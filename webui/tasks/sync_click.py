#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
参数化同步点击任务 — 统一承担原 单线程/双线程/多机同步 三个编排脚本

由 Web UI 调度器以子进程方式拉起，向 stdout 输出 JSONL 结构化事件。
事件契约见 docs/WEBUI_开发方案.md 第 6 章。

用法:
  python webui/tasks/sync_click.py [选项]
    --devices 10.56.82.72:5555,10.56.82.134:5555   目标设备(逗号分隔)，留空自动检测
    --device-mode all|first                        自动检测策略 (默认 all)
    --button-id <resourceId>                       监听按钮 resource-id
    --filter-texts 结束调度,...                     按钮文本命中则不点击
    --poll-interval 0.5                            轮询间隔(秒)
    --click-cooldown 2.0                           点击后冷却(秒)
    --connect-retries 3                            连接重试次数
    --require-all                                  需全部设备就绪才同步点击
    --mock                                         演示模式: 无需真机，模拟设备与点击
    --mock-devices 2                               演示模式模拟设备数

优雅停止: 调度器写停止文件 (WEBUI_STOP_FILE 环境变量) → 主循环检测到后抛出
KeyboardInterrupt → 输出 summary 与 phase:stopped 后正常退出 (退出码 0)；
无控制台宿主环境下 CTRL_BREAK_EVENT 不可靠，故以停止文件为主通道。
"""

import argparse
import os
import random
import sys
import threading
import time
from pathlib import Path

# 使 `from webui.engine import events` 可用 (子进程 cwd=仓库根，此处再保险加一次路径)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webui.engine import events  # noqa: E402


# ============================================================
# 设备抽象: MockImpl (演示模式) 与 RealImpl (真机) 实现同一接口
# ============================================================

class MockImpl:
    """模拟设备: 周期性出现目标按钮，偶发掉线，无需真机"""

    def __init__(self, addr: str, filter_texts: list[str]):
        self.addr = addr
        self.filter_texts = filter_texts
        self.online = True
        self._visible = False
        self._text = ""
        self._next_change = time.monotonic() + random.uniform(1.0, 4.0)
        self._offline_until = 0.0

    def connect(self, retries: int) -> bool:
        time.sleep(random.uniform(0.1, 0.3))   # 模拟连接耗时
        events.log(f"✅ {self.addr} 连接成功（演示模式模拟设备）")
        return True

    def try_reconnect(self) -> bool:
        if time.monotonic() < self._offline_until:
            return False
        self.online = True
        return True

    def probe(self) -> tuple[bool, str]:
        """返回 (按钮是否存在, 按钮文本)"""
        now = time.monotonic()
        if now >= self._next_change:
            if self._visible:
                self._visible = False
                self._text = ""
                self._next_change = now + random.uniform(1.0, 4.0)
            else:
                self._visible = True
                # 约 12% 概率出现被过滤文本，用于演示过滤逻辑
                self._text = "结束调度" if random.random() < 0.12 else "确定"
                self._next_change = now + random.uniform(2.0, 6.0)
        # 偶发掉线演示 (平均每台约 100 秒一次，持续 4~6 秒)
        if self.online and random.random() < 0.005:
            self.online = False
            self._offline_until = now + random.uniform(4.0, 6.0)
            raise ConnectionError("模拟设备掉线")
        return self._visible, self._text

    def click(self) -> tuple[int, int, int]:
        """模拟点击，返回 (x, y, cost_ms)，约 5% 概率失败"""
        x, y = random.randint(400, 680), random.randint(1000, 1300)
        cost = random.randint(40, 130)
        time.sleep(cost / 1000.0)
        if random.random() < 0.05:
            raise RuntimeError("模拟点击失败（演示）")
        return x, y, cost


class RealImpl:
    """真机设备: uiautomator2 实现，逻辑与原编排脚本保持一致"""

    def __init__(self, addr: str, button_id: str):
        self.addr = addr
        self.button_id = button_id
        self.online = False
        self.d = None

    def connect(self, retries: int) -> bool:
        import uiautomator2 as u2
        for i in range(retries):
            try:
                events.log(f"⏳ 正在连接 {self.addr} ...（第{i + 1}次）")
                self.d = u2.connect(self.addr)
                self.online = True
                events.log(f"✅ {self.addr} 连接成功")
                return True
            except Exception as e:
                events.log(f"❌ {self.addr} 连接失败({i + 1}/{retries}): {e}", "warn")
                if i < retries - 1:
                    time.sleep(5)
        return False

    def try_reconnect(self) -> bool:
        import uiautomator2 as u2
        try:
            self.d = u2.connect(self.addr)
            # 快速探活: 任意调用成功即认为连接恢复
            self.d.info
            self.online = True
            return True
        except Exception:
            return False

    def probe(self) -> tuple[bool, str]:
        btn = self.d(resourceId=self.button_id)
        has = btn.exists()
        text = ""
        if has:
            try:
                text = btn.get_text(timeout=0.3).strip()
            except Exception:
                text = ""
        return has, text

    def click(self) -> tuple[int, int, int]:
        t0 = time.monotonic()
        btn = self.d(resourceId=self.button_id)
        x, y = btn.center()
        self.d.click(x, y)
        return x, y, int((time.monotonic() - t0) * 1000)


class Slot:
    """设备槽位: 状态去抖 + 就绪时间戳记录"""

    def __init__(self, addr: str, name: str, impl):
        self.addr = addr
        self.name = name
        self.impl = impl
        self.online = False
        self.btn_ready = False
        self.text = ""
        self.first_ready_ts: float | None = None
        self.last_reconnect_try = 0.0
        self._last_state: tuple | None = None

    def emit_if_changed(self) -> None:
        """状态三元组变化才发事件 (去抖，避免每轮刷屏)"""
        state = (self.online, self.btn_ready, self.text)
        if state != self._last_state:
            self._last_state = state
            events.device(self.addr, self.name, self.online, self.btn_ready, self.text)


# ============================================================
# 主流程
# ============================================================

def resolve_addrs(args) -> list[str]:
    """确定目标设备地址列表"""
    if args.devices:
        return [a.strip() for a in args.devices.split(",") if a.strip()]
    if args.mock:
        return [f"MOCK-{i + 1}" for i in range(args.mock_devices)]
    # 自动检测 (逻辑同 多机同步任务编排.py:get_all_device_addrs，改用列表参数避免 shell 解析)
    import subprocess
    try:
        result = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=10)
        output = result.stdout
    except Exception:
        output = ""
    addrs = []
    for line in output.strip().splitlines():
        if "device" in line and not line.startswith("List"):
            addrs.append(line.split()[0])
    if args.device_mode == "first":
        return addrs[:1]
    return addrs


def build_slots(args) -> list[Slot]:
    slots: list[Slot] = []
    addrs = resolve_addrs(args)
    if not addrs:
        events.error("未检测到任何ADB设备，请先建立 ADB 连接（可用「无线 ADB 连接」任务）", fatal=True)
        return []
    events.log(f"📱 检测到 {len(addrs)} 台设备：{addrs}")

    filter_texts = [t.strip() for t in args.filter_texts.split(",") if t.strip()] if args.filter_texts else []

    for i, addr in enumerate(addrs):
        name = f"机器人{i + 1}({addr})"
        if args.mock:
            impl = MockImpl(addr, filter_texts)
        else:
            impl = RealImpl(addr, args.button_id)
        slots.append(Slot(addr, name, impl))
    return slots


def click_worker(slot: Slot, seq: int, results: list) -> None:
    """线程化点击 (与原脚本一致: 每台一个线程并行，尽可能同一时刻点击)"""
    try:
        x, y, cost = slot.impl.click()
        events.click(seq, slot.addr, True, x=x, y=y, cost_ms=cost)
        events.log(f"✅ {slot.name} 点击成功")
        results.append(True)
    except Exception as e:
        events.click(seq, slot.addr, False, err=str(e))
        events.log(f"❌ {slot.name} 点击失败: {e}", "error")
        results.append(False)


def main() -> int:
    parser = argparse.ArgumentParser(description="参数化同步点击任务")
    parser.add_argument("--devices", default="", help="目标设备，逗号分隔；留空自动检测")
    parser.add_argument("--device-mode", choices=["all", "first"], default="all")
    parser.add_argument("--button-id", default="com.keenon.solutionindustry:id/tv_start")
    parser.add_argument("--filter-texts", default="", help="过滤文本，逗号分隔")
    parser.add_argument("--poll-interval", type=float, default=0.5)
    parser.add_argument("--click-cooldown", type=float, default=2.0)
    parser.add_argument("--connect-retries", type=int, default=3)
    parser.add_argument("--require-all", action="store_true", help="需全部设备就绪才点击")
    parser.add_argument("--mock", action="store_true", help="演示模式: 无需真机")
    parser.add_argument("--mock-devices", type=int, default=2, help="演示模式模拟设备数")
    args = parser.parse_args()

    events.init()
    filter_texts = [t.strip() for t in args.filter_texts.split(",") if t.strip()]

    events.phase("connecting")
    mode_desc = "演示模式（模拟设备）" if args.mock else "真机模式"
    strategy = "全部就绪后同步点击" if args.require_all else "按钮出现即点击"
    events.log(f"🚀 同步点击任务启动 | {mode_desc} | 策略: {strategy}")
    events.log(f"过滤条件：按钮文本不能是 {filter_texts or '(无)'}")

    slots = build_slots(args)
    connected = []
    for slot in slots:
        if slot.impl.connect(args.connect_retries):
            slot.online = True
            slot.emit_if_changed()
            connected.append(slot)
        else:
            events.error(f"{slot.addr} 连接失败，将跳过该设备", addr=slot.addr)
            slot.emit_if_changed()

    if not connected:
        events.error("所有设备连接均失败，任务退出", fatal=True)
        events.phase("failed")
        return 1

    events.phase("ready")
    n = len(connected)
    events.log(f"🚀 {n} 台机器人已就绪")
    events.phase("running")

    seq = 0
    batches = clicks_ok = clicks_fail = 0
    wait_sum = 0
    t_start = time.monotonic()
    stop_file = os.environ.get("WEBUI_STOP_FILE") or ""

    try:
        while True:
            # 协作式优雅停止: 调度器写停止文件 → 走 KeyboardInterrupt 分支输出汇总后退出
            if stop_file and os.path.exists(stop_file):
                raise KeyboardInterrupt
            # ---- 逐台探测按钮状态 ----
            for slot in connected:
                if not slot.online:
                    # 掉线设备: 节流重连 (每 5 秒尝试一次)
                    now = time.monotonic()
                    if now - slot.last_reconnect_try >= 5.0:
                        slot.last_reconnect_try = now
                        if slot.impl.try_reconnect():
                            slot.online = True
                            events.log(f"🔄 {slot.name} 重新连接成功")
                            slot.emit_if_changed()
                    continue
                try:
                    has, text = slot.impl.probe()
                    slot.btn_ready = has and text not in filter_texts
                    slot.text = text
                except Exception as e:
                    # 探测异常视为掉线，任务继续跑 (相比原脚本的强化点)
                    slot.online = False
                    slot.btn_ready = False
                    slot.first_ready_ts = None
                    events.error(f"{slot.name} 掉线: {e}，将自动重连", addr=slot.addr)
                    slot.emit_if_changed()
                    continue
                slot.emit_if_changed()

            # ---- 维护各设备首次就绪时间戳 (用于同步等待耗时) ----
            now = time.monotonic()
            for slot in connected:
                if slot.online and slot.btn_ready and slot.first_ready_ts is None:
                    slot.first_ready_ts = now
                elif not (slot.online and slot.btn_ready):
                    slot.first_ready_ts = None

            # ---- 判定触发条件 ----
            ready_slots = [s for s in connected if s.online and s.btn_ready]
            if args.require_all:
                all_online = all(s.online for s in connected)
                trigger = all_online and len(ready_slots) == len(connected)
            else:
                trigger = bool(ready_slots)

            if trigger and ready_slots:
                seq += 1
                batches += 1
                ready_ts = [s.first_ready_ts for s in ready_slots if s.first_ready_ts]
                wait_ms = int((max(ready_ts) - min(ready_ts)) * 1000) if len(ready_ts) > 1 else 0
                wait_sum += wait_ms
                events.batch(seq, len(ready_slots), wait_ms)
                events.log(f"🎯 {len(ready_slots)} 台机器人全部到位，准备同步点击...")

                threads = []
                results: list = []
                for slot in ready_slots:
                    t = threading.Thread(target=click_worker, args=(slot, seq, results))
                    threads.append(t)
                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=3)

                ok_count = sum(1 for r in results if r)
                clicks_ok += ok_count
                clicks_fail += len(results) - ok_count
                events.log(f"✅ 本轮 {len(results)} 台并行点击操作完成 "
                           f"(成功 {ok_count} / 失败 {len(results) - ok_count})")
                for slot in ready_slots:
                    slot.first_ready_ts = None
                time.sleep(args.click_cooldown)

            time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        duration = round(time.monotonic() - t_start, 1)
        events.summary(
            batches=batches, clicks_ok=clicks_ok, clicks_fail=clicks_fail,
            avg_wait_ms=round(wait_sum / batches) if batches else 0,
            duration_s=duration,
        )
        events.phase("stopped")
        events.log("🛑 脚本停止运行")
        return 0


if __name__ == "__main__":
    sys.exit(main())

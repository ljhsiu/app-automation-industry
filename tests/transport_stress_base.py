#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搬运功能压测 v3.0 — 双机分布式共享逻辑 (基类)
技术栈: Python + uiautomator2 + ADB

本模块提供 TransportStressTest 基类，由各机器入口脚本调用:
  - transport_stress_test_machine1.py  → machine_id="machine1"
  - transport_stress_test_machine2.py  → machine_id="machine2"

设备 IP 统一从根 config.yaml 的 transport_machines 段读取，
各脚本通过 machine_id 区分连接目标，日志/报告均带机器标识，
避免双机并行运行时产生混淆。
"""

import os, sys, time, yaml, re, threading
from pathlib import Path
from datetime import datetime
from typing import Optional

import uiautomator2 as u2

# 多线程打印锁 (双机同步版脚本并行输出时保证日志不交错)
_PRINT_LOCK = threading.Lock()

# 修复 Windows GBK 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent

# ==================== 配置 ====================

def load_cfg():
    """加载根 config.yaml，返回完整配置字典"""
    cfg_path = PROJECT_ROOT.parent / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as f:
        full = yaml.safe_load(f)
    return full

# ==================== UI 辅助 ====================

def wait_text(d: u2.Device, text: str, timeout: int = 15) -> bool:
    return d(text=text).wait(timeout=timeout)

def click_text(d: u2.Device, text: str, timeout: int = 15) -> bool:
    e = d(text=text)
    if e.wait(timeout=timeout):
        e.click()
        return True
    return False

def click_rid(d: u2.Device, rid: str, timeout: int = 15) -> bool:
    e = d(resourceId=rid)
    if e.wait(timeout=timeout):
        e.click()
        return True
    return False

def has_text(d: u2.Device, text: str) -> bool:
    return d(text=text).exists

def get_tv_msg(d: u2.Device) -> str:
    try:
        return d(resourceId="com.keenon.solutionindustry:id/tv_msg").get_text()
    except Exception:
        return ""

# ==================== 主控制器 ====================

class TransportStressTest:
    """
    搬运压测主控制器 (双机分布式版)。

    通过 machine_id 从 config.yaml 的 transport_machines 段读取对应机器的
    IP/端口/包名等连接信息，确保两个独立脚本分别连接到各自目标设备。
    所有日志输出与报告均携带机器标识 (self.tag)。
    """

    def __init__(self, machine_id: str = "machine1"):
        self.machine_id = machine_id

        full = load_cfg()
        machines = full.get("transport_machines", {})
        if machine_id not in machines:
            raise ValueError(
                f"config.yaml 中未找到 transport_machines.{machine_id}，"
                f"可用: {list(machines.keys())}"
            )

        # —— 设备连接信息（按 machine_id 区分目标机器）——
        self.dev = machines[machine_id]
        self.machine_name = self.dev.get("name", machine_id)
        # 日志/报告中的机器归属标识
        self.tag = f"{self.machine_name}[{machine_id}]"
        self.ip = self.dev["ip"]
        self.port = self.dev["port"]
        self.addr = f"{self.ip}:{self.port}"

        # —— 压测业务配置 ——
        self.cfg = full["transport_stress"]
        self.ui = self.cfg["ui_elements"]

        self.d: Optional[u2.Device] = None

        # 动态点位与货架：按 machine_id 读取，优先 machines.<id>，回退 transport 默认
        transport = self.cfg["transport"]
        m_override = self.cfg.get("machines", {}).get(machine_id, {})
        self.primary = {**transport["primary"], **m_override.get("primary", {})}
        self.shelf_spec_cfg = m_override.get("shelf_spec", transport.get("shelf_spec"))
        p = self.primary
        self.sp = p["start_point"]  # 当前起点
        self.ep = p["end_point"]    # 当前终点

        # 失败熔断
        self.consecutive_fails = 0
        self.max_fails = self.cfg["fail"]["max_consecutive_failures"]

        self.results = []
        self.started = None

    # ==================== 日志 ====================

    def _log(self, msg: str = ""):
        """统一日志输出，前缀携带机器归属标识，避免双机混淆。"""
        if msg:
            print(f"[{self.tag}] {msg}")
        else:
            print()

    # ==================== 设备 ====================

    def connect(self) -> bool:
        import subprocess
        r = subprocess.run(f"adb connect {self.addr}", shell=True, capture_output=True, text=True)
        if "connected" in r.stdout.lower() or "already" in r.stdout.lower():
            try:
                self.d = u2.connect(self.addr)
                self._log(f"[连接] [OK] {self.addr} | sdk={self.d.info.get('sdkInt')}")
                return True
            except Exception as e:
                self._log(f"[连接] [FAIL] u2: {e}")
        else:
            self._log(f"[连接] [FAIL] adb 未连接: {r.stdout.strip()}")
        return False

    def get_battery(self) -> int:
        try:
            lvl = self.d.info.get("battery", {}).get("level")
            if lvl is not None:
                return lvl
        except Exception:
            pass
        try:
            out = self.d.shell(["dumpsys", "battery"]).output
            m = re.search(r"level:\s*(\d+)", out)
            if m: return int(m.group(1))
        except Exception:
            pass
        return -1

    def on_home(self) -> bool:
        try:
            cur = self.d.app_current()
            return "industryhomeactivity" in str(cur.get("activity", "")).lower()
        except Exception:
            return has_text(self.d, "搬运")

    # ==================== 步骤实现 ====================

    def step_start_app(self) -> bool:
        self._log("[1] 启动App...")
        self.d.app_stop(self.dev["package"])
        time.sleep(1)
        self.d.app_start(self.dev["package"], self.dev["home_activity"])
        time.sleep(3)
        ok = wait_text(self.d, self.ui["home"]["transport_btn"]["text"], timeout=20)
        self._log(f"    {'[OK]' if ok else '[FAIL]'} 首页")
        return ok

    def step_click_transport(self) -> bool:
        self._log("[2] 进入搬运页...")
        t = self.ui["home"]["transport_btn"]["text"]
        if not click_text(self.d, t):
            click_rid(self.d, self.ui["home"]["transport_btn"]["resourceId"])
        time.sleep(1)
        ok = wait_text(self.d, "开始工作", timeout=10)
        self._log(f"    {'[OK]' if ok else '[FAIL]'}")
        return ok

    def _pick_point(self, label_text: str, name: str, label: str) -> bool:
        """通用点位选择 - 自动切换楼层"""
        self._log(f"[{label}] 选择 {name}...")
        ot = self.cfg["stress"]["operation_timeout"]
        pp = self.ui["point_picker"]

        # 点击标签行(如"起点"、"终点")
        if not click_text(self.d, label_text, timeout=ot):
            self._log(f"    [FAIL] 找不到「{label_text}」行")
            return False
        time.sleep(1)

        # 等浮窗
        if not wait_text(self.d, pp["dialog_check_text"], timeout=10):
            self._log(f"    [FAIL] 浮窗未出现")
            return False

        # 楼层切换（按当前机器配置，默认1楼不切换）
        floor = self.primary.get("floor", 1)
        if floor > 1:
            floor_text = f"楼层{floor}"
            self._log(f"    切换: {floor_text}...")
            if not click_text(self.d, floor_text, timeout=5):
                self._log(f"    [WARN] 找不到 {floor_text}")
            time.sleep(0.5)

        # 选点位
        if not click_text(self.d, name, timeout=ot):
            self._log(f"    [FAIL] 找不到 {name}")
            return False
        time.sleep(0.5)

        # 确定
        click_text(self.d, pp["confirm_text"], timeout=ot)
        time.sleep(1)
        self._log(f"    [OK] {name}")
        return True

    def step_shelf_spec(self) -> bool:
        shelf_cfg = self.shelf_spec_cfg
        if not shelf_cfg:
            self._log("[货架] 跳过")
            return True
        ot = self.cfg["stress"]["operation_timeout"]
        sp = self.ui["shelf_picker"]
        shelf_name = shelf_cfg["name"]
        shelf_desc = shelf_cfg["description"]
        shelf_idx = shelf_cfg["instance"]
        self._log(f"[货架] 选择: {shelf_name} ({shelf_desc})...")

        if not click_text(self.d, "货架规格", timeout=ot):
            self._log("    [FAIL] 找不到货架规格")
            return False
        time.sleep(1)

        if not wait_text(self.d, sp["dialog_title"], timeout=10):
            self._log("    [FAIL] 浮窗未出现")
            return False

        # 点击目标 swipe_layout
        sl = self.d(resourceId=sp["swipe_layout_resourceId"], instance=shelf_idx)
        if not sl.exists:
            self._log(f"    [FAIL] 找不到货架选项 #{shelf_idx}")
            return False
        sl.click()
        time.sleep(0.5)

        # 验证: iv_checked.selected=true 在目标 swipe 内
        xml = self.d.dump_hierarchy()
        swipes = list(re.finditer(
            rf'resource-id="{re.escape(sp["swipe_layout_resourceId"])}"[^>]*',
            xml))
        ck = False
        if len(swipes) > shelf_idx:
            s = swipes[shelf_idx].start()
            e = swipes[shelf_idx + 1].start() if shelf_idx + 1 < len(swipes) else len(xml)
            ck = 'selected="true"' in xml[s:e]
        if ck:
            self._log(f"    [OK] 已选中 {shelf_name}")
        else:
            self._log(f"    [WARN] 选中状态未验证, 继续...")

        click_text(self.d, sp["confirm_text"], timeout=ot)
        time.sleep(1)
        return True

    def step_start_work(self) -> bool:
        self._log("[开始] 点击开始工作...")
        sw = self.ui["transport_page"]["start_work_btn"]
        if not click_text(self.d, sw["text"], timeout=self.cfg["stress"]["operation_timeout"]):
            click_rid(self.d, sw["resourceId"])
        time.sleep(2)
        ok = wait_text(self.d, "运行中", timeout=10)
        self._log(f"    {'[OK] 任务已下发' if ok else '[FAIL] 下发失败'}")
        return ok

    def poll_task(self) -> dict:
        """轮询 tv_msg 直到终态或超时"""
        tc = self.cfg["transport"]["task"]
        interval = tc["poll_interval"]
        timeout = tc["max_wait_seconds"]
        success = tc["success_text"]
        fail = tc["fail_text"]
        rp = self.ui["running_page"]

        self._log(f"[轮询] 每{interval}s检测，超时{timeout}s...")
        t0 = time.time()
        last_msg = ""

        while time.time() - t0 < timeout:
            try:
                msg = get_tv_msg(self.d)
            except Exception:
                time.sleep(interval)
                continue

            if msg and msg != last_msg:
                elapsed = int(time.time() - t0)
                self._log(f"  [{elapsed}s] {msg}")
                last_msg = msg

            # 检测终端状态
            if success in msg:
                self._log(f"  [OK] 任务成功！")
                return {"status": "success", "elapsed": int(time.time() - t0)}
            if fail in msg:
                self._log(f"  [FAIL] 匹配失败！")
                return {"status": "match_fail", "elapsed": int(time.time() - t0)}

            # 兜底: 如果底部「确定」按钮出现(running页面的 view_commit)，说明已到达终态
            if has_text(self.d, rp["exit_btn_text"]):
                # 再次读取确认
                msg2 = get_tv_msg(self.d)
                if success in msg2:
                    self._log(f"  [OK] 任务成功(按钮检测)！")
                    return {"status": "success", "elapsed": int(time.time() - t0)}
                if fail in msg2:
                    self._log(f"  [FAIL] 匹配失败(按钮检测)！")
                    return {"status": "match_fail", "elapsed": int(time.time() - t0)}
                # 按钮出现但 tv_msg 未匹配，打印原始值
                self._log(f"  [WARN] 确定按钮已出现，tv_msg=「{msg2}」")

            time.sleep(interval)

        self._log(f"  [FAIL] 超时 ({timeout}s)")
        return {"status": "timeout", "elapsed": timeout}

    def step_exit_running(self) -> bool:
        """点击确定退出运行页"""
        rp = self.ui["running_page"]
        ok = click_text(self.d, rp["exit_btn_text"], timeout=10) or \
             click_rid(self.d, rp["exit_btn_resourceId"], timeout=10)
        time.sleep(2)
        return ok

    def step_go_home(self) -> bool:
        for _ in range(6):
            if self.on_home():
                return True
            self.d.press("back")
            time.sleep(1)
        return self.on_home()

    def screenshot(self, tag: str):
        d = PROJECT_ROOT / self.cfg["screenshot"]["result_dir"]
        d.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        # 文件名带 machine_id，避免双机截图互相覆盖
        fp = str(d / f"{self.machine_id}_{tag}_{ts}.png")
        try:
            self.d.screenshot(fp)
        except Exception:
            pass

    # ==================== 单轮 ====================

    def run_one(self, cycle: int) -> dict:
        t0 = time.time()
        res = {"cycle": cycle, "machine": self.machine_id, "sp": self.sp, "ep": self.ep,
               "start": datetime.now().strftime("%H:%M:%S"), "status": "failed", "error": None, "elapsed": 0}

        def _ret():
            res["elapsed"] = int(time.time() - t0)
            return res

        try:
            # 确保在首页
            if not self.on_home():
                if not self.step_start_app():
                    res["error"] = "无法到首页"; return _ret()
            else:
                self._log("[首页] 已在首页")

            if not self.step_click_transport():
                res["error"] = "进搬运页失败"; return _ret()

            if not self._pick_point("起点", self.sp, "起点"):
                res["error"] = f"选起点{self.sp}失败"; return _ret()

            if not self._pick_point("终点", self.ep, "终点"):
                res["error"] = f"选终点{self.ep}失败"; return _ret()

            if not self.step_shelf_spec():
                res["error"] = "选货架失败"; return _ret()

            if not self.step_start_work():
                res["error"] = "开始工作失败"; return _ret()

            poll = self.poll_task()
            self.screenshot(f"cycle{cycle}_{poll['status']}")

            if poll["status"] == "success":
                res["status"] = "success"
            else:
                res["status"] = "failed"
                res["error"] = poll["status"]

            self.step_exit_running()
            self.step_go_home()

        except Exception as e:
            res["status"] = "failed"
            res["error"] = str(e)

        return _ret()

    # ==================== 主流程 ====================

    def run(self):
        self._log("=" * 60)
        self._log(f"  搬运压测 v3.0 (双机分布式) | 设备: {self.addr}")
        self._log(f"  机器归属: {self.tag}")
        self._log(f"  初始点位: {self.sp}→{self.ep}")
        self._log(f"  熔断: 连续{self.max_fails}次失败则停止")
        self._log("=" * 60)

        if not self.connect():
            self._log("[FAIL] 连接失败"); return

        # 电量检查
        if self.cfg["battery_protect"]["enabled"]:
            bat = self.get_battery()
            if bat < self.cfg["battery_protect"]["low_threshold"]:
                self._log(f"[FAIL] 电量 {bat}% 不足, 退出"); return
            self._log(f"[电量] {bat}%")

        self.started = datetime.now()
        cycle = 0
        target_cycles = self.cfg["stress"]["cycles"]

        while cycle < target_cycles:
            cycle += 1
            self._log(f"\n{'─' * 40}")
            self._log(f"  -> 第 {cycle} 轮: {self.sp} → {self.ep}")
            self._log(f"{'─' * 40}")

            res = self.run_one(cycle)
            self.results.append(res)

            icon = "[OK]" if res["status"] == "success" else "[FAIL]"
            self._log(f"  {icon} 第{cycle}轮: {res['status']} | {res['elapsed']}s")

            if res["status"] == "success":
                self.consecutive_fails = 0
                # 成功 → 互换点位
                self.sp, self.ep = self.ep, self.sp
                self._log(f"  -> 下一轮互换: {self.sp} → {self.ep}")
            else:
                self.consecutive_fails += 1
                self._log(f"  [WARN] 连续失败: {self.consecutive_fails}/{self.max_fails}")
                if self.consecutive_fails >= self.max_fails:
                    self._log(f"\n  [STOP] 连续失败 {self.consecutive_fails} 次 ≥ {self.max_fails}，停止压测！")
                    break

            if cycle < target_cycles:
                w = self.cfg["stress"]["interval_between_cycles"]
                self._log(f"  [等待] {w}s ...")
                time.sleep(w)

        self._report()

    def _report(self):
        d = PROJECT_ROOT / self.cfg["report"]["output_dir"]
        d.mkdir(parents=True, exist_ok=True)
        ts = self.started.strftime("%Y%m%d_%H%M%S")
        # 报告文件名带 machine_id，避免双机报告互相覆盖
        base_name = self.cfg["report"]["filename_template"].format(timestamp=ts)
        fp = d / f"{self.machine_id}_{base_name}"

        t = len(self.results)
        ok = sum(1 for r in self.results if r["status"] == "success")
        fail = sum(1 for r in self.results if r["status"] == "failed")
        rate = f"{ok/t*100:.1f}%" if t > 0 else "N/A"

        lines = [
            "# 搬运功能压测报告 (双机分布式)", "",
            "## 基本信息", "",
            f"| 项目 | 值 |", f"|------|-----|",
            f"| 机器归属 | {self.tag} |",
            f"| machine_id | {self.machine_id} |",
            f"| 时间 | {self.started.strftime('%Y-%m-%d %H:%M:%S')} → {datetime.now().strftime('%H:%M:%S')} |",
            f"| 设备 | {self.addr} |",
            f"| 技术栈 | Python + uiautomator2 + ADB |",
            f"| 初始点位 | {self.primary['start_point']} → {self.primary['end_point']} |",
            f"| 总轮数 | {t} | 成功 | {ok} | 失败 | {fail} | 成功率 | {rate} |",
            f"| 熔断 | 连续{self.max_fails}次失败停止 | 实际连续失败 | {self.consecutive_fails} |",
            "",
            "## 详细", "",
            "| 轮 | 起点 | 终点 | 开始 | 耗时 | 结果 |", "|--|--|--|--|--|--|",
        ]
        for r in self.results:
            icon = "[OK]" if r["status"] == "success" else "[FAIL]"
            lines.append(f"| {r['cycle']} | {r['sp']} | {r['ep']} | {r['start']} | {r['elapsed']}s | {icon} {r['status']} |")

        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self._log(f"\n{'=' * 60}")
        self._log(f"  [REPORT] 报告: {fp}")
        self._log(f"  [OK] {ok} | [FAIL] {fail} | [RATE] {rate}")
        self._log(f"{'=' * 60}")

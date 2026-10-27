#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搬运功能压测 v3.1 — 双机同步版 (单脚本同时控制2台设备)
技术栈: Python + uiautomator2 + ADB + threading
用法: python transport_stress_dual.py

特性:
  1. 单脚本用双线程同时控制 machine1 / machine2 两台设备，无需分别启动两个脚本。
  2. 双机同步屏障:
     - 同步点A (到达): 两台机器都轮询到任务终态(到达目标点)后，才各自点击「确定(到达)」。
     - 同步点B (起步): 两台都回到首页就绪后，才同时进入下一轮，保证双机同时起步。
  3. 设备 IP / 楼层点位 / 货架 均从 config.yaml 统一读取，按 machine_id 区分。
  4. 日志带机器归属标识且线程安全；报告为双机合并报告。
  5. 屏障带超时(barrier_timeout)，单机故障不会永久卡死另一台。

依赖: transport_stress_base.py (复用 TransportStressTest 的全部步骤方法)
"""

import sys, time, threading
from pathlib import Path
from datetime import datetime

# 修复 Windows GBK 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transport_stress_base import TransportStressTest, load_cfg, PROJECT_ROOT, _PRINT_LOCK


# ==================== 同步原语 ====================

class SyncPoint:
    """
    N 方就绪同步点 (基于 Event 实现，比 threading.Barrier 更可控)。
    - arrive_and_wait(): 本方到达并等待其余方，返回 True 表示全员就绪；
      返回 False 表示超时或被 abort(对方故障)，调用方应继续执行避免死等。
    - abort(): 主动解除等待，唤醒所有等待方。
    每个 cycle 使用独立的 SyncPoint 实例，互不影响。
    """

    def __init__(self, n: int = 2, timeout: float = 600):
        self.n = n
        self.timeout = timeout
        self._count = 0
        self._lock = threading.Lock()
        self._event = threading.Event()
        self._aborted = False

    def arrive_and_wait(self) -> bool:
        with self._lock:
            if self._aborted:
                return False
            self._count += 1
            if self._count >= self.n:
                self._event.set()
        ok = self._event.wait(timeout=self.timeout)
        return bool(ok) and not self._aborted

    def abort(self):
        with self._lock:
            self._aborted = True
            self._event.set()


# ==================== 双机同步控制器 ====================

class DualTransportController:
    """单脚本同时控制两台设备，关键节点双机同步。"""

    def __init__(self):
        full = load_cfg()
        self.cfg = full["transport_stress"]
        ds = self.cfg.get("dual_sync", {})
        self.barrier_timeout = ds.get("barrier_timeout", 600)

        self.cycles = self.cfg["stress"]["cycles"]
        self.interval = self.cfg["stress"]["interval_between_cycles"]
        self.max_fails = self.cfg["fail"]["max_consecutive_failures"]

        self.m1 = TransportStressTest("machine1")
        self.m2 = TransportStressTest("machine2")

        self.results = {"machine1": [], "machine2": []}
        self.cf = {"machine1": 0, "machine2": 0}  # 连续失败计数
        self.started = None

    # ---------- 日志 ----------

    def _log(self, msg: str = ""):
        with _PRINT_LOCK:
            if msg:
                print(f"[双机] {msg}")
            else:
                print()

    # ---------- 连接 ----------

    def _connect_one(self, t: TransportStressTest, ok_box: dict):
        ok_box[t.machine_id] = t.connect()

    def _connect_all(self) -> bool:
        ok_box = {}
        c1 = threading.Thread(target=self._connect_one, args=(self.m1, ok_box))
        c2 = threading.Thread(target=self._connect_one, args=(self.m2, ok_box))
        c1.start(); c2.start(); c1.join(); c2.join()
        return ok_box.get("machine1") and ok_box.get("machine2")

    def _battery_one(self, t: TransportStressTest):
        try:
            bat = t.get_battery()
            if bat >= 0:
                t._log(f"[电量] {bat}%")
        except Exception:
            pass

    # ---------- 单轮 (单台 worker) ----------

    def _prepare_and_start(self, t: TransportStressTest, cycle: int) -> bool:
        """阶段1: 首页→搬运页→选起点→选终点→选货架→开始工作。成功返回True。"""
        if not t.on_home():
            if not t.step_start_app():
                return False
        else:
            t._log("[首页] 已在首页")
        if not t.step_click_transport():
            return False
        if not t._pick_point("起点", t.sp, "起点"):
            return False
        if not t._pick_point("终点", t.ep, "终点"):
            return False
        if not t.step_shelf_spec():
            return False
        if not t.step_start_work():
            return False
        return True

    def _finish_home(self, t: TransportStressTest, home_sync: SyncPoint):
        """阶段4: 回首页 + 同步点B(双机就绪同时起步)。"""
        try:
            t.step_go_home()
        except Exception as e:
            t._log(f"[WARN] 回首页异常: {e}")
        t._log("[同步] 等待双机均回首页，准备同时起步...")
        ok = home_sync.arrive_and_wait()
        if ok:
            t._log("[同步] 双机均已就绪，准备同时起步")
        else:
            t._log("[同步][WARN] 等待回首页超时/中断，继续")

    def _run_cycle(self, t: TransportStressTest, cycle: int,
                   poll_sync: SyncPoint, home_sync: SyncPoint, out: dict):
        """单台机器执行一轮（线程入口），结果写入 out。"""
        t0 = time.time()
        res = {"cycle": cycle, "machine": t.machine_id, "sp": t.sp, "ep": t.ep,
               "start": datetime.now().strftime("%H:%M:%S"),
               "status": "failed", "error": None, "elapsed": 0}

        try:
            # 阶段1: 准备 + 下发任务
            if not self._prepare_and_start(t, cycle):
                res["error"] = "准备/下发任务失败"
                t._log("[FAIL] 准备阶段失败，跳过本轮任务")
                poll_sync.abort()          # 通知对方不必再等本机轮询
                self._finish_home(t, home_sync)
                res["elapsed"] = int(time.time() - t0)
                out.update(res)
                return

            # 阶段2: 轮询任务直到终态
            poll = t.poll_task()
            t.screenshot(f"cycle{cycle}_{poll['status']}")
            if poll["status"] == "success":
                res["status"] = "success"
            else:
                res["status"] = "failed"
                res["error"] = poll["status"]

            # ===== 同步点A: 等双机均到达目标点 =====
            t._log("[同步] 等待双机均到达目标点...")
            ok = poll_sync.arrive_and_wait()
            if ok:
                t._log("[同步] 双机均已到达，点击确定(到达)")
            else:
                t._log("[同步][WARN] 等待超时或对方中断，仍尝试点击确定")

            # 阶段3: 点击确定退出运行页(到达)
            t.step_exit_running()

        except Exception as e:
            res["status"] = "failed"
            res["error"] = str(e)
            t._log(f"[异常] {e}")
            poll_sync.abort()

        # 阶段4: 回首页 + 同步点B
        self._finish_home(t, home_sync)
        res["elapsed"] = int(time.time() - t0)
        out.update(res)

    # ---------- 主流程 ----------

    def run(self):
        self._log("=" * 60)
        self._log("  搬运压测 v3.1 (双机同步版) — 单脚本同时控制2台设备")
        self._log(f"  机器1: {self.m1.tag} | {self.m1.addr} | {self.m1.sp}→{self.m1.ep}")
        self._log(f"  机器2: {self.m2.tag} | {self.m2.addr} | {self.m2.sp}→{self.m2.ep}")
        self._log(f"  循环: {self.cycles} | 间隔: {self.interval}s | 屏障超时: {self.barrier_timeout}s")
        self._log(f"  熔断: 连续{self.max_fails}次失败则停止")
        self._log("  同步: 双机均到达才点确定，均回首页才同时起步")
        self._log("=" * 60)

        # 并行连接
        self._log("[连接] 并行连接两台设备...")
        if not self._connect_all():
            self._log("[FAIL] 任一设备连接失败，退出")
            return

        # 电量检查
        if self.cfg["battery_protect"]["enabled"]:
            b1 = threading.Thread(target=self._battery_one, args=(self.m1,))
            b2 = threading.Thread(target=self._battery_one, args=(self.m2,))
            b1.start(); b2.start(); b1.join(); b2.join()

        self.started = datetime.now()
        stopped = False

        for cycle in range(1, self.cycles + 1):
            self._log(f"\n{'━' * 50}")
            self._log(f"  >>> 第 {cycle} 轮 (双机同步) <<<")
            self._log(f"  机器1: {self.m1.sp} → {self.m1.ep}")
            self._log(f"  机器2: {self.m2.sp} → {self.m2.ep}")
            self._log(f"{'━' * 50}")

            # 每轮独立的同步点
            poll_sync = SyncPoint(2, self.barrier_timeout)
            home_sync = SyncPoint(2, self.barrier_timeout)

            r1, r2 = {}, {}
            th1 = threading.Thread(target=self._run_cycle,
                                   args=(self.m1, cycle, poll_sync, home_sync, r1))
            th2 = threading.Thread(target=self._run_cycle,
                                   args=(self.m2, cycle, poll_sync, home_sync, r2))
            th1.start(); th2.start(); th1.join(); th2.join()

            self.results["machine1"].append(r1)
            self.results["machine2"].append(r2)

            # 结果汇总 + 熔断判定
            for t, res, key in [(self.m1, r1, "machine1"), (self.m2, r2, "machine2")]:
                icon = "[OK]" if res["status"] == "success" else "[FAIL]"
                t._log(f"  {icon} 第{cycle}轮: {res['status']} | {res['elapsed']}s")
                if res["status"] == "success":
                    self.cf[key] = 0
                    t.sp, t.ep = t.ep, t.sp  # 成功→互换点位
                    t._log(f"  -> 下一轮互换: {t.sp} → {t.ep}")
                else:
                    self.cf[key] += 1
                    t._log(f"  [WARN] 连续失败: {self.cf[key]}/{self.max_fails}")
                    if self.cf[key] >= self.max_fails:
                        self._log(f"\n  [STOP] {t.tag} 连续失败 {self.cf[key]} 次，停止双机压测！")
                        stopped = True

            if stopped:
                break

            # 双机都已就绪，统一等待后同时起步下一轮
            if cycle < self.cycles:
                self._log(f"[双机] 双机就绪，等待 {self.interval}s 后同时起步下一轮...")
                time.sleep(self.interval)

        self._report()

    # ---------- 报告 ----------

    def _report(self):
        d = PROJECT_ROOT / self.cfg["report"]["output_dir"]
        d.mkdir(parents=True, exist_ok=True)
        ts = self.started.strftime("%Y%m%d_%H%M%S")
        fp = d / f"dual_transport_stress_report_{ts}.md"

        def _stat(rs):
            t = len(rs)
            ok = sum(1 for r in rs if r["status"] == "success")
            fail = sum(1 for r in rs if r["status"] == "failed")
            rate = f"{ok/t*100:.1f}%" if t > 0 else "N/A"
            return t, ok, fail, rate

        t1, ok1, fail1, rate1 = _stat(self.results["machine1"])
        t2, ok2, fail2, rate2 = _stat(self.results["machine2"])

        lines = [
            "# 搬运功能压测报告 (双机同步版 v3.1)", "",
            "## 基本信息", "",
            "| 项目 | 机器1 | 机器2 |", "|------|------|------|",
            f"| 机器标识 | {self.m1.tag} | {self.m2.tag} |",
            f"| 设备地址 | {self.m1.addr} | {self.m2.addr} |",
            f"| machine_id | machine1 | machine2 |",
            f"| 初始点位 | {self.m1.primary['start_point']}→{self.m1.primary['end_point']} | {self.m2.primary['start_point']}→{self.m2.primary['end_point']} |",
            f"| 总轮数 | {t1} | {t2} |",
            f"| 成功 | {ok1} | {ok2} |",
            f"| 失败 | {fail1} | {fail2} |",
            f"| 成功率 | {rate1} | {rate2} |",
            f"| 连续失败 | {self.cf['machine1']} | {self.cf['machine2']} |",
            f"| 时间 | {self.started.strftime('%Y-%m-%d %H:%M:%S')} → {datetime.now().strftime('%H:%M:%S')} | |",
            f"| 技术栈 | Python + uiautomator2 + ADB + threading | |",
            f"| 同步屏障超时 | {self.barrier_timeout}s | |",
            "",
            "## 机器1 详细", "",
            "| 轮 | 起点 | 终点 | 开始 | 耗时 | 结果 |", "|--|--|--|--|--|--|",
        ]
        for r in self.results["machine1"]:
            icon = "[OK]" if r["status"] == "success" else "[FAIL]"
            lines.append(f"| {r['cycle']} | {r['sp']} | {r['ep']} | {r['start']} | {r['elapsed']}s | {icon} {r['status']} |")

        lines += ["", "## 机器2 详细", "",
                  "| 轮 | 起点 | 终点 | 开始 | 耗时 | 结果 |", "|--|--|--|--|--|--|"]
        for r in self.results["machine2"]:
            icon = "[OK]" if r["status"] == "success" else "[FAIL]"
            lines.append(f"| {r['cycle']} | {r['sp']} | {r['ep']} | {r['start']} | {r['elapsed']}s | {icon} {r['status']} |")

        with open(fp, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))

        self._log(f"\n{'=' * 60}")
        self._log(f"  [REPORT] 双机报告: {fp}")
        self._log(f"  机器1 [OK]{ok1} [FAIL]{fail1} [RATE]{rate1}")
        self._log(f"  机器2 [OK]{ok2} [FAIL]{fail2} [RATE]{rate2}")
        self._log(f"{'=' * 60}")


if __name__ == "__main__":
    DualTransportController().run()

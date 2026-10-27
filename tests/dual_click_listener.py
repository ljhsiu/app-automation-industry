#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
双机确定按钮同步监听 v2.0 (项目格式适配版)
技术栈: Python + uiautomator2 + ADB
用法: python dual_click_listener.py

特性:
  1. 从 config.yaml 读取两台机器 IP (transport_machines)，统一管理。
  2. 启动时先执行 adb connect，再 u2.connect，确保设备可达。
  3. 两台机器同时监听确定按钮，都出现才同时点击(双机同步到达)。
  4. 过滤「结束调度」等不需要点击的按钮文本(从 config 读取 filter_texts)。
  5. 所有日志带机器归属标识 [机器1[machine1]] / [机器2[machine2]]，双机不混淆。
  6. 按钮 resource-id、过滤文本、轮询间隔均从 config.yaml 读取，修改无需改代码。

依赖: transport_stress_base.py (复用 load_cfg / _PRINT_LOCK)
"""

import sys, time, threading, subprocess
from pathlib import Path

# 修复 Windows GBK 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 项目根目录
PROJECT_ROOT = Path(__file__).resolve().parent

sys.path.insert(0, str(PROJECT_ROOT))
from transport_stress_base import load_cfg, _PRINT_LOCK


def adb_connect(addr: str) -> bool:
    """执行 adb connect + u2.connect，返回 (是否成功, u2.Device 或 None)"""
    r = subprocess.run(f"adb connect {addr}", shell=True, capture_output=True, text=True)
    connected = "connected" in r.stdout.lower() or "already" in r.stdout.lower()
    if not connected:
        with _PRINT_LOCK:
            print(f"[ADB] 连接失败: {addr} -> {r.stdout.strip()}")
        return False, None

    import uiautomator2 as u2
    try:
        d = u2.connect(addr)
        with _PRINT_LOCK:
            print(f"[ADB] 连接成功: {addr} | sdk={d.info.get('sdkInt')}")
        return True, d
    except Exception as e:
        with _PRINT_LOCK:
            print(f"[ADB] u2.connect 失败: {addr} -> {e}")
        return False, None


class MachineWatcher:
    """单台机器的按钮监听器"""

    def __init__(self, machine_id: str, cfg: dict):
        self.machine_id = machine_id
        dev_cfg = cfg["transport_machines"][machine_id]
        self.machine_name = dev_cfg.get("name", machine_id)
        self.tag = f"{self.machine_name}[{machine_id}]"
        self.addr = f"{dev_cfg['ip']}:{dev_cfg['port']}"

        # dual_click 配置
        dc = cfg["dual_click"]
        self.button_rid = dc["button_resourceId"]
        self.filter_texts = dc.get("filter_texts", [])
        self.poll_interval = dc.get("poll_interval", 1)
        self.click_delay = dc.get("click_delay", 2)

        self.d = None  # u2.Device，connect 后赋值

    def _log(self, msg: str = ""):
        with _PRINT_LOCK:
            if msg:
                print(f"[{self.tag}] {msg}")
            else:
                print()

    def connect(self) -> bool:
        """ADB + u2 连接"""
        ok, d = adb_connect(self.addr)
        if ok:
            self.d = d
            return True
        return False


def main():
    cfg = load_cfg()
    machines_cfg = cfg.get("transport_machines", {})
    if "machine1" not in machines_cfg or "machine2" not in machines_cfg:
        print("[FAIL] config.yaml 缺少 transport_machines.machine1 或 machine2")
        return

    m1 = MachineWatcher("machine1", cfg)
    m2 = MachineWatcher("machine2", cfg)

    print("=" * 50)
    print("  双机确定按钮同步监听 v2.0")
    print(f"  机器1: {m1.tag} @ {m1.addr}")
    print(f"  机器2: {m2.tag} @ {m2.addr}")
    print(f"  监听按钮: {cfg['dual_click']['button_resourceId']}")
    print(f"  过滤文本: {m1.filter_texts}")
    print(f"  两台同时出现确定按钮才点击")
    print("=" * 50)

    # ADB 连接
    if not m1.connect():
        m1._log("[FAIL] 连接失败，退出")
        return
    if not m2.connect():
        m2._log("[FAIL] 连接失败，退出")
        return

    try:
        while True:
            r1_btn = m1.d(resourceId=m1.button_rid)
            r2_btn = m2.d(resourceId=m2.button_rid)

            r1_has = r1_btn.exists()
            r2_has = r2_btn.exists()

            if r1_has and r2_has:
                # 获取按钮文本，过滤不需要点击的
                r1_text = (r1_btn.get_text() or "").strip()
                r2_text = (r2_btn.get_text() or "").strip()

                # 如果任一按钮文本在过滤列表中，跳过
                skip = False
                for ft in m1.filter_texts:
                    if ft in r1_text or ft in r2_text:
                        m1._log(f"检测到「{ft}」(R1:{r1_text}, R2:{r2_text})，跳过点击")
                        m2._log(f"检测到「{ft}」(R1:{r1_text}, R2:{r2_text})，跳过点击")
                        skip = True
                        break

                if skip:
                    time.sleep(10)
                    continue

                # 正常点击
                m1._log("两台机器同时到位，点击确定")
                m2._log("两台机器同时到位，点击确定")

                try:
                    r1_btn.click()
                except Exception:
                    m1._log("按钮已消失，跳过点击")
                try:
                    r2_btn.click()
                except Exception:
                    m2._log("按钮已消失，跳过点击")

                time.sleep(m1.click_delay)

            time.sleep(m1.poll_interval)

    except KeyboardInterrupt:
        m1._log("脚本停止运行")
        m2._log("脚本停止运行")


if __name__ == "__main__":
    main()

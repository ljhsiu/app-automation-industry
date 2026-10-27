#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搬运功能压测 v3.0 — 机器2 独立入口脚本 (分布式)
技术栈: Python + uiautomator2 + ADB
用法: python transport_stress_test_machine2.py

说明:
  - 本脚本固定以 machine_id="machine2" 运行，单独控制机器2。
  - 目标设备 IP 从根 config.yaml 的 transport_machines.machine2 读取。
  - 日志与报告均带「机器2[machine2]」标识，避免与机器1混淆。

  ★ 推荐使用双机同步版 (单脚本同时控制2台设备，含到达同步与同时起步):
        python transport_stress_dual.py
    如需两台机器各自独立运行(无同步)，分别执行 machine1.py 与本脚本。
"""

import sys
from pathlib import Path

# 修复 Windows GBK 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

# 确保能 import 同目录下的基类模块
sys.path.insert(0, str(Path(__file__).resolve().parent))

from transport_stress_base import TransportStressTest


if __name__ == "__main__":
    print("=" * 60)
    print("  >>> 启动搬运压测 — 机器2 (machine2) <<<")
    print("  >>> 目标 IP 见 config.yaml → transport_machines.machine2 <<<")
    print("=" * 60)
    TransportStressTest(machine_id="machine2").run()

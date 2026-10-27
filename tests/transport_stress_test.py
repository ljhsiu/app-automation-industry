#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
搬运功能压测 v3.0 — 兼容入口 (已迁移为双机分布式)

⚠️ 已弃用: 本脚本为向后兼容保留，实际逻辑已迁移至:
    - transport_stress_test_machine1.py  (机器1)
    - transport_stress_test_machine2.py  (机器2)

双机分布式用法:
    机器1:  python transport_stress_test_machine1.py
    机器2:  python transport_stress_test_machine2.py

本脚本默认以 machine1 运行，等价于 transport_stress_test_machine1.py。
原用法: python transport_stress_test.py
"""

import sys
from pathlib import Path

# 修复 Windows GBK 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from transport_stress_base import TransportStressTest


if __name__ == "__main__":
    print("[提示] 本脚本已迁移为双机分布式，默认按 machine1 运行。")
    print("[提示] 机器1 请用: python transport_stress_test_machine1.py")
    print("[提示] 机器2 请用: python transport_stress_test_machine2.py")
    print("-" * 60)
    TransportStressTest(machine_id="machine1").run()

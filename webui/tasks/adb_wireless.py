#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
无线 ADB 连接任务 — 移植自 点击编排任务/adbconnect.py

改造点 (设计文档 7.7 节):
1. 删除原脚本 3 处阻塞式 input() (Web 调用会永久挂死)
2. 新增 --serial: 多台 USB 设备时可指定目标 (原脚本只取第一台)
3. print → events 结构化输出

用法:
  python webui/tasks/adb_wireless.py [--serial <usb_serial>] [--port 5555] [--mock]
"""

import argparse
import os
import re
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from webui.engine import events  # noqa: E402

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


def run_adb(cmd_list: list[str], timeout: float = 15.0) -> tuple[str, str]:
    """执行 adb 命令，返回 (stdout, stderr)"""
    try:
        r = subprocess.run(cmd_list, capture_output=True, text=True, timeout=timeout,
                           creationflags=_CREATE_NO_WINDOW, encoding="utf-8", errors="replace")
        return (r.stdout or "").strip(), (r.stderr or "").strip()
    except Exception as e:
        return "", str(e)


def find_usb_serial(specified: str = "") -> str | None:
    """查找 USB 有线设备 (serial 不含冒号)；specified 非空时直接采用"""
    if specified:
        return specified
    out, _ = run_adb(["adb", "devices"])
    for line in out.splitlines():
        if "device" in line and not line.startswith("List"):
            serial = line.split()[0]
            if ":" not in serial:   # 跳过无线设备
                return serial
    return None


def get_device_ip(serial: str) -> str | None:
    """获取设备 wlan0 的 IP 地址"""
    out, _ = run_adb(["adb", "-s", serial, "shell", "ip", "addr", "show", "wlan0"])
    match = re.search(r"inet (\d+\.\d+\.\d+\.\d+)/\d+", out)
    return match.group(1) if match else None


def main() -> int:
    parser = argparse.ArgumentParser(description="无线 ADB 连接")
    parser.add_argument("--serial", default="", help="USB 设备序列号，留空自动取第一台")
    parser.add_argument("--port", type=int, default=5555)
    parser.add_argument("--mock", action="store_true", help="演示模式: 无需真机")
    args = parser.parse_args()

    events.init()
    events.phase("connecting")
    events.log("=" * 30)
    events.log("  一键开启无线ADB" + ("（演示模式）" if args.mock else ""))
    events.log("=" * 30)

    # ---- 演示模式: 模拟完整流程，不触碰真实 adb ----
    if args.mock:
        events.log("[成功] 找到USB设备：MOCKUSB001（模拟）")
        time.sleep(0.5)
        ip = "192.168.8.197"
        events.log(f"[信息] 设备IP地址：{ip}（模拟）")
        events.log(f"[信息] 正在切换至TCP模式（端口{args.port}）...")
        time.sleep(0.5)
        events.log("[信息] 等待3秒让ADB服务重启...")
        time.sleep(1.0)
        events.log(f"[信息] 正在连接 {ip}:{args.port} ...")
        time.sleep(0.5)
        events.log(f"connected to {ip}:{args.port}（模拟）")
        events.log("✅ 配置完成！演示模式下未执行真实 adb 命令。")
        events.phase("stopped")
        return 0

    # ---- 真实流程 ----
    serial = find_usb_serial(args.serial.strip())
    if not serial:
        events.error("未检测到任何USB有线连接的设备！请确认USB线已插好，且机器已开启USB调试。", fatal=True)
        events.phase("failed")
        return 1
    events.log(f"[成功] 找到USB设备：{serial}")

    ip = get_device_ip(serial)
    if not ip:
        events.error("获取IP失败，请确认机器人已连接Wi-Fi！", fatal=True)
        events.phase("failed")
        return 1
    events.log(f"[信息] 设备IP地址：{ip}")

    events.log(f"[信息] 正在切换至TCP模式（端口{args.port}）...")
    run_adb(["adb", "-s", serial, "tcpip", str(args.port)])

    events.log("[信息] 等待3秒让ADB服务重启...")
    time.sleep(3)

    events.log(f"[信息] 正在连接 {ip}:{args.port} ...")
    conn_out, conn_err = run_adb(["adb", "connect", f"{ip}:{args.port}"])
    if conn_out:
        events.log(conn_out)
    if conn_err:
        events.log(conn_err, "warn")

    if "connected" in (conn_out or "").lower():
        events.log("=" * 30)
        events.log(f"✅ 配置完成！现在可以拔掉USB线了。无线地址: {ip}:{args.port}")
        events.log("=" * 30)
        events.phase("stopped")
        return 0

    events.error("无线连接未成功，请检查网络后重试", fatal=True)
    events.phase("failed")
    return 1


if __name__ == "__main__":
    sys.exit(main())

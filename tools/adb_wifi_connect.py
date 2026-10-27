"""
ADB 无线连接工具
通过统一 config.yaml 或 USB 连接后启用无线连接
"""
import subprocess
import time
import sys
import re
import yaml
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ---------- 从统一 config.yaml 读取设备列表 ----------

def _load_cfg():
    with open(PROJECT_ROOT / "config.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)

def get_device_config(device_name=None):
    cfg = _load_cfg()
    devices = cfg.get("devices", {})
    default_name = cfg.get("current_device", "default")
    name = device_name or default_name
    return devices.get(name, devices.get("default", {}))

def get_device_address(device_name=None):
    config = get_device_config(device_name)
    ip = config.get("ip")
    port = config.get("port", 5555)
    if ip:
        return f"{ip}:{port}"
    return None

def list_devices():
    cfg = _load_cfg()
    devices = cfg.get("devices", {})
    current = cfg.get("current_device", "default")
    print("\n已配置的设备：")
    print("-" * 50)
    for name, config in devices.items():
        marker = " <- 当前" if name == current else ""
        print(f"[{name}] {config['name']}{marker}")
        print(f"       IP: {config['ip']}")
        if config.get('serial'):
            print(f"       Serial: {config['serial']}")
    print("-" * 50)


# ---------- ADB 连接 --------------

def get_devices_usb():
    result = subprocess.run(["adb", "devices"], capture_output=True, text=True)
    devices = []
    for line in result.stdout.strip().split("\n")[1:]:
        if line.strip():
            parts = line.split("\t")
            if len(parts) >= 2:
                serial, status = parts[0].strip(), parts[1].strip()
                if status == "device":
                    devices.append(serial)
    return devices

def get_device_ip(serial):
    result = subprocess.run(f"adb -s {serial} shell ip route".split(), capture_output=True, text=True)
    if result.stdout:
        match = re.search(r"(\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    result = subprocess.run(f"adb -s {serial} shell netcfg".split(), capture_output=True, text=True)
    if result.stdout:
        match = re.search(r"wlan0\s+(\d+\.\d+\.\d+\.\d+)", result.stdout)
        if match:
            return match.group(1)
    return None

def enable_tcpip(serial):
    print(f"正在为设备 {serial} 启用 TCP/IP 模式...")
    result = subprocess.run(f"adb -s {serial} tcpip 5555".split(), capture_output=True, text=True)
    if "restarting" in result.stdout or result.returncode == 0:
        print("已启用 TCP/IP 模式，端口 5555")
        return True
    print(f"[FAIL] 启用失败: {result.stderr}")
    return False

def connect_wifi(serial_or_ip):
    print(f"正在连接到 {serial_or_ip}...")
    result = subprocess.run(f"adb connect {serial_or_ip}".split(), capture_output=True, text=True)
    print(result.stdout.strip())
    return "connected" in result.stdout.lower()

def disconnect_device(serial_or_ip):
    print(f"正在断开 {serial_or_ip}...")
    result = subprocess.run(f"adb disconnect {serial_or_ip}".split(), capture_output=True, text=True)
    print(result.stdout.strip())

def connect_by_config(device_name=None):
    config = get_device_config(device_name)
    device_ip = config.get("ip")
    device_name_display = config.get("name")
    if not device_ip:
        print("[FAIL] 配置中未找到设备 IP")
        return None
    print(f"\n{'='*50}")
    print(f"连接设备: {device_name_display}")
    print(f"IP 地址: {device_ip}")
    print(f"{'='*50}")
    target = f"{device_ip}:5555"
    if connect_wifi(target):
        print(f"\n成功连接到 {device_name_display}")
        return target
    print("连接失败，5s后重试...")
    time.sleep(5)
    if connect_wifi(target):
        print("\n重试成功！")
        return target
    print(f"\n[FAIL] 连接 {device_ip} 失败")
    return None

def main():
    import argparse
    cfg = _load_cfg()
    parser = argparse.ArgumentParser(description="ADB 无线连接工具")
    parser.add_argument("-c", "--config", default=cfg.get("current_device", "default"), help="配置中的设备名称")
    parser.add_argument("-i", "--ip", help="设备 IP 地址")
    parser.add_argument("-s", "--serial", help="USB 设备序列号")
    parser.add_argument("-d", "--disconnect", help="断开指定连接")
    parser.add_argument("-l", "--list", action="store_true", help="列出已配置的设备")
    parser.add_argument("--port", default="5555", help="TCP 端口")
    args = parser.parse_args()

    if args.list:
        list_devices()
        return
    if args.disconnect:
        disconnect_device(args.disconnect)
        return
    if args.ip:
        target = f"{args.ip}:{args.port}"
        if connect_wifi(target):
            print(f"\n成功连接到 {target}")
        else:
            print(f"\n[FAIL] 连接 {target} 失败")
            sys.exit(1)
        return
    if args.config:
        result = connect_by_config(args.config)
        if result:
            print(f"\n后续连接可用: adb connect {result}")
        else:
            sys.exit(1)
        return
    print("""
用法:
  1. 通过配置连接:    python adb_wifi_connect.py
  2. 指定配置设备:    python adb_wifi_connect.py -c default
  3. 通过 IP 直连:    python adb_wifi_connect.py -i 192.168.0.100
  4. USB 启用无线:    python adb_wifi_connect.py -s <序列号>
  5. 断开连接:        python adb_wifi_connect.py -d <地址>
  6. 列出设备:        python adb_wifi_connect.py -l
    """)

if __name__ == "__main__":
    main()

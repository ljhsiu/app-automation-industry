import subprocess
import re
import time
import sys


def run_adb(cmd, serial=None):
    target = f" -s {serial}" if serial else ""
    full_cmd = f"adb{target} {cmd}"
    result = subprocess.run(full_cmd, shell=True, capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip()


def main():
    print("=" * 30)
    print("  一键开启无线ADB")
    print("=" * 30)

    # 1. 获取设备列表，只找纯USB设备（不带冒号）
    output, _ = run_adb("devices")
    lines = output.splitlines()
    usb_serial = None

    for line in lines:
        if "device" in line and not line.startswith("List"):
            serial = line.split()[0]
            if ":" not in serial:  # 关键：跳过无线设备
                usb_serial = serial
                break

    if not usb_serial:
        print("[错误] 未检测到任何USB有线连接的设备！")
        print("请确认USB线已插好，且机器已开启USB调试。")
        input("按任意键退出...")
        sys.exit(1)

    print(f"[成功] 找到USB设备：{usb_serial}")

    # 2. 获取IP地址
    ip_output, _ = run_adb("shell ip addr show wlan0", usb_serial)
    match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)/\d+', ip_output)
    if not match:
        print("[错误] 获取IP失败，请确认机器人已连接Wi-Fi！")
        input("按任意键退出...")
        sys.exit(1)

    ip = match.group(1)
    print(f"[信息] 设备IP地址：{ip}")

    # 3. 切换TCP模式
    print("[信息] 正在切换至TCP模式（端口5555）...")
    run_adb("tcpip 5555", usb_serial)

    # 4. 等待ADB重启
    print("[信息] 等待3秒让ADB服务重启...")
    time.sleep(3)

    # 5. 无线连接
    print(f"[信息] 正在连接 {ip}:5555 ...")
    conn_out, _ = run_adb(f"connect {ip}:5555")
    print(conn_out)

    print("=" * 30)
    print("  配置完成！现在可以拔掉USB线了。")
    print("=" * 30)
    input("按任意键退出...")


if __name__ == "__main__":
    main()


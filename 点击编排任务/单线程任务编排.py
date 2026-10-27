import uiautomator2 as u2
import time
import sys
import subprocess

BUTTON_ID = "com.keenon.solutionindustry:id/tv_start"


def get_first_device_addr():
    """通过 adb devices 获取第一个已连接设备的地址"""
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    for line in lines:
        if "device" in line and not line.startswith("List"):
            addr = line.split()[0]
            print(f"📱 检测到设备：{addr}")
            return addr
    return None


def safe_connect(addr, retries=3, delay=5):
    for i in range(retries):
        try:
            device = u2.connect(addr)
            print(f"✅ {addr} 连接成功")
            return device
        except Exception as e:
            print(f"❌ {addr} 连接失败({i+1}/{retries}): {e}")
            if i < retries - 1:
                time.sleep(delay)
    print(f"🛑 {addr} 连接失败，请先运行 adbconnect.py 建立无线连接！")
    sys.exit(1)


ROBOT_ADDR = get_first_device_addr()
if not ROBOT_ADDR:
    print("🛑 未检测到任何ADB设备，请先运行 adbconnect.py 建立连接！")
    sys.exit(1)

d = safe_connect(ROBOT_ADDR)

print("单机器人监听，按钮出现即点击")
print("过滤条件：按钮文本不能是'结束调度'")

try:
    while True:
        btn = d(resourceId=BUTTON_ID)

        if btn.exists():
            try:
                text = btn.get_text(timeout=0.3).strip()
            except:
                text = ""

            if text == "结束调度":
                print("⚠️ 检测到'结束调度'，跳过本轮")
                time.sleep(0.5)
                continue

            print("🎯 检测到目标按钮，准备点击...")

            try:
                x, y = btn.center()
            except:
                print("⚠️ 获取坐标失败，跳过本轮")
                time.sleep(0.5)
                continue

            try:
                d.click(x, y)
                print(f"✅ 点击成功 (坐标: {x}, {y})")
            except Exception as e:
                print(f"❌ 点击失败: {e}")

            time.sleep(2)

        time.sleep(0.5)

except KeyboardInterrupt:
    print("🛑 脚本停止运行")

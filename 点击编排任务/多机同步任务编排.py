import uiautomator2 as u2
import time
import threading
import sys
import subprocess

BUTTON_ID = "com.keenon.solutionindustry:id/tv_start"


def get_all_device_addrs():
    """通过 adb devices 获取所有已连接设备的地址"""
    result = subprocess.run("adb devices", shell=True, capture_output=True, text=True)
    lines = result.stdout.strip().splitlines()
    addrs = []
    for line in lines:
        if "device" in line and not line.startswith("List"):
            addr = line.split()[0]
            addrs.append(addr)
    return addrs


def safe_connect(addr, retries=3, delay=10):
    """尝试连接设备，失败返回 None（不退出脚本）"""
    for i in range(retries):
        try:
            print(f"⏳ 正在连接 {addr} ...（第{i+1}次）")
            device = u2.connect(addr)
            print(f"✅ {addr} 连接成功")
            return device
        except Exception as e:
            print(f"❌ {addr} 连接失败({i+1}/{retries}): {e}")
            if i < retries - 1:
                time.sleep(delay)
    print(f"⚠️ {addr} 连接失败，将跳过该设备")
    return None


def click_at_position(device, x, y, name):
    try:
        device.click(x, y)
        print(f"✅ {name} 点击成功")
        return True
    except Exception as e:
        print(f"❌ {name} 点击失败: {e}")
        return False


# ---- 自动检测并连接所有设备 ----
addrs = get_all_device_addrs()
if not addrs:
    print("🛑 未检测到任何ADB设备，请先运行 adbconnect.py 建立连接！")
    sys.exit(1)

print(f"📱 检测到 {len(addrs)} 台设备：{addrs}")

devices = []
for i, addr in enumerate(addrs):
    d = safe_connect(addr)
    if d is not None:
        devices.append((d, f"机器人{i+1}({addr})"))

if not devices:
    print("🛑 所有设备连接均失败，脚本退出！")
    sys.exit(1)

n = len(devices)
print(f"🚀 {n} 台机器人已就绪，必须全部出现确认按钮后才同步点击")
print("过滤条件：按钮文本不能是'结束调度'")

try:
    while True:
        # ---- 检查所有设备上按钮状态 ----
        btn_info = []  # [(device, name, btn_obj, has_btn, text)]
        all_ready = True

        for d, name in devices:
            btn = d(resourceId=BUTTON_ID)
            has_btn = btn.exists()
            try:
                text = btn.get_text(timeout=0.3).strip() if has_btn else ""
            except:
                text = ""
            btn_info.append((d, name, btn, has_btn, text))

            # 如果某台设备按钮不存在或文本是"结束调度"，就不满足全部就绪
            if not has_btn or text == "结束调度":
                all_ready = False

        # ---- 全部就绪：所有按钮都出现且都不是"结束调度" ----
        if all_ready:
            print(f"🎯 {n} 台机器人全部到位，准备同步点击...")

            # 获取所有坐标
            coords = []
            coord_ok = True
            for d, name, btn, has_btn, text in btn_info:
                try:
                    x, y = btn.center()
                    coords.append((x, y))
                except:
                    print(f"⚠️ {name} 获取坐标失败，跳过本轮")
                    coord_ok = False
                    break

            if coord_ok:
                # 用线程并行点击，保证尽可能同一时刻点击
                threads = []
                for i, (d, name, btn, _, _) in enumerate(btn_info):
                    x, y = coords[i]
                    t = threading.Thread(target=click_at_position, args=(d, x, y, name))
                    threads.append(t)

                for t in threads:
                    t.start()
                for t in threads:
                    t.join(timeout=3)

                print(f"✅ 本轮 {n} 台并行点击操作完成")
                time.sleep(2)
            else:
                time.sleep(0.5)
                continue

        time.sleep(0.5)

except KeyboardInterrupt:
    print("🛑 脚本停止运行")

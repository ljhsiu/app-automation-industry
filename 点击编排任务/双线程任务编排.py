import uiautomator2 as u2
import time
import threading
import sys

BUTTON_ID = "com.keenon.solutionindustry:id/tv_start"
ROBOT1_ADDR = "10.56.82.72:5555"
ROBOT2_ADDR = "10.56.82.134:5555"

def safe_connect(ip, retries=3, delay=5):
    for i in range(retries):
        try:
            device = u2.connect(ip)
            print(f"✅ {ip} 连接成功")
            return device
        except Exception as e:
            print(f"❌ {ip} 连接失败({i+1}/{retries}): {e}")
            if i < retries - 1:
                time.sleep(delay)
    print(f"🛑 {ip} 连接失败，请先运行 adbconnect.py 建立无线连接！")
    sys.exit(1)

d1 = safe_connect(ROBOT1_ADDR)
d2 = safe_connect(ROBOT2_ADDR)

def click_at_position(device, x, y, robot_name):
    try:
        device.click(x, y)
        print(f"✅ {robot_name} 点击成功")
        return True
    except Exception as e:
        print(f"❌ {robot_name} 点击失败: {e}")
        return False

print("双机器人监听，确保两台同时出发")
print("过滤条件：按钮文本不能是‘结束调度’")

try:
    while True:
        r1_btn = d1(resourceId=BUTTON_ID)
        r2_btn = d2(resourceId=BUTTON_ID)

        r1_has = r1_btn.exists()
        r2_has = r2_btn.exists()

        # ---- 获取文本（带异常捕获） ----
        try:
            r1_text = r1_btn.get_text(timeout=0.3).strip() if r1_has else ""
        except:
            r1_text = ""
        try:
            r2_text = r2_btn.get_text(timeout=0.3).strip() if r2_has else ""
        except:
            r2_text = ""

        # 条件：两个按钮都在 且 都不是“结束调度”
        if r1_has and r2_has and r1_text != "结束调度" and r2_text != "结束调度":
            print("🎯 两台机器人同时到位，准备同时点击...")

            # 获取坐标（也可能会失败，但此时存在性已经确认，可用try兜底）
            try:
                x1, y1 = r1_btn.center()
                x2, y2 = r2_btn.center()
            except:
                print("⚠️ 获取坐标失败，跳过本轮")
                time.sleep(0.5)
                continue

            t1 = threading.Thread(target=click_at_position, args=(d1, x1, y1, "机器人1"))
            t2 = threading.Thread(target=click_at_position, args=(d2, x2, y2, "机器人2"))

            t1.start()
            t2.start()

            t1.join(timeout=3)
            t2.join(timeout=3)

            print("✅ 本轮并行点击操作完成")
            time.sleep(2)

        time.sleep(0.5)

except KeyboardInterrupt:
    print("🛑 脚本停止运行")
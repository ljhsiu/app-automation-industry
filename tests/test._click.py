import uiautomator2 as u2
import time

BUTTON_ID = "com.keenon.solutionindustry:id/tv_start"
ROBOT1_IP = "172.20.10.4"
ROBOT2_IP = "172.20.10.14"

d1 = u2.connect(ROBOT1_IP)
d2 = u2.connect(ROBOT2_IP)

print("双机器人监听，两台同时出现确定按钮才点击")
print("注意：如果按钮文本为‘结束调度’，则不会点击")

try:
    while True:
        r1_btn = d1(resourceId=BUTTON_ID)
        r2_btn = d2(resourceId=BUTTON_ID)

        r1_has = r1_btn.exists()
        r2_has = r2_btn.exists()

        if r1_has and r2_has:
            # ---- 新增逻辑：获取按钮文本，过滤“结束调度” ----
            # 使用 get_text() 获取文本，并去除首尾空格避免干扰
            r1_text = r1_btn.get_text().strip() if r1_btn.get_text() else ""
            r2_text = r2_btn.get_text().strip() if r2_btn.get_text() else ""

            # 如果任一按钮文本是“结束调度”，则跳过本次点击，继续等待
            if r1_text == "结束调度" or r2_text == "结束调度":
                print(f"检测到‘结束调度’按钮（R1:{r1_text}, R2:{r2_text}），跳过点击")
                time.sleep(10)  # 稍微休息一下避免疯狂循环
                continue       # 直接进入下一次循环，不执行点击

            # ---- 原有逻辑：正常点击 ----
            print("两台机器人同时到位，自动点击确定")
            # 分别捕获单台点击异常，一台消失不影响另一台
            try:
                r1_btn.click()
            except Exception:
                print("机器1按钮已消失，跳过点击")
            try:
                r2_btn.click()
            except Exception:
                print("机器2按钮已消失，跳过点击")
            time.sleep(2)
        time.sleep(1)
except KeyboardInterrupt:
    print("脚本停止运行")
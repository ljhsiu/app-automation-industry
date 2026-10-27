"""
下桩返回原点脚本
从充电桩下桩并返回到首页
"""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pages.home_page import HomePage


class UndockScript:
    """下桩返回原点脚本"""

    PACKAGE = "com.keenon.solutionindustry"
    CHECK_INTERVAL = 10
    WAIT_AFTER_EXIT = 60
    MAX_WAIT_HOME = 120

    def __init__(self, driver):
        self.driver = driver
        self.home_page = HomePage(driver)

    def is_on_charging_station(self):
        charging_text = self.driver(text="正在充电")
        current = self.driver.app_current()
        is_charge_activity = "charge" in str(current.get('activity', '')).lower()
        is_on_station = charging_text.exists or is_charge_activity
        if is_on_station:
            print("检测到在桩上充电状态")
        else:
            print(f"[WARN] 未检测到桩上充电 (Activity: {current.get('activity')})")
        return is_on_station

    def click_exit_charging(self):
        print("点击'点击屏幕可退出充电'呼出弹窗...")
        exit_hint = self.driver(text="点击屏幕可退出充电")
        if not exit_hint.exists:
            print("[FAIL] 未找到'点击屏幕可退出充电'")
            return False
        bounds = exit_hint.info.get('bounds', {})
        if not bounds:
            print("[FAIL] 无法获取元素位置")
            return False
        x = (bounds['left'] + bounds['right']) // 2
        y = (bounds['top'] + bounds['bottom']) // 2
        print(f"点击 ({x}, {y})...")
        self.driver.click(x, y)
        time.sleep(2)
        print("已呼出弹窗")
        return True

    def click_confirm(self):
        print("点击'结束'按钮...")
        confirm_btn = self.driver(text="结束")
        if confirm_btn.exists:
            confirm_btn.click()
            print("已点击结束")
            time.sleep(2)
            return True
        else:
            print("[FAIL] 未找到'结束'按钮")
            return False

    def is_exiting_charging(self):
        exiting_text = self.driver(text="正在退出充电")
        is_exiting = exiting_text.exists
        if is_exiting:
            print("检测到'正在退出充电'状态")
        else:
            print("[WARN] 未检测到'正在退出充电'")
        return is_exiting

    def wait_for_exit_complete(self, timeout=60):
        print(f"\n等待退出充电完成（最多 {timeout}s）...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if not self.is_exiting_charging():
                print("退出充电完成")
                return True
            time.sleep(2)
        print(f"[FAIL] 等待 {timeout}s 后仍未退出充电")
        return False

    def wait_for_home_page(self, timeout=None):
        if timeout is None:
            timeout = self.MAX_WAIT_HOME
        print(f"\n等待回到首页（最多 {timeout}s）...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.home_page.is_at_home_page():
                elapsed = int(time.time() - start_time)
                print(f"已回到首页（耗时 {elapsed}s）")
                return True
            elapsed = int(time.time() - start_time)
            remaining = timeout - elapsed
            print(f"  等待中... ({elapsed}/{timeout}s, 剩余 {remaining}s)")
            time.sleep(self.CHECK_INTERVAL)
        print(f"[FAIL] 等待 {timeout}s 后仍未回到首页")
        return False

    def run(self):
        print("\n" + "=" * 50)
        print("开始下桩返回原点流程")
        print("=" * 50)

        if not self.is_on_charging_station():
            print("\n[WARN] 不在桩上充电，无需下桩")
            return True
        if not self.click_exit_charging():
            print("[FAIL] 无法点击退出充电")
            return False
        if not self.click_confirm():
            print("[FAIL] 无法点击确认")
            return False
        if not self.wait_for_exit_complete():
            print("[FAIL] 退出充电失败")
            return False

        print(f"\n等待 {self.WAIT_AFTER_EXIT}s 后检查首页...")
        time.sleep(self.WAIT_AFTER_EXIT)

        if self.wait_for_home_page():
            print("\n" + "=" * 50)
            print("下桩返回原点成功！")
            print("=" * 50)
            return True
        else:
            print("\n" + "=" * 50)
            print("[WARN] 下桩完成但未回到首页")
            print("=" * 50)
            return False

    def run_with_retry(self, max_retries=3):
        for attempt in range(1, max_retries + 1):
            print(f"\n{'='*40}")
            print(f"下桩尝试 {attempt}/{max_retries}")
            print(f"{'='*40}")
            if self.run():
                return True
            if attempt < max_retries:
                print(f"\n[WARN] 第 {attempt} 次尝试失败，10s后重试...")
                time.sleep(10)
        print(f"\n[FAIL] 连续 {max_retries} 次尝试全部失败")
        return False


def undock_and_return_home(driver):
    script = UndockScript(driver)
    return script.run()


if __name__ == "__main__":
    import uiautomator2 as u2
    print("\n" + "=" * 60)
    print("  下桩返回原点脚本")
    print("=" * 60)
    d = u2.connect()
    print(f"设备: {d.serial}")
    script = UndockScript(d)
    script.run_with_retry()

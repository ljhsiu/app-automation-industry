"""
充电脚本
当电量低于阈值时，自动执行充电流程（从首页→设置→充电设置→立刻充电）
支持等待充电到目标电量后下桩继续
"""
import sys
import time
from pathlib import Path

# 加项目根到 path，以便 import pages
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pages.home_page import HomePage
from pages.setting_page import SettingPage
from pages.charge_setting_page import ChargeSettingPage
from pages.charge_page import ChargePage


class ChargeScript:
    """充电脚本"""

    PACKAGE = "com.keenon.solutionindustry"
    CHARGE_ACTIVITY = "com.keenon.industry.setting.activity.SettingHomeActivity"
    LOW_BATTERY_THRESHOLD = 10
    TARGET_BATTERY_THRESHOLD = 80
    CHECK_INTERVAL = 60  # 充电中检测间隔（秒）

    def __init__(self, driver):
        self.driver = driver
        self.home_page = HomePage(driver)
        self.setting_page = SettingPage(driver)
        self.charge_setting_page = ChargeSettingPage(driver)
        self.charge_page = ChargePage(driver)

    def get_battery(self):
        battery = self.driver(resourceId=f"{self.PACKAGE}:id/tv_battery")
        if battery.exists:
            text = battery.get_text()
            if text and '%' in text:
                return int(text.replace('%', ''))
        return None

    def go_to_home(self):
        print("正在返回首页...")
        for _ in range(10):
            if self.home_page.is_at_home_page():
                print("已到达首页")
                return True
            try:
                back_btn = self.driver(resourceId=f"{self.PACKAGE}:id/view_left")
                if back_btn.exists:
                    back_btn.click()
                else:
                    self.driver.press("back")
            except Exception:
                self.driver.press("back")
            time.sleep(0.5)

        if not self.home_page.is_at_home_page():
            print("强制重启 App...")
            self.driver.app_stop(self.PACKAGE)
            time.sleep(1)
            self.driver.app_start(self.PACKAGE, "com.keenon.industry.activity.IndustryHomeActivity")
            time.sleep(2)
            from pages.home_page import HomePageHelper
            HomePageHelper(self.driver).ensure_app_started()

        return self.home_page.is_at_home_page()

    def go_to_setting(self):
        print("正在进入设置页...")
        if not self.home_page.is_at_home_page():
            self.go_to_home()
        self.home_page.click_setting()
        time.sleep(1)
        return self.setting_page.is_at_setting_page()

    def start_charge(self):
        """开始充电流程"""
        print("\n" + "="*50)
        print("开始充电流程")
        print("="*50)

        if not self.go_to_home():
            print("[FAIL] 无法返回首页")
            return False

        current = self.driver.app_current()
        if "setting" not in str(current.get('activity', '')).lower():
            if not self.go_to_setting():
                print("[FAIL] 无法进入设置页")
                return False
            print("进入设置页")
        else:
            print("已在设置页")

        print("点击充电设置...")
        if not self.charge_setting_page.is_at_charge_setting_page():
            self.setting_page.click_charge_setting()

        if not self.charge_setting_page.is_at_charge_setting_page():
            print("[FAIL] 无法进入充电设置页")
            return False

        print("进入充电设置页")
        print("点击立刻充电...")
        charge_page = self.charge_setting_page.click_charge_now()

        print("检查充电下发状态...")
        time.sleep(2)

        if charge_page.is_navigating_to_charge():
            print("充电下发成功！正在前往充电桩...")
            return True
        if charge_page.is_charging():
            print("已在充电中！")
            return True

        print("[WARN] 未检测到前往充电桩或充电中状态")
        return False

    def wait_for_charging(self, timeout=180):
        print(f"\n等待进入充电状态（最多 {timeout} 秒）...")
        start_time = time.time()
        while time.time() - start_time < timeout:
            if self.charge_page.is_charging():
                percent = self.charge_page.get_charge_percent()
                print(f"已进入充电状态！当前电量: {percent}%")
                return True
            time.sleep(5)
        print(f"[FAIL] 等待 {timeout} 秒后仍未进入充电状态")
        return False

    def wait_for_target_battery(self, target_battery=None, max_wait_seconds=7200):
        if target_battery is None:
            target_battery = self.TARGET_BATTERY_THRESHOLD

        print(f"\n{'='*50}")
        print(f"等待充电到 {target_battery}% 以上")
        print(f"最大等待: {max_wait_seconds}s ({max_wait_seconds//60}min)")
        print(f"{'='*50}")

        start_time = time.time()
        last_battery = None
        no_change_count = 0

        while time.time() - start_time < max_wait_seconds:
            current_battery = self.get_battery()

            if current_battery is not None:
                if current_battery != last_battery:
                    print(f"当前电量: {current_battery}%")
                    last_battery = current_battery
                    no_change_count = 0
                else:
                    no_change_count += 1

                if current_battery >= target_battery:
                    elapsed = int(time.time() - start_time)
                    print(f"\n电量已达 {current_battery}%，充电耗时 {elapsed}s ({elapsed//60}min)")
                    print("正在下桩...")
                    self._stop_charging()
                    return True

                if no_change_count > 12:
                    print(f"\n[WARN] 电量 {current_battery}% 超过2分钟无变化")
                    self._stop_charging()
                    return True

            if not self.charge_page.is_charging() and not self.charge_page.is_navigating_to_charge():
                print("[WARN] 充电中断，尝试重新进入...")
                if not self.start_charge():
                    print("[FAIL] 无法重新启动充电")
                    return False

            time.sleep(10)

        print(f"\n[FAIL] 等待 {max_wait_seconds}s 后仍未达到目标电量")
        return False

    def _stop_charging(self):
        print("执行下桩操作...")
        self.go_to_home()
        time.sleep(1)
        try:
            stop_btn = self.driver(text="停止充电")
            if stop_btn.exists:
                print("点击停止充电...")
                stop_btn.click()
                time.sleep(2)
        except Exception as e:
            print(f"停止充电失败: {e}")
        try:
            back_btn = self.driver(resourceId=f"{self.PACKAGE}:id/view_left")
            if back_btn.exists:
                back_btn.click()
                time.sleep(1)
        except Exception:
            pass
        print("下桩完成")

    def run(self, low_battery_threshold=None, target_battery=None):
        if low_battery_threshold is None:
            low_battery_threshold = self.LOW_BATTERY_THRESHOLD
        if target_battery is None:
            target_battery = self.TARGET_BATTERY_THRESHOLD

        current_battery = self.get_battery()
        print(f"\n当前电量: {current_battery}%")
        if current_battery is None:
            print("[FAIL] 无法获取电量")
            return False
        if current_battery >= target_battery:
            print(f"电量充足（{current_battery}% >= {target_battery}%），无需充电")
            return True

        if not self.start_charge():
            print("[FAIL] 充电下发失败")
            return False
        if not self.wait_for_charging():
            print("[WARN] 未检测到充电状态，但充电已下发")

        success = self.wait_for_target_battery(target_battery)
        if success:
            print(f"\n充电流程完成！")
        else:
            print(f"\n[WARN] 充电未达到目标电量，已下桩")
        return True

    def charge_to_full(self):
        return self.run(low_battery_threshold=0, target_battery=100)


def check_and_charge(driver, low_battery_threshold=10, target_battery=80):
    script = ChargeScript(driver)
    return script.run(low_battery_threshold, target_battery)


if __name__ == "__main__":
    import uiautomator2 as u2
    print("\n" + "=" * 60)
    print("  充电脚本")
    print("=" * 60)
    d = u2.connect()
    print(f"设备: {d.serial}")
    script = ChargeScript(d)
    script.start_charge()
    print("充电任务已下发")

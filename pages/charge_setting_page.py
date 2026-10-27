"""
充电设置页面对象
"""
import time
from .base_page import BasePage


class ChargeSettingPage(BasePage):
    """充电设置页面对象"""

    PACKAGE = "com.keenon.solutionindustry"

    # ========== 页面元素定位器 ==========

    @property
    def title_text(self):
        """标题文本"""
        return self.driver(text="充电设置")

    @property
    def add_work_period(self):
        """添加工作时段"""
        return self.driver(text="添加工作时段")

    @property
    def back_button(self):
        """返回按钮"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/view_left")

    @property
    def charge_now_button(self):
        """立刻充电按钮"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/tv_charge")

    @property
    def push_to_charge(self):
        """试试手推至充电桩"""
        return self.driver(text="试试手推至充电桩?")

    # ========== 页面操作方法 ==========

    def click_back(self):
        """点击返回按钮"""
        self.back_button.click()

    def click_charge_now(self):
        """
        点击立刻充电按钮，前往充电桩

        Returns:
            ChargePage: 充电页面对象（前往充电桩）
        """
        from .charge_page import ChargePage

        # 等待页面加载完成
        self.wait_page_loaded()
        time.sleep(1)

        # 点击立刻充电按钮
        elem = self.charge_now_button
        if elem.exists:
            info = elem.info
            bounds = info.get('bounds', {})
            if bounds:
                x = (bounds['left'] + bounds['right']) // 2
                y = (bounds['top'] + bounds['bottom']) // 2
                self.driver.click(x, y)
                print(f"点击立刻充电: ({x}, {y})")
            else:
                elem.click()
        else:
            print("未找到立刻充电按钮，尝试使用 text 点击")
            self.driver(text="立刻充电").click()

        # 等待页面跳转
        time.sleep(2)

        return ChargePage(self.driver)

    def get_battery(self):
        """获取电池电量"""
        # 从顶部状态栏获取
        battery = self.driver(resourceId=f"{self.PACKAGE}:id/tv_battery")
        if battery.exists:
            text = battery.get_text()
            if text and '%' in text:
                return int(text.replace('%', ''))
        return None

    def take_screenshot(self, name="charge_setting_page"):
        """截图"""
        return super().take_screenshot(name)

    # ========== 页面状态断言方法 ==========

    def is_at_charge_setting_page(self):
        """判断是否在充电设置页"""
        return self.add_work_period.exists

    def wait_page_loaded(self, timeout=10):
        """等待充电设置页加载完成"""
        return self.add_work_period.wait(timeout=timeout)

    def assert_at_charge_setting_page(self):
        """断言当前在充电设置页"""
        assert self.is_at_charge_setting_page(), "当前不在充电设置页"

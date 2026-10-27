"""
设置页面对象
"""
import time
from .base_page import BasePage


class SettingPage(BasePage):
    """设置页面对象"""

    PACKAGE = "com.keenon.solutionindustry"

    # ========== 页面元素定位器 ==========

    @property
    def title_text(self):
        """标题文本"""
        return self.driver(text="设置")

    @property
    def back_button(self):
        """返回按钮"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/view_left")

    @property
    def charge_setting(self):
        """充电设置"""
        return self.driver(text="充电设置")

    @property
    def basic_setting(self):
        """基本设置"""
        return self.driver(text="基本设置")

    @property
    def sound_setting(self):
        """声音设置"""
        return self.driver(text="声音设置")

    @property
    def motion_setting(self):
        """运动设置"""
        return self.driver(text="运动设置")

    @property
    def task_setting(self):
        """任务设置"""
        return self.driver(text="任务设置")

    @property
    def battery_text(self):
        """电池电量"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/tv_battery")

    # ========== 页面操作方法 ==========

    def click_back(self):
        """点击返回按钮"""
        self.back_button.click()

    def click_charge_setting(self):
        """
        点击充电设置，进入充电设置页

        Returns:
            ChargeSettingPage: 充电设置页面对象
        """
        from .charge_setting_page import ChargeSettingPage

        # 等待设置页加载
        self.wait_page_loaded()
        time.sleep(1)

        # 尝试点击"充电设置"元素
        elem = self.charge_setting
        if elem.exists:
            # 点击元素中心位置
            info = elem.info
            bounds = info.get('bounds', {})
            if bounds:
                x = (bounds['left'] + bounds['right']) // 2
                y = (bounds['top'] + bounds['bottom']) // 2
                self.driver.click(x, y)
                print(f"点击充电设置: ({x}, {y})")
            else:
                elem.click()
        else:
            print("未找到充电设置元素，尝试使用 text 点击")
            self.driver(text="充电设置").click()

        # 等待页面跳转
        time.sleep(3)

        return ChargeSettingPage(self.driver)

    def get_battery(self):
        """获取电池电量"""
        if self.battery_text.exists:
            text = self.battery_text.get_text()
            # 提取数字，如 "82%" -> 82
            if text and '%' in text:
                return int(text.replace('%', ''))
        return None

    def take_screenshot(self, name="setting_page"):
        """截图"""
        return super().take_screenshot(name)

    # ========== 页面状态断言方法 ==========

    def is_at_setting_page(self):
        """
        判断是否在设置页

        Returns:
            bool: True 表示在设置页
        """
        return self.title_text.exists

    def wait_page_loaded(self, timeout=10):
        """等待设置页加载完成"""
        # 等待任意一个设置项出现
        return self.charge_setting.wait(timeout=timeout) or self.basic_setting.wait(timeout=timeout)

    def assert_at_setting_page(self):
        """断言当前在设置页"""
        assert self.is_at_setting_page(), "当前不在设置页"

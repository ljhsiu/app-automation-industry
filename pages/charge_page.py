"""
充电页面对象（前往充电桩 / 充电中）
"""
import time
from .base_page import BasePage


class ChargePage(BasePage):
    """充电页面对象"""

    PACKAGE = "com.keenon.solutionindustry"

    # ========== 页面元素定位器 ==========

    @property
    def title_navigating(self):
        """前往充电标题"""
        return self.driver(text="前往充电")

    @property
    def title_charging(self):
        """正在充电标题"""
        return self.driver(text="正在充电")

    @property
    def tip_navigating(self):
        """正在前往提示"""
        return self.driver(text="正在前往充电")

    @property
    def back_button(self):
        """返回按钮"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/view_left")

    @property
    def charge_percent(self):
        """充电百分比"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/tv_state_change")

    @property
    def charge_time(self):
        """充电时间"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/tv_charge_time")

    @property
    def charge_tip(self):
        """充电提示（充满电）"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/tv_charge_tip")

    # ========== 页面操作方法 ==========

    def click_back(self):
        """点击返回按钮"""
        self.back_button.click()

    def get_charge_percent(self):
        """获取充电百分比"""
        if self.charge_percent.exists:
            text = self.charge_percent.get_text()
            if text and '%' in text:
                return int(text.replace('%', ''))
        return None

    def take_screenshot(self, name="charge_page"):
        """截图"""
        return super().take_screenshot(name)

    # ========== 页面状态断言方法 ==========

    def is_navigating_to_charge(self):
        """
        判断是否在前往充电桩页面

        Returns:
            bool: True 表示在前往充电桩
        """
        return self.tip_navigating.exists

    def is_charging(self):
        """
        判断是否在充电中页面

        Returns:
            bool: True 表示在充电中
        """
        return self.title_charging.exists

    def is_at_charge_page(self):
        """
        判断是否在任何充电相关页面

        Returns:
            bool: True 表示在充电相关页面
        """
        return self.is_navigating_to_charge() or self.is_charging()

    def wait_page_loaded(self, timeout=10):
        """等待充电页面加载完成"""
        return self.title_navigating.wait_exists(timeout=timeout) or \
               self.title_charging.wait_exists(timeout=timeout)

    def assert_navigating(self):
        """断言正在前往充电桩"""
        assert self.is_navigating_to_charge(), "当前不在前往充电桩页面"

    def assert_charging(self):
        """断言正在充电"""
        assert self.is_charging(), "当前不在充电中页面"

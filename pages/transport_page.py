"""
搬运任务页面对象
"""
import time
from .base_page import BasePage


class TransportPage(BasePage):
    """搬运任务页面对象"""

    PACKAGE = "com.keenon.solutionindustry"

    # ========== 页面元素定位器 ==========

    @property
    def jack_button(self):
        """
        举升/放下按钮 - 用于判断是否在搬运任务页
        判断元素：resourceId
        """
        return self.driver(resourceId=f"{self.PACKAGE}:id/tv_jack_button")

    @property
    def jack_button_by_text(self):
        """
        举升按钮 - 通过文本定位
        """
        return self.driver(text="举升")

    @property
    def drop_button_by_text(self):
        """
        放下按钮 - 通过文本定位
        """
        return self.driver(text="放下")

    @property
    def title_bar(self):
        """标题栏"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/view_title")

    @property
    def back_button(self):
        """返回按钮"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/view_left")

    @property
    def start_point(self):
        """起点"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/item_start_point")

    @property
    def end_point(self):
        """终点"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/item_end_point")

    @property
    def start_button(self):
        """开始按钮"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/view_start")

    @property
    def lift_status_text(self):
        """举升状态文本"""
        return self.driver(text="举升状态")

    @property
    def lift_status_value(self):
        """举升状态值（未举升/已举升）"""
        return self.driver(resourceId=f"{self.PACKAGE}:id/tv_text")

    # ========== 页面操作方法 ==========

    def click_jack(self):
        """点击举升按钮"""
        self.jack_button.click()

    def click_back(self):
        """点击返回按钮"""
        self.back_button.click()

    def click_start_point(self):
        """点击起点"""
        self.start_point.click()

    def click_end_point(self):
        """点击终点"""
        self.end_point.click()

    def click_start(self):
        """点击开始按钮"""
        self.start_button.click()

    def get_lift_status(self):
        """获取举升状态"""
        if self.lift_status_value.exists:
            return self.lift_status_value.get_text()
        return None

    def take_screenshot(self, name="transport_page"):
        """截图"""
        return super().take_screenshot(name)

    # ========== 页面状态断言方法 ==========

    def is_at_transport_page(self):
        """
        判断是否在搬运任务页
        通过检查举升按钮元素是否存在来判断

        Returns:
            bool: True 表示在搬运任务页
        """
        return self.jack_button.exists

    def wait_page_loaded(self, timeout=10):
        """
        等待搬运任务页加载完成

        Args:
            timeout: 超时时间（秒）

        Returns:
            bool: True 表示加载成功
        """
        return self.jack_button.wait_exists(timeout=timeout)

    def assert_at_transport_page(self):
        """断言当前在搬运任务页"""
        assert self.is_at_transport_page(), "当前不在搬运任务页，举升按钮不存在"

    def assert_lift_status(self, expected_status):
        """
        断言举升状态

        Args:
            expected_status: 期望的状态，如"未举升"、"已举升"
        """
        current_status = self.get_lift_status()
        assert current_status == expected_status, f"举升状态不符，期望: {expected_status}, 实际: {current_status}"

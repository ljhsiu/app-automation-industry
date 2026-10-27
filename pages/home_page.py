"""
首页页面对象
IndustryHomeActivity 首页
"""
import time
from .base_page import BasePage


class HomePage(BasePage):
    """首页页面对象"""

    # ========== 页面元素定位器 ==========

    @property
    def menu_button(self):
        """菜单按钮 - 用于判断是否在首页"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/view_menu")

    @property
    def time_display(self):
        """时间显示"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/tv_time")

    @property
    def date_display(self):
        """日期显示"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/tv_date")

    @property
    def wifi_icon(self):
        """WiFi 图标"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/iv_wifi")

    @property
    def battery_text(self):
        """电池电量"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/tv_battery")

    @property
    def setting_button(self):
        """设置按钮（在侧边栏中）"""
        return self.driver(text="设置")

    @property
    def iv_menu_button(self):
        """设置图标"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/view_menu")

    @property
    def clock_text(self):
        """系统时钟"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/clock")

    @property
    def timer_text(self):
        """计时器"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/tv_timer")

    # 模式菜单
    @property
    def model_recycler(self):
        """模式列表"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/recycler_list")

    @property
    def model_direct(self):
        """直达模式"""
        return self.driver(text="直达")

    @property
    def model_loop(self):
        """循环模式"""
        return self.driver(text="循环")

    @property
    def model_multi_point(self):
        """多点模式"""
        return self.driver(text="多点")

    # 顶部/底部模式
    @property
    def model_top(self):
        """顶部模式（料箱）"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/tv_model_top")

    @property
    def model_bottom(self):
        """底部模式（搬运）"""
        return self.driver(resourceId="com.keenon.solutionindustry:id/tv_model_bom")

    # ========== 页面操作方法 ==========

    def click_menu(self):
        """点击菜单按钮"""
        self.menu_button.click()
        time.sleep(0.5)

    def click_direct_mode(self):
        """点击直达模式"""
        self.model_direct.click()

    def click_loop_mode(self):
        """点击循环模式"""
        self.model_loop.click()

    def click_multi_point_mode(self):
        """点击多点模式"""
        self.model_multi_point.click()

    def click_transport_mode(self):
        """
        点击搬运模式，进入搬运任务页面

        Returns:
            TransportPage: 搬运任务页面对象
        """
        from .transport_page import TransportPage

        self.model_bottom.click()
        time.sleep(1)

        return TransportPage(self.driver)

    def get_time(self):
        """获取当前时间显示"""
        if self.time_display.exists:
            return self.time_display.get_text()
        return None

    def get_date(self):
        """获取当前日期显示"""
        if self.date_display.exists:
            return self.date_display.get_text()
        return None

    def get_battery(self):
        """
        获取电池电量（数字）

        Returns:
            int: 电量百分比，如 82
        """
        if self.battery_text.exists:
            text = self.battery_text.get_text()
            if text and '%' in text:
                return int(text.replace('%', ''))
        return None

    def click_setting(self):
        """
        点击设置按钮，进入设置页

        Returns:
            SettingPage: 设置页面对象
        """
        from .setting_page import SettingPage

        # 方式1：直接用 view_menu 点击进入设置
        if self.iv_menu_button.exists:
            print("使用 view_menu 进入设置页...")
            self.iv_menu_button.click()
            time.sleep(1)
        else:
            # 方式2：先点菜单，再点设置
            self.click_menu()
            time.sleep(1)

            if self.setting_button.exists:
                self.setting_button.click()
                time.sleep(1)
            else:
                # 方式3：直接启动设置页
                self.driver.app_start(
                    "com.keenon.solutionindustry",
                    "com.keenon.industry.setting.activity.SettingHomeActivity"
                )
                time.sleep(2)

        # 等待设置页加载
        time.sleep(1)

        return SettingPage(self.driver)

    def take_screenshot(self, name="home_page"):
        """截图"""
        return super().take_screenshot(name)

    # ========== 页面状态断言方法 ==========

    def is_at_home_page(self):
        """
        判断是否在首页
        通过检查 view_menu 元素是否存在来判断

        Returns:
            bool: True 表示在首页
        """
        return self.menu_button.exists

    def wait_page_loaded(self, timeout=10):
        """
        等待首页加载完成

        Args:
            timeout: 超时时间（秒）

        Returns:
            bool: True 表示加载成功
        """
        return self.menu_button.wait_exists(timeout=timeout)

    def assert_at_home_page(self):
        """断言当前在首页"""
        assert self.is_at_home_page(), "当前不在 App 首页"

    def assert_elements_visible(self):
        """断言首页关键元素都可见"""
        assert self.is_at_home_page(), "菜单按钮不存在"
        assert self.time_display.exists, "时间显示不存在"
        assert self.date_display.exists, "日期显示不存在"


class HomePageHelper:
    """
    首页辅助类
    提供 App 状态检查和启动功能
    """

    # 等待配置
    CHECK_INTERVAL = 5  # 每隔 5 秒检查一次
    MAX_WAIT_PER_ROUND = 60  # 每轮最多等待 60 秒
    MAX_RETRIES = 3  # 最多重启 3 轮

    def __init__(self, driver):
        self.driver = driver
        self.package = "com.keenon.solutionindustry"
        self.activity = "com.keenon.industry.activity.IndustryHomeActivity"
        self.home_page = HomePage(driver)

    def is_app_at_home(self):
        """检查 App 是否在首页"""
        return self.home_page.is_at_home_page()

    def _wait_for_home_page(self, round_num):
        """
        等待首页出现（每轮最多等待 60 秒，每 5 秒检查一次）

        Args:
            round_num: 当前轮次编号

        Returns:
            bool: True 表示找到了首页
        """
        elapsed = 0
        while elapsed < self.MAX_WAIT_PER_ROUND:
            if self.is_app_at_home():
                return True

            elapsed += self.CHECK_INTERVAL
            remaining = self.MAX_WAIT_PER_ROUND - elapsed
            print(f"  轮次 {round_num}: 等待中... ({remaining} 秒后可重启)")
            time.sleep(self.CHECK_INTERVAL)

        return False

    def ensure_app_started(self, max_retries=None):
        """
        确保 App 已启动并在前台首页
        重启后会有定位提示页（最多 60 秒），本方法会自动等待

        Args:
            max_retries: 最大重试次数（默认 3）

        Returns:
            bool: True 表示成功到达首页，False 表示失败
        """
        if max_retries is None:
            max_retries = self.MAX_RETRIES

        # 检查是否已在首页
        if self.is_app_at_home():
            print("✅ App 已在首页")
            return True

        # 不在首页，开始重启循环
        for i in range(1, max_retries + 1):
            print(f"\n{'='*40}")
            print(f"第 {i}/{max_retries} 轮：重启 App")
            print(f"{'='*40}")

            # 重启 App
            self.driver.app_stop(self.package)
            time.sleep(1)
            self.driver.app_start(self.package, self.activity)

            # 等待首页出现
            if self._wait_for_home_page(i):
                print(f"✅ 第 {i} 轮：成功到达首页")
                return True
            else:
                print(f"❌ 第 {i} 轮：60 秒内未找到首页，将重启...")

        # 所有轮次都失败
        print(f"\n❌ 全部 {max_retries} 轮都失败，无法到达首页")
        return False

    def restart_app(self):
        """重启 App"""
        self.driver.app_stop(self.package)
        time.sleep(1)
        self.driver.app_start(self.package, self.activity)

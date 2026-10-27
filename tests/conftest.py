"""
pytest configuration - 从 app-automation 迁移并适配
"""
import sys
import os
import pytest
from pathlib import Path

# 确保项目根在 path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(scope="session")
def device_config():
    """设备配置 fixture"""
    return {
        "platform": "android",
        "serial": "192.168.0.100:5555",
        "caps": {
            "platformName": "Android",
            "appPackage": "com.keenon.solutionindustry",
            "appActivity": "com.keenon.industry.activity.IndustryHomeActivity",
            "noReset": True,
            "newCommandTimeout": 300,
        }
    }


@pytest.fixture(scope="function")
def app_driver(device_config):
    """创建 uiautomator2 driver"""
    import uiautomator2 as u2
    from pages.home_page import HomePageHelper

    platform = device_config["platform"]
    driver = None

    if platform == "android":
        if device_config["serial"]:
            driver = u2.connect(device_config["serial"])
        else:
            driver = u2.connect()
        driver.wait_timeout = 10.0

        helper = HomePageHelper(driver)
        if not helper.is_app_at_home():
            print(f"\n[WARN] App 不在首页，正在重启...")
            helper.ensure_app_started()

    yield driver

    if driver:
        try:
            driver.screenshot()
        except Exception:
            pass


@pytest.fixture(scope="function")
def home_page(app_driver):
    from pages.home_page import HomePage
    return HomePage(app_driver)


@pytest.fixture(scope="function")
def setting_page(home_page):
    import time
    page = home_page.click_setting()
    time.sleep(1)
    return page


@pytest.fixture(scope="function")
def transport_page(home_page):
    import time
    page = home_page.click_transport_mode()
    time.sleep(2)
    return page


@pytest.fixture(scope="session")
def project_root():
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


@pytest.fixture(scope="session")
def screenshot_dir(project_root):
    path = os.path.join(project_root, "screenshots")
    os.makedirs(path, exist_ok=True)
    return path


def pytest_configure(config):
    config.addinivalue_line("markers", "smoke: Smoke test cases")
    config.addinivalue_line("markers", "regression: Regression test cases")

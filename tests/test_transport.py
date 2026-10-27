"""
搬运任务页测试用例（从 app-automation 迁移）
"""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest


class TestTransportPage:
    """搬运任务页测试"""

    def test_enter_transport_page(self, transport_page):
        assert transport_page.is_at_transport_page(), "未成功进入搬运任务页"

    def test_transport_page_elements(self, transport_page):
        assert transport_page.jack_button.exists, "举升按钮不存在"
        assert transport_page.title_bar.exists, "标题栏不存在"
        assert transport_page.back_button.exists, "返回按钮不存在"
        assert transport_page.start_point.exists, "起点不存在"
        assert transport_page.end_point.exists, "终点不存在"

    def test_get_lift_status(self, transport_page):
        status = transport_page.get_lift_status()
        print(f"举升状态: {status}")
        assert status is not None, "无法获取举升状态"

    def test_back_to_home_page(self, transport_page, home_page):
        transport_page.click_back()
        import time
        time.sleep(1)
        assert home_page.is_at_home_page(), "未成功返回首页"

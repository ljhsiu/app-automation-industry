"""
MCP Server Tests - MCP 服务器测试

测试 MCP 服务器的工具定义和基本功能
"""

import pytest
import sys
from pathlib import Path

# 添加 src 目录到 Python 路径
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))


class TestToolDefinitions:
    """测试工具定义"""

    def test_charge_tool_definition(self):
        """测试充电工具定义"""
        from mcp_server.tools import ChargeTool

        tool = ChargeTool()
        assert tool.name == "charge_start"
        assert len(tool.description) > 0
        assert "properties" in tool.input_schema
        assert "device_ip" in tool.input_schema["properties"]

    def test_undock_tool_definition(self):
        """测试下桩工具定义"""
        from mcp_server.tools import UndockTool

        tool = UndockTool()
        assert tool.name == "undock"
        assert len(tool.description) > 0
        assert "properties" in tool.input_schema

    def test_jack_tool_definition(self):
        """测试举升压测工具定义"""
        from mcp_server.tools import JackStressTool

        tool = JackStressTool()
        assert tool.name == "jack_stress_test"
        assert len(tool.description) > 0
        assert "test_count" in tool.input_schema["properties"]

    def test_device_tool_definitions(self):
        """测试设备工具定义"""
        from mcp_server.tools import DeviceStatusTool, DeviceListTool

        status_tool = DeviceStatusTool()
        assert status_tool.name == "get_device_status"

        list_tool = DeviceListTool()
        assert list_tool.name == "list_devices"


class TestConfigAdapter:
    """测试配置适配器"""

    def test_config_singleton(self):
        """测试配置单例"""
        from mcp_server.adapters.config_adapter import ConfigAdapter

        config1 = ConfigAdapter()
        config2 = ConfigAdapter()
        assert config1 is config2

    def test_device_parsing(self):
        """测试设备配置解析"""
        from mcp_server.adapters.config_adapter import DeviceConfig

        device = DeviceConfig(
            name="测试设备",
            ip="192.168.1.100",
            port=5555
        )
        assert device.address == "192.168.1.100:5555"


class TestHelpers:
    """测试辅助函数"""

    def test_parse_battery(self):
        """测试电量解析"""
        from mcp_server.utils.helpers import parse_battery

        assert parse_battery("85%") == 85
        assert parse_battery("100") == 100
        assert parse_battery("50%") == 50
        assert parse_battery(None) is None
        assert parse_battery("") is None

    def test_format_result(self):
        """测试结果格式化"""
        from mcp_server.utils.helpers import format_result

        result = format_result(True, "测试成功", data={"key": "value"})
        assert result["success"] is True
        assert result["message"] == "测试成功"
        assert result["data"]["key"] == "value"

    def test_validate_device_ip(self):
        """测试 IP 验证"""
        from mcp_server.utils.helpers import validate_device_ip

        assert validate_device_ip("192.168.3.211") is True
        assert validate_device_ip("192.168.3.211:5555") is True
        assert validate_device_ip("invalid") is False
        assert validate_device_ip(None) is False
        assert validate_device_ip("") is False

    def test_format_duration(self):
        """测试时长格式化"""
        from mcp_server.utils.helpers import format_duration

        assert format_duration(30) == "30 秒"
        assert format_duration(60) == "1 分"
        assert format_duration(90) == "1 分 30 秒"
        assert format_duration(3660) == "1 小时 1 分"


class TestServerInitialization:
    """测试服务器初始化"""

    def test_create_server(self):
        """测试创建服务器"""
        from mcp_server.server import create_server

        server = create_server()
        assert server is not None
        assert len(server.tools) >= 4  # 至少 4 个工具

    def test_get_tool_definitions(self):
        """测试获取工具定义"""
        from mcp_server.server import create_server

        server = create_server()
        definitions = server.get_tool_definitions()

        assert len(definitions) >= 4
        for tool_def in definitions:
            assert "name" in tool_def
            assert "description" in tool_def
            assert "inputSchema" in tool_def


class TestChargeStatusTool:
    """测试充电状态工具"""

    def test_charge_status_definition(self):
        """测试充电状态工具定义"""
        from mcp_server.tools import ChargeStatusTool

        tool = ChargeStatusTool()
        assert tool.name == "charge_status"
        assert "device_ip" in tool.input_schema["properties"]


class TestUndockStatusTool:
    """测试下桩状态工具"""

    def test_undock_status_definition(self):
        """测试下桩状态工具定义"""
        from mcp_server.tools import UndockStatusTool

        tool = UndockStatusTool()
        assert tool.name == "undock_status"


class TestDeviceScreenshotTool:
    """测试截图工具"""

    def test_screenshot_definition(self):
        """测试截图工具定义"""
        from mcp_server.tools import DeviceScreenshotTool

        tool = DeviceScreenshotTool()
        assert tool.name == "device_screenshot"
        assert "filename" in tool.input_schema["properties"]


# 集成测试（需要实际设备）
class TestIntegration:
    """集成测试"""

    @pytest.fixture
    def mock_driver(self):
        """模拟驱动"""
        class MockDriver:
            serial = "mock_serial"

            def __getattr__(self, name):
                return lambda *args, **kwargs: MockElement()

        class MockElement:
            exists = True

            def get_text(self):
                return "85%"

            def click(self):
                pass

            def info(self):
                return {}

        return MockDriver()

    def test_charge_tool_execute_validation(self):
        """测试充电工具参数验证"""
        from mcp_server.tools import ChargeTool

        tool = ChargeTool()

        # 空 IP 应该返回错误
        result = tool.execute({})
        assert result["success"] is False
        assert "device_ip" in result.get("error", "").lower() or "error" in result


if __name__ == "__main__":
    pytest.main([__file__, "-v"])

"""
Device Tool - 设备状态工具

提供设备状态查询功能
"""

import time
import logging
from typing import Optional
from .base_tool import BaseTool
from ..adapters.driver_adapter import DriverAdapter
from ..adapters.config_adapter import get_config
from ..utils.helpers import format_result, sanitize_error

logger = logging.getLogger(__name__)


class DeviceStatusTool(BaseTool):
    """设备状态查询工具"""

    PACKAGE = "com.keenon.solutionindustry"

    @property
    def name(self) -> str:
        return "get_device_status"

    @property
    def description(self) -> str:
        return """获取设备的完整状态信息。

返回值包含：
- 设备序列号
- 当前 Activity
- 电量
- 是否在充电
- 当前页面状态"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "device_ip": {
                    "type": "string",
                    "description": "设备 IP 地址"
                }
            },
            "required": ["device_ip"]
        }

    def execute(self, arguments: dict) -> dict:
        """获取设备状态"""
        device_ip = arguments.get("device_ip")

        if not device_ip:
            return format_result(False, "设备 IP 不能为空", error="device_ip is required")

        try:
            driver = DriverAdapter.get_driver(device_ip)

            # 获取基本信息
            info = driver.info

            # 获取电量
            battery = DriverAdapter.get_battery(device_ip)

            # 获取当前 Activity
            current = driver.app_current()
            activity = str(current.get('activity', ''))

            # 获取包名
            package = str(current.get('package', ''))

            # 判断页面状态
            page_status = self._get_page_status(driver, activity)

            # 获取设备信息
            display_info = info.get('display', {}) if info else {}

            return format_result(
                True,
                "设备状态查询成功",
                data={
                    "device_ip": device_ip,
                    "serial": driver.serial if hasattr(driver, 'serial') else "unknown",
                    "current_activity": activity,
                    "current_package": package,
                    "battery": battery,
                    "is_charging": self._is_charging(driver),
                    "is_on_charge_station": self._is_on_charge_station(driver),
                    "page_status": page_status,
                    "display": {
                        "width": display_info.get('width', 0),
                        "height": display_info.get('height', 0)
                    },
                    "sdk_version": info.get('sdkInt', 0) if info else 0
                }
            )

        except Exception as e:
            logger.error(f"获取设备状态失败: {str(e)}")
            return format_result(
                False,
                "获取设备状态失败",
                error=sanitize_error(e)
            )

    def _get_page_status(self, driver, activity: str) -> str:
        """获取页面状态"""
        activity_lower = activity.lower()

        if 'home' in activity_lower or 'IndustryHomeActivity' in activity:
            return "首页"
        elif 'setting' in activity_lower:
            return "设置页"
        elif 'charge' in activity_lower:
            return "充电页"
        elif 'transport' in activity_lower:
            return "搬运任务页"
        else:
            return "其他页面"

    def _is_charging(self, driver) -> bool:
        """检查是否在充电"""
        if driver(text="正在充电").exists:
            return True

        if driver(text="充电中").exists:
            return True

        return False

    def _is_on_charge_station(self, driver) -> bool:
        """检查是否在充电桩上"""
        if driver(text="点击屏幕可退出充电").exists:
            return True

        if driver(text="正在退出充电").exists:
            return True

        return False


class DeviceScreenshotTool(BaseTool):
    """设备截图工具"""

    @property
    def name(self) -> str:
        return "device_screenshot"

    @property
    def description(self) -> str:
        return """对设备进行截图并保存。

参数：
- device_ip: 设备 IP 地址（必需）
- filename: 保存文件名（可选，默认自动生成）

返回值包含截图保存路径"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "device_ip": {
                    "type": "string",
                    "description": "设备 IP 地址"
                },
                "filename": {
                    "type": "string",
                    "description": "保存文件名（不含路径）"
                }
            },
            "required": ["device_ip"]
        }

    def execute(self, arguments: dict) -> dict:
        """截图"""
        device_ip = arguments.get("device_ip")
        filename = arguments.get("filename")

        if not device_ip:
            return format_result(False, "设备 IP 不能为空", error="device_ip is required")

        try:
            # 生成文件名
            if not filename:
                from datetime import datetime
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                filename = f"screenshot_{timestamp}.png"

            # 获取截图
            path = DriverAdapter.screenshot(device_ip, filename)

            if path:
                return format_result(
                    True,
                    f"截图保存成功",
                    data={
                        "filename": filename,
                        "path": path
                    }
                )
            else:
                return format_result(
                    False,
                    "截图保存失败",
                    error="Screenshot failed"
                )

        except Exception as e:
            return format_result(False, "截图失败", error=sanitize_error(e))


class DeviceListTool(BaseTool):
    """设备列表工具"""

    @property
    def name(self) -> str:
        return "list_devices"

    @property
    def description(self) -> str:
        return """列出所有已配置的设备。

返回值包含每个设备的：
- 名称
- IP 地址
- 端口
- 是否为当前设备"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {}
        }

    def execute(self, arguments: dict) -> dict:
        """列出设备"""
        try:
            config = get_config()
            devices = config.list_devices()

            return format_result(
                True,
                f"共 {len(devices)} 个设备",
                data={
                    "devices": devices,
                    "count": len(devices),
                    "current": config.current_device
                }
            )

        except Exception as e:
            return format_result(False, "获取设备列表失败", error=sanitize_error(e))

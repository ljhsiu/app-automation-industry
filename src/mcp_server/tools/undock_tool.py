"""
Undock Tool - 下桩工具

封装下桩脚本的功能，提供 MCP 接口
"""

import time
import logging
from typing import Optional
from .base_tool import BaseTool
from ..adapters.driver_adapter import DriverAdapter
from ..utils.helpers import format_result, sanitize_error, format_duration

logger = logging.getLogger(__name__)


class UndockTool(BaseTool):
    """下桩工具"""

    PACKAGE = "com.keenon.solutionindustry"

    @property
    def name(self) -> str:
        return "undock"

    @property
    def description(self) -> str:
        return """从充电桩下桩并返回首页。

当设备连接在充电桩上时，执行此操作可以让设备下桩并返回到工作位置。

支持参数：
- device_ip: 设备 IP 地址（必需）
- max_retries: 最大重试次数，默认 3
- wait_timeout: 等待超时时间（秒），默认 120

返回值包含：
- 是否成功
- 执行耗时
- 最终状态"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "device_ip": {
                    "type": "string",
                    "description": "设备 IP 地址"
                },
                "max_retries": {
                    "type": "integer",
                    "description": "最大重试次数",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 10
                },
                "wait_timeout": {
                    "type": "integer",
                    "description": "等待超时时间（秒）",
                    "default": 120,
                    "minimum": 30,
                    "maximum": 600
                }
            },
            "required": ["device_ip"]
        }

    def execute(self, arguments: dict) -> dict:
        """执行下桩"""
        device_ip = arguments.get("device_ip")
        max_retries = arguments.get("max_retries", 3)
        wait_timeout = arguments.get("wait_timeout", 120)

        if not device_ip:
            return format_result(False, "设备 IP 不能为空", error="device_ip is required")

        try:
            driver = DriverAdapter.get_driver(device_ip)
            start_time = time.time()

            # 执行下桩流程
            success = self._undock_with_retry(driver, max_retries, wait_timeout)

            elapsed = int(time.time() - start_time)

            if success:
                return format_result(
                    True,
                    f"下桩成功，耗时 {format_duration(elapsed)}",
                    data={
                        "success": True,
                        "elapsed_seconds": elapsed,
                        "elapsed_formatted": format_duration(elapsed),
                        "retries": 0  # 实际重试次数需要跟踪
                    }
                )
            else:
                return format_result(
                    False,
                    f"下桩失败，耗时 {format_duration(elapsed)}",
                    data={
                        "success": False,
                        "elapsed_seconds": elapsed,
                        "elapsed_formatted": format_duration(elapsed)
                    },
                    error="Undock failed after max retries"
                )

        except Exception as e:
            logger.error(f"下桩执行失败: {str(e)}")
            return format_result(False, "下桩执行失败", error=sanitize_error(e))

    def _undock_with_retry(self, driver, max_retries: int, timeout: int) -> bool:
        """带重试的下桩流程"""
        for attempt in range(1, max_retries + 1):
            logger.info(f"下桩尝试 {attempt}/{max_retries}")

            if self._undock(driver, timeout):
                return True

            if attempt < max_retries:
                logger.info(f"第 {attempt} 次尝试失败，10秒后重试...")
                time.sleep(10)

        return False

    def _undock(self, driver, timeout: int) -> bool:
        """执行单次下桩"""
        # 1. 检查是否在桩上
        if not self._is_on_charging_station(driver):
            logger.info("不在桩上，无需下桩")
            return True

        # 2. 点击退出充电
        if not self._click_exit_charging(driver):
            logger.warning("无法点击退出充电")
            return False

        # 3. 点击确认
        if not self._click_confirm(driver):
            logger.warning("无法点击确认")
            return False

        # 4. 等待退出充电完成
        if not self._wait_for_exit_complete(driver, timeout=60):
            logger.warning("退出充电失败")
            return False

        # 5. 等待回到首页
        if not self._wait_for_home_page(driver, timeout=timeout):
            logger.warning("未回到首页")
            return False

        return True

    def _is_on_charging_station(self, driver) -> bool:
        """检查是否在桩上充电"""
        # 方法1: 检查文案
        if driver(text="正在充电").exists:
            return True

        if driver(text="点击屏幕可退出充电").exists:
            return True

        # 方法2: 检查 Activity
        try:
            current = driver.app_current()
            activity = str(current.get('activity', '')).lower()
            if "charge" in activity:
                return True
        except Exception:
            pass

        return False

    def _click_exit_charging(self, driver) -> bool:
        """点击退出充电"""
        exit_hint = driver(text="点击屏幕可退出充电")

        if not exit_hint.exists:
            logger.info("未找到'点击屏幕可退出充电'，尝试其他方式")
            # 尝试点击屏幕中央
            try:
                info = driver.info
                width = info.get('display', {}).get('width', 1080)
                height = info.get('display', {}).get('height', 1920)
                driver.click(width // 2, height // 2)
                time.sleep(2)
                return True
            except Exception as e:
                logger.error(f"点击屏幕失败: {str(e)}")
                return False

        try:
            bounds = exit_hint.info.get('bounds', {})
            if bounds:
                x = (bounds['left'] + bounds['right']) // 2
                y = (bounds['top'] + bounds['bottom']) // 2
                driver.click(x, y)
                time.sleep(2)
                return True
        except Exception as e:
            logger.error(f"点击退出充电失败: {str(e)}")
            return False

    def _click_confirm(self, driver) -> bool:
        """点击确认按钮"""
        confirm_btn = driver(text="结束")

        if confirm_btn.exists:
            confirm_btn.click()
            time.sleep(2)
            return True

        # 备用方案
        ok_btn = driver(text="确认")
        if ok_btn.exists:
            ok_btn.click()
            time.sleep(2)
            return True

        logger.info("未找到确认按钮，可能已自动执行")
        return True

    def _wait_for_exit_complete(self, driver, timeout: int = 60) -> bool:
        """等待退出充电完成"""
        start_time = time.time()

        while time.time() - start_time < timeout:
            # 检查是否还在"正在退出充电"状态
            if not driver(text="正在退出充电").exists:
                logger.info("退出充电完成")
                return True

            time.sleep(2)

        logger.warning(f"等待 {timeout} 秒后仍未退出充电")
        return False

    def _wait_for_home_page(self, driver, timeout: int = 120) -> bool:
        """等待回到首页"""
        start_time = time.time()
        check_interval = 10

        while time.time() - start_time < timeout:
            try:
                current = driver.app_current()
                if 'IndustryHomeActivity' in str(current.get('activity', '')):
                    elapsed = int(time.time() - start_time)
                    logger.info(f"已回到首页，耗时 {elapsed} 秒")
                    return True
            except Exception:
                pass

            elapsed = int(time.time() - start_time)
            remaining = timeout - elapsed
            if remaining > 0:
                logger.debug(f"等待中... ({elapsed}/{timeout} 秒)")

            time.sleep(check_interval)

        logger.warning(f"等待 {timeout} 秒后仍未回到首页")
        return False


class UndockStatusTool(BaseTool):
    """下桩状态查询工具"""

    @property
    def name(self) -> str:
        return "undock_status"

    @property
    def description(self) -> str:
        return """查询设备当前的下桩状态。

返回值包含：
- 是否在充电桩上
- 当前的 Activity
- 是否可以下桩"""

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
        device_ip = arguments.get("device_ip")

        if not device_ip:
            return format_result(False, "设备 IP 不能为空", error="device_ip is required")

        try:
            driver = DriverAdapter.get_driver(device_ip)

            # 获取当前 Activity
            current = driver.app_current()
            activity = str(current.get('activity', ''))

            # 检查是否在桩上
            is_on_station = False
            if driver(text="正在充电").exists:
                is_on_station = True
            elif "charge" in activity.lower():
                is_on_station = True

            # 检查是否可以下桩
            can_undock = driver(text="点击屏幕可退出充电").exists or is_on_station

            return format_result(
                True,
                "查询成功",
                data={
                    "device_ip": device_ip,
                    "is_on_station": is_on_station,
                    "can_undock": can_undock,
                    "current_activity": activity
                }
            )

        except Exception as e:
            return format_result(False, "查询失败", error=sanitize_error(e))

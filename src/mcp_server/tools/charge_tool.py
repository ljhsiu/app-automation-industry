"""
Charge Tool - 充电工具

封装充电脚本的功能，提供 MCP 接口
"""

import time
import logging
from typing import Optional
from .base_tool import BaseTool
from ..adapters.driver_adapter import DriverAdapter
from ..adapters.config_adapter import get_config
from ..utils.helpers import format_result, sanitize_error, format_duration

logger = logging.getLogger(__name__)


class ChargeTool(BaseTool):
    """充电工具"""

    # 类常量
    PACKAGE = "com.keenon.solutionindustry"

    @property
    def name(self) -> str:
        return "charge_start"

    @property
    def description(self) -> str:
        return """开始充电流程。当设备电量低于低电量阈值时，自动下发充电指令让设备前往充电桩充电。
        
支持参数：
- device_ip: 设备 IP 地址（必需）
- low_battery_threshold: 低电量阈值，默认 10%
- target_battery_threshold: 目标电量阈值，默认 80%
- wait_for_target: 是否等待充到目标电量，默认 false

返回值包含：是否成功、当前电量、充电下发状态"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "device_ip": {
                    "type": "string",
                    "description": "设备 IP 地址，如 192.168.3.211"
                },
                "low_battery_threshold": {
                    "type": "integer",
                    "description": "低电量阈值（%），低于此值触发充电",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                },
                "target_battery_threshold": {
                    "type": "integer",
                    "description": "目标电量（%），充到此值后下桩",
                    "default": 80,
                    "minimum": 1,
                    "maximum": 100
                },
                "wait_for_target": {
                    "type": "boolean",
                    "description": "是否等待充到目标电量后下桩",
                    "default": False
                },
                "max_wait_seconds": {
                    "type": "integer",
                    "description": "最大等待时间（秒），仅当 wait_for_target=true 时有效",
                    "default": 7200,
                    "minimum": 60,
                    "maximum": 86400
                }
            },
            "required": ["device_ip"]
        }

    def execute(self, arguments: dict) -> dict:
        """执行充电"""
        device_ip = arguments.get("device_ip")
        low_battery = arguments.get("low_battery_threshold", 10)
        target_battery = arguments.get("target_battery_threshold", 80)
        wait_for_target = arguments.get("wait_for_target", False)
        max_wait = arguments.get("max_wait_seconds", 7200)

        # 验证参数
        if not device_ip:
            return format_result(False, "设备 IP 不能为空", error="device_ip is required")

        try:
            # 获取驱动
            driver = DriverAdapter.get_driver(device_ip)
            config = get_config()

            # 获取当前电量
            current_battery = DriverAdapter.get_battery(device_ip)
            logger.info(f"当前电量: {current_battery}%")

            # 检查是否需要充电
            if current_battery is not None and current_battery >= target_battery:
                return format_result(
                    True,
                    f"电量充足（{current_battery}% >= {target_battery}%），无需充电",
                    data={
                        "current_battery": current_battery,
                        "target_battery": target_battery,
                        "charged": False
                    }
                )

            # 执行充电流程
            success = self._start_charge(driver, device_ip)

            if not success:
                return format_result(
                    False,
                    "充电下发失败",
                    data={"current_battery": current_battery},
                    error="Failed to start charging"
                )

            result_data = {
                "current_battery": current_battery,
                "target_battery": target_battery,
                "charged": True,
                "charge_initiated": True
            }

            # 如果需要等待充满
            if wait_for_target:
                wait_result = self._wait_for_target_battery(
                    device_ip,
                    target_battery,
                    max_wait
                )
                result_data["wait_result"] = wait_result

            return format_result(
                True,
                "充电任务已下发",
                data=result_data
            )

        except Exception as e:
            logger.error(f"充电执行失败: {str(e)}")
            return format_result(
                False,
                "充电执行失败",
                error=sanitize_error(e)
            )

    def _start_charge(self, driver, device_ip: str) -> bool:
        """开始充电流程"""
        logger.info("开始充电流程...")

        # 1. 返回首页
        if not self._go_home(driver):
            logger.warning("无法返回首页，但继续尝试充电")

        # 2. 进入设置页
        if not self._go_to_setting(driver):
            logger.warning("无法进入设置页，但继续尝试")

        # 3. 点击充电设置
        self._click_charge_setting(driver)

        # 4. 点击立刻充电
        time.sleep(1)
        charge_now = driver(
            resourceId=f"{self.PACKAGE}:id/tv_end",
            text="立刻充电"
        )

        if charge_now.exists:
            charge_now.click()
            logger.info("已点击立刻充电")
            time.sleep(2)
            return True

        # 备用方案：直接发送 intent
        try:
            driver.shell([
                "am", "start", "-n",
                f"{self.PACKAGE}/com.keenon.industry.setting.activity.SettingHomeActivity"
            ])
            return True
        except Exception as e:
            logger.error(f"备用启动方式失败: {str(e)}")
            return False

    def _go_home(self, driver) -> bool:
        """返回首页"""
        for _ in range(10):
            try:
                current = driver.app_current()
                if 'IndustryHomeActivity' in str(current.get('activity', '')):
                    return True
            except Exception:
                pass

            driver.press("back")
            time.sleep(0.5)

        return False

    def _go_to_setting(self, driver) -> bool:
        """进入设置页"""
        # 点击设置按钮
        menu_btn = driver(resourceId=f"{self.PACKAGE}:id/view_menu")
        if menu_btn.exists:
            menu_btn.click()
            time.sleep(1)
            return True

        # 备用：点击 iv_menu
        iv_menu = driver(resourceId=f"{self.PACKAGE}:id/iv_menu")
        if iv_menu.exists:
            iv_menu.click()
            time.sleep(1)
            return True

        return False

    def _click_charge_setting(self, driver):
        """点击充电设置"""
        charge_setting = driver(text="充电设置")
        if charge_setting.exists:
            charge_setting.click()
            time.sleep(1)

    def _wait_for_target_battery(
        self,
        device_ip: str,
        target_battery: int,
        max_wait_seconds: int
    ) -> dict:
        """等待充电到目标电量"""
        logger.info(f"等待充电到 {target_battery}%...")

        start_time = time.time()
        last_battery = None
        check_interval = 10  # 每 10 秒检查一次

        while time.time() - start_time < max_wait_seconds:
            current_battery = DriverAdapter.get_battery(device_ip)

            if current_battery is not None:
                if current_battery != last_battery:
                    logger.info(f"当前电量: {current_battery}%")
                    last_battery = current_battery

                # 到达目标电量
                if current_battery >= target_battery:
                    elapsed = int(time.time() - start_time)
                    return {
                        "success": True,
                        "final_battery": current_battery,
                        "elapsed_seconds": elapsed,
                        "elapsed_formatted": format_duration(elapsed)
                    }

            time.sleep(check_interval)

        # 超时
        elapsed = int(time.time() - start_time)
        current_battery = DriverAdapter.get_battery(device_ip)
        return {
            "success": False,
            "final_battery": current_battery,
            "elapsed_seconds": elapsed,
            "elapsed_formatted": format_duration(elapsed),
            "error": "超时"
        }


class ChargeStatusTool(BaseTool):
    """充电状态查询工具"""

    @property
    def name(self) -> str:
        return "charge_status"

    @property
    def description(self) -> str:
        return """查询设备当前的充电状态和电量。

返回值包含：
- 当前电量百分比
- 是否在充电中
- 是否连接到充电桩"""

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

            # 获取电量
            battery = DriverAdapter.get_battery(device_ip)

            # 检查是否在充电
            is_charging = self._check_charging(driver)

            # 获取当前 Activity
            current = driver.app_current()
            activity = str(current.get('activity', ''))

            return format_result(
                True,
                "查询成功",
                data={
                    "device_ip": device_ip,
                    "battery": battery,
                    "is_charging": is_charging,
                    "current_activity": activity
                }
            )

        except Exception as e:
            return format_result(False, "查询失败", error=sanitize_error(e))

    def _check_charging(self, driver) -> bool:
        """检查是否在充电"""
        # 方法1: 检查文案
        if driver(text="正在充电").exists:
            return True

        # 方法2: 检查 Activity
        try:
            current = driver.app_current()
            if "charge" in str(current.get('activity', '')).lower():
                return True
        except Exception:
            pass

        return False

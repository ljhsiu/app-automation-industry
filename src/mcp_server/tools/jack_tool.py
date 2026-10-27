"""
Jack Stress Tool - 举升压测工具

封装举升压测脚本的功能，提供 MCP 接口
"""

import time
import logging
from typing import Optional
from .base_tool import BaseTool
from ..adapters.driver_adapter import DriverAdapter
from ..adapters.config_adapter import get_config
from ..utils.helpers import format_result, sanitize_error, format_duration

logger = logging.getLogger(__name__)


class JackStressTool(BaseTool):
    """举升压测工具"""

    PACKAGE = "com.keenon.solutionindustry"

    @property
    def name(self) -> str:
        return "jack_stress_test"

    @property
    def description(self) -> str:
        return """执行举升压测，测试机械臂举升/放下功能稳定性。

测试流程：
1. 在搬运任务页点击举升按钮
2. 等待 10 秒
3. 点击放下按钮
4. 等待 10 秒
5. 检测电量，必要时充电
6. 重复指定次数

支持参数：
- device_ip: 设备 IP 地址（必需）
- test_count: 测试次数，默认 3
- low_battery_threshold: 低电量阈值，默认 10%
- target_battery_threshold: 目标电量阈值，默认 80%
- auto_charge: 是否在低电量时自动充电，默认 true

返回值包含：
- 总测试次数
- 成功次数
- 失败次数
- 成功率"""

    @property
    def input_schema(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "device_ip": {
                    "type": "string",
                    "description": "设备 IP 地址"
                },
                "test_count": {
                    "type": "integer",
                    "description": "测试次数",
                    "default": 3,
                    "minimum": 1,
                    "maximum": 100
                },
                "low_battery_threshold": {
                    "type": "integer",
                    "description": "低电量阈值（%）",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 100
                },
                "target_battery_threshold": {
                    "type": "integer",
                    "description": "目标电量（%）",
                    "default": 80,
                    "minimum": 1,
                    "maximum": 100
                },
                "auto_charge": {
                    "type": "boolean",
                    "description": "低电量时是否自动充电",
                    "default": True
                }
            },
            "required": ["device_ip"]
        }

    def execute(self, arguments: dict) -> dict:
        """执行举升压测"""
        device_ip = arguments.get("device_ip")
        test_count = arguments.get("test_count", 3)
        low_battery = arguments.get("low_battery_threshold", 10)
        target_battery = arguments.get("target_battery_threshold", 80)
        auto_charge = arguments.get("auto_charge", True)

        if not device_ip:
            return format_result(False, "设备 IP 不能为空", error="device_ip is required")

        start_time = time.time()

        try:
            driver = DriverAdapter.get_driver(device_ip)

            # 确保在搬运任务页
            if not self._go_to_transport_page(driver):
                return format_result(
                    False,
                    "无法进入搬运任务页",
                    error="Failed to navigate to transport page"
                )

            success_count = 0
            fail_count = 0
            cycle_results = []

            for i in range(1, test_count + 1):
                logger.info(f"第 {i} 轮开始")

                cycle_start = time.time()
                cycle_success, cycle_data = self._do_jack_cycle(
                    driver,
                    i,
                    low_battery,
                    target_battery,
                    auto_charge
                )

                cycle_elapsed = int(time.time() - cycle_start)
                cycle_results.append({
                    "cycle": i,
                    "success": cycle_success,
                    "elapsed_seconds": cycle_elapsed,
                    "details": cycle_data
                })

                if cycle_success:
                    success_count += 1
                    logger.info(f"第 {i} 轮成功")
                else:
                    fail_count += 1
                    logger.warning(f"第 {i} 轮失败")

                # 每轮间隔
                time.sleep(1)

            elapsed = int(time.time() - start_time)
            success_rate = (success_count / test_count * 100) if test_count > 0 else 0

            # 触发充电
            if auto_charge:
                self._trigger_charge(driver)

            return format_result(
                True,
                f"举升压测完成，成功率 {success_rate:.1f}%",
                data={
                    "total_count": test_count,
                    "success_count": success_count,
                    "fail_count": fail_count,
                    "success_rate": f"{success_rate:.1f}%",
                    "elapsed_seconds": elapsed,
                    "elapsed_formatted": format_duration(elapsed),
                    "cycles": cycle_results
                }
            )

        except Exception as e:
            logger.error(f"举升压测失败: {str(e)}")
            return format_result(
                False,
                "举升压测执行失败",
                error=sanitize_error(e)
            )

    def _go_to_transport_page(self, driver) -> bool:
        """进入搬运任务页"""
        # 返回首页
        for _ in range(10):
            try:
                current = driver.app_current()
                if 'IndustryHomeActivity' in str(current.get('activity', '')):
                    break
            except Exception:
                pass

            driver.press("back")
            time.sleep(0.5)

        time.sleep(2)

        # 点击搬运模式
        transport_btn = driver(text="搬运")
        if transport_btn.exists:
            transport_btn.click()
            time.sleep(3)
            return True

        # 备用方案
        transport_btn = driver(
            resourceId=f"{self.PACKAGE}:id/tv_mode",
            text="搬运模式"
        )
        if transport_btn.exists:
            transport_btn.click()
            time.sleep(3)
            return True

        return True  # 假设已经在搬运任务页

    def _do_jack_cycle(
        self,
        driver,
        cycle_num: int,
        low_battery: int,
        target_battery: int,
        auto_charge: bool
    ) -> tuple[bool, dict]:
        """执行一轮举升-放下"""
        details = {}

        # 1. 获取初始状态
        initial_status = self._get_lift_status(driver)
        initial_button = self._get_button_text(driver)
        details["initial_status"] = initial_status
        details["initial_button"] = initial_button
        logger.info(f"初始状态: {initial_status}, 按钮: {initial_button}")

        # 2. 点击举升
        logger.info("步骤1: 举升")
        jack_success, jack_data = self._do_jack_up(driver)
        details["jack_up"] = jack_data

        if not jack_success:
            return False, details

        # 3. 等待 10 秒
        logger.info("等待 10 秒...")
        time.sleep(10)

        # 4. 点击放下
        logger.info("步骤2: 放下")
        down_success, down_data = self._do_jack_down(driver)
        details["jack_down"] = down_data

        if not down_success:
            return False, details

        # 5. 等待 10 秒
        logger.info("等待 10 秒...")
        time.sleep(10)

        # 6. 检查电量
        if auto_charge:
            # 获取设备 IP 用于查询电量
            device_ip_for_battery = device_ip.split(':')[0]
            battery = DriverAdapter.get_battery(device_ip_for_battery)
            details["battery_after"] = battery

            if battery is not None and battery < low_battery:
                logger.info(f"电量过低（{battery}%），触发充电...")
                self._auto_charge(driver, low_battery, target_battery)
                details["charged"] = True
            else:
                details["charged"] = False

        return True, details

    def _get_lift_status(self, driver) -> Optional[str]:
        """获取举升状态"""
        status_element = driver(
            resourceId=f"{self.PACKAGE}:id/tv_lift_state"
        )

        if status_element.exists:
            return status_element.get_text()

        return "未知"

    def _get_button_text(self, driver) -> Optional[str]:
        """获取按钮文案"""
        jack_button = driver(
            resourceId=f"{self.PACKAGE}:id/tv_jack"
        )

        if jack_button.exists:
            return jack_button.get_text()

        return None

    def _do_jack_up(self, driver) -> tuple[bool, dict]:
        """执行举升"""
        data = {}

        # 点击举升按钮
        jack_button = driver(
            resourceId=f"{self.PACKAGE}:id/tv_jack"
        )

        if not jack_button.exists:
            logger.error("未找到举升按钮")
            data["error"] = "Jack button not found"
            return False, data

        jack_button.click()
        data["clicked"] = True

        # 等待状态变化
        time.sleep(1)

        # 检查是否在运动中
        status = self._get_lift_status(driver)
        button = self._get_button_text(driver)
        data["status_after_click"] = status
        data["button_after_click"] = button

        # 等待最终状态
        final_status, final_button = self._wait_for_final_state(driver, timeout=10)
        data["final_status"] = final_status
        data["final_button"] = final_button

        # 判断是否成功
        success = (
            final_button == "放下" or
            "已举升" in str(final_status)
        )

        data["success"] = success

        return success, data

    def _do_jack_down(self, driver) -> tuple[bool, dict]:
        """执行放下"""
        data = {}

        jack_button = driver(
            resourceId=f"{self.PACKAGE}:id/tv_jack"
        )

        if not jack_button.exists:
            data["error"] = "Jack button not found"
            return False, data

        jack_button.click()
        data["clicked"] = True

        time.sleep(1)

        # 等待最终状态
        final_status, final_button = self._wait_for_final_state(driver, timeout=10)
        data["final_status"] = final_status
        data["final_button"] = final_button

        # 判断是否成功
        success = (
            final_button == "举升" or
            "举升" in str(final_status)
        )

        data["success"] = success

        return success, data

    def _wait_for_final_state(
        self,
        driver,
        timeout: int = 10
    ) -> tuple[Optional[str], Optional[str]]:
        """等待状态稳定"""
        start_time = time.time()
        last_status = None
        last_button = None
        stable_count = 0

        while time.time() - start_time < timeout:
            current_status = self._get_lift_status(driver)
            current_button = self._get_button_text(driver)

            # 检测变化
            if current_status != last_status or current_button != last_button:
                logger.debug(f"状态变化: {last_status}/{last_button} -> {current_status}/{current_button}")
                last_status = current_status
                last_button = current_button
                stable_count = 0
            else:
                stable_count += 1

            # 检查是否稳定
            if stable_count >= 4:  # 约 2 秒稳定
                return current_status, current_button

            time.sleep(0.5)

        return last_status, last_button

    def _auto_charge(self, driver, low_battery: int, target_battery: int):
        """自动充电"""
        # 返回首页
        for _ in range(5):
            driver.press("back")
            time.sleep(0.5)

        time.sleep(2)

        # 进入设置
        menu_btn = driver(resourceId=f"{self.PACKAGE}:id/view_menu")
        if menu_btn.exists:
            menu_btn.click()
            time.sleep(1)

        # 点击充电设置
        charge_setting = driver(text="充电设置")
        if charge_setting.exists:
            charge_setting.click()
            time.sleep(1)

        # 点击立刻充电
        charge_now = driver(text="立刻充电")
        if charge_now.exists:
            charge_now.click()
            logger.info("自动充电已触发")

    def _trigger_charge(self, driver):
        """触发充电"""
        self._auto_charge(driver, 0, 100)

"""
Driver Adapter - uiautomator2 驱动适配器

统一管理设备连接和驱动实例
"""

import logging
from typing import Optional
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class DriverInfo:
    """驱动信息"""
    serial: str
    ip: str
    package: str
    connected: bool = False


class DriverAdapter:
    """uiautomator2 驱动适配器"""

    # 驱动缓存池
    _driver_pool: dict[str, any] = {}

    # 包名常量
    PACKAGE = "com.keenon.solutionindustry"
    CHARGE_ACTIVITY = "com.keenon.industry.setting.activity.SettingHomeActivity"
    HOME_ACTIVITY = "com.keenon.industry.activity.IndustryHomeActivity"

    @classmethod
    def get_driver(cls, device_ip: str) -> any:
        """
        获取或创建驱动实例

        Args:
            device_ip: 设备 IP 地址，格式如 "192.168.3.211" 或 "192.168.3.211:5555"

        Returns:
            uiautomator2 driver 实例

        Raises:
            ConnectionError: 无法连接到设备
        """
        # 标准化 IP 地址
        address = cls._normalize_ip(device_ip)

        # 检查缓存
        if address in cls._driver_pool:
            try:
                # 验证连接是否仍然有效
                driver = cls._driver_pool[address]
                if driver.info:
                    logger.debug(f"Using cached driver for {address}")
                    return driver
            except Exception:
                # 连接失效，移除缓存
                logger.warning(f"Driver for {address} connection lost, reconnecting...")
                cls._remove_driver(address)

        # 创建新驱动
        try:
            import uiautomator2 as u2
            driver = u2.connect(address)
            cls._driver_pool[address] = driver

            logger.info(f"Connected to device: {address}, serial: {driver.serial}")
            return driver

        except Exception as e:
            logger.error(f"Failed to connect to device {address}: {str(e)}")
            raise ConnectionError(f"无法连接到设备 {address}: {str(e)}")

    @classmethod
    def release_driver(cls, device_ip: str):
        """
        释放驱动（但不关闭连接，保持连接池）

        Args:
            device_ip: 设备 IP 地址
        """
        address = cls._normalize_ip(device_ip)
        logger.debug(f"Released driver reference for {address}")

    @classmethod
    def close_driver(cls, device_ip: str):
        """
        关闭并移除驱动

        Args:
            device_ip: 设备 IP 地址
        """
        address = cls._normalize_ip(device_ip)
        cls._remove_driver(address)

    @classmethod
    def _remove_driver(cls, address: str):
        """从池中移除驱动"""
        if address in cls._driver_pool:
            del cls._driver_pool[address]
            logger.debug(f"Removed driver from pool: {address}")

    @classmethod
    def _normalize_ip(cls, device_ip: str) -> str:
        """
        标准化 IP 地址

        Args:
            device_ip: 原始 IP 地址

        Returns:
            str: 标准化后的地址 (IP:5555 格式)
        """
        if not device_ip:
            raise ValueError("设备 IP 不能为空")

        # 如果已经是 IP:Port 格式，直接返回
        if ':' in device_ip:
            return device_ip

        # 否则添加默认端口
        return f"{device_ip}:5555"

    @classmethod
    def get_device_info(cls, device_ip: str) -> dict:
        """
        获取设备信息

        Args:
            device_ip: 设备 IP 地址

        Returns:
            dict: 设备信息
        """
        driver = cls.get_driver(device_ip)

        try:
            info = driver.info
            return {
                "serial": driver.serial,
                "ip": device_ip,
                "package": cls.PACKAGE,
                "display": info.get("display", {}),
                "battery": info.get("battery", {}),
                "sdk_int": info.get("sdkInt", 0),
                "connected": True
            }
        except Exception as e:
            logger.error(f"Failed to get device info: {str(e)}")
            return {
                "serial": driver.serial if hasattr(driver, 'serial') else "unknown",
                "ip": device_ip,
                "package": cls.PACKAGE,
                "connected": False,
                "error": str(e)
            }

    @classmethod
    def get_battery(cls, device_ip: str) -> Optional[int]:
        """
        获取设备电量

        Args:
            device_ip: 设备 IP 地址

        Returns:
            int: 电量百分比，失败返回 None
        """
        from ..utils.helpers import parse_battery

        driver = cls.get_driver(device_ip)

        try:
            # 方法1: 通过 driver.info 获取
            info = driver.info
            if info and 'battery' in info:
                battery_level = info['battery'].get('level')
                if battery_level is not None:
                    return battery_level

            # 方法2: 通过 UI 元素获取
            battery_element = driver(
                resourceId=f"{cls.PACKAGE}:id/tv_battery"
            )
            if battery_element.exists:
                text = battery_element.get_text()
                return parse_battery(text)

            # 方法3: 通过 shell 命令
            battery_shell = driver.shell([
                "dumpsys", "battery"
            ])
            for line in battery_shell.output.split('\n'):
                if 'level:' in line.lower():
                    parts = line.split(':')
                    if len(parts) >= 2:
                        try:
                            return int(parts[1].strip())
                        except ValueError:
                            pass

            return None

        except Exception as e:
            logger.error(f"Failed to get battery: {str(e)}")
            return None

    @classmethod
    def is_app_running(cls, device_ip: str) -> bool:
        """
        检查 App 是否正在运行

        Args:
            device_ip: 设备 IP 地址

        Returns:
            bool: App 是否运行中
        """
        driver = cls.get_driver(device_ip)

        try:
            current = driver.app_current()
            activity = str(current.get('activity', '')).lower()
            return cls.PACKAGE in activity or 'keenon' in activity
        except Exception:
            return False

    @classmethod
    def start_app(cls, device_ip: str) -> bool:
        """
        启动 App

        Args:
            device_ip: 设备 IP 地址

        Returns:
            bool: 是否启动成功
        """
        driver = cls.get_driver(device_ip)

        try:
            driver.app_stop(cls.PACKAGE)
            driver.app_start(cls.PACKAGE, cls.HOME_ACTIVITY)
            return True
        except Exception as e:
            logger.error(f"Failed to start app: {str(e)}")
            return False

    @classmethod
    def press_back(cls, device_ip: str, times: int = 1) -> bool:
        """
        按返回键

        Args:
            device_ip: 设备 IP 地址
            times: 按键次数

        Returns:
            bool: 是否成功
        """
        driver = cls.get_driver(device_ip)

        try:
            for _ in range(times):
                driver.press("back")
            return True
        except Exception as e:
            logger.error(f"Failed to press back: {str(e)}")
            return False

    @classmethod
    def screenshot(cls, device_ip: str, filename: str) -> Optional[str]:
        """
        截图

        Args:
            device_ip: 设备 IP 地址
            filename: 保存路径

        Returns:
            str: 保存的路径，失败返回 None
        """
        driver = cls.get_driver(device_ip)

        try:
            driver.screenshot(filename)
            return filename
        except Exception as e:
            logger.error(f"Failed to take screenshot: {str(e)}")
            return None

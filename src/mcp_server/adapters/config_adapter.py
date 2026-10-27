"""
Config Adapter - 配置适配器

管理设备配置和应用设置
"""

import os
import json
import yaml
import logging
from typing import Optional
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class DeviceConfig:
    """设备配置"""
    name: str
    ip: str
    port: int = 5555
    serial: Optional[str] = None
    package: str = "com.keenon.solutionindustry"

    @property
    def address(self) -> str:
        """获取设备地址"""
        return f"{self.ip}:{self.port}"

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "name": self.name,
            "ip": self.ip,
            "port": self.port,
            "serial": self.serial,
            "package": self.package
        }


@dataclass
class ChargeConfig:
    """充电配置"""
    low_battery_threshold: int = 10
    target_battery_threshold: int = 80
    max_wait_seconds: int = 7200
    check_interval: int = 60


@dataclass
class JackStressConfig:
    """举升压测配置"""
    test_count: int = 3
    low_battery_threshold: int = 10
    target_battery_threshold: int = 80
    wait_after_action: int = 10


@dataclass
class MCPSettings:
    """MCP 服务器设置"""
    log_level: str = "INFO"
    screenshot_dir: str = "./screenshots"
    reports_dir: str = "./reports"
    device_config_path: str = "./config/device_config.yaml"
    timeout_default: int = 300


class ConfigAdapter:
    """配置适配器"""

    _instance: Optional['ConfigAdapter'] = None
    _config_dir: Path | None = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._initialized = True
        self._config_dir = self._find_config_dir()

        # 加载配置
        self.devices: dict[str, DeviceConfig] = {}
        self.current_device: str = "default"
        self.charge_config = ChargeConfig()
        self.jack_config = JackStressConfig()
        self.mcp_settings = MCPSettings()

        self._load_all_configs()

    def _find_config_dir(self) -> Path:
        """查找配置目录（返回项目根目录）"""
        possible = [
            Path(__file__).parent.parent.parent.parent,  # src/mcp_server/adapters -> 项目根
            Path(__file__).parent.parent.parent,          # fallback
            Path.cwd(),
        ]
        for p in possible:
            if (p / "config.yaml").exists():
                return p
        return possible[0]

    def _load_all_configs(self):
        """从统一 config.yaml 加载所有配置"""
        config_path = self._config_dir / "config.yaml"

        if not config_path.exists():
            logger.warning(f"config.yaml not found: {config_path}, using defaults")
            return

        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            # 设备列表
            devices_data = data.get('devices', {})
            for name, cfg in devices_data.items():
                self.devices[name] = DeviceConfig(
                    name=cfg.get('name', name),
                    ip=cfg.get('ip', ''),
                    port=cfg.get('port', 5555),
                    serial=cfg.get('serial'),
                    package=cfg.get('package', 'com.keenon.solutionindustry')
                )
            self.current_device = data.get('current_device', 'default')

            # 充电配置
            charge_cfg = data.get('charge', {})
            if charge_cfg:
                self.charge_config = ChargeConfig(
                    low_battery_threshold=charge_cfg.get('low_battery_threshold', 10),
                    target_battery_threshold=charge_cfg.get('target_battery_threshold', 80),
                    max_wait_seconds=charge_cfg.get('max_wait_seconds', 7200),
                    check_interval=charge_cfg.get('check_interval', 60)
                )

            # 举升压测配置
            jack_cfg = data.get('jack_stress', {})
            if jack_cfg:
                self.jack_config = JackStressConfig(
                    test_count=jack_cfg.get('test_count', 3),
                    low_battery_threshold=jack_cfg.get('low_battery_threshold', 10),
                    target_battery_threshold=jack_cfg.get('target_battery_threshold', 80),
                    wait_after_action=jack_cfg.get('wait_after_action', 10)
                )

            # MCP 设置
            mcp_cfg = data.get('mcp', {})
            if mcp_cfg:
                self.mcp_settings = MCPSettings(
                    log_level=mcp_cfg.get('log_level', 'INFO'),
                    screenshot_dir=mcp_cfg.get('screenshot_dir', './screenshots'),
                    reports_dir=mcp_cfg.get('reports_dir', './reports'),
                    device_config_path=str(config_path),
                    timeout_default=mcp_cfg.get('timeout_default', 300)
                )

            logger.info(f"Loaded config from {config_path}: {len(self.devices)} devices")

        except Exception as e:
            logger.error(f"Failed to load config.yaml: {str(e)}")

    def get_device(self, device_name: Optional[str] = None) -> DeviceConfig:
        """
        获取设备配置

        Args:
            device_name: 设备名称，默认使用当前设备

        Returns:
            DeviceConfig: 设备配置
        """
        if device_name is None:
            device_name = self.current_device

        if device_name not in self.devices:
            logger.warning(f"Device {device_name} not found, using default")
            device_name = 'default'

        return self.devices.get(device_name, DeviceConfig(
            name='default',
            ip='192.168.3.211'
        ))

    def get_device_by_ip(self, ip: str) -> DeviceConfig:
        """
        通过 IP 获取设备配置

        Args:
            ip: 设备 IP 地址

        Returns:
            DeviceConfig: 设备配置
        """
        # 标准化 IP
        if ':' not in ip:
            ip = f"{ip}:5555"

        # 查找匹配的设备
        for device in self.devices.values():
            if f"{device.ip}:{device.port}" == ip:
                return device

        # 如果找不到，返回默认设备但使用提供的 IP
        default = self.get_device()
        return DeviceConfig(
            name=f"临时设备 ({ip})",
            ip=ip.split(':')[0],
            port=int(ip.split(':')[1]) if ':' in ip else 5555,
            package=default.package
        )

    def list_devices(self) -> list[dict]:
        """
        列出所有设备

        Returns:
            list[dict]: 设备列表
        """
        devices = []
        for name, cfg in self.devices.items():
            devices.append({
                "name": name,
                "display_name": cfg.name,
                "ip": cfg.ip,
                "port": cfg.port,
                "address": cfg.address,
                "current": name == self.current_device
            })
        return devices

    def set_current_device(self, device_name: str) -> bool:
        """
        设置当前设备

        Args:
            device_name: 设备名称

        Returns:
            bool: 是否设置成功
        """
        if device_name not in self.devices:
            logger.error(f"Device {device_name} not found")
            return False

        self.current_device = device_name
        return True

    def reload(self):
        """重新加载配置"""
        self._load_all_configs()


# 全局配置实例
_config: Optional[ConfigAdapter] = None


def get_config() -> ConfigAdapter:
    """获取配置实例"""
    global _config
    if _config is None:
        _config = ConfigAdapter()
    return _config

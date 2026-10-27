"""工具基类"""

from abc import ABC, abstractmethod
from typing import Any


class BaseTool(ABC):
    """MCP 工具基类"""

    @property
    @abstractmethod
    def name(self) -> str:
        """工具名称"""
        pass

    @property
    @abstractmethod
    def description(self) -> str:
        """工具描述"""
        pass

    @property
    @abstractmethod
    def input_schema(self) -> dict:
        """输入模式定义"""
        pass

    @abstractmethod
    def execute(self, arguments: dict) -> Any:
        """执行工具"""
        pass

    def validate_arguments(self, arguments: dict) -> tuple[bool, str]:
        """
        验证参数

        Returns:
            tuple: (是否有效, 错误消息)
        """
        return True, ""

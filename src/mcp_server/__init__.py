"""
Industrial Automation App Testing MCP Server
工业自动化 App 测试 MCP 服务器

封装了三个核心测试脚本:
- 充电脚本 (ChargeScript)
- 下桩脚本 (UndockScript)
- 举升压测 (JackStress)
"""

__version__ = "1.0.0"
__author__ = "Industrial Automation Team"

from .server import create_server, main

__all__ = ["create_server", "main"]

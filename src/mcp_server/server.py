"""
MCP Server - 核心服务器实现

基于 FastMCP 框架实现，支持标准 MCP 协议
"""

import logging
from typing import Any
from dataclasses import dataclass

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class ToolDefinition:
    """工具定义"""
    name: str
    description: str
    input_schema: dict


class AutomationMCPServer:
    """工业自动化测试 MCP 服务器"""

    def __init__(self):
        self.tools: dict[str, Any] = {}
        self._initialized = False

    def register_tool(self, tool_class):
        """注册工具"""
        tool = tool_class()
        self.tools[tool.name] = tool
        logger.info(f"Registered tool: {tool.name}")

    def get_tool_definitions(self) -> list[dict]:
        """获取所有工具定义 (用于 MCP manifest)"""
        definitions = []
        for name, tool in self.tools.items():
            definitions.append({
                "name": tool.name,
                "description": tool.description,
                "inputSchema": tool.input_schema
            })
        return definitions

    def execute_tool(self, tool_name: str, arguments: dict) -> dict:
        """执行工具"""
        if tool_name not in self.tools:
            return {
                "success": False,
                "error": f"Unknown tool: {tool_name}"
            }

        tool = self.tools[tool_name]
        try:
            logger.info(f"Executing tool: {tool_name} with args: {arguments}")
            result = tool.execute(arguments)
            logger.info(f"Tool {tool_name} executed successfully")
            return {
                "success": True,
                "result": result
            }
        except Exception as e:
            logger.error(f"Tool {tool_name} failed: {str(e)}")
            return {
                "success": False,
                "error": str(e)
            }

    def initialize(self):
        """初始化服务器"""
        if self._initialized:
            return

        # 延迟导入，避免循环依赖
        from .tools import (
            ChargeTool,
            ChargeStatusTool,
            UndockTool,
            UndockStatusTool,
            JackStressTool,
            DeviceStatusTool,
            DeviceScreenshotTool,
            DeviceListTool,
        )

        # 注册所有工具
        self.register_tool(ChargeTool)
        self.register_tool(ChargeStatusTool)
        self.register_tool(UndockTool)
        self.register_tool(UndockStatusTool)
        self.register_tool(JackStressTool)
        self.register_tool(DeviceStatusTool)
        self.register_tool(DeviceScreenshotTool)
        self.register_tool(DeviceListTool)

        self._initialized = True
        logger.info("MCP Server initialized with %d tools", len(self.tools))


# 全局服务器实例
_server_instance: AutomationMCPServer | None = None


def create_server() -> AutomationMCPServer:
    """创建并初始化服务器"""
    global _server_instance
    if _server_instance is None:
        _server_instance = AutomationMCPServer()
        _server_instance.initialize()
    return _server_instance


def main():
    """MCP 服务器主入口 - 用于命令行直接运行"""
    import json
    import sys

    server = create_server()

    # 输出服务器信息
    info = {
        "server": "app-automation-mcp",
        "version": "1.0.0",
        "protocol_version": "2024-11-05",
        "tools": server.get_tool_definitions()
    }

    # 支持 --info 参数输出服务器信息
    if len(sys.argv) > 1 and sys.argv[1] == "--info":
        print(json.dumps(info, indent=2, ensure_ascii=False))
        return

    # MCP stdin/stdout 协议模式
    try:
        while True:
            line = sys.stdin.readline()
            if not line:
                break

            try:
                request = json.loads(line.strip())

                # 处理 MCP 请求
                method = request.get("method")
                params = request.get("params", {})
                request_id = request.get("id")

                response = {"jsonrpc": "2.0", "id": request_id}

                if method == "initialize":
                    response["result"] = {
                        "protocolVersion": "2024-11-05",
                        "serverInfo": {
                            "name": "app-automation-mcp",
                            "version": "1.0.0"
                        },
                        "capabilities": {
                            "tools": {}
                        }
                    }

                elif method == "tools/list":
                    response["result"] = {
                        "tools": server.get_tool_definitions()
                    }

                elif method == "tools/call":
                    tool_name = params.get("name")
                    arguments = params.get("arguments", {})
                    result = server.execute_tool(tool_name, arguments)
                    response["result"] = result

                else:
                    response["error"] = {
                        "code": -32601,
                        "message": f"Method not found: {method}"
                    }

                print(json.dumps(response, ensure_ascii=False))
                sys.stdout.flush()

            except json.JSONDecodeError:
                continue
            except Exception as e:
                error_response = {
                    "jsonrpc": "2.0",
                    "error": {
                        "code": -32603,
                        "message": str(e)
                    }
                }
                print(json.dumps(error_response, ensure_ascii=False))
                sys.stdout.flush()

    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error("Server error: %s", str(e))
        raise


# 便捷导入
def get_server() -> AutomationMCPServer:
    """获取服务器实例"""
    return create_server()
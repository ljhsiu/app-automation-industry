"""任务目录: 定义可执行任务、参数 schema 与默认值

设计文档 7.1 节。前端根据 TaskSpec 自动渲染参数表单，无需硬编码。

一期任务:
- sync_click_single / dual / multi : 参数化同步点击 (合并原三个编排脚本)
- adb_wireless                     : USB 转无线 ADB
- legacy_*                         : 直接调用 点击编排任务/ 下的原脚本
                                     (纯文本日志降级显示，无结构化指标)
"""

from dataclasses import dataclass, field
from typing import Any, Optional

from .config import load_webui_config


@dataclass
class ParamSpec:
    key: str
    label: str
    type: str                      # string | int | float | bool | devices | tags
    default: Any = None
    required: bool = False
    min: Optional[float] = None
    max: Optional[float] = None
    help: str = ""

    def to_dict(self) -> dict:
        return {
            "key": self.key, "label": self.label, "type": self.type,
            "default": self.default, "required": self.required,
            "min": self.min, "max": self.max, "help": self.help,
        }


@dataclass
class TaskSpec:
    id: str
    name: str
    group: str
    description: str
    script: str                    # 相对仓库根的脚本路径
    metrics_kind: str = "daemon"   # daemon(守护型) | cycle(轮次型，三期)
    params: list[ParamSpec] = field(default_factory=list)
    fixed_args: dict = field(default_factory=dict)
    uses_devices: bool = False     # 前端是否展示设备勾选区
    supports_mock: bool = False    # 是否支持 --mock 演示模式

    def to_dict(self) -> dict:
        return {
            "id": self.id, "name": self.name, "group": self.group,
            "description": self.description, "script": self.script,
            "metrics_kind": self.metrics_kind,
            "params": [p.to_dict() for p in self.params],
            "fixed_args": self.fixed_args,
            "uses_devices": self.uses_devices,
            "supports_mock": self.supports_mock,
        }


def _sync_click_params(scd: dict) -> list[ParamSpec]:
    """构造 sync_click 系列参数表 (默认值来自 config)"""
    return [
        ParamSpec("devices", "目标设备", "devices", default=[],
                  help="留空 = 自动使用全部在线设备"),
        ParamSpec("button_id", "按钮 resourceId", "string",
                  default=scd["button_id"], required=True,
                  help="监听的确定按钮 resource-id"),
        ParamSpec("filter_texts", "过滤文本", "tags",
                  default=scd["filter_texts"],
                  help="按钮文本命中则不点击，逗号分隔"),
        ParamSpec("poll_interval", "轮询间隔(秒)", "float",
                  default=scd["poll_interval"], min=0.1, max=5),
        ParamSpec("click_cooldown", "点击后冷却(秒)", "float",
                  default=scd["click_cooldown"], min=0.5, max=30),
        ParamSpec("connect_retries", "连接重试次数", "int",
                  default=scd["connect_retries"], min=1, max=10),
    ]


def build_tasks() -> list[TaskSpec]:
    scd = load_webui_config()["sync_click_defaults"]
    return [
        TaskSpec(
            id="sync_click_single", name="单机监听",
            group="点击编排任务",
            description="监听单台设备，目标按钮出现即点击（过滤「结束调度」）。"
                        "对应原脚本: 单线程任务编排.py",
            script="webui/tasks/sync_click.py",
            params=_sync_click_params(scd),
            fixed_args={"require_all": False, "device_mode": "first"},
            uses_devices=True, supports_mock=True,
        ),
        TaskSpec(
            id="sync_click_dual", name="双机同步",
            group="点击编排任务",
            description="两台设备全部出现目标按钮后才同时点击。"
                        "对应原脚本: 双线程任务编排.py",
            script="webui/tasks/sync_click.py",
            params=_sync_click_params(scd),
            fixed_args={"require_all": True},
            uses_devices=True, supports_mock=True,
        ),
        TaskSpec(
            id="sync_click_multi", name="多机同步",
            group="点击编排任务",
            description="N 台设备全部出现目标按钮后才同步点击。"
                        "对应原脚本: 多机同步任务编排.py",
            script="webui/tasks/sync_click.py",
            params=_sync_click_params(scd),
            fixed_args={"require_all": True},
            uses_devices=True, supports_mock=True,
        ),
        TaskSpec(
            id="adb_wireless", name="无线 ADB 连接",
            group="设备管理",
            description="USB 连接状态下，一键切换为无线 ADB（tcpip 5555 并自动连接）。"
                        "对应原脚本: adbconnect.py（已移除阻塞式 input()）",
            script="webui/tasks/adb_wireless.py",
            params=[
                ParamSpec("serial", "USB 设备序列号", "string", default="",
                          help="留空 = 自动取第一台 USB 设备"),
                ParamSpec("port", "端口", "int", default=5555, min=1024, max=65535),
            ],
            supports_mock=True,
        ),
        # ---- 原脚本直接调用 (纯文本日志降级，无结构化指标) ----
        TaskSpec(
            id="legacy_single", name="单机监听（原脚本）",
            group="点击编排任务（原脚本·参数硬编码）",
            description="直接以子进程运行 点击编排任务/单线程任务编排.py，"
                        "日志为纯文本展示，参数在脚本内硬编码。",
            script="点击编排任务/单线程任务编排.py",
        ),
        TaskSpec(
            id="legacy_dual", name="双机同步（原脚本）",
            group="点击编排任务（原脚本·参数硬编码）",
            description="直接以子进程运行 点击编排任务/双线程任务编排.py，"
                        "设备地址硬编码于脚本内。",
            script="点击编排任务/双线程任务编排.py",
        ),
        TaskSpec(
            id="legacy_multi", name="多机同步（原脚本）",
            group="点击编排任务（原脚本·参数硬编码）",
            description="直接以子进程运行 点击编排任务/多机同步任务编排.py，"
                        "自动检测全部 adb 设备。",
            script="点击编排任务/多机同步任务编排.py",
        ),
    ]


_tasks: list[TaskSpec] | None = None


def get_registry() -> list[TaskSpec]:
    """获取任务目录 (单例)"""
    global _tasks
    if _tasks is None:
        _tasks = build_tasks()
    return _tasks


def get_task(task_id: str) -> TaskSpec | None:
    for t in get_registry():
        if t.id == task_id:
            return t
    return None

"""结构化事件助手 (JSONL over stdout)

供 webui/tasks/*.py 任务脚本 import 使用，向 stdout 输出
JSON Lines 结构化事件，由引擎侧 runner 解析为实时日志与监控指标。

注意: 本模块必须保持纯标准库实现 —— 任务脚本以子进程方式运行，
不得引入 fastapi 等 Web 依赖。

事件契约详见 docs/WEBUI_开发方案.md 第 6 章。
"""

import json
import sys
import time

# 相对任务启动的秒数基准
_start_ts = time.monotonic()


def init(start_ts: float | None = None) -> None:
    """初始化时间基准，并修复 Windows stdout 编码 (参考 transport_stress_base.py 的既有做法)"""
    global _start_ts
    _start_ts = start_ts if start_ts is not None else time.monotonic()
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


def emit(ev: str, **fields) -> None:
    """输出一条结构化事件 (自动补 ts，自动 flush)"""
    obj = {"ts": round(time.monotonic() - _start_ts, 2), "ev": ev}
    obj.update(fields)
    try:
        print(json.dumps(obj, ensure_ascii=False), flush=True)
    except Exception:
        # 事件输出失败不应影响任务主流程
        pass


def log(msg: str, level: str = "info") -> None:
    """普通日志事件"""
    emit("log", level=level, msg=str(msg))


def phase(name: str) -> None:
    """任务阶段: connecting / ready / running / stopped / failed"""
    emit("phase", phase=name)


def error(msg: str, fatal: bool = False, **extra) -> None:
    """异常事件; fatal=True 表示任务无法继续"""
    emit("error", msg=str(msg), fatal=fatal, **extra)


def device(addr: str, name: str, online: bool, btn_ready: bool, text: str = "") -> None:
    """设备状态变化事件 (调用方负责去抖: 仅状态变化时才发送)"""
    emit("device", addr=addr, name=name, online=online, btn_ready=btn_ready, text=text)


def batch(seq: int, n: int, wait_ms: int) -> None:
    """同步批次触发事件"""
    emit("batch", seq=seq, n=n, wait_ms=wait_ms)


def click(seq: int, addr: str, ok: bool, x: int = 0, y: int = 0,
          cost_ms: int = 0, err: str | None = None) -> None:
    """单次点击结果事件"""
    emit("click", seq=seq, addr=addr, ok=ok, x=x, y=y, cost_ms=cost_ms, err=err)


def summary(**fields) -> None:
    """任务结束汇总 (退出前最后一条)"""
    emit("summary", **fields)

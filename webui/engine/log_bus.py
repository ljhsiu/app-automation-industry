"""日志总线: 环形缓冲 + WebSocket 订阅广播 + seq 断线补齐

设计文档 7.3 节。每个 run 一个 RunChannel:
- deque(maxlen=N) 环形缓冲，每行带自增 seq (供断线重连按 ?from=seq 补齐)
- 订阅者为 asyncio.Queue；读取线程通过 loop.call_soon_threadsafe 跨线程投递
- 队列满时丢弃最旧条目，防止慢客户端拖垮服务

BusItem.kind:
- "log"     普通日志行 (含降级文本与结构化事件渲染结果)
- "status"  运行状态变化 (payload: {status, exit_code, ended_at})
- "metrics" 指标快照 (payload: DaemonMetrics.snapshot)
"""

import asyncio
import itertools
import threading
from collections import deque
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class BusItem:
    kind: str                    # "log" | "status" | "metrics"
    seq: int
    ts: float
    level: str = "info"
    text: str = ""
    payload: Optional[dict] = None

    def to_dict(self) -> dict:
        if self.kind == "log":
            return {"seq": self.seq, "ts": self.ts, "level": self.level, "text": self.text}
        return {"seq": self.seq, "ts": self.ts, "payload": self.payload}


class RunChannel:
    """单个 run 的日志通道 (线程安全)"""

    def __init__(self, run_id: str, buffer_size: int = 5000):
        self.run_id = run_id
        self._buffer: deque[BusItem] = deque(maxlen=buffer_size)
        self._seq = itertools.count(1)
        self._lock = threading.Lock()
        self._subscribers: set[asyncio.Queue] = set()
        self.dropped = 0

    # ---- 推送侧 (任意线程可调用) ----
    def push_log(self, ts: float, level: str, text: str) -> None:
        self._push(BusItem("log", next(self._seq), ts, level, text))

    def push_status(self, ts: float, payload: dict) -> None:
        self._push(BusItem("status", next(self._seq), ts, payload=payload))

    def push_metrics(self, ts: float, payload: dict) -> None:
        # metrics 不进环形缓冲 (历史快照无意义)，仅广播给在线订阅者
        item = BusItem("metrics", next(self._seq), ts, payload=payload)
        self._deliver_to_subscribers(item)

    def _push(self, item: BusItem) -> None:
        with self._lock:
            self._buffer.append(item)
        self._deliver_to_subscribers(item)

    def _deliver_to_subscribers(self, item: BusItem) -> None:
        loop = _LOG_BUS.loop
        for q in list(self._subscribers):
            if loop is not None and loop.is_running():
                try:
                    loop.call_soon_threadsafe(self._put, q, item)
                except RuntimeError:
                    pass
            else:
                self._put(q, item)

    @staticmethod
    def _put(q: asyncio.Queue, item: BusItem) -> None:
        try:
            q.put_nowait(item)
        except asyncio.QueueFull:
            try:
                q.get_nowait()  # 丢弃最旧，防止慢客户端堆积
            except asyncio.QueueEmpty:
                pass
            try:
                q.put_nowait(item)
            except asyncio.QueueFull:
                pass

    # ---- 订阅侧 (asyncio 上下文调用) ----
    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        self._subscribers.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue) -> None:
        self._subscribers.discard(q)

    # ---- 查询侧 ----
    def tail(self, from_seq: int = 0, limit: int = 2000) -> tuple[list[dict], int]:
        """返回 seq > from_seq 的缓冲行 (最多 limit 条) 与当前最大 seq"""
        with self._lock:
            items = [it for it in self._buffer if it.kind != "metrics" and it.seq > from_seq]
            max_seq = self._buffer[-1].seq if self._buffer else 0
        return [it.to_dict() for it in items[:limit]], max_seq


class LogBus:
    """全局日志总线 (单例)"""

    def __init__(self, buffer_size: int = 5000):
        self.buffer_size = buffer_size
        self._channels: dict[str, RunChannel] = {}
        self._lock = threading.Lock()
        self.loop: Optional[asyncio.AbstractEventLoop] = None

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self.loop = loop

    def create(self, run_id: str) -> RunChannel:
        with self._lock:
            ch = RunChannel(run_id, self.buffer_size)
            self._channels[run_id] = ch
            return ch

    def get(self, run_id: str) -> Optional[RunChannel]:
        with self._lock:
            return self._channels.get(run_id)


_LOG_BUS: Optional[LogBus] = None


def get_bus() -> LogBus:
    """获取全局日志总线单例"""
    global _LOG_BUS
    if _LOG_BUS is None:
        from .config import load_webui_config
        _LOG_BUS = LogBus(load_webui_config()["log_buffer_size"])
    return _LOG_BUS

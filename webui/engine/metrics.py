"""指标聚合: 结构化事件 → 守护型(daemon)实时指标

设计文档 7.4 / 8.1 节。点击编排任务是守护监听型任务 (非轮次型)，
指标以同步批次、点击成功率、同步等待耗时为核心。

广播降频: dirty 标志由 app.py 的指标广播协程消费 (默认 500ms 合并推送)。
"""

import threading
import time
from dataclasses import dataclass, field


@dataclass
class DeviceState:
    addr: str
    name: str = ""
    online: bool = False
    btn_ready: bool = False
    text: str = ""
    was_offline: bool = False   # 是否经历过掉线 (用于重连计数)


class DaemonMetrics:
    """守护型任务指标聚合器 (单 run 专用，由读取线程 feed，事件循环 snapshot)"""

    def __init__(self, started_epoch: float):
        self.started_epoch = started_epoch
        self.phase = "starting"
        self.devices: dict[str, DeviceState] = {}
        self.batches = 0
        self.clicks_ok = 0
        self.clicks_fail = 0
        self.waits: list[tuple[int, int]] = []   # (batch_seq, wait_ms)，最多保留 200
        self.consecutive_fails = 0
        self.reconnects = 0
        self.last_error: str | None = None
        self.summary: dict | None = None
        self.dirty = True
        self._lock = threading.Lock()

    # ---- 写入侧 (读取线程) ----
    def feed(self, evt: dict) -> None:
        ev = evt.get("ev")
        with self._lock:
            if ev == "device":
                self._feed_device(evt)
            elif ev == "batch":
                self.batches += 1
                wait = int(evt.get("wait_ms") or 0)
                self.waits.append((int(evt.get("seq") or self.batches), wait))
                if len(self.waits) > 200:
                    self.waits = self.waits[-200:]
            elif ev == "click":
                if evt.get("ok"):
                    self.clicks_ok += 1
                    self.consecutive_fails = 0
                else:
                    self.clicks_fail += 1
                    self.consecutive_fails += 1
            elif ev == "phase":
                self.phase = str(evt.get("phase") or self.phase)
            elif ev == "error":
                self.last_error = str(evt.get("msg") or "")
            elif ev == "summary":
                self.summary = {k: v for k, v in evt.items() if k not in ("ts", "ev")}
            self.dirty = True

    def _feed_device(self, evt: dict) -> None:
        addr = str(evt.get("addr") or "")
        if not addr:
            return
        st = self.devices.get(addr)
        if st is None:
            st = DeviceState(addr=addr)
            self.devices[addr] = st
        online = bool(evt.get("online"))
        if online and st.was_offline:
            self.reconnects += 1
            st.was_offline = False
        if not online:
            st.was_offline = True
        st.online = online
        st.btn_ready = bool(evt.get("btn_ready"))
        st.text = str(evt.get("text") or "")
        if not st.name:
            st.name = str(evt.get("name") or addr)
        elif evt.get("name"):
            st.name = str(evt["name"])

    # ---- 读取侧 (事件循环 / API) ----
    def snapshot(self) -> dict:
        with self._lock:
            self.dirty = False
            devices = [
                {"addr": s.addr, "name": s.name, "online": s.online,
                 "btn_ready": s.btn_ready, "text": s.text}
                for s in self.devices.values()
            ]
            wait_vals = [w for _, w in self.waits]
            total_clicks = self.clicks_ok + self.clicks_fail
            sorted_waits = sorted(wait_vals)
            return {
                "kind": "daemon",
                "phase": self.phase,
                "duration_s": round(time.time() - self.started_epoch, 1),
                "device_total": len(devices),
                "online_count": sum(1 for d in devices if d["online"]),
                "ready_count": sum(1 for d in devices if d["btn_ready"]),
                "devices": devices,
                "batches": self.batches,
                "clicks_ok": self.clicks_ok,
                "clicks_fail": self.clicks_fail,
                "click_success_rate": round(self.clicks_ok / total_clicks * 100, 1) if total_clicks else None,
                "avg_wait_ms": round(sum(wait_vals) / len(wait_vals)) if wait_vals else None,
                "max_wait_ms": max(wait_vals) if wait_vals else None,
                "p95_wait_ms": (sorted_waits[int(0.95 * (len(sorted_waits) - 1))] if sorted_waits else None),
                "wait_series": [list(t) for t in self.waits[-100:]],
                "consecutive_fails": self.consecutive_fails,
                "reconnects": self.reconnects,
                "last_error": self.last_error,
                "summary": self.summary,
            }


class MetricsStore:
    """全局指标仓库: run_id → DaemonMetrics"""

    def __init__(self):
        self._store: dict[str, DaemonMetrics] = {}
        self._lock = threading.Lock()

    def get_or_create(self, run_id: str, started_epoch: float) -> DaemonMetrics:
        with self._lock:
            m = self._store.get(run_id)
            if m is None:
                m = DaemonMetrics(started_epoch)
                self._store[run_id] = m
            return m

    def get(self, run_id: str) -> DaemonMetrics | None:
        with self._lock:
            return self._store.get(run_id)

    def snapshot(self, run_id: str) -> dict | None:
        m = self.get(run_id)
        return m.snapshot() if m else None

    def iter_dirty(self):
        with self._lock:
            items = [(rid, m) for rid, m in self._store.items() if m.dirty]
        return items

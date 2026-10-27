"""设备服务: adb 扫描 / 型号与电量缓存

设计文档 7.5 节。所有 subprocess 调用带 timeout，防 adb 卡死拖住 Web 请求；
Windows 下加 CREATE_NO_WINDOW 避免弹黑框。
"""

import os
import subprocess
import threading
import time
from dataclasses import dataclass

_CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0

# 缓存: {"scan": (ts, items), "detail": {addr: (ts, model, battery)}}
_cache: dict = {"scan": (0.0, []), "detail": {}}
_lock = threading.Lock()


@dataclass
class DeviceInfo:
    addr: str
    state: str = "device"         # device | offline | unauthorized
    wireless: bool = False
    model: str | None = None
    battery: int | None = None
    busy_run_id: str | None = None

    def to_dict(self) -> dict:
        return {
            "addr": self.addr,
            "state": self.state,
            "wireless": self.wireless,
            "model": self.model,
            "battery": self.battery,
            "busy_run_id": self.busy_run_id,
        }


def _run(cmd: list[str], timeout: float = 5.0) -> str:
    """执行 adb 命令，返回 stdout；失败或超时返回空串"""
    try:
        r = subprocess.run(
            cmd, capture_output=True, text=True, timeout=timeout,
            creationflags=_CREATE_NO_WINDOW, encoding="utf-8", errors="replace",
        )
        return r.stdout or ""
    except Exception:
        return ""


def scan(force: bool = False, ttl: float = 5.0) -> list[DeviceInfo]:
    """扫描 adb devices (默认 5 秒缓存，避免前端轮询时频繁调 adb)"""
    now = time.time()
    with _lock:
        ts, items = _cache["scan"]
        if not force and items and now - ts < ttl:
            return items

    out = _run(["adb", "devices"])
    infos: list[DeviceInfo] = []
    for line in out.strip().splitlines():
        # 跳过 "List of devices attached" 与空行
        if not line.strip() or line.startswith("List"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        addr, state = parts[0], parts[1]
        infos.append(DeviceInfo(addr=addr, state=state, wireless=":" in addr))

    with _lock:
        _cache["scan"] = (now, infos)
    return infos


def device_detail(addr: str, ttl: float = 30.0) -> tuple[str | None, int | None]:
    """获取设备型号与电量 (30s TTL 缓存，首次查询较慢)"""
    now = time.time()
    with _lock:
        hit = _cache["detail"].get(addr)
        if hit and now - hit[0] < ttl:
            return hit[1], hit[2]

    model_out = _run(["adb", "-s", addr, "shell", "getprop", "ro.product.model"]).strip()
    model = model_out or None

    battery: int | None = None
    bat_out = _run(["adb", "-s", addr, "shell", "dumpsys", "battery"])
    for line in bat_out.splitlines():
        if "level:" in line:
            try:
                battery = int(line.split(":", 1)[1].strip())
            except ValueError:
                pass
            break

    with _lock:
        _cache["detail"][addr] = (now, model, battery)
    return model, battery


def scan_with_details(force: bool = False, ttl_detail: float = 30.0) -> list[DeviceInfo]:
    """扫描并附带型号/电量 (仅对 state=device 的设备查询详情)"""
    infos = scan(force=force)
    for info in infos:
        if info.state == "device":
            info.model, info.battery = device_detail(info.addr, ttl_detail)
    return infos

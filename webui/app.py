"""AMR 压测 Web UI 控制台 — FastAPI 应用

REST + WebSocket 契约见 docs/WEBUI_开发方案.md 7.8 节。

启动:
    python -m uvicorn webui.app:app --host 127.0.0.1 --port 8000
或直接双击 start_webui.bat
"""

import asyncio
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .engine import devices as device_svc
from .engine.config import load_webui_config
from .engine.log_bus import get_bus
from .engine.registry import get_registry, get_task
from .engine.runner import DeviceBusyError, get_runner

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("webui.app")

STATIC_DIR = Path(__file__).resolve().parent / "static"

_cfg = load_webui_config()
_runner = get_runner()
_bus = get_bus()


# ============================================================
# 指标广播协程: 500ms 合并推送，避免高频点击压垮 WebSocket
# ============================================================

async def _metrics_broadcaster() -> None:
    interval = float(_cfg["metrics_push_interval"])
    while True:
        await asyncio.sleep(interval)
        for run_id, m in _runner.metrics.iter_dirty():
            snap = m.snapshot()
            ch = _bus.get(run_id)
            if ch is not None:
                ch.push_metrics(time.time(), snap)


@asynccontextmanager
async def lifespan(app: FastAPI):
    _bus.set_loop(asyncio.get_running_loop())
    broadcaster = asyncio.create_task(_metrics_broadcaster())
    logger.info(f"Web UI 服务启动 | 日志目录: {_cfg['log_dir']}")
    yield
    broadcaster.cancel()
    logger.info("服务关闭中，停止全部运行任务...")
    _runner.stop_all()


app = FastAPI(title="AMR 压测控制台", version="0.1.0", lifespan=lifespan)


# ============================================================
# 页面与静态资源
# ============================================================

@app.get("/")
async def index():
    return FileResponse(STATIC_DIR / "index.html")


app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")


# ============================================================
# 基础与健康检查
# ============================================================

@app.get("/api/health")
async def health():
    return {"ok": True, "time": time.time()}


# ============================================================
# 任务目录
# ============================================================

@app.get("/api/tasks")
async def list_tasks():
    return [t.to_dict() for t in get_registry()]


# ============================================================
# 设备
# ============================================================

@app.get("/api/devices")
async def list_devices():
    infos = device_svc.scan_with_details(force=False, ttl_detail=float(_cfg["device_cache_ttl"]))
    occupied = _runner.occupied_devices()
    out = []
    for info in infos:
        d = info.to_dict()
        d["busy_run_id"] = occupied.get(info.addr)
        out.append(d)
    return out


@app.post("/api/adb/scan")
async def adb_scan():
    infos = device_svc.scan_with_details(force=True, ttl_detail=float(_cfg["device_cache_ttl"]))
    occupied = _runner.occupied_devices()
    out = []
    for info in infos:
        d = info.to_dict()
        d["busy_run_id"] = occupied.get(info.addr)
        out.append(d)
    return out


# ============================================================
# 运行管理
# ============================================================

@app.post("/api/runs")
async def start_run(request: Request):
    try:
        data = await request.json()
    except Exception:
        return JSONResponse(status_code=400, content={"detail": {"code": "BAD_JSON", "message": "请求体必须是 JSON"}})

    task_id = data.get("task_id")
    params = data.get("params") or {}
    task = get_task(str(task_id or ""))
    if task is None:
        return JSONResponse(status_code=404, content={
            "detail": {"code": "TASK_NOT_FOUND", "message": f"任务不存在: {task_id}"}})

    try:
        rec = await asyncio.to_thread(_runner.start, task, params)
    except DeviceBusyError as e:
        return JSONResponse(status_code=409, content={
            "detail": {"code": "DEVICE_BUSY", "message": str(e),
                       "addr": e.addr, "run_id": e.run_id}})

    if rec.status == "failed" and rec.pid is None:
        return JSONResponse(status_code=500, content={
            "detail": {"code": "SPAWN_FAILED", "message": "子进程启动失败，详见日志",
                       "run_id": rec.run_id}})
    return {"run_id": rec.run_id, "status": rec.status}


@app.get("/api/runs")
async def list_runs():
    runs = []
    for rec in _runner.list_runs():
        s = rec.to_summary()
        snap = _runner.metrics.snapshot(rec.run_id)
        if snap:
            s["batches"] = snap["batches"]
            s["clicks_ok"] = snap["clicks_ok"]
            s["clicks_fail"] = snap["clicks_fail"]
        runs.append(s)
    return runs


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    rec = _runner.get(run_id)
    if rec is None:
        return JSONResponse(status_code=404, content={
            "detail": {"code": "RUN_NOT_FOUND", "message": f"运行不存在: {run_id}"}})
    return {"run": rec.to_summary(), "metrics": _runner.metrics.snapshot(run_id)}


@app.post("/api/runs/{run_id}/stop")
async def stop_run(run_id: str):
    rec = _runner.get(run_id)
    if rec is None:
        return JSONResponse(status_code=404, content={
            "detail": {"code": "RUN_NOT_FOUND", "message": f"运行不存在: {run_id}"}})
    result = await asyncio.to_thread(_runner.stop, run_id)
    return result


@app.get("/api/runs/{run_id}/logs")
async def get_logs(run_id: str, from_seq: int = Query(0, alias="from"), limit: int = 2000):
    ch = _bus.get(run_id)
    if ch is None:
        return JSONResponse(status_code=404, content={
            "detail": {"code": "RUN_NOT_FOUND", "message": f"运行不存在: {run_id}"}})
    lines, next_seq = ch.tail(from_seq, limit)
    return {"lines": lines, "next_seq": next_seq}


@app.get("/api/runs/{run_id}/logfile")
async def download_logfile(run_id: str):
    rec = _runner.get(run_id)
    if rec is None or not Path(rec.log_path).exists():
        return JSONResponse(status_code=404, content={
            "detail": {"code": "LOG_NOT_FOUND", "message": "日志文件不存在"}})
    return FileResponse(rec.log_path, filename=f"{run_id}.log",
                        media_type="text/plain; charset=utf-8")


# ============================================================
# WebSocket: 实时日志 / 指标 / 状态推送
# ============================================================

@app.websocket("/ws/runs/{run_id}")
async def ws_run(ws: WebSocket, run_id: str):
    rec = _runner.get(run_id)
    if rec is None:
        await ws.close(code=4004)
        return

    await ws.accept()
    ch = _bus.get(run_id)

    # 首次连接推送全量快照，再进入增量推送
    await ws.send_json({
        "type": "hello",
        "data": {"run": rec.to_summary(), "metrics": _runner.metrics.snapshot(run_id)},
    })

    if ch is None:
        await ws.close()
        return

    q = ch.subscribe()
    try:
        pending = None
        while True:
            item = pending if pending is not None else await q.get()
            pending = None

            if item.kind == "metrics":
                await ws.send_json({"type": "metrics", "data": item.payload})
            elif item.kind == "status":
                await ws.send_json({"type": "status", "data": item.payload})
            else:
                # 日志批量推送: 一次性排空队列中连续的 log 项，减少帧数
                group = [item]
                while len(group) < 50:
                    try:
                        nxt = q.get_nowait()
                    except asyncio.QueueEmpty:
                        break
                    if nxt.kind == "log":
                        group.append(nxt)
                    else:
                        pending = nxt
                        break
                await ws.send_json({
                    "type": "log",
                    "lines": [it.to_dict() for it in group],
                })
    except WebSocketDisconnect:
        pass
    except Exception as e:
        logger.warning(f"WS 异常 ({run_id}): {e}")
    finally:
        ch.unsubscribe(q)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("webui.app:app", host=_cfg["host"], port=int(_cfg["port"]))

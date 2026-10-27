#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Web UI 无真机自动冒烟检查 (纯标准库，无需安装额外依赖)

前置条件: Web UI 服务已启动 (双击 start_webui.bat 或手动 uvicorn)。
用法:
    python tools/webui_smoke_check.py [--port 8000]

覆盖项 (对应 docs/WEBUI_冒烟自测用例.md 的 A 组):
  A1 健康检查与任务目录
  A2 演示模式启动双机同步 → JSONL 事件解析 → 指标聚合
  A3 日志断线补齐接口 (按 seq 增量)
  A4 优雅停止 (退出码 0) 与最终状态
  A5 无线 ADB 演示任务自动完成
  A6 设备占用冲突 → HTTP 409
  A7 原脚本降级调用 (纯文本日志，无指标)
  A8 日志文件落盘检查 (中文编码)

注意: WebSocket 通道需在浏览器中人工验证 (见用例文档 B 组)。
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

# GBK 控制台下防止 emoji/中文打印崩溃
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

REPO_ROOT = Path(__file__).resolve().parents[1]


class Smoke:
    def __init__(self, port: int):
        self.base = f"http://127.0.0.1:{port}"
        self.passed = 0
        self.failed = 0

    def req(self, method: str, path: str, body: dict | None = None, timeout: int = 15):
        url = self.base + path
        data = json.dumps(body).encode("utf-8") if body is not None else None
        r = urllib.request.Request(
            url, data=data, method=method,
            headers={"Content-Type": "application/json"} if data else {},
        )
        with urllib.request.urlopen(r, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def req_status(self, method: str, path: str, body: dict | None = None, timeout: int = 15):
        """返回 (status, body)，非 2xx 也不抛异常"""
        try:
            return self.req(method, path, body, timeout)
        except urllib.error.HTTPError as e:
            try:
                return e.code, json.loads(e.read().decode("utf-8"))
            except Exception:
                return e.code, {}

    def check(self, name: str, cond: bool, detail: str = ""):
        if cond:
            self.passed += 1
            print(f"  [PASS] {name}")
        else:
            self.failed += 1
            print(f"  [FAIL] {name}  {detail}")

    def wait_run_status(self, run_id: str, statuses: list[str], timeout: float = 30.0) -> dict:
        end = time.time() + timeout
        last = {}
        while time.time() < end:
            _, data = self.req("GET", f"/api/runs/{run_id}")
            last = data
            if data.get("run", {}).get("status") in statuses:
                return data
            time.sleep(0.5)
        return last


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    s = Smoke(args.port)

    print(f"== Web UI 冒烟检查 @ {s.base} ==\n")

    # ---- A1 健康检查与任务目录 ----
    print("[A1] 健康检查与任务目录")
    try:
        code, health = s.req("GET", "/api/health")
        s.check("健康检查 /api/health", code == 200 and health.get("ok"))
    except Exception as e:
        print(f"  [FAIL] 无法连接服务: {e}")
        print("        请先双击 start_webui.bat 启动服务")
        return 1
    code, tasks = s.req("GET", "/api/tasks")
    task_ids = {t["id"] for t in tasks}
    s.check("任务目录包含 7 个任务", len(tasks) >= 7, f"实际 {len(tasks)}")
    s.check("包含 sync_click 三预设", {"sync_click_single", "sync_click_dual", "sync_click_multi"} <= task_ids)
    s.check("包含 legacy 原脚本任务", {"legacy_single", "legacy_dual", "legacy_multi"} <= task_ids)
    s.check("包含 adb_wireless", "adb_wireless" in task_ids)

    # ---- A2 演示模式双机同步 ----
    print("\n[A2] 演示模式启动双机同步")
    devs = ["MOCK-1", "MOCK-2"]
    code, r = s.req("POST", "/api/runs", {
        "task_id": "sync_click_dual",
        "params": {"devices": devs, "mock": True,
                   "poll_interval": 0.3, "click_cooldown": 1.0},
    })
    s.check("启动成功返回 run_id", code == 200 and r.get("run_id"), f"HTTP {code}: {r}")
    run_id = r.get("run_id")
    if not run_id:
        print("后续用例依赖 run_id，终止。")
        return 1

    # 等任务产生批次
    deadline = time.time() + 30
    metrics = {}
    while time.time() < deadline:
        _, data = s.req("GET", f"/api/runs/{run_id}")
        metrics = data.get("metrics") or {}
        if metrics.get("batches", 0) >= 2:
            break
        time.sleep(1)
    s.check("运行状态为 running", metrics.get("phase") == "running", f"phase={metrics.get('phase')}")
    s.check("产生 >=2 个同步批次", metrics.get("batches", 0) >= 2, f"batches={metrics.get('batches')}")
    s.check("点击成功数 >0", (metrics.get("clicks_ok") or 0) > 0)
    s.check("设备状态含 2 台 MOCK 设备", metrics.get("device_total") == 2,
            f"device_total={metrics.get('device_total')}")
    s.check("wait_series 有序列数据", len(metrics.get("wait_series") or []) >= 1)

    # ---- A3 日志断线补齐 ----
    print("\n[A3] 日志增量接口")
    code, d1 = s.req("GET", f"/api/runs/{run_id}/logs?from=0&limit=50")
    s.check("首批日志可获取", code == 200 and len(d1.get("lines", [])) > 0)
    from_seq = d1.get("next_seq", 0)
    code, d2 = s.req("GET", f"/api/runs/{run_id}/logs?from={from_seq}&limit=100")
    new_lines = d2.get("lines", [])
    s.check("增量补齐不重复 (seq 均 > from)",
            all(ln["seq"] > from_seq for ln in new_lines) if new_lines else True)

    # ---- A4 优雅停止 ----
    print("\n[A4] 优雅停止")
    code, _ = s.req("POST", f"/api/runs/{run_id}/stop")
    s.check("停止接口返回成功", code == 200)
    final = s.wait_run_status(run_id, ["stopped", "failed"], timeout=15)
    run = final.get("run", {})
    s.check("最终状态为 stopped (优雅退出)", run.get("status") == "stopped",
            f"status={run.get('status')} exit_code={run.get('exit_code')}")
    s.check("退出码为 0", run.get("exit_code") == 0, f"exit_code={run.get('exit_code')}")

    # ---- A5 无线 ADB 演示任务 ----
    print("\n[A5] 无线 ADB 演示任务")
    code, r = s.req("POST", "/api/runs", {"task_id": "adb_wireless", "params": {"mock": True}})
    s.check("启动成功", code == 200 and r.get("run_id"))
    if r.get("run_id"):
        final = s.wait_run_status(r["run_id"], ["stopped", "failed"], timeout=20)
        run = final.get("run", {})
        s.check("自动完成且退出码 0", run.get("status") == "stopped" and run.get("exit_code") == 0,
                f"status={run.get('status')} exit_code={run.get('exit_code')}")

    # ---- A6 设备占用冲突 ----
    print("\n[A6] 设备占用冲突")
    code, r1 = s.req("POST", "/api/runs", {
        "task_id": "sync_click_single",
        "params": {"devices": ["MOCK-X"], "mock": True},
    })
    s.check("首个 run 启动成功", code == 200 and r1.get("run_id"))
    time.sleep(2.0)   # 等待首个 run 进入 running 并登记设备占用
    code2, r2 = s.req_status("POST", "/api/runs", {
        "task_id": "sync_click_single",
        "params": {"devices": ["MOCK-X"], "mock": True},
    })
    s.check("重复占用同设备返回 409", code2 == 409, f"HTTP {code2}")
    s.check("409 响应带 DEVICE_BUSY 码",
            (r2.get("detail") or {}).get("code") == "DEVICE_BUSY", str(r2))
    if r1.get("run_id"):
        s.req("POST", f"/api/runs/{r1['run_id']}/stop")

    # ---- A7 原脚本降级调用 ----
    print("\n[A7] 原脚本降级调用 (多机同步任务编排.py)")
    code, r = s.req("POST", "/api/runs", {"task_id": "legacy_multi", "params": {}})
    s.check("原脚本启动成功", code == 200 and r.get("run_id"))
    if r.get("run_id"):
        # 无设备时应快速失败退出 (打印 🛑 后 exit 1)
        final = s.wait_run_status(r["run_id"], ["stopped", "failed"], timeout=30)
        run = final.get("run", {})
        s.check("无设备时退出且状态为 failed", run.get("status") == "failed",
                f"status={run.get('status')}")
        _, d = s.req("GET", f"/api/runs/{r['run_id']}/logs?from=0&limit=100")
        texts = [ln["text"] for ln in d.get("lines", []) if "text" in ln]
        s.check("纯文本日志降级可读 (含中文)",
                any("未检测到" in t or "设备" in t for t in texts), str(texts[:3]))

    # ---- A8 日志文件落盘与编码 ----
    print("\n[A8] 日志落盘与中文编码")
    log_dir = REPO_ROOT / "logs" / "webui"
    logs = sorted(log_dir.glob(f"{run_id}.log")) if log_dir.exists() else []
    s.check("日志文件存在", len(logs) == 1, f"期望 {log_dir / (run_id + '.log')}")
    if logs:
        content = logs[0].read_text(encoding="utf-8")
        s.check("日志含中文且无乱码", ("机器人" in content or "同步" in content), content[:120])
        s.check("日志含结构化批次记录", "批次#" in content)

    # ---- 汇总 ----
    print("\n" + "=" * 40)
    print(f"结果: {s.passed} 通过 / {s.failed} 失败")
    print("=" * 40)
    if s.failed:
        print("\nWebSocket 实时推送请在浏览器中按 docs/WEBUI_冒烟自测用例.md B 组人工验证。")
        return 1
    print("\nREST + 子进程 + JSONL 全链路冒烟通过 ✅")
    print("WebSocket 实时推送请在浏览器中按 docs/WEBUI_冒烟自测用例.md B 组人工验证。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

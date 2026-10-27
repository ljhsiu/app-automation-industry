"""子进程执行引擎: 任务启动 / stdout 读取 / 四级停止 / 进程树清理

设计文档 7.2 节。核心要点:
- PYTHONIOENCODING=utf-8 约束子进程 stdout 编码 (不可设 PYTHONUTF8=1，见 start())
- CREATE_NEW_PROCESS_GROUP 是 CTRL_BREAK_EVENT 的前置条件
- stderr 合流到 stdout，崩溃 Traceback 也能进 Web 日志
- JSONL 解析失败的行降级为纯文本日志 (兼容原脚本的 print 输出)
- 四级停止:
  0) 停止文件 (协作式，子进程主循环轮询 → 与宿主控制台环境无关，最可靠)
  1) CTRL_BREAK_EVENT (有控制台环境时触发 KeyboardInterrupt)
  2) terminate
  3) kill + taskkill /T /F
"""

import json
import os
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from .config import REPO_ROOT, load_webui_config
from .log_bus import get_bus
from .metrics import MetricsStore
from .registry import TaskSpec


class DeviceBusyError(Exception):
    """目标设备已被其他 run 占用"""

    def __init__(self, addr: str, run_id: str):
        self.addr = addr
        self.run_id = run_id
        super().__init__(f"设备 {addr} 已被运行 {run_id} 占用")


@dataclass
class RunRecord:
    run_id: str
    task_id: str
    task_name: str
    params: dict = field(default_factory=dict)
    devices: list[str] = field(default_factory=list)
    status: str = "starting"       # starting|running|stopping|stopped|failed
    pid: int | None = None
    started_at: float = 0.0        # epoch
    ended_at: float | None = None
    exit_code: int | None = None
    log_path: str = ""
    stop_file: str = ""            # 协作式优雅停止信号文件路径
    stop_requested: bool = False
    proc: object | None = field(default=None, repr=False)

    @property
    def active(self) -> bool:
        return self.status in ("starting", "running", "stopping")

    def to_summary(self) -> dict:
        return {
            "run_id": self.run_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "params": self.params,
            "devices": self.devices,
            "status": self.status,
            "pid": self.pid,
            "started_at": self.started_at,
            "started_at_iso": datetime.fromtimestamp(self.started_at).strftime("%Y-%m-%d %H:%M:%S"),
            "ended_at": self.ended_at,
            "ended_at_iso": (datetime.fromtimestamp(self.ended_at).strftime("%Y-%m-%d %H:%M:%S")
                             if self.ended_at else None),
            "exit_code": self.exit_code,
            "log_path": self.log_path,
        }


def _render_event(evt: dict) -> tuple[str, str] | None:
    """结构化事件 → (level, 可读文本)；未知事件返回 JSON 原文"""
    ev = evt.get("ev")
    if ev == "log":
        return str(evt.get("level") or "info"), str(evt.get("msg") or "")
    if ev == "phase":
        return "info", f"⏩ 阶段: {evt.get('phase')}"
    if ev == "device":
        name = evt.get("name") or evt.get("addr")
        state = "在线" if evt.get("online") else "掉线"
        btn = "｜按钮就绪" if evt.get("btn_ready") else ""
        text = f"📱 {name} {state}{btn}"
        if evt.get("text"):
            text += f"｜文本「{evt['text']}」"
        return "info", text
    if ev == "batch":
        return "info", (f"🎯 批次#{evt.get('seq')} 同步点击 {evt.get('n')} 台，"
                        f"同步等待 {evt.get('wait_ms')}ms")
    if ev == "click":
        if evt.get("ok"):
            return "info", (f"✅ {evt.get('addr')} 点击成功 "
                            f"({evt.get('x')},{evt.get('y')}) 耗时{evt.get('cost_ms')}ms")
        return "error", f"❌ {evt.get('addr')} 点击失败: {evt.get('err')}"
    if ev == "error":
        level = "error" if evt.get("fatal") else "warn"
        return level, f"⚠️ {evt.get('msg')}"
    if ev == "summary":
        return "info", (f"📊 汇总: 批次{evt.get('batches')} "
                        f"点击成功{evt.get('clicks_ok')}/失败{evt.get('clicks_fail')} "
                        f"平均等待{evt.get('avg_wait_ms')}ms 时长{evt.get('duration_s')}s")
    return "info", json.dumps(evt, ensure_ascii=False)


def build_cli(task: TaskSpec, params: dict) -> list[str]:
    """TaskSpec + 用户参数 → 子进程命令行"""
    cfg = load_webui_config()["sync_click_defaults"]
    args = [sys.executable, "-u", str(REPO_ROOT / task.script)]
    fa = task.fixed_args

    if task.script.endswith("sync_click.py"):
        devices = [d for d in (params.get("devices") or []) if d]
        if devices:
            args += ["--devices", ",".join(devices)]
        elif fa.get("device_mode"):
            args += ["--device-mode", str(fa["device_mode"])]
        args += ["--button-id", str(params.get("button_id") or cfg["button_id"])]
        filter_texts = params.get("filter_texts")
        if filter_texts is None:
            filter_texts = cfg["filter_texts"]
        if filter_texts:
            args += ["--filter-texts", ",".join(str(t) for t in filter_texts)]
        args += ["--poll-interval", str(params.get("poll_interval") or cfg["poll_interval"])]
        args += ["--click-cooldown", str(params.get("click_cooldown") or cfg["click_cooldown"])]
        args += ["--connect-retries", str(params.get("connect_retries") or cfg["connect_retries"])]
        if fa.get("require_all"):
            args.append("--require-all")
        if params.get("mock"):
            args.append("--mock")

    elif task.script.endswith("adb_wireless.py"):
        serial = str(params.get("serial") or "").strip()
        if serial:
            args += ["--serial", serial]
        port = params.get("port") or 5555
        args += ["--port", str(port)]
        if params.get("mock"):
            args.append("--mock")
    # legacy_* 原脚本无参数，直接运行

    return args


class Runner:
    """子进程任务调度器 (全局单实例，内部锁保护)"""

    def __init__(self, metrics: MetricsStore):
        self.metrics = metrics
        self.bus = get_bus()
        self.cfg = load_webui_config()
        self._runs: dict[str, RunRecord] = {}
        self._lock = threading.RLock()
        Path(self.cfg["log_dir"]).mkdir(parents=True, exist_ok=True)

    # ---- 查询 ----
    def get(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(self) -> list[RunRecord]:
        with self._lock:
            runs = list(self._runs.values())
        return sorted(runs, key=lambda r: r.started_at, reverse=True)

    def occupied_devices(self) -> dict[str, str]:
        """返回 当前被占用的设备 → run_id 映射"""
        out: dict[str, str] = {}
        with self._lock:
            for r in self._runs.values():
                if r.active:
                    for addr in r.devices:
                        out[addr] = r.run_id
        return out

    # ---- 启动 ----
    def start(self, task: TaskSpec, params: dict) -> RunRecord:
        devices = [d for d in (params.get("devices") or []) if d]

        # 设备占用冲突检查 (仅对显式指定设备的 run)
        occupied = self.occupied_devices()
        for addr in devices:
            if addr in occupied:
                raise DeviceBusyError(addr, occupied[addr])

        run_id = f"r-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{os.urandom(2).hex()}"
        log_path = Path(self.cfg["log_dir"]) / f"{run_id}.log"
        stop_file = Path(self.cfg["log_dir"]) / f"{run_id}.stop"

        cli = build_cli(task, params)
        env = os.environ.copy()
        # 仅约束 stdout/stderr 编码；不能设 PYTHONUTF8=1 —— 它会改变文件系统编码，
        # 导致 site 模块读取含 GBK 字节的 .pth 文件时 UnicodeDecodeError，子进程未启动即崩溃
        env["PYTHONIOENCODING"] = "utf-8"
        # 协作式停止信号文件 (任务脚本主循环轮询；与宿主控制台环境无关)
        env["WEBUI_STOP_FILE"] = str(stop_file)

        creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

        rec = RunRecord(
            run_id=run_id, task_id=task.id, task_name=task.name,
            params=dict(params), devices=devices,
            started_at=time.time(), log_path=str(log_path),
            stop_file=str(stop_file),
        )

        try:
            proc = subprocess.Popen(
                cli,
                cwd=str(REPO_ROOT),          # 统一工作目录，相对路径行为可预期
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,    # 合流: 崩溃 Traceback 也进日志
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
                creationflags=creationflags,
            )
        except Exception as e:
            rec.status = "failed"
            rec.ended_at = time.time()
            ch = self.bus.create(run_id)
            ch.push_log(time.time(), "error", f"子进程启动失败: {e}")
            with self._lock:
                self._runs[run_id] = rec
            return rec

        rec.proc = proc
        rec.pid = proc.pid
        rec.status = "running"
        self.bus.create(run_id)
        self.metrics.get_or_create(run_id, rec.started_at)

        with self._lock:
            self._runs[run_id] = rec

        threading.Thread(target=self._reader, args=(rec, proc),
                         name=f"reader-{run_id}", daemon=True).start()
        return rec

    # ---- 读取线程 ----
    def _reader(self, rec: RunRecord, proc: subprocess.Popen) -> None:
        ch = self.bus.get(rec.run_id)
        metrics = self.metrics.get_or_create(rec.run_id, rec.started_at)
        try:
            # 落盘内容与页面一致: 结构化事件写渲染后的可读文本，非 JSONL 行原样写入
            with open(rec.log_path, "a", encoding="utf-8") as f:
                assert proc.stdout is not None
                for raw in proc.stdout:
                    line = raw.rstrip("\r\n")
                    if not line:
                        continue
                    evt = self._try_parse(line)
                    if evt is None:
                        # 纯文本降级: 原脚本 print 输出照常显示
                        f.write(line + "\n")
                        f.flush()
                        ch.push_log(time.time(), "info", line)
                    else:
                        metrics.feed(evt)
                        rendered = _render_event(evt)
                        if rendered:
                            f.write(rendered[1] + "\n")
                            f.flush()
                            ch.push_log(time.time(), rendered[0], rendered[1])
        except Exception as e:
            if ch:
                ch.push_log(time.time(), "error", f"日志读取线程异常: {e}")

        rc = proc.wait()
        self._finalize(rec, rc)

    @staticmethod
    def _try_parse(line: str) -> dict | None:
        s = line.strip()
        if not (s.startswith("{") and s.endswith("}")):
            return None
        try:
            obj = json.loads(s)
            return obj if isinstance(obj, dict) and "ev" in obj else None
        except Exception:
            return None

    def _finalize(self, rec: RunRecord, rc: int) -> None:
        rec.exit_code = rc
        rec.ended_at = time.time()
        if rec.stop_requested or rc == 0:
            rec.status = "stopped"
        else:
            rec.status = "failed"
        # 清理停止信号文件
        try:
            if rec.stop_file:
                Path(rec.stop_file).unlink(missing_ok=True)
        except Exception:
            pass
        ch = self.bus.get(rec.run_id)
        if ch:
            ts = time.time()
            ch.push_log(ts, "info", f"🏁 任务结束 (status={rec.status}, exit_code={rc})")
            ch.push_status(ts, {
                "status": rec.status, "exit_code": rc,
                "ended_at": datetime.fromtimestamp(rec.ended_at).strftime("%Y-%m-%d %H:%M:%S"),
            })

    # ---- 停止 ----
    def stop(self, run_id: str, fast: bool = False) -> dict:
        rec = self.get(run_id)
        if rec is None:
            return {"ok": False, "detail": "run 不存在"}
        if not rec.active:
            return {"ok": False, "detail": f"run 已结束 (status={rec.status})"}

        rec.stop_requested = True
        rec.status = "stopping"
        proc = rec.proc

        if fast:
            self._hard_kill(rec, proc)
            return {"ok": True, "mode": "kill"}

        grace_break = float(self.cfg["stop_grace_break"])
        grace_term = float(self.cfg["stop_grace_term"])

        # 0) 协作式: 写停止文件，任务脚本主循环轮询后自行优雅退出 (退出码 0)
        #    与宿主控制台环境无关，是最可靠的优雅停止通道
        try:
            if rec.stop_file:
                Path(rec.stop_file).write_text("stop", encoding="utf-8")
            if self._wait_exit(proc, grace_break):
                return {"ok": True, "mode": "stop_file"}
        except Exception:
            pass

        # 1) 半优雅: 触发子进程 KeyboardInterrupt (需宿主/子进程有控制台，legacy 脚本依赖此通道)
        try:
            if os.name == "nt":
                proc.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                proc.send_signal(signal.SIGINT)
            if self._wait_exit(proc, grace_break):
                return {"ok": True, "mode": "break"}
        except Exception:
            pass

        # 2) 温和: terminate
        try:
            proc.terminate()
            if self._wait_exit(proc, grace_term):
                return {"ok": True, "mode": "terminate"}
        except Exception:
            pass

        # 3) 强制: kill + 进程树清理
        self._hard_kill(rec, proc)
        return {"ok": True, "mode": "kill"}

    def _hard_kill(self, rec: RunRecord, proc: subprocess.Popen) -> None:
        try:
            proc.kill()
        except Exception:
            pass
        if os.name == "nt" and proc.pid:
            # uiautomator2 可能派生 adb 子进程，必须清理进程树防孤儿
            try:
                subprocess.run(["taskkill", "/PID", str(proc.pid), "/T", "/F"],
                               capture_output=True, timeout=5,
                               creationflags=0x08000000)
            except Exception:
                pass

    @staticmethod
    def _wait_exit(proc: subprocess.Popen, timeout: float) -> bool:
        end = time.time() + timeout
        while time.time() < end:
            if proc.poll() is not None:
                return True
            time.sleep(0.1)
        return False

    def stop_all(self) -> None:
        """服务关闭时停止全部运行中的 run (短超时，不阻塞关闭流程)"""
        with self._lock:
            active = [r.run_id for r in self._runs.values() if r.active]
        for run_id in active:
            try:
                rec = self.get(run_id)
                if rec and rec.proc is not None:
                    rec.stop_requested = True
                    rec.status = "stopping"
                    try:
                        if rec.stop_file:
                            Path(rec.stop_file).write_text("stop", encoding="utf-8")
                    except Exception:
                        pass
                    try:
                        if os.name == "nt":
                            rec.proc.send_signal(signal.CTRL_BREAK_EVENT)
                        else:
                            rec.proc.send_signal(signal.SIGINT)
                    except Exception:
                        pass
            except Exception:
                pass
        # 给优雅停止一点时间，剩余强杀
        time.sleep(1.0)
        for run_id in active:
            rec = self.get(run_id)
            if rec and rec.active and rec.proc is not None:
                self._hard_kill(rec, rec.proc)


_runner: Runner | None = None


def get_runner() -> Runner:
    """获取全局调度器单例"""
    global _runner
    if _runner is None:
        _runner = Runner(MetricsStore())
    return _runner

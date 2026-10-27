#!/usr/bin/env python3
# -*- coding: utf-8 -*-
# ============================================================
# 交互式流程录制器
# 用法: python tools/monitor_record.py
# 功能: 逐步引导你操作设备，每步自动截图+抓取UI层级树
# ============================================================

import os
import sys
import time
import json
import subprocess
import yaml
from pathlib import Path
from datetime import datetime

# 修复 Windows GBK 编码问题
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent.parent
FLOW_FILE = PROJECT_ROOT / "操作步骤" / "transport_flow.yaml"
RECORD_DIR = PROJECT_ROOT / "reports" / "recording"


def adb(cmd: str, timeout: int = 15) -> str:
    """执行 ADB 命令"""
    r = subprocess.run(
        f"adb -s 192.168.0.100:5555 {cmd}",
        shell=True, capture_output=True, text=True, timeout=timeout
    )
    return (r.stdout + r.stderr).strip()


def capture_screenshot(save_path: str) -> bool:
    """截图"""
    dev_path = "/sdcard/monitor_scr.png"
    adb(f"shell screencap -p {dev_path}")
    result = adb(f"pull {dev_path} \"{save_path}\"")
    adb(f"shell rm {dev_path}")
    return os.path.exists(save_path)


def capture_ui_hierarchy(save_path: str) -> bool:
    """抓取 UI 层级树"""
    dev_path = "/sdcard/monitor_ui.xml"
    adb(f"shell uiautomator dump {dev_path}")
    result = adb(f"pull {dev_path} \"{save_path}\"")
    adb(f"shell rm {dev_path}")
    return os.path.exists(save_path)


def capture_current_activity() -> str:
    """获取当前 Activity"""
    out = adb("shell dumpsys activity activities 2>/dev/null")
    for line in out.split("\n"):
        if "top-activity" in line.lower() or "mResumedActivity" in line:
            return line.strip()
    return "unknown"


def print_step(step: dict, idx: int, total: int):
    """打印当前步骤信息"""
    print(f"\n{'=' * 68}")
    print(f"  📌 步骤 {idx}/{total}: {step['id']} - {step['name']}")
    print(f"{'=' * 68}")
    print(f"  📝 {step['description']}")
    print(f"  🎯 预期: {step.get('expected', 'N/A')}")

    # 打印定位信息
    locs = step.get("locators", [])
    if locs:
        print(f"  🔍 定位方式:")
        for loc in locs:
            fallback = " (兜底)" if loc.get("fallback") else ""
            print(f"      - {loc['type']}: \"{loc['value']}\"{fallback}")

    # 特殊操作提示
    if step.get("action") == "poll":
        print(f"  ⏳ 此步需要轮询等待，请持续观察屏幕...")


def collect_observations(step: dict) -> dict:
    """收集用户对当前步骤的观察"""
    obs = {}
    print(f"\n  {'─' * 40}")

    # 确认操作结果
    while True:
        status = input(f"  ✅ 操作结果 [ok / fail / skip]: ").strip().lower()
        if status in ("ok", "o", ""):
            obs["status"] = "ok"
            break
        elif status in ("fail", "f"):
            obs["status"] = "fail"
            break
        elif status in ("skip", "s"):
            obs["status"] = "skip"
            break

    if obs["status"] == "fail":
        obs["reason"] = input(f"  ❓ 失败原因: ").strip()

    # 收集元素实际文本
    locs = step.get("locators", [])
    for loc in locs:
        if loc["type"] == "text":
            actual = input(f"  📝 页面上 \"{loc['value']}\" 的实际文案是? (回车=一致): ").strip()
            if actual:
                obs[f"actual_text_{loc['value']}"] = actual

    # 验证后检查
    verifies = step.get("verify_after", [])
    for v in verifies:
        if v["type"] == "text":
            ok = input(f"  🔎 \"{v['value']}\" 是否可见? [y/n]: ").strip().lower()
            obs[f"verify_{v['value']}"] = ok in ("y", "yes", "")

    # 备注
    note = input(f"  💬 备注 (可选): ").strip()
    if note:
        obs["note"] = note

    return obs


def format_time(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}m{s}s"


def main():
    print("=" * 68)
    print("  🔬 搬运流程 - 交互式监控录制器")
    print(f"  设备: 192.168.0.100:5555")
    print(f"  录制目录: {RECORD_DIR}")
    print("=" * 68)

    # 检查 ADB 连接
    print("\n[初始化] 检查 ADB 连接...")
    out = adb("shell echo OK")
    if "OK" not in out:
        print("  ❌ 设备未连接，请先执行: adb connect 192.168.0.100:5555")
        sys.exit(1)
    print(f"  ✅ 设备已连接")

    # 加载流程
    print(f"\n[初始化] 加载流程文件: {FLOW_FILE}")
    with open(FLOW_FILE, "r", encoding="utf-8") as f:
        flow = yaml.safe_load(f)

    steps = flow["steps"]
    total = len(steps)
    print(f"  共 {total} 个步骤")

    # 创建录制目录
    session_id = datetime.now().strftime("%Y%m%d_%H%M%S")
    session_dir = RECORD_DIR / session_id
    ss_dir = session_dir / "screenshots"
    ui_dir = session_dir / "ui_hierarchy"
    ss_dir.mkdir(parents=True, exist_ok=True)
    ui_dir.mkdir(parents=True, exist_ok=True)
    print(f"  录制目录: {session_dir}")

    # 开始录制
    observations = []
    session_start = time.time()

    print(f"\n{'─' * 68}")
    print(f"  🚀 开始录制！请按照提示逐步操作设备")
    print(f"  每完成一步操作后，按 Enter 继续")
    print(f"{'─' * 68}")

    for i, step in enumerate(steps, 1):
        step_start = time.time()

        # 显示步骤
        print_step(step, i, total)

        # 等待用户操作
        input(f"\n  ⏸️  请在设备上完成上述操作，完成后按 Enter 录制...")

        # 截图
        ss_file = str(ss_dir / f"s{i:02d}_{step['id']}.png")
        print(f"  📸 截图...", end=" ")
        if capture_screenshot(ss_file):
            print("✓")
        else:
            print("✗")

        # 抓取 UI 层级树
        ui_file = str(ui_dir / f"s{i:02d}_{step['id']}.xml")
        print(f"  📄 UI层级树...", end=" ")
        if capture_ui_hierarchy(ui_file):
            print("✓")
        else:
            print("✗")

        # 记录当前 Activity
        activity = capture_current_activity()
        print(f"  📱 Activity: {activity[:80]}...")

        # 收集观察
        obs = collect_observations(step)
        obs["step_id"] = step["id"]
        obs["step_name"] = step["name"]
        obs["screenshot"] = ss_file
        obs["ui_hierarchy"] = ui_file
        obs["activity"] = activity
        obs["elapsed"] = round(time.time() - step_start, 1)
        observations.append(obs)

        # 如果失败且不跳过，询问是否继续
        if obs["status"] == "fail":
            cont = input(f"  ⚠️  此步失败，是否继续下一歩? [Y/n]: ").strip().lower()
            if cont in ("n", "no"):
                print("  ⏹️  录制已中止")
                break

    # 生成汇总
    session_elapsed = round(time.time() - session_start, 1)
    ok_count = sum(1 for o in observations if o["status"] == "ok")
    fail_count = sum(1 for o in observations if o["status"] == "fail")
    skip_count = sum(1 for o in observations if o["status"] == "skip")

    print(f"\n{'=' * 68}")
    print(f"  📊 录制完成")
    print(f"  总耗时: {format_time(session_elapsed)}")
    print(f"  ✅ OK: {ok_count} | ❌ FAIL: {fail_count} | ⏭️ SKIP: {skip_count}")
    print(f"  录制目录: {session_dir}")
    print(f"{'=' * 68}")

    # 保存观察记录
    report = {
        "session_id": session_id,
        "timestamp": datetime.now().isoformat(),
        "device": "192.168.0.100:5555",
        "flow_file": str(FLOW_FILE),
        "total_steps": total,
        "completed_steps": len(observations),
        "ok": ok_count,
        "fail": fail_count,
        "skip": skip_count,
        "elapsed_seconds": session_elapsed,
        "observations": observations,
    }

    report_file = session_dir / "observations.json"
    with open(report_file, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    # 生成快速摘要
    print(f"\n  📋 步骤摘要:")
    for obs in observations:
        icon = {"ok": "✅", "fail": "❌", "skip": "⏭️"}.get(obs["status"], "❓")
        note = obs.get("note", "") or obs.get("reason", "")
        note_str = f" — {note}" if note else ""
        print(f"  {icon} {obs['step_id']}: {obs['step_name']} ({obs['elapsed']}s){note_str}")

    print(f"\n  📁 完整记录: {report_file}")
    print(f"  📁 截图: {ss_dir}/")
    print(f"  📁 UI层级: {ui_dir}/")
    print(f"\n  运行结束后请将录制结果反馈给我，我会据此调整脚本。")

    # 输出需要关注的问题点
    issues = [o for o in observations if o["status"] == "fail"]
    unknowns = [o for o in observations if any(
        k.startswith("actual_text_") and v
        for k, v in o.items()
    )]
    if issues:
        print(f"\n  ⚠️  失败步骤需要重点关注:")
        for iss in issues:
            print(f"    - {iss['step_id']}: {iss.get('reason', '未说明原因')}")
    if unknowns:
        print(f"\n  🔄  文案不一致的步骤:")
        for u in unknowns:
            for k, v in u.items():
                if k.startswith("actual_text_") and v:
                    orig = k.replace("actual_text_", "")
                    print(f"    - {u['step_id']}: \"{orig}\" → 实际为 \"{v}\"")


if __name__ == "__main__":
    main()

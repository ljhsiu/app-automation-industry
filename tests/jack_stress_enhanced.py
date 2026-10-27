"""
举升压测脚本（增强版）
支持: 连续失败熔断 / fail.md 记录 / 测试报告 / 自动回充
从 app-automation/tests/test_jack_stress_enhanced.py 改写为直调 uiautomator2 模式
"""
import os, sys, time, yaml
from pathlib import Path
from datetime import datetime

import uiautomator2 as u2

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent  # tests/
CONFIG_DIR = PROJECT_ROOT.parent / "jack_stress"  # 配置和截图仍放 jack_stress/

sys.path.insert(0, str(PROJECT_ROOT.parent))  # 让 from tools.xxx 可 import

# ---------- 辅助 ----------

def click_rid(d, rid, timeout=5):
    e = d(resourceId=rid)
    for _ in range(timeout * 2):
        if e.exists:
            e.click()
            return True
        time.sleep(0.5)
    return False

def click_text(d, text, timeout=5):
    e = d(text=text)
    for _ in range(timeout * 2):
        if e.exists:
            e.click()
            return True
        time.sleep(0.5)
    return False

def get_text_rid(d, rid):
    e = d(resourceId=rid)
    if e.exists:
        return e.get_text()
    return None

def d_has_element(d, rid):
    return d(resourceId=rid).exists

def load_cfg():
    """加载根 config.yaml，返回 jack_stress 子配置"""
    with open(PROJECT_ROOT.parent / "config.yaml", "r", encoding="utf-8") as f:
        full = yaml.safe_load(f)
    return full["jack_stress"]


# ---------- 主类 ----------

class JackStressEnhanced:
    """举升压测（增强版）"""

    def __init__(self):
        self.cfg = load_cfg()
        self.ui = self.cfg["ui"]
        self.sc = self.cfg["stress"]
        dev = self.cfg["device"]
        self.d = u2.connect(dev["serial"])
        self.d.wait_timeout = 5.0
        self.pkg = dev["package"]
        self.home_act = dev["home_activity"]

        self.success_count = 0
        self.fail_count = 0
        self.consecutive_fail = 0
        self.total = 0
        self.fail_records = []
        self.test_start = datetime.now()

        self.ss_dir = CONFIG_DIR / "screenshots"
        self.ss_dir.mkdir(parents=True, exist_ok=True)

        self.max_consecutive = self.sc["max_consecutive_fails"]

    # ---- 导航 ----
    def on_home(self):
        return d_has_element(self.d, self.ui["home"]["menu_rid"])

    def start_app(self):
        print("[App] 启动...")
        self.d.app_start(self.pkg, self.home_act)
        time.sleep(3)
        return self.on_home()

    def is_on_transport_page(self):
        return d_has_element(self.d, self.ui["transport_page"]["jack_button_rid"])

    def goto_transport(self):
        print("[导航] 进入搬运任务页...")
        if self.on_home():
            click_text(self.d, self.ui["home"]["transport_btn_text"], timeout=5)
            time.sleep(2)
        return self.is_on_transport_page()

    def go_home(self):
        rid = self.ui["transport_page"]["back_rid"]
        for _ in range(10):
            if self.on_home():
                return True
            try:
                if d_has_element(self.d, rid):
                    click_rid(self.d, rid)
                else:
                    self.d.press("back")
            except Exception:
                self.d.press("back")
            time.sleep(0.5)
        return self.on_home()

    def restart_app(self):
        print("重启 App...")
        self.d.app_stop(self.pkg)
        time.sleep(2)
        self.d.app_start(self.pkg, self.home_act)
        time.sleep(3)
        for _ in range(10):
            if self.on_home():
                print("[OK] App 已到首页")
                return True
            time.sleep(1)
        return False

    # ---- 举升 ----
    def get_jack_status(self):
        return get_text_rid(self.d, self.ui["transport_page"]["jack_status_rid"])

    def get_jack_button_text(self):
        return get_text_rid(self.d, self.ui["transport_page"]["jack_button_rid"])

    def click_jack(self):
        click_rid(self.d, self.ui["transport_page"]["jack_button_rid"])

    def wait_stable(self, timeout=15):
        start = time.time()
        last_s = self.get_jack_status()
        last_b = self.get_jack_button_text()
        stable = 0
        while time.time() - start < timeout:
            s = self.get_jack_status()
            b = self.get_jack_button_text()
            if s != last_s or b != last_b:
                print(f"  状态: {last_s}/{last_b} -> {s}/{b}")
                last_s = s
                last_b = b
                stable = 0
            else:
                stable += 1
            if "运动中" not in str(s) and "运动中" not in str(b):
                if stable >= 4:
                    return True, s, b
            time.sleep(0.5)
        return True, last_s, last_b

    def _save_ss(self, reason):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        fp = str(self.ss_dir / f"jack_fail_{reason}_{ts}.png")
        self.d.screenshot(fp)
        return fp

    def do_jack_up(self):
        self.click_jack()
        time.sleep(1)
        s = self.get_jack_status()
        b = self.get_jack_button_text()
        if "运动中" not in str(s) and "运动中" not in str(b):
            s2 = self.get_jack_status()
            b2 = self.get_jack_button_text()
            if "已举升" in str(s2) or "放下" in str(b2):
                return True
        self.wait_stable()
        fs = self.get_jack_status()
        fb = self.get_jack_button_text()
        if fb == "放下" or "已举升" in str(fs):
            return True
        return False

    def do_jack_down(self):
        self.click_jack()
        time.sleep(1)
        self.wait_stable()
        fs = self.get_jack_status()
        fb = self.get_jack_button_text()
        if fb == "举升" or "举升" in str(fs):
            return True
        return False

    # ---- 电量 ----
    def get_battery(self):
        text = get_text_rid(self.d, self.ui["home"]["battery_rid"])
        if text and '%' in text:
            return int(text.replace('%', ''))
        return None

    # ---- 失败处理 ----
    def _handle_failure(self, reason):
        self.total += 1
        self.fail_count += 1
        self.consecutive_fail += 1

        ss = self._save_ss(reason)
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {"ts": ts, "reason": reason, "ss": ss, "cycle": self.total}
        self.fail_records.append(record)

        # 写 fail.md
        fail_md = self.ss_dir / "fail.md"
        with open(fail_md, "a", encoding="utf-8") as f:
            f.write(f"## 失败 #{len(self.fail_records)}\n")
            f.write(f"- 时间: {ts}\n- 轮次: {self.total}\n- 原因: {reason}\n")
            f.write(f"- 截图: {ss}\n\n")

        if self.consecutive_fail >= self.max_consecutive:
            print(f"\n[STOP] 连续失败 {self.consecutive_fail} 次，达到上限，停止测试")
            return False

        print(f"\n失败后等待 {self.sc['fail_wait_seconds']}s...")
        time.sleep(self.sc["fail_wait_seconds"])
        print("重启 App...")
        self.restart_app()
        time.sleep(2)
        self.goto_transport()
        return True

    # ---- 报告 ----
    def _gen_report(self):
        rp = self.ss_dir / "test_report.md"
        rate = (self.success_count / self.total * 100) if self.total > 0 else 0
        dur = datetime.now() - self.test_start
        with open(rp, "w", encoding="utf-8") as f:
            f.write("# 举升压测报告\n\n")
            f.write(f"**时间**: {self.test_start:%Y-%m-%d %H:%M:%S} - {datetime.now():%Y-%m-%d %H:%M:%S}\n\n")
            f.write(f"**时长**: {dur}\n\n")
            f.write("## 统计\n\n")
            f.write(f"| 指标 | 数值 |\n|------|------|\n")
            f.write(f"| 总次数 | {self.total} |\n")
            f.write(f"| 成功 | {self.success_count} |\n")
            f.write(f"| 失败 | {self.fail_count} |\n")
            f.write(f"| 成功率 | {rate:.1f}% |\n\n")
            if self.fail_records:
                f.write("## 失败详情\n\n")
                for r in self.fail_records:
                    f.write(f"### {r['reason']}\n- 时间: {r['ts']}\n- 截图: {r['ss']}\n\n")
        print(f"\n报告: {rp}")

    # ---- 运行 ----
    def run(self):
        cycles = self.sc["cycles"]
        print(f"\n{'#'*60}")
        print(f"# 举升压测（增强版）- {cycles} 轮")
        print(f"# 连续失败上限: {self.max_consecutive}")
        print(f"{'#'*60}")

        # 初始化 fail.md
        fail_md = self.ss_dir / "fail.md"
        with open(fail_md, "w", encoding="utf-8") as f:
            f.write("# 举升压测失败记录\n\n")

        battery = self.get_battery()
        print(f"初始电量: {battery}%")

        for i in range(1, cycles + 1):
            self.total += 1
            print(f"\n{'='*40}")
            print(f"第 {i}/{cycles} 轮")
            print(f"{'='*40}")

            try:
                if not self.is_on_transport_page():
                    print("  不在搬运页，进入...")
                    if not self.goto_transport():
                        if not self._handle_failure(f"第{i}轮: 无法进入搬运页"):
                            break
                        continue
                time.sleep(2)

                init_s = self.get_jack_status()
                init_b = self.get_jack_button_text()
                print(f"初始: {init_s}/{init_b}")

                # 举升
                if not self.do_jack_up():
                    print(f"第 {i} 轮举升失败")
                    if not self._handle_failure(f"第{i}轮: 举升失败"):
                        break
                    continue

                time.sleep(self.sc["interval_between"])

                # 放下
                if not self.do_jack_down():
                    print(f"第 {i} 轮放下失败")
                    if not self._handle_failure(f"第{i}轮: 放下失败"):
                        break
                    continue

                time.sleep(self.sc["interval_between"])

                self.consecutive_fail = 0
                self.success_count += 1
                print(f"[OK] 第 {i} 轮成功")

                # 电量
                b = self.get_battery()
                if b and b < self.sc["low_battery_threshold"]:
                    print(f"电量低 ({b}%)，充电...")
                    self.go_home()
                    from tools.charge_script import ChargeScript
                    ChargeScript(self.d).run(self.sc["low_battery_threshold"], self.sc["target_battery"])
                    self.goto_transport()

            except Exception as e:
                if not self._handle_failure(f"第{i}轮: 异常 - {e}"):
                    break

            time.sleep(1)

        # 结语
        print(f"\n{'#'*60}")
        print(f"# 压测完成")
        print(f"# 总: {self.total} | 成功: {self.success_count} | 失败: {self.fail_count}")
        if self.total > 0:
            print(f"# 成功率: {self.success_count/self.total*100:.1f}%")
        print(f"{'#'*60}")

        self._gen_report()

        if self.sc.get("charge_after_complete"):
            print("触发回充...")
            self.go_home()
            time.sleep(2)
            from tools.charge_script import ChargeScript
            ChargeScript(self.d).start_charge()
            print("充电已下发")


if __name__ == "__main__":
    JackStressEnhanced().run()

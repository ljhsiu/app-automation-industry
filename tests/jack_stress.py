"""
举升压测脚本（基础版）
循环举升-放下 N 次，支持电量检测和自动充电
从 app-automation/tests/test_jack_stress.py 改写为直调 uiautomator2 模式
"""
import os, sys, time, yaml
from pathlib import Path
from datetime import datetime

import uiautomator2 as u2

# 修复 Windows GBK 编码
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

PROJECT_ROOT = Path(__file__).resolve().parent  # tests/
CONFIG_DIR = PROJECT_ROOT.parent / "jack_stress"  # 配置和截图仍放 jack_stress/

sys.path.insert(0, str(PROJECT_ROOT.parent))  # 让 from tools.xxx 可 import

# ---------- 辅助函数 ----------

def click_rid(d, rid, timeout=5):
    """点击 resourceId，轮询等待"""
    e = d(resourceId=rid)
    for _ in range(timeout * 2):
        if e.exists:
            e.click()
            return True
        time.sleep(0.5)
    return False

def click_text(d, text, timeout=5):
    """点击 text，轮询等待"""
    e = d(text=text)
    for _ in range(timeout * 2):
        if e.exists:
            e.click()
            return True
        time.sleep(0.5)
    return False

def has_text(d, text):
    """检查 text 元素是否存在"""
    return d(text=text).exists

def get_text_rid(d, rid):
    """获取 resourceId 元素文本"""
    e = d(resourceId=rid)
    if e.exists:
        return e.get_text()
    return None

def load_cfg():
    """加载根 config.yaml，返回 jack_stress 子配置"""
    with open(PROJECT_ROOT.parent / "config.yaml", "r", encoding="utf-8") as f:
        full = yaml.safe_load(f)
    return full["jack_stress"]


# ---------- 主类 ----------

class JackStressTest:
    """举升压测"""

    def __init__(self):
        self.cfg = load_cfg()
        self.ui = self.cfg["ui"]
        self.sc = self.cfg["stress"]
        dev = self.cfg["device"]
        self.d = u2.connect(dev["serial"])
        self.pkg = dev["package"]
        self.home_act = dev["home_activity"]
        self.d.wait_timeout = 5.0

        # 统计
        self.success_count = 0
        self.fail_count = 0
        self.total = 0

        # 截图目录
        self.ss_dir = CONFIG_DIR / "screenshots"
        self.ss_dir.mkdir(parents=True, exist_ok=True)

    # ---- 导航 ----
    def on_home(self):
        return d_has_element(self.d, self.ui["home"]["menu_rid"])

    def start_app(self):
        print("[App] 启动...")
        self.d.app_start(self.pkg, self.home_act)
        time.sleep(3)
        return self.on_home()

    def goto_transport(self):
        print("[导航] 进入搬运任务页...")
        if not self.on_home():
            if not self.start_app():
                return False
        if not click_text(self.d, self.ui["home"]["transport_btn_text"], timeout=5):
            return False
        time.sleep(2)
        return self.is_on_transport_page()

    def is_on_transport_page(self):
        rid = self.ui["transport_page"]["jack_button_rid"]
        return d_has_element(self.d, rid)

    def go_home(self):
        print("返回首页...")
        back_rid = self.ui["transport_page"]["back_rid"]
        for _ in range(10):
            if self.on_home():
                print("  已到首页")
                return True
            try:
                if d_has_element(self.d, back_rid):
                    click_rid(self.d, back_rid)
                else:
                    self.d.press("back")
            except Exception:
                self.d.press("back")
            time.sleep(0.5)
        return self.on_home()

    # ---- 举升操作 ----
    def get_jack_status(self):
        return get_text_rid(self.d, self.ui["transport_page"]["jack_status_rid"])

    def get_jack_button_text(self):
        return get_text_rid(self.d, self.ui["transport_page"]["jack_button_rid"])

    def click_jack(self):
        rid = self.ui["transport_page"]["jack_button_rid"]
        click_rid(self.d, rid)

    def wait_stable(self, timeout=15):
        """等待举升状态稳定"""
        start = time.time()
        last_status = self.get_jack_status()
        last_btn = self.get_jack_button_text()
        stable = 0
        while time.time() - start < timeout:
            s = self.get_jack_status()
            b = self.get_jack_button_text()
            if s != last_status or b != last_btn:
                print(f"  状态: {last_status}/{last_btn} -> {s}/{b}")
                last_status = s
                last_btn = b
                stable = 0
            else:
                stable += 1
            if "运动中" not in str(s) and "运动中" not in str(b):
                if stable >= 4:
                    return True, s, b
            time.sleep(0.5)
        return True, last_status, last_btn

    def _save_ss(self, reason):
        ts = int(time.time())
        fp = str(self.ss_dir / f"jack_fail_{reason}_{ts}.png")
        self.d.screenshot(fp)
        print(f"  截图: {fp}")
        return fp

    def do_jack_up(self):
        print("  点击举升...")
        self.click_jack()
        time.sleep(1)

        status = self.get_jack_status()
        btn = self.get_jack_button_text()
        print(f"  当前: {status}, 按钮: {btn}")

        if "举起运动中" not in str(status) and "举起运动中" not in str(btn):
            s2 = self.get_jack_status()
            b2 = self.get_jack_button_text()
            if "已举升" in str(s2) or "放下" in str(b2):
                print(f"  直接终态: {s2}/{b2}")
                return True

        self.wait_stable()
        final_status = self.get_jack_status()
        final_btn = self.get_jack_button_text()
        print(f"  举升完成: {final_status}/{final_btn}")

        if final_btn == "放下" or "已举升" in str(final_status):
            print("  [OK] 举升成功")
            return True
        self._save_ss("举升失败")
        return False

    def do_jack_down(self):
        print("  点击放下...")
        self.click_jack()
        time.sleep(1)

        self.wait_stable()
        final_status = self.get_jack_status()
        final_btn = self.get_jack_button_text()
        print(f"  放下完成: {final_status}/{final_btn}")

        if final_btn == "举升" or "举升" in str(final_status):
            print("  [OK] 放下成功")
            return True
        self._save_ss("放下失败")
        return False

    # ---- 电量 ----
    def get_battery(self):
        rid = self.ui["home"]["battery_rid"]
        text = get_text_rid(self.d, rid)
        if text and '%' in text:
            return int(text.replace('%', ''))
        return None

    def check_and_charge(self):
        battery = self.get_battery()
        print(f"  电量: {battery}%")
        if battery is not None and battery < self.sc["low_battery_threshold"]:
            print(f"  [WARN] 电量低 ({battery}% < {self.sc['low_battery_threshold']}%)，启动充电...")
            self.go_home()
            from tools.charge_script import ChargeScript
            script = ChargeScript(self.d)
            script.run(self.sc["low_battery_threshold"], self.sc["target_battery"])
            print("  充电完成，回到搬运页...")
            time.sleep(2)
            self.goto_transport()
        return True

    # ---- 一轮 ----
    def do_one_cycle(self, cycle):
        print(f"\n{'='*40}")
        print(f"第 {cycle} 轮")
        print(f"{'='*40}")

        if not self.is_on_transport_page():
            print("  不在搬运页，尝试进入...")
            if self.on_home():
                if not self.goto_transport():
                    self._save_ss(f"第{cycle}轮_进搬运页失败")
                    return False
            else:
                self._save_ss(f"第{cycle}轮_不在搬运页")
                return False

        time.sleep(2)
        init_status = self.get_jack_status()
        init_btn = self.get_jack_button_text()
        print(f"初始: {init_status}/{init_btn}")

        # 举升
        if not self.do_jack_up():
            print(f"第 {cycle} 轮举升失败")
            return False

        time.sleep(self.sc["interval_between"])
        print(f"等待 {self.sc['interval_between']}s...")

        # 放下
        if not self.do_jack_down():
            print(f"第 {cycle} 轮放下失败")
            return False

        time.sleep(self.sc["interval_between"])
        print(f"等待 {self.sc['interval_between']}s...")

        # 电量
        self.check_and_charge()
        print(f"第 {cycle} 轮完成")
        return True

    # ---- 运行 ----
    def run(self):
        cycles = self.sc["cycles"]
        print(f"\n{'#'*60}")
        print(f"# 举升压测 - {cycles} 轮")
        print(f"{'#'*60}")

        battery = self.get_battery()
        print(f"初始电量: {battery}%")

        for i in range(1, cycles + 1):
            self.total += 1
            try:
                ok = self.do_one_cycle(i)
            except Exception as e:
                print(f"第 {i} 轮异常: {e}")
                self._save_ss(f"第{i}轮_异常")
                ok = False

            if ok:
                self.success_count += 1
                print(f"[OK] 第 {i} 轮成功")
            else:
                self.fail_count += 1
                print(f"[FAIL] 第 {i} 轮失败")

            time.sleep(1)

        # 完事
        print(f"\n{'#'*60}")
        print(f"# 压测完成")
        print(f"# 总: {self.total} | 成功: {self.success_count} | 失败: {self.fail_count}")
        print(f"{'#'*60}")

        if self.sc.get("charge_after_complete"):
            print("\n触发回充...")
            self.go_home()
            time.sleep(2)
            from tools.charge_script import ChargeScript
            ChargeScript(self.d).start_charge()
            print("充电已下发")


# ---------- 全局辅助 ----------

def d_has_element(d, rid):
    return d(resourceId=rid).exists


if __name__ == "__main__":
    JackStressTest().run()

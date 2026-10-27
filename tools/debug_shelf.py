#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
货架选择调测脚本 - 独立测试 click / verify 逻辑
用法: python tools/debug_shelf.py
"""
import time, re, sys
import uiautomator2 as u2

if sys.platform == "win32":
    try: sys.stdout.reconfigure(encoding="utf-8")
    except: pass

d = u2.connect("192.168.0.100:5555")
PKG = "com.keenon.solutionindustry"
SPEC = "1200 x 500"  # 目标: tv_description 匹配此文本

# ==================== 1. 进入货架浮窗 ====================
print("=" * 50)
print("[1] 进入货架浮窗...")
d.app_start(PKG, "com.keenon.industry.activity.IndustryHomeActivity")
time.sleep(3)

if not d(text="搬运").wait(timeout=10):
    print("[FAIL] 找不到搬运"); exit()
d(text="搬运").click()
time.sleep(2)

if not d(text="货架规格").wait(timeout=10):
    print("[FAIL] 找不到货架规格"); exit()
d(text="货架规格").click()
time.sleep(2)

if not d(text="选择货架").wait(timeout=5):
    print("[FAIL] 浮窗未出现"); exit()
print("[OK] 浮窗已出现")

# ==================== 2. 列出所有选项 ====================
print("\n[2] 浮窗内容:")
for i in range(10):
    sl = d(resourceId="com.keenon.solutionindustry:id/swipe_layout", instance=i)
    if not sl.exists: break
    title_elem = sl.child(resourceId="com.keenon.solutionindustry:id/tv_title")
    desc_elem = sl.child(resourceId="com.keenon.solutionindustry:id/tv_description")
    ck = sl.child(resourceId="com.keenon.solutionindustry:id/iv_checked")
    title = title_elem.get_text() if title_elem.exists else "?"
    desc = desc_elem.get_text() if desc_elem.exists else "?"
    sel = "SELECTED" if ck.exists and ck.info.get("selected") else "---"
    print(f"  [{i}] {title} | {desc} | {sel}")

# ==================== 3. 测试不同点击方式 ====================
print("\n[3] 测试点击...")

# 方式A: 点击 swipe_layout 本身
sl1 = d(resourceId="com.keenon.solutionindustry:id/swipe_layout", instance=1)
print(f"  方式A(swipe_layout[1]): exists={sl1.exists}, clickable={sl1.info.get('clickable')}")
sl1.click()
time.sleep(1)
ck1 = sl1.child(resourceId="com.keenon.solutionindustry:id/iv_checked")
print(f"    结果: selected={ck1.info.get('selected')}")

# 还原始: 点回第一个
sl0 = d(resourceId="com.keenon.solutionindustry:id/swipe_layout", instance=0)
sl0.click()
time.sleep(1)

# 方式B: 点击 view_root  
vr = d.xpath(
    f'//*[@resource-id="com.keenon.solutionindustry:id/tv_description" and @text="{SPEC}"]/../..')
print(f"  方式B(view_root): exists={vr.exists}")
if vr.exists:
    vr.click()
    time.sleep(1)
    ck1b = sl1.child(resourceId="com.keenon.solutionindustry:id/iv_checked")
    print(f"    结果: selected={ck1b.info.get('selected')}")

# 还原
sl0.click(); time.sleep(1)

# 方式C: click_text("1200")
print(f"  方式C(text='1200'):")
d(text="1200").click()
time.sleep(1)
ck1c = sl1.child(resourceId="com.keenon.solutionindustry:id/iv_checked")
print(f"    结果: selected={ck1c.info.get('selected') if ck1c.exists else 'N/A'}")

# ==================== 4. 最终: 选中目标 + 确认 + 验证 ====================
print("\n[4] 最终测试: 选中 {} -> 确定为".format(SPEC))
# 确保选中第二个
sl1.click()
time.sleep(1)
print("  点击确定...")
d(text="确定").click()
time.sleep(2)

# 检查搬运页上货架行右侧的文字
print("\n[5] 搬运页货架行状态:")
try:
    xml = d.dump_hierarchy()
    shelf_row = d(resourceId="com.keenon.solutionindustry:id/item_shelf_size")
    if shelf_row.exists:
        # 找行内所有 text
        row_xml = re.findall(r'text="([^"]*)"', xml)
        # 找到 tv_end 中的文字
        tv_end = d(resourceId="com.keenon.solutionindustry:id/item_shelf_size").child(
            resourceId="com.keenon.solutionindustry:id/tv_end")
        if tv_end.exists:
            txt = tv_end.child(resourceId="com.keenon.solutionindustry:id/tv_text").get_text()
            print(f"  货架行右侧显示: [{txt}]")
        else:
            print("  tv_end not found inside item_shelf_size")
    else:
        print("  item_shelf_size not found")
except Exception as e:
    print(f"  出错: {e}")

# 备选: 直接 dump 中找
try:
    xml = d.dump_hierarchy()
    # 在 item_shelf_size 范围内找 tv_end 里的 tv_text
    rid = "com.keenon.solutionindustry:id"
    m = re.search(
        f'resource-id="{rid}/item_shelf_size".*?resource-id="{rid}/tv_end".*?text="([^"]*)"',
        xml)
    if m:
        print(f"  正则匹配到: [{m.group(1)}]")
    else:
        print("  正则未匹配到")
except Exception as e:
    print(f"  正则出错: {e}")

print("\n" + "=" * 50)
print("请告诉我: 搬运页货架行右侧显示的文字是什么?")
print(f"同时确认浮窗内点击 swipe_layout[1] 是否能正确选中 '{SPEC}'?")

# CodeBuddy 环境自动搭建指南

> 本文档是 CodeBuddy Agent 的环境搭建参考手册。
> Agent 导入此项目后，应按照以下步骤自动完成环境搭建。

---

## 前置条件检查

Agent 应首先检查并引导用户完成以下准备：

| 项目 | 检查命令 | 最低版本 | 安装方式 |
|------|---------|---------|---------|
| Python | `python --version` | 3.10+ | https://python.org |
| ADB | `adb --version` | 任意 | https://developer.android.com/studio/releases/platform-tools |
| pip | `pip --version` | 最新 | 随 Python 安装 |

> **重要**: ADB 安装后需要加入系统 PATH 环境变量。

---

## 自动搭建步骤

### 步骤 1: 安装 Python 依赖

```powershell
# Windows (推荐)
.\setup_env.bat

# 或手动
pip install -r requirements.txt
```

依赖清单:
- `uiautomator2>=2.12.0` — Android UI 自动化驱动
- `pyyaml>=6.0` — 配置文件解析
- `pytest` / `pytest-asyncio` — 测试框架（可选）
- `matplotlib` — 图形生成（可选，calculate_footprint.py 需要）

### 步骤 2: 初始化 uiautomator2

```bash
python -m uiautomator2 init
```

> 注意: 此步骤只需执行一次。会向已连接的 Android 设备推送 ATX Agent。

### 步骤 3: 连接设备

用户需要提供机器人 IP 地址。Agent 应：

1. **询问用户设备 IP**（如 `192.168.0.100`）
2. 连接设备：
   ```bash
   adb connect <用户提供的IP>:5555
   ```
3. 验证连接：
   ```bash
   adb devices
   uiautomator2 connect <IP>:5555
   ```
4. **将 IP 写入 `config.yaml`**：
   - `device.ip`
   - `device.serial`（格式: `<IP>:5555`）
   - `devices.default.ip`

### 步骤 4: 验证设备状态

```bash
# 检查设备信息
python -c "import uiautomator2 as u2; d=u2.connect(); print(d.info)"
```

确认目标 App `com.keenon.solutionindustry` 已安装并运行。

### 步骤 5: 配置压测参数

Agent 应根据用户需求修改 `config.yaml`：

- **搬运压测**: 确认 `start_point` / `end_point` 与实际操作点位名称一致
- **举升压测**: 设置 `cycles` 和 `max_consecutive_fails`
- **充电保护**: 设置 `battery_protect.low_threshold`

### 步骤 6: 运行冒烟测试

```bash
# 搬运压测 (1轮冒烟)
python tests/transport_stress_test.py --cycles 1

# 举升压测 (1轮冒烟)
python tests/jack_stress_enhanced.py --cycles 1
```

---

## config.yaml 配置速查

| 参数 | 说明 | 示例 |
|------|------|------|
| `device.ip` | 机器人 WiFi IP | `192.168.0.100` |
| `device.port` | ADB 端口 | `5555` |
| `device.serial` | 设备序列号 | `192.168.0.100:5555` |
| `transport_stress.stress.cycles` | 搬运循环次数 | `10` |
| `transport_stress.transport.primary.floor` | 楼层号 | `1` |
| `transport_stress.transport.primary.start_point` | 起点名称 | `装卸点1_1` |
| `transport_stress.transport.primary.end_point` | 终点名称 | `装卸点1_2` |
| `transport_stress.transport.shelf_spec.instance` | 货架选项索引 | `4` |
| `transport_stress.battery_protect.enabled` | 电量保护开关 | `true` |
| `transport_stress.battery_protect.low_threshold` | 电量低阈值 % | `20` |
| `jack_stress.stress.cycles` | 举升循环次数 | `10` |

---

## 项目结构速览

```
app-automation-mcp/
├── config.yaml              ← 统一配置 (Agent 必须修改)
├── CODEBUDDY_SETUP.md       ← 本文档
├── setup_env.bat            ← 一键环境初始化
├── requirements.txt         ← Python 依赖
│
├── tests/                   ← 压测入口
│   ├── transport_stress_test.py     ← 搬运压测
│   ├── jack_stress_enhanced.py      ← 举升压测
│   └── conftest.py
│
├── pages/                   ← Page Object 层
├── tools/                   ← 独立工具脚本
├── utils/                   ← 工具模块
├── src/mcp_server/          ← MCP 服务器
│
├── 操作步骤/                 ← 操作文档 (YAML + Markdown)
└── .codebuddy/skills/       ← CodeBuddy Skill
```

---

## 常见问题

| 问题 | 解决方案 |
|------|---------|
| ADB 连接不上 | 检查设备和电脑是否在同一 WiFi；重新拔插 USB 线授权调试 |
| uiautomator2 连接超时 | `python -m uiautomator2 init` 重新推送 ATX Agent |
| 点位匹配失败 | 确认 `start_point` / `end_point` 名称与 App 显示完全一致 |
| shelf_spec.instance 不对 | 使用 `tools/debug_shelf.py` 查看货架列表确定正确索引 |
| 电量保护触发 | 机器人会自动去充电，等待充满后继续压测 |

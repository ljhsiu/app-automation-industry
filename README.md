# App Automation — 工业自动化压测项目

基于 Python + uiautomator2 + ADB 的工业机器人自动化压测工具集。

## 项目结构

```
app-automation-mcp/
├── config.yaml            # 统一配置文件（设备、搬运、举升、充电、MCP）
│
├── tests/                 # 压测脚本
│   ├── transport_stress_test.py    # 搬运压测
│   ├── jack_stress.py              # 举升压测（基础版）
│   ├── jack_stress_enhanced.py     # 举升压测（增强版：熔断+报告）
│   ├── test_transport.py           # pytest 搬运页测试
│   └── conftest.py                 # pytest fixtures
│
├── tools/                 # 工具脚本
│   ├── adb_wifi_connect.py  # ADB 无线连接
│   ├── charge_script.py     # 充电脚本
│   ├── undock_script.py     # 下桩脚本
│   ├── relay_monitor.py     # 继电器监控
│   ├── monitor_record.py    # 交互式录制器
│   └── debug_shelf.py       # 货架选择调测
│
├── pages/                 # Page Object 层
│   ├── home_page.py
│   ├── transport_page.py
│   ├── setting_page.py
│   ├── charge_page.py
│   └── charge_setting_page.py
│
├── utils/                 # 工具模块
│   └── app_helper.py
│
├── src/mcp_server/        # MCP 服务器
│   ├── server.py
│   ├── tools/
│   └── adapters/
│
├── 操作步骤/               # 操作文档
│   ├── transport_flow.yaml        # 搬运流程定义（YAML）
│   ├── 自动搬运任务.md
│   └── 自动搬运任务_精炼版.md
│
├── screenshots/           # 截图
├── reports/               # 测试报告
└── requirements.txt       # Python 依赖
```

## 快速开始

### 1. 安装依赖

```bash
pip install uiautomator2 pyyaml
# 或
pip install -r requirements.txt
```

### 2. 连接设备

```bash
# 方式1: 通过工具连接
python tools/adb_wifi_connect.py -i 192.168.0.100

# 方式2: 直接 ADB
adb connect 192.168.0.100:5555
```

### 3. 修改配置

编辑根目录 `config.yaml`，调整设备 IP、点位等参数。

### 4. 运行压测

```bash
# 搬运压测
cd tests && python transport_stress_test.py

# 举升压测
cd tests && python jack_stress_enhanced.py

# pytest 测试
pytest tests/ -v
```

## 搬运压测

**运行逻辑：**

1. 启动 App → 进入搬运任务页
2. 依次选择起点、终点、货架规格（1200 x 500）
3. 点击「开始工作」，轮询等待终态
4. **成功**: `tv_msg = "已完成卸货"` → 截图 → 确定 → 回首页，**下一轮点位互换**
5. **失败**: `tv_msg = "匹配失败"` → 截图 → 确定 → 回首页，**点位不变**，连续失败+1
6. 连续失败 ≥ `max_consecutive_failures` → 停止全部压测
7. 生成 MD 报告到 `reports/`

### 配置关键参数

| 参数路径 | 说明 | 默认值 |
|---------|------|--------|
| `device.ip` | 机器人 IP | `192.168.0.100` |
| `transport_stress.transport.primary.start_point` | 起点名称 | `装卸点7` |
| `transport_stress.transport.primary.end_point` | 终点名称 | `装卸点8` |
| `transport_stress.transport.shelf_spec.description` | 货架描述 | `1200 x 500` |
| `transport_stress.transport.task.max_wait_seconds` | 任务超时 | `300` |
| `transport_stress.fail.max_consecutive_failures` | 连续失败熔断 | `3` |

---

## 举升压测

**运行逻辑：**

1. 进入搬运任务页
2. 循环执行: 举升 → 等待 → 放下 → 等待
3. 检查电量（低电量自动充电）
4. 增强版支持: 连续失败熔断 / fail.md / 测试报告 / 自动回充

### 配置关键参数

| 参数路径 | 说明 | 默认值 |
|---------|------|--------|
| `jack_stress.stress.cycles` | 循环次数 | `100` |
| `jack_stress.stress.max_consecutive_fails` | 连续失败熔断 | `5` |
| `jack_stress.stress.interval_between` | 举升放下间隔/s | `10` |

---

## 工具脚本

| 脚本 | 用途 | 用法 |
|------|------|------|
| `adb_wifi_connect.py` | ADB 远程连接 | `python tools/adb_wifi_connect.py -i <IP>` |
| `charge_script.py` | 充电到目标电量 | `python tools/charge_script.py` |
| `undock_script.py` | 从充电桩下桩 | `python tools/undock_script.py` |
| `relay_monitor.py` | 继电器断电重启监控 | `python tools/relay_monitor.py --port COM3` |
| `debug_shelf.py` | 货架选择单独调测 | `python tools/debug_shelf.py` |

---

## MCP 服务器

将压测脚本封装为 MCP (Model Context Protocol) 服务，可通过标准化接口调用。

### 启动

```bash
python -m src.mcp_server.server
```

### 可用工具

| 工具 | 功能 |
|------|------|
| `charge_start` | 开始充电 |
| `undock` | 下桩返回原点 |
| `jack_stress_test` | 举升压测 |
| `get_device_status` | 获取设备状态 |

### Claude Code 配置

```json
{
  "mcpServers": {
    "app-automation": {
      "command": "python",
      "args": ["-m", "src.mcp_server.server"],
      "cwd": "/path/to/app-automation-mcp"
    }
  }
}
```

---

## Web UI 控制台（一期）

通过浏览器一键启动/停止「点击编排任务」，实时查看日志与监控面板，替代终端手工执行。

### 启动

```bash
# 方式 1: 双击启动（推荐，自动安装缺失的 Web 依赖）
start_webui.bat

# 方式 2: 命令行
pip install fastapi "uvicorn[standard]"
python -m uvicorn webui.app:app --host 127.0.0.1 --port 8000
```

浏览器访问 http://127.0.0.1:8000

### 功能

| 功能 | 说明 |
|---|---|
| 任务预设 | 单机监听 / 双机同步 / 多机同步（参数化新脚本），及原脚本直接调用 |
| 无线 ADB 连接 | USB 一键转无线（已移除阻塞式 `input()`） |
| 实时日志 | WebSocket 推送，支持级别/关键词过滤、断线补齐 |
| 监控面板 | 设备红绿灯、同步批次数、点击成功率、同步等待耗时折线图 |
| 演示模式 | 无真机时用 `--mock` 模拟设备与点击，验证全链路 |

### 与原脚本的关系

`点击编排任务/` 下的原脚本保持不动，终端用法不受影响；Web UI 通过 `webui/tasks/sync_click.py`（合并三个编排脚本的参数化版本）与子进程调度器驱动。日志落盘在 `logs/webui/{run_id}.log`。

- 设计文档: `docs/WEBUI_开发方案.md`
- 冒烟自测: `docs/WEBUI_冒烟自测用例.md`，自动化脚本 `python tools/webui_smoke_check.py`

---

## 依赖

- Python 3.8+
- uiautomator2 ≥ 2.12.0
- ADB (Android Debug Bridge)
- 设备需开启 USB 调试 + 网络 ADB

## 相关资源

- [uiautomator2 文档](https://github.com/openatx/uiautomator2)
- [MCP 协议规范](https://modelcontextprotocol.io/)

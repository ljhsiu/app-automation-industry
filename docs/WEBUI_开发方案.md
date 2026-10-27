# AMR 压测 Web UI 控制台 — 开发方案

| 项目 | 内容 |
|---|---|
| 文档版本 | v1.0 |
| 编写日期 | 2026-08-16 |
| 文档状态 | **待评审 / 未开工** |
| 所属仓库 | `app-automation-industry` |
| 目标读者 | 开发实施者、方案决策者 |

---

## 目录

- [1. 项目背景与目标](#1-项目背景与目标)
- [2. 现状代码调研结论](#2-现状代码调研结论)
- [3. 技术方案对比与选型](#3-技术方案对比与选型)
- [4. 核心架构决策](#4-核心架构决策)
- [5. 总体架构设计](#5-总体架构设计)
- [6. 结构化事件契约](#6-结构化事件契约)
- [7. 模块详细设计](#7-模块详细设计)
- [8. 监控指标规范](#8-监控指标规范)
- [9. 前端设计](#9-前端设计)
- [10. 配置与部署](#10-配置与部署)
- [11. 开发计划与工时](#11-开发计划与工时)
- [12. 测试计划](#12-测试计划)
- [13. 风险与对策](#13-风险与对策)
- [14. 后续扩展路线](#14-后续扩展路线)
- [附录 A：参考文件索引](#附录-a参考文件索引)

---

## 1. 项目背景与目标

### 1.1 现状痛点

当前仓库是面向 AMR（自主移动机器人）的 App 自动化压测项目，基于 Python + uiautomator2 + ADB 实现。所有测试流程依赖使用者在终端手动执行脚本，存在以下问题：

1. **操作门槛高**：需要记忆脚本路径、手动 `cd` 切目录、区分单机/双机/多机脚本
2. **参数修改靠改代码**：设备 IP、按钮 ID 等硬编码在脚本里，换设备要改源码
3. **缺乏实时监控**：只能盯着滚动的终端文本，无法直观看到"哪台设备在线""同步等待了多久""累计点击成功率"
4. **停止方式粗暴**：只能 `Ctrl+C`，多个终端窗口并行时容易误停
5. **无历史留存**：终端窗口关闭后日志即丢失（点击编排任务不产报告、不截图）

### 1.2 一期目标

构建一个 **Windows 本机运行的 Web 控制台**，使用者双击 bat 启动后，在浏览器中完成：

- 一键扫描 / 无线连接 ADB 设备
- 通过表单配置参数（无需改代码），点击按钮启动「点击编排任务」
- 实时查看执行日志（自动滚动、关键词过滤、仅看错误）
- 实时查看监控面板（设备就绪红绿灯、同步批次、点击成功率、同步等待耗时）
- 一键优雅停止，确保无残留进程

### 1.3 一期非目标（明确不做）

| 不做项 | 原因 |
|---|---|
| 用户鉴权 / 登录 | 已确认为**单人本机使用**，绑定 `127.0.0.1`，无网络暴露面 |
| 多用户状态隔离 | 同上 |
| 数据库持久化 | 一期 run 历史存内存 + 日志落文件，够用；避免引入 DB 运维成本 |
| 接入 `transport_stress` 搬运压测 | 排在三期；但架构预留接入位 |
| 打包 exe | 已确认采用**双击 bat 启动**；exe 打包排在后续可选项 |
| 前端框架 / 构建工具链 | 工业内网可能离线，避免 Node 工具链与 CDN 依赖 |

### 1.4 已锁定的决策（评审确认项）

| 决策项 | 结论 |
|---|---|
| 部署形态 | 单人本机，`127.0.0.1:8000`，无鉴权 |
| 一期接入范围 | 单线程 / 双线程 / 多机同步点击编排 + adb 无线连接 |
| 技术方案 | **方案 A：FastAPI + Uvicorn + WebSocket + 零构建原生前端** |
| 启动方式 | `start_webui.bat` 双击启动 |
| 前端资源 | 全部本地化，**不使用任何 CDN** |

---

## 2. 现状代码调研结论

### 2.1 影响方案可行性的硬约束

| # | 发现 | 位置 | 对 Web UI 的影响 |
|---|---|---|---|
| 1 | **点击编排脚本无函数封装**：顶层直接 `while True`，无 `main()`、无 `if __name__ == "__main__"` | `点击编排任务/多机同步任务编排.py:48-128`<br>`点击编排任务/双线程任务编排.py:23-84`<br>`点击编排任务/单线程任务编排.py:35-81` | **无法 `import` 调用**，必须以子进程方式拉起，或重构为类 |
| 2 | **只能靠 `KeyboardInterrupt` 停止**，无停止标志位 | 三个脚本末尾 `except KeyboardInterrupt` | Web 的"停止"按钮在**线程模式下无法中断**；子进程模式可复用此分支做优雅退出 |
| 3 | **硬编码设备地址与按钮 ID** | `双线程任务编排.py:6-8`（`ROBOT1_ADDR`/`ROBOT2_ADDR`/`BUTTON_ID`） | 需外部化为 CLI 参数 / 配置项 |
| 4 | **全篇 `print()` + emoji**，无 logging、无结构化事件 | 三个脚本全篇 | 只能拿到"文本日志流"，**拿不到量化指标**（成功率/耗时需结构化事件支撑） |
| 5 | `adbconnect.py` 有 **3 处阻塞 `input()`** | `点击编排任务/adbconnect.py:34, 44, 66` | 被 Web 调用会**永久挂死**，必须移除 |
| 6 | `adbconnect.py` / `单线程任务编排.py` 只取**第一台**设备 | `adbconnect.py:24-29`、`单线程任务编排.py:9-18` | 多台 USB/无线设备时行为不可控，需支持指定 |
| 7 | 三个点击编排脚本**逻辑高度重复** | 三文件对比 | 差异仅在"设备数量"和"是否要求全部就绪"，可合并为一个参数化脚本 |
| 8 | 压测框架**已是可复用类**（质量明显更高） | `tests/transport_stress_base.py`（`TransportStressTest`）<br>`tests/transport_stress_dual.py`（`DualTransportController`、`SyncPoint`） | 含 `results[]`、`_report()`、同步屏障；三期接入成本低 |
| 9 | **零 Web 依赖**，Python ≥ 3.10 | `requirements.txt`、`pyproject.toml` | 技术栈完全自由，无历史包袱 |
| 10 | 已有 Windows GBK 编码修复先例 | `tests/transport_stress_base.py:27-30`（`sys.stdout.reconfigure`） | 子进程 stdout 编码问题有成熟解法，需在 runner 层统一处理 |
| 11 | 已有设备/配置抽象层 | `src/mcp_server/adapters/driver_adapter.py`（连接池）<br>`src/mcp_server/adapters/config_adapter.py`（单例配置） | `ConfigAdapter` 的 `config.yaml` 加载逻辑可参考；`DriverAdapter` 三期可复用 |

### 2.2 脚本改造项清单

| 脚本 | 改造动作 | 是否改动原文件 |
|---|---|---|
| `单线程任务编排.py` | 逻辑合并进新脚本 `webui/tasks/sync_click.py` | ❌ 原文件保留不动 |
| `双线程任务编排.py` | 同上（`require_all=true`，2 台） | ❌ 原文件保留不动 |
| `多机同步任务编排.py` | 同上（`require_all=true`，N 台） | ❌ 原文件保留不动 |
| `adbconnect.py` | 移植为 `webui/tasks/adb_wireless.py`，去 `input()`、加 `--serial`、加事件输出 | ❌ 原文件保留不动 |

> **设计原则**：不破坏现有终端用法。老用户继续 `python 点击编排任务/多机同步任务编排.py` 照常可用；Web UI 走新增的 `webui/tasks/` 下的参数化版本。二者共存，互不影响。

---

## 3. 技术方案对比与选型

### 3.1 四方案对比

#### 方案 A：FastAPI + WebSocket + 原生 HTML/JS ⭐ 已选定

**技术栈**：FastAPI + Uvicorn + WebSocket + 单页 `index.html`（原生 JS，无框架）

| 维度 | 评估 |
|---|---|
| 优点 | 无 Node 工具链，`pip install` 即可跑；WebSocket 原生支持，日志/指标推送延迟 < 100ms；Pydantic 参数校验可自动驱动前端表单渲染；API 契约稳定，将来换 Vue 前端零后端改动；异步生态适合长任务；可后续 PyInstaller 打包 exe |
| 缺点 | 前端手写，复杂交互（多标签页、拖拽编排）会吃力；无组件库，UI 精美度一般 |
| 风险 | **低**。主要坑是 Windows 子进程编码与进程树 kill，均有成熟解法 |
| 实施难度 | ★★☆☆☆ |
| 工期 | **9–11 人日** |

#### 方案 B：Streamlit

| 维度 | 评估 |
|---|---|
| 优点 | 最快出可视原型（3 天可见东西）；图表/表格开箱即用；纯 Python，无前端知识门槛 |
| 缺点 | **执行模型与需求冲突**：Streamlit 每次交互都会从头重跑整个脚本，长任务/实时日志必须靠 `session_state` + 后台线程 + `st.fragment` 自动刷新硬凑；"停止按钮"状态管理别扭；日志靠轮询而非推送，卡顿明显；多人访问共享同一 server 进程，状态隔离差 |
| 风险 | **中高**。多设备并发 + 停止控制正是 Streamlit 最弱的场景，后期大概率重写 UI |
| 实施难度 | ★★☆☆☆（但天花板低） |
| 工期 | 7–8 人日（引擎层同样 4 人日，UI 仅 1.5） |

#### 方案 C：FastAPI + Vue3/React 前后端分离

| 维度 | 评估 |
|---|---|
| 优点 | UI 上限最高（Element Plus / Ant Design）；多设备卡片、图表、历史报告浏览、任务编排拖拽都好做；长期可扩展性最强 |
| 缺点 | 引入 Node + 构建产物，**Windows 部署复杂度显著上升**；当前需求（按钮 + 日志 + 指标）用不到这么重的方案；开发周期翻倍 |
| 风险 | 中（交付/部署摩擦，非技术风险） |
| 实施难度 | ★★★★☆ |
| 工期 | 14–18 人日 |

#### 方案 D：Flask + Flask-SocketIO

| 维度 | 评估 |
|---|---|
| 优点 | Flask 学习曲线最平；SocketIO 有成熟房间/广播机制；生态文档多 |
| 缺点 | 同步框架，长任务需配 eventlet/gevent（Windows 下 monkey-patch 兼容性偶发坑）；无自动 API 文档与参数校验，"任务参数表单自动生成"要手写 |
| 风险 | 中低 |
| 实施难度 | ★★☆☆☆ |
| 工期 | 8–10 人日 |

### 3.2 横向评分汇总

| 维度 | A: FastAPI+原生 | B: Streamlit | C: FastAPI+Vue | D: Flask+SocketIO |
|---|---|---|---|---|
| 实时日志质量 | ★★★★★ | ★★☆☆☆ | ★★★★★ | ★★★★☆ |
| 多设备并发控制 | ★★★★★ | ★★☆☆☆ | ★★★★★ | ★★★★☆ |
| Windows 部署简易度 | ★★★★★ | ★★★★★ | ★★☆☆☆ | ★★★★☆ |
| 可扩展性 | ★★★★☆ | ★★☆☆☆ | ★★★★★ | ★★★☆☆ |
| UI 精美度 | ★★★☆☆ | ★★★★☆ | ★★★★★ | ★★★☆☆ |
| 首版工期 | 9–11d | 7–8d | 14–18d | 8–10d |

### 3.3 选型结论与理由

**选定方案 A**，理由：

1. **零部署摩擦**：只需 Python 环境（项目本来就有），`start_webui.bat` 一键起。方案 C 的 Node 工具链在工业现场是实质负担。
2. **实时性刚好命中需求**：WebSocket 推送天然适配"日志流 + 指标面板"，而 Streamlit 的轮询刷新在长任务场景体验明显退化。
3. **停止控制可靠**：FastAPI 的异步模型 + 独立子进程管理，能干净实现"启动/停止/状态"三态，这是 Streamlit 的短板。
4. **演进路径平滑**：前端与后端通过 REST + WS 契约解耦，若将来 UI 需求超预期，可**只替换前端为 Vue，后端与引擎层零改动**，不存在重写风险。
5. **工期与价值平衡**：比 Streamlit 多 2–3 人日，换来的是不用重写的架构；比 Vue 方案省 5–7 人日，且当前需求用不到 Vue 的能力上限。

**关键提醒**：四个方案在「执行引擎层」的工作量**几乎完全相同**（约占总量 60%）。前端选型只影响剩余 40%。因此引擎层设计质量比框架选型更重要，本文档第 7 章为其重点。

---

## 4. 核心架构决策

### 4.1 决策一：子进程执行，而非线程 ✅

| 对比项 | 子进程（采用） | 线程（否决） |
|---|---|---|
| 停止任务 | `terminate()` / 信号必然生效 | ❌ uiautomator2 阻塞调用 + `while True` **无法强制中断** |
| 脚本改造量 | 小（保留原有输出方式，重定向 stdout 即可） | 大（必须全面重构为可中断类，加停止标志位） |
| 崩溃隔离 | 脚本崩溃不影响 Web 服务 | 可能拖死整个服务 |
| 多设备并发 | 天然隔离，每组一进程 | GIL 下 uiautomator2 轮询互相拖慢 |
| 代价 | 需处理编码（Windows GBK）、进程树清理 | — |

> **这个决策把脚本改造成本从约 4 人日降到约 1.5 人日**，是本项目性价比最高的一步。

### 4.2 决策二：优雅停止复用现有 `KeyboardInterrupt` 分支 ✅

三个点击编排脚本都写了 `except KeyboardInterrupt: print("🛑 脚本停止运行")`。Windows 下可用 `CTRL_BREAK_EVENT` 精准触发子进程的 `KeyboardInterrupt`，从而**复用脚本自身的清理逻辑**，无需为停止功能改造脚本。

停止三级降级策略：

```
CTRL_BREAK_EVENT  →  等 5s  →  terminate()  →  等 3s  →  kill() + taskkill /T /F
```

### 4.3 决策三：结构化事件（JSONL）驱动指标，兼容纯文本降级 ✅

任务脚本向 stdout 输出 **JSON Lines**；Runner 逐行尝试 JSON 解析：

- 解析成功 → 作为结构化事件进入指标聚合器 + 日志总线
- 解析失败 → 降级为普通文本日志行（**保证任何遗留 `print` 输出都不丢**）

这使得"接入一个新脚本"的最低成本是**零改造**（只有文本日志、无指标面板），加上 `emit()` 调用后才逐步获得指标能力。渐进式，可控。

### 4.4 决策四：三层分离，UI 可替换

```
┌──────────────────────────────────────────┐
│  ui/     静态前端（唯一随方案变化的部分） 20% │
├──────────────────────────────────────────┤
│  api/    REST + WebSocket 契约层          20% │
├──────────────────────────────────────────┤
│  engine/ 执行引擎（所有方案完全相同）      60% │
└──────────────────────────────────────────┘
```

### 4.5 决策五：三个点击编排脚本合并为一个参数化脚本

单/双/多机三脚本逻辑高度重复，差异仅两个维度。新增 `webui/tasks/sync_click.py` 统一承担，UI 侧以**三个预设**呈现：

| UI 预设 | `--devices` | `--require-all` | 对应原脚本 |
|---|---|---|---|
| 单机监听 | 自动取第 1 台 | `false` | `单线程任务编排.py` |
| 双机同步 | 手选 2 台 | `true` | `双线程任务编排.py` |
| 多机同步 | 自动全部 / 手选 N 台 | `true` | `多机同步任务编排.py` |

**收益**：一份代码、一处修 bug、三种用法；后续加"部分就绪即点击（M of N）"等策略也只改一处。

---

## 5. 总体架构设计

### 5.1 架构图

```
┌─────────────────── 浏览器 (127.0.0.1:8000) ───────────────────┐
│  index.html + app.js + style.css   （原生 JS，零构建，无 CDN） │
│  ┌──────────────┬─────────────────────┬────────────────────┐  │
│  │ 任务预设      │  指标卡 / 设备红绿灯  │  实时日志窗口       │  │
│  │ 参数表单      │  同步等待耗时折线图   │  过滤 / 暂停滚动    │  │
│  │ 设备勾选      │                     │                    │  │
│  └──────────────┴─────────────────────┴────────────────────┘  │
└────────────┬──────────────────────────────┬───────────────────┘
             │ REST (启停/查询)              │ WebSocket (日志/指标推送)
┌────────────▼──────────────────────────────▼───────────────────┐
│                    FastAPI (webui/app.py)                      │
│   /api/tasks  /api/devices  /api/runs  /api/runs/{id}/stop     │
│   /ws/runs/{id}                                                │
└────────────┬───────────────────────────────────────────────────┘
             │
┌────────────▼───────────────────────────────────────────────────┐
│                  执行引擎 (webui/engine/)                       │
│  registry ── 任务目录 / 参数 schema                              │
│  runner   ── Popen 生命周期 / stdout 读取线程 / 三级停止          │
│  log_bus  ── 环形缓冲(5000) + WS 广播 + seq 断线补齐              │
│  metrics  ── 事件 → 指标聚合（500ms 合并广播）                    │
│  devices  ── adb devices 扫描 / 占用检测                         │
└────────────┬───────────────────────────────────────────────────┘
             │ subprocess.Popen(sys.executable, "-u", ...)
             │ stdout=PIPE (JSONL)
┌────────────▼───────────────────────────────────────────────────┐
│                   任务脚本 (webui/tasks/)                       │
│  sync_click.py    参数化同步点击（覆盖单/双/多机）                 │
│  adb_wireless.py  USB→无线 ADB（无 input() 阻塞）                 │
└────────────┬───────────────────────────────────────────────────┘
             │ uiautomator2 / adb
┌────────────▼───────────────────────────────────────────────────┐
│                    AMR 机器人设备 (N 台)                         │
└────────────────────────────────────────────────────────────────┘
```

### 5.2 数据流

**启动流**
```
前端点「启动」
  → POST /api/runs {task_id, params}
  → registry 校验参数 schema
  → devices 检查设备是否被其他 run 占用
  → runner 构造 CLI 参数并 Popen 拉起子进程
  → 创建 run 记录（run_id / status=running / started_at）
  → 启动守护读取线程
  → 返回 {run_id}
  → 前端建立 WS 连接 /ws/runs/{run_id}
```

**日志/指标流**
```
子进程 stdout 输出一行
  → 读取线程 readline
  → 尝试 json.loads
      ├─ 成功 → metrics.feed(event) + log_bus.append(格式化文本)
      └─ 失败 → log_bus.append(原始文本)
  → loop.call_soon_threadsafe 跨线程投递到各订阅者 asyncio.Queue
  → WS 推送：日志实时逐条，指标 500ms 合并一次
  → 前端渲染
```

**停止流**
```
前端点「停止」
  → POST /api/runs/{id}/stop
  → runner 发 CTRL_BREAK_EVENT
  → 子进程 except KeyboardInterrupt → 输出 phase:stopped → 正常退出
  → 读取线程读到 EOF → 记录 exit_code / ended_at → status=stopped
  → 广播 status 事件 → 前端切换按钮状态
  → （若 5s 未退出则 terminate，再 3s 未退出则 kill + taskkill /T /F）
```

### 5.3 目录结构

```
app-automation-industry/
├── webui/                          【新增】
│   ├── __init__.py
│   ├── app.py                      FastAPI 应用：路由 + WS + 静态挂载
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── events.py               事件 schema + emit() 助手（任务脚本 import）
│   │   ├── registry.py             任务目录：id/名称/参数 schema/脚本路径
│   │   ├── runner.py               子进程生命周期 + 读取线程 + 三级停止
│   │   ├── log_bus.py              环形缓冲 + 订阅广播 + seq 补齐
│   │   ├── metrics.py              事件 → 指标聚合
│   │   └── devices.py              adb devices 扫描 / 占用检测
│   ├── tasks/
│   │   ├── __init__.py
│   │   ├── sync_click.py           参数化同步点击（单/双/多机）
│   │   └── adb_wireless.py         USB→无线 ADB
│   └── static/
│       ├── index.html
│       ├── app.js
│       └── style.css
├── logs/webui/                     【新增】{run_id}.log 落盘
├── docs/WEBUI_开发方案.md           【本文档】
├── start_webui.bat                 【新增】双击启动
├── config.yaml                     【修改】新增 webui: 段
├── requirements.txt                【修改】新增 fastapi / uvicorn
└── 点击编排任务/                     【不动】保留原终端用法
```

---

## 6. 结构化事件契约

### 6.1 通用格式

任务脚本每行输出一个 JSON 对象（UTF-8，`\n` 结尾，**必须 flush**）。公共字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `ts` | float | ✅ | 相对任务启动的秒数，保留 2 位小数 |
| `ev` | string | ✅ | 事件类型：`log`/`device`/`batch`/`click`/`phase`/`error`/`summary` |

### 6.2 事件类型定义

#### `ev: "log"` — 普通日志
```json
{"ts":12.34,"ev":"log","level":"info","msg":"3 台机器人已就绪"}
```
| 字段 | 说明 |
|---|---|
| `level` | `debug` / `info` / `warn` / `error` |
| `msg` | 日志正文 |

#### `ev: "device"` — 设备状态变化（去抖，仅状态变化时发送）
```json
{"ts":12.34,"ev":"device","addr":"10.56.82.72:5555","name":"机器人1",
 "online":true,"btn_ready":true,"text":"确定"}
```
| 字段 | 说明 |
|---|---|
| `addr` | 设备地址，作为唯一标识 |
| `name` | 显示名，如 `机器人1(10.56.82.72:5555)` |
| `online` | 连接是否正常 |
| `btn_ready` | 目标按钮是否已就绪（存在且不在过滤文本内） |
| `text` | 当前按钮文本（用于诊断"结束调度"过滤是否生效） |

> **去抖要求**：轮询间隔 0.5s，若每轮都发会刷屏。仅当 `(online, btn_ready, text)` 三元组发生变化时才发送事件。

#### `ev: "batch"` — 同步批次触发
```json
{"ts":12.34,"ev":"batch","seq":12,"n":3,"wait_ms":842}
```
| 字段 | 说明 |
|---|---|
| `seq` | 批次序号，自增 |
| `n` | 本批次参与的设备数 |
| `wait_ms` | **同步等待耗时** = 最晚就绪设备时间 − 最早就绪设备时间 |

> `wait_ms` 是守护型任务最有价值的指标：它量化了"最快的机器人白等了多久"，直接反映多机协同效率与设备一致性问题。

#### `ev: "click"` — 单次点击结果
```json
{"ts":12.34,"ev":"click","seq":12,"addr":"10.56.82.72:5555",
 "ok":true,"x":540,"y":1180,"cost_ms":73,"err":null}
```
| 字段 | 说明 |
|---|---|
| `seq` | 所属批次序号 |
| `ok` | 点击是否成功 |
| `x` / `y` | 实际点击坐标 |
| `cost_ms` | 点击调用耗时 |
| `err` | 失败原因（`ok=true` 时为 `null`） |

#### `ev: "phase"` — 任务阶段
```json
{"ts":0.12,"ev":"phase","phase":"connecting"}
```
`phase` 取值：`connecting` → `ready` → `running` → `stopped` / `failed`

#### `ev: "error"` — 异常
```json
{"ts":12.34,"ev":"error","msg":"设备 10.56.82.72:5555 掉线","addr":"10.56.82.72:5555","fatal":false}
```
`fatal=true` 表示任务无法继续，将退出。

#### `ev: "summary"` — 任务结束汇总（退出前最后一条）
```json
{"ts":3600.0,"ev":"summary","batches":142,"clicks_ok":420,"clicks_fail":6,
 "avg_wait_ms":735,"max_wait_ms":4210,"duration_s":3600.0}
```

### 6.3 `events.py` 助手接口

任务脚本统一通过助手输出，避免手拼 JSON：

```python
# webui/engine/events.py 对外接口（供 webui/tasks/*.py import）

def init(start_ts: float | None = None) -> None:
    """初始化时间基准；同时修复 Windows stdout 编码为 utf-8"""

def emit(ev: str, **fields) -> None:
    """输出一条结构化事件（自动补 ts，自动 flush）"""

def log(msg: str, level: str = "info") -> None:
    """等价于 emit('log', level=level, msg=msg)"""

def phase(name: str) -> None: ...
def error(msg: str, fatal: bool = False, **extra) -> None: ...
```

**实现要点**
- `print(json.dumps(obj, ensure_ascii=False), flush=True)` —— `ensure_ascii=False` 保留中文可读性，`flush=True` 保证实时性
- 模块导入时执行 `sys.stdout.reconfigure(encoding="utf-8")`（参考 `tests/transport_stress_base.py:27-30` 的既有做法）
- `events.py` 位于 `engine/` 但被 `tasks/` 脚本以子进程方式 import，因此**不得依赖 fastapi 等 Web 库**，保持纯标准库

---

## 7. 模块详细设计

### 7.1 `engine/registry.py` — 任务目录

集中定义"有哪些可执行任务、每个任务要什么参数"，前端据此**自动渲染表单**，无需前端硬编码。

```python
@dataclass
class ParamSpec:
    key: str
    label: str                  # 中文标签
    type: str                   # "string" | "int" | "float" | "bool" | "devices" | "tags"
    default: Any = None
    required: bool = False
    min: float | None = None
    max: float | None = None
    help: str = ""              # 表单下方灰字提示

@dataclass
class TaskSpec:
    id: str                     # "sync_click_single" 等
    name: str                   # "单机监听"
    group: str                  # "点击编排任务"
    description: str
    script: str                 # 相对仓库根的脚本路径
    metrics_kind: str           # "daemon"（守护型）| "cycle"（轮次型）
    params: list[ParamSpec]
    fixed_args: dict            # 预设固定值，如 {"require_all": False}
```

**一期注册的 4 个任务**

| id | 名称 | script | metrics_kind | fixed_args |
|---|---|---|---|---|
| `sync_click_single` | 单机监听 | `webui/tasks/sync_click.py` | `daemon` | `require_all=False`, `device_mode=first` |
| `sync_click_dual` | 双机同步 | `webui/tasks/sync_click.py` | `daemon` | `require_all=True`, `device_count=2` |
| `sync_click_multi` | 多机同步 | `webui/tasks/sync_click.py` | `daemon` | `require_all=True` |
| `adb_wireless` | 无线 ADB 连接 | `webui/tasks/adb_wireless.py` | `daemon` | — |

**`sync_click` 系列参数表**

| key | label | type | default | 说明 |
|---|---|---|---|---|
| `devices` | 目标设备 | `devices` | `[]` | 空 = 自动使用全部在线设备 |
| `button_id` | 按钮 resourceId | `string` | `com.keenon.solutionindustry:id/tv_start` | 来自 `config.yaml` 的 `dual_click.button_resourceId` |
| `filter_texts` | 过滤文本 | `tags` | `["结束调度"]` | 按钮文本命中则不点击 |
| `poll_interval` | 轮询间隔(秒) | `float` | `0.5` | 范围 0.1–5 |
| `click_cooldown` | 点击后冷却(秒) | `float` | `2.0` | 防重复点击 |
| `connect_retries` | 连接重试次数 | `int` | `3` | 范围 1–10 |
| `require_all` | 需全部就绪 | `bool` | `true` | 预设固定，UI 不展示 |

**扩展位**：三期接入搬运压测时，只需在此文件追加 `TaskSpec(id="transport_dual", metrics_kind="cycle", ...)`，前端无需改动即可渲染其表单。

### 7.2 `engine/runner.py` — 子进程生命周期（核心模块）

#### 数据结构
```python
@dataclass
class RunRecord:
    run_id: str                 # "r-20260816-153012-a1b2"
    task_id: str
    task_name: str
    params: dict
    devices: list[str]          # 本 run 占用的设备地址
    status: str                 # "starting"|"running"|"stopping"|"stopped"|"failed"
    pid: int | None
    started_at: datetime
    ended_at: datetime | None
    exit_code: int | None
    log_path: Path
```

#### 启动
```python
env = os.environ.copy()
env["PYTHONIOENCODING"] = "utf-8"   # 关键：防 Windows GBK 乱码
env["PYTHONUTF8"] = "1"

creationflags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0

proc = subprocess.Popen(
    [sys.executable, "-u", str(script_abs), *cli_args],
    cwd=REPO_ROOT,                  # 统一工作目录，保证相对路径一致
    env=env,
    stdout=subprocess.PIPE,
    stderr=subprocess.STDOUT,       # 合流，异常栈也能进日志
    text=True,
    encoding="utf-8",
    errors="replace",               # 兜底：非法字节不抛异常
    bufsize=1,                      # 行缓冲
    creationflags=creationflags,
)
```

| 要点 | 原因 |
|---|---|
| `-u` | 关闭 Python 输出缓冲，保证日志实时 |
| `PYTHONIOENCODING=utf-8` + `errors="replace"` | Windows 中文/emoji 乱码的根治组合 |
| `stderr=STDOUT` | Traceback 不丢失，能在 Web 日志里看到崩溃原因 |
| `CREATE_NEW_PROCESS_GROUP` | 前置条件：不加此 flag 无法发 `CTRL_BREAK_EVENT` |
| `cwd=REPO_ROOT` | 脚本内的 `./config.yaml`、`./logs` 等相对路径行为可预期 |

#### 读取线程
```python
def _reader(run: RunRecord, proc, bus, agg, loop):
    with open(run.log_path, "a", encoding="utf-8") as f:
        for raw in proc.stdout:              # 阻塞逐行读，EOF 自然结束
            line = raw.rstrip("\r\n")
            f.write(line + "\n"); f.flush()  # 同步落盘，服务重启后日志仍可查
            evt = _try_parse(line)           # json.loads 失败返回 None
            if evt is None:
                bus.push(run.run_id, level="info", text=line, raw=True)
            else:
                agg.feed(run.run_id, evt)
                bus.push(run.run_id, **_render(evt))
    proc.wait()
    _finalize(run, proc.returncode)          # 写 status/ended_at，广播 status
```

- 每个 run 一个 `threading.Thread(daemon=True)`
- 跨线程投递到 asyncio 世界统一走 `loop.call_soon_threadsafe`

#### 三级停止
```python
def stop(run_id: str, grace_break=5.0, grace_term=3.0):
    run.status = "stopping"
    # 1) 优雅：触发子进程 KeyboardInterrupt，复用脚本自身清理逻辑
    if os.name == "nt":
        proc.send_signal(signal.CTRL_BREAK_EVENT)
    else:
        proc.send_signal(signal.SIGINT)
    if _wait(proc, grace_break): return
    # 2) 温和：terminate
    proc.terminate()
    if _wait(proc, grace_term): return
    # 3) 强制：kill + 清理进程树（uiautomator2 可能派生 adb 子进程）
    proc.kill()
    if os.name == "nt":
        subprocess.run(["taskkill","/PID",str(proc.pid),"/T","/F"],
                       capture_output=True)
```

> **必须做进程树清理**：uiautomator2 会派生 `adb` 子进程，只 kill 父进程会留下孤儿进程占用设备，导致下次启动报"设备被占用"。

#### 并发与占用控制
- 全局单实例 `Runner`，内部 `threading.RLock` 保护 `_runs` 字典
- **允许同一 task_id 并行多个 run**（多设备分组场景）
- **但拒绝设备重复占用**：启动前检查目标设备是否已被 `status in (starting, running, stopping)` 的 run 持有，冲突则返回 `409 Conflict` 并说明是哪个 run 占用
- 服务关闭时（FastAPI `shutdown` 事件）自动停止全部运行中的 run，避免孤儿进程

### 7.3 `engine/log_bus.py` — 日志总线

```python
@dataclass
class LogLine:
    seq: int            # 每 run 内自增，从 1 开始
    ts: float
    level: str
    text: str
```

| 能力 | 设计 |
|---|---|
| 缓冲 | 每 run 一个 `deque(maxlen=5000)`（可配 `webui.log_buffer_size`） |
| 订阅 | 订阅者持 `asyncio.Queue(maxsize=1000)`；队列满时**丢弃最旧**并插入一条"日志过快，已丢弃 N 行"提示，避免慢客户端拖垮服务 |
| 跨线程 | 读取线程 → `loop.call_soon_threadsafe(queue.put_nowait, line)` |
| 断线补齐 | `GET /api/runs/{id}/logs?from=seq` 返回 seq > from 的所有缓冲行 |
| 落盘 | 由 runner 读取线程同步写 `logs/webui/{run_id}.log`，与内存缓冲独立 |

**前端重连协议**：WS 断开重连后，先取本地已有的最大 seq，调 `?from=maxSeq` 补齐历史，再消费新的 WS 消息。由于 seq 单调递增，可去重，**保证不丢行、不重复**。

### 7.4 `engine/metrics.py` — 指标聚合

```python
@dataclass
class DaemonMetrics:                 # metrics_kind == "daemon"
    duration_s: float
    phase: str
    devices: dict[str, DeviceState]  # addr → {name, online, btn_ready, text, last_change}
    online_count: int
    ready_count: int
    batches: int
    clicks_ok: int
    clicks_fail: int
    click_success_rate: float        # ok / (ok+fail)
    avg_wait_ms: float
    max_wait_ms: float
    p95_wait_ms: float
    wait_series: list[tuple[int,int]] # [(batch_seq, wait_ms)] 保留最近 100 点，供折线图
    consecutive_fails: int
    last_error: str | None
    reconnects: int
```

| 输入事件 | 聚合动作 |
|---|---|
| `device` | 更新 `devices[addr]`；`online` 由 false→true 时 `reconnects += 1`；重算 `online_count`/`ready_count` |
| `batch` | `batches += 1`；`wait_series` 追加；更新 avg/max/p95 |
| `click` | `ok` → `clicks_ok += 1`, `consecutive_fails = 0`；否则 `clicks_fail += 1`, `consecutive_fails += 1` |
| `phase` | 更新 `phase` |
| `error` | 更新 `last_error` |
| `summary` | 用脚本自报数据做最终校准 |

**广播降频**：指标变化频繁（每次点击都变），若每次都推 WS 会在密集点击时压垮前端。采用**500ms 定时合并推送**——只在有变化时推，且最快 500ms 一次。日志则实时逐条推（日志本身有天然频率上限）。

**轮次型指标预留**：三期接入搬运压测时新增 `CycleMetrics`（总轮次/成功轮次/成功率/平均轮耗时/熔断状态），由 `metrics_kind` 分派。前端按 `metrics_kind` 渲染不同面板。

### 7.5 `engine/devices.py` — 设备服务

```python
def scan() -> list[DeviceInfo]:
    """执行 adb devices，解析为结构化列表"""

@dataclass
class DeviceInfo:
    addr: str          # "10.56.82.72:5555" 或 USB 序列号
    state: str         # "device" | "offline" | "unauthorized"
    wireless: bool     # addr 中是否含 ':'
    busy_run_id: str | None   # 被哪个 run 占用
    model: str | None         # adb -s X shell getprop ro.product.model（带缓存）
    battery: int | None       # adb -s X shell dumpsys battery（带缓存，30s TTL）
```

**实现要点**
- `adb devices` 解析逻辑复用现有 `多机同步任务编排.py:10-19` 的写法（跳过 `List` 开头行）
- `model` / `battery` 查询较慢（每台约 200–500ms），加 **30s TTL 缓存**，避免前端轮询设备列表时卡顿
- 所有 `subprocess.run` 加 `timeout=5`，防 adb 卡死拖住 Web 请求
- Windows 下 `subprocess.run` 统一加 `creationflags=CREATE_NO_WINDOW`，避免弹黑框

### 7.6 `tasks/sync_click.py` — 参数化同步点击

#### CLI 接口
```
python webui/tasks/sync_click.py
    [--devices 10.56.82.72:5555,10.56.82.134:5555]   # 空=自动全部
    [--device-mode all|first]                        # 自动选择策略
    [--button-id com.keenon.solutionindustry:id/tv_start]
    [--filter-texts 结束调度,其他文本]
    [--poll-interval 0.5]
    [--click-cooldown 2.0]
    [--connect-retries 3]
    [--require-all]                                  # flag
```

#### 主流程（基于 `多机同步任务编排.py` 移植并强化）

```
1. events.init() → phase(connecting)
2. 解析目标设备：--devices 显式指定，或 adb 扫描（all / first）
3. 逐台 safe_connect（保留原有重试逻辑），失败的设备标记 online=false 但不退出
4. 若全部连接失败 → error(fatal=True) → phase(failed) → exit 1
5. phase(ready) → phase(running)
6. while True 主循环：
     a. 遍历每台设备：探测按钮 exists / text
     b. 计算 btn_ready = exists && text not in filter_texts
     c. 状态三元组变化 → emit device 事件（去抖）
     d. 记录每台设备首次进入 ready 的时间戳 first_ready_ts[addr]
     e. 判定触发条件：
          require_all=True  → 全部设备 btn_ready
          require_all=False → 任一设备 btn_ready（各自独立点击）
     f. 触发时：
          - wait_ms = (max(first_ready_ts) - min(first_ready_ts)) * 1000
          - emit batch(seq, n, wait_ms)
          - 取各设备按钮 center() 坐标（失败则跳过本轮并 warn）
          - 每台起一个 Thread 并行 click，join(timeout=3)
          - 每台 emit click(ok, x, y, cost_ms, err)
          - 清空 first_ready_ts，sleep(click_cooldown)
     g. sleep(poll_interval)
7. except KeyboardInterrupt → emit summary → phase(stopped) → 正常退出 0
```

#### 相比原脚本的三处强化

| 强化点 | 原脚本行为 | 新行为 |
|---|---|---|
| **掉线容错** | 设备异常时裸 `except:` 吞掉，可能死循环空转 | 捕获后标记 `online=false`，按 `connect_retries` 后台重连，emit `error(fatal=False)`，**任务继续跑** |
| **同步等待可观测** | 无 | 记录 `first_ready_ts`，量化 `wait_ms` |
| **日志去抖** | 无（0.5s 一轮不打印，但状态不可见） | 状态变化才发事件，既不刷屏又能看到实时红绿灯 |

> **注意保留** `except KeyboardInterrupt` 分支——这是 runner 优雅停止机制的落点，删掉会导致停止时退出码非 0 且无 summary。

### 7.7 `tasks/adb_wireless.py` — USB 转无线 ADB

移植 `点击编排任务/adbconnect.py`，改造三处：

| 改造 | 说明 |
|---|---|
| **删除 3 处 `input()`** | 原 L34/L44/L66 的 `input("按任意键退出...")` 会让 Web 调用永久挂死 |
| **新增 `--serial`** | 原脚本只取第一台 USB 设备；多台时需能指定 |
| **`print` → `emit`** | 输出 `phase` / `log` / `error` 事件，并在成功时 emit 结果 |

CLI：`python webui/tasks/adb_wireless.py [--serial <usb_serial>] [--port 5555]`

流程：`adb devices` 找 USB 设备（`:` 不在 serial 中）→ `adb -s X shell ip addr show wlan0` 提 IP → `adb tcpip 5555` → `sleep 3` → `adb connect IP:5555` → emit 结果。

该任务是**短时任务**（约 5–10 秒），执行完自然退出，前端表现为"运行 → 完成"，无需手动停止。

### 7.8 `app.py` — API 契约

| 方法 | 路径 | 请求 | 响应 | 说明 |
|---|---|---|---|---|
| GET | `/` | — | HTML | 返回 `static/index.html` |
| GET | `/api/tasks` | — | `[TaskSpec]` | 任务目录 + 参数 schema，前端据此渲染表单 |
| GET | `/api/devices` | — | `[DeviceInfo]` | adb 设备列表（含占用状态、电量） |
| POST | `/api/adb/scan` | — | `[DeviceInfo]` | 强制刷新（跳过缓存） |
| POST | `/api/runs` | `{task_id, params}` | `{run_id}` | 启动；参数非法 `422`，设备被占用 `409` |
| GET | `/api/runs` | — | `[RunSummary]` | 运行列表（状态/起止/指标摘要） |
| GET | `/api/runs/{id}` | — | `{run, metrics}` | 详情快照（用于首次进页面渲染） |
| POST | `/api/runs/{id}/stop` | — | `{ok}` | 优雅停止 |
| GET | `/api/runs/{id}/logs` | `?from=seq&limit=2000` | `{lines, next_seq}` | 断线补齐 |
| GET | `/api/runs/{id}/logfile` | — | 文件下载 | 下载完整日志 |
| WS | `/ws/runs/{id}` | — | 见下 | 实时推送 |

#### WebSocket 消息格式

服务端 → 客户端，三种类型：

```json
{"type":"log","lines":[{"seq":101,"ts":12.3,"level":"info","text":"..."}]}
{"type":"metrics","data":{ ...DaemonMetrics... }}
{"type":"status","data":{"status":"stopped","exit_code":0,"ended_at":"..."}}
```

- `log` 支持批量数组（高频时合并，减少帧数）
- 连接建立时先推一次 `metrics` + `status` 全量快照，再进入增量推送
- 服务端每 30s 发 WS ping，检测死连接

#### 错误响应统一格式
```json
{"detail":{"code":"DEVICE_BUSY","message":"设备 10.56.82.72:5555 已被运行 r-xxx 占用","run_id":"r-xxx"}}
```

---

## 8. 监控指标规范

### 8.1 一个必须纠正的需求认知

需求原文要求"成功率、失败率、执行时间"面板。但**点击编排任务不是"N 轮循环"型压测**，它是**守护监听型**任务（死循环等按钮出现 → 同步点击），没有"轮次"概念。若直接套用轮次型指标，面板会长期显示 0 或无意义数据。

因此按任务性质区分两套指标（由 `TaskSpec.metrics_kind` 分派）：

| | 轮次型 `cycle`（transport_stress，三期） | 守护型 `daemon`（点击编排，一期） |
|---|---|---|
| 核心计数 | 总轮次 / 成功轮次 / 成功率 | 同步批次数 / 点击成功数 / 点击成功率 |
| 时间指标 | 单轮耗时、平均轮耗时 | **同步等待耗时** avg / max / p95 |
| 状态指标 | 连续失败数、熔断状态 | 在线设备数、**各设备就绪红绿灯** |
| 稳定性 | 电量保护触发次数 | 设备掉线/重连次数 |
| 产出 | MD 报告 + 截图 | 日志文件 |

### 8.2 一期面板字段清单

**顶部指标卡（6 个）**

| 卡片 | 数据来源 | 说明 |
|---|---|---|
| 运行时长 | `duration_s` | HH:MM:SS 格式 |
| 在线设备 | `online_count / len(devices)` | 分子分母形式 |
| 同步批次 | `batches` | 累计触发次数 |
| 点击成功率 | `click_success_rate` | `clicks_ok/(ok+fail)`，< 95% 标红 |
| 平均同步等待 | `avg_wait_ms` | 毫秒；> 3000ms 标黄提示设备不同步 |
| 连续失败 | `consecutive_fails` | ≥ 3 标红 |

**设备红绿灯列表**：每台一行，展示 `name` / `addr` / 在线灯 / 就绪灯 / 当前按钮文本 / 电量。
- 在线灯：绿=online，红=offline
- 就绪灯：绿=btn_ready，灰=按钮未出现，黄=按钮出现但被过滤文本拦下（此时显示文本内容，便于诊断）

**同步等待耗时折线图**：X 轴批次序号，Y 轴 `wait_ms`，取 `wait_series` 最近 100 点。手写 canvas 绘制，不引入图表库。

---

## 9. 前端设计

### 9.1 技术约束

| 约束 | 说明 |
|---|---|
| **零构建** | 无 npm / webpack / vite；直接由 FastAPI `StaticFiles` 托管 |
| **零 CDN** | 工业内网可能离线，不引用任何外部资源 |
| **零框架** | 原生 JS + `fetch` + `WebSocket`；DOM 操作量在本需求下可控 |
| **图表手写** | 折线图用 `<canvas>` 手绘（约 60 行），不引 ECharts |

### 9.2 页面布局（单页三区）

```
┌─────────────────────────────────────────────────────────────────┐
│  AMR 压测控制台            [无线ADB连接]  [刷新设备]  服务状态●    │
├──────────────┬──────────────────────────────────────────────────┤
│ ■ 任务预设    │  ┌ 指标卡 ×6 ──────────────────────────────────┐ │
│  ○ 单机监听   │  │ 运行时长 在线设备 同步批次 成功率 等待 失败  │ │
│  ● 双机同步   │  └─────────────────────────────────────────────┘ │
│  ○ 多机同步   │  ┌ 设备状态 ──────────────────────────────────┐ │
│              │  │ 机器人1 10.56.82.72:5555 ●在线 ●就绪 确定 82%│ │
│ ■ 参数        │  │ 机器人2 10.56.82.134:5555 ●在线 ○待命  -  75%│ │
│  按钮ID [___] │  └─────────────────────────────────────────────┘ │
│  过滤文本[___]│  ┌ 同步等待耗时(ms) ───────────────────────────┐ │
│  轮询间隔[0.5]│  │        ╱╲    ╱╲                            │ │
│  冷却   [2.0] │  │   ╱╲╱  ╲╱╲╱  ╲╱╲                          │ │
│              │  └─────────────────────────────────────────────┘ │
│ ■ 设备选择    │  ┌ 实时日志  [全部▾][搜索__][暂停滚动][下载] ──┐ │
│  ☑ 机器人1    │  │ 12.3 ✅ 机器人1 点击成功 (540,1180)         │ │
│  ☑ 机器人2    │  │ 12.3 🎯 2 台全部到位，同步等待 842ms        │ │
│  ☐ 机器人3    │  │ ...                                        │ │
│              │  │                                    (自动滚动)│ │
│ [启动] [停止] │  └─────────────────────────────────────────────┘ │
├──────────────┴──────────────────────────────────────────────────┤
│  运行历史: r-20260816-153012 双机同步 已停止 00:42:15 [查看日志]   │
└─────────────────────────────────────────────────────────────────┘
```

### 9.3 关键交互行为

| 行为 | 设计 |
|---|---|
| 预设切换 | 切换时按 `TaskSpec.params` 重渲染表单并回填默认值；`fixed_args` 中的参数不展示 |
| 设备勾选校验 | 「双机同步」强制恰好选 2 台，不满足时禁用启动按钮并提示 |
| 参数持久化 | 表单值存 `localStorage`，下次打开自动回填（避免重复填 button_id） |
| 启动中禁用 | `status in (starting, running)` 时禁用启动、启用停止；反之相反 |
| 日志过滤 | 前端本地过滤（级别下拉 + 关键词），不走后端，响应即时 |
| 自动滚动 | 默认开启；用户手动向上滚动时自动暂停，滚回底部时恢复（常见日志窗口惯例） |
| 日志上限 | DOM 中最多保留 3000 行，超出移除最旧节点（防内存膨胀与渲染卡顿） |
| WS 重连 | 断开后指数退避重连（1s/2s/4s/8s，上限 8s）；重连成功后按 `maxSeq` 调 `/logs?from=` 补齐 |
| 页面刷新 | 刷新后按 `/api/runs` 找到运行中的 run，自动重连其 WS 并拉全量快照 |

---

## 10. 配置与部署

### 10.1 `config.yaml` 新增段

追加到文件末尾，**所有项都有内置默认值，整段缺失也能正常启动**：

```yaml
# ============================================================
# 六、Web UI 控制台 (webui/)
# ============================================================
webui:
  host: "127.0.0.1"           # 单人本机使用，不对外暴露
  port: 8000
  auto_open_browser: true     # 启动后自动打开浏览器
  log_buffer_size: 5000       # 每个 run 的内存日志行数上限
  log_dir: "./logs/webui"     # 日志落盘目录
  metrics_push_interval: 0.5  # 指标合并推送间隔(秒)
  device_cache_ttl: 30        # 设备型号/电量缓存时间(秒)
  stop_grace_break: 5         # CTRL_BREAK 后等待秒数
  stop_grace_term: 3          # terminate 后等待秒数

  # 点击编排任务默认参数（可在 UI 上覆盖）
  sync_click_defaults:
    button_id: "com.keenon.solutionindustry:id/tv_start"
    filter_texts:
      - "结束调度"
    poll_interval: 0.5
    click_cooldown: 2.0
    connect_retries: 3
```

> `button_id` 与 `filter_texts` 与现有 `dual_click` 段语义重复。**读取优先级**：`webui.sync_click_defaults` > `dual_click` > 代码内置默认值。这样老配置仍生效，不产生破坏性变更。

### 10.2 依赖新增

`requirements.txt` 追加：
```
# Web UI dependencies
fastapi>=0.110.0
uvicorn[standard]>=0.27.0
```

- `uvicorn[standard]` 含 `websockets` + `httptools`，WebSocket 必需
- 不引入 `pydantic` 显式依赖（FastAPI 自带）
- 不引入前端相关依赖

### 10.3 `start_webui.bat`

```
@echo off
chcp 65001 >nul                          REM 与 setup_env.bat 保持一致
cd /d "%~dp0"

REM 支持传参覆盖端口：start_webui.bat 8010
set PORT=%1
if "%PORT%"=="" set PORT=8000

[1/3] 检查 Python（沿用 setup_env.bat 的检查与提示文案）
[2/3] 检查 fastapi/uvicorn 是否已安装，缺失则自动 pip install
[3/3] 检查端口占用（netstat -ano | findstr :%PORT%），占用则提示换端口
启动 uvicorn webui.app:app --host 127.0.0.1 --port %PORT%
延迟 2 秒后 start http://127.0.0.1:%PORT%
窗口保持打开（关闭窗口 = 停止服务，并由 shutdown 钩子清理子进程）
```

**设计要点**
- 端口可传参，避免 8000 被占用时无解
- 依赖缺失自动安装，使用者无需先跑 `setup_env.bat`
- 保持窗口打开：关掉窗口即停服务，符合直觉；FastAPI `shutdown` 钩子负责停掉所有运行中的任务子进程

### 10.4 README 补充

在 `README.md` 增加「Web UI 控制台」章节：启动方式、界面说明、与终端脚本用法的关系（二者共存）。

---

## 11. 开发计划与工时

### 阶段划分

| 阶段 | 内容 | 交付物 | 工时 |
|---|---|---|---|
| **P1** | 执行引擎层 | `engine/` 全部模块 + 单元自测 | **4.0 人日** |
| P1.1 | `events.py` 事件助手 + 编码修复 | | 0.5 |
| P1.2 | `registry.py` 任务目录 + 参数 schema | | 0.5 |
| P1.3 | `runner.py` 子进程生命周期 + 三级停止 + 进程树清理 | | 1.5 |
| P1.4 | `log_bus.py` 环形缓冲 + 跨线程广播 + seq 补齐 | | 0.75 |
| P1.5 | `metrics.py` 守护型指标聚合 | | 0.5 |
| P1.6 | `devices.py` adb 扫描 + 缓存 + 占用检测 | | 0.25 |
| **P2** | 任务脚本改造 | `tasks/sync_click.py`、`tasks/adb_wireless.py` | **1.5 人日** |
| P2.1 | `sync_click.py` 三脚本合并 + 事件化 + 掉线容错 | | 1.0 |
| P2.2 | `adb_wireless.py` 去 input() + 事件化 + `--serial` | | 0.5 |
| **P3** | API 层 | `app.py` REST + WebSocket | **1.5 人日** |
| P3.1 | REST 路由 + 参数校验 + 错误码 | | 0.75 |
| P3.2 | WebSocket 推送 + 心跳 + 快照 | | 0.75 |
| **P4** | 前端 | `static/` 三文件 | **2.5 人日** |
| P4.1 | 布局 + 样式 + 任务表单动态渲染 | | 1.0 |
| P4.2 | 日志窗口（过滤/滚动/上限/下载） | | 0.5 |
| P4.3 | 指标卡 + 设备红绿灯 | | 0.5 |
| P4.4 | canvas 折线图 + WS 重连补齐 | | 0.5 |
| **P5** | 集成与交付 | bat 脚本 + 配置 + 联调 + 文档 | **1.5 人日** |
| P5.1 | `start_webui.bat` + `config.yaml` + `requirements.txt` | | 0.5 |
| P5.2 | 真机联调（多设备启停、编码、残留进程） | | 0.75 |
| P5.3 | README 补充 | | 0.25 |
| | | **合计** | **11.0 人日** |

### 里程碑

| 里程碑 | 完成标志 | 累计工时 |
|---|---|---|
| **M1 可用最小闭环** | 浏览器能启动多机同步任务、看实时日志、点停止且无残留进程 | 7.0 人日 |
| **M2 监控完备** | 指标面板、设备红绿灯、同步等待折线图全部可用 | 9.5 人日 |
| **M3 交付就绪** | bat 双击启动、真机联调通过、文档完成 | 11.0 人日 |

> **M1 即已实现"替代终端手工执行"的核心价值**，可在此节点先投入使用，再继续 M2/M3。

### 建议实施顺序

先做 `P1.1 → P1.3 → P2.1 → P3.1 → P4.1(简版)` 打通「启动-看日志-停止」纵向链路，尽早在真机上验证子进程编码与停止可靠性这两个最高风险点，再横向补齐指标与美化。**不要先把 engine 全部写完再联调**——Windows 子进程行为需要尽早在真机上暴露。

---

## 12. 测试计划

### 12.1 功能测试

| # | 场景 | 步骤 | 预期 |
|---|---|---|---|
| T1 | 无设备启动 | 不连任何设备，双击 bat | 服务正常起，页面正常显示，设备列表为空且提示"未检测到设备，请先建立 ADB 连接" |
| T2 | 端口占用 | 先占用 8000，再启动 | bat 明确提示端口占用及换端口用法，不静默失败 |
| T3 | 依赖缺失 | 在干净环境双击 bat | 自动 pip install fastapi/uvicorn 后正常启动 |
| T4 | 预设切换 | 依次切换单机/双机/多机 | 参数表单正确重渲染并回填默认值 |
| T5 | 设备勾选校验 | 选「双机同步」但只勾 1 台 | 启动按钮禁用并提示需选 2 台 |
| T6 | 启停闭环 | 启动多机同步 → 观察日志 → 点停止 | 日志实时滚动；停止后出现"脚本停止运行"，状态转 stopped，退出码 0 |
| T7 | **无残留进程** | T6 后执行 `tasklist \| findstr python` | 除 Web 服务自身外无残留 python 进程；`adb devices` 设备状态正常 |
| T8 | 指标正确性 | 手动让机器人到位触发点击，核对面板 | 同步批次数、点击成功数、`wait_ms` 与日志逐条一致 |
| T9 | 断线重连 | 运行中刷新浏览器 | 自动重连，日志按 seq 补齐，不丢行不重复；指标继续更新 |
| T10 | **中文编码** | 查看含中文与 emoji 的日志 | 页面与 `logs/webui/*.log` 中均正常显示，无 `???` 或乱码 |
| T11 | 掉线容错 | 运行中断开一台设备网络 | 任务不退出；该设备红灯；恢复后自动重连，`reconnects` +1 |
| T12 | 无线 ADB 连接 | USB 连接机器人后点按钮 | 输出 IP、连接成功；设备列表出现无线地址；任务自动结束 |
| T13 | 设备占用冲突 | 用设备 A 启动 run1，再用 A 启动 run2 | 返回 409，前端提示被 run1 占用 |
| T14 | 多 run 并行 | 设备 A/B 启一个 run，C/D 启另一个 | 两个 run 独立运行，日志与指标互不干扰 |
| T15 | 脚本崩溃 | 人为让脚本抛未捕获异常 | Traceback 出现在 Web 日志中；status 转 failed；Web 服务不受影响 |
| T16 | 服务关闭清理 | 运行中直接关掉 bat 窗口 | 所有任务子进程被清理，无孤儿进程 |
| T17 | 高频日志 | 让脚本高速输出日志 | 页面不卡死；超过缓冲时有"已丢弃 N 行"提示而非崩溃 |
| T18 | 日志下载 | 点下载按钮 | 得到完整 `.log` 文件，内容与页面一致 |

### 12.2 回归测试（确保不破坏现有功能）

| # | 场景 | 预期 |
|---|---|---|
| R1 | `python 点击编排任务/多机同步任务编排.py` | 终端用法完全不受影响 |
| R2 | `python 点击编排任务/adbconnect.py` | 原交互式行为保留 |
| R3 | `cd tests; python transport_stress_test_machine1.py` | 搬运压测不受影响 |
| R4 | `config.yaml` 删掉 `webui:` 整段后启动 Web UI | 使用内置默认值正常启动 |
| R5 | MCP server 启动 | `src/mcp_server/` 不受影响 |

### 12.3 重点关注的两个高风险验证点

1. **T7 无残留进程** —— uiautomator2 派生 adb 子进程，是最容易出问题的地方。必须在多设备场景下反复验证 kill 进程树的完整性。
2. **T10 中文编码** —— Windows GBK 是本仓库已踩过的坑（`transport_stress_base.py:27-30` 有修复痕迹）。需覆盖三条链路：子进程 stdout → Web 页面、子进程 stdout → 日志文件、异常 Traceback 中的中文。

---

## 13. 风险与对策

| # | 风险 | 等级 | 影响 | 对策 |
|---|---|---|---|---|
| 1 | **子进程残留** | 高 | 设备被占用，后续任务无法启动 | 三级停止 + `taskkill /T /F` 进程树清理 + FastAPI `shutdown` 钩子兜底；T7 专项验证 |
| 2 | **Windows 中文乱码** | 高 | 日志不可读，失去核心价值 | `PYTHONIOENCODING=utf-8` + `PYTHONUTF8=1` + `encoding="utf-8", errors="replace"` + `ensure_ascii=False` 四重保障；T10 专项验证 |
| 3 | `CTRL_BREAK_EVENT` 未生效 | 中 | 停止退化为强杀，无 summary | 前置条件是 `CREATE_NEW_PROCESS_GROUP`，务必设置；已有 terminate/kill 两级降级兜底 |
| 4 | 高频日志压垮前端 | 中 | 页面卡死 | 后端 asyncio.Queue 有界 + 丢弃提示；指标 500ms 合并；前端 DOM 限 3000 行 |
| 5 | adb 命令卡死 | 中 | Web 请求挂住 | 所有 `subprocess.run` 加 `timeout=5`；设备信息加 30s 缓存 |
| 6 | 设备电量/型号查询慢 | 低 | 设备列表刷新卡顿 | 30s TTL 缓存；首次加载异步补齐，不阻塞列表返回 |
| 7 | 原生 JS 后期维护成本 | 低 | UI 复杂化后难维护 | REST + WS 契约已解耦；届时只替换前端为 Vue，后端零改动 |
| 8 | 脚本合并引入回归 | 中 | 新脚本行为与原脚本不一致 | 原脚本保留不动（R1/R2 回归）；新脚本在真机上与原脚本对比验证点击时序 |
| 9 | 弹出 adb 黑框窗口 | 低 | 体验干扰 | Windows 下统一加 `CREATE_NO_WINDOW` |

---

## 14. 后续扩展路线

### 二期：能力增强（预估 4–5 人日）

| 项 | 说明 |
|---|---|
| 历史 run 持久化 | 引入 SQLite，服务重启后 run 记录不丢；支持按时间/任务筛选 |
| 设备管理页 | 无线连接批量管理、`config.yaml` 中 `devices` 段的可视化编辑 |
| 任务调度 | 定时启动、按次数自动停止、异常自动重启 |
| 消息通知 | 连续失败 / 任务结束时企微或钉钉推送 |

### 三期：接入压测框架（预估 3–4 人日）

`TransportStressTest` 与 `DualTransportController` **已是可复用类**（含 `results[]`、`_report()`、`SyncPoint` 屏障），接入成本低：

| 项 | 说明 |
|---|---|
| 注册轮次型任务 | `registry.py` 追加 `TaskSpec(metrics_kind="cycle")`，参数取自 `transport_stress` 配置段 |
| `CycleMetrics` 聚合 | 总轮次/成功率/平均轮耗时/熔断状态/电量保护触发 |
| 轮次型面板 | 前端按 `metrics_kind` 分派渲染 |
| 报告与截图浏览 | 列出 `reports/*.md` 与 `reports/screenshots/*.png`，在页面内查看 |
| 双机同步可视化 | 展示 `SyncPoint` 屏障等待状态（哪台在等哪台） |

### 可选项

| 项 | 说明 |
|---|---|
| PyInstaller 打包 exe | 目标机器无需 Python 环境；需处理 uiautomator2 资源文件打包，预估额外 1.5–2 人日 |
| 前端换 Vue3 | 若 UI 需求超出原生 JS 承载能力；后端零改动，预估 5–7 人日 |
| 接入 MCP | 将 Web UI 的任务能力同时暴露为 MCP 工具，复用 `src/mcp_server/` 架构 |

---

## 附录 A：参考文件索引

### 一期直接相关

| 文件 | 作用 | 一期动作 |
|---|---|---|
| `点击编排任务/单线程任务编排.py` | 单机监听点击 | 逻辑移植，原文件不动 |
| `点击编排任务/双线程任务编排.py` | 双机同步点击 | 逻辑移植，原文件不动 |
| `点击编排任务/多机同步任务编排.py` | N 机同步点击（主要参考蓝本） | 逻辑移植，原文件不动 |
| `点击编排任务/adbconnect.py` | USB 转无线 ADB | 移植去 `input()`，原文件不动 |
| `config.yaml` | 统一配置 | 追加 `webui:` 段 |
| `requirements.txt` | 依赖清单 | 追加 fastapi / uvicorn |
| `setup_env.bat` | 环境初始化（bat 写法参考） | 不动 |

### 三期相关

| 文件 | 作用 |
|---|---|
| `tests/transport_stress_base.py` | `TransportStressTest` 基类，含 `run_one` / `run` / `_report` / 熔断 / 电量保护 |
| `tests/transport_stress_dual.py` | `DualTransportController` + `SyncPoint` 同步屏障 |
| `tests/transport_stress_test_machine1.py` / `machine2.py` | 双机分布式入口 |

### 可复用的既有抽象

| 文件 | 可复用点 |
|---|---|
| `src/mcp_server/adapters/config_adapter.py` | `config.yaml` 加载与单例模式写法参考 |
| `src/mcp_server/adapters/driver_adapter.py` | uiautomator2 连接池、电量获取、截图 |
| `src/mcp_server/tools/base_tool.py` | 参数 schema 定义风格参考（`input_schema`） |
| `utils/app_helper.py`、`pages/base_page.py` | PO 模式封装（注意其日志用 `print`） |

---

**文档结束。开工前请确认本文档第 1.4 节的锁定决策仍然成立。**

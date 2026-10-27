/* AMR 压测控制台 — 原生 JS，零构建零 CDN
 * 交互契约见 docs/WEBUI_开发方案.md 第 9 章
 */
"use strict";

const $ = (id) => document.getElementById(id);

const state = {
  tasks: [],
  taskMap: {},
  currentTask: null,
  devices: [],
  picked: new Set(),
  runId: null,
  runInfo: null,
  readonly: false,          // 查看已结束 run 的历史日志
  ws: null,
  wsRetry: 0,
  reconnectTimer: null,
  lines: [],                // 全量日志行 (上限 3000)
  maxSeq: 0,
  metrics: null,
  filterLevel: "",
  filterText: "",
};

const LOG_CAP = 3000;

/* ============================================================
 * 工具函数
 * ============================================================ */

async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  if (!r.ok) {
    let msg = `HTTP ${r.status}`;
    try {
      const d = await r.json();
      msg = (d && d.detail && (d.detail.message || d.detail)) || msg;
    } catch (_) { /* ignore */ }
    throw new Error(msg);
  }
  return r.json();
}

function toast(msg, kind = "info") {
  const el = $("toast");
  el.textContent = msg;
  el.className = "show " + (kind === "err" ? "err" : kind === "ok" ? "ok" : "");
  clearTimeout(toast._t);
  toast._t = setTimeout(() => { el.className = ""; }, 4000);
}

function fmtDur(sec) {
  if (sec == null || isNaN(sec)) return "-";
  sec = Math.floor(sec);
  const h = String(Math.floor(sec / 3600)).padStart(2, "0");
  const m = String(Math.floor((sec % 3600) / 60)).padStart(2, "0");
  const s = String(sec % 60).padStart(2, "0");
  return `${h}:${m}:${s}`;
}

function fmtClock(ts) {
  if (!ts) return "";
  const d = new Date(ts * 1000);
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`;
}

/* ============================================================
 * 任务预设与参数表单
 * ============================================================ */

async function loadTasks() {
  state.tasks = await api("/api/tasks");
  state.taskMap = Object.fromEntries(state.tasks.map((t) => [t.id, t]));
  renderPresets();
  if (!state.currentTask && state.tasks.length) selectTask(state.tasks[0].id);
}

function renderPresets() {
  const box = $("preset-list");
  box.replaceChildren();
  const groups = {};
  for (const t of state.tasks) (groups[t.group] ||= []).push(t);
  for (const [group, tasks] of Object.entries(groups)) {
    const gh = document.createElement("div");
    gh.className = "preset-group";
    gh.textContent = group;
    box.appendChild(gh);
    for (const t of tasks) {
      const label = document.createElement("label");
      label.className = "preset-item";
      const radio = document.createElement("input");
      radio.type = "radio";
      radio.name = "preset";
      radio.value = t.id;
      radio.checked = state.currentTask && state.currentTask.id === t.id;
      radio.onchange = () => selectTask(t.id);
      label.appendChild(radio);
      label.appendChild(document.createTextNode(t.name));
      box.appendChild(label);
    }
  }
}

function selectTask(taskId) {
  state.currentTask = state.taskMap[taskId];
  const t = state.currentTask;
  $("task-desc").textContent = t ? t.description : "";
  $("mock-row").hidden = !(t && t.supports_mock);
  $("device-section").style.display = t && t.uses_devices ? "" : "none";
  renderParamForm();
}

function renderParamForm() {
  const box = $("param-form");
  box.replaceChildren();
  const t = state.currentTask;
  if (!t) return;
  const saved = JSON.parse(localStorage.getItem(`webui.params.${t.id}`) || "{}");
  for (const p of t.params) {
    if (p.type === "devices") continue;   // 设备选择由独立区域承担
    const row = document.createElement("div");
    row.className = "param-row";
    const label = document.createElement("label");
    label.textContent = p.label + (p.required ? " *" : "");
    row.appendChild(label);

    let input;
    if (p.type === "int" || p.type === "float") {
      input = document.createElement("input");
      input.type = "number";
      if (p.min != null) input.min = p.min;
      if (p.max != null) input.max = p.max;
      input.step = p.type === "float" ? "0.1" : "1";
      input.value = saved[p.key] != null ? saved[p.key] : p.default;
    } else {
      input = document.createElement("input");
      input.type = "text";
      const dv = saved[p.key] != null ? saved[p.key] : p.default;
      input.value = Array.isArray(dv) ? dv.join(",") : (dv == null ? "" : dv);
    }
    input.dataset.key = p.key;
    input.dataset.ptype = p.type;
    row.appendChild(input);

    if (p.help) {
      const help = document.createElement("div");
      help.className = "param-help";
      help.textContent = p.help;
      row.appendChild(help);
    }
    box.appendChild(row);
  }
}

function collectParams() {
  const t = state.currentTask;
  const params = {};
  if (!t) return params;
  const saved = {};
  for (const input of $("param-form").querySelectorAll("input")) {
    const key = input.dataset.key;
    const ptype = input.dataset.ptype;
    let val = input.value;
    if (ptype === "int") val = parseInt(val, 10);
    else if (ptype === "float") val = parseFloat(val);
    else if (t.params.find((p) => p.key === key)?.type === "tags") {
      val = val.split(/[,，]/).map((s) => s.trim()).filter(Boolean);
    }
    if (val === "" || (typeof val === "number" && isNaN(val))) {
      const spec = t.params.find((p) => p.key === key);
      val = spec ? spec.default : null;
    }
    params[key] = val;
    saved[key] = input.value;
  }
  localStorage.setItem(`webui.params.${t.id}`, JSON.stringify(saved));
  return params;
}

/* ============================================================
 * 设备列表
 * ============================================================ */

async function loadDevices(force = false) {
  try {
    state.devices = await api("/api/devices");
  } catch (e) {
    state.devices = [];
  }
  renderDevicePick();
}

function showMuted(container, text) {
  const p = document.createElement("p");
  p.className = "muted";
  p.textContent = text;
  container.replaceChildren(p);
}

async function refreshDevices() {
  try {
    const list = await api("/api/adb/scan", { method: "POST" });
    state.devices = list;
    renderDevicePick();
    toast(`扫描完成，共 ${list.length} 台设备`, "ok");
  } catch (e) {
    toast("设备扫描失败: " + e.message, "err");
  }
}

function renderDevicePick() {
  const box = $("device-pick");
  box.replaceChildren();
  if (!state.devices.length) {
    showMuted(box, "未检测到设备。可勾选「演示模式」模拟，或用 USB 连接后点「刷新设备」。");
    return;
  }
  for (const d of state.devices) {
    const item = document.createElement("label");
    item.className = "dev-pick-item" + (d.busy_run_id ? " busy" : "");
    const cb = document.createElement("input");
    cb.type = "checkbox";
    cb.value = d.addr;
    cb.checked = state.picked.has(d.addr);
    cb.disabled = !!d.busy_run_id;
    cb.onchange = () => {
      if (cb.checked) state.picked.add(d.addr);
      else state.picked.delete(d.addr);
    };
    item.appendChild(cb);
    const meta = document.createElement("span");
    const parts = [d.addr];
    if (d.model) parts.push(d.model);
    if (d.battery != null) parts.push(`${d.battery}%`);
    if (d.state !== "device") parts.push(`[${d.state}]`);
    if (d.busy_run_id) parts.push(`(被 ${d.busy_run_id} 占用)`);
    meta.className = "dev-meta";
    meta.textContent = parts.join(" ");
    item.appendChild(meta);
    box.appendChild(item);
  }
}

/* ============================================================
 * 启动 / 停止
 * ============================================================ */

async function startRun() {
  const t = state.currentTask;
  if (!t) return toast("请先选择任务", "err");
  const params = collectParams();

  if (t.uses_devices) {
    const devs = [...state.picked];
    if (t.id === "sync_click_dual" && devs.length !== 2) {
      return toast("「双机同步」需恰好勾选 2 台设备（或一台不勾，留空自动检测会被拒绝）", "err");
    }
    if (devs.length) params.devices = devs;
  }
  if (t.supports_mock && $("mock-mode").checked) params.mock = true;

  try {
    const r = await api("/api/runs", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ task_id: t.id, params }),
    });
    toast(`任务已启动: ${r.run_id}`, "ok");
    attachRun(r.run_id);
    loadDevices();
    loadHistory();
  } catch (e) {
    toast("启动失败: " + e.message, "err");
  }
}

async function stopRun() {
  if (!state.runId) return;
  try {
    await api(`/api/runs/${state.runId}/stop`, { method: "POST" });
    toast("停止指令已发送，等待任务优雅退出…");
  } catch (e) {
    toast("停止失败: " + e.message, "err");
  }
}

/* ============================================================
 * 运行绑定 / WebSocket
 * ============================================================ */

function attachRun(runId, readonly = false) {
  disconnectWS();
  state.runId = runId;
  state.readonly = readonly;
  state.lines = [];
  state.maxSeq = 0;
  state.metrics = null;
  $("log-body").replaceChildren();
  $("log-title").textContent = `实时日志 — ${runId}`;
  $("btn-download-log").disabled = false;
  updateButtons();
  if (readonly) {
    loadHistoricLogs(runId);
  } else {
    connectWS();
  }
  loadHistory();
}

function disconnectWS() {
  clearTimeout(state.reconnectTimer);
  if (state.ws) {
    state.ws.onclose = null;
    state.ws.close();
    state.ws = null;
  }
  setSvc("off");
}

function setSvc(cls) {
  const dot = $("svc-dot");
  dot.className = "dot " + (cls === "on" ? "on" : cls === "off" ? "off" : "");
  $("svc-text").textContent = cls === "on" ? "实时连接正常" : cls === "off" ? "未连接" : "连接中…";
}

function connectWS() {
  if (!state.runId || state.readonly) return;
  const proto = location.protocol === "https:" ? "wss" : "ws";
  const ws = new WebSocket(`${proto}://${location.host}/ws/runs/${state.runId}`);
  state.ws = ws;

  ws.onopen = () => {
    state.wsRetry = 0;
    setSvc("on");
    catchUp();   // 断线重连后按 maxSeq 补齐，保证不丢行
  };
  ws.onmessage = (e) => {
    let m;
    try { m = JSON.parse(e.data); } catch (_) { return; }
    handleWS(m);
  };
  ws.onclose = () => {
    setSvc("off");
    if (state.runId && !state.readonly && state.runInfo &&
        ["starting", "running", "stopping"].includes(state.runInfo.status)) {
      scheduleReconnect();
    }
  };
  ws.onerror = () => { /* onclose 会接管重连 */ };
}

function scheduleReconnect() {
  const delay = Math.min(8000, 1000 * Math.pow(2, state.wsRetry++));
  clearTimeout(state.reconnectTimer);
  state.reconnectTimer = setTimeout(connectWS, delay);
}

async function catchUp() {
  try {
    const d = await api(`/api/runs/${state.runId}/logs?from=${state.maxSeq}&limit=2000`);
    for (const ln of d.lines) {
      if (ln.seq > state.maxSeq) pushLine(ln);
    }
  } catch (_) { /* 服务可能重启，忽略 */ }
}

function handleWS(m) {
  if (m.type === "hello") {
    state.runInfo = m.data.run;
    if (m.data.metrics) updateMetrics(m.data.metrics);
    updateButtons();
  } else if (m.type === "log") {
    for (const ln of m.lines) {
      if (ln.seq > state.maxSeq) pushLine(ln);
    }
  } else if (m.type === "metrics") {
    updateMetrics(m.data);
  } else if (m.type === "status") {
    if (state.runInfo) state.runInfo.status = m.data.status;
    if (state.runInfo) state.runInfo.exit_code = m.data.exit_code;
    updateButtons();
    loadHistory();
    if (m.data.status === "stopped") toast(`任务已结束 (exit_code=${m.data.exit_code})`, "ok");
    if (m.data.status === "failed") toast(`任务异常退出 (exit_code=${m.data.exit_code})`, "err");
  }
}

function updateButtons() {
  const active = state.runInfo && ["starting", "running", "stopping"].includes(state.runInfo.status);
  $("btn-stop").disabled = !(active && !state.readonly);
}

/* ============================================================
 * 日志渲染 (本地过滤 + 上限 + 自动滚动)
 * ============================================================ */

function pushLine(ln, skipRender = false) {
  state.lines.push(ln);
  if (state.lines.length > LOG_CAP) state.lines.splice(0, state.lines.length - LOG_CAP);
  if (!skipRender && passesFilter(ln)) appendLogNode(ln);
}

function passesFilter(ln) {
  if (state.filterLevel && ln.level !== state.filterLevel) return false;
  if (state.filterText && !ln.text.toLowerCase().includes(state.filterText.toLowerCase())) return false;
  return true;
}

function appendLogNode(ln) {
  const body = $("log-body");
  const nearBottom = body.scrollHeight - body.scrollTop - body.clientHeight < 40;
  const div = document.createElement("div");
  div.className = `log-line ${ln.level || "info"}`;
  const ts = document.createElement("span");
  ts.className = "ts";
  ts.textContent = fmtClock(ln.ts);
  const txt = document.createElement("span");
  txt.className = "txt";
  txt.textContent = ln.text;
  div.appendChild(ts);
  div.appendChild(txt);
  body.appendChild(div);
  while (body.childElementCount > LOG_CAP) body.removeChild(body.firstChild);
  if ((nearBottom || $("log-autoscroll").checked) && $("log-autoscroll").checked) {
    body.scrollTop = body.scrollHeight;
  }
}

function rerenderLogs() {
  const body = $("log-body");
  body.replaceChildren();
  for (const ln of state.lines) if (passesFilter(ln)) appendLogNode(ln);
}

async function loadHistoricLogs(runId) {
  try {
    const d = await api(`/api/runs/${runId}/logs?from=0&limit=2000`);
    state.lines = [];
    $("log-body").replaceChildren();
    for (const ln of d.lines) pushLine(ln, true);
    rerenderLogs();
    const info = await api(`/api/runs/${runId}`);
    state.runInfo = info.run;
    if (info.metrics) updateMetrics(info.metrics);
    updateButtons();
  } catch (e) {
    toast("加载历史日志失败: " + e.message, "err");
  }
}

/* ============================================================
 * 指标卡 / 设备红绿灯 / 折线图
 * ============================================================ */

function updateMetrics(m) {
  state.metrics = m;
  if (!m) return;
  setText("m-duration", fmtDur(m.duration_s));
  setText("m-devices", m.device_total ? `${m.online_count}/${m.device_total}` : "-");
  setText("m-batches", m.batches ?? "-");

  const rateEl = $("m-rate");
  if (m.click_success_rate == null) { rateEl.textContent = "-"; rateEl.className = "card-value"; }
  else {
    rateEl.textContent = m.click_success_rate + "%";
    rateEl.className = "card-value " + (m.click_success_rate < 95 ? "bad" : "good");
  }
  const waitEl = $("m-wait");
  if (m.avg_wait_ms == null) { waitEl.textContent = "-"; waitEl.className = "card-value"; }
  else {
    waitEl.textContent = m.avg_wait_ms + "ms";
    waitEl.className = "card-value " + (m.avg_wait_ms > 3000 ? "warn" : "");
  }
  const failEl = $("m-fails");
  failEl.textContent = m.consecutive_fails ?? 0;
  failEl.className = "card-value " + (m.consecutive_fails >= 3 ? "bad" : "");

  renderDeviceBoard(m.devices || []);
  drawChart(m.wait_series || []);
}

function setText(id, v) { $(id).textContent = v; }

function renderDeviceBoard(devices) {
  const tbody = $("device-board").querySelector("tbody");
  tbody.replaceChildren();
  if (!devices.length) {
    const tr = document.createElement("tr");
    const td = document.createElement("td");
    td.colSpan = 5;
    td.className = "muted";
    td.textContent = "暂无设备数据";
    tr.appendChild(td);
    tbody.appendChild(tr);
    return;
  }
  for (const d of devices) {
    const tr = document.createElement("tr");
    const tdName = document.createElement("td");
    tdName.textContent = d.name || d.addr;
    const tdAddr = document.createElement("td");
    tdAddr.className = "addr";
    tdAddr.textContent = d.addr;

    const tdOnline = document.createElement("td");
    const l1 = document.createElement("span");
    l1.className = "light " + (d.online ? "green" : "red");
    tdOnline.appendChild(l1);

    const tdReady = document.createElement("td");
    const l2 = document.createElement("span");
    // 绿=就绪；灰=未出现；黄=出现但被过滤文本拦下
    l2.className = "light " + (d.btn_ready ? "green" : (!d.online ? "" : d.text ? "yellow" : ""));
    tdReady.appendChild(l2);

    const tdText = document.createElement("td");
    tdText.textContent = d.text || "-";

    tr.appendChild(tdName); tr.appendChild(tdAddr);
    tr.appendChild(tdOnline); tr.appendChild(tdReady); tr.appendChild(tdText);
    tbody.appendChild(tr);
  }
}

function drawChart(series) {
  const cv = $("wait-chart");
  const ctx = cv.getContext("2d");
  const W = cv.width, H = cv.height, PAD = 24;
  ctx.clearRect(0, 0, W, H);

  ctx.strokeStyle = "#2a3542";
  ctx.beginPath();
  ctx.moveTo(PAD, H - PAD); ctx.lineTo(W - 8, H - PAD);
  ctx.moveTo(PAD, 8); ctx.lineTo(PAD, H - PAD);
  ctx.stroke();

  if (!series.length) {
    ctx.fillStyle = "#7d8a99";
    ctx.font = "12px sans-serif";
    ctx.fillText("暂无批次数据", W / 2 - 36, H / 2);
    return;
  }

  const vals = series.map((p) => p[1]);
  const maxV = Math.max(...vals, 1);
  const plotW = W - PAD - 16, plotH = H - PAD - 16;
  const stepX = series.length > 1 ? plotW / (series.length - 1) : 0;

  ctx.fillStyle = "#7d8a99";
  ctx.font = "10px monospace";
  ctx.fillText(String(maxV), 2, 14);
  ctx.fillText("0", 2, H - PAD);

  ctx.strokeStyle = "#2f81f7";
  ctx.lineWidth = 1.5;
  ctx.beginPath();
  series.forEach((p, i) => {
    const x = PAD + i * stepX;
    const y = H - PAD - (p[1] / maxV) * plotH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

/* ============================================================
 * 运行时长计时器 (每秒刷新)
 * ============================================================ */

setInterval(() => {
  const active = state.runInfo && ["starting", "running"].includes(state.runInfo.status);
  if (active && state.runInfo.started_at) {
    setText("m-duration", fmtDur(Date.now() / 1000 - state.runInfo.started_at));
  }
}, 1000);

/* ============================================================
 * 运行历史
 * ============================================================ */

async function loadHistory() {
  try {
    const runs = await api("/api/runs");
    const box = $("run-history");
    box.replaceChildren();
    if (!runs.length) {
      showMuted(box, "暂无记录");
      return;
    }
    for (const r of runs.slice(0, 20)) {
      const item = document.createElement("div");
      item.className = "hist-item" + (r.run_id === state.runId ? " current" : "");
      const st = document.createElement("span");
      st.className = `hist-status status-${r.status}`;
      st.textContent = r.status;
      item.appendChild(st);
      item.appendChild(document.createTextNode(`${r.task_name} · ${fmtClock(r.started_at)}`));
      if (r.batches != null) {
        item.appendChild(document.createTextNode(` · ${r.batches}批次`));
      }
      item.onclick = () => {
        const isActive = ["starting", "running", "stopping"].includes(r.status);
        attachRun(r.run_id, !isActive);
      };
      box.appendChild(item);
    }
  } catch (_) { /* 忽略 */ }
}

/* ============================================================
 * 初始化
 * ============================================================ */

function bindEvents() {
  $("btn-start").onclick = startRun;
  $("btn-stop").onclick = stopRun;
  $("btn-refresh-devices").onclick = refreshDevices;
  $("btn-clear-log").onclick = () => { state.lines = []; $("log-body").replaceChildren(); };
  $("btn-download-log").onclick = () => {
    if (state.runId) window.open(`/api/runs/${state.runId}/logfile`, "_blank");
  };
  $("log-level").onchange = (e) => { state.filterLevel = e.target.value; rerenderLogs(); };
  $("log-filter").oninput = (e) => { state.filterText = e.target.value; rerenderLogs(); };
  $("log-autoscroll").onchange = (e) => {
    if (e.target.checked) $("log-body").scrollTop = $("log-body").scrollHeight;
  };
}

async function init() {
  bindEvents();
  try {
    await loadTasks();
  } catch (e) {
    toast("加载任务目录失败: " + e.message, "err");
  }
  await loadDevices();
  await loadHistory();
  // 页面刷新后自动重连运行中的 run
  try {
    const runs = await api("/api/runs");
    const active = runs.find((r) => ["starting", "running"].includes(r.status));
    if (active) attachRun(active.run_id, false);
  } catch (_) { /* 忽略 */ }
}

init();

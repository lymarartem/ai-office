import asyncio
import logging
from datetime import datetime

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse

import bot.approval as approval
import bot.memory as memory
import bot.logger_buffer as log_buffer
import bot.permissions as permissions
import bot.git_manager as git
from bot.task_queue import queue
from bot.event_bus import bus

logger = logging.getLogger(__name__)

app = FastAPI(title="AI Office Dashboard")

_start_time = datetime.now()
_agent_calls: dict = {
    "CEO": 0, "Developer": 0, "Marketing": 0, "Designer": 0
}


def track_call(agent_name: str) -> None:
    for key in _agent_calls:
        if key.lower() in agent_name.lower():
            _agent_calls[key] += 1
            break


@app.websocket("/ws/events")
async def ws_events(websocket: WebSocket):
    await websocket.accept()
    bus.register_ws(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        bus.unregister_ws(websocket)


@app.get("/api/metrics")
async def metrics():
    proposals = approval.all_proposals()
    approved  = sum(1 for p in proposals if p["status"] == "approved")
    rejected  = sum(1 for p in proposals if p["status"] == "rejected")
    pending   = sum(1 for p in proposals if p["status"] == "pending")
    uptime    = str(datetime.now() - _start_time).split(".")[0]
    tasks     = queue.all()
    return JSONResponse({
        "uptime":       uptime,
        "proposals":    {"total": len(proposals), "approved": approved,
                         "rejected": rejected, "pending": pending},
        "tasks":        {"total": len(tasks),
                         "done": sum(1 for t in tasks if t.status.value == "done"),
                         "failed": sum(1 for t in tasks if t.status.value == "failed"),
                         "pending": len(queue.pending())},
        "agent_calls":  _agent_calls,
        "git_branch":   git.current_branch() if git.is_repo() else "—",
        "git_status":   git.status() if git.is_repo() else "—",
        "memory_count": len(memory.load()),
    })


@app.get("/api/proposals")
async def get_proposals():
    return JSONResponse(approval.all_proposals()[-20:])


@app.get("/api/memory")
async def get_memory():
    return JSONResponse(memory.load()[-20:])


@app.get("/api/logs")
async def get_logs():
    return JSONResponse(log_buffer.get_logs(100))


@app.get("/api/tasks")
async def get_tasks():
    return JSONResponse([
        {"id": t.id, "name": t.name, "status": t.status.value,
         "created": t.created, "started": t.started,
         "finished": t.finished, "error": t.error}
        for t in queue.all()[-20:]
    ])


@app.get("/api/events")
async def get_events():
    return JSONResponse(bus.get_log(100))


@app.get("/api/plugins")
async def get_plugins():
    from bot.plugins.registry import registry
    return JSONResponse(registry.stats())


@app.get("/api/agents")
async def get_agents():
    from bot.distributed import _local_agents, _remote_agents
    from bot.self_healing import get_breaker
    result = []
    for name, agent in _local_agents.items():
        cb = get_breaker(agent.name)
        result.append({
            "name":    agent.name,
            "model":   agent.model,
            "type":    "local",
            "circuit": cb.state.value,
            "calls":   cb.total_calls,
            "failures": cb.total_failures,
        })
    for name, url in _remote_agents.items():
        result.append({"name": name, "type": "remote", "url": url})
    return JSONResponse(result)


@app.get("/api/health")
async def get_health():
    from bot.self_healing import all_breakers, monitor
    from bot.vector_memory import count as vmem_count
    return JSONResponse({
        "breakers":   {n: {"state": cb.state.value,
                           "calls": cb.total_calls,
                           "failures": cb.total_failures}
                       for n, cb in all_breakers().items()},
        "components": monitor.get_status(),
        "alerts":     monitor.get_alerts()[-10:],
        "vector_db":  vmem_count(),
    })


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    return HTMLResponse(content=_HTML)


async def start_server(port: int) -> None:
    config = uvicorn.Config(
        app=app, host="0.0.0.0", port=port, log_level="warning"
    )
    server = uvicorn.Server(config)
    logger.info(f"🌐 Dashboard: http://localhost:{port}")
    await server.serve()


_HTML = """<!DOCTYPE html>
<html lang="ru">
<head>
<meta charset="UTF-8">
<title>AI Office Dashboard</title>
<style>
* { margin:0; padding:0; box-sizing:border-box; }
body { background:#0d1117; color:#c9d1d9; font-family:'Segoe UI',monospace; }
header { background:#161b22; border-bottom:1px solid #30363d; padding:16px 24px;
         display:flex; align-items:center; gap:12px; }
header h1 { font-size:18px; color:#f0f6fc; }
.badge { background:#238636; color:#fff; font-size:11px; padding:2px 8px; border-radius:12px; }
.tabs { display:flex; gap:0; border-bottom:1px solid #30363d; padding:0 24px; background:#161b22; }
.tab { padding:10px 20px; cursor:pointer; font-size:13px; color:#8b949e;
       border-bottom:2px solid transparent; }
.tab.active { color:#f0f6fc; border-bottom-color:#58a6ff; }
.panel { display:none; padding:24px; }
.panel.active { display:block; }
.grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(200px,1fr)); gap:16px; margin-bottom:24px; }
.card { background:#161b22; border:1px solid #30363d; border-radius:8px; padding:16px; }
.card h3 { font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:1px; margin-bottom:8px; }
.card .val { font-size:26px; font-weight:700; color:#f0f6fc; }
.card .sub { font-size:12px; color:#8b949e; margin-top:4px; }
table { width:100%; border-collapse:collapse; font-size:13px; }
th { text-align:left; padding:8px 12px; background:#21262d; color:#8b949e; }
td { padding:8px 12px; border-bottom:1px solid #21262d; }
tr:hover td { background:#1c2128; }
.s-approved,.s-done { color:#3fb950; }
.s-rejected,.s-failed { color:#f85149; }
.s-pending,.s-running { color:#d29922; }
.s-closed { color:#3fb950; }
.s-open { color:#f85149; }
.s-half_open { color:#d29922; }
.log-box,.event-box { background:#0d1117; border:1px solid #30363d; border-radius:6px;
                       padding:12px; height:350px; overflow-y:auto; font-size:12px; font-family:monospace; }
.log-INFO { color:#c9d1d9; }
.log-WARNING { color:#d29922; }
.log-ERROR { color:#f85149; }
.log-line,.event-line { padding:3px 0; border-bottom:1px solid #1c2128; }
.evt-agent_responded { color:#58a6ff; }
.evt-proposal_created,.evt-proposal_approved { color:#3fb950; }
.evt-pipeline_started,.evt-pipeline_stage { color:#a371f7; }
.evt-tool_called { color:#d29922; }
.evt-sandbox_executed { color:#f0883e; }
.evt-health_alert { color:#f85149; }
.agents-grid { display:grid; grid-template-columns:repeat(4,1fr); gap:12px; margin-bottom:24px; }
.agent-card { background:#161b22; border:1px solid #30363d; border-radius:8px;
              padding:14px; text-align:center; }
.agent-card .name { font-size:13px; font-weight:600; color:#f0f6fc; }
.agent-card .calls { font-size:22px; font-weight:700; color:#58a6ff; margin:4px 0; }
.agent-card .circuit { font-size:11px; }
h2 { font-size:13px; color:#8b949e; text-transform:uppercase; letter-spacing:1px;
     margin-bottom:12px; border-bottom:1px solid #21262d; padding-bottom:8px; }
code { background:#21262d; padding:2px 6px; border-radius:4px; font-size:12px; }
.refresh { font-size:11px; color:#8b949e; margin-top:8px; }
</style>
</head>
<body>
<header>
  <span>🏢</span>
  <h1>AI Office Dashboard</h1>
  <span class="badge">● LIVE</span>
  <span id="ws-status" style="font-size:11px;color:#8b949e;margin-left:8px">WS: connecting...</span>
  <span style="margin-left:auto;font-size:12px;color:#8b949e" id="uptime"></span>
</header>

<div class="tabs">
  <div class="tab active" onclick="switchTab('overview')">Overview</div>
  <div class="tab" onclick="switchTab('proposals')">Proposals</div>
  <div class="tab" onclick="switchTab('events')">Events</div>
  <div class="tab" onclick="switchTab('plugins')">Plugins</div>
  <div class="tab" onclick="switchTab('agents')">Agents</div>
  <div class="tab" onclick="switchTab('logs')">Logs</div>
  <div class="tab" onclick="switchTab('health')">Health</div>
</div>

<!-- OVERVIEW -->
<div id="tab-overview" class="panel active">
  <div class="grid">
    <div class="card"><h3>Proposals</h3><div class="val" id="m-total">—</div><div class="sub" id="m-sub">—</div></div>
    <div class="card"><h3>Tasks</h3><div class="val" id="t-total">—</div><div class="sub" id="t-sub">—</div></div>
    <div class="card"><h3>Memory</h3><div class="val" id="mem-count">—</div><div class="sub">решений</div></div>
    <div class="card"><h3>Git Branch</h3><div class="val" style="font-size:15px;padding-top:6px" id="git-branch">—</div><div class="sub" id="git-status">—</div></div>
  </div>
  <h2>Агенты</h2>
  <div class="agents-grid" id="agents-overview"></div>
</div>

<!-- PROPOSALS -->
<div id="tab-proposals" class="panel">
  <table>
    <thead><tr><th>ID</th><th>Название</th><th>Статус</th><th>Pre-tests</th><th>Дата</th></tr></thead>
    <tbody id="proposals-tbody"></tbody>
  </table>
</div>

<!-- EVENTS -->
<div id="tab-events" class="panel">
  <h2>Live Events <span id="event-count" style="color:#58a6ff"></span></h2>
  <div class="event-box" id="event-box"></div>
</div>

<!-- PLUGINS -->
<div id="tab-plugins" class="panel">
  <table>
    <thead><tr><th>Плагин</th><th>Описание</th><th>Вызовов</th><th>Ошибок</th></tr></thead>
    <tbody id="plugins-tbody"></tbody>
  </table>
</div>

<!-- AGENTS -->
<div id="tab-agents" class="panel">
  <table>
    <thead><tr><th>Агент</th><th>Модель</th><th>Тип</th><th>Circuit</th><th>Вызовов</th><th>Сбоев</th></tr></thead>
    <tbody id="agents-tbody"></tbody>
  </table>
</div>

<!-- LOGS -->
<div id="tab-logs" class="panel">
  <div class="log-box" id="log-box"></div>
</div>

<!-- HEALTH -->
<div id="tab-health" class="panel">
  <h2>Circuit Breakers</h2>
  <table>
    <thead><tr><th>Агент</th><th>Состояние</th><th>Вызовов</th><th>Сбоев</th></tr></thead>
    <tbody id="health-tbody"></tbody>
  </table>
  <br>
  <h2>Компоненты</h2>
  <table>
    <thead><tr><th>Компонент</th><th>Статус</th><th>Рестартов</th></tr></thead>
    <tbody id="components-tbody"></tbody>
  </table>
  <br>
  <h2>Vector Memory</h2>
  <div id="vmem-stats" style="font-size:13px;color:#c9d1d9"></div>
</div>

<div class="refresh" id="last-refresh" style="padding:0 24px 12px"></div>

<script>
let activeTab = 'overview';

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t,i) => {
    const tabs = ['overview','proposals','events','plugins','agents','logs','health'];
    t.classList.toggle('active', tabs[i] === name);
  });
  document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
  document.getElementById('tab-' + name).classList.add('active');
  activeTab = name;
}

// WebSocket для live events
const ws = new WebSocket(`ws://${location.host}/ws/events`);
ws.onopen = () => {
  document.getElementById('ws-status').textContent = 'WS: ✅ connected';
  document.getElementById('ws-status').style.color = '#3fb950';
};
ws.onclose = () => {
  document.getElementById('ws-status').textContent = 'WS: ❌ disconnected';
  document.getElementById('ws-status').style.color = '#f85149';
};
ws.onmessage = (e) => {
  const evt = JSON.parse(e.data);
  const box = document.getElementById('event-box');
  const div = document.createElement('div');
  div.className = `event-line evt-${evt.type}`;
  div.innerHTML = `<span style="color:#8b949e">${evt.timestamp}</span> <b>${evt.type}</b> ${JSON.stringify(evt.data).slice(0,120)}`;
  box.prepend(div);
  const count = box.children.length;
  document.getElementById('event-count').textContent = `(${count})`;
  if (count > 200) box.lastChild.remove();
};

async function fetchJSON(url) {
  try { return await (await fetch(url)).json(); } catch { return null; }
}

async function refresh() {
  const m = await fetchJSON('/api/metrics');
  if (m) {
    document.getElementById('uptime').textContent = 'uptime: ' + m.uptime;
    document.getElementById('m-total').textContent = m.proposals.total;
    document.getElementById('m-sub').textContent = `✅${m.proposals.approved} ❌${m.proposals.rejected} ⏳${m.proposals.pending}`;
    document.getElementById('t-total').textContent = m.tasks.total;
    document.getElementById('t-sub').textContent = `done:${m.tasks.done} failed:${m.tasks.failed} pending:${m.tasks.pending}`;
    document.getElementById('mem-count').textContent = m.memory_count;
    document.getElementById('git-branch').textContent = m.git_branch;
    document.getElementById('git-status').textContent = m.git_status || 'clean';
  }

  if (activeTab === 'overview') {
    const agents = await fetchJSON('/api/agents');
    if (agents) {
      document.getElementById('agents-overview').innerHTML = agents.map(a => `
        <div class="agent-card">
          <div class="name">${a.name}</div>
          <div class="calls">${a.calls || 0}</div>
          <div class="label">вызовов</div>
          <div class="circuit s-${a.circuit || 'closed'}">${a.circuit || 'closed'}</div>
        </div>`).join('');
    }
  }

  if (activeTab === 'proposals') {
    const proposals = await fetchJSON('/api/proposals');
    if (proposals) {
      document.getElementById('proposals-tbody').innerHTML = [...proposals].reverse().map(p => `
        <tr>
          <td><code>${p.id}</code></td>
          <td>${p.title}</td>
          <td class="s-${p.status}">${p.status}</td>
          <td>${p.pre_test_passed === null ? '—' : p.pre_test_passed ? '✅' : '❌'}</td>
          <td>${p.created}</td>
        </tr>`).join('');
    }
  }

  if (activeTab === 'plugins') {
    const plugins = await fetchJSON('/api/plugins');
    if (plugins) {
      document.getElementById('plugins-tbody').innerHTML = plugins.map(p => `
        <tr>
          <td><code>${p.name}</code></td>
          <td style="color:#8b949e">${p.description}</td>
          <td style="color:#58a6ff">${p.calls}</td>
          <td style="color:${p.errors > 0 ? '#f85149' : '#3fb950'}">${p.errors}</td>
        </tr>`).join('');
    }
  }

  if (activeTab === 'agents') {
    const agents = await fetchJSON('/api/agents');
    if (agents) {
      document.getElementById('agents-tbody').innerHTML = agents.map(a => `
        <tr>
          <td>${a.name}</td>
          <td><code>${a.model || '—'}</code></td>
          <td>${a.type}</td>
          <td class="s-${a.circuit || 'closed'}">${a.circuit || '—'}</td>
          <td>${a.calls || 0}</td>
          <td style="color:${(a.failures||0) > 0 ? '#f85149' : '#3fb950'}">${a.failures || 0}</td>
        </tr>`).join('');
    }
  }

  if (activeTab === 'logs') {
    const logs = await fetchJSON('/api/logs');
    if (logs) {
      const box = document.getElementById('log-box');
      box.innerHTML = [...logs].reverse().map(l => `
        <div class="log-line log-${l.level}">
          <span style="color:#8b949e">${l.time}</span>
          <span style="color:#58a6ff">[${l.name}]</span> ${l.message}
        </div>`).join('');
    }
  }

  if (activeTab === 'health') {
    const h = await fetchJSON('/api/health');
    if (h) {
      document.getElementById('health-tbody').innerHTML = Object.entries(h.breakers || {}).map(([n, b]) => `
        <tr>
          <td>${n}</td>
          <td class="s-${b.state}">${b.state}</td>
          <td>${b.calls}</td>
          <td style="color:${b.failures > 0 ? '#f85149' : '#3fb950'}">${b.failures}</td>
        </tr>`).join('');
      document.getElementById('components-tbody').innerHTML = Object.entries(h.components || {}).map(([n, c]) => `
        <tr>
          <td>${n}</td>
          <td style="color:${c.state==='running'?'#3fb950':'#f85149'}">${c.state}</td>
          <td>${c.restarts}</td>
        </tr>`).join('');
      if (h.vector_db) {
        document.getElementById('vmem-stats').innerHTML =
          `memories: <b>${h.vector_db.memories}</b> &nbsp;|&nbsp; ` +
          `decisions: <b>${h.vector_db.decisions}</b> &nbsp;|&nbsp; ` +
          `proposals: <b>${h.vector_db.proposals}</b>`;
      }
    }
  }

  document.getElementById('last-refresh').textContent =
    'Обновлено: ' + new Date().toLocaleTimeString();
}

refresh();
setInterval(refresh, 3000);
</script>
</body>
</html>
"""
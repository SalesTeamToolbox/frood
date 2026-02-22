/* Agent42 Dashboard — Single-page Application */
"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  token: localStorage.getItem("agent42_token") || "",
  setupNeeded: null,  // null = checking, true = show wizard, false = show login/app
  setupStep: 1,       // 1 = password, 2 = API key, 3 = done
  page: "tasks",
  tasks: [],
  approvals: [],
  selectedTask: null,
  wsConnected: false,
  settingsTab: "providers",
  tools: [],
  skills: [],
  channels: [],
  providers: {},
  health: {},
  // Mission Control state
  viewMode: "kanban", // "kanban" or "list"
  activityFeed: [],
  activityOpen: false,
  filterPriority: "",
  filterType: "",
  status: {},
  // API key management
  apiKeys: {},
  keyEdits: {},
  keySaving: false,
};

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
const API = "/api";

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (res.status === 401) {
    state.token = "";
    localStorage.removeItem("agent42_token");
    render();
    return null;
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Setup wizard
// ---------------------------------------------------------------------------
async function checkSetup() {
  try {
    const res = await fetch(`${API}/setup/status`);
    if (res.ok) {
      const data = await res.json();
      state.setupNeeded = data.setup_needed;
    } else {
      state.setupNeeded = false;
    }
  } catch {
    state.setupNeeded = false;
  }
}

let _setupPassword = "";

function handleSetupStep1() {
  const pass = document.getElementById("setup-pass")?.value || "";
  const confirm = document.getElementById("setup-pass-confirm")?.value || "";
  const errEl = document.getElementById("setup-error");
  if (errEl) errEl.textContent = "";

  if (pass.length < 8) {
    if (errEl) errEl.textContent = "Password must be at least 8 characters.";
    return;
  }
  if (pass !== confirm) {
    if (errEl) errEl.textContent = "Passwords do not match.";
    return;
  }
  _setupPassword = pass;
  state.setupStep = 2;
  render();
}

async function handleSetupStep2(skip) {
  const apiKey = skip ? "" : (document.getElementById("setup-apikey")?.value?.trim() || "");
  const btn = document.getElementById("setup-finish-btn");
  const errEl = document.getElementById("setup-error");
  if (errEl) errEl.textContent = "";
  if (btn) { btn.disabled = true; btn.textContent = "Setting up\u2026"; }

  try {
    const res = await fetch(`${API}/setup/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password: _setupPassword, openrouter_api_key: apiKey }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Setup failed");
    }
    const data = await res.json();
    _setupPassword = "";
    state.token = data.token;
    localStorage.setItem("agent42_token", data.token);
    state.setupStep = 3;
    render();
    // After brief success message, transition to the app
    setTimeout(async () => {
      state.setupNeeded = false;
      state.setupStep = 1;
      connectWS();
      await loadAll();
      render();
      toast("Welcome to Agent42!", "success");
    }, 2000);
  } catch (err) {
    _setupPassword = "";
    if (errEl) errEl.textContent = err.message;
    if (btn) { btn.disabled = false; btn.textContent = "Finish Setup"; }
  }
}

function renderSetupWizard() {
  const root = document.getElementById("app");
  const s = state.setupStep;
  const stepDot = (num) => {
    const cls = s > num ? "active" : s === num ? "active current" : "";
    return `<div class="setup-step ${cls}"><div class="step-number">${num}</div><div class="step-label">${["Password","API Key","Done"][num-1]}</div></div>`;
  };
  const line = (num) => `<div class="setup-step-line ${s > num ? 'active' : ''}"></div>`;
  const steps = `<div class="setup-steps">${stepDot(1)}${line(1)}${stepDot(2)}${line(2)}${stepDot(3)}</div>`;

  let body = "";
  if (s === 1) {
    body = `
      <h2>Welcome to Agent<span style="color:var(--accent)">42</span></h2>
      <p class="setup-subtitle">The answer to life, the universe, and all your tasks.</p>
      <p class="setup-desc">Let's secure your dashboard with a password.</p>
      ${steps}
      <div id="setup-error" style="color:var(--danger);font-size:0.85rem;min-height:1.2em;margin-bottom:0.25rem"></div>
      <form onsubmit="event.preventDefault();handleSetupStep1()">
        <div class="form-group">
          <label for="setup-pass">Dashboard Password</label>
          <input type="password" id="setup-pass" placeholder="At least 8 characters" autofocus autocomplete="new-password">
        </div>
        <div class="form-group">
          <label for="setup-pass-confirm">Confirm Password</label>
          <input type="password" id="setup-pass-confirm" placeholder="Re-enter password" autocomplete="new-password">
        </div>
        <button type="submit" class="btn btn-primary btn-full" style="margin-top:0.5rem">Next</button>
      </form>`;
  } else if (s === 2) {
    body = `
      <h2>API Key <span style="color:var(--text-muted);font-weight:400;font-size:0.9rem">(optional)</span></h2>
      <p class="setup-desc">Agent42 uses OpenRouter for LLM access. Free models work without a key, but adding one unlocks 200+ models.</p>
      ${steps}
      <div id="setup-error" style="color:var(--danger);font-size:0.85rem;min-height:1.2em;margin-bottom:0.25rem"></div>
      <div class="form-group">
        <label for="setup-apikey">OpenRouter API Key</label>
        <input type="password" id="setup-apikey" placeholder="sk-or-... (optional)" autocomplete="off">
        <div style="font-size:0.78rem;color:var(--text-muted);margin-top:0.25rem">Get a free key at <a href="https://openrouter.ai/keys" target="_blank" rel="noopener">openrouter.ai/keys</a></div>
      </div>
      <div style="display:flex;gap:0.5rem;margin-top:1rem">
        <button class="btn btn-outline" style="flex:1" onclick="handleSetupStep2(true)">Skip for Now</button>
        <button id="setup-finish-btn" class="btn btn-primary" style="flex:1" onclick="handleSetupStep2(false)">Finish Setup</button>
      </div>`;
  } else {
    body = `
      ${steps}
      <div style="text-align:center;padding:2rem 0">
        <div style="font-size:3rem;margin-bottom:0.75rem">&#9989;</div>
        <h2>You're All Set!</h2>
        <p class="setup-desc" style="margin-bottom:0">Dashboard secured. Loading Mission Control\u2026</p>
      </div>`;
  }
  root.innerHTML = `<div class="login-page"><div class="login-card setup-wizard">${body}</div></div>`;
}

// ---------------------------------------------------------------------------
// Toast notifications
// ---------------------------------------------------------------------------
function toast(message, type = "info") {
  const container = document.getElementById("toasts");
  const el = document.createElement("div");
  el.className = `toast toast-${type}`;
  el.textContent = message;
  container.appendChild(el);
  setTimeout(() => el.remove(), 4000);
}

// ---------------------------------------------------------------------------
// WebSocket
// ---------------------------------------------------------------------------
let ws = null;
let wsRetries = 0;

function connectWS() {
  if (!state.token) return;
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  ws = new WebSocket(`${proto}//${location.host}/ws?token=${state.token}`);

  ws.onopen = () => {
    state.wsConnected = true;
    wsRetries = 0;
    updateWSIndicator();
  };

  ws.onmessage = (e) => {
    try {
      const msg = JSON.parse(e.data);
      handleWSMessage(msg);
    } catch {}
  };

  ws.onclose = () => {
    state.wsConnected = false;
    updateWSIndicator();
    // Reconnect with backoff
    if (state.token && wsRetries < 10) {
      const delay = Math.min(1000 * Math.pow(2, wsRetries), 30000);
      wsRetries++;
      setTimeout(connectWS, delay);
    }
  };
}

function handleWSMessage(msg) {
  if (msg.type === "task_update") {
    const idx = state.tasks.findIndex((t) => t.id === msg.data.id);
    if (idx >= 0) state.tasks[idx] = msg.data;
    else state.tasks.unshift(msg.data);
    if (state.page === "tasks") renderTasks();
    if (state.page === "detail" && state.selectedTask?.id === msg.data.id) {
      state.selectedTask = msg.data;
      renderDetail();
    }
    // Update stats
    renderStats();
  } else if (msg.type === "system_health") {
    state.status = msg.data;
    if (state.page === "status") renderStatus();
  } else if (msg.type === "agent_stall") {
    toast(`Agent stalled: ${msg.data.task_id}`, "error");
  }
}

function updateWSIndicator() {
  const dot = document.getElementById("ws-dot");
  const label = document.getElementById("ws-label");
  if (dot) {
    dot.className = `ws-dot ${state.wsConnected ? "connected" : "disconnected"}`;
  }
  if (label) {
    label.textContent = state.wsConnected ? "Connected" : "Disconnected";
  }
}

// ---------------------------------------------------------------------------
// Data loading
// ---------------------------------------------------------------------------
async function loadTasks() {
  try {
    state.tasks = (await api("/tasks")) || [];
  } catch { state.tasks = []; }
}

async function loadApprovals() {
  try {
    state.approvals = (await api("/approvals")) || [];
  } catch { state.approvals = []; }
}

async function loadTools() {
  try {
    state.tools = (await api("/tools")) || [];
  } catch { state.tools = []; }
}

async function loadSkills() {
  try {
    state.skills = (await api("/skills")) || [];
  } catch { state.skills = []; }
}

async function loadChannels() {
  try {
    state.channels = (await api("/channels")) || [];
  } catch { state.channels = []; }
}

async function loadProviders() {
  try {
    state.providers = (await api("/providers")) || {};
  } catch { state.providers = {}; }
}

async function loadHealth() {
  try {
    state.health = (await api("/health")) || {};
  } catch { state.health = {}; }
}

async function loadStatus() {
  try {
    state.status = (await api("/status")) || {};
  } catch { state.status = {}; }
}

async function loadApiKeys() {
  try {
    state.apiKeys = (await api("/settings/keys")) || {};
  } catch { state.apiKeys = {}; }
}

async function saveApiKeys() {
  state.keySaving = true;
  renderSettingsPanel();
  try {
    const keys = {};
    for (const [envVar, value] of Object.entries(state.keyEdits)) {
      if (value !== undefined) keys[envVar] = value;
    }
    await api("/settings/keys", {
      method: "PUT",
      body: JSON.stringify({ keys }),
    });
    state.keyEdits = {};
    await loadApiKeys();
    toast("API keys saved successfully", "success");
  } catch (e) {
    toast("Failed to save: " + e.message, "error");
  }
  state.keySaving = false;
  renderSettingsPanel();
}

// ---------------------------------------------------------------------------
// Actions
// ---------------------------------------------------------------------------
async function doLogin(username, password) {
  const errEl = document.getElementById("login-error");
  const btn = document.querySelector('.login-card button[type="submit"]');
  if (errEl) errEl.textContent = "";
  if (btn) { btn.disabled = true; btn.textContent = "Signing in\u2026"; }
  try {
    const res = await fetch(`${API}/login`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Login failed");
    }
    const data = await res.json();
    state.token = data.token;
    localStorage.setItem("agent42_token", data.token);
    connectWS();
    await loadAll();
    render();
    toast("Logged in successfully", "success");
  } catch (err) {
    if (errEl) errEl.textContent = err.message;
    toast(err.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Sign In"; }
  }
}

function doLogout() {
  state.token = "";
  localStorage.removeItem("agent42_token");
  if (ws) ws.close();
  render();
}

async function doCreateTask(title, description, taskType) {
  try {
    await api("/tasks", {
      method: "POST",
      body: JSON.stringify({ title, description, task_type: taskType }),
    });
    await loadTasks();
    renderTasks();
    closeModal();
    toast("Task created", "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function doApproveTask(taskId) {
  try {
    await api(`/tasks/${taskId}/approve`, { method: "POST" });
    await loadTasks();
    toast("Task approved", "success");
    if (state.page === "tasks") renderTasks();
    if (state.page === "detail") {
      state.selectedTask = state.tasks.find((t) => t.id === taskId);
      renderDetail();
    }
  } catch (err) { toast(err.message, "error"); }
}

async function doCancelTask(taskId) {
  try {
    await api(`/tasks/${taskId}/cancel`, { method: "POST" });
    await loadTasks();
    toast("Task cancelled", "success");
    if (state.page === "tasks") renderTasks();
    if (state.page === "detail") {
      state.selectedTask = state.tasks.find((t) => t.id === taskId);
      renderDetail();
    }
  } catch (err) { toast(err.message, "error"); }
}

async function doRetryTask(taskId) {
  try {
    await api(`/tasks/${taskId}/retry`, { method: "POST" });
    await loadTasks();
    toast("Task retried", "success");
    if (state.page === "tasks") renderTasks();
  } catch (err) { toast(err.message, "error"); }
}

async function doSubmitReview(taskId, feedback, approved) {
  try {
    await api(`/tasks/${taskId}/review`, {
      method: "POST",
      body: JSON.stringify({ feedback, approved }),
    });
    await loadTasks();
    closeModal();
    toast(approved ? "Approved with feedback" : "Feedback submitted", "success");
    if (state.page === "detail") {
      state.selectedTask = state.tasks.find((t) => t.id === taskId);
      renderDetail();
    }
  } catch (err) { toast(err.message, "error"); }
}

// -- Mission Control actions --
async function doMoveTask(taskId, newStatus, position = 0) {
  try {
    await api(`/tasks/${taskId}/move`, {
      method: "PATCH",
      body: JSON.stringify({ status: newStatus, position }),
    });
    await loadTasks();
    if (state.page === "tasks") renderTasks();
    toast(`Task moved to ${newStatus}`, "success");
  } catch (err) { toast(err.message, "error"); }
}

async function doAddComment(taskId, text) {
  try {
    await api(`/tasks/${taskId}/comment`, {
      method: "POST",
      body: JSON.stringify({ text, author: "admin" }),
    });
    await loadTasks();
    if (state.selectedTask?.id === taskId) {
      state.selectedTask = state.tasks.find((t) => t.id === taskId);
      renderDetail();
    }
    toast("Comment added", "success");
  } catch (err) { toast(err.message, "error"); }
}

async function doSetPriority(taskId, priority) {
  try {
    await api(`/tasks/${taskId}/priority`, {
      method: "PATCH",
      body: JSON.stringify({ priority }),
    });
    await loadTasks();
    if (state.page === "tasks") renderTasks();
  } catch (err) { toast(err.message, "error"); }
}

async function doBlockTask(taskId, reason) {
  try {
    await api(`/tasks/${taskId}/block`, {
      method: "PATCH",
      body: JSON.stringify({ reason }),
    });
    await loadTasks();
    if (state.page === "tasks") renderTasks();
    toast("Task blocked", "info");
  } catch (err) { toast(err.message, "error"); }
}

async function doUnblockTask(taskId) {
  try {
    await api(`/tasks/${taskId}/unblock`, { method: "PATCH" });
    await loadTasks();
    if (state.page === "tasks") renderTasks();
    toast("Task unblocked", "success");
  } catch (err) { toast(err.message, "error"); }
}

async function doArchiveTask(taskId) {
  try {
    await api(`/tasks/${taskId}/archive`, { method: "POST" });
    await loadTasks();
    if (state.page === "tasks") renderTasks();
    toast("Task archived", "info");
  } catch (err) { toast(err.message, "error"); }
}

async function loadActivity() {
  try {
    state.activityFeed = (await api("/activity")) || [];
  } catch { state.activityFeed = []; }
}

async function doHandleApproval(taskId, action, approved) {
  try {
    await api("/approvals", {
      method: "POST",
      body: JSON.stringify({ task_id: taskId, action, approved }),
    });
    await loadApprovals();
    renderApprovals();
    toast(approved ? "Approved" : "Denied", approved ? "success" : "info");
  } catch (err) { toast(err.message, "error"); }
}

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function navigate(page, data) {
  state.page = page;
  if (data) {
    if (page === "detail") state.selectedTask = data;
    if (page === "settings" && data.tab) state.settingsTab = data.tab;
  }
  render();
  // Update active nav
  document.querySelectorAll(".sidebar-nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.page === page);
  });
}

// ---------------------------------------------------------------------------
// Modals
// ---------------------------------------------------------------------------
function showModal(html) {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.id = "modal-overlay";
  overlay.innerHTML = html;
  overlay.addEventListener("click", (e) => {
    if (e.target === overlay) closeModal();
  });
  document.body.appendChild(overlay);
}

function closeModal() {
  const el = document.getElementById("modal-overlay");
  if (el) el.remove();
}

function showCreateTaskModal() {
  const types = [
    "coding","debugging","research","refactoring","documentation",
    "marketing","email","design","content","strategy","data_analysis","project_management"
  ];
  showModal(`
    <div class="modal">
      <div class="modal-header"><h3>Create Task</h3>
        <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="ct-title">Title</label>
          <input type="text" id="ct-title" placeholder="Brief task description">
        </div>
        <div class="form-group">
          <label for="ct-desc">Description</label>
          <textarea id="ct-desc" rows="4" placeholder="Detailed instructions for the agent..."></textarea>
        </div>
        <div class="form-group">
          <label for="ct-type">Task Type</label>
          <select id="ct-type">
            ${types.map((t) => `<option value="${t}">${t.replace("_", " ")}</option>`).join("")}
          </select>
          <div class="help">The task type determines which model, critic, and skills are used.</div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitCreateTask()">Create</button>
      </div>
    </div>
  `);
  document.getElementById("ct-title")?.focus();
}

function submitCreateTask() {
  const title = document.getElementById("ct-title")?.value?.trim();
  const desc = document.getElementById("ct-desc")?.value?.trim();
  const type = document.getElementById("ct-type")?.value;
  if (!title) return toast("Title is required", "error");
  if (!desc) return toast("Description is required", "error");
  doCreateTask(title, desc, type);
}

function showReviewModal(task) {
  showModal(`
    <div class="modal">
      <div class="modal-header"><h3>Review: ${esc(task.title)}</h3>
        <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="rv-feedback">Feedback</label>
          <textarea id="rv-feedback" rows="4" placeholder="Your feedback on the agent's output..."></textarea>
          <div class="help">This feedback helps the agent learn and improve.</div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button class="btn btn-danger" onclick="submitReview('${task.id}', false)">Request Changes</button>
        <button class="btn btn-success" onclick="submitReview('${task.id}', true)">Approve</button>
      </div>
    </div>
  `);
}

function submitReview(taskId, approved) {
  const feedback = document.getElementById("rv-feedback")?.value?.trim() || "";
  doSubmitReview(taskId, feedback, approved);
}

// ---------------------------------------------------------------------------
// Rendering helpers
// ---------------------------------------------------------------------------
function esc(str) {
  if (!str) return "";
  const d = document.createElement("div");
  d.textContent = str;
  return d.innerHTML;
}

function statusBadge(status) {
  return `<span class="badge-status badge-${status}">${status}</span>`;
}

function timeSince(ts) {
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ---------------------------------------------------------------------------
// Page renderers
// ---------------------------------------------------------------------------

function renderStats() {
  const el = document.getElementById("stats-row");
  if (!el) return;
  const counts = { pending: 0, assigned: 0, running: 0, review: 0, blocked: 0, done: 0, failed: 0, archived: 0 };
  state.tasks.forEach((t) => { if (counts[t.status] !== undefined) counts[t.status]++; });
  const active = counts.pending + counts.assigned + counts.running + counts.review + counts.blocked;
  el.innerHTML = `
    <div class="stat-card"><div class="stat-label">Total</div><div class="stat-value">${state.tasks.length}</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value text-info">${active}</div></div>
    <div class="stat-card"><div class="stat-label">In Progress</div><div class="stat-value text-warning">${counts.running}</div></div>
    <div class="stat-card"><div class="stat-label">Review</div><div class="stat-value" style="color:var(--accent)">${counts.review}</div></div>
    <div class="stat-card"><div class="stat-label">Blocked</div><div class="stat-value text-danger">${counts.blocked}</div></div>
    <div class="stat-card"><div class="stat-label">Done</div><div class="stat-value text-success">${counts.done}</div></div>
  `;
}

function renderTasks() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "tasks") return;

  el.innerHTML = `
    <div id="stats-row" class="stats-row"></div>
    <div class="kanban-controls">
      <div class="view-toggle">
        <button class="${state.viewMode === 'kanban' ? 'active' : ''}" onclick="state.viewMode='kanban';renderTasks()">Board</button>
        <button class="${state.viewMode === 'list' ? 'active' : ''}" onclick="state.viewMode='list';renderTasks()">List</button>
      </div>
      <div class="filter-bar">
        <select onchange="state.filterPriority=this.value;renderTasks()">
          <option value="">All Priorities</option>
          <option value="2" ${state.filterPriority==="2"?"selected":""}>Urgent</option>
          <option value="1" ${state.filterPriority==="1"?"selected":""}>High</option>
          <option value="0" ${state.filterPriority==="0"?"selected":""}>Normal</option>
        </select>
        <select onchange="state.filterType=this.value;renderTasks()">
          <option value="">All Types</option>
          ${["coding","debugging","research","refactoring","documentation","marketing","email","design","content","strategy","data_analysis","project_management"].map(t=>`<option value="${t}" ${state.filterType===t?"selected":""}>${t.replace("_"," ")}</option>`).join("")}
        </select>
      </div>
      <button class="btn btn-primary btn-sm" onclick="showCreateTaskModal()">+ New Task</button>
      <button class="btn btn-outline btn-sm" onclick="state.activityOpen=!state.activityOpen;renderActivitySidebar()">Activity</button>
    </div>
    <div id="board-area"></div>
  `;
  renderStats();
  if (state.viewMode === "kanban") renderKanbanBoard();
  else renderListView();
}

function getFilteredTasks() {
  return state.tasks.filter(t => {
    if (state.filterPriority !== "" && String(t.priority || 0) !== state.filterPriority) return false;
    if (state.filterType && t.task_type !== state.filterType) return false;
    return true;
  });
}

function renderKanbanBoard() {
  const area = document.getElementById("board-area");
  if (!area) return;
  const columns = [
    { key: "pending", label: "Inbox" },
    { key: "assigned", label: "Assigned" },
    { key: "running", label: "In Progress" },
    { key: "review", label: "Review" },
    { key: "blocked", label: "Blocked" },
    { key: "done", label: "Done" },
    { key: "archived", label: "Archived" },
  ];
  const filtered = getFilteredTasks();
  const byStatus = {};
  columns.forEach(c => byStatus[c.key] = []);
  filtered.forEach(t => { if (byStatus[t.status]) byStatus[t.status].push(t); });

  area.innerHTML = `<div class="kanban-board">${columns.map(col => {
    const tasks = byStatus[col.key] || [];
    tasks.sort((a,b) => (a.position||0) - (b.position||0) || (b.priority||0) - (a.priority||0));
    return `
      <div class="kanban-column" data-status="${col.key}">
        <div class="kanban-column-header">
          <span>${col.label}</span>
          <span class="count">${tasks.length}</span>
        </div>
        <div class="kanban-column-body"
             ondragover="event.preventDefault();this.classList.add('drag-over')"
             ondragleave="this.classList.remove('drag-over')"
             ondrop="handleDrop(event,'${col.key}');this.classList.remove('drag-over')">
          ${tasks.map(t => `
            <div class="kanban-card" draggable="true"
                 ondragstart="event.dataTransfer.setData('text/plain','${t.id}');this.classList.add('dragging')"
                 ondragend="this.classList.remove('dragging')"
                 onclick="navigate('detail', state.tasks.find(x=>x.id==='${t.id}'))">
              <div class="card-title">${esc(t.title)}</div>
              <div class="card-meta">
                <span class="priority-dot p${t.priority||0}"></span>
                <span class="badge-type">${esc(t.task_type)}</span>
                ${t.assigned_agent ? `<span>${esc(t.assigned_agent)}</span>` : ""}
                ${(t.comments||[]).length > 0 ? `<span>${(t.comments||[]).length} comments</span>` : ""}
              </div>
            </div>
          `).join("")}
          ${tasks.length === 0 ? '<div style="color:var(--text-muted);font-size:0.8rem;text-align:center;padding:1rem">Drop tasks here</div>' : ""}
        </div>
      </div>
    `;
  }).join("")}</div>`;
}

function handleDrop(event, newStatus) {
  event.preventDefault();
  const taskId = event.dataTransfer.getData("text/plain");
  if (taskId) doMoveTask(taskId, newStatus);
}

function renderListView() {
  const area = document.getElementById("board-area");
  if (!area) return;
  const filtered = getFilteredTasks();

  let rows = "";
  if (filtered.length === 0) {
    rows = `<tr><td colspan="7"><div class="empty-state"><div class="empty-icon">&#128203;</div><h3>No tasks</h3></div></td></tr>`;
  } else {
    rows = filtered.map((t) => `
      <tr>
        <td style="font-family:var(--mono);font-size:0.8rem;color:var(--text-muted)">${esc(t.id)}</td>
        <td class="task-title" onclick="navigate('detail', state.tasks.find(x=>x.id==='${t.id}'))">
          <span class="priority-dot p${t.priority||0}"></span> ${esc(t.title)}
        </td>
        <td>${statusBadge(t.status)}</td>
        <td><span class="badge-type">${esc(t.task_type)}</span></td>
        <td style="color:var(--text-muted)">${esc(t.assigned_agent || '-')}</td>
        <td style="color:var(--text-muted)">${timeSince(t.created_at)}</td>
        <td>
          ${t.status === "review" ? `<button class="btn btn-sm btn-success" onclick="event.stopPropagation();doApproveTask('${t.id}')">Approve</button>` : ""}
          ${t.status === "review" ? `<button class="btn btn-sm btn-outline" onclick="event.stopPropagation();showReviewModal(state.tasks.find(x=>x.id==='${t.id}'))">Review</button>` : ""}
          ${t.status === "pending" || t.status === "running" ? `<button class="btn btn-sm btn-outline" onclick="event.stopPropagation();doCancelTask('${t.id}')">Cancel</button>` : ""}
          ${t.status === "failed" ? `<button class="btn btn-sm btn-outline" onclick="event.stopPropagation();doRetryTask('${t.id}')">Retry</button>` : ""}
          ${t.status === "done" ? `<button class="btn btn-sm btn-outline" onclick="event.stopPropagation();doArchiveTask('${t.id}')">Archive</button>` : ""}
        </td>
      </tr>
    `).join("");
  }

  area.innerHTML = `
    <div class="card">
      <div class="table-wrap">
        <table>
          <thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Type</th><th>Agent</th><th>Created</th><th>Actions</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>
      </div>
    </div>
  `;
}

function renderActivitySidebar() {
  let sidebar = document.getElementById("activity-sidebar");
  if (!sidebar) {
    sidebar = document.createElement("div");
    sidebar.id = "activity-sidebar";
    sidebar.className = "activity-sidebar";
    document.body.appendChild(sidebar);
  }
  sidebar.classList.toggle("open", state.activityOpen);
  sidebar.innerHTML = `
    <div class="activity-header">
      <span>Activity Feed</span>
      <button class="btn btn-icon btn-outline" onclick="state.activityOpen=false;renderActivitySidebar()">&times;</button>
    </div>
    <div class="activity-list">
      ${state.activityFeed.length === 0 ? '<div style="padding:1rem;color:var(--text-muted);text-align:center">No recent activity</div>' : ""}
      ${state.activityFeed.slice(-50).reverse().map(a => `
        <div class="activity-item">
          <div>${esc(a.event || a.type || "event")}: ${esc(a.title || a.task_id || "")}</div>
          <div class="activity-time">${a.timestamp ? timeSince(a.timestamp) : ""}</div>
        </div>
      `).join("")}
    </div>
  `;
}

function renderDetail() {
  const el = document.getElementById("page-content");
  if (!el) return;
  const t = state.selectedTask;
  if (!t) { navigate("tasks"); return; }

  const result = t.result || t.error || "(no output yet)";
  const isReview = t.status === "review";

  el.innerHTML = `
    <div style="margin-bottom:1rem">
      <button class="btn btn-outline btn-sm" onclick="navigate('tasks')">&larr; Back to Tasks</button>
    </div>
    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-header">
        <h3>${esc(t.title)}</h3>
        <div style="display:flex;gap:0.5rem">
          ${isReview ? `<button class="btn btn-success btn-sm" onclick="doApproveTask('${t.id}')">Approve</button>` : ""}
          ${isReview ? `<button class="btn btn-outline btn-sm" onclick="showReviewModal(state.selectedTask)">Review with Feedback</button>` : ""}
          ${t.status === "pending" || t.status === "running" ? `<button class="btn btn-danger btn-sm" onclick="doCancelTask('${t.id}')">Cancel</button>` : ""}
          ${t.status === "failed" ? `<button class="btn btn-outline btn-sm" onclick="doRetryTask('${t.id}')">Retry</button>` : ""}
        </div>
      </div>
      <div class="card-body">
        <div class="detail-grid">
          <div class="detail-item"><label>ID</label><div class="value" style="font-family:var(--mono)">${esc(t.id)}</div></div>
          <div class="detail-item"><label>Status</label><div class="value">${statusBadge(t.status)}</div></div>
          <div class="detail-item"><label>Type</label><div class="value"><span class="badge-type">${esc(t.task_type)}</span></div></div>
          <div class="detail-item"><label>Iterations</label><div class="value">${t.iterations || 0} / ${t.max_iterations || "?"}</div></div>
          <div class="detail-item"><label>Created</label><div class="value">${new Date(t.created_at * 1000).toLocaleString()}</div></div>
          <div class="detail-item"><label>Updated</label><div class="value">${new Date(t.updated_at * 1000).toLocaleString()}</div></div>
          ${t.origin_channel ? `<div class="detail-item"><label>Origin</label><div class="value">${esc(t.origin_channel)}</div></div>` : ""}
          ${t.worktree_path ? `<div class="detail-item"><label>Workspace</label><div class="value" style="font-family:var(--mono);font-size:0.8rem">${esc(t.worktree_path)}</div></div>` : ""}
        </div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-header"><h3>Description</h3></div>
      <div class="card-body">
        <div class="detail-result">${esc(t.description)}</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-header"><h3>${t.status === "failed" ? "Error" : "Output"}</h3></div>
      <div class="card-body">
        <div class="detail-result">${esc(result)}</div>
      </div>
    </div>

    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-header"><h3>Comments (${(t.comments||[]).length})</h3></div>
      <div class="card-body">
        <div class="comment-thread" style="max-height:200px;overflow-y:auto;margin-bottom:0.75rem">
          ${(t.comments||[]).map(c => `
            <div style="padding:0.5rem;border-bottom:1px solid var(--border)">
              <span style="font-weight:600;color:var(--accent);font-size:0.8rem">${esc(c.author)}</span>
              <span style="color:var(--text-muted);font-size:0.7rem;margin-left:0.5rem">${c.timestamp ? timeSince(c.timestamp) : ""}</span>
              <div style="margin-top:0.2rem;font-size:0.85rem">${esc(c.text)}</div>
            </div>
          `).join("") || '<div style="color:var(--text-muted);font-size:0.85rem">No comments yet</div>'}
        </div>
        <div style="display:flex;gap:0.5rem">
          <input type="text" id="comment-input" placeholder="Add a comment..." style="flex:1">
          <button class="btn btn-primary btn-sm" onclick="submitComment('${t.id}')">Post</button>
        </div>
      </div>
    </div>

    <div class="card">
      <div class="card-header"><h3>Actions</h3></div>
      <div class="card-body" style="display:flex;gap:0.5rem;flex-wrap:wrap">
        <select onchange="if(this.value)doSetPriority('${t.id}',parseInt(this.value));this.value=''" style="width:auto">
          <option value="">Set Priority...</option>
          <option value="0">Normal</option>
          <option value="1">High</option>
          <option value="2">Urgent</option>
        </select>
        ${t.status !== "blocked" ? `<button class="btn btn-outline btn-sm" onclick="promptBlock('${t.id}')">Block</button>` : ""}
        ${t.status === "blocked" ? `<button class="btn btn-outline btn-sm" onclick="doUnblockTask('${t.id}')">Unblock</button>` : ""}
        ${t.status === "done" || t.status === "failed" ? `<button class="btn btn-outline btn-sm" onclick="doArchiveTask('${t.id}')">Archive</button>` : ""}
      </div>
    </div>
  `;
}

function submitComment(taskId) {
  const input = document.getElementById("comment-input");
  if (input && input.value.trim()) {
    doAddComment(taskId, input.value.trim());
    input.value = "";
  }
}

function promptBlock(taskId) {
  const reason = prompt("Block reason:");
  if (reason) doBlockTask(taskId, reason);
}

function renderApprovals() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "approvals") return;

  let content = "";
  if (state.approvals.length === 0) {
    content = `<div class="empty-state"><div class="empty-icon">&#9989;</div><h3>No pending approvals</h3><p>Approval requests from agents will appear here.</p></div>`;
  } else {
    content = state.approvals.map((a) => `
      <div class="approval-card">
        <div class="approval-info">
          <div class="approval-action">${esc(a.action || "Unknown action")}</div>
          <div class="approval-desc">${esc(a.description || "")}</div>
          <div style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-muted)">
            Task: ${esc(a.task_id || "")}
          </div>
        </div>
        <div class="approval-btns">
          <button class="btn btn-success btn-sm" onclick="doHandleApproval('${esc(a.task_id)}','${esc(a.action)}',true)">Approve</button>
          <button class="btn btn-danger btn-sm" onclick="doHandleApproval('${esc(a.task_id)}','${esc(a.action)}',false)">Deny</button>
        </div>
      </div>
    `).join("");
  }

  el.innerHTML = `
    <div class="card">
      <div class="card-header"><h3>Pending Approvals</h3></div>
      <div class="card-body">${content}</div>
    </div>
  `;
}

function renderTools() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "tools") return;

  const rows = state.tools.map((t) => `
    <tr>
      <td style="font-weight:600">${esc(t.name)}</td>
      <td style="color:var(--text-secondary)">${esc(t.description || "")}</td>
    </tr>
  `).join("");

  el.innerHTML = `
    <div class="card">
      <div class="card-header"><h3>Registered Tools (${state.tools.length})</h3></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Description</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="2"><div class="empty-state">No tools registered</div></td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

function renderSkills() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "skills") return;

  const rows = state.skills.map((s) => `
    <tr>
      <td style="font-weight:600">${esc(s.name)}</td>
      <td style="color:var(--text-secondary)">${esc(s.description || "")}</td>
      <td>${(s.task_types || []).map((t) => `<span class="badge-type">${esc(t)}</span>`).join(" ")}</td>
      <td>${s.always_load ? '<span style="color:var(--success)">Always</span>' : ""}</td>
    </tr>
  `).join("");

  el.innerHTML = `
    <div class="card">
      <div class="card-header"><h3>Loaded Skills (${state.skills.length})</h3></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Description</th><th>Task Types</th><th>Auto-load</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="4"><div class="empty-state">No skills loaded</div></td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

function renderStatus() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "status") return;
  const s = state.status;

  // Helpers
  const fmt = (v, d = 1) => (v != null ? Number(v).toFixed(d) : "--");
  const cores = s.cpu_cores || 1;
  const effMax = s.effective_max_agents || 0;
  const cfgMax = s.configured_max_agents || 0;
  const active = s.active_agents || 0;
  const stalled = s.stalled_agents || 0;
  const memTotal = s.memory_total_mb || 0;
  const memAvail = s.memory_available_mb || 0;
  const memUsed = memTotal > 0 ? memTotal - memAvail : 0;
  const memPct = memTotal > 0 ? ((memUsed / memTotal) * 100) : 0;
  const uptime = s.uptime_seconds || 0;

  function loadBarClass(pct) {
    if (pct >= 90) return "load-crit";
    if (pct >= 70) return "load-warn";
    return "load-ok";
  }

  function formatUptime(sec) {
    const d = Math.floor(sec / 86400);
    const h = Math.floor((sec % 86400) / 3600);
    const m = Math.floor((sec % 3600) / 60);
    if (d > 0) return d + "d " + h + "h " + m + "m";
    if (h > 0) return h + "h " + m + "m";
    return m + "m";
  }

  // Agent slot visualization
  const freeSlots = Math.max(0, effMax - active - stalled);
  const restrictedSlots = Math.max(0, cfgMax - effMax);
  let slotsHtml = "";
  for (let i = 0; i < active - stalled; i++) slotsHtml += '<div class="agent-slot slot-active" title="Active agent"></div>';
  for (let i = 0; i < stalled; i++) slotsHtml += '<div class="agent-slot slot-stalled" title="Stalled agent"></div>';
  for (let i = 0; i < freeSlots; i++) slotsHtml += '<div class="agent-slot slot-free" title="Available slot"></div>';
  for (let i = 0; i < restrictedSlots; i++) slotsHtml += '<div class="agent-slot slot-restricted" title="Load-restricted slot"></div>';

  // CPU load bars
  const load1Pct = Math.min(100, ((s.cpu_load_1m || 0) / cores) * 100);
  const load5Pct = Math.min(100, ((s.cpu_load_5m || 0) / cores) * 100);
  const load15Pct = Math.min(100, ((s.cpu_load_15m || 0) / cores) * 100);

  el.innerHTML = `
    <div class="stats-row" style="margin-bottom:1.5rem">
      <div class="stat-card">
        <div class="stat-label">Active Agents</div>
        <div class="stat-value text-warning">${active} <span style="font-size:0.9rem;color:var(--text-muted)">/ ${effMax}</span></div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Effective Capacity</div>
        <div class="stat-value text-success">${effMax}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">CPU Load (1m)</div>
        <div class="stat-value ${load1Pct >= 90 ? "text-danger" : load1Pct >= 70 ? "text-warning" : "text-success"}">${fmt(s.cpu_load_1m, 2)}</div>
      </div>
      <div class="stat-card">
        <div class="stat-label">Memory</div>
        <div class="stat-value ${memPct >= 90 ? "text-danger" : memPct >= 70 ? "text-warning" : "text-info"}">${fmt(memUsed / 1024, 1)} <span style="font-size:0.9rem;color:var(--text-muted)">/ ${fmt(memTotal / 1024, 1)} GB</span></div>
      </div>
    </div>

    <div class="capacity-banner">
      <div class="capacity-number">${effMax}</div>
      <div class="capacity-detail">
        <div class="capacity-title">Dynamic Agent Capacity (configured max: ${cfgMax})</div>
        <div class="capacity-reason">${esc(s.capacity_reason || "Calculating...")}</div>
      </div>
    </div>

    <div class="status-grid">
      <div>
        <div class="card status-section">
          <div class="card-header"><h3>Agent Slots</h3></div>
          <div class="card-body">
            <div class="agent-slots">${slotsHtml || '<span style="color:var(--text-muted)">No slots configured</span>'}</div>
            <div class="slot-legend">
              <div class="slot-legend-item"><div class="slot-legend-dot" style="background:var(--warning)"></div> Active</div>
              <div class="slot-legend-item"><div class="slot-legend-dot" style="background:var(--success)"></div> Free</div>
              <div class="slot-legend-item"><div class="slot-legend-dot" style="background:var(--danger)"></div> Stalled</div>
              <div class="slot-legend-item"><div class="slot-legend-dot" style="background:var(--text-muted);opacity:0.4"></div> Load-restricted</div>
            </div>
          </div>
        </div>

        <div class="card status-section" style="margin-top:1rem">
          <div class="card-header"><h3>CPU Load</h3></div>
          <div class="card-body">
            <div class="load-bar-row">
              <div class="load-label-row"><span class="label">1 min avg</span><span class="value">${fmt(s.cpu_load_1m, 2)} / ${cores}</span></div>
              <div class="load-bar-track"><div class="load-bar-fill ${loadBarClass(load1Pct)}" style="width:${load1Pct}%"></div></div>
            </div>
            <div class="load-bar-row">
              <div class="load-label-row"><span class="label">5 min avg</span><span class="value">${fmt(s.cpu_load_5m, 2)} / ${cores}</span></div>
              <div class="load-bar-track"><div class="load-bar-fill ${loadBarClass(load5Pct)}" style="width:${load5Pct}%"></div></div>
            </div>
            <div class="load-bar-row">
              <div class="load-label-row"><span class="label">15 min avg</span><span class="value">${fmt(s.cpu_load_15m, 2)} / ${cores}</span></div>
              <div class="load-bar-track"><div class="load-bar-fill ${loadBarClass(load15Pct)}" style="width:${load15Pct}%"></div></div>
            </div>
            <div style="font-size:0.8rem;color:var(--text-muted);margin-top:0.5rem">${cores} logical core${cores !== 1 ? "s" : ""} &middot; Load per core: ${fmt(s.load_per_core, 2)}</div>
          </div>
        </div>
      </div>

      <div>
        <div class="card status-section">
          <div class="card-header"><h3>Memory</h3></div>
          <div class="card-body">
            <div class="load-bar-row">
              <div class="load-label-row"><span class="label">Used</span><span class="value">${fmt(memUsed, 0)} / ${fmt(memTotal, 0)} MB</span></div>
              <div class="load-bar-track"><div class="load-bar-fill ${loadBarClass(memPct)}" style="width:${memPct}%"></div></div>
            </div>
            <div style="margin-top:0.75rem">
              <div class="status-metric-row"><span class="metric-label">Total</span><span class="metric-value">${fmt(memTotal, 0)} MB</span></div>
              <div class="status-metric-row"><span class="metric-label">Available</span><span class="metric-value" style="color:var(--success)">${fmt(memAvail, 0)} MB</span></div>
              <div class="status-metric-row"><span class="metric-label">Used</span><span class="metric-value">${fmt(memUsed, 0)} MB</span></div>
              <div class="status-metric-row"><span class="metric-label">Process (Agent42)</span><span class="metric-value">${fmt(s.memory_mb, 1)} MB</span></div>
            </div>
          </div>
        </div>

        <div class="card status-section" style="margin-top:1rem">
          <div class="card-header"><h3>System</h3></div>
          <div class="card-body">
            <div class="status-metric-row"><span class="metric-label">Uptime</span><span class="metric-value">${formatUptime(uptime)}</span></div>
            <div class="status-metric-row"><span class="metric-label">Tools Registered</span><span class="metric-value">${s.tools_registered || 0}</span></div>
            <div class="status-metric-row"><span class="metric-label">Tasks Pending</span><span class="metric-value text-info">${s.tasks_pending || 0}</span></div>
            <div class="status-metric-row"><span class="metric-label">Tasks Completed</span><span class="metric-value text-success">${s.tasks_completed || 0}</span></div>
            <div class="status-metric-row"><span class="metric-label">Tasks Failed</span><span class="metric-value text-danger">${s.tasks_failed || 0}</span></div>
          </div>
        </div>
      </div>
    </div>
  `;
}

function renderSettings() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "settings") return;

  const tabs = [
    { id: "providers", label: "LLM Providers" },
    { id: "channels", label: "Channels" },
    { id: "security", label: "Security" },
    { id: "orchestrator", label: "Orchestrator" },
    { id: "storage", label: "Storage & Paths" },
  ];

  el.innerHTML = `
    <div class="card">
      <div class="settings-grid">
        <div class="settings-nav">
          ${tabs.map((t) => `<a href="#" data-tab="${t.id}" class="${state.settingsTab === t.id ? "active" : ""}" onclick="event.preventDefault();state.settingsTab='${t.id}';renderSettingsPanel()">${t.label}</a>`).join("")}
        </div>
        <div id="settings-panel" class="settings-panel"></div>
      </div>
    </div>
  `;
  renderSettingsPanel();
}

function renderSettingsPanel() {
  const el = document.getElementById("settings-panel");
  if (!el) return;

  // Update nav active state
  document.querySelectorAll(".settings-nav a").forEach((a) => {
    a.classList.toggle("active", a.dataset.tab === state.settingsTab);
  });

  const panels = {
    providers: () => `
      <h3>LLM Providers</h3>
      <p class="section-desc">API keys for language model providers. Agent42 uses free models by default (via OpenRouter) and falls back to premium providers when configured.</p>
      ${settingSecret("OPENROUTER_API_KEY", "OpenRouter API Key", "Primary provider. Free models available without a key. Get one at openrouter.ai/keys.", true)}
      ${settingSecret("OPENAI_API_KEY", "OpenAI API Key", "Required for DALL-E image generation and GPT models. Get one at platform.openai.com.")}
      ${settingSecret("ANTHROPIC_API_KEY", "Anthropic API Key", "For Claude models. Get one at console.anthropic.com.")}
      ${settingSecret("DEEPSEEK_API_KEY", "DeepSeek API Key", "For DeepSeek Coder models. Get one at platform.deepseek.com.")}
      ${settingSecret("GEMINI_API_KEY", "Gemini API Key", "For Google Gemini models. Get one at aistudio.google.com.")}
      ${settingSecret("REPLICATE_API_TOKEN", "Replicate API Token", "For FLUX image generation and CogVideoX video. Get one at replicate.com.")}
      ${settingSecret("LUMA_API_KEY", "Luma AI API Key", "For Luma Ray2 premium video generation.")}
      ${settingSecret("BRAVE_API_KEY", "Brave Search API Key", "For web search tool. Get one at brave.com/search/api.")}
      <div class="form-group" style="margin-top:1.5rem">
        <button class="btn btn-primary" id="save-keys-btn" onclick="saveApiKeys()" ${Object.keys(state.keyEdits).length === 0 || state.keySaving ? "disabled" : ""}>
          ${state.keySaving ? "Saving..." : "Save API Keys"}
        </button>
        <div class="help" style="margin-top:0.5rem">Keys saved here override <code>.env</code> values and take effect immediately for new API calls.</div>
      </div>
    `,
    channels: () => `
      <h3>Communication Channels</h3>
      <p class="section-desc">Configure channels for receiving tasks via chat. Each channel requires its own API credentials.</p>

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Discord</h4>
      ${settingSecret("DISCORD_BOT_TOKEN", "Bot Token", "Create a bot at discord.com/developers/applications.")}
      ${settingReadonly("DISCORD_GUILD_IDS", "Guild IDs", "Comma-separated server IDs the bot should respond in.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Slack</h4>
      ${settingSecret("SLACK_BOT_TOKEN", "Bot Token", "xoxb-... token from api.slack.com/apps.")}
      ${settingSecret("SLACK_APP_TOKEN", "App Token", "xapp-... token for Socket Mode.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Telegram</h4>
      ${settingSecret("TELEGRAM_BOT_TOKEN", "Bot Token", "Get one from @BotFather on Telegram.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Email (IMAP/SMTP)</h4>
      ${settingReadonly("EMAIL_IMAP_HOST", "IMAP Host", "e.g., imap.gmail.com")}
      ${settingReadonly("EMAIL_IMAP_PORT", "IMAP Port", "Usually 993 for SSL")}
      ${settingSecret("EMAIL_IMAP_USER", "IMAP Username", "")}
      ${settingSecret("EMAIL_IMAP_PASSWORD", "IMAP Password", "")}
      ${settingReadonly("EMAIL_SMTP_HOST", "SMTP Host", "e.g., smtp.gmail.com")}
      ${settingReadonly("EMAIL_SMTP_PORT", "SMTP Port", "Usually 587 for TLS")}
      <div class="form-group" style="margin-top:1rem">
        <div class="help">Active channels: ${state.channels.length > 0 ? state.channels.map((c) => `<strong>${esc(c.type || c.name || c)}</strong>`).join(", ") : "<em>None configured</em>"}</div>
      </div>
    `,
    security: () => `
      <h3>Security</h3>
      <p class="section-desc">Authentication, rate limiting, and sandbox settings for the dashboard and agent execution.</p>

      <h4 style="margin:1rem 0 0.75rem;font-size:0.95rem">Dashboard Authentication</h4>
      ${settingReadonly("DASHBOARD_USERNAME", "Username", "Default: admin")}
      ${settingSecret("DASHBOARD_PASSWORD_HASH", "Password Hash (bcrypt)", 'Generate: python -c "from passlib.context import CryptContext; print(CryptContext([\'bcrypt\']).hash(\'yourpassword\'))"')}
      <div class="form-group">
        <div class="help" style="color:var(--warning)">Use DASHBOARD_PASSWORD_HASH (bcrypt) in production. DASHBOARD_PASSWORD (plaintext) is for development only.</div>
      </div>

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Rate Limiting</h4>
      ${settingReadonly("LOGIN_RATE_LIMIT", "Login attempts / minute / IP", "Default: 5. Protects against brute-force attacks.")}
      ${settingReadonly("MAX_WEBSOCKET_CONNECTIONS", "Max WebSocket connections", "Default: 50. Prevents connection flooding.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Execution Sandbox</h4>
      ${settingReadonly("SANDBOX_ENABLED", "Sandbox enabled", "Default: true. Restricts file/shell access to the workspace directory.")}
      ${settingReadonly("WORKSPACE_RESTRICT", "Workspace restriction", "Default: true. Blocks path traversal and access outside the repo.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">CORS &amp; Network</h4>
      ${settingReadonly("CORS_ALLOWED_ORIGINS", "Allowed origins", "Comma-separated. Empty = same-origin only (most secure).")}
      ${settingReadonly("DASHBOARD_HOST", "Dashboard bind address", "Default: 127.0.0.1 (localhost only). Use 0.0.0.0 for remote access behind a reverse proxy.")}
    `,
    orchestrator: () => `
      <h3>Orchestrator</h3>
      <p class="section-desc">Controls how Agent42 processes tasks, including concurrency limits and spending controls.</p>

      ${settingReadonly("MAX_CONCURRENT_AGENTS", "Max concurrent agents", "Default: 3. How many agents can run simultaneously. Higher values use more memory and API calls.")}
      ${settingReadonly("MAX_DAILY_API_SPEND_USD", "Daily API spend limit (USD)", "Default: 0 (unlimited). Set a positive value to cap daily spending across all providers.")}
      ${settingReadonly("DEFAULT_REPO_PATH", "Repository path", "The project directory agents work in.")}
      ${settingReadonly("TASKS_JSON_PATH", "Tasks file path", "Default: tasks.json. Persisted task queue file.")}
      ${settingReadonly("MCP_SERVERS_JSON", "MCP servers config", "Path to JSON file defining MCP server connections.")}
      ${settingReadonly("CRON_JOBS_PATH", "Cron jobs file", "Default: cron_jobs.json. Scheduled task definitions.")}
    `,
    storage: () => `
      <h3>Storage &amp; Paths</h3>
      <p class="section-desc">Directories where Agent42 stores memory, outputs, templates, and generated media.</p>

      ${settingReadonly("MEMORY_DIR", "Memory directory", "Default: .agent42/memory. Persistent memory and learning data.")}
      ${settingReadonly("SESSIONS_DIR", "Sessions directory", "Default: .agent42/sessions. Channel conversation history.")}
      ${settingReadonly("OUTPUTS_DIR", "Outputs directory", "Default: .agent42/outputs. Non-code task outputs (reports, analysis, etc.).")}
      ${settingReadonly("TEMPLATES_DIR", "Templates directory", "Default: .agent42/templates. Content templates for reuse.")}
      ${settingReadonly("IMAGES_DIR", "Images directory", "Default: .agent42/images. Generated images from image_gen tool.")}
      ${settingReadonly("SKILLS_DIRS", "Extra skill directories", "Comma-separated paths. Skills are auto-discovered from these + builtins.")}
    `,
  };

  el.innerHTML = (panels[state.settingsTab] || panels.providers)();
}

function settingSecret(envVar, label, help, highlight = false) {
  // Only keys returned by GET /api/settings/keys are admin-configurable.
  // Other secret fields (channel tokens, password hash) render as read-only.
  const isAdminConfigurable = envVar in state.apiKeys;

  if (!isAdminConfigurable) {
    return `
      <div class="form-group">
        <label>${esc(label)}</label>
        <input type="password" value="***" disabled style="font-family:var(--mono)">
        ${help ? `<div class="help">${help}</div>` : ""}
        <div class="secret-status not-configured">
          Set via environment variable: <code>${esc(envVar)}</code>
        </div>
      </div>
    `;
  }

  const keyInfo = state.apiKeys[envVar] || {};
  const configured = keyInfo.configured;
  const source = keyInfo.source || "none";
  const masked = keyInfo.masked_value || "";

  const hasEdit = state.keyEdits[envVar] !== undefined;
  const statusClass = configured ? "configured" : "not-configured";
  const statusText = configured
    ? (source === "admin" ? `Configured via admin UI (${esc(masked)})` : `Configured via .env (${esc(masked)})`)
    : "Not configured";

  return `
    <div class="form-group">
      <label>${esc(label)}</label>
      <div class="secret-input" style="display:flex;gap:0.5rem;align-items:center">
        <input type="password"
               placeholder="${configured ? "Enter new value to override" : "Enter API key"}"
               value="${hasEdit ? esc(state.keyEdits[envVar]) : ""}"
               oninput="state.keyEdits['${envVar}']=this.value;updateSaveBtn()"
               style="font-family:var(--mono);flex:1;${highlight ? "border-color:var(--accent)" : ""}">
        ${configured && source === "admin" ? `<button class="btn btn-sm" onclick="state.keyEdits['${envVar}']='';updateSaveBtn()" title="Clear admin-set key" style="white-space:nowrap">Clear</button>` : ""}
      </div>
      ${help ? `<div class="help">${help}</div>` : ""}
      <div class="secret-status ${statusClass}">${statusText}</div>
    </div>
  `;
}

function updateSaveBtn() {
  const btn = document.getElementById("save-keys-btn");
  if (btn) {
    const hasEdits = Object.values(state.keyEdits).some(v => v !== undefined);
    btn.disabled = !hasEdits || state.keySaving;
  }
}

function settingReadonly(envVar, label, help) {
  return `
    <div class="form-group">
      <label>${esc(label)}</label>
      <input type="text" value="(set via environment)" disabled style="font-family:var(--mono)">
      ${help ? `<div class="help">${help}</div>` : ""}
      <div class="secret-status not-configured">
        Environment variable: <code>${esc(envVar)}</code>
      </div>
    </div>
  `;
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------
async function loadAll() {
  await Promise.all([loadTasks(), loadApprovals(), loadTools(), loadSkills(), loadChannels(), loadProviders(), loadHealth(), loadActivity(), loadApiKeys()]);
  await Promise.all([loadTasks(), loadApprovals(), loadTools(), loadSkills(), loadChannels(), loadProviders(), loadHealth(), loadStatus()]);
}

function render() {
  const root = document.getElementById("app");
  // Setup wizard takes priority
  if (state.setupNeeded === true && !state.token) { renderSetupWizard(); return; }
  if (state.setupNeeded === null) { root.innerHTML = ""; return; }  // still checking
  if (!state.token) {
    root.innerHTML = `
      <div class="login-page">
        <div class="login-card">
          <h1>Agent<span style="color:var(--accent)">42</span></h1>
          <div class="subtitle">The answer to life, the universe, and all your tasks.</div>
          <form onsubmit="event.preventDefault();doLogin(document.getElementById('login-user').value,document.getElementById('login-pass').value)">
            <div id="login-error" style="color:#ef4444;font-size:0.85rem;min-height:1.2em;margin-bottom:0.25rem"></div>
            <div class="form-group">
              <label for="login-user">Username</label>
              <input type="text" id="login-user" value="admin" autocomplete="username">
            </div>
            <div class="form-group">
              <label for="login-pass">Password</label>
              <input type="password" id="login-pass" autocomplete="current-password" autofocus>
            </div>
            <button type="submit" class="btn btn-primary btn-full" style="margin-top:0.5rem">Sign In</button>
          </form>
        </div>
      </div>
    `;
    return;
  }

  const approvalBadge = state.approvals.length > 0 ? `<span class="badge">${state.approvals.length}</span>` : "";

  root.innerHTML = `
    <div class="app-layout">
      <aside class="sidebar">
        <div class="sidebar-brand">Agent<span class="num">42</span></div>
        <nav class="sidebar-nav">
          <a href="#" data-page="tasks" class="${state.page === "tasks" ? "active" : ""}" onclick="event.preventDefault();navigate('tasks')">&#127919; Mission Control</a>
          <a href="#" data-page="tasks" class="${state.page === "tasks" ? "active" : ""}" onclick="event.preventDefault();navigate('tasks')">&#128203; Tasks</a>
          <a href="#" data-page="status" class="${state.page === "status" ? "active" : ""}" onclick="event.preventDefault();navigate('status')">&#128200; Status</a>
          <a href="#" data-page="approvals" class="${state.page === "approvals" ? "active" : ""}" onclick="event.preventDefault();navigate('approvals')">&#128274; Approvals ${approvalBadge}</a>
          <a href="#" data-page="tools" class="${state.page === "tools" ? "active" : ""}" onclick="event.preventDefault();navigate('tools')">&#128295; Tools</a>
          <a href="#" data-page="skills" class="${state.page === "skills" ? "active" : ""}" onclick="event.preventDefault();navigate('skills')">&#9889; Skills</a>
          <a href="#" data-page="settings" class="${state.page === "settings" ? "active" : ""}" onclick="event.preventDefault();navigate('settings')">&#9881; Settings</a>
        </nav>
        <div class="sidebar-footer">
          <span id="ws-dot" class="ws-dot ${state.wsConnected ? "connected" : "disconnected"}"></span>
          <span id="ws-label">${state.wsConnected ? "Connected" : "Disconnected"}</span>
          <br><a href="#" onclick="event.preventDefault();doLogout()" style="font-size:0.8rem;color:var(--text-muted)">Logout</a>
        </div>
      </aside>
      <div class="main">
        <div class="topbar">
          <h2>${{ tasks: "Mission Control", approvals: "Approvals", tools: "Tools", skills: "Skills", settings: "Settings", detail: "Task Detail" }[state.page] || "Dashboard"}</h2>
          <h2>${{ tasks: "Tasks", status: "Platform Status", approvals: "Approvals", tools: "Tools", skills: "Skills", settings: "Settings", detail: "Task Detail" }[state.page] || "Dashboard"}</h2>
          <div class="topbar-actions">
            ${state.page === "tasks" ? '<button class="btn btn-primary btn-sm" onclick="showCreateTaskModal()">+ New Task</button><button class="btn btn-outline btn-sm" style="margin-left:0.5rem" onclick="state.activityOpen=!state.activityOpen;renderActivitySidebar()">Activity</button>' : ""}
          </div>
        </div>
        <div class="content" id="page-content"></div>
      </div>
    </div>
  `;

  // Render page content
  const renderers = {
    tasks: renderTasks,
    status: renderStatus,
    approvals: renderApprovals,
    tools: renderTools,
    skills: renderSkills,
    settings: renderSettings,
    detail: renderDetail,
  };
  (renderers[state.page] || renderTasks)();
}

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
document.addEventListener("DOMContentLoaded", async () => {
  await checkSetup();
  if (!state.setupNeeded && state.token) {
    await loadAll();
    connectWS();
  }
  render();
  // Auto-refresh approvals every 30s
  setInterval(async () => {
    if (state.token) {
      await loadApprovals();
      // Update badge in sidebar
      const navLinks = document.querySelectorAll('.sidebar-nav a[data-page="approvals"]');
      navLinks.forEach((a) => {
        const badge = a.querySelector(".badge");
        if (state.approvals.length > 0) {
          if (badge) badge.textContent = state.approvals.length;
          else {
            const b = document.createElement("span");
            b.className = "badge";
            b.textContent = state.approvals.length;
            a.appendChild(b);
          }
        } else if (badge) badge.remove();
      });
    }
  }, 30000);
});

/* Agent42 Dashboard — Single-page Application */
"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  token: localStorage.getItem("agent42_token") || "",
  setupNeeded: null,  // null = checking, true = show wizard, false = show login/app
  setupStep: 1,       // 1 = password, 2 = API key, 3 = memory, 4 = done
  page: "tasks",
  tasks: [],
  approvals: [],
  selectedTask: null,
  wsConnected: false,
  settingsTab: "providers",
  tokenStats: null,
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
  // Apps
  apps: [],
  appFilter: "",  // "" = all, "running", "stopped", "building", etc.
  // API key management
  apiKeys: {},
  keyEdits: {},
  keySaving: false,
  // Chat (multi-session)
  chatMessages: [],
  chatInput: "",
  chatSending: false,
  canvasOpen: false,
  canvasContent: "",
  canvasTitle: "",
  canvasLang: "",
  chatSessions: [],
  currentSessionId: "",
  currentSessionMessages: [],
  // Code page
  codeSessions: [],
  codeCurrentSessionId: "",
  codeCurrentMessages: [],
  codeSetupStep: 0,  // 0=not started, 1=mode, 2=config, 3=done
  codeSending: false,
  codeCanvasOpen: true,
  // Projects
  projects: [],
  selectedProject: null,
  missionControlTab: "tasks",  // "tasks" or "projects"
  projectViewMode: "kanban",
  // GitHub
  githubConnected: false,
  githubDeviceCode: null,
  githubPolling: false,
  // GitHub multi-account management
  githubAccounts: [],
  githubAccountsLoading: false,
  githubAccountAdding: false,
  githubAccountNewLabel: "",
  githubAccountNewToken: "",
  // Editable settings
  envSettings: {},
  envEdits: {},
  envSaving: false,
  // Storage backend status
  storageStatus: null,
  storageInstalling: false,
  // OpenRouter account status
  orStatus: null,
  orStatusLoading: false,
  // Repositories
  repos: [],
  repoBranches: {},
  githubRepos: [],
  githubLoading: false,
  // Reports
  reportsData: null,
  reportsLoading: false,
  reportsTab: "overview",
};

// ---------------------------------------------------------------------------
// Brand personality
// ---------------------------------------------------------------------------
const TAGLINES = [
  "Don\u2019t Panic.",
  "The Answer to Life, the Universe, and All Your Tasks.",
  "Mostly Harmless.",
  "Time is an illusion. Lunchtime doubly so. Deadlines triply.",
  "Now with 100% more towels than competing platforms.",
  "A Whose-Who\u2019s Guide to Getting Things Done.",
  "It\u2019s just a flesh wound.",
  "We are the knights who say\u2026 Ni!",
];

const STATUS_FLAVOR = {
  pending: "Waiting in the Infinite Improbability Queue\u2026",
  assigned: "Towel at the ready.",
  running: "An agent is on it. Towel at the ready.",
  review: "Awaiting human review.",
  blocked: "Stuck. Like a sofa in a staircase.",
  done: "The Answer has been computed.",
  failed: "Even Deep Thought had bad days.",
  cancelled: "Probably for the best \u2014 the Vogons were getting involved.",
  archived: "Filed in the Galactic Archives.",
};

function randomFrom(arr) { return arr[Math.floor(Math.random() * arr.length)]; }
function isTowelDay() { const d = new Date(); return d.getMonth() === 4 && d.getDate() === 25; }

let _taglineIdx = Math.floor(Math.random() * TAGLINES.length);
function rotateTagline() {
  const el = document.getElementById("login-tagline");
  if (!el) return;
  el.style.opacity = "0";
  setTimeout(() => {
    _taglineIdx = (_taglineIdx + 1) % TAGLINES.length;
    el.textContent = TAGLINES[_taglineIdx];
    el.style.opacity = "1";
  }, 800);
}
setInterval(rotateTagline, 8000);

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
let _setupApiKey = "";
let _setupMemory = "skip";

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

function handleSetupStep2(skip) {
  _setupApiKey = skip ? "" : (document.getElementById("setup-apikey")?.value?.trim() || "");
  state.setupStep = 3;
  render();
}

function _selectMemoryOption(choice) {
  _setupMemory = choice;
  document.querySelectorAll(".memory-option").forEach(el => {
    el.classList.toggle("selected", el.dataset.choice === choice);
  });
}

async function handleSetupStep3() {
  const btn = document.getElementById("setup-finish-btn");
  const errEl = document.getElementById("setup-error");
  if (errEl) errEl.textContent = "";
  if (btn) { btn.disabled = true; btn.textContent = "Setting up\u2026"; }

  try {
    const res = await fetch(`${API}/setup/complete`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        password: _setupPassword,
        openrouter_api_key: _setupApiKey,
        memory_backend: _setupMemory,
      }),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || "Setup failed");
    }
    const data = await res.json();
    _setupPassword = "";
    _setupApiKey = "";
    state.token = data.token;
    localStorage.setItem("agent42_token", data.token);
    state._setupResult = data;
    state.setupStep = 4;
    render();
    // After brief success message, transition to the app
    setTimeout(async () => {
      state.setupNeeded = false;
      state.setupStep = 1;
      state._setupResult = null;
      connectWS();
      await loadAll();
      render();
      if (data.setup_task_id) {
        toast("Welcome! A setup task has been queued to verify memory services.", "success");
      } else {
        toast("Welcome, hitchhiker! The Guide is ready.", "success");
      }
    }, 4000);
  } catch (err) {
    _setupPassword = "";
    _setupApiKey = "";
    if (errEl) errEl.textContent = err.message;
    if (btn) { btn.disabled = false; btn.textContent = "Finish Setup"; }
  }
}

function renderSetupWizard() {
  const root = document.getElementById("app");
  const s = state.setupStep;
  const labels = ["Password", "API Key", "Memory", "Done"];
  const stepDot = (num) => {
    const cls = s > num ? "active" : s === num ? "active current" : "";
    return `<div class="setup-step ${cls}"><div class="step-number">${num}</div><div class="step-label">${labels[num-1]}</div></div>`;
  };
  const line = (num) => `<div class="setup-step-line ${s > num ? 'active' : ''}"></div>`;
  const steps = `<div class="setup-steps">${stepDot(1)}${line(1)}${stepDot(2)}${line(2)}${stepDot(3)}${line(3)}${stepDot(4)}</div>`;

  let body = "";
  if (s === 1) {
    body = `
      <h2>Welcome to Agent<span style="color:var(--accent)">42</span></h2>
      <p class="setup-subtitle">The answer to life, the universe, and all your tasks.</p>
      <p class="setup-desc">Welcome, hoopy frood. Let\u2019s secure the Guide with a passphrase.</p>
      ${steps}
      <div id="setup-error" style="color:var(--danger);font-size:0.85rem;min-height:1.2em;margin-bottom:0.25rem"></div>
      <form onsubmit="event.preventDefault();handleSetupStep1()">
        <div class="form-group">
          <label for="setup-pass">Dashboard Password</label>
          <input type="password" id="setup-pass" placeholder="At least 8 characters (more improbable is better)" autofocus autocomplete="new-password">
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
      <p class="setup-desc">Agent42 uses OpenRouter for LLM access. Free models work without a key, but adding one unlocks 200+ models. It\u2019s like upgrading from a towel to a Sub-Etha Sens-O-Matic.</p>
      ${steps}
      <div id="setup-error" style="color:var(--danger);font-size:0.85rem;min-height:1.2em;margin-bottom:0.25rem"></div>
      <div class="form-group">
        <label for="setup-apikey">OpenRouter API Key</label>
        <input type="password" id="setup-apikey" placeholder="sk-or-... (optional)" autocomplete="off">
        <div style="font-size:0.78rem;color:var(--text-muted);margin-top:0.25rem">Get a free key at <a href="https://openrouter.ai/keys" target="_blank" rel="noopener">openrouter.ai/keys</a></div>
      </div>
      <div style="display:flex;gap:0.5rem;margin-top:1rem">
        <button class="btn btn-outline" style="flex:1" onclick="handleSetupStep2(true)">Skip for Now</button>
        <button class="btn btn-primary" style="flex:1" onclick="handleSetupStep2(false)">Next</button>
      </div>`;
  } else if (s === 3) {
    body = `
      <h2>Enhanced Memory <span style="color:var(--text-muted);font-weight:400;font-size:0.9rem">(optional)</span></h2>
      <p class="setup-desc">Add semantic search and session caching for smarter agents. Agent42 works fully without these.</p>
      ${steps}
      <div id="setup-error" style="color:var(--danger);font-size:0.85rem;min-height:1.2em;margin-bottom:0.25rem"></div>
      <div class="memory-options">
        <div class="memory-option selected" data-choice="skip" onclick="_selectMemoryOption('skip')">
          <div class="memory-option-radio"></div>
          <div class="memory-option-body">
            <div class="memory-option-title">Skip</div>
            <div class="memory-option-desc">File-based (perfectly adequate for smaller universes).</div>
          </div>
        </div>
        <div class="memory-option" data-choice="qdrant_embedded" onclick="_selectMemoryOption('qdrant_embedded')">
          <div class="memory-option-radio"></div>
          <div class="memory-option-body">
            <div class="memory-option-title">Qdrant Embedded</div>
            <div class="memory-option-desc">Vector semantic search stored locally. No Docker needed &mdash; just a pip install.</div>
            <div class="memory-option-tag">Mostly Painless</div>
          </div>
        </div>
        <div class="memory-option" data-choice="qdrant_redis" onclick="_selectMemoryOption('qdrant_redis')">
          <div class="memory-option-radio"></div>
          <div class="memory-option-body">
            <div class="memory-option-title">Qdrant + Redis</div>
            <div class="memory-option-desc">Full semantic search + fast session caching. Services may already be running if installed via install-server.sh.</div>
            <div class="memory-option-tag">Infinite Improbability Drive</div>
          </div>
        </div>
      </div>
      <div style="display:flex;gap:0.5rem;margin-top:1rem">
        <button class="btn btn-outline" style="flex:1" onclick="state.setupStep=2;render()">Back</button>
        <button id="setup-finish-btn" class="btn btn-primary" style="flex:1" onclick="handleSetupStep3()">Finish Setup</button>
      </div>`;
  } else {
    const result = state._setupResult || {};
    const mem = result.memory_backend || "skip";
    let extraMsg = "";
    if (mem === "qdrant_redis" && result.setup_task_id) {
      extraMsg = `<p class="setup-desc" style="margin-top:0.75rem;font-size:0.82rem;color:var(--text-muted)">A setup task has been queued to verify the memory services are running.</p>`;
    } else if (mem === "qdrant_embedded") {
      extraMsg = `<p class="setup-desc" style="margin-top:0.75rem;font-size:0.82rem;color:var(--text-muted)">Embedded Qdrant enabled. Run <code style="background:var(--bg-tertiary);padding:0.1em 0.3em;border-radius:3px">pip install qdrant-client</code> if not installed yet.</p>`;
    }
    body = `
      ${steps}
      <div style="text-align:center;padding:2rem 0">
        <div style="font-size:3rem;margin-bottom:0.75rem">&#9989;</div>
        <h2>Don\u2019t Panic \u2014 You\u2019re All Set!</h2>
        <p class="setup-desc" style="margin-bottom:0">You are now a hoopy frood who really knows where their towel is. Loading Mission Control\u2026</p>
        ${extraMsg}
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
    if (state.page === "tasks") renderMissionControl();
    if (state.page === "detail" && state.selectedTask?.id === msg.data.id) {
      state.selectedTask = msg.data;
      renderDetail();
    }
    // Update stats (including token usage)
    renderStats();
    loadTokenStats();
    // First task completion celebration
    if (msg.data.status === "done" && !localStorage.getItem("a42_first_done")) {
      localStorage.setItem("a42_first_done", "1");
      toast("And there was much rejoicing. (yaay)", "success");
    }
  } else if (msg.type === "system_health") {
    state.status = msg.data;
    if (state.page === "status") renderStatus();
  } else if (msg.type === "app_status") {
    // Real-time app status update
    const idx = state.apps.findIndex((a) => a.id === msg.data.id);
    if (idx >= 0) state.apps[idx] = msg.data;
    else state.apps.unshift(msg.data);
    if (state.page === "apps") renderApps();
  } else if (msg.type === "agent_stall") {
    toast(`Agent stalled on ${msg.data.task_id}. For a moment, nothing happened.`, "error");
  } else if (msg.type === "project_update") {
    const idx = state.projects.findIndex(p => p.id === msg.data.id);
    if (idx >= 0) state.projects[idx] = msg.data;
    else state.projects.unshift(msg.data);
    if (state.page === "tasks" && state.missionControlTab === "projects") renderMissionControl();
    if (state.page === "projectDetail" && state.selectedProject?.id === msg.data.id) {
      state.selectedProject = msg.data;
      renderProjectDetail();
    }
  } else if (msg.type === "chat_message") {
    const sid = msg.data.session_id || "";
    // Route to chat or code page based on session
    if (sid && sid === state.currentSessionId) {
      // Active chat session
      let needsAppend = false;
      if (msg.data.role === "user") {
        const idx = state.currentSessionMessages.findIndex(m => m.id?.startsWith("local-") && m.content === msg.data.content);
        if (idx >= 0) state.currentSessionMessages[idx] = msg.data;
        else { state.currentSessionMessages.push(msg.data); needsAppend = true; }
      } else {
        state.currentSessionMessages.push(msg.data);
        state.chatSending = false;
        needsAppend = true;
      }
      if (state.page === "chat") {
        if (needsAppend) {
          if (!appendChatMsgToDOM(msg.data, state.currentSessionMessages, false)) renderChat();
          else updateChatTypingIndicator(state.chatSending, false);
        }
      }
    } else if (sid && sid === state.codeCurrentSessionId) {
      // Active code session
      let needsAppend = false;
      if (msg.data.role === "user") {
        const idx = state.codeCurrentMessages.findIndex(m => m.id?.startsWith("local-") && m.content === msg.data.content);
        if (idx >= 0) state.codeCurrentMessages[idx] = msg.data;
        else { state.codeCurrentMessages.push(msg.data); needsAppend = true; }
      } else {
        state.codeCurrentMessages.push(msg.data);
        state.codeSending = false;
        needsAppend = true;
      }
      if (state.page === "code") {
        if (needsAppend) {
          if (!appendChatMsgToDOM(msg.data, state.codeCurrentMessages, true)) renderCode();
          else updateChatTypingIndicator(state.codeSending, true);
        }
      }
    } else if (!sid) {
      // Legacy messages without session_id (backward compat)
      let needsAppend = false;
      if (msg.data.role === "user") {
        const idx = state.chatMessages.findIndex(m => m.id?.startsWith("local-") && m.content === msg.data.content);
        if (idx >= 0) state.chatMessages[idx] = msg.data;
        else { state.chatMessages.push(msg.data); needsAppend = true; }
      } else {
        state.chatMessages.push(msg.data);
        state.chatSending = false;
        needsAppend = true;
      }
      if (state.page === "chat") {
        if (needsAppend) {
          if (!appendChatMsgToDOM(msg.data, state.chatMessages, false)) renderChat();
          else updateChatTypingIndicator(state.chatSending, false);
        }
      }
    } else {
      // Message for a non-active session — update unread badge
      const session = state.chatSessions.find(s => s.id === sid) || state.codeSessions.find(s => s.id === sid);
      if (session) session._unread = (session._unread || 0) + 1;
    }
  } else if (msg.type === "chat_thinking") {
    // Agent started/stopped processing a chat task — show/hide typing indicator
    const sid = msg.data.session_id || "";
    const thinking = msg.data.thinking;
    if (sid && sid === state.currentSessionId) {
      state.chatSending = thinking;
      if (state.page === "chat") {
        if (!updateChatTypingIndicator(thinking, false)) renderChat();
      }
    } else if (sid && sid === state.codeCurrentSessionId) {
      state.codeSending = thinking;
      if (state.page === "code") {
        if (!updateChatTypingIndicator(thinking, true)) renderCode();
      }
    } else if (!sid) {
      state.chatSending = thinking;
      if (state.page === "chat") {
        if (!updateChatTypingIndicator(thinking, false)) renderChat();
      }
    }
  }
}

function updateWSIndicator() {
  const dot = document.getElementById("ws-dot");
  const label = document.getElementById("ws-label");
  if (dot) {
    dot.className = `ws-dot ${state.wsConnected ? "connected" : "disconnected"}`;
  }
  if (label) {
    label.textContent = state.wsConnected ? "Connected to the Guide" : "Disconnected";
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

async function loadTokenStats() {
  try {
    state.tokenStats = (await api("/stats/tokens")) || null;
  } catch { state.tokenStats = null; }
}

async function loadRepos() {
  try {
    state.repos = (await api("/repos")) || [];
  } catch { state.repos = []; }
}

async function loadGithubAccounts() {
  try {
    state.githubAccounts = (await api("/github/accounts")) || [];
  } catch { state.githubAccounts = []; }
}

async function loadRepoBranches(repoId) {
  if (state.repoBranches[repoId]) return;
  try {
    const data = await api(`/repos/${repoId}/branches`);
    state.repoBranches[repoId] = data.branches || [];
  } catch { state.repoBranches[repoId] = []; }
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

async function toggleTool(name, enabled) {
  try {
    await api(`/tools/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    await loadTools();
    renderTools();
    toast(`Tool '${name}' ${enabled ? "enabled" : "disabled"}`, "success");
  } catch (e) {
    toast("Failed to update tool: " + e.message, "error");
    await loadTools();
    renderTools();
  }
}

async function toggleSkill(name, enabled) {
  try {
    await api(`/skills/${encodeURIComponent(name)}`, {
      method: "PATCH",
      body: JSON.stringify({ enabled }),
    });
    await loadSkills();
    renderSkills();
    toast(`Skill '${name}' ${enabled ? "enabled" : "disabled"}`, "success");
  } catch (e) {
    toast("Failed to update skill: " + e.message, "error");
    await loadSkills();
    renderSkills();
  }
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

async function loadApps() {
  try {
    state.apps = (await api("/apps")) || [];
  } catch { state.apps = []; }
}

async function saveApiKeys() {
  state.keySaving = true;
  renderSettingsPanel();
  try {
    const keys = {};
    for (const [envVar, value] of Object.entries(state.keyEdits)) {
      if (value !== undefined) keys[envVar] = value;
    }
    const result = await api("/settings/keys", {
      method: "PUT",
      body: JSON.stringify({ keys }),
    });
    if (result === null) return; // 401 auth error — user was redirected to login
    state.keyEdits = {};
    await loadApiKeys();
    toast("API keys saved successfully", "success");
  } catch (e) {
    toast("Failed to save: " + e.message, "error");
  }
  state.keySaving = false;
  renderSettingsPanel();
}

async function loadEnvSettings() {
  try {
    state.envSettings = (await api("/settings/env")) || {};
  } catch { state.envSettings = {}; }
}

async function loadStorageStatus() {
  try {
    state.storageStatus = (await api("/settings/storage")) || null;
  } catch { state.storageStatus = null; }
}

async function installStoragePackages() {
  state.storageInstalling = true;
  renderSettingsPanel();
  try {
    const result = await api("/settings/storage/install-packages", { method: "POST" });
    if (result.errors && result.errors.length) {
      toast("Install failed: " + result.errors.join("; "), "error");
    } else {
      toast("Packages installed. Restart Agent42 to activate the storage backend.", "success");
    }
    await loadStorageStatus();
  } catch (e) {
    toast("Install failed: " + e.message, "error");
  }
  state.storageInstalling = false;
  renderSettingsPanel();
}

async function saveEnvSettings() {
  state.envSaving = true;
  renderSettingsPanel();
  try {
    await api("/settings/env", {
      method: "PUT",
      body: JSON.stringify({ settings: state.envEdits }),
    });
    state.envEdits = {};
    await loadEnvSettings();
    toast("Settings saved. Some changes may require a restart.", "success");
  } catch (e) {
    toast("Failed to save: " + e.message, "error");
  }
  state.envSaving = false;
  renderSettingsPanel();
}

async function changePassword() {
  const errEl = document.getElementById("cp-error");
  const btn = document.getElementById("cp-btn");
  const currentPass = document.getElementById("cp-current")?.value || "";
  const newPass = document.getElementById("cp-new")?.value || "";
  const confirmPass = document.getElementById("cp-confirm")?.value || "";
  if (errEl) errEl.textContent = "";

  if (!currentPass) { if (errEl) errEl.textContent = "Current password is required."; return; }
  if (newPass.length < 8) { if (errEl) errEl.textContent = "New password must be at least 8 characters."; return; }
  if (newPass !== confirmPass) { if (errEl) errEl.textContent = "New passwords do not match."; return; }

  if (btn) { btn.disabled = true; btn.textContent = "Changing..."; }
  try {
    const data = await api("/settings/password", {
      method: "POST",
      body: JSON.stringify({ current_password: currentPass, new_password: newPass }),
    });
    if (data.token) {
      state.token = data.token;
      localStorage.setItem("agent42_token", data.token);
    }
    toast("Password changed successfully.", "success");
    if (document.getElementById("cp-current")) document.getElementById("cp-current").value = "";
    if (document.getElementById("cp-new")) document.getElementById("cp-new").value = "";
    if (document.getElementById("cp-confirm")) document.getElementById("cp-confirm").value = "";
  } catch (e) {
    if (errEl) errEl.textContent = e.message || "Failed to change password.";
    toast("Failed to change password: " + e.message, "error");
  } finally {
    if (btn) { btn.disabled = false; btn.textContent = "Change Password"; }
  }
}

async function loadChatMessages() {
  try {
    state.chatMessages = (await api("/chat/messages")) || [];
  } catch { state.chatMessages = []; }
}

// -- Chat sessions --
async function loadChatSessions() {
  try {
    state.chatSessions = (await api("/chat/sessions?type=chat")) || [];
  } catch { state.chatSessions = []; }
}

async function loadCodeSessions() {
  try {
    state.codeSessions = (await api("/chat/sessions?type=code")) || [];
  } catch { state.codeSessions = []; }
}

async function createChatSession(sessionType) {
  try {
    const session = await api("/chat/sessions", {
      method: "POST",
      body: JSON.stringify({ title: "", session_type: sessionType }),
    });
    if (sessionType === "chat") {
      state.chatSessions.unshift(session);
      await switchChatSession(session.id);
    } else {
      state.codeSessions.unshift(session);
      await switchCodeSession(session.id);
    }
    return session;
  } catch (e) {
    toast("Failed to create session: " + e.message, "error");
    return null;
  }
}

async function switchChatSession(sessionId) {
  state.currentSessionId = sessionId;
  try {
    state.currentSessionMessages = (await api(`/chat/sessions/${sessionId}/messages`)) || [];
  } catch { state.currentSessionMessages = []; }
  const session = state.chatSessions.find(s => s.id === sessionId);
  if (session) session._unread = 0;
  if (state.page === "chat") renderChat();
}

async function switchCodeSession(sessionId) {
  state.codeCurrentSessionId = sessionId;
  state.codeSetupStep = 0;
  try {
    state.codeCurrentMessages = (await api(`/chat/sessions/${sessionId}/messages`)) || [];
    const session = state.codeSessions.find(s => s.id === sessionId);
    if (session) {
      session._unread = 0;
      // Check if setup is needed
      if (session.session_type === "code" && !session.deployment_target) {
        state.codeSetupStep = 1;
      } else {
        state.codeSetupStep = 3;
      }
    }
  } catch { state.codeCurrentMessages = []; }
  if (state.page === "code") renderCode();
}

async function sendSessionMessage(sessionId, isCode) {
  const inputId = isCode ? "code-chat-input" : "chat-input";
  const input = document.getElementById(inputId);
  const text = (input?.value || "").trim();
  if (!text) return;
  if (isCode) { if (state.codeSending) return; state.codeSending = true; }
  else { if (state.chatSending) return; state.chatSending = true; }

  const messages = isCode ? state.codeCurrentMessages : state.currentSessionMessages;
  const newMsg = {
    id: "local-" + Date.now(),
    role: "user",
    content: text,
    timestamp: Date.now() / 1000,
    sender: "You",
    session_id: sessionId,
  };
  messages.push(newMsg);
  if (input) input.value = "";

  // Incremental append: only add the new message to the DOM instead of rebuilding everything
  const onCorrectPage = isCode ? state.page === "code" : state.page === "chat";
  if (onCorrectPage) {
    if (!appendChatMsgToDOM(newMsg, messages, isCode)) {
      // Container not found — fall back to full render
      if (isCode) renderCode(); else renderChat();
    } else {
      updateChatTypingIndicator(true, isCode);
    }
  }

  try {
    await api(`/chat/sessions/${sessionId}/send`, {
      method: "POST",
      body: JSON.stringify({ message: text }),
    });
    // Don't reset sending state here — the WebSocket "chat_thinking" event
    // will set it to true when the agent starts and false when it finishes.
  } catch (e) {
    toast("Failed to send: " + e.message, "error");
    // Only reset on error so the typing indicator disappears
    if (isCode) state.codeSending = false;
    else state.chatSending = false;
    if (isCode && state.page === "code") renderCode();
    else if (!isCode && state.page === "chat") renderChat();
  }
}

async function deleteChatSession(sessionId, sessionType) {
  if (!confirm("Delete this conversation?")) return;
  try {
    await api(`/chat/sessions/${sessionId}`, { method: "DELETE" });
    if (sessionType === "chat") {
      state.chatSessions = state.chatSessions.filter(s => s.id !== sessionId);
      if (state.currentSessionId === sessionId) {
        state.currentSessionId = "";
        state.currentSessionMessages = [];
      }
    } else {
      state.codeSessions = state.codeSessions.filter(s => s.id !== sessionId);
      if (state.codeCurrentSessionId === sessionId) {
        state.codeCurrentSessionId = "";
        state.codeCurrentMessages = [];
        state.codeSetupStep = 0;
      }
    }
    if (state.page === "chat") renderChat();
    if (state.page === "code") renderCode();
  } catch (e) { toast("Delete failed: " + e.message, "error"); }
}

// -- Projects --
async function loadProjects() {
  try {
    state.projects = (await api("/projects")) || [];
  } catch { state.projects = []; }
}

async function loadGitHubStatus() {
  try {
    const res = await api("/github/status");
    state.githubConnected = res?.connected || false;
  } catch { state.githubConnected = false; }
}

async function submitCodeSetup(sessionId) {
  const mode = document.querySelector('input[name="code-mode"]:checked')?.value || "local";
  const runtime = document.getElementById("code-runtime")?.value || "python";
  const appName = document.getElementById("code-app-name")?.value || "Untitled";
  const sshHost = document.getElementById("code-ssh-host")?.value || "";
  const ghRepoName = document.getElementById("code-gh-repo")?.value || "";
  const ghCloneUrl = document.getElementById("code-gh-clone-url")?.value || "";
  const ghPrivate = document.getElementById("code-gh-private")?.checked ?? true;
  const repoId = document.getElementById("code-repo-id")?.value || "";

  try {
    const result = await api(`/chat/sessions/${sessionId}/setup`, {
      method: "POST",
      body: JSON.stringify({
        mode, runtime, app_name: appName,
        ssh_host: sshHost, github_repo_name: ghRepoName,
        github_clone_url: ghCloneUrl, github_private: ghPrivate,
        repo_id: repoId,
      }),
    });
    // Update session in local state
    const idx = state.codeSessions.findIndex(s => s.id === sessionId);
    if (idx >= 0) state.codeSessions[idx] = result;
    state.codeSetupStep = 3;
    renderCode();
  } catch (e) {
    toast("Setup failed: " + e.message, "error");
  }
}

async function createProject() {
  const name = document.getElementById("project-name")?.value?.trim();
  const desc = document.getElementById("project-desc")?.value?.trim() || "";
  if (!name) { toast("Project name required", "error"); return; }
  try {
    const project = await api("/projects", {
      method: "POST",
      body: JSON.stringify({ name, description: desc }),
    });
    state.projects.unshift(project);
    closeModal();
    renderMissionControl();
    toast("Project created", "success");
  } catch (e) { toast("Failed: " + e.message, "error"); }
}

async function loadProjectTasks(projectId) {
  try {
    return (await api(`/projects/${projectId}/tasks`)) || [];
  } catch { return []; }
}

async function sendChatMessage() {
  const input = document.getElementById("chat-input");
  const text = (input?.value || "").trim();
  if (!text || state.chatSending) return;
  state.chatSending = true;
  // Optimistic: add user message immediately
  const newMsg = {
    id: "local-" + Date.now(),
    role: "user",
    content: text,
    timestamp: Date.now() / 1000,
    sender: "You",
  };
  state.chatMessages.push(newMsg);
  if (input) input.value = "";

  // Incremental append: only add the new message to the DOM instead of rebuilding everything
  if (state.page === "chat") {
    if (!appendChatMsgToDOM(newMsg, state.chatMessages, false)) {
      renderChat();
    } else {
      updateChatTypingIndicator(true, false);
    }
  }

  try {
    await api("/chat/send", {
      method: "POST",
      body: JSON.stringify({ message: text }),
    });
    // Don't reset chatSending here — the WebSocket "chat_thinking" event
    // controls the typing indicator based on actual agent processing state.
  } catch (e) {
    toast("Failed to send: " + e.message, "error");
    state.chatSending = false;
    if (state.page === "chat") renderChat();
  }
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
    toast("Don\u2019t Panic \u2014 you\u2019re in.", "success");
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

async function doCreateTask(title, description, taskType, repoId, branch) {
  try {
    const body = { title, description, task_type: taskType };
    if (repoId) body.repo_id = repoId;
    if (branch) body.branch = branch;
    await api("/tasks", {
      method: "POST",
      body: JSON.stringify(body),
    });
    await loadTasks();
    if (state.page === "tasks") renderMissionControl();
    else if (state.page === "projectDetail") renderProjectDetail();
    closeModal();
    toast("Task created. An agent has been dispatched. Don\u2019t Panic.", "success");
  } catch (err) {
    toast(err.message, "error");
  }
}

async function doApproveTask(taskId) {
  try {
    await api(`/tasks/${taskId}/approve`, { method: "POST" });
    await loadTasks();
    toast("Task approved", "success");
    if (state.page === "tasks") renderMissionControl();
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
    toast("Task cancelled. Probably for the best.", "success");
    if (state.page === "tasks") renderMissionControl();
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
    toast("Task retried. It\u2019s not dead yet!", "success");
    if (state.page === "tasks") renderMissionControl();
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
    if (state.page === "tasks") renderMissionControl();
    toast(`Task moved to ${newStatus}`, "success");
  } catch (err) { toast(err.message, "error"); }
}

async function doAddComment(taskId, text) {
  try {
    await api(`/tasks/${taskId}/comment`, {
      method: "POST",
      body: JSON.stringify({ text, author: "admin" }),
    });
    // Task update arrives via WebSocket (task_update event) which
    // refreshes state.tasks and re-renders the detail view automatically.
    // We still do a manual loadTasks() as a fallback for non-WS clients.
    await loadTasks();
    if (state.selectedTask?.id === taskId) {
      state.selectedTask = state.tasks.find((t) => t.id === taskId);
      renderDetail();
      // Auto-scroll comment thread to bottom
      const thread = document.querySelector(".comment-thread");
      if (thread) thread.scrollTop = thread.scrollHeight;
    }
    const task = state.tasks.find((t) => t.id === taskId);
    const isActive = task && ["pending", "assigned", "running"].includes(task.status);
    toast(isActive ? "Message sent to agent" : "Comment added", "success");
  } catch (err) { toast(err.message, "error"); }
}

async function doSetPriority(taskId, priority) {
  try {
    await api(`/tasks/${taskId}/priority`, {
      method: "PATCH",
      body: JSON.stringify({ priority }),
    });
    await loadTasks();
    if (state.page === "tasks") renderMissionControl();
  } catch (err) { toast(err.message, "error"); }
}

async function doBlockTask(taskId, reason) {
  try {
    await api(`/tasks/${taskId}/block`, {
      method: "PATCH",
      body: JSON.stringify({ reason }),
    });
    await loadTasks();
    if (state.page === "tasks") renderMissionControl();
    toast("Task blocked. Stuck behind a Vogon queue.", "info");
  } catch (err) { toast(err.message, "error"); }
}

async function doUnblockTask(taskId) {
  try {
    await api(`/tasks/${taskId}/unblock`, { method: "PATCH" });
    await loadTasks();
    if (state.page === "tasks") renderMissionControl();
    toast("Task unblocked. The Vogons have moved on.", "success");
  } catch (err) { toast(err.message, "error"); }
}

async function doArchiveTask(taskId) {
  try {
    await api(`/tasks/${taskId}/archive`, { method: "POST" });
    await loadTasks();
    if (state.page === "tasks") renderMissionControl();
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
// Mobile sidebar toggle
// ---------------------------------------------------------------------------
function toggleMobileSidebar() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (!sidebar) return;
  const isOpen = sidebar.classList.contains("mobile-open");
  if (isOpen) {
    closeMobileSidebar();
  } else {
    sidebar.classList.add("mobile-open");
    if (backdrop) backdrop.classList.add("visible");
  }
}

function closeMobileSidebar() {
  const sidebar = document.getElementById("sidebar");
  const backdrop = document.getElementById("sidebar-backdrop");
  if (sidebar) sidebar.classList.remove("mobile-open");
  if (backdrop) backdrop.classList.remove("visible");
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

function showCreateTaskModal(projectId) {
  const types = [
    "coding","debugging","research","refactoring","documentation",
    "marketing","email","design","content","strategy","data_analysis","project_management"
  ];
  const projectOpts = state.projects.length ? `
    <div class="form-group">
      <label for="ct-project">Project</label>
      <select id="ct-project">
        <option value="">None (standalone task)</option>
        ${state.projects.map((p) => `<option value="${p.id}"${projectId === p.id ? ' selected' : ''}>${esc(p.name)}</option>`).join("")}
      </select>
    </div>` : '';
  const repoOptions = state.repos.map((r) => `<option value="${esc(r.id)}">${esc(r.name)} (${esc(r.default_branch)})</option>`).join("");
  showModal(`
    <div class="modal">
      <div class="modal-header"><h3>Create Task</h3>
        <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="ct-title">Title</label>
          <input type="text" id="ct-title" placeholder="Describe your task. Be more specific than 'What is the meaning of life?'">
        </div>
        <div class="form-group">
          <label for="ct-desc">Description</label>
          <textarea id="ct-desc" rows="4" placeholder="Detailed instructions for the agent. The Guide appreciates specifics..."></textarea>
        </div>
        <div class="form-group">
          <label for="ct-type">Task Type</label>
          <select id="ct-type">
            ${types.map((t) => `<option value="${t}">${t.replace("_", " ")}</option>`).join("")}
          </select>
          <div class="help">The task type determines which model, critic, and skills are used.</div>
        </div>
        ${projectOpts}
        ${state.repos.length > 0 ? `
        <div class="form-group">
          <label for="ct-repo">Repository</label>
          <select id="ct-repo" onchange="onTaskRepoChange(this.value)">
            <option value="">None (default)</option>
            ${repoOptions}
          </select>
          <div class="help">Select the repo the agent should work in.</div>
        </div>
        <div class="form-group" id="ct-branch-group" style="display:none">
          <label for="ct-branch">Branch</label>
          <select id="ct-branch">
            <option value="">Default branch</option>
          </select>
        </div>
        ` : ""}
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitCreateTask()">Create</button>
      </div>
    </div>
  `);
  document.getElementById("ct-title")?.focus();
}

async function onTaskRepoChange(repoId) {
  const branchGroup = document.getElementById("ct-branch-group");
  const branchSelect = document.getElementById("ct-branch");
  if (!repoId) {
    if (branchGroup) branchGroup.style.display = "none";
    return;
  }
  if (branchGroup) branchGroup.style.display = "";
  // Load branches if not cached
  await loadRepoBranches(repoId);
  const branches = state.repoBranches[repoId] || [];
  if (branchSelect) {
    const repo = state.repos.find((r) => r.id === repoId);
    const defBranch = repo ? repo.default_branch : "main";
    branchSelect.innerHTML = branches.map((b) => `<option value="${esc(b)}" ${b === defBranch ? "selected" : ""}>${esc(b)}</option>`).join("") || `<option value="">${esc(defBranch)}</option>`;
  }
}

function submitCreateTask() {
  const title = document.getElementById("ct-title")?.value?.trim();
  const desc = document.getElementById("ct-desc")?.value?.trim();
  const type = document.getElementById("ct-type")?.value;
  const projectId = document.getElementById("ct-project")?.value || "";
  if (!title) return toast("Title is required", "error");
  if (!desc) return toast("Description is required", "error");
  doCreateTask(title, desc, type, projectId);
  const repoId = document.getElementById("ct-repo")?.value || "";
  const branch = document.getElementById("ct-branch")?.value || "";
  if (!title) return toast("Title is required", "error");
  if (!desc) return toast("Description is required", "error");
  doCreateTask(title, desc, type, repoId, branch);
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

function showCreateAppModal() {
  const runtimes = ["python", "node", "static", "docker"];
  showModal(`
    <div class="modal">
      <div class="modal-header"><h3>Create App</h3>
        <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="ca-name">App Name</label>
          <input type="text" id="ca-name" placeholder="My Awesome App">
        </div>
        <div class="form-group">
          <label for="ca-desc">Description</label>
          <textarea id="ca-desc" rows="3" placeholder="Describe what this app should do..."></textarea>
        </div>
        <div class="form-group">
          <label for="ca-runtime">Runtime</label>
          <select id="ca-runtime">
            ${runtimes.map((r) => `<option value="${r}">${r}</option>`).join("")}
          </select>
          <div class="help">Python = Flask/FastAPI, Node = Express/Next, Static = HTML/CSS/JS, Docker = custom container.</div>
        </div>
        <div class="form-group">
          <label for="ca-tags">Tags (comma-separated)</label>
          <input type="text" id="ca-tags" placeholder="dashboard, api, internal">
        </div>
        <div class="form-group">
          <label for="ca-mode">Mode</label>
          <select id="ca-mode">
            <option value="internal">Internal (Agent42 system tool)</option>
            <option value="external">External (public release)</option>
          </select>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitCreateApp()">Create &amp; Build</button>
      </div>
    </div>
  `);
  document.getElementById("ca-name")?.focus();
}

async function submitCreateApp() {
  const name = document.getElementById("ca-name")?.value?.trim();
  const description = document.getElementById("ca-desc")?.value?.trim();
  const runtime = document.getElementById("ca-runtime")?.value;
  const tagsRaw = document.getElementById("ca-tags")?.value?.trim() || "";
  const app_mode = document.getElementById("ca-mode")?.value || "internal";
  if (!name) return toast("App name is required", "error");
  if (!description) return toast("Description is required", "error");
  const tags = tagsRaw ? tagsRaw.split(",").map((t) => t.trim()).filter(Boolean) : [];
  try {
    const res = await api("/apps", {
      method: "POST",
      body: JSON.stringify({ name, description, runtime, tags, app_mode }),
    });
    closeModal();
    toast(`App "${name}" created — building now`, "success");
    await loadApps();
    navigate("apps");
  } catch (err) { toast(err.message, "error"); }
}

function showAppUpdateModal(appId, appName) {
  showModal(`
    <div class="modal">
      <div class="modal-header"><h3>Update: ${esc(appName)}</h3>
        <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="au-desc">Describe the changes</label>
          <textarea id="au-desc" rows="4" placeholder="What should be changed or added..."></textarea>
          <div class="help">An agent will read the existing app and apply your requested changes.</div>
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitAppUpdate('${appId}')">Submit Update</button>
      </div>
    </div>
  `);
  document.getElementById("au-desc")?.focus();
}

async function submitAppUpdate(appId) {
  const description = document.getElementById("au-desc")?.value?.trim();
  if (!description) return toast("Description is required", "error");
  try {
    await api(`/apps/${appId}/update`, {
      method: "POST",
      body: JSON.stringify({ description }),
    });
    closeModal();
    toast("Update task created", "success");
    await loadApps();
    renderApps();
  } catch (err) { toast(err.message, "error"); }
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
  const flavor = STATUS_FLAVOR[status] || "";
  return `<span class="badge-status badge-${status}" title="${flavor}">${status}</span>`;
}

function timeSince(ts) {
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

function formatNumber(n) {
  if (n == null) return "-";
  if (n >= 1000000) return (n / 1000000).toFixed(1) + "M";
  if (n >= 1000) return (n / 1000).toFixed(1) + "K";
  return String(n);
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
  const ts = state.tokenStats;
  const tokenDisplay = ts ? formatNumber(ts.total_tokens) : "-";
  const costDisplay = ts ? "$" + ts.daily_spend_usd.toFixed(4) : "-";
  el.innerHTML = `
    <div class="stat-card"><div class="stat-label">Total</div><div class="stat-value">${state.tasks.length}</div></div>
    <div class="stat-card"><div class="stat-label">Active</div><div class="stat-value text-info">${active}</div></div>
    <div class="stat-card"><div class="stat-label">In Progress</div><div class="stat-value text-warning">${counts.running}</div></div>
    <div class="stat-card"><div class="stat-label">Review</div><div class="stat-value" style="color:var(--accent)">${counts.review}</div></div>
    <div class="stat-card"><div class="stat-label">Blocked</div><div class="stat-value text-danger">${counts.blocked}</div></div>
    <div class="stat-card"><div class="stat-label">Done</div><div class="stat-value text-success">${counts.done}</div></div>
    <div class="stat-card"><div class="stat-label">Tokens</div><div class="stat-value" style="font-family:var(--mono)">${tokenDisplay}</div></div>
    <div class="stat-card"><div class="stat-label">Cost (24h)</div><div class="stat-value" style="font-family:var(--mono)">${costDisplay}</div></div>
  `;
}

function renderTasks() {
  const el = document.getElementById("mc-content") || document.getElementById("page-content");
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
                ${t.repo_id ? `<span style="color:var(--accent)">${esc((state.repos.find(r=>r.id===t.repo_id)||{}).name||"repo")}${t.branch ? ":"+esc(t.branch) : ""}</span>` : ""}
                ${t.assigned_agent ? `<span>${esc(t.assigned_agent)}</span>` : ""}
                ${(t.comments||[]).length > 0 ? `<span>${(t.comments||[]).length} comments</span>` : ""}
                ${t.token_usage?.total_tokens ? `<span class="badge-tokens" title="Tokens used">${formatNumber(t.token_usage.total_tokens)} tok</span>` : ""}
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
    rows = `<tr><td colspan="8"><div class="empty-state"><div class="empty-icon">&#128203;</div><h3>No tasks in the queue</h3><p>The universe is momentarily at peace. Create one?</p></div></td></tr>`;
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
        <td style="font-family:var(--mono);font-size:0.8rem;color:var(--text-muted)">${t.token_usage?.total_tokens ? formatNumber(t.token_usage.total_tokens) : "-"}</td>
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
          <thead><tr><th>ID</th><th>Title</th><th>Status</th><th>Type</th><th>Agent</th><th>Tokens</th><th>Created</th><th>Actions</th></tr></thead>
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
      ${state.activityFeed.length === 0 ? '<div style="padding:1rem;color:var(--text-muted);text-align:center">No recent activity. The universe is suspiciously quiet.</div>' : ""}
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
  const isActive = ["pending", "assigned", "running"].includes(t.status);

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
          <div class="detail-item"><label>Status</label><div class="value">${statusBadge(t.status)}<div style="font-size:0.75rem;color:var(--text-muted);margin-top:0.25rem;font-style:italic">${STATUS_FLAVOR[t.status] || ""}</div></div></div>
          <div class="detail-item"><label>Type</label><div class="value"><span class="badge-type">${esc(t.task_type)}</span></div></div>
          <div class="detail-item"><label>Iterations</label><div class="value">${t.iterations || 0} / ${t.max_iterations || "?"}</div></div>
          ${t.token_usage?.total_tokens ? `<div class="detail-item"><label>Tokens</label><div class="value" style="font-family:var(--mono)">${formatNumber(t.token_usage.total_tokens)} <span style="color:var(--text-muted);font-size:0.8rem">(${formatNumber(t.token_usage.total_prompt_tokens)} in / ${formatNumber(t.token_usage.total_completion_tokens)} out)</span></div></div>` : ""}
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
      <div class="card-header">
        <h3>${isActive ? "Messages" : "Comments"} (${(t.comments||[]).length})</h3>
        ${isActive ? '<span style="font-size:0.75rem;color:var(--success);font-weight:500">Agent is listening</span>' : ""}
      </div>
      <div class="card-body">
        <div class="comment-thread" style="max-height:300px;overflow-y:auto;margin-bottom:0.75rem">
          ${(t.comments||[]).map(c => `
            <div style="padding:0.5rem;border-bottom:1px solid var(--border)">
              <span style="font-weight:600;color:var(--accent);font-size:0.8rem">${esc(c.author)}</span>
              <span style="color:var(--text-muted);font-size:0.7rem;margin-left:0.5rem">${c.timestamp ? timeSince(c.timestamp) : ""}</span>
              <div style="margin-top:0.2rem;font-size:0.85rem">${esc(c.text)}</div>
            </div>
          `).join("") || '<div style="color:var(--text-muted);font-size:0.85rem">No messages yet</div>'}
        </div>
        ${isActive ? '<div style="font-size:0.75rem;color:var(--text-muted);margin-bottom:0.5rem">Messages here are sent directly to the agent working on this task.</div>' : ""}
        <div style="display:flex;gap:0.5rem">
          <input type="text" id="comment-input" placeholder="${isActive ? "Send a message to the agent..." : "Add a comment..."}" style="flex:1" onkeydown="if(event.key==='Enter'){submitComment('${t.id}');event.preventDefault()}">
          <button class="btn btn-primary btn-sm" onclick="submitComment('${t.id}')">${isActive ? "Send" : "Post"}</button>
        </div>
      </div>
    </div>

    ${t.token_usage?.by_model && Object.keys(t.token_usage.by_model).length > 0 ? `
    <div class="card" style="margin-bottom:1.5rem">
      <div class="card-header"><h3>Token Usage by Model</h3></div>
      <div class="card-body">
        <div class="table-wrap">
          <table>
            <thead><tr><th>Model</th><th>Calls</th><th>Prompt</th><th>Completion</th><th>Total</th></tr></thead>
            <tbody>
              ${Object.entries(t.token_usage.by_model).map(([model, d]) => `
                <tr>
                  <td style="font-family:var(--mono);font-size:0.8rem">${esc(model)}</td>
                  <td>${d.calls}</td>
                  <td>${formatNumber(d.prompt_tokens)}</td>
                  <td>${formatNumber(d.completion_tokens)}</td>
                  <td><strong>${formatNumber(d.prompt_tokens + d.completion_tokens)}</strong></td>
                </tr>
              `).join("")}
            </tbody>
          </table>
        </div>
      </div>
    </div>
    ` : ""}

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
    content = `<div class="empty-state"><div class="empty-icon">&#9989;</div><h3>No pending approvals</h3><p>All clear. No Vogon bureaucracy today.</p></div>`;
  } else {
    content = state.approvals.map((a) => `
      <div class="approval-card">
        <div class="approval-info">
          <div style="font-size:0.75rem;color:var(--text-muted);font-style:italic;margin-bottom:0.25rem">None shall pass\u2026 without your approval.</div>
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

  const rows = state.tools.map((t) => {
    const enabled = t.enabled !== false;
    const toggleId = `tool-toggle-${esc(t.name)}`;
    return `
    <tr style="${enabled ? "" : "opacity:0.55"}">
      <td style="font-weight:600">${esc(t.name)}</td>
      <td style="color:var(--text-secondary)">${esc(t.description || "")}</td>
      <td style="text-align:center">
        <label class="toggle-switch" title="${enabled ? "Disable" : "Enable"} ${esc(t.name)}">
          <input type="checkbox" id="${toggleId}" ${enabled ? "checked" : ""}
            onchange="toggleTool('${esc(t.name)}', this.checked)">
          <span class="toggle-slider"></span>
        </label>
      </td>
    </tr>
  `}).join("");

  el.innerHTML = `
    <div class="card">
      <div class="card-header"><h3>Registered Tools (${state.tools.length})</h3></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Description</th><th style="text-align:center;width:80px">Enabled</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="3"><div class="empty-state">No tools registered</div></td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

function renderSkills() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "skills") return;

  const rows = state.skills.map((s) => {
    const enabled = s.enabled !== false;
    const toggleId = `skill-toggle-${esc(s.name)}`;
    return `
    <tr style="${enabled ? "" : "opacity:0.55"}">
      <td style="font-weight:600">${esc(s.name)}</td>
      <td style="color:var(--text-secondary)">${esc(s.description || "")}</td>
      <td>${(s.task_types || []).map((t) => `<span class="badge-type">${esc(t)}</span>`).join(" ")}</td>
      <td>${s.always_load ? '<span style="color:var(--success)">Always</span>' : ""}</td>
      <td style="text-align:center">
        <label class="toggle-switch" title="${enabled ? "Disable" : "Enable"} ${esc(s.name)}">
          <input type="checkbox" id="${toggleId}" ${enabled ? "checked" : ""}
            onchange="toggleSkill('${esc(s.name)}', this.checked)">
          <span class="toggle-slider"></span>
        </label>
      </td>
    </tr>
  `}).join("");

  el.innerHTML = `
    <div class="card">
      <div class="card-header"><h3>Loaded Skills (${state.skills.length})</h3></div>
      <div class="table-wrap">
        <table>
          <thead><tr><th>Name</th><th>Description</th><th>Task Types</th><th>Auto-load</th><th style="text-align:center;width:80px">Enabled</th></tr></thead>
          <tbody>${rows || `<tr><td colspan="5"><div class="empty-state">No skills loaded</div></td></tr>`}</tbody>
        </table>
      </div>
    </div>
  `;
}

function renderApps() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "apps") return;

  const filtered = state.appFilter
    ? state.apps.filter((a) => a.status === state.appFilter)
    : state.apps;

  // Status counts for filter chips
  const counts = { all: state.apps.length, running: 0, building: 0, ready: 0, stopped: 0, draft: 0, error: 0 };
  state.apps.forEach((a) => { if (counts[a.status] !== undefined) counts[a.status]++; });

  const filterChips = ["", "running", "building", "ready", "stopped", "draft", "error"]
    .filter((f) => f === "" || counts[f] > 0)
    .map((f) => {
      const label = f || "all";
      const count = f ? counts[f] : counts.all;
      const active = state.appFilter === f ? "active" : "";
      return `<button class="chip ${active}" onclick="state.appFilter='${f}';renderApps()">${label} <span class="chip-count">${count}</span></button>`;
    }).join("");

  const cards = filtered.map((app) => {
    const statusClass = `badge-${app.status}`;
    const isRunning = app.status === "running";
    const isStopped = app.status === "stopped" || app.status === "ready";
    const isBuilding = app.status === "building";
    const isError = app.status === "error";

    const actions = [];
    if (isRunning) {
      actions.push(`<button class="btn btn-outline btn-xs" onclick="appAction('${app.id}','stop')">Stop</button>`);
      actions.push(`<button class="btn btn-outline btn-xs" onclick="appAction('${app.id}','restart')">Restart</button>`);
      if (app.url) actions.push(`<a href="${esc(app.url)}" target="_blank" class="btn btn-primary btn-xs">Open</a>`);
    } else if (isStopped) {
      actions.push(`<button class="btn btn-primary btn-xs" onclick="appAction('${app.id}','start')">Start</button>`);
    }
    if (!isBuilding) {
      actions.push(`<button class="btn btn-outline btn-xs" onclick="showAppUpdateModal('${app.id}','${esc(app.name)}')">Update</button>`);
    }
    actions.push(`<button class="btn btn-outline btn-xs" onclick="showAppLogs('${app.id}','${esc(app.name)}')">Logs</button>`);
    actions.push(`<button class="btn btn-outline btn-xs btn-danger-text" onclick="appAction('${app.id}','delete')">Delete</button>`);

    const runtimeIcon = { static: "&#128196;", python: "&#128013;", node: "&#9889;", docker: "&#128051;" }[app.runtime] || "&#128187;";
    const modeLabel = app.app_mode === "external" ? '<span class="badge-type">external</span>' : "";
    const tagsHtml = (app.tags || []).map((t) => `<span class="badge-type">${esc(t)}</span>`).join(" ");

    return `
      <div class="app-card ${isError ? 'app-card-error' : ''} ${isRunning ? 'app-card-running' : ''}">
        <div class="app-card-header">
          <div class="app-card-icon">${app.icon || runtimeIcon}</div>
          <div class="app-card-title">
            <h4>${esc(app.name)}</h4>
            <span class="badge-status ${statusClass}">${app.status}</span>
            ${modeLabel}
          </div>
        </div>
        <p class="app-card-desc">${esc(app.description) || '<span style="color:var(--text-muted)">No description</span>'}</p>
        <div class="app-card-meta">
          <span title="Runtime">${runtimeIcon} ${esc(app.runtime)}</span>
          ${app.port ? `<span title="Port">:${app.port}</span>` : ""}
          <span title="Created">${timeSince(app.created_at)}</span>
          ${tagsHtml}
        </div>
        <div class="app-card-actions">${actions.join("")}</div>
      </div>
    `;
  }).join("");

  el.innerHTML = `
    <div class="apps-stats-row">
      <div class="stat-card"><div class="stat-label">Total</div><div class="stat-value">${state.apps.length}</div></div>
      <div class="stat-card"><div class="stat-label">Running</div><div class="stat-value text-success">${counts.running}</div></div>
      <div class="stat-card"><div class="stat-label">Building</div><div class="stat-value text-warning">${counts.building}</div></div>
      <div class="stat-card"><div class="stat-label">Errors</div><div class="stat-value text-danger">${counts.error}</div></div>
    </div>
    <div class="apps-filters">${filterChips}</div>
    ${filtered.length ? `<div class="apps-grid">${cards}</div>` : '<div class="empty-state" style="padding:3rem;text-align:center"><p style="font-size:1.1rem;margin-bottom:1rem">No apps yet</p><p style="color:var(--text-muted)">In the beginning there were no apps. This has since been rectified.</p><button class="btn btn-primary" style="margin-top:1rem" onclick="showCreateAppModal()">+ Create App</button></div>'}
  `;
}

async function appAction(appId, action) {
  try {
    if (action === "delete") {
      if (!confirm("Permanently delete this app and all its files? This cannot be undone.")) return;
    }
    const method = action === "delete" ? "DELETE" : "POST";
    const path = action === "delete" ? `/apps/${appId}` : `/apps/${appId}/${action}`;
    await api(path, { method });
    toast(`App ${action} successful`, "success");
    await loadApps();
    renderApps();
  } catch (err) { toast(err.message, "error"); }
}

async function showAppLogs(appId, name) {
  try {
    const data = await api(`/apps/${appId}/logs?lines=100`);
    const logs = data?.logs || "No logs available.";
    showModal(`
      <div class="modal" style="max-width:700px">
        <div class="modal-header"><h3>Logs: ${esc(name)}</h3>
          <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
        </div>
        <div class="modal-body">
          <pre class="app-logs-pre">${esc(logs)}</pre>
        </div>
        <div class="modal-footer">
          <button class="btn btn-outline" onclick="closeModal()">Close</button>
        </div>
      </div>
    `);
  } catch (err) { toast(err.message, "error"); }
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
        <div class="capacity-title">Dynamic Agent Capacity ${s.capacity_auto_mode ? "(auto-scaled from hardware)" : `(configured max: ${cfgMax})`}</div>
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

// ---------------------------------------------------------------------------
// Markdown rendering (lightweight)
// ---------------------------------------------------------------------------
function renderMarkdown(text) {
  if (!text) return "";
  let html = esc(text);
  // Code blocks: ```lang\ncode\n```
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const id = "cb-" + Math.random().toString(36).slice(2, 8);
    return `<div class="md-code-block"><div class="md-code-header"><span class="md-code-lang">${lang || "code"}</span><button class="md-code-copy" onclick="copyCodeBlock('${id}')">Copy</button></div><pre id="${id}"><code>${code.trim()}</code></pre></div>`;
  });
  // Inline code: `code`
  html = html.replace(/`([^`\n]+)`/g, '<code class="md-inline-code">$1</code>');
  // Bold: **text**
  html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
  // Italic: *text*
  html = html.replace(/(?<!\*)\*([^*]+)\*(?!\*)/g, "<em>$1</em>");
  // Headers: ### text
  html = html.replace(/^### (.+)$/gm, '<div class="md-h3">$1</div>');
  html = html.replace(/^## (.+)$/gm, '<div class="md-h2">$1</div>');
  html = html.replace(/^# (.+)$/gm, '<div class="md-h1">$1</div>');
  // Unordered lists: - item
  html = html.replace(/^- (.+)$/gm, '<div class="md-li">&bull; $1</div>');
  // Ordered lists: 1. item
  html = html.replace(/^\d+\. (.+)$/gm, '<div class="md-li md-oli">$1</div>');
  // Horizontal rule
  html = html.replace(/^---$/gm, '<hr class="md-hr">');
  // Line breaks (preserve paragraphs)
  html = html.replace(/\n\n/g, '</p><p class="md-p">');
  html = html.replace(/\n/g, "<br>");
  html = '<p class="md-p">' + html + "</p>";
  return html;
}

function copyCodeBlock(id) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {
    const btn = el.parentElement.querySelector(".md-code-copy");
    if (btn) { btn.textContent = "Copied!"; setTimeout(() => btn.textContent = "Copy", 2000); }
  }).catch(() => {});
}

// ---------------------------------------------------------------------------
// Canvas panel (code/output viewer)
// ---------------------------------------------------------------------------
function openCanvas(content, title, lang) {
  state.canvasOpen = true;
  state.canvasContent = content;
  state.canvasTitle = title || "Output";
  state.canvasLang = lang || "";
  renderCanvasPanel();
}

function closeCanvas() {
  state.canvasOpen = false;
  renderCanvasPanel();
}

function renderCanvasPanel() {
  let panel = document.getElementById("canvas-panel");
  if (!state.canvasOpen) {
    if (panel) panel.classList.remove("open");
    document.querySelector(".chat-main")?.classList.remove("canvas-active");
    return;
  }
  if (!panel) {
    panel = document.createElement("div");
    panel.id = "canvas-panel";
    panel.className = "canvas-panel";
    document.querySelector(".chat-layout")?.appendChild(panel);
  }
  panel.classList.add("open");
  document.querySelector(".chat-main")?.classList.add("canvas-active");
  const id = "canvas-code-" + Math.random().toString(36).slice(2, 8);
  panel.innerHTML = `
    <div class="canvas-header">
      <div class="canvas-title">${esc(state.canvasTitle)}</div>
      <div class="canvas-actions">
        <button class="btn btn-sm btn-outline" onclick="copyCodeBlock('${id}')">Copy</button>
        <button class="btn btn-sm btn-outline" onclick="closeCanvas()">&times;</button>
      </div>
    </div>
    <div class="canvas-body">
      <pre id="${id}"><code>${esc(state.canvasContent)}</code></pre>
    </div>
  `;
}

// Extract code blocks from a message to make them openable in canvas
function extractCodeBlocks(text) {
  const blocks = [];
  const re = /```(\w*)\n([\s\S]*?)```/g;
  let m;
  while ((m = re.exec(text)) !== null) {
    blocks.push({ lang: m[1] || "code", code: m[2].trim() });
  }
  return blocks;
}

// ---------------------------------------------------------------------------
// Chat rendering (Claude-like)
// ---------------------------------------------------------------------------

// Build HTML for a single chat message (shared by full render and incremental append)
function buildChatMsgHtml(m, idx, msgArrayName, isCode) {
  const isUser = m.role === "user";
  const sender = m.sender || (isUser ? "You" : "Agent42");
  const time = m.timestamp ? formatChatTime(m.timestamp) : "";
  const content = isUser ? esc(m.content).replace(/\n/g, "<br>") : renderMarkdown(m.content);

  if (isUser) {
    return `<div class="chat-msg chat-msg-user"><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-user">${content}</div></div><div class="chat-avatar chat-avatar-user">U</div></div>`;
  }
  const codeBlocks = extractCodeBlocks(m.content || "");
  m.__codeBlocks = codeBlocks;
  const avatarStyle = isCode ? ' style="background:var(--success-dim);color:var(--success)"' : "";
  const canvasButtons = codeBlocks.map((b, j) =>
    `<button class="chat-canvas-btn" onclick="openCanvas(${msgArrayName}[${idx}].__codeBlocks[${j}].code, '${esc(b.lang)}', '${esc(b.lang)}')">Open ${esc(b.lang)} in canvas</button>`
  ).join("");
  const taskRef = !isCode && m.task_id ? `<div class="chat-task-ref"><a href="#" onclick="event.preventDefault();state.selectedTask=state.tasks.find(t=>t.id==='${m.task_id}');navigate('detail')">View task &rarr;</a></div>` : "";
  return `<div class="chat-msg chat-msg-agent"><div class="chat-avatar chat-avatar-agent"${avatarStyle}>42</div><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-agent">${content}</div>${canvasButtons ? `<div class="chat-canvas-btns">${canvasButtons}</div>` : ""}${taskRef}</div></div>`;
}

// Scroll chat to bottom reliably (after browser paint)
function scrollChatToBottom(containerId) {
  requestAnimationFrame(() => {
    const c = document.getElementById(containerId || "chat-messages");
    if (c) c.scrollTop = c.scrollHeight;
  });
}

// Append a single message to the chat DOM without full re-render.
// Returns true if successful, false if container not found (caller should fall back to full render).
function appendChatMsgToDOM(msg, messages, isCode) {
  const containerId = isCode ? "code-messages" : "chat-messages";
  const container = document.getElementById(containerId);
  if (!container) return false;

  const hasSession = isCode ? !!state.codeCurrentSessionId : !!state.currentSessionId;
  const msgArrayName = isCode
    ? "state.codeCurrentMessages"
    : (hasSession ? "state.currentSessionMessages" : "state.chatMessages");
  const idx = messages.indexOf(msg);
  const msgIdx = idx >= 0 ? idx : messages.length - 1;

  const html = buildChatMsgHtml(msg, msgIdx, msgArrayName, isCode);

  // Remove typing indicator before appending message
  const typing = document.getElementById("chat-typing-indicator");
  if (typing) typing.remove();

  container.insertAdjacentHTML("beforeend", html);

  // Re-add typing indicator if still sending
  const isSending = isCode ? state.codeSending : state.chatSending;
  if (isSending) {
    _insertTypingIndicator(container, isCode);
  }

  scrollChatToBottom(containerId);
  return true;
}

// Add or remove typing indicator without full re-render.
// Returns true if the container exists (incremental update applied), false otherwise.
function updateChatTypingIndicator(show, isCode) {
  const containerId = isCode ? "code-messages" : "chat-messages";
  const container = document.getElementById(containerId);
  if (!container) return false;

  const existing = document.getElementById("chat-typing-indicator");
  if (show && !existing) {
    _insertTypingIndicator(container, isCode);
    scrollChatToBottom(containerId);
  } else if (!show && existing) {
    existing.remove();
  }

  // Update input/button disabled state
  const inputId = isCode ? "code-chat-input" : "chat-input";
  const input = document.getElementById(inputId);
  if (input) input.disabled = show;
  const sendBtn = input?.closest(".chat-composer-inner")?.querySelector(".chat-send-btn");
  if (sendBtn) sendBtn.disabled = show;

  return true;
}

// Internal: insert typing indicator element into container
function _insertTypingIndicator(container, isCode) {
  const avatarStyle = isCode ? ' style="background:var(--success-dim);color:var(--success)"' : "";
  container.insertAdjacentHTML("beforeend",
    `<div class="chat-msg chat-msg-agent" id="chat-typing-indicator"><div class="chat-avatar chat-avatar-agent"${avatarStyle}>42</div><div class="chat-msg-content"><div class="chat-typing"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></div></div></div>`
  );
}

function renderChat() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "chat") return;

  const sessions = state.chatSessions;
  const hasSession = !!state.currentSessionId;

  // Session sidebar
  const sessionList = sessions.map(s => {
    const isActive = s.id === state.currentSessionId;
    const unread = s._unread ? `<span class="session-unread">${s._unread}</span>` : "";
    const title = s.title || "New Chat";
    return `
      <div class="session-item ${isActive ? 'active' : ''}" onclick="switchChatSession('${s.id}')">
        <span class="session-title">${esc(title)}</span>
        ${unread}
        <button class="session-delete" onclick="event.stopPropagation();deleteChatSession('${s.id}','chat')" title="Delete">&times;</button>
      </div>`;
  }).join("");

  // Determine which messages to show
  const messages = hasSession ? state.currentSessionMessages : state.chatMessages;
  const sendFn = hasSession
    ? `sendSessionMessage('${state.currentSessionId}',false)`
    : "sendChatMessage()";
  const keydownFn = hasSession
    ? `if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendSessionMessage('${state.currentSessionId}',false)}`
    : "handleChatKeydown(event)";

  // Welcome / empty
  if (!hasSession && messages.length === 0 && !state.chatSending) {
    el.innerHTML = `
      <div class="chat-layout">
        <div class="session-sidebar">
          <button class="btn btn-primary btn-sm session-new-btn" onclick="createChatSession('chat')">+ New Chat</button>
          <div class="session-list">${sessionList}</div>
        </div>
        <div class="chat-main">
          <div class="chat-welcome">
            <div class="chat-welcome-icon">42</div>
            <h2>Chat with Agent42</h2>
            <p>Start a new conversation or pick up where you left off.</p>
            <div class="chat-suggestions">
              <button class="chat-suggestion" onclick="createChatSession('chat')">+ New Chat</button>
              <button class="chat-suggestion" onclick="applySuggestion('What tasks are currently running?')">What tasks are running?</button>
              <button class="chat-suggestion" onclick="applySuggestion('Help me write a Python script')">Write a Python script</button>
            </div>
          </div>
          <div class="chat-composer">
            <div class="chat-composer-inner">
              <textarea id="chat-input" class="chat-textarea" rows="1" placeholder="Message Agent42..."
                        oninput="autoGrowTextarea(this)" onkeydown="handleChatKeydown(event)"></textarea>
              <button class="chat-send-btn" onclick="sendChatMessage()" title="Send message">
                <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
              </button>
            </div>
          </div>
        </div>
      </div>`;
    return;
  }

  // Build messages
  const msgs = messages.map((m, i) => {
    const isUser = m.role === "user";
    const sender = m.sender || (isUser ? "You" : "Agent42");
    const time = m.timestamp ? formatChatTime(m.timestamp) : "";
    const codeBlocks = isUser ? [] : extractCodeBlocks(m.content || "");
    const content = isUser ? esc(m.content).replace(/\n/g, "<br>") : renderMarkdown(m.content);
    const msgArray = hasSession ? "state.currentSessionMessages" : "state.chatMessages";

    if (isUser) {
      return `<div class="chat-msg chat-msg-user"><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-user">${content}</div></div><div class="chat-avatar chat-avatar-user">U</div></div>`;
    }
    const canvasButtons = codeBlocks.map((b, j) =>
      `<button class="chat-canvas-btn" onclick="openCanvas(${msgArray}[${i}].__codeBlocks[${j}].code, '${esc(b.lang)}', '${esc(b.lang)}')">Open ${esc(b.lang)} in canvas</button>`
    ).join("");
    return `<div class="chat-msg chat-msg-agent"><div class="chat-avatar chat-avatar-agent">42</div><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-agent">${content}</div>${canvasButtons ? `<div class="chat-canvas-btns">${canvasButtons}</div>` : ""}${m.task_id ? `<div class="chat-task-ref"><a href="#" onclick="event.preventDefault();state.selectedTask=state.tasks.find(t=>t.id==='${m.task_id}');navigate('detail')">View task &rarr;</a></div>` : ""}</div></div>`;
  }).join("");

  messages.forEach(m => { if (m.role !== "user") m.__codeBlocks = extractCodeBlocks(m.content || ""); });

  const typingHtml = state.chatSending ? `<div class="chat-msg chat-msg-agent" id="chat-typing-indicator"><div class="chat-avatar chat-avatar-agent">42</div><div class="chat-msg-content"><div class="chat-typing"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></div></div></div>` : "";

  el.innerHTML = `
    <div class="chat-layout">
      <div class="session-sidebar">
        <button class="btn btn-primary btn-sm session-new-btn" onclick="createChatSession('chat')">+ New Chat</button>
        <div class="session-list">${sessionList}</div>
      </div>
      <div class="chat-main ${state.canvasOpen ? "canvas-active" : ""}">
        <div class="chat-messages" id="chat-messages">${msgs}${typingHtml}</div>
        <div class="chat-composer">
          <div class="chat-composer-inner">
            <textarea id="chat-input" class="chat-textarea" rows="1" placeholder="Message Agent42..."
                      oninput="autoGrowTextarea(this)" onkeydown="${keydownFn}"
                      ${state.chatSending ? "disabled" : ""}></textarea>
            <button class="chat-send-btn" onclick="${sendFn}" ${state.chatSending ? "disabled" : ""} title="Send message">
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
            </button>
          </div>
          <div class="chat-composer-hint">Enter to send, Shift+Enter for new line</div>
        </div>
      </div>
      <div id="canvas-panel" class="canvas-panel ${state.canvasOpen ? "open" : ""}"></div>
    </div>
  `;
  scrollChatToBottom("chat-messages");
  if (state.canvasOpen) renderCanvasPanel();
}

function formatChatTime(ts) {
  const d = new Date(ts * 1000);
  const now = new Date();
  const isToday = d.toDateString() === now.toDateString();
  if (isToday) return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  return d.toLocaleDateString([], { month: "short", day: "numeric" }) + " " + d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function autoGrowTextarea(el) {
  el.style.height = "auto";
  el.style.height = Math.min(el.scrollHeight, 200) + "px";
}

function handleChatKeydown(event) {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    sendChatMessage();
  }
}

function applySuggestion(text) {
  const input = document.getElementById("chat-input");
  if (input) {
    input.value = text;
    autoGrowTextarea(input);
    input.focus();
  }
}

// ---------------------------------------------------------------------------
// Mission Control (tabbed: Tasks | Projects)
// ---------------------------------------------------------------------------
function renderMissionControl() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "tasks") return;

  const isProjects = state.missionControlTab === "projects";
  el.innerHTML = `
    <div class="mc-tabs">
      <button class="mc-tab ${isProjects ? 'active' : ''}" onclick="state.missionControlTab='projects';renderMissionControl()">Projects</button>
      <button class="mc-tab ${!isProjects ? 'active' : ''}" onclick="state.missionControlTab='tasks';renderMissionControl()">Tasks</button>
    </div>
    <div id="mc-content"></div>
  `;

  if (isProjects) renderProjectsBoard();
  else renderTasks();
}

function renderProjectsBoard() {
  const el = document.getElementById("mc-content") || document.getElementById("page-content");
  if (!el) return;

  const statuses = ["planning", "active", "paused", "completed"];
  const statusLabels = { planning: "Planning", active: "Active", paused: "Paused", completed: "Completed" };
  const statusColors = { planning: "var(--info)", active: "var(--success)", paused: "var(--warning)", completed: "var(--text-muted)" };

  const columns = statuses.map(s => {
    const items = state.projects.filter(p => p.status === s);
    const cards = items.map(p => {
      const stats = p.stats || {};
      const total = stats.total || 0;
      const done = stats.done || 0;
      const pct = total > 0 ? Math.round((done / total) * 100) : 0;
      const priorityDot = p.priority > 0 ? `<span class="priority-dot priority-${p.priority}"></span>` : "";
      return `
        <div class="project-card" onclick="state.selectedProject=state.projects.find(x=>x.id==='${p.id}');navigate('projectDetail')">
          <div class="project-card-header">
            ${priorityDot}
            <span class="project-card-name">${esc(p.name)}</span>
          </div>
          ${p.description ? `<div class="project-card-desc">${esc(p.description).substring(0, 80)}</div>` : ""}
          <div class="project-card-progress">
            <div class="progress-bar"><div class="progress-fill" style="width:${pct}%;background:${statusColors[s]}"></div></div>
            <span class="progress-text">${done}/${total} tasks</span>
          </div>
          ${p.tags?.length ? `<div class="project-card-tags">${p.tags.map(t => `<span class="tag">${esc(t)}</span>`).join("")}</div>` : ""}
          <div class="project-card-actions" onclick="event.stopPropagation()">
            <button class="btn btn-outline btn-xs" onclick="showCreateTaskModal('${p.id}')">+ Add Task</button>
          </div>
        </div>`;
    }).join("");

    return `
      <div class="kanban-column" style="border-top:3px solid ${statusColors[s]}">
        <div class="kanban-column-header">
          <span>${statusLabels[s]}</span><span class="count">${items.length}</span>
        </div>
        <div class="kanban-column-body">${cards || '<div style="color:var(--text-muted);font-size:0.8rem;text-align:center;padding:1rem">No projects</div>'}</div>
      </div>`;
  }).join("");

  el.innerHTML = `<div class="kanban-board">${columns}</div>`;
}

function renderProjectDetail() {
  const el = document.getElementById("page-content");
  if (!el) return;
  const p = state.selectedProject;
  if (!p) { navigate("tasks"); return; }

  const stats = p.stats || {};
  const total = stats.total || 0;
  const done = stats.done || 0;
  const pct = total > 0 ? Math.round((done / total) * 100) : 0;

  el.innerHTML = `
    <div style="margin-bottom:1rem">
      <a href="#" onclick="event.preventDefault();navigate('tasks')" style="color:var(--text-muted)">&larr; Back to Mission Control</a>
    </div>
    <div class="card" style="margin-bottom:1rem">
      <div style="display:flex;align-items:center;gap:1rem;margin-bottom:1rem">
        <h3 style="margin:0;flex:1">${esc(p.name)}</h3>
        <span class="status-badge status-${p.status}">${p.status}</span>
        <select onchange="updateProjectStatus('${p.id}',this.value)" style="background:var(--bg-input);color:var(--text-primary);border:1px solid var(--border);border-radius:var(--radius-sm);padding:0.25rem 0.5rem">
          ${["planning","active","paused","completed"].map(s => `<option value="${s}" ${p.status === s ? "selected" : ""}>${s}</option>`).join("")}
        </select>
        <button class="btn btn-outline btn-sm btn-danger-text" onclick="archiveProject('${p.id}')">Archive</button>
      </div>
      ${p.description ? `<p style="color:var(--text-secondary);margin-bottom:1rem">${esc(p.description)}</p>` : ""}
      <div class="project-card-progress" style="margin-bottom:1rem">
        <div class="progress-bar" style="height:8px"><div class="progress-fill" style="width:${pct}%"></div></div>
        <span class="progress-text">${done}/${total} tasks done (${pct}%)</span>
      </div>
      ${p.github_repo ? `<div style="color:var(--text-muted);font-size:0.85rem">GitHub: ${esc(p.github_repo)}</div>` : ""}
    </div>
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem">
        <h4 style="margin:0">Tasks</h4>
        <button class="btn btn-primary btn-sm" onclick="showCreateTaskModal('${p.id}')">+ Add Task</button>
      </div>
      <div id="project-tasks-list">Consulting the Guide...</div>
    </div>
  `;

  loadProjectTasks(p.id).then(tasks => {
    const container = document.getElementById("project-tasks-list");
    if (!container) return;
    if (!tasks.length) { container.innerHTML = '<div style="color:var(--text-muted)">No tasks yet</div>'; return; }
    container.innerHTML = tasks.map(t => `
      <div class="task-row" onclick="state.selectedTask=state.tasks.find(x=>x.id==='${t.id}')||${JSON.stringify(t).replace(/'/g, "\\'")};navigate('detail')" style="cursor:pointer">
        <span class="status-badge status-${t.status}">${t.status}</span>
        <span style="flex:1;margin-left:0.5rem">${esc(t.title)}</span>
      </div>
    `).join("");
  });
}

async function updateProjectStatus(projectId, status) {
  try {
    const updated = await api(`/projects/${projectId}/status`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    const idx = state.projects.findIndex(p => p.id === projectId);
    if (idx >= 0) state.projects[idx] = updated;
    if (state.selectedProject?.id === projectId) state.selectedProject = updated;
  } catch (e) { toast("Failed: " + e.message, "error"); }
}

async function archiveProject(projectId) {
  if (!confirm("Archive this project? It will be hidden from the board. Any linked app continues running independently.")) return;
  try {
    await api(`/projects/${projectId}`, { method: "DELETE" });
    state.projects = state.projects.filter(p => p.id !== projectId);
    state.selectedProject = null;
    toast("Project archived", "info");
    navigate("tasks");
  } catch (e) { toast("Failed: " + e.message, "error"); }
}

function showCreateProjectModal() {
  const overlay = document.createElement("div");
  overlay.className = "modal-overlay";
  overlay.id = "modal-overlay";
  overlay.onclick = (e) => { if (e.target === overlay) closeModal(); };
  overlay.innerHTML = `
    <div class="modal">
      <h3>New Project</h3>
      <div class="form-group">
        <label>Project Name</label>
        <input type="text" id="project-name" placeholder="e.g., Website Redesign" autofocus>
      </div>
      <div class="form-group">
        <label>Description</label>
        <textarea id="project-desc" rows="3" placeholder="What is this project about?"></textarea>
      </div>
      <div style="display:flex;gap:0.5rem;justify-content:flex-end;margin-top:1rem">
        <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="createProject()">Create</button>
      </div>
    </div>
  `;
  document.body.appendChild(overlay);
}

// ---------------------------------------------------------------------------
// Code Page
// ---------------------------------------------------------------------------
function renderCode() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "code") return;

  const sessions = state.codeSessions;
  const hasSession = !!state.codeCurrentSessionId;
  const currentSession = sessions.find(s => s.id === state.codeCurrentSessionId);

  // Session sidebar
  const sessionList = sessions.map(s => {
    const isActive = s.id === state.codeCurrentSessionId;
    const unread = s._unread ? `<span class="session-unread">${s._unread}</span>` : "";
    const title = s.title || "New Code";
    return `
      <div class="session-item ${isActive ? 'active' : ''}" onclick="switchCodeSession('${s.id}')">
        <span class="session-title">${esc(title)}</span>
        ${unread}
        <button class="session-delete" onclick="event.stopPropagation();deleteChatSession('${s.id}','code')" title="Delete">&times;</button>
      </div>`;
  }).join("");

  // Code setup flow or chat
  let mainContent = "";
  if (!hasSession) {
    mainContent = `
      <div class="code-welcome">
        <h2 style="margin-bottom:0.5rem">Code with Agent42</h2>
        <p style="color:var(--text-secondary);margin-bottom:1.5rem">Start a new coding session to build projects with AI assistance.</p>
        <button class="btn btn-primary" onclick="createChatSession('code')">+ New Coding Session</button>
      </div>`;
  } else if (state.codeSetupStep === 1 || state.codeSetupStep === 2) {
    mainContent = renderCodeSetupHTML(state.codeCurrentSessionId);
  } else {
    mainContent = renderCodeChatHTML();
  }

  el.innerHTML = `
    <div class="code-layout">
      <div class="session-sidebar">
        <button class="btn btn-primary btn-sm session-new-btn" onclick="createChatSession('code')">+ New Session</button>
        <div class="session-list">${sessionList}</div>
      </div>
      <div class="code-main">
        ${mainContent}
      </div>
    </div>
  `;

  if (hasSession && state.codeSetupStep >= 3) {
    scrollChatToBottom("code-messages");
    if (state.codeCanvasOpen) renderCodeCanvasPanel();
  }
}

function renderCodeSetupHTML(sessionId) {
  if (state.codeSetupStep === 1) {
    return `
      <div class="code-setup">
        <h3>Project Setup</h3>
        <p style="color:var(--text-secondary);margin-bottom:1.5rem">Where will this project run?</p>
        <div class="setup-cards">
          <label class="setup-card">
            <input type="radio" name="code-mode" value="local" checked>
            <div class="setup-card-content">
              <div class="setup-card-icon">&#128187;</div>
              <div class="setup-card-title">Local App</div>
              <div class="setup-card-desc">Build and run on this server using Agent42's app platform</div>
            </div>
          </label>
          <label class="setup-card">
            <input type="radio" name="code-mode" value="remote">
            <div class="setup-card-content">
              <div class="setup-card-icon">&#9729;&#65039;</div>
              <div class="setup-card-title">Remote Server</div>
              <div class="setup-card-desc">Deploy to a remote server via SSH connection</div>
            </div>
          </label>
          <label class="setup-card">
            <input type="radio" name="code-mode" value="github">
            <div class="setup-card-content">
              <div class="setup-card-icon">&#128025;</div>
              <div class="setup-card-title">GitHub Repository</div>
              <div class="setup-card-desc">Connect to a GitHub repo — create new or clone existing</div>
            </div>
          </label>
        </div>
        <button class="btn btn-primary" style="margin-top:1.5rem" onclick="state.codeSetupStep=2;renderCode()">Continue</button>
      </div>`;
  }

  const mode = document.querySelector('input[name="code-mode"]:checked')?.value || "local";
  if (state.codeSetupStep === 2) {
    const localFields = `
      <div class="form-group">
        <label>App Name</label>
        <input type="text" id="code-app-name" placeholder="my-awesome-app">
      </div>
      <div class="form-group">
        <label>Runtime</label>
        <select id="code-runtime">
          <option value="python">Python (Flask/FastAPI)</option>
          <option value="node">Node.js (Express/Next.js)</option>
          <option value="static">Static (HTML/CSS/JS)</option>
        </select>
      </div>`;

    const remoteFields = `
      <div class="form-group">
        <label>SSH Host</label>
        <input type="text" id="code-ssh-host" placeholder="user@hostname">
        <div class="help">Must be in SSH_ALLOWED_HOSTS</div>
      </div>
      <div class="form-group">
        <label><input type="checkbox" id="code-deploy-now"> Deploy immediately after setup</label>
      </div>`;

    const connectedRepoOptions = state.repos.filter(r => r.status === "active").map(r =>
      `<option value="${esc(r.id)}">${esc(r.name)}${r.github_repo ? " (" + esc(r.github_repo) + ")" : ""}</option>`
    ).join("");

    const githubFields = `
      ${connectedRepoOptions ? `
      <div class="form-group">
        <label>Use a connected repository</label>
        <select id="code-repo-id">
          <option value="">-- Select a repo from Settings --</option>
          ${connectedRepoOptions}
        </select>
        <div class="help">Repos connected in Settings are ready to code on and submit PRs</div>
      </div>
      <div style="text-align:center;color:var(--text-muted);margin:0.75rem 0;font-size:0.85rem">— or create / clone —</div>
      ` : ""}
      <div class="form-group">
        <label>Create new repository</label>
        <input type="text" id="code-gh-repo" placeholder="my-project">
        <div class="help">${state.githubConnected ? "A new repo will be created under your GitHub account" : '<a href="#" onclick="openSettings();return false">Connect GitHub in Settings</a> to enable repo creation'}</div>
      </div>
      <div class="form-group">
        <label>Or clone by URL</label>
        <input type="text" id="code-gh-clone-url" placeholder="https://github.com/user/repo.git">
      </div>
      <div class="form-group">
        <label><input type="checkbox" id="code-gh-private" checked> Private repository</label>
      </div>
      <div class="form-group">
        <label>Runtime</label>
        <select id="code-runtime">
          <option value="python">Python (Flask/FastAPI)</option>
          <option value="node">Node.js (Express/Next.js)</option>
          <option value="static">Static (HTML/CSS/JS)</option>
        </select>
      </div>`;

    const titles = { local: "Local App Setup", remote: "Remote Server Setup", github: "GitHub Repository Setup" };

    return `
      <div class="code-setup">
        <h3>${titles[mode] || "Project Setup"}</h3>
        ${mode === "local" ? localFields : mode === "github" ? githubFields : remoteFields}
        ${mode !== "github" ? `
        <div class="form-group">
          <label>GitHub Repository (optional)</label>
          <input type="text" id="code-gh-repo" placeholder="my-project">
          <div class="help">${state.githubConnected ? "Connected to GitHub" : "Connect GitHub in Settings to enable"}</div>
        </div>` : ""}
        <div style="display:flex;gap:0.5rem;margin-top:1.5rem">
          <button class="btn btn-outline" onclick="state.codeSetupStep=1;renderCode()">Back</button>
          <button class="btn btn-primary" onclick="submitCodeSetup('${sessionId}')">Start Coding</button>
        </div>
      </div>`;
  }
  return "";
}

function renderCodeChatHTML() {
  const messages = state.codeCurrentMessages;
  const session = state.codeSessions.find(s => s.id === state.codeCurrentSessionId);

  const msgs = messages.map((m, i) => {
    const isUser = m.role === "user";
    const sender = m.sender || (isUser ? "You" : "Agent42");
    const time = m.timestamp ? formatChatTime(m.timestamp) : "";
    const content = isUser ? esc(m.content).replace(/\n/g, "<br>") : renderMarkdown(m.content);

    if (isUser) {
      return `<div class="chat-msg chat-msg-user"><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-user">${content}</div></div><div class="chat-avatar chat-avatar-user">U</div></div>`;
    }
    const codeBlocks = extractCodeBlocks(m.content || "");
    const canvasButtons = codeBlocks.map((b, j) =>
      `<button class="chat-canvas-btn" onclick="openCanvas(state.codeCurrentMessages[${i}].__codeBlocks[${j}].code, '${esc(b.lang)}', '${esc(b.lang)}')">Open ${esc(b.lang)} in canvas</button>`
    ).join("");
    return `<div class="chat-msg chat-msg-agent"><div class="chat-avatar chat-avatar-agent" style="background:var(--success-dim);color:var(--success)">42</div><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-agent">${content}</div>${canvasButtons ? `<div class="chat-canvas-btns">${canvasButtons}</div>` : ""}</div></div>`;
  }).join("");

  messages.forEach(m => { if (m.role !== "user") m.__codeBlocks = extractCodeBlocks(m.content || ""); });

  const typingHtml = state.codeSending ? `<div class="chat-msg chat-msg-agent" id="chat-typing-indicator"><div class="chat-avatar chat-avatar-agent" style="background:var(--success-dim);color:var(--success)">42</div><div class="chat-msg-content"><div class="chat-typing"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></div></div></div>` : "";

  const deployLabel = { local: "Local", remote: "Remote", github: "GitHub" }[session?.deployment_target] || session?.deployment_target || "";
  const sessionInfo = session?.deployment_target ? `<div class="code-session-info"><span>${deployLabel}</span>${session.github_repo ? ` <span>&#8226; ${esc(session.github_repo)}</span>` : ""}</div>` : "";

  return `
    <div class="code-chat-area ${state.codeCanvasOpen ? 'canvas-active' : ''}">
      <div class="code-chat-panel">
        ${sessionInfo}
        <div class="chat-messages" id="code-messages">${msgs}${typingHtml}</div>
        <div class="chat-composer">
          <div class="chat-composer-inner">
            <textarea id="code-chat-input" class="chat-textarea code-textarea" rows="1" placeholder="Describe what you want to build..."
                      oninput="autoGrowTextarea(this)" onkeydown="if(event.key==='Enter'&&!event.shiftKey){event.preventDefault();sendSessionMessage('${state.codeCurrentSessionId}',true)}"
                      ${state.codeSending ? "disabled" : ""}></textarea>
            <button class="chat-send-btn" onclick="sendSessionMessage('${state.codeCurrentSessionId}',true)" ${state.codeSending ? "disabled" : ""}>
              <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 2L11 13"/><path d="M22 2L15 22L11 13L2 9L22 2Z"/></svg>
            </button>
          </div>
        </div>
      </div>
      <div id="code-canvas-panel" class="canvas-panel ${state.codeCanvasOpen ? 'open' : ''}"></div>
    </div>`;
}

function renderCodeCanvasPanel() {
  const panel = document.getElementById("code-canvas-panel");
  if (!panel || !state.canvasContent) return;
  panel.innerHTML = `
    <div class="canvas-header">
      <span>${esc(state.canvasTitle || "Code")}</span>
      <button class="canvas-close" onclick="state.codeCanvasOpen=false;renderCode()">&times;</button>
    </div>
    <pre class="canvas-code"><code>${esc(state.canvasContent)}</code></pre>
  `;
}

// ---------------------------------------------------------------------------
// Multi-session Chat (updated renderChat)
// ---------------------------------------------------------------------------

function renderReposPanel() {
  const repoRows = state.repos.map((r) => `
    <tr>
      <td><strong>${esc(r.name)}</strong></td>
      <td><code style="font-size:0.8rem">${esc(r.github_repo || r.url || r.local_path)}</code></td>
      <td>${esc(r.default_branch)}</td>
      <td><span class="status-badge status-${r.status === "active" ? "running" : r.status === "error" ? "failed" : "pending"}">${esc(r.status)}</span></td>
      <td>
        <button class="btn btn-outline btn-sm" onclick="syncRepo('${esc(r.id)}')">Sync</button>
        <button class="btn btn-danger btn-sm" onclick="removeRepo('${esc(r.id)}','${esc(r.name)}')">Remove</button>
      </td>
    </tr>
  `).join("");

  const ghRepoRows = state.githubRepos.map((r) => {
    const alreadyAdded = state.repos.some((lr) => lr.github_repo === r.full_name);
    return `
    <tr>
      <td><strong>${esc(r.name)}</strong> ${r.private ? '<span style="color:var(--warning);font-size:0.75rem">private</span>' : ""}</td>
      <td style="font-size:0.8rem;color:var(--text-muted)">${esc(r.description).substring(0, 60)}</td>
      <td>${esc(r.default_branch)}</td>
      <td>${esc(r.language)}</td>
      <td>${alreadyAdded ? '<span style="color:var(--success)">Added</span>' : `<button class="btn btn-primary btn-sm" onclick="addGithubRepo('${esc(r.full_name)}','${esc(r.default_branch)}','${esc(r.account_id || "")}')">Add</button>`}</td>
    </tr>`;
  }).join("");

  const accountRows = state.githubAccounts.map(a => `
    <tr>
      <td><strong>${esc(a.label)}</strong>${a.username ? ` <span style="color:var(--text-muted);font-size:0.8rem">@${esc(a.username)}</span>` : ""}</td>
      <td style="font-family:monospace;font-size:0.8rem;color:var(--text-muted)">${esc(a.masked_token)}</td>
      <td><button class="btn btn-outline btn-sm" style="color:var(--error)" onclick="removeGithubAccount('${esc(a.id)}')">Remove</button></td>
    </tr>`).join("");

  return `
    <h3>Repositories</h3>
    <p class="section-desc">Connect project repositories for agents to work in. Add local repos or clone from GitHub.</p>

    <h4 style="margin:0 0 0.75rem;font-size:0.95rem">GitHub Accounts</h4>
    <p style="color:var(--text-muted);font-size:0.85rem;margin-bottom:0.75rem">Connect one or more GitHub accounts using Personal Access Tokens (PAT). Create tokens at <strong>github.com/settings/tokens</strong> with <code>repo</code> scope.</p>

    ${state.githubAccounts.length > 0 ? `
    <table class="table" style="margin-bottom:1rem">
      <thead><tr><th>Account</th><th>Token</th><th></th></tr></thead>
      <tbody>${accountRows}</tbody>
    </table>` : '<p style="color:var(--text-muted);font-size:0.9rem;margin-bottom:0.75rem">No GitHub accounts connected yet.</p>'}

    <div style="display:flex;gap:0.5rem;flex-wrap:wrap;align-items:flex-end;margin-bottom:1.5rem">
      <div class="form-group" style="margin:0;flex:1;min-width:140px">
        <label style="font-size:0.8rem">Label (optional)</label>
        <input type="text" id="gh-acct-label" placeholder="e.g. personal or my-org" style="width:100%">
      </div>
      <div class="form-group" style="margin:0;flex:2;min-width:200px">
        <label style="font-size:0.8rem">Personal Access Token</label>
        <input type="password" id="gh-acct-token" placeholder="ghp_..." style="width:100%">
      </div>
      <button class="btn btn-primary btn-sm" onclick="addGithubAccount()" ${state.githubAccountAdding ? "disabled" : ""} style="white-space:nowrap">
        ${state.githubAccountAdding ? "Connecting..." : "+ Add Account"}
      </button>
    </div>

    <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Connected Repositories</h4>
    ${state.repos.length > 0 ? `
    <div style="overflow-x:auto">
      <table class="table">
        <thead><tr><th>Name</th><th>Source</th><th>Branch</th><th>Status</th><th>Actions</th></tr></thead>
        <tbody>${repoRows}</tbody>
      </table>
    </div>
    ` : '<p style="color:var(--text-muted);font-size:0.9rem">No repositories connected yet. Add a local repo or connect GitHub below.</p>'}

    <div style="display:flex;gap:0.75rem;margin:1rem 0;flex-wrap:wrap">
      <button class="btn btn-outline btn-sm" onclick="showAddLocalRepoModal()">+ Add Local Repo</button>
      <button class="btn btn-outline btn-sm" onclick="fetchGithubRepos()" ${state.githubLoading ? "disabled" : ""}>
        ${state.githubLoading ? "Loading..." : "Browse GitHub Repos"}
      </button>
    </div>

    ${state.githubRepos.length > 0 ? `
    <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">GitHub Repositories</h4>
    <div style="overflow-x:auto;max-height:400px;overflow-y:auto">
      <table class="table">
        <thead><tr><th>Name</th><th>Description</th><th>Branch</th><th>Lang</th><th></th></tr></thead>
        <tbody>${ghRepoRows}</tbody>
      </table>
    </div>
    ` : ""}
  `;
}

async function fetchGithubRepos() {
  state.githubLoading = true;
  renderSettingsPanel();
  try {
    const data = await api("/github/repos");
    state.githubRepos = data.repos || [];
  } catch (err) {
    toast(err.message || "Failed to load GitHub repos", "error");
    state.githubRepos = [];
  }
  state.githubLoading = false;
  renderSettingsPanel();
}

async function addGithubRepo(fullName, defaultBranch, accountId) {
  try {
    await api("/repos", {
      method: "POST",
      body: JSON.stringify({
        name: fullName.split("/").pop(),
        source: "github",
        github_repo: fullName,
        default_branch: defaultBranch,
        account_id: accountId || "",
      }),
    });
    await loadRepos();
    renderSettingsPanel();
    toast("Repository added", "success");
  } catch (err) {
    toast(err.message || "Failed to add repo", "error");
  }
}

async function addGithubAccount() {
  const token = document.getElementById("gh-acct-token")?.value?.trim();
  const label = document.getElementById("gh-acct-label")?.value?.trim() || "";
  if (!token) return toast("Token is required", "error");
  state.githubAccountAdding = true;
  renderSettingsPanel();
  try {
    await api("/github/accounts", {
      method: "POST",
      body: JSON.stringify({ token, label }),
    });
    state.githubAccountNewLabel = "";
    state.githubAccountNewToken = "";
    await loadGithubAccounts();
    toast("GitHub account connected", "success");
  } catch (err) {
    toast(err.message || "Failed to add account", "error");
  }
  state.githubAccountAdding = false;
  renderSettingsPanel();
}

async function removeGithubAccount(accountId) {
  try {
    await api(`/github/accounts/${accountId}`, { method: "DELETE" });
    await loadGithubAccounts();
    renderSettingsPanel();
    toast("Account removed", "success");
  } catch (err) {
    toast(err.message || "Failed to remove account", "error");
  }
}

function showAddLocalRepoModal() {
  showModal(`
    <div class="modal">
      <div class="modal-header"><h3>Add Local Repository</h3>
        <button class="btn btn-icon btn-outline" onclick="closeModal()">&times;</button>
      </div>
      <div class="modal-body">
        <div class="form-group">
          <label for="lr-name">Name</label>
          <input type="text" id="lr-name" placeholder="my-project">
        </div>
        <div class="form-group">
          <label for="lr-path">Local Path</label>
          <input type="text" id="lr-path" placeholder="/home/user/projects/my-project">
          <div class="help">Absolute path to an existing git repository on this server.</div>
        </div>
        <div class="form-group">
          <label for="lr-branch">Default Branch</label>
          <input type="text" id="lr-branch" value="main" placeholder="main">
        </div>
      </div>
      <div class="modal-footer">
        <button class="btn btn-outline" onclick="closeModal()">Cancel</button>
        <button class="btn btn-primary" onclick="submitAddLocalRepo()">Add</button>
      </div>
    </div>
  `);
  document.getElementById("lr-name")?.focus();
}

async function submitAddLocalRepo() {
  const name = document.getElementById("lr-name")?.value?.trim();
  const path = document.getElementById("lr-path")?.value?.trim();
  const branch = document.getElementById("lr-branch")?.value?.trim() || "main";
  if (!name) return toast("Name is required", "error");
  if (!path) return toast("Path is required", "error");
  try {
    await api("/repos", {
      method: "POST",
      body: JSON.stringify({ name, source: "local", local_path: path, default_branch: branch }),
    });
    await loadRepos();
    closeModal();
    renderSettingsPanel();
    toast("Repository added", "success");
  } catch (err) {
    toast(err.message || "Failed to add repo", "error");
  }
}

async function syncRepo(repoId) {
  try {
    const data = await api(`/repos/${repoId}/sync`, { method: "POST" });
    toast(data.message || "Synced", "success");
  } catch (err) {
    toast(err.message || "Sync failed", "error");
  }
}

async function removeRepo(repoId, name) {
  if (!confirm(`Remove repository "${name}"? This only unlinks it — local files are preserved.`)) return;
  try {
    await api(`/repos/${repoId}`, { method: "DELETE" });
    await loadRepos();
    renderSettingsPanel();
    toast("Repository removed", "success");
  } catch (err) {
    toast(err.message || "Failed to remove", "error");
  }
}

// ---------------------------------------------------------------------------
// Reports page
// ---------------------------------------------------------------------------
function switchReportsTab(tab) {
  state.reportsTab = tab;
  renderReports();
}

async function refreshReports() {
  await loadReports();
  renderReports();
}

function renderReports() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "reports") return;

  const d = state.reportsData;
  if (state.reportsLoading && !d) {
    el.innerHTML = '<div style="padding:2rem;color:var(--text-muted)">Loading reports...</div>';
    return;
  }
  if (!d) {
    el.innerHTML = '<div style="padding:2rem;color:var(--text-muted)">No report data available. Make sure tasks have been run.</div>';
    return;
  }

  const tab = state.reportsTab;
  const tabs = [
    { id: "overview", label: "Overview" },
    { id: "llm", label: "LLM Usage" },
    { id: "tasks", label: "Tasks & Projects" },
  ];
  const tabBar = `<div class="reports-tabs">${tabs.map(t =>
    `<button class="reports-tab ${tab === t.id ? "active" : ""}" onclick="switchReportsTab('${t.id}')">${t.label}</button>`
  ).join("")}<button class="btn btn-outline btn-sm" style="margin-left:auto;align-self:center" onclick="refreshReports()">Refresh</button></div>`;

  let body = "";
  if (tab === "overview") body = _renderReportsOverview(d);
  else if (tab === "llm") body = _renderReportsLLM(d);
  else if (tab === "tasks") body = _renderReportsTasks(d);

  el.innerHTML = tabBar + body;
}

function _reportsBar(pct, label, cls) {
  const p = Math.max(0, Math.min(100, pct || 0));
  const c = cls ? " " + cls : "";
  return `<div class="bar-cell"><div class="bar-fill${c}" style="width:${p}%"></div><span class="bar-label">${esc(String(label))}</span></div>`;
}

function _renderReportsOverview(d) {
  const tb = d.task_breakdown || {};
  const tu = d.token_usage || {};
  const costs = d.costs || {};
  const llm = d.llm_usage || [];
  const conn = d.connectivity || {};
  const byType = tb.by_type || [];
  const byStatus = tb.by_status || {};
  const projects = d.project_breakdown || [];
  const tools = d.tools || {};
  const skills = d.skills || {};

  // Summary stat cards
  const successPct = tb.overall_success_rate != null ? (tb.overall_success_rate * 100).toFixed(1) + "%" : "--";
  const stats = `<div class="reports-stats">
    <div class="stat-card"><div class="stat-label">Total Tasks</div><div class="stat-value">${tb.total || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Success Rate</div><div class="stat-value text-success">${successPct}</div></div>
    <div class="stat-card"><div class="stat-label">Total Tokens</div><div class="stat-value" style="font-family:var(--mono)">${formatNumber(tu.total_tokens)}</div></div>
    <div class="stat-card"><div class="stat-label">Est. Total Cost</div><div class="stat-value" style="font-family:var(--mono)">$${(costs.total_estimated_usd || 0).toFixed(4)}</div></div>
    <div class="stat-card"><div class="stat-label">Daily Spend</div><div class="stat-value" style="font-family:var(--mono)">$${(tu.daily_spend_usd || 0).toFixed(4)}</div></div>
    <div class="stat-card"><div class="stat-label">Models Used</div><div class="stat-value text-info">${llm.length}</div></div>
    <div class="stat-card"><div class="stat-label">Projects</div><div class="stat-value">${projects.length}</div></div>
    <div class="stat-card"><div class="stat-label">Tools</div><div class="stat-value">${tools.enabled || 0}/${tools.total || 0}</div></div>
  </div>`;

  // Top models table (top 10)
  const maxTok = llm.length > 0 ? llm[0].total_tokens : 1;
  const modelRows = llm.slice(0, 10).map(m => {
    const pct = maxTok > 0 ? (m.total_tokens / maxTok * 100) : 0;
    return `<tr>
      <td style="font-weight:600;font-family:var(--mono);font-size:0.85rem">${esc(m.model_key)}</td>
      <td style="text-align:right">${formatNumber(m.calls)}</td>
      <td>${_reportsBar(pct, formatNumber(m.total_tokens), "")}</td>
      <td style="text-align:right;font-family:var(--mono)">$${m.estimated_cost_usd.toFixed(4)}</td>
    </tr>`;
  }).join("");
  const modelsTable = llm.length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Top Models by Token Usage</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Model</th><th style="text-align:right">Calls</th><th>Tokens</th><th style="text-align:right">Est. Cost</th></tr></thead>
      <tbody>${modelRows}</tbody>
    </table></div>
  </div>` : "";

  // Task type breakdown
  const maxType = byType.length > 0 ? Math.max(...byType.map(t => t.total)) : 1;
  const typeRows = byType.map(t => {
    const pct = maxType > 0 ? (t.total / maxType * 100) : 0;
    const sr = t.success_rate != null ? (t.success_rate * 100).toFixed(0) + "%" : "--";
    const srCls = t.success_rate >= 0.8 ? "text-success" : t.success_rate >= 0.5 ? "text-warning" : "text-danger";
    return `<tr>
      <td style="font-weight:600">${esc(t.type)}</td>
      <td>${_reportsBar(pct, t.total, "bar-info")}</td>
      <td style="text-align:right">${t.done || 0}</td>
      <td style="text-align:right">${t.failed || 0}</td>
      <td style="text-align:right" class="${srCls}">${sr}</td>
    </tr>`;
  }).join("");
  const typesTable = byType.length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Task Type Breakdown</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Type</th><th>Count</th><th style="text-align:right">Done</th><th style="text-align:right">Failed</th><th style="text-align:right">Success</th></tr></thead>
      <tbody>${typeRows}</tbody>
    </table></div>
  </div>` : "";

  // Connectivity summary
  const hs = conn.summary || {};
  const connBadges = Object.entries(hs).map(([k, v]) =>
    `<span class="badge-status badge-${k === "ok" ? "done" : k === "unavailable" ? "failed" : "pending"}" style="margin-right:0.5rem">${esc(k)}: ${v}</span>`
  ).join("");
  const connCard = Object.keys(hs).length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Model Connectivity</h3></div>
    <div class="card-body">${connBadges || '<span style="color:var(--text-muted)">No health data</span>'}</div>
  </div>` : "";

  return stats + `<div class="reports-grid">${modelsTable}${typesTable}</div>${connCard}`;
}

function _renderReportsLLM(d) {
  const llm = d.llm_usage || [];
  const perf = d.model_performance || [];
  const conn = d.connectivity || {};
  const models = conn.models || {};

  // Full model usage table
  const maxTok = llm.length > 0 ? llm[0].total_tokens : 1;
  const usageRows = llm.map(m => {
    const pct = maxTok > 0 ? (m.total_tokens / maxTok * 100) : 0;
    return `<tr>
      <td style="font-weight:600;font-family:var(--mono);font-size:0.85rem">${esc(m.model_key)}</td>
      <td style="text-align:right">${formatNumber(m.calls)}</td>
      <td style="text-align:right;font-family:var(--mono)">${formatNumber(m.prompt_tokens)}</td>
      <td style="text-align:right;font-family:var(--mono)">${formatNumber(m.completion_tokens)}</td>
      <td>${_reportsBar(pct, formatNumber(m.total_tokens), "")}</td>
      <td style="text-align:right;font-family:var(--mono)">$${m.estimated_cost_usd.toFixed(4)}</td>
    </tr>`;
  }).join("");
  const usageTable = `<div class="card reports-section">
    <div class="card-header"><h3>Model Token Usage</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Model</th><th style="text-align:right">Calls</th><th style="text-align:right">Prompt</th><th style="text-align:right">Completion</th><th>Total</th><th style="text-align:right">Est. Cost</th></tr></thead>
      <tbody>${usageRows || '<tr><td colspan="6"><div style="padding:1rem;color:var(--text-muted)">No usage data</div></td></tr>'}</tbody>
    </table></div>
  </div>`;

  // Model performance table
  const perfRows = perf.map(m => {
    const scorePct = (m.composite_score || 0) * 100;
    const srPct = (m.success_rate || 0) * 100;
    const srCls = srPct >= 80 ? "bar-success" : srPct >= 50 ? "bar-warning" : "bar-danger";
    return `<tr>
      <td style="font-weight:600;font-family:var(--mono);font-size:0.85rem">${esc(m.model_key)}</td>
      <td>${esc(m.task_type)}</td>
      <td style="text-align:right">${m.total_tasks}</td>
      <td>${_reportsBar(srPct, srPct.toFixed(0) + "%", srCls)}</td>
      <td style="text-align:right;font-family:var(--mono)">${(m.iteration_efficiency || 0).toFixed(2)}</td>
      <td style="text-align:right;font-family:var(--mono)">${(m.critic_avg || 0).toFixed(2)}</td>
      <td>${_reportsBar(scorePct, scorePct.toFixed(0) + "%", "bar-info")}</td>
    </tr>`;
  }).join("");
  const perfTable = perf.length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Model Performance (Evaluator)</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Model</th><th>Task Type</th><th style="text-align:right">Tasks</th><th>Success Rate</th><th style="text-align:right">Iter. Eff.</th><th style="text-align:right">Critic Avg</th><th>Composite</th></tr></thead>
      <tbody>${perfRows}</tbody>
    </table></div>
  </div>` : "";

  // Connectivity / health table
  const healthEntries = Object.entries(models);
  const healthRows = healthEntries.map(([mk, info]) => {
    const st = info.status || "unknown";
    const dot = `<span class="health-dot h-${st}"></span>`;
    const lat = info.latency_ms != null ? info.latency_ms.toFixed(0) + "ms" : "--";
    const checked = info.last_checked ? new Date(info.last_checked * 1000).toLocaleString() : "--";
    return `<tr>
      <td style="font-family:var(--mono);font-size:0.85rem">${esc(mk)}</td>
      <td>${dot}${esc(st)}</td>
      <td style="text-align:right;font-family:var(--mono)">${lat}</td>
      <td style="font-size:0.82rem;color:var(--text-muted)">${esc(checked)}</td>
      <td style="font-size:0.82rem;color:var(--danger)">${esc(info.error || "")}</td>
    </tr>`;
  }).join("");
  const healthTable = healthEntries.length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Model Connectivity</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Model</th><th>Status</th><th style="text-align:right">Latency</th><th>Last Checked</th><th>Error</th></tr></thead>
      <tbody>${healthRows}</tbody>
    </table></div>
  </div>` : "";

  return usageTable + perfTable + healthTable;
}

function _renderReportsTasks(d) {
  const tb = d.task_breakdown || {};
  const byType = tb.by_type || [];
  const byStatus = tb.by_status || {};
  const projects = d.project_breakdown || [];
  const tools = d.tools || {};
  const skills = d.skills || {};
  const skillList = skills.skills || [];

  // Status distribution stat cards
  const statuses = ["pending", "assigned", "running", "review", "blocked", "done", "failed", "archived"];
  const statusCards = `<div class="reports-stats">${statuses.map(s => {
    const cnt = byStatus[s] || 0;
    const cls = s === "done" ? "text-success" : s === "failed" ? "text-danger" : s === "running" ? "text-warning" : s === "blocked" ? "text-danger" : "";
    return `<div class="stat-card"><div class="stat-label">${s}</div><div class="stat-value ${cls}">${cnt}</div></div>`;
  }).join("")}</div>`;

  // Task type table (full)
  const maxType = byType.length > 0 ? Math.max(...byType.map(t => t.total)) : 1;
  const typeRows = byType.map(t => {
    const pct = maxType > 0 ? (t.total / maxType * 100) : 0;
    const sr = t.success_rate != null ? (t.success_rate * 100).toFixed(0) + "%" : "--";
    const srCls = t.success_rate >= 0.8 ? "text-success" : t.success_rate >= 0.5 ? "text-warning" : "text-danger";
    return `<tr>
      <td style="font-weight:600">${esc(t.type)}</td>
      <td>${_reportsBar(pct, t.total, "bar-info")}</td>
      <td style="text-align:right">${t.done || 0}</td>
      <td style="text-align:right">${t.failed || 0}</td>
      <td style="text-align:right" class="${srCls}">${sr}</td>
      <td style="text-align:right;font-family:var(--mono)">${t.avg_iterations || 0}</td>
      <td style="text-align:right;font-family:var(--mono)">${formatNumber(t.total_tokens)}</td>
    </tr>`;
  }).join("");
  const typeTable = `<div class="card reports-section">
    <div class="card-header"><h3>Task Types</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Type</th><th>Count</th><th style="text-align:right">Done</th><th style="text-align:right">Failed</th><th style="text-align:right">Success</th><th style="text-align:right">Avg Iters</th><th style="text-align:right">Tokens</th></tr></thead>
      <tbody>${typeRows || '<tr><td colspan="7"><div style="padding:1rem;color:var(--text-muted)">No tasks</div></td></tr>'}</tbody>
    </table></div>
  </div>`;

  // Projects table
  const projRows = projects.map(p => {
    const total = p.total_tasks || 0;
    const donePct = total > 0 ? (p.done / total * 100) : 0;
    return `<tr>
      <td style="font-weight:600">${esc(p.name)}</td>
      <td><span class="status-badge status-${p.status}">${esc(p.status)}</span></td>
      <td style="text-align:right">${total}</td>
      <td>${_reportsBar(donePct, p.done + "/" + total, "bar-success")}</td>
      <td style="text-align:right">${p.failed || 0}</td>
      <td style="text-align:right">${p.running || 0}</td>
    </tr>`;
  }).join("");
  const projTable = projects.length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Projects (${projects.length})</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Project</th><th>Status</th><th style="text-align:right">Tasks</th><th>Progress</th><th style="text-align:right">Failed</th><th style="text-align:right">Running</th></tr></thead>
      <tbody>${projRows}</tbody>
    </table></div>
  </div>` : "";

  // Skills table
  const skillRows = skillList.map(s => {
    const types = (s.task_types || []).join(", ") || "all";
    const en = s.enabled !== false;
    return `<tr style="${en ? "" : "opacity:0.55"}">
      <td style="font-weight:600">${esc(s.name)}</td>
      <td style="font-size:0.85rem;color:var(--text-secondary)">${esc(s.description || "")}</td>
      <td style="font-size:0.82rem;font-family:var(--mono)">${esc(types)}</td>
      <td style="text-align:center">${en ? '<span style="color:var(--success)">On</span>' : '<span style="color:var(--text-muted)">Off</span>'}</td>
    </tr>`;
  }).join("");
  const skillTable = skillList.length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Skills (${skills.enabled || 0}/${skills.total || 0} enabled)</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Skill</th><th>Description</th><th>Task Types</th><th style="text-align:center">Status</th></tr></thead>
      <tbody>${skillRows}</tbody>
    </table></div>
  </div>` : "";

  // Tools summary
  const toolCard = `<div class="card reports-section">
    <div class="card-header"><h3>Tools</h3></div>
    <div class="card-body">
      <span style="font-size:1.5rem;font-weight:700">${tools.enabled || 0}</span>
      <span style="color:var(--text-muted)"> / ${tools.total || 0} enabled</span>
    </div>
  </div>`;

  return statusCards + typeTable + `<div class="reports-grid">${projTable}${toolCard}</div>` + skillTable;
}

function renderSettings() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "settings") return;

  const tabs = [
    { id: "providers", label: "LLM Providers" },
    { id: "repos", label: "Repositories" },
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
      <div style="text-align:center;padding:1rem;color:var(--text-muted);font-size:0.72rem;font-style:italic">\u201cAnd now for something completely different\u2026\u201d these are your settings.</div>
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
      <p class="section-desc">Configure API keys for language model providers. Agent42 intelligently routes tasks to the best available model based on your configured keys.</p>

      <div class="form-group" style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem">
        <h4 style="margin:0 0 0.75rem;font-size:0.95rem;color:var(--text)">How Model Routing Works</h4>
        <div class="help" style="line-height:1.7">
          Agent42 selects models using a <strong>5-layer priority chain</strong>:<br>
          <strong>1. Admin Override</strong> &mdash; Set <code>AGENT42_CODING_MODEL</code>, <code>AGENT42_CODING_CRITIC</code>, etc. in Orchestrator tab to force a specific model for any task type (e.g., <code>claude-opus-4-6</code> for final code review).<br>
          <strong>2. Dynamic Routing</strong> &mdash; Agent42 tracks task outcomes and automatically promotes models that perform well.<br>
          <strong>3. Trial Injection</strong> &mdash; A small % of tasks test unproven models to discover better options.<br>
          <strong>4. Policy Routing</strong> &mdash; In <em>balanced</em> or <em>performance</em> mode, complex tasks upgrade to paid models when OpenRouter credits are available.<br>
          <strong>5. Free Defaults</strong> &mdash; <strong>Gemini Flash</strong> (primary) + <strong>OpenRouter free models</strong> (critic/fallback).
        </div>
      </div>

      <div class="form-group" style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem">
        <h4 style="margin:0 0 0.75rem;font-size:0.95rem;color:var(--text)">Fallback Chain</h4>
        <div class="help" style="line-height:1.7">
          When a model fails (rate-limited, unavailable, auth error), Agent42 automatically tries the next available provider:<br>
          <strong>Gemini Flash</strong> (free tier: 1,500 req/day, 1M context) &rarr;
          <strong>OpenRouter free models</strong> (diverse but rate-limited) &rarr;
          <strong>OpenAI / Anthropic / DeepSeek</strong> (if keys configured).<br>
          Rate-limited models (429) are skipped instantly &mdash; no wasted retries. Auth errors (401) skip the entire provider.
        </div>
      </div>

      <h4 style="margin:0 0 0.75rem;font-size:0.95rem">Primary Providers</h4>
      ${settingSecret("GEMINI_API_KEY", "Gemini API Key (Recommended)", "Default primary model. Generous free tier: 1,500 requests/day for Flash, 1M token context. Get one at aistudio.google.com.", true)}
      ${settingSecret("OPENROUTER_API_KEY", "OpenRouter API Key", "200+ models via one key. Free models used as critic/fallback. Paid models activated when credits are available. Get one at openrouter.ai/keys.", true)}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Premium Providers (Optional)</h4>
      <div class="help" style="margin-bottom:0.75rem">Set these to enable premium models for admin overrides (e.g., <code>AGENT42_CODING_MODEL=claude-opus-4-6</code>).</div>
      ${settingSecret("ANTHROPIC_API_KEY", "Anthropic API Key", "For Claude Opus/Sonnet models. Get one at console.anthropic.com.")}
      ${settingSecret("OPENAI_API_KEY", "OpenAI API Key", "For GPT-4o, o1, and DALL-E image generation. Get one at platform.openai.com.")}
      ${settingSecret("DEEPSEEK_API_KEY", "DeepSeek API Key", "For DeepSeek Coder/R1 models. Get one at platform.deepseek.com.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Media & Search</h4>
      ${settingSecret("REPLICATE_API_TOKEN", "Replicate API Token", "For FLUX image generation and CogVideoX video. Get one at replicate.com.")}
      ${settingSecret("LUMA_API_KEY", "Luma AI API Key", "For Luma Ray2 premium video generation.")}
      ${settingSecret("BRAVE_API_KEY", "Brave Search API Key", "For web search tool. Get one at brave.com/search/api.")}

      <div class="form-group" style="margin-top:1.5rem">
        <button class="btn btn-primary" id="save-keys-btn" onclick="saveApiKeys()" ${Object.keys(state.keyEdits).length === 0 || state.keySaving ? "disabled" : ""}>
          ${state.keySaving ? "Saving..." : "Save API Keys"}
        </button>
        <div class="help" style="margin-top:0.5rem">Keys saved here override <code>.env</code> values and take effect immediately for new API calls.</div>
      </div>

      <h3 style="margin-top:2rem">OpenRouter Account Status</h3>
      ${state.orStatus ? `
        <div class="form-group">
          <div class="secret-status ${state.orStatus.account && !state.orStatus.account.is_free_tier ? "configured" : "not-configured"}">
            <strong>Tier:</strong> ${state.orStatus.account ? (state.orStatus.account.is_free_tier ? "Free" : "Paid") : "Unknown"}
            ${state.orStatus.account && state.orStatus.account.limit_remaining !== null && state.orStatus.account.limit_remaining !== undefined ? ` &mdash; <strong>Credits remaining:</strong> $${Number(state.orStatus.account.limit_remaining).toFixed(2)}` : ""}
            ${state.orStatus.account && state.orStatus.account.error ? ` &mdash; <span style="color:var(--danger)">${esc(state.orStatus.account.error)}</span>` : ""}
          </div>
          <div class="help" style="margin-top:0.5rem">
            <strong>Policy:</strong> ${esc(state.orStatus.policy)} &mdash;
            <strong>Paid models registered:</strong> ${state.orStatus.paid_models_registered}
            &mdash; <a href="#" onclick="loadOrStatus().then(()=>renderSettingsPanel());return false">Refresh</a>
          </div>
          <div class="help" style="margin-top:0.25rem">
            When policy is <em>balanced</em>, complex tasks (coding, debugging, app creation) auto-upgrade to paid models when credits are available.
            Set policy to <em>free_only</em> in Orchestrator tab to disable paid upgrades, or <em>performance</em> to always prefer the best model.
          </div>
        </div>
      ` : `<div class="help">${state.orStatusLoading ? "Loading..." : "Status not available. Configure an OpenRouter API key first."}</div>`}
    `,
    repos: () => renderReposPanel(),
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
      ${_envSaveBtn()}
    `,
    security: () => `
      <h3>Security</h3>
      <p class="section-desc">Authentication, rate limiting, and sandbox settings for the dashboard and agent execution.</p>

      <h4 style="margin:1rem 0 0.75rem;font-size:0.95rem">Change Password</h4>
      <div class="form-group">
        <label for="cp-current">Current Password</label>
        <input type="password" id="cp-current" placeholder="Enter current password" autocomplete="current-password">
      </div>
      <div class="form-group">
        <label for="cp-new">New Password</label>
        <input type="password" id="cp-new" placeholder="At least 8 characters" autocomplete="new-password">
      </div>
      <div class="form-group">
        <label for="cp-confirm">Confirm New Password</label>
        <input type="password" id="cp-confirm" placeholder="Re-enter new password" autocomplete="new-password">
      </div>
      <div class="form-group">
        <div id="cp-error" style="color:var(--danger);font-size:0.85rem;min-height:1.2em"></div>
        <button class="btn btn-primary" id="cp-btn" onclick="changePassword()">Change Password</button>
      </div>

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Dashboard Authentication</h4>
      ${settingReadonly("DASHBOARD_USERNAME", "Username", "Default: admin")}
      ${settingSecret("DASHBOARD_PASSWORD_HASH", "Password Hash (bcrypt)", 'Generate: python -c "import bcrypt; print(bcrypt.hashpw(b\'yourpassword\', bcrypt.gensalt()).decode())"')}
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
      ${_envSaveBtn()}
    `,
    orchestrator: () => `
      <h3>Orchestrator</h3>
      <p class="section-desc">Controls how Agent42 processes tasks, including concurrency limits and spending controls.</p>

      ${settingReadonly("MAX_CONCURRENT_AGENTS", "Max concurrent agents", "Default: 0 (auto). When 0, capacity is dynamically determined by CPU/memory. Set a positive number to cap the maximum.")}
      ${settingReadonly("MAX_DAILY_API_SPEND_USD", "Daily API spend limit (USD)", "Default: 0 (unlimited). Set a positive value to cap daily spending across all providers.")}
      ${settingReadonly("DEFAULT_REPO_PATH", "Repository path", "The project directory agents work in.")}
      ${settingReadonly("TASKS_JSON_PATH", "Tasks file path", "Default: tasks.json. Persisted task queue file.")}
      ${settingReadonly("MCP_SERVERS_JSON", "MCP servers config", "Path to JSON file defining MCP server connections.")}
      ${settingReadonly("CRON_JOBS_PATH", "Cron jobs file", "Default: cron_jobs.json. Scheduled task definitions.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Model Routing Policy</h4>
      ${settingSelect("MODEL_ROUTING_POLICY", "Routing policy", [
        {value: "free_only", label: "Free only — only free OpenRouter models"},
        {value: "balanced", label: "Balanced — upgrade complex tasks when OR credits available"},
        {value: "performance", label: "Performance — best model regardless of cost"},
      ], "Controls whether Agent42 uses paid models when OpenRouter credits are available.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Dynamic Model Routing</h4>
      ${settingEditable("MODEL_TRIAL_PERCENTAGE", "Trial percentage", "Default: 10. Percentage of tasks randomly assigned to unproven models for evaluation (0-100).")}
      ${settingEditable("MODEL_CATALOG_REFRESH_HOURS", "Catalog refresh interval (hours)", "Default: 24. How often to sync the model catalog from OpenRouter.")}
      ${settingSelect("MODEL_RESEARCH_ENABLED", "Benchmark research", [
        {value: "true", label: "Enabled"},
        {value: "false", label: "Disabled"},
      ], "Enable web benchmark research from authoritative sources (LMSys, HuggingFace).")}
      ${settingEditable("OPENROUTER_BALANCE_CHECK_HOURS", "Balance check interval (hours)", "Default: 1. How often to re-check OpenRouter account balance.")}
      ${_envSaveBtn()}
    `,
    storage: () => {
      const ss = state.storageStatus;
      const modeLabels = {
        file: "File-based (no Qdrant/Redis)",
        qdrant_embedded: "Qdrant embedded + file sessions",
        qdrant_server: "Qdrant server + file sessions",
        qdrant_redis: "Qdrant + Redis (full semantic search & session caching)",
      };
      const statusBadge = (s) => {
        const map = {
          connected: ["ok", "Connected"],
          embedded_ok: ["ok", "Embedded (local)"],
          disabled: ["muted", "Disabled"],
          not_installed: ["warn", "Package not installed"],
          unreachable: ["error", "Unreachable"],
        };
        const [cls, label] = map[s] || ["muted", s];
        const colors = { ok: "#22c55e", warn: "#f59e0b", error: "#ef4444", muted: "var(--text-muted)" };
        return `<span style="color:${colors[cls]};font-weight:600;font-size:0.82rem">${esc(label)}</span>`;
      };
      const backendSection = ss ? `
        <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem">
          <div style="font-weight:600;margin-bottom:0.6rem;font-size:0.9rem">Active Storage Backend</div>
          <div style="margin-bottom:0.5rem;color:var(--text-muted);font-size:0.85rem">${esc(modeLabels[ss.mode] || ss.mode)}</div>
          <table style="width:100%;border-collapse:collapse;font-size:0.84rem">
            <tr>
              <td style="padding:0.3rem 0;color:var(--text-muted);width:120px">Qdrant</td>
              <td>${statusBadge(ss.qdrant.status)}${ss.qdrant.url ? ` &mdash; <code style="font-size:0.8rem">${esc(ss.qdrant.url)}</code>` : ss.qdrant.local_path ? ` &mdash; <code style="font-size:0.8rem">${esc(ss.qdrant.local_path)}</code>` : ""}</td>
            </tr>
            <tr>
              <td style="padding:0.3rem 0;color:var(--text-muted)">Redis</td>
              <td>${statusBadge(ss.redis.status)}${ss.redis.url ? ` &mdash; <code style="font-size:0.8rem">${esc(ss.redis.url)}</code>` : ""}</td>
            </tr>
          </table>
          ${(ss.qdrant.status === "not_installed" || ss.redis.status === "not_installed") ? `
          <div style="margin-top:0.85rem">
            <button onclick="installStoragePackages()" ${state.storageInstalling ? "disabled" : ""} style="background:var(--accent);color:#fff;border:none;border-radius:6px;padding:0.45rem 1rem;font-size:0.84rem;cursor:pointer;opacity:${state.storageInstalling ? "0.6" : "1"}">
              ${state.storageInstalling ? "Installing&hellip;" : "Install missing packages"}
            </button>
            <span style="margin-left:0.75rem;font-size:0.78rem;color:var(--text-muted)">Installs <code>qdrant-client</code>${ss.redis.status === "not_installed" ? " and <code>redis[hiredis]</code>" : ""} via pip. Agent42 restart required after install.</span>
          </div>` : ""}
          <div style="margin-top:0.75rem;font-size:0.78rem;color:var(--text-muted)">
            Backend is configured in <code>.env</code>. To change it, edit <code>QDRANT_ENABLED</code>, <code>QDRANT_URL</code>, and <code>REDIS_URL</code> and restart Agent42.
            <a href="#" onclick="loadStorageStatus().then(renderSettingsPanel);return false" style="margin-left:0.5rem">Refresh</a>
          </div>
        </div>` : `<div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:1rem">Storage status unavailable.</div>`;
      return `
      <h3>Storage &amp; Paths</h3>
      <p class="section-desc">Directories where Agent42 stores memory, outputs, templates, and generated media.</p>

      ${backendSection}

      ${settingReadonly("MEMORY_DIR", "Memory directory", "Default: .agent42/memory. Persistent memory and learning data.")}
      ${settingReadonly("SESSIONS_DIR", "Sessions directory", "Default: .agent42/sessions. Channel conversation history.")}
      ${settingReadonly("OUTPUTS_DIR", "Outputs directory", "Default: .agent42/outputs. Non-code task outputs (reports, analysis, etc.).")}
      ${settingReadonly("TEMPLATES_DIR", "Templates directory", "Default: .agent42/templates. Content templates for reuse.")}
      ${settingReadonly("IMAGES_DIR", "Images directory", "Default: .agent42/images. Generated images from image_gen tool.")}
      ${settingReadonly("SKILLS_DIRS", "Extra skill directories", "Comma-separated paths. Skills are auto-discovered from these + builtins.")}
      ${_envSaveBtn()}
    `; },
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
  const willBeCleared = hasEdit && state.keyEdits[envVar] === '';
  const statusClass = willBeCleared ? "not-configured" : (configured ? "configured" : "not-configured");
  const statusText = willBeCleared
    ? "Will be cleared — click Save API Keys to confirm"
    : (configured
      ? (source === "admin" ? `Configured via admin UI (${esc(masked)})` : `Configured via .env (${esc(masked)})`)
      : "Not configured");

  return `
    <div class="form-group">
      <label>${esc(label)}</label>
      <div class="secret-input" style="display:flex;gap:0.5rem;align-items:center">
        <input type="password"
               placeholder="${willBeCleared ? "— will be cleared on save —" : (configured ? "Enter new value to override" : "Enter API key")}"
               value="${hasEdit ? esc(state.keyEdits[envVar]) : ""}"
               oninput="state.keyEdits['${envVar}']=this.value;updateSaveBtn()"
               style="font-family:var(--mono);flex:1;${highlight || willBeCleared ? "border-color:var(--accent)" : ""}">
        ${configured && source === "admin" ? `<button class="btn btn-sm" onclick="${willBeCleared ? `delete state.keyEdits['${envVar}']` : `state.keyEdits['${envVar}']=''`};renderSettingsPanel()" title="${willBeCleared ? "Undo clear" : "Clear admin-set key"}" style="white-space:nowrap">${willBeCleared ? "Undo" : "Clear"}</button>` : ""}
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

function _envSaveBtn() {
  const hasEdits = Object.keys(state.envEdits).some(k => state.envEdits[k] !== (state.envSettings[k] || ""));
  return `
    <div class="form-group" style="margin-top:1.5rem">
      <button class="btn btn-primary" id="save-env-btn" onclick="saveEnvSettings()" ${!hasEdits || state.envSaving ? "disabled" : ""}>
        ${state.envSaving ? "Saving..." : "Save Settings"}
      </button>
      <div class="help" style="margin-top:0.5rem">Changes are written to <code>.env</code> and hot-reloaded. Some settings may require a restart.</div>
    </div>
  `;
}

function settingEditable(envVar, label, help) {
  const current = state.envSettings[envVar] || "";
  const edited = state.envEdits[envVar];
  const displayVal = edited !== undefined ? edited : current;
  const isChanged = edited !== undefined && edited !== current;
  return `
    <div class="form-group">
      <label>${esc(label)}</label>
      <input type="text" value="${esc(displayVal)}" style="font-family:var(--mono);${isChanged ? "border-color:var(--accent)" : ""}"
             oninput="state.envEdits['${envVar}']=this.value;updateEnvSaveBtn()">
      ${help ? `<div class="help">${help}</div>` : ""}
      <div class="secret-status ${current ? "configured" : "not-configured"}">
        <code>${esc(envVar)}</code>${current ? "" : " (not set)"}
      </div>
    </div>
  `;
}

function settingReadonly(envVar, label, help) {
  return settingEditable(envVar, label, help);
}

function settingSelect(envVar, label, options, help) {
  const current = state.envSettings[envVar] || "";
  const edited = state.envEdits[envVar];
  const displayVal = edited !== undefined ? edited : current;
  const isChanged = edited !== undefined && edited !== current;
  return `
    <div class="form-group">
      <label>${esc(label)}</label>
      <select style="font-family:var(--mono);${isChanged ? "border-color:var(--accent)" : ""}"
              onchange="state.envEdits['${envVar}']=this.value;updateEnvSaveBtn()">
        ${options.map(opt => `<option value="${esc(opt.value)}"${displayVal === opt.value ? " selected" : ""}>${esc(opt.label)}</option>`).join("")}
      </select>
      ${help ? `<div class="help">${help}</div>` : ""}
      <div class="secret-status ${current ? "configured" : "not-configured"}">
        <code>${esc(envVar)}</code>${current ? "" : " (not set)"}
      </div>
    </div>
  `;
}

async function loadOrStatus() {
  state.orStatusLoading = true;
  try {
    const resp = await apiFetch("/settings/openrouter-status");
    if (resp.ok) state.orStatus = await resp.json();
  } catch (e) { /* non-critical */ }
  state.orStatusLoading = false;
}

async function loadReports() {
  state.reportsLoading = true;
  try {
    state.reportsData = (await api("/reports")) || null;
  } catch { state.reportsData = null; }
  state.reportsLoading = false;
}

function updateEnvSaveBtn() {
  const btn = document.getElementById("save-env-btn");
  if (btn) {
    const hasEdits = Object.keys(state.envEdits).some(k => state.envEdits[k] !== state.envSettings[k]);
    btn.disabled = !hasEdits || state.envSaving;
  }
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------
async function loadAll() {
  await Promise.all([
    loadTasks(), loadApprovals(), loadTools(), loadSkills(), loadChannels(), loadProviders(),
    loadHealth(), loadStatus(), loadActivity(), loadApiKeys(), loadEnvSettings(), loadStorageStatus(),
    loadChatMessages(), loadTokenStats(), loadChatSessions(), loadCodeSessions(),
    loadProjects(), loadGitHubStatus(), loadRepos(), loadApps(), loadGithubAccounts(), loadOrStatus(),
    loadReports(),
  ]);
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
          <div class="login-logo">
            <img src="/assets/agent42-logo-light.svg" alt="Agent42" onerror="this.outerHTML='<h1>Agent<span style=&quot;color:var(--accent)&quot;>42</span></h1>'">
          </div>
          <div class="subtitle tagline-rotate" id="login-tagline">${TAGLINES[_taglineIdx]}</div>
          <form onsubmit="event.preventDefault();doLogin(document.getElementById('login-user').value,document.getElementById('login-pass').value)">
            <div id="login-error" style="color:#ef4444;font-size:0.85rem;min-height:1.2em;margin-bottom:0.25rem"></div>
            <div class="form-group">
              <label for="login-user">Username</label>
              <input type="text" id="login-user" value="admin" autocomplete="username">
            </div>
            <div class="form-group">
              <label for="login-pass">Password</label>
              <input type="password" id="login-pass" placeholder="Your improbability passphrase..." autocomplete="current-password" autofocus>
            </div>
            <button type="submit" class="btn btn-primary btn-full" style="margin-top:0.5rem">Sign In</button>
          </form>
          <div class="login-footer-text">A mostly harmless orchestrator</div>
        </div>
      </div>
    `;
    return;
  }

  const approvalBadge = state.approvals.length > 0 ? `<span class="badge">${state.approvals.length}</span>` : "";

  root.innerHTML = `
    <div class="sidebar-backdrop" id="sidebar-backdrop" onclick="closeMobileSidebar()"></div>
    <div class="app-layout">
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-brand"><img src="/assets/agent42-logo-light.svg" alt="Agent42" height="28" onerror="this.outerHTML='Agent<span class=&quot;num&quot;>42</span>'"></div>
        <nav class="sidebar-nav">
          <a href="#" data-page="tasks" class="${state.page === "tasks" ? "active" : ""}" onclick="event.preventDefault();navigate('tasks');closeMobileSidebar()">&#127919; Mission Control</a>
          <a href="#" data-page="status" class="${state.page === "status" ? "active" : ""}" onclick="event.preventDefault();navigate('status');closeMobileSidebar()">&#128200; Status</a>
          <a href="#" data-page="approvals" class="${state.page === "approvals" ? "active" : ""}" onclick="event.preventDefault();navigate('approvals');closeMobileSidebar()">&#128274; Approvals ${approvalBadge}</a>
          <a href="#" data-page="chat" class="${state.page === "chat" ? "active" : ""}" onclick="event.preventDefault();navigate('chat');closeMobileSidebar()">&#128172; Chat</a>
          <a href="#" data-page="code" class="${state.page === "code" ? "active" : ""}" onclick="event.preventDefault();navigate('code');closeMobileSidebar()">&#128187; Code</a>
          <a href="#" data-page="tools" class="${state.page === "tools" ? "active" : ""}" onclick="event.preventDefault();navigate('tools');closeMobileSidebar()">&#128295; Tools</a>
          <a href="#" data-page="skills" class="${state.page === "skills" ? "active" : ""}" onclick="event.preventDefault();navigate('skills');closeMobileSidebar()">&#9889; Skills</a>
          <a href="#" data-page="apps" class="${state.page === "apps" ? "active" : ""}" onclick="event.preventDefault();navigate('apps');closeMobileSidebar()">&#128640; Apps</a>
          <a href="#" data-page="settings" class="${state.page === "settings" ? "active" : ""}" onclick="event.preventDefault();navigate('settings');closeMobileSidebar()">&#9881; Settings</a>
        </nav>
        <div class="sidebar-footer">
          <span id="ws-dot" class="ws-dot ${state.wsConnected ? "connected" : "disconnected"}"></span>
          <span id="ws-label">${state.wsConnected ? "Connected to the Guide" : "Disconnected"}</span>
          <br><a href="#" onclick="event.preventDefault();doLogout()" style="font-size:0.8rem;color:var(--text-muted)">Logout</a>
          <div class="dont-panic-watermark">DON'T PANIC</div>
        </div>
      </aside>
      <div class="main">
        <div class="topbar">
          <button class="hamburger-btn" onclick="toggleMobileSidebar()" aria-label="Open menu">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
          </button>
          <h2>${{ tasks: "Mission Control", status: "Platform Status", approvals: "Approvals", tools: "Tools", skills: "Skills", apps: "Apps", settings: "Settings", detail: "Task Detail", chat: "Chat with Agent42", code: "Code with Agent42", projectDetail: "Project Detail" }[state.page] || "Dashboard"}</h2>
          <div class="topbar-actions">
            ${state.page === "tasks" ? `
              <button class="btn btn-primary btn-sm" onclick="${state.missionControlTab === 'projects' ? 'showCreateProjectModal()' : 'showCreateTaskModal()'}">+ New ${state.missionControlTab === 'projects' ? 'Project' : 'Task'}</button>
              <button class="btn btn-outline btn-sm" style="margin-left:0.5rem" onclick="state.activityOpen=!state.activityOpen;renderActivitySidebar()">Activity</button>
            ` : ""}
            ${state.page === "apps" ? '<button class="btn btn-primary btn-sm" onclick="showCreateAppModal()">+ New App</button>' : ""}
          </div>
        </div>
        <div class="content" id="page-content"></div>
      </div>
    </div>
  `;

  // Render page content
  const renderers = {
    tasks: renderMissionControl,
    status: renderStatus,
    approvals: renderApprovals,
    chat: renderChat,
    code: renderCode,
    tools: renderTools,
    skills: renderSkills,
    apps: renderApps,
    reports: renderReports,
    settings: renderSettings,
    detail: renderDetail,
    projectDetail: renderProjectDetail,
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
  // Towel Day Easter Egg (May 25)
  if (isTowelDay()) {
    document.body.classList.add("towel-day");
    if (state.token && !localStorage.getItem("towelday_" + new Date().getFullYear())) {
      setTimeout(() => {
        toast("\ud83e\udde3 Happy Towel Day! A towel is about the most massively useful thing an interstellar hitchhiker can have.", "info");
        localStorage.setItem("towelday_" + new Date().getFullYear(), "1");
      }, 3000);
    }
  }
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

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
  // Agents
  profiles: [],
  defaultProfile: "",
  selectedProfile: null,
  agentsViewMode: "grid",  // "grid" or "detail"
  personaCustom: "",
  personaDefault: "",
  // API key management
  apiKeys: {},
  keyEdits: {},
  keySaving: false,
  // LLM Routing
  routingModels: { l1: [], fallback: [], l2: [] },
  routingConfig: {},
  routingEdits: {},
  routingSaving: false,
  // Per-agent routing (Agents page)
  agentRoutingEdits: {},
  agentRoutingSaving: false,
  selectedProfileRouting: null,
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
  codeCanvasOpen: false,
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
  // Teams
  teamRuns: [],
  selectedTeamRun: null,
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
  "So long, and thanks for all the tasks.",
  "I love deadlines. I love the whooshing noise they make as they go by.",
  "This must be Thursday. I never could get the hang of Thursdays.",
  "Would it save you a lot of time if I just gave up and went mad now?",
];

// Agent42 robot avatar SVG — cheerful, optimistic (the anti-Marvin)
const AGENT42_AVATAR = `<img src="/assets/agent42-avatar.svg" alt="42" width="20" height="20" style="border-radius:50%">`;

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

// Cross-tab auth synchronization
const _authChannel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("agent42_auth") : null;
if (_authChannel) {
  _authChannel.onmessage = (ev) => {
    if (ev.data?.type === "logout") {
      state.token = "";
      localStorage.removeItem("agent42_token");
      if (ws) ws.close();
      render();
    } else if (ev.data?.type === "login" && ev.data?.token) {
      state.token = ev.data.token;
      localStorage.setItem("agent42_token", ev.data.token);
      connectWS();
      loadAll().then(render);
    }
  };
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json" };
  if (state.token) headers["Authorization"] = `Bearer ${state.token}`;
  const res = await fetch(`${API}${path}`, { ...opts, headers });
  if (res.status === 401) {
    // Try to get specific error code from response
    let errorCode = "";
    let errorMessage = "Session expired. Please log in again.";
    try {
      const data = await res.json();
      if (data.detail?.code) {
        errorCode = data.detail.code;
        errorMessage = data.detail.message || errorMessage;
      } else if (data.error) {
        errorCode = data.error;
        errorMessage = data.message || errorMessage;
      }
    } catch {}

    state.token = "";
    localStorage.removeItem("agent42_token");

    // Broadcast logout to other tabs
    if (_authChannel) {
      _authChannel.postMessage({ type: "logout" });
    }

    render();

    // Show specific error message
    const errEl = document.getElementById("login-error");
    if (errEl) errEl.textContent = errorMessage;

    return null;
  }
  if (!res.ok) {
    const data = await res.json().catch(() => ({}));
    // Handle structured error responses: {error, message, action}
    if (data.error && data.message) {
      if (typeof showError === "function") {
        showError(data.error, data.message, data.action || "");
      }
      const err = new Error(data.message);
      err.code = data.error;
      err.action = data.action || "";
      throw err;
    }
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
      <div class="login-logo">
        <img src="/assets/agent42-logo-light.svg" alt="Agent42" onerror="this.outerHTML='<h1>Agent<span style=&quot;color:var(--accent)&quot;>42</span></h1>'">
      </div>
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
    updateWSIndicator();
    if (wsRetries > 0) {
      // Reconnecting after disconnect — reload data that may have changed
      loadChatSessions(); loadCodeSessions(); loadTasks(); loadStatus();
    }
    wsRetries = 0;
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
    if (idx >= 0) Object.assign(state.tasks[idx], msg.data);
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
    updateGsdIndicator();
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

async function loadProfiles() {
  try {
    const data = await api("/profiles");
    state.profiles = data.profiles || [];
    state.defaultProfile = data.default_profile || "";
  } catch { state.profiles = []; state.defaultProfile = ""; }
}

async function loadPersona() {
  try {
    const data = await api("/persona");
    state.personaCustom = data.custom_prompt || "";
    state.personaDefault = data.default_prompt || "";
  } catch { state.personaCustom = ""; state.personaDefault = ""; }
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
    // Structured errors already shown by api(); only toast unstructured ones
    if (!e.code) toast("Failed to send: " + e.message, "error");
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
    // Structured errors already shown by api(); only toast unstructured ones
    if (!e.code) toast("Failed to send: " + e.message, "error");
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
      // Handle structured error responses from unified handler
      if (data.error && data.message) {
        throw new Error(data.message);
      }
      throw new Error(data.detail || "Login failed");
    }
    const data = await res.json();
    state.token = data.token;
    localStorage.setItem("agent42_token", data.token);

    // Broadcast login to other tabs
    if (_authChannel) {
      _authChannel.postMessage({ type: "login", token: data.token });
    }

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

async function doLogout() {
  // Call logout API to clear httpOnly cookie
  try {
    await fetch(`${API}/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
    });
  } catch (e) {
    // Ignore errors - local logout still happens
  }

  state.token = "";
  localStorage.removeItem("agent42_token");

  // Broadcast logout to other tabs
  if (_authChannel) {
    _authChannel.postMessage({ type: "logout" });
  }

  if (ws) ws.close();
  render();
}

async function doCreateTask(title, description, taskType, projectId, repoId, branch) {
  if (state._creatingTask) return;
  state._creatingTask = true;
  const btn = document.querySelector(".modal .btn-primary, .modal button[type='submit']");
  let loader = null;
  if (btn && typeof LoadingIndicator !== "undefined") {
    loader = new LoadingIndicator(btn);
    loader.show();
  }
  try {
    const body = { title, description, task_type: taskType };
    if (projectId) body.project_id = projectId;
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
    // Structured errors already shown by api(); only toast unstructured ones
    if (!err.code) toast(err.message, "error");
  } finally {
    state._creatingTask = false;
    if (loader) loader.hide();
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
  // Remove IDE layout class when leaving code page
  var pc = document.getElementById("page-content");
  if (pc) pc.classList.remove("ide-layout-parent");
  if (data) {
    if (page === "detail") state.selectedTask = data;
    if (page === "settings" && data.tab) state.settingsTab = data.tab;
  }
  // Preserve IDE container across render() — detach before innerHTML nuke, re-attach after
  var ideEl = document.getElementById("ide-persistent");
  if (ideEl && ideEl.children.length > 0) {
    ideEl.remove();
    window._ideDetached = ideEl;
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
  const repoId = document.getElementById("ct-repo")?.value || "";
  const branch = document.getElementById("ct-branch")?.value || "";
  if (!title) return toast("Title is required", "error");
  if (!desc) return toast("Description is required", "error");
  doCreateTask(title, desc, type, projectId, repoId, branch);
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
  if (!ts) return "-";
  const s = Math.floor(Date.now() / 1000 - ts);
  if (s < 0) return "just now";
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
  const allColumns = [
    { key: "pending", label: "Inbox", alwaysShow: true },
    { key: "assigned", label: "Assigned" },
    { key: "running", label: "In Progress", alwaysShow: true },
    { key: "review", label: "Review", alwaysShow: true },
    { key: "blocked", label: "Blocked" },
    { key: "done", label: "Done", alwaysShow: true },
    { key: "failed", label: "Failed" },
    { key: "archived", label: "Archived" },
  ];
  const filtered = getFilteredTasks();
  const byStatus = {};
  allColumns.forEach(c => byStatus[c.key] = []);
  filtered.forEach(t => { if (byStatus[t.status]) byStatus[t.status].push(t); });
  // Hide empty columns unless they're always-show (core workflow columns)
  const columns = allColumns.filter(c => c.alwaysShow || (byStatus[c.key] || []).length > 0);

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
                ${t.team_run_id ? `<span style="color:var(--a42-gold)" title="Team: ${esc(t.team_name)}">${esc(t.team_name)}/${esc(t.role_name)}</span>` : ""}
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
          <div class="detail-item"><label>Created</label><div class="value">${t.created_at ? new Date(t.created_at * 1000).toLocaleString() : "-"}</div></div>
          <div class="detail-item"><label>Updated</label><div class="value">${t.updated_at ? new Date(t.updated_at * 1000).toLocaleString() : "-"}</div></div>
          ${t.origin_channel ? `<div class="detail-item"><label>Origin</label><div class="value">${esc(t.origin_channel)}</div></div>` : ""}
          ${t.worktree_path ? `<div class="detail-item"><label>Workspace</label><div class="value" style="font-family:var(--mono);font-size:0.8rem">${esc(t.worktree_path)}</div></div>` : ""}
          ${t.team_run_id ? `<div class="detail-item"><label>Team</label><div class="value"><a href="#" onclick="event.preventDefault();viewTeamRun('${esc(t.team_run_id)}')">${esc(t.team_name || "team")} / ${esc(t.role_name || "")}</a></div></div>` : ""}
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

// ---------------------------------------------------------------------------
// Agents page
// ---------------------------------------------------------------------------
function renderAgents() {
  var el = document.getElementById("page-content");
  if (!el || state.page !== "agents") return;

  // Fetch agents from API
  fetch("/api/agents", { headers: { Authorization: "Bearer " + state.token } })
    .then(function(r) { return r.json(); })
    .then(function(agents) { _renderAgentCards(el, agents); })
    .catch(function() { _renderAgentCards(el, []); });
}

function _renderAgentCards(el, agents) {
  var statusColors = { active: "#34d399", running: "#38bdf8", paused: "#facc15", stopped: "#64748b", error: "#f87171" };
  var cards = agents.map(function(a) {
    var color = statusColors[a.status] || "#64748b";
    var tools = (a.tools || []).slice(0, 4).map(function(t) { return '<span class="badge-type">' + esc(t) + '</span>'; }).join(" ");
    var extra = (a.tools || []).length > 4 ? '<span class="badge-type">+' + ((a.tools || []).length - 4) + '</span>' : '';
    var skills = (a.skills || []).slice(0, 3).map(function(s) { return '<span class="badge-type" style="background:var(--primary-dim);color:var(--primary)">' + esc(s) + '</span>'; }).join(" ");
    return '<div class="agent-card" onclick="agentShowDetail(\'' + a.id + '\')">' +
      '<div class="agent-card-header">' +
        '<div class="agent-card-title"><h4>' + esc(a.name) + '</h4>' +
        '<span class="badge-tier" style="background:' + color + ';color:#000">' + esc(a.status) + '</span></div>' +
      '</div>' +
      '<p class="agent-card-desc">' + esc(a.description || "No description") + '</p>' +
      '<div class="agent-card-meta">' +
        '<div style="font-size:0.72rem;color:var(--text-secondary)">Model: ' + esc(a.model || "default") + ' | Schedule: ' + esc(a.schedule || "manual") + '</div>' +
        '<div class="agent-card-chips" style="margin-top:0.3rem">' + tools + extra + '</div>' +
        '<div class="agent-card-chips" style="margin-top:0.2rem">' + skills + '</div>' +
        '<div style="font-size:0.68rem;color:var(--text-muted);margin-top:0.3rem">Runs: ' + (a.total_runs || 0) + ' | Tokens: ' + (a.total_tokens || 0) + '</div>' +
      '</div></div>';
  }).join("");

  el.innerHTML =
    '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">' +
      '<h2 style="margin:0">Agents</h2>' +
      '<div style="display:flex;gap:0.5rem">' +
        '<button class="btn btn-primary" onclick="agentShowCreate()">+ Create Agent</button>' +
        '<button class="btn btn-outline" onclick="agentShowTemplates()">Templates</button>' +
      '</div>' +
    '</div>' +
    '<div class="stats-row">' +
      '<div class="stat-card"><div class="stat-label">Total Agents</div><div class="stat-value">' + agents.length + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">Active</div><div class="stat-value text-success">' + agents.filter(function(a) { return a.status === "active" || a.status === "running"; }).length + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">Paused</div><div class="stat-value text-warning">' + agents.filter(function(a) { return a.status === "paused"; }).length + '</div></div>' +
      '<div class="stat-card"><div class="stat-label">Total Runs</div><div class="stat-value">' + agents.reduce(function(s, a) { return s + (a.total_runs || 0); }, 0) + '</div></div>' +
    '</div>' +
    (cards ? '<div class="agents-grid">' + cards + '</div>' :
      '<div class="empty-state" style="padding:3rem;text-align:center">' +
        '<p style="font-size:1.1rem;margin-bottom:1rem">No agents yet</p>' +
        '<p style="color:var(--text-muted)">Create your first autonomous agent or start from a template.</p>' +
        '<div style="display:flex;gap:0.5rem;justify-content:center;margin-top:1rem">' +
          '<button class="btn btn-primary" onclick="agentShowCreate()">+ Create Agent</button>' +
          '<button class="btn btn-outline" onclick="agentShowTemplates()">Use Template</button>' +
        '</div>' +
      '</div>');
}

function agentShowCreate() {
  var el = document.getElementById("page-content");
  if (!el) return;
  el.innerHTML =
    '<div style="max-width:600px;margin:0 auto">' +
      '<h2>Create Agent</h2>' +
      '<div class="form-group"><label>Name</label><input type="text" id="agent-name" placeholder="My Agent"></div>' +
      '<div class="form-group"><label>Description</label><textarea id="agent-desc" rows="2" placeholder="What does this agent do?"></textarea></div>' +
      '<div class="form-group"><label>Provider</label>' +
        '<select id="agent-provider"><option value="anthropic">Anthropic (CC Subscription)</option><option value="synthetic">Synthetic.new</option><option value="openrouter">OpenRouter</option></select></div>' +
      '<div class="form-group"><label>Model</label>' +
        '<select id="agent-model"><option value="claude-sonnet-4-6">Sonnet 4.6</option><option value="claude-opus-4-6">Opus 4.6</option><option value="claude-haiku-4-5">Haiku 4.5</option></select></div>' +
      '<div class="form-group"><label>Schedule</label>' +
        '<select id="agent-schedule"><option value="manual">Manual</option><option value="always">Always On</option><option value="0 9 * * *">Daily 9am</option><option value="*/5 * * * *">Every 5 min</option></select></div>' +
      '<div class="form-group"><label>Tools (comma-separated)</label><input type="text" id="agent-tools" placeholder="shell, memory, web_search, git"></div>' +
      '<div class="form-group"><label>Skills (comma-separated)</label><input type="text" id="agent-skills" placeholder="code-review, debugging, testing"></div>' +
      '<div class="form-group"><label>Max Iterations</label><input type="number" id="agent-iterations" value="10" min="1" max="100"></div>' +
      '<div style="display:flex;gap:0.5rem;margin-top:1.5rem">' +
        '<button class="btn btn-outline" onclick="renderAgents()">Cancel</button>' +
        '<button class="btn btn-primary" onclick="agentDoCreate()">Create Agent</button>' +
      '</div>' +
    '</div>';
}

async function agentDoCreate() {
  var data = {
    name: document.getElementById("agent-name").value.trim(),
    description: document.getElementById("agent-desc").value.trim(),
    provider: document.getElementById("agent-provider").value,
    model: document.getElementById("agent-model").value,
    schedule: document.getElementById("agent-schedule").value,
    tools: document.getElementById("agent-tools").value.split(",").map(function(s) { return s.trim(); }).filter(Boolean),
    skills: document.getElementById("agent-skills").value.split(",").map(function(s) { return s.trim(); }).filter(Boolean),
    max_iterations: parseInt(document.getElementById("agent-iterations").value) || 10,
  };
  if (!data.name) { toast("Agent name is required", "error"); return; }
  try {
    var res = await fetch("/api/agents", {
      method: "POST",
      headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/json" },
      body: JSON.stringify(data),
    });
    if (res.ok) { toast("Agent created: " + data.name, "success"); renderAgents(); }
    else { toast("Failed to create agent", "error"); }
  } catch (e) { toast("Error: " + e.message, "error"); }
}

function agentShowTemplates() {
  fetch("/api/agents/templates", { headers: { Authorization: "Bearer " + state.token } })
    .then(function(r) { return r.json(); })
    .then(function(templates) {
      var el = document.getElementById("page-content");
      if (!el) return;
      var cards = Object.keys(templates).map(function(key) {
        var t = templates[key];
        var tools = (t.tools || []).map(function(x) { return '<span class="badge-type">' + esc(x) + '</span>'; }).join(" ");
        return '<div class="agent-card" style="cursor:pointer" onclick="agentCreateFromTemplate(\'' + key + '\')">' +
          '<div class="agent-card-header"><div class="agent-card-title"><h4>' + esc(t.name) + '</h4></div></div>' +
          '<p class="agent-card-desc">' + esc(t.description) + '</p>' +
          '<div class="agent-card-meta"><div class="agent-card-chips">' + tools + '</div>' +
          '<div style="font-size:0.72rem;color:var(--text-secondary);margin-top:0.3rem">Model: ' + esc(t.model || "default") + ' | Schedule: ' + esc(t.schedule || "manual") + '</div></div></div>';
      }).join("");
      el.innerHTML =
        '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">' +
          '<h2>Agent Templates</h2>' +
          '<button class="btn btn-outline" onclick="renderAgents()">Back</button>' +
        '</div>' +
        '<p style="color:var(--text-secondary);margin-bottom:1rem">Click a template to create an agent from it.</p>' +
        '<div class="agents-grid">' + cards + '</div>';
    });
}

async function agentCreateFromTemplate(key) {
  try {
    var res = await fetch("/api/agents", {
      method: "POST",
      headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/json" },
      body: JSON.stringify({ template: key }),
    });
    if (res.ok) {
      var agent = await res.json();
      toast("Created agent: " + agent.name, "success");
      renderAgents();
    } else { toast("Failed to create agent", "error"); }
  } catch (e) { toast("Error: " + e.message, "error"); }
}

async function agentShowDetail(id) {
  try {
    var res = await fetch("/api/agents/" + id, { headers: { Authorization: "Bearer " + state.token } });
    var agent = await res.json();
    var el = document.getElementById("page-content");
    if (!el) return;
    var statusColors = { active: "#34d399", running: "#38bdf8", paused: "#facc15", stopped: "#64748b", error: "#f87171" };
    var color = statusColors[agent.status] || "#64748b";
    var tools = (agent.tools || []).map(function(t) { return '<span class="badge-type">' + esc(t) + '</span>'; }).join(" ");
    var skills = (agent.skills || []).map(function(s) { return '<span class="badge-type" style="background:var(--primary-dim);color:var(--primary)">' + esc(s) + '</span>'; }).join(" ");
    var lastRun = agent.last_run_at ? new Date(agent.last_run_at * 1000).toLocaleString() : "Never";
    el.innerHTML =
      '<div style="max-width:700px">' +
        '<button class="btn btn-outline btn-sm" onclick="renderAgents()" style="margin-bottom:1rem">&larr; Back</button>' +
        '<div class="agent-detail-card" style="background:var(--bg-secondary);padding:1.5rem;border-radius:12px;border:1px solid var(--border)">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem">' +
            '<div><h3 style="margin:0">' + esc(agent.name) + '</h3>' +
            '<span class="badge-tier" style="background:' + color + ';color:#000;margin-top:0.25rem;display:inline-block">' + esc(agent.status) + '</span></div>' +
            '<div style="display:flex;gap:0.5rem">' +
              (agent.status === "stopped" ? '<button class="btn btn-primary btn-sm" onclick="agentStart(\'' + agent.id + '\')">Start</button>' : '') +
              (agent.status === "active" ? '<button class="btn btn-outline btn-sm" onclick="agentStop(\'' + agent.id + '\')">Stop</button>' : '') +
              '<button class="btn btn-outline btn-sm btn-danger-text" onclick="agentDelete(\'' + agent.id + '\')">Delete</button>' +
            '</div>' +
          '</div>' +
          '<p style="color:var(--text-secondary)">' + esc(agent.description || "No description") + '</p>' +
          '<div style="display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:1rem">' +
            '<div><strong>Provider:</strong> ' + esc(agent.provider) + '</div>' +
            '<div><strong>Model:</strong> ' + esc(agent.model) + '</div>' +
            '<div><strong>Schedule:</strong> ' + esc(agent.schedule) + '</div>' +
            '<div><strong>Max Iterations:</strong> ' + agent.max_iterations + '</div>' +
            '<div><strong>Total Runs:</strong> ' + (agent.total_runs || 0) + '</div>' +
            '<div><strong>Total Tokens:</strong> ' + (agent.total_tokens || 0) + '</div>' +
            '<div><strong>Last Run:</strong> ' + lastRun + '</div>' +
            '<div><strong>Memory Scope:</strong> ' + esc(agent.memory_scope) + '</div>' +
          '</div>' +
          '<div style="margin-top:1rem"><strong>Tools:</strong><div style="margin-top:0.3rem">' + (tools || "None") + '</div></div>' +
          '<div style="margin-top:0.75rem"><strong>Skills:</strong><div style="margin-top:0.3rem">' + (skills || "None") + '</div></div>' +
        '</div>' +
      '</div>';
  } catch (e) { toast("Error loading agent", "error"); }
}

async function agentStart(id) {
  await fetch("/api/agents/" + id + "/start", { method: "POST", headers: { Authorization: "Bearer " + state.token } });
  toast("Agent started", "success");
  agentShowDetail(id);
}

async function agentStop(id) {
  await fetch("/api/agents/" + id + "/stop", { method: "POST", headers: { Authorization: "Bearer " + state.token } });
  toast("Agent stopped", "success");
  agentShowDetail(id);
}

async function agentDelete(id) {
  if (!confirm("Delete this agent?")) return;
  await fetch("/api/agents/" + id, { method: "DELETE", headers: { Authorization: "Bearer " + state.token } });
  toast("Agent deleted", "success");
  renderAgents();
}

// ---------------------------------------------------------------------------
// Teams Page — Multi-Agent Team Collaboration Monitoring
// ---------------------------------------------------------------------------
// NOTE: All interpolated values use esc() for XSS protection — this follows
// the existing innerHTML pattern used throughout this file (55+ inline handlers).

function renderTeams() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "teams") return;

  if (state.selectedTeamRun) {
    renderTeamRunDetail(el);
    return;
  }

  el.innerHTML = '<div class="teams-page"><div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:1rem"><h3 style="margin:0">Team Runs</h3><button class="btn btn-outline btn-sm" onclick="loadTeamRuns()">Refresh</button></div><div id="team-runs-list"><p style="color:var(--text-muted)">Loading team runs...</p></div></div>';
  loadTeamRuns();
}

async function loadTeamRuns() {
  try {
    const runs = await api("/team-runs");
    state.teamRuns = runs || [];
    const container = document.getElementById("team-runs-list");
    if (!container) return;

    if (state.teamRuns.length === 0) {
      container.innerHTML = '<div class="empty-state"><p>No team runs yet.</p><p style="color:var(--text-muted);font-size:0.85rem">Team runs are created when tasks trigger multi-agent team workflows (research-team, content-team, etc.)</p></div>';
      return;
    }

    container.innerHTML = state.teamRuns.map(function(run) {
      var statusClass = run.status === "completed" ? "text-success" : run.status === "running" ? "text-warning" : run.status === "failed" ? "text-danger" : "";
      var started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : "";
      var duration = run.completed_at && run.started_at ? Math.round(run.completed_at - run.started_at) + "s" : run.status === "running" ? "in progress" : "";
      var taskCount = (run.task_ids || []).length;
      var qualityBadge = run.quality_score ? '<span class="badge-tier">' + run.quality_score + '/10</span>' : "";
      return '<div class="team-run-card" onclick="viewTeamRun(\'' + esc(run.run_id) + '\')"><div style="display:flex;justify-content:space-between;align-items:flex-start"><div><h4 style="margin:0 0 0.25rem 0">' + esc(run.team) + '</h4><p style="margin:0;font-size:0.85rem;color:var(--text-muted)">' + esc((run.task || "").substring(0, 100)) + '</p></div><div style="display:flex;gap:0.5rem;align-items:center"><span class="badge-tier ' + statusClass + '">' + esc(run.status) + '</span>' + qualityBadge + '</div></div><div style="display:flex;gap:1.5rem;margin-top:0.5rem;font-size:0.8rem;color:var(--text-muted)"><span>Workflow: ' + esc(run.workflow) + '</span><span>Tasks: ' + taskCount + '</span><span>Started: ' + started + '</span><span>Duration: ' + duration + '</span></div></div>';
    }).join("");
  } catch (err) {
    var container = document.getElementById("team-runs-list");
    if (container) container.innerHTML = '<p class="text-danger">Failed to load team runs: ' + esc(err.message) + '</p>';
  }
}

async function viewTeamRun(runId) {
  try {
    var detail = await api("/team-runs/" + runId);
    state.selectedTeamRun = detail;
    render();
  } catch (err) { toast(err.message, "error"); }
}

function renderTeamRunDetail(el) {
  var run = state.selectedTeamRun;
  if (!run) return;

  var statusClass = run.status === "completed" ? "text-success" : run.status === "running" ? "text-warning" : run.status === "failed" ? "text-danger" : "";
  var started = run.started_at ? new Date(run.started_at * 1000).toLocaleString() : "";
  var completed = run.completed_at ? new Date(run.completed_at * 1000).toLocaleString() : "";
  var duration = run.completed_at && run.started_at ? Math.round(run.completed_at - run.started_at) + "s" : "in progress";

  var childTasks = (run.child_tasks || []).map(function(t) {
    var tStatusClass = t.status === "done" || t.status === "review" ? "text-success" : t.status === "running" ? "text-warning" : t.status === "failed" ? "text-danger" : "text-muted";
    return '<div class="team-task-row"><span class="badge-tier ' + tStatusClass + '" style="min-width:60px;text-align:center">' + esc(t.status) + '</span><span class="badge-type">' + esc(t.role_name || t.task_type) + '</span><span style="flex:1">' + esc(t.title) + '</span></div>';
  }).join("");

  var roleResults = Object.entries(run.role_results || {}).map(function(entry) {
    var role = entry[0], data = entry[1];
    var output = (data.output || "").substring(0, 1000);
    var revised = data.revised ? '<span class="badge-tier badge-l2">Revised</span>' : "";
    return '<div class="team-role-result"><div style="display:flex;align-items:center;gap:0.5rem;margin-bottom:0.5rem"><h5 style="margin:0">' + esc(role) + '</h5>' + revised + '</div><div class="team-output-preview">' + esc(output) + '</div></div>';
  }).join("");

  var html = '<div class="teams-page">';
  html += '<div style="margin-bottom:1rem"><button class="btn btn-outline btn-sm" onclick="state.selectedTeamRun=null;render()">Back to Team Runs</button></div>';
  html += '<div class="team-run-header"><h3 style="margin:0">' + esc(run.team) + ' <span class="badge-tier ' + statusClass + '">' + esc(run.status) + '</span></h3>';
  html += '<p style="margin:0.5rem 0;color:var(--text-muted)">' + esc(run.task) + '</p>';
  html += '<div style="display:flex;gap:1.5rem;font-size:0.85rem;color:var(--text-muted)">';
  html += '<span>Run ID: ' + esc(run.run_id) + '</span><span>Workflow: ' + esc(run.workflow) + '</span>';
  html += '<span>Started: ' + started + '</span><span>Completed: ' + completed + '</span><span>Duration: ' + duration + '</span>';
  if (run.quality_score) html += '<span>Quality: ' + run.quality_score + '/10</span>';
  html += '</div></div>';

  html += '<div class="team-section"><h4>Task Timeline (' + (run.child_tasks || []).length + ' tasks)</h4>';
  html += '<div class="team-tasks-timeline">' + (childTasks || '<p style="color:var(--text-muted)">No child tasks found</p>') + '</div></div>';

  if (run.manager_plan) {
    html += '<div class="team-section"><h4>Manager Plan</h4><div class="team-output-preview">' + esc((run.manager_plan || "").substring(0, 2000)) + '</div></div>';
  }

  html += '<div class="team-section"><h4>Role Results</h4>' + (roleResults || '<p style="color:var(--text-muted)">No role results yet</p>') + '</div>';

  if (run.manager_review) {
    html += '<div class="team-section"><h4>Manager Review</h4><div class="team-output-preview">' + esc((run.manager_review || "").substring(0, 2000)) + '</div></div>';
  }

  html += '</div>';
  el.innerHTML = html;
}

function updateGsdIndicator() {
  var slot = document.getElementById("gsd-indicator-slot");
  if (!slot) return;
  var ws = state.status && state.status.gsd_workstream;
  while (slot.firstChild) slot.removeChild(slot.firstChild);
  if (ws) {
    var indicator = document.createElement("div");
    indicator.className = "gsd-indicator";
    var wsEl = document.createElement("div");
    wsEl.className = "gsd-workstream";
    wsEl.textContent = "\u25BA " + ws;
    var phaseEl = document.createElement("div");
    phaseEl.className = "gsd-phase";
    phaseEl.textContent = state.status.gsd_phase ? "Phase " + state.status.gsd_phase : "";
    indicator.appendChild(wsEl);
    indicator.appendChild(phaseEl);
    slot.appendChild(indicator);
  }
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

    <div class="card status-section" style="margin-bottom:1.5rem">
      <div class="card-header"><h3>MCP Servers</h3></div>
      <div class="card-body">
        <p style="color:var(--text-muted);margin-bottom:0.75rem">Agent42 MCP server provides tools to Claude Code via stdio transport.</p>
        <div class="status-metric-row"><span class="metric-label">Local Node</span><span class="badge badge-success" style="font-size:0.8rem">Connected</span></div>
        <div class="status-metric-row"><span class="metric-label">Remote Node</span><span class="badge badge-muted" style="font-size:0.8rem;opacity:0.6">Not configured</span></div>
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
            <div class="status-metric-row"><span class="metric-label">Skills Registered</span><span class="metric-value">${s.skills_registered || 0}</span></div>
            <div class="status-metric-row"><span class="metric-label">Tasks Pending</span><span class="metric-value text-info">${s.tasks_pending || 0}</span></div>
            <div class="status-metric-row"><span class="metric-label">Tasks Running</span><span class="metric-value text-warning">${s.tasks_running || 0}</span></div>
            <div class="status-metric-row"><span class="metric-label">Tasks Review</span><span class="metric-value text-purple">${s.tasks_review || 0}</span></div>
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
  // Protect code blocks and inline code from formatting — extract with placeholders
  const codeBlocks = [];
  html = html.replace(/```(\w*)\n([\s\S]*?)```/g, (_, lang, code) => {
    const id = "cb-" + Math.random().toString(36).slice(2, 8);
    const idx = codeBlocks.length;
    codeBlocks.push(`<div class="md-code-block"><div class="md-code-header"><span class="md-code-lang">${lang || "code"}</span><button class="md-code-copy" onclick="copyCodeBlock('${id}')">Copy</button></div><pre id="${id}"><code>${code.trim()}</code></pre></div>`);
    return `\x00CB${idx}\x00`;
  });
  html = html.replace(/`([^`\n]+)`/g, (_, code) => {
    const idx = codeBlocks.length;
    codeBlocks.push(`<code class="md-inline-code">${code}</code>`);
    return `\x00CB${idx}\x00`;
  });
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
  // Restore code blocks
  html = html.replace(/\x00CB(\d+)\x00/g, (_, idx) => codeBlocks[parseInt(idx)]);
  return html;
}

function copyCodeBlock(id) {
  const el = document.getElementById(id);
  if (!el) return;
  navigator.clipboard.writeText(el.textContent).then(() => {
    const btn = el.parentElement?.querySelector(".md-code-copy");
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
  return `<div class="chat-msg chat-msg-agent"><div class="chat-avatar chat-avatar-agent"${avatarStyle}>${AGENT42_AVATAR}</div><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-agent">${content}</div>${canvasButtons ? `<div class="chat-canvas-btns">${canvasButtons}</div>` : ""}${taskRef}</div></div>`;
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
    `<div class="chat-msg chat-msg-agent" id="chat-typing-indicator"><div class="chat-avatar chat-avatar-agent"${avatarStyle}>${AGENT42_AVATAR}</div><div class="chat-msg-content"><div class="chat-typing"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></div></div></div>`
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
            <div class="chat-welcome-icon"><img src="/assets/agent42-avatar.svg" alt="Agent42" width="64" height="64"></div>
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
    return `<div class="chat-msg chat-msg-agent"><div class="chat-avatar chat-avatar-agent">${AGENT42_AVATAR}</div><div class="chat-msg-content"><div class="chat-msg-header"><span class="chat-msg-sender">${esc(sender)}</span><span class="chat-msg-time">${time}</span></div><div class="chat-msg-body chat-msg-body-agent">${content}</div>${canvasButtons ? `<div class="chat-canvas-btns">${canvasButtons}</div>` : ""}${m.task_id ? `<div class="chat-task-ref"><a href="#" onclick="event.preventDefault();state.selectedTask=state.tasks.find(t=>t.id==='${m.task_id}');navigate('detail')">View task &rarr;</a></div>` : ""}</div></div>`;
  }).join("");

  messages.forEach(m => { if (m.role !== "user") m.__codeBlocks = extractCodeBlocks(m.content || ""); });

  const typingHtml = state.chatSending ? `<div class="chat-msg chat-msg-agent" id="chat-typing-indicator"><div class="chat-avatar chat-avatar-agent">${AGENT42_AVATAR}</div><div class="chat-msg-content"><div class="chat-typing"><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span><span class="chat-typing-dot"></span></div></div></div>` : "";

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
// IDE (Monaco Editor)
// ---------------------------------------------------------------------------
let _monacoEditor = null;
let _monacoReady = false;
const _ideTabs = [];
let _ideActiveTab = -1;
let _ideTreeCache = {};
let _ideExpandedDirs = new Set([""]);

function ideDetectLanguage(filename) {
  if (!filename) return "plaintext";
  var ext = filename.split(".").pop().toLowerCase();
  var map = {
    py: "python", js: "javascript", ts: "typescript", tsx: "typescript",
    jsx: "javascript", css: "css", html: "html", json: "json",
    md: "markdown", yaml: "yaml", yml: "yaml", xml: "xml",
    sh: "shell", bash: "shell", rs: "rust", go: "go", java: "java",
    rb: "ruby", php: "php", sql: "sql", toml: "ini", cfg: "ini",
    txt: "plaintext"
  };
  return map[ext] || "plaintext";
}

function renderCode() {
  var pageContent = document.getElementById("page-content");
  var persistent = document.getElementById("ide-persistent");
  if (!pageContent || !persistent || state.page !== "code") return;

  // Hide normal page content, show persistent IDE container
  pageContent.style.display = "none";
  persistent.style.display = "block";

  // If IDE is already built, just show it — don't rebuild
  if (persistent.querySelector("#ide-layout")) {
    // Re-fit terminals after returning
    setTimeout(function() {
      if (typeof termFitAll === "function") termFitAll();
      if (_monacoEditor) _monacoEditor.layout();
      // Re-fit CC terminals
      for (var i = 0; i < _ideTabs.length; i++) {
        if (_ideTabs[i].type === "claude" && _ideTabs[i].fitAddon && _ideTabs[i].el && _ideTabs[i].el.offsetHeight > 0) {
          try { _ideTabs[i].fitAddon.fit(); } catch(e) {}
        }
      }
    }, 50);
    return;
  }

  var el = persistent;

  // NOTE: innerHTML is used here with static template literals only (no user input).
  // All dynamic content is inserted via textContent/DOM methods after this point.
  el.innerHTML = `
    <div id="ide-layout" style="display:flex;flex-direction:column;height:100%;overflow:hidden">
      <div class="ide-top-row" style="display:flex;flex:1;overflow:hidden;min-height:0">
        <div class="ide-activity-bar">
          <button class="ide-activity-btn active" onclick="ideShowPanel('explorer',event)" title="Explorer">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z"/></svg>
          </button>
          <button class="ide-activity-btn" onclick="ideShowPanel('search',event)" title="Search">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>
          </button>
          <button class="ide-activity-btn" onclick="ideToggleCCPanel()" title="Claude Code Panel">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 17l6-6-6-6M12 19h8"/></svg>
          </button>
        </div>
        <div id="ide-sidebar-panel" class="ide-sidebar">
          <div class="ide-sidebar-header">
            <span>EXPLORER</span>
            <div>
              <button onclick="ideRefreshTree()" title="Refresh">&#8635;</button>
              <button onclick="ideToggleSearch()" title="Search">&#128269;</button>
            </div>
          </div>
          <div id="ide-search-panel" class="ide-search-bar" style="display:none">
            <input type="text" id="ide-search-input" placeholder="Search files..."
                   onkeydown="if(event.key==='Enter')ideDoSearch(this.value)">
            <div id="ide-search-results" class="ide-search-results"></div>
          </div>
          <div id="ide-file-tree" class="ide-file-tree"></div>
        </div>
        <div class="ide-main" style="flex:1;display:flex;flex-direction:row;overflow:hidden">
          <div class="ide-main-editor-area" style="flex:1;display:flex;flex-direction:column;overflow:hidden;min-width:0">
            <div id="ide-tabs" class="ide-tabs"></div>
            <div id="ide-editor-container" class="ide-editor-container" style="flex:1;overflow:hidden"></div>
            <div id="ide-cc-container" class="ide-cc-container" style="display:none;flex:1;overflow:hidden;background:#1a1a2e"></div>
            <div id="ide-welcome" class="ide-welcome" style="display:flex">
              <h2>Agent42 IDE</h2>
              <p>Select a file from the explorer to start editing.<br>Changes are saved with Ctrl+S.</p>
              <button class="ide-cc-launch-btn" onclick="ideOpenCCChat('local')">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" style="margin-right:6px;vertical-align:middle"><path d="M4 17l6-6-6-6M12 19h8"/></svg>
                Open Claude Code
              </button>
            </div>
          </div>
          <div id="ide-panel-drag-handle" class="ide-panel-drag-handle" style="display:none"></div>
          <div id="ide-cc-panel" class="ide-cc-panel" style="display:none"></div>
        </div>
      </div>
      <div id="ide-drag-handle" class="ide-drag-handle"></div>
      <div id="ide-terminal-wrapper" class="ide-terminal-wrapper" style="display:flex">
        <div class="ide-panel-tabs">
          <button class="ide-panel-tab" onclick="idePanelTab('problems')">PROBLEMS</button>
          <button class="ide-panel-tab" onclick="idePanelTab('output')">OUTPUT</button>
          <button class="ide-panel-tab active" onclick="idePanelTab('terminal')">TERMINAL</button>
          <div class="ide-panel-actions">
            <div id="ide-terminal-tabs" class="ide-terminal-tabs"></div>
            <div style="display:flex;gap:0.2rem;align-items:center;position:relative">
              <button class="ide-term-btn" onclick="termDropdownToggle()" title="New terminal">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M12 5v14M5 12h14"/></svg>
              </button>
              <button class="ide-term-btn" onclick="termSplit()" title="Split terminal">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M12 3v18"/></svg>
              </button>
              <button class="ide-term-btn" onclick="termKillActive()" title="Kill terminal">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>
              </button>
              <button class="ide-term-btn" onclick="termMaximize()" title="Maximize panel">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M8 3H5a2 2 0 00-2 2v3m18 0V5a2 2 0 00-2-2h-3m0 18h3a2 2 0 002-2v-3M3 16v3a2 2 0 002 2h3"/></svg>
              </button>
              <button class="ide-term-btn" onclick="termToggle()" title="Close panel">
                <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 6L6 18M6 6l12 12"/></svg>
              </button>
              <div id="ide-term-dropdown" class="ide-term-dropdown" style="display:none">
                <div class="dropdown-group-label">Local</div>
                <div class="dropdown-item" onclick="termNew('local');termDropdownDismiss()">Terminal</div>
                <div class="dropdown-item" onclick="termNewClaude('local');termDropdownDismiss()">Claude Code (panel)</div>
                <div class="dropdown-item" onclick="ideOpenCCChat('local');termDropdownDismiss()">Claude Code (tab)</div>
                <div class="dropdown-group-label">Remote</div>
                <div class="dropdown-item remote-item" onclick="termNew('remote');termDropdownDismiss()">Terminal</div>
                <div class="dropdown-item remote-item" onclick="termNewClaude('remote');termDropdownDismiss()">Claude Code (panel)</div>
                <div class="dropdown-item remote-item" onclick="ideOpenCCChat('remote');termDropdownDismiss()">Claude Code (tab)</div>
              </div>
            </div>
          </div>
        </div>
        <div id="ide-terminal-container" style="flex:1;overflow:hidden"></div>
      </div>
      <div id="ide-statusbar" class="ide-statusbar">
        <div class="ide-statusbar-left">
          <span class="ide-status-branch" id="ide-status-branch">main</span>
          <span id="ide-status-left">Ready</span>
        </div>
        <div class="ide-statusbar-right">
          <span id="ide-status-pos">Ln 1, Col 1</span>
          <span id="ide-status-encoding">UTF-8</span>
          <span id="ide-status-lang">Plain Text</span>
        </div>
      </div>
    </div>
  `;

  ideLoadTree("");
  ideInitMonaco();
  initDragHandle();
  initPanelDragHandle();

  // Open default local terminal on first load
  if (_termSessions.length === 0) {
    _termVisible = true;
    termNew("local");
  }

  // Single shared resize listener (guard against duplicate on page revisit)
  if (!window._ideResizeListenerAttached) {
    window._ideResizeListenerAttached = true;
    window.addEventListener("resize", termFitAll);
  }

  // Ctrl+backtick keyboard shortcut (guard against duplicate on page revisit)
  if (!window._ideKeyListenerAttached) {
    window._ideKeyListenerAttached = true;
    document.addEventListener("keydown", function(e) {
      if (state.page !== "code") return;
      if (e.key === "`" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        termToggle();
      }
      // Ctrl+B: toggle explorer (same as VS Code)
      if (e.key === "b" && (e.ctrlKey || e.metaKey)) {
        e.preventDefault();
        ideToggleExplorer();
      }
    });
  }
}

function ideInitMonaco() {
  const container = document.getElementById("ide-editor-container");
  if (!container) return;

  // If Monaco was previously created but DOM was destroyed (SPA re-render),
  // re-create the editor in the new container
  if (_monacoReady && _monacoEditor) {
    if (!container.querySelector(".monaco-editor")) {
      _monacoEditor.dispose();
      _monacoEditor = monaco.editor.create(container, {
        value: "",
        language: "plaintext",
        theme: "agent42-dark",
        fontSize: 14,
        fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
        minimap: { enabled: true },
        automaticLayout: true,
        scrollBeyondLastLine: false,
        wordWrap: "on",
        tabSize: 4,
        renderWhitespace: "selection",
        bracketPairColorization: { enabled: true },
      });
      _monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, function () {
        ideSaveCurrentFile();
      });
      _monacoEditor.onDidChangeCursorPosition(function (e) {
        const pos = document.getElementById("ide-status-pos");
        if (pos) pos.textContent = "Ln " + e.position.lineNumber + ", Col " + e.position.column;
      });
      _monacoEditor.onDidChangeModelContent(function () {
        if (_ideActiveTab >= 0 && _ideTabs[_ideActiveTab]) {
          _ideTabs[_ideActiveTab].modified = true;
          ideRenderTabs();
        }
      });
      container.style.display = "none";
      // Re-activate current tab if one was open
      if (_ideActiveTab >= 0 && _ideTabs[_ideActiveTab]) {
        ideActivateTab();
      }
    }
    return;
  }

  if (_monacoReady) return;
  // Dynamically load Monaco loader if not present
  if (typeof require === "undefined" || !require.config) {
    if (!document.getElementById("monaco-loader-script")) {
      var script = document.createElement("script");
      script.id = "monaco-loader-script";
      script.src = "/vs/loader.js";
      script.onload = function() {
        require.config({ paths: { vs: "/vs" } });
        setTimeout(ideInitMonaco, 100);
      };
      document.head.appendChild(script);
    }
    setTimeout(ideInitMonaco, 300);
    return;
  }
  require(["vs/editor/editor.main"], function () {
    monaco.editor.defineTheme("agent42-dark", {
      base: "vs-dark",
      inherit: true,
      rules: [],
      colors: {
        "editor.background": "#0f172a",
        "editor.foreground": "#e2e8f0",
        "editorLineNumber.foreground": "#475569",
        "editorCursor.foreground": "#38bdf8",
        "editor.selectionBackground": "#334155",
        "editor.lineHighlightBackground": "#1e293b",
      },
    });
    _monacoEditor = monaco.editor.create(container, {
      value: "",
      language: "plaintext",
      theme: "agent42-dark",
      fontSize: 14,
      fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
      minimap: { enabled: true },
      automaticLayout: true,
      scrollBeyondLastLine: false,
      wordWrap: "on",
      tabSize: 4,
      renderWhitespace: "selection",
      bracketPairColorization: { enabled: true },
    });
    _monacoEditor.addCommand(monaco.KeyMod.CtrlCmd | monaco.KeyCode.KeyS, function () {
      ideSaveCurrentFile();
    });
    _monacoEditor.onDidChangeCursorPosition(function (e) {
      const pos = document.getElementById("ide-status-pos");
      if (pos) pos.textContent = "Ln " + e.position.lineNumber + ", Col " + e.position.column;
    });
    _monacoEditor.onDidChangeModelContent(function () {
      if (_ideActiveTab >= 0 && _ideTabs[_ideActiveTab]) {
        _ideTabs[_ideActiveTab].modified = true;
        ideRenderTabs();
      }
    });
    container.style.display = "none";
    _monacoReady = true;
  });
}

async function ideLoadTree(path) {
  try {
    const res = await fetch("/api/ide/tree?path=" + encodeURIComponent(path), {
      headers: { Authorization: "Bearer " + state.token },
    });
    const data = await res.json();
    _ideTreeCache[path] = data.entries;
    ideRenderTree();
  } catch (e) {
    console.error("Tree load error:", e);
  }
}

function ideRenderTree() {
  const el = document.getElementById("ide-file-tree");
  if (!el) return;
  el.innerHTML = ideRenderTreeLevel("", 0);
}

function ideRenderTreeLevel(dirPath, depth) {
  const entries = _ideTreeCache[dirPath];
  if (!entries) return "";
  const indent = '<span class="ide-tree-indent"></span>'.repeat(depth);
  return entries.map(function(e) {
    if (e.type === "dir") {
      const expanded = _ideExpandedDirs.has(e.path);
      const icon = expanded ? "&#9660;" : "&#9654;";
      const children = expanded ? ideRenderTreeLevel(e.path, depth + 1) : "";
      return '<div class="ide-tree-item ide-tree-dir" onclick="ideToggleDir(\'' + e.path.replace(/'/g, "\\'") + '\')">' + indent + '<span class="icon">' + icon + '</span>' + esc(e.name) + '</div>' + children;
    }
    var activeClass = _ideActiveTab >= 0 && _ideTabs[_ideActiveTab] && _ideTabs[_ideActiveTab].path === e.path ? "active" : "";
    var fileIcon = ideFileIcon(e.name);
    return '<div class="ide-tree-item ide-tree-file ' + activeClass + '" onclick="ideOpenFile(\'' + e.path.replace(/'/g, "\\'") + '\')">' + indent + '<span class="icon">' + fileIcon + '</span>' + esc(e.name) + '</div>';
  }).join("");
}

function ideFileIcon(name) {
  var ext = name.split(".").pop();
  if (ext) ext = ext.toLowerCase();
  var icons = { py: "&#128013;", js: "&#9998;", ts: "&#9998;", json: "{ }", md: "&#128196;",
    html: "&#127760;", css: "&#127912;", sh: "&#9881;", yaml: "&#9881;", yml: "&#9881;",
    toml: "&#9881;", txt: "&#128196;", sql: "&#128451;" };
  return icons[ext] || "&#128196;";
}

async function ideToggleDir(path) {
  if (_ideExpandedDirs.has(path)) {
    _ideExpandedDirs.delete(path);
  } else {
    _ideExpandedDirs.add(path);
    if (!_ideTreeCache[path]) await ideLoadTree(path);
  }
  ideRenderTree();
}

async function ideOpenFile(path) {
  var existing = -1;
  for (var i = 0; i < _ideTabs.length; i++) {
    if (_ideTabs[i].path === path) { existing = i; break; }
  }
  if (existing >= 0) {
    _ideActiveTab = existing;
    ideActivateTab();
    return;
  }
  try {
    var statusEl = document.getElementById("ide-status-left");
    if (statusEl) statusEl.textContent = "Loading " + path + "...";
    var res = await fetch("/api/ide/file?path=" + encodeURIComponent(path), {
      headers: { Authorization: "Bearer " + state.token },
    });
    if (!res.ok) { toast("Failed to load file", "error"); return; }
    var data = await res.json();
    var uri = monaco.Uri.parse("file:///" + path);
    var model = monaco.editor.getModel(uri);
    if (model) model.dispose();
    model = monaco.editor.createModel(data.content, data.language, uri);
    _ideTabs.push({ path: path, modified: false, model: model, language: data.language, originalContent: data.content });
    _ideActiveTab = _ideTabs.length - 1;
    ideActivateTab();
    if (statusEl) statusEl.textContent = path;
  } catch (e) {
    toast("Error loading file: " + e.message, "error");
  }
}

function ideActivateTab() {
  if (_ideActiveTab < 0 || !_ideTabs[_ideActiveTab]) return;
  var tab = _ideTabs[_ideActiveTab];
  var container = document.getElementById("ide-editor-container");
  var welcome = document.getElementById("ide-welcome");
  var ccContainer = document.getElementById("ide-cc-container");

  if (tab.type === "claude") {
    // Panel mode: CC session is already in the right panel — switch which tab is visible
    if (_ccPanelMode && tab.inPanel) {
      if (_monacoEditor) _monacoEditor.setModel(null);
      if (container) container.style.display = "none";
      if (welcome) welcome.style.display = "none";
      if (ccContainer) ccContainer.style.display = "none";
      // In the CC panel, hide all CC sessions then show the requested one
      var panel = document.getElementById("ide-cc-panel");
      if (panel) {
        var panelDivs = panel.querySelectorAll(".ide-cc-term, .ide-cc-chat");
        panelDivs.forEach(function(d) { d.style.display = "none"; });
      }
      if (tab.el) tab.el.style.display = tab.chatPanel ? "flex" : "block";
      var langEl2 = document.getElementById("ide-status-lang");
      if (langEl2) langEl2.textContent = "Claude Code";
      var statusEl2 = document.getElementById("ide-status-left");
      if (statusEl2) statusEl2.textContent = tab.path;
      ideRenderTabs();
      ideRenderTree();
      return;
    }
    // Claude Code tab: hide Monaco, show CC terminal
    if (_monacoEditor) _monacoEditor.setModel(null);
    if (container) container.style.display = "none";
    if (welcome) welcome.style.display = "none";
    if (ccContainer) {
      ccContainer.style.display = "block";
      // Show the right CC terminal
      var ccDivs = ccContainer.querySelectorAll(".ide-cc-term, .ide-cc-chat");
      ccDivs.forEach(function(d) { d.style.display = "none"; });
      if (tab.el) tab.el.style.display = tab.chatPanel ? "flex" : "block";
      // Only call fitAddon for xterm-based tabs (chatPanel tabs have no fitAddon -- Pitfall 5)
      if (!tab.chatPanel && tab.fitAddon) { try { tab.fitAddon.fit(); } catch(e) {} }
    }
  } else if (tab.type === "diff") {
    // Diff tab: hide Monaco file editor and CC containers, show diff container
    if (_monacoEditor) _monacoEditor.setModel(null);
    if (container) container.style.display = "none";
    if (welcome) welcome.style.display = "none";
    if (ccContainer) ccContainer.style.display = "none";
    // Hide all other diff containers
    var allDiffEls = document.querySelectorAll(".ide-diff-container");
    allDiffEls.forEach(function(d) { d.style.display = "none"; });
    if (tab.el) {
      tab.el.style.display = "block";
      tab.diffEditor.layout();
    }
  } else {
    // File tab: show Monaco, hide CC terminal
    if (_monacoEditor) {
      _monacoEditor.setModel(tab.model);
      if (container) container.style.display = "block";
    }
    if (welcome) welcome.style.display = "none";
    if (ccContainer) ccContainer.style.display = "none";
  }

  var langEl = document.getElementById("ide-status-lang");
  if (langEl) langEl.textContent = tab.type === "claude" ? "Claude Code" : (tab.language || "plaintext");
  var statusEl = document.getElementById("ide-status-left");
  if (statusEl) statusEl.textContent = tab.type === "claude" ? tab.path : tab.path + (tab.modified ? " (modified)" : "");
  ideRenderTabs();
  ideRenderTree();
}

function ideRenderTabs() {
  var el = document.getElementById("ide-tabs");
  if (!el) return;
  el.innerHTML = _ideTabs.map(function(t, i) {
    // Hide CC tabs from the tab bar when they are displayed in the panel
    if (t.type === "claude" && t.inPanel) return "";
    var active = i === _ideActiveTab ? "active" : "";
    var mod = t.modified ? '<span class="modified">&#9679;</span>' : "";
    var name = t.type === "claude" ? t.path : t.path.split("/").pop();
    var icon = t.type === "claude" ? '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2" style="margin-right:4px;vertical-align:middle"><path d="M4 17l6-6-6-6M12 19h8"/></svg>' : "";
    return '<div class="ide-tab ' + active + '" onclick="_ideActiveTab=' + i + ';ideActivateTab()">' +
      mod + icon + esc(name) +
      '<span class="close" onclick="event.stopPropagation();ideCloseTab(' + i + ')">&times;</span>' +
    '</div>';
  }).join("") +
  '<button class="ide-tab-new-cc" onclick="ideOpenCCChat(\'local\')" title="New Claude Code instance">' +
    '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="#f97316" stroke-width="2"><path d="M4 17l6-6-6-6M12 19h8"/></svg>' +
    '<svg width="10" height="10" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" style="margin-left:2px"><path d="M12 5v14M5 12h14"/></svg>' +
  '</button>';
}

function ideCloseTab(index) {
  var tab = _ideTabs[index];
  if (tab.type === "claude") {
    // Close Claude Code session — clear timer synchronously before DOM removal
    clearInterval(tab.streamTimer);
    tab.streamTimer = null;
    tab.streamMsgEl = null;
    if (tab.ws && tab.ws.readyState <= 1) tab.ws.close();
    if (tab.el) tab.el.remove();
  } else if (tab.type === "diff") {
    if (tab.diffEditor) tab.diffEditor.dispose();
    if (tab.diffOriginalModel) tab.diffOriginalModel.dispose();
    if (tab.diffModifiedModel) tab.diffModifiedModel.dispose();
    if (tab.el) tab.el.remove();
  } else {
    if (tab.modified && !confirm("Discard unsaved changes to " + tab.path + "?")) return;
    if (tab.model) tab.model.dispose();
  }
  _ideTabs.splice(index, 1);
  if (_ideActiveTab >= _ideTabs.length) _ideActiveTab = _ideTabs.length - 1;
  if (_ideTabs.length === 0) {
    _ideActiveTab = -1;
    if (_monacoEditor) _monacoEditor.setModel(null);
    var container = document.getElementById("ide-editor-container");
    var welcome = document.getElementById("ide-welcome");
    var ccContainer = document.getElementById("ide-cc-container");
    if (container) container.style.display = "none";
    if (ccContainer) ccContainer.style.display = "none";
    if (welcome) welcome.style.display = "flex";
  } else {
    ideActivateTab();
  }
  ideRenderTabs();
}

// -- Monaco Diff Editor (LAYOUT-04) -------------------------------------------

function ideOpenDiffTab(filename, originalContent, modifiedContent, language) {
  language = language || ideDetectLanguage(filename) || "plaintext";

  // Create container div inside .ide-main-editor-area
  var editorArea = document.querySelector(".ide-main-editor-area");
  if (!editorArea) {
    var editorContainer = document.getElementById("ide-editor-container");
    if (editorContainer) editorArea = editorContainer.parentNode;
  }
  var diffContainer = document.createElement("div");
  diffContainer.className = "ide-diff-container";
  diffContainer.style.cssText = "flex:1;overflow:hidden;display:none";
  if (editorArea) editorArea.appendChild(diffContainer);

  var origModel = monaco.editor.createModel(originalContent || "", language);
  var modModel = monaco.editor.createModel(modifiedContent || "", language);

  var diffEditor = monaco.editor.createDiffEditor(diffContainer, {
    automaticLayout: true,
    renderSideBySide: true,
    originalEditable: false,
    enableSplitViewResizing: true,
    theme: "agent42-dark"
  });
  diffEditor.setModel({ original: origModel, modified: modModel });
  // Ensure both panes are read-only (Pitfall 3 from research)
  diffEditor.getOriginalEditor().updateOptions({ readOnly: true });
  diffEditor.getModifiedEditor().updateOptions({ readOnly: true });

  var shortName = filename.split("/").pop();
  var tab = {
    type: "diff",
    path: shortName + " \u2194 Changes",
    chatPanel: false,
    diffEditor: diffEditor,
    diffOriginalModel: origModel,
    diffModifiedModel: modModel,
    el: diffContainer,
    modified: false,
  };
  _ideTabs.push(tab);
  _ideActiveTab = _ideTabs.length - 1;
  ideActivateTab();
  ideRenderTabs();
}

function ccOpenDiffFromToolCard(filePath, toolId) {
  if (!filePath) return;

  // Get modified content from the tool card output
  var outputEl = document.querySelector('.cc-tool-output[data-tool-id="' + toolId + '"]');
  var modifiedContent = "";
  if (outputEl) {
    var pre = outputEl.querySelector("pre");
    if (pre) modifiedContent = pre.textContent || "";
  }

  // Fetch original file content from server
  var url = "/api/ide/file?path=" + encodeURIComponent(filePath);
  fetch(url, { headers: { Authorization: "Bearer " + state.token } }).then(function(resp) {
    if (!resp.ok) return Promise.resolve("");
    return resp.text();
  }).then(function(originalContent) {
    // Parse response — the endpoint returns JSON with a content field
    var origText = originalContent || "";
    try {
      var parsed = JSON.parse(origText);
      if (parsed.content !== undefined) origText = parsed.content;
    } catch(e) {
      // Response was plain text, use as-is
    }
    ideOpenDiffTab(filePath, origText, modifiedContent);
  }).catch(function() {
    // New file (original doesn't exist) — show empty original pane
    ideOpenDiffTab(filePath, "", modifiedContent);
  });
}

// -- CC Chat markdown renderer (marked.js + DOMPurify + highlight.js) -----------

var _ccMarkdownReady = false;

function _initCCMarkdown() {
  if (typeof marked === "undefined" || typeof hljs === "undefined"
      || typeof markedHighlight === "undefined" || typeof DOMPurify === "undefined") {
    return false;
  }
  // CDN UMD pattern: markedHighlight global is a namespace; actual function is .markedHighlight
  var mhFn = markedHighlight.markedHighlight;
  marked.use(mhFn({
    emptyLangClass: "hljs",
    langPrefix: "hljs language-",
    highlight: function(code, lang) {
      var language = hljs.getLanguage(lang) ? lang : "plaintext";
      return hljs.highlight(code, { language: language }).value;
    }
  }));
  marked.use({ gfm: true, breaks: false });
  // Enforce rel="noopener noreferrer" on target="_blank" links to prevent tab-napping
  DOMPurify.addHook("afterSanitizeAttributes", function(node) {
    if (node.tagName === "A" && node.getAttribute("target") === "_blank") {
      node.setAttribute("rel", "noopener noreferrer");
    }
  });
  return true;
}

function ccRenderMarkdown(text) {
  if (!_ccMarkdownReady) _ccMarkdownReady = _initCCMarkdown();
  if (!_ccMarkdownReady || !text) return "<p>" + esc(text || "") + "</p>";
  var rawHtml = marked.parse(text);
  // CHAT-05 locked decision: ALL marked output MUST be sanitized via DOMPurify (STATE.md)
  return DOMPurify.sanitize(rawHtml, {
    ALLOWED_TAGS: ["p","br","strong","em","b","i","h1","h2","h3","h4","h5","h6",
                   "ul","ol","li","blockquote","pre","code","a","table","thead",
                   "tbody","tr","th","td","hr","span","div","details","summary"],
    ALLOWED_ATTR: ["href","class","id","target","rel","open"],
  });
}

function ccAppendUserBubble(tab, text) {
  var container = tab.el.querySelector(".cc-chat-messages");
  if (!container) return;
  var now = new Date();
  var time = now.getHours() + ":" + String(now.getMinutes()).padStart(2, "0");
  var wrapper = document.createElement("div");
  wrapper.className = "chat-msg chat-msg-user";
  var content = document.createElement("div");
  content.className = "chat-msg-content";
  var header = document.createElement("div");
  header.className = "chat-msg-header";
  var senderEl = document.createElement("span");
  senderEl.className = "chat-msg-sender";
  senderEl.textContent = "You";
  var timeEl = document.createElement("span");
  timeEl.className = "chat-msg-time";
  timeEl.textContent = time;
  header.appendChild(senderEl);
  header.appendChild(timeEl);
  var body = document.createElement("div");
  body.className = "chat-msg-body chat-msg-body-user";
  body.textContent = text;  // textContent only -- no HTML in user messages
  content.appendChild(header);
  content.appendChild(body);
  var avatar = document.createElement("div");
  avatar.className = "chat-avatar chat-avatar-user";
  avatar.textContent = "U";
  wrapper.appendChild(content);
  wrapper.appendChild(avatar);
  container.appendChild(wrapper);
  if (tab.autoScroll) {
    requestAnimationFrame(function() { container.scrollTop = container.scrollHeight; });
  }
}

function ccAppendThinkingBlock(tab, text) {
  var container = tab.el.querySelector(".cc-chat-messages");
  if (!container) return;
  var block = document.createElement("details");
  block.className = "cc-thinking-block";
  var summary = document.createElement("summary");
  summary.className = "cc-thinking-summary";
  summary.textContent = "Thinking...";
  block.appendChild(summary);
  var content = document.createElement("div");
  content.className = "cc-thinking-content";
  content.textContent = text;  // textContent only -- thinking is unformatted
  block.appendChild(content);
  container.appendChild(block);
}

// --- Claude Code as editor tab ---
var _ccTabCounter = 0;

// -- CC Tool Card Rendering (TOOL-01 through TOOL-05) -------------------------

var _CC_FILE_TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "MultiEdit"];
var _CC_BASH_TOOLS = ["Bash", "bash"];
var _CC_WRITE_TOOLS = ["Write", "Edit", "MultiEdit"];

function ccIsWriteTool(name) {
  return _CC_WRITE_TOOLS.indexOf(name) >= 0;
}

function ccToolType(name) {
  if (_CC_FILE_TOOLS.indexOf(name) >= 0) return "file";
  if (_CC_BASH_TOOLS.indexOf(name) >= 0) return "bash";
  return "generic";
}

function ccCreateToolCard(tab, toolId, toolName) {
  var container = tab.el.querySelector(".cc-chat-messages");
  if (!container) return null;

  // If streaming text bubble in progress, finalize it first
  if (tab.streamMsgEl && tab.streamBuffer) {
    // Render accumulated text via DOMPurify-sanitized markdown
    tab.streamMsgEl.textContent = tab.streamBuffer;
    tab.streamMsgEl.classList.remove("cc-streaming-body");
    tab.streamMsgEl = null;
    tab.streamBuffer = "";
  }

  var card = document.createElement("div");
  card.className = "cc-tool-card cc-tool-running";
  card.setAttribute("data-tool-id", toolId);

  var header = document.createElement("div");
  header.className = "cc-tool-header";
  header.setAttribute("onclick", "ccToggleToolCard(this)");

  var statusIcon = document.createElement("span");
  statusIcon.className = "cc-tool-status-icon";
  statusIcon.textContent = "\u23F3";
  header.appendChild(statusIcon);

  var nameSpan = document.createElement("span");
  nameSpan.className = "cc-tool-name";
  nameSpan.textContent = toolName;
  header.appendChild(nameSpan);

  var targetSpan = document.createElement("span");
  targetSpan.className = "cc-tool-target";
  targetSpan.textContent = "";
  header.appendChild(targetSpan);

  var chevron = document.createElement("span");
  chevron.className = "cc-tool-chevron";
  chevron.textContent = "\u25B6";
  header.appendChild(chevron);

  card.appendChild(header);

  var body = document.createElement("div");
  body.className = "cc-tool-body";
  body.style.display = "none";
  card.appendChild(body);

  container.appendChild(card);

  if (tab.autoScroll) {
    requestAnimationFrame(function() { container.scrollTop = container.scrollHeight; });
  }

  return card;
}

function ccToggleToolCard(headerEl) {
  var card = headerEl.parentElement;
  if (!card) return;
  var body = card.querySelector(".cc-tool-body");
  if (!body) return;
  var chevron = card.querySelector(".cc-tool-chevron");
  if (body.style.display === "none") {
    body.style.display = "block";
    if (chevron) chevron.textContent = "\u25BC";
  } else {
    body.style.display = "none";
    if (chevron) chevron.textContent = "\u25B6";
  }
}

function ccFinalizeToolCard(cardEl, toolName, parsedInput, isError) {
  if (!cardEl) return;
  var ttype = ccToolType(toolName);

  cardEl.classList.remove("cc-tool-running");
  cardEl.classList.add(isError ? "cc-tool-error" : "cc-tool-complete");

  var icon = cardEl.querySelector(".cc-tool-status-icon");
  if (icon) icon.textContent = isError ? "\u274C" : "\u2705";

  var targetSpan = cardEl.querySelector(".cc-tool-target");
  if (targetSpan) {
    if (ttype === "file") {
      targetSpan.textContent = parsedInput.file_path || parsedInput.path || parsedInput.pattern || "";
    } else if (ttype === "bash") {
      var cmd = parsedInput.command || "";
      targetSpan.textContent = cmd.length > 60 ? cmd.substring(0, 57) + "..." : cmd;
    }
  }

  var body = cardEl.querySelector(".cc-tool-body");
  if (!body) return;

  var inputSection = document.createElement("div");
  inputSection.className = "cc-tool-input";
  var inputLabel = document.createElement("div");
  inputLabel.className = "cc-tool-section-label";
  inputLabel.textContent = "Input";
  inputSection.appendChild(inputLabel);

  if (ttype === "bash") {
    var cmdPre = document.createElement("pre");
    cmdPre.className = "cc-tool-bash";
    var cmdCode = document.createElement("code");
    cmdCode.textContent = parsedInput.command || JSON.stringify(parsedInput, null, 2);
    cmdPre.appendChild(cmdCode);
    inputSection.appendChild(cmdPre);
  } else if (ttype === "file") {
    var pathDiv = document.createElement("div");
    pathDiv.className = "cc-tool-file-path";
    pathDiv.textContent = parsedInput.file_path || parsedInput.path || parsedInput.pattern || "";
    inputSection.appendChild(pathDiv);
    var otherKeys = Object.keys(parsedInput).filter(function(k) {
      return k !== "file_path" && k !== "path";
    });
    if (otherKeys.length > 0) {
      var paramPre = document.createElement("pre");
      paramPre.className = "cc-tool-params";
      var filtered = {};
      otherKeys.forEach(function(k) { filtered[k] = parsedInput[k]; });
      paramPre.textContent = JSON.stringify(filtered, null, 2);
      inputSection.appendChild(paramPre);
    }
  } else {
    var paramPre2 = document.createElement("pre");
    paramPre2.className = "cc-tool-params";
    paramPre2.textContent = JSON.stringify(parsedInput, null, 2);
    inputSection.appendChild(paramPre2);
  }

  body.appendChild(inputSection);

  // Action buttons for Write/Edit tool cards (LAYOUT-04)
  if (ccIsWriteTool(toolName) && !isError) {
    var actionsDiv = document.createElement("div");
    actionsDiv.className = "cc-tool-actions";

    var filePath = parsedInput.file_path || parsedInput.path || "";
    var cardToolId = cardEl.getAttribute("data-tool-id");

    var viewDiffBtn = document.createElement("button");
    viewDiffBtn.className = "cc-tool-action-btn cc-tool-diff-btn";
    viewDiffBtn.textContent = "View Diff";
    viewDiffBtn.setAttribute("data-filepath", filePath);
    viewDiffBtn.setAttribute("data-tool-id", cardToolId);
    viewDiffBtn.addEventListener("click", function() {
      ccOpenDiffFromToolCard(this.getAttribute("data-filepath"), this.getAttribute("data-tool-id"));
    });
    actionsDiv.appendChild(viewDiffBtn);

    var openFileBtn = document.createElement("button");
    openFileBtn.className = "cc-tool-action-btn";
    openFileBtn.textContent = "Open File";
    openFileBtn.addEventListener("click", function() {
      ideOpenFile(filePath);
    });
    actionsDiv.appendChild(openFileBtn);

    body.appendChild(actionsDiv);
  }

  var outputSection = document.createElement("div");
  outputSection.className = "cc-tool-output";
  outputSection.setAttribute("data-tool-id", cardEl.getAttribute("data-tool-id"));
  body.appendChild(outputSection);
}

function ccSetToolOutput(toolId, content, contentType) {
  var outputEl = document.querySelector('.cc-tool-output[data-tool-id="' + toolId + '"]');
  if (!outputEl) return;

  var outputLabel = document.createElement("div");
  outputLabel.className = "cc-tool-section-label";
  outputLabel.textContent = "Output";
  outputEl.appendChild(outputLabel);

  var card = outputEl.closest(".cc-tool-card");
  var toolName = "";
  if (card) {
    var nameEl = card.querySelector(".cc-tool-name");
    if (nameEl) toolName = nameEl.textContent;
  }
  var ttype = ccToolType(toolName);

  var pre = document.createElement("pre");
  pre.className = ttype === "bash" ? "cc-tool-bash cc-tool-output-content" : "cc-tool-output-content";

  var maxLines = ttype === "bash" ? 20 : 30;
  var lines = (content || "").split("\n");
  var truncated = lines.length > maxLines;
  var displayContent = truncated ? lines.slice(0, maxLines).join("\n") : content;

  if (ttype === "file" && contentType === "text") {
    // Syntax highlight via hljs, then sanitize via DOMPurify (CHAT-05 pattern)
    try {
      var highlighted = hljs.highlightAuto(displayContent);
      var sanitized = DOMPurify.sanitize(highlighted.value);
      pre.insertAdjacentHTML("afterbegin", sanitized);
    } catch(e) {
      pre.textContent = displayContent;
    }
  } else {
    pre.textContent = displayContent;
  }

  outputEl.appendChild(pre);

  if (truncated) {
    var showMore = document.createElement("button");
    showMore.className = "cc-tool-show-more";
    showMore.textContent = "Show " + (lines.length - maxLines) + " more lines";
    showMore.addEventListener("click", function() {
      if (ttype === "file") {
        try {
          var fullH = hljs.highlightAuto(content);
          var fullSanitized = DOMPurify.sanitize(fullH.value);
          pre.textContent = "";
          pre.insertAdjacentHTML("afterbegin", fullSanitized);
        } catch(e2) {
          pre.textContent = content;
        }
      } else {
        pre.textContent = content;
      }
      showMore.style.display = "none";
    });
    outputEl.appendChild(showMore);
  }
}

// -- CC Permission Request UI (TOOL-06) --------------------------------------

function ccCreatePermissionCard(tab, permId, toolInput) {
  var container = tab.el.querySelector(".cc-chat-messages");
  if (!container) return;

  // Auto-approve in trust mode
  if (tab.trustMode && tab.ws && tab.ws.readyState === 1) {
    tab.ws.send(JSON.stringify({ type: "permission_response", id: permId, approved: true }));
    // Show brief auto-approved notice
    var notice = document.createElement("div");
    notice.className = "cc-perm-auto-approved";
    notice.textContent = "\u2705 Auto-approved (trust mode)";
    container.appendChild(notice);
    return;
  }

  var card = document.createElement("div");
  card.className = "cc-perm-card";
  card.id = "cc-perm-" + permId;

  var label = document.createElement("div");
  label.className = "cc-perm-label";
  label.textContent = "\uD83D\uDD12 Permission Required";
  card.appendChild(label);

  var desc = document.createElement("div");
  desc.className = "cc-perm-desc";
  // toolInput may contain tool_name and description from CC
  var toolName = (toolInput && toolInput.tool_name) || "a tool";
  var target = (toolInput && (toolInput.file_path || toolInput.command || toolInput.description)) || "";
  desc.textContent = "Claude Code wants to use " + toolName + (target ? ": " + target : "");
  card.appendChild(desc);

  var actions = document.createElement("div");
  actions.className = "cc-perm-actions";

  var approveBtn = document.createElement("button");
  approveBtn.className = "cc-perm-approve";
  approveBtn.textContent = "Approve";
  approveBtn.setAttribute("data-perm-id", permId);
  approveBtn.addEventListener("click", function() {
    ccResolvePermission(tab, permId, true);
  });
  actions.appendChild(approveBtn);

  var rejectBtn = document.createElement("button");
  rejectBtn.className = "cc-perm-reject";
  rejectBtn.textContent = "Reject";
  rejectBtn.setAttribute("data-perm-id", permId);
  rejectBtn.addEventListener("click", function() {
    ccResolvePermission(tab, permId, false);
  });
  actions.appendChild(rejectBtn);

  card.appendChild(actions);
  container.appendChild(card);

  if (tab.autoScroll) {
    requestAnimationFrame(function() { container.scrollTop = container.scrollHeight; });
  }
}

function ccResolvePermission(tab, permId, approved) {
  if (!tab.ws || tab.ws.readyState !== 1) return;
  tab.ws.send(JSON.stringify({ type: "permission_response", id: permId, approved: approved }));

  // Update card UI to show resolved state
  var card = document.getElementById("cc-perm-" + permId);
  if (card) {
    card.classList.add(approved ? "cc-perm-approved" : "cc-perm-rejected");
    var actions = card.querySelector(".cc-perm-actions");
    if (actions) actions.style.display = "none";
    var result = document.createElement("div");
    result.className = "cc-perm-result";
    result.textContent = approved ? "\u2705 Approved" : "\u274C Rejected";
    card.appendChild(result);
  }
}

function ccToggleTrustMode(tabIdx) {
  var tab = ccGetTab(tabIdx);
  if (!tab) return;
  tab.trustMode = !tab.trustMode;
  if (tab.ws && tab.ws.readyState === 1) {
    tab.ws.send(JSON.stringify({ type: "trust_mode", enabled: tab.trustMode }));
  }
  var indicator = document.getElementById("cc-trust-indicator-" + tabIdx);
  if (indicator) {
    indicator.textContent = tab.trustMode ? "\uD83D\uDD13 Trust mode ON" : "";
    indicator.style.display = tab.trustMode ? "inline-block" : "none";
  }
  var toggle = document.getElementById("cc-trust-toggle-" + tabIdx);
  if (toggle) {
    toggle.textContent = tab.trustMode ? "Disable Trust" : "Trust Mode";
    toggle.classList.toggle("cc-trust-active", tab.trustMode);
  }
}

// -- CC WS Message Handler Factory (shared by ideOpenCCChat + ccResumeSession) --

function ccMakeWsHandler(tab, msgs) {
  return function(ev) {
    var data;
    try { data = JSON.parse(ev.data); } catch(e) { return; }
    var msgType = data.type;
    var msgData = data.data || {};

    if (msgType === "tool_start") {
      var card = ccCreateToolCard(tab, msgData.id, msgData.name);
      tab.toolCards[msgData.id] = { el: card, inputBuf: "", name: msgData.name, status: "running" };

    } else if (msgType === "tool_delta") {
      var tc = tab.toolCards[msgData.id];
      if (tc) { tc.inputBuf += (msgData.partial || ""); }

    } else if (msgType === "tool_complete") {
      var tc2 = tab.toolCards[msgData.id];
      if (tc2) {
        var parsed = {};
        try { parsed = JSON.parse(tc2.inputBuf); } catch(e) {}
        ccFinalizeToolCard(tc2.el, tc2.name || msgData.name, parsed, msgData.is_error);
        tc2.status = msgData.is_error ? "error" : "complete";
      }

    } else if (msgType === "tool_output") {
      ccSetToolOutput(msgData.id, msgData.content, msgData.content_type);

    } else if (msgType === "permission_request") {
      // Backend emits permission_request at content_block_stop with fully parsed input
      // (no need to look up tab.toolCards — backend buffers input_json_delta internally)
      ccCreatePermissionCard(tab, msgData.id, msgData.input || {});

    } else if (msgType === "text_delta") {
      var deltaText = (msgData.text || "");
      if (!tab.streamMsgEl) {
        var now2 = new Date();
        var time2 = now2.getHours() + ":" + String(now2.getMinutes()).padStart(2, "0");
        var msgWrapper = document.createElement("div");
        msgWrapper.className = "chat-msg chat-msg-agent";
        var avatarEl = document.createElement("div");
        avatarEl.className = "chat-avatar chat-avatar-agent";
        avatarEl.textContent = "CC";
        msgWrapper.appendChild(avatarEl);
        var msgContent = document.createElement("div");
        msgContent.className = "chat-msg-content";
        var msgHeader = document.createElement("div");
        msgHeader.className = "chat-msg-header";
        var senderSpan = document.createElement("span");
        senderSpan.className = "chat-msg-sender";
        senderSpan.textContent = "Claude Code";
        var timeSpan = document.createElement("span");
        timeSpan.className = "chat-msg-time";
        timeSpan.textContent = time2;
        msgHeader.appendChild(senderSpan);
        msgHeader.appendChild(timeSpan);
        msgContent.appendChild(msgHeader);
        var bodyEl = document.createElement("div");
        bodyEl.className = "chat-msg-body chat-msg-body-agent cc-streaming-body";
        msgContent.appendChild(bodyEl);
        msgWrapper.appendChild(msgContent);
        if (msgs) msgs.appendChild(msgWrapper);
        tab.streamMsgEl = bodyEl;
        tab.streamTimer = setInterval(function() {
          if (tab.streamMsgEl) tab.streamMsgEl.textContent = tab.streamBuffer;
          if (tab.autoScroll && msgs) requestAnimationFrame(function() {
            msgs.scrollTop = msgs.scrollHeight;
          });
        }, 50);
      }
      tab.streamBuffer += deltaText;

    } else if (msgType === "turn_complete") {
      clearInterval(tab.streamTimer);
      tab.streamTimer = null;
      var finalEl = tab.streamMsgEl;
      var finalBuf = tab.streamBuffer;
      tab.streamMsgEl = null;
      tab.streamBuffer = "";
      tab.toolCards = {};
      if (finalEl && finalBuf) {
        var rendered = ccRenderMarkdown(finalBuf);
        finalEl.textContent = "";
        finalEl.insertAdjacentHTML("afterbegin", DOMPurify.sanitize(rendered));
        finalEl.classList.remove("cc-streaming-body");
      }
      // SESS-06: accumulate token usage
      tab.totalInputTokens += (msgData.input_tokens || 0);
      tab.totalOutputTokens += (msgData.output_tokens || 0);
      tab.totalCostUsd += (msgData.cost_usd || 0);
      ccUpdateTokenBar(tab);
      ccSetSendingState(tab, false);
      if (tab.autoScroll && msgs) requestAnimationFrame(function() {
        msgs.scrollTop = msgs.scrollHeight;
      });

    } else if (msgType === "thinking_complete") {
      ccAppendThinkingBlock(tab, msgData.text || "");

    } else if (msgType === "error") {
      clearInterval(tab.streamTimer);
      tab.streamTimer = null;
      tab.streamBuffer = "";
      tab.streamMsgEl = null;
      ccSetSendingState(tab, false);
      var errDiv = document.createElement("div");
      errDiv.style.cssText = "color:var(--danger,#ef4444);padding:0.5rem;font-size:0.85rem";
      errDiv.textContent = "Error: " + (msgData.message || "Unknown error");
      if (msgs) msgs.appendChild(errDiv);

    } else if (msgType === "status") {
      var statusDiv = document.createElement("div");
      statusDiv.style.cssText = "color:var(--text-muted);font-size:0.78rem;padding:0.25rem 0;text-align:center;font-style:italic";
      statusDiv.textContent = msgData.message || "";
      if (msgs) msgs.appendChild(statusDiv);
    }
  };
}

// -- CC Session Management (SESS-01 through SESS-06) --------------------------

function ccGetStoredSessionId() {
  try { return sessionStorage.getItem("cc_active_session") || ""; } catch(e) { return ""; }
}

function ccStoreSessionId(sessionId) {
  try { sessionStorage.setItem("cc_active_session", sessionId); } catch(e) {}
}

function ccRelativeTime(isoString) {
  if (!isoString) return "";
  var now = Date.now();
  var then = new Date(isoString).getTime();
  var diff = Math.floor((now - then) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  if (diff < 172800) return "yesterday";
  return Math.floor(diff / 86400) + "d ago";
}

function ccFormatTokens(n) {
  if (typeof n !== "number" || isNaN(n)) return "0";
  return n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(n);
}

function ccUpdateTokenBar(tab) {
  var bar = document.getElementById("cc-token-bar-" + tab.tabIdx);
  if (!bar) return;
  bar.textContent = "In: " + ccFormatTokens(tab.totalInputTokens)
    + "  Out: " + ccFormatTokens(tab.totalOutputTokens)
    + "  Cost: $" + (tab.totalCostUsd || 0).toFixed(4);
}

function ccLoadSessionSidebar(tab) {
  var sidebar = document.getElementById("cc-session-sidebar-" + tab.tabIdx);
  if (!sidebar) return;
  var listEl = sidebar.querySelector(".cc-session-list");
  if (!listEl) return;

  fetch("/api/cc/sessions", {
    headers: { "Authorization": "Bearer " + (state.token || "") }
  })
  .then(function(resp) { return resp.json(); })
  .then(function(data) {
    var sessions = (data.sessions || []).sort(function(a, b) {
      return (b.last_active_at || "").localeCompare(a.last_active_at || "");
    });

    while (listEl.firstChild) listEl.removeChild(listEl.firstChild);

    var now = new Date();
    var todayStr = now.toISOString().slice(0, 10);
    var yesterday = new Date(now.getTime() - 86400000);
    var yesterdayStr = yesterday.toISOString().slice(0, 10);

    var groups = { "Today": [], "Yesterday": [], "Older": [] };
    sessions.forEach(function(s) {
      var dateStr = (s.last_active_at || "").slice(0, 10);
      if (dateStr === todayStr) groups["Today"].push(s);
      else if (dateStr === yesterdayStr) groups["Yesterday"].push(s);
      else groups["Older"].push(s);
    });

    ["Today", "Yesterday", "Older"].forEach(function(groupName) {
      var items = groups[groupName];
      if (items.length === 0) return;

      var groupLabel = document.createElement("div");
      groupLabel.className = "cc-session-group-label";
      groupLabel.textContent = groupName;
      listEl.appendChild(groupLabel);

      items.forEach(function(s) {
        var entry = document.createElement("div");
        entry.className = "cc-session-entry";
        entry.setAttribute("data-session-id", s.ws_session_id || "");

        var title = document.createElement("div");
        title.className = "cc-session-title";
        title.textContent = (s.title || "Untitled").substring(0, 30);
        entry.appendChild(title);

        var meta = document.createElement("div");
        meta.className = "cc-session-meta";
        meta.textContent = ccRelativeTime(s.last_active_at)
          + (s.message_count ? " \u00B7 " + s.message_count + " msgs" : "");
        entry.appendChild(meta);

        if (s.preview_text) {
          var preview = document.createElement("div");
          preview.className = "cc-session-preview";
          preview.textContent = s.preview_text.substring(0, 60);
          entry.appendChild(preview);
        }

        entry.addEventListener("click", function() {
          ccResumeSession(tab, s.ws_session_id, s.title || "Untitled");
        });

        listEl.appendChild(entry);
      });
    });

    if (sessions.length === 0) {
      var empty = document.createElement("div");
      empty.className = "cc-session-empty";
      empty.textContent = "No past sessions";
      listEl.appendChild(empty);
    }
  })
  .catch(function(err) {
    console.error("Failed to load CC sessions:", err);
  });
}

function ccResumeSession(tab, wsSessionId, title) {
  if (!wsSessionId) return;

  if (tab.ws && tab.ws.readyState <= 1) {
    tab.ws.close();
  }

  tab.ccSessionId = wsSessionId;
  ccStoreSessionId(wsSessionId);

  var msgs = tab.el.querySelector(".cc-chat-messages");
  if (msgs) { while (msgs.firstChild) msgs.removeChild(msgs.firstChild); }

  var notice = document.createElement("div");
  notice.style.cssText = "color:var(--success,#22c55e);font-size:0.8rem;padding:0.5rem 0;text-align:center";
  notice.textContent = "Session resumed: " + title;
  if (msgs) msgs.appendChild(notice);

  tab.totalInputTokens = 0;
  tab.totalOutputTokens = 0;
  tab.totalCostUsd = 0;
  ccUpdateTokenBar(tab);

  var protocol = location.protocol === "https:" ? "wss:" : "ws:";
  var wsUrl = protocol + "//" + location.host + "/ws/cc-chat?token="
    + encodeURIComponent(state.token) + "&session_id=" + encodeURIComponent(wsSessionId);
  var ws = new WebSocket(wsUrl);
  tab.ws = ws;

  // Reuse the shared WS handler factory (defined in Plan 03-03)
  // This prevents handler duplication -- any changes to ccMakeWsHandler
  // automatically apply to both ideOpenCCChat and ccResumeSession
  ws.onmessage = ccMakeWsHandler(tab, msgs);

  ws.onopen = function() {
    var connNotice = document.createElement("div");
    connNotice.style.cssText = "color:var(--text-muted);font-size:0.8rem;padding:0.5rem 0;text-align:center";
    connNotice.textContent = "Claude Code reconnected";
    if (msgs) msgs.appendChild(connNotice);
  };

  ws.onclose = function() {
    clearInterval(tab.streamTimer);
    tab.streamTimer = null;
    if (tab.streamMsgEl && tab.streamBuffer) {
      tab.streamMsgEl.textContent = tab.streamBuffer;
      tab.streamMsgEl.classList.remove("cc-streaming-body");
      tab.streamBuffer = "";
      tab.streamMsgEl = null;
    }
    ccSetSendingState(tab, false);
  };

  ws.onerror = function() {
    var errDiv = document.createElement("div");
    errDiv.style.cssText = "color:var(--danger,#ef4444);padding:0.5rem;font-size:0.85rem";
    errDiv.textContent = "WebSocket connection error";
    if (msgs) msgs.appendChild(errDiv);
  };
}

function ccToggleSessionSidebar(tabIdx) {
  var sidebar = document.getElementById("cc-session-sidebar-" + tabIdx);
  if (!sidebar) return;
  var visible = sidebar.style.display !== "none";
  sidebar.style.display = visible ? "none" : "block";
  if (!visible) {
    var tab = ccGetTab(tabIdx);
    if (tab) ccLoadSessionSidebar(tab);
  }
}

function ideOpenCCChat(node) {
  node = node || "local";
  _ccTabCounter++;
  var tabIdx = _ccTabCounter;
  var label = "Claude Code" + (tabIdx > 1 ? " " + tabIdx : "");
  var ccContainer = document.getElementById("ide-cc-container");
  if (!ccContainer) return;

  // SESS-01/02: restore session from sessionStorage on page refresh
  var storedSession = ccGetStoredSessionId();
  var sessionResumed = false;
  var sessionId;
  if (storedSession && _ccTabCounter === 1) {
    sessionId = storedSession;
    sessionResumed = true;
  } else {
    sessionId = (typeof crypto !== "undefined" && crypto.randomUUID)
      ? crypto.randomUUID()
      : Math.random().toString(36).slice(2) + Date.now().toString(36);
  }
  ccStoreSessionId(sessionId);

  // Build chat panel DOM using safe DOM methods
  var chatDiv = document.createElement("div");
  chatDiv.className = "ide-cc-chat";
  chatDiv.id = "cc-chat-" + tabIdx;

  var header = document.createElement("div");
  header.className = "cc-chat-header";
  var headerLabel = document.createElement("span");
  headerLabel.textContent = "Claude Code";
  header.appendChild(headerLabel);

  var historyBtn = document.createElement("button");
  historyBtn.className = "cc-history-btn";
  historyBtn.textContent = "\uD83D\uDCCB";
  historyBtn.title = "Session History";
  historyBtn.setAttribute("onclick", "ccToggleSessionSidebar(" + tabIdx + ")");
  header.appendChild(historyBtn);

  var trustToggle = document.createElement("button");
  trustToggle.className = "cc-trust-toggle";
  trustToggle.id = "cc-trust-toggle-" + tabIdx;
  trustToggle.textContent = "Trust Mode";
  trustToggle.setAttribute("onclick", "ccToggleTrustMode(" + tabIdx + ")");
  header.appendChild(trustToggle);

  var trustIndicator = document.createElement("span");
  trustIndicator.className = "cc-trust-indicator";
  trustIndicator.id = "cc-trust-indicator-" + tabIdx;
  trustIndicator.style.display = "none";
  header.appendChild(trustIndicator);

  chatDiv.appendChild(header);

  // SESS-03: session tab strip
  var tabStrip = document.createElement("div");
  tabStrip.className = "cc-tab-strip";
  tabStrip.id = "cc-tab-strip-" + tabIdx;
  var sessionTab = document.createElement("div");
  sessionTab.className = "cc-session-tab cc-session-tab-active";
  sessionTab.textContent = label;
  tabStrip.appendChild(sessionTab);
  var tabAddBtn = document.createElement("button");
  tabAddBtn.className = "cc-tab-add";
  tabAddBtn.textContent = "+";
  tabAddBtn.title = "New session";
  tabAddBtn.setAttribute("onclick", "ideOpenCCChat('local')");
  tabStrip.appendChild(tabAddBtn);
  chatDiv.appendChild(tabStrip);

  // SESS-06: token usage bar
  var tokenBar = document.createElement("div");
  tokenBar.className = "cc-token-bar";
  tokenBar.id = "cc-token-bar-" + tabIdx;
  tokenBar.textContent = "In: 0  Out: 0  Cost: $0.0000";
  chatDiv.appendChild(tokenBar);

  // SESS-04/05: session history sidebar (hidden by default)
  var sessionSidebar = document.createElement("div");
  sessionSidebar.className = "cc-session-sidebar";
  sessionSidebar.id = "cc-session-sidebar-" + tabIdx;
  sessionSidebar.style.display = "none";
  var sidebarHeader = document.createElement("div");
  sidebarHeader.className = "cc-session-sidebar-header";
  sidebarHeader.textContent = "Session History";
  sessionSidebar.appendChild(sidebarHeader);
  var sessionList = document.createElement("div");
  sessionList.className = "cc-session-list";
  sessionSidebar.appendChild(sessionList);
  chatDiv.appendChild(sessionSidebar);

  var messagesDiv = document.createElement("div");
  messagesDiv.className = "cc-chat-messages";
  messagesDiv.id = "cc-msgs-" + tabIdx;
  chatDiv.appendChild(messagesDiv);

  var scrollAnchor = document.createElement("div");
  scrollAnchor.className = "cc-chat-scroll-anchor";
  scrollAnchor.id = "cc-scroll-anchor-" + tabIdx;
  scrollAnchor.style.display = "none";
  var scrollBtn = document.createElement("button");
  scrollBtn.className = "cc-scroll-btn";
  scrollBtn.textContent = "\u2193 scroll to bottom";
  scrollBtn.setAttribute("onclick", "ccScrollToBottom(" + tabIdx + ")");
  scrollAnchor.appendChild(scrollBtn);
  chatDiv.appendChild(scrollAnchor);

  var composer = document.createElement("div");
  composer.className = "cc-chat-composer";

  var slashDropdown = document.createElement("div");
  slashDropdown.className = "cc-slash-dropdown";
  slashDropdown.id = "cc-slash-" + tabIdx;
  slashDropdown.style.display = "none";
  composer.appendChild(slashDropdown);

  var textarea = document.createElement("textarea");
  textarea.className = "cc-chat-input";
  textarea.id = "cc-input-" + tabIdx;
  textarea.rows = 1;
  textarea.placeholder = "Message Claude Code... (Enter to send, Shift+Enter for newline)";
  textarea.setAttribute("oninput", "ccInputResize(this);ccUpdateSlashDropdown(ccGetTab(" + tabIdx + "))");
  textarea.setAttribute("onkeydown", "ccHandleKeydown(event," + tabIdx + ")");
  composer.appendChild(textarea);

  var sendBtn = document.createElement("button");
  sendBtn.className = "cc-send-btn";
  sendBtn.id = "cc-send-" + tabIdx;
  sendBtn.textContent = "Send";
  sendBtn.setAttribute("onclick", "ccSend(" + tabIdx + ")");
  composer.appendChild(sendBtn);

  var stopBtn = document.createElement("button");
  stopBtn.className = "cc-stop-btn";
  stopBtn.id = "cc-stop-" + tabIdx;
  stopBtn.textContent = "Stop";
  stopBtn.style.display = "none";
  stopBtn.setAttribute("onclick", "ccStop(" + tabIdx + ")");
  composer.appendChild(stopBtn);

  chatDiv.appendChild(composer);
  ccContainer.appendChild(chatDiv);

  var tab = {
    type: "claude",
    path: label,
    chatPanel: true,
    el: chatDiv,
    ws: null,
    node: node,
    tabIdx: tabIdx,
    sending: false,
    autoScroll: true,
    streamBuffer: "",
    streamMsgEl: null,
    streamTimer: null,
    ccSessionId: sessionId,
    _scrollListenerAttached: false,
    toolCards: {},  // Map of tool_id to {el, inputBuf, name, status}
    trustMode: false,
    totalInputTokens: 0,
    totalOutputTokens: 0,
    totalCostUsd: 0,
  };
  _ideTabs.push(tab);
  _ideActiveTab = _ideTabs.length - 1;

  ccSetupScrollBehavior(tab);

  var protocol = location.protocol === "https:" ? "wss:" : "ws:";
  var wsUrl = protocol + "//" + location.host + "/ws/cc-chat?token="
    + encodeURIComponent(state.token) + "&session_id=" + encodeURIComponent(sessionId);

  // Guard against duplicate WS (Pitfall 6)
  if (tab.ws && tab.ws.readyState <= 1) { ideActivateTab(); return; }

  var ws = new WebSocket(wsUrl);
  tab.ws = ws;

  ws.onopen = function() {
    var notice = document.createElement("div");
    notice.style.cssText = "color:var(--text-muted);font-size:0.8rem;padding:0.5rem 0;text-align:center";
    notice.textContent = "Claude Code connected";
    messagesDiv.appendChild(notice);
    if (sessionResumed) {
      var resumeNotice = document.createElement("div");
      resumeNotice.style.cssText = "color:var(--success,#22c55e);font-size:0.8rem;padding:0.5rem 0;text-align:center";
      resumeNotice.textContent = "Session resumed \u2014 context preserved";
      messagesDiv.appendChild(resumeNotice);
    }
  };

  ws.onmessage = ccMakeWsHandler(tab, messagesDiv);

  ws.onclose = function() {
    clearInterval(tab.streamTimer);
    tab.streamTimer = null;
    if (tab.streamMsgEl && tab.streamBuffer) {
      // Safe: ccRenderMarkdown always returns DOMPurify.sanitize() output
      tab.streamMsgEl.innerHTML = ccRenderMarkdown(tab.streamBuffer);
      tab.streamMsgEl.classList.remove("cc-streaming-body");
      tab.streamBuffer = "";
      tab.streamMsgEl = null;
    }
    ccSetSendingState(tab, false);
  };

  ws.onerror = function() {
    var errDiv = document.createElement("div");
    errDiv.style.cssText = "color:var(--danger,#ef4444);padding:0.5rem;font-size:0.85rem";
    errDiv.textContent = "WebSocket connection error";
    messagesDiv.appendChild(errDiv);
  };

  ideActivateTab();
}

function ccGetTab(tabIdx) {
  for (var i = 0; i < _ideTabs.length; i++) {
    if (_ideTabs[i].tabIdx === tabIdx) return _ideTabs[i];
  }
  return null;
}

function ccSetSendingState(tab, sending) {
  tab.sending = sending;
  var sendBtn = document.getElementById("cc-send-" + tab.tabIdx);
  var stopBtn2 = document.getElementById("cc-stop-" + tab.tabIdx);
  if (sendBtn) sendBtn.style.display = sending ? "none" : "inline-block";
  if (stopBtn2) stopBtn2.style.display = sending ? "inline-block" : "none";
}

function ccScrollToBottom(tabIdx) {
  var tab = ccGetTab(tabIdx);
  if (!tab) return;
  var msgs = document.getElementById("cc-msgs-" + tabIdx);
  if (msgs) requestAnimationFrame(function() { msgs.scrollTop = msgs.scrollHeight; });
  tab.autoScroll = true;
  var anchor = document.getElementById("cc-scroll-anchor-" + tabIdx);
  if (anchor) anchor.style.display = "none";
}

function ccSetupScrollBehavior(tab) {
  if (tab._scrollListenerAttached) return;
  tab._scrollListenerAttached = true;
  var tabIdx = tab.tabIdx;
  setTimeout(function() {
    var msgs = document.getElementById("cc-msgs-" + tabIdx);
    var anchor = document.getElementById("cc-scroll-anchor-" + tabIdx);
    if (!msgs) return;
    msgs.addEventListener("scroll", function() {
      var atBottom = msgs.scrollTop + msgs.clientHeight >= msgs.scrollHeight - 40;
      tab.autoScroll = atBottom;
      if (anchor) anchor.style.display = atBottom ? "none" : "block";
    });
  }, 100);
}

// -- CC Chat Input Controls --------------------------------------------------

var CC_INPUT_MAX_HEIGHT = 200; // px (INPUT-03)

var CC_SLASH_COMMANDS = [
  { cmd: "/help",    desc: "Show available commands" },
  { cmd: "/clear",   desc: "Clear current chat display" },
  { cmd: "/compact", desc: "Compact conversation context" },
];

function ccSend(tabIdx) {
  var tab = ccGetTab(tabIdx);
  var input = document.getElementById("cc-input-" + tabIdx);
  if (!tab || !input || tab.sending) return;
  var text = input.value.trim();
  if (!text) return;

  // /clear handled locally without sending to CC backend
  if (text === "/clear") {
    var msgs = tab.el.querySelector(".cc-chat-messages");
    if (msgs) { while (msgs.firstChild) msgs.removeChild(msgs.firstChild); }
    input.value = "";
    ccInputResize(input);
    return;
  }

  if (!tab.ws || tab.ws.readyState !== 1) {
    var errDiv = document.createElement("div");
    errDiv.style.cssText = "color:var(--danger,#ef4444);padding:0.5rem;font-size:0.85rem";
    errDiv.textContent = "Not connected. Please wait or reload.";
    tab.el.querySelector(".cc-chat-messages").appendChild(errDiv);
    return;
  }
  ccAppendUserBubble(tab, text);  // CHAT-01: immediate user bubble before send
  tab.ws.send(JSON.stringify({ message: text }));
  ccSetSendingState(tab, true);
  input.value = "";
  ccInputResize(input);
  var dropdown = document.getElementById("cc-slash-" + tabIdx);
  if (dropdown) dropdown.style.display = "none";
}

function ccStop(tabIdx) {
  var tab = ccGetTab(tabIdx);
  if (!tab || !tab.ws || tab.ws.readyState !== 1) return;
  // Backend handles {"type":"stop"} via asyncio.wait() concurrent receive (Plan 02-02)
  tab.ws.send(JSON.stringify({ type: "stop" }));
  // Backend emits turn_complete after proc.terminate() -- ccSetSendingState called there
}

function ccHandleKeydown(event, tabIdx) {
  // INPUT-01: Enter sends; Shift+Enter inserts newline natively
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    ccSend(tabIdx);
  }
}

function ccInputResize(textarea) {
  // INPUT-03: scrollHeight auto-resize pattern (CSS-Tricks standard)
  textarea.style.height = "auto";
  textarea.style.height = Math.min(textarea.scrollHeight, CC_INPUT_MAX_HEIGHT) + "px";
}

function ccUpdateSlashDropdown(tab) {
  // INPUT-04: show filtered slash command dropdown when input starts with "/"
  if (!tab) return;
  var input = document.getElementById("cc-input-" + tab.tabIdx);
  var dropdown = document.getElementById("cc-slash-" + tab.tabIdx);
  if (!input || !dropdown) return;

  var val = input.value;
  if (!val.startsWith("/") || val.includes(" ")) {
    dropdown.style.display = "none";
    return;
  }

  var filter = val.toLowerCase();
  var matches = CC_SLASH_COMMANDS.filter(function(c) {
    return c.cmd.startsWith(filter);
  });

  if (matches.length === 0) { dropdown.style.display = "none"; return; }

  // Rebuild dropdown with safe DOM methods (textContent only, no innerHTML with user data)
  while (dropdown.firstChild) dropdown.removeChild(dropdown.firstChild);
  matches.forEach(function(c) {
    var item = document.createElement("div");
    item.className = "cc-slash-item";
    item.dataset.cmd = c.cmd;
    var cmdSpan = document.createElement("span");
    cmdSpan.className = "cc-slash-cmd";
    cmdSpan.textContent = c.cmd;
    var descSpan = document.createElement("span");
    descSpan.className = "cc-slash-desc";
    descSpan.textContent = c.desc;
    item.appendChild(cmdSpan);
    item.appendChild(descSpan);
    item.addEventListener("click", function() {
      if (input) { input.value = c.cmd + " "; ccInputResize(input); }
      dropdown.style.display = "none";
      if (input) input.focus();
    });
    dropdown.appendChild(item);
  });
  dropdown.style.display = "block";
}

function ideOpenClaude(node) {
  node = node || "local";
  _ccTabCounter++;
  var label = "Claude Code" + (_ccTabCounter > 1 ? " " + _ccTabCounter : "");
  var ccContainer = document.getElementById("ide-cc-container");
  if (!ccContainer) return;

  termLoadXterm(function() {
    var termDiv = document.createElement("div");
    termDiv.className = "ide-cc-term";
    termDiv.style.height = "100%";
    ccContainer.appendChild(termDiv);

    var term = new Terminal({
      theme: { background: "#1a1a2e", foreground: "#e2e8f0", cursor: "#f97316",
               selectionBackground: "#334155" },
      fontSize: 14,
      fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
      cursorBlink: true,
    });
    term.open(termDiv);

    var fitAddon = null;
    try {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      fitAddon.fit();
    } catch(e) {}

    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = protocol + "//" + location.host + "/ws/terminal?token=" +
      encodeURIComponent(state.token) + "&node=" + encodeURIComponent(node) + "&cmd=claude";

    var tab = {
      type: "claude",
      path: label,
      el: termDiv,
      term: term,
      ws: null,
      fitAddon: fitAddon,
      node: node
    };
    _ideTabs.push(tab);
    _ideActiveTab = _ideTabs.length - 1;

    // Connect WS
    var ws = new WebSocket(wsUrl);
    tab.ws = ws;
    ws.onopen = function() {
      term.write("\x1b[38;5;208m" + label + " connected\x1b[0m\r\n\r\n");
      if (fitAddon) {
        fitAddon.fit();
        ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
      }
    };
    ws.onmessage = function(ev) { term.write(ev.data); };
    ws.onclose = function() { term.write("\r\n\x1b[90m[session ended]\x1b[0m\r\n"); };
    ws.onerror = function() { term.write("\r\n\x1b[31m[connection error]\x1b[0m\r\n"); };
    term.onData(function(data) {
      if (ws.readyState === 1) ws.send(data);
    });
    term.onResize(function(size) {
      if (ws.readyState === 1) ws.send(JSON.stringify({ type: "resize", cols: size.cols, rows: size.rows }));
    });

    ideActivateTab();

    // Fit on window resize
    window.addEventListener("resize", function() {
      if (fitAddon && tab.el && tab.el.offsetHeight > 0) {
        try { fitAddon.fit(); } catch(e) {}
      }
    });
  });
}

async function ideSaveCurrentFile() {
  if (_ideActiveTab < 0) return;
  var tab = _ideTabs[_ideActiveTab];
  var content = tab.model.getValue();
  var statusEl = document.getElementById("ide-status-left");
  try {
    if (statusEl) statusEl.textContent = "Saving " + tab.path + "...";
    var res = await fetch("/api/ide/file", {
      method: "POST",
      headers: { Authorization: "Bearer " + state.token, "Content-Type": "application/json" },
      body: JSON.stringify({ path: tab.path, content: content }),
    });
    if (!res.ok) { toast("Save failed", "error"); return; }
    tab.modified = false;
    tab.originalContent = content;
    ideRenderTabs();
    if (statusEl) statusEl.textContent = tab.path + " — saved";
    toast("Saved " + tab.path, "success");
  } catch (e) {
    toast("Save error: " + e.message, "error");
  }
}

function ideRefreshTree() {
  _ideTreeCache = {};
  _ideExpandedDirs = new Set([""]);
  ideLoadTree("");
}

function ideToggleSearch() {
  var panel = document.getElementById("ide-search-panel");
  if (panel) {
    panel.style.display = panel.style.display === "none" ? "block" : "none";
    if (panel.style.display === "block") {
      var input = document.getElementById("ide-search-input");
      if (input) input.focus();
    }
  }
}

async function ideDoSearch(query) {
  if (!query.trim()) return;
  var resultsEl = document.getElementById("ide-search-results");
  if (!resultsEl) return;
  resultsEl.textContent = "Searching...";
  try {
    var res = await fetch("/api/ide/search?q=" + encodeURIComponent(query), {
      headers: { Authorization: "Bearer " + state.token },
    });
    var data = await res.json();
    if (data.results.length === 0) { resultsEl.textContent = "No results"; return; }
    resultsEl.innerHTML = data.results.map(function(r) {
      return '<div class="ide-search-result" onclick="ideOpenFile(\'' + r.file.replace(/'/g, "\\'") + '\')">' +
        '<span class="file">' + esc(r.file) + '</span><span class="line-num">:' + r.line + '</span> ' +
        esc(r.text) + '</div>';
    }).join("");
  } catch (e) {
    resultsEl.textContent = "Search error: " + e.message;
  }
}

// ---------------------------------------------------------------------------
// Terminal (xterm.js)
// ---------------------------------------------------------------------------
var _termSessions = [];
var _termActiveIdx = -1;
var _termVisible = false;
var _xtermLoaded = false;

function termLoadXterm(cb) {
  if (_xtermLoaded) { cb(); return; }
  var link = document.createElement("link");
  link.rel = "stylesheet";
  link.href = "/xterm/xterm.css";
  document.head.appendChild(link);
  // Save and disable AMD define to prevent conflict with Monaco
  var savedDefine = window.define;
  var savedRequire = window.require;
  window.define = undefined;
  window.require = undefined;
  var script = document.createElement("script");
  script.src = "/xterm/xterm.js";
  script.onload = function() {
    var script2 = document.createElement("script");
    script2.src = "/xterm/addon-fit.js";
    script2.onload = function() {
      // Restore AMD
      window.define = savedDefine;
      window.require = savedRequire;
      _xtermLoaded = true;
      cb();
    };
    document.head.appendChild(script2);
  };
  document.head.appendChild(script);
}

function termToggle() {
  _termVisible = !_termVisible;
  var wrapper = document.getElementById("ide-terminal-wrapper");
  var handle = document.getElementById("ide-drag-handle");
  if (!wrapper) return;
  if (_termVisible) {
    wrapper.style.display = "flex";
    if (handle) handle.style.display = "block";
    if (_termSessions.length === 0) termNew("local");
    else termFitAll();
  } else {
    wrapper.style.display = "none";
    if (handle) handle.style.display = "none";
  }
}

function termNew(node) {
  termLoadXterm(function() {
    // Show terminal panel if hidden
    if (!_termVisible) {
      _termVisible = true;
      var wrapperEl = document.getElementById("ide-terminal-wrapper");
      var handleEl = document.getElementById("ide-drag-handle");
      if (wrapperEl) wrapperEl.style.display = "flex";
      if (handleEl) handleEl.style.display = "block";
    }

    var container = document.getElementById("ide-terminal-container");
    if (!container) return;
    // Hide all existing terminals
    for (var i = 0; i < _termSessions.length; i++) {
      if (_termSessions[i].el) _termSessions[i].el.style.display = "none";
    }
    var termDiv = document.createElement("div");
    termDiv.style.height = "100%";
    container.appendChild(termDiv);
    var term = new Terminal({
      theme: { background: "#0f172a", foreground: "#e2e8f0", cursor: "#38bdf8",
               selectionBackground: "#334155" },
      fontSize: 13,
      fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
      cursorBlink: true,
    });
    term.open(termDiv);

    var fitAddon = null;
    try {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      fitAddon.fit();
    } catch(e) {}

    // Build WebSocket URL
    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = protocol + "//" + location.host + "/ws/terminal?token=" + encodeURIComponent(state.token) + "&node=" + encodeURIComponent(node || "local");

    // Build label: "bash (remote)" for remote, "bash N" for local
    var localCount = _termSessions.filter(function(s) { return s.node !== "remote" && s.label.indexOf("bash") === 0; }).length;
    var label = (node === "remote") ? "bash (remote)" : "bash " + (localCount + 1);

    var session = {
      term: term,
      ws: null,
      el: termDiv,
      node: node || "local",
      label: label,
      fitAddon: fitAddon,
      reconnecting: false,
      retryCount: 0,
      wsUrl: wsUrl
    };
    _termSessions.push(session);
    _termActiveIdx = _termSessions.length - 1;
    termConnectWs(session, wsUrl, 0);
    termRenderTabs();
  });
}

function termNewClaude(node) {
  termLoadXterm(function() {
    // Show terminal panel if hidden
    if (!_termVisible) {
      _termVisible = true;
      var wrapperEl = document.getElementById("ide-terminal-wrapper");
      var handleEl = document.getElementById("ide-drag-handle");
      if (wrapperEl) wrapperEl.style.display = "flex";
      if (handleEl) handleEl.style.display = "block";
    }

    var container = document.getElementById("ide-terminal-container");
    if (!container) return;
    for (var i = 0; i < _termSessions.length; i++) {
      if (_termSessions[i].el) _termSessions[i].el.style.display = "none";
    }
    var termDiv = document.createElement("div");
    termDiv.style.height = "100%";
    container.appendChild(termDiv);
    var term = new Terminal({
      theme: { background: "#0f172a", foreground: "#e2e8f0", cursor: "#38bdf8",
               selectionBackground: "#334155" },
      fontSize: 13,
      fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
      cursorBlink: true,
    });
    term.open(termDiv);

    var fitAddon = null;
    try {
      fitAddon = new FitAddon.FitAddon();
      term.loadAddon(fitAddon);
      fitAddon.fit();
    } catch(e) {}

    var protocol = location.protocol === "https:" ? "wss:" : "ws:";
    var wsUrl = protocol + "//" + location.host + "/ws/terminal?token=" + encodeURIComponent(state.token) + "&node=" + encodeURIComponent(node || "local") + "&cmd=claude";

    var label = (node === "remote") ? "Claude (remote)" : "Claude (local)";

    var session = {
      term: term,
      ws: null,
      el: termDiv,
      node: node || "local",
      label: label,
      fitAddon: fitAddon,
      reconnecting: false,
      retryCount: 0,
      wsUrl: wsUrl
    };
    _termSessions.push(session);
    _termActiveIdx = _termSessions.length - 1;
    termConnectWs(session, wsUrl, 0);
    termRenderTabs();
  });
}

function termSwitch(idx) {
  if (idx < 0 || idx >= _termSessions.length) return;
  for (var i = 0; i < _termSessions.length; i++) {
    if (_termSessions[i].el) _termSessions[i].el.style.display = i === idx ? "block" : "none";
  }
  _termActiveIdx = idx;
  termRenderTabs();
}

function termClose(idx) {
  var s = _termSessions[idx];
  if (s.ws) s.ws.close();
  if (s.term) s.term.dispose();
  if (s.el) s.el.remove();
  _termSessions.splice(idx, 1);
  if (_termActiveIdx >= _termSessions.length) _termActiveIdx = _termSessions.length - 1;
  if (_termSessions.length === 0) { _termVisible = false; var w = document.getElementById("ide-terminal-wrapper"); if (w) w.style.display = "none"; }
  else termSwitch(_termActiveIdx);
  termRenderTabs();
}

function termRenderTabs() {
  var el = document.getElementById("ide-terminal-tabs");
  if (!el) return;
  el.innerHTML = _termSessions.map(function(s, i) {
    var active = i === _termActiveIdx ? " active" : "";
    var dotColor = s.reconnecting ? "#f59e0b" : (s.node === "remote" ? "#34d399" : "#38bdf8");
    return '<span class="ide-terminal-tab' + active + '" onclick="termSwitch(' + i + ')">'
      + '<span style="color:' + dotColor + ';margin-right:4px">&#9679;</span>'
      + esc(s.label)
      + ' <span class="close" onclick="event.stopPropagation();termClose(' + i + ')">&times;</span>'
      + '</span>';
  }).join("");
}

// ---------------------------------------------------------------------------
// Terminal WebSocket connector with auto-reconnect
// ---------------------------------------------------------------------------
function termConnectWs(session, wsUrl, retryCount) {
  retryCount = retryCount || 0;
  var ws = new WebSocket(wsUrl);
  session.ws = ws;
  session.reconnecting = retryCount > 0;
  termRenderTabs();

  ws.onopen = function() {
    session.reconnecting = false;
    session.retryCount = 0;
    termRenderTabs();
    if (retryCount > 0) {
      session.term.write("\r\n\x1b[32mReconnected\x1b[0m\r\n");
    }
  };
  ws.onmessage = function(e) { session.term.write(e.data); };
  ws.onclose = function() {
    if (retryCount >= 3) {
      session.term.write("\r\n\x1b[31mDisconnected (max retries reached)\x1b[0m\r\n");
      session.reconnecting = false;
      termRenderTabs();
      return;
    }
    var delay = Math.pow(2, retryCount) * 1000; // 1000, 2000, 4000 ms
    session.term.write("\r\n\x1b[33mDisconnected \u2014 reconnecting in " + (delay / 1000) + "s...\x1b[0m\r\n");
    session.reconnecting = true;
    termRenderTabs();
    setTimeout(function() {
      if (_termSessions.indexOf(session) !== -1) {
        termConnectWs(session, wsUrl, retryCount + 1);
      }
    }, delay);
  };
  session.term.onData(function(data) {
    if (ws.readyState === 1) ws.send(data);
  });
}

function termFitAll() {
  _termSessions.forEach(function(s) {
    if (!s.fitAddon) return;
    try {
      s.fitAddon.fit();
      if (s.ws && s.ws.readyState === 1 && s.term) {
        s.ws.send(JSON.stringify({ type: "resize", cols: s.term.cols, rows: s.term.rows }));
      }
    } catch(e) {}
  });
}

// ---------------------------------------------------------------------------
// Terminal dropdown helpers
// ---------------------------------------------------------------------------
var _remoteAvailCache = null;
var _remoteAvailCacheAt = 0;

// --- Re-attach Claude Code tabs after SPA navigation ---
function ideReattachCCTabs() {
  var ccContainer = document.getElementById("ide-cc-container");
  if (!ccContainer) return;
  var hasCCTabs = false;
  for (var i = 0; i < _ideTabs.length; i++) {
    var tab = _ideTabs[i];
    if (tab.type !== "claude") continue;
    if (tab.chatPanel) {
      // Chat panel tabs persist their DOM -- no xterm re-creation needed
      if (tab.el && !tab.el.isConnected) ccContainer.appendChild(tab.el);
      hasCCTabs = true;
      continue;
    }
    hasCCTabs = true;
    // Old DOM was destroyed — re-create xterm in new container
    termLoadXterm(function(tabRef, idx) {
      return function() {
        var termDiv = document.createElement("div");
        termDiv.className = "ide-cc-term";
        termDiv.style.height = "100%";
        termDiv.style.display = (idx === _ideActiveTab) ? "block" : "none";
        ccContainer.appendChild(termDiv);

        var term = new Terminal({
          theme: { background: "#1a1a2e", foreground: "#e2e8f0", cursor: "#f97316",
                   selectionBackground: "#334155" },
          fontSize: 14,
          fontFamily: "'Cascadia Code', 'Fira Code', 'JetBrains Mono', 'Consolas', monospace",
          cursorBlink: true,
        });
        term.open(termDiv);

        var fitAddon = null;
        try {
          fitAddon = new FitAddon.FitAddon();
          term.loadAddon(fitAddon);
          fitAddon.fit();
        } catch(e) {}

        // Close old WS if still open
        if (tabRef.ws && tabRef.ws.readyState <= 1) tabRef.ws.close();

        // Update tab references
        tabRef.el = termDiv;
        tabRef.term = term;
        tabRef.fitAddon = fitAddon;

        // Reconnect WS
        var protocol = location.protocol === "https:" ? "wss:" : "ws:";
        var wsUrl = protocol + "//" + location.host + "/ws/terminal?token=" +
          encodeURIComponent(state.token) + "&node=" + encodeURIComponent(tabRef.node || "local") + "&cmd=claude";

        var ws = new WebSocket(wsUrl);
        tabRef.ws = ws;
        ws.onopen = function() {
          term.write("\x1b[38;5;208m" + tabRef.path + " reconnected\x1b[0m\r\n\r\n");
          if (fitAddon) {
            fitAddon.fit();
            ws.send(JSON.stringify({ type: "resize", cols: term.cols, rows: term.rows }));
          }
        };
        ws.onmessage = function(ev) { term.write(ev.data); };
        ws.onclose = function() { term.write("\r\n\x1b[90m[session ended]\x1b[0m\r\n"); };
        ws.onerror = function() { term.write("\r\n\x1b[31m[connection error]\x1b[0m\r\n"); };
        term.onData(function(data) {
          if (ws.readyState === 1) ws.send(data);
        });
        term.onResize(function(size) {
          if (ws.readyState === 1) ws.send(JSON.stringify({ type: "resize", cols: size.cols, rows: size.rows }));
        });

        // If this is the active tab, show it
        if (idx === _ideActiveTab) {
          ideActivateTab();
        }
      };
    }(tab, i));
  }
  // Re-render tabs to show CC tabs
  if (hasCCTabs) {
    setTimeout(function() { ideRenderTabs(); }, 500);
  }
}

// --- VS Code-style panel/activity bar helpers ---
var _ideSidebarVisible = true;
var _ideActivePanel = "explorer";

function ideShowPanel(panel, evt) {
  evt = evt || window.event;
  var btn = evt && evt.currentTarget ? evt.currentTarget : document.querySelectorAll(".ide-activity-btn")[panel === "search" ? 1 : 0];
  var sidebar = document.getElementById("ide-sidebar-panel");

  // Toggle: clicking the active panel hides sidebar only (activity bar stays)
  if (panel === _ideActivePanel && _ideSidebarVisible) {
    _ideSidebarVisible = false;
    if (sidebar) sidebar.style.display = "none";
    if (btn) btn.classList.remove("active");
    return;
  }

  // Show sidebar and switch panel (activity bar always visible)
  _ideSidebarVisible = true;
  _ideActivePanel = panel;
  var btns = document.querySelectorAll(".ide-activity-btn");
  btns.forEach(function(b) { b.classList.remove("active"); });
  if (btn) btn.classList.add("active");
  if (sidebar) sidebar.style.display = "";

  var searchPanel = document.getElementById("ide-search-panel");
  var fileTree = document.getElementById("ide-file-tree");
  var header = document.querySelector(".ide-sidebar-header span");
  if (panel === "search") {
    if (searchPanel) searchPanel.style.display = "block";
    if (fileTree) fileTree.style.display = "none";
    if (header) header.textContent = "SEARCH";
    var inp = document.getElementById("ide-search-input");
    if (inp) inp.focus();
  } else {
    if (searchPanel) searchPanel.style.display = "none";
    if (fileTree) fileTree.style.display = "";
    if (header) header.textContent = "EXPLORER";
  }
}

// Toggle explorer panel (Ctrl+B, same as VS Code)
function ideToggleExplorer() {
  var sidebar = document.getElementById("ide-sidebar-panel");
  if (_ideSidebarVisible) {
    // Hide sidebar only — activity bar stays visible for re-toggle
    _ideSidebarVisible = false;
    if (sidebar) sidebar.style.display = "none";
    var btns = document.querySelectorAll(".ide-activity-btn");
    btns.forEach(function(b) { b.classList.remove("active"); });
  } else {
    // Show sidebar
    _ideSidebarVisible = true;
    if (sidebar) sidebar.style.display = "";
    var idx = _ideActivePanel === "search" ? 1 : 0;
    var btns = document.querySelectorAll(".ide-activity-btn");
    if (btns[idx]) btns[idx].classList.add("active");
  }
  setTimeout(function() {
    if (typeof termFitAll === "function") termFitAll();
    if (_monacoEditor) _monacoEditor.layout();
  }, 100);
}

// Collapse/expand main Agent42 sidebar when in IDE mode
var _ideMainSidebarCollapsed = false;
function ideToggleMainSidebar() {
  _ideMainSidebarCollapsed = !_ideMainSidebarCollapsed;
  var sidebar = document.querySelector(".sidebar");
  var main = document.querySelector(".main");
  var miniBar = document.getElementById("ide-mini-sidebar");

  if (_ideMainSidebarCollapsed) {
    if (sidebar) sidebar.style.display = "none";
    if (main) { main.style.marginLeft = "48px"; main.style.width = "calc(100% - 48px)"; }
    // Create mini icon sidebar if not exists
    if (!miniBar) {
      miniBar = document.createElement("div");
      miniBar.id = "ide-mini-sidebar";
      miniBar.className = "ide-mini-sidebar";
      // NOTE: innerHTML used with static content only — no user input
      miniBar.innerHTML = [
        {icon:'M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-4 0h4', page:'tasks', title:'Mission Control'},
        {icon:'M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z', page:'status', title:'Status'},
        {icon:'M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z', page:'approvals', title:'Approvals'},
        {icon:'M8 10h.01M12 10h.01M16 10h.01M9 16H5a2 2 0 01-2-2V6a2 2 0 012-2h14a2 2 0 012 2v8a2 2 0 01-2 2h-5l-5 5v-5z', page:'chat', title:'Chat'},
        {icon:'M10 20l4-16m4 4l4 4-4 4M6 16l-4-4 4-4', page:'code', title:'Code'},
        {icon:'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z', page:'tools', title:'Tools'},
        {icon:'M13 10V3L4 14h7v7l9-11h-7z', page:'skills', title:'Skills'},
        {icon:'M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z', page:'agents', title:'Agents'},
        {icon:'M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z', page:'teams', title:'Teams'},
        {icon:'M4 7v10c0 2 1 3 3 3h10c2 0 3-1 3-3V7M4 7l4-4h8l4 4M4 7h16M9 11v4M15 11v4', page:'apps', title:'Apps'},
        {icon:'M9 17v-2m3 2v-4m3 4v-6m2 10H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z', page:'reports', title:'Reports'},
        {icon:'M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.066 2.573c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.573 1.066c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.066-2.573c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z', page:'settings', title:'Settings'}
      ].map(function(item) {
        var active = item.page === state.page ? ' active' : '';
        return '<button class="ide-mini-btn' + active + '" onclick="navigate(\'' + item.page + '\')" title="' + item.title + '">'
          + '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="' + item.icon + '"/></svg>'
          + '</button>';
      }).join('');
      document.body.appendChild(miniBar);
    } else {
      // Update active state
      var btns = miniBar.querySelectorAll('.ide-mini-btn');
      var pages = ['tasks','status','approvals','chat','code','tools','skills','agents','teams','apps','reports','settings'];
      btns.forEach(function(b, i) { b.classList.toggle('active', pages[i] === state.page); });
    }
    miniBar.style.display = "flex";
  } else {
    if (sidebar) sidebar.style.display = "";
    if (main) { main.style.marginLeft = ""; main.style.width = ""; }
    if (miniBar) miniBar.style.display = "none";
  }
  // Re-fit terminals after layout change
  setTimeout(function() { if (typeof termFitAll === "function") termFitAll(); }, 100);
}

function idePanelTab(tab) {
  var btns = document.querySelectorAll(".ide-panel-tab");
  btns.forEach(function(b) { b.classList.remove("active"); });
  event.currentTarget.classList.add("active");
  // Only terminal tab is functional for now
  var termContainer = document.getElementById("ide-terminal-container");
  if (termContainer) termContainer.style.display = tab === "terminal" ? "" : "none";
  var termTabs = document.getElementById("ide-terminal-tabs");
  if (termTabs) termTabs.style.display = tab === "terminal" ? "" : "none";
}

function termSplit() {
  // Split = just open another terminal of the same type
  termNew("local");
}

function termKillActive() {
  if (_termSessions.length === 0) return;
  var idx = _termActiveIdx;
  var session = _termSessions[idx];
  if (session.ws && session.ws.readyState <= 1) session.ws.close();
  if (session.el) session.el.remove();
  _termSessions.splice(idx, 1);
  if (_termSessions.length > 0) {
    _termActiveIdx = Math.min(idx, _termSessions.length - 1);
    termSwitch(_termActiveIdx);
  } else {
    _termActiveIdx = 0;
  }
  termRenderTabs();
}

var _termMaximized = false;
function termMaximize() {
  var topRow = document.querySelector(".ide-top-row");
  var handle = document.getElementById("ide-drag-handle");
  if (!topRow) return;
  _termMaximized = !_termMaximized;
  topRow.style.display = _termMaximized ? "none" : "";
  if (handle) handle.style.display = _termMaximized ? "none" : "";
  termFitAll();
}

function termDropdownToggle() {
  var menu = document.getElementById("ide-term-dropdown");
  if (!menu) return;
  var visible = menu.style.display !== "none";
  menu.style.display = visible ? "none" : "block";
  if (!visible) {
    checkRemoteAvailable(function(available) {
      var remoteItems = menu.querySelectorAll(".remote-item");
      remoteItems.forEach(function(el) {
        el.style.opacity = available ? "1" : "0.4";
        el.style.pointerEvents = available ? "auto" : "none";
        el.title = available ? "" : "No remote node configured";
      });
    });
    setTimeout(function() {
      document.addEventListener("click", termDropdownDismiss, { once: true });
    }, 0);
  }
}

function termDropdownDismiss() {
  var menu = document.getElementById("ide-term-dropdown");
  if (menu) menu.style.display = "none";
}

function checkRemoteAvailable(cb) {
  var now = Date.now();
  if (_remoteAvailCache !== null && now - _remoteAvailCacheAt < 30000) {
    cb(_remoteAvailCache);
    return;
  }
  apiFetch("/api/remote/status")
    .then(function(d) {
      _remoteAvailCache = !!(d && d.available);
      _remoteAvailCacheAt = Date.now();
      cb(_remoteAvailCache);
    })
    .catch(function() { cb(false); });
}

// ---------------------------------------------------------------------------
// Drag handle for terminal panel resize
// ---------------------------------------------------------------------------
var _isDragging = false;
var _dragStartY = 0;
var _dragStartHeight = 0;

function initDragHandle() {
  var handle = document.getElementById("ide-drag-handle");
  if (!handle) return;
  handle.addEventListener("mousedown", function(e) {
    _isDragging = true;
    _dragStartY = e.clientY;
    var wrapper = document.getElementById("ide-terminal-wrapper");
    _dragStartHeight = wrapper ? wrapper.getBoundingClientRect().height : 200;
    document.body.style.cursor = "ns-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  });
  document.addEventListener("mousemove", function(e) {
    if (!_isDragging) return;
    var delta = _dragStartY - e.clientY;
    var newHeight = Math.max(80, Math.min(_dragStartHeight + delta, window.innerHeight * 0.8));
    var wrapper = document.getElementById("ide-terminal-wrapper");
    if (wrapper) {
      wrapper.style.height = newHeight + "px";
      wrapper.style.flex = "none";
    }
    termFitAll();
  });
  document.addEventListener("mouseup", function() {
    if (!_isDragging) return;
    _isDragging = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
  });
}

// ---------------------------------------------------------------------------
// CC Panel drag handle for horizontal resize (LAYOUT-02)
// ---------------------------------------------------------------------------
var _ccPanelMode = false;
var _isPanelDragging = false;
var _panelDragStartX = 0;
var _panelDragStartWidth = 0;

function initPanelDragHandle() {
  var handle = document.getElementById("ide-panel-drag-handle");
  if (!handle) return;
  handle.addEventListener("mousedown", function(e) {
    _isPanelDragging = true;
    _panelDragStartX = e.clientX;
    var panel = document.getElementById("ide-cc-panel");
    _panelDragStartWidth = panel ? panel.getBoundingClientRect().width : 400;
    document.body.style.cursor = "ew-resize";
    document.body.style.userSelect = "none";
    e.preventDefault();
  });
  document.addEventListener("mousemove", function(e) {
    if (!_isPanelDragging) return;
    var delta = _panelDragStartX - e.clientX;
    var editorArea = document.querySelector(".ide-main-editor-area");
    var maxWidth = editorArea ? editorArea.getBoundingClientRect().width * 0.6 : 600;
    var newWidth = Math.max(250, Math.min(_panelDragStartWidth + delta, maxWidth));
    var panel = document.getElementById("ide-cc-panel");
    if (panel) { panel.style.width = newWidth + "px"; panel.style.flex = "none"; }
    if (_monacoEditor) _monacoEditor.layout();
  });
  document.addEventListener("mouseup", function() {
    if (!_isPanelDragging) return;
    _isPanelDragging = false;
    document.body.style.cursor = "";
    document.body.style.userSelect = "";
    var panel = document.getElementById("ide-cc-panel");
    if (panel) {
      try { localStorage.setItem("cc_panel_width", Math.round(panel.getBoundingClientRect().width)); } catch(e) {}
    }
  });
}

function ideToggleCCPanel() {
  // Three-state toggle (Plan 04-03 full implementation):
  // 1. Panel open → close and move sessions back to tabs
  // 2. CC tabs exist → open panel and move sessions into it
  // 3. No CC open → open panel and start a new session
  var ccTabs = _ideTabs.filter(function(t) { return t.type === "claude"; });
  if (_ccPanelMode) {
    ideMoveSessionsToTab();
    ideCloseCCPanel();
  } else if (ccTabs.length > 0) {
    ideOpenCCPanel();
    ideMoveSessionsToPanel();
  } else {
    ideOpenCCPanel();
    ideOpenCCChat("local");
    setTimeout(ideMoveSessionsToPanel, 50);
  }
}

function ideOpenCCPanel() {
  var panel = document.getElementById("ide-cc-panel");
  var handle = document.getElementById("ide-panel-drag-handle");
  if (!panel) return;
  var savedWidth = 400;
  try { savedWidth = parseInt(localStorage.getItem("cc_panel_width")) || 400; } catch(e) {}
  panel.style.display = "flex";
  panel.style.flexDirection = "column";
  panel.style.width = savedWidth + "px";
  panel.style.flex = "none";
  if (handle) handle.style.display = "";
  _ccPanelMode = true;
  setTimeout(function() { if (_monacoEditor) _monacoEditor.layout(); }, 50);
}

function ideCloseCCPanel() {
  var panel = document.getElementById("ide-cc-panel");
  var handle = document.getElementById("ide-panel-drag-handle");
  if (!panel) return;
  try { localStorage.setItem("cc_panel_width", Math.round(panel.getBoundingClientRect().width)); } catch(e) {}
  panel.style.display = "none";
  if (handle) handle.style.display = "none";
  _ccPanelMode = false;
  setTimeout(function() { if (_monacoEditor) _monacoEditor.layout(); }, 50);
}

function ideMoveSessionsToPanel() {
  var panel = document.getElementById("ide-cc-panel");
  var ccContainer = document.getElementById("ide-cc-container");
  if (!panel) return;
  // Move each CC tab's DOM element into the panel (appendChild moves, does not clone)
  _ideTabs.forEach(function(tab) {
    if (tab.type === "claude" && tab.el) {
      panel.appendChild(tab.el);
      tab.el.style.display = tab.chatPanel ? "flex" : "block";
      tab.inPanel = true;
    }
  });
  // Hide the CC container (no longer houses CC sessions)
  if (ccContainer) ccContainer.style.display = "none";
  // Show the first active CC tab in the panel
  var ccTabs = _ideTabs.filter(function(t) { return t.type === "claude"; });
  if (ccTabs.length > 0) {
    var activeCC = ccTabs[0];
    ccTabs.forEach(function(t) { if (t.el) t.el.style.display = "none"; });
    if (activeCC.el) activeCC.el.style.display = activeCC.chatPanel ? "flex" : "block";
  }
  // Activate the first non-CC tab (show editor), or welcome if none
  var fileTabs = _ideTabs.filter(function(t) { return t.type !== "claude"; });
  if (fileTabs.length > 0) {
    _ideActiveTab = _ideTabs.indexOf(fileTabs[0]);
    ideActivateTab();
  } else {
    _ideActiveTab = -1;
    if (_monacoEditor) _monacoEditor.setModel(null);
    var container = document.getElementById("ide-editor-container");
    var welcome = document.getElementById("ide-welcome");
    if (container) container.style.display = "none";
    if (welcome) welcome.style.display = "flex";
  }
  ideRenderTabs();
}

function ideMoveSessionsToTab() {
  var ccContainer = document.getElementById("ide-cc-container");
  if (!ccContainer) return;
  // Move CC tab DOM elements back into the CC container
  _ideTabs.forEach(function(tab) {
    if (tab.type === "claude" && tab.el) {
      ccContainer.appendChild(tab.el);
      tab.inPanel = false;
    }
  });
  // Activate the first CC tab
  var ccTabs = _ideTabs.filter(function(t) { return t.type === "claude"; });
  if (ccTabs.length > 0) {
    _ideActiveTab = _ideTabs.indexOf(ccTabs[0]);
    ideActivateTab();
  }
  ideRenderTabs();
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
    { id: "health", label: "System Health" },
    { id: "tasks", label: "Tasks & Projects" },
  ];

  // Only rebuild the full page (tab bar + body container) if not already
  // rendered — on tab switch, just swap the body to prevent DOM detachment.
  // Note: innerHTML is used with pre-escaped content (esc() applied in
  // render helpers) — this is an internal dashboard, not user-facing HTML.
  let bodyEl = el.querySelector(".reports-body");
  if (!bodyEl) {
    const tabBar = `<div class="reports-tabs">${tabs.map(t =>
      `<button class="reports-tab ${tab === t.id ? "active" : ""}" onclick="switchReportsTab('${t.id}')">${t.label}</button>`
    ).join("")}<button class="btn btn-outline btn-sm" style="margin-left:auto;align-self:center" onclick="refreshReports()">Refresh</button></div>`;
    el.innerHTML = tabBar + '<div class="reports-body"></div>';
    bodyEl = el.querySelector(".reports-body");
  } else {
    // Update active tab highlight without replacing tab bar DOM nodes
    el.querySelectorAll(".reports-tab").forEach(btn => {
      const btnTab = btn.getAttribute("onclick")?.match(/'([^']+)'/)?.[1];
      btn.classList.toggle("active", btnTab === tab);
    });
  }

  let body = "";
  if (tab === "overview") body = _renderReportsOverview(d);
  else if (tab === "health") body = _renderReportsHealth(d);
  else if (tab === "tasks") body = _renderReportsTasks(d);

  bodyEl.innerHTML = body;
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
    <div class="stat-card"><div class="stat-label">MCP Tools</div><div class="stat-value text-info">${tools.enabled || tools.total || 0}</div></div>
    <div class="stat-card"><div class="stat-label">Projects</div><div class="stat-value">${projects.length}</div></div>
    <div class="stat-card"><div class="stat-label">Tools</div><div class="stat-value">${tools.enabled || 0}/${tools.total || 0}</div></div>
  </div>`;

  // MCP integration summary card
  const mcpCard = `<div class="card reports-section">
    <div class="card-header"><h3>MCP Integration</h3></div>
    <div class="card-body">
      <div class="status-metric-row"><span class="metric-label">Transport</span><span class="metric-value">stdio</span></div>
      <div class="status-metric-row"><span class="metric-label">Tools Available</span><span class="metric-value">${tools.enabled || tools.total || 0}</span></div>
      <div class="status-metric-row"><span class="metric-label">Skills Loaded</span><span class="metric-value">${(skills.skills || []).length || skills.total || 0}</span></div>
      <p style="color:var(--text-muted);font-size:0.85rem;margin-top:0.75rem">Model routing is handled by Claude Code. Token usage below reflects auxiliary API calls (embeddings, media, search).</p>
    </div>
  </div>`;

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

  return stats + `<div class="reports-grid">${mcpCard}${typesTable}</div>`;
}

function _renderReportsHealth(d) {
  const tu = d.token_usage || {};
  const tools = d.tools || {};
  const skills = d.skills || {};
  const toolList = tools.top_tools || [];
  const skillList = skills.skills || [];

  // Memory / storage stats
  const memCard = `<div class="card reports-section">
    <div class="card-header"><h3>System Health</h3></div>
    <div class="card-body">
      <p style="color:var(--text-muted);margin-bottom:1rem">Agent42 operates as an MCP server. Model routing is handled by Claude Code.</p>
      <div class="status-metric-row"><span class="metric-label">MCP Transport</span><span class="metric-value text-success">stdio</span></div>
      <div class="status-metric-row"><span class="metric-label">Tools Registered</span><span class="metric-value">${tools.total || 0}</span></div>
      <div class="status-metric-row"><span class="metric-label">Tools Enabled</span><span class="metric-value text-success">${tools.enabled || 0}</span></div>
      <div class="status-metric-row"><span class="metric-label">Skills Loaded</span><span class="metric-value">${(skillList || []).length || skills.total || 0}</span></div>
      <div class="status-metric-row"><span class="metric-label">Total Tokens Tracked</span><span class="metric-value" style="font-family:var(--mono)">${formatNumber(tu.total_tokens)}</span></div>
      <div class="status-metric-row"><span class="metric-label">Daily Spend</span><span class="metric-value" style="font-family:var(--mono)">$${(tu.daily_spend_usd || 0).toFixed(4)}</span></div>
    </div>
  </div>`;

  // Tool usage table
  const maxTool = toolList.length > 0 ? Math.max(...toolList.map(t => t.calls || 0)) : 1;
  const toolRows = toolList.slice(0, 20).map(t => {
    const pct = maxTool > 0 ? ((t.calls || 0) / maxTool * 100) : 0;
    return `<tr>
      <td style="font-weight:600;font-family:var(--mono);font-size:0.85rem">${esc(t.name || t.tool || "")}</td>
      <td>${_reportsBar(pct, formatNumber(t.calls || 0), "bar-info")}</td>
    </tr>`;
  }).join("");
  const toolTable = toolList.length > 0 ? `<div class="card reports-section">
    <div class="card-header"><h3>Tool Usage</h3></div>
    <div class="table-wrap"><table>
      <thead><tr><th>Tool</th><th>Invocations</th></tr></thead>
      <tbody>${toolRows}</tbody>
    </table></div>
  </div>` : "";

  return memCard + toolTable;
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
    { id: "providers", label: "API Keys" },
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
        <h4 style="margin:0 0 0.75rem;font-size:0.95rem;color:var(--text)">Model Routing (v2.0)</h4>
        <div class="help" style="line-height:1.7">
          Model routing is now handled by <strong>Claude Code</strong>. Agent42 operates as an MCP server, providing tools and context to Claude Code sessions.<br><br>
          API keys configured here are used for <strong>media generation</strong> (Replicate, Luma), <strong>web search</strong> (Brave), and <strong>embeddings</strong> (Gemini, OpenAI). LLM model selection is managed in your Claude Code configuration.
        </div>
      </div>

      <div class="form-group" style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem">
        <h4 style="margin:0 0 0.75rem;font-size:0.95rem;color:var(--text)">MCP Integration</h4>
        <div class="help" style="line-height:1.7">
          Agent42 runs as an MCP server that Claude Code connects to via stdio transport. Tools, memory, and workspace operations are exposed as MCP tools.<br>
          API keys below are still used for auxiliary services (image/video generation, search, embeddings).
        </div>
      </div>

      <h4 style="margin:0 0 0.75rem;font-size:0.95rem">Primary Providers</h4>
      ${settingSecret("GEMINI_API_KEY", "Gemini API Key (Recommended)", "Default primary model. Generous free tier: 1,500 requests/day for Flash, 1M token context. Get one at aistudio.google.com.", true)}
      ${settingSecret("STRONGWALL_API_KEY", "StrongWall API Key", "L1 workhorse provider. Kimi K2.5 with unlimited requests ($16/mo). Get access at strongwall.ai.", true)}
      ${settingSecret("OPENROUTER_API_KEY", "OpenRouter API Key", "200+ models via one key. Free models used as critic/fallback. Paid models activated when credits are available. Get one at openrouter.ai/keys.", true)}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Premium Providers (Optional)</h4>
      <div class="help" style="margin-bottom:0.75rem">Set these to enable premium models for admin overrides (e.g., <code>AGENT42_CODING_MODEL=claude-opus-4-6</code>).</div>
      ${settingSecret("ANTHROPIC_API_KEY", "Anthropic API Key", "For Claude Opus/Sonnet models. Get one at console.anthropic.com.")}
      ${settingSecret("OPENAI_API_KEY", "OpenAI API Key", "For GPT-4o, o1, and DALL-E image generation. Get one at platform.openai.com.")}
      ${settingSecret("DEEPSEEK_API_KEY", "DeepSeek API Key", "For DeepSeek Coder/R1 models. Get one at platform.deepseek.com.")}
      ${settingSecret("CEREBRAS_API_KEY", "Cerebras API Key", "Free inference (~3000 tok/s). 4 models included. Get one at cloud.cerebras.ai.")}

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
    routing: () => `<h3>LLM Routing</h3><p class="section-desc">Model routing is now handled by Claude Code. Configure models in your Claude Code settings.</p>`,
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
        redis_only: "Redis + file (semantic search degraded)",
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
      const isDegraded = ss && ss.configured_mode && ss.configured_mode !== ss.mode;
      const backendSection = ss ? `
        <div style="background:var(--bg-secondary);border:1px solid var(--border);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem">
          <div style="font-weight:600;margin-bottom:0.6rem;font-size:0.9rem">Active Storage Backend</div>
          <div style="margin-bottom:0.5rem;color:var(--text-muted);font-size:0.85rem">${esc(modeLabels[ss.mode] || ss.mode)}</div>
          ${isDegraded ? `<div style="background:#fef3c7;border:1px solid #f59e0b;border-radius:6px;padding:0.5rem 0.75rem;margin-bottom:0.65rem;font-size:0.82rem;color:#92400e">Degraded: configured as <strong>${esc(modeLabels[ss.configured_mode] || ss.configured_mode)}</strong> but one or more backends are unreachable. Memory system is using file-based fallback.</div>` : ""}
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
        <input type="password" id="key-${envVar}"
               placeholder="${willBeCleared ? "— will be cleared on save —" : (configured ? "Enter new value to override" : "Enter API key")}"
               value="${hasEdit ? esc(state.keyEdits[envVar]) : ""}"
               oninput="state.keyEdits['${envVar}']=this.value;updateSaveBtn()"
               style="font-family:var(--mono);flex:1;${highlight || willBeCleared ? "border-color:var(--accent)" : ""}">
        <button class="btn btn-sm" onclick="const inp=document.getElementById('key-${envVar}');inp.type=inp.type==='password'?'text':'password';this.textContent=inp.type==='password'?'Show':'Hide'" title="Toggle visibility" style="white-space:nowrap">Show</button>
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
    state.orStatus = (await api("/settings/openrouter-status")) || null;
  } catch (e) { state.orStatus = null; }
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
// LLM Routing helpers (shared between Settings and Agents pages)
// ---------------------------------------------------------------------------
async function loadRoutingModels() {
  try {
    state.routingModels = (await api("/available-models")) || { l1: [], fallback: [], l2: [] };
  } catch { state.routingModels = { l1: [], fallback: [], l2: [] }; }
}

async function loadRoutingConfig() {
  try {
    state.routingConfig = (await api("/agent-routing")) || { profiles: {} };
  } catch { state.routingConfig = { profiles: {} }; }
}

function routingSelect(field, label, currentValue, isInherited, inheritedFrom, scope) {
  scope = scope || "default";
  const models = state.routingModels;
  const healthDot = (h) => h === "healthy" ? "&#9679;" // green dot via CSS color
                         : h === "degraded" ? "&#9679;"
                         : h === "unhealthy" ? "&#9679;" : "";
  const healthColor = (h) => h === "healthy" ? "color:#22c55e"
                            : h === "degraded" ? "color:#eab308"
                            : h === "unhealthy" ? "color:#ef4444" : "";

  const optionsHtml = (tier, tierLabel) => {
    if (!models[tier] || models[tier].length === 0) return "";
    return `<optgroup label="${esc(tierLabel)}">
      ${models[tier].map(m =>
        `<option value="${esc(m.key)}" ${currentValue === m.key ? "selected" : ""}>
          ${m.health ? "\u25CF " : ""}${esc(m.display_name)} (${esc(m.provider)})
        </option>`
      ).join("")}
    </optgroup>`;
  };

  const inheritLabel = isInherited
    ? `<span style="color:var(--text-muted);font-size:0.75rem">inherited from ${esc(inheritedFrom || "system")}</span>`
    : "";
  const editFn = scope === "agent" ? "updateAgentRoutingEdit" : "updateRoutingEdit";
  const clearFn = scope === "agent" ? "clearAgentRoutingField" : "clearRoutingField";
  const resetBtn = !isInherited && currentValue
    ? `<button class="btn btn-sm" onclick="${clearFn}('${esc(field)}')" title="Reset to inherited">&#10005;</button>`
    : "";

  return `
    <div class="form-group">
      <label>${esc(label)} ${inheritLabel}</label>
      <div style="display:flex;gap:0.5rem;align-items:center">
        <select style="flex:1;${isInherited ? 'color:var(--text-muted)' : ''}"
                onchange="${editFn}('${esc(field)}', this.value)">
          <option value="">Use default (Inherit)</option>
          ${optionsHtml("l1", "L1 Models")}
          ${optionsHtml("fallback", "Fallback Models")}
          ${optionsHtml("l2", "L2 Premium Models")}
        </select>
        ${resetBtn}
      </div>
    </div>
  `;
}

function renderChainSummary(chain) {
  if (!chain || chain.length === 0) return "";
  const badges = chain.map(entry => {
    const sourceStyle = entry.source === "FALLBACK_ROUTING"
      ? "background:var(--bg-hover);color:var(--text-muted)"
      : entry.source && entry.source.startsWith("profile:")
        ? "background:rgba(60,191,174,0.15);color:var(--a42-teal)"
        : "background:rgba(232,168,56,0.12);color:var(--a42-gold)";
    const sourceLabel = entry.source === "FALLBACK_ROUTING" ? "system"
      : entry.source === "_default" ? "default" : "overridden";
    return `<span style="display:inline-block;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.75rem;${sourceStyle}">
      ${esc(entry.field)}: ${esc(entry.value)} (${sourceLabel})
    </span>`;
  }).join(" &rarr; ");
  return `<div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.3rem;align-items:center">
    <strong style="font-size:0.8rem;color:var(--text-secondary)">Effective:</strong> ${badges}
  </div>`;
}

function updateRoutingEdit(field, value) {
  state.routingEdits[field] = value;
  renderSettingsPanel();
}

function clearRoutingField(field) {
  state.routingEdits[field] = "";
  renderSettingsPanel();
}

function updateAgentRoutingEdit(field, value) {
  state.agentRoutingEdits[field] = value;
  render();
}

function clearAgentRoutingField(field) {
  state.agentRoutingEdits[field] = "";
  render();
}

async function saveRouting(profileName) {
  const isDefault = profileName === "_default";
  if (isDefault) { state.routingSaving = true; renderSettingsPanel(); }
  else { state.agentRoutingSaving = true; render(); }
  try {
    const edits = isDefault ? state.routingEdits : state.agentRoutingEdits;
    const body = {};
    for (const [field, val] of Object.entries(edits)) {
      if (val === undefined) continue;
      body[field] = val === "" ? null : val;
    }
    if (Object.keys(body).length === 0) {
      toast("No changes to save", "info");
      if (isDefault) { state.routingSaving = false; renderSettingsPanel(); }
      else { state.agentRoutingSaving = false; render(); }
      return;
    }
    await api(`/agent-routing/${encodeURIComponent(profileName)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    if (isDefault) {
      state.routingEdits = {};
    } else {
      state.agentRoutingEdits = {};
      // Refresh per-agent routing data for detail view
      try {
        state.selectedProfileRouting = await api(`/agent-routing/${encodeURIComponent(profileName)}`);
      } catch { /* ignore */ }
    }
    await loadRoutingConfig();
    toast("Routing updated. Takes effect on next dispatch.", "success");
  } catch (e) {
    toast("Failed to save routing: " + e.message, "error");
  }
  if (isDefault) { state.routingSaving = false; renderSettingsPanel(); }
  else { state.agentRoutingSaving = false; render(); }
}

async function resetRouting(profileName) {
  const isDefault = profileName === "_default";
  const label = isDefault ? "global routing defaults" : `routing for ${profileName}`;
  if (!confirm(`Reset ${label}? This will clear all overrides.`)) return;
  try {
    await api(`/agent-routing/${encodeURIComponent(profileName)}`, { method: "DELETE" });
    if (isDefault) {
      state.routingEdits = {};
    } else {
      state.agentRoutingEdits = {};
      state.selectedProfileRouting = null;
      // Refresh per-agent routing data
      try {
        state.selectedProfileRouting = await api(`/agent-routing/${encodeURIComponent(profileName)}`);
      } catch { /* no config after reset */ }
    }
    await loadRoutingConfig();
    toast(`Routing reset. Inherits from ${isDefault ? "system defaults" : "global defaults"}.`, "success");
  } catch (e) {
    if (e.message && e.message.includes("404")) {
      toast("No overrides to reset", "info");
    } else {
      toast("Failed to reset: " + e.message, "error");
    }
  }
  if (isDefault) renderSettingsPanel();
  else render();
}

function renderRoutingPanel() {
  const defaultConfig = state.routingConfig && state.routingConfig.profiles ? state.routingConfig.profiles["_default"] : undefined;
  const overrides = defaultConfig && defaultConfig.overrides ? defaultConfig.overrides : {};
  const chain = defaultConfig && defaultConfig.resolution_chain ? defaultConfig.resolution_chain : [];

  const isOverridden = (field) => overrides[field] !== undefined && overrides[field] !== null;
  const currentVal = (field) => {
    if (state.routingEdits[field] !== undefined) return state.routingEdits[field];
    if (isOverridden(field)) return overrides[field];
    return "";
  };

  const hasEdits = Object.keys(state.routingEdits).length > 0;
  const unsavedWarning = hasEdits ? `<div class="help" style="color:var(--a42-gold);margin-bottom:0.5rem">Unsaved changes</div>` : "";

  return `
    <h3>LLM Routing</h3>
    <p class="section-desc">Configure global model routing defaults. Per-agent overrides can be set on the Agents page.</p>
    ${routingSelect("primary", "Primary (L1)", currentVal("primary"), !isOverridden("primary") && state.routingEdits["primary"] === undefined, "system")}
    ${routingSelect("critic", "Critic", currentVal("critic"), !isOverridden("critic") && state.routingEdits["critic"] === undefined, "system")}
    ${routingSelect("fallback", "Fallback", currentVal("fallback"), !isOverridden("fallback") && state.routingEdits["fallback"] === undefined, "system")}
    ${renderChainSummary(chain)}
    ${unsavedWarning}
    <div class="form-group" style="margin-top:1.5rem">
      <button class="btn btn-primary" onclick="saveRouting('_default')"
              ${!hasEdits || state.routingSaving ? "disabled" : ""}>
        ${state.routingSaving ? "Saving..." : "Save Routing Defaults"}
      </button>
      <button class="btn btn-outline" onclick="resetRouting('_default')" style="margin-left:0.5rem">
        Reset Global Defaults
      </button>
    </div>
  `;
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
    loadReports(), loadProfiles(), loadPersona(), loadRoutingModels(), loadRoutingConfig(),
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
        <div class="sidebar-brand"><img src="/assets/agent42-logo-light.svg" alt="Agent42" height="36" onerror="this.outerHTML='Agent<span class=&quot;num&quot;>42</span>'"></div>
        <nav class="sidebar-nav">
          <a href="#" data-page="tasks" class="${state.page === "tasks" ? "active" : ""}" onclick="event.preventDefault();navigate('tasks');closeMobileSidebar()">&#127919; Mission Control</a>
          <a href="#" data-page="status" class="${state.page === "status" ? "active" : ""}" onclick="event.preventDefault();navigate('status');closeMobileSidebar()">&#128200; Status</a>
          <a href="#" data-page="approvals" class="${state.page === "approvals" ? "active" : ""}" onclick="event.preventDefault();navigate('approvals');closeMobileSidebar()">&#128274; Approvals ${approvalBadge}</a>
          <a href="#" data-page="chat" class="${state.page === "chat" ? "active" : ""}" onclick="event.preventDefault();navigate('chat');closeMobileSidebar()">&#128172; Chat</a>
          <a href="#" data-page="code" class="${state.page === "code" ? "active" : ""}" onclick="event.preventDefault();navigate('code');closeMobileSidebar()">&#128187; Code</a>
          <a href="#" data-page="tools" class="${state.page === "tools" ? "active" : ""}" onclick="event.preventDefault();navigate('tools');closeMobileSidebar()">&#128295; Tools</a>
          <a href="#" data-page="skills" class="${state.page === "skills" ? "active" : ""}" onclick="event.preventDefault();navigate('skills');closeMobileSidebar()">&#9889; Skills</a>
          <a href="#" data-page="agents" class="${state.page === "agents" ? "active" : ""}" onclick="event.preventDefault();navigate('agents');closeMobileSidebar()">&#129302; Agents</a>
          <a href="#" data-page="teams" class="${state.page === "teams" ? "active" : ""}" onclick="event.preventDefault();navigate('teams');closeMobileSidebar()">&#129309; Teams</a>
          <a href="#" data-page="apps" class="${state.page === "apps" ? "active" : ""}" onclick="event.preventDefault();navigate('apps');closeMobileSidebar()">&#128640; Apps</a>
          <a href="#" data-page="reports" class="${state.page === "reports" ? "active" : ""}" onclick="event.preventDefault();navigate('reports');closeMobileSidebar()">&#128202; Reports</a>
          <a href="#" data-page="settings" class="${state.page === "settings" ? "active" : ""}" onclick="event.preventDefault();navigate('settings');closeMobileSidebar()">&#9881; Settings</a>
        </nav>
        <div id="gsd-indicator-slot">${state.status && state.status.gsd_workstream ? `<div class="gsd-indicator"><div class="gsd-workstream">&#9654; ${state.status.gsd_workstream}</div><div class="gsd-phase">${state.status.gsd_phase ? "Phase " + state.status.gsd_phase : ""}</div></div>` : ""}</div>
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
          <button class="ide-sidebar-toggle" onclick="ideToggleMainSidebar()" title="Toggle sidebar"><svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M9 3v18"/></svg></button>
          <h2>${{ tasks: "Mission Control", status: "Platform Status", approvals: "Approvals", tools: "Tools", skills: "Skills", agents: "Agent Profiles", apps: "Apps", reports: "Reports", settings: "Settings", detail: "Task Detail", chat: "Chat with Agent42", code: "Code with Agent42", projectDetail: "Project Detail" }[state.page] || "Dashboard"}</h2>
          <div class="topbar-actions">
            ${state.page === "tasks" ? `
              <button class="btn btn-primary btn-sm" onclick="${state.missionControlTab === 'projects' ? 'showCreateProjectModal()' : 'showCreateTaskModal()'}">+ New ${state.missionControlTab === 'projects' ? 'Project' : 'Task'}</button>
              <button class="btn btn-outline btn-sm" style="margin-left:0.5rem" onclick="state.activityOpen=!state.activityOpen;renderActivitySidebar()">Activity</button>
            ` : ""}
            ${state.page === "agents" && state.agentsViewMode === "grid" ? '<button class="btn btn-primary btn-sm" onclick="showCreateProfileModal()">+ New Profile</button>' : ""}
            ${state.page === "apps" ? '<button class="btn btn-primary btn-sm" onclick="showCreateAppModal()">+ New App</button>' : ""}
          </div>
        </div>
        <div class="content" id="page-content"></div>
        <div class="content ide-layout-parent" id="ide-persistent" style="display:none;overflow:hidden;height:calc(100vh - 48px);padding:0;flex:none;width:100%"></div>
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
    agents: renderAgents,
    teams: renderTeams,
    apps: renderApps,
    reports: renderReports,
    settings: renderSettings,
    detail: renderDetail,
    projectDetail: renderProjectDetail,
  };
  // Re-attach preserved IDE container after innerHTML rebuild
  if (window._ideDetached) {
    var newPlaceholder = document.getElementById("ide-persistent");
    if (newPlaceholder) {
      newPlaceholder.replaceWith(window._ideDetached);
    } else {
      // Append to .main if placeholder wasn't created
      var mainEl = document.querySelector(".main");
      if (mainEl) mainEl.appendChild(window._ideDetached);
    }
    window._ideDetached = null;
  }

  // When NOT on Code page, ensure page-content is visible and IDE is hidden
  if (state.page !== "code") {
    var _pc = document.getElementById("page-content");
    var _ip = document.getElementById("ide-persistent");
    if (_pc) _pc.style.display = "";
    if (_ip) _ip.style.display = "none";
  }

  (renderers[state.page] || renderTasks)();

  // Re-apply sidebar collapsed state after render (persists across navigation)
  if (_ideMainSidebarCollapsed) {
    var sidebar = document.querySelector(".sidebar");
    var main = document.querySelector(".main");
    if (sidebar) sidebar.style.display = "none";
    if (main) { main.style.marginLeft = "48px"; main.style.width = "calc(100% - 48px)"; }
    var miniBar = document.getElementById("ide-mini-sidebar");
    if (miniBar) {
      miniBar.style.display = "flex";
      var btns = miniBar.querySelectorAll('.ide-mini-btn');
      var pages = ['tasks','status','approvals','chat','code','tools','skills','agents','teams','apps','reports','settings'];
      btns.forEach(function(b, i) { b.classList.toggle('active', pages[i] === state.page); });
    }
  }
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

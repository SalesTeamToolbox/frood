/* Agent42 Dashboard — Single-page Application */
"use strict";

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  token: localStorage.getItem("agent42_token") || "",
  setupNeeded: null,  // null = checking, true = show wizard, false = show login/app
  setupStep: 1,       // 1 = password, 2 = API key, 3 = memory, 4 = done
  page: "apps",
  wsConnected: false,
  settingsTab: "providers",
  tokenStats: null,
  tools: [],
  skills: [],
  channels: [],
  providers: {},
  health: {},
  // Apps
  apps: [],
  appFilter: "",  // "" = all, "running", "stopped", "building", etc.
  // API key management
  apiKeys: {},
  keyEdits: {},
  keySaving: false,
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
  // Reports
  reportsData: null,
  reportsLoading: false,
  reportsTab: "overview",
  // Tool/skill search state
  _toolSearch: "",
  _skillSearch: "",
  _expandedTool: null,
  _expandedSkill: null,
  // Provider status
  providerStatus: null,
  providerStatusLoading: false,
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
  "There\u2019s a frood who really knows where his towel is.",
  "The ships hung in the sky in much the same way that bricks don\u2019t.",
  "Ford, you\u2019re turning into a penguin. Stop it.",
];

// Frood towel avatar SVG — the essential hitchhiker's companion
const AGENT42_AVATAR = `<img src="/assets/agent42-avatar.svg" alt="Frood" width="20" height="20" style="border-radius:50%">`;

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
// Workspace namespace conventions (Phase 1: definition only)
// Phase 2 will migrate ideOpenFile() and storage call sites to use these.
// ---------------------------------------------------------------------------
var WORKSPACE_URI_SCHEME = "workspace";

/**
 * Build a Monaco-compatible URI for a file in a specific workspace.
 * Format: "workspace://{workspaceId}/{filePath}"
 * @param {string} workspaceId - 12-char hex workspace ID
 * @param {string} filePath - relative file path within workspace
 * @returns {string} workspace URI string
 */
function makeWorkspaceUri(workspaceId, filePath) {
  return WORKSPACE_URI_SCHEME + "://" + workspaceId + "/" + filePath.replace(/^\//, "");
}

/**
 * Build a workspace-namespaced storage key.
 * Format: "ws_{workspaceId}_{key}"
 * @param {string} workspaceId - 12-char hex workspace ID
 * @param {string} key - the base key name (e.g., "cc_active_session", "cc_panel_width")
 * @returns {string} namespaced storage key
 */
function wsKey(workspaceId, key) {
  return "ws_" + workspaceId + "_" + key;
}

// Storage key namespace mapping (Phase 2 will migrate these call sites):
//   wsKey(id, "cc_active_session")    replaces  "cc_active_session"
//   wsKey(id, "cc_panel_width")       replaces  "cc_panel_width"
//   wsKey(id, "cc_panel_session_id")  replaces  "cc_panel_session_id"
//
// Keys that stay GLOBAL (no namespace prefix):
//   "agent42_token"   — auth is workspace-independent
//   "a42_first_done"  — one-time onboarding flag
//
// Keys that stay SESSION-SCOPED (no workspace prefix needed):
//   "cc_hist_{sessionId}" — session UUIDs are already globally unique
// ---------------------------------------------------------------------------

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
      loadAll().then(function() { render(); updateGsdIndicator(); });
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
      updateGsdIndicator();
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
        <img src="/assets/agent42-logo-light.svg" alt="Frood" onerror="this.outerHTML='<h1>Frood<span style=&quot;color:var(--accent)&quot;>42</span></h1>'">
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
      <p class="setup-desc">Frood uses OpenRouter for LLM access. Free models work without a key, but adding one unlocks 200+ models. It\u2019s like upgrading from a towel to a Sub-Etha Sens-O-Matic.</p>
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
      <p class="setup-desc">Add semantic search and session caching for smarter agents. Frood works fully without these — a towel always gets the job done.</p>
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
  if (msg.type === "system_health") {
    updateGsdIndicator();
  } else if (msg.type === "app_status") {
    // Real-time app status update
    const idx = state.apps.findIndex((a) => a.id === msg.data.id);
    if (idx >= 0) state.apps[idx] = msg.data;
    else state.apps.unshift(msg.data);
    if (state.page === "apps") renderApps();
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
async function loadStorageStatus() {
  try {
    state.storageStatus = (await api("/settings/storage")) || null;
  } catch { state.storageStatus = null; }
}

async function loadTokenStats() {
  try {
    state.tokenStats = (await api("/stats/tokens")) || null;
  } catch { state.tokenStats = null; }
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

async function saveZenDefaultModel() {
  var sel = document.getElementById('zen-default-model');
  if (!sel) return;
  var model = sel.value;
  try {
    await api('/settings/env', {
      method: 'PUT',
      body: JSON.stringify({ settings: { ZEN_DEFAULT_MODEL: model } }),
    });
    if (state.envSettings) state.envSettings['ZEN_DEFAULT_MODEL'] = model;
    toast('Zen default model set to ' + model, 'success');
  } catch (e) {
    toast('Failed to save: ' + e.message, 'error');
  }
}

async function toggleZenAllowPaid(enabled) {
  var val = enabled ? 'true' : 'false';
  try {
    await api('/settings/env', {
      method: 'PUT',
      body: JSON.stringify({ settings: { ZEN_ALLOW_PAID: val } }),
    });
    if (state.envSettings) state.envSettings['ZEN_ALLOW_PAID'] = val;
    toast(enabled ? 'Paid Zen models enabled' : 'Paid models disabled (free only)', 'success');
    renderSettingsPanel();
  } catch (e) {
    toast('Failed to save: ' + e.message, 'error');
  }
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

// ---------------------------------------------------------------------------
// Navigation
// ---------------------------------------------------------------------------
function navigate(page, data) {
  state.page = page;
  if (data) {
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

function renderTools() {
  var el = document.getElementById("page-content");
  if (!el || state.page !== "tools") return;
  var searchVal = (state._toolSearch || "").toLowerCase();
  var filtered = state.tools.filter(function(t) {
    if (!searchVal) return true;
    return (t.name || "").toLowerCase().includes(searchVal) || (t.description || "").toLowerCase().includes(searchVal);
  });
  var rows = filtered.map(function(t) {
    var enabled = t.enabled !== false;
    var toggleId = "tool-toggle-" + esc(t.name);
    var isExpanded = state._expandedTool === t.name;
    var category = _CODE_ONLY_TOOLS.has(t.name) ? "code" : "general";
    var srcBadge = '<span class="badge-source badge-' + esc(t.source || "builtin") + '">' + esc(t.source || "builtin") + '</span>';
    var catBadge = '<span class="badge-category badge-' + category + '">' + category + '</span>';
    var detail = isExpanded ? '<tr class="tool-detail-row"><td colspan="4"><div class="tool-detail-panel"><div class="tool-detail-desc">' + esc(t.description || "No description") + '</div><div class="tool-detail-meta">' + srcBadge + ' ' + catBadge + '</div></div></td></tr>' : '';
    return '<tr style="' + (enabled ? '' : 'opacity:0.55') + ';cursor:pointer" onclick="state._expandedTool=(state._expandedTool===\'' + esc(t.name) + '\')?null:\'' + esc(t.name) + '\';renderTools()">' +
      '<td style="font-weight:600">' + esc(t.name) + (isExpanded ? ' &#9660;' : ' &#9654;') + '</td>' +
      '<td style="color:var(--text-secondary)">' + esc(t.description || '') + '</td>' +
      '<td style="text-align:center">' + srcBadge + '</td>' +
      '<td style="text-align:center"><label class="toggle-switch" title="' + (enabled ? 'Disable' : 'Enable') + ' ' + esc(t.name) + '" onclick="event.stopPropagation()"><input type="checkbox" id="' + toggleId + '" ' + (enabled ? 'checked' : '') + ' onchange="toggleTool(\'' + esc(t.name) + '\', this.checked)"><span class="toggle-slider"></span></label></td></tr>' + detail;
  }).join('');
  el.innerHTML = '<div class="card"><div class="card-header"><h3>Registered Tools (' + filtered.length + '/' + state.tools.length + ')</h3></div><div class="tool-search-wrap"><input type="text" class="tool-search-input" placeholder="Search tools by name or description..." value="' + esc(state._toolSearch || '') + '" oninput="state._toolSearch=this.value;renderTools()"></div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Description</th><th style="text-align:center;width:80px">Source</th><th style="text-align:center;width:80px">Enabled</th></tr></thead><tbody>' + (rows || '<tr><td colspan="4"><div class="empty-state">No tools match filter</div></td></tr>') + '</tbody></table></div></div>';
}

function renderSkills() {
  var el = document.getElementById("page-content");
  if (!el || state.page !== "skills") return;
  var searchVal = (state._skillSearch || "").toLowerCase();
  var filtered = state.skills.filter(function(s) {
    if (!searchVal) return true;
    return (s.name || "").toLowerCase().includes(searchVal) || (s.description || "").toLowerCase().includes(searchVal);
  });
  var rows = filtered.map(function(s) {
    var enabled = s.enabled !== false;
    var toggleId = "skill-toggle-" + esc(s.name);
    var isExpanded = state._expandedSkill === s.name;
    var taskBadges = (s.task_types || []).map(function(t) { return '<span class="badge-type">' + esc(t) + '</span>'; }).join(' ');
    var detail = isExpanded ? '<tr class="skill-detail-row"><td colspan="5"><div class="tool-detail-panel"><div class="tool-detail-desc">' + esc(s.description || 'No description') + '</div><div class="tool-detail-meta">' + (taskBadges ? '<div>Task types: ' + taskBadges + '</div>' : '') + '<div>Auto-load: ' + (s.always_load ? '<span style="color:var(--success)">Yes</span>' : 'No') + '</div></div></div></td></tr>' : '';
    return '<tr style="' + (enabled ? '' : 'opacity:0.55') + ';cursor:pointer" onclick="state._expandedSkill=(state._expandedSkill===\'' + esc(s.name) + '\')?null:\'' + esc(s.name) + '\';renderSkills()">' +
      '<td style="font-weight:600">' + esc(s.name) + (isExpanded ? ' &#9660;' : ' &#9654;') + '</td>' +
      '<td style="color:var(--text-secondary)">' + esc(s.description || '') + '</td>' +
      '<td>' + taskBadges + '</td>' +
      '<td>' + (s.always_load ? '<span style="color:var(--success)">Always</span>' : '') + '</td>' +
      '<td style="text-align:center"><label class="toggle-switch" title="' + (enabled ? 'Disable' : 'Enable') + ' ' + esc(s.name) + '" onclick="event.stopPropagation()"><input type="checkbox" id="' + toggleId + '" ' + (enabled ? 'checked' : '') + ' onchange="toggleSkill(\'' + esc(s.name) + '\', this.checked)"><span class="toggle-slider"></span></label></td></tr>' + detail;
  }).join('');
  el.innerHTML = '<div class="card"><div class="card-header"><h3>Loaded Skills (' + filtered.length + '/' + state.skills.length + ')</h3></div><div class="tool-search-wrap"><input type="text" class="tool-search-input" placeholder="Search skills by name or description..." value="' + esc(state._skillSearch || '') + '" oninput="state._skillSearch=this.value;renderSkills()"></div><div class="table-wrap"><table><thead><tr><th>Name</th><th>Description</th><th>Task Types</th><th>Auto-load</th><th style="text-align:center;width:80px">Enabled</th></tr></thead><tbody>' + (rows || '<tr><td colspan="5"><div class="empty-state">No skills match filter</div></td></tr>') + '</tbody></table></div></div>';
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
    <details class="platform-info" style="margin-bottom:1rem;padding:0.5rem 0.75rem;border:1px solid var(--border);border-radius:6px;font-size:0.82rem;color:var(--text-muted)">
      <summary style="cursor:pointer;color:var(--text-secondary);font-weight:500">What do sandboxed apps get from Agent42?</summary>
      <div style="margin-top:0.5rem;line-height:1.6">
        <strong style="color:var(--text-primary)">Every app runs in an isolated sandbox with access to:</strong><br>
        &bull; <strong>Memory</strong> &mdash; Semantic search via ONNX embeddings + Qdrant (shared or per-app namespace)<br>
        &bull; <strong>AI Agents</strong> &mdash; Assign agents to app tasks with tiered model routing (L1/L2/free fallback)<br>
        &bull; <strong>Monitoring</strong> &mdash; Health checks, auto-restart, log streaming, and status in this dashboard<br>
        &bull; <strong>Workspaces</strong> &mdash; Each app can be opened as a workspace tab for editing + terminal access<br>
        &bull; <strong>Git Integration</strong> &mdash; Per-app GitHub repo with push-on-build and version tracking<br>
        &bull; <strong>Security</strong> &mdash; Path sandboxing, command filtering, and optional dashboard auth for public apps<br>
        &bull; <strong>Port Management</strong> &mdash; Auto-assigned ports with reverse proxy for clean URLs
      </div>
    </details>
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

// the existing innerHTML pattern used throughout this file (55+ inline handlers).

function renderMemorySystemCard() {
  const ss = state.storageStatus;
  if (!ss) return '<div class="card status-section" style="margin-bottom:1.5rem"><div class="card-header"><h3>Memory System</h3></div><div class="card-body"><p style="color:var(--text-muted)">Loading...</p></div></div>';
  const qStatus = ss.qdrant?.status || "unknown";
  const rStatus = ss.redis?.status || "unknown";
  const qBadge = qStatus === "connected" ? "badge-success" : "badge-danger";
  const rBadge = rStatus === "connected" ? "badge-success" : "badge-danger";
  const qUrl = ss.qdrant?.url || ss.qdrant?.local_path || "embedded";
  const rUrl = ss.redis?.url || "not configured";
  const synced = ss.cc_sync?.total_synced || 0;
  const lastSync = ss.cc_sync?.last_sync ? new Date(ss.cc_sync.last_sync * 1000).toLocaleString() : "never";
  const consScanned = ss.consolidation?.last_scanned || 0;
  const consRemoved = ss.consolidation?.last_removed || 0;
  return `<div class="card status-section" style="margin-bottom:1.5rem">
    <div class="card-header"><h3>Memory System</h3></div>
    <div class="card-body">
      <p style="color:var(--text-muted);margin-bottom:0.75rem">ONNX embeddings + Qdrant vector search + Redis session cache.</p>
      <div class="status-metric-row"><span class="metric-label">Qdrant</span><span class="badge ${qBadge}" style="font-size:0.8rem">${esc(qStatus)}</span></div>
      <div class="status-metric-row"><span class="metric-label" style="padding-left:1rem">URL</span><span class="metric-value" style="font-size:0.8rem;color:var(--text-muted)">${esc(qUrl)}</span></div>
      <div class="status-metric-row"><span class="metric-label">Redis</span><span class="badge ${rBadge}" style="font-size:0.8rem">${esc(rStatus)}</span></div>
      <div class="status-metric-row"><span class="metric-label" style="padding-left:1rem">URL</span><span class="metric-value" style="font-size:0.8rem;color:var(--text-muted)">${esc(rUrl)}</span></div>
      <div style="margin-top:0.75rem;border-top:1px solid var(--border);padding-top:0.75rem">
        <div class="status-metric-row"><span class="metric-label">CC Memories Synced</span><span class="metric-value">${synced}</span></div>
        <div class="status-metric-row"><span class="metric-label">Last Sync</span><span class="metric-value" style="font-size:0.8rem">${lastSync}</span></div>
        <div class="status-metric-row"><span class="metric-label">Consolidation Scanned</span><span class="metric-value">${consScanned}</span></div>
        <div class="status-metric-row"><span class="metric-label">Duplicates Removed</span><span class="metric-value">${consRemoved}</span></div>
      </div>
      <div style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-muted)">Mode: ${esc(ss.mode || "unknown")}${ss.configured_mode && ss.configured_mode !== ss.mode ? " (configured: " + esc(ss.configured_mode) + ")" : ""}</div>
    </div>
  </div>`;
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
      <p style="color:var(--text-muted);font-size:0.85rem;margin-top:0.75rem">Model routing is handled by Agent42's tiered routing. Token usage below reflects API calls (embeddings, media, search).</p>
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
      <p style="color:var(--text-muted);margin-bottom:1rem">Agent42 operates as an MCP server and plugin for CLI harnesses.</p>
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
    { id: "channels", label: "Channels" },
    { id: "security", label: "Security" },
    { id: "orchestrator", label: "Orchestrator" },
    { id: "storage", label: "Storage & Paths" },
    { id: "memory", label: "Memory & Learning" },
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
    providers: () => {
      // Section 1: Routing info box (D-04)
      var html = '<h3>LLM Providers</h3>';
      html += '<div class="form-group" style="background:var(--bg-card);border:1px solid var(--border);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem">';
      html += '<h4 style="margin:0 0 0.75rem;font-size:0.95rem;color:var(--text)">Provider Routing</h4>';
      html += '<div class="help" style="line-height:1.7">';
      html += 'Agent42 routes tasks in priority order: <strong>OpenCode Zen</strong> (free/paid primary) &rarr; <strong>OpenRouter</strong> (200+ models) &rarr; <strong>Anthropic</strong> &rarr; <strong>OpenAI</strong>.<br>';
      html += 'Configure keys for the providers you want to enable. Providers without keys are skipped gracefully.';
      html += '</div></div>';

      if (!state.providerStatus && !state.providerStatusLoading) {
        loadProviderStatus().then(renderSettingsPanel);
      }

      // Section 2: API Key Providers
      html += '<h4 style="margin:0 0 0.75rem;font-size:0.95rem">LLM Providers</h4>';
      html += settingSecret("ZEN_API_KEY", "OpenCode Zen API Key", "Primary provider. Free models: Qwen3.6 Plus, MiniMax M2.5, Nemotron 3 Super. Get one at opencode.ai/auth.", true);
      html += settingSecret("OPENROUTER_API_KEY", "OpenRouter API Key", "200+ models via one key. Paid fallback. Get one at openrouter.ai/keys.");
      html += settingSecret("ANTHROPIC_API_KEY", "Anthropic API Key", "Direct Claude access (Opus/Sonnet). Get one at console.anthropic.com.");
      html += settingSecret("OPENAI_API_KEY", "OpenAI API Key", "Direct GPT access (GPT-4o, o3). Get one at platform.openai.com/api-keys.");
      html += settingSecret("GEMINI_API_KEY", "Gemini API Key", "Google AI models and embeddings. Get one at aistudio.google.com.");

      // Section 4: Provider Connectivity (D-12, D-13, D-14)
      html += '<h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Provider Connectivity</h4>';
      var ps = state.providerStatus;
      if (ps && ps.providers && ps.providers.length > 0) {
        var statusLabelMap = { ok: 'Connected', auth_error: 'Auth error', timeout: 'Timeout', unconfigured: 'Not configured', unreachable: 'Unreachable' };
        var statusDotMap = { ok: 'h-ok', auth_error: 'h-auth_error', timeout: 'h-timeout', unconfigured: 'h-unavailable', unreachable: 'h-error' };
        html += '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;margin-bottom:0.5rem">';
        html += '<thead><tr style="border-bottom:1px solid var(--border)"><th style="text-align:left;padding:0.3rem 0.5rem;color:var(--text-muted)">Provider</th><th style="text-align:left;padding:0.3rem 0.5rem;color:var(--text-muted)">Status</th></tr></thead><tbody>';
        ps.providers.forEach(function(p) {
          var dot = statusDotMap[p.status] || 'h-error';
          var label = statusLabelMap[p.status] || esc(p.status);
          html += '<tr style="border-bottom:1px solid var(--border)">';
          html += '<td style="padding:0.35rem 0.5rem">' + esc(p.label) + '</td>';
          html += '<td style="padding:0.35rem 0.5rem;display:flex;align-items:center;gap:0.4rem"><span class="health-dot ' + dot + '"></span>' + label + '</td>';
          html += '</tr>';
        });
        html += '</tbody></table>';
        html += '<div class="help" style="font-size:0.77rem"><a href="#" onclick="state.providerStatus=null;renderSettingsPanel();return false">Refresh</a></div>';
      } else {
        html += '<div class="help">' + (state.providerStatusLoading ? 'Checking connectivity...' : 'Status unavailable.') + '</div>';
      }

      // Section 4b: Zen Proxy Model picker + paid toggle
      html += '<h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Zen Proxy Model</h4>';
      html += '<div style="margin-bottom:0.75rem;font-size:0.85rem;color:var(--text-muted)">Default model for Claude Code CLI / VS Code through the Zen proxy. On rate limit, falls back through other free models automatically.</div>';
      var zenFreeModels = [
        { id: 'qwen3.6-plus-free', label: 'Qwen 3.6 Plus', desc: 'Fast, general purpose' },
        { id: 'minimax-m2.5-free', label: 'MiniMax M2.5', desc: 'Creative, marketing' },
        { id: 'nemotron-3-super-free', label: 'Nemotron 3 Super', desc: 'Reasoning, analysis' },
        { id: 'big-pickle', label: 'Big Pickle', desc: 'Content generation' },
        { id: 'trinity-large-preview-free', label: 'Trinity Large', desc: 'Preview model' },
      ];
      var zenPaidModels = [
        { id: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
        { id: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
        { id: 'gpt-5.4', label: 'GPT-5.4' },
        { id: 'gpt-5.4-pro', label: 'GPT-5.4 Pro' },
        { id: 'gemini-3.1-pro', label: 'Gemini 3.1 Pro' },
        { id: 'kimi-k2.5', label: 'Kimi K2.5' },
        { id: 'minimax-m2.5', label: 'MiniMax M2.5 (Paid)' },
        { id: 'glm-5', label: 'GLM-5' },
      ];
      var currentZenModel = state.envSettings && state.envSettings['ZEN_DEFAULT_MODEL'] || 'qwen3.6-plus-free';
      var allowPaid = state.envSettings && state.envSettings['ZEN_ALLOW_PAID'] === 'true';
      html += '<select id="zen-default-model" style="width:100%;padding:0.5rem;background:var(--card-bg);color:var(--text);border:1px solid var(--border);border-radius:6px;font-size:0.9rem">';
      html += '<optgroup label="Free Models (no credits needed)">';
      zenFreeModels.forEach(function(m) {
        var sel = m.id === currentZenModel ? ' selected' : '';
        html += '<option value="' + esc(m.id) + '"' + sel + '>' + esc(m.label) + ' \u2014 ' + esc(m.desc) + '</option>';
      });
      html += '</optgroup>';
      if (allowPaid) {
        html += '<optgroup label="Paid Models (requires Zen credits)">';
        zenPaidModels.forEach(function(m) {
          var sel = m.id === currentZenModel ? ' selected' : '';
          html += '<option value="' + esc(m.id) + '"' + sel + '>\ud83d\udcb3 ' + esc(m.label) + '</option>';
        });
        html += '</optgroup>';
      }
      html += '</select>';
      html += '<div style="margin-top:0.6rem;display:flex;align-items:center;gap:0.75rem">';
      html += '<button onclick="saveZenDefaultModel()" style="padding:0.4rem 1rem;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:0.85rem">Save</button>';
      html += '<label style="display:flex;align-items:center;gap:0.4rem;font-size:0.85rem;cursor:pointer">';
      html += '<input type="checkbox" id="zen-allow-paid" ' + (allowPaid ? 'checked' : '') + ' onchange="toggleZenAllowPaid(this.checked)" style="cursor:pointer">';
      html += '<span>Allow paid models</span></label>';
      html += '</div>';
      if (allowPaid) {
        html += '<div style="margin-top:0.5rem;padding:0.5rem;background:rgba(255,170,0,0.1);border:1px solid rgba(255,170,0,0.3);border-radius:4px;font-size:0.8rem;color:#ffa500">\u26a0\ufe0f Paid models consume Zen wallet credits. Make sure your account has funds at opencode.ai/billing.</div>';
      }
      html += '<div style="margin-top:0.5rem;font-size:0.8rem;color:var(--text-muted)"><strong>Tip:</strong> In Claude Code CLI, use <code>zen:model-name</code> as the model to bypass the default (e.g. <code>--model zen:nemotron-3-super-free</code>).</div>';

      // Section 5: Media & Search (D-02, D-03)
      html += '<h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Media &amp; Search</h4>';
      html += settingSecret("REPLICATE_API_TOKEN", "Replicate API Token", "For FLUX image generation and CogVideoX video. Get one at replicate.com.");
      html += settingSecret("LUMA_API_KEY", "Luma AI API Key", "For Luma Ray2 premium video generation.");
      html += settingSecret("BRAVE_API_KEY", "Brave Search API Key", "For web search tool. Get one at brave.com/search/api.");

      // Section 6: Save button
      html += '<div class="form-group" style="margin-top:1.5rem">';
      html += '<button class="btn btn-primary" id="save-keys-btn" onclick="saveApiKeys()" ' + (Object.keys(state.keyEdits).length === 0 || state.keySaving ? 'disabled' : '') + '>';
      html += state.keySaving ? 'Saving...' : 'Save API Keys';
      html += '</button>';
      html += '<div class="help" style="margin-top:0.5rem">Keys saved here override <code>.env</code> values and take effect immediately for new API calls.</div>';
      html += '</div>';

      return html;
    },
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
    memory: function() {
      var html = '<h3>Memory &amp; Learning</h3>';
      html += '<p class="section-desc">Memory operation statistics, learning extraction controls, and storage backend status.</p>';
      if (!state.memoryStats) {
        if (!state.memoryStatsLoading) {
          state.memoryStatsLoading = true;
          fetch('/api/memory/stats', { headers: { 'Authorization': 'Bearer ' + state.token } })
            .then(function(r) { return r.json(); })
            .then(function(d) { state.memoryStats = d; state.memoryStatsLoading = false; renderSettingsPanel(); })
            .catch(function() { state.memoryStatsLoading = false; renderSettingsPanel(); });
        }
        html += '<p class="help">Loading memory stats...</p>';
      } else {
        var ms = state.memoryStats;
        html += '<div class="stats-row" style="margin-bottom:1.5rem">';
        html += '<div class="stat-card" style="text-align:center"><div class="stat-value">' + esc(String(ms.recall_count || 0)) + '</div><div class="stat-label">Recalls (24h)</div></div>';
        html += '<div class="stat-card" style="text-align:center"><div class="stat-value">' + esc(String(ms.learn_count || 0)) + '</div><div class="stat-label">Learnings (24h)</div></div>';
        html += '<div class="stat-card" style="text-align:center"><div class="stat-value">' + esc(String(ms.error_count || 0)) + '</div><div class="stat-label">Errors (24h)</div></div>';
        html += '<div class="stat-card" style="text-align:center"><div class="stat-value">' + esc(String(Math.round(ms.avg_latency_ms || 0))) + ' ms</div><div class="stat-label">Avg Latency</div></div>';
        html += '</div>';
      }
      html += '<div class="form-group" style="margin-bottom:1.5rem">';
      html += '<h4 style="margin:0 0 0.5rem;font-size:0.95rem">Learning Extraction</h4>';
      var learningEnabled = (state.envSettings && state.envSettings.LEARNING_ENABLED !== 'false') ? true : false;
      html += '<label style="display:flex;align-items:center;gap:8px;cursor:pointer">';
      html += '<input type="checkbox" ' + (learningEnabled ? 'checked' : '') + ' onchange="toggleLearningEnabled(this.checked)" style="width:16px;height:16px">';
      html += '<span style="font-size:0.85rem">Enable automatic learning extraction from agent runs</span>';
      html += '</label>';
      html += '<p class="help">When enabled, Agent42 extracts learnings from completed agent runs and stores them in the knowledge base for future recall.</p>';
      html += '</div>';
      if (state.storageStatus) {
        var ss = state.storageStatus;
        html += '<h4 style="margin:0 0 0.5rem;font-size:0.95rem">Storage Backend</h4>';
        html += '<div class="form-group" style="margin-bottom:1rem"><div style="display:flex;gap:12px;flex-wrap:wrap">';
        html += '<span class="badge" style="padding:4px 8px;border-radius:4px;font-size:0.75rem;background:#dbeafe;color:#1e40af">Mode: ' + esc(ss.mode) + '</span>';
        var qdrantOk = ss.qdrant && (ss.qdrant.status === 'connected' || ss.qdrant.status === 'embedded_ok');
        html += '<span class="badge" style="padding:4px 8px;border-radius:4px;font-size:0.75rem;background:' + (qdrantOk ? '#dcfce7;color:#166534' : '#fef2f2;color:#991b1b') + '">Qdrant: ' + esc(ss.qdrant ? ss.qdrant.status : 'disabled') + '</span>';
        if (ss.redis) { html += '<span class="badge" style="padding:4px 8px;border-radius:4px;font-size:0.75rem;background:' + (ss.redis.status === 'connected' ? '#dcfce7;color:#166534' : '#fef2f2;color:#991b1b') + '">Redis: ' + esc(ss.redis.status) + '</span>'; }
        html += '</div></div>';
        if (ss.cc_sync && ss.cc_sync.last_sync) { html += '<div class="form-group" style="margin-bottom:0.5rem"><span style="font-size:0.8rem;color:var(--text-muted)">Last CC Sync: ' + esc(ss.cc_sync.last_sync) + ' (' + esc(String(ss.cc_sync.total_synced || 0)) + ' entries)</span></div>'; }
        if (ss.consolidation && ss.consolidation.last_run) { html += '<div class="form-group" style="margin-bottom:0.5rem"><span style="font-size:0.8rem;color:var(--text-muted)">Last Consolidation: ' + esc(ss.consolidation.last_run) + ' (scanned: ' + esc(String(ss.consolidation.last_scanned || 0)) + ', removed: ' + esc(String(ss.consolidation.last_removed || 0)) + ')</span></div>'; }
      }
      html += '<h4 style="margin:1.5rem 0 0.5rem;font-size:0.95rem;color:#dc2626">Danger Zone</h4>';
      html += '<p class="help" style="margin-bottom:0.75rem">Purge operations are irreversible. All entries in the selected collection will be permanently deleted.</p>';
      html += '<div style="display:flex;gap:8px;flex-wrap:wrap">';
      html += '<button class="btn btn-sm" style="background:#fef2f2;color:#dc2626;border:1px solid #fca5a5" onclick="confirmPurgeCollection(\'memory\')">Purge Memory</button>';
      html += '<button class="btn btn-sm" style="background:#fef2f2;color:#dc2626;border:1px solid #fca5a5" onclick="confirmPurgeCollection(\'knowledge\')">Purge Knowledge</button>';
      html += '<button class="btn btn-sm" style="background:#fef2f2;color:#dc2626;border:1px solid #fca5a5" onclick="confirmPurgeCollection(\'history\')">Purge History</button>';
      html += '</div>';
      return html;
    },
  };

  el.innerHTML = (panels[state.settingsTab] || panels.providers)();
}

function toggleLearningEnabled(enabled) {
  fetch('/api/settings/env', {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json', 'Authorization': 'Bearer ' + state.token },
    body: JSON.stringify({ settings: { LEARNING_ENABLED: enabled ? 'true' : 'false' } })
  }).then(function(r) { return r.json(); }).then(function() {
    if (state.envSettings) state.envSettings.LEARNING_ENABLED = enabled ? 'true' : 'false';
    toast(enabled ? 'Learning enabled' : 'Learning disabled', 'success');
  }).catch(function() { toast('Failed to update learning setting', 'error'); });
}

function confirmPurgeCollection(collection) {
  var answer = prompt('This will permanently delete ALL entries in the "' + collection + '" collection. Type PURGE to confirm:');
  if (answer !== 'PURGE') return;
  fetch('/api/settings/memory/' + encodeURIComponent(collection), {
    method: 'DELETE',
    headers: { 'Authorization': 'Bearer ' + state.token }
  }).then(function(r) {
    if (!r.ok) throw new Error('HTTP ' + r.status);
    return r.json();
  }).then(function() {
    toast('Collection "' + collection + '" purged successfully', 'success');
    state.memoryStats = null;
    state.memoryStatsLoading = false;
    renderSettingsPanel();
  }).catch(function(e) { toast('Purge failed: ' + e.message, 'error'); });
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
  const displayValue = hasEdit ? state.keyEdits[envVar] : (configured && source === "admin" ? masked : "");
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
               value="${esc(displayValue)}"
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

async function loadProviderStatus() {
  state.providerStatusLoading = true;
  try {
    state.providerStatus = (await api("/settings/provider-status")) || null;
  } catch (e) { state.providerStatus = null; }
  state.providerStatusLoading = false;
}

async function loadAgentModels(provider) {
  var sel = document.getElementById("agent-model");
  if (!sel) return;
  while (sel.options.length > 0) sel.remove(0);
  var placeholder = new Option("Loading models...", "");
  sel.add(placeholder);
  try {
    var allModels = (await api("/agents/models")) || {};
    var providerModels = allModels[provider] || {};
    var entries = Object.entries(providerModels);
    while (sel.options.length > 0) sel.remove(0);
    if (entries.length === 0) {
      sel.add(new Option("(no models for this provider)", ""));
    } else {
      entries.forEach(function(entry) {
        var category = entry[0];
        var modelId = entry[1];
        sel.add(new Option(category + " -- " + modelId, modelId));
      });
    }
  } catch (e) {
    while (sel.options.length > 0) sel.remove(0);
    sel.add(new Option("(failed to load models)", ""));
  }
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
    loadTools(), loadSkills(), loadChannels(), loadProviders(),
    loadHealth(), loadApiKeys(), loadEnvSettings(), loadStorageStatus(), loadTokenStats(), loadGsdWorkstreams(),
    loadApps(), loadReports(),
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
            <img src="/assets/agent42-logo-light.svg" alt="Frood" onerror="this.outerHTML='<h1>Frood<span style=&quot;color:var(--accent)&quot;>42</span></h1>'">
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
          <div class="login-footer-text">A hoopy frood who really knows where his towel is</div>
        </div>
      </div>
    `;
    return;
  }


  root.innerHTML = `
    <div class="sidebar-backdrop" id="sidebar-backdrop" onclick="closeMobileSidebar()"></div>
    <div class="app-layout">
      <aside class="sidebar" id="sidebar">
        <div class="sidebar-brand"><img src="/assets/agent42-logo-light.svg" alt="Frood" height="36" onerror="this.outerHTML='Frood<span class=&quot;num&quot;>42</span>'"></div>
        <nav class="sidebar-nav">
          <a href="#" data-page="apps" class="${state.page === "apps" ? "active" : ""}" onclick="event.preventDefault();navigate('apps');closeMobileSidebar()">&#128640; Sandboxed Apps</a>
          <a href="#" data-page="tools" class="${state.page === "tools" ? "active" : ""}" onclick="event.preventDefault();navigate('tools');closeMobileSidebar()">&#128295; Tools</a>
          <a href="#" data-page="skills" class="${state.page === "skills" ? "active" : ""}" onclick="event.preventDefault();navigate('skills');closeMobileSidebar()">&#9889; Skills</a>
          <a href="#" data-page="reports" class="${state.page === "reports" ? "active" : ""}" onclick="event.preventDefault();navigate('reports');closeMobileSidebar()">&#128202; Reports</a>
          <a href="#" data-page="settings" class="${state.page === "settings" ? "active" : ""}" onclick="event.preventDefault();navigate('settings');closeMobileSidebar()">&#9881; Settings</a>
        </nav>
        <div id="gsd-indicator-slot"></div>
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
          <h2>${{ apps: "Sandboxed Apps", tools: "Tools", skills: "Skills", reports: "Reports", settings: "Settings" }[state.page] || "Dashboard"}</h2>
          <div class="topbar-actions">
            ${state.page === "apps" ? '<button class="btn btn-primary btn-sm" onclick="showCreateAppModal()">+ New App</button>' : ""}
          </div>
        </div>
        <div class="content" id="page-content"></div>
      </div>
    </div>
  `;

  // Render page content
  const renderers = {
    apps: renderApps,
    tools: renderTools,
    skills: renderSkills,
    reports: renderReports,
    settings: renderSettings,
  };

  (renderers[state.page] || renderApps)();
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
  updateGsdIndicator();
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

});

/* Frood Dashboard — Single-page Application */
"use strict";

// One-time migration: legacy -> frood namespace (Phase 53)
(function migrateStorage() {
  if (!localStorage.getItem("frood_token")) {
    var _old = localStorage.getItem("agent42_token"); // migrate
    if (_old) { localStorage.setItem("frood_token", _old); }
  }
  localStorage.removeItem("agent42_token"); // migrate
  if (!localStorage.getItem("frood_first_done")) {
    var _oldflag = localStorage.getItem("a42_first_done"); // migrate
    if (_oldflag) { localStorage.setItem("frood_first_done", _oldflag); }
  }
  localStorage.removeItem("a42_first_done"); // migrate
})();

// ---------------------------------------------------------------------------
// State
// ---------------------------------------------------------------------------
const state = {
  token: localStorage.getItem("frood_token") || "",
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
  // Provider tier counts (populated by /api/settings/probe-models or initial load)
  providerTiers: {},
  // Reports
  reportsData: null,
  memoryStats: null,
  effectivenessStats: null,
  reportsLoading: false,
  reportsTab: "overview",
  // Activity Feed
  activityEvents: [],
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
const FROOD_AVATAR = `<img src="/assets/frood-avatar.svg" alt="Frood" width="20" height="20" style="border-radius:50%">`;

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
//   "frood_token"     — auth is workspace-independent
//   "frood_first_done" — one-time onboarding flag
//
// Keys that stay SESSION-SCOPED (no workspace prefix needed):
//   "cc_hist_{sessionId}" — session UUIDs are already globally unique
// ---------------------------------------------------------------------------

// ---------------------------------------------------------------------------
// API helpers
// ---------------------------------------------------------------------------
const API = "/api";

// Cross-tab auth synchronization
const _authChannel = typeof BroadcastChannel !== "undefined" ? new BroadcastChannel("frood_auth") : null;
if (_authChannel) {
  _authChannel.onmessage = (ev) => {
    if (ev.data?.type === "logout") {
      state.token = "";
      localStorage.removeItem("frood_token");
      if (ws) ws.close();
      render();
    } else if (ev.data?.type === "login" && ev.data?.token) {
      state.token = ev.data.token;
      localStorage.setItem("frood_token", ev.data.token);
      connectWS();
      loadAll().then(function() { render(); });
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
    localStorage.removeItem("frood_token");

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
    localStorage.setItem("frood_token", data.token);
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
        <img src="/assets/frood-logo-light.svg" alt="Frood" onerror="this.outerHTML='<h1>Frood<span style=&quot;color:var(--accent)&quot;>42</span></h1>'">
      </div>
      <p class="setup-subtitle">The answer to life, the universe, and intelligent tools.</p>
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
        <p class="setup-desc" style="margin-bottom:0">You are now a hoopy frood who really knows where their towel is. Launching Frood Dashboard\u2026</p>
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
  if (msg.type === "app_status") {
    // Real-time app status update
    const idx = state.apps.findIndex((a) => a.id === msg.data.id);
    if (idx >= 0) state.apps[idx] = msg.data;
    else state.apps.unshift(msg.data);
    if (state.page === "apps") renderApps();
  } else if (msg.type === "intelligence_event") {
    state.activityEvents = [msg.data, ...(state.activityEvents || [])].slice(0, 200);
    if (state.page === "activity") renderActivity();
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

// ---- CLI Setup loader + toggle (Phase 01: cross-cli-setup-core, DASH-03) ----
async function loadCliSetup() {
  try {
    state.cliSetup = (await api("/cli-setup/detect")) || {};
  } catch (e) {
    state.cliSetup = { _error: e.message || "Failed to detect CLIs" };
  }
}

async function toggleCliSetup(cli, enabled) {
  try {
    await api(`/cli-setup/wire`, {
      method: "POST",
      body: JSON.stringify({ cli, enabled }),
    });
    toast(`CLI '${cli}' ${enabled ? "wired" : "unwired"}`, "success");
  } catch (e) {
    toast("Failed to toggle CLI: " + e.message, "error");
  } finally {
    await loadCliSetup();
    renderCliSetup();
  }
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
      toast("Packages installed. Restart Frood to activate the storage backend.", "success");
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

async function toggleAllowPaid(envKey, enabled) {
  var val = enabled ? 'true' : 'false';
  var payload = {};
  payload[envKey] = val;
  try {
    await api('/settings/env', {
      method: 'PUT',
      body: JSON.stringify({ settings: payload }),
    });
    if (state.envSettings) state.envSettings[envKey] = val;
    toast(enabled ? (envKey + ' enabled — paid models eligible') : (envKey + ' disabled — free-only'), 'success');
    renderSettingsPanel();
  } catch (e) {
    toast('Failed to save: ' + e.message, 'error');
  }
}

async function reprobeModels() {
  toast('Probing providers...', 'info');
  try {
    var result = await api('/settings/probe-models', { method: 'POST' });
    if (result && result.providers) {
      state.providerTiers = result.providers;
      var ran = (result.ran || []).join(', ') || 'none';
      toast('Probe complete (ran: ' + ran + ')', 'success');
      renderSettingsPanel();
    } else {
      toast('Probe returned unexpected response', 'error');
    }
  } catch (e) {
    toast('Probe failed: ' + e.message, 'error');
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
      localStorage.setItem("frood_token", data.token);
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
    localStorage.setItem("frood_token", data.token);

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
  localStorage.removeItem("frood_token");

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
            <option value="internal">Internal (Frood system tool)</option>
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
    var category = "general";
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

function renderCliSetup() {
  // CLI Setup panel (Phase 01: cross-cli-setup-core, DASH-03)
  var el = document.getElementById("page-content");
  if (!el || state.page !== "cli-setup") return;
  var data = state.cliSetup || {};
  if (data._error) {
    el.innerHTML = '<div class="card"><div class="card-header"><h3>CLI Setup</h3></div><div class="empty-state" style="color:var(--error)">Failed to detect CLIs: ' + esc(data._error) + '</div></div>';
    return;
  }
  var entries = Object.entries(data).filter(function(kv) { return !kv[0].startsWith("_"); });
  if (!entries.length) {
    el.innerHTML = '<div class="card"><div class="card-header"><h3>CLI Setup</h3></div><div class="empty-state">Detecting CLIs...</div></div>';
    return;
  }
  var rows = entries.map(function(kv) {
    var cli = kv[0];
    var info = kv[1] || {};
    var installed = info.installed ? 'installed' : 'not installed';
    var wired = info.wired ? 'wired' : 'not wired';
    var checked = info.wired ? 'checked' : '';
    var toggleId = "cli-setup-toggle-" + esc(cli);
    return '<tr>' +
      '<td style="font-weight:600">' + esc(cli) + '</td>' +
      '<td><span class="badge-source">' + esc(installed) + '</span> <span class="badge-category">' + esc(wired) + '</span></td>' +
      '<td style="text-align:center"><label class="toggle-switch" title="' + (info.wired ? 'Unwire' : 'Wire') + ' ' + esc(cli) + '"><input type="checkbox" id="' + toggleId + '" ' + checked + ' onchange="toggleCliSetup(\'' + esc(cli) + '\', this.checked)"><span class="toggle-slider"></span></label></td>' +
      '</tr>';
  }).join('');
  el.innerHTML =
    '<div class="card">' +
      '<div class="card-header"><h3>CLI Setup</h3></div>' +
      '<div style="padding:0.5rem 1rem;color:var(--text-secondary)">' +
        '<p>Frood can wire itself into other MCP-capable CLIs so they can call ' +
        '<code>frood_skill</code> to load warehoused skills/commands/agents on demand. ' +
        'Toggling here produces the same config mutations as running ' +
        '<code>frood cli-setup &lt;cli&gt;</code> / <code>frood cli-setup unwire &lt;cli&gt;</code> ' +
        'from the command line.</p>' +
        '<p><a href="https://github.com/anthropics/claude-code" target="_blank" rel="noopener">Docs</a></p>' +
      '</div>' +
      '<div class="table-wrap"><table><thead><tr><th>CLI</th><th>State</th><th style="text-align:center;width:80px">Wired</th></tr></thead><tbody>' +
        rows +
      '</tbody></table></div>' +
    '</div>';
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
      <summary style="cursor:pointer;color:var(--text-secondary);font-weight:500">What do Agent Apps get from Frood?</summary>
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
    { id: "overview", label: "Intelligence" },
    { id: "health", label: "System Health" },
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

  bodyEl.innerHTML = body;
}

function _reportsBar(pct, label, cls) {
  const p = Math.max(0, Math.min(100, pct || 0));
  const c = cls ? " " + cls : "";
  return `<div class="bar-cell"><div class="bar-fill${c}" style="width:${p}%"></div><span class="bar-label">${esc(String(label))}</span></div>`;
}

function _renderReportsOverview(d) {
  // Section 1: Intelligence Summary Cards
  const mem = state.memoryStats || {};
  const eff = state.effectivenessStats || {};
  const effStats = Array.isArray(eff.stats) ? eff.stats : [];
  const totalInvocations = effStats.reduce((s, e) => s + (e.invocations || 0), 0);
  const avgSuccess = effStats.length > 0
    ? Math.round(effStats.reduce((s, e) => s + (e.success_rate || 0), 0) / effStats.length)
    : 0;
  const cards = `<div class="reports-grid" style="grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1rem; margin-bottom: 1.5rem;">
  <div class="stat-card"><div class="stat-value">${mem.recall_count != null ? mem.recall_count : "---"}</div><div class="stat-label">Memory Recalls (24h)</div></div>
  <div class="stat-card"><div class="stat-value">${mem.learn_count != null ? mem.learn_count : "---"}</div><div class="stat-label">Learning Extractions</div></div>
  <div class="stat-card"><div class="stat-value">${mem.avg_latency_ms != null ? Math.round(mem.avg_latency_ms) + "ms" : "---"}</div><div class="stat-label">Avg Recall Latency</div></div>
  <div class="stat-card"><div class="stat-value">${avgSuccess}%</div><div class="stat-label">Tool Effectiveness</div></div>
</div>`;

  // Section 2: Routing Tier Distribution (from _routing_stats in /api/reports)
  const rs = (d && d.routing_stats) || {};
  const routingTotal = (rs.L1 || 0) + (rs.L2 || 0) + (rs.free || 0);
  const routingSection = `<div class="card" style="margin-bottom:1rem;padding:1rem;">
  <h4>Routing Tier Distribution</h4>
  ${routingTotal > 0 ? `
  <table class="data-table"><thead><tr><th>Tier</th><th>Requests</th><th>Share</th></tr></thead>
  <tbody>
    <tr><td>L1 (Workhorse)</td><td>${rs.L1 || 0}</td><td>${routingTotal ? Math.round(((rs.L1 || 0) / routingTotal) * 100) : 0}%</td></tr>
    <tr><td>L2 (Premium)</td><td>${rs.L2 || 0}</td><td>${routingTotal ? Math.round(((rs.L2 || 0) / routingTotal) * 100) : 0}%</td></tr>
    <tr><td>Free</td><td>${rs.free || 0}</td><td>${routingTotal ? Math.round(((rs.free || 0) / routingTotal) * 100) : 0}%</td></tr>
  </tbody></table>
  <p style="color:var(--text-muted);font-size:0.8rem;margin-top:0.5rem;">Total: ${routingTotal} requests since restart</p>
  ` : '<p style="color:var(--text-muted)">No routing requests yet. Counters start fresh on restart.</p>'}
</div>`;

  // Section 3: Token Spend Summary
  const tokenSection = d && d.token_usage ? `<div class="card" style="margin-bottom:1rem;padding:1rem;">
  <h4>Token Usage</h4>
  <p>Total tokens: ${(d.token_usage.total_tokens || 0).toLocaleString()}</p>
  <p>Estimated cost: $${(d.costs && d.costs.total_cost || 0).toFixed(4)}</p>
</div>` : "";

  // Section 4: Top Performing Tools
  const topTools = effStats
    .filter(e => e.invocations > 0)
    .sort((a, b) => (b.success_rate || 0) - (a.success_rate || 0))
    .slice(0, 5);
  const toolTable = topTools.length > 0 ? `<div class="card" style="margin-bottom:1rem;padding:1rem;">
  <h4>Top Performing Tools</h4>
  <table class="data-table"><thead><tr><th>Tool</th><th>Success Rate</th><th>Invocations</th></tr></thead>
  <tbody>${topTools.map(t => `<tr><td>${t.tool_name || t.name || "---"}</td><td>${Math.round(t.success_rate || 0)}%</td><td>${t.invocations || 0}</td></tr>`).join("")}</tbody></table>
</div>` : "";

  return cards + routingSection + tokenSection + toolTable;
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
      <p style="color:var(--text-muted);margin-bottom:1rem">Frood operates as an MCP server and plugin for CLI harnesses.</p>
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

function renderSettings() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "settings") return;

  const tabs = [
    { id: "providers", label: "API Keys" },
    { id: "security", label: "Security" },
    { id: "routing", label: "Routing" },
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
      html += 'Frood routes LLM requests in priority order: <strong>OpenCode Zen</strong> (free/paid primary) &rarr; <strong>OpenRouter</strong> (200+ models) &rarr; <strong>Anthropic</strong> &rarr; <strong>OpenAI</strong>.<br>';
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
       html += settingSecret("NVIDIA_API_KEY", "NVIDIA API Key", "NVIDIA models via build.nvidia.com. Get one at build.nvidia.com.");

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

      // Section 4b: Per-provider paid-model authorization + re-probe control
      html += '<h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Paid Model Authorization</h4>';
      html += '<div style="margin-bottom:0.75rem;font-size:0.85rem;color:var(--text-muted)">Routing is free-first. Enable paid models only for providers where you have credit. Frood classifies each model by probe (not filename), so the list stays accurate as catalogs change.</div>';
      var _providerLabel = {
        zen: 'OpenCode Zen',
        openrouter: 'OpenRouter',
        nvidia: 'NVIDIA',
        anthropic: 'Anthropic',
        openai: 'OpenAI',
      };
      var _providerKey = {
        zen: 'ZEN_API_KEY',
        openrouter: 'OPENROUTER_API_KEY',
        nvidia: 'NVIDIA_API_KEY',
        anthropic: 'ANTHROPIC_API_KEY',
        openai: 'OPENAI_API_KEY',
      };
      var _allowPaidEnv = {
        zen: 'ALLOW_PAID_ZEN',
        openrouter: 'ALLOW_PAID_OPENROUTER',
        nvidia: 'ALLOW_PAID_NVIDIA',
        anthropic: 'ALLOW_PAID_ANTHROPIC',
        openai: 'ALLOW_PAID_OPENAI',
      };
      html += '<table style="width:100%;border-collapse:collapse;font-size:0.85rem;margin-bottom:0.6rem"><thead><tr style="border-bottom:1px solid var(--border)">';
      html += '<th style="text-align:left;padding:0.3rem 0.5rem;color:var(--text-muted)">Provider</th>';
      html += '<th style="text-align:left;padding:0.3rem 0.5rem;color:var(--text-muted)">Free / Paid</th>';
      html += '<th style="text-align:left;padding:0.3rem 0.5rem;color:var(--text-muted)">Allow paid</th>';
      html += '</tr></thead><tbody>';
      Object.keys(_providerLabel).forEach(function(prov) {
        var hasKey = state.apiKeys && state.apiKeys[_providerKey[prov]] && state.apiKeys[_providerKey[prov]].configured;
        var tierInfo = (state.providerTiers && state.providerTiers[prov]) || {};
        var freeN = tierInfo.free || 0;
        var paidN = tierInfo.paid || 0;
        var envKey = _allowPaidEnv[prov];
        var checked = state.envSettings && state.envSettings[envKey] === 'true';
        html += '<tr style="border-bottom:1px solid var(--border);opacity:' + (hasKey ? '1' : '0.5') + '">';
        html += '<td style="padding:0.35rem 0.5rem">' + _providerLabel[prov] + '</td>';
        html += '<td style="padding:0.35rem 0.5rem;color:var(--text-muted)">' + freeN + ' free / ' + paidN + ' paid</td>';
        if (hasKey) {
          html += '<td style="padding:0.35rem 0.5rem"><label style="display:flex;align-items:center;gap:0.4rem;cursor:pointer;font-size:0.8rem"><input type="checkbox"' + (checked ? ' checked' : '') + ' onchange="toggleAllowPaid(\'' + envKey + '\', this.checked)" style="cursor:pointer"><span>Enabled</span></label></td>';
        } else {
          html += '<td style="padding:0.35rem 0.5rem;color:var(--text-muted);font-size:0.8rem">\u2014 no key</td>';
        }
        html += '</tr>';
      });
      html += '</tbody></table>';
      html += '<div style="display:flex;gap:0.5rem;align-items:center;margin-bottom:0.5rem">';
      html += '<button onclick="reprobeModels()" style="padding:0.4rem 0.9rem;background:var(--accent);color:#fff;border:none;border-radius:4px;cursor:pointer;font-size:0.85rem">Re-probe models</button>';
      html += '<div style="font-size:0.78rem;color:var(--text-muted)">Forces an immediate probe of every configured provider (normally every 6h).</div>';
      html += '</div>';

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
    routing: () => `
      <h3>Routing</h3>
      <p class="section-desc">Controls how Frood routes LLM requests, including spending controls and model routing policy.</p>

      ${settingReadonly("MAX_DAILY_API_SPEND_USD", "Daily API spend limit (USD)", "Default: 0 (unlimited). Set a positive value to cap daily spending across all providers.")}
      ${settingReadonly("MCP_SERVERS_JSON", "MCP servers config", "Path to JSON file defining MCP server connections.")}
      ${settingReadonly("CRON_JOBS_PATH", "Cron jobs file", "Default: cron_jobs.json. Scheduled task definitions.")}

      <h4 style="margin:1.5rem 0 0.75rem;font-size:0.95rem">Model Routing Policy</h4>
      ${settingSelect("MODEL_ROUTING_POLICY", "Routing policy", [
        {value: "free_only", label: "Free only — only free OpenRouter models"},
        {value: "balanced", label: "Balanced — upgrade complex tasks when OR credits available"},
        {value: "performance", label: "Performance — best model regardless of cost"},
      ], "Controls whether Frood uses paid models when OpenRouter credits are available.")}

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
            <span style="margin-left:0.75rem;font-size:0.78rem;color:var(--text-muted)">Installs <code>qdrant-client</code>${ss.redis.status === "not_installed" ? " and <code>redis[hiredis]</code>" : ""} via pip. Frood restart required after install.</span>
          </div>` : ""}
          <div style="margin-top:0.75rem;font-size:0.78rem;color:var(--text-muted)">
            Backend is configured in <code>.env</code>. To change it, edit <code>QDRANT_ENABLED</code>, <code>QDRANT_URL</code>, and <code>REDIS_URL</code> and restart Frood.
            <a href="#" onclick="loadStorageStatus().then(renderSettingsPanel);return false" style="margin-left:0.5rem">Refresh</a>
          </div>
        </div>` : `<div style="color:var(--text-muted);font-size:0.85rem;margin-bottom:1rem">Storage status unavailable.</div>`;
      return `
      <h3>Storage &amp; Paths</h3>
      <p class="section-desc">Directories where Frood stores memory, outputs, templates, and generated media.</p>

      ${backendSection}

      ${settingReadonly("MEMORY_DIR", "Memory directory", "Default: .frood/memory. Persistent memory and learning data.")}
      ${settingReadonly("SESSIONS_DIR", "Sessions directory", "Default: .frood/sessions. Channel conversation history.")}
      ${settingReadonly("OUTPUTS_DIR", "Outputs directory", "Default: .frood/outputs. Non-code task outputs (reports, analysis, etc.).")}
      ${settingReadonly("TEMPLATES_DIR", "Templates directory", "Default: .frood/templates. Content templates for reuse.")}
      ${settingReadonly("IMAGES_DIR", "Images directory", "Default: .frood/images. Generated images from image_gen tool.")}
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
      html += '<p class="help">When enabled, Frood extracts learnings from completed agent runs and stores them in the knowledge base for future recall.</p>';
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
   // API keys and service tokens are editable regardless of source (admin or env).
   // Other secret fields (channel tokens, password hash) render as read-only.
   const isAdminConfigurable = [
     "ZEN_API_KEY",
     "OPENROUTER_API_KEY",
     "ANTHROPIC_API_KEY",
     "OPENAI_API_KEY",
     "GEMINI_API_KEY",
     "NVIDIA_API_KEY",
     "REPLICATE_API_TOKEN",
     "LUMA_API_KEY",
     "BRAVE_API_KEY",
     "GITHUB_TOKEN"
   ].includes(envVar);

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
    const [reports, memStats, effStats] = await Promise.all([
      api("/reports"),
      api("/memory/stats").catch(() => null),
      api("/effectiveness/stats").catch(() => null),
    ]);
    state.reportsData = reports || null;
    state.memoryStats = memStats;
    state.effectivenessStats = effStats;
  } catch { state.reportsData = null; state.memoryStats = null; state.effectivenessStats = null; }
  state.reportsLoading = false;
}

async function loadActivity() {
  try {
    const data = await api("/activity");
    state.activityEvents = (data && data.events) || [];
  } catch { state.activityEvents = []; }
}

function updateEnvSaveBtn() {
  const btn = document.getElementById("save-env-btn");
  if (btn) {
    const hasEdits = Object.keys(state.envEdits).some(k => state.envEdits[k] !== state.envSettings[k]);
    btn.disabled = !hasEdits || state.envSaving;
  }
}

// ---------------------------------------------------------------------------
// Activity Feed
// ---------------------------------------------------------------------------
function renderActivity() {
  const el = document.getElementById("page-content");
  if (!el || state.page !== "activity") return;

  const events = state.activityEvents || [];

  if (events.length === 0) {
    el.innerHTML = '<div class="card" style="padding:2rem;text-align:center;color:var(--text-muted)">No intelligence events yet. Events appear as memory recalls, routing decisions, and learning extractions occur.</div>';
    return;
  }

  const badgeColors = {
    memory_recall: "#3b82f6",
    effectiveness: "#10b981",
    learning: "#f59e0b",
    routing: "#8b5cf6",
  };

  const badgeLabels = {
    memory_recall: "Memory",
    effectiveness: "Effectiveness",
    learning: "Learning",
    routing: "Routing",
  };

  const rows = events.map(ev => {
    const t = ev.type || "unknown";
    const d = ev.data || {};
    const ts = ev.ts ? new Date(ev.ts * 1000).toLocaleTimeString() : "";
    const badge = '<span class="activity-badge" style="background:' + (badgeColors[t] || '#6b7280') + '">' + (badgeLabels[t] || t) + '</span>';

    let detail = "";
    if (t === "memory_recall") {
      detail = (d.results != null ? d.results : 0) + " results in " + (d.latency_ms != null ? d.latency_ms : "?") + "ms (" + (d.method || "search") + ")";
    } else if (t === "effectiveness") {
      detail = (d.tool_name || "tool") + ": " + (d.success ? "success" : "failure") + " (" + (d.duration_ms != null ? d.duration_ms : 0) + "ms)";
    } else if (t === "learning") {
      detail = (d.task_type || "task") + " / " + (d.outcome || "?") + ": " + (d.summary || "");
    } else if (t === "routing") {
      detail = (d.model || "model") + " via " + (d.tier || "?") + " - " + (d.reason || "");
    } else {
      detail = JSON.stringify(d).slice(0, 120);
    }

    return '<div class="activity-event">'
      + '<div class="activity-event-header">' + badge + '<span class="activity-ts">' + ts + '</span></div>'
      + '<div class="activity-event-detail">' + detail + '</div>'
      + '</div>';
  }).join("");

  el.innerHTML = '<div class="activity-feed">' + rows + '</div>';
}

// ---------------------------------------------------------------------------
// Main render
// ---------------------------------------------------------------------------
async function loadAll() {
  await Promise.all([
    loadTools(), loadSkills(), loadProviders(),
    loadHealth(), loadApiKeys(), loadEnvSettings(), loadStorageStatus(), loadTokenStats(),
    loadApps(), loadReports(), loadActivity(),
    loadCliSetup(),
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
            <img src="/assets/frood-logo-light.svg" alt="Frood" onerror="this.outerHTML='<h1>Frood<span style=&quot;color:var(--accent)&quot;>42</span></h1>'">
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
        <div class="sidebar-brand"><img src="/assets/frood-logo-light.svg" alt="Frood" height="36" onerror="this.outerHTML='Frood<span class=&quot;num&quot;>42</span>'"></div>
        <nav class="sidebar-nav">
          <a href="#" data-page="apps" class="${state.page === "apps" ? "active" : ""}" onclick="event.preventDefault();navigate('apps');closeMobileSidebar()">&#128640; Agent Apps</a>
          <a href="#" data-page="tools" class="${state.page === "tools" ? "active" : ""}" onclick="event.preventDefault();navigate('tools');closeMobileSidebar()">&#128295; Tools</a>
          <a href="#" data-page="skills" class="${state.page === "skills" ? "active" : ""}" onclick="event.preventDefault();navigate('skills');closeMobileSidebar()">&#9889; Skills</a>
          <a href="#" data-page="cli-setup" class="${state.page === "cli-setup" ? "active" : ""}" onclick="event.preventDefault();navigate('cli-setup');closeMobileSidebar()">&#128279; CLI Setup</a>
          <a href="#" data-page="reports" class="${state.page === "reports" ? "active" : ""}" onclick="event.preventDefault();navigate('reports');closeMobileSidebar()">&#128202; Reports</a>
          <a href="#" data-page="activity" class="${state.page === "activity" ? "active" : ""}" onclick="event.preventDefault();navigate('activity');closeMobileSidebar()">&#128200; Activity</a>
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
          <h2>${{ apps: "Agent Apps", tools: "Tools", skills: "Skills", "cli-setup": "CLI Setup", reports: "Reports", activity: "Activity", settings: "Settings" }[state.page] || "Dashboard"}</h2>
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
    "cli-setup": renderCliSetup,
    reports: renderReports,
    activity: renderActivity,
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

#!/usr/bin/env node
/**
 * Cross-harness statusline + on-demand dashboard for Claude Code.
 *
 * Three modes:
 *   (default)     CC pipes this session's state on stdin; we print a TWO-LINE bar:
 *                   line 1 — CC-native: model, context bar, cost, 5h/7d rate limits, cwd
 *                   line 2 — cross-harness: latest OC session, peer-mail unread,
 *                            remote instances (named, one row each), configured repo
 *                            release trains, verify runs (📊 segment is an OSC-8 link ->
 *                            HTML dashboard, Ctrl/Cmd+click)
 *   --html        rebuild ~/.claude/harness-dashboard.html (the click-through "popup";
 *                 spawned detached from default mode whenever the file is >60s stale)
 *   --text        print the same dashboard as plain text (used by /frood-harness)
 *   --json        one JSON line for the claude-session-sidebar VS Code extension:
 *                 OC latest, global peer-mail unread + newest rows, remote-instance
 *                 probes, train/verify state, and CC's quota from the sidecar (the
 *                 only local source for it). No stdin, no git, no session listing.
 *
 * Remote instances live in ~/.claude/harness-config.json — a named list of ssh
 * aliases, each an entry to probe (today: one, disabled while no server exists;
 * more entries when there is more than one instance). Entries with
 * "enabled": false are listed but never connected; an empty list reads
 * "no remote instance". The same file also carries the release-train repos
 * ({ "repos": [{ "label", "dir" }] }), the peer-mail dist path (peerMailDist)
 * and per-alias probe targets (probeFallbacks: { alias: { host, port } }) — no
 * machine-specific values are tracked in this repo (see examples/).
 *
 * Every external read is local, bounded and fails soft: sqlite opens carry
 * busy_timeout so a live writer never blocks the TUI, remote probes are TCP
 * connects with a 400ms cap, and a 3s stdin watchdog prints whatever is ready
 * (cf. GSD's statusline stdin hang, issue #775). The statusline itself never
 * spawns git — full-fidelity session lists (titles/branches via peer-mail's
 * dist) run only in the detached --html rebuild.
 */

// Hide console windows of every child process (Windows). A detached rebuild has no console, so each git it
// runs would otherwise open a visible window and steal focus (found 2026-11-12). Same as bin/no-window.mjs.
(() => {
  if (process.platform !== "win32") return;
  const cp = require("child_process");
  const KEY = Symbol.for("orchestrator.noWindow");
  if (cp[KEY]) return;
  const hide = (o) => (o && typeof o === "object" ? { windowsHide: true, ...o } : { windowsHide: true });
  for (const name of ["spawn", "spawnSync", "execFile", "execFileSync", "exec", "execSync", "fork"]) {
    const orig = cp[name];
    cp[name] = function (cmd, ...rest) {
      let i = rest.findIndex((x) => x && typeof x === "object" && !Array.isArray(x));
      if (i === -1) { i = Array.isArray(rest[0]) ? 1 : 0; rest.splice(i, 0, {}); }
      rest[i] = hide(rest[i]);
      return orig.call(this, cmd, ...rest);
    };
  }
  cp[KEY] = true;
  try { require("module").syncBuiltinESMExports(); } catch {}
})();
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");
const net = require("node:net");
const { spawn } = require("node:child_process");
const { pathToFileURL } = require("node:url");

// ── config ──────────────────────────────────────────────────────────────────
const CLAUDE_DIR = path.join(os.homedir(), ".claude");
const DASH_HTML = path.join(CLAUDE_DIR, "harness-dashboard.html");
const CC_SIDECAR = path.join(CLAUDE_DIR, ".harness-cc.json");
const MAILBOX_DB = path.join(os.homedir(), ".local", "share", "opencode-peer-mail", "mailbox.db");
const OC_DB = path.join(os.homedir(), ".local", "share", "opencode", "opencode.db");

const REMOTES_CONFIG = path.join(CLAUDE_DIR, "harness-config.json");
// Probes are TCP connects capped at PROBE_TIMEOUT_MS each, run in parallel —
// well inside CC's 3s stdin watchdog when the bar renders.
const PROBE_TIMEOUT_MS = 400;
const DASH_STALE_MS = 15_000; // live view: rebuilt at most every 15 s while something kicks it
const VERIFY_RUNNING_MS = 10 * 60_000;
const DEPART_STALE_MS = 15 * 60_000;

// ── ANSI ────────────────────────────────────────────────────────────────────
const R = "\x1b[0m", DIM = "\x1b[2m", BOLD = "\x1b[1m";
const GREEN = "\x1b[32m", YELLOW = "\x1b[33m", ORANGE = "\x1b[38;5;208m";
const RED = "\x1b[31m", CYAN = "\x1b[36m", BLUE = "\x1b[34m", MAGENTA = "\x1b[35m";

const AUTO_COMPACT_BUFFER_PCT = 16.5;
const TITLE_MAX = 24;
const MODEL_MAX = 14;

// ── small utils ─────────────────────────────────────────────────────────────
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function age(ms) {
  const s = Math.max(0, (Date.now() - ms) / 1000);
  if (s < 60) return "now";
  if (s < 3600) return `${Math.floor(s / 60)}m`;
  if (s < 86400) return `${Math.floor(s / 3600)}h`;
  return `${Math.floor(s / 86400)}d`;
}

/** "now" doesn't take "ago" — keep prose grammatical in text/HTML. */
function ago(ms) {
  const a = age(ms);
  return a === "now" ? "just now" : `${a} ago`;
}

/** db columns may hold ms epochs, seconds, or ISO strings — normalise to ms. */
function ts(v) {
  const n = Number(v);
  if (Number.isFinite(n) && n > 0) return n > 1e12 ? n : n * 1000;
  const p = Date.parse(String(v ?? ""));
  return Number.isFinite(p) ? p : 0;
}

function shortModel(raw) {
  let id = String(raw ?? "");
  if (id.startsWith("{")) {
    // session_v2.model is a JSON blob: {"id":"provider/model","providerID":...}
    try { id = JSON.parse(id).id ?? ""; } catch { /* keep raw */ }
  }
  const last = id.split("/").pop() || "";
  return last.length > MODEL_MAX ? last.slice(0, MODEL_MAX - 1) + "…" : last;
}

function atomicWrite(file, data) {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, data);
  fs.renameSync(tmp, file);
}

function tailBytes(file, n) {
  try {
    const st = fs.statSync(file);
    const fd = fs.openSync(file, "r");
    try {
      const len = Math.min(n, st.size);
      const buf = Buffer.alloc(len);
      fs.readSync(fd, buf, 0, len, st.size - len);
      return buf.toString("utf8");
    } finally { fs.closeSync(fd); }
  } catch { return ""; }
}

function stripAnsi(s) {
  return s.replace(/\x1b\[[0-9;]*m/g, "");
}

// ── remote instances ────────────────────────────────────────────────────────
/** The repo path to name in hints. The installer renders {{ORCH_REPO}} right here; run straight from a checkout the
 *  token is still un-rendered, so fall back to ORCH_REPO or the directory above this hook. A hint never shows `{{`. */
const ORCH_REPO_DIR = (() => {
  const rendered = "{{ORCH_REPO}}";
  return (rendered.startsWith("{{") ? process.env.ORCH_REPO || path.resolve(__dirname, "..") : rendered).replace(/\\/g, "/");
})();

/** The whole harness config from ~/.claude/harness-config.json, read once per process and re-read only when the file
 *   changes (mtime or size: an edited config lands without restarting the statusline; appearing/disappearing counts).
 *   { "remotes": [{ "name", "alias", "enabled" }], "repos": [{ "label", "dir" }],
 *     "peerMailDist": "<path to sessions.js>", "probeFallbacks": { alias: { host, port } } }
 * Missing file or a bad key = that feature is off; nothing machine-specific is tracked here. */
const configCache = new Map(); // file -> { stamp, data }
function loadConfig(file = REMOTES_CONFIG) {
  let stamp = "missing";
  try {
    const st = fs.statSync(file);
    stamp = `${st.mtimeMs}:${st.size}`;
  } catch { /* missing: a state of its own, so an appearing file invalidates the cache */ }
  const hit = configCache.get(file);
  if (hit && hit.stamp === stamp) return hit.data;
  let data = {};
  try {
    const raw = JSON.parse(fs.readFileSync(file, "utf8"));
    data = raw && typeof raw === "object" && !Array.isArray(raw) ? raw : {};
  } catch {
    data = {};
  }
  configCache.set(file, { stamp, data });
  return data;
}

/** `~/...` in a config path means the home dir (the examples use it); anything else is used as-is. */
function expandHome(p) {
  return typeof p === "string" ? p.replace(/^~(?=$|[\\/])/, os.homedir()) : p;
}

/** The configured remote list. Missing file or empty list = nothing probed;
 * surfaces say "no remote instance". */
function loadRemotes(config = loadConfig()) {
  if (!Array.isArray(config.remotes)) return [];
  return config.remotes
    .filter((r) => r && typeof r.name === "string" && typeof r.alias === "string")
    .map((r) => ({ name: r.name, alias: r.alias, enabled: r.enabled !== false }));
}

/** Repos that run the release train (house rules: ops/train.sh status is file-truth). */
function loadRepos(config = loadConfig()) {
  if (!Array.isArray(config.repos)) return [];
  return config.repos
    .filter((r) => r && typeof r.label === "string" && typeof r.dir === "string")
    .map((r) => ({ label: r.label, dir: expandHome(r.dir) }));
}

/** peer-mail's dist module (full-fidelity session list); unset = that feature is off. */
function peerDistPath(config = loadConfig()) {
  const p = config.peerMailDist;
  return typeof p === "string" && p.trim() ? expandHome(p.trim()) : null;
}

/** Alias -> known target when ~/.ssh/config has no block for it. */
function probeFallbacks(config = loadConfig()) {
  const f = config.probeFallbacks;
  return f && typeof f === "object" && !Array.isArray(f) ? f : {};
}

/** Resolve HostName/Port for an alias from ~/.ssh/config (block-scoped parse). */
function sshTarget(alias) {
  const fallback = probeFallbacks()[alias] || { host: alias, port: 22 };
  try {
    const lines = fs.readFileSync(path.join(os.homedir(), ".ssh", "config"), "utf8").split(/\r?\n/);
    let inBlock = false, out = { ...fallback };
    for (const line of lines) {
      const host = line.match(/^\s*Host\s+(.+)$/i);
      if (host) {
        inBlock = host[1].split(/\s+/).some((a) => a.replace(/^\*\.?/, "") === alias);
        continue;
      }
      if (!inBlock) continue;
      const hn = line.match(/^\s*HostName\s+(\S+)/i);
      const pt = line.match(/^\s*Port\s+(\d+)/i);
      if (hn) out.host = hn[1];
      if (pt) out.port = Number(pt[1]);
    }
    return out;
  } catch { return { ...fallback }; }
}

/** TCP connect only, 400ms cap each, parallel — proves the port answers, never runs a
 * command on the box. Disabled entries are listed but never connected: up stays null. */
function probeRemotes(timeoutMs = PROBE_TIMEOUT_MS) {
  return Promise.all(loadRemotes().map((t) => new Promise((resolve) => {
    const { host, port } = sshTarget(t.alias);
    if (!t.enabled) { resolve({ ...t, host, port, up: null, ms: null }); return; }
    const t0 = Date.now();
    const sock = new net.Socket();
    let settled = false;
    const done = (up) => {
      if (settled) return;
      settled = true;
      try { sock.destroy(); } catch { /* ignore */ }
      resolve({ ...t, host, port, up, ms: Date.now() - t0 });
    };
    sock.setTimeout(timeoutMs, () => done(false));
    sock.once("connect", () => done(true));
    sock.once("error", () => done(false));
    sock.connect(port, host);
  })));
}

// ── data collectors ─────────────────────────────────────────────────────────
function openDb(dbPath) {
  if (!fs.existsSync(dbPath)) return null;
  try {
    const { DatabaseSync } = require("node:sqlite");
    const db = new DatabaseSync(dbPath, { readOnly: true });
    db.exec("PRAGMA busy_timeout=300;"); // never block the TUI behind a live writer
    return db;
  } catch { return null; }
}

/** Most recently active OpenCode session — light read, no git subprocess. */
function ocLatest() {
  const db = openDb(OC_DB);
  if (!db) return null;
  try {
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all()
      .map((t) => t.name);
    const table = tables.includes("session_v2") ? "session_v2" : "session";
    const row = db.prepare(
      `SELECT id, title, model, time_updated FROM ${table} ORDER BY time_updated DESC LIMIT 1`,
    ).get();
    if (!row) return null;
    return {
      id: String(row.id),
      title: String(row.title ?? "").replace(/\s+/g, " ").trim() || "(untitled)",
      model: shortModel(row.model),
      updated: ts(row.time_updated),
    };
  } catch { return null; }
  finally { try { db.close(); } catch { /* ignore */ } }
}

function unreadCount(sessionId) {
  if (!sessionId) return 0;
  const db = openDb(MAILBOX_DB);
  if (!db) return 0;
  try {
    const row = db.prepare(
      "SELECT COUNT(*) AS n FROM messages WHERE to_session = ? AND status = 'unread'",
    ).get(sessionId);
    return Number(row?.n ?? 0);
  } catch { return 0; }
  finally { try { db.close(); } catch { /* ignore */ } }
}

// ── can the recipient still read it? ────────────────────────────────────────
// Nobody but the recipient may read or ack mail (by design), so mail addressed to
// a session that ended is unread forever. Count only what somebody can still open:
// a recipient active within ORCH_MAIL_LIVE_H hours (default 24). Unknown = idle.
const MAIL_LIVE_H_DEFAULT = 24;
const activityCache = new Map(); // one lookup per recipient per render

/** Mail is "live" when the recipient was active within this many hours; bad/absent value = 24. */
function mailLiveHours() {
  const n = Number(process.env.ORCH_MAIL_LIVE_H);
  return Number.isFinite(n) && n > 0 ? n : MAIL_LIVE_H_DEFAULT;
}

/** Last activity of an OpenCode session (ses_* id) from session_v2, falling back to session. */
function ocSessionActivity(id, dbPath) {
  const db = openDb(dbPath);
  if (!db) return null;
  try {
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all()
      .map((t) => t.name);
    const table = tables.includes("session_v2") ? "session_v2" : tables.includes("session") ? "session" : null;
    if (!table) return null;
    const row = db.prepare(`SELECT time_updated FROM ${table} WHERE id = ?`).get(id);
    const v = ts(row?.time_updated);
    return v > 0 ? v : null;
  } catch { return null; }
  finally { try { db.close(); } catch { /* ignore */ } }
}

/** Newest mtime of <projectsDir>/<project>/<id>.jsonl (a Claude Code session transcript). */
function ccTranscriptActivity(id, projectsDir) {
  let dirs;
  try { dirs = fs.readdirSync(projectsDir); } catch { return null; }
  let newest = null;
  for (const d of dirs) {
    try {
      const m = fs.statSync(path.join(projectsDir, d, `${id}.jsonl`)).mtimeMs;
      if (newest == null || m > newest) newest = m;
    } catch { /* no transcript for that id under this project */ }
  }
  return newest;
}

/** ms epoch of the recipient's last activity, or null when it cannot be known.
 *  ses_* = an OpenCode session; anything else = a Claude Code transcript. Cached per process. */
function recipientActivity(id, opts = {}) {
  const sid = String(id ?? "");
  if (!sid) return null;
  const ocDb = opts.ocDb || OC_DB;
  const projectsDir = opts.projectsDir || path.join(CLAUDE_DIR, "projects");
  const key = `${ocDb}\0${projectsDir}\0${sid}`;
  if (activityCache.has(key)) return activityCache.get(key);
  const v = sid.startsWith("ses_")
    ? ocSessionActivity(sid, ocDb)
    : ccTranscriptActivity(sid, projectsDir);
  activityCache.set(key, v);
  return v;
}

function isLiveMail(active, now, horizonMs) {
  return active != null && now - active <= horizonMs;
}

/** Unread rows that have expired (peer-mail hard-expires mail; the column is not always there). */
function mailExpiryClause(db) {
  let cols = [];
  try { cols = db.prepare("PRAGMA table_info(messages)").all().map((c) => c.name); } catch { /* old mailbox */ }
  return cols.includes("expires_at") ? " AND expires_at > ?" : "";
}

/** Unread split by whether the recipient can still read it: { live, idle }. */
function unreadTotal(opts = {}) {
  const now = opts.now ?? Date.now();
  const db = openDb(opts.mailboxDb || MAILBOX_DB);
  if (!db) return { live: 0, idle: 0 };
  try {
    const expiry = mailExpiryClause(db);
    const rows = db.prepare(
      `SELECT to_session FROM messages WHERE status = 'unread'${expiry}`,
    ).all(...(expiry ? [now] : []));
    const horizon = mailLiveHours() * 3600_000;
    let live = 0, idle = 0;
    for (const r of rows) {
      if (isLiveMail(recipientActivity(r.to_session, opts), now, horizon)) live++;
      else idle++;
    }
    return { live, idle };
  } catch { return { live: 0, idle: 0 }; }
  finally { try { db.close(); } catch { /* ignore */ } }
}

/** Unread rows for the dashboards, newest first, each with `idle` and the recipient's `active`
 *  time. `{ liveOnly: true }` keeps only rows somebody can still read. */
function recentUnread(limit = 20, opts = {}) {
  const now = opts.now ?? Date.now();
  const db = openDb(opts.mailboxDb || MAILBOX_DB);
  if (!db) return [];
  try {
    const expiry = mailExpiryClause(db);
    const horizon = mailLiveHours() * 3600_000;
    const rows = db.prepare(
      `SELECT ts, from_title, from_branch, subject, to_session FROM messages
       WHERE status = 'unread'${expiry} ORDER BY ts DESC`,
    ).all(...(expiry ? [now] : [])).map((r) => {
      const active = recipientActivity(r.to_session, opts);
      return {
        ts: ts(r.ts),
        from_title: String(r.from_title ?? ""),
        from_branch: String(r.from_branch ?? ""),
        subject: String(r.subject ?? ""),
        to_session: String(r.to_session ?? ""),
        idle: !isLiveMail(active, now, horizon),
        active,
      };
    });
    const shown = opts.liveOnly ? rows.filter((r) => !r.idle) : rows;
    return Number.isFinite(limit) && limit >= 0 ? shown.slice(0, limit) : shown;
  } catch { return []; }
  finally { try { db.close(); } catch { /* ignore */ } }
}

// ── related sessions for a focused session (--json --for <id>) ──────────────
// The TUI panel shows only OTHER harnesses' sessions related to the one being
// viewed: same orchestrator stream, peer-mail thread, or working directory.
// Same-harness sessions are visible as tabs already — listing them is noise.

function ocSessionById(sid, dbPath) {
  const db = openDb(dbPath);
  if (!db) return null;
  try {
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all()
      .map((t) => t.name);
    const table = tables.includes("session_v2") ? "session_v2" : tables.includes("session") ? "session" : null;
    if (!table) return null;
    const cols = db.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name);
    const dirSel = cols.includes("directory") ? "directory" : "'' AS directory";
    const row = db.prepare(`SELECT id, title, ${dirSel} FROM ${table} WHERE id = ?`).get(sid);
    return row ?? null;
  } catch { return null; }
  finally { try { db.close(); } catch { /* ignore */ } }
}

function findPeerRow(sid, opts = {}) {
  const db = openDb(opts.mailboxDb || MAILBOX_DB);
  if (!db) return null;
  try {
    const row = db.prepare("SELECT * FROM peers WHERE session_id = ?").get(sid);
    return row ?? null;
  } catch { return null; } // no peers table on old mailboxes
  finally { try { db.close(); } catch { /* ignore */ } }
}

/** Focus identity: opencode db first, peers registry second, CC transcript last. */
function resolveFocus(id, opts = {}) {
  const sid = String(id ?? "");
  if (!sid) return null;
  const oc = ocSessionById(sid, opts.ocDb || OC_DB);
  if (oc) {
    return { id: sid, harness: "opencode", title: String(oc.title ?? ""), directory: String(oc.directory ?? "") };
  }
  const peer = findPeerRow(sid, opts);
  if (peer) {
    return { id: sid, harness: String(peer.harness || "claude"), title: String(peer.title ?? ""), directory: String(peer.directory ?? "") };
  }
  if (!sid.startsWith("ses_") && ccTranscriptActivity(sid, opts.projectsDir || path.join(CLAUDE_DIR, "projects")) != null) {
    return { id: sid, harness: "claude", title: "", directory: "" };
  }
  return null;
}

/** Peer-mail threads involving the focus: one row per counterpart, newest first. */
function mailThreads(focusId, limit = 8, opts = {}) {
  const now = opts.now ?? Date.now();
  const db = openDb(opts.mailboxDb || MAILBOX_DB);
  if (!db) return [];
  try {
    const expiry = mailExpiryClause(db);
    const rows = db.prepare(
      `SELECT from_session, to_session, subject, status, ts FROM messages
       WHERE (from_session = ? OR to_session = ?)${expiry} ORDER BY ts DESC`,
    ).all(focusId, focusId, ...(expiry ? [now] : []));
    const seen = new Map();
    for (const r of rows) {
      const peer = r.from_session === focusId ? r.to_session : r.from_session;
      if (!peer) continue;
      const t = seen.get(peer);
      if (t) {
        if (r.status === "unread" && r.to_session === focusId) t.unread++;
        continue;
      }
      seen.set(peer, {
        peer_id: String(peer),
        last_subject: String(r.subject ?? ""),
        incoming: r.to_session === focusId,
        unread: r.status === "unread" && r.to_session === focusId ? 1 : 0,
        ts: ts(r.ts),
      });
    }
    return [...seen.values()].sort((a, b) => b.ts - a.ts).slice(0, Math.max(0, limit));
  } catch { return []; }
  finally { try { db.close(); } catch { /* ignore */ } }
}

/** Orchestrator streams with the session ids on them (held + claim). */
function readStreams(dir) {
  let files = [];
  try { files = fs.readdirSync(dir); } catch { return []; }
  const out = [];
  for (const f of files) {
    const m = /^(.*)\.json$/.exec(f);
    if (!m || !/^[a-z0-9][a-z0-9-]{0,39}$/.test(m[1])) continue;
    try {
      const s = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
      if (!s || typeof s !== "object" || s.status === "parked" || s.status === "done") continue;
      const ids = [s.held_session, s.claim && s.claim.session].filter((x) => typeof x === "string" && x);
      out.push({ name: m[1], repo: String(s.repo ?? ""), sessions: [...new Set(ids)] });
    } catch { /* corrupt pointer: skip */ }
  }
  return out.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

/**
 * Sessions related to the focus, other harnesses only, ranked:
 * stream-mate first, then unread mail, then recency. Each row names its reason.
 */
function relatedSessions(focus, sessions, streams, threads, limit = 8) {
  const others = (sessions || []).filter((s) =>
    s.session_id !== focus.id && (s.harness || "opencode") !== focus.harness);
  const byId = new Map();
  for (const s of others) {
    if (!byId.has(s.session_id)) {
      byId.set(s.session_id, {
        session_id: s.session_id,
        harness: s.harness || "opencode",
        title: s.title || "",
        directory: s.directory || "",
        branch: s.branch ?? null,
        last_active: s.last_active || 0,
        via: [],
        unread: 0,
      });
    }
  }
  const streamNames = new Map(); // session id -> stream names carrying it
  for (const st of streams || []) {
    if (!(st.sessions || []).includes(focus.id)) continue;
    for (const id of st.sessions) {
      if (id === focus.id) continue;
      if (!streamNames.has(id)) streamNames.set(id, []);
      streamNames.get(id).push(st.name);
    }
  }
  for (const [id, names] of streamNames) {
    const r = byId.get(id);
    if (r) for (const n of names) r.via.push(`stream ${n}`);
  }
  for (const t of threads || []) {
    let r = byId.get(t.peer_id);
    if (!r && t.peer_id !== focus.id) {
      // A mail counterpart the session list missed (cap, timing): still related,
      // with what the thread itself tells us.
      r = {
        session_id: t.peer_id,
        harness: t.peer_id.startsWith("ses_") ? "opencode" : "claude",
        title: "",
        directory: "",
        branch: null,
        last_active: 0,
        via: [],
        unread: 0,
      };
      if (r.harness !== focus.harness) byId.set(t.peer_id, r);
      else r = null;
    }
    if (!r) continue;
    r.via.push(t.unread ? `mail: ${t.last_subject} (${t.unread} unread)` : `mail: ${t.last_subject}`);
    r.unread += t.unread;
    r.last_active = Math.max(r.last_active || 0, t.ts);
  }
  for (const r of byId.values()) {
    if (focus.directory && r.directory === focus.directory) r.via.push("same dir");
  }
  const rank = (r) => [
    r.via.some((v) => v.startsWith("stream ")) ? 0 : 1,
    r.unread > 0 ? 0 : 1,
    -(r.last_active || 0),
  ];
  return [...byId.values()]
    .filter((r) => r.via.length > 0)
    .sort((a, b) => {
      const sa = rank(a), sb = rank(b);
      for (let i = 0; i < sa.length; i++) if (sa[i] !== sb[i]) return sa[i] - sb[i];
      return 0;
    })
    .slice(0, Math.max(0, limit));
}

/** Resolve .git dir whether it's a directory or a worktree `gitdir:` file. */
function gitDir(repo) {
  const dot = path.join(repo, ".git");
  try {
    const st = fs.statSync(dot);
    if (st.isDirectory()) return dot;
    const m = fs.readFileSync(dot, "utf8").match(/^gitdir:\s*(.+)$/m);
    return m ? path.resolve(repo, m[1].trim()) : null;
  } catch { return null; }
}

/** Mirror ops/train.sh's state model: departing > boarded > last receipt. */
function trainState(repo) {
  const git = gitDir(repo);
  if (!git) return null;
  const t = path.join(git, "release-train");
  if (!fs.existsSync(t)) return null;
  try {
    const departing = path.join(t, "departing");
    if (fs.existsSync(departing)) {
      let owner = "";
      try {
        owner = fs.readFileSync(path.join(departing, "owner"), "utf8").split(/\r?\n/)[0].trim();
      } catch { /* owner file may not exist yet */ }
      const stale = Date.now() - fs.statSync(departing).mtimeMs > DEPART_STALE_MS;
      return { kind: "departing", owner, stale };
    }
    let boarded = 0;
    try { boarded = fs.readdirSync(path.join(t, "boarded")).filter((f) => !f.startsWith(".")).length; }
    catch { /* no platform */ }
    if (boarded > 0) return { kind: "boarded", n: boarded };
    try {
      const last = fs.readFileSync(path.join(t, "last"), "utf8").trim();
      const m = last.match(/shipped\s+(\w+)/);
      return { kind: "shipped", sha: m ? m[1] : "", raw: last };
    } catch { return { kind: "empty" }; }
  } catch { return null; }
}

/** Newest verify worktree log: running (<10min, % from dot progress) > PASS/FAIL. */
function verifyState(repo) {
  const wt = path.join(repo, ".claude", "worktrees");
  let newest = null;
  try {
    for (const e of fs.readdirSync(wt)) {
      if (!e.startsWith("verify-")) continue;
      const log = path.join(wt, e, ".claude", "verify.log");
      try {
        const st = fs.statSync(log);
        if (!newest || st.mtimeMs > newest.mtime) newest = { log, mtime: st.mtimeMs };
      } catch { /* no log in that worktree */ }
    }
  } catch { return null; }
  if (!newest) return null;
  const ageMs = Date.now() - newest.mtime;
  if (ageMs < VERIFY_RUNNING_MS) {
    const tail = stripAnsi(tailBytes(newest.log, 4096));
    const pct = [...tail.matchAll(/\[\s*(\d{1,3})%\]/g)].pop()?.[1];
    return { kind: "running", pct: pct ? Number(pct) : null, ageMs };
  }
  const tail = stripAnsi(tailBytes(newest.log, 8192));
  if (/\bFAIL\b/.test(tail)) return { kind: "fail", ageMs };
  if (/\bPASS\b|Test Files/.test(tail)) return { kind: "pass", ageMs };
  return null; // stale log from a killed run — say nothing rather than lie
}

/** Full-fidelity session list (both harnesses, titles + branches) — peer-mail's dist. */
async function peerSessions(limit = 12) {
  const dist = peerDistPath();
  if (!dist) return [];
  try {
    const mod = await import(pathToFileURL(dist).href);
    return mod.listPeerSessions(limit);
  } catch { return []; }
}

async function collectFast(payload) {
  const sessionId = typeof payload?.session_id === "string" ? payload.session_id : "";
  const remotes = await probeRemotes();
  return {
    oc: ocLatest(),
    unread: unreadCount(sessionId),
    remotes,
    trains: loadRepos().map((r) => ({ ...r, state: trainState(r.dir), verify: verifyState(r.dir) })),
  };
}

async function collectFull(payload) {
  const fast = await collectFast(payload);
  const [sessions] = await Promise.all([peerSessions(12)]);
  full_sessionsCache = sessions;
  // rows first, then the totals: recipientActivity is cached, so the second pass is free.
  const unreadRows = recentUnread(20);
  return {
    ...fast,
    sessions,
    unreadRows,
    unreadTotals: unreadTotal(),
    orch: orchestratorState(),
    active: activeNow(),
  };
}

// ── what is running right now (both harnesses) ─────────────────────────────
const ACTIVE_WINDOW_MS = 5 * 60_000;
function pidAlive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
}
function activeNow() {
  const now = Date.now();
  const out = { runs: [], oc: [], cc: [] };
  // 1. oc-worker runs (registry written by bin/oc-worker.mjs; dead pids are pruned)
  try {
    const dir = path.join(ORCH_DIR, "runs");
    for (const f of fs.existsSync(dir) ? fs.readdirSync(dir) : []) {
      const p = path.join(dir, f);
      const r = readJsonSafe(p);
      if (!r || !pidAlive(r.pid)) { try { fs.rmSync(p, { force: true }); } catch {} continue; }
      let last = null;
      try { last = fs.statSync(r.out + ".events.jsonl").mtimeMs; } catch {}
      out.runs.push({ ...r, last });
    }
  } catch {}
  // 2. OpenCode sessions that are busy now (time_busy after time_idle, touched recently)
  try {
    if (fs.existsSync(OC_DB)) {
      process.emitWarning = () => {};
      const { DatabaseSync } = require("node:sqlite");
      const db = new DatabaseSync(OC_DB, { readOnly: true });
      try {
        out.oc = db.prepare(
          "SELECT s.id, s.title, s.agent, s.model, s.parent_id, s.time_busy, s.time_updated, s.directory, " +
          "(SELECT COUNT(*) FROM session_v2 c WHERE c.parent_id = s.id AND c.time_busy > COALESCE(c.time_idle, 0)) AS busy_children " +
          "FROM session_v2 s WHERE s.time_busy > COALESCE(s.time_idle, 0) AND s.time_updated > ? AND s.parent_id IS NULL " +
          "ORDER BY s.time_updated DESC LIMIT 12",
        ).all(now - 15 * 60_000).map((r) => {
          let model = r.model;
          try { const m = JSON.parse(r.model); model = `${m.providerID}/${m.id}`; } catch {}
          return { ...r, model };
        });
      } finally { db.close(); }
    }
  } catch {}
  // 3. Claude Code sessions (transcript written recently) and their recently-active subagents
  try {
    const root = path.join(CLAUDE_DIR, "projects");
    for (const proj of fs.readdirSync(root)) {
      const pdir = path.join(root, proj);
      let entries = [];
      try { entries = fs.readdirSync(pdir); } catch { continue; }
      for (const e of entries) {
        if (!e.endsWith(".jsonl")) continue;
        const id = e.slice(0, -6);
        let m = 0;
        try { m = fs.statSync(path.join(pdir, e)).mtimeMs; } catch { continue; }
        const subDir = path.join(pdir, id, "subagents");
        let subs = 0, subLast = 0;
        try {
          for (const s of fs.readdirSync(subDir)) {
            const sm = fs.statSync(path.join(subDir, s)).mtimeMs;
            if (now - sm < ACTIVE_WINDOW_MS) { subs++; subLast = Math.max(subLast, sm); }
          }
        } catch {}
        if (now - m < ACTIVE_WINDOW_MS || subs) {
          const s = (full_sessionsCache || []).find((x) => x.session_id === id);
          out.cc.push({ id, project: proj, last: Math.max(m, subLast), subagents: subs, title: s?.title || "" });
        }
      }
    }
    out.cc.sort((a, b) => b.last - a.last);
  } catch {}
  return out;
}
let full_sessionsCache = null;

// ── orchestrator: model pools + recent runs (read-only) ─────────────────────
const ORCH_DIR = path.join(os.homedir(), ".config", "orchestrator");
function readJsonSafe(p) {
  try { return JSON.parse(fs.readFileSync(p, "utf8")); } catch { return null; }
}
function orchestratorState() {
  const health = readJsonSafe(path.join(ORCH_DIR, "router-health.json"));
  const pool = readJsonSafe(path.join(ORCH_DIR, "pool-health.json")) || {};
  const now = Date.now();
  const down = Object.entries(pool)
    .filter(([, v]) => Date.parse(v.until) > now)
    .map(([model, v]) => ({ model, reason: v.reason, until: v.until }));
  let runs = [];
  try {
    if (fs.existsSync(OC_DB)) {
      process.emitWarning = () => {};
      const { DatabaseSync } = require("node:sqlite");
      const db = new DatabaseSync(OC_DB, { readOnly: true });
      try {
        const since = now - 48 * 3600_000;
        const roots = db.prepare(
          "SELECT id, title, agent, model, cost, time_created, time_updated FROM session_v2 " +
          "WHERE parent_id IS NULL AND title LIKE 'orch %' AND time_updated > ? ORDER BY time_updated DESC LIMIT 15",
        ).all(since);
        const kids = db.prepare("SELECT id, cost FROM session_v2 WHERE parent_id = ?");
        const treeCost = (id, d = 0) => {
          if (d > 4) return 0;
          return kids.all(id).reduce((t, k) => t + (k.cost || 0) + treeCost(k.id, d + 1), 0);
        };
        runs = roots.map((r) => {
          let model = r.model;
          try { const m = JSON.parse(r.model); model = `${m.providerID}/${m.id}`; } catch {}
          return { title: r.title, agent: r.agent, model, cost: (r.cost || 0) + treeCost(r.id), updated: r.time_updated };
        });
      } finally { db.close(); }
    }
  } catch { /* dashboard is best-effort */ }
  return { health, down, runs };
}

// ── statusline rendering ────────────────────────────────────────────────────
function ctxSegment(data) {
  const remaining = data?.context_window?.remaining_percentage;
  if (remaining == null) return "";
  // Normalize out of CC's autocompact reserve: 16.5% remaining == 100% usable used.
  const usableRemaining = Math.max(0,
    ((remaining - AUTO_COMPACT_BUFFER_PCT) / (100 - AUTO_COMPACT_BUFFER_PCT)) * 100);
  const used = Math.max(0, Math.min(100, Math.round(100 - usableRemaining)));
  const filled = Math.floor(used / 10);
  const bar = "█".repeat(filled) + "░".repeat(10 - filled);
  const color = used < 50 ? GREEN : used < 65 ? YELLOW : used < 80 ? ORANGE : RED;
  return `${color}${bar} ${used}%${R}`;
}

function limitsSegment(data) {
  const rl = data?.rate_limits;
  const parts = [];
  const fmt = (label, win) => {
    const pct = win?.used_percentage;
    if (pct == null) return;
    const p = Math.round(pct);
    const color = p < 50 ? GREEN : p < 80 ? YELLOW : RED;
    parts.push(`${DIM}${label}${R}${color}${p}%${R}`);
  };
  fmt("5h", rl?.five_hour);
  fmt("7d", rl?.seven_day);
  const spend = rl?.spend_limit;
  if (spend?.used_percentage != null) {
    const p = Math.round(spend.used_percentage);
    const color = p < 50 ? GREEN : p < 80 ? YELLOW : RED;
    const usd = spend.used_usd != null && spend.limit_usd != null
      ? `$${Math.round(spend.used_usd)}/$${Math.round(spend.limit_usd)}`
      : `${p}%`;
    parts.push(`${DIM}spend${R}${color}${usd}${R}`);
  }
  return parts.join(" ");
}

function costSegment(data) {
  const c = data?.cost?.total_cost_usd;
  if (c == null) return "";
  return `${DIM}$${Number(c).toFixed(2)}${R}`;
}

function ocSegment(fast) {
  const s = fast.oc;
  if (!s) return "";
  let title = s.title;
  if (title.length > TITLE_MAX) title = title.slice(0, TITLE_MAX - 1) + "…";
  return `${DIM}OC:${R}${CYAN}${s.model}${R} ${DIM}"${title}" ${age(s.updated)}${R}`;
}

function trainSegment(label, state) {
  if (!state) return "";
  const L = `${DIM}${label}${R}`;
  switch (state.kind) {
    case "departing":
      return `${L} ${state.stale ? `${YELLOW}🚂⚠${R}` : `${MAGENTA}🚂${R}`}`;
    case "boarded":
      return `${L} ${BLUE}📦${state.n}${R}`;
    case "shipped":
      return `${L} ${GREEN}✅${state.sha || ""}${R}`;
    case "empty":
      return `${L} ${DIM}·${R}`;
    default:
      return "";
  }
}

function verifySegment(label, v) {
  if (!v) return "";
  const L = `${DIM}${label}${R}`;
  if (v.kind === "running") return `${L} ${YELLOW}▓${v.pct != null ? v.pct + "%" : ""}${R}`;
  if (v.kind === "pass") return `${L} ${GREEN}✔${R}`;
  if (v.kind === "fail") return `${L} ${RED}✖${R}`;
  return "";
}

/** Remote instances, named: name🟢 when up, name· dim when no instance is
 * up (probe off), name🔴 only when an enabled remote fails. */
function remoteSegment(remotes) {
  if (!remotes || !remotes.length) return `${DIM}remote ·${R}`;
  const shown = remotes.slice(0, 3).map((r) => {
    if (r.enabled === false || r.up == null) return `${DIM}${r.name}·${R}`;
    return r.up ? `${GREEN}${r.name}🟢${R}` : `${RED}${r.name}🔴${R}`;
  });
  if (remotes.length > 3) shown.push(`${DIM}+${remotes.length - 3}${R}`);
  return shown.join(" ");
}

/** The dashboard as a clickable OSC-8 link (Ctrl/Cmd+click opens the browser). */
function dashLink() {
  const url = pathToFileURL(DASH_HTML).href;
  return `\x1b]8;;${url}\x1b\\${DIM}📊${R}\x1b]8;;\x1b\\`;
}

function visibleWidth(s) {
  return stripAnsi(s).replace(/\x1b\]8;;[^\x1b]*\x1b\\/, "").length;
}

function renderLines(payload, fast) {
  const dir = path.basename(payload?.workspace?.current_dir || payload?.cwd || process.cwd());
  const model = payload?.model?.display_name || "Claude";

  const line1 = [
    `${DIM}${model}${R}`,
    ctxSegment(payload),
    costSegment(payload),
    limitsSegment(payload),
    `${DIM}${dir}${R}`,
  ].filter(Boolean).join(` ${DIM}│${R} `);

  const oc = ocSegment(fast);
  const segments = [
    oc,
    fast.unread > 0 ? `${YELLOW}✉${fast.unread}${R}` : "",
    remoteSegment(fast.remotes),
    ...fast.trains.flatMap((t) => [
      trainSegment(t.label, t.state),
      verifySegment(t.label, t.verify),
    ]),
  ].filter(Boolean);

  let line2 = segments.join(` ${DIM}│${R} `);
  const cols = Number(process.env.COLUMNS) || 0;
  if (cols > 0 && visibleWidth(line2) > cols - 2) {
    // Narrow terminal: drop the OC title first, then the shipped sha.
    const ocFallback = fast.oc
      ? `${DIM}OC:${R}${CYAN}${fast.oc.model}${R} ${DIM}${age(fast.oc.updated)}${R}`
      : "";
    const segs2 = segments.map((s) => (s === oc ? ocFallback : s)).filter(Boolean);
    line2 = segs2.join(` ${DIM}│${R} `);
    if (visibleWidth(line2) > cols - 2) {
      const segs3 = segs2.map((s) => s.replace(/(✅)[0-9a-f]{7,}/, "$1…"));
      line2 = segs3.join(` ${DIM}│${R} `);
    }
  }

  return `${line1}\n${line2} ${DIM}│${R} ${dashLink()}`;
}

// ── dashboard rendering (HTML + text) ───────────────────────────────────────
function sessionRows(full) {
  const rows = full.sessions || [];
  if (rows.length) return rows;
  // peer-mail dist unavailable — fall back to the light OC read.
  const oc = full.oc;
  return oc
    ? [{ session_id: oc.id, title: oc.title, directory: "", branch: null, last_active: oc.updated, harness: "opencode" }]
    : [];
}

function trainSummary(state) {
  if (!state) return `<span class="dim">no release-train data</span>`;
  switch (state.kind) {
    case "departing":
      return `<span class="warn">🚂 departing</span>${state.owner ? ` <span class="dim">${esc(state.owner)}</span>` : ""}${state.stale ? ` <span class="bad">(owner heartbeat >15min old)</span>` : ""}`;
    case "boarded":
      return `<span class="hi">📦 ${state.n} boarded</span>`;
    case "shipped":
      return `<span class="ok">✅ last shipped ${esc(state.sha)}</span>`;
    case "empty":
      return `<span class="dim">platform empty, no receipt</span>`;
    default:
      return `<span class="dim">—</span>`;
  }
}

function verifySummary(v) {
  if (!v) return `<span class="dim">no recent run</span>`;
  if (v.kind === "running") return `<span class="warn">▓ running${v.pct != null ? " " + v.pct + "%" : ""}</span>`;
  if (v.kind === "pass") return `<span class="ok">✔ PASS</span> <span class="dim">${ago(Date.now() - v.ageMs)}</span>`;
  if (v.kind === "fail") return `<span class="bad">✖ FAIL</span> <span class="dim">${ago(Date.now() - v.ageMs)}</span>`;
  return `<span class="dim">—</span>`;
}

function activeHtml(a) {
  if (!a) return `<div class="dim">no activity data</div>`;
  const dur = (ms) => { const s = Math.max(0, Math.round(ms / 1000)); return s < 90 ? `${s}s` : s < 5400 ? `${Math.round(s / 60)}m` : `${(s / 3600).toFixed(1)}h`; };
  const now = Date.now();
  const runRows = a.runs.map((r) => `<tr><td><span class="badge b-oc">worker run</span></td><td>${esc(r.title)}</td><td>${esc(r.agent)}</td><td class="dim">${esc(r.model)}</td><td>${dur(now - r.started)}</td><td class="${r.last && now - r.last < 120000 ? "ok" : "warn"}">${r.last ? "output " + ago(r.last) : "starting"}</td></tr>`);
  const ocRows = a.oc.map((s) => `<tr><td><span class="badge b-oc">opencode</span></td><td>${esc(s.title)}</td><td>${esc(s.agent || "")}${s.busy_children ? ` <span class="hi">+${s.busy_children} subagent${s.busy_children > 1 ? "s" : ""}</span>` : ""}</td><td class="dim">${esc(s.model || "")}</td><td>${dur(now - s.time_busy)}</td><td class="ok">busy · ${ago(s.time_updated)}</td></tr>`);
  const ccRows = a.cc.map((s) => `<tr><td><span class="badge b-claude">claude</span></td><td>${esc(s.title || s.id.slice(0, 8))}</td><td>${s.subagents ? `<span class="hi">${s.subagents} subagent${s.subagents > 1 ? "s" : ""} active</span>` : "session"}</td><td class="dim">${esc(s.project.replace(/^[A-Za-z]--Users-[^-]+-/, ""))}</td><td></td><td class="ok">${ago(s.last)}</td></tr>`);
  const rows = [...runRows, ...ocRows, ...ccRows].join("");
  return `<table><tr><th>kind</th><th>what</th><th>agent</th><th>model / where</th><th>running</th><th>last activity</th></tr>${rows || `<tr><td colspan="6" class="dim">nothing active in the last 5 minutes</td></tr>`}</table>`;
}

function orchHtml(o) {
  if (!o) return `<div class="dim">no orchestrator state</div>`;
  const h = o.health;
  const roleRows = h?.roles
    ? Object.entries(h.roles).map(([role, r]) => {
      const skipped = (r.chain || []).filter((c) => c.state !== "healthy")
        .map((c) => `${esc(c.agent)}: ${esc(c.state)}${c.detail ? " (" + esc(c.detail) + ")" : ""}`).join("; ");
      const use = r.use ? `<span class="ok">${esc(r.use)}</span>` : `<span class="bad">NONE</span>`;
      const model = (r.chain || []).find((c) => c.agent === r.use)?.model || "";
      return `<tr><td>${esc(role)}</td><td>${use}</td><td class="dim">${esc(model)}</td><td class="dim">${skipped}</td></tr>`;
    }).join("")
    : `<tr><td colspan="4" class="dim">router-health has not run — node ${esc(ORCH_REPO_DIR)}/bin/router-health.mjs --probe</td></tr>`;
  const downRows = o.down.length
    ? o.down.map((d) => `<tr><td class="bad">${esc(d.model)}</td><td>${esc(d.reason)}</td><td class="dim">until ${esc(new Date(d.until).toLocaleString())}</td></tr>`).join("")
    : `<tr><td colspan="3" class="ok">all pools healthy</td></tr>`;
  const np = h?.new_providers || [];
  const banner = np.length
    ? `<div class="warn" style="border:1px solid #d29922;padding:8px;margin:6px 0">NEW PROVIDER connected, not in any chain: ${np.map((p) => `<b>${esc(p.id)}</b> (${esc(p.models)} models)`).join(", ")}<br><span class="dim">evaluate, or ignore: router-health --decide &lt;id&gt; routed|ignored</span></div>`
    : "";
  return `${banner}<div class="sub">router-health ${h?.checked_at ? "checked " + ago(Date.parse(h.checked_at)) : "never run"}</div>
<table><tr><th>role</th><th>use</th><th>model</th><th>skipped</th></tr>${roleRows}</table>
<div class="sub" style="margin-top:10px">known-down pools</div>
<table><tr><th>model</th><th>reason</th><th>back</th></tr>${downRows}</table>`;
}

function orchRunsHtml(o) {
  if (!o?.runs?.length) return `<div class="dim">no orchestrator runs (sessions titled "orch …") in the last 48h</div>`;
  const total = o.runs.reduce((t, r) => t + r.cost, 0);
  const rows = o.runs.map((r) => `<tr><td>${esc(r.title)}</td><td>${esc(r.agent || "")}</td><td class="dim">${esc(r.model || "")}</td><td>$${r.cost.toFixed(4)}</td><td class="dim">${ago(r.updated)}</td></tr>`).join("");
  return `<table><tr><th>run</th><th>agent</th><th>model</th><th>cost (incl. subagents)</th><th>when</th></tr>${rows}
<tr><td colspan="3" class="dim">total, last ${o.runs.length} runs</td><td><b>$${total.toFixed(4)}</b></td><td></td></tr></table>`;
}

function renderHtml(payload, full) {
  const cc = payload || {};
  const model = cc.model?.display_name || "—";
  const dir = cc.workspace?.current_dir || cc.cwd || "";
  // used_percentage is what CC normally sends; some payloads only carry remaining.
  const ctxPct = cc.context_window?.used_percentage
    ?? (cc.context_window?.remaining_percentage != null
      ? Math.round(100 - cc.context_window.remaining_percentage)
      : null);
  const cost = cc.cost?.total_cost_usd;
  const rl = cc.rate_limits || {};
  const fmtLimit = (w) => {
    if (w?.used_percentage == null) return `<span class="dim">n/a</span>`;
    let out = `${Math.round(w.used_percentage)}%`;
    const r = Number(w.resets_at);
    if (Number.isFinite(r) && r > 0) {
      out += ` <span class="dim">resets ${new Date(r * 1000).toLocaleString()}</span>`;
    }
    return out;
  };

  const sessions = sessionRows(full).map((s) => `
    <tr>
      <td><span class="badge ${s.harness === "claude" ? "b-claude" : "b-oc"}">${esc(s.harness)}</span></td>
      <td class="dim">${esc(s.session_id)}</td>
      <td>${esc(s.title)}</td>
      <td class="dim">${esc(s.branch ? "@" + s.branch : (s.directory ? path.basename(s.directory) : ""))}</td>
      <td class="dim">${ago(s.last_active)}</td>
    </tr>`).join("");

  const titles = new Map(sessionRows(full).map((s) => [s.session_id, s.title]));
  const mail = full.unreadTotals || { live: 0, idle: 0 };
  let unread;
  if (!peerDistPath()) {
    unread = `<tr><td colspan="4" class="dim">peer-mail not configured — set "peerMailDist" in ~/.claude/harness-config.json</td></tr>`;
  } else if (full.unreadRows.length) {
    unread = full.unreadRows.map((m) => `
      <tr${m.idle ? ` class="dim"` : ""}>
        <td>→ ${esc(titles.get(m.to_session) || m.to_session.slice(0, 12) + "…")}</td>
        <td class="dim">${esc(m.from_title)}${m.from_branch ? " @" + esc(m.from_branch) : ""}</td>
        <td>${esc(m.subject)}</td>
        <td class="dim">${ago(m.ts)}${m.idle ? ` (idle ${m.active != null ? ago(m.active) : "?"})` : ""}</td>
      </tr>`).join("");
  } else {
    unread = `<tr><td colspan="4" class="dim">inbox zero 🎉</td></tr>`;
  }

  const remotes = full.remotes || [];
  const remoteSummary = (r) => (r.enabled === false || r.up == null
    ? `<span class="dim">no remote instance</span>`
    : r.up
      ? `<span class="ok">🟢 up</span> <span class="dim">${r.ms}ms</span>`
      : `<span class="bad">🔴 down</span> <span class="dim">${esc(r.host)}:${r.port} · ${PROBE_TIMEOUT_MS}ms timeout</span>`);
  const remoteRows = remotes.length
    ? remotes.map((r) => `
      <tr>
        <td>${esc(r.name)}</td>
        <td class="dim">${esc(r.alias)}</td>
        <td class="dim">${esc(r.host)}:${r.port}</td>
        <td>${remoteSummary(r)}</td>
      </tr>`).join("")
    : `<tr><td colspan="4" class="dim">no remote instances configured — add them to ~/.claude/harness-config.json</td></tr>`;

  const trains = full.trains.map((t) => `
    <tr>
      <td>${esc(t.label)}</td>
      <td>${trainSummary(t.state)}</td>
      <td>${verifySummary(t.verify)}</td>
    </tr>`).join("");

  const receipt = full.trains
    .map((t) => (t.state?.raw ? `<div class="dim">${esc(t.label)}: ${esc(t.state.raw.split("\n")[0])}</div>` : ""))
    .join("");

  // No repos configured (or none with train data): hide the section rather than show an empty table.
  const trainsHtml = full.trains.length
    ? `
<h2>release trains + verify</h2>
<table><tr><th>repo</th><th>train</th><th>verify</th></tr>${trains}</table>
${receipt}`
    : "";

  const oc = full.oc;
  const ocLine = oc
    ? `<span class="hi">${esc(oc.model)}</span> “${esc(oc.title)}” <span class="dim">${ago(oc.updated)} · ${esc(oc.id)}</span>`
    : `<span class="dim">no opencode sessions found</span>`;

  return `<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta http-equiv="refresh" content="15">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>harness dashboard</title>
<style>
  body { background:#0d1117; color:#c9d1d9; margin:0; padding:24px 16px;
         font:13px/1.55 ui-monospace, SFMono-Regular, Consolas, monospace; }
  .wrap { max-width:1080px; margin:0 auto; }
  h1 { font-size:15px; margin:0 0 4px; color:#e6edf3; }
  h2 { font-size:11px; color:#8b949e; text-transform:uppercase; letter-spacing:.09em;
       border-bottom:1px solid #21262d; padding-bottom:4px; margin:26px 0 8px; }
  .sub { color:#8b949e; font-size:12px; margin-bottom:6px; }
  table { border-collapse:collapse; width:100%; }
  td, th { text-align:left; padding:4px 14px 4px 0; vertical-align:top; }
  th { color:#8b949e; font-weight:600; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }
  .ok { color:#3fb950; } .bad { color:#f85149; } .warn { color:#d29922; }
  .hi { color:#58a6ff; } .dim { color:#8b949e; }
  .badge { font-size:10px; padding:1px 7px; border-radius:10px; border:1px solid #30363d; }
  .b-claude { color:#d2a8ff; border-color:#6e40c9; } .b-oc { color:#7ee787; border-color:#238636; }
  .grid { display:grid; grid-template-columns:repeat(auto-fit,minmax(300px,1fr)); gap:4px 24px; }
  .footer { color:#484f58; font-size:11px; margin-top:28px; border-top:1px solid #21262d; padding-top:8px; }
  a { color:#58a6ff; }
</style></head><body><div class="wrap">

<h1>⚡ harness dashboard</h1>
<div class="sub">line behind the CC statusline · auto-refresh 60s · regenerated ${new Date().toLocaleString()}</div>

<h2>active now <span class="dim">(live — page reloads every 15 s; rebuilt by running workers and every Claude Code / OpenCode turn)</span></h2>
${activeHtml(full.active)}

<h2>model pools — routing</h2>
${orchHtml(full.orch)}

<h2>orchestrator runs — last 48h</h2>
${orchRunsHtml(full.orch)}

<h2>Claude Code rate limits <span class="dim">(last terminal-statusline snapshot${cc.saved_at ? ", " + ago(cc.saved_at) : ""} — VS Code sessions don't report these)</span></h2>
<div class="grid">
  <div><span class="dim">rate 5h</span> ${fmtLimit(rl.five_hour)}</div>
  <div><span class="dim">rate 7d</span> ${fmtLimit(rl.seven_day)}</div>
  <div><span class="dim">snapshot model</span> ${esc(model)}</div>
</div>

<h2>sessions — opencode + claude</h2>
<div class="sub">latest opencode activity: ${ocLine}</div>
<table><tr><th>harness</th><th>id</th><th>title</th><th>where</th><th>active</th></tr>${sessions || `<tr><td colspan="5" class="dim">none found</td></tr>`}</table>

<h2>peer-mail: ${mail.live} unread (${mail.idle} to idle sessions)</h2>
<table><tr><th>to</th><th>from</th><th>subject</th><th>age</th></tr>${unread}</table>

<h2>remote instances</h2>
<table><tr><th>name</th><th>ssh alias</th><th>target</th><th>state</th></tr>${remoteRows}</table>
${trainsHtml}

<div class="footer">file is truth: train state mirrors ops/train.sh (departing → boarded → last receipt);
verify reads .claude/worktrees/verify-*/.claude/verify.log; sessions via opencode-peer-mail.
Quota note: Go/CommandCode allowances have no local counter — CC's own 5h/7d windows are above;
check the opencode console for the rest.</div>

</div></body></html>`;
}

function renderText(payload, full) {
  const cc = payload || {};
  const line = (k, v) => `  ${k.padEnd(10)} ${v}`;
  const out = [];
  out.push("harness dashboard  " + new Date().toISOString());
  out.push("");
  const snapAge = cc.saved_at ? ago(cc.saved_at) : "unknown age";
  out.push(`LAST CC STATUSLINE SNAPSHOT (session ${(cc.session_id || "?").slice(0, 8)}, ${snapAge}; VS Code sessions never write it)`);
  out.push(line("model", cc.model?.display_name || "—"));
  out.push(line("cwd", cc.workspace?.current_dir || cc.cwd || "—"));
  const ccCtx = cc.context_window ?? {};
  const ctxPct = ccCtx.used_percentage
    ?? (ccCtx.remaining_percentage != null ? Math.round(100 - ccCtx.remaining_percentage) : null);
  out.push(line("context", ctxPct != null ? ctxPct + "%" : "n/a"));
  out.push(line("cost", cc.cost?.total_cost_usd != null ? "$" + Number(cc.cost.total_cost_usd).toFixed(2) : "n/a"));
  const rl = cc.rate_limits || {};
  const lim = (w) => (w?.used_percentage != null ? Math.round(w.used_percentage) + "%" : "n/a");
  out.push(line("rate", `5h ${lim(rl.five_hour)} · 7d ${lim(rl.seven_day)}`));
  for (const p of full.orch?.health?.new_providers || []) {
    out.push(`  NEW PROVIDER ${p.id} (${p.models} models) not in any chain — router-health --decide ${p.id} routed|ignored`);
  }
  out.push("");
  out.push("ACTIVE NOW");
  const act = full.active || { runs: [], oc: [], cc: [] };
  for (const r of act.runs) out.push(`  [worker  ] ${r.title}  ${r.agent} ${r.model}  running ${ago(r.started)}`);
  for (const o of act.oc) out.push(`  [opencode] ${o.title}  ${o.agent || ""}${o.busy_children ? " +" + o.busy_children + " subagents" : ""}  busy since ${ago(o.time_busy)}`);
  for (const c of act.cc) out.push(`  [claude  ] ${c.title || c.id.slice(0, 8)}${c.subagents ? "  " + c.subagents + " subagents active" : ""}  ${ago(c.last)}`);
  if (!act.runs.length && !act.oc.length && !act.cc.length) out.push("  nothing active in the last 5 minutes");
  out.push("");
  out.push("SESSIONS (opencode + claude)");
  for (const s of sessionRows(full)) {
    out.push(`  [${s.harness.padEnd(8)}] ${s.title}${s.branch ? " @" + s.branch : ""}  (${ago(s.last_active)})  ${DIM}${s.session_id}${R}`);
  }
  if (!full.sessions?.length && !full.oc) out.push("  (none found)");
  out.push("");
  out.push("PEER-MAIL UNREAD");
  const mail = full.unreadTotals || { live: 0, idle: 0 };
  out.push(`  peer-mail: ${mail.live} unread (${mail.idle} to idle sessions)`);
  if (!peerDistPath()) {
    out.push("  peer-mail not configured — set \"peerMailDist\" in ~/.claude/harness-config.json");
  } else if (full.unreadRows.length) {
    const titles = new Map(sessionRows(full).map((s) => [s.session_id, s.title]));
    for (const m of full.unreadRows) {
      const idleMark = m.idle ? `  (idle ${m.active != null ? ago(m.active) : "?"})` : "";
      out.push(`  → ${titles.get(m.to_session) || m.to_session.slice(0, 12)} ← ${m.from_title}: ${m.subject}  (${ago(m.ts)})${idleMark}`);
    }
  } else out.push("  inbox zero");
  out.push("");
  out.push("REMOTE INSTANCES");
  const remotes = full.remotes || [];
  if (remotes.length) {
    for (const r of remotes) {
      const state = r.enabled === false || r.up == null ? "no remote instance"
        : r.up ? `up ${r.ms}ms` : `DOWN ${r.host}:${r.port}`;
      out.push(`  ${r.name.padEnd(9)} ${state.padEnd(20)} ${DIM}${r.alias}${R}`);
    }
  } else out.push("  (none configured — ~/.claude/harness-config.json)");
  out.push("");
  if (full.trains.length) {
    out.push("RELEASE TRAINS + VERIFY");
    for (const t of full.trains) {
      const plain = (s) => stripAnsi(String(s)).replace(/<[^>]+>/g, "");
      out.push(`  ${t.label.padEnd(8)} train: ${plain(trainSummary(t.state)).padEnd(34)} verify: ${plain(verifySummary(t.verify))}`);
    }
    out.push("");
  }
  out.push(`full HTML: ${DASH_HTML}`);
  return stripAnsi(out.join("\n"));
}

// ── sidecar + rebuild orchestration ─────────────────────────────────────────
function writeSidecar(payload) {
  try {
    atomicWrite(CC_SIDECAR, JSON.stringify({
      saved_at: Date.now(),
      session_id: payload?.session_id ?? "",
      model: payload?.model ?? null,
      workspace: payload?.workspace ?? null,
      cwd: payload?.cwd ?? null,
      context_window: payload?.context_window ?? null,
      cost: payload?.cost ?? null,
      rate_limits: payload?.rate_limits ?? null,
    }));
  } catch { /* sidecar is best-effort */ }
}

function readSidecar() {
  try { return JSON.parse(fs.readFileSync(CC_SIDECAR, "utf8")); } catch { return null; }
}

function dashStale() {
  try { return Date.now() - fs.statSync(DASH_HTML).mtimeMs > DASH_STALE_MS; }
  catch { return true; }
}

/** Rebuild detached so the bar never waits on git-heavy session listing. */
const DASH_LOCK = DASH_HTML + ".lock";
function spawnDashRebuild() {
  // One rebuild at a time across every open session: mkdir is atomic; a lock older than 2 min is stale.
  try {
    fs.mkdirSync(DASH_LOCK);
  } catch {
    try {
      if (Date.now() - fs.statSync(DASH_LOCK).mtimeMs < 120_000) return;
      fs.rmSync(DASH_LOCK, { recursive: true, force: true });
      fs.mkdirSync(DASH_LOCK);
    } catch { return; }
  }
  try {
    const child = spawn(process.execPath, [__filename, "--html"], {
      detached: true, stdio: "ignore", windowsHide: true,
    });
    child.unref();
  } catch { /* bar stays correct; dashboard catches up next run */ }
}

// ── modes ───────────────────────────────────────────────────────────────────
async function runHtml() {
  try {
    const payload = readSidecar();
    const full = await collectFull(payload);
    atomicWrite(DASH_HTML, renderHtml(payload, full));
  } finally {
    try { fs.rmSync(DASH_LOCK, { recursive: true, force: true }); } catch { /* best effort */ }
  }
}

/** CC's quota as last written by a CLI statusline run: { model, rate_limits, ageMs } or null. */
function ccSidecar() {
  try {
    const st = fs.statSync(CC_SIDECAR);
    const sc = JSON.parse(fs.readFileSync(CC_SIDECAR, "utf8"));
    return {
      model: sc.model?.display_name ?? null,
      rate_limits: sc.rate_limits ?? null,
      ageMs: Math.max(0, Date.now() - st.mtimeMs),
    };
  } catch { return null; }
}

/** The claude-session-sidebar extension polls this: fast, no CC stdin, never spawns git. */
/** Rebuild the dashboard in the background if it is stale (locked, detached). Safe to call from any hook. */
function kick() {
  // Off-switch: ~/.config/orchestrator/dashboard.off disables background rebuilds (e.g. if console windows flash).
  if (fs.existsSync(path.join(os.homedir(), ".config", "orchestrator", "dashboard.off"))) return;
  if (dashStale()) spawnDashRebuild();
}

async function runJson(forId) {
  kick(); // the OpenCode sidebar polls --json every 15 s: that keeps the HTML fresh without a terminal statusline
  try {
    const fast = await collectFast(null);
    // unread counts only mail a recipient can still read; unreadIdle says how much is stranded.
    const mail = unreadTotal();
    // Active oc-worker runs give the sidebar something to render as a live spinner
    // for headless desk-driven workers that cannot set todowrite themselves.
    const active = activeNow();
    const out = {
      ts: Date.now(),
      oc: fast.oc,
      remotes: fast.remotes,
      trains: fast.trains,
      unread: mail.live,
      unreadIdle: mail.idle,
      unreadRows: recentUnread(3, { liveOnly: true }),
      cc: ccSidecar(),
      active,
    };
    if (forId) {
      // Related-sessions view for one session: the panel shows only other
      // harnesses' sessions related to the one being viewed.
      const sessions = await peerSessions(50);
      const focus = resolveFocus(forId);
      if (focus) {
        const streams = readStreams(path.join(os.homedir(), ".config", "orchestrator", "streams"));
        const threads = mailThreads(forId, 8);
        const related = relatedSessions(focus, sessions, streams, threads);
        const titles = new Map(sessions.map((s) => [s.session_id, s]));
        out.focus = focus;
        out.myUnread = unreadCount(forId);
        out.related = related;
        out.threads = threads.map((t) => {
          const s = titles.get(t.peer_id);
          return { ...t, harness: (s && s.harness) || (t.peer_id.startsWith("ses_") ? "opencode" : "claude"), title: (s && s.title) || "" };
        });
      } else {
        out.focus = null;
      }
    }
    process.stdout.write(JSON.stringify(out) + "\n");
  } catch (e) {
    // A line of JSON either way: the extension distinguishes "error" from "no data".
    process.stdout.write(JSON.stringify({ ts: Date.now(), error: String(e?.message || e) }) + "\n");
  }
}

async function runText() {
  const payload = readSidecar();
  const full = await collectFull(payload);
  process.stdout.write(renderText(payload, full) + "\n");
}

async function runStatusline(payload) {
  const fast = await collectFast(payload);
  writeSidecar(payload);
  if (dashStale()) spawnDashRebuild();
  process.stdout.write(renderLines(payload, fast) + "\n");
}

function main() {
  const argv = process.argv.slice(2);
  const mode = argv.includes("--html") ? "html"
    : argv.includes("--text") ? "text"
      : argv.includes("--json") ? "json"
        : "statusline";
  const forIdx = argv.indexOf("--for");
  const forId = forIdx >= 0 ? argv[forIdx + 1] : null;

  // --kick: hook-friendly — rebuild the HTML in the background only if stale, print nothing, return at once.
  if (argv.includes("--kick")) { try { kick(); } catch {} process.exit(0); }
  if (mode === "html") { runHtml().then(() => process.exit(0)).catch(() => process.exit(0)); return; }
  if (mode === "text") { runText().then(() => process.exit(0)).catch(() => process.exit(0)); return; }
  if (mode === "json") { runJson(forId).then(() => process.exit(0)).catch(() => process.exit(0)); return; }

  // statusline: read CC's stdin payload with a watchdog, never hang the TUI.
  let input = "";
  const guard = setTimeout(() => finish(), 3000);
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (c) => (input += c));
  process.stdin.on("end", finish);

  let done = false;
  function finish() {
    if (done) return;
    done = true;
    clearTimeout(guard);
    let payload = {};
    try { payload = JSON.parse(input || "{}"); } catch { /* render what we can */ }
    runStatusline(payload)
      .then(() => process.exit(0))
      .catch(() => process.exit(0));
  }
}

// Requiring the module (tests) must not start anything: no stdin read, no spawn, no kick.
if (require.main === module) main();

module.exports.__test = {
  recipientActivity,
  unreadTotal,
  recentUnread,
  unreadCount,
  resolveFocus,
  mailThreads,
  readStreams,
  relatedSessions,
  mailLiveHours,
  renderText,
  renderHtml,
  loadConfig,
  ORCH_REPO_DIR,
};

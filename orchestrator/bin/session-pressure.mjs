#!/usr/bin/env node
// Session-pressure notice: warn when open sessions stack up past what the laptop
// can handle, and list idle ones the owner can safely archive.
//
//   node session-pressure.mjs [--json] [--notify]
//
// Reads /proc/meminfo + /proc/loadavg, every claude process (pid, RSS, cwd,
// session id, idle age), Frood MCP server count + RSS, and opencode count + RSS.
// Prints one summary line and the idle sessions (>= 30 min), oldest first.
// --notify sends notify-send when the level rises or every 60 min while
// warn-or-above (rate-limited through a state file). Skips all notifying when
// ORCH_NO_NOTIFY=1, and is a no-op on non-Linux or when /proc is missing.
// It never kills, archives or renices anything — only reports.
//
//   export function measure(procRoot, clock, homeDir)  // injectable /proc root, clock, home
//   export function level(freeGB, claudeN, load5)        // pure level decision
//   export function shouldNotify(prev, nowMs, lvl)       // notify decision + rate-limit
//
// State: <ORCH_HOME || ~>/.config/orchestrator/session-pressure.json
//   { lastLevel, lastNotifyMs, cpuTime: { [pid]: ns } }
// Exit 0 always (best effort: a thrown error is a no-op).

import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync } from "node:child_process";

const GB = 1024 * 1024;
const IDLE_MIN = 30;
const NOTIFY_MS = 60 * 60 * 1000;
const NOTIFY_CAP = 8; // oldest idle sessions to show in a notification body

// Env-overridable thresholds. ORCH_PRESSURE_* (values in GB, sessions, load).
const MEM_OK_GB = envNum("ORCH_PRESSURE_MEM_OK_GB", 8);
const MEM_CRIT_GB = envNum("ORCH_PRESSURE_MEM_CRIT_GB", 4);
const CLAUDE_OK = envNum("ORCH_PRESSURE_CLAUDE_OK", 12);
const LOAD_OK = envNum("ORCH_PRESSURE_LOAD_OK", 6);
const LOAD_CRIT = envNum("ORCH_PRESSURE_LOAD_CRIT", 7.5);

function envNum(name, def) {
  const v = Number(process.env[name]);
  return Number.isFinite(v) ? v : def;
}

function resolveHome(homeDir) {
  return homeDir ?? process.env.ORCH_HOME ?? os.homedir();
}

function statePath(homeDir) {
  return path.join(resolveHome(homeDir), ".config", "orchestrator", "session-pressure.json");
}

export function readState(homeDir) {
  try {
    const s = JSON.parse(fs.readFileSync(statePath(homeDir), "utf8"));
    return s && typeof s === "object" ? s : {};
  } catch {
    return {};
  }
}

export function writeState(s, homeDir) {
  try {
    fs.mkdirSync(path.dirname(statePath(homeDir)), { recursive: true });
    fs.writeFileSync(statePath(homeDir), JSON.stringify(s));
  } catch {
    // best effort: notifying without state still works (just no rate-limit memory)
  }
}

function meminfo(procRoot) {
  // <procRoot>/meminfo key -> kB string. MemAvailable when present, else MemFree+Buffers+Cached.
  let availKb = null;
  let freeKb = null;
  try {
    const lines = fs.readFileSync(path.join(procRoot, "meminfo"), "utf8").split(/\r?\n/);
    for (const line of lines) {
      const m = line.match(/^(MemAvailable|MemFree|Buffers|Cached):\s*(\d+)\s*kB/);
      if (!m) continue;
      const n = Number(m[2]);
      if (m[1] === "MemAvailable") availKb = n;
      if (m[1] === "MemFree") freeKb = n;
      if (m[1] === "Buffers" || m[1] === "Cached") freeKb = (freeKb ?? 0) + n;
    }
  } catch {
    // /proc missing (non-Linux): no-op everywhere
  }
  return { availKb, freeKb };
}

function load5(procRoot) {
  try {
    const m = fs.readFileSync(path.join(procRoot, "loadavg"), "utf8").match(/^([\d.]+)/);
    return m ? Number(m[1]) : null;
  } catch {
    return null;
  }
}

function rssKb(procRoot, pid) {
  try {
    const status = fs.readFileSync(path.join(procRoot, String(pid), "status"), "utf8");
    const m = status.match(/^VmRSS:\s*(\d+)\s*kB/m);
    return m ? Number(m[1]) : null;
  } catch {
    return null;
  }
}

function cpuTimeMs(procRoot, pid) {
  // /proc/<pid>/stat field 14 = utime, field 15 = stime, in clock ticks.
  try {
    const f = fs.readFileSync(path.join(procRoot, String(pid), "stat"), "utf8").split(" ");
    const ticks = Number(f[13]) + Number(f[14]);
    return Number.isFinite(ticks) ? ticks * 10 : null; // CLK_TCK=100 -> 10 ms per tick
  } catch {
    return null;
  }
}

function procCwd(procRoot, pid) {
  try {
    return fs.readlinkSync(path.join(procRoot, String(pid), "cwd"));
  } catch {
    return null;
  }
}

function procCmdline(procRoot, pid) {
  try {
    return fs.readFileSync(path.join(procRoot, String(pid), "cmdline"), "utf8").replace(/\0/g, " ").trim();
  } catch {
    return "";
  }
}

function procArgv0(procRoot, pid) {
  // argv[0] is the first NUL-terminated segment of cmdline.
  try {
    const raw = fs.readFileSync(path.join(procRoot, String(pid), "cmdline"), "utf8");
    return raw.split("\0")[0];
  } catch {
    return "";
  }
}

function cwdSlug(cwd, home) {
  // <home>/.claude/projects/<slug>: home-relative path, slashes -> dashes.
  if (!cwd) return "home";
  let rel = cwd;
  if (home && rel.startsWith(home)) rel = rel.slice(home.length);
  rel = rel.replace(/^\/+/, "");
  return rel.replace(/\//g, "-") || "home";
}

// Read a live-session file <home>/.claude/sessions/<pid>.json.
// Returns { sessionId, cwd, name, status, statusUpdatedAt } or null.
function sessionFile(home, pid) {
  try {
    const s = JSON.parse(fs.readFileSync(path.join(home, ".claude", "sessions", String(pid) + ".json"), "utf8"));
    if (!s || typeof s !== "object") return null;
    return {
      sessionId: s.sessionId || null,
      cwd: s.cwd || null,
      name: s.name || null,
      status: s.status || null,
      statusUpdatedAt: s.statusUpdatedAt != null ? Number(s.statusUpdatedAt) : null,
    };
  } catch {
    return null;
  }
}

// Transcript mtime fallback for idle age, and title fallback.
function transcriptInfo(home, sessionId, cwd, nowMs) {
  if (!cwd || !sessionId) return { ms: null, title: null };
  const tdir = path.join(home, ".claude", "projects", cwdSlug(cwd, home));
  const tfile = path.join(tdir, `${sessionId}.jsonl`);
  let ms = null;
  let title = null;
  try {
    const st = fs.statSync(tfile);
    ms = nowMs - st.mtimeMs;
  } catch {}
  try {
    const content = fs.readFileSync(tfile, "utf8");
    const mt = content.match(/"title":"([^"]{0,80})"/);
    if (mt) title = mt[1];
  } catch {}
  return { ms, title };
}

// ---- pure, exported helpers -------------------------------------------------

export function level(freeGB, claudeN, load5) {
  if (freeGB != null && freeGB < MEM_CRIT_GB) return "critical";
  if (load5 != null && load5 > LOAD_CRIT) return "critical";
  if (freeGB != null && freeGB < MEM_OK_GB) return "warn";
  if (claudeN > CLAUDE_OK) return "warn";
  if (load5 != null && load5 > LOAD_OK) return "warn";
  return "ok";
}

function levelRank(l) {
  return { ok: 0, warn: 1, critical: 2 }[l] ?? 0;
}

// Decide whether to notify now. Returns { notify, reason }.
// Notifies when the level rises above the last observed level (ok included) or
// every NOTIFY_MS while warn-or-above. ok never notifies.
export function shouldNotify(prev, nowMs, lvl) {
  const last = prev.lastLevel;
  const lastNotify = prev.lastNotifyMs;
  const rising = last != null && levelRank(lvl) > levelRank(last);
  const overdue = lastNotify == null || nowMs - lastNotify >= NOTIFY_MS;
  const notify = lvl !== "ok" && (rising || overdue);
  return {
    notify,
    reason: rising ? "level rose" : overdue ? "60 min elapsed" : "unchanged",
  };
}

// ---- measurement -----------------------------------------------------------

function measureOnce(procRoot, clock, homeDir) {
  const now = clock ? clock() : Date.now();
  const home = resolveHome(homeDir);
  const mi = meminfo(procRoot);
  const freeGb = mi.availKb != null ? mi.availKb / (1024 * 1024) : null;
  const load = load5(procRoot);

  // Count a process as a session only when the basename of argv[0] is "claude"
  // (excludes the claude-desktop disclaimer wrapper and other helper processes).
  // Dedupe by session id, keeping the larger RSS.
  // mcp_server.py and opencode are counted separately for every process.
  let mcpN = 0, mcpRss = 0;
  let ocN = 0, ocRss = 0;
  const bySession = new Map(); // sessionId -> entry (largest rss)
  const sessions = [];

  // Process CPU-time state, read once and written once at the end.
  // cpuTimes maps pid -> { cpuMs, sinceMs }: cpuMs is the last observed CPU time and
  // sinceMs is when it first stopped changing (idle age = now - sinceMs while unchanged).
  const state = readState(home);
  const cpuTimes = state.cpuTime || {};
  const seenPids = new Set();

  try {
    const entries = fs.readdirSync(procRoot, { withFileTypes: true });
    for (const e of entries) {
      if (!e.isDirectory() || !/^\d+$/.test(e.name)) continue;
      const pid = Number(e.name);
      const cmd = procCmdline(procRoot, pid);
      const low = cmd.toLowerCase();
      const rss = rssKb(procRoot, pid);
      if (low.includes("mcp_server.py")) {
        mcpN += 1; if (rss != null) mcpRss += rss;
      } else if (low.includes("opencode") || low.includes("opencode-pty")) {
        ocN += 1; if (rss != null) ocRss += rss;
      }
      if (path.basename(procArgv0(procRoot, pid)) !== "claude") continue;
      seenPids.add(pid);

      const sf = sessionFile(home, pid);
      const resume = procCmdline(procRoot, pid).match(/--resume=([^\s]+)/);
      const sessionId = (sf && sf.sessionId) ? sf.sessionId : (resume ? resume[1] : "");
      const cwd = (sf && sf.cwd) ? sf.cwd : procCwd(procRoot, pid);
      const rssGb = rss != null ? rss / GB : null;

      // Idle age: session file (status idle -> now - statusUpdatedAt) first,
      // then transcript mtime, then process CPU-time delta tracked in state.
      let idleMs, idleSource;
      let title = sf ? sf.name : null;
      if (sf) {
        if (sf.status === "idle") {
          idleMs = sf.statusUpdatedAt != null ? now - sf.statusUpdatedAt : null;
          idleSource = "session-file";
        } else {
          idleMs = 0; // non-idle status: not idle
          idleSource = "session-file";
        }
      } else {
        const tr = transcriptInfo(home, sessionId, cwd, now);
        idleMs = tr.ms;
        idleSource = tr.ms != null ? "transcript" : "none";
        title = tr.title;
      }

      // CPU-time fallback for idle age when nothing else is available.
      if (idleMs == null) {
        const cpuMs = cpuTimeMs(procRoot, pid);
        const prev = cpuTimes[String(pid)];
        if (prev == null) {
          // First read for this pid: nothing to measure yet; idle age starts at 0.
          idleMs = 0;
          cpuTimes[String(pid)] = { cpuMs, sinceMs: now };
        } else if (cpuMs != null && cpuMs === prev.cpuMs) {
          // CPU time unchanged since prev read: the span of stillness is the idle age.
          idleMs = now - prev.sinceMs;
        } else {
          // CPU time changed (or unreadable): reset the stillness clock.
          idleMs = 0;
          if (cpuMs != null) cpuTimes[String(pid)] = { cpuMs, sinceMs: now };
        }
        idleSource = idleMs != null ? "cpu" : "none";
      }

      const entry = { pid, sessionId, cwd, rss: rssGb, idleMs, idleSource, title };

      if (sessionId) {
        const existing = bySession.get(sessionId);
        if (existing) {
          if (rssGb != null && (existing.rss == null || rssGb > existing.rss)) {
            // keep the larger RSS; merge idle/title info from the winning entry
            bySession.set(sessionId, {
              ...existing,
              ...entry,
              rss: Math.max(existing.rss ?? 0, rssGb ?? 0),
            });
          }
        } else {
          bySession.set(sessionId, entry);
        }
      } else {
        sessions.push(entry);
      }
    }
  } catch {
    // /proc unreadable: nothing measurable
  }

  // Prune state for pids that are gone.
  for (const pid of Object.keys(cpuTimes)) {
    if (!seenPids.has(Number(pid))) delete cpuTimes[pid];
  }

  state.cpuTime = cpuTimes;
  writeState(state, home);

  for (const e of bySession.values()) sessions.push(e);

  const idle = sessions
    .filter((s) => s.idleMs != null && s.idleMs >= IDLE_MIN * 60 * 1000)
    .sort((a, b) => (b.idleMs ?? 0) - (a.idleMs ?? 0));

  return {
    now,
    freeGb,
    load,
    claudeN: sessions.length,
    mcpN, mcpRss: mcpRss / GB, ocN, ocRss: ocRss / GB,
    sessions,
    idle,
  };
}

export function measure(procRoot = "/proc", clock = undefined, homeDir = undefined) {
  // non-Linux or missing /proc: a no-op (nothing measurable, nothing to report)
  if (process.platform !== "linux") {
    return { freeGb: null, load: null, claudeN: 0, mcpN: 0, mcpRss: 0, ocN: 0, ocRss: 0, sessions: [], idle: [] };
  }
  try {
    return measureOnce(procRoot, clock, homeDir);
  } catch {
    return { freeGb: null, load: null, claudeN: 0, mcpN: 0, mcpRss: 0, ocN: 0, ocRss: 0, sessions: [], idle: [] };
  }
}

function fmtRss(g) {
  // Under 1 GB: whole MB (e.g. 312 MB). From 1 GB up: one decimal (e.g. 5.5 GB).
  if (g == null) return "?";
  const mb = g * 1024;
  if (mb < 1024) return `${Math.round(mb)} MB`;
  return `${g.toFixed(1)} GB`;
}

function fmtIdle(ms) {
  const m = Math.floor(ms / 60000);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}h ${m % 60}m` : `${m}m`;
}

export function summaryLine(lvl, m) {
  const free = fmtRss(m.freeGb);
  const load = m.load == null ? "?" : m.load.toFixed(1);
  const rss = fmtRss(m.claudeN ? m.sessions.reduce((a, s) => a + (s.rss ?? 0), 0) : 0);
  return `${lvl}: ${m.claudeN} sessions, ${rss}; ${free} free; load ${load}`;
}

function idleLines(m) {
  if (!m.idle.length) return [];
  const lines = ["idle sessions (oldest first):"];
  const shown = m.idle.slice(0, NOTIFY_CAP);
  for (const s of shown) {
    const base = s.cwd ? path.basename(s.cwd) : "?";
    const prefix = s.sessionId ? s.sessionId.slice(0, 8) : "-";
    lines.push(`  ${base} ${prefix} ${fmtIdle(s.idleMs)} ${fmtRss(s.rss)}${s.title ? ` — ${s.title}` : ""}`);
  }
  if (m.idle.length > NOTIFY_CAP) lines.push(`  +${m.idle.length - NOTIFY_CAP} more`);
  return lines;
}

export function reportText(m) {
  const lvl = level(m.freeGb, m.claudeN, m.load);
  return [summaryLine(lvl, m), ...idleLines(m), "archive finished sessions in the Claude app sidebar"].join("\n");
}

// summary + body for a notification: summary line as the summary, idle lines
// (capped at NOTIFY_CAP oldest, "+N more" after) plus the archive line as body.
export function notifyParts(lvl, m) {
  const summary = summaryLine(lvl, m);
  const body = [...idleLines(m), "archive finished sessions in the Claude app sidebar"].join("\n");
  return { summary, body };
}

// ---- notify -----------------------------------------------------------------

export function notifyNow(lvl, summary, body) {
  if (process.env.ORCH_NO_NOTIFY === "1") return;
  try {
    const u = lvl === "critical" ? "critical" : "normal";
    execFileSync("notify-send", ["-u", u, "orchestrator", summary, body], { stdio: "ignore", windowsHide: true });
  } catch {
    // best effort
  }
}

export function shouldRunNotify(prev, nowMs, lvl) {
  return shouldNotify(prev, nowMs, lvl).notify;
}

// ---- CLI -------------------------------------------------------------------

function main(argv) {
  let json = false, notify = false;
  for (const a of argv) {
    if (a === "--json") json = true;
    else if (a === "--notify") notify = true;
    else {
      console.error("usage: session-pressure.mjs [--json] [--notify]");
      return 2;
    }
  }
  try {
    const m = measure();
    // no-op: /proc unreadable or non-Linux — nothing to report, nothing to notify
    if (m.freeGb === null) return 0;
    const lvl = level(m.freeGb, m.claudeN, m.load);
    const text = reportText(m);
    if (json) {
      console.log(JSON.stringify({ level: lvl, ...m, report: text }, null, 2));
    } else {
      console.log(text);
    }
    if (notify) {
      const prev = readState();
      const now = m.now;
      const d = shouldNotify(prev, now, lvl);
      if (d.notify && lvl !== "ok") {
        const { summary, body } = notifyParts(lvl, m);
        notifyNow(lvl, summary, body);
        prev.lastNotifyMs = now;
      }
      // Record the observed level on every --notify tick, including ok.
      prev.lastLevel = lvl;
      writeState(prev);
    }
    return 0;
  } catch {
    return 0;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}

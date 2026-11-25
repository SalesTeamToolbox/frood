#!/usr/bin/env node
// Session-pressure notice: warn when open sessions stack up past what the laptop
// can handle, and list idle ones the owner can safely archive.
//
//   node session-pressure.mjs [--json] [--notify]
//
// Reads /proc/meminfo + /proc/loadavg, every claude process (pid, RSS, cwd,
// session id from --resume=<id>, idle age), Frood MCP server count + RSS, and
// opencode count + RSS. Prints one summary line and the idle sessions (>= 30 min),
// oldest first. --notify sends notify-send when the level rises or every 60 min
// while warn-or-above (rate-limited through a state file). Skips all notifying
// when ORCH_NO_NOTIFY=1, and is a no-op on non-Linux or when /proc is missing.
// It never kills, archives or renices anything — only reports.
//
//   export function measure(procRoot, clock)  // injectable /proc root + clock
//   export function level(freeGB, claudeN, load5)  // pure level decision
//   export function shouldNotify(prev, nowMs, level)  // notify decision + rate-limit
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

function statePath() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "session-pressure.json");
}

export function readState() {
  try {
    const s = JSON.parse(fs.readFileSync(statePath(), "utf8"));
    return s && typeof s === "object" ? s : {};
  } catch {
    return {};
  }
}

export function writeState(s) {
  try {
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    fs.writeFileSync(statePath(), JSON.stringify(s));
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


function cwdSlug(cwd) {
  // ~/.claude/projects/<slug> matches the home-relative path with slashes -> dashes.
  const rel = cwd.replace(os.homedir(), "").replace(/^\/+/, "");
  return rel.replace(/\//g, "-") || "home";
}

function findIdleAge(sessionId, cwd, nowMs) {
  // Prefer transcript mtime; fall back to process CPU-time delta tracked in state.
  if (!cwd) return { ms: null, source: "none" };
  const tdir = path.join(os.homedir(), ".claude", "projects", cwdSlug(cwd));
  const tfile = path.join(tdir, `${sessionId}.jsonl`);
  try {
    const st = fs.statSync(tfile);
    return { ms: nowMs - st.mtimeMs, source: "transcript" };
  } catch {
    // no transcript: fall back below
  }
  return { ms: null, source: "none" };
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

// Decide whether to notify now, and record the result. prev = last state.
// Returns { notify: boolean, reason: string }. Rate-limits: notifies when the
// level rises above the last reported level, or every NOTIFY_MS while warn+.
export function shouldNotify(prev, nowMs, lvl) {
  const last = prev.lastLevel;
  const lastNotify = prev.lastNotifyMs;
  const rising = last && last !== "ok" && lvl !== "ok" && levelRank(lvl) > levelRank(last);
  const overdue = lastNotify == null || nowMs - lastNotify >= NOTIFY_MS;
  const notify = (lvl !== "ok") && (rising || overdue);
  return { notify, reason: rising ? "level rose" : overdue ? "60 min elapsed" : "unchanged" };
}

function levelRank(l) {
  return { ok: 0, warn: 1, critical: 2 }[l] ?? 0;
}

// ---- measurement -----------------------------------------------------------

function measureOnce(procRoot, clock) {
  const now = clock ? clock() : Date.now();
  const mi = meminfo(procRoot);
  const freeGb = mi.availKb != null ? mi.availKb / (1024 * 1024) : null;
  const load = load5(procRoot);

  // Count processes. On this box "claude" means the claude code binary
  // (comm == "claude"); mcp_server.py and opencode are counted by cmdline.
  let claudeProcs = [];
  let mcpN = 0, mcpRss = 0;
  let ocN = 0, ocRss = 0;

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
      if (/--resume=([^\s]+)/.test(cmd)) {
        claudeProcs.push({ pid, cmd, rss });
      }
    }
  } catch {
    // /proc unreadable: nothing measurable
  }

  // claude processes counted by comm regardless of --resume
  try {
    for (const e of fs.readdirSync(procRoot, { withFileTypes: true })) {
      if (!e.isDirectory() || !/^\d+$/.test(e.name)) continue;
      try {
        const comm = fs.readFileSync(path.join(procRoot, e.name, "comm"), "utf8").trim();
        if (comm === "claude" && !claudeProcs.some((c) => c.pid === Number(e.name))) {
          claudeProcs.push({ pid: Number(e.name), cmd: procCmdline(procRoot, Number(e.name)), rss: rssKb(procRoot, Number(e.name)) });
        }
      } catch {}
    }
  } catch {}

  const state = readState();
  const cpuTimes = state.cpuTime || {};
  const sessions = [];
  for (const c of claudeProcs) {
    const m = c.cmd.match(/--resume=([^\s]+)/);
    const sessionId = m ? m[1] : "";
    const cwd = procCwd(procRoot, c.pid);
    const idle = findIdleAge(sessionId, cwd, now);
    const rss = c.rss != null ? c.rss / GB : null;
    const cpuMs = cpuTimeMs(procRoot, c.pid);
    let idleMs = idle.ms;
    if (idleMs == null && cpuMs != null) {
      const prev = cpuTimes[String(c.pid)];
      idleMs = prev != null ? cpuMs - prev : null;
      cpuTimes[String(c.pid)] = cpuMs;
    }
    sessions.push({ pid: c.pid, sessionId, cwd, rss, idleMs, idleSource: idle.source });
  }

  const idle = sessions
    .filter((s) => s.idleMs != null && s.idleMs >= IDLE_MIN * 60 * 1000)
    .sort((a, b) => (b.idleMs ?? 0) - (a.idleMs ?? 0));

  state.cpuTime = cpuTimes;
  writeState(state);

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

export function measure(procRoot = "/proc", clock = undefined) {
  // non-Linux or missing /proc: a no-op (nothing measurable, nothing to report)
  if (process.platform !== "linux") {
    return { freeGb: null, load: null, claudeN: 0, mcpN: 0, mcpRss: 0, ocN: 0, ocRss: 0, sessions: [], idle: [] };
  }
  try {
    return measureOnce(procRoot, clock);
  } catch {
    return { freeGb: null, load: null, claudeN: 0, mcpN: 0, mcpRss: 0, ocN: 0, ocRss: 0, sessions: [], idle: [] };
  }
}

function fmtGb(g) {
  return g == null ? "?" : `${Math.round(g)} GB`;
}

function fmtIdle(ms) {
  const m = Math.floor(ms / 60000);
  const h = Math.floor(m / 60);
  return h > 0 ? `${h}h ${m % 60}m` : `${m}m`;
}

function titleOf(sessionId, cwd) {
  try {
    if (!cwd) return null;
    const tdir = path.join(os.homedir(), ".claude", "projects", cwdSlug(cwd));
    const tf = path.join(tdir, `${sessionId}.jsonl`);
    const content = fs.readFileSync(tf, "utf8");
    const mt = content.match(/"title":"([^"]{0,80})"/);
    if (mt) return mt[1];
    const ct = path.join(tdir, "custom-title.json");
    try {
      const cj = JSON.parse(fs.readFileSync(ct, "utf8"));
      if (cj.customTitle) return cj.customTitle;
    } catch {}
    return null;
  } catch {
    return null;
  }
}

export function reportText(m) {
  const free = fmtGb(m.freeGb);
  const load = m.load == null ? "?" : m.load.toFixed(1);
  const lines = [`${m.claudeN} sessions, ${fmtGb(m.claudeN ? m.sessions.reduce((a, s) => a + (s.rss ?? 0), 0) : 0)}; ${free} free; load ${load}`];
  if (m.idle.length) {
    lines.push("idle sessions (oldest first):");
    for (const s of m.idle) {
      const title = titleOf(s.sessionId, s.cwd);
      const base = s.cwd ? path.basename(s.cwd) : "?";
      const prefix = s.sessionId ? s.sessionId.slice(0, 8) : "-";
      lines.push(`  ${base} ${prefix} ${fmtIdle(s.idleMs)} ${fmtGb(s.rss)}${title ? ` — ${title}` : ""}`);
    }
  }
  lines.push("archive finished sessions in the Claude app sidebar");
  return lines.join("\n");
}

// ---- notify ----------------------------------------------------------------

export function notifyNow(lvl, text) {
  if (process.env.ORCH_NO_NOTIFY === "1") return;
  try {
    const u = lvl === "critical" ? "critical" : "normal";
    execFileSync("notify-send", ["-u", u, "orchestrator", text], { stdio: "ignore", windowsHide: true });
  } catch {
    // best effort
  }
}

export function shouldRunNotify(prev, nowMs, lvl) {
  const d = shouldNotify(prev, nowMs, lvl);
  return d.notify;
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
    if (notify && lvl !== "ok") {
      const prev = readState();
      const now = m.now;
      if (shouldRunNotify(prev, now, lvl)) {
        notifyNow(lvl, text.split("\n")[0]);
        prev.lastLevel = lvl;
        prev.lastNotifyMs = now;
        writeState(prev);
      }
    }
    return 0;
  } catch {
    return 0;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = main(process.argv.slice(2));
}

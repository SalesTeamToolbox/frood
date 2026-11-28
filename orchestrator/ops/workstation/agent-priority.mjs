#!/usr/bin/env node
// Frood workstation agent priority guard (Linux only).
//
// Loops every 15 s and renices every thread of every agent process tree to
// nice >= 10, never lowering a nice value and never touching a non-agent tree.
// Agent roots: claude, opencode, codex, gemini, aider, cursor-agent, copilot,
// copilot-runtime, goose, amp (by exe/argv[0] name), plus node/bun/python/
// python3/deno whose argv names an agent package (@openai/codex,
// @google/gemini-cli, @github/copilot, opencode-ai, @sourcegraph/amp,
// aider, claude-code). The Claude desktop UI under /usr/lib/claude-desktop/,
// /opt/Claude or /usr/lib/electron* is never a root.
//
// Proc root is ORCH_PROC_ROOT || /proc (same name slots.mjs:21 uses). Tests
// inject a fake proc root and a fake setPriority through runPass(), so no real
// process is ever reniced by a test.
//
// SPIKE SAMPLING: each loop pass keeps the previous pass's pid->ticks map and,
// when load1 >= 0.75*nproc or PSI some avg10 >= 20, logs the top-8 CPU consumers
// (agent trees and ~/projects only; vault paths redacted) to
// <stateDir>/spikes.jsonl (rotated like the priority-guard log). The sampler is
// pure (spikeSample) and never breaks or slows a renice pass.
//
//   node agent-priority.mjs        loop forever (SIGTERM/SIGINT exit 0)
//   node agent-priority.mjs --once one pass, print what it lowered
//   any other arg                  exit 2 with usage
//
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

const TARGET_NICE = 10;
const GUARD_PID = process.pid;
const LOG_MAX = 512 * 1024;
const DEFAULT_INTERVAL_MS = 15000;

function defaultProcRoot() {
  return process.env.ORCH_PROC_ROOT || "/proc";
}
function stateDir() {
  return process.env.FROOD_WS_STATE || path.join(os.homedir(), ".local", "state", "frood-workstation");
}
function pauseFile() {
  return path.join(stateDir(), "priority-guard.off");
}
function logFile() {
  return path.join(stateDir(), "priority-guard.log");
}
function intervalMs() {
  return Number(process.env.FROOD_WS_INTERVAL_MS || DEFAULT_INTERVAL_MS) || DEFAULT_INTERVAL_MS;
}

const ROOT_NAME_RE = /^(claude|opencode\d*|codex|gemini|aider|cursor-agent|copilot|copilot-runtime|goose|amp)$/;
const INTERPRETER_RE = /^(node|bun|python|python3|deno)$/;
// argv[1..] element that marks an agent launched through an interpreter.
// Anchored on path-segment boundaries so `/work/claude-code-foo/x.js` does not
// match while `/x/node_modules/@anthropic-ai/claude-code/cli.js` does, and
// `raider` does not match `aider`. `aider` matches exactly, or ending in
// `/aider` or `aider/__main__.py`.
const AGENT_ARGV_RE =
  /(?:^|\/)(@openai\/codex|@google\/gemini-cli|@github\/copilot|opencode-ai|@sourcegraph\/amp|claude-code)(?:$|\/)|^aider$|\/aider$|(?:^|\/)aider\/__main__\.py$/;

function stripExe(name) {
  return String(name).replace(/\.exe$/i, "");
}
function baseName(p) {
  return path.basename(String(p || ""));
}

// exe or argv[0] under a desktop/electron install: never a root, even when
// named `claude`. Claude Code under ~/.config/Claude/claude-code/ is not one of
// these, so it matches rule (a) by name.
function isDesktopPath(p) {
  if (!p) return false;
  return (
    p.startsWith("/usr/lib/claude-desktop/") ||
    p.startsWith("/opt/Claude") ||
    p.startsWith("/usr/lib/electron")
  );
}

function readNice(statText) {
  // /proc/<pid>/stat: pid (comm) state ppid ... nice is field 19; everything
  // after the last ')' is whitespace split, field 3 = rest[0], field 19 =
  // rest[16].
  const close = statText.lastIndexOf(")");
  if (close === -1) return NaN;
  const rest = statText.slice(close + 2).trim().split(/\s+/);
  return Number(rest[16]);
}

export function readProc(procRoot, pidStr) {
  let stat;
  try {
    stat = fs.readFileSync(path.join(procRoot, pidStr, "stat"), "utf8");
  } catch {
    return null; // vanished between readdir and read
  }
  const close = stat.lastIndexOf(")");
  if (close === -1) return null;
  const comm = stat.slice(stat.indexOf("(") + 1, close);
  const rest = stat.slice(close + 2).trim().split(/\s+/);
  const ppid = Number(rest[1]);
  const nice = Number(rest[16]);
  // stat fields 14 (utime) and 15 (stime) are rest[11] and rest[12] after the
  // leading state field (field 3) that heads `rest`.
  const ticks = (Number(rest[11] || 0) + Number(rest[12] || 0));
  let argv = [];
  try {
    argv = fs.readFileSync(path.join(procRoot, pidStr, "cmdline"), "utf8").split("\0").filter(Boolean);
  } catch {
    argv = [];
  }
  let exe = "";
  try {
    exe = fs.readlinkSync(path.join(procRoot, pidStr, "exe"));
  } catch {
    exe = "";
  }
  let uid = null;
  let rssKiB = null;
  try {
    const statusText = fs.readFileSync(path.join(procRoot, pidStr, "status"), "utf8");
    const m = statusText.match(/^Uid:\s+(\d+)/m);
    if (m) uid = Number(m[1]);
    const rss = statusText.match(/^VmRSS:\s+(\d+)/m);
    if (rss) rssKiB = Number(rss[1]);
  } catch {
    uid = null;
  }
  return { pid: Number(pidStr), ppid, comm, argv, exe, nice, uid, ticks, rssKiB };
}

function gatherSnapshot(procRoot) {
  const procs = new Map();
  let entries;
  try {
    entries = fs.readdirSync(procRoot);
  } catch {
    return procs;
  }
  for (const name of entries) {
    if (!/^\d+$/.test(name)) continue;
    const p = readProc(procRoot, name);
    if (p) procs.set(Number(name), p);
  }
  return procs;
}

function isAgentRoot(p) {
  const exeBase = stripExe(baseName(p.exe));
  const argv0Base = stripExe(baseName(p.argv[0]));
  const desktop = isDesktopPath(p.exe) || isDesktopPath(p.argv[0]);
  if (ROOT_NAME_RE.test(exeBase) || ROOT_NAME_RE.test(argv0Base)) {
    return !desktop;
  }
  if (INTERPRETER_RE.test(exeBase) || INTERPRETER_RE.test(argv0Base)) {
    for (let i = 1; i < p.argv.length; i++) {
      if (AGENT_ARGV_RE.test(p.argv[i])) return !desktop;
    }
  }
  return false;
}

// Roots plus all descendants by ppid from the one snapshot; a pid is visited
// once. Orphans reparented to init are not reached from any root.
function walkDescendants(procs, roots) {
  const children = new Map();
  for (const [pid, p] of procs) {
    if (!children.has(p.ppid)) children.set(p.ppid, []);
    children.get(p.ppid).push(pid);
  }
  const visited = new Set();
  const stack = [...roots];
  while (stack.length) {
    const pid = stack.pop();
    if (visited.has(pid)) continue;
    visited.add(pid);
    for (const child of children.get(pid) || []) stack.push(child);
  }
  return visited;
}

// Production setpriority per thread. Node's os.setPriority calls
// setpriority(PRIO_PROCESS, pid, …), which is per-thread on Linux: passing a
// thread ID sets that thread's priority. ESRCH/ENOENT (vanished) are surfaced
// via err.info.code (err.code is "ERR_SYSTEM_ERROR") and handled by the caller.
export function realSetPriority(tid, value) {
  os.setPriority(tid, value);
}

// One pass. Returns { lowered, eperm, errors, roots, pids, paused }. Never throws.
// `log`, if given, is called once per lowered tid:
//   `<pid> <tid> <comm> <old>->10`
export function runPass({ procRoot, setPriority = realSetPriority, uid = process.getuid(), log } = {}) {
  const root = procRoot !== undefined ? procRoot : defaultProcRoot();
  if (fs.existsSync(pauseFile())) {
    return { lowered: 0, eperm: 0, roots: 0, pids: 0, paused: true };
  }
  let lowered = 0;
  let eperm = 0;
  let errors = 0;
  let roots = 0;
  let pids = 0;
  let procs = null;
  try {
    procs = gatherSnapshot(root);
    const rootPids = [];
    for (const p of procs.values()) {
      if (p.pid === GUARD_PID) continue;
      if (p.uid !== uid) continue;
      if (!isAgentRoot(p)) continue;
      rootPids.push(p.pid);
    }
    roots = rootPids.length;
    const set = walkDescendants(procs, rootPids);
    pids = set.size;
    for (const pid of set) {
      const p = procs.get(pid);
      if (!p || p.uid !== uid) continue;
      const taskDir = path.join(root, String(pid), "task");
      let tids;
      try {
        tids = fs.readdirSync(taskDir);
      } catch {
        continue;
      }
      for (const name of tids) {
        const tid = Number(name);
        if (!Number.isFinite(tid)) continue;
        let current;
        try {
          current = readNice(fs.readFileSync(path.join(taskDir, name, "stat"), "utf8"));
        } catch {
          continue; // ESRCH/ENOENT: vanished task
        }
        if (!Number.isFinite(current) || current >= TARGET_NICE) continue;
        // Never lower: only raise to TARGET_NICE, so 10 > current holds.
        if (!(TARGET_NICE > current)) continue;
        try {
          setPriority(tid, TARGET_NICE);
          lowered += 1;
          if (log) log(`${pid} ${tid} ${p.comm} ${current}->10`);
        } catch (err) {
          // Real os.setPriority throws code "ERR_SYSTEM_ERROR" with the errno
          // name in err.info.code (e.g. ESRCH for a vanished tid).
          const code = err?.info?.code ?? err?.code;
          if (code === "ESRCH") continue; // vanished task
          if (code === "EPERM" || code === "EACCES") {
            eperm += 1;
            continue;
          }
          errors += 1;
          console.error(`agent-priority: setpriority(${tid}, 10) failed: ${err && err.message}`);
        }
      }
    }
  } catch {
    // A pass never throws.
  }
  return { lowered, eperm, errors, roots, pids, procs, paused: false };
}

export function writePassLog(lowered, eperm, errors, roots) {
  try {
    fs.mkdirSync(stateDir(), { recursive: true });
    const lf = logFile();
    if (fs.existsSync(lf)) {
      try {
        if (fs.statSync(lf).size > LOG_MAX) fs.renameSync(lf, lf + ".1");
      } catch {
        // rotation is best-effort
      }
    }
    fs.appendFileSync(lf, `${new Date().toISOString()} lowered=${lowered} eperm=${eperm} errors=${errors} roots=${roots}\n`);
  } catch {
    // logging must never break a pass
  }
}

// --- spike sampler ----------------------------------------------------------

// Parse "some avg10 = N" (and variants like "full avg10") from /proc/pressure/cpu text.
function psiSomeAvg10(text) {
  const m = String(text || "").match(/\bsome\s+avg10=([0-9.]+)/);
  return m ? Number(m[1]) : null;
}

// Pure spike detector. Returns null unless spiking.
export function spikeSample({
  procs,
  prevTicks,
  elapsedMs,
  loadavgText,
  psiCpuText,
  nproc,
  clkTck = 100,
} = {}) {
  const load1 = Number((loadavgText || "").split(/\s+/)[0] || 0);
  const load5 = Number((loadavgText || "").split(/\s+/)[1] || 0);
  const cpuSomeAvg10 = psiSomeAvg10(psiCpuText);
  const spiking = load1 >= 0.75 * nproc || (cpuSomeAvg10 !== null && cpuSomeAvg10 >= 20);
  if (!spiking || !prevTicks || elapsedMs <= 0) return null;

  const sec = elapsedMs / 1000;
  const top = [];
  for (const [pid, p] of procs) {
    const prev = prevTicks.get(pid);
    const delta = p.ticks - (Number.isFinite(prev) ? prev : 0);
    if (!Number.isFinite(delta) || delta <= 0) continue;
    top.push({
      pid,
      comm: p.comm || "",
      argv: p.argv,        // carried for redaction in doPass; removed before output
      cmd: capArgv(p.argv),
      rssMiB: p.rssKiB === null ? null : Math.round(p.rssKiB / 1024),
      cpu: delta / clkTck / sec * 100,
      agentRoot: null,
      repo: null,
    });
  }
  top.sort((a, b) => b.cpu - a.cpu);
  top.length > 8 && (top.length = 8);
  attachAgentRoots(procs, top);
  return { load1, load5, cpuSomeAvg10, top };
}

// pid -> ticks (utime + stime) from a procs map.
export function ticksOf(procs) {
  const m = new Map();
  for (const [pid, p] of procs) m.set(pid, p.ticks);
  return m;
}

// Agent root: nearest ancestor (by ppid chain) that isAgentRoot accepts.
function agentRootOf(procs, pid) {
  let cur = pid;
  let seen = 0;
  while (cur !== undefined && cur !== 0 && seen < 1000) {
    const p = procs.get(cur);
    if (p && isAgentRoot(p)) return { pid: cur, comm: p.comm };
    cur = p ? p.ppid : 0;
    seen += 1;
  }
  return null;
}

// Fill agentRoot for each top entry (and nothing else) from the procs map.
function attachAgentRoots(procs, top) {
  for (const entry of top) {
    entry.agentRoot = agentRootOf(procs, entry.pid);
  }
}

// Pure privacy redaction for a spike top entry. Returns the fields to set
// (cmd, repo, vault) on an entry.
// - cmd and repo are kept ONLY when the process is in an agent tree
//   (agentRoot non-null) OR its cwd is under $HOME/projects/.
// - Always redact: if cwd or any argv element contains $HOME/Vault or
//   $HOME/.vault (also the realpath of cwd), set cmd/repo to null and vault: true.
// - Never log a full cwd: repo is the first path segment under $HOME/projects/,
//   or null.
const VAULT_SEGMENT_RE = /(^|[\/=:\s])\.?vault(\/|$)/i;
export function redactEntry({ argv, cwd, agentRoot }, home) {
  const vaultA = `${home}/Vault`;
  const vaultB = `${home}/.vault`;
  const projects = `${home}/projects/`;
  let redact = false;
  const realCwd = cwd ? tryRealpath(cwd) : null;
  const inVault =
    (cwd && (cwd.includes(vaultA) || cwd.includes(vaultB))) ||
    (realCwd && (realCwd.includes(vaultA) || realCwd.includes(vaultB)));
  const inProjects = cwd ? cwd.startsWith(projects) : false;
  const argvText = (argv || []).join("\0");
  // Absolute match, plus any path segment named Vault/.vault (any case) so relative forms such as
  // `../../Vault/x`, `Vault/p.txt` or `--file=../.vault/k` are caught too, and any element that
  // resolves under the vault from this cwd.
  const resolvesIntoVault = (el) => {
    if (!cwd || typeof el !== "string") return false;
    const r = path.resolve(cwd, el.includes("=") ? el.slice(el.indexOf("=") + 1) : el);
    return r === vaultA || r === vaultB || r.startsWith(vaultA + "/") || r.startsWith(vaultB + "/");
  };
  const argvInVault =
    argvText.includes(vaultA) || argvText.includes(vaultB) ||
    (argv || []).some((el) => VAULT_SEGMENT_RE.test(String(el)) || resolvesIntoVault(el)) ||
    (cwd ? VAULT_SEGMENT_RE.test(cwd) : false);
  if (inVault || argvInVault) redact = true;
  const keep = (agentRoot !== null) || inProjects;
  const cmd = keep && !redact ? capArgv(argv) : null;
  const repo = keep && !redact && inProjects ? repoSegment(cwd, home) : null;
  return { cmd, repo, vault: redact };
}

// realpath best-effort; null on failure.
function tryRealpath(p) {
  try {
    return fs.realpathSync(p);
  } catch {
    return null;
  }
}

function capArgv(argv) {
  return (argv || []).join(" ").slice(0, 160);
}

// First path segment under $HOME/projects/, else null.
function repoSegment(cwd, home) {
  const prefix = `${home}/projects/`;
  if (!cwd || !cwd.startsWith(prefix)) return null;
  const rest = cwd.slice(prefix.length);
  const seg = rest.split("/")[0];
  return seg ? `${home}/projects/${seg}` : null;
}

// Module scope: the run loop's sleep timer and its resolver, so a signal can
// interrupt the 15 s wait instead of stalling a `systemctl restart` behind it.
// Pause-transition state: doPass prints `paused` once on entering pause and
// `resumed` once on leaving it.
let sleepTimer = null;
let sleepResolve = null;
let lastPaused = false;
// Spike sampler state: the previous pass's pid -> ticks map and its timestamp.
// On the first pass there is no previous sample, so nothing is logged.
let prevTicks = null;
let prevTs = null;

function doPass({ sample = false } = {}) {
  const result = runPass({
    procRoot: defaultProcRoot(),
    setPriority: realSetPriority,
    uid: process.getuid(),
    log: (line) => {
      console.log(line);
    },
  });
  if (result.paused) {
    if (!lastPaused) console.log("paused");
    lastPaused = true;
    return { paused: true, lowered: 0, eperm: 0, roots: 0 };
  }
  if (lastPaused) console.log("resumed");
  lastPaused = false;
  if (result.lowered > 0 || result.eperm > 0 || result.errors > 0) {
    writePassLog(result.lowered, result.eperm, result.errors, result.roots);
  }
  // --- spike sampler (loop only, never --once, never tests) ---
  if (!sample) {
    prevTs = Date.now();
    return { paused: false, ...result };
  }
  try {
    const now = Date.now();
    const elapsedMs = prevTs === null ? null : now - prevTs;
    const root = defaultProcRoot();
    let loadavgText = "";
    try {
      loadavgText = fs.readFileSync(path.join(root, "loadavg"), "utf8").trim();
    } catch {
      loadavgText = "";
    }
    let psiCpuText = "";
    try {
      psiCpuText = fs.readFileSync(path.join(root, "pressure", "cpu"), "utf8");
    } catch {
      psiCpuText = "";
    }
    const home = process.env.HOME || "";
    const spike = spikeSample({
      procs: result.procs,
      prevTicks,
      elapsedMs,
      loadavgText,
      psiCpuText,
      nproc: os.cpus().length,
    });
    if (spike) {
      const state = stateDir();
      fs.mkdirSync(state, { recursive: true });
      const spikes = path.join(state, "spikes.jsonl");
      if (fs.existsSync(spikes)) {
        try {
          if (fs.statSync(spikes).size > LOG_MAX) fs.renameSync(spikes, spikes + ".1");
        } catch {
          // rotation is best-effort
        }
      }
      for (const entry of spike.top) {
        let cwd;
        try {
          cwd = fs.readlinkSync(path.join(root, String(entry.pid), "cwd"));
        } catch {
          cwd = null;
        }
        const redaction = redactEntry(
          { argv: entry.argv, cwd, agentRoot: entry.agentRoot },
          home,
        );
        entry.cmd = redaction.cmd;
        entry.repo = redaction.repo;
        entry.vault = redaction.vault;
        delete entry.argv;
      }
      fs.appendFileSync(
        spikes,
        JSON.stringify({ at: new Date().toISOString(), ...spike }) + "\n",
      );
    }
    prevTicks = ticksOf(result.procs);
    prevTs = now;
  } catch {
    // A sampler failure must never break or slow the renice pass.
  }
  return { paused: false, ...result };
}

function sleep(ms) {
  return new Promise((resolve) => {
    sleepResolve = resolve;
    sleepTimer = setTimeout(() => {
      sleepTimer = null;
      sleepResolve = null;
      resolve();
    }, ms);
  });
}

async function runLoop() {
  let stopping = false;
  const onSignal = () => {
    stopping = true;
    if (sleepTimer !== null) {
      clearTimeout(sleepTimer);
      sleepTimer = null;
    }
    if (sleepResolve) {
      const wake = sleepResolve;
      sleepResolve = null;
      wake();
    }
  };
  process.on("SIGTERM", onSignal);
  process.on("SIGINT", onSignal);
  try {
    while (!stopping) {
      doPass({ sample: true });
      if (stopping) break;
      await sleep(intervalMs());
    }
  } finally {
    process.removeListener("SIGTERM", onSignal);
    process.removeListener("SIGINT", onSignal);
  }
  process.exit(0);
}

function runOnce() {
  const result = doPass();
  if (!result.paused) {
    console.log(`lowered ${result.lowered} eperm ${result.eperm} errors ${result.errors} roots ${result.roots}`);
  }
  process.exit(0);
}

function usage() {
  console.error("usage: agent-priority.mjs [--once]");
  process.exit(2);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  if (args.length === 0) runLoop();
  else if (args.length === 1 && args[0] === "--once") runOnce();
  else usage();
}

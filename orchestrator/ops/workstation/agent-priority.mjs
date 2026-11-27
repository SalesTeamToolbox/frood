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

function readProc(procRoot, pidStr) {
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
  try {
    const m = fs.readFileSync(path.join(procRoot, pidStr, "status"), "utf8").match(/^Uid:\s+(\d+)/m);
    if (m) uid = Number(m[1]);
  } catch {
    uid = null;
  }
  return { pid: Number(pidStr), ppid, comm, argv, exe, nice, uid };
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
  try {
    const procs = gatherSnapshot(root);
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
  return { lowered, eperm, errors, roots, pids, paused: false };
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

// Module scope: the run loop's sleep timer and its resolver, so a signal can
// interrupt the 15 s wait instead of stalling a `systemctl restart` behind it.
// Pause-transition state: doPass prints `paused` once on entering pause and
// `resumed` once on leaving it.
let sleepTimer = null;
let sleepResolve = null;
let lastPaused = false;

function doPass() {
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
      doPass();
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

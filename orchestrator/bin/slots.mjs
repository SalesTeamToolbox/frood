#!/usr/bin/env node
// Machine-wide worker slots: a load-based cap that replaces the fixed WORKER_SLOTS default.
//
//   readSample()   -> { cpuSomeAvg300, load5, nproc, memAvailGiB, source } | null   (PSI / loadavg / meminfo)
//   slotConfig(env, cliSlots) -> { mode: "fixed", n } | { mode: "dynamic", min, max }
//   allowedSlots(sample, cfg, state, now) -> { allowed, max, reason, state }
//   decisionLog(cfg, entry) -> appends one JSON line to slot-decisions.log (rotation past maxLines)
//
// Pure except the explicit sampler/log functions; every file read is sync readFileSync, called once per poll.
// All env reads go through `env` (in tests: a temp fixture object, never the real process.env).
// procRoot defaults to ORCH_PROC_ROOT || "/proc" — every test points it at a temp fixtures dir.
// The decision log lives under ORCH_HOME like slotDir() in oc-worker.mjs.

import fs from "node:fs";
import os from "node:os";
import path from "node:path";

// ---- procRoot ----------------------------------------------------------------

function procRoot(env = process.env) {
  return env.ORCH_PROC_ROOT || "/proc";
}

// A source string describing where each sample field came from (for the null-sample reason text).
function sampleSource(root) {
  const have = [];
  try { fs.readFileSync(path.join(root, "pressure", "cpu"), "utf8"); have.push("psi"); } catch {}
  try { fs.readFileSync(path.join(root, "loadavg"), "utf8"); have.push("loadavg"); } catch {}
  try { fs.readFileSync(path.join(root, "meminfo"), "utf8"); have.push("meminfo"); } catch {}
  return have.join(",") || "none";
}

// Read one 5-minute load sample from /proc-ish files. Returns null when any source is missing or
// unparsable (no /proc on Windows/macOS, no PSI file, no MemAvailable line).
export function readSample({ procRoot: root } = {}) {
  const r = root || procRoot();
  let cpuSomeAvg300, load5, nproc, memAvailGiB;
  try {
    const psi = fs.readFileSync(path.join(r, "pressure", "cpu"), "utf8");
    // PSI cpu line: "some avg10=X avg300=Y avg600=Z" — avg300 is the 5-minute CPU-wait fraction.
    const line = psi.split(/\r?\n/).find((l) => l.startsWith("some "));
    const m = line ? /\bavg300=([0-9.]+)/.exec(line) : null;
    if (!m) return null;
    cpuSomeAvg300 = Number(m[1]);
    if (!Number.isFinite(cpuSomeAvg300)) return null;
  } catch {
    return null;
  }
  try {
    const fields = fs.readFileSync(path.join(r, "loadavg"), "utf8").trim().split(/\s+/);
    load5 = Number(fields[1]);
    if (!Number.isFinite(load5)) return null;
  } catch {
    return null;
  }
  try {
    const mem = fs.readFileSync(path.join(r, "meminfo"), "utf8");
    const m = /^MemAvailable:\s+([0-9]+)\s+kB/m.exec(mem);
    if (!m) return null;
    memAvailGiB = Number(m[1]) / 1024 / 1024;
    if (!Number.isFinite(memAvailGiB)) return null;
  } catch {
    return null;
  }
  nproc = os.availableParallelism();
  if (!Number.isFinite(nproc) || nproc < 1) return null;
  return { cpuSomeAvg300, load5, nproc, memAvailGiB, source: sampleSource(r) };
}

// ---- slotConfig --------------------------------------------------------------

function posInt(name, v) {
  if (typeof v !== "string" || v === "") throw new Error(`invalid ${name}: "${v}" (must be a positive integer)`);
  const n = Number(v);
  if (!Number.isInteger(n) || n < 1 || String(n) !== v.trim()) {
    // String(n) !== v.trim() rejects "2.5", " 2", "2 ", "02", "+2"
    throw new Error(`invalid ${name}: "${v}" (must be a positive integer)`);
  }
  return n;
}

export function slotConfig(env, cliSlots) {
  // --slots N wins over WORKER_SLOTS.
  if (cliSlots !== undefined && cliSlots !== null && cliSlots !== "") {
    const n = posInt("WORKER_SLOTS", String(cliSlots));
    return { mode: "fixed", n };
  }
  const raw = env.WORKER_SLOTS;
  if (raw === undefined || raw === "") {
    const min = posInt("WORKER_SLOTS_MIN", String(env.WORKER_SLOTS_MIN ?? 2));
    const max = posInt("WORKER_SLOTS_MAX", String(env.WORKER_SLOTS_MAX ?? 6));
    if (min > max) throw new Error(`invalid WORKER_SLOTS_MIN/MAX: min ${min} > max ${max}`);
    return { mode: "dynamic", min, max };
  }
  const n = posInt("WORKER_SLOTS", raw);
  return { mode: "fixed", n };
}

// ---- allowedSlots ------------------------------------------------------------

const CLEAR_CPU = 20;      // PSI some avg300 under 20% = the box is not waiting on CPU
const CLEAR_MEM_GIB = 4;   // more than 4 GiB MemAvailable
const CLEAR_FOR_MS = 60_000; // once clear, stay at min for this long before rising to max

function isClear(sample) {
  return sample.cpuSomeAvg300 < CLEAR_CPU
    && sample.load5 < 0.75 * sample.nproc
    && sample.memAvailGiB > CLEAR_MEM_GIB;
}

function reasonText(allowed, max, sample, source, mode) {
  if (mode === "fixed") return `slots ${allowed}/${max} (fixed)`;
  if (sample === null) return `slots ${allowed}/${max} (no load sample: ${source})`;
  return `slots ${allowed}/${max} (cpu wait ${sample.cpuSomeAvg300}%, load ${sample.load5}, ${sample.memAvailGiB.toFixed(0)} GiB free)`;
}

export function allowedSlots(sample, cfg, state, now) {
  state = state || { clearSince: null };
  let allowed, clearSince = state.clearSince;
  if (cfg.mode === "fixed") {
    allowed = cfg.n;
  } else if (sample === null) {
    allowed = cfg.min;
    clearSince = null;
  } else if (!isClear(sample)) {
    allowed = cfg.min;
    clearSince = null;
  } else {
    // clear now
    if (clearSince === null) clearSince = now;
    allowed = now - clearSince >= CLEAR_FOR_MS ? cfg.max : cfg.min;
  }
  return { allowed, max: cfg.mode === "fixed" ? cfg.n : cfg.max,
    reason: reasonText(allowed, cfg.mode === "fixed" ? cfg.n : cfg.max, sample,
      sample == null ? String(procRoot()) : sample.source, cfg.mode),
    state: { clearSince } };
}

// ---- decision log ------------------------------------------------------------

function decisionLogFile(env = process.env) {
  return path.join(env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "slot-decisions.log");
}

// Count slot dirs whose owner pid is still live.
// ---- Nvidia provider cap -----------------------------------------------------------------------------------
// NVIDIA_SLOTS=N (positive integer) is a fixed cap and turns the adaptive mode off. Unset (or not a positive
// integer): adaptive. NVIDIA_SLOTS_MAX (default 3) with no recent 429; within NVIDIA_COOLDOWN_MS (default 600000)
// of the last Nvidia 429 the cap is 1, then it steps up one per further quiet cooldown:
//   cap = min(max, 1 + floor((now - last429) / cooldown)).
// Pure: takes env, now and state ({ last429 } or null); the state file helpers below do the I/O.
const nvInt = (v) => (/^[1-9]\d*$/.test(String(v ?? "").trim()) ? Number(String(v).trim()) : null);

export function nvidiaCap({ env = process.env, now = Date.now(), state = null } = {}) {
  const fixed = nvInt(env.NVIDIA_SLOTS);
  if (fixed !== null) return { cap: fixed, fixed: true, max: fixed, last429: state?.last429 ?? null };
  const max = nvInt(env.NVIDIA_SLOTS_MAX) ?? 3;
  const cooldown = nvInt(env.NVIDIA_COOLDOWN_MS) ?? 600000;
  const last = Number.isFinite(state?.last429) ? state.last429 : null;
  if (last === null) return { cap: max, fixed: false, max, last429: null };
  const quiet = Math.max(0, now - last);
  return { cap: Math.min(max, 1 + Math.floor(quiet / cooldown)), fixed: false, max, last429: last };
}

const nvidiaStateFile = (dir) => path.join(dir, "provider-nvidia.state.json");
const nvidiaCapFile = (dir) => path.join(dir, "provider-nvidia.cap.json");

function readJson(file) {
  try { return JSON.parse(fs.readFileSync(file, "utf8")); } catch { return null; }
}
function writeJsonAtomic(file, obj) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, JSON.stringify(obj));
  fs.renameSync(tmp, file);
}

export function readNvidiaState(dir) {
  const st = readJson(nvidiaStateFile(dir));
  return st && Number.isFinite(st.last429) ? { last429: st.last429 } : null;
}

// An Nvidia rate-limit or quota was classified: remember when. tmp + rename, so a reader never sees half a file.
export function recordNvidia429(dir, now = Date.now()) {
  writeJsonAtomic(nvidiaStateFile(dir), { last429: now });
}

// The cap for a new admission now. Appends one decision line (decisionLog) when it differs from the last cap
// logged; that last cap lives in its own file so it can never clobber a concurrent recordNvidia429.
export function nvidiaCapNow(dir, { env = process.env, now = Date.now() } = {}) {
  const r = nvidiaCap({ env, now, state: readNvidiaState(dir) });
  const prev = readJson(nvidiaCapFile(dir))?.cap ?? null;
  if (prev !== r.cap) {
    const why = r.fixed ? "NVIDIA_SLOTS fixed" : r.last429 === null ? "no recent 429" : `429 at ${new Date(r.last429).toISOString()}`;
    try {
      decisionLog({ provider: "nvidia", cap: r.cap, prev, reason: `nvidia cap ${prev ?? "-"} -> ${r.cap} (${why})` }, { env });
      writeJsonAtomic(nvidiaCapFile(dir), { cap: r.cap });
    } catch {} // logging never changes admission
  }
  return r;
}

export function heldCount() {
  const dir = path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "slots");
  let count = 0;
  let names;
  try { names = fs.readdirSync(dir); } catch { return 0; }
  for (const n of names) {
    if (!n.startsWith("slot-")) continue;
    let owner;
    try { owner = JSON.parse(fs.readFileSync(path.join(dir, n, "owner"), "utf8")); } catch {}
    if (owner && owner.pid && alive(owner.pid)) count++;
  }
  return count;
}

export function alive(pid) {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
}

function rotateIfNeeded(file, maxLines) {
  let lines = 0;
  try {
    const data = fs.readFileSync(file, "utf8");
    lines = data.split("\n").length;
  } catch { return; } // missing file: nothing to rotate
  if (lines > maxLines) {
    const rotated = file + ".1";
    try { fs.renameSync(file, rotated); } catch { fs.copyFileSync(file, rotated); fs.truncateSync(file, 0); }
  }
}

export function decisionLog(entry, { maxLines = 5000, env = process.env } = {}) {
  const file = decisionLogFile(env);
  rotateIfNeeded(file, maxLines);
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.appendFileSync(file, JSON.stringify({ at: new Date().toISOString(), pid: process.pid, ...entry }) + "\n");
}

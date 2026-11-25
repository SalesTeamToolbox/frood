import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "os";
import path from "path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { readSample, slotConfig, allowedSlots, decisionLog, nvidiaCap, nvidiaCapNow, readNvidiaState, recordNvidia429 } from "../bin/slots.mjs";
import { acquireSlot, slotDir } from "../bin/oc-worker.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");
const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function tmp() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-slots-"));
  CLEAN.push(d);
  return d;
}

// Fixtures under ORCH_PROC_ROOT; every test sets ORCH_HOME to a temp dir.
function procFixture(root, { psi, load, mem } = {}) {
  fs.mkdirSync(path.join(root, "pressure"), { recursive: true });
  if (psi !== undefined) fs.writeFileSync(path.join(root, "pressure", "cpu"), psi);
  if (load !== undefined) fs.writeFileSync(path.join(root, "loadavg"), load);
  if (mem !== undefined) fs.writeFileSync(path.join(root, "meminfo"), mem);
}

// ---------------------------------------------------------------- readSample

test("readSample: parses PSI, loadavg, meminfo and availableParallelism", () => {
  const root = tmp();
  procFixture(root, {
    psi: "some avg10=0.5 avg300=5.5 avg600=0.2\n",
    load: "0.53 0.83 1.00 123/4567\n",
    mem: "MemAvailable: 13500000 kB\nMemTotal: 31000000 kB\n",
  });
  const s = readSample({ procRoot: root, env: { ORCH_PROC_ROOT: root } });
  assert.equal(s.cpuSomeAvg300, 5.5);
  assert.equal(s.load5, 0.83);
  assert.equal(s.nproc, os.availableParallelism());
  assert.ok(s.memAvailGiB > 12 && s.memAvailGiB < 13.5);
  assert.ok(typeof s.source === "string" && s.source.length > 0);
});

test("readSample: missing any file or field returns null", () => {
  const root = tmp();
  // all present
  procFixture(root, { psi: "some avg300=5\n", load: "0.53 0.83 1.00\n", mem: "MemAvailable: 13500000 kB\n" });
  assert.ok(readSample({ procRoot: root }) !== null);
  // missing pressure file
  fs.rmSync(path.join(root, "pressure", "cpu"));
  assert.equal(readSample({ procRoot: root }), null);
  // missing loadavg
  fs.writeFileSync(path.join(root, "pressure", "cpu"), "some avg300=5\n");
  fs.rmSync(path.join(root, "loadavg"));
  assert.equal(readSample({ procRoot: root }), null);
  // no MemAvailable line
  fs.writeFileSync(path.join(root, "loadavg"), "0.53 0.83 1.00\n");
  fs.writeFileSync(path.join(root, "meminfo"), "MemTotal: 31000000 kB\n");
  assert.equal(readSample({ procRoot: root }), null);
  // unparsable PSI (no avg300)
  fs.writeFileSync(path.join(root, "meminfo"), "MemAvailable: 13500000 kB\n");
  fs.writeFileSync(path.join(root, "pressure", "cpu"), "some avg10=0.1 avg600=0.2\n");
  assert.equal(readSample({ procRoot: root }), null);
  // defaults to ORCH_PROC_ROOT env when no procRoot given
  const root2 = tmp();
  procFixture(root2, { psi: "some avg300=7\n", load: "0.1 0.2 0.3\n", mem: "MemAvailable: 4000000 kB\n" });
  const old = process.env.ORCH_PROC_ROOT;
  process.env.ORCH_PROC_ROOT = root2;
  try {
    const s = readSample({});
    assert.equal(s.cpuSomeAvg300, 7);
    assert.equal(s.memAvailGiB, 4000000 / 1024 / 1024);
  } finally {
    if (old === undefined) delete process.env.ORCH_PROC_ROOT;
    else process.env.ORCH_PROC_ROOT = old;
  }
});

// ---------------------------------------------------------------- slotConfig

test("slotConfig: --slots beats WORKER_SLOTS; empty string = unset", () => {
  assert.deepEqual(slotConfig({ WORKER_SLOTS: "5" }, 3), { mode: "fixed", n: 3 });
  assert.deepEqual(slotConfig({ WORKER_SLOTS: "5" }, ""), { mode: "fixed", n: 5 }); // WORKER_SLOTS non-empty wins
  assert.deepEqual(slotConfig({ WORKER_SLOTS: "" }, ""), { mode: "dynamic", min: 2, max: 6 }); // both unset
  assert.deepEqual(slotConfig({}, undefined), { mode: "dynamic", min: 2, max: 6 });
  assert.deepEqual(slotConfig({ WORKER_SLOTS: "4" }, undefined), { mode: "fixed", n: 4 });
  assert.deepEqual(slotConfig({ WORKER_SLOTS: "", WORKER_SLOTS_MIN: "3", WORKER_SLOTS_MAX: "9" }, undefined), {
    mode: "dynamic", min: 3, max: 9,
  });
});

test("slotConfig: invalid values throw naming the variable", () => {
  for (const v of ["abc", "0", "2.5", "-1"]) {
    assert.throws(() => slotConfig({ WORKER_SLOTS: v }, undefined), (e) => e.message.includes(`invalid WORKER_SLOTS: "${v}"`));
  }
  assert.throws(() => slotConfig({ WORKER_SLOTS_MIN: "abc" }, undefined), (e) => e.message.includes("invalid WORKER_SLOTS_MIN"));
  assert.throws(() => slotConfig({ WORKER_SLOTS_MAX: "0" }, undefined), (e) => e.message.includes("invalid WORKER_SLOTS_MAX"));
  assert.throws(() => slotConfig({ WORKER_SLOTS_MIN: "6", WORKER_SLOTS_MAX: "2" }, undefined), (e) => e.message.includes("min 6 > max 2"));
});

test("slotConfig: WORKER_SLOTS non-empty fixed value wins over defaults", () => {
  assert.deepEqual(slotConfig({ WORKER_SLOTS: "1" }, undefined), { mode: "fixed", n: 1 });
});

// ---------------------------------------------------------------- allowedSlots

function clearSample() {
  return { cpuSomeAvg300: 5, load5: 1, nproc: 8, memAvailGiB: 13, source: "psi,loadavg,meminfo" };
}
function busyCpu() { return { cpuSomeAvg300: 31, load5: 1, nproc: 8, memAvailGiB: 13, source: "x" }; }
function busyLoad() { return { cpuSomeAvg300: 5, load5: 7, nproc: 8, memAvailGiB: 13, source: "x" }; } // 7 > 0.75*8=6
function busyMem() { return { cpuSomeAvg300: 5, load5: 1, nproc: 8, memAvailGiB: 3, source: "x" }; }

test("allowedSlots: fixed mode returns n", () => {
  const r = allowedSlots(clearSample(), { mode: "fixed", n: 3 }, { clearSince: null }, 1000);
  assert.deepEqual(r, { allowed: 3, max: 3, reason: "slots 3/3 (fixed)", state: { clearSince: null } });
});

test("allowedSlots: dynamic null sample -> min, clearSince null", () => {
  const r = allowedSlots(null, { mode: "dynamic", min: 2, max: 6 }, { clearSince: 5000 }, 1000);
  assert.equal(r.allowed, 2);
  assert.equal(r.max, 6);
  assert.equal(r.reason, "slots 2/6 (no load sample: /proc)");
  assert.equal(r.state.clearSince, null);
});

test("allowedSlots: each threshold alone failing -> min", () => {
  const cfg = { mode: "dynamic", min: 2, max: 6 };
  assert.equal(allowedSlots(busyCpu(), cfg, { clearSince: null }, 1000).allowed, 2);
  assert.equal(allowedSlots(busyLoad(), cfg, { clearSince: null }, 1000).allowed, 2);
  assert.equal(allowedSlots(busyMem(), cfg, { clearSince: null }, 1000).allowed, 2);
  assert.equal(allowedSlots(busyCpu(), cfg, { clearSince: null }, 1000).state.clearSince, null);
});

test("allowedSlots: dynamic clear -> max after 60 s; cold start clear -> min until 60 s", () => {
  const cfg = { mode: "dynamic", min: 2, max: 6 };
  let state = { clearSince: null };
  let r = allowedSlots(clearSample(), cfg, state, 1000); state = r.state; // cold start
  assert.equal(r.allowed, 2, "cold clear start gives min");
  r = allowedSlots(clearSample(), cfg, state, 1000 + 59000); state = r.state;
  assert.equal(r.allowed, 2, "59 s still min");
  r = allowedSlots(clearSample(), cfg, state, 1000 + 61000); state = r.state;
  assert.equal(r.allowed, 6, "61 s gives max");
});

test("allowedSlots: hysteresis - not-clear then clear for 59 s -> min, 61 s -> max; not-clear resets clearSince", () => {
  const cfg = { mode: "dynamic", min: 2, max: 6 };
  let state = { clearSince: null };
  let r = allowedSlots(busyCpu(), cfg, state, 1000); state = r.state;
  assert.equal(r.allowed, 2);
  assert.equal(state.clearSince, null, "not-clear resets clearSince");
  r = allowedSlots(clearSample(), cfg, state, 2000); state = r.state;
  assert.equal(r.allowed, 2, "clear 0 s -> min");
  assert.equal(state.clearSince, 2000);
  r = allowedSlots(clearSample(), cfg, state, 2000 + 59000); state = r.state;
  assert.equal(r.allowed, 2, "clear 59 s -> min");
  r = allowedSlots(clearSample(), cfg, state, 2000 + 61000); state = r.state;
  assert.equal(r.allowed, 6, "clear 61 s -> max");
  // back to busy resets
  r = allowedSlots(busyLoad(), cfg, state, 300000); state = r.state;
  assert.equal(r.allowed, 2);
  assert.equal(state.clearSince, null);
});

test("allowedSlots: reason text format", () => {
  const r = allowedSlots(clearSample(), { mode: "dynamic", min: 2, max: 6 }, { clearSince: null }, 1000);
  assert.equal(r.reason, "slots 2/6 (cpu wait 5%, load 1, 13 GiB free)");
  const r2 = allowedSlots(null, { mode: "dynamic", min: 2, max: 6 }, { clearSince: null }, 1000);
  assert.equal(r2.reason, "slots 2/6 (no load sample: /proc)");
});

// ---------------------------------------------------------------- acquireSlot with injection

test("acquireSlot: never exceeds allowed; allowed drop does not remove a live slot", async () => {
  process.env.ORCH_HOME = tmp();
  const dir = slotDir();
  // allowed = 3: claims slot-1 only (never slot 4)
  const release = await acquireSlot({ mode: "fixed", n: 3 }, { pollMs: 10, sample: null });
  assert.ok(fs.existsSync(path.join(dir, "slot-1")), "claimed a slot within allowed");
  assert.ok(!fs.existsSync(path.join(dir, "slot-4")), "never exceeds allowed");
  release();
  fs.rmSync(dir, { recursive: true, force: true });
  delete process.env.ORCH_HOME;
});

test("acquireSlot: allowed drop does not remove a live slot", async () => {
  process.env.ORCH_HOME = tmp();
  const dir = slotDir();
  const release = await acquireSlot({ mode: "fixed", n: 3 }, { pollMs: 10, sample: null });
  // lower the cap: the live slot is NOT removed
  const r = allowedSlots(null, { mode: "dynamic", min: 1, max: 1 }, { clearSince: null }, 1000);
  assert.equal(r.allowed, 1);
  assert.ok(fs.existsSync(path.join(dir, "slot-1")), "live slot remains after allowed drop");
  release();
  delete process.env.ORCH_HOME;
});

test("acquireSlot: dynamic cold start gives min; floor slots held blocks above-floor", async () => {
  process.env.ORCH_HOME = tmp();
  const dir = slotDir();
  fs.mkdirSync(dir, { recursive: true });
  const T = 100000;
  // floor slots held with OLD timestamps (owners alive so they are not reclaimed)
  const me = process.pid;
  fs.mkdirSync(path.join(dir, "slot-1"), { recursive: true });
  fs.writeFileSync(path.join(dir, "slot-1", "owner"), JSON.stringify({ pid: me, since: new Date(T - 120000).toISOString() }));
  fs.mkdirSync(path.join(dir, "slot-2"), { recursive: true });
  fs.writeFileSync(path.join(dir, "slot-2", "owner"), JSON.stringify({ pid: me, since: new Date(T - 120000).toISOString() }));

  const cfg = { mode: "dynamic", min: 2, max: 6 };
  const clear = () => clearSample();
  // Dynamic cold start gives min=2; both floor slots held -> nothing free -> deadline in the past throws immediately.
  await assert.rejects(
    acquireSlot(cfg, { pollMs: 10, sample: clear, now: T, deadline: T - 1 }),
    /no free worker slot \(slots/,
  );
  // No above-floor slot was attempted/created because cold start caps at min=2.
  assert.ok(!fs.existsSync(path.join(dir, "slot-3")), "no slot above the floor created");
  delete process.env.ORCH_HOME;
});

test("acquireSlot: floor slots claimed without the burst guard; above-floor slot never created at cold start", async () => {
  process.env.ORCH_HOME = tmp();
  const dir = slotDir();
  fs.mkdirSync(dir, { recursive: true });
  const T = 100000;
  const cfg = { mode: "dynamic", min: 2, max: 6 };
  const clear = () => clearSample();
  // No slots held: cold start gives min=2, slot-1 claimed (floor, no guard needed).
  const releaseA = await acquireSlot(cfg, { pollMs: 10, sample: clear, now: T, deadline: T + 5000 });
  assert.ok(fs.existsSync(path.join(dir, "slot-1")), "slot-1 claimed (floor, no guard)");
  assert.ok(!fs.existsSync(path.join(dir, "slot-3")), "no above-floor slot at cold start");
  // slot-2 still free: a second waiter at the same instant claims it (floor, no guard).
  const releaseB = await acquireSlot(cfg, { pollMs: 10, sample: clear, now: T, deadline: T + 5000 });
  assert.ok(fs.existsSync(path.join(dir, "slot-2")), "slot-2 claimed (floor, no guard)");
  // Both floor slots held now; a third waiter at the same instant blocks -> deadline throws.
  await assert.rejects(
    acquireSlot(cfg, { pollMs: 10, sample: clear, now: T, deadline: T - 1 }),
    /no free worker slot \(slots/,
  );
  releaseA();
  releaseB();
  delete process.env.ORCH_HOME;
});

function heldFloor(dir, me, T, sinceMs = 10000) {
  // slot-1 and slot-2 held by a live pid, claimed `sinceMs` milliseconds before T.
  for (const n of [1, 2]) {
    fs.mkdirSync(path.join(dir, `slot-${n}`), { recursive: true });
    fs.writeFileSync(path.join(dir, `slot-${n}`, "owner"), JSON.stringify({ pid: me, since: new Date(T - sinceMs).toISOString() }));
  }
}
function dynamicCfg() { return { mode: "dynamic", min: 2, max: 6 }; }
function clear() { return clearSample(); }

test("acquireSlot: burst guard refuses an above-floor slot when a floor slot was claimed within 60 s", async () => {
  process.env.ORCH_HOME = tmp();
  process.env.ORCH_PROC_ROOT = tmp();
  const dir = slotDir();
  fs.mkdirSync(dir, { recursive: true });
  const T = 100000;
  const me = process.pid;
  heldFloor(dir, me, T); // since = T - 10 s, inside the 60 s burst window
  const cfg = dynamicCfg();
  // allowed = 6 (clearSince long past), but every slot above the floor is blocked by the burst guard.
  await assert.rejects(
    acquireSlot(cfg, { pollMs: 10, sample: clear(), now: T, state: { clearSince: T - 120000 }, deadline: T - 1 }),
    /no free worker slot/,
  );
  assert.ok(!fs.existsSync(path.join(dir, "slot-3")), "no above-floor slot admitted");
  delete process.env.ORCH_HOME;
  delete process.env.ORCH_PROC_ROOT;
});

test("acquireSlot: burst guard admits slot-3 when floor slots are older than 60 s", async () => {
  process.env.ORCH_HOME = tmp();
  process.env.ORCH_PROC_ROOT = tmp();
  const dir = slotDir();
  fs.mkdirSync(dir, { recursive: true });
  const T = 100000;
  const me = process.pid;
  heldFloor(dir, me, T); // since = T - 10 s... override to 120 s below
  // re-write with old since (outside the burst window)
  for (const n of [1, 2]) {
    fs.writeFileSync(path.join(dir, `slot-${n}`, "owner"), JSON.stringify({ pid: me, since: new Date(T - 120000).toISOString() }));
  }
  const cfg = dynamicCfg();
  const release = await acquireSlot(cfg, { pollMs: 10, sample: clear(), now: T, state: { clearSince: T - 120000 }, deadline: T + 5000 });
  assert.ok(fs.existsSync(path.join(dir, "slot-3")), "slot-3 admitted above the floor");
  release();
  delete process.env.ORCH_HOME;
  delete process.env.ORCH_PROC_ROOT;
});

test("acquireSlot: two concurrent acquires admit exactly one above-floor slot", async () => {
  process.env.ORCH_HOME = tmp();
  process.env.ORCH_PROC_ROOT = tmp();
  const dir = slotDir();
  fs.mkdirSync(dir, { recursive: true });
  const T = 100000;
  const me = process.pid;
  heldFloor(dir, me, T);
  for (const n of [1, 2]) {
    fs.writeFileSync(path.join(dir, `slot-${n}`, "owner"), JSON.stringify({ pid: me, since: new Date(T - 120000).toISOString() }));
  }
  const cfg = dynamicCfg();
  const deadline = T - 1; // injected now (T) is past the deadline: each call throws after one poll
  const [r1, r2] = await Promise.allSettled([
    acquireSlot(cfg, { pollMs: 10, sample: clear(), now: T, state: { clearSince: T - 120000 }, deadline }),
    acquireSlot(cfg, { pollMs: 10, sample: clear(), now: T, state: { clearSince: T - 120000 }, deadline }),
  ]);
  const fulfilled = [r1, r2].filter((s) => s.status === "fulfilled");
  assert.equal(fulfilled.length, 1, `exactly one above-floor admission, got ${fulfilled.length}`);
  assert.ok(fs.existsSync(path.join(dir, "slot-3")), "slot-3 admitted by the winner");
  fulfilled[0].value(); // release the winner's slot
  const rejected = [r1, r2].filter((s) => s.status === "rejected");
  assert.equal(rejected.length, 1, "the other acquire was refused");
  delete process.env.ORCH_HOME;
  delete process.env.ORCH_PROC_ROOT;
});

test("acquireSlot: an admit.lock older than 30 s is stale and removed", async () => {
  process.env.ORCH_HOME = tmp();
  process.env.ORCH_PROC_ROOT = tmp();
  const dir = slotDir();
  fs.mkdirSync(dir, { recursive: true });
  const T = 100000;
  const me = process.pid;
  heldFloor(dir, me, T, 120000); // floor slots old: burst guard passes, only the lock is in question
  for (const n of [1, 2]) {
    fs.writeFileSync(path.join(dir, `slot-${n}`, "owner"), JSON.stringify({ pid: me, since: new Date(T - 120000).toISOString() }));
  }
  // a stale admit.lock (40 s old, real clock) must not block admission
  const lock = path.join(dir, "admit.lock");
  fs.mkdirSync(lock, { recursive: true });
  fs.utimesSync(lock, T - 40000, T - 40000);
  const cfg = dynamicCfg();
  const release = await acquireSlot(cfg, { pollMs: 10, sample: clear(), now: T, state: { clearSince: T - 120000 }, deadline: T + 5000 });
  assert.ok(fs.existsSync(path.join(dir, "slot-3")), "stale lock did not block slot-3");
  assert.ok(!fs.existsSync(lock), "stale admit.lock was removed");
  release();
  delete process.env.ORCH_HOME;
  delete process.env.ORCH_PROC_ROOT;
});

// ---------------------------------------------------------------- decision log

test("decision log: written on admission and allowed change only; rotates past maxLines", () => {
  const home = tmp();
  const old = process.env.ORCH_HOME;
  process.env.ORCH_HOME = home;
  try {
    const logFile = path.join(home, ".config", "orchestrator", "slot-decisions.log");
    // admission writes a line
    decisionLog({ allowed: 2, held: 0, sample: null, reason: "slots 2/6 (no load sample: /proc)" }, { maxLines: 5000, env: { ORCH_HOME: home } });
    assert.ok(fs.existsSync(logFile));
    let lines = fs.readFileSync(logFile, "utf8").trim().split("\n").filter(Boolean);
    assert.equal(lines.length, 1);
    const first = JSON.parse(lines[0]);
    assert.equal(first.allowed, 2);
    assert.equal(first.pid, process.pid);
    // change of allowed writes another line
    decisionLog({ allowed: 6, held: 0, sample: null, reason: "slots 6/6 (cpu wait 5%, load 1, 13 GiB free)" }, { maxLines: 5000, env: { ORCH_HOME: home } });
    lines = fs.readFileSync(logFile, "utf8").trim().split("\n").filter(Boolean);
    assert.equal(lines.length, 2);
    // rotation: small maxLines triggers rename to .1
    for (let i = 0; i < 4; i++) decisionLog({ allowed: 2, held: 0, sample: null, reason: "x" }, { maxLines: 2, env: { ORCH_HOME: home } });
    assert.ok(fs.existsSync(logFile + ".1"), "rotated to .1");
    const cur = fs.readFileSync(logFile, "utf8").trim().split("\n").filter(Boolean);
    assert.ok(cur.length <= 2, "current log trimmed after rotation");
  } finally {
    if (old === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = old;
  }
});

// ---------------------------------------------------------------- oc-worker CLI exits 2 on invalid WORKER_SLOTS

test("oc-worker: invalid WORKER_SLOTS exits 2 (usage error)", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", path.join(dir, "out", "f.md")], {
    env: { ...process.env, OPENCODE_BIN: path.join(HERE, "fixtures", "fake-opencode.mjs"), ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, WORKER_SLOTS: "abc" },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, /invalid WORKER_SLOTS/);
});

// ---- Nvidia adaptive cap: pure math, injected `now`, no sleeps ----------------------------------------------
const C = 600000;
test("nvidiaCap: no 429 on record -> NVIDIA_SLOTS_MAX (default 3; bad values fall back to 3)", () => {
  assert.equal(nvidiaCap({ env: {}, now: 1e9, state: null }).cap, 3);
  assert.equal(nvidiaCap({ env: { NVIDIA_SLOTS_MAX: "5" }, now: 1e9, state: null }).cap, 5);
  for (const bad of ["0", "-2", "x", "1.5", ""]) assert.equal(nvidiaCap({ env: { NVIDIA_SLOTS_MAX: bad }, now: 1e9, state: null }).cap, 3, bad);
});

test("nvidiaCap: a 429 gives 1, then steps up one per quiet cooldown and never past the max", () => {
  const t = 1e12;
  const cap = (since, env = {}) => nvidiaCap({ env, now: t + since, state: { last429: t } }).cap;
  assert.equal(cap(0), 1);
  assert.equal(cap(C - 1), 1);
  assert.equal(cap(C), 2);
  assert.equal(cap(2 * C - 1), 2);
  assert.equal(cap(2 * C), 3);
  assert.equal(cap(50 * C), 3, "never more than the max");
  assert.equal(cap(5 * C, { NVIDIA_SLOTS_MAX: "4" }), 4);
  assert.equal(cap(1500, { NVIDIA_COOLDOWN_MS: "1000" }), 2, "cooldown is configurable");
});

test("nvidiaCap: a fixed NVIDIA_SLOTS overrides the adaptive cap in both directions", () => {
  const t = 1e12;
  assert.equal(nvidiaCap({ env: { NVIDIA_SLOTS: "1" }, now: t + 99 * C, state: { last429: t - 99 * C } }).cap, 1, "fixed 1 below the adaptive max, long after a 429");
  assert.equal(nvidiaCap({ env: { NVIDIA_SLOTS: "5" }, now: t, state: { last429: t } }).cap, 5, "fixed 5 above the adaptive cap, right after a 429");
  assert.equal(nvidiaCap({ env: { NVIDIA_SLOTS: "2", NVIDIA_SLOTS_MAX: "9" }, now: t, state: null }).fixed, true);
  assert.equal(nvidiaCap({ env: { NVIDIA_SLOTS: "abc" }, now: t, state: null }).fixed, false, "not a positive integer: adaptive");
});

test("nvidia state file: atomic write, read back, cap change logged once per change", () => {
  const home = tmp();
  const env = { ORCH_HOME: home };
  const dir = path.join(home, ".config", "orchestrator", "slots");
  assert.equal(readNvidiaState(dir), null);
  assert.equal(nvidiaCapNow(dir, { env, now: 1e12 }).cap, 3);
  recordNvidia429(dir, 1e12);
  assert.deepEqual(readNvidiaState(dir), { last429: 1e12 });
  assert.ok(!fs.readdirSync(dir).some((n) => n.endsWith(".tmp")), "no tmp file left behind");
  assert.equal(nvidiaCapNow(dir, { env, now: 1e12 + 10 }).cap, 1);
  assert.equal(nvidiaCapNow(dir, { env, now: 1e12 + 20 }).cap, 1);
  assert.equal(nvidiaCapNow(dir, { env, now: 1e12 + C }).cap, 2);
  const log = fs.readFileSync(path.join(home, ".config", "orchestrator", "slot-decisions.log"), "utf8").trim().split("\n").map((l) => JSON.parse(l)).filter((e) => e.provider === "nvidia");
  assert.deepEqual(log.map((e) => [e.prev, e.cap]), [[null, 3], [3, 1], [1, 2]], "one line per cap change");
  assert.match(log[1].reason, /^nvidia cap 3 -> 1 \(429 at /);
});

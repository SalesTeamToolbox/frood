import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { activeRuns, fmtDur, registerRun, runsDir } from "../bin/oc-worker.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ocw-active-"));
  CLEAN.push(h);
  return h;
}

const NOW = Date.now();
const iso = (ms) => new Date(ms).toISOString();
function inHome(h, fn) {
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    return fn();
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
}

test("registerRun keeps a touch() override (grace-extended timeoutMin) across later heartbeats", () => {
  const h = home();
  const read = () => {
    const d = path.join(h, ".config", "orchestrator", "runs");
    return JSON.parse(fs.readFileSync(path.join(d, fs.readdirSync(d)[0]), "utf8"));
  };
  inHome(h, () => {
    const r = registerRun({ agent: "worker", model: "m", title: "t", dir: h, out: path.join(h, "o.md"), started: NOW, idleMin: 5, timeoutMin: 9 });
    r.touch({ timeoutMin: 24 });
    assert.equal(read().timeoutMin, 24);
    r.touch(); // the 20 s heartbeat
    assert.equal(read().timeoutMin, 24, "a plain heartbeat must not revert the extended deadline");
    r.end();
  });
});

test("fmtDur renders compact durations", () => {
  assert.equal(fmtDur(45_000), "45s");
  assert.equal(fmtDur(26 * 60_000), "26m");
  assert.equal(fmtDur((3 * 60 + 12) * 60_000), "3h12m");
  assert.equal(fmtDur((2 * 24 + 5) * 3600_000), "2d5h");
  assert.equal(fmtDur(NaN), "?");
});

test("registerRun records watchdog limits for active to read", () => {
  const h = home();
  const before = inHome(h, () =>
    registerRun({ agent: "worker", model: "m", title: "t", dir: h, out: path.join(h, "o.md"), started: NOW, idleMin: 5, timeoutMin: 9 }));
  assert.ok(before && typeof before.end === "function");
  const files = fs.readdirSync(path.join(h, ".config", "orchestrator", "runs"));
  assert.equal(files.length, 1);
  const rec = JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "runs", files[0]), "utf8"));
  assert.equal(rec.pid, process.pid);
  assert.equal(rec.idleMin, 5);
  assert.equal(rec.timeoutMin, 9);
  assert.ok(rec.heartbeat);
  before.end();
  assert.deepEqual(fs.readdirSync(path.join(h, ".config", "orchestrator", "runs")), []);
});

function baseRec(over = {}) {
  return {
    pid: process.pid, agent: "worker", model: "opencode-go/mimo-v2.6-flash",
    title: "w title", dir: "/tmp", out: "", started: NOW - 26 * 60_000,
    idleMin: 20, timeoutMin: 30, heartbeat: iso(NOW), ...over,
  };
}

function mkOut(homeDir, name, ageMs, now = NOW) {
  const runDir = path.join(homeDir, "reports");
  fs.mkdirSync(runDir, { recursive: true });
  const out = path.join(runDir, `${name}.md`);
  if (ageMs == null) return out; // never written: STARTING
  fs.writeFileSync(out, "partial\n");
  fs.writeFileSync(out + ".events.jsonl", '{"type":"text"}\n');
  const t = new Date(now - ageMs);
  fs.utimesSync(out + ".events.jsonl", t, t);
  fs.utimesSync(out, t, t);
  return out;
}

test("activeRuns states: RUNNING, QUIET, STALE, OVERDUE, HEARTBEAT-STALE, STARTING", () => {
  const h = home();
  const recs = {
    running: baseRec({ out: mkOut(h, "r1", 3 * 60_000) }),
    quiet: baseRec({ out: mkOut(h, "r2", 25 * 60_000), title: "quiet one", started: NOW - 25 * 60_000 }),
    stale: baseRec({ pid: 2 ** 30, out: mkOut(h, "r3", 60 * 60_000), title: "dead wrapper" }),
    overdue: baseRec({ out: mkOut(h, "r4", 3 * 60_000), started: NOW - 40 * 60_000, timeoutMin: 30, title: "overdue run" }),
    heartbeat: baseRec({ out: mkOut(h, "r5", 60_000), heartbeat: iso(NOW - 5 * 60_000), title: "stuck loop", started: NOW - 24 * 60_000 }),
    starting: baseRec({ out: mkOut(h, "r6", null), started: NOW - 30_000, title: "just spawned", heartbeat: iso(NOW) }),
    noidle: baseRec({ out: mkOut(h, "r7", 90 * 60_000), idleMin: 0, title: "idle checks off", started: NOW - 23 * 60_000 }),
    legacy: baseRec({ out: mkOut(h, "r8", 3 * 60_000), title: "old entry", started: NOW - 22 * 60_000 }),
  };
  delete recs.legacy.idleMin;
  delete recs.legacy.timeoutMin;
  for (const r of Object.values(recs)) {
    const dir = path.join(h, ".config", "orchestrator", "runs");
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, `${r.pid}-${r.started}.json`), JSON.stringify(r));
  }
  const rows = inHome(h, () => activeRuns(NOW));
  const by = Object.fromEntries(rows.map((r) => [r.title, r]));
  assert.equal(by["w title"].state, "RUNNING");
  assert.equal(by["quiet one"].state, "QUIET");
  assert.match(by["quiet one"].detail, /silent 25m past idle-min 20m/);
  assert.equal(by["dead wrapper"].state, "STALE");
  assert.equal(by["overdue run"].state, "OVERDUE");
  assert.equal(by["stuck loop"].state, "HEARTBEAT-STALE");
  assert.equal(by["just spawned"].state, "STARTING");
  assert.equal(by["idle checks off"].state, "RUNNING", "idle-min 0 disables the QUIET trip");
  assert.equal(by["old entry"].state, "RUNNING");
  assert.match(by["old entry"].outAge ?? "", /\d+[smh]/);
  assert.equal(by["w title"].elapsed, "26m");
});

test("active CLI prints text rows and --json", () => {
  const h = home();
  // The CLI reads the live clock, so anchor this test to a fresh now (not the module's NOW, which can be
  // minutes old by the time this runs) and sit mid-minute so floor-to-minute output cannot flip.
  const now = Date.now();
  const started = now - 26 * 60_000 - 30_000;
  const out = mkOut(h, "cli1", 3 * 60_000 + 30_000, now);
  const dir = path.join(h, ".config", "orchestrator", "runs");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(
    path.join(dir, `${process.pid}-${started}.json`),
    JSON.stringify(baseRec({ out, title: "cli run", started, heartbeat: iso(now) })),
  );
  const env = { ...process.env, ORCH_HOME: h };
  const text = spawnSync(process.execPath, [BIN, "active"], { env, encoding: "utf8" });
  assert.equal(text.status, 0, text.stderr);
  assert.match(text.stdout, /^RUNNING worker cli run \| elapsed 26m \| out 3m \| idle-min 20m timeout-min 30m \| pid \d+$/m);
  const js = spawnSync(process.execPath, [BIN, "active", "--json"], { env, encoding: "utf8" });
  assert.equal(js.status, 0, js.stderr);
  const rows = JSON.parse(js.stdout);
  assert.equal(rows.length, 1);
  assert.equal(rows[0].state, "RUNNING");
  assert.equal(rows[0].stream ?? null, null);
  const empty = spawnSync(process.execPath, [BIN, "active"], { env: { ...process.env, ORCH_HOME: tmpEmpty() }, encoding: "utf8" });
  assert.match(empty.stdout, /no registered runs/);
  function tmpEmpty() {
    const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ocw-empty-"));
    CLEAN.push(d);
    return d;
  }
});

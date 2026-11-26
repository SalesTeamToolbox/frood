// cc-pacing M6: `desk status` shows the Claude Code pace. Text mode prints `pace: <statusLine>` first (omitted when
// the state is off); --json carries a top-level `pace` key (absent when off); a failed pace read shows as UNKNOWN and
// status still exits 0. Hermetic: ORCH_HOME is a temp dir, cwd is that dir (no real board), every child has a timeout.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { statusLine } from "../bin/cc-pace.mjs";
import { installFixtureGuard } from "./fixtures/fixture-guard.mjs";

installFixtureGuard();

const HERE = path.dirname(fileURLToPath(import.meta.url));
const DESK = path.join(HERE, "..", "bin", "desk.mjs");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});
const tmp = () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-desk-pace-"));
  CLEAN.push(d);
  return d;
};

const H = 3600 * 1000;
const iso = (ms) => new Date(ms).toISOString();
// An `under` snapshot (same shape as pace-routing.test.mjs): 10% used with 100 h left in the week.
function underHome(h = tmp()) {
  const now = Date.now();
  const snap = { at: iso(now - 10 * 60 * 1000), source: "app", five_hour: { pct: 0, resets_at: iso(now + 3 * H) }, weekly: { pct: 10, resets_at: iso(now + 100 * H) }, fable: null };
  const d = path.join(h, ".config", "orchestrator");
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, "cc-usage.json"), JSON.stringify(snap) + "\n");
  fs.writeFileSync(path.join(d, "cc-usage.jsonl"), JSON.stringify(snap) + "\n");
  return h;
}

function desk(h, args, extra = {}) {
  const env = { ...process.env, ORCH_HOME: h, WORKER_SLOTS: "3", ...extra };
  for (const k of ["ORCH_NO_PACE", "ORCH_PACE_BIN"]) if (!(k in extra)) delete env[k];
  const r = spawnSync(process.execPath, [DESK, ...args], { cwd: h, env, encoding: "utf8", timeout: 60000 });
  return { ...r, lines: String(r.stdout).split("\n").filter(Boolean) };
}

// A pace bin that prints a fixed `status --json` object.
const FIXED = { state: "over", weekly: 62.4, projected: 118.2, reserve: 5, five_hour: 71, fable: { pct: 33 }, weekly_resets_at: "2026-11-30T12:00:00.000Z", at: "2026-11-26T10:00:00.000Z" };
function fixedBin(h) {
  const p = path.join(h, "fixed-pace.mjs");
  fs.writeFileSync(p, `console.log(${JSON.stringify(JSON.stringify(FIXED))});\n`);
  return p;
}

test("status: first line is `pace: <statusLine>` from a fixed pace bin; --json has the pace object", () => {
  const h = tmp();
  const bin = fixedBin(h);
  const r = desk(h, ["status"], { ORCH_PACE_BIN: bin });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.lines[0], `pace: ${statusLine(FIXED)}`);
  assert.match(r.lines[0], /^pace: OVER wk 62%→118% @\w{3}\d{2} rsv 5% 5h 71% fable 33%$/);
  assert.match(r.lines[1], /^watch none/, "the watch line follows the pace line");
  assert.match(r.lines[2], /^slots \d+\/\d+ \(fixed\)$/);
  assert.ok(r.lines[0].length <= 106, "statusLine is cut at 100 chars");
  const j = JSON.parse(desk(h, ["status", "--json"], { ORCH_PACE_BIN: bin }).stdout);
  assert.deepEqual(j.pace, FIXED);
  assert.deepEqual(j.streams, []);
  assert.equal(j.watch, null);
  assert.ok(j.slots, "the rest of the JSON shape is unchanged");
});

test("status: real cc-pace over snapshots in ORCH_HOME prints the UNDER line", () => {
  const h = underHome();
  const r = desk(h, ["status"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.lines[0], /^pace: UNDER wk 10%→/);
  assert.match(r.lines[0], / fable n\/a$/);
  assert.equal(JSON.parse(desk(h, ["status", "--json"]).stdout).pace.state, "under");
});

test("status: ORCH_NO_PACE=1 (state off) omits the line and the JSON key", () => {
  const h = underHome();
  const r = desk(h, ["status"], { ORCH_NO_PACE: "1" });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.lines[0], /^watch none/);
  assert.ok(!r.lines.some((l) => l.startsWith("pace:")), "no pace line when off");
  const j = JSON.parse(desk(h, ["status", "--json"], { ORCH_NO_PACE: "1" }).stdout);
  assert.equal("pace" in j, false);
  assert.deepEqual(Object.keys(j).sort(), ["slots", "streams", "watch"]);
});

test("status: a failed pace read prints `pace: UNKNOWN …` and still exits 0", () => {
  const h = tmp();
  const missing = path.join(h, "missing", "cc-pace.mjs");
  const r = desk(h, ["status"], { ORCH_PACE_BIN: missing });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.lines[0], "pace: UNKNOWN (pace read failed: missing cc-pace.mjs)");
  assert.match(r.lines[1], /^watch none/);
  const j = desk(h, ["status", "--json"], { ORCH_PACE_BIN: missing });
  assert.equal(j.status, 0);
  assert.deepEqual(JSON.parse(j.stdout).pace, { state: "unknown", reason: "pace read failed: missing cc-pace.mjs" });
  // a bin that exits non-zero is the same: UNKNOWN, exit 0
  const bad = path.join(h, "bad-pace.mjs");
  fs.writeFileSync(bad, "process.exit(3);\n");
  const b = desk(h, ["status"], { ORCH_PACE_BIN: bad });
  assert.equal(b.status, 0);
  assert.equal(b.lines[0], "pace: UNKNOWN (pace read failed: exit 3)");
});

test("status: no snapshot at all reads `unknown` and prints the line", () => {
  const h = tmp();
  const r = desk(h, ["status"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.lines[0], /^pace: UNKNOWN \(/);
});

// cc-pace: the pure pace model (table test) and the status CLI. Hermetic: ORCH_HOME=<tmp>, TZ=UTC.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { reserve, projected, paceState, statusLine, DEFAULTS } from "../bin/cc-pace.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "cc-pace.mjs");
const HOUR = 3600 * 1000;
const NOW = Date.parse("2026-01-07T19:30:00.000Z");
const iso = (t) => new Date(t).toISOString();

/** A snapshot `ageH` hours before `now`, weekly reset `H` hours after `now`. */
function snap({ now = NOW, ageH = 0, weekly = 42, H = 20.5, five = 40, fiveResetH = 2, fable = 13, resets } = {}) {
  return {
    at: iso(now - ageH * HOUR),
    source: "app",
    five_hour: five == null ? null : { pct: five, resets_at: iso(now + fiveResetH * HOUR) },
    weekly: { pct: weekly, resets_at: resets ?? iso(now + H * HOUR) },
    fable: fable == null ? null : { pct: fable, resets_at: iso(now + H * HOUR) },
  };
}
const pace = (snaps, prev = null, cfg = DEFAULTS, now = NOW) => paceState(snaps, cfg, now, prev);

test("reserve: 20 at week start, 10 at H=90, 0 in the last 12 h", () => {
  assert.equal(reserve(168, DEFAULTS), 20);
  assert.equal(reserve(90, DEFAULTS), 10);
  assert.equal(reserve(12, DEFAULTS), 0);
  assert.equal(reserve(5, DEFAULTS), 0);
  assert.equal(reserve(0, DEFAULTS), 0);
  assert.ok(Math.abs(reserve(100, DEFAULTS) - 11.28) < 0.01);
  assert.equal(projected(42, 1, 10, 5), 57);
});

test("worked example: weekly 42, H 20.5, 5h 40, one snapshot -> under, projected 52.8", () => {
  const r = pace([snap()]);
  assert.equal(r.state, "under");
  assert.ok(Math.abs(r.projected - 52.8) <= 0.1, String(r.projected));
  assert.equal(r.weekly, 42);
  assert.equal(r.five_hour, 40);
  assert.ok(Math.abs(r.hours_to_reset - 20.5) < 1e-9);
  assert.ok(Math.abs(r.reserve - 20 * 8.5 / 156) < 1e-9);
  assert.deepEqual(r.fable, { pct: 13, state: "ok" });
  assert.equal(r.at, iso(NOW));
  for (const k of ["state", "reason", "weekly", "projected", "reserve", "rate", "hours_to_reset", "five_hour", "fable", "at"]) assert.ok(k in r, k);
});

test("table: over / on / unknown rows, first match wins", () => {
  const rows = [
    ["5h 90 with projected ~50 -> over", [snap({ weekly: 40, five: 90 })], "over"],
    ["weekly 90 at H=100 -> over (ceiling ~88.7)", [snap({ weekly: 90, H: 100, five: 0 })], "over"],
    ["projected >= 95 -> over", [snap({ weekly: 80, H: 20.5, five: 0 })], "over"],
    ["E=6 -> on", [snap({ weekly: 0, H: 162, five: 0 })], "on"],
    ["snapshot 3 h old -> unknown", [snap({ ageH: 3 })], "unknown"],
    ["no snapshot -> unknown", [], "unknown"],
    ["weekly reset past -> unknown", [snap({ H: -1 })], "unknown"],
    ["weekly reset missing -> unknown", [{ ...snap(), weekly: { pct: 42, resets_at: null } }], "unknown"],
    ["no weekly window -> unknown", [{ ...snap(), weekly: null }], "unknown"],
    ["5h 70 blocks under -> on", [snap({ five: 70 })], "on"],
  ];
  for (const [name, snaps, want] of rows) assert.equal(pace(snaps).state, want, name);
  assert.equal(pace([snap({ ageH: 3 })]).reason, "stale 3h");
  assert.equal(pace([]).reason, "no snapshot");
});

test("off when cfg.enabled is false, even with no snapshot", () => {
  assert.equal(pace([snap()], null, { ...DEFAULTS, enabled: false }).state, "off");
  assert.equal(pace([], null, { enabled: false }).state, "off");
});

test("hysteresis: prev under holds to 85; prev null leaves under above 80", () => {
  // H = E = 84, single snapshot: projected = 2 * weekly + 5.
  const at82 = [snap({ weekly: 38.5, H: 84, five: 10 })];
  const at86 = [snap({ weekly: 40.5, H: 84, five: 10 })];
  assert.ok(Math.abs(pace(at82).projected - 82) < 1e-9);
  assert.equal(pace(at82, "under").state, "under");
  assert.equal(pace(at82, { state: "under" }).state, "under");
  assert.equal(pace(at86, "under").state, "on");
  assert.equal(pace(at82, null).state, "on");
  assert.equal(pace(at82, "on").state, "on");
});

test("five_hour: past resets_at reads 0; null reads 0", () => {
  const r = pace([snap({ five: 90, fiveResetH: -0.5 })]);
  assert.equal(r.five_hour, 0);
  assert.equal(r.state, "under");
  assert.equal(pace([snap({ five: null })]).five_hour, 0);
});

test("fable: over at >= 85, null when absent, never changes the main state", () => {
  const r = pace([snap({ fable: 90 })]);
  assert.deepEqual(r.fable, { pct: 90, state: "over" });
  assert.equal(r.state, "under");
  assert.equal(pace([snap({ fable: null })]).fable, null);
});

test("recent slope beats avg when steeper; ignored when span < 4 h or the window differs", () => {
  const cur = snap({ weekly: 42 });
  const avg = pace([cur]).rate;
  // 6 h span, +12 points: 2 %/h, steeper than avg 0.285.
  const steep = pace([snap({ ageH: 6, weekly: 30 }), cur]);
  assert.ok(Math.abs(steep.rate - 2) < 1e-9);
  assert.ok(Math.abs(steep.projected - (42 + 2 * 20.5 + 5)) < 1e-9);
  assert.equal(steep.state, "on");
  // A shallow recent slope does not lower the rate below avg.
  assert.equal(pace([snap({ ageH: 6, weekly: 41.9 }), cur]).rate, avg);
  // Span < 4 h: ignored.
  assert.equal(pace([snap({ ageH: 3, weekly: 30 }), cur]).rate, avg);
  // Different weekly window: ignored.
  assert.equal(pace([snap({ ageH: 6, weekly: 30, H: 20.5 - 168 + 6 }), cur]).rate, avg);
  // Older than 24 h: ignored.
  assert.equal(pace([snap({ ageH: 30, weekly: 10 }), cur]).rate, avg);
});

test("statusLine: shape and <= 100 chars for every state", () => {
  // In-process (shared with other test files): don't touch TZ; derive the local weekday/hour the same way.
  // The CLI tests pin TZ=UTC and check the UTC rendering.
  const r = pace([snap()]);
  const d = new Date(r.weekly_resets_at);
  const at = `@${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][d.getDay()]}${String(d.getHours()).padStart(2, "0")}`;
  assert.equal(statusLine(r), `UNDER wk 42%→53% ${at} rsv 1% 5h 40% fable 13%`);
  assert.equal(statusLine(pace([snap({ fable: null })])), `UNDER wk 42%→53% ${at} rsv 1% 5h 40% fable n/a`);
  assert.equal(statusLine(pace([])), "UNKNOWN (no snapshot)");
  assert.equal(statusLine(pace([snap({ ageH: 3 })])), "UNKNOWN (stale 3h)");
  assert.equal(statusLine(pace([], null, { enabled: false })), "OFF");
  for (const r2 of [pace([snap({ weekly: 99.999, five: 100, fable: 100, H: 1 })]), pace([snap({ H: -1 })]), pace([{ ...snap(), weekly: null }])]) {
    const s = statusLine(r2);
    assert.ok(s.length <= 100 && !s.includes("\n") && !/^pace/i.test(s), s);
  }
});

// ---------------------------------------------------------------- CLI
function sandbox() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "ccp-"));
  const dir = path.join(home, ".config", "orchestrator");
  fs.mkdirSync(dir, { recursive: true });
  const run = (args = [], env = {}) => {
    const e = { ...process.env, ORCH_HOME: home, TZ: "UTC", ...env };
    delete e.ORCH_NO_PACE;
    Object.assign(e, env);
    return spawnSync(process.execPath, [BIN, ...args], { env: e, encoding: "utf8", timeout: 20000 });
  };
  const put = (rec) => fs.writeFileSync(path.join(dir, "cc-usage.json"), JSON.stringify(rec));
  const statePath = path.join(dir, "cc-pace-state.json");
  return { home, dir, run, put, statePath };
}
const lines = (out) => out.split("\n").filter(Boolean);

test("CLI: no snapshot -> one UNKNOWN line, exit 0, state persisted", () => {
  const s = sandbox();
  const r = s.run();
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(lines(r.stdout), ["UNKNOWN (no snapshot)"]);
  assert.equal(JSON.parse(fs.readFileSync(s.statePath, "utf8")).state, "unknown");
});

test("CLI: status / --json for a live snapshot; state file round-trips", () => {
  const s = sandbox();
  const now = Date.now();
  s.put(snap({ now }));
  const reset = new Date(now + 20.5 * HOUR);
  const at = `@${["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"][reset.getUTCDay()]}${String(reset.getUTCHours()).padStart(2, "0")}`;
  const r = s.run(["status"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(lines(r.stdout).length, 1);
  assert.equal(r.stdout, `UNDER wk 42%→53% ${at} rsv 1% 5h 40% fable 13%\n`);
  assert.ok(lines(r.stdout)[0].length <= 100);
  assert.equal(JSON.parse(fs.readFileSync(s.statePath, "utf8")).state, "under");
  const j = s.run(["status", "--json"]);
  assert.equal(j.status, 0, j.stderr);
  assert.equal(lines(j.stdout).length, 1);
  const o = JSON.parse(j.stdout);
  assert.equal(o.state, "under");
  for (const k of ["weekly", "projected", "at"]) assert.ok(k in o, k);
  assert.deepEqual(JSON.parse(s.run(["--json"]).stdout).state, "under");
});

test("CLI: hysteresis reads the persisted state", () => {
  const s = sandbox();
  s.put(snap({ now: Date.now(), weekly: 38.5, H: 84, five: 10 })); // projected ~82
  fs.writeFileSync(s.statePath, JSON.stringify({ state: "under" }));
  assert.match(s.run().stdout, /^UNDER /);
  fs.rmSync(s.statePath);
  assert.match(s.run().stdout, /^ON /);
  assert.equal(JSON.parse(fs.readFileSync(s.statePath, "utf8")).state, "on");
});

test("CLI: a corrupt state file is ignored and replaced", () => {
  const s = sandbox();
  s.put(snap({ now: Date.now() }));
  fs.writeFileSync(s.statePath, "{not json");
  const r = s.run();
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /^UNDER /);
  assert.equal(JSON.parse(fs.readFileSync(s.statePath, "utf8")).state, "under");
});

test("CLI: stale snapshot, ORCH_NO_PACE=1 and cc.enabled false; corrupt usage-limits uses defaults", () => {
  const s = sandbox();
  s.put(snap({ now: Date.now(), ageH: 3.2 }));
  assert.deepEqual(lines(s.run().stdout), ["UNKNOWN (stale 3h)"]);
  s.put(snap({ now: Date.now() }));
  const off = s.run([], { ORCH_NO_PACE: "1" });
  assert.equal(off.status, 0);
  assert.deepEqual(lines(off.stdout), ["OFF"]);
  fs.writeFileSync(path.join(s.dir, "usage-limits.json"), JSON.stringify({ cc: { enabled: false } }));
  assert.deepEqual(lines(s.run().stdout), ["OFF"]);
  fs.writeFileSync(path.join(s.dir, "usage-limits.json"), "garbage");
  assert.match(s.run().stdout, /^UNDER /);
  fs.writeFileSync(path.join(s.dir, "usage-limits.json"), JSON.stringify({ cc: { margin: 50 } }));
  assert.match(s.run().stdout, /^OVER /);
});

test("CLI: history snapshots feed the recent slope", () => {
  const s = sandbox();
  const now = Date.now();
  const hist = [snap({ now, ageH: 6, weekly: 30 }), snap({ now, weekly: 42 })];
  fs.writeFileSync(path.join(s.dir, "cc-usage.jsonl"), hist.map((h) => JSON.stringify(h)).join("\n") + "\n");
  s.put(hist[1]);
  const o = JSON.parse(s.run(["--json"]).stdout);
  assert.ok(Math.abs(o.rate - 2) < 0.01, String(o.rate));
});

test("CLI: unknown command or flag exits 2 with usage on stderr", () => {
  const s = sandbox();
  for (const args of [["bogus"], ["--verbose"], ["status", "extra"]]) {
    const r = s.run(args);
    assert.equal(r.status, 2, args.join(" "));
    assert.match(r.stderr, /usage/);
    assert.equal(r.stdout, "");
  }
});

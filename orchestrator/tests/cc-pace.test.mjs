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

test("reserve rule alone: weekly >= 100 - reserve is over even when projected < 95", () => {
  // margin -200 pins projected far below 95, so only the reserve ceiling (100 - 11.28 = 88.72 at H=100) can fire.
  const cfg = { ...DEFAULTS, margin: -200 };
  const hit = pace([snap({ weekly: 90, H: 100, five: 10 })], null, cfg);
  assert.ok(hit.projected < 95, String(hit.projected));
  assert.equal(hit.state, "over");
  assert.match(hit.reason, /weekly 90% >= 88\.7 \(100 - reserve\)/);
  // Just under the ceiling, projected < 95, five_hour < 85: not over.
  const miss = pace([snap({ weekly: 88.5, H: 100, five: 10 })], null, cfg);
  assert.ok(miss.projected < 95 && 88.5 < 100 - miss.reserve);
  assert.notEqual(miss.state, "over");
  // A raised reserve moves the ceiling: 60 % reserve at H=100 -> ceiling ~66.2.
  const raised = pace([snap({ weekly: 70, H: 100, five: 10 })], null, { ...cfg, weekly_reserve_pct: 60 });
  assert.equal(raised.state, "over");
  assert.match(raised.reason, /100 - reserve/);
});

test("early week (E < 12): projected alone is not over; 5h and reserve rules still are", () => {
  // E = 2 h, weekly 3 -> avg 1.5 %/h, projected >> 95: cold start wins over the projection.
  const steep = pace([snap({ weekly: 3, H: 166, five: 0 })]);
  assert.ok(steep.projected >= 95, String(steep.projected));
  assert.equal(steep.state, "on");
  assert.match(steep.reason, /^early week/);
  // E = 2 h with five_hour 90: the 5-hour rule stays ahead of cold start.
  const five = pace([snap({ weekly: 3, H: 166, five: 90 })]);
  assert.equal(five.state, "over");
  assert.match(five.reason, /^5h 90% >= 85/);
  // E = 2 h with weekly above the reserve ceiling (~80.3 at H=166): the reserve rule stays ahead of cold start.
  const rsv = pace([snap({ weekly: 85, H: 166, five: 0 })]);
  assert.ok(85 >= 100 - rsv.reserve, String(rsv.reserve));
  assert.equal(rsv.state, "over");
  assert.match(rsv.reason, /100 - reserve/);
  // E = 13 h, weekly 20 -> projected >> 95: past the cold-start window the projection rules again.
  const later = pace([snap({ weekly: 20, H: 155, five: 0 })]);
  assert.ok(later.projected >= 95 && 20 < 100 - later.reserve, String(later.projected));
  assert.equal(later.state, "over");
  assert.match(later.reason, /^projected/);
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

// ---------------------------------------------------------------- ledger shadow (cc-pacing-v2 A2)
import { ledgerShadow, withDefaults, main as paceMain } from "../bin/cc-pace.mjs";
import { DEFAULT_WEIGHTS } from "../bin/cc-ledger.mjs";

const MIN = 60 * 1000;
/** 10-minute opus buckets of {in: 1000} (w = 1000 each at opus weight 1) with start in [from, to). */
function ledgerBuckets(from, to) {
  const b = {};
  for (let t = from; t < to; t += 10 * MIN) b[new Date(t).toISOString().slice(0, 15) + "0Z"] = { opus: { in: 1000, out: 0, cc: 0, cr: 0, w: 1000 } };
  return b;
}
/** Snapshots 0.6 points per hour (k = 0.6 / 6000 = 1e-4 against ledgerBuckets); newest 1 h before `now`. */
function ledgerSnaps(now = NOW) {
  return [[12, 30], [9, 31.8], [6, 33.6], [3, 35.4], [1, 36.6]].map(([ageH, weekly]) => snap({ now, ageH, weekly, H: 20.5, resets: iso(now + 20.5 * HOUR) }));
}
const ledgerOf = (now = NOW, { scannedAgoMin = 1, to = now } = {}) => ({ v: 1, scanned_at: iso(now - scannedAgoMin * MIN), files: {}, ids: {}, buckets: ledgerBuckets(now - 24 * HOUR, to) });
const near = (a, b, eps = 1e-9) => assert.ok(Math.abs(a - b) < eps, `${a} vs ${b}`);

test("ledger: DEFAULTS.ledger is frozen shadow with cc-ledger weights; withDefaults keeps mode shadow and overlays fresh_minutes", () => {
  assert.ok(Object.isFrozen(DEFAULTS.ledger));
  assert.deepEqual(DEFAULTS.ledger, { weights: DEFAULT_WEIGHTS, fresh_minutes: 30, mode: "shadow" });
  const c = withDefaults({ ledger: { mode: "on", fresh_minutes: 45, weights: { opus: 3, haiku: "junk" } } });
  assert.equal(c.ledger.mode, "shadow");
  assert.equal(c.ledger.fresh_minutes, 45);
  assert.equal(c.ledger.weights.opus, 3);
  assert.equal(c.ledger.weights.haiku, DEFAULT_WEIGHTS.haiku);
  assert.equal(withDefaults({ ledger: { fresh_minutes: "x" } }).ledger.fresh_minutes, 30);
  const once = withDefaults({ ledger: { fresh_minutes: 45 } });
  assert.deepEqual(withDefaults(once).ledger, once.ledger, "idempotent on an already-defaulted config");
});

test("ledger: null without a ledger, with k null, with scanned_at older than fresh_minutes, or without a usable weekly/at", () => {
  const snaps = ledgerSnaps();
  const r = pace(snaps);
  assert.equal(ledgerShadow(r, null, snaps, DEFAULTS, NOW), null);
  assert.equal(ledgerShadow(r, { v: 1, scanned_at: null, files: {}, ids: {}, buckets: {} }, snaps, DEFAULTS, NOW), null);
  assert.equal(ledgerShadow(r, ledgerOf(), snaps.slice(-2), DEFAULTS, NOW), null, "one pair: k null");
  assert.equal(ledgerShadow(r, ledgerOf(NOW, { scannedAgoMin: 31 }), snaps, DEFAULTS, NOW), null, "31 min old");
  assert.notEqual(ledgerShadow(r, ledgerOf(NOW, { scannedAgoMin: 31 }), snaps, { ledger: { fresh_minutes: 60 } }, NOW), null, "fresh_minutes overlays");
  assert.equal(ledgerShadow({ ...r, weekly: null }, ledgerOf(), snaps, DEFAULTS, NOW), null);
  assert.equal(ledgerShadow({ ...r, at: "nope" }, ledgerOf(), snaps, DEFAULTS, NOW), null);
  assert.equal(ledgerShadow(pace([], null), ledgerOf(), snaps, DEFAULTS, NOW), null, "unknown state");
});

test("ledger: nowcast_weekly = weekly + k·w(since at); ledger_rate = k·w(24 h)/24", () => {
  const snaps = ledgerSnaps();
  const r = pace(snaps);
  assert.equal(r.weekly, 36.6);
  const l = ledgerShadow(r, ledgerOf(), snaps, DEFAULTS, NOW);
  assert.deepEqual(Object.keys(l).sort(), ["k", "ledger_rate", "nowcast_weekly", "pairs", "rms", "scanned_at", "unmetered"]);
  near(l.k, 1e-4, 1e-12);
  assert.equal(l.pairs, 4);
  near(l.rms, 0, 1e-9);
  assert.equal(l.scanned_at, iso(NOW - MIN));
  near(l.nowcast_weekly, 36.6 + l.k * 6000); // six buckets since r.at (NOW - 1 h)
  assert.ok(l.nowcast_weekly > r.weekly);
  near(l.ledger_rate, (l.k * 144000) / 24); // 144 buckets in the last 24 h
  near(l.ledger_rate, 0.6, 1e-9);
});

test("ledger: nowcast never below weekly (w = 0 since the snapshot -> exactly weekly)", () => {
  const snaps = ledgerSnaps();
  const r = pace(snaps);
  const l = ledgerShadow(r, ledgerOf(NOW, { to: NOW - HOUR }), snaps, DEFAULTS, NOW);
  assert.notEqual(l, null);
  assert.equal(l.nowcast_weekly, r.weekly);
  near(l.ledger_rate, (l.k * 138000) / 24);
});

// In-process status runs at a fixed clock, so outputs with and without a ledger compare byte for byte.
function runStatus(home, args, now) {
  const saved = { home: process.env.ORCH_HOME, nopace: process.env.ORCH_NO_PACE, now: Date.now, log: console.log };
  const out = [];
  process.env.ORCH_HOME = home;
  delete process.env.ORCH_NO_PACE;
  Date.now = () => now;
  console.log = (s) => out.push(String(s) + "\n");
  try {
    const code = paceMain(args);
    return { code, stdout: out.join("") };
  } finally {
    Date.now = saved.now;
    console.log = saved.log;
    if (saved.home === undefined) delete process.env.ORCH_HOME; else process.env.ORCH_HOME = saved.home;
    if (saved.nopace !== undefined) process.env.ORCH_NO_PACE = saved.nopace;
  }
}
const FIXTURES = {
  "no snapshot": () => ({ snaps: [] }),
  under: (now) => ({ snaps: [snap({ now })] }),
  "ledger history": (now) => ({ snaps: ledgerSnaps(now) }),
  on: (now) => ({ snaps: [snap({ now, weekly: 38.5, H: 84, five: 10 })] }),
  over: (now) => ({ snaps: [snap({ now, five: 90 })] }),
  stale: (now) => ({ snaps: [snap({ now, ageH: 3.2 })] }),
  off: (now) => ({ snaps: [snap({ now })], limits: { cc: { enabled: false } } }),
};
function fixtureHome(name, now, withLedger) {
  const s = sandbox();
  const { snaps, limits } = FIXTURES[name](now);
  if (snaps.length) {
    fs.writeFileSync(path.join(s.dir, "cc-usage.jsonl"), snaps.map((x) => JSON.stringify(x)).join("\n") + "\n");
    s.put(snaps[snaps.length - 1]);
  }
  if (limits) fs.writeFileSync(path.join(s.dir, "usage-limits.json"), JSON.stringify(limits));
  const ledgerFile = path.join(s.dir, "cc-ledger.json");
  if (withLedger) fs.writeFileSync(ledgerFile, JSON.stringify(ledgerOf(now)));
  return { ...s, ledgerFile };
}
const stateBytes = (s) => (fs.existsSync(s.statePath) ? fs.readFileSync(s.statePath, "utf8") : null);

test("status: text byte-identical, pre-existing --json keys and state file identical with and without a ledger; line = text", () => {
  const now = NOW;
  for (const name of Object.keys(FIXTURES)) {
    const a = fixtureHome(name, now, false);
    const b = fixtureHome(name, now, true);
    const ta = runStatus(a.home, ["status"], now);
    const tb = runStatus(b.home, ["status"], now);
    assert.equal(ta.code, 0, name);
    assert.equal(tb.stdout, ta.stdout, `${name}: text`);
    assert.equal(stateBytes(b), stateBytes(a), `${name}: state file`);
    const ja = JSON.parse(runStatus(a.home, ["status", "--json"], now).stdout);
    const jb = JSON.parse(runStatus(b.home, ["status", "--json"], now).stdout);
    assert.equal(ja.line + "\n", ta.stdout, `${name}: line equals the text output`);
    assert.equal(jb.line, ja.line);
    assert.equal(ja.ledger, null, `${name}: no ledger file`);
    const strip = ({ ledger, line, ...rest }) => rest;
    assert.deepEqual(strip(jb), strip(ja), `${name}: pre-existing keys`);
    assert.deepEqual(strip(jb), JSON.parse(JSON.stringify(paceState(FIXTURES[name](now).snaps, withDefaults(FIXTURES[name](now).limits?.cc), now, JSON.parse(stateBytes(a))))), `${name}: the state`);
    assert.equal(stateBytes(b), stateBytes(a), `${name}: state file after --json`);
    if (name === "ledger history") {
      assert.notEqual(jb.ledger, null);
      near(jb.ledger.nowcast_weekly, jb.weekly + jb.ledger.k * 6000);
    }
  }
});

test("status: a stale or k-null ledger gives ledger null; status never writes cc-ledger.json", () => {
  const now = NOW;
  const none = fixtureHome("ledger history", now, false);
  runStatus(none.home, ["status", "--json"], now);
  runStatus(none.home, ["status"], now);
  assert.equal(fs.existsSync(none.ledgerFile), false, "status never scans or creates the ledger");
  const stale = fixtureHome("ledger history", now, false);
  fs.writeFileSync(stale.ledgerFile, JSON.stringify(ledgerOf(now, { scannedAgoMin: 31 })));
  const old = new Date(now - 2 * HOUR);
  fs.utimesSync(stale.ledgerFile, old, old);
  const before = fs.readFileSync(stale.ledgerFile, "utf8");
  assert.equal(JSON.parse(runStatus(stale.home, ["status", "--json"], now).stdout).ledger, null);
  assert.equal(fs.statSync(stale.ledgerFile).mtimeMs, old.getTime(), "ledger mtime unchanged");
  assert.equal(fs.readFileSync(stale.ledgerFile, "utf8"), before);
  const kNull = fixtureHome("under", now, true); // one snapshot: no pairs
  assert.equal(JSON.parse(runStatus(kNull.home, ["status", "--json"], now).stdout).ledger, null);
  const corrupt = fixtureHome("ledger history", now, false);
  fs.writeFileSync(corrupt.ledgerFile, "{garbage");
  const j = runStatus(corrupt.home, ["status", "--json"], now);
  assert.equal(j.code, 0);
  assert.equal(JSON.parse(j.stdout).ledger, null);
});

test("CLI: status --json (child process) carries line and ledger", () => {
  const s = sandbox();
  const now = Date.now();
  s.put(snap({ now }));
  const t = s.run(["status"]);
  const o = JSON.parse(s.run(["status", "--json"]).stdout);
  assert.equal(o.line + "\n", t.stdout);
  assert.equal(o.ledger, null);
});

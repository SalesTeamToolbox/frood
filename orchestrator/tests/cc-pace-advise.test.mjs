// cc-pace reset advisor (cc-pacing M5): the pure adviseState table, effectiveDeadline, the 24 h notify memory,
// the board count, the advise / reset-used CLI and the desk-check tick. Hermetic: ORCH_HOME=<tmp>, TZ=UTC,
// ORCH_NO_NOTIFY=1; synthetic data only.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { adviseState, effectiveDeadline, dueNotifications, adviseTick, activeTickets, laTime } from "../bin/cc-pace.mjs";
import { shouldNotify } from "../bin/session-pressure.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "cc-pace.mjs");
const DESK_CHECK = path.join(HERE, "..", "bin", "desk-check.mjs");
const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;
const iso = (t) => new Date(t).toISOString();
const CLEAN = [];
after(() => { for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 }); });

// Weekly resets on Thursdays 16:00Z; the statusline sidecar adds ms jitter.
const W = Date.parse("2026-12-10T16:00:00.000Z");
const FULL_EXP = "2026-12-10T22:00:00Z";

/** A snapshot at `at`, weekly reset at `resets` (default W with jitter). */
function snap({ at, weekly = 42, resets = W + 274, five = 40, fiveResetH = 1, fable = 13 } = {}) {
  return {
    at: iso(at),
    source: "statusline",
    five_hour: five == null ? null : { pct: five, resets_at: iso(at + fiveResetH * HOUR) },
    weekly: weekly == null ? null : { pct: weekly, resets_at: iso(resets) },
    fable: fable == null ? null : { pct: fable, resets_at: iso(resets) },
  };
}
const ids = (r) => r.advice.map((a) => a.id);

test("effectiveDeadline: full expiry 6 h after a Thursday reset -> that reset; far expiry -> itself; no window -> expiry", () => {
  assert.equal(effectiveDeadline(Date.parse(FULL_EXP), W), W);
  assert.equal(effectiveDeadline(Date.parse(FULL_EXP), W + 274), W); // minute rounding
  assert.equal(effectiveDeadline(Date.parse(FULL_EXP), W - 3 * 7 * DAY), W); // any multiple of 168 h
  assert.equal(effectiveDeadline(Date.parse(FULL_EXP), W + 7 * DAY), W);
  const fableExp = Date.parse("2027-03-09T07:59:00Z"); // Tue: > 24 h after Thu Mar 4 16:00Z
  assert.equal(effectiveDeadline(fableExp, W), fableExp);
  assert.equal(effectiveDeadline(fableExp, NaN), fableExp);
  assert.equal(laTime(W), "Thu Dec 10 08:00 PST");
});

test("expiry stages: 15 d none, 13 d 14d, 60 h 72h, 20 h 24h, count 0 none, past expires_at none", () => {
  const now = Date.parse("2026-11-26T12:00:00Z");
  const at = (left, count = 1) => adviseState({ snapshots: [], resets: [{ kind: "fable", count, expires_at: iso(now + left) }], now });
  assert.deepEqual(ids(at(15 * DAY)), []);
  assert.deepEqual(ids(at(13 * DAY)), ["expiry-fable-14d"]);
  assert.deepEqual(ids(at(60 * HOUR)), ["expiry-fable-72h"]);
  assert.deepEqual(ids(at(20 * HOUR)), ["expiry-fable-24h"]);
  assert.deepEqual(ids(at(20 * HOUR, 0)), []);
  assert.deepEqual(ids(at(-HOUR)), []);
  assert.equal(at(13 * DAY).advice[0].level, "warn");
  assert.equal(at(60 * HOUR).advice[0].level, "warn");
  assert.equal(at(20 * HOUR).advice[0].level, "critical");
  for (const left of [13 * DAY, 60 * HOUR, 20 * HOUR]) {
    const a = at(left, 2).advice[0];
    assert.ok(a.text.length <= 100, a.text);
    assert.match(a.text, /^[A-Z][a-z]+ /);
    assert.match(a.text, /2 fable resets/);
    assert.equal(a.kind, "fable");
  }
  // Junk entries and a missing block give no advice and no error.
  assert.deepEqual(ids(adviseState({ snapshots: [], resets: undefined, now })), []);
  assert.deepEqual(ids(adviseState({ snapshots: [], resets: [null, { kind: "x", count: 1, expires_at: iso(now + DAY) }, { kind: "full", count: "1", expires_at: iso(now + DAY) }, { kind: "full", count: 1, expires_at: "bad" }], now })), []);
});

test("expiry measured against the effective deadline, and the late stage between deadline and expiry", () => {
  const resets = [{ kind: "full", count: 1, expires_at: FULL_EXP }];
  // 20 h before the weekly reset (26 h before expiry): the 24h stage already, because the deadline is W.
  const pre = adviseState({ snapshots: [snap({ at: W - 20 * HOUR - 3 * HOUR, weekly: 10 })], resets, now: W - 20 * HOUR });
  assert.deepEqual(ids(pre), ["expiry-full-24h"]);
  assert.match(pre.advice[0].text, /Thu Dec 10 08:00 PST/);
  // Past W, before the expiry: late, even with a stale snapshot.
  const late = adviseState({ snapshots: [snap({ at: W - 50 * HOUR })], resets, now: W + 2 * HOUR });
  assert.deepEqual(ids(late), ["expiry-full-late"]);
  assert.equal(late.advice[0].level, "critical");
  assert.match(late.advice[0].text, /expires Thu Dec 10 14:00 PST; pressing now gives back little/);
  assert.ok(late.advice[0].text.length <= 100);
});

test("press-full (a): weekly >= 90 with >= 36 h to the weekly reset", () => {
  const resets = [{ kind: "full", count: 1, expires_at: "2027-06-01T00:00:00Z" }];
  const now = W - 40 * HOUR;
  const a = adviseState({ snapshots: [snap({ at: now - 10 * 60000, weekly: 91 })], resets, now });
  assert.deepEqual(ids(a), ["press-full"]);
  assert.equal(a.advice[0].level, "critical");
  assert.match(a.advice[0].text, /^Press the full reset now: weekly 91%/);
  const now30 = W - 30 * HOUR;
  assert.deepEqual(ids(adviseState({ snapshots: [snap({ at: now30, weekly: 91 })], resets, now: now30 })), []);
  // Stale (3 h) snapshot: no press advice.
  assert.deepEqual(ids(adviseState({ snapshots: [snap({ at: now - 3 * HOUR, weekly: 91 })], resets, now })), []);
  // No full entry: no press advice.
  assert.deepEqual(ids(adviseState({ snapshots: [snap({ at: now, weekly: 91 })], resets: [], now })), []);
});

test("press-full (b): within 24 h of the deadline at >= 50%", () => {
  const resets = [{ kind: "full", count: 1, expires_at: FULL_EXP }];
  const now = W - 20 * HOUR;
  const hit = adviseState({ snapshots: [snap({ at: now, weekly: 55 })], resets, now });
  assert.deepEqual(ids(hit), ["expiry-full-24h", "press-full"]);
  const p = hit.advice[1];
  assert.equal(p.text, "Press the full reset now: weekly 55%, best before Thu Dec 10 08:00 PST");
  assert.deepEqual(ids(adviseState({ snapshots: [snap({ at: now, weekly: 45 })], resets, now })), ["expiry-full-24h"]);
});

test("press-fable: needs an active ticket; fable >= 85 or 5h >= 90 with > 2 h left", () => {
  const resets = [{ kind: "fable", count: 2, expires_at: "2027-03-09T07:59:00Z" }];
  const now = W - 50 * HOUR;
  const s = (o) => [snap({ at: now, ...o })];
  const run = (o, n = 1) => ids(adviseState({ snapshots: s(o), resets, now, activeTickets: n }));
  assert.deepEqual(run({ fable: 87 }), ["press-fable"]);
  assert.deepEqual(run({ fable: 87 }, 0), []);
  assert.deepEqual(run({ fable: 80, five: 92, fiveResetH: 3 }), ["press-fable"]);
  assert.deepEqual(run({ fable: 80, five: 92, fiveResetH: 1.5 }), []);
  assert.deepEqual(run({ fable: null, five: null }), []);
  const a = adviseState({ snapshots: s({ fable: 87 }), resets, now, activeTickets: 3 }).advice[0];
  assert.equal(a.level, "warn");
  assert.match(a.text, /^Press a fable reset now: fable 87%, 3 tickets active$/);
});

test("reset detection: a 25-point drop in one window pauses press-full and asks; across windows nothing; an ack clears it", () => {
  const resets = [{ kind: "full", count: 1, expires_at: FULL_EXP }];
  const now = W - 20 * HOUR;
  const snaps = [
    snap({ at: now - 5 * HOUR, weekly: 80 }),
    snap({ at: now - 3 * HOUR, weekly: 55 }),
    snap({ at: now, weekly: 56 }),
  ];
  const r = adviseState({ snapshots: snaps, resets, now });
  assert.equal(r.paused, true);
  assert.deepEqual(r.drop, { from: 80, to: 55, at: iso(now - 3 * HOUR) });
  assert.deepEqual(ids(r), ["expiry-full-24h", "ask-reset-drop"]);
  const ask = r.advice.find((a) => a.id === "ask-reset-drop");
  assert.equal(ask.level, "warn");
  assert.equal(ask.text, "Weekly fell 80%→55%: if you pressed a reset, run cc-pace reset-used full|fable");

  // Same drop, acknowledged after it: press-full is back, no question.
  const acked = adviseState({ snapshots: snaps, resets, now, acks: [{ kind: "full", at: iso(now - HOUR) }] });
  assert.equal(acked.paused, false);
  assert.deepEqual(ids(acked), ["expiry-full-24h", "press-full"]);
  // An ack older than the drop does not count.
  assert.equal(adviseState({ snapshots: snaps, resets, now, acks: [{ kind: "full", at: iso(now - 4 * HOUR) }] }).paused, true);

  // The same fall across two different weekly windows is the weekly reset itself, not a press.
  const across = [
    snap({ at: W - 7 * DAY - HOUR, weekly: 80, resets: W - 7 * DAY + 123 }),
    snap({ at: now, weekly: 55 }),
  ];
  const x = adviseState({ snapshots: across, resets, now });
  assert.equal(x.paused, false);
  assert.equal(x.drop, null);
  assert.deepEqual(ids(x), ["expiry-full-24h", "press-full"]);
  // A 20-point fall is not a drop.
  assert.equal(adviseState({ snapshots: [snap({ at: now - HOUR, weekly: 75 }), snap({ at: now, weekly: 55 })], resets, now }).drop, null);
});

test("shouldNotify: the optional interval defaults to the 60 min of session-pressure", () => {
  assert.equal(shouldNotify({ lastLevel: "warn", lastNotifyMs: 0 }, 61 * 60000, "warn").notify, true);
  assert.equal(shouldNotify({ lastLevel: "warn", lastNotifyMs: 0 }, 61 * 60000, "warn", DAY).notify, false);
});

test("dueNotifications: once per 24 h per id; again after 24 h; warn -> critical under the same id at once", () => {
  const t0 = Date.parse("2026-12-01T12:00:00Z");
  const warn = [{ id: "x", kind: "full", level: "warn", text: "Do x" }];
  const crit = [{ id: "x", kind: "full", level: "critical", text: "Do x" }];
  assert.equal(dueNotifications(warn, {}, t0).length, 1);
  const st = { x: { lastLevel: "warn", lastNotifyMs: t0 } };
  assert.equal(dueNotifications(warn, st, t0 + 23 * HOUR).length, 0);
  assert.equal(dueNotifications(warn, st, t0 + DAY).length, 1);
  assert.equal(dueNotifications(crit, st, t0 + HOUR).length, 1);
  assert.equal(dueNotifications(warn, { acks: [] }, t0).length, 1);
  assert.equal(dueNotifications(warn, null, t0).length, 1);
});

function sandbox() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "ccadv-"));
  CLEAN.push(home);
  const dir = path.join(home, ".config", "orchestrator");
  fs.mkdirSync(dir, { recursive: true });
  const env = (extra = {}) => {
    const e = { ...process.env, ORCH_HOME: home, TZ: "UTC", ORCH_NO_NOTIFY: "1", CC_SIDECAR: path.join(home, "no-sidecar.json"), SERVICE_JSON: path.join(home, "no-service.json"), ...extra };
    delete e.ORCH_NO_PACE;
    return e;
  };
  const run = (args = [], extra = {}) => spawnSync(process.execPath, [BIN, ...args], { env: env(extra), encoding: "utf8", timeout: 20000 });
  const limits = path.join(dir, "usage-limits.json");
  const state = path.join(dir, "cc-advise-state.json");
  return { home, dir, env, run, limits, state };
}
const lines = (out) => out.split("\n").filter(Boolean);

/** Run fn with ORCH_HOME (and ORCH_NO_NOTIFY) pointed at the sandbox, restoring the env after. */
function inHome(home, fn) {
  const saved = { ORCH_HOME: process.env.ORCH_HOME, ORCH_NO_NOTIFY: process.env.ORCH_NO_NOTIFY };
  process.env.ORCH_HOME = home;
  process.env.ORCH_NO_NOTIFY = "1";
  try { return fn(); } finally {
    for (const [k, v] of Object.entries(saved)) { if (v === undefined) delete process.env[k]; else process.env[k] = v; }
  }
}

test("adviseTick: notifies once a day per id, records every level, prints nothing, keeps acks", () => {
  const s = sandbox();
  const now = Date.now();
  fs.writeFileSync(s.limits, JSON.stringify({ cc: { resets: [{ kind: "fable", count: 1, expires_at: iso(now + 10 * DAY) }] } }));
  fs.writeFileSync(s.state, JSON.stringify({ acks: [{ kind: "full", at: iso(now - DAY) }] }));
  const sent = [];
  const deps = { activeTickets: () => 0, notify: (lvl, summary, body) => sent.push([lvl, body]) };
  const log = console.log;
  const printed = [];
  console.log = (...a) => printed.push(a);
  let r1, r2, r3;
  try {
    inHome(s.home, () => {
      r1 = adviseTick(now, deps);
      r2 = adviseTick(now + HOUR, deps);
      r3 = adviseTick(now + DAY + HOUR, deps);
    });
  } finally { console.log = log; }
  assert.deepEqual(printed, []);
  assert.deepEqual(ids(r1), ["expiry-fable-14d"]);
  assert.ok(r2 && r3);
  assert.equal(sent.length, 2);
  assert.equal(sent[0][0], "warn");
  const st = JSON.parse(fs.readFileSync(s.state, "utf8"));
  assert.deepEqual(st["expiry-fable-14d"], { lastLevel: "warn", lastNotifyMs: now + DAY + HOUR });
  assert.equal(st.acks.length, 1);
  // A corrupt state file is treated as {} and replaced; a throwing board count is 0.
  fs.writeFileSync(s.state, "{nope");
  const r4 = inHome(s.home, () => adviseTick(now, { activeTickets: () => { throw new Error("x"); }, notify: () => {} }));
  assert.deepEqual(ids(r4), ["expiry-fable-14d"]);
  assert.ok(JSON.parse(fs.readFileSync(s.state, "utf8"))["expiry-fable-14d"]);
});

test("activeTickets: queued + working across distinct stream repos; junk and missing boards count 0", () => {
  const s = sandbox();
  const streams = path.join(s.dir, "streams");
  fs.mkdirSync(streams, { recursive: true });
  const repo = path.join(s.home, "repo");
  const tdir = path.join(repo, ".opencode", "board", "tickets");
  fs.mkdirSync(tdir, { recursive: true });
  const put = (f, body) => fs.writeFileSync(path.join(tdir, f), body);
  put("a.json", JSON.stringify({ id: "a", stage: "queued" }));
  put("b.json", JSON.stringify({ id: "b", stage: "working" }));
  put("c.json", JSON.stringify({ id: "c", stage: "done" }));
  put("d.json", "{garbage");
  put("e.gate-1.log", "stage: working");
  const stream = (name, r) => fs.writeFileSync(path.join(streams, `${name}.json`), JSON.stringify({ name, repo: r, plan: "", status: "active", next: "n", written_at: new Date().toISOString() }));
  assert.equal(inHome(s.home, () => activeTickets()), 0);
  stream("one", repo);
  stream("two", repo);
  stream("three", path.join(s.home, "no-such-repo"));
  stream("four", "");
  assert.equal(inHome(s.home, () => activeTickets()), 2);
});

test("CLI advise: no config / no snapshot exits 0; --json; --notify writes state; unknown flag exits 2", () => {
  const s = sandbox();
  let r = s.run(["advise"]);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(lines(r.stdout), ["no reset advice"]);
  r = s.run(["advise", "--json"]);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout), { advice: [], paused: false, drop: null });
  assert.ok(!fs.existsSync(s.state), "advise without --notify writes nothing");
  r = s.run(["advise", "--bogus"]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /usage/);
  assert.equal(r.stdout, "");

  const now = Date.now();
  fs.writeFileSync(s.limits, JSON.stringify({ go_monthly_usd: 60, cc: { resets: [{ kind: "full", count: 1, expires_at: iso(now + 13 * DAY) }] } }));
  r = s.run(["advise"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(lines(r.stdout).length, 1);
  assert.match(r.stdout, /^You: Use the full reset before /);
  r = s.run(["advise", "--notify", "--json"]);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(JSON.parse(r.stdout).advice.map((a) => a.id), ["expiry-full-14d"]);
  assert.equal(JSON.parse(fs.readFileSync(s.state, "utf8"))["expiry-full-14d"].lastLevel, "warn");
  // Corrupt config: still exit 0.
  fs.writeFileSync(s.limits, "garbage");
  r = s.run(["advise"]);
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(lines(r.stdout), ["no reset advice"]);
});

test("CLI reset-used: full 1 -> 0 keeps other keys and acks; again exits 2 byte-identical; bad kind / missing file exit 2", () => {
  const s = sandbox();
  let r = s.run(["reset-used", "full"]);
  assert.equal(r.status, 2, "missing file");
  assert.ok(!fs.existsSync(s.limits));
  const cfg = { go_monthly_usd: 60, cc: { stale_hours: 2, resets: [{ kind: "full", count: 1, expires_at: FULL_EXP }, { kind: "fable", count: 2, expires_at: "2027-03-09T07:59:00Z" }] }, other: { a: [1, 2] } };
  fs.writeFileSync(s.limits, JSON.stringify(cfg));
  r = s.run(["reset-used", "full"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /0/);
  const after1 = JSON.parse(fs.readFileSync(s.limits, "utf8"));
  const want = structuredClone(cfg);
  want.cc.resets[0].count = 0;
  assert.deepEqual(after1, want);
  const acks = JSON.parse(fs.readFileSync(s.state, "utf8")).acks;
  assert.equal(acks.length, 1);
  assert.equal(acks[0].kind, "full");
  assert.ok(Math.abs(Date.parse(acks[0].at) - Date.now()) < 60000);

  const bytes = fs.readFileSync(s.limits);
  r = s.run(["reset-used", "full"]);
  assert.equal(r.status, 2);
  assert.ok(fs.readFileSync(s.limits).equals(bytes), "file unchanged at count 0");
  for (const bad of [["reset-used"], ["reset-used", "weekly"], ["reset-used", "full", "fable"]]) {
    r = s.run(bad);
    assert.equal(r.status, 2, bad.join(" "));
    assert.ok(fs.readFileSync(s.limits).equals(bytes));
  }
  // Kind missing from config.
  fs.writeFileSync(s.limits, JSON.stringify({ cc: { resets: [{ kind: "fable", count: 2, expires_at: "2027-03-09T07:59:00Z" }] } }));
  const b2 = fs.readFileSync(s.limits);
  assert.equal(s.run(["reset-used", "full"]).status, 2);
  assert.ok(fs.readFileSync(s.limits).equals(b2));
  // Unparsable file.
  fs.writeFileSync(s.limits, "{x");
  assert.equal(s.run(["reset-used", "fable"]).status, 2);
  assert.equal(fs.readFileSync(s.limits, "utf8"), "{x");
  // Fable 2 -> 1; acks keep the last 20.
  fs.writeFileSync(s.limits, JSON.stringify({ cc: { resets: [{ kind: "fable", count: 25, expires_at: "2027-03-09T07:59:00Z" }] } }));
  for (let i = 0; i < 21; i++) assert.equal(s.run(["reset-used", "fable"]).status, 0);
  assert.equal(JSON.parse(fs.readFileSync(s.limits, "utf8")).cc.resets[0].count, 4);
  assert.equal(JSON.parse(fs.readFileSync(s.state, "utf8")).acks.length, 20);
});

test("CLI status / no-arg output unchanged by the advisor", () => {
  const s = sandbox();
  fs.writeFileSync(s.limits, JSON.stringify({ cc: { resets: [{ kind: "full", count: 1, expires_at: iso(Date.now() + DAY) }] } }));
  for (const args of [[], ["status"]]) {
    const r = s.run(args);
    assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(lines(r.stdout), ["UNKNOWN (no snapshot)"]);
  }
  assert.ok(!fs.existsSync(s.state), "status never runs the advisor");
});

test("desk-check runs one silent advise tick: stdout and exit code unchanged", () => {
  const s = sandbox();
  fs.writeFileSync(s.limits, JSON.stringify({ cc: { resets: [{ kind: "full", count: 1, expires_at: iso(Date.now() + 20 * HOUR) }] } }));
  const r = spawnSync(process.execPath, [DESK_CHECK], { env: s.env(), encoding: "utf8", timeout: 30000 });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "");
  const st = JSON.parse(fs.readFileSync(s.state, "utf8"));
  assert.equal(st["expiry-full-24h"].lastLevel, "critical");
});

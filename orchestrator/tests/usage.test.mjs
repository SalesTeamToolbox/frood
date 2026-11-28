// Local usage ledger: spend math, windows, headroom — all from fixture DBs, fixed clock.
// Never touches the real opencode db (OPENCODE_DB override) or the network.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { collectUsage, isPeak, loadLimits, poolHeadroom, rollup, rowCost } from "../bin/usage.mjs";
import {
  GO_LEDGER_SQL, GO_MODEL_LIMITS, goCost, goLedger, goV2,
} from "../bin/usage.mjs";

import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const require = createRequire(import.meta.url);

const NOW = Date.UTC(2026, 10, 17, 12, 0, 0); // Tue 2026-11-17 12:00 UTC
const HOUR = 3600_000;

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orch-usage-"));
}

function makeDb(rows) {
  const file = path.join(tmp(), "opencode.db");
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    db.exec(`CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, model TEXT, cost REAL,
      time_created INTEGER, time_updated INTEGER, tokens_input INTEGER, tokens_output INTEGER,
      tokens_reasoning INTEGER, tokens_cache_read INTEGER, directory TEXT);`);
    const ins = db.prepare(`INSERT INTO session_v2
      (id, title, model, cost, time_created, time_updated, tokens_input, tokens_output, tokens_reasoning, tokens_cache_read, directory)
      VALUES (?,?,?,?,?,?,?,?,?,?,?)`);
    for (const [i, r] of rows.entries()) {
      ins.run(`s${i}`, r.title ?? `s${i}`, r.model, 0, r.ts, r.ts,
        r.ti ?? 0, r.to ?? 0, r.tr ?? 0, r.tc ?? 0, "/tmp/x");
    }
  } finally { db.close(); }
  return file;
}

const M = (provider, id) => JSON.stringify({ providerID: provider, id });

test("isPeak covers Mon–Fri 01–04 and 06–10 UTC only", () => {
  const mon0200 = Date.UTC(2026, 10, 16, 2, 30); // Monday
  const mon0500 = Date.UTC(2026, 10, 16, 5, 0);
  const sat0200 = Date.UTC(2026, 10, 21, 2, 30); // Saturday
  assert.equal(isPeak(mon0200), true);
  assert.equal(isPeak(Date.UTC(2026, 10, 16, 7, 0)), true);
  assert.equal(isPeak(mon0500), false);
  assert.equal(isPeak(sat0200), false);
});

test("rollup prices input+reasoning/output/cache, doubles DeepSeek at peak", () => {
  const rows = [
    // 10M in + 1M out + 4M cache-read on Go MiMo, off-peak Tuesday 10:00
    { provider: "opencode-go", id: "mimo-v2.6-flash", ts: NOW - 1 * HOUR, tokens: { input: 10e6, output: 1e6, cache_read: 4e6 } },
    // 1M in + 0.5M out on Go DeepSeek at Monday 02:30 UTC: input+output x2, cache unchanged
    { provider: "opencode-go", id: "deepseek-v4.1-flash", ts: Date.UTC(2026, 10, 16, 2, 30), tokens: { input: 1e6, output: 0.5e6, cache_read: 1e6 } },
  ];
  const priced = rows.map((r) => ({ ...r, cost: rowCost(r.provider, r.id, r.tokens, r.ts) }));
  const u = rollup(priced, NOW, { go_monthly_usd: 60 });
  // mimo: 10*.14 + 1*.28 + 4*.0028 = 1.4 + 0.28 + 0.0112 = 1.6912
  // deepseek peak: (1*.15 + .5*.60)*2 + 1*.003 = (0.15+0.30)*2 + 0.003 = 0.903
  const b = u.pools.go;
  assert.ok(Math.abs(b.spend_5h - 1.6912) < 1e-9, String(b.spend_5h));
  assert.ok(Math.abs(b.spend_7d - (1.6912 + 0.903)) < 1e-9, String(b.spend_7d));
  assert.equal(b.cap_5h, 12);
  assert.equal(Math.round(b.headroom_5h * 1000) / 1000, Math.round((1 - 1.6912 / 12) * 1000) / 1000);
});

test("rollup ignores free pools and counts unmetered rows", () => {
  const rows = [
    { provider: "nvidia", id: "x", ts: NOW - HOUR, tokens: { input: 1e9, output: 1e9 } },
    { provider: "opencode", id: "anything-free", ts: NOW - HOUR, tokens: { input: 1e9, output: 1e9 } },
    { provider: "opencode-go", id: "mystery-model", ts: NOW - HOUR, tokens: { input: 1e9, output: 1e9 } },
  ];
  const priced = rows.map((r) => ({ ...r, cost: rowCost(r.provider, r.id, r.tokens, r.ts) }));
  const u = rollup(priced, NOW, { go_monthly_usd: 60 });
  assert.equal(u.pools.go.spend_5h, 0);
  assert.equal(u.pools.cmdc.spend_5h, 0);
  assert.equal(u.pools.go.unmetered, 1, "unknown Go model counted, not priced");
});

test("rollup tracks CmdC per-model monthly caps", () => {
  const rows = [
    { provider: "commandcode", id: "claude-haiku-5-5", ts: NOW - 2 * HOUR, tokens: { input: 100e6, output: 10e6 } },
  ];
  const priced = rows.map((r) => ({ ...r, cost: rowCost(r.provider, r.id, r.tokens, r.ts) }));
  const u = rollup(priced, NOW, { go_monthly_usd: 60 });
  // 100*.10 + 10*.50 = 10 + 5 = $15 of the $20 monthly cap
  assert.equal(u.pools.cmdc.models["commandcode/claude-haiku-5-5"].cap_mtd, 20);
  assert.equal(u.pools.cmdc.models["commandcode/claude-haiku-5-5"].spend_mtd, 15);
  assert.equal(u.pools.cmdc.models["commandcode/claude-haiku-5-5"].headroom_mtd, 0.25);
});

test("poolHeadroom picks the tightest window; free/unknown are null", () => {
  const priced = [{ provider: "opencode-go", id: "mimo-v2.6-flash", ts: NOW - HOUR, tokens: { input: 50e6, output: 0 } }]
    .map((r) => ({ ...r, cost: rowCost(r.provider, r.id, r.tokens, r.ts) }));
  const u = rollup(priced, NOW, { go_monthly_usd: 60 });
  // $7 of $12 5h cap -> tightest is 5h at ~0.4167
  const h = poolHeadroom(u, "opencode-go", "mimo-v2.6-flash");
  assert.ok(Math.abs(h.headroom - (1 - 7 / 12)) < 1e-9, JSON.stringify(h));
  assert.match(h.label, /^5h /);
  assert.equal(poolHeadroom(u, "nvidia", "x"), null);
  assert.equal(poolHeadroom(u, "opencode", "y-free"), null);
  assert.equal(poolHeadroom(u, "unknown", "z"), null);
  assert.equal(poolHeadroom(null, "opencode-go", "mimo-v2.6-flash"), null);
});

test("collectUsage reads the session db end to end", () => {
  const file = makeDb([
    { model: M("opencode-go", "mimo-v2.6-flash"), ts: NOW - HOUR, ti: 10e6, to: 1e6, tc: 4e6 },
    { model: "commandcode/deepseek/deepseek-v4.1-flash", ts: NOW - 2 * HOUR, ti: 1e6, to: 0, tc: 0 },
    { model: M("nvidia", "nemotron-3.5-super"), ts: NOW - 3 * HOUR, ti: 5e6, to: 1e6 },
  ]);
  const u = collectUsage(file, NOW, { go_monthly_usd: 60 });
  assert.ok(u.pools, "pools present");
  assert.ok(u.pools.go.spend_5h > 1.6 && u.pools.go.spend_5h < 1.7, u.pools.go.spend_5h);
  // string "provider/id" form works too: 1*.15 = $0.15
  assert.equal(u.pools.cmdc.spend_5h, 0.15);
  assert.ok(Array.isArray(u.assumptions) && u.assumptions.length > 0);
});

test("collectUsage with no db reports unknown, never throws", () => {
  const u = collectUsage(path.join(tmp(), "missing.db"), NOW, { go_monthly_usd: 60 });
  assert.equal(u.pools, null);
  assert.match(u.assumptions[0], /unknown/);
});

test("loadLimits defaults and honours the config file", () => {
  const h = tmp();
  const OLD = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    assert.deepEqual(loadLimits(), { go_monthly_usd: 60, low_headroom_pct: 15, missing: true });
    fs.mkdirSync(path.join(h, ".config", "orchestrator"), { recursive: true });
    fs.writeFileSync(path.join(h, ".config", "orchestrator", "usage-limits.json"), JSON.stringify({ go_monthly_usd: 200 }));
    const l = loadLimits();
    assert.equal(l.go_monthly_usd, 200);
    assert.equal(l.low_headroom_pct, 15);
    assert.equal(l.missing, undefined);
  } finally {
    if (OLD === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = OLD;
  }
});

test("loadLimits defaults and honours the config file", () => {
  const h = tmp();
  const OLD = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    assert.deepEqual(loadLimits(), { go_monthly_usd: 60, low_headroom_pct: 15, missing: true });
    fs.mkdirSync(path.join(h, ".config", "orchestrator"), { recursive: true });
    fs.writeFileSync(path.join(h, ".config", "orchestrator", "usage-limits.json"), JSON.stringify({ go_monthly_usd: 200 }));
    const l = loadLimits();
    assert.equal(l.go_monthly_usd, 200);
    assert.equal(l.low_headroom_pct, 15);
    assert.equal(l.missing, undefined);
  } finally {
    if (OLD === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = OLD;
  }
});

// ── go-pacing G2: the v2 Go ledger (per-message rows, fixed windows) ─────────
// Bar 1: the ledger query never selects message text.
test("GO_LEDGER_SQL selects numeric fields only: no content, no bare data", () => {
  assert.doesNotMatch(GO_LEDGER_SQL, /content/);
  const withoutExtract = GO_LEDGER_SQL.replace(/json_extract\(data,/g, "json_extract(");
  assert.doesNotMatch(withoutExtract, /data/);
});

function makeMsgDb(messages) {
  const file = path.join(tmp(), "opencode.db");
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    db.exec(`CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, model TEXT, cost REAL,
      time_created INTEGER, time_updated INTEGER, tokens_input INTEGER, tokens_output INTEGER,
      tokens_reasoning INTEGER, tokens_cache_read INTEGER, directory TEXT);`);
    db.exec(`CREATE TABLE session_message (id TEXT PRIMARY KEY, sessionID TEXT, type TEXT, data TEXT, time_created INTEGER);`);
    const ins = db.prepare("INSERT INTO session_message VALUES (?,?,?,?,?)");
    for (const [i, m] of messages.entries()) {
      ins.run(`m${i}`, m.session ?? "ses0", m.type ?? "assistant", JSON.stringify(m.data), m.tc ?? 0);
    }
  } finally { db.close(); }
  return file;
}

const GO_MSG = (id, { ti = null, to = null, tr = null, cr = null, cw = null, completed = null, tc = 0, content = null, prov = "opencode-go" } = {}) => ({
  tc,
  data: {
    model: { providerID: prov, id },
    time: { completed, created: tc },
    tokens: { input: ti, output: to, reasoning: tr, cache: { read: cr, write: cw } },
    ...(content == null ? {} : { content }),
  },
});

test("goLedger never surfaces message content (bar 1)", () => {
  const file = makeMsgDb([
    GO_MSG("mimo-v2.6-flash", { ti: 1e6, tc: NOW - HOUR, content: [{ type: "text", text: "MARKER-9f3kq-secret" }] }),
  ]);
  const ledger = goLedger(file);
  assert.ok(ledger, "ledger present");
  assert.equal(ledger.rows.length, 1);
  assert.doesNotMatch(JSON.stringify(ledger), /MARKER-9f3kq-secret/);
});

test("goCost prices unknown models at the max rate, -free at $0, and keeps DeepSeek peak (bar 6)", () => {
  const off = Date.UTC(2026, 10, 17, 12, 0, 0); // Tuesday, off-peak
  const peak = Date.UTC(2026, 10, 16, 2, 30, 0); // Monday 02:30 UTC
  // Unknown model: highest rate in each column (input 0.37), unrated.
  const u = goCost("mystery-model", { input: 1e6 }, off);
  assert.equal(u.unrated, true);
  assert.ok(Math.abs(u.usd - 0.37) < 1e-9, JSON.stringify(u));
  // -free model: $0, never unrated.
  assert.deepEqual(goCost("iceman-contributor-free", { input: 1e6, output: 1e6 }, off), { usd: 0, unrated: false });
  // DeepSeek peak x2 on input+output, cache untouched by the multiplier.
  const dOff = goCost("deepseek-v4.1-flash", { input: 1e6, output: 1e6, cache_read: 1e6 }, off);
  const dPeak = goCost("deepseek-v4.1-flash", { input: 1e6, output: 1e6, cache_read: 1e6 }, peak);
  assert.ok(Math.abs(dOff.usd - (0.15 + 0.6 + 0.003)) < 1e-9, JSON.stringify(dOff));
  assert.ok(Math.abs(dPeak.usd - ((0.15 + 0.6) * 2 + 0.003)) < 1e-9, JSON.stringify(dPeak));
  assert.equal(dPeak.unrated, false);
  // Cache write bills at the input rate; reasoning as input.
  assert.ok(Math.abs(goCost("mimo-v2.6-flash", { cache_write: 1e6 }, off).usd - 0.14) < 1e-9);
  assert.ok(Math.abs(goCost("mimo-v2.6-flash", { input: 1e6, reasoning: 1e6 }, off).usd - 0.28) < 1e-9);
  // No tokens at all: $0, not unrated (the caller counts no_tokens).
  assert.deepEqual(goCost("mimo-v2.6-flash", {}, off), { usd: 0, unrated: false });
  assert.deepEqual(goCost("mystery-model", { input: null, output: null }, off), { usd: 0, unrated: false });
});

test("goLedger counts unrated and tokenless rows; t is completed ?? time_created (bars 2, 6)", () => {
  const t0 = Date.UTC(2026, 10, 17, 10, 0, 0);
  const file = makeMsgDb([
    GO_MSG("mimo-v2.6-flash", { ti: 1e6, tc: t0 - 1000, completed: t0, session: "long" }),
    GO_MSG("mystery-model", { ti: 1e6, tc: t0 + 6 * HOUR, session: "long" }),
    GO_MSG("mimo-v2.6-flash", { tc: t0 + 7 * HOUR, session: "long" }),
    // Non-assistant and non-Go rows are ignored.
    { ...GO_MSG("mimo-v2.6-flash", { ti: 9e6, tc: t0 }), type: "user" },
    GO_MSG("mimo-v2.6-flash", { ti: 9e6, tc: t0, prov: "commandcode" }),
  ]);
  const ledger = goLedger(file);
  assert.equal(ledger.rows.length, 3);
  assert.deepEqual(ledger.rows.map((r) => r.t), [t0, t0 + 6 * HOUR, t0 + 7 * HOUR], "completed wins; sorted by t");
  assert.equal(ledger.unrated, 1);
  assert.equal(ledger.no_tokens, 1);
  assert.equal(ledger.rows[2].usd, 0);
});

test("goV2 puts one session's messages in their own 5h windows (bar 2)", () => {
  const t0 = Date.UTC(2026, 10, 16, 10, 0, 0); // Monday, off-peak
  const anc = { go: { period_anchor: "2026-11-01T00:00:00.000Z" } };
  const at = (h) => Date.UTC(2026, 10, 16, h, 0, 0);
  const ledger = {
    rows: [
      { t: at(10), usd: 0.6, model: "mimo-v2.6-flash" },
      { t: at(16), usd: 0.6, model: "mimo-v2.6-flash" },
    ],
    unrated: 0,
    no_tokens: 0,
  };
  const v = goV2(ledger, at(16), anc);
  // 10:00 opens 10:00–15:00; 16:00 opens 16:00–21:00. Only the second counts.
  assert.equal(v.used_5h, 1, "100 * 0.6 / 60");
  assert.equal(v.usd_5h, 0.6);
  assert.equal(v.R_5h, new Date(at(21)).toISOString());
});

test("goV2 week starts Monday 00:00:00.000 UTC (bar 3)", () => {
  const mon = Date.UTC(2026, 10, 16, 0, 0, 0); // Monday
  const sun = mon - 1; // Sunday 23:59:59.999
  const ledger = {
    rows: [
      { t: sun, usd: 6, model: "mimo-v2.6-flash" },
      { t: mon, usd: 0.6, model: "mimo-v2.6-flash" },
    ],
    unrated: 0,
    no_tokens: 0,
  };
  const v = goV2(ledger, mon + HOUR, {});
  assert.equal(v.used_wk, 1, "only the Monday message counts");
  assert.equal(v.usd_wk, 0.6);
  assert.equal(v.R_wk, new Date(Date.UTC(2026, 10, 23, 0, 0, 0)).toISOString());
  assert.equal(v.used_mo, null, "no anchor: no monthly window");
  assert.equal(v.period_src, null);
});

test("goV2 fixed 5h windows: 10:00, 14:00, 15:30 at 16:00 (bar 4)", () => {
  const at = (h, m = 0) => Date.UTC(2026, 10, 16, h, m, 0); // Monday
  const ledger = {
    rows: [
      { t: at(10), usd: 1, model: "mimo-v2.6-flash" },
      { t: at(14), usd: 2, model: "mimo-v2.6-flash" },
      { t: at(15, 30), usd: 3, model: "mimo-v2.6-flash" },
    ],
    unrated: 0,
    no_tokens: 0,
  };
  const v = goV2(ledger, at(16), {});
  // Windows 10:00–15:00 and 15:30–20:30: only the 15:30 message counts.
  assert.ok(Math.abs(v.used_5h - 5) < 1e-9, JSON.stringify(v.used_5h)); // 100*3/60
  assert.equal(v.usd_5h, 3);
  assert.equal(v.R_5h, new Date(at(20, 30)).toISOString());
});

test("goV2 monthly window clamps the anchor day; none without an anchor (bar 5)", () => {
  const now = Date.UTC(2026, 2, 15, 12, 0, 0);
  const anchored = { go: { period_anchor: "2026-01-31T00:00:00.000Z" } };
  const ledger = {
    rows: [
      { t: Date.UTC(2026, 1, 1, 12), usd: 60, model: "mimo-v2.6-flash" }, // before the period
      { t: Date.UTC(2026, 2, 1, 12), usd: 0.6, model: "mimo-v2.6-flash" }, // in the period
    ],
    unrated: 0,
    no_tokens: 0,
  };
  const v = goV2(ledger, now, anchored);
  assert.equal(v.period_src, "anchor");
  assert.equal(v.R_mo, "2026-03-31T00:00:00.000Z");
  assert.equal(v.used_mo, 1, "only the March message counts");
  assert.equal(v.usd_mo, 0.6);
  assert.equal(v.elapsed_mo_h, 372, "Feb 28 00:00 to Mar 15 12:00");
  const bare = goV2(ledger, now, {});
  assert.equal(bare.period_src, null);
  assert.equal(bare.used_mo, null);
  assert.equal(bare.usd_mo, null);
  assert.equal(bare.R_mo, null);
  assert.equal(bare.elapsed_mo_h, null);
});

test("goV2 allowance-percent and plan selection (bar 7)", () => {
  const now = Date.UTC(2026, 10, 17, 12, 0, 0);
  const ledger = {
    rows: [
      { t: now - HOUR, usd: 1, model: "deepseek-v4.1-flash" },
      { t: now - HOUR, usd: 0.6, model: "mimo-v2.6-flash" },
      { t: now - HOUR, usd: 0.15, model: "mystery-model" },
    ],
    unrated: 1,
    no_tokens: 0,
  };
  const v = goV2(ledger, now, {});
  assert.equal(v.plan, "go");
  assert.deepEqual(v.caps, { "5h": 20, wk: 50, mo: 100 });
  // deepseek $1 of $100 = 1%; mimo $0.60 of $60 = 1%; unknown $0.15 of $15 = 1%.
  assert.equal(v.used_5h, 3);
  assert.equal(v.unrated, 1, "the ledger's unrated count passes through, counted once");
  // A model with a rate but no limit row falls back to the smallest limit.
  const rated = goV2(
    { rows: [{ t: now - HOUR, usd: 0.15, model: "qwen3.8-flash" }], unrated: 0, no_tokens: 0 },
    now, {},
  );
  assert.equal(rated.used_5h, 1, "$0.15 of the $15 fallback limit");
  assert.equal(rated.unrated, 1, "rate-known but limit-unknown counts unrated");
  const plus = goV2(
    { rows: [{ t: now - HOUR, usd: 2, model: "deepseek-v4.1-flash" }], unrated: 0, no_tokens: 0 },
    now, { go: { plan: "go-plus" } },
  );
  assert.equal(plus.plan, "go-plus");
  assert.equal(plus.used_5h, 1, "$2 of the $200 Go Plus limit");
  for (const limits of [{ go: { plan: "ultra" } }, { go: 42 }, {}, { go_monthly_usd: 200 }]) {
    const got = goV2(ledger, now, limits);
    assert.equal(got.plan, "go", JSON.stringify(limits));
    assert.equal(got.used_5h, 3, `the old go_monthly_usd key changes nothing: ${JSON.stringify(limits)}`);
  }
});

test("collectUsage without a message table: go_v2 null with the reason; without a db: unchanged (bar 8)", () => {
  const file = makeDb([{ model: M("opencode-go", "mimo-v2.6-flash"), ts: NOW - HOUR, ti: 10e6, to: 1e6, tc: 4e6 }]);
  // makeDb writes session_v2 only: goLedger finds no session_message table.
  const u = collectUsage(file, NOW, { go_monthly_usd: 60 });
  assert.ok(u.pools, "old pools still computed");
  assert.equal(u.go_v2, null);
  assert.ok(u.assumptions.includes("go ledger v2: no message ledger"), JSON.stringify(u.assumptions));
  assert.equal(goLedger(file), null);
  const missing = collectUsage(path.join(tmp(), "missing.db"), NOW, { go_monthly_usd: 60 });
  assert.equal(missing.pools, null);
  assert.equal(missing.go_v2, null);
  assert.deepEqual(missing.assumptions, ["no opencode db — usage unknown, nothing skipped for headroom"]);
});

test("goLedger returns null for a missing db and closes cleanly", () => {
  assert.equal(goLedger(path.join(tmp(), "missing.db")), null);
  assert.equal(goV2(null, NOW, {}), null);
});

test("old pools keys are byte-identical to the pre-change ledger (bar 9)", () => {
  const file = path.join(tmp(), "opencode.db");
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    db.exec(`CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, model TEXT, cost REAL,
      time_created INTEGER, time_updated INTEGER, tokens_input INTEGER, tokens_output INTEGER,
      tokens_reasoning INTEGER, tokens_cache_read INTEGER, directory TEXT);`);
    const ins = db.prepare("INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?)");
    ins.run("s0", "a", M("opencode-go", "mimo-v2.6-flash"), 0, NOW - 3600_000, NOW - 3600_000, 10e6, 1e6, 0, 4e6, "/tmp/x");
    ins.run("s1", "b", M("opencode-go", "deepseek-v4.1-flash"), 0, Date.UTC(2026, 10, 16, 2, 30), Date.UTC(2026, 10, 16, 2, 30), 1e6, 0.5e6, 0, 1e6, "/tmp/x");
    ins.run("s2", "c", "commandcode/deepseek/deepseek-v4.1-flash", 0, NOW - 2 * 3600_000, NOW - 2 * 3600_000, 1e6, 0, 0, 0, "/tmp/x");
    ins.run("s3", "d", M("nvidia", "x"), 0, NOW - 3 * 3600_000, NOW - 3 * 3600_000, 5e6, 1e6, 0, 0, "/tmp/x");
  } finally { db.close(); }
  const u = collectUsage(file, NOW, { go_monthly_usd: 60 });
  // Captured from the pre-change code before the v2 edit (bar 9 gate).
  const EXPECTED = `{"go":{"spend_5h":1.6912000000000003,"spend_7d":2.5942000000000003,"spend_mtd":2.5942000000000003,"spend_wtd":2.5942000000000003,"unmetered":0,"cap_5h":12,"cap_7d":30,"cap_mtd":60,"cap_wtd":30,"headroom_5h":0.8590666666666666,"headroom_7d":0.9135266666666666,"headroom_mtd":0.9567633333333333,"headroom":0.8590666666666666},"cmdc":{"spend_5h":0.15,"spend_7d":0.15,"spend_mtd":0.15,"spend_wtd":0.15,"unmetered":0,"cap_5h":20,"cap_7d":50,"cap_mtd":100,"cap_wtd":50,"headroom_5h":0.9925,"headroom_7d":0.997,"headroom_mtd":0.9985,"headroom":0.9925,"models":{"commandcode/deepseek/deepseek-v4.1-flash":{"spend_mtd":0.15,"cap_mtd":100,"headroom_mtd":0.9985}}}}`;
  assert.equal(JSON.stringify(u.pools), EXPECTED);
});

test("GO_MODEL_LIMITS: Claude-via-Go has no rate, prices at the max, unrated", () => {
  // GO_RATES never lists a Claude/Anthropic model (owner rule: Claude runs on
  // Claude Code). A Claude id therefore misses the rates and is priced at the
  // highest rate in each column, counted unrated — never free.
  const c = goCost("claude-haiku-5-5", { input: 1e6 }, Date.UTC(2026, 10, 17, 12, 0, 0));
  assert.equal(c.unrated, true);
  assert.ok(Math.abs(c.usd - 0.37) < 1e-9, JSON.stringify(c));
  // The limits columns still carry the plan's $15 rows, with the right minima.
  for (const [plan, column] of Object.entries(GO_MODEL_LIMITS)) {
    assert.equal(Math.min(...Object.values(column)), plan === "go" ? 15 : 60, `${plan} minimum`);
  }
  assert.equal(GO_MODEL_LIMITS.go["deepseek-v4.1-flash"], 100);
  assert.equal(GO_MODEL_LIMITS["go-plus"]["deepseek-v4.1-flash"], 200);
});

test("CLI prints the go ledger v2 line when the ledger exists, omits it otherwise", () => {
  const cli = path.join(HERE, "..", "bin", "usage.mjs");
  const withLedger = makeMsgDb([GO_MSG("mimo-v2.6-flash", { ti: 6e6, tc: Date.now() - HOUR })]);
  const r = spawnSync(process.execPath, [cli], {
    env: { ...process.env, OPENCODE_DB: withLedger, ORCH_HOME: tmp() }, encoding: "utf8", timeout: 30000,
  });
  assert.equal(r.status, 0, r.stderr);
  // Exact percents are covered by the goV2 unit tests; here only the line shape
  // (plan, caps, no-anchor mo part) matters. Mimo never pays a peak multiplier.
  assert.match(r.stdout, /^go ledger v2 \(go\): 5h \d+\.\d%\/20 · wk \d+\.\d%\/50 · mo \?\/100 \(no period anchor\)$/m, r.stdout);
  const withoutLedger = makeDb([{ model: M("opencode-go", "mimo-v2.6-flash"), ts: NOW - HOUR, ti: 10e6 }]);
  const r2 = spawnSync(process.execPath, [cli], {
    env: { ...process.env, OPENCODE_DB: withoutLedger, ORCH_HOME: tmp() }, encoding: "utf8", timeout: 30000,
  });
  assert.equal(r2.status, 0, r2.stderr);
  assert.doesNotMatch(r2.stdout, /go ledger v2/);
});

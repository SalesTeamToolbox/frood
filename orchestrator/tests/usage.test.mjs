// Local usage ledger: spend math, windows, headroom — all from fixture DBs, fixed clock.
// Never touches the real opencode db (OPENCODE_DB override) or the network.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { collectUsage, isPeak, loadLimits, poolHeadroom, rollup, rowCost } from "../bin/usage.mjs";

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

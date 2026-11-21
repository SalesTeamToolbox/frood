#!/usr/bin/env node
// Local usage ledger + pool headroom. Neither Go nor CommandCode exposes a live
// balance endpoint to agents (Go reports per-request `opencode.allowance` only in
// Console API responses, never in `opencode run` output; CmdC `/usage` is
// interactive-only), so headroom is estimated from local spend: every session row
// in opencode's db carries tokens + model + timestamp, and both providers publish
// per-token rates, window sizes and peak hours. External spend (other harnesses,
// Studio, phone) is invisible, so this is an UPPER bound on remaining headroom —
// good enough for preference ordering, never for hard gating. Quota failures still
// mark pools down through pool-health; that remains the backstop.
//
// Windows (UTC): Go 5h = trailing 5h vs 20% of monthly, week vs 50% (Monday 00:00
// reset), month vs calendar month (paid-period start unknown — assumed); CmdC
// GOAT trailing 5h vs $20, trailing 7d vs $50, calendar month vs $100, plus
// per-model monthly credit caps. Peak x2 on input+output for DeepSeek models,
// Mon–Fri 01–04 and 06–10 UTC, on both providers. Free pools always have full
// headroom. Unknown models are unmetered (never skipped for headroom).
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { DatabaseSync } from "node:sqlite";

export const LOW_HEADROOM_PCT_DEFAULT = 15;

// Per-1M-token [input, output, cacheRead]. Reasoning bills as output.
const GO_RATES = {
  "mimo-v2.6-flash": [0.14, 0.28, 0.0028],
  "deepseek-v4.1-flash": [0.15, 0.6, 0.003],
  "muse-spark-1.3-contributor": [0.1, 0.2, 0.002],
  "muse-spark-1.2-contributor": [0.1, 0.2, 0.002],
  "qwen3.8-flash": [0.16, 0.47, 0.016],
  "glm-5.3-flash": [0.37, 1.25, 0.075],
  "longcat-2.0": [0.3, 1.2, 0.006],
  "minimax-m3": [0.3, 1.2, 0.06],
};
const CMDC_RATES = {
  "deepseek/deepseek-v4.1-flash": [0.15, 0.6, 0.003],
  "z-ai/glm-5.3-flash": [0.15, 0.5, 0.03],
  "claude-haiku-5-5": [0.1, 0.5, 0.01],
  "gpt-6-luna": [0.1, 0.5, 0.01],
  "claude-sonnet-5-5": [2.0, 10.0, 0.1],
  "deepseek/deepseek-v4-pro": [0.66, 1.98, 0.022],
  "meta/muse-spark-1.3-contributor": [0.1, 0.2, 0.002],
  "moonshotai/kimi-k2.7-code": [0.95, 4.0, 0.19],
};
// CmdC per-model monthly credit caps (GOAT plan page; allowances move with deals).
const CMDC_MODEL_CAPS = {
  "deepseek/deepseek-v4.1-flash": 100,
  "z-ai/glm-5.3-flash": 100,
  "claude-haiku-5-5": 20,
  "gpt-6-luna": 20,
  "claude-sonnet-5-5": 10,
  "deepseek/deepseek-v4-pro": 20,
};

export function orchDir() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator");
}

/** Tunables live here, not in code: monthly caps are plan-specific. */
export function loadLimits() {
  const defaults = { go_monthly_usd: 60, low_headroom_pct: LOW_HEADROOM_PCT_DEFAULT };
  try {
    const raw = JSON.parse(fs.readFileSync(path.join(orchDir(), "usage-limits.json"), "utf8"));
    return { ...defaults, ...raw };
  } catch {
    return { ...defaults, missing: true };
  }
}

export function ocDbPath() {
  return process.env.OPENCODE_DB || path.join(os.homedir(), ".local", "share", "opencode", "opencode.db");
}

/** Peak pricing: DeepSeek input+output x2, Mon–Fri 01:00–04:00 and 06:00–10:00 UTC. */
export function isPeak(ts) {
  const d = new Date(ts);
  const day = d.getUTCDay();
  if (day === 0 || day === 6) return false;
  const h = d.getUTCHours() + d.getUTCMinutes() / 60;
  return (h >= 1 && h < 4) || (h >= 6 && h < 10);
}

function splitModel(raw) {
  if (!raw || typeof raw !== "string") return null;
  let provider = null;
  let id = raw;
  try {
    const m = JSON.parse(raw);
    if (m && typeof m === "object") {
      provider = m.providerID ?? null;
      id = m.id ?? raw;
    }
  } catch { /* plain "provider/id" string */ }
  if (!provider && id.includes("/")) {
    const cut = id.indexOf("/");
    provider = id.slice(0, cut);
    id = id.slice(cut + 1);
  }
  if (!provider) return null;
  return { provider, id };
}

function isFree(provider, id) {
  return provider === "nvidia" || id.endsWith("-free") || id.endsWith(":free") || provider === "opencode";
}

/** List-cost dollars of one session row. Null when unmetered (unknown model). */
export function rowCost(provider, id, tokens, ts) {
  const table = provider === "opencode-go" ? GO_RATES : provider === "commandcode" ? CMDC_RATES : null;
  const r = table?.[id];
  if (!r) return null;
  const peak = /deepseek/i.test(id) && isPeak(ts) ? 2 : 1;
  const t = tokens || {};
  const inp = (t.input || 0) + (t.reasoning || 0);
  return ((inp * r[0] + (t.output || 0) * r[1]) * peak + (t.cache_read || 0) * r[2]) / 1e6;
}

function openDb(dbPath) {
  if (!fs.existsSync(dbPath)) return null;
  try {
    const db = new DatabaseSync(dbPath, { readOnly: true });
    db.exec("PRAGMA busy_timeout=2000;");
    return db;
  } catch {
    return null;
  }
}

function monthStart(now) {
  const d = new Date(now);
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), 1);
}

function weekStartMonday(now) {
  const d = new Date(now);
  const back = (d.getUTCDay() + 6) % 7;
  return Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - back);
}

/**
 * Spend per pool and per CmdC model across the live windows. Pure function of
 * rows: [{provider, id, ts, cost}] — cost null means unmetered (free or unknown).
 */
export function rollup(rows, now = Date.now(), limits = loadLimits()) {
  const h5 = now - 5 * 3600_000;
  const d7 = now - 7 * 86400_000;
  const mStart = monthStart(now);
  const wStart = weekStartMonday(now);
  const pools = {
    go: { spend_5h: 0, spend_7d: 0, spend_mtd: 0, spend_wtd: 0, unmetered: 0 },
    cmdc: { spend_5h: 0, spend_7d: 0, spend_mtd: 0, spend_wtd: 0, unmetered: 0 },
  };
  const models = {}; // "commandcode/<id>" -> {spend_mtd}
  for (const r of rows) {
    if (r.cost == null) {
      if (r.provider === "opencode-go" || r.provider === "commandcode") {
        (r.provider === "opencode-go" ? pools.go : pools.cmdc).unmetered++;
      }
      continue;
    }
    const p = r.provider === "opencode-go" ? pools.go : r.provider === "commandcode" ? pools.cmdc : null;
    if (!p) continue; // free pools cost nothing by construction
    if (r.ts > h5) p.spend_5h += r.cost;
    if (r.ts > d7) p.spend_7d += r.cost;
    if (r.ts >= wStart) p.spend_wtd += r.cost;
    if (r.ts >= mStart) p.spend_mtd += r.cost;
    if (r.provider === "commandcode") {
      const k = `commandcode/${r.id}`;
      models[k] = models[k] || { spend_mtd: 0 };
      if (r.ts >= mStart) models[k].spend_mtd += r.cost;
    }
  }
  const M = limits.go_monthly_usd;
  const headroom = (spend, cap) => (cap <= 0 ? 0 : Math.max(0, Math.min(1, 1 - spend / cap)));
  const go = {
    ...pools.go,
    cap_5h: 0.2 * M, cap_7d: 0.5 * M, cap_mtd: M, cap_wtd: 0.5 * M,
    headroom_5h: headroom(pools.go.spend_5h, 0.2 * M),
    headroom_7d: headroom(pools.go.spend_7d, 0.5 * M),
    headroom_mtd: headroom(pools.go.spend_mtd, M),
    headroom: 0,
  };
  go.headroom = Math.min(go.headroom_5h, go.headroom_7d, go.headroom_mtd);
  const cmdc = {
    ...pools.cmdc,
    cap_5h: 20, cap_7d: 50, cap_mtd: 100, cap_wtd: 50,
    headroom_5h: headroom(pools.cmdc.spend_5h, 20),
    headroom_7d: headroom(pools.cmdc.spend_7d, 50),
    headroom_mtd: headroom(pools.cmdc.spend_mtd, 100),
    headroom: 0,
    models: {},
  };
  for (const [k, v] of Object.entries(models)) {
    const cap = CMDC_MODEL_CAPS[k.slice("commandcode/".length)] ?? null;
    cmdc.models[k] = { ...v, cap_mtd: cap, headroom_mtd: cap == null ? null : headroom(v.spend_mtd, cap) };
  }
  cmdc.headroom = Math.min(cmdc.headroom_5h, cmdc.headroom_7d, cmdc.headroom_mtd);
  return { now, pools: { go, cmdc }, assumptions: assumptions(limits) };
}

/**
 * Headroom for one model ("provider/id"). Null when the model is free or
 * unmetered — free pools are never skipped for headroom. Otherwise
 * {headroom 0..1, label} with label naming the tightest window.
 */
export function poolHeadroom(usage, provider, id) {
  if (!usage?.pools) return null;
  if (provider !== "opencode-go" && provider !== "commandcode") return null;
  if (id.endsWith("-free") || id.endsWith(":free")) return null;
  const money = (x) => `$${x.toFixed(2)}`;
  if (provider === "opencode-go") {
    const p = usage.pools.go;
    const wins = [
      ["5h", p.headroom_5h, p.spend_5h, p.cap_5h],
      ["7d", p.headroom_7d, p.spend_7d, p.cap_7d],
      ["mtd", p.headroom_mtd, p.spend_mtd, p.cap_mtd],
    ].sort((a, b) => a[1] - b[1]);
    const [name, h, spend, cap] = wins[0];
    return { headroom: h, label: `${name} ${money(spend)}/${money(cap)}` };
  }
  const p = usage.pools.cmdc;
  const wins = [
    ["5h", p.headroom_5h, p.spend_5h, p.cap_5h],
    ["7d", p.headroom_7d, p.spend_7d, p.cap_7d],
    ["mtd", p.headroom_mtd, p.spend_mtd, p.cap_mtd],
  ];
  const m = p.models?.[`commandcode/${id}`];
  if (m?.cap_mtd != null) wins.push(["model-mtd", m.headroom_mtd, m.spend_mtd, m.cap_mtd]);
  wins.sort((a, b) => a[1] - b[1]);
  const [name, h, spend, cap] = wins[0];
  return { headroom: h, label: `${name} ${money(spend)}/${money(cap)}` };
}

function assumptions(limits) {
  return [
    `spend from local sessions only — other harnesses/clients are invisible, so headroom is an upper bound`,
    `Go monthly allowance $${limits.go_monthly_usd} (${limits.missing ? "default; set go_monthly_usd in usage-limits.json" : "from usage-limits.json"}), calendar month (paid-period start unknown)`,
    `CmdC GOAT windows $20/5h, $50/7d, $100/calendar-month; per-model monthly credit caps from the plan page`,
    `peak x2 input+output for DeepSeek, Mon–Fri 01–04 and 06–10 UTC`,
  ];
}

export function collectUsage(dbPath = ocDbPath(), now = Date.now(), limits = loadLimits()) {
  const db = openDb(dbPath);
  if (!db) return { now, pools: null, assumptions: ["no opencode db — usage unknown, nothing skipped for headroom"] };
  try {
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map((t) => t.name);
    const table = tables.includes("session_v2") ? "session_v2" : tables.includes("session") ? "session" : null;
    if (!table) return { now, pools: null, assumptions: ["no session table — usage unknown"] };
    const cols = db.prepare(`PRAGMA table_info(${table})`).all().map((c) => c.name);
    const has = (c) => (cols.includes(c) ? c : null);
    // Legacy `session` table lacks token/model columns: presence only, never spend.
    const rows = db.prepare(
      `SELECT id, ${has("model") ?? "'' AS model"}, ${has("tokens_input") ?? "0 AS tokens_input"}, ${has("tokens_output") ?? "0 AS tokens_output"}, ${has("tokens_reasoning") ?? "0 AS tokens_reasoning"}, ${has("tokens_cache_read") ?? "0 AS tokens_cache_read"}, ${has("time_created") ?? "0 AS time_created"} FROM ${table}`,
    ).all().map((r) => {
      const split = splitModel(r.model);
      if (!split) return null;
      if (isFree(split.provider, split.id)) return { provider: split.provider, id: split.id, ts: r.time_created, cost: 0 };
      return {
        provider: split.provider, id: split.id, ts: r.time_created,
        cost: rowCost(split.provider, split.id, { input: r.tokens_input, output: r.tokens_output, reasoning: r.tokens_reasoning, cache_read: r.tokens_cache_read }, r.time_created),
      };
    }).filter(Boolean);
    return rollup(rows, now, limits);
  } catch {
    return { now, pools: null, assumptions: ["opencode db unreadable — usage unknown, nothing skipped for headroom"] };
  } finally {
    try { db.close(); } catch { /* ignore */ }
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  const args = new Set(process.argv.slice(2));
  const u = collectUsage();
  if (args.has("--json")) {
    console.log(JSON.stringify(u, null, 2));
    process.exit(0);
  }
  if (!u.pools) {
    console.log(`usage: ${u.assumptions[0]}`);
    process.exit(0);
  }
  const pct = (x) => `${Math.round(x * 100)}%`;
  for (const [name, p] of Object.entries(u.pools)) {
    console.log(`${name}: 5h $${p.spend_5h.toFixed(2)}/$${p.cap_5h} · 7d $${p.spend_7d.toFixed(2)}/$${p.cap_7d} · mtd $${p.spend_mtd.toFixed(2)}/$${p.cap_mtd} · headroom ${pct(p.headroom)}${p.unmetered ? ` (${p.unmetered} unmetered rows)` : ""}`);
    for (const [m, v] of Object.entries(p.models ?? {})) {
      if (v.cap_mtd != null) console.log(`  ${m}: mtd $${v.spend_mtd.toFixed(2)}/$${v.cap_mtd} · headroom ${pct(v.headroom_mtd)}`);
    }
  }
}

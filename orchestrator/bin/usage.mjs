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
import { fiveHourWindow, goConfig, periodBounds, sumUsd, weekBounds } from "./go-pace.mjs";

export const LOW_HEADROOM_PCT_DEFAULT = 15;

// Per-1M-token [input, output, cacheRead] for the OLD trailing-window ledger.
// Never a Claude/Anthropic entry: owner rule, Claude runs on the Claude Code
// subscription, never through OpenCode Go (go-pacing G1 enforces this in lint
// and pool-health). A Go model missing here costs null → unmetered in the old
// floor; the v2 ledger (goCost) instead prices it at the highest rate so an
// unknown Go model can never look free.
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

// Per-model monthly allowance limits in dollars for the v2 Go ledger (allowance
// percent = 100 * usd / L). Keys are opencode model ids (without the
// `opencode-go/` prefix). `go` from the plan Handoff (G-D2, re-read
// 2026-11-27); `go-plus` from the Go Plus column of opencode.ai/docs/console/go.
// A model in neither column uses the smallest limit of its column and counts
// `unrated`. No Claude entry is costed here — see GO_RATES above.
export const GO_MODEL_LIMITS = Object.freeze({
  go: Object.freeze({
    "deepseek-v4.1-flash": 100,
    "mimo-v2.6-flash": 60,
    "muse-spark-1.3-contributor": 60,
    "muse-spark-1.2-contributor": 60,
    "glm-5.3-flash": 60,
    "glm-5.3": 200,
    "glm-5.2": 60,
    "minimax-m3": 60,
    "minimax-m3.1-flash": 20,
    "kimi-k2.7-code": 60,
    "kimi-k3": 15,
    "kimi-k3.1-pro": 15,
    "longcat-2.5": 60,
    "deepseek-v4-pro": 15,
    "mimo-v2.6-pro": 15,
    "claude-haiku-5-5": 15,
    "gpt-6-luna": 15,
    "gpt-5.6-luna": 15,
    "grok-4.7": 15,
    "qwen3.8-max": 15,
    "qwen4-max": 15,
    "step-5-preview": 15,
    "gemini-4-argon": 30,
    "hy4-preview": 30,
    "hy4": 60,
    "hy3": 60,
  }),
  "go-plus": Object.freeze({
    "deepseek-v4.1-flash": 200,
    "mimo-v2.6-flash": 120,
    "muse-spark-1.3-contributor": 120,
    "muse-spark-1.2-contributor": 120,
    "glm-5.3-flash": 180,
    "glm-5.3": 400,
    "glm-5.2": 180,
    "minimax-m3": 180,
    "minimax-m3.1-flash": 80,
    "kimi-k2.7-code": 180,
    "kimi-k3": 60,
    "kimi-k3.1-pro": 60,
    "longcat-2.5": 240,
    "deepseek-v4-pro": 60,
    "mimo-v2.6-pro": 60,
    "claude-haiku-5-5": 60,
    "gpt-6-luna": 60,
    "gpt-5.6-luna": 60,
    "grok-4.7": 60,
    "qwen3.8-max": 60,
    "qwen4-max": 60,
    "step-5-preview": 60,
    "gemini-4-argon": 120,
    "hy4-preview": 120,
    "hy4": 240,
    "hy3": 240,
  }),
});

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

// Highest per-column rate across GO_RATES: an unknown Go model is priced here,
// so it can never look free. [input, output, cacheRead].
const GO_MAX_RATE = (() => {
  let inp = 0, out = 0, read = 0;
  for (const r of Object.values(GO_RATES)) {
    if (r[0] > inp) inp = r[0];
    if (r[1] > out) out = r[1];
    if (r[2] > read) read = r[2];
  }
  return [inp, out, read];
})();

/**
 * List-cost dollars of one v2 ledger message. `tokens` carries the
 * session_message numeric fields (input/output/reasoning/cache_read/cache_write,
 * with a nested cache {read, write} also accepted). Returns {usd, unrated}:
 * a `-free` id is $0 and never unrated; all tokens null/absent is $0 (the
 * caller counts it in no_tokens); an id missing from GO_RATES is priced at the
 * highest rate in each column and unrated. DeepSeek peak x2 on input+output
 * (isPeak); cache_write is billed at the input rate; reasoning as input.
 */
export function goCost(id, tokens, ts) {
  const t = tokens || {};
  const cacheRead = t.cache_read ?? t.cache?.read;
  const cacheWrite = t.cache_write ?? t.cache?.write;
  const anyPresent = t.input != null || t.output != null || t.reasoning != null || cacheRead != null || cacheWrite != null;
  if (!anyPresent) return { usd: 0, unrated: false };
  if (typeof id === "string" && id.endsWith("-free")) return { usd: 0, unrated: false };
  const known = typeof id === "string" ? GO_RATES[id] : undefined;
  const r = known ?? GO_MAX_RATE;
  const peak = typeof id === "string" && /deepseek/i.test(id) && isPeak(ts) ? 2 : 1;
  const inp = (t.input || 0) + (t.reasoning || 0);
  const usd = ((inp * r[0] + (t.output || 0) * r[1]) * peak + (cacheRead || 0) * r[2] + (cacheWrite || 0) * r[0]) / 1e6;
  return { usd, unrated: known == null };
}

// The exact v2 ledger query. Numeric fields only, via json_extract: `data`
// never appears outside json_extract(, and message text (`content`) is never
// selected, so a marker planted in content cannot reach the parsed rows.
export const GO_LEDGER_SQL = `SELECT time_created, json_extract(data,'$.model.providerID') AS provider, json_extract(data,'$.model.id') AS id, json_extract(data,'$.time.completed') AS completed, json_extract(data,'$.tokens.input') AS ti, json_extract(data,'$.tokens.output') AS tout, json_extract(data,'$.tokens.reasoning') AS tr, json_extract(data,'$.tokens.cache.read') AS tcr, json_extract(data,'$.tokens.cache.write') AS tcw FROM session_message WHERE type='assistant' AND json_extract(data,'$.model.providerID') = 'opencode-go'`;

/**
 * The v2 Go ledger: per-message cost from session_message rows (type
 * assistant, provider opencode-go). Returns null when there is no db or no
 * session_message table (or on any read error), else
 * {rows: [{t, usd, model}] sorted by t, unrated, no_tokens}. t is
 * time.completed ?? time_created (epoch ms); rows with no tokens cost $0 and
 * count in no_tokens. Read-only open, closed in finally.
 */
export function goLedger(dbPath = ocDbPath()) {
  let db = null;
  try {
    if (!fs.existsSync(dbPath)) return null;
    db = new DatabaseSync(dbPath, { readOnly: true });
    db.exec("PRAGMA busy_timeout=2000;");
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map((t) => t.name);
    if (!tables.includes("session_message")) return null;
    const found = db.prepare(GO_LEDGER_SQL).all();
    const rows = [];
    let unrated = 0;
    let noTokens = 0;
    for (const m of found) {
      if (m.provider !== "opencode-go") continue;
      const t = m.completed ?? m.time_created;
      if (!Number.isFinite(t)) continue;
      const tokens = { input: m.ti, output: m.tout, reasoning: m.tr, cache_read: m.tcr, cache_write: m.tcw };
      const priced = goCost(m.id, tokens, t);
      if (priced.usd === 0) {
        const cacheRead = tokens.cache_read;
        const cacheWrite = tokens.cache_write;
        if (tokens.input == null && tokens.output == null && tokens.reasoning == null && cacheRead == null && cacheWrite == null) noTokens++;
      }
      if (priced.unrated) unrated++;
      rows.push({ t, usd: priced.usd, model: m.id });
    }
    rows.sort((a, b) => a.t - b.t);
    return { rows, unrated, no_tokens: noTokens };
  } catch {
    return null;
  } finally {
    try { db?.close(); } catch { /* ignore */ }
  }
}

const round4 = (v) => (Number.isFinite(v) ? Math.round(v * 1e4) / 1e4 : null);

/**
 * The v2 Go ledger in allowance-percent. Pure function of the ledger, now and
 * limits. Units (owner correction 2026-11-27): used_* and recent are
 * allowance-percent (sum of row pct = 100 * usd / L), usd_* the same windows
 * in dollars. Plan from limits.go.plan ("go"/"go-plus", else "go");
 * caps are {5h: 20, wk: 50, mo: 100}. 5h is the fixed window over rows with
 * usd > 0 (none open: used_5h/usd_5h 0, R_5h null); wk starts Monday 00:00
 * UTC; mo starts at the paid period (period_anchor; none: used_mo, usd_mo,
 * R_mo, elapsed_mo_h and period_src null). recent is the percent over the
 * last pace.recent_hours. R_* are ISO strings; percents and dollars rounded
 * to 4 decimals. Null when the ledger is null.
 */
export function goV2(ledger, now = Date.now(), limits = loadLimits()) {
  if (ledger == null) return null;
  const top = limits && typeof limits === "object" ? limits : {};
  const goBlock = top.go && typeof top.go === "object" && !Array.isArray(top.go) ? top.go : null;
  const plan = goBlock?.plan === "go-plus" ? "go-plus" : "go";
  const column = GO_MODEL_LIMITS[plan];
  const minLimit = Math.min(...Object.values(column));
  const cfg = goConfig(top);
  const rows = Array.isArray(ledger.rows) ? ledger.rows : [];
  const withPct = rows.map((r) => {
    const L = (typeof r.model === "string" && column[r.model]) || minLimit;
    return { t: r.t, usd: Number.isFinite(r.usd) ? r.usd : 0, pct: 100 * (Number.isFinite(r.usd) ? r.usd : 0) / L };
  });
  // A model with a rate but no limit row still costs allowance against the
  // fallback limit: count it unrated here (the ledger already counted the
  // rate-unknown ones). Free (-free) rows cost nothing and stay rated.
  let unrated = Number.isFinite(ledger.unrated) ? ledger.unrated : 0;
  for (const r of rows) {
    if (typeof r.model === "string" && !r.model.endsWith("-free") && column[r.model] == null && GO_RATES[r.model] != null && Number.isFinite(r.usd) && r.usd > 0) unrated++;
  }
  const noTokens = Number.isFinite(ledger.no_tokens) ? ledger.no_tokens : 0;
  // sumUsd sums a row's usd field: for percents pass rows mapped to {t, usd: pct}.
  const past = withPct.filter((r) => r.t <= now);
  const forPct = past.map((r) => ({ t: r.t, usd: r.pct }));
  const forUsd = past.map((r) => ({ t: r.t, usd: r.usd }));
  const w5 = fiveHourWindow(withPct.filter((r) => r.usd > 0).map((r) => r.t), now);
  const wk = weekBounds(now);
  const mo = periodBounds(cfg.period_anchor, now);
  const used5h = w5 ? sumUsd(forPct, w5.start, w5.end) : 0;
  const usd5h = w5 ? sumUsd(forUsd, w5.start, w5.end) : 0;
  const usedWk = wk ? sumUsd(forPct, wk.start, Infinity) : 0;
  const usdWk = wk ? sumUsd(forUsd, wk.start, Infinity) : 0;
  const recentFrom = now - cfg.pace.recent_hours * 3600_000;
  const recent = sumUsd(forPct, recentFrom, Infinity);
  const out = {
    plan,
    caps: { "5h": 20, wk: 50, mo: 100 },
    used_5h: round4(used5h),
    used_wk: round4(usedWk),
    used_mo: null,
    usd_5h: round4(usd5h),
    usd_wk: round4(usdWk),
    usd_mo: null,
    R_5h: w5 ? new Date(w5.end).toISOString() : null,
    R_wk: wk ? new Date(wk.end).toISOString() : null,
    R_mo: null,
    elapsed_mo_h: null,
    recent: round4(recent),
    unrated,
    no_tokens: noTokens,
    period_src: null,
  };
  if (mo) {
    const usedMo = sumUsd(forPct, mo.start, Infinity);
    const usdMo = sumUsd(forUsd, mo.start, Infinity);
    out.used_mo = round4(usedMo);
    out.usd_mo = round4(usdMo);
    out.R_mo = new Date(mo.end).toISOString();
    out.elapsed_mo_h = round4((now - mo.start) / 3600_000);
    out.period_src = "anchor";
  }
  return out;
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
  if (!db) return { now, pools: null, go_v2: null, assumptions: ["no opencode db — usage unknown, nothing skipped for headroom"] };
  try {
    const tables = db.prepare("SELECT name FROM sqlite_master WHERE type='table'").all().map((t) => t.name);
    const table = tables.includes("session_v2") ? "session_v2" : tables.includes("session") ? "session" : null;
    if (!table) return { now, pools: null, go_v2: null, assumptions: ["no session table — usage unknown"] };
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
    const rolled = rollup(rows, now, limits);
    // Second, correct Go ledger from per-message rows beside the old headroom
    // floor: the old pools and every old key stay byte-identical.
    const ledger = goLedger(dbPath);
    const v2 = goV2(ledger, now, limits);
    const assumptions = v2 == null
      ? [...rolled.assumptions, "go ledger v2: no message ledger"]
      : rolled.assumptions;
    return { ...rolled, go_v2: v2, assumptions };
  } catch {
    return { now, pools: null, go_v2: null, assumptions: ["opencode db unreadable — usage unknown, nothing skipped for headroom"] };
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
  const v2 = u.go_v2;
  if (v2 != null) {
    const mo = v2.used_mo == null ? "mo ?/100 (no period anchor)" : `mo ${v2.used_mo.toFixed(1)}%/100 ($${v2.usd_mo.toFixed(2)})`;
    console.log(`go ledger v2 (${v2.plan}): 5h ${v2.used_5h.toFixed(1)}%/20 · wk ${v2.used_wk.toFixed(1)}%/50 · ${mo}${v2.unrated > 0 ? ` · ${v2.unrated} unrated` : ""}`);
  }
}

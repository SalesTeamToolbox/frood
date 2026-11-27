#!/usr/bin/env node
// Go usage snapshots (go-pacing G3a). One fixed endpoint, key in-process, no URL/env/argv key flow.
//   readGoKey({env, dbPath}) reads OPENCODE_GO_KEY else opencode's db credential row (read-only,
//   active opencode-go row only); any error gives null. parseUsage(json) maps the G0 shape
//   {usage: {rolling|weekly|monthly: {status, percent, resetsAt}}} to {rolling, weekly, monthly} each
//   {pct, status, resets_at} or null (whole result null when json.usage is not an object).
//   snapshot({url, fetchImpl, now, key}) GETs the URL (https, or http only for 127.0.0.1/localhost/[::1])
//   with the key in the Authorization header only (10 s timeout); key defaults to readGoKey().
//   appendSnapshot(snap, {path}) atomically appends to <orchDir()>/go-usage.jsonl (temp + rename,
//   pruned past 8 weeks). readLatest({path}) / readHistory({path, since}) skip unparsable lines.
//   CLI: node go-usage.mjs snapshot [--json] (snapshot() with defaults, append on ok, one line, exit 0
//   always) and node go-usage.mjs latest [--json]. The URL is a parameter only, never env or argv.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { DatabaseSync } from "node:sqlite";
import { orchDir } from "./usage.mjs";

export const GO_USAGE_URL_DEFAULT = "https://opencode.ai/inference/go/v1/usage";

const HISTORY_MS = 8 * 7 * 24 * 3600 * 1000;
const TIMEOUT_MS = 10000;
const MAX_TIME = 8.64e15;

const defaultPath = () => path.join(orchDir(), "go-usage.jsonl");

function dbDefault(env) {
  if (env && typeof env.OPENCODE_DB === "string" && env.OPENCODE_DB.length > 0) return env.OPENCODE_DB;
  return path.join(os.homedir(), ".local", "share", "opencode", "opencode.db");
}

/**
 * The Go key: OPENCODE_GO_KEY when set, else the active opencode-go credential row's key
 * (SELECT value only; JSON.parse(value).key). Any error gives null. Never throws.
 */
export function readGoKey({ env = process.env, dbPath } = {}) {
  try {
    const e = env && typeof env === "object" ? env : {};
    const fromEnv = e.OPENCODE_GO_KEY;
    if (typeof fromEnv === "string" && fromEnv.length > 0) return fromEnv;
    const p = typeof dbPath === "string" && dbPath.length > 0 ? dbPath : dbDefault(e);
    if (!fs.existsSync(p)) return null;
    let db;
    try {
      db = new DatabaseSync(p, { readOnly: true });
    } catch {
      return null;
    }
    try {
      try {
        db.exec("PRAGMA busy_timeout=2000;");
      } catch {
        /* ignore */
      }
      let row;
      try {
        row = db.prepare("SELECT value FROM credential WHERE integration_id = 'opencode-go' AND active = 1 LIMIT 1").get();
      } catch {
        return null;
      }
      if (!row || typeof row.value !== "string") return null;
      let parsed;
      try {
        parsed = JSON.parse(row.value);
      } catch {
        return null;
      }
      const k = parsed && typeof parsed === "object" ? parsed.key : null;
      if (typeof k !== "string" || k.length === 0) return null;
      return k;
    } finally {
      try {
        db.close();
      } catch {
        /* ignore */
      }
    }
  } catch {
    return null;
  }
}

function meterOf(usage, name) {
  const m = usage ? usage[name] : null;
  if (!m || typeof m !== "object" || Array.isArray(m)) return null;
  const pct = m.percent;
  if (!Number.isFinite(pct) || pct < 0 || pct > 100) return null;
  if (typeof m.status !== "string") return null;
  if (typeof m.resetsAt !== "string" || !Number.isFinite(Date.parse(m.resetsAt))) return null;
  let resets_at;
  try {
    resets_at = new Date(Date.parse(m.resetsAt)).toISOString();
  } catch {
    return null;
  }
  return { pct, status: m.status, resets_at };
}

/** G0 shape to {rolling, weekly, monthly}; null when json.usage is not an object. Never throws. */
export function parseUsage(json) {
  try {
    if (!json || typeof json !== "object" || Array.isArray(json)) return null;
    const u = json.usage;
    if (!u || typeof u !== "object" || Array.isArray(u)) return null;
    return { rolling: meterOf(u, "rolling"), weekly: meterOf(u, "weekly"), monthly: meterOf(u, "monthly") };
  } catch {
    return null;
  }
}

function isLoopback(hostname) {
  const h = String(hostname || "").toLowerCase().replace(/^\[|\]$/g, "");
  return h === "127.0.0.1" || h === "localhost" || h === "::1";
}

/**
 * One usage read. key defaults to readGoKey(); no key gives {ok:false, reason:"no key"} with no
 * request. Non-loopback http, ftp and unparsable URLs give {ok:false, reason:"refused url"} with no
 * request. Never throws; error reasons are fixed strings so the key cannot leak into them.
 */
export async function snapshot({ url = GO_USAGE_URL_DEFAULT, fetchImpl = fetch, now = Date.now(), key } = {}) {
  let k = key;
  if (k === undefined) {
    try {
      k = readGoKey();
    } catch {
      k = null;
    }
  }
  if (typeof k !== "string" || k.length === 0) return { ok: false, reason: "no key" };
  let parsed;
  try {
    parsed = new URL(url);
  } catch {
    return { ok: false, reason: "refused url" };
  }
  const proto = String(parsed.protocol || "").toLowerCase();
  if (proto === "https:") {
    /* allowed */
  } else if (proto === "http:" && isLoopback(parsed.hostname)) {
    /* loopback test servers only */
  } else {
    return { ok: false, reason: "refused url" };
  }
  let res;
  try {
    res = await fetchImpl(url, {
      headers: { Authorization: `Bearer ${k}` },
      signal: AbortSignal.timeout(TIMEOUT_MS),
    });
  } catch (e) {
    const name = e && typeof e === "object" ? e.name || e.code : null;
    if (name === "TimeoutError" || name === "AbortError" || name === "ABORT_ERR") return { ok: false, reason: "timeout" };
    return { ok: false, reason: "error" };
  }
  try {
    if (!res || typeof res.status !== "number") return { ok: false, reason: "error" };
    if (res.status !== 200) return { ok: false, reason: `http ${res.status}` };
    let body;
    try {
      body = await res.json();
    } catch {
      return { ok: false, reason: "bad json" };
    }
    const meters = parseUsage(body);
    if (!meters) return { ok: false, reason: "bad shape" };
    let at;
    try {
      if (!Number.isFinite(now) || Math.abs(now) > MAX_TIME) return { ok: false, reason: "error" };
      at = new Date(now).toISOString();
    } catch {
      return { ok: false, reason: "error" };
    }
    return { ok: true, snap: { at, rolling: meters.rolling, weekly: meters.weekly, monthly: meters.monthly } };
  } catch {
    return { ok: false, reason: "error" };
  }
}

/** Append to the jsonl store (temp + rename, pruned to 8 weeks from snap.at). Returns lines kept. */
export function appendSnapshot(snap, opts = {}) {
  const custom = opts && typeof opts === "object" ? opts.path : null;
  const file = typeof custom === "string" && custom.length > 0 ? custom : defaultPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const ref =
    snap && typeof snap.at === "string" && Number.isFinite(Date.parse(snap.at)) ? Date.parse(snap.at) : Date.now();
  const cutoff = ref - HISTORY_MS;
  let lines = [];
  try {
    lines = fs.readFileSync(file, "utf8").split("\n").filter(Boolean);
  } catch {
    lines = [];
  }
  const kept = [];
  for (const line of lines) {
    try {
      const r = JSON.parse(line);
      if (!r || typeof r !== "object" || typeof r.at !== "string") continue;
      const t = Date.parse(r.at);
      if (!Number.isFinite(t) || t < cutoff) continue;
      kept.push(r);
    } catch {
      continue;
    }
  }
  if (snap && typeof snap === "object" && typeof snap.at === "string" && Number.isFinite(Date.parse(snap.at))) {
    if (Date.parse(snap.at) >= cutoff) kept.push(snap);
  }
  kept.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, kept.map((r) => JSON.stringify(r)).join("\n") + (kept.length ? "\n" : ""));
  fs.renameSync(tmp, file);
  return kept.length;
}

/** Every parseable line, oldest first; since (ms or ISO) filters to at >= since. Never throws. */
export function readHistory(opts = {}) {
  const custom = opts && typeof opts === "object" ? opts.path : null;
  const since = opts && typeof opts === "object" ? opts.since : undefined;
  const file = typeof custom === "string" && custom.length > 0 ? custom : defaultPath();
  let sinceMs = null;
  if (typeof since === "number" && Number.isFinite(since)) sinceMs = since;
  else if (typeof since === "string" && Number.isFinite(Date.parse(since))) sinceMs = Date.parse(since);
  try {
    const raw = fs.readFileSync(file, "utf8");
    const out = [];
    for (const line of raw.split("\n")) {
      if (!line) continue;
      try {
        const r = JSON.parse(line);
        if (!r || typeof r !== "object") continue;
        if (sinceMs != null) {
          const t = Date.parse(r.at);
          if (!Number.isFinite(t) || t < sinceMs) continue;
        }
        out.push(r);
      } catch {
        continue;
      }
    }
    return out;
  } catch {
    return [];
  }
}

/** Newest record by at, or null. Never throws. */
export function readLatest(opts = {}) {
  const hist = readHistory(opts);
  if (!hist.length) return null;
  let best = hist[0];
  let bestT = Date.parse(best && best.at);
  if (!Number.isFinite(bestT)) bestT = -Infinity;
  for (let i = 1; i < hist.length; i++) {
    const t = Date.parse(hist[i] && hist[i].at);
    if (Number.isFinite(t) && t >= bestT) {
      best = hist[i];
      bestT = t;
    } else if (!Number.isFinite(t) && !Number.isFinite(bestT)) {
      best = hist[i];
    }
  }
  return best;
}

const pctOrNa = (m) => (m && Number.isFinite(m.pct) ? `${m.pct}%` : "n/a");

function formatLine(snap) {
  const moReset = snap && snap.monthly && typeof snap.monthly.resets_at === "string" ? snap.monthly.resets_at : "?";
  return `go usage: 5h ${pctOrNa(snap && snap.rolling)} wk ${pctOrNa(snap && snap.weekly)} mo ${pctOrNa(snap && snap.monthly)} resets mo ${moReset}`;
}

export async function main(argv) {
  const [cmd, ...rest] = argv;
  const json = rest.includes("--json");
  if (cmd === "snapshot") {
    let r;
    try {
      r = await snapshot();
    } catch {
      console.log("go usage: error");
      return 0;
    }
    if (r.ok) {
      try {
        appendSnapshot(r.snap);
      } catch {
        /* store failure never changes the line */
      }
      if (json) console.log(JSON.stringify(r.snap));
      else console.log(formatLine(r.snap));
    } else if (json) {
      console.log(JSON.stringify({ ok: false, reason: r.reason }));
    } else {
      console.log(`go usage: ${r.reason}`);
    }
    return 0;
  }
  if (cmd === "latest") {
    let r;
    try {
      r = readLatest();
    } catch {
      console.log("no snapshot");
      return 0;
    }
    if (!r) {
      console.log("no snapshot");
      return 0;
    }
    if (json) console.log(JSON.stringify(r));
    else console.log(formatLine(r));
    return 0;
  }
  console.error("go-usage: usage: snapshot [--json] | latest [--json]");
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === path.resolve(new URL(import.meta.url).pathname)) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    () => process.exit(0),
  );
}

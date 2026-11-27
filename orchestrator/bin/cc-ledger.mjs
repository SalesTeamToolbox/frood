#!/usr/bin/env node
// Claude Code transcript ledger (cc-pacing-v2 A1a). Counts-only, incremental scan of the token usage Claude Code
// writes to ~/.claude/projects/**/*.jsonl (one line per assistant message; a message id can repeat across lines,
// the last line wins). Nothing but counts is stored: no path, text, cwd, branch or session id.
//
// State <orchDir()>/cc-ledger.json (atomic write):
//   {v: 1, scanned_at, files: {<sha1(abs path)[:16]>: {size, mtime, offset}},
//    ids: {<message.id>: {b, f, in, out, cc, cr}}, buckets: {<YYYY-MM-DDTHH:M0Z>: {<family>: {in, out, cc, cr, w}}}}
// w = weight[family] × (in + 1.25·cc + 0.1·cr + 5·out); weights from usage-limits.json `cc.ledger.weights`.
//
//   node cc-ledger.mjs scan [--budget-ms N] [--json]
//   node cc-ledger.mjs summary [--hours N] [--json]
//   node cc-ledger.mjs fit [--json]        k = weekly % per weighted token, from cc-usage.jsonl snapshots (A1b)
//   node cc-ledger.mjs backtest [--json]   walk-forward check of k against the snapshots (A1b)
// Exit: 0 ok, 2 usage. Never prints transcript content.
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { orchDir, loadLimits } from "./usage.mjs";
import { readHistory } from "./cc-usage.mjs";

export const KEEP_MS = 8 * 7 * 24 * 3600 * 1000;
export const DEFAULT_WEIGHTS = Object.freeze({ fable: 2, opus: 1, sonnet: 0.6, haiku: 0.2, other: 0.6 });
export const DEFAULT_BUDGET_MS = 20000;
const MAX_DEPTH = 3;
const CHUNK = 1 << 20;
const FAMILIES = ["fable", "opus", "sonnet", "haiku"];
const USAGE_NEEDLE = Buffer.from('"usage"');

/** Transcript root: $ORCH_CC_PROJECTS, else $CLAUDE_CONFIG_DIR/projects, else ~/.claude/projects. */
export function projectsDir(env = process.env) {
  if (env.ORCH_CC_PROJECTS) return path.resolve(env.ORCH_CC_PROJECTS);
  if (env.CLAUDE_CONFIG_DIR) return path.resolve(env.CLAUDE_CONFIG_DIR, "projects");
  return path.join(os.homedir(), ".claude", "projects");
}

/** Lowercased model -> the first of fable/opus/sonnet/haiku it contains, else "other". */
export function familyOf(model) {
  const m = String(model ?? "").toLowerCase();
  return FAMILIES.find((f) => m.includes(f)) ?? "other";
}

const num = (v) => {
  const n = Number(v);
  return Number.isFinite(n) && n > 0 ? n : 0;
};

/** Weighted tokens of one usage record ({in,out,cc,cr} or the raw Claude usage keys). */
export function weighted(usage, fam, weights = DEFAULT_WEIGHTS) {
  const u = usage ?? {};
  const inp = num(u.in ?? u.input_tokens);
  const out = num(u.out ?? u.output_tokens);
  const cc = num(u.cc ?? u.cache_creation_input_tokens);
  const cr = num(u.cr ?? u.cache_read_input_tokens);
  const w = Number(weights?.[fam] ?? weights?.other ?? DEFAULT_WEIGHTS.other);
  return (Number.isFinite(w) ? w : 0) * (inp + 1.25 * cc + 0.1 * cr + 5 * out);
}

/** 10-minute UTC bucket `YYYY-MM-DDTHH:M0Z` of a timestamp, or null when it does not parse. */
export function bucketOf(ts) {
  if (typeof ts !== "string" && typeof ts !== "number") return null;
  const ms = typeof ts === "number" ? ts : Date.parse(ts);
  if (!Number.isFinite(ms)) return null;
  const d = new Date(ms);
  if (Number.isNaN(d.getTime())) return null;
  return d.toISOString().slice(0, 15) + "0Z";
}

/** Config weights (`cc.ledger.weights`) over the defaults; junk values ignored. */
export function loadWeights(limits) {
  let lim = limits;
  if (lim === undefined) {
    try { lim = loadLimits(); } catch { lim = {}; }
  }
  const cfg = lim?.cc?.ledger?.weights;
  const out = { ...DEFAULT_WEIGHTS };
  if (cfg && typeof cfg === "object") {
    for (const [k, v] of Object.entries(cfg)) {
      const n = Number(v);
      if (Number.isFinite(n) && n >= 0) out[k] = n;
    }
  }
  return out;
}

export const statePath = () => path.join(orchDir(), "cc-ledger.json");

export function emptyState() {
  return { v: 1, scanned_at: null, files: {}, ids: {}, buckets: {} };
}

export function loadState(file = statePath()) {
  try {
    const s = JSON.parse(fs.readFileSync(file, "utf8"));
    if (s && s.v === 1 && s.files && s.ids && s.buckets) {
      return { v: 1, scanned_at: s.scanned_at ?? null, files: s.files, ids: s.ids, buckets: s.buckets };
    }
  } catch { /* missing or corrupt: start over */ }
  return emptyState();
}

function writeFileAtomic(file, text) {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

export function saveState(state, file = statePath()) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const out = { v: 1, scanned_at: state.scanned_at, files: state.files, ids: state.ids, buckets: state.buckets };
  writeFileAtomic(file, JSON.stringify(out) + "\n");
}

export const fileKey = (abs) => crypto.createHash("sha1").update(abs).digest("hex").slice(0, 16);

/** *.jsonl files under root, directories up to depth 3 below it; symlinked dirs not followed. */
function listFiles(root) {
  const out = [];
  const walk = (dir, depth) => {
    let ents;
    try { ents = fs.readdirSync(dir, { withFileTypes: true }); } catch { return; }
    for (const e of ents) {
      const p = path.join(dir, e.name);
      if (e.isFile() && e.name.endsWith(".jsonl")) out.push(p);
      else if (e.isDirectory() && depth < MAX_DEPTH) walk(p, depth + 1);
    }
  };
  walk(root, 0);
  return out;
}

/** A counted line -> {id, b, f, in, out, cc, cr}, or null (skipped). */
export function parseLine(text) {
  let j;
  try { j = JSON.parse(text); } catch { return null; }
  const m = j?.message;
  if (!m || typeof m !== "object") return null;
  const u = m.usage;
  if (!u || typeof u !== "object" || Array.isArray(u)) return null;
  if (typeof m.id !== "string" || !m.id) return null;
  if (typeof m.model !== "string" || !m.model || m.model === "<synthetic>") return null;
  if (typeof j.timestamp !== "string") return null;
  const b = bucketOf(j.timestamp);
  if (!b) return null;
  return {
    id: m.id, b, f: familyOf(m.model),
    in: num(u.input_tokens), out: num(u.output_tokens),
    cc: num(u.cache_creation_input_tokens), cr: num(u.cache_read_input_tokens),
  };
}

function addTo(buckets, b, f, rec, sign) {
  const fams = (buckets[b] ??= {});
  const cell = (fams[f] ??= { in: 0, out: 0, cc: 0, cr: 0, w: 0 });
  for (const k of ["in", "out", "cc", "cr"]) cell[k] += sign * rec[k];
  if (cell.in <= 0 && cell.out <= 0 && cell.cc <= 0 && cell.cr <= 0) {
    delete fams[f];
    if (!Object.keys(fams).length) delete buckets[b];
  }
}

function ingest(state, rec) {
  const old = state.ids[rec.id];
  if (old) addTo(state.buckets, old.b, old.f, old, -1);
  addTo(state.buckets, rec.b, rec.f, rec, +1);
  state.ids[rec.id] = { b: rec.b, f: rec.f, in: rec.in, out: rec.out, cc: rec.cc, cr: rec.cr };
}

/** Drop ids and buckets older than KEEP_MS; recompute every bucket's w with the current weights. */
export function prune(state, now, weights) {
  const cut = bucketOf(now - KEEP_MS);
  for (const [id, r] of Object.entries(state.ids)) if (!(r.b >= cut)) delete state.ids[id];
  for (const [b, fams] of Object.entries(state.buckets)) {
    if (!(b >= cut)) { delete state.buckets[b]; continue; }
    for (const [f, c] of Object.entries(fams)) c.w = weighted(c, f, weights);
  }
}

/**
 * Incremental scan. opts: {dir, stateFile, budgetMs, now, weights, save}.
 * Returns {files, files_read, bytes_read, lines, counted, skipped, partial, scanned_at, ms}.
 */
export function scan(opts = {}) {
  const t0 = Date.now();
  const dir = opts.dir ?? projectsDir();
  const stateFile = opts.stateFile ?? statePath();
  const budgetMs = opts.budgetMs ?? DEFAULT_BUDGET_MS;
  const now = opts.now ?? Date.now();
  const weights = opts.weights ?? loadWeights();
  const state = opts.state ?? loadState(stateFile);
  const cutoff = now - KEEP_MS;
  const cutBucket = bucketOf(cutoff);
  const res = { files: 0, files_read: 0, bytes_read: 0, lines: 0, counted: 0, skipped: 0, errors: 0, partial: false };
  let any = false;
  // Budget 0 reads nothing; a positive budget always reads at least one line (progress guarantee).
  const expired = () => budgetMs <= 0 || (any && Date.now() - t0 >= budgetMs);

  const listed = [];
  for (const p of listFiles(dir)) {
    let st;
    try { st = fs.statSync(p); } catch { continue; }
    listed.push({ p, key: fileKey(p), size: st.size, mtime: st.mtimeMs });
  }
  res.files = listed.length;
  const seen = new Set(listed.map((x) => x.key));
  for (const k of Object.keys(state.files)) if (!seen.has(k)) delete state.files[k];
  listed.sort((a, b) => b.mtime - a.mtime);

  const buf = Buffer.allocUnsafe(CHUNK);
  for (const f of listed) {
    let ent = state.files[f.key];
    if (!ent) {
      if (f.mtime < cutoff) continue;
      ent = { size: 0, mtime: 0, offset: 0 };
    }
    if (f.size < ent.offset || f.mtime < ent.mtime) ent.offset = 0;
    if (f.size === ent.offset) { state.files[f.key] = { size: f.size, mtime: f.mtime, offset: ent.offset }; continue; }
    if (expired()) { res.partial = true; break; }
    // One unreadable file (open/read error) must not abort the scan: its stored entry stays as it was.
    let fd;
    try { fd = fs.openSync(f.p, "r"); } catch { res.errors++; continue; }
    res.files_read++;
    let offset = ent.offset;
    let carry = null;
    let stop = false;
    try {
      // A rewrite to a size >= offset: the byte before the offset is no longer the newline we stopped after.
      if (offset > 0) {
        const one = Buffer.alloc(1);
        if (fs.readSync(fd, one, 0, 1, offset - 1) !== 1 || one[0] !== 10) offset = 0;
      }
      let pos = offset;
      while (pos < f.size) {
        const n = fs.readSync(fd, buf, 0, Math.min(CHUNK, f.size - pos), pos);
        if (n <= 0) break;
        pos += n;
        let data = carry ? Buffer.concat([carry, buf.subarray(0, n)]) : buf.subarray(0, n);
        let start = 0;
        let nl;
        while ((nl = data.indexOf(10, start)) !== -1) {
          if (expired()) { res.partial = true; stop = true; break; }
          const line = data.subarray(start, nl);
          res.lines++;
          any = true;
          const rec = line.indexOf(USAGE_NEEDLE) === -1 ? null : parseLine(line.toString("utf8"));
          if (!rec) res.skipped++;
          else if (rec.b >= cutBucket) { ingest(state, rec); res.counted++; }
          const len = nl - start + 1;
          offset += len;
          res.bytes_read += len;
          start = nl + 1;
        }
        if (stop) break;
        carry = start < data.length ? Buffer.from(data.subarray(start)) : null;
      }
    } catch {
      res.errors++;
      continue;
    } finally {
      try { fs.closeSync(fd); } catch { /* already gone */ }
    }
    state.files[f.key] = { size: f.size, mtime: f.mtime, offset };
    if (stop) break;
  }

  prune(state, now, weights);
  state.scanned_at = new Date(now).toISOString();
  if (opts.save !== false) saveState(state, stateFile);
  return { ...res, scanned_at: state.scanned_at, ms: Date.now() - t0 };
}

/** Weighted tokens per family over buckets starting within the last `hours` hours, and the total. */
export function summary(state, hours = 24, now = Date.now()) {
  const since = bucketOf(now - hours * 3600 * 1000);
  const families = {};
  let total = 0;
  for (const [b, fams] of Object.entries(state?.buckets ?? {})) {
    if (!(b >= since)) continue;
    for (const [f, c] of Object.entries(fams)) {
      const w = Number(c.w) || 0;
      families[f] = (families[f] ?? 0) + w;
      total += w;
    }
  }
  return { hours, since, scanned_at: state?.scanned_at ?? null, families, total };
}

// ---- fit / backtest (A1b) ----------------------------------------------------------------------------------
export const FIT_DAYS = 14;
const FIT_MIN_PAIRS = 3;
const FIT_MIN_HOURS = 6;
const PAIR_MIN_H = 0.5;
const PAIR_MAX_H = 12;
const BACKTEST_MIN_H = 2;

/**
 * Snapshots -> [{t, pct, resets}] sorted by time; records without a parseable at / weekly.pct / resets_at dropped.
 * `resets` is weekly.resets_at rounded to the minute: snapshots carry sub-second jitter (15:59:59.8 vs 16:00:00.1),
 * so windows are compared the way cc-pace compares them.
 */
function normSnaps(snapshots) {
  const out = [];
  for (const s of snapshots ?? []) {
    const t = Date.parse(s?.at);
    const pct = Number(s?.weekly?.pct);
    const r = typeof s?.weekly?.resets_at === "string" ? Date.parse(s.weekly.resets_at) : NaN;
    if (!Number.isFinite(t) || s?.weekly?.pct == null || !Number.isFinite(pct) || !Number.isFinite(r)) continue;
    const resets = Math.round(r / 60e3);
    out.push({ t, pct, resets });
  }
  return out.sort((a, b) => a.t - b.t);
}

/**
 * Buckets -> a weight-sum function over [t1, t2). Each bucket's w is recomputed from its raw {in, out, cc, cr} with
 * `weights` (the stored w is ignored), so a weights change re-weights all history uniformly.
 */
function bucketIndex(buckets, weights) {
  const rows = [];
  for (const [b, fams] of Object.entries(buckets ?? {})) {
    const t = Date.parse(b);
    if (!Number.isFinite(t) || !fams || typeof fams !== "object") continue;
    const ws = {};
    for (const [f, c] of Object.entries(fams)) ws[f] = weighted(c, f, weights);
    rows.push({ t, ws });
  }
  rows.sort((a, b) => a.t - b.t);
  const lower = (x) => { // first index with rows[i].t >= x
    let lo = 0, hi = rows.length;
    while (lo < hi) { const mid = (lo + hi) >> 1; if (rows[mid].t < x) lo = mid + 1; else hi = mid; }
    return lo;
  };
  return (t1, t2) => {
    const fam = {};
    let w = 0;
    for (let i = lower(t1); i < rows.length && rows[i].t < t2; i++) {
      for (const [f, v] of Object.entries(rows[i].ws)) { fam[f] = (fam[f] ?? 0) + v; w += v; }
    }
    return { w, fam };
  };
}

/** Valid pairs: consecutive snapshots, same window, 0.5 h <= dt <= 12 h, dpct >= 0. */
function pairsOf(snaps, sumW) {
  const out = [];
  for (let i = 1; i < snaps.length; i++) {
    const a = snaps[i - 1], b = snaps[i];
    const h = (b.t - a.t) / 3600e3;
    const dpct = b.pct - a.pct;
    if (a.resets !== b.resets || h < PAIR_MIN_H || h > PAIR_MAX_H || dpct < 0) continue;
    const { w, fam } = sumW(a.t, b.t);
    out.push({ t1: a.t, t2: b.t, h, dpct, dw: w, fam });
  }
  return out;
}

/** Least squares through the origin over pairs ending in (now - 14 d, now]. */
function fitPairs(all, now) {
  const since = now - FIT_DAYS * 24 * 3600e3;
  const pairs = all.filter((p) => p.t2 <= now && p.t2 > since);
  let sxy = 0, sxx = 0, sh = 0;
  const famW = {};
  let totW = 0;
  for (const p of pairs) {
    sxy += p.dpct * p.dw; sxx += p.dw * p.dw; sh += p.h;
    for (const [f, v] of Object.entries(p.fam)) { famW[f] = (famW[f] ?? 0) + v; totW += v; }
  }
  const mix = {};
  if (totW > 0) for (const [f, v] of Object.entries(famW)) mix[f] = v / totW;
  const valid = pairs.length >= FIT_MIN_PAIRS && sh >= FIT_MIN_HOURS && totW > 0 && sxx > 0;
  if (!valid) return { k: null, rms: null, unmetered: null, pairs: pairs.length, hours: sh, mix };
  const k = sxy / sxx;
  let sr = 0, sr2 = 0;
  for (const p of pairs) { const r = p.dpct - k * p.dw; sr += r; sr2 += r * r; }
  return { k, rms: Math.sqrt(sr2 / pairs.length), unmetered: sr / sh, pairs: pairs.length, hours: sh, mix };
}

/**
 * Fit k (weekly percent per weighted token) from usage snapshots and ledger buckets.
 * opts: {now = Date.now(), weights = loadWeights()}. Returns {k|null, rms, unmetered (%/h, signed), pairs, hours, mix}.
 */
export function fit(snapshots, buckets, opts = {}) {
  const now = opts.now ?? Date.now();
  const sumW = bucketIndex(buckets, opts.weights ?? loadWeights());
  return fitPairs(pairsOf(normSnaps(snapshots), sumW), now);
}

/**
 * Walk-forward backtest: for each snapshot s_j, s_i = the latest earlier snapshot in the same window with
 * s_j.at - s_i.at >= 2 h; k is fitted only on pairs ending at or before s_i.at. Predict s_i.pct + k·Δw(s_i→s_j).
 * Returns {n, mae, max_err, under_predict (count of predictions below the actual)}; points without a valid k skip.
 */
export function backtest(snapshots, buckets, opts = {}) {
  const now = opts.now ?? Date.now();
  const snaps = normSnaps(snapshots).filter((s) => s.t <= now);
  const sumW = bucketIndex(buckets, opts.weights ?? loadWeights());
  const all = pairsOf(snaps, sumW);
  let n = 0, sum = 0, max = 0, under = 0;
  for (let j = 1; j < snaps.length; j++) {
    const sj = snaps[j];
    let si = null;
    for (let i = j - 1; i >= 0; i--) {
      if (snaps[i].resets !== sj.resets) break;
      if (sj.t - snaps[i].t >= BACKTEST_MIN_H * 3600e3) { si = snaps[i]; break; }
    }
    if (!si) continue;
    const { k } = fitPairs(all, si.t);
    if (k == null) continue;
    const pred = si.pct + k * sumW(si.t, sj.t).w;
    const err = pred - sj.pct;
    n++; sum += Math.abs(err); max = Math.max(max, Math.abs(err));
    if (err < -1e-9) under++;
  }
  return { n, mae: n ? sum / n : null, max_err: n ? max : null, under_predict: under };
}

const USAGE = "usage: cc-ledger.mjs scan [--budget-ms N] [--json] | summary [--hours N] [--json] | fit [--json] | backtest [--json]";

const fnum = (v, d) => {
  if (v == null) return "null";
  const s = v.toFixed(d);
  return Number(s) === 0 ? (0).toFixed(d) : s; // no "-0.000"
};
const fk = (k) => (k == null ? "null" : String(Number(k.toPrecision(4))));

export function fitLine(r) {
  const mix = Object.entries(r.mix).sort((a, b) => b[1] - a[1]).map(([f, s]) => `${f}:${s.toFixed(2)}`).join(",");
  return `fit: k=${fk(r.k)} pairs=${r.pairs} rms=${fnum(r.rms, 3)} unmetered=${fnum(r.unmetered, 3)}%/h mix=${mix}`;
}

export function backtestLine(r) {
  return `backtest: n=${r.n} mae=${fnum(r.mae, 3)} max_err=${fnum(r.max_err, 3)} under_predict=${r.under_predict}`;
}

const fmt = (n) => {
  const a = Math.abs(n);
  if (a >= 1e9) return `${(n / 1e9).toFixed(2)}G`;
  if (a >= 1e6) return `${(n / 1e6).toFixed(2)}M`;
  if (a >= 1e3) return `${(n / 1e3).toFixed(1)}k`;
  return `${Math.round(n)}`;
};

export function main(argv) {
  const [cmd, ...rest] = argv;
  const fail = (m) => { console.error(`cc-ledger: ${m}\n${USAGE}`); return 2; };
  const flags = { json: false };
  const valued = cmd === "scan" ? "--budget-ms" : cmd === "summary" ? "--hours" : cmd === "fit" || cmd === "backtest" ? "" : null;
  if (valued == null) return fail(cmd ? `unknown command: ${cmd}` : "missing command");
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === "--json") flags.json = true;
    else if (valued && a === valued) {
      const v = rest[++i];
      const n = Number(v);
      if (v == null || v === "" || !Number.isFinite(n) || n < 0 || (valued === "--hours" && n <= 0)) {
        return fail(`${a} needs a ${valued === "--hours" ? "positive" : "non-negative"} number`);
      }
      flags.value = n;
    } else return fail(`unknown flag: ${a}`);
  }
  if (cmd === "scan") {
    const r = scan({ budgetMs: flags.value ?? DEFAULT_BUDGET_MS });
    if (flags.json) console.log(JSON.stringify(r));
    else {
      const mb = (r.bytes_read / 1e6).toFixed(1);
      console.log(`ledger: ${r.counted} msgs, ${r.files_read}/${r.files} files, ${mb} MB in ${r.ms} ms${r.partial ? " partial" : ""}${r.errors ? ` ${r.errors} errors` : ""}`);
    }
    return 0;
  }
  if (cmd === "fit" || cmd === "backtest") {
    const buckets = loadState().buckets;
    const snaps = readHistory();
    const r = cmd === "fit" ? fit(snaps, buckets) : backtest(snaps, buckets);
    console.log(flags.json ? JSON.stringify(r) : cmd === "fit" ? fitLine(r) : backtestLine(r));
    return 0;
  }
  const s = summary(loadState(), flags.value ?? 24);
  if (flags.json) console.log(JSON.stringify(s));
  else {
    const parts = Object.entries(s.families).sort((a, b) => b[1] - a[1]).map(([f, w]) => `${f} ${fmt(w)}`);
    console.log(`ledger last ${s.hours} h: ${parts.length ? parts.join(", ") + ", " : ""}total ${fmt(s.total)} weighted tokens${s.scanned_at ? "" : " (never scanned)"}`);
  }
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}

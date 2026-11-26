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
// Exit: 0 ok, 2 usage. Never prints transcript content.
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { orchDir, loadLimits } from "./usage.mjs";

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
  const res = { files: 0, files_read: 0, bytes_read: 0, lines: 0, counted: 0, skipped: 0, partial: false };
  let any = false;
  const expired = () => any && Date.now() - t0 >= budgetMs;

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
  outer: for (const f of listed) {
    let ent = state.files[f.key];
    if (!ent) {
      if (f.mtime < cutoff) continue;
      ent = { size: 0, mtime: 0, offset: 0 };
    }
    if (f.size < ent.offset || f.mtime < ent.mtime) ent.offset = 0;
    if (f.size === ent.offset) { state.files[f.key] = { size: f.size, mtime: f.mtime, offset: ent.offset }; continue; }
    if (expired()) { res.partial = true; break; }
    let fd;
    try { fd = fs.openSync(f.p, "r"); } catch { continue; }
    res.files_read++;
    let offset = ent.offset;
    let pos = offset;
    let carry = null;
    try {
      while (pos < f.size) {
        const n = fs.readSync(fd, buf, 0, Math.min(CHUNK, f.size - pos), pos);
        if (n <= 0) break;
        pos += n;
        let data = carry ? Buffer.concat([carry, buf.subarray(0, n)]) : buf.subarray(0, n);
        let start = 0;
        let nl;
        while ((nl = data.indexOf(10, start)) !== -1) {
          if (expired()) {
            res.partial = true;
            state.files[f.key] = { size: f.size, mtime: f.mtime, offset };
            break outer;
          }
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
        carry = start < data.length ? Buffer.from(data.subarray(start)) : null;
      }
    } finally {
      fs.closeSync(fd);
    }
    state.files[f.key] = { size: f.size, mtime: f.mtime, offset };
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

const USAGE = "usage: cc-ledger.mjs scan [--budget-ms N] [--json] | summary [--hours N] [--json]";

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
  const valued = cmd === "scan" ? "--budget-ms" : cmd === "summary" ? "--hours" : null;
  if (!valued) return fail(cmd ? `unknown command: ${cmd}` : "missing command");
  for (let i = 0; i < rest.length; i++) {
    const a = rest[i];
    if (a === "--json") flags.json = true;
    else if (a === valued) {
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
      console.log(`ledger: ${r.counted} msgs, ${r.files_read}/${r.files} files, ${mb} MB in ${r.ms} ms${r.partial ? " partial" : ""}`);
    }
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

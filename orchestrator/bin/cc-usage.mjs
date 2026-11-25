#!/usr/bin/env node
// Claude Code plan-usage snapshots (cc-pacing M1). Two writers feed one store:
//   app        the desktop-app `get_usage` JSON, piped in by a session
//   statusline the sidecar ~/.claude/.harness-cc.json written by hooks/cross-harness-statusline.js
// Record: { at, source, five_hour:{pct,resets_at}|null, weekly:{pct,resets_at}, fable:{pct,resets_at}|null }, UTC ISO.
// Store: <orchDir()>/cc-usage.json (latest, newest `at` wins) + cc-usage.jsonl (history, pruned to 8 weeks).
//
//   node cc-usage.mjs snapshot --from-app <file|->
//   node cc-usage.mjs snapshot --from-statusline [path]
//   node cc-usage.mjs latest [--json]
// Exit: 0 ok (a stale snapshot that loses to a newer one is still 0), 2 bad input/usage; files untouched on 2.
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { orchDir } from "./usage.mjs";

const HISTORY_MS = 8 * 7 * 24 * 3600 * 1000;

const iso = (v) => {
  if (v == null || v === "") return null;
  // Numbers under 1e12 are epoch seconds (statusline); larger are milliseconds.
  const d = typeof v === "number" ? new Date(v < 1e12 ? v * 1000 : v) : new Date(v);
  return Number.isNaN(d.getTime()) ? null : d.toISOString();
};
const win = (pct, resets) => {
  const n = Number(pct);
  if (pct == null || pct === "" || !Number.isFinite(n)) return null;
  return { pct: n, resets_at: iso(resets) };
};

/** Desktop-app get_usage JSON -> record, or null when there is no weekly window. */
export function normalizeApp(json, now = Date.now()) {
  const list = Array.isArray(json) ? json : json?.windows ?? json?.limits ?? json?.usage ?? [];
  if (!Array.isArray(list)) return null;
  const find = (label) => {
    const w = list.find((x) => typeof x?.label === "string" && x.label.trim() === label);
    return w ? win(w.percentUsed, w.resetsAt) : null;
  };
  const weekly = find("Weekly · all models");
  if (!weekly) return null;
  return {
    at: new Date(now).toISOString(),
    source: "app",
    five_hour: find("5-hour limit"),
    weekly,
    fable: find("Weekly · Fable"),
  };
}

/** Statusline sidecar JSON -> record, or null when there is no seven_day window. */
export function normalizeStatusline(json, fallbackAtMs = Date.now()) {
  const rl = json?.rate_limits;
  if (!rl || typeof rl !== "object") return null;
  const w = (x) => win(x?.used_percentage, x?.resets_at);
  const weekly = w(rl.seven_day);
  if (!weekly) return null;
  const fableKey = Object.keys(rl).find((k) => /fable/i.test(k));
  return {
    at: new Date(Number.isFinite(json.saved_at) ? json.saved_at : fallbackAtMs).toISOString(),
    source: "statusline",
    five_hour: w(rl.five_hour),
    weekly,
    fable: fableKey ? w(rl[fableKey]) : null,
  };
}

const latestPath = () => path.join(orchDir(), "cc-usage.json");
const historyPath = () => path.join(orchDir(), "cc-usage.jsonl");

function writeFileAtomic(file, text) {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

export function readLatest() {
  try { return JSON.parse(fs.readFileSync(latestPath(), "utf8")); } catch { return null; }
}

export function readHistory() {
  try {
    return fs.readFileSync(historyPath(), "utf8").split("\n").filter(Boolean)
      .map((l) => { try { return JSON.parse(l); } catch { return null; } }).filter(Boolean);
  } catch { return []; }
}

/** Append to history (pruned past 8 weeks) and replace latest when this record is the newest. Returns "stored" | "older". */
export function store(record, now = Date.now()) {
  fs.mkdirSync(orchDir(), { recursive: true });
  const cutoff = now - HISTORY_MS;
  const hist = readHistory().filter((r) => Date.parse(r.at) >= cutoff);
  const dup = hist.some((r) => r.at === record.at && r.source === record.source);
  if (!dup && Date.parse(record.at) >= cutoff) hist.push(record);
  hist.sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  writeFileAtomic(historyPath(), hist.map((r) => JSON.stringify(r)).join("\n") + (hist.length ? "\n" : ""));
  const cur = readLatest();
  if (cur && Date.parse(cur.at) > Date.parse(record.at)) return "older";
  writeFileAtomic(latestPath(), JSON.stringify(record, null, 2) + "\n");
  return "stored";
}

/** Quiet statusline import for callers that must not print (desk-check tick). Returns store()'s result or null. */
export function importStatusline(p = path.join(os.homedir(), ".claude", ".harness-cc.json")) {
  const rec = normalizeStatusline(JSON.parse(fs.readFileSync(p, "utf8")), fs.statSync(p).mtimeMs);
  return rec ? store(rec) : null;
}

function readInput(src) {
  return src === "-" ? fs.readFileSync(0, "utf8") : fs.readFileSync(src, "utf8");
}

export function main(argv) {
  const [cmd, ...rest] = argv;
  const fail = (m) => { console.error(`cc-usage: ${m}`); return 2; };
  if (cmd === "latest") {
    const r = readLatest();
    if (!r) { console.log("no snapshot"); return 0; }
    if (rest.includes("--json")) console.log(JSON.stringify(r));
    else console.log(`${r.at} (${r.source}) 5h ${r.five_hour?.pct ?? "n/a"}% weekly ${r.weekly.pct}% (resets ${r.weekly.resets_at}) fable ${r.fable?.pct ?? "n/a"}%`);
    return 0;
  }
  if (cmd !== "snapshot") return fail("usage: snapshot --from-app <file|-> | snapshot --from-statusline [path] | latest [--json]");
  let rec;
  try {
    if (rest[0] === "--from-app") {
      if (!rest[1]) return fail("--from-app needs <file|->");
      rec = normalizeApp(JSON.parse(readInput(rest[1])));
    } else if (rest[0] === "--from-statusline") {
      const p = rest[1] || path.join(os.homedir(), ".claude", ".harness-cc.json");
      const json = JSON.parse(fs.readFileSync(p, "utf8"));
      rec = normalizeStatusline(json, fs.statSync(p).mtimeMs);
    } else return fail("snapshot needs --from-app or --from-statusline");
  } catch (e) {
    return fail(`cannot read input: ${e.message}`);
  }
  if (!rec) return fail("no weekly window in input");
  try {
    console.log(store(rec));
  } catch (e) {
    return fail(e.message);
  }
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}

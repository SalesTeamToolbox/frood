#!/usr/bin/env node
// Claude Code weekly pace model (cc-pacing M2). Pure model over the M1 snapshots (cc-usage.mjs) + a status CLI.
// States, first match wins: off -> unknown -> over -> on (E < 12) -> under (hysteresis) -> on.
// All numbers are percentage points of the weekly limit; H = hours to the weekly reset, E = 168 - H.
//
//   node cc-pace.mjs [status] [--json]
// `status` prints ONE line (<= 100 chars, no leading "pace": workers-view prefixes it) and exits 0 for every
// state. Last state (hysteresis only) lives in <orchDir()>/cc-pace-state.json, rewritten atomically on change.
// Env: ORCH_NO_PACE=1 -> off. Exit 2 on unknown commands/flags. No network, no child processes.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { orchDir, loadLimits } from "./usage.mjs";
import { readLatest, readHistory } from "./cc-usage.mjs";

const HOUR = 3600 * 1000;
const WEEK_H = 168;
export const DEFAULTS = Object.freeze({ enabled: true, weekly_reserve_pct: 20, reserve_floor_hours: 12, stale_hours: 2, margin: 5 });

/** Defaults overlaid with a (possibly partial or junk) cc config; non-numeric numbers fall back to the default. */
export function withDefaults(cc) {
  const out = { ...DEFAULTS };
  if (cc && typeof cc === "object") {
    if (typeof cc.enabled === "boolean") out.enabled = cc.enabled;
    for (const k of ["weekly_reserve_pct", "reserve_floor_hours", "stale_hours", "margin"]) {
      if (Number.isFinite(cc[k])) out[k] = cc[k];
    }
  }
  return out;
}

const clamp = (x, lo, hi) => Math.min(hi, Math.max(lo, x));

/** Weekly reserve in points: weekly_reserve_pct at week start, falling linearly to 0 at reserve_floor_hours. */
export function reserve(H, cfg = DEFAULTS) {
  const c = withDefaults(cfg);
  const span = WEEK_H - c.reserve_floor_hours;
  if (!(span > 0)) return 0;
  return c.weekly_reserve_pct * clamp((H - c.reserve_floor_hours) / span, 0, 1);
}

/** Weekly pct expected at the reset: current + rate (%/h) over the H hours left + margin. */
export function projected(weeklyPct, rate, H, margin = DEFAULTS.margin) {
  return weeklyPct + rate * H + margin;
}

const ms = (v) => (v == null ? NaN : Date.parse(v));
const usable = (s) => s && typeof s === "object" && Number.isFinite(ms(s.at));

function blank(state, reason, at = null, extra = {}) {
  return { state, reason, weekly: null, projected: null, reserve: null, rate: null, hours_to_reset: null, five_hour: null, fable: null, at, ...extra };
}

/**
 * Pure pace state. snapshots: M1 records (any order, duplicates fine); newest `at` is current.
 * now: ms. prev: last state ("under" | {state:"under"} | null) for hysteresis.
 */
export function paceState(snapshots, cfg, now, prev = null) {
  const c = withDefaults(cfg);
  const list = (Array.isArray(snapshots) ? snapshots : []).filter(usable).sort((a, b) => ms(a.at) - ms(b.at));
  const cur = list.length ? list[list.length - 1] : null;
  if (!c.enabled) return blank("off", "disabled", cur?.at ?? null);
  if (!cur) return blank("unknown", "no snapshot");
  const ageH = (now - ms(cur.at)) / HOUR;
  if (ageH > c.stale_hours) return blank("unknown", `stale ${Math.floor(ageH)}h`, cur.at, { age_hours: ageH });
  const wk = cur.weekly;
  if (!wk || typeof wk !== "object" || !Number.isFinite(wk.pct)) return blank("unknown", "no weekly window", cur.at);
  const resetMs = ms(wk.resets_at);
  if (!Number.isFinite(resetMs)) return blank("unknown", "weekly reset missing", cur.at);
  if (resetMs <= now) return blank("unknown", "weekly reset past", cur.at);

  const H = (resetMs - now) / HOUR;
  const E = WEEK_H - H;
  const avg = wk.pct / Math.max(E, 1 / 60); // E <= 0 only on a bogus reset > 168 h away: keep it finite
  let recent = null;
  const win = list.filter((s) => ms(s.at) >= now - 24 * HOUR && ms(s.at) <= now
    && s.weekly && Number.isFinite(s.weekly.pct) && s.weekly.resets_at === wk.resets_at);
  if (win.length >= 2) {
    const a = win[0];
    const b = win[win.length - 1];
    const spanH = (ms(b.at) - ms(a.at)) / HOUR;
    if (spanH >= 4) recent = (b.weekly.pct - a.weekly.pct) / spanH;
  }
  const rate = Math.max(avg, recent ?? avg);
  const proj = projected(wk.pct, rate, H, c.margin);
  const rsv = reserve(H, c);
  const fh = cur.five_hour;
  const fhResets = ms(fh?.resets_at);
  const five = !fh || !Number.isFinite(fh.pct) || (Number.isFinite(fhResets) && fhResets < now) ? 0 : fh.pct;
  const fable = cur.fable && Number.isFinite(cur.fable.pct) ? { pct: cur.fable.pct, state: cur.fable.pct >= 85 ? "over" : "ok" } : null;

  const base = { weekly: wk.pct, projected: proj, reserve: rsv, rate, avg, recent, hours_to_reset: H, five_hour: five, fable, at: cur.at, weekly_resets_at: wk.resets_at };
  const out = (state, reason) => ({ state, reason, ...base });
  if (five >= 85) return out("over", `5h ${five}% >= 85`);
  if (wk.pct >= 100 - rsv) return out("over", `weekly ${wk.pct}% >= ${(100 - rsv).toFixed(1)} (100 - reserve)`);
  if (proj >= 95) return out("over", `projected ${proj.toFixed(1)} >= 95`);
  if (E < 12) return out("on", `early week (E ${E.toFixed(1)}h < 12)`);
  const prevState = typeof prev === "string" ? prev : prev?.state ?? null;
  const ceiling = prevState === "under" ? 85 : 80;
  if (proj <= ceiling && five < 60) return out("under", `projected ${proj.toFixed(1)} <= ${ceiling}`);
  return out("on", `projected ${proj.toFixed(1)}`);
}

const DAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];
const pad2 = (n) => String(n).padStart(2, "0");

/** One status line (<= 100 chars). Weekday/hour of the weekly reset are local time (TZ). */
export function statusLine(r) {
  let s;
  if (r.state === "off") s = "OFF";
  else if (r.state === "unknown") s = `UNKNOWN (${r.reason})`;
  else {
    const d = new Date(r.weekly_resets_at);
    const at = Number.isNaN(d.getTime()) ? "" : ` @${DAYS[d.getDay()]}${pad2(d.getHours())}`;
    const fable = r.fable ? `${Math.round(r.fable.pct)}%` : "n/a";
    s = `${r.state.toUpperCase()} wk ${Math.round(r.weekly)}%→${Math.round(r.projected)}%${at} rsv ${Math.round(r.reserve)}% 5h ${Math.round(r.five_hour)}% fable ${fable}`;
  }
  return s.replace(/\s+/g, " ").slice(0, 100);
}

const statePath = () => path.join(orchDir(), "cc-pace-state.json");

export function readState() {
  try {
    const j = JSON.parse(fs.readFileSync(statePath(), "utf8"));
    return j && typeof j === "object" && typeof j.state === "string" ? j : null;
  } catch { return null; }
}

function writeFileAtomic(file, text) {
  const tmp = `${file}.${process.pid}.tmp`;
  fs.writeFileSync(tmp, text);
  fs.renameSync(tmp, file);
}

const USAGE = "usage: cc-pace.mjs [status] [--json]";

export function main(argv) {
  const args = [...argv];
  const json = args.includes("--json");
  const rest = args.filter((a) => a !== "--json");
  if (rest.length > 1 || (rest.length === 1 && rest[0] !== "status")) {
    console.error(`cc-pace: unknown argument ${rest.find((a) => a !== "status") ?? rest[1]}\n${USAGE}`);
    return 2;
  }
  let cc;
  try { cc = loadLimits().cc; } catch { cc = undefined; }
  const cfg = withDefaults(cc);
  if (process.env.ORCH_NO_PACE === "1") cfg.enabled = false;
  const snaps = [...readHistory(), readLatest()].filter(Boolean);
  const prev = readState();
  const now = Date.now();
  const r = paceState(snaps, cfg, now, prev);
  if (r.state !== prev?.state) {
    try {
      fs.mkdirSync(orchDir(), { recursive: true });
      writeFileAtomic(statePath(), JSON.stringify({ state: r.state, at: r.at, updated: new Date(now).toISOString() }) + "\n");
    } catch { /* hysteresis memory only: never fail the status line over it */ }
  }
  console.log(json ? JSON.stringify(r) : statusLine(r));
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exit(main(process.argv.slice(2)));
}

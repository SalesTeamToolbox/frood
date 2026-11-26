#!/usr/bin/env node
// Claude Code weekly pace model (cc-pacing M2). Pure model over the M1 snapshots (cc-usage.mjs) + a status CLI.
// States, first match wins: off -> unknown -> over -> on (E < 12) -> under (hysteresis) -> on.
// All numbers are percentage points of the weekly limit; H = hours to the weekly reset, E = 168 - H.
//
//   node cc-pace.mjs [status] [--json]
// `status` prints ONE line (<= 100 chars, no leading "pace": workers-view prefixes it) and exits 0 for every
// state. Last state (hysteresis only) lives in <orchDir()>/cc-pace-state.json, rewritten atomically on change.
// Env: ORCH_NO_PACE=1 -> off. Exit 2 on unknown commands/flags. No network, no child processes.
//
//   node cc-pace.mjs advise [--json] [--notify]   reset advice (M5); advise only, Frood never presses a reset
//   node cc-pace.mjs reset-used full|fable        the owner pressed one: decrement usage-limits.json cc.resets + ack
// Advisor state (once-a-day notify memory per advice id, reset acks) lives in <orchDir()>/cc-advise-state.json.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { orchDir, loadLimits } from "./usage.mjs";
import { readLatest, readHistory } from "./cc-usage.mjs";
import { listStreams } from "./handoff.mjs";
import { shouldNotify, notifyNow } from "./session-pressure.mjs";

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

// ---- reset advisor (cc-pacing M5) ------------------------------------------------------------------------
// Advise only: Frood never presses a reset. The owner presses it on the usage page, then runs
// `cc-pace reset-used full|fable`, which decrements the count in usage-limits.json and acks any usage drop.

const DAY = 24 * HOUR;
const WEEK = WEEK_H * HOUR;
const MINUTE = 60 * 1000;
const DROP_POINTS = 20;
const ADVISE_NOTIFY_MS = DAY;
const ACKS_KEPT = 20;
const KINDS = ["full", "fable"];

const roundMin = (t) => Math.round(t / MINUTE) * MINUTE;
const fin = (x) => Number.isFinite(x);

/** "Thu Dec 10 08:00 PST": the owner's clock, whatever TZ the process runs in. */
export function laTime(t) {
  const parts = Object.fromEntries(new Intl.DateTimeFormat("en-US", {
    timeZone: "America/Los_Angeles", weekday: "short", month: "short", day: "numeric",
    hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZoneName: "short",
  }).formatToParts(new Date(t)).map((p) => [p.type, p.value]));
  return `${parts.weekday} ${parts.month} ${parts.day} ${parts.hour}:${parts.minute} ${parts.timeZoneName}`;
}

/**
 * The deadline that matters for a reset expiring at expiresAtMs: the last weekly reset W <= expiry when the
 * expiry falls less than 24 h after it (a press after W gives back under a day), else the expiry itself.
 * weeklyResetMs is any weekly reset time (whole weeks are added or removed); non-finite -> the expiry.
 */
export function effectiveDeadline(expiresAtMs, weeklyResetMs) {
  if (!fin(expiresAtMs)) return NaN;
  if (!fin(weeklyResetMs)) return expiresAtMs;
  const r = roundMin(weeklyResetMs);
  const W = r + Math.floor((expiresAtMs - r) / WEEK) * WEEK;
  return expiresAtMs - W < DAY ? W : expiresAtMs;
}

/** Valid reset entries from config (`loadLimits().cc.resets`); junk entries are skipped. */
export function parseResets(resets) {
  if (!Array.isArray(resets)) return [];
  const out = [];
  for (const e of resets) {
    if (!e || typeof e !== "object" || !KINDS.includes(e.kind) || !fin(e.count)) continue;
    const exp = ms(e.expires_at);
    if (!fin(exp)) continue;
    out.push({ kind: e.kind, count: e.count, expires_at: e.expires_at, expiresMs: exp });
  }
  return out;
}

const weeklyResetOf = (s) => (s?.weekly && typeof s.weekly === "object" ? ms(s.weekly.resets_at) : NaN);

/** The first fall of more than 20 points within one weekly window, scanning forward; restarts after each drop. */
export function detectDrop(list, windowMs) {
  if (!fin(windowMs)) return null;
  const win = list.filter((s) => fin(s.weekly?.pct) && roundMin(weeklyResetOf(s)) === windowMs);
  let maxE = -Infinity;
  let drop = null;
  for (const s of win) {
    if (maxE - s.weekly.pct > DROP_POINTS) {
      drop = { from: maxE, to: s.weekly.pct, at: s.at };
      maxE = s.weekly.pct; // a new baseline: later low snapshots of the same press are not a second drop
    } else maxE = Math.max(maxE, s.weekly.pct);
  }
  return drop;
}

const plural = (n, one, many) => (n === 1 ? one : `${n} ${many}`);
const cap = (t) => t.replace(/\s+/g, " ").slice(0, 100);
const hoursLeft = (d) => (d >= 2 * DAY ? `${Math.floor(d / DAY)} days left` : `${Math.max(1, Math.round(d / HOUR))} h left`);

/**
 * Pure reset advice. snapshots: M1 records (newest `at` is current); resets: config entries; now: ms;
 * activeTickets: board tickets queued or working; acks: [{kind, at}] from reset-used.
 * Returns {advice: [{id, kind, level, text}], paused, drop}.
 */
export function adviseState({ snapshots, resets, now, activeTickets = 0, acks = [] } = {}) {
  const list = (Array.isArray(snapshots) ? snapshots : []).filter(usable).sort((a, b) => ms(a.at) - ms(b.at));
  const cur = list.length ? list[list.length - 1] : null;
  const withWeekly = list.filter((s) => fin(weeklyResetOf(s)));
  const ref = withWeekly.length ? withWeekly[withWeekly.length - 1] : null;
  const weeklyMs = ref ? roundMin(weeklyResetOf(ref)) : NaN;

  const wk = cur?.weekly;
  const curResetMs = roundMin(weeklyResetOf(cur));
  const fresh = Boolean(cur) && (now - ms(cur.at)) / HOUR <= DEFAULTS.stale_hours
    && wk && typeof wk === "object" && fin(wk.pct) && fin(curResetMs) && curResetMs > now;

  const drop = detectDrop(list, weeklyMs);
  const ackList = Array.isArray(acks) ? acks : [];
  const acked = drop != null && ackList.some((a) => fin(ms(a?.at)) && ms(a.at) >= ms(drop.at));
  const paused = drop != null && !acked;

  const advice = [];
  const live = parseResets(resets).filter((e) => e.count > 0 && now < e.expiresMs);
  const deadlines = new Map();
  for (const e of live) {
    const deadline = effectiveDeadline(e.expiresMs, weeklyMs);
    if (!deadlines.has(e.kind)) deadlines.set(e.kind, deadline);
    const left = deadline - now;
    const what = e.count === 1 ? `the ${e.kind} reset` : `the ${e.count} ${e.kind} resets`;
    const by = laTime(deadline);
    let item = null;
    if (left <= 0) {
      item = { id: `expiry-${e.kind}-late`, level: "critical",
        text: `Decide on ${what}: it expires ${laTime(e.expiresMs)}; pressing now gives back little` };
    } else if (left <= DAY) {
      item = { id: `expiry-${e.kind}-24h`, level: "critical", text: `Press ${what} before ${by} or lose it (${hoursLeft(left)})` };
    } else if (left <= 3 * DAY) {
      item = { id: `expiry-${e.kind}-72h`, level: "warn", text: `Plan to press ${what} before ${by} (${hoursLeft(left)})` };
    } else if (left <= 14 * DAY) {
      item = { id: `expiry-${e.kind}-14d`, level: "warn", text: `Use ${what} before ${by} (${hoursLeft(left)})` };
    }
    if (item) advice.push({ id: item.id, kind: e.kind, level: item.level, text: cap(item.text) });
  }

  if (fresh) {
    const H = (curResetMs - now) / HOUR;
    if (deadlines.has("full") && !paused) {
      const left = deadlines.get("full") - now;
      let why = null;
      if (wk.pct >= 90 && H >= 36) why = `weekly ${Math.round(wk.pct)}% with ${Math.round(H)} h to the weekly reset`;
      else if (left > 0 && left <= DAY && wk.pct >= 50) why = `weekly ${Math.round(wk.pct)}%, best before ${laTime(deadlines.get("full"))}`;
      if (why) advice.push({ id: "press-full", kind: "full", level: "critical", text: cap(`Press the full reset now: ${why}`) });
    }
    if (deadlines.has("fable") && activeTickets > 0) {
      const fable = cur.fable && fin(cur.fable.pct) ? cur.fable.pct : null;
      const five = cur.five_hour && fin(cur.five_hour.pct) ? cur.five_hour.pct : null;
      const fiveLeft = ms(cur.five_hour?.resets_at) - now;
      let why = null;
      if (fable != null && fable >= 85) why = `fable ${Math.round(fable)}%`;
      else if (five != null && five >= 90 && fin(fiveLeft) && fiveLeft > 2 * HOUR) why = `5h ${Math.round(five)}% with ${Math.round(fiveLeft / HOUR)} h to its reset`;
      if (why) {
        advice.push({ id: "press-fable", kind: "fable", level: "warn",
          text: cap(`Press a fable reset now: ${why}, ${plural(activeTickets, "1 ticket", "tickets")} active`) });
      }
    }
  }

  if (paused) {
    advice.push({ id: "ask-reset-drop", kind: "full", level: "warn",
      text: cap(`Weekly fell ${Math.round(drop.from)}%→${Math.round(drop.to)}%: if you pressed a reset, run cc-pace reset-used full|fable`) });
  }
  return { advice, paused, drop };
}

/** Advice items due a notification now: once per id per 24 h, or at once when the level rises under that id. */
export function dueNotifications(advice, notifyState, now) {
  const st = notifyState && typeof notifyState === "object" ? notifyState : {};
  return (Array.isArray(advice) ? advice : []).filter((item) => {
    const prev = st[item.id] && typeof st[item.id] === "object" ? st[item.id] : {};
    return shouldNotify({ lastLevel: prev.lastLevel, lastNotifyMs: prev.lastNotifyMs }, now, item.level, ADVISE_NOTIFY_MS).notify;
  });
}

const adviseStatePath = () => path.join(orchDir(), "cc-advise-state.json");
const limitsPath = () => path.join(orchDir(), "usage-limits.json");

export function readAdviseState() {
  try {
    const j = JSON.parse(fs.readFileSync(adviseStatePath(), "utf8"));
    return j && typeof j === "object" && !Array.isArray(j) ? j : {};
  } catch { return {}; }
}

function writeAdviseState(st) {
  fs.mkdirSync(orchDir(), { recursive: true });
  writeFileAtomic(adviseStatePath(), JSON.stringify(st, null, 2) + "\n");
}

/** Board tickets in `queued` or `working`, read straight from each stream repo's board. No children, no network. */
export function activeTickets(now = Date.now()) {
  let streams = [];
  try { streams = listStreams(now); } catch { return 0; }
  const repos = [...new Set(streams.map((s) => s?.repo).filter((r) => typeof r === "string" && r))];
  let n = 0;
  for (const repo of repos) {
    const dir = path.join(repo, ".opencode", "board", "tickets");
    let files = [];
    try { files = fs.readdirSync(dir); } catch { continue; }
    for (const f of files) {
      if (!f.endsWith(".json")) continue;
      try {
        const t = JSON.parse(fs.readFileSync(path.join(dir, f), "utf8"));
        if (t && (t.stage === "queued" || t.stage === "working")) n++;
      } catch { /* unreadable ticket counts 0 */ }
    }
  }
  return n;
}

function adviseInputs(now, deps = {}) {
  let cc;
  try { cc = loadLimits().cc; } catch { cc = undefined; }
  const snapshots = [...readHistory(), readLatest()].filter(Boolean);
  const count = deps.activeTickets ?? activeTickets;
  let active = 0;
  try { active = Number(count(now)) || 0; } catch { active = 0; }
  const st = readAdviseState();
  return { input: { snapshots, resets: cc?.resets, now, activeTickets: active, acks: Array.isArray(st.acks) ? st.acks : [] }, st };
}

/**
 * One advisor tick: compute advice, send due notifications (notifyNow honours ORCH_NO_NOTIFY), record every
 * advice id's level (lastNotifyMs only when sent) atomically. Prints nothing; never throws (null on failure).
 */
export function adviseTick(now = Date.now(), deps = {}) {
  try {
    const { input, st } = adviseInputs(now, deps);
    const r = adviseState(input);
    const send = deps.notify ?? notifyNow;
    const due = new Set(dueNotifications(r.advice, st, now).map((a) => a.id));
    for (const item of r.advice) {
      const prev = st[item.id] && typeof st[item.id] === "object" ? st[item.id] : {};
      let sent = false;
      if (due.has(item.id)) {
        try { send(item.level, "Claude reset advice", item.text); sent = true; } catch { /* best effort */ }
      }
      st[item.id] = { lastLevel: item.level, lastNotifyMs: sent ? now : prev.lastNotifyMs ?? null };
    }
    writeAdviseState(st);
    return r;
  } catch {
    return null;
  }
}

function adviseMain(args) {
  let json = false, notify = false;
  for (const a of args) {
    if (a === "--json") json = true;
    else if (a === "--notify") notify = true;
    else {
      console.error(`cc-pace: unknown argument ${a}\nusage: cc-pace.mjs advise [--json] [--notify]`);
      return 2;
    }
  }
  const now = Date.now();
  let r = null;
  if (notify) r = adviseTick(now);
  if (!r) {
    try { r = adviseState(adviseInputs(now).input); } catch { r = { advice: [], paused: false, drop: null }; }
  }
  if (json) console.log(JSON.stringify(r));
  else if (!r.advice.length) console.log("no reset advice");
  else for (const a of r.advice) console.log(`You: ${a.text}`);
  return 0;
}

function resetUsedMain(args, now = Date.now()) {
  const fail = (m) => { console.error(`cc-pace reset-used: ${m}\nusage: cc-pace.mjs reset-used full|fable`); return 2; };
  if (args.length !== 1 || !KINDS.includes(args[0])) return fail(`kind must be full or fable`);
  const kind = args[0];
  let j;
  try { j = JSON.parse(fs.readFileSync(limitsPath(), "utf8")); } catch (e) { return fail(`cannot read usage-limits.json: ${e.message}`); }
  const resets = j && typeof j === "object" && j.cc && typeof j.cc === "object" ? j.cc.resets : null;
  const entry = Array.isArray(resets) ? resets.find((e) => e && typeof e === "object" && e.kind === kind && fin(e.count)) : null;
  if (!entry) return fail(`no ${kind} reset in usage-limits.json cc.resets`);
  if (entry.count <= 0) return fail(`no ${kind} resets left (count ${entry.count})`);
  entry.count -= 1;
  try { writeFileAtomic(limitsPath(), JSON.stringify(j, null, 2) + "\n"); } catch (e) { return fail(e.message); }
  try {
    const st = readAdviseState();
    st.acks = [...(Array.isArray(st.acks) ? st.acks : []), { kind, at: new Date(now).toISOString() }].slice(-ACKS_KEPT);
    writeAdviseState(st);
  } catch { /* the count is the record; the ack only silences the drop question */ }
  console.log(`${kind} resets left: ${entry.count}`);
  return 0;
}

const USAGE = "usage: cc-pace.mjs [status] [--json] | advise [--json] [--notify] | reset-used full|fable";

export function main(argv) {
  if (argv[0] === "advise") return adviseMain(argv.slice(1));
  if (argv[0] === "reset-used") return resetUsedMain(argv.slice(1));
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

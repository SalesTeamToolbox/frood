// Go subscription pace model (go-pacing G4a). Pure functions over the G2 ledger (go_v2 shape) and the
// G3 snapshot shape; no file, network, env or clock access — every input is a parameter. G4b adds the CLI
// and receipts; G5b wires routing. Nothing calls this yet.
//
//   goConfig(limits) overlays the Config table defaults on a parsed usage-limits.json (missing/junk `go`
//   gives every default; a wrong type or non-finite number falls back to its default).
//   weekBounds(now) is the Monday-00:00-UTC week containing now; periodBounds(anchor, now) steps calendar
//   months from the anchor (day clamped to each month's last day); periodFromReset(resetMs) is the month
//   before a snapshot reset; fiveHourWindow(times, now) is the fixed 5 h window containing now (a window
//   opens at the first used time after the previous one closed); sumUsd(rows, from, to) sums window spend.
//   reserve(H, span, cfg) is the over-ceiling reserve in cap-points, linear from reserve_pct to 0.
//   goPaceState({cfg, ledger, snapshots, health, now, prev, noPace}) is the state (first match wins):
//   off -> unknown -> over (go quota mark) -> over (5h burst) -> over (reserve) -> on (early period)
//   -> over (projected) -> under (hysteresis) -> on.
//   Result numbers are rounded to 1 decimal, except `rate` ($/h, kept exact: 0.025 would round to 0).
//   statusLine(r) is one line (<= 100 chars). goTail(role, chain, go, mode, {agentModel, roles, session})
//   orders a role chain's tail by Go state (shadow records would_chain instead). Never mutates its input.

export const OVER = 95;
export const OVER_EXIT = 90;
export const UNDER = 80;
export const UNDER_HYST = 85;
export const LEDGER_UNDER = 70;
export const LEDGER_UNDER_HYST = 75;
export const BURST_OVER = 85;
export const BURST_UNDER_MAX = 60;
export const EARLY_H = 24;
export const SPAN_WK_H = 168;
export const DEFAULT_ROLES = Object.freeze(["worker", "worker-strong"]);

const HOUR = 3600 * 1000;
const DAY = 24 * HOUR;
const WEEK = 7 * DAY;
const FIVE_H = 5 * HOUR;

// Config table defaults. monthly_usd falls back to top-level go_monthly_usd, else 60.
export const GO_DEFAULTS = Object.freeze({
  monthly_usd: 60,
  period_anchor: null,
  pace: Object.freeze({
    enabled: true,
    mode: "shadow",
    margin: 5,
    external_margin_pct: 10,
    ledger_under: true,
    reserve_pct: 20,
    reserve_floor_hours: 12,
    stale_hours: 2,
    recent_hours: 24,
  }),
  snapshot: Object.freeze({ min_interval_min: 15 }),
});

const numOr = (v, d) => (Number.isFinite(v) ? v : d);

/** Defaults overlaid with a (possibly partial or junk) parsed usage-limits.json. Never throws. */
export function goConfig(limits) {
  const d = GO_DEFAULTS;
  const top = limits && typeof limits === "object" ? limits : null;
  const go = top && top.go && typeof top.go === "object" && !Array.isArray(top.go) ? top.go : null;
  const pace = go && go.pace && typeof go.pace === "object" && !Array.isArray(go.pace) ? go.pace : null;
  const snap = go && go.snapshot && typeof go.snapshot === "object" && !Array.isArray(go.snapshot) ? go.snapshot : null;
  let monthly = d.monthly_usd;
  if (Number.isFinite(go?.monthly_usd) && go.monthly_usd > 0) monthly = go.monthly_usd;
  else if (Number.isFinite(top?.go_monthly_usd) && top.go_monthly_usd > 0) monthly = top.go_monthly_usd;
  let anchor = null;
  if (typeof go?.period_anchor === "string" && Number.isFinite(Date.parse(go.period_anchor))) anchor = go.period_anchor;
  const mode = pace?.mode === "on" || pace?.mode === "shadow" ? pace.mode : d.pace.mode;
  return Object.freeze({
    monthly_usd: monthly,
    period_anchor: anchor,
    pace: Object.freeze({
      enabled: typeof pace?.enabled === "boolean" ? pace.enabled : d.pace.enabled,
      mode,
      margin: numOr(pace?.margin, d.pace.margin),
      external_margin_pct: numOr(pace?.external_margin_pct, d.pace.external_margin_pct),
      ledger_under: typeof pace?.ledger_under === "boolean" ? pace.ledger_under : d.pace.ledger_under,
      reserve_pct: numOr(pace?.reserve_pct, d.pace.reserve_pct),
      reserve_floor_hours: numOr(pace?.reserve_floor_hours, d.pace.reserve_floor_hours),
      stale_hours: numOr(pace?.stale_hours, d.pace.stale_hours),
      recent_hours: numOr(pace?.recent_hours, d.pace.recent_hours),
    }),
    snapshot: Object.freeze({ min_interval_min: numOr(snap?.min_interval_min, d.snapshot.min_interval_min) }),
  });
}

// A config already in goConfig() shape passes through untouched (limits carry a `go` block instead).
function asConfig(cfg) {
  if (cfg && typeof cfg === "object" && cfg.go != null && typeof cfg.go === "object") return goConfig(cfg);
  const d = GO_DEFAULTS;
  const c = cfg && typeof cfg === "object" ? cfg : null;
  const pace = c?.pace && typeof c.pace === "object" ? c.pace : null;
  const snap = c?.snapshot && typeof c.snapshot === "object" ? c.snapshot : null;
  return {
    monthly_usd: Number.isFinite(c?.monthly_usd) && c.monthly_usd > 0 ? c.monthly_usd : d.monthly_usd,
    period_anchor:
      typeof c?.period_anchor === "string" && Number.isFinite(Date.parse(c.period_anchor)) ? c.period_anchor : null,
    pace: {
      enabled: typeof pace?.enabled === "boolean" ? pace.enabled : d.pace.enabled,
      mode: pace?.mode === "on" || pace?.mode === "shadow" ? pace.mode : d.pace.mode,
      margin: numOr(pace?.margin, d.pace.margin),
      external_margin_pct: numOr(pace?.external_margin_pct, d.pace.external_margin_pct),
      ledger_under: typeof pace?.ledger_under === "boolean" ? pace.ledger_under : d.pace.ledger_under,
      reserve_pct: numOr(pace?.reserve_pct, d.pace.reserve_pct),
      reserve_floor_hours: numOr(pace?.reserve_floor_hours, d.pace.reserve_floor_hours),
      stale_hours: numOr(pace?.stale_hours, d.pace.stale_hours),
      recent_hours: numOr(pace?.recent_hours, d.pace.recent_hours),
    },
    snapshot: { min_interval_min: numOr(snap?.min_interval_min, d.snapshot.min_interval_min) },
  };
}

/** Monday 00:00:00.000 UTC on or before now, plus 7 days. Null for non-finite now. */
export function weekBounds(now) {
  if (!Number.isFinite(now)) return null;
  const d = new Date(now);
  const daysSinceMonday = (d.getUTCDay() + 6) % 7;
  const start = Date.UTC(d.getUTCFullYear(), d.getUTCMonth(), d.getUTCDate() - daysSinceMonday);
  return { start, end: start + WEEK };
}

const daysInMonth = (y, m) => new Date(Date.UTC(y, m + 1, 0)).getUTCDate();

/**
 * The paid period containing now, stepping calendar months from the anchor. Each boundary uses the
 * anchor's day-of-month clamped to that month's last day and the anchor's UTC time of day (anchor
 * 2026-01-31T00:00Z gives boundaries Feb 28, Mar 31, Apr 30, ...). Steps backwards for now < anchor.
 * Returns null for a missing or unparsable anchor, or a non-finite now.
 */
export function periodBounds(anchor, now) {
  if (typeof anchor !== "string" || !Number.isFinite(now)) return null;
  const a = new Date(Date.parse(anchor));
  if (!Number.isFinite(a.getTime())) return null;
  const day = a.getUTCDate();
  const t = [a.getUTCHours(), a.getUTCMinutes(), a.getUTCSeconds(), a.getUTCMilliseconds()];
  const at = (y, m) => Date.UTC(y, m, Math.min(day, daysInMonth(y, m)), ...t);
  if (now >= a.getTime()) {
    // Walk forward month by month from the anchor's month.
    let cy = a.getUTCFullYear();
    let cm = a.getUTCMonth();
    for (;;) {
      const ny = cm === 11 ? cy + 1 : cy;
      const nm = cm === 11 ? 0 : cm + 1;
      if (at(ny, nm) > now) return { start: at(cy, cm), end: at(ny, nm) };
      cy = ny;
      cm = nm;
    }
  }
  // now < anchor: walk backwards until the boundary at or before now.
  let cy = a.getUTCFullYear();
  let cm = a.getUTCMonth();
  for (;;) {
    const start = at(cy, cm);
    if (start <= now) {
      const ny = cm === 11 ? cy + 1 : cy;
      const nm = cm === 11 ? 0 : cm + 1;
      return { start, end: at(ny, nm) };
    }
    cy = cm === 0 ? cy - 1 : cy;
    cm = cm === 0 ? 11 : cm - 1;
  }
}

/** The month before a snapshot's monthly reset: same day clamped to that month, same UTC time. */
export function periodFromReset(resetMs) {
  if (!Number.isFinite(resetMs)) return null;
  const r = new Date(resetMs);
  const py = r.getUTCMonth() === 0 ? r.getUTCFullYear() - 1 : r.getUTCFullYear();
  const pm = r.getUTCMonth() === 0 ? 11 : r.getUTCMonth() - 1;
  const start = Date.UTC(
    py,
    pm,
    Math.min(r.getUTCDate(), daysInMonth(py, pm)),
    r.getUTCHours(),
    r.getUTCMinutes(),
    r.getUTCSeconds(),
    r.getUTCMilliseconds(),
  );
  return { start, end: resetMs };
}

/**
 * The fixed 5 h window containing now, or null. A window opens at the first time at or after the
 * previous window's end and lasts 5 h (times 10:00, 14:00, 15:30 give 10:00-15:00 and 15:30-20:30).
 */
export function fiveHourWindow(times, now) {
  if (!Number.isFinite(now)) return null;
  const sorted = (Array.isArray(times) ? times : []).filter(Number.isFinite).sort((a, b) => a - b);
  let prevEnd = -Infinity;
  for (const t of sorted) {
    if (t > now) break;
    if (t >= prevEnd) {
      prevEnd = t + FIVE_H;
      if (now < prevEnd) return { start: t, end: prevEnd };
    }
  }
  return null;
}

/** Sum of usd over rows with from <= t < to; non-finite usd counts 0. */
export function sumUsd(rows, from, to) {
  let s = 0;
  for (const r of Array.isArray(rows) ? rows : []) {
    if (!r || typeof r !== "object") continue;
    if (Number.isFinite(r.t) && r.t >= from && r.t < to) s += Number.isFinite(r.usd) ? r.usd : 0;
  }
  return s;
}

/** Reserve in cap-points: reserve_pct at H = span, falling linearly to 0 at the floor. */
export function reserve(H, span, cfg) {
  const c = cfg && typeof cfg === "object" && cfg.pace && typeof cfg.pace === "object" ? cfg.pace : cfg;
  const pct = numOr(c?.reserve_pct, GO_DEFAULTS.pace.reserve_pct);
  const floor = numOr(c?.reserve_floor_hours, GO_DEFAULTS.pace.reserve_floor_hours);
  if (!(span > floor)) return 0;
  const f = Math.min(1, Math.max(0, (H - floor) / (span - floor)));
  return pct * f;
}

const round1 = (v) => (Number.isFinite(v) ? Math.round(v * 10) / 10 : null);
const isoOrNull = (t) => (Number.isFinite(t) ? new Date(t).toISOString() : null);

/**
 * Pure Go pace state. cfg: goConfig() output (raw limits with a `go` block also accepted). ledger:
 * null (no message ledger) or {rows: [{t, usd}], unrated}. snapshots: G3 records (any order); the
 * newest by `at` is current. health: readHealth() object. prev: {state} from the last run, or null.
 */
export function goPaceState({ cfg, ledger, snapshots = [], health = {}, now, prev = null, noPace = false } = {}) {
  const c = asConfig(cfg);
  const M = c.monthly_usd;
  const C_5h = 0.2 * M;
  const C_wk = 0.5 * M;
  const C_mo = M;
  const p5h = (x) => (100 * x) / C_5h;
  const pwk = (x) => (100 * x) / C_wk;
  const pmo = (x) => (100 * x) / C_mo;
  const rows = ledger && typeof ledger === "object" && Array.isArray(ledger.rows) ? ledger.rows : [];
  const unrated = Number.isFinite(ledger?.unrated) ? ledger.unrated : 0;
  const mode = c.pace.mode;
  const at = Number.isFinite(now) ? new Date(now).toISOString() : null;

  const nullResets = { "5h": null, wk: null, mo: null };
  const blank = (state, reason, extra = {}) => ({
    state,
    reason,
    mode,
    src: null,
    period_src: null,
    bind: null,
    proj: null,
    proj_wk: null,
    proj_mo: null,
    p_5h: null,
    p_wk: null,
    p_mo: null,
    used_5h: null,
    used_wk: null,
    used_mo: null,
    resets: { ...nullResets },
    rate: null,
    margin: c.pace.margin,
    unrated,
    at,
    ...extra,
  });

  if (c.pace.enabled === false || noPace) return blank("off", "disabled");

  // Newest snapshot by at; fresh when now - at <= stale_hours.
  const list = (Array.isArray(snapshots) ? snapshots : [])
    .filter((s) => s && typeof s === "object" && Number.isFinite(Date.parse(s.at)))
    .sort((a, b) => Date.parse(a.at) - Date.parse(b.at));
  const snap = list.length ? list[list.length - 1] : null;
  const fresh = snap && now - Date.parse(snap.at) <= c.pace.stale_hours * HOUR ? snap : null;
  const snapAt = fresh ? Date.parse(fresh.at) : null;

  // mo bounds: snapshot reset, else anchor, else none.
  let mo = null;
  let periodSrc = null;
  const snapMoReset = Number.isFinite(Date.parse(fresh?.monthly?.resets_at)) ? Date.parse(fresh.monthly.resets_at) : NaN;
  if (Number.isFinite(snapMoReset) && snapMoReset > now) {
    mo = periodFromReset(snapMoReset);
    periodSrc = "snap";
  } else {
    const anchored = periodBounds(c.period_anchor, now);
    if (anchored) {
      mo = anchored;
      periodSrc = "anchor";
    }
  }

  // wk bounds: always the Monday week; a fresh weekly resets_at replaces the end only.
  const wk = weekBounds(now);
  if (wk === null) return blank("unknown", "no period"); // non-finite now: no window resolves
  const snapWkReset = Number.isFinite(Date.parse(fresh?.weekly?.resets_at)) ? Date.parse(fresh.weekly.resets_at) : NaN;
  if (Number.isFinite(snapWkReset) && snapWkReset > now) wk.end = snapWkReset;

  // 5h always from the ledger, over the times of rows with usd > 0.
  const w5 = fiveHourWindow(
    rows.filter((r) => r && typeof r === "object" && Number.isFinite(r.usd) && r.usd > 0).map((r) => r.t),
    now,
  );
  const used5h = w5 ? sumUsd(rows, w5.start, now) : 0;

  // Per-window spend: fresh snapshot meter + ledger delta since the snapshot, else ledger from the start.
  const meter = (w) =>
    fresh?.[w] && typeof fresh[w] === "object" && Number.isFinite(fresh[w].pct)
      ? { pct: fresh[w].pct, reset: Date.parse(fresh[w].resets_at) }
      : null;
  const mwk = meter("weekly");
  const mmo = meter("monthly");
  const useSnapWk = mwk && Number.isFinite(mwk.reset) && mwk.reset > now;
  const useSnapMo = mmo && Number.isFinite(mmo.reset) && mmo.reset > now && mo !== null;
  const usedWk = useSnapWk ? (mwk.pct / 100) * C_wk + sumUsd(rows, snapAt, now) : sumUsd(rows, wk.start, now);
  const usedMo = mo === null ? null : useSnapMo ? (mmo.pct / 100) * C_mo + sumUsd(rows, snapAt, now) : sumUsd(rows, mo.start, now);
  const src = useSnapWk && useSnapMo ? "snap" : "ledger";
  const marginTotal = src === "snap" ? c.pace.margin : c.pace.margin + c.pace.external_margin_pct;

  const base = {
    src: ledger === null && !fresh ? null : src,
    period_src: periodSrc,
    p_5h: round1(p5h(used5h)),
    p_wk: round1(pwk(usedWk)),
    p_mo: usedMo === null ? null : round1(pmo(usedMo)),
    used_5h: round1(used5h),
    used_wk: round1(usedWk),
    used_mo: usedMo === null ? null : round1(usedMo),
    resets: { "5h": w5 ? new Date(w5.end).toISOString() : null, wk: new Date(wk.end).toISOString(), mo: mo ? new Date(mo.end).toISOString() : null },
    margin: round1(marginTotal),
  };
  const done = (state, reason, extra = {}) => ({ ...blank(state, reason), ...base, ...extra });

  // Rule 2: unknown.
  if (ledger === null && !fresh) return done("unknown", "no ledger", { ...base, src: null });
  if (mo === null) return done("unknown", "no period");
  if (fresh) {
    for (const [w, m, C, start] of [
      ["wk", mwk, C_wk, wk.start],
      ["mo", mmo, C_mo, mo.start],
    ]) {
      const snapUsed = w === "wk" ? useSnapWk : useSnapMo;
      if (snapUsed && m.pct > 0 && sumUsd(rows, start, snapAt) > 1.1 * (m.pct / 100) * C) {
        return done("unknown", "allowance mismatch");
      }
    }
  }

  // Rule 3: provider-wide Go quota mark set after both resets.
  const mark = health && typeof health === "object" ? health["opencode-go/*"] : null;
  if (
    mark &&
    typeof mark === "object" &&
    mark.reason === "quota" &&
    Number.isFinite(Date.parse(mark.until)) &&
    Date.parse(mark.until) > now &&
    Number.isFinite(Date.parse(mark.since)) &&
    Date.parse(mark.since) > Math.max(wk.start, mo.start)
  ) {
    return done("over", "go quota mark");
  }

  // Rule 4: 5h burst.
  if (p5h(used5h) >= BURST_OVER) return done("over", "5h burst");

  // Rule 5: reserve ceiling on either window.
  const Hwk = (wk.end - now) / HOUR;
  const Hmo = (mo.end - now) / HOUR;
  const spanMo = (mo.end - mo.start) / HOUR;
  if (pwk(usedWk) >= 100 - reserve(Hwk, SPAN_WK_H, c)) return done("over", "reserve wk");
  if (pmo(usedMo) >= 100 - reserve(Hmo, spanMo, c)) return done("over", "reserve mo");

  // Rule 6: early period.
  const elapsedMoH = (now - mo.start) / HOUR;
  if (elapsedMoH < EARLY_H) return done("on", "early period");

  // Rule 7: projection on the binding window.
  const recentFrom = now - c.pace.recent_hours * HOUR;
  const recentRate = c.pace.recent_hours > 0 ? sumUsd(rows, recentFrom, now) / c.pace.recent_hours : 0;
  const rate = Math.max(elapsedMoH > 0 ? usedMo / elapsedMoH : 0, recentRate);
  const projWk = pwk(usedWk + rate * Hwk) + marginTotal;
  const projMo = pmo(usedMo + rate * Hmo) + marginTotal;
  const bind = projMo >= projWk ? "mo" : "wk";
  const proj = bind === "mo" ? projMo : projWk;
  const projExtra = {
    bind,
    proj: round1(proj),
    proj_wk: round1(projWk),
    proj_mo: round1(projMo),
    // $/h keeps full precision: the worked example's 0.025 would round to 0 at 1 decimal.
    rate,
  };
  const prevState = typeof prev === "string" ? prev : prev?.state ?? null;
  if (proj >= OVER || (prevState === "over" && proj > OVER_EXIT)) return done("over", "projected", projExtra);

  // Rule 8: under (stricter, and optional, on ledger-only).
  const ceiling =
    src === "ledger" ? (prevState === "under" ? LEDGER_UNDER_HYST : LEDGER_UNDER) : prevState === "under" ? UNDER_HYST : UNDER;
  if (src === "ledger" && c.pace.ledger_under === false) return done("on", "projected", projExtra);
  if (proj <= ceiling && p5h(used5h) < BURST_UNDER_MAX) return done("under", "projected", projExtra);

  // Rule 9: on.
  return done("on", "projected", projExtra);
}

const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];

/** One status line (<= 100 chars, cut never wrapped). */
export function statusLine(r) {
  let s;
  if (!r || typeof r !== "object") return "go pace: UNKNOWN (no result)";
  if (r.state === "off") s = `go pace: OFF (${r.reason})`;
  else if (r.state === "unknown") s = `go pace: UNKNOWN (${r.reason})`;
  else if (r.reason !== "projected" || r.bind == null || !Number.isFinite(r.proj)) {
    const parts = [];
    if (Number.isFinite(r.p_wk)) parts.push(`wk ${Math.round(r.p_wk)}%`);
    if (Number.isFinite(r.p_5h)) parts.push(`5h ${Math.round(r.p_5h)}%`);
    if (r.src != null) parts.push(`src ${r.src}`);
    const mid = parts.length ? ` ${parts.join(" ")}` : "";
    s = `go pace${r.mode === "shadow" ? " (shadow)" : ""}: ${String(r.state).toUpperCase()}${mid} (${r.reason})`;
  } else {
    const pBind = r.bind === "mo" ? r.p_mo : r.p_wk;
    const d = Number.isFinite(Date.parse(r.resets?.[r.bind])) ? new Date(Date.parse(r.resets[r.bind])) : null;
    const on = d ? `${MONTHS[d.getUTCMonth()]}${String(d.getUTCDate()).padStart(2, "0")}` : "?";
    s = `go pace${r.mode === "shadow" ? " (shadow)" : ""}: ${String(r.state).toUpperCase()} ${r.bind} ${Math.round(pBind)}%→${Math.round(r.proj)}% bind ${r.bind} @${on} wk ${Math.round(r.p_wk)}% 5h ${Math.round(r.p_5h)}% src ${r.src}`;
  }
  return s.slice(0, 100);
}

const sameOrder = (a, b) => a.length === b.length && a.every((v, i) => v === b[i]);

/**
 * Order a role chain's tail by Go state. agentModel(name) is the pinned model (a throw or null is
 * class `other`). Classes: `cc-*` name -> cc; `opencode-go/*` (not `-free`) model -> go; else other.
 * Leading cc agents never move; a cc agent inside the tail counts as other. `roles` (default
 * worker/worker-strong) gates reordering; `session: true` never reorders. Mode `on` reorders;
 * `shadow` keeps the chain and records would_chain. The input array is never mutated.
 */
export function goTail(role, chain, go, mode, { agentModel, roles = DEFAULT_ROLES, session = false } = {}) {
  const list = Array.isArray(chain) ? [...chain] : [];
  const modelOf = (name) => {
    try {
      return typeof agentModel === "function" ? agentModel(name) : null;
    } catch {
      return null;
    }
  };
  const cls = (name) => {
    if (typeof name === "string" && name.startsWith("cc-")) return "cc";
    const m = modelOf(name);
    if (typeof m === "string" && m.startsWith("opencode-go/") && !m.endsWith("-free")) return "go";
    return "other";
  };
  let head = 0;
  while (head < list.length && cls(list[head]) === "cc") head++;
  const headAgents = list.slice(0, head);
  const tail = list.slice(head);
  const state = typeof go === "string" ? go : go?.state;
  let ordered = tail;
  if (Array.isArray(roles) && roles.includes(role) && !session) {
    const goAgents = tail.filter((n) => cls(n) === "go");
    const rest = tail.filter((n) => cls(n) !== "go");
    if (state === "under") ordered = [...goAgents, ...rest];
    else if (state === "over") ordered = [...rest, ...goAgents];
  }
  const next = [...headAgents, ...ordered];
  if (mode === "on") return { chain: next, would_chain: null, reordered: !sameOrder(next, list) };
  return { chain: list, would_chain: sameOrder(next, list) ? null : next, reordered: false };
}

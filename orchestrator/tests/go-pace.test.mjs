// go-pace: the pure Go pace model (table tests, no I/O, no child processes). All times UTC.
import test from "node:test";
import assert from "node:assert/strict";
import {
  OVER,
  OVER_EXIT,
  UNDER,
  UNDER_HYST,
  LEDGER_UNDER,
  LEDGER_UNDER_HYST,
  BURST_OVER,
  BURST_UNDER_MAX,
  EARLY_H,
  SPAN_WK_H,
  DEFAULT_ROLES,
  GO_DEFAULTS,
  goConfig,
  weekBounds,
  periodBounds,
  periodFromReset,
  fiveHourWindow,
  sumUsd,
  reserve,
  goPaceState,
  statusLine,
  goTail,
} from "../bin/go-pace.mjs";

const HOUR = 3600 * 1000;
const iso = (t) => new Date(t).toISOString();

// Anchor 2026-10-23T00:00Z: periods Oct 23 / Nov 23 / Dec 23 / Jan 23. The Nov 23 - Dec 23
// period is 30 days (720 h). Monday 2026-11-30 + 72 h = Thursday 2026-12-03T00:00Z.
const ANCHOR = "2026-10-23T00:00:00.000Z";
const NOW_W = Date.parse("2026-12-03T00:00:00.000Z"); // elapsed_mo 240 h, H_mo 480 h, H_wk 96 h
const WK_END = Date.parse("2026-12-07T00:00:00.000Z");
const MO_END = Date.parse("2026-12-23T00:00:00.000Z");
const cfg = (go = {}) => goConfig({ go: { monthly_usd: 60, period_anchor: ANCHOR, ...go } });
const BASE = cfg();
const st = (o = {}) =>
  goPaceState({ cfg: BASE, now: NOW_W, ledger: { rows: [], unrated: 0 }, snapshots: [], health: {}, prev: null, ...o });

const snap = ({ at, weekly, monthly, rolling } = {}) => {
  const s = { at: iso(at ?? NOW_W) };
  if (weekly !== null) s.weekly = weekly ?? { pct: 10, resets_at: iso(WK_END) };
  if (monthly !== null) s.monthly = monthly ?? { pct: 10, resets_at: iso(MO_END) };
  if (rolling !== undefined) s.rolling = rolling;
  return s;
};

/** The plan's worked example: M=60, snap weekly/monthly 10 taken at now, $0.60 in one open 5h window. */
const worked = () =>
  st({
    snapshots: [
      snap({ rolling: { pct: 99, resets_at: iso(NOW_W + 4 * HOUR) } }), // rolling is ignored until G0
    ],
    ledger: { rows: [{ t: NOW_W - HOUR, usd: 0.6 }], unrated: 0 },
  });

test("bar 1: worked example -> rate 0.025, proj_mo 35, proj_wk 23, bind mo, under, snap, p_5h 5", () => {
  const r = worked();
  assert.equal(r.state, "under");
  assert.equal(r.reason, "projected");
  assert.equal(r.src, "snap");
  assert.equal(r.period_src, "snap");
  assert.equal(r.bind, "mo");
  assert.ok(Math.abs(r.rate - 0.025) < 1e-9, `rate ${r.rate}`);
  assert.equal(r.proj, 35);
  assert.equal(r.proj_mo, 35);
  assert.equal(r.proj_wk, 23);
  assert.equal(r.p_5h, 5);
  assert.equal(r.p_wk, 10);
  assert.equal(r.p_mo, 10);
  assert.equal(r.used_5h, 0.6);
  assert.equal(r.used_wk, 3);
  assert.equal(r.used_mo, 6);
  assert.equal(r.margin, 5);
  assert.equal(r.unrated, 0);
  assert.equal(r.mode, "shadow");
  assert.deepEqual(r.resets, { "5h": iso(NOW_W + 4 * HOUR), wk: iso(WK_END), mo: iso(MO_END) });
  assert.equal(r.at, iso(NOW_W));
  for (const k of [
    "state", "reason", "mode", "src", "period_src", "bind", "proj", "proj_wk", "proj_mo",
    "p_5h", "p_wk", "p_mo", "used_5h", "used_wk", "used_mo", "resets", "rate", "margin", "unrated", "at",
  ]) {
    assert.ok(k in r, k);
  }
  assert.equal(
    statusLine(r),
    "go pace (shadow): UNDER mo 10%→35% bind mo @Dec23 wk 10% 5h 5% src snap",
  );
});

test("bar 2: weekly window binds", () => {
  // now = Monday 2026-12-21: elapsed_mo 672 h, H_mo 48 h, H_wk 168 h. Heavy week, light month.
  const now = Date.parse("2026-12-21T00:00:00.000Z");
  const r = goPaceState({
    cfg: BASE,
    now,
    ledger: { rows: [], unrated: 0 },
    snapshots: [
      { at: iso(now), weekly: { pct: 60, resets_at: iso(now + 168 * HOUR) }, monthly: { pct: 50, resets_at: iso(MO_END) } },
    ],
    health: {},
  });
  assert.equal(r.bind, "wk");
  assert.ok(r.proj_wk > r.proj_mo, `${r.proj_wk} vs ${r.proj_mo}`);
  assert.ok(Math.abs(r.proj_wk - 90) < 0.6, `proj_wk ${r.proj_wk}`);
  assert.ok(Math.abs(r.proj_mo - 58.6) < 0.6, `proj_mo ${r.proj_mo}`);
  assert.equal(r.state, "on");
  assert.equal(r.reason, "projected");
});

test("bar 3: rules 1 and 3-9 fire first where expected; early masks projected-over", () => {
  // Rule 1: off (config) and off (noPace).
  assert.equal(st({ cfg: cfg({ pace: { enabled: false } }) }).state, "off");
  assert.equal(st({ cfg: cfg({ pace: { enabled: false } }) }).reason, "disabled");
  assert.equal(st({ noPace: true }).state, "off");

  // Rule 2: allowance mismatch (ledger dollars for the snap window exceed 110 % of the meter).
  const at = NOW_W;
  const mismatch = st({
    snapshots: [snap({ at })],
    ledger: { rows: [{ t: Date.parse("2026-11-30T01:00:00.000Z"), usd: 10 }], unrated: 0 },
  });
  assert.equal(mismatch.state, "unknown");
  assert.equal(mismatch.reason, "allowance mismatch");

  // Rule 3: provider-wide quota mark set after both resets.
  const quota = st({
    health: { "opencode-go/*": { reason: "quota", since: iso(NOW_W - HOUR), until: iso(NOW_W + 24 * HOUR) } },
  });
  assert.equal(quota.state, "over");
  assert.equal(quota.reason, "go quota mark");

  // Rule 4: 5h burst (p = 91.7 >= 85).
  const burst = st({ ledger: { rows: [{ t: NOW_W - HOUR, usd: 11 }], unrated: 0 } });
  assert.equal(burst.state, "over");
  assert.equal(burst.reason, "5h burst");

  // Rule 5: reserve wk (p_wk 90 >= 89.2) and reserve mo (p_mo 91.7 >= 90.2).
  const rwk = st({ ledger: { rows: [{ t: Date.parse("2026-11-30T02:00:00.000Z"), usd: 27 }], unrated: 0 } });
  assert.equal(rwk.state, "over");
  assert.equal(rwk.reason, "reserve wk");
  const nowMo = Date.parse("2026-12-08T00:00:00.000Z"); // Tue; elapsed 360, H_mo 360
  const rmo = goPaceState({
    cfg: BASE,
    now: nowMo,
    ledger: { rows: [{ t: nowMo - 200 * HOUR, usd: 55 }], unrated: 0 },
    snapshots: [],
    health: {},
  });
  assert.equal(rmo.state, "over");
  assert.equal(rmo.reason, "reserve mo");

  // Rule 6: early period masks a projected-over (proj would be ~600).
  const earlyCfg = cfg({ period_anchor: "2026-11-23T00:00:00.000Z" });
  const earlyNow = Date.parse("2026-11-23T10:00:00.000Z");
  const early = goPaceState({
    cfg: earlyCfg,
    now: earlyNow,
    ledger: { rows: [{ t: earlyNow - HOUR, usd: 5 }], unrated: 0 },
    snapshots: [],
    health: {},
  });
  assert.equal(early.state, "on");
  assert.equal(early.reason, "early period");
  assert.equal(early.proj, null); // projection never runs

  // Rule 7: over on projection (recent burst, windows calm): proj ~548.
  const overNow = Date.parse("2026-12-08T00:00:00.000Z");
  const over = goPaceState({
    cfg: BASE,
    now: overNow,
    ledger: {
      rows: [-23, -17, -11, -5].map((h) => ({ t: overNow + h * HOUR, usd: 5 })),
      unrated: 0,
    },
    snapshots: [],
    health: {},
  });
  assert.equal(over.state, "over");
  assert.equal(over.reason, "projected");
  assert.equal(over.bind, "mo");
  assert.ok(over.proj >= 95, `proj ${over.proj}`);

  // Rule 8: under (worked example).
  const under = worked();
  assert.equal(under.state, "under");

  // Rule 9: on (proj ~90.1, between the snap ceiling and over).
  const onNow = Date.parse("2026-12-22T23:00:00.000Z");
  const on = goPaceState({
    cfg: BASE,
    now: onNow,
    ledger: { rows: [], unrated: 0 },
    snapshots: [
      {
        at: iso(onNow),
        weekly: { pct: 10, resets_at: iso(Date.parse("2026-12-28T00:00:00.000Z")) },
        monthly: { pct: 85, resets_at: iso(MO_END) },
      },
    ],
    health: {},
  });
  assert.equal(on.state, "on");
  assert.equal(on.reason, "projected");
  assert.equal(on.bind, "mo");
  assert.ok(on.proj > 85 && on.proj < 95, `proj ${on.proj}`);
});

test("bar 4: reserve 20 at span, 0 at floor, 10 halfway; rule-5 triggers", () => {
  assert.equal(reserve(SPAN_WK_H, SPAN_WK_H, BASE), 20);
  assert.equal(reserve(12, SPAN_WK_H, BASE), 0);
  assert.equal(reserve(90, SPAN_WK_H, BASE), 10);
  assert.equal(reserve(5, SPAN_WK_H, BASE), 0);
  assert.equal(reserve(5, 10, BASE), 0); // span <= floor
  assert.equal(reserve(90, SPAN_WK_H, BASE.pace), 10); // pace sub-object also accepted
  // Rule-5 triggers live in the bar-3 test (reasons "reserve wk" / "reserve mo"); pin the math here:
  // H_wk 96 -> 20*(96-12)/156 = 10.77 -> ceiling 89.2; p_wk 90 fires, 89 does not.
  assert.ok(90 >= 100 - reserve(96, SPAN_WK_H, BASE));
  assert.ok(!(89 >= 100 - reserve(96, SPAN_WK_H, BASE)));
});

test("bar 5: over-exit and under hysteresis with chained prev", () => {
  // Ledger-only, one stale row (outside the week and the recent window): rate = X/360, proj = 100*2X/60 + 15.
  const now = Date.parse("2026-12-08T00:00:00.000Z");
  const atX = (X, prev) =>
    goPaceState({ cfg: BASE, now, ledger: { rows: [{ t: now - 48 * HOUR, usd: X }], unrated: 0 }, snapshots: [], health: {}, prev });
  const targets = [96, 93, 91, 89];
  const Xs = targets.map((p) => (p - 15) * 0.3);
  let prev = null;
  const states = [];
  for (const X of Xs) {
    const r = atX(X, prev);
    assert.ok(Math.abs(r.proj - targets[states.length]) < 0.6, `proj ${r.proj}`);
    states.push(r.state);
    assert.equal(r.reason, "projected");
    prev = r;
  }
  assert.deepEqual(states, ["over", "over", "over", "on"]);

  // Under hysteresis at proj 82 (snap, 2P + 5): prev under -> under, prev on -> on.
  const hystNow = Date.parse("2026-12-08T00:00:00.000Z");
  const hyst = (prevState) =>
    goPaceState({
      cfg: BASE,
      now: hystNow,
      ledger: { rows: [], unrated: 0 },
      snapshots: [
        {
          at: iso(hystNow),
          weekly: { pct: 10, resets_at: iso(Date.parse("2026-12-14T00:00:00.000Z")) },
          monthly: { pct: 38.5, resets_at: iso(MO_END) },
        },
      ],
      health: {},
      prev: prevState ? { state: prevState } : null,
    });
  const a = hyst("under");
  const b = hyst("on");
  assert.ok(Math.abs(a.proj - 82) < 0.6, `proj ${a.proj}`);
  assert.equal(a.state, "under");
  assert.equal(b.state, "on");
});

test("bar 6: ledger-only margin 15, ceiling 70/75, ledger_under false never under", () => {
  // One stale row: proj = 100*2X/60 + 15. X = 17.1 -> 72; X = 10.5 -> 50.
  const now = Date.parse("2026-12-08T00:00:00.000Z");
  const atX = (X, prev, c = BASE) =>
    goPaceState({ cfg: c, now, ledger: { rows: [{ t: now - 48 * HOUR, usd: X }], unrated: 2 }, snapshots: [], health: {}, prev });
  const proj72 = atX(17.1, null);
  assert.equal(proj72.margin, 15);
  assert.equal(proj72.src, "ledger");
  assert.ok(Math.abs(proj72.proj - 72) < 0.6, `proj ${proj72.proj}`);
  assert.equal(proj72.state, "on"); // 72 > 70
  assert.equal(proj72.unrated, 2);
  const proj72Under = atX(17.1, { state: "under" });
  assert.equal(proj72Under.state, "under"); // 72 <= 75
  const strict = atX(10.5, null, cfg({ pace: { ledger_under: false } }));
  assert.ok(Math.abs(strict.proj - 50) < 0.6, `proj ${strict.proj}`);
  assert.equal(strict.state, "on"); // never under when ledger_under is false
  assert.equal(strict.reason, "projected");
});

test("bar 7: snapshot meter with past resets_at -> ledger counts from the window start", () => {
  const at = NOW_W - 30 * 60 * 1000;
  const r = st({
    snapshots: [
      {
        at: iso(at),
        weekly: { pct: 50, resets_at: iso(NOW_W - HOUR) }, // past: ignored, would have been $15
        monthly: { pct: 10, resets_at: iso(MO_END) },
      },
    ],
    ledger: {
      rows: [
        { t: Date.parse("2026-11-30T01:00:00.000Z"), usd: 4 },
        { t: NOW_W - 10 * 60 * 1000, usd: 1 },
      ],
      unrated: 0,
    },
  });
  assert.equal(r.used_wk, 5); // ledger from the week start, not the stale meter
  assert.equal(r.src, "ledger"); // wk did not come from the snapshot
  assert.equal(r.period_src, "snap");
  assert.equal(r.margin, 15);
  assert.equal(r.used_mo, 7); // $6 meter + $1 delta since the snapshot
});

test("bar 8: quota mark after both resets counts; stale/expired/model-scoped do not", () => {
  const mark = (since, until, key = "opencode-go/*", reason = "quota") => ({ [key]: { reason, since: iso(since), until: iso(until) } });
  const low = { snapshots: [snap({})], ledger: { rows: [], unrated: 0 } };
  const fresh = st({ ...low, health: mark(NOW_W - HOUR, NOW_W + 24 * HOUR) });
  assert.equal(fresh.state, "over");
  assert.equal(fresh.reason, "go quota mark");
  // Set before the last weekly reset: stale for the pace.
  const stale = st({ ...low, health: mark(Date.parse("2026-11-30T00:00:00.000Z") - HOUR, NOW_W + 24 * HOUR) });
  assert.notEqual(stale.reason, "go quota mark");
  assert.equal(stale.state, "under");
  // Expired.
  const expired = st({ ...low, health: mark(NOW_W - 48 * HOUR, NOW_W - HOUR) });
  assert.notEqual(expired.reason, "go quota mark");
  assert.equal(expired.state, "under");
  // Model-scoped mark never counts.
  const scoped = st({ ...low, health: mark(NOW_W - HOUR, NOW_W + 24 * HOUR, "opencode-go/some-model") });
  assert.notEqual(scoped.reason, "go quota mark");
  assert.equal(scoped.state, "under");
  // Non-quota provider mark never counts.
  const other = st({ ...low, health: mark(NOW_W - HOUR, NOW_W + 24 * HOUR, "opencode-go/*", "error") });
  assert.notEqual(other.reason, "go quota mark");
  assert.equal(other.state, "under");
  // A provider mark set between wk.start and mo.start is stale: mo.start (mid-week) is the later reset.
  const midC = cfg({ period_anchor: "2026-11-01T00:00:00.000Z" }); // Dec 1 - Jan 1 period; wk Nov 30 - Dec 7
  const between = goPaceState({
    cfg: midC,
    now: NOW_W,
    ledger: { rows: [], unrated: 0 },
    snapshots: [],
    health: mark(Date.parse("2026-11-30T12:00:00.000Z"), NOW_W + 24 * HOUR),
  });
  assert.notEqual(between.reason, "go quota mark");
  assert.equal(between.state, "under");
});

test("bar 9: unknown reasons; allowance mismatch; pct 0 never mismatches", () => {
  // No anchor and no snapshot (ledger present) -> no period.
  const noAnchor = goPaceState({
    cfg: goConfig({ go: { monthly_usd: 60 } }),
    now: NOW_W,
    ledger: { rows: [{ t: NOW_W - HOUR, usd: 1 }], unrated: 0 },
    snapshots: [],
    health: {},
  });
  assert.equal(noAnchor.state, "unknown");
  assert.equal(noAnchor.reason, "no period");

  // Ledger null and no fresh snapshot -> no ledger (even with an anchor).
  const noLedger = st({ ledger: null, snapshots: [] });
  assert.equal(noLedger.state, "unknown");
  assert.equal(noLedger.reason, "no ledger");
  // A stale snapshot is no snapshot.
  const staleSnap = st({ ledger: null, snapshots: [snap({ at: NOW_W - 5 * HOUR })] });
  assert.equal(staleSnap.state, "unknown");
  assert.equal(staleSnap.reason, "no ledger");

  // Ledger null with a fresh snapshot still resolves (rows count 0).
  const snapOnly = st({ ledger: null, snapshots: [snap({})] });
  assert.equal(snapOnly.state, "under");
  assert.equal(snapOnly.src, "snap");

  // Allowance mismatch boundary: just over 110 % of the meter.
  const over = st({
    snapshots: [snap({})],
    ledger: { rows: [{ t: Date.parse("2026-11-30T01:00:00.000Z"), usd: 3.31 }], unrated: 0 },
  });
  assert.equal(over.reason, "allowance mismatch");
  const under110 = st({
    snapshots: [snap({})],
    ledger: { rows: [{ t: Date.parse("2026-11-30T01:00:00.000Z"), usd: 3.29 }], unrated: 0 },
  });
  assert.notEqual(under110.reason, "allowance mismatch");

  // pct 0 never mismatches, however large the ledger window is.
  const zero = st({
    snapshots: [
      {
        at: iso(NOW_W),
        weekly: { pct: 0, resets_at: iso(WK_END) },
        monthly: { pct: 50, resets_at: iso(MO_END) },
      },
    ],
    ledger: { rows: [{ t: NOW_W - HOUR, usd: 10 }], unrated: 0 },
  });
  assert.notEqual(zero.state, "unknown");

  // mo-meter mismatch while the wk window passes: spend sits before wk.start but inside the period.
  const moMismatch = st({
    snapshots: [snap({})],
    ledger: { rows: [{ t: Date.parse("2026-11-25T00:00:00.000Z"), usd: 7 }], unrated: 0 },
  });
  assert.equal(moMismatch.state, "unknown");
  assert.equal(moMismatch.reason, "allowance mismatch");

  // Non-finite now resolves no window.
  const nanNow = st({ now: NaN });
  assert.equal(nanNow.state, "unknown");
});

test("bar 10: early period (elapsed < 24 h) -> on", () => {
  const c = cfg({ period_anchor: "2026-11-23T00:00:00.000Z" });
  const go = (now, rows) => goPaceState({ cfg: c, now, ledger: { rows, unrated: 0 }, snapshots: [], health: {} });
  const early = go(Date.parse("2026-11-23T10:00:00.000Z"), [{ t: Date.parse("2026-11-23T09:00:00.000Z"), usd: 1 }]);
  assert.equal(early.state, "on");
  assert.equal(early.reason, "early period");
  // Exactly 24 h is not early.
  const boundary = go(Date.parse("2026-11-24T00:00:00.000Z"), [{ t: Date.parse("2026-11-23T23:00:00.000Z"), usd: 1 }]);
  assert.notEqual(boundary.reason, "early period");
  assert.equal(boundary.state, "under");
});

test("bar 11: goConfig defaults, aliases, fallbacks, frozen", () => {
  assert.deepEqual(goConfig({}), GO_DEFAULTS);
  assert.deepEqual(goConfig(null), GO_DEFAULTS);
  assert.deepEqual(goConfig("junk"), GO_DEFAULTS);
  assert.deepEqual(goConfig({ go: 5 }), GO_DEFAULTS);
  assert.deepEqual(goConfig({ go: null }), GO_DEFAULTS);
  const d = goConfig({});
  assert.ok(Object.isFrozen(d) && Object.isFrozen(d.pace) && Object.isFrozen(d.snapshot));

  assert.equal(goConfig({ go_monthly_usd: 40 }).monthly_usd, 40);
  assert.equal(goConfig({ go: { monthly_usd: 100 }, go_monthly_usd: 40 }).monthly_usd, 100);
  for (const bad of [0, -5, NaN, Infinity, "60", null]) {
    assert.equal(goConfig({ go: { monthly_usd: bad } }).monthly_usd, 60, String(bad));
  }

  assert.equal(goConfig({}).period_anchor, null);
  assert.equal(goConfig({ go: { period_anchor: "not a date" } }).period_anchor, null);
  assert.equal(goConfig({ go: { period_anchor: 42 } }).period_anchor, null);
  assert.equal(goConfig({ go: { period_anchor: ANCHOR } }).period_anchor, ANCHOR);

  assert.equal(goConfig({}).pace.mode, "shadow");
  assert.equal(goConfig({ go: { pace: { mode: "x" } } }).pace.mode, "shadow");
  assert.equal(goConfig({ go: { pace: { mode: "on" } } }).pace.mode, "on");
  assert.equal(goConfig({ go: { pace: { enabled: "yes" } } }).pace.enabled, true);
  assert.equal(goConfig({ go: { pace: { margin: "x", ledger_under: 1 } } }).pace.margin, 5);
  assert.equal(goConfig({ go: { pace: { ledger_under: 1 } } }).pace.ledger_under, true);
  assert.equal(goConfig({ go: { pace: "junk", snapshot: 7 } }).snapshot.min_interval_min, 15);
  assert.deepEqual(Object.keys(goConfig({ go: { pace: { bogus: 1 } } }).pace).sort(), Object.keys(GO_DEFAULTS.pace).sort());
});

test("bar 12: window helpers", () => {
  // Monday 00:00 opens the new week; Sunday 23:59:59.999 belongs to the old.
  const mon = Date.parse("2026-12-07T00:00:00.000Z");
  assert.deepEqual(weekBounds(mon), { start: mon, end: mon + 7 * 24 * HOUR });
  const sun = Date.parse("2026-12-06T23:59:59.999Z");
  assert.deepEqual(weekBounds(sun), { start: Date.parse("2026-11-30T00:00:00.000Z"), end: mon });

  // Anchor 2026-01-31: clamped day steps Feb 28 / Mar 31 / Apr 30.
  const a31 = "2026-01-31T00:00:00.000Z";
  assert.deepEqual(periodBounds(a31, Date.parse("2026-03-15T00:00:00.000Z")), {
    start: Date.parse("2026-02-28T00:00:00.000Z"),
    end: Date.parse("2026-03-31T00:00:00.000Z"),
  });
  assert.deepEqual(periodBounds(a31, Date.parse("2026-04-10T00:00:00.000Z")), {
    start: Date.parse("2026-03-31T00:00:00.000Z"),
    end: Date.parse("2026-04-30T00:00:00.000Z"),
  });
  assert.deepEqual(periodBounds(a31, Date.parse("2026-02-15T00:00:00.000Z")), {
    start: Date.parse("2026-01-31T00:00:00.000Z"),
    end: Date.parse("2026-02-28T00:00:00.000Z"),
  });
  // Anchor time of day carries to every boundary; now before the anchor steps backwards.
  assert.deepEqual(periodBounds("2026-01-31T15:30:45.123Z", Date.parse("2026-03-15T00:00:00.000Z")), {
    start: Date.parse("2026-02-28T15:30:45.123Z"),
    end: Date.parse("2026-03-31T15:30:45.123Z"),
  });
  assert.deepEqual(periodBounds(a31, Date.parse("2025-12-15T00:00:00.000Z")), {
    start: Date.parse("2025-11-30T00:00:00.000Z"),
    end: Date.parse("2025-12-31T00:00:00.000Z"),
  });
  assert.equal(periodBounds(null, NOW_W), null);
  assert.equal(periodBounds("junk", NOW_W), null);
  assert.equal(periodBounds(42, NOW_W), null);

  // periodFromReset: one clamped month back.
  assert.deepEqual(periodFromReset(MO_END), { start: Date.parse("2026-11-23T00:00:00.000Z"), end: MO_END });
  assert.deepEqual(periodFromReset(Date.parse("2026-03-31T00:00:00.000Z")), {
    start: Date.parse("2026-02-28T00:00:00.000Z"),
    end: Date.parse("2026-03-31T00:00:00.000Z"),
  });

  // fiveHourWindow: 10:00, 14:00, 15:30 -> 10:00-15:00 and 15:30-20:30.
  const day = Date.parse("2026-12-03T00:00:00.000Z");
  const t10 = day + 10 * HOUR;
  const t14 = day + 14 * HOUR;
  const t1530 = day + 15.5 * HOUR;
  assert.deepEqual(fiveHourWindow([t10, t14, t1530], day + 16 * HOUR), { start: t1530, end: t1530 + 5 * HOUR });
  assert.deepEqual(fiveHourWindow([t1530, t10, t14], day + 12 * HOUR), { start: t10, end: t10 + 5 * HOUR });
  assert.equal(fiveHourWindow([t10, t14, t1530], day + 15 * HOUR + 10 * 60 * 1000), null); // between windows
  assert.deepEqual(fiveHourWindow([t10], t10), { start: t10, end: t10 + 5 * HOUR }); // start inclusive
  assert.equal(fiveHourWindow([t10], t10 + 5 * HOUR), null); // end exclusive
  assert.equal(fiveHourWindow([], day + 12 * HOUR), null);
  assert.equal(fiveHourWindow([t10], day + 9 * HOUR), null); // now before the window

  // sumUsd: from inclusive, to exclusive, non-finite usd counts 0.
  const rows = [
    { t: 100, usd: 1 },
    { t: 200, usd: NaN },
    { t: 300, usd: 2 },
    { t: "x", usd: 5 },
  ];
  assert.equal(sumUsd(rows, 100, 300), 1);
  assert.equal(sumUsd(rows, 0, 1000), 3);
  assert.equal(sumUsd([], 0, 1000), 0);

  // Non-finite now resolves no window.
  assert.equal(periodBounds(ANCHOR, NaN), null);
  assert.equal(weekBounds(NaN), null);
  assert.equal(fiveHourWindow([t10], NaN), null);
  assert.equal(periodFromReset(NaN), null);
});

test("bar 13: goTail role x state x mode x leading-cc x throwing agentModel", () => {
  const models = {
    worker: "opencode-go/x",
    "worker-strong": "opencode-go/muse",
    "worker-nvidia": "nvidia/n",
    "worker-free": "opencode/f-free",
    "cc-worker": "sonnet",
    "mystery": null,
  };
  const agentModel = (n) => {
    if (n === "boom") throw new Error("unresolvable");
    return models[n] ?? null;
  };
  const tail = (role, chain, go, mode, extra = {}) => {
    const before = [...chain];
    const r = goTail(role, chain, go, mode, { agentModel, ...extra });
    assert.deepEqual(chain, before, "input mutated");
    return r;
  };

  // Mandate Expected results.
  assert.deepEqual(tail("worker", ["cc-worker", "worker-nvidia", "worker", "worker-free"], "under", "on").chain, [
    "cc-worker",
    "worker",
    "worker-nvidia",
    "worker-free",
  ]);
  assert.deepEqual(tail("worker", ["worker", "worker-nvidia", "worker-free"], "over", "on").chain, [
    "worker-nvidia",
    "worker-free",
    "worker",
  ]);
  assert.deepEqual(
    tail("worker-strong", ["worker-strong", "worker-nvidia", "worker-free"], "over", "on").chain,
    ["worker-nvidia", "worker-free", "worker-strong"],
  );
  assert.deepEqual(tail("critic", ["worker", "worker-nvidia"], "under", "on").chain, ["worker", "worker-nvidia"]);

  // State table (mode on): under -> go first; over -> go last; on/unknown/off -> unchanged.
  const mixed = ["worker-nvidia", "worker", "worker-free"];
  assert.deepEqual(tail("worker", mixed, "under", "on").chain, ["worker", "worker-nvidia", "worker-free"]);
  assert.deepEqual(tail("worker", mixed, "over", "on").chain, ["worker-nvidia", "worker-free", "worker"]);
  for (const s of ["on", "unknown", "off"]) {
    const r = tail("worker", mixed, s, "on");
    assert.deepEqual(r.chain, mixed, s);
    assert.equal(r.reordered, false, s);
    assert.equal(r.would_chain, null, s);
  }
  // go as a result object also works.
  assert.deepEqual(tail("worker", mixed, { state: "under" }, "on").chain, ["worker", "worker-nvidia", "worker-free"]);

  // Leading cc agents never move (over pushes go after them, not past them).
  assert.deepEqual(tail("worker", ["cc-worker", "worker", "worker-nvidia"], "over", "on").chain, [
    "cc-worker",
    "worker-nvidia",
    "worker",
  ]);
  // A cc agent inside the tail counts as other: relative order kept.
  assert.deepEqual(tail("worker", ["worker", "cc-helper", "worker-nvidia"], "over", "on").chain, [
    "cc-helper",
    "worker-nvidia",
    "worker",
  ]);

  // Throwing agentModel and null model are class other; -free is not go.
  assert.deepEqual(tail("worker", ["worker", "boom", "worker-nvidia"], "over", "on").chain, [
    "boom",
    "worker-nvidia",
    "worker",
  ]);
  assert.deepEqual(tail("worker", ["worker", "mystery", "worker-free"], "under", "on").chain, [
    "worker",
    "mystery",
    "worker-free",
  ]);

  // Shadow: chain unchanged, would_chain recorded only when it differs; reordered always false.
  const sh = tail("worker", ["cc-worker", "worker-nvidia", "worker", "worker-free"], "under", "shadow");
  assert.deepEqual(sh.chain, ["cc-worker", "worker-nvidia", "worker", "worker-free"]);
  assert.deepEqual(sh.would_chain, ["cc-worker", "worker", "worker-nvidia", "worker-free"]);
  assert.equal(sh.reordered, false);
  const shSame = tail("critic", ["worker", "worker-nvidia"], "under", "shadow");
  assert.deepEqual(shSame.chain, ["worker", "worker-nvidia"]);
  assert.equal(shSame.would_chain, null);
  assert.equal(shSame.reordered, false);

  // session: true never reorders, even under/on.
  const sess = tail("worker", mixed, "under", "on", { session: true });
  assert.deepEqual(sess.chain, mixed);
  assert.equal(sess.would_chain, null);
  assert.equal(sess.reordered, false);

  // Roles gate: worker-strong under moves; orchestrator never does.
  assert.deepEqual(tail("worker-strong", ["worker-nvidia", "worker-strong"], "under", "on").chain, [
    "worker-strong",
    "worker-nvidia",
  ]);
  const orch = tail("orchestrator", ["worker-nvidia", "worker"], "under", "on");
  assert.deepEqual(orch.chain, ["worker-nvidia", "worker"]);
  assert.equal(orch.reordered, false);

  // on reports reordered only when the order differs.
  assert.equal(tail("worker", mixed, "under", "on").reordered, true);
  assert.equal(tail("worker", ["worker", "worker-nvidia"], "under", "on").reordered, false);
  assert.equal(tail("worker", mixed, "under", "on").would_chain, null);
});

test("bar 14: statusLine for off, unknown, shadow under, on-mode over (non-projected)", () => {
  const lines = [];
  lines.push(statusLine({ state: "off", reason: "disabled", mode: "shadow" }));
  lines.push(statusLine({ state: "unknown", reason: "no ledger", mode: "shadow" }));
  lines.push(statusLine(worked()));
  // Minimal object: no window parts, only the reason.
  lines.push(statusLine({ state: "over", reason: "go quota mark", mode: "on" }));
  // Real burst result in on mode carries the window parts before the reason.
  const burstLine = goPaceState({
    cfg: cfg({ pace: { mode: "on" } }),
    now: NOW_W,
    ledger: {
      rows: [
        { t: NOW_W - HOUR, usd: 10.8 },
        { t: Date.parse("2026-11-30T01:00:00.000Z"), usd: 1.2 },
      ],
      unrated: 0,
    },
    snapshots: [],
    health: {},
  });
  assert.equal(burstLine.state, "over");
  assert.equal(burstLine.reason, "5h burst");
  lines.push(statusLine(burstLine));
  // Single-digit day of month is zero-padded.
  lines.push(
    statusLine({
      ...worked(),
      resets: { ...worked().resets, mo: iso(Date.parse("2026-12-03T00:00:00.000Z")) },
    }),
  );
  // A 200-char reason is cut, never wrapped.
  lines.push(statusLine({ state: "unknown", reason: "x".repeat(200), mode: "shadow" }));
  assert.equal(lines[0], "go pace: OFF (disabled)");
  assert.equal(lines[1], "go pace: UNKNOWN (no ledger)");
  assert.equal(lines[3], "go pace: OVER (go quota mark)");
  assert.equal(lines[4], "go pace: OVER wk 40% 5h 90% src ledger (5h burst)");
  assert.ok(lines[5].includes("@Dec03"), lines[5]);
  assert.ok(lines[2].startsWith("go pace (shadow): UNDER"), lines[2]);
  for (const l of lines) {
    assert.ok(!l.includes("\n"), l);
    assert.ok(l.length <= 100, `${l.length}: ${l}`);
  }
});

test("constants and roles are frozen", () => {
  assert.equal(OVER, 95);
  assert.equal(OVER_EXIT, 90);
  assert.equal(UNDER, 80);
  assert.equal(UNDER_HYST, 85);
  assert.equal(LEDGER_UNDER, 70);
  assert.equal(LEDGER_UNDER_HYST, 75);
  assert.equal(BURST_OVER, 85);
  assert.equal(BURST_UNDER_MAX, 60);
  assert.equal(EARLY_H, 24);
  assert.equal(SPAN_WK_H, 168);
  assert.deepEqual([...DEFAULT_ROLES], ["worker", "worker-strong"]);
  assert.ok(Object.isFrozen(DEFAULT_ROLES));
});

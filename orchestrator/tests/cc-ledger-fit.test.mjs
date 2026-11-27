// cc-ledger fit/backtest (cc-pacing-v2 A1b): k = weekly % per weighted token, fitted from usage snapshots and
// ledger buckets; walk-forward backtest; CLI. Synthetic data only (fixtures/cc-ledger/fit-week.json + generators).
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { fit, backtest, bucketOf, DEFAULT_WEIGHTS, fitLine, backtestLine } from "../bin/cc-ledger.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "cc-ledger.mjs");
const H = 3600 * 1000;
const FIX = JSON.parse(fs.readFileSync(path.join(HERE, "fixtures", "cc-ledger", "fit-week.json"), "utf8"));
const FIX_NOW = Date.parse(FIX.now);
const BASE = Date.parse(FIX.snapshots[0].at);
const W = DEFAULT_WEIGHTS;
const near = (a, b, eps = 1e-9) => assert.ok(a != null && Math.abs(a - b) <= eps, `${a} != ${b} (±${eps})`);

const A = "2026-01-10T00:00:00.000Z";
const B = "2026-01-17T00:00:00.000Z";
const snap = (h, pct, resets = A) =>
  ({ at: new Date(BASE + h * H).toISOString(), weekly: { pct, resets_at: resets } });

/** Opus buckets (weight 1) spreading `perHour` weighted tokens evenly over 10-minute buckets in [fromH, toH). */
function usage(fromH, toH, perHour, into = {}) {
  for (let m = fromH * 60; m < toH * 60; m += 10) {
    const b = bucketOf(BASE + m * 60e3);
    const cell = ((into[b] ??= {}).opus ??= { in: 0, out: 0, cc: 0, cr: 0, w: 0 });
    cell.in += perHour / 6;
    cell.w += perHour / 6;
  }
  return into;
}

test("bar 1: fixture fit-week.json -> k = 0.001, rms = 0, pairs = 4", () => {
  const r = fit(FIX.snapshots, FIX.buckets, { now: FIX_NOW, weights: W });
  near(r.k, 0.001);
  near(r.rms, 0);
  near(r.unmetered, 0);
  assert.equal(r.pairs, 4);
  assert.equal(r.hours, 8);
  assert.deepEqual(r.mix, { opus: 1 });
});

test("bar 2: only 2 pairs -> k null", () => {
  const r = fit([snap(0, 10), snap(4, 14), snap(8, 18)], usage(0, 8, 1000), { now: BASE + 8 * H, weights: W });
  assert.equal(r.pairs, 2);
  assert.equal(r.k, null);
  assert.equal(r.rms, null);
  assert.equal(r.unmetered, null);
});

test("bar 3: sum of dt 4 h -> k null", () => {
  const r = fit([0, 1, 2, 3, 4].map((h) => snap(h, 10 + h)), usage(0, 4, 1000), { now: BASE + 4 * H, weights: W });
  assert.equal(r.pairs, 4);
  assert.equal(r.hours, 4);
  assert.equal(r.k, null);
});

test("bar 3b: no ledger weight in the pairs -> k null", () => {
  const r = fit(FIX.snapshots, {}, { now: FIX_NOW, weights: W });
  assert.equal(r.pairs, 4);
  assert.equal(r.k, null);
});

test("bar 4: a pair with negative dpct is excluded", () => {
  const snaps = [...FIX.snapshots, snap(10, 15), snap(12, 17)];
  const r = fit(snaps, usage(0, 12, 1000), { now: BASE + 12 * H, weights: W });
  assert.equal(r.pairs, 5); // 8->10 dropped 3 points: excluded
  near(r.k, 0.001);
  near(r.rms, 0);
});

test("bar 5: pairs across two windows are pooled", () => {
  const a = [snap(0, 10, A), snap(2, 12, A), snap(4, 14, A)];
  const b = [snap(24, 30, B), snap(26, 32, B), snap(28, 34, B)];
  const buckets = usage(24, 28, 1000, usage(0, 4, 1000));
  const now = BASE + 28 * H;
  assert.equal(fit(a, buckets, { now, weights: W }).k, null, "one window alone has 2 pairs");
  const r = fit([...a, ...b], buckets, { now, weights: W });
  assert.equal(r.pairs, 4);
  near(r.k, 0.001);
});

test("bar 5b: resets_at jitter (15:59:59.8 vs 16:00:00.1) is the same window, as in cc-pace", () => {
  const jit = ["2026-01-09T23:59:59.814Z", "2026-01-10T00:00:00.080Z", "2026-01-09T23:59:59.922Z", A, "2026-01-10T00:00:00.337Z"];
  const snaps = FIX.snapshots.map((s, i) => ({ ...s, weekly: { ...s.weekly, resets_at: jit[i] } }));
  const r = fit(snaps, FIX.buckets, { now: FIX_NOW, weights: W });
  assert.equal(r.pairs, 4);
  near(r.k, 0.001);
  const bad = fit(snaps.map((s) => ({ ...s, weekly: { ...s.weekly, resets_at: "nope" } })), FIX.buckets, { now: FIX_NOW, weights: W });
  assert.equal(bad.pairs, 0, "unparseable resets_at dropped");
});

test("bar 6: a pair straddling resets_at is excluded", () => {
  const snaps = [snap(0, 10, A), snap(2, 12, A), snap(4, 14, A), snap(6, 16, A), snap(8, 50, B), snap(10, 52, B)];
  const r = fit(snaps, usage(0, 10, 1000), { now: BASE + 10 * H, weights: W });
  assert.equal(r.pairs, 4);
  near(r.k, 0.001);
  near(r.rms, 0);
});

test("bar 7: unmetered is signed; 0.5 %/h unseen by the ledger -> about +0.5", () => {
  // 3 busy half-hours (1,000 w each), then 10 idle 12 h pairs; 0.5 %/h accrues the whole time.
  const hs = [0, 0.5, 1, 1.5, ...Array.from({ length: 10 }, (_, i) => 1.5 + 12 * (i + 1))];
  const pct = (h) => 10 + 0.001 * 2000 * Math.min(h, 1.5) + 0.5 * h;
  const snaps = hs.map((h) => snap(h, pct(h)));
  const now = BASE + hs.at(-1) * H;
  const r = fit(snaps, usage(0, 1.5, 2000), { now, weights: W });
  assert.equal(r.pairs, 13);
  near(r.unmetered, 0.5, 0.01);
  assert.ok(r.unmetered > 0);

  // Ledger over-counts: idle pairs show weight but no percent -> negative.
  const snaps2 = [0, 0.5, 1, 1.5, ...Array.from({ length: 10 }, (_, i) => 1.5 + 12 * (i + 1))]
    .map((h) => snap(h, 10 + 0.001 * 20000 * Math.min(h, 1.5)));
  const r2 = fit(snaps2, usage(1.5, 121.5, 10, usage(0, 1.5, 20000)), { now, weights: W });
  assert.ok(r2.k > 0);
  assert.ok(r2.unmetered < 0, String(r2.unmetered));
});

test("bar 8: backtest on the fixture -> mae 0", () => {
  const r = backtest(FIX.snapshots, FIX.buckets, { now: FIX_NOW, weights: W });
  assert.equal(r.n, 1); // k needs 3 pairs / 6 h: only s_j = 8 h (s_i = 6 h) is predictable
  near(r.mae, 0);
  near(r.max_err, 0);
  assert.equal(r.under_predict, 0);
});

test("bar 8b: backtest with ±1 noise on the snapshots -> mae <= 1", () => {
  let seed = 7;
  const rnd = () => ((seed = (seed * 1103515245 + 12345) % 2147483648) / 2147483648) * 2 - 1;
  const hs = Array.from({ length: 73 }, (_, i) => i);
  const snaps = hs.map((h) => snap(h, 10 + 3 * h + rnd()));
  const r = backtest(snaps, usage(0, 72, 3000), { now: BASE + 72 * H, weights: W });
  assert.ok(r.n > 50, String(r.n));
  assert.ok(r.mae <= 1, String(r.mae));
  assert.ok(r.max_err <= 2.5, String(r.max_err));
});

test("bar 8c: backtest fits k only on pairs ending at or before s_i (a later pair would change k)", () => {
  // Hours 0-8 at k = 0.001; 8 -> 10 jumps 6 points on the same 2,000 w (a later, steeper pair).
  const snaps = [...FIX.snapshots, snap(10, 24)];
  const r = backtest(snaps, usage(0, 10, 1000), { now: BASE + 10 * H, weights: W });
  // Walk-forward: j=8 uses k 0.001 (err 0); j=10 uses k from 4 pairs = 0.001 (pred 20, err -4).
  // Leaking the 8->10 pair would give k 0.0014 and errors 0.8 / 3.2.
  assert.equal(r.n, 2);
  near(r.mae, 2);
  near(r.max_err, 4);
  assert.equal(r.under_predict, 1);
});

test("bar 9: weights change fit's dw even though the stored bucket w is unchanged", () => {
  const stored = JSON.stringify(FIX.buckets);
  const r = fit(FIX.snapshots, FIX.buckets, { now: FIX_NOW, weights: { ...W, opus: 2 } });
  near(r.k, 0.0005);
  assert.equal(JSON.stringify(FIX.buckets), stored, "buckets not mutated");
  // A stale stored w is ignored: w comes from the raw counts.
  const bad = JSON.parse(stored);
  for (const fams of Object.values(bad)) fams.opus.w = 999999;
  near(fit(FIX.snapshots, bad, { now: FIX_NOW, weights: W }).k, 0.001);
});

test("fit: pairs outside 0.5-12 h and outside the last 14 days are ignored", () => {
  const snaps = [0, 0.5, 2, 20, 22, 24, 26].map((h) => snap(h, 10 + h));
  const buckets = usage(0, 26, 1000);
  // 0->0.5 ok (0.5 h), 0.5->2 ok, 2->20 too long (18 h), then 3 pairs.
  const r = fit(snaps, buckets, { now: BASE + 26 * H, weights: W });
  assert.equal(r.pairs, 5);
  near(r.k, 0.001);
  const short = fit([0, 0.25, 2, 20, 22, 24, 26].map((h) => snap(h, 10 + h)), buckets, { now: BASE + 26 * H, weights: W });
  assert.equal(short.pairs, 4, "0 -> 0.25 h is too short");
  // 14 days later only the pairs ending after now - 14 d count: 22->24, 24->26.
  const late = fit(snaps, buckets, { now: BASE + (22 + 14 * 24) * H, weights: W });
  assert.equal(late.pairs, 2);
  assert.equal(late.k, null);
  // Snapshots after `now` are not used.
  assert.equal(fit(snaps, buckets, { now: BASE + 2 * H, weights: W }).pairs, 2);
});

test("fit/backtest text lines", () => {
  const f = fit(FIX.snapshots, FIX.buckets, { now: FIX_NOW, weights: W });
  assert.equal(fitLine(f), "fit: k=0.001 pairs=4 rms=0.000 unmetered=0.000%/h mix=opus:1.00");
  assert.equal(fitLine({ k: null, rms: null, unmetered: null, pairs: 0, mix: {} }), "fit: k=null pairs=0 rms=null unmetered=null%/h mix=");
  const b = backtest(FIX.snapshots, FIX.buckets, { now: FIX_NOW, weights: W });
  assert.equal(backtestLine(b), "backtest: n=1 mae=0.000 max_err=0.000 under_predict=0");
});

test("bar 13: CLI fit/backtest --json print one JSON object; text lines; unknown flag -> 2", () => {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "cclf-"));
  const orch = path.join(home, ".config", "orchestrator");
  fs.mkdirSync(orch, { recursive: true });
  // Shift the fixture so its last snapshot is the current hour (the CLI fits against Date.now()).
  const shift = Math.floor(Date.now() / H) * H - FIX_NOW;
  const iso = (s) => new Date(Date.parse(s) + shift).toISOString();
  const snaps = FIX.snapshots.map((s) => ({ ...s, at: iso(s.at), weekly: { ...s.weekly, resets_at: iso(s.weekly.resets_at) } }));
  const buckets = Object.fromEntries(Object.entries(FIX.buckets).map(([b, v]) => [bucketOf(Date.parse(b) + shift), v]));
  fs.writeFileSync(path.join(orch, "cc-usage.jsonl"), snaps.map((s) => JSON.stringify(s)).join("\n") + "\nnot json\n");
  fs.writeFileSync(path.join(orch, "cc-ledger.json"), JSON.stringify({ v: 1, scanned_at: null, files: {}, ids: {}, buckets }));
  const cli = (args) => spawnSync(process.execPath, [BIN, ...args], {
    env: { ...process.env, ORCH_HOME: home, ORCH_CC_PROJECTS: path.join(home, "none") }, encoding: "utf8", timeout: 30000,
  });

  const fj = cli(["fit", "--json"]);
  assert.equal(fj.status, 0, fj.stderr);
  assert.equal(fj.stdout.trim().split("\n").length, 1);
  const fo = JSON.parse(fj.stdout);
  near(fo.k, 0.001);
  assert.equal(fo.pairs, 4);
  const bj = cli(["backtest", "--json"]);
  assert.equal(bj.status, 0, bj.stderr);
  assert.equal(bj.stdout.trim().split("\n").length, 1);
  assert.deepEqual(Object.keys(JSON.parse(bj.stdout)).sort(), ["mae", "max_err", "n", "under_predict"]);

  const ft = cli(["fit"]);
  assert.equal(ft.status, 0);
  assert.match(ft.stdout, /^fit: k=0\.001 pairs=4 rms=0\.000 unmetered=0\.000%\/h mix=opus:1\.00\n$/);
  const bt = cli(["backtest"]);
  assert.equal(bt.status, 0);
  assert.match(bt.stdout, /^backtest: n=1 mae=0\.000 max_err=0\.000 under_predict=0\n$/);

  for (const args of [["fit", "--nope"], ["backtest", "--hours", "3"], ["fit", "--budget-ms", "1"]]) {
    const r = cli(args);
    assert.equal(r.status, 2, args.join(" "));
    assert.match(r.stderr, /usage: cc-ledger/);
    assert.equal(r.stdout, "");
  }
});

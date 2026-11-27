import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { goResetProbeTick } from "../bin/desk-check.mjs";

// 2026-11-30 is a Monday (2026-11-27 is a Friday): week boundaries are exact midnights.
const MON = Date.UTC(2026, 10, 30, 0, 0, 0);
const WEEK = 7 * 24 * 3600_000;
const iso = (ms) => new Date(ms).toISOString();

function tmpState() {
  return path.join(fs.mkdtempSync(path.join(os.tmpdir(), "orch-go-reset-")), "go-reset-probe.json");
}
const read = (p) => JSON.parse(fs.readFileSync(p, "utf8"));

test("no state writes the boundary and never runs (a first install never probes)", () => {
  const statePath = tmpState();
  let runs = 0;
  const r = goResetProbeTick({ now: MON + 12 * 3600_000, limits: {}, statePath, run: () => { runs++; } });
  assert.deepEqual(r, { ran: false, boundary: MON });
  assert.equal(runs, 0);
  assert.equal(read(statePath).last_reset_probe, iso(MON));
});

test("unreadable state is treated like missing: boundary written, no run", () => {
  const statePath = tmpState();
  fs.writeFileSync(statePath, "{not json");
  let runs = 0;
  const r = goResetProbeTick({ now: MON + 12 * 3600_000, limits: {}, statePath, run: () => { runs++; } });
  assert.deepEqual(r, { ran: false, boundary: MON });
  assert.equal(runs, 0);
  assert.equal(read(statePath).last_reset_probe, iso(MON));
});

test("first tick after a Monday 00:00 UTC runs once; the next tick does not", () => {
  const statePath = tmpState();
  let runs = 0;
  const run = () => { runs++; };
  fs.writeFileSync(statePath, JSON.stringify({ last_reset_probe: iso(MON) }) + "\n");
  const after = MON + WEEK + 60_000;
  const first = goResetProbeTick({ now: after, limits: {}, statePath, run });
  assert.deepEqual(first, { ran: true, boundary: MON + WEEK });
  assert.equal(runs, 1);
  assert.equal(read(statePath).last_reset_probe, iso(MON + WEEK));
  const second = goResetProbeTick({ now: after + 3600_000, limits: {}, statePath, run });
  assert.deepEqual(second, { ran: false, boundary: MON + WEEK });
  assert.equal(runs, 1, "no new boundary, no second run");
});

test("after a fake period reset (anchor set) the probe runs again; then it is quiet", () => {
  const statePath = tmpState();
  let runs = 0;
  const run = () => { runs++; };
  const now = MON + WEEK + 60_000; // Monday 2026-12-07 00:01 UTC
  fs.writeFileSync(statePath, JSON.stringify({ last_reset_probe: iso(MON + WEEK) }) + "\n");
  // Same week, no anchor: quiet.
  assert.deepEqual(goResetProbeTick({ now, limits: {}, statePath, run }), { ran: false, boundary: MON + WEEK });
  assert.equal(runs, 0);
  // A period starting 00:00:30 today is a newer boundary than the week's midnight: run.
  const anchor = iso(MON + WEEK + 30_000);
  const reset = goResetProbeTick({ now, limits: { go: { period_anchor: anchor } }, statePath, run });
  assert.deepEqual(reset, { ran: true, boundary: MON + WEEK + 30_000 });
  assert.equal(runs, 1);
  assert.equal(read(statePath).last_reset_probe, anchor);
  // Same tick again: quiet.
  assert.deepEqual(goResetProbeTick({ now, limits: { go: { period_anchor: anchor } }, statePath, run }), { ran: false, boundary: MON + WEEK + 30_000 });
  assert.equal(runs, 1);
});

test("a throwing run returns {ran:false} with the state already written (no retry storm)", () => {
  const statePath = tmpState();
  fs.writeFileSync(statePath, JSON.stringify({ last_reset_probe: iso(MON) }) + "\n");
  const after = MON + WEEK + 60_000;
  const r = goResetProbeTick({
    now: after,
    limits: {},
    statePath,
    run: () => { throw new Error("spawn ESRCH"); },
  });
  assert.deepEqual(r, { ran: false });
  assert.equal(read(statePath).last_reset_probe, iso(MON + WEEK), "boundary written before run()");
  let runs = 0;
  const again = goResetProbeTick({ now: after, limits: {}, statePath, run: () => { runs++; } });
  assert.deepEqual(again, { ran: false, boundary: MON + WEEK });
  assert.equal(runs, 0, "the failed probe is not retried on the next tick");
});

test("a tick with no new boundary never runs, even far inside the week", () => {
  const statePath = tmpState();
  fs.writeFileSync(statePath, JSON.stringify({ last_reset_probe: iso(MON) }) + "\n");
  let runs = 0;
  const r = goResetProbeTick({ now: MON + 6 * 24 * 3600_000, limits: {}, statePath, run: () => { runs++; } });
  assert.deepEqual(r, { ran: false, boundary: MON });
  assert.equal(runs, 0);
});

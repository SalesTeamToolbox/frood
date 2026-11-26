import test from "node:test";
import assert from "node:assert/strict";
import { gate } from "../bin/verdict-gate.mjs";

const doc = (verdict, blast, findings = "1. [minor] a.py:1 — nit — none") =>
  `VERDICT: ${verdict}\nTESTS: pytest -> 10 passed\nBLAST RADIUS:\n${blast}\n${findings}\nSENIOR_REVIEW: not-needed — small`;

test("clean approval stands; free approval is marked APPROVED_FREE", () => {
  const d = doc("APPROVED", "- a.py:3 — unchanged\n- b.py:9 — intended (Mandate rule 2)");
  assert.equal(gate(d).effective, "APPROVED");
  assert.equal(gate(d, { free: true }).effective, "APPROVED_FREE");
  assert.equal(gate(d, { free: true }).overridden, false);
});

test("an UNREQUESTED caller change overrides APPROVED (the bake-off failure)", () => {
  const d = doc("APPROVED", "- keys.py:120 — intended\n- known_orgs.py:81 — UNREQUESTED: junk state now matches the \"\" bucket (false Signed up)");
  const r = gate(d, { free: true });
  assert.equal(r.effective, "CHANGES_REQUESTED");
  assert.equal(r.overridden, true);
  assert.equal(r.unrequested.length, 1);
});

test("a [major] finding overrides APPROVED", () => {
  const r = gate(doc("APPROVED", "- a.py:1 — unchanged", "1. [major] ledger.py:247 — wildcard — guard"));
  assert.equal(r.effective, "CHANGES_REQUESTED");
});

test("missing verdict or missing caller trace is INVALID, not approval", () => {
  assert.equal(gate("looks good to me").effective, "INVALID");
  assert.equal(gate("VERDICT: APPROVED\nTESTS: ok\n1. [minor] x").effective, "INVALID");
  assert.equal(gate("VERDICT: APPROVED\nBLAST RADIUS:\n\n1. [minor] x").effective, "INVALID");
});

test("CHANGES_REQUESTED from the critic stands", () => {
  assert.equal(gate(doc("CHANGES_REQUESTED", "- a.py:1 — unchanged")).effective, "CHANGES_REQUESTED");
});

test("UNREQUESTED only as the tag: prose mention in an intended line is ignored (the real case)", () => {
  const d = doc("APPROVED", "- boardRounds (desk.mjs:926) — new pure helper; its four callers are the lines above, all inside desk.mjs; no callers elsewhere in the repo; no UNREQUESTED callers.");
  const r = gate(d);
  assert.equal(r.effective, "APPROVED");
  assert.equal(r.overridden, false);
  assert.equal(r.unrequested.length, 0);
});

test("negated UNREQUESTED wording in tagged lines does not count", () => {
  const d = doc("APPROVED", "- a.py:1 — unchanged; no UNREQUESTED change\n- b.py:2 — intended (nothing UNREQUESTED)");
  const r = gate(d);
  assert.equal(r.effective, "APPROVED");
  assert.equal(r.overridden, false);
  assert.equal(r.unrequested.length, 0);
});

test("UNREQUESTED tag still overrides APPROVED: plain, emphasized, backticked, en-dash, double-dash", () => {
  const blasts = [
    "- x.py:9 — UNREQUESTED: …",
    "- x.py:9 — **UNREQUESTED**: …",
    "- x.py:9 – UNREQUESTED",
    "- x.py:9 -- UNREQUESTED: …",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "CHANGES_REQUESTED", blast);
    assert.equal(r.overridden, true, blast);
    assert.equal(r.unrequested.length, 1, blast);
  }
});

test("fail safe: UNREQUESTED with no separator still counts", () => {
  const d = doc("APPROVED", "- UNREQUESTED change in x.py:9 with no separator");
  const r = gate(d);
  assert.equal(r.effective, "CHANGES_REQUESTED");
  assert.equal(r.overridden, true);
  assert.equal(r.unrequested.length, 1);
});

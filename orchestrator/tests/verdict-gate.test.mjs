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

test("UNREQUESTED still counts when an earlier dash precedes the tag (senior finding 1)", () => {
  const blasts = [
    "- orchestrator/bin/x.mjs:10 (a - b) — UNREQUESTED: changes y",
    "- foo.mjs:3 -- helper (a - b) — UNREQUESTED: z",
    "- desk.mjs:1324 – verdict path — UNREQUESTED: changed",
    "- node x.mjs -- --free (cli) — UNREQUESTED: flag changed",
    "- oc-worker.mjs:1018-1021 runChain: UNREQUESTED. No fallback hop — see finding 2",
    "- x.mjs:10: UNREQUESTED: changes y - and z",
    "- oc-worker.mjs:863 watch(child.pid) — unchanged; the receipt can now list serve in orphans_killed — UNREQUESTED: not asked",
    "- run.ts (150-161) — intended (deviation 3). A job with no sealed config now pauses - UNREQUESTED: ticket 5 must seal {}",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "CHANGES_REQUESTED", blast);
    assert.equal(r.overridden, true, blast);
    assert.equal(r.unrequested.length, 1, blast);
  }
});

test("UNREQUESTED counts with punctuation around/after the tag (senior finding 2)", () => {
  const blasts = [
    "- x.py:9 — UNREQUESTED. changed y",
    "- x.py:9 — UNREQUESTED; changed y",
    "- x.py:9 — UNREQUESTED, changed y",
    "- x.py:9 — *UNREQUESTED*: …",
    "- x.py:9 — ***UNREQUESTED***: …",
    "- x.py:9 — [UNREQUESTED]: …",
    "- x.py:9 — (UNREQUESTED) …",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "CHANGES_REQUESTED", blast);
    assert.equal(r.overridden, true, blast);
    assert.equal(r.unrequested.length, 1, blast);
  }
});

test("intended tag after an earlier dash is still the tag; its UNREQUESTED detail is ignored", () => {
  const d = doc("APPROVED", "- c.py:3 (a - b) — intended: nothing UNREQUESTED");
  const r = gate(d);
  assert.equal(r.effective, "APPROVED");
  assert.equal(r.overridden, false);
  assert.equal(r.unrequested.length, 0);
});

test("backtick-wrapped unchanged tag then `: UNREQUESTED none` still passes (senior must-pass)", () => {
  const d = doc("APPROVED", "- b.py:2 -- `unchanged`: UNREQUESTED none");
  const r = gate(d);
  assert.equal(r.effective, "APPROVED");
  assert.equal(r.overridden, false);
  assert.equal(r.unrequested.length, 0);
});

// Pass bar 1: the real false positive — a doc whose only blast line is the new-format
// form of gate-unrequested-tag/findings-r4.md:7 must stay APPROVED.
test("tag-first intended line quoting UNREQUESTED in its detail stays APPROVED (pass bar 1)", () => {
  const d = doc("APPROVED", "- intended — orchestrator/bin/board.mjs:928: two-clause lines such as `— unchanged; … — UNREQUESTED: …` override APPROVED again");
  const r = gate(d);
  assert.equal(r.effective, "APPROVED");
  assert.equal(r.overridden, false);
  assert.equal(r.unrequested.length, 0);
});

// Pass bar 2: new-format tag-first lines whose detail mentions UNREQUESTED stay APPROVED.
test("tag-first unchanged/intended lines with UNREQUESTED in the detail do not count (pass bar 2)", () => {
  const blasts = [
    "- unchanged — a.py:1 — UNREQUESTED: quoted in prose",
    "- intended — b.py:2: no UNREQUESTED callers",
    "- **intended** — c.py:3 (nothing UNREQUESTED)",
    "- unchanged: d.py:4 — UNREQUESTED",
    "- intended | e.py:5 — UNREQUESTED",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "APPROVED", blast);
    assert.equal(r.overridden, false, blast);
    assert.equal(r.unrequested.length, 0, blast);
  }
});

// Pass bar 3: new format catches — tag-first UNREQUESTED overrides APPROVED in every form.
test("tag-first UNREQUESTED line overrides APPROVED: plain, emphasized, backticked, bracketed, colon, lowercase, no separator (pass bar 3)", () => {
  const blasts = [
    "- UNREQUESTED — x.py:9: …",
    "- **UNREQUESTED** — x.py:9: …",
    "- `UNREQUESTED` — x.py:9",
    "- [UNREQUESTED] x.py:9",
    "- UNREQUESTED: x.py:9 …",
    "- unrequested — x.py:9: …",
    "- UNREQUESTED x.py:9 changed",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "CHANGES_REQUESTED", blast);
    assert.equal(r.overridden, true, blast);
    assert.equal(r.unrequested.length, 1, blast);
  }
});

// Pass bar 4: every senior-r2/r3 line still CHANGES_REQUESTED in old format, and its
// tag-first rewrite also CHANGES_REQUESTED; senior-r2.md:34 (INVALID rules … unchanged) does not count.
const SENIOR_R2 = [
  "- orchestrator/bin/board.mjs:928 (round verdict from a critic receipt) — UNREQUESTED: a blast line whose tag is UNREQUESTED but has an earlier dash, a colon separator with a dash in the detail, or punctuation after the tag no longer overrides APPROVED; the Mandate expects \"lines whose tag is UNREQUESTED still override APPROVED\"",
  "- orchestrator/bin/board.mjs:944 (round verdict from a native subagent) — UNREQUESTED: same miss, and this path is always treated as a paid review, so the wrong APPROVED is final for the round",
  "- orchestrator/bin/board.mjs:1065 (signoff refusal on non-APPROVED) — UNREQUESTED: same miss; signoff no longer refuses a findings file carrying such a line",
  "- orchestrator/bin/desk.mjs:1324 (desk verdict) — UNREQUESTED: same miss; the desk records APPROVED and moves the ticket on instead of sending it back",
  "- orchestrator/bin/oc-worker.mjs:1548 (receipt verdict; :1701 on main) — UNREQUESTED: same miss; the receipt's gate result says APPROVED, and board.mjs:928 then reads that receipt",
];
const SENIOR_R3 = [
  "- orchestrator/bin/board.mjs:928 — UNREQUESTED: a two-clause line ending `— UNREQUESTED:` no longer overrides APPROVED at 26d90cc7",
  "- orchestrator/bin/board.mjs:944 — UNREQUESTED: same miss",
  "- orchestrator/bin/board.mjs:1065 — UNREQUESTED: same miss",
  "- orchestrator/bin/desk.mjs:1324 — UNREQUESTED: same miss",
  "- oc-worker.mjs gate call — UNREQUESTED: same miss",
];
test("senior-r2/r3 old-format lines still CHANGES_REQUESTED; tag-first rewrites also CHANGES_REQUESTED; INVALID-rule line does not count (pass bar 4)", () => {
  for (const blast of [...SENIOR_R2, ...SENIOR_R3]) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "CHANGES_REQUESTED", blast);
    assert.equal(r.overridden, true, blast);
    assert.equal(r.unrequested.length, 1, blast);
  }
  // Tag-first rewrites: - UNREQUESTED — <caller>: <detail>
  for (const blast of [...SENIOR_R2, ...SENIOR_R3]) {
    const caller = blast.split(/ — | – |: /, 2)[0];
    const rewrite = `- UNREQUESTED — ${caller}: rewritten by this ticket`;
    const r = gate(doc("APPROVED", rewrite));
    assert.equal(r.effective, "CHANGES_REQUESTED", rewrite);
    assert.equal(r.overridden, true, rewrite);
    assert.equal(r.unrequested.length, 1, rewrite);
  }
  // senior-r2.md:34 "- INVALID rules … — unchanged" does not count
  const r = gate(doc("APPROVED", "- INVALID rules (no VERDICT line, no BLAST RADIUS entries) and the blocker/major override — unchanged"));
  assert.equal(r.effective, "APPROVED");
  assert.equal(r.overridden, false);
  assert.equal(r.unrequested.length, 0);
});

// Pass bar 5: transition (old format) keeps today's answers.
test("transition: old-format two-clause line and no-separator UNREQUESTED still CHANGES_REQUESTED (pass bar 5)", () => {
  const d = gate(doc("APPROVED", "- unchanged callers in x.py — UNREQUESTED: y"));
  assert.equal(d.effective, "CHANGES_REQUESTED");
  assert.equal(d.overridden, true);
  assert.equal(d.unrequested.length, 1);
  const d2 = gate(doc("APPROVED", "- UNREQUESTED change in x.py:9 with no separator"));
  assert.equal(d2.effective, "CHANGES_REQUESTED");
  assert.equal(d2.overridden, true);
  assert.equal(d2.unrequested.length, 1);
});

// Pass bar (senior-r1 blocker): an old-format line whose caller token starts with
// `unchanged`/`intended` plus an UNSPACED dash must NOT be read as a benign tag-first
// line; it falls through to the transition walk and counts UNREQUESTED. Each failed
// (returned APPROVED) on 9734ba4a.
test("caller token starting with unchanged/intended + unspaced dash still counts UNREQUESTED (senior-r1 blocker)", () => {
  const blasts = [
    "- intended-callers.mjs:3 — UNREQUESTED: real change",
    "- unchanged-callers.test.mjs:12 — UNREQUESTED: real change",
    "- `intended-use.mjs:3` — UNREQUESTED: real change",
    "- Unchanged-by-design paths in a.mjs — UNREQUESTED: y",
    "- unchanged—x — UNREQUESTED: real",
    "- unchanged-UNREQUESTED",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "CHANGES_REQUESTED", blast);
    assert.equal(r.overridden, true, blast);
    assert.equal(r.unrequested.length, 1, blast);
  }
});

// Pass bar (this ticket): decoration before the first word never hides an UNREQUESTED tag.
test("decorated UNREQUESTED blast lines count: emoji, checkbox, numbering, emphasis", () => {
  const blasts = [
    "- ❌ UNREQUESTED — a.mjs:1: x",
    "+ UNREQUESTED — a.mjs:1: x",
    "- [x] UNREQUESTED — a.mjs:1: x",
    "- [ ] UNREQUESTED — a.mjs:1: x",
    "- 1. UNREQUESTED — a.mjs:1: x",
    "1. UNREQUESTED — a.mjs:1: x",
    "- (a) UNREQUESTED — a.mjs:1: x",
    "- **❌ UNREQUESTED** — a.mjs:1: x",
    "- ⚠️ UNREQUESTED — a.mjs:1: x",
    "- • UNREQUESTED — b.mjs:2: x",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "CHANGES_REQUESTED", blast);
    assert.equal(r.overridden, true, blast);
    assert.equal(r.unrequested.length, 1, blast);
  }
});

// Pass bar (this ticket): a decorated UNREQUESTED line counts even when it is not the
// first blast-line entry (real findings-file shape — a plain entry precedes it).
test("decorated UNREQUESTED blast line counts after a plain entry", () => {
  const d = doc(
    "APPROVED",
    "- a.mjs:1 — unchanged\n- ❌ UNREQUESTED — b.mjs:2: the caller now returns null",
  );
  const r = gate(d);
  assert.equal(r.effective, "CHANGES_REQUESTED");
  assert.equal(r.overridden, true);
  assert.equal(r.unrequested.length, 1);
  assert.equal(r.unrequested[0], "- ❌ UNREQUESTED — b.mjs:2: the caller now returns null");
});

test("decorated unchanged/intended blast lines stay APPROVED", () => {
  const blasts = [
    "- ✅ unchanged — a.mjs:1: x",
    "- [x] intended — a.mjs:1: x",
    "- 1. unchanged — a.mjs:1: no UNREQUESTED callers",
  ];
  for (const blast of blasts) {
    const r = gate(doc("APPROVED", blast));
    assert.equal(r.effective, "APPROVED", blast);
    assert.equal(r.overridden, false, blast);
    assert.equal(r.unrequested.length, 0, blast);
  }
});

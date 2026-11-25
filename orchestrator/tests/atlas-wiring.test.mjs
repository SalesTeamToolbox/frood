// The Atlas is part of the loop, not just a repo doc (atlas-m1, plan-atlas-wiring.md §M1).
//
// Three wirings, each asserted on the file a runtime path actually reads:
//   1. worker rule  — every `agents/worker*.md` body orients via the repo map before touching code
//                     (oc-worker reads the agent file it dispatches; the body is the prompt).
//   2. critic check — every `agents/critic*.md` body carries the atlas-freshness check under BLAST RADIUS
//                     (desk.mjs spawns `--agent critic`; verdict-gate.mjs keys off that document's shape).
//   3. Mandate line — `commands/frood-orchestrator.md` step 1 requires "Atlas refs consulted / updated?" and
//                     `tests/fixtures/board/mandate.md` carries it (board.test/oc-worker.test copy that
//                     fixture into a temp repo and run the real `board create` on it).
//
// Bodies only: frontmatter carries model pins, which routing owns (check-routing.mjs), not this test.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const read = (p) => fs.readFileSync(path.join(REPO, p), "utf8").replace(/\r\n/g, "\n");
// The prose is hard-wrapped, so every multi-word assertion runs against a single-space-flattened copy.
const flat = (s) => s.replace(/\s+/g, " ");

// Everything after the closing `---` of the frontmatter. An agent file without frontmatter is a bug, not a pass.
function body(file) {
  const text = read(file);
  const m = text.match(/^---\n[\s\S]*?\n---\n([\s\S]*)$/);
  assert.ok(m, `${file} has frontmatter followed by a body`);
  return m[1];
}

// Each variant set: the base file plus every pool/fallback copy that must stay in sync with it.
const WORKERS = ["worker.md", "worker-free.md", "worker-nvidia.md", "worker-strong.md"];
const CRITICS = ["critic.md", "critic-go.md", "critic-free.md", "critic-nvidia.md"];

// ---------------------------------------------------------------- 1. worker rule: orient via the repo map first
test("worker rule: every worker variant orients via the repo map (docs/ATLAS.md, docs/atlas/, or the map CLAUDE.md/AGENTS.md names) before touching code", () => {
  for (const f of WORKERS) {
    const b = flat(body(`agents/${f}`));
    assert.match(b, /Orient via the repo map first/, `${f} names the orient rule`);
    assert.match(b, /docs\/ATLAS\.md/, `${f} names docs/ATLAS.md`);
    assert.match(b, /docs\/atlas\//, `${f} names a docs\/atlas\/ directory`);
    assert.match(b, /its `CLAUDE\.md` \/ `AGENTS\.md` names as the place to orient/, `${f} falls back to the map CLAUDE.md/AGENTS.md names`);
    assert.match(b, /the Mandate may name the map entry points to start from/i, `${f} lets the Mandate name entry points`);
    // The rule must sit among the rules, before the first command the worker runs.
    assert.ok(b.indexOf("Orient via the repo map first") < b.indexOf("Run the Mandate's test command"), `${f} orients before testing`);
  }
});

test("worker rule: all worker variants carry the identical body, so every pool orients the same way", () => {
  const first = body(`agents/${WORKERS[0]}`);
  for (const f of WORKERS.slice(1)) assert.equal(body(`agents/${f}`), first, `${f} body matches ${WORKERS[0]}`);
});

// ---------------------------------------------------------------- 2. critic check: atlas freshness under BLAST RADIUS
test("critic check: every critic variant makes an atlas-referenced rename/move without a same-commit map update a major finding under BLAST RADIUS", () => {
  for (const f of CRITICS) {
    const b = flat(body(`agents/${f}`));
    assert.match(b, /Atlas freshness/, `${f} names the atlas-freshness check`);
    assert.match(b, /renames, moves, or reshapes a symbol, route, page or model the map references/, `${f} names the changed shapes`);
    assert.match(b, /the \*\*same commit\*\* must update the map/, `${f} requires the map update in the same commit`);
    assert.match(b, /\*\*major\*\* finding/, `${f} grades it major, so the gate turns it into CHANGES_REQUESTED`);
    assert.match(b, /Say `no map` plainly/, `${f} says "no map" instead of inventing a finding`);
    // It is part of the blast-radius step, not a separate pass: after the BLAST RADIUS heading, before step 5.
    const blast = b.indexOf("Blast radius — mandatory");
    const atlas = b.indexOf("Atlas freshness");
    const next = b.indexOf("5. On round > 1");
    assert.ok(blast >= 0 && atlas > blast && next > atlas, `${f} places the check inside the blast-radius step`);
  }
});

test("critic check: every critic variant carries the same atlas-freshness wording", () => {
  const block = (f) => flat(body(`agents/${f}`)).split("Atlas freshness")[1]?.split("5. On round > 1")[0] ?? "";
  const first = block(CRITICS[0]);
  assert.ok(first.length > 0, `${CRITICS[0]} carries the check`);
  for (const f of CRITICS.slice(1)) assert.equal(block(f), first, `${f} mirrors the check identically`);
});

// ---------------------------------------------------------------- 3. Mandate line: where Mandates are born
test("Mandate line: commands/frood-orchestrator.md step 1 requires an 'Atlas refs consulted / updated?' line in every Mandate", () => {
  const cmd = flat(read("commands/frood-orchestrator.md"));
  assert.match(cmd, /Atlas refs consulted \/ updated\?/, "the command names the line verbatim");
  assert.match(cmd, /every Mandate carries the line/i, "the line is required, not suggested");
  assert.match(cmd, /say `no map` plainly when the repo has none/, "a repo without a map still answers the line");
  // It belongs to the ticket/Mandate step, which is step 1 of the worker → critic loop.
  const step1 = cmd.indexOf("Ticket + Mandate");
  const line = cmd.indexOf("Atlas refs consulted / updated?");
  assert.ok(step1 >= 0 && line > step1, "the line is wired into the Ticket + Mandate step");
  assert.ok(line < cmd.indexOf("2. **Worker** codes"), "it is required before any worker is dispatched");
});

test("Mandate line: the standing board fixture carries the Atlas line, so the runtime `board create` path sees it", () => {
  const fixture = read("tests/fixtures/board/mandate.md");
  assert.match(fixture, /^\*\*Atlas refs consulted \/ updated\?\*\*\s+\S/m, "the fixture answers the Atlas line");
});

test("Mandate line: `board create` refuses a Mandate that does not answer it (the enforcement behind the line)", () => {
  // The board's own --help is rendered from its source header at run time, so this is a runtime read of the
  // contract, not a copy of it. The refusal itself is covered by tests/board.test.mjs case 5b.
  const r = spawnSync(process.execPath, [path.join(REPO, "bin", "board.mjs"), "--help"], { encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /Atlas refs consulted \/ updated\?/, "create's contract names the Atlas line");
  assert.match(read("bin/board.mjs"), /mandate has no Atlas line/, "create refuses without it");
});

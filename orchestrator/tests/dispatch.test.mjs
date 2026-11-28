import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// dispatch.mjs reads the board's ticket files and adapter.json, so every case builds a temp repo and spawns the CLI.
const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "dispatch.mjs");
const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function mk(adapterExtra = {}) {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "orch-dispatch-"));
  CLEAN.push(repo);
  assert.equal(spawnSync("git", ["-C", repo, "init", "-q", "-b", "main"]).status, 0);
  fs.mkdirSync(path.join(repo, ".opencode", "board", "tickets"), { recursive: true });
  fs.writeFileSync(path.join(repo, ".opencode", "board", "adapter.json"), JSON.stringify({ base: "main", gates: [["true"]], ...adapterExtra }));
  return repo;
}
// A board ticket (schema 1) with a Mandate carrying optional `depends:` lines.
function ticket(repo, id, { scope = [], callers = [], tests = [], depends = [], stage = "queued", session = null, created = undefined, egm = undefined } = {}) {
  const mandate = path.join(repo, `${id}.mandate.md`);
  fs.writeFileSync(mandate, `# ${id}\n${depends.length ? `depends: ${depends.join(", ")}\n` : ""}`);
  fs.writeFileSync(
    path.join(repo, ".opencode", "board", "tickets", `${id}.json`),
    JSON.stringify({
      schema: 1,
      id,
      stage,
      mandate_path: mandate,
      scope,
      blast_radius: [...callers.map((c) => ({ caller: c, expect: "unchanged" })), ...tests.map((t) => ({ caller: "new code", expect: "x", test: t }))],
      ...(created ? { created } : {}),
      ...(egm ? { egm: { status: egm } } : {}),
      assignment: session ? { owner: null, session } : stage === "working" ? { owner: "s1" } : null,
    }),
  );
}
const run = (repo, ...args) => spawnSync(process.execPath, [BIN, ...args, "--repo", repo], { encoding: "utf8" });
const plan = (repo, ...ids) => {
  const r = run(repo, "plan", ...ids, "--json");
  assert.equal(r.status, 0, r.stderr);
  return JSON.parse(r.stdout);
};

test("plan: tickets with disjoint files share one group", () => {
  const r = mk();
  ticket(r, "a-one", { scope: ["src/a.mjs"] });
  ticket(r, "b-one", { scope: ["src/b.mjs"], callers: ["`run()` in `lib/b.mjs`"] });
  assert.deepEqual(plan(r, "a-one", "b-one").groups, [["a-one", "b-one"]]);
});

test("plan: two tickets sharing a file are never grouped together", () => {
  const r = mk();
  ticket(r, "a-one", { scope: ["src/shared.mjs", "src/a.mjs"] });
  ticket(r, "b-one", { scope: ["src/b.mjs", "src/shared.mjs"] });
  ticket(r, "c-one", { scope: ["src/c.mjs"] });
  const p = plan(r, "a-one", "b-one", "c-one");
  assert.deepEqual(p.groups, [["a-one", "c-one"], ["b-one"]]);
  assert.equal(p.conflicts[0].why, "shared file src/shared.mjs");
});

test("plan: overlap through a blast-radius caller, a directory or a glob also serialises", () => {
  const r = mk();
  ticket(r, "a-one", { scope: ["src/a.mjs"], callers: ["`x()` in `lib/core.mjs`"] });
  ticket(r, "b-one", { scope: ["lib/core.mjs"] });
  ticket(r, "c-one", { scope: ["src"] });
  ticket(r, "d-one", { scope: ["docs/*.md"] });
  ticket(r, "e-one", { scope: ["docs/ATLAS.md"] });
  const p = plan(r, "a-one", "b-one", "c-one", "d-one", "e-one");
  const together = (x, y) => p.groups.some((g) => g.includes(x) && g.includes(y));
  assert.equal(together("a-one", "b-one"), false, "caller path equals the other's scope");
  assert.equal(together("a-one", "c-one"), false, "a directory contains the file");
  assert.equal(together("d-one", "e-one"), false, "a glob covers the file");
  assert.equal(together("b-one", "c-one"), true, "lib/ and src/ are disjoint");
});

test("plan: a whole-repo scope (`.`, `./` or the repo root path) overlaps every ticket — never fails open", () => {
  const r = mk();
  ticket(r, "a-one", { scope: ["src/a.mjs"] });
  ticket(r, "dot-one", { scope: ["."] });
  ticket(r, "slash-one", { scope: ["./"] });
  ticket(r, "root-one", { scope: [r] });
  ticket(r, "b-one", { scope: ["docs/b.md"] });
  const p = plan(r, "a-one", "dot-one", "slash-one", "root-one", "b-one");
  const together = (x, y) => p.groups.some((g) => g.includes(x) && g.includes(y));
  for (const whole of ["dot-one", "slash-one", "root-one"]) {
    assert.equal(together(whole, "a-one"), false, `${whole} overlaps src/a.mjs`);
    assert.equal(together(whole, "b-one"), false, `${whole} overlaps docs/b.md`);
  }
  assert.equal(together("a-one", "b-one"), true, "disjoint files still share a group");
});

test("plan: a depends: chain stays serial, in dependency order, even when files are disjoint", () => {
  const r = mk();
  ticket(r, "t-three", { scope: ["c.mjs"], depends: ["t-two"] });
  ticket(r, "t-two", { scope: ["b.mjs"], depends: ["t-one"] });
  ticket(r, "t-one", { scope: ["a.mjs"] });
  assert.deepEqual(plan(r, "t-three", "t-two", "t-one").groups, [["t-one"], ["t-two"], ["t-three"]]);
});

test("plan: a dependency on an unshipped ticket outside the list holds the ticket; a shipped one does not", () => {
  const r = mk();
  ticket(r, "out-one", { scope: ["o.mjs"], stage: "working" });
  ticket(r, "done-one", { scope: ["d.mjs"], stage: "shipped" });
  ticket(r, "w-one", { scope: ["w.mjs"], depends: ["out-one"] });
  ticket(r, "w-two", { scope: ["x.mjs"], depends: ["w-one"] });
  ticket(r, "s-one", { scope: ["s.mjs"], depends: ["done-one"] });
  const p = plan(r, "w-one", "w-two", "s-one");
  assert.deepEqual(p.groups, [["s-one"]]);
  assert.deepEqual(p.held.map((h) => h.id).sort(), ["w-one", "w-two"]);
});

test("plan: a depends: on a closed ticket is satisfied, like shipped", () => {
  const r = mk();
  ticket(r, "done-one", { scope: ["d.mjs"], stage: "closed" });
  ticket(r, "s-one", { scope: ["s.mjs"], depends: ["done-one"] });
  const p = plan(r, "s-one");
  assert.deepEqual(p.groups, [["s-one"]]);
  assert.deepEqual(p.held, []);
  assert.deepEqual(p.unknown, []);
});

test("plan: a dependency cycle exits 1; an unknown id exits 2; a plan file contributes the ticket ids it names", () => {
  const r = mk();
  ticket(r, "c-one", { scope: ["a.mjs"], depends: ["c-two"] });
  ticket(r, "c-two", { scope: ["b.mjs"], depends: ["c-one"] });
  ticket(r, "p-one", { scope: ["p.mjs"] });
  const cyc = run(r, "plan", "c-one", "c-two");
  assert.equal(cyc.status, 1);
  assert.match(cyc.stderr, /dependency cycle/);
  assert.equal(run(r, "plan", "nope").status, 2);
  const file = path.join(r, "plan.md");
  fs.writeFileSync(file, "- [ ] p-one: do the thing\n- [ ] c-one-extra is not a ticket\n");
  assert.deepEqual(plan(r, file).groups, [["p-one"]]);
});

test("cap: refuses a third build when two are running; default 2 build / 1 train", () => {
  const r = mk();
  ticket(r, "b-one", { stage: "working" });
  let c = run(r, "cap");
  assert.equal(c.status, 0, c.stderr);
  assert.match(c.stdout, /^ok build 1\/2/);
  ticket(r, "b-two", { stage: "queued", session: "sess-1" }); // dispatched, not yet claimed: counts as building
  c = run(r, "cap");
  assert.equal(c.status, 1);
  assert.match(c.stderr, /cap reached — build 2\/2/);
  ticket(r, "q-one", { stage: "queued" }); // an idle queued ticket is not running
  assert.equal(run(r, "cap", "--json").status, 1);
  assert.deepEqual(JSON.parse(run(r, "cap", "--json").stdout), { kind: "build", running: 2, max: 2, ok: false });
});

test("cap: train kind counts ready tickets, --exclude skips the departing one; adapter max_parallel overrides and is validated", () => {
  const r = mk();
  assert.equal(run(r, "cap", "--kind", "train").status, 0);
  ticket(r, "r-one", { stage: "ready" });
  assert.equal(run(r, "cap", "--kind", "train").status, 1, "a ready ticket fills the one train slot");
  assert.equal(run(r, "cap", "--kind", "train", "--exclude", "r-one").status, 0, "one ready ticket, departing it");
  ticket(r, "r-two", { stage: "ready" });
  assert.equal(run(r, "cap", "--kind", "train", "--exclude", "r-one").status, 1, "a second train in flight is refused");
  const adapter = path.join(r, ".opencode", "board", "adapter.json");
  fs.writeFileSync(adapter, JSON.stringify({ base: "main", gates: [["true"]], max_parallel: { build: 3, train: 3 } }));
  assert.equal(run(r, "cap", "--kind", "train").status, 0);
  ticket(r, "w-one", { stage: "working" });
  ticket(r, "w-two", { stage: "working" });
  assert.equal(run(r, "cap").status, 0, "3 allowed, 2 running");
  fs.writeFileSync(adapter, JSON.stringify({ base: "main", gates: [["true"]], max_parallel: { build: 0 } }));
  assert.equal(run(r, "cap").status, 2);
  assert.equal(run(r, "cap", "--kind", "huh").status, 2);
});

test("plan: path overlap survives a bare basename, absolute paths, .. segments and case", () => {
  const r = mk();
  const apart = (x, y) => plan(r, x, y).groups.length === 2;
  ticket(r, "n-one", { scope: ["orchestrator/bin/desk.mjs"] });
  ticket(r, "n-two", { scope: ["a.mjs"], callers: ["`cmdStatus` in `desk.mjs`"] });
  assert.ok(apart("n-one", "n-two"), "bare basename vs full path");
  ticket(r, "abs-one", { scope: [`${r}/src/x.mjs`] });
  ticket(r, "abs-two", { scope: ["src/x.mjs"] });
  assert.ok(apart("abs-one", "abs-two"), "absolute under the repo root vs relative");
  ticket(r, "dd-one", { scope: ["src/lib/../x.mjs"] });
  assert.ok(apart("dd-one", "abs-two"), ".. collapsed");
  ticket(r, "cs-one", { scope: ["SRC/X.mjs"] });
  assert.ok(apart("cs-one", "abs-two"), "case-insensitive");
  ticket(r, "ok-one", { scope: ["other/y.mjs"] });
  assert.deepEqual(plan(r, "abs-two", "ok-one").groups, [["abs-two", "ok-one"]], "disjoint paths still group");
});

test("plan: depends: none is no dependency; an id not on the board is reported as unknown, not grouped", () => {
  const r = mk();
  const f = (id, v) => {
    ticket(r, id, { scope: [`${id}.mjs`] });
    const m = JSON.parse(fs.readFileSync(path.join(r, ".opencode", "board", "tickets", `${id}.json`), "utf8")).mandate_path;
    fs.writeFileSync(m, `depends: ${v}\n`);
  };
  f("z-none", "none");
  f("z-na", "n/a");
  f("z-typo", "t99-typo");
  const p = plan(r, "z-none", "z-na", "z-typo");
  assert.deepEqual(p.groups, [["z-none", "z-na"]]);
  assert.deepEqual(p.unknown, [{ id: "z-typo", unknown_ids: ["t99-typo"] }]);
  assert.deepEqual(p.held, []);
});

test("plan: a ticket sharing a file with an in-flight board ticket outside the list is held", () => {
  const r = mk();
  ticket(r, "fly-one", { scope: ["src/busy.mjs"], stage: "working" });
  ticket(r, "new-one", { scope: ["src/busy.mjs"] });
  ticket(r, "new-two", { scope: ["src/free.mjs"] });
  const p = plan(r, "new-one", "new-two");
  assert.deepEqual(p.groups, [["new-two"]]);
  assert.equal(p.held[0].id, "new-one");
  assert.deepEqual(p.held[0].waiting_on, ["fly-one"]);
});

// ---- edits vs reads, and queue priority (dispatch-fair-holds)

test("plan: two tickets that only CALL the same file are not serialised or held (caller∩caller)", () => {
  const r = mk();
  ticket(r, "m6b-like", { scope: ["orchestrator/bin/workers-view.mjs"], callers: ["orchestrator/bin/oc-worker.mjs active reader"] });
  ticket(r, "gate-like", { scope: ["orchestrator/bin/verdict-gate.mjs"], callers: ["`gate()` called by oc-worker.mjs receipt verdict (:1701)"], stage: "working" });
  ticket(r, "peer-like", { scope: ["orchestrator/bin/other.mjs"], callers: ["orchestrator/bin/oc-worker.mjs"] });
  const p = plan(r, "m6b-like", "peer-like");
  assert.deepEqual(p.held, [], "not held by an in-flight ticket that only calls oc-worker.mjs too");
  assert.deepEqual(p.groups, [["m6b-like", "peer-like"]], "not serialised against each other either");
});

test("plan: one ticket editing a file the other calls still holds/serialises, in both directions, with the reason", () => {
  const r = mk();
  ticket(r, "edit-fly", { scope: ["lib/core.mjs"], stage: "working" });
  ticket(r, "call-new", { scope: ["src/a.mjs"], callers: ["`x()` in lib/core.mjs"] });
  let p = plan(r, "call-new");
  assert.deepEqual(p.held, [{ id: "call-new", waiting_on: ["edit-fly"], in_flight: ["edit-fly: edit-fly edits lib/core.mjs, which call-new calls"] }]);
  ticket(r, "call-fly", { scope: ["src/b.mjs"], callers: ["lib/util.mjs"], stage: "working" });
  ticket(r, "edit-new", { scope: ["lib/util.mjs"] });
  p = plan(r, "edit-new");
  assert.deepEqual(p.held[0].in_flight, ["call-fly: edit-new edits lib/util.mjs, which call-fly calls"]);
  const t = run(r, "plan", "edit-new");
  assert.match(t.stdout, /^held: edit-new — waiting on call-fly \(in flight: call-fly: edit-new edits lib\/util\.mjs, which call-fly calls\)$/m);
  ticket(r, "both-fly", { scope: ["src/s.mjs"], stage: "working" });
  ticket(r, "both-new", { scope: ["src/s.mjs"] });
  assert.deepEqual(plan(r, "both-new").held[0].in_flight, ["both-fly: both edit src/s.mjs"]);
  ticket(r, "x-one", { scope: ["q/x.mjs"], callers: ["q/y.mjs"] });
  ticket(r, "y-one", { scope: ["q/y.mjs"] });
  assert.deepEqual(plan(r, "x-one", "y-one").conflicts, [{ a: "x-one", b: "y-one", why: "y-one edits q/y.mjs, which x-one calls" }]);
});

test("plan: a blast-radius test path counts as an edit", () => {
  const r = mk();
  ticket(r, "t-fly", { scope: ["a.mjs", "tests/shared.test.mjs"], tests: ["tests/shared.test.mjs"], stage: "working" });
  ticket(r, "t-new", { scope: ["b.mjs", "tests/shared.test.mjs"], tests: ["tests/shared.test.mjs"] });
  assert.deepEqual(plan(r, "t-new").held[0].in_flight, ["t-fly: both edit tests/shared.test.mjs"]);
});

test("plan: a blast-radius test outside scope is run-only: no hold, one group", () => {
  const r = mk();
  ticket(r, "t-fly", { scope: ["a.mjs"], tests: ["tests/shared.test.mjs"], stage: "working" });
  ticket(r, "t-new", { scope: ["b.mjs"], tests: ["tests/shared.test.mjs"] });
  const p = plan(r, "t-fly", "t-new");
  assert.deepEqual(p.groups, [["t-fly", "t-new"]]);
  assert.deepEqual(p.held, []);
  assert.deepEqual(p.conflicts, []);
});

test("plan: two tickets sharing docs/ATLAS.md are one group (merge-friendly default)", () => {
  const r = mk();
  ticket(r, "a-one", { scope: ["docs/ATLAS.md", "src/a.mjs"] });
  ticket(r, "b-one", { scope: ["docs/ATLAS.md", "src/b.mjs"] });
  const p = plan(r, "a-one", "b-one");
  assert.deepEqual(p.groups, [["a-one", "b-one"]]);
  assert.deepEqual(p.conflicts, []);
  assert.deepEqual(p.held, []);
});

test("plan: docs/ATLAS.md shared with an in-flight ticket is not held", () => {
  const r = mk();
  ticket(r, "fly-one", { scope: ["docs/ATLAS.md", "src/a.mjs"], stage: "working" });
  ticket(r, "new-one", { scope: ["docs/ATLAS.md", "src/b.mjs"] });
  const p = plan(r, "new-one");
  assert.deepEqual(p.groups, [["new-one"]]);
  assert.deepEqual(p.held, []);
});

test("plan: docs/ATLAS.md shared with an older queued EGM-cleared ticket is not held (queue priority)", () => {
  const r = mk();
  ticket(r, "old-q", { scope: ["docs/ATLAS.md", "src/a.mjs"], created: ago(5), egm: "approved" });
  ticket(r, "new-q", { scope: ["docs/ATLAS.md", "src/b.mjs"], created: ago(1), egm: "waived" });
  const p = plan(r, "new-q");
  assert.deepEqual(p.groups, [["new-q"]]);
  assert.deepEqual(p.held, []);
  assert.deepEqual(plan(r, "old-q").groups, [["old-q"]]);
});

test("plan: merge_friendly: [] turns the default off — docs/ATLAS.md conflicts", () => {
  const r = mk({ merge_friendly: [] });
  ticket(r, "a-one", { scope: ["docs/ATLAS.md", "src/a.mjs"] });
  ticket(r, "b-one", { scope: ["docs/ATLAS.md", "src/b.mjs"] });
  const p = plan(r, "a-one", "b-one");
  assert.deepEqual(p.groups, [["a-one"], ["b-one"]]);
  assert.equal(p.conflicts[0].why, "shared file docs/atlas.md");
});

test("plan: docs/** in one scope still conflicts with docs/ATLAS.md in the other", () => {
  const r = mk();
  ticket(r, "a-one", { scope: ["docs/**"] });
  ticket(r, "b-one", { scope: ["docs/ATLAS.md", "src/b.mjs"] });
  const p = plan(r, "a-one", "b-one");
  assert.deepEqual(p.groups, [["a-one"], ["b-one"]]);
  assert.equal(p.conflicts[0].why, "shared file docs/** ~ docs/atlas.md");
});

test("plan: custom merge_friendly: CHANGELOG.md ignored, docs/ATLAS.md still conflicts", () => {
  const r = mk({ merge_friendly: ["CHANGELOG.md"] });
  ticket(r, "a-one", { scope: ["CHANGELOG.md", "src/a.mjs"] });
  ticket(r, "b-one", { scope: ["CHANGELOG.md", "src/b.mjs"] });
  ticket(r, "c-one", { scope: ["docs/ATLAS.md", "src/c.mjs"] });
  ticket(r, "d-one", { scope: ["docs/ATLAS.md", "src/d.mjs"] });
  const p = plan(r, "a-one", "b-one", "c-one", "d-one");
  const together = (x, y) => p.groups.some((g) => g.includes(x) && g.includes(y));
  assert.ok(together("a-one", "b-one"), "CHANGELOG.md is merge-friendly");
  assert.ok(!together("c-one", "d-one"), "docs/ATLAS.md still serialises");
  assert.equal(p.conflicts.find((c) => c.a === "c-one" && c.b === "d-one")?.why, "shared file docs/atlas.md");
});

test("plan: merge_friendly must be an array of exact file paths", () => {
  let r = mk({ merge_friendly: "docs/ATLAS.md" });
  ticket(r, "a-one", { scope: ["a.mjs"] });
  let res = run(r, "plan", "a-one");
  assert.equal(res.status, 2, res.stderr);
  assert.match(res.stderr, /adapter\.json: merge_friendly must be an array of exact file paths/);
  r = mk({ merge_friendly: ["docs/*.md"] });
  ticket(r, "a-one", { scope: ["a.mjs"] });
  res = run(r, "plan", "a-one");
  assert.equal(res.status, 2, res.stderr);
  assert.match(res.stderr, /adapter\.json: merge_friendly must be an array of exact file paths/);
});

test("plan: edit-vs-read on docs/ATLAS.md still conflicts", () => {
  const r = mk();
  ticket(r, "x-one", { scope: ["docs/ATLAS.md", "src/x.mjs"] });
  ticket(r, "y-one", { scope: ["src/y.mjs"], callers: ["`readAtlas()` in docs/ATLAS.md"] });
  const p = plan(r, "x-one", "y-one");
  assert.equal(p.conflicts[0].why, "x-one edits docs/atlas.md, which y-one calls");
});

const NOW = Date.now();
const ago = (h) => new Date(NOW - h * 3600_000).toISOString();

test("plan: an older queued EGM-cleared ticket holds a newer overlapping one (queue priority)", () => {
  const r = mk();
  ticket(r, "old-q", { scope: ["orchestrator/bin/workers-view.mjs"], callers: ["orchestrator/bin/dispatch.mjs plan"], created: ago(5), egm: "approved" });
  ticket(r, "new-q", { scope: ["orchestrator/bin/dispatch.mjs"], created: ago(1), egm: "waived" });
  const p = plan(r, "new-q");
  assert.deepEqual(p.groups, []);
  assert.deepEqual(p.held, [{ id: "new-q", waiting_on: ["old-q"], queued_first: ["old-q: new-q edits orchestrator/bin/dispatch.mjs, which old-q calls"] }]);
  assert.match(run(r, "plan", "new-q").stdout, /^held: new-q — waiting on old-q \(older queued: old-q: /m);
  // The older one is never held by the newer one.
  assert.deepEqual(plan(r, "old-q").groups, [["old-q"]]);
  // Both in the list: grouped by the normal rules, no hold.
  assert.deepEqual(plan(r, "old-q", "new-q").held, []);
});

test("plan: queue priority skips EGM-pending, stale, dispatched, caller-only and non-queued cases; window 0 turns it off", () => {
  const r = mk();
  ticket(r, "pend-q", { scope: ["p.mjs"], created: ago(5), egm: "pending" });
  ticket(r, "stale-q", { scope: ["s.mjs"], created: ago(49), egm: "approved" });
  ticket(r, "read-q", { scope: ["r1.mjs"], callers: ["shared/c.mjs"], created: ago(5), egm: "approved" });
  ticket(r, "new-q", { scope: ["p.mjs", "s.mjs", "n.mjs"], callers: ["shared/c.mjs"], created: ago(1), egm: "approved" });
  assert.deepEqual(plan(r, "new-q").held, [], "pending EGM, older than 48 h, and caller∩caller give no priority");
  ticket(r, "old-q", { scope: ["n.mjs"], created: ago(5), egm: "approved" });
  assert.deepEqual(plan(r, "new-q").held.map((h) => h.waiting_on), [["old-q"]]);
  ticket(r, "work-new", { scope: ["n.mjs"], created: ago(1), stage: "working" });
  assert.deepEqual(plan(r, "work-new").held, [], "a ticket already working is not held behind a queued one");
  fs.rmSync(path.join(r, ".opencode", "board", "tickets", "work-new.json"));
  ticket(r, "sess-new", { scope: ["n.mjs"], created: ago(1), session: "s-9" });
  assert.deepEqual(plan(r, "sess-new").held, [], "a queued ticket already dispatched to a session is not held behind a queued one");
  fs.rmSync(path.join(r, ".opencode", "board", "tickets", "sess-new.json"));
  ticket(r, "sess-old", { scope: ["m.mjs"], created: ago(5), egm: "approved", session: "s-8" });
  ticket(r, "m-new", { scope: ["m.mjs"], created: ago(1), egm: "approved" });
  assert.deepEqual(plan(r, "m-new").held[0], { id: "m-new", waiting_on: ["sess-old"], in_flight: ["sess-old: both edit m.mjs"] }, "a dispatched older ticket holds as in flight, not twice as queued_first");
  fs.rmSync(path.join(r, ".opencode", "board", "tickets", "sess-old.json"));
  const adapter = path.join(r, ".opencode", "board", "adapter.json");
  fs.writeFileSync(adapter, JSON.stringify({ base: "main", gates: [["true"]], queue_priority_hours: 0 }));
  assert.deepEqual(plan(r, "new-q").held, [], "window 0 disables priority");
  fs.writeFileSync(adapter, JSON.stringify({ base: "main", gates: [["true"]], queue_priority_hours: 100 }));
  assert.deepEqual(plan(r, "new-q").held[0].waiting_on.sort(), ["old-q", "stale-q"], "a wider window keeps the 49 h ticket");
  fs.writeFileSync(adapter, JSON.stringify({ base: "main", gates: [["true"]], queue_priority_hours: "x" }));
  assert.equal(run(r, "plan", "new-q").status, 2);
});

test("--help prints the header and exits 0", () => {
  const r = spawnSync(process.execPath, [BIN, "--help"], { encoding: "utf8" });
  assert.equal(r.status, 0);
  assert.match(r.stdout, /plan <ticket-id\|plan-file>/);
});

// ---- cap --kind build with max_parallel.build: "auto" ----

function procRoot(psi, load, mem) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-dispatch-proc-"));
  CLEAN.push(root);
  fs.mkdirSync(path.join(root, "pressure"), { recursive: true });
  fs.writeFileSync(path.join(root, "pressure", "cpu"), psi || "some avg300=5\n");
  fs.writeFileSync(path.join(root, "loadavg"), load || "0.53 0.83 1.00\n");
  fs.writeFileSync(path.join(root, "meminfo"), mem || "MemAvailable: 13500000 kB\n");
  return root;
}
function runProc(repo, root, ...args) {
  return spawnSync(process.execPath, [BIN, ...args, "--repo", repo], {
    encoding: "utf8",
    env: { ...process.env, ORCH_PROC_ROOT: root, WORKER_SLOTS: "" },
  });
}

test("cap --kind build auto: clear sample -> max from slots max (10), reason present in --json", () => {
  const repo = mk({ max_parallel: { build: "auto" } });
  const root = procRoot("some avg300=5\n", "0.53 0.83 1.00\n", "MemAvailable: 13500000 kB\n");
  const c = runProc(repo, root, "cap", "--kind", "build", "--json");
  assert.equal(c.status, 0, c.stderr);
  const s = JSON.parse(c.stdout);
  assert.equal(s.kind, "build");
  assert.equal(s.running, 0);
  assert.equal(s.max, 10);
  assert.equal(s.ok, true);
  assert.ok(s.reason, "reason present in auto mode");
  assert.match(s.reason, /^slots 10\/10 \(cpu wait 5%, load 0\.83, 13 GiB free\) \(advisory\)$/);
  const text = runProc(repo, root, "cap", "--kind", "build");
  assert.equal(text.status, 0, text.stderr);
  assert.match(text.stdout, /^ok build 0\/10/);
});

test("cap --kind build auto: busy sample -> max falls to slots min (2), reason says so", () => {
  const repo = mk({ max_parallel: { build: "auto" } });
  const root = procRoot("some avg300=31\n", "0.53 0.83 1.00\n", "MemAvailable: 13500000 kB\n");
  const c = runProc(repo, root, "cap", "--kind", "build", "--json");
  assert.equal(c.status, 0, c.stderr); // 0 running < 2 max: room left
  const s = JSON.parse(c.stdout);
  assert.equal(s.max, 2);
  assert.match(s.reason, /cpu wait 31%/);
  assert.match(s.reason, /\(advisory\)$/);
});

test("cap --kind build auto: absent max_parallel still defaults to build 2", () => {
  const repo = mk(); // no max_parallel at all
  const root = procRoot("some avg300=5\n", "0.53 0.83 1.00\n", "MemAvailable: 13500000 kB\n");
  const c = runProc(repo, root, "cap", "--kind", "build", "--json");
  assert.equal(c.status, 0, c.stderr);
  assert.deepEqual(JSON.parse(c.stdout), { kind: "build", running: 0, max: 2, ok: true });
});

test("cap --kind build auto: integer cap unchanged", () => {
  const repo = mk({ max_parallel: { build: 3 } });
  const root = procRoot("some avg300=5\n", "0.53 0.83 1.00\n", "MemAvailable: 13500000 kB\n");
  const c = runProc(repo, root, "cap", "--kind", "build", "--json");
  assert.equal(c.status, 0, c.stderr);
  assert.deepEqual(JSON.parse(c.stdout), { kind: "build", running: 0, max: 3, ok: true });
});

test("cap --kind train auto: usage error (auto only valid for build)", () => {
  const repo = mk({ max_parallel: { train: "auto" } });
  const c = runProc(repo, null, "cap", "--kind", "train");
  assert.equal(c.status, 2, c.stderr);
  assert.match(c.stderr, /max_parallel\.train/);
});

test("cap --kind build auto: no /proc sample -> max falls to min (2), reason names the source", () => {
  const repo = mk({ max_parallel: { build: "auto" } });
  const empty = fs.mkdtempSync(path.join(os.tmpdir(), "orch-dispatch-empty-"));
  CLEAN.push(empty);
  const c = runProc(repo, empty, "cap", "--kind", "build", "--json");
  assert.equal(c.status, 0, c.stderr);
  const s = JSON.parse(c.stdout);
  assert.equal(s.max, 2);
  assert.match(s.reason, /no load sample/);
});

// ---------- status ----------
// Each status run needs an isolated ORCH_HOME so the runs/streams dirs (shared with the real machine)
// do not leak into the assertions.
function mkStatus() {
  const repo = mk();
  const oh = fs.mkdtempSync(path.join(os.tmpdir(), "orch-status-home-"));
  CLEAN.push(oh);
  fs.mkdirSync(path.join(oh, ".config", "orchestrator", "runs"), { recursive: true });
  fs.mkdirSync(path.join(oh, ".config", "orchestrator", "streams"), { recursive: true });
  return { repo, oh };
}
const status = (repo, oh, ...args) => spawnSync(process.execPath, [BIN, ...args, "--repo", repo], {
  encoding: "utf8", env: { ...process.env, ORCH_HOME: oh },
});
function runFile(oh, pid, started, over = {}) {
  const dir = path.join(oh, ".config", "orchestrator", "runs");
  const f = path.join(dir, `${pid}-${started}.json`);
  fs.writeFileSync(f, JSON.stringify({
    pid, agent: "worker-nvidia", model: "nvidia/nemotron", title: "run", dir: "/tmp/wt",
    out: "/tmp/out.md", started, idleMin: 5, timeoutMin: 60, session: `sess-${pid}`, ...over,
  }));
  return f;
}

test("status: --line is empty with no active tickets; exit 0", () => {
  const { repo, oh } = mkStatus();
  ticket(repo, "done-one", { scope: ["d.mjs"], stage: "shipped" });
  ticket(repo, "idle-one", { scope: ["i.mjs"], stage: "queued" }); // no session: not active
  const r = status(repo, oh, "status", "--line");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "");
});

test("status: two building and one ready give the right counts", () => {
  const { repo, oh } = mkStatus();
  ticket(repo, "b-one", { scope: ["a.mjs"], stage: "working" });
  ticket(repo, "b-two", { scope: ["b.mjs"], stage: "queued", session: "sess-1" }); // dispatched, not yet claimed
  ticket(repo, "r-one", { scope: ["c.mjs"], stage: "ready" });
  const r = status(repo, oh, "status", "--json");
  assert.equal(r.status, 0, r.stderr);
  const d = JSON.parse(r.stdout);
  assert.equal(d.counts.building, 2);
  assert.equal(d.counts.ready, 1);
  assert.equal(d.tickets.length, 3);
});

test("status: --session keeps only that session's tickets (board assignment or held stream); counts follow", () => {
  const { repo, oh } = mkStatus();
  ticket(repo, "mine-board", { scope: ["a.mjs"], stage: "working", session: "me" });
  ticket(repo, "mine-stream", { scope: ["b.mjs"], stage: "working" });
  fs.writeFileSync(path.join(oh, ".config", "orchestrator", "streams", "mine-stream.json"), JSON.stringify({ name: "mine-stream", held_session: "me" }));
  ticket(repo, "mine-ready", { scope: ["c.mjs"], stage: "ready", session: "me" });
  ticket(repo, "other-one", { scope: ["d.mjs"], stage: "working", session: "other" });
  const r = status(repo, oh, "status", "--json", "--session", "me");
  assert.equal(r.status, 0, r.stderr);
  const d = JSON.parse(r.stdout);
  assert.deepEqual(d.tickets.map((t) => t.id).sort(), ["mine-board", "mine-ready", "mine-stream"]);
  assert.equal(d.counts.building, 2, "only this session's building tickets, not the repo-wide cap count");
  assert.equal(d.counts.ready, 1);
  const none = status(repo, oh, "status", "--line", "--session", "nobody");
  assert.equal(none.status, 0, none.stderr);
  assert.equal(none.stdout, "", "a session with no tickets draws nothing");
  const all = JSON.parse(status(repo, oh, "status", "--json").stdout);
  assert.equal(all.tickets.length, 4, "without --session every active ticket is listed");
});

test("status: --json has the documented shape", () => {
  const { repo, oh } = mkStatus();
  ticket(repo, "t-one", { scope: ["a.mjs"], stage: "working", session: "sess-1" });
  ticket(repo, "t-two", { scope: ["b.mjs"], stage: "ready" });
  const r = status(repo, oh, "status", "--json");
  assert.equal(r.status, 0, r.stderr);
  const d = JSON.parse(r.stdout);
  assert.ok(Number.isFinite(Date.parse(d.at)), "at is an ISO instant");
  assert.deepEqual(Object.keys(d), ["at", "tickets", "counts"]);
  assert.deepEqual(Object.keys(d.counts), ["building", "ready", "runs"]);
  assert.equal(d.counts.building, 1);
  assert.equal(d.counts.ready, 1);
  assert.equal(d.tickets.length, 2);
  const byId = Object.fromEntries(d.tickets.map((t) => [t.id, t]));
  assert.equal(byId["t-one"].stage, "working");
  assert.equal(byId["t-one"].session, "sess-1");
  assert.equal(byId["t-one"].run, null); // no run file registered
  assert.equal(byId["t-two"].stage, "ready");
  assert.equal(byId["t-two"].session, null);
  assert.equal(byId["t-two"].run, null);
  for (const t of d.tickets) {
    assert.ok(["id", "stage", "session"].every((k) => k in t));
    if (t.run) assert.ok(["pid", "agent", "model", "elapsed_s", "out_age_s", "alive"].every((k) => k in t.run));
  }
});

test("status: a dead-pid run gets ⚠ in --line", () => {
  const { repo, oh } = mkStatus();
  ticket(repo, "t-one", { scope: ["a.mjs"], stage: "working", session: "sess-1" });
  runFile(oh, 999999, Date.now() - 10_000, { session: "sess-1" }); // pid 999999 is not alive on this box
  const r = status(repo, oh, "status", "--line");
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /t-one/);
  assert.match(r.stdout, /⚠/);
});

test("status: a live-pid run shows no ⚠ in --line", () => {
  const { repo, oh } = mkStatus();
  ticket(repo, "t-one", { scope: ["a.mjs"], stage: "working", session: "sess-1" });
  runFile(oh, process.pid, Date.now() - 10_000, { session: "sess-1" });
  const r = status(repo, oh, "status", "--line");
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /t-one/);
  assert.ok(!r.stdout.includes("⚠"), `live run should not warn: ${r.stdout}`);
});

test("status: overflow truncates with +K and stays ≤ 120 chars", () => {
  const { repo, oh } = mkStatus();
  const n = 24;
  const base = Date.now();
  for (let i = 0; i < n; i++) {
    ticket(repo, `t-${i}`, { scope: [`src/${i}.mjs`], stage: "working", session: `sess-${i}` });
    runFile(oh, 90000 + i, base - (n - i) * 1000, { session: `sess-${i}` }); // dead pids → ⚠
  }
  const r = status(repo, oh, "status", "--line");
  assert.equal(r.status, 0, r.stderr);
  const line = r.stdout;
  assert.ok(line.length <= 120, `line too long (${line.length}): ${line}`);
  assert.match(line, /⇉/);
  assert.match(line, /\+[0-9]+/, `expected +K truncation: ${line}`);
  // every shown run is a real segment; the +K accounts for the hidden remainder
  assert.ok(line.split(" · ").some((s) => /\+\d+$/.test(s.trim())), `no +K tail: ${line}`);
});

test("status: stream last-event age appears in --json when a run names a stream", () => {
  const { repo, oh } = mkStatus();
  const stream = "stream-alpha";
  ticket(repo, "t-one", { scope: ["a.mjs"], stage: "working", session: "sess-1" });
  runFile(oh, 999999, Date.now() - 10_000, { session: "sess-1", stream }); // run names stream-alpha
  fs.writeFileSync(
    path.join(oh, ".config", "orchestrator", "streams", `${stream}.events.jsonl`),
    '{"key":"k1","kind":"queued","at":"2026-11-24T10:00:00Z"}\n',
  );
  const r = status(repo, oh, "status", "--json");
  assert.equal(r.status, 0, r.stderr);
  const d = JSON.parse(r.stdout);
  const t = d.tickets.find((x) => x.id === "t-one");
  assert.ok(t && t.run, "t-one should carry its run");
  assert.ok(t.last_event_age_s != null, "last_event_age_s missing for streamed run");
  assert.ok(Number.isFinite(t.last_event_age_s) && t.last_event_age_s > 0);
});

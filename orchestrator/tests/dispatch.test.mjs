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
function ticket(repo, id, { scope = [], callers = [], depends = [], stage = "queued", session = null } = {}) {
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
      blast_radius: callers.map((c) => ({ caller: c, expect: "unchanged" })),
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

test("--help prints the header and exits 0", () => {
  const r = spawnSync(process.execPath, [BIN, "--help"], { encoding: "utf8" });
  assert.equal(r.status, 0);
  assert.match(r.stdout, /plan <ticket-id\|plan-file>/);
});

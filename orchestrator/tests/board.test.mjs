import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

// The board is CLI-only: every case builds a real repo + worktree and spawns `node bin/board.mjs`.
const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "board.mjs");
const FIX = path.join(HERE, "fixtures", "board");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function git(cwd, ...args) {
  const r = spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8" });
  assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
  return r.stdout.trim();
}

// Temp git repo (bare-path-free: `main` + one commit), an adapter.json, and a real worktree.
function mk() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-board-"));
  CLEAN.push(root);
  const repo = path.join(root, "repo");
  fs.mkdirSync(repo);
  git(repo, "init", "-b", "main");
  git(repo, "config", "user.email", "board@example.test");
  git(repo, "config", "user.name", "board test");
  git(repo, "config", "commit.gpgsign", "false");
  fs.mkdirSync(path.join(repo, ".opencode", "board"), { recursive: true });
  fs.copyFileSync(path.join(FIX, "adapter.json"), path.join(repo, ".opencode", "board", "adapter.json"));
  fs.writeFileSync(path.join(repo, "README.md"), "board test repo\n");
  git(repo, "add", "README.md", ".opencode/board/adapter.json");
  git(repo, "commit", "-m", "init");
  const wt = path.join(root, "wt");
  git(repo, "worktree", "add", "-b", "feat/demo", wt);
  const mandate = path.join(root, "mandate.md");
  fs.copyFileSync(path.join(FIX, "mandate.md"), mandate);
  const noBlast = path.join(root, "mandate-no-blast.md");
  fs.copyFileSync(path.join(FIX, "mandate-no-blast.md"), noBlast);
  // BOARD_GATE_TIMEOUT_MS: a stalled gate spawn fails in seconds instead of the production 20-minute cap.
  return { root, repo, wt, mandate, noBlast, env: { ...process.env, ORCH_HOME: path.join(root, "orch-home"), BOARD_GATE_TIMEOUT_MS: "60000" } };
}

function board(c, ...args) {
  const r = spawnSync(process.execPath, [BIN, ...args], { cwd: c.repo, env: c.env, encoding: "utf8" });
  // Success prints the ticket as the first line; `ready` adds its wake-up line, `verify` prints nothing.
  const first = String(r.stdout || "").split("\n").find((l) => l.trim());
  return { status: r.status, stdout: r.stdout, stderr: r.stderr, ticket: (() => { try { return JSON.parse(first); } catch { return null; } })() };
}
const ticketFile = (c, id) => path.join(c.repo, ".opencode", "board", "tickets", `${id}.json`);
const lockDir = (c, id) => path.join(c.repo, ".opencode", "board", "locks", `${id}.lock`);
const bytes = (p) => fs.readFileSync(p);
// The default scope is broad (`bin/**`, was `bin/demo.mjs`): with the scope fence on, rounds and ready diff
// base..sha against it, and the existing tests commit other files under bin/. A later --scope in `extra` wins.
function created(c, id, ...extra) {
  const r = board(c, "create", id, "--mandate", c.mandate, "--scope", "bin/**", ...extra);
  assert.equal(r.status, 0, r.stderr);
  return r.ticket;
}
function waived(c, id) {
  const r = board(c, "egm", id, "waive", "--reason", "no persisted format, no public interface", "--by", "rick");
  assert.equal(r.status, 0, r.stderr);
  return r.ticket;
}
function claim(c, id, owner = "s1", wt = c.wt) {
  return board(c, "claim", id, "--owner", owner, "--harness", "claude", "--worktree", wt);
}
// Seed a ticket lock by hand (owner.json) so the break rules can be exercised without waiting out a real clock.
function seedLock(c, id, owner, heartbeatMs = Date.now(), mtimeMs = heartbeatMs) {
  const d = lockDir(c, id);
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, "owner.json"), JSON.stringify({ owner, harness: "claude", heartbeat: new Date(heartbeatMs).toISOString() }));
  fs.utimesSync(d, new Date(mtimeMs), new Date(mtimeMs));
  return d;
}
// Seed the global lock: no owner.json (a bare dir) or a stale owner, at a chosen age.
function seedGlobalLock(c, ownerAtMs = null, ageMs = 0) {
  const d = path.join(c.repo, ".opencode", "board", ".board.lock");
  fs.mkdirSync(d, { recursive: true });
  if (ownerAtMs !== null) {
    fs.writeFileSync(path.join(d, "owner.json"), JSON.stringify({ pid: 999999, at: new Date(ownerAtMs).toISOString() }));
  }
  const age = new Date(Date.now() - ageMs);
  fs.utimesSync(d, age, age);
  return d;
}
// Write a ticket file directly: the board's own on-disk interface, used to reach a stage nothing else produces yet.
function editTicket(c, id, fn) {
  const p = ticketFile(c, id);
  const t = JSON.parse(bytes(p));
  fn(t);
  t.updated = new Date().toISOString();
  fs.writeFileSync(p, JSON.stringify(t, null, 2) + "\n");
}

// ---------------------------------------------------------------- Phase 1 happy path
test("phase 1 happy path: create → egm waive → claim → heartbeat → release → claim again", () => {
  const c = mk();
  const t = created(c, "demo-one", "--title", "Demo ticket");
  assert.equal(t.stage, "queued");
  assert.equal(t.epoch, 0);
  assert.equal(t.egm.status, "pending");
  assert.equal(t.egm.required, false);
  assert.equal(t.title, "Demo ticket");
  assert.equal(t.blast_radius.length, 3);
  assert.deepEqual(t.blast_radius[0], { caller: "`run()` in `bin/main.mjs`", expect: "unchanged", test: "bin/demo.test.mjs" });
  assert.equal(t.blast_radius[1].expect, "unchanged", "no — separator means unchanged");
  assert.equal(t.blast_radius[2].expect, "new caller only");
  assert.equal(t.history.length, 1);
  assert.equal(fs.existsSync(lockDir(c, "demo-one")), false);

  const w = waived(c, "demo-one");
  assert.equal(w.egm.status, "waived");
  assert.equal(w.epoch, 1);

  const claimed = claim(c, "demo-one", "s1");
  assert.equal(claimed.status, 0, claimed.stderr);
  assert.equal(claimed.ticket.stage, "working");
  assert.equal(claimed.ticket.assignment.owner, "s1");
  assert.equal(claimed.ticket.assignment.harness, "claude");
  assert.equal(claimed.ticket.assignment.worker, null);
  assert.equal(claimed.ticket.worktree, c.wt);
  assert.match(claimed.ticket.base_sha, /^[0-9a-f]{40}$/);
  const lock = JSON.parse(fs.readFileSync(path.join(lockDir(c, "demo-one"), "owner.json"), "utf8"));
  assert.equal(lock.owner, "s1");
  assert.equal(lock.harness, "claude");
  assert.ok(Date.parse(lock.heartbeat) > 0);

  // heartbeat rewrites the lock only: the ticket file must not move at all
  const before = bytes(ticketFile(c, "demo-one"));
  const hb = board(c, "heartbeat", "demo-one", "--owner", "s1");
  assert.equal(hb.status, 0, hb.stderr);
  assert.equal(hb.ticket.stage, "working");
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "demo-one"))) === 0, "heartbeat must not write the ticket");

  const rel = board(c, "release", "demo-one", "--owner", "s1");
  assert.equal(rel.status, 0, rel.stderr);
  assert.equal(rel.ticket.stage, "queued");
  assert.equal(rel.ticket.assignment, null);
  assert.equal(fs.existsSync(lockDir(c, "demo-one")), false, "leaving working drops the lock");

  const again = claim(c, "demo-one", "s2");
  assert.equal(again.status, 0, again.stderr);
  assert.equal(again.ticket.stage, "working");
  assert.equal(again.ticket.assignment.owner, "s2");
  assert.deepEqual(again.ticket.history.map((h) => h.cmd), ["create", "egm waive", "claim", "release", "claim"]);
  assert.equal(again.ticket.epoch, 4);
});

test("create computes egm triggers: declared, data-model from scope, many-modules over 3 top dirs", () => {
  const c = mk();
  const dataModel = created(c, "data-change", "--scope", "db/migrations/001.sql");
  assert.deepEqual(dataModel.egm.triggers, ["data-model"]);
  assert.equal(dataModel.egm.required, true);

  const declared = created(c, "new-thing", "--egm-trigger", "new-module", "--egm-trigger", "security");
  assert.deepEqual(declared.egm.triggers, ["new-module", "security"]);
  assert.equal(declared.egm.required, true);

  const many = created(c, "spread", "--scope", "bin/a.mjs,docs/b.md,tests/c.mjs,skills/d.md");
  assert.deepEqual(many.egm.triggers, ["many-modules"]);
  const guarded = many.senior;
  assert.equal(guarded.required, false);
  const guard = created(c, "guarded", "--scope", "ops/train.sh");
  assert.equal(guard.senior.required, true);
  assert.match(guard.senior.reasons.join(" "), /guarded path: ops\/train\.sh/);
});

test("2. invalid transition queued → ready is refused with exit 1 and no write", () => {
  const c = mk();
  created(c, "demo-two");
  const before = bytes(ticketFile(c, "demo-two"));
  const r = board(c, "ready", "demo-two", "--owner", "s1");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /^board: ready needs stage working, ticket is queued/);
  assert.equal(r.stdout, "");
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "demo-two"))) === 0, "a refused transition writes nothing");
  assert.equal(JSON.parse(before).epoch, 0);
});

test("3. claim while egm is pending is refused with exit 1", () => {
  const c = mk();
  created(c, "needs-egm", "--egm-trigger", "new-module");
  const r = claim(c, "needs-egm");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /egm is pending/);
  assert.equal(JSON.parse(bytes(ticketFile(c, "needs-egm"))).stage, "queued");
  assert.equal(fs.existsSync(lockDir(c, "needs-egm")), false, "a refused claim must not leave a lock");
});

test("4. waive is refused when egm is required, and for a 19-character reason", () => {
  const c = mk();
  created(c, "req-one", "--egm-trigger", "security");
  const required = board(c, "egm", "req-one", "waive", "--reason", "this reason is plenty long enough", "--by", "rick");
  assert.equal(required.status, 1, required.stderr);
  assert.match(required.stderr, /egm is required/);

  created(c, "opt-two");
  const short = board(c, "egm", "opt-two", "waive", "--reason", "1234567890123456789", "--by", "rick");
  assert.equal(short.status, 1, short.stderr);
  assert.match(short.stderr, /at least 20 characters/);
  assert.equal(JSON.parse(bytes(ticketFile(c, "opt-two"))).egm.status, "pending");

  const ok = board(c, "egm", "opt-two", "waive", "--reason", "12345678901234567890", "--by", "rick");
  assert.equal(ok.status, 0, ok.stderr);
  assert.equal(ok.ticket.egm.status, "waived");
});

test("4b. egm approve needs an existing report and records its absolute path + sha256", () => {
  const c = mk();
  created(c, "approved-one", "--egm-trigger", "new-module");
  assert.equal(board(c, "egm", "approved-one", "approve", "--report", path.join(c.root, "nope.md"), "--by", "rick").status, 2);
  const report = path.join(c.repo, "egm.md");
  fs.writeFileSync(report, "APPROVED\n");
  const r = board(c, "egm", "approved-one", "approve", "--report", "egm.md", "--by", "rick");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.egm.status, "approved");
  assert.equal(r.ticket.egm.report_path, report);
  assert.match(r.ticket.egm.report_sha256, /^[0-9a-f]{64}$/);
  assert.equal(board(c, "claim", "approved-one", "--owner", "s1", "--harness", "claude", "--worktree", c.wt).status, 0);
});

test("5. a Mandate with no blast-radius bullets is refused", () => {
  const c = mk();
  const r = board(c, "create", "no-blast", "--mandate", c.noBlast, "--scope", "bin/demo.mjs");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /blast-radius/);
  assert.equal(fs.existsSync(ticketFile(c, "no-blast")), false);
  const missing = board(c, "create", "no-file", "--mandate", path.join(c.root, "absent.md"), "--scope", "bin/x.mjs");
  assert.equal(missing.status, 2, missing.stderr);
});

test("5c. create refuses a changed-expectation bullet with no test: path, naming the bullet", () => {
  const c = mk();
  const bullets = "**Blast radius:**\n\n- `run()` in `bin/main.mjs` — unchanged; test: bin/demo.test.mjs\n- `parse()` in `bin/other.mjs` — changed\n";
  const mandate = path.join(c.root, "mandate-changed.md");
  fs.writeFileSync(mandate, `# Ticket\n\n**Atlas refs consulted / updated?** no map\n\n${bullets}\n`);
  const r = board(c, "create", "changed-no-test", "--mandate", mandate, "--scope", "bin/demo.mjs");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /changes expectations but names no test path/);
  assert.match(r.stderr, /bin\/other\.mjs/);
  assert.equal(fs.existsSync(ticketFile(c, "changed-no-test")), false, "nothing was written");

  // Same bullet WITH a test path: create accepts it.
  const bulletsWithTest = "**Blast radius:**\n\n- `parse()` in `bin/other.mjs` — changed; test: bin/other.test.mjs\n";
  const mandate2 = path.join(c.root, "mandate-changed-with-test.md");
  fs.writeFileSync(mandate2, `# Ticket\n\n**Atlas refs consulted / updated?** no map\n\n${bulletsWithTest}\n`);
  const ok = board(c, "create", "changed-with-test", "--mandate", mandate2, "--scope", "bin/demo.mjs");
  assert.equal(ok.status, 0, ok.stderr);
  assert.deepEqual(ok.ticket.blast_radius, [{ caller: "`parse()` in `bin/other.mjs`", expect: "changed", test: "bin/other.test.mjs" }]);
});

test("5d. an expect starting with 'unchanged' (e.g. 'unchanged (reason)') counts as unchanged at create", () => {
  const c = mk();
  const bullets = "**Blast radius:**\n\n- `run()` in `bin/main.mjs` — unchanged (reason); test: bin/demo.test.mjs\n- `parse()` in `bin/other.mjs` — expected: unchanged; must still pass\n";
  const mandate = path.join(c.root, "mandate-unchanged-reason.md");
  fs.writeFileSync(mandate, `# Ticket\n\n**Atlas refs consulted / updated?** no map\n\n${bullets}\n`);
  const r = board(c, "create", "unchanged-reason", "--mandate", mandate, "--scope", "bin/demo.mjs");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.ticket.blast_radius, [
    { caller: "`run()` in `bin/main.mjs`", expect: "unchanged (reason)", test: "bin/demo.test.mjs" },
    { caller: "`parse()` in `bin/other.mjs`", expect: "expected: unchanged; must still pass" },
  ]);
});

// atlas-m1: the Mandate's map answer. A repo without a map still answers ("no map"); silence is refused.
test("5b. a Mandate with no 'Atlas refs consulted / updated?' line is refused; an empty label is not an answer", () => {
  const c = mk();
  const atlasLine = "**Atlas refs consulted / updated?** no map in this fixture repo";
  const bullets = "**Blast radius:**\n\n- `run()` in `bin/main.mjs` — unchanged\n";
  const write = (name, text) => {
    const p = path.join(c.root, `${name}.md`);
    fs.writeFileSync(p, text);
    return p;
  };

  const bare = board(c, "create", "no-atlas", "--mandate", write("no-atlas", `# Ticket\n\n${bullets}`), "--scope", "bin/demo.mjs");
  assert.equal(bare.status, 1, bare.stderr);
  assert.match(bare.stderr, /no Atlas line/);
  assert.equal(fs.existsSync(ticketFile(c, "no-atlas")), false, "nothing was written");

  const empty = board(c, "create", "empty-atlas", "--mandate", write("empty-atlas", `# Ticket\n\n**Atlas refs consulted / updated?**\n\n${bullets}`), "--scope", "bin/demo.mjs");
  assert.equal(empty.status, 1, empty.stderr);
  assert.match(empty.stderr, /no Atlas line/);

  // Both accepted shapes: the bold label with an answer, and a plain bullet. The fixture Mandate answers it.
  const answered = board(c, "create", "atlas-answered", "--mandate", write("atlas-answered", `# Ticket\n\n${atlasLine}\n\n${bullets}`), "--scope", "bin/demo.mjs");
  assert.equal(answered.status, 0, answered.stderr);
  const bulletForm = board(c, "create", "atlas-bullet", "--mandate", write("atlas-bullet", `# Ticket\n\n- **Atlas refs consulted / updated?** docs/ATLAS.md#lending -> unchanged\n\n${bullets}`), "--scope", "bin/demo.mjs");
  assert.equal(bulletForm.status, 0, bulletForm.stderr);
});

// Design case 6: ten claims, exactly one winner, and the board is left consistent.
// `claim` is queued→working and its stage check runs before the ticket lock, so a late arrival that observes
// `working` is refused by the stage machine (exit 1) rather than by the lock. Both are correct; the next test
// isolates the lock path so that contention itself is proved to exit 3.
test("6. ten concurrent claims: exactly one exits 0 and the board is left consistent", async () => {
  const c = mk();
  created(c, "race-one");
  waived(c, "race-one");
  const runs = await Promise.all(
    Array.from({ length: 10 }, (_, i) => new Promise((resolve) => {
      const ch = spawn(process.execPath, [BIN, "claim", "race-one", "--owner", `s${i}`, "--harness", "opencode", "--worktree", c.wt], { cwd: c.repo, env: c.env });
      let out = "";
      let err = "";
      ch.stdout.on("data", (d) => (out += d));
      ch.stderr.on("data", (d) => (err += d));
      ch.on("close", (code) => resolve({ code, out, err }));
    })),
  );
  const winners = runs.filter((r) => r.code === 0);
  assert.equal(winners.length, 1, runs.map((r) => `${r.code}: ${r.err.trim()}`).join(" | "));
  const winner = JSON.parse(winners[0].out);
  assert.equal(winner.stage, "working");
  const t = JSON.parse(bytes(ticketFile(c, "race-one")));
  assert.equal(t.assignment.owner, winner.assignment.owner);
  assert.equal(t.epoch, 2, "create + claim only: nine refusals wrote nothing");
  const lock = JSON.parse(fs.readFileSync(path.join(lockDir(c, "race-one"), "owner.json"), "utf8"));
  assert.equal(lock.owner, t.assignment.owner);
  // Every loser failed for a named reason, never silently and never for an unnamed code.
  for (const r of runs.filter((x) => x.code !== 0)) {
    assert.match(r.err, /^(board: claim needs stage queued|board: ticket race-one is locked by)/, r.err);
    assert.ok([1, 3].includes(r.code), r.err);
  }
});

// The lock path on its own, with the same 10 real processes: a live foreign ticket lock is contention and must
// be exit 3 for every one of them, with nothing written.
test("6b. ten concurrent claims against a live lock all exit 3", async () => {
  const c = mk();
  created(c, "race-locked");
  waived(c, "race-locked");
  seedLock(c, "race-locked", "busy-owner", Date.now()); // live: inside stale_minutes
  const env = { ...c.env, BOARD_LOCK_TIMEOUT_MS: "20000" };
  const before = bytes(ticketFile(c, "race-locked"));
  const runs = await Promise.all(
    Array.from({ length: 10 }, (_, i) => new Promise((resolve) => {
      const ch = spawn(process.execPath, [BIN, "claim", "race-locked", "--owner", `s${i}`, "--harness", "opencode", "--worktree", c.wt], { cwd: c.repo, env });
      let err = "";
      ch.stderr.on("data", (d) => (err += d));
      ch.on("close", (code) => resolve({ code, err }));
    })),
  );
  const codes = runs.map((r) => r.code);
  assert.deepEqual([...new Set(codes)], [3], `all ten must report lock contention: ${runs.map((r) => r.err.trim()).join(" | ")}`);
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "race-locked"))) === 0, "no loser wrote the ticket");
  assert.equal(JSON.parse(fs.readFileSync(path.join(lockDir(c, "race-locked"), "owner.json"), "utf8")).owner, "busy-owner");
});

test("16. a corrupt ticket is listed as CORRUPT and never blocks the other tickets", () => {
  const c = mk();
  created(c, "good-one");
  created(c, "bad-one");
  fs.writeFileSync(ticketFile(c, "bad-one"), "{ this is not json");
  const s = board(c, "status", "--json");
  assert.equal(s.status, 0, s.stderr);
  const rows = JSON.parse(s.stdout);
  assert.deepEqual(rows.map((r) => `${r.id}:${r.stage}`), ["bad-one:CORRUPT", "good-one:queued"]);
  // another ticket is still fully usable
  waived(c, "good-one");
  const claimed = claim(c, "good-one");
  assert.equal(claimed.status, 0, claimed.stderr);
  const rel = board(c, "release", "good-one", "--owner", "s1");
  assert.equal(rel.status, 0, rel.stderr);
  assert.equal(rel.ticket.stage, "queued");
  // the corrupt file itself is refused, not truncated
  assert.equal(board(c, "release", "bad-one", "--owner", "s1").status, 2);
  assert.match(fs.readFileSync(ticketFile(c, "bad-one"), "utf8"), /not json/);
});

test("17. bad ids (a&b, .., A) are refused with exit 2 everywhere", () => {
  const c = mk();
  for (const id of ["a&b", "..", "A", "", "nine-".padEnd(62, "x")]) {
    const r = board(c, "create", id, "--mandate", c.mandate, "--scope", "bin/x.mjs");
    assert.equal(r.status, 2, `create ${id}: ${r.stderr}`);
    assert.match(r.stderr, /^board: /);
  }
  created(c, "ok-one");
  for (const id of ["a&b", "..", "A"]) {
    assert.equal(board(c, "claim", id, "--owner", "s1", "--harness", "claude", "--worktree", c.wt).status, 2, id);
    assert.equal(board(c, "heartbeat", id, "--owner", "s1").status, 2, id);
    assert.equal(board(c, "quarantine", id).status, 2, id);
  }
  assert.equal(fs.readdirSync(path.join(c.repo, ".opencode", "board", "tickets")).length, 1, "no bad id reached the disk");
});

test("19. an epoch conflict exits 3 and writes nothing; the right epoch succeeds", () => {
  const c = mk();
  created(c, "epoch-one");
  const before = bytes(ticketFile(c, "epoch-one"));
  const bad = board(c, "egm", "epoch-one", "waive", "--reason", "no persisted format, nothing shared", "--by", "rick", "--expect-epoch", "3");
  assert.equal(bad.status, 3, bad.stderr);
  assert.match(bad.stderr, /epoch 0 != expected 3/);
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "epoch-one"))) === 0);
  const good = board(c, "egm", "epoch-one", "waive", "--reason", "no persisted format, nothing shared", "--by", "rick", "--expect-epoch", "0");
  assert.equal(good.status, 0, good.stderr);
  assert.equal(good.ticket.epoch, 1);
});

test("21. heartbeat by a non-owner is refused with exit 1", () => {
  const c = mk();
  created(c, "hb-one");
  waived(c, "hb-one");
  assert.equal(claim(c, "hb-one", "s1").status, 0);
  const other = board(c, "heartbeat", "hb-one", "--owner", "s2");
  assert.equal(other.status, 1, other.stderr);
  assert.match(other.stderr, /locked by s1/);
  assert.equal(board(c, "heartbeat", "hb-one", "--owner", "s1").status, 0);
});

test("22. release --force --by human --note frees another owner's ticket", () => {
  const c = mk();
  created(c, "force-one");
  waived(c, "force-one");
  assert.equal(claim(c, "force-one", "s1").status, 0);

  assert.equal(board(c, "release", "force-one", "--owner", "s2").status, 1, "a non-owner cannot release");
  assert.equal(board(c, "release", "force-one", "--force", "--note", "short", "--by", "human").status, 1, "a 5-char note is refused");
  assert.equal(board(c, "release", "force-one", "--force", "--by", "human").status, 2, "--force needs --note");
  const noBy = board(c, "release", "force-one", "--force", "--note", "session died, handing back");
  assert.equal(noBy.status, 2, "a forced release must name a human");
  assert.match(noBy.stderr, /--by human/);
  for (const who of ["opencode", "critic", "rick"]) {
    const bad = board(c, "release", "force-one", "--force", "--by", who, "--note", "session died, handing back");
    assert.equal(bad.status, 2, `--by ${who} is not a human sign-off`);
  }
  assert.equal(JSON.parse(bytes(ticketFile(c, "force-one"))).stage, "working", "refusals wrote nothing");

  const forced = board(c, "release", "force-one", "--force", "--note", "session died, handing back", "--by", "human");
  assert.equal(forced.status, 0, forced.stderr);
  assert.equal(forced.ticket.stage, "queued");
  assert.equal(forced.ticket.assignment, null);
  assert.equal(fs.existsSync(lockDir(c, "force-one")), false);
  assert.match(forced.ticket.history.pop().cmd, /release --force/);
});

test("23. quarantine moves a corrupt ticket file out of tickets/ and refuses one that parses", () => {
  const c = mk();
  created(c, "broken-one");
  fs.writeFileSync(ticketFile(c, "broken-one"), "not json at all");
  const r = board(c, "quarantine", "broken-one");
  assert.equal(r.status, 0, r.stderr);
  const out = JSON.parse(r.stdout);
  assert.deepEqual(Object.keys(out), ["id", "quarantined_to"], "a corrupt file has no ticket to print");
  assert.equal(out.id, "broken-one");
  assert.equal(out.quarantined_to, path.join(c.repo, ".opencode", "board", "tickets", "quarantine", "broken-one.json"));
  assert.equal(fs.existsSync(ticketFile(c, "broken-one")), false);
  assert.equal(fs.readFileSync(out.quarantined_to, "utf8"), "not json at all", "quarantine preserves the bytes for inspection");
  assert.deepEqual(JSON.parse(board(c, "status", "--json").stdout), []);
  assert.equal(board(c, "quarantine", "broken-one").status, 2, "already moved: no ticket");

  // A valid ticket is live state: quarantining it would delete a working ticket and its lock.
  created(c, "live-one");
  waived(c, "live-one");
  assert.equal(claim(c, "live-one", "s1").status, 0);
  const before = bytes(ticketFile(c, "live-one"));
  const refused = board(c, "quarantine", "live-one");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /parses — quarantine only moves a corrupt file/);
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "live-one"))) === 0, "a refused quarantine writes nothing");
  assert.equal(fs.existsSync(lockDir(c, "live-one")), true, "the live lock is untouched");

  // A file that is valid JSON but fails the schema is corrupt too, and may be quarantined.
  created(c, "schema-one");
  fs.writeFileSync(ticketFile(c, "schema-one"), JSON.stringify({ schema: 1, id: "schema-one" }));
  const bad = board(c, "quarantine", "schema-one");
  assert.equal(bad.status, 0, bad.stderr);
  assert.equal(JSON.parse(bad.stdout).id, "schema-one");
});

test("24. --help exits 0 and writes nothing, from anywhere", () => {
  const c = mk();
  const at = board(c, "--help");
  assert.equal(at.status, 0, at.stderr);
  assert.match(at.stdout, /create <id> --mandate <path>/);
  assert.match(at.stdout, /Exit: 0 ok, 1 refused by a rule/);
  assert.equal(at.stderr, "");
  // -h, and help before any repo/adapter resolution or argument validation
  const outside = spawnSync(process.execPath, [BIN, "-h"], { cwd: os.tmpdir(), encoding: "utf8" });
  assert.equal(outside.status, 0, outside.stderr);
  assert.match(outside.stdout, /--expect-epoch/);
  assert.equal(spawnSync(process.execPath, [BIN, "--help", "--bogus"], { cwd: os.tmpdir(), encoding: "utf8" }).status, 0);
  const noArgs = spawnSync(process.execPath, [BIN], { cwd: c.repo, encoding: "utf8" });
  assert.equal(noArgs.status, 2);
  assert.equal(fs.existsSync(path.join(c.repo, ".opencode", "board", "tickets")), false, "help writes nothing");
});

test("25. status --json has the documented shape", () => {
  const c = mk();
  created(c, "shape-one", "--title", "Shape");
  waived(c, "shape-one");
  assert.equal(claim(c, "shape-one", "s1").status, 0);
  const rows = JSON.parse(board(c, "status", "--json").stdout);
  assert.equal(rows.length, 1);
  assert.deepEqual(Object.keys(rows[0]), ["id", "stage", "owner", "age_min", "rounds", "cost", "egm", "signoff"]);
  assert.deepEqual(rows[0], { id: "shape-one", stage: "working", owner: "s1", age_min: 0, rounds: 0, cost: 0, egm: "waived", signoff: null });
  assert.match(board(c, "status").stdout, /^ID\tSTAGE\tOWNER/);
});

test("repo root resolves from inside the worktree, and a foreign worktree is refused", () => {
  const c = mk();
  created(c, "wt-one");
  waived(c, "wt-one");
  // no --repo: the cwd is the worktree, so the common dir must still find the repo root
  const r = spawnSync(process.execPath, [BIN, "claim", "wt-one", "--owner", "s1", "--harness", "opencode", "--worktree", c.wt], { cwd: c.wt, env: c.env, encoding: "utf8" });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(JSON.parse(r.stdout).stage, "working");

  const other = fs.mkdtempSync(path.join(os.tmpdir(), "orch-board-other-"));
  CLEAN.push(other);
  git(other, "init", "-b", "main");
  git(other, "commit", "--allow-empty", "-m", "x");
  assert.equal(board(c, "release", "wt-one", "--owner", "s1").status, 0);
  const foreign = claim(c, "wt-one", "s2", other);
  assert.equal(foreign.status, 1, foreign.stderr);
  assert.match(foreign.stderr, /not a worktree of this repo/);
});

test("fail is terminal; a blocked ticket can be unblocked by a human", () => {
  const c = mk();
  created(c, "fail-one");
  waived(c, "fail-one");
  assert.equal(claim(c, "fail-one", "s1").status, 0);
  const f = board(c, "fail", "fail-one", "--note", "abandoned by the owner");
  assert.equal(f.status, 0, f.stderr);
  assert.equal(f.ticket.stage, "failed");
  assert.equal(fs.existsSync(lockDir(c, "fail-one")), false);
  assert.equal(board(c, "release", "fail-one", "--owner", "s1").status, 1, "failed is terminal");
  assert.equal(board(c, "fail", "fail-one", "--note", "again").status, 1, "failed is terminal");
  assert.equal(board(c, "unblock", "fail-one", "--by", "human", "--note", "reopen please").status, 1);

  // No Phase-1 command parks a ticket in `blocked` (that is `watch`/`round`, phases 2-3), so the state a
  // sweep would leave behind is written directly: the ticket file is the board's own interface.
  created(c, "blocked-one");
  const p = ticketFile(c, "blocked-one");
  const t = JSON.parse(bytes(p));
  Object.assign(t, { stage: "blocked", epoch: t.epoch + 1, updated: new Date().toISOString(), blocked: { reason: "stale", note: "no heartbeat", at: new Date().toISOString() } });
  fs.writeFileSync(p, JSON.stringify(t, null, 2) + "\n");
  assert.equal(board(c, "unblock", "blocked-one", "--by", "human", "--note", "short").status, 1);
  assert.equal(board(c, "unblock", "blocked-one", "--by", "opencode", "--note", "a human must do this").status, 2);
  const u = board(c, "unblock", "blocked-one", "--by", "human", "--note", "decided to continue");
  assert.equal(u.status, 0, u.stderr);
  assert.equal(u.ticket.stage, "queued");
  assert.equal(u.ticket.blocked, null);
});

// close: a human-only terminal exit from queued/working/ready/blocked into the new final stage closed.
test("close: lands in closed from queued, working, ready and blocked, with the closed record and no lock", () => {
  const c = mk();
  created(c, "c-q");
  const q = board(c, "close", "c-q", "--by", "human", "--sha", head(c), "--note", "merged by the desk, not the train");
  assert.equal(q.status, 0, q.stderr);
  assert.equal(q.ticket.stage, "closed");
  assert.equal(q.ticket.closed.by, "human");
  assert.equal(q.ticket.closed.sha, head(c));
  assert.match(q.ticket.closed.note, /merged by the desk/);
  assert.match(q.ticket.closed.at, /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}/);
  assert.equal(q.ticket.assignment, null);
  assert.equal(fs.existsSync(lockDir(c, "c-q")), false);
  assert.deepEqual(q.ticket.history.map((h) => h.cmd).slice(-1), ["close"]);
  assert.deepEqual(q.ticket.history.map((h) => h.by).slice(-1), ["human"]);

  created(c, "c-w");
  waived(c, "c-w");
  assert.equal(claim(c, "c-w", "s1").status, 0);
  const w = board(c, "close", "c-w", "--by", "human", "--sha", head(c), "--note", "superseded by a later ticket");
  assert.equal(w.status, 0, w.stderr);
  assert.equal(w.ticket.stage, "closed");
  assert.equal(w.ticket.assignment, null);
  assert.equal(fs.existsSync(lockDir(c, "c-w")), false, "leaving working drops the lock");

  created(c, "c-r");
  waived(c, "c-r");
  assert.equal(claim(c, "c-r", "s1").status, 0);
  editTicket(c, "c-r", (t) => { t.stage = "ready"; t.epoch += 1; t.updated = new Date().toISOString(); });
  const r = board(c, "close", "c-r", "--by", "human", "--sha", head(c), "--note", "another path to production");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "closed");
  assert.equal(r.ticket.assignment, null);

  created(c, "c-b");
  editTicket(c, "c-b", (t) => { t.stage = "blocked"; t.blocked = { reason: "stale", note: "gone", at: new Date().toISOString() }; t.epoch += 1; t.updated = new Date().toISOString(); });
  const b = board(c, "close", "c-b", "--by", "human", "--sha", head(c), "--note", "abandoned, nothing to land");
  assert.equal(b.status, 0, b.stderr);
  assert.equal(b.ticket.stage, "closed");
  assert.equal(b.ticket.assignment, null);
});

test("close: refused from shipped, failed and closed, writing nothing", () => {
  const c = mk();
  created(c, "c-t");
  for (const stage of ["shipped", "failed", "closed"]) {
    editTicket(c, "c-t", (t) => { t.stage = stage; t.epoch += 1; t.updated = new Date().toISOString(); });
    const before = bytes(ticketFile(c, "c-t"));
    const r = board(c, "close", "c-t", "--by", "human", "--sha", head(c), "--note", "a long enough note here");
    assert.equal(r.status, 1, `${stage}: ${r.stderr}`);
    assert.match(r.stderr, new RegExp(`close needs stage .* ticket is ${stage}`));
    assert.ok(Buffer.compare(before, bytes(ticketFile(c, "c-t"))) === 0, `${stage} wrote nothing`);
  }
});

test("close: --by human, a long enough note, and a resolvable sha are required", () => {
  const c = mk();
  created(c, "c-u");
  const noBy = board(c, "close", "c-u", "--sha", head(c), "--note", "a long enough note");
  assert.equal(noBy.status, 2, noBy.stderr);
  assert.match(noBy.stderr, /close needs --by human/);
  const noNote = board(c, "close", "c-u", "--by", "human", "--sha", head(c));
  assert.equal(noNote.status, 2, noNote.stderr);
  assert.match(noNote.stderr, /--note is required/);
  const noSha = board(c, "close", "c-u", "--by", "human", "--note", "a long enough note");
  assert.equal(noSha.status, 2, noSha.stderr);
  assert.match(noSha.stderr, /--sha is required/);
  const short = board(c, "close", "c-u", "--by", "human", "--sha", head(c), "--note", "short");
  assert.equal(short.status, 1, short.stderr);
  assert.match(short.stderr, /close needs --note of at least 10 characters/);
  const unknown = board(c, "close", "c-u", "--by", "human", "--note", "a long enough note", "--sha", "0".repeat(40));
  assert.equal(unknown.status, 1, unknown.stderr);
  assert.match(unknown.stderr, /does not resolve/);
  assert.equal(JSON.parse(bytes(ticketFile(c, "c-u"))).stage, "queued", "refusals wrote nothing");
});

test("close: --sha must be an ancestor of adapter.base or of the local base branch", () => {
  const c = mk();
  created(c, "c-s");
  // a commit on the worktree branch: its ancestor chain never reaches local main
  const side = commitFile(c, "side.txt", "side work\n");
  const notAncestor = board(c, "close", "c-s", "--by", "human", "--note", "a long enough note", "--sha", side);
  assert.equal(notAncestor.status, 1, notAncestor.stderr);
  assert.match(notAncestor.stderr, /not an ancestor of/);
  assert.match(notAncestor.stderr, /main/);
  assert.equal(JSON.parse(bytes(ticketFile(c, "c-s"))).stage, "queued");
});

test("close: a sha on local main but not on origin/main is accepted", () => {
  const c = mk();
  created(c, "c-a");
  const bare = fs.mkdtempSync(path.join(os.tmpdir(), "orch-bare-"));
  CLEAN.push(bare);
  git(bare, "init", "--bare");
  git(c.repo, "remote", "add", "origin", bare);
  git(c.repo, "fetch", "origin");
  git(c.repo, "commit", "--allow-empty", "-m", "ahead on local main");
  const ahead = git(c.repo, "rev-parse", "HEAD");
  const onOrigin = spawnSync("git", ["-C", c.repo, "merge-base", "--is-ancestor", ahead, "origin/main"]);
  assert.notEqual(onOrigin.status, 0, "ahead must not be on origin/main yet");
  const r = board(c, "close", "c-a", "--by", "human", "--sha", ahead, "--note", "ff-merged locally, not yet pushed");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "closed");
  assert.equal(r.ticket.closed.sha, ahead);
});

test("close: a pre-change ticket with no closed key still loads", () => {
  const c = mk();
  created(c, "c-p");
  editTicket(c, "c-p", (t) => { delete t.closed; });
  const s = board(c, "status", "--json");
  assert.equal(s.status, 0, s.stderr);
  assert.equal(JSON.parse(s.stdout)[0].stage, "queued");
  const r = board(c, "close", "c-p", "--by", "human", "--sha", head(c), "--note", "closed with no prior closed key");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "closed");
  assert.equal(r.ticket.closed.by, "human");
  assert.equal(r.ticket.closed.sha, head(c));
  assert.equal(r.ticket.assignment, null);
});

test("egm reopen returns an owned ticket to queued with a pending egm, lock released", () => {
  const c = mk();
  created(c, "reopen-one");
  waived(c, "reopen-one");
  assert.equal(claim(c, "reopen-one", "s1").status, 0);
  const r = board(c, "egm", "reopen-one", "reopen", "--owner", "s1", "--trigger", "data-model");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "queued");
  assert.equal(r.ticket.egm.status, "pending");
  assert.equal(r.ticket.egm.required, true);
  assert.deepEqual(r.ticket.egm.triggers, ["data-model"]);
  assert.equal(fs.existsSync(lockDir(c, "reopen-one")), false);
  assert.equal(board(c, "egm", "reopen-one", "reopen", "--owner", "s1", "--trigger", "x").status, 1, "only an owned working ticket reopens");
});

test("missing adapter.json is exit 2, a bad one is too", () => {
  const c = mk();
  fs.rmSync(path.join(c.repo, ".opencode", "board", "adapter.json"));
  const missing = board(c, "status", "--json");
  assert.equal(missing.status, 2, missing.stderr);
  assert.match(missing.stderr, /no adapter\.json/);
  fs.writeFileSync(path.join(c.repo, ".opencode", "board", "adapter.json"), JSON.stringify({ base: "main" }));
  const bad = board(c, "status");
  assert.equal(bad.status, 2);
  assert.match(bad.stderr, /adapter\.json: /);
});

// ---------------------------------------------------------------- lock break rules (finding #5)
test("claim breaks a ticket lock whose heartbeat is older than stale_minutes", () => {
  const c = mk();
  created(c, "stale-lock");
  waived(c, "stale-lock");
  // 90 minutes old against adapter stale_minutes: 45, and no worker pid recorded
  seedLock(c, "stale-lock", "gone-owner", Date.now() - 90 * 60_000);
  const r = claim(c, "stale-lock", "fresh-owner");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "working");
  const lock = JSON.parse(fs.readFileSync(path.join(lockDir(c, "stale-lock"), "owner.json"), "utf8"));
  assert.equal(lock.owner, "fresh-owner", "the stale owner is replaced, not stacked");
});

test("claim refuses a live foreign ticket lock with exit 3", () => {
  const c = mk();
  created(c, "live-lock");
  waived(c, "live-lock");
  seedLock(c, "live-lock", "busy-owner"); // heartbeat now: inside stale_minutes
  const before = bytes(ticketFile(c, "live-lock"));
  const r = claim(c, "live-lock", "other");
  assert.equal(r.status, 3, `a live lock is contention: ${r.stderr}`);
  assert.match(r.stderr, /is locked by busy-owner/);
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "live-lock"))) === 0, "a refused claim writes nothing");
  assert.equal(JSON.parse(fs.readFileSync(path.join(lockDir(c, "live-lock"), "owner.json"), "utf8")).owner, "busy-owner");
});

test("a bare ticket-lock dir is reclaimable only after 60 s", () => {
  const c = mk();
  created(c, "bare-lock");
  waived(c, "bare-lock");
  const d = lockDir(c, "bare-lock");
  fs.mkdirSync(d, { recursive: true }); // no owner.json
  const fresh = claim(c, "bare-lock", "s1");
  assert.equal(fresh.status, 3, `a young bare lock is contention: ${fresh.stderr}`);
  const old = new Date(Date.now() - 61_000);
  fs.utimesSync(d, old, old);
  const reclaimed = claim(c, "bare-lock", "s1");
  assert.equal(reclaimed.status, 0, reclaimed.stderr);
  assert.equal(reclaimed.ticket.stage, "working");
});

test("the global lock is broken once its owner is older than 30 s", () => {
  const c = mk();
  seedGlobalLock(c, Date.now() - 31_000);
  const r = board(c, "create", "after-stale-global", "--mandate", c.mandate, "--scope", "bin/a.mjs");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.id, "after-stale-global");
});

test("a live global lock times out with exit 3, and BOARD_LOCK_TIMEOUT_MS shortens the wait", () => {
  const c = mk();
  const d = seedGlobalLock(c, Date.now()); // fresh owner: real contention
  const started = Date.now();
  const r = spawnSync(process.execPath, [BIN, "create", "blocked-by-global", "--mandate", c.mandate, "--scope", "bin/a.mjs"], {
    cwd: c.repo,
    env: { ...c.env, BOARD_LOCK_TIMEOUT_MS: "300" },
    encoding: "utf8",
  });
  assert.equal(r.status, 3, r.stderr);
  assert.match(r.stderr, /global lock is held/);
  assert.ok(Date.now() - started < 8000, "the timeout env var must actually shorten the wait");
  assert.equal(fs.existsSync(ticketFile(c, "blocked-by-global")), false, "no ticket was written");
  assert.equal(JSON.parse(fs.readFileSync(path.join(d, "owner.json"), "utf8")).pid, 999999, "the live lock survives");
});

test("glob match also reaches through an ancestor directory, which is what guarded paths rely on", () => {
  const c = mk();
  // `auth/login.ts` never matches `**/auth` itself; its parent dir `auth` does. Same for `ops/`.
  const guarded = created(c, "guarded-ancestor", "--scope", "auth/login.ts");
  assert.equal(guarded.senior.required, true);
  assert.deepEqual(guarded.senior.reasons, ["guarded path: auth/login.ts"]);
  const egm = created(c, "egm-ancestor", "--scope", "prisma/schema.prisma");
  assert.deepEqual(egm.egm.triggers, ["data-model"]);
  const plain = created(c, "plain-path", "--scope", "docs/readme.md");
  assert.equal(plain.senior.required, false);
  assert.equal(plain.egm.required, false);
});

test("many-modules counts directories only: four root-level files do not trigger it", () => {
  const c = mk();
  const rootOnly = created(c, "root-files", "--scope", "a.md,b.md,c.md,d.md");
  assert.equal(rootOnly.egm.required, false, "root-level files are not modules");
  const fourDirs = created(c, "four-dirs", "--scope", "bin/a.mjs,docs/b.md,tests/c.mjs,skills/d.md");
  assert.deepEqual(fourDirs.egm.triggers, ["many-modules"]);
  const threeDirs = created(c, "three-dirs", "--scope", "bin/a.mjs,docs/b.md,tests/c.mjs");
  assert.equal(threeDirs.egm.required, false, "> 3 means four or more");
});

test("unknown commands exit 2, including Object.prototype member names", () => {
  const c = mk();
  for (const cmd of ["bogus", "hasOwnProperty", "constructor", "toString", "valueOf", "__proto__"]) {
    const r = board(c, cmd);
    assert.equal(r.status, 2, `${cmd}: ${r.stderr}`);
    assert.match(r.stderr, /^board: /);
    assert.equal(r.stdout, "", `${cmd} must not print a ticket`);
  }
  assert.equal(board(c).status, 2, "no arguments prints usage and exits 2");
});

test("egm approve and waive are queued-only, like every other unlisted pair", () => {
  const c = mk();
  created(c, "egm-stage");
  waived(c, "egm-stage");
  assert.equal(claim(c, "egm-stage", "s1").status, 0);
  // a second waive on a working ticket is refused by the stage machine, not by "already waived"
  const r = board(c, "egm", "egm-stage", "waive", "--reason", "no persisted format, no public interface", "--by", "rick");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /egm waive needs stage queued, ticket is working/);
});

test("a claim refused before it takes the lock leaves no ticket lock behind", () => {
  const c = mk();
  created(c, "no-leak");
  // Every check that can refuse a claim (stage, egm, worktree, live lock) runs before takeTicketLock, so a
  // refused claim must not leave a lock that would block the next one until the heartbeat goes stale.
  const pendingEgm = claim(c, "no-leak", "s1");
  assert.equal(pendingEgm.status, 1, pendingEgm.stderr);
  assert.equal(fs.existsSync(lockDir(c, "no-leak")), false, "no lock for a refused claim");

  waived(c, "no-leak");
  const other = fs.mkdtempSync(path.join(os.tmpdir(), "orch-board-foreign-"));
  CLEAN.push(other);
  git(other, "init", "-b", "main");
  git(other, "commit", "--allow-empty", "-m", "x");
  assert.equal(claim(c, "no-leak", "s1", other).status, 1);
  assert.equal(fs.existsSync(lockDir(c, "no-leak")), false, "still no lock");

  seedLock(c, "no-leak", "busy-owner");
  assert.equal(claim(c, "no-leak", "s1").status, 3);
  assert.equal(fs.readdirSync(path.dirname(lockDir(c, "no-leak"))).length, 1, "one lock dir, not two");

  // And a successful claim leaves exactly one lock, owned by the claimant.
  fs.rmSync(lockDir(c, "no-leak"), { recursive: true, force: true });
  assert.equal(claim(c, "no-leak", "s2").status, 0);
  assert.equal(fs.readdirSync(path.dirname(lockDir(c, "no-leak"))).length, 1);
  assert.equal(JSON.parse(fs.readFileSync(path.join(lockDir(c, "no-leak"), "owner.json"), "utf8")).owner, "s2");
});

// ---------------------------------------------------------------- Phase 2: rounds, signoff, gates, ready, verify, shipped
const head = (c) => git(c.wt, "rev-parse", "HEAD");
// Copy a fixture into this case's temp root so the board sees a real absolute path inside the case.
function fixture(c, rel) {
  const dst = path.join(c.root, "inputs", rel);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.copyFileSync(path.join(FIX, rel), dst);
  return dst;
}
// A receipt variant: the same fixture with one field changed, written under this case's temp root.
function fixtureJson(c, name, baseRel, patch) {
  const dst = path.join(c.root, "inputs", "variants", `${name}.json`);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  const v = JSON.parse(fs.readFileSync(path.join(FIX, baseRel), "utf8"));
  fs.writeFileSync(dst, JSON.stringify({ ...v, ...patch }, null, 2) + "\n");
  return dst;
}
// A findings file written from a string (one-off verdicts the fixture set does not carry).
function fixtureText(c, name, text) {
  const dst = path.join(c.root, "inputs", "variants", `${name}.md`);
  fs.mkdirSync(path.dirname(dst), { recursive: true });
  fs.writeFileSync(dst, text);
  return dst;
}
// An input is either a fixture-relative path or an absolute one produced by fixtureJson/fixtureText.
const input = (c, p) => (path.isAbsolute(p) ? p : fixture(c, p));
function commitFile(c, rel, content, msg = `add ${rel}`) {
  const p = path.join(c.wt, rel);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  git(c.wt, "add", rel);
  git(c.wt, "commit", "-m", msg);
  return head(c);
}
// Ready rule 6: bin/load.test.mjs is the fixture Mandate's only blast-radius entry whose expectation changed.
function landBlastFile(c) {
  return commitFile(c, "bin/load.test.mjs", "// fixture: the load() caller test\n");
}
// Write a pinned OpenCode agent into ORCH_HOME, so a receipt's "(agent default)" can be resolved (pool-health).
function installAgent(c, name, model) {
  const p = path.join(c.env.ORCH_HOME, ".config", "opencode", "agents", `${name}.md`);
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, `---\ndescription: test fixture\nmodel: ${model}\n---\n`);
}
function workingTicket(c, id) {
  created(c, id);
  waived(c, id);
  const r = claim(c, id, "s1");
  assert.equal(r.status, 0, r.stderr);
  return r.ticket;
}
// A round with the usual reader defaults; pass null to omit an optional input (non-done outcomes).
function round(c, id, opts = {}) {
  const worker = opts.worker ?? "receipts/worker-done.json";
  const findings = opts.findings === undefined ? "findings/approved.md" : opts.findings;
  const critic = opts.critic === undefined ? "receipts/critic-paid.json" : opts.critic;
  const reviewed = opts.reviewed === undefined ? head(c) : opts.reviewed;
  const args = ["round", id, "--owner", "s1", "--worker-receipt", input(c, worker)];
  if (findings) args.push("--findings", input(c, findings));
  if (critic) args.push("--critic-receipt", input(c, critic));
  if (opts.native) args.push("--native-critic", opts.native);
  if (reviewed) args.push("--reviewed-sha", reviewed);
  return board(c, ...args);
}
function signedCritic(c, id) {
  const r = board(c, "signoff", id, "--by", "critic", "--owner", "s1");
  assert.equal(r.status, 0, r.stderr);
  return r.ticket;
}
function gatesOk(c, id) {
  const r = board(c, "gates", id, "--owner", "s1");
  assert.equal(r.status, 0, r.stderr);
  return r.ticket;
}
function setAdapterGates(c, gates) {
  const p = path.join(c.repo, ".opencode", "board", "adapter.json");
  const a = JSON.parse(fs.readFileSync(p, "utf8"));
  a.gates = gates;
  fs.writeFileSync(p, JSON.stringify(a, null, 2) + "\n");
}
// The happy path through the lock-releasing `ready`, for the cases that only need a ready ticket.
function atReady(c, id) {
  workingTicket(c, id);
  const sha = landBlastFile(c);
  assert.equal(round(c, id, { reviewed: sha }).status, 0);
  signedCritic(c, id);
  gatesOk(c, id);
  const rd = board(c, "ready", id, "--owner", "s1");
  assert.equal(rd.status, 0, rd.stderr);
  return { sha, ticket: rd.ticket };
}

test("phase 2 case 1: round → signoff → gates → ready → verify → shipped", () => {
  const c = mk();
  workingTicket(c, "p2-happy");
  const sha = landBlastFile(c);

  const r = round(c, "p2-happy", { reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  const t = r.ticket;
  assert.equal(t.rounds.length, 1);
  const ro = t.rounds[0];
  assert.equal(ro.n, 1);
  assert.equal(ro.counted, true);
  assert.equal(ro.worker.outcome, "done");
  assert.equal(ro.worker.agent, "worker");
  assert.match(ro.worker.receipt_sha256, /^[0-9a-f]{64}$/);
  assert.equal(ro.critic.source, "receipt");
  assert.equal(ro.critic.critic_verdict, "APPROVED");
  assert.equal(ro.critic.effective, "APPROVED", "the board re-gated the findings; the receipt's own gate said INVALID");
  assert.equal(ro.critic.free, false);
  assert.equal(ro.critic.model, "commandcode/claude-haiku-5-5");
  assert.match(ro.critic.findings_sha256, /^[0-9a-f]{64}$/);
  assert.match(ro.critic.receipt_sha256, /^[0-9a-f]{64}$/);
  assert.equal(ro.reviewed_sha, sha);
  assert.equal(ro.cost, 0.0042, "cost is tree.total_cost when the receipt has one");
  assert.equal(ro.senior_needed, false);
  assert.equal(t.senior.required, false);

  const so = board(c, "signoff", "p2-happy", "--by", "critic", "--owner", "s1");
  assert.equal(so.status, 0, so.stderr);
  const s = so.ticket.signoffs[0];
  assert.equal(s.by, "critic");
  assert.equal(s.reviewed_sha, sha);
  assert.equal(s.free, false);
  assert.equal(s.invalidated_by, null);

  const g = gatesOk(c, "p2-happy");
  assert.equal(g.gates.length, 1);
  assert.deepEqual(g.gates[0].argv, ["node", "-e", "0"]);
  assert.equal(g.gates[0].exit, 0);
  assert.equal(g.gates[0].sha, sha);
  assert.ok(fs.existsSync(g.gates[0].log_path), "every gate keeps its log");

  const rd = board(c, "ready", "p2-happy", "--owner", "s1");
  assert.equal(rd.status, 0, rd.stderr);
  const lines = rd.stdout.trim().split("\n");
  assert.equal(lines.length, 2, "ready prints the ticket, then the wake-up line");
  assert.equal(JSON.parse(lines[0]).stage, "ready");
  assert.equal(lines[1], `READY p2-happy feat/p2-happy ${sha} — board verify then train`);
  assert.equal(fs.existsSync(lockDir(c, "p2-happy")), false, "ready releases the lock");

  const v = board(c, "verify", "p2-happy", "--sha", sha);
  assert.equal(v.status, 0, v.stderr);
  assert.equal(v.stdout, "", "verify prints nothing on success");

  const sh = board(c, "shipped", "p2-happy", "--sha", sha);
  assert.equal(sh.status, 0, sh.stderr);
  assert.equal(sh.ticket.stage, "shipped");
  assert.equal(sh.ticket.signoffs[0].reviewed_sha, sha);
});

test("phase 2 case 7: a free critic cannot reach ready until a human signs the same sha", () => {
  const c = mk();
  workingTicket(c, "p2-free");
  const sha = landBlastFile(c);
  const r = round(c, "p2-free", { critic: "receipts/critic-free.json", reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.rounds[0].critic.free, true);
  assert.equal(r.ticket.rounds[0].critic.free_source, "agent:critic-free");
  assert.equal(r.ticket.rounds[0].critic.effective, "APPROVED_FREE");

  const so = signedCritic(c, "p2-free");
  assert.equal(so.signoffs[0].free, true);
  gatesOk(c, "p2-free");

  const refused = board(c, "ready", "p2-free", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /free/);

  const hu = board(c, "signoff", "p2-free", "--by", "human");
  assert.equal(hu.status, 0, hu.stderr);
  const hs = hu.ticket.signoffs[1];
  assert.equal(hs.by, "human");
  assert.equal(hs.free, false);
  assert.equal(hs.reviewed_sha, sha);
  const ok = board(c, "ready", "p2-free", "--owner", "s1");
  assert.equal(ok.status, 0, ok.stderr);
  assert.equal(ok.ticket.stage, "ready");
});

test("phase 2 case 8: an unresolvable critic model is free (fail closed), a resolved paid or free model is not", () => {
  const c = mk();
  workingTicket(c, "p2-model");
  const sha = landBlastFile(c);

  const unknown = round(c, "p2-model", { critic: "receipts/critic-unknown.json", reviewed: sha });
  assert.equal(unknown.status, 0, unknown.stderr);
  assert.equal(unknown.ticket.rounds[0].critic.free, true, "no agent file and (agent default): fail closed");
  assert.equal(unknown.ticket.rounds[0].critic.free_source, "unknown");
  assert.equal(unknown.ticket.rounds[0].critic.effective, "APPROVED_FREE");

  installAgent(c, "critic", "commandcode/claude-haiku-5-5");
  const paid = round(c, "p2-model", { critic: "receipts/critic-unknown.json", reviewed: sha });
  assert.equal(paid.ticket.rounds[1].critic.model, "commandcode/claude-haiku-5-5", "(agent default) resolved via pool-health");
  assert.equal(paid.ticket.rounds[1].critic.free, false);
  assert.equal(paid.ticket.rounds[1].critic.effective, "APPROVED");

  installAgent(c, "critic", "opencode/mimo-v2.6-flash-free");
  const free = round(c, "p2-model", { critic: "receipts/critic-unknown.json", reviewed: sha });
  assert.equal(free.ticket.rounds[2].critic.free, true);
  assert.match(free.ticket.rounds[2].critic.free_source, /^model:/);
  assert.equal(free.ticket.rounds[2].critic.effective, "APPROVED_FREE");
});

test("cc-pacing-v2-a3b: a cc-critic receipt is paid whatever its model says; OpenCode free-ness unchanged", () => {
  // A fresh case per receipt: a ticket holds at most max_rounds (3) rounds, and each lands its own blast file.
  const firstRound = (id, critic) => {
    const c = mk();
    workingTicket(c, id);
    const sha = landBlastFile(c);
    const r = round(c, id, { critic: typeof critic === "function" ? critic(c) : critic, reviewed: sha });
    assert.equal(r.status, 0, r.stderr);
    return r.ticket.rounds[0].critic;
  };
  for (const [name, model, recorded] of [["empty", "", null], ["agent-default", "(agent default)", null], ["opus", "opus", "opus"]]) {
    const cr = firstRound(`p2-cc-${name}`, (c) => fixtureJson(c, `cc-critic-${name}`, "receipts/critic-unknown.json", { agent: "cc-critic", model }));
    assert.equal(cr.free, false, `model ${JSON.stringify(model)}`);
    assert.equal(cr.free_source, "agent:cc-critic");
    assert.equal(cr.model, recorded);
    assert.equal(cr.effective, "APPROVED");
  }
  const free = firstRound("p2-cc-ocfree", "receipts/critic-free.json");
  assert.equal(free.free, true, "a *-free OpenCode agent is still free");
  assert.equal(free.free_source, "agent:critic-free");
  const unknown = firstRound("p2-cc-ocunknown", "receipts/critic-unknown.json");
  assert.equal(unknown.free, true, "an unknown OpenCode agent with no model is still free");
  assert.equal(unknown.free_source, "unknown");
});

test("phase 2 case 9: a commit after the signoff blocks ready", () => {
  const c = mk();
  workingTicket(c, "p2-head");
  const sha = landBlastFile(c);
  assert.equal(round(c, "p2-head", { reviewed: sha }).status, 0);
  signedCritic(c, "p2-head");
  gatesOk(c, "p2-head");

  const newer = commitFile(c, "bin/extra.mjs", "// the work moved on after the review\n");
  assert.notEqual(newer, sha);
  const refused = board(c, "ready", "p2-head", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /not the signed-off sha/);
  assert.equal(JSON.parse(bytes(ticketFile(c, "p2-head"))).stage, "working");
});

test("phase 2 case 10: a later round invalidates every earlier signoff", () => {
  const c = mk();
  workingTicket(c, "p2-inval");
  const sha = landBlastFile(c);
  round(c, "p2-inval", { reviewed: sha });
  signedCritic(c, "p2-inval");
  gatesOk(c, "p2-inval");

  const second = round(c, "p2-inval", { reviewed: sha });
  assert.equal(second.status, 0, second.stderr);
  assert.equal(second.ticket.rounds.length, 2);
  assert.equal(second.ticket.signoffs[0].invalidated_by, 2, "round 2 invalidates the round-1 signoff");

  const refused = board(c, "ready", "p2-inval", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /invalidated/);
});

test("phase 2 case 11: the 4th counted round blocks rounds_exhausted and records nothing", () => {
  const c = mk();
  workingTicket(c, "p2-cap");
  const sha = landBlastFile(c);
  for (let i = 1; i <= 3; i++) {
    const r = round(c, "p2-cap", { reviewed: sha });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.ticket.rounds.length, i);
    assert.equal(r.ticket.rounds[i - 1].counted, true);
  }
  const before = JSON.parse(bytes(ticketFile(c, "p2-cap")));
  assert.equal(before.senior.required, true, "a third counted round requires senior review");

  const fourth = round(c, "p2-cap", { reviewed: sha });
  assert.equal(fourth.status, 0, fourth.stderr);
  assert.equal(fourth.ticket.stage, "blocked");
  assert.equal(fourth.ticket.blocked.reason, "rounds_exhausted");
  assert.equal(fourth.ticket.rounds.length, 3, "the refused 4th round is not recorded");
  assert.equal(fs.existsSync(lockDir(c, "p2-cap")), false, "leaving working drops the lock");
  // blocked is not working: even a valid uncounted round is refused by the stage machine, not re-blocked.
  const after = round(c, "p2-cap", { worker: "receipts/worker-timeout.json", findings: null, critic: null, reviewed: null });
  assert.equal(after.status, 1, after.stderr);
  assert.match(after.stderr, /round needs stage working, ticket is blocked/);
});

test("round: INVALID findings (no BLAST RADIUS) are refused before the cap; ticket unchanged", () => {
  const c = mk();
  workingTicket(c, "p2-invalid");
  const sha = landBlastFile(c);
  const invalid = fixtureText(c, "findings-invalid.md", "VERDICT: APPROVED\nTESTS: not run\n");

  const before = bytes(ticketFile(c, "p2-invalid"));
  const r = round(c, "p2-invalid", { findings: invalid, reviewed: sha });
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /no BLAST RADIUS entries/);
  assert.match(r.stderr, /save the critic's reply verbatim/);
  assert.match(r.stderr, /re-run the critic/);
  const after = JSON.parse(bytes(ticketFile(c, "p2-invalid")));
  assert.deepEqual(after.rounds, [], "no round recorded");
  assert.equal(after.stage, "working", "ticket stays working, never blocked by INVALID paperwork");
  assert.deepEqual(after.signoffs, [], "no signoffs");
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "p2-invalid"))) === 0, "nothing written");
});

test("round: valid findings still record a counted round", () => {
  const c = mk();
  workingTicket(c, "p2-valid-findings");
  const sha = landBlastFile(c);
  const r = round(c, "p2-valid-findings", { reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.rounds.length, 1);
  assert.equal(r.ticket.rounds[0].counted, true);
  assert.equal(r.ticket.rounds[0].critic.effective, "APPROVED");
});

test("round: three INVALID attempts in a row never reach rounds_exhausted", () => {
  const c = mk();
  workingTicket(c, "p2-invalid-cap");
  const sha = landBlastFile(c);
  const invalid = fixtureText(c, "findings-invalid.md", "VERDICT: APPROVED\nTESTS: not run\n");
  for (let i = 1; i <= 3; i++) {
    const r = round(c, "p2-invalid-cap", { findings: invalid, reviewed: sha });
    assert.equal(r.status, 1, `attempt ${i}: ${r.stderr}`);
    assert.match(r.stderr, /no BLAST RADIUS entries/);
  }
  const t = JSON.parse(bytes(ticketFile(c, "p2-invalid-cap")));
  assert.deepEqual(t.rounds, [], "three INVALID attempts recorded nothing");
  assert.equal(t.stage, "working", "not blocked by INVALID paperwork");
  // A 4th INVALID attempt is still refused, never rounds_exhausted.
  const fourth = round(c, "p2-invalid-cap", { findings: invalid, reviewed: sha });
  assert.equal(fourth.status, 1, fourth.stderr);
  assert.equal(JSON.parse(bytes(ticketFile(c, "p2-invalid-cap"))).rounds.length, 0);
});

test("round: INVALID findings after three counted rounds are refused, not rounds_exhausted", () => {
  const c = mk();
  workingTicket(c, "p2-invalid-after-cap");
  const sha = landBlastFile(c);
  // Seed three counted rounds (approved findings each time), exhausting the cap.
  for (let i = 1; i <= 3; i++) {
    const r = round(c, "p2-invalid-after-cap", { reviewed: sha });
    assert.equal(r.status, 0, `counted round ${i}: ${r.stderr}`);
    assert.equal(r.ticket.rounds.length, i);
    assert.equal(r.ticket.rounds[i - 1].counted, true);
  }
  const invalid = fixtureText(c, "findings-invalid.md", "VERDICT: APPROVED\nTESTS: not run\n");
  const before = bytes(ticketFile(c, "p2-invalid-after-cap"));
  const r = round(c, "p2-invalid-after-cap", { findings: invalid, reviewed: sha });
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /findings gate INVALID/, "INVALID refusal must win over the cap");
  assert.ok(!/rounds_exhausted/.test(r.stderr), "a refused INVALID never reaches rounds_exhausted");
  const after = JSON.parse(bytes(ticketFile(c, "p2-invalid-after-cap")));
  assert.equal(after.stage, "working", "ticket stays working, not blocked by INVALID paperwork");
  assert.equal(after.rounds.length, 3, "no fourth round recorded");
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "p2-invalid-after-cap"))) === 0, "nothing written");
});

test("phase 2 case 12: a worker question blocks the ticket without recording a round", () => {
  const c = mk();
  workingTicket(c, "p2-question");
  // B4: findings are only meaningful for a done round.
  const noisy = board(c, "round", "p2-question", "--owner", "s1", "--worker-receipt", fixture(c, "receipts/worker-blocked-question.json"), "--findings", fixture(c, "findings/approved.md"));
  assert.equal(noisy.status, 2, noisy.stderr);
  assert.match(noisy.stderr, /--findings is only accepted/);

  const r = round(c, "p2-question", { worker: "receipts/worker-blocked-question.json", findings: null, critic: null, reviewed: null });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "blocked");
  assert.equal(r.ticket.blocked.reason, "worker_question");
  assert.match(r.ticket.blocked.note, /which adapter/);
  assert.equal(r.ticket.rounds.length, 0);
  assert.equal(fs.existsSync(lockDir(c, "p2-question")), false);
  assert.equal(board(c, "unblock", "p2-question", "--by", "human", "--note", "the adapter question is answered").status, 0);
});

test("round: no healthy pool blocks with reason no_pool", () => {
  const c = mk();
  workingTicket(c, "p2-nopool");
  const r = round(c, "p2-nopool", { worker: "receipts/worker-no-pool.json", findings: null, critic: null, reviewed: null });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "blocked");
  assert.equal(r.ticket.blocked.reason, "no_pool");
  assert.equal(r.ticket.rounds.length, 0);
});

test("cc-pacing-v2-a3b: a lone cc reader's cc-slot-timeout receipt blocks like no-healthy-pool", () => {
  const c = mk();
  workingTicket(c, "p2-slot");
  const w = fixtureJson(c, "worker-slot-timeout", "receipts/worker-no-pool.json", { agent: "cc-critic", exit: "cc-slot-timeout" });
  const r = round(c, "p2-slot", { worker: w, findings: null, critic: null, reviewed: null });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "blocked");
  assert.equal(r.ticket.blocked.reason, "no_pool");
});

test("round: timeout and no-output are recorded uncounted; a third in a row blocks for a human", () => {
  const c = mk();
  workingTicket(c, "p2-retry");
  const t1 = round(c, "p2-retry", { worker: "receipts/worker-timeout.json", findings: null, critic: null, reviewed: null });
  assert.equal(t1.status, 0, t1.stderr);
  assert.equal(t1.ticket.rounds[0].counted, false);
  assert.equal(t1.ticket.rounds[0].worker.outcome, "timeout");
  assert.equal(t1.ticket.rounds[0].critic, null);
  assert.equal(t1.ticket.rounds[0].reviewed_sha, null);
  assert.equal(t1.ticket.rounds[0].cost, 0.031);
  assert.equal(t1.ticket.stage, "working");

  const t2 = round(c, "p2-retry", { worker: "receipts/worker-no-output.json", findings: null, critic: null, reviewed: null });
  assert.equal(t2.ticket.rounds[1].worker.outcome, "no_output");
  assert.equal(t2.ticket.stage, "working");

  const t3 = round(c, "p2-retry", { worker: "receipts/worker-timeout.json", findings: null, critic: null, reviewed: null });
  assert.equal(t3.status, 0, t3.stderr);
  assert.equal(t3.ticket.stage, "blocked");
  assert.equal(t3.ticket.blocked.reason, "manual");
  assert.match(t3.ticket.blocked.note, /3rd consecutive uncounted/);
  assert.equal(t3.ticket.rounds.length, 2, "the third uncounted run blocks; it is not recorded");
});

test("round: a landed timeout receipt counts as done and proceeds to a reviewed round", () => {
  const c = mk();
  workingTicket(c, "p2-landed");
  const sha = landBlastFile(c);
  const t = round(c, "p2-landed", { worker: "receipts/worker-landed.json", reviewed: sha });
  assert.equal(t.status, 0, t.stderr);
  assert.equal(t.ticket.rounds.length, 1);
  assert.equal(t.ticket.rounds[0].counted, true);
  assert.equal(t.ticket.rounds[0].worker.outcome, "done", "a landed timeout is done");
  assert.equal(t.ticket.rounds[0].reviewed_sha, sha);
});

test("round input matrix: a done round needs findings, a reviewed sha and exactly one critic source", () => {
  const c = mk();
  workingTicket(c, "p2-args");
  const sha = landBlastFile(c);
  const args = (extra) => ["round", "p2-args", "--owner", "s1", "--worker-receipt", fixture(c, "receipts/worker-done.json"), ...extra];
  const fnd = () => ["--findings", fixture(c, "findings/approved.md")];
  const crt = () => ["--critic-receipt", fixture(c, "receipts/critic-paid.json")];

  const noReviewed = board(c, ...args([...fnd(), ...crt()]));
  assert.equal(noReviewed.status, 2, noReviewed.stderr);
  assert.match(noReviewed.stderr, /reviewed-sha/);
  const both = board(c, ...args([...fnd(), ...crt(), "--native-critic", "sonnet", "--reviewed-sha", sha]));
  assert.equal(both.status, 2, both.stderr);
  assert.match(both.stderr, /exactly one/);
  assert.equal(board(c, ...args([...fnd(), "--reviewed-sha", sha])).status, 2, "no critic source");
  assert.equal(board(c, ...args([...crt(), "--reviewed-sha", sha])).status, 2, "no findings");
  const stale = board(c, ...args([...fnd(), ...crt(), "--reviewed-sha", "0".repeat(40)]));
  assert.equal(stale.status, 1, stale.stderr);
  assert.match(stale.stderr, /is not HEAD/);
  const wrongOwner = board(c, "round", "p2-args", "--owner", "s9", "--worker-receipt", fixture(c, "receipts/worker-done.json"), ...fnd(), ...crt(), "--reviewed-sha", sha);
  assert.equal(wrongOwner.status, 1, wrongOwner.stderr);
  assert.match(wrongOwner.stderr, /owned by s1/);
  assert.equal(JSON.parse(bytes(ticketFile(c, "p2-args"))).rounds.length, 0, "no refusal wrote a round");

  const native = board(c, ...args([...fnd(), "--native-critic", "sonnet", "--reviewed-sha", sha]));
  assert.equal(native.status, 0, native.stderr);
  const c2 = native.ticket.rounds[0].critic;
  assert.equal(c2.source, "native");
  assert.equal(c2.free, false);
  assert.equal(c2.free_source, "native:sonnet");
  assert.equal(c2.receipt_sha256, null);
  assert.equal(c2.effective, "APPROVED");
});

test("signoff: needs a round, refuses a CHANGES_REQUESTED round, and a senior needs proof and an APPROVED reply", () => {
  const c = mk();
  workingTicket(c, "p2-sign");
  assert.equal(board(c, "signoff", "p2-sign", "--by", "critic", "--owner", "s1").status, 1, "no round yet");

  const sha = landBlastFile(c);
  assert.equal(round(c, "p2-sign", { findings: "findings/changes.md", reviewed: sha }).status, 0);
  const refused = board(c, "signoff", "p2-sign", "--by", "critic", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /CHANGES_REQUESTED/);

  assert.equal(board(c, "signoff", "p2-sign", "--by", "bystander", "--owner", "s1").status, 2);
  const noProof = board(c, "signoff", "p2-sign", "--by", "senior", "--owner", "s1", "--findings", fixture(c, "findings/senior.md"));
  assert.equal(noProof.status, 2, "a senior signoff needs --receipt or --native");
  const badSenior = board(c, "signoff", "p2-sign", "--by", "senior", "--owner", "s1", "--findings", fixture(c, "findings/changes.md"), "--native", "opus");
  assert.equal(badSenior.status, 1, badSenior.stderr);
  assert.match(badSenior.stderr, /CHANGES_REQUESTED/);

  // A human sign-off belongs to no ticket owner, and is bound to the current HEAD.
  const human = board(c, "signoff", "p2-sign", "--by", "human");
  assert.equal(human.status, 0, human.stderr);
  const s = human.ticket.signoffs.pop();
  assert.equal(s.by, "human");
  assert.equal(s.free, false);
  assert.equal(s.free_source, null);
  assert.equal(s.reviewed_sha, sha);
});

test("phase 2 case 13: senior is required by a critic, by a third counted round, or by a guarded diff", () => {
  // (a) the critic asks for it; only a senior signoff then satisfies ready
  const c = mk();
  workingTicket(c, "p2-senior");
  const sha = landBlastFile(c);
  const r = round(c, "p2-senior", { findings: "findings/senior-needed.md", reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.senior.required, true);
  assert.deepEqual(r.ticket.senior.reasons, ["critic: SENIOR_REVIEW needed"]);
  assert.equal(r.ticket.rounds[0].senior_needed, true);
  signedCritic(c, "p2-senior");
  gatesOk(c, "p2-senior");
  const refused = board(c, "ready", "p2-senior", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /senior review is required/);

  const sen = board(c, "signoff", "p2-senior", "--by", "senior", "--owner", "s1", "--findings", fixture(c, "findings/senior.md"), "--native", "opus");
  assert.equal(sen.status, 0, sen.stderr);
  const ss = sen.ticket.signoffs.pop();
  assert.equal(ss.by, "senior");
  assert.equal(ss.free, false);
  assert.equal(ss.free_source, "native:opus");
  assert.equal(ss.reviewed_sha, sha);
  const ok = board(c, "ready", "p2-senior", "--owner", "s1");
  assert.equal(ok.status, 0, ok.stderr);

  // (b) three counted rounds
  const c2 = mk();
  workingTicket(c2, "p2-three");
  const sha2 = landBlastFile(c2);
  for (let i = 1; i <= 3; i++) assert.equal(round(c2, "p2-three", { reviewed: sha2 }).status, 0);
  const t2 = JSON.parse(bytes(ticketFile(c2, "p2-three")));
  assert.equal(t2.senior.required, true);
  assert.ok(t2.senior.reasons.includes("counted rounds 3 > 2"), JSON.stringify(t2.senior.reasons));
  const sen2 = board(c2, "signoff", "p2-three", "--by", "senior", "--owner", "s1", "--findings", fixture(c2, "findings/senior.md"), "--receipt", fixture(c2, "receipts/senior-paid.json"));
  assert.equal(sen2.status, 0, sen2.stderr);
  const ss2 = sen2.ticket.signoffs.pop();
  assert.equal(ss2.free, false);
  assert.equal(ss2.model, "commandcode/claude-sonnet-5-5");

  // (c) the diff touches a guarded path, even though the declared scope did not
  const c3 = mk();
  workingTicket(c3, "p2-guard");
  landBlastFile(c3);
  const sha3 = commitFile(c3, "ops/release.sh", "#!/bin/sh\nexit 0\n");
  const r3 = round(c3, "p2-guard", { reviewed: sha3 });
  assert.equal(r3.status, 0, r3.stderr);
  assert.equal(r3.ticket.senior.required, true);
  assert.ok(r3.ticket.senior.reasons.includes("guarded path: ops/release.sh"), JSON.stringify(r3.ticket.senior.reasons));
});

test("phase 2 case 14: a failing gate and gates at an older sha both block ready; a failed gate never changes stage", () => {
  // (a) gate exit 1
  const c = mk();
  workingTicket(c, "p2-gatefail");
  const sha = landBlastFile(c);
  round(c, "p2-gatefail", { reviewed: sha });
  signedCritic(c, "p2-gatefail");
  setAdapterGates(c, [["node", "-e", "process.exit(1)"]]);
  const g = board(c, "gates", "p2-gatefail", "--owner", "s1");
  assert.equal(g.status, 0, g.stderr);
  assert.equal(g.ticket.stage, "working", "a failed gate is evidence, not a stage change");
  assert.equal(g.ticket.gates.length, 1);
  assert.equal(g.ticket.gates[0].exit, 1);
  assert.ok(fs.existsSync(g.ticket.gates[0].log_path));
  const refused = board(c, "ready", "p2-gatefail", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /has no exit 0 at/);

  // (b) gates recorded at an older sha than the signed-off one
  const c2 = mk();
  workingTicket(c2, "p2-gateold");
  const sha2 = landBlastFile(c2);
  round(c2, "p2-gateold", { reviewed: sha2 });
  signedCritic(c2, "p2-gateold");
  gatesOk(c2, "p2-gateold");
  const newer = commitFile(c2, "bin/extra.mjs", "// newer than the gate run\n");
  const hu = board(c2, "signoff", "p2-gateold", "--by", "human");
  assert.equal(hu.status, 0, hu.stderr);
  assert.equal(hu.ticket.signoffs.pop().reviewed_sha, newer);
  const stale = board(c2, "ready", "p2-gateold", "--owner", "s1");
  assert.equal(stale.status, 1, stale.stderr);
  assert.match(stale.stderr, new RegExp(`has no exit 0 at ${newer}`));
});

test("phase 2 case 15: a dirty worktree blocks ready; a bare node_modules entry is ignored", () => {
  const c = mk();
  workingTicket(c, "p2-dirty");
  const sha = landBlastFile(c);
  round(c, "p2-dirty", { reviewed: sha });
  signedCritic(c, "p2-dirty");
  gatesOk(c, "p2-dirty");

  fs.writeFileSync(path.join(c.wt, "junk.txt"), "untracked\n");
  const refused = board(c, "ready", "p2-dirty", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /worktree is dirty/);
  fs.rmSync(path.join(c.wt, "junk.txt"));

  // The shared install appears as one `node_modules` line, which is not the ticket's work (B13).
  fs.writeFileSync(path.join(c.wt, "node_modules"), "link\n");
  const ok = board(c, "ready", "p2-dirty", "--owner", "s1");
  assert.equal(ok.status, 0, ok.stderr);
  assert.equal(ok.ticket.stage, "ready");
});

test("phase 2 case 20: shipped with the wrong sha is refused; verify is idempotent and read-only", () => {
  const c = mk();
  const { sha } = atReady(c, "p2-idem");
  const before = bytes(ticketFile(c, "p2-idem"));

  assert.equal(board(c, "verify", "p2-idem", "--sha", "0".repeat(40)).status, 1, "a foreign sha never verifies");
  assert.equal(board(c, "verify", "p2-idem", "--sha", sha).status, 0);
  assert.equal(board(c, "verify", "p2-idem", "--sha", sha).status, 0);
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "p2-idem"))) === 0, "verify never writes");

  const wrong = board(c, "shipped", "p2-idem", "--sha", "0".repeat(40));
  assert.equal(wrong.status, 1, wrong.stderr);
  assert.equal(JSON.parse(bytes(ticketFile(c, "p2-idem"))).stage, "ready", "a refused ship writes nothing");
  const sh = board(c, "shipped", "p2-idem", "--sha", sha);
  assert.equal(sh.status, 0, sh.stderr);
  assert.equal(sh.ticket.stage, "shipped");
  assert.equal(board(c, "verify", "p2-idem", "--sha", sha).status, 1, "verify is for the ready window, not after shipping");
});

// ---------------------------------------------------------------- round 2: critic findings 1, 2, 4, 5, 6, 7
test("finding 1: an uncounted round never clears a critic's SENIOR_REVIEW: needed", () => {
  const c = mk();
  workingTicket(c, "p2-keep-senior");
  const sha = landBlastFile(c);
  const r = round(c, "p2-keep-senior", { findings: "findings/senior-needed.md", reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.senior.required, true);
  signedCritic(c, "p2-keep-senior");

  // A timeout round carries no findings, so there is no critic answer to recompute from: it must not clear the
  // requirement the last real review asked for.
  const t = round(c, "p2-keep-senior", { worker: "receipts/worker-timeout.json", findings: null, critic: null, reviewed: null });
  assert.equal(t.status, 0, t.stderr);
  assert.equal(t.ticket.stage, "working");
  assert.equal(t.ticket.rounds.length, 2);
  assert.equal(t.ticket.rounds[1].counted, false);
  assert.equal(t.ticket.senior.required, true, "the uncounted round kept the senior requirement");
  assert.deepEqual(t.ticket.senior.reasons, ["critic: SENIOR_REVIEW needed"]);

  gatesOk(c, "p2-keep-senior");
  const refused = board(c, "ready", "p2-keep-senior", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /senior review is required/);
});

test("finding 2: a free senior is refused, and cannot satisfy senior.required in either signoff order", () => {
  const freeSenior = (sha) => ({
    by: "senior",
    model: "opencode/mimo-v2.6-flash-free",
    free: true,
    free_source: "model:opencode/mimo-v2.6-flash-free",
    reviewed_sha: sha,
    at: new Date().toISOString(),
    invalidated_by: null,
  });

  // (a) `signoff --by senior` refuses a free receipt outright.
  const c = mk();
  workingTicket(c, "p2-free-senior");
  const sha = landBlastFile(c);
  round(c, "p2-free-senior", { findings: "findings/senior-needed.md", reviewed: sha });
  signedCritic(c, "p2-free-senior");
  const freeReceipt = fixtureJson(c, "senior-free", "receipts/senior-paid.json", { agent: "senior-free", model: "(agent default)" });
  const refused = board(c, "signoff", "p2-free-senior", "--by", "senior", "--owner", "s1", "--findings", fixture(c, "findings/senior.md"), "--receipt", freeReceipt);
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /must be a paid review/);
  assert.equal(JSON.parse(bytes(ticketFile(c, "p2-free-senior"))).signoffs.length, 1, "the refused senior signoff wrote nothing");

  // (b) A ticket that already holds a free senior signoff (from before the guard) still cannot reach ready.
  // Order A: the free senior is the newest signoff -> the free rule refuses it.
  const cA = mk();
  workingTicket(cA, "p2-order-a");
  const shaA = landBlastFile(cA);
  round(cA, "p2-order-a", { findings: "findings/senior-needed.md", reviewed: shaA });
  signedCritic(cA, "p2-order-a");
  editTicket(cA, "p2-order-a", (t) => t.signoffs.push(freeSenior(shaA)));
  gatesOk(cA, "p2-order-a");
  const a = board(cA, "ready", "p2-order-a", "--owner", "s1");
  assert.equal(a.status, 1, a.stderr);
  assert.match(a.stderr, /is free/);

  // Order B: the paid critic is newest, so the free rule passes — the senior rule must still refuse. This is the
  // order that used to reach ready without a paid senior.
  const cB = mk();
  workingTicket(cB, "p2-order-b");
  const shaB = landBlastFile(cB);
  round(cB, "p2-order-b", { findings: "findings/senior-needed.md", reviewed: shaB });
  editTicket(cB, "p2-order-b", (t) => t.signoffs.push(freeSenior(shaB)));
  signedCritic(cB, "p2-order-b");
  gatesOk(cB, "p2-order-b");
  const b = board(cB, "ready", "p2-order-b", "--owner", "s1");
  assert.equal(b.status, 1, "a free senior never satisfies senior.required");
  assert.match(b.stderr, /senior review is required/);
});

test("finding 4: gates refuse a dirty worktree, and a gate that never started is logged as such", () => {
  const c = mk();
  workingTicket(c, "p2-gates-dirty");
  const sha = landBlastFile(c);
  round(c, "p2-gates-dirty", { reviewed: sha });
  signedCritic(c, "p2-gates-dirty");

  fs.writeFileSync(path.join(c.wt, "junk.txt"), "uncommitted code\n");
  const dirty = board(c, "gates", "p2-gates-dirty", "--owner", "s1");
  assert.equal(dirty.status, 1, dirty.stderr);
  assert.match(dirty.stderr, /worktree is dirty/);
  assert.deepEqual(JSON.parse(bytes(ticketFile(c, "p2-gates-dirty"))).gates, [], "no gate ran on the dirty tree");
  fs.rmSync(path.join(c.wt, "junk.txt"));

  // A gate that cannot start is a broken adapter (127 + "could not start"), not a slow one (124 + "timed out").
  setAdapterGates(c, [["board-no-such-binary-xyz", "--version"]]);
  const missing = gatesOk(c, "p2-gates-dirty");
  assert.equal(missing.gates[0].exit, 127);
  assert.equal(missing.gates[0].sha, sha);
  const log = fs.readFileSync(missing.gates[0].log_path, "utf8");
  assert.match(log, /could not start/);
  assert.doesNotMatch(log, /timed out/);
});

test("finding 5: a blast-radius test path that leaves the worktree is refused", () => {
  const c = mk();
  workingTicket(c, "p2-escape");
  const sha = landBlastFile(c);
  // The escaping file exists, so an existence-only check would have accepted it.
  fs.writeFileSync(path.join(c.root, "escape.test.mjs"), "// outside the worktree\n");
  editTicket(c, "p2-escape", (t) => {
    const b = t.blast_radius.find((x) => x.test === "bin/load.test.mjs");
    assert.ok(b, "the fixture Mandate's load() bullet is the one whose expectations changed");
    b.test = "../escape.test.mjs";
  });
  round(c, "p2-escape", { reviewed: sha });
  signedCritic(c, "p2-escape");
  gatesOk(c, "p2-escape");
  const refused = board(c, "ready", "p2-escape", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /resolves outside the worktree/);
});

test("finding 6: an UNREQUESTED caller line is never approvable, and a -free agent stays free with a paid model", () => {
  // (a) The mechanical gate outranks the critic's own APPROVED, so the round cannot be signed off as a critic.
  const c = mk();
  workingTicket(c, "p2-unreq");
  const sha = landBlastFile(c);
  const r = round(c, "p2-unreq", { findings: "findings/unrequested.md", reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  const cr = r.ticket.rounds[0].critic;
  assert.equal(cr.critic_verdict, "APPROVED", "the fixture critic wrote APPROVED");
  assert.equal(cr.effective, "CHANGES_REQUESTED", "the unrequested caller line overrides it");
  assert.equal(cr.reasons.length, 1);
  const refused = board(c, "signoff", "p2-unreq", "--by", "critic", "--owner", "s1");
  assert.equal(refused.status, 1, refused.stderr);
  assert.match(refused.stderr, /CHANGES_REQUESTED/);

  // (b) The agent name decides free-ness before the model does: a paid model on `critic-free` is still free.
  const c2 = mk();
  workingTicket(c2, "p2-free-agent");
  const sha2 = landBlastFile(c2);
  const paidModel = fixtureJson(c2, "critic-free-paid-model", "receipts/critic-free.json", { model: "commandcode/claude-haiku-5-5" });
  const r2 = round(c2, "p2-free-agent", { critic: paidModel, reviewed: sha2 });
  assert.equal(r2.status, 0, r2.stderr);
  assert.equal(r2.ticket.rounds[0].critic.free, true);
  assert.equal(r2.ticket.rounds[0].critic.free_source, "agent:critic-free");
  assert.equal(r2.ticket.rounds[0].critic.effective, "APPROVED_FREE");

  // (b2) A model on a `free-only` provider (owner allowlist) is free, even on a paid-looking agent name.
  const c4 = mk();
  workingTicket(c4, "p2-free-only");
  const sha4 = landBlastFile(c4);
  fs.mkdirSync(path.join(c4.env.ORCH_HOME, ".config", "orchestrator"), { recursive: true });
  fs.writeFileSync(path.join(c4.env.ORCH_HOME, ".config", "orchestrator", "providers.json"), JSON.stringify({ google: { decision: "free-only", allow: ["gemini-*-flash*"] } }));
  const policyFree = fixtureJson(c4, "critic-free-only", "receipts/critic-paid.json", { model: "google/gemini-3-flash-preview" });
  const r4 = round(c4, "p2-free-only", { critic: policyFree, reviewed: sha4 });
  assert.equal(r4.status, 0, r4.stderr);
  assert.equal(r4.ticket.rounds[0].critic.free, true);
  assert.equal(r4.ticket.rounds[0].critic.effective, "APPROVED_FREE");

  // (c) Only a bare `node_modules` entry is the shared install: a nested one is still the ticket's own dirt.
  const c3 = mk();
  workingTicket(c3, "p2-nested-modules");
  const sha3 = landBlastFile(c3);
  round(c3, "p2-nested-modules", { reviewed: sha3 });
  signedCritic(c3, "p2-nested-modules");
  gatesOk(c3, "p2-nested-modules");
  fs.mkdirSync(path.join(c3.wt, "node_modules", "dep"), { recursive: true });
  fs.writeFileSync(path.join(c3.wt, "node_modules", "dep", "index.js"), "// untracked\n");
  const nested = board(c3, "ready", "p2-nested-modules", "--owner", "s1");
  assert.equal(nested.status, 1, nested.stderr);
  assert.match(nested.stderr, /worktree is dirty .*node_modules\/dep/);
  fs.rmSync(path.join(c3.wt, "node_modules"), { recursive: true, force: true });

  fs.mkdirSync(path.join(c3.wt, "foo", "node_modules"), { recursive: true });
  fs.writeFileSync(path.join(c3.wt, "foo", "node_modules", "index.js"), "// untracked\n");
  const foo = board(c3, "ready", "p2-nested-modules", "--owner", "s1");
  assert.equal(foo.status, 1, foo.stderr);
  assert.match(foo.stderr, /worktree is dirty .*foo\/node_modules/);
  fs.rmSync(path.join(c3.wt, "foo"), { recursive: true, force: true });

  const ok = board(c3, "ready", "p2-nested-modules", "--owner", "s1");
  assert.equal(ok.status, 0, ok.stderr);
  assert.equal(ok.ticket.stage, "ready");
});

test("finding 7: a receipt-supplied agent name cannot walk out of the agents dir", () => {
  const c = mk();
  workingTicket(c, "p2-traversal");
  const sha = landBlastFile(c);
  // What `path.join(agentsDir, "../../evil.md")` would read: a paid model one level above `opencode/`.
  const evil = path.join(c.env.ORCH_HOME, ".config", "evil.md");
  fs.mkdirSync(path.dirname(evil), { recursive: true });
  fs.writeFileSync(evil, "---\nmodel: commandcode/claude-haiku-5-5\n---\n");

  const trav = fixtureJson(c, "critic-traversal", "receipts/critic-unknown.json", { agent: "../../evil" });
  const r = round(c, "p2-traversal", { critic: trav, reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  const cr = r.ticket.rounds[0].critic;
  assert.notEqual(cr.model, "commandcode/claude-haiku-5-5", "an invalid agent name is never resolved");
  assert.equal(cr.free, true, "and an unresolvable review is free (fail closed)");
  assert.equal(cr.free_source, "unknown");
});

// ---------------------------------------------------------------- Phase 3: attach + watch
test("27. attach records the running worker's pid, process start time and output path", () => {
  const c = mk();
  workingTicket(c, "p3-attach");
  const out = path.join(c.root, "out", "worker-r1.md");
  const r = board(c, "attach", "p3-attach", "--owner", "s1", "--pid", String(process.pid), "--out", out);
  assert.equal(r.status, 0, r.stderr);
  const w = r.ticket.assignment.worker;
  assert.equal(w.pid, process.pid);
  assert.equal(w.out_path, out, "the output path is recorded absolute; it need not exist yet");
  assert.equal(r.ticket.assignment.missed_sweeps, 0, "a new worker starts a new liveness clock");
  assert.equal(r.ticket.stage, "working");
  assert.equal(r.ticket.history.pop().cmd, "attach");
  // The start time is this process's own, read with an argv array and no shell (design B7). A failed lookup is
  // null and liveness falls back to pid existence; on Windows PowerShell always answers for a live pid, so a null
  // here would mean the start-time check had silently degraded to "any process with this pid".
  if (process.platform === "win32") assert.ok(w.started, "PowerShell reports this process's start time");
  if (w.started !== null) {
    assert.match(w.started, /^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/);
    // npm test runs in-process (--test-isolation=none), so "this process" may be the long-lived runner: compare
    // against its real uptime instead of assuming a fresh per-file process.
    const expected = Date.now() - process.uptime() * 1000;
    assert.ok(Math.abs(Date.parse(w.started) - expected) < 120_000, "start time matches this process's uptime");
  }

  // Refusals and usage errors write nothing.
  const before = bytes(ticketFile(c, "p3-attach"));
  const notOwner = board(c, "attach", "p3-attach", "--owner", "s2", "--pid", String(process.pid), "--out", out);
  assert.equal(notOwner.status, 1, notOwner.stderr);
  assert.match(notOwner.stderr, /owned by s1/);
  assert.equal(board(c, "attach", "p3-attach", "--owner", "s1", "--pid", "abc", "--out", out).status, 2);
  assert.equal(board(c, "attach", "p3-attach", "--owner", "s1", "--out", out).status, 2, "--pid is required");
  assert.equal(board(c, "attach", "p3-attach", "--owner", "s1", "--pid", String(process.pid)).status, 2, "--out is required");
  assert.ok(Buffer.compare(before, bytes(ticketFile(c, "p3-attach"))) === 0, "no refusal wrote the ticket");

  created(c, "p3-queued");
  assert.equal(board(c, "attach", "p3-queued", "--owner", "s1", "--pid", String(process.pid), "--out", out).status, 1, "attach is working-only");
});

test("18. watch: stale once stays working, twice blocks; a live pid is never blocked; a slept sweep only records", () => {
  const t0 = Date.now();
  const at = (min) => new Date(t0 + min * 60_000).toISOString();
  const stageOf = (c, id) => JSON.parse(bytes(ticketFile(c, id)));

  // (a) no worker pid, no output and a heartbeat older than stale_minutes (45): the first sweep counts, the
  // second blocks `stale` and drops the lock.
  const c = mk();
  workingTicket(c, "p3-stale");
  const first = board(c, "watch", "--now", at(120));
  assert.equal(first.status, 0, first.stderr);
  assert.equal(stageOf(c, "p3-stale").stage, "working");
  assert.equal(stageOf(c, "p3-stale").assignment.missed_sweeps, 1);
  assert.ok(fs.existsSync(lockDir(c, "p3-stale")), "one missed sweep is not a verdict");
  assert.match(first.stdout, /^ID\tSTAGE\tOWNER\tROUNDS\tAGE_MIN\tEGM\tSIGNOFF/, "the sweep ends with the status table");

  const second = board(c, "watch", "--now", at(121));
  assert.equal(second.status, 0, second.stderr);
  const blocked = stageOf(c, "p3-stale");
  assert.equal(blocked.stage, "blocked");
  assert.equal(blocked.blocked.reason, "stale");
  assert.equal(blocked.assignment, null);
  assert.equal(fs.existsSync(lockDir(c, "p3-stale")), false, "leaving working drops the lock");
  assert.equal(board(c, "watch", "--now", at(122)).status, 0, "a blocked ticket is not swept again");

  // (b) a live worker pid is never blocked, however long the sweep runs: the pid and its start time decide.
  const c2 = mk();
  workingTicket(c2, "p3-live");
  const out2 = path.join(c2.root, "out", "worker-r1.md");
  assert.equal(board(c2, "attach", "p3-live", "--owner", "s1", "--pid", String(process.pid), "--out", out2).status, 0);
  for (const min of [200, 201, 202]) {
    assert.equal(board(c2, "watch", "--now", at(min)).status, 0);
    assert.equal(stageOf(c2, "p3-live").stage, "working");
    assert.equal(stageOf(c2, "p3-live").assignment.missed_sweeps, 0);
  }
  assert.ok(fs.existsSync(lockDir(c2, "p3-live")));

  // (b2) the start time is what makes a live pid *this* worker: a recycled pid (alive, different start time) with
  // no fresh output and a stale heartbeat is not live, so two sweeps block it — this is the only case that fails
  // if `started` is recorded but never compared.
  const c5 = mk();
  workingTicket(c5, "p3-recycled");
  const out5 = path.join(c5.root, "out", "worker-r1.md");
  assert.equal(board(c5, "attach", "p3-recycled", "--owner", "s1", "--pid", String(process.pid), "--out", out5).status, 0);
  editTicket(c5, "p3-recycled", (t) => {
    t.assignment.worker.started = new Date(t0 - 1000 * 60_000).toISOString(); // a different process held this pid
  });
  assert.equal(board(c5, "watch", "--now", at(120)).status, 0);
  assert.equal(stageOf(c5, "p3-recycled").stage, "working", "one sweep is not a verdict");
  assert.equal(stageOf(c5, "p3-recycled").assignment.missed_sweeps, 1);
  assert.equal(board(c5, "watch", "--now", at(121)).status, 0);
  assert.equal(stageOf(c5, "p3-recycled").stage, "blocked");
  assert.equal(stageOf(c5, "p3-recycled").blocked.reason, "stale");

  // (c) a dead worker whose output (or its event stream) is newer than stale_minutes is still live.
  const c3 = mk();
  workingTicket(c3, "p3-mtime");
  workingTicket(c3, "p3-events");
  const out3 = path.join(c3.root, "out", "worker-r1.md");
  const out4 = path.join(c3.root, "out", "worker-r2.md");
  fs.mkdirSync(path.dirname(out3), { recursive: true });
  fs.writeFileSync(out3, "RESULT: DONE\n");
  fs.writeFileSync(`${out4}.events.jsonl`, '{"type":"text"}\n');
  fs.utimesSync(out3, new Date(t0 + 120 * 60_000), new Date(t0 + 120 * 60_000));
  fs.utimesSync(`${out4}.events.jsonl`, new Date(t0 + 120 * 60_000), new Date(t0 + 120 * 60_000));
  assert.equal(board(c3, "attach", "p3-mtime", "--owner", "s1", "--pid", "999999", "--out", out3).status, 0);
  assert.equal(board(c3, "attach", "p3-events", "--owner", "s1", "--pid", "999999", "--out", out4).status, 0);
  assert.equal(board(c3, "watch", "--now", at(120)).status, 0);
  for (const id of ["p3-mtime", "p3-events"]) {
    assert.equal(stageOf(c3, id).stage, "working", `${id}: fresh output keeps a dead pid's ticket alive`);
    assert.equal(stageOf(c3, id).assignment.missed_sweeps, 0);
  }

  // (d) a sweep more than stale_minutes after the last one (the laptop slept) records only the timestamp: no
  // ticket is counted, even one that would have been blocked had the gap been observed.
  const c4 = mk();
  workingTicket(c4, "p3-sleep");
  const watchFile = path.join(c4.repo, ".opencode", "board", ".watch.json");
  fs.writeFileSync(watchFile, JSON.stringify({ at: new Date(t0).toISOString() }) + "\n");
  const before = stageOf(c4, "p3-sleep");
  const slept = board(c4, "watch", "--now", at(120));
  assert.equal(slept.status, 0, slept.stderr);
  const after = stageOf(c4, "p3-sleep");
  assert.equal(after.stage, "working");
  assert.equal(after.assignment.missed_sweeps, 0);
  assert.equal(after.epoch, before.epoch, "a slept sweep writes no ticket");
  assert.equal(JSON.parse(fs.readFileSync(watchFile, "utf8")).at, at(120), "it records the sweep time");
  // The next sweep, inside the window, is the first real observation.
  assert.equal(board(c4, "watch", "--now", at(121)).status, 0);
  assert.equal(stageOf(c4, "p3-sleep").assignment.missed_sweeps, 1);

  assert.equal(board(c4, "watch", "--now", "not-a-time").status, 2, "--now must be an ISO timestamp");
});



test("round: a stalled worker receipt is recorded as a timeout, uncounted", () => {
  const c = mk();
  workingTicket(c, "p2-stalled");
  const t = round(c, "p2-stalled", { worker: "receipts/worker-stalled.json", findings: null, critic: null, reviewed: null });
  assert.equal(t.status, 0, t.stderr);
  assert.equal(t.ticket.rounds[0].counted, false);
  assert.equal(t.ticket.rounds[0].worker.outcome, "timeout");
});

// reopen: the train refused a ready sha. Before this command the only way out of `ready` was `fail` + a new id.
test("reopen: ready → working keeps history, invalidates signoffs, and ready needs fresh evidence at the fix", () => {
  const c = mk();
  const { sha } = atReady(c, "re-one");
  const why = "train: settings-hub suite failed 11 tests at this sha";

  assert.equal(board(c, "reopen", "re-one", "--owner", "s1", "--harness", "claude").status, 2, "--note is required");
  assert.equal(board(c, "reopen", "re-one", "--owner", "s1", "--harness", "claude", "--note", "flaky").status, 1, "a short note is refused");
  assert.equal(board(c, "reopen", "re-one", "--owner", "s1", "--harness", "bob", "--note", why).status, 2);
  assert.equal(fs.existsSync(lockDir(c, "re-one")), false, "a refused reopen takes no lock");

  const r = board(c, "reopen", "re-one", "--owner", "s1", "--harness", "claude", "--note", why);
  assert.equal(r.status, 0, r.stderr);
  const t = r.ticket;
  assert.equal(t.stage, "working");
  assert.equal(t.assignment.owner, "s1");
  assert.ok(fs.existsSync(lockDir(c, "re-one")), "reopen takes the ticket lock again");
  assert.ok(t.signoffs.every((s) => s.invalidated_by === "reopen 1"), "every live signoff is invalidated");
  assert.deepEqual(t.reopens.map((x) => [x.n, x.after_round, x.note]), [[1, 1, why]]);
  assert.equal(t.rounds.length, 1, "rounds are never reset");
  assert.deepEqual(t.history.map((h) => h.cmd).slice(-2), ["ready", "reopen"]);
  assert.equal(board(c, "verify", "re-one", "--sha", sha).status, 1, "a reopened ticket is not verifiable");

  // The old evidence does not carry: same sha, no new round -> ready refuses.
  const stale = board(c, "ready", "re-one", "--owner", "s1");
  assert.equal(stale.status, 1);
  assert.match(stale.stderr, /every signoff was invalidated/);

  // A fix, a new round, signoff and gates at the new sha -> ready again, verifiable at the new sha only.
  const fix = commitFile(c, "bin/fix.mjs", "export const fixed = true;\n");
  assert.equal(round(c, "re-one", { reviewed: fix }).status, 0);
  signedCritic(c, "re-one");
  gatesOk(c, "re-one");
  const rd = board(c, "ready", "re-one", "--owner", "s1");
  assert.equal(rd.status, 0, rd.stderr);
  assert.equal(board(c, "verify", "re-one", "--sha", fix).status, 0);
  assert.equal(board(c, "verify", "re-one", "--sha", sha).status, 1, "the refused sha stays refused");
});

test("reopen: a same-sha re-ready needs a fresh gate run, not the refused lap's green gates", () => {
  const c = mk();
  const { sha } = atReady(c, "re-same");
  const r = board(c, "reopen", "re-same", "--owner", "s1", "--harness", "claude", "--note", "train: lap failed, suspected flaky suite");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.ticket.gates, [], "gate results are cleared");
  assert.equal(r.ticket.reopens[0].refused_sha, sha);
  assert.equal(round(c, "re-same", { reviewed: sha }).status, 0);
  signedCritic(c, "re-same");
  const noGates = board(c, "ready", "re-same", "--owner", "s1");
  assert.equal(noGates.status, 1, "old green gates must not carry the refused sha back to ready");
  assert.match(noGates.stderr, /has no exit 0/);
  assert.equal(board(c, "verify", "re-same", "--sha", sha).status, 1);
  gatesOk(c, "re-same");
  assert.equal(board(c, "ready", "re-same", "--owner", "s1").status, 0, "with fresh evidence a flaky lap can re-ready");
});

test("reopen: owner lock, stage table, worktree check, and the reopen cap", () => {
  const c = mk();
  const why = "train: merge conflict against brain-backend in nav.ts";
  workingTicket(c, "re-two");
  assert.equal(board(c, "reopen", "re-two", "--owner", "s1", "--harness", "claude", "--note", why).status, 1, "working is not ready");

  atReady(c, "re-cap");
  const bogus = fs.mkdtempSync(path.join(os.tmpdir(), "not-a-wt-"));
  CLEAN.push(bogus);
  const bad = board(c, "reopen", "re-cap", "--owner", "s1", "--harness", "claude", "--note", why, "--worktree", bogus);
  assert.equal(bad.status, 1, "a directory outside the repo is refused");
  assert.match(bad.stderr, /not a worktree of this repo/);
  seedLock(c, "re-cap", "someone-else");
  assert.equal(board(c, "reopen", "re-cap", "--owner", "s1", "--harness", "claude", "--note", why).status, 3, "a live foreign lock is contention");
  fs.rmSync(lockDir(c, "re-cap"), { recursive: true, force: true });

  for (const n of [1, 2]) {
    const r = board(c, "reopen", "re-cap", "--owner", "s1", "--harness", "claude", "--note", why);
    assert.equal(r.status, 0, r.stderr);
    const fix = commitFile(c, `bin/fix${n}.mjs`, `export const n = ${n};\n`);
    assert.equal(round(c, "re-cap", { reviewed: fix }).status, 0);
    // A counted-round total above 2 asks for a senior: a twice-refused ticket gets one, by the existing rule.
    const tk = JSON.parse(fs.readFileSync(ticketFile(c, "re-cap"), "utf8"));
    if (tk.senior.required) assert.equal(board(c, "signoff", "re-cap", "--by", "human").status, 0);
    signedCritic(c, "re-cap");
    gatesOk(c, "re-cap");
    assert.equal(board(c, "ready", "re-cap", "--owner", "s1").status, 0);
  }
  const third = board(c, "reopen", "re-cap", "--owner", "s1", "--harness", "claude", "--note", why);
  assert.equal(third.status, 1);
  assert.match(third.stderr, /already reopened 2 times/);
});

test("reopen: each lap gets its own round cap; the 4th round of one lap still blocks", () => {
  const c = mk();
  atReady(c, "re-lap"); // lap 0 used 1 counted round
  const why = "train: verify-commit failed the pinned suite at this sha";
  assert.equal(board(c, "reopen", "re-lap", "--owner", "s1", "--harness", "claude", "--note", why).status, 0);
  for (const n of [1, 2, 3]) {
    const fix = commitFile(c, `bin/lap${n}.mjs`, `export const n = ${n};\n`);
    const r = round(c, "re-lap", { reviewed: fix });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.ticket.stage, "working", `round ${n} of the new lap is allowed (4 counted in total by the 3rd)`);
  }
  const fourth = round(c, "re-lap", { reviewed: commitFile(c, "bin/lap4.mjs", "export const n = 4;\n") });
  assert.equal(fourth.status, 0, fourth.stderr);
  assert.equal(fourth.ticket.stage, "blocked");
  assert.equal(fourth.ticket.blocked.reason, "rounds_exhausted");
});

// ---------------------------------------------------------------- session (parallel dispatch)
test("session: recorded on a queued ticket, survives claim, shows in status --json only when set", () => {
  const c = mk();
  created(c, "ses-one");
  created(c, "ses-two");
  waived(c, "ses-one");
  const s = board(c, "session", "ses-one", "--session", "sess-abc");
  assert.equal(s.status, 0, s.stderr);
  assert.equal(s.ticket.stage, "queued", "a label, not a transition");
  assert.equal(s.ticket.assignment.session, "sess-abc");
  assert.equal(s.ticket.assignment.owner, null);
  const cl = claim(c, "ses-one");
  assert.equal(cl.status, 0, cl.stderr);
  assert.equal(cl.ticket.assignment.session, "sess-abc", "claim keeps the dispatched session");
  assert.equal(cl.ticket.assignment.owner, "s1");
  const rows = JSON.parse(board(c, "status", "--json").stdout);
  assert.equal(rows.find((r) => r.id === "ses-one").session, "sess-abc");
  assert.equal("session" in rows.find((r) => r.id === "ses-two"), false);
  const again = board(c, "session", "ses-one", "--session", "sess-def");
  assert.equal(again.ticket.assignment.session, "sess-def", "a working ticket can be re-pointed");
});

test("session: needs a token, and is refused on a failed ticket", () => {
  const c = mk();
  created(c, "ses-bad");
  assert.equal(board(c, "session", "ses-bad").status, 2);
  assert.equal(board(c, "session", "ses-bad", "--session", "two words").status, 2);
  assert.equal(board(c, "fail", "ses-bad", "--note", "x").status, 0);
  const r = board(c, "session", "ses-bad", "--session", "s");
  assert.equal(r.status, 1);
  assert.match(r.stderr, /session needs stage queued\|working/);
});

test("session: stays visible when the ticket reaches ready; a ticket without one still ends with assignment null", () => {
  const c = mk();
  atReady(c, "ses-ready");
  assert.equal(JSON.parse(fs.readFileSync(ticketFile(c, "ses-ready"), "utf8")).assignment, null);
  const d = mk();
  workingTicket(d, "ses-r2");
  assert.equal(board(d, "session", "ses-r2", "--session", "sess-keep").status, 0);
  const sha = landBlastFile(d);
  assert.equal(round(d, "ses-r2", { reviewed: sha }).status, 0);
  signedCritic(d, "ses-r2");
  gatesOk(d, "ses-r2");
  assert.equal(board(d, "ready", "ses-r2", "--owner", "s1").status, 0);
  const t = JSON.parse(fs.readFileSync(ticketFile(d, "ses-r2"), "utf8"));
  assert.equal(t.stage, "ready");
  assert.equal(t.assignment.session, "sess-keep");
  assert.equal(t.assignment.owner, null);
});

// ---------------------------------------------------------------- scope fence
test("scope create: a --scope entry on the hard deny list is refused", () => {
  const c = mk();
  const r = board(c, "create", "scope-deny", "--mandate", c.mandate, "--scope", ".claude/plans/foo.md");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /deny list/);
  assert.equal(fs.existsSync(ticketFile(c, "scope-deny")), false, "nothing was written");
});

test("scope create: an open-ended Mandate Scope is refused", () => {
  const c = mk();
  const mandate = path.join(c.root, "scope-open.md");
  fs.writeFileSync(mandate, `# Ticket x\n\n**Atlas refs consulted / updated?** no map\n\n**Scope:** and any doc line found\n\n**Blast radius:**\n\n- \`run()\` in \`bin/main.mjs\` — unchanged; test: bin/demo.test.mjs\n`);
  const r = board(c, "create", "scope-open", "--mandate", mandate, "--scope", "bin/**");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /board: mandate scope is open-ended: "\*\*Scope:\*\* and any doc line found"/);
  assert.equal(fs.existsSync(ticketFile(c, "scope-open")), false, "nothing was written");
});

test("scope create: an open-ended grant under a ## Scope heading, wrapped across lines, is refused whole", () => {
  const c = mk();
  const mandate = path.join(c.root, "scope-open-h.md");
  fs.writeFileSync(mandate, `# Ticket x\n\n**Atlas refs consulted / updated?** no map\n\n## Scope\nMay touch:\n- bin/a.mjs\n- README.md, and any doc\n  line found\n\n## Blast radius\n\n- \`run()\` in \`bin/main.mjs\` — unchanged; test: bin/demo.test.mjs\n`);
  const r = board(c, "create", "scope-open-h", "--mandate", mandate, "--scope", "bin/**");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /board: mandate scope is open-ended: "- README.md, and any doc line found"/);
  assert.equal(fs.existsSync(ticketFile(c, "scope-open-h")), false, "nothing was written");
});

function scopeMandate(c, name, scopeBody) {
  const mandate = path.join(c.root, `${name}.md`);
  fs.writeFileSync(mandate, `# Ticket x\n\n**Atlas refs consulted / updated?** no map\n\n${scopeBody}\n\n**Blast radius:**\n\n- \`run()\` in \`bin/main.mjs\` — unchanged; test: bin/demo.test.mjs\n`);
  return board(c, "create", name, "--mandate", mandate, "--scope", "bin/**");
}

test("scope create: an open-ended grant under a ### sub-heading of ## Scope is refused", () => {
  const c = mk();
  const r = scopeMandate(c, "scope-sub", "## Scope\n\n### May touch\n- README.md, and any doc line found");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /board: mandate scope is open-ended: "- README.md, and any doc line found"/);
});

test("scope create: an open-ended grant on a bold label inside ## Scope is refused", () => {
  const c = mk();
  const r = scopeMandate(c, "scope-bold", "## Scope\n\n**Files:** README.md, and any doc line found");
  assert.equal(r.status, 1, r.stderr);
  assert.match(r.stderr, /board: mandate scope is open-ended: "\*\*Files:\*\* README.md, and any doc line found"/);
});

test("scope create: a negated grant phrase in the Scope section is accepted", () => {
  const c = mk();
  const r = scopeMandate(c, "scope-neg", "## Scope\n\nMay touch bin/a.mjs. Never edit any file outside bin/. Do not touch any other stream's plan.");
  assert.equal(r.status, 0, r.stderr);
});

test("scope create: an open-ended grant naming backticked paths all in --scope is accepted", () => {
  const c = mk();
  const mandate = path.join(c.root, "scope-ok-bt.md");
  fs.writeFileSync(mandate, `# Ticket x\n\n**Atlas refs consulted / updated?** no map\n\n**Scope:** \`bin/a.mjs\` and \`bin/b.mjs\`, as needed.\n\n**Blast radius:**\n\n- \`run()\` in \`bin/main.mjs\` — unchanged; test: bin/demo.test.mjs\n`);
  const r = board(c, "create", "scope-ok-bt", "--mandate", mandate, "--scope", "bin/**");
  assert.equal(r.status, 0, r.stderr);
});

test("scope create: an open-ended grant naming exact paths all in --scope is accepted", () => {
  const c = mk();
  const mandate = path.join(c.root, "scope-ok.md");
  fs.writeFileSync(mandate, `# Ticket x\n\n**Atlas refs consulted / updated?** no map\n\n**Scope:** bin/a.mjs and any doc line found\n\n**Blast radius:**\n\n- \`run()\` in \`bin/main.mjs\` — unchanged; test: bin/demo.test.mjs\n`);
  const r = board(c, "create", "scope-ok", "--mandate", mandate, "--scope", "bin/**");
  assert.equal(r.status, 0, r.stderr);
});

test("scope round: an out-of-scope reviewed sha records CHANGES_REQUESTED even when the critic approved", () => {
  const c = mk();
  created(c, "sround", "--scope", "bin/demo.mjs");
  waived(c, "sround");
  claim(c, "sround");
  commitFile(c, "README.md", "out of scope\n", "touch readme");
  const sha = head(c);
  const r = round(c, "sround", { reviewed: sha, native: "sonnet", findings: "findings/approved.md", critic: null });
  assert.equal(r.status, 0, r.stderr);
  const ro = r.ticket.rounds[0];
  assert.equal(ro.counted, true, "the round still counts");
  assert.equal(ro.critic.critic_verdict, "APPROVED", "the critic did approve");
  assert.equal(ro.critic.effective, "CHANGES_REQUESTED", "scope overrode the critic");
  assert.ok(ro.critic.reasons.some((x) => x === "out of scope: README.md"), JSON.stringify(ro.critic.reasons));
});

test("scope ready: refuses a ticket whose signed-off sha leaves the scope", () => {
  const c = mk();
  created(c, "sready", "--scope", "bin/demo.mjs");
  waived(c, "sready");
  claim(c, "sready");
  commitFile(c, "README.md", "out of scope\n", "touch readme");
  const sha = head(c);
  // Fabricate a pre-fence counted round plus a critic signoff at the out-of-scope sha: this is the backstop
  // case `ready` exists for (rounds recorded before the scope check).
  editTicket(c, "sready", (t) => {
    const sha64 = "x".repeat(64);
    t.rounds.push({
      n: 1, at: new Date().toISOString(), counted: true,
      worker: { outcome: "done", agent: "worker", model: null, receipt_sha256: sha64 },
      critic: { source: "receipt", alias: "critic", model: "critic", free: false, free_source: "model:critic",
        critic_verdict: "APPROVED", effective: "APPROVED", reasons: [], findings_sha256: sha64, receipt_sha256: sha64 },
      reviewed_sha: sha, cost: 0, senior_needed: false,
    });
    t.signoffs.push({ by: "human", model: null, free: false, free_source: null, reviewed_sha: sha, at: new Date().toISOString(), invalidated_by: null });
  });
  const rd = board(c, "ready", "sready", "--owner", "s1");
  assert.equal(rd.status, 1, rd.stderr);
  assert.match(rd.stderr, /out of scope: README.md/);
});

// ---------------------------------------------------------------- scope normalisation + `scope` amend (ws-guard-followups)
test("create normalises --scope: trims, strips ./, collapses //, drops dups; empty-after-normalise is exit 2", { timeout: 30_000 }, () => {
  const c = mk();
  const r = board(c, "create", "norm-one", "--mandate", c.mandate, "--scope", "a/,./b//c/,a");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.ticket.scope, ["a", "b/c"]);
  const bad = board(c, "create", "norm-bad", "--mandate", c.mandate, "--scope", "x,/");
  assert.equal(bad.status, 2, bad.stderr);
  assert.match(bad.stderr, /empty after normalisation/);
  assert.equal(fs.existsSync(ticketFile(c, "norm-bad")), false, "a refused create writes nothing");
});

test("a normalised directory scope keeps its senior reason against a guarded glob", { timeout: 30_000 }, () => {
  const c = mk();
  const p = path.join(c.repo, ".opencode", "board", "adapter.json");
  const a = JSON.parse(fs.readFileSync(p, "utf8"));
  a.guarded_paths = ["orchestrator/ops/**"];
  fs.writeFileSync(p, JSON.stringify(a, null, 2) + "\n");
  const r = board(c, "create", "guarded-dir", "--mandate", c.mandate, "--scope", "orchestrator/ops/");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.ticket.scope, ["orchestrator/ops"]);
  assert.equal(r.ticket.senior.required, true);
  assert.deepEqual(r.ticket.senior.reasons, ["guarded path: orchestrator/ops"]);
});

test("checkScope admits a path under a stored directory scope (no fence override on round)", { timeout: 30_000 }, () => {
  const c = mk();
  const cr = board(c, "create", "dir-ok", "--mandate", c.mandate, "--scope", "orchestrator/ops");
  assert.equal(cr.status, 0, cr.stderr);
  assert.deepEqual(cr.ticket.scope, ["orchestrator/ops"]);
  waived(c, "dir-ok");
  assert.equal(claim(c, "dir-ok", "s1").status, 0);
  const sha = commitFile(c, "orchestrator/ops/x.mjs", "// under the stored dir scope\n");
  const r = round(c, "dir-ok", { reviewed: sha });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.rounds[0].critic.effective, "APPROVED", "the fence left the critic's verdict alone");
});

test("scope amends a queued ticket: new scope, senior union, history event", { timeout: 30_000 }, () => {
  const c = mk();
  const cr = board(c, "create", "amend-q", "--mandate", c.mandate, "--scope", "bin/a.mjs");
  assert.equal(cr.status, 0, cr.stderr);
  const r = board(c, "scope", "amend-q", "--scope", "bin/b.mjs,docs/c.md", "--reason", "widen a little", "--by", "rick");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.ticket.scope, ["bin/b.mjs", "docs/c.md"]);
  assert.equal(r.ticket.stage, "queued");
  const h = r.ticket.history.at(-1);
  assert.equal(h.cmd, "scope");
  assert.equal(h.from, "queued");
  assert.equal(h.to, "queued");
  assert.equal(h.by, "rick");
  assert.equal(h.note, "widen a little; scope bin/a.mjs -> bin/b.mjs,docs/c.md");
});

test("scope keeps earlier senior reasons and unions new ones", { timeout: 30_000 }, () => {
  const c = mk();
  const cr = board(c, "create", "amend-senior", "--mandate", c.mandate, "--scope", "ops/train.sh");
  assert.equal(cr.status, 0, cr.stderr);
  assert.deepEqual(cr.ticket.senior.reasons, ["guarded path: ops/train.sh"]);
  const r = board(c, "scope", "amend-senior", "--scope", "docs/x.md", "--reason", "docs only now", "--by", "rick");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.ticket.scope, ["docs/x.md"]);
  assert.deepEqual(r.ticket.senior.reasons, ["guarded path: ops/train.sh"], "old reasons are never removed");
  assert.equal(r.ticket.senior.required, true);
  const r2 = board(c, "scope", "amend-senior", "--scope", "bin/auth.mjs", "--reason", "guarded now", "--by", "rick");
  assert.equal(r2.status, 0, r2.stderr);
  assert.deepEqual(r2.ticket.senior.reasons, ["guarded path: ops/train.sh", "guarded path: bin/auth.mjs"]);
  assert.equal(r2.ticket.senior.required, true);
});

test("scope amends a working ticket and is refused on ready/blocked/failed/closed", { timeout: 30_000 }, () => {
  const c = mk();
  workingTicket(c, "amend-w");
  const r = board(c, "scope", "amend-w", "--scope", "bin/c.mjs", "--reason", "narrow it", "--by", "s1");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.ticket.stage, "working");
  assert.deepEqual(r.ticket.scope, ["bin/c.mjs"]);
  for (const stage of ["ready", "blocked", "failed", "closed", "shipped"]) {
    editTicket(c, "amend-w", (t) => { t.stage = stage; });
    const before = bytes(ticketFile(c, "amend-w"));
    const bad = board(c, "scope", "amend-w", "--scope", "bin/d.mjs", "--reason", "too late", "--by", "s1");
    assert.equal(bad.status, 1, `${stage}: ${bad.stderr}`);
    assert.match(bad.stderr, /scope needs stage queued\|working/);
    assert.ok(Buffer.compare(before, bytes(ticketFile(c, "amend-w"))) === 0, `${stage} wrote nothing`);
  }
});

test("scope refusals: deny list (exit 1), missing --reason (exit 2), EGM trigger on working (exit 1)", { timeout: 30_000 }, () => {
  const c = mk();
  const cr = board(c, "create", "scope-deny", "--mandate", c.mandate, "--scope", "bin/a.mjs");
  assert.equal(cr.status, 0, cr.stderr);
  const d = board(c, "scope", "scope-deny", "--scope", ".opencode/x", "--reason", "nope", "--by", "rick");
  assert.equal(d.status, 1, d.stderr);
  assert.match(d.stderr, /deny list/);
  const nr = board(c, "scope", "scope-deny", "--scope", "bin/b.mjs", "--by", "rick");
  assert.equal(nr.status, 2, nr.stderr);
  assert.match(nr.stderr, /--reason is required/);
  assert.deepEqual(JSON.parse(bytes(ticketFile(c, "scope-deny"))).scope, ["bin/a.mjs"], "refusals wrote nothing");
});

test("scope on a queued ticket adds an EGM trigger and re-pends; on working it refuses", { timeout: 30_000 }, () => {
  const c = mk();
  const cr = board(c, "create", "scope-egm", "--mandate", c.mandate, "--scope", "bin/a.mjs");
  assert.equal(cr.status, 0, cr.stderr);
  assert.deepEqual(cr.ticket.egm.triggers, []);
  const q = board(c, "scope", "scope-egm", "--scope", "bin/a.mjs,prisma/schema.prisma", "--reason", "data model", "--by", "rick");
  assert.equal(q.status, 0, q.stderr);
  assert.deepEqual(q.ticket.egm.triggers, ["data-model"]);
  assert.equal(q.ticket.egm.required, true);
  assert.equal(q.ticket.egm.status, "pending");

  workingTicket(c, "scope-w");
  const w = board(c, "scope", "scope-w", "--scope", "bin/a.mjs,prisma/schema.prisma", "--reason", "data model", "--by", "s1");
  assert.equal(w.status, 1, w.stderr);
  assert.match(w.stderr, /scope adds EGM trigger data-model; release the ticket and amend it while queued/);
  assert.deepEqual(JSON.parse(bytes(ticketFile(c, "scope-w"))).scope, ["bin/**"], "the refused amend wrote nothing");
});

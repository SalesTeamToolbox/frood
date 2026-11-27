import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { checkScope, matchAny } from "../bin/scope-check.mjs";

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function git(cwd, ...args) {
  const r = spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8" });
  assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
  return r.stdout.trim();
}
// Temp git repo on `main` with one base commit.
function mkRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-scope-"));
  CLEAN.push(root);
  const repo = path.join(root, "repo");
  fs.mkdirSync(repo, { recursive: true });
  git(repo, "init", "-b", "main");
  git(repo, "config", "user.email", "scope@example.test");
  git(repo, "config", "user.name", "scope test");
  git(repo, "config", "commit.gpgsign", "false");
  return { root, repo };
}
// Stage + commit `files` (rel -> content), return the new HEAD.
function commit(repo, files, msg) {
  for (const [rel, content] of Object.entries(files)) {
    const p = path.join(repo, rel);
    fs.mkdirSync(path.dirname(p), { recursive: true });
    fs.writeFileSync(p, content);
  }
  git(repo, "add", "-A");
  git(repo, "commit", "-m", msg);
  return git(repo, "rev-parse", "HEAD");
}

test("matchAny: ancestor directories match, so a root file matches a parent-dir glob", () => {
  assert.equal(matchAny("auth/login.ts", ["**/auth"]), true);
  assert.equal(matchAny("bin/demo.mjs", ["bin/**"]), true);
  assert.equal(matchAny("README.md", ["bin/**"]), false);
  assert.equal(matchAny(".claude/plans/x.md", [".claude/plans/**"]), true);
});

test("checkScope: .claude/plans/x.md is denied even when scope is **", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/a.mjs": "a\n" }, "base");
  const sha = commit(repo, { ".claude/plans/x.md": "plan\n" }, "touch a plan");
  const r = checkScope({ repo, base, sha, scope: ["**"] });
  assert.equal(r.ok, false);
  assert.deepEqual(r.denied, [".claude/plans/x.md"]);
  assert.deepEqual(r.outOfScope, []);
});

test("checkScope: README.md is out of scope for scope orchestrator/bin/**", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/a.mjs": "a\n" }, "base");
  const sha = commit(repo, { "README.md": "readme\n" }, "touch readme");
  const r = checkScope({ repo, base, sha, scope: ["orchestrator/bin/**"] });
  assert.equal(r.ok, false);
  assert.deepEqual(r.outOfScope, ["README.md"]);
  assert.deepEqual(r.denied, []);
});

test("checkScope: ok for an in-scope diff", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/a.mjs": "a\n" }, "base");
  const sha = commit(repo, { "bin/a.mjs": "a2\n", "bin/b.mjs": "b\n" }, "in scope");
  const r = checkScope({ repo, base, sha, scope: ["bin/**"] });
  assert.equal(r.ok, true);
  assert.deepEqual(r.outOfScope, []);
  assert.deepEqual(r.denied, []);
});

test("checkScope: a deleted file is checked by its old path", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/to-delete.mjs": "gone\n", "kept.md": "k\n" }, "base");
  fs.unlinkSync(path.join(repo, "bin/to-delete.mjs"));
  git(repo, "add", "-A");
  git(repo, "commit", "-m", "delete bin/to-delete.mjs");
  const after = git(repo, "rev-parse", "HEAD");
  const r = checkScope({ repo, base, sha: after, scope: ["docs/**"] });
  assert.equal(r.ok, false);
  assert.ok(r.outOfScope.includes("bin/to-delete.mjs"), `expected bin/to-delete.mjs in outOfScope, got ${JSON.stringify(r.outOfScope)}`);
});

test("checkScope: a renamed file is checked by its old and new paths", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/old.mjs": "old\n" }, "base");
  git(repo, "mv", "bin/old.mjs", "bin/new.mjs");
  git(repo, "commit", "-m", "rename bin/old.mjs to bin/new.mjs");
  const after = git(repo, "rev-parse", "HEAD");
  // Only the new path is in scope; the old path must still be flagged.
  const r = checkScope({ repo, base, sha: after, scope: ["bin/new.mjs"] });
  assert.equal(r.ok, false);
  assert.ok(r.outOfScope.includes("bin/old.mjs"), `expected bin/old.mjs in outOfScope, got ${JSON.stringify(r.outOfScope)}`);
  assert.ok(!r.outOfScope.includes("bin/new.mjs"), `bin/new.mjs is in scope, got ${JSON.stringify(r.outOfScope)}`);
});

test("checkScope: a non-ASCII deny-listed path is denied, not hidden by git's path quoting", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/a.mjs": "a\n" }, "base");
  const sha = commit(repo, { ".claude/plans/é.md": "plan\n" }, "touch a non-ASCII plan");
  const r = checkScope({ repo, base, sha, scope: ["**"] });
  assert.equal(r.ok, false);
  assert.deepEqual(r.denied, [".claude/plans/é.md"]);
});

test("checkScope: a branch rebased onto a main that advanced an unrelated file is still ok with baseRef", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/a.mjs": "a\n" }, "base");
  git(repo, "checkout", "-q", "-b", "work");
  commit(repo, { "bin/a.mjs": "a2\n" }, "in scope");
  git(repo, "checkout", "-q", "main");
  commit(repo, { "README.md": "main moved\n" }, "main advances");
  git(repo, "checkout", "-q", "work");
  git(repo, "rebase", "-q", "main");
  const sha = git(repo, "rev-parse", "HEAD");
  // Without the base ref, the stale ticket base reports main's README.md as out of scope.
  assert.deepEqual(checkScope({ repo, base, sha, scope: ["bin/**"] }).outOfScope, ["README.md"]);
  const r = checkScope({ repo, base, sha, scope: ["bin/**"], baseRef: "main" });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.deepEqual(r.outOfScope, []);
});

test("checkScope: a base ref that lags the ticket base is still checked from the ticket base", () => {
  const { repo } = mkRepo();
  commit(repo, { "bin/a.mjs": "a\n" }, "first");
  git(repo, "branch", "lag"); // the base ref stays here, behind the ticket base
  const base = commit(repo, { "README.md": "ticket base\n" }, "ticket base");
  git(repo, "checkout", "-q", "-b", "work");
  const ok = commit(repo, { "bin/a.mjs": "a2\n" }, "in scope");
  // README.md changed before the ticket base: it must not be reported.
  const r = checkScope({ repo, base, sha: ok, scope: ["bin/**"], baseRef: "lag" });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(r.from, base);
  const bad = commit(repo, { "docs/x.md": "x\n" }, "out of scope");
  const r2 = checkScope({ repo, base, sha: bad, scope: ["bin/**"], baseRef: "lag" });
  assert.deepEqual(r2.outOfScope, ["docs/x.md"]);
});

test("checkScope: an unresolvable baseRef falls back to the ticket base", () => {
  const { repo } = mkRepo();
  const base = commit(repo, { "bin/a.mjs": "a\n" }, "base");
  const sha = commit(repo, { "README.md": "r\n" }, "out of scope");
  const r = checkScope({ repo, base, sha, scope: ["bin/**"], baseRef: "no-such-ref" });
  assert.equal(r.from, base);
  assert.deepEqual(r.outOfScope, ["README.md"]);
});

// A repo whose local `main` is ahead of `origin/main`: origin is a bare repo local main was once
// pushed to, then advanced without pushing, so origin/main lags the ticket base.
function mkWithOrigin() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-scope-origin-"));
  CLEAN.push(root);
  const bare = path.join(root, "origin.git");
  fs.mkdirSync(bare, { recursive: true });
  git(bare, "init", "--bare");
  const repo = path.join(root, "repo");
  fs.mkdirSync(repo, { recursive: true });
  git(repo, "init", "-b", "main");
  git(repo, "config", "user.email", "scope@example.test");
  git(repo, "config", "user.name", "scope test");
  git(repo, "config", "commit.gpgsign", "false");
  git(repo, "remote", "add", "origin", bare);
  commit(repo, { "bin/a.mjs": "a\n" }, "c0");
  git(repo, "push", "-u", "origin", "main"); // origin/main = c0, local main advances from here
  return { root, repo, bare };
}

test("checkScope: origin/main lags but local main advanced → diffs from the local-main merge-base", () => {
  const { repo } = mkWithOrigin();
  const base = commit(repo, { "bin/a.mjs": "base\n" }, "ticket base"); // local main ahead of origin/main
  git(repo, "checkout", "-q", "-b", "work");
  commit(repo, { "bin/a.mjs": "a2\n" }, "in scope on work");
  git(repo, "checkout", "-q", "main");
  commit(repo, { "other/x.mjs": "another ticket\n" }, "another ticket on local main");
  git(repo, "checkout", "-q", "work");
  git(repo, "rebase", "-q", "main");
  const sha = git(repo, "rev-parse", "HEAD");
  const main = git(repo, "rev-parse", "main");
  const r = checkScope({ repo, base, sha, scope: ["bin/**"], baseRef: "origin/main" });
  assert.equal(r.ok, true, JSON.stringify(r));
  assert.equal(r.from, main, "from is the local-main merge-base");
  assert.deepEqual(r.outOfScope, []);
  assert.deepEqual(r.denied, []);
});

test("checkScope: rebased onto local main, out-of-scope and denied files on the branch are still caught", () => {
  const { repo } = mkWithOrigin();
  const base = commit(repo, { "bin/a.mjs": "base\n" }, "ticket base");
  git(repo, "checkout", "-q", "-b", "work");
  commit(repo, { "bin/a.mjs": "a2\n", "README.md": "out of scope\n", ".claude/plans/x.md": "plan\n" }, "work commit");
  git(repo, "checkout", "-q", "main");
  commit(repo, { "other/x.mjs": "another ticket\n" }, "another ticket on local main");
  git(repo, "checkout", "-q", "work");
  git(repo, "rebase", "-q", "main");
  const sha = git(repo, "rev-parse", "HEAD");
  const main = git(repo, "rev-parse", "main");
  const r = checkScope({ repo, base, sha, scope: ["bin/**"], baseRef: "origin/main" });
  assert.equal(r.ok, false, JSON.stringify(r));
  assert.equal(r.from, main, "from is still the local-main merge-base");
  assert.ok(r.outOfScope.includes("README.md"), JSON.stringify(r.outOfScope));
  assert.ok(r.denied.includes(".claude/plans/x.md"), JSON.stringify(r.denied));
});

test("checkScope: work merged into local main (M == sha) falls back to base", () => {
  const { repo } = mkWithOrigin();
  const base = commit(repo, { "bin/a.mjs": "base\n" }, "ticket base");
  git(repo, "checkout", "-q", "-b", "work");
  const sha = commit(repo, { "bin/a.mjs": "a2\n", "README.md": "out of scope\n" }, "work commit");
  git(repo, "checkout", "-q", "main");
  git(repo, "merge", "-q", "--ff", "work"); // local main = work head == sha
  const r = checkScope({ repo, base, sha, scope: ["bin/**"], baseRef: "origin/main" });
  assert.equal(r.from, base, "M == sha is rejected, so diff from the ticket base");
  assert.ok(r.outOfScope.includes("README.md"), JSON.stringify(r.outOfScope));
});

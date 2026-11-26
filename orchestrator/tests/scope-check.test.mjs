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

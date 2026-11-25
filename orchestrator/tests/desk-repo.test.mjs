import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { isDeskRepo } from "../bin/desk.mjs";

const REAL_ORCH = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");

function tmpRepo() {
  const root = fs.realpathSync(fs.mkdtempSync(path.join(os.tmpdir(), "desk-repo-")));
  const r = spawnSync("git", ["init", "-q", root], { encoding: "utf8", timeout: 10000 });
  assert.equal(r.status, 0, r.stderr);
  fs.mkdirSync(path.join(root, "orchestrator"));
  return root;
}

test("isDeskRepo: the git root holding the orchestrator dir is the desk's repo (Frood layout)", () => {
  const root = tmpRepo();
  try {
    assert.equal(isDeskRepo(root, path.join(root, "orchestrator")), true);
    assert.equal(isDeskRepo(root + "/", path.join(root, "orchestrator")), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("isDeskRepo: the orchestrator dir itself still matches (standalone layout)", () => {
  const root = tmpRepo();
  try {
    assert.equal(isDeskRepo(path.join(root, "orchestrator"), path.join(root, "orchestrator")), true);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test("isDeskRepo: another repo, an empty repo field, or a non-git dir is refused", () => {
  const root = tmpRepo();
  const other = tmpRepo();
  const plain = fs.mkdtempSync(path.join(os.tmpdir(), "desk-plain-"));
  fs.mkdirSync(path.join(plain, "orchestrator"));
  try {
    assert.equal(isDeskRepo(other, path.join(root, "orchestrator")), false);
    assert.equal(isDeskRepo("", path.join(root, "orchestrator")), false);
    assert.equal(isDeskRepo(undefined, path.join(root, "orchestrator")), false);
    assert.equal(isDeskRepo(plain, path.join(plain, "orchestrator")), false);
  } finally {
    for (const d of [root, other, plain]) fs.rmSync(d, { recursive: true, force: true });
  }
});

test("isDeskRepo: the real checkout's root is accepted by default", () => {
  const top = spawnSync("git", ["-C", REAL_ORCH, "rev-parse", "--show-toplevel"], { encoding: "utf8", timeout: 10000 });
  assert.equal(top.status, 0);
  assert.equal(isDeskRepo(top.stdout.trim()), true);
});

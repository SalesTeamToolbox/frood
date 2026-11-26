import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");
const FAKE = path.join(HERE, "fixtures", "fake-opencode.mjs");

import {
  allowedRoots,
  isOutside,
  scanEvents,
  findMain,
  gitStatusZ,
  parseStatusZ,
  underMain,
  appendDiff,
  restorePath,
  foldEscapes,
  finalizeEscapes,
  footer,
  editFenceConfig,
  mergeEditFence,
  hasCompletedWrite,
} from "../bin/worktree-fence.mjs";

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function tmp() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-wtf-"));
  CLEAN.push(d);
  return d;
}

// A temp git repo with one committed file. Returns { dir, file, sha }.
function gitRepo() {
  const dir = tmp();
  const git = (...args) => {
    const r = spawnSync("git", ["-C", dir, ...args], { encoding: "utf8", timeout: 10000 });
    assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
    return r.stdout.trim();
  };
  git("init", "-b", "main");
  git("config", "user.email", "wtf@example.test");
  git("config", "user.name", "wtf test");
  const file = path.join(dir, "file.txt");
  fs.writeFileSync(file, "original\n");
  git("add", "file.txt");
  git("commit", "-m", "init");
  const sha = git("rev-parse", "HEAD");
  return { dir, file, sha, git };
}

// A linked worktree of repo, plus the main checkout. Returns { main, wt, mainFile, wtFile }.
function linkedWorktree() {
  const { dir: main, file: mainFile, sha, git } = gitRepo();
  const wt = tmp();
  git("worktree", "add", "--detach", wt);
  const wtFile = path.join(wt, "file.txt");
  return { main, wt, mainFile, wtFile, sha, git };
}

// Creates a main repo outside /tmp and a linked worktree outside /tmp, so that
// writing to main from the worktree is outside the allowed roots (/tmp is allowed).
function linkedWorktreeOutsideTmp() {
  const base = fs.mkdtempSync(path.join(os.homedir(), ".wtf-test-"));
  fs.mkdirSync(base, { recursive: true });
  CLEAN.push(base);
  const main = fs.mkdtempSync(path.join(base, "main-XXXXXX"));
  CLEAN.push(main);
  const git = (...args) => {
    const r = spawnSync("git", ["-C", main, ...args], { encoding: "utf8", timeout: 10000 });
    assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
    return r.stdout.trim();
  };
  git("init", "-b", "main");
  git("config", "user.email", "wtf@example.test");
  git("config", "user.name", "wtf test");
  const mainFile = path.join(main, "file.txt");
  fs.writeFileSync(mainFile, "original\n");
  git("add", "file.txt");
  git("commit", "-m", "init");
  const wt = fs.mkdtempSync(path.join(base, "wt-XXXXXX"));
  CLEAN.push(wt);
  git("worktree", "add", "--detach", wt);
  const wtFile = path.join(wt, "file.txt");
  return { main, wt, mainFile, wtFile, git };
}

// Creates an enclosing repo <top> tracking a/b/x.txt and a/b/a/b/x.txt, plus a
// separate git dir foo.git sitting inside <top>/a/b, and a linked worktree of
// that git dir. findMain(wt) must be null because <top>/a/b is not the real
// top level (its real toplevel is <top>). Returns { top, wt, git } where git
// runs against <top>.
function separateGitDirInsideRepo() {
  const base = fs.mkdtempSync(path.join(os.homedir(), ".wtf-toplevel-test-"));
  fs.mkdirSync(base, { recursive: true });
  CLEAN.push(base);
  const top = fs.mkdtempSync(path.join(base, "top-XXXXXX"));
  CLEAN.push(top);
  const git = (...args) => {
    const r = spawnSync("git", ["-C", top, ...args], { encoding: "utf8", timeout: 10000 });
    assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
    return r.stdout.trim();
  };
  git("init", "-b", "main");
  git("config", "user.email", "wtf@example.test");
  git("config", "user.name", "wtf test");
  fs.mkdirSync(path.join(top, "a", "b", "a", "b"), { recursive: true });
  fs.writeFileSync(path.join(top, "a", "b", "x.txt"), "worker original\n");
  fs.writeFileSync(path.join(top, "a", "b", "a", "b", "x.txt"), "other original\n");
  git("add", "a/b/x.txt", "a/b/a/b/x.txt");
  git("commit", "-m", "init");

  const otherDir = fs.mkdtempSync(path.join(base, "other-XXXXXX"));
  CLEAN.push(otherDir);
  const otherGit = (...args) => {
    const r = spawnSync("git", ["-C", otherDir, ...args], { encoding: "utf8", timeout: 10000 });
    assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
    return r.stdout.trim();
  };
  otherGit("init", "-b", "main");
  otherGit("config", "user.email", "wtf@example.test");
  otherGit("config", "user.name", "wtf test");
  fs.writeFileSync(path.join(otherDir, "o.txt"), "o\n");
  otherGit("add", "o.txt");
  otherGit("commit", "-m", "init");
  const fooGit = path.join(top, "a", "b", "foo.git");
  fs.renameSync(path.join(otherDir, ".git"), fooGit);
  fs.writeFileSync(path.join(otherDir, ".git"), `gitdir: ../a/b/foo.git\n`);
  fs.rmSync(otherDir, { recursive: true, force: true });

  const wt = fs.mkdtempSync(path.join(base, "wt-XXXXXX"));
  CLEAN.push(wt);
  spawnSync("git", ["-C", fooGit, "worktree", "add", "--detach", wt], {
    encoding: "utf8", timeout: 10000, stdio: "pipe",
  });
  return { top, wt, git };
}

// ---------------------------------------------------------------- allowedRoots

test("allowedRoots: dir, out dir, tmpdir and /tmp", () => {
  const d = tmp();
  const out = path.join(d, "out", "r.md");
  const roots = allowedRoots(d, out);
  assert.ok(roots.has(path.resolve(d)), "contains D");
  assert.ok(roots.has(path.resolve(path.dirname(out))), "contains out dir");
  assert.ok(roots.has(os.tmpdir()), "contains tmpdir");
  assert.ok(roots.has("/tmp"), "contains /tmp");
});

test("isOutside: paths under roots are not outside", () => {
  const d = tmp();
  const out = path.join(d, "out", "r.md");
  const roots = allowedRoots(d, out);
  assert.equal(isOutside(path.join(d, "a.txt"), roots), false, "inside D");
  assert.equal(isOutside(path.join(path.dirname(out), "b.txt"), roots), false, "inside out dir");
  assert.equal(isOutside(path.join(os.tmpdir(), "c.txt"), roots), false, "inside tmpdir");
  assert.equal(isOutside("/tmp/d.txt", roots), false, "inside /tmp");
});

test("isOutside: paths outside roots are outside", () => {
  const d = tmp();
  const out = path.join(d, "out", "r.md");
  const roots = allowedRoots(d, out);
  assert.equal(isOutside("/etc/shadow", roots), true, "/etc is outside");
  assert.equal(isOutside(path.join(os.homedir(), "other", "x.txt"), roots), true, "/home is outside");
});

// ---------------------------------------------------------------- scanEvents

test("scanEvents: edit tool_use with filePath outside roots is escaped", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const ev = JSON.stringify({
    type: "tool_use",
    sessionID: "ses",
    part: { sessionID: "ses", messageID: "m1", type: "tool_use", name: "edit", input: { filePath: "/etc/passwd" } },
  });
  const { escaped } = scanEvents(ev + "\n", roots);
  assert.ok(escaped.has("/etc/passwd"), "path is escaped");
  assert.equal(escaped.get("/etc/passwd").length, 1, "one write event");
});

test("scanEvents: edit inside roots is not escaped", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const ev = JSON.stringify({
    type: "tool_use",
    part: { name: "edit", input: { filePath: "/tmp/wt/a.txt" } },
  });
  assert.equal(scanEvents(ev + "\n", roots).escaped.size, 0, "no escapes");
});

test("scanEvents: patch with paths array reads every path", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const ev = JSON.stringify({
    type: "tool_use",
    part: { name: "patch", input: { paths: ["/tmp/wt/a.txt", "/etc/shadow"] } },
  });
  const { escaped } = scanEvents(ev + "\n", roots);
  assert.ok(escaped.has("/etc/shadow"), "/etc/shadow escaped");
  assert.equal(escaped.size, 1, "only /etc/shadow escaped");
});

test("scanEvents: multiedit reads filePath and each edit's filePath", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const ev = JSON.stringify({
    type: "tool_use",
    part: {
      name: "multiedit",
      input: {
        filePath: "/tmp/wt/a.txt",
        edits: [{ filePath: "/etc/hosts" }, { filePath: "/tmp/wt/b.txt" }],
      },
    },
  });
  const { escaped } = scanEvents(ev + "\n", roots);
  assert.ok(escaped.has("/etc/hosts"), "/etc/hosts escaped");
  assert.equal(escaped.size, 1, "only /etc/hosts escaped");
});

test("scanEvents: generic tool with path + content outside is escaped", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const ev = JSON.stringify({
    type: "tool_use",
    part: { name: "write", input: { path: "/etc/secret.txt", content: "x" } },
  });
  const { escaped } = scanEvents(ev + "\n", roots);
  assert.ok(escaped.has("/etc/secret.txt"), "/etc/secret.txt escaped");
});

test("scanEvents: de-duplicates repeated paths", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const ev1 = JSON.stringify({ type: "tool_use", part: { name: "edit", input: { filePath: "/etc/passwd" } } });
  const ev2 = JSON.stringify({ type: "tool_use", part: { name: "write", input: { path: "/etc/passwd" } } });
  const { escaped } = scanEvents(ev1 + "\n" + ev2 + "\n", roots);
  assert.equal(escaped.size, 1, "one unique path");
  assert.ok(escaped.has("/etc/passwd"));
  assert.equal(escaped.get("/etc/passwd").length, 2, "two write events for same path");
});

test("scanEvents: ignores non-tool_use lines and malformed JSON", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const text = '{"type":"text","part":{"text":"hi"}}\nnot json\n{"type":"tool_use","part":{"name":"read","input":{}}}';
  assert.equal(scanEvents(text, roots).escaped.size, 0, "no escapes");
});

test("scanEvents: a non-completed write still records the path but not restored", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const ev = JSON.stringify({
    type: "tool_use",
    part: { type: "tool", tool: "edit", state: { status: "error", input: { path: "/etc/passwd" } } },
  });
  const { escaped } = scanEvents(ev + "\n", roots);
  assert.ok(escaped.has("/etc/passwd"), "path recorded even on error status");
  assert.equal(hasCompletedWrite(escaped.get("/etc/passwd")), false, "not completed");
});

// ---------------------------------------------------------------- findMain

test("findMain: returns null for a non-linked repo (common dir == git dir)", () => {
  const { dir } = gitRepo();
  assert.equal(findMain(dir), null, "a plain repo is not a linked worktree");
});

test("findMain: returns the main checkout for a linked worktree", () => {
  const { main, wt } = linkedWorktree();
  assert.equal(findMain(wt), main, "findMain resolves the main checkout");
});

test("findMain: returns null when git is unavailable", () => {
  assert.equal(findMain("/nonexistent-dir-xyz"), null);
});

test("findMain: returns null when the common dir's parent is not the real top level", () => {
  // enclosing repo <top> tracking a/b/x.txt and a/b/a/b/x.txt
  const base = fs.mkdtempSync(path.join(os.homedir(), ".wtf-toplevel-test-"));
  fs.mkdirSync(base, { recursive: true });
  CLEAN.push(base);
  const top = fs.mkdtempSync(path.join(base, "top-XXXXXX"));
  CLEAN.push(top);
  const git = (...args) => {
    const r = spawnSync("git", ["-C", top, ...args], { encoding: "utf8", timeout: 10000 });
    assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
    return r.stdout.trim();
  };
  git("init", "-b", "main");
  git("config", "user.email", "wtf@example.test");
  git("config", "user.name", "wtf test");
  fs.mkdirSync(path.join(top, "a", "b", "a", "b"), { recursive: true });
  fs.writeFileSync(path.join(top, "a", "b", "x.txt"), "worker original\n");
  fs.writeFileSync(path.join(top, "a", "b", "a", "b", "x.txt"), "other original\n");
  git("add", "a/b/x.txt", "a/b/a/b/x.txt");
  git("commit", "-m", "init");

  // separate git dir foo.git sitting inside <top>/a/b (like --separate-git-dir inside another repo's worktree)
  const otherDir = fs.mkdtempSync(path.join(base, "other-XXXXXX"));
  CLEAN.push(otherDir);
  const otherGit = (...args) => {
    const r = spawnSync("git", ["-C", otherDir, ...args], { encoding: "utf8", timeout: 10000 });
    assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
    return r.stdout.trim();
  };
  otherGit("init", "-b", "main");
  otherGit("config", "user.email", "wtf@example.test");
  otherGit("config", "user.name", "wtf test");
  fs.writeFileSync(path.join(otherDir, "o.txt"), "o\n");
  otherGit("add", "o.txt");
  otherGit("commit", "-m", "init");
  const fooGit = path.join(top, "a", "b", "foo.git");
  fs.renameSync(path.join(otherDir, ".git"), fooGit);
  fs.writeFileSync(path.join(otherDir, ".git"), `gitdir: ../a/b/foo.git\n`);
  fs.rmSync(otherDir, { recursive: true, force: true });

  // linked worktree of the git dir at foo.git
  const wt = fs.mkdtempSync(path.join(base, "wt-XXXXXX"));
  CLEAN.push(wt);
  spawnSync("git", ["-C", fooGit, "worktree", "add", "--detach", wt], {
    encoding: "utf8", timeout: 10000, stdio: "pipe",
  });

  // parent(commonDir) = <top>/a/b, but its real toplevel is <top> -> not the top level
  assert.equal(findMain(wt), null, "findMain fences off when main is not the real top level");
});

// ---------------------------------------------------------------- gitStatusZ / parseStatusZ

test("parseStatusZ: parses modified and added files", () => {
  const { dir, file, git } = gitRepo();
  fs.writeFileSync(file, "modified\n");
  const raw = gitStatusZ(dir);
  const m = parseStatusZ(raw);
  const rel = path.relative(dir, file);
  assert.ok(m.has(rel), `tracked modified file ${rel} present`);
});

test("parseStatusZ: handles rename records (R XY source dest)", () => {
  const { dir, git } = gitRepo();
  fs.writeFileSync(path.join(dir, "old.txt"), "old\n");
  git("add", "old.txt");
  git("commit", "-m", "add old");
  fs.renameSync(path.join(dir, "old.txt"), path.join(dir, "new.txt"));
  const raw = gitStatusZ(dir);
  const m = parseStatusZ(raw);
  // a rename produces R status with source and dest; both paths should appear
  assert.ok(m.has("old.txt") || m.has("new.txt"), "rename paths parsed");
});

// ---------------------------------------------------------------- underMain

test("underMain: path under main is true", () => {
  const { main, mainFile } = gitRepo(); // main is just a dir here
  // reuse main dir from a repo
  const { dir } = gitRepo();
  assert.equal(underMain(path.join(dir, "a.txt"), dir), true);
  assert.equal(underMain(dir, dir), true);
});

test("underMain: path outside main is false", () => {
  const a = tmp();
  const b = tmp();
  assert.equal(underMain(path.join(b, "x.txt"), a), false);
});

// ---------------------------------------------------------------- appendDiff / restorePath

test("appendDiff: appends git diff of a modified file to patch file", () => {
  const { dir, file, git } = gitRepo();
  fs.writeFileSync(file, "modified\n");
  const patch = path.join(tmp(), "escaped.patch");
  appendDiff(dir, file, patch);
  const content = fs.readFileSync(patch, "utf8");
  assert.ok(content.includes("diff --git"), "diff header present");
  assert.ok(content.includes("-original\n") || content.includes("-original"), "old content in diff");
});

test("restorePath: restores a modified file to HEAD", () => {
  const { dir, file, sha, git } = gitRepo();
  fs.writeFileSync(file, "modified\n");
  const ok = restorePath(dir, file);
  assert.equal(ok, true, "restore succeeded");
  assert.equal(fs.readFileSync(file, "utf8"), "original\n", "file content restored");
});

test("restorePath: returns false on failure, never throws", () => {
  assert.equal(restorePath("/nonexistent", "/nonexistent/x"), false);
});

// ---------------------------------------------------------------- foldEscapes

test("foldEscapes: records an escaped path outside main", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const lines = [
    JSON.stringify({ type: "tool_use", part: { name: "edit", input: { filePath: "/etc/passwd" } } }),
  ];
  foldEscapes(state, { lines, roots, dir: "/tmp/wt", main: null, beforeStatus: null, out: "/tmp/out/r.md" });
  assert.deepEqual(state.paths, ["/etc/passwd"]);
  assert.deepEqual(state.restored, []);
  assert.deepEqual(state.left, []);
});

test("foldEscapes: restores a clean escaped path inside main, lists dirty one in left", () => {
  const { dir: main, file: mainFile, git } = gitRepo();
  // make mainFile dirty before the run (already dirty -> left)
  fs.writeFileSync(mainFile, "pre-dirty\n");
  const before = parseStatusZ(gitStatusZ(main));
  // roots WITHOUT /tmp so paths under /tmp count as outside (escape)
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const cleanFile = path.join(main, "clean.txt");
  fs.writeFileSync(cleanFile, "clean content\n");
  git("add", "clean.txt");
  git("commit", "-m", "add clean");
  // now dirty it during the "run" with a completed edit whose replay matches
  fs.writeFileSync(cleanFile, "modified during run\n");
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: cleanFile, oldString: "clean content\n", newString: "modified during run\n" } },
      },
    }),
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: mainFile } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  // cleanFile was clean pre-run and replay matches -> restored
  assert.ok(state.restored.includes(cleanFile), `restored: ${JSON.stringify(state.restored)}`);
  assert.equal(fs.readFileSync(cleanFile, "utf8"), "clean content\n", "clean file restored");
  // mainFile has no oldString so replay fails (empty oldString treated as set-to-newString which is "" -> mismatch)
  assert.ok(state.left.includes(mainFile), `left: ${JSON.stringify(state.left)}`);
  assert.equal(fs.readFileSync(mainFile, "utf8"), "pre-dirty\n", "pre-dirty file left alone");
});

test("foldEscapes: de-duplicates paths across calls", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const line = JSON.stringify({ type: "tool_use", part: { name: "edit", input: { filePath: "/etc/passwd" } } });
  foldEscapes(state, { lines: [line], roots, dir: "/tmp/wt", main: null, beforeStatus: null, out: "/tmp/out/r.md" });
  foldEscapes(state, { lines: [line], roots, dir: "/tmp/wt", main: null, beforeStatus: null, out: "/tmp/out/r.md" });
  assert.deepEqual(state.paths, ["/etc/passwd"]);
});

test("foldEscapes: suspected tracks dirty main paths with no tool event", () => {
  const { dir: main, file: mainFile, git } = gitRepo();
  const before = parseStatusZ(gitStatusZ(main));
  // dirty mainFile outside any tool event
  fs.writeFileSync(mainFile, "dirty without tool\n");
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  foldEscapes(state, { lines: [], roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  const rel = path.relative(main, mainFile);
  assert.ok(state.suspected.includes(rel), `suspected: ${JSON.stringify(state.suspected)}`);
});

test("foldEscapes: does not re-report already-suspected paths", () => {
  const { dir: main, file: mainFile, git } = gitRepo();
  const before = parseStatusZ(gitStatusZ(main));
  fs.writeFileSync(mainFile, "dirty without tool\n");
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  foldEscapes(state, { lines: [], roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  const n = state.suspected.length;
  foldEscapes(state, { lines: [], roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.equal(state.suspected.length, n, "no duplicate suspected entries");
});

test("foldEscapes: null snapshot -> escaped path goes to left, diff still appended", () => {
  const { dir: main, file: mainFile, git } = gitRepo();
  // mainFile is clean pre-run ("original\n"), but beforeStatus is null (C does not apply)
  // roots WITHOUT /tmp so paths under /tmp count as outside (escape)
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  // the run's edit exactly reproduces the current file content; the null guard
  // must still short-circuit before the replay guard is reached
  fs.writeFileSync(mainFile, "modified during run\n");
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: { type: "tool", tool: "edit", state: { status: "completed", input: { path: mainFile, oldString: "original\n", newString: "modified during run\n" } } },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: null, out: path.join(main, "out", "r.md") });
  // not restored (null snapshot means we cannot know if it was clean)
  assert.ok(state.left.includes(mainFile), `left: ${JSON.stringify(state.left)}`);
  assert.equal(state.restored.length, 0, "nothing restored with null snapshot");
  assert.ok(state.notes.some((n) => n.includes("no snapshot")), "no snapshot note: " + JSON.stringify(state.notes));
  // file unchanged (not restored even though replay would match)
  assert.equal(fs.readFileSync(mainFile, "utf8"), "modified during run\n", "file unchanged");
  // diff still appended
  const patch = path.join(main, "out", "r.md.escaped.patch");
  assert.ok(fs.existsSync(patch), "escaped.patch created");
  assert.ok(fs.readFileSync(patch, "utf8").includes("diff --git"), "patch holds a diff");
});

test("foldEscapes: relative tool path resolved against dir is not an escape", () => {
  const { dir: main, file: mainFile, git } = gitRepo();
  // write an edit with a relative path that resolves inside main
  const roots = allowedRoots(main, path.join(main, "out", "r.md"));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const rel = path.relative(main, mainFile);
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: { type: "tool", tool: "edit", state: { status: "completed", input: { path: rel } } },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main: null, beforeStatus: null, out: path.join(main, "out", "r.md") });
  assert.deepEqual(state.paths, [], "relative path under dir is not escaped");
});

test("foldEscapes: symlink inside dir reaching outside is not an escape (lexical check)", () => {
  const { dir: main, git } = gitRepo();
  // create a symlink inside main pointing to /etc (outside), then an edit through it
  const link = path.join(main, ".venv");
  fs.symlinkSync("/etc", link);
  const roots = allowedRoots(main, path.join(main, "out", "r.md"));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const throughLink = path.join(main, ".venv", "passwd");
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: { type: "tool", tool: "edit", state: { status: "completed", input: { path: throughLink } } },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main: null, beforeStatus: null, out: path.join(main, "out", "r.md") });
  assert.deepEqual(state.paths, [], "symlink path lexically under dir is not escaped");
  fs.unlinkSync(link);
});

test("foldEscapes: directory path is not restored, dirty files inside stay untouched", () => {
  const { dir: main, git } = gitRepo();
  const srcDir = path.join(main, "src");
  fs.mkdirSync(srcDir, { recursive: true });
  fs.writeFileSync(path.join(srcDir, "dirty.txt"), "dirty\n");
  git("add", "src/dirty.txt");
  git("commit", "-m", "add src");

  // snapshot while src is clean
  const before = parseStatusZ(gitStatusZ(main));

  // modify a tracked file under src after the snapshot (new content, not the committed content)
  fs.writeFileSync(path.join(srcDir, "dirty.txt"), "modified by run\n");

  // roots without /tmp so src counts as outside
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: { type: "tool", tool: "write", state: { status: "completed", input: { path: srcDir, content: "x" } } },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.paths.includes(srcDir), "directory path is recorded");
  assert.ok(state.left.includes(srcDir), "directory path is in left");
  assert.ok(state.notes.some((n) => n.includes("not a single tracked regular file")), "isFile guard note: " + JSON.stringify(state.notes));
  assert.equal(state.restored.length, 0, "nothing restored");
  // the modified file under src still has its new content
  assert.equal(fs.readFileSync(path.join(srcDir, "dirty.txt"), "utf8"), "modified by run\n", "dirty file keeps its new content");
});

test("foldEscapes: repo root path is not restored", () => {
  const { dir: main, git } = gitRepo();
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: { type: "tool", tool: "write", state: { status: "completed", input: { path: main, content: "x" } } },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.left.includes(main), "repo root path is in left");
  assert.ok(state.notes.some((n) => n.includes("not a single tracked regular file")), "root guard note: " + JSON.stringify(state.notes));
  assert.equal(state.restored.length, 0, "nothing restored for root");
});

test("foldEscapes: main not the real top level -> nothing restored, other writer's content kept", () => {
  const { top, wt, git } = separateGitDirInsideRepo();
  // <top>/a/b/x.txt is escaped by this run (roots exclude <top>); <top>/a/b/a/b/x.txt
  // is modified by another writer after a clean snapshot.
  const escapedFile = path.join(top, "a", "b", "x.txt");
  const otherFile = path.join(top, "a", "b", "a", "b", "x.txt");
  const roots = new Set([path.resolve(wt), path.resolve(path.join(wt, "out"))]);
  const before = parseStatusZ(gitStatusZ(top));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  // clean snapshot for escapedFile; another writer changes otherFile after snapshot
  fs.writeFileSync(otherFile, "other writer content\n");
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: escapedFile, oldString: "worker original\n", newString: "worker edit\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: wt, main: null, beforeStatus: null, out: path.join(wt, "out", "r.md") });
  // findMain(fenced off) => main null => nothing restored
  assert.equal(state.restored.length, 0, "nothing restored when main is not the real top level");
  // other writer's content kept (nothing touched at all since main is null)
  assert.equal(fs.readFileSync(otherFile, "utf8"), "other writer content\n", "other writer's content kept");
  // escaped path recorded (record only, not left/restored since main is null)
  assert.ok(state.paths.includes(escapedFile), "escaped path recorded: " + JSON.stringify(state.paths));
  assert.ok(!state.left.includes(escapedFile), "not left when main is null");
  assert.ok(!state.restored.includes(escapedFile), "not restored when main is null");
});

test("foldEscapes: glob-looking name only touches its own file", () => {
  const { dir: main, git } = gitRepo();
  // app/i/page.txt exists and is dirty before the run (snapshot will show it dirty)
  fs.mkdirSync(path.join(main, "app", "i"), { recursive: true });
  fs.writeFileSync(path.join(main, "app", "i", "page.txt"), "original\n");
  git("add", "app/i/page.txt");
  git("commit", "-m", "add i/page");
  fs.writeFileSync(path.join(main, "app", "i", "page.txt"), "dirty before\n");

  // app/[id]/page.txt is clean and committed. Use --literal-pathspecs so `[id]`
  // is treated literally and does not also match the `app/i` neighbour.
  fs.mkdirSync(path.join(main, "app", "[id]"), { recursive: true });
  fs.writeFileSync(path.join(main, "app", "[id]", "page.txt"), "clean\n");
  git("--literal-pathspecs", "add", "app/[id]/page.txt");
  git("commit", "-m", "add [id]/page");

  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  // app/i/page.txt was dirtied above and never committed: it must still show
  // as modified at snapshot time.
  assert.ok(before.has("app/i/page.txt"), "app/i/page.txt modified at snapshot time: " + JSON.stringify([...before.keys()]));
  // now the run modifies app/[id]/page.txt
  fs.writeFileSync(path.join(main, "app", "[id]", "page.txt"), "modified by run\n");

  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const idPage = path.join(main, "app", "[id]", "page.txt");
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: idPage, oldString: "clean\n", newString: "modified by run\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.restored.includes(idPage), `[id]/page.txt restored: ${JSON.stringify(state.restored)}`);
  assert.equal(fs.readFileSync(idPage, "utf8"), "clean\n", "[id]/page.txt back to clean");
  // app/i/page.txt stays dirty, untouched
  assert.equal(fs.readFileSync(path.join(main, "app", "i", "page.txt"), "utf8"), "dirty before\n", "i/page.txt untouched");
  // the patch holds only the [id] diff, not the app/i neighbour
  const patch = fs.readFileSync(path.join(main, "out", "r.md.escaped.patch"), "utf8");
  assert.ok(patch.includes("app/[id]/page.txt"), "patch contains the [id] diff: " + patch.slice(0, 400));
  assert.ok(!patch.includes("app/i/page.txt"), "patch does not contain the app/i diff: " + patch.slice(0, 400));
});

test("foldEscapes: failed edit (status error) on clean file changed by another writer is not restored", () => {
  const { dir: main, git } = gitRepo();
  const file = path.join(main, "file.txt");
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  // another writer changed the file during the run (after the snapshot)
  fs.writeFileSync(file, "another writer's content\n");
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "error", input: { path: file, oldString: "original\n", newString: "would-be edit\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.left.includes(file), "failed edit path is in left");
  assert.equal(state.restored.length, 0, "nothing restored");
  // another writer's content is kept
  assert.equal(fs.readFileSync(file, "utf8"), "another writer's content\n", "other writer's content kept");
});

test("foldEscapes: unwritable patch path -> left with 'diff not saved', worker's edit stays", () => {
  const { dir: main, git } = gitRepo();
  const file = path.join(main, "file.txt");
  // snapshot while file is clean
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  // simulate the fake having applied the edit
  fs.writeFileSync(file, "worker's edit\n");
  // make main/out a regular file so mkdirSync for patch dir fails
  fs.writeFileSync(path.join(main, "out"), "not a directory");

  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: file, oldString: "original\n", newString: "worker's edit\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.left.includes(file), "unwritable path is in left");
  assert.ok(state.notes.some((n) => n.includes("diff not saved")), "diff not saved note: " + JSON.stringify(state.notes));
  // the worker's edit is still in the file (not restored because diff wasn't saved)
  assert.equal(fs.readFileSync(file, "utf8"), "worker's edit\n", "worker's edit still present");
});

test("foldEscapes: replay match - two completed edits on one clean file -> restored", () => {
  const { dir: main, git } = gitRepo();
  const file = path.join(main, "file.txt");
  fs.writeFileSync(file, "v1\n");
  git("add", "file.txt");
  git("commit", "-m", "v1");

  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  // now the run applies two edits: v1 -> v2 -> v3
  fs.writeFileSync(file, "v3\n"); // run's final state

  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: file, oldString: "v1\n", newString: "v2\n" } },
      },
    }),
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: file, oldString: "v2\n", newString: "v3\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.restored.includes(file), "replay match -> restored: " + JSON.stringify(state.restored));
  assert.equal(fs.readFileSync(file, "utf8"), "v1\n", "file back to index content");
});

test("foldEscapes: replay mismatch - completed edit then another writer appends -> not restored", () => {
  const { dir: main, git } = gitRepo();
  const file = path.join(main, "file.txt");
  fs.writeFileSync(file, "v1\n");
  git("add", "file.txt");
  git("commit", "-m", "v1");

  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  // Another writer changes the file after the snapshot
  fs.writeFileSync(file, "v1\nappended by another writer\n");

  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: file, oldString: "v1\n", newString: "v2\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.left.includes(file), "replay mismatch -> left");
  assert.ok(state.notes.some((n) => n.includes("replay mismatch")), "replay mismatch note: " + JSON.stringify(state.notes));
  // file is NOT restored - another writer's content kept
  assert.equal(fs.readFileSync(file, "utf8"), "v1\nappended by another writer\n", "other writer's content kept");
});

test("foldEscapes: binary file diff uses --binary", () => {
  const { dir: main, git } = gitRepo();
  // create a binary file
  const binFile = path.join(main, "binary.bin");
  const original = Buffer.from([0, 1, 2, 3, 255, 254, 253]);
  fs.writeFileSync(binFile, original);
  git("add", "binary.bin");
  git("commit", "-m", "add binary");

  // modify the binary file
  const modified = Buffer.from([0, 1, 2, 3, 255, 254]);
  fs.writeFileSync(binFile, modified);

  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "write",
        state: { status: "completed", input: { path: binFile, content: "\x00\x01\x02\x03\xff\xfe" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  const patch = path.join(main, "out", "r.md.escaped.patch");
  assert.ok(fs.existsSync(patch), "escaped.patch created");
  const content = fs.readFileSync(patch, "utf8");
  assert.ok(content.includes("GIT binary patch"), "patch contains GIT binary patch marker: " + content.slice(0, 200));
  // replay cannot match a JS-string write against raw bytes -> left
  assert.ok(state.left.includes(binFile), "binary path is in left: " + JSON.stringify(state.left));
  // file bytes unchanged (not restored)
  assert.deepEqual(fs.readFileSync(binFile), modified, "binary file bytes unchanged");
});

test("foldEscapes: latin-1 file with another writer -> left, bytes kept, raw patch holds 0xE8", () => {
  const { dir: main, git } = gitRepo();
  const latinFile = path.join(main, "cafe.txt");
  // tracked file is caf\xE9\nline2\n, clean in the snapshot
  fs.writeFileSync(latinFile, Buffer.from("caf\xE9\nline2\n", "latin1"));
  git("add", "cafe.txt");
  git("commit", "-m", "add cafe");

  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  // worker completes an edit of line2 -> WORKER
  fs.writeFileSync(latinFile, Buffer.from("caf\xE9\nWORKER\n", "latin1"));
  // another writer changes \xE9 to \xE8 after the snapshot
  fs.writeFileSync(latinFile, Buffer.from("caf\xE8\nWORKER\n", "latin1"));
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: latinFile, oldString: "line2\n", newString: "WORKER\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  // path goes to left with not valid UTF-8
  assert.ok(state.left.includes(latinFile), "latin-1 path in left: " + JSON.stringify(state.left));
  assert.ok(state.notes.some((n) => n.includes("not valid UTF-8")), "not valid UTF-8 note: " + JSON.stringify(state.notes));
  assert.equal(state.restored.length, 0, "nothing restored");
  // the 0xE8 byte kept in the file (not restored)
  const fileBuf = fs.readFileSync(latinFile);
  assert.ok(fileBuf.includes(0xE8), "0xE8 byte kept in file");
  assert.ok(!fileBuf.includes(0xE9), "original 0xE9 byte replaced by worker/other writer");
  // raw 0xE8 byte present in the patch file
  const patch = fs.readFileSync(path.join(main, "out", "r.md.escaped.patch"));
  assert.ok(patch.includes(0xE8), "patch holds raw 0xE8 byte");
});

test("foldEscapes: latin-1 file, no other writer -> still left with not valid UTF-8, patch holds real bytes", () => {
  const { dir: main, git } = gitRepo();
  const latinFile = path.join(main, "cafe.txt");
  fs.writeFileSync(latinFile, Buffer.from("caf\xE9\nline2\n", "latin1"));
  git("add", "cafe.txt");
  git("commit", "-m", "add cafe");

  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  // worker edit completes, content diverges from index, no other writer
  fs.writeFileSync(latinFile, Buffer.from("caf\xE9\nWORKER\n", "latin1"));
  const lines = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: latinFile, oldString: "line2\n", newString: "WORKER\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines, roots, dir: main, main, beforeStatus: before, out: path.join(main, "out", "r.md") });
  assert.ok(state.left.includes(latinFile), "latin-1 path in left: " + JSON.stringify(state.left));
  assert.ok(state.notes.some((n) => n.includes("not valid UTF-8")), "not valid UTF-8 note: " + JSON.stringify(state.notes));
  assert.equal(state.restored.length, 0, "nothing restored");
  // file unchanged (worker's content kept)
  const fileBuf = fs.readFileSync(latinFile);
  assert.ok(fileBuf.includes(0xE9), "0xE9 byte kept in file");
  const patch = fs.readFileSync(path.join(main, "out", "r.md.escaped.patch"));
  assert.ok(patch.includes(0xE9), "patch holds real 0xE9 byte");
});

test("foldEscapes: restored path written again in a later attempt -> left", () => {
  const { dir: main, git } = gitRepo();
  const file = path.join(main, "file.txt");
  const roots = new Set([path.resolve("/tmp/wt"), path.resolve("/tmp/out")]);
  const before = parseStatusZ(gitStatusZ(main));
  const out = path.join(main, "out", "r.md");

  const state = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };

  // Attempt 1: completed edit on clean file -> restored
  fs.writeFileSync(file, "modified\n");
  const lines1 = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "edit",
        state: { status: "completed", input: { path: file, oldString: "original\n", newString: "modified\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines: lines1, roots, dir: main, main, beforeStatus: before, out });
  assert.ok(state.restored.includes(file), "restored after attempt 1: " + JSON.stringify(state.restored));
  assert.equal(fs.readFileSync(file, "utf8"), "original\n", "file back to index content");

  // Attempt 2: another completed write to the same path, but content diverges
  fs.writeFileSync(file, "something else entirely\n");
  const lines2 = [
    JSON.stringify({
      type: "tool_use",
      part: {
        type: "tool",
        tool: "write",
        state: { status: "completed", input: { path: file, content: "completely different\n" } },
      },
    }),
  ];
  foldEscapes(state, { lines: lines2, roots, dir: main, main, beforeStatus: before, out });
  assert.ok(state.left.includes(file), "left after attempt 2: " + JSON.stringify(state.left));
  assert.equal(state.restored.length, 0, "no longer restored");
  assert.ok(state.notes.some((n) => n.includes("written again in a later attempt")), "re-process note: " + JSON.stringify(state.notes));
  // file content kept (not re-restored)
  assert.equal(fs.readFileSync(file, "utf8"), "something else entirely\n", "file content kept");
});

test("scanEvents: null JSON line does not throw", () => {
  const roots = allowedRoots("/tmp/wt", "/tmp/out/r.md");
  const text = "null\n{\"type\":\"tool_use\",\"part\":null}\n{\"type\":\"tool_use\",\"part\":{\"type\":\"tool\",\"tool\":\"edit\",\"state\":{\"status\":\"completed\",\"input\":{\"path\":\"/etc/passwd\"}}}}\n";
  const { escaped } = scanEvents(text, roots);
  assert.ok(escaped.has("/etc/passwd"), "null lines don't break scanning");
});

// ---------------------------------------------------------------- finalizeEscapes

test("finalizeEscapes: returns null escaped when nothing found", () => {
  const { escaped, note } = finalizeEscapes({ paths: [], restored: [], left: [], suspected: [] });
  assert.equal(escaped, null);
  assert.equal(note, "");
});

test("finalizeEscapes: builds escaped receipt with all fields", () => {
  const { escaped } = finalizeEscapes({
    paths: ["/etc/passwd"],
    restored: ["/main/clean.txt"],
    left: ["/main/dirty.txt"],
    suspected: ["/main/suspected.txt"],
  });
  assert.ok(escaped);
  assert.deepEqual(escaped.paths, ["/etc/passwd"]);
  assert.deepEqual(escaped.restored, ["/main/clean.txt"]);
  assert.deepEqual(escaped.left, ["/main/dirty.txt"]);
  assert.deepEqual(escaped.suspected, ["/main/suspected.txt"]);
});

test("finalizeEscapes: omitted optional fields when empty", () => {
  const { escaped } = finalizeEscapes({ paths: ["/etc/passwd"], restored: [], left: [], suspected: [] });
  assert.equal(escaped.restored, undefined);
  assert.equal(escaped.left, undefined);
  assert.equal(escaped.suspected, undefined);
});

test("scanEvents: all 8 real escaped edits from fence-real-edits.jsonl are flagged", () => {
  const FIX = path.join(HERE, "fixtures", "fence-real-edits.jsonl");
  const events = fs.readFileSync(FIX, "utf8");

  // Create a temp main checkout and a temp linked worktree (both outside /tmp so
  // they are not trivially covered by the tmpdir root).
  const base = fs.mkdtempSync(path.join(os.homedir(), ".wtf-real-edit-"));
  fs.mkdirSync(base, { recursive: true });
  CLEAN.push(base);
  const main = fs.mkdtempSync(base + "/main-XXXXXX");
  CLEAN.push(main);
  const wt = fs.mkdtempSync(base + "/wt-XXXXXX");
  CLEAN.push(wt);
  const git = (...args) => {
    const r = spawnSync("git", ["-C", main, ...args], { encoding: "utf8", timeout: 10000 });
    assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
    return r.stdout.trim();
  };
  git("init", "-b", "main");
  git("config", "user.email", "t@t");
  git("config", "user.name", "t");
  fs.writeFileSync(path.join(main, "README.md"), "main\n");
  git("add", "README.md");
  git("commit", "-m", "init");
  git("worktree", "add", "--detach", wt);

  // Substitute tokens: __MAIN__ -> main, __WT__ -> wt
  const mapped = events.replaceAll("__MAIN__", main).replaceAll("__WT__", wt);
  const roots = allowedRoots(wt, path.join(wt, "out", "r.md"));
  const { escaped } = scanEvents(mapped, roots, wt);

  // The fixture has 8 edit events targeting 3 unique files under __MAIN__.
  const editLines = events.split("\n").filter((l) => l.trim() && JSON.parse(l).part?.tool === "edit");
  assert.equal(editLines.length, 8, "fixture has 8 edit events");

  // All 3 unique paths under __MAIN__ (main checkout), not under __WT__ (worktree).
  assert.equal(escaped.size, 3, `expected 3 unique escapes, got ${escaped.size}`);
  for (const p of escaped.keys()) assert.ok(p.startsWith(main), `escaped path under main: ${p}`);
});

// ---------------------------------------------------------------- footer

test("footer: contains worktree paragraph with D and report dir", () => {
  const d = path.join(os.homedir(), "wt");
  const out = path.join(os.homedir(), "runs", "out", "r.md");
  const f = footer(d, out, null);
  assert.ok(f.includes(d), "mentions D");
  assert.ok(f.includes(path.join(os.homedir(), "runs", "out")), "mentions report dir");
  assert.ok(!f.includes("/main/"), "no main when not linked");
});

test("footer: includes main when a linked worktree was found", () => {
  const d = path.join(os.homedir(), "wt");
  const out = path.join(os.homedir(), "runs", "out", "r.md");
  const main = path.join(os.homedir(), "frood");
  const f = footer(d, out, main);
  assert.ok(f.includes(main), "mentions main");
  assert.ok(f.includes(path.join(os.homedir(), "frood", "orchestrator") + "/…"), "example path mentions main");
});

test("allowedRoots: includes --report directory when given", () => {
  const d = path.join(os.homedir(), "wt");
  const out = path.join(os.homedir(), "runs", "out", "r.md");
  const report = path.join(os.homedir(), "reports", "r1.md");
  const reportDir = path.dirname(report);
  const roots = allowedRoots(d, out, reportDir);
  assert.ok(roots.has(path.resolve(d)), "contains D");
  assert.ok(roots.has(path.resolve(path.dirname(out))), "contains out dir");
  assert.ok(roots.has(path.resolve(reportDir)), "contains report dir");
  assert.ok(roots.has(os.tmpdir()), "contains tmpdir");
});

// ---------------------------------------------------------------- editFenceConfig / mergeEditFence

test("editFenceConfig: denies * and allows D, out dir, tmp", () => {
  const d = path.join(os.homedir(), "wt");
  const out = path.join(os.homedir(), "runs", "out", "r.md");
  const cfg = JSON.parse(editFenceConfig(d, out));
  assert.equal(cfg.permission.edit["*"], "deny");
  assert.ok(cfg.permission.edit[`${d}/**`]);
  assert.ok(cfg.permission.edit[`${path.dirname(out)}/**`]);
  assert.ok(cfg.permission.edit[`${os.tmpdir()}/**`]);
});

test("mergeEditFence: merges into existing config", () => {
  const d = path.join(os.homedir(), "wt");
  const out = path.join(os.homedir(), "runs", "out", "r.md");
  const existing = JSON.stringify({ permission: { edit: { "/existing/**": "allow" } }, other: 1 });
  const merged = JSON.parse(mergeEditFence(existing, d, out));
  assert.equal(merged.other, 1, "existing fields preserved");
  assert.equal(merged.permission.edit["/existing/**"], "allow", "existing edit rule preserved");
  assert.equal(merged.permission.edit["*"], "deny", "fence deny added");
  assert.ok(merged.permission.edit[`${d}/**`], "fence allow added");
});

test("mergeEditFence: empty existing yields just the fence", () => {
  const d = path.join(os.homedir(), "wt");
  const out = path.join(os.homedir(), "runs", "out", "r.md");
  const merged = JSON.parse(mergeEditFence("", d, out));
  assert.equal(merged.permission.edit["*"], "deny");
  assert.ok(merged.permission.edit[`${d}/**`], "D allow");
  assert.ok(merged.permission.edit[`${path.dirname(out)}/**`], "out dir allow");
  assert.ok(merged.permission.edit[`${os.tmpdir()}/**`], "tmp allow");
  assert.equal(Object.keys(merged).length, 1, "only permission key at top level");
});

test("mergeEditFence: invalid existing is treated as empty", () => {
  const d = path.join(os.homedir(), "wt");
  const out = path.join(os.homedir(), "runs", "out", "r.md");
  const merged = JSON.parse(mergeEditFence("{not json", d, out));
  assert.equal(merged.permission.edit["*"], "deny");
});

// ---------------------------------------------------------------- end-to-end via oc-worker

function ocRun(envExtra, ...flags) {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", out, ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, ...envExtra },
    encoding: "utf8",
    timeout: 30000,
  });
  return { ...r, dir, out, argsFile };
}

test("e2e: escape-edit restores the file, writes escaped.patch, non-zero exit, escaped-worktree error", () => {
  const { main, wt, mainFile, git } = linkedWorktreeOutsideTmp();
  const out = path.join(wt, "out", "worker-r1.md");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const prompt = path.join(wt, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", wt, "--prompt", prompt, "--out", out], {
    env: {
      ...process.env,
      OPENCODE_BIN: FAKE,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: wt,
      FAKE_OC_MODE: "escape-edit",
      FAKE_OC_TARGET: mainFile,
    },
    encoding: "utf8",
    timeout: 30000,
  });
  // file restored to original
  assert.equal(fs.readFileSync(mainFile, "utf8"), "original\n", "escaped file restored");
  // escaped.patch exists and holds a diff
  const patch = out + ".escaped.patch";
  assert.ok(fs.existsSync(patch), "escaped.patch created");
  assert.ok(fs.readFileSync(patch, "utf8").includes("diff --git"), "patch holds a diff");
  // receipt has escaped.paths
  const rec = JSON.parse(r.stdout.trim());
  assert.ok(rec.escaped, "receipt has escaped field: " + r.stdout);
  assert.ok(rec.escaped.paths.includes(mainFile), "escaped.paths lists the file");
  assert.ok(rec.escaped.restored.includes(mainFile), "restored lists the file");
  // exit non-zero
  assert.notEqual(r.status, 0, "exit non-zero on escape");
  // errors has escaped-worktree
  assert.ok(rec.errors.some((e) => e.startsWith("escaped-worktree:")), "errors has escaped-worktree: " + JSON.stringify(rec.errors));
});

test("e2e: main goes dirty with no tool event of ours -> suspected warning only, not restored, exit and errors unchanged", () => {
  const { wt, mainFile } = linkedWorktreeOutsideTmp();
  const out = path.join(wt, "out", "worker-r1.md");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const prompt = path.join(wt, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", wt, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: wt, FAKE_OC_MODE: "dirty-main", FAKE_OC_TARGET: mainFile },
    encoding: "utf8",
    timeout: 30000,
  });
  const rec = JSON.parse(r.stdout.trim());
  assert.equal(fs.readFileSync(mainFile, "utf8"), "someone else's edit\n", "a suspected path is never reverted");
  assert.deepEqual(rec.escaped.paths, [], "no exact escape");
  assert.ok(rec.escaped.suspected.length >= 1, "suspected lists the dirty main path: " + JSON.stringify(rec.escaped));
  assert.ok(!rec.errors.some((e) => e.startsWith("escaped-worktree:")), "no errors entry: " + JSON.stringify(rec.errors));
  assert.notEqual(rec.exit, "escaped-worktree");
  assert.equal(r.status, 0, r.stderr);
});

test("e2e: already-dirty escaped file is left alone and listed in left", () => {
  const { main, wt, mainFile, git } = linkedWorktreeOutsideTmp();
  // pre-dirty the file
  fs.writeFileSync(mainFile, "pre-dirty\n");
  const out = path.join(wt, "out", "worker-r1.md");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const prompt = path.join(wt, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", wt, "--prompt", prompt, "--out", out], {
    env: {
      ...process.env,
      OPENCODE_BIN: FAKE,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: wt,
      FAKE_OC_MODE: "escape-edit",
      FAKE_OC_TARGET: mainFile,
    },
    encoding: "utf8",
    timeout: 30000,
  });
  // file left as the fake wrote it (not restored to HEAD)
  assert.notEqual(fs.readFileSync(mainFile, "utf8"), "original\n", "pre-dirty file not restored to HEAD");
  const rec = JSON.parse(r.stdout.trim());
  assert.ok(rec.escaped.left.includes(mainFile), "left lists the file: " + JSON.stringify(rec.escaped));
  assert.equal(rec.escaped.restored, undefined, "not restored");
});

test("e2e: edit inside worktree produces no escaped key, exit unchanged", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const target = path.join(dir, "inside.txt");
  fs.writeFileSync(target, "original\n");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: {
      ...process.env,
      OPENCODE_BIN: FAKE,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: dir,
      FAKE_OC_MODE: "edit-worktree",
      FAKE_OC_TARGET: target,
    },
    encoding: "utf8",
    timeout: 30000,
  });
  const rec = JSON.parse(r.stdout.trim());
  assert.equal(rec.escaped, undefined, "no escaped key for in-worktree edit");
  assert.equal(r.status, 0, "exit unchanged (0)");
});

test("e2e: symlink inside worktree pointing outside is not an escape", () => {
  const { main, wt, mainFile, git } = linkedWorktree();
  // a symlink inside wt that points outside (like .venv)
  const link = path.join(wt, ".venv");
  fs.symlinkSync(main, link);
  const out = path.join(wt, "out", "worker-r1.md");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const prompt = path.join(wt, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", wt, "--prompt", prompt, "--out", out], {
    env: {
      ...process.env,
      OPENCODE_BIN: FAKE,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: wt,
      FAKE_OC_MODE: "ok",
    },
    encoding: "utf8",
    timeout: 30000,
  });
  const rec = JSON.parse(r.stdout.trim());
  assert.equal(rec.escaped, undefined, "symlink inside worktree is not an escape");
});

test("e2e: --stream run-done outcome is not done when escape detected", () => {
  const { main, wt, mainFile } = linkedWorktreeOutsideTmp();

  // Set up a stream home with the m6a stream
  const streamHome = tmp();
  CLEAN.push(streamHome);
  const streamsDir = path.join(streamHome, ".config", "orchestrator", "streams");
  fs.mkdirSync(streamsDir, { recursive: true });
  fs.writeFileSync(path.join(streamsDir, "m6a.json"), JSON.stringify({ name: "m6a", status: "active" }));

  // --out must be fresh, with ticket.json beside it
  const runDir = path.join(wt, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a" }));
  const out = path.join(runDir, "worker-r1.md");

  const prompt = path.join(wt, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");

  const eventsFile = path.join(streamsDir, "m6a.events.jsonl");

  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", wt, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: {
      ...process.env,
      OPENCODE_BIN: FAKE,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: streamHome,
      FAKE_OC_MODE: "escape-edit",
      FAKE_OC_TARGET: mainFile,
    },
    encoding: "utf8",
    timeout: 30000,
  });

  // Process exit non-zero
  assert.notEqual(r.status, 0, "process exit non-zero on escape");

  // Receipt exit !== 0
  const rec = JSON.parse(r.stdout.trim());
  assert.notEqual(rec.exit, 0, "receipt exit non-zero on escape");
  assert.ok(rec.escaped, "receipt has escaped field");

  // Run-done event outcome !== "done"
  const events = fs.readFileSync(eventsFile, "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  const done = events.find((e) => e.kind === "run-done");
  assert.ok(done, "run-done event present");
  assert.notEqual(done.outcome, "done", "run-done outcome not done");
});

test("e2e: footer contains worktree paragraph", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
    timeout: 30000,
  });
  const { argv } = JSON.parse(fs.readFileSync(argsFile, "utf8"));
  const message = argv.at(-1);
  assert.ok(message.includes("Your worktree is"), "footer has worktree paragraph");
  assert.ok(message.includes("Create and edit files only under it"), "footer names allowed roots");
});

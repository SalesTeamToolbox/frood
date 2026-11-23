import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
import { once } from "node:events";
import { fileURLToPath } from "node:url";
import { cwdOf, listProcesses, killHolder, mcpTarget, finish, exitCode } from "../bin/wt-finish.mjs";

// Every fixture is a throwaway repo under os.tmpdir(). The only processes ever killed are the children this file
// spawns and hands to the CLI; nothing here touches a real worktree, a real worktree's files or any other process.
const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.resolve(HERE, "..", "bin", "wt-finish.mjs");
const IS_WIN = process.platform === "win32";
const norm = (p) => (IS_WIN ? path.resolve(p).toLowerCase() : path.resolve(p));
const MARKER = "fake_mcp_marker";

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

function git(cwd, ...args) {
  const r = spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8", windowsHide: true });
  return { code: r.status, out: String(r.stdout || ""), err: String(r.stderr || "") };
}

function must(r, what) {
  assert.equal(r.code, 0, `${what} failed: ${r.err || r.out}`);
  return r;
}

// A temp repo with one commit on `main` and the worktree <root>/wt on branch t/x. `node_modules/` and `.claude/`
// are ignored, as they are in a real worktree, so links and nested verify worktrees leave the tree clean.
function fixture() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-wtf-"));
  const repo = path.join(root, "repo");
  const wt = path.join(root, "wt");
  fs.mkdirSync(repo);
  must(git(repo, "init", "-q", "-b", "main"), "git init");
  must(git(repo, "config", "user.email", "wt-finish@example.test"), "git config email");
  must(git(repo, "config", "user.name", "wt finish"), "git config name");
  must(git(repo, "config", "commit.gpgsign", "false"), "git config gpgsign");
  fs.writeFileSync(path.join(repo, ".gitignore"), "node_modules\n.claude/\n");
  fs.writeFileSync(path.join(repo, "a.txt"), "a\n");
  must(git(repo, "add", ".gitignore", "a.txt"), "git add");
  must(git(repo, "commit", "-q", "-m", "one"), "git commit");
  must(git(repo, "worktree", "add", "-q", "-b", "t/x", wt, "main"), "git worktree add");
  return { root, repo, wt };
}

// A tiny script outside the worktree, so a holder can carry a marker in its script path (mcpTarget looks at the
// program and its script argument only, never at later argv).
function script(root, name) {
  const p = path.join(root, name);
  fs.writeFileSync(p, "setInterval(()=>{},1000);\n");
  return p;
}

function cleanup(...roots) {
  for (const root of roots) {
    // `fs.rmSync` is not trusted with a junction (that is the whole point of this file's link handling), so any
    // link the test itself left behind is unlinked by hand first.
    for (const rel of linksUnder(root)) removeLink(path.join(root, rel));
    try {
      fs.rmSync(root, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 });
    } catch {}
  }
}

// Test-side mirror of the CLI's walk: relative paths of links, never descending into one.
function linksUnder(dir, rel = "", out = []) {
  let entries = [];
  try {
    entries = fs.readdirSync(path.join(dir, rel), { withFileTypes: true });
  } catch {
    return out;
  }
  for (const e of entries) {
    const r = rel ? `${rel}/${e.name}` : e.name;
    const p = path.join(dir, r);
    let st;
    try {
      st = fs.lstatSync(p);
    } catch {
      continue;
    }
    if (st.isSymbolicLink()) out.push(r);
    else if (st.isDirectory()) linksUnder(dir, r, out);
  }
  return out;
}

function removeLink(p) {
  try {
    fs.unlinkSync(p);
  } catch {
    try {
      fs.rmdirSync(p);
    } catch {}
  }
}

function linkTo(target, link) {
  fs.symlinkSync(target, link, IS_WIN ? "junction" : "dir");
}

const children = [];
// A live process whose cwd is `cwd`; `args` are node's own (a script path for a marker holder).
async function holder(cwd, ...args) {
  const child = spawn(process.execPath, args, { cwd, stdio: "ignore", windowsHide: true });
  children.push(child);
  await once(child, "spawn");
  return child;
}

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
}

async function waitFor(fn, ms, what) {
  const until = Date.now() + ms;
  for (;;) {
    if (await fn()) return;
    assert.ok(Date.now() < until, `timed out waiting for ${what}`);
    await sleep(200);
  }
}

function run(args, env = {}) {
  return spawnSync(process.execPath, [BIN, ...args], {
    encoding: "utf8",
    windowsHide: true,
    timeout: 180_000,
    env: { ...process.env, ...env },
  });
}

function kill(...ps) {
  for (const child of ps) {
    try {
      child?.kill();
    } catch {}
  }
}

// ------------------------------------------------------------------ cwd of a process

test("listProcesses/cwdOf report a child's cwd", { timeout: 120_000 }, async () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-wtf-cwd-"));
  const child = await holder(dir, "-e", "setInterval(()=>{},1000)");
  try {
    let seen = null;
    await waitFor(() => {
      seen = listProcesses().find((p) => p.pid === child.pid);
      return Boolean(seen?.cwd);
    }, 30_000, `cwd of pid ${child.pid}`);
    assert.equal(norm(seen.cwd), norm(dir));
    assert.equal(norm(cwdOf(child.pid)), norm(dir));
  } finally {
    kill(child);
    await once(child, "exit").catch(() => {});
    cleanup(dir);
  }
});

// ------------------------------------------------------------------ the happy path

test("a merged, clean worktree with one MCP-like holder is removed and the holder killed", { timeout: 180_000 }, async () => {
  const { root, repo, wt } = fixture();
  try {
    assert.ok(!git(wt, "status", "--porcelain").out.trim(), "fixture starts clean");
    const child = await holder(wt, script(root, `${MARKER}.js`));
    const r = run([wt, "--base", "main"], { ORCH_WT_MCP_PATTERNS: MARKER });
    assert.equal(r.status, 0, `stdout=${r.stdout} stderr=${r.stderr}`);
    assert.match(r.stdout, /^OK .* killed=1$/m);
    assert.equal(fs.existsSync(wt), false, "worktree directory is gone");
    assert.doesNotMatch(git(repo, "worktree", "list", "--porcelain").out, /[\\/]wt(\r?\n|$)/);
    await waitFor(() => !alive(child.pid), 10_000, `pid ${child.pid} to die`);
    assert.match(git(repo, "branch", "--list", "t/x").out, /t\/x/, "the branch stays without --delete-branch");
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

test("a holder that is not an MCP server makes it FAIL busy: nothing killed, nothing removed", { timeout: 180_000 }, async () => {
  const { root, repo, wt } = fixture();
  try {
    const child = await holder(wt, script(root, "plain-holder.js"));
    const r = run([wt, "--base", "main"], { ORCH_WT_MCP_PATTERNS: MARKER });
    assert.equal(r.status, 4, `stdout=${r.stdout}`);
    const line = r.stdout.split(/\r?\n/).find((l) => l.startsWith("FAIL busy "));
    assert.ok(line, `no FAIL busy line in ${JSON.stringify(r.stdout)}`);
    assert.match(line, new RegExp(`^FAIL busy ${child.pid} \\S`), "the line names the child");
    assert.ok(alive(child.pid), "the busy holder was not killed");
    assert.equal(fs.existsSync(wt), true, "the worktree is still there");
    assert.match(git(repo, "worktree", "list", "--porcelain").out, /[\\/]wt(\r?\n|$)/, "still registered");
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

test("an MCP name only in a trailing argument is not an MCP server: FAIL busy, holder alive", { timeout: 180_000 }, async () => {
  const { root, wt } = fixture();
  try {
    // The shape of `opencode run ... <Mandate>`: the marker travels as free text after the script argument.
    const child = await holder(wt, script(root, "worker-like.js"), MARKER, "and mcp_server.py and opencode-peer-mail");
    const r = run([wt, "--base", "main"]);
    assert.equal(r.status, 4, `stdout=${r.stdout}`);
    const line = r.stdout.split(/\r?\n/).find((l) => l.startsWith("FAIL busy "));
    assert.ok(line, `no FAIL busy line in ${JSON.stringify(r.stdout)}`);
    assert.match(line, new RegExp(`^FAIL busy ${child.pid} \\S`));
    assert.ok(alive(child.pid), "a worker whose Mandate names an MCP server must not be killed");
    assert.equal(fs.existsSync(wt), true, "nothing removed");
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

test("--dry-run reports would-kill, kills nothing and keeps the worktree", { timeout: 180_000 }, async () => {
  const { root, wt } = fixture();
  try {
    const child = await holder(wt, script(root, `${MARKER}.js`));
    const r = run([wt, "--dry-run", "--base", "main"], { ORCH_WT_MCP_PATTERNS: MARKER });
    assert.equal(r.status, 0, `stdout=${r.stdout}`);
    assert.match(r.stdout, new RegExp(`^DRY .*${path.basename(wt)}$`, "m"));
    assert.match(r.stdout, new RegExp(`^would-kill ${child.pid} `, "m"));
    assert.ok(alive(child.pid), "dry run kills nothing");
    assert.equal(fs.existsSync(wt), true, "dry run removes nothing");
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

test("--dry-run still recognises the two real MCP server command shapes (default patterns)", { timeout: 180_000 }, async () => {
  const { root, wt } = fixture();
  // The Python MCP server runs as `<python> <...>/mcp_server.py serve`; peer-mail as
  // `<node> <...>/opencode-peer-mail/dist/index.js`. Script contents are JS here (the program is irrelevant to the
  // match), but the script paths and argv shape are the real ones.
  const py = path.join(root, "mcp-like", "mcp_server.py");
  const js = path.join(root, "opencode-peer-mail", "dist", "index.js");
  for (const p of [py, js]) fs.mkdirSync(path.dirname(p), { recursive: true });
  for (const p of [py, js]) fs.writeFileSync(p, "setInterval(()=>{},1000);\n");
  try {
    const a = await holder(wt, py, "serve");
    const b = await holder(wt, js);
    const r = run([wt, "--dry-run", "--base", "main"]);
    assert.equal(r.status, 0, `stdout=${r.stdout}`);
    for (const child of [a, b]) assert.match(r.stdout, new RegExp(`^would-kill ${child.pid} \\S`, "m"), r.stdout);
    assert.ok(alive(a.pid) && alive(b.pid), "dry run kills nothing");
    assert.equal(fs.existsSync(wt), true, "dry run removes nothing");
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

// ------------------------------------------------------------------ refusals

test("dirty, unmerged and main-worktree cases fail with their own exit codes", { timeout: 120_000 }, () => {
  const { root, repo, wt } = fixture();
  try {
    fs.writeFileSync(path.join(wt, "scratch.txt"), "x\n");
    let r = run([wt, "--base", "main"]);
    assert.equal(r.status, 3, r.stdout);
    assert.match(r.stdout, /FAIL dirty/);
    fs.rmSync(path.join(wt, "scratch.txt"));

    fs.writeFileSync(path.join(wt, "b.txt"), "b\n");
    must(git(wt, "add", "b.txt"), "add b");
    must(git(wt, "commit", "-q", "-m", "unmerged"), "commit b");
    r = run([wt, "--base", "main"]);
    assert.equal(r.status, 3, r.stdout);
    assert.match(r.stdout, /FAIL not-merged/);

    r = run([repo]);
    assert.equal(r.status, 2, r.stdout);
    assert.match(r.stdout, /FAIL not-a-worktree/);

    r = run([]);
    assert.equal(r.status, 2, r.stdout);
    assert.match(r.stdout, /FAIL usage/);
  } finally {
    cleanup(root);
  }
});

test("a sibling directory whose name extends the worktree's is not a holder", { timeout: 180_000 }, async () => {
  const { root, wt } = fixture();
  const sibling = path.join(root, "wt2");
  fs.mkdirSync(sibling);
  try {
    const child = await holder(sibling, script(root, `${MARKER}.js`));
    const r = run([wt, "--base", "main"], { ORCH_WT_MCP_PATTERNS: MARKER });
    assert.equal(r.status, 0, `stdout=${r.stdout}`);
    assert.match(r.stdout, /killed=0/);
    assert.equal(fs.existsSync(wt), false, "the real worktree is removed");
    assert.ok(alive(child.pid), "the wt2 process is not the wt holder");
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

test("a registered worktree nested under the target is refused", { timeout: 180_000 }, () => {
  const { root, repo, wt } = fixture();
  const nested = path.join(wt, ".claude", "worktrees", "nested-wt");
  try {
    must(git(repo, "worktree", "add", "-q", "-b", "t/nested", nested, "main"), "nested worktree add");
    const r = run([wt, "--base", "main"]);
    assert.equal(r.status, 5, r.stdout);
    assert.match(r.stdout, new RegExp(`^FAIL nested .*nested-wt$`, "m"));
    assert.equal(fs.existsSync(wt), true, "nothing removed");
    assert.match(git(repo, "worktree", "list", "--porcelain").out, /nested-wt/, "the nested worktree still registered");
  } finally {
    cleanup(root);
  }
});

// ------------------------------------------------------------------ links

test("a node_modules junction is unlinked before removal and its target survives", { timeout: 180_000 }, () => {
  const { root, wt } = fixture();
  const target = path.join(root, "shared-install");
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, "keep.txt"), "keep\n");
  try {
    linkTo(target, path.join(wt, "node_modules"));
    const r = run([wt, "--base", "main"]);
    assert.equal(r.status, 0, `stdout=${r.stdout}`);
    assert.equal(fs.existsSync(wt), false, "worktree removed");
    assert.equal(fs.readFileSync(path.join(target, "keep.txt"), "utf8"), "keep\n", "the link target was not followed");
  } finally {
    cleanup(root);
  }
});

test("a nested junction's target survives the removal (the verify-worktree incident)", { timeout: 180_000 }, () => {
  const { root, wt } = fixture();
  const target = path.join(root, "shared-install");
  const nested = path.join(wt, ".claude", "worktrees", "verify-abc123", "node_modules");
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, "keep.txt"), "keep\n");
  try {
    fs.mkdirSync(path.dirname(nested), { recursive: true });
    linkTo(target, nested);
    assert.ok(!git(wt, "status", "--porcelain").out.trim(), "ignored links keep the worktree clean");
    const r = run([wt, "--base", "main"]);
    assert.equal(r.status, 0, `stdout=${r.stdout}`);
    assert.equal(fs.existsSync(wt), false, "worktree removed");
    assert.equal(fs.readFileSync(path.join(target, "keep.txt"), "utf8"), "keep\n", "the nested link target was not followed");
  } finally {
    cleanup(root);
  }
});

test("a link that could not be unlinked stops the run with FAIL links and no git removal", { timeout: 180_000 }, async () => {
  const { root, repo, wt } = fixture();
  const target = path.join(root, "shared-install");
  fs.mkdirSync(target);
  fs.writeFileSync(path.join(target, "keep.txt"), "keep\n");
  try {
    linkTo(target, path.join(wt, "node_modules"));
    const r = await finish([wt, "--base", "main"], process.env, { unlink: () => false });
    assert.equal(r.check, "links", JSON.stringify(r));
    assert.equal(exitCode(r), 5);
    assert.match(r.lines[0], new RegExp(`^FAIL links .*node_modules$`));
    assert.equal(fs.existsSync(wt), true, "no removal was attempted");
    assert.match(git(repo, "worktree", "list", "--porcelain").out, /[\\/]wt(\r?\n|$)/, "still registered");
  } finally {
    cleanup(root);
  }
});

test("a listing without this process's cwd fails closed with FAIL scan: no unlink, no removal", { timeout: 180_000 }, async () => {
  const { root, repo, wt } = fixture();
  const target = path.join(root, "shared-install");
  fs.mkdirSync(target);
  try {
    linkTo(target, path.join(wt, "node_modules"));
    const r = await finish([wt, "--base", "main"], process.env, { list: () => [] });
    assert.equal(r.check, "scan", JSON.stringify(r));
    assert.equal(exitCode(r), 5);
    assert.match(r.lines[0], /^FAIL scan /);
    assert.equal(fs.existsSync(path.join(wt, "node_modules")), true, "the link was not unlinked");
    assert.match(git(repo, "worktree", "list", "--porcelain").out, /[\\/]wt(\r?\n|$)/, "still registered");
  } finally {
    cleanup(root);
  }
});

// ------------------------------------------------------------------ options

test("--delete-branch deletes the merged branch; --json prints one object", { timeout: 180_000 }, async () => {
  const { root, repo, wt } = fixture();
  try {
    const child = await holder(wt, script(root, `${MARKER}.js`));
    const r = run([wt, "--base", "main", "--delete-branch", "--json"], { ORCH_WT_MCP_PATTERNS: MARKER });
    assert.equal(r.status, 0, `stdout=${r.stdout}`);
    const lines = r.stdout.trim().split(/\r?\n/);
    assert.equal(lines.length, 1, "one JSON line and nothing else");
    const obj = JSON.parse(lines[0]);
    assert.deepEqual(Object.keys(obj).sort(), ["busy", "check", "killed", "ok", "worktree"]);
    assert.equal(obj.ok, true);
    assert.equal(obj.check, "ok");
    assert.equal(norm(obj.worktree), norm(wt));
    assert.equal(obj.killed.length, 1);
    assert.equal(obj.killed[0].pid, child.pid);
    assert.equal(typeof obj.killed[0].cmd, "string");
    assert.deepEqual(obj.busy, []);
    assert.equal(git(repo, "branch", "--list", "t/x").out.trim(), "", "the branch is gone");
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

test("--json keeps the busy shape and exit code", { timeout: 180_000 }, async () => {
  const { root, wt } = fixture();
  try {
    const child = await holder(wt, script(root, "plain-holder.js"));
    const r = run([wt, "--base", "main", "--json"], { ORCH_WT_MCP_PATTERNS: MARKER });
    assert.equal(r.status, 4, `stdout=${r.stdout}`);
    const obj = JSON.parse(r.stdout.trim());
    assert.equal(obj.ok, false);
    assert.equal(obj.check, "busy");
    assert.equal(obj.busy.length, 1);
    assert.equal(obj.busy[0].pid, child.pid);
    assert.deepEqual(obj.killed, []);
  } finally {
    kill(...children.splice(0));
    cleanup(root);
  }
});

// ------------------------------------------------------------------ guards

test("killHolder skips when the start time differs or is missing, kills only on an exact match", () => {
  const calls = [];
  const kill = (pid) => (calls.push(pid), true);
  assert.equal(killHolder({ pid: 4242, start: "2026-01-01T00:00:00.000Z" }, { start: () => "2026-02-02T00:00:00.000Z", kill }), false);
  assert.equal(killHolder({ pid: 4242, start: "2026-01-01T00:00:00.000Z" }, { start: () => null, kill }), false);
  assert.equal(killHolder({ pid: 4242, start: null }, { start: () => "2026-01-01T00:00:00.000Z", kill }), false);
  assert.deepEqual(calls, []);
  assert.equal(killHolder({ pid: 4242, start: "2026-01-01T00:00:00.000Z" }, { start: () => "2026-01-01T00:00:00.000Z", kill }), true);
  assert.deepEqual(calls, [4242]);
});

test("mcpTarget decides on the program and its script argument only", () => {
  assert.match(mcpTarget("node C:/x/opencode-peer-mail/dist/index.js"), /opencode-peer-mail/);
  assert.match(mcpTarget('"C:\\tools\\python.exe" C:\\tools\\mcp\\mcp_server.py serve'), /mcp_server\.py/);
  assert.match(mcpTarget("python -u /srv/mcp/mcp_server.py serve"), /mcp_server\.py/);
  // A worker's Mandate travels after the script argument and must never make it an MCP server.
  assert.doesNotMatch(mcpTarget('opencode.exe run --format json "Implement mcp_server.py and opencode-peer-mail"'), /mcp_server|peer-mail/);
  assert.doesNotMatch(mcpTarget("node C:/tmp/plain.js fake_mcp_marker"), /fake_mcp_marker/);
  assert.equal(mcpTarget(""), "");
});

test("--base starting with a dash is rejected as usage", { timeout: 60_000 }, () => {
  const r = run(["somewhere", "--base", "-x"]);
  assert.equal(r.status, 2, r.stdout);
  assert.match(r.stdout, /FAIL usage/);
});

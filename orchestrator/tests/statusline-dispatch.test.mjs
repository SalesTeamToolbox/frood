// Statusline dispatch segment: the --line text from dispatch.mjs appears on line 2 of the
// cross-harness bar only when a board is active, is absent without a board, and a segment throw
// is swallowed so it can never break the bar.
//
// The hook is CommonJS; it imports dispatch.mjs (ESM) dynamically in-process. Tests drive the
// exported helpers and spawn the hook against a throwaway HOME/ORCH_HOME - never the real machine.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HOOK = path.join(HERE, "..", "hooks", "cross-harness-statusline.js");
const require = createRequire(import.meta.url);
const hook = require(HOOK);
const { renderLines, dispatchSegmentLine } = hook.__test;

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function tmpDir(prefix) {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}

// Throwaway HOME: dashboard.off so no detached rebuild spawns; peer-mail pieces present so
// collectFast doesn't blow up (they're unrelated to dispatch but exercised by the spawn).
function home() {
  const h = tmpDir("orch-dispatch-home-");
  CLEAN.push(h);
  fs.mkdirSync(path.join(h, ".local", "share", "opencode-peer-mail"), { recursive: true });
  fs.mkdirSync(path.join(h, ".local", "share", "opencode"), { recursive: true });
  fs.mkdirSync(path.join(h, ".claude", "projects"), { recursive: true });
  fs.mkdirSync(path.join(h, ".config", "orchestrator"), { recursive: true });
  fs.writeFileSync(path.join(h, ".config", "orchestrator", "dashboard.off"), "");
  fs.writeFileSync(path.join(h, "peer-dist.mjs"), "export function listPeerSessions() { return []; }\n");
  fs.writeFileSync(path.join(h, ".claude", "harness-config.json"), JSON.stringify({ peerMailDist: path.join(h, "peer-dist.mjs") }));
  return h;
}

// A board repo with one active ticket (working, session sess-1).
function mkBoard() {
  const repo = tmpDir("orch-dispatch-board-");
  CLEAN.push(repo);
  assert.equal(spawnSync("git", ["-C", repo, "init", "-q", "-b", "main"]).status, 0);
  fs.mkdirSync(path.join(repo, ".opencode", "board", "tickets"), { recursive: true });
  fs.writeFileSync(path.join(repo, ".opencode", "board", "adapter.json"), JSON.stringify({ base: "main", gates: [["true"]] }));
  fs.writeFileSync(
    path.join(repo, ".opencode", "board", "tickets", "t-one.json"),
    JSON.stringify({
      schema: 1, id: "t-one", stage: "working", mandate_path: path.join(repo, "t-one.md"),
      scope: ["src/a.mjs"], blast_radius: [],
      assignment: { owner: "s1", session: "sess-1", worker: null },
      worktree: "/tmp/wt-one",
    }),
  );
  fs.writeFileSync(path.join(repo, "t-one.md"), "# t-one\n");
  return repo;
}

// Register a live oc-worker run attached to t-one (by session) in the isolated runs dir.
function registerRun(oh, over = {}) {
  const dir = path.join(oh, ".config", "orchestrator", "runs");
  fs.mkdirSync(dir, { recursive: true });
  const started = Date.now() - 60_000;
  fs.writeFileSync(path.join(dir, `${process.pid}-${started}.json`), JSON.stringify({
    pid: process.pid, agent: "worker-nvidia", model: "nvidia/nemotron", title: "t-one run",
    dir: "/tmp/wt-one", out: "/tmp/out.md", started, idleMin: 5, timeoutMin: 60,
    session: "sess-1", stream: null, heartbeat: new Date().toISOString(), ...over,
  }));
}

const PAYLOAD = (cwd) => JSON.stringify({ session_id: "s1", workspace: { current_dir: cwd }, cwd });

function spawnHook(stdin, env) {
  return spawnSync(process.execPath, [HOOK], {
    env, encoding: "utf8", input: stdin, timeout: 60_000, windowsHide: true,
  });
}

test("statusline: no board in cwd → no dispatch segment on line 2", () => {
  const h = home();
  const r = spawnHook(PAYLOAD("/tmp"), { ...process.env, HOME: h });
  assert.equal(r.status, 0, r.stderr);
  const lines = r.stdout.split(/\r?\n/).filter(Boolean);
  assert.ok(lines.length >= 2, "bar has two lines");
  assert.ok(!lines[1].includes("⇉"), `unexpected dispatch segment without a board: ${lines[1]}`);
});

test("statusline: board with an active run shows the dispatch segment on line 2", () => {
  const h = home();
  const oh = tmpDir("orch-dispatch-orch-");
  CLEAN.push(oh);
  fs.mkdirSync(path.join(oh, ".config", "orchestrator", "runs"), { recursive: true });
  fs.mkdirSync(path.join(oh, ".config", "orchestrator", "streams"), { recursive: true });
  const repo = mkBoard();
  registerRun(oh);
  const env = { ...process.env, HOME: h, ORCH_HOME: oh };
  const r = spawnHook(PAYLOAD(repo), env);
  assert.equal(r.status, 0, r.stderr);
  const lines = r.stdout.split(/\r?\n/).filter(Boolean);
  assert.ok(lines.length >= 2, "bar has two lines");
  assert.ok(lines[1].includes("⇉"), `missing dispatch segment: ${lines[1]}`);
  assert.ok(lines[1].includes("t-one"), `missing ticket id: ${lines[1]}`);
});

test("statusline: renderLines places the dispatch segment on line 2", () => {
  const out = renderLines(
    { cwd: "/tmp", workspace: { current_dir: "/tmp" } },
    { oc: null, unread: 0, remotes: [], trains: [], active: { runs: [], oc: [], cc: [] } },
    "⇉ 1 building · t-one nvidia 2m",
  );
  const lines = out.split("\n");
  assert.equal(lines.length, 2);
  assert.ok(lines[1].includes("⇉ 1 building · t-one nvidia 2m"), `segment not on line 2: ${lines[1]}`);
});

test("statusline: a segment throw is swallowed - bar still renders", async () => {
  const repo = mkBoard();
  // A throwing statusData replacement: dispatchSegmentLine must return "" instead of throwing.
  const line = await dispatchSegmentLine(repo, () => { throw new Error("segment boom"); });
  assert.equal(line, "", "throwing segment must be swallowed");
  // renderLines still produces a two-line bar with no dispatch content.
  const out = renderLines(
    { cwd: repo, workspace: { current_dir: repo } },
    { oc: null, unread: 0, remotes: [], trains: [], active: { runs: [], oc: [], cc: [] } },
    line,
  );
  const lines = out.split("\n");
  assert.equal(lines.length, 2);
  assert.ok(!lines[1].includes("⇉"), `swallowed segment leaked into the bar: ${lines[1]}`);
});

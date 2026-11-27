// cc-pacing-v2-a3b: the desk treats a cc-critic run (headless Claude Code) as a critic run, and any cc-* receipt as paid.
// Every dispatch test here fails if desk.mjs reverts to `agent.startsWith("critic")`; every free-ness test fails if
// a cc-* receipt with no resolvable model is counted as free again. Temp ORCH_HOME only; every child has a timeout.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { driveOnce, handleEvent } from "../bin/desk.mjs";
import { appendAck, appendEvent, orchRoot, readEvents } from "../bin/handoff.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "desk.mjs");
const REAL_HOME = os.homedir();
const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

const tmp = (prefix) => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  CLEAN.push(d);
  return d;
};
const sdir = (h) => path.join(h, ".config", "orchestrator", "streams");
const at = () => new Date().toISOString();

async function inHome(h, fn) {
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    if (path.resolve(orchRoot()) === path.resolve(REAL_HOME)) throw new Error("orchRoot resolved to the real home — refusing");
    return await fn();
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
}
async function withEnv(vars, fn) {
  const saved = Object.fromEntries(Object.keys(vars).map((k) => [k, process.env[k]]));
  Object.assign(process.env, vars);
  try {
    return await fn();
  } finally {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  }
}

function gitRepo() {
  const dir = tmp("orch-ccc-git-");
  const g = (...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8", timeout: 20000 }).trim();
  g("init", "-q", "-b", "main");
  g("config", "user.email", "t@example.invalid");
  g("config", "user.name", "t");
  fs.writeFileSync(path.join(dir, "a.txt"), "a\n");
  g("add", "a.txt");
  g("commit", "-q", "-m", "base");
  return { dir, head: g("rev-parse", "HEAD") };
}

// A home with one active stream and one ticket. worktree: a git repo (live verdicts) or a placeholder (dry runs).
function setup(name, { git = false } = {}) {
  const h = tmp("orch-ccc-");
  fs.mkdirSync(sdir(h), { recursive: true });
  fs.writeFileSync(
    path.join(sdir(h), `${name}.json`),
    JSON.stringify({ name, repo: "", plan: "", status: "active", next: "n", done: "", waiting: "", written_at: at(), written_by: "", consumed_at: null, done_at: null }),
  );
  const runDir = path.join(h, "reports", "t1");
  fs.mkdirSync(runDir, { recursive: true });
  let worktree = path.join(h, "wt", "t1");
  if (git) worktree = gitRepo().dir;
  else {
    fs.mkdirSync(worktree, { recursive: true });
    fs.writeFileSync(path.join(worktree, ".git"), "gitdir: placeholder\n");
  }
  const t = { ticket: "t1", worktree, branch: "feat/t1", base: "HEAD", mandate: path.join(runDir, "mandate.md"), report: path.join(runDir, "report.md"), max_rounds: 3, senior_trigger: null, repo: "", merge: "ff" };
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify(t));
  fs.writeFileSync(t.mandate, "mandate\n");
  fs.writeFileSync(t.report, "report\n");
  return { h, name, runDir, ticket: path.join(runDir, "ticket.json") };
}
const evQ = (run, out, ticket, agent) => ({ key: `run:${run}:queued`, kind: "queued", run, out, agent, ticket, pid: 1, pid_start: null, at: at() });
const evDone = (run, out, agent) => ({ key: `run:${run}:done`, kind: "run-done", run, out, agent, exit: 0, outcome: "done", session: "ses_1", at: at() });
const APPROVED = "VERDICT: APPROVED\nTESTS: npm test -> 10 pass\nBLAST RADIUS:\n- bin/x.mjs:1 - unchanged\nSENIOR_REVIEW: not-needed - small\n";
const DRY = { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" };

// A finished critic run of `agent` (findings written with a VERDICT line).
async function criticDone(s, agent, run = "critic-r1") {
  const findings = path.join(s.runDir, `${run}.md`);
  fs.writeFileSync(findings, APPROVED);
  await inHome(s.h, () => {
    appendEvent(s.name, evQ(run, findings, s.ticket, agent));
    appendEvent(s.name, evDone(run, findings, agent));
  });
  return findings;
}

// ---- pass bar 1: run-done dispatch ----

test("a cc-critic run-done reaches verdictFlow, not ESCALATE agent-cc-critic", async () => {
  const s = setup("ccc-dispatch");
  await criticDone(s, "cc-critic");
  const r = await withEnv(DRY, () => inHome(s.h, () => handleEvent(s.name, "run:critic-r1:done", undefined)));
  assert.equal(r.outcome, "verdict", JSON.stringify(r));
  assert.equal(r.line, "verdict critic-r1");
  assert.ok(!String(r.line).includes("agent-cc-critic"));
});

test("a plain critic run-done still reaches verdictFlow", async () => {
  const s = setup("critic-dispatch");
  await criticDone(s, "critic");
  const r = await withEnv(DRY, () => inHome(s.h, () => handleEvent(s.name, "run:critic-r1:done", undefined)));
  assert.equal(r.outcome, "verdict", JSON.stringify(r));
  assert.equal(r.line, "verdict critic-r1");
});

test("a cc-worker run-done is unchanged: stepped to ACTION critic, never verdicted", async () => {
  const s = setup("ccw-dispatch");
  const out = path.join(s.runDir, "worker-r1.md");
  fs.writeFileSync(out, "RESULT: DONE\n");
  await inHome(s.h, () => {
    appendEvent(s.name, evQ("worker-r1", out, s.ticket, "cc-worker"));
    appendEvent(s.name, evDone("worker-r1", out, "cc-worker"));
  });
  const r = await withEnv(DRY, () => inHome(s.h, () => handleEvent(s.name, "run:worker-r1:done", undefined)));
  assert.equal(r.outcome, "critic", JSON.stringify(r));
  assert.match(r.line, /^critic r1/);
});

// ---- pass bar 2: the round scan (sweepVerdicts) ----

test("the round scan verdicts an unverdicted cc-critic run-done", async () => {
  const s = setup("ccc-sweep", { git: true });
  await criticDone(s, "cc-critic");
  // Ack the run-done so poll() does not hand it to handleEvent: only the sweep can verdict it now.
  await inHome(s.h, () => appendAck(s.name, "run:critic-r1:done", "test: sweep only", { resolved: true, ticket: "t1" }));
  await withEnv({ ORCH_NO_NOTIFY: "1" }, () => inHome(s.h, () => driveOnce({ lastPoll: null, printed: new Set() }, {})));
  const events = await inHome(s.h, () => readEvents(s.name));
  const v = events.find((e) => e.key === "verdict:critic-r1");
  assert.ok(v, `sweep wrote no verdict: ${JSON.stringify(events.map((e) => e.key))}`);
  assert.equal(v.effective, "APPROVED");
});

// ---- pass bar 4: desk free-ness from the critic's receipt ----

const cli = (h, args) => spawnSync(process.execPath, [BIN, ...args], { env: { ...process.env, ORCH_HOME: h }, encoding: "utf8", timeout: 60000 });

async function verdictWithReceipt(label, receipt) {
  const s = setup(`free-${label}`, { git: true });
  const findings = await criticDone(s, receipt.agent);
  fs.writeFileSync(`${findings}.receipt.json`, JSON.stringify(receipt));
  const r = cli(s.h, ["verdict", s.name, "critic-r1", "--findings", findings]);
  assert.equal(r.status, 0, r.stderr);
  const events = await inHome(s.h, () => readEvents(s.name));
  return events.find((e) => e.key === "verdict:critic-r1");
}

for (const [label, model] of [["empty", ""], ["agent-default", "(agent default)"], ["opus", "opus"]]) {
  test(`desk free-ness: a cc-critic receipt with model ${JSON.stringify(model)} is paid (APPROVED, not APPROVED_FREE)`, async () => {
    const v = await verdictWithReceipt(label, { agent: "cc-critic", model });
    assert.equal(v.effective, "APPROVED");
  });
}

test("desk free-ness: a *-free OpenCode critic is still free; an unknown agent with no model is still free", async () => {
  assert.equal((await verdictWithReceipt("oc-free", { agent: "critic-free", model: "" })).effective, "APPROVED_FREE");
  assert.equal((await verdictWithReceipt("oc-unknown", { agent: "critic-nopin", model: "(agent default)" })).effective, "APPROVED_FREE");
});

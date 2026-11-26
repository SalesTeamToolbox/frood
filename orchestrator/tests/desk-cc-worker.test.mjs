// cc-pacing-m4b: the desk treats a cc-worker run (headless Claude Code) as a worker run.
// Every test here fails if desk.mjs isWorkerAgent() reverts to `agent.startsWith("worker")`.
// Fixtures copy the step-test pattern of desk.test.mjs: a temp ORCH_HOME, a stream, ticket.json, events, `desk step`.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { appendEvent, appendAck, orchRoot } from "../bin/handoff.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "desk.mjs");
const OC_WORKER = fileURLToPath(new URL("../bin/oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
const REAL_HOME = os.homedir();
const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

const fwd = (p) => p.replace(/\\/g, "/");
const sdir = (h) => path.join(h, ".config", "orchestrator", "streams");

function inHome(h, fn) {
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    if (path.resolve(orchRoot()) === path.resolve(REAL_HOME)) throw new Error("orchRoot resolved to the real home — refusing");
    return fn();
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
}

function t8Stream(name) {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-desk-cc-"));
  CLEAN.push(h);
  fs.mkdirSync(sdir(h), { recursive: true });
  fs.writeFileSync(
    path.join(sdir(h), `${name}.json`),
    JSON.stringify({ name, repo: "", plan: "", status: "active", next: "", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: null, done_at: null }),
  );
  const runDir = path.join(h, "reports", "t8");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, ".git"), "gitdir: placeholder\n");
  const t = {
    ticket: "t8",
    worktree: runDir,
    branch: "feat/t8",
    base: "HEAD",
    mandate: path.join(runDir, "mandate.md"),
    report: path.join(runDir, "report.md"),
    max_rounds: 3,
    senior_trigger: null,
    repo: "",
    merge: "ff",
  };
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify(t));
  return { h, name, runDir };
}

const evQueued = (run, runDir, agent, over = {}) => ({
  key: `run:${run}:queued`,
  kind: "queued",
  run,
  out: path.join(runDir, `${run}.md`),
  pid: 1,
  pid_start: null,
  agent,
  ticket: path.join(runDir, "ticket.json"),
  ...over,
});
const evDone = (run, runDir, over = {}) => ({
  key: `run:${run}:done`,
  kind: "run-done",
  run,
  out: path.join(runDir, `${run}.md`),
  agent: "worker",
  exit: 0,
  outcome: "done",
  session: "ses_1",
  ...over,
});
const evVerdict = (run, runDir, over = {}) => ({
  key: `verdict:${run}`,
  kind: "verdict",
  run,
  effective: "APPROVED",
  senior: false,
  findings: path.join(runDir, "findings-r1.md"),
  reviewed_sha: "abc",
  ...over,
});
const step = (h, name, key) => {
  const r = spawnSync(process.execPath, [BIN, "step", name, key], { cwd: h, env: { ...process.env, ORCH_HOME: h, WORKER_SLOTS: "3" }, encoding: "utf8", timeout: 60000 });
  return r.stdout.split("\n").filter(Boolean)[0];
};

// A finished worker run of `agent` on a fresh stream; returns the step line for its run-done.
function runDone(name, agent, over = {}) {
  const s = t8Stream(name);
  inHome(s.h, () => {
    appendEvent(s.name, evQueued("worker-r1", s.runDir, agent));
    appendEvent(s.name, evDone("worker-r1", s.runDir, { agent, ...over }));
  });
  return { ...s, line: step(s.h, s.name, "run:worker-r1:done") };
}

test("cc-worker run-done gets the same ACTION critic a worker-nvidia run-done gets", () => {
  const nv = runDone("nv-done", "worker-nvidia");
  const cc = runDone("cc-done", "cc-worker", { session: "ses_claude" });
  const expected = (s) =>
    `ACTION critic ${fwd(path.join(s.runDir, "ticket.json"))} ${fwd(path.join(s.runDir, "worker-r1.md"))} ${fwd(path.join(s.runDir, "findings-r1.md"))} 1`;
  assert.equal(nv.line, expected(nv));
  assert.equal(cc.line, expected(cc), "cc-worker is a worker: critic, not ESCALATE agent-cc-worker");
  assert.ok(!cc.line.includes("agent-cc-worker"));
});

test("CHANGES_REQUESTED keyed on a cc-worker run resumes --agent cc-worker --session <its session>", () => {
  const { h, name, runDir } = t8Stream("cc-changes");
  inHome(h, () => {
    appendEvent(name, evQueued("worker-r1", runDir, "cc-worker"));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "cc-worker", session: "ses_claude" }));
    appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  assert.equal(
    step(h, name, "verdict:worker-r1"),
    `ACTION resume-worker node ${OC_WORKER} --agent cc-worker --dir ${fwd(runDir)} --prompt ${fwd(path.join(runDir, "findings-r1.md"))} ` +
      `--report ${fwd(path.join(runDir, "report.md"))} --out ${fwd(path.join(runDir, "worker-r2.md"))} --session ses_claude --stream ${name}`,
  );
});

test("CHANGES_REQUESTED keyed on the critic run links back to the cc-worker run via the ACTION critic ack", () => {
  const { h, name, runDir } = t8Stream("cc-link");
  inHome(h, () => {
    appendEvent(name, evQueued("worker-r1", runDir, "cc-worker"));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "cc-worker", session: "ses_claude" }));
  });
  // The step on the run-done records ACTION critic: the linkage criticReviewedRun follows.
  assert.match(step(h, name, "run:worker-r1:done"), /^ACTION critic .*findings-r1\.md 1$/);
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\n");
  inHome(h, () => {
    appendEvent(name, evQueued("t8c/findings-r1", runDir, "critic", { out: findings }));
    appendEvent(name, evDone("t8c/findings-r1", runDir, { out: findings, agent: "critic", session: "ses_c" }));
    appendEvent(name, evVerdict("t8c/findings-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  assert.equal(
    step(h, name, "verdict:t8c/findings-r1"),
    `ACTION resume-worker node ${OC_WORKER} --agent cc-worker --dir ${fwd(runDir)} --prompt ${fwd(findings)} ` +
      `--report ${fwd(path.join(runDir, "report.md"))} --out ${fwd(path.join(runDir, "worker-r2.md"))} --session ses_claude --stream ${name}`,
  );
});

test("a timed-out cc-worker run escalates with its outcome (only worker-nvidia/worker-free auto-resume)", () => {
  const t = runDone("cc-timeout", "cc-worker", { outcome: "timeout", exit: "timeout", session: "ses_claude" });
  assert.equal(t.line, `ESCALATE worker-timeout ${fwd(path.join(t.runDir, "worker-r1.md"))}`, "a worker-* escalation, not agent-cc-worker");
  const d = runDone("cc-error", "cc-worker", { outcome: "error", exit: 1, session: "ses_claude" });
  assert.equal(d.line, `ESCALATE worker-error ${fwd(path.join(d.runDir, "worker-r1.md"))}`);
});

test("critic agents are still not workers: their run-done escalates agent-<critic>", () => {
  for (const agent of ["critic", "critic-go", "critic-nvidia", "critic-free"]) {
    const c = runDone(`not-worker-${agent}`, agent);
    assert.equal(c.line, `ESCALATE agent-${agent} ${fwd(path.join(c.runDir, "worker-r1.md"))}`, agent);
  }
  // the contrast that pins the helper: the same run as cc-worker is a worker
  assert.match(runDone("contrast-cc", "cc-worker").line, /^ACTION critic /);
});

test("a verdict keyed on a critic whose ACTION link names a critic run is not resumed as a worker", () => {
  // Only the ACTION line links; a linked run that is itself a critic must not be resumed.
  const { h, name, runDir } = t8Stream("critic-linked");
  const findings = path.join(runDir, "findings-r1.md");
  inHome(h, () => {
    appendEvent(name, evQueued("critic-r0", runDir, "critic-go"));
    appendEvent(name, evDone("critic-r0", runDir, { agent: "critic-go", session: "ses_cg" }));
    appendAck(name, "run:critic-r0:done", `ACTION critic ${path.join(runDir, "ticket.json")} x ${findings} 1`, { ticket: "t8" });
    appendEvent(name, evQueued("t8c/findings-r1", runDir, "critic", { out: findings }));
    appendEvent(name, evDone("t8c/findings-r1", runDir, { out: findings, agent: "critic", session: "ses_c" }));
    appendEvent(name, evVerdict("t8c/findings-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  assert.match(step(h, name, "verdict:t8c/findings-r1"), /^ESCALATE review-unlinked /);
  // the same link to a cc-worker run resumes it
  const s2 = t8Stream("cc-linked");
  const f2 = path.join(s2.runDir, "findings-r1.md");
  inHome(s2.h, () => {
    appendEvent(s2.name, evQueued("worker-r1", s2.runDir, "cc-worker"));
    appendEvent(s2.name, evDone("worker-r1", s2.runDir, { agent: "cc-worker", session: "ses_claude" }));
    appendAck(s2.name, "run:worker-r1:done", `ACTION critic ${path.join(s2.runDir, "ticket.json")} x ${f2} 1`, { ticket: "t8" });
    appendEvent(s2.name, evQueued("t8c/findings-r1", s2.runDir, "critic", { out: f2 }));
    appendEvent(s2.name, evDone("t8c/findings-r1", s2.runDir, { out: f2, agent: "critic", session: "ses_c" }));
    appendEvent(s2.name, evVerdict("t8c/findings-r1", s2.runDir, { effective: "CHANGES_REQUESTED" }));
  });
  assert.match(step(s2.h, s2.name, "verdict:t8c/findings-r1"), /^ACTION resume-worker .*--agent cc-worker .*--session ses_claude /);
});

import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { driveOnce, handleEvent } from "../bin/desk.mjs";
import { appendAck, appendEvent, orchRoot, readAckLines, readEvents, unhandled } from "../bin/handoff.mjs";
import { processStart } from "../bin/proc-tree.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "desk.mjs");
const CLEAN = [];
const REAL_HOME = os.homedir();
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-daemon-"));
  CLEAN.push(h);
  return h;
}
const sdir = (h) => path.join(h, ".config", "orchestrator", "streams");
function mkStream(h, name = "m6a") {
  fs.mkdirSync(sdir(h), { recursive: true });
  fs.writeFileSync(
    path.join(sdir(h), `${name}.json`),
    JSON.stringify({ name, repo: "", plan: "", status: "active", next: "n", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: null, done_at: null }),
  );
}
function inHome(h, fn) {
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  if (path.resolve(orchRoot()) === path.resolve(REAL_HOME)) {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
    throw new Error("orchRoot resolved to the real home — refusing");
  }
  const restore = () => {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  };
  let out;
  try {
    out = fn();
  } catch (e) {
    restore();
    throw e;
  }
  // An async body keeps the env for the WHOLE body: the restore runs only once the returned promise settles.
  if (out && typeof out.then === "function") {
    return (async () => {
      try {
        return await out;
      } finally {
        restore();
      }
    })();
  }
  restore();
  return out;
}
const lockDirOf = (h) => path.join(h, ".config", "orchestrator", "desk-watch.lock");
const cli = (h, args, extraEnv = {}) => spawnSync(process.execPath, [BIN, ...args], { env: { ...process.env, ORCH_HOME: h, ...extraEnv }, encoding: "utf8" });
const DRY = { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" };
const at = () => new Date().toISOString();

function mkTicket(h, slug = "t1", over = {}) {
  const runDir = path.join(h, "reports", slug);
  fs.mkdirSync(runDir, { recursive: true });
  const t = { ticket: slug, worktree: path.join(h, "wt", slug), branch: `feat/${slug}`, base: "HEAD", mandate: path.join(runDir, "mandate.md"), report: path.join(runDir, "report.md"), max_rounds: 3, senior_trigger: null, repo: "", merge: "ff", ...over };
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify(t));
  fs.writeFileSync(t.mandate, "mandate\n");
  fs.writeFileSync(t.report, "report\n");
  fs.mkdirSync(t.worktree, { recursive: true });
  if (!fs.existsSync(path.join(t.worktree, ".git"))) fs.writeFileSync(path.join(t.worktree, ".git"), "gitdir: placeholder\n"); // open ticket, like desk.test.mjs mkTicket
  return t;
}
const gitRepo = () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-dgit-"));
  CLEAN.push(dir);
  const g = (...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();
  g("init", "-b", "main");
  g("config", "user.email", "daemon@example.com");
  g("config", "user.name", "daemon");
  fs.writeFileSync(path.join(dir, "a.txt"), "a\n");
  g("add", "a.txt");
  g("commit", "-m", "base");
  return { dir, head: g("rev-parse", "HEAD") };
};
const evQ = (run, out, ticket, agent = "worker") => ({ key: `run:${run}:queued`, kind: "queued", run, out, agent, ticket, pid: process.pid, pid_start: processStart(process.pid), at: at() });
const evDone = (run, out, agent = "worker", over = {}) => ({ key: `run:${run}:done`, kind: "run-done", run, out, agent, exit: 0, outcome: "done", at: at(), ...over });
const daemonState = (h) => JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "desk-daemon", "state.json"), "utf8"));
const escLines = (h) => fs.readFileSync(path.join(h, ".config", "orchestrator", "desk-daemon", "escalations.jsonl"), "utf8").split("\n").filter(Boolean);

test("driveOnce (dry): a worker run-done becomes ACTION critic, then critic-inflight once queued", async () => {
  const h = home();
  mkStream(h);
  const t = mkTicket(h);
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out));
  });
  const dry = { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" };
  const saved = { ...process.env };
  Object.assign(process.env, dry);
  try {
    const first = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "critic");
    assert.match(first[0].line, /^critic r1/);
    // The critic run is now queued (oc-worker dispatched): re-stepping the same key must not spawn a second one.
    const findings = path.join(h, "reports", "t1", "findings-r1.md");
    inHome(h, () => appendEvent("m6a", evQ("t1/findings-r1", findings, path.join(h, "reports", "t1", "ticket.json"), "critic")));
    const second = await inHome(h, () => handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(second.outcome, "critic-inflight");
  } finally {
    for (const k of Object.keys(dry)) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("driveOnce (dry): a blocked_question pages exactly once", async () => {
  const h = home();
  mkStream(h);
  const t = mkTicket(h);
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "blocked\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out, "worker", { outcome: "blocked_question" }));
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    const first = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(first[0].outcome, "paged");
    assert.equal(escLines(h).length, 1);
    assert.match(escLines(h)[0], /blocked_question|question/);
    const second = await inHome(h, () => handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(second.outcome, "paged", "replay of a paged key never re-pages");
    assert.equal(escLines(h).length, 1, "exactly once");
    assert.deepEqual(daemonState(h).paged, ["run:t1/worker-r1:done"]);
  } finally {
    for (const k of Object.keys(DRY)) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("driveOnce: a finished critic run becomes a verdict and its run-done leaves unhandled", async () => {
  const h = home();
  mkStream(h);
  const repo = gitRepo();
  const t = mkTicket(h, "t1", { worktree: repo.dir, base: "main" });
  const findings = path.join(h, "reports", "t1", "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: APPROVED\nTESTS: none\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/critic-r1", findings, path.join(h, "reports", "t1", "ticket.json"), "critic"));
    appendEvent("m6a", evDone("t1/critic-r1", findings, "critic"));
  });
  const saved = { ORCH_NO_NOTIFY: process.env.ORCH_NO_NOTIFY };
  process.env.ORCH_NO_NOTIFY = "1";
  try {
    const r = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(r.length, 1);
    assert.equal(r[0].outcome, "verdict", JSON.stringify(r));
    const keys = inHome(h, () => readEvents("m6a").map((e) => e.key));
    assert.ok(keys.includes("verdict:t1/critic-r1"), "verdict event appended");
    const acks = inHome(h, () => readAckLines("m6a"));
    assert.ok(acks.some((l) => l.key === "run:t1/critic-r1:done" && l.resolved), "run-done resolved-acked");
    const un = inHome(h, () => unhandled("m6a"));
    assert.ok(!un.some((e) => e.key === "run:t1/critic-r1:done"), "handled run-done leaves unhandled");
  } finally {
    if (saved.ORCH_NO_NOTIFY === undefined) delete process.env.ORCH_NO_NOTIFY;
    else process.env.ORCH_NO_NOTIFY = saved.ORCH_NO_NOTIFY;
  }
});

test("daemon start refuses a live session lock; takes a stale one; stop clears it", () => {
  const h = home();
  mkStream(h);
  fs.mkdirSync(lockDirOf(h), { recursive: true });
  const ownerFile = path.join(lockDirOf(h), "owner");
  // live session owner: this very process
  fs.writeFileSync(ownerFile, JSON.stringify({ pid: process.pid, pid_start: processStart(process.pid), at: at(), token: "live", by: "oc" }));
  const refused = cli(h, ["daemon", "start", "--interval", "1"], DRY);
  assert.equal(refused.status, 3, refused.stderr);
  assert.match(refused.stderr, /desk-watch: running as pid/);
  // stale owner: a recycled pid record (alive pid, wrong start) with an old heartbeat
  fs.writeFileSync(ownerFile, JSON.stringify({ pid: process.pid, pid_start: "2020-01-01T00:00:00.000Z", at: "2020-01-01T00:00:00.000Z", token: "stale" }));
  const started = cli(h, ["daemon", "start", "--interval", "1"], DRY);
  assert.equal(started.status, 0, started.stderr);
  assert.match(started.stdout, /daemon started pid=\d+ log=/);
  const owner = JSON.parse(fs.readFileSync(ownerFile, "utf8"));
  assert.equal(owner.kind, "daemon");
  assert.notEqual(owner.pid, process.pid);
  // a second start refuses the live daemon
  const second = cli(h, ["daemon", "start", "--interval", "1"], DRY);
  assert.equal(second.status, 3);
  const daemonPid = owner.pid;
  assert.ok(daemonPid > 0);
  const stopped = cli(h, ["daemon", "stop"]);
  assert.equal(stopped.status, 0, stopped.stderr);
  assert.match(stopped.stdout, new RegExp(`daemon: stopped pid ${daemonPid}`));
  assert.ok(!fs.existsSync(lockDirOf(h)), "stop releases the lock");
  assert.equal(cli(h, ["daemon", "stop"]).status, 0, "stop on no lock is 0");
});

test("daemon status names a daemon owner and pending escalations", () => {
  const h = home();
  mkStream(h);
  fs.mkdirSync(lockDirOf(h), { recursive: true });
  fs.writeFileSync(
    path.join(lockDirOf(h), "owner"),
    JSON.stringify({ pid: process.pid, pid_start: processStart(process.pid), at: at(), token: "d", kind: "daemon", log: "/tmp/daemon.log" }),
  );
  const ddir = path.join(h, ".config", "orchestrator", "desk-daemon");
  fs.mkdirSync(ddir, { recursive: true });
  fs.writeFileSync(path.join(ddir, "escalations.jsonl"), JSON.stringify({ at: at(), stream: "m6a", key: "run:t1/worker-r1:done", reason: "worker-blocked /x" }) + "\n");
  const r = cli(h, ["daemon", "status"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /watch live pid=\d+ \(daemon\) heartbeat \ds ago \(start verified\) log=\/tmp\/daemon\.log/);
  assert.match(r.stdout, /escalations pending: 1/);
  assert.match(r.stdout, /run:t1\/worker-r1:done worker-blocked/);
});

test("desk-check pages on an unresolved ESCALATE even with zero unhandled events", async () => {
  const h = home();
  mkStream(h);
  inHome(h, () => appendAck("m6a", "run:t1/worker-r1:done", "ESCALATE worker-blocked /x/out.md", { ticket: "t1" }));
  const r = await inHome(h, async () => (await import("../bin/desk-check.mjs")).check());
  assert.equal(r.code, 1);
  assert.match(r.text, /1 unresolved escalation\(s\) on m6a; no watcher — open a \/frood-desk/);
});

test("driveOnce: a verdict that cannot run pages exactly once, naming the fix", async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  // Ticket without worktree, like the live m3-pipeline ticket: verdict cannot run.
  const tp = path.join(h, "reports", "t1", "ticket.json");
  const tj = JSON.parse(fs.readFileSync(tp, "utf8"));
  delete tj.worktree;
  fs.writeFileSync(tp, JSON.stringify(tj));
  const findings = path.join(h, "reports", "t1", "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\nTESTS: none\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/findings-r1", findings, tp, "critic"));
    appendEvent("m6a", evDone("t1/findings-r1", findings, "critic", { outcome: "error" }));
  });
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  // Daemon ctx persists across polls: reuse it, like daemonRun does.
  const ctx = { lastPoll: null, printed: new Set() };
  try {
    const first = await inHome(h, async () => await driveOnce(ctx, {}));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "paged");
    assert.equal(escLines(h).length, 1);
    assert.match(escLines(h)[0], /lacks worktree/);
    const second = await inHome(h, async () => await driveOnce(ctx, {}));
    assert.equal(second.length, 0, "acked nothing new, verdict already recorded as paged");
    assert.equal(escLines(h).length, 1, "a stuck key never re-pages, on any path");
    assert.deepEqual(daemonState(h).paged, ["run:t1/findings-r1:done"]);
  } finally {
    for (const k of Object.keys({ ORCH_NO_NOTIFY: 1, ORCH_AWAIT_QUEUED_MS: 1 })) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("verdict names the exact ticket problem", () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  const findings = path.join(h, "reports", "t1", "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: APPROVED\n");
  // Never queued at all.
  let r = cli(h, ["verdict", "m6a", "t1/nope", "--findings", findings]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /no run t1\/nope/);
  inHome(h, () => appendEvent("m6a", evQ("t1/findings-r1", findings, path.join(h, "reports", "t1", "ticket.json"), "critic")));
  // Ticket without worktree.
  const tp = path.join(h, "reports", "t1", "ticket.json");
  const tj = JSON.parse(fs.readFileSync(tp, "utf8"));
  delete tj.worktree;
  fs.writeFileSync(tp, JSON.stringify(tj));
  r = cli(h, ["verdict", "m6a", "t1/findings-r1", "--findings", findings]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /lacks worktree/);
});


test("driveOnce (dry): a worker run-done becomes ACTION critic, then critic-inflight once queued", async () => {
  const h = home();
  mkStream(h);
  const t = mkTicket(h);
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out));
  });
  const dry = { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" };
  const saved = { ...process.env };
  Object.assign(process.env, dry);
  try {
    const first = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "critic");
    assert.match(first[0].line, /^critic r1/);
    // The critic run is now queued (oc-worker dispatched): re-stepping the same key must not spawn a second one.
    const findings = path.join(h, "reports", "t1", "findings-r1.md");
    inHome(h, () => appendEvent("m6a", evQ("t1/findings-r1", findings, path.join(h, "reports", "t1", "ticket.json"), "critic")));
    const second = await inHome(h, () => handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(second.outcome, "critic-inflight");
  } finally {
    for (const k of Object.keys(dry)) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("driveOnce (dry): a blocked_question pages exactly once", async () => {
  const h = home();
  mkStream(h);
  const t = mkTicket(h);
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "blocked\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out, "worker", { outcome: "blocked_question" }));
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    const first = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(first[0].outcome, "paged");
    assert.equal(escLines(h).length, 1);
    assert.match(escLines(h)[0], /blocked_question|question/);
    const second = await inHome(h, () => handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(second.outcome, "paged", "replay of a paged key never re-pages");
    assert.equal(escLines(h).length, 1, "exactly once");
    assert.deepEqual(daemonState(h).paged, ["run:t1/worker-r1:done"]);
  } finally {
    for (const k of Object.keys(DRY)) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("driveOnce: a finished critic run becomes a verdict and its run-done leaves unhandled", async () => {
  const h = home();
  mkStream(h);
  const repo = gitRepo();
  const t = mkTicket(h, "t1", { worktree: repo.dir, base: "main" });
  const findings = path.join(h, "reports", "t1", "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: APPROVED\nTESTS: none\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/critic-r1", findings, path.join(h, "reports", "t1", "ticket.json"), "critic"));
    appendEvent("m6a", evDone("t1/critic-r1", findings, "critic"));
  });
  const saved = { ORCH_NO_NOTIFY: process.env.ORCH_NO_NOTIFY };
  process.env.ORCH_NO_NOTIFY = "1";
  try {
    const r = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(r.length, 1);
    assert.equal(r[0].outcome, "verdict", JSON.stringify(r));
    const keys = inHome(h, () => readEvents("m6a").map((e) => e.key));
    assert.ok(keys.includes("verdict:t1/critic-r1"), "verdict event appended");
    const acks = inHome(h, () => readAckLines("m6a"));
    assert.ok(acks.some((l) => l.key === "run:t1/critic-r1:done" && l.resolved), "run-done resolved-acked");
    const un = inHome(h, () => unhandled("m6a"));
    assert.ok(!un.some((e) => e.key === "run:t1/critic-r1:done"), "handled run-done leaves unhandled");
  } finally {
    if (saved.ORCH_NO_NOTIFY === undefined) delete process.env.ORCH_NO_NOTIFY;
    else process.env.ORCH_NO_NOTIFY = saved.ORCH_NO_NOTIFY;
  }
});

test("daemon start refuses a live session lock; takes a stale one; stop clears it", () => {
  const h = home();
  mkStream(h);
  fs.mkdirSync(lockDirOf(h), { recursive: true });
  const ownerFile = path.join(lockDirOf(h), "owner");
  // live session owner: this very process
  fs.writeFileSync(ownerFile, JSON.stringify({ pid: process.pid, pid_start: processStart(process.pid), at: at(), token: "live", by: "oc" }));
  const refused = cli(h, ["daemon", "start", "--interval", "1"], DRY);
  assert.equal(refused.status, 3, refused.stderr);
  assert.match(refused.stderr, /desk-watch: running as pid/);
  // stale owner: a recycled pid record (alive pid, wrong start) with an old heartbeat
  fs.writeFileSync(ownerFile, JSON.stringify({ pid: process.pid, pid_start: "2020-01-01T00:00:00.000Z", at: "2020-01-01T00:00:00.000Z", token: "stale" }));
  const started = cli(h, ["daemon", "start", "--interval", "1"], DRY);
  assert.equal(started.status, 0, started.stderr);
  assert.match(started.stdout, /daemon started pid=\d+ log=/);
  const owner = JSON.parse(fs.readFileSync(ownerFile, "utf8"));
  assert.equal(owner.kind, "daemon");
  assert.notEqual(owner.pid, process.pid);
  // a second start refuses the live daemon
  const second = cli(h, ["daemon", "start", "--interval", "1"], DRY);
  assert.equal(second.status, 3);
  const daemonPid = owner.pid;
  assert.ok(daemonPid > 0);
  const stopped = cli(h, ["daemon", "stop"]);
  assert.equal(stopped.status, 0, stopped.stderr);
  assert.match(stopped.stdout, new RegExp(`daemon: stopped pid ${daemonPid}`));
  assert.ok(!fs.existsSync(lockDirOf(h)), "stop releases the lock");
  assert.equal(cli(h, ["daemon", "stop"]).status, 0, "stop on no lock is 0");
});

test("daemon status names a daemon owner and pending escalations", () => {
  const h = home();
  mkStream(h);
  fs.mkdirSync(lockDirOf(h), { recursive: true });
  fs.writeFileSync(
    path.join(lockDirOf(h), "owner"),
    JSON.stringify({ pid: process.pid, pid_start: processStart(process.pid), at: at(), token: "d", kind: "daemon", log: "/tmp/daemon.log" }),
  );
  const ddir = path.join(h, ".config", "orchestrator", "desk-daemon");
  fs.mkdirSync(ddir, { recursive: true });
  fs.writeFileSync(path.join(ddir, "escalations.jsonl"), JSON.stringify({ at: at(), stream: "m6a", key: "run:t1/worker-r1:done", reason: "worker-blocked /x" }) + "\n");
  const r = cli(h, ["daemon", "status"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /watch live pid=\d+ \(daemon\) heartbeat \ds ago \(start verified\) log=\/tmp\/daemon\.log/);
  assert.match(r.stdout, /escalations pending: 1/);
  assert.match(r.stdout, /run:t1\/worker-r1:done worker-blocked/);
});

test("desk-check pages on an unresolved ESCALATE even with zero unhandled events", async () => {
  const h = home();
  mkStream(h);
  inHome(h, () => appendAck("m6a", "run:t1/worker-r1:done", "ESCALATE worker-blocked /x/out.md", { ticket: "t1" }));
  const r = await inHome(h, async () => (await import("../bin/desk-check.mjs")).check());
  assert.equal(r.code, 1);
  assert.match(r.text, /1 unresolved escalation\(s\) on m6a; no watcher — open a \/frood-desk/);
});

test("driveOnce: a verdict that cannot run pages exactly once, naming the fix", async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  // Ticket without worktree, like the live m3-pipeline ticket: verdict cannot run.
  const tp = path.join(h, "reports", "t1", "ticket.json");
  const tj = JSON.parse(fs.readFileSync(tp, "utf8"));
  delete tj.worktree;
  fs.writeFileSync(tp, JSON.stringify(tj));
  const findings = path.join(h, "reports", "t1", "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\nTESTS: none\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/findings-r1", findings, tp, "critic"));
    appendEvent("m6a", evDone("t1/findings-r1", findings, "critic", { outcome: "error" }));
  });
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  // Daemon ctx persists across polls: reuse it, like daemonRun does.
  const ctx = { lastPoll: null, printed: new Set() };
  try {
    const first = await inHome(h, async () => await driveOnce(ctx, {}));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "paged");
    assert.equal(escLines(h).length, 1);
    assert.match(escLines(h)[0], /lacks worktree/);
    const second = await inHome(h, async () => await driveOnce(ctx, {}));
    assert.equal(second.length, 0, "acked nothing new, verdict already recorded as paged");
    assert.equal(escLines(h).length, 1, "a stuck key never re-pages, on any path");
    assert.deepEqual(daemonState(h).paged, ["run:t1/findings-r1:done"]);
  } finally {
    for (const k of Object.keys({ ORCH_NO_NOTIFY: 1, ORCH_AWAIT_QUEUED_MS: 1 })) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("verdict names the exact ticket problem", () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  const findings = path.join(h, "reports", "t1", "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: APPROVED\n");
  // Never queued at all.
  let r = cli(h, ["verdict", "m6a", "t1/nope", "--findings", findings]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /no run t1\/nope/);
  inHome(h, () => appendEvent("m6a", evQ("t1/findings-r1", findings, path.join(h, "reports", "t1", "ticket.json"), "critic")));
  // Ticket without worktree.
  const tp = path.join(h, "reports", "t1", "ticket.json");
  const tj = JSON.parse(fs.readFileSync(tp, "utf8"));
  delete tj.worktree;
  fs.writeFileSync(tp, JSON.stringify(tj));
  r = cli(h, ["verdict", "m6a", "t1/findings-r1", "--findings", findings]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /lacks worktree/);
});

test("doCritic pages critic-spawn-failed when the spawn never queues (and retries on the next poll)", async () => {
  const h = home();
  mkStream(h);
  const t = mkTicket(h);
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out));
  });
  // Point the ticket worktree at a path whose spawn instantly dies: oc-worker exits
  // before writing its queued event, so nothing ever appears. Keep the .git marker
  // so the ticket still reads as open (closedTicket treats a missing .git as merged).
  const tp = path.join(h, "reports", "t1", "ticket.json");
  const tj = JSON.parse(fs.readFileSync(tp, "utf8"));
  tj.worktree = path.join(h, "wt", "gone");
  fs.mkdirSync(tj.worktree, { recursive: true });
  fs.writeFileSync(path.join(tj.worktree, ".git"), "gitdir: placeholder\n");
  fs.writeFileSync(tp, JSON.stringify(tj));
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1", ORCH_AWAIT_QUEUED_MS: "1500" });
  // Short-circuit the 30s watch: patch awaitQueued via a dead OC_WORKER is overkill;
  // instead drive handleEvent with a stubbed spawn by pointing OC_WORKER at /bin/false
  // through a wrapper is complex — so assert the page path via a missing out dir:
  // remove the run dir so the prompt write fails? No — mkdirSync recreates it.
  // Simplest deterministic trigger: delete the ticket file → readTicket null → no-ticket page.
  // That path already exists; the NEW path needs a spawn that dies. Use ORCH_NO_DASH-free
  // real spawn of `node -e process.exit(1)` by temporarily replacing OC_WORKER? OC_WORKER is
  // a module const. Instead: run the real flow — oc-worker with a bad agent fails fast
  // with no queued event, which is exactly the production shape.
  try {
    const r = await inHome(h, async () => await handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(r.outcome, "paged");
    const lines = escLines(h);
    assert.equal(lines.length, 1);
    assert.match(lines[0], /critic-spawn-failed/);
    // The page is once-only: a second poll does not re-page the same key.
    const r2 = await inHome(h, async () => await handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(r2.outcome, "paged");
    assert.equal(escLines(h).length, 1, "exactly once");
  } finally {
    for (const k of Object.keys({ ORCH_NO_NOTIFY: 1, ORCH_AWAIT_QUEUED_MS: 1 })) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

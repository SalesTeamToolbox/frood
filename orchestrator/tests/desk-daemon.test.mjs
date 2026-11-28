import test, { after } from "node:test";
import assert from "node:assert/strict";
import crypto from "node:crypto";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { driveOnce, handleEvent, sweepOrphans } from "../bin/desk.mjs";
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

test("driveOnce (dry): a timed-out worker-nvidia run resumes on a fresh out with the mandate prompt", async () => {
  const h = home();
  mkStream(h);
  const t = mkTicket(h);
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json"), "worker-nvidia"));
    appendEvent("m6a", evDone("t1/worker-r1", out, "worker-nvidia", { outcome: "timeout", session: "ses_nvidia" }));
  });
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" });
  try {
    const first = await inHome(h, async () => await driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "resume", JSON.stringify(first));
    // nextOutTaken checks worker-r<nr+1>.md, so the fresh slot is worker-r2.md (never the timed-out run's own out).
    assert.match(first[0].line, /--out .*worker-r2\.md/, "resume names the fresh next out");
    assert.match(first[0].line, /--prompt .*mandate\.md/, "resume restates the task from the Mandate");
    assert.ok(!first[0].line.includes("worker-prompt-r1"), "prompt is the Mandate, never the unwritten worker-prompt-r1.md");
    assert.ok(!first[0].line.includes("--fallback"), "no hand-typed paid-first fallback");
  } finally {
    for (const k of Object.keys({ ORCH_DAEMON_DRY_RUN: 1, ORCH_NO_NOTIFY: 1 })) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
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

test("desk-check does not page on an unresolved ESCALATE with zero unhandled events", async () => {
  const h = home();
  mkStream(h);
  inHome(h, () => appendAck("m6a", "run:t1/worker-r1:done", "ESCALATE worker-blocked /x/out.md", { ticket: "t1" }));
  const r = await inHome(h, async () => (await import("../bin/desk-check.mjs")).check());
  assert.deepEqual(r, { code: 0 });
});

// A stub notify-send on PATH records desktop pages; ORCH_NO_NOTIFY is cleared so notifyDesktop really runs.
async function pagedDesktop(h, held) {
  const bin = fs.mkdtempSync(path.join(os.tmpdir(), "orch-notify-"));
  CLEAN.push(bin);
  const log = path.join(bin, "pages.log");
  fs.writeFileSync(path.join(bin, "notify-send"), `#!/bin/sh\necho "$@" >> "${log}"\n`, { mode: 0o755 });
  mkStream(h);
  if (held) {
    const sp = path.join(sdir(h), "m6a.json");
    const patch = held === "done" ? { status: "done" } : { held_by: "cc" };
    fs.writeFileSync(sp, JSON.stringify({ ...JSON.parse(fs.readFileSync(sp, "utf8")), ...patch }));
  }
  mkTicket(h);
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
  delete process.env.ORCH_NO_NOTIFY;
  process.env.PATH = `${bin}${path.delimiter}${saved.PATH}`;
  const errs = [];
  const origErr = console.error;
  console.error = (...a) => errs.push(a.join(" "));
  try {
    // a done stream is not polled (its escalations come from a direct step), so hand the event over explicitly
    if (held === "done") await inHome(h, async () => await handleEvent("m6a", "run:t1/findings-r1:done", undefined));
    else await inHome(h, async () => await driveOnce({ lastPoll: null, printed: new Set() }, {}));
  } finally {
    console.error = origErr;
    process.env.PATH = saved.PATH;
    if (saved.ORCH_NO_NOTIFY !== undefined) process.env.ORCH_NO_NOTIFY = saved.ORCH_NO_NOTIFY;
  }
  // an orphan notice is a detached helper: wait (briefly) for it to reach the stub when one is expected
  if (held !== true) for (let i = 0; i < 100 && !fs.existsSync(log); i++) await new Promise((r) => setTimeout(r, 50));
  return { pages: fs.existsSync(log) ? fs.readFileSync(log, "utf8") : "", errs };
}

test("escalation on a held stream with no reachable session leaves the desktop quiet", async () => {
  const { pages, errs } = await pagedDesktop(home(), true);
  assert.equal(pages, "");
  assert.ok(errs.some((e) => /escalation left for holder cc \(no reachable session\)/.test(e)), errs.join("\n"));
});

test("escalation on an unheld stream pages the desktop", async () => {
  const { pages } = await pagedDesktop(home(), false);
  assert.match(pages, /orchestrator desk/);
  assert.match(pages, /lacks worktree/);
  assert.match(pages, /Resolve in new session/);
});

test("escalation on a done stream gets a plain desktop page with no resolve action", async () => {
  const { pages } = await pagedDesktop(home(), "done");
  assert.match(pages, /orchestrator desk/);
  assert.match(pages, /lacks worktree/);
  assert.doesNotMatch(pages, /Resolve in new session/);
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
  // The spawn must die before it queues. A findings file that already exists does that: oc-worker --stream refuses a
  // used --out (exit 2) before writing the queued event. (Before --stream was passed, every spawn "never queued".)
  fs.writeFileSync(path.join(h, "reports", "t1", "findings-r1.md"), "stale\n");
  // step now skips a taken findings slot, so the stale slot reaches doCritic only through a stored decision (a replay).
  inHome(h, () => appendAck("m6a", "run:t1/worker-r1:done", `ACTION critic ${tp} ${out} ${path.join(h, "reports", "t1", "findings-r1.md")} 1`, { ticket: "t1" }));
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

// The daemon's critic spawns must carry --stream, or oc-worker writes no queued/run-done event and the desk pages
// critic-spawn-failed for a running critic and never sees its verdict (findings 7, plan-desk-daemon-errors).
test("doCritic and the critic retry spawn oc-worker with --stream <stream>", { skip: process.platform === "win32" ? "POSIX stub" : false }, async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  const runDir = path.join(h, "reports", "t1");
  const out = path.join(runDir, "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  const argvLog = path.join(h, "argv.log");
  const stub = path.join(h, "stub-oc-worker.mjs");
  fs.writeFileSync(stub, `import fs from "node:fs"; fs.appendFileSync(${JSON.stringify(argvLog)}, JSON.stringify(process.argv.slice(2)) + "\\n");\n`);
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(runDir, "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out));
  });
  const keys = ["ORCH_NO_NOTIFY", "ORCH_AWAIT_QUEUED_MS", "ORCH_OC_WORKER"];
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1", ORCH_AWAIT_QUEUED_MS: "300", ORCH_OC_WORKER: stub });
  const desk = await import(`../bin/desk.mjs?stub=${Date.now()}`); // re-read OC_WORKER with the stub in place
  const waitArgv = async (n) => {
    for (let i = 0; i < 50; i++) {
      try {
        const lines = fs.readFileSync(argvLog, "utf8").trim().split("\n");
        if (lines.length >= n) return lines.map((l) => JSON.parse(l));
      } catch {}
      await new Promise((r) => setTimeout(r, 50));
    }
    return [];
  };
  try {
    await inHome(h, async () => await desk.handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    const [critic] = await waitArgv(1);
    assert.ok(critic, "the critic was spawned");
    assert.equal(critic[critic.indexOf("--role") + 1], "critic", JSON.stringify(critic));
    assert.ok(!critic.includes("--agent"), "no hand-typed --agent: " + JSON.stringify(critic));
    assert.ok(!critic.includes("--fallback"), "no hand-typed --fallback: " + JSON.stringify(critic));
    assert.equal(critic[critic.indexOf("--stream") + 1], "m6a", JSON.stringify(critic));
    // The critic ran and failed (no VERDICT in its out): the retry uses CHAINS.critic minus `critic` -> critic-go first.
    const findings = path.join(runDir, "findings-r1.md");
    fs.writeFileSync(findings, "no verdict here\n");
    inHome(h, () => {
      appendEvent("m6a", evQ("t1/findings-r1", findings, path.join(runDir, "ticket.json"), "critic"));
      appendEvent("m6a", evDone("t1/findings-r1", findings, "critic"));
    });
    await inHome(h, async () => await desk.handleEvent("m6a", "run:t1/findings-r1:done", undefined));
    const all = await waitArgv(2);
    const alt = all[1];
    assert.ok(alt, "the critic retry was spawned");
    assert.equal(alt[alt.indexOf("--agent") + 1], "critic-go");
    assert.equal(alt[alt.indexOf("--fallback") + 1], "critic-nvidia,critic-free");
    assert.equal(alt[alt.indexOf("--out") + 1], path.join(runDir, "findings-r1-alt.md"));
    assert.equal(alt[alt.indexOf("--stream") + 1], "m6a", JSON.stringify(alt));
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// A failed `critic-nvidia` run retries with CHAINS.critic minus critic-nvidia: critic first, then
// critic-go,critic-free (never critic-free ahead of Nvidia).
test("critic retry after a failed critic-nvidia run spawns critic first", { skip: process.platform === "win32" ? "POSIX stub" : false }, async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  const runDir = path.join(h, "reports", "t1");
  const tp = path.join(runDir, "ticket.json");
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(findings, "no verdict here\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/findings-r1", findings, tp, "critic-nvidia"));
    appendEvent("m6a", evDone("t1/findings-r1", findings, "critic-nvidia"));
  });
  const argvLog = path.join(h, "argv.log");
  const stub = path.join(h, "stub-oc-worker.mjs");
  fs.writeFileSync(stub, `import fs from "node:fs"; fs.appendFileSync(${JSON.stringify(argvLog)}, JSON.stringify(process.argv.slice(2)) + "\\n");\n`);
  const keys = ["ORCH_NO_NOTIFY", "ORCH_AWAIT_QUEUED_MS", "ORCH_OC_WORKER"];
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1", ORCH_AWAIT_QUEUED_MS: "300", ORCH_OC_WORKER: stub });
  const desk = await import(`../bin/desk.mjs?nvidia=${Date.now()}`);
  const waitArgv = async (n) => {
    for (let i = 0; i < 50; i++) {
      try {
        const lines = fs.readFileSync(argvLog, "utf8").trim().split("\n");
        if (lines.length >= n) return lines.map((l) => JSON.parse(l));
      } catch {}
      await new Promise((r) => setTimeout(r, 50));
    }
    return [];
  };
  try {
    await inHome(h, async () => await desk.handleEvent("m6a", "run:t1/findings-r1:done", undefined));
    const [retry] = await waitArgv(1);
    assert.ok(retry, "the critic retry was spawned");
    assert.equal(retry[retry.indexOf("--agent") + 1], "critic");
    assert.equal(retry[retry.indexOf("--fallback") + 1], "critic-go,critic-free");
    assert.equal(retry[retry.indexOf("--out") + 1], path.join(runDir, "findings-r1-alt.md"));
    assert.equal(retry[retry.indexOf("--stream") + 1], "m6a", JSON.stringify(retry));
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// A failed critic is retried once as critic-alt. The retry's run is a stream event of its own, so the failed critic's
// run-done must not page critic-failed on the next sweep while the -alt critic is still running.
test("critic-alt retry: one spawn, no critic-failed page across polls, and the failed run-done is settled", { skip: process.platform === "win32" ? "POSIX stub" : false }, async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  const runDir = path.join(h, "reports", "t1");
  const tp = path.join(runDir, "ticket.json");
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(findings, "critic crashed, no verdict\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/findings-r1", findings, tp, "critic"));
    appendEvent("m6a", evDone("t1/findings-r1", findings, "critic"));
  });
  // The stub queues its run like oc-worker --stream does, so awaitQueued sees it.
  const argvLog = path.join(h, "argv.log");
  const stub = path.join(h, "stub-oc-worker.mjs");
  const handoff = path.resolve(import.meta.dirname, "..", "bin", "handoff.mjs");
  fs.writeFileSync(
    stub,
    `import fs from "node:fs"; import path from "node:path"; import { appendEvent } from ${JSON.stringify(handoff)};
const a = process.argv.slice(2); fs.appendFileSync(${JSON.stringify(argvLog)}, JSON.stringify(a) + "\\n");
const out = a[a.indexOf("--out") + 1], stream = a[a.indexOf("--stream") + 1];
const run = "t1/" + path.basename(out, ".md");
appendEvent(stream, { key: "run:" + run + ":queued", kind: "queued", run, out, agent: "critic-alt", ticket: ${JSON.stringify(tp)}, pid: process.pid, at: new Date().toISOString() });
`,
  );
  const keys = ["ORCH_NO_NOTIFY", "ORCH_AWAIT_QUEUED_MS", "ORCH_OC_WORKER"];
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1", ORCH_AWAIT_QUEUED_MS: "5000", ORCH_OC_WORKER: stub });
  const desk = await import(`../bin/desk.mjs?alt=${Date.now()}`);
  const ctx = { lastPoll: null, printed: new Set() };
  try {
    const first = await inHome(h, async () => await desk.driveOnce(ctx, {}));
    assert.ok(first.some((r) => r.outcome === "critic-retry"), JSON.stringify(first));
    await inHome(h, async () => await desk.driveOnce(ctx, {}));
    await inHome(h, async () => await desk.driveOnce(ctx, {}));
    const spawns = fs.readFileSync(argvLog, "utf8").trim().split("\n");
    assert.equal(spawns.length, 1, "exactly one critic-alt spawn");
    const esc = fs.existsSync(path.join(h, ".config", "orchestrator", "desk-daemon", "escalations.jsonl")) ? escLines(h) : [];
    assert.deepEqual(esc.filter((l) => /critic-failed/.test(l)), [], "no critic-failed page while the -alt critic runs");
    const un = inHome(h, () => unhandled("m6a"));
    assert.ok(!un.some((e) => e.key === "run:t1/findings-r1:done"), "the retried run-done is settled");
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// An -alt critic's CHANGES_REQUESTED must still resume the worker it reviewed (the ACTION critic ack names
// findings-r<N>.md, the -alt verdict names findings-r<N>-alt.md).
test("step: an -alt critic's CHANGES_REQUESTED verdict resumes the reviewed worker, not review-unlinked", () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  const runDir = path.join(h, "reports", "t1");
  const tp = path.join(runDir, "ticket.json");
  const out = path.join(runDir, "worker-r1.md");
  const findings = path.join(runDir, "findings-r1.md");
  const alt = path.join(runDir, "findings-r1-alt.md");
  fs.writeFileSync(out, "done\n");
  fs.writeFileSync(alt, "VERDICT: CHANGES_REQUESTED\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, tp, "worker"));
    appendEvent("m6a", evDone("t1/worker-r1", out, "worker", { session: "ses_W1" }));
    appendAck("m6a", "run:t1/worker-r1:done", `ACTION critic ${tp} ${out} ${findings} 1`, { ticket: "t1" });
    appendEvent("m6a", evQ("t1/findings-r1-alt", alt, tp, "critic-alt"));
    appendEvent("m6a", evDone("t1/findings-r1-alt", alt, "critic-alt"));
    appendEvent("m6a", { key: "verdict:t1/findings-r1-alt", kind: "verdict", run: "t1/findings-r1-alt", at: at(), effective: "CHANGES_REQUESTED", senior: false, findings: alt, reviewed_sha: "abc1234" });
  });
  const r = cli(h, ["step", "m6a", "verdict:t1/findings-r1-alt", "--by", "cc"], { ORCH_NO_NOTIFY: "1" });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /^ACTION resume-worker .*--session ses_W1/m, r.stdout);
  assert.doesNotMatch(r.stdout, /review-unlinked/);
});

test("driveOnce (dry or stubbed): a critic whose run already has a verdict pages critic-slot-taken", async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  const runDir = path.join(h, "reports", "t1");
  const tp = path.join(runDir, "ticket.json");
  const out = path.join(runDir, "worker-r2.md");
  const findings = path.join(runDir, "findings-r2.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r2", out, tp));
    appendEvent("m6a", evDone("t1/worker-r2", out));
    appendEvent("m6a", evQ("t1/findings-r2", findings, tp, "critic"));
    appendEvent("m6a", evDone("t1/findings-r2", findings, "critic"));
    appendEvent("m6a", { key: "verdict:t1/findings-r2", kind: "verdict", run: "t1/findings-r2", effective: "APPROVED", senior: false, reviewed_sha: "abc", at: at() });
    // The stored decision names a slot whose critic already ran and was judged.
    appendAck("m6a", "run:t1/worker-r2:done", `ACTION critic ${tp} ${out} ${findings} 2`, { ticket: "t1" });
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    const r = await inHome(h, () => handleEvent("m6a", "run:t1/worker-r2:done", undefined));
    assert.equal(r.outcome, "paged");
    assert.match(escLines(h)[0], /critic-slot-taken/);
  } finally {
    for (const k of Object.keys(DRY)) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// ---------------------------------------------------------------- nested escalations (desk-nested-escalations)

import { createRequire as _createRequire } from "node:module";
const _require = _createRequire(import.meta.url);

// Full-schema mailbox fixture (like desk.test.mjs mkMailbox): desk.mjs inserts a complete row.
function mkMailbox(h) {
  const file = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const { DatabaseSync } = _require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    db.exec(`CREATE TABLE messages (
      id TEXT PRIMARY KEY, ts INTEGER NOT NULL, from_session TEXT NOT NULL,
      from_title TEXT NOT NULL DEFAULT '', from_branch TEXT NOT NULL DEFAULT '', to_session TEXT NOT NULL,
      subject TEXT NOT NULL, body TEXT NOT NULL,
      status TEXT NOT NULL DEFAULT 'unread' CHECK (status IN ('unread','read','acked')),
      expires_at INTEGER NOT NULL);`);
    db.exec(`CREATE TABLE peers (
      session_id TEXT PRIMARY KEY, harness TEXT NOT NULL DEFAULT 'claude', title TEXT NOT NULL DEFAULT '',
      directory TEXT NOT NULL DEFAULT '', branch TEXT NOT NULL DEFAULT '',
      first_seen INTEGER NOT NULL, last_seen INTEGER NOT NULL);`);
  } finally {
    db.close();
  }
  return file;
}
const mkPeers2 = (h, rows) => {
  const file = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  const { DatabaseSync } = _require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    for (const [id, agoMin] of Object.entries(rows))
      db.prepare("INSERT INTO peers (session_id, harness, title, directory, branch, first_seen, last_seen) VALUES (?, 'claude', '', '', '', ?, ?)").run(id, Date.now(), Date.now() - agoMin * 60_000);
  } finally {
    db.close();
  }
};
const mailTo = (file, to) => {
  if (!fs.existsSync(file)) return [];
  const { DatabaseSync } = _require("node:sqlite");
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    return db.prepare("SELECT subject, body FROM messages WHERE to_session = ? ORDER BY ts, id").all(to);
  } finally {
    db.close();
  }
};
const allMail = (file) => {
  if (!fs.existsSync(file)) return [];
  const { DatabaseSync } = _require("node:sqlite");
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    return db.prepare("SELECT to_session, subject FROM messages ORDER BY ts, id").all();
  } finally {
    db.close();
  }
};
// A stream held by a nested child session with a live parent: the child is long silent, the parent was just seen.
function nestedHeld(h, name = "m6a", { childAgo = 200, parentAgo = 2, parent = "ses_parent" } = {}) {
  mkStream(h, name);
  mkMailbox(h);
  const sp = path.join(sdir(h), `${name}.json`);
  const old = isoAgo(childAgo);
  fs.writeFileSync(sp, JSON.stringify({ ...JSON.parse(fs.readFileSync(sp, "utf8")), held_by: "cc", held_session: "ses_child", held_at: old, held_parent: parent, written_at: old }));
  mkPeers2(h, { "ses_child": childAgo, [parent]: parentAgo });
}
const isoAgo = (min) => new Date(Date.now() - min * 60_000).toISOString();
const openEsc = (h, name, key = "run:t1/worker-r1:done", reason = "senior /f") =>
  inHome(h, () => appendAck(name, key, `ESCALATE ${reason}`));

test("nested: an escalation mails both the holder and its parent, with the resolve line", async () => {
  const h = home();
  mkStream(h);
  const sp = path.join(sdir(h), "m6a.json");
  fs.writeFileSync(sp, JSON.stringify({ ...JSON.parse(fs.readFileSync(sp, "utf8")), held_by: "cc", held_session: "ses_child", held_at: at(), held_parent: "ses_parent" }));
  const mailbox = mkMailbox(h);
  mkPeers2(h, { "ses_child": 200, "ses_parent": 2 });
  mkTicket(h);
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "blocked\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out, "worker", { outcome: "blocked_question" }));
  });
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const r = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(r.length, 1);
    assert.equal(r[0].outcome, "paged");
    const child = mailTo(mailbox, "ses_child");
    assert.equal(child.length, 1, "the holder is mailed as today");
    assert.match(child[0].subject, /^desk: /);
    assert.doesNotMatch(child[0].subject, /nested/);
    const parent = mailTo(mailbox, "ses_parent");
    assert.equal(parent.length, 1, "the nested parent is mailed alongside");
    assert.match(parent[0].subject, /^desk: \[nested m6a\] /);
    for (const m of [...child, ...parent]) {
      assert.match(m.body, /Stream: m6a/);
      assert.match(m.body, /Event: run:t1\/worker-r1:done/);
      assert.match(m.body, /After you handle it: node .* resolve m6a run:t1\/worker-r1:done --note/);
    }
  } finally {
    for (const k of ["ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("nested: an idle holder with a live parent mails the parent once and never orphan-pages", () => {
  const h = home();
  nestedHeld(h);
  const mailbox = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    openEsc(h, "m6a");
    assert.deepEqual(inHome(h, () => sweepOrphans()), ["m6a"]);
    const state = daemonState(h);
    assert.ok(state.orphaned.some((id) => id.startsWith("parent:m6a:")), "a parent: entry records the wake-up");
    assert.ok(!state.orphaned.some((id) => id.startsWith("orphan:")), "no owner page: no orphan: entry");
    const parent = mailTo(mailbox, "ses_parent");
    assert.equal(parent.length, 1);
    assert.match(parent[0].subject, /child session idle with 1 open escalation\(s\)/);
    assert.match(parent[0].body, /run:t1\/worker-r1:done: node .* resolve m6a run:t1\/worker-r1:done --note/);
    assert.deepEqual(mailTo(mailbox, "ses_child"), [], "the sweep mails nobody else");
    assert.deepEqual(inHome(h, () => sweepOrphans()), [], "second poll: already woken");
    assert.equal(mailTo(mailbox, "ses_parent").length, 1, "exactly once per claim");
  } finally {
    for (const k of ["ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("nested: an idle holder with no parent still orphan-pages; a live holder stays quiet", () => {
  const h = home();
  mkStream(h);
  mkMailbox(h);
  const sp = path.join(sdir(h), "m6a.json");
  const old = isoAgo(200);
  fs.writeFileSync(sp, JSON.stringify({ ...JSON.parse(fs.readFileSync(sp, "utf8")), held_by: "cc", held_session: "ses_child", held_at: old, written_at: old }));
  mkPeers2(h, { "ses_child": 200 });
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    openEsc(h, "m6a");
    assert.deepEqual(inHome(h, () => sweepOrphans()), ["m6a"]);
    assert.ok(daemonState(h).orphaned.some((id) => id.startsWith("orphan:m6a:")), "the owner is paged as today");
  } finally {
    for (const k of ["ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("nested: a live-pid parent idle 3 h gets the parent mail and no orphan page", () => {
  const h = home();
  nestedHeld(h, "m6a", { parent: "local_awake3" });
  const mailbox = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  const dir = path.join(h, ".claude", "sessions");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${process.pid}.json`), JSON.stringify({ hostSessionId: "local_awake3", sessionId: "ses_awake3", status: "idle", statusUpdatedAt: Date.now() - 180 * 60_000 }));
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    openEsc(h, "m6a");
    assert.deepEqual(inHome(h, () => sweepOrphans()), ["m6a"]);
    const state = daemonState(h);
    assert.ok(state.orphaned.some((id) => id.startsWith("parent:m6a:")), "the parent is woken");
    assert.ok(!state.orphaned.some((id) => id.startsWith("orphan:")), "no owner page");
    const parent = mailTo(mailbox, "ses_awake3");
    assert.equal(parent.length, 1, "the live parent is mailed");
    assert.match(parent[0].subject, /\[nested m6a\]/);
  } finally {
    for (const k of ["ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("nested: a parent idle 25 h (past the wake window) does not suppress the orphan page", () => {
  const h = home();
  const mailbox = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  const dir = path.join(h, ".claude", "sessions");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, `${process.pid}.json`), JSON.stringify({ hostSessionId: "local_sleepy", sessionId: "ses_sleepy", status: "idle", statusUpdatedAt: Date.now() - 25 * 60 * 60_000 }));
  nestedHeld(h, "m6a", { parent: "local_sleepy", parentAgo: 2 });
  // no peer row for ses_sleepy: its only sign of life is the old session file
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    openEsc(h, "m6a");
    assert.deepEqual(inHome(h, () => sweepOrphans()), ["m6a"]);
    const state = daemonState(h);
    assert.ok(state.orphaned.some((id) => id.startsWith("orphan:m6a:")), "the owner is paged");
    assert.ok(!state.orphaned.some((id) => id.startsWith("parent:")), "no parent entry");
    assert.deepEqual(allMail(mailbox), [], "nobody is mailed");
  } finally {
    for (const k of ["ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("nested: a failed parent send falls through to the orphan page and writes no parent: entry", () => {
  const h = home();
  nestedHeld(h, "m6a", { parent: "ghost-parent" });
  // no mailbox at all: every send fails — but the parent still reads as live via its session file
  fs.rmSync(path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db"));
  const sessDir = path.join(h, ".claude", "sessions");
  fs.mkdirSync(sessDir, { recursive: true });
  fs.writeFileSync(path.join(sessDir, `${process.pid}.json`), JSON.stringify({ sessionId: "ghost-parent", status: "idle", statusUpdatedAt: Date.now() }));
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  const errs = [];
  const origErr = console.error;
  console.error = (...a) => errs.push(a.join(" "));
  try {
    openEsc(h, "m6a");
    assert.deepEqual(inHome(h, () => sweepOrphans()), ["m6a"]);
    const state = daemonState(h);
    assert.ok(state.orphaned.some((id) => id.startsWith("orphan:m6a:")), "the owner is paged");
    assert.ok(!state.orphaned.some((id) => id.startsWith("parent:")), "a failed send writes no parent: entry");
    assert.ok(errs.some((e) => /cannot send peer-mail to ghost-parent/.test(e)));
  } finally {
    console.error = origErr;
    for (const k of ["ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("nested: a dry run sends nothing and writes no ledger across two polls", () => {
  const h = home();
  nestedHeld(h);
  const mailbox = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1", ORCH_DAEMON_DRY_RUN: "1" });
  const logs = [];
  const origLog = console.log;
  console.log = (...a) => logs.push(a.join(" "));
  try {
    openEsc(h, "m6a");
    assert.deepEqual(inHome(h, () => sweepOrphans()), [], "dry run never pages");
    assert.deepEqual(inHome(h, () => sweepOrphans()), [], "nor on the second poll");
    assert.ok(!fs.existsSync(path.join(h, ".config", "orchestrator", "desk-daemon", "state.json")), "no ledger write");
    assert.deepEqual(allMail(mailbox), [], "no mail");
    assert.equal(logs.filter((l) => /DRY would wake parent of m6a/.test(l)).length, 1, "one dry line per process");
  } finally {
    console.log = origLog;
    for (const k of ["ORCH_NO_NOTIFY", "ORCH_DAEMON_DRY_RUN"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("pendingEscalations drops a closed/shipped board ticket's escalation", () => {
  const h = home();
  mkStream(h);
  const boardRepo = path.join(h, "boardrepo");
  fs.mkdirSync(path.join(boardRepo, ".opencode", "board", "tickets"), { recursive: true });
  fs.writeFileSync(path.join(boardRepo, ".opencode", "board", "tickets", "t1.json"), JSON.stringify({ id: "t1", stage: "shipped" }));
  const sp = path.join(sdir(h), "m6a.json");
  fs.writeFileSync(sp, JSON.stringify({ ...JSON.parse(fs.readFileSync(sp, "utf8")), repo: boardRepo }));
  const ddir = path.join(h, ".config", "orchestrator", "desk-daemon");
  fs.mkdirSync(ddir, { recursive: true });
  fs.writeFileSync(path.join(ddir, "escalations.jsonl"), JSON.stringify({ at: at(), stream: "m6a", key: "run:t1/worker-r1:done", reason: "senior /f" }) + "\n");
  const r = cli(h, ["daemon", "status"], { ORCH_NO_NOTIFY: "1" });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /escalations pending: 0/);
  // an open ticket's row still shows
  fs.writeFileSync(path.join(ddir, "escalations.jsonl"), JSON.stringify({ at: at(), stream: "m6a", key: "run:t9/worker-r1:done", reason: "blocked /x" }) + "\n");
  const r2 = cli(h, ["daemon", "status"], { ORCH_NO_NOTIFY: "1" });
  assert.match(r2.stdout, /escalations pending: 1/);
  assert.match(r2.stdout, /run:t9\/worker-r1:done blocked/);
});

// ---------------------------------------------------------------- session-driven guard (desk-live-guard)

const mkBoardTicket = (h, slug, over = {}) => {
  const repo = path.join(h, "boardrepo");
  fs.mkdirSync(path.join(repo, ".opencode", "board", "tickets"), { recursive: true });
  const t = { id: slug, stage: "working", rounds: [], signoffs: [], reopens: [], ...over };
  fs.writeFileSync(path.join(repo, ".opencode", "board", "tickets", `${slug}.json`), JSON.stringify(t));
  return repo;
};
const withDriver = (h, slug, driver) => {
  const tp = path.join(h, "reports", slug, "ticket.json");
  fs.writeFileSync(tp, JSON.stringify({ ...JSON.parse(fs.readFileSync(tp, "utf8")), driver }));
};
const restoreEnv = (saved, keys) => {
  for (const k of keys) {
    if (saved[k] === undefined) delete process.env[k];
    else process.env[k] = saved[k];
  }
};

test("session-driven (driver=session): a worker run-done is not dispatched to a critic", async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  withDriver(h, "t1", "session");
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out));
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    const first = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "session-driven", JSON.stringify(first));
    assert.match(first[0].detail, /driver=session/);
    // No spawn, no page, no ack: no findings file, no escalation, and the decision ack stays unresolved
    assert.ok(!fs.existsSync(path.join(h, "reports", "t1", "findings-r1.md")), "no critic findings written");
    assert.ok(!fs.existsSync(path.join(h, "reports", "t1", "critic-prompt-r1.md")), "no critic prompt written");
    const lines = inHome(h, () => readAckLines("m6a"));
    assert.ok(lines.some((l) => l.key === "run:t1/worker-r1:done" && !l.resolved), "the decision stays for when the session lets go");
    assert.ok(!lines.some((l) => l.key === "run:t1/worker-r1:done" && l.resolved), "nothing resolved");
    assert.ok(!fs.existsSync(path.join(h, ".config", "orchestrator", "desk-daemon", "escalations.jsonl")), "no page");
  } finally {
    restoreEnv(saved, Object.keys(DRY));
  }
});

test("session-driven (driver=session): a CHANGES_REQUESTED verdict is neither resumed nor merged", async () => {
  const h = home();
  mkStream(h);
  mkTicket(h);
  withDriver(h, "t1", "session");
  const runDir = path.join(h, "reports", "t1");
  const out = path.join(runDir, "worker-r1.md");
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(out, "done\n");
  fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\nBLAST RADIUS:\n- x\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(runDir, "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out, "worker", { session: "ses_W1" }));
    appendEvent("m6a", { key: "verdict:t1/worker-r1", kind: "verdict", run: "t1/worker-r1", at: at(), effective: "CHANGES_REQUESTED", senior: false, findings, reviewed_sha: "abc1234" });
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    const handled = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(handled.length, 2);
    for (const row of handled) assert.equal(row.outcome, "session-driven", JSON.stringify(handled));
    assert.ok(!fs.existsSync(path.join(runDir, "worker-r2.md")), "no resume out");
    assert.ok(!fs.existsSync(path.join(h, ".config", "orchestrator", "desk-daemon", "escalations.jsonl")), "no page");
  } finally {
    restoreEnv(saved, Object.keys(DRY));
  }
});

test("session-driven (native-critic round): no desk critic and no sweepVerdicts verdict", async () => {
  const h = home();
  mkStream(h);
  const runDir = path.join(h, "reports", "t1");
  fs.mkdirSync(runDir, { recursive: true });
  const findings = path.join(runDir, "findings-r1.md");
  const content = "VERDICT: APPROVED\nBLAST RADIUS:\n- none\n";
  fs.writeFileSync(findings, content);
  const sha = crypto.createHash("sha256").update(content).digest("hex");
  const repo = mkBoardTicket(h, "t1", {
    rounds: [{
      n: 1, at: at(), counted: true, worker: { outcome: "done" },
      critic: { source: "native", alias: "sonnet", model: "sonnet", free: false, free_source: "native:sonnet", critic_verdict: "APPROVED", effective: "APPROVED", reasons: [], findings_sha256: sha, receipt_sha256: null },
      reviewed_sha: "abc", cost: 0, senior_needed: false,
    }],
  });
  mkTicket(h, "t1", { repo }); // no driver field: the native round alone drives the guard
  const out = path.join(runDir, "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(runDir, "ticket.json"), "worker"));
    appendEvent("m6a", evDone("t1/worker-r1", out, "worker"));
    appendEvent("m6a", evQ("t1/findings-r1", findings, path.join(runDir, "ticket.json"), "critic"));
    appendEvent("m6a", evDone("t1/findings-r1", findings, "critic"));
  });
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" }); // not dry: prove no spawn happens even live
  try {
    const handled = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    const byKey = Object.fromEntries(handled.map((r) => [r.key, r.outcome]));
    assert.equal(byKey["run:t1/worker-r1:done"], "session-driven", JSON.stringify(handled));
    assert.equal(byKey["run:t1/findings-r1:done"], "session-driven", JSON.stringify(handled));
    assert.ok(!fs.existsSync(path.join(runDir, "findings-r2.md")), "no desk critic findings");
    assert.ok(!fs.existsSync(path.join(runDir, "critic-prompt-r2.md")), "no desk critic prompt");
    const keys = inHome(h, () => readEvents("m6a").map((e) => e.key));
    assert.ok(!keys.some((k) => k.startsWith("verdict:t1/findings-r1")), "no sweepVerdicts verdict");
  } finally {
    restoreEnv(saved, ["ORCH_NO_NOTIFY"]);
  }
});

test("held --by cc with a live held_session is still desk-driven (no driver, no native round)", async () => {
  const h = home();
  mkStream(h);
  const sp = path.join(sdir(h), "m6a.json");
  fs.writeFileSync(sp, JSON.stringify({ ...JSON.parse(fs.readFileSync(sp, "utf8")), held_by: "cc", held_session: "ses_live" }));
  mkTicket(h); // repo "" and no driver field: the claim alone must not stop the desk
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out));
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    const first = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, { by: "cc" }));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "critic", JSON.stringify(first));
    assert.match(first[0].line, /^critic r1/);
  } finally {
    restoreEnv(saved, Object.keys(DRY));
  }
});

test("unheld stream with a live assignment.session is still desk-driven", async () => {
  const h = home();
  mkStream(h);
  const repo = mkBoardTicket(h, "t1", { assignment: { session: "ses_live", owner: "o" } });
  mkTicket(h, "t1", { repo }); // no driver field, no rounds: assignment.session must not stop the desk
  const out = path.join(h, "reports", "t1", "worker-r1.md");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, path.join(h, "reports", "t1", "ticket.json")));
    appendEvent("m6a", evDone("t1/worker-r1", out));
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    const first = await inHome(h, () => driveOnce({ lastPoll: null, printed: new Set() }, {}));
    assert.equal(first.length, 1);
    assert.equal(first[0].outcome, "critic", JSON.stringify(first));
  } finally {
    restoreEnv(saved, Object.keys(DRY));
  }
});

test("doCritic refuses a findings path the board already hashed", async () => {
  const h = home();
  mkStream(h);
  const runDir = path.join(h, "reports", "t1");
  fs.mkdirSync(runDir, { recursive: true });
  const findings = path.join(runDir, "findings-r1.md");
  const content = "VERDICT: APPROVED\nBLAST RADIUS:\n- none\n";
  fs.writeFileSync(findings, content);
  const sha = crypto.createHash("sha256").update(content).digest("hex");
  const repo = mkBoardTicket(h, "t1", {
    rounds: [{
      n: 1, at: at(), counted: true, worker: { outcome: "done" },
      critic: { source: "receipt", alias: "critic", model: "m", free: true, free_source: "agent:critic", critic_verdict: "APPROVED", effective: "APPROVED", reasons: [], findings_sha256: sha, receipt_sha256: null },
      reviewed_sha: "abc", cost: 0, senior_needed: false,
    }],
  });
  mkTicket(h, "t1", { repo });
  const out = path.join(runDir, "worker-r1.md");
  const tp = path.join(runDir, "ticket.json");
  fs.writeFileSync(out, "done\n");
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/worker-r1", out, tp));
    appendEvent("m6a", evDone("t1/worker-r1", out));
    // A stored r1 decision replays against a file the board has since hashed (the 2026-11-27
    // shape: the session recorded the round itself, and the desk's replay must not overwrite it).
    appendAck("m6a", "run:t1/worker-r1:done", `ACTION critic ${tp} ${out} ${findings} 1`, { ticket: "t1" });
  });
  const saved = { ...process.env };
  Object.assign(process.env, DRY);
  try {
    // A stored decision replays through handleEvent (a stored ack leaves `unhandled`, so driveOnce
    // would not re-emit it — the replay shape is a direct handleEvent, like the spawn-failed test).
    const r = await inHome(h, () => handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(r.outcome, "findings-hashed", JSON.stringify(r));
    assert.equal(fs.readFileSync(findings, "utf8"), content, "the hashed file is unchanged");
    assert.ok(!fs.existsSync(path.join(runDir, "critic-prompt-r1.md")), "no critic prompt written");
    assert.equal(escLines(h).length, 1);
    assert.match(escLines(h)[0], /findings-hashed/);
    const r2 = await inHome(h, () => handleEvent("m6a", "run:t1/worker-r1:done", undefined));
    assert.equal(r2.outcome, "paged", "a replay of a paged key never re-pages");
    assert.equal(escLines(h).length, 1, "page is once-only");
  } finally {
    restoreEnv(saved, Object.keys(DRY));
  }
});

test("critic -alt retry refuses a board-hashed -alt target", { skip: process.platform === "win32" ? "POSIX stub" : false }, async () => {
  const h = home();
  mkStream(h);
  const runDir = path.join(h, "reports", "t1");
  fs.mkdirSync(runDir, { recursive: true });
  const tp = path.join(runDir, "ticket.json");
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(findings, "critic crashed, no verdict\n");
  const alt = path.join(runDir, "findings-r1-alt.md");
  const altContent = "VERDICT: APPROVED\nBLAST RADIUS:\n- none\n";
  fs.writeFileSync(alt, altContent);
  const sha = crypto.createHash("sha256").update(altContent).digest("hex");
  const repo = mkBoardTicket(h, "t1", {
    rounds: [{
      n: 1, at: at(), counted: true, worker: { outcome: "done" },
      critic: { source: "receipt", alias: "critic", model: "m", free: true, free_source: "agent:critic", critic_verdict: "APPROVED", effective: "APPROVED", reasons: [], findings_sha256: sha, receipt_sha256: null },
      reviewed_sha: "abc", cost: 0, senior_needed: false,
    }],
  });
  mkTicket(h, "t1", { repo });
  inHome(h, () => {
    appendEvent("m6a", evQ("t1/findings-r1", findings, tp, "critic"));
    appendEvent("m6a", evDone("t1/findings-r1", findings, "critic"));
  });
  const argvLog = path.join(h, "argv.log");
  const stub = path.join(h, "stub-oc-worker.mjs");
  fs.writeFileSync(stub, `import fs from "node:fs"; fs.appendFileSync(${JSON.stringify(argvLog)}, JSON.stringify(process.argv.slice(2)) + "\\n");\n`);
  const keys = ["ORCH_NO_NOTIFY", "ORCH_AWAIT_QUEUED_MS", "ORCH_OC_WORKER"];
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1", ORCH_AWAIT_QUEUED_MS: "300", ORCH_OC_WORKER: stub });
  const desk = await import(`../bin/desk.mjs?hashedalt=${Date.now()}`);
  try {
    const r = await inHome(h, async () => await desk.handleEvent("m6a", "run:t1/findings-r1:done", undefined));
    assert.equal(r.outcome, "findings-hashed", JSON.stringify(r));
    assert.ok(!fs.existsSync(argvLog), "no retry spawned");
    assert.equal(escLines(h).length, 1);
    assert.match(escLines(h)[0], /findings-hashed/);
  } finally {
    restoreEnv(saved, keys);
  }
});

for (const [name, board] of [
  ["ready", { stage: "ready" }],
  ["shipped", { stage: "shipped" }],
  ["signed-off", { stage: "working", signoffs: [{ by: "human", model: null, free: false, free_source: null, reviewed_sha: "abc1234", at: "2026-11-27T00:00:00.000Z", invalidated_by: null }] }],
]) {
  test(`doResume on a ${name} ticket does nothing (board-final)`, async () => {
    const h = home();
    mkStream(h);
    const repo = mkBoardTicket(h, "t1", board);
    mkTicket(h, "t1", { repo });
    const runDir = path.join(h, "reports", "t1");
    const out = path.join(runDir, "worker-r1.md");
    const findings = path.join(runDir, "findings-r1.md");
    fs.writeFileSync(out, "done\n");
    inHome(h, () => {
      appendEvent("m6a", evQ("t1/worker-r1", out, path.join(runDir, "ticket.json")));
      appendEvent("m6a", evDone("t1/worker-r1", out, "worker", { session: "ses_W1" }));
      appendEvent("m6a", { key: "verdict:t1/worker-r1", kind: "verdict", run: "t1/worker-r1", at: at(), effective: "CHANGES_REQUESTED", senior: false, findings, reviewed_sha: "abc1234" });
    });
    // Not dry: prove no spawn happens even live. The stub records any spawn that slips through.
    const argvLog = path.join(h, "argv.log");
    const stub = path.join(h, "stub-oc-worker.mjs");
    fs.writeFileSync(stub, `import fs from "node:fs"; fs.appendFileSync(${JSON.stringify(argvLog)}, JSON.stringify(process.argv.slice(2)) + "\\n");\n`);
    const keys = ["ORCH_NO_NOTIFY", "ORCH_AWAIT_QUEUED_MS", "ORCH_OC_WORKER"];
    const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
    Object.assign(process.env, { ORCH_NO_NOTIFY: "1", ORCH_AWAIT_QUEUED_MS: "300", ORCH_OC_WORKER: stub });
    const desk = await import(`../bin/desk.mjs?final-${name}=${Date.now()}`);
    try {
      const handled = await inHome(h, async () => await desk.driveOnce({ lastPoll: null, printed: new Set() }, {}));
      assert.ok(handled.length >= 1, JSON.stringify(handled));
      for (const row of handled) assert.equal(row.outcome, "board-final", JSON.stringify(handled));
      assert.ok(!fs.existsSync(argvLog), "no worker resumed, no critic spawned");
      assert.ok(!fs.existsSync(path.join(runDir, "worker-r2.md")), "no resume out written");
      assert.ok(!fs.existsSync(path.join(h, ".config", "orchestrator", "desk-daemon", "escalations.jsonl")), "no page");
    } finally {
      restoreEnv(saved, keys);
    }
  });
}

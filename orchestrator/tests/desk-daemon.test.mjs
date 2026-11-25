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
    assert.equal(alt[alt.indexOf("--fallback") + 1], "critic-alt,critic-nvidia,critic-free");
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
// critic-go,critic-alt,critic-free (never critic-free ahead of Nvidia).
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
    assert.equal(retry[retry.indexOf("--fallback") + 1], "critic-go,critic-alt,critic-free");
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

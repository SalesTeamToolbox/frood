import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { handleEvent, poll, readDaemonState, statusRows, runIsLive, lockPath, wakeHolder, watchInfo, latestVerdict } from "../bin/desk.mjs";
import { workerOutcome } from "../bin/outcome.mjs";
import { appendEvent, appendAck, orchRoot, readAckLines } from "../bin/handoff.mjs";
import { plan } from "../bin/install.mjs";
import { processStart } from "../bin/proc-tree.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "desk.mjs");
const require = createRequire(import.meta.url);
const CLEAN = [];
const SPAWNED = []; // only processes this file started are ever killed
// Captured at module load, before any test swaps the environment: the one directory a test must never resolve a
// lock path into, because the live desk watcher keeps its lock at <real home>/.config/orchestrator/desk-watch.lock.
const REAL_HOME = os.homedir();
after(() => {
  killAll();
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-desk-"));
  CLEAN.push(h);
  return h;
}
const sdir = (h) => path.join(h, ".config", "orchestrator", "streams");
function mkStream(h, name = "m6a", status = "active") {
  fs.mkdirSync(sdir(h), { recursive: true });
  fs.writeFileSync(
    path.join(sdir(h), `${name}.json`),
    JSON.stringify({ name, repo: "", plan: "", status, next: "ship T7", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: null, done_at: null }),
  );
}
// Run fn with process.env pointed at h (and optionally a fixed clock), restored afterwards: npm test shares one process.
// An async body keeps the env for the WHOLE body — the restore runs only once the returned promise settles — so a
// lockPath() called after an await still resolves inside h. (It used to restore on the promise returned by fn,
// which left ORCH_HOME unset for the rest of an async body and let the lock path fall back to the real home.)
function inHome(h, now, fn) {
  const saved = { ORCH_HOME: process.env.ORCH_HOME, ORCH_NOW_MS: process.env.ORCH_NOW_MS };
  process.env.ORCH_HOME = h;
  if (now !== undefined) process.env.ORCH_NOW_MS = String(now);
  const restore = () => {
    for (const [k, v] of Object.entries(saved)) {
      if (v === undefined) delete process.env[k];
      else process.env[k] = v;
    }
  };
  // The swap must have taken: if orchRoot() still resolves to the real home, refuse before fn can touch anything.
  if (path.resolve(orchRoot()) === path.resolve(REAL_HOME)) {
    restore();
    throw new Error("orchRoot resolved to the real home — refusing");
  }
  let out;
  try {
    out = fn();
  } catch (e) {
    restore();
    throw e;
  }
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
// The lock dir this test's temp home owns (mirrors lockPath(), but built from h and never from the ambient env).
const lockDirOf = (h) => path.join(h, ".config", "orchestrator", "desk-watch.lock");
// cwd: h — `status` lists tickets from the board of the repo it runs in (ticketSessions(process.cwd())); from the real
// checkout every live ticket on the real board leaked into the expected output.
const cli = (h, args, extraEnv = {}) => spawnSync(process.execPath, [BIN, ...args], { cwd: h, env: { ...process.env, ORCH_HOME: h, WORKER_SLOTS: "3", ...extraEnv }, encoding: "utf8", timeout: 60000 });
const queued = (run, pid, pid_start, at = new Date().toISOString()) => ({ key: `run:${run}:queued`, kind: "queued", at, run, out: `/x/${run}.md`, pid, pid_start, agent: "worker", ticket: "/x/ticket.json" });
const eventsOf = (h, name = "m6a") =>
  fs.readFileSync(path.join(sdir(h), `${name}.events.jsonl`), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
const ctx = (extra = {}) => {
  const lines = [];
  return { interval: 30, lastPoll: null, printed: new Set(), out: (l) => lines.push(l), err: () => {}, lines, ...extra };
};
const within = (promise, ms, what) => Promise.race([promise, new Promise((_, rej) => setTimeout(() => rej(new Error(`timed out: ${what}`)), ms))]);
const killAll = () => {
  for (const p of SPAWNED.splice(0)) {
    try {
      process.kill(p.pid);
    } catch {}
  }
};
const waitFor = async (fn, ms = 20000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const v = fn();
    if (v) return v;
    await new Promise((r) => setTimeout(r, 100));
  }
  throw new Error("timed out waiting");
};

// ---------------------------------------------------------------- T8 fixtures (ticket.json, events, temp git repos)

const HANDOFF = path.join(HERE, "..", "bin", "handoff.mjs");
const handoff = (h, args) => spawnSync(process.execPath, [HANDOFF, ...args], { env: { ...process.env, ORCH_HOME: h }, encoding: "utf8" });
const runDirOf = (h, ticket = "t8") => path.join(h, "reports", ticket);
const fwd = (p) => p.replace(/\\/g, "/"); // desk prints and stores forward slashes on every platform

// ticket.json lives in the run dir (= dirname(mandate)) and never changes once written (M7).
// `closed: true` models a ticket whose worktree was removed after the merge (no `.git` entry: desk's closed-ticket
// check is a file test); every other ticket's worktree gets a placeholder `.git` so it reads as open.
function mkTicket(runDir, over = {}) {
  fs.mkdirSync(runDir, { recursive: true });
  const { closed, ...rest } = over;
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
    ...rest,
  };
  if (!closed) {
    fs.mkdirSync(t.worktree, { recursive: true });
    const dot = path.join(t.worktree, ".git");
    if (!fs.existsSync(dot)) fs.writeFileSync(dot, "gitdir: placeholder\n");
  }
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify(t));
  return t;
}
const evQueued = (run, runDir, agent = "worker", over = {}) => ({
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
// A fresh home + stream + run dir + ticket.json, the fixture every step/verdict test starts from.
function t8Stream(name = "s1", ticket = "t8") {
  const h = home();
  mkStream(h, name);
  const runDir = runDirOf(h, ticket);
  const t = mkTicket(runDir);
  return { h, name, runDir, ticket: t };
}
const cliLines = (h, args, extraEnv) => {
  const r = cli(h, args, extraEnv);
  return { ...r, lines: r.stdout.split("\n").filter(Boolean) };
};
// A repo where `main` is behind `feat` by one commit (ff possible), for merge-check.
const gitRepo = () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-git-"));
  CLEAN.push(dir);
  const g = (...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();
  g("init", "-b", "main");
  g("config", "user.email", "t8@example.com");
  g("config", "user.name", "t8");
  fs.writeFileSync(path.join(dir, "a.txt"), "a\n");
  g("add", "a.txt");
  g("commit", "-m", "base");
  g("checkout", "-b", "feat");
  fs.appendFileSync(path.join(dir, "a.txt"), "b\n");
  g("add", "a.txt");
  g("commit", "-m", "feature");
  return { dir, g, head: g("rev-parse", "HEAD") };
};

test("workerOutcome: the copied rules plus not_allowed and blocked", () => {
  assert.equal(workerOutcome({ exit: 0, out: "/x", first_line: "RESULT: DONE" }), "done");
  assert.equal(workerOutcome({ exit: "model-not-allowed" }), "not_allowed");
  assert.equal(workerOutcome({ exit: "model-unresolvable" }), "not_allowed");
  assert.equal(workerOutcome({ exit: 0, out: "/x", first_line: "RESULT: BLOCKED: timeout after 3 min" }), "blocked");
  assert.equal(workerOutcome({ exit: 0, out: "/x", first_line: "RESULT: BLOCKED: question — which?" }), "blocked_question");
  assert.equal(workerOutcome({ exit: 5, out: null, first_line: "" }), "error");
  assert.equal(workerOutcome({ exit: "timeout" }), "timeout");
  assert.equal(workerOutcome({ exit: "no-healthy-pool" }), "no_pool");
  assert.equal(workerOutcome({ exit: 0, out: null }), "no_output");
});

test("dead detection: a gone pid gets exactly one run-dead; a live pid with a matching start gets none", () => {
  const h = home();
  mkStream(h);
  inHome(h, undefined, () => {
    appendEvent("m6a", queued("worker-r1", 999999, "2026-01-01T00:00:00.000Z"));
    appendEvent("m6a", queued("worker-r2", process.pid, processStart(process.pid)));
    const c = ctx();
    poll(c);
    poll(c);
    assert.deepEqual(eventsOf(h).filter((e) => e.kind === "run-dead").map((e) => e.key), ["run:worker-r1:dead"]);
    assert.deepEqual(c.lines, ["EVENT m6a run:worker-r1:dead run-dead -"]);
  });
});

test("dead detection: a live pid with a different start is dead; a null pid_start trusts a live pid (M10)", () => {
  const h = home();
  mkStream(h);
  inHome(h, undefined, () => {
    appendEvent("m6a", queued("worker-r1", process.pid, "2001-01-01T00:00:00.000Z"));
    appendEvent("m6a", queued("worker-r2", process.pid, null));
    appendEvent("m6a", queued("worker-r3", 999999, null));
    poll(ctx());
    assert.deepEqual(eventsOf(h).filter((e) => e.kind === "run-dead").map((e) => e.run).sort(), ["worker-r1", "worker-r3"]);
    assert.equal(runIsLive({ pid: process.pid, pid_start: null }), true);
  });
});

test("a sleep gap (now - lastPoll > 5 x interval) skips dead detection for that poll", () => {
  const h = home();
  mkStream(h);
  const t0 = Date.parse("2026-11-13T10:00:00Z");
  inHome(h, t0 + 6 * 30_000, () => {
    appendEvent("m6a", queued("worker-r1", 999999, "2026-01-01T00:00:00.000Z"));
    const c = ctx({ lastPoll: t0 });
    poll(c);
    assert.equal(eventsOf(h).filter((e) => e.kind === "run-dead").length, 0, "the host slept: nothing is declared dead");
    poll(c); // this poll is 0 s after the last: detection runs again
    assert.equal(eventsOf(h).filter((e) => e.kind === "run-dead").length, 1);
  });
});

test("watch --once: only EVENT lines, queued never printed, a second run replays, an ack silences", () => {
  const h = home();
  mkStream(h);
  mkStream(h, "parked-one", "parked");
  inHome(h, undefined, () => {
    appendEvent("m6a", queued("worker-r1", process.pid, processStart(process.pid)));
    appendEvent("m6a", { key: "run:worker-r1:done", kind: "run-done", run: "worker-r1", out: "/x/worker-r1.md", agent: "worker", exit: 0, outcome: "done", session: "ses_1" });
    appendEvent("m6a", { key: "verdict:worker-r1", kind: "verdict", run: "worker-r1", effective: "APPROVED", senior: false, findings: "/x/f.md", reviewed_sha: "abc" });
    appendEvent("parked-one", { key: "run:p:done", kind: "run-done", run: "p", agent: "worker", exit: 0, outcome: "done", session: null });
  });
  const first = cli(h, ["watch", "--events", "--once"]);
  assert.equal(first.status, 0, first.stderr);
  const lines = first.stdout.split("\n").filter(Boolean);
  assert.deepEqual(lines, ["EVENT m6a run:worker-r1:done run-done done", "EVENT m6a verdict:worker-r1 verdict APPROVED"]);
  for (const l of lines) assert.match(l, /^EVENT /);
  assert.equal(cli(h, ["watch", "--events", "--once"]).stdout, first.stdout, "a new watcher replays unhandled events");
  inHome(h, undefined, () => {
    appendAck("m6a", "run:worker-r1:done", "ACTION critic");
    appendAck("m6a", "verdict:worker-r1", "DONE");
  });
  assert.equal(cli(h, ["watch", "--events", "--once"]).stdout, "");
});

test("an unreadable events line is skipped with a stderr line; the rest still prints", () => {
  const h = home();
  mkStream(h);
  const good = JSON.stringify({ key: "run:w:done", kind: "run-done", at: new Date().toISOString(), run: "w", outcome: "done" });
  fs.writeFileSync(path.join(sdir(h), "m6a.events.jsonl"), `{not json\n${good}\n`);
  const r = cli(h, ["watch", "--events", "--once"]);
  assert.equal(r.status, 0);
  assert.equal(r.stdout, "EVENT m6a run:w:done run-done done\n");
  assert.match(r.stderr, /m6a\.events\.jsonl line 1 is unreadable/);
});

test("watch --until-event: one unhandled event prints and exits 0", () => {
  const h = home();
  mkStream(h);
  inHome(h, undefined, () => {
    appendEvent("m6a", { key: "run:worker-r1:done", kind: "run-done", run: "worker-r1", out: "/x/worker-r1.md", agent: "worker", exit: 0, outcome: "done", session: "ses_1" });
  });
  const r = cli(h, ["watch", "--events", "--until-event", "1", "--interval", "0.1"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /^EVENT m6a run:worker-r1:done run-done done$/m);
});

test("watch --until-event: no events exits 4", () => {
  const h = home();
  mkStream(h);
  const r = cli(h, ["watch", "--events", "--until-event", "1", "--interval", "0.1"]);
  assert.equal(r.status, 4, r.stderr);
  assert.equal(r.stdout, "");
});

test("watch --until-event: lock held by live pid exits 3", async () => {
  const h = home();
  mkStream(h);
  const env = { ...process.env, ORCH_HOME: h };
  const watcher = (...flags) => {
    const p = spawn(process.execPath, [BIN, "watch", "--events", "--interval", "0.3", ...flags], { env, stdio: "ignore", windowsHide: true });
    p.unref();
    SPAWNED.push(p);
    return p;
  };
  try {
    await inHome(h, undefined, async () => {
      const ownerFile = path.join(lockPath(), "owner");
      const owner = () => {
        try {
          return JSON.parse(fs.readFileSync(ownerFile, "utf8"));
        } catch {
          return null;
        }
      };
      const a = watcher();
      assert.ok(await waitFor(owner), "lock owner file appeared");
      // Now try another watch with --until-event
      const r = cli(h, ["watch", "--events", "--until-event", "1", "--interval", "0.1"]);
      assert.equal(r.status, 3, r.stderr);
      assert.match(r.stderr, new RegExp(`desk-watch: running as pid ${a.pid} since `));
    });
  } finally {
    // The watcher is killed by the test cleanup (SPAWNED)
  }
});

test("watch --until-event rejects --once and zero/negative seconds", () => {
  const h = home();
  mkStream(h);
  const r1 = cli(h, ["watch", "--events", "--once", "--until-event", "1"]);
  assert.equal(r1.status, 2);
  assert.match(r1.stderr, /--until-event cannot be combined with --once/);
  const r2 = cli(h, ["watch", "--events", "--until-event", "0"]);
  assert.equal(r2.status, 2);
  assert.match(r2.stderr, /--until-event must be a positive number/);
  const r3 = cli(h, ["watch", "--events", "--until-event", "-1"]);
  assert.equal(r3.status, 2);
  assert.match(r3.stderr, /--until-event must be a positive number/);
});

test("usage: watch needs --events; an unknown flag or command exits 2", () => {
  const h = home();
  assert.equal(cli(h, ["watch"]).status, 2);
  assert.equal(cli(h, ["watch", "--events", "--nope"]).status, 2);
  assert.equal(cli(h, ["bogus"]).status, 2);
});

test("lock: a second watcher exits 3; a fenced watcher exits 0; --takeover kills a spawned dummy owner", { timeout: 90_000 }, async () => {
  const h = home();
  mkStream(h);
  const env = { ...process.env, ORCH_HOME: h };
  const watcher = (...flags) => {
    const p = spawn(process.execPath, [BIN, "watch", "--events", "--interval", "0.3", ...flags], { env, stdio: "ignore", windowsHide: true });
    p.unref();
    SPAWNED.push(p);
    return p;
  };
  try {
    await inHome(h, undefined, async () => {
    const ownerFile = path.join(lockPath(), "owner");
    const owner = () => {
      try {
        return JSON.parse(fs.readFileSync(ownerFile, "utf8"));
      } catch {
        return null;
      }
    };
    const a = watcher();
    assert.equal((await waitFor(owner)).pid, a.pid);
    const second = cli(h, ["watch", "--events", "--interval", "30"]); // a wide freshness window: no timing dependence
    assert.equal(second.status, 3);
    assert.match(second.stderr, new RegExp(`desk-watch: running as pid ${a.pid} since `));

    // fenced: the lock record now names someone else; the watcher sees it on its next poll and exits 0
    const exited = new Promise((res) => a.on("exit", (code) => res(code)));
    const foreign = JSON.stringify({ pid: 1, pid_start: null, at: new Date().toISOString(), token: "someone-else" });
    fs.writeFileSync(ownerFile, foreign);
    const again = setInterval(() => {
      try {
        fs.writeFileSync(ownerFile, foreign); // the new owner keeps its record in place, whatever the old watcher is doing
      } catch {}
    }, 200);
    try {
      assert.equal(await within(exited, 30000, "fenced watcher exit"), 0);
    } finally {
      clearInterval(again);
    }
    fs.rmSync(lockDirOf(h), { recursive: true, force: true });

    // live but stale owner, no --takeover: the lock is taken and the old owner fences itself
    const old = watcher();
    await waitFor(() => owner()?.pid === old.pid);
    const oldExited = new Promise((res) => old.on("exit", (code) => res(code)));
    fs.writeFileSync(ownerFile, JSON.stringify({ pid: old.pid, pid_start: processStart(old.pid), at: "2020-01-01T00:00:00.000Z", token: old.pid + "-stale" }));
    const fresh = watcher();
    assert.equal((await waitFor(() => (owner()?.pid === fresh.pid ? owner() : null))).pid, fresh.pid);
    assert.equal(await within(oldExited, 20000, "stale owner fences itself"), 0);
    fresh.kill();
    await new Promise((r) => setTimeout(r, 300));
    fs.rmSync(lockDirOf(h), { recursive: true, force: true });

    // takeover: the owner is a dummy process this test spawned, and it is the only thing that is killed
    const victim = spawn(process.execPath, ["-e", "setInterval(()=>{},1000)"], { stdio: "ignore", windowsHide: true });
    SPAWNED.push(victim);
    const victimGone = new Promise((res) => victim.on("exit", res));
    fs.mkdirSync(lockDirOf(h), { recursive: true });
    // the record is made stale on purpose (an old `at`), so the kill must not depend on freshness
    fs.writeFileSync(ownerFile, JSON.stringify({ pid: victim.pid, pid_start: processStart(victim.pid), at: "2020-01-01T00:00:00.000Z", token: "victim" }));
    const t = watcher("--takeover");
    await within(victimGone, 20000, "dummy owner not killed");
    assert.equal((await waitFor(() => (owner()?.pid === t.pid ? owner() : null))).pid, t.pid);
    });
  } finally {
    killAll(); // never leave a watcher behind, pass or fail
  }
});

test("status: watch line first, then rows per stream and run; --json carries streams + watch", () => {
  const h = home();
  const out = cli(h, ["status"]).stdout.split("\n").filter(Boolean);
  assert.match(out[0], /^watch none — no desk watcher holds the lock$/);
  assert.match(out[1], /^slots \d+\/\d+ \(fixed\)$/);
  mkStream(h);
  mkStream(h, "old", "done");
  const t0 = Date.parse("2026-11-13T10:00:00Z");
  const at = (min) => new Date(t0 - min * 60000).toISOString();
  inHome(h, undefined, () => {
    appendEvent("m6a", queued("worker-r1", process.pid, processStart(process.pid), at(12)));
    appendEvent("m6a", queued("worker-r2", 999999, "2026-01-01T00:00:00.000Z", at(5)));
    appendEvent("m6a", { key: "run:worker-r2:dead", kind: "run-dead", run: "worker-r2", at: at(0) });
    appendEvent("m6a", queued("worker-r3", 999999, "2026-01-01T00:00:00.000Z", at(3)));
    appendEvent("m6a", { key: "run:worker-r3:done", kind: "run-done", run: "worker-r3", at: at(0), agent: "worker", exit: 0, outcome: "done", session: null });
    appendEvent("m6a", { key: "verdict:worker-r3", kind: "verdict", run: "worker-r3", at: at(0), effective: "CHANGES_REQUESTED", senior: false, findings: "/f", reviewed_sha: "a" });
  });
  const env = { ORCH_NOW_MS: String(t0) };
  const lines = cli(h, ["status"], env).stdout.split("\n").filter(Boolean);
  assert.match(lines[0], /^watch none/);
  assert.match(lines[1], /^slots \d+\/\d+ \(fixed\)$/);
  assert.match(lines[2], /^m6a {2}pending {2}next: ship T7 {2}unhandled=3$/); // run-dead, run-done, verdict; queued is not counted
  assert.equal(lines[3], "  worker-r1  worker  running  12m");
  assert.equal(lines[4], "  worker-r2  worker  dead  5m");
  assert.equal(lines[5], "  worker-r3  worker  verdict CHANGES_REQUESTED  3m");
  assert.equal(lines.length, 6, "watch line + slots line + stream + 3 runs; a done stream is not listed");
  const j = JSON.parse(cli(h, ["status", "--json"], env).stdout);
  assert.deepEqual(j.watch, null, "no lock dir means no watch owner");
  assert.deepEqual(j.streams.map((s) => s.name), ["m6a"]);
  assert.deepEqual(j.streams[0].runs.map((x) => [x.run, x.state, x.age_min]), [["worker-r1", "running", 12], ["worker-r2", "dead", 5], ["worker-r3", "verdict", 3]]);
  assert.deepEqual(inHome(h, t0, () => statusRows()), j.streams);
  assert.ok(Number.isInteger(j.slots.allowed) && Number.isInteger(j.slots.max), "json slots object present");
});

test("status watch line: live names harness + session; stale names the reason and the remedy", async () => {
  const h = home();
  mkStream(h);
  const ownerFile = path.join(lockDirOf(h), "owner");
  const now = Date.now();
  // live: this very process with a fresh heartbeat and recorded identity
  fs.mkdirSync(lockDirOf(h), { recursive: true });
  fs.writeFileSync(
    ownerFile,
    JSON.stringify({ pid: process.pid, pid_start: processStart(process.pid), at: new Date(now - 5000).toISOString(), token: "self", by: "oc", session: "ses_live1" }),
  );
  const live = inHome(h, now, () => watchInfo());
  assert.equal(live.state, "live");
  assert.equal(live.by, "oc");
  assert.equal(live.session, "ses_live1");
  assert.equal(live.verified, true);
  const liveLines = cli(h, ["status"], { ORCH_NOW_MS: String(now) }).stdout.split("\n").filter(Boolean);
  assert.match(liveLines[0], /^watch live pid=\d+ \(by oc, session ses_live1\) heartbeat \ds ago \(start verified\)$/);
  assert.deepEqual(JSON.parse(cli(h, ["status", "--json"], { ORCH_NOW_MS: String(now) }).stdout).watch.state, "live");
  // stale, owner gone: the pid belongs to nothing (a spawned dummy, killed and reaped)
  const gone = spawn(process.execPath, ["-e", "setTimeout(()=>{},1000)"], { stdio: "ignore", windowsHide: true });
  const goneExit = new Promise((res) => gone.on("exit", res));
  await goneExit; // reaped: the pid is gone for good (a recycled pid would fail the start match anyway)
  const oldAt = new Date(now - 3600000).toISOString();
  fs.writeFileSync(ownerFile, JSON.stringify({ pid: gone.pid, pid_start: "2020-01-01T00:00:00.000Z", at: oldAt, token: "gone", by: "cc" }));
  const stale = inHome(h, now, () => watchInfo());
  assert.equal(stale.state, "stale");
  assert.equal(stale.reason, "owner process gone");
  const staleLines = cli(h, ["status"], { ORCH_NOW_MS: String(now) }).stdout.split("\n").filter(Boolean);
  assert.match(staleLines[0], /^watch stale pid=\d+ \(by cc\) last heartbeat 1h ago \(owner process gone\) — safe to take/);
  // stale, pid recycled: this process alive under a wrong start
  fs.writeFileSync(ownerFile, JSON.stringify({ pid: process.pid, pid_start: "2020-01-01T00:00:00.000Z", at: oldAt, token: "recycled" }));
  assert.equal(inHome(h, now, () => watchInfo().reason), "pid recycled (start mismatch)");
});

test("watch records owner identity; exit 3 names it; a dead owner is replaced without --takeover", { timeout: 90_000 }, async () => {
  const h = home();
  mkStream(h);
  const env = { ...process.env, ORCH_HOME: h, OPENCODE_SESSION_ID: "ses_owner1" };
  const ownerFile = path.join(lockDirOf(h), "owner");
  const watcher = (...flags) => {
    const p = spawn(process.execPath, [BIN, "watch", "--events", "--by", "oc", "--interval", "0.3", ...flags], { env, stdio: "ignore", windowsHide: true });
    p.unref();
    SPAWNED.push(p);
    return p;
  };
  const owner = () => {
    try {
      return JSON.parse(fs.readFileSync(ownerFile, "utf8"));
    } catch {
      return null;
    }
  };
  try {
    const a = watcher();
    assert.equal((await waitFor(owner)).pid, a.pid);
    assert.equal(owner().by, "oc");
    assert.equal(owner().session, "ses_owner1");
    const second = cli(h, ["watch", "--events", "--by", "oc", "--interval", "30"], { OPENCODE_SESSION_ID: "ses_second" });
    assert.equal(second.status, 3);
    assert.match(second.stderr, new RegExp(`desk-watch: running as pid ${a.pid} since .* \\(by oc, session ses_owner1\\)`));
    a.kill();
    await new Promise((r) => a.once("exit", r));
    // the killed watcher is reaped (its pid is gone): the next watch takes the lock without --takeover
    fs.writeFileSync(ownerFile, JSON.stringify({ pid: a.pid, pid_start: owner().pid_start, at: "2020-01-01T00:00:00.000Z", token: "dead", by: "oc" }));
    const r = cli(h, ["watch", "--events", "--by", "oc", "--until-event", "1", "--interval", "0.1"]);
    assert.equal(r.status, 4, r.stderr);
    assert.notEqual(owner().pid, a.pid, "the dead owner's lock was replaced");
  } finally {
    killAll(); // never leave a watcher behind, pass or fail
  }
});

// ---------------------------------------------------------------- T8 step / verdict / merge-check

test("step: every run-done and run-dead row prints its one line", () => {
  const { h, name, runDir } = t8Stream("steps");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    appendEvent(name, evQueued("worker-r2", runDir));
    appendEvent(name, evDone("worker-r2", runDir, { outcome: "blocked_question", exit: 3 }));
    ["blocked", "timeout", "no_output", "no_pool", "not_allowed", "error"].forEach((outcome, i) => {
      const run = `worker-f${i}`;
      appendEvent(name, evQueued(run, runDir));
      appendEvent(name, evDone(run, runDir, { outcome, exit: outcome === "error" ? 5 : "timeout" }));
    });
    appendEvent(name, evQueued("critic-r1", runDir, "critic"));
    appendEvent(name, evDone("critic-r1", runDir, { agent: "critic" }));
    appendEvent(name, evQueued("worker-r9", runDir));
    appendEvent(name, { key: "run:worker-r9:dead", kind: "run-dead", run: "worker-r9", out: path.join(runDir, "worker-r9.md") });
    appendEvent(name, { key: "note:hello", kind: "note" });
  });
  const step = (key) => {
    const r = cliLines(h, ["step", name, key]);
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.lines.length, 1, `exactly one line for ${key}`);
    return r.lines[0];
  };
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(step("run:worker-r1:done"), `ACTION critic ${ticketJson} ${fwd(path.join(runDir, "worker-r1.md"))} ${fwd(path.join(runDir, "findings-r1.md"))} 1`);
  assert.equal(step("run:worker-r2:done"), `ESCALATE question ${fwd(path.join(runDir, "worker-r2.md"))}`);
  ["blocked", "timeout", "no_output", "no_pool", "not_allowed", "error"].forEach((outcome, i) => {
    assert.equal(step(`run:worker-f${i}:done`), `ESCALATE worker-${outcome} ${fwd(path.join(runDir, `worker-f${i}.md`))}`);
  });
  assert.equal(step("run:critic-r1:done"), `ESCALATE agent-critic ${fwd(path.join(runDir, "critic-r1.md"))}`);
  assert.equal(step("run:worker-r9:dead"), `ESCALATE run-dead ${fwd(path.join(runDir, "worker-r9.md"))}`);
  assert.equal(step("note:hello"), "ESCALATE unknown-event note:hello");
  // every printed line is copy-pasteable on any platform: no win32 backslashes, stored acks hold the same line
  for (const l of inHome(h, undefined, () => readAckLines(name).map((x) => x.action))) {
    assert.doesNotMatch(l, /\\/, `stored line has a backslash: ${l}`);
  }
});

test("step: exit 2 for usage, unknown stream and unknown key; no usable ticket.json is ESCALATE no-ticket", () => {
  const { h, name, runDir } = t8Stream("noticket");
  assert.equal(cli(h, ["step"]).status, 2);
  assert.equal(cli(h, ["step", name]).status, 2);
  assert.equal(cli(h, ["step", "nope", "run:x:done"]).status, 2, "unknown stream");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
  });
  assert.equal(cli(h, ["step", name, "run:missing:done"]).status, 2, "key not in the events");
  fs.writeFileSync(path.join(runDir, "ticket.json"), "{not json");
  assert.equal(cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0], `ESCALATE no-ticket ${fwd(path.join(runDir, "ticket.json"))}`);

  // a queued event with no `ticket` field at all: the key is the only thing to name
  const s2 = t8Stream("noticket2");
  inHome(s2.h, undefined, () => {
    appendEvent(s2.name, { key: "run:worker-r1:queued", kind: "queued", run: "worker-r1", out: path.join(s2.runDir, "worker-r1.md"), pid: 1, pid_start: null, agent: "worker" });
    appendEvent(s2.name, evDone("worker-r1", s2.runDir));
  });
  assert.equal(cliLines(s2.h, ["step", s2.name, "run:worker-r1:done"]).lines[0], "ESCALATE no-ticket run:worker-r1:done");
});

test("step: verdict rows — round after two resumes, exhausted, no-session, senior, merge, invalid", () => {
  const OC_WORKER = fileURLToPath(new URL("../bin/oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
  // A legacy, un-prefixed run id (`worker-r1`): its resume keeps the legacy shape (no `<ticket>/` prefix).
  const resume = (stream, dir, round) =>
    `ACTION resume-worker node ${OC_WORKER} --agent worker --dir ${fwd(dir)} ` +
    `--prompt ${fwd(path.join(dir, `findings-r${round}.md`))} --report ${fwd(path.join(dir, "report.md"))} ` +
    `--out ${fwd(path.join(dir, `worker-r${round + 1}.md`))} --session ses_1 --stream ${stream}`;
  const finishRun = (h, stream, dir, run, round, over = {}) =>
    inHome(h, undefined, () => {
      appendEvent(stream, evQueued(run, dir));
      appendEvent(stream, evDone(run, dir));
      appendEvent(stream, evVerdict(run, dir, { findings: path.join(dir, `findings-r${round}.md`), ...over }));
    });

  // round 1 -> resume worker-r2, round 2 -> resume worker-r3, round 3 (= max_rounds) -> exhausted
  const { h, name, runDir } = t8Stream("rounds");
  finishRun(h, name, runDir, "worker-r1", 1, { effective: "CHANGES_REQUESTED" });
  assert.equal(cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0], resume(name, runDir, 1), "round 1");
  finishRun(h, name, runDir, "worker-r2", 2, { effective: "CHANGES_REQUESTED" });
  assert.equal(cliLines(h, ["step", name, "verdict:worker-r2"]).lines[0], resume(name, runDir, 2), "round 2 after one resume");
  finishRun(h, name, runDir, "worker-r3", 3, { effective: "CHANGES_REQUESTED" });
  assert.equal(cliLines(h, ["step", name, "verdict:worker-r3"]).lines[0], `ESCALATE rounds-exhausted ${fwd(path.join(runDir, "findings-r3.md"))}`);
  // an APPROVED at round 3 is still a senior review (> 2 rounds)
  finishRun(h, name, runDir, "worker-r4", 4);
  assert.equal(cliLines(h, ["step", name, "verdict:worker-r4"]).lines[0], `ESCALATE senior ${fwd(path.join(runDir, "findings-r4.md"))}`);

  // CHANGES_REQUESTED with no worker session to resume
  const noSession = t8Stream("nosession");
  inHome(noSession.h, undefined, () => {
    appendEvent(noSession.name, evQueued("worker-r1", noSession.runDir));
    appendEvent(noSession.name, evDone("worker-r1", noSession.runDir, { session: null }));
    appendEvent(noSession.name, evVerdict("worker-r1", noSession.runDir, { effective: "CHANGES_REQUESTED" }));
  });
  assert.equal(
    cliLines(noSession.h, ["step", noSession.name, "verdict:worker-r1"]).lines[0],
    `ESCALATE no-session ${fwd(path.join(noSession.runDir, "worker-r1.md"))}`,
  );

  // APPROVED with senior, APPROVED plain, INVALID
  const sv = t8Stream("verdict-rows");
  inHome(sv.h, undefined, () => {
    appendEvent(sv.name, evQueued("worker-r1", sv.runDir));
    appendEvent(sv.name, evDone("worker-r1", sv.runDir));
    appendEvent(sv.name, evVerdict("worker-r1", sv.runDir, { senior: true }));
    appendEvent(sv.name, evQueued("worker-r2", sv.runDir));
    appendEvent(sv.name, evDone("worker-r2", sv.runDir));
    appendEvent(sv.name, evVerdict("worker-r2", sv.runDir));
    appendEvent(sv.name, evQueued("worker-r3", sv.runDir));
    appendEvent(sv.name, evDone("worker-r3", sv.runDir));
    appendEvent(sv.name, evVerdict("worker-r3", sv.runDir, { effective: "INVALID", findings: path.join(sv.runDir, "findings-r3.md") }));
  });
  assert.equal(cliLines(sv.h, ["step", sv.name, "verdict:worker-r1"]).lines[0], `ESCALATE senior ${fwd(path.join(sv.runDir, "findings-r1.md"))}`);
  assert.equal(cliLines(sv.h, ["step", sv.name, "verdict:worker-r2"]).lines[0], `ESCALATE merge ${fwd(path.join(sv.runDir, "ticket.json"))} abc`);
  assert.equal(cliLines(sv.h, ["step", sv.name, "verdict:worker-r3"]).lines[0], `ESCALATE critic-invalid ${fwd(path.join(sv.runDir, "findings-r3.md"))}`);

  // ticket.senior_trigger makes even a first-round APPROVED a senior review
  const st = t8Stream("senior-trigger");
  mkTicket(st.runDir, { senior_trigger: "guarded path" });
  inHome(st.h, undefined, () => {
    appendEvent(st.name, evQueued("worker-r1", st.runDir));
    appendEvent(st.name, evDone("worker-r1", st.runDir));
    appendEvent(st.name, evVerdict("worker-r1", st.runDir));
  });
  assert.equal(cliLines(st.h, ["step", st.name, "verdict:worker-r1"]).lines[0], `ESCALATE senior ${fwd(path.join(st.runDir, "findings-r1.md"))}`);

  // the round counts only acks that carry this ticket's slug
  const so = t8Stream("other-ticket");
  inHome(so.h, undefined, () => {
    appendEvent(so.name, evQueued("worker-r1", so.runDir));
    appendEvent(so.name, evDone("worker-r1", so.runDir));
    appendEvent(so.name, evVerdict("worker-r1", so.runDir, { effective: "CHANGES_REQUESTED" }));
    appendAck(so.name, "run:someone-else:done", "ACTION resume-worker node x --out /x/worker-r9.md --session s", { ticket: "other" });
  });
  assert.equal(cliLines(so.h, ["step", so.name, "verdict:worker-r1"]).lines[0], resume(so.name, so.runDir, 1), "another ticket's resume does not count");
});

test("step: worker-nvidia timed-out run resumes with --role worker --session, fresh out + mandate prompt", () => {
  const { h, name, runDir } = t8Stream("nvidia-timeout");
  const OC_WORKER = fileURLToPath(new URL("../bin/oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir, { agent: "worker-nvidia" }));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "worker-nvidia", outcome: "timeout", session: "ses_nvidia" }));
  });
  const line = cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0];
  assert.equal(
    line,
    `ACTION resume-worker node ${OC_WORKER} --role worker --dir ${fwd(runDir)} --prompt ${fwd(path.join(runDir, "mandate.md"))} --report ${fwd(path.join(runDir, "report.md"))} --out ${fwd(path.join(runDir, "worker-r2.md"))} --session ses_nvidia --stream ${name}`,
  );
  assert.ok(!line.includes("--fallback"), "no hand-typed paid-first fallback");
  assert.ok(!line.includes("worker-prompt-r1"), "prompt is the Mandate, never the unwritten worker-prompt-r1.md");
});

test("step: a worker-nvidia run that escaped its worktree pages the owner, never auto-resumes", () => {
  const { h, name, runDir } = t8Stream("nvidia-escaped");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir, { agent: "worker-nvidia" }));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "worker-nvidia", outcome: "error", exit: "escaped-worktree", session: "ses_nvidia" }));
  });
  const line = cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0];
  assert.equal(line, `ESCALATE worktree-escape ${fwd(path.join(runDir, "worker-r1.md"))}`);
  assert.ok(!line.includes("resume-worker"), "an escaped run is never resumed");
});

test("step: a timed-out worker-nvidia run resumes on a fresh out, never DONE on replay", () => {
  const { h, name, runDir } = t8Stream("nvidia-resume");
  const OC_WORKER = fileURLToPath(new URL("../bin/oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir, { agent: "worker-nvidia" }));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "worker-nvidia", outcome: "timeout", session: "ses_nvidia" }));
  });
  const first = cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0];
  assert.match(first, new RegExp(`^ACTION resume-worker node ${OC_WORKER} --role worker --dir ${fwd(runDir)} --prompt ${fwd(path.join(runDir, "mandate.md"))} --report ${fwd(path.join(runDir, "report.md"))} --out ${fwd(path.join(runDir, "worker-r2.md"))} --session ses_nvidia --stream ${name}$`));
  // Replay: the fresh out worker-r2.md has no queued event, so effectPresent is false and the stored line
  // repeats (not DONE, not resume-inflight) — doResume would spawn it.
  const second = cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0];
  assert.equal(second, first, "fresh out has no queued event: the resume line repeats");
  assert.ok(!/DONE/.test(second), "not reported DONE / resume-inflight");
});

test("step: a timed-out worker-nvidia run with every resume slot taken pages worker-timeout", () => {
  const { h, name, runDir } = t8Stream("nvidia-exhausted");
  fs.writeFileSync(path.join(runDir, "worker-r2.md"), "taken\n");
  fs.writeFileSync(path.join(runDir, "worker-r3.md"), "taken\n");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir, { agent: "worker-nvidia" }));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "worker-nvidia", outcome: "timeout", session: "ses_nvidia" }));
  });
  const line = cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0];
  assert.match(line, /^ESCALATE worker-timeout /);
});

test("step: CHANGES_REQUESTED on worker-nvidia resumes same agent + session, no --fallback", () => {
  const { h, name, runDir } = t8Stream("nvidia-changes");
  const OC_WORKER = fileURLToPath(new URL("../bin/oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir, { agent: "worker-nvidia" }));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "worker-nvidia", session: "ses_nvidia" }));
    appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  const line = cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0];
  assert.equal(
    line,
    `ACTION resume-worker node ${OC_WORKER} --agent worker-nvidia --dir ${fwd(runDir)} --prompt ${fwd(path.join(runDir, "findings-r1.md"))} --report ${fwd(path.join(runDir, "report.md"))} --out ${fwd(path.join(runDir, "worker-r2.md"))} --session ses_nvidia --stream ${name}`,
  );
  assert.ok(!line.includes("--fallback"), "same agent, no hand-typed fallback");
});

test("step: replay prints the stored line once and DONE once the effect exists", () => {
  // ACTION critic: replays until verdict:<run> exists, one ack line
  const critic = t8Stream("replay-critic");
  inHome(critic.h, undefined, () => {
    appendEvent(critic.name, evQueued("worker-r1", critic.runDir));
    appendEvent(critic.name, evDone("worker-r1", critic.runDir));
  });
  const first = cliLines(critic.h, ["step", critic.name, "run:worker-r1:done"]).lines[0];
  assert.match(first, /^ACTION critic /);
  assert.equal(cliLines(critic.h, ["step", critic.name, "run:worker-r1:done"]).lines[0], first, "no effect yet: the stored line repeats");
  assert.equal(inHome(critic.h, undefined, () => readAckLines(critic.name).filter((l) => l.key === "run:worker-r1:done").length), 1, "one decision line");
  inHome(critic.h, undefined, () => appendEvent(critic.name, evVerdict("worker-r1", critic.runDir)));
  assert.equal(cliLines(critic.h, ["step", critic.name, "run:worker-r1:done"]).lines[0], "DONE run:worker-r1:done");

  // ACTION resume-worker: the effect is the next run's queued event
  const res = t8Stream("replay-resume");
  inHome(res.h, undefined, () => {
    appendEvent(res.name, evQueued("worker-r1", res.runDir));
    appendEvent(res.name, evDone("worker-r1", res.runDir));
    appendEvent(res.name, evVerdict("worker-r1", res.runDir, { effective: "CHANGES_REQUESTED" }));
  });
  assert.match(cliLines(res.h, ["step", res.name, "verdict:worker-r1"]).lines[0], /^ACTION resume-worker /);
  inHome(res.h, undefined, () => appendEvent(res.name, evQueued("worker-r2", res.runDir)));
  assert.equal(cliLines(res.h, ["step", res.name, "verdict:worker-r1"]).lines[0], "DONE verdict:worker-r1");

  // ESCALATE: the effect is a resolved ack for the same key (handoff.mjs ack --resolved)
  const esc = t8Stream("replay-escalate");
  inHome(esc.h, undefined, () => {
    appendEvent(esc.name, evQueued("worker-r1", esc.runDir));
    appendEvent(esc.name, evDone("worker-r1", esc.runDir, { outcome: "blocked" }));
  });
  const line = cliLines(esc.h, ["step", esc.name, "run:worker-r1:done"]).lines[0];
  assert.equal(line, `ESCALATE worker-blocked ${fwd(path.join(esc.runDir, "worker-r1.md"))}`);
  assert.equal(cliLines(esc.h, ["step", esc.name, "run:worker-r1:done"]).lines[0], line, "unresolved: the stored line repeats");
  assert.equal(handoff(esc.h, ["ack", "--stream", esc.name, "--key", "run:worker-r1:done", "--resolved"]).status, 0);
  assert.equal(cliLines(esc.h, ["step", esc.name, "run:worker-r1:done"]).lines[0], "DONE run:worker-r1:done");
});

test("step: a resume takes the next free out instead of paging (out file, receipt or queued event)", () => {
  for (const kind of ["out", "receipt", "queued"]) {
    const { h, name, runDir } = t8Stream(`out-${kind}`);
    inHome(h, undefined, () => {
      appendEvent(name, evQueued("worker-r1", runDir));
      appendEvent(name, evDone("worker-r1", runDir));
      appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED" }));
      if (kind === "queued") appendEvent(name, { ...evQueued("worker-r2", runDir), pid: 2 });
    });
    if (kind === "out") fs.writeFileSync(path.join(runDir, "worker-r2.md"), "partial\n");
    if (kind === "receipt") fs.writeFileSync(path.join(runDir, "worker-r2.md.receipt.json"), "{}\n");
    assert.match(cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0], /^ACTION resume-worker .*--out .*worker-r3\.md/, kind);
  }
});

test("step: a resume with every slot through max_rounds taken pages rounds-exhausted", () => {
  const { h, name, runDir } = t8Stream("out-full");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  fs.writeFileSync(path.join(runDir, "worker-r2.md"), "partial\n");
  fs.writeFileSync(path.join(runDir, "worker-r3.md"), "partial\n");
  assert.match(cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0], /^ESCALATE rounds-exhausted /, "max_rounds=3, r2+r3 taken");
});

test("step: a critic round past max_rounds pages rounds-exhausted naming the highest findings file", () => {
  const { h, name, runDir } = t8Stream("past-max");
  mkTicket(runDir, { max_rounds: 2 });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r2", runDir));
    appendEvent(name, evDone("worker-r2", runDir));
  });
  fs.writeFileSync(path.join(runDir, "findings-r2.md"), "taken\n");
  const line = cliLines(h, ["step", name, "run:worker-r2:done"]).lines[0];
  assert.equal(line, `ESCALATE rounds-exhausted ${fwd(path.join(runDir, "findings-r2.md"))}`);
});

test("step: a findings slot judged by a recorded verdict advances the critic round even when its file is gone", () => {
  const { h, name, runDir } = t8Stream("judged");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    appendEvent(name, evQueued("findings-r1", runDir, "critic"));
    appendEvent(name, evDone("findings-r1", runDir, { agent: "critic" }));
    appendEvent(name, evVerdict("findings-r1", runDir, { effective: "INVALID" }));
  });
  const line = cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0];
  assert.match(line, /findings-r2\.md 2$/, line);
});

test("verdict: gate() decides the four findings kinds, stores reviewed_sha, prints KEY", () => {
  const { h, name, runDir } = t8Stream("verdicts");
  const repo = gitRepo();
  mkTicket(runDir, { worktree: repo.dir });
  const blast = "BLAST RADIUS:\n- bin/x.mjs:1 - unchanged\n";
  const cases = {
    approved: { text: `VERDICT: APPROVED\nTESTS: npm test -> 200 pass\n${blast}SENIOR_REVIEW: not-needed - small\n`, effective: "APPROVED", senior: false },
    overridden: { text: `VERDICT: APPROVED\n${blast}1. [blocker] bin/y.mjs:2 - broken\nSENIOR_REVIEW: not-needed\n`, effective: "CHANGES_REQUESTED", senior: false },
    invalid: { text: "TESTS: npm test -> 200 pass\nno verdict line here\n", effective: "INVALID", senior: false },
    senior: { text: `VERDICT: APPROVED\n${blast}SENIOR_REVIEW: needed - guarded path\n`, effective: "APPROVED", senior: true },
  };
  let i = 0;
  for (const [label, c] of Object.entries(cases)) {
    const run = `worker-v${++i}`;
    inHome(h, undefined, () => {
      appendEvent(name, evQueued(run, runDir));
      appendEvent(name, evDone(run, runDir));
    });
    const findings = path.join(runDir, `${label}.md`);
    fs.writeFileSync(findings, c.text);
    const r = cliLines(h, ["verdict", name, run, "--findings", findings]);
    assert.equal(r.status, 0, r.stderr);
    assert.deepEqual(r.lines, [`KEY verdict:${run}`], "not an EVENT line");
    const ev = eventsOf(h, name).find((e) => e.key === `verdict:${run}`);
    assert.equal(ev.effective, c.effective, label);
    assert.equal(ev.senior, c.senior, label);
    assert.equal(ev.findings, path.resolve(findings), label);
    assert.equal(ev.reviewed_sha, repo.head, label);
  }
  // exit 2: missing findings, missing run, git failure
  assert.equal(cli(h, ["verdict", name, "worker-v1", "--findings", path.join(runDir, "nope.md")]).status, 2);
  assert.equal(cli(h, ["verdict", name, "worker-nope", "--findings", path.join(runDir, "approved.md")]).status, 2);
  mkTicket(runDir, { worktree: runDir }); // not a git repo
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-v9", runDir));
    appendEvent(name, evDone("worker-v9", runDir));
  });
  assert.equal(cli(h, ["verdict", name, "worker-v9", "--findings", path.join(runDir, "approved.md")]).status, 2);
});

test("merge-check: OK, then each FAIL (dirty, head-moved, not-ff, not-approved) and exit 2", () => {
  const setup = (label, { base = "main", effective = "APPROVED" } = {}) => {
    const s = t8Stream(`mc-${label}`);
    const repo = gitRepo();
    mkTicket(s.runDir, { worktree: repo.dir, base });
    inHome(s.h, undefined, () => {
      appendEvent(s.name, evQueued("worker-r1", s.runDir));
      appendEvent(s.name, evDone("worker-r1", s.runDir));
      appendEvent(s.name, evVerdict("worker-r1", s.runDir, { effective, reviewed_sha: repo.head }));
    });
    return { ...s, repo };
  };

  const ok = setup("ok");
  const good = cliLines(ok.h, ["merge-check", ok.name, "worker-r1"]);
  assert.equal(good.status, 0, good.stderr);
  assert.deepEqual(good.lines, ["OK"]);

  const dirty = setup("dirty");
  fs.writeFileSync(path.join(dirty.repo.dir, "untracked.txt"), "x\n");
  const d = cliLines(dirty.h, ["merge-check", dirty.name, "worker-r1"]);
  assert.equal(d.status, 1);
  assert.deepEqual(d.lines, ["FAIL dirty"]);

  const moved = setup("moved");
  fs.appendFileSync(path.join(moved.repo.dir, "a.txt"), "later\n");
  moved.repo.g("add", "a.txt");
  moved.repo.g("commit", "-m", "after the review");
  const m = cliLines(moved.h, ["merge-check", moved.name, "worker-r1"]);
  assert.equal(m.status, 1);
  assert.deepEqual(m.lines, ["FAIL head-moved"]);

  const notff = setup("notff", { base: "other" });
  notff.repo.g("checkout", "main");
  notff.repo.g("checkout", "-b", "other");
  fs.appendFileSync(path.join(notff.repo.dir, "a.txt"), "other\n");
  notff.repo.g("add", "a.txt");
  notff.repo.g("commit", "-m", "other work");
  notff.repo.g("checkout", "feat");
  const nf = cliLines(notff.h, ["merge-check", notff.name, "worker-r1"]);
  assert.equal(nf.status, 1);
  assert.deepEqual(nf.lines, ["FAIL not-ff"]);

  const notApproved = setup("notapproved", { effective: "CHANGES_REQUESTED" });
  const na = cliLines(notApproved.h, ["merge-check", notApproved.name, "worker-r1"]);
  assert.equal(na.status, 1);
  assert.deepEqual(na.lines, ["FAIL not-approved"]);

  assert.equal(cli(ok.h, ["merge-check", ok.name, "worker-nope"]).status, 2);
});

// ---------------------------------------------------------------- T8-minors: prefixed run ids, stale tickets, minors

test("prefixed run ids: critic, verdict, resume and the next key all carry <ticket>/", () => {
  const OC_WORKER = fileURLToPath(new URL("../bin/oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
  const { h, name, runDir, ticket } = t8Stream("prefixed");
  const run = `${ticket.ticket}/worker-r1`;
  const out1 = fwd(path.join(runDir, "worker-r1.md"));
  inHome(h, undefined, () => {
    // out is the real run file: the ticket prefix lives in the key, not in the path
    appendEvent(name, evQueued(run, runDir, "worker", { out: out1 }));
    appendEvent(name, evDone(run, runDir, { out: out1 }));
  });
  assert.equal(
    cliLines(h, ["step", name, `run:${run}:done`]).lines[0],
    `ACTION critic ${fwd(path.join(runDir, "ticket.json"))} ${out1} ${fwd(path.join(runDir, "findings-r1.md"))} 1`,
  );
  inHome(h, undefined, () => appendEvent(name, evVerdict(run, runDir, { effective: "CHANGES_REQUESTED" })));
  assert.equal(cliLines(h, ["step", name, `run:${run}:done`]).lines[0], `DONE run:${run}:done`, "the critic's verdict satisfies the action");
  assert.equal(
    cliLines(h, ["step", name, `verdict:${run}`]).lines[0],
    `ACTION resume-worker node ${OC_WORKER} --agent worker --dir ${fwd(runDir)} --prompt ${fwd(path.join(runDir, "findings-r1.md"))} ` +
      `--report ${fwd(path.join(runDir, "report.md"))} --out ${fwd(path.join(runDir, "worker-r2.md"))} --session ses_1 --stream ${name}`,
  );
  // the resume's own key is <ticket>/worker-r2: the desk recognises it as the effect of its line
  inHome(h, undefined, () => appendEvent(name, evQueued(`${ticket.ticket}/worker-r2`, runDir, "worker", { out: fwd(path.join(runDir, "worker-r2.md")) })));
  assert.equal(cliLines(h, ["step", name, `verdict:${run}`]).lines[0], `DONE verdict:${run}`);
  // status shows the full id, and two tickets on one stream are two rows
  const other = mkTicket(path.join(h, "reports", "t8b"), { ticket: "t8b" });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued(`${other.ticket}/worker-r1`, path.dirname(other.mandate), "worker", { out: fwd(path.join(path.dirname(other.mandate), "worker-r1.md")) }));
  });
  const rows = inHome(h, undefined, () => statusRows()).find((s) => s.name === name);
  assert.deepEqual(rows.runs.map((r) => r.run).sort(), ["t8/worker-r1", "t8/worker-r2", "t8b/worker-r1"]);
});

test("a stale event of a closed ticket is DONE, not replayed; run-done without verdict escalates unreviewed-merge", () => {
  const { h, name, runDir, ticket } = t8Stream("closed");
  const run = `${ticket.ticket}/worker-r1`;
  const out = fwd(path.join(runDir, "worker-r1.md"));
  inHome(h, undefined, () => {
    appendEvent(name, evQueued(run, runDir, "worker", { out }));
    appendEvent(name, evDone(run, runDir, { out }));
    appendEvent(name, evQueued("worker-r9", runDir)); // a legacy id of the same ticket
    appendEvent(name, evDone("worker-r9", runDir));
  });
  // merged: the worktree is gone. The orphan directory may remain; only the `.git` entry matters.
  fs.rmSync(path.join(runDir, ".git"), { force: true });
  // D2: run-done for a closed ticket with no verdict -> ESCALATE unreviewed-merge
  const first = cliLines(h, ["step", name, `run:${run}:done`]);
  assert.equal(first.status, 0, first.stderr);
  assert.deepEqual(first.lines, [`ESCALATE unreviewed-merge ${ticket.ticket}`]);
  const acks = () => inHome(h, undefined, () => readAckLines(name).filter((l) => l.key === `run:${run}:done`));
  assert.deepEqual(acks().map((l) => [l.action, Boolean(l.resolved)]), [[`ESCALATE unreviewed-merge ${ticket.ticket}`, true]], "one resolved ack for unreviewed-merge");
  assert.deepEqual(cliLines(h, ["step", name, `run:${run}:done`]).lines, [`DONE run:${run}:done`], "a replay prints DONE");
  assert.equal(acks().length, 1, "a replay writes nothing");
  // run-dead and verdict of the same closed ticket are stale too, prefixed or legacy
  inHome(h, undefined, () => {
    appendEvent(name, { key: `run:${run}:dead`, kind: "run-dead", run, out });
    appendEvent(name, evVerdict(run, runDir));
  });
  assert.deepEqual(cliLines(h, ["step", name, `run:${run}:dead`]).lines, [`DONE run:${run}:dead`]);
  assert.deepEqual(cliLines(h, ["step", name, `verdict:${run}`]).lines, [`DONE verdict:${run}`]);
  assert.deepEqual(cliLines(h, ["step", name, "run:worker-r9:done"]).lines, ["DONE run:worker-r9:done"], "a legacy id of a closed ticket steps clean too");

  // an open ticket of its own still gets its decision: the closed check is per ticket, not per stream
  const open = t8Stream("open");
  const openRun = `${open.ticket.ticket}/worker-r1`;
  inHome(open.h, undefined, () => {
    appendEvent(open.name, evQueued(openRun, open.runDir, "worker", { out: fwd(path.join(open.runDir, "worker-r1.md")) }));
    appendEvent(open.name, evDone(openRun, open.runDir, { out: fwd(path.join(open.runDir, "worker-r1.md")) }));
  });
  assert.match(cliLines(open.h, ["step", open.name, `run:${openRun}:done`]).lines[0], /^ACTION critic /);
});

test("merge-check: no verdict reads FAIL not-approved, before dirty and head-moved", () => {
  const s = t8Stream("mc-noverdict");
  const repo = gitRepo();
  mkTicket(s.runDir, { worktree: repo.dir });
  inHome(s.h, undefined, () => {
    appendEvent(s.name, evQueued(`${s.ticket.ticket}/worker-r1`, s.runDir));
    appendEvent(s.name, evDone(`${s.ticket.ticket}/worker-r1`, s.runDir));
  });
  const pending = cliLines(s.h, ["merge-check", s.name, `${s.ticket.ticket}/worker-r1`]);
  assert.equal(pending.status, 1);
  assert.deepEqual(pending.lines, ["FAIL not-approved"]);
  // a dirty tree and a moved HEAD do not change that: nothing was approved
  fs.writeFileSync(path.join(repo.dir, "untracked.txt"), "x\n");
  fs.appendFileSync(path.join(repo.dir, "a.txt"), "later\n");
  repo.g("add", "a.txt");
  repo.g("commit", "-m", "after the review");
  const still = cliLines(s.h, ["merge-check", s.name, `${s.ticket.ticket}/worker-r1`]);
  assert.equal(still.status, 1);
  assert.deepEqual(still.lines, ["FAIL not-approved"]);
});

test("effectPresent: a resume out path containing ` --` still resolves its queued event", () => {
  const h = home();
  mkStream(h, "double-dash");
  // a run dir whose own name contains the flag-ish separator the old regex cut at
  const runDir = path.join(h, "reports", "t8 -- copy");
  const t = mkTicket(runDir);
  const run = `${t.ticket}/worker-r1`;
  const out1 = fwd(path.join(runDir, "worker-r1.md"));
  inHome(h, undefined, () => {
    appendEvent("double-dash", evQueued(run, runDir, "worker", { out: out1 }));
    appendEvent("double-dash", evDone(run, runDir, { out: out1 }));
    appendEvent("double-dash", evVerdict(run, runDir, { effective: "CHANGES_REQUESTED" }));
  });
  const line = cliLines(h, ["step", "double-dash", `verdict:${run}`]).lines[0];
  assert.match(line, new RegExp(`--out ${fwd(path.join(runDir, "worker-r2.md")).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")} --session ses_1`));
  // the resume ran: its queued event carries <ticket>/worker-r2 and an out inside that odd directory
  inHome(h, undefined, () => appendEvent("double-dash", evQueued(`${t.ticket}/worker-r2`, runDir, "worker", { out: fwd(path.join(runDir, "worker-r2.md")) })));
  assert.deepEqual(cliLines(h, ["step", "double-dash", `verdict:${run}`]).lines, [`DONE verdict:${run}`]);
});

test("status survives a throwing migrate: stderr names it and the command still runs", () => {
  const h = home();
  const cfg = path.join(h, ".config", "orchestrator");
  fs.mkdirSync(cfg, { recursive: true });
  fs.writeFileSync(path.join(cfg, "handoff.json"), JSON.stringify({ plan: "p", next: "n", written_at: new Date().toISOString() }));
  fs.writeFileSync(path.join(cfg, "streams"), "not a directory\n"); // the fold's mkdirSync throws
  const r = cli(h, ["status"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, /^desk: migrate failed: /m);
  assert.match(r.stdout, /^watch none — no desk watcher holds the lock\nslots \d+\/\d+ \(fixed\)\n$/);
});

test("manifest: commands/frood-desk.md installs to both harnesses, and install --check sees it", () => {
  const h = home();
  const items = inHome(h, undefined, () => plan());
  const desk = items.filter((i) => i.src.replace(/\\/g, "/").endsWith("commands/frood-desk.md"));
  assert.equal(desk.length, 2, "two targets: cc + oc");
  const cc = desk.find((d) => d.harness === "cc");
  const oc = desk.find((d) => d.harness === "oc");
  assert.ok(cc, "cc target exists");
  assert.ok(oc, "oc target exists");
  assert.ok(cc.target.endsWith(path.join(".claude", "commands", "frood-desk.md")), cc.target);
  assert.ok(oc.target.endsWith(path.join(".config", "opencode", "commands", "frood-desk.md")), oc.target);

  // CC content: unchanged
  assert.match(cc.content, /^---\ndescription: Follow every orchestrator stream from one flat session/m);
  assert.match(cc.content, /managed by Frood/);
  assert.match(cc.content, /desk: idle — no unhandled events, ending session/);
  assert.match(cc.content, /Start \*\*one\*\* `Monitor`/);
  assert.match(cc.content, /Agent\(subagent_type: "critic"\)/);
  assert.match(cc.content, /run_in_background/);

  // OC content: no Monitor block, no Agent(subagent_type, no run_in_background, no .claude/
  assert.doesNotMatch(oc.content, /Start \*\*one\*\* `Monitor`/);
  assert.doesNotMatch(oc.content, /Agent\(subagent_type/);
  assert.doesNotMatch(oc.content, /run_in_background/);
  // The managed header records where the source lives, and in a worktree that path itself contains
  // `.claude/`; the rule is about Claude Code config references, so name those paths explicitly.
  assert.doesNotMatch(oc.content, /\.claude\/(hooks|commands|agents)\//);
  assert.match(oc.content, /watch --events --by oc --until-event/);
  assert.match(oc.content, /desk: idle — no unhandled events, ending session/);
  assert.match(oc.content, /oc-worker\.mjs --role critic/);
  // 1f5aa26 removed the agent pin so /frood-desk never forces a switch to a down pool model:
  // no `agent: <desk-agent>` pin remains, and the models report is the availability path.
  assert.doesNotMatch(oc.content, /agent: orchestrator/);
  assert.match(oc.content, /desk\.mjs models/);

  const run = (args) =>
    spawnSync(process.execPath, [path.join(HERE, "..", "bin", "install.mjs"), ...args], {
      env: { ...process.env, ORCH_HOME: h, ORCH_SKIP_ROUTING: "1" },
      encoding: "utf8",
    });
  const installed = run([]);
  assert.equal(installed.status, 0, installed.stderr);
  assert.ok(fs.existsSync(path.join(h, ".claude", "commands", "frood-desk.md")));
  assert.ok(fs.existsSync(path.join(h, ".config", "opencode", "commands", "frood-desk.md")));
  const check = run(["--check"]);
  assert.equal(check.status, 0, check.stdout);
  assert.match(check.stdout, /check: OK/);
});

// ---------------------------------------------------------------- T5 desk-lease (--by)

function heldStream(h, name, heldBy) {
  mkStream(h, name);
  const f = path.join(sdir(h), `${name}.json`);
  const o = JSON.parse(fs.readFileSync(f, "utf8"));
  Object.assign(o, { held_by: heldBy, held_session: "s1", held_at: new Date().toISOString() });
  fs.writeFileSync(f, JSON.stringify(o));
}
const doneEv = { key: "run:worker-r1:done", kind: "run-done", run: "worker-r1", out: "/x/worker-r1.md", agent: "worker", exit: 0, outcome: "done", session: "ses_1" };

test("watch --once --by cc: skips an oc-held stream (no EVENT, no run-dead); free or cc-held prints", () => {
  const h = home();
  heldStream(h, "m6a", "oc");
  inHome(h, undefined, () => {
    appendEvent("m6a", doneEv);
    appendEvent("m6a", queued("worker-r2", 999999, "2026-01-01T00:00:00.000Z"));
  });
  const r = cli(h, ["watch", "--events", "--once", "--by", "cc"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "");
  assert.ok(!eventsOf(h).some((e) => e.kind === "run-dead"), "no run-dead synthesised for a held stream");
  for (const holder of [null, "cc"]) {
    heldStream(h, "m6a", holder);
    const f = cli(h, ["watch", "--events", "--once", "--by", "cc"]);
    assert.match(f.stdout, /^EVENT m6a run:worker-r1:done run-done done$/m);
  }
});

test("watch --once without --by prints an oc-held stream (back-compat)", () => {
  const h = home();
  heldStream(h, "m6a", "oc");
  inHome(h, undefined, () => appendEvent("m6a", doneEv));
  assert.match(cli(h, ["watch", "--events", "--once"]).stdout, /^EVENT m6a run:worker-r1:done run-done done$/m);
});

test("watch --by xx exits 2", () => {
  const h = home();
  mkStream(h);
  const r = cli(h, ["watch", "--events", "--once", "--by", "xx"]);
  assert.equal(r.status, 2);
  assert.match(r.stderr, /--by must be cc or oc/);
});

test("watch --until-event --by cc with only an oc-held stream exits 4 at the deadline", () => {
  const h = home();
  heldStream(h, "m6a", "oc");
  inHome(h, undefined, () => appendEvent("m6a", doneEv));
  const r = cli(h, ["watch", "--events", "--until-event", "1", "--interval", "0.1", "--by", "cc"]);
  assert.equal(r.status, 4, r.stderr);
  assert.equal(r.stdout, "");
});

test("step --by cc on an oc-held stream prints HELD and acks nothing; free steps normally", () => {
  const h = home();
  heldStream(h, "m6a", "oc");
  inHome(h, undefined, () => appendEvent("m6a", doneEv));
  const acks = () => inHome(h, undefined, () => JSON.stringify(readAckLines("m6a")));
  const before = acks();
  const r = cli(h, ["step", "m6a", "run:worker-r1:done", "--by", "cc"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "HELD m6a oc\n");
  assert.equal(acks(), before);
  heldStream(h, "m6a", null);
  const f = cli(h, ["step", "m6a", "run:worker-r1:done", "--by", "cc"]);
  assert.equal(f.status, 0, f.stderr);
  assert.match(f.stdout, /^ESCALATE no-ticket /);
  assert.equal(cli(h, ["step", "m6a", "run:worker-r1:done", "--by", "xx"]).status, 2);
});

test("status shows held=<h>; --json has held_by", () => {
  const h = home();
  heldStream(h, "m6a", "oc");
  mkStream(h, "free");
  const lines = cli(h, ["status"]).stdout.split("\n").filter(Boolean);
  assert.match(lines.find((l) => l.startsWith("watch ")), /^watch none/);
  assert.match(lines.find((l) => l.startsWith("m6a")), /unhandled=\d+ held=oc$/);
  assert.doesNotMatch(lines.find((l) => l.startsWith("free")), /held=/);
  const j = JSON.parse(cli(h, ["status", "--json"]).stdout);
  assert.deepEqual(j.streams.map((s) => [s.name, s.held_by]), [["free", null], ["m6a", "oc"]]);
});

// ---------------------------------------------------------------- lock-path safety (M7 B1)

test("inHome keeps ORCH_HOME set across an await, so lockPath() resolves inside the temp home", async () => {
  const h = home();
  const body = await inHome(h, undefined, async () => {
    await new Promise((r) => setTimeout(r, 5)); // the original shape: the lock path is built after the body's first await
    return { env: process.env.ORCH_HOME, lock: lockPath() };
  });
  assert.equal(body.env, h, "ORCH_HOME is still set after the await");
  assert.equal(path.resolve(body.lock), path.resolve(lockDirOf(h)), "the lock path is the temp home's");
  assert.notEqual(path.resolve(body.lock), path.resolve(lockDirOf(REAL_HOME)), "never the live watcher's lock");
  assert.notEqual(process.env.ORCH_HOME, h, "env is restored once the body completed");
});

test("inHome refuses when orchRoot() would resolve to the real home", () => {
  const before = process.env.ORCH_HOME;
  let ran = false;
  assert.throws(
    () =>
      inHome(REAL_HOME, undefined, () => {
        ran = true;
      }),
    /orchRoot resolved to the real home — refusing/,
  );
  assert.equal(ran, false, "the callback never ran");
  assert.equal(process.env.ORCH_HOME, before, "env restored on refusal");
});

test("step: a critic-keyed CHANGES_REQUESTED verdict resumes the reviewed worker, not the critic", () => {
  const { h, name, runDir } = t8Stream("resume-link");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
  });
  // The step records ACTION critic on the worker run-done: the linkage the desk later follows.
  assert.match(cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0], /^ACTION critic .*findings-r1\.md 1$/);
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\n");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("t8c/findings-r1", runDir, "critic", { out: findings }));
    appendEvent(name, evDone("t8c/findings-r1", runDir, { out: findings, agent: "critic", session: "ses_c" }));
    appendEvent(name, evVerdict("t8c/findings-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  const line = cliLines(h, ["step", name, "verdict:t8c/findings-r1"]).lines[0];
  assert.match(line, /^ACTION resume-worker /);
  assert.match(line, /--agent worker .*--prompt .*findings-r1\.md .*--out .*worker-r2\.md --session ses_1 --stream resume-link$/);
});

test("step: a critic-keyed verdict with no ACTION linkage pages review-unlinked", () => {
  const { h, name, runDir } = t8Stream("resume-unlinked");
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\n");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    // No step on the worker run-done: the critic was launched outside the flow, so nothing
    // records which worker run it reviewed.
    appendEvent(name, evQueued("t8c/findings-r1", runDir, "critic", { out: findings }));
    appendEvent(name, evDone("t8c/findings-r1", runDir, { out: findings, agent: "critic", session: "ses_c" }));
    appendEvent(name, evVerdict("t8c/findings-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  assert.match(cliLines(h, ["step", name, "verdict:t8c/findings-r1"]).lines[0], /^ESCALATE review-unlinked .*findings-r1\.md/);
});

test("step: CHANGES_REQUESTED resumes the same agent + session, no --fallback", () => {
  for (const agent of ["worker-nvidia", "worker-free", "worker"]) {
    const { h, name, runDir } = t8Stream(`resume-same-${agent}`);
    const findings = path.join(runDir, "findings-r1.md");
    fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\n");
    inHome(h, undefined, () => {
      appendEvent(name, evQueued("worker-r1", runDir, agent));
      appendEvent(name, evDone("worker-r1", runDir, { agent }));
      appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED" }));
    });
    const line = cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0];
    assert.match(line, new RegExp(`^ACTION resume-worker .*--agent ${agent} `), agent);
    assert.match(line, /--session ses_1 /);
    assert.doesNotMatch(line, /--fallback/, `${agent}: no hand-typed fallback`);
  }
});

test("step: a paid round 1 resumes same-agent with no fallback added", () => {
  for (const agent of ["worker", "worker-strong"]) {
    const { h, name, runDir } = t8Stream(`resume-paid-${agent}`);
    const findings = path.join(runDir, "findings-r1.md");
    fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\n");
    inHome(h, undefined, () => {
      appendEvent(name, evQueued("worker-r1", runDir, agent));
      appendEvent(name, evDone("worker-r1", runDir, { agent }));
      appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED" }));
    });
    const line = cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0];
    assert.match(line, new RegExp(`^ACTION resume-worker .*--agent ${agent} `), agent);
    assert.doesNotMatch(line, /--fallback/, agent);
  }
});

test("step: a critic-keyed verdict on a free run resumes same agent + session via linkage", () => {
  const { h, name, runDir } = t8Stream("resume-tier-cc");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir, "worker-free"));
    appendEvent(name, evDone("worker-r1", runDir, { agent: "worker-free" }));
  });
  assert.match(cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0], /^ACTION critic .*findings-r1\.md 1$/);
  const findings = path.join(runDir, "findings-r1.md");
  fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\n");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("t8c/findings-r1", runDir, "critic", { out: findings }));
    appendEvent(name, evDone("t8c/findings-r1", runDir, { out: findings, agent: "critic", session: "ses_c" }));
    appendEvent(name, evVerdict("t8c/findings-r1", runDir, { effective: "CHANGES_REQUESTED" }));
  });
  const line = cliLines(h, ["step", name, "verdict:t8c/findings-r1"]).lines[0];
  assert.match(line, /--agent worker-free /);
  assert.match(line, /--session ses_1 /);
  assert.doesNotMatch(line, /--fallback/);
});

// ---------------------------------------------------------------- completion wake-up (loop-stay)

// The mailbox fixture uses the REAL schema (body + expires_at NOT NULL, the status CHECK) because the desk
// inserts a full row; a temp ORCH_HOME owns the file, so the real mailbox is never opened.
function mkMailbox(h) {
  const file = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const { DatabaseSync } = require("node:sqlite");
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
const mailboxPath = (h) => path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
const mailTo = (file, to) => {
  if (!fs.existsSync(file)) return [];
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(file, { readOnly: true });
  try {
    return db.prepare("SELECT subject, body FROM messages WHERE to_session = ? ORDER BY ts, id").all(to);
  } finally {
    db.close();
  }
};
const HOLDER = "ses_holder0000000000000000";
const IS_WIN = process.platform === "win32";

// Stub `notify-send` on PATH so a desktop page is observable instead of hitting the real desktop.
// A POSIX shell script: Windows resolves it through PATHEXT, not execFileSync, so the one test that
// uses this is skipped there (the code path is platform-independent; only the stub is not).
// Returns { root, env, reads() } where reads() is every page arg line, oldest first.
function stubNotifySend() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ns-"));
  CLEAN.push(root);
  const bin = path.join(root, "bin");
  fs.mkdirSync(bin, { recursive: true });
  const marker = path.join(root, "pages.txt");
  const exe = path.join(bin, "notify-send");
  fs.writeFileSync(exe, `#!/bin/sh\nprintf '%s\\n' "$*" >> ${JSON.stringify(marker)}\n`);
  fs.chmodSync(exe, 0o755);
  return {
    root,
    env: { PATH: `${bin}${path.delimiter}${process.env.PATH ?? ""}` },
    reads: () => (fs.existsSync(marker) ? fs.readFileSync(marker, "utf8").split("\n").filter(Boolean) : []),
  };
}

// A t8 fixture whose stream is held by an OpenCode session (the one the desk must wake), plus its mailbox.
function heldT8(name = "wake") {
  const s = t8Stream(name);
  const f = path.join(sdir(s.h), `${name}.json`);
  const o = JSON.parse(fs.readFileSync(f, "utf8"));
  Object.assign(o, { held_by: "oc", held_session: HOLDER, held_at: new Date().toISOString() });
  fs.writeFileSync(f, JSON.stringify(o));
  return { ...s, mailbox: mkMailbox(s.h) };
}

test("completion wake-up: ESCALATE merge, ESCALATE senior and ESCALATE owner-signoff each mail the holder once", async () => {
  const saved = { ...process.env };
  // Dry run keeps doMerge out of git, so `ESCALATE merge` reaches the wake-up instead of paging on merge-check.
  Object.assign(process.env, { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" });
  try {
    for (const [label, verdict, needle] of [
      ["merge", { effective: "APPROVED", senior: false, reviewed_sha: "0123456789abcdef0123456789abcdef01234567" }, /approved and ready to merge at 0123456789ab/],
      ["senior", { effective: "APPROVED", senior: true }, /senior .*findings-r1\.md/],
      ["owner-signoff", { effective: "APPROVED_FREE", senior: false, reviewed_sha: "0123456789abcdef0123456789abcdef01234567" }, /owner-signoff .*free review/],
    ]) {
      const { h, name, runDir, mailbox } = heldT8(`wake-${label}`);
      inHome(h, undefined, () => {
        appendEvent(name, evQueued("worker-r1", runDir));
        appendEvent(name, evDone("worker-r1", runDir));
        appendEvent(name, evVerdict("worker-r1", runDir, verdict));
      });
      const r = await inHome(h, undefined, () => handleEvent(name, "verdict:worker-r1", undefined));
      assert.ok(r, label);
      const mail = mailTo(mailbox, HOLDER);
      assert.equal(mail.length, 1, `${label}: exactly one peer-mail to the holding session`);
      assert.match(mail[0].subject, /^desk: /, label);
      assert.match(mail[0].subject, needle, `${label}: the subject says what happened`);
      assert.match(mail[0].body, new RegExp(`Stream: ${name}`), `${label}: body carries the stream`);
      assert.match(mail[0].body, /Event: verdict:worker-r1/, `${label}: body carries the event key`);
      assert.match(mail[0].body, /Resolve with:/, `${label}: body keeps the resolve hint`);
      // Only ONE mail for this key: a replay may re-report the same line, but nothing is sent twice.
      await inHome(h, undefined, () => handleEvent(name, "verdict:worker-r1", undefined));
      assert.equal(mailTo(mailbox, HOLDER).length, 1, `${label}: a replay never re-mails`);
    }
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("completion wake-up: resume-worker, critic dispatch and an unheld stream mail nobody", async () => {
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" });
  try {
    // A CHANGES_REQUESTED verdict resumes the worker: the loop working, not news for the owner.
    const resume = heldT8("wake-resume");
    const findings = path.join(resume.runDir, "findings-r1.md");
    fs.writeFileSync(findings, "VERDICT: CHANGES_REQUESTED\n");
    inHome(resume.h, undefined, () => {
      appendEvent(resume.name, evQueued("worker-r1", resume.runDir));
      appendEvent(resume.name, evDone("worker-r1", resume.runDir));
      appendEvent(resume.name, evVerdict("worker-r1", resume.runDir, { effective: "CHANGES_REQUESTED", findings }));
    });
    const r = await inHome(resume.h, undefined, () => handleEvent(resume.name, "verdict:worker-r1", undefined));
    assert.equal(r.outcome, "resume", JSON.stringify(r));
    assert.equal(mailTo(resume.mailbox, HOLDER).length, 0, "a resume wakes nobody");

    // A worker run-done dispatches the critic: also quiet.
    const critic = heldT8("wake-critic");
    const out = path.join(critic.runDir, "worker-r1.md");
    fs.writeFileSync(out, "done\n");
    inHome(critic.h, undefined, () => {
      appendEvent(critic.name, evQueued("worker-r1", critic.runDir));
      appendEvent(critic.name, evDone("worker-r1", critic.runDir));
    });
    const c = await inHome(critic.h, undefined, () => handleEvent(critic.name, "run:worker-r1:done", undefined));
    assert.equal(c.outcome, "critic", JSON.stringify(c));
    assert.equal(mailTo(critic.mailbox, HOLDER).length, 0, "a critic dispatch wakes nobody");

    // An unheld stream (no held_session) has nobody to wake: the merge still completes, no mail, and NO
    // desktop page either (finding 1: the wake-up reaches a session, never the desktop).
    const free = t8Stream("wake-unheld");
    const freeBox = mkMailbox(free.h);
    inHome(free.h, undefined, () => {
      appendEvent(free.name, evQueued("worker-r1", free.runDir));
      appendEvent(free.name, evDone("worker-r1", free.runDir));
      appendEvent(free.name, evVerdict("worker-r1", free.runDir, { effective: "APPROVED", reviewed_sha: "0123456789abcdef0123456789abcdef01234567" }));
    });
    const u = await inHome(free.h, undefined, () => handleEvent(free.name, "verdict:worker-r1", undefined));
    assert.equal(u.outcome, "merge", JSON.stringify(u));
    assert.equal(mailTo(freeBox, HOLDER).length, 0, "an unheld stream sends no peer-mail");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Finding 1: the wake-up must never raise a desktop page — for an unheld stream OR for a held one whose
// mail write fails. Provoked WITHOUT ORCH_NO_NOTIFY so the gate cannot mask a leak; a PATH stub records
// every notify-send the process would have run.
test("completion wake-up: no desktop page for a held stream, an unheld stream, or a held stream with no mailbox", { skip: IS_WIN ? "notify-send stub is a POSIX script" : false }, () => {
  const ns = stubNotifySend();
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_DAEMON_DRY_RUN: "1" }, ns.env);
  delete process.env.ORCH_NO_NOTIFY; // the gate must not hide a page: this asserts the code path, not the env
  try {
    // `outcome: "merge"` is the branch that actually reaches notifyHeldSession; a `paged` outcome returns
    // earlier (dpage already mailed), so it would make this test vacuous. The decisions cover all three
    // completion keys, which is what selects the reason text.
    const decisions = [
      "ESCALATE merge /x/reports/t1/ticket.json 0123456789abcdef0123456789abcdef01234567",
      "ESCALATE senior /x/findings-r1.md",
      "ESCALATE owner-signoff /x/findings-r1.md (free review: abc)",
    ];
    // held stream, mailbox present: mail only
    const held = heldT8("page-held");
    for (const d of decisions) inHome(held.h, undefined, () => wakeHolder(held.name, `run:${d}`, d, { outcome: "merge" }));
    assert.equal(mailTo(held.mailbox, HOLDER).length, 3, "the held stream is mailed for every completion key");
    assert.deepEqual(ns.reads(), [], "a held stream never pages the desktop");

    // unheld stream: nothing at all
    const free = t8Stream("page-unheld");
    for (const d of decisions) inHome(free.h, undefined, () => wakeHolder(free.name, `run:${d}`, d, { outcome: "merge" }));
    assert.deepEqual(ns.reads(), [], "an unheld stream never pages the desktop");

    // held stream whose mailbox is missing: nothing (and it says so on stderr)
    const gone = t8Stream("page-no-mailbox");
    const f = path.join(sdir(gone.h), `${gone.name}.json`);
    const o = JSON.parse(fs.readFileSync(f, "utf8"));
    Object.assign(o, { held_by: "oc", held_session: HOLDER });
    fs.writeFileSync(f, JSON.stringify(o));
    assert.ok(!fs.existsSync(mailboxPath(gone.h)), "no mailbox for this home");
    for (const d of decisions) inHome(gone.h, undefined, () => wakeHolder(gone.name, `run:${d}`, d, { outcome: "merge" }));
    assert.deepEqual(ns.reads(), [], "a held stream with no mailbox never pages the desktop either");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY", "PATH"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Finding 2 (round 2) + round-3 finding 1: a rehearsal must not consume the key, AND the durable entry must
// be stream-scoped. A bare `paged` entry would make handleEvent's key-only early return suppress another
// stream's same-named event (every stream's first run is `worker-r1`) — the merge would never happen.
test("completion wake-up: a rehearsal writes no paged entry, and the live entry is stream-scoped", () => {
  const saved = { ...process.env };
  const stateOf = (h) => {
    try {
      return JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "desk-daemon", "state.json"), "utf8"));
    } catch {
      return null;
    }
  };
  const key = "verdict:worker-r1";
  const decision = "ESCALATE merge /x/reports/t1/ticket.json 0123456789abcdef0123456789abcdef01234567";
  try {
    // --- dry run: mail goes out, once; no durable ledger entry
    Object.assign(process.env, { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" });
    const dry = heldT8("ledger-dry");
    inHome(dry.h, undefined, () => {
      wakeHolder(dry.name, key, decision, { outcome: "merge" });
      wakeHolder(dry.name, key, decision, { outcome: "merge" }); // same poll replay: still one mail
    });
    assert.equal(mailTo(dry.mailbox, HOLDER).length, 1, "a rehearsal mails the holder exactly once");
    assert.deepEqual(stateOf(dry.h)?.paged ?? [], [], "a rehearsal writes no paged entry at all");

    // --- live run: mail once, and the entry is `${stream}\0${key}` — never the bare key, which is what
    // handleEvent/dpage compare against and what would let one stream stall another.
    delete process.env.ORCH_DAEMON_DRY_RUN;
    const live = heldT8("ledger-live");
    inHome(live.h, undefined, () => {
      wakeHolder(live.name, key, decision, { outcome: "merge" });
      wakeHolder(live.name, key, decision, { outcome: "merge" }); // the stream-scoped entry stops the second
    });
    assert.equal(mailTo(live.mailbox, HOLDER).length, 1, "the live run mails exactly once");
    const paged = stateOf(live.h)?.paged ?? [];
    assert.deepEqual(paged, [`${live.name}\u0000${key}`], "the live entry is stream+key, in one entry");
    assert.ok(!paged.includes(key), "the bare key is never written: another stream's event must not be suppressed");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Round-3 finding 1, end to end through handleEvent: stream A's live merge must not stop stream B acting on
// its own same-named event. Both streams live in ONE state dir (one `paged` set is what makes the hazard
// real) and both name their first run `worker-r1`, so a key-only entry from A would make B's handleEvent
// return `paged` before its merge — after `step` had already acked the event (acked, no effect).
test("completion wake-up: stream A's live merge does not stall stream B's verdict:worker-r1", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home(); // ONE home: both streams share the durable paged set
    const mkHeld = (name) => {
      mkStream(h, name);
      const f = path.join(sdir(h), `${name}.json`);
      const o = JSON.parse(fs.readFileSync(f, "utf8"));
      Object.assign(o, { held_by: "oc", held_session: HOLDER });
      fs.writeFileSync(f, JSON.stringify(o));
      const runDir = runDirOf(h, name); // its own ticket dir, so ticket.json/mandate are distinct
      mkTicket(runDir, { ticket: name });
      return { name, runDir };
    };
    const mailbox = mkMailbox(h);
    const verdict = { effective: "APPROVED", reviewed_sha: "0123456789abcdef0123456789abcdef01234567" };

    const a = mkHeld("stall-a");
    inHome(h, undefined, () => {
      appendEvent("stall-a", evQueued("worker-r1", a.runDir));
      appendEvent("stall-a", evDone("worker-r1", a.runDir));
      appendEvent("stall-a", evVerdict("worker-r1", a.runDir, verdict));
    });
    // A's live merge, exactly as handleEvent reports it: the wake-up writes the durable entry.
    inHome(h, undefined, () => wakeHolder("stall-a", "verdict:worker-r1", "ESCALATE merge /x/t.json 0123456789ab", { outcome: "merged", line: "merged 0123456789ab" }));
    assert.equal(mailTo(mailbox, HOLDER).length, 1, "stream A woke its holder");
    const paged = JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "desk-daemon", "state.json"), "utf8")).paged;
    assert.ok(!paged.includes("verdict:worker-r1"), "A never wrote the bare key into the shared set");
    assert.deepEqual(paged, ["stall-a\u0000verdict:worker-r1"], "A's entry is stream-scoped");

    // Stream B, same home, same event key: handleEvent must REACH actOn, not short-circuit on `paged`.
    const b = mkHeld("stall-b");
    inHome(h, undefined, () => {
      appendEvent("stall-b", evQueued("worker-r1", b.runDir));
      appendEvent("stall-b", evDone("worker-r1", b.runDir));
      appendEvent("stall-b", evVerdict("worker-r1", b.runDir, verdict));
    });
    const rb = await inHome(h, undefined, () => handleEvent("stall-b", "verdict:worker-r1", undefined));
    // actOn ran: the fixture's worktree is not an ff ticket, so doMerge's merge-check pages — the escalation
    // file names stall-b. A short-circuit would leave that file empty and return before doMerge.
    const esc = fs.existsSync(path.join(h, ".config", "orchestrator", "desk-daemon", "escalations.jsonl"))
      ? fs.readFileSync(path.join(h, ".config", "orchestrator", "desk-daemon", "escalations.jsonl"), "utf8")
      : "";
    assert.match(esc, /stall-b/, `B's merge path ran (escalation recorded): ${JSON.stringify(rb)}`);
    assert.match(esc, /merge-check|merge-train/, "it was the merge path, not the paged short-circuit");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Finding 3: a held stream whose mailbox is missing used to fail completely silently — neither the desk's
// peer-mail nor dpage's desktop page said anything. It now names the missing file on stderr.
test("completion wake-up: a held stream with no mailbox says so on stderr instead of failing silently", () => {
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" });
  const out = [];
  const realErr = console.error;
  console.error = (m) => out.push(String(m));
  try {
    const s = t8Stream("no-mailbox-log");
    const f = path.join(sdir(s.h), `${s.name}.json`);
    const o = JSON.parse(fs.readFileSync(f, "utf8"));
    Object.assign(o, { held_by: "oc", held_session: HOLDER });
    fs.writeFileSync(f, JSON.stringify(o));
    inHome(s.h, undefined, () => wakeHolder(s.name, "verdict:worker-r1", "ESCALATE merge /x/ticket.json abc1234", { outcome: "merge" }));
    assert.equal(mailTo(mailboxPath(s.h), HOLDER).length, 0, "no mail was possible");
    const line = out.find((l) => l.includes("cannot send peer-mail"));
    assert.ok(line, `stderr named the failure: ${JSON.stringify(out)}`);
    assert.match(line, new RegExp(`no mailbox at .*mailbox\\.db`), "the line names the missing mailbox path");
    assert.ok(line.includes(HOLDER), "the line names the session it could not reach");
  } finally {
    console.error = realErr;
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Round-3: with the ledger entry stream-scoped, wakeHolder can no longer see dpage's bare-key entry. A
// senior/owner-signoff escalation goes through dpage (which mails once), so the wake-up must stand down on a
// `paged` result or the holder would be told twice: once as the escalation, once as a "waking the holder".
test("completion wake-up: a senior escalation mails the holder exactly once (dpage or the wake-up, never both)", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const { h, name, runDir, mailbox } = heldT8("one-mail-senior");
    inHome(h, undefined, () => {
      appendEvent(name, evQueued("worker-r1", runDir));
      appendEvent(name, evDone("worker-r1", runDir));
      // senior: true routes the APPROVED verdict to `ESCALATE senior`, which dpage handles.
      appendEvent(name, evVerdict("worker-r1", runDir, { effective: "APPROVED", senior: true }));
    });
    const r = await inHome(h, undefined, () => handleEvent(name, "verdict:worker-r1", undefined));
    assert.equal(r.outcome, "paged", JSON.stringify(r));
    const mail = mailTo(mailbox, HOLDER);
    assert.equal(mail.length, 1, `exactly one mail to the holder, not two: ${JSON.stringify(mail.map((m) => m.subject))}`);
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// 2026-11-23: a stream held by a Claude Code orchestrator (held_by cc, held_session = its peer-mail id, a
// transcript UUID) was never mailed — only `ses_` ids were — so every escalation on it paged the owner's
// desktop. dpage now mails any holder and falls back to the desktop only when no mail went out.
test("dpage: a Claude Code holder is mailed, not paged; the desktop gets only what no session received", { skip: IS_WIN ? "notify-send stub is a POSIX script" : false }, async () => {
  const CC_HOLDER = "0f3c9a2e-5b7d-4e1a-9c2f-8d6b4a1e7c30";
  const ns = stubNotifySend();
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  delete process.env.ORCH_NO_NOTIFY; // assert the real page path, through the stub
  Object.assign(process.env, ns.env);
  const escalateSenior = async (s) => {
    inHome(s.h, undefined, () => {
      appendEvent(s.name, evQueued("worker-r1", s.runDir));
      appendEvent(s.name, evDone("worker-r1", s.runDir));
      appendEvent(s.name, evVerdict("worker-r1", s.runDir, { effective: "APPROVED", senior: true })); // -> dpage
    });
    return inHome(s.h, undefined, () => handleEvent(s.name, "verdict:worker-r1", undefined));
  };
  const holdBy = (s, by, session) => {
    const f = path.join(sdir(s.h), `${s.name}.json`);
    const o = JSON.parse(fs.readFileSync(f, "utf8"));
    Object.assign(o, { held_by: by, held_session: session, held_at: new Date().toISOString() });
    fs.writeFileSync(f, JSON.stringify(o));
  };
  try {
    // held by Claude Code, mailbox present: one mail to the CC session, no desktop page
    const cc = t8Stream("cc-held");
    holdBy(cc, "cc", CC_HOLDER);
    const mailbox = mkMailbox(cc.h);
    const r = await escalateSenior(cc);
    assert.equal(r.outcome, "paged", JSON.stringify(r));
    const mail = mailTo(mailbox, CC_HOLDER);
    assert.equal(mail.length, 1, "the Claude Code holder is mailed once");
    assert.match(mail[0].body, /--by cc\n/, "the resolve hint names the holder's harness");
    assert.deepEqual(ns.reads(), [], "a reachable holder never pages the desktop");

    // held_by cc but no session to mail: left for the holder (stderr + ack file), the desktop stays quiet
    const free = t8Stream("cc-no-session");
    holdBy(free, "cc", null);
    mkMailbox(free.h);
    await escalateSenior(free);
    assert.equal(ns.reads().length, 0, "a held stream is never paged to the desktop, even without a reachable session");

    // held by Claude Code but no mailbox: still the holder's to read, not the desktop's
    const gone = t8Stream("cc-no-mailbox");
    holdBy(gone, "cc", CC_HOLDER);
    await escalateSenior(gone);
    assert.equal(ns.reads().length, 0, "an unreachable holder -> no desktop page; the escalation stays in the ack file");

    // unheld: no agent can act, so the desktop is the page
    const unheld = t8Stream("unheld");
    await escalateSenior(unheld);
    // the notice is a detached helper (notify-send --wait): give it a moment to reach the stub
    for (let i = 0; i < 100 && ns.reads().length === 0; i++) await new Promise((r) => setTimeout(r, 50));
    assert.equal(ns.reads().length, 1, "an unheld stream -> one desktop page");
    assert.match(ns.reads()[0], /Resolve in new session/, "the page carries the resolve action");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY", "PATH"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// ---------------------------------------------------------------- dpage escalation ledger, stream-scoped

const ddirOf = (h) => path.join(h, ".config", "orchestrator", "desk-daemon");
const stateOf = (h) => JSON.parse(fs.readFileSync(path.join(ddirOf(h), "state.json"), "utf8"));
const escRows = (h) => {
  try {
    return fs.readFileSync(path.join(ddirOf(h), "escalations.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  } catch {
    return [];
  }
};
// A held stream with its own run dir + ticket, as the loop's two-stream case really looks.
const heldStreamIn = (h, name) => {
  mkStream(h, name);
  const f = path.join(sdir(h), `${name}.json`);
  const o = JSON.parse(fs.readFileSync(f, "utf8"));
  Object.assign(o, { held_by: "oc", held_session: HOLDER, held_at: new Date().toISOString() });
  fs.writeFileSync(f, JSON.stringify(o));
  const runDir = runDirOf(h, name);
  mkTicket(runDir, { ticket: name });
  return { name, runDir };
};

// The hazard this ticket fixes, driven through dpage (loop-stay's test 5 mirrored): stream A escalates a
// live `verdict:worker-r1`, and stream B's identical event must still reach its own escalation instead of
// being short-circuited by A's ledger entry. Before the fix B returned `paged` with no escalation row and
// no mail — after step had already acked, i.e. consumed with no effect.
test("dpage: stream A's escalation does not suppress stream B's identical verdict:worker-r1", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home(); // ONE home: both streams share the one durable ledger
    const mailbox = mkMailbox(h);
    const verdict = { effective: "APPROVED", senior: true }; // `ESCALATE senior` -> dpage, no git
    const seed = (s) =>
      inHome(h, undefined, () => {
        appendEvent(s.name, evQueued("worker-r1", s.runDir));
        appendEvent(s.name, evDone("worker-r1", s.runDir));
        appendEvent(s.name, evVerdict("worker-r1", s.runDir, verdict));
      });
    const a = heldStreamIn(h, "dpage-a");
    const b = heldStreamIn(h, "dpage-b");
    seed(a);
    seed(b);

    const ra = await inHome(h, undefined, () => handleEvent(a.name, "verdict:worker-r1", undefined));
    assert.equal(ra.outcome, "paged", JSON.stringify(ra));
    assert.equal(escRows(h).length, 1, "stream A escalated once");
    assert.equal(escRows(h)[0].stream, "dpage-a", JSON.stringify(escRows(h)));
    assert.equal(mailTo(mailbox, HOLDER).length, 1, "A mailed its holder");
    // The scoped id is authoritative; `paged` keeps dpage's historical bare shape for older readers.
    assert.deepEqual(stateOf(h).pagedIds, ["dpage-a\u0000verdict:worker-r1"], JSON.stringify(stateOf(h)));
    assert.deepEqual(stateOf(h).paged, ["verdict:worker-r1"], "the bare key still goes to the legacy field only");

    const rb = await inHome(h, undefined, () => handleEvent(b.name, "verdict:worker-r1", undefined));
    assert.equal(rb.outcome, "paged", JSON.stringify(rb));
    // The proof that B acted: its OWN escalation row. A short-circuit appended nothing.
    const rows = escRows(h);
    assert.equal(rows.length, 2, `B escalated its own event: ${JSON.stringify(rows)}`);
    assert.match(rows[1].stream, /^dpage-b$/, "the second row belongs to stream B");
    assert.equal(mailTo(mailbox, HOLDER).length, 2, "B mailed its holder too");
    assert.deepEqual(stateOf(h).pagedIds, ["dpage-a\u0000verdict:worker-r1", "dpage-b\u0000verdict:worker-r1"], JSON.stringify(stateOf(h)));
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// The once-only contract survives the scoping: the SAME stream's same key never re-pages and never re-logs.
test("dpage: a same-stream replay of the same key pages exactly once", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home();
    const mailbox = mkMailbox(h);
    const a = heldStreamIn(h, "replay-a");
    inHome(h, undefined, () => {
      appendEvent(a.name, evQueued("worker-r1", a.runDir));
      appendEvent(a.name, evDone("worker-r1", a.runDir));
      appendEvent(a.name, evVerdict("worker-r1", a.runDir, { effective: "APPROVED", senior: true }));
    });
    const first = await inHome(h, undefined, () => handleEvent(a.name, "verdict:worker-r1", undefined));
    assert.equal(first.outcome, "paged", JSON.stringify(first));
    assert.equal(escRows(h).length, 1, "first pass escalates");
    const second = await inHome(h, undefined, () => handleEvent(a.name, "verdict:worker-r1", undefined));
    assert.equal(second.outcome, "paged", JSON.stringify(second));
    assert.equal(escRows(h).length, 1, "the same stream's replay never re-logs");
    assert.equal(mailTo(mailbox, HOLDER).length, 1, "and never re-mails");
    assert.deepEqual(stateOf(h).pagedIds, ["replay-a\u0000verdict:worker-r1"], JSON.stringify(stateOf(h)));
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// dpage's OWN guard, not handleEvent's: a critic run-done is routed to verdictFlow BEFORE handleEvent's
// `paged` short-circuit, so this path calls dpage twice for one key. A ticket without a worktree skips the
// critic-alt retry (and spawns nothing), so both pass-bys reach dpage — exactly one may log and mail.
test("dpage: its own guard stops a second page on a path handleEvent does not intercept", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home();
    const mailbox = mkMailbox(h);
    const s = heldStreamIn(h, "replay-critic");
    // No worktree: verdictFlow cannot run a verdict and cannot retry, so it pages on the first pass.
    const tp = path.join(s.runDir, "ticket.json");
    const tj = JSON.parse(fs.readFileSync(tp, "utf8"));
    delete tj.worktree;
    fs.writeFileSync(tp, JSON.stringify(tj));
    const findings = path.join(s.runDir, "findings-r1.md"); // never written: no VERDICT line
    inHome(h, undefined, () => {
      appendEvent(s.name, evQueued("critic-r1", findings, "critic"));
      appendEvent(s.name, evDone("critic-r1", findings, { agent: "critic" }));
    });
    const key = "run:critic-r1:done";
    const first = await inHome(h, undefined, () => handleEvent(s.name, key, undefined));
    assert.equal(first.outcome, "paged", JSON.stringify(first));
    assert.equal(escRows(h).length, 1, "the first verdictFlow pass pages");
    const second = await inHome(h, undefined, () => handleEvent(s.name, key, undefined));
    assert.equal(second.outcome, "paged", JSON.stringify(second));
    assert.equal(escRows(h).length, 1, "dpage's guard, not handleEvent's, stops the re-log");
    assert.equal(mailTo(mailbox, HOLDER).length, 1, "and the holder is mailed exactly once");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Upgrade path: a `state.json` written by the old code has a bare-key `paged` and no `pagedIds`. On first
// read the bare keys are adopted into the scoped ledger from escalations.jsonl (which always recorded the
// stream), so the escalation A already reported is not paged a second time — and B, a different stream with
// the same key, is not suppressed by it. No crash, no double page.
test("dpage: a pre-upgrade bare-key paged array is adopted, never re-paged, never cross-suppressing", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home();
    const mailbox = mkMailbox(h);
    const verdict = { effective: "APPROVED", senior: true };
    const a = heldStreamIn(h, "legacy-a");
    const b = heldStreamIn(h, "legacy-b");
    for (const s of [a, b])
      inHome(h, undefined, () => {
        appendEvent(s.name, evQueued("worker-r1", s.runDir));
        appendEvent(s.name, evDone("worker-r1", s.runDir));
        appendEvent(s.name, evVerdict("worker-r1", s.runDir, verdict));
      });
    // The pre-upgrade state: bare key only, exactly what origin/main's dpage wrote.
    fs.mkdirSync(ddirOf(h), { recursive: true });
    fs.writeFileSync(path.join(ddirOf(h), "state.json"), JSON.stringify({ retries: {}, paged: ["verdict:worker-r1"], errors: {} }));
    fs.writeFileSync(
      path.join(ddirOf(h), "escalations.jsonl"),
      // Two rows, different keys: adoption must attribute each bare key by KEY, not by "the only row".
      JSON.stringify({ at: new Date().toISOString(), stream: "legacy-a", key: "verdict:worker-r1", reason: "senior /x/findings-r1.md" }) +
        "\n" +
        JSON.stringify({ at: new Date().toISOString(), stream: "someone-else", key: "verdict:worker-r9", reason: "senior /y/findings-r9.md" }) +
        "\n",
    );

    // A already escalated before the upgrade: the adopted scoped entry keeps it from paging again, so the
    // escalation log stays at the pre-upgrade baseline (the two seeded rows) and nothing is mailed.
    const before = escRows(h).length;
    const ra = await inHome(h, undefined, () => handleEvent(a.name, "verdict:worker-r1", undefined));
    assert.equal(ra.outcome, "paged", JSON.stringify(ra));
    assert.equal(escRows(h).length, before, "the adopted entry never re-logs A");
    assert.equal(mailTo(mailbox, HOLDER).length, 0, "and never re-mails: adoption did not crash or double-page");

    // B shares the key but not the stream: the bare legacy entry must not silence it.
    const rb = await inHome(h, undefined, () => handleEvent(b.name, "verdict:worker-r1", undefined));
    assert.equal(rb.outcome, "paged", JSON.stringify(rb));
    const rows = escRows(h);
    assert.equal(rows.length, before + 1, `B escalated despite the bare entry: ${JSON.stringify(rows)}`);
    assert.equal(rows.at(-1).stream, "legacy-b");
    assert.equal(mailTo(mailbox, HOLDER).length, 1, "B mailed its holder");
    assert.deepEqual(stateOf(h).pagedIds, ["legacy-a\u0000verdict:worker-r1", "legacy-b\u0000verdict:worker-r1"], JSON.stringify(stateOf(h)));
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Loop-stay wrote its wake-up ids into `paged` (`wakeId(stream, key)`) before `pagedIds` existed. Those entries are
// already stream-scoped, so the upgrade copies them across: without that, an event loop-stay had already woken the
// holder for is re-processed after the upgrade and pages a second time.
test("dpage: a loop-stay-era scoped id in paged is adopted, never re-paged", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home();
    const mailbox = mkMailbox(h);
    const a = heldStreamIn(h, "staya");
    const b = heldStreamIn(h, "other");
    for (const s of [a, b])
      inHome(h, undefined, () => {
        appendEvent(s.name, evQueued("worker-r1", s.runDir));
        appendEvent(s.name, evDone("worker-r1", s.runDir));
        appendEvent(s.name, evVerdict("worker-r1", s.runDir, { effective: "APPROVED", senior: true }));
      });
    // The pre-upgrade state in loop-stay's shape: a scoped id in `paged`, no `pagedIds`, no rows needed.
    fs.mkdirSync(ddirOf(h), { recursive: true });
    fs.writeFileSync(path.join(ddirOf(h), "state.json"), JSON.stringify({ retries: {}, paged: ["staya\u0000verdict:worker-r1"], errors: {} }));

    // A's event is one loop-stay already reported: the adopted entry returns it `paged` with no row and no mail.
    const ra = await inHome(h, undefined, () => handleEvent(a.name, "verdict:worker-r1", undefined));
    assert.equal(ra.outcome, "paged", JSON.stringify(ra));
    assert.equal(escRows(h).length, 0, "the already-notified escalation is never logged again");
    assert.equal(mailTo(mailbox, HOLDER).length, 0, "and the holder is never mailed again");

    // B's identical key is genuinely new: its page writes the state, which is where the adopted entry lands.
    const rb = await inHome(h, undefined, () => handleEvent(b.name, "verdict:worker-r1", undefined));
    assert.equal(rb.outcome, "paged", JSON.stringify(rb));
    assert.equal(escRows(h).length, 1, "only B's new escalation is logged");
    assert.equal(escRows(h)[0].stream, "other", JSON.stringify(escRows(h)));
    assert.deepEqual(stateOf(h).pagedIds, ["staya\u0000verdict:worker-r1", "other\u0000verdict:worker-r1"], JSON.stringify(stateOf(h)));
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// The boarding-order edge desk-follow's review flagged (findings-r1 #1): a state file that already has
// `pagedIds` (dpage-scope wrote it) but was produced before a loop-stay wake-up id was adopted would, under
// the once-only `adoptLegacyPaged` guard, never adopt that id and the holder could be woken a second time.
// `adoptLoopStayIds` therefore runs on EVERY `readDaemonState`, before the `pagedIds` check, so a loop-stay
// id already in `pagedIds` is kept idempotently and persisted, and its wake-up is consumed — not re-paged.
test("dpage: an already-adopted loop-stay id persists on every read and its wake-up is not re-paged", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home();
    const mailbox = mkMailbox(h);
    const a = heldStreamIn(h, "staya");
    inHome(h, undefined, () => {
      appendEvent(a.name, evQueued("worker-r1", a.runDir));
      appendEvent(a.name, evDone("worker-r1", a.runDir));
      appendEvent(a.name, evVerdict("worker-r1", a.runDir, { effective: "APPROVED", senior: true }));
    });
    // The mandated seed: the loop-stay id already in `pagedIds`, no `paged` entry at all.
    fs.mkdirSync(ddirOf(h), { recursive: true });
    fs.writeFileSync(
      path.join(ddirOf(h), "state.json"),
      JSON.stringify({ retries: {}, pagedIds: ["staya\u0000verdict:worker-r1"], errors: {} }),
    );

    // readDaemonState adopts it (idempotent — already present) and the entry persists on write.
    const adopted = inHome(h, undefined, () => readDaemonState());
    assert.deepEqual(adopted.pagedIds, ["staya\u0000verdict:worker-r1"], JSON.stringify(adopted));
    assert.deepEqual(stateOf(h).pagedIds, ["staya\u0000verdict:worker-r1"], "the entry persists on write");
    const again = inHome(h, undefined, () => readDaemonState());
    assert.deepEqual(again.pagedIds, ["staya\u0000verdict:worker-r1"], `a second read is idempotent: ${JSON.stringify(again)}`);

    // Feed the same key through handleEvent -> `paged` with 0 rows and 0 mails (wake-up consumed).
    const r = await inHome(h, undefined, () => handleEvent(a.name, "verdict:worker-r1", undefined));
    assert.equal(r.outcome, "paged", JSON.stringify(r));
    assert.equal(escRows(h).length, 0, "the adopted wake-up is never logged again");
    assert.equal(mailTo(mailbox, HOLDER).length, 0, "the holder is not mailed again");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// Step failures are counted per stream+key. Before the fix they were bare-key, so stream A's four failed steps on
// `verdict:worker-r1` pushed stream B's counter over the 3-strike page and paged B for an event B never failed.
// A's step fails here for real: both streams exist, but the key is not an event, so `desk.mjs step` exits 2.
test("dpage: stream A's step failures neither page nor count against stream B", async () => {
  const saved = { ...process.env };
  delete process.env.ORCH_DAEMON_DRY_RUN;
  Object.assign(process.env, { ORCH_NO_NOTIFY: "1" });
  try {
    const h = home();
    const a = heldStreamIn(h, "err-a");
    const b = heldStreamIn(h, "err-b");
    for (let i = 0; i < 4; i++) await inHome(h, undefined, () => handleEvent(a.name, "verdict:worker-r1", undefined));
    assert.equal(escRows(h).length, 1, "A paged on its own fourth failure");
    assert.equal(escRows(h)[0].stream, "err-a", JSON.stringify(escRows(h)));

    // B's FIRST failure: pre-fix this was the fifth bare-key error, so B was paged having never failed before.
    const rb = await inHome(h, undefined, () => handleEvent(b.name, "verdict:worker-r1", undefined));
    assert.equal(rb.outcome, "error", JSON.stringify(rb));
    assert.equal(escRows(h).length, 1, "B is not paged by A's failures");
    const s1 = stateOf(h);
    assert.equal(s1.errors["err-b\u0000verdict:worker-r1"], 1, JSON.stringify(s1.errors));
    assert.equal(s1.errors["verdict:worker-r1"], undefined, "no bare-key counter is written");
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

// The critic-alt retry is per stream+key too: one stream's retry must not consume another's identical run and page it
// with `critic-failed`. Dry run keeps the retry from spawning (it increments, then returns `critic-retry`).
test("dpage: stream A's critic retry neither consumes nor pages stream B's", async () => {
  const saved = { ...process.env };
  Object.assign(process.env, { ORCH_DAEMON_DRY_RUN: "1", ORCH_NO_NOTIFY: "1" });
  try {
    const h = home();
    const a = heldStreamIn(h, "retry-a");
    const b = heldStreamIn(h, "retry-b");
    const seed = (s) =>
      inHome(h, undefined, () => {
        const findings = path.join(s.runDir, "critic-r1.md"); // never written: no VERDICT line, so the retry path runs
        appendEvent(s.name, evQueued("critic-r1", s.runDir, "critic"));
        appendEvent(s.name, evDone("critic-r1", s.runDir, { agent: "critic", out: findings }));
      });
    seed(a);
    seed(b);
    const ra = await inHome(h, undefined, () => handleEvent(a.name, "run:critic-r1:done", undefined));
    assert.equal(ra.outcome, "critic-retry", JSON.stringify(ra));
    const rb = await inHome(h, undefined, () => handleEvent(b.name, "run:critic-r1:done", undefined));
    assert.equal(rb.outcome, "critic-retry", JSON.stringify(rb));
    assert.deepEqual(Object.keys(stateOf(h).retries).sort(), ["retry-a\u0000run:critic-r1:done", "retry-b\u0000run:critic-r1:done"], JSON.stringify(stateOf(h).retries));
  } finally {
    for (const k of ["ORCH_DAEMON_DRY_RUN", "ORCH_NO_NOTIFY"]) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
});

test("status: board tickets holding a session are listed after the streams; absent otherwise", () => {
  const h = home();
  const repo = path.join(h, "repo");
  fs.mkdirSync(path.join(repo, ".opencode", "board", "tickets"), { recursive: true });
  execFileSync("git", ["-C", repo, "init", "-q", "-b", "main"]);
  const put = (id, stage, assignment) =>
    fs.writeFileSync(path.join(repo, ".opencode", "board", "tickets", `${id}.json`), JSON.stringify({ schema: 1, id, stage, assignment }));
  put("t-none", "queued", null);
  const run = (args) => spawnSync(process.execPath, [BIN, ...args], { cwd: repo, env: { ...process.env, ORCH_HOME: h, WORKER_SLOTS: "3" }, encoding: "utf8" });
  const out = run(["status"]).stdout.split("\n").filter(Boolean);
  assert.match(out[0], /^watch none — no desk watcher holds the lock$/);
  assert.match(out[1], /^slots \d+\/\d+ \(fixed\)$/);
  const j = JSON.parse(run(["status", "--json"]).stdout);
  assert.deepEqual(j.streams, []);
  assert.deepEqual(j.watch, null);
  assert.ok(Number.isInteger(j.slots.allowed) && Number.isInteger(j.slots.max), "json slots object present");
  assert.match(j.slots.reason, /^slots/);
  put("t-held", "working", { owner: "s1", session: "sess-9" });
  put("t-wait", "queued", { owner: null, session: "sess-7" });
  const lines = run(["status"]).stdout.split("\n").filter(Boolean);
  assert.deepEqual(lines.slice(2), ["ticket t-held  working  session sess-9  owner s1", "ticket t-wait  queued  session sess-7"]); // lines[0]=watch, lines[1]=slots
  assert.deepEqual(JSON.parse(run(["status", "--json"]).stdout).tickets.map((t) => t.id), ["t-held", "t-wait"]);
});

// ---------------------------------------------------------------- desk bookkeeping (Fix 1: critic round floor)

// worker-r2 done, no resume acks, findings-r1.md already on disk -> round 2 -> findings-r2.md
test("desk: worker-r2 run-done with findings-r1.md on disk reviews in round 2", () => {
  const { h, name, runDir } = t8Stream("fix1-disk");
  fs.writeFileSync(path.join(runDir, "findings-r1.md"), "r1\n");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r2", runDir));
    appendEvent(name, evDone("worker-r2", runDir));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "run:worker-r2:done"]).lines[0],
    `ACTION critic ${ticketJson} ${fwd(path.join(runDir, "worker-r2.md"))} ${fwd(path.join(runDir, "findings-r2.md"))} 2`,
  );
});

// findings-r1.md + findings-r2.md on disk -> round 3 -> findings-r3.md
test("desk: two findings files on disk bumps the run-done critic round to 3", () => {
  const { h, name, runDir } = t8Stream("fix1-disk2");
  fs.writeFileSync(path.join(runDir, "findings-r1.md"), "r1\n");
  fs.writeFileSync(path.join(runDir, "findings-r2.md"), "r2\n");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r2", runDir));
    appendEvent(name, evDone("worker-r2", runDir));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "run:worker-r2:done"]).lines[0],
    `ACTION critic ${ticketJson} ${fwd(path.join(runDir, "worker-r2.md"))} ${fwd(path.join(runDir, "findings-r3.md"))} 3`,
  );
});

// board ticket rounds.length 2 -> round 3 with nothing on disk
test("desk: board ticket counted rounds 2 floors the critic round at 3", () => {
  const { h, name, runDir } = t8Stream("fix1-board");
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "orch-board-"));
  CLEAN.push(repo);
  fs.mkdirSync(path.join(repo, ".opencode", "board", "tickets"), { recursive: true });
  fs.writeFileSync(
    path.join(repo, ".opencode", "board", "tickets", "t8.json"),
    JSON.stringify({ schema: 1, id: "t8", rounds: [{ n: 1, counted: true }, { n: 2, counted: true }] }),
  );
  const t = mkTicket(runDir, { repo });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0],
    `ACTION critic ${ticketJson} ${fwd(path.join(runDir, "worker-r1.md"))} ${fwd(path.join(runDir, "findings-r3.md"))} 3`,
  );
});

// unparseable board ticket -> no throw, falls back to round 1
test("desk: unparseable board ticket does not throw and falls back", () => {
  const { h, name, runDir } = t8Stream("fix1-badboard");
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "orch-badboard-"));
  CLEAN.push(repo);
  fs.mkdirSync(path.join(repo, ".opencode", "board", "tickets"), { recursive: true });
  fs.writeFileSync(path.join(repo, ".opencode", "board", "tickets", "t8.json"), "{not json");
  mkTicket(runDir, { repo });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "run:worker-r1:done"]).lines[0],
    `ACTION critic ${ticketJson} ${fwd(path.join(runDir, "worker-r1.md"))} ${fwd(path.join(runDir, "findings-r1.md"))} 1`,
  );
});

// ---------------------------------------------------------------- Pass bars (desk-senior-rounds)

// Helper: write a board ticket for slug t8 in a temp repo, return the repo dir.
const boardRepo = (rounds, reopens) => {
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "orch-pb-"));
  CLEAN.push(repo);
  fs.mkdirSync(path.join(repo, ".opencode", "board", "tickets"), { recursive: true });
  fs.writeFileSync(path.join(repo, ".opencode", "board", "tickets", "t8.json"),
    JSON.stringify({ schema: 1, id: "t8", rounds, reopens }));
  return repo;
};

// 1. Senior misfire (test-orphans): r1/r2 never reviewed, r3 DONE, critic APPROVED at findings-r3.md;
// board has 1 counted round whose reviewed_sha == the verdict's -> merge, not senior.
test("pass bar: APPROVED with 1 counted board round (matching sha) -> merge, not senior", () => {
  const { h, name, runDir } = t8Stream("pb-orphans");
  const repo = boardRepo([{ n: 1, counted: true, reviewed_sha: "abc" }]);
  mkTicket(runDir, { repo });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r3", runDir));
    appendEvent(name, evDone("worker-r3", runDir));
    appendEvent(name, evVerdict("worker-r3", runDir, { effective: "APPROVED", findings: path.join(runDir, "findings-r3.md"), reviewed_sha: "abc" }));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "verdict:worker-r3"]).lines[0],
    `ESCALATE merge ${ticketJson} abc`,
    "one counted round including this verdict is not > 2",
  );
});

// 2. Same but the board round is not recorded yet (0 counted) -> still merge.
test("pass bar: APPROVED with 0 counted board rounds -> merge, not senior", () => {
  const { h, name, runDir } = t8Stream("pb-nocount");
  const repo = boardRepo([{ n: 1, counted: false, reviewed_sha: "other" }]);
  mkTicket(runDir, { repo });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r3", runDir));
    appendEvent(name, evDone("worker-r3", runDir));
    appendEvent(name, evVerdict("worker-r3", runDir, { effective: "APPROVED", findings: path.join(runDir, "findings-r3.md"), reviewed_sha: "abc" }));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "verdict:worker-r3"]).lines[0],
    `ESCALATE merge ${ticketJson} abc`,
    "zero counted rounds is not > 2",
  );
});

// 3. Real third round: 3 counted board rounds, last with the verdict's sha -> senior.
test("pass bar: APPROVED with 3 counted board rounds (matching sha) -> senior", () => {
  const { h, name, runDir } = t8Stream("pb-third");
  const repo = boardRepo([
    { n: 1, counted: true, reviewed_sha: "x" },
    { n: 2, counted: true, reviewed_sha: "y" },
    { n: 3, counted: true, reviewed_sha: "abc" },
  ]);
  mkTicket(runDir, { repo });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r3", runDir));
    appendEvent(name, evDone("worker-r3", runDir));
    appendEvent(name, evVerdict("worker-r3", runDir, { effective: "APPROVED", findings: path.join(runDir, "findings-r3.md"), reviewed_sha: "abc" }));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "verdict:worker-r3"]).lines[0],
    `ESCALATE senior ${fwd(path.join(runDir, "findings-r3.md"))}`,
    "three counted rounds including this verdict is > 2",
  );
});

// 5. Rounds-exhausted not early: 1 counted round, findings-r1..r3 on disk (unreviewed), new worker DONE ->
// ACTION critic findings-r4.md 4, not rounds-exhausted (slot numbers are slots, not rounds).
test("pass bar: rounds-exhausted not early when lap < max, next free slot above max", () => {
  const { h, name, runDir } = t8Stream("pb-notearly");
  const repo = boardRepo([{ n: 1, counted: true, reviewed_sha: "x" }]);
  mkTicket(runDir, { repo });
  fs.writeFileSync(path.join(runDir, "findings-r1.md"), "r1\n");
  fs.writeFileSync(path.join(runDir, "findings-r2.md"), "r2\n");
  fs.writeFileSync(path.join(runDir, "findings-r3.md"), "r3\n");
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r4", runDir));
    appendEvent(name, evDone("worker-r4", runDir));
  });
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "run:worker-r4:done"]).lines[0],
    `ACTION critic ${ticketJson} ${fwd(path.join(runDir, "worker-r4.md"))} ${fwd(path.join(runDir, "findings-r4.md"))} 4`,
    "lap 1 < max 3: pick the next free slot even above max",
  );
});

// 6. Reopen lap: 3 counted rounds + reopens after_round 3 => lap 0, CHANGES_REQUESTED resumes (not exhausted).
test("pass bar: reopen lap resets the lap cap; CHANGES_REQUESTED resumes instead of rounds-exhausted", () => {
  const { h, name, runDir } = t8Stream("pb-reopen");
  const repo = boardRepo(
    [
      { n: 1, counted: true, reviewed_sha: "x" },
      { n: 2, counted: true, reviewed_sha: "y" },
      { n: 3, counted: true, reviewed_sha: "z" },
    ],
    [{ after_round: 3 }],
  );
  mkTicket(runDir, { repo });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED", findings: path.join(runDir, "findings-r1.md"), reviewed_sha: "z" }));
  });
  const OC_WORKER = fileURLToPath(new URL("../bin/oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
  const ticketJson = fwd(path.join(runDir, "ticket.json"));
  assert.equal(
    cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0],
    `ACTION resume-worker node ${OC_WORKER} --agent worker --dir ${fwd(runDir)} --prompt ${fwd(path.join(runDir, "findings-r1.md"))} --report ${fwd(path.join(runDir, "report.md"))} --out ${fwd(path.join(runDir, "worker-r2.md"))} --session ses_1 --stream ${name}`,
    "lap 0 after reopen: resume on the next free slot",
  );
});

// 6b. With 3 counted rounds after the reopen, CHANGES_REQUESTED pages rounds-exhausted.
test("pass bar: 3 counted rounds after a reopen pages rounds-exhausted", () => {
  const { h, name, runDir } = t8Stream("pb-reopen-exh");
  const repo = boardRepo(
    [
      { n: 1, counted: true, reviewed_sha: "x" },
      { n: 2, counted: true, reviewed_sha: "y" },
      { n: 3, counted: true, reviewed_sha: "z" },
    ],
    [{ after_round: 3 }],
  );
  // 3 more counted rounds in the new lap
  fs.writeFileSync(path.join(repo, ".opencode", "board", "tickets", "t8.json"),
    JSON.stringify({ schema: 1, id: "t8", rounds: [
      { n: 1, counted: true, reviewed_sha: "x" },
      { n: 2, counted: true, reviewed_sha: "y" },
      { n: 3, counted: true, reviewed_sha: "z" },
      { n: 4, counted: true, reviewed_sha: "a" },
      { n: 5, counted: true, reviewed_sha: "b" },
      { n: 6, counted: true, reviewed_sha: "c" },
    ], reopens: [{ after_round: 3 }] }));
  mkTicket(runDir, { repo });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    appendEvent(name, evVerdict("worker-r1", runDir, { effective: "CHANGES_REQUESTED", findings: path.join(runDir, "findings-r1.md"), reviewed_sha: "c" }));
  });
  const line = cliLines(h, ["step", name, "verdict:worker-r1"]).lines[0];
  assert.match(line, /^ESCALATE rounds-exhausted /, "lap 3 >= max 3: rounds-exhausted after reopen");
});

// INVALID first verdict; corrected APPROVED at same HEAD -> KEY verdict:<run>@2, old key resolved acked,
// merge-check reads the @2 verdict (OK on an ff fixture).
test("desk: superseding an INVALID verdict on the same sha writes verdict:<run>@2 and resolves the old key", () => {
  const { h, name, runDir } = t8Stream("fix2-same");
  const repo = gitRepo();
  mkTicket(runDir, { worktree: repo.dir, base: "main" });
  const head = repo.head;
  const bad = path.join(runDir, "bad.md");
  const good = path.join(runDir, "good.md");
  fs.writeFileSync(bad, "TESTS: npm test -> 200 pass\nno verdict line\n");
  fs.writeFileSync(good, `VERDICT: APPROVED\nTESTS: npm test -> 200 pass\nBLAST RADIUS:\n- bin/x.mjs:1 - unchanged\nSENIOR_REVIEW: not-needed - small\n`);
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
  });
  const first = cliLines(h, ["verdict", name, "worker-r1", "--findings", bad]);
  assert.equal(first.status, 0, first.stderr);
  assert.deepEqual(first.lines, [`KEY verdict:worker-r1`]);
  // the first verdict is INVALID
  const ev1 = eventsOf(h, name).find((e) => e.key === "verdict:worker-r1");
  assert.equal(ev1.effective, "INVALID");
  // corrected findings at the same HEAD -> verdict:worker-r1@2
  const second = cliLines(h, ["verdict", name, "worker-r1", "--findings", good]);
  assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(second.lines, [`KEY verdict:worker-r1@2`]);
  const ev2 = eventsOf(h, name).find((e) => e.key === "verdict:worker-r1@2");
  assert.ok(ev2, "verdict:worker-r1@2 exists");
  assert.equal(ev2.effective, "APPROVED");
  assert.equal(ev2.replaces, "verdict:worker-r1");
  // latestVerdict returns the @2 verdict
  const latest = inHome(h, undefined, () => latestVerdict(new Map(eventsOf(h, name).map((e) => [e.key, e])), "worker-r1"));
  assert.equal(latest.key, "verdict:worker-r1@2");
  // old key has a resolved ack
  const acks = inHome(h, undefined, () => readAckLines(name).filter((l) => l.key === "verdict:worker-r1" && l.resolved));
  assert.equal(acks.length, 1, "old verdict key resolved-acked");
  // merge-check reads the @2 verdict -> OK (ff fixture, clean tree, HEAD == reviewed_sha)
  const mc = cliLines(h, ["merge-check", name, "worker-r1"]);
  assert.equal(mc.status, 0, mc.stderr);
  assert.deepEqual(mc.lines, ["OK"]);
  // stepping the @2 key decides fresh (merge at the reviewed sha) — it never replays the INVALID decision —
  // and the superseded key reads DONE
  const step2 = cliLines(h, ["step", name, "verdict:worker-r1@2"]);
  assert.equal(step2.status, 0, step2.stderr);
  assert.equal(step2.lines.length, 1);
  assert.match(step2.lines[0], new RegExp(`^ESCALATE merge \\S+ticket\\.json ${head}$`));
  assert.deepEqual(cliLines(h, ["step", name, "verdict:worker-r1"]).lines, ["DONE verdict:worker-r1"]);
});

// Same flow but HEAD moved before the second verdict -> exit 2, no new event.
test("desk: superseding an INVALID verdict on a different sha exits 2 and writes nothing", () => {
  const { h, name, runDir } = t8Stream("fix2-moved");
  const repo = gitRepo();
  mkTicket(runDir, { worktree: repo.dir, base: "main" });
  const bad = path.join(runDir, "bad.md");
  const good = path.join(runDir, "good.md");
  fs.writeFileSync(bad, "TESTS: npm test -> 200 pass\nno verdict line\n");
  fs.writeFileSync(good, `VERDICT: APPROVED\nTESTS: npm test -> 200 pass\nBLAST RADIUS:\n- bin/x.mjs:1 - unchanged\nSENIOR_REVIEW: not-needed - small\n`);
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
  });
  const first = cliLines(h, ["verdict", name, "worker-r1", "--findings", bad]);
  assert.equal(first.status, 0, first.stderr);
  // move HEAD before the second verdict
  fs.appendFileSync(path.join(repo.dir, "a.txt"), "later\n");
  repo.g("add", "a.txt");
  repo.g("commit", "-m", "after the review");
  const second = cli(h, ["verdict", name, "worker-r1", "--findings", good]);
  assert.equal(second.status, 2, second.stderr);
  assert.match(second.stderr, /reviewed_sha .* !== HEAD/);
  // no @2 event was written
  assert.equal(
    eventsOf(h, name).filter((e) => e.key.startsWith("verdict:worker-r1")).length,
    1,
    "only the original verdict event exists",
  );
});

// An APPROVED first verdict is never replaced.
test("desk: an APPROVED first verdict is never superseded", () => {
  const { h, name, runDir } = t8Stream("fix2-approved");
  const repo = gitRepo();
  mkTicket(runDir, { worktree: repo.dir, base: "main" });
  const good = path.join(runDir, "good.md");
  fs.writeFileSync(good, `VERDICT: APPROVED\nTESTS: npm test -> 200 pass\nBLAST RADIUS:\n- bin/x.mjs:1 - unchanged\nSENIOR_REVIEW: not-needed - small\n`);
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
  });
  const first = cliLines(h, ["verdict", name, "worker-r1", "--findings", good]);
  assert.equal(first.status, 0, first.stderr);
  assert.deepEqual(first.lines, [`KEY verdict:worker-r1`]);
  // a second verdict for the same run prints the existing key, no @2
  const second = cliLines(h, ["verdict", name, "worker-r1", "--findings", good]);
  assert.equal(second.status, 0, second.stderr);
  assert.deepEqual(second.lines, [`KEY verdict:worker-r1`]);
  assert.equal(
    eventsOf(h, name).filter((e) => e.key.startsWith("verdict:worker-r1")).length,
    1,
    "no superseding @2 event for an APPROVED verdict",
  );
});

// ---------------------------------------------------------------- desk bookkeeping (Fix 3: patch-identical rebase)

// main gains an unrelated commit; feat rebased with the same ticket patch -> merge-check OK
test("desk: merge-check accepts a patch-identical rebase of an approved ticket", () => {
  const r = rebaseRepo(false);
  const { h, name, runDir } = t8Stream("fix3-same");
  mkTicket(runDir, { worktree: r.dir, base: "main" });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    appendEvent(name, evVerdict("worker-r1", runDir, { effective: "APPROVED", reviewed_sha: r.t }));
  });
  const mc = cliLines(h, ["merge-check", name, "worker-r1"]);
  assert.equal(mc.status, 0, mc.stderr);
  assert.deepEqual(mc.lines, ["OK"]);
  assert.match(mc.stderr || "", /same patch-id/, "stderr notes the rebase");
});

// rebase that also amends the ticket's change -> FAIL head-moved
test("desk: merge-check rejects a rebase that changed the ticket's patch", () => {
  const r = rebaseRepo(true);
  const { h, name, runDir } = t8Stream("fix3-amend");
  mkTicket(runDir, { worktree: r.dir, base: "main" });
  inHome(h, undefined, () => {
    appendEvent(name, evQueued("worker-r1", runDir));
    appendEvent(name, evDone("worker-r1", runDir));
    appendEvent(name, evVerdict("worker-r1", runDir, { effective: "APPROVED", reviewed_sha: r.t }));
  });
  const mc = cliLines(h, ["merge-check", name, "worker-r1"]);
  assert.equal(mc.status, 1, mc.stderr);
  assert.deepEqual(mc.lines, ["FAIL head-moved"]);
});

// repo helper: main M1, feat branched at M1 with ticket commit T (=reviewed_sha), then main gets M2
// unrelated and feat is rebased onto main. If amend, the ticket commit is amended after rebase.
function rebaseRepo(amend = false) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-rebase-"));
  CLEAN.push(dir);
  const g = (...args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" }).trim();
  g("init", "-b", "main");
  g("config", "user.email", "t8@example.com");
  g("config", "user.name", "t8");
  fs.writeFileSync(path.join(dir, "a.txt"), "a\n");
  g("add", "a.txt");
  g("commit", "-m", "M1 base");
  g("checkout", "-b", "feat");
  fs.appendFileSync(path.join(dir, "ticket.txt"), "ticket change\n");
  g("add", "ticket.txt");
  g("commit", "-m", "ticket change");
  const t = g("rev-parse", "HEAD");
  g("checkout", "main");
  fs.appendFileSync(path.join(dir, "unrelated.txt"), "unrelated\n");
  g("add", "unrelated.txt");
  g("commit", "-m", "M2 unrelated on main");
  g("checkout", "feat");
  g("rebase", "main");
  if (amend) {
    fs.appendFileSync(path.join(dir, "ticket.txt"), " amended\n");
    g("add", "ticket.txt");
    g("commit", "--amend", "--no-edit");
  }
  return { dir, g, t, head: g("rev-parse", "HEAD") };
}

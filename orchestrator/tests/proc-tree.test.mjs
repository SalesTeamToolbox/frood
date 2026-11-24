import test from "node:test";
import assert from "node:assert/strict";
import { spawn, execFileSync } from "node:child_process";
import { watch, parseJsonLine, parsePsLine, processStart, killPid, procState, isZombie } from "../bin/proc-tree.mjs";

// All samples are injected: no real process is ever killed except in the smoke test, which only touches its own.
const T0 = Date.parse("2026-01-01T00:00:00.000Z");
const iso = (offsetS) => new Date(T0 + offsetS * 1000).toISOString();
const P = (pid, ppid, offsetS, cmd = "") => ({ pid, ppid, start: iso(offsetS), cmd });
const ME = process.pid;

function harness(samples, opts = {}) {
  const queue = [...samples];
  const killed = [];
  const trees = new Map();
  const w = watch(100, { everyMs: 0, since: T0, ...opts, sample: async () => queue.shift() ?? [], kill: async (pid, o) => (killed.push(pid), trees.set(pid, o?.tree), true) });
  return { w, killed, trees };
}

test("a tracked live child is killed by sweep", async () => {
  const { w, killed } = harness([[P(100, 1, 1), P(200, 100, 2), P(300, 200, 3)], [P(200, 100, 2), P(300, 200, 3), P(999, 1, 0, "unrelated")]]);
  await w.observe();
  assert.equal(w.tracked().length, 2);
  const res = await w.sweep();
  assert.deepEqual(killed.sort(), [200, 300]);
  assert.deepEqual(res.map((r) => r.pid).sort(), [200, 300]);
});

test("sweep never kills with /T: rule (a) and rule (c) victims are single pids", async () => {
  const { w, trees } = harness([[P(100, 1, 1), P(200, 100, 2)], [P(200, 100, 2)]]);
  await w.observe();
  await w.sweep();
  assert.equal(trees.get(200), false);
});

test("rule (c) single-pid kill: orphan of a gone tracked parent", async () => {
  const { w, trees } = harness([[P(100, 1, 1), P(200, 100, 2)], [P(400, 200, 5)]]);
  await w.observe();
  await w.sweep();
  assert.equal(trees.get(400), false);
});

test("a recycled parent pid held by an unrelated live process: its children are never killed", async () => {
  // tracked 200 exits; pid 200 is recycled for an unrelated program Z (start later), which spawns 500
  const { w, killed } = harness([[P(100, 1, 1), P(200, 100, 2)], [P(200, 1, 50, "Z"), P(500, 200, 60, "Z child")]]);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, []);
});

test("a recycled rootPid held by an unrelated live process: its children are never killed", async () => {
  const { w, killed } = harness([[P(100, 1, 1)], [P(100, 1, 50, "Z"), P(500, 100, 60, "Z child")]]);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, []);
});

test("sample parsing: a single JSON object row, an array, garbage; POSIX lstart", () => {
  const row = { ProcessId: 5, ParentProcessId: 4, CommandLine: null, Start: "2026-01-01T00:00:00.0000000Z" };
  assert.deepEqual(parseJsonLine(JSON.stringify(row)), [{ pid: 5, ppid: 4, start: row.Start, cmd: "" }]);
  assert.equal(parseJsonLine(JSON.stringify([row, row])).length, 2);
  assert.equal(parseJsonLine("not json"), null);
  // a raw control character inside a CommandLine (PowerShell leaves some unescaped) must not lose the whole sample
  const ctl = parseJsonLine('[{"ProcessId":5,"ParentProcessId":4,"CommandLine":"a' + String.fromCharCode(26) + 'b","Start":"2026-01-01T00:00:00.0000000Z"}]');
  assert.equal(ctl[0].pid, 5);
  const ps = parsePsLine("  4242   1 Fri Nov 13 10:00:00 2026 bash -v foo");
  assert.equal(ps.pid, 4242);
  assert.equal(ps.ppid, 1);
  assert.equal(ps.cmd, "bash -v foo");
  assert.equal(ps.start, new Date("Fri Nov 13 10:00:00 2026").toISOString());
  assert.equal(parsePsLine("garbage"), null);
});

test("a reused pid with a different start is not killed", async () => {
  const { w, killed } = harness([[P(100, 1, 1), P(200, 100, 2)], [P(200, 1, 50, "someone else")]]);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, []);
});

test("an orphan of a tracked parent that started after `since` is killed", async () => {
  // 200 was tracked, then died; 400 (ppid 200) appeared between samples
  const { w, killed } = harness([[P(100, 1, 1), P(200, 100, 2)], [P(400, 200, 5, "bash -v")]]);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, [400]);
});

test("an orphan that started before `since` is never killed", async () => {
  const { w, killed } = harness([[P(100, 1, 1), P(200, 100, 2)], [P(400, 200, -30, "old")]]);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, []);
});

test("an unrelated process, even with a matching command line, is never killed", async () => {
  const { w, killed } = harness([[P(100, 1, 1, "opencode run"), P(200, 100, 2)], [P(777, 1, 10, "opencode run"), P(778, 555, 10, "bash -v")]]);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, []);
});

test("self and the ancestors of self and of the root are never killed", async () => {
  // root 100 is (bogusly) linked to its own ancestors and to us: none may become a victim
  const rows = [P(100, 7000, 1), P(7000, 7100, -100), P(7100, 1, -200), P(ME, 7100, 1), P(200, 100, 2), P(7001, 100, 3)];
  const { w, killed } = harness([rows, rows]);
  await w.observe();
  await w.sweep();
  for (const pid of [ME, 7000, 7100, 100]) assert.ok(!killed.includes(pid), `${pid} must not be killed`);
});

test("a child that predates its tracked parent (stale link) is not tracked", async () => {
  const { w } = harness([[P(100, 1, 5), P(200, 100, 2)]]);
  await w.observe();
  assert.equal(w.tracked().length, 0);
});

test("sampler failures give empty results and never throw", async () => {
  const w = watch(100, {
    everyMs: 0,
    since: T0,
    sample: async () => {
      throw new Error("no powershell");
    },
  });
  assert.deepEqual(await w.sweep(), []);
  w.stop();
  w.stop();
});

test("ORCH_NO_PROCTREE=1 disables the watcher", async () => {
  const before = process.env.ORCH_NO_PROCTREE;
  process.env.ORCH_NO_PROCTREE = "1";
  try {
    const w = watch(100, { everyMs: 0, since: T0, sample: async () => [P(100, 1, 1), P(200, 100, 2)], kill: async () => assert.fail("must not kill") });
    assert.deepEqual(await w.sweep(), []);
  } finally {
    if (before === undefined) delete process.env.ORCH_NO_PROCTREE;
    else process.env.ORCH_NO_PROCTREE = before;
  }
});

test("procState: reads the state letter after the last close paren; isZombie excludes self and the gone", () => {
  assert.equal(procState("1 (init) S 0 0 0 0 -1 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"), "S");
  assert.equal(procState("2921010 (node-MainThread) Z 252820 2921010 252820 0 -1 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0"), "Z");
  assert.equal(procState("42 (weird (name) here) R 1 2 3"), "R"); // comm may contain parens: the LAST one counts
  assert.equal(procState(""), null);
  assert.equal(procState("no parens here"), null);
  assert.equal(procState(null), null);
  assert.equal(isZombie(process.pid), false, "the test process itself is never a zombie");
  assert.equal(isZombie(-1), false);
  assert.equal(isZombie(4000000000), false, "a pid that cannot exist is gone, not a zombie");
});

test("smoke: a grandchild orphaned by killing its parent is swept", { skip: process.env.ORCH_NO_PROCTREE === "1", timeout: 60_000 }, async () => {
  const pids = [];
  let w;
  const alive = (pid) => {
    try {
      process.kill(pid, 0);
      return true;
    } catch (e) {
      return e.code === "EPERM";
    }
  };
  try {
    const since = Date.now() - 1000;
    const src = `const {spawn}=require("node:child_process");const g=spawn(process.execPath,["-e","setTimeout(()=>{},60000)"],{detached:true,stdio:"ignore",windowsHide:true});console.log(g.pid);setTimeout(()=>{},60000)`;
    const parent = spawn(process.execPath, ["-e", src], { stdio: ["ignore", "pipe", "ignore"], windowsHide: true });
    pids.push(parent.pid);
    const grand = await new Promise((res, rej) => {
      parent.stdout.once("data", (d) => res(Number(String(d).trim())));
      setTimeout(() => rej(new Error("no grandchild pid")), 15_000).unref();
    });
    pids.push(grand);
    w = watch(parent.pid, { everyMs: 300, since });
    const t = Date.now();
    while (!w.tracked().some((p) => p.pid === grand)) {
      assert.ok(Date.now() - t < 40_000, "watcher never saw the grandchild");
      await new Promise((r) => setTimeout(r, 250));
    }
    parent.kill(); // the parent only: the grandchild is now an orphan
    await new Promise((r) => parent.once("close", r));
    assert.ok(alive(grand), "grandchild should have survived its parent");
    const res = await w.sweep();
    assert.ok(
      res.some((r) => r.pid === grand),
      `sweep did not report the grandchild: ${JSON.stringify(res)}`,
    );
    await new Promise((r) => setTimeout(r, 500));
    assert.ok(!alive(grand), "grandchild still alive after sweep");
  } finally {
    w?.stop();
    for (const pid of pids) {
      try {
        if (process.platform === "win32") execFileSync("taskkill", ["/PID", String(pid), "/T", "/F"], { stdio: "ignore" });
        else process.kill(pid, "SIGKILL");
      } catch {}
    }
  }
});

function clocked(samples, clock) {
  const queue = [...samples];
  const killed = [];
  const trees = [];
  const w = watch(100, { everyMs: 5000, autoPoll: false, since: T0, now: () => clock.t, sample: async () => queue.shift() ?? [], kill: async (pid, o) => (killed.push(pid), trees.push(o?.tree), true) });
  return { w, killed, trees };
}

test("rule (c): a child born while the parent was alive is killed; one born long after it was last seen is not", async () => {
  const clock = { t: T0 + 10_000 };
  const { w, killed } = clocked([[P(100, 1, 1), P(200, 100, 2)], [P(500, 200, 12, "born while alive"), P(600, 200, 60, "born long after")]], clock);
  await w.observe(); // 200 seen alive at T0+10s
  clock.t = T0 + 70_000;
  await w.sweep();
  assert.deepEqual(killed, [500]);
});

test("rule (c): a tracked parent never seen alive by a later sample has no trusted orphans", async () => {
  const clock = { t: T0 };
  const { w, killed } = clocked([[P(100, 1, 1)], [P(500, 200, 5)]], clock);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, []);
});

test("a sampler whose start is ~1.5 s behind `since` tracks nothing without a skew shift (the bug)", async () => {
  // Default (injected sampler → skew 0): root's ps start is older than wall `since`, so rootStart is
  // never set and nothing is tracked — the production leak this fix closes.
  const { w, killed } = harness(
    [[P(100, 1, -1.5), P(200, 100, -1.5)], [P(200, 100, -1.5)]],
    { now: () => T0 }
  );
  await w.observe();
  assert.equal(w.tracked().length, 0, "rootStart never set: everything older than `since`");
  assert.deepEqual(await w.sweep(), []);
});

test("an injected clock skew (~1.5 s behind `since`) still tracks and sweeps a reparented grandchild", async () => {
  // Shifting `since` onto the ps clock (skew -1500 ms) makes root's ps start pass startOk, so the
  // grandchild is tracked and swept even though its ps start reads behind wall `since`.
  const { w, killed } = harness(
    [[P(100, 1, -1.5), P(200, 100, -1.5)], [P(200, 100, -1.5)]],
    { clockSkewMs: -1500, now: () => T0 }
  );
  await w.observe();
  assert.equal(w.tracked().length, 1, "child tracked despite ps start behind `since`");
  assert.ok(w.tracked().some((p) => p.pid === 200), "grandchild present in tracked");
  const res = await w.sweep();
  assert.deepEqual(killed, [200]);
  assert.deepEqual(res.map((r) => r.pid).sort(), [200]);
});

test("sweep: a stale-ppid row (older than the tracked parent it points at) is never killed, and never with /T", async () => {
  const clock = { t: T0 + 10_000 };
  const { w, killed, trees } = clocked([[P(100, 1, 1), P(200, 100, 5)], [P(200, 100, 5), P(300, 200, 3, "stale ppid")]], clock);
  await w.observe();
  await w.sweep();
  assert.deepEqual(killed, [200]);
  assert.ok(trees.every((t) => t === false));
});

test("processStart: this process has a start time, a pid that does not exist does not", () => {
  const start = processStart(process.pid);
  assert.match(String(start), /^\d{4}-\d{2}-\d{2}T[\d:.]+Z$/, `unexpected start time ${start}`);
  assert.equal(processStart(999999), null);
  assert.equal(processStart(0), null);
  assert.equal(processStart(-1), null);
  assert.equal(processStart("4242"), null, "a non-integer pid never reaches the command line");
});

test("killPid always returns a Promise and a dead pid resolves false", async () => {
  const p = killPid(999999);
  assert.ok(p instanceof Promise);
  assert.equal(await p, false);
});

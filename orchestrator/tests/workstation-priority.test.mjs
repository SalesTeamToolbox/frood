import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";
import { runPass, writePassLog, realSetPriority } from "../ops/workstation/agent-priority.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORKSTATION = path.join(HERE, "..", "ops", "workstation");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "ws-priority-"));
}

const ME = process.getuid();
// A uid that is never the current uid, for "another user" cases.
const OTHER_UID = process.getuid() + 1;

// /proc/<pid>/stat: field 19 is nice. f[18] = field 19 (nice), f[17] = field 18 (priority).
function makeStat(pid, comm, ppid, nice) {
  const f = [];
  f[0] = String(pid); // 1 pid
  f[1] = `(${comm})`; // 2 comm
  f[2] = "S"; // 3 state
  f[3] = String(ppid); // 4 ppid
  for (let i = 4; i <= 17; i++) f[i] = "0"; // fields 5..18
  f[18] = String(nice); // 19 nice
  for (let i = 19; i < 40; i++) f[i] = "0";
  return f.join(" ");
}

function writeProc(root, pid, { ppid = 1, comm, argv, exe, nice, uid = ME, tasks = {} }) {
  const dir = path.join(root, String(pid));
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "stat"), makeStat(pid, comm, ppid, nice));
  fs.writeFileSync(path.join(dir, "cmdline"), argv.join("\0") + "\0");
  if (exe) fs.symlinkSync(exe, path.join(dir, "exe"));
  fs.writeFileSync(path.join(dir, "status"), `Uid:\t${uid}\t${uid}\t${uid}\t${uid}\n`);
  const taskDir = path.join(dir, "task");
  fs.mkdirSync(taskDir, { recursive: true });
  for (const [tid, tnice] of Object.entries(tasks)) {
    if (tnice === undefined) continue; // missing stat -> vanished task
    fs.mkdirSync(path.join(taskDir, String(tid)), { recursive: true });
    fs.writeFileSync(path.join(taskDir, String(tid), "stat"), makeStat(tid, comm, pid, tnice));
  }
}

test("runPass renices only agent tree threads to 10, never lowers, skips non-agent/foreign/desktop", () => {
  const root = tmp();
  const calls = [];
  function setPriority(tid, value) {
    calls.push([tid, value]);
    assert.equal(value, 10, "setPriority must only ever be called with 10");
  }

  // root claude + child node with 3 tasks (0, 0, 12) + grandchild node
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  writeProc(root, 1001, {
    comm: "node",
    argv: ["node", "vitest"],
    exe: "/usr/bin/node",
    nice: 0,
    ppid: 1000,
    tasks: { 1001: 0, 1002: 0, 1003: 12 },
  });
  writeProc(root, 1002, {
    comm: "node",
    argv: ["node"],
    exe: "/usr/bin/node",
    nice: 5,
    ppid: 1001,
    tasks: { 1002: 5 },
  });
  // bash -c "grep opencode-ai" must not match through its arguments
  writeProc(root, 2000, {
    comm: "bash",
    argv: ['bash', '-c', 'grep opencode-ai'],
    exe: "/usr/bin/bash",
    nice: 0,
    tasks: { 2000: 0 },
  });
  // node … opencode-ai must match via argv[1]
  writeProc(root, 3000, {
    comm: "node",
    argv: ["node", "/app/opencode-ai"],
    exe: "/usr/bin/node",
    nice: 0,
    tasks: { 3000: 0 },
  });
  // /usr/lib/claude-desktop/claude must not match (desktop exclusion)
  writeProc(root, 4000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/usr/lib/claude-desktop/claude",
    nice: 0,
    tasks: { 4000: 0 },
  });
  // non-matching tree
  writeProc(root, 5000, {
    comm: "foo",
    argv: ["foo"],
    exe: "/usr/bin/foo",
    nice: 0,
    tasks: { 5000: 0 },
  });
  // foreign-uid process
  writeProc(root, 6000, {
    comm: "node",
    argv: ["node"],
    exe: "/usr/bin/node",
    nice: 0,
    uid: OTHER_UID,
    tasks: { 6000: 0 },
  });
  writeProc(root, 6001, {
    comm: "node",
    argv: ["node"],
    exe: "/usr/bin/node",
    nice: 0,
    uid: OTHER_UID,
    ppid: 6000,
    tasks: { 6001: 0 },
  });
  // vanished task stat missing
  writeProc(root, 8000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 8000: 0, 8001: undefined },
  });

  const res = runPass({ procRoot: root, setPriority, uid: ME });

  assert.equal(res.roots, 3, "three agent roots: claude(1000), node opencode-ai(3000) and claude(8000)");
  assert.equal(res.paused, false);

  const lowered = calls.map((c) => c[0]).sort((a, b) => a - b);
  // expected tids: 1000 (claude task), 1001+1002 (child node tasks at 0), 1002's task at 5,
  // 3000 (node opencode-ai task), 8000 (root with a vanished sibling task)
  assert.deepEqual(lowered, [1000, 1001, 1002, 1002, 3000, 8000]);
  assert.equal(calls.filter((c) => c[0] === 1003).length, 0, "task already at 12 must not be lowered");
  assert.equal(calls.filter((c) => c[0] === 2000).length, 0, "bash grep must not be touched");
  assert.equal(calls.filter((c) => c[0] === 4000).length, 0, "desktop claude must not be touched");
  assert.equal(calls.filter((c) => c[0] === 5000).length, 0, "non-matching tree must not be touched");
  assert.equal(calls.filter((c) => c[0] === 6000).length, 0, "foreign-uid process must not be touched");
  assert.equal(calls.filter((c) => c[0] === 6001).length, 0, "foreign-uid child must not be touched");
  assert.equal(calls.filter((c) => c[0] === 8001).length, 0, "vanished task must be skipped");
  // all values are 10
  assert.ok(calls.every((c) => c[1] === 10), "every setPriority call uses 10");
});

test("runPass does nothing when the pause file exists", () => {
  const state = tmp();
  fs.writeFileSync(path.join(state, "priority-guard.off"), "");
  const root = tmp();
  writeProc(root, 1000, { comm: "claude", argv: ["claude"], exe: "/home/user/.config/Claude/claude-code/claude", nice: 0, tasks: { 1000: 0 } });
  const calls = [];
  process.env.FROOD_WS_STATE = state;
  try {
    const res = runPass({ procRoot: root, setPriority: (t, v) => calls.push([t, v]), uid: ME });
    assert.equal(res.paused, true);
    assert.equal(res.lowered, 0);
    assert.deepEqual(calls, []);
  } finally {
    delete process.env.FROOD_WS_STATE;
  }
});

test("runPass never throws on a proc root it cannot read", () => {
  const calls = [];
  const res = runPass({ procRoot: "/definitely/does/not/exist", setPriority: (t, v) => calls.push([t, v]), uid: ME });
  assert.equal(res.lowered, 0);
  assert.deepEqual(calls, []);
});

// ----------------------------------------------------------- argv regex anchoring

test("argv regex: claude-code-foo path does NOT match", () => {
  const root = tmp();
  const calls = [];
  // exe is node, argv[1] contains claude-code-foo (not a path segment match)
  writeProc(root, 1000, {
    comm: "node",
    argv: ["node", "/work/claude-code-foo/x.js"],
    exe: "/usr/bin/node",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runPass({ procRoot: root, setPriority: (t, v) => calls.push([t, v]), uid: ME });
  assert.equal(res.roots, 0, "claude-code-foo path must not be an agent root");
  assert.deepEqual(calls, []);
});

test("argv regex: @anthropic-ai/claude-code/cli.js matches", () => {
  const root = tmp();
  const calls = [];
  writeProc(root, 1000, {
    comm: "node",
    argv: ["node", "/x/node_modules/@anthropic-ai/claude-code/cli.js"],
    exe: "/usr/bin/node",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runPass({ procRoot: root, setPriority: (t, v) => calls.push([t, v]), uid: ME });
  assert.equal(res.roots, 1, "@anthropic-ai/claude-code/cli.js must be an agent root");
  assert.equal(calls.length, 1);
});

test("argv regex: raider does not match aider", () => {
  const root = tmp();
  const calls = [];
  writeProc(root, 1000, {
    comm: "node",
    argv: ["node", "/usr/bin/raider"],
    exe: "/usr/bin/node",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runPass({ procRoot: root, setPriority: (t, v) => calls.push([t, v]), uid: ME });
  assert.equal(res.roots, 0, "raider must not match aider");
  assert.deepEqual(calls, []);
});

test("argv regex: aider matches exactly", () => {
  const root = tmp();
  const calls = [];
  writeProc(root, 1000, {
    comm: "node",
    argv: ["node", "aider"],
    exe: "/usr/bin/node",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runPass({ procRoot: root, setPriority: (t, v) => calls.push([t, v]), uid: ME });
  assert.equal(res.roots, 1, "aider must match as an agent root");
});

// ----------------------------------------------------------- negative nice

test("runPass raises a negative nice to 10, setter called once", () => {
  const root = tmp();
  const calls = [];
  function setPriority(tid, value) {
    calls.push([tid, value]);
    assert.equal(value, 10);
  }
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: -5 },
  });
  const res = runPass({ procRoot: root, setPriority, uid: ME });
  assert.equal(res.lowered, 1);
  assert.deepEqual(calls, [[1000, 10]]);
});

// ----------------------------------------------------------- desktop path whose name is not claude

test("runPass: desktop exe with non-claude name is not touched", () => {
  const root = tmp();
  const calls = [];
  // exe under /usr/lib/electron* but name is "foo", not claude -> not a root
  writeProc(root, 1000, {
    comm: "foo",
    argv: ["foo"],
    exe: "/usr/lib/electron/foo",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runPass({ procRoot: root, setPriority: (t, v) => calls.push([t, v]), uid: ME });
  assert.equal(res.roots, 0, "desktop exe named foo must not be an agent root");
  assert.deepEqual(calls, []);
});

// ----------------------------------------------------------- ESRCH / EPERM setter

test("runPass: ESRCH-throwing setter is skipped, not counted as eperm", () => {
  const root = tmp();
  const calls = [];
  function setPriority(tid, value) {
    calls.push([tid, value]);
    const e = new Error("no such process");
    e.code = "ESRCH";
    throw e;
  }
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runPass({ procRoot: root, setPriority, uid: ME });
  assert.equal(res.lowered, 0);
  assert.equal(res.eperm, 0);
  assert.equal(res.errors, 0);
  assert.equal(calls.length, 1);
});

test("runPass: EPERM-throwing setter is counted as eperm", () => {
  const root = tmp();
  const calls = [];
  function setPriority(tid, value) {
    calls.push([tid, value]);
    const e = new Error("permission denied");
    e.code = "EPERM";
    throw e;
  }
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runPass({ procRoot: root, setPriority, uid: ME });
  assert.equal(res.lowered, 0);
  assert.equal(res.eperm, 1);
  assert.equal(res.errors, 0);
  assert.equal(calls.length, 1);
});

// ----------------------------------------------------------- --once CLI output

function runOnceCLI(procRoot, extraEnv = {}) {
  return spawnSync(process.execPath, [path.join(WORKSTATION, "agent-priority.mjs"), "--once"], {
    env: { ...process.env, FROOD_WS_STATE: tmp(), ORCH_PROC_ROOT: procRoot, ...extraEnv },
    encoding: "utf8",
    timeout: 10000,
  });
}

test("runOnceCLI defaults FROOD_WS_STATE to an isolated temp dir", () => {
  const root = tmp();
  writeProc(root, 1000, {
    comm: "foo",
    argv: ["foo"],
    exe: "/usr/bin/foo",
    nice: 0,
    uid: OTHER_UID,
    tasks: { 1000: 0 },
  });
  // A pause file in the (fake) HOME default state dir must NOT pause the run:
  // the helper injects its own FROOD_WS_STATE, so a real pause file can never
  // affect a test.
  const fakeHome = tmp();
  const defaultState = path.join(fakeHome, ".local", "state", "frood-workstation");
  fs.mkdirSync(defaultState, { recursive: true });
  fs.writeFileSync(path.join(defaultState, "priority-guard.off"), "");
  // No FROOD_WS_STATE passed: the helper must isolate state so the pause file
  // above (standing in for a real one) is never seen.
  const res = runOnceCLI(root, { HOME: fakeHome });
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stdout, /lowered 0 eperm 0 errors 0 roots 0/);
  assert.doesNotMatch(res.stdout, /paused/);
});

test("runPass: Node ERR_SYSTEM_ERROR shape with info.code ESRCH is skipped", () => {
  const state = tmp();
  const root = tmp();
  const calls = [];
  function setPriority(tid, value) {
    calls.push([tid, value]);
    const e = new Error("no such process");
    e.code = "ERR_SYSTEM_ERROR";
    e.info = { code: "ESRCH" };
    throw e;
  }
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  process.env.FROOD_WS_STATE = state;
  try {
    const res = runPass({ procRoot: root, setPriority, uid: ME });
    assert.equal(res.lowered, 0);
    assert.equal(res.eperm, 0);
    assert.equal(res.errors, 0);
    assert.equal(calls.length, 1);
  } finally {
    delete process.env.FROOD_WS_STATE;
  }
});

test("runPass: Node ERR_SYSTEM_ERROR shape with info.code EPERM is counted as eperm", () => {
  const state = tmp();
  const root = tmp();
  const calls = [];
  function setPriority(tid, value) {
    calls.push([tid, value]);
    const e = new Error("operation not permitted");
    e.code = "ERR_SYSTEM_ERROR";
    e.info = { code: "EPERM" };
    throw e;
  }
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  process.env.FROOD_WS_STATE = state;
  try {
    const res = runPass({ procRoot: root, setPriority, uid: ME });
    assert.equal(res.lowered, 0);
    assert.equal(res.eperm, 1);
    assert.equal(res.errors, 0);
    assert.equal(calls.length, 1);
  } finally {
    delete process.env.FROOD_WS_STATE;
  }
});

test("realSetPriority on a pid that cannot exist throws with mapped code ESRCH", () => {
  // pid_max itself is never a valid pid, so this never touches a real process.
  const pidMax = Number(fs.readFileSync("/proc/sys/kernel/pid_max", "utf8").trim());
  assert.ok(Number.isInteger(pidMax) && pidMax > 0, "pid_max must be a positive integer");
  assert.throws(
    () => realSetPriority(pidMax, 10),
    (err) => (err?.info?.code ?? err?.code) === "ESRCH",
    "expected ESRCH for a pid that cannot exist",
  );
});

test("--once CLI: no agent roots -> lowered 0 eperm 0 roots 0", () => {
  const root = tmp();
  // Only foreign-uid and non-agent processes
  writeProc(root, 1000, {
    comm: "foo",
    argv: ["foo"],
    exe: "/usr/bin/foo",
    nice: 0,
    uid: OTHER_UID,
    tasks: { 1000: 0 },
  });
  const res = runOnceCLI(root);
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stdout, /lowered 0 eperm 0 errors 0 roots 0/);
});

test("--once CLI: all pids outside uid -> nothing lowered", () => {
  const root = tmp();
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    uid: OTHER_UID,
    tasks: { 1000: 0 },
  });
  const res = runOnceCLI(root);
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stdout, /lowered 0 eperm 0 errors 0 roots 0/);
});

test("--once CLI: vanished pids are skipped silently", () => {
  const root = tmp();
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  // Remove the stat file for pid 1000 so it "vanishes" between gatherSnapshot and readProc
  fs.rmSync(path.join(root, "1000", "stat"));
  const res = runOnceCLI(root);
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stdout, /lowered 0 eperm 0 errors 0 roots 0/);
});

// ----------------------------------------------------------- FROOD_WS_STATE pause via --once

test("--once CLI: pause file prints paused and exits 0", () => {
  const state = tmp();
  fs.writeFileSync(path.join(state, "priority-guard.off"), "");
  const root = tmp();
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const res = runOnceCLI(root, { FROOD_WS_STATE: state });
  assert.equal(res.status, 0, res.stderr);
  assert.match(res.stdout, /paused/);
});

// ----------------------------------------------------------- log rotation over 512 KB

test("runPass: log rotates when over 512 KB", () => {
  const state = tmp();
  const lf = path.join(state, "priority-guard.log");
  fs.mkdirSync(state, { recursive: true });
  fs.writeFileSync(lf, "x".repeat(600 * 1024));
  // Directly exercise writePassLog via doPass-equivalent: runPass with a lowered tid
  // then writePassLog (doPass calls writePassLog only when something changed).
  const root = tmp();
  writeProc(root, 1000, {
    comm: "claude",
    argv: ["claude"],
    exe: "/home/user/.config/Claude/claude-code/claude",
    nice: 0,
    tasks: { 1000: 0 },
  });
  const calls = [];
  process.env.FROOD_WS_STATE = state;
  try {
    const res = runPass({ procRoot: root, setPriority: (t, v) => calls.push([t, v]), uid: ME, log: (l) => console.log(l) });
    assert.ok(res.lowered > 0, "should have lowered something to trigger log write");
    // writePassLog is called by doPass (not runPass directly); call it here to test rotation
    writePassLog(res.lowered, res.eperm, res.errors, res.roots);
    // .log.1 should exist (rotated)
    assert.ok(fs.existsSync(lf + ".1"), "rotated log .log.1 should exist");
    // Current log should be small (just this pass's line)
    const curSize = fs.statSync(lf).size;
    assert.ok(curSize < 512 * 1024, `current log ${curSize} bytes should be under 512 KB`);
  } finally {
    delete process.env.FROOD_WS_STATE;
  }
});

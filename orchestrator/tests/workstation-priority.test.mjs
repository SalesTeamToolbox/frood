import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "os";
import path from "path";
import { fileURLToPath } from "node:url";
import { runPass } from "../ops/workstation/agent-priority.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const WORKSTATION = path.join(HERE, "..", "ops", "workstation");

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "ws-priority-"));
}

const ME = process.getuid();

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
    uid: 999,
    tasks: { 6000: 0 },
  });
  writeProc(root, 6001, {
    comm: "node",
    argv: ["node"],
    exe: "/usr/bin/node",
    nice: 0,
    uid: 999,
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

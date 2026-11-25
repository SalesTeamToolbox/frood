import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import { measure, level, shouldNotify, reportText } from "../bin/session-pressure.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "session-pressure.mjs");
const CLEAN = [];
const REAL_HOME = os.homedir();
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-sp-"));
  CLEAN.push(h);
  return h;
}

// Run fn with HOME and ORCH_HOME both pointing at a temp dir, then restore.
function withHome(h, fn) {
  const savedHome = process.env.HOME;
  const savedOrch = process.env.ORCH_HOME;
  process.env.HOME = h;
  process.env.ORCH_HOME = h;
  try {
    return fn();
  } finally {
    if (savedHome === undefined) delete process.env.HOME;
    else process.env.HOME = savedHome;
    if (savedOrch === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = savedOrch;
  }
}

// Build a fixture /proc tree at `root`. meminfo kB, loadavg, and per-pid dirs.
function procRoot(procs, memAvailableKb = 15_000_000, load = 0.5) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-proc-"));
  CLEAN.push(root);
  fs.writeFileSync(
    path.join(root, "meminfo"),
    `MemAvailable: ${memAvailableKb} kB\nMemFree: 1000000 kB\nBuffers: 100000 kB\nCached: 2000000 kB\n`,
  );
  fs.writeFileSync(path.join(root, "loadavg"), `${load} 0.6 0.7 1/100 1234\n`);
  for (const p of procs) {
    const pdir = path.join(root, String(p.pid));
    fs.mkdirSync(pdir, { recursive: true });
    fs.writeFileSync(path.join(pdir, "comm"), (p.comm ?? "claude") + "\n");
    const cmd = p.cmd ?? `/usr/bin/claude\0--resume=${p.id}\0--flag`;
    fs.writeFileSync(path.join(pdir, "cmdline"), cmd);
    if (p.rss != null) fs.writeFileSync(path.join(pdir, "status"), `VmRSS: ${p.rss} kB\n`);
    fs.writeFileSync(path.join(pdir, "stat"), `(${p.comm ?? "claude"}) S 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 1 ${100} 1 1 1 1\n`);
    if (p.cwd) {
      try {
        fs.mkdirSync(path.dirname(p.cwd), { recursive: true });
        fs.symlinkSync(p.cwd, path.join(pdir, "cwd"));
      } catch {} // cwd target may not be creatable in fixtures; cwd then reads as null
    }
  }
  return root;
}

// Write a transcript under HOME/.claude/projects/<slug>/<id>.jsonl with a fixed mtime.
// cwd is expected to be under HOME so the slug is the cwd basename.
function writeTranscript(homeDir, cwd, id, mtimeSec) {
  const slug = cwd.replace(homeDir, "").replace(/^\/+/, "").replace(/\//g, "-") || "home";
  const dir = path.join(homeDir, ".claude", "projects", slug);
  fs.mkdirSync(dir, { recursive: true });
  const file = path.join(dir, `${id}.jsonl`);
  fs.writeFileSync(file, `{"type":"session","sessionId":"${id}","title":"title for ${id}"}\n`);
  fs.utimesSync(file, mtimeSec, mtimeSec);
  return file;
}

const MIN = 60 * 1000;
const T = 1_700_000_000_000; // fixed clock (ms)

test("level: ok when everything is within limits", () => {
  assert.equal(level(15, 5, 0.5), "ok");
});

test("level: warn when MemAvailable < 8 GB", () => {
  assert.equal(level(6, 5, 0.5), "warn");
});

test("level: warn when more than 12 claude sessions", () => {
  assert.equal(level(15, 13, 0.5), "warn");
});

test("level: warn when load5 > 6", () => {
  assert.equal(level(15, 5, 7), "warn");
});

test("level: critical when MemAvailable < 4 GB", () => {
  assert.equal(level(3, 5, 0.5), "critical");
});

test("level: critical when load5 > 7.5", () => {
  assert.equal(level(15, 5, 8), "critical");
});

test("level: critical wins over warn", () => {
  assert.equal(level(3, 13, 8), "critical");
});

test("measure: ok level from a fixture", () => {
  const root = procRoot([{ pid: 100, id: "a1", cwd: "/home/user/r1" }]);
  const m = measure(root, () => T);
  assert.equal(m.freeGb > 8, true);
  assert.equal(m.claudeN, 1);
  assert.equal(m.load, 0.5);
});

test("measure: warn level from low MemAvailable", () => {
  const root = procRoot([{ pid: 100, id: "a1", cwd: "/home/user/r1" }], 6_000_000); // ~5.7 GB
  const m = measure(root, () => T);
  assert.equal(level(m.freeGb, m.claudeN, m.load), "warn");
});

test("measure: critical level from very low MemAvailable", () => {
  const root = procRoot([{ pid: 100, id: "a1", cwd: "/home/user/r1" }], 3_000_000); // ~2.9 GB
  const m = measure(root, () => T);
  assert.equal(level(m.freeGb, m.claudeN, m.load), "critical");
});

test("measure: missing /proc is a no-op (freeGb null, no throw)", () => {
  const m = measure("/definitely/does/not/exist", () => T);
  assert.equal(m.freeGb, null);
  assert.equal(m.claudeN, 0);
  assert.deepEqual(m.sessions, []);
  assert.deepEqual(m.idle, []);
});

test("measure: counts mcp_server.py and opencode separately", () => {
  const root = procRoot([
    { pid: 100, id: "a1", comm: "claude", cwd: "/home/user/r1" },
    { pid: 200, cmd: "/usr/bin/python\0mcp_server.py\0", comm: "python", rss: 140000, cwd: "/home/user/r1" },
    { pid: 300, cmd: "/usr/bin/opencode\0", comm: "opencode", rss: 800000, cwd: "/home/user/r1" },
  ]);
  const m = measure(root, () => T);
  assert.equal(m.claudeN, 1);
  assert.equal(m.mcpN, 1);
  assert.equal(m.mcpRss, 140000 / (1024 * 1024));
  assert.equal(m.ocN, 1);
});

test("measure: idle sessions listed oldest first (transcript mtime)", () => {
  const h = home();
  const cwd = path.join(h, "myrepo");
  const root = procRoot([
    { pid: 100, id: "id-oldest", cwd },
    { pid: 101, id: "id-mid", cwd },
    { pid: 102, id: "id-newest", cwd },
    { pid: 103, id: "id-active", cwd },
  ]);
  const clock = () => T;
  // idle ages: 60 min, 45 min, 35 min (all >= 30 min), plus one active (5 min)
  writeTranscript(h, cwd, "id-oldest", (T - 60 * MIN) / 1000);
  writeTranscript(h, cwd, "id-mid", (T - 45 * MIN) / 1000);
  writeTranscript(h, cwd, "id-newest", (T - 35 * MIN) / 1000);
  writeTranscript(h, cwd, "id-active", (T - 5 * MIN) / 1000);
  const m = withHome(h, () => measure(root, clock));
  assert.equal(m.idle.length, 3);
  assert.deepEqual(m.idle.map((s) => s.sessionId), ["id-oldest", "id-mid", "id-newest"]);
  assert.ok(m.idle[0].idleMs >= m.idle[1].idleMs);
  assert.ok(m.idle[1].idleMs >= m.idle[2].idleMs);
  // every idle entry carries cwd, id prefix, rss
  for (const s of m.idle) {
    assert.equal(s.cwd, cwd);
    assert.equal(s.sessionId.slice(0, 8), s.sessionId.slice(0, 8));
    assert.ok(s.idleMs >= 30 * MIN);
  }
});

test("measure: no idle sessions when none reach 30 min", () => {
  const h = home();
  const cwd = path.join(h, "myrepo");
  const root = procRoot([{ pid: 100, id: "a1", cwd }]);
  writeTranscript(h, cwd, "a1", (T - 5 * MIN) / 1000);
  const m = withHome(h, () => measure(root, () => T));
  assert.deepEqual(m.idle, []);
});

test("reportText: summary line + idle list + archive line", () => {
  const h = home();
  const cwd = path.join(h, "myrepo");
  const root = procRoot([
    { pid: 100, id: "id-oldest", cwd, rss: 500_000 },
  ]);
  writeTranscript(h, cwd, "id-oldest", (T - 40 * MIN) / 1000);
  let m;
  let text;
  withHome(h, () => {
    m = measure(root, () => T);
    text = reportText(m);
  });
  assert.ok(text.includes("sessions,"), "summary line");
  assert.ok(text.includes("free; load"), "summary line");
  assert.ok(text.includes("idle sessions (oldest first):"), "idle header");
  assert.ok(text.includes("id-oldes"), "session id prefix");
  assert.ok(text.includes("40m"), "idle age");
  assert.ok(text.includes("title for id-oldest"), "transcript title");
  assert.ok(text.includes("archive finished sessions in the Claude app sidebar"), "archive line");
});

test("shouldNotify: first warn notifies (no previous state)", () => {
  const d = shouldNotify({}, T, "warn");
  assert.equal(d.notify, true);
});

test("shouldNotify: unchanged warn within 60 min is suppressed", () => {
  const prev = { lastLevel: "warn", lastNotifyMs: T };
  const d = shouldNotify(prev, T + 30 * MIN, "warn");
  assert.equal(d.notify, false);
  assert.equal(d.reason, "unchanged");
});

test("shouldNotify: unchanged warn after 60 min notifies", () => {
  const prev = { lastLevel: "warn", lastNotifyMs: T };
  const d = shouldNotify(prev, T + 61 * MIN, "warn");
  assert.equal(d.notify, true);
  assert.equal(d.reason, "60 min elapsed");
});

test("shouldNotify: level rising warn->critical notifies", () => {
  const prev = { lastLevel: "warn", lastNotifyMs: T };
  const d = shouldNotify(prev, T + 5 * MIN, "critical");
  assert.equal(d.notify, true);
  assert.equal(d.reason, "level rose");
});

test("shouldNotify: ok never notifies", () => {
  const prev = { lastLevel: "warn", lastNotifyMs: T };
  assert.equal(shouldNotify(prev, T + 61 * MIN, "ok").notify, false);
});

test("shouldNotify: ok->warn on first occurrence notifies (overdue, no lastNotify)", () => {
  const d = shouldNotify({ lastLevel: "ok" }, T, "warn");
  assert.equal(d.notify, true);
});

test("CLI: runs and exits 0 with ORCH_NO_NOTIFY=1 (state written to temp ORCH_HOME)", () => {
  const h = home();
  const env = { ...process.env, HOME: h, ORCH_HOME: h, ORCH_NO_NOTIFY: "1" };
  const r = spawnSync(process.execPath, [BIN], { env, encoding: "utf8", timeout: 30_000 });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /\d+ sessions/);
});

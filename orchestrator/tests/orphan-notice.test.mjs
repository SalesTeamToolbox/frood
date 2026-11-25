// Orphan notice text + launch plan: "waiting on you" when a holder session still exists,
// today's "no live session" behaviour otherwise (temp ORCH_HOME, stub notify-send).
import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { noticeText, launchPlan } from "../bin/orphan-notice.mjs";
import { appendAck } from "../bin/handoff.mjs";

const NOTICE = path.resolve(import.meta.dirname, "..", "bin", "orphan-notice.mjs");
const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true });
});
const mkdtemp = () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-onotice-"));
  CLEAN.push(d);
  return d;
};
const MIN = 60_000;
const iso = (agoMin) => new Date(Date.now() - agoMin * MIN).toISOString();
const sdir = (h) => path.join(h, ".config", "orchestrator", "streams");

function withHome(h, env, fn) {
  const keys = ["ORCH_HOME", "ORCH_ORPHAN_MIN", "ORCH_NO_NOTIFY", "ORCH_LAUNCH_CMD", ...Object.keys(env)];
  const saved = Object.fromEntries(keys.map((k) => [k, process.env[k]]));
  for (const k of keys) delete process.env[k];
  Object.assign(process.env, { ORCH_HOME: h, ...env });
  try {
    return fn();
  } finally {
    for (const k of keys) {
      if (saved[k] === undefined) delete process.env[k];
      else process.env[k] = saved[k];
    }
  }
}
function mkStream(h, name, { ageMin = 0, repo = "", ...over } = {}) {
  fs.mkdirSync(sdir(h), { recursive: true });
  const at = iso(ageMin);
  const ptr = { name, repo, plan: "", status: "active", next: "n", done: "", waiting: "", written_at: at, written_by: "", consumed_at: null, done_at: null, held_by: null, held_session: null, held_at: null, ...over };
  fs.writeFileSync(path.join(sdir(h), `${name}.json`), JSON.stringify(ptr));
}
// Write a live Claude session file <home>/.claude/sessions/<pid>.json whose session id matches `heldSessionId`
// and whose pid is alive (process.pid always is).
function holderSessionFile(h, heldSessionId, { idleMin = 10, title = "The Work" } = {}) {
  const sdir2 = path.join(h, ".claude", "sessions");
  fs.mkdirSync(sdir2, { recursive: true });
  const pid = String(process.pid);
  fs.writeFileSync(path.join(sdir2, `${pid}.json`), JSON.stringify({
    sessionId: heldSessionId, cwd: "/repo", name: title, status: "idle",
    statusUpdatedAt: Date.now() - idleMin * MIN,
  }));
  return pid;
}

test("noticeText: holder session -> 'waiting on you' names the session and its idle age", () => {
  const t = noticeText("s1", [{ reason: "senior /x/run:t1/worker-r1:done" }], { id: "ses_abc123", title: "The Work", idleMs: 2 * 3600_000 });
  assert.equal(t, 's1: 1 escalation(s) waiting on you — session "The Work" idle 2h — senior /x/run:t1/worker-r1:done');
});
test("noticeText: holder session, no title -> uses id prefix", () => {
  const t = noticeText("s1", [{ reason: "r" }], { id: "ses_abc123def456", title: null, idleMs: 900_000 });
  assert.equal(t, 's1: 1 escalation(s) waiting on you — session "ses_abc1" idle 15m — r');
});
test("noticeText: no holder -> unchanged 'no live session'", () => {
  const t = noticeText("s1", [{ reason: "r" }]);
  assert.equal(t, 's1: 1 escalation(s), no live session — r');
});
test("noticeText: multiple escalations, truncated reasons", () => {
  const esc = [{ reason: "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa" }, { reason: "b" }, { reason: "c" }];
  const t = noticeText("s1", esc);
  assert.match(t, /; \+1 more/);
});

function terminalLaunchPlan(h, stream, s, holder) {
  const cfgDir = path.join(h, ".config", "orchestrator");
  fs.mkdirSync(cfgDir, { recursive: true });
  fs.writeFileSync(path.join(cfgDir, "launch.json"), '{"mode":"terminal"}');
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    return launchPlan(stream, s, holder);
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
}
test("launchPlan: holder cc terminal resumes with --resume", () => {
  const h = mkdtemp();
  const repo = fs.realpathSync(mkdtemp());
  const s = { repo, held_by: "cc", held_session: "ses_x" };
  const p = terminalLaunchPlan(h, "my-stream", s, { id: "ses_x" });
  assert.deepEqual(p.argv, ["xdg-terminal-exec", "--", "claude", "--resume", "ses_x"]);
  assert.equal(p.cwd, repo);
});
test("launchPlan: holder oc terminal uses --session", () => {
  const h = mkdtemp();
  const repo = fs.realpathSync(mkdtemp());
  const s = { repo, held_by: "oc", held_session: "ses_x" };
  const p = terminalLaunchPlan(h, "my-stream", s, { id: "ses_x" });
  assert.deepEqual(p.argv, ["xdg-terminal-exec", "--", "opencode", "--session", "ses_x"]);
  assert.equal(p.cwd, repo);
});
test("launchPlan: no holder -> today's behaviour (claude /frood-next)", () => {
  const h = mkdtemp();
  const repo = fs.realpathSync(mkdtemp());
  const cfgDir = path.join(h, ".config", "orchestrator");
  fs.mkdirSync(cfgDir, { recursive: true });
  fs.writeFileSync(path.join(cfgDir, "launch.json"), '{"mode":"terminal"}');
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    const s = { repo, held_by: "cc", held_session: null };
    const p = launchPlan("my-stream", s);
    assert.deepEqual(p.argv, ["xdg-terminal-exec", "--", "claude", "/frood-next my-stream"]);
    assert.equal(p.cwd, repo);
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
});
test("launchPlan: no holder -> oc uses --prompt", () => {
  const h = mkdtemp();
  const repo = fs.realpathSync(mkdtemp());
  const cfgDir = path.join(h, ".config", "orchestrator");
  fs.mkdirSync(cfgDir, { recursive: true });
  fs.writeFileSync(path.join(cfgDir, "launch.json"), '{"mode":"terminal"}');
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    const s = { repo, held_by: "oc", held_session: null };
    const p = launchPlan("my-stream", s);
    assert.deepEqual(p.argv, ["xdg-terminal-exec", "--", "opencode", "--prompt", "/frood-next my-stream"]);
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
});
test("launchPlan: ORCH_LAUNCH_CMD substitutes {session} with a holder and empties it without", () => {
  const s = { repo: "/repo", held_by: "cc", held_session: "ses_x" };
  process.env.ORCH_LAUNCH_CMD = "go {stream} {harness} {session}";
  try {
    const p1 = launchPlan("my-stream", s, { id: "ses_x" });
    assert.equal(p1.shell, "go my-stream cc ses_x");
    const p2 = launchPlan("my-stream", s);
    assert.equal(p2.shell, "go my-stream cc ");
  } finally {
    delete process.env.ORCH_LAUNCH_CMD;
  }
});

// ---- main: button label via stubbed notify-send ---------------------------------------------

function stubs(printed) {
  const bin = mkdtemp();
  const log = path.join(bin, "notify.log");
  const out = path.join(bin, "launch.log");
  fs.writeFileSync(path.join(bin, "notify-send"), `#!/bin/sh\necho "$@" >> "${log}"\n${printed ? `echo ${printed}\n` : ""}`, { mode: 0o755 });
  fs.writeFileSync(path.join(bin, "rec.sh"), `#!/bin/sh\necho "args=$*" >> "${out}"\n`, { mode: 0o755 });
  return { bin, log, out };
}
function runNotice(h, st, env = {}) {
  return spawnSync(process.execPath, [NOTICE, "hs"], { env: { ...process.env, ORCH_HOME: h, ORCH_NO_NOTIFY: "", PATH: `${st.bin}${path.delimiter}${process.env.PATH}`, ...env }, encoding: "utf8" });
}

test("main: holder session -> button 'Open session', waiting-on-you text", () => {
  const h = mkdtemp();
  const repo = fs.realpathSync(mkdtemp());
  holderSessionFile(h, "ses_live", { idleMin: 10 });
  mkStream(h, "hs", { repo, held_by: "cc", held_session: "ses_live", held_at: iso(300) });
  withHome(h, {}, () => appendAck("hs", "run:t1/worker-r1:done", "ESCALATE senior /x/run:t1/worker-r1:done"));
  const st = stubs("Open session");
  const r = runNotice(h, st, { ORCH_LAUNCH_CMD: `${path.join(st.bin, "rec.sh")} {stream} {harness} {session}` });
  assert.equal(r.status, 0);
  const said = fs.readFileSync(st.log, "utf8");
  assert.match(said, /-A resolve=Open session/);
  assert.match(said, /waiting on you/);
});
test("main: no holder session -> button 'Resolve in new session', today's text", () => {
  const h = mkdtemp();
  const repo = fs.realpathSync(mkdtemp());
  mkStream(h, "hs", { repo, held_by: "oc", held_at: iso(300) });
  withHome(h, {}, () => appendAck("hs", "run:t1/worker-r1:done", "ESCALATE senior /x/run:t1/worker-r1:done"));
  const st = stubs("Resolve in new session");
  const r = runNotice(h, st, { ORCH_LAUNCH_CMD: `${path.join(st.bin, "rec.sh")} {stream} {harness} {session}` });
  assert.equal(r.status, 0);
  const said = fs.readFileSync(st.log, "utf8");
  assert.match(said, /-A resolve=Resolve in new session/);
  assert.match(said, /no live session/);
});

// Orphaned-stream detection, the once-per-stream ledger and the notice helper (temp ORCH_HOME, stub notify-send).
import { test, after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { DatabaseSync } from "node:sqlite";
import { appendAck } from "../bin/handoff.mjs";
import { openEscalations, orphanThresholdMs, streamOrphaned } from "../bin/orphan.mjs";
import { sweepOrphans, readDaemonState } from "../bin/desk.mjs";

const NOTICE = path.resolve(import.meta.dirname, "..", "bin", "orphan-notice.mjs");
const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true });
});
const mkdtemp = () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-orphan-"));
  CLEAN.push(d);
  return d;
};
const MIN = 60_000;
const iso = (agoMin) => new Date(Date.now() - agoMin * MIN).toISOString();
const sdir = (h) => path.join(h, ".config", "orchestrator", "streams");

function withHome(h, env, fn) {
  const keys = ["ORCH_HOME", "ORCH_ORPHAN_MIN", "ORCH_NO_NOTIFY", "ORCH_DAEMON_DRY_RUN", "PEER_MAIL_OC_DB", ...Object.keys(env)];
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

// Every timestamp on the pointer defaults to `ageMin` minutes ago, so "idle" is one knob.
function mkStream(h, name, { ageMin = 0, repo = "", ...over } = {}) {
  fs.mkdirSync(sdir(h), { recursive: true });
  const at = iso(ageMin);
  const ptr = { name, repo, plan: "", status: "active", next: "n", done: "", waiting: "", written_at: at, written_by: "", consumed_at: null, done_at: null, held_by: null, held_session: null, held_at: null, ...over };
  fs.writeFileSync(path.join(sdir(h), `${name}.json`), JSON.stringify(ptr));
}
const mkPeers = (h, rows) => {
  const file = path.join(h, ".local", "share", "opencode-peer-mail", "mailbox.db");
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const db = new DatabaseSync(file);
  db.exec("CREATE TABLE IF NOT EXISTS peers (session_id TEXT PRIMARY KEY, harness TEXT, title TEXT, directory TEXT, branch TEXT, first_seen INTEGER, last_seen INTEGER);");
  for (const [id, agoMin] of Object.entries(rows)) db.prepare("INSERT INTO peers VALUES (?, 'claude', '', '', '', ?, ?)").run(id, Date.now(), Date.now() - agoMin * MIN);
  db.close();
};
const escalate = (name, key = "run:t1/worker-r1:done") => appendAck(name, key, `ESCALATE senior /x/${key}`);

test("orphaned: unheld stream with an open escalation; quiet without one or once resolved", () => {
  const h = mkdtemp();
  mkStream(h, "s1");
  withHome(h, {}, () => {
    assert.equal(streamOrphaned("s1").orphaned, false, "no escalation, no orphan");
    escalate("s1");
    const r = streamOrphaned("s1");
    assert.equal(r.orphaned, true);
    assert.match(r.why, /nobody holds/);
    assert.equal(r.escalations.length, 1);
    appendAck("s1", "run:t1/worker-r1:done", "resolved", { resolved: true });
    assert.equal(streamOrphaned("s1").orphaned, false, "a resolved escalation is not open");
  });
});

test("orphaned: done and parked streams are never paged", () => {
  const h = mkdtemp();
  mkStream(h, "dn", { status: "done" });
  mkStream(h, "pk", { status: "parked" });
  withHome(h, {}, () => {
    escalate("dn");
    escalate("pk");
    assert.equal(streamOrphaned("dn").orphaned, false);
    assert.equal(streamOrphaned("pk").orphaned, false);
  });
});

test("orphaned: held with a session -> its peer-mail last_seen decides", () => {
  const h = mkdtemp();
  mkPeers(h, { "live-sess": 5, "dead-sess": 120 });
  mkStream(h, "lv", { ageMin: 300, held_by: "cc", held_session: "live-sess", held_at: iso(300) });
  mkStream(h, "dd", { ageMin: 300, held_by: "cc", held_session: "dead-sess", held_at: iso(300) });
  withHome(h, {}, () => {
    escalate("lv");
    escalate("dd");
    assert.equal(streamOrphaned("lv").orphaned, false, "recent last_seen: live holder keeps peer-mail only");
    const d = streamOrphaned("dd");
    assert.equal(d.orphaned, true);
    assert.match(d.why, /silent 120m/);
  });
});

test("orphaned: ORCH_ORPHAN_MIN moves the threshold", () => {
  const h = mkdtemp();
  mkPeers(h, { sess: 30 });
  mkStream(h, "t", { ageMin: 300, held_by: "cc", held_session: "sess", held_at: iso(300) });
  withHome(h, {}, () => {
    escalate("t");
    assert.equal(orphanThresholdMs(), 60 * MIN);
    assert.equal(streamOrphaned("t").orphaned, false);
  });
  withHome(h, { ORCH_ORPHAN_MIN: "10" }, () => assert.equal(streamOrphaned("t").orphaned, true));
  withHome(h, { ORCH_ORPHAN_MIN: "junk" }, () => assert.equal(orphanThresholdMs(), 60 * MIN));
});

test("orphaned: a held session in neither store is judged by stream activity; its claim counts", () => {
  const h = mkdtemp();
  mkPeers(h, {});
  mkStream(h, "old", { ageMin: 200, held_by: "cc", held_session: "ghost", held_at: iso(200) });
  mkStream(h, "fresh", { ageMin: 200, held_by: "cc", held_session: "ghost", held_at: iso(2) });
  mkStream(h, "claimed", { ageMin: 200, held_by: "cc", held_session: "ghost", held_at: iso(200), claim: { session: "ghost", at: iso(3), taken_from: null } });
  withHome(h, {}, () => {
    for (const n of ["old", "fresh", "claimed"]) escalate(n);
    assert.equal(streamOrphaned("old").orphaned, true, "absent session, idle stream");
    assert.equal(streamOrphaned("fresh").orphaned, false, "just claimed, not yet in peers");
    assert.equal(streamOrphaned("claimed").orphaned, false, "a recent session claim is a sign of life");
  });
});

test("orphaned: an OpenCode holder is alive by its session row in opencode's db", () => {
  const h = mkdtemp();
  mkPeers(h, {});
  const ocdb = path.join(h, "opencode.db");
  const db = new DatabaseSync(ocdb);
  db.exec("CREATE TABLE session_v2 (id TEXT PRIMARY KEY, time_updated INTEGER);");
  db.prepare("INSERT INTO session_v2 VALUES ('ses_live', ?)").run(Date.now() - 4 * MIN);
  db.close();
  mkStream(h, "oc1", { ageMin: 300, held_by: "oc", held_session: "ses_live", held_at: iso(300) });
  mkStream(h, "oc2", { ageMin: 300, held_by: "oc", held_session: "ses_gone", held_at: iso(300) });
  withHome(h, { PEER_MAIL_OC_DB: ocdb }, () => {
    escalate("oc1");
    escalate("oc2");
    assert.equal(streamOrphaned("oc1").orphaned, false);
    assert.equal(streamOrphaned("oc2").orphaned, true);
  });
});

test("orphaned: held with no session -> the stream's own activity decides", () => {
  const h = mkdtemp();
  mkStream(h, "idle", { ageMin: 200, held_by: "cc", held_at: iso(200) });
  mkStream(h, "busy", { ageMin: 200, held_by: "cc", held_at: iso(200), noted_at: iso(5) });
  mkStream(h, "evt", { ageMin: 200, held_by: "cc", held_at: iso(200) });
  withHome(h, {}, () => {
    escalate("idle");
    escalate("busy");
    escalate("evt");
    appendAck("evt", "other", "ACTION x"); // an ack stamped now is activity
    assert.equal(streamOrphaned("idle").orphaned, true);
    assert.equal(streamOrphaned("busy").orphaned, false);
    assert.equal(streamOrphaned("evt").orphaned, false);
  });
});

test("openEscalations: daemon pages count once per key alongside ESCALATE acks", () => {
  const h = mkdtemp();
  mkStream(h, "s");
  const dir = path.join(h, ".config", "orchestrator", "desk-daemon");
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, "escalations.jsonl"), [{ stream: "s", key: "a", reason: "r-a" }, { stream: "s", key: "run:t1/worker-r1:done", reason: "dup" }, { stream: "other", key: "z", reason: "r" }].map((o) => JSON.stringify(o)).join("\n") + "\n");
  withHome(h, {}, () => {
    escalate("s");
    assert.deepEqual(openEscalations("s").map((e) => e.key).sort(), ["a", "run:t1/worker-r1:done"]);
  });
});

test("sweepOrphans: N escalations on one dead stream page once; a new claim re-arms; dry-run pages nothing", () => {
  const h = mkdtemp();
  mkStream(h, "dead", { ageMin: 300, held_by: "cc", held_at: iso(300) });
  withHome(h, { ORCH_NO_NOTIFY: "1" }, () => {
    escalate("dead", "k1");
    escalate("dead", "k2");
    escalate("dead", "k3");
    const quiet = withHome(h, { ORCH_NO_NOTIFY: "1", ORCH_DAEMON_DRY_RUN: "1" }, () => sweepOrphans());
    assert.deepEqual(quiet, [], "dry run pages nothing");
    assert.deepEqual(readDaemonState().orphaned, [], "and writes no ledger entry");
    assert.deepEqual(sweepOrphans(), ["dead"]);
    assert.deepEqual(sweepOrphans(), [], "second poll: already paged");
    assert.equal(readDaemonState().orphaned.length, 1);
    assert.match(readDaemonState().orphaned[0], /^orphan:dead:/);
    // a new claim (new held_at) on a stream that goes quiet again re-arms the page
    mkStream(h, "dead", { ageMin: 300, held_by: "cc", held_at: iso(299) });
    assert.deepEqual(sweepOrphans(), ["dead"], "new held_at -> new ledger key");
    assert.equal(readDaemonState().orphaned.length, 2);
  });
});

test("sweepOrphans: once its escalations are resolved a later one on the same stream pages again", () => {
  const h = mkdtemp();
  mkStream(h, "again");
  withHome(h, { ORCH_NO_NOTIFY: "1" }, () => {
    escalate("again", "k1");
    assert.deepEqual(sweepOrphans(), ["again"]);
    assert.deepEqual(sweepOrphans(), []);
    appendAck("again", "k1", "resolved", { resolved: true });
    assert.deepEqual(sweepOrphans(), [], "nothing open");
    assert.deepEqual(readDaemonState().orphaned, [], "ledger entry pruned");
    escalate("again", "k2");
    assert.deepEqual(sweepOrphans(), ["again"], "k2 pages");
  });
});

test("orphaned: a session known to the mail store but busy on the stream is alive", () => {
  const h = mkdtemp();
  mkPeers(h, { sess: 120 });
  mkStream(h, "busy2", { ageMin: 300, held_by: "cc", held_session: "sess", held_at: iso(300), noted_at: iso(5) });
  withHome(h, {}, () => {
    escalate("busy2");
    assert.equal(streamOrphaned("busy2").orphaned, false);
  });
});

test("sweepOrphans: unheld stream keys on 'unheld'; a live holder is never swept", () => {
  const h = mkdtemp();
  mkPeers(h, { live: 1 });
  mkStream(h, "free");
  mkStream(h, "mine", { held_by: "cc", held_session: "live", held_at: iso(400) });
  withHome(h, { ORCH_NO_NOTIFY: "1" }, () => {
    escalate("free");
    escalate("mine");
    assert.deepEqual(sweepOrphans(), ["free"]);
    assert.deepEqual(readDaemonState().orphaned, ["orphan:free:unheld"]);
  });
});

// ---- the helper -------------------------------------------------------------------------------------------

function stubs(printed) {
  const bin = mkdtemp();
  const log = path.join(bin, "notify.log");
  fs.writeFileSync(path.join(bin, "notify-send"), `#!/bin/sh\necho "$@" >> "${log}"\n${printed ? `echo ${printed}\n` : ""}`, { mode: 0o755 });
  const rec = path.join(bin, "rec.sh");
  const out = path.join(bin, "launch.log");
  fs.writeFileSync(rec, `#!/bin/sh\necho "cwd=$(pwd) args=$*" >> "${out}"\n`, { mode: 0o755 });
  return { bin, log, rec, out };
}
function runNotice(h, st, env = {}) {
  return spawnSync(process.execPath, [NOTICE, "hs"], { env: { ...process.env, ORCH_HOME: h, ORCH_NO_NOTIFY: "", PATH: `${st.bin}${path.delimiter}${process.env.PATH}`, ORCH_LAUNCH_CMD: `${st.rec} {stream} {harness}`, ...env }, encoding: "utf8" });
}
async function waitFor(file) {
  for (let i = 0; i < 100 && !fs.existsSync(file); i++) await new Promise((r) => setTimeout(r, 50));
}

test("notice helper: choosing the action launches the command in the stream's repo", async () => {
  const h = mkdtemp();
  const repo = fs.realpathSync(mkdtemp());
  mkStream(h, "hs", { repo, held_by: "oc", held_at: iso(300) });
  withHome(h, {}, () => escalate("hs"));
  const st = stubs("resolve");
  const r = runNotice(h, st);
  assert.equal(r.status, 0);
  const said = fs.readFileSync(st.log, "utf8");
  assert.match(said, /-u critical -A resolve=Resolve in new session --wait orchestrator desk hs: 1 escalation\(s\), no live session/);
  await waitFor(st.out);
  assert.equal(fs.readFileSync(st.out, "utf8").trim(), `cwd=${repo} args=hs oc`);
});

test("notice helper: dismissing the notice launches nothing; a missing launcher never throws", async () => {
  const h = mkdtemp();
  mkStream(h, "hs", { held_at: null });
  withHome(h, {}, () => escalate("hs"));
  const st = stubs("");
  assert.equal(runNotice(h, st).status, 0);
  await new Promise((r) => setTimeout(r, 300));
  assert.equal(fs.existsSync(st.out), false);
  const st2 = stubs("resolve");
  assert.equal(runNotice(h, st2, { ORCH_LAUNCH_CMD: "/nonexistent/launcher {stream}" }).status, 0);
});

test("notice helper: default launch is the terminal wrapper running claude (cc/unheld) or opencode --prompt (oc)", async () => {
  const h = mkdtemp();
  mkStream(h, "hs", { held_by: "cc", held_at: iso(300) });
  withHome(h, {}, () => escalate("hs"));
  const st = stubs("resolve");
  // a stub terminal on PATH records its argv
  fs.writeFileSync(path.join(st.bin, "xdg-terminal-exec"), `#!/bin/sh\necho "$@" >> "${st.out}"\n`, { mode: 0o755 });
  runNotice(h, st, { ORCH_LAUNCH_CMD: "" });
  await waitFor(st.out);
  assert.equal(fs.readFileSync(st.out, "utf8").trim(), "-- claude /frood-next hs");
  fs.rmSync(st.out);
  mkStream(h, "hs", { held_by: "oc", held_at: iso(300) });
  runNotice(h, st, { ORCH_LAUNCH_CMD: "" });
  await waitFor(st.out);
  assert.equal(fs.readFileSync(st.out, "utf8").trim(), "-- opencode --prompt /frood-next hs");
});

test("notice helper: ORCH_NO_NOTIFY=1 does nothing", () => {
  const h = mkdtemp();
  mkStream(h, "hs");
  const st = stubs("resolve");
  runNotice(h, st, { ORCH_NO_NOTIFY: "1" });
  assert.equal(fs.existsSync(st.log), false);
});

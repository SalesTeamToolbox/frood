import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
const require = createRequire(import.meta.url);

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HOOK = path.join(HERE, "..", "hooks", "peer-mail-wake.js");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function tmpDir(prefix) {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), prefix));
  CLEAN.push(d);
  return d;
}

const SESSION = "ses_wake0000000000000000001";
const OTHER = "ses_other0000000000000000002";

function makeMailbox(file, rows, { withExpiry = true } = {}) {
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(file);
  try {
    db.exec(
      `CREATE TABLE messages (
         id TEXT PRIMARY KEY, ts INTEGER, from_session TEXT, from_title TEXT, from_branch TEXT,
         to_session TEXT, subject TEXT, status TEXT${withExpiry ? ", expires_at INTEGER" : ""});`,
    );
    const sql = withExpiry
      ? "INSERT INTO messages (id, ts, from_session, from_title, from_branch, to_session, subject, status, expires_at) VALUES (?,?,?,?,?,?,?,?,?)"
      : "INSERT INTO messages (id, ts, from_session, from_title, from_branch, to_session, subject, status) VALUES (?,?,?,?,?,?,?,?)";
    const ins = db.prepare(sql);
    const now = Date.now();
    for (const r of rows) {
      const base = [r.id, r.ts ?? now, r.from ?? "ses_sender", r.from_title ?? "orch", r.from_branch ?? "main", r.to, r.subject ?? `subj ${r.id}`, r.status ?? "unread"];
      if (withExpiry) ins.run(...base, r.expires ?? now + 7 * 24 * 60 * 60 * 1000);
      else ins.run(...base);
    }
  } finally { db.close(); }
}

function envFor(over = {}) {
  const env = { ...process.env };
  if (over.orchHome) env.ORCH_HOME = over.orchHome;
  if (over.mailbox) env.PEER_MAIL_DB = over.mailbox;
  env.PEER_WAKE_POLL_MS = String(over.pollMs ?? 50);
  env.PEER_WAKE_MAX_MIN = String(over.maxMin ?? 1);
  return env;
}

function startHook(over, stdin) {
  const ps = spawn(process.execPath, [HOOK], { env: envFor(over), encoding: "utf8" });
  if (stdin !== undefined) ps.stdin.write(stdin);
  ps.stdin.end();
  let stderr = "", stdout = "";
  ps.stderr.on("data", (d) => (stderr += d));
  ps.stdout.on("data", (d) => (stdout += d));
  const wait = new Promise((resolve) => ps.on("close", (code, signal) => resolve({ code, signal, stderr, stdout })));
  return { ps, pid: ps.pid, kill: () => { try { ps.kill("SIGTERM"); } catch {} }, wait };
}

async function waitWithTimeout(promise, ms, msg) {
  let timer;
  const timeout = new Promise((_, rej) => { timer = setTimeout(() => rej(new Error(msg || "timeout")), ms); });
  try { return await Promise.race([promise, timeout]); } finally { clearTimeout(timer); }
}

const STATE_SUB = path.join(".config", "orchestrator", "peer-wake");
function pidFile(home) { return path.join(home, STATE_SUB, `${SESSION}.pid`); }
function announcedFile(home) { return path.join(home, STATE_SUB, `${SESSION}.announced`); }

// ---------------------------------------------------------------- stdin handling

test("bad stdin -> exit 0", async () => {
  const d = tmpDir("pmw-");
  const { ps, wait } = startHook({ orchHome: d, mailbox: path.join(d, "m.db") }, "not json at all");
  const r = await waitWithTimeout(wait, 5000, "bad stdin did not exit");
  assert.equal(r.code, 0, `bad stdin exited ${r.code}`);
});

test("missing session_id -> exit 0", async () => {
  const d = tmpDir("pmw-");
  const { ps, wait } = startHook({ orchHome: d, mailbox: path.join(d, "m.db") }, JSON.stringify({ foo: 1 }));
  const r = await waitWithTimeout(wait, 5000, "missing session did not exit");
  assert.equal(r.code, 0, `missing session exited ${r.code}`);
});

// ---------------------------------------------------------------- unread mail wakes

test("unread mail for the session -> exit 2 within ~1s, stderr names id/from/subject", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, [{ id: "msg_a", to: SESSION, from_title: "desk", subject: "ESCALATE no-ticket" }]);
  const started = Date.now();
  const { ps, wait } = startHook({ orchHome: d, mailbox: mbox }, JSON.stringify({ session_id: SESSION }));
  const r = await waitWithTimeout(wait, 5000, "wake hook did not exit 2");
  assert.equal(r.code, 2, `expected exit 2, got ${r.code} (${r.signal})`);
  assert.ok(Date.now() - started < 2500, `woke too slowly: ${Date.now() - started}ms`);
  assert.match(r.stderr, /peer-mail: 1 new message\(s\)/);
  assert.match(r.stderr, /msg_a/);
  assert.match(r.stderr, /desk/);
  assert.match(r.stderr, /ESCALATE no-ticket/);
  assert.match(r.stderr, /peer_read/);
  assert.match(r.stderr, /peer_ack/);
});

// ---------------------------------------------------------------- announced suppression

test("already-announced id -> no wake (stays alive, killed cleanly with exit 0)", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, [{ id: "msg_a", to: SESSION, from_title: "desk", subject: "ESCALATE" }]);
  fs.mkdirSync(path.dirname(pidFile(d)), { recursive: true });
  fs.writeFileSync(announcedFile(d), JSON.stringify(["msg_a"]));
  const { ps, kill, wait } = startHook({ orchHome: d, mailbox: mbox, maxMin: 1 }, JSON.stringify({ session_id: SESSION }));
  let woke = false;
  try { await waitWithTimeout(wait, 700, "stayed-alive probe"); woke = true; } catch { /* stayed alive: good */ }
  assert.equal(woke, false, "announced mail woke the hook (exited 2) before we killed it");
  kill();
  const res = await waitWithTimeout(wait, 3000, "hook did not exit after kill");
  assert.equal(res.code, 0, `killed hook exited ${res.code} (${res.signal})`);
});

test("a NEW message after announcement -> exit 2", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, [
    { id: "msg_old", to: SESSION, from_title: "desk", subject: "old" },
    { id: "msg_new", to: SESSION, from_title: "desk", subject: "fresh" },
  ]);
  fs.mkdirSync(path.dirname(pidFile(d)), { recursive: true });
  fs.writeFileSync(announcedFile(d), JSON.stringify(["msg_old"]));
  const { ps, wait } = startHook({ orchHome: d, mailbox: mbox }, JSON.stringify({ session_id: SESSION }));
  const r = await waitWithTimeout(wait, 5000, "new message after announcement did not wake");
  assert.equal(r.code, 2, `expected exit 2, got ${r.code}`);
  assert.match(r.stderr, /msg_new/);
  assert.doesNotMatch(r.stderr, /msg_old/);
});

// ---------------------------------------------------------------- filtering

test("mail to another session -> no wake", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, [{ id: "msg_x", to: OTHER, from_title: "desk", subject: "for someone else" }]);
  const { ps, kill, wait } = startHook({ orchHome: d, mailbox: mbox, maxMin: 1 }, JSON.stringify({ session_id: SESSION }));
  let woke = false;
  try { await waitWithTimeout(wait, 700, "stayed-alive probe"); woke = true; } catch { /* stayed alive: good */ }
  assert.equal(woke, false, "other-session mail woke the hook");
  kill();
  const res = await waitWithTimeout(wait, 3000, "hook did not exit after kill");
  assert.equal(res.code, 0);
});

test("read mail (status != unread) -> no wake", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, [{ id: "msg_r", to: SESSION, status: "read", subject: "already read" }]);
  const { ps, kill, wait } = startHook({ orchHome: d, mailbox: mbox, maxMin: 1 }, JSON.stringify({ session_id: SESSION }));
  let woke = false;
  try { await waitWithTimeout(wait, 700, "stayed-alive probe"); woke = true; } catch { /* stayed alive: good */ }
  assert.equal(woke, false, "read mail woke the hook");
  kill();
  const res = await waitWithTimeout(wait, 3000, "hook did not exit after kill");
  assert.equal(res.code, 0);
});

test("expired mail -> no wake", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, [{ id: "msg_e", to: SESSION, expires: Date.now() - 1000, subject: "expired" }]);
  const { ps, kill, wait } = startHook({ orchHome: d, mailbox: mbox, maxMin: 1 }, JSON.stringify({ session_id: SESSION }));
  let woke = false;
  try { await waitWithTimeout(wait, 700, "stayed-alive probe"); woke = true; } catch { /* stayed alive: good */ }
  assert.equal(woke, false, "expired mail woke the hook");
  kill();
  const res = await waitWithTimeout(wait, 3000, "hook did not exit after kill");
  assert.equal(res.code, 0);
});

// ---------------------------------------------------------------- single instance

test("second instance SIGTERMs the first; pid file holds the second", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, []);
  const { ps: s1, kill: k1, wait: w1 } = startHook({ orchHome: d, mailbox: mbox }, JSON.stringify({ session_id: SESSION }));
  await new Promise((r) => setTimeout(r, 250)); // let instance 1 settle and write its pid
  const { ps: s2, wait: w2 } = startHook({ orchHome: d, mailbox: mbox }, JSON.stringify({ session_id: SESSION }));
  const r1 = await waitWithTimeout(w1, 5000, "first instance did not exit after second started");
  assert.equal(r1.code, 0, `first instance exited ${r1.code} (${r1.signal}), expected 0`);
  const pid = Number(fs.readFileSync(pidFile(d), "utf8").trim());
  assert.equal(pid, s2.pid, `pid file holds ${pid}, expected instance 2 pid ${s2.pid}`);
  s2.kill();
  const r2 = await waitWithTimeout(w2, 3000, "second instance did not exit after kill");
  assert.equal(r2.code, 0, `second instance exited ${r2.code} (${r2.signal})`);
});

// ---------------------------------------------------------------- mailbox appears later

test("no mailbox file, then it appears with mail -> exit 2", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  // no mailbox yet
  const { ps, wait } = startHook({ orchHome: d, mailbox: mbox, maxMin: 1 }, JSON.stringify({ session_id: SESSION }));
  await new Promise((r) => setTimeout(r, 150)); // let it poll once with no DB
  makeMailbox(mbox, [{ id: "msg_l", to: SESSION, from_title: "desk", subject: "late" }]);
  const r = await waitWithTimeout(wait, 5000, "hook did not exit 2 after mailbox appeared");
  assert.equal(r.code, 2, `expected exit 2, got ${r.code}`);
  assert.match(r.stderr, /msg_l/);
});

// ---------------------------------------------------------------- max-min deadline (exit 0)

test("exit 0 at PEER_WAKE_MAX_MIN with nothing found", async () => {
  const d = tmpDir("pmw-");
  const mbox = path.join(d, "m.db");
  makeMailbox(mbox, []); // empty
  // 0 minutes -> deadline already passed at first tick -> exit 0 immediately
  const { ps, wait } = startHook({ orchHome: d, mailbox: mbox, maxMin: 0 }, JSON.stringify({ session_id: SESSION }));
  const r = await waitWithTimeout(wait, 5000, "hook did not exit at MAX_MIN");
  assert.equal(r.code, 0, `expected exit 0 at MAX_MIN, got ${r.code}`);
});

// ---------------------------------------------------------------- errors never thrown

test("unreadable mailbox path is logged, not thrown", async () => {
  const d = tmpDir("pmw-");
  // The file exists (so it is not "missing") but cannot be opened: DatabaseSync throws.
  const mbox = path.join(d, "m.db");
  fs.writeFileSync(mbox, "");
  fs.chmodSync(mbox, 0o000);
  // maxMin 0.005 (0.3 s) at the test's 50 ms poll: several polls hit the open error before the deadline.
  const { ps, wait } = startHook({ orchHome: d, mailbox: mbox, maxMin: 0.005 }, JSON.stringify({ session_id: SESSION }));
  const r = await waitWithTimeout(wait, 5000, "hook threw on unreadable mailbox");
  fs.chmodSync(mbox, 0o600);
  assert.equal(r.code, 0, `expected exit 0, got ${r.code}`);
  const log = path.join(d, ".config", "orchestrator", "peer-wake", "peer-wake.log");
  assert.ok(fs.existsSync(log) && fs.readFileSync(log, "utf8").trim(), "the open error must be logged");
});

import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const HOOK = path.join(HERE, "..", "hooks", "peer-mail-session-id.js");
const require = createRequire(import.meta.url);

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function tmpDir() {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-peer-mail-notice-"));
  CLEAN.push(d);
  return d;
}

/** Build a mailbox.db with the messages schema used by the hook. */
function makeMailbox(dbPath, rows) {
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(dbPath);
  try {
    db.exec(
      `CREATE TABLE messages (
         id TEXT PRIMARY KEY, to_session TEXT, from_title TEXT, subject TEXT,
         status TEXT, ts INTEGER, expires_at INTEGER)`,
    );
    const ins = db.prepare("INSERT INTO messages (id, to_session, from_title, subject, status, ts, expires_at) VALUES (?,?,?,?,?,?,?)");
    const now = Date.now();
    for (const r of rows) {
      ins.run(r.id, r.to_session, r.from_title ?? "orch", r.subject ?? `subj ${r.id}`, r.status ?? "unread", r.ts ?? now, r.expires ?? now + 7 * 24 * 3600_000);
    }
  } finally { db.close(); }
}

/** Spawn the hook with a given payload and PEER_MAIL_DB, capturing stdout/exit. */
function spawnHook(payload, dbPath) {
  const input = JSON.stringify(payload);
  const r = spawnSync(process.execPath, [HOOK], {
    input,
    env: { ...process.env, PEER_MAIL_DB: dbPath },
    encoding: "utf8",
    timeout: 30_000,
    windowsHide: true,
  });
  return r;
}

function parseStdout(r) {
  const out = String(r.stdout || "").trim();
  return out.length ? JSON.parse(out) : null;
}

test("SessionStart output is unchanged (id line + unread mail)", () => {
  const db = tmpDir();
  const mdb = path.join(db, "mailbox.db");
  makeMailbox(mdb, [
    { id: "m1", to_session: "ses_cc1", from_title: "orchestrator desk", subject: "ESCALATE no-ticket", status: "unread" },
  ]);
  const r = spawnHook({ hook_event_name: "SessionStart", session_id: "ses_cc1" }, mdb);
  assert.equal(r.status, 0, r.stderr);
  const d = parseStdout(r);
  assert.ok(d, "SessionStart prints output");
  assert.equal(d.hookSpecificOutput.hookEventName, "SessionStart");
  assert.match(d.hookSpecificOutput.additionalContext, /peer-mail: your session id for the peer_\* messaging tools is ses_cc1/);
  assert.match(d.hookSpecificOutput.additionalContext, /ESCALATE no-ticket/);
});

test("SessionStart with no unread mail prints 'no unread messages'", () => {
  const db = tmpDir();
  const mdb = path.join(db, "mailbox.db");
  makeMailbox(mdb, [
    { id: "m1", to_session: "ses_cc1", from_title: "orch", subject: "read mail", status: "read" },
  ]);
  const r = spawnHook({ hook_event_name: "SessionStart", session_id: "ses_cc1" }, mdb);
  assert.equal(r.status, 0, r.stderr);
  const d = parseStdout(r);
  assert.ok(d);
  assert.match(d.hookSpecificOutput.additionalContext, /no unread messages/);
});

test("UserPromptSubmit with unread mail prints the notice with subjects", () => {
  const db = tmpDir();
  const mdb = path.join(db, "mailbox.db");
  makeMailbox(mdb, [
    { id: "m1", to_session: "ses_cc1", from_title: "orchestrator desk", subject: "ESCALATE no-ticket", status: "unread" },
    { id: "m2", to_session: "ses_cc1", from_title: "critic", subject: "CHANGES_REQUESTED on blast radius", status: "unread" },
  ]);
  const r = spawnHook({ hook_event_name: "UserPromptSubmit", session_id: "ses_cc1" }, mdb);
  assert.equal(r.status, 0, r.stderr);
  const d = parseStdout(r);
  assert.ok(d, "UserPromptSubmit prints a notice when mail is unread");
  assert.equal(d.hookSpecificOutput.hookEventName, "UserPromptSubmit");
  assert.match(d.hookSpecificOutput.additionalContext, /peer-mail: 2 unread/);
  assert.match(d.hookSpecificOutput.additionalContext, /m1 from orchestrator desk: ESCALATE no-ticket/);
  assert.match(d.hookSpecificOutput.additionalContext, /m2 from critic: CHANGES_REQUESTED on blast radius/);
});

test("UserPromptSubmit with no unread mail prints nothing (empty stdout)", () => {
  const db = tmpDir();
  const mdb = path.join(db, "mailbox.db");
  makeMailbox(mdb, [
    { id: "m1", to_session: "ses_cc1", from_title: "orch", subject: "read mail", status: "read" },
  ]);
  const r = spawnHook({ hook_event_name: "UserPromptSubmit", session_id: "ses_cc1" }, mdb);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(String(r.stdout || "").trim(), "", "no unread mail: empty stdout");
});

test("UserPromptSubmit with all mail read prints nothing", () => {
  const db = tmpDir();
  const mdb = path.join(db, "mailbox.db");
  makeMailbox(mdb, [
    { id: "m1", to_session: "ses_cc1", from_title: "orch", subject: "read one", status: "read" },
    { id: "m2", to_session: "ses_cc1", from_title: "orch", subject: "read two", status: "read" },
  ]);
  const r = spawnHook({ hook_event_name: "UserPromptSubmit", session_id: "ses_cc1" }, mdb);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(String(r.stdout || "").trim(), "", "all read: empty stdout");
});

test("missing DB: UserPromptSubmit exits 0 silently", () => {
  const db = path.join(tmpDir(), "does-not-exist.db");
  assert.ok(!fs.existsSync(db));
  const r = spawnHook({ hook_event_name: "UserPromptSubmit", session_id: "ses_cc1" }, db);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(String(r.stdout || "").trim(), "", "missing DB: empty stdout");
});

test("missing DB: SessionStart exits 0 with just the id line", () => {
  const db = path.join(tmpDir(), "does-not-exist.db");
  assert.ok(!fs.existsSync(db));
  const r = spawnHook({ hook_event_name: "SessionStart", session_id: "ses_cc1" }, db);
  assert.equal(r.status, 0, r.stderr);
  const d = parseStdout(r);
  assert.ok(d, "SessionStart still prints the id line even without a mailbox");
  assert.equal(d.hookSpecificOutput.hookEventName, "SessionStart");
  assert.match(d.hookSpecificOutput.additionalContext, /session id.*ses_cc1/);
  assert.match(d.hookSpecificOutput.additionalContext, /Inbox: no unread messages/);
});

test("no payload at all exits 0 silently", () => {
  const r = spawnHook(null, tmpDir());
  assert.equal(r.status, 0, r.stderr);
  assert.equal(String(r.stdout || "").trim(), "");
});

test("malformed payload exits 0 silently", () => {
  const r = spawnSync(process.execPath, [HOOK], {
    input: "not json at all",
    env: { ...process.env, PEER_MAIL_DB: tmpDir() },
    encoding: "utf8",
    timeout: 30_000,
    windowsHide: true,
  });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(String(r.stdout || "").trim(), "");
});

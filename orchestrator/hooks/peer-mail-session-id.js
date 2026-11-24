#!/usr/bin/env node
/**
 * peer-mail identity + inbox hook (Claude Code SessionStart + UserPromptSubmit).
 * Managed in the Frood repo's orchestrator/ directory ({{ORCH_REPO}}/hooks) — edit there, then install.
 *
 * A Claude Code session has no env var with its id, so this hook reads the hook payload's
 * session_id (== the transcript filename, which is how peer-mail addresses this session) and
 * injects it as `peer-mail id`. It also opens the mailbox READ-ONLY and lists unread subjects,
 * so mail is seen at start without relying on the model remembering to poll.
 *
 * SessionStart keeps today's output byte-for-byte (id line, then unread mail or "no unread").
 * UserPromptSubmit prints nothing when there is no unread mail; otherwise it emits one
 * hookSpecificOutput notice: `peer-mail: N unread …` plus up to 6 `id from: subject` lines,
 * so mail that arrives mid-session surfaces at the next prompt instead of waiting for the
 * next SessionStart.
 *
 * Never breaks a prompt: any failure exits 0 with no output.
 */
const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

function unreadFor(id) {
  const dbPath = (process.env.PEER_MAIL_DB || "").trim() ||
    path.join(os.homedir(), ".local", "share", "opencode-peer-mail", "mailbox.db");
  if (!fs.existsSync(dbPath)) return [];
  process.emitWarning = () => {}; // node:sqlite prints an ExperimentalWarning otherwise
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(dbPath, { readOnly: true });
  try {
    return db
      .prepare(
        "SELECT id, from_title, subject FROM messages WHERE to_session = ? AND status = 'unread' AND expires_at > ? ORDER BY ts DESC LIMIT 6",
      )
      .all(id, Date.now());
  } finally {
    db.close();
  }
}

function noticeFor(id) {
  try {
    const rows = unreadFor(id);
    if (!rows.length) return null;
    let ctx = `peer-mail: ${rows.length >= 6 ? "6+" : rows.length} unread message(s) — read with peer_read { for_session_id, id }:`;
    for (const r of rows) ctx += `\n- ${r.id} from ${r.from_title || "?"}: ${r.subject}`;
    return ctx;
  } catch {
    return null;
  }
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  try {
    const payload = JSON.parse(raw || "{}");
    const event = payload && typeof payload === "object" ? payload.hook_event_name : null;
    const id = payload && typeof payload.session_id === "string" ? payload.session_id : null;
    if (typeof id !== "string" || !id) process.exit(0);

    if (event === "UserPromptSubmit") {
      const ctx = noticeFor(id);
      if (ctx) process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: "UserPromptSubmit", additionalContext: ctx } }));
      process.exit(0);
      return;
    }

    // SessionStart (or anything else): today's output, byte-for-byte.
    let ctx =
      `peer-mail: your session id for the peer_* messaging tools is ${id}. ` +
      `Pass it as from_session_id / for_session_id; other sessions address you by it ([claude] in peer_sessions).`;
    try {
      const rows = unreadFor(id);
      if (rows.length) {
        ctx += ` You have ${rows.length >= 6 ? "6+" : rows.length} unread message(s) — read with peer_read { for_session_id, id }:` +
          rows.map((r) => `\n- ${r.id} from ${r.from_title || "?"}: ${r.subject}`).join("");
      } else ctx += " Inbox: no unread messages.";
    } catch {
      ctx += " (Could not read the mailbox — check peer_inbox.)";
    }
    process.stdout.write(JSON.stringify({ hookSpecificOutput: { hookEventName: "SessionStart", additionalContext: ctx } }));
  } catch {
    // never break session start or a prompt
  }
  process.exit(0);
});

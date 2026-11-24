#!/usr/bin/env node
/**
 * peer-mail wake hook (Claude Code Stop, asyncRewake).
 * Managed in the Frood repo's orchestrator/ directory ({{ORCH_REPO}}/hooks) — edit there, then install.
 *
 * Registered on Claude Code's `Stop` event:
 *   {"type":"command","command":"node ~/.claude/hooks/peer-mail-wake.js","asyncRewake":true,"timeout":86400}
 *
 * Reads hook JSON from stdin; `session_id` is the peer-mail id of this session. Then polls the
 * mailbox (PEER_MAIL_DB override, default ~/.local/share/opencode-peer-mail/mailbox.db) every
 * PEER_WAKE_POLL_MS (default 15000 ms) for unread, unexpired messages addressed to this session
 * whose id is not yet announced. When one appears it prints them and exits 2 — Claude Code shows
 * an asyncRewake hook's output on exit code 2, which wakes the idle model.
 *
 * Single instance per session: state dir ${ORCH_HOME||~}/.config/orchestrator/peer-wake/ holds
 * <session>.pid and <session>.announced. A second instance SIGTERMs the first and takes over.
 * Exits 0 after PEER_WAKE_MAX_MIN (default 1440 min / 24 h), on SIGTERM, or on any error
 * (errors appended to peer-wake.log, never thrown). A missing mailbox DB is not an error.
 *
 * Env: PEER_MAIL_DB, ORCH_HOME, PEER_WAKE_POLL_MS, PEER_WAKE_MAX_MIN.
 */

const os = require("node:os");
const path = require("node:path");
const fs = require("node:fs");

const POLL_MS = Number(process.env.PEER_WAKE_POLL_MS || 15000);
const MAX_MIN = Number(process.env.PEER_WAKE_MAX_MIN || 1440);

function dbPath() {
  return (process.env.PEER_MAIL_DB || "").trim() ||
    path.join(os.homedir(), ".local", "share", "opencode-peer-mail", "mailbox.db");
}

function stateDir() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "peer-wake");
}

function pidFile(session) { return path.join(stateDir(), `${session}.pid`); }
function announcedFile(session) { return path.join(stateDir(), `${session}.announced`); }
function logFile() { return path.join(stateDir(), "peer-wake.log"); }

function now() { return Date.now(); }

function unreadFor(session) {
  const file = dbPath();
  if (!fs.existsSync(file)) return [];
  process.emitWarning = () => {}; // node:sqlite ExperimentalWarning
  const { DatabaseSync } = require("node:sqlite");
  // timeout = SQLite busy timeout: wait out a writer (peer-mail MCP, desk.mjs) instead of skipping the poll.
  const db = new DatabaseSync(file, { readOnly: true, timeout: 2000 });
  try {
    return db
      .prepare(
        "SELECT id, from_title, subject FROM messages WHERE to_session = ? AND status = 'unread' AND expires_at > ? ORDER BY ts ASC",
      )
      .all(session, now());
  } finally {
    db.close();
  }
}

function logError(msg) {
  try { fs.appendFileSync(logFile(), `${new Date().toISOString()} ${msg}\n`); } catch { /* never throw */ }
}

function readAnnounced(session) {
  try {
    const arr = JSON.parse(fs.readFileSync(announcedFile(session), "utf8"));
    return Array.isArray(arr) ? arr : [];
  } catch { return []; }
}

function writeAnnounced(session, arr) {
  try { fs.writeFileSync(announcedFile(session), JSON.stringify(arr)); } catch (e) { logError(`announced: ${e.message}`); }
}

function removeOwnPid(session) {
  try {
    const pid = Number(fs.readFileSync(pidFile(session), "utf8").trim());
    if (pid === process.pid) fs.unlinkSync(pidFile(session));
  } catch { /* never throw */ }
}

function sigtermExisting(session) {
  try {
    const pid = Number(fs.readFileSync(pidFile(session), "utf8").trim());
    if (!pid || pid === process.pid) return;
    const cmdline = fs.readFileSync(`/proc/${pid}/cmdline`, "utf8").replace(/\0/g, " ");
    if (cmdline.includes("peer-mail-wake.js")) {
      try { process.kill(pid, "SIGTERM"); } catch { /* gone already */ }
    }
  } catch { /* missing / not readable — fine */ }
}

function writePid(session) {
  fs.mkdirSync(stateDir(), { recursive: true });
  fs.writeFileSync(pidFile(session), String(process.pid));
}

function emit(lines) {
  const text = lines.join("\n") + "\n";
  process.stderr.write(text);
  process.stdout.write(text);
}

function run(session) {
  fs.mkdirSync(stateDir(), { recursive: true });
  sigtermExisting(session);
  writePid(session);

  let announced = readAnnounced(session);
  const deadline = now() + MAX_MIN * 60 * 1000;

  // A SIGTERM means a successor took over and owns the pid file now: leave it alone. Unlinking here raced the
  // successor's writePid and deleted ITS pid file. A stale pid file is harmless (the cmdline check guards the kill).
  process.on("SIGTERM", () => process.exit(0));

  function tick() {
    try {
      if (now() >= deadline) { removeOwnPid(session); process.exit(0); return; }
      const rows = unreadFor(session);
      const fresh = rows.filter((r) => !announced.includes(r.id));
      if (fresh.length) {
        announced = announced.concat(fresh.map((r) => r.id)).slice(-200);
        writeAnnounced(session, announced);
        emit([
          `peer-mail: ${fresh.length} new message(s) for this session (${session}):`,
          ...fresh.map((r) => `- ${r.id} from ${r.from_title || "?"}: ${r.subject}`),
          `Read with peer_read { for_session_id: "${session}", id } (or the mailbox CLI), act on it, then peer_ack.`,
        ]);
        removeOwnPid(session);
        process.exit(2);
      }
    } catch (e) { logError(`poll: ${e.message}`); }
    setTimeout(tick, POLL_MS);
  }
  tick();
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  try {
    const payload = JSON.parse(raw || "{}");
    const session = typeof payload.session_id === "string" && payload.session_id ? payload.session_id : null;
    if (!session) { process.exit(0); return; }
    run(session);
  } catch { process.exit(0); }
});

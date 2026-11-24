// Orphan detection: an escalation sits on a stream nobody live is working. Pure reads, no side effects; shared by
// desk.mjs (the daemon's once-per-stream page) and orphan-notice.mjs (the desktop notice text).
//
// A stream is orphaned when it has an open escalation AND
//   - nobody holds it, or
//   - its holder session's liveness is older than the threshold (ORCH_ORPHAN_MIN, default 60 min), or
//   - it is held with no session id and the stream's own activity is older than the threshold.
// Liveness of a holder session = the newest of its peer-mail `peers.last_seen`, its OpenCode session `time_updated`
// (OpenCode sessions live in opencode's db, not in `peers`), the stream's session claim `at` for that session and,
// once the session is known to a store, the stream's own activity.
// peers.last_seen is refreshed only by peer-mail tool use (peer_register / send / authenticated read), NOT by tool
// use in general, so on its own it under-reports a busy Claude Code session; the claim `at` (refreshed by
// /frood-next steps 3 and 5) and the stream's activity cover that. A session found in neither store is judged by
// the stream's activity, like a held stream with no session id.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";
import { orchRoot, readAckLines, readEvents, readStream } from "./handoff.mjs";

const requireSqlite = createRequire(import.meta.url);
const DEFAULT_ORPHAN_MIN = 60;

export function orphanThresholdMs() {
  const raw = process.env.ORCH_ORPHAN_MIN;
  if (raw === undefined || !raw.trim()) return DEFAULT_ORPHAN_MIN * 60_000;
  const min = Number(raw);
  if (!Number.isFinite(min) || min < 0) return DEFAULT_ORPHAN_MIN * 60_000;
  return min * 60_000;
}

const mailboxFile = () => path.join(orchRoot(), ".local", "share", "opencode-peer-mail", "mailbox.db");
const opencodeDbFile = () => (process.env.PEER_MAIL_OC_DB ?? "").trim() || path.join(orchRoot(), ".local", "share", "opencode", "opencode.db");
const escalationsFile = () => path.join(orchRoot(), ".config", "orchestrator", "desk-daemon", "escalations.jsonl");

const ms = (iso) => {
  const t = Date.parse(iso ?? "");
  return Number.isFinite(t) ? t : null;
};
const newest = (xs) => xs.filter((x) => x !== null && x !== undefined).reduce((a, b) => (b > a ? b : a), -Infinity);

/** Escalations nobody has resolved: unresolved ESCALATE acks plus unresolved desk-daemon pages, one row per key. */
export function openEscalations(stream) {
  let acks = [];
  try {
    acks = readAckLines(stream);
  } catch {}
  const resolved = new Set(acks.filter((l) => l.resolved).map((l) => l.key));
  const rows = new Map();
  for (const l of acks) {
    if (l.resolved || resolved.has(l.key) || !String(l.action ?? "").startsWith("ESCALATE")) continue;
    if (!rows.has(l.key)) rows.set(l.key, { key: l.key, reason: String(l.action).replace(/^ESCALATE\s+/, "") });
  }
  try {
    for (const line of fs.readFileSync(escalationsFile(), "utf8").split("\n")) {
      if (!line.trim()) continue;
      let e;
      try {
        e = JSON.parse(line);
      } catch {
        continue;
      }
      if (e.stream !== stream || resolved.has(e.key) || rows.has(e.key)) continue;
      rows.set(e.key, { key: e.key, reason: String(e.reason ?? e.key) });
    }
  } catch {}
  return [...rows.values()];
}

// A session's newest sign of life in the two session stores, or null when it is in neither.
function sessionSeen(session) {
  let seen = null;
  const bump = (t) => {
    if (typeof t === "number" && Number.isFinite(t)) seen = seen === null || t > seen ? t : seen;
  };
  const query = (file, sql) => {
    if (!fs.existsSync(file)) return;
    try {
      const { DatabaseSync } = requireSqlite("node:sqlite");
      const db = new DatabaseSync(file, { readOnly: true });
      try {
        db.exec("PRAGMA busy_timeout=2000;");
        return db.prepare(sql).get(session);
      } finally {
        db.close();
      }
    } catch {}
  };
  bump(query(mailboxFile(), "SELECT last_seen AS t FROM peers WHERE session_id = ?")?.t);
  for (const table of ["session_v2", "session"]) bump(query(opencodeDbFile(), `SELECT time_updated AS t FROM ${table} WHERE id = ?`)?.t);
  return seen;
}

// Newest timestamp the stream shows: lease, pointer writes, session claim, and its events and (non-escalation) acks.
function streamActivity(s) {
  const ts = [s.held_at, s.noted_at, s.written_at, s.consumed_at, s.claim?.at].map(ms);
  try {
    for (const e of readEvents(s.name)) ts.push(ms(e.at));
    // an ESCALATE ack is the desk reporting its own dead end, not anyone working the stream
    for (const a of readAckLines(s.name)) if (!String(a.action ?? "").startsWith("ESCALATE")) ts.push(ms(a.at));
  } catch {}
  const t = newest(ts);
  return Number.isFinite(t) ? t : null;
}

/** { orphaned, why, escalations }. `why` is short prose for the notice; `escalations` are the open ones. */
export function streamOrphaned(name, now = Date.now()) {
  const none = { orphaned: false, why: "", escalations: [] };
  let s;
  try {
    s = readStream(name, now);
  } catch {
    return none;
  }
  if (!s || s.status === "done" || s.status === "parked") return none;
  const escalations = openEscalations(name);
  if (!escalations.length) return none;
  const limit = orphanThresholdMs();
  const orphan = (why) => ({ orphaned: true, why, escalations });
  if (!s.held_by) return orphan("nobody holds it");
  const idleMs = (t) => (t === null ? Infinity : now - t);
  if (typeof s.held_session === "string" && s.held_session) {
    const peer = sessionSeen(s.held_session);
    const claim = s.claim?.session === s.held_session ? ms(s.claim.at) : null;
    // Found in a store: the newest of its mail presence, its claim and the stream's own activity, so a busy
    // session that rarely touches peer-mail is not judged dead. Found nowhere: the activity rule below decides.
    const alive = Number.isFinite(newest([peer, claim])) ? newest([peer, claim, streamActivity(s)]) : -Infinity;
    if (Number.isFinite(alive)) return idleMs(alive) > limit ? orphan(`holder ${s.held_by} session silent ${Math.round(idleMs(alive) / 60_000)}m`) : none;
  }
  const act = streamActivity(s);
  return idleMs(act) > limit ? orphan(`held by ${s.held_by}, no activity ${act === null ? "ever" : `${Math.round(idleMs(act) / 60_000)}m`}`) : none;
}

/** Ledger key: one page per stream per claim. A new claim (new held_at) re-arms it. */
export const orphanLedgerKey = (name, s = readStream(name)) => `orphan:${name}:${s?.held_at ?? "unheld"}`;

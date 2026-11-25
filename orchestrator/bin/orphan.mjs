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

const SESSION_DIR = (home) => path.join(home, ".claude", "sessions");
const PROJECTS_DIR = (home) => path.join(home, ".claude", "projects");
const ID_RE = /^[a-z0-9][a-z0-9-]{0,59}$/;

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

const TICKET_KEY = /^(?:verdict|run):([a-z0-9][a-z0-9-]*)\//;

/** The board ticket an escalation key names, resolved against `<stream.repo>/.opencode/board/tickets/`.
 *  Returns { stage } or null when the ticket is missing/unreadable (leave the escalation open). */
function boardTicket(key, repo) {
  const m = TICKET_KEY.exec(String(key));
  if (!m || !repo || !ID_RE.test(m[1])) return null;
  const p = path.join(repo, ".opencode", "board", "tickets", `${m[1]}.json`);
  let t;
  try {
    t = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null; // missing or unreadable: leave the escalation open
  }
  return t && typeof t === "object" && !Array.isArray(t) && typeof t.stage === "string" ? { stage: t.stage } : null;
}

/** True when the board ticket an escalation names is closed or shipped (resolved). Missing ticket -> open. */
export function ticketResolved(key, repo) {
  const t = boardTicket(key, repo);
  return t ? t.stage === "closed" || t.stage === "shipped" : false;
}

/** Escalations nobody has resolved: unresolved ESCALATE acks plus unresolved desk-daemon pages, one row per key.
 *  Rows whose board ticket is `closed` or `shipped` are dropped; a missing ticket leaves the row open. */
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
  const s = readStream(stream);
  const repo = s && typeof s.repo === "string" && s.repo ? s.repo : "";
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
  return [...rows.values()].filter((r) => !ticketResolved(r.key, repo));
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

// cwd -> docs/atlas-style slug for the Claude projects dir (read-only copy of session-pressure.mjs's helper;
// session-pressure.mjs is out of scope and its helpers are not exported).
function cwdSlug(cwd, home) {
  if (!cwd) return "home";
  let rel = cwd;
  if (home && rel.startsWith(home)) rel = rel.slice(home.length);
  rel = rel.replace(/^\/+/, "");
  return rel.replace(/\//g, "-") || "home";
}

// Read a live-session file <home>/.claude/sessions/<pid>.json.
// Returns { sessionId, cwd, name, status, statusUpdatedAt } or null.
function sessionFile(home, pid) {
  try {
    const s = JSON.parse(fs.readFileSync(path.join(SESSION_DIR(home), String(pid) + ".json"), "utf8"));
    if (!s || typeof s !== "object") return null;
    return {
      sessionId: s.sessionId || null,
      cwd: s.cwd || null,
      name: s.name || null,
      status: s.status || null,
      statusUpdatedAt: s.statusUpdatedAt != null ? Number(s.statusUpdatedAt) : null,
    };
  } catch {
    return null;
  }
}

// Transcript mtime fallback for idle age, and title fallback.
function transcriptInfo(home, sessionId, cwd, nowMs) {
  if (!cwd || !sessionId) return { ms: null, title: null };
  const tdir = path.join(PROJECTS_DIR(home), cwdSlug(cwd, home));
  const tfile = path.join(tdir, `${sessionId}.jsonl`);
  let ms = null;
  let title = null;
  try {
    const st = fs.statSync(tfile);
    ms = nowMs - st.mtimeMs;
  } catch {}
  try {
    const content = fs.readFileSync(tfile, "utf8");
    const mt = content.match(/"title":"([^"]{0,80})"/);
    if (mt) title = mt[1];
  } catch {}
  return { ms, title };
}

/** The holder of `stream`, if its session still exists. Read-only; `home` defaults to ORCH_HOME and is injectable
 *  so tests run on fixtures.
 *
 *  cc: a `~/.claude/sessions/<pid>.json` whose session id matches `held_session` and whose pid is alive;
 *      otherwise its transcript `~/.claude/projects/<cwd-slug>/<id>.jsonl`.
 *  oc: the opencode.db session row for `held_session`.
 *  Returns { id, title, idleMs, alive } or null when nothing is held / nothing is found.
 */
export function holderSession(stream, home = orchRoot()) {
  let s;
  try {
    s = readStream(stream);
  } catch {
    return null;
  }
  if (!s || !s.held_session) return null;
  const id = String(s.held_session);
  const now = Date.now();
  if (s.held_by === "oc") {
    const dbFile = (process.env.PEER_MAIL_OC_DB ?? "").trim() || path.join(home, ".local", "share", "opencode", "opencode.db");
    if (!fs.existsSync(dbFile)) return null;
    try {
      const { DatabaseSync } = requireSqlite("node:sqlite");
      const db = new DatabaseSync(dbFile, { readOnly: true });
      try {
        db.exec("PRAGMA busy_timeout=2000;");
        let row = null;
        for (const table of ["session_v2", "session"]) {
          try {
            row = db.prepare(`SELECT time_updated AS t FROM ${table} WHERE id = ?`).get(id);
            if (row) break;
          } catch {}
        }
        db.close();
        if (!row || !Number.isFinite(row.t)) return null;
        return { id, title: null, idleMs: now - row.t, alive: true };
      } finally {
        try { db.close(); } catch {}
      }
    } catch {
      return null;
    }
  }
  // cc: walk the session files, find one whose session id matches and whose pid is alive.
  let foundPid = null;
  try {
    const entries = fs.readdirSync(SESSION_DIR(home), { withFileTypes: true });
    for (const e of entries) {
      if (!e.isFile() || !/\.json$/.test(e.name)) continue;
      const pid = Number(e.name.replace(/\.json$/, ""));
      if (!Number.isInteger(pid) || pid <= 0) continue;
      const sf = sessionFile(home, pid);
      if (!sf || sf.sessionId !== id) continue;
      try { if (process.kill(pid, 0)) { foundPid = pid; break; } } catch (e) { if (e.code === "EPERM") { foundPid = pid; break; } }
    }
  } catch {}
  if (foundPid !== null) {
    const sf = sessionFile(home, foundPid);
    let title = sf ? sf.name : null;
    let idleMs = null;
    if (sf && sf.status === "idle" && Number.isFinite(sf.statusUpdatedAt)) idleMs = now - sf.statusUpdatedAt;
    if (idleMs === null) {
      const tr = transcriptInfo(home, id, sf ? sf.cwd : null, now);
      if (tr.ms != null) idleMs = tr.ms;
      if (!title && tr.title) title = tr.title;
    }
    return { id, title, idleMs, alive: true };
  }
  // Not in the sessions dir: fall back to the transcript alone (no pid to prove alive).
  const tr = transcriptInfo(home, id, s.repo ? path.resolve(s.repo) : null, now);
  if (tr.ms === null) return null;
  return { id, title: tr.title ?? null, idleMs: tr.ms, alive: false };
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

/** { orphaned, why, escalations, waiting?, holder? }. `why` is short prose for the notice; `escalations`
 *  are the open ones. `waiting`/`holder` are set when the holder session still exists (idle, waiting on you). */
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
  const orphan = (why, waiting) => ({ orphaned: true, why, escalations, ...(waiting ? { waiting: true, holder: waiting } : {}) });
  const idleH = (ms) => Math.max(0, Math.floor(ms / 3600_000));
  if (!s.held_by) return orphan("nobody holds it");
  const idleMs = (t) => (t === null ? Infinity : now - t);
  if (typeof s.held_session === "string" && s.held_session) {
    const peer = sessionSeen(s.held_session);
    const claim = s.claim?.session === s.held_session ? ms(s.claim.at) : null;
    // Found in a store: the newest of its mail presence, its claim and the stream's own activity, so a busy
    // session that rarely touches peer-mail is not judged dead. Found nowhere: the activity rule below decides.
    const alive = Number.isFinite(newest([peer, claim])) ? newest([peer, claim, streamActivity(s)]) : -Infinity;
    if (Number.isFinite(alive)) {
      if (idleMs(alive) > limit) {
        const holder = holderSession(name);
        if (holder) {
          const h = { id: holder.id, title: holder.title, idleMs: holder.idleMs };
          return orphan(`holder session idle ${idleH(holder.idleMs)}h — waiting on you`, h);
        }
        return orphan(`holder ${s.held_by} session silent ${Math.round(idleMs(alive) / 60_000)}m`);
      }
      return none;
    }
  }
  const act = streamActivity(s);
  return idleMs(act) > limit ? orphan(`held by ${s.held_by}, no activity ${act === null ? "ever" : `${Math.round(idleMs(act) / 60_000)}m`}`) : none;
}

/** Ledger key: one page per stream per claim. A new claim (new held_at) re-arms it. */
export const orphanLedgerKey = (name, s = readStream(name)) => `orphan:${name}:${s?.held_at ?? "unheld"}`;

#!/usr/bin/env node
// The desk: a flat-context /frood-desk session watches its streams (bin/handoff.mjs) through this CLI.
//
//   node desk.mjs status [--json]
//   node desk.mjs models
//   node desk.mjs watch --events [--interval 30] [--once] [--takeover] [--until-event <sec>] [--by cc|oc]
//   node desk.mjs daemon start [--interval 30] [--by cc|oc] [--takeover] | daemon _run (internal) | daemon stop | daemon status
//   node desk.mjs step <stream> <key> [--by cc|oc]
//   node desk.mjs verdict <stream> <run> --findings <path>
//   node desk.mjs merge-check <stream> <run>
//
// `<run>` is the part of the EVENT key between `run:` and `:done` (`verdict:<run>` likewise): a run id is
// `<ticket>/<run>` — e.g. `m6a-desk-minors/worker-r1` — so one stream carries many tickets. Legacy un-prefixed ids
// (`worker-r1`) already written in a stream still step, verdict and merge-check.
//
// status: first a `watch <live|stale|none> ...` line naming the desk-watch lock owner (harness, session, pid,
//   heartbeat age, liveness) so any /frood-desk session can tell a live owner (talk to them) from a stale one (safe to
//   take over) — then per active or parked stream `<name>  <state>  next: <80>  unhandled=<n>[ held=<h>]`, then one
//   row per run `  <run>  <agent>  queued|running|done <outcome>|dead|verdict <effective>  <age>m` — with a
//   `dead` row that carries `  dead wrapper, live tree?` appended when the run's worktree has writes NEWER than
//   its run-dead event (restart reconciliation: the wrapper died but the agent may have lived on — never
//   relaunch on an unverified run-dead; see the checklist in commands/frood-orchestrator.md). --json gives a run row
//   `live_tree: true|false` (present on dead rows only).
//   --json prints `{streams: [...], watch: {...}|null}` (stream rows carry `held_by`, null when free).
//   ` held=<h>` is the stream lease (bin/handoff.mjs): the harness that holds the stream.
// watch --events: polls every active stream. A run with a `queued` event and no `run-done`/`run-dead` whose oc-worker
//   is gone gets a `run-dead` event. Every unhandled event not yet printed by this process is one stdout line
//   `EVENT <stream> <key> <kind> <outcome|effective|->` (a new watcher replays unhandled events once; `queued` is never
//   printed). stdout carries only EVENT lines; diagnostics go to stderr. One watcher at a time (lock desk-watch.lock):
//   a second one exits 3 naming the owner (pid, `--by` harness, session id, heartbeat age); a stale owner — dead,
//   zombie, recycled pid, or heartbeat past 3 x interval — is replaced without --takeover, --takeover kills a live
//   owner first (only when the recorded pid AND start match, so it never kills a stranger). --once polls once
//   without the lock. A zombie owner reads as stale, never as running: kill(pid, 0) still succeeds on zombies.
//   --until-event <sec>: takes the lock like plain watch and polls every --interval until one EVENT line was printed
//   (exit 0) or <sec> seconds passed with nothing (exit 4), so a harness without a Monitor can block on one call.
//   Not combinable with --once.
//   --by <h> (cc|oc, the harness this desk runs in): a stream whose `held_by` is set and is not h is skipped entirely in
//   that poll (no EVENT lines, no run-dead synthesis; its events stay unprinted until it is released or handed back).
//   Without --by every stream is watched.
// daemon: the same loop headless. `daemon start` double-forks `daemon _run` (internal: takes the lock with
//   kind "daemon" and never returns until fenced or signalled); the parent exits 0 once the child owns the lock,
//   or the child's code (3 when a live owner holds it). `daemon stop` SIGTERMs a live daemon (3 when a live
//   session holds the lock instead), clears a stale one. `daemon status` prints the `watch` line plus pending
//   escalations. The driver executes ACTION lines itself (critic prompt + headless oc-worker, detached resume,
//   ff-merge path) and pages once per ESCALATE (escalations.jsonl + notify-send). ORCH_DAEMON_DRY_RUN=1 logs
//   every action instead of spawning anything.
//   A judgment call is peer-mailed to the stream's holding session instead of the user (`notifyHeldSession`),
//   whichever harness holds it (an OpenCode `ses_…` id or a Claude Code peer-mail id), with the notify-send
//   page kept only for when no mail went out: no session holds the stream, or its mailbox cannot be written.
//   Orphaned streams: an open escalation on a stream nobody live is working (unheld, or the holder's session silent
//   past ORCH_ORPHAN_MIN, default 60) pages the owner ONCE per stream per claim (`orphaned` ledger in state.json) with a
//   desktop notice whose "Resolve in new session" action opens a terminal on `/frood-next <stream>`
//   (orphan-notice.mjs, ORCH_LAUNCH_CMD overrides the command). See orphan.mjs for the detection rules.
//   That same wake-up also fires when a
//   ticket reaches a terminal state the owner should hear about through that session — `ESCALATE merge`
//   (ready, or merged by the daemon itself), `ESCALATE senior`, `ESCALATE owner-signoff` — so the owner never
//   has to watch `status` for a merge. Quiet for `ACTION resume-worker`, critic dispatches and retries, and
//   held streams only (it reaches a session, never the desktop). Once-only is the one ledger in
//   state.json, shared with dpage and keyed by stream+event (`pagedIds`), so one stream's escalation can
//   never suppress another's same-named event; ORCH_DAEMON_DRY_RUN=1 keeps a wake-up out of the file so a
//   rehearsal cannot consume a key a live run still has to act on.
//   That shared identity is a deliberate coupling: a completion wake-up for (stream, key) makes a later
//   `handleEvent` for the same stream+key return `paged` before acting, and a later `dpage` for it silent.
//   Safe because events are acked first — an entry suppresses only a second report of one event, never a
//   distinct event — and because the ledger key carries the stream, so no other stream can match it.
// step: one line for one event. Already acked and its action's effect is present -> `DONE <key>` (nothing to do);
//   acked without the effect -> the stored line again (retry after a crash or /clear); otherwise it decides, acks
//   and prints exactly one line: `ACTION critic <ticket.json> <out> <findings-r<N>.md> <N>`,
//   `ACTION resume-worker <command>` or `ESCALATE <reason> <path>`. Never runs git, never spawns anything.
//   An event of a **closed ticket** — its worktree has no `.git` entry (the worktree was removed after the merge, even
//   if an orphan directory remains) — is stale: step acks it with `STALE ticket-closed` plus a resolved ack for the key
//   and prints `DONE <key>`, so a fresh /frood-desk never replays a merged ticket's old run-done as `ACTION critic`.
//   The round is derived: 1 + the acks whose action starts `ACTION resume-worker` for the same ticket.
//   Every path it prints carries forward slashes (the stored ack line is the printed line).
//   --by <h>: a stream held by the other harness prints `HELD <stream> <holder>` and exits 0, acking nothing.
// verdict: runs verdict-gate's gate() on a findings file (paid), appends the `verdict:<run>` event, resolved-acks
//   the critic's `run:<run>:done` (a reviewed run-done is handled: it leaves `unhandled`), and prints
//   `KEY verdict:<run>` (not an EVENT line: the desk runs step on that key itself).
// merge-check: the worktree is clean, HEAD = the verdict's reviewed_sha, base is an ancestor of HEAD (ff possible)
//   and the verdict is APPROVED -> `OK`; otherwise `FAIL <check>` (dirty|head-moved|not-ff|not-approved).
// Exit: 0 ok; 1 merge-check FAIL; 2 usage, IO, unknown stream/event/run or git failure; 3 another watcher holds a
//   live lock (stderr names the owner: pid, harness, session — message them, or --takeover a stale one per `status`);
//   4 watch --until-event: the deadline passed with no event.
// ORCH_NOW_MS replaces the clock (tests).
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync, spawn, spawnSync } from "node:child_process";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";
import { appendAck, appendEvent, atomicWrite, listStreams, migrate, noteStream, orchRoot, readAckLines, readEvents, readStream, streamsDir, unhandled } from "./handoff.mjs";
import { gate } from "./verdict-gate.mjs";
import { openEscalations, orphanLedgerKey, streamOrphaned } from "./orphan.mjs";
export { streamOrphaned } from "./orphan.mjs";
import { killPid, processStart, isZombie } from "./proc-tree.mjs";
import { agentModel, isPolicyFree, isDown, modelAllowed, policyReason } from "./pool-health.mjs";

const NEXT_CUT = 80;
const DEFAULT_INTERVAL_S = 30;
const ROUND_CAP = 3; // mirrors ticket.json max_rounds; only used when the ticket omits it
// Derived from this module's location so the desk's resume line names the checkout it runs from.
const ORPHAN_NOTICE = fileURLToPath(new URL("./orphan-notice.mjs", import.meta.url));
// ORCH_OC_WORKER: tests point the daemon's spawns at a stub that records its argv.
const OC_WORKER = process.env.ORCH_OC_WORKER || fileURLToPath(new URL("./oc-worker.mjs", import.meta.url)).replace(/\\/g, "/");
const nowMs = () => (process.env.ORCH_NOW_MS ? Number(process.env.ORCH_NOW_MS) : Date.now());
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const isStr = (v) => typeof v === "string";

// Peer-mail to the stream's holding session: the desk notifies the responsible
// orchestration session instead of paging the user directly. That session's agent
// resolves the escalation and brings questions to the user.
const requireSqlite = createRequire(import.meta.url);
// Resolved per call, not at load: ORCH_HOME is the desk's state root (handoff.mjs orchRoot), so a test home owns
// its own mailbox and never writes into the real one. In production ORCH_HOME is unset and this is the user's home.
const mailboxDb = () => path.join(orchRoot(), ".local", "share", "opencode-peer-mail", "mailbox.db");
const DESK_PEER_ID = "desk-daemon";

function newId() {
  return `msg_${Date.now().toString(36)}${crypto.randomBytes(4).toString("hex")}`;
}

// The shape handoff.mjs accepts for `--session`: an OpenCode `ses_…` id and a Claude Code peer-mail id
// (the transcript UUID) both pass. Until 2026-11-23 only `ses_` was mailed, so every escalation on a
// stream a Claude Code orchestrator held fell through to the desktop page.
const HELD_SESSION_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;

/** Send a peer-mail message to the session that holds `stream`, so that session's
 *  orchestrator agent can resolve the escalation instead of paging the user directly.
 *  Returns true only when the message was written. Best-effort: never crashes the desk
 *  loop and never pages itself — a false return is the caller's notify-send decision. */
function notifyHeldSession(stream, key, reason) {
  const s = readStream(stream);
  const toSession = s?.held_session;
  if (typeof toSession !== "string" || !HELD_SESSION_RE.test(toSession)) return false;
  const file = mailboxDb();
  if (!fs.existsSync(file)) {
    // A held stream with no mailbox cannot be woken. Say so rather than fail silently:
    // the completion wake-up has no desktop fallback, so this line is its only trace.
    console.error(`daemon: cannot send peer-mail to ${toSession}: no mailbox at ${file}`);
    return false;
  }
  const by = s.held_by === "cc" ? "cc" : "oc";
  try {
    const { DatabaseSync } = requireSqlite("node:sqlite");
    const db = new DatabaseSync(file, { readOnly: false });
    db.exec("PRAGMA busy_timeout=2000;");
    db.exec("PRAGMA journal_mode=WAL;");
    // Register desk-daemon as a peer so validation passes on read.
    db.prepare(`INSERT INTO peers (session_id, harness, title, directory, branch, first_seen, last_seen)
     VALUES (?, 'claude', 'orchestrator desk', '', '', ?, ?)
     ON CONFLICT(session_id) DO UPDATE SET last_seen = ?`)
      .run(DESK_PEER_ID, Date.now(), Date.now(), Date.now());
    const now = Date.now();
    const id = newId();
    db.prepare(`INSERT INTO messages (id, ts, from_session, from_title, from_branch, to_session, subject, body, status, expires_at)
     VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'unread', ?)`)
      .run(id, now, DESK_PEER_ID, "orchestrator desk", "", toSession,
        `desk: ${reason}`,
        `${reason}\n\nStream: ${stream}\nEvent: ${key}\nResolve with:\n  node ${SELF_BIN} step ${stream} ${key} --by ${by}\n`,
        now + 14 * 24 * 60 * 60 * 1000);
    db.close();
    return true;
  } catch (e) {
    console.error(`daemon: cannot send peer-mail to ${toSession}: ${e.message}`);
    return false;
  }
}

export const lockPath = () => path.join(orchRoot(), ".config", "orchestrator", "desk-watch.lock");

function alive(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
}

// M10: a null pid_start (lookup failed) means the pid check alone decides.
// A zombie is dead, not live: kill(pid, 0) succeeds until the parent reaps it, and ps still lists it with a
// matching start — without this exclusion a closed session's watcher reads as "running" for its whole zombie window.
export function runIsLive(q) {
  if (!alive(q.pid)) return false;
  if (isZombie(q.pid)) return false;
  if (!q.pid_start) return true;
  const cur = processStart(q.pid);
  return cur !== null && cur === q.pid_start;
}

// ---------------------------------------------------------------- runs (derived from events)

function runOf(e) {
  if (typeof e.run === "string" && e.run) return e.run;
  const m = /^(?:run:(.+):(?:queued|done|dead)|verdict:(.+))$/.exec(e.key);
  return m ? m[1] ?? m[2] : null;
}

export function runsOf(events) {
  const runs = new Map();
  for (const e of events) {
    const run = runOf(e);
    if (!run) continue;
    const r = runs.get(run) ?? { run, first: e.at };
    if (e.kind === "queued") r.queued = e;
    else if (e.kind === "run-done") r.done = e;
    else if (e.kind === "run-dead") r.dead = e;
    else if (e.kind === "verdict") r.verdict = e;
    runs.set(run, r);
  }
  return [...runs.values()];
}

const wordOf = (e) => (e.kind === "run-done" ? e.outcome : e.kind === "verdict" ? e.effective : "-") ?? "-";

// ---------------------------------------------------------------- poll

// One pass over every active stream. ctx: {interval (s), lastPoll (ms|null), printed (Set), out (line writer), err}.
// Returns the number of EVENT lines this pass wrote, so a caller can stop on the first informative poll.
export function poll(ctx) {
  const now = nowMs();
  const slept = ctx.lastPoll != null && now - ctx.lastPoll > 5 * ctx.interval * 1000; // the host slept: queued pids look dead
  const err = ctx.err ?? ((m) => console.error(m));
  let wrote = 0;
  for (const s of listStreams(now)) {
    if (s.status !== "active") continue;
    if (ctx.by && s.held_by && s.held_by !== ctx.by) continue; // the other harness holds it: not this desk's to watch
    warnUnreadable(s.name, ctx, err);
    if (!slept) {
      for (const r of runsOf(readEvents(s.name))) {
        if (!r.queued || r.done || r.dead || runIsLive(r.queued)) continue;
        try {
          appendEvent(s.name, { key: `run:${r.run}:dead`, kind: "run-dead", run: r.run, out: r.queued.out, at: new Date(now).toISOString() });
        } catch (e) {
          err(`desk-watch: cannot append run-dead for ${s.name}/${r.run}: ${e.message}`);
        }
      }
    }
    for (const e of unhandled(s.name)) {
      const id = `${s.name}\0${e.key}`;
      if (ctx.printed.has(id)) continue;
      ctx.printed.add(id);
      ctx.out(`EVENT ${s.name} ${e.key} ${e.kind} ${wordOf(e)}`);
      wrote++;
    }
  }
  ctx.lastPoll = now;
  return wrote;
}

// handoff.mjs skips an unreadable events line silently; the watcher says so on stderr, once per line.
function warnUnreadable(name, ctx, err) {
  ctx.warned ??= new Set();
  let raw;
  try {
    raw = fs.readFileSync(path.join(streamsDir(), `${name}.events.jsonl`), "utf8");
  } catch {
    return;
  }
  raw.split(/\r?\n/).forEach((line, i) => {
    if (!line.trim()) return;
    let ok = false;
    try {
      const v = JSON.parse(line);
      ok = Boolean(v && typeof v === "object" && typeof v.key === "string" && v.key);
    } catch {}
    const id = `${name}:${i}:${line}`;
    if (ok || ctx.warned.has(id)) return;
    ctx.warned.add(id);
    err(`desk-watch: ${name}.events.jsonl line ${i + 1} is unreadable; skipped`);
  });
}

// ---------------------------------------------------------------- the single-instance lock

function readOwner() {
  try {
    return JSON.parse(fs.readFileSync(path.join(lockPath(), "owner"), "utf8"));
  } catch {
    return null;
  }
}

const SELF_START = { v: undefined };
// The session holding the watch lock, for the exit-3 message and `status`: a contending /frood-desk session reads this
// (not a pid alone) to tell its own dead session from someone else's live one. Harness id comes from --by, not env.
function ownerSession() {
  return process.env.OPENCODE_SESSION_ID || process.env.ORCH_SESSION || null;
}
function writeOwner(token, at, by, extra) {
  SELF_START.v ??= processStart(process.pid); // one lookup: a slow lookup between the fence check and the write would clobber a new owner
  atomicWrite(
    path.join(lockPath(), "owner"),
    JSON.stringify({ pid: process.pid, pid_start: SELF_START.v, at: new Date(at).toISOString(), token, by: by ?? null, session: ownerSession(), ...(extra ?? {}) }),
  );
}

// Who holds the lock, for the exit-3 message: pid, heartbeat time, harness and session when recorded (older
// records predate the identity fields and print without them). A new /frood-desk session reads this plus the `watch`
// status line to decide: message the live owner, or --takeover a stale or confirmed-closed one — never silently.
function lockHeldMsg(owner) {
  const who = [owner.by ? `by ${owner.by}` : null, owner.session ? `session ${owner.session}` : null].filter(Boolean).join(", ");
  return `desk-watch: running as pid ${owner.pid} since ${owner.at}${who ? ` (${who})` : ""}`;
}

// Returns {token} when the lock is ours, {code, msg} when not.
async function takeLock(interval, takeover, by, extra) {
  const dir = lockPath();
  fs.mkdirSync(path.dirname(dir), { recursive: true });
  const token = crypto.randomBytes(6).toString("hex");
  for (let attempt = 0; attempt < 5; attempt++) {
    try {
      fs.mkdirSync(dir);
      writeOwner(token, nowMs(), by, extra);
      return { token };
    } catch (e) {
      if (e.code !== "EEXIST") throw e;
    }
    const owner = readOwner();
    if (owner && owner.pid !== process.pid) {
      const fresh = nowMs() - Date.parse(owner.at) <= 3 * interval * 1000;
      if (!takeover && fresh && runIsLive(owner)) return { code: 3, msg: lockHeldMsg(owner) };
      // --takeover kills any owner that is verifiably the recorded process (pid alive, start time matches), stale or not.
      // Without it a stale owner is just replaced: if it is still alive it fences itself on its next poll.
      if (takeover && owner.pid_start && processStart(owner.pid) === owner.pid_start) await killPid(owner.pid);
    } else if (!owner) {
      await sleep(100); // the holder is between mkdir and writing `owner`
      if (!readOwner()) fs.rmSync(dir, { recursive: true, force: true });
      continue;
    }
    fs.rmSync(dir, { recursive: true, force: true });
  }
  return { code: 2, msg: "desk-watch: cannot take the lock" };
}

// ---------------------------------------------------------------- watch

const BY = new Set(["cc", "oc"]);

const usage = () =>
  "usage: desk.mjs status [--json] | models | watch --events [--interval 30] [--once] [--takeover] [--until-event <sec>] [--by cc|oc]\n" +
  "       desk.mjs daemon start [--interval 30] [--by cc|oc] [--takeover] | daemon stop | daemon status\n" +
  "       desk.mjs step <stream> <key> [--by cc|oc] (HELD <stream> <holder> when the other harness holds it) | verdict <stream> <worker-run> --findings <path>\n" +
  "       desk.mjs merge-check <stream> <worker-run>";

async function cmdWatch(opts) {
  if (!opts.events) {
    console.error("desk: watch needs --events");
    return 2;
  }
  if (opts.by !== undefined && !BY.has(opts.by)) {
    console.error(`desk: --by must be cc or oc\n${usage()}`);
    return 2;
  }
  const interval = opts.interval ?? DEFAULT_INTERVAL_S;
  if (!(interval > 0)) {
    console.error("desk: --interval must be a positive number of seconds");
    return 2;
  }
  if (opts.untilEvent !== undefined) {
    if (opts.once) {
      console.error(`desk: --until-event cannot be combined with --once\n${usage()}`);
      return 2;
    }
    if (!(opts.untilEvent > 0)) {
      console.error(`desk: --until-event must be a positive number of seconds\n${usage()}`);
      return 2;
    }
  }
  const ctx = { by: opts.by, interval, lastPoll: null, printed: new Set(), out: (l) => process.stdout.write(l + "\n") };
  if (opts.once) {
    poll(ctx);
    return 0;
  }
  const got = await takeLock(interval, opts.takeover, opts.by);
  if (got.code) {
    console.error(got.msg);
    return got.code;
  }
  // --until-event: the deadline is measured on the same clock the fence and the freshness check use (ORCH_NOW_MS in tests).
  const deadline = opts.untilEvent !== undefined ? nowMs() + opts.untilEvent * 1000 : null;
  for (;;) {
    const owner = readOwner();
    if (!owner || owner.token !== got.token) return 0; // fenced: someone else owns the lock now
    let wrote = 0;
    try {
      if (readOwner()?.token === got.token) writeOwner(got.token, nowMs(), opts.by); // re-check right before the refresh
      wrote = poll(ctx);
    } catch (e) {
      console.error(`desk-watch: poll failed: ${e.message}`);
    }
    if (deadline !== null) {
      if (wrote > 0) return 0;
      const left = deadline - nowMs();
      if (left <= 0) return 4;
      await sleep(Math.min(interval * 1000, left)); // never oversleep the deadline the caller asked for
      continue;
    }
    await sleep(interval * 1000);
  }
}

// ---------------------------------------------------------------- status

const cut = (s, n) => (String(s ?? "").length > n ? String(s).slice(0, n) : String(s ?? ""));

// ---------------------------------------------------------------- restart reconciliation (read-only flag)

// A host restart can kill the oc-worker wrapper while the agent lives on and keeps writing; the watcher then
// records a `run-dead` that is a lie, and relaunching on that lie spawned a duplicate worker (incident:
// video-studio M2, 2026-11-17). Status only surfaces the contradiction — "dead wrapper, live tree?" — so the
// orchestrator's restart checklist can ADOPT the live agent (`oc-worker --session`) instead of relaunching.
// Nothing here decides, relaunches or acks; it is a flag on the status output.

// The ticket.json a run was dispatched under: the queued event carries its path, and a `run-dead` written by the
// watcher carries only `out`, whose directory is the run dir holding that same ticket.json.
const ticketFileOf = (r) => r.queued?.ticket ?? (r.dead?.out ? path.join(path.dirname(path.resolve(r.dead.out)), "ticket.json") : null);

// True when anything inside `root` was written after `afterMs` (a symlink's target counts; a dangling one is
// skipped). Bounded walk: `.git` and `node_modules` are skipped (metadata and dependency churn is not agent
// activity) and at most `budget` entries are read — exhausting the budget returns false, so a big tree can only
// ever hide the flag, never raise it. A read failure (gone worktree) is false for the same reason.
export function wroteAfter(root, afterMs, budget = 20000) {
  let seen = 0;
  const walk = (dir) => {
    let entries;
    try {
      entries = fs.readdirSync(dir, { withFileTypes: true });
    } catch {
      return false;
    }
    for (const e of entries) {
      if (++seen > budget) return false;
      const p = path.join(dir, e.name);
      if (e.isDirectory()) {
        if (e.name === ".git" || e.name === "node_modules") continue;
        if (walk(p)) return true;
        continue;
      }
      try {
        if (fs.statSync(p).mtimeMs > afterMs) return true;
      } catch {
        // dangling symlink or a file deleted between readdir and stat: not evidence of anything
      }
    }
    return false;
  };
  return walk(root);
}

// The run's worktree from its ticket.json, or null when there is no usable ticket (legacy events) — in which
// case there is nothing to compare and the flag stays off.
function worktreeOf(r) {
  const file = ticketFileOf(r);
  const t = file ? readTicket(file) : null;
  return typeof t?.worktree === "string" && t.worktree ? t.worktree : null;
}

function runState(r) {
  if (r.verdict) return { state: "verdict", detail: r.verdict.effective ?? "-" };
  if (r.done) return { state: "done", detail: r.done.outcome ?? "-" };
  if (r.dead) return { state: "dead", detail: null };
  if (r.queued && runIsLive(r.queued)) return { state: "running", detail: null };
  return { state: "queued", detail: null };
}

export function statusRows(now = nowMs()) {
  const rows = [];
  for (const s of listStreams(now)) {
    if (s.status !== "active" && s.status !== "parked") continue;
    const events = readEvents(s.name);
    const runs = runsOf(events).map((r) => {
      const { state, detail } = runState(r);
      const since = Date.parse(r.queued?.at ?? r.first);
      // Restart reconciliation: only a dead run can contradict the tree, and only the tree's writes that are
      // NEWER than the death timestamp count (writes that predate the restart prove nothing).
      const deadAt = state === "dead" ? Date.parse(r.dead?.at) : NaN;
      const wt = worktreeOf(r);
      const liveTree = Number.isFinite(deadAt) && wt !== null ? wroteAfter(wt, deadAt) : false;
      return {
        run: r.run,
        agent: r.queued?.agent ?? r.done?.agent ?? "-",
        state,
        detail,
        age_min: Number.isFinite(since) ? Math.max(0, Math.floor((now - since) / 60000)) : null,
        ...(state === "dead" ? { live_tree: liveTree } : {}),
      };
    });
    rows.push({ name: s.name, state: s.state, next: s.next ?? "", unhandled: unhandled(s.name).length, held_by: s.held_by ?? null, runs });
  }
  return rows;
}

// Board tickets that carry a desktop session (board.mjs `session`), for the repo the desk is run from. A ticket
// with no session, a missing board or an unreadable file contributes nothing: this only adds lines to `status`.
export function ticketSessions(dir = process.cwd()) {
  let root = dir;
  try {
    root = path.dirname(execFileSync("git", ["-C", dir, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim());
  } catch {}
  const tdir = path.join(root, ".opencode", "board", "tickets");
  let names = [];
  try {
    names = fs.readdirSync(tdir).filter((n) => n.endsWith(".json")).sort();
  } catch {
    return [];
  }
  const rows = [];
  for (const n of names) {
    try {
      const t = JSON.parse(fs.readFileSync(path.join(tdir, n), "utf8"));
      const session = t?.assignment?.session;
      if (t?.schema === 1 && isStr(t.id) && isStr(session) && session) rows.push({ id: t.id, stage: t.stage, session, owner: t.assignment.owner ?? null });
    } catch {}
  }
  return rows;
}

const fmtAge = (ms) => {
  if (ms === null) return "?";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h`;
};

// The watch lock as one value: `status` prints it and takeLock's exit-3 points at it, so any /frood-desk session can
// tell whether the lock is held live (message the owner) or stale (safe to take over) without guessing from a
// pid. Stale covers: owner gone, owner a zombie (dead, awaiting reap), pid recycled under a new process (start
// mismatch), or a live owner whose heartbeat expired (crashed between heartbeats, clock jumped).
export function watchInfo(now = nowMs()) {
  const owner = readOwner();
  if (!owner || !Number.isInteger(owner.pid) || owner.pid <= 0) return { state: "none" };
  const at = Date.parse(owner.at);
  const ageMs = Number.isFinite(at) ? Math.max(0, now - at) : null;
  const zombie = isZombie(owner.pid);
  const live = runIsLive({ pid: owner.pid, pid_start: owner.pid_start ?? null });
  const started = owner.pid_start ? processStart(owner.pid) : null;
  const verified = Boolean(owner.pid_start) && started !== null && started === owner.pid_start;
  const fresh = ageMs !== null && ageMs <= 3 * DEFAULT_INTERVAL_S * 1000;
  const info = { pid: owner.pid, by: owner.by ?? null, session: owner.session ?? null, kind: owner.kind ?? "session", log: owner.log ?? null, age_ms: ageMs, verified };
  if (live && fresh) return { state: "live", ...info };
  let reason = "heartbeat expired";
  if (zombie) reason = "zombie (dead, awaiting reap)";
  else if (!live && !alive(owner.pid)) reason = "owner process gone";
  else if (!live) reason = "pid recycled (start mismatch)";
  return { state: "stale", reason, ...info };
}

const whoOf = (w) =>
  [w.kind && w.kind !== "session" ? w.kind : null, w.by ? `by ${w.by}` : null, w.session ? `session ${w.session}` : null].filter(Boolean).join(", ");

function watchLine(w) {
  if (w.state === "none") return "watch none — no desk watcher holds the lock";
  const who = whoOf(w);
  if (w.state === "live") return `watch live pid=${w.pid}${who ? ` (${who})` : ""} heartbeat ${fmtAge(w.age_ms)} ago${w.verified ? " (start verified)" : " (start unverified)"}${w.kind === "daemon" && w.log ? ` log=${w.log}` : ""}`;
  return `watch stale pid=${w.pid}${who ? ` (${who})` : ""} last heartbeat ${fmtAge(w.age_ms)} ago (${w.reason}) — safe to take: run watch again or add --takeover`;
}

function cmdStatus(opts) {
  const info = watchInfo();
  const rows = statusRows();
  const tickets = ticketSessions();
  if (opts.json) {
    // `tickets` appears only when some board ticket holds a session, so the existing shape is unchanged.
    console.log(JSON.stringify({ streams: rows, watch: info.state === "none" ? null : info, ...(tickets.length ? { tickets } : {}) }));
    return 0;
  }
  console.log(watchLine(info));
  for (const s of rows) {
    console.log(`${s.name}  ${s.state}  next: ${cut(s.next, NEXT_CUT)}  unhandled=${s.unhandled}${s.held_by ? ` held=${s.held_by}` : ""}`);
    for (const r of s.runs) console.log(`  ${r.run}  ${r.agent}  ${r.detail ? `${r.state} ${r.detail}` : r.state}  ${r.age_min ?? "-"}m${r.live_tree ? "  dead wrapper, live tree?" : ""}`);
  }
  for (const t of tickets) console.log(`ticket ${t.id}  ${t.stage}  session ${t.session}${t.owner ? `  owner ${t.owner}` : ""}`);
  return 0;
}

// ---------------------------------------------------------------- daemon (headless driver)

// The daemon runs the same poll -> step -> act loop as an interactive desk, detached from any session: workers it
// launches are detached (as oc-worker's are), so closing every session stalls nothing. Judgment calls page the
// owner exactly once per stream+key (the `pagedIds` ledger) and never block other streams. ORCH_DAEMON_DRY_RUN=1
// logs every action instead of spawning anything (tests, safe rehearsal).
const REPO_ROOT = path.resolve(fileURLToPath(import.meta.url), "..", "..");
const SELF_BIN = fileURLToPath(import.meta.url);
const daemonDir = () => path.join(orchRoot(), ".config", "orchestrator", "desk-daemon");
const daemonLogFile = () => path.join(daemonDir(), "daemon.log");
const daemonStateFile = () => path.join(daemonDir(), "state.json");
const daemonEscFile = () => path.join(daemonDir(), "escalations.jsonl");
const DAEMON_DRY = () => process.env.ORCH_DAEMON_DRY_RUN === "1";

export function readDaemonState() {
  try {
    const s = JSON.parse(fs.readFileSync(daemonStateFile(), "utf8"));
    if (s && typeof s === "object") {
      const st = { retries: s.retries ?? {}, paged: Array.isArray(s.paged) ? s.paged : [], pagedIds: Array.isArray(s.pagedIds) ? s.pagedIds : [], errors: s.errors ?? {}, orphaned: Array.isArray(s.orphaned) ? s.orphaned : [] };
      // Loop-stay ids sit in `paged` already stream-scoped. Adopt them on EVERY read, before the
      // pre-schema upgrade below: the two changes can board in either order, and the file dpage-scope
      // writes already has `pagedIds`, so the once-only upgrade would never run for it.
      const adopted = adoptLoopStayIds(st);
      // A file written before this schema has no `pagedIds` at all: its `paged` holds dpage's bare keys.
      // Adopt them once (their stream comes from escalations.jsonl, which always recorded one), so an
      // unresolved pre-upgrade escalation is neither re-paged nor matched against another stream.
      if (typeof s.pagedIds === "undefined") adoptLegacyPaged(st);
      // Persist an adoption rather than leaving it for the next page: the id must survive a poll that
      // never writes. Written after both upgrades so the write cannot itself suppress the bare-key one
      // (a persisted `pagedIds` would make the next read skip it).
      if (adopted) writeDaemonState(st);
      return st;
    }
  } catch {}
  return { retries: {}, paged: [], pagedIds: [], errors: {}, orphaned: [] };
}
function writeDaemonState(s) {
  fs.mkdirSync(daemonDir(), { recursive: true });
  atomicWrite(daemonStateFile(), JSON.stringify(s));
}

// One identity for a ledger entry — an escalation or a completion wake-up: the stream AND the key,
// so two streams that share a run id (every stream's first run is `worker-r1`) are distinct and no
// stream can consume, or be silenced by, another's entry.
const wakeId = (stream, key) => `${stream}\u0000${key}`;

// The once-only ledger, in two fields for one upgrade reason:
//   `pagedIds` is authoritative — every entry is `wakeId(stream, key)`, so a bare key can never match
//     and no stream can silence another (the hazard: step acks first, so a suppressed event is consumed
//     with no effect). Every reader goes through `wasPaged`, every writer through `markPaged`.
//   `paged` predates the stream scoping: dpage wrote a BARE event key there and the completion wake-up
//     its `wakeId`, the split that made stream A's `verdict:worker-r1` suppress stream B's identical
//     event. Both keep writing it in that historical shape (it is the documented schema,
//     docs/designs/desk-daemon.md: `{retries, paged, pagedIds, errors}`), but nothing *suppresses* on it any
//     more: a pre-upgrade bare entry is inert there and cannot re-suppress another stream. Its once-only
//     meaning is carried over into `pagedIds`: bare keys on first read by `adoptLegacyPaged` (via
//     escalations.jsonl), loop-stay-era `wakeId`s by `adoptLoopStayIds` on every read (they are already
//     scoped, and must land even on a file that already has `pagedIds`). The readers: `wasPaged` (the only
//     suppression) and `markPaged`'s dedupe both read `pagedIds` alone; `paged` is read by `readDaemonState`
//     (to hold it), `adoptLoopStayIds` and `adoptLegacyPaged` (upgrade only).
//   `errors` and `retries` are keyed by that same `wakeId(stream, key)`: both are per-stream counters (step
//     failures against the 3-strike page, and the one critic-alt retry), so a bare key let stream A's failures
//     push stream B's counter over the limit and page B for an event B never failed. Entries a pre-upgrade file
//     wrote bare are inert after the upgrade (they match no stream) — the counter restarts at zero, never
//     shared, which is the safe direction: one extra retry, never a page for another stream's failures.
function wasPaged(state, stream, key) {
  return state.pagedIds.includes(wakeId(stream, key));
}
function markPaged(state, stream, key, legacy) {
  const id = wakeId(stream, key);
  if (!state.pagedIds.includes(id)) state.pagedIds.push(id);
  if (!state.paged.includes(legacy)) state.paged.push(legacy);
}
// Loop-stay wrote its completion wake-up ids into `paged` (`wakeId(stream, key)`) before `pagedIds` existed.
// Those entries are already stream-scoped, so they need no attribution from escalations.jsonl: copy them
// straight across, deduped. This runs on EVERY read, unlike the once-only bare-key upgrade below — a file
// dpage-scope wrote already has `pagedIds`, so `adoptLegacyPaged` would never run for it, and a loop-stay id
// left in `paged` (the two changes boarding in the wrong order) would re-process its event and wake the
// holder a second time after the upgrade. Returns true when anything was added so the caller can persist it.
function adoptLoopStayIds(state) {
  const ids = new Set(state.pagedIds);
  const before = ids.size;
  for (const e of state.paged) if (typeof e === "string" && e.includes("\u0000")) ids.add(e);
  if (ids.size === before) return false; // every scoped `paged` entry is already adopted: read-only
  state.pagedIds = [...ids];
  return true;
}
// A `paged` entry written before this schema is a bare key with no stream in it, so it cannot say which
// stream escalated it — matching it against every stream is the bug being fixed. escalations.jsonl has
// always recorded `{at, stream, key, reason}`, so the scoped ledger is rebuilt from it exactly: the
// upgrade keeps an already-notified escalation notified instead of paging it a second time, and a bare
// key with no recorded row stays without a scoped entry rather than matching every stream.
// Runs once per pre-upgrade file; after the first write `pagedIds` exists and this never parses again.
// (`paged`'s loop-stay-era scoped ids are handled by `adoptLoopStayIds`, on every read.)
function adoptLegacyPaged(state) {
  const bare = state.paged.filter((e) => typeof e === "string" && !e.includes("\u0000"));
  if (!bare.length) return;
  const owners = new Map(); // bare key -> every scoped id escalations.jsonl attributes to it
  try {
    for (const l of fs.readFileSync(daemonEscFile(), "utf8").split("\n").filter(Boolean)) {
      let e;
      try {
        e = JSON.parse(l);
      } catch {
        continue;
      }
      if (!e || typeof e.stream !== "string" || typeof e.key !== "string") continue;
      const id = wakeId(e.stream, e.key);
      if (!owners.has(e.key)) owners.set(e.key, []);
      if (!owners.get(e.key).includes(id)) owners.get(e.key).push(id);
    }
  } catch {}
  for (const k of bare) {
    for (const id of owners.get(k) ?? []) if (!state.pagedIds.includes(id)) state.pagedIds.push(id);
  }
}

// A judgment call the daemon may not make: recorded for `daemon status`, notified once per stream+key.
// dpage itself enforces once-only: every call site may page unconditionally and a stuck key still
// notifies exactly once, no matter which path (verdict, critic, resume, merge) hits it. Best effort
// throughout: paging must never crash the loop.
function dpage(stream, key, reason) {
  const entry = { at: new Date().toISOString(), stream, key, reason };
  try {
    fs.mkdirSync(daemonDir(), { recursive: true });
    const s = readDaemonState();
    if (wasPaged(s, stream, key)) return; // this stream already escalated it: never re-page, never re-log
    fs.appendFileSync(daemonEscFile(), JSON.stringify(entry) + "\n");
    markPaged(s, stream, key, key);
    writeDaemonState(s);
  } catch (e) {
    console.error(`daemon: cannot record escalation: ${e.message}`);
  }
  const text = `desk daemon: ${reason} (${stream} ${key}) — open a /frood-desk`;
  console.log(text);
  // Notify the responsible orchestration session (stream holder) via peer-mail.
  // That session's agent resolves the escalation and brings questions to the user.
  // Desktop notify only for an unheld stream (no agent can act). A held stream whose holder cannot be
  // mailed is left for that holder: the escalation stays in the ack file, escalations.jsonl and `status`.
  const mailed = notifyHeldSession(stream, key, reason);
  // The one desktop path: a stream nobody live is working (unheld, or its holder gone quiet) gets the
  // once-per-stream notice with a "Resolve in new session" action. A live holder keeps peer-mail only.
  if (streamOrphaned(stream).orphaned) {
    orphanPage(stream);
    return;
  }
  // A missing, done or parked stream has no session to resume (/frood-next refuses it): plain page, no action.
  const cur = readStream(stream);
  if (!cur || cur.status === "done" || cur.status === "parked") {
    notifyDesktop(text);
    return;
  }
  if (mailed) return;
  const holder = readStream(stream)?.held_by;
  if (holder) console.error(`daemon: escalation left for holder ${holder} (no reachable session): ${reason} (${stream} ${key})`);
}

// A plain critical notice (no action) for an escalation no session can resume. dpage's ledger makes it once per key.
function notifyDesktop(text) {
  if (process.env.ORCH_NO_NOTIFY === "1" || DAEMON_DRY()) return;
  try {
    execFileSync("notify-send", ["-u", "critical", "orchestrator desk", text], { stdio: "ignore", windowsHide: true });
  } catch {}
}

const dryOrphanLogged = new Set(); // dry run only: log each would-be page once per process, not every poll

// Page the owner once per stream per claim about an orphaned stream. The ledger (`orphaned` in state.json, key
// `orphan:<stream>:<held_at|unheld>`) means N escalations on one dead stream page once and a new claim re-arms it.
// Dry-run and ORCH_NO_NOTIFY log instead of spawning; a dry run writes no ledger entry. Returns true when it paged.
function orphanPage(stream) {
  try {
    const state = readDaemonState();
    const id = orphanLedgerKey(stream);
    if (state.orphaned.includes(id)) return false;
    if (DAEMON_DRY()) {
      if (!dryOrphanLogged.has(id)) {
        dryOrphanLogged.add(id);
        console.log(`daemon: DRY would page orphaned stream ${stream}`);
      }
      return false;
    }
    state.orphaned.push(id);
    writeDaemonState(state);
    if (process.env.ORCH_NO_NOTIFY === "1") {
      console.log(`daemon: orphaned stream ${stream} (notify suppressed)`);
      return true;
    }
    console.log(`daemon: orphaned stream ${stream}: notice launched`);
    detached(process.execPath, [ORPHAN_NOTICE, stream]);
    return true;
  } catch (e) {
    console.error(`daemon: cannot page orphaned stream ${stream}: ${e.message}`);
    return false;
  }
}

// A stream with no open escalation left forgets its ledger entries, so a later escalation on it pages again.
// An entry also goes when the claim it recorded can never page again: the stream is deleted (no pointer file),
// finished or parked (nothing to resume), or the stream's current held_at differs from the entry's (a newer claim
// re-armed paging with its own key, and the old page must not suppress anything). A live orphaned stream's current
// entry stays, so a second poll does not page it again.
function pruneOrphanLedger() {
  if (DAEMON_DRY()) return;
  try {
    const state = readDaemonState();
    const keep = state.orphaned.filter((id) => {
      const m = /^orphan:([^:]+):(.*)$/.exec(id);
      if (!m) return true; // unparseable: leave it alone, it can never match a stream either way
      const [, stream, claim] = m;
      const s = readStream(stream); // null for a deleted stream and for an unreadable one: both are gone
      if (!s || s.status === "done" || s.status === "parked") return false;
      if (claim !== (s.held_at ?? "unheld")) return false; // superseded claim
      return openEscalations(stream).length > 0;
    });
    if (keep.length !== state.orphaned.length) {
      state.orphaned = keep;
      writeDaemonState(state);
    }
  } catch {}
}

// Each poll: any stream with an open escalation and no live session pages the owner once.
export function sweepOrphans() {
  const paged = [];
  for (const s of listStreams(Date.now())) {
    if (s.state === "corrupt" || s.status === "done" || s.status === "parked") continue;
    try {
      if (streamOrphaned(s.name).orphaned && orphanPage(s.name)) paged.push(s.name);
    } catch {}
  }
  pruneOrphanLedger();
  return paged;
}

const sub = (args) => {
  try {
    const r = spawnSync(process.execPath, [SELF_BIN, ...args], { encoding: "utf8" });
    return { status: r.status, out: String(r.stdout ?? ""), err: String(r.stderr ?? "") };
  } catch (e) {
    return { status: 2, out: "", err: e.message };
  }
};
// node is implied: the printed resume line starts with `node <oc-worker> ...`; tokens after it are argv.
const tokenize = (cmd) => (cmd.match(/"([^"]*)"|\S+/g) ?? []).map((t) => t.replace(/^"|"$/g, ""));
const detached = (cmd, args) => {
  const child = spawn(cmd, args, { detached: process.platform !== "win32", stdio: "ignore", windowsHide: true });
  child.unref();
  return child.pid;
};

// ---------------------------------------------------------------- step

// `<run>` is everything between the markers, so a `<ticket>/<run>` id comes back whole (greedy: the last marker wins).
const RUN_KEY_RE = /^(?:run:(.+):(?:queued|done|dead)|verdict:(.+))$/;

const eventsOf = (name) => new Map(readEvents(name).map((e) => [e.key, e]));
// readStream validates the name itself (handoff.mjs checkName); a bad name is "no such stream", not a crash.
const streamExists = (name) => {
  try {
    return Boolean(readStream(name));
  } catch {
    return false;
  }
};
const runOfKey = (key) => {
  const m = RUN_KEY_RE.exec(key);
  return m ? m[1] ?? m[2] : null;
};

// ticket.json = dirname(out)/ticket.json, written once by /frood-orchestrator before the first dispatch.
function readTicket(file) {
  try {
    const t = JSON.parse(fs.readFileSync(file, "utf8"));
    return t && typeof t === "object" && !Array.isArray(t) ? t : null;
  } catch {
    return null;
  }
}

// Round = 1 + the resumes this ticket has already had (derived, never stored). Only acks tagged with this
// ticket's slug count, so a resume recorded for another ticket in the same stream never inflates the round (N1).
function roundOf(lines, slug) {
  return (
    1 +
    lines.filter((l) => !l.resolved && typeof l.action === "string" && l.action.startsWith("ACTION resume-worker") && slug && l.ticket === slug).length
  );
}

// The ticket a run was dispatched under: the `ticket` string of dirname(out)/ticket.json, else the directory's
// basename — the same derivation oc-worker.mjs uses for its run id. Pure file read: step runs no git.
const ticketIdOf = (out) => {
  const dir = path.dirname(path.resolve(out));
  try {
    const t = JSON.parse(fs.readFileSync(path.join(dir, "ticket.json"), "utf8"));
    if (t && typeof t === "object" && typeof t.ticket === "string" && t.ticket) return t.ticket;
  } catch {
    // no usable ticket.json: the directory basename still names the ticket
  }
  return path.basename(dir);
};
const runIdOf = (out) => `${ticketIdOf(out)}/${path.basename(out, path.extname(out))}`;

// The id of the run a resume will start: keep the `<ticket>/` prefix of the current id and raise the round.
// A legacy un-prefixed id (`worker-r1`) has no prefix, so its resume keeps the legacy shape.
function nextRunId(run, round) {
  const cut = run.lastIndexOf("/");
  const prefix = cut === -1 ? "" : run.slice(0, cut + 1);
  return `${prefix}worker-r${round + 1}`;
}

// M2: replay only what has not happened yet. The effect is read from the files, never from the action's wording alone.
function effectPresent(key, action, events, lines) {
  if (action.startsWith("ACTION critic")) {
    const run = runOfKey(key);
    if (run && events.has(`verdict:${run}`)) return true;
    // Daemon verdicts key on the critic run, not the worker run: match by the findings path instead.
    const m = /^ACTION critic \S+ \S+ (\S+) \d+$/.exec(action);
    if (m) {
      for (const [, e] of events) {
        if (e.kind === "verdict" && typeof e.findings === "string" && baseFindings(e.findings) === m[1]) return true;
      }
    }
    return false;
  }
  if (action.startsWith("ACTION resume-worker")) {
    // The out path is everything between ` --out ` and the LAST ` --session ` (greedy): a path that itself contains
    // ` --` still resolves, and no flag after --session can cut it short.
    const m = /--out ([\s\S]+) --session /.exec(action);
    if (!m) return false;
    const out = m[1];
    const legacy = path.basename(out, path.extname(out)); // an ack written before run ids gained the ticket prefix
    return events.has(`run:${runIdOf(out)}:queued`) || events.has(`run:${legacy}:queued`);
  }
  if (action.startsWith("ESCALATE")) return lines.some((l) => l.key === key && l.resolved);
  return false;
}

// The next out of a resume must be fresh: worker-r<N+1>.md, its receipt, or a queued event for it (B4).
// The out path is what the desk must see (a taken out needs a fresh name), whichever of the three exists. The queued
// event is looked up under the prefixed id the resume will actually produce.
function nextOutTaken(runDir, round, events, run) {
  const out = path.join(runDir, `worker-r${round + 1}.md`);
  return fs.existsSync(out) || fs.existsSync(out + ".receipt.json") || events.has(`run:${nextRunId(run, round)}:queued`) ? out : null;
}

// The worker run a critic reviewed: the ACTION critic ack whose findings path matches carries the
// worker run-done key. Null when the critic was launched outside the step flow (a direct oc-worker
// run records no ACTION) — then nobody wrote down what it reviewed.
// A critic-alt retry writes `findings-r<N>-alt.md` for the `ACTION critic … findings-r<N>.md` it stands in for.
const baseFindings = (f) => (typeof f === "string" ? f.replace(/-alt\.md$/, ".md") : f);

function criticReviewedRun(lines, events, slug, findings) {
  for (const l of lines) {
    if (l.ticket !== slug) continue;
    const m = /^ACTION critic \S+ \S+ (\S+) \d+$/.exec(l.action ?? "");
    if (!m || m[1] !== baseFindings(findings)) continue;
    const run = runOfKey(l.key);
    if (run && (events.get(`run:${run}:done`)?.agent ?? "").startsWith("worker")) return run;
  }
  return null;
}

// One decision line for one event. Pure: reads the stream files and ticket.json only; the caller acks it.
export function decideStep(stream, key, events, lines) {
  const run = runOfKey(key);
  if (!run) return { action: `ESCALATE unknown-event ${key}`, ticket: "" };
  const ev = events.get(key);
  const queued = events.get(`run:${run}:queued`) ?? null;
  const done = events.get(`run:${run}:done`) ?? null;
  const ticketPath = queued?.ticket ?? null;
  const ticket = ticketPath ? readTicket(ticketPath) : null;
  const slug = typeof ticket?.ticket === "string" ? ticket.ticket : "";
  if (!ticket?.mandate) return { action: `ESCALATE no-ticket ${ticketPath ?? key}`, ticket: slug };

  const runDir = path.dirname(ticket.mandate);
  const out = ev.out ?? done?.out ?? queued?.out ?? "";
  const round = roundOf(lines, slug);
  const max = Number.isInteger(ticket.max_rounds) ? ticket.max_rounds : ROUND_CAP;
  const findings = ev.findings ?? path.join(runDir, `findings-r${round}.md`);

  if (ev.kind === "run-done") {
    const agent = ev.agent ?? "";
    if (!agent.startsWith("worker")) return { action: `ESCALATE agent-${agent} ${out}`, ticket: slug };
    if (ev.outcome === "done") return { action: `ACTION critic ${ticketPath} ${out} ${path.join(runDir, `findings-r${round}.md`)} ${round}`, ticket: slug };
    if (ev.outcome === "blocked_question") return { action: `ESCALATE question ${out}`, ticket: slug };
    // Worker errored: try auto-resume on the next round before paging the owner.
    // A run that timed out or dropped (worker-nvidia or worker-free) resumes on the
    // same worker role with `--role worker --session` — oc-worker's Nvidia drop rule
    // handles repeated Nvidia stalls (2 stalled/timeout receipts leave worker-nvidia
    // out). Paid workers and runs without a session are escalated with their
    // original outcome; paid-worker errors keep escalating as today.
    const m = run.match(/worker-r(\d+)$/);
    const workerRound = m ? Number(m[1]) : round;
    const wagent = ev.agent;
    const wsession = done?.session ?? null;
    let canResume = false;
    if ((wagent === "worker-nvidia" || wagent === "worker-free") && wsession) canResume = true;
    if (canResume) {
      let nr = workerRound;
      while (nr < max && nextOutTaken(runDir, nr, events, run)) nr++;
      if (nr < max && !nextOutTaken(runDir, nr, events, run)) {
        // nextOutTaken(nr) checks worker-r<nr+1>.md, so the fresh slot is r<nr+1> (never the timed-out run's own out).
        // The prompt is the Mandate: it always exists, and step stays pure (an interactive desk runs this verbatim).
        const next = path.join(runDir, `worker-r${nr + 1}.md`);
        const prompt = ticket.mandate;
        const cmd = `node ${OC_WORKER} --role worker --dir ${ticket.worktree} --prompt ${prompt} --report ${ticket.report} --out ${next} --session ${wsession} --stream ${stream}`;
        return { action: `ACTION resume-worker ${cmd}`, ticket: slug };
      }
    }
    return { action: `ESCALATE worker-${ev.outcome ?? "unknown"} ${out}`, ticket: slug };
  }
  if (ev.kind === "run-dead") return { action: `ESCALATE run-dead ${out}`, ticket: slug };
  if (ev.kind === "verdict") {
    const session = done?.session ?? null;
    if (ev.effective === "CHANGES_REQUESTED") {
      // The resume always targets the reviewed WORKER run, never the critic: a verdict may key on
      // either (daemon verdicts key on the critic run, sessions and step tests on the worker run).
      let wrun = run;
      let wdone = done;
      if ((wdone?.agent ?? "") && !wdone.agent.startsWith("worker")) {
        wrun = null;
        const linked = criticReviewedRun(lines, events, slug, findings);
        if (linked) {
          wrun = linked;
          wdone = events.get(`run:${linked}:done`) ?? null;
        }
      }
      const wsession = wdone?.session ?? null;
      if (wrun && wsession && (wdone?.agent ?? "").startsWith("worker")) {
        // The next out must be fresh (B4) — but a taken slot is the desk's problem, not the
        // owner's: direct dispatches consume worker-r<N> names outside the resume flow, so
        // advance to the next free slot instead of paging. Only truly out of rounds pages.
        // Revision rounds stay on the same agent and the same session (--session);
        // switch to the next stronger pool only after 2 rounds on one model. No
        // hand-typed --fallback: oc-worker --role expands the chain from CHAINS and
        // applies the Nvidia drop rule. Same session keeps the worker's context.
        // (Free agents code round 1; a drop is resumed via --role worker above.)
        let agent = wdone.agent;
        let r = round;
        while (r < max && nextOutTaken(runDir, r, events, wrun)) r++;
        if (r < max && !nextOutTaken(runDir, r, events, wrun)) {
          const next = path.join(runDir, `worker-r${r + 1}.md`);
          const cmd = `node ${OC_WORKER} --agent ${agent} --dir ${ticket.worktree} --prompt ${findings} --report ${ticket.report} --out ${next} --session ${wsession} --stream ${stream}`;
          return { action: `ACTION resume-worker ${cmd}`, ticket: slug };
        }
        return { action: `ESCALATE rounds-exhausted ${findings}`, ticket: slug };
      }
      if (!wrun) return { action: `ESCALATE review-unlinked ${findings} (critic run outside the step flow: say which worker run it reviewed)`, ticket: slug };
      if (!wsession) return { action: `ESCALATE no-session ${out}`, ticket: slug };
    }
    if (ev.effective === "APPROVED_FREE") {
      // D1: free review -> owner signoff, never merge
      return { action: `ESCALATE owner-signoff ${findings} (free review: ${ev.reviewed_sha ?? "unknown"})`, ticket: slug };
    }
    if (ev.effective === "APPROVED") {
      if (ev.senior || ticket.senior_trigger || round > 2) return { action: `ESCALATE senior ${findings}`, ticket: slug };
      return { action: `ESCALATE merge ${ticketPath} ${ev.reviewed_sha ?? ""}`.trimEnd(), ticket: slug };
    }
    return { action: `ESCALATE critic-invalid ${findings}`, ticket: slug };
  }
  return { action: `ESCALATE unknown-event ${key}`, ticket: slug };
}

// A closed ticket is a merged one: its worktree was removed after the merge (an orphan directory may remain), so the
// worktree has no `.git` entry. Pure file check — step still runs no git. Returns the ticket, or null while it is open.
function closedTicket(events, run) {
  const file = events.get(`run:${run}:queued`)?.ticket ?? null;
  const ticket = file ? readTicket(file) : null;
  if (!ticket || typeof ticket.worktree !== "string" || !ticket.worktree) return null;
  return fs.existsSync(path.join(ticket.worktree, ".git")) ? null : ticket;
}

const STALE = "STALE ticket-closed";

const AGENT_RE = /^[a-z0-9][a-z0-9-]{0,40}$/;
function resolvedModel(agent, raw) {
  if (!raw || raw === "(agent default)") {
    return (isStr(agent) && AGENT_RE.test(agent) ? agentModel(agent) : null) || null;
  }
  return raw;
}
function criticFreeFromReceipt(receiptPath) {
  try {
    const receipt = JSON.parse(fs.readFileSync(receiptPath, "utf8"));
    const agent = isStr(receipt.agent) ? receipt.agent : "";
    const rawModel = isStr(receipt.model) ? receipt.model : null;
    const model = resolvedModel(agent, rawModel);
    if (/-free$/.test(agent)) return { free: true, model, free_source: `agent:${agent}` };
    if (!model) return { free: true, model: rawModel, free_source: "unknown" };
    const free = (model.startsWith("opencode/") && model.endsWith("-free")) || isPolicyFree(model);
    return { free, model, free_source: `model:${model}` };
  } catch (e) {
    if (e.code === "ENOENT") return { free: false, model: null, free_source: "no-receipt" }; // no receipt => paid (legacy default)
    return { free: true, model: null, free_source: "unreadable" }; // fail closed: unreadable => free
  }
}

// step is idempotent: the decision line is written once (as the ack); replays see the effect, not the wording.
function cmdStep(opts) {
  const [stream, key] = opts.args ?? [];
  if (!stream || !key) {
    console.error("usage: desk.mjs step <stream> <key>");
    return 2;
  }
  if (opts.by !== undefined && !BY.has(opts.by)) {
    console.error(`desk: --by must be cc or oc\n${usage()}`);
    return 2;
  }
  if (!streamExists(stream)) {
    console.error(`desk: no stream ${stream}`);
    return 2;
  }
  // The other harness holds the stream: not this desk's to decide. Nothing is acked, so the event returns after a handback.
  const holder = opts.by ? readStream(stream)?.held_by : null;
  if (holder && holder !== opts.by) {
    console.log(`HELD ${stream} ${holder}`);
    return 0;
  }
  const events = eventsOf(stream);
  if (!events.has(key)) {
    console.error(`desk: no event ${key} in stream ${stream}`);
    return 2;
  }
  const run = runOfKey(key);
  const kind = events.get(key).kind;
  const lines = readAckLines(stream);
  // Replay check first: if there's already a resolved ack for this key, the action is complete -> DONE
  const resolvedAck = lines.find((l) => l.key === key && l.resolved);
  if (resolvedAck) {
    console.log(`DONE ${key}`);
    return 0;
  }
  // If there's an unresolved decision, check if its effect is present
  const decided = lines.find((l) => l.key === key && !l.resolved);
  if (decided) {
    const action = decided.action ?? "";
    console.log(effectPresent(key, action, events, lines) ? `DONE ${key}` : action.replace(/\\/g, "/"));
    return 0;
  }
  // A stale event of a merged ticket is DONE, never replayed: a stream that still holds T3's `run:worker-r1:done` must
  // not make a fresh /frood-desk print `ACTION critic` for a ticket merged long ago. The acks are written once (appendAck
  // dedupes), so a replay takes this same branch and prints DONE again.
  if (run && (kind === "run-done" || kind === "run-dead" || kind === "verdict")) {
    const closed = closedTicket(events, run);
    if (closed) {
      const slug = typeof closed.ticket === "string" ? closed.ticket : "";
      // D2: if a run-done for a closed ticket has no verdict event, it was merged without review
      // Only escalate once per ticket (first time we see the closed ticket)
      if (kind === "run-done" && !events.has(`verdict:${run}`)) {
        // Check if we already escalated unreviewed-merge for this ticket (any run)
        const alreadyEscalated = lines.some((l) => l.ticket === slug && l.action?.startsWith("ESCALATE unreviewed-merge"));
        if (!alreadyEscalated) {
          const line = `ESCALATE unreviewed-merge ${slug}`;
          try {
            appendAck(stream, key, line, { ticket: slug, resolved: true });
          } catch (e) {
            console.error(`desk: cannot ack ${key}: ${e.message}`);
            return 2;
          }
          console.log(line);
          return 0;
        }
        // Already escalated for this ticket -> treat as stale
      }
      try {
        appendAck(stream, key, STALE, { ticket: slug });
        appendAck(stream, key, STALE, { resolved: true, ticket: slug });
      } catch (e) {
        console.error(`desk: cannot ack ${key}: ${e.message}`);
        return 2;
      }
      console.log(`DONE ${key}`);
      return 0;
    }
  }
  const { action, ticket } = decideStep(stream, key, events, lines);
  const line = action.replace(/\\/g, "/"); // forward slashes everywhere: the line is copy-pasted across harnesses
  try {
    appendAck(stream, key, line, { ticket }); // the ack stores exactly the printed line
  } catch (e) {
    console.error(`desk: cannot ack ${key}: ${e.message}`);
    return 2;
  }
  console.log(line);
  return 0;
}

// ---------------------------------------------------------------- verdict and merge-check (the only git here)

const git = (dir, args) => execFileSync("git", ["-C", dir, ...args], { encoding: "utf8" });

// The ticket a run was dispatched under (the `ticket` field of its queued event), or null.
// The ticket a run was dispatched under — or exactly why it is unusable (never queued
// with one, unreadable file, missing worktree). Callers print the error verbatim so the
// escalation names the fix instead of "no ticket".
function ticketOrProblem(events, stream, run) {
  const qev = events.get(`run:${run}:queued`);
  if (!qev?.ticket) return { error: `desk: run ${run} was never queued with a ticket in stream ${stream} (re-dispatch it with ticket.json)` };
  const ticket = readTicket(qev.ticket);
  if (!ticket) return { error: `desk: unreadable ticket ${qev.ticket} for ${run} in stream ${stream}` };
  if (!ticket.worktree) return { error: `desk: ticket ${qev.ticket} for ${run} lacks worktree (add "worktree" or re-dispatch)` };
  return { ticket };
}

// The critic's claim is advice; verdict-gate's gate() is the decision. The CC critic is Sonnet (paid): free: false.
function cmdVerdict(opts) {
  const [stream, run] = opts.args ?? [];
  const findings = opts.findings;
  if (!stream || !run || !findings) {
    console.error("usage: desk.mjs verdict <stream> <worker-run> --findings <path>");
    return 2;
  }
  if (!streamExists(stream)) {
    console.error(`desk: no stream ${stream}`);
    return 2;
  }
  const events = eventsOf(stream);
  if (!events.has(`run:${run}:queued`) && !events.has(`run:${run}:done`)) {
    console.error(`desk: no run ${run} in stream ${stream}`);
    return 2;
  }
  let text;
  try {
    text = fs.readFileSync(findings, "utf8");
  } catch {
    console.error(`desk: cannot read findings ${findings}`);
    return 2;
  }
  const { ticket, error } = ticketOrProblem(events, stream, run);
  if (error) {
    console.error(error);
    return 2;
  }
  let sha;
  try {
    sha = git(ticket.worktree, ["rev-parse", "HEAD"]).trim();
  } catch (e) {
    console.error(`desk: git rev-parse failed in ${ticket.worktree}: ${(e.stderr || e.message).toString().trim()}`);
    return 2;
  }
  // D1: determine free-ness from the critic's receipt (fail closed: unreadable => free)
  const receiptPath = `${findings}.receipt.json`;
  const { free } = criticFreeFromReceipt(receiptPath);
  const result = gate(text, { free });
  const senior = /^\s*SENIOR_REVIEW:\s*needed\b/m.test(text);
  try {
    appendEvent(stream, { key: `verdict:${run}`, kind: "verdict", run, effective: result.effective, senior, findings: path.resolve(findings), reviewed_sha: sha });
  } catch (e) {
    console.error(`desk: cannot append verdict for ${run}: ${e.message}`);
    return 2;
  }
  // The critic's run-done is handled by this verdict: resolved-ack it so it leaves `unhandled` (the gate and the
  // trigger converge to zero on a fully processed stream). Best effort: the verdict event is the record that matters.
  try {
    appendAck(stream, `run:${run}:done`, `verdict:${run}`, { resolved: true, ticket: ticket?.ticket });
  } catch (e) {
    console.error(`desk: cannot ack run-done for ${run}: ${e.message}`);
  }
  console.log(`KEY verdict:${run}`);
  return 0;
}

// ff is only possible when base is an ancestor of HEAD; a moved base is a train's job, not the desk's.
function isAncestor(dir, base) {
  try {
    execFileSync("git", ["-C", dir, "merge-base", "--is-ancestor", base, "HEAD"], { stdio: "ignore" });
    return true;
  } catch (e) {
    if (e.status === 1) return false;
    throw e;
  }
}

function cmdMergeCheck(opts) {
  const [stream, run] = opts.args ?? [];
  if (!stream || !run) {
    console.error("usage: desk.mjs merge-check <stream> <worker-run>");
    return 2;
  }
  if (!streamExists(stream)) {
    console.error(`desk: no stream ${stream}`);
    return 2;
  }
  const events = eventsOf(stream);
  const verdict = events.get(`verdict:${run}`);
  if (!events.has(`run:${run}:queued`) && !events.has(`run:${run}:done`) && !verdict) {
    console.error(`desk: no run ${run} in stream ${stream}`);
    return 2;
  }
  const { ticket, error } = ticketOrProblem(events, stream, run);
  if (error) {
    console.error(error);
    return 2;
  }
  if (!ticket.base) {
    console.error(`desk: ticket ${events.get(`run:${run}:queued`).ticket} for ${run} lacks base (add "base" or re-dispatch)`);
    return 2;
  }
  const fail = (check) => {
    console.log(`FAIL ${check}`);
    return 1;
  };
  // No verdict for the run means nobody approved it; that is checked before git so a pending review reads
  // `FAIL not-approved`, exactly as the design says (the git checks would otherwise report head-moved).
  if (!verdict) return fail("not-approved");
  try {
    if (git(ticket.worktree, ["status", "--porcelain"]).trim()) return fail("dirty");
    const head = git(ticket.worktree, ["rev-parse", "HEAD"]).trim();
    if (head !== verdict.reviewed_sha) return fail("head-moved");
    if (!isAncestor(ticket.worktree, ticket.base)) return fail("not-ff");
  } catch (e) {
    console.error(`desk: git failed in ${ticket.worktree}: ${(e.stderr || e.message).toString().trim()}`);
    return 2;
  }
  if (verdict.effective !== "APPROVED") return fail("not-approved");
  console.log("OK");
  return 0;
}

// One EVENT line through the interactive flow, executed: returns what happened for the log/tests.
export async function handleEvent(stream, key, by) {
  const state = readDaemonState();
  let events;
  try {
    events = eventsOf(stream);
  } catch (e) {
    return { stream, key, line: "", outcome: "error", detail: e.message };
  }
  const ev = events.get(key);
  // A finished critic run is not stepped (step would ESCALATE agent-critic): it is verdicted, like a session does.
  if (ev?.kind === "run-done" && (ev.agent ?? "").startsWith("critic")) return await verdictFlow(stream, key, state);
  const r = sub(["step", stream, key, ...(by ? ["--by", by] : [])]);
  const line = r.out.split(/\r?\n/).filter(Boolean)[0] ?? "";
  if (r.status !== 0 || !line) {
    // `errors` is stream-scoped like the ledger: a bare key let stream A's step failures page stream B, whose
    // identical event never failed (every stream's first run is `worker-r1`).
    const errId = wakeId(stream, key);
    state.errors[errId] = (state.errors[errId] ?? 0) + 1;
    writeDaemonState(state);
    if (state.errors[errId] > 3 && !wasPaged(state, stream, key)) {
      dpage(stream, key, `step-failed ${r.err.trim().split(/\r?\n/)[0] ?? "no output"}`);
      return { stream, key, line, outcome: "paged" };
    }
    return { stream, key, line, outcome: "error", detail: r.err };
  }
  if (line.startsWith("DONE ") || line === "DONE" || line.startsWith("HELD ")) return { stream, key, line, outcome: "noop" };
  if (wasPaged(state, stream, key)) return { stream, key, line, outcome: "paged" }; // this stream already escalated it: never re-page
  const out = await actOn(stream, key, events, line);
  wakeHolder(stream, key, line, out);
  return out;
}

// The stored decision, executed. Split from handleEvent so the completion wake-up below runs on
// every branch (critic, resume, merge, escalation) instead of being duplicated per call site.
async function actOn(stream, key, events, line) {
  let m = /^ACTION critic (\S+) (\S+) (\S+) (\d+)$/.exec(line);
  if (m) return await doCritic(stream, key, events, m[1], m[2], m[3], Number(m[4]));
  m = /^ACTION resume-worker (.+)$/.exec(line);
  if (m) return await doResume(stream, key, events, m[1]);
  m = /^ESCALATE merge (\S+) ?(\S*)$/.exec(line);
  if (m) return doMerge(stream, key, m[1], m[2]);
  dpage(stream, key, line);
  return { stream, key, line, outcome: "paged" };
}

// A ticket that reaches a terminal state the owner should hear about wakes the stream's holding
// session through the same peer-mail an escalation uses, so that session reports the outcome and the
// owner never has to watch `desk.mjs status` for a merge. The keys are exactly `ESCALATE merge`,
// `ESCALATE senior` and `ESCALATE owner-signoff`: the ticket is done, or it needs only a decision.
// Everything else stays quiet — `ACTION resume-worker`, critic dispatches and retries are the loop
// working, not news the owner should be woken for.
//
// Once-only is the one ledger in state.json, shared with dpage and keyed by stream+event (`pagedIds`/
// `paged`). `ESCALATE senior` / `ESCALATE owner-signoff` never reach this function: `actOn` sends every
// other `ESCALATE` through dpage and returns `outcome: "paged"`, and the outcome gate below returns on
// that before the ledger — that gate, not this guard, is what keeps those two to one mail per event.
// What this adds is the wake-up on `ESCALATE merge`, whose daemon path never goes through dpage — the
// quiet success that left the owner doing the desk's watching. Called after the decision is executed, so
// a merge the daemon made itself is reported as done rather than as pending.
//
// Two deliberate limits:
//   - Held streams only. A stream no session holds keeps its pre-existing behaviour here (nothing is
//     sent for merge/senior/owner-signoff), because the Mandate leaves the notify-send fallback
//     untouched and this wake-up exists to reach a *session*, not the desktop. dpage already pages
//     the desktop for the paths it owns.
//   - No durable write during a rehearsal (ORCH_DAEMON_DRY_RUN=1). A `paged` entry written there
//     would make the next live poll skip the key outright — handleEvent returns early on `paged`, so
//     the real run would neither merge nor mail, and a rehearsal would have consumed the ticket. The
//     mail still goes out (a dry run shows the owner exactly what they would receive), so the
//     once-only guard for that case is the in-process `wokenThisProcess` set: no file, nothing a live
//     run can see, and no mail on every poll.
//
// The durable entry is STREAM-SCOPED via `wakeId` (one identity shared with dpage). That identity is now a
// real coupling, not just a namespace: a `wakeHolder` mark for (stream, key) makes a later `handleEvent`
// for the same stream+key return `paged` before acting, and a later `dpage` for it silent (see the header).
// It remains safe because events are acked before either runs — the only thing the entry suppresses is a
// second report of one event, never a distinct event — and because the id carries the stream: run ids are
// not unique across streams (every stream names its first run `worker-r1`), so no stream's entry can
// stall or silence another stream's identical event. Step acks first, so a cross-stream match would be
// consumed with no effect; a stream-scoped id cannot match another stream's, so that cannot happen.
const COMPLETION_RE = /^ESCALATE (?:merge|senior|owner-signoff)\b/;
const wokenThisProcess = new Set(); // dry run only: this process's already-woken wakeIds

// Exported as the unit-test seam for the live/dry branches (like handleEvent/driveOnce): it takes no lock
// and sleeps nowhere, so a test can assert the ledger decision without driving a whole merge.
export function wakeHolder(stream, key, decision, result) {
  if (!COMPLETION_RE.test(decision ?? "")) return;
  // dpage already mailed this event (a merge-check/merge-train failure pages and returns `paged`): the
  // same key would otherwise be reported twice, once as the failure and once as "ready to merge".
  if (result?.outcome === "paged") return;
  const id = wakeId(stream, key);
  if (DAEMON_DRY()) {
    if (wokenThisProcess.has(id)) return; // rehearsal: once-only without a durable ledger
    wokenThisProcess.add(id);
  } else {
    const state = readDaemonState();
    if (wasPaged(state, stream, key)) return; // this stream already woke the holder for this event
    try {
      markPaged(state, stream, key, id);
      writeDaemonState(state);
    } catch (e) {
      console.error(`daemon: cannot record completion wake-up: ${e.message}`);
      return;
    }
  }
  // The body keeps dpage's shape (reason + Stream/Event/Resolve with): one session reads both.
  const run = runOfKey(key) ?? key;
  let reason;
  if (result?.outcome === "merged") {
    reason = `${result.line} by the desk — nothing left to do`; // doMerge's own words: `merged <sha>`
  } else if (decision.startsWith("ESCALATE merge")) {
    // `ESCALATE merge <ticket.json> <sha>`: the sha is the reviewed head, and it is what a merge acts on.
    const sha = decision.trim().split(/\s+/).pop() ?? "";
    reason = `${run} is approved and ready to merge${/^[0-9a-f]{7,64}$/.test(sha) ? ` at ${sha.slice(0, 12)}` : ""} — the desk has not merged it`;
  } else {
    reason = decision.replace(/^ESCALATE /, ""); // senior <findings> | owner-signoff <findings> (free review: …)
  }
  console.log(`daemon: waking the holder: ${reason} (${stream} ${key})`);
  // Held streams only: with no held_session this returns without a word, and it is the one page the
  // Mandate left alone (the desktop fallback stays dpage's, on the paths dpage owns).
  notifyHeldSession(stream, key, reason);
}

// A critic run-done with findings becomes a verdict event; a failed critic is retried once, then paged.
async function verdictFlow(stream, key, state) {
  const run = runOfKey(key);
  const events = eventsOf(stream);
  const ev = events.get(key) ?? {};
  const findings = ev.out ?? "";
  const verdictKey = `verdict:${run}`;
  if (events.has(verdictKey)) return { stream, key, line: verdictKey, outcome: "noop" };
  let text = null;
  try {
    text = fs.readFileSync(findings, "utf8");
  } catch {}
  if (typeof text === "string" && /^VERDICT:/m.test(text)) {
    if (DAEMON_DRY()) return { stream, key, line: `verdict ${run}`, outcome: "verdict" };
    const r = sub(["verdict", stream, run, "--findings", findings]);
    if (r.status !== 0) {
      dpage(stream, key, `verdict-failed ${r.err.trim().split(/\r?\n/)[0] ?? findings}`);
      return { stream, key, line: "", outcome: "paged" };
    }
    try {
      noteStream(stream, { next: `daemon: verdict recorded for ${run}` });
    } catch {}
    return { stream, key, line: (r.out.split(/\r?\n/).filter(Boolean)[0] ?? "").trim(), outcome: "verdict" };
  }
  // No usable findings: the critic failed. Retry once with critic-alt, then page.
  // The retry writes its own out, `findings-r<N>-alt.md`: under --stream oc-worker refuses a used out (exit 2) and a
  // run id that is already queued (exit 9), and the failed critic's run id is. An -alt run is never retried again.
  const queued = events.get(`run:${run}:queued`) ?? {};
  const ticket = queued.ticket ? readTicket(queued.ticket) : null;
  // Same stream scoping as the ledger: one stream's critic retry must not consume another stream's retry
  // for the same-named run, nor page it on the strength of this stream's failures.
  const retryId = wakeId(stream, key);
  const isAlt = /-alt\.md$/.test(findings);
  const alt = findings && !isAlt ? findings.replace(/\.md$/, "-alt.md") : null;
  // The retry is already running or done: its own run-done carries the outcome (a verdict, or critic-failed since an
  // -alt is never retried). This run-done is settled — ack it so it leaves `unhandled`, and never page it again.
  if (alt && ticket && (events.has(`run:${runIdOf(alt)}:queued`) || events.has(`run:${runIdOf(alt)}:done`))) {
    try {
      appendAck(stream, key, `retried as critic-alt ${alt}`, { resolved: true, ticket: ticket.ticket });
    } catch {}
    return { stream, key, line: "", outcome: "noop" };
  }
  if ((state.retries[retryId] ?? 0) < 1 && ticket?.worktree && alt) {
    state.retries[retryId] = (state.retries[retryId] ?? 0) + 1;
    writeDaemonState(state);
    if (DAEMON_DRY()) return { stream, key, line: "retry critic-alt", outcome: "critic-retry" };
    detached(process.execPath, [OC_WORKER, "--agent", "critic-alt", "--dir", ticket.worktree, "--prompt", promptFor(ticket, findings), "--out", alt, "--stream", stream]);
    if (!(await awaitQueued(stream, runIdOf(alt)))) {
      dpage(stream, key, `critic-spawn-failed ${alt} (critic-alt retry: no queued event in 30s — check oc-worker)`);
      return { stream, key, line: "", outcome: "paged" };
    }
    try {
      appendAck(stream, key, `retried as critic-alt ${alt}`, { resolved: true, ticket: ticket.ticket });
    } catch {}
    return { stream, key, line: "retry critic-alt", outcome: "critic-retry" };
  }
  dpage(stream, key, `critic-failed ${findings || "(no findings)"}`);
  return { stream, key, line: "", outcome: "paged" };
}

const promptFor = (ticket, findings) => {
  const runDir = path.dirname(ticket.mandate);
  const m = /findings-r(\d+)\.md$/.exec(path.basename(findings));
  return path.join(runDir, `critic-prompt-r${m ? m[1] : 1}.md`);
};

// The session's 6-line critic prompt, written the same way so a human can re-run it verbatim.
async function doCritic(stream, key, events, ticketPath, out, findings, round) {
  const ticket = readTicket(ticketPath);
  if (!ticket?.mandate || !ticket.worktree) {
    dpage(stream, key, `no-ticket ${ticketPath}`);
    return { stream, key, line: "", outcome: "paged" };
  }
  const crun = runIdOf(findings);
  if (events.has(`run:${crun}:queued`) || events.has(`run:${crun}:done`)) return { stream, key, line: "", outcome: "critic-inflight" };
  const runDir = path.dirname(ticket.mandate);
  const prompt = path.join(runDir, `critic-prompt-r${round}.md`);
  const lines = [`Mandate: ${ticket.mandate}`, `Worktree: ${ticket.worktree}`, `Base: ${ticket.base ?? ""}`, `Report: ${ticket.report ?? ""}`, `Round: ${round}`];
  if (round > 1) lines.push(`Previous findings: ${path.join(runDir, `findings-r${round - 1}.md`)}`);
  if (DAEMON_DRY()) return { stream, key, line: `critic r${round} -> ${findings}`, outcome: "critic" };
  try {
    fs.mkdirSync(runDir, { recursive: true });
    fs.writeFileSync(prompt, lines.join("\n") + "\n");
  } catch (e) {
    dpage(stream, key, `critic-prompt-failed ${e.message}`);
    return { stream, key, line: "", outcome: "paged" };
  }
  // --stream: oc-worker writes this run's `queued` and `run-done` events to the stream. Without it (a19c2e87 to
  // 2026-11-24) awaitQueued below never saw a queued event and paged critic-spawn-failed for a running critic, and the
  // finished critic's verdict never reached the desk.
  detached(process.execPath, [OC_WORKER, "--agent", "critic", "--fallback", "critic-alt,critic-go,critic-free,critic-nvidia", "--dir", ticket.worktree, "--prompt", prompt, "--out", findings, "--stream", stream]);
  const started = await awaitQueued(stream, crun);
  if (!started) {
    dpage(stream, key, `critic-spawn-failed ${findings} (no queued event in 30s — check oc-worker)`);
    return { stream, key, line: "", outcome: "paged" };
  }
  try {
    noteStream(stream, { next: `daemon: critic r${round} spawned for ${runOfKey(key)}` });
  } catch {}
  return { stream, key, line: `critic r${round}`, outcome: "critic" };
}

// A detached spawn is fire-and-forget (stdio ignored): a child that dies instantly
// (bad binary, dead pool, bad argv) leaves no trace. Confirm the run actually
// started by watching for its `queued` event; otherwise page instead of claiming success.
async function awaitQueued(stream, run, timeoutMs = Number(process.env.ORCH_AWAIT_QUEUED_MS) || 30000) {
  const end = Date.now() + timeoutMs;
  for (;;) {
    try {
      if (eventsOf(stream).has(`run:${run}:queued`)) return true;
    } catch {}
    if (Date.now() >= end) return false;
    await asleep(500);
  }
}

// The resume line is re-derived by step, so the daemon only spawns what is not already queued (no duplicates even
// when the ack replays before oc-worker writes its queued event).
async function doResume(stream, key, events, cmd) {
  const m = /--out ([\s\S]+) --session /.exec(cmd);
  let rrun = null;
  if (m) {
    rrun = runIdOf(m[1]);
    const legacy = path.basename(m[1], path.extname(m[1]));
    if (events.has(`run:${rrun}:queued`) || events.has(`run:${legacy}:queued`)) return { stream, key, line: "", outcome: "resume-inflight" };
  }
  if (DAEMON_DRY()) return { stream, key, line: cmd, outcome: "resume" };
  const tokens = tokenize(cmd);
  if (tokens[0] !== "node" || tokens.length < 2) {
    dpage(stream, key, `resume-unparseable ${cmd.slice(0, 120)}`);
    return { stream, key, line: "", outcome: "paged" };
  }
  detached(process.execPath, tokens.slice(1));
  if (rrun && !(await awaitQueued(stream, rrun))) {
    dpage(stream, key, `resume-spawn-failed ${rrun} (no queued event in 30s — check oc-worker)`);
    return { stream, key, line: "", outcome: "paged" };
  }
  try {
    noteStream(stream, { next: `daemon: resumed ${runOfKey(key)}` });
  } catch {}
  return { stream, key, line: cmd, outcome: "resume" };
}

// The merge path from frood-desk.md, executed: ff-only into the Frood repo, then install + check + wt-finish.
// Anything else (train repos, non-ff, a FAIL) pages the owner — the daemon never merges what a session would not.
function doMerge(stream, key, ticketPath, sha) {
  const run = runOfKey(key);
  if (DAEMON_DRY()) return { stream, key, line: `merge ${run}`, outcome: "merge" };
  const mc = sub(["merge-check", stream, run]);
  if (mc.status !== 0) {
    dpage(stream, key, `merge-check ${(mc.out.split(/\r?\n/).filter(Boolean)[0] ?? "FAIL").trim()} ${run}`);
    return { stream, key, line: "", outcome: "paged" };
  }
  const ticket = readTicket(ticketPath);
  if (!ticket || ticket.merge !== "ff" || path.resolve(ticket.repo ?? "") !== REPO_ROOT) {
    dpage(stream, key, `merge-train ${ticket?.branch ?? ticketPath} (${ticket?.repo ?? "unknown repo"})`);
    return { stream, key, line: "", outcome: "paged" };
  }
  const step2 = (cmd, args, what) => {
    const r = spawnSync(cmd, args, { encoding: "utf8" });
    if (r.status !== 0) {
      dpage(stream, key, `${what}-failed ${(String(r.stderr ?? r.stdout ?? "").trim().split(/\r?\n/)[0] ?? "").slice(0, 160)}`);
      return false;
    }
    return true;
  };
  if (!step2("git", ["-C", ticket.repo, "merge", "--ff-only", ticket.branch], "merge")) return { stream, key, line: "", outcome: "paged" };
  if (!step2(process.execPath, [path.join(REPO_ROOT, "bin", "install.mjs")], "install")) return { stream, key, line: "", outcome: "paged" };
  if (!step2(process.execPath, [path.join(REPO_ROOT, "bin", "install.mjs"), "--check"], "install-check")) return { stream, key, line: "", outcome: "paged" };
  if (!step2(process.execPath, [path.join(REPO_ROOT, "bin", "wt-finish.mjs"), ticket.worktree, "--delete-branch"], "wt-finish")) return { stream, key, line: "", outcome: "paged" };
  try {
    appendAck(stream, key, `merged ${sha}`, { resolved: true, ticket: ticket.ticket });
    noteStream(stream, { next: `daemon: merged ${ticket.branch} as ${sha}` });
  } catch {}
  return { stream, key, line: `merged ${sha}`, outcome: "merged" };
}

// One poll + act iteration. Pure driver for the daemon loop; also the unit-test seam (no lock, no sleep).
export async function driveOnce(ctx, opts = {}) {
  const handled = [];
  const lines = [];
  poll({ by: opts.by, interval: opts.interval ?? DEFAULT_INTERVAL_S, lastPoll: ctx.lastPoll ?? null, printed: ctx.printed ?? new Set(), out: (l) => lines.push(l), err: () => {} });
  ctx.lastPoll = Date.now();
  for (const line of lines) {
    const m = /^EVENT (\S+) (\S+) (\S+)/.exec(line);
    if (m) handled.push(await handleEvent(m[1], m[2], opts.by));
  }
  if (!opts.skipVerdicts) await sweepVerdicts(opts);
  sweepOrphans();
  return handled;
}

// Critic completions become verdicts without waiting for their own EVENT turn (their run-done is never stepped).
async function sweepVerdicts(opts = {}) {
  const state = readDaemonState();
  for (const s of listStreams(Date.now())) {
    if (s.status !== "active") continue;
    if (opts.by && s.held_by && s.held_by !== opts.by) continue;
    let events;
    try {
      events = eventsOf(s.name);
    } catch {
      continue;
    }
    for (const [k, ev] of events) {
      if (ev.kind !== "run-done" || !(ev.agent ?? "").startsWith("critic")) continue;
      const vkey = `verdict:${ev.run}`;
      if (!ev.run || events.has(vkey)) continue;
      await verdictFlow(s.name, k, state);
    }
  }
}

const asleep = (ms) => new Promise((r) => setTimeout(r, ms));

// The headless loop: hold the lock, drive events, release on fence/stop. Exits 0 when someone else owns the lock.
async function daemonRun(by, interval, token) {
  let stopping = false;
  process.on("SIGTERM", () => {
    stopping = true;
  });
  process.on("SIGINT", () => {
    stopping = true;
  });
  const ctx = { lastPoll: null, printed: new Set() };
  for (;;) {
    const owner = readOwner();
    if (!owner || owner.token !== token) return 0; // fenced: someone else owns the lock now
    writeOwner(token, nowMs(), by, { kind: "daemon", session: null, log: daemonLogFile() });
    try {
      await driveOnce(ctx, { by, interval });
    } catch (e) {
      console.error(`daemon: poll failed: ${e.message}`);
    }
    for (let i = 0; i < interval * 2 && !stopping; i++) await asleep(500);
    if (stopping) break;
  }
  try {
    if (readOwner()?.token === token) fs.rmSync(lockPath(), { recursive: true, force: true });
  } catch {}
  return 0;
}

// Escalations the owner has not resolved yet (resolved acks clear them from `status`).
function pendingEscalations() {
  let rows = [];
  try {
    rows = fs.readFileSync(daemonEscFile(), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  } catch {
    return [];
  }
  return rows.filter((e) => {
    try {
      return !readAckLines(e.stream).some((l) => l.key === e.key && l.resolved);
    } catch {
      return true;
    }
  });
}

async function cmdDaemon(opts) {
  const [sub2] = opts.args ?? [];
  if (opts.interval !== undefined && !(opts.interval > 0)) {
    console.error("desk: --interval must be a positive number of seconds");
    return 2;
  }
  if (opts.by !== undefined && !BY.has(opts.by)) {
    console.error(`desk: --by must be cc or oc`);
    return 2;
  }
  const interval = opts.interval ?? DEFAULT_INTERVAL_S;
  if (sub2 === "_run") {
    // Internal: the detached child. Takes the lock as a daemon and never returns until fenced or signalled.
    const got = await takeLock(interval, opts.takeover, opts.by, { kind: "daemon", session: null, log: daemonLogFile() });
    if (got.code) {
      console.error(got.msg);
      return got.code;
    }
    return daemonRun(opts.by, interval, got.token);
  }
  if (sub2 === "start") {
    fs.mkdirSync(daemonDir(), { recursive: true });
    const logFd = fs.openSync(daemonLogFile(), "a");
    const child = spawn(process.execPath, [SELF_BIN, "daemon", "_run", ...(opts.by ? ["--by", opts.by] : []), "--interval", String(interval), ...(opts.takeover ? ["--takeover"] : [])], {
      detached: process.platform !== "win32",
      stdio: ["ignore", logFd, logFd],
      windowsHide: true,
    });
    child.unref();
    let code = null;
    child.once("exit", (c) => {
      code = c;
    });
    const logTail = () => {
      try {
        return fs.readFileSync(daemonLogFile(), "utf8").trim().split(/\r?\n/).slice(-5).join("\n");
      } catch {
        return "";
      }
    };
    const end = Date.now() + 10000;
    for (;;) {
      const owner = readOwner();
      if (owner?.pid === child.pid) {
        console.log(`daemon started pid=${child.pid} log=${daemonLogFile()}`);
        return 0;
      }
      if (code !== null) {
        const tail = logTail(); // the child names its reason in the log: surface it, don't make the operator hunt
        if (tail) console.error(tail);
        return code ?? 2;
      }
      try {
        process.kill(child.pid, 0);
      } catch {
        return 2; // child died before taking the lock: the log tail names the reason
      }
      if (Date.now() > end) {
        console.error(`desk: daemon did not take the lock in 10s (log: ${daemonLogFile()})`);
        return 2;
      }
      await asleep(200);
    }
  }
  if (sub2 === "stop") {
    const owner = readOwner();
    if (!owner) {
      console.log("daemon: not running (no lock)");
      return 0;
    }
    const live = runIsLive({ pid: owner.pid, pid_start: owner.pid_start ?? null });
    if ((owner.kind ?? "session") !== "daemon") {
      if (live) {
        console.error(`${lockHeldMsg(owner)} — not a daemon, refusing to stop`);
        return 3;
      }
      fs.rmSync(lockPath(), { recursive: true, force: true });
      console.log(`daemon: cleared stale session lock (pid ${owner.pid})`);
      return 0;
    }
    if (!live) {
      fs.rmSync(lockPath(), { recursive: true, force: true });
      console.log(`daemon: cleared dead daemon lock (pid ${owner.pid})`);
      return 0;
    }
    try {
      process.kill(owner.pid, "SIGTERM");
    } catch {
      fs.rmSync(lockPath(), { recursive: true, force: true });
      return 0;
    }
    const end = Date.now() + 15000;
    while (Date.now() < end) {
      const o = readOwner();
      if (!o || !runIsLive({ pid: owner.pid, pid_start: owner.pid_start ?? null })) {
        if (o?.token === owner.token) fs.rmSync(lockPath(), { recursive: true, force: true });
        console.log(`daemon: stopped pid ${owner.pid}`);
        return 0;
      }
      await asleep(300);
    }
    console.error(`daemon: pid ${owner.pid} did not exit in 15s`);
    return 1;
  }
  if (sub2 === "status") {
    const info = watchInfo();
    console.log(watchLine(info));
    const pending = pendingEscalations();
    console.log(pending.length ? `escalations pending: ${pending.length}` : "escalations pending: 0");
    for (const e of pending.slice(-5)) console.log(`  ${e.at} ${e.stream} ${e.key} ${e.reason}`);
    return 0;
  }
  console.error("usage: desk.mjs daemon start [--interval 30] [--by cc|oc] [--takeover] | daemon stop | daemon status");
  return 2;
}

// ---------------------------------------------------------------- models (orchestrator desk model availability)

// The Orchestration Desk role chain, in preference order (paid first, then free).
// Agent → model pins come from ~/.config/opencode/agents/<agent>.md frontmatter.
const DESK_CHAIN = [
  { agent: "orchestrator", tier: "paid (Go)" },
  { agent: "orchestrator-alt", tier: "paid (CmdC)" },
  { agent: "orchestrator-free", tier: "free (Zen)" },
];

// Free-only fallback models (Nvidia free-only provider, per providers.json allowlist).
// These are not pinned to desk agents but are available for the user to switch into
// when every desk-chain model is down. IDs must match the live `opencode models` catalog.
const FREE_FALLBACKS = [
  "nvidia/deepseek-ai/deepseek-v4.1-flash",
  "nvidia/openai/gpt-oss-20b",
  "nvidia/minimaxai/minimax-m3.1-flash",
  "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b",
];

function modelStatus(model) {
  if (!model) return { ok: false, text: "unpinned (no model in agent frontmatter)" };
  const down = isDown(model);
  if (down) return { ok: false, text: `DOWN (${down.reason}, until ${down.until})` };
  if (!modelAllowed(model)) return { ok: false, text: `BLOCKED (${policyReason(model)})` };
  return { ok: true, text: "available" };
}

function cmdModels() {
  let bestPaid = null;
  let bestFreeAgent = null;
  console.log("Orchestration Desk model availability:");
  for (const { agent, tier } of DESK_CHAIN) {
    const model = agentModel(agent);
    const st = modelStatus(model);
    const mark = st.ok ? "  " : "✗ ";
    console.log(`${mark}${agent} → ${model ?? "(unpinned)"} [${tier}]: ${st.text}`);
    if (st.ok) {
      if (tier.startsWith("paid") && !bestPaid) bestPaid = { agent, model };
      if (!bestFreeAgent) bestFreeAgent = { agent, model };
    }
  }

  // Graceful degradation: scan free fallback models (Nvidia etc.) when the desk chain is all down.
  console.log("");
  console.log("Free fallback models (degradation targets when desk chain is down):");
  let bestFreeModel = null;
  for (const model of FREE_FALLBACKS) {
    const st = modelStatus(model);
    const mark = st.ok ? "  " : "✗ ";
    console.log(`${mark}${model} [free (Nvidia)]: ${st.text}`);
    if (st.ok && !bestFreeModel) bestFreeModel = model;
  }

  console.log("");
  if (bestPaid) {
    console.log(`Recommendation: switch the Orchestration Desk agent to ${bestPaid.model} (${bestPaid.agent}) — first available paid model.`);
  } else if (bestFreeModel) {
    console.log(`Recommendation: all desk-chain models are down. Switch to ${bestFreeModel} (free Nvidia) for graceful degradation — tickets end READY — human/senior review required.`);
  } else if (bestFreeAgent) {
    console.log(`Recommendation: switch the Orchestration Desk agent to ${bestFreeAgent.model} (${bestFreeAgent.agent}) — first available free model (tickets end READY — human/senior review required).`);
  } else {
    console.log("No Orchestration Desk model is available right now — all pools are down. Wait for pool-health entries to expire, then rerun `desk models`. `bin/router-health.mjs --probe` re-checks whether a pinned model is back.");
  }
  return 0;
}

// ---------------------------------------------------------------- main

function parse(argv, { allowArgs = false } = {}) {
  const opts = {};
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--json") opts.json = true;
    else if (k === "--events") opts.events = true;
    else if (k === "--once") opts.once = true;
    else if (k === "--takeover") opts.takeover = true;
    else if (k === "--interval") opts.interval = Number(argv[++i]);
    else if (k === "--by") opts.by = argv[++i];
    else if (k === "--until-event") opts.untilEvent = Number(argv[++i]);
    else if (allowArgs && k === "--findings") opts.findings = argv[++i];
    else if (allowArgs && !k.startsWith("--")) (opts.args ??= []).push(k);
    else throw new Error(`unknown flag ${k}`);
  }
  return opts;
}

export async function main(argv) {
  const [cmd, ...rest] = argv;
  if (cmd === "--help" || cmd === "-h") {
    console.log(fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split(/\r?\n/).slice(1).filter((l) => l.startsWith("//")).map((l) => l.replace(/^\/\/ ?/, "")).join("\n"));
    return 0;
  }
  try {
    migrate(); // fold a legacy handoff.json into stream "default" (idempotent; a failure never fails a status)
  } catch (e) {
    console.error(`desk: migrate failed: ${e.message}`); // a broken legacy file must not take the desk down
  }
  const allowArgs = cmd === "step" || cmd === "verdict" || cmd === "merge-check" || cmd === "daemon";
  let opts;
  try {
    opts = parse(rest, { allowArgs });
  } catch (e) {
    console.error(`desk: ${e.message}`);
    return 2;
  }
  if (cmd === "status") return cmdStatus(opts);
  if (cmd === "models") return cmdModels(opts);
  if (cmd === "watch") return cmdWatch(opts);
  if (cmd === "daemon") return cmdDaemon(opts);
  if (cmd === "step") return cmdStep(opts);
  if (cmd === "verdict") return cmdVerdict(opts);
  if (cmd === "merge-check") return cmdMergeCheck(opts);
  console.error(usage());
  return 2;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2))
    .then((code) => process.exit(code))
    .catch((e) => {
      console.error(`desk: ${e.message}`);
      process.exit(2);
    });
}

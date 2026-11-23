#!/usr/bin/env node
// Module-boundary handoffs, one named stream per workstream: lets a fresh session (after /clear or a fresh tab)
// continue exactly where the last one stopped, and lets one /frood-desk session follow several workstreams at once.
//
//   node handoff.mjs write --stream <n> --plan <plan.md> --next "<next module / step>" [--done "<summary>"]
//                          [--waiting "<owner items>"] [--repo <dir>] [--status active|parked|done]
//                          [--written-by <id>]
//   node handoff.mjs note  --stream <n> [--next <t>] [--done <t>] [--waiting <t>]   (the desk's update)
//   node handoff.mjs show  [--stream <n>]    one stream as JSON, or the table of every stream
//   node handoff.mjs consume [--stream <n>] [--session <id>] [--takeover]
//                                            mark it consumed (called by /frood-next once the plan is loaded)
//   node handoff.mjs list  [--json]          prune finished streams, then print the table
//   node handoff.mjs ack   --stream <n> --key <k> [--action <line>] [--ticket <slug>] [--resolved]
//   node handoff.mjs done  --stream <n>      status done, done_at = now
//   node handoff.mjs claim --stream <n> --by <cc|oc> [--session <id>] [--takeover]   take the stream lease
//   node handoff.mjs release --stream <n> --by <cc|oc> [--to <cc|oc>]               give it up (optionally hand back)
//   write and note also take --by <cc|oc>: refused when the OTHER harness holds the lease.
//
// Exit codes: 0 ok, 1 no stream / parked / done, 2 usage or lock timeout, 3 held by the other harness,
//             4 claimed by a live session (only with --session; --takeover overrides).
//
// State lives in <ORCH_HOME || ~>/.config/orchestrator/streams/:
//   <name>.json         the pointer (plan, next, done, waiting, status, timestamps) — verbs here only
//   <name>.events.jsonl append-only events from oc-worker (queued/done) and the desk (dead, verdict)
//   <name>.acks.jsonl   append-only acks from the desk (one line per handled event key)
//   <name>.lease.jsonl  append-only takeover/handback audit lines (never in events: the desk would wake on them)
// The lease (held_by, held_session, held_at, taken_from, handback_to) lives on the pointer; the holder is the
// HARNESS (cc | oc), not a session id, because /clear gives a new session id every module.
// The session claim (claim: { session, at, taken_from }) also lives on the pointer, written only when `--session` is
// passed: /frood-next records it at step 3 and refreshes it at step 5, so two /frood-next runs the same day cannot both load the
// same stream. There is no pid and no heartbeat; the TTL is the liveness proxy (10 min, ORCH_CLAIM_TTL_MIN overrides,
// 0 = no enforcement). A claim older than the TTL is presumed dead and replaced (the expired session lands in
// `taken_from`, with a one-line note on stderr). Only a claim/consume re-run refreshes it — `note` (the desk) never
// does. `write`, `done` and `release` by the holder clear it. A missing or corrupt claim reads as no claim at all.
// The prose handoff still lives in the plan file itself under "## Handoff"; these files only say where to look.
// A stream written more than 72 h ago is stale (listed, never auto-resumed); parked and done are never watched.
// Everything here is synchronous; only proc-tree's killPid is async (taskkill on win32).
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { processStart } from "./proc-tree.mjs";

const STALE_MS = 72 * 3600_000;
const DONE_KEEP_MS = 14 * 24 * 3600_000;
const LOCK_WAIT_MS = 5000;
const LOCK_POLL_MS = 100;
const LOCK_AGE_MS = 30_000;
const NEXT_CUT = 80;
const CLAIM_TTL_MS = 10 * 60_000;
const NAME_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const STATUSES = ["active", "parked", "done"];
const HARNESSES = ["cc", "oc"];
const SESSION_RE = /^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$/;
const LEASE_KEYS = ["held_by", "held_session", "held_at", "taken_from", "handback_to"];
const CLAIM_KEYS = ["session", "at", "taken_from"];

// ---------------------------------------------------------------- paths

export function orchRoot() {
  return process.env.ORCH_HOME || os.homedir();
}

// The legacy single-handoff pointer (migrate() folds it into stream "default").
export function handoffPath() {
  return path.join(orchRoot(), ".config", "orchestrator", "handoff.json");
}

export function streamsDir() {
  return path.join(orchRoot(), ".config", "orchestrator", "streams");
}

const streamFile = (name) => path.join(streamsDir(), `${name}.json`);
const eventsFile = (name) => path.join(streamsDir(), `${name}.events.jsonl`);
const acksFile = (name) => path.join(streamsDir(), `${name}.acks.jsonl`);
const leaseFile = (name) => path.join(streamsDir(), `${name}.lease.jsonl`);
const lockDir = (name) => path.join(streamsDir(), `${name}.lock`);

function checkName(name) {
  if (typeof name !== "string" || !NAME_RE.test(name)) throw new Error(`bad stream name ${JSON.stringify(name)}`);
  return name;
}

// ---------------------------------------------------------------- sleeps, liveness, writes

// Synchronous 100 ms sleeps (the lock is synchronous by design: no callback may interleave with a read-modify-write).
const sleepCell = new Int32Array(new SharedArrayBuffer(4));
function sleepSync(ms) {
  Atomics.wait(sleepCell, 0, 0, ms);
}

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
}

let ownStart; // undefined = not looked up yet; null = lookup failed
const startCache = new Map();
function startFor(pid) {
  if (pid === process.pid) {
    if (ownStart === undefined) ownStart = processStart(pid);
    return ownStart;
  }
  if (!startCache.has(pid)) startCache.set(pid, processStart(pid));
  return startCache.get(pid);
}

// tmp + fsync, then rename, retrying the rename (Windows holds a file briefly after another process closes it).
export function atomicWrite(file, text) {
  fs.mkdirSync(path.dirname(file), { recursive: true });
  const tmp = `${file}.${process.pid}.${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}.tmp`;
  const fd = fs.openSync(tmp, "w");
  try {
    fs.writeFileSync(fd, text);
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  for (let attempt = 0; ; attempt++) {
    try {
      fs.renameSync(tmp, file);
      return;
    } catch (e) {
      if (!["EPERM", "EBUSY", "EACCES"].includes(e.code) || attempt >= 9) {
        try {
          fs.unlinkSync(tmp);
        } catch {}
        throw e;
      }
      sleepSync(50);
    }
  }
}

// ---------------------------------------------------------------- the stream lock

function readLockOwner(dir) {
  try {
    return JSON.parse(fs.readFileSync(path.join(dir, "owner"), "utf8"));
  } catch {
    return null;
  }
}

// Remove a lock only while it still belongs to the owner we judged stale (another waiter may have taken it already).
function dropLock(name, owner) {
  const dir = lockDir(name);
  try {
    const current = readLockOwner(dir);
    if (owner && (!current || current.pid !== owner.pid || current.at !== owner.at)) return false;
    if (!owner && current) return false;
    fs.rmSync(dir, { recursive: true, force: true });
    return true;
  } catch {
    return false;
  }
}

// true = the lock was reclaimed (the caller retries immediately); false = a live owner holds it.
function reclaimIfStale(name) {
  const dir = lockDir(name);
  const owner = readLockOwner(dir);
  if (!owner) {
    // The holder creates the directory, then writes `owner`. Only a directory that stays ownerless is a crashed holder.
    try {
      if (Date.now() - fs.statSync(dir).mtimeMs < 500) return false;
    } catch {
      return true; // it is gone already
    }
    return dropLock(name, null);
  }
  const age = Date.now() - Date.parse(owner.at);
  if (!(age <= LOCK_AGE_MS)) return dropLock(name, owner);
  if (!Number.isInteger(owner.pid) || !alive(owner.pid)) return dropLock(name, owner);
  if (owner.pid === process.pid) return dropLock(name, owner); // our own pid, but we are not inside the lock
  const current = startFor(owner.pid);
  if (current && owner.pid_start && current !== owner.pid_start) return dropLock(name, owner); // pid was recycled
  return false;
}

// Serialise every read-modify-write of one stream: mkdir is the atomic take, `owner` carries pid + start time so a
// dead or recycled owner is reclaimed instead of blocking forever. Throws `stream <name> is locked` after 5 s.
export function withStreamLock(name, fn) {
  checkName(name);
  fs.mkdirSync(streamsDir(), { recursive: true });
  const dir = lockDir(name);
  const deadline = Date.now() + LOCK_WAIT_MS;
  for (;;) {
    try {
      fs.mkdirSync(dir);
      break;
    } catch (e) {
      if (e.code !== "EEXIST") throw e;
      if (reclaimIfStale(name)) continue;
      if (Date.now() > deadline) throw new Error(`stream ${name} is locked`);
      sleepSync(LOCK_POLL_MS);
    }
  }
  const mine = { pid: process.pid, pid_start: startFor(process.pid), at: new Date().toISOString() };
  try {
    atomicWrite(path.join(dir, "owner"), JSON.stringify(mine));
    return fn();
  } finally {
    // Release only a lock that is still ours: if it was reclaimed while fn ran, the directory belongs to the new owner.
    try {
      const cur = readLockOwner(dir);
      if (cur && cur.pid === mine.pid && cur.at === mine.at && cur.pid_start === mine.pid_start) fs.rmSync(dir, { recursive: true, force: true });
    } catch {}
  }
}

// ---------------------------------------------------------------- stream pointers

function stateOf(s, now) {
  if (s.status === "parked") return "parked";
  if (s.status === "done") return "done";
  const written = Date.parse(s.written_at);
  if (!Number.isFinite(written) || now - written > STALE_MS) return "stale";
  return s.consumed_at ? "consumed" : "pending";
}

// The stream plus its derived `state`; null when the file is missing or unreadable (see listStreams for CORRUPT).
// `claim` is exposed as an additive field (null when absent or corrupt), so a reader that never heard of claims keeps
// reading the pointer it already knows.
export function readStream(name, now = Date.now()) {
  let raw;
  try {
    raw = fs.readFileSync(streamFile(checkName(name)), "utf8");
  } catch {
    return null;
  }
  try {
    const s = JSON.parse(raw);
    if (!s || typeof s !== "object" || Array.isArray(s)) return null;
    const lease = Object.fromEntries(LEASE_KEYS.map((k) => [k, s[k] ?? null]));
    return { ...s, ...lease, claim: claimOf(s.claim), state: stateOf(s, now) };
  } catch {
    return null;
  }
}

const TITLE_MAX = 60;
const baseName = (p) => String(p || "").replace(/[\\/]+$/, "").split(/[\\/]/).pop() || "";

/** Tab title for a stream, same shape as the CC hook's sessionTitle: `[<stream>] <repo>: <module> — <what>`, cut to 60. */
export function streamTitle(s) {
  if (!s || typeof s !== "object") return "";
  const repo = baseName(s.repo);
  const next = String(s.next || "").trim();
  const g = /^\/frood-gauntlet\s+(.*)$/.exec(next);
  let title;
  if (g) {
    const args = g[1].split(/\s+/);
    const rest = args.slice(2).join(" ").trim().replace(/^[—–-]+\s*/, "");
    const what = rest || baseName(args[0] || "").replace(/\.md$/i, "").replace(/^plan-/, "");
    title = `[${s.name}] ${repo ? `${repo}: ` : ""}${args[1] || ""} — ${what}`;
  } else if (next) {
    title = `[${s.name}] ${repo ? `${repo}: ` : ""}${next.replace(/^\/\S+\s*/, "")}`;
  } else {
    title = `[${s.name}] ${repo ? `${repo}: ` : ""}${s.name}`;
  }
  return title.length > TITLE_MAX ? title.slice(0, TITLE_MAX) : title;
}

// Every stream, sorted by name. A corrupt file is listed as {name, state: "corrupt"} so one bad file never hides the rest.
export function listStreams(now = Date.now()) {
  let files = [];
  try {
    files = fs.readdirSync(streamsDir());
  } catch {
    return [];
  }
  const out = [];
  for (const file of files) {
    const m = /^(.*)\.json$/.exec(file);
    if (!m || !NAME_RE.test(m[1])) continue;
    out.push(readStream(m[1], now) ?? { name: m[1], state: "corrupt" });
  }
  return out.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0));
}

const cut = (s, n) => (String(s ?? "").length > n ? String(s).slice(0, n) : String(s ?? ""));
const ageHours = (iso, now) => {
  const t = Date.parse(iso);
  return Number.isFinite(t) ? Math.max(0, Math.floor((now - t) / 3600_000)) : 0;
};

const heldLine = (name, s) => `stream ${name} held by ${s.held_by} (session ${s.held_session ?? "-"}) since ${s.held_at}`;

// An Error that main() turns into exit 3 (the stream is leased to the other harness).
function heldError(name, s) {
  const e = new Error(heldLine(name, s));
  e.exitCode = 3;
  return e;
}
const heldByOther = (cur, by) => Boolean(by && cur?.held_by && cur.held_by !== by);

// ---------------------------------------------------------------- the session claim

// TTL in ms: 10 min by default, ORCH_CLAIM_TTL_MIN overrides it. 0 turns enforcement off — with a zero TTL no claim
// is ever fresh, so every claim is replaced at once. An unreadable value falls back to the default (never to zero).
export function claimTtlMs() {
  const raw = process.env.ORCH_CLAIM_TTL_MIN;
  if (raw === undefined || !raw.trim()) return CLAIM_TTL_MS;
  const min = Number(raw);
  if (!Number.isFinite(min) || min < 0) return CLAIM_TTL_MS;
  return min * 60_000;
}

const atIso = (ms) => new Date(ms).toISOString();
// How long ago the claim was taken, or null when its `at` is unreadable.
function claimAge(claim, nowMs) {
  const t = Date.parse(claim?.at ?? "");
  return Number.isFinite(t) ? Math.max(0, nowMs - t) : null;
}
const fmtAge = (ms) => (ms < 60_000 ? `${Math.floor(ms / 1000)}s` : ms < 3600_000 ? `${Math.floor(ms / 60_000)}m` : `${Math.floor(ms / 3600_000)}h`);

// A missing, half-written or corrupt claim reads as no claim: one bad line must never wedge a stream.
function claimOf(v) {
  if (!v || typeof v !== "object" || Array.isArray(v) || typeof v.session !== "string" || !v.session) return null;
  return {
    session: v.session,
    at: typeof v.at === "string" && v.at ? v.at : null,
    taken_from: typeof v.taken_from === "string" && v.taken_from ? v.taken_from : null,
  };
}

const claimLine = (name, s, ageMs) => `stream ${name} claimed by session ${s} (${fmtAge(ageMs)} ago)`;
const claimExpiredLine = (name, s) =>
  s.ageMs === null
    ? `claim by session ${s.session} on stream ${name} had no readable at; replaced`
    : `claim by session ${s.session} on stream ${name} expired (${fmtAge(s.ageMs)} ago); replaced`;

// Decide the claim write for one claim/consume run. Rules (only ever reached with --session): no claim -> set it; the
// same session -> refresh `at` and keep taken_from; a live claim by another session -> exit 4 unless --takeover; a
// stale (or unreadable) claim -> replace it and say who expired. Returns {code:0, claim, expired?} or {code:4, msg}.
function resolveClaim(name, cur, session, nowMs, takeover) {
  const at = atIso(nowMs);
  if (!cur) return { code: 0, claim: { session, at, taken_from: null } };
  if (cur.session === session) return { code: 0, claim: { ...cur, at } }; // refresh: same session, any age
  const ageMs = claimAge(cur, nowMs);
  const live = ageMs !== null && ageMs < claimTtlMs();
  if (live && !takeover) return { code: 4, msg: `${claimLine(name, cur.session, ageMs)}; re-run with --takeover to take it over` };
  return { code: 0, claim: { session, at, taken_from: cur.session }, expired: live ? undefined : { session: cur.session, ageMs } };
}

// NAME  STATE  AGE  NEXT, with the stale hint on its own line under the table.
function formatTable(streams, now = Date.now()) {
  if (!streams.length) return "(no streams)";
  const rows = [["NAME", "STATE", "AGE", "NEXT"]];
  const extra = {};
  for (const s of streams) {
    if (s.state === "corrupt") rows.push([s.name, "CORRUPT", "", ""]);
    else rows.push([s.name, s.state, `${ageHours(s.written_at, now)}h`, cut(s.next, NEXT_CUT)]);
    // one indented extra line under the row keeps the four columns untouched
    if (s.state !== "corrupt" && s.held_by) extra[rows.length - 1] = `  held by ${s.held_by} (session ${s.held_session ?? "-"}) since ${s.held_at}`;
    else if (s.state !== "corrupt" && s.handback_to) extra[rows.length - 1] = `  handed back to ${s.handback_to}`;
  }
  const width = (i) => rows.reduce((w, r) => Math.max(w, String(r[i]).length), 0);
  const w = [width(0), width(1), width(2)];
  const lines = [];
  rows.forEach((r, i) => {
    lines.push([String(r[0]).padEnd(w[0]), String(r[1]).padEnd(w[1]), String(r[2]).padEnd(w[2]), String(r[3])].join("  ").trimEnd());
    if (extra[i]) lines.push(extra[i]);
  });
  for (const s of streams) {
    if (s.state === "stale") lines.push(`stale (written ${ageHours(s.written_at, now)}h ago): not auto-resumed; /frood-next ${s.name} to resume`);
  }
  return lines.join("\n");
}

// ---------------------------------------------------------------- migration

// Fold the old single handoff.json into stream "default", then step it aside. Safe to call on every verb (and the hook).
export function migrate() {
  const legacy = handoffPath();
  if (!fs.existsSync(legacy)) return false;
  if (fs.existsSync(streamFile("default"))) return false; // already migrated (or written again since)
  let h;
  try {
    h = JSON.parse(fs.readFileSync(legacy, "utf8"));
  } catch {
    return false; // a corrupt legacy file is left alone; never fail a session start over it
  }
  const obj = {
    name: "default",
    repo: "",
    plan: h.plan ?? "",
    status: "active",
    next: h.next ?? "",
    done: h.done ?? "",
    waiting: h.waiting ?? "",
    written_at: h.written_at ?? new Date().toISOString(),
    written_by: "",
    consumed_at: h.consumed_at ?? null,
    done_at: null,
  };
  fs.mkdirSync(streamsDir(), { recursive: true });
  atomicWrite(streamFile("default"), JSON.stringify(obj, null, 2) + "\n");
  let target = `${legacy}.migrated`;
  for (let i = 2; fs.existsSync(target); i++) target = `${legacy}.migrated.${i}`;
  try {
    fs.renameSync(legacy, target);
  } catch {}
  return true;
}

// ---------------------------------------------------------------- events and acks (append-only)

function jsonLines(file) {
  let raw;
  try {
    raw = fs.readFileSync(file, "utf8");
  } catch {
    return [];
  }
  const out = [];
  for (const line of raw.split(/\r?\n/)) {
    if (!line.trim()) continue;
    try {
      const v = JSON.parse(line);
      if (v && typeof v === "object" && typeof v.key === "string" && v.key) out.push(v);
    } catch {
      // an unreadable line is skipped: one bad append must never stop a read
    }
  }
  return out;
}

// Append one event line, unless its key is already present. Returns false for a duplicate (the check runs under the lock).
export function appendEvent(name, ev) {
  checkName(name);
  if (!ev || typeof ev.key !== "string" || !ev.key) throw new Error("an event needs a key");
  return withStreamLock(name, () => {
    if (jsonLines(eventsFile(name)).some((l) => l.key === ev.key)) return false;
    const { key, kind, run, out, ...rest } = ev;
    const line = { key, kind, at: ev.at ?? new Date().toISOString(), ...(run !== undefined ? { run } : {}), ...(out !== undefined ? { out } : {}), ...rest };
    fs.mkdirSync(streamsDir(), { recursive: true });
    fs.appendFileSync(eventsFile(name), JSON.stringify(line) + "\n");
    return true;
  });
}

// Deduped events: the first line for a key wins, later duplicates are ignored.
export function readEvents(name) {
  checkName(name);
  const seen = new Set();
  const out = [];
  for (const e of jsonLines(eventsFile(name))) {
    if (seen.has(e.key)) continue;
    seen.add(e.key);
    out.push(e);
  }
  return out;
}

// Every ack line as written (decision lines and `resolved: true` lines), in file order.
export function readAckLines(name) {
  checkName(name);
  return jsonLines(acksFile(name));
}

// key -> action for every event the desk has decided on (first line per key wins).
export function readAcks(name) {
  const m = new Map();
  for (const line of readAckLines(name)) if (!m.has(line.key)) m.set(line.key, line.action ?? "");
  return m;
}

// Append an ack; a no-op when the same key already has a line with the same meaning (one decision line, one resolved line).
export function appendAck(name, key, action = "", { resolved = false, ticket } = {}) {
  checkName(name);
  if (!key) throw new Error("an ack needs a key");
  return withStreamLock(name, () => {
    if (jsonLines(acksFile(name)).some((l) => l.key === key && Boolean(l.resolved) === Boolean(resolved))) return false;
    const line = { key, at: new Date().toISOString(), action: action ?? "" };
    if (ticket) line.ticket = ticket;
    if (resolved) line.resolved = true;
    fs.mkdirSync(streamsDir(), { recursive: true });
    fs.appendFileSync(acksFile(name), JSON.stringify(line) + "\n");
    return true;
  });
}

// Events nobody has handled yet. `queued` is bookkeeping for the desk's dead detection, never something to act on.
export function unhandled(name) {
  const acks = readAcks(name);
  return readEvents(name).filter((e) => e.kind !== "queued" && !acks.has(e.key));
}

// ---------------------------------------------------------------- the verbs (shared with T8's desk)

function saveStream(name, obj) {
  atomicWrite(streamFile(name), JSON.stringify(obj, null, 2) + "\n");
}

// Create or update a stream; a write is an end-of-session handoff, so it clears consumed_at and the session claim.
// A write also resets status to "active" unless explicitly provided, because a new handoff means the stream is being worked on again.
export function writeStream(name, fields = {}) {
  checkName(name);
  const now = new Date().toISOString();
  if (fields.status !== undefined && !STATUSES.includes(fields.status)) throw new Error(`bad --status ${fields.status}`);
  return withStreamLock(name, () => {
    const cur = readStream(name);
    if (heldByOther(cur, fields.by)) throw heldError(name, cur);
    const status = fields.status ?? "active"; // a write always makes the stream active unless explicitly set
    const obj = {
      name,
      repo: fields.repo ?? cur?.repo ?? "",
      plan: fields.plan !== undefined ? path.resolve(fields.plan) : cur?.plan ?? "",
      status,
      next: fields.next ?? cur?.next ?? "",
      done: fields.done ?? cur?.done ?? "",
      waiting: fields.waiting ?? cur?.waiting ?? "",
      written_at: now,
      written_by: fields.writtenBy ?? cur?.written_by ?? "",
      consumed_at: null,
      done_at: status === "done" ? cur?.done_at ?? now : cur?.done_at ?? null,
      claim: null, // the new session has not claimed it yet
    };
    if (cur?.noted_at) obj.noted_at = cur.noted_at;
    for (const k of LEASE_KEYS) obj[k] = cur?.[k] ?? null;
    saveStream(name, obj);
    return obj;
  });
}

// The desk's update: next/done/waiting only — consumed_at and written_at stay as they are.
export function noteStream(name, fields = {}) {
  checkName(name);
  return withStreamLock(name, () => {
    const cur = readStream(name);
    if (!cur) return null;
    if (heldByOther(cur, fields.by)) throw heldError(name, cur);
    const { state, ...obj } = cur;
    if (fields.next !== undefined) obj.next = fields.next;
    if (fields.done !== undefined) obj.done = fields.done;
    if (fields.waiting !== undefined) obj.waiting = fields.waiting;
    obj.noted_at = new Date().toISOString();
    saveStream(name, obj);
    return obj;
  });
}

// Mark consumed. Accepted for pending, consumed and stale streams (M4); parked and done are refused. With `session`
// the claim is enforced first, in the same lock acquisition (step 5 of /frood-next): a refused consume writes nothing at all.
export function consumeStream(name, { session, takeover = false } = {}) {
  checkName(name);
  return withStreamLock(name, () => {
    const cur = readStream(name);
    if (!cur) return { code: 1, msg: `no stream ${name}` };
    if (cur.state === "parked" || cur.state === "done") return { code: 1, msg: `stream ${name} is ${cur.state}` };
    let claim;
    let expired;
    if (session !== undefined) {
      const d = resolveClaim(name, cur.claim, session, Date.now(), takeover);
      if (d.code !== 0) return d;
      claim = d.claim;
      expired = d.expired;
    }
    const { state, ...obj } = cur;
    if (session !== undefined) obj.claim = claim;
    if (!obj.consumed_at) obj.consumed_at = new Date().toISOString();
    saveStream(name, obj);
    const out = { code: 0, value: obj };
    if (expired) out.note = claimExpiredLine(name, expired);
    return out;
  });
}

export function markDone(name) {
  checkName(name);
  return withStreamLock(name, () => {
    const cur = readStream(name);
    if (!cur) return null;
    const { state, ...obj } = cur;
    obj.status = "done";
    obj.done_at = new Date().toISOString();
    obj.held_by = obj.held_session = obj.held_at = null; // a done stream is not held
    obj.claim = null; // and nobody is working it
    saveStream(name, obj);
    return obj;
  });
}

// Take the lease for harness `by`. Runs entirely under the stream lock; the audit line is a raw append (never
// appendEvent/appendAck/withStreamLock in here: the lock is not re-entrant). Returns {code, msg?, value?, note?}.
// With `session` the session claim is decided and written inside that same lock acquisition, so a refused claim
// (exit 4) leaves the pointer byte-identical: not even held_session moves.
export function claimStream(name, by, { session, takeover = false } = {}) {
  checkName(name);
  return withStreamLock(name, () => {
    const cur = readStream(name);
    if (!cur) return { code: 1, msg: `no stream ${name}` };
    if (cur.state === "parked" || cur.state === "done") return { code: 1, msg: `stream ${name} is ${cur.state}` };
    const { state, ...obj } = cur;
    const now = new Date().toISOString();
    let claim;
    let expired;
    if (session !== undefined) {
      const d = resolveClaim(name, cur.claim, session, Date.now(), takeover);
      if (d.code !== 0) return d;
      claim = d.claim;
      expired = d.expired;
    }
    if (cur.held_by === by) {
      if (session !== undefined) obj.held_session = session;
      obj.handback_to = null;
    } else if (!cur.held_by) {
      Object.assign(obj, { held_by: by, held_session: session ?? null, held_at: now, taken_from: null, handback_to: null });
    } else {
      if (!takeover) return { code: 3, msg: heldLine(name, cur) };
      const from = { by: cur.held_by, session: cur.held_session };
      Object.assign(obj, { held_by: by, held_session: session ?? null, held_at: now, taken_from: from.by, handback_to: null });
      const line = { key: `takeover:${now}`, kind: "takeover", from: from.by, from_session: from.session, to: by, to_session: session ?? null, at: now };
      fs.appendFileSync(leaseFile(name), JSON.stringify(line) + "\n");
    }
    if (session !== undefined) obj.claim = claim;
    saveStream(name, obj);
    const out = { code: 0, value: obj };
    if (expired) out.note = claimExpiredLine(name, expired);
    return out;
  });
}

// Give the lease up (only lease fields change). `to` records who should pick it up next. The holder's release also
// clears the session claim: the session is handing the stream over, so the next /frood-next must not meet its own ghost.
// A release by a harness that does not hold the lease leaves a live claim alone (it is not giving anything up).
export function releaseStream(name, by, { to } = {}) {
  checkName(name);
  return withStreamLock(name, () => {
    const cur = readStream(name);
    if (!cur) return { code: 1, msg: `no stream ${name}` };
    const { state, ...obj } = cur;
    const now = new Date().toISOString();
    if (!cur.held_by) {
      if (to === undefined) return { code: 0, value: obj };
      obj.handback_to = to;
    } else if (cur.held_by === by) {
      Object.assign(obj, { held_by: null, held_session: null, held_at: null, handback_to: to ?? null, claim: null });
    } else {
      return { code: 3, msg: heldLine(name, cur) };
    }
    if (to !== undefined) {
      const line = { key: `handback:${now}`, kind: "handback", from: by, to, at: now };
      fs.appendFileSync(leaseFile(name), JSON.stringify(line) + "\n");
    }
    saveStream(name, obj);
    return { code: 0, value: obj };
  });
}

// Delete a finished stream's four files (the pointer, its events, its acks and its lease audit).
export function pruneStream(name) {
  checkName(name);
  withStreamLock(name, () => {
    for (const file of [streamFile(name), eventsFile(name), acksFile(name), leaseFile(name)]) {
      try {
        fs.rmSync(file, { force: true });
      } catch {}
    }
  });
}

// ---------------------------------------------------------------- CLI

function parseArgs(argv) {
  const values = new Map();
  const flags = new Set();
  for (let i = 0; i < argv.length; i++) {
    const arg = argv[i];
    if (!arg.startsWith("--")) throw new Error(`unexpected argument ${JSON.stringify(arg)}`);
    const key = arg.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) flags.add(key);
    else {
      values.set(key, next);
      i++;
    }
  }
  return { has: (k) => flags.has(k) || values.has(k), get: (k) => values.get(k) };
}

function usage() {
  console.error(
    "usage: handoff.mjs write --stream <n> --plan <p> --next <text> [--done <text>] [--waiting <text>] [--repo <dir>]\n" +
      "                  [--status active|parked|done] [--written-by <id>]\n" +
      "       handoff.mjs note --stream <n> [--next <text>] [--done <text>] [--waiting <text>]\n" +
      "       handoff.mjs show [--stream <n>] | consume [--stream <n>] | list [--json]\n" +
      "       handoff.mjs ack --stream <n> --key <k> [--action <line>] [--ticket <slug>] [--resolved]\n" +
      "       handoff.mjs done --stream <n>\n" +
      "       handoff.mjs claim --stream <n> --by <cc|oc> [--session <id>] [--takeover]\n" +
      "       handoff.mjs release --stream <n> --by <cc|oc> [--to <cc|oc>]\n" +
      "       (write and note also take --by <cc|oc>; exit 3 = held by the other harness; exit 4 = claimed by a live session with --session)",
  );
}

// Validate --by / --to / --session; throws (exit 2) on a bad value. Returns the parsed values.
function leaseArgs(a, { requireBy = false } = {}) {
  const pick = (k) => {
    if (!a.has(k)) return undefined;
    const v = a.get(k);
    if (!HARNESSES.includes(v)) throw new Error(`--${k} must be cc or oc`);
    return v;
  };
  const by = pick("by");
  if (requireBy && by === undefined) throw new Error("--by must be cc or oc");
  const to = pick("to");
  let session;
  if (a.has("session")) {
    session = a.get("session");
    if (typeof session !== "string" || !SESSION_RE.test(session)) throw new Error("bad --session");
  }
  return { by, to, session };
}

function requireStream(a) {
  const n = a.get("stream");
  if (n === undefined) throw new Error("--stream is required");
  return checkName(n);
}

function leaseResult(out) {
  if (out.code !== 0) {
    console.error(`handoff: ${out.msg}`);
    return out.code;
  }
  console.log(JSON.stringify(out.value));
  if (out.note) console.error(out.note);
  return 0;
}

function cmdClaim(a) {
  const { by, session } = leaseArgs(a, { requireBy: true });
  const name = requireStream(a);
  const out = claimStream(name, by, { session, takeover: a.has("takeover") });
  if (out.code === 0) out.value = readStream(name);
  return leaseResult(out);
}

function cmdRelease(a) {
  const { by, to } = leaseArgs(a, { requireBy: true });
  const name = requireStream(a);
  const out = releaseStream(name, by, { to });
  if (out.code === 0) out.value = readStream(name);
  return leaseResult(out);
}

function cmdWrite(a, name) {
  const { by } = leaseArgs(a);
  const plan = a.get("plan");
  if (!plan) throw new Error("--plan is required");
  if (!fs.existsSync(plan)) throw new Error(`plan file not found: ${plan}`);
  const next = a.get("next");
  if (!next) throw new Error("--next is required");
  const obj = writeStream(name, {
    plan,
    next,
    done: a.has("done") ? a.get("done") ?? "" : undefined,
    waiting: a.has("waiting") ? a.get("waiting") ?? "" : undefined,
    repo: a.get("repo"),
    status: a.get("status"),
    writtenBy: a.get("written-by"),
    by,
  });
  console.log(JSON.stringify(obj));
  return 0;
}

function cmdNote(a, name) {
  const { by } = leaseArgs(a);
  const obj = noteStream(name, {
    by,
    next: a.has("next") ? a.get("next") ?? "" : undefined,
    done: a.has("done") ? a.get("done") ?? "" : undefined,
    waiting: a.has("waiting") ? a.get("waiting") ?? "" : undefined,
  });
  if (!obj) {
    console.error(`handoff: no stream ${name}`);
    return 1;
  }
  console.log(JSON.stringify(obj));
  return 0;
}

// Tickets sitting in this repo's board that no stream points at: work somebody created and forgot
// to hand off. A board ticket is recognised by its `schema` field; a file without one was
// hand-written and was never on the board at all (that is the failure `/frood-ticket` prevents).
export function unstreamedTickets(dir = process.cwd(), streams = listStreams()) {
  const ticketsDir = path.join(dir, ".opencode", "board", "tickets");
  let files;
  try {
    files = fs.readdirSync(ticketsDir, { withFileTypes: true });
  } catch {
    return []; // no board in this directory: nothing to report
  }
  const refs = streams.flatMap((s) => [s?.plan, s?.next].map((v) => String(v ?? "")));
  const out = [];
  for (const ent of files.sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))) {
    if (!ent.isFile() || !ent.name.endsWith(".json")) continue;
    let t;
    try {
      t = JSON.parse(fs.readFileSync(path.join(ticketsDir, ent.name), "utf8"));
    } catch {
      continue; // unreadable is the board's quarantine case, not a silent work item
    }
    const id = typeof t?.id === "string" && t.id ? t.id : ent.name.replace(/\.json$/, "");
    if (!t || typeof t !== "object" || t.schema === undefined) {
      out.push({ id, kind: "hand-written, not on the board" });
      continue;
    }
    if (t.schema !== 1 || t.stage !== "queued") continue; // only queued tickets are waiting for a session
    // a stream already names it (whole-token match: "m1" is named by "plan-m1.md" but not hidden by "plan-m10.md")
    const tok = new RegExp(`(^|[^A-Za-z0-9_])${id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^A-Za-z0-9_])`);
    if (refs.some((r) => tok.test(r))) continue;
    out.push({ id, kind: `queued, not in any stream` });
  }
  return out;
}

function cmdShow(a) {
  const named = a.get("stream");
  if (named !== undefined) {
    checkName(named);
    const s = readStream(named);
    if (!s) {
      console.error(`handoff: no stream ${named}`);
      return 1;
    }
    console.log(JSON.stringify(s));
    return s.state === "pending" ? 0 : 1;
  }
  const all = listStreams();
  const pending = all.filter((s) => s.state === "pending");
  if (pending.length === 1) {
    console.log(JSON.stringify(pending[0]));
    return 0;
  }
  console.log(formatTable(all));
  // Exit 1 means no single pending stream, so nothing here is resumed for the owner: list the tickets
  // that no stream names, in case the work exists only on the board (or only as a hand-written file).
  const stray = unstreamedTickets(process.cwd(), all);
  if (stray.length) {
    console.log(`\nunstreamed tickets in ${process.cwd()}:`);
    for (const t of stray) console.log(`  ${t.id} — ${t.kind}`);
  }
  return 1;
}

function cmdConsume(a) {
  let target = a.get("stream");
  if (target === undefined) {
    const pending = listStreams().filter((s) => s.state === "pending");
    if (!pending.length) {
      console.log("null"); // the old shape for "nothing to resume"
      return 1;
    }
    if (pending.length > 1) {
      console.error(`handoff: ${pending.length} streams pending; name one with --stream`);
      return 2;
    }
    target = pending[0].name;
  }
  const session = a.get("session");
  const takeover = a.has("takeover");
  const out = consumeStream(target, { session, takeover });
  if (out.code !== 0) {
    console.error(`handoff: ${out.msg}`);
    return out.code;
  }
  console.log(JSON.stringify(out.value));
  if (out.note) console.error(out.note);
  return 0;
}

function cmdList(a) {
  const now = Date.now();
  for (const s of listStreams(now)) {
    if (s.state === "done" && now - Date.parse(s.done_at) > DONE_KEEP_MS) pruneStream(s.name);
  }
  const all = listStreams();
  if (a.has("json")) {
    const rows = all.map((s) => (s.state === "corrupt" ? { name: s.name, state: s.state, unhandled: 0 } : { ...s, unhandled: unhandled(s.name).length }));
    console.log(JSON.stringify(rows));
  } else {
    console.log(formatTable(all));
  }
  return 0;
}

function cmdAck(a, name) {
  const key = a.get("key");
  if (!key) throw new Error("--key is required");
  const resolved = a.has("resolved");
  const action = a.get("action");
  if (!resolved && action === undefined) throw new Error("--action or --resolved is required");
  if (!readEvents(name).some((e) => e.key === key)) {
    console.error(`handoff: no event ${key} in stream ${name}`);
    return 1;
  }
  appendAck(name, key, action ?? "", { resolved, ticket: a.get("ticket") });
  console.log(JSON.stringify(resolved ? { key, resolved: true } : { key, action: action ?? "" }));
  return 0;
}

function cmdDone(a, name) {
  const obj = markDone(name);
  if (!obj) {
    console.error(`handoff: no stream ${name}`);
    return 1;
  }
  console.log(JSON.stringify(obj));
  return 0;
}

function main(argv) {
  const [cmd, ...rest] = argv;
  const a = parseArgs(rest);
  const name = a.get("stream") ?? "default";
  migrate();
  switch (cmd) {
    case "write":
      return cmdWrite(a, checkName(name));
    case "note":
      return cmdNote(a, checkName(name));
    case "show":
      return cmdShow(a);
    case "consume":
      return cmdConsume(a);
    case "list":
      return cmdList(a);
    case "ack":
      return cmdAck(a, checkName(name));
    case "done":
      return cmdDone(a, checkName(name));
    case "claim":
      return cmdClaim(a);
    case "release":
      return cmdRelease(a);
    default:
      usage();
      return 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  let code = 2;
  try {
    code = main(process.argv.slice(2));
  } catch (e) {
    console.error(`handoff: ${e.message}`);
    code = e.exitCode ?? 2;
  }
  process.exit(code);
}

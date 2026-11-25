#!/usr/bin/env node
// Ticket board: records and verifies evidence; it never runs work (worktrees, gates and the train stay outside).
//
//   node bin/board.mjs <command> [args] [--repo <path>] [--expect-epoch <n>]
//
//   create <id> --mandate <path> --scope <a,b,...> [--title <t>] [--egm-trigger <name>]...
//          (the Mandate needs >=1 blast-radius bullet AND an "Atlas refs consulted / updated?" line)
//   egm <id> approve --report <path> --by <who>  |  waive --reason <text> --by <who>
//   egm <id> reopen --owner <s> --trigger <name>
//   claim <id> --owner <s> --harness claude|opencode --worktree <path>
//   heartbeat <id> --owner <s>
//   attach <id> --owner <s> --pid <n> --out <path>
//   session <id> --session <sid>     (records the desktop session holding the ticket in assignment.session; queued or
//                                     working; claim/reopen carry it over; `dispatch.mjs` and `desk.mjs status` read it)
//   release <id> --owner <s>   |   release <id> --force --by human --note <text>
//   fail <id> --note <text>     |   unblock <id> --by human --note <text>
//   watch [--now <iso>]
//   status [--json]             |   quarantine <id>
//
//   round <id> --owner <s> --worker-receipt <path> --findings <path> --reviewed-sha <sha>
//                       (--critic-receipt <path> | --native-critic sonnet|haiku|opus)
//   signoff <id> --by critic|senior|human [--owner <s>]
//   signoff <id> --by senior --owner <s> --findings <path> (--receipt <path> | --native <alias>)
//   gates <id> --owner <s>       |   ready <id> --owner <s>
//   verify <id> --sha <sha>      |   shipped <id> --sha <sha>
//   reopen <id> --owner <s> --harness claude|opencode --note <why> [--worktree <path>]
//          (ready -> working after the train refused the sha: every live signoff is invalidated, the round cap
//           and gate results are cleared, the round cap starts a fresh lap of 3, at most 2 reopens per ticket;
//           history and counted rounds are kept. The senior trigger "counted rounds > 2" stays cumulative, so a
//           ticket reopened after 3 rounds needs a senior; base_sha is not refreshed on a rebase)
//   --help  (or -h) prints this text and exits 0; nothing is written
//
// Repo root = parent of `git rev-parse --git-common-dir` from --repo/cwd, so it works from any worktree.
// Board dir = <root>/.opencode/board/ (adapter.json committed; tickets/ locks/ .board.lock gitignored).
// Every write reads (recording the epoch), validates, mutates, bumps the epoch, writes a temp file, fsyncs and
// renames; a write whose read epoch differs from --expect-epoch is refused. Counted rounds are never reset.
// Success prints the updated ticket as one JSON line (ready then prints its wake-up line); refusals print
// `board: <rule>` on stderr.
//
// Phase 2 in one line each: a `round` re-gates the findings itself, maps the worker receipt to an outcome, binds
// the round to the worktree HEAD and invalidates every earlier signoff; a `signoff` copies a paid verdict bound
// to that sha (a senior signoff must itself be paid); `gates` runs the adapter's argv on a clean worktree and
// records each result; `ready` re-checks all six rules (clean tree, HEAD = signed-off sha, non-free, senior when
// required, gates green at that sha, blast-radius tests present inside the worktree) and prints
// `READY <id> <branch> <sha>`; `verify`/`shipped` let the train prove the shipped commit is the reviewed one.
//
// Phase 3 in one line each: `attach` records the running oc-worker (its pid, that process's start time and its
// output path) so a later sweep can tell a live worker from a dead one; `watch` sweeps every `working` ticket and
// blocks `stale` the ones whose worker pid, output and lock heartbeat have all gone quiet on two sweeps in a row.
//
// Three documented deviations from "success prints the ticket":
//   - `quarantine` prints {id, quarantined_to}: it acts on a file that cannot be parsed, so there is no ticket to
//     print. It refuses (exit 1) any ticket that still parses — only a corrupt file may be quarantined.
//   - `status` prints one JSON array (or a table), not a ticket: it lists every ticket. `watch` also ends with that
//     status table (the design asks for it) and prints no ticket, because one sweep touches every ticket.
//   - `verify` prints nothing: it is read-only and the train reads its exit code (B12).
//
// Timestamps: `created`/`updated` more than 60 s in the future are refused as invalid. The 60 s tolerance is
// deliberate — it absorbs the clock skew between the processes that share one board dir on one machine.
// BOARD_LOCK_TIMEOUT_MS overrides the global-lock wait (default 10000); when it elapses the command exits 3.
// Exit: 0 ok, 1 refused by a rule (no write), 2 usage/schema/missing file, 3 lock contention or epoch conflict.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import path from "node:path";
import crypto from "node:crypto";
import { execFileSync, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { gate } from "./verdict-gate.mjs";
import { agentModel, isPolicyFree } from "./pool-health.mjs";
class Refuse extends Error {} // exit 1: a rule said no, nothing was written
class Usage extends Error {} // exit 2: usage, schema, or missing file
class Conflict extends Error {} // exit 3: lock contention or epoch conflict — retry

const ID_RE = /^[a-z0-9][a-z0-9-]{0,59}$/;
const EGM_STATUS = ["pending", "approved", "waived"];
const STAGES = ["queued", "working", "ready", "shipped", "blocked", "failed"];
const GLOBAL_LOCK_STALE_MS = 30_000; // a global lock older than this is a dead writer, not contention
const BARE_LOCK_STALE_MS = 60_000; // a ticket lock dir with no owner.json is reclaimable after this
const FUTURE_SKEW_MS = 60_000; // see the header: tolerated clock skew, not a licence for stale data
const ROUND_CAP = 3; // counted rounds 1..3 are allowed; a 4th blocks the ticket (`rounds_exhausted`)
const REOPEN_CAP = 2; // `reopen` laps per ticket; each lap gets its own ROUND_CAP, so the review spend stays bounded
// Per adapter gate; a timeout is a failed gate, never a hang. BOARD_GATE_TIMEOUT_MS overrides it (tests use seconds,
// so one stalled process spawn fails fast instead of holding the suite for 20 minutes — seen 2026-11-12).
const GATE_TIMEOUT_MS = Number(process.env.BOARD_GATE_TIMEOUT_MS) || 20 * 60_000;
const DROP = Symbol("drop-lock"); // a write callback returns this to release the ticket lock inside the write
// The stage machine: any pair not listed is refused (exit 1, no write). Later phases slot in as rows.
const STAGE = {
  create: { from: [], to: "queued", phase: 1 },
  claim: { from: ["queued"], to: "working", phase: 1 },
  "egm approve": { from: ["queued"], to: "queued", phase: 1 },
  "egm waive": { from: ["queued"], to: "queued", phase: 1 },
  "egm reopen": { from: ["working"], to: "queued", phase: 1 },
  release: { from: ["working"], to: "queued", phase: 1 },
  unblock: { from: ["blocked"], to: "queued", phase: 1 },
  fail: { from: ["queued", "working", "ready", "blocked"], to: "failed", phase: 1 },
  round: { from: ["working"], to: "working", phase: 2 },
  signoff: { from: ["working"], to: "working", phase: 2 },
  gates: { from: ["working"], to: "working", phase: 2 },
  ready: { from: ["working"], to: "ready", phase: 2 },
  shipped: { from: ["ready"], to: "shipped", phase: 2 },
  reopen: { from: ["ready"], to: "working", phase: 2 },
  attach: { from: ["working"], to: "working", phase: 3 },
  session: { from: ["queued", "working"], to: null, phase: 3 }, // stays where it is: a label, not a transition
  watch: { from: ["working"], to: "blocked", phase: 3 },
};

// ---------- helpers
const now = () => new Date().toISOString();
const sleep = (ms) => Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0, ms);
const rmrf = (p) => fs.rmSync(p, { recursive: true, force: true, maxRetries: 5 });
const rand = () => crypto.randomBytes(4).toString("hex");
const sha256 = (p) => crypto.createHash("sha256").update(fs.readFileSync(p)).digest("hex");
const isStr = (v) => typeof v === "string";
const isArr = (v) => Array.isArray(v);
const isFile = (p) => fs.existsSync(p) && fs.statSync(p).isFile();
const isDir = (p) => fs.existsSync(p) && fs.statSync(p).isDirectory();
const isGlobs = (v) => isArr(v) && v.every(isStr);
const alive = (pid) => {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
};
// Process start time as ISO UTC (design B7), so a recycled pid cannot pass for the old worker. win32 asks
// PowerShell; elsewhere `ps -o lstart=`. A lookup that fails is not an error: `started` stays null and liveness
// falls back to pid existence alone. The pid is validated before it reaches the command line.
function workerStart(pid) {
  if (!Number.isInteger(pid) || pid <= 0) return null;
  const toIso = (raw) => {
    const d = Date.parse(String(raw).trim());
    return d > 0 ? new Date(d).toISOString() : null;
  };
  try {
    if (process.platform === "win32") {
      const ps = "(Get-Process -Id " + pid + ").StartTime.ToUniversalTime().ToString('o')";
      const out = execFileSync("powershell", ["-NoProfile", "-Command", ps], {
        encoding: "utf8",
        stdio: ["ignore", "pipe", "ignore"],
        windowsHide: true,
      });
      return toIso(out);
    }
    const out = execFileSync("ps", ["-o", "lstart=", "-p", String(pid)], {
      encoding: "utf8",
      stdio: ["ignore", "pipe", "ignore"],
    });
    return toIso(out);
  } catch {
    return null;
  }
}
const mtimeNewer = (p, cutoffMs) => {
  try {
    return fs.statSync(p).mtimeMs > cutoffMs;
  } catch {
    return false;
  }
};
function readJson(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}
function writeJson(p, v) {
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(v, null, 2) + "\n");
}
const git = (cwd, args) =>
  execFileSync("git", ["-C", cwd, ...args], { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], windowsHide: true }).trim();
function tryGit(cwd, args) {
  try {
    return git(cwd, args);
  } catch {
    return null;
  }
}
const commonDir = (d) => tryGit(d, ["rev-parse", "--path-format=absolute", "--git-common-dir"]);
// Windows paths differ only by case and separators; compare them normalized.
const posixPath = (p) => path.resolve(p).replace(/\\/g, "/").replace(/\/+$/, "");
const norm = (p) => (process.platform === "win32" ? posixPath(p).toLowerCase() : posixPath(p));
function repoRoot(cwd) {
  const c = commonDir(cwd);
  if (!c) throw new Usage(`not a git repository: ${cwd}`);
  return path.dirname(c);
}
const lockWaitMs = () => Number(process.env.BOARD_LOCK_TIMEOUT_MS || 10_000);
// --help is the header comment block, so usage cannot drift out of date.
function usage() {
  const src = fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split(/\r?\n/);
  const out = [];
  for (let i = src[0]?.startsWith("#!") ? 1 : 0; i < src.length && src[i].startsWith("//"); i++) {
    out.push(src[i].replace(/^\/\/ ?/, ""));
  }
  return out.join("\n");
}

// ---------- arguments
function parseArgs(argv, bools) {
  const o = { _: [] };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k.length < 2 || !k.startsWith("-")) {
      o._.push(k);
      continue;
    }
    const name = k.replace(/^--?/, "");
    if (bools.includes(name)) {
      o[name] = true;
      continue;
    }
    const v = argv[++i];
    if (v === undefined) throw new Usage(`--${name} needs a value`);
    (o[name] ||= []).push(v);
  }
  return o;
}
const one = (o, k) => (isArr(o[k]) ? o[k][o[k].length - 1] : o[k]);
const text = (o, k) => String(one(o, k) ?? "").trim();
function need(o, k) {
  const v = one(o, k);
  if (v === undefined || v === "") throw new Usage(`--${k} is required`);
  return v;
}

// ---------- locations, adapter, globs
const boardDir = (root) => path.join(root, ".opencode", "board");
const ticketsDir = (root) => path.join(boardDir(root), "tickets");
const ticketPath = (root, id) => path.join(ticketsDir(root), `${id}.json`);
const lockPath = (root, id) => path.join(boardDir(root), "locks", `${id}.lock`);
const lockExists = (root, id) => fs.existsSync(lockPath(root, id));
const readLock = (root, id) => readJson(path.join(lockPath(root, id), "owner.json"));
const dropLock = (root, id) => rmrf(lockPath(root, id));

const isArgv = (g) => isArr(g) && g.length > 0 && g.every(isStr);
const ADAPTER_RULES = [
  ["base", (v) => isStr(v) && v !== "", "a non-empty string"],
  ["branch_prefix", isStr, "a string"],
  ["gates", (v) => isArr(v) && v.length > 0 && v.every(isArgv), "a non-empty array of argv arrays"],
  ["egm_paths", isGlobs, "an array of globs"],
  ["guarded_paths", isGlobs, "an array of globs"],
  ["stale_minutes", (v) => typeof v === "number" && v > 0, "a positive number"],
];
function readAdapter(root) {
  const p = path.join(boardDir(root), "adapter.json");
  let a;
  try {
    a = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch (e) {
    const msg = e.code === "ENOENT" ? `no adapter.json (required): ${p}` : `adapter.json is not valid JSON: ${p}`;
    throw new Usage(msg);
  }
  for (const [k, ok, want] of ADAPTER_RULES) {
    if (!ok(a[k])) throw new Usage(`adapter.json: ${k} must be ${want}`);
  }
  return a;
}

// Globs (B10): P matches G iff P matches G, or one of P's ancestor directories matches G.
// So scope "auth/login.ts" matches "**/auth" through its parent dir, even though the file itself never does.
function matchGlob(p, g) {
  const P = String(p).replace(/\\/g, "/").replace(/^\.\//, "");
  if (path.posix.matchesGlob(P, g)) return true;
  const ancestors = P.split("/");
  ancestors.pop();
  while (ancestors.length) {
    if (path.posix.matchesGlob(ancestors.join("/"), g)) return true;
    ancestors.pop();
  }
  return false;
}
const matchAny = (p, globs) => globs.some((g) => matchGlob(p, g));

// ---------- ticket schema v1
function nullishOf(f) {
  return (v) => v === null || f(v);
}
const isObjOrNull = nullishOf((v) => typeof v === "object" && !isArr(v));
const isBool = (v) => typeof v === "boolean";
// A timestamp more than FUTURE_SKEW_MS in the future is invalid (see the header for why the skew is allowed).
function isIso(v) {
  const d = Date.parse(v);
  return d > 0 && d <= Date.now() + FUTURE_SKEW_MS;
}
function isBlast(v) {
  if (!isArr(v) || !v.length) return false;
  return v.every((b) => {
    if (!b || !isStr(b.caller) || !b.caller.trim()) return false;
    if (!isStr(b.expect)) return false;
    return b.test == null || isStr(b.test);
  });
}
const TS = "an ISO-8601 timestamp that is not in the future";
const TICKET_RULES = [
  ["schema", (v) => v === 1, "1"],
  ["id", (v) => isStr(v) && ID_RE.test(v), "a valid id"],
  ["title", isStr, "a string"],
  ["stage", (v) => STAGES.includes(v), STAGES.join("|")],
  ["epoch", (v) => Number.isInteger(v) && v >= 0, "a non-negative integer"],
  ["mandate_path", (v) => isStr(v) && path.isAbsolute(v), "an absolute path"],
  ["scope", isGlobs, "a string[]"],
  ["blast_radius", isBlast, "entries with caller and expect"],
  ["egm", (v) => v && isBool(v.required) && EGM_STATUS.includes(v.status) && isArr(v.triggers), "required (bool), status pending|approved|waived, triggers"],
  ["worktree", nullishOf(isStr), "a path or null"],
  ["base_sha", nullishOf(isStr), "a sha or null"],
  ["assignment", isObjOrNull, "an object or null"],
  ["blocked", isObjOrNull, "an object or null"],
  ["rounds", isArr, "an array"],
  ["signoffs", isArr, "an array"],
  ["gates", isArr, "an array"],
  ["history", isArr, "an array"],
  ["senior", (v) => v && isBool(v.required) && isArr(v.reasons), "{required, reasons}"],
  ["created", isIso, TS],
  ["updated", isIso, TS],
];
function validateTicket(t, id) {
  const bad = (m) => {
    throw new Usage(`ticket schema (${id ?? t?.id}): ${m}`);
  };
  if (!t || typeof t !== "object" || isArr(t)) bad("not an object");
  for (const [k, ok, want] of TICKET_RULES) {
    if (!ok(t[k])) bad(`${k} must be ${want}`);
  }
  if (id && t.id !== id) bad(`id "${t.id}" does not match the file name`);
}
function readTicket(root, id) {
  if (!id || !ID_RE.test(id)) throw new Usage(`bad id "${id ?? ""}" — must match ^[a-z0-9][a-z0-9-]{0,59}$`);
  const p = ticketPath(root, id);
  let t;
  try {
    t = JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    if (!fs.existsSync(p)) throw new Usage(`no ticket ${id}`);
    throw new Usage(`ticket ${id} is not readable JSON`);
  }
  validateTicket(t, id);
  return t;
}

// Atomic write: temp file -> fsync -> rename (retry EPERM/EBUSY 5x at 100 ms).
function atomicWrite(root, id, t) {
  const p = ticketPath(root, id);
  const tmp = `${p}.${process.pid}.${rand()}.tmp`;
  fs.mkdirSync(path.dirname(p), { recursive: true });
  const fd = fs.openSync(tmp, "w");
  try {
    fs.writeSync(fd, JSON.stringify(t, null, 2) + "\n");
    fs.fsyncSync(fd);
  } finally {
    fs.closeSync(fd);
  }
  for (let i = 0; ; i++) {
    try {
      return fs.renameSync(tmp, p);
    } catch (e) {
      if ((e.code !== "EPERM" && e.code !== "EBUSY") || i >= 5) throw e;
      sleep(100);
    }
  }
}

// ---------- phase 2 helpers: receipts, outcomes, free-ness, senior, worktree facts
function needOwner(t, owner) {
  if (t.assignment?.owner !== owner) {
    throw new Refuse(`ticket ${t.id} is owned by ${t.assignment?.owner ?? "nobody"}, not ${owner}`);
  }
}
function needWorktree(t) {
  if (!t.worktree || !isDir(t.worktree)) throw new Usage(`ticket ${t.id} has no worktree (claim it first)`);
  return t.worktree;
}
const headOf = (wt) => git(wt, ["rev-parse", "HEAD"]);
function readReceipt(p, what) {
  if (!isFile(p)) throw new Usage(`${what} not found: ${p}`);
  const v = readJson(p);
  if (!v || typeof v !== "object" || isArr(v)) throw new Usage(`${what} is not a JSON object: ${p}`);
  return v;
}
// oc-worker receipts have no `status` field (design B1): the outcome is these rules, in this order.
function workerStatusLine(r) {
  const v = String(r?.verdict ?? "").trim();
  if (/^RESULT:/.test(v)) return v; // the verdict wins when it is the status line
  return String(r?.first_line ?? "").trim();
}
function workerOutcome(r) {
  if (r.exit === "timeout" || r.exit === "stalled") return r.landed ? "done" : "timeout";
  if (r.exit === "no-healthy-pool") return "no_pool";
  // A missing `out` is as good as a null one: no final message was saved.
  if (r.exit === 0 && (r.out === null || r.out === undefined)) return "no_output";
  const line = workerStatusLine(r);
  if (r.exit === 0 && line.startsWith("RESULT: DONE")) return "done";
  if (line.startsWith("RESULT: BLOCKED: question")) return "blocked_question";
  return "error";
}
// Free-ness (design B5): the agent name first, then the resolved model. Nothing resolvable => free, because a
// signoff that cannot be proved paid must never be the one that ships. The agent name comes from a receipt, so it
// is validated before pool-health turns it into a file path (a receipt is not allowed to name ../../something).
const AGENT_RE = /^[a-z0-9][a-z0-9-]{0,40}$/;
function resolvedModel(agent, raw) {
  if (!raw || raw === "(agent default)") {
    return (isStr(agent) && AGENT_RE.test(agent) ? agentModel(agent) : null) || null;
  }
  return raw;
}
function criticFree(agent, rawModel) {
  const a = isStr(agent) ? agent : "";
  const model = resolvedModel(a, isStr(rawModel) ? rawModel : null);
  if (/-free$/.test(a)) return { free: true, model, free_source: `agent:${a}` };
  if (!model) return { free: true, model: isStr(rawModel) ? rawModel : null, free_source: "unknown" };
  const free = (model.startsWith("opencode/") && model.endsWith("-free")) || isPolicyFree(model); // owner-allowlisted free-only provider model
  return { free, model, free_source: `model:${model}` };
}
function blockTicket(t, reason, note) {
  t.stage = "blocked";
  t.blocked = { reason, note: note ? String(note).trim().slice(0, 200) : null, at: now() };
  t.assignment = null; // leaving working drops the lock; unblock -> queued -> claim again
}
function trailingUncounted(rounds) {
  let n = 0;
  for (let i = rounds.length - 1; i >= 0 && !rounds[i].counted; i--) n++;
  return n;
}
// senior is recomputed every round (design): the declared scope's guarded paths are never dropped (fail safe),
// and the actual diff, a critic asking for it, and a third counted round can each add the requirement.
function recomputeSenior(t, adapter, wt, findingsText) {
  const reasons = seniorFor(t.scope, adapter).reasons;
  const counted = t.rounds.filter((r) => r.counted).length;
  if (counted > 2) reasons.push(`counted rounds ${counted} > 2`);
  if (findingsText && /^\s*SENIOR_REVIEW:\s*needed\b/im.test(findingsText)) reasons.push("critic: SENIOR_REVIEW needed");
  if (t.base_sha && wt) {
    for (const p of (tryGit(wt, ["diff", "--name-only", t.base_sha, "HEAD"]) || "").split("\n").filter(Boolean)) {
      if (matchAny(p, adapter.guarded_paths)) reasons.push(`guarded path: ${p}`);
    }
  }
  const unique = [...new Set(reasons)];
  return { required: unique.length > 0, reasons: unique };
}
// Clean-tree rule (B13): one `node_modules` entry is the shared install, not the ticket's work. Returns paths, so a
// refusal can name the offending file instead of `?? <path>`.
function dirtyLines(wt) {
  return git(wt, ["status", "--porcelain", "--untracked-files=all"])
    .split("\n")
    .filter(Boolean)
    .map((l) => l.slice(3).trim().replace(/^"(.*)"$/, "$1"))
    .filter((p) => p !== "node_modules" && p !== "node_modules/");
}

// ---------- locks (mkdir is the mutex)
function takeLock(d) {
  try {
    fs.mkdirSync(d);
    return true;
  } catch (e) {
    if (e.code !== "EEXIST") throw e;
    return false;
  }
}
// Is the global lock at `d` a dead writer's? Reads the owner it has right now, or its mtime when it has none.
function globalLockStale(d) {
  const owner = readJson(path.join(d, "owner.json"));
  if (owner) {
    const at = Date.parse(owner.at);
    return !(at > 0) || Date.now() - at > GLOBAL_LOCK_STALE_MS;
  }
  try {
    return Date.now() - fs.statSync(d).mtimeMs > GLOBAL_LOCK_STALE_MS;
  } catch {
    return false; // it vanished; the caller retries the mkdir
  }
}
// Break a stale global lock without ever deleting the path we examined: `rename` is atomic, so exactly one
// breaker wins the tombstone. We then re-read the owner inside the tombstone — if a fresh lock was swapped in
// between our read and our rename, that owner is not stale and we put it back.
// KNOWN LIMITATION (accepted by senior review, 2026-11-12): if a third process mkdirs the lock path in the
// microseconds between that check and the rename-back, the fresh lock stays stranded in the tombstone and two
// writers could overlap. It needs two simultaneous breakers of a CRASHED writer's lock plus a third arrival;
// epoch checks still refuse a stale write. Stray `.board.lock.break.*` dirs are safe to delete.
function breakGlobalLock(d) {
  const tomb = `${d}.break.${process.pid}.${rand()}`;
  try {
    fs.renameSync(d, tomb);
  } catch {
    return false; // another breaker got there first
  }
  if (!globalLockStale(tomb)) {
    try {
      fs.renameSync(tomb, d);
    } catch {}
    return false;
  }
  rmrf(tomb);
  return true;
}
// Retry every 50 ms until BOARD_LOCK_TIMEOUT_MS; break a lock older than 30 s or a bare dir older than 30 s.
function withGlobalLock(root, fn) {
  const d = path.join(boardDir(root), ".board.lock");
  const deadline = Date.now() + lockWaitMs();
  fs.mkdirSync(path.dirname(d), { recursive: true });
  for (;;) {
    if (takeLock(d)) {
      writeJson(path.join(d, "owner.json"), { pid: process.pid, at: now() });
      try {
        return fn();
      } finally {
        rmrf(d);
      }
    }
    if (globalLockStale(d)) {
      breakGlobalLock(d);
      continue;
    }
    if (Date.now() > deadline) throw new Conflict(`global lock is held: ${d}`);
    sleep(50);
  }
}

// Breakable only when the heartbeat is older than stale_minutes and no worker pid lives (a bare dir: 60 s).
function lockBreakable(root, id, adapter) {
  const d = lockPath(root, id);
  let age;
  try {
    age = Date.now() - fs.statSync(d).mtimeMs;
  } catch {
    return true; // gone
  }
  const cur = readLock(root, id);
  if (!cur) return age > BARE_LOCK_STALE_MS;
  const pid = readJson(ticketPath(root, id))?.assignment?.worker?.pid;
  if (pid && alive(pid)) return false;
  const hb = Date.parse(cur.heartbeat || cur.at || "");
  return !(hb > 0) || Date.now() - hb > adapter.stale_minutes * 60_000;
}
// A live foreign lock is lock contention (exit 3, retry), not a rule refusal: the design's exit-code table says
// so, and the caller may legitimately retry once the owner's heartbeat goes stale.
function takeTicketLock(ctx, id, owner, harness) {
  const d = lockPath(ctx.root, id);
  fs.mkdirSync(path.dirname(d), { recursive: true });
  if (!takeLock(d)) {
    const cur = readLock(ctx.root, id);
    if (!lockBreakable(ctx.root, id, ctx.adapter)) {
      throw new Conflict(`ticket ${id} is locked by ${cur?.owner || "an unknown owner"}`);
    }
    rmrf(d);
    fs.mkdirSync(d);
  }
  writeJson(path.join(d, "owner.json"), { owner, harness, heartbeat: now() });
  ctx.lockTaken = true; // `write` drops this again if the command fails after taking it (#8)
}

// ---------- the one write path
function assertFrom(cmd, t) {
  const s = STAGE[cmd];
  if (!s) throw new Usage(`unknown transition ${cmd}`);
  if (!s.from.includes(t.stage)) {
    throw new Refuse(`${cmd} needs stage ${s.from.join("|") || "new"}, ticket is ${t.stage}`);
  }
}
function checkEpoch(t, o) {
  const want = one(o, "expect-epoch");
  if (want === undefined) return;
  if (!/^\d+$/.test(want)) throw new Usage("--expect-epoch must be an integer");
  if (Number(want) !== t.epoch) throw new Conflict(`epoch ${t.epoch} != expected ${want}`);
}
// read (record epoch) -> validate -> mutate -> epoch+1 -> atomic write, all under the global lock.
// The ticket lock is dropped inside the same callback for transitions that leave `working` (#3): releasing it
// afterwards would race a claim that has already broken the stale lock and taken a fresh one.
function write(ctx, id, o, cmd, fn, drop = false) {
  return withGlobalLock(ctx.root, () => {
    ctx.lockTaken = false;
    try {
      const t = readTicket(ctx.root, id);
      const from = t.stage;
      checkEpoch(t, o);
      const wantsDrop = fn(t) === DROP; // a round that blocks, or `ready`, releases the lock in this callback
      t.epoch += 1;
      t.updated = now();
      t.history.push({
        at: t.updated,
        cmd,
        from,
        to: t.stage,
        by: one(o, "owner") || one(o, "by") || null,
        note: text(o, "note") || null,
      });
      validateTicket(t, id);
      atomicWrite(ctx.root, id, t);
      if (drop || wantsDrop) dropLock(ctx.root, id); // any transition into blocked, queued or failed drops the lock
      return t;
    } catch (e) {
      // A lock this command took must not outlive its own failure, or the next claim waits out stale_minutes.
      if (ctx.lockTaken) dropLock(ctx.root, id);
      throw e;
    }
  });
}

// ---------- create
// Mandate blast radius: a heading line, then "- " bullets until the next non-bullet, non-blank line.
function parseBlastRadius(md) {
  const lines = String(md).replace(/\r\n/g, "\n").split("\n");
  const out = [];
  const start = lines.findIndex((l) => /^\s*\**blast radius\b/i.test(l));
  if (start < 0) return out;
  for (let i = start + 1; i < lines.length; i++) {
    const l = lines[i];
    if (/^\s*$/.test(l)) continue;
    if (!/^\s*-\s+/.test(l)) break;
    let b = l.replace(/^\s*-\s+/, "").trim();
    let test;
    const tm = b.match(/(?:[;,]\s*|\s+)test:\s*(\S+)\s*$/i);
    if (tm) {
      test = tm[1];
      b = b.slice(0, tm.index).trim().replace(/[;,]$/, "").trim();
    }
    const sep = b.indexOf(" — "); // the first " — " splits caller from expect; none means unchanged
    const entry = sep < 0
      ? { caller: b, expect: "unchanged" }
      : { caller: b.slice(0, sep).trim(), expect: b.slice(sep + 3).trim() };
    if (!entry.caller) continue;
    if (test) entry.test = test;
    out.push(entry);
  }
  return out;
}
// Atlas line: the Mandate says what the repo map (`docs/ATLAS.md`, `docs/atlas/`, or the map the repo's
// CLAUDE.md/AGENTS.md names) said about the entry points the ticket touches, and which map lines change.
// Written as a bold label with the answer after it ("**Atlas refs consulted / updated?** no map in this repo")
// or as a bullet. The label starts the line, and `no map` is an answer while an empty label is not: refuse.
function parseAtlasRefs(md) {
  for (const raw of String(md).replace(/\r\n/g, "\n").split("\n")) {
    const line = raw.replace(/\*/g, "").trim().replace(/^[-*]\s+/, "");
    if (!/^atlas refs\b/i.test(line)) continue;
    const rest = line.replace(/^atlas refs[^:?—–-]*[:?—–-]?/i, "").replace(/^[\s:—–-]+/, "");
    return rest.trim() || null;
  }
  return null;
}
// Only paths with a "/" after the first segment name a directory: a root-level file is not a module.
function topDirs(scope) {
  const dirs = new Set();
  for (const s of scope) {
    const p = String(s).replace(/\\/g, "/").replace(/^\.\//, "");
    const cut = p.indexOf("/");
    if (cut > 0) dirs.add(p.slice(0, cut));
  }
  return [...dirs];
}
function seniorFor(scope, adapter) {
  const reasons = scope.filter((s) => matchAny(s, adapter.guarded_paths)).map((s) => `guarded path: ${s}`);
  return { required: reasons.length > 0, reasons };
}
function cmdCreate(ctx) {
  const o = ctx.o;
  const id = o._[0];
  if (!id || !ID_RE.test(id)) throw new Usage(`bad id "${id ?? ""}" — must match ^[a-z0-9][a-z0-9-]{0,59}$`);
  const mandate = path.resolve(need(o, "mandate"));
  if (!isFile(mandate)) throw new Usage(`mandate not found: ${mandate}`);
  const scope = need(o, "scope").split(",").map((s) => s.trim()).filter(Boolean);
  if (!scope.length) throw new Usage("--scope needs at least one path");
  const mand = fs.readFileSync(mandate, "utf8");
  const blast = parseBlastRadius(mand);
  if (!blast.length) throw new Refuse("mandate has no blast-radius bullets");
  // The Atlas line is the Mandate's map answer; `no map` is an answer, silence is not (atlas-m1).
  if (!parseAtlasRefs(mand)) throw new Refuse('mandate has no Atlas line ("Atlas refs consulted / updated?" — write "no map" when the repo has none)');
  const want = one(o, "expect-epoch");
  if (want !== undefined && !/^\d+$/.test(want)) throw new Usage("--expect-epoch must be an integer");
  if (want !== undefined && want !== "0") throw new Conflict(`a new ticket is epoch 0, not ${want}`);
  return withGlobalLock(ctx.root, () => {
    if (fs.existsSync(ticketPath(ctx.root, id))) throw new Refuse(`ticket ${id} already exists`);
    const triggers = new Set(o["egm-trigger"] || []);
    if (scope.some((s) => matchAny(s, ctx.adapter.egm_paths))) triggers.add("data-model");
    if (topDirs(scope).length > 3) triggers.add("many-modules");
    const at = now();
    const t = {
      schema: 1,
      id,
      title: one(o, "title") || id,
      stage: STAGE.create.to,
      epoch: 0,
      mandate_path: mandate,
      scope,
      blast_radius: blast,
      egm: {
        required: triggers.size > 0,
        triggers: [...triggers],
        status: "pending",
        reason: null,
        report_path: null,
        report_sha256: null,
        by: null,
        at: null,
      },
      worktree: null,
      base_sha: null,
      assignment: null,
      rounds: [],
      senior: seniorFor(scope, ctx.adapter),
      signoffs: [],
      gates: [],
      blocked: null,
      history: [{ at, cmd: "create", from: null, to: STAGE.create.to, by: one(o, "owner") || null, note: null }],
      created: at,
      updated: at,
    };
    validateTicket(t, id);
    atomicWrite(ctx.root, id, t);
    return t;
  });
}

// ---------- egm approve | waive | reopen (a new ticket starts pending; claim needs approve or waive)
function cmdEgm(ctx) {
  const o = ctx.o;
  const [id, sub] = o._;
  if (!id || !sub) throw new Usage("egm needs <id> approve|waive|reopen");
  if (sub === "reopen") {
    const owner = need(o, "owner");
    const trigger = need(o, "trigger");
    return write(ctx, id, o, "egm reopen", (t) => {
      assertFrom("egm reopen", t);
      if (t.assignment?.owner !== owner) {
        throw new Refuse(`ticket ${id} is owned by ${t.assignment?.owner ?? "nobody"}`);
      }
      t.egm.triggers = [...new Set([...t.egm.triggers, trigger])];
      Object.assign(t.egm, {
        required: true,
        status: "pending",
        reason: null,
        report_path: null,
        report_sha256: null,
        by: owner,
        at: now(),
      });
      t.stage = STAGE["egm reopen"].to;
      t.assignment = null;
      t.blocked = null;
    }, true);
  }
  if (sub !== "approve" && sub !== "waive") throw new Usage(`unknown egm action "${sub}"`);
  const by = need(o, "by");
  return write(ctx, id, o, `egm ${sub}`, (t) => {
    assertFrom(`egm ${sub}`, t); // approve/waive are queued-only, like every unlisted pair
    if (t.egm.status !== "pending") throw new Refuse(`egm is already ${t.egm.status}`);
    if (sub === "approve") {
      const report = path.resolve(need(o, "report"));
      if (!isFile(report)) throw new Usage(`report not found: ${report}`);
      Object.assign(t.egm, {
        status: "approved",
        report_path: report,
        report_sha256: sha256(report),
        reason: null,
        by,
        at: now(),
      });
      return;
    }
    if (t.egm.required) throw new Refuse(`egm is required for ${id} — waive is not allowed`);
    const reason = text(o, "reason");
    if (reason.length < 20) throw new Refuse("waive needs --reason of at least 20 characters");
    Object.assign(t.egm, {
      status: "waived",
      reason,
      report_path: null,
      report_sha256: null,
      by,
      at: now(),
    });
  });
}

// ---------- claim / heartbeat / release
// A session recorded before the claim (the dispatcher knows it first) survives the claim and a reopen.
const keepSession = (t) => (t.assignment?.session ? { session: t.assignment.session } : {});
function cmdClaim(ctx, id) {
  const o = ctx.o;
  const owner = need(o, "owner");
  const harness = need(o, "harness");
  if (harness !== "claude" && harness !== "opencode") throw new Usage("--harness must be claude or opencode");
  const wt = path.resolve(need(o, "worktree"));
  if (!isDir(wt)) throw new Usage(`--worktree does not exist: ${wt}`);
  const here = commonDir(ctx.root);
  const there = commonDir(wt);
  if (!there || norm(there) !== norm(here)) {
    throw new Refuse(`--worktree is not a worktree of this repo: ${wt}`);
  }
  const base = tryGit(ctx.root, ["rev-parse", ctx.adapter.base]);
  if (!base) throw new Refuse(`adapter.base does not resolve: ${ctx.adapter.base}`);
  return write(ctx, id, o, "claim", (t) => {
    assertFrom("claim", t);
    if (t.egm.status === "pending") {
      throw new Refuse(`egm is pending — approve or waive it before claiming ${id}`);
    }
    takeTicketLock(ctx, id, owner, harness);
    t.stage = STAGE.claim.to;
    t.worktree = wt;
    t.base_sha = base;
    t.assignment = { owner, harness, since: now(), missed_sweeps: 0, worker: null, ...keepSession(t) };
  });
}
function cmdHeartbeat(ctx, id) {
  const owner = need(ctx.o, "owner");
  return withGlobalLock(ctx.root, () => {
    const t = readTicket(ctx.root, id);
    checkEpoch(t, ctx.o);
    const cur = readLock(ctx.root, id);
    if (!cur) throw new Refuse(`ticket ${id} has no lock to heartbeat`);
    if (cur.owner !== owner) throw new Refuse(`ticket ${id} is locked by ${cur.owner}, not ${owner}`);
    writeJson(path.join(lockPath(ctx.root, id), "owner.json"), { ...cur, heartbeat: now() });
    return t; // lock file only: no ticket write, no history entry
  });
}
function cmdRelease(ctx, id) {
  const o = ctx.o;
  const force = o.force === true;
  const owner = one(o, "owner");
  const note = text(o, "note");
  if (!force && !owner) throw new Usage("--owner is required (or --force --by human --note)");
  if (force && !note) throw new Usage("--force needs --note");
  if (force && one(o, "by") !== "human") throw new Usage("--force needs --by human");
  return write(ctx, id, o, force ? "release --force" : "release", (t) => {
    assertFrom("release", t);
    if (!force) {
      if (t.assignment?.owner !== owner) {
        throw new Refuse(`ticket ${id} is owned by ${t.assignment?.owner ?? "nobody"}, not ${owner}`);
      }
    } else if (note.length < 10) {
      throw new Refuse("--force needs --note of at least 10 characters");
    }
    t.stage = STAGE.release.to;
    t.assignment = null;
  }, true);
}

// ---------- fail / unblock
function cmdFail(ctx, id) {
  if (!text(ctx.o, "note")) throw new Usage("--note is required");
  return write(ctx, id, ctx.o, "fail", (t) => {
    assertFrom("fail", t);
    t.stage = STAGE.fail.to;
    t.assignment = null;
  }, true);
}
function cmdUnblock(ctx, id) {
  if (need(ctx.o, "by") !== "human") throw new Usage("unblock needs --by human");
  const note = text(ctx.o, "note");
  if (!note) throw new Usage("--note is required");
  if (note.length < 10) throw new Refuse("unblock needs --note of at least 10 characters");
  return write(ctx, id, ctx.o, "unblock", (t) => {
    assertFrom("unblock", t);
    if (readLock(ctx.root, id)) throw new Refuse(`ticket ${id} still has a lock — release it first`);
    t.stage = STAGE.unblock.to;
    t.assignment = null;
    t.blocked = null;
  });
}

// ---------- round / signoff / gates / ready / verify / shipped (phase 2)
// A done round: the critic is re-gated by the board from `--findings`; the receipt's own gate is never trusted.
function doneRoundCritic(o, findingsText) {
  const receiptArg = o["critic-receipt"] === undefined ? null : path.resolve(one(o, "critic-receipt"));
  const native = o["native-critic"] === undefined ? null : text(o, "native-critic");
  if (Boolean(receiptArg) === Boolean(native)) {
    throw new Usage("a done round takes exactly one of --critic-receipt or --native-critic");
  }
  const findingsSha = sha256(path.resolve(need(o, "findings")));
  if (receiptArg) {
    const cr = readReceipt(receiptArg, "critic receipt");
    const f = criticFree(cr.agent, cr.model);
    const g = gate(findingsText, { free: f.free });
    return {
      source: "receipt",
      alias: isStr(cr.agent) ? cr.agent : null,
      model: f.model,
      free: f.free,
      free_source: f.free_source,
      critic_verdict: g.critic,
      effective: g.effective,
      reasons: g.reasons,
      findings_sha256: findingsSha,
      receipt_sha256: sha256(receiptArg),
    };
  }
  if (!["sonnet", "haiku", "opus"].includes(native)) throw new Usage("--native-critic must be sonnet, haiku or opus");
  // A native Claude Code subagent has no receipt and no free tier: it is a paid review by construction.
  const g = gate(findingsText, { free: false });
  return {
    source: "native",
    alias: native,
    model: native,
    free: false,
    free_source: `native:${native}`,
    critic_verdict: g.critic,
    effective: g.effective,
    reasons: g.reasons,
    findings_sha256: findingsSha,
    receipt_sha256: null,
  };
}
function cmdRound(ctx, id) {
  const o = ctx.o;
  const owner = need(o, "owner");
  const workerPath = path.resolve(need(o, "worker-receipt"));
  const wr = readReceipt(workerPath, "worker receipt");
  const outcome = workerOutcome(wr);
  const done = outcome === "done";
  const worker = {
    outcome,
    agent: isStr(wr.agent) ? wr.agent : null,
    model: isStr(wr.model) ? wr.model : null,
    receipt_sha256: sha256(workerPath),
  };
  // The cost of the run is the whole session tree when oc-worker could read it, else the run's own cost.
  const cost = Number(Number(wr.tree?.total_cost ?? wr.cost ?? 0).toFixed(6));
  let critic = null;
  let findingsText = "";
  let reviewedArg = null;
  if (done) {
    findingsText = (() => {
      const p = path.resolve(need(o, "findings"));
      if (!isFile(p)) throw new Usage(`findings not found: ${p}`);
      return fs.readFileSync(p, "utf8");
    })();
    reviewedArg = String(need(o, "reviewed-sha"));
    critic = doneRoundCritic(o, findingsText);
  } else if (o.findings !== undefined) {
    // B4: only a done round has findings. Refusing this keeps a blocked/timeout round from looking reviewed.
    throw new Usage("--findings is only accepted when the worker outcome is done");
  }

  return write(ctx, id, o, "round", (t) => {
    assertFrom("round", t);
    needOwner(t, owner);
    const wt = needWorktree(t);
    const head = headOf(wt);
    // The cap is per lap: a `reopen` starts a new one after the round it was reopened at (rounds are never reset).
    const floor = isArr(t.reopens) && t.reopens.length ? t.reopens[t.reopens.length - 1].after_round : 0;
    const counted = t.rounds.filter((r) => r.counted && r.n > floor).length;

    if (done) {
      if (counted >= ROUND_CAP) {
        // A listed transition (working -> blocked), so this succeeds and prints the blocked ticket. The round is
        // not recorded: the 4th review is exactly the evidence the cap exists to stop.
        blockTicket(t, "rounds_exhausted", `${counted} counted rounds already — a 4th round is refused`);
        return DROP;
      }
      if (reviewedArg !== head) throw new Refuse(`--reviewed-sha ${reviewedArg} is not HEAD ${head}`);
      const round = {
        n: t.rounds.length + 1,
        at: now(),
        counted: true,
        worker,
        critic,
        reviewed_sha: head,
        cost,
        senior_needed: false,
      };
      t.rounds.push(round);
      // A new review of new work invalidates every earlier signoff; `invalidated_by` names the round that did it.
      for (const s of t.signoffs) if (s.invalidated_by == null) s.invalidated_by = round.n;
      t.senior = recomputeSenior(t, ctx.adapter, wt, findingsText);
      round.senior_needed = t.senior.required;
      return;
    }

    // The three blocking outcomes record no round: the design says "appends" only for an uncounted 1st/2nd, and
    // evidence of a run nobody may retry belongs in `blocked`, not in the round list a reviewer reads.
    if (outcome === "blocked_question") {
      blockTicket(t, "worker_question", workerStatusLine(wr));
      return DROP;
    }
    if (outcome === "no_pool") {
      blockTicket(t, "no_pool", (wr.errors || [])[0] || "oc-worker found no healthy pool");
      return DROP;
    }
    // timeout | no_output | error: recorded uncounted, so the orchestrator may retry — twice in a row, then a human.
    if (trailingUncounted(t.rounds) >= 2) {
      blockTicket(t, "manual", `3rd consecutive uncounted round (${outcome})`);
      return DROP;
    }
    const round = {
      n: t.rounds.length + 1,
      at: now(),
      counted: false,
      worker,
      critic: null,
      reviewed_sha: null, // nothing was reviewed: an uncounted round never invalidates a signoff
      cost,
      senior_needed: false,
    };
    t.rounds.push(round);
    // No findings means no critic answer to recompute from: an uncounted round must not erase a "SENIOR_REVIEW:
    // needed" the last real review asked for. The next counted round recomputes from the whole diff again.
    round.senior_needed = t.senior.required;
  });
}

// A senior reply is a review like any other except that it is never free: it must gate APPROVED as written.
function seniorSignoff(o) {
  const findingsPath = path.resolve(need(o, "findings"));
  if (!isFile(findingsPath)) throw new Usage(`findings not found: ${findingsPath}`);
  const receiptArg = o.receipt === undefined ? null : path.resolve(one(o, "receipt"));
  const native = o.native === undefined ? null : text(o, "native");
  if (Boolean(receiptArg) === Boolean(native)) {
    throw new Usage("--by senior needs exactly one of --receipt or --native");
  }
  const g = gate(fs.readFileSync(findingsPath, "utf8"), { free: false });
  if (!String(g.effective).startsWith("APPROVED")) {
    const why = g.reasons.length ? ` (${g.reasons.join("; ")})` : "";
    throw new Refuse(`senior findings gate ${g.effective}${why}`);
  }
  if (native) return { model: native, free: false, free_source: `native:${native}` };
  const receipt = readReceipt(receiptArg, "senior receipt");
  const f = criticFree(receipt.agent, receipt.model);
  // A senior signoff is the shipping-policy guard: a free one would let the free-review loophole back in.
  if (f.free) throw new Refuse(`a senior signoff must be a paid review, not ${f.free_source}`);
  return { model: f.model, free: f.free, free_source: f.free_source };
}
function cmdSignoff(ctx, id) {
  const o = ctx.o;
  const by = need(o, "by");
  if (!["critic", "senior", "human"].includes(by)) throw new Usage("--by must be critic, senior or human");
  const owner = by === "human" ? null : need(o, "owner"); // a human sign-off belongs to no ticket owner
  const senior = by === "senior" ? seniorSignoff(o) : null;

  return write(ctx, id, o, "signoff", (t) => {
    assertFrom("signoff", t);
    if (by !== "human") needOwner(t, owner);
    if (!t.rounds.length) throw new Refuse(`signoff needs at least one round`);
    const wt = needWorktree(t);
    let s;
    if (by === "critic") {
      // The latest counted round is the review being endorsed; an uncounted one reviewed nothing.
      const r = [...t.rounds].reverse().find((x) => x.counted);
      if (!r) throw new Refuse("signoff --by critic needs a counted round");
      const verdict = String(r.critic?.effective ?? "MISSING");
      if (!verdict.startsWith("APPROVED")) throw new Refuse(`the latest counted round is ${verdict}, not APPROVED`);
      s = { model: r.critic.model, free: r.critic.free, free_source: r.critic.free_source, reviewed_sha: r.reviewed_sha };
    } else if (by === "senior") {
      s = { model: senior.model, free: senior.free, free_source: senior.free_source, reviewed_sha: headOf(wt) };
    } else {
      s = { model: null, free: false, free_source: null, reviewed_sha: headOf(wt) };
    }
    t.signoffs.push({ by, ...s, at: now(), invalidated_by: null });
  });
}

function cmdGates(ctx, id) {
  const o = ctx.o;
  const owner = need(o, "owner");
  // Validate before the (possibly slow) run; the write below re-checks under the lock.
  const first = readTicket(ctx.root, id);
  assertFrom("gates", first);
  needOwner(first, owner);
  const wt = needWorktree(first);
  // Gates measure a commit: a dirty tree would let a gate pass on code that is not in the sha being signed off.
  const dirty = dirtyLines(wt);
  if (dirty.length) throw new Refuse(`worktree is dirty (${dirty[0]}) — gates run on a clean worktree only`);
  const sha = headOf(wt);
  const results = [];
  for (const [i, argv] of ctx.adapter.gates.entries()) {
    const logPath = path.join(ticketsDir(ctx.root), `${id}.gate-${i + 1}.log`);
    const r = spawnSync(argv[0], argv.slice(1), {
      cwd: wt,
      encoding: "utf8",
      timeout: GATE_TIMEOUT_MS,
      windowsHide: true,
      shell: false, // argv only: a gate is never handed to a shell
      maxBuffer: 16 * 1024 * 1024,
    });
    const timedOut = r.signal != null || r.error?.code === "ETIMEDOUT";
    // A gate that never started (ENOENT, EACCES) is a broken adapter, not a slow gate: its own code, its own line.
    const spawnError = !timedOut && Boolean(r.error);
    const output = String(r.stdout || "") + String(r.stderr || "");
    const note = spawnError
      ? `\nboard: gate could not start: ${r.error.message}\n`
      : timedOut
        ? `\nboard: gate timed out after ${Math.round(GATE_TIMEOUT_MS / 1000)} s\n`
        : "";
    fs.writeFileSync(logPath, output + note);
    const exit = timedOut ? 124 : spawnError ? 127 : r.status ?? 1; // 124 = timed out, 127 = never ran
    results.push({ argv: [...argv], exit, sha, at: now(), log_path: logPath });
    if (exit !== 0) break; // stop at the first failure; ready wants every gate green at the sha
  }
  return write(ctx, id, o, "gates", (t) => {
    assertFrom("gates", t);
    needOwner(t, owner);
    t.gates = results; // the latest run replaces the earlier evidence; a failed gate never changes the stage
  });
}

function cmdReady(ctx, id) {
  const o = ctx.o;
  const owner = need(o, "owner");
  const t = write(ctx, id, o, "ready", (t) => {
    assertFrom("ready", t);
    needOwner(t, owner);
    const wt = needWorktree(t);
    const dirty = dirtyLines(wt);
    if (dirty.length) throw new Refuse(`worktree is dirty (${dirty[0]}) — commit or clean it first`);
    const head = headOf(wt);
    const live = t.signoffs.filter((s) => !s.invalidated_by);
    const sig = live[live.length - 1]; // the newest signoff that a later round has not invalidated
    if (!sig) {
      throw new Refuse(t.signoffs.length ? "every signoff was invalidated by a later round" : "no signoff yet");
    }
    if (sig.reviewed_sha !== head) {
      throw new Refuse(`HEAD ${head} is not the signed-off sha ${sig.reviewed_sha}`);
    }
    const humanSameSha = live.some((s) => s.by === "human" && s.reviewed_sha === sig.reviewed_sha);
    if (sig.free && !humanSameSha) {
      throw new Refuse(`the signoff is free (${sig.free_source ?? "free"}) — a paid critic, senior or human must sign this sha`);
    }
    // A senior signoff must itself be a paid review (a human is non-free by definition), so the answer cannot
    // depend on the order the two signoffs arrived in: a free senior never satisfies the requirement.
    const seniorSameSha = live.some(
      (s) => (s.by === "senior" || s.by === "human") && !s.free && s.reviewed_sha === sig.reviewed_sha,
    );
    if (t.senior.required && !seniorSameSha) {
      throw new Refuse(`senior review is required (${t.senior.reasons.join("; ")}) — a paid senior or a human must sign this sha`);
    }
    for (const argv of ctx.adapter.gates) {
      const ok = t.gates.find((g) => isArr(g.argv) && g.argv.join("\0") === argv.join("\0") && g.sha === sig.reviewed_sha && g.exit === 0);
      if (!ok) throw new Refuse(`gate ${argv.join(" ")} has no exit 0 at ${sig.reviewed_sha}`);
    }
    for (const b of t.blast_radius) {
      if (b.expect === "unchanged") continue;
      if (!b.test) throw new Refuse(`blast radius "${b.caller}" changed expectations but names no test path`);
      const abs = path.resolve(wt, b.test);
      const rel = path.relative(wt, abs);
      // The test has to be the ticket's, not some file it points at outside its own tree (`../shared/x.test.mjs`).
      if (!rel || rel.startsWith("..") || path.isAbsolute(rel)) {
        throw new Refuse(`blast radius "${b.caller}" test ${b.test} resolves outside the worktree`);
      }
      if (!fs.existsSync(abs)) {
        throw new Refuse(`blast radius "${b.caller}" test ${b.test} does not exist in the worktree`);
      }
    }
    t.stage = "ready";
    // The owner and worker are gone, but the desktop session stays visible: the dispatcher needs it while the
    // ticket waits for the train (`desk status`). Only a recorded session survives; otherwise assignment is null.
    t.assignment = t.assignment?.session
      ? { owner: null, harness: null, since: null, missed_sweeps: 0, worker: null, session: t.assignment.session }
      : null;
    return DROP; // ready releases the lock
  });
  const branch = `${ctx.adapter.branch_prefix}${id}`;
  return [t, `READY ${id} ${branch} ${t.signoffs.filter((s) => !s.invalidated_by).pop().reviewed_sha} — board verify then train`];
}

// Read-only: exit 0 iff the ticket is ready and the sha the train is about to ship is the signed-off sha.
function cmdVerify(ctx, id) {
  const sha = String(need(ctx.o, "sha"));
  const t = readTicket(ctx.root, id);
  const live = t.signoffs.filter((s) => !s.invalidated_by);
  const sig = live[live.length - 1];
  if (t.stage !== "ready") throw new Refuse(`ticket ${id} is ${t.stage}, not ready`);
  if (!sig) throw new Refuse(`ticket ${id} has no signoff`);
  if (sig.reviewed_sha !== sha) throw new Refuse(`sha ${sha} is not the signed-off sha ${sig.reviewed_sha}`);
  return null; // the train reads the exit code, not a ticket
}

function cmdShipped(ctx, id) {
  const sha = String(need(ctx.o, "sha"));
  return write(ctx, id, ctx.o, "shipped", (t) => {
    assertFrom("shipped", t);
    const live = t.signoffs.filter((s) => !s.invalidated_by);
    const sig = live[live.length - 1];
    if (!sig) throw new Refuse(`ticket ${id} has no signoff`);
    if (sig.reviewed_sha !== sha) throw new Refuse(`sha ${sha} is not the signed-off sha ${sig.reviewed_sha}`);
    t.stage = "shipped";
    t.assignment = null;
  }, true);
}

// reopen: the train refused a ready ticket's sha (a failing suite, a merge conflict). Before this, the only way out of
// `ready` was `fail` plus a new ticket id, which lost the ticket's history and renamed its branch. Reopening keeps
// both, and gives none of the old evidence a second life: every live signoff is invalidated, so `ready` needs a new
// round, a new signoff and green gates at the fixed sha. It is owner-claimed like `claim` and takes the ticket lock.
function cmdReopen(ctx, id) {
  const o = ctx.o;
  const owner = need(o, "owner");
  const harness = need(o, "harness");
  if (harness !== "claude" && harness !== "opencode") throw new Usage("--harness must be claude or opencode");
  const note = text(o, "note");
  if (!note) throw new Usage("--note is required (what the train refused)");
  if (note.length < 20) throw new Refuse("reopen needs --note of at least 20 characters naming the train failure");
  const wtArg = one(o, "worktree");
  const wtNew = wtArg ? path.resolve(wtArg) : null;
  return write(ctx, id, o, "reopen", (t) => {
    assertFrom("reopen", t);
    const reopens = isArr(t.reopens) ? t.reopens : [];
    if (reopens.length >= REOPEN_CAP) {
      throw new Refuse(`ticket ${id} was already reopened ${reopens.length} times — fail it and open a new ticket`);
    }
    const wt = wtNew ?? t.worktree;
    if (!wt || !isDir(wt)) throw new Usage(`worktree does not exist: ${wt ?? "(none)"} — pass --worktree`);
    const there = commonDir(wt);
    if (!there || norm(there) !== norm(commonDir(ctx.root))) {
      throw new Refuse(`--worktree is not a worktree of this repo: ${wt}`);
    }
    const after = t.rounds.length;
    const live = t.signoffs.filter((s) => !s.invalidated_by);
    const refused = live.length ? live[live.length - 1].reviewed_sha : null;
    for (const s of live) s.invalidated_by = `reopen ${reopens.length + 1}`;
    takeTicketLock(ctx, id, owner, harness);
    // Gate results go too: `ready` matches gates by sha, so green gates at the refused sha would otherwise carry a
    // same-sha re-ready (a flaky lap) through without a single gate run. The log files stay on disk as evidence.
    t.gates = [];
    t.reopens = [...reopens, { n: reopens.length + 1, at: now(), by: owner, note, after_round: after, refused_sha: refused }];
    t.stage = STAGE.reopen.to;
    t.worktree = wt;
    t.assignment = { owner, harness, since: now(), missed_sweeps: 0, worker: null, ...keepSession(t) };
    t.blocked = null;
  });
}

// ---------- attach / watch (phase 3)
// attach is called by the running oc-worker (`oc-worker --ticket`): it records the pid, that process's start
// time and the output path a sweep should watch. The start-time lookup happens before the write, so the global
// lock is never held across a PowerShell/ps call.
function cmdAttach(ctx, id) {
  const o = ctx.o;
  const owner = need(o, "owner");
  const pidText = String(need(o, "pid"));
  if (!/^\d+$/.test(pidText) || Number(pidText) <= 0) throw new Usage("--pid must be a positive integer");
  const pid = Number(pidText);
  const outPath = path.resolve(need(o, "out"));
  const started = workerStart(pid);
  return write(ctx, id, o, "attach", (t) => {
    assertFrom("attach", t);
    needOwner(t, owner);
    // `claim` already refuses a pending EGM, so this only fires on hand-edited state; the design names it anyway.
    if (t.egm.status === "pending") throw new Refuse(`egm is pending on ${id}`);
    t.assignment.worker = { pid, started, out_path: outPath };
    t.assignment.missed_sweeps = 0; // a new worker starts a new liveness clock
  });
}

// session records which desktop session holds the ticket. It works on a queued ticket (the dispatcher starts the
// session before the session claims), so a queued ticket may carry an assignment with no owner yet.
function cmdSession(ctx, id) {
  const o = ctx.o;
  const sid = String(need(o, "session")).trim();
  if (!sid || /\s/.test(sid)) throw new Usage("--session must be one non-empty token");
  return write(ctx, id, o, "session", (t) => {
    assertFrom("session", t);
    t.assignment = t.assignment ?? { owner: null, harness: null, since: null, missed_sweeps: 0, worker: null };
    t.assignment.session = sid;
  });
}

// Liveness (B7): the recorded worker is live while its pid is alive AND still that same process (`started`); when
// the start-time lookup fails, pid existence alone decides. A worker that cannot be seen that way still proves it
// is working through its output, its event stream or the lock heartbeat inside stale_minutes.
function liveWorker(root, t, adapter, nowMs) {
  const cutoff = nowMs - adapter.stale_minutes * 60_000;
  const w = t.assignment?.worker;
  if (w && Number.isInteger(w.pid) && w.pid > 0 && alive(w.pid)) {
    const cur = workerStart(w.pid);
    // A recycled pid started at a different time and is not this worker. Both reads go through the same clock
    // and formatting, so `started` (attach) and `cur` (now) are equal for the same process.
    if (!cur || !w.started || cur === w.started) return true;
  }
  if (w && isStr(w.out_path)) {
    if (mtimeNewer(w.out_path, cutoff) || mtimeNewer(`${w.out_path}.events.jsonl`, cutoff)) return true;
  }
  const hb = Date.parse(readLock(root, t.id)?.heartbeat ?? "");
  return hb > cutoff;
}
// One ticket in a sweep, written under the global lock like every other ticket write. `--expect-epoch` does not
// apply: one ticket's epoch cannot describe a sweep over every ticket. The start-time query is a sub-second
// process lookup that is part of the check the lock protects, never a gate or a git command. A live sweep that
// finds missed_sweeps already 0 records nothing at all (no epoch churn from polling), and a ticket that left
// `working` between the listing and this write is skipped rather than refused: a sweep is not a transition.
function sweepWrite(ctx, id, nowMs) {
  return withGlobalLock(ctx.root, () => {
    const t = readTicket(ctx.root, id);
    if (t.stage !== "working" || !t.assignment) return null;
    const live = liveWorker(ctx.root, t, ctx.adapter, nowMs);
    const from = t.stage;
    if (live) {
      if (t.assignment.missed_sweeps === 0) return null;
      t.assignment.missed_sweeps = 0;
    } else {
      t.assignment.missed_sweeps = (t.assignment.missed_sweeps ?? 0) + 1;
    }
    const missed = t.assignment.missed_sweeps;
    if (!live && missed >= 2) {
      // Two sweeps in a row with no evidence: the worker is gone. Leaving `working` drops the lock (B9).
      blockTicket(t, "stale", `no live worker pid, output or heartbeat on ${missed} sweeps`);
    }
    t.epoch += 1;
    t.updated = now();
    t.history.push({ at: t.updated, cmd: "watch", from, to: t.stage, by: null, note: live ? "live" : `missed_sweeps ${missed}` });
    validateTicket(t, id);
    atomicWrite(ctx.root, id, t);
    if (t.stage !== "working") dropLock(ctx.root, id);
    return t;
  });
}
const watchPath = (root) => path.join(boardDir(root), ".watch.json");
// A sweep over every `working` ticket, then the status table. `--now` is the whole clock (tests): the heartbeat,
// output mtimes and the gap to the previous sweep are all measured against it.
function cmdWatch(ctx) {
  const raw = one(ctx.o, "now");
  const nowMs = raw === undefined ? Date.now() : Date.parse(String(raw));
  if (!(nowMs > 0)) throw new Usage("--now must be an ISO-8601 timestamp");
  const lastMs = Date.parse(readJson(watchPath(ctx.root))?.at ?? "");
  // Sleep detection (B7): if the laptop slept, nobody observed the gap, so this sweep changes nothing but the
  // timestamp; the next one inside stale_minutes is the first real observation.
  const slept = lastMs > 0 && nowMs - lastMs > ctx.adapter.stale_minutes * 60_000;
  if (!slept) {
    for (const f of ticketFiles(ctx.root)) {
      const id = f.slice(0, -".json".length);
      if (!ID_RE.test(id)) continue;
      try {
        sweepWrite(ctx, id, nowMs);
      } catch (e) {
        // One unreadable ticket must not stop the sweep for the others (`status` lists it as CORRUPT).
        if (!(e instanceof Usage)) throw e;
      }
    }
  }
  writeJson(watchPath(ctx.root), { at: new Date(nowMs).toISOString() });
  cmdStatus({ ...ctx, o: {} }); // the design asks for the status table after the sweep
  return null;
}

// ---------- status / quarantine
function ticketFiles(root) {
  try {
    return fs.readdirSync(ticketsDir(root), { withFileTypes: true })
      .filter((d) => d.isFile() && d.name.endsWith(".json"))
      .map((d) => d.name);
  } catch {
    return [];
  }
}
// A corrupt ticket is listed and skipped; it never blocks the other tickets.
const CORRUPT = { stage: "CORRUPT", owner: null, age_min: null, rounds: 0, cost: 0, egm: null, signoff: null };
function statusRow(t, id) {
  const s = t.signoffs.filter((x) => !x.invalidated_by).pop();
  const age_min = Math.max(0, Math.round((Date.now() - Date.parse(t.created)) / 60_000));
  const rounds = t.rounds.filter((r) => r.counted);
  const cost = Number(rounds.reduce((a, r) => a + (r.cost || 0), 0).toFixed(6));
  return {
    id,
    stage: t.stage,
    owner: t.assignment?.owner ?? null,
    age_min,
    rounds: rounds.length,
    cost,
    egm: t.egm.status,
    signoff: s ? `${s.by}:${String(s.reviewed_sha || "").slice(0, 8)}` : null,
    ...(t.assignment?.session ? { session: t.assignment.session } : {}), // only when set: the row shape is pinned
  };
}
function cmdStatus(ctx) {
  const rows = [];
  for (const f of ticketFiles(ctx.root)) {
    const id = f.slice(0, -".json".length);
    let t = null;
    try {
      t = JSON.parse(fs.readFileSync(ticketPath(ctx.root, id), "utf8"));
      validateTicket(t, id);
    } catch {
      t = null;
    }
    rows.push(t ? statusRow(t, id) : { id, ...CORRUPT });
  }
  rows.sort((a, b) => a.id.localeCompare(b.id));
  if (ctx.o.json === true) return console.log(JSON.stringify(rows));
  console.log("ID\tSTAGE\tOWNER\tROUNDS\tAGE_MIN\tEGM\tSIGNOFF");
  for (const r of rows) {
    console.log([r.id, r.stage, r.owner ?? "-", r.rounds, r.age_min ?? "-", r.egm ?? "-", r.signoff ?? "-"].join("\t"));
  }
}
// quarantine is for a file the board can no longer read. A ticket that still parses is live state, and moving it
// (with its lock) would silently delete a working ticket — so that is refused, not "deviated from".
function cmdQuarantine(ctx, id) {
  if (!id || !ID_RE.test(id)) throw new Usage(`bad id "${id ?? ""}"`);
  const src = ticketPath(ctx.root, id);
  if (!fs.existsSync(src)) throw new Usage(`no ticket ${id}`);
  let parses = true;
  try {
    readTicket(ctx.root, id);
  } catch {
    parses = false;
  }
  if (parses) throw new Refuse(`ticket ${id} parses — quarantine only moves a corrupt file`);
  const dest = path.join(ticketsDir(ctx.root), "quarantine", `${id}.json`);
  withGlobalLock(ctx.root, () => {
    fs.mkdirSync(path.dirname(dest), { recursive: true });
    fs.renameSync(src, dest);
    dropLock(ctx.root, id);
  });
  return { id, quarantined_to: dest }; // no ticket to print: the file does not parse
}

// ---------- dispatch
const COMMANDS = {
  create: (ctx) => cmdCreate(ctx),
  egm: (ctx) => cmdEgm(ctx),
  status: (ctx) => cmdStatus(ctx),
  claim: (ctx, id) => cmdClaim(ctx, id),
  heartbeat: (ctx, id) => cmdHeartbeat(ctx, id),
  attach: (ctx, id) => cmdAttach(ctx, id),
  session: (ctx, id) => cmdSession(ctx, id),
  watch: (ctx) => cmdWatch(ctx),
  release: (ctx, id) => cmdRelease(ctx, id),
  fail: (ctx, id) => cmdFail(ctx, id),
  unblock: (ctx, id) => cmdUnblock(ctx, id),
  quarantine: (ctx, id) => cmdQuarantine(ctx, id),
  round: (ctx, id) => cmdRound(ctx, id),
  signoff: (ctx, id) => cmdSignoff(ctx, id),
  gates: (ctx, id) => cmdGates(ctx, id),
  ready: (ctx, id) => cmdReady(ctx, id),
  verify: (ctx, id) => cmdVerify(ctx, id),
  shipped: (ctx, id) => cmdShipped(ctx, id),
  reopen: (ctx, id) => cmdReopen(ctx, id),
};
function main(argv) {
  const [cmd, ...rest] = argv;
  const o = parseArgs(rest, ["json", "force"]);
  const ctx = { root: repoRoot(one(o, "repo") || process.cwd()), o };
  ctx.adapter = readAdapter(ctx.root);
  // Object.hasOwn, not `COMMANDS[cmd]`: a bare lookup would find Object.prototype members ("toString",
  // "constructor", "hasOwnProperty") and exit 0 having done nothing.
  if (Object.hasOwn(COMMANDS, cmd)) return COMMANDS[cmd](ctx, o._[0]);
  // A later-phase command is refused by the stage table first (exit 1, no write), so the table stays the
  // authority on transitions; only then does the phase gate report it unimplemented.
  if (Object.hasOwn(STAGE, cmd)) {
    assertFrom(cmd, readTicket(ctx.root, o._[0]));
    throw new Usage(`${cmd} is not implemented yet (phase ${STAGE[cmd].phase})`);
  }
  throw new Usage(`unknown command "${cmd ?? ""}"`);
}
const argv = process.argv.slice(2);
if (!argv.length) {
  console.error(usage());
  process.exit(2);
}
if (argv.includes("--help") || argv.includes("-h")) {
  console.log(usage());
  process.exit(0);
}
try {
  const out = main(argv);
  // A command may return [ticket, ...extraLines] when it prints more than the ticket (ready's wake-up line).
  if (isArr(out)) {
    console.log(JSON.stringify(out[0]));
    for (const line of out.slice(1)) console.log(line);
  } else if (out && typeof out === "object") console.log(JSON.stringify(out));
} catch (e) {
  console.error(`board: ${e instanceof Error ? e.message : e}`);
  process.exit(e instanceof Refuse ? 1 : e instanceof Conflict ? 3 : 2);
}

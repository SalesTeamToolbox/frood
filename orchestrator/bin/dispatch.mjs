#!/usr/bin/env node
// Parallel dispatch: which board tickets may run in their own sessions at once, and how many may run.
//
//   node bin/dispatch.mjs plan <ticket-id|plan-file>... [--repo <path>] [--json]
//   node bin/dispatch.mjs cap [--kind build|train] [--exclude <id>]... [--repo <path>] [--json]
//   node bin/dispatch.mjs status [--ticket <id>] [--session <sid>] [--repo <path>] [--json | --line]
//     --session keeps only tickets held by that session (assignment.session or assignment.owner, or a stream named
//     after the ticket whose held_session is sid); counts then cover those tickets alone.
//   --help  (or -h) prints this text and exits 0
//
// plan: each argument is a ticket id on the board, or a plan file; a plan file contributes every board ticket id it
//   names as a whole token. Per ticket it reads the stored `scope` and `blast_radius` (callers and tests) from
//   .opencode/board/tickets/<id>.json and any `depends: <id>, <id>` line in the ticket's Mandate. Two tickets
//   CONFLICT when their file sets overlap (the same path, a path under the other's directory, or globs whose
//   literal prefixes nest) or when one depends on the other. It never guesses: overlap means serial.
//   Paths are compared normalised (posix, `..` collapsed, repo/worktree prefix stripped, case-insensitive); an entry
//   without a `/` (a bare `desk.mjs`) overlaps any path with that last segment.
//   Output: ordered `groups`; every ticket in a group can run at once, and group N+1 starts only when every ticket
//   of group N is shipped (groups run one after another). `held` (not grouped): a ticket that depends on a board
//   ticket outside the argument list which is not `shipped` or `closed`, or whose files overlap a ticket already in flight on
//   the board (working, ready, or queued with a session) that is not in the argument list. `unknown` (not
//   grouped): a ticket whose `depends:` names an id that is not on the board, reported apart so a typo is seen.
//   A `depends:` value of none / n/a / nothing / - means no dependency.
//   Exit 0 ok, 1 a dependency cycle, 2 usage / missing ticket.
// cap: counts board tickets by stage and refuses (exit 1) when the cap for the kind is reached.
//   build = tickets in `working`, plus `queued` tickets that already carry a session (dispatched, not yet claimed);
//   train = tickets in `ready` (queued for or inside the train and verify), minus any `--exclude <id>`: the
//   dispatcher passes the ticket it is about to depart, so "one ready ticket, departing it" passes while a
//   second ticket in the train is refused. Caps come from .opencode/board/
//   adapter.json `max_parallel` {build, train}; absent keys default to build 2, train 1. The box-wide suite lock
//   and the train stay serial regardless: parallelism is for building and review, never for heavy gates.
//   Exit 0 room left, 1 refused (cap reached), 2 usage / bad adapter.
// Repo root = parent of `git rev-parse --git-common-dir` from --repo/cwd, so it works from any worktree.
import "./no-window.mjs";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { slotConfig, readSample, allowedSlots } from "./slots.mjs";
import { activeRuns } from "./oc-worker.mjs";

const DEFAULT_CAPS = { build: 2, train: 1 };
const ID_RE = /^[a-z0-9][a-z0-9-]{0,59}$/;
class Usage extends Error {}

function repoRoot(cwd) {
  try {
    const c = execFileSync("git", ["-C", cwd, "rev-parse", "--path-format=absolute", "--git-common-dir"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
    return path.dirname(c);
  } catch {
    throw new Usage(`not a git repository: ${cwd}`);
  }
}
const ticketsDir = (root) => path.join(root, ".opencode", "board", "tickets");
function readJson(p) {
  try {
    return JSON.parse(fs.readFileSync(p, "utf8"));
  } catch {
    return null;
  }
}
function boardTickets(root) {
  let names = [];
  try {
    names = fs.readdirSync(ticketsDir(root)).filter((n) => n.endsWith(".json"));
  } catch {}
  const out = [];
  for (const n of names.sort()) {
    const t = readJson(path.join(ticketsDir(root), n));
    if (t && t.schema === 1 && typeof t.id === "string") out.push(t);
  }
  return out;
}

// ---------- file sets and overlap
const PATH_RE = /[\w.@-]+\/[\w./*@-]+|\b[\w-]+\.(?:mjs|js|cjs|ts|tsx|py|md|json|sh|css|html|yml|yaml|toml)\b/g;
// Posix, `..` collapsed, an absolute path under the repo root or the ticket's worktree made relative, lower-cased.
function normPath(p, roots = []) {
  let x = String(p).replace(/\\/g, "/").toLowerCase();
  for (const r of roots) {
    const rr = String(r ?? "").replace(/\\/g, "/").replace(/\/+$/, "").toLowerCase();
    if (rr && (x === rr || x.startsWith(`${rr}/`))) {
      x = x.slice(rr.length + 1);
      break;
    }
  }
  x = path.posix.normalize(x || ".").replace(/^\.\//, "").replace(/\/+$/, "");
  // The repo root (`.`, `./`, or the root path itself) is the whole tree: `**` overlaps every file. It used to
  // normalise to "" and be filtered out, so a whole-repo scope overlapped nothing and failed open.
  return x === "." || x === "" ? "**" : x;
}
export function filesOf(t, root = null) {
  const roots = [t.worktree, root];
  const set = new Set((t.scope ?? []).map((p) => normPath(p, roots)));
  for (const b of t.blast_radius ?? []) {
    for (const m of String(b.caller ?? "").match(PATH_RE) ?? []) set.add(normPath(m, roots));
    if (typeof b.test === "string" && b.test) set.add(normPath(b.test, roots));
  }
  return [...set].filter(Boolean);
}
// The literal directory/file path before the first wildcard, as segments: "a/b/*.mjs" -> [a, b].
function literal(g) {
  const segs = g.split("/");
  const out = [];
  for (const s of segs) {
    if (/[*?[\]{}]/.test(s)) return { segs: out, glob: true };
    out.push(s);
  }
  return { segs: out, glob: false };
}
const nests = (a, b) => a.length <= b.length && a.every((s, i) => s === b[i]);
const lastSeg = (p) => p.split("/").pop();
export function pathsOverlap(a, b) {
  if (a === b) return true;
  // A bare name (no `/`) may be any directory's file: it overlaps whatever ends in the same last segment.
  if (!a.includes("/") !== !b.includes("/")) {
    const [bare, other] = a.includes("/") ? [b, a] : [a, b];
    const seg = lastSeg(other);
    if (bare === seg || path.posix.matchesGlob(seg, bare) || path.posix.matchesGlob(bare, seg)) return true;
  }
  const la = literal(a);
  const lb = literal(b);
  // Either side is a directory or glob when it is a strict path-prefix of the other, or carries a wildcard.
  if (nests(la.segs, lb.segs) || nests(lb.segs, la.segs)) {
    if (la.glob || lb.glob) return true; // a glob covers everything under its literal prefix
    return la.segs.length !== lb.segs.length; // a directory contains the file/dir below it
  }
  return false;
}
// The first pair of paths shared by two tickets, or null. THE shared-file check: dispatch never groups on a hit.
export function sharedFile(fa, fb) {
  for (const a of fa) for (const b of fb) if (pathsOverlap(a, b)) return a === b ? a : `${a} ~ ${b}`;
  return null;
}

// `depends: a, b` (optionally bold / bulleted / `**depends:**`) anywhere in the Mandate.
const NO_DEPENDENCY = new Set(["none", "n/a", "na", "nothing", "no", "-", "nil"]);
export function dependsOf(mandateText) {
  const out = new Set();
  for (const line of String(mandateText).split(/\r?\n/)) {
    const m = /^\s*(?:[-*]\s+)?\**depends\**\s*:\**\s*(.+)$/i.exec(line);
    if (!m) continue;
    for (const tok of m[1].split(/[,\s]+/)) {
      const id = tok.replace(/[`*.;]/g, "");
      if (NO_DEPENDENCY.has(id.toLowerCase())) continue;
      if (ID_RE.test(id)) out.add(id);
    }
  }
  return [...out];
}

// ---------- plan
function resolveArgs(root, args, tickets) {
  const byId = new Map(tickets.map((t) => [t.id, t]));
  const ids = [];
  const add = (id) => ids.includes(id) || ids.push(id);
  for (const a of args) {
    if (byId.has(a)) {
      add(a);
      continue;
    }
    const p = path.resolve(a);
    if (fs.existsSync(p) && fs.statSync(p).isFile()) {
      const text = fs.readFileSync(p, "utf8");
      let any = false;
      for (const t of tickets) {
        const re = new RegExp(`(^|[^A-Za-z0-9_-])${t.id.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}($|[^A-Za-z0-9_-])`);
        if (re.test(text)) {
          add(t.id);
          any = true;
        }
      }
      if (!any) throw new Usage(`plan file names no board ticket: ${a}`);
      continue;
    }
    throw new Usage(`not a board ticket id or a plan file: ${a}`);
  }
  if (!ids.length) throw new Usage("plan needs at least one ticket id or plan file");
  return ids.map((id) => byId.get(id));
}

export function buildPlan(root, args) {
  const all = boardTickets(root);
  const picked = resolveArgs(root, args, all);
  const inSet = new Set(picked.map((t) => t.id));
  const stageOf = new Map(all.map((t) => [t.id, t.stage]));
  const info = picked.map((t) => {
    const mandate = fs.existsSync(t.mandate_path ?? "") ? fs.readFileSync(t.mandate_path, "utf8") : "";
    return { id: t.id, files: filesOf(t, root), depends: dependsOf(mandate).filter((d) => d !== t.id) };
  });
  const held = [];
  const unknown = [];
  const live = [];
  const inFlight = all
    .filter((t) => !inSet.has(t.id) && (t.stage === "working" || t.stage === "ready" || (t.stage === "queued" && t.assignment?.session)))
    .map((t) => ({ id: t.id, files: filesOf(t, root) }));
  for (const i of info) {
    const missing = i.depends.filter((d) => !stageOf.has(d));
    if (missing.length) {
      unknown.push({ id: i.id, unknown_ids: missing });
      continue;
    }
    const ext = i.depends.filter((d) => !inSet.has(d) && stageOf.get(d) !== "shipped" && stageOf.get(d) !== "closed");
    const busy = inFlight.map((f) => ({ id: f.id, file: sharedFile(i.files, f.files) })).filter((f) => f.file);
    if (ext.length || busy.length) {
      held.push({ id: i.id, waiting_on: [...ext, ...busy.map((b) => b.id)], ...(busy.length ? { in_flight: busy.map((b) => `${b.id}: ${b.file}`) } : {}) });
    } else live.push(i);
  }
  const unknownIds = new Set(unknown.map((u) => u.id));
  const heldIds = new Set([...held.map((h) => h.id), ...unknownIds]);
  // A ticket depending on a held ticket cannot start either.
  for (let changed = true; changed; ) {
    changed = false;
    for (const i of live) {
      if (heldIds.has(i.id)) continue;
      const w = i.depends.filter((d) => heldIds.has(d));
      if (w.length) {
        held.push({ id: i.id, waiting_on: w });
        heldIds.add(i.id);
        changed = true;
      }
    }
  }
  const items = live.filter((i) => !heldIds.has(i.id));
  const conflicts = [];
  const confl = new Map(items.map((i) => [i.id, new Set()]));
  for (let x = 0; x < items.length; x++) {
    for (let y = x + 1; y < items.length; y++) {
      const a = items[x];
      const b = items[y];
      let why = null;
      if (a.depends.includes(b.id)) why = `${a.id} depends on ${b.id}`;
      else if (b.depends.includes(a.id)) why = `${b.id} depends on ${a.id}`;
      else {
        const f = sharedFile(a.files, b.files);
        if (f) why = `shared file ${f}`;
      }
      if (why) {
        conflicts.push({ a: a.id, b: b.id, why });
        confl.get(a.id).add(b.id);
        confl.get(b.id).add(a.id);
      }
    }
  }
  // Topological placement: a ticket goes in the earliest group after all its dependencies' groups that holds
  // none of its conflicts. Input order breaks ties, so the output is deterministic.
  const groups = [];
  const placed = new Map();
  const left = [...items];
  while (left.length) {
    const next = left.find((i) => i.depends.every((d) => !inSet.has(d) || heldIds.has(d) || placed.has(d)));
    if (!next) {
      const err = new Error(`dependency cycle among: ${left.map((i) => i.id).join(", ")}`);
      err.cycle = true;
      throw err;
    }
    left.splice(left.indexOf(next), 1);
    let g = Math.max(-1, ...next.depends.filter((d) => placed.has(d)).map((d) => placed.get(d))) + 1;
    while (groups[g]?.some((m) => confl.get(next.id).has(m))) g++;
    (groups[g] ??= []).push(next.id);
    placed.set(next.id, g);
  }
  return { groups: groups.filter(Boolean), conflicts, held, unknown };
}

// ---------- cap
function readCaps(root) {
  const a = readJson(path.join(root, ".opencode", "board", "adapter.json"));
  if (!a) throw new Usage("no readable .opencode/board/adapter.json");
  const mp = a.max_parallel ?? {};
  if (typeof mp !== "object" || Array.isArray(mp)) throw new Usage("adapter.json: max_parallel must be an object");
  const caps = { ...DEFAULT_CAPS };
  for (const k of Object.keys(DEFAULT_CAPS)) {
    if (mp[k] === undefined) continue;
    if (k === "build" && mp[k] === "auto") {
      caps[k] = { mode: "auto" }; // dynamic: resolved per `cap` call from a live load sample
      continue;
    }
    if (mp[k] === "auto") throw new Usage(`adapter.json: max_parallel.${k} must be a positive integer or "auto" for build`);
    if (!Number.isInteger(mp[k]) || mp[k] < 1) throw new Usage(`adapter.json: max_parallel.${k} must be a positive integer`);
    caps[k] = mp[k];
  }
  return caps;
}
export function capStatus(root, kind, exclude = []) {
  if (!Object.hasOwn(DEFAULT_CAPS, kind)) throw new Usage(`--kind must be build or train, not "${kind}"`);
  const caps = readCaps(root);
  const cap = caps[kind];
  let max, reason, auto;
  if (kind === "build" && typeof cap === "object" && cap !== null && cap.mode === "auto") {
    auto = true;
    // Point-in-time advisory sample: no hysteresis state, so no 60 s wait. Treat a clear sample as
    // already-sustained (clearSince in the past) so allowed resolves to max immediately.
    const cfg = slotConfig(process.env, undefined);
    const sample = readSample();
    const { allowed, reason: r } = allowedSlots(sample, cfg, { clearSince: Date.now() - 120000 }, Date.now());
    max = allowed;
    reason = r + " (advisory)";
  } else {
    max = cap;
  }
  const tickets = boardTickets(root);
  const running =
    kind === "build"
      ? tickets.filter((t) => t.stage === "working" || (t.stage === "queued" && t.assignment?.session)).length
      : tickets.filter((t) => t.stage === "ready" && !exclude.includes(t.id)).length;
  return { kind, running, max, ok: running < max, ...(auto ? { reason } : {}) };
}

// ---------- status
// One status line / JSON snapshot of the sessions and runs the orchestrator is managing.
// Side-effect-free: no git, no network, no locks; every read fails soft.

const ORCH_HOME = process.env.ORCH_HOME || os.homedir();
const STREAMS_DIR = path.join(ORCH_HOME, ".config", "orchestrator", "streams");

function activeTicket(t) {
  if (t.stage === "working" || t.stage === "ready") return true;
  return t.stage === "queued" && t.assignment && t.assignment.session;
}

/** Walk up from `start` to the first dir holding `.opencode/board/` (no git involved). */
function findBoardRoot(start) {
  let dir = path.resolve(start);
  for (let i = 0; i < 40; i++) {
    try {
      if (fs.statSync(path.join(dir, ".opencode", "board")).isDirectory()) return dir;
    } catch { /* keep walking up */ }
    const parent = path.dirname(dir);
    if (parent === dir) break;
    dir = parent;
  }
  return null;
}

function fmtDurS(s) {
  s = Math.max(0, Math.floor(Number(s ?? 0)));
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  return `${h}h${m % 60 ? `${m % 60}m` : ""}`;
}

function shortAgent(agent) {
  if (!agent) return "";
  return agent.includes("-") ? agent.split("-").pop() : agent;
}

/** Newest mtime (ms) of a run's output files (events log first, then the report itself). */
function outMsOf(run) {
  let best = null;
  for (const p of [`${run.out}.events.jsonl`, run.out]) {
    if (typeof p !== "string") continue;
    try {
      const m = fs.statSync(p).mtimeMs;
      if (best == null || m > best) best = m;
    } catch { /* missing yet */ }
  }
  return best;
}

/** Age in seconds of the last line of a stream's events.jsonl, or null. */
function streamLastAgeS(stream, now) {
  if (!stream) return null;
  const file = path.join(STREAMS_DIR, `${stream}.events.jsonl`);
  try {
    const text = fs.readFileSync(file, "utf8");
    const line = text.split(/\r?\n/).filter(Boolean).pop();
    if (!line) return null;
    const e = JSON.parse(line);
    const t = e && e.at ? Date.parse(e.at) : 0;
    if (Number.isFinite(t) && t > 0) return (now - t) / 1000;
  } catch { return null; }
  return null;
}

/** Full status data, computed in-process (also used by the statusline hook). */
// A ticket is held by session `sid` when the board says so (assignment.session / assignment.owner) or when the
// stream named after the ticket is held by that session. Fails soft: an unreadable stream file is not a match.
function heldBy(t, sid) {
  const a = t.assignment || {};
  if (a.session === sid || a.owner === sid) return true;
  try {
    const f = path.join(STREAMS_DIR, `${t.id}.json`);
    return JSON.parse(fs.readFileSync(f, "utf8")).held_session === sid;
  } catch {
    return false;
  }
}
export function statusData(root, opts = {}) {
  const now = Number.isFinite(opts.now) ? opts.now : Date.now();
  const ticketFilter = opts.ticket;

  // 1. board tickets in an active stage, failing soft
  let tickets = [];
  try {
    tickets = boardTickets(root).filter(activeTicket);
  } catch { tickets = []; }
  if (ticketFilter) tickets = tickets.filter((t) => t.id === ticketFilter);
  const sid = opts.session || null;
  if (sid) tickets = tickets.filter((t) => heldBy(t, sid));

  // counts: `building` reuses capStatus --kind build; `ready` is staged-ready tickets.
  const localBuilding = () => tickets.filter((t) => t.stage === "working" || (t.stage === "queued" && t.assignment?.session)).length;
  let building = 0;
  if (sid) building = localBuilding(); // one session's tickets: the repo-wide cap count would include others'
  else {
    try {
      building = capStatus(root, "build").running;
    } catch {
      building = localBuilding();
    }
  }
  const ready = tickets.filter((t) => t.stage === "ready").length;

  // 2. live oc-worker runs (reuse oc-worker's own active-run reader), failing soft
  let runs = [];
  try {
    runs = activeRuns(now);
  } catch { runs = []; }

  // match runs to tickets: --ticket/board attach (run.session === ticket.assignment.session)
  // or dir === ticket worktree; most recent run wins per ticket
  const runByTicket = new Map();
  for (const run of runs) {
    let matched = null;
    for (const t of tickets) {
      if (run.session && run.session === (t.assignment && t.assignment.session)) { matched = t; break; }
      if (run.dir && run.dir === t.worktree) { matched = t; break; }
    }
    if (!matched) continue;
    const cur = runByTicket.get(matched.id);
    if (!cur || (run.started || 0) > (cur.started || 0)) runByTicket.set(matched.id, run);
  }

  // 3. stream last-event ages (cached per stream), failing soft
  const streamAge = new Map();
  function streamAgeOf(stream) {
    if (!stream) return null;
    if (!streamAge.has(stream)) streamAge.set(stream, streamLastAgeS(stream, now));
    return streamAge.get(stream);
  }

  const ticketRows = [];
  const runSegs = [];
  for (const t of tickets) {
    const run = runByTicket.get(t.id);
    let runObj = null;
    let seg = null;
    if (run) {
      const elapsed_s = Number.isFinite(run.started) ? (now - run.started) / 1000 : null;
      const outMs = outMsOf(run);
      const out_age_s = outMs == null ? null : (now - outMs) / 1000;
      const warn = !run.pidAlive || (out_age_s != null && Number.isInteger(run.idleMin) && run.idleMin > 0 && out_age_s > run.idleMin * 60);
      runObj = {
        pid: run.pid ?? null,
        agent: run.agent ?? null,
        model: run.model ?? null,
        elapsed_s,
        out_age_s,
        alive: Boolean(run.pidAlive),
      };
      seg = `${t.id} ${shortAgent(run.agent)} ${fmtDurS(elapsed_s ?? 0)}${warn ? " ⚠" : ""}`;
      runSegs.push({ elapsed_s: elapsed_s ?? 0, seg });
    }
    ticketRows.push({
      id: t.id,
      stage: t.stage,
      session: (t.assignment && t.assignment.session) || null,
      run: runObj,
      ...(streamAgeOf(t.stream || (t.assignment && t.assignment.stream) || (run && run.stream)) != null
        ? { last_event_age_s: streamAgeOf(t.stream || (t.assignment && t.assignment.stream) || (run && run.stream)) }
        : {}),
    });
  }

  // runs sort by elapsed, most recent last -> descending elapsed
  runSegs.sort((a, b) => b.elapsed_s - a.elapsed_s);

  const counts = { building, ready, runs: sid ? runByTicket.size : runs.length };
  return {
    at: new Date(now).toISOString(),
    tickets: ticketRows,
    counts,
    line: buildLine(building, ready, runSegs.map((r) => r.seg)),
  };
}

function buildLine(building, ready, runSegs) {
  if (building === 0 && ready === 0 && runSegs.length === 0) return "";
  const head = [];
  if (building > 0) head.push(`${building} building`);
  if (ready > 0) head.push(`${ready} ready`);
  let line = `⇉ ${[...head, ...runSegs].join(" · ")}`;
  if (line.length <= 120) return line;
  // Overflow: keep the head and the first N runs, then append ` +K`.
  const kept = [];
  let out = "";
  for (let i = 0; i < runSegs.length; i++) {
    const trial = `⇉ ${[...head, ...kept, runSegs[i]].join(" · ")}`;
    const remaining = runSegs.length - i - 1;
    const candidate = remaining > 0 ? `${trial} +${remaining}` : trial;
    if (candidate.length > 120) break;
    kept.push(runSegs[i]);
    out = candidate;
  }
  return out || line.slice(0, 120);
}

function statusTable(rows) {
  const pad = (s, w) => String(s ?? "").slice(0, w).padEnd(w);
  const lines = [
    `ID${" ".repeat(7)}STAGE   SESSION${" ".repeat(7)}PID   AGENT${" ".repeat(10)}ELAPSED OUT_AGE  ALIVE`,
  ];
  for (const t of rows) {
    const r = t.run;
    lines.push(
      `${pad(t.id, 16)}${pad(t.stage, 9)}${pad(t.session, 16)}${pad(r ? r.pid : "-", 6)}${
        pad(r ? shortAgent(r.agent) : "-", 16)
      }${pad(r ? fmtDurS(r.elapsed_s) : "-", 10)}${pad(r ? fmtDurS(r.out_age_s) : "-", 9)}${r ? (r.alive ? "yes" : "no") : "-"}`
    );
  }
  return lines.join("\n");
}

// ---------- cli
function usage() {
  const src = fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split(/\r?\n/);
  const out = [];
  for (let i = src[0]?.startsWith("#!") ? 1 : 0; i < src.length && src[i].startsWith("//"); i++) out.push(src[i].replace(/^\/\/ ?/, ""));
  return out.join("\n");
}
function parse(argv) {
  const o = { _: [], json: false, line: false, repo: null, ticket: null, kind: "build", exclude: [] };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--json") o.json = true;
    else if (k === "--line") o.line = true;
    else if (k === "--exclude") {
      const v = argv[++i];
      if (v === undefined) throw new Usage("--exclude needs a value");
      o.exclude.push(v);
    } else if (k === "--repo" || k === "--kind" || k === "--ticket" || k === "--session") {
      const v = argv[++i];
      if (v === undefined) throw new Usage(`${k} needs a value`);
      o[k.slice(2)] = v;
    } else if (k.startsWith("--")) throw new Usage(`unknown flag ${k}`);
    else o._.push(k);
  }
  return o;
}
function main(argv) {
  if (!argv.length) {
    console.error(usage());
    return 2;
  }
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log(usage());
    return 0;
  }
  const [cmd, ...rest] = argv;
  const o = parse(rest);
  if (cmd === "plan") {
    const root = repoRoot(o.repo || process.cwd());
    let plan;
    try {
      plan = buildPlan(root, o._);
    } catch (e) {
      if (!e.cycle) throw e;
      console.error(`dispatch: ${e.message}`);
      return 1;
    }
    if (o.json) console.log(JSON.stringify(plan));
    else {
      plan.groups.forEach((g, i) => console.log(`group ${i + 1}: ${g.join(" ")}`));
      for (const c of plan.conflicts) console.log(`serial: ${c.a} / ${c.b} — ${c.why}`);
      for (const h of plan.held) console.log(`held: ${h.id} — waiting on ${h.waiting_on.join(", ")}${h.in_flight ? ` (in flight, shared file: ${h.in_flight.join("; ")})` : ""}`);
      for (const u of plan.unknown) console.log(`unknown: ${u.id} — depends on ids not on the board: ${u.unknown_ids.join(", ")}`);
    }
    return 0;
  }
  if (cmd === "cap") {
    const root = repoRoot(o.repo || process.cwd());
    const s = capStatus(root, o.kind, o.exclude);
    if (o.json) console.log(JSON.stringify(s));
    else if (s.ok) console.log(`ok ${s.kind} ${s.running}/${s.max}`);
    else console.error(`dispatch: cap reached — ${s.kind} ${s.running}/${s.max}`);
    return s.ok ? 0 : 1;
  }
  if (cmd === "status") {
    const root = o.repo ? path.resolve(o.repo) : findBoardRoot(process.cwd());
    const now = Date.now();
    if (!root) {
      if (o.json) console.log(JSON.stringify({ at: new Date(now).toISOString(), tickets: [], counts: { building: 0, ready: 0, runs: 0 } }));
      else if (o.line) { /* empty output */ }
      else console.log("no board found — nothing active");
      return 0;
    }
    const data = statusData(root, { ticket: o.ticket, session: o.session });
    if (o.json) {
      console.log(JSON.stringify({ at: data.at, tickets: data.tickets, counts: data.counts }));
    } else if (o.line) {
      if (data.line) console.log(data.line);
    } else {
      console.log(statusTable(data.tickets));
      console.log(`counts: building ${data.counts.building}, ready ${data.counts.ready}, runs ${data.counts.runs}`);
    }
    return 0;
  }
  throw new Usage(`unknown command "${cmd}"`);
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  try {
    process.exit(main(process.argv.slice(2)));
  } catch (e) {
    console.error(`dispatch: ${e instanceof Error ? e.message : e}`);
    process.exit(2);
  }
}

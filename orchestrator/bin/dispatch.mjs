#!/usr/bin/env node
// Parallel dispatch: which board tickets may run in their own sessions at once, and how many may run.
//
//   node bin/dispatch.mjs plan <ticket-id|plan-file>... [--repo <path>] [--json]
//   node bin/dispatch.mjs cap [--kind build|train] [--exclude <id>]... [--repo <path>] [--json]
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
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { slotConfig, readSample, allowedSlots } from "./slots.mjs";

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
    if (rr && x.startsWith(`${rr}/`)) {
      x = x.slice(rr.length + 1);
      break;
    }
  }
  x = path.posix.normalize(x).replace(/^\.\//, "").replace(/\/+$/, "");
  return x === "." ? "" : x;
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

// ---------- cli
function usage() {
  const src = fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split(/\r?\n/);
  const out = [];
  for (let i = src[0]?.startsWith("#!") ? 1 : 0; i < src.length && src[i].startsWith("//"); i++) out.push(src[i].replace(/^\/\/ ?/, ""));
  return out.join("\n");
}
function parse(argv) {
  const o = { _: [], json: false, repo: null, kind: "build", exclude: [] };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === "--json") o.json = true;
    else if (k === "--exclude") {
      const v = argv[++i];
      if (v === undefined) throw new Usage("--exclude needs a value");
      o.exclude.push(v);
    } else if (k === "--repo" || k === "--kind") {
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
  const root = repoRoot(o.repo || process.cwd());
  if (cmd === "plan") {
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
    const s = capStatus(root, o.kind, o.exclude);
    if (o.json) console.log(JSON.stringify(s));
    else if (s.ok) console.log(`ok ${s.kind} ${s.running}/${s.max}`);
    else console.error(`dispatch: cap reached — ${s.kind} ${s.running}/${s.max}`);
    return s.ok ? 0 : 1;
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

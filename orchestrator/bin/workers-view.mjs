#!/usr/bin/env node
// workers-view — one read-only look at the headless workers: which runs are alive, which ticket each serves,
// which tickets are held and why, and which `working` tickets have no live run.
//
//   node bin/workers-view.mjs [--json | --html <path> [--watch <sec>]] [--repo <path>]
//
// Data (each child CLI via spawnSync, 10 s timeout; a failing child degrades only its own section):
//   runs     oc-worker.mjs active --json   (states verbatim from activeRuns(): RUNNING STARTING QUIET ...)
//   tickets  board.mjs status --json       (+ .opencode/board/tickets/<id>.json for assignment.worker, which the
//                                           status row does not carry; board.mjs exports nothing)
//   held     dispatch.mjs plan <queued ids> (parses its `held:` lines)
//   pace     cc-pace.mjs, only when that file exists
// Join run -> ticket on assignment.worker.pid or out_path against the run's pid / out. The title is not a key.
// Test hooks: WV_OCW_CLI, WV_BOARD_CLI, WV_DISPATCH_CLI, WV_PACE_CLI replace the child scripts.
import fs from "node:fs";
import path from "node:path";
import { spawnSync, execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
// Each child gets at most CHILD_TIMEOUT_MS, and the whole collect() stays inside BUDGET_MS (under the mod's 12 s kill),
// so one hung child degrades its own section and the others still answer.
const CHILD_TIMEOUT_MS = Number(process.env.WV_CHILD_TIMEOUT_MS) || 10_000;
const BUDGET_MS = Number(process.env.WV_BUDGET_MS) || 9_000;
let deadline = Infinity;
const NA = "—";

const script = (env, name) => process.env[env] || path.join(HERE, name);

function runChild(file, args, cwd) {
  const timeout = Math.min(CHILD_TIMEOUT_MS, deadline - Date.now());
  if (timeout <= 0) throw new Error("no time left in the overall budget");
  const r = spawnSync(process.execPath, [file, ...args], { cwd, encoding: "utf8", timeout, killSignal: "SIGKILL", windowsHide: true });
  if (r.error) throw new Error(r.error.code === "ETIMEDOUT" ? `timed out after ${Math.round(timeout / 100) / 10}s` : r.error.message);
  if (r.status !== 0) throw new Error(`exit ${r.status}${r.stderr ? `: ${r.stderr.trim().slice(0, 120)}` : ""}`);
  return r.stdout;
}

function boardRoot(dir) {
  try {
    const c = execFileSync("git", ["-C", dir, "rev-parse", "--path-format=absolute", "--git-common-dir"], {
      encoding: "utf8", stdio: ["ignore", "pipe", "ignore"], timeout: CHILD_TIMEOUT_MS,
    }).trim();
    return path.dirname(c);
  } catch {
    return dir;
  }
}

export const roundOf = (out) => {
  const m = /-r(\d+)\.[^./\\]+$/.exec(path.basename(String(out || "")));
  return m ? Number(m[1]) : null;
};
const sessionLink = (s) => (typeof s === "string" && s.startsWith("local_") ? `claude://claude.ai/epitaxy/${s}` : null);
const norm = (p) => (p ? path.resolve(String(p)) : null);

function readWorker(root, id) {
  try {
    const t = JSON.parse(fs.readFileSync(path.join(root, ".opencode", "board", "tickets", `${id}.json`), "utf8"));
    return t?.assignment?.worker ?? null;
  } catch {
    return null;
  }
}

export function collect({ repo = process.cwd() } = {}) {
  const errors = {};
  deadline = Date.now() + BUDGET_MS;
  const root = boardRoot(repo);

  let runs = null;
  try {
    runs = JSON.parse(runChild(script("WV_OCW_CLI", "oc-worker.mjs"), ["active", "--json"], repo));
    if (!Array.isArray(runs)) throw new Error("not a list");
  } catch (e) {
    errors.runs = e.message;
  }

  let tickets = null;
  try {
    tickets = JSON.parse(runChild(script("WV_BOARD_CLI", "board.mjs"), ["status", "--json"], repo));
    if (!Array.isArray(tickets)) throw new Error("not a list");
    tickets = tickets.map((t) => ({ ...t, worker: readWorker(root, t.id) }));
  } catch (e) {
    errors.board = e.message;
    tickets = null;
  }

  const byPid = new Map();
  const byOut = new Map();
  // Several tickets may carry the same pid/out (a recycled pid on a stale ticket): a `working` ticket wins.
  const put = (m, k, t) => {
    const old = m.get(k);
    if (!old || old.stage !== "working" || t.stage === "working") m.set(k, t);
  };
  for (const t of tickets ?? []) {
    if (Number.isInteger(t.worker?.pid)) put(byPid, t.worker.pid, t);
    if (t.worker?.out_path) put(byOut, norm(t.worker.out_path), t);
  }
  const matched = new Set();
  const runRows = (runs ?? []).map((r) => {
    const t = (Number.isInteger(r.pid) && byPid.get(r.pid)) || (r.out && byOut.get(norm(r.out))) || null;
    if (t) matched.add(t.id);
    return {
      state: r.state,
      agent: r.agent ?? null,
      ticket: t ? t.id : null,
      round: roundOf(r.out),
      elapsed: r.elapsed ?? null,
      out_age: r.outAge ?? null,
      detail: r.detail || null,
      pid: r.pid ?? null,
      stream: r.stream ?? null,
      title: r.title ?? null,
      session: t?.session ?? r.session ?? null,
      session_link: sessionLink(t?.session ?? r.session),
    };
  });

  // The statusline hook deletes dead registry files, so a dead worker is seen from the board side only.
  const noRun = (tickets ?? [])
    .filter((t) => t.stage === "working" && !matched.has(t.id))
    .map((t) => ({ ticket: t.id, state: "NO LIVE RUN", owner: t.owner ?? null, session: t.session ?? null, session_link: sessionLink(t.session) }));

  let held = null;
  const queued = (tickets ?? []).filter((t) => t.stage === "queued").map((t) => t.id);
  if (queued.length) {
    try {
      held = runChild(script("WV_DISPATCH_CLI", "dispatch.mjs"), ["plan", ...queued, "--repo", root], repo)
        .split("\n")
        .filter((l) => l.startsWith("held:"))
        .map((l) => l.slice(5).trim());
    } catch (e) {
      errors.held = e.message;
      held = "unavailable";
    }
  } else if (tickets) held = [];

  let pace = null;
  const paceCli = script("WV_PACE_CLI", "cc-pace.mjs");
  if (fs.existsSync(paceCli)) {
    try {
      pace = runChild(paceCli, [], repo).trim().split("\n")[0] || null;
    } catch (e) {
      errors.pace = e.message;
    }
  }

  return { generated: new Date().toISOString(), runs: runs ? runRows : null, no_live_run: tickets ? noRun : null, held, pace, errors };
}

const cell = (v) => (v == null || v === "" ? NA : String(v));

export function renderText(d) {
  const out = [];
  if (d.pace) out.push(`pace: ${d.pace}`);
  if (d.runs == null) out.push(`runs: unavailable (${d.errors.runs})`);
  else if (!d.runs.length) out.push("no live runs");
  else {
    out.push(["STATE", "AGENT", "TICKET", "RND", "ELAPSED", "OUT", "PID", "SESSION"].join("\t"));
    for (const r of d.runs) {
      out.push([r.state, r.agent, r.ticket, r.round, r.elapsed, r.out_age ?? "none yet", r.pid, r.session_link].map(cell).join("\t") + (r.detail ? `  (${r.detail})` : ""));
    }
  }
  if (d.no_live_run == null) out.push(`tickets: unavailable (${d.errors.board})`);
  for (const n of d.no_live_run ?? []) out.push(`NO LIVE RUN\t${n.ticket}\towner ${cell(n.owner)}\t${cell(n.session_link)}`);
  if (d.held === "unavailable") out.push("held: unavailable");
  else for (const h of d.held ?? []) out.push(`held: ${h}`);
  return out.join("\n");
}

const esc = (s) => String(s).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);

export function renderHtml(d, refreshSec = 15) {
  return `<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="refresh" content="${Number(refreshSec) || 15}">
<title>workers</title><style>body{font:14px monospace;margin:1em}pre{white-space:pre-wrap}</style></head>
<body><h3>Workers <small>${esc(d.generated)}</small></h3><pre>${esc(renderText(d))}</pre></body></html>
`;
}

function main(argv) {
  const o = { json: false, html: null, watch: null, repo: process.cwd() };
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--json") o.json = true;
    else if (a === "--html") o.html = argv[++i];
    else if (a === "--watch") o.watch = Number(argv[++i]);
    else if (a === "--repo") o.repo = argv[++i];
    else {
      console.error(`workers-view: unknown argument ${a}`);
      return 2;
    }
  }
  if (o.html === undefined || o.html === "") {
    console.error("workers-view: --html needs a path");
    return 2;
  }
  if (o.html) {
    const write = () => {
      const tmp = `${o.html}.tmp`;
      fs.writeFileSync(tmp, renderHtml(collect(o), o.watch || 15));
      fs.renameSync(tmp, o.html);
    };
    write();
    // A failed refresh is logged and the watcher keeps going.
    const safeWrite = () => {
      try {
        write();
      } catch (e) {
        console.error(`workers-view: ${e.message}`);
      }
    };
    if (o.watch > 0) setInterval(safeWrite, o.watch * 1000);
    else return 0;
    return null; // keep running
  }
  const d = collect(o);
  console.log(o.json ? JSON.stringify(d, null, 2) : renderText(d));
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const code = main(process.argv.slice(2));
  if (code !== null) process.exit(code);
}

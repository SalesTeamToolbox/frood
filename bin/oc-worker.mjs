#!/usr/bin/env node
// Launch one headless OpenCode agent run (worker, critic, scout, senior, ...) and record what it did.
//
//   node oc-worker.mjs --agent worker --dir <worktree> --prompt <mandate.md>
//        [--out <final-message.md>] [--session <ses_id>] [--model <provider/model>]
//        [--ticket <id> --owner <session>]
//        [--stream <name>] [--title <text>] [--timeout-min 30] [--idle-min 20] [--resume 1] [--slots 2] [--fallback <agent>[,<agent>]] [--report <path>]
//   node oc-worker.mjs --help   (or -h) prints this text and exits 0; nothing is launched
//   node oc-worker.mjs active [--json]   list running headless runs with elapsed time, last-output
//      age and watchdog limits (idle-min / timeout-min). STALE = wrapper pid gone; OVERDUE = past its
//      timeout budget but still alive; HEARTBEAT-STALE = wrapper alive but not ticking; QUIET = silent
//      past its idle limit; STARTING = no output yet. Read-only; exits 0.
//
// - Runs `opencode run --format json --auto --agent <agent>` with cwd=<dir> and stdin closed
//   (an open stdin makes `opencode run` wait forever).
// - The prompt file's text is the message. A footer tells the agent it cannot ask questions:
//   it must finish with `RESULT: BLOCKED: question — ...` instead.
// - --session resumes the same agent session (revision rounds keep the worker's context).
// - --fallback: when a run dies on a provider quota/rate limit or "model unavailable" before producing any
//   text (e.g. Go weekly limit), that model is marked down in ~/.config/orchestrator/pool-health.json (until
//   the provider's retry-after) and the next agent in the list runs; later runs skip known-down models
//   without calling them. Max 3 real attempts. The receipt records every hop and skip.
// - Machine-wide WORKER_SLOTS cap (default 2): waits for a free slot (lock dirs under
//   ~/.config/orchestrator/slots, stale when the owning pid is gone).
// - --ticket <id> --owner <session>: the ticket names an OpenCode board ticket; before anything is launched this
//   runs `node <board.mjs> attach <id> --pid <this pid> --out <out>` (execFileSync, no shell), which the board
//   refuses unless the ticket is working, owned by --owner and past its EGM gate. A refusal exits 7 with nothing
//   launched and no slot taken.
// - Writes <out> (the agent's final text), <out>.events.jsonl (raw events), <out>.receipt.json
//   ({agent, model, session, exit, seconds, tokens, cost, first_line}); model is the pinned model of the agent
//   when --model was not given. Prints the receipt JSON.
// - --idle-min <n> (default 20, 0 disables): kills a run whose stdout has been silent for n minutes (a sleeping host
//   never counts). Receipt exit "stalled", status 4, partial output kept like a timeout. Receipt max_silence_s is the
//   longest stdout silence seen, for tuning the default.
// - --resume <n> (default 1, 0 disables): a run that dropped (ECONNRESET, socket hang up, ...), stalled, or died
//   mid-run on a transient pool error (quota/rate-limit, provider 5xx/overload) after producing output and a session
//   id is resumed with --session after 30 s (ORCH_RESUME_WAIT_MS), inside the same slot: the manual "nudge it along",
//   automatic. Deterministic failures (unknown/retired model, not-in-plan) and clean finishes never resume.
//   --timeout-min is one wall-clock budget for all attempts together. Receipt: resumed [{session, reason,
//   seconds}] and attempts (spawns). On a resumed run, errors, first_line and verdict come from the last attempt only;
//   tokens and cost are summed. stderr is always listed in errors but counts as pool-health evidence only when the
//   run did not finish cleanly (exit 0 with a final message). A stalled run exits 4 like a timeout.
// - After every attempt (finished, failed, timeout, stall) the run's leftover descendants are killed (bin/proc-tree.mjs: the
//   process table is sampled while opencode runs; a child whose parent died is still swept). Receipt orphans_killed
//   [{pid, cmd}] appears only when something was killed. ORCH_NO_PROCTREE=1 disables.
// - --stream <name>: report this run to a desk stream (bin/handoff.mjs). The stream must exist (exit 2) and --out must be
//   fresh: if <out> or <out>.receipt.json exists the run is refused (exit 2). Before a slot is taken a `queued` event
//   (pid, pid start, agent, ticket.json path) is appended to the stream; exit 9 (nothing launched) if that run is
//   already queued. When the run ends (any status) one `run-done` event {agent, exit, outcome, session} is appended.
//   The run id, and so every key, is `<ticket>/<run>`: `<ticket>` is the `ticket` string of dirname(--out)/ticket.json
//   (the run dir's basename when that file is missing or has no string `ticket`), `<run>` is the --out basename without
//   its extension — e.g. `run:m6a-desk-minors/worker-r1:queued`. One stream therefore carries many tickets without
//   their worker-r1 keys colliding; exit 9 still means this exact run id is already queued.
//   Event write failures go to stderr and never change the run's status. Without --stream no stream file is touched.
// Exit: 0 finished, 3 no final text, 4 timeout, 5 opencode error, 6 every pool in the chain known-down, 7 board
// attach refused (--ticket), 8 model not allowed by provider policy (`ignored`; unreadable providers.json; model unresolvable while any provider is restricted; `free-only`
// and not on the allowlist).
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { gate } from "./verdict-gate.mjs";
import { watch, processStart } from "./proc-tree.mjs";
import { diff, homeDir } from "../ops/install.mjs"; // install.mjs is vendored at ops/install.mjs (M3: repo-local, no ~/ paths)
import { agentModel, classify, isDown, isPolicyFree, markDown, markUp, modelAllowed, policyReason, providerOf, hasRestrictivePolicy } from "./pool-health.mjs";
import crypto from "node:crypto";
import { appendEvent, atomicWrite, streamsDir } from "./handoff.mjs";
import { workerOutcome } from "./outcome.mjs";

export const FOOTER = `

---
Run constraints (from the orchestrator):
- You are running headless. Nobody can answer questions mid-run. If you cannot proceed without a decision,
  stop and make your final message start with: RESULT: BLOCKED: question — <one specific question>
- Stay inside the working directory you were started in. Never push, merge, deploy, or touch other worktrees.
- Your final message is saved verbatim for the orchestrator. Make its first line the status line your role defines
  (RESULT: ... for workers, VERDICT: ... for critics).`;

export const READONLY_AGENT_RE = /^(critic|senior|scout|explorer)(-|$)/;

// Usage is the header comment block of this file, so it cannot drift out of date.
export function usage() {
  const src = fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split(/\r?\n/);
  const out = [];
  for (let i = src[0]?.startsWith("#!") ? 1 : 0; i < src.length && src[i].startsWith("//"); i++) {
    out.push(src[i].replace(/^\/\/ ?/, ""));
  }
  return out.join("\n");
}

function args(argv) {
  const a = { timeoutMin: 30, idleMin: 20, resume: 1, slots: Number(process.env.WORKER_SLOTS || 2) };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    const v = () => argv[++i];
    if (k === "--agent") a.agent = v();
    else if (k === "--dir") a.dir = v();
    else if (k === "--prompt") a.prompt = v();
    else if (k === "--out") a.out = v();
    else if (k === "--session") a.session = v();
    else if (k === "--model") a.model = v();
    else if (k === "--ticket") a.ticket = v();
    else if (k === "--owner") a.owner = v();
    else if (k === "--stream") a.stream = v();
    else if (k === "--title") a.title = v();
    else if (k === "--report") a.report = v();
    else if (k === "--timeout-min") a.timeoutMin = Number(v());
    else if (k === "--idle-min") a.idleMin = Number(v());
    else if (k === "--resume") a.resume = Number(v());
    else if (k === "--slots") a.slots = Number(v());
    else if (k === "--fallback") a.fallback = v().split(",").map((x) => x.trim()).filter(Boolean).slice(0, 8); // skips are free; real calls stay capped at 3
    else throw new Error(`unknown flag ${k}`);
  }
  for (const req of ["agent", "dir", "prompt"]) if (!a[req]) throw new Error(`--${req} is required`);
  if (a.ticket && !a.owner) throw new Error("--ticket needs --owner");
  a.out ||= path.join(path.dirname(path.resolve(a.prompt)), `${a.agent}-out.md`);
  return a;
}

export function opencodeBin() {
  const env = process.env.OPENCODE_BIN;
  if (env && /\.m?js$/.test(env)) return { cmd: process.execPath, pre: [env], shell: false }; // tests: fake opencode
  if (env) return { cmd: env, shell: false };
  const exe = path.join(process.env.APPDATA || "", "npm", "node_modules", "@opencode", "cli", "bin", "opencode.exe");
  if (process.platform === "win32") {
    if (fs.existsSync(exe)) return { cmd: exe, shell: false };
    // Never fall back to `opencode.cmd` via a shell: the Mandate travels in argv and cmd.exe would interpret it.
    throw new Error(`opencode.exe not found at ${exe}; set OPENCODE_BIN to the real opencode.exe`);
  }
  return { cmd: "opencode", shell: false };
}

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
}

// Extra env for worker runs comes from <state>/worker-env.json: { "VAR": "value" }.
// Some MCP servers keep a locked dir under the session cwd unless told otherwise, which breaks
// `git worktree remove`; pointing them at a shared dir outside any repo is a config concern, not
// this script's. A var is set only when the environment does not already define it; "{state}"
// expands to the orchestrator state dir (<ORCH_HOME or home>/.config/orchestrator) and a value
// written as "{state}/..." is created as a directory. Missing/invalid file: env unchanged.
export function workerEnv(env = process.env) {
  const out = { ...env };
  const state = path.join(env.ORCH_HOME || os.homedir(), ".config", "orchestrator");
  let cfg;
  try {
    cfg = JSON.parse(fs.readFileSync(path.join(state, "worker-env.json"), "utf8"));
  } catch {
    return out;
  }
  if (!cfg || typeof cfg !== "object" || Array.isArray(cfg)) return out;
  for (const [k, v] of Object.entries(cfg)) {
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(k) || typeof v !== "string") continue;
    if (out[k] !== undefined && out[k] !== "") continue; // explicit (non-empty) env wins
    // {state}/x on Windows must come out as a real path (mixed separators confuse some tools).
    const value = v.includes("{state}") ? path.normalize(v.replaceAll("{state}", state)) : v;
    out[k] = value;
    if (v.startsWith("{state}/")) fs.mkdirSync(value, { recursive: true });
  }
  return out;
}

export function slotDir() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "slots");
}

// mkdir is atomic: the first claimant of slot-N wins. A slot whose owner pid is dead is reclaimed.
export async function acquireSlot(n, { pollMs = 3000, deadline = Infinity, pid = process.pid } = {}) {
  fs.mkdirSync(slotDir(), { recursive: true });
  for (;;) {
    for (let i = 1; i <= n; i++) {
      const d = path.join(slotDir(), `slot-${i}`);
      try {
        fs.mkdirSync(d);
        fs.writeFileSync(path.join(d, "owner"), JSON.stringify({ pid, since: new Date().toISOString() }));
        return () => fs.rmSync(d, { recursive: true, force: true });
      } catch {
        let owner = null;
        try {
          owner = JSON.parse(fs.readFileSync(path.join(d, "owner"), "utf8"));
        } catch {}
        const age = Date.now() - fs.statSync(d).mtimeMs;
        if ((owner && !alive(owner.pid)) || (!owner && age > 60000)) fs.rmSync(d, { recursive: true, force: true });
      }
    }
    if (Date.now() > deadline) throw new Error(`no free worker slot (WORKER_SLOTS=${n})`);
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

function killTree(child) {
  if (process.platform === "win32") {
    try {
      execFileSync("taskkill", ["/PID", String(child.pid), "/T", "/F"], { stdio: "ignore" });
    } catch {}
  } else {
    try {
      process.kill(-child.pid, "SIGKILL"); // opencode runs detached, so it leads its own process group
    } catch {
      try {
        child.kill("SIGKILL");
      } catch {}
    }
  }
}

// Fold the JSON event stream into the final text, session, tokens and cost.
export function summarize(lines) {
  const s = { session: null, texts: new Map(), lastMessage: null, tokens: { input: 0, output: 0, reasoning: 0, cache_read: 0 }, cost: 0, errors: [] };
  for (const line of lines) {
    let e;
    try {
      e = JSON.parse(line);
    } catch {
      continue;
    }
    s.session ||= e.sessionID || e.part?.sessionID || null;
    const p = e.part || {};
    if (e.type === "text" && p.text != null) {
      s.lastMessage = p.messageID;
      const list = s.texts.get(p.messageID) || [];
      list.push(p.text);
      s.texts.set(p.messageID, list);
    }
    if (e.type === "step_finish") {
      s.cost += p.cost || 0;
      const t = p.tokens || {};
      s.tokens.input += t.input || 0;
      s.tokens.output += t.output || 0;
      s.tokens.reasoning += t.reasoning || 0;
      s.tokens.cache_read += t.cache?.read || 0;
    }
    if (e.type === "error") s.errors.push(JSON.stringify(e.error || e).slice(0, 500));
  }
  const final = s.lastMessage ? s.texts.get(s.lastMessage).join("") : "";
  // Everything the agent said, in order — kept so a timeout does not throw away its findings.
  const all = [...s.texts.values()].map((parts) => parts.join("")).join("\n\n");
  return { session: s.session, final, all, tokens: s.tokens, cost: Number(s.cost.toFixed(6)), errors: s.errors };
}

export function statusLine(text) {
  const m = String(text || "").match(/^\s*((?:RESULT|VERDICT):.*)$/m);
  return m ? m[1].trim().slice(0, 200) : "";
}

function readText(p) {
  try {
    return fs.readFileSync(p, "utf8");
  } catch {
    return "";
  }
}

export function opencodeDb() {
  return process.env.ORCH_OPENCODE_DB || path.join(os.homedir(), ".local", "share", "opencode", "opencode.db");
}

// Cost + routed model of a session and every subagent session under it, read-only from OpenCode's db.
// Returns null when the db or table is unavailable (never fails a run over bookkeeping).
export function sessionTree(rootId, dbPath = opencodeDb()) {
  if (!fs.existsSync(dbPath)) return null;
  let db;
  try {
    process.emitWarning = () => {}; // node:sqlite ExperimentalWarning
    const { DatabaseSync } = globalThis.__orchSqlite || (globalThis.__orchSqlite = requireSqlite());
    db = new DatabaseSync(dbPath, { readOnly: true });
    const one = db.prepare("SELECT id, agent, model, cost, tokens_input, tokens_output FROM session_v2 WHERE id = ?");
    const kids = db.prepare("SELECT id FROM session_v2 WHERE parent_id = ?");
    const sessions = [];
    const walk = (id, depth) => {
      const s = one.get(id);
      if (!s || depth > 5) return;
      let model = s.model;
      try {
        const m = JSON.parse(s.model);
        model = `${m.providerID}/${m.id}`;
      } catch {}
      sessions.push({ id: s.id, agent: s.agent, model, cost: Number((s.cost || 0).toFixed(6)), tokens_in: s.tokens_input, tokens_out: s.tokens_output, depth });
      for (const k of kids.all(id)) walk(k.id, depth + 1);
    };
    walk(rootId, 0);
    if (!sessions.length) return null;
    return { total_cost: Number(sessions.reduce((t, s) => t + s.cost, 0).toFixed(6)), sessions };
  } catch {
    return null;
  } finally {
    try {
      db?.close();
    } catch {}
  }
}

function requireSqlite() {
  // node:sqlite via createRequire keeps this module loadable on Node builds where the import would throw
  return createRequire(import.meta.url)("node:sqlite");
}

// A provider quota/rate-limit error with no output yet is worth re-pooling (see runChain below).
// A mid-run pool-side failure (dropped connection, quota/rate-limit, provider 5xx/overload) is worth
// one automatic resume with --session: the manual "nudge it along", for any model on any pool.
// Deterministic failures (unknown/retired model, not-in-plan) and clean finishes never resume.
export function isQuotaError(receipt) {
  return !receipt.first_line && receipt.errors.some((e) => /limit|quota|429|rate.?limit|insufficient|credit/i.test(e));
}

/** Classify-and-decide for the resume gate above: only transient pool-side failures. */
export function resumableReason(errors) {
  const r = classify(errors)?.reason;
  return r === "dropped" || r === "quota" || r === "provider-error" ? r : null;
}

// A refused board attach (--ticket): nothing was launched, so it is not an opencode error.
export class AttachRefused extends Error {}
// `oc-worker --ticket`: the board is the ticket's truth, so the run registers itself on the ticket before it
// starts. execFileSync with an argv array and no shell (design B11); it runs before a slot is taken, so a refused
// ticket launches nothing and consumes no capacity.
export function attachTicket(a) {
  const board = path.join(path.dirname(fileURLToPath(import.meta.url)), "board.mjs");
  const argv = [
    board,
    "attach",
    a.ticket,
    "--repo",
    path.resolve(a.dir),
    "--owner",
    a.owner,
    "--pid",
    String(process.pid),
    "--out",
    path.resolve(a.out),
  ];
  try {
    execFileSync(process.execPath, argv, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], windowsHide: true });
  } catch (e) {
    const why = String(e.stderr || e.message || "").trim() || "board attach failed";
    throw new AttachRefused(`--ticket ${a.ticket}: ${why}`);
  }
}

// Walk [agent, ...fallback]. Known-down pools (pool-health) are skipped without a call; a run that dies on
// a quota/unavailable error before any output marks its model down and moves on. Max 3 real attempts.
export async function runWithFallback(a) {
  if (!a.stream) return runChain(a);
  streamPreflight(a);
  let r;
  try {
    r = await runChain(a);
  } catch (e) {
    // a throw after `queued` (attach refused, bad --dir, ...) still ends the run exactly once
    streamEvent(a, doneEvent(a, { agent: a.agent, exit: "error", session: null, first_line: "", out: null }));
    throw e;
  }
  streamEvent(a, doneEvent(a, r)); // once per invocation, after the final receipt, for every status
  return r;
}

export class StreamRefused extends Error {
  constructor(msg, code) {
    super(msg);
    this.code = code;
  }
}

// The ticket a run belongs to: the `ticket` string of dirname(--out)/ticket.json (written once by /orchestrator before
// the first dispatch), else the run directory's basename when that file is missing, unreadable or has no string ticket.
function ticketIdOf(out) {
  const dir = path.dirname(path.resolve(out));
  try {
    const t = JSON.parse(fs.readFileSync(path.join(dir, "ticket.json"), "utf8"));
    if (t && typeof t === "object" && typeof t.ticket === "string" && t.ticket) return t.ticket;
  } catch {
    // missing, unreadable or not JSON: the directory name still tells two tickets apart
  }
  return path.basename(dir);
}

// A run's id is `<ticket>/<out basename without extension>`. The stream dedupes events by key, so the ticket has to be
// part of it: two tickets' `worker-r1` on one stream must both get a `queued` event. bin/desk.mjs derives the same id
// for resume effects; legacy un-prefixed ids already in a stream keep stepping (the desk reads the key as written).
const runName = (a) => `${ticketIdOf(a.out)}/${path.basename(a.out, path.extname(a.out))}`;

// --stream checks and the `queued` event, before attachTicket and before any slot is taken.
function streamPreflight(a) {
  const stream = a.stream;
  if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(stream) || !fs.existsSync(path.join(streamsDir(), `${stream}.json`))) throw new StreamRefused(`no stream ${stream}`, 2);
  const out = path.resolve(a.out);
  if (fs.existsSync(out) || fs.existsSync(out + ".receipt.json")) throw new StreamRefused("out exists — use a fresh --out per run", 2);
  const run = runName(a);
  const ev = { key: `run:${run}:queued`, kind: "queued", run, out, pid: process.pid, pid_start: processStart(process.pid), agent: a.agent, ticket: path.join(path.dirname(out), "ticket.json") };
  let added;
  try {
    added = appendEvent(stream, ev);
  } catch (e) {
    console.error(`oc-worker: stream event failed: ${e.message}`); // O6: never changes the run
    return;
  }
  if (added === false) throw new StreamRefused(`run ${run} already queued`, 9);
}

function doneEvent(a, r) {
  const run = runName(a);
  let outcome = "error";
  try {
    outcome = workerOutcome(r);
  } catch {}
  return { key: `run:${run}:done`, kind: "run-done", run, out: path.resolve(a.out), agent: r.agent ?? a.agent, exit: r.exit, outcome, session: r.session ?? null };
}

function streamEvent(a, ev) {
  try {
    appendEvent(a.stream, ev);
  } catch (e) {
    console.error(`oc-worker: stream event failed: ${e.message}`);
  }
}

async function runChain(a) {
  if (a.ticket) attachTicket(a); // no ticket, no run: this is the only gate between the board and a launch
  const chain = [a.agent, ...(a.fallback || [])];
  const hops = [];
  let r = null;
  let attempts = 0;
  for (let i = 0; i < chain.length && attempts < 3; i++) {
    const agent = chain[i];
    const first = i === 0;
    const model = (first && a.model) || agentModel(agent);
    if (model && !modelAllowed(model)) {
      hops.push({ agent, model, skipped: true, reason: policyReason(model) });
      continue;
    }
    const down = isDown(model);
    if (down) {
      hops.push({ agent, model, skipped: true, reason: `${down.reason} until ${down.until}` });
      continue;
    }
    attempts++;
    // a new pool means a new session; a resumed session belongs to the first pool only
    r = await runWorker(first ? a : { ...a, agent, session: undefined, model: undefined });
    attempts += (r.attempts ?? 1) - 1; // cap 3 counts spawns: a resumed run used more than one
    const anyCls = classify(r.classifyErrors ?? r.errors);
    // A pool that died mid-run (output already produced) is still down for the next run.
    if (anyCls && r.first_line) markDown(model, { ...anyCls, detail: r.errors[0] || "" });
    const cls = !r.first_line ? anyCls : null;
    if (!cls) {
      if (r.first_line && !anyCls) markUp(model);
      break;
    }
    markDown(model, { ...cls, detail: r.errors[0] || "" });
    if (i === chain.length - 1) break; // nothing left to move to: this failure is the result
    hops.push({ agent, model, session: r.session, error: (r.errors[0] || "").slice(0, 200) });
  }
  if (!r && hops.every((h) => /^policy:/.test(h.reason))) {
    const m = hops[0]?.model || a.model || agentModel(a.agent);
    r = notAllowedReceipt(a, m);
  }
  if (!r) {
    // every pool in the chain is known-down: fail fast, no calls made
    r = { agent: a.agent, model: a.model || agentModel(a.agent) || "(agent default)", session: null, exit: "no-healthy-pool", seconds: 0, tokens: null, cost: 0, first_line: "", verdict: null, out: null, partial: false, errors: ["every agent in the chain is known-down (pool-health); run router-health or wait"], status: 6 };
  }
  if (hops.length) r.repooled_from = hops;
  if (hops.length || r.status === 6 || r.status === 8) {
    fs.mkdirSync(path.dirname(path.resolve(a.out)), { recursive: true });
    atomicWrite(path.resolve(a.out) + ".receipt.json", JSON.stringify({ ...r, status: undefined }, null, 2) + "\n");
  }
  return r;
}

export function notAllowedReceipt(a, model) {
  const why = policyReason(model);
  const msg = why === "policy: providers.json unreadable" ? `model ${model} not allowed: providers.json unreadable (failing closed)` : `model ${model} not allowed: provider ${providerOf(model)} is ${why.replace("policy: ", "")}`;
  return { agent: a.agent, model, session: null, exit: "model-not-allowed", seconds: 0, tokens: null, cost: 0, first_line: "", verdict: null, out: null, partial: false, errors: [msg], status: 8 };
}

function unresolvableReceipt(a) {
  return { agent: a.agent, model: null, session: null, exit: "model-unresolvable", seconds: 0, tokens: null, cost: 0, first_line: "", verdict: null, out: null, partial: false, errors: [`model unresolvable for agent ${a.agent}: pin a model in its agent file`], status: 8 };
}

export async function runWorker(a) {
  const dir = path.resolve(a.dir);
  if (!fs.existsSync(dir)) throw new Error(`--dir does not exist: ${dir}`);
  // The model the receipt records is the one that actually runs: --model, else the agent's pinned model. The
  // board reads this to decide whether a review was paid (a receipt no longer says "(agent default)").
  const wanted = a.model || agentModel(a.agent);
  if (!wanted && hasRestrictivePolicy()) return unresolvableReceipt(a); // policy cannot be checked without a model
  if (wanted && !modelAllowed(wanted)) return notAllowedReceipt(a, wanted); // before a slot is taken or opencode started
  const model = wanted || "(agent default)";
  const bin = opencodeBin();
  const title = a.title || `orch ${a.agent} ${path.basename(dir)}`;
  // A message that starts with "-" (YAML front-matter) would be parsed by `opencode run` as a flag.
  const safe = (m) => (m.startsWith("-") ? "\n" + m : m);

  const promptText = fs.readFileSync(a.prompt, "utf8"); // before the slot: a bad --prompt must not leak a slot, registry entry or timer
  const release = await acquireSlot(a.slots);
  const started = Date.now();
  const deadline = started + a.timeoutMin * 60000; // one wall-clock budget for every attempt together
  const out = path.resolve(a.out);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  // Live registry for the dashboard: one file per running oc-worker, removed when it ends.
  const run = registerRun({ agent: a.agent, model, title, dir, out, started, idleMin: a.idleMin, timeoutMin: a.timeoutMin, stream: a.stream ?? null, session: a.session ?? null });
  const kickTimer = setInterval(() => run.touch(), 20_000);
  const events = fs.createWriteStream(out + ".events.jsonl"); // appended across attempts
  const idleMin = a.idleMin ?? 20;
  const resumeMax = a.resume ?? 1;

  // Read-only guard: prepare scratch dir and footer before first attempt
  let isReadOnly = READONLY_AGENT_RE.test(a.agent) && !process.env.ORCH_NO_READONLY_GUARD;
  const guardErrors = []; // guard failures never change the run outcome; they only add error lines
  let preDiff = null;
  let wtHeadBefore = null;
  let wtStatusBefore = null;
  let scratchDir = null;
  let readonlyFooter = "";
  if (isReadOnly) {
    try {
      scratchDir = path.join(os.tmpdir(), `orch-scratch-${process.pid}-${Date.now()}`);
      fs.mkdirSync(scratchDir, { recursive: true });
    } catch (e) {
      guardErrors.push(`readonly guard skipped: ${e.message}`);
      scratchDir = null;
      isReadOnly = false;
    }
  }
  if (isReadOnly) {
    readonlyFooter = `\n- You are a read-only role. Do not create, modify or delete files anywhere except under the scratch dir \$ORCH_SCRATCH (${scratchDir}). Use it for any repro.`;
  }
  const base = promptText + FOOTER + readonlyFooter;
  const cliFor = (session, message) => {
    const cli = ["run", "--format", "json", "--auto", "--agent", a.agent, "--title", title];
    if (a.model) cli.push("--model", a.model);
    if (session) cli.push("--session", session);
    cli.push(safe(message));
    return cli;
  };

  // One spawn of opencode. Stdout activity (not stderr) is what keeps a run from counting as stalled.
  const attempt = (cli) =>
    new Promise((resolve, reject) => {
      const lines = [];
      let stderr = "";
      let killReason = null;
      let lastOut = Date.now();
      let lastTick = Date.now();
      let maxSilence = 0;
      const attemptStart = Date.now();
      const childEnv = isReadOnly ? { ...workerEnv(), ORCH_SCRATCH: scratchDir } : workerEnv();
      const child = spawn(bin.cmd, [...(bin.pre || []), ...cli], { cwd: dir, env: childEnv, stdio: ["ignore", "pipe", "pipe"], shell: bin.shell, windowsHide: true, detached: process.platform !== "win32" });
      const tree = child.pid ? watch(child.pid, { since: attemptStart, everyMs: Number(process.env.ORCH_PROCTREE_MS) || 5000 }) : null;
      let buf = "";
      child.stdout.on("data", (d) => {
        lastOut = Date.now();
        events.write(d);
        buf += d;
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          lines.push(buf.slice(0, i));
          buf = buf.slice(i + 1);
        }
      });
      child.stderr.on("data", (d) => (stderr += d));
      const timer = setTimeout(() => {
        killReason = "timeout";
        killTree(child);
      }, Math.max(0, deadline - Date.now()));
      const watchdog = setInterval(() => {
        if (Date.now() - lastTick > 30_000) lastOut = Date.now(); // the host slept: never call that a stall
        lastTick = Date.now();
        maxSilence = Math.max(maxSilence, Date.now() - lastOut);
        if (idleMin > 0 && !killReason && Date.now() - lastOut > idleMin * 60000) {
          killReason = "stalled";
          killTree(child);
        }
      }, 5000);
      child.on("error", (e) => {
        clearTimeout(timer);
        clearInterval(watchdog);
        tree?.stop();
        reject(e);
      });
      child.on("close", async (code) => {
        clearTimeout(timer);
        clearInterval(watchdog);
        if (buf.trim()) lines.push(buf);
        let orphans = [];
        try {
          orphans = (await tree?.sweep()) || [];
        } catch {} // a watcher failure never changes a run's outcome
        tree?.stop();
        resolve({ code, lines, stderr, killReason, maxSilence, orphans });
      });
    });

  try {
    const resumed = [];
    const alls = [];
    const tokens = { input: 0, output: 0, reasoning: 0, cache_read: 0 };
    let cost = 0;
    let maxSilenceMs = 0;
    let attempts = 0;
    const orphansKilled = [];
    let r;
    let sum;
    let errors;
    let classifyErrors;
    // Read-only guard pre-snapshot (inside try so errors is in scope)
    if (isReadOnly) {
      try {
        preDiff = installedState(diff());
      } catch (e) {
        guardErrors.push(`readonly guard skipped: ${e.message}`);
      }
      try {
        wtHeadBefore = gitOut(dir, ["rev-parse", "HEAD"]);
        wtStatusBefore = gitOut(dir, ["status", "--porcelain"]);
      } catch (e) {
        guardErrors.push(`readonly guard skipped: ${e.message}`);
      }
    }
    let cli = cliFor(a.session, base);
    for (;;) {
      attempts++;
      const t0 = Date.now();
      r = await attempt(cli);
      for (const o of r.orphans) orphansKilled.push({ pid: o.pid, cmd: String(o.cmd || "").slice(0, 120) });
      sum = summarize(r.lines);
      maxSilenceMs = Math.max(maxSilenceMs, r.maxSilence);
      for (const k of Object.keys(tokens)) tokens[k] += sum.tokens[k];
      cost += sum.cost;
      if (sum.all.trim()) alls.push(sum.all);
      errors = sum.errors.slice();
      if (r.killReason === "stalled") errors.push(`stalled — no output for ${idleMin} min`);
      // stderr is always shown in the receipt, but it is pool/drop evidence only when the attempt did not finish cleanly
      const clean = !r.killReason && r.code === 0 && Boolean(sum.final);
      classifyErrors = errors.slice();
      if (r.stderr.trim()) {
        errors.push(r.stderr.slice(-500));
        if (!clean) classifyErrors.push(r.stderr.slice(-500));
      }
      const resumeReason = !clean && !r.killReason ? resumableReason(classifyErrors) : null;
      const interrupted = r.killReason === "stalled" || resumeReason != null;
      const waitMs = Number(process.env.ORCH_RESUME_WAIT_MS ?? 30_000);
      if (!interrupted || !sum.all.trim() || !sum.session || resumed.length >= resumeMax || Date.now() + waitMs >= deadline) break;
      const why = r.killReason === "stalled" ? `no output for ${idleMin} min` : (classifyErrors.find((e) => classify([e])?.reason === resumeReason) || errors[0] || "dropped").slice(0, 80);
      resumed.push({ session: sum.session, reason: why, seconds: Math.round((Date.now() - t0) / 1000) });
      if (waitMs > 0) await new Promise((res) => setTimeout(res, waitMs));
      const msg =
        `The previous run was interrupted (${why}). Continue the task from where you stopped. The Mandate is unchanged.\n` +
        `Before continuing, check the worktree state below and verify any half-finished edit or command.\n\n` +
        `git status --short:\n${gitOut(dir, ["status", "--short"])}\n\ngit diff --stat:\n${gitOut(dir, ["diff", "--stat"])}` +
        FOOTER;
      cli = cliFor(sum.session, msg);
    }
    events.end();
    const killReason = r.killReason;
    const all = alls.join("\n\n");
    if (killReason && all.trim()) {
      // Partial work survives a timeout or stall; the status line makes it impossible to mistake for a finished run.
      const why = killReason === "stalled" ? `stalled — no output for ${idleMin} min` : `timeout after ${a.timeoutMin} min`;
      fs.writeFileSync(out, `RESULT: BLOCKED: ${why} — partial output below\n\n${all}\n`);
      sum.final = "";
    } else if (sum.final) fs.writeFileSync(out, sum.final.endsWith("\n") ? sum.final : sum.final + "\n");
    const code = r.code;

    // Read-only guard: compare with the pre-run snapshot. Never changes status/exit.
    const tampered = [];
    let worktreeChanged = null;
    if (isReadOnly && preDiff) {
      try {
        const postDiff = diff();
        const stamp = new Date().toISOString().replace(/[:.]/g, "-") + "-tampered";
        for (const c of postDiff.changes) {
          if (preDiff.get(c.target) === fileSha(c.target)) continue; // drift that existed before the run is the owner's
          try {
            let backupPath = null;
            if (fs.existsSync(c.target)) {
              const home = homeDir();
              const rel = path.relative(home, c.target).replace(/^(\.\.[\\/])+/, "outside/");
              backupPath = path.join(home, ".config", "orchestrator", "backups", stamp, rel);
              fs.mkdirSync(path.dirname(backupPath), { recursive: true });
              fs.copyFileSync(c.target, backupPath);
            }
            fs.mkdirSync(path.dirname(c.target), { recursive: true });
            fs.writeFileSync(c.target, c.content);
            tampered.push({ target: c.target, backup: backupPath, restored: true });
            guardErrors.push(`read-only role modified installed file ${c.target} (restored)`);
          } catch (e) {
            guardErrors.push(`readonly guard restore failed for ${c.target}: ${e.message}`);
          }
        }
      } catch (e) {
        guardErrors.push(`readonly guard skipped: ${e.message}`);
      }
    }
    if (isReadOnly && wtHeadBefore !== null) {
      try {
        const head = gitOut(dir, ["rev-parse", "HEAD"]);
        const status = gitOut(dir, ["status", "--porcelain"]);
        if (head !== wtHeadBefore || status !== wtStatusBefore) {
          worktreeChanged = { head_before: wtHeadBefore, head_after: head, status_before: wtStatusBefore, status_after: status };
          guardErrors.push("read-only role changed the worktree");
        }
      } catch (e) {
        guardErrors.push(`readonly guard skipped: ${e.message}`);
      }
    }
    errors.push(...guardErrors);
    const readonlyViolation = tampered.length > 0 || worktreeChanged !== null;
    let gateResult = /^(critic|senior)/.test(a.agent) && sum.final
      ? gate(sum.final, { free: /-free$/.test(a.agent) || /^opencode\/.*-free$/.test(a.model || "") || isPolicyFree(a.model || agentModel(a.agent) || "") })
      : null;
    if (readonlyViolation && gateResult) gateResult = { ...gateResult, effective: "INVALID", reasons: [...gateResult.reasons, "readonly_violation"] };
    const receipt = {
      agent: a.agent,
      model,
      session: sum.session,
      exit: killReason ?? code,
      seconds: Math.round((Date.now() - started) / 1000),
      tokens,
      cost: Number(cost.toFixed(6)),
      first_line: (sum.final.split("\n").find((l) => l.trim()) || "").slice(0, 200),
      // The verdict, wherever the agent put it: final message first, then the --report file.
      verdict: statusLine(sum.final) || (a.report ? statusLine(readText(path.resolve(dir, a.report))) : "") || null,
      out: sum.final || (killReason && all.trim()) ? out : null,
      partial: Boolean(killReason && all.trim()),
      errors,
      max_silence_s: Math.round(maxSilenceMs / 1000),
      resumed,
      attempts,
      ...(orphansKilled.length ? { orphans_killed: orphansKilled } : {}),
      // An orchestrator's own events do not include the subagents it spawned; price the whole tree.
      tree: sum.session ? sessionTree(sum.session) : null,
      // Read-only guard fields
      ...(tampered.length ? { tampered } : {}),
      ...(worktreeChanged ? { worktree_changed: worktreeChanged } : {}),
      ...(readonlyViolation ? { readonly_violation: true } : {}),
      // Critics: the mechanical decision, not the critic's own claim (free critics find, then approve).
      gate: gateResult,
    };
    atomicWrite(out + ".receipt.json", JSON.stringify(receipt, null, 2) + "\n");
    Object.defineProperty(receipt, "classifyErrors", { value: classifyErrors, enumerable: false }); // for runWithFallback; not serialized
    receipt.status = killReason ? 4 : code ? 5 : sum.final ? 0 : 3;
    return receipt;
  } finally {
    clearInterval(kickTimer);
    run.end();
    release();
    // Clean up scratch dir for read-only roles
    if (scratchDir && fs.existsSync(scratchDir)) {
      try {
        fs.rmSync(scratchDir, { recursive: true, force: true });
      } catch {}
    }
  }
}

function fileSha(p) {
  let c = "";
  try { c = fs.readFileSync(p, "utf8").replace(/\r\n/g, "\\n"); } catch {}
  return crypto.createHash("sha256").update(c).digest("hex");
}
// target -> sha256 of what is on disk now (or "") for every target install.diff() says differs from the repo.
function installedState(d) {
  if (process.env.ORCH_TEST_GUARD_FAULT) throw new Error("injected guard fault"); // test hook: simulate install.diff() failing
  return new Map(d.changes.map((c) => [c.target, fileSha(c.target)]));
}

function gitOut(dir, argv) {
  try {
    return execFileSync("git", ["-C", dir, ...argv], { encoding: "utf8", windowsHide: true, stdio: ["ignore", "pipe", "ignore"] }).trim() || "(clean)";
  } catch {
    return "(git unavailable)";
  }
}

export function runsDir() {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "runs");
}

// The dashboard script, if installed: kicking it rebuilds the HTML in the background when stale.
function kickDashboard() {
  const dash = path.join(process.env.ORCH_HOME || os.homedir(), ".claude", "hooks", "cross-harness-statusline.js");
  if (process.env.ORCH_NO_DASH || !fs.existsSync(dash)) return;
  if (fs.existsSync(path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "dashboard.off"))) return;
  try {
    spawn(process.execPath, [dash, "--kick"], { detached: true, stdio: "ignore", windowsHide: true }).unref();
  } catch {}
}

/** Register a running oc-worker so the dashboard can show it live; touch() refreshes + kicks, end() removes. */
export function registerRun(info) {
  const dir = runsDir();
  const file = path.join(dir, `${process.pid}-${info.started}.json`);
  const write = (extra = {}) => {
    try {
      fs.mkdirSync(dir, { recursive: true });
      fs.writeFileSync(file, JSON.stringify({ pid: process.pid, ...info, ...extra, heartbeat: new Date().toISOString() }));
    } catch {}
  };
  write();
  kickDashboard();
  return {
    touch(extra) {
      write(extra);
      kickDashboard();
    },
    end() {
      try {
        fs.rmSync(file, { force: true });
      } catch {}
      kickDashboard();
    },
  };
}

/** Compact duration for the active list: 45s, 26m, 3h12m, 2d5h. */
export function fmtDur(ms) {
  if (!Number.isFinite(ms) || ms < 0) return "?";
  const s = Math.floor(ms / 1000);
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  const h = Math.floor(m / 60);
  if (h < 48) return `${h}h${m % 60 ? `${m % 60}m` : ""}`;
  return `${Math.floor(h / 24)}d${h % 24 ? `${h % 24}h` : ""}`;
}

function readRunFiles() {
  let files = [];
  try {
    files = fs.readdirSync(runsDir()).filter((f) => f.endsWith(".json"));
  } catch { return []; }
  const out = [];
  for (const f of files) {
    try {
      out.push({ file: path.join(runsDir(), f), ...JSON.parse(fs.readFileSync(path.join(runsDir(), f), "utf8")) });
    } catch { /* corrupt entry: skip, never crash the list */ }
  }
  return out;
}

/** Newest mtime of the run's output files (events log first, then the report itself). */
function lastOutMs(run) {
  for (const p of [`${run.out}.events.jsonl`, run.out]) {
    if (typeof p !== "string") continue;
    try { return fs.statSync(p).mtimeMs; } catch { /* missing yet */ }
  }
  return null;
}

/**
 * One status row per registered run. States: RUNNING (producing), STARTING (no
 * output yet), QUIET (silent past its idle limit — the killer should fire on its
 * next poll), OVERDUE (alive past its timeout budget — the wrapper should have
 * exited), HEARTBEAT-STALE (wrapper alive but not ticking its 20s heartbeat),
 * STALE (wrapper pid gone — a crash that skipped end()). Read-only.
 */
export function activeRuns(now = Date.now()) {
  return readRunFiles().map((r) => {
    const pidAlive = Number.isInteger(r.pid) ? alive(r.pid) : false;
    const hbAge = r.heartbeat ? now - Date.parse(r.heartbeat) : null;
    const outMs = lastOutMs(r);
    const outAge = outMs == null ? null : now - outMs;
    const idleMin = Number.isInteger(r.idleMin) ? r.idleMin : null;
    const timeoutMin = Number.isInteger(r.timeoutMin) ? r.timeoutMin : null;
    let state = "RUNNING";
    let detail = "";
    if (!pidAlive) {
      state = "STALE";
      detail = "wrapper pid gone (crashed without end())";
    } else if (timeoutMin != null && timeoutMin > 0 && Number.isFinite(r.started) && now - r.started > timeoutMin * 60000) {
      state = "OVERDUE";
      detail = `over timeout-min ${timeoutMin}m budget`;
    } else if (hbAge != null && hbAge > 120000) {
      state = "HEARTBEAT-STALE";
      detail = `no heartbeat for ${fmtDur(hbAge)} (ticks every 20s)`;
    } else if (outMs == null) {
      state = "STARTING";
    } else if (idleMin != null && idleMin > 0 && outAge != null && outAge > idleMin * 60000) {
      state = "QUIET";
      detail = `silent ${fmtDur(outAge)} past idle-min ${idleMin}m`;
    }
    return {
      ...r,
      pidAlive,
      elapsed: Number.isFinite(r.started) ? fmtDur(now - r.started) : "?",
      outAge: outAge == null ? null : fmtDur(outAge),
      state,
      detail,
    };
  }).sort((a, b) => (a.started || 0) - (b.started || 0));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const argv = process.argv.slice(2);
  // Help wins over everything: no validation, no slot, no launch.
  if (argv.includes("--help") || argv.includes("-h")) {
    console.log(usage());
    process.exit(0);
  }
  // Live status, no launch: which headless runs exist, how long each has run,
  // when each last produced output, and the watchdog limits watching it.
  if (argv[0] === "active") {
    const rows = activeRuns();
    if (argv.includes("--json")) {
      console.log(JSON.stringify(rows, null, 2));
      process.exit(0);
    }
    if (!rows.length) console.log("oc-worker: no registered runs");
    for (const r of rows) {
      const what = r.title || (r.out ? path.basename(r.out) : path.basename(r.file));
      const limits = `idle-min ${r.idleMin == null ? "?" : r.idleMin === 0 ? "off" : r.idleMin + "m"} timeout-min ${r.timeoutMin == null ? "?" : r.timeoutMin + "m"}`;
      console.log(`${r.state} ${r.agent} ${what} | elapsed ${r.elapsed} | out ${r.outAge ?? "none yet"} | ${limits} | pid ${r.pid ?? "?"}${r.stream ? ` | stream ${r.stream}` : ""}`);
    }
    process.exit(0);
  }
  let a;
  try {
    a = args(argv);
  } catch (e) {
    console.error(`oc-worker: ${e.message}`);
    process.exit(2);
  }
  runWithFallback(a)
    .then((r) => {
      const { status, ...rest } = r;
      console.log(JSON.stringify(rest));
      process.exit(status);
    })
    .catch((e) => {
      console.error(`oc-worker: ${e.message}`);
      process.exit(e instanceof StreamRefused ? e.code : e instanceof AttachRefused ? 7 : 5);
    });
}

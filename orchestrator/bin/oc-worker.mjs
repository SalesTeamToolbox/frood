#!/usr/bin/env node
// Launch one headless OpenCode agent run (worker, critic, scout, senior, ...) and record what it did.
//
//   node oc-worker.mjs --agent worker --dir <worktree> --prompt <mandate.md>
//        [--out <final-message.md>] [--session <ses_id>] [--model <provider/model>]
//        [--ticket <id> --owner <session>]
//        [--stream <name>] [--title <text>] [--timeout-min 30] [--idle-min 20] [--grace-min 15] [--resume 1] [--slots N]
//        [--role <name>] [--fallback <agent>[,<agent>]] [--report <path>] [--vision] [--detach | --no-detach]
//   node oc-worker.mjs --help   (or -h) prints this text and exits 0; nothing is launched
//   node oc-worker.mjs active [--json]   list running headless runs with elapsed time, last-output
//      age and watchdog limits (idle-min / timeout-min). STALE = wrapper pid gone; OVERDUE = past its
//      timeout budget but still alive; HEARTBEAT-STALE = wrapper alive but not ticking; QUIET = silent
//      past its idle limit; STARTING = no output yet. Read-only; exits 0.
//
// - Runs `opencode run --standalone --format json --auto --agent <agent>` with cwd=<dir> and stdin closed
//   (--standalone gives the run a private server on its stdio, so killing the run ends the session: the
//   server exits when its pipe closes, with the proc-tree sweep as backstop. Without it the session lives
//   on in the shared background service. An open stdin makes `opencode run` wait forever.)
// - The prompt file's text is the message. A footer tells the agent it cannot ask questions:
//   it must finish with `RESULT: BLOCKED: question — ...` instead.
// - --session resumes the same agent session (revision rounds keep the worker's context).
// - --fallback: when a run dies on a provider quota/rate limit or "model unavailable" before producing any
//   text (e.g. Go weekly limit), that model is marked down in ~/.config/orchestrator/pool-health.json (until
//   the provider's retry-after) and the next agent in the list runs; later runs skip known-down models
//   without calling them. Max 3 real attempts. The receipt records every hop and skip.
// - Machine-wide worker slot cap: `WORKER_SLOTS=N` (or --slots N) is a fixed cap of N. When unset, the cap is
//   dynamic between WORKER_SLOTS_MIN (default 2) and WORKER_SLOTS_MAX (default 6), decided from machine load over
//   the last 5 minutes (/proc/pressure/cpu some avg300, /proc/loadavg, /proc/meminfo MemAvailable); ORCH_PROC_ROOT
//   overrides the proc tree (tests use temp fixtures, never the real /proc). Invalid values exit 2. Slots are lock
//   dirs under ~/.config/orchestrator/slots, stale when the owning pid is gone. Decisions are logged to
//   ~/.config/orchestrator/slot-decisions.log (on admission and on allowed changes only).
// - Machine-wide Nvidia provider slot: a run whose model starts with `nvidia/` first claims one of the lock dirs
//   `provider-nvidia-<i>` beside the worker slots, then a machine slot. One API key means one 429 budget, so Nvidia
//   runs are capped across every ticket and role. The cap is adaptive: NVIDIA_SLOTS_MAX (default 3) with no recent
//   429; an Nvidia rate-limit/quota classification is recorded in provider-nvidia.state.json and for
//   NVIDIA_COOLDOWN_MS (default 600000) the cap is 1, then it steps up one per further quiet cooldown. NVIDIA_SLOTS=N
//   (positive integer) is a fixed cap that turns adaptive off. In-flight runs keep their slot; only new admissions
//   see a lower cap. Cap changes are logged to slot-decisions.log. Waiting takes no machine slot and does not spend
//   --timeout-min; a chain hop to a non-Nvidia agent holds none. ORCH_NVIDIA_POLL_MS (default 3000) is the poll
//   interval. The queued event's `slots` names it (`nvidia <held>/<cap>`); the receipt has `provider_slot`.
// - Visible slot waits: while waiting for either the worker slot (`acquireSlot`) or the Nvidia provider slot
//   (`acquireProviderSlot`), oc-worker prints one stderr line when each wait begins and again at most once a
//   minute: `oc-worker: waiting for a worker slot (cap <n> <fixed|dynamic>; held by pid <p> <agent> <title>, …)`
//   and `oc-worker: waiting for an nvidia slot (cap <n>; held by pid <p> <agent> <title>, …)`.
//   Slot owners carry `agent`/`title`/`out` so they can be named. The run registers in the live registry with
//   `state: "queued"` while waiting (distinguishable from running), and the receipt gains `queued_s` (seconds
//   spent waiting, both waits together). Slot caps and admission logic are unchanged; the time budget starts
//   after the slot is acquired.
// - --ticket <id> --owner <session>: the ticket names an OpenCode board ticket; before anything is launched this
//   runs `node <board.mjs> attach <id> --pid <this pid> --out <out>` (execFileSync, no shell), which the board
//   refuses unless the ticket is working, owned by --owner and past its EGM gate. A refusal exits 7 with nothing
//   launched and no slot taken.
// - Writes <out> (the agent's final text), <out>.events.jsonl (raw events), <out>.receipt.json
//   ({agent, model, session, exit, seconds, tokens, cost, first_line, queued_s, …}); model is the pinned model
//   of the agent when --model was not given. Prints the receipt JSON.
// - --idle-min <n> (default 20, 0 disables): kills a run whose stdout has been silent for n minutes (a sleeping host
//   never counts). For agents whose name ends `-nvidia` (worker-nvidia, critic-nvidia) the default is 6 instead
//   of 20; explicit --idle-min always wins. Receipt exit "stalled", status 4, partial output kept like a timeout.
//   Receipt max_silence_s is the longest stdout silence seen, for tuning the default.
// - --resume <n> (default 1, 0 disables): a run that dropped (ECONNRESET, socket hang up, ...), stalled, or died
//   mid-run on a transient pool error (quota/rate-limit, provider 5xx/overload) after producing output and a session
//   id is resumed with --session after 30 s (ORCH_RESUME_WAIT_MS), inside the same slot: the manual "nudge it along",
//   automatic. For `*-nvidia` agents the default is 3 instead of 1; explicit --resume always wins. After a
//   quota/rate-limit death the wait is max(ORCH_RESUME_WAIT_MS, ORCH_RATE_LIMIT_WAIT_MS), the latter default
//   60000: a 429 window is longer than a dropped socket. Deterministic failures (unknown/retired model, not-in-plan)
//   and clean finishes never resume. --timeout-min is one wall-clock budget for all attempts together. Receipt:
//   resumed [{session, reason, seconds}] and attempts (spawns). On a resumed run, errors, first_line and verdict
//   come from the last attempt only; tokens and cost are summed. stderr is always listed in errors but counts as
//   pool-health evidence only when the run did not finish cleanly (exit 0 with a final message). A stalled run
//   exits 4 like a timeout.
// - Hung tool calls: when the stall rule fires and the opencode process tree holds exactly one live
//   descendant that has existed longer than the idle window (a shell tool child: `node --test`, `npm`, …),
//   that descendant is killed and the silence clock restarts — opencode survives and is nudged by the tool
//   failure. If it stays silent for another idle window, the normal stall path kills opencode and the resume
//   message carries one extra line: `A tool command ran over <n> min and was stopped: <cmd>`. With more than
//   one such descendant (a hung tool next to long-lived MCP servers / a pty daemon) the pid cannot be
//   identified, so the normal stall kill runs instead — a pid is never guessed. Only pids from this run's
//   opencode child tree are ever killed — never by name pattern. bin/proc-tree.mjs read-only helpers list
//   descendants; its sweep rules are unchanged.
// - After every attempt (finished, failed, timeout, stall) the run's leftover descendants are killed (bin/proc-tree.mjs: the
//   process table is sampled while opencode runs; a child whose parent died is still swept). Receipt orphans_killed
//   [{pid, cmd}] appears only when something was killed. ORCH_NO_PROCTREE=1 disables.
// - ORCH_TEST_POSTRUN_PAUSE_MS: test-only, default 0. If set (>0 ms), after the last attempt finishes and <out>
//   has been written, oc-worker pauses that long before writing the receipt. A signal landing in that pause
//   (after a clean last attempt) leaves the clean receipt intact and oc-worker exits promptly afterwards; it is
//   how a test lands a SIGTERM once <out> exists.
// - --stream <name>: report this run to a desk stream (bin/handoff.mjs). The stream must exist (exit 2) and --out must be
//   fresh: if <out> or <out>.receipt.json exists the run is refused (exit 2). Before a slot is taken a `queued` event
//   (pid, pid start, agent, ticket.json path) is appended to the stream; exit 9 (nothing launched) if that run is
//   already queued. When the run ends (any status) one `run-done` event {agent, exit, outcome, session} is appended.
//   The run id, and so every key, is `<ticket>/<run>`: `<ticket>` is the `ticket` string of dirname(--out)/ticket.json
//   (the run dir's basename when that file is missing or has no string `ticket`), `<run>` is the --out basename without
//   its extension — e.g. `run:m6a-desk-minors/worker-r1:queued`. One stream therefore carries many tickets without
//   their worker-r1 keys colliding; exit 9 still means this exact run id is already queued.
//   Event write failures go to stderr and never change the run's status. Without --stream no stream file is touched.
// - SIGTERM / SIGINT / SIGHUP to oc-worker while a run holds its slots (exit "killed"): the attempt's process group gets
//   SIGTERM, then SIGKILL after 5 s if it is still there, and the proc-tree sweep kills the leftover descendants. Both
//   slots are released, the receipt is written with exit "killed" (errors: "killed by <SIGNAL>"), the stream run-done is
//   appended, and oc-worker exits 143 / 130 / 129. A second signal during cleanup is ignored. While still waiting for a
//   slot nothing is held, so the signal just ends the process (no receipt).
// - --agent cc-worker | cc-worker-strong | cc-critic | cc-senior (any key of `cc.models`): the backend is headless
//   Claude Code, not OpenCode. The cc agents are the keys of `cc.models` in usage-limits.json merged over the default
//   {"cc-worker":"sonnet","cc-worker-strong":"opus","cc-critic":"opus","cc-senior":"fable"} (only "cc-" keys count);
//   the receipt model is cc.models[agent] (or --model on the first hop), never empty. cc-senior runs `opus` instead
//   while the launch's one pace read says `fable.state: "over"` (a detached child inherits that bit). It runs `claude`
//   (ORCH_CLAUDE_BIN, else `claude` on PATH) with cwd=<dir>. Writers (cc-worker, cc-worker-strong): `-p <prompt>
//   --model <m> --settings {"disableAllHooks":true} --tools Read,Grep,Glob,Edit,Write,Bash --strict-mcp-config
//   --permission-mode acceptEdits --allowedTools Bash --permission-prompts none --output-format stream-json --verbose`.
//   Readers (cc-critic, cc-senior: a cc agent matching READONLY_AGENT_RE): `--tools Read,Grep,Glob,Bash
//   --strict-mcp-config --allowedTools Bash --disallowedTools Edit,Write,NotebookEdit` in place of the writer tool
//   flags, and no acceptEdits; they get the read-only guard (scratch footer, tamper and worktree check,
//   readonly_violation) and the verdict gate like an OpenCode critic. A reader also gets its role contract:
//   `--append-system-prompt-file <out>.contract.md` right after --settings, the body (frontmatter stripped) of
//   <ORCH_HOME or home>/.claude/agents/<role>.md (cc-critic → critic.md, cc-senior → senior.md), and a read-only fence
//   footer. A missing or empty contract file skips the hop (reason and receipt note `cc-no-contract: <file>`, no attempt
//   used), so the chain falls back to the OpenCode reader; a reader never runs contract-less. Plus `--resume <id>` for --session and the
//   automatic resume. Hook-free: the owner's
//   Stop hooks (an asyncRewake peer-mail wake, the repo's learning hooks) would keep a finished run alive and dirty the
//   worktree; the child env also gets PEER_WAKE_MAX_MIN=0 (overriding any inherited value) as a backstop. Never `--bare`
//   (it refuses the OAuth subscription login). Session, final text, tokens and
//   cost come from the stream-json `session_id` / `result` events; with no `result` event (timeout, kill) tokens are the
//   sum of the `assistant` events' message.usage, each message id counted once. Timeout, idle, BelowNormal, the proc-tree
//   sweep, signals, --stream, --out and --report behave as for an OpenCode agent. A Claude usage/rate limit is classified
//   quota / rate-limit, so --fallback moves on. Pool health keys a cc agent by its name; the cc agents are ONE group
//   (one subscription): a limit on any of them marks every cc.models key down with the same reset (the 5-hour reset in
//   the message, else now + 5 h), any live cc-* quota / rate-limit mark holds every cc agent down (a dropped /
//   provider-error mark holds only its own key), and an answer clears the group except marks written after the
//   answering run started. A lone reader whose only hop was a ccread slot timeout ends with exit "cc-slot-timeout"
//   (status 6, as no-healthy-pool). Desk and board treat cc-* agents as paid (receipt free-ness and the verdict gate),
//   and the desk verdicts a cc-critic run-done like a critic's.
//   Slots: at most `cc.max_workers` (usage-limits.json, default 1) cc writers at once machine-wide (lock dirs
//   `provider-cc-<i>`; a waiting writer waits and never fails), and at most `cc.max_readers` (default 1) cc readers
//   (`provider-ccread-<i>`); the two caps are independent. A reader also takes the machine worker slot as every run
//   does. A reader that waited `cc.reader_wait_min` (default 10) minutes for `ccread` gives up: the chain skips to
//   the next agent without using an attempt, the hop's reason is `cc-slot-timeout: ...`, and the final receipt
//   carries it in a `notes` array (errors, too, when no agent ran). Polling: ORCH_CC_POLL_MS, default 3000. The cc
//   agents are not in any CHAINS role: name them with --agent (or see pace-aware routing below).
// - Detached runs (detachRun): a cc agent run (or any run with --detach) survives its launcher. The launching oc-worker
//   re-spawns itself (same argv, env marker ORCH_DETACHED_CHILD=1) in a new session and process group (POSIX setsid),
//   stdin ignored, the child's stderr to <out>.detached.log and its stdout to <out>.detached.out (<out> is the --out path,
//   or its default beside the prompt). The launcher prints `oc-worker: detached run pid <n>, log <path>` on stderr, waits,
//   then copies the child's stderr and stdout to its own and exits with the child's code: a foreground caller sees the
//   same output and status. SIGTERM / SIGINT / SIGHUP to the launcher exit it (143 / 130 / 129) WITHOUT signalling the
//   child, so a Claude Code session that ends its turn no longer kills the run; signal the child pid to stop the run.
//   --no-detach runs in process (the old behaviour). Windows never detaches. OpenCode agents detach only with --detach.
// - Pace-aware routing (bin/pace-read.mjs): every launch reads `cc-pace.mjs status --json` once (10 s timeout; any
//   failure reads as `unknown`, never fails the run; ORCH_NO_PACE=1 → `off`). PACE_POLICY (pace-read.mjs) maps
//   worker → cc-worker, worker-strong → cc-worker-strong, critic → cc-critic, senior → cc-senior. On an `under`
//   pace, `--role <r>` for r in the table becomes [<r's cc agent>, <today's chain after the Nvidia drop rule>],
//   except senior while Fable is over; scout and orchestrator, every other state, --agent / --fallback launches and
//   any `--session` launch never pace-prepend. A `--role <r> --session <id>` (r in the table) whose id does not
//   start with `ses_` is a Claude session: the chain becomes [<r's cc agent>, <today's chain>] so the resume goes
//   to that cc agent, in every pace state, without a pace decision; a `ses_` id keeps today's chain.
//   With --vision (or an image Mandate) cc-worker counts as vision-capable; a first hop that is not the agent
//   `a` books (the vision filter dropped it) runs fresh on its own pinned model. Every receipt
//   gets cc_pace {state, weekly, projected, at, prepended, role, shadow} (role: the --role, null for --agent). A
//   detached child takes the launcher's read and chain (env ORCH_PACE_DECISION) and never reads again.
//   ORCH_PACE_BIN overrides the cc-pace.mjs path (tests).
// Exit: 0 finished, 3 no final text, 4 timeout, 5 opencode error, 6 every pool in the chain known-down, 7 board
// attach refused (--ticket), 8 model not allowed by provider policy (`ignored`; unreadable providers.json; model unresolvable while any provider is restricted; `free-only`
// and not on the allowlist), 10 stale or dirty tree (fresh --stream worker refused before queued/spawn).
//   Also 143 / 130 / 129: killed by SIGTERM / SIGINT / SIGHUP (receipt exit "killed").
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawn, spawnSync, execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";
import { gate } from "./verdict-gate.mjs";
import { watch, processStart } from "./proc-tree.mjs";
import { diff, homeDir } from "./install.mjs";
import { agentModel, classify, isDown, isPolicyFree, markDown, markGroupDown, markUp, modelAllowed, policyReason, providerOf, hasRestrictivePolicy, readHealth, isCcPool } from "./pool-health.mjs";
import crypto from "node:crypto";
import { appendEvent, atomicWrite, streamsDir } from "./handoff.mjs";
import { workerOutcome } from "./outcome.mjs";
import { CHAINS, chainFor } from "./chains.mjs";
import { readPace, paceChain, ccPaceRecord, PACE_POLICY } from "./pace-read.mjs";
import { readSample, slotConfig, allowedSlots, decisionLog, heldCount, nvidiaCapNow, recordNvidia429 } from "./slots.mjs";
import { allowedRoots, findMain, gitStatusZ, parseStatusZ, footer, mergeEditFence, foldEscapes, finalizeEscapes, hasCompletedWrite } from "./worktree-fence.mjs";

export const FOOTER = `

---
Run constraints (from the orchestrator):
- You are running headless. Nobody can answer questions mid-run. If you cannot proceed without a decision,
  stop and make your final message start with: RESULT: BLOCKED: question — <one specific question>
- Stay inside the working directory you were started in. Never push, merge, deploy, or touch other worktrees.
- Your final message is saved verbatim for the orchestrator. Make its first line the status line your role defines
  (RESULT: ... for workers, VERDICT: ... for critics).
- Workers: The first line of your final reply is exactly \`RESULT: DONE\` or \`RESULT: BLOCKED: <reason>\`: capitals, with no markdown, emoji, quote or prefix. The parser is case-sensitive, and anything else counts as an error.`;

export const READONLY_AGENT_RE = /^(cc-)?(critic|senior|scout|explorer)(-|$)/;
// Agents the verdict gate judges (OpenCode critic/senior and their headless Claude twins).
export const VERDICT_AGENT_RE = /^(cc-)?(critic|senior)/;

// Static list of known vision-capable models (must match router-health.mjs VISION_CAPABLE_MODELS)
const VISION_CAPABLE_MODELS = new Set([
  "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b",
  "opencode-go/muse-spark-1.3-contributor",
  "opencode-go/muse-spark-1.2-contributor",
]);

// Check if a model is vision-capable
function isVisionCapable(model) {
  return VISION_CAPABLE_MODELS.has(model);
}

// Check if agent frontmatter has vision: true
function agentHasVision(agent) {
  const dirs = [path.join(process.env.ORCH_HOME || os.homedir(), ".config", "opencode", "agents"),
    path.join(process.env.ORCH_HOME || os.homedir(), ".config", "opencode", "agent")];
  for (const d of dirs) {
    try {
      const fm = fs.readFileSync(path.join(d, `${agent}.md`), "utf8").split(/\r?\n---/)[0];
      const m = fm.match(/^vision:\s*(true|false)/m);
      if (m) return m[1] === "true";
    } catch {}
  }
  return false;
}

// Image detection for auto-vision mode
const IMAGE_EXTENSIONS = new Set([".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".ico"]);
const MAX_IMAGE_SIZE = 10 * 1024 * 1024; // 10MB per image
const MAX_TOTAL_SIZE = 50 * 1024 * 1024; // 50MB total

// Check if a file path is an image (by extension)
function isImagePath(p) {
  const ext = path.extname(p).toLowerCase();
  return IMAGE_EXTENSIONS.has(ext);
}

// Check if a string looks like a base64 data URL with image MIME type
function isImageDataUrl(s) {
  return /^data:image\/(png|jpeg|jpg|gif|webp|bmp|svg\+xml);base64,/.test(s.trim());
}

// Check if a URL has an image MIME type via HEAD request (with timeout)
async function isImageUrl(urlStr) {
  try {
    const url = new URL(urlStr);
    if (url.protocol !== "http:" && url.protocol !== "https:") return false;
    // Quick extension check first
    if (isImagePath(url.pathname)) return true;
    // HEAD request to verify content-type
    const controller = new AbortController();
    const timeout = setTimeout(() => controller.abort(), 5000);
    const res = await fetch(urlStr, { method: "HEAD", signal: controller.signal });
    clearTimeout(timeout);
    const ct = res.headers.get("content-type") || "";
    return ct.startsWith("image/");
  } catch {
    return false;
  }
}

// Scan text for image references (file paths, data URLs, HTTP URLs)
async function detectImagesInText(text, workDir) {
  const images = [];
  let totalSize = 0;

  // Pattern 1: File paths with image extensions (relative to workDir or absolute)
  const filePathRegex = /(?:^|\s)([~\/][\w\-\.\/]*?(?:\.png|\.jpg|\.jpeg|\.gif|\.webp|\.bmp|\.svg|\.tiff|\.ico))\b/gim;
  let match;
  while ((match = filePathRegex.exec(text)) !== null) {
    const p = match[1].replace(/^~/, os.homedir());
    const absPath = path.isAbsolute(p) ? p : path.resolve(workDir, p);
    try {
      const stat = fs.statSync(absPath);
      if (stat.isFile() && stat.size <= MAX_IMAGE_SIZE) {
        images.push({ type: "file", path: absPath, size: stat.size });
        totalSize += stat.size;
      }
    } catch {}
  }

  // Pattern 2: Base64 data URLs
  const dataUrlRegex = /data:image\/(png|jpeg|jpg|gif|webp|bmp|svg\+xml);base64,/g;
  while ((match = dataUrlRegex.exec(text)) !== null) {
    // Estimate size from base64 length (roughly 3/4 of base64 string)
    const base64Part = text.slice(match.index + match[0].length, match.index + match[0].length + 200);
    const estimatedSize = Math.floor(base64Part.length * 0.75);
    if (estimatedSize <= MAX_IMAGE_SIZE) {
      images.push({ type: "data-url", mime: `image/${match[1]}`, estimatedSize });
      totalSize += estimatedSize;
    }
  }

  // Pattern 3: HTTP/HTTPS URLs (we'll verify async)
  const urlRegex = /https?:\/\/[^\s\)\]\}]+/g;
  while ((match = urlRegex.exec(text)) !== null) {
    const url = match[0].replace(/[.,;:]+$/, ""); // strip trailing punctuation
    if (await isImageUrl(url)) {
      images.push({ type: "url", url });
    }
  }

  return { images, totalSize, overLimit: totalSize > MAX_TOTAL_SIZE };
}

// Usage is the header comment block of this file, so it cannot drift out of date.
export function usage() {
  const src = fs.readFileSync(fileURLToPath(import.meta.url), "utf8").split(/\r?\n/);
  const out = [];
  for (let i = src[0]?.startsWith("#!") ? 1 : 0; i < src.length && src[i].startsWith("//"); i++) {
    out.push(src[i].replace(/^\/\/ ?/, ""));
  }
  return out.join("\n");
}

// Agents whose name ends `-nvidia` (worker-nvidia, critic-nvidia) run on Nvidia models whose steps take
// 2-50 s with silences up to ~5 min, so their stall defaults are tighter: idle-min 6 (the worst healthy
// silence is ~80 s, so 6 min catches real stalls fast) and resume 3 (repeated nudges inside the same
// wall-clock budget). Explicit --idle-min / --resume flags always win; non-Nvidia agents keep idle 20 /
// resume 1. `isNvidiaAgent` is also applied after `--role` expansion (the agent is only known then).
function isNvidiaAgent(agent) {
  return typeof agent === "string" && /-nvidia$/.test(agent);
}

// Pure: the time the host spent asleep between two watchdog ticks, i.e. the tick gap
// minus the one tick (tickMs) that would have elapsed anyway. 0 when there was no sleep
// (gap <= tickMs) so a normal 5 s tick never extends the deadline. Testable without a
// real suspend.
export function sleepGapMs(lastTick, now, tickMs) {
  const slept = now - lastTick - tickMs;
  return slept > 0 ? slept : 0;
}
// Pure: how much of an observed `gapMs` of host-sleep time can be given back to the
// deadline, honoring the cap. Returns { add, total }: `add` is the ms to extend now (0
// when the cap is exhausted) and `total` is the new cumulative slept time. Testable
// without a real suspend, so the capped extension is covered at unit level.
export function sleepExtensionMs(totalSleptMs, gapMs, capMs) {
  const add = Math.max(0, Math.min(Math.max(gapMs, 0), capMs - totalSleptMs));
  return { add, total: totalSleptMs + add };
}
// The watchdog ticks every 5 s; sleepGapMs subtracts exactly one tick so a normal tick
// never counts as sleep.
const WATCHDOG_MS = 5000;
// The most a run's deadline may be pushed back for host sleep, so a machine that sleeps
// all night still ends the run.
const MAX_SLEEP_EXTENSION_MS = 2 * 60 * 60_000;
// opts.pace: the pace object (or a function returning it, called at most once) used by `--role` expansion;
// opts.chain: an already-decided chain (the detached child). Neither given: today's chain, no pace read.
export function args(argv, opts = {}) {
  const a = { timeoutMin: 30, idleMin: undefined, resume: undefined, vision: false, graceMin: 15 };
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
    else if (k === "--idle-min") { a.idleMin = Number(v()); a.idleMinSet = true; }
    else if (k === "--grace-min") a.graceMin = Number(v());
    else if (k === "--resume") { a.resume = Number(v()); a.resumeSet = true; }
    else if (k === "--slots") a.slots = v();
    else if (k === "--fallback") a.fallback = v().split(",").map((x) => x.trim()).filter(Boolean).slice(0, 8);
    else if (k === "--role") a.role = v();
    else if (k === "--vision") a.vision = true;
    else if (k === "--no-vision") a.vision = false; // explicit opt-out
    else if (k === "--detach") a.detach = true;
    else if (k === "--no-detach") a.detach = false;
    else throw new Error(`unknown flag ${k}`);
  }
  // --role <name> expands to --agent <first> --fallback <rest> from CHAINS[role].
  // It refuses --agent/--fallback together (usage exit 2) and an unknown role.
  // It applies the per-ticket Nvidia drop rule: if worker-nvidia dropped (exit timeout/stalled)
  // on 2 earlier rounds in this run dir, the next round leaves worker-nvidia out.
  if (a.role) {
    if (a.agent || a.fallback) throw new Error("--role may not be combined with --agent or --fallback");
    let chain = chainFor(a.role); // throws on unknown role
    const provisionalOut = a.out || path.join(path.dirname(path.resolve(a.prompt)), `${chain[0]}-out.md`);
    const outDir = path.dirname(path.resolve(provisionalOut));
    if (chain[0] === "worker-nvidia" && nvidiaDropCount(outDir) >= 2) chain = chain.slice(1);
    if (Array.isArray(opts.chain) && opts.chain.length) {
      chain = [...opts.chain]; // detached child: the launcher's decision, never a second pace read
    } else if (Object.hasOwn(PACE_POLICY, a.role) && a.session && !a.session.startsWith("ses_")) {
      // A non-`ses_` session is a Claude Code session (a cc-* round): resume it on the role's cc agent (rule 5, same
      // agent and session) whatever the pace; fallback hops start fresh OpenCode sessions. Not a pace decision.
      const cc = PACE_POLICY[a.role];
      if (chain[0] !== cc) chain = [cc, ...chain];
    } else if (!a.session && opts.pace !== undefined) {
      // Pace-aware routing (M4, v2 A4): an `under` pace puts the role's cc agent first (PACE_POLICY). --session pins
      // the backend (a revision round stays on its agent and session), so it never prepends.
      const pace = typeof opts.pace === "function" ? opts.pace() : opts.pace;
      const next = paceChain(a.role, chain, pace);
      if (next.length > chain.length) {
        chain = next;
        a.pacePrepended = true;
      }
    }
    a.agent = chain[0];
    a.fallback = chain.slice(1);
  }

  // Nvidia agents (`*-nvidia`) get tighter stall defaults: idle-min 6, resume 3. Explicit flags win.
  if (isNvidiaAgent(a.agent)) {
    if (!a.idleMinSet) a.idleMin = 6;
    if (!a.resumeSet) a.resume = 3;
  } else {
    if (!a.idleMinSet) a.idleMin = 20;
    if (!a.resumeSet) a.resume = 1;
  }

  for (const req of ["agent", "dir", "prompt"]) if (!a[req]) throw new Error(`--${req} is required`);
  if (a.ticket && !a.owner) throw new Error("--ticket needs --owner");

  a.out ||= path.join(path.dirname(path.resolve(a.prompt)), `${a.agent}-out.md`);

  // Auto-detect images in prompt/mandate and enable vision if found (unless --no-vision was explicit)
  // We do this after parsing so --no-vision can override
  const visionExplicitlySet = argv.includes("--vision") || argv.includes("--no-vision");
  if (!visionExplicitlySet && a.prompt) {
    const promptText = fs.readFileSync(a.prompt, "utf8");
    // Run detection synchronously for file paths and data URLs; URL check is async but we can defer
    const fileAndDataImages = detectImagesInTextSync(promptText, a.dir);
    if (fileAndDataImages.images.length > 0) {
      a.vision = true;
      a.autoVision = true;
      a.autoVisionImages = fileAndDataImages.images;
      a.autoVisionTotalSize = fileAndDataImages.totalSize;
    }
  }
  return a;
}

// Synchronous version for file paths and data URLs (URL HEAD requests are async, skip for auto-detection)
function detectImagesInTextSync(text, workDir) {
  const images = [];
  let totalSize = 0;

  // Match: absolute paths (/path), home paths (~/path), and relative paths (path/to/file.png)
  // Relative paths must contain at least one / and end with image extension
  // Allow preceding: whitespace, backtick, (, [, { (common in markdown/code)
  const filePathRegex = /(?:^|[\s`\(\[\{])((?:~\/|\/)?[\w\-\.\/]*\/[\w\-\.]*?(?:\.png|\.jpg|\.jpeg|\.gif|\.webp|\.bmp|\.svg|\.tiff|\.ico))\b/gim;
  let match;
  while ((match = filePathRegex.exec(text)) !== null) {
    const p = match[1].replace(/^~/, os.homedir());
    const absPath = path.isAbsolute(p) ? p : path.resolve(workDir, p);
    try {
      const stat = fs.statSync(absPath);
      if (stat.isFile() && stat.size <= MAX_IMAGE_SIZE) {
        images.push({ type: "file", path: absPath, size: stat.size });
        totalSize += stat.size;
      }
    } catch {}
  }

  const dataUrlRegex = /data:image\/(png|jpeg|jpg|gif|webp|bmp|svg\+xml);base64,/g;
  while ((match = dataUrlRegex.exec(text)) !== null) {
    const base64Part = text.slice(match.index + match[0].length, match.index + match[0].length + 200);
    const estimatedSize = Math.floor(base64Part.length * 0.75);
    if (estimatedSize <= MAX_IMAGE_SIZE) {
      images.push({ type: "data-url", mime: `image/${match[1]}`, estimatedSize });
      totalSize += estimatedSize;
    }
  }

  // Heuristic: HTTP/HTTPS/www URLs — treat as potential images (no HEAD request in sync mode)
  // Matches http://, https://, or www. URLs
  const urlRegex = /(?:https?:\/\/|www\.)[^\s\)\]\}]+/gim;
  while ((match = urlRegex.exec(text)) !== null) {
    let url = match[0].replace(/[.,;:]+$/, "");
    // Normalize www. to https:// for consistency
    if (url.startsWith("www.")) url = "https://" + url;
    // Skip obvious API/non-image endpoints
    if (/^https?:\/\/(?:api\.|graphql|webhook|webhooks|callback|oauth|auth|token|health|metrics|status|version|ping)\b/i.test(url)) {
      continue;
    }
    // Flag as potential image if:
    // - Has image extension, OR
    // - Known image host patterns, OR
    // - Generic web URL (user may want visual evaluation)
    // Only skip if it's clearly an API endpoint
    const isLikelyImage = /\.(?:png|jpg|jpeg|gif|webp|bmp|svg|tiff|ico)(?:\?|$)/i.test(url) ||
                          /(?:cdn|images|img|assets|media|static|photos|pictures|avatars|thumbnails)\./i.test(url);
    // Be permissive: flag generic URLs too (user asked for visual eval)
    // Only exclude obvious API patterns
    const isApi = /\/api\/|\/v\d+\/|\/graphql|\.json$/i.test(url);
    if (isLikelyImage || !isApi) {
      images.push({ type: "url", url, estimatedSize: 0 });
    }
  }

  return { images, totalSize, overLimit: totalSize > MAX_TOTAL_SIZE };
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

// usage.mjs loadLimits(), imported once and lazily: usage.mjs pulls in node:sqlite, which an old Node build cannot
// load; then every limit below reads as its default. The file is re-read at every call, so an edit takes effect.
let loadLimitsFn = null;
try {
  ({ loadLimits: loadLimitsFn } = await import("./usage.mjs"));
} catch {}
const ccLimit = (key) => {
  try {
    const l = loadLimitsFn ? loadLimitsFn() : null;
    return l?.cc?.[key] ?? l?.[`cc.${key}`];
  } catch {
    return undefined;
  }
};

// The headless Claude Code agents and their models. `cc.models` in usage-limits.json is merged over the default;
// only keys starting "cc-" and non-empty string values count (the pool group and the read-only rule key on "cc-").
export const CC_MODELS_DEFAULT = Object.freeze({ "cc-worker": "sonnet", "cc-worker-strong": "opus", "cc-critic": "opus", "cc-senior": "fable" });
export function ccModels() {
  const merged = { ...CC_MODELS_DEFAULT };
  const m = ccLimit("models");
  if (m && typeof m === "object" && !Array.isArray(m)) {
    for (const [k, v] of Object.entries(m)) if (isCcPool(k) && typeof v === "string" && v.trim()) merged[k] = v.trim();
  }
  return merged;
}
// ORCH_CLAUDE_BIN overrides the binary (tests: a fake .mjs).
export const isCcAgent = (agent) => typeof agent === "string" && Object.hasOwn(ccModels(), agent);
// A cc reader (cc-critic, cc-senior, any configured read-only cc-* agent): read-only tools, the `ccread` slot.
export const isCcReader = (agent) => isCcAgent(agent) && READONLY_AGENT_RE.test(agent);
// The verdict gate's free-ness for a run. A cc agent bills the Claude subscription: paid, explicitly (it has no
// OpenCode pin, so the model lookup alone would only be false by accident).
export const gateFree = (a) => !isCcAgent(a.agent) && (/-free$/.test(a.agent) || /^opencode\/.*-free$/.test(a.model || "") || isPolicyFree(a.model || agentModel(a.agent) || ""));
// The machine-wide provider slot of a cc agent: writers share `cc`, readers share `ccread` (not `cc-read`:
// providerHeld/providerHolders match the `provider-cc-` prefix, so `cc-read` dirs would count as writer slots).
export const ccSlotKey = (agent) => (isCcReader(agent) ? "ccread" : "cc");
// The model a cc agent runs: cc.models[agent]; cc-senior runs opus instead while the pace says fable is over.
export function ccModelFor(agent, { fableOver = false } = {}) {
  if (agent === "cc-senior" && fableOver) return "opus";
  return ccModels()[agent] || "sonnet";
}
// --tools and permission flags: writers keep cc-worker's argv; readers get no Edit/Write and no acceptEdits.
export function ccToolArgs(agent) {
  if (isCcReader(agent)) return ["--tools", "Read,Grep,Glob,Bash", "--strict-mcp-config", "--allowedTools", "Bash", "--disallowedTools", "Edit,Write,NotebookEdit"];
  return ["--tools", "Read,Grep,Glob,Edit,Write,Bash", "--strict-mcp-config", "--permission-mode", "acceptEdits", "--allowedTools", "Bash"];
}
export const CC_SETTINGS = JSON.stringify({ disableAllHooks: true });
export function claudeBin() {
  const env = process.env.ORCH_CLAUDE_BIN;
  if (env && /\.m?js$/.test(env)) return { cmd: process.execPath, pre: [env], shell: false };
  return { cmd: env || "claude", shell: false };
}

// `cc.<key>` from usage-limits.json (e.g. max_workers, max_readers): a positive integer, else `dflt`.
// Returns a synchronous cap reader (acquireProviderSlot asks it at every poll, so an edited file takes effect).
export function capReader(key, dflt = 1) {
  return () => {
    const n = Number(ccLimit(key));
    return Number.isInteger(n) && n >= 1 ? n : dflt;
  };
}
// `cc.reader_wait_min` (default 10): how long a cc reader waits for `ccread` before its chain moves on.
export function ccReaderWaitMin() {
  const n = Number(ccLimit("reader_wait_min"));
  return Number.isFinite(n) && n > 0 ? n : 10;
}
// A cc reader gave up waiting for its `ccread` slot: runChain skips to the next agent (no attempt used).
export class CcSlotTimeout extends Error {}
// A cc reader whose role contract is missing: runChain skips to the next agent (no attempt used), never contract-less.
export class CcNoContract extends Error {}

// The role contract of a cc reader (cc-pacing-v2 A4 r2): the installed Claude Code agent file of its role,
// <ORCH_HOME or home>/.claude/agents/<agent without "cc-">.md (cc-critic → critic.md, cc-senior → senior.md; same home
// rule as install.mjs homeDir). `claude -p` gets only the short pointer prompt, so without this the run has no critic or
// senior contract (VERDICT first line, findings, BLAST RADIUS) and the verdict gate reads it INVALID.
export function ccContractFile(agent) {
  return path.join(process.env.ORCH_HOME || os.homedir(), ".claude", "agents", `${String(agent).replace(/^cc-/, "")}.md`);
}
/** The contract body (frontmatter stripped), or null when the file is missing, unreadable or has an empty body. */
export function ccContract(agent) {
  let text;
  try {
    text = fs.readFileSync(ccContractFile(agent), "utf8");
  } catch {
    return null;
  }
  const m = text.match(/^\uFEFF?---\r?\n[\s\S]*?\r?\n---[ \t]*(?:\r?\n|$)/);
  const body = (m ? text.slice(m[0].length) : text).trim();
  return body ? body + "\n" : null;
}

function alive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return e.code === "EPERM";
  }
}

// Exported, test-replaceable priority setter: nice 10 for opencode children on non-win32.
export const prio = { set: (pid, n) => os.setPriority(pid, n) };
let prioWarned = false;

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
//
// `acquireSlot(n, opts)` — fixed mode when `n` is an integer (legacy signature, WORKER_SLOTS/--slots).
// `acquireSlot(cfg, opts)` — dynamic mode when `cfg` is {mode, min, max} from slotConfig().
// Test injection via opts: sample (object/null/function returning one per poll), cfg, now (ms).
// Dynamic mode admits only slots 1..allowed; slots above min are gated by the burst guard.
// A decision log line is written on admission and whenever `allowed` changes (never every poll).
// `opts.agent`/`title`/`out` are written to the slot owner file so waiters can name holders.
// `opts.onWait(info)` is called (stderr line, registry update) each poll while no slot is free;
// info = { type: "worker", cap, mode, holders: [{pid, agent, title, out}] }.
export async function acquireSlot(nOrCfg, { pollMs = 3000, deadline = Infinity, pid = process.pid, sample: injectedSample, cfg: injectedCfg, now: injectedNow, state: injectedState, agent, title, out, onWait } = {}) {
  fs.mkdirSync(slotDir(), { recursive: true });
  const isDynamic = typeof nOrCfg === "object" && nOrCfg !== null && nOrCfg.mode;
  const cfg = isDynamic ? (injectedCfg || nOrCfg) : { mode: "fixed", n: nOrCfg };
  let state = injectedState || { clearSince: null };
  let lastAllowed = null;
  let waitedSince = null; // ms when this run started waiting (null = not waiting right now)
  let claimedDir = null;
  for (;;) {
    const now = injectedNow !== undefined ? injectedNow : Date.now();
    let sample;
    if (isDynamic) {
      if (typeof injectedSample === "function") sample = injectedSample();
      else sample = injectedSample !== undefined ? injectedSample : readSample();
    }
    const { allowed, max, reason, state: newState } = allowedSlots(sample, cfg, state, now);
    state = newState;
    if (allowed !== lastAllowed) {
      decisionLog({ allowed, held: heldCount(), sample, reason });
      lastAllowed = allowed;
    }
    for (let i = 1; i <= allowed; i++) {
      const d = path.join(slotDir(), `slot-${i}`);
      if (isDynamic && i > cfg.min && !burstGuardOk(now)) continue; // above the floor: one admission per 60 s
      try {
        fs.mkdirSync(d);
        fs.writeFileSync(path.join(d, "owner"), JSON.stringify({ pid, agent, title, out, since: new Date().toISOString() }));
        decisionLog({ allowed, held: heldCount(), sample, reason }); // admission
        claimedDir = d;
        break;
      } catch {
        let owner = null;
        try {
          owner = JSON.parse(fs.readFileSync(path.join(d, "owner"), "utf8"));
        } catch {}
        const age = Date.now() - fs.statSync(d).mtimeMs;
        if ((owner && !alive(owner.pid)) || (!owner && age > 60000)) fs.rmSync(d, { recursive: true, force: true });
      }
    }
    if (claimedDir) break;
    // No slot free this poll: report the wait (on entry and every poll thereafter; the caller throttles the
    // stderr line to once a minute, the registry update is cheap).
    if (waitedSince === null) waitedSince = now;
    const holders = slotHolders("slot");
    if (onWait) onWait({ type: "worker", cap: cfg.mode === "fixed" ? cfg.n : allowed, mode: cfg.mode, holders });
    if (now > deadline) {
      throw new Error(cfg.mode === "fixed"
        ? `no free worker slot (WORKER_SLOTS=${cfg.n})`
        : `no free worker slot (${reason})`);
    }
    await new Promise((r) => setTimeout(r, pollMs));
  }
  // The release stays callable (`release()`, the legacy contract) and also carries the wait start
  // (`release.waitedSince`) so existing callers and the receipt's `queued_s` both work.
  const release = () => fs.rmSync(claimedDir, { recursive: true, force: true });
  release.release = release;
  release.waitedSince = waitedSince;
  return release;
}

// Read live holders of slot-<i> or provider-<name>-<i> dirs, returning {pid, agent, title, out} for each.
// A dir whose owner pid is dead (or that never got an owner file and is older than 60 s) is skipped.
function slotHolders(prefix) {
  const holders = [];
  let names;
  try { names = fs.readdirSync(slotDir()); } catch { return holders; }
  for (const n of names) {
    const re = prefix === "slot" ? /^slot-(\d+)$/ : new RegExp(`^provider-${prefix}-(\\d+)$`);
    const m = re.exec(n);
    if (!m) continue;
    const d = path.join(slotDir(), n);
    let owner = null;
    try { owner = JSON.parse(fs.readFileSync(path.join(d, "owner"), "utf8")); } catch {}
    if (!owner || !owner.pid || !alive(owner.pid)) continue;
    holders.push({ pid: owner.pid, agent: owner.agent || "-", title: owner.title || "-", out: owner.out || "-" });
  }
  return holders.sort((x, y) => x.pid - y.pid);
}

export const isNvidiaModel = (m) => typeof m === "string" && m.startsWith("nvidia/");

// Live holders of provider-<name>-* slots (queued event only; never reclaims).
export function providerHeld(provider) {
  let count = 0;
  let names;
  try { names = fs.readdirSync(slotDir()); } catch { return 0; }
  for (const n of names) {
    if (!n.startsWith(`provider-${provider}-`)) continue;
    let owner;
    try { owner = JSON.parse(fs.readFileSync(path.join(slotDir(), n, "owner"), "utf8")); } catch {}
    if (owner && owner.pid && alive(owner.pid)) count++;
  }
  return count;
}

// Live holders of provider-<name>-<i> dirs, oldest claim first (ties: lowest index). A dir whose owner pid is dead
// (or that never got an owner file and is older than 60 s) is reclaimed here. A young dir without an owner yet is a
// claim in progress: it counts as a holder, ranked last.
function providerHolders(provider) {
  const holders = [];
  let names;
  try { names = fs.readdirSync(slotDir()); } catch { return holders; }
  for (const n of names) {
    const m = new RegExp(`^provider-${provider}-(\\d+)$`).exec(n);
    if (!m) continue;
    const d = path.join(slotDir(), n);
    let owner = null;
    try { owner = JSON.parse(fs.readFileSync(path.join(d, "owner"), "utf8")); } catch {}
    let age = 0;
    try { age = Date.now() - fs.statSync(d).mtimeMs; } catch { continue; }
    if ((owner && !alive(owner.pid)) || (!owner && age > 60000)) {
      fs.rmSync(d, { recursive: true, force: true });
      continue;
    }
    const since = owner ? Date.parse(owner.since) : NaN;
    holders.push({ index: Number(m[1]), pid: owner?.pid, since: Number.isFinite(since) ? since : Infinity });
  }
  return holders.sort((x, y) => x.since - y.since || x.index - y.index);
}

// Machine-wide slot for one provider under slotDir()/provider-<name>-<i>: atomic mkdir, dead-owner reclaim.
// Admission is COUNT-based: a run is admitted only while the live holders number fewer than the cap, and then it
// takes any free index. So after a 429 lowers the cap, in-flight runs keep their slots (never revoked) and new runs
// queue until live holders < cap, whichever indexes are free. Race: after the mkdir the claimant re-reads the
// holders; it keeps its claim only if fewer than `cap` holders rank before it (oldest `since` first, ties by lowest
// index), otherwise it removes its dir and keeps waiting. The order is total and older holders always rank first,
// so simultaneous claimants cannot all back off, and an in-flight run is never displaced.
// `opts.agent`/`title`/`out` are written to the slot owner file; `opts.onWait(info)` is called each poll while waiting.
// Returns { release, index, cap, waitedSince }. Claimed before the machine slot and before the run's clock starts.
export async function acquireProviderSlot(provider, capOrFn, { pollMs = 3000, deadline = Infinity, pid = process.pid, agent, title, out, onWait } = {}) {
  fs.mkdirSync(slotDir(), { recursive: true });
  let waitedSince = null;
  for (;;) {
    const cap = typeof capOrFn === "function" ? capOrFn() : capOrFn; // a function is asked at every poll
    const holders = providerHolders(provider);
    if (holders.length < cap) {
      const taken = new Set(holders.map((h) => h.index));
      let i = 1;
      while (taken.has(i)) i++;
      const d = path.join(slotDir(), `provider-${provider}-${i}`);
      let claimed = false;
      try {
        fs.mkdirSync(d);
        claimed = true;
        fs.writeFileSync(path.join(d, "owner"), JSON.stringify({ pid, agent, title, out, since: new Date().toISOString() }));
      } catch {}
      if (claimed) {
        const rank = providerHolders(provider).findIndex((h) => h.index === i && h.pid === pid);
        if (rank >= 0 && rank < cap) return { index: i, cap, release: () => fs.rmSync(d, { recursive: true, force: true }), waitedSince };
        fs.rmSync(d, { recursive: true, force: true }); // lost the race: back off and keep waiting
      }
    }
    // No provider slot free this poll: report the wait (on entry and every poll thereafter).
    if (waitedSince === null) waitedSince = Date.now();
    const ph = slotHolders(provider);
    if (onWait) onWait({ type: provider, cap, mode: "fixed", holders: ph });
    if (Date.now() > deadline) throw new Error(`no free ${provider} slot (${provider.toUpperCase()}_SLOTS=${cap})`);
    await new Promise((r) => setTimeout(r, pollMs));
  }
}

// Short box-wide lock around an above-floor admission: while a lock dir is held (or younger than 30 s)
// another admission is in progress; if any live slot was claimed within the last 60 s, deny this one.
// Slots 1..min are claimed without the guard.
function burstGuardOk(now) {
  const lock = path.join(slotDir(), "admit.lock");
  let released;
  try {
    try {
      const st = fs.statSync(lock);
      if (Date.now() - st.mtimeMs > 30000) fs.rmSync(lock, { recursive: true, force: true });
    } catch {}
    fs.mkdirSync(lock);
    released = () => { try { fs.rmSync(lock, { recursive: true, force: true }); } catch {} };
  } catch {
    return false; // lock held: treat as a concurrent recent admission
  }
  try {
    const cutoff = now - 60000;
    let names;
    try { names = fs.readdirSync(slotDir()); } catch { return true; }
    for (const n of names) {
      if (!n.startsWith("slot-")) continue;
      let owner;
      try { owner = JSON.parse(fs.readFileSync(path.join(slotDir(), n, "owner"), "utf8")); } catch {}
      if (owner && owner.pid && alive(owner.pid)) {
        const since = Date.parse(owner.since);
        if (Number.isFinite(since) && since > cutoff) return false; // a recent admission above the floor
      }
    }
    return true;
  } finally {
    released();
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

// Fold Claude Code's `--output-format stream-json` lines into the same shape summarize() returns.
// The final text is the `result` event's `result`; an `is_error` result is an error (never a final message), so a
// usage limit reads as "no output yet" and the chain can move on. Tokens: input + cache creation as `input`, cache
// reads as `cache_read`; cost is `total_cost_usd`. The `result` event's usage is the source of truth; when no `result`
// event arrived (timeout, kill) the tokens are the `assistant` events' `message.usage`, each `message.id` counted once
// (stream-json repeats a message per content block), with the same mapping.
export function summarizeClaude(lines) {
  const s = { session: null, texts: [], final: "", tokens: { input: 0, output: 0, reasoning: 0, cache_read: 0 }, cost: 0, errors: [] };
  const addUsage = (t, u) => {
    t.input += (u.input_tokens || 0) + (u.cache_creation_input_tokens || 0);
    t.output += u.output_tokens || 0;
    t.cache_read += u.cache_read_input_tokens || 0;
  };
  const seen = new Set();
  const fallback = { input: 0, output: 0, reasoning: 0, cache_read: 0 };
  let sawResult = false;
  for (const line of lines) {
    let e;
    try {
      e = JSON.parse(line);
    } catch {
      continue;
    }
    if (!e || typeof e !== "object") continue;
    s.session ||= e.session_id || null;
    if (e.type === "assistant" && Array.isArray(e.message?.content)) {
      const t = e.message.content.filter((c) => c?.type === "text" && typeof c.text === "string").map((c) => c.text).join("");
      if (t) s.texts.push(t);
    }
    if (e.type === "assistant" && e.message?.usage && typeof e.message.usage === "object") {
      const id = e.message.id;
      if (!id || !seen.has(id)) {
        if (id) seen.add(id);
        addUsage(fallback, e.message.usage);
      }
    }
    if (e.type === "result") {
      sawResult = true;
      if (e.session_id) s.session = e.session_id;
      addUsage(s.tokens, e.usage || {});
      s.cost += Number(e.total_cost_usd) || 0;
      const text = typeof e.result === "string" ? e.result : "";
      if (e.is_error) {
        s.errors.push((text || e.subtype || "claude error").slice(0, 500));
        // the limit/error message also arrives as the last assistant text: it is not the agent's work
        while (s.texts.length && text && s.texts[s.texts.length - 1] === text) s.texts.pop();
      } else if (text) s.final = text;
    }
  }
  if (!sawResult) s.tokens = fallback;
  return { session: s.session, final: s.final, all: s.texts.join("\n\n"), tokens: s.tokens, cost: Number(s.cost.toFixed(6)), errors: s.errors };
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

/** Classify-and-decide for the resume gate above: transient pool-side failures (quota, rate-limit,
 * dropped, provider-error), plus `truncated` for an output-token limit runWorker can resume past. */
export function resumableReason(errors) {
  const text = errors.join("\n");
  // Output-token truncation (e.g. "Response still truncated after two output token limit
  // continuations") is a model output constraint, not a pool failure: its own resume reason
  // so the resume message can tell the worker to split its edits into smaller pieces. Shapes
  // are narrowed to the Mandate's truncation forms so a bare "truncated" error still takes its
  // quota/rate-limit classification via `classify`.
  if (/output.?token.?limit|output.?exceeded|truncat.{0,40}continuation/i.test(text)) return "truncated";
  const r = classify(errors)?.reason;
  return r === "dropped" || r === "quota" || r === "rate-limit" || r === "provider-error" ? r : null;
}

// Per-ticket Nvidia drop rule (routing rule point 3): count receipts in the run dir whose
// agent is worker-nvidia and whose exit is a drop (timeout / stalled). When a run dir has 2
// such receipts, worker-nvidia is left out of the worker chain on the next dispatch — oc-worker
// resumes dropped Nvidia runs on the same session instead of skipping ahead, so after 2 drops
// on this ticket the orchestrator moves to the next pool.
export function nvidiaDropCount(outDir) {
  let count = 0;
  try {
    for (const f of fs.readdirSync(outDir)) {
      if (!f.endsWith(".receipt.json")) continue;
      let r;
      try {
        r = JSON.parse(fs.readFileSync(path.join(outDir, f), "utf8"));
      } catch {
        continue;
      }
      if (r.agent === "worker-nvidia" && (r.exit === "stalled" || r.exit === "timeout") && !r.landed) count++; // a run whose work landed is not a drop
    }
  } catch {}
  return count;
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

// The ticket a run belongs to: the `ticket` string of dirname(--out)/ticket.json (written once by /frood-orchestrator before
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

// Run one git command in <dir> with a hard timeout (process-safety rule: no unbounded spawns).
// Trims only trailing newlines per line so porcelain output keeps its leading status columns
// (` M a.txt` stays ` M a.txt`); `maxBuffer` bounds a huge dirty-tree listing.
function gitTimed(dir, argv, timeoutMs, env) {
  const out = execFileSync("git", ["-C", dir, ...argv], {
    encoding: "utf8",
    windowsHide: true,
    stdio: ["ignore", "pipe", "pipe"],
    timeout: timeoutMs,
    maxBuffer: 10 * 1024 * 1024,
    env,
  }).toString("utf8");
  return out.replace(/\r\n/g, "\n").replace(/\r/g, "\n").replace(/\n+$/, "");
}

// Fresh-tree preflight for a fresh (non--session) worker run with --stream.
// Refuses a stale or dirty tree before the `queued` event and before any slot is taken.
// ticket.json's `base` names the commit the worktree must be built on.
function freshTreeCheck(dir, base) {
  if (!base) {
    console.error(`oc-worker: ticket.json has no "base": skipping fresh-tree check`);
    return;
  }
  // A leading "-" would be read as a git option.
  if (base.startsWith("-")) {
    throw new StreamRefused(`base ${base} starts with '-' — pass a bare commit sha`, 10);
  }
  // 1. --dir is a git work tree; if not, skip the check (warn on stderr).
  let inside;
  try {
    inside = gitTimed(dir, ["rev-parse", "--is-inside-work-tree"], 10000);
  } catch {
    inside = "";
  }
  if (inside !== "true") {
    console.error(`oc-worker: fresh-tree check skipped: ${dir} is not a git work tree`);
    return;
  }
  // 2. Base resolves. origin/<rest>: fetch first (60 s); a failed fetch is a warning only.
  //    GIT_TERMINAL_PROMPT=0 keeps a missing remote from blocking on a credential prompt.
  const fetchEnv = { ...process.env, GIT_TERMINAL_PROMPT: "0" };
  let rest = base;
  if (base.startsWith("origin/")) {
    rest = base.slice("origin/".length);
    // An option-like ref (`origin/-x`) would reach `git fetch origin -x` and be parsed as a flag: refuse it
    // before any git call (B3).
    if (rest.startsWith("-")) {
      throw new StreamRefused(`base ${base} rejects an option-like ref: pass a bare commit sha`, 10);
    }
    try {
      gitTimed(dir, ["fetch", "origin", rest], 60000, fetchEnv);
    } catch {
      console.error(`oc-worker: fetch origin ${rest} failed: fresh-tree check continues`);
    }
  }
  let baseSha;
  try {
    baseSha = gitTimed(dir, ["rev-parse", "--verify", `${base}^{commit}`], 10000);
  } catch {
    throw new StreamRefused(`base ${base} not found in ${dir}`, 10);
  }
  // 3. base must be an ancestor of HEAD.
  let headSha;
  try {
    headSha = gitTimed(dir, ["rev-parse", "HEAD"], 10000);
  } catch {
    headSha = "";
  }
  try {
    gitTimed(dir, ["merge-base", "--is-ancestor", base, "HEAD"], 30000);
  } catch {
    throw new StreamRefused(
      `stale tree: ${base} (${baseSha}) is not an ancestor of HEAD (${headSha || "(unavailable)"}) in ${dir} — rebase onto ${base} or recreate the worktree`,
      10,
    );
  }
  // 4. Tree must be clean (.gitignore honoured). A git-status failure refuses rather than
  //    reading as clean; untracked symlinks/junctions are not counted as dirt.
  let status;
  try {
    status = gitTimed(dir, ["status", "--porcelain"], 10000);
  } catch {
    throw new StreamRefused(`dirty check failed: git status --porcelain failed in ${dir}`, 10);
  }
  const dirty = [];
  for (const line of status.split("\n")) {
    if (line.length === 0) continue;
    if (line.startsWith("?? ")) {
      const p = path.join(dir, line.slice(3));
      let isLink = false;
      try {
        isLink = fs.lstatSync(p).isSymbolicLink();
      } catch {}
      if (isLink) continue; // untracked symlink/junction: not real dirt
    }
    dirty.push(line);
  }
  if (dirty.length) {
    throw new StreamRefused(
      `dirty tree: ${dirty.length} uncommitted path(s) in ${dir} (first: ${dirty[0]}) — commit, stash or remove them before dispatch; another session's work is the owner's call`,
      10,
    );
  }
}

// --stream checks and the `queued` event, before attachTicket and before any slot is taken.
function streamPreflight(a) {
  const stream = a.stream;
  if (!/^[a-z0-9][a-z0-9-]{0,39}$/.test(stream) || !fs.existsSync(path.join(streamsDir(), `${stream}.json`))) throw new StreamRefused(`no stream ${stream}`, 2);
  const out = path.resolve(a.out);
  if (fs.existsSync(out) || fs.existsSync(out + ".receipt.json")) throw new StreamRefused("out exists — use a fresh --out per run", 2);
  // --stream needs a ticket.json beside --out that parses and carries a non-empty string `ticket`:
  // the run id keys off the ticket, and the desk cannot act on a run that has no ticket.
  // Refuse before a slot is taken or anything spawns.
  const ticketPath = path.join(path.dirname(out), "ticket.json");
  if (!fs.existsSync(ticketPath)) throw new StreamRefused(`--stream needs ${ticketPath} beside --out`, 2);
  let ticket;
  try {
    ticket = JSON.parse(fs.readFileSync(ticketPath, "utf8"));
  } catch {
    throw new StreamRefused(`--stream needs ${ticketPath} beside --out: not valid JSON`, 2);
  }
  if (typeof ticket.ticket !== "string" || !ticket.ticket) {
    throw new StreamRefused(`--stream needs ${ticketPath} beside --out: missing non-empty string "ticket"`, 2);
  }
  // Fresh-worker freshness check: refuse a stale or dirty tree before the `queued` event and before any
  // slot is taken. Revision rounds (--session), critics, scouts and seniors are never checked.
  if (!a.session && a.stream && /^(cc-)?worker/.test(a.agent)) {
    freshTreeCheck(path.resolve(a.dir), ticket.base);
  }
  // With --stream the agent writes the report itself (cwd = --dir), so a relative --report would
  // land in the worktree, not the caller's run dir. Require an absolute run-dir path.
  if (a.report && !path.isAbsolute(a.report)) {
    throw new StreamRefused(`--report must be an absolute path with --stream (pass the run-dir path, e.g. ${path.join(path.dirname(out), "report.md")})`, 2);
  }
  const run = runName(a);
  // Queue-time snapshot of the slot decision (fresh sample, clearSince: null) — not the admission outcome.
  const slotsNow = Date.now();
  const slotsReason = allowedSlots(readSample(), a.slotCfg, { clearSince: null }, slotsNow).reason;
  const ev = { key: `run:${run}:queued`, kind: "queued", run, out, pid: process.pid, pid_start: processStart(process.pid), agent: a.agent, ticket: path.join(path.dirname(out), "ticket.json"), slots: slotsReason + (isNvidiaModel(a.model || agentModel(a.agent)) ? `; nvidia ${providerHeld("nvidia")}/${nvidiaCapNow(slotDir()).cap}` : "") + (isCcAgent(a.agent) ? `; ${ccSlotKey(a.agent)} ${providerHeld(ccSlotKey(a.agent))}` : "") };
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

// Filter chain for vision-capable agents when --vision is set. A cc agent (headless Claude) counts as
// vision-capable: it reads image files with its Read tool, so it is never filtered out.
export function filterVisionChain(chain, a) {
  if (!a.vision) return { chain, fallback: false };
  const visionChain = chain.filter((agent) => {
    if (isCcAgent(agent)) return true;
    const model = agentModel(agent);
    return model && isVisionCapable(model) && agentHasVision(agent);
  });
  if (visionChain.length === 0) {
    // Fallback: use original chain but warn in receipt
    return { chain, fallback: true };
  }
  return { chain: visionChain, fallback: false };
}

// The model IDs `opencode models` lists right now, or null when that cannot be known (fail open: nothing is
// filtered). A provider the owner removed from the harness vanishes from this list; a hop on one of its models
// would only fail instantly and use up an attempt. Cached 10 minutes at <ORCH_HOME>/.config/orchestrator/opencode-models.json.
// ORCH_OPENCODE_MODELS_FILE (one ID per line) replaces the listing, for tests.
const MODELS_CACHE_MS = 10 * 60_000;
const modelIds = (text) => new Set(String(text).split(/\r?\n/).map((l) => l.trim()).filter((l) => /^[^\s/]+\/\S+$/.test(l)));
export function opencodeModelSet(now = Date.now()) {
  try {
    if (process.env.ORCH_OPENCODE_MODELS_FILE) {
      const set = modelIds(fs.readFileSync(process.env.ORCH_OPENCODE_MODELS_FILE, "utf8"));
      return set.size ? set : null;
    }
    const cache = path.join(process.env.ORCH_HOME || os.homedir(), ".config", "orchestrator", "opencode-models.json");
    try {
      const c = JSON.parse(fs.readFileSync(cache, "utf8"));
      if (now - Date.parse(c.at) < MODELS_CACHE_MS && Array.isArray(c.models) && c.models.length) return new Set(c.models);
    } catch {}
    const bin = opencodeBin();
    const r = spawnSync(bin.cmd, [...(bin.pre || []), "models"], { encoding: "utf8", timeout: 20000, shell: bin.shell, windowsHide: true });
    if (r.error || r.status !== 0) return null;
    const set = modelIds(r.stdout);
    if (!set.size) return null;
    atomicWrite(cache, JSON.stringify({ at: new Date(now).toISOString(), models: [...set] }) + "\n");
    return set;
  } catch {
    return null;
  }
}

async function runChain(a) {
  if (a.ticket) attachTicket(a); // no ticket, no run: this is the only gate between the board and a launch
  const fullChain = [a.agent, ...(a.fallback || [])];
  const { chain, fallback } = filterVisionChain(fullChain, a);
  const hops = [];
  let r = null;
  let attempts = 0;
  let visionFallbackWarning = false;
  let liveModels; // `opencode models`, read once and only if some hop has a model to check
  const notes = []; // receipt `notes`: chain events that are not errors of the run that answered (cc-slot-timeout, cc-no-contract)
  for (let i = 0; i < chain.length && attempts < 3; i++) {
    const agent = chain[i];
    // The first hop reuses `a` (its --session, --model) only when it is the agent `a` books: after the vision
    // filter dropped a.agent, chain[0] is another agent and runs fresh, with its own pinned model.
    const first = i === 0 && agent === a.agent;
    const cc = isCcAgent(agent);
    const model = cc ? ((first && a.model) || ccModelFor(agent, a)) : (first && a.model) || agentModel(agent);
    const poolKey = cc ? agent : model; // pool-health key: a cc agent is keyed by its name whatever --model says
    if (model && !modelAllowed(model)) {
      hops.push({ agent, model, skipped: true, reason: policyReason(model) });
      continue;
    }
    // A model the harness no longer lists (its provider was removed) is skipped before a spawn and costs no attempt.
    if (model && !cc) {
      if (liveModels === undefined) liveModels = opencodeModelSet();
      if (liveModels && !liveModels.has(model)) {
        hops.push({ agent, model, skipped: true, reason: "absent: not in opencode models" });
        continue;
      }
    }
    const down = isDown(poolKey);
    if (down) {
      hops.push({ agent, model, skipped: true, reason: `${down.reason} until ${down.until}` });
      continue;
    }
    attempts++;
    // a new pool means a new session; a resumed session belongs to the first pool only
    const hopStartedAt = Date.now(); // markUp keeps a cc group mark written after this
    try {
      r = await runWorker(first ? a : { ...a, agent, session: undefined, model: undefined });
    } catch (e) {
      if (!(e instanceof CcSlotTimeout) && !(e instanceof CcNoContract)) throw e;
      attempts--; // nothing was spawned; r keeps the previous hop's result, if any
      hops.push({ agent, model, skipped: true, reason: e.message });
      notes.push(e.message);
      continue;
    }
    attempts += (r.attempts ?? 1) - 1; // cap 3 counts spawns: a resumed run used more than one
    if (r.exit === "killed") break; // the owner stopped this run: no fallback hop, no pool-health change
    const anyCls = classify(r.classifyErrors ?? r.errors, poolKey);
    // A pool that died mid-run (output already produced) is still down for the next run.
    // A cc usage / rate limit is the subscription's: every cc.models key goes down with the same reset. Any other
    // cc failure (dropped, provider-error) marks only this agent's key.
    const markPool = (c) => (cc && (c.reason === "quota" || c.reason === "rate-limit") ? markGroupDown(Object.keys(ccModels()), { ...c, detail: r.errors[0] || "" }) : markDown(poolKey, { ...c, detail: r.errors[0] || "" }));
    if (anyCls && r.first_line) markPool(anyCls);
    const cls = !r.first_line ? anyCls : null;
    if (!cls) {
      if (r.first_line && !anyCls) markUp(poolKey, { startedAt: hopStartedAt });
      break;
    }
    markPool(cls);
    if (i === chain.length - 1) break; // nothing left to move to: this failure is the result
    hops.push({ agent, model, session: r.session, error: (r.errors[0] || "").slice(0, 200) });
  }
  if (fallback && r) {
    visionFallbackWarning = true;
  }
  if (!r && hops.every((h) => /^policy:/.test(h.reason))) {
    const m = hops[0]?.model || a.model || agentModel(a.agent);
    r = notAllowedReceipt(a, m);
  }
  if (!r) {
    // every pool in the chain is known-down: fail fast, no calls made. When every hop was a cc reader that gave up
    // waiting for its ccread slot (a lone cc-critic with the slot held), the exit names that instead.
    const slotTimeout = hops.length > 0 && hops.every((h) => /^cc-slot-timeout/.test(h.reason || ""));
    const m = isCcAgent(a.agent) ? a.model || ccModelFor(a.agent, a) : a.model || agentModel(a.agent);
    r = { agent: a.agent, model: m || "(agent default)", session: null, exit: slotTimeout ? "cc-slot-timeout" : "no-healthy-pool", seconds: 0, tokens: null, cost: 0, first_line: "", verdict: null, out: null, partial: false, errors: noPoolErrors(hops), status: 6 };
  }
  if (hops.length) r.repooled_from = hops;
  if (notes.length) r.notes = notes;
  r.cc_pace = a.ccPace ?? ccPaceRecord(null, false, a.role ?? null); // the launch's one pace read (main block), on every receipt
  if (visionFallbackWarning) r.vision_fallback = "no vision-capable agent available, using first healthy agent";
  // Record auto-vision detection info
  if (a.autoVision) {
    r.vision = {
      auto_detected: true,
      images_detected: a.autoVisionImages.length,
      total_bytes: a.autoVisionTotalSize,
      images: a.autoVisionImages.map(img => ({ type: img.type, path: img.path || img.url || img.mime, size: img.size || img.estimatedSize }))
    };
  } else if (a.vision) {
    r.vision = { auto_detected: false, explicit: true };
  }
  if (hops.length || r.status === 6 || r.status === 8) {
    fs.mkdirSync(path.dirname(path.resolve(a.out)), { recursive: true });
    atomicWrite(path.resolve(a.out) + ".receipt.json", JSON.stringify({ ...r, status: undefined }, null, 2) + "\n");
  }
  return r;
}

// Why no hop ran: known-down pools, plus the models `opencode models` no longer lists (named, so the owner sees what vanished).
function noPoolErrors(hops) {
  const absent = hops.filter((h) => /^absent:/.test(h.reason || "")).map((h) => h.model);
  const why = !absent.length ? "known-down (pool-health); run router-health or wait"
    : absent.length === hops.length ? "absent from opencode models"
    : "absent from opencode models or known-down (pool-health)";
  const errors = [`every agent in the chain is ${why}`];
  for (const h of hops) if (/^cc-(slot-timeout|no-contract)/.test(h.reason || "")) errors.push(h.reason);
  if (absent.length) errors.push(`absent from opencode models: ${absent.join(", ")}`);
  return errors;
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
  const wanted = isCcAgent(a.agent) ? (a.model || ccModelFor(a.agent, a)) : a.model || agentModel(a.agent);
  if (!wanted && hasRestrictivePolicy()) return unresolvableReceipt(a); // policy cannot be checked without a model
  if (wanted && !modelAllowed(wanted)) return notAllowedReceipt(a, wanted); // before a slot is taken or opencode started
  const isCc = isCcAgent(a.agent);
  const model = isCc ? wanted : wanted || "(agent default)";
  const bin = isCc ? claudeBin() : opencodeBin();
  const title = a.title || `orch ${a.agent} ${path.basename(dir)}`;
  // A message that starts with "-" (YAML front-matter) would be parsed by `opencode run` as a flag.
  const safe = (m) => (m.startsWith("-") ? "\n" + m : m);

  const promptText = fs.readFileSync(a.prompt, "utf8"); // before the slot: a bad --prompt must not leak a slot, registry entry or timer
  // A cc reader runs with its role contract or not at all (before the slot: a skipped hop holds nothing).
  const ccReader = isCc && isCcReader(a.agent);
  const contract = ccReader ? ccContract(a.agent) : null;
  if (ccReader && !contract) throw new CcNoContract(`cc-no-contract: ${ccContractFile(a.agent)}`);
  // Provider slot first: a run waiting for Nvidia holds no machine slot and has not started its clock.
  let providerSlot = null;
  let releaseMachine = null;
  let queuedMs = 0; // total seconds spent waiting for a slot (nvidia + worker), reported as receipt.queued_s
  const out = path.resolve(a.out);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  // Live registry for the dashboard: one file per running oc-worker, removed when it ends.
  // Register as "queued" before taking any slot, so the desk shows queued runs distinguishable from running.
  const run = registerRun({ agent: a.agent, model, title, dir, out, started: Date.now(), queuedSince: Date.now(), idleMin: a.idleMin, timeoutMin: a.timeoutMin, stream: a.stream ?? null, session: a.session ?? null, state: "queued" });
  const kickTimer = setInterval(() => run.touch(), 20_000);
  // One stderr line when each wait begins and then at most once a minute, naming the slot holders.
  let waitLineAt = 0;
  let waitLineType = null;
  const announceWait = (info) => {
    const now = Date.now();
    if (waitLineType === info.type && waitLineAt && now - waitLineAt < 60_000) return;
    waitLineType = info.type;
    waitLineAt = now;
    const held = info.holders.map((h) => `pid ${h.pid} ${h.agent} ${h.title}`).join(", ");
    const what = info.type; // "worker", "nvidia" or "cc"
    console.error(`oc-worker: waiting for a ${what} slot (cap ${info.cap} ${info.mode}; held by ${held || "none"})`);
  };
  // Signal handlers are installed before any slot wait (A1): a signal while waiting for the Nvidia/provider
  // or the machine slot releases whatever we hold, ends the registry entry and exits 143/130/129 with no
  // receipt (nothing ran). `release()` is safe to call before `releaseMachine` is set.
  let inhibitorChild = null; // D5: dead pid state dropped, never read
  // Sleep inhibitor: while a run is active (slots held → attempt loop's end, resumes included) hold a
  // systemd inhibitor that blocks idle sleep and lid-switch sleep only. Skipped on Windows/macOS and with
  // ORCH_NO_INHIBIT=1; a missing `systemd-inhibit` (or any failed spawn) warns once on stderr and the run
  // continues. Ends by itself after timeout + grace + 5 minutes even if oc-worker dies (D2).
  const releaseInhibitor = () => {
    if (inhibitorChild) {
      try { inhibitorChild.kill("SIGTERM"); } catch {}
      inhibitorChild = null;
    }
  };
  const startInhibitor = () => {
    if (process.platform === "win32" || process.platform === "darwin") return;
    if (process.env.ORCH_NO_INHIBIT === "1") return;
    const bin = process.env.ORCH_INHIBIT_BIN || "systemd-inhibit";
    const timeoutMin = Number.isFinite(a.timeoutMin) ? a.timeoutMin : 30;
    const graceMin = Number.isFinite(a.graceMin) ? a.graceMin : 15;
    const seconds = (timeoutMin + graceMin + 5) * 60;
    let child;
    try {
      child = spawn(bin, [
        "--what=idle:handle-lid-switch",
        "--mode=block",
        "--who=oc-worker",
        `--why=worker run ${title}`,
        "sleep",
        String(seconds),
      ], { detached: true, stdio: "ignore", windowsHide: true });
    } catch (e) {
      console.error(`oc-worker: sleep inhibitor spawn failed (${bin}): ${e.message}`);
      return;
    }
    child.on("error", (e) => {
      console.error(`oc-worker: sleep inhibitor spawn failed (${bin}): ${e.message}`);
    });
    child.unref();
    inhibitorChild = child;
  };
  const release = () => {
    releaseMachine?.();
    providerSlot?.release();
    releaseInhibitor();
  };
  const sig = { name: null, code: null, current: null, wake: null };
  const SIGNALS = { SIGTERM: 143, SIGINT: 130, SIGHUP: 129 };
  // A2: a signal that lands while an attempt or the resume wait is live flips the run to "killed";
  // one that lands only after a clean last attempt leaves the clean receipt intact.
  let inCritical = false;
  let signalledWhileLive = false;
  let postAttempt = false;
  const onSignal = (name) => {
    if (sig.name) return; // idempotent: a second signal never interrupts cleanup
    sig.name = name;
    sig.code = SIGNALS[name];
    sig.wake?.();
    releaseInhibitor(); // the run is ending: release the sleep inhibitor now
    signalledWhileLive = signalledWhileLive || inCritical;
    const cur = sig.current;
    if (!cur && !postAttempt) {
      // Nothing ran and no attempt/resume is live: we are still waiting for a slot (or in the gap right
      // after slot admission). Release anything held and exit without a receipt.
      release();
      clearInterval(kickTimer);
      run.end();
      process.exit(sig.code);
    }
    if (!cur) return; // attempt loop already finished: the normal flow decides "killed" vs clean
    if (process.platform === "win32") return killTree(cur.child);
    try { process.kill(-cur.child.pid, "SIGTERM"); } catch { try { cur.child.kill("SIGTERM"); } catch {} }
    cur.hard = setTimeout(() => killTree(cur.child), 5000); // 5 s to exit, then SIGKILL what is left
  };
  const handlers = Object.keys(SIGNALS).map((n) => [n, () => onSignal(n)]);
  for (const [n, h] of handlers) process.on(n, h);
  try {
    if (isNvidiaModel(wanted)) {
      providerSlot = await acquireProviderSlot("nvidia", () => nvidiaCapNow(slotDir()).cap, {
        pollMs: Number(process.env.ORCH_NVIDIA_POLL_MS) || 3000,
        pid: process.pid,
        agent: a.agent, title, out,
        onWait: announceWait,
      });
      queuedMs += providerSlot.waitedSince != null ? Date.now() - providerSlot.waitedSince : 0;
    }
    // cc writers: at most cc.max_workers headless Claude runs machine-wide (slot `cc`); a waiting writer waits and
    // never fails. cc readers: at most cc.max_readers (slot `ccread`); a reader that waited cc.reader_wait_min gives up
    // (CcSlotTimeout) and runChain moves to the next agent.
    if (isCc) {
      const reader = isCcReader(a.agent);
      const waitMin = reader ? ccReaderWaitMin() : null;
      const deadline = reader ? Date.now() + waitMin * 60000 : Infinity;
      try {
        providerSlot = await acquireProviderSlot(ccSlotKey(a.agent), reader ? capReader("max_readers", 1) : capReader("max_workers", 1), {
          pollMs: Number(process.env.ORCH_CC_POLL_MS) || 3000,
          deadline,
          pid: process.pid,
          agent: a.agent, title, out,
          onWait: announceWait,
        });
      } catch (e) {
        if (reader && Date.now() > deadline) throw new CcSlotTimeout(`cc-slot-timeout: ${a.agent} waited ${waitMin} min for a ccread slot`);
        throw e;
      }
      queuedMs += providerSlot.waitedSince != null ? Date.now() - providerSlot.waitedSince : 0;
    }
    const slotResult = await acquireSlot(a.slotCfg, { pollMs: 3000, pid: process.pid, agent: a.agent, title, out, onWait: announceWait });
    releaseMachine = slotResult.release;
    queuedMs += slotResult.waitedSince != null ? Date.now() - slotResult.waitedSince : 0;
  } catch (e) {
    providerSlot?.release();
    run.end();
    clearInterval(kickTimer);
    throw e;
  }
  // Both slots held: the clock starts now (the time budget does not count slot wait time). The registry
  // heartbeat moves the run out of `queued`, and `started` resets so elapsed/OVERDUE measure the run only.
  run.touch({ state: "running", started: Date.now() });
  let scratchDir = null; // D1: in runWorker scope so the `finally` can remove the scratch dir even if setup throws
  try {
  // D1: the run's try starts right after both slots are held; startInhibitor is its first statement so a
  // throw in the setup gap (fs.createWriteStream, mkdirSync, atomicWrite, findMain, gitStatusZ, ...)
  // still runs release() in the finally below.
  startInhibitor();
  const started = Date.now();
  let effectiveDeadline = started + a.timeoutMin * 60000; // one wall-clock budget for every attempt together
  // Grace: once extended, the dashboard's OVERDUE check must see the extended deadline.
  const graceMin = Number.isFinite(a.graceMin) ? a.graceMin : 15;
  let extendedMin;
  let graceUsed = false; // run scope: one extension per run, not per resume attempt
  let totalSleptMs = 0; // host-sleep time given back to the deadline, capped at 2 h
  // HEAD at run start, for every agent (not only read-only roles): used to detect landed work when a run
  // times out or stalls — a commit after the start HEAD means work landed even though the run was killed.
  let wtHeadBefore = null;
  try { wtHeadBefore = gitOut(dir, ["rev-parse", "HEAD"]); } catch {}
  const events = fs.createWriteStream(out + ".events.jsonl"); // appended across attempts
  const idleMin = a.idleMin ?? 20;
  const resumeMax = a.resume ?? 1;

  // Read-only guard: prepare scratch dir and footer before first attempt
  let isReadOnly = READONLY_AGENT_RE.test(a.agent) && !process.env.ORCH_NO_READONLY_GUARD;
  const guardErrors = []; // guard failures never change the run outcome; they only add error lines
  let preDiff = null;
  let wtStatusBefore = null;
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
  // Vision context injection: when --vision set AND agent has vision: true frontmatter
  let visionFooter = "";
  let visionEnv = {};
  if (a.vision && agentHasVision(a.agent)) {
    visionFooter = `\n- You may receive images. Analyze them as part of your task.`;
    visionEnv = { ORCH_VISION: "1" };
  }
  // The agent writes the report itself (cwd = --dir), so point it at the absolute report path:
  // a relative --report would land in the worktree, not the caller's run dir.
  const reportLine = a.report ? `\nWrite your report to ${path.resolve(a.report)} (absolute path; not the worktree).` : "";
  // Worktree fence: allowed roots, main checkout (if linked), pre-run snapshot, prompt footer.
  const reportDir = a.report ? path.dirname(path.resolve(a.report)) : null;
  const fenceRoots = allowedRoots(dir, out, reportDir);
  const fenceMain = findMain(dir);
  let fenceBefore = null;
  if (fenceMain) {
    const snap = gitStatusZ(fenceMain);
    fenceBefore = snap === null ? null : parseStatusZ(snap);
  }
  const fenceState = { paths: [], restored: [], left: [], suspected: [], notes: [], eventsByPath: new Map() };
  // A cc reader is told to read, not "create and edit files" (the OpenCode readers keep the shared footer).
  const fenceFooter = ccReader ? `\nYour worktree is ${dir}. Read it; do not create or edit files in it.\n` : footer(dir, out, fenceMain);
  // The cc reader's contract goes to `claude` as an appended system prompt file beside the run's out file.
  let contractFile = null;
  if (ccReader) {
    contractFile = out + ".contract.md";
    atomicWrite(contractFile, contract);
  }
  // Small-edit rule up front for writer (non-read-only) agents only: one model response is capped at about
  // 8k output tokens, so edits must be small pieces. Critic, senior and scout prompts do not get it.
  let smallEditFooter = "";
  if (!isReadOnly) {
    smallEditFooter = "\n- Make file changes in small pieces with the edit tool, one function or section at a time, and never write more than about 150 lines in one tool call, because one model response is capped at about 8k output tokens.";
  }
  const base = promptText + reportLine + FOOTER + readonlyFooter + visionFooter + fenceFooter + smallEditFooter;
  const cliFor = (session, message) => {
    if (isCc) {
      // The prompt comes right after -p: --tools and --allowedTools are variadic and would swallow a later positional.
      // --settings disableAllHooks: the owner's Stop hooks must not keep a finished run alive or dirty the worktree.
      // Writers keep cc-worker's argv byte-for-byte; readers swap the tool/permission flags (ccToolArgs) and get their
      // role contract with --append-system-prompt-file, placed before the variadic --tools so it cannot be swallowed.
      const contractArgs = contractFile ? ["--append-system-prompt-file", contractFile] : [];
      const cc = ["-p", safe(message), "--model", model, "--settings", CC_SETTINGS, ...contractArgs, ...ccToolArgs(a.agent), "--permission-prompts", "none", "--output-format", "stream-json", "--verbose"];
      if (session) cc.push("--resume", session);
      return cc;
    }
    // --standalone: a private opencode server on the run's stdio, so killTree ends the session (the server
    // exits when its pipe closes; the proc-tree sweep is the backstop) instead of leaving it writing in the
    // worktree via the shared service (ticket killed-run-stops-agent). Needs opencode >= 2.4 (--standalone).
    const cli = ["run", "--standalone", "--format", "json", "--auto", "--agent", a.agent, "--title", title];
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
      let lastOut = Date.now();      // stall watchdog (updated by stdout + host-sleep hack)
      let lastRealOutput = null;     // real opencode stdout output only — used for the grace window
      let lastTick = Date.now();
      let maxSilence = 0;
      const attemptStart = Date.now();
      let hungToolChild = null; // a descendant tool child killed because it outlived the idle window
      const childEnv = isReadOnly ? { ...workerEnv(), ORCH_SCRATCH: scratchDir, ...visionEnv } : { ...workerEnv(), ...visionEnv };
      if (isCc) childEnv.PEER_WAKE_MAX_MIN = "0"; // backstop for the hook-free flag: no peer-mail wake keeps the run alive
      // Opt-in OpenCode edit fence: merge per-run edit permissions into OPENCODE_CONFIG_CONTENT.
      if (process.env.ORCH_EDIT_FENCE === "1") {
        const existing = childEnv.OPENCODE_CONFIG_CONTENT;
        childEnv.OPENCODE_CONFIG_CONTENT = mergeEditFence(existing, dir, out);
      }
      const child = spawn(bin.cmd, [...(bin.pre || []), ...cli], { cwd: dir, env: childEnv, stdio: ["ignore", "pipe", "pipe"], shell: bin.shell, windowsHide: true, detached: process.platform !== "win32" });
      if (process.platform !== "win32") {
        try { prio.set(child.pid, 10); } catch {
          if (!prioWarned) { prioWarned = true; console.error(`oc-worker: could not set priority 10 on pid ${child.pid}: continuing at default niceness`); }
        }
      }
      if (sig.name) { killTree(child); } // signalled between the loop check and the spawn
      else sig.current = { child, hard: null };
      const tree = child.pid ? watch(child.pid, { since: attemptStart, everyMs: Number(process.env.ORCH_PROCTREE_MS) || 5000 }) : null;
      // Find a tracked descendant that has outlived the idle window (a hung tool child: node --test, npm, ...).
      // Only pids from this run's opencode tree are ever killed — never by name pattern. Exactly one live
      // candidate is the hung command; with more than one (a hung tool next to MCP servers / a pty daemon) the
      // pid cannot be identified and is not guessed — the normal stall kill of opencode runs instead.
      // `t.start` (from ps lstart via toISOString) is wall-clock time, so compare directly against the
      // wall-clock cutoff without skew (proc-tree already applies skew internally for its `since` checks).
      const findHungTool = () => {
        if (!tree) return null;
        const cutoff = Date.now() - idleMin * 60000;
        const candidates = [];
        for (const t of tree.tracked()) {
          const start = Date.parse(t.start);
          if (!Number.isFinite(start) || start >= cutoff) continue;
          if (!alive(t.pid)) continue; // tracked entries stay after death; never target a dead/recycled pid
          candidates.push(t);
        }
        return candidates.length === 1 ? candidates[0] : null;
      };
      let buf = "";
      child.stdout.on("data", (d) => {
        lastOut = Date.now();
        lastRealOutput = Date.now(); // real opencode output, not the host-sleep hack
        events.write(d);
        buf += d;
        let i;
        while ((i = buf.indexOf("\n")) >= 0) {
          lines.push(buf.slice(0, i));
          buf = buf.slice(i + 1);
        }
      });
      child.stderr.on("data", (d) => (stderr += d));
      // Grace: an active run at the deadline gets one extension instead of a kill.
      const GRACE_WINDOW_MS = 5 * 60000; // output within the last 5 minutes counts as active
      const arm = () => {
        clearTimeout(timer); // never leave a stale deadline timer pending when re-arming
        timer = setTimeout(() => {
          const active = lastRealOutput != null && Date.now() - lastRealOutput <= GRACE_WINDOW_MS;
          if (!graceUsed && graceMin > 0 && active) {
            graceUsed = true;
            effectiveDeadline += graceMin * 60000;
            run.touch({ timeoutMin: Math.round((effectiveDeadline - started) / 60000) });
            extendedMin = graceMin;
            arm(); // re-arm for the extended deadline
          } else {
            killReason = "timeout";
            killTree(child);
          }
        }, Math.max(0, effectiveDeadline - Date.now()));
      };
      let timer;
      arm();
      const watchdog = setInterval(() => {
        const now = Date.now();
        if (now - lastTick > 30_000) {
          // The host slept: never call that a stall, and give the stolen time back to the
          // deadline (capped at 2 h total). Re-arm so oc-worker active shows the new limit.
          const slept = sleepGapMs(lastTick, now, WATCHDOG_MS);
          if (slept > 0) {
            const { add, total } = sleepExtensionMs(totalSleptMs, slept, MAX_SLEEP_EXTENSION_MS);
            if (add > 0) {
              totalSleptMs = total;
              effectiveDeadline += add;
              run.touch({ timeoutMin: Math.round((effectiveDeadline - started) / 60000) });
              arm(); // re-arm for the extended deadline
            }
          }
          lastOut = now; // the host slept: never call that a stall
        }
        lastTick = now;
        maxSilence = Math.max(maxSilence, Date.now() - lastOut);
        if (idleMin > 0 && !killReason && Date.now() - lastOut > idleMin * 60000) {
          const hung = findHungTool();
          if (hung) {
            // Kill only the hung tool child; opencode survives and is nudged by the tool failure. Never
            // resolve while `child` is alive: a second opencode on the same session/worktree is exactly the
            // bug killed-run-stops-agent fixed. If it stays silent for another idle window, the normal stall
            // path below kills opencode, and the resume message carries `hungToolChild` into the nudge line.
            hungToolChild = hung;
            try { process.kill(hung.pid, "SIGKILL"); } catch {}
            lastOut = Date.now(); // the tool kill is progress: restart the silence clock
          } else {
            killReason = "stalled";
            killTree(child);
          }
        }
      }, WATCHDOG_MS);
      child.on("error", (e) => {
        if (sig.current?.child === child) { clearTimeout(sig.current.hard); sig.current = null; }
        clearTimeout(timer);
        clearInterval(watchdog);
        tree?.stop();
        reject(e);
      });
      child.on("close", async (code) => {
        clearTimeout(timer);
        clearInterval(watchdog);
        if (sig.current?.child === child) { clearTimeout(sig.current.hard); sig.current = null; }
        if (buf.trim()) lines.push(buf);
        let orphans = [];
        try {
          orphans = (await tree?.sweep()) || [];
        } catch {} // a watcher failure never changes a run's outcome
        tree?.stop();
        resolve({ code, lines, stderr, killReason, maxSilence, orphans, hungToolChild });
      });
    });

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
    let receiptExitOverride;
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
    r = { code: null, lines: [], stderr: "", killReason: null, maxSilence: 0, orphans: [] }; // stands in if signalled before any attempt
    sum = summarize([]);
    errors = [];
    classifyErrors = [];
    for (;;) {
      if (sig.name) break;
      attempts++;
      const t0 = Date.now();
      inCritical = true; // A2: an attempt is live; a signal here flips the run to "killed"
      r = await attempt(cli);
      inCritical = false;
      // Worktree fence: scan this attempt's events for exact escapes; check main for suspected dirt.
      try {
        foldEscapes(fenceState, { lines: r.lines, roots: fenceRoots, dir, main: fenceMain, beforeStatus: fenceBefore, out });
      } catch (e) {
        fenceState.notes.push(`worktree fence scan failed: ${e.message}`);
      }
      for (const o of r.orphans) orphansKilled.push({ pid: o.pid, cmd: String(o.cmd || "").slice(0, 120) });
      if (r.hungToolChild) orphansKilled.push({ pid: r.hungToolChild.pid, cmd: String(r.hungToolChild.cmd || "").slice(0, 120) });
      sum = isCc ? summarizeClaude(r.lines) : summarize(r.lines);
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
      // An Nvidia rate limit shrinks the machine-wide Nvidia cap for the next admissions (slots.mjs nvidiaCap).
      if (isNvidiaModel(wanted) && (resumeReason === "quota" || resumeReason === "rate-limit")) {
        try { recordNvidia429(slotDir()); } catch {}
      }
      const interrupted = r.killReason === "stalled" || resumeReason != null;
      const plainWaitMs = Number(process.env.ORCH_RESUME_WAIT_MS ?? 30_000);
      // A 429 window outlasts a dropped socket: wait it out rather than nudge into the same limit.
      const waitMs = resumeReason === "quota" || resumeReason === "rate-limit"
        ? Math.max(plainWaitMs, Number(process.env.ORCH_RATE_LIMIT_WAIT_MS ?? 60_000))
        : plainWaitMs;
      // A stalled run may be nudged before it produced output (silent stall) only if it has a session id:
      // resuming without one would start a fresh agent whose whole prompt is "Continue…" — it never saw the
      // Mandate. A dropped run also needs output. No session id => no resume (the run fails as stalled).
      const canResumeSilent = r.killReason === "stalled";
      if (sig.name || !interrupted || (!sum.all.trim() && !canResumeSilent) || !sum.session || resumed.length >= resumeMax || Date.now() + waitMs >= effectiveDeadline) break;
      const why = r.killReason === "stalled" ? `no output for ${idleMin} min`
        : resumeReason === "truncated" ? "output token limit"
        : (classifyErrors.find((e) => classify([e])?.reason === resumeReason) || errors[0] || "dropped").slice(0, 80);
      resumed.push({ session: sum.session, reason: why, seconds: Math.round((Date.now() - t0) / 1000) });
      inCritical = true; // A2: the resume wait is live; a signal here flips the run to "killed"
      if (waitMs > 0) await new Promise((res) => { const t = setTimeout(res, waitMs); sig.wake = () => { clearTimeout(t); res(); }; });
      sig.wake = null;
      inCritical = false;
      const msg =
        `The previous run was interrupted (${why}). Continue the task from where you stopped. The Mandate is unchanged.\n` +
        `Before continuing, check the worktree state below and verify any half-finished edit or command.\n\n` +
        `git status --short:\n${gitOut(dir, ["status", "--short"])}\n\ngit diff --stat:\n${gitOut(dir, ["diff", "--stat"])}` +
        (r.hungToolChild ? `\nA tool command ran over ${idleMin} min and was stopped: ${r.hungToolChild.cmd}` : "") +
        (resumeReason === "truncated"
          ? "\nYour last response was cut off at the output token limit; split the remaining edit into smaller pieces, one function or section at a time, and never write more than about 150 lines in one tool call."
          : "") +
        FOOTER;
      cli = cliFor(sum.session, msg);
    }
    postAttempt = true; // A2: the attempt loop finished; a signal now lands after the last attempt
    events.end();
    // Worktree fence: finalize the escape check.
    const { escaped } = finalizeEscapes(fenceState);
    // Any escaped path with a completed write means this run wrote outside its
    // worktree: fail the run so the desk escalates instead of sending it to a
    // critic. Suspected-only or attempted-but-not-completed writes are just a
    // warning in the receipt; exit unchanged.
    if (fenceState.paths.length > 0) {
      errors.push(...fenceState.notes);
      const anyCompleted = Array.from(fenceState.eventsByPath.values()).some(hasCompletedWrite);
      if (anyCompleted) {
        receiptExitOverride = "escaped-worktree";
        errors.push(`escaped-worktree: ${fenceState.paths.length} path(s) written outside the worktree`);
      }
    }
    // Suspected-only (main went dirty, no tool event of ours): `escaped.suspected` in the receipt is the warning;
    // no errors[] entry, exit unchanged. Main is often busy with other sessions.
    const killedBySignal = sig.name && signalledWhileLive; // A2: "killed" only if the signal landed while an attempt/resume was live
    const killReason = killedBySignal ? "killed" : r.killReason;
    if (killedBySignal) errors.push(`killed by ${sig.name}`);
    // Landed work: a timed-out or stalled run whose commit made it in counts as done.
    // HEAD moved, tree is clean, and the --report file's status line says DONE.
    let landed;
    if (killReason === "timeout" || killReason === "stalled") {
      try {
        const headAfter = gitOut(dir, ["rev-parse", "HEAD"]);
        const status = gitOut(dir, ["status", "--porcelain"]);
        const headMoved = wtHeadBefore != null && wtHeadBefore !== "(git unavailable)"
          && headAfter !== "(git unavailable)" && headAfter !== wtHeadBefore;
        const clean = status === "" || status === "(clean)";
        const report = a.report ? statusLine(readText(path.resolve(dir, a.report))) : "";
        const reportDone = report.startsWith("RESULT: DONE");
        if (headMoved && clean && reportDone) landed = { head_before: wtHeadBefore, head_after: headAfter };
      } catch {}
    }
    const all = alls.join("\n\n");
    if (killReason && all.trim()) {
      // Partial work survives a timeout or stall; the status line makes it impossible to mistake for a finished run.
      const why = killReason === "killed" ? `killed by ${sig.name}` : killReason === "stalled" ? `stalled — no output for ${idleMin} min` : `timeout after ${Math.round((effectiveDeadline - started) / 60000)} min`;
      fs.writeFileSync(out, `RESULT: BLOCKED: ${why} — partial output below\n\n${all}\n`);
      sum.final = "";
    } else if (sum.final) fs.writeFileSync(out, sum.final.endsWith("\n") ? sum.final : sum.final + "\n");
    // ORCH_TEST_POSTRUN_PAUSE_MS: test-only pause once <out> has been written, so a test can land a
    // SIGTERM after a clean attempt and assert the receipt stays clean (default 0: no pause).
    const postRunPauseMs = Number(process.env.ORCH_TEST_POSTRUN_PAUSE_MS || 0);
    if (postRunPauseMs > 0) await new Promise((res) => setTimeout(res, postRunPauseMs));
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
    let gateResult = VERDICT_AGENT_RE.test(a.agent) && sum.final
      ? gate(sum.final, { free: gateFree(a) })
      : null;
    if (readonlyViolation && gateResult) gateResult = { ...gateResult, effective: "INVALID", reasons: [...gateResult.reasons, "readonly_violation"] };
    const receipt = {
      agent: a.agent,
      model,
      session: sum.session,
      exit: receiptExitOverride ?? killReason ?? code,
      seconds: Math.round((Date.now() - started) / 1000),
      tokens,
      cost: Number(cost.toFixed(6)),
      first_line: (sum.final.split("\n").find((l) => l.trim()) || "").slice(0, 200),
      // The verdict, wherever the agent put it: final message first, then the --report file.
      verdict: statusLine(sum.final) || (a.report ? statusLine(readText(path.resolve(a.report))) : "") || null,
      out: sum.final || (killReason && all.trim()) ? out : null,
      partial: Boolean(killReason && all.trim()),
      errors,
      max_silence_s: Math.round(maxSilenceMs / 1000),
      queued_s: Math.round(queuedMs / 1000), // seconds spent waiting for a slot (nvidia + worker together)
      resumed,
      attempts,
      ...(providerSlot && !isCc ? { provider_slot: `nvidia ${providerSlot.index}/${providerSlot.cap}` } : {}),
      ...(orphansKilled.length ? { orphans_killed: orphansKilled } : {}),
      ...(landed ? { landed } : {}),
      ...(extendedMin !== undefined ? { extended_min: extendedMin } : {}),
      slept_ms: totalSleptMs, // host-sleep time given back to the deadline (0 when none, capped at 2 h)
      // An orchestrator's own events do not include the subagents it spawned; price the whole tree.
      tree: sum.session && !isCc ? sessionTree(sum.session) : null,
      // Read-only guard fields
      ...(tampered.length ? { tampered } : {}),
      ...(worktreeChanged ? { worktree_changed: worktreeChanged } : {}),
      ...(readonlyViolation ? { readonly_violation: true } : {}),
      // Worktree fence: only present when something escaped or was suspected.
      ...(escaped ? { escaped } : {}),
      // Claude Code weekly pace at launch (M4): read once per launch, never fails the run.
      cc_pace: a.ccPace ?? ccPaceRecord(null, false, a.role ?? null),
      // Critics: the mechanical decision, not the critic's own claim (free critics find, then approve).
      gate: gateResult,
      // Vision metadata
      vision: a.autoVision
        ? { auto_detected: true, images_detected: a.autoVisionImages.length, total_bytes: a.autoVisionTotalSize, images: a.autoVisionImages.map(img => ({ type: img.type, path: img.path || img.url || img.mime, size: img.size || img.estimatedSize })) }
        : a.vision
          ? { auto_detected: false, explicit: true }
          : undefined,
    };
    atomicWrite(out + ".receipt.json", JSON.stringify(receipt, null, 2) + "\n");
    Object.defineProperty(receipt, "classifyErrors", { value: classifyErrors, enumerable: false }); // for runWithFallback; not serialized
    receipt.status = killedBySignal ? sig.code : killReason ? 4 : code ? 5 : sum.final ? 0 : 3;
    // A run with at least one completed escaped write is a failed run (non-zero
    // exit) so the desk escalates instead of sending it to a critic. Status 5 is
    // set only when the receipt exit is escaped-worktree (a completed write);
    // an attempted-only escape (path recorded, no completed write) leaves exit
    // and status unchanged — it is a warning, not a failure.
    if (receipt.exit === "escaped-worktree" && !sig.name) receipt.status = 5;
    return receipt;
  } finally {
    clearInterval(kickTimer);
    run.end();
    release();
    for (const [n, h] of handlers) process.off(n, h);
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
      // An override (e.g. the grace-extended timeoutMin) sticks: later heartbeats call touch() with no argument.
      if (extra) Object.assign(info, extra);
      write();
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
 * STALE (wrapper pid gone — a crash that skipped end()), QUEUED (registered, waiting for a slot:
 * never OVERDUE/QUIET, since its clock has not started). Read-only.
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
    } else if (r.state === "queued") {
      // Waiting for a slot (Nvidia and/or machine-wide): no output yet and not yet on the clock,
      // so it is never OVERDUE/QUIET — the wait itself is the expected state.
      state = "QUEUED";
      detail = `waiting for a slot since ${fmtDur(now - (r.queuedSince || r.started || now))}`;
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

// ORCH_PACE_DECISION (set by detachRun for its child): { cc_pace, chain }. Unreadable → null (the child reads itself).
export function paceDecision(text) {
  if (!text) return null;
  try {
    const d = JSON.parse(text);
    if (!d || typeof d !== "object" || !d.cc_pace || typeof d.cc_pace !== "object") return null;
    const chain = Array.isArray(d.chain) && d.chain.every((x) => typeof x === "string") ? d.chain : null;
    return { cc_pace: ccPaceRecord(d.cc_pace, d.cc_pace.prepended === true, d.cc_pace.role), chain, ...(d.fable_over === true ? { fable_over: true } : {}) };
  } catch {
    return null;
  }
}

// Survive the launcher: re-spawn this script in its own session (setsid) and wait for it, relaying its output and exit
// code; a signal to the launcher ends only the launcher. Returns false when this process should do the run itself:
// it is the detached child (marker set), detach is off (--no-detach, or a non-cc agent without --detach), or Windows.
export function detachRun(a, argv) {
  if (process.env.ORCH_DETACHED_CHILD === "1") {
    delete process.env.ORCH_DETACHED_CHILD; // the run's own children (claude, a nested oc-worker) must not inherit it
    return false;
  }
  if (process.platform === "win32" || !(a.detach ?? isCcAgent(a.agent))) return false;
  const out = path.resolve(a.out);
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const log = out + ".detached.log"; // the child's stderr
  const stdoutFile = out + ".detached.out"; // the child's stdout (the receipt JSON line)
  const errFd = fs.openSync(log, "w");
  const outFd = fs.openSync(stdoutFile, "w");
  // The pace decision travels to the child (ORCH_PACE_DECISION): one read, one chain, one receipt value.
  const decision = a.ccPace ? { ORCH_PACE_DECISION: JSON.stringify({ cc_pace: a.ccPace, chain: a.role ? [a.agent, ...(a.fallback || [])] : null, ...(a.fableOver ? { fable_over: true } : {}) }) } : {};
  const child = spawn(process.execPath, [fileURLToPath(import.meta.url), ...argv], { detached: true, stdio: ["ignore", outFd, errFd], env: { ...process.env, ORCH_DETACHED_CHILD: "1", ...decision }, windowsHide: true });
  fs.closeSync(errFd);
  fs.closeSync(outFd);
  const SIGNALS = { SIGTERM: 143, SIGINT: 130, SIGHUP: 129 };
  for (const [name, code] of Object.entries(SIGNALS)) process.on(name, () => process.exit(code)); // never signal the child
  child.on("error", (e) => {
    console.error(`oc-worker: detached run failed to start: ${e.message}`);
    process.exit(5);
  });
  if (!child.pid) return true; // the error handler exits
  console.error(`oc-worker: detached run pid ${child.pid}, log ${log}`);
  child.on("exit", (code, signal) => {
    const status = code ?? (signal ? 128 + (os.constants.signals[signal] || 0) : 5);
    const done = () => process.exit(status);
    process.stdout.on("error", done); // a closed caller pipe must not change the exit code
    process.stderr.on("error", done);
    process.stderr.write(readText(log), () => process.stdout.write(readText(stdoutFile), done));
  });
  return true;
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
  // Pace (M4): read at most once per launch. A detached child takes the launcher's decision instead.
  const inherited = process.env.ORCH_DETACHED_CHILD === "1" ? paceDecision(process.env.ORCH_PACE_DECISION) : null;
  delete process.env.ORCH_PACE_DECISION; // the run's own children (a nested oc-worker) decide for themselves
  let paceRead;
  const pace = () => (paceRead ??= readPace());
  let a;
  try {
    a = inherited ? args(argv, { chain: inherited.chain }) : args(argv, { pace });
  } catch (e) {
    console.error(`oc-worker: ${e.message}`);
    process.exit(2);
  }
  a.ccPace = inherited ? inherited.cc_pace : ccPaceRecord(pace(), a.pacePrepended === true, a.role ?? null);
  // cc-senior runs opus while fable is over pace: from the same single read (a detached child inherits it).
  a.fableOver = inherited ? inherited.fable_over === true : pace()?.fable?.state === "over";
  // Resolve the fixed/dynamic slot decision once at startup; a usage error exits 2.
  let slotCfg;
  try {
    slotCfg = slotConfig(process.env, a.slots);
  } catch (e) {
    console.error(`oc-worker: ${e.message}`);
    process.exit(2);
  }
  a.slotCfg = slotCfg;
  if (!detachRun(a, argv)) runWithFallback(a)
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

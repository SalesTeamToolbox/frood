// Fake `opencode run --format json` for tests. Behaviour from FAKE_OC_MODE:
//   ok (default) -> emits session/text/step_finish; text echoes agent + whether stdin is closed
//   hang         -> never exits (timeout test)
//   fail         -> exits 1 with stderr
//   silent       -> exits 0 with no text
//   drop         -> one text event, then an error event `read ECONNRESET`, exits 1
//   drop-once    -> `drop` on the first call (marker file in FAKE_OC_STATE_DIR), normal finish on the resumed call;
//                   every call's argv is appended to FAKE_OC_STATE_DIR/calls.jsonl
//   midrun-quota-once -> text + `text-then-quota`-style 429 on the first call, normal finish on the resumed call
//   orphan       -> spawns a detached grandchild (sleeps 60 s, pid in FAKE_OC_STATE_DIR/grandchild.pid), waits
//                   FAKE_OC_ORPHAN_WAIT ms (default 4000) so a watcher can see it, then finishes like `ok` and exits,
//                   leaving the grandchild orphaned
//   hang-after-text -> one text event, then sleeps
//   nudge-once      -> silent forever on the first call; the resumed call finishes (the nudge worked)
//   hung-tool       -> spawns a detached child that sleeps forever, emits one text, then stays silent;
//                      the resumed call records whether the first opencode was alive when it started
//   silent-no-session -> no session id in any event, then sleeps (a stall with nothing to resume)
//   landed          -> git add -A + commit (moves HEAD), writes "RESULT: DONE" to the --report path,
//                     then hangs (a worker that committed and reported done before the timeout killed it)
//   grace-ok        -> one text event immediately, then finishes cleanly after FAKE_OC_DELAY ms
//                     (output at the deadline triggers the grace extension)
//   edit-installed -> writes "modified by fake" to FAKE_OC_TARGET (an installed file), then finishes like ok
//   edit-worktree -> same, for a worktree file
//   escape-edit -> writes FAKE_OC_TARGET and emits a completed edit tool_use for it (a completed escape)
//   escape-edit-attempted -> emits an edit tool_use with status "error" for FAKE_OC_TARGET but writes
//                            nothing (an attempted-only escape: path recorded, no completed write)
//   capture-scratch -> records ORCH_SCRATCH, whether it exists and the
//                    message into FAKE_OC_RECORD, then finishes like ok
//
// Every `run` invocation is bounded by FAKE_OC_MAX_MS (default 300000 ms = 5 min): a timer exits the
// process with code 124 once it elapses, and is unref()ed so it never delays a normal exit. No test needs
// a fixture to outlive 5 minutes, so a hung fake can never strand a suite.
import fs from "node:fs";
import path from "node:path";
import { spawn, spawnSync } from "node:child_process";
const argv = process.argv.slice(2);
// `opencode models`: FAKE_OC_MODELS (comma list) is the listing; FAKE_OC_MODELS_FAIL=1 exits 1;
// with neither set it prints nothing (an empty listing).
if (argv[0] === "models") {
  if (process.env.FAKE_OC_MODELS_FAIL) { process.stderr.write("models: boom\n"); process.exit(1); }
  else {
    if (process.env.FAKE_OC_MODELS) process.stdout.write(process.env.FAKE_OC_MODELS.split(",").join("\n") + "\n");
    process.exit(0);
  }
}
// Max-life guard for every `run` invocation: exit 124 after FAKE_OC_MAX_MS, unref()ed so a normal exit
// is never delayed. The orphan grandchild is killed by this timer too (see below).
let grandchild = null;
const maxMs = Number(process.env.FAKE_OC_MAX_MS || 300000);
const maxTimer = setTimeout(() => {
  try { if (grandchild) grandchild.kill("SIGKILL"); } catch {}
  process.exit(124);
}, maxMs);
maxTimer.unref();
const agent = argv[argv.indexOf("--agent") + 1];
const session = argv.includes("--session") ? argv[argv.indexOf("--session") + 1] : "ses_fake123";
let mode = process.env.FAKE_OC_MODE || "ok";
// quota-<agent>: that agent hits a provider limit, every other agent succeeds
if (mode.startsWith("quota-")) mode = mode.slice(6).split(",").includes(agent) ? "quota" : "ok";
// rate429-<agent>: that agent gets Nvidia's real 429 (the body names no model), every other agent succeeds
if (mode.startsWith("rate429-")) mode = mode.slice(8).split(",").includes(agent) ? "rate429" : "ok";
if (process.env.FAKE_OC_ARGS_FILE) fs.writeFileSync(process.env.FAKE_OC_ARGS_FILE, JSON.stringify({ argv, cwd: process.cwd(), pid: process.pid, testVar: process.env.ORCH_TEST_VAR ?? null }));
// FAKE_OC_STDERR: text written to stderr on every call (a healthy run with benign stderr)
if (process.env.FAKE_OC_STDERR) process.stderr.write(process.env.FAKE_OC_STDERR + "\n");
const dropEvents = () => {
  process.stdout.write(JSON.stringify({ type: "text", sessionID: session, part: { sessionID: session, messageID: "msg_1", type: "text", text: "found candidate A at x.py:12" } }) + "\n");
  process.stdout.write(JSON.stringify({ type: "error", sessionID: session, error: { name: "UnknownError", message: "read ECONNRESET" } }) + "\n");
  process.exit(1);
};
if (mode === "orphan") {
  const gc = spawn(process.execPath, ["-e", "setTimeout(() => {}, 60000)"], { detached: true, stdio: "ignore", windowsHide: true });
  gc.unref();
  grandchild = gc;
  // The detached grandchild must not outlive the fixture's own 5-minute cap: the max-life timer kills it.
  fs.writeFileSync(path.join(process.env.FAKE_OC_STATE_DIR, "grandchild.pid"), String(gc.pid));
  await new Promise((r) => setTimeout(r, Number(process.env.FAKE_OC_ORPHAN_WAIT || 4000)));
  mode = "ok";
}
if (mode === "midrun-quota-once") {
  const dir = process.env.FAKE_OC_STATE_DIR;
  fs.appendFileSync(path.join(dir, "calls.jsonl"), JSON.stringify(argv) + "\n");
  const marker = path.join(dir, "mquota");
  if (!fs.existsSync(marker)) {
    fs.writeFileSync(marker, "1");
    mode = "text-then-quota";
  } else mode = "ok";
}
if (mode === "drop-once") {
  const dir = process.env.FAKE_OC_STATE_DIR;
  fs.appendFileSync(path.join(dir, "calls.jsonl"), JSON.stringify(argv) + "\n");
  const marker = path.join(dir, "dropped");
  if (!fs.existsSync(marker)) {
    fs.writeFileSync(marker, "1");
    mode = "drop";
  } else mode = "ok";
}
if (mode === "edit-installed" || mode === "edit-worktree") {
  fs.writeFileSync(process.env.FAKE_OC_TARGET, mode === "edit-installed" ? "modified by fake\n" : "modified\n");
  mode = "ok";
}
// escape-edit: writes a file outside the worktree (FAKE_OC_TARGET) and emits an
// edit tool_use in the real OpenCode 2.4.1 shape (part.tool, part.state.input,
// path, oldString/newString), so oc-worker's worktree fence can detect it.
// dirty-main: writes FAKE_OC_TARGET (another session's edit, say) without any tool event, then finishes normally.
if (mode === "dirty-main") {
  if (process.env.FAKE_OC_TARGET) fs.writeFileSync(process.env.FAKE_OC_TARGET, "someone else's edit\n");
  mode = "ok";
}
if (mode === "escape-edit") {
  const target = process.env.FAKE_OC_TARGET;
  if (target) {
    fs.writeFileSync(target, "escaped edit by fake\n");
    process.stdout.write(JSON.stringify({
      type: "tool_use",
      sessionID: session,
      part: {
        type: "tool",
        sessionID: session,
        messageID: "msg_escape",
        tool: "edit",
        state: {
          status: "completed",
          input: { path: target, oldString: "original\n", newString: "escaped edit by fake\n" }
        }
      }
    }) + "\n");
  }
  mode = "ok";
}
if (mode === "escape-edit-attempted") {
  const target = process.env.FAKE_OC_TARGET;
  if (target) {
    process.stdout.write(JSON.stringify({
      type: "tool_use",
      sessionID: session,
      part: {
        type: "tool",
        sessionID: session,
        messageID: "msg_escape_attempt",
        tool: "edit",
        state: {
          status: "error",
          input: { path: target, oldString: "original\n", newString: "escaped edit by fake\n" }
        }
      }
    }) + "\n");
  }
  mode = "ok";
}
if (mode === "capture-scratch") {
  const scratch = process.env.ORCH_SCRATCH || "";
  fs.writeFileSync(process.env.FAKE_OC_RECORD, JSON.stringify({ scratch, existed: !!scratch && fs.existsSync(scratch), message: argv[argv.length - 1] }));
  mode = "ok";
}
if (mode === "drop") dropEvents();
else if (mode === "quota") {
  process.stdout.write(JSON.stringify({ type: "error", sessionID: session, error: { type: "provider.go-limit", message: "OpenCode Go weekly usage limit reached", status: 429 } }) + "\n");
  process.exit(1);
} else if (mode === "rate429") {
  const body = JSON.stringify({ status: 429, title: "Too Many Requests" });
  process.stdout.write(JSON.stringify({ type: "error", sessionID: session, error: { type: "provider.rate-limit", message: `Provider request failed with HTTP 429: ${body}`, status: 429, response: { body } } }) + "\n");
  process.exit(1);
} else if (mode === "hang") setInterval(() => {}, 1000);
else if (mode === "text-then-quota") {
  // produces output, then dies on a plan-wide quota (CommandCode style, no retryAfterMs)
  process.stdout.write(JSON.stringify({ type: "text", sessionID: session, part: { sessionID: session, messageID: "msg_1", type: "text", text: "RESULT: DONE partial work" } }) + "\n");
  process.stdout.write(JSON.stringify({ type: "error", sessionID: session, error: { type: "provider.quota", message: "You've reached your weekly usage limit for your plan. Your limit resets at 2099-01-01T00:00:00.000Z.", status: 429 } }) + "\n");
  process.exit(1);
}
else if (mode === "hang-after-text") {
  process.stdout.write(JSON.stringify({ type: "text", sessionID: session, part: { sessionID: session, messageID: "msg_1", type: "text", text: "found candidate A at x.py:12" } }) + "\n");
  setInterval(() => {}, 1000);
}
else if (mode === "nudge-once") {
  // First call: go silent forever (simulates a run that stalls). Resumed call (marker present):
  // produce output and finish — the nudge worked.
  const dir = process.env.FAKE_OC_STATE_DIR;
  const marker = path.join(dir, "nudged");
  if (dir && !fs.existsSync(marker)) {
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(marker, "1");
    // A session id but no text: a silent stall with a session may be nudged (--session). Without a
    // session id a stall must not resume (see silent-no-session).
    process.stdout.write(JSON.stringify({ type: "step_start", sessionID: session, part: { sessionID: session, messageID: "msg_1", type: "step-start" } }) + "\n");
    setInterval(() => {}, 1000); // silent forever: oc-worker will stall and nudge
  } else {
    const ev = (type, part) => process.stdout.write(JSON.stringify({ type, sessionID: session, part: { sessionID: session, messageID: "msg_2", ...part } }) + "\n");
    ev("text", { type: "text", text: "RESULT: DONE\nnudged work\n" });
    ev("step_finish", { type: "step-finish", cost: 0.0012, tokens: { input: 100, output: 20, reasoning: 5, cache: { read: 1000, write: 0 } } });
    process.exit(0);
  }
}
else if (mode === "hung-tool") {
  // Spawns a detached child that sleeps forever (simulates a hung tool: node --test, npm, ...), produces
  // one text event, then goes silent. oc-worker kills the descendant (not opencode) and restarts the
  // silence clock; the fake does not recover, so the next idle window is a normal stall: oc-worker kills
  // opencode and nudges. The resumed call records whether the first opencode was still alive when it
  // started (it must not be), then finishes.
  const dir = process.env.FAKE_OC_STATE_DIR;
  fs.mkdirSync(dir, { recursive: true });
  fs.appendFileSync(path.join(dir, "calls.jsonl"), JSON.stringify({ pid: process.pid, argv }) + "\n");
  const firstPidFile = path.join(dir, "opencode-pid-1");
  if (!fs.existsSync(firstPidFile)) {
    fs.writeFileSync(firstPidFile, String(process.pid));
    const gc = spawn(process.execPath, ["-e", "setTimeout(() => {}, 600000)"], { detached: true, stdio: "ignore", windowsHide: true });
    gc.unref();
    fs.writeFileSync(path.join(dir, "hung-tool-pid"), String(gc.pid)); // the pid oc-worker kills
    process.stdout.write(JSON.stringify({ type: "text", sessionID: session, part: { sessionID: session, messageID: "msg_1", type: "text", text: "found candidate A at x.py:12" } }) + "\n");
    setInterval(() => {}, 1000); // silent: the tool is killed, opencode does not recover, the next window stalls
  } else {
    fs.writeFileSync(path.join(dir, "opencode-pid-2"), String(process.pid));
    let firstAlive = false;
    try { process.kill(Number(fs.readFileSync(firstPidFile, "utf8")), 0); firstAlive = true; } catch {}
    fs.writeFileSync(path.join(dir, "first-alive-at-resume"), firstAlive ? "1" : "0");
    const ev = (type, part) => process.stdout.write(JSON.stringify({ type, sessionID: session, part: { sessionID: session, messageID: "msg_2", ...part } }) + "\n");
    ev("text", { type: "text", text: "RESULT: DONE\ntool-killed work\n" });
    ev("step_finish", { type: "step-finish", cost: 0.0012, tokens: { input: 100, output: 20, reasoning: 5, cache: { read: 1000, write: 0 } } });
    process.exit(0);
  }
}
else if (mode === "silent-no-session") {
  // No session id in any event, then silence: a stall with nothing to resume must never spawn a fresh
  // agent (whose prompt would be only "Continue…" with no Mandate).
  const dir = process.env.FAKE_OC_STATE_DIR;
  if (dir) {
    fs.mkdirSync(dir, { recursive: true });
    fs.appendFileSync(path.join(dir, "calls.jsonl"), JSON.stringify({ pid: process.pid, argv }) + "\n");
  }
  setInterval(() => {}, 1000);
}
else if (mode === "landed") {
  // Commit (moves HEAD) and write a DONE report, then hang: work landed before the kill.
  process.on("SIGTERM", () => process.exit(0));
  process.on("SIGINT", () => process.exit(0));
  const session = argv[argv.indexOf("--session") + 1] || "ses_fake123";
  process.stdout.write(JSON.stringify({ type: "text", sessionID: session, part: { sessionID: session, messageID: "msg_1", type: "text", text: "RESULT: DONE work in progress\n" } }) + "\n");
  try { fs.writeFileSync(path.join(process.cwd(), "landed-work.txt"), "done\n"); } catch {}
  try { spawnSync("git", ["-C", process.cwd(), "add", "landed-work.txt"], { stdio: "pipe", encoding: "utf8", timeout: 10000 }); } catch {}
  try { spawnSync("git", ["-C", process.cwd(), "commit", "-m", "work by fake opencode"], { stdio: "pipe", encoding: "utf8", timeout: 10000 }); } catch {}
  const report = process.env.FAKE_OC_REPORT;
  if (report && !fs.existsSync(report)) {
    try { fs.writeFileSync(report, "RESULT: DONE\nwork landed\n"); } catch {}
  }
  setInterval(() => {}, 1000);
}
else if (mode === "grace-ok") {
  // Emit output right away, then finish cleanly after FAKE_OC_DELAY ms so a grace
  // extension lets the run complete past the original deadline.
  const ev = (type, part) => process.stdout.write(JSON.stringify({ type, sessionID: session, part: { sessionID: session, messageID: "msg_2", ...part } }) + "\n");
  ev("text", { type: "text", text: "RESULT: DONE\ngrace work\n" });
  setTimeout(() => {
    ev("step_finish", { type: "step-finish", cost: 0.0012, tokens: { input: 100, output: 20, reasoning: 5, cache: { read: 1000, write: 0 } } });
    process.exit(0);
  }, Number(process.env.FAKE_OC_DELAY || 500));
}
else if (mode === "fail") {
  process.stderr.write("boom: provider error\n");
  process.exit(1);
} else {
  const ev = (type, part) => process.stdout.write(JSON.stringify({ type, sessionID: session, part: { sessionID: session, messageID: "msg_2", ...part } }) + "\n");
  ev("step_start", { type: "step-start" });
  if (mode !== "silent") {
    ev("text", { type: "text", text: `VERDICT: APPROVED\nagent=${agent}\n` });
    if (process.env.FAKE_OC_BLAST) ev("text", { type: "text", text: "BLAST RADIUS:\n- a.js: no callers affected\n" });
    ev("text", { type: "text", text: "1. [minor] a.js:1 — fine" });
  }
  ev("step_finish", { type: "step-finish", cost: 0.0012, tokens: { input: 100, output: 20, reasoning: 5, cache: { read: 1000, write: 0 } } });
}

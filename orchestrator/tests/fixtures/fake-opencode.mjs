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
//   edit-installed -> writes "modified by fake" to FAKE_OC_TARGET (an installed file), then finishes like ok
//   edit-worktree -> same, for a worktree file; capture-scratch -> records ORCH_SCRATCH, whether it exists and the
//                    message into FAKE_OC_RECORD, then finishes like ok
import fs from "node:fs";
import path from "node:path";
import { spawn } from "node:child_process";
const argv = process.argv.slice(2);
const agent = argv[argv.indexOf("--agent") + 1];
const session = argv.includes("--session") ? argv[argv.indexOf("--session") + 1] : "ses_fake123";
let mode = process.env.FAKE_OC_MODE || "ok";
// quota-<agent>: that agent hits a provider limit, every other agent succeeds
if (mode.startsWith("quota-")) mode = mode.slice(6).split(",").includes(agent) ? "quota" : "ok";
if (process.env.FAKE_OC_ARGS_FILE) fs.writeFileSync(process.env.FAKE_OC_ARGS_FILE, JSON.stringify({ argv, cwd: process.cwd(), testVar: process.env.ORCH_TEST_VAR ?? null }));
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
if (mode === "capture-scratch") {
  const scratch = process.env.ORCH_SCRATCH || "";
  fs.writeFileSync(process.env.FAKE_OC_RECORD, JSON.stringify({ scratch, existed: !!scratch && fs.existsSync(scratch), message: argv[argv.length - 1] }));
  mode = "ok";
}
if (mode === "drop") dropEvents();
else if (mode === "quota") {
  process.stdout.write(JSON.stringify({ type: "error", sessionID: session, error: { type: "provider.go-limit", message: "OpenCode Go weekly usage limit reached", status: 429 } }) + "\n");
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

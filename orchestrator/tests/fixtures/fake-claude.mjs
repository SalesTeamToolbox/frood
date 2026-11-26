// Fake `claude -p ... --output-format stream-json --verbose` for tests. Behaviour from FAKE_CC_MODE:
//   success (default) -> system init, one assistant text, a `result` event with usage + total_cost_usd, exit 0
//   usage-limit       -> init, then an is_error result "Claude AI usage limit reached|<epoch>" (FAKE_CC_RESET_S, default
//                        now + 2 h, epoch seconds), exit 1
//   rate-limit        -> init, then an is_error result "API Error: 429 rate_limit_error", exit 1
//   slow              -> like success, but holds FAKE_CC_DELAY ms (default 1500) after the init event
//   hang              -> init, then sleeps (timeout / signal tests)
//   usage-no-result   -> init, assistant events carrying message.usage (message id "msg-1" twice, as stream-json repeats a
//                        message per content block, then "msg-2"), never a `result` event, then sleeps (token fallback)
//   edit              -> writes fake-edit.txt in its cwd (a write a read-only role must not make), then as success
// FAKE_CC_ARGV_OUT, when set, gets the argv as a JSON array at start.
// Every invocation writes FAKE_CC_ARGS_FILE ({argv, cwd, pid, ppid, peerWakeMaxMin}) at start, so a test sees when the
// run began, which pid to check afterwards, who its parent is and the PEER_WAKE_MAX_MIN it got. The session is the --resume value, else FAKE_CC_SESSION, else
// "cc-ses-fake123".
//
// Every invocation is bounded by FAKE_CC_MAX_MS (default 300000 ms = 5 min): a timer exits the process with
// code 124 once it elapses, and is unref()ed so it never delays a normal exit. No test needs a fixture to outlive
// 5 minutes, so a hung fake can never strand a suite.
import fs from "node:fs";

const argv = process.argv.slice(2);
const maxTimer = setTimeout(() => process.exit(124), Number(process.env.FAKE_CC_MAX_MS || 300000));
maxTimer.unref();
const session = argv.includes("--resume") ? argv[argv.indexOf("--resume") + 1] : process.env.FAKE_CC_SESSION || "cc-ses-fake123";
if (process.env.FAKE_CC_ARGS_FILE) fs.writeFileSync(process.env.FAKE_CC_ARGS_FILE, JSON.stringify({ argv, cwd: process.cwd(), pid: process.pid, ppid: process.ppid, peerWakeMaxMin: process.env.PEER_WAKE_MAX_MIN ?? null }));
if (process.env.FAKE_CC_ARGV_OUT) fs.writeFileSync(process.env.FAKE_CC_ARGV_OUT, JSON.stringify(argv));
const mode = process.env.FAKE_CC_MODE || "success";
const ev = (o) => process.stdout.write(JSON.stringify({ session_id: session, ...o }) + "\n");
const result = (o) => ev({ type: "result", duration_ms: 10, num_turns: 1, ...o });

ev({ type: "system", subtype: "init", model: "claude-sonnet-fake", cwd: process.cwd() });
if (mode === "usage-limit") {
  const reset = Number(process.env.FAKE_CC_RESET_S || Math.floor(Date.now() / 1000) + 7200);
  const text = `Claude AI usage limit reached|${reset}`;
  ev({ type: "assistant", message: { role: "assistant", content: [{ type: "text", text }] } });
  result({ subtype: "success", is_error: true, result: text, total_cost_usd: 0, usage: { input_tokens: 0, output_tokens: 0 } });
  process.exit(1);
} else if (mode === "rate-limit") {
  result({ subtype: "error_during_execution", is_error: true, result: "API Error: 429 rate_limit_error", total_cost_usd: 0, usage: {} });
  process.exit(1);
} else if (mode === "hang") {
  setInterval(() => {}, 1000);
} else if (mode === "usage-no-result") {
  const usage = { input_tokens: 10, output_tokens: 5, cache_creation_input_tokens: 2, cache_read_input_tokens: 100 };
  ev({ type: "assistant", message: { id: "msg-1", role: "assistant", content: [{ type: "text", text: "working on it" }], usage } });
  ev({ type: "assistant", message: { id: "msg-1", role: "assistant", content: [{ type: "tool_use", name: "Edit" }], usage } });
  ev({ type: "assistant", message: { id: "msg-2", role: "assistant", content: [{ type: "text", text: "still going" }], usage: { ...usage, output_tokens: 7 } } });
  setInterval(() => {}, 1000);
} else {
  if (mode === "edit") fs.writeFileSync("fake-edit.txt", "written by fake claude\n");
  if (mode === "slow") await new Promise((r) => setTimeout(r, Number(process.env.FAKE_CC_DELAY || 1500)));
  const text = `RESULT: DONE\nfake claude worked in ${process.cwd()}\n`;
  ev({ type: "assistant", message: { role: "assistant", content: [{ type: "text", text }] } });
  result({
    subtype: "success",
    is_error: false,
    result: text,
    total_cost_usd: 0.0123,
    usage: { input_tokens: 100, output_tokens: 20, cache_creation_input_tokens: 30, cache_read_input_tokens: 1000 },
  });
}

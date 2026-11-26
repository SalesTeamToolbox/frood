// Fake `opencode run --format json --model <model> "Reply with exactly: PONG"` for free-inventory probe tests.
// Behaviour from FAKE_PROBE_OK (comma-separated model ids):
//   model in list -> emits one JSON line with type "text" containing "PONG"
//   model NOT in list -> emits one JSON line with type "error"
import fs from "node:fs";
const argv = process.argv.slice(2);
const modelIdx = argv.indexOf("--model");
const model = modelIdx >= 0 ? argv[modelIdx + 1] : "";
const okList = (process.env.FAKE_PROBE_OK || "").split(",").map((s) => s.trim()).filter(Boolean);
// Agent probes (router-health --probe: `--agent <name>`, no --model) answer when the agent is in FAKE_PROBE_OK_AGENTS;
// FAKE_PROBE_FAIL_BODY replaces the error line they print otherwise (e.g. a quota error).
const agentIdx = argv.indexOf("--agent");
const agent = agentIdx >= 0 ? argv[agentIdx + 1] : "";
const okAgents = (process.env.FAKE_PROBE_OK_AGENTS || "").split(",").map((s) => s.trim()).filter(Boolean);
if (process.env.FAKE_PROBE_LOG) fs.appendFileSync(process.env.FAKE_PROBE_LOG, `${agent || model}\n`);
if (agent && !okAgents.includes(agent) && process.env.FAKE_PROBE_FAIL_BODY) {
  process.stdout.write(process.env.FAKE_PROBE_FAIL_BODY + "\n");
  process.exit(1);
}
const isOk = okList.includes(model) || (agent !== "" && okAgents.includes(agent));
if (process.env.FAKE_PROBE_ARGS_FILE) fs.writeFileSync(process.env.FAKE_PROBE_ARGS_FILE, JSON.stringify({ argv, model }));
if (isOk) {
  process.stdout.write(JSON.stringify({ type: "text", sessionID: "ses_probe", part: { sessionID: "ses_probe", messageID: "msg_1", type: "text", text: "PONG" } }) + "\n");
  process.exit(0);
} else {
  process.stdout.write(JSON.stringify({ type: "error", sessionID: "ses_probe", error: { type: "provider.unavailable", message: "model not available", status: 404 } }) + "\n");
  process.exit(1);
}

import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { checkRouting } from "../bin/check-routing.mjs";

const MODELS = new Set([
  "opencode/mimo-v2.6-flash-free",
  "opencode-go/mimo-v2.6-flash",
  "commandcode/claude-haiku-5-5",
  "commandcode/deepseek/deepseek-v4.1-flash",
  "commandcode/deepseek/deepseek-v4.1-flash-fast",
]);
const RULE = [
  "# routing",
  "Worker `opencode-go/mimo-v2.6-flash`. Critic `commandcode/claude-haiku-5-5`.",
  "- **Dropped (do not route to):** `commandcode/deepseek/deepseek-v4.1-flash-fast` (4.5x worse), `commandcode/Qwen/*`, `claude-sonnet-4-5`.",
  'Never write bare "CC".',
].join("\n");

function fixture(files) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-route-"));
  for (const [rel, text] of Object.entries({ "rules/01-orchestrator-models.md": RULE, ...files })) {
    fs.mkdirSync(path.dirname(path.join(root, rel)), { recursive: true });
    fs.writeFileSync(path.join(root, rel), text);
  }
  return root;
}
const run = (files) => checkRouting({ root: fixture(files), extra: [], models: MODELS });

test("clean config passes; dropped IDs may be documented in rules", () => {
  const r = run({ "commands/x.md": 'use `subagent({ agent: "worker" })` or `opencode-go/mimo-v2.6-flash`' });
  assert.deepEqual(r.problems, []);
});

test("dropped model in a dispatch file fails with file:line", () => {
  const r = run({ "commands/egm.md": "a\nspawn `subagent({ model: \"commandcode/deepseek/deepseek-v4.1-flash-fast\" })`" });
  assert.equal(r.problems.length, 1);
  assert.match(r.problems[0], /^commands\/egm\.md:2 .*dropped model/);
});

test("dropped wildcard family matches", () => {
  const r = checkRouting({
    root: fixture({ "agents/q.md": "model: commandcode/Qwen/Qwen3.8-Max  # oc-only" }),
    extra: [],
    models: new Set([...MODELS, "commandcode/Qwen/Qwen3.8-Max"]),
  });
  assert.ok(r.problems.some((p) => /dropped model `commandcode\/Qwen\/Qwen3.8-Max`/.test(p)));
});

test("unknown model ID fails", () => {
  const r = run({ "commands/x.md": "use commandcode/google/gemini-3.8-flash here" });
  assert.ok(r.problems.some((p) => /unknown model ID `commandcode\/google\/gemini-3.8-flash`/.test(p)));
});

test("Claude Code full model IDs fail; aliases pass", () => {
  const bad = run({ "commands/x.md": 'Task({ model: "claude-sonnet-4-5" })' });
  assert.ok(bad.problems.some((p) => /must be an alias.*claude-sonnet-4-5/.test(p)));
  const agentBad = run({ "agents/w.md": "model: claude-haiku-5-5  # cc-only" });
  assert.ok(agentBad.problems.some((p) => /agent model must be an alias/.test(p)));
  assert.deepEqual(run({ "commands/x.md": 'Agent({ subagent_type: "critic", model: "haiku" })', "agents/w.md": "model: sonnet  # cc-only" }).problems, []);
});

test("bare CC in rules fails, quoted mention passes", () => {
  const r = run({ "rules/02-x.md": 'Critic via CC Haiku.\nWe never say "CC".' });
  assert.equal(r.problems.filter((p) => /bare "CC"/.test(p)).length, 1);
});

test("missing live model list is a warning, not a crash", () => {
  const r = checkRouting({ root: fixture({}), extra: [], models: null });
  assert.equal(r.problems.length, 0);
  assert.equal(r.warn.length, 1);
});

test("worker --agent/--fallback chain that disagrees with CHAINS is flagged with --role", () => {
  const r = run({ "commands/w.md": "run node bin/oc-worker.mjs --agent worker --fallback worker-burst,worker-alt" });
  assert.ok(r.problems.some((p) => /disagrees with CHAINS/.test(p) && /--role worker/.test(p)));
});

test("worker-strong --agent/--fallback chain matching CHAINS still suggests --role", () => {
  const r = run({ "commands/w.md": "run node bin/oc-worker.mjs --agent worker-strong --fallback worker-burst,worker-nvidia,worker-alt,worker-free" });
  assert.ok(r.problems.some((p) => /should use `--role worker-strong`/.test(p)));
});

test("non-worker agent --fallback is not flagged by the worker-chain rule", () => {
  const r = run({ "commands/w.md": "run node bin/oc-worker.mjs --agent critic --fallback critic-alt,critic-free" });
  assert.ok(!r.problems.some((p) => /CHAINS/.test(p)));
});

test("worker-nvidia as --agent is flagged by the worker-chain rule", () => {
  const r = run({ "commands/w.md": "run node bin/oc-worker.mjs --agent worker-nvidia --fallback worker,worker-burst" });
  assert.ok(r.problems.some((p) => /worker-nvidia/.test(p) && /CHAINS/.test(p)));
});

test("worker-free as --agent is flagged by the worker-chain rule", () => {
  const r = run({ "commands/w.md": "run node bin/oc-worker.mjs --agent worker-free --fallback worker-burst" });
  assert.ok(r.problems.some((p) => /worker-free/.test(p) && /CHAINS/.test(p)));
});

test("trailing backtick in --fallback value is stripped", () => {
  const r = run({ "commands/w.md": "run node bin/oc-worker.mjs --agent worker --fallback worker-burst,worker-alt,worker-free`" });
  assert.ok(r.problems.some((p) => /disagrees with CHAINS/.test(p)));
});

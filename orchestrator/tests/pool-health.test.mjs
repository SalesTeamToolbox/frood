import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { classify, markDown, isDown, readHealth, agentModel, markUp } from "../bin/pool-health.mjs";
import { installFixtureGuard } from "./fixtures/fixture-guard.mjs";

// Every fixture child carries this process's suite marker; the guard reaps strays after the suite.
installFixtureGuard();

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");
const FAKE = path.join(HERE, "fixtures", "fake-opencode.mjs");

function home() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-health-"));
  const agents = path.join(h, ".config", "opencode", "agents");
  fs.mkdirSync(agents, { recursive: true });
  for (const [name, model] of [["critic", "commandcode/claude-haiku-5-5"], ["critic-alt", "commandcode/gpt-6-luna"], ["critic-free", "opencode/minimax-m3.1-flash-free"]]) {
    fs.writeFileSync(path.join(agents, `${name}.md`), `---\ndescription: x\nmode: subagent\nmodel: ${model}\n---\nbody\n`);
  }
  return h;
}

test("classify: quota uses retryAfterMs (capped at 7 days); model-not-found is 'unavailable'", () => {
  assert.deepEqual(classify(['{"type":"provider.go-limit","message":"OpenCode Go weekly usage limit reached","status":429,"retryAfterMs":277049000}']), { reason: "quota", ms: 277049000, scope: "provider" });
  assert.equal(classify(["429 rate limit"]).ms, 3600_000);
  assert.equal(classify(['"retryAfterMs":99999999999 quota']).ms, 7 * 24 * 3600_000);
  assert.equal(classify(["Model not found: commandcode/old-model"]).reason, "unavailable");
  assert.equal(classify(["TypeError: boom"]), null);
});

test("classify: Nvidia's real 429 body names no model, so the model passed in makes it a short rate limit", () => {
  // The exact error oc-worker recorded on 2026-11-25: no "nvidia/" anywhere in the text.
  const real = ['{"type":"provider.rate-limit","message":"Provider request failed with HTTP 429: {\\"status\\":429,\\"title\\":\\"Too Many Requests\\"}","status":429,"response":{"body":"{\\"status\\":429,\\"title\\":\\"Too Many Requests\\"}"}}'];
  const m = "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b";
  assert.deepEqual(classify(real, m), { reason: "rate-limit", ms: 5 * 60_000, scope: "model" });
  assert.equal(classify(['{"status":429,"retryAfterMs":120000}'], m).ms, 120_000);
  assert.equal(classify(['{"status":429,"retryAfterMs":99999999}'], m).ms, 30 * 60_000); // clamped to 30 min
  // Without the model (old callers) the same text is still the generic 1-hour quota; other providers unchanged.
  assert.equal(classify(real).reason, "quota");
  assert.equal(classify(real, "commandcode/z-ai/glm-5.3-flash").reason, "quota");
});

test("classify: out of credits is a provider-wide quota, so the provider's other models are skipped too", () => {
  const c = classify(['{"type":"provider.invalid-request","message":"You have insufficient credits to make this request. Please purchase more credits to continue using the service.","status":400}']);
  assert.equal(c.reason, "quota");
  assert.equal(c.scope, "provider");
});

test("markDown/isDown/markUp round trip and entries expire on their own", () => {
  process.env.ORCH_HOME = home();
  markDown("x/m", { reason: "quota", ms: 60_000 });
  assert.equal(isDown("x/m").reason, "quota");
  assert.equal(isDown("x/m", Date.now() + 120_000), null, "expired entry is not down");
  markUp("x/m");
  assert.equal(isDown("x/m"), null);
  assert.equal(agentModel("critic"), "commandcode/claude-haiku-5-5");
  assert.equal(agentModel("nope"), null);
  delete process.env.ORCH_HOME;
});

function run(h, env, ...flags) {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-hw-"));
  fs.writeFileSync(path.join(dir, "p.md"), "review");
  return spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", path.join(dir, "p.md"), "--out", path.join(dir, "o.md"), ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, ...env }, encoding: "utf8",
  });
}

test("a quota failure marks the model down; the next run skips it without calling it", () => {
  const h = home();
  // the fake's quota is a weekly plan limit -> the whole commandcode provider goes down,
  // so critic-alt (also commandcode) is skipped and critic-free (Zen free) runs
  const r1 = run(h, { FAKE_OC_MODE: "quota-critic" }, "--fallback", "critic-alt,critic-free");
  assert.equal(r1.status, 0, r1.stdout + r1.stderr);
  const rec1 = JSON.parse(r1.stdout.trim());
  assert.equal(rec1.agent, "critic-free");
  assert.equal(rec1.repooled_from[1].skipped, true, "critic-alt skipped: same provider is down");
  process.env.ORCH_HOME = h;
  assert.equal(isDown("commandcode/claude-haiku-5-5").reason, "quota");
  assert.equal(isDown("commandcode/gpt-6-luna").key, "commandcode/*");
  delete process.env.ORCH_HOME;
  // second run: critic would succeed now (mode ok), but its provider is known-down -> both skipped without calls
  const r2 = run(h, {}, "--fallback", "critic-alt,critic-free");
  const rec = JSON.parse(r2.stdout.trim());
  assert.equal(rec.agent, "critic-free");
  assert.equal(rec.repooled_from[0].skipped, true);
  assert.match(rec.repooled_from[0].reason, /^quota until /);
});

test("an Nvidia 429 marks only that model down, as a 5-minute rate limit — not a 1-hour quota", () => {
  const h = home();
  fs.writeFileSync(path.join(h, ".config", "opencode", "agents", "critic.md"), "---\ndescription: x\nmode: subagent\nmodel: nvidia/nvidia/nemotron-test\n---\nbody\n");
  const before = Date.now();
  const r = run(h, { FAKE_OC_MODE: "rate429-critic" }, "--fallback", "critic-alt");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(JSON.parse(r.stdout.trim()).agent, "critic-alt");
  process.env.ORCH_HOME = h;
  const down = isDown("nvidia/nvidia/nemotron-test");
  assert.equal(down.reason, "rate-limit");
  const ms = Date.parse(down.until) - before;
  assert.ok(ms > 4 * 60_000 && ms <= 6 * 60_000, `until is ~5 min out, got ${ms} ms`);
  assert.equal(isDown("nvidia/nvidia/other-model"), null, "scope is the model, not the provider");
  delete process.env.ORCH_HOME;
});

test("every pool known-down: exit 6, no call made", () => {
  const h = home();
  process.env.ORCH_HOME = h;
  markDown("commandcode/claude-haiku-5-5", { reason: "quota", ms: 3600_000 });
  markDown("commandcode/gpt-6-luna", { reason: "unavailable", ms: 3600_000 });
  delete process.env.ORCH_HOME;
  const argsFile = path.join(h, "args.json");
  const r = run(h, { FAKE_OC_ARGS_FILE: argsFile }, "--fallback", "critic-alt");
  assert.equal(r.status, 6);
  assert.equal(JSON.parse(r.stdout.trim()).exit, "no-healthy-pool");
  assert.ok(!fs.existsSync(argsFile), "opencode must not be invoked");
  assert.equal(Object.keys(JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "pool-health.json"), "utf8"))).length, 2);
});

test("a long fallback chain reaches its first healthy pool past three known-down ones (no 2-entry cap)", () => {
  const h = home();
  const agents = path.join(h, ".config", "opencode", "agents");
  for (const [name, model] of [["critic-x", "goprov/x-model"], ["critic-y", "zenprov/y-model-free"]]) {
    fs.writeFileSync(path.join(agents, `${name}.md`), `---
description: x
mode: subagent
model: ${model}
---
body
`);
  }
  process.env.ORCH_HOME = h;
  markDown("commandcode/claude-haiku-5-5", { reason: "quota", ms: 3600_000 });
  markDown("commandcode/gpt-6-luna", { reason: "quota", ms: 3600_000 });
  markDown("goprov/x-model", { reason: "quota", ms: 3600_000 });
  delete process.env.ORCH_HOME;
  const r = run(h, {}, "--fallback", "critic-alt,critic-x,critic-y");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const rec = JSON.parse(r.stdout.trim());
  assert.equal(rec.agent, "critic-y");
  assert.equal(rec.repooled_from.filter((x) => x.skipped).length, 3);
});

test("classify: MODEL_NOT_IN_PLAN is its own week-long outage, not a quota", () => {
  const c = classify(['{"type":"provider.auth","message":"MODEL_NOT_IN_PLAN: Claude Opus"}']);
  assert.equal(c.reason, "not-in-plan");
  assert.equal(c.ms, 7 * 24 * 3600_000);
  assert.equal(classify(["GPT-6 Sol available in Pro and above plans or extra on demand"]).reason, "not-in-plan");
});

test("classify: other provider failures are a short provider-error outage (re-pool, retry later)", () => {
  const c = classify(['{"type":"provider.invalid-request","message":"Invalid discriminator value. Expected \'user\' | \'assistant\' at messages.3.role","status":400}']);
  assert.equal(c.reason, "provider-error");
  assert.equal(c.ms, 15 * 60_000);
  assert.equal(classify(["upstream overloaded, try again"]).reason, "provider-error");
  assert.equal(classify(["SyntaxError in user code"]), null, "ordinary failures are not pool failures");
});

test("plan-wide quota marks the whole provider down, until CommandCode's 'resets at' time", () => {
  process.env.ORCH_HOME = home();
  const resetAt = new Date(Date.now() + 5 * 24 * 3600_000).toISOString();
  const c = classify([`{"type":"provider.quota","message":"You've reached your weekly usage limit for your plan. Your limit resets at ${resetAt}.","status":429}`]);
  assert.equal(c.reason, "quota");
  assert.equal(c.scope, "provider");
  assert.ok(Math.abs(c.ms - 5 * 24 * 3600_000) < 60_000, "uses the resets-at time");
  markDown("commandcode/deepseek/deepseek-v4.1-flash", c);
  assert.equal(isDown("commandcode/claude-haiku-5-5").key, "commandcode/*", "every model on the provider is down");
  assert.equal(isDown("opencode/minimax-m3.1-flash-free"), null, "other providers unaffected");
  assert.equal(classify(["429 rate limit, slow down"]).scope, "model");
  delete process.env.ORCH_HOME;
});

test("a quota hit after output still marks the pool down for the next run", () => {
  const h = home();
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-hw-"));
  fs.writeFileSync(path.join(dir, "p.md"), "x");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", path.join(dir, "p.md"), "--out", path.join(dir, "o.md")], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_MODE: "text-then-quota" }, encoding: "utf8",
  });
  assert.equal(r.status, 5, r.stdout + r.stderr);
  process.env.ORCH_HOME = h;
  assert.equal(isDown("commandcode/claude-haiku-5-5").key, "commandcode/*");
  delete process.env.ORCH_HOME;
});

// ── provider policy: free-only / ignored ────────────────────────────────────
function policyHome(entries, agents = {}) {
  const h = home();
  fs.mkdirSync(path.join(h, ".config", "orchestrator"), { recursive: true });
  fs.writeFileSync(path.join(h, ".config", "orchestrator", "providers.json"), JSON.stringify(entries));
  for (const [n, m] of Object.entries(agents)) fs.writeFileSync(path.join(h, ".config", "opencode", "agents", `${n}.md`), `---\nmodel: ${m}\n---\n`);
  return h;
}
const FREE_GOOGLE = { google: { decision: "free-only", allow: ["gemini-*-flash*"], at: "2026-01-01T00:00:00Z", note: "" } };

test("modelAllowed: free-only matches globs after the provider prefix; ignored is rejected; others allowed", async () => {
  const { modelAllowed, providerPolicy, isPolicyFree } = await import("../bin/pool-health.mjs");
  process.env.ORCH_HOME = policyHome({ ...FREE_GOOGLE, nvidia: { decision: "ignored" }, opencode: { decision: "routed" } });
  try {
    assert.deepEqual(providerPolicy("google/gemini-3-flash-preview"), { decision: "free-only", allow: ["gemini-*-flash*"] });
    assert.equal(modelAllowed("google/gemini-3-flash-preview"), true);
    assert.equal(modelAllowed("google/gemini-3-pro"), false);
    assert.equal(modelAllowed("nvidia/anything"), false);
    assert.equal(modelAllowed("opencode/x"), true);
    assert.equal(modelAllowed("unknown/x"), true);
    assert.equal(isPolicyFree("google/gemini-3-flash-preview"), true);
    assert.equal(isPolicyFree("google/gemini-3-pro"), false);
  } finally {
    delete process.env.ORCH_HOME;
  }
});

test("oc-worker exits 8 for a disallowed model and never starts opencode", () => {
  const h = policyHome(FREE_GOOGLE);
  const argsFile = path.join(h, "args.json");
  const r = run(h, { FAKE_OC_ARGS_FILE: argsFile }, "--model", "google/gemini-3-pro");
  assert.equal(r.status, 8, r.stdout + r.stderr);
  assert.match(JSON.parse(r.stdout.trim()).errors[0], /model google\/gemini-3-pro not allowed: provider google is free-only/);
  assert.ok(!fs.existsSync(argsFile), "opencode must not be invoked");
  assert.ok(!fs.existsSync(path.join(h, ".config", "orchestrator", "slots")) || fs.readdirSync(path.join(h, ".config", "orchestrator", "slots")).length === 0, "no slot taken");
});

test("an allowed free-only model runs; its critic gate is APPROVED_FREE", () => {
  const h = policyHome(FREE_GOOGLE);
  const r = run(h, { FAKE_OC_BLAST: "1" }, "--model", "google/gemini-3-flash-preview");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(JSON.parse(r.stdout.trim()).gate.effective, "APPROVED_FREE");
});

test("fallback skips a disallowed agent like a known-down one, recording the policy", () => {
  const h = policyHome(FREE_GOOGLE, { "critic-alt": "google/gemini-3-pro" });
  const r = run(h, {}, "--model", "google/gemini-3-pro", "--fallback", "critic-alt,critic-free");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const rec = JSON.parse(r.stdout.trim());
  assert.equal(rec.agent, "critic-free");
  assert.equal(rec.repooled_from.length, 2);
  for (const hop of rec.repooled_from) assert.deepEqual([hop.skipped, hop.reason], [true, "policy: free-only"]);
});

test("check-routing flags an installed agent pinned to a disallowed model", async () => {
  const { checkRouting } = await import("../bin/check-routing.mjs");
  process.env.ORCH_HOME = policyHome(FREE_GOOGLE, { "critic-alt": "google/gemini-3-pro" });
  try {
    const { problems } = checkRouting({ root: fs.mkdtempSync(path.join(os.tmpdir(), "orch-cr-")), models: null });
    assert.ok(problems.some((p) => /critic-alt\.md.*google\/gemini-3-pro/.test(p)), problems.join("\n"));
  } finally {
    delete process.env.ORCH_HOME;
  }
});

const TEXT_FLASH = ["gemini-*-flash", "gemini-*-flash-lite", "gemini-*-flash-preview", "gemini-*-flash-lite-preview"];

test("free-only built-in deny: non-text modalities are refused even when an allow glob matches", async () => {
  const { modelAllowed } = await import("../bin/pool-health.mjs");
  process.env.ORCH_HOME = policyHome({ google: { decision: "free-only", allow: ["gemini-*"] } });
  try {
    for (const ok of ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]) assert.equal(modelAllowed("google/" + ok), true, ok);
    for (const no of ["gemini-2.5-flash-image", "gemini-2.5-flash-preview-tts", "gemini-live-2.5-flash", "gemini-embedding-001", "gemini-x-audio"]) assert.equal(modelAllowed("google/" + no), false, no);
    process.env.ORCH_HOME = policyHome({ google: { decision: "free-only", allow: TEXT_FLASH } });
    for (const no of ["gemini-2.5-flash-image", "gemini-2.5-flash-preview-tts", "gemini-live-2.5-flash", "gemini-3-pro-preview"]) assert.equal(modelAllowed("google/" + no), false, "text-only allowlist: " + no);
    for (const ok of ["gemini-3-flash-preview", "gemini-2.5-flash", "gemini-2.5-flash-lite"]) assert.equal(modelAllowed("google/" + ok), true, ok);
  } finally {
    delete process.env.ORCH_HOME;
  }
});

test("fail closed: unparsable or non-object providers.json rejects every model; a missing file allows", async () => {
  const { modelAllowed, policyReason } = await import("../bin/pool-health.mjs");
  const h = home();
  process.env.ORCH_HOME = h;
  try {
    assert.equal(modelAllowed("google/gemini-3-flash-preview"), true, "ENOENT means no policy");
    const f = path.join(h, ".config", "orchestrator", "providers.json");
    fs.mkdirSync(path.dirname(f), { recursive: true });
    for (const bad of ["{oops", "[]", "null", "42"]) {
      fs.writeFileSync(f, bad);
      assert.equal(modelAllowed("opencode/anything"), false, bad);
      assert.equal(policyReason("opencode/anything"), "policy: providers.json unreadable");
    }
  } finally {
    delete process.env.ORCH_HOME;
  }
});

test("provider keys are case-insensitive", async () => {
  const { modelAllowed } = await import("../bin/pool-health.mjs");
  process.env.ORCH_HOME = policyHome({ Google: { decision: "free-only", allow: ["gemini-*-flash"] } });
  try {
    assert.equal(modelAllowed("google/gemini-3-flash"), true);
    assert.equal(modelAllowed("google/gemini-3-pro"), false);
  } finally {
    delete process.env.ORCH_HOME;
  }
});

test("oc-worker refuses (exit 8, no launch) when the agent's model is unresolvable and a provider is restricted", () => {
  const h = policyHome(FREE_GOOGLE);
  const argsFile = path.join(h, "args.json");
  const r = run(h, { FAKE_OC_ARGS_FILE: argsFile }, "--agent", "ghost-agent");
  assert.equal(r.status, 8, r.stdout + r.stderr);
  assert.ok(JSON.parse(r.stdout.trim()).errors[0].includes("model unresolvable for agent ghost-agent: pin a model in its agent file"));
  assert.ok(!fs.existsSync(argsFile));
});

test("oc-worker with an unparsable providers.json refuses a pinned model (fail closed)", () => {
  const h = home();
  fs.mkdirSync(path.join(h, ".config", "orchestrator"), { recursive: true });
  fs.writeFileSync(path.join(h, ".config", "orchestrator", "providers.json"), "{oops");
  const r = run(h, {});
  assert.equal(r.status, 8, r.stdout + r.stderr);
  assert.ok(JSON.parse(r.stdout.trim()).errors[0].includes("providers.json unreadable"));
});

test("check-routing reports an agent pinned to a provider with no owner decision (seed providers exempt)", async () => {
  const { checkRouting } = await import("../bin/check-routing.mjs");
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-cr-"));
  process.env.ORCH_HOME = policyHome({ other: { decision: "routed" } }, { scout: "nvidia/m", worker: "opencode-go/m", critic: "other/m" });
  try {
    const { problems } = checkRouting({ root, models: null });
    assert.ok(problems.some((p) => p.includes("scout.md") && p.includes("provider nvidia has no owner decision")), problems.join(String.fromCharCode(10)));
    assert.ok(!problems.some((p) => p.includes("worker.md") || p.includes("critic.md")), "seed and decided providers are fine");
  } finally {
    delete process.env.ORCH_HOME;
  }
});

test("an unrecognised decision value fails closed (hand-edited typo), only 'routed' is unrestricted", async () => {
  const { modelAllowed, hasRestrictivePolicy } = await import("../bin/pool-health.mjs");
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-typo-"));
  const p = path.join(h, ".config", "orchestrator", "providers.json");
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify({ google: { decision: "free_only", allow: ["gemini-*"] }, opencode: { decision: "routed" } }));
  process.env.ORCH_HOME = h;
  try {
    assert.equal(modelAllowed("google/gemini-3-flash-preview"), false, "typo'd decision must not allow");
    assert.equal(modelAllowed("opencode/mimo-v2.6-flash-free"), true, "explicit routed allows");
    assert.equal(hasRestrictivePolicy(), true);
  } finally {
    delete process.env.ORCH_HOME;
  }
});

test("classify: a dropped connection or a stall is 'dropped', after quota/unavailable/provider-error", () => {
  assert.deepEqual(classify(["read ECONNRESET"]), { reason: "dropped", ms: 10 * 60_000 });
  for (const t of ["socket hang up", "ETIMEDOUT", "EPIPE", "fetch failed", "other side closed", "UND_ERR_SOCKET", "stalled — no output for 20 min"]) {
    assert.equal(classify([t]).reason, "dropped", t);
  }
  assert.equal(classify(["429 rate limit; read ECONNRESET"]).reason, "quota", "quota keeps priority");
  assert.equal(classify(["Model not found; ECONNRESET"]).reason, "unavailable");
  assert.equal(classify(["provider.error overloaded; ECONNRESET"]).reason, "provider-error");
});

test("a dropped run (--resume 0) marks its model down as 'dropped'", () => {
  const h = home();
  const r = run(h, { FAKE_OC_MODE: "drop" }, "--resume", "0");
  assert.equal(r.status, 5, r.stdout + r.stderr);
  process.env.ORCH_HOME = h;
  assert.equal(isDown("commandcode/claude-haiku-5-5").reason, "dropped");
  delete process.env.ORCH_HOME;
});

test("benign stderr on a clean run does not mark the model down (and marks it up)", () => {
  const h = home();
  process.env.ORCH_HOME = h;
  markDown("commandcode/claude-haiku-5-5", { reason: "dropped", ms: 60_000 });
  // markDown above is only to prove markUp: the run is skipped while down, so clear it first
  markUp("commandcode/claude-haiku-5-5");
  delete process.env.ORCH_HOME;
  const r = run(h, { FAKE_OC_STDERR: "rate limit warning" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  process.env.ORCH_HOME = h;
  assert.equal(isDown("commandcode/claude-haiku-5-5"), null);
  assert.equal(readHealth()["commandcode/claude-haiku-5-5"], undefined);
  assert.equal(readHealth()["commandcode/*"], undefined);
  delete process.env.ORCH_HOME;
});

test("classify: a model the provider no longer serves is 'absent' for 24 h, scoped to the model", () => {
  const body = '{"type":"provider.no-route","message":"Model unavailable: commandcode/claude-haiku-5-5"}';
  assert.deepEqual(classify([body]), { reason: "absent", ms: 24 * 3600_000, scope: "model" });
  assert.equal(classify(["ProviderModelNotFoundError: x"]).reason, "absent");
  assert.equal(classify(["provider gone not found"]).reason, "absent");
  assert.equal(classify(['{"type":"provider.error","message":"overloaded"}']).reason, "provider-error", "other provider errors unchanged");
});

test("classify: rate-limit, quota, truncation and not-in-plan win over 'absent'", () => {
  assert.equal(classify(["Rate limit: provider nvidia endpoint not found, 429"], "nvidia/x").reason, "rate-limit");
  assert.equal(classify(["Your limit resets at 2099-01-01T00:00:00.000Z. Model unavailable"]).reason, "quota");
  assert.equal(classify(["Model unavailable: output token limit truncated"]).reason, "dropped");
  assert.equal(classify(["MODEL_NOT_IN_PLAN Model unavailable"]).reason, "not-in-plan");
  assert.equal(classify(['{"type":"provider.no-route","message":"Model unavailable: commandcode/claude-haiku-5-5"}']).reason, "absent");
  assert.equal(classify(["the provider endpoint was not found in the weekly report"]), null, "loose prose is not 'absent'");
});

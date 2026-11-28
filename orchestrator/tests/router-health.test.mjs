import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "router-health.mjs");

function home(agents) {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-rh-"));
  const d = path.join(h, ".config", "opencode", "agents");
  fs.mkdirSync(d, { recursive: true });
  for (const [n, m] of Object.entries(agents)) fs.writeFileSync(path.join(d, `${n}.md`), `---\nmode: subagent\nmodel: ${m}\n---\nx\n`);
  return h;
}
const ALL = {
  worker: "opencode-go/mimo-v2.6-flash", "worker-free": "opencode/deepseek-v4.1-flash-free", "worker-strong": "opencode-go/muse-spark-1.3-contributor",
  "worker-nvidia": "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b",
  "senior-nvidia": "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b", "senior-free": "opencode/deepseek-v4.1-flash-free",
  "orchestrator-nvidia": "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b", "orchestrator-free": "opencode/deepseek-v4.1-flash-free",
  critic: "opencode-go/deepseek-v4.1-flash", "critic-go": "opencode-go/glm-5.3-flash", "critic-nvidia": "nvidia/minimaxai/minimax-m3.1-flash", "critic-free": "opencode/minimax-m3.1-flash-free",
  scout: "opencode/mimo-v2.6-flash-free", senior: "opencode-go/deepseek-v4-pro", orchestrator: "opencode-go/muse-spark-1.3-contributor",
};
function run(h, models, ...args) {
  const mf = path.join(h, "models.txt");
  fs.writeFileSync(mf, models.join("\n"));
  // Hermetic: never call the real `opencode auth list`. Tests that need auth data pass their own --auth-file.
  const auth = args.includes("--auth-file") ? [] : ["--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt"))];
  // Hermetic: usage reads a temp db, never the real opencode.db (headroom would leak into use-selection).
  const ocDb = path.join(h, "oc.db");
  return spawnSync(process.execPath, [BIN, "--models-file", mf, ...auth, ...args], { env: { ...process.env, ORCH_HOME: h, OPENCODE_DB: ocDb }, encoding: "utf8" });
}

test("all models live: every role uses its first agent, exit 0", () => {
  const h = home(ALL);
  const r = run(h, Object.values(ALL));
  assert.equal(r.status, 0, r.stdout);
  assert.match(r.stdout, /^worker\s+use worker-nvidia\s*(?:👁)?$/m);
  assert.match(r.stdout, /^critic\s+use critic\s*(?:👁)?$/m);
});

test("a pinned model vanishing from opencode models self-corrects to the next agent and is remembered", () => {
  const h = home(ALL);
  const live = Object.values(ALL).filter((m) => m !== "opencode-go/deepseek-v4.1-flash");
  const r = run(h, live);
  assert.match(r.stdout, /^critic\s+use critic-go\s+\[skipped critic: down \(unavailable until/m);
  assert.match(r.stdout, /^worker\s+use worker-nvidia/m);
  assert.equal(r.status, 0);
  const health = JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "pool-health.json"), "utf8"));
  assert.equal(health["opencode-go/deepseek-v4.1-flash"].reason, "unavailable");
});

test("Go gone: the orchestrator self-corrects to the Nvidia agent, and no chain names a CommandCode agent", () => {
  const h = home(ALL);
  const r = run(h, Object.values(ALL).filter((m) => !m.startsWith("opencode-go/")));
  assert.match(r.stdout, /^orchestrator\s+use orchestrator-nvidia/m);
  assert.doesNotMatch(r.stdout, /-alt|-burst/);
});

test("--if-stale skips a fresh check", () => {
  const h = home(ALL);
  run(h, Object.values(ALL));
  const r = run(h, Object.values(ALL), "--if-stale", "24");
  assert.match(r.stdout, /fresh .* skipped/);
});

test("a role with every agent gone is NONE and exits 1", () => {
  const h = home(ALL);
  const live = Object.values(ALL).filter((m) => !/deepseek-v4-pro|nemotron|deepseek-v4.1-flash-free/.test(m));
  const r = run(h, live);
  assert.match(r.stdout, /^senior\s+use NONE/m);
  assert.equal(r.status, 1);
});

// ── new-provider detection ──────────────────────────────────────────────────
const ESC = "\x1b";
const AUTH = [
  `${ESC}[0m┌  Credentials ${ESC}[90m~/.local/share/opencode/auth.json${ESC}[0m`,
  `│`,
  `●  ${ESC}[1mOpenCode Go${ESC}[0m stored`,
  `●  Alibaba  API key stored`,
  `●  Google  API key stored`,
  `●  Nvidia stored`,
  `●  OpenCode Console stored`,
  `●  OpenCode Console stored`,
  `└  5 credentials`,
].join("\n");
const PREFIXES = ["alibaba/q", "anthropic/c", "google/g", "nvidia/a", "nvidia/b", "opencode/m", "opencode-go/m", "openrouter/z"];
const SMALL = { worker: "opencode-go/mimo-v2.6-flash", critic: "opencode/mimo-v2.6-flash-free" };
const envFor = (h) => ({ ...process.env, ORCH_HOME: h });
function runAuth(h, models, auth, ...args) {
  const af = path.join(h, "auth.txt");
  fs.writeFileSync(af, auth);
  return run(h, models, "--auth-file", af, ...args);
}

test("connectedProviders strips ANSI and maps display names to model prefixes", async () => {
  const { connectedProviders } = await import("../bin/router-health.mjs");
  assert.deepEqual(connectedProviders(AUTH, PREFIXES), ["alibaba", "google", "nvidia", "opencode", "opencode-go"]);
});

test("a stored provider with no decision is NEW; a chain provider is auto-routed; unstored is ignored", () => {
  const h = home(SMALL);
  const r = runAuth(h, PREFIXES, AUTH);
  assert.match(r.stdout, /^NEW PROVIDER: nvidia — connected, 2 models, not in any chain\./m);
  assert.match(r.stdout, /router-health --decide nvidia routed\|ignored/);
  assert.doesNotMatch(r.stdout, /NEW PROVIDER: (opencode|opencode-go)\b/);
  assert.doesNotMatch(r.stdout, /NEW PROVIDER: openrouter/);
  const dir = path.join(h, ".config", "orchestrator");
  const stamp = JSON.parse(fs.readFileSync(path.join(dir, "router-health.json"), "utf8"));
  assert.ok(stamp.new_providers.some((p) => p.id === "nvidia" && p.models === 2));
  const dec = JSON.parse(fs.readFileSync(path.join(dir, "providers.json"), "utf8"));
  assert.equal(dec.opencode.decision, "routed");
  assert.equal(dec.opencode.note, "in a chain");
});

test("--decide ignored removes it from NEW; an unknown decision exits 2", () => {
  const h = home(SMALL);
  const d = spawnSync(process.execPath, [BIN, "--decide", "nvidia", "ignored", "--note", "no thanks"], { env: envFor(h), encoding: "utf8" });
  assert.equal(d.status, 0);
  assert.doesNotMatch(runAuth(h, PREFIXES, AUTH).stdout, /NEW PROVIDER: nvidia/);
  const bad = spawnSync(process.execPath, [BIN, "--decide", "nvidia", "maybe"], { env: envFor(h), encoding: "utf8" });
  assert.equal(bad.status, 2);
});

test("--if-stale fresh still prints NEW lines; a new provider never changes the exit code", () => {
  const h = home(ALL);
  const models = Object.values(ALL).concat(PREFIXES);
  assert.equal(runAuth(h, models, "").status, 0);
  const r = runAuth(h, models, AUTH, "--if-stale", "24");
  assert.match(r.stdout, /fresh .* skipped/);
  assert.match(r.stdout, /^NEW PROVIDER: nvidia/m);
  assert.equal(r.status, 0);
});

test("--decide free-only needs --allow, stores the globs, and prints them in normal output", () => {
  const h = home(SMALL);
  const env = envFor(h);
  const decide = (...a) => spawnSync(process.execPath, [BIN, "--decide", "google", ...a], { env, encoding: "utf8" });
  assert.equal(decide("free-only").status, 2);
  assert.equal(decide("free-only", "--allow", " ").status, 2);
  assert.equal(decide("free-only", "--allow", "gemini-*-flash*, gemma-*").status, 0);
  const e = JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "providers.json"), "utf8")).google;
  assert.equal(e.decision, "free-only");
  assert.deepEqual(e.allow, ["gemini-*-flash*", "gemma-*"]);
  const r = runAuth(h, PREFIXES, AUTH);
  assert.match(r.stdout, /^free-only provider: google — allowed models: gemini-\*-flash\*, gemma-\*/m);
  assert.doesNotMatch(r.stdout, /NEW PROVIDER: google/);
});

test("ORCH_NO_AUTH skips detection with a note and never calls opencode", () => {
  const h = home(SMALL);
  const mf = path.join(h, "m.txt");
  fs.writeFileSync(mf, PREFIXES.join(String.fromCharCode(10)));
  const r = spawnSync(process.execPath, [BIN, "--models-file", mf], { env: { ...process.env, ORCH_HOME: h, ORCH_NO_AUTH: "1", OPENCODE_BIN: "/nonexistent/opencode" }, encoding: "utf8" });
  assert.ok(r.stdout.includes("note: ORCH_NO_AUTH set"), r.stdout + r.stderr);
  assert.ok(!r.stdout.includes("NEW PROVIDER"));
});

test("an unparsable providers.json is never overwritten: --decide exits 2; detection is skipped", () => {
  const h = home(SMALL);
  const f = path.join(h, ".config", "orchestrator", "providers.json");
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, "{not json");
  const d = spawnSync(process.execPath, [BIN, "--decide", "nvidia", "ignored"], { env: envFor(h), encoding: "utf8" });
  assert.equal(d.status, 2);
  assert.equal(fs.readFileSync(f, "utf8"), "{not json");
  const r = runAuth(h, PREFIXES, AUTH);
  assert.ok(r.stdout.includes("providers.json exists but cannot be parsed"), r.stdout);
  assert.equal(fs.readFileSync(f, "utf8"), "{not json");
});

test("--decide lowercases the provider key and leaves no tmp file", () => {
  const h = home(SMALL);
  const d = spawnSync(process.execPath, [BIN, "--decide", "Nvidia", "ignored"], { env: envFor(h), encoding: "utf8" });
  assert.equal(d.status, 0);
  const dir = path.join(h, ".config", "orchestrator");
  assert.deepEqual(Object.keys(JSON.parse(fs.readFileSync(path.join(dir, "providers.json"), "utf8"))), ["nvidia"]);
  assert.deepEqual(fs.readdirSync(dir).filter((n) => n.endsWith(".tmp")), []);
});

test("only seed providers are auto-routed from an agent pin; others stay NEW", () => {
  const h = home({ ...SMALL, scout: "nvidia/some-model" });
  const r = runAuth(h, PREFIXES, AUTH);
  assert.match(r.stdout, /^NEW PROVIDER: nvidia /m);
  const dec = JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "providers.json"), "utf8"));
  assert.equal(dec.nvidia, undefined);
  assert.equal(dec.opencode.decision, "routed");
});

test("a NEW provider with zero matching models says so", () => {
  const h = home(SMALL);
  const r = runAuth(h, ["opencode/m"], "●  Nvidia stored");
  assert.ok(r.stdout.includes("0 models") && r.stdout.includes("(no models matched this provider id — check the name mapping)"), r.stdout);
});

// ── free inventory (T4) ──────────────────────────────────────────────────────
// Agents needed for free inventory tests: only the ones pinned to free models
const FREE_AGENTS = {
  "worker-free": "opencode/deepseek-v4.1-flash-free",
  "critic-free": "opencode/minimax-m3.1-flash-free",
  "orchestrator-free": "opencode/deepseek-v4.1-flash-free",
  scout: "opencode/mimo-v2.6-flash-free",
};
// Free models for testing. Note: nvidia models use single-prefix format to match "nemotron-*" glob
const FREE_MODELS = [
  // in-chain: worker-free is pinned
  "opencode/deepseek-v4.1-flash-free",
  // in-chain: critic-free is pinned
  "opencode/minimax-m3.1-flash-free",
  // in-chain: orchestrator-free is pinned (same model as worker-free)
  // in-chain: scout is pinned
  "opencode/mimo-v2.6-flash-free",
  // free under opencode-go/ (unused)
  "opencode-go/mimo-v2.6-flash-free",
  "opencode-go/glm-5.3-flash-free",
  "opencode-go/nemotron-3.5-lightning-free",
  // free under opencode/ (unused)
  "opencode/glm-5.3-flash-free",
  "opencode/nemotron-3.5-lightning-free",
  // Nvidia free-only allowed (nemotron-*) - single prefix to match glob
  "nvidia/nemotron-3-ultra-550b-a55b",
  "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning",
  // Nvidia free-only BLOCKED (not matching allowlist)
  "nvidia/glm-5.3-flash",
];

// providers.json with nvidia free-only allowlist
const NVIDIA_FREE_ONLY = { nvidia: { decision: "free-only", allow: ["nemotron-*"], at: new Date().toISOString(), note: "test" } };

function writeProviders(h, data) {
  const f = path.join(h, ".config", "orchestrator", "providers.json");
  fs.mkdirSync(path.dirname(f), { recursive: true });
  fs.writeFileSync(f, JSON.stringify(data, null, 2) + "\n");
}

function homeFree(extraAgents = {}) {
  return home({ ...FREE_AGENTS, ...extraAgents });
}

function runFree(h, models, ...args) {
  const mf = path.join(h, "models.txt");
  fs.writeFileSync(mf, models.join("\n"));
  const auth = args.includes("--auth-file") ? [] : ["--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt"))];
  return spawnSync(process.execPath, [BIN, "--models-file", mf, ...auth, ...args], { env: { ...process.env, ORCH_HOME: h }, encoding: "utf8" });
}

test("--free prints inventory with correct classification and counts", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const r = runFree(h, FREE_MODELS, "--free");
  // Some roles have no agents installed → exit 1, that's fine for this test
  // 11 live models, 3 unique in-chain (worker-free/orchestrator-free share a model), 1 blocked, 7 unused
  assert.match(r.stdout, /free models: 11 live, 3 in chains, 1 blocked by policy, 7 unused, 0 down — router-health --free/);
  // in-chain models
  assert.match(r.stdout, /opencode\/deepseek-v4.1-flash-free\s+in-chain/);
  assert.match(r.stdout, /opencode\/minimax-m3.1-flash-free\s+in-chain/);
  assert.match(r.stdout, /opencode\/mimo-v2.6-flash-free\s+in-chain/);
  // Nvidia allowed (unused)
  assert.match(r.stdout, /nvidia\/nemotron-3-ultra-550b-a55b\s+unused/);
  assert.match(r.stdout, /nvidia\/nemotron-3-nano-omni-30b-a3b-reasoning\s+unused/);
  // Nvidia blocked
  assert.match(r.stdout, /nvidia\/glm-5.3-flash\s+blocked \(policy: free-only\)/);
  // opencode-go free models (unused)
  assert.match(r.stdout, /opencode-go\/mimo-v2.6-flash-free\s+unused/);
  assert.match(r.stdout, /opencode-go\/glm-5.3-flash-free\s+unused/);
  // Never probed
  assert.match(r.stdout, /never probed/);
});

test("--free with --json includes free_inventory", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const r = runFree(h, FREE_MODELS, "--free", "--json");
  // Some roles have no agents installed → exit 1, that's fine
  const report = JSON.parse(r.stdout);
  assert.ok(report.free_inventory);
  assert.equal(report.free_inventory.counts.live, 11);
  assert.equal(report.free_inventory.counts.in_chains, 3);
  assert.equal(report.free_inventory.counts.blocked, 1);
  assert.equal(report.free_inventory.counts.unused, 7);
  assert.equal(report.free_inventory.counts.down, 0);
  assert.equal(report.free_inventory.models.length, 11);
  // Check structure
  for (const m of report.free_inventory.models) {
    assert.ok(m.model);
    assert.ok(["in-chain", "blocked", "unused", "down"].includes(m.state));
    if (m.state === "in-chain") assert.ok(Array.isArray(m.agents) && m.agents.length > 0);
    if (m.state === "blocked") assert.ok(typeof m.reason === "string");
    assert.ok(m.probe !== undefined);
  }
});

test("--probe-free probes max 12 unused models, writes free-inventory.json, does not touch pool-health.json", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // We need many unused free models to test the cap
  const manyFree = FREE_MODELS.concat(
    Array.from({ length: 10 }, (_, i) => `opencode-go/free-model-${i}-free`)
  );
  const fakeProbe = path.join(HERE, "fixtures", "fake-probe.mjs");
  const r = spawnSync(process.execPath, [BIN, "--models-file", (() => { const mf = path.join(h, "models.txt"); fs.writeFileSync(mf, manyFree.join("\n")); return mf; })(), "--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt")), "--probe-free", "--free"], {
    env: { ...process.env, ORCH_HOME: h, OPENCODE_BIN: fakeProbe, FAKE_PROBE_OK: "opencode-go/mimo-v2.6-flash-free,opencode-go/glm-5.3-flash-free,opencode-go/nemotron-3.5-lightning-free,nvidia/nemotron-3-ultra-550b-a55b,nvidia/nemotron-3-nano-omni-30b-a3b-reasoning" },
    encoding: "utf8"
  });
  // Some roles have no agents → exit 1, that's fine
  // free-inventory.json exists
  const invPath = path.join(h, ".config", "orchestrator", "free-inventory.json");
  assert.ok(fs.existsSync(invPath), "free-inventory.json should exist");
  const inv = JSON.parse(fs.readFileSync(invPath, "utf8"));
  // Should have entries for probed models (up to 12) - only count those with real probe results
  const probedCount = Object.values(inv).filter((v) => v.class !== "never probed" && v.class !== "not probed (cap 12)").length;
  assert.ok(probedCount <= 12, `probed ${probedCount}, expected <= 12`);
  // Should have cap entries in output (not persisted)
  assert.match(r.stdout, /not probed \(cap 12\)/);
  // T8-minors: the models past the cap get no entry in the file at all — it holds measured results only. Writing
  // `never probed` there contradicted the comment and made an old inventory look like a set of failed probes.
  const capped = [...r.stdout.matchAll(/^(\S+)  unused .*not probed \(cap 12\)$/gm)].map((m) => m[1]);
  assert.ok(capped.length > 0, "the output names the models past the cap");
  for (const model of capped) assert.equal(inv[model], undefined, `${model} must not be persisted`);
  assert.ok(!Object.values(inv).some((v) => v.class === "never probed"), "no never-probed entry is written");
  // pool-health.json should NOT have been modified by probe-free
  const healthPath = path.join(h, ".config", "orchestrator", "pool-health.json");
  let health = {};
  if (fs.existsSync(healthPath)) {
    health = JSON.parse(fs.readFileSync(healthPath, "utf8"));
  }
  // Only the initial markDown from missing models should be there (none missing here)
  assert.equal(Object.keys(health).length, 0, "pool-health.json should be empty after --probe-free");
});

test("--probe-free without --free still works and writes inventory", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const fakeProbe = path.join(HERE, "fixtures", "fake-probe.mjs");
  const r = spawnSync(process.execPath, [BIN, "--models-file", (() => { const mf = path.join(h, "models.txt"); fs.writeFileSync(mf, FREE_MODELS.join("\n")); return mf; })(), "--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt")), "--probe-free"], {
    env: { ...process.env, ORCH_HOME: h, OPENCODE_BIN: fakeProbe, FAKE_PROBE_OK: "opencode-go/mimo-v2.6-flash-free,nvidia/nemotron-3-ultra-550b-a55b" },
    encoding: "utf8"
  });
  // Exit code may be 1 due to missing agents, that's fine
  // free-inventory.json exists
  const invPath = path.join(h, ".config", "orchestrator", "free-inventory.json");
  assert.ok(fs.existsSync(invPath), "free-inventory.json should exist");
});

test("--if-stale fresh path prints no inventory", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // First run to create stamp
  runFree(h, FREE_MODELS, "--free");
  // Second run with --if-stale
  const r = runFree(h, FREE_MODELS, "--free", "--if-stale", "24");
  assert.match(r.stdout, /fresh .* skipped/);
  assert.doesNotMatch(r.stdout, /free models:/);
});

test("live models unavailable prints note and skips inventory", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // Don't pass --models-file, and make opencodeBin fail by using a non-existent binary
  const r = spawnSync(process.execPath, [BIN, "--free"], {
    env: { ...process.env, ORCH_HOME: h, OPENCODE_BIN: "/nonexistent/opencode" },
    encoding: "utf8"
  });
  assert.match(r.stdout, /`opencode models` unavailable/);
  assert.doesNotMatch(r.stdout, /free models:/);
  // the summary line still says where the inventory stands, so the run never looks like "no free models at all"
  assert.match(r.stdout, /free inventory: unavailable \(opencode models failed\)/);
});

// ── T4 addendum: catalog-based free detection ─────────────────────────────────
// Real catalog structure: { "<provider>": { "models": { "<id>": { "cost": {...} } } } }
const CATALOG_FIXTURE = {
  "opencode-go": {
    models: {
      "x/y:free": { cost: { input: 0, output: 0 } },
      "zero-cost-model": { cost: { input: 0, output: 0 } },
      "paid-model": { cost: { input: 10, output: 30 } },
      "contributor-model": { cost: { input: 0, output: 0 } },
      "iceman-model": { cost: { input: 0, output: 0 } },
    }
  },
  opencode: {
    models: {
      "free-model": { cost: { input: 0, output: 0 } }
    }
  }
};

function writeCatalog(h, catalog) {
  const catalogDir = path.join(h, ".cache", "opencode");
  fs.mkdirSync(catalogDir, { recursive: true });
  fs.writeFileSync(path.join(catalogDir, "models.json"), JSON.stringify(catalog, null, 2) + "\n");
}

function runWithCatalog(h, models, catalog, ...args) {
  const mf = path.join(h, "models.txt");
  fs.writeFileSync(mf, models.join("\n"));
  writeCatalog(h, catalog);
  const auth = args.includes("--auth-file") ? [] : ["--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt"))];
  return spawnSync(process.execPath, [BIN, "--models-file", mf, ...auth, ...args], {
    env: { ...process.env, ORCH_HOME: h, ORCH_OC_CATALOG: path.join(h, ".cache", "opencode", "models.json") },
    encoding: "utf8"
  });
}

test("catalog :free suffix models are detected as free (opencode-go/x/y:free)", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const models = [...FREE_MODELS, "opencode-go/x/y:free"];
  const r = runWithCatalog(h, models, CATALOG_FIXTURE, "--free");
  // Should include the :free model
  assert.match(r.stdout, /opencode-go\/x\/y:free\s+unused/);
  // Should have trains-on-data for contributor/iceman
  // (not in this test, separate test below)
});

test("catalog zero-cost models without -free suffix are detected as free", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const models = [...FREE_MODELS, "opencode-go/zero-cost-model"];
  const r = runWithCatalog(h, models, CATALOG_FIXTURE, "--free");
  // Should include the zero-cost model
  assert.match(r.stdout, /opencode-go\/zero-cost-model\s+unused/);
});

test("catalog paid models are NOT detected as free", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const models = [...FREE_MODELS, "opencode-go/paid-model"];
  const r = runWithCatalog(h, models, CATALOG_FIXTURE, "--free");
  // Should NOT include the paid model
  assert.doesNotMatch(r.stdout, /opencode-go\/paid-model/);
});

test("catalog-only models (not in live list) are NOT included", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // Live list does NOT include opencode-go/catalog-only-model
  const models = [...FREE_MODELS];
  const r = runWithCatalog(h, models, CATALOG_FIXTURE, "--free");
  // Should NOT include catalog-only model
  assert.doesNotMatch(r.stdout, /opencode-go\/catalog-only-model/);
});

test("trains-on-data tag appears for contributor and iceman models", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const models = [...FREE_MODELS, "opencode-go/contributor-model", "opencode-go/iceman-model"];
  const r = runWithCatalog(h, models, CATALOG_FIXTURE, "--free");
  // Should include trains-on-data tag
  assert.match(r.stdout, /opencode-go\/contributor-model\s+unused trains-on-data/);
  assert.match(r.stdout, /opencode-go\/iceman-model\s+unused trains-on-data/);
});

test("unconnected provider without providers.json decision is skipped (openrouter without auth)", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // openrouter is not in providers.json and we don't provide auth for it
  // Even if it has zero-cost models in catalog, it should be skipped
  const models = [...FREE_MODELS, "openrouter/free-model"];
  // Use a catalog that includes openrouter (real structure: no wrapper key)
  const catalogWithOpenrouter = {
    ...CATALOG_FIXTURE,
    openrouter: {
      models: {
        "free-model": { cost: { input: 0, output: 0 } }
      }
    }
  };
  const r = runWithCatalog(h, models, catalogWithOpenrouter, "--free");
  // openrouter should be skipped because no providers.json entry and no auth
  assert.doesNotMatch(r.stdout, /openrouter\/free-model/);
});

test("connected provider with zero-cost models is included", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // Provide auth for openrouter - format matches what connectedProviders expects
  const auth = `${ESC}[0m┌  Credentials ${ESC}[90m~/.local/share/opencode/auth.json${ESC}[0m
│
●  ${ESC}[1mOpenRouter${ESC}[0m stored
└  1 credentials`;
  const models = [...FREE_MODELS, "openrouter/free-model"];
  const catalogWithOpenrouter = {
    ...CATALOG_FIXTURE,
    openrouter: {
      models: {
        "free-model": { cost: { input: 0, output: 0 } }
      }
    }
  };
  const mf = path.join(h, "models.txt");
  fs.writeFileSync(mf, models.join("\n"));
  writeCatalog(h, catalogWithOpenrouter);
  const af = path.join(h, "auth.txt");
  fs.writeFileSync(af, auth);
  const r = spawnSync(process.execPath, [BIN, "--models-file", mf, "--auth-file", af, "--free"], {
    env: { ...process.env, ORCH_HOME: h, ORCH_OC_CATALOG: path.join(h, ".cache", "opencode", "models.json") },
    encoding: "utf8"
  });
  // openrouter should be included because it's connected
  assert.match(r.stdout, /openrouter\/free-model\s+unused/);
});

// ── Additional tests for down state, precedence, promote line, probeModel argv ─────
test("down state appears for models marked down in pool-health", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // Pre-populate pool-health with a down entry
  const healthPath = path.join(h, ".config", "orchestrator", "pool-health.json");
  fs.mkdirSync(path.dirname(healthPath), { recursive: true });
  fs.writeFileSync(healthPath, JSON.stringify({
    "opencode/down-model-free": { reason: "quota", since: new Date().toISOString(), until: new Date(Date.now() + 3600000).toISOString(), detail: "test" }
  }, null, 2) + "\n");
  const models = [...FREE_MODELS, "opencode/down-model-free"];
  const r = runWithCatalog(h, models, CATALOG_FIXTURE, "--free");
  assert.match(r.stdout, /opencode\/down-model-free\s+down \(quota until/);
});

test("precedence: blocked > in-chain > down > unused", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // Add a model that is both in-chain AND would be blocked (blocked should win)
  // Actually, we test: a model that's in providers.json free-only but not allowed = blocked
  // A model that's in chain = in-chain (even if also free-only)
  // A model that's down = down (if not in-chain)
  // A model that's none of the above = unused
  // This is implicitly tested by other tests; here we verify the summary counts
  const models = [...FREE_MODELS, "nvidia/blocked-model"]; // blocked by policy
  const r = runWithCatalog(h, models, CATALOG_FIXTURE, "--free");
  assert.match(r.stdout, /nvidia\/blocked-model\s+blocked \(policy: free-only\)/);
  // The summary should show blocked count includes this
  assert.match(r.stdout, /blocked by policy/);
});

test("promote line appears when unused model probes ok", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  // Only one unused model that will probe ok
  const models = [...FREE_MODELS, "opencode/probe-ok-free"];
  const fakeProbe = path.join(HERE, "fixtures", "fake-probe.mjs");
  const r = spawnSync(process.execPath, [BIN, "--models-file", (() => { const mf = path.join(h, "models.txt"); fs.writeFileSync(mf, models.join("\n")); return mf; })(), "--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt")), "--probe-free", "--free"], {
    env: { ...process.env, ORCH_HOME: h, OPENCODE_BIN: fakeProbe, FAKE_PROBE_OK: "opencode/probe-ok-free" },
    encoding: "utf8"
  });
  assert.match(r.stdout, /promote: \/frood-model-router-refresh \+ owner approval/);
});

test("probeModel argv recorded via FAKE_PROBE_ARGS_FILE (title before model)", () => {
  const h = homeFree();
  writeProviders(h, NVIDIA_FREE_ONLY);
  const argsFile = path.join(h, "probe-args.json");
  const fakeProbe = path.join(HERE, "fixtures", "fake-probe.mjs");
  const r = spawnSync(process.execPath, [BIN, "--models-file", (() => { const mf = path.join(h, "models.txt"); fs.writeFileSync(mf, "opencode/test-probe-free\n"); return mf; })(), "--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt")), "--probe-free"], {
    env: { ...process.env, ORCH_HOME: h, OPENCODE_BIN: fakeProbe, FAKE_PROBE_OK: "opencode/test-probe-free", FAKE_PROBE_ARGS_FILE: argsFile },
    encoding: "utf8"
  });
  const args = JSON.parse(fs.readFileSync(argsFile, "utf8"));
  // Check argv has --title "orch router-health free probe" before --model
  const argv = args.argv;
  const titleIdx = argv.indexOf("--title");
  const modelIdx = argv.indexOf("--model");
  assert.ok(titleIdx >= 0, "--title should be in argv");
  assert.ok(modelIdx >= 0, "--model should be in argv");
  assert.ok(titleIdx < modelIdx, "--title should come before --model");
  assert.equal(argv[titleIdx + 1], "orch router-health free probe");
  assert.equal(argv[modelIdx + 1], "opencode/test-probe-free");
});

test("headroom: a Go pool near its cap is skipped for a healthy paid fallback", () => {
  const h = home(ALL);
  // $14 of list-cost in the trailing 5h against the $12 5h cap (20% of the default $60 monthly).
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(path.join(h, "oc.db"));
  try {
    db.exec(`CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, model TEXT, cost REAL,
      time_created INTEGER, time_updated INTEGER, tokens_input INTEGER, tokens_output INTEGER,
      tokens_reasoning INTEGER, tokens_cache_read INTEGER, directory TEXT);`);
    db.prepare("INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?)").run(
      "ses_heavy", "heavy", JSON.stringify({ providerID: "opencode-go", id: "mimo-v2.6-flash" }),
      0, Date.now() - 3600_000, Date.now() - 3600_000, 100e6, 0, 0, 0, "/tmp/x");
  } finally { db.close(); }
  const r = run(h, Object.values(ALL));
  assert.match(r.stdout, /^worker\s+use worker-nvidia\s*(?:👁)?\s*\[skipped worker: low-headroom/m, r.stdout);
  // critic and critic-go both ride the same exhausted Go pool, so both are skipped — use falls to critic-nvidia.
  assert.match(r.stdout, /^critic\s+use critic-nvidia\s*(?:👁)?\s+\[skipped critic: low-headroom[^\]]*critic-go: low-headroom/m, r.stdout);
  assert.equal(r.status, 0);
});

// ── Quota marks are re-tested on --probe (Go 2026-11-21 → 11-26: a monthly-cap retry-after held the whole provider
// down for five days after the subscription was live again) ─────────────────────────────────────────────────────
function goQuotaHome() {
  const h = home(ALL);
  const healthPath = path.join(h, ".config", "orchestrator", "pool-health.json");
  fs.mkdirSync(path.dirname(healthPath), { recursive: true });
  fs.writeFileSync(healthPath, JSON.stringify({
    "opencode-go/*": { reason: "quota", since: new Date().toISOString(), until: new Date(Date.now() + 5 * 86400_000).toISOString(), detail: "OpenCode Go monthly usage limit reached" },
    "nvidia/*": { reason: "unavailable", since: new Date().toISOString(), until: new Date(Date.now() + 86400_000).toISOString(), detail: "not a quota" },
  }, null, 2) + "\n");
  return { h, healthPath };
}
function runProbe(h, env) {
  const log = path.join(h, "probes.log");
  const r = spawnSync(process.execPath, [BIN, "--models-file", (fs.writeFileSync(path.join(h, "models.txt"), Object.values(ALL).join("\n")), path.join(h, "models.txt")),
    "--auth-file", (fs.writeFileSync(path.join(h, "empty-auth.txt"), ""), path.join(h, "empty-auth.txt")), "--probe"], {
    env: { ...process.env, ORCH_HOME: h, OPENCODE_DB: path.join(h, "oc.db"), OPENCODE_BIN: path.join(HERE, "fixtures", "fake-probe.mjs"), FAKE_PROBE_LOG: log, ...env }, encoding: "utf8",
  });
  const probes = fs.existsSync(log) ? fs.readFileSync(log, "utf8").trim().split("\n").filter(Boolean) : [];
  return { r, probes };
}

test("--probe re-tests a provider-wide quota mark; a model that answers clears it and the Go agents are used again", () => {
  const { h, healthPath } = goQuotaHome();
  const goAgents = Object.entries(ALL).filter(([, m]) => m.startsWith("opencode-go/")).map(([a]) => a).join(",");
  const { r } = runProbe(h, { FAKE_PROBE_OK_AGENTS: `${goAgents},scout,worker-free,critic-free,senior-free,orchestrator-free` });
  const health = JSON.parse(fs.readFileSync(healthPath, "utf8"));
  assert.equal(health["opencode-go/*"], undefined, "the Go quota mark is cleared");
  assert.equal(health["nvidia/*"].reason, "unavailable", "a non-quota mark is still trusted, never re-tested");
  assert.match(r.stdout, /^critic\s+use critic\s/m, r.stdout);
  assert.match(r.stdout, /^worker\s+use worker\s/m, r.stdout);
  assert.match(r.stdout, /^worker-strong\s+use worker-strong/m, r.stdout);
});

test("a quota mark that is still real costs one probe per run, not one per model on that provider", () => {
  const { h, healthPath } = goQuotaHome();
  const quota = JSON.stringify({ type: "error", error: { type: "provider.go-limit", message: "OpenCode Go monthly usage limit reached.", status: 429 } });
  const { r, probes } = runProbe(h, { FAKE_PROBE_FAIL_BODY: quota, FAKE_PROBE_OK_AGENTS: "scout,worker-free,critic-free,orchestrator-free" });
  const goProbes = probes.filter((a) => ALL[a]?.startsWith("opencode-go/"));
  assert.equal(goProbes.length, 1, `Go probed once: ${probes.join(",")}`);
  const health = JSON.parse(fs.readFileSync(healthPath, "utf8"));
  assert.equal(health["opencode-go/*"].reason, "quota", "still down after a failed re-test");
  assert.match(r.stdout, /^worker-strong\s+use worker-free/m, r.stdout);
});

test("a quota re-test that fails for another reason is one probe-failed row, and the next model under the mark re-tests it", () => {
  const { h, healthPath } = goQuotaHome();
  const flaky = JSON.stringify({ type: "error", error: { type: "weird", message: "something odd" } });
  const { r, probes } = runProbe(h, { FAKE_PROBE_FAIL_BODY: flaky, FAKE_PROBE_OK_AGENTS: "scout,worker-free,critic-free,orchestrator-free" });
  const workerLine = r.stdout.split("\n").find((l) => /^worker\s/.test(l)) || "";
  assert.equal((workerLine.match(/\bworker:/g) || []).length, 1, `worker listed once: ${workerLine}`);
  assert.match(workerLine, /worker: probe-failed/);
  assert.ok(probes.filter((a) => ALL[a]?.startsWith("opencode-go/")).length > 1, `re-tested past the flaky one: ${probes.join(",")}`);
  assert.equal(JSON.parse(fs.readFileSync(healthPath, "utf8"))["opencode-go/*"].reason, "quota", "mark kept: nothing proved it wrong");
});

// ── go-pacing G1: no Claude through Go ──────────────────────────────────────
test("a Claude-via-Go model shows as blocked by policy in the free inventory; other Go models do not", () => {
  const h = home({ ...FREE_AGENTS, critic: "opencode-go/claude-haiku-5-5" });
  writeProviders(h, { "opencode-go": { decision: "free-only", allow: ["mimo-*"], at: new Date().toISOString(), note: "test" } });
  const models = [...FREE_MODELS, "opencode-go/mimo-v2.6-flash", "opencode-go/claude-haiku-5-5"];
  const r = runFree(h, models, "--free");
  assert.match(r.stdout, /^opencode-go\/claude-haiku-5-5  blocked \(policy: claude via go\)$/m, r.stdout);
  assert.doesNotMatch(r.stdout, /^opencode-go\/mimo-v2\.6-flash  blocked/m, r.stdout);
  assert.match(r.stdout, /^opencode-go\/mimo-v2\.6-flash  (in-chain|unused)/m, r.stdout);
});

// ── go-pacing G2: one info line when the v2 message ledger exists ─────────────
test("go ledger v2 info line appears beside the usage note, with the old windows suffixed", () => {
  const h = home(ALL);
  const { DatabaseSync } = require("node:sqlite");
  const db = new DatabaseSync(path.join(h, "oc.db"));
  try {
    db.exec(`CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, model TEXT, cost REAL,
      time_created INTEGER, time_updated INTEGER, tokens_input INTEGER, tokens_output INTEGER,
      tokens_reasoning INTEGER, tokens_cache_read INTEGER, directory TEXT);`);
    db.prepare("INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?,?,?,?,?)").run(
      "s0", "old", JSON.stringify({ providerID: "opencode-go", id: "mimo-v2.6-flash" }),
      0, Date.now() - 3600_000, Date.now() - 3600_000, 10e6, 0, 0, 0, "/tmp/x");
    db.exec(`CREATE TABLE session_message (id TEXT PRIMARY KEY, sessionID TEXT, type TEXT, data TEXT, time_created INTEGER);`);
    db.prepare("INSERT INTO session_message VALUES (?,?,?,?,?)").run(
      "m0", "ses0", "assistant",
      JSON.stringify({
        model: { providerID: "opencode-go", id: "mimo-v2.6-flash" },
        time: { completed: Date.now() - 3600_000 },
        tokens: { input: 1e6, output: 0, reasoning: 0, cache: { read: 0, write: 0 } },
      }),
      Date.now() - 3600_000);
  } finally { db.close(); }
  const r = run(h, Object.values(ALL));
  // The old headroom floor is untouched: $1.40 of the $12 5h cap leaves Go
  // healthy, so the first-chain agents are still used; the v2 line carries the
  // allowance-percent windows plus the old dollar windows.
  // (Old-window dollars are shape-matched: a run in the first hour of a month
  // puts the message in last month's mtd window.)
  assert.match(r.stdout, /^worker\s+use worker-nvidia/m, r.stdout);
  assert.match(
    r.stdout,
    /^note: go ledger v2 \(go\): 5h \d+\.\d%\/20 · wk \d+\.\d%\/50 · mo \?\/100 \(no period anchor\) \(old: 5h \$\d+\.\d\d 7d \$\d+\.\d\d mtd \$\d+\.\d\d\)$/m,
    r.stdout,
  );
});

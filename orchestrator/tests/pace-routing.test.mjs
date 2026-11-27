// cc-pacing M4: pace-aware routing. router-health's pace line against the goldens captured before the change,
// oc-worker's --role worker chain per pace state, the cc_pace receipt field, and check-routing knowing cc-worker.
// Hermetic: every child runs with ORCH_HOME in a temp dir and a timeout; fake claude/opencode only, no paid run.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { args, paceDecision } from "../bin/oc-worker.mjs";
import { readPace, paceChain, ccPaceRecord } from "../bin/pace-read.mjs";
import { checkRouting } from "../bin/check-routing.mjs";
import { installFixtureGuard } from "./fixtures/fixture-guard.mjs";

installFixtureGuard();

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin");
const RH = path.join(BIN, "router-health.mjs");
const OCW = path.join(BIN, "oc-worker.mjs");
const CC_PACE = path.join(BIN, "cc-pace.mjs");
const FAKE_CC = path.join(HERE, "fixtures", "fake-claude.mjs");
const FAKE_OC = path.join(HERE, "fixtures", "fake-opencode.mjs");
const GOLD = path.join(HERE, "fixtures", "router-health-golden");
const FULL = fs.readFileSync(path.join(GOLD, "full.txt"), "utf8");
const FRESH = fs.readFileSync(path.join(GOLD, "if-stale-fresh.txt"), "utf8");
const OVER_ADVICE = "pace: OVER — conserve: no Fable senior unless guarded; scouts haiku";
const TODAY = ["worker-nvidia", "worker", "worker-free"];

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});
const tmp = (p = "orch-pace-") => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), p));
  CLEAN.push(d);
  return d;
};

// ---- pace fixtures: M1 snapshots in <ORCH_HOME>/.config/orchestrator/cc-usage.json, `at` relative to now ----
const H = 3600 * 1000;
const iso = (ms) => new Date(ms).toISOString();
function snapshot(state) {
  const now = Date.now();
  const at = iso(now - 10 * 60 * 1000);
  if (state === "under") return { at, source: "app", five_hour: { pct: 0, resets_at: iso(now + 3 * H) }, weekly: { pct: 10, resets_at: iso(now + 100 * H) }, fable: null };
  // early week (E < 12 h) reads `on` whatever the projection
  if (state === "on") return { at, source: "app", five_hour: { pct: 0, resets_at: iso(now + 3 * H) }, weekly: { pct: 1, resets_at: iso(now + 160 * H) }, fable: null };
  if (state === "over") return { at, source: "app", five_hour: { pct: 90, resets_at: iso(now + 3 * H) }, weekly: { pct: 10, resets_at: iso(now + 100 * H) }, fable: null };
  return null; // unknown: no snapshot; off: ORCH_NO_PACE=1
}
function paceHome(state, h = tmp()) {
  const snap = snapshot(state);
  if (snap) {
    const d = path.join(h, ".config", "orchestrator");
    fs.mkdirSync(d, { recursive: true });
    fs.writeFileSync(path.join(d, "cc-usage.json"), JSON.stringify(snap) + "\n");
    fs.writeFileSync(path.join(d, "cc-usage.jsonl"), JSON.stringify(snap) + "\n");
  }
  return h;
}
const paceEnv = (state) => (state === "off" ? { ORCH_NO_PACE: "1" } : {});
function baseEnv(h, extra = {}) {
  const e = { ...process.env, ORCH_HOME: h, ...extra };
  if (!("ORCH_NO_PACE" in extra)) delete e.ORCH_NO_PACE;
  if (!("ORCH_PACE_BIN" in extra)) delete e.ORCH_PACE_BIN;
  if (!("ORCH_PACE_DECISION" in extra)) delete e.ORCH_PACE_DECISION;
  if (!("ORCH_DETACHED_CHILD" in extra)) delete e.ORCH_DETACHED_CHILD;
  return e;
}
/** What cc-pace prints for this home right now (the router-health line must be exactly this). */
function expectedLine(h, extra) {
  const r = spawnSync(process.execPath, [CC_PACE, "status"], { env: baseEnv(h, extra), encoding: "utf8", timeout: 15000 });
  assert.equal(r.status, 0, r.stderr);
  return r.stdout.trim();
}

// ---- router-health: the same hermetic home as router-health.test.mjs ALL (all models live, empty auth) ----
const ALL = {
  worker: "opencode-go/mimo-v2.6-flash", "worker-free": "opencode/deepseek-v4.1-flash-free", "worker-strong": "opencode-go/muse-spark-1.3-contributor",
  "worker-nvidia": "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b",
  "senior-nvidia": "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b", "senior-free": "opencode/deepseek-v4.1-flash-free",
  "orchestrator-nvidia": "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b", "orchestrator-free": "opencode/deepseek-v4.1-flash-free",
  critic: "opencode-go/claude-haiku-5-5", "critic-go": "opencode-go/deepseek-v4.1-flash", "critic-nvidia": "nvidia/minimaxai/minimax-m3.1-flash", "critic-free": "opencode/minimax-m3.1-flash-free",
  scout: "opencode/mimo-v2.6-flash-free", senior: "opencode-go/deepseek-v4-pro", orchestrator: "opencode-go/muse-spark-1.3-contributor",
};
function rhHome(state) {
  const h = paceHome(state);
  const d = path.join(h, ".config", "opencode", "agents");
  fs.mkdirSync(d, { recursive: true });
  for (const [n, m] of Object.entries(ALL)) fs.writeFileSync(path.join(d, `${n}.md`), `---\nmode: subagent\nmodel: ${m}\n---\nx\n`);
  return h;
}
function rh(h, extraEnv, ...argv) {
  const mf = path.join(h, "models.txt");
  fs.writeFileSync(mf, Object.values(ALL).join("\n"));
  const auth = path.join(h, "empty-auth.txt");
  fs.writeFileSync(auth, "");
  return spawnSync(process.execPath, [RH, "--models-file", mf, "--auth-file", auth, ...argv], { env: baseEnv(h, { OPENCODE_DB: path.join(h, "oc.db"), ...extraEnv }), encoding: "utf8", timeout: 60000 });
}

test("goldens are the captured files, unchanged", async () => {
  const { createHash } = await import("node:crypto");
  const sha = (s) => createHash("sha256").update(s).digest("hex");
  assert.equal(sha(FULL), "76f0f5a7f164bc438fffe8915f80e0a276526a24b89f450b07e0fd2adef0bc52");
  assert.equal(sha(FRESH), "af42001b68be4886ea9fc8f9978b55ae207b69c3388718652028e7a4c2d7af47");
});

for (const state of ["off", "unknown", "on", "over", "under"]) {
  test(`router-health ${state}: pace line first, then the golden output (full and --if-stale fresh)`, () => {
    const h = rhHome(state);
    const env = paceEnv(state);
    const full = rh(h, env);
    assert.equal(full.status, 0, full.stderr);
    const line = expectedLine(h, env);
    if (state === "off") assert.equal(line, "OFF");
    if (state === "unknown") assert.equal(line, "UNKNOWN (no snapshot)");
    assert.match(line, new RegExp(`^${state.toUpperCase()}\\b`));
    const head = `pace: ${line}\n${state === "over" ? OVER_ADVICE + "\n" : ""}`;
    const body = state === "under"
      ? FULL.replace(/^worker {9}use /m, "worker         use cc-worker (pace UNDER), fallback ")
      : FULL;
    if (state === "under") {
      assert.notEqual(body, FULL);
      assert.match(body, /^worker {9}use cc-worker \(pace UNDER\), fallback worker-nvidia 👁$/m);
    }
    assert.equal(full.stdout, head + body);
    // only the worker line may differ from the golden: critic, senior, scout, orchestrator, worker-strong as captured
    const gold = FULL.split("\n");
    const got = full.stdout.split("\n").slice(state === "over" ? 2 : 1);
    for (const role of ["worker-strong", "critic", "scout", "senior", "orchestrator"]) {
      const re = new RegExp(`^${role} `);
      assert.equal(got.find((l) => re.test(l)), gold.find((l) => re.test(l)), role);
    }
    const fresh = rh(h, env, "--if-stale", "24");
    assert.equal(fresh.status, 0, fresh.stderr);
    assert.equal(fresh.stdout, head + FRESH);
  });
}

test("router-health: a failed pace read prints `pace: UNKNOWN (<reason>)` and the rest unchanged", () => {
  const h = rhHome("under");
  const r = rh(h, { ORCH_PACE_BIN: path.join(h, "missing", "cc-pace.mjs") });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stdout, "pace: UNKNOWN (pace read failed: missing cc-pace.mjs)\n" + FULL);
});

test("router-health --json: top-level pace key; the router-health.json stamp never holds it; --decide output unchanged", () => {
  const h = rhHome("under");
  const r = rh(h, {}, "--json");
  assert.equal(r.status, 0, r.stderr);
  const j = JSON.parse(r.stdout);
  assert.equal(j.pace.state, "under");
  assert.equal(j.pace.weekly, 10);
  assert.ok(j.roles.worker, "the report is still there");
  const stamp = JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "router-health.json"), "utf8"));
  assert.equal("pace" in stamp, false);
  const d = rh(h, {}, "--decide", "someprov", "ignored");
  assert.equal(d.status, 0, d.stderr);
  assert.equal(d.stdout, "someprov: ignored\n");
});

// ---- pace-read ----
function withEnv(vars, fn) {
  const saved = {};
  for (const k of Object.keys(vars)) saved[k] = process.env[k];
  try {
    for (const [k, v] of Object.entries(vars)) v === undefined ? delete process.env[k] : (process.env[k] = v);
    return fn();
  } finally {
    for (const [k, v] of Object.entries(saved)) v === undefined ? delete process.env[k] : (process.env[k] = v);
  }
}

test("readPace: parses cc-pace JSON; ORCH_NO_PACE=1 → off; every failure → unknown, never throws", () => {
  const h = paceHome("under");
  assert.equal(withEnv({ ORCH_HOME: h, ORCH_NO_PACE: undefined, ORCH_PACE_BIN: undefined }, () => readPace()).state, "under");
  assert.equal(withEnv({ ORCH_HOME: h, ORCH_NO_PACE: "1", ORCH_PACE_BIN: undefined }, () => readPace()).state, "off");
  const missing = withEnv({ ORCH_HOME: h, ORCH_PACE_BIN: path.join(h, "nope.mjs") }, () => readPace());
  assert.deepEqual(missing, { state: "unknown", reason: "pace read failed: missing nope.mjs" });
  const bad = path.join(h, "bad.mjs");
  fs.writeFileSync(bad, "console.log('not json')\n");
  assert.deepEqual(withEnv({ ORCH_HOME: h, ORCH_PACE_BIN: bad }, () => readPace()), { state: "unknown", reason: "pace read failed: unparsable output" });
  const fail = path.join(h, "fail.mjs");
  fs.writeFileSync(fail, "process.exit(3)\n");
  assert.deepEqual(withEnv({ ORCH_HOME: h, ORCH_PACE_BIN: fail }, () => readPace()), { state: "unknown", reason: "pace read failed: exit 3" });
  const slow = path.join(h, "slow.mjs");
  fs.writeFileSync(slow, "setTimeout(() => {}, 20000)\n");
  assert.deepEqual(withEnv({ ORCH_HOME: h, ORCH_PACE_BIN: slow }, () => readPace({ timeoutMs: 300 })), { state: "unknown", reason: "pace read failed: timeout" });
});

test("paceChain: cc-worker first only for role worker on under; same contents otherwise", () => {
  assert.deepEqual(paceChain("worker", TODAY, { state: "under" }), ["cc-worker", ...TODAY]);
  for (const s of ["off", "unknown", "on", "over"]) assert.deepEqual(paceChain("worker", TODAY, { state: s }), TODAY);
  assert.deepEqual(paceChain("worker-strong", ["worker-strong", "worker-nvidia", "worker-free"], { state: "under" }), ["worker-strong", "worker-nvidia", "worker-free"]);
  assert.deepEqual(paceChain("critic", ["critic"], { state: "under" }), ["critic"]);
  assert.deepEqual(paceChain("worker", TODAY, null), TODAY);
  assert.deepEqual(ccPaceRecord({ state: "under", weekly: 10, projected: 29.7, at: "x", reason: "r" }, true), { state: "under", weekly: 10, projected: 29.7, at: "x", prepended: true, shadow: null });
  assert.deepEqual(ccPaceRecord(null), { state: "unknown", weekly: null, projected: null, at: null, prepended: false, shadow: null });
});

// ---- oc-worker --role expansion (dry: args() with the pace injected) ----
function dryRun(argvExtra, pace, { drops = 0 } = {}) {
  const h = tmp();
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "Do it.");
  const runDir = path.join(h, "run");
  fs.mkdirSync(runDir);
  for (let i = 0; i < drops; i++) fs.writeFileSync(path.join(runDir, `worker-r${i + 1}.md.receipt.json`), JSON.stringify({ agent: "worker-nvidia", exit: "stalled" }));
  let reads = 0;
  const a = args(["--dir", h, "--prompt", prompt, "--out", path.join(runDir, "worker-r9.md"), ...argvExtra], { pace: () => (reads++, pace) });
  return { chain: [a.agent, ...(a.fallback || [])], prepended: a.pacePrepended === true, reads };
}

test("oc-worker --role worker: under → cc-worker first; off/unknown/on/over → today's chain", () => {
  const u = dryRun(["--role", "worker"], { state: "under" });
  assert.deepEqual(u.chain, ["cc-worker", "worker-nvidia", "worker", "worker-free"]);
  assert.equal(u.prepended, true);
  assert.equal(u.reads, 1);
  for (const s of ["off", "unknown", "on", "over"]) {
    const r = dryRun(["--role", "worker"], { state: s });
    assert.deepEqual(r.chain, TODAY, s);
    assert.equal(r.prepended, false);
  }
});

test("oc-worker: under + --session → today's chain (no read); under + worker-strong → today's; under + 2 Nvidia drops → [cc-worker, worker, worker-free]", () => {
  const s = dryRun(["--role", "worker", "--session", "ses_abc"], { state: "under" });
  assert.deepEqual(s.chain, TODAY);
  assert.equal(s.reads, 0, "--session pins the backend: the role expansion does not consult the pace");
  assert.deepEqual(dryRun(["--role", "worker-strong"], { state: "under" }).chain, ["worker-strong", "worker-nvidia", "worker-free"]);
  assert.deepEqual(dryRun(["--role", "worker"], { state: "under" }, { drops: 2 }).chain, ["cc-worker", "worker", "worker-free"]);
  assert.deepEqual(dryRun(["--role", "worker"], { state: "on" }, { drops: 2 }).chain, ["worker", "worker-free"]);
  // --agent launches and a launch without opts are today's behaviour
  assert.deepEqual(dryRun(["--agent", "worker", "--fallback", "worker-free"], { state: "under" }).chain, ["worker", "worker-free"]);
  const h = tmp();
  fs.writeFileSync(path.join(h, "m.md"), "x");
  const plain = args(["--role", "worker", "--dir", h, "--prompt", path.join(h, "m.md")]);
  assert.deepEqual([plain.agent, ...plain.fallback], TODAY);
});

test("paceDecision: the detached child's decision round-trips; junk → null", () => {
  const d = paceDecision(JSON.stringify({ cc_pace: { state: "under", weekly: 10, projected: 30, at: "t", prepended: true }, chain: ["cc-worker", "worker"] }));
  assert.deepEqual(d, { cc_pace: { state: "under", weekly: 10, projected: 30, at: "t", prepended: true, shadow: null }, chain: ["cc-worker", "worker"] });
  assert.equal(paceDecision("nope"), null);
  assert.equal(paceDecision(""), null);
  const h = tmp();
  fs.writeFileSync(path.join(h, "m.md"), "x");
  const a = args(["--role", "worker", "--dir", h, "--prompt", path.join(h, "m.md")], { chain: d.chain, pace: () => assert.fail("no read in the child") });
  assert.deepEqual([a.agent, ...a.fallback], ["cc-worker", "worker"]);
});

// ---- oc-worker end to end with the fakes: receipt cc_pace, one read per launch (counting wrapper) ----
function countingBin(h) {
  const count = path.join(h, "pace-reads.txt");
  const bin = path.join(h, "count-pace.mjs");
  fs.writeFileSync(bin, `import fs from "node:fs";\nimport { main } from ${JSON.stringify(CC_PACE)};\nfs.appendFileSync(${JSON.stringify(count)}, "x\\n");\nprocess.exit(main(process.argv.slice(2)));\n`);
  return { bin, reads: () => (fs.existsSync(count) ? fs.readFileSync(count, "utf8").split("\n").filter(Boolean).length : 0) };
}
function ocw(h, argvExtra, extraEnv = {}, name = "w") {
  const dir = path.join(h, `wt-${name}`);
  fs.mkdirSync(dir, { recursive: true });
  const prompt = path.join(h, `${name}-mandate.md`);
  fs.writeFileSync(prompt, "Implement the ticket.");
  const out = path.join(h, "out", `${name}.md`);
  const env = baseEnv(h, { ORCH_CLAUDE_BIN: FAKE_CC, OPENCODE_BIN: FAKE_OC, ORCH_NO_PROCTREE: "1", ORCH_CC_POLL_MS: "50", FAKE_CC_MAX_MS: "60000", FAKE_OC_MAX_MS: "60000", ...extraEnv });
  delete env.WORKER_SLOTS;
  const r = spawnSync(process.execPath, [OCW, "--dir", dir, "--prompt", prompt, "--out", out, ...argvExtra], { env, encoding: "utf8", timeout: 60000 });
  const line = r.stdout.trim().split("\n").filter((l) => l.startsWith("{")).pop();
  const fileReceipt = fs.existsSync(out + ".receipt.json") ? JSON.parse(fs.readFileSync(out + ".receipt.json", "utf8")) : null;
  return { ...r, receipt: line ? JSON.parse(line) : null, fileReceipt, out };
}
const FIVE = ["at", "prepended", "projected", "shadow", "state", "weekly"];

test("oc-worker under --role worker: cc-worker runs first (detached), one pace read, receipt cc_pace prepended", () => {
  const h = paceHome("under");
  const c = countingBin(h);
  const r = ocw(h, ["--role", "worker"], { ORCH_PACE_BIN: c.bin });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, /detached run pid/);
  assert.equal(r.receipt.agent, "cc-worker");
  assert.deepEqual(Object.keys(r.receipt.cc_pace).sort(), FIVE);
  assert.equal(r.receipt.cc_pace.state, "under");
  assert.equal(r.receipt.cc_pace.prepended, true);
  assert.equal(r.receipt.cc_pace.weekly, 10);
  assert.equal(typeof r.receipt.cc_pace.projected, "number");
  assert.equal(typeof r.receipt.cc_pace.at, "string");
  assert.deepEqual(r.fileReceipt.cc_pace, r.receipt.cc_pace);
  assert.equal(c.reads(), 1, "the detached child must not read the pace again");
});

test("oc-worker under --role worker --session: today's chain (worker-nvidia, an OpenCode session), prepended false", () => {
  const h = paceHome("under");
  const c = countingBin(h);
  const r = ocw(h, ["--role", "worker", "--session", "ses_prev"], { ORCH_PACE_BIN: c.bin });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.receipt.agent, "worker-nvidia");
  assert.equal(r.receipt.cc_pace.state, "under");
  assert.equal(r.receipt.cc_pace.prepended, false);
  assert.equal(c.reads(), 1, "the receipt still reads the pace once");
});

test("oc-worker over --role worker: today's chain; --agent launch with ORCH_NO_PACE=1 records off", () => {
  const h = paceHome("over");
  const r = ocw(h, ["--role", "worker"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.receipt.agent, "worker-nvidia");
  assert.equal(r.receipt.cc_pace.state, "over");
  assert.equal(r.receipt.cc_pace.prepended, false);
  const off = ocw(h, ["--agent", "critic"], { ORCH_NO_PACE: "1" }, "c");
  assert.equal(off.receipt.agent, "critic");
  assert.deepEqual(Object.keys(off.fileReceipt.cc_pace).sort(), FIVE);
  assert.equal(off.fileReceipt.cc_pace.state, "off");
});

test("oc-worker: a broken pace read records unknown and the run still succeeds", () => {
  const h = paceHome("under");
  const r = ocw(h, ["--agent", "worker"], { ORCH_PACE_BIN: path.join(h, "missing", "cc-pace.mjs") });
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.receipt.cc_pace, { state: "unknown", weekly: null, projected: null, at: null, prepended: false, shadow: null });
  assert.deepEqual(r.fileReceipt.cc_pace, r.receipt.cc_pace);
  const role = ocw(h, ["--role", "worker"], { ORCH_PACE_BIN: path.join(h, "missing", "cc-pace.mjs") }, "r");
  assert.equal(role.status, 0, role.stderr);
  assert.equal(role.receipt.agent, "worker-nvidia", "an unknown pace keeps today's chain");
});

test("oc-worker: a forged ORCH_PACE_DECISION without ORCH_DETACHED_CHILD=1 is ignored (today's chain, own pace read)", () => {
  const h = paceHome("over");
  const c = countingBin(h);
  const forged = JSON.stringify({ cc_pace: { state: "under", weekly: 1, projected: 2, at: "forged", prepended: true }, chain: ["cc-worker", "worker"] });
  const r = ocw(h, ["--role", "worker"], { ORCH_PACE_BIN: c.bin, ORCH_PACE_DECISION: forged });
  assert.equal(r.status, 0, r.stderr);
  assert.doesNotMatch(r.stderr, /detached run pid/, "a worker-nvidia run is not detached");
  assert.equal(r.receipt.agent, "worker-nvidia", "the forged chain must not be used");
  assert.equal(r.receipt.cc_pace.state, "over");
  assert.equal(r.receipt.cc_pace.prepended, false);
  assert.notEqual(r.receipt.cc_pace.at, "forged");
  assert.equal(c.reads(), 1, "the launch reads the pace itself");
});

test("oc-worker: the detached child strips ORCH_PACE_DECISION and ORCH_DETACHED_CHILD from its run's env", () => {
  const h = paceHome("under");
  const envFile = path.join(h, "claude-env.json");
  const wrapper = path.join(h, "env-claude.mjs");
  fs.writeFileSync(wrapper, `import fs from "node:fs";\nfs.writeFileSync(${JSON.stringify(envFile)}, JSON.stringify({ decision: process.env.ORCH_PACE_DECISION ?? null, detached: process.env.ORCH_DETACHED_CHILD ?? null }));\nawait import(${JSON.stringify(FAKE_CC)});\n`);
  const r = ocw(h, ["--role", "worker"], { ORCH_CLAUDE_BIN: wrapper });
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, /detached run pid/, "the run went through the detached child");
  assert.equal(r.receipt.agent, "cc-worker");
  assert.equal(r.receipt.cc_pace.prepended, true, "the child used the launcher's decision");
  const seen = JSON.parse(fs.readFileSync(envFile, "utf8"));
  assert.deepEqual(seen, { decision: null, detached: null }, "a nested oc-worker inside the run must not inherit either variable");
});

// ---- senior finding 1: the vision filter vs the first hop ----
const NV_MODEL = "nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b"; // in VISION_CAPABLE_MODELS
function agentFiles(h, agents) {
  const d = path.join(h, ".config", "opencode", "agents");
  fs.mkdirSync(d, { recursive: true });
  for (const [n, { model, vision }] of Object.entries(agents)) fs.writeFileSync(path.join(d, `${n}.md`), `---\nmode: subagent\nmodel: ${model}\n${vision ? "vision: true\n" : ""}---\nx\n`);
  const mf = path.join(h, "oc-models.txt");
  fs.writeFileSync(mf, Object.values(agents).map((x) => x.model).join("\n") + "\n");
  return mf;
}
const VISION_AGENTS = {
  "worker-nvidia": { model: NV_MODEL, vision: true },
  worker: { model: "opencode-go/mimo-v2.6-flash" },
  "worker-free": { model: "opencode/deepseek-v4.1-flash-free" },
};
/** A Mandate naming an existing image in the worktree (auto-vision). */
function imageMandate(h, name) {
  const dir = path.join(h, `wt-${name}`);
  fs.mkdirSync(path.join(dir, "static"), { recursive: true });
  fs.writeFileSync(path.join(dir, "static", "icon.png"), Buffer.from([0x89, 0x50, 0x4e, 0x47]));
  return " Match the design in static/icon.png exactly.";
}
function ocwPrompt(h, argvExtra, extraEnv, name, text) {
  const dir = path.join(h, `wt-${name}`);
  fs.mkdirSync(dir, { recursive: true });
  const prompt = path.join(h, `${name}-mandate.md`);
  fs.writeFileSync(prompt, `Implement the ticket.${text}`);
  const out = path.join(h, "out", `${name}.md`);
  const env = baseEnv(h, { ORCH_CLAUDE_BIN: FAKE_CC, OPENCODE_BIN: FAKE_OC, ORCH_NO_PROCTREE: "1", ORCH_CC_POLL_MS: "50", ORCH_NVIDIA_POLL_MS: "50", FAKE_CC_MAX_MS: "60000", FAKE_OC_MAX_MS: "60000", ...extraEnv });
  delete env.WORKER_SLOTS;
  const r = spawnSync(process.execPath, [OCW, "--dir", dir, "--prompt", prompt, "--out", out, ...argvExtra], { env, encoding: "utf8", timeout: 60000 });
  const line = r.stdout.trim().split("\n").filter((l) => l.startsWith("{")).pop();
  return { ...r, receipt: line ? JSON.parse(line) : null };
}
const health = (h) => {
  try { return JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "pool-health.json"), "utf8")); } catch { return {}; }
};
const healthKeys = (h) => JSON.stringify(health(h));

test("senior repro: under + image Mandate + cc-worker usage limit → cc-worker marked down (not Nvidia), re-pools to worker-nvidia, exit 0", () => {
  const h = paceHome("under");
  const mf = agentFiles(h, VISION_AGENTS);
  const text = imageMandate(h, "v");
  const ocArgs = path.join(h, "oc-args.json");
  const r = ocwPrompt(h, ["--role", "worker"], { ORCH_OPENCODE_MODELS_FILE: mf, FAKE_CC_MODE: "usage-limit", FAKE_OC_ARGS_FILE: ocArgs }, "v", text);
  assert.equal(r.status, 0, r.stderr + r.stdout);
  assert.equal(r.receipt.cc_pace.prepended, true);
  assert.equal(r.receipt.vision?.auto_detected, true, "the image Mandate turned vision on");
  assert.equal(r.receipt.agent, "worker-nvidia");
  assert.equal(r.receipt.repooled_from?.[0]?.agent, "cc-worker", "cc-worker ran first");
  assert.match(r.receipt.repooled_from[0].error, /limit/i);
  const hl = healthKeys(h);
  assert.match(hl, /"cc-worker"/, "the cc-worker pool is marked down");
  assert.ok(!hl.includes(NV_MODEL), `the Nvidia model must not be marked down: ${hl}`);
  const { argv } = JSON.parse(fs.readFileSync(ocArgs, "utf8"));
  assert.equal(argv[argv.indexOf("--agent") + 1], "worker-nvidia");
  assert.equal(argv.includes("--session"), false, "a fallback hop starts a fresh OpenCode session");
});

test("vision filter drops a.agent: the first hop runs and books the same agent (worker-nvidia), fresh session, its own model", () => {
  const h = paceHome("over");
  const mf = agentFiles(h, VISION_AGENTS);
  const text = imageMandate(h, "f");
  const ocArgs = path.join(h, "oc-args.json");
  const r = ocwPrompt(h, ["--agent", "worker", "--fallback", "worker-nvidia", "--session", "ses_old", "--model", "opencode-go/mimo-v2.6-flash"], { ORCH_OPENCODE_MODELS_FILE: mf, FAKE_OC_ARGS_FILE: ocArgs }, "f", text);
  assert.equal(r.status, 0, r.stderr + r.stdout);
  const { argv } = JSON.parse(fs.readFileSync(ocArgs, "utf8"));
  assert.equal(argv[argv.indexOf("--agent") + 1], "worker-nvidia", "the agent that ran is the one the hop booked");
  assert.equal(argv.includes("ses_old"), false, "the dropped agent's session is not handed on");
  assert.equal(r.receipt.agent, "worker-nvidia");
  assert.equal(r.receipt.model, NV_MODEL);
});

// ---- senior finding 2: --role worker --session <Claude session id> resumes on cc-worker ----
const CLAUDE_SES = "0b6f3c2e-1d4a-4f6b-9c8e-2a7d5e9f1b3c";

test("dry: --role worker --session <non-ses_ id> → [cc-worker, today's chain] in every pace state, no pace read; ses_ keeps today's", () => {
  for (const s of ["over", "unknown", "on", "off", "under"]) {
    const r = dryRun(["--role", "worker", "--session", CLAUDE_SES], { state: s });
    assert.deepEqual(r.chain, ["cc-worker", ...TODAY], s);
    assert.equal(r.prepended, false);
    assert.equal(r.reads, 0);
  }
  assert.deepEqual(dryRun(["--role", "worker", "--session", CLAUDE_SES], { state: "over" }, { drops: 2 }).chain, ["cc-worker", "worker", "worker-free"]);
  assert.deepEqual(dryRun(["--role", "worker", "--session", "ses_x"], { state: "under" }).chain, TODAY);
  assert.deepEqual(dryRun(["--role", "worker-strong", "--session", CLAUDE_SES], { state: "under" }).chain, ["worker-strong", "worker-nvidia", "worker-free"]);
});

for (const state of ["over", "unknown"]) {
  test(`oc-worker ${state}: --role worker --session <Claude id> resumes on cc-worker (fake claude gets --resume <id>), prepended false`, () => {
    const h = paceHome(state);
    const c = countingBin(h);
    const ccArgs = path.join(h, "cc-args.json");
    const r = ocw(h, ["--role", "worker", "--session", CLAUDE_SES], { ORCH_PACE_BIN: c.bin, FAKE_CC_ARGS_FILE: ccArgs });
    assert.equal(r.status, 0, r.stderr);
    assert.equal(r.receipt.agent, "cc-worker");
    const { argv } = JSON.parse(fs.readFileSync(ccArgs, "utf8"));
    assert.equal(argv[argv.indexOf("--resume") + 1], CLAUDE_SES);
    assert.equal(r.receipt.cc_pace.state, state);
    assert.equal(r.receipt.cc_pace.prepended, false);
    assert.equal(c.reads(), 1, "one read, for the receipt only");
  });
}

// ---- check-routing: cc-worker is a known agent ----
test("check-routing: --agent cc-worker (with or without --fallback) is not flagged; the shipped rules and commands are green", () => {
  const root = tmp();
  fs.mkdirSync(path.join(root, "commands"), { recursive: true });
  fs.writeFileSync(path.join(root, "commands", "w.md"), "run node bin/oc-worker.mjs --agent cc-worker --dir x\nrun node bin/oc-worker.mjs --agent cc-worker --fallback worker,worker-free\n");
  const r = checkRouting({ root, extra: [], models: new Set() });
  assert.deepEqual(r.problems, []);
  const repo = path.join(HERE, "..");
  const home = tmp();
  const live = withEnv({ ORCH_HOME: home }, () => checkRouting({ root: repo, extra: [], models: null }));
  assert.deepEqual(live.problems, []);
});

test("ccPaceRecord.shadow: numbers from a pace with ledger, null without; a record's shadow round-trips (detached child)", () => {
  const pace = { state: "on", weekly: 40, projected: 70, at: "t", ledger: { k: 1e-4, rms: 0, pairs: 4, unmetered: 0, scanned_at: "s", nowcast_weekly: 41.5, ledger_rate: 0.6 } };
  const rec = ccPaceRecord(pace, false);
  assert.deepEqual(rec, { state: "on", weekly: 40, projected: 70, at: "t", prepended: false, shadow: { nowcast_weekly: 41.5, ledger_rate: 0.6 } });
  assert.equal(ccPaceRecord({ ...pace, ledger: null }).shadow, null);
  assert.equal(ccPaceRecord({ state: "on" }).shadow, null);
  assert.deepEqual(ccPaceRecord({ ...pace, ledger: { nowcast_weekly: "x", ledger_rate: NaN } }).shadow, { nowcast_weekly: null, ledger_rate: null });
  assert.deepEqual(ccPaceRecord(rec, false), rec, "re-recording a record keeps its shadow");
  assert.deepEqual(paceDecision(JSON.stringify({ cc_pace: rec, chain: null })).cc_pace, rec);
  assert.deepEqual(paceChain("worker", TODAY, pace), TODAY, "the shadow never routes");
});

// cc-pacing-v2 A3a: the headless Claude backend for every role (cc-worker-strong, cc-critic, cc-senior).
// fixtures/fake-claude.mjs stands in for `claude` (ORCH_CLAUDE_BIN); ORCH_HOME is a temp dir, so nothing touches the
// real ~/.config. Every child has a timeout and the fixture has a life cap.
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { READONLY_AGENT_RE, VERDICT_AGENT_RE, ccModels, isCcAgent, isCcReader, ccSlotKey, ccModelFor, ccToolArgs, capReader, paceDecision, gateFree, args as parseArgs } from "../bin/oc-worker.mjs";
import { isCcPool } from "../bin/pool-health.mjs";
import { installFixtureGuard } from "./fixtures/fixture-guard.mjs";

installFixtureGuard();

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");
const FAKE_CC = path.join(HERE, "fixtures", "fake-claude.mjs");
const FAKE_OC = path.join(HERE, "fixtures", "fake-opencode.mjs");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});
// Every temp home carries the cc readers' role contracts (<home>/.claude/agents/{critic,senior}.md, A4 r2): a cc reader
// without one is skipped (cc-no-contract). Pass { contracts: false } for a home without them.
const CONTRACT = (role) => `---\nname: ${role}\nmodel: sonnet\nFRONTMATTER-MARKER-${role}\n---\nCONTRACT-MARKER-${role}: you are the ${role}.\n`;
function writeContracts(home, roles = ["critic", "senior"]) {
  const d = path.join(home, ".claude", "agents");
  fs.mkdirSync(d, { recursive: true });
  for (const r of roles) fs.writeFileSync(path.join(d, `${r}.md`), CONTRACT(r));
}
const tmp = ({ contracts = true } = {}) => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ccroles-"));
  CLEAN.push(d);
  if (contracts) writeContracts(d);
  return d;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const orchDir = (home) => path.join(home, ".config", "orchestrator");
const slotsOf = (home) => path.join(orchDir(home), "slots");
const limits = (home, cc) => {
  fs.mkdirSync(orchDir(home), { recursive: true });
  fs.writeFileSync(path.join(orchDir(home), "usage-limits.json"), JSON.stringify({ cc }));
};

function env(home, extra = {}) {
  const e = { ...process.env, ORCH_CLAUDE_BIN: FAKE_CC, OPENCODE_BIN: FAKE_OC, ORCH_NO_PROCTREE: "1", ORCH_HOME: home, ORCH_CC_POLL_MS: "50", ORCH_NO_PACE: "1", FAKE_CC_MAX_MS: "60000", FAKE_OC_MAX_MS: "60000", ...extra };
  delete e.WORKER_SLOTS;
  delete e.ORCH_NO_READONLY_GUARD;
  delete e.ORCH_PACE_DECISION;
  delete e.ORCH_DETACHED_CHILD;
  for (const [k, v] of Object.entries(extra)) if (v === undefined) delete e[k];
  return e;
}
function setup(home, name) {
  const dir = path.join(home, `wt-${name}`);
  fs.mkdirSync(dir, { recursive: true });
  const prompt = path.join(home, `${name}-mandate.md`);
  fs.writeFileSync(prompt, "Review the ticket.");
  return { dir, prompt, out: path.join(home, "out", `${name}.md`), argsFile: path.join(home, `${name}-args.json`), argvOut: path.join(home, `${name}-argv.json`) };
}
const flags = (agent, s, extra = []) => ["--agent", agent, "--dir", s.dir, "--prompt", s.prompt, "--out", s.out, ...extra];
function runSync(home, agent, name, extra = [], extraEnv = {}, prep) {
  const s = setup(home, name);
  if (prep) prep(s);
  const r = spawnSync(process.execPath, [BIN, ...flags(agent, s, extra)], { env: env(home, { FAKE_CC_ARGS_FILE: s.argsFile, FAKE_CC_ARGV_OUT: s.argvOut, ...extraEnv }), encoding: "utf8", timeout: 60000 });
  const last = r.stdout.trim().split("\n").pop() || "";
  return { ...r, ...s, receipt: last.startsWith("{") ? JSON.parse(last) : null, argv: fs.existsSync(s.argvOut) ? JSON.parse(fs.readFileSync(s.argvOut, "utf8")) : null };
}
function runAsync(home, agent, name, extra = [], extraEnv = {}) {
  const s = setup(home, name);
  const child = spawn(process.execPath, [BIN, ...flags(agent, s, extra)], { env: env(home, { FAKE_CC_ARGS_FILE: s.argsFile, ...extraEnv }), stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  child.stdout.on("data", (d) => (stdout += d));
  child.stderr.on("data", () => {});
  const killer = setTimeout(() => child.kill("SIGKILL"), 45000);
  const done = new Promise((resolve) => child.on("close", (code) => { clearTimeout(killer); resolve({ code, stdout, endedAt: Date.now(), ...s }); }));
  return { child, done, ...s, started: () => fs.existsSync(s.argsFile) };
}
const waitFor = async (fn, ms = 15000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return true; await sleep(50); }
  return false;
};
const val = (argv, f) => argv[argv.indexOf(f) + 1];
const gitInit = (dir) => {
  const g = (...a) => spawnSync("git", ["-c", "user.name=t", "-c", "user.email=t@example.invalid", ...a], { cwd: dir, encoding: "utf8", timeout: 20000 });
  g("init", "-q");
  fs.writeFileSync(path.join(dir, "a.txt"), "a\n");
  g("add", "a.txt");
  g("commit", "-q", "-m", "init");
};
const WRITER_TOOLS = ["--tools", "Read,Grep,Glob,Edit,Write,Bash", "--strict-mcp-config", "--permission-mode", "acceptEdits", "--allowedTools", "Bash"];

// ---- unit: names, regexes, models, tools ----

test("cc agents: default cc.models keys; readers are cc-critic/cc-senior; slot keys cc / ccread", () => {
  assert.deepEqual(ccModels(), { "cc-worker": "sonnet", "cc-worker-strong": "opus", "cc-critic": "opus", "cc-senior": "fable" });
  for (const a of ["cc-worker", "cc-worker-strong", "cc-critic", "cc-senior"]) assert.ok(isCcAgent(a), a);
  for (const a of ["worker", "critic", "cc-nope", "", undefined]) assert.ok(!isCcAgent(a), String(a));
  assert.deepEqual(["cc-worker", "cc-worker-strong", "cc-critic", "cc-senior"].map(isCcReader), [false, false, true, true]);
  assert.deepEqual(["cc-worker", "cc-worker-strong", "cc-critic", "cc-senior"].map(ccSlotKey), ["cc", "cc", "ccread", "ccread"]);
  assert.ok(!"ccread".startsWith("cc-"), "ccread is not under the provider-cc- prefix");
  assert.equal(ccModelFor("cc-senior"), "fable");
  assert.equal(ccModelFor("cc-senior", { fableOver: true }), "opus");
  assert.equal(ccModelFor("cc-critic", { fableOver: true }), "opus");
  assert.deepEqual(ccToolArgs("cc-worker"), WRITER_TOOLS);
  assert.deepEqual(ccToolArgs("cc-worker-strong"), WRITER_TOOLS);
  assert.ok(isCcPool("cc-critic") && !isCcPool("ccread") && !isCcPool("opencode-go/x"));
});

test("READONLY_AGENT_RE / VERDICT_AGENT_RE: OpenCode roles unchanged, cc readers added, writers not", () => {
  for (const a of ["critic", "critic-free", "senior", "scout", "explorer", "cc-critic", "cc-senior"]) assert.ok(READONLY_AGENT_RE.test(a), a);
  for (const a of ["worker", "cc-worker", "cc-worker-strong", "critical", "orchestrator"]) assert.ok(!READONLY_AGENT_RE.test(a), a);
  for (const a of ["critic", "critic-free", "senior", "cc-critic", "cc-senior"]) assert.ok(VERDICT_AGENT_RE.test(a), a);
  for (const a of ["worker", "cc-worker", "scout", "cc-worker-strong"]) assert.ok(!VERDICT_AGENT_RE.test(a), a);
});

test("cc.models from usage-limits.json merges over the default; capReader reads cc.<key>, else the default", () => {
  const home = tmp();
  const prev = process.env.ORCH_HOME;
  process.env.ORCH_HOME = home;
  try {
    limits(home, { models: { "cc-critic": "sonnet", "cc-scout": "haiku", plain: "x", "cc-empty": "" }, max_readers: 2, max_workers: 0 });
    const m = ccModels();
    assert.equal(m["cc-critic"], "sonnet");
    assert.equal(m["cc-scout"], "haiku");
    assert.equal(m["cc-worker"], "sonnet");
    assert.ok(!("plain" in m) && !("cc-empty" in m));
    assert.ok(isCcAgent("cc-scout") && isCcReader("cc-scout"));
    assert.equal(capReader("max_readers", 1)(), 2);
    assert.equal(capReader("max_workers", 1)(), 1, "a non-positive cap reads as the default");
  } finally {
    if (prev === undefined) delete process.env.ORCH_HOME; else process.env.ORCH_HOME = prev;
  }
});

test("paceDecision carries fable_over only when set (the round-trip without it is unchanged)", () => {
  const cc_pace = { state: "on", weekly: 1, projected: 2, at: "t", prepended: false, role: null, shadow: null };
  assert.deepEqual(paceDecision(JSON.stringify({ cc_pace, chain: null })), { cc_pace, chain: null });
  assert.deepEqual(paceDecision(JSON.stringify({ cc_pace, chain: null, fable_over: true })), { cc_pace, chain: null, fable_over: true });
});

// ---- end to end through the fake claude ----

test("cc-worker argv is unchanged (writer tools, acceptEdits, sonnet)", () => {
  const home = tmp();
  const r = runSync(home, "cc-worker", "w");
  assert.equal(r.status, 0, r.stderr);
  assert.deepEqual(r.argv.slice(2), ["--model", "sonnet", "--settings", JSON.stringify({ disableAllHooks: true }), ...WRITER_TOOLS, "--permission-prompts", "none", "--output-format", "stream-json", "--verbose"]);
  assert.equal(r.receipt.model, "sonnet");
  assert.equal(r.receipt.gate, null);
});

test("--agent cc-critic: opus, reader tools, no acceptEdits; receipt model opus and a gate; detached by default", () => {
  const home = tmp();
  const r = runSync(home, "cc-critic", "c");
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, /oc-worker: detached run pid \d+/, "cc-critic detaches by default, as cc-worker");
  const argv = r.argv;
  assert.equal(argv[0], "-p");
  assert.match(argv[1], /read-only role[\s\S]*ORCH_SCRATCH/, "the read-only footer is in the prompt");
  assert.equal(val(argv, "--model"), "opus");
  assert.equal(val(argv, "--tools"), "Read,Grep,Glob,Bash");
  assert.equal(val(argv, "--allowedTools"), "Bash");
  assert.equal(val(argv, "--disallowedTools"), "Edit,Write,NotebookEdit");
  assert.ok(!argv.includes("acceptEdits") && !argv.includes("--permission-mode"));
  assert.equal(val(argv, "--settings"), JSON.stringify({ disableAllHooks: true }));
  assert.equal(val(argv, "--output-format"), "stream-json");
  assert.ok(argv.includes("--strict-mcp-config") && argv.includes("--verbose"));
  assert.equal(r.receipt.agent, "cc-critic");
  assert.equal(r.receipt.model, "opus");
  assert.ok(r.receipt.gate && typeof r.receipt.gate === "object", "a cc critic gets the verdict gate");
  assert.ok(!r.receipt.readonly_violation);
  assert.deepEqual(fs.readdirSync(slotsOf(home)), [], "slots released");
});

test("--agent cc-worker-strong: opus with writer tools", () => {
  const home = tmp();
  const r = runSync(home, "cc-worker-strong", "s", ["--no-detach"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(val(r.argv, "--model"), "opus");
  assert.deepEqual(r.argv.slice(r.argv.indexOf("--tools"), r.argv.indexOf("--tools") + WRITER_TOOLS.length), WRITER_TOOLS);
  assert.ok(!r.argv.includes("--disallowedTools"));
  assert.equal(r.receipt.model, "opus");
  assert.equal(r.receipt.gate, null);
});

test("FAKE_CC_MODE=edit on cc-critic → readonly_violation and an INVALID gate", () => {
  const home = tmp();
  const r = runSync(home, "cc-critic", "e", ["--no-detach"], { FAKE_CC_MODE: "edit" }, (s) => gitInit(s.dir));
  assert.ok(fs.existsSync(path.join(r.dir, "fake-edit.txt")), "the fake wrote in its cwd");
  assert.equal(r.receipt.readonly_violation, true, r.stderr);
  assert.ok(r.receipt.errors.includes("read-only role changed the worktree"));
  assert.equal(r.receipt.gate.effective, "INVALID");
  assert.ok(r.receipt.gate.reasons.includes("readonly_violation"));
});

test("cc-senior: fable by default; opus when the pace says fable.state over (ORCH_PACE_BIN)", () => {
  const home = tmp();
  const pace = (fable) => {
    const p = path.join(home, `pace-${fable}.mjs`);
    fs.writeFileSync(p, `console.log(JSON.stringify({ state: "on", weekly: 1, projected: 2, at: "t", fable: { state: ${JSON.stringify(fable)} } }));\n`);
    return p;
  };
  const over = runSync(home, "cc-senior", "so", [], { ORCH_NO_PACE: undefined, ORCH_PACE_BIN: pace("over") });
  assert.equal(over.status, 0, over.stderr);
  assert.equal(val(over.argv, "--model"), "opus");
  assert.equal(over.receipt.model, "opus");
  assert.equal(val(over.argv, "--tools"), "Read,Grep,Glob,Bash");
  const on = runSync(home, "cc-senior", "sn", [], { ORCH_NO_PACE: undefined, ORCH_PACE_BIN: pace("on") });
  assert.equal(val(on.argv, "--model"), "fable");
  assert.equal(on.receipt.model, "fable");
  const off = runSync(home, "cc-senior", "sf");
  assert.equal(off.receipt.model, "fable");
});

test("cc.max_readers 1: a second reader waits on ccread while a cc-worker runs alongside", async () => {
  const home = tmp();
  const slow = { FAKE_CC_MODE: "slow", FAKE_CC_DELAY: "2500" };
  const r1 = runAsync(home, "cc-critic", "r1", [], slow);
  assert.ok(await waitFor(r1.started), "reader 1 started");
  assert.ok(fs.existsSync(path.join(slotsOf(home), "provider-ccread-1")), "reader 1 holds provider-ccread-1");
  const w = runAsync(home, "cc-worker", "w", [], slow);
  assert.ok(await waitFor(w.started), "a cc-worker runs while a reader holds ccread");
  assert.ok(fs.existsSync(path.join(slotsOf(home), "provider-cc-1")));
  const r2 = runAsync(home, "cc-critic", "r2", [], slow);
  await sleep(700);
  assert.ok(!r2.started(), "reader 2 waits on ccread");
  const [a, b, c] = await Promise.all([r1.done, w.done, r2.done]);
  assert.equal(a.code, 0);
  assert.equal(b.code, 0);
  assert.equal(c.code, 0, "the waiting reader runs after the first");
  assert.ok(fs.statSync(r2.argsFile).mtimeMs >= a.endedAt - 600, "reader 2 started only after reader 1 finished");
  assert.deepEqual(fs.readdirSync(slotsOf(home)).filter((n) => n.startsWith("provider-")), []);
});

test("a reader does not block the writer slot: a waiting cc-worker is not held up by a cc-critic", async () => {
  const home = tmp();
  const slow = { FAKE_CC_MODE: "slow", FAKE_CC_DELAY: "2500" };
  const w1 = runAsync(home, "cc-worker", "w1", [], slow);
  assert.ok(await waitFor(w1.started));
  const c = runAsync(home, "cc-critic", "c1", [], slow);
  assert.ok(await waitFor(c.started), "a reader runs while a writer holds cc");
  for (const r of await Promise.all([w1.done, c.done])) assert.equal(r.code, 0);
});

test("cc.reader_wait_min 0.01 with ccread held → the reader skips to the --fallback agent, notes cc-slot-timeout", () => {
  const home = tmp();
  limits(home, { reader_wait_min: 0.01 });
  const held = path.join(slotsOf(home), "provider-ccread-1");
  fs.mkdirSync(held, { recursive: true });
  fs.writeFileSync(path.join(held, "owner"), JSON.stringify({ pid: process.pid, agent: "cc-critic", title: "holder", since: new Date().toISOString() }));
  const r = runSync(home, "cc-critic", "t", ["--no-detach", "--fallback", "cc-worker"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.receipt.agent, "cc-worker", "the next chain agent ran");
  assert.equal(val(r.argv, "--model"), "sonnet");
  assert.ok(r.receipt.notes.some((n) => /^cc-slot-timeout: cc-critic waited 0\.01 min/.test(n)), JSON.stringify(r.receipt.notes));
  assert.ok(r.receipt.repooled_from.some((h) => h.agent === "cc-critic" && h.skipped && /^cc-slot-timeout/.test(h.reason)));
  assert.equal(r.receipt.attempts, 1, "the skipped reader used no attempt");
  const saved = JSON.parse(fs.readFileSync(r.out + ".receipt.json", "utf8"));
  assert.ok(saved.notes.some((n) => /cc-slot-timeout/.test(n)));
  assert.ok(fs.existsSync(held), "the holder's slot is untouched");
  fs.rmSync(held, { recursive: true, force: true });
});

test("cc-slot-timeout with no fallback: no agent ran, errors name cc-slot-timeout", () => {
  const home = tmp();
  limits(home, { reader_wait_min: 0.01 });
  const held = path.join(slotsOf(home), "provider-ccread-1");
  fs.mkdirSync(held, { recursive: true });
  fs.writeFileSync(path.join(held, "owner"), JSON.stringify({ pid: process.pid, agent: "cc-critic", since: new Date().toISOString() }));
  const r = runSync(home, "cc-critic", "t0", ["--no-detach"]);
  assert.equal(r.status, 6, r.stderr);
  assert.ok(r.receipt.errors.some((e) => /^cc-slot-timeout/.test(e)));
  assert.ok(r.receipt.notes.some((n) => /^cc-slot-timeout/.test(n)));
  assert.equal(r.argv, null, "claude never started");
  fs.rmSync(held, { recursive: true, force: true });
});

test("a usage limit on cc-critic marks the whole cc group down (cc-worker too), and a cc-worker launch then skips", () => {
  const home = tmp();
  const reset = Math.floor(Date.now() / 1000) + 3 * 3600;
  const r = runSync(home, "cc-critic", "u", ["--no-detach"], { FAKE_CC_MODE: "usage-limit", FAKE_CC_RESET_S: String(reset) });
  assert.notEqual(r.status, 0);
  const h = JSON.parse(fs.readFileSync(path.join(orchDir(home), "pool-health.json"), "utf8"));
  for (const k of ["cc-worker", "cc-worker-strong", "cc-critic", "cc-senior"]) {
    assert.equal(h[k]?.reason, "quota", k);
    assert.equal(h[k].until, h["cc-critic"].until, `${k} shares the same mark`);
    assert.ok(Math.abs(Date.parse(h[k].until) - reset * 1000) < 1000, `${k} is down until the message's reset`);
  }
  const w = runSync(home, "cc-worker", "u2", ["--no-detach"]);
  assert.equal(w.status, 6, "cc-worker is down with the group");
  assert.equal(w.argv, null);
});

test("pool-health group read-back: any live cc-* mark holds every cc agent down; an answer clears the group", async () => {
  const home = tmp();
  const prev = process.env.ORCH_HOME;
  process.env.ORCH_HOME = home;
  try {
    const ph = await import("../bin/pool-health.mjs");
    ph.markDown("cc-senior", { reason: "rate-limit", ms: 60_000 });
    assert.equal(ph.isDown("cc-worker")?.key, "cc-senior");
    assert.equal(ph.isDown("cc-critic")?.reason, "rate-limit");
    assert.equal(ph.isDown("opencode-go/some-model"), null, "other pools are untouched");
    ph.markDown("opencode-go/some-model", { reason: "quota", ms: 60_000 });
    ph.markUp("cc-worker");
    assert.equal(ph.isDown("cc-senior"), null);
    assert.ok(ph.isDown("opencode-go/some-model"), "markUp on cc leaves other pools alone");
  } finally {
    if (prev === undefined) delete process.env.ORCH_HOME; else process.env.ORCH_HOME = prev;
  }
});

// ---- cc-pacing-v2-a3b ----

test("gateFree: a cc critic is paid explicitly, even with a free-looking model; OpenCode critics unchanged", () => {
  for (const agent of ["cc-critic", "cc-senior"]) {
    assert.equal(gateFree({ agent }), false, agent);
    assert.equal(gateFree({ agent, model: "opus" }), false, agent);
    assert.equal(gateFree({ agent, model: "opencode/some-model-free" }), false, `${agent}: no model makes a cc agent free`);
  }
  assert.equal(gateFree({ agent: "critic-free" }), true, "a *-free OpenCode agent is free");
  assert.equal(gateFree({ agent: "critic", model: "opencode/some-model-free" }), true, "an opencode/*-free model is free");
});

test("a lone cc-critic whose ccread wait times out ends with exit cc-slot-timeout (status 6), not no-healthy-pool", () => {
  const home = tmp();
  limits(home, { reader_wait_min: 0.01 });
  const held = path.join(slotsOf(home), "provider-ccread-1");
  fs.mkdirSync(held, { recursive: true });
  fs.writeFileSync(path.join(held, "owner"), JSON.stringify({ pid: process.pid, agent: "cc-critic", since: new Date().toISOString() }));
  const r = runSync(home, "cc-critic", "lone", ["--no-detach"]);
  assert.equal(r.status, 6, r.stderr);
  assert.equal(r.receipt.exit, "cc-slot-timeout");
  assert.equal(r.receipt.model, "opus", "the cc model, not (agent default)");
  const saved = JSON.parse(fs.readFileSync(r.out + ".receipt.json", "utf8"));
  assert.equal(saved.exit, "cc-slot-timeout");
  assert.equal(r.argv, null, "claude never started");
  fs.rmSync(held, { recursive: true, force: true });
});

// ---- cc-pacing-v2 A4: --role <r> --session <Claude id> resumes on r's cc agent, in every pace state ----
test("A4 --session: --role critic --session <Claude id> → cc-critic first in every pace state, no pace read; ses_ → today", () => {
  const home = tmp();
  const prompt = path.join(home, "m.md");
  fs.writeFileSync(prompt, "Review.");
  const CLAUDE = "7c1d2e3f-4a5b-4c6d-8e9f-0a1b2c3d4e5f";
  const CRITIC = ["critic", "critic-go", "critic-nvidia", "critic-free"];
  const dry = (role, session, pace) => {
    let reads = 0;
    const a = parseArgs(["--role", role, "--session", session, "--dir", home, "--prompt", prompt, "--out", path.join(home, "o.md")], { pace: () => (reads++, pace) });
    return { chain: [a.agent, ...a.fallback], prepended: a.pacePrepended === true, reads };
  };
  for (const state of ["under", "on", "over", "unknown", "off"]) {
    for (const fable of ["ok", "over"]) {
      const pace = { state, fable: { state: fable } };
      const r = dry("critic", CLAUDE, pace);
      assert.deepEqual(r.chain, ["cc-critic", ...CRITIC], `${state}/${fable}`);
      assert.equal(r.prepended, false);
      assert.equal(r.reads, 0);
      assert.deepEqual(dry("critic", "ses_x", pace).chain, CRITIC, `${state}/${fable} ses_`);
      assert.deepEqual(dry("senior", CLAUDE, pace).chain, ["cc-senior", "senior", "senior-nvidia", "senior-free"], "a Claude session resumes on cc-senior even with Fable over");
      assert.deepEqual(dry("worker-strong", CLAUDE, pace).chain, ["cc-worker-strong", "worker-strong", "worker-nvidia", "worker-free"]);
      assert.deepEqual(dry("scout", CLAUDE, pace).chain, ["scout", "worker-nvidia", "critic-nvidia"], "scout is never paced");
    }
  }
});

// ---- cc-pacing-v2 A4 r2: a cc reader runs with its role contract (--append-system-prompt-file), or not at all ----
for (const [agent, role] of [["cc-critic", "critic"], ["cc-senior", "senior"]]) {
  test(`${agent}: --append-system-prompt-file right after --settings carries the ${role}.md body, not its frontmatter; read-only fence footer`, () => {
    const home = tmp();
    const r = runSync(home, agent, `k-${role}`, ["--no-detach"]);
    assert.equal(r.status, 0, r.stderr);
    const argv = r.argv;
    const i = argv.indexOf("--append-system-prompt-file");
    assert.ok(i > 0, JSON.stringify(argv));
    assert.equal(argv[i - 2], "--settings", "placed after --settings, before the variadic --tools");
    assert.ok(i < argv.indexOf("--tools"));
    const file = argv[i + 1];
    assert.equal(file, r.out + ".contract.md", "the contract file sits beside the run's out file, not in the worktree");
    const body = fs.readFileSync(file, "utf8");
    assert.match(body, new RegExp(`^CONTRACT-MARKER-${role}: you are the ${role}\\.`));
    assert.doesNotMatch(body, /FRONTMATTER-MARKER|^---|model: sonnet/m);
    assert.doesNotMatch(argv[1], /Create and edit files/, "a cc reader is not told to create and edit files");
    assert.match(argv[1], /do not create or edit files in it/);
    assert.equal(r.receipt.agent, agent);
  });
}

test("cc reader with no contract file: hop skipped as cc-no-contract (no attempt), the OpenCode fallback runs, receipt records it", () => {
  const home = tmp({ contracts: false });
  const r = runSync(home, "cc-critic", "nc", ["--no-detach", "--fallback", "critic"]);
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.receipt.agent, "critic", "the next chain agent ran");
  assert.equal(r.argv, null, "claude never started");
  const want = `cc-no-contract: ${path.join(home, ".claude", "agents", "critic.md")}`;
  assert.ok(r.receipt.repooled_from.some((h) => h.agent === "cc-critic" && h.skipped && h.reason === want), JSON.stringify(r.receipt.repooled_from));
  assert.ok(r.receipt.notes.includes(want));
  assert.equal(r.receipt.attempts, 1, "the skipped reader used no attempt");
  const saved = JSON.parse(fs.readFileSync(r.out + ".receipt.json", "utf8"));
  assert.ok(saved.notes.includes(want));
  // a frontmatter-only file is no contract either
  writeContracts(home, []);
  fs.writeFileSync(path.join(home, ".claude", "agents", "senior.md"), "---\nname: senior\n---\n\n");
  const s = runSync(home, "cc-senior", "ns", ["--no-detach"]);
  assert.equal(s.status, 6, s.stderr);
  assert.equal(s.argv, null);
  assert.ok(s.receipt.errors.some((e) => /^cc-no-contract: /.test(e)), JSON.stringify(s.receipt.errors));
});

test("cc-worker and cc-worker-strong get no contract flag (writer argv unchanged)", () => {
  const home = tmp();
  for (const agent of ["cc-worker", "cc-worker-strong"]) {
    const r = runSync(home, agent, `w-${agent}`, ["--no-detach"]);
    assert.equal(r.status, 0, r.stderr);
    assert.ok(!r.argv.includes("--append-system-prompt-file"), agent);
    assert.match(r.argv[1], /Create and edit files only under it/, "writers keep the shared fence footer");
  }
});

test("desk-shaped: --role critic on an under pace → cc-critic with its contract, a gate-valid reply → gate APPROVED", () => {
  const home = tmp();
  const now = Date.now();
  const H = 3600 * 1000;
  const snap = { at: new Date(now - 10 * 60 * 1000).toISOString(), source: "app", five_hour: { pct: 0, resets_at: new Date(now + 3 * H).toISOString() }, weekly: { pct: 10, resets_at: new Date(now + 100 * H).toISOString() }, fable: null };
  fs.mkdirSync(orchDir(home), { recursive: true });
  fs.writeFileSync(path.join(orchDir(home), "cc-usage.json"), JSON.stringify(snap) + "\n");
  fs.writeFileSync(path.join(orchDir(home), "cc-usage.jsonl"), JSON.stringify(snap) + "\n");
  const s = setup(home, "desk");
  const reply = "VERDICT: APPROVED\nTESTS: npm test -> 10 pass\nBLAST RADIUS:\n- bin/x.mjs:1 - unchanged\nSENIOR_REVIEW: not-needed - small\n";
  const r = spawnSync(process.execPath, [BIN, "--role", "critic", "--dir", s.dir, "--prompt", s.prompt, "--out", s.out], { env: env(home, { ORCH_NO_PACE: undefined, ORCH_PACE_BIN: undefined, FAKE_CC_TEXT: reply, FAKE_CC_ARGS_FILE: s.argsFile, FAKE_CC_ARGV_OUT: s.argvOut }), encoding: "utf8", timeout: 60000 });
  assert.equal(r.status, 0, r.stderr);
  const receipt = JSON.parse(r.stdout.trim().split("\n").filter((l) => l.startsWith("{")).pop());
  assert.equal(receipt.agent, "cc-critic");
  assert.equal(receipt.cc_pace.state, "under");
  assert.equal(receipt.cc_pace.prepended, true);
  assert.equal(receipt.cc_pace.role, "critic");
  assert.equal(receipt.gate?.effective, "APPROVED", JSON.stringify(receipt.gate));
  const argv = JSON.parse(fs.readFileSync(s.argvOut, "utf8"));
  assert.match(fs.readFileSync(val(argv, "--append-system-prompt-file"), "utf8"), /CONTRACT-MARKER-critic/);
});

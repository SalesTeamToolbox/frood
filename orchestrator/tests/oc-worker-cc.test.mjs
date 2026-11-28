// cc-worker: the headless Claude Code backend of oc-worker (fixtures/fake-claude.mjs stands in for `claude`).
// Every child has a timeout and a fixture life cap; nothing touches the real ~/.config (ORCH_HOME is a temp dir).
import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { summarizeClaude, claudeBin } from "../bin/oc-worker.mjs";
import { classify, ccResetMs, isDown, markDown } from "../bin/pool-health.mjs";
import { installFixtureGuard } from "./fixtures/fixture-guard.mjs";

installFixtureGuard(); // every fixture child carries the suite marker; the guard reaps strays and fails on survivors

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");
const FAKE_CC = path.join(HERE, "fixtures", "fake-claude.mjs");
const FAKE_OC = path.join(HERE, "fixtures", "fake-opencode.mjs");

const CLEAN = [];
const BYSTANDERS = [];
after(() => {
  for (const p of BYSTANDERS) try { process.kill(p, "SIGKILL"); } catch {}
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

const tmp = () => {
  const d = fs.mkdtempSync(path.join(os.tmpdir(), "orch-occ-"));
  CLEAN.push(d);
  return d;
};
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
const slotsOf = (home) => path.join(home, ".config", "orchestrator", "slots");

function env(home, extra = {}) {
  const e = { ...process.env, ORCH_CLAUDE_BIN: FAKE_CC, OPENCODE_BIN: FAKE_OC, ORCH_NO_PROCTREE: "1", ORCH_HOME: home, ORCH_CC_POLL_MS: "50", FAKE_CC_MAX_MS: "60000", FAKE_OC_MAX_MS: "60000", ...extra };
  delete e.WORKER_SLOTS;
  return e;
}
function setup(home, name = "w") {
  const dir = path.join(home, `wt-${name}`);
  fs.mkdirSync(dir, { recursive: true });
  const prompt = path.join(home, `${name}-mandate.md`);
  fs.writeFileSync(prompt, "Implement the ticket.");
  return { dir, prompt, out: path.join(home, "out", `${name}.md`), argsFile: path.join(home, `${name}-args.json`) };
}
function flags(s, extra = []) {
  return ["--agent", "cc-worker", "--dir", s.dir, "--prompt", s.prompt, "--out", s.out, ...extra];
}
function runSync(home, extra = [], extraEnv = {}, name = "w") {
  const s = setup(home, name);
  const r = spawnSync(process.execPath, [BIN, ...flags(s, extra)], { env: env(home, { FAKE_CC_ARGS_FILE: s.argsFile, ...extraEnv }), encoding: "utf8", timeout: 30000 });
  return { ...r, ...s, receipt: r.stdout.trim().startsWith("{") ? JSON.parse(r.stdout.trim()) : null };
}
function runAsync(home, name, extra = [], extraEnv = {}) {
  const s = setup(home, name);
  const child = spawn(process.execPath, [BIN, ...flags(s, extra)], { env: env(home, { FAKE_CC_ARGS_FILE: s.argsFile, ...extraEnv }), stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  child.stdout.on("data", (d) => (stdout += d));
  child.stderr.on("data", () => {});
  const killer = setTimeout(() => child.kill("SIGKILL"), 40000); // every child has a timeout
  const done = new Promise((resolve) => child.on("close", (code) => { clearTimeout(killer); resolve({ code, stdout, endedAt: Date.now(), ...s }); }));
  return { child, done, ...s, started: () => fs.existsSync(s.argsFile) };
}
const waitFor = async (fn, ms = 10000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (fn()) return true; await sleep(50); }
  return false;
};
const dead = (pid) => { try { process.kill(pid, 0); return false; } catch (e) { return e.code !== "EPERM"; } };

test("success: claude argv per the spike, cwd = worktree, receipt model sonnet, tokens/cost/session from the result event", () => {
  const home = tmp();
  const r = runSync(home, ["--report", path.join(home, "report.md")]);
  assert.equal(r.status, 0, r.stderr);
  const { argv, cwd } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.equal(fs.realpathSync(cwd), fs.realpathSync(r.dir));
  assert.equal(argv[0], "-p");
  assert.match(argv[1], /Implement the ticket\.[\s\S]*Write your report to .*report\.md[\s\S]*RESULT: BLOCKED: question/);
  const rest = argv.slice(2);
  const val = (f) => rest[rest.indexOf(f) + 1];
  assert.equal(val("--model"), "sonnet");
  assert.equal(val("--tools"), "Read,Grep,Glob,Edit,Write,Bash");
  assert.ok(rest.includes("--strict-mcp-config"));
  assert.equal(val("--permission-mode"), "acceptEdits");
  assert.equal(val("--allowedTools"), "Bash");
  assert.equal(val("--permission-prompts"), "none");
  assert.equal(val("--output-format"), "stream-json");
  assert.ok(rest.includes("--verbose"));
  assert.ok(!rest.includes("--resume"));
  const rc = r.receipt;
  assert.equal(rc.agent, "cc-worker");
  assert.equal(rc.model, "sonnet");
  assert.equal(rc.session, "cc-ses-fake123");
  assert.equal(rc.exit, 0);
  assert.equal(rc.first_line, "RESULT: DONE");
  assert.equal(rc.verdict, "RESULT: DONE");
  assert.equal(rc.cost, 0.0123);
  assert.deepEqual(rc.tokens, { input: 130, output: 20, reasoning: 0, cache_read: 1000 });
  assert.match(fs.readFileSync(r.out, "utf8"), /^RESULT: DONE\nfake claude worked in /);
  assert.ok(fs.existsSync(r.out + ".events.jsonl"));
  assert.deepEqual(JSON.parse(fs.readFileSync(r.out + ".receipt.json", "utf8")).session, "cc-ses-fake123");
  assert.deepEqual(fs.readdirSync(slotsOf(home)), ["clear-state.json"], "slots released");
});

test("receipt has the same field set as an OpenCode worker run", () => {
  const home = tmp();
  const cc = runSync(home, [], {}, "cc").receipt;
  const s = setup(home, "oc");
  const oc = JSON.parse(spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", s.dir, "--prompt", s.prompt, "--out", s.out], { env: env(home), encoding: "utf8", timeout: 30000 }).stdout.trim());
  assert.deepEqual(Object.keys(cc).sort(), Object.keys(oc).sort());
});

test("--session maps to --resume", () => {
  const home = tmp();
  const r = runSync(home, ["--session", "cc-ses-round1"]);
  assert.equal(r.status, 0, r.stderr);
  const { argv } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.equal(argv[argv.indexOf("--resume") + 1], "cc-ses-round1");
  assert.equal(r.receipt.session, "cc-ses-round1");
});

test("--model overrides the model flag and the receipt", () => {
  const home = tmp();
  const r = runSync(home, ["--model", "opus"]);
  const { argv } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.equal(argv[argv.indexOf("--model") + 1], "opus");
  assert.equal(r.receipt.model, "opus");
});

test("usage limit: classified quota, cc-worker marked down until the reset, run re-pools to the next --fallback", () => {
  const home = tmp();
  const resetS = Math.floor(Date.now() / 1000) + 3 * 3600;
  const r = runSync(home, ["--fallback", "worker"], { FAKE_CC_MODE: "usage-limit", FAKE_CC_RESET_S: String(resetS) });
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.receipt.agent, "worker", "the fallback agent ran");
  assert.equal(r.receipt.repooled_from.length, 1);
  assert.equal(r.receipt.repooled_from[0].agent, "cc-worker");
  assert.match(r.receipt.repooled_from[0].error, /usage limit reached/);
  const health = JSON.parse(fs.readFileSync(path.join(home, ".config", "orchestrator", "pool-health.json"), "utf8"));
  assert.equal(health["cc-worker"].reason, "quota");
  assert.ok(Math.abs(Date.parse(health["cc-worker"].until) - resetS * 1000) < 5000, "down until the reset named in the message");
  // the next run skips the known-down cc-worker without calling it
  fs.rmSync(r.argsFile);
  const again = runSync(home, ["--fallback", "worker"], {}, "again");
  assert.equal(again.receipt.agent, "worker");
  assert.equal(again.receipt.repooled_from[0].skipped, true);
  assert.match(again.receipt.repooled_from[0].reason, /^quota until /);
  assert.ok(!fs.existsSync(again.argsFile), "claude was never spawned for a down pool");
});

test("a rate limit (429) re-pools as rate-limit; with no fallback the failure is the result", () => {
  const home = tmp();
  const r = runSync(home, ["--fallback", "worker"], { FAKE_CC_MODE: "rate-limit" });
  assert.equal(r.receipt.agent, "worker");
  const health = JSON.parse(fs.readFileSync(path.join(home, ".config", "orchestrator", "pool-health.json"), "utf8"));
  assert.equal(health["cc-worker"].reason, "rate-limit");
  const solo = runSync(tmp(), [], { FAKE_CC_MODE: "usage-limit" });
  assert.equal(solo.status, 5);
  assert.equal(solo.receipt.exit, 1);
  assert.match(solo.receipt.errors.join("\n"), /usage limit reached/);
  assert.equal(solo.receipt.first_line, "");
});

test("every cc-worker pool known-down and no fallback: exit 6, claude never spawned", () => {
  const home = tmp();
  fs.mkdirSync(path.join(home, ".config", "orchestrator"), { recursive: true });
  fs.writeFileSync(path.join(home, ".config", "orchestrator", "pool-health.json"), JSON.stringify({ "cc-worker": { reason: "quota", since: new Date().toISOString(), until: new Date(Date.now() + 3600e3).toISOString(), detail: "" } }));
  const r = runSync(home);
  assert.equal(r.status, 6);
  assert.ok(!fs.existsSync(r.argsFile));
});

test("slot cap: a second concurrent cc-worker waits (cc.max_workers defaults to 1), then runs after the first releases", async () => {
  const home = tmp();
  const slow = { FAKE_CC_MODE: "slow", FAKE_CC_DELAY: "1500" };
  const a = runAsync(home, "a", [], slow);
  assert.ok(await waitFor(a.started), "a started");
  assert.ok(fs.existsSync(path.join(slotsOf(home), "provider-cc-1")), "a holds provider-cc-1");
  const b = runAsync(home, "b", [], slow);
  await sleep(700);
  assert.ok(!b.started(), "b waits on the cc slot while a runs");
  const [ra, rb] = await Promise.all([a.done, b.done]);
  assert.equal(ra.code, 0);
  assert.equal(rb.code, 0, "a waiting launch never fails");
  const bStart = fs.statSync(b.argsFile).mtimeMs;
  assert.ok(bStart + 50 >= ra.endedAt - 400, "b spawned only after a finished");
  assert.ok(bStart > fs.statSync(a.argsFile).mtimeMs + 1000, "b started at least a's hold time after a");
  assert.deepEqual(fs.readdirSync(slotsOf(home)).filter((n) => n.startsWith("provider-cc-")), []);
});

test("slot cap: cc.max_workers=2 from usage-limits.json lets two overlap, a third waits; a non-cc run never waits", async () => {
  const home = tmp();
  fs.mkdirSync(path.join(home, ".config", "orchestrator"), { recursive: true });
  fs.writeFileSync(path.join(home, ".config", "orchestrator", "usage-limits.json"), JSON.stringify({ cc: { max_workers: 2 } }));
  const slow = { FAKE_CC_MODE: "slow", FAKE_CC_DELAY: "4000" };
  const a = runAsync(home, "a", [], slow);
  const b = runAsync(home, "b", [], slow);
  assert.ok(await waitFor(() => a.started() && b.started()), "both run at once under max_workers=2");
  const c = runAsync(home, "c", [], slow);
  await sleep(500);
  assert.ok(!c.started(), "a third waits");
  const s = setup(home, "oc");
  const oc = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", s.dir, "--prompt", s.prompt, "--out", s.out], { env: env(home), encoding: "utf8", timeout: 30000 });
  assert.equal(oc.status, 0, "an OpenCode run does not take a cc slot");
  for (const r of await Promise.all([a.done, b.done, c.done])) assert.equal(r.code, 0);
});

test("timeout kills only its own claude pid", async () => {
  const home = tmp();
  const bystander = spawn(process.execPath, ["-e", "setTimeout(()=>{},30000)"], { stdio: "ignore", env: process.env });
  BYSTANDERS.push(bystander.pid);
  const r = runSync(home, ["--timeout-min", "0.04", "--idle-min", "0", "--grace-min", "0", "--resume", "0"], { FAKE_CC_MODE: "hang" });
  assert.equal(r.status, 4, r.stderr);
  assert.equal(r.receipt.exit, "timeout");
  const { pid } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.ok(dead(pid), "the timed-out claude is gone");
  assert.ok(!dead(bystander.pid), "an unrelated process is untouched");
  bystander.kill("SIGKILL");
  assert.deepEqual(fs.readdirSync(slotsOf(home)), ["clear-state.json"], "slots released after a timeout");
});

test("SIGTERM to an in-process (--no-detach) oc-worker ends the claude process and releases the cc slot (exit 143, receipt killed)", async () => {
  const home = tmp();
  const a = runAsync(home, "a", ["--no-detach"], { FAKE_CC_MODE: "hang" });
  assert.ok(await waitFor(a.started), "claude started");
  const { pid } = JSON.parse(fs.readFileSync(a.argsFile, "utf8"));
  a.child.kill("SIGTERM");
  const r = await a.done;
  assert.equal(r.code, 143);
  assert.equal(JSON.parse(fs.readFileSync(a.out + ".receipt.json", "utf8")).exit, "killed");
  assert.ok(await waitFor(() => dead(pid), 7000), "claude is gone");
  assert.deepEqual(fs.readdirSync(slotsOf(home)), ["clear-state.json"]);
});

test("hook-free: --settings disableAllHooks in the claude argv and PEER_WAKE_MAX_MIN=0 even when the parent sets 30; OpenCode argv has no --settings", () => {
  const home = tmp();
  const r = runSync(home, [], { PEER_WAKE_MAX_MIN: "30" });
  assert.equal(r.status, 0, r.stderr);
  const { argv, peerWakeMaxMin } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.equal(argv[0], "-p", "the prompt stays right after -p");
  const settings = argv[argv.indexOf("--settings") + 1];
  assert.ok(argv.includes("--settings"));
  assert.equal(JSON.parse(settings).disableAllHooks, true);
  assert.ok(!argv.includes("--bare") && !argv.includes("--safe-mode"));
  assert.equal(peerWakeMaxMin, "0");
  const s = setup(home, "oc");
  const ocArgs = path.join(home, "oc-args.json");
  const oc = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", s.dir, "--prompt", s.prompt, "--out", s.out], { env: env(home, { FAKE_OC_ARGS_FILE: ocArgs, PEER_WAKE_MAX_MIN: "30" }), encoding: "utf8", timeout: 30000 });
  assert.equal(oc.status, 0, oc.stderr);
  assert.ok(!JSON.parse(fs.readFileSync(ocArgs, "utf8")).argv.includes("--settings"));
});

test("foreground: a default (detached) cc-worker run exits 0 with the receipt on stdout; the fake's parent is the detached child", () => {
  const home = tmp();
  const r = runSync(home);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stderr, /oc-worker: detached run pid \d+, log .*\.detached\.log/);
  assert.equal(r.receipt.exit, 0);
  assert.equal(r.receipt.first_line, "RESULT: DONE");
  assert.deepEqual(JSON.parse(fs.readFileSync(r.out + ".receipt.json", "utf8")).first_line, "RESULT: DONE");
  const childPid = Number(r.stderr.match(/detached run pid (\d+)/)[1]);
  const { ppid } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.equal(ppid, childPid, "claude ran under the detached oc-worker");
  assert.ok(fs.existsSync(r.out + ".detached.log"));
});

test("--no-detach runs in process: the fake's parent pid is the launcher's pid, no detached log", () => {
  const home = tmp();
  const s = setup(home);
  const child = spawnSync(process.execPath, [BIN, ...flags(s, ["--no-detach"])], { env: env(home, { FAKE_CC_ARGS_FILE: s.argsFile }), encoding: "utf8", timeout: 30000 });
  assert.equal(child.status, 0, child.stderr);
  assert.equal(JSON.parse(child.stdout.trim()).first_line, "RESULT: DONE");
  assert.doesNotMatch(child.stderr, /detached run pid/);
  assert.equal(JSON.parse(fs.readFileSync(s.argsFile, "utf8")).ppid, child.pid);
  assert.ok(!fs.existsSync(s.out + ".detached.log"));
});

test("survival: SIGTERM to the launcher exits it 143; the detached run finishes and writes its receipt (exit 0); nothing is left", async () => {
  const home = tmp();
  const s = setup(home, "surv");
  const launcher = spawn(process.execPath, [BIN, ...flags(s)], { env: env(home, { FAKE_CC_ARGS_FILE: s.argsFile, FAKE_CC_MODE: "slow", FAKE_CC_DELAY: "2500" }), stdio: ["ignore", "pipe", "pipe"] });
  let stderr = "";
  launcher.stderr.on("data", (d) => (stderr += d));
  const killer = setTimeout(() => launcher.kill("SIGKILL"), 40000);
  const exited = new Promise((resolve) => launcher.on("exit", (code, signal) => { clearTimeout(killer); resolve({ code, signal }); }));
  let childPid = null;
  try {
    assert.ok(await waitFor(() => fs.existsSync(s.argsFile)), "fake claude started");
    childPid = Number(stderr.match(/detached run pid (\d+)/)?.[1]) || null;
    assert.ok(childPid, `launcher named its detached child: ${stderr}`);
    const { pid: claudePid } = JSON.parse(fs.readFileSync(s.argsFile, "utf8"));
    process.kill(launcher.pid, "SIGTERM");
    const { code } = await exited;
    assert.equal(code, 143);
    assert.ok(await waitFor(() => fs.existsSync(s.out + ".receipt.json"), 20000), "the run wrote its receipt");
    const rc = JSON.parse(fs.readFileSync(s.out + ".receipt.json", "utf8"));
    assert.equal(rc.exit, 0);
    assert.equal(rc.first_line, "RESULT: DONE");
    assert.ok(await waitFor(() => dead(childPid) && dead(claudePid), 10000), "no process of the run remains");
    assert.deepEqual(fs.readdirSync(slotsOf(home)), ["clear-state.json"], "slots released");
  } finally {
    if (childPid && !dead(childPid)) try { process.kill(childPid, "SIGKILL"); } catch {}
  }
});

test("tokens: no result event (killed by timeout) falls back to assistant usage, each message id once", () => {
  const home = tmp();
  const r = runSync(home, ["--timeout-min", "0.03", "--idle-min", "0", "--grace-min", "0", "--resume", "0"], { FAKE_CC_MODE: "usage-no-result" });
  assert.equal(r.status, 4, r.stderr);
  assert.equal(r.receipt.exit, "timeout");
  assert.deepEqual(r.receipt.tokens, { input: 24, output: 12, reasoning: 0, cache_read: 200 });
});

test("summarizeClaude: assistant usage is only a fallback; a result event's usage wins", () => {
  const u = { input_tokens: 1, output_tokens: 1 };
  const lines = [
    JSON.stringify({ type: "assistant", message: { id: "m1", content: [], usage: u } }),
    JSON.stringify({ type: "assistant", message: { id: "m1", content: [], usage: u } }),
  ];
  assert.deepEqual(summarizeClaude(lines).tokens, { input: 1, output: 1, reasoning: 0, cache_read: 0 });
  const withResult = [...lines, JSON.stringify({ type: "result", is_error: false, result: "x", usage: { input_tokens: 50, output_tokens: 9 } })];
  assert.deepEqual(summarizeClaude(withResult).tokens, { input: 50, output: 9, reasoning: 0, cache_read: 0 });
});

test("summarizeClaude: result event folds session, text, tokens, cost; an is_error result is an error, not a final message", () => {
  const ok = summarizeClaude([
    "not json",
    JSON.stringify({ type: "system", subtype: "init", session_id: "s1" }),
    JSON.stringify({ type: "assistant", session_id: "s1", message: { content: [{ type: "text", text: "working" }, { type: "tool_use", name: "Edit" }] } }),
    JSON.stringify({ type: "result", session_id: "s1", is_error: false, result: "RESULT: DONE", total_cost_usd: 0.5, usage: { input_tokens: 1, output_tokens: 2, cache_creation_input_tokens: 3, cache_read_input_tokens: 4 } }),
  ]);
  assert.equal(ok.session, "s1");
  assert.equal(ok.final, "RESULT: DONE");
  assert.equal(ok.all, "working");
  assert.deepEqual(ok.tokens, { input: 4, output: 2, reasoning: 0, cache_read: 4 });
  assert.equal(ok.cost, 0.5);
  const bad = summarizeClaude([
    JSON.stringify({ type: "assistant", session_id: "s2", message: { content: [{ type: "text", text: "limit hit" }] } }),
    JSON.stringify({ type: "result", session_id: "s2", is_error: true, result: "limit hit" }),
  ]);
  assert.equal(bad.final, "");
  assert.equal(bad.all, "", "the limit message is not the agent's work");
  assert.deepEqual(bad.errors, ["limit hit"]);
});

test("claudeBin: ORCH_CLAUDE_BIN .mjs runs under node; unset means `claude` on PATH", () => {
  const saved = process.env.ORCH_CLAUDE_BIN;
  try {
    process.env.ORCH_CLAUDE_BIN = "/x/fake.mjs";
    assert.deepEqual(claudeBin(), { cmd: process.execPath, pre: ["/x/fake.mjs"], shell: false });
    delete process.env.ORCH_CLAUDE_BIN;
    assert.deepEqual(claudeBin(), { cmd: "claude", shell: false });
  } finally {
    if (saved === undefined) delete process.env.ORCH_CLAUDE_BIN;
    else process.env.ORCH_CLAUDE_BIN = saved;
  }
});

test("pool-health: claude limit texts classify; the quota outage runs to the named reset, else 5 h; other pools unchanged", () => {
  const now = Date.now();
  const epoch = Math.floor(now / 1000) + 3600;
  assert.equal(classify([`Claude AI usage limit reached|${epoch}`], "cc-worker").reason, "quota");
  assert.ok(Math.abs(ccResetMs(`limit reached|${epoch}`, now) - 3600e3) < 1500);
  assert.ok(Math.abs(ccResetMs("limit resets at 2099-01-01T00:00:00Z", now) - (Date.parse("2099-01-01T00:00:00Z") - now)) < 5);
  const noTime = classify(["5-hour limit reached"], "cc-worker");
  assert.equal(noTime.reason, "quota");
  assert.equal(noTime.ms, 5 * 3600e3);
  assert.equal(classify(["You've hit your limit"], "cc-worker").ms, 5 * 3600e3);
  assert.equal(classify(["API Error: 429 rate_limit_error"], "cc-worker").reason, "rate-limit");
  assert.equal(classify(["API Error: overloaded_error"], "cc-worker").reason, "provider-error");
  // unchanged elsewhere: a generic provider limit is still a 1 h quota scoped by its own rules
  assert.deepEqual(classify(["usage limit reached"], "opencode-go/kimi").scope, "provider");
  assert.equal(classify(["usage limit reached"], "opencode-go/kimi").ms, 3600e3);
});

test("pool-health: markDown records cc-worker and isDown reads it", () => {
  const home = tmp();
  const saved = process.env.ORCH_HOME;
  process.env.ORCH_HOME = home;
  try {
    markDown("cc-worker", { reason: "quota", ms: 5 * 3600e3, detail: "x" });
    const d = isDown("cc-worker");
    assert.equal(d.reason, "quota");
    assert.equal(isDown("opencode-go/kimi"), null);
  } finally {
    if (saved === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = saved;
  }
});

import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { summarize, acquireSlot, slotDir, prio, args, FOOTER, sleepGapMs, sleepExtensionMs, resumableReason } from "../bin/oc-worker.mjs";
import { workerOutcome } from "../bin/outcome.mjs";
import { CHAINS } from "../bin/chains.mjs";
import { installFixtureGuard, fixtureChildren, reapFixtureChildren } from "./fixtures/fixture-guard.mjs";

// Every fixture child carries this process's suite marker; the guard reaps strays after the suite.
installFixtureGuard();

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");
const BOARD = path.join(HERE, "..", "bin", "board.mjs");
const FAKE = path.join(HERE, "fixtures", "fake-opencode.mjs");
const BOARD_FIX = path.join(HERE, "fixtures", "board");

const CLEAN = [];
const SAVED_NO_INHIBIT = process.env.ORCH_NO_INHIBIT;
const SAVED_INHIBIT_BIN = process.env.ORCH_INHIBIT_BIN;
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
  if (SAVED_NO_INHIBIT === undefined) delete process.env.ORCH_NO_INHIBIT;
  else process.env.ORCH_NO_INHIBIT = SAVED_NO_INHIBIT;
  if (SAVED_INHIBIT_BIN === undefined) delete process.env.ORCH_INHIBIT_BIN;
  else process.env.ORCH_INHIBIT_BIN = SAVED_INHIBIT_BIN;
});

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orch-ocw-"));
}
function run(extraEnv, ...flags) {
  const dir = tmp();
  CLEAN.push(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", path.join(dir, "out", "findings-r1.md"), ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, ...extraEnv },
    encoding: "utf8",
    timeout: 30000,
  });
  return { ...r, dir, argsFile };
}

// The worker env is config, not code: <ORCH_HOME>/.config/orchestrator/worker-env.json.
function runWithWorkerEnv(config, extraEnv = {}) {
  const dir = tmp();
  CLEAN.push(dir);
  if (config) {
    const cfgDir = path.join(dir, ".config", "orchestrator");
    fs.mkdirSync(cfgDir, { recursive: true });
    fs.writeFileSync(path.join(cfgDir, "worker-env.json"), typeof config === "string" ? config : JSON.stringify(config));
  }
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const argsFile = path.join(dir, "args.json");
  const env = { ...process.env };
  delete env.ORCH_TEST_VAR; // the host must not leak into the "env unchanged" case
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", path.join(dir, "out", "findings-r1.md")], {
    env: { ...env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, ...extraEnv },
    encoding: "utf8",
  });
  return { ...r, dir, argsFile };
}

// --------------------------------------------------------------------------- sleep inhibitor tripwire
// Every oc-worker child inherits ORCH_NO_INHIBIT=1 and an ORCH_INHIBIT_BIN that points at this
// tripwire script, so no test can start the real systemd-inhibit. The six inhibitor tests opt back
// in explicitly (ORCH_NO_INHIBIT: "0" plus their own fake ORCH_INHIBIT_BIN); every other test keeps
// ORCH_NO_INHIBIT=1 and the inhibitor is never spawned. If the tripwire file exists after the suite,
// some non-inhibitor test started an inhibitor.
const TRIPWIRE_DIR = tmp();
CLEAN.push(TRIPWIRE_DIR);
const TRIPWIRE_FILE = path.join(TRIPWIRE_DIR, "inhibit-tripwire.log");
const TRIPWIRE_BIN = path.join(TRIPWIRE_DIR, "tripwire-inhibit.mjs");
fs.writeFileSync(
  TRIPWIRE_BIN,
  `#!/usr/bin/env node\n` +
  `import fs from "node:fs";\n` +
  `const file = ${JSON.stringify(TRIPWIRE_FILE)};\n` +
  `try { fs.appendFileSync(file, new Date().toISOString() + " inhibitor spawned: " + process.argv.slice(2).join(" ") + "\\n"); } catch {}\n` +
  `process.exit(0);\n`,
);
fs.chmodSync(TRIPWIRE_BIN, 0o755);

process.env.ORCH_NO_INHIBIT = "1";
process.env.ORCH_INHIBIT_BIN = TRIPWIRE_BIN;

test("worker env: a {state} value is created as a dir and passed; explicit env wins; no file changes nothing", () => {
  const r = runWithWorkerEnv({ ORCH_TEST_VAR: "{state}/ws", ORCH_TEST_PLAIN: "x" });
  assert.equal(r.status, 0, r.stderr);
  const { testVar } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.equal(testVar, path.join(r.dir, ".config", "orchestrator", "ws"));
  assert.ok(fs.existsSync(testVar), "a {state}/ value is created as a directory");

  const own = runWithWorkerEnv({ ORCH_TEST_VAR: "{state}/ws" }, { ORCH_TEST_VAR: path.join(os.tmpdir(), "mine") });
  assert.equal(JSON.parse(fs.readFileSync(own.argsFile, "utf8")).testVar, path.join(os.tmpdir(), "mine"), "explicit value wins");

  const none = runWithWorkerEnv(null);
  assert.equal(JSON.parse(fs.readFileSync(none.argsFile, "utf8")).testVar, null, "no config: env unchanged");
  assert.equal(JSON.parse(fs.readFileSync(runWithWorkerEnv("{not json").argsFile, "utf8")).testVar, null, "invalid config: env unchanged");
});

test("summarize folds the real opencode json stream", () => {
  const lines = fs.readFileSync(path.join(HERE, "fixtures", "opencode-run.jsonl"), "utf8").split("\n").filter(Boolean);
  const s = summarize(lines);
  assert.match(s.session, /^ses_/);
  assert.equal(s.final, "PONG");
  assert.equal(s.tokens.input, 44);
});

test("happy path: saves final message, receipt, events; passes agent, cwd, footer; no shell", () => {
  const r = run({});
  assert.equal(r.status, 0, r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.session, "ses_fake123");
  assert.equal(receipt.first_line, "VERDICT: APPROVED");
  assert.equal(receipt.cost, 0.0012);
  const out = fs.readFileSync(path.join(r.dir, "out", "findings-r1.md"), "utf8");
  assert.match(out, /^VERDICT: APPROVED\nagent=critic\n1\. \[minor\]/);
  assert.ok(fs.existsSync(path.join(r.dir, "out", "findings-r1.md.receipt.json")));
  assert.ok(fs.existsSync(path.join(r.dir, "out", "findings-r1.md.events.jsonl")));
  const { argv, cwd } = JSON.parse(fs.readFileSync(r.argsFile, "utf8"));
  assert.equal(fs.realpathSync(cwd), fs.realpathSync(r.dir));
  for (const f of ["run", "--standalone", "--format", "json", "--auto", "--agent", "critic"]) assert.ok(argv.includes(f), f);
  assert.match(argv[argv.length - 1], /Review the diff\.[\s\S]*RESULT: BLOCKED: question/);
});

test("--session resumes the same session (revision rounds)", () => {
  const r = run({}, "--session", "ses_round1");
  assert.equal(JSON.parse(r.stdout.trim()).session, "ses_round1");
});

test("timeout kills the run and exits 4", () => {
  const r = run({ FAKE_OC_MODE: "hang" }, "--timeout-min", "0.02");
  assert.equal(r.status, 4);
  assert.equal(JSON.parse(r.stdout.trim()).exit, "timeout");
});

test("fence: attempted-only escape (no completed write) leaves exit and status unchanged, not 5", () => {
  const dir = tmp();
  CLEAN.push(dir);
  // outside every allowed root (/tmp is allowed, homedir is not)
  const outside = fs.mkdtempSync(path.join(os.homedir(), ".wtf-oc-escape-"));
  CLEAN.push(outside);
  const target = path.join(outside, "attempted.txt");
  fs.writeFileSync(target, "original\n");
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const out = path.join(dir, "out", "findings-r1.md");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "escape-edit-attempted", FAKE_OC_TARGET: target },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  // `status` is stripped from the stdout receipt; it drives process.exit(code)
  // no completed write -> exit unchanged (clean finish), exit code not 5
  assert.equal(receipt.exit, 0, "exit unchanged on attempted-only escape: " + r.stdout);
  assert.equal(r.status, 0, "exit code not 5 on attempted-only escape: " + r.stdout);
  // path recorded as escaped
  assert.ok(receipt.escaped, "receipt has escaped field: " + r.stdout);
  assert.ok(receipt.escaped.paths.includes(target), "escaped.paths lists the target: " + JSON.stringify(receipt.escaped.paths));
  // target file untouched (attempted only, nothing restored)
  assert.equal(fs.readFileSync(target, "utf8"), "original\n", "target untouched by attempted escape");
});

test("opencode failure exits 5 with stderr in the receipt; no text exits 3", () => {
  const f = run({ FAKE_OC_MODE: "fail" });
  assert.equal(f.status, 5);
  assert.match(JSON.parse(f.stdout.trim()).errors.join(" "), /boom/);
  assert.equal(run({ FAKE_OC_MODE: "silent" }).status, 3);
});

test("slots: two holders, third waits until one releases; dead owner is reclaimed", async () => {
  process.env.ORCH_HOME = tmp();
  const r1 = await acquireSlot(2, { pollMs: 20 });
  const r2 = await acquireSlot(2, { pollMs: 20 });
  await assert.rejects(acquireSlot(2, { pollMs: 20, deadline: Date.now() + 150 }), /no free worker slot/);
  r1.release();
  const r3 = await acquireSlot(2, { pollMs: 20, deadline: Date.now() + 1000 });
  r2.release();
  r3.release();
  // dead owner
  const d = path.join(slotDir(), "slot-1");
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, "owner"), JSON.stringify({ pid: 999999, since: "x" }));
  fs.mkdirSync(path.join(slotDir(), "slot-2"), { recursive: true });
  fs.writeFileSync(path.join(slotDir(), "slot-2", "owner"), JSON.stringify({ pid: process.pid, since: "x" }));
  const r4 = await acquireSlot(2, { pollMs: 20, deadline: Date.now() + 500 });
  r4.release();
  delete process.env.ORCH_HOME;
});

test("never spawns through a shell (Mandate text travels in argv)", async () => {
  const src = fs.readFileSync(BIN, "utf8");
  assert.doesNotMatch(src, /shell:\s*true|shell:\s*process\.platform/);
});

function help(...flags) {
  const dir = tmp();
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  return { ...r, dir, argsFile };
}

// The header comment block ends with the "Exit: ..." lines, so this assertion fails if usage() truncates.
const LAST_HEADER_LINE = /Exit: 0 finished, 3 no final text, 4 timeout, 5 opencode error, 6 every pool in the chain known-down, 7 board\nattach refused \(--ticket\), 8 model not allowed by provider policy[^\n]*\nand not on the allowlist\), 10 stale or dirty tree \(fresh --stream worker refused before queued\/spawn\)\./;

test("--help prints usage and exits 0 without launching anything", () => {
  const r = help("--help");
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /--agent/);
  assert.match(r.stdout, /WORKER_SLOTS/);
  assert.match(r.stdout, LAST_HEADER_LINE, "the whole header must be emitted, including its last line");
  assert.ok(!fs.existsSync(r.argsFile), "opencode must not be spawned for --help");
});

test("-h is the same as --help", () => {
  const r = help("-h");
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /--agent/);
  assert.match(r.stdout, /WORKER_SLOTS/);
  assert.match(r.stdout, LAST_HEADER_LINE);
  assert.ok(!fs.existsSync(r.argsFile));
});

test("--help wins over invalid arguments", () => {
  assert.equal(help("--help", "--bogus").status, 0);
  assert.equal(help("--not-a-flag", "-h").status, 0);
  const r = help("--help");
  // help text documents the `oc-worker: waiting for ...` stderr format; error lines start at column 0.
  assert.doesNotMatch(r.stdout, /^oc-worker: /m);
});

test("--help as another flag's value still prints usage and exits 0", () => {
  const r = help("--title", "--help");
  assert.equal(r.status, 0, r.stderr);
  assert.equal(r.stderr, "");
  assert.match(r.stdout, /--agent/);
  assert.match(r.stdout, /WORKER_SLOTS/);
  assert.match(r.stdout, LAST_HEADER_LINE);
  assert.ok(!fs.existsSync(r.argsFile), "help must be detected before --title consumes the value");
});

test("invalid flags still exit 2 with the existing messages", () => {
  const unknown = help("--nope", "--agent", "worker");
  assert.equal(unknown.status, 2);
  assert.match(unknown.stderr, /oc-worker: unknown flag --nope/);
  const missing = help("--agent", "worker");
  assert.equal(missing.status, 2);
  assert.match(missing.stderr, /oc-worker: --dir is required/);
});

test("--fallback re-pools on a quota error and records the hop", () => {
  const r = run({ FAKE_OC_MODE: "quota-critic" }, "--fallback", "critic-go,scout");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.agent, "critic-go");
  assert.equal(receipt.repooled_from.length, 1);
  assert.match(receipt.repooled_from[0].error, /limit/);
  const onDisk = JSON.parse(fs.readFileSync(path.join(r.dir, "out", "findings-r1.md.receipt.json"), "utf8"));
  assert.equal(onDisk.repooled_from[0].agent, "critic");
});

test("--fallback does not re-pool ordinary failures; stops after the list", () => {
  assert.equal(run({ FAKE_OC_MODE: "fail" }, "--fallback", "scout").status, 5);
  const r = run({ FAKE_OC_MODE: "quota-critic,a,b" }, "--fallback", "a,b");
  assert.equal(r.status, 5);
  assert.equal(JSON.parse(r.stdout.trim()).repooled_from.length, 2);
});

// --role: single chain source from bin/chains.mjs
function spawnRole(dir, ...flags) {
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const argsFile = path.join(dir, "args.json");
  const out = path.join(dir, "out", "worker-r1.md");
  const r = spawnSync(process.execPath, [BIN, "--dir", dir, "--prompt", prompt, "--out", out, ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  return { ...r, dir, argsFile, out };
}

function receiptOf(r) {
  return JSON.parse(r.stdout.trim());
}

test("--role worker expands to worker-nvidia first (one chain source)", () => {
  const dir = tmp();
  const r = spawnRole(dir, "--role", "worker");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(receiptOf(r).agent, "worker-nvidia");
  // --role reads CHAINS directly, so this literal pin is what guards the expanded order (the fake
  // opencode harness does not record the --fallback tail).
  assert.deepEqual(CHAINS.worker, ["worker-nvidia", "worker", "worker-free"]);
});

test("--role worker-strong expands to worker-strong first (unchanged chain)", () => {
  const dir = tmp();
  const r = spawnRole(dir, "--role", "worker-strong");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(receiptOf(r).agent, "worker-strong");
  assert.deepEqual(CHAINS["worker-strong"], ["worker-strong", "worker-nvidia", "worker-free"]);
});

test("--role with --agent is refused (usage exit 2)", () => {
  const dir = tmp();
  const r = spawnRole(dir, "--role", "worker", "--agent", "worker");
  assert.equal(r.status, 2);
  assert.match(r.stderr, /oc-worker: --role may not be combined with --agent or --fallback/);
});

test("--role with --fallback is refused (usage exit 2)", () => {
  const dir = tmp();
  const r = spawnRole(dir, "--role", "worker", "--fallback", "worker");
  assert.equal(r.status, 2);
  assert.match(r.stderr, /oc-worker: --role may not be combined with --agent or --fallback/);
});

test("unknown role is refused (usage exit 2)", () => {
  const dir = tmp();
  const r = spawnRole(dir, "--role", "nope");
  assert.equal(r.status, 2);
  assert.match(r.stderr, /oc-worker: unknown role/);
});

test("two prior worker-nvidia stalled receipts drop worker-nvidia; one does not", () => {
  const dir = tmp();
  const outDir = path.join(dir, "out");
  fs.mkdirSync(outDir, { recursive: true });
  // One stalled receipt: worker-nvidia still used
  fs.writeFileSync(path.join(outDir, "worker-r1.md.receipt.json"), JSON.stringify({ agent: "worker-nvidia", exit: "stalled" }));
  const one = spawnRole(dir, "--role", "worker", "--out", path.join(outDir, "worker-r2.md"));
  assert.equal(receiptOf(one).agent, "worker-nvidia", "one stall does not drop worker-nvidia");

  // A timeout receipt also counts as a drop
  fs.writeFileSync(path.join(outDir, "worker-r2.md.receipt.json"), JSON.stringify({ agent: "worker-nvidia", exit: "timeout" }));
  const two = spawnRole(dir, "--role", "worker", "--out", path.join(outDir, "worker-r3.md"));
  assert.equal(receiptOf(two).agent, "worker", "two stalls drop worker-nvidia, fall to worker");
});


test("timeout keeps partial output, clearly marked BLOCKED", () => {
  const r = run({ FAKE_OC_MODE: "hang-after-text" }, "--timeout-min", "0.03", "--grace-min", "0");
  assert.equal(r.status, 4);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.partial, true);
  const out = fs.readFileSync(path.join(r.dir, "out", "findings-r1.md"), "utf8");
  assert.match(out, /^RESULT: BLOCKED: timeout/);
  assert.match(out, /found candidate A at x\.py:12/);
});

test("sessionTree prices a session and its subagents from a read-only db", async () => {
  const { sessionTree } = await import("../bin/oc-worker.mjs");
  const { DatabaseSync } = await import("node:sqlite");
  const dbPath = path.join(tmp(), "oc.db");
  const db = new DatabaseSync(dbPath);
  db.exec("CREATE TABLE session_v2 (id TEXT, parent_id TEXT, agent TEXT, model TEXT, cost REAL, tokens_input INT, tokens_output INT)");
  const ins = db.prepare("INSERT INTO session_v2 VALUES (?,?,?,?,?,?,?)");
  ins.run("ses_root", null, "orchestrator", JSON.stringify({ providerID: "commandcode", id: "meta/muse" }), 0.02, 10, 1);
  ins.run("ses_w", "ses_root", "worker-burst", JSON.stringify({ providerID: "commandcode", id: "deepseek" }), 0.015, 5, 1);
  ins.run("ses_c", "ses_root", "critic", JSON.stringify({ providerID: "commandcode", id: "claude-haiku-5-5" }), 0.01, 5, 1);
  db.close();
  const before = fs.readFileSync(dbPath);
  const t = sessionTree("ses_root", dbPath);
  assert.equal(t.total_cost, 0.045);
  assert.deepEqual(t.sessions.map((s) => `${s.agent}@${s.model}`), ["orchestrator@commandcode/meta/muse", "worker-burst@commandcode/deepseek", "critic@commandcode/claude-haiku-5-5"]);
  assert.ok(Buffer.compare(before, fs.readFileSync(dbPath)) === 0, "db must not be written");
  assert.equal(sessionTree("ses_missing", dbPath), null);
  assert.equal(sessionTree("x", path.join(tmp(), "nope.db")), null);
});

test("statusLine finds RESULT/VERDICT anywhere; receipt.verdict falls back to --report", async () => {
  const { statusLine } = await import("../bin/oc-worker.mjs");
  assert.equal(statusLine("Report is written.\n\nRESULT: DONE\nmore"), "RESULT: DONE");
  assert.equal(statusLine("VERDICT: APPROVED\n1. x"), "VERDICT: APPROVED");
  assert.equal(statusLine("nothing here"), "");
  const r = run({ FAKE_OC_MODE: "silent" });
  assert.equal(JSON.parse(r.stdout.trim()).verdict, null);
});

test("critic receipts carry the mechanical gate (fake critic output has no BLAST RADIUS -> INVALID)", () => {
  const r = run({});
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.gate.critic, "APPROVED");
  assert.equal(receipt.gate.effective, "INVALID");
});

test("a running oc-worker registers itself for the live dashboard and unregisters when done", () => {
  const r = run({ FAKE_OC_MODE: "hang" }, "--timeout-min", "0.02");
  assert.equal(r.status, 4);
  const runs = path.join(r.dir, ".config", "orchestrator", "runs");
  assert.ok(!fs.existsSync(runs) || fs.readdirSync(runs).length === 0, "registry entry removed at end");
});

// ---------------------------------------------------------------- Phase 3: --ticket and the resolved model
function git(cwd, ...args) {
  const r = spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8" });
  assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`);
  return r.stdout.trim();
}
// A temp repo with the board fixtures and one ticket; `claim` moves it to working, owned by s1.
function boardRepo({ claim = false } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ocw-board-"));
  CLEAN.push(root);
  const repo = path.join(root, "repo");
  fs.mkdirSync(repo);
  git(repo, "init", "-b", "main");
  git(repo, "config", "user.email", "board@example.test");
  git(repo, "config", "user.name", "oc-worker test");
  git(repo, "config", "commit.gpgsign", "false");
  fs.mkdirSync(path.join(repo, ".opencode", "board"), { recursive: true });
  fs.copyFileSync(path.join(BOARD_FIX, "adapter.json"), path.join(repo, ".opencode", "board", "adapter.json"));
  fs.writeFileSync(path.join(repo, "README.md"), "board test repo\n");
  git(repo, "add", "README.md", ".opencode/board/adapter.json");
  git(repo, "commit", "-m", "init");
  const wt = path.join(root, "wt");
  git(repo, "worktree", "add", "-b", "feat/demo", wt);
  const mandate = path.join(root, "mandate.md");
  fs.copyFileSync(path.join(BOARD_FIX, "mandate.md"), mandate);
  const env = { ...process.env, ORCH_HOME: path.join(root, "orch-home") };
  const board = (...args) => spawnSync(process.execPath, [BOARD, ...args], { cwd: repo, env, encoding: "utf8" });
  const ok = (r) => assert.equal(r.status, 0, r.stderr);
  ok(board("create", "ticket-one", "--mandate", mandate, "--scope", "bin/demo.mjs"));
  if (claim) {
    ok(board("egm", "ticket-one", "waive", "--reason", "no persisted format, no public interface", "--by", "rick"));
    ok(board("claim", "ticket-one", "--owner", "s1", "--harness", "opencode", "--worktree", wt));
  }
  const ticketPath = path.join(repo, ".opencode", "board", "tickets", "ticket-one.json");
  return { root, repo, wt, mandate, env, board, ticket: () => JSON.parse(fs.readFileSync(ticketPath, "utf8")) };
}

test("26. --ticket on a non-working ticket exits 7 and never launches opencode or takes a slot", () => {
  const c = boardRepo(); // created, never claimed: still queued
  const argsFile = path.join(c.root, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", c.wt, "--prompt", c.mandate, "--out", path.join(c.root, "out", "worker-r1.md"), "--ticket", "ticket-one", "--owner", "s1"], {
    env: { ...c.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 7, r.stderr);
  assert.match(r.stderr, /oc-worker: --ticket ticket-one: board: attach needs stage working, ticket is queued/);
  assert.ok(!fs.existsSync(argsFile), "opencode must not be spawned");
  const slots = path.join(c.env.ORCH_HOME, ".config", "orchestrator", "slots");
  assert.ok(!fs.existsSync(slots) || fs.readdirSync(slots).length === 0, "no worker slot was taken");
  assert.equal(c.ticket().assignment, null, "nothing was attached");

  // --ticket is a usage error without --owner.
  const noOwner = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", c.wt, "--prompt", c.mandate, "--ticket", "ticket-one"], {
    env: { ...c.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(noOwner.status, 2);
  assert.match(noOwner.stderr, /--ticket needs --owner/);
  assert.ok(!fs.existsSync(argsFile));

  // A working ticket owned by another session is refused as well: a worker cannot attach to someone else's ticket.
  const other = boardRepo({ claim: true }); // claimed by s1
  const hijackFile = path.join(other.root, "args.json");
  const hijack = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", other.wt, "--prompt", other.mandate, "--out", path.join(other.root, "out", "worker-r1.md"), "--ticket", "ticket-one", "--owner", "s2"], {
    env: { ...other.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", FAKE_OC_ARGS_FILE: hijackFile },
    encoding: "utf8",
  });
  assert.equal(hijack.status, 7, hijack.stderr);
  assert.match(hijack.stderr, /owned by s1/);
  assert.equal(other.ticket().assignment.worker, null, "the other session's ticket was left alone");
  assert.ok(!fs.existsSync(hijackFile), "opencode must not be spawned");
});

test("--ticket on a working owned ticket attaches the run to the board before launching it", () => {
  const c = boardRepo({ claim: true });
  const out = path.join(c.root, "out", "worker-r1.md");
  const argsFile = path.join(c.root, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", c.wt, "--prompt", c.mandate, "--out", out, "--ticket", "ticket-one", "--owner", "s1"], {
    env: { ...c.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stderr);
  const w = c.ticket().assignment.worker;
  assert.ok(Number.isInteger(w.pid) && w.pid > 0, "the oc-worker's own pid was attached");
  assert.equal(w.out_path, path.resolve(out));
  assert.ok(w.started === null || Date.parse(w.started) > 0, "started is the process start time, or null on a failed lookup");
  assert.ok(fs.existsSync(argsFile), "opencode ran");
});

test("28. a receipt records the pinned model when the agent default was used", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const agents = path.join(dir, ".config", "opencode", "agents");
  fs.mkdirSync(agents, { recursive: true });
  fs.writeFileSync(path.join(agents, "critic.md"), "---\ndescription: fixture\nmodel: commandcode/claude-haiku-5-5\n---\n");
  const spawnWith = (...flags) =>
    spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", path.join(dir, "out", "f.md"), ...flags], {
      env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir },
      encoding: "utf8",
    });
  const r = spawnWith();
  assert.equal(r.status, 0, r.stderr);
  assert.equal(JSON.parse(r.stdout.trim()).model, "commandcode/claude-haiku-5-5", "the pinned model, not (agent default)");
  const onDisk = JSON.parse(fs.readFileSync(path.join(dir, "out", "f.md.receipt.json"), "utf8"));
  assert.equal(onDisk.model, "commandcode/claude-haiku-5-5");

  const explicit = spawnWith("--model", "opencode-go/mimo-v2.6-flash");
  assert.equal(explicit.status, 0, explicit.stderr);
  assert.equal(JSON.parse(explicit.stdout.trim()).model, "opencode-go/mimo-v2.6-flash", "--model still wins");
});

test("drop-once: a dropped run is resumed with --session and finishes (one slot, two spawns)", () => {
  const state = tmp();
  CLEAN.push(state);
  const r = run({ FAKE_OC_MODE: "drop-once", FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "0" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.resumed.length, 1);
  assert.match(receipt.resumed[0].reason, /ECONNRESET/);
  assert.equal(receipt.attempts, 2);
  assert.deepEqual(receipt.errors, []);
  const calls = fs.readFileSync(path.join(state, "calls.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.equal(calls.length, 2);
  assert.ok(!calls[0].includes("--session"));
  assert.equal(calls[1][calls[1].indexOf("--session") + 1], "ses_fake123");
  assert.match(calls[1].at(-1), /^The previous run was interrupted \(.*ECONNRESET/);
  assert.match(calls[1].at(-1), /git status --short/);
  assert.match(calls[1].at(-1), /Run constraints/);
  assert.ok(calls[0].includes("--standalone"), "first attempt carries --standalone");
  assert.ok(calls[1].includes("--standalone"), "resumed call carries --standalone");
});

test("drop with --resume 0 is not resumed; stderr and events errors reach the receipt", () => {
  const r = run({ FAKE_OC_MODE: "drop" }, "--resume", "0");
  assert.equal(r.status, 5);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.attempts, 1);
  assert.deepEqual(receipt.resumed, []);
  assert.match(receipt.errors.join("\n"), /ECONNRESET/);
});

test("a drop that persists is resumed once, then the failure is the result", () => {
  const r = run({ FAKE_OC_MODE: "drop", ORCH_RESUME_WAIT_MS: "0" });
  assert.equal(r.status, 5);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.attempts, 2);
  assert.equal(receipt.resumed.length, 1);
});

test("hang-after-text with --idle-min is killed as stalled and keeps its partial output", () => {
  const r = run({ FAKE_OC_MODE: "hang-after-text", ORCH_RESUME_WAIT_MS: "0" }, "--idle-min", "0.02", "--resume", "0", "--timeout-min", "2");
  assert.equal(r.status, 4, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "stalled");
  assert.equal(receipt.partial, true);
  assert.ok(receipt.max_silence_s >= 1);
  assert.ok(receipt.errors.some((e) => /^stalled — no output for 0\.02 min/.test(e)));
  const out = fs.readFileSync(path.join(r.dir, "out", "findings-r1.md"), "utf8");
  assert.match(out, /^RESULT: BLOCKED: stalled — no output for 0\.02 min — partial output below/);
  assert.match(out, /found candidate A/);
});

test("--idle-min 0 never stalls: the run ends on the timeout", () => {
  const r = run({ FAKE_OC_MODE: "hang-after-text" }, "--idle-min", "0", "--timeout-min", "0.1", "--grace-min", "0");
  assert.equal(r.status, 4);
  assert.equal(JSON.parse(r.stdout.trim()).exit, "timeout");
});

// ---------------------------------------------------------------- worker-liveness: Nvidia idle/resume defaults

test("nvidia agent defaults: idle-min 6, resume 3 (explicit flags still win)", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const nv = args(["--agent", "worker-nvidia", "--dir", dir, "--prompt", prompt]);
  assert.equal(nv.idleMin, 6, "worker-nvidia idle-min default is 6");
  assert.equal(nv.resume, 3, "worker-nvidia resume default is 3");
  const nvc = args(["--agent", "critic-nvidia", "--dir", dir, "--prompt", prompt]);
  assert.equal(nvc.idleMin, 6, "critic-nvidia idle-min default is 6");
  assert.equal(nvc.resume, 3, "critic-nvidia resume default is 3");
  const plain = args(["--agent", "critic", "--dir", dir, "--prompt", prompt]);
  assert.equal(plain.idleMin, 20, "non-nvidia idle-min default stays 20");
  assert.equal(plain.resume, 1, "non-nvidia resume default stays 1");
  // explicit flags win over nvidia defaults
  const expl = args(["--agent", "worker-nvidia", "--dir", dir, "--prompt", prompt, "--idle-min", "9", "--resume", "7"]);
  assert.equal(expl.idleMin, 9);
  assert.equal(expl.resume, 7);
});

// ---------------------------------------------------------------- worker-liveness: visible slot wait

test("slot wait: both worker slots held -> stderr names both holders, registry is queued, queued_s > 0 after release", async () => {
  const home = tmp();
  CLEAN.push(home);
  const slots = path.join(home, ".config", "orchestrator", "slots");
  // Hold both slots with live owner files
  fs.mkdirSync(slots, { recursive: true });
  for (const i of [1, 2]) {
    fs.mkdirSync(path.join(slots, `slot-${i}`), { recursive: true });
    fs.writeFileSync(path.join(slots, `slot-${i}`, "owner"), JSON.stringify({ pid: process.pid, agent: "worker", title: "holder " + i, out: "/tmp/holder" + i + ".md", since: new Date().toISOString() }));
  }
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const argsFile = path.join(home, "args.json");
  const out = path.join(home, "out", "worker-r1.md");
  const stderr = [];
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", home, "--prompt", prompt, "--out", out, "--slots", "2"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_HOME: home, FAKE_OC_ARGS_FILE: argsFile, ORCH_NO_PROCTREE: "1", ORCH_NVIDIA_POLL_MS: "50" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stderr.on("data", (d) => stderr.push(d.toString()));
  const exited = new Promise((res) => child.on("close", (code) => res(code)));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 20000);
  try {
    // Wait until the waiting line appears on stderr
    let sawWait = false;
    for (let i = 0; i < 100 && !sawWait; i++) {
      await new Promise((r) => setTimeout(r, 200));
      const joined = stderr.join("");
      if (/oc-worker: waiting for a worker slot \(cap 2 fixed; held by pid/.test(joined)) sawWait = true;
    }
    assert.ok(sawWait, "stderr should show the worker slot waiting line naming holders; got: " + stderr.join(""));
    const joined = stderr.join("");
    assert.match(joined, /pid \d+ worker holder 1/);
    assert.match(joined, /pid \d+ worker holder 2/);
    // Registry entry exists and is queued
    const runs = path.join(home, ".config", "orchestrator", "runs");
    const runFiles = fs.readdirSync(runs).filter((f) => f.endsWith(".json"));
    assert.equal(runFiles.length, 1, "exactly one registry entry while waiting");
    const reg = JSON.parse(fs.readFileSync(path.join(runs, runFiles[0]), "utf8"));
    assert.equal(reg.state, "queued", "registry state is queued while waiting");
    // Release one slot: the run should acquire it and complete
    fs.rmSync(path.join(slots, "slot-1"), { recursive: true, force: true });
    const code = await exited;
    assert.equal(code, 0, "run completes after a slot frees");
    clearTimeout(hard);
    const receipt = JSON.parse(fs.readFileSync(out + ".receipt.json", "utf8"));
    assert.ok(receipt.queued_s > 0, `receipt.queued_s should be > 0, got ${receipt.queued_s}`);
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

test("slot wait: nvidia slot held -> stderr names the nvidia holder", async () => {
  const home = tmp();
  CLEAN.push(home);
  const slots = path.join(home, ".config", "orchestrator", "slots");
  fs.mkdirSync(slots, { recursive: true });
  fs.mkdirSync(path.join(slots, "provider-nvidia-1"), { recursive: true });
  fs.writeFileSync(path.join(slots, "provider-nvidia-1", "owner"), JSON.stringify({ pid: process.pid, agent: "worker-nvidia", title: "nvidia holder", out: "/tmp/nv.md", since: new Date().toISOString() }));
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const argsFile = path.join(home, "args.json");
  const out = path.join(home, "out", "nv-r1.md");
  const stderr = [];
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", home, "--prompt", prompt, "--out", out, "--model", "nvidia/test-model", "--slots", "2"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_HOME: home, FAKE_OC_ARGS_FILE: argsFile, ORCH_NO_PROCTREE: "1", ORCH_NVIDIA_POLL_MS: "50", NVIDIA_SLOTS: "1" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stderr.on("data", (d) => stderr.push(d.toString()));
  const exited = new Promise((res) => child.on("close", (code) => res(code)));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 20000);
  try {
    let sawWait = false;
    for (let i = 0; i < 100 && !sawWait; i++) {
      await new Promise((r) => setTimeout(r, 200));
      if (/oc-worker: waiting for a nvidia slot \(cap 1 fixed; held by pid/.test(stderr.join(""))) sawWait = true;
    }
    assert.ok(sawWait, "stderr should show the nvidia slot waiting line; got: " + stderr.join(""));
    const joined = stderr.join("");
    assert.match(joined, /pid \d+ worker-nvidia nvidia holder/);
    // Release the nvidia slot: run completes
    fs.rmSync(path.join(slots, "provider-nvidia-1"), { recursive: true, force: true });
    const code = await exited;
    assert.equal(code, 0, "run completes after the nvidia slot frees");
    clearTimeout(hard);
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

// ---------------------------------------------------------------- worker-liveness: nvidia nudge (silent -> resumed -> done)

test("worker-nvidia nudge: a silent fake is nudged then finishes (resumed.length >= 1, exit 0)", () => {
  const state = tmp();
  CLEAN.push(state);
  // The real Nvidia default (6 min) cannot fit a suite, so assert it here — the mutation check reverts the
  // default to 20 and this assertion fails — then shorten the idle window for the behavioural part below.
  const dflt = args(["--agent", "worker-nvidia", "--dir", state, "--prompt", "/dev/null"]);
  assert.equal(dflt.idleMin, 6, "worker-nvidia default idle-min is 6 (mutation check)");
  const r = run({ FAKE_OC_MODE: "nudge-once", FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "0" }, "--agent", "worker-nvidia", "--idle-min", "0.02", "--resume", "3", "--timeout-min", "2");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.ok(receipt.resumed.length >= 1, `expected resumed.length >= 1, got ${receipt.resumed.length}: ${r.stdout}`);
  assert.equal(receipt.exit, 0);
  assert.ok(receipt.resumed.some((x) => /no output for/.test(x.reason)), `resumed reason should mention stall: ${JSON.stringify(receipt.resumed)}`);
  // The marker file proves the resumed call was handled differently from the first
  assert.ok(fs.existsSync(path.join(state, "nudged")), "nudged marker should exist after the resumed call");
});

test("non-nvidia agent keeps idle-min 20 / resume 1 defaults (no flags)", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const nv = args(["--agent", "worker", "--dir", dir, "--prompt", prompt]);
  assert.equal(nv.idleMin, 20);
  assert.equal(nv.resume, 1);
});

// ---------------------------------------------------------------- worker-liveness: hung tool call

test("hung tool call: the descendant tool child is killed, opencode survives, then the next stall nudges it", async () => {
  const state = tmp();
  CLEAN.push(state);
  const home = tmp();
  CLEAN.push(home);
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const argsFile = path.join(home, "args.json");
  const out = path.join(home, "out", "worker-r1.md");
  const stderr = [];
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", home, "--prompt", prompt, "--out", out, "--slots", "2", "--idle-min", "0.02", "--resume", "2", "--timeout-min", "2", "--grace-min", "0"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_HOME: home, FAKE_OC_ARGS_FILE: argsFile, ORCH_NO_PROCTREE: "", ORCH_PROCTREE_MS: "300", FAKE_OC_MODE: "hung-tool", FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "0" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  child.stderr.on("data", (d) => stderr.push(d.toString()));
  const exited = new Promise((res) => child.on("close", (code) => res(code)));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 40000);
  const alive = (pid) => { try { process.kill(pid, 0); return true; } catch { return false; } };
  try {
    const code = await exited;
    assert.equal(code, 0, "run finishes after the hung tool is killed and opencode is nudged");
    clearTimeout(hard);
    const receipt = JSON.parse(fs.readFileSync(out + ".receipt.json", "utf8"));
    // The tool child was killed (and named in the receipt)
    const toolPid = Number(fs.readFileSync(path.join(state, "hung-tool-pid"), "utf8"));
    assert.ok(receipt.orphans_killed?.some((o) => o.pid === toolPid), `receipt orphans_killed should include the tool child pid ${toolPid}: ${JSON.stringify(receipt.orphans_killed)}`);
    // The resume happened and its message names the stopped command
    assert.ok(receipt.resumed.length >= 1, `expected a nudge, got ${JSON.stringify(receipt.resumed)}`);
    const call = JSON.parse(fs.readFileSync(argsFile, "utf8"));
    const lastMsg = call.argv[call.argv.length - 1];
    assert.ok(/A tool command ran over/.test(lastMsg), "resume message should mention the stopped tool command: " + lastMsg);
    // Never a second opencode while the first was alive (the killed-run-stops-agent class): the resumed
    // invocation recorded whether the first pid was still running when it started.
    assert.equal(fs.readFileSync(path.join(state, "first-alive-at-resume"), "utf8"), "0", "the first opencode must be dead before the resume spawns");
    // No opencode process survives the run
    const pid1 = Number(fs.readFileSync(path.join(state, "opencode-pid-1"), "utf8"));
    const pid2 = Number(fs.readFileSync(path.join(state, "opencode-pid-2"), "utf8"));
    assert.equal(alive(pid1), false, `first opencode pid ${pid1} must not survive the run`);
    assert.equal(alive(pid2), false, `resumed opencode pid ${pid2} must not survive the run`);
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

test("stall with no session id: never resumes into a fresh agent without the Mandate", () => {
  const state = tmp();
  CLEAN.push(state);
  const r = run({ FAKE_OC_MODE: "silent-no-session", FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "0" }, "--agent", "critic", "--idle-min", "0.02", "--resume", "3", "--timeout-min", "1", "--grace-min", "0");
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "stalled", `a stall with no session stays stalled: ${r.stdout}`);
  assert.equal(receipt.resumed.length, 0, "no resume without a session id");
  const calls = fs.readFileSync(path.join(state, "calls.jsonl"), "utf8").trim().split("\n");
  assert.equal(calls.length, 1, "exactly one opencode spawn (no resume without a session)");
});


test("a prompt starting with --- reaches opencode as a message (newline-prefixed), not a flag", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "---\ntitle: x\n---\nDo it.");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", path.join(dir, "o.md")], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const { argv } = JSON.parse(fs.readFileSync(argsFile, "utf8"));
  assert.ok(argv.at(-1).startsWith("\n---\ntitle: x\n---\nDo it."));
});

test("--help documents --idle-min, --resume, stalled, max_silence_s and resumed", () => {
  const h = spawnSync(process.execPath, [BIN, "--help"], { encoding: "utf8" });
  for (const w of ["--idle-min", "--resume", "stalled", "max_silence_s", "resumed"]) assert.ok(h.stdout.includes(w), w);
});

test("a clean run (exit 0, final text) with stderr 'fetch failed' is not resumed; stderr stays in errors", () => {
  const r = run({ FAKE_OC_STDERR: "fetch failed", ORCH_RESUME_WAIT_MS: "0" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.attempts, 1);
  assert.deepEqual(receipt.resumed, []);
  assert.match(receipt.errors.join("\n"), /fetch failed/);
});

test("an orphaned grandchild left by opencode is swept and listed in orphans_killed", { skip: process.env.ORCH_NO_PROCTREE === "1", timeout: 90_000 }, () => {
  const stateDir = tmp();
  CLEAN.push(stateDir);
  const r = run({ FAKE_OC_MODE: "orphan", FAKE_OC_STATE_DIR: stateDir, FAKE_OC_ORPHAN_WAIT: "6000", ORCH_PROCTREE_MS: "300", ORCH_NO_PROCTREE: "" });
  const gc = Number(fs.readFileSync(path.join(stateDir, "grandchild.pid"), "utf8"));
  const isAlive = () => {
    try {
      process.kill(gc, 0);
      return true;
    } catch (e) {
      return e.code === "EPERM";
    }
  };
  const alive = isAlive();
  if (alive) {
    try {
      if (process.platform === "win32") spawnSync("taskkill", ["/PID", String(gc), "/T", "/F"], { stdio: "ignore" });
      else process.kill(gc, "SIGKILL");
    } catch {}
  }
  assert.equal(r.status, 0, r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.ok(receipt.orphans_killed?.some((o) => o.pid === gc), `receipt: ${r.stdout}`);
  assert.equal(alive, false, "grandchild survived the run");
});

test("receipt has no orphans_killed when nothing was left over", () => {
  const r = run({});
  assert.equal(JSON.parse(r.stdout.trim()).orphans_killed, undefined);
});

// ============ Read-only guard tests (T9) ============

// A throwaway ORCH_HOME with the real plan installed into it. Returns { home, target } where target is an installed file.
async function installedHome() {
  const home = tmp();
  CLEAN.push(home);
  const prev = process.env.ORCH_HOME;
  process.env.ORCH_HOME = home;
  try {
    const inst = await import("../bin/install.mjs");
    inst.install({ log() {} });
    const t = inst.plan().find((it) => /critic.md$/.test(it.target));
    assert.ok(t && fs.existsSync(t.target), "plan has an installed critic.md");
    return { home, target: t.target, content: t.content };
  } finally {
    if (prev === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = prev;
  }
}

function runAgent(agent, extraEnv, flags = []) {
  const dir = tmp();
  CLEAN.push(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = spawnSync(process.execPath, [BIN, "--agent", agent, "--dir", extraEnv.WT || dir, "--prompt", prompt, "--out", path.join(dir, "out", "findings-r1.md"), ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", FAKE_OC_ARGS_FILE: path.join(dir, "args.json"), ...extraEnv },
    encoding: "utf8",
  });
  return { ...r, dir, receipt: r.stdout.trim().startsWith("{") ? JSON.parse(r.stdout.trim()) : null };
}

test("readonly guard: critic editing an installed file is restored, backed up, and its gate is INVALID", async () => {
  const { home, target, content } = await installedHome();
  const r = runAgent("critic", { ORCH_HOME: home, FAKE_OC_MODE: "edit-installed", FAKE_OC_TARGET: target });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(fs.readFileSync(target, "utf8").replace(/\r\n/g, "\\n"), content);
  const t = r.receipt.tampered;
  assert.equal(t.length, 1);
  assert.equal(t[0].target, target);
  assert.equal(t[0].restored, true);
  assert.match(fs.readFileSync(t[0].backup, "utf8"), /modified by fake/);
  assert.match(t[0].backup, /-tampered/);
  assert.ok(r.receipt.errors.some((e) => e.includes("read-only role modified installed file")));
  assert.equal(r.receipt.readonly_violation, true);
  assert.equal(r.receipt.gate.effective, "INVALID");
  assert.ok(r.receipt.gate.reasons.includes("readonly_violation"));
});

test("readonly guard: drift that existed before the run is left alone and not reported", async () => {
  const { home, target } = await installedHome();
  fs.writeFileSync(target, "owner drift\n");
  const r = runAgent("critic", { ORCH_HOME: home, FAKE_OC_MODE: "ok" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(fs.readFileSync(target, "utf8"), "owner drift\n");
  assert.equal(r.receipt.tampered, undefined);
  assert.equal(r.receipt.readonly_violation, undefined);
});

test("readonly guard: worktree changes are recorded, not reverted", () => {
  const home = tmp();
  CLEAN.push(home);
  const wt = tmp();
  CLEAN.push(wt);
  const git = (...args) => spawnSync("git", ["-C", wt, ...args], { encoding: "utf8" });
  git("init", "-b", "main");
  git("config", "user.email", "t@t");
  git("config", "user.name", "t");
  fs.writeFileSync(path.join(wt, "file.txt"), "original");
  git("add", "file.txt");
  git("commit", "-m", "init");
  const file = path.join(wt, "file.txt");
  const r = runAgent("critic", { ORCH_HOME: home, WT: wt, FAKE_OC_MODE: "edit-worktree", FAKE_OC_TARGET: file });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(fs.readFileSync(file, "utf8"), "modified\n");
  const w = r.receipt.worktree_changed;
  assert.ok(w, "worktree_changed present");
  assert.equal(w.head_before, w.head_after);
  assert.equal(w.status_before, "(clean)");
  assert.match(w.status_after, /file.txt/);
  assert.equal(r.receipt.readonly_violation, true);
  assert.equal(r.receipt.gate.effective, "INVALID");
  assert.ok(r.receipt.errors.includes("read-only role changed the worktree"));
});

test("readonly guard: a worker agent is not guarded and gets no guard fields", async () => {
  const { home, target } = await installedHome();
  const r = runAgent("worker", { ORCH_HOME: home, FAKE_OC_MODE: "edit-installed", FAKE_OC_TARGET: target });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(fs.readFileSync(target, "utf8"), "modified by fake\n");
  for (const k of ["tampered", "worktree_changed", "readonly_violation"]) assert.equal(r.receipt[k], undefined, k);
});

test("readonly guard: ORCH_NO_READONLY_GUARD=1 turns it off", async () => {
  const { home, target } = await installedHome();
  const r = runAgent("critic", { ORCH_HOME: home, ORCH_NO_READONLY_GUARD: "1", FAKE_OC_MODE: "edit-installed", FAKE_OC_TARGET: target });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(fs.readFileSync(target, "utf8"), "modified by fake\n");
  for (const k of ["tampered", "worktree_changed", "readonly_violation"]) assert.equal(r.receipt[k], undefined, k);
  assert.ok(!r.receipt.gate.reasons.includes("readonly_violation"));
});

test("readonly guard: scratch dir exists during the run, ORCH_SCRATCH is set and the prompt names it, dir is gone after", () => {
  const home = tmp();
  CLEAN.push(home);
  const rec = path.join(home, "scratch-record.json");
  const r = runAgent("critic", { ORCH_HOME: home, FAKE_OC_MODE: "capture-scratch", FAKE_OC_RECORD: rec });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const seen = JSON.parse(fs.readFileSync(rec, "utf8"));
  assert.ok(seen.scratch.startsWith(path.join(os.tmpdir(), "orch-scratch-")), seen.scratch);
  assert.equal(seen.existed, true);
  assert.ok(seen.message.includes(seen.scratch), "prompt names the scratch dir");
  assert.match(seen.message, /read-only role/);
  assert.equal(fs.existsSync(seen.scratch), false);
});

test("readonly guard: a missing --prompt leaves no slot and no scratch dir", () => {
  const home = tmp();
  CLEAN.push(home);
  const priv = tmp(); // private temp dir so other tests scratch dirs cannot interfere
  CLEAN.push(priv);
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", home, "--prompt", path.join(home, "nope.md"), "--out", path.join(home, "out", "f.md")], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: home, TEMP: priv, TMP: priv, TMPDIR: priv },
    encoding: "utf8",
  });
  assert.notEqual(r.status, 0);
  const sd = path.join(home, ".config", "orchestrator", "slots");
  assert.deepEqual(fs.existsSync(sd) ? fs.readdirSync(sd).filter((n) => n.startsWith("slot-")) : [], []);
  assert.deepEqual(fs.readdirSync(priv), []);
});

test("readonly guard: a guard exception leaves exit and status unchanged, and the worktree guard still works", () => {
  const home = tmp();
  CLEAN.push(home);
  const wt = tmp();
  CLEAN.push(wt);
  const git = (...args) => spawnSync("git", ["-C", wt, ...args], { encoding: "utf8" });
  git("init", "-b", "main");
  git("config", "user.email", "t@t");
  git("config", "user.name", "t");
  fs.writeFileSync(path.join(wt, "file.txt"), "original");
  git("add", "file.txt");
  git("commit", "-m", "init");
  const file = path.join(wt, "file.txt");
  const r = runAgent("critic", { ORCH_HOME: home, WT: wt, ORCH_TEST_GUARD_FAULT: "1", FAKE_OC_MODE: "edit-worktree", FAKE_OC_TARGET: file });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.ok(r.receipt.errors.some((e) => e.startsWith("readonly guard skipped: injected guard fault")));
  assert.equal(r.receipt.exit, 0);
  assert.ok(r.receipt.worktree_changed, "worktree guard survives a diff() failure");
  assert.equal(r.receipt.readonly_violation, true);
});

// ── --stream: queued / run-done events (m6a T7) ─────────────────────────────
function streamHome(name = "m6a") {
  const h = tmp();
  CLEAN.push(h);
  const sd = path.join(h, ".config", "orchestrator", "streams");
  fs.mkdirSync(sd, { recursive: true });
  fs.writeFileSync(path.join(sd, `${name}.json`), JSON.stringify({ name, repo: "", plan: "", status: "active", next: "x", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: null, done_at: null }));
  return { h, sd };
}
function streamRun(h, extraEnv, outName, ...flags) {
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(h, "run");
  fs.mkdirSync(runDir, { recursive: true });
  // --stream now requires ticket.json beside --out: write it so the preflight passes.
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir }));
  const out = path.join(runDir, outName);
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", prompt, "--out", out, "--stream", "m6a", ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, ...extraEnv },
    encoding: "utf8",
  });
  return { ...r, out };
}
const eventsOf = (sd) => {
  try {
    return fs.readFileSync(path.join(sd, "m6a.events.jsonl"), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  } catch {
    return [];
  }
};

test("--stream appends queued then one run-done; no stream flag creates no stream files", () => {
  const { h, sd } = streamHome();
  const r = streamRun(h, {}, "worker-r1.md");
  assert.equal(r.status, 0, r.stderr);
  const ev = eventsOf(sd);
  // ticket.json now carries ticket "m6a": the id's ticket part is "m6a", not the run dir basename
  assert.deepEqual(ev.map((e) => e.key), ["run:m6a/worker-r1:queued", "run:m6a/worker-r1:done"]);
  assert.equal(ev[0].run, "m6a/worker-r1");
  assert.equal(ev[0].kind, "queued");
  assert.equal(ev[0].pid > 0, true);
  assert.equal(ev[0].ticket, path.join(path.dirname(r.out), "ticket.json"));
  assert.equal(ev[0].agent, "critic");
  assert.equal(ev[1].kind, "run-done");
  assert.equal(ev[1].exit, 0);
  assert.equal(ev[1].session, "ses_fake123");
  assert.equal(typeof ev[1].outcome, "string");
  const plain = run({});
  assert.equal(plain.status, 0);
  assert.ok(!fs.existsSync(path.join(plain.dir, ".config", "orchestrator", "streams")), "no --stream: no stream files");
});

test("--stream with a fallback hop appends run-done exactly once, for the final receipt", () => {
  const { h, sd } = streamHome();
  const r = streamRun(h, { FAKE_OC_MODE: "quota-critic" }, "worker-r1.md", "--fallback", "critic-go");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const ev = eventsOf(sd);
  assert.equal(ev.filter((e) => e.kind === "queued").length, 1);
  const done = ev.filter((e) => e.kind === "run-done");
  assert.equal(done.length, 1);
  assert.equal(done[0].agent, "critic-go");
});

test("status 6 (every pool down) and status 8 (model not allowed) runs still append run-done and a receipt", async () => {
  const { markDown } = await import("../bin/pool-health.mjs");
  const six = streamHome();
  const before = process.env.ORCH_HOME;
  process.env.ORCH_HOME = six.h;
  try {
    markDown("p/m", { reason: "quota", ms: 3600_000 });
  } finally {
    if (before === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = before;
  }
  const r6 = streamRun(six.h, {}, "worker-r1.md", "--model", "p/m");
  assert.equal(r6.status, 6, r6.stdout + r6.stderr);
  const d6 = eventsOf(six.sd).filter((e) => e.kind === "run-done");
  assert.equal(d6.length, 1);
  assert.equal(d6[0].outcome, "no_pool");
  assert.ok(fs.existsSync(r6.out + ".receipt.json"));

  const eight = streamHome();
  fs.writeFileSync(path.join(eight.h, ".config", "orchestrator", "providers.json"), JSON.stringify({ nvidia: { decision: "ignored" } }));
  const r8 = streamRun(eight.h, {}, "worker-r1.md", "--model", "nvidia/anything");
  assert.equal(r8.status, 8, r8.stdout + r8.stderr);
  const d8 = eventsOf(eight.sd).filter((e) => e.kind === "run-done");
  assert.equal(d8.length, 1);
  assert.equal(d8[0].outcome, "not_allowed");
  assert.equal(JSON.parse(fs.readFileSync(r8.out + ".receipt.json", "utf8")).exit, "model-not-allowed", "O5: the status-8 receipt is written");
});

test("--stream refusals: unknown stream, existing out or receipt (exit 2), duplicate queued (exit 9)", () => {
  const { h, sd } = streamHome();
  const noStream = streamRun(h, {}, "worker-r1.md", "--stream", "nope");
  assert.equal(noStream.status, 2);
  assert.match(noStream.stderr, /oc-worker: no stream nope/);
  fs.mkdirSync(path.join(h, "run"), { recursive: true });
  fs.writeFileSync(path.join(h, "run", "worker-r1.md"), "old");
  const exists = streamRun(h, {}, "worker-r1.md");
  assert.equal(exists.status, 2);
  assert.match(exists.stderr, /oc-worker: out exists — use a fresh --out per run/);
  fs.rmSync(path.join(h, "run", "worker-r1.md"));
  fs.writeFileSync(path.join(h, "run", "worker-r2.md.receipt.json"), "{}");
  assert.equal(streamRun(h, {}, "worker-r2.md").status, 2, "an old receipt alone also refuses");
  assert.deepEqual(eventsOf(sd), [], "refusals append nothing");
  fs.rmSync(path.join(h, "run", "worker-r2.md.receipt.json"));
  // ticket.json carries ticket "m6a": the queued event key uses the ticket part
  fs.writeFileSync(path.join(sd, "m6a.events.jsonl"), JSON.stringify({ key: "run:m6a/worker-r3:queued", kind: "queued", at: new Date().toISOString(), run: "m6a/worker-r3" }) + "\n");
  const dup = streamRun(h, {}, "worker-r3.md");
  assert.equal(dup.status, 9);
  assert.match(dup.stderr, /oc-worker: run m6a\/worker-r3 already queued/);
  assert.ok(!fs.existsSync(dup.out + ".events.jsonl"), "no slot taken, nothing launched");
});

test("--stream: an unresolvable model (no hop) writes the status-8 receipt and run-done; a throw after queued still appends run-done error", () => {
  const { h, sd } = streamHome();
  fs.writeFileSync(path.join(h, ".config", "orchestrator", "providers.json"), JSON.stringify({ nvidia: { decision: "ignored" } }));
  const r = streamRun(h, {}, "worker-r1.md");
  assert.equal(r.status, 8, r.stdout + r.stderr);
  assert.equal(JSON.parse(fs.readFileSync(r.out + ".receipt.json", "utf8")).exit, "model-unresolvable");
  const done = eventsOf(sd).filter((e) => e.kind === "run-done");
  assert.equal(done.length, 1);
  assert.equal(done[0].outcome, "not_allowed");

  const t = streamHome();
  const bad = streamRun(t.h, {}, "worker-r1.md", "--dir", path.join(t.h, "missing"));
  assert.equal(bad.status, 5, bad.stderr);
  const d = eventsOf(t.sd).filter((e) => e.kind === "run-done");
  assert.equal(d.length, 1);
  assert.equal(d[0].outcome, "error");
});

test("--stream: two tickets' worker-r1 on one stream both queue; the same run id queued twice is exit 9; no ticket.json uses the run dir name", () => {
  const { h, sd } = streamHome();
  // One dispatch into <runDir>, with <runDir>/ticket.json holding the ticket the desk keys runs under.
  const dispatch = (runDirName, ticketId) => {
    const runDir = path.join(h, runDirName);
    fs.mkdirSync(runDir, { recursive: true });
    if (ticketId) fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: ticketId, worktree: runDir }));
    const prompt = path.join(h, `mandate-${runDirName}.md`);
    fs.writeFileSync(prompt, "Do the thing.");
    const out = path.join(runDir, "worker-r1.md");
    const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
      env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
      encoding: "utf8",
    });
    return { ...r, out, runDir };
  };

  // Two tickets, both calling their first run worker-r1: without the ticket in the key the second would be refused (9).
  const a = dispatch("run-a", "m6a-a");
  const b = dispatch("run-b", "m6a-b");
  assert.equal(a.status, 0, a.stderr);
  assert.equal(b.status, 0, b.stderr);
  const queuedKeys = eventsOf(sd).filter((e) => e.kind === "queued").map((e) => e.key).sort();
  assert.deepEqual(queuedKeys, ["run:m6a-a/worker-r1:queued", "run:m6a-b/worker-r1:queued"]);
  assert.deepEqual(eventsOf(sd).filter((e) => e.kind === "run-done").map((e) => e.run).sort(), ["m6a-a/worker-r1", "m6a-b/worker-r1"]);

  // The same out dispatched twice while the first run is still going (no out or receipt yet) is the run's own key: 9.
  fs.rmSync(a.out, { force: true });
  fs.rmSync(a.out + ".receipt.json", { force: true });
  const again = dispatch("run-a", "m6a-a");
  assert.equal(again.status, 9, again.stdout + again.stderr);
  assert.match(again.stderr, /oc-worker: run m6a-a\/worker-r1 already queued/);

  // No ticket.json: the run directory's basename is the ticket part — but --stream now requires
  // ticket.json, so give each dir one. Two dirs still do not collide.
  const c = dispatch("run-c", "run-c");
  const d = dispatch("run-d", "run-d");
  assert.equal(c.status, 0, c.stderr);
  assert.equal(d.status, 0, d.stderr);
  assert.deepEqual(
    eventsOf(sd).filter((e) => e.kind === "queued").map((e) => e.run).sort(),
    ["m6a-a/worker-r1", "m6a-b/worker-r1", "run-c/worker-r1", "run-d/worker-r1"],
  );
});

test("--stream refuses a relative --report with exit 2, naming the flag", () => {
  const { h, sd } = streamHome();
  const runDir = path.join(h, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(h, "args.json");
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", prompt, "--out", out, "--stream", "m6a", "--report", "report.md"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, /oc-worker: --report must be an absolute path with --stream/);
  assert.ok(!fs.existsSync(argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

test("--stream requires ticket.json to parse with a non-empty string ticket", () => {
  const { h, sd } = streamHome();
  const runDir = path.join(h, "run");
  fs.mkdirSync(runDir, { recursive: true });
  const out = path.join(runDir, "worker-r1.md");
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");

  // invalid JSON
  fs.writeFileSync(path.join(runDir, "ticket.json"), "{ not json");
  const badJson = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", path.join(h, "mandate.md"), "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(badJson.status, 2, badJson.stderr);
  assert.match(badJson.stderr, new RegExp(`oc-worker: --stream needs ${path.join(runDir, "ticket.json")} beside --out: not valid JSON`));

  // empty ticket string
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "" }));
  const empty = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", path.join(h, "mandate.md"), "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(empty.status, 2, empty.stderr);
  assert.match(empty.stderr, /missing non-empty string "ticket"/);

  // missing ticket key
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ worktree: runDir }));
  const missing = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", path.join(h, "mandate.md"), "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(missing.status, 2, missing.stderr);
  assert.match(missing.stderr, /missing non-empty string "ticket"/);

  // valid ticket: passes preflight
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir }));
  const valid = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", path.join(h, "mandate.md"), "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(valid.status, 0, valid.stderr);
});

// ── stale / dirty tree preflight (M3) ─────────────────────────────────
// A temp git repo: HEAD = "head" commit, base = a commit on an orphan branch (not an ancestor of HEAD).
function makeRepo() {
  const dir = tmp();
  CLEAN.push(dir);
  const git = (...args) => spawnSync("git", ["-C", dir, ...args], { encoding: "utf8" });
  const ran = (...args) => { const r = git(...args); assert.equal(r.status, 0, `git ${args.join(" ")}: ${r.stderr}`); return r.stdout.trim(); };
  assert.equal(ran("init", "-b", "main").length > 0, true, "git init");
  ran("config", "user.email", "t@t");
  ran("config", "user.name", "t");
  fs.writeFileSync(path.join(dir, ".gitignore"), "run/\n");
  fs.writeFileSync(path.join(dir, "a.txt"), "a\n");
  ran("add", ".gitignore", "a.txt");
  ran("commit", "-m", "head");
  const head = ran("rev-parse", "HEAD");
  ran("checkout", "--orphan", "base-branch");
  fs.writeFileSync(path.join(dir, "b.txt"), "b\n");
  ran("add", "b.txt");
  ran("commit", "-m", "base");
  const base = ran("rev-parse", "HEAD");
  ran("checkout", "main");
  return { dir, head, base };
}

// --stream worker run against a git repo dir; stream home is h (ORCH_HOME). ticket.json carries base.
function freshStream(h, workdir, agent, outName, base, ...flags) {
  const git = (...args) => spawnSync("git", ["-C", workdir, ...args], { encoding: "utf8" });
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  git("add", prompt);
  git("commit", "-m", "prompt");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base }));
  const out = path.join(runDir, outName);
  const argsFile = path.join(workdir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", agent, "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a", ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  return { ...r, out, argsFile, workdir };
}

test("stale tree: base not an ancestor of HEAD -> exit 10, 'stale tree', no queued, fake-opencode not called", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, base } = makeRepo();
  const r = freshStream(h, workdir, "worker", "worker-r1.md", base);
  assert.equal(r.status, 10, r.stdout + r.stderr);
  assert.match(r.stderr, /oc-worker: stale tree/);
  assert.ok(!fs.existsSync(r.argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

test("dirty tree: modified tracked file -> exit 10 'dirty tree'", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  fs.writeFileSync(path.join(workdir, "a.txt"), "modified\n"); // tracked file modified
  const r = freshStream(h, workdir, "worker", "worker-r1.md", head);
  assert.equal(r.status, 10, r.stdout + r.stderr);
  assert.match(r.stderr, /oc-worker: dirty tree/);
  assert.ok(!fs.existsSync(r.argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

test("dirty tree: untracked file -> exit 10 'dirty tree'", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  fs.writeFileSync(path.join(workdir, "junk.txt"), "junk\n"); // untracked file
  const r = freshStream(h, workdir, "worker", "worker-r1.md", head);
  assert.equal(r.status, 10, r.stdout + r.stderr);
  assert.match(r.stderr, /oc-worker: dirty tree/);
  assert.ok(!fs.existsSync(r.argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

test("clean tree + fresh base: worker runs as today (exit 0, queued + run-done)", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  const r = freshStream(h, workdir, "worker", "worker-r1.md", head);
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.session, "ses_fake123");
  const ev = eventsOf(sd);
  assert.deepEqual(ev.map((e) => e.key), ["run:m6a/worker-r1:queued", "run:m6a/worker-r1:done"]);
});

test("--session on a stale tree is not checked: runs", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, base } = makeRepo();
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base }));
  const out = path.join(runDir, "worker-r1.md");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", workdir, "--prompt", prompt, "--out", out, "--session", "ses_round1", "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(JSON.parse(r.stdout.trim()).session, "ses_round1");
});

test("critic agent (--agent critic-nvidia) on a dirty tree is not checked: runs", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  fs.writeFileSync(path.join(workdir, "junk.txt"), "junk\n"); // untracked => dirty
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base: head }));
  const out = path.join(runDir, "findings-r1.md");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic-nvidia", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("ticket.json without base: runs (warning only)", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir })); // no base
  const out = path.join(runDir, "worker-r1.md");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.ok(r.stderr.includes("no \"base\""), `expected base-missing warning, got: ${r.stderr}`);
});

test("dirty tree: untracked symlink/junction is not counted as dirty -> runs", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  fs.mkdirSync(path.join(workdir, "real-dir"), { recursive: true });
  fs.symlinkSync(path.join(workdir, "real-dir"), path.join(workdir, "link-to-dir")); // untracked symlink
  const r = freshStream(h, workdir, "worker", "worker-r1.md", head);
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("dirty tree: a tracked change still refuses even alongside an untracked symlink", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  fs.symlinkSync(path.join(workdir, "a.txt"), path.join(workdir, "link.txt")); // untracked symlink (ignored)
  fs.writeFileSync(path.join(workdir, "a.txt"), "modified\n"); // tracked change => real dirt
  const r = freshStream(h, workdir, "worker", "worker-r1.md", head);
  assert.equal(r.status, 10, r.stdout + r.stderr);
  assert.match(r.stderr, /oc-worker: dirty tree/);
});

test("--role worker expansion runs on a clean tree (agent worker-nvidia)", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const git = (...args) => spawnSync("git", ["-C", workdir, ...args], { encoding: "utf8" });
  git("add", prompt);
  git("commit", "-m", "prompt");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base: head }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(workdir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--role", "worker", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(JSON.parse(r.stdout.trim()).agent, "worker-nvidia", "--role worker expands to worker-nvidia");
  const ev = eventsOf(sd);
  assert.deepEqual(ev.map((e) => e.key), ["run:m6a/worker-r1:queued", "run:m6a/worker-r1:done"]);
});

test("--agent worker-nvidia runs on a clean tree", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  const r = freshStream(h, workdir, "worker-nvidia", "worker-r1.md", head);
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("origin/ base: fetch succeeds and base is an ancestor of HEAD -> runs", () => {
  const { h, sd } = streamHome();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ocw-origin-"));
  CLEAN.push(root);
  const git = (cwd, ...args) => spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8" });
  const origin = path.join(root, "origin");
  fs.mkdirSync(origin);
  git(origin, "init", "-b", "main");
  git(origin, "config", "user.email", "t@t");
  git(origin, "config", "user.name", "t");
  fs.writeFileSync(path.join(origin, "o.txt"), "o\n");
  git(origin, "add", "o.txt");
  git(origin, "commit", "-m", "origin");
  const originHead = git(origin, "rev-parse", "HEAD");

  const workdir = path.join(root, "wt");
  fs.mkdirSync(workdir);
  git(workdir, "init", "-b", "main");
  git(workdir, "config", "user.email", "t@t");
  git(workdir, "config", "user.name", "t");
  git(workdir, "remote", "add", "origin", origin);
  git(workdir, "fetch", "origin");
  git(workdir, "checkout", "-b", "dev", "origin/main");
  fs.writeFileSync(path.join(workdir, ".gitignore"), "run/\n");
  git(workdir, "add", ".gitignore");
  git(workdir, "commit", "-m", "gitignore");
  fs.writeFileSync(path.join(workdir, "a.txt"), "a\n");
  git(workdir, "add", "a.txt");
  git(workdir, "commit", "-m", "head");

  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  git(workdir, "add", prompt);
  git(workdir, "commit", "-m", "prompt");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base: "origin/main" }));
  const out = path.join(runDir, "worker-r1.md");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
});

test("dirty tree: --role worker (expands to worker-nvidia) refuses with exit 10 before queued/spawn", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  fs.writeFileSync(path.join(workdir, "a.txt"), "modified\n"); // tracked file modified => dirty
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base: head }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(workdir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--role", "worker", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 10, r.stdout + r.stderr);
  assert.match(r.stderr, /oc-worker: dirty tree/);
  assert.ok(!fs.existsSync(r.argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

test("dirty tree: --agent worker-nvidia refuses with exit 10 before queued/spawn", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  fs.writeFileSync(path.join(workdir, "a.txt"), "modified\n"); // tracked file modified => dirty
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base: head }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(workdir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker-nvidia", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 10, r.stdout + r.stderr);
  assert.match(r.stderr, /oc-worker: dirty tree/);
  assert.ok(!fs.existsSync(r.argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

test("origin/ base: failed fetch warns but the run continues (exit 0)", () => {
  const { h, sd } = streamHome();
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ocw-origin-fail-"));
  CLEAN.push(root);
  const git = (cwd, ...args) => spawnSync("git", ["-C", cwd, ...args], { encoding: "utf8" });
  const origin = path.join(root, "origin");
  fs.mkdirSync(origin);
  git(origin, "init", "-b", "main");
  git(origin, "config", "user.email", "t@t");
  git(origin, "config", "user.name", "t");
  fs.writeFileSync(path.join(origin, "o.txt"), "o\n");
  git(origin, "add", "o.txt");
  git(origin, "commit", "-m", "origin");
  const workdir = path.join(root, "wt");
  fs.mkdirSync(workdir);
  git(workdir, "init", "-b", "main");
  git(workdir, "config", "user.email", "t@t");
  git(workdir, "config", "user.name", "t");
  git(workdir, "remote", "add", "origin", origin);
  git(workdir, "fetch", "origin");
  git(workdir, "checkout", "-b", "dev", "origin/main");
  fs.writeFileSync(path.join(workdir, ".gitignore"), "run/\n");
  git(workdir, "add", ".gitignore");
  git(workdir, "commit", "-m", "gitignore");
  fs.writeFileSync(path.join(workdir, "a.txt"), "a\n");
  git(workdir, "add", "a.txt");
  git(workdir, "commit", "-m", "head");
  // Remove the origin so the fetch fails while origin/main (remote-tracking) still resolves locally.
  fs.rmSync(origin, { recursive: true, force: true });
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  git(workdir, "add", prompt);
  git(workdir, "commit", "-m", "prompt");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base: "origin/main" }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(workdir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.match(r.stderr, /oc-worker: fetch origin main failed/, "fetch warning present: " + r.stderr);
  assert.ok(fs.existsSync(argsFile), "opencode was spawned: the run continued after the failed fetch");
  const ev = eventsOf(sd);
  assert.deepEqual(ev.map((e) => e.key), ["run:m6a/worker-r1:queued", "run:m6a/worker-r1:done"]);
});

test("origin/-x base: option-like ref refused with exit 10 before any git call", () => {
  const { h, sd } = streamHome();
  const { dir: workdir, head } = makeRepo();
  const prompt = path.join(workdir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(workdir, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir, base: "origin/-x" }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(workdir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", workdir, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 10, r.stdout + r.stderr);
  assert.ok(!/fetch origin/.test(r.stderr), "no fetch warning for an option-like base: " + r.stderr);
  assert.ok(!fs.existsSync(r.argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

test("O4: both receipt writes go through atomicWrite", () => {
  const src = fs.readFileSync(BIN, "utf8");
  assert.equal((src.match(/atomicWrite\([^\n]*receipt\.json/g) || []).length, 2);
  assert.ok(!/writeFileSync\([^\n]*receipt\.json/.test(src), "no plain writeFileSync of a receipt");
});

test("midrun-quota-once: a mid-run quota death is nudged with --session and finishes", () => {
  const state = tmp();
  CLEAN.push(state);
  const r = run({ FAKE_OC_MODE: "midrun-quota-once", FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "0", ORCH_RATE_LIMIT_WAIT_MS: "0" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.attempts, 2);
  assert.equal(receipt.resumed.length, 1);
  assert.match(receipt.resumed[0].reason, /weekly usage limit|quota/i);
  assert.deepEqual(receipt.errors, []);
  const calls = fs.readFileSync(path.join(state, "calls.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.equal(calls.length, 2);
  assert.ok(!calls[0].includes("--session"));
  assert.equal(calls[1][calls[1].indexOf("--session") + 1], "ses_fake123");
  assert.match(calls[1].at(-1), /^The previous run was interrupted \(.*weekly usage limit/);
  assert.ok(calls[0].includes("--standalone"), "first attempt carries --standalone");
  assert.ok(calls[1].includes("--standalone"), "resumed call carries --standalone");
});

test("quota with --resume 0 is not nudged; a persistent quota fails after one nudge", () => {
  const noNudge = run({ FAKE_OC_MODE: "text-then-quota", ORCH_RESUME_WAIT_MS: "0", ORCH_RATE_LIMIT_WAIT_MS: "0" }, "--resume", "0");
  assert.equal(noNudge.status, 5, noNudge.stdout);
  assert.deepEqual(JSON.parse(noNudge.stdout.trim()).resumed, []);
  const persistent = run({ FAKE_OC_MODE: "text-then-quota", ORCH_RESUME_WAIT_MS: "0", ORCH_RATE_LIMIT_WAIT_MS: "0" });
  assert.equal(persistent.status, 5, persistent.stdout);
  const receipt = JSON.parse(persistent.stdout.trim());
  assert.equal(receipt.attempts, 2);
  assert.equal(receipt.resumed.length, 1, "one nudge, then the failure stands");
  assert.match(receipt.errors.join("\n"), /weekly usage limit/);
});

// ── --stream: ticket.json preflight ──────────────────────────────────────

test("--stream without ticket.json beside --out is refused with exit 2, no child spawned", () => {
  const { h, sd } = streamHome();
  const runDir = path.join(h, "run");
  fs.mkdirSync(runDir, { recursive: true });
  // deliberately NO ticket.json
  const argsFile = path.join(h, "args.json");
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const out = path.join(runDir, "worker-r1.md");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
  });
  assert.equal(r.status, 2, r.stderr);
  assert.match(r.stderr, new RegExp(`oc-worker: --stream needs ${path.join(runDir, "ticket.json")} beside --out`));
  assert.ok(!fs.existsSync(argsFile), "opencode must not be spawned");
  assert.deepEqual(eventsOf(sd), [], "no queued event appended");
});

// ── --out / --report: caller-cwd resolution ──────────────────────────────

// A tiny fake opencode whose final text has NO status line, but which writes the report file
// given by FAKE_OC_REPORT_PATH with `VERDICT: CHANGES_REQUESTED`. This makes the receipt verdict
// depend on oc-worker reading --report (not on statusLine(sum.final) short-circuiting).
function makeReportFake(dir) {
  const fake = path.join(dir, "fake-report-oc.mjs");
  fs.writeFileSync(fake, `#!/usr/bin/env node\nimport fs from "node:fs";\nconst argv = process.argv.slice(2);\nif (process.env.FAKE_OC_ARGS_FILE) fs.writeFileSync(process.env.FAKE_OC_ARGS_FILE, JSON.stringify({ argv, cwd: process.cwd() }));\nconst rp = process.env.FAKE_OC_REPORT_PATH;\nif (rp) fs.writeFileSync(rp, "VERDICT: CHANGES_REQUESTED\\nagent=critic\\n");\nprocess.stdout.write(JSON.stringify({ type: "text", sessionID: "ses_x", part: { sessionID: "ses_x", messageID: "m", type: "text", text: "findings with no status line" } }) + "\\n");\nprocess.stdout.write(JSON.stringify({ type: "step_finish", part: { type: "step-finish", cost: 0.001 } }) + "\\n");\n`);
  return fake;
}

test("relative --report resolves against the caller's cwd, not the worktree --dir", () => {
  const callerDir = tmp();
  CLEAN.push(callerDir);
  const wtDir = tmp();
  CLEAN.push(wtDir);
  fs.writeFileSync(path.join(wtDir, "mandate.md"), "Review the diff.");
  const fake = makeReportFake(callerDir);
  const reportRel = "report.md";
  const absReport = path.resolve(callerDir, reportRel);
  const out = path.join(callerDir, "out", "worker-r1.md");
  const argsFile = path.join(callerDir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", wtDir, "--prompt", path.join(wtDir, "mandate.md"), "--out", out, "--report", reportRel], {
    env: { ...process.env, OPENCODE_BIN: fake, ORCH_NO_PROCTREE: "1", ORCH_HOME: callerDir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_REPORT_PATH: absReport },
    cwd: callerDir,
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  // statusLine(sum.final) is "" (no status line), so the verdict must come from --report at caller cwd
  assert.equal(receipt.verdict, "VERDICT: CHANGES_REQUESTED", "verdict read from report.md at caller cwd, not from the worktree dir");
  // the report file was written by the agent at the caller's cwd
  assert.ok(fs.existsSync(path.join(callerDir, "report.md")), "agent wrote the report at the caller's cwd");
  assert.equal(fs.readFileSync(path.join(callerDir, "report.md"), "utf8"), "VERDICT: CHANGES_REQUESTED\nagent=critic\n");
  // the agent was told the absolute report path
  const { argv } = JSON.parse(fs.readFileSync(argsFile, "utf8"));
  assert.ok(argv.some((a) => a.includes(`Write your report to ${absReport}`) && a.includes("absolute path; not the worktree")), "prompt names the absolute report path");
});

test("absolute --report is unchanged", () => {
  const callerDir = tmp();
  CLEAN.push(callerDir);
  const wtDir = tmp();
  CLEAN.push(wtDir);
  fs.writeFileSync(path.join(wtDir, "mandate.md"), "Review the diff.");
  const fake = makeReportFake(callerDir);
  const absReport = path.join(callerDir, "abs-report.md");
  const out = path.join(callerDir, "out", "worker-r1.md");
  const argsFile = path.join(callerDir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", wtDir, "--prompt", path.join(wtDir, "mandate.md"), "--out", out, "--report", absReport], {
    env: { ...process.env, OPENCODE_BIN: fake, ORCH_NO_PROCTREE: "1", ORCH_HOME: callerDir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_REPORT_PATH: absReport },
    cwd: callerDir,
    encoding: "utf8",
  });
  assert.equal(r.status, 0, r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.verdict, "VERDICT: CHANGES_REQUESTED", "absolute --report read as-is");
  // the agent was told the absolute report path
  const { argv } = JSON.parse(fs.readFileSync(argsFile, "utf8"));
  assert.ok(argv.some((a) => a.includes(`Write your report to ${absReport}`) && a.includes("absolute path; not the worktree")), "prompt names the absolute report path");
});

// ── landed-work detection (worker-done-detection) ──────────────────────────

function gitRepo(dir) {
  const git = (...args) => {
    const r = spawnSync("git", ["-C", dir, ...args], { encoding: "utf8", timeout: 10000 });
    if (r.status !== 0) throw new Error(`git ${args.join(" ")} failed: ${r.stderr}`);
    return r.stdout.trim();
  };
  git("init", "-b", "main");
  git("config", "user.email", "t@t");
  git("config", "user.name", "t");
  fs.writeFileSync(path.join(dir, "file.txt"), "original\n");
  git("add", "file.txt");
  git("commit", "-m", "init");
  return () => git("rev-parse", "HEAD");
}

// workerRun runs oc-worker against `repo` (a git repo) while mandate/report/out/args live in `artDir`
// (outside the repo), so `git status --porcelain` inside the repo stays clean.
function workerRun(repo, artDir, headBefore, extraEnv, ...flags) {
  const mandate = path.join(artDir, "mandate.md");
  fs.writeFileSync(mandate, "Do the work.");
  const report = path.join(artDir, "report.md");
  const out = path.join(artDir, "out", "worker-r1.md");
  const argsFile = path.join(artDir, "args.json");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", repo, "--prompt", mandate, "--out", out, "--report", report, ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: artDir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_REPORT: report, ...extraEnv },
    encoding: "utf8",
    timeout: 30000,
  });
  return { ...r, repo, artDir, out, report, headBefore };
}

test("landed: timeout after a commit with a clean tree and DONE report -> landed + outcome done", () => {
  const repo = tmp(); const artDir = tmp(); CLEAN.push(repo, artDir);
  const head = gitRepo(repo);
  const headBefore = head();
  const r = workerRun(repo, artDir, headBefore, { FAKE_OC_MODE: "landed" }, "--timeout-min", "0.02", "--grace-min", "0", "--resume", "0");
  assert.equal(r.status, 4, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "timeout");
  assert.ok(receipt.landed, "landed field missing: " + r.stdout);
  assert.equal(receipt.landed.head_before, headBefore);
  assert.notEqual(receipt.landed.head_after, headBefore, "HEAD must have moved");
  assert.equal(receipt.partial, true);
  assert.equal(workerOutcome(receipt), "done");
});

test("landed: timeout with uncommitted changes left -> no landed, outcome stays timeout", () => {
  const repo = tmp(); const artDir = tmp(); CLEAN.push(repo, artDir);
  const head = gitRepo(repo);
  const headBefore = head();
  // Leave the tree dirty: HEAD moves but an untracked file remains after.
  fs.writeFileSync(path.join(repo, "untracked.txt"), "junk\n");
  const r = workerRun(repo, artDir, headBefore, { FAKE_OC_MODE: "landed" }, "--timeout-min", "0.02", "--grace-min", "0", "--resume", "0");
  assert.equal(r.status, 4);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "timeout");
  assert.equal(receipt.landed, undefined, "dirty tree must not count as landed");
  assert.equal(workerOutcome(receipt), "timeout");
});

test("landed: timeout with HEAD unchanged -> no landed, outcome stays timeout", () => {
  const repo = tmp(); const artDir = tmp(); CLEAN.push(repo, artDir);
  const head = gitRepo(repo);
  const headBefore = head();
  // hang-after-text produces output but never commits: HEAD unchanged.
  const r = workerRun(repo, artDir, headBefore, { FAKE_OC_MODE: "hang-after-text" }, "--timeout-min", "0.02", "--grace-min", "0", "--resume", "0");
  assert.equal(r.status, 4);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "timeout");
  assert.equal(receipt.landed, undefined, "unchanged HEAD must not count as landed");
  assert.equal(workerOutcome(receipt), "timeout");
});

test("landed: timeout with report not DONE -> no landed, outcome stays timeout", () => {
  const repo = tmp(); const artDir = tmp(); CLEAN.push(repo, artDir);
  const head = gitRepo(repo);
  const headBefore = head();
  // Pre-write a non-DONE report; the landed fixture won't clobber an existing report.
  fs.writeFileSync(path.join(artDir, "report.md"), "RESULT: NOT DONE\n");
  const r = workerRun(repo, artDir, headBefore, { FAKE_OC_MODE: "landed" }, "--timeout-min", "0.02", "--grace-min", "0", "--resume", "0");
  assert.equal(r.status, 4);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "timeout");
  assert.equal(receipt.landed, undefined, "non-DONE report must not count as landed");
  assert.equal(workerOutcome(receipt), "timeout");
});

// ── grace (worker-done-detection) ──────────────────────────────────────────

test("grace: output in the last 5 minutes extends the deadline once and the run finishes", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const mandate = path.join(dir, "mandate.md");
  fs.writeFileSync(mandate, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", mandate, "--out", out, "--timeout-min", "0.02", "--grace-min", "0.1", "--resume", "0"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "grace-ok", FAKE_OC_DELAY: "1500" },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, 0);
  assert.equal(receipt.extended_min, 0.1, "grace extension not recorded: " + r.stdout);
  const outText = fs.readFileSync(out, "utf8");
  assert.match(outText, /grace work/);
});

test("grace: silent run is killed at the deadline, no extension", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const r = run({ FAKE_OC_MODE: "hang" }, "--timeout-min", "0.02", "--grace-min", "0.1", "--resume", "0");
  assert.equal(r.status, 4);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "timeout");
  assert.equal(receipt.extended_min, undefined, "silent run must not be extended");
});

test("sleep: a host sleep (SIGSTOP) past the original deadline extends it and records slept_ms", { skip: process.platform !== "linux", timeout: 90000 }, async () => {
  const dir = tmp();
  CLEAN.push(dir);
  const mandate = path.join(dir, "mandate.md");
  fs.writeFileSync(mandate, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const argsFile = path.join(dir, "args.json");
  const timeoutMin = 0.1; // 6 s original deadline
  const originalDeadlineMs = timeoutMin * 60000;
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", mandate, "--out", out, "--timeout-min", String(timeoutMin), "--grace-min", "0", "--resume", "0"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "hang" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const start = Date.now();
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal, at: Date.now() - start })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 90000);
  try {
    for (let i = 0; i < 100 && !fs.existsSync(argsFile); i++) await sleep(100);
    assert.ok(fs.existsSync(argsFile), "the fake agent started");
    await sleep(300); // let the watchdog arm its deadline timer
    // Freeze oc-worker's own event loop past the 30 s sleep threshold and past the original deadline.
    process.kill(child.pid, "SIGSTOP");
    await sleep(36_000);
    process.kill(child.pid, "SIGCONT");
    const { code, at } = await exited;
    clearTimeout(hard);
    // It must not have died at the original deadline (it was frozen then); it ends later.
    assert.ok(at > originalDeadlineMs + 20_000, `ended at ${at} ms, not past the original deadline ${originalDeadlineMs} ms`);
    const receipt = JSON.parse(fs.readFileSync(out + ".receipt.json", "utf8"));
    assert.ok(receipt.slept_ms > 0, `slept_ms must be > 0, got ${receipt.slept_ms}`);
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { process.kill(child.pid, "SIGCONT"); } catch {} } // resume before kill
    if (child.exitCode === null) { try { process.kill(child.pid, "SIGKILL"); } catch {} }
  }
});

test("grace: --grace-min 0 disables the extension", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const mandate = path.join(dir, "mandate.md");
  fs.writeFileSync(mandate, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", mandate, "--out", out, "--timeout-min", "0.02", "--grace-min", "0", "--resume", "0"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "grace-ok", FAKE_OC_DELAY: "1500" },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 4, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.exit, "timeout");
  assert.equal(receipt.extended_min, undefined, "grace-min 0 must not extend");
});

// ---------------------------------------------------------------- sleep-aware deadline

test("sleepGapMs: sleeps return the gap minus one tick; normal ticks return 0", () => {
  const now = 1_000_000_000_000;
  const tickMs = 5000;
  // a 10-minute tick gap: the host slept ~10 min, give back gap minus the one tick
  assert.equal(sleepGapMs(now - 10 * 60 * 1000, now, tickMs), 10 * 60 * 1000 - tickMs);
  // a normal 5 s tick: no sleep
  assert.equal(sleepGapMs(now - tickMs, now, tickMs), 0);
  // a gap smaller than a tick: no sleep
  assert.equal(sleepGapMs(now - 1000, now, tickMs), 0);
  // a 30 s gap (the watchdog's sleep threshold): 25 s given back
  assert.equal(sleepGapMs(now - 30_000, now, tickMs), 25_000);
});

test("sleep: a run with no host sleep has receipt slept_ms 0", () => {
  const r = run({});
  assert.equal(r.status, 0, r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.slept_ms, 0, "no sleep: slept_ms must be 0: " + r.stdout);
});

test("sleep: no real suspend -> killed at the original deadline, slept_ms 0", () => {
  // A real suspend would need a live host suspend; runWorker's watchdog uses real Date.now(),
  // so no sleep occurs here and the run dies at its original deadline with slept_ms 0.
  const state = tmp();
  CLEAN.push(state);
  const mandate = path.join(state, "mandate.md");
  fs.writeFileSync(mandate, "Do the work.");
  const out = path.join(state, "out", "worker-r1.md");
  const argsFile = path.join(state, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", state, "--prompt", mandate, "--out", out, "--timeout-min", "0.02", "--grace-min", "0", "--resume", "0"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: state, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "hang-after-text" },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 4, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.slept_ms, 0, "no sleep: slept_ms must be 0: " + r.stdout);
  assert.equal(receipt.exit, "timeout");
});

// sleepExtensionMs: the capped extension the watchdog applies, pure and clock-free.
test("sleepExtensionMs: a 10-minute sleep gap is given back minus one tick, capped at 2 h", () => {
  const capMs = 2 * 60 * 60 * 1000;
  // The watchdog already subtracted one tick via sleepGapMs; sleepExtensionMs just caps the remainder.
  const slept = 10 * 60 * 1000 - 5000;
  const first = sleepExtensionMs(0, slept, capMs);
  assert.equal(first.add, slept, "first sleep gap extended by the already-tick-subtracted slept time");
  assert.equal(first.total, slept, "total equals the add on the first sleep");
  // A second sleep pushes total toward but not past the cap.
  const second = sleepExtensionMs(first.total, slept, capMs);
  assert.equal(second.total, first.total + second.add, "total accumulates");
  assert.ok(second.add > 0, "room remains for a second sleep");
  // Fill the rest of the cap in one go: add should equal the remaining room exactly.
  const room = capMs - second.total;
  const filled = sleepExtensionMs(second.total, room + 1_000_000_000, capMs);
  assert.equal(filled.add, room, "add equals remaining room when the gap exceeds it");
  assert.equal(filled.total, capMs, "total reaches the cap exactly");
  // Beyond the cap: no further extension.
  const over = sleepExtensionMs(capMs, 3 * 60 * 60 * 1000, capMs);
  assert.equal(over.add, 0, "cap exhausted: a 3 h gap adds nothing");
  assert.equal(over.total, capMs, "total stays at the cap");
});

// sleepGapMs itself is uncapped: a raw 3 h gap is returned as-is; runWorker caps the accumulated
// extension via sleepExtensionMs (see the :1735 test).
test("sleepGapMs: a raw 3 h gap is returned uncapped; runWorker caps total via sleepExtensionMs", () => {
  const now = 1_000_000_000_000;
  const threeHoursMs = 3 * 60 * 60 * 1000;
  assert.ok(sleepGapMs(now - threeHoursMs, now, 5000) > 2 * 60 * 60 * 1000, "raw 3 h gap is returned uncapped");
});

// ---------------------------------------------------------------- small-edit footer

test("worker footer: a worker-role run's prompt carries the small-edit line", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", path.join(dir, "out", "worker-r1.md")], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stderr);
  const { argv } = JSON.parse(fs.readFileSync(argsFile, "utf8"));
  const message = argv.at(-1);
  assert.ok(message.includes("small pieces"), "worker prompt has the small-edit line: " + message);
  assert.ok(message.includes("8k output tokens"), "worker prompt names the output-token cap: " + message);
});

test("worker footer: read-only roles (critic, senior, scout) do not get the small-edit line", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  for (const agent of ["critic", "senior", "scout"]) {
    const argsFile = path.join(dir, `${agent}-args.json`);
    const r = spawnSync(process.execPath, [BIN, "--agent", agent, "--dir", dir, "--prompt", prompt, "--out", path.join(dir, `out-${agent}.md`)], {
      env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile },
      encoding: "utf8",
      timeout: 30000,
    });
    assert.equal(r.status, 0, `${agent}: ${r.stderr}`);
    const { argv } = JSON.parse(fs.readFileSync(argsFile, "utf8"));
    const message = argv.at(-1);
    assert.ok(!message.includes("small pieces"), `${agent} prompt must not carry the small-edit line: ${message}`);
    assert.ok(!message.includes("8k output tokens"), `${agent} prompt must not name the output-token cap: ${message}`);
  }
});

// ---------------------------------------------------------------- truncation-aware resume

test("resumableReason: output-token truncation is its own 'truncated' reason", () => {
  assert.equal(resumableReason(["Response still truncated after two output token limit continuations"]), "truncated");
  assert.equal(resumableReason(["the model output exceeded the output token limit"]), "truncated");
  assert.equal(resumableReason(["read ECONNRESET"]), "dropped");
});

test("truncation resume: the resume message tells the worker to split edits; ECONNRESET does not", () => {
  const truncState = tmp(); CLEAN.push(truncState);
  const truncFake = path.join(truncState, "fake-truncate-oc.mjs");
  fs.writeFileSync(truncFake, `#!/usr/bin/env node\nimport fs from "node:fs";\nimport path from "node:path";\nconst argv = process.argv.slice(2);\nconst session = "ses_trunc";\nconst state = process.env.FAKE_OC_STATE_DIR;\nif (state) { fs.mkdirSync(state, { recursive: true }); fs.appendFileSync(path.join(state, "calls.jsonl"), JSON.stringify({ argv, cwd: process.cwd() }) + "\\n"); }\nif (process.env.FAKE_OC_ARGS_FILE) fs.writeFileSync(process.env.FAKE_OC_ARGS_FILE, JSON.stringify({ argv, cwd: process.cwd() }));\nconst counter = path.join(state, "trunc-count");\nlet n = 0;\ntry { n = Number(fs.readFileSync(counter, "utf8")) || 0; } catch {}\nfs.writeFileSync(counter, String(n + 1));\nconst ev = (type, part) => process.stdout.write(JSON.stringify({ type, sessionID: session, part: { sessionID: session, messageID: "m", ...part } }) + "\\n");\nif (n === 0) {\n  ev("text", { type: "text", text: "some work\\n" });\n  ev("error", { type: "error", error: { name: "UnknownError", message: "Response still truncated after two output token limit continuations" } });\n  process.exit(1);\n} else {\n  ev("text", { type: "text", text: "RESULT: DONE\\ntruncated recovery done\\n" });\n  ev("step_finish", { type: "step-finish", cost: 0.001 });\n  process.exit(0);\n}\n`);
  fs.writeFileSync(path.join(truncState, "mandate.md"), "Do the work.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", truncState, "--prompt", path.join(truncState, "mandate.md"), "--out", path.join(truncState, "out", "worker-r1.md")], {
    env: { ...process.env, OPENCODE_BIN: truncFake, ORCH_NO_PROCTREE: "1", ORCH_HOME: truncState, FAKE_OC_STATE_DIR: truncState, ORCH_RESUME_WAIT_MS: "0", FAKE_OC_ARGS_FILE: path.join(truncState, "args.json") },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.resumed.length, 1, `expected one truncation resume, got ${JSON.stringify(receipt.resumed)}`);
  assert.equal(receipt.resumed[0].reason, "output token limit", `truncation resume reason: ${JSON.stringify(receipt.resumed)}`);
  const calls = fs.readFileSync(path.join(truncState, "calls.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.equal(calls.length, 2, "first (truncated) call plus one resumed call");
  const resumedMsg = calls[1].argv[calls[1].argv.length - 1];
  assert.ok(resumedMsg.includes("split the remaining edit into smaller pieces"), "truncation resume message must tell the worker to split edits: " + resumedMsg);

  // negative: a plain ECONNRESET drop is resumed with the ordinary message, no split line
  const ecState = tmp(); CLEAN.push(ecState);
  const dropFake = path.join(ecState, "fake-drop-oc.mjs");
  fs.writeFileSync(dropFake, `#!/usr/bin/env node\nimport fs from "node:fs";\nimport path from "node:path";\nconst argv = process.argv.slice(2);\nconst session = "ses_drop";\nconst state = process.env.FAKE_OC_STATE_DIR;\nif (state) { fs.mkdirSync(state, { recursive: true }); fs.appendFileSync(path.join(state, "calls.jsonl"), JSON.stringify({ argv, cwd: process.cwd() }) + "\\n"); }\nif (process.env.FAKE_OC_ARGS_FILE) fs.writeFileSync(process.env.FAKE_OC_ARGS_FILE, JSON.stringify({ argv, cwd: process.cwd() }));\nconst counter = path.join(state, "drop-count");\nlet n = 0;\ntry { n = Number(fs.readFileSync(counter, "utf8")) || 0; } catch {}\nfs.writeFileSync(counter, String(n + 1));\nconst ev = (type, part) => process.stdout.write(JSON.stringify({ type, sessionID: session, part: { sessionID: session, messageID: "m", ...part } }) + "\\n");\nif (n === 0) {\n  ev("text", { type: "text", text: "some work\\n" });\n  ev("error", { type: "error", error: { name: "UnknownError", message: "read ECONNRESET" } });\n  process.exit(1);\n} else {\n  ev("text", { type: "text", text: "RESULT: DONE\\ndrop recovery done\\n" });\n  ev("step_finish", { type: "step-finish", cost: 0.001 });\n  process.exit(0);\n}\n`);
  fs.writeFileSync(path.join(ecState, "mandate.md"), "Do the work.");
  const r2 = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", ecState, "--prompt", path.join(ecState, "mandate.md"), "--out", path.join(ecState, "out", "worker-r1.md")], {
    env: { ...process.env, OPENCODE_BIN: dropFake, ORCH_NO_PROCTREE: "1", ORCH_HOME: ecState, FAKE_OC_STATE_DIR: ecState, ORCH_RESUME_WAIT_MS: "0", FAKE_OC_ARGS_FILE: path.join(ecState, "args.json") },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r2.status, 0, r2.stdout + r2.stderr);
  const receipt2 = JSON.parse(r2.stdout.trim());
  assert.equal(receipt2.resumed.length, 1, "drop resumes once");
  const calls2 = fs.readFileSync(path.join(ecState, "calls.jsonl"), "utf8").trim().split("\n").map((l) => JSON.parse(l));
  assert.equal(calls2.length, 2, "first (dropped) call plus one resumed call");
  const droppedMsg = calls2[calls2.length - 1].argv[calls2[calls2.length - 1].argv.length - 1];
  assert.ok(!droppedMsg.includes("split the remaining edit into smaller pieces"), "ECONNRESET resume must not carry the split line: " + droppedMsg);
  assert.ok(!droppedMsg.includes("output token limit"), "ECONNRESET resume must not mention the output cap: " + droppedMsg);
});

test("--stream queued event carries slots (queue-time snapshot)", () => {
  const { h, sd } = streamHome();
  const r = streamRun(h, {}, "worker-r1.md");
  assert.equal(r.status, 0, r.stderr);
  const ev = eventsOf(sd);
  const queued = ev.find((e) => e.kind === "queued");
  assert.ok(queued, "queued event present");
  assert.equal(typeof queued.slots, "string", "slots field present");
  assert.match(queued.slots, /^slots \d+\/\d+ /, "slots reason text");
});

test("nice 10: prio is exported and the spawn path calls prio.set(child.pid, 10) on non-win32", () => {
  if (process.platform === "win32") return; // Windows unchanged: no priority call
  assert.ok(prio && typeof prio.set === "function", "prio.set exported and callable");
  const src = fs.readFileSync(BIN, "utf8");
  assert.ok(/os\.setPriority\(pid,\s*n\)/.test(src), "calls os.setPriority(pid, n)");
  assert.ok(/prio\.set\(child\.pid,\s*10\)/.test(src), "spawn path calls prio.set(child.pid, 10)");
  assert.ok(
    /process\.platform\s*!==\s*"win32"/.test(src) || /process\.platform\s*!==\s*'win32'/.test(src),
    "gated on non-win32",
  );
  assert.ok(/catch\s*\{/.test(src), "wrapped in try/catch (never fails the run)");
});

test("nice 10: a normal run succeeds (niceness set, never fails the run)", () => {
  if (process.platform === "win32") return;
  const r = run({});
  assert.equal(r.status, 0, r.stderr);
});

// --- provider-removed: a model missing from `opencode models` is skipped before a spawn and costs no attempt.
// Five agents on five providers (a quota hit takes the whole provider down). a1's model is absent; a2 and a3 hit a
// quota; a4 answers. The 3-attempt cap lets a4 run only if the absent hop used no attempt (a1, a2, a3 would be 3).
function chainHome() {
  const h = tmp();
  CLEAN.push(h);
  const agents = path.join(h, ".config", "opencode", "agents");
  fs.mkdirSync(agents, { recursive: true });
  for (const n of ["a1", "a2", "a3", "a4", "a5"]) fs.writeFileSync(path.join(agents, `${n}.md`), `---\ndescription: x\nmode: subagent\nmodel: p${n[1]}/m\n---\nbody\n`);
  return h;
}
function runChainFixture(h, env) {
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = spawnSync(process.execPath, [BIN, "--agent", "a1", "--fallback", "a2,a3,a4,a5", "--dir", h, "--prompt", prompt, "--out", path.join(h, "out", "r1.md")], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_MODE: "quota-a2,a3", ...env },
    encoding: "utf8",
    timeout: 60000,
  });
  return { ...r, receipt: r.stdout.trim() ? JSON.parse(r.stdout.trim()) : null };
}

test("runChain: a model absent from opencode models is skipped with no spawn and no attempt counted", () => {
  const h = chainHome();
  const list = path.join(h, "models.txt");
  fs.writeFileSync(list, ["p2/m", "p3/m", "p4/m", "p5/m"].join("\n"));
  const r = runChainFixture(h, { ORCH_OPENCODE_MODELS_FILE: list });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(r.receipt.agent, "a4", "a4 is reached: the absent hop was not one of the 3 attempts");
  const hops = r.receipt.repooled_from;
  assert.deepEqual(hops.map((x) => x.agent), ["a1", "a2", "a3"]);
  assert.equal(hops[0].skipped, true);
  assert.match(hops[0].reason, /^absent: not in opencode models/);
  assert.ok(!hops[1].skipped, "a2 was really spawned");
});

test("runChain: the real listing path (opencode models) skips an absent model and caches the list", () => {
  const h = chainHome();
  const r = runChainFixture(h, { FAKE_OC_MODELS: "p2/m,p3/m,p4/m,p5/m" });
  assert.equal(r.receipt.agent, "a4", r.stdout + r.stderr);
  assert.match(r.receipt.repooled_from[0].reason, /^absent/);
  const cache = JSON.parse(fs.readFileSync(path.join(h, ".config", "orchestrator", "opencode-models.json"), "utf8"));
  assert.ok(cache.models.includes("p5/m"));
});

test("runChain: when the models listing fails nothing is filtered (fail open)", () => {
  const h = chainHome();
  const r = runChainFixture(h, { FAKE_OC_MODE: "ok", FAKE_OC_MODELS_FAIL: "1" });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  assert.equal(r.receipt.agent, "a1", "a1 ran: nothing was filtered");
  assert.equal(r.receipt.repooled_from, undefined, "nothing recorded");
});

test("runChain: every hop absent returns no-healthy-pool naming the absent models", () => {
  const h = chainHome();
  const list = path.join(h, "models.txt");
  fs.writeFileSync(list, "other/model\n");
  const r = runChainFixture(h, { ORCH_OPENCODE_MODELS_FILE: list });
  assert.equal(r.status, 6, r.stdout + r.stderr);
  assert.equal(r.receipt.exit, "no-healthy-pool");
  assert.match(r.receipt.errors[0], /absent from opencode models/);
  assert.doesNotMatch(r.receipt.errors[0], /known-down/);
  assert.match(r.receipt.errors.join("\n"), /p1\/m/);
  assert.match(r.receipt.errors.join("\n"), /p5\/m/);
});

test("chains: no chain names a removed agent, and every chain agent has an agent file", () => {
  const removed = ["worker-burst", "worker-alt", "critic-alt", "senior-alt", "orchestrator-alt"];
  for (const [role, chain] of Object.entries(CHAINS)) {
    for (const agent of chain) {
      assert.ok(!removed.includes(agent), `${role} names removed agent ${agent}`);
      assert.ok(fs.existsSync(path.join(HERE, "..", "agents", `${agent}.md`)), `${role}: agents/${agent}.md exists`);
    }
  }
  assert.ok(!Object.values(CHAINS).flat().some((a) => /alt$|burst$/.test(a)));
});

test("runChain: a fresh models cache is used without spawning opencode models; a stale one is refetched", () => {
  const cacheOf = (h) => path.join(h, ".config", "orchestrator", "opencode-models.json");
  const put = (h, at, models) => {
    fs.mkdirSync(path.dirname(cacheOf(h)), { recursive: true });
    fs.writeFileSync(cacheOf(h), JSON.stringify({ at: new Date(at).toISOString(), models }));
  };
  // fresh cache lacks p1/m; the fake would list it (and fail if asked at all): the cache wins, so a1 is skipped
  const fresh = chainHome();
  put(fresh, Date.now() - 60_000, ["p2/m", "p3/m", "p4/m", "p5/m"]);
  const f = runChainFixture(fresh, { FAKE_OC_MODELS_FAIL: "1" });
  assert.equal(f.receipt.agent, "a4", f.stdout + f.stderr);
  assert.match(f.receipt.repooled_from[0].reason, /^absent/);
  // stale cache (11 min old) lacks p1/m, the live listing has it: refetched, a1 runs, cache rewritten
  const stale = chainHome();
  put(stale, Date.now() - 11 * 60_000, ["p2/m", "p3/m", "p4/m", "p5/m"]);
  const s = runChainFixture(stale, { FAKE_OC_MODE: "ok", FAKE_OC_MODELS: "p1/m,p2/m" });
  assert.equal(s.receipt.agent, "a1", s.stdout + s.stderr);
  assert.ok(JSON.parse(fs.readFileSync(cacheOf(stale), "utf8")).models.includes("p1/m"), "cache refreshed");
});

test("runChain: an explicit --model on hop 1 is the model checked against the list", () => {
  const h = chainHome();
  const list = path.join(h, "models.txt");
  fs.writeFileSync(list, ["p1/m", "p2/m", "p3/m", "p4/m", "p5/m"].join("\n"));
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "x");
  const r = spawnSync(process.execPath, [BIN, "--agent", "a1", "--model", "gone/explicit", "--fallback", "a2", "--dir", h, "--prompt", prompt, "--out", path.join(h, "out", "r1.md")], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, ORCH_OPENCODE_MODELS_FILE: list },
    encoding: "utf8",
    timeout: 60000,
  });
  const rec = JSON.parse(r.stdout.trim());
  assert.equal(rec.agent, "a2", r.stdout + r.stderr);
  assert.equal(rec.repooled_from[0].model, "gone/explicit");
  assert.match(rec.repooled_from[0].reason, /^absent/);
});

// ---- Nvidia provider slot (ticket nvidia-throttle) ----------------------------------------------------------
// Runs are launched on the nvidia/ model via --model; the fake's grace-ok mode holds a run for FAKE_OC_DELAY ms.
function startNvidia(home, name, { delay = 600, extraEnv = {}, flags = [], model = "nvidia/test-model" } = {}) {
  const dir = path.join(home, name);
  fs.mkdirSync(dir, { recursive: true });
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const argsFile = path.join(dir, "args.json");
  const out = path.join(dir, "out", "findings.md");
  const env = { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: home, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "grace-ok", FAKE_OC_DELAY: String(delay), ORCH_NVIDIA_POLL_MS: "50", ...extraEnv };
  delete env.NVIDIA_SLOTS;
  Object.assign(env, extraEnv);
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", out, "--model", model, ...flags], { env, stdio: ["ignore", "pipe", "pipe"] });
  let stdout = "";
  child.stdout.on("data", (d) => (stdout += d));
  const killer = setTimeout(() => child.kill("SIGKILL"), 30000); // every child has a timeout
  const done = new Promise((resolve) => child.on("close", (code) => { clearTimeout(killer); resolve({ code, stdout, endedAt: Date.now(), argsFile, out }); }));
  return { done, argsFile, started: () => fs.existsSync(argsFile) && fs.statSync(argsFile).mtimeMs };
}
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

test("nvidia slot: NVIDIA_SLOTS=1 (fixed) runs two nvidia runs one after the other", async () => {
  const home = tmp();
  CLEAN.push(home);
  const a = startNvidia(home, "a", { extraEnv: { NVIDIA_SLOTS: "1" } });
  await sleep(250); // a is running (its fake started and is holding for 600 ms)
  const b = startNvidia(home, "b", { extraEnv: { NVIDIA_SLOTS: "1" } });
  const [ra, rb] = await Promise.all([a.done, b.done]);
  assert.equal(ra.code, 0);
  assert.equal(rb.code, 0);
  const aStart = fs.statSync(ra.argsFile).mtimeMs;
  const bStart = fs.statSync(rb.argsFile).mtimeMs;
  assert.ok(bStart >= aStart + 600, `b's first spawn (${bStart - aStart} ms after a's) must come after a's exit (a holds 600 ms)`);
  assert.deepEqual(fs.readdirSync(slotDir_(home)).filter((n) => /^provider-nvidia-\d/.test(n)), [], "the provider slot is released");
});
function slotDir_(home) {
  return path.join(home, ".config", "orchestrator", "slots");
}

test("nvidia slot: NVIDIA_SLOTS=2 lets two nvidia runs overlap; a non-nvidia run never waits on a held slot", async () => {
  const home = tmp();
  CLEAN.push(home);
  const a = startNvidia(home, "a", { delay: 1500, extraEnv: { NVIDIA_SLOTS: "2" } });
  const b = startNvidia(home, "b", { delay: 1500, extraEnv: { NVIDIA_SLOTS: "2" } });
  await sleep(700);
  assert.ok(a.started() && b.started(), "both nvidia runs are running at once under NVIDIA_SLOTS=2");
  await Promise.all([a.done, b.done]);

  // cap 1, one nvidia run holding: a run on a non-nvidia model starts at once
  const h2 = tmp();
  CLEAN.push(h2);
  const holder = startNvidia(h2, "holder", { delay: 1500, extraEnv: { NVIDIA_SLOTS: "1" } });
  await sleep(500);
  assert.ok(holder.started());
  const other = startNvidia(h2, "other", { delay: 100, model: "opencode/other-model", extraEnv: { NVIDIA_SLOTS: "1" } });
  await sleep(700);
  assert.ok(other.started(), "a non-nvidia run starts while the nvidia slot is held");
  const blocked = startNvidia(h2, "blocked", { delay: 100, extraEnv: { NVIDIA_SLOTS: "1" } });
  await sleep(400);
  assert.ok(!blocked.started(), "a second nvidia run waits while the single slot is held");
  await blocked.done;
  const ro = await other.done;
  const rh = await holder.done;
  assert.equal(ro.code, 0);
  assert.ok(ro.endedAt < rh.endedAt, "the non-nvidia run finished before the nvidia holder");
});

test("nvidia slot: a slot whose owner pid is dead is reclaimed; a live one is not", async () => {
  const savedHome = process.env.ORCH_HOME;
  process.env.ORCH_HOME = tmp();
  CLEAN.push(process.env.ORCH_HOME);
  const { acquireProviderSlot } = await import("../bin/oc-worker.mjs");
  assert.equal(typeof acquireProviderSlot, "function");
  // a pid that is certainly dead: a short-lived child we started and waited for
  const child = spawn(process.execPath, ["-e", "0"], { stdio: "ignore" });
  const killer = setTimeout(() => child.kill("SIGKILL"), 10000);
  await new Promise((r) => child.on("close", r));
  clearTimeout(killer);
  const deadPid = child.pid;
  const d = path.join(slotDir(), "provider-nvidia-1");
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, "owner"), JSON.stringify({ pid: deadPid, since: new Date().toISOString() }));
  const got = await acquireProviderSlot("nvidia", 1, { pollMs: 20 });
  assert.equal(got.index, 1);
  assert.equal(JSON.parse(fs.readFileSync(path.join(d, "owner"), "utf8")).pid, process.pid, "the dead owner's slot is now ours");
  // we are alive: a second claimant times out rather than stealing
  let second = "claimed";
  const waiting = acquireProviderSlot("nvidia", 1, { pollMs: 20 }).then(() => (second = "stole"));
  await sleep(200);
  assert.equal(second, "claimed");
  got.release();
  await waiting; // released: the waiter gets it
  fs.rmSync(path.join(slotDir(), "provider-nvidia-1"), { recursive: true, force: true });
  if (savedHome === undefined) delete process.env.ORCH_HOME;
  else process.env.ORCH_HOME = savedHome;
});

test("nvidia cap: admission is by live-holder count, not slot index (cap 1, slots 2 and 3 held, slot 1 free)", async () => {
  const savedHome = process.env.ORCH_HOME;
  const savedSlots = process.env.NVIDIA_SLOTS;
  process.env.ORCH_HOME = tmp();
  CLEAN.push(process.env.ORCH_HOME);
  delete process.env.NVIDIA_SLOTS;
  try {
    const { acquireProviderSlot } = await import("../bin/oc-worker.mjs");
    const { nvidiaCapNow, recordNvidia429 } = await import("../bin/slots.mjs");
    fs.mkdirSync(slotDir(), { recursive: true });
    recordNvidia429(slotDir()); // a 429 just now: cap 1
    const holders = [spawn(process.execPath, ["-e", "setTimeout(()=>{}, 20000)"], { stdio: "ignore" }), spawn(process.execPath, ["-e", "setTimeout(()=>{}, 20000)"], { stdio: "ignore" })];
    try {
      [2, 3].forEach((i, k) => {
        const d = path.join(slotDir(), `provider-nvidia-${i}`);
        fs.mkdirSync(d);
        fs.writeFileSync(path.join(d, "owner"), JSON.stringify({ pid: holders[k].pid, since: new Date(Date.now() - 5000).toISOString() }));
      });
      assert.equal(nvidiaCapNow(slotDir()).cap, 1);
      let got = null;
      const waiting = acquireProviderSlot("nvidia", () => nvidiaCapNow(slotDir()).cap, { pollMs: 20 }).then((g) => (got = g));
      await sleep(300);
      assert.equal(got, null, "a new run waits: 2 live holders >= cap 1, even though slot 1 is free");
      fs.rmSync(path.join(slotDir(), "provider-nvidia-2"), { recursive: true, force: true });
      await sleep(200);
      assert.equal(got, null, "one holder left, still >= cap 1");
      fs.rmSync(path.join(slotDir(), "provider-nvidia-3"), { recursive: true, force: true });
      await waiting;
      assert.ok(got, "admitted once live holders < cap");
      got.release();
    } finally {
      for (const h of holders) h.kill("SIGKILL");
    }
  } finally {
    if (savedHome === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = savedHome;
    if (savedSlots !== undefined) process.env.NVIDIA_SLOTS = savedSlots;
  }
});

test("nvidia cap: simultaneous claimants never exceed the cap and never all back off", async () => {
  const savedHome = process.env.ORCH_HOME;
  process.env.ORCH_HOME = tmp();
  CLEAN.push(process.env.ORCH_HOME);
  try {
    const { acquireProviderSlot } = await import("../bin/oc-worker.mjs");
    const claims = await Promise.all([1, 2, 3, 4, 5].map(() => acquireProviderSlot("nvidia", 2, { pollMs: 10, deadline: Date.now() + 500 }).catch(() => null)));
    const won = claims.filter(Boolean);
    assert.equal(won.length, 2, "exactly the cap is admitted");
    for (const w of won) w.release();
  } finally {
    if (savedHome === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = savedHome;
  }
});

test("nvidia slot: the queued event and the receipt name the slot", async () => {
  const { h: home, sd } = streamHome();
  const dir = path.join(home, "w");
  fs.mkdirSync(path.join(dir, "run"), { recursive: true });
  fs.writeFileSync(path.join(dir, "mandate.md"), "Do the thing.");
  fs.writeFileSync(path.join(dir, "run", "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: dir }));
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", path.join(dir, "mandate.md"), "--out", path.join(dir, "run", "c.md"), "--stream", "m6a", "--model", "nvidia/test-model"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: home, ORCH_NVIDIA_POLL_MS: "50", NVIDIA_SLOTS: "1" },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const queued = eventsOf(sd).find((e) => e.kind === "queued");
  assert.match(queued.slots, /nvidia 0\/1/);
  assert.equal(JSON.parse(r.stdout.trim()).provider_slot, "nvidia 1/1");
});

test("resume wait: a mid-run 429 waits ORCH_RATE_LIMIT_WAIT_MS; a mid-run drop waits only ORCH_RESUME_WAIT_MS", () => {
  const timed = (mode, extra) => {
    const state = tmp();
    CLEAN.push(state);
    const t0 = Date.now();
    const r = run({ FAKE_OC_MODE: mode, FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "10", ORCH_RATE_LIMIT_WAIT_MS: "1500", ...extra });
    return { r, ms: Date.now() - t0 };
  };
  const quota = timed("midrun-quota-once");
  assert.equal(quota.r.status, 0, quota.r.stdout + quota.r.stderr);
  assert.equal(JSON.parse(quota.r.stdout.trim()).attempts, 2);
  assert.ok(quota.ms >= 1500, `a 429 resume waited ${quota.ms} ms, wanted at least ORCH_RATE_LIMIT_WAIT_MS (1500)`);
  const drop = timed("drop-once");
  assert.equal(drop.r.status, 0, drop.r.stdout + drop.r.stderr);
  assert.equal(JSON.parse(drop.r.stdout.trim()).attempts, 2);
  assert.ok(drop.ms < 1500, `a drop resume took ${drop.ms} ms, must wait only ORCH_RESUME_WAIT_MS (10)`);
  // the larger of the two wins: a resume wait above the rate-limit wait is kept
  const big = timed("midrun-quota-once", { ORCH_RESUME_WAIT_MS: "1800", ORCH_RATE_LIMIT_WAIT_MS: "10" });
  assert.ok(big.ms >= 1800);
});

test("nvidia slot: waiting for the slot does not consume --timeout-min", async () => {
  const home = tmp();
  CLEAN.push(home);
  const a = startNvidia(home, "a", { delay: 2000, extraEnv: { NVIDIA_SLOTS: "1" } });
  await sleep(500);
  // --timeout-min 0.03 = 1.8 s: shorter than the 1.5+ s wait plus its own 700 ms run, longer than the run alone
  const b = startNvidia(home, "b", { delay: 700, extraEnv: { NVIDIA_SLOTS: "1" }, flags: ["--timeout-min", "0.03", "--grace-min", "0"] });
  const [ra, rb] = await Promise.all([a.done, b.done]);
  assert.equal(ra.code, 0);
  assert.equal(rb.code, 0, "b was not timed out while it waited for the slot");
  const receipt = JSON.parse(fs.readFileSync(rb.out + ".receipt.json", "utf8"));
  assert.notEqual(receipt.exit, "timeout");
  assert.ok(fs.statSync(rb.argsFile).mtimeMs >= fs.statSync(ra.argsFile).mtimeMs + 2000, "b ran after a finished, so it did wait");
  assert.ok(receipt.seconds <= 2, `b's clock started after the wait (${receipt.seconds} s)`);
});

// ---- adaptive cap (round 2) ---------------------------------------------------------------------------------
// startNvidia deletes NVIDIA_SLOTS and runs under a temp ORCH_HOME, so neither the slot dir nor the 429 state
// file of this machine can leak in.
test("nvidia cap: no recent 429 and NVIDIA_SLOTS unset admits 3 at once; a 4th waits", async () => {
  const home = tmp();
  CLEAN.push(home);
  const runs = [1, 2, 3, 4].map((i) => startNvidia(home, `r${i}`, { delay: 4000, extraEnv: { WORKER_SLOTS: "6" } }) /* machine cap out of the way */);
  for (let i = 0; i < 60 && runs.filter((r) => r.started()).length < 3; i++) await sleep(100); // a loaded host starts slowly
  await sleep(300); // the fourth has had its chance
  assert.equal(runs.filter((r) => r.started()).length, 3, "exactly three nvidia runs are admitted");
  assert.equal(runs.filter((r) => !r.started()).length, 1, "the fourth run waits (which one is last is a race)");
  const results = await Promise.all(runs.map((r) => r.done));
  assert.ok(results.every((r) => r.code === 0));
});

test("nvidia cap: a 429 inside the cooldown caps new admissions at 1", async () => {
  const home = tmp();
  CLEAN.push(home);
  fs.mkdirSync(slotDir_(home), { recursive: true });
  fs.writeFileSync(path.join(slotDir_(home), "provider-nvidia.state.json"), JSON.stringify({ last429: Date.now() }));
  const a = startNvidia(home, "a", { delay: 1200 });
  await sleep(400);
  const b = startNvidia(home, "b", { delay: 100 });
  await sleep(500);
  assert.ok(a.started());
  assert.ok(!b.started(), "b waits: the cap is 1 inside the cooldown");
  await Promise.all([a.done, b.done]);
  assert.ok(fs.statSync(b.argsFile).mtimeMs >= fs.statSync(a.argsFile).mtimeMs + 1200);
});

test("nvidia cap: an nvidia rate-limit classified by oc-worker is recorded in the slot dir state file", async () => {
  const home = tmp();
  CLEAN.push(home);
  const t0 = Date.now();
  const a = startNvidia(home, "a", { extraEnv: { FAKE_OC_MODE: "rate429" }, flags: ["--resume", "0"] });
  await a.done;
  const st = JSON.parse(fs.readFileSync(path.join(slotDir_(home), "provider-nvidia.state.json"), "utf8"));
  assert.ok(st.last429 >= t0 && st.last429 <= Date.now());
  // a non-nvidia model's 429 is not recorded
  const h2 = tmp();
  CLEAN.push(h2);
  await startNvidia(h2, "a", { model: "opencode/other-model", extraEnv: { FAKE_OC_MODE: "rate429" }, flags: ["--resume", "0"] }).done;
  assert.ok(!fs.existsSync(path.join(slotDir_(h2), "provider-nvidia.state.json")));
});

// ---- SIGTERM / SIGINT / SIGHUP to oc-worker end the agent and release the slots -----------------------------
// Each test starts one oc-worker with the fake agent in `hang` mode, signals ONLY that pid, and in `finally`
// kills the one agent pid it read from the fake's args file (never by name pattern), so a failure leaves nothing behind.
const pidAlive = (pid) => {
  try { process.kill(pid, 0); return true; } catch (e) { return e.code === "EPERM"; }
};
async function startHung({ stream, extraFlags = [], extraEnv = {} } = {}) {
  const home = tmp();
  CLEAN.push(home);
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(home, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(home, "args.json");
  const flags = ["--agent", "critic", "--dir", home, "--prompt", prompt, "--out", out, "--slots", "2", ...extraFlags];
  let sd;
  if (stream) {
    sd = path.join(home, ".config", "orchestrator", "streams");
    fs.mkdirSync(sd, { recursive: true });
    fs.writeFileSync(path.join(sd, `${stream}.json`), JSON.stringify({ name: stream, repo: "", plan: "", status: "active", next: "x", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: null, done_at: null }));
    flags.push("--stream", stream);
  }
  const child = spawn(process.execPath, [BIN, ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_HOME: home, FAKE_OC_MODE: "hang", FAKE_OC_ARGS_FILE: argsFile, ...extraEnv },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", (d) => (stderr += d));
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 40000); // test-level backstop
  let agentPid = null;
  for (let i = 0; i < 200 && !agentPid; i++) {
    try { agentPid = JSON.parse(fs.readFileSync(argsFile, "utf8")).pid; } catch { await sleep(100); }
  }
  const cleanup = () => {
    clearTimeout(hard);
    if (agentPid && pidAlive(agentPid)) { try { process.kill(agentPid, "SIGKILL"); } catch {} }
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  };
  return { home, out, child, exited, agentPid, cleanup, stderr: () => stderr, sd };
}

for (const [signal, code] of [["SIGTERM", 143], ["SIGINT", 130], ["SIGHUP", 129]]) {
  test(`${signal} to oc-worker kills the agent, writes a killed receipt, frees the slot, exits ${code}`, async () => {
    const h = await startHung();
    try {
      assert.ok(h.agentPid, `the fake agent started: ${h.stderr()}`);
      assert.ok(pidAlive(h.agentPid));
      const t0 = Date.now();
      h.child.kill(signal);
      const res = await h.exited;
      assert.ok(Date.now() - t0 < 10000, "ended within 10 s");
      assert.equal(res.code, code, h.stderr());
      for (let i = 0; i < 50 && pidAlive(h.agentPid); i++) await sleep(100);
      assert.equal(pidAlive(h.agentPid), false, "the agent process is gone");
      const receipt = JSON.parse(fs.readFileSync(h.out + ".receipt.json", "utf8"));
      assert.equal(receipt.exit, "killed");
      assert.ok(receipt.errors.includes(`killed by ${signal}`), JSON.stringify(receipt.errors));
      assert.deepEqual(fs.readdirSync(slotDir_(h.home)), [], "no slot dir left");
    } finally {
      h.cleanup();
    }
  });
}

test("SIGTERM with --stream appends one run-done for the killed run", async () => {


  const probe = await startHung({ stream: "m6a" });
  try {
    assert.ok(probe.agentPid, probe.stderr());
    probe.child.kill("SIGTERM");
    const res = await probe.exited;
    assert.equal(res.code, 143, probe.stderr());
    const ev = eventsOf(probe.sd).filter((e) => e.kind === "run-done");
    assert.equal(ev.length, 1);
    assert.equal(ev[0].run, "m6a/worker-r1");
    assert.equal(ev[0].exit, "killed");
    assert.equal(ev[0].outcome, "error");
  } finally {
    probe.cleanup();
  }
});

test("SIGTERM while waiting for a held slot exits and leaves no slot of its own", async () => {
  const home = tmp();
  CLEAN.push(home);
  const slots = slotDir_(home);
  fs.mkdirSync(path.join(slots, "slot-1"), { recursive: true });
  fs.writeFileSync(path.join(slots, "slot-1", "owner"), JSON.stringify({ pid: process.pid, since: new Date().toISOString() })); // held by this live test process
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const argsFile = path.join(home, "args.json");
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", home, "--prompt", prompt, "--out", path.join(home, "out", "f.md"), "--slots", "1"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_HOME: home, FAKE_OC_ARGS_FILE: argsFile },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 30000);
  try {
    await sleep(1500);
    assert.equal(child.exitCode, null, "still waiting for the slot");
    assert.ok(!fs.existsSync(argsFile), "the agent was never launched");
    child.kill("SIGTERM");
    const res = await exited;
    assert.ok(res.code !== 0, "exits non-zero");
    assert.deepEqual(fs.readdirSync(slots), ["slot-1"], "only the foreign holder's slot remains");
    assert.ok(!fs.existsSync(path.join(home, "out", "f.md.receipt.json")), "no receipt: nothing ran");
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

test("A1: SIGTERM while waiting for a machine slot with the Nvidia provider slot taken releases both and exits 143, no receipt", async () => {
  const home = tmp();
  CLEAN.push(home);
  const slots = slotDir_(home);
  // The only machine slot is held by this live test process, so the run parks in acquireSlot.
  fs.mkdirSync(path.join(slots, "slot-1"), { recursive: true });
  fs.writeFileSync(path.join(slots, "slot-1", "owner"), JSON.stringify({ pid: process.pid, since: new Date().toISOString() }));
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const out = path.join(home, "out", "f.md");
  const argsFile = path.join(home, "args.json");
  const child = spawn(process.execPath, [BIN, "--agent", "worker-nvidia", "--model", "nvidia/test-model", "--dir", home, "--prompt", prompt, "--out", out, "--slots", "1"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_HOME: home, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "hang", ORCH_NVIDIA_POLL_MS: "50" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 30000);
  try {
    await sleep(2500); // let it take the provider slot and park waiting for the machine slot
    assert.equal(child.exitCode, null, "still waiting for the machine slot");
    const nvidiaSlots = fs.readdirSync(slots).filter((n) => /^provider-nvidia-\d+$/.test(n));
    assert.equal(nvidiaSlots.length, 1, `provider slot taken: ${JSON.stringify(nvidiaSlots)}`);
    child.kill("SIGTERM");
    const res = await exited;
    assert.equal(res.code, 143, `expected exit 143, got ${JSON.stringify(res)}`);
    // provider slot released at once (not merely stale for dead-pid reclaim)
    assert.equal(fs.readdirSync(slots).filter((n) => /^provider-nvidia-\d+$/.test(n)).length, 0, "provider slot dir gone");
    assert.deepEqual(fs.readdirSync(slots).filter((n) => /^slot-\d+$/.test(n)), ["slot-1"], "only the foreign holder's machine slot remains");
    assert.ok(!fs.existsSync(out + ".receipt.json"), "no receipt: nothing ran");
    const runs = path.join(home, ".config", "orchestrator", "runs");
    assert.deepEqual(fs.readdirSync(runs).filter(Boolean), [], "no registry file left after the signal");
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

test("A2: SIGTERM after a clean attempt leaves the clean receipt (exit 0, no killed)", async () => {
  const home = tmp();
  CLEAN.push(home);
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const out = path.join(home, "out", "findings-r1.md");
  const argsFile = path.join(home, "args.json");
  // Clean attempt (default fake "ok"), then a postrun pause once <out> exists so the test can land SIGTERM
  // after the loop. The clean receipt must survive the signal.
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", home, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: home, FAKE_OC_ARGS_FILE: argsFile, ORCH_TEST_POSTRUN_PAUSE_MS: "4000" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  let stderr = "";
  child.stderr.on("data", (d) => (stderr += d));
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 30000);
  try {
    // wait for <out> (written after the clean attempt) then SIGTERM during the pause
    for (let i = 0; i < 100 && !fs.existsSync(out); i++) await sleep(50);
    assert.ok(fs.existsSync(out), `<out> written by the clean attempt: ${stderr}`);
    await sleep(150); // let it enter the postrun pause
    assert.equal(child.exitCode, null, "oc-worker still paused after <out>");
    child.kill("SIGTERM");
    const res = await exited;
    assert.equal(res.code, 0, `expected clean exit 0, got ${JSON.stringify(res)}: ${stderr}`);
    const receipt = JSON.parse(fs.readFileSync(out + ".receipt.json", "utf8"));
    assert.notEqual(receipt.exit, "killed", `exit must not be killed: ${JSON.stringify(receipt)}`);
    assert.ok(!receipt.errors.some((e) => /killed by /.test(e)), `no 'killed by' error: ${JSON.stringify(receipt.errors)}`);
    assert.equal(receipt.exit, 0);
    assert.ok(!receipt.errors.some((e) => /killed by/.test(e)), "no killed-by marker");
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

test("A1: SIGTERM during the resume wait writes a killed receipt and one run-done", async () => {
  const { h, sd } = streamHome();
  const state = tmp();
  CLEAN.push(state);
  const prompt = path.join(h, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const runDir = path.join(h, "run");
  fs.mkdirSync(runDir, { recursive: true });
  fs.writeFileSync(path.join(runDir, "ticket.json"), JSON.stringify({ ticket: "m6a", worktree: runDir }));
  const out = path.join(runDir, "worker-r1.md");
  const argsFile = path.join(h, "args.json");
  // drop-once: the first attempt drops (ECONNRESET) after producing output, then oc-worker parks in the
  // resume wait (ORCH_RESUME_WAIT_MS). SIGTERM there must keep the killed receipt + run-done (not go silent).
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", h, "--prompt", prompt, "--out", out, "--stream", "m6a"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: h, FAKE_OC_MODE: "drop-once", FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "6000", FAKE_OC_ARGS_FILE: argsFile },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 30000);
  try {
    await sleep(1800); // first attempt dropped; parked in the 6 s resume wait
    assert.equal(child.exitCode, null, "still in the resume wait");
    child.kill("SIGTERM");
    const res = await exited;
    assert.equal(res.code, 143, `expected exit 143, got ${JSON.stringify(res)}`);
    const receipt = JSON.parse(fs.readFileSync(out + ".receipt.json", "utf8"));
    assert.equal(receipt.exit, "killed", JSON.stringify(receipt));
    assert.ok(receipt.errors.some((e) => e.includes("killed by SIGTERM")), JSON.stringify(receipt.errors));
    const done = eventsOf(sd).filter((e) => e.kind === "run-done");
    assert.equal(done.length, 1, "one run-done");
    assert.equal(done[0].exit, "killed");
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

test("fence: a post-settle SIGTERM keeps an escaped-worktree run at status 5", async () => {
  const dir = tmp();
  CLEAN.push(dir);
  // outside every allowed root (/tmp is allowed, homedir is not)
  const outside = fs.mkdtempSync(path.join(os.homedir(), ".wtf-oc-escape-"));
  CLEAN.push(outside);
  const target = path.join(outside, "escaped.txt");
  fs.writeFileSync(target, "original\n");
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const out = path.join(dir, "out", "findings-r1.md");
  const argsFile = path.join(dir, "args.json");
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "escape-edit", FAKE_OC_TARGET: target, ORCH_TEST_POSTRUN_PAUSE_MS: "4000" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 30000);
  try {
    for (let i = 0; i < 100 && !fs.existsSync(out); i++) await sleep(50);
    assert.ok(fs.existsSync(out), "<out> written by the completed escape");
    await sleep(150); // enter the postrun pause
    assert.equal(child.exitCode, null, "still paused after <out>");
    child.kill("SIGTERM");
    const res = await exited;
    // escaped-worktree keeps status 5 despite the post-settle signal (not sig.code 143, not clean 0)
    assert.equal(res.code, 5, `expected exit 5 (escaped-worktree), got ${JSON.stringify(res)}`);
  } finally {
    clearTimeout(hard);
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

test("slot-wait handlers do not poison the next hop after a CcSlotTimeout", async () => {
  const home = tmp();
  CLEAN.push(home);
  const slots = slotDir_(home);
  // Hold the ccread slot with this live test process so cc-critic times out and runChain moves on in-process.
  fs.mkdirSync(path.join(slots, "provider-ccread-1"), { recursive: true });
  fs.writeFileSync(path.join(slots, "provider-ccread-1", "owner"), JSON.stringify({ pid: process.pid, since: new Date().toISOString() }));
  // Tiny reader wait so hop 1 gives up fast.
  const cfgDir = path.join(home, ".config", "orchestrator");
  fs.mkdirSync(cfgDir, { recursive: true });
  fs.writeFileSync(path.join(cfgDir, "usage-limits.json"), JSON.stringify({ cc: { reader_wait_min: 0.02 } }));
  // cc-critic's role contract must exist, else it throws CcNoContract before the ccread wait (no handlers
  // installed yet). A minimal fixture gets it to the slot wait, where CcSlotTimeout fires.
  const agentDir = path.join(home, ".claude", "agents");
  fs.mkdirSync(agentDir, { recursive: true });
  fs.writeFileSync(path.join(agentDir, "critic.md"), "---\nname: critic\n---\nFixture critic contract body.\n");
  const prompt = path.join(home, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const out = path.join(home, "out", "f.md");
  const argsFile = path.join(home, "args.json");
  const child = spawn(process.execPath, [BIN, "--agent", "cc-critic", "--fallback", "worker", "--no-detach", "--dir", home, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: home, FAKE_OC_MODE: "hang", FAKE_OC_ARGS_FILE: argsFile, ORCH_CC_POLL_MS: "50" },
    stdio: ["ignore", "pipe", "pipe"],
  });
  const exited = new Promise((res) => child.on("close", (code, signal) => res({ code, signal })));
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 30000);
  let agentPid = null;
  try {
    // Wait for hop 2's fake agent (hop 1 never spawns — it throws CcSlotTimeout during its slot wait).
    for (let i = 0; i < 200 && !agentPid; i++) {
      try { agentPid = JSON.parse(fs.readFileSync(argsFile, "utf8")).pid; } catch { await sleep(100); }
    }
    assert.ok(agentPid, "hop 2's fake agent started");
    child.kill("SIGTERM");
    const res = await exited;
    assert.equal(res.code, 143, `expected exit 143, got ${JSON.stringify(res)}`);
    const receipt = JSON.parse(fs.readFileSync(out + ".receipt.json", "utf8"));
    assert.equal(receipt.exit, "killed", JSON.stringify(receipt));
    assert.ok(receipt.errors.some((e) => e.includes("killed by SIGTERM")), JSON.stringify(receipt.errors));
    // hop 2's agent killed, its machine slot released, its registry entry ended
    for (let i = 0; i < 50 && pidAlive(agentPid); i++) await sleep(100);
    assert.equal(pidAlive(agentPid), false, "the fake agent is gone");
    assert.deepEqual(fs.readdirSync(slots).filter((n) => /^slot-\d+$/.test(n)), [], "no machine slot left");
    assert.deepEqual(fs.readdirSync(path.join(home, ".config", "orchestrator", "runs")).filter(Boolean), [], "no registry file left");
  } finally {
    clearTimeout(hard);
    if (agentPid && pidAlive(agentPid)) { try { process.kill(agentPid, "SIGKILL"); } catch {} }
    if (child.exitCode === null) { try { child.kill("SIGKILL"); } catch {} }
  }
});

// ── fixture orphan guard (test-orphans M2) ───────────────────────────────────

test("fake-opencode cap: a hung run exits 124 after FAKE_OC_MAX_MS, well inside the spawn timeout", () => {
  const r = spawnSync(process.execPath, [FAKE, "run", "--agent", "critic"], {
    env: { ...process.env, FAKE_OC_MODE: "hang", FAKE_OC_MAX_MS: "500" },
    encoding: "utf8",
    timeout: 10000,
  });
  assert.equal(r.status, 124, `expected exit 124, got status=${r.status} signal=${r.signal}: ${r.stderr}`);
});

test("reap: a fixture child orphaned by a SIGKILLed oc-worker is reaped by the guard (Linux)", { skip: process.platform !== "linux", timeout: 15000 }, async () => {
  const id = `reap-test-${process.pid}-${Date.now()}`;
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "orch-reap-"));
  CLEAN.push(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the thing.");
  const argsFile = path.join(dir, "args.json");
  const out = path.join(dir, "out", "f.md");
  fs.mkdirSync(path.dirname(out), { recursive: true });
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", out, "--timeout-min", "5"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, FAKE_OC_MODE: "hang", FAKE_OC_SUITE: id },
    encoding: "utf8",
    timeout: 3000,
    killSignal: "SIGKILL",
  });
  // The wrapper died without running its handler (simulates a crash). The detached fake agent survives.
  const children = fixtureChildren(id);
  assert.ok(children.length > 0, `expected at least one fixture child for ${id}, got none (r.status=${r.status} signal=${r.signal})`);
  const killed = reapFixtureChildren(id);
  assert.ok(killed.length > 0, `expected to kill at least one child, got none`);
  // Within 5 s every fixture child for this id is gone.
  const sleep = (ms) => new Promise((res) => setTimeout(res, ms));
  let gone = false;
  const deadline = Date.now() + 5000;
  while (Date.now() < deadline) {
    if (fixtureChildren(id).length === 0) { gone = true; break; }
    await sleep(200);
  }
  assert.equal(gone, true, `fixture children survived reaping: ${fixtureChildren(id).join(",")}`);
});

// ── worktree fence tests ──────────────────────────────────────────

test("fence: footer contains the worktree paragraph", () => {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stderr);
  const { argv } = JSON.parse(fs.readFileSync(argsFile, "utf8"));
  const message = argv.at(-1);
  assert.ok(message.includes("Your worktree is"), "footer has worktree paragraph");
  assert.ok(message.includes("Create and edit files only under it"), "footer names allowed roots");
  assert.ok(message.includes(path.resolve(dir)), "footer names D");
});

test("fence: ORCH_EDIT_FENCE=1 sets OPENCODE_CONFIG_CONTENT with the fence config", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const envFile = path.join(dir, "env.json");
  const fake = path.join(dir, "fake-env-oc.mjs");
  fs.writeFileSync(fake, `#!/usr/bin/env node\nimport fs from "node:fs";\nconst argv = process.argv.slice(2);\nif (process.env.FAKE_OC_ARGS_FILE) fs.writeFileSync(process.env.FAKE_OC_ARGS_FILE, JSON.stringify({ argv, cwd: process.cwd() }));\nfs.writeFileSync(process.env.FAKE_OC_ENV_FILE, JSON.stringify({ oc: process.env.OPENCODE_CONFIG_CONTENT }));\nprocess.stdout.write(JSON.stringify({ type: "text", sessionID: "ses", part: { sessionID: "ses", messageID: "m", type: "text", text: "RESULT: DONE\\n" } }) + "\\n");\nprocess.stdout.write(JSON.stringify({ type: "step_finish", part: { type: "step-finish", cost: 0 } }) + "\\n");\n`);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: {
      ...process.env,
      OPENCODE_BIN: fake,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: dir,
      FAKE_OC_ARGS_FILE: argsFile,
      FAKE_OC_ENV_FILE: envFile,
      ORCH_EDIT_FENCE: "1",
    },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stderr);
  const env = JSON.parse(fs.readFileSync(envFile, "utf8"));
  assert.ok(env.oc, "OPENCODE_CONFIG_CONTENT was set");
  const cfg = JSON.parse(env.oc);
  assert.equal(cfg.permission.edit["*"], "deny", "default deny");
  assert.ok(cfg.permission.edit[`${path.resolve(dir)}/**`], "D allow");
  assert.ok(cfg.permission.edit[`${path.resolve(path.dirname(out))}/**`], "report dir allow");
  assert.ok(cfg.permission.edit[`${os.tmpdir()}/**`], "tmp allow");
});

test("fence: ORCH_EDIT_FENCE=1 merges fence into existing OPENCODE_CONFIG_CONTENT", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const envFile = path.join(dir, "env.json");
  const fake = path.join(dir, "fake-env-oc.mjs");
  fs.writeFileSync(fake, `#!/usr/bin/env node\nimport fs from "node:fs";\nfs.writeFileSync(process.env.FAKE_OC_ENV_FILE, JSON.stringify({ oc: process.env.OPENCODE_CONFIG_CONTENT }));\nprocess.stdout.write(JSON.stringify({ type: "text", sessionID: "ses", part: { sessionID: "ses", messageID: "m", type: "text", text: "RESULT: DONE\\n" } }) + "\\n");\nprocess.stdout.write(JSON.stringify({ type: "step_finish", part: { type: "step-finish", cost: 0 } }) + "\\n");\n`);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const existing = JSON.stringify({ permission: { edit: { "/existing/**": "allow" } }, other: 1 });
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: {
      ...process.env,
      OPENCODE_BIN: fake,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: dir,
      FAKE_OC_ENV_FILE: envFile,
      ORCH_EDIT_FENCE: "1",
      OPENCODE_CONFIG_CONTENT: existing,
    },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stderr);
  const env = JSON.parse(fs.readFileSync(envFile, "utf8"));
  const cfg = JSON.parse(env.oc);
  assert.equal(cfg.other, 1, "existing fields preserved");
  assert.equal(cfg.permission.edit["/existing/**"], "allow", "existing edit rule preserved");
  assert.equal(cfg.permission.edit["*"], "deny", "fence deny added");
  assert.ok(cfg.permission.edit[`${path.resolve(dir)}/**`], "fence D allow added");
});

test("fence: ORCH_EDIT_FENCE=0 leaves OPENCODE_CONFIG_CONTENT untouched", () => {
  const dir = tmp();
  CLEAN.push(dir);
  const envFile = path.join(dir, "env.json");
  const fake = path.join(dir, "fake-env-oc.mjs");
  fs.writeFileSync(fake, `#!/usr/bin/env node\nimport fs from "node:fs";\nfs.writeFileSync(process.env.FAKE_OC_ENV_FILE, JSON.stringify({ oc: process.env.OPENCODE_CONFIG_CONTENT }));\nprocess.stdout.write(JSON.stringify({ type: "text", sessionID: "ses", part: { sessionID: "ses", messageID: "m", type: "text", text: "RESULT: DONE\\n" } }) + "\\n");\nprocess.stdout.write(JSON.stringify({ type: "step_finish", part: { type: "step-finish", cost: 0 } }) + "\\n");\n`);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Do the work.");
  const out = path.join(dir, "out", "worker-r1.md");
  const existing = JSON.stringify({ permission: { edit: { "/existing/**": "allow" } } });
  const r = spawnSync(process.execPath, [BIN, "--agent", "worker", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: {
      ...process.env,
      OPENCODE_BIN: fake,
      ORCH_NO_PROCTREE: "1",
      ORCH_HOME: dir,
      FAKE_OC_ENV_FILE: envFile,
      ORCH_EDIT_FENCE: "0",
      OPENCODE_CONFIG_CONTENT: existing,
    },
    encoding: "utf8",
    timeout: 30000,
  });
  assert.equal(r.status, 0, r.stderr);
  const env = JSON.parse(fs.readFileSync(envFile, "utf8"));
  assert.equal(env.oc, existing, "config unchanged when ORCH_EDIT_FENCE=0");
});

// ---------------------------------------------------------------- (d)(f) installer + status-line sentences (ws-guard-followups)
const INSTALLER_SENTENCE =
  "Never run an installer (`orchestrator/bin/install.mjs`, `ops/install.mjs`, or any other install script) from a worktree unless `ORCH_HOME` points at a scratch directory: without it the installer writes to the real home. Installing is the orchestrator's job, from main, after ship.";
const STATUS_SENTENCE =
  "The first line of your final reply is exactly `RESULT: DONE` or `RESULT: BLOCKED: <reason>`: capitals, with no markdown, emoji, quote or prefix. The parser is case-sensitive, and anything else counts as an error.";

test("FOOTER carries the exact worker status-line sentence", () => {
  assert.match(FOOTER, /RESULT: DONE/);
  assert.match(FOOTER, /RESULT: BLOCKED: <reason>/);
  assert.match(FOOTER, /case-sensitive/);
  assert.match(FOOTER, /- Workers: The first line of your final reply is exactly/);
  assert.ok(FOOTER.includes(STATUS_SENTENCE), "FOOTER holds the sentence verbatim");
});

test("every worker variant carries the installer sentence and the status-line sentence verbatim", () => {
  for (const f of ["worker.md", "worker-free.md", "worker-nvidia.md", "worker-strong.md"]) {
    const text = fs.readFileSync(path.join(HERE, "..", "agents", f), "utf8");
    assert.ok(text.includes(INSTALLER_SENTENCE), `${f} carries the installer sentence verbatim`);
    assert.ok(text.includes(STATUS_SENTENCE), `${f} carries the status-line sentence verbatim`);
  }
});

test("frood-ticket.md and frood-orchestrator.md carry the installer sentence", () => {
  for (const f of ["commands/frood-ticket.md", "commands/frood-orchestrator.md"]) {
    const text = fs.readFileSync(path.join(HERE, "..", f), "utf8");
    assert.ok(text.includes(INSTALLER_SENTENCE), `${f} carries the installer sentence verbatim`);
  }
});

// ---------------------------------------------------------------- sleep inhibitor (worker-prompts-keep-awake)

// A fake `systemd-inhibit`: records argv + pid to INHIBIT_RECORD_FILE, then stays alive until killed.
function fakeInhibit(dir) {
  const fake = path.join(dir, "fake-inhibit.mjs");
  fs.writeFileSync(
    fake,
    `#!/usr/bin/env node\n` +
    `import fs from "node:fs";\n` +
    `const file = process.env.INHIBIT_RECORD_FILE;\n` +
    `try { if (file) fs.writeFileSync(file, JSON.stringify({ argv: process.argv.slice(2), pid: String(process.pid) })); } catch {}\n` +
    `setInterval(() => {}, 3600000);\n`,
  );
  fs.chmodSync(fake, 0o755);
  return fake;
}

function waitForRecord(record, ms = 10000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    try { return JSON.parse(fs.readFileSync(record, "utf8")); } catch {}
    const start = Date.now();
    while (Date.now() - start < 50) {}
  }
  return null;
}

// Wait (bounded) for pid `pid` to vanish. ESRCH = gone.
function pidGone(pid, ms = 3000) {
  const deadline = Date.now() + ms;
  while (Date.now() < deadline) {
    try { process.kill(pid, 0); } catch (e) { if (e.code === "ESRCH") return true; }
    const start = Date.now();
    while (Date.now() - start < 50) {}
  }
  return false;
}

test("inhibitor: spawned with --what=idle:handle-lid-switch --mode=block; argv never names sleep:; pid released after a clean run", { skip: process.platform === "win32" }, () => {
  const dir = tmp();
  CLEAN.push(dir);
  const record = path.join(dir, "inhibit.json");
  const fake = fakeInhibit(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = run({ INHIBIT_RECORD_FILE: record, ORCH_INHIBIT_BIN: fake, ORCH_NO_INHIBIT: "0" }, "--timeout-min", "1");
  assert.equal(r.status, 0, r.stderr);
  const logged = waitForRecord(record);
  assert.ok(logged, "inhibitor never recorded");
  assert.ok(logged.argv.includes("--what=idle:handle-lid-switch"), JSON.stringify(logged));
  assert.ok(logged.argv.includes("--mode=block"), JSON.stringify(logged));
  assert.ok(logged.argv.some((a) => a.startsWith("--who=oc-worker")), JSON.stringify(logged));
  assert.ok(logged.argv.some((a) => a.startsWith("--why=worker run ")), JSON.stringify(logged));
  assert.ok(logged.argv.includes("sleep"), JSON.stringify(logged));
  assert.ok(!logged.argv.includes("--what=sleep"), JSON.stringify(logged));
  assert.ok(!logged.argv.some((a) => a.includes("sleep:")), JSON.stringify(logged));
  // D3: --timeout-min 1 with default grace 15 => (1+15+5)*60 = 1260 s.
  assert.equal(logged.argv.at(-1), "1260", `inhibitor duration should be 1260 s, got ${JSON.stringify(logged.argv)}`);
  assert.ok(pidGone(Number(logged.pid)), `inhibitor pid ${logged.pid} still alive after clean run`);
});

test("inhibitor: --grace-min sets the duration (--timeout-min 1 --grace-min 2 => 480 s)", { skip: process.platform === "win32" }, () => {
  const dir = tmp();
  CLEAN.push(dir);
  const record = path.join(dir, "inhibit.json");
  const fake = fakeInhibit(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = run({ INHIBIT_RECORD_FILE: record, ORCH_INHIBIT_BIN: fake, ORCH_NO_INHIBIT: "0" }, "--timeout-min", "1", "--grace-min", "2");
  assert.equal(r.status, 0, r.stderr);
  const logged = waitForRecord(record);
  assert.ok(logged, "inhibitor never recorded");
  assert.equal(logged.argv.at(-1), "480", `inhibitor duration should be 480 s, got ${JSON.stringify(logged.argv)}`);
  assert.ok(pidGone(Number(logged.pid)), `inhibitor pid ${logged.pid} still alive after clean run`);
});

test("inhibitor: pid released after a timed-out run", { skip: process.platform === "win32" }, () => {
  const dir = tmp();
  CLEAN.push(dir);
  const record = path.join(dir, "inhibit.json");
  const fake = fakeInhibit(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = run({ INHIBIT_RECORD_FILE: record, ORCH_INHIBIT_BIN: fake, FAKE_OC_MODE: "hang", ORCH_NO_INHIBIT: "0" }, "--timeout-min", "0.02");
  assert.equal(r.status, 4, r.stderr);
  assert.equal(JSON.parse(r.stdout.trim()).exit, "timeout");
  const logged = waitForRecord(record);
  assert.ok(logged, "inhibitor never recorded");
  assert.ok(pidGone(Number(logged.pid)), `inhibitor pid ${logged.pid} still alive after timeout`);
});

test("inhibitor: pid released after SIGTERM to oc-worker", { skip: process.platform === "win32" }, async () => {
  const dir = tmp();
  CLEAN.push(dir);
  const record = path.join(dir, "inhibit.json");
  const fake = fakeInhibit(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const out = path.join(dir, "out", "findings-r1.md");
  const child = spawn(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", out, "--timeout-min", "30"], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, INHIBIT_RECORD_FILE: record, ORCH_INHIBIT_BIN: fake, FAKE_OC_MODE: "hang", ORCH_NO_INHIBIT: "0" },
    encoding: "utf8",
  });
  const hard = setTimeout(() => { try { child.kill("SIGKILL"); } catch {} }, 30000);
  const logged = waitForRecord(record);
  assert.ok(logged, "inhibitor never recorded");
  assert.ok(child.exitCode === null && child.signalCode === null, "oc-worker exited before the inhibitor was recorded");
  child.kill("SIGTERM");
  const { code, signal } = await new Promise((res) => {
    if (child.exitCode !== null || child.signalCode !== null) res({ code: child.exitCode, signal: child.signalCode });
    else child.once("exit", (c, s) => res({ code: c, signal: s }));
  });
  clearTimeout(hard);
  assert.ok(code === 143 || signal === "SIGTERM", `oc-worker exited with code ${code} signal ${signal}`);
  assert.ok(pidGone(Number(logged.pid)), `inhibitor pid ${logged.pid} still alive after SIGTERM`);
});

test("inhibitor: a throw in the setup gap releases the inhibitor and the slots (D1)", { skip: process.platform === "win32" }, async () => {
  const dir = tmp();
  CLEAN.push(dir);
  const record = path.join(dir, "inhibit.json");
  const fake = fakeInhibit(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  // cc-critic needs its role contract (<ORCH_HOME>/.claude/agents/critic.md). Write a minimal fixture so
  // ccContract resolves it (never copy the host's installed agent file), then make --out read-only so
  // atomicWrite(contractFile) throws EACCES in the setup gap (after startInhibitor, before any spawn) —
  // uncaught, so runWorker's finally releases the inhibitor and the slots.
  const agentDir = path.join(dir, ".claude", "agents");
  fs.mkdirSync(agentDir, { recursive: true });
  fs.writeFileSync(path.join(agentDir, "critic.md"), "---\nname: critic\n---\nFixture critic contract body.\n");
  const outDir = path.join(dir, "out");
  fs.mkdirSync(outDir, { recursive: true });
  fs.chmodSync(outDir, 0o555);
  const out = path.join(outDir, "findings-r1.md");
  const child = spawn(process.execPath, [BIN, "--agent", "cc-critic", "--no-detach", "--dir", dir, "--prompt", prompt, "--out", out], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, INHIBIT_RECORD_FILE: record, ORCH_INHIBIT_BIN: fake, ORCH_NO_INHIBIT: "0" },
    encoding: "utf8",
  });
  const { code } = await new Promise((res) => child.on("close", (c) => res({ code: c })));
  assert.ok(code !== 0, `expected a non-zero exit from the setup throw, got ${code}`);
  // D1 core: release() runs in the finally, so the machine slot is freed even though setup threw.
  assert.deepEqual(fs.readdirSync(slotDir_(dir)), [], "no slot dir left after the setup throw");
  // If the fake inhibitor managed to record before oc-worker exited, its pid must be gone now.
  let logged;
  try { logged = JSON.parse(fs.readFileSync(record, "utf8")); } catch { logged = null; }
  if (logged) assert.ok(pidGone(Number(logged.pid)), `inhibitor pid ${logged.pid} still alive after the setup throw`);
  // restore perms so CLEAN can remove the dir
  try { fs.chmodSync(outDir, 0o755); } catch {}
});

test("inhibitor: ORCH_NO_INHIBIT=1 spawns nothing and the run succeeds", { skip: process.platform === "win32" }, () => {
  const dir = tmp();
  CLEAN.push(dir);
  const record = path.join(dir, "inhibit.json");
  const fake = fakeInhibit(dir);
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = run({ INHIBIT_RECORD_FILE: record, ORCH_INHIBIT_BIN: fake, ORCH_NO_INHIBIT: "1" });
  assert.equal(r.status, 0, r.stderr);
  assert.ok(!fs.existsSync(record), "inhibitor was spawned with ORCH_NO_INHIBIT=1");
});

test("inhibitor: systemd-inhibit missing from PATH warns on stderr but the run succeeds", { skip: process.platform === "win32" }, () => {
  const dir = tmp();
  CLEAN.push(dir);
  const nodir = path.join(dir, "no-bin");
  fs.mkdirSync(nodir, { recursive: true });
  const record = path.join(dir, "inhibit.json");
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const r = run({ INHIBIT_RECORD_FILE: record, PATH: nodir, ORCH_NO_INHIBIT: "0", ORCH_INHIBIT_BIN: path.join(nodir, "systemd-inhibit") }, "--timeout-min", "1");
  assert.equal(r.status, 0, r.stderr);
  assert.ok(!fs.existsSync(record), "inhibitor was spawned without systemd-inhibit");
  assert.match(r.stderr, /sleep inhibitor spawn failed/, r.stderr);
});

test("inhibitor: no non-inhibitor test may start the inhibitor (tripwire never fired)", () => {
  assert.ok(
    !fs.existsSync(TRIPWIRE_FILE),
    "tripwire fired: a non-inhibitor test started an inhibitor",
  );
});

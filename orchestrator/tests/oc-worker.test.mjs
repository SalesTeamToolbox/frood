import test, { after } from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { summarize, acquireSlot, slotDir } from "../bin/oc-worker.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "oc-worker.mjs");
const BOARD = path.join(HERE, "..", "bin", "board.mjs");
const FAKE = path.join(HERE, "fixtures", "fake-opencode.mjs");
const BOARD_FIX = path.join(HERE, "fixtures", "board");

const CLEAN = [];
after(() => {
  for (const d of CLEAN) fs.rmSync(d, { recursive: true, force: true, maxRetries: 10 });
});

function tmp() {
  return fs.mkdtempSync(path.join(os.tmpdir(), "orch-ocw-"));
}
function run(extraEnv, ...flags) {
  const dir = tmp();
  const prompt = path.join(dir, "mandate.md");
  fs.writeFileSync(prompt, "Review the diff.");
  const argsFile = path.join(dir, "args.json");
  const r = spawnSync(process.execPath, [BIN, "--agent", "critic", "--dir", dir, "--prompt", prompt, "--out", path.join(dir, "out", "findings-r1.md"), ...flags], {
    env: { ...process.env, OPENCODE_BIN: FAKE, ORCH_NO_PROCTREE: "1", ORCH_HOME: dir, FAKE_OC_ARGS_FILE: argsFile, ...extraEnv },
    encoding: "utf8",
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
  for (const f of ["run", "--format", "json", "--auto", "--agent", "critic"]) assert.ok(argv.includes(f), f);
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
  r1();
  const r3 = await acquireSlot(2, { pollMs: 20, deadline: Date.now() + 1000 });
  r2();
  r3();
  // dead owner
  const d = path.join(slotDir(), "slot-1");
  fs.mkdirSync(d, { recursive: true });
  fs.writeFileSync(path.join(d, "owner"), JSON.stringify({ pid: 999999, since: "x" }));
  fs.mkdirSync(path.join(slotDir(), "slot-2"), { recursive: true });
  fs.writeFileSync(path.join(slotDir(), "slot-2", "owner"), JSON.stringify({ pid: process.pid, since: "x" }));
  const r4 = await acquireSlot(2, { pollMs: 20, deadline: Date.now() + 500 });
  r4();
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
const LAST_HEADER_LINE = /Exit: 0 finished, 3 no final text, 4 timeout, 5 opencode error, 6 every pool in the chain known-down, 7 board\nattach refused \(--ticket\), 8 model not allowed by provider policy[^\n]*\nand not on the allowlist\)\./;

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
  assert.doesNotMatch(r.stdout, /oc-worker:/);
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
  const r = run({ FAKE_OC_MODE: "quota-critic" }, "--fallback", "critic-alt,scout");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const receipt = JSON.parse(r.stdout.trim());
  assert.equal(receipt.agent, "critic-alt");
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

test("timeout keeps partial output, clearly marked BLOCKED", () => {
  const r = run({ FAKE_OC_MODE: "hang-after-text" }, "--timeout-min", "0.03");
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
  const r = run({ FAKE_OC_MODE: "hang-after-text" }, "--idle-min", "0", "--timeout-min", "0.1");
  assert.equal(r.status, 4);
  assert.equal(JSON.parse(r.stdout.trim()).exit, "timeout");
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
  const out = path.join(h, "run", outName);
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
  // no ticket.json in the run dir: the id's ticket part is the run dir's basename ("run")
  assert.deepEqual(ev.map((e) => e.key), ["run:run/worker-r1:queued", "run:run/worker-r1:done"]);
  assert.equal(ev[0].run, "run/worker-r1");
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
  const r = streamRun(h, { FAKE_OC_MODE: "quota-critic" }, "worker-r1.md", "--fallback", "critic-alt");
  assert.equal(r.status, 0, r.stdout + r.stderr);
  const ev = eventsOf(sd);
  assert.equal(ev.filter((e) => e.kind === "queued").length, 1);
  const done = ev.filter((e) => e.kind === "run-done");
  assert.equal(done.length, 1);
  assert.equal(done[0].agent, "critic-alt");
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
  fs.writeFileSync(path.join(sd, "m6a.events.jsonl"), JSON.stringify({ key: "run:run/worker-r3:queued", kind: "queued", at: new Date().toISOString(), run: "run/worker-r3" }) + "\n");
  const dup = streamRun(h, {}, "worker-r3.md");
  assert.equal(dup.status, 9);
  assert.match(dup.stderr, /oc-worker: run run\/worker-r3 already queued/);
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

  // No ticket.json: the run directory's basename is the ticket part, so two dirs still do not collide.
  const c = dispatch("run-c", null);
  const d = dispatch("run-d", null);
  assert.equal(c.status, 0, c.stderr);
  assert.equal(d.status, 0, d.stderr);
  assert.deepEqual(
    eventsOf(sd).filter((e) => e.kind === "queued").map((e) => e.run).sort(),
    ["m6a-a/worker-r1", "m6a-b/worker-r1", "run-c/worker-r1", "run-d/worker-r1"],
  );
});

test("O4: both receipt writes go through atomicWrite", () => {
  const src = fs.readFileSync(BIN, "utf8");
  assert.equal((src.match(/atomicWrite\([^\n]*receipt\.json/g) || []).length, 2);
  assert.ok(!/writeFileSync\([^\n]*receipt\.json/.test(src), "no plain writeFileSync of a receipt");
});

test("midrun-quota-once: a mid-run quota death is nudged with --session and finishes", () => {
  const state = tmp();
  CLEAN.push(state);
  const r = run({ FAKE_OC_MODE: "midrun-quota-once", FAKE_OC_STATE_DIR: state, ORCH_RESUME_WAIT_MS: "0" });
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
});

test("quota with --resume 0 is not nudged; a persistent quota fails after one nudge", () => {
  const noNudge = run({ FAKE_OC_MODE: "text-then-quota", ORCH_RESUME_WAIT_MS: "0" }, "--resume", "0");
  assert.equal(noNudge.status, 5, noNudge.stdout);
  assert.deepEqual(JSON.parse(noNudge.stdout.trim()).resumed, []);
  const persistent = run({ FAKE_OC_MODE: "text-then-quota", ORCH_RESUME_WAIT_MS: "0" });
  assert.equal(persistent.status, 5, persistent.stdout);
  const receipt = JSON.parse(persistent.stdout.trim());
  assert.equal(receipt.attempts, 2);
  assert.equal(receipt.resumed.length, 1, "one nudge, then the failure stands");
  assert.match(receipt.errors.join("\n"), /weekly usage limit/);
});

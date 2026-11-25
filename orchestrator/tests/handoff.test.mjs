import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync, spawn } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";
import { appendEvent, appendAck, readEvents, readAcks, readAckLines, unhandled, withStreamLock, streamTitle } from "../bin/handoff.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO = path.resolve(HERE, "..");
const BIN = path.join(REPO, "bin", "handoff.mjs");
const HOOK = path.join(REPO, "hooks", "orchestrator-handoff.js");
const HOUR = 3600_000;
const DAY = 24 * HOUR;

function env() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-ho-"));
  const plan = path.join(h, "plan.md");
  fs.writeFileSync(plan, "# plan\n## Handoff\nnext: M5\n");
  // ORCH_REPO makes the hook import this worktree's handoff.mjs, not whatever is installed in the real repo.
  return { h, plan, e: { ...process.env, ORCH_HOME: h, USERPROFILE: h, HOME: h, ORCH_REPO: REPO } };
}
const run = (e, ...a) => spawnSync(process.execPath, [BIN, ...a], { env: e, encoding: "utf8" });
const hook = (e, source) => spawnSync(process.execPath, [HOOK], { env: e, input: JSON.stringify({ session_id: "x", source }), encoding: "utf8" });
const dirOf = (h) => path.join(h, ".config", "orchestrator", "streams");
const jpath = (h, name) => path.join(dirOf(h), `${name}.json`);
const stream = (h, name) => JSON.parse(fs.readFileSync(jpath(h, name), "utf8"));

// The module exports take ORCH_HOME from the environment, so point it at a temp dir for the duration of one call.
function withHome(h, fn) {
  const before = process.env.ORCH_HOME;
  process.env.ORCH_HOME = h;
  try {
    return fn();
  } finally {
    if (before === undefined) delete process.env.ORCH_HOME;
    else process.env.ORCH_HOME = before;
  }
}

// Helper to run with a modified env (for TTL override)
function runWithEnv(baseEnv, extraEnv, ...args) {
  return run({ ...baseEnv, ...extraEnv }, ...args);
}

// Helper to write a claim with a specific timestamp directly to the stream file
function writeClaimWithTime(h, name, claim, writtenAt) {
  const s = stream(h, name);
  s.claim = claim;
  if (writtenAt) s.written_at = writtenAt;
  fs.writeFileSync(jpath(h, name), JSON.stringify(s, null, 2));
}

// ------------------------------------------------------------------ old CLI, unchanged

test("old CLI form: write --plan --next, show, consume keep their exit codes and JSON output", () => {
  const { plan, e } = env();
  assert.equal(run(e, "show").status, 1, "nothing pending yet");
  assert.equal(run(e, "write", "--plan", plan, "--next", "M5 cutover", "--waiting", "board a consuming repo").status, 0);
  const s = run(e, "show");
  assert.equal(s.status, 0);
  const obj = JSON.parse(s.stdout);
  assert.equal(obj.next, "M5 cutover");
  assert.equal(obj.waiting, "board a consuming repo");
  assert.equal(obj.name, "default", 'no --stream writes stream "default"');
  assert.equal(obj.status, "active");
  assert.equal(obj.repo, "");
  assert.equal(obj.written_by, "");
  assert.equal(obj.consumed_at, null);
  assert.equal(obj.done_at, null);
  const consumed = run(e, "consume");
  assert.equal(consumed.status, 0);
  assert.ok(JSON.parse(consumed.stdout).consumed_at, "consume returns the stream with consumed_at set");
  assert.equal(run(e, "show").status, 1);
  assert.equal(run(e, "consume").status, 1, "a second /frood-next does not replay it");
});

test("write refuses a missing plan, a missing --next, a bad stream name and a bad status", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--plan", path.join(h, "nope.md"), "--next", "x").status, 2);
  assert.equal(run(e, "write", "--plan", plan).status, 2);
  assert.equal(run(e, "write", "--stream", "Bad Name", "--plan", plan, "--next", "x").status, 2);
  assert.equal(run(e, "write", "--stream", "-lead", "--plan", plan, "--next", "x").status, 2);
  assert.equal(run(e, "write", "--stream", "ok", "--plan", plan, "--next", "x", "--status", "weird").status, 2);
});

test("write records repo/status/written-by and keeps omitted fields on update", () => {
  const { plan, e } = env();
  assert.equal(run(e, "write", "--stream", "m6a", "--plan", plan, "--next", "T6", "--done", "T5", "--repo", REPO, "--written-by", "sess-1").status, 0);
  const s = run(e, "write", "--stream", "m6a", "--plan", plan, "--next", "T7");
  assert.equal(s.status, 0);
  const kept = JSON.parse(s.stdout);
  assert.equal(kept.next, "T7");
  assert.equal(kept.done, "T5", "an omitted --done keeps its value");
  assert.equal(kept.repo, REPO);
  assert.equal(kept.written_by, "sess-1");
});

// ------------------------------------------------------------------ migration

test("migrate: handoff.json becomes streams/default.json and steps aside (.migrated, then .migrated.2)", () => {
  const { h, plan, e } = env();
  const legacy = path.join(h, ".config", "orchestrator", "handoff.json");
  fs.mkdirSync(path.dirname(legacy), { recursive: true });
  fs.writeFileSync(
    legacy,
    JSON.stringify({ plan, next: "M4 cutover", done: "M3 shipped", waiting: "owner", written_at: new Date().toISOString(), consumed_at: null }),
  );
  assert.equal(fs.readFileSync(legacy, "utf8").length > 0, true);
  // any verb migrates first; this one finds exactly one pending stream and prints it
  const shown = run(e, "show");
  assert.equal(shown.status, 0, shown.stderr);
  assert.equal(JSON.parse(shown.stdout).name, "default");
  const def = stream(h, "default");
  assert.deepEqual(
    { plan: def.plan, next: def.next, done: def.done, waiting: def.waiting, repo: def.repo, status: def.status, written_by: def.written_by, done_at: def.done_at },
    { plan: path.resolve(plan), next: "M4 cutover", done: "M3 shipped", waiting: "owner", repo: "", status: "active", written_by: "", done_at: null },
  );
  assert.equal(fs.existsSync(legacy), false);
  assert.equal(fs.existsSync(`${legacy}.migrated`), true);

  // a leftover .migrated name must not be overwritten
  const other = env();
  const legacy2 = path.join(other.h, ".config", "orchestrator", "handoff.json");
  fs.mkdirSync(path.dirname(legacy2), { recursive: true });
  fs.writeFileSync(legacy2, JSON.stringify({ plan: other.plan, next: "old", written_at: new Date().toISOString(), consumed_at: null }));
  fs.writeFileSync(`${legacy2}.migrated`, "an earlier migration\n");
  assert.equal(run(other.e, "show").status, 0);
  assert.equal(fs.existsSync(`${legacy2}.migrated.2`), true);
  assert.equal(fs.readFileSync(`${legacy2}.migrated`, "utf8"), "an earlier migration\n");

  // both files present: nothing is migrated or renamed
  const both = env();
  const legacy3 = path.join(both.h, ".config", "orchestrator", "handoff.json");
  assert.equal(run(both.e, "write", "--stream", "default", "--plan", both.plan, "--next", "fresh").status, 0);
  fs.writeFileSync(legacy3, JSON.stringify({ plan: both.plan, next: "legacy", written_at: new Date().toISOString(), consumed_at: null }));
  assert.equal(run(both.e, "list").status, 0);
  assert.equal(stream(both.h, "default").next, "fresh");
  assert.equal(fs.existsSync(legacy3), true, "the legacy file is left alone when streams/default.json exists");
});

// ------------------------------------------------------------------ several streams

test("two streams survive interleaved writes", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "m6a", "--plan", plan, "--next", "T6").status, 0);
  assert.equal(run(e, "write", "--stream", "m5", "--plan", plan, "--next", "board adapter").status, 0);
  assert.equal(run(e, "write", "--stream", "m6a", "--plan", plan, "--next", "T7").status, 0);
  assert.equal(run(e, "write", "--stream", "m5", "--plan", plan, "--next", "board claims").status, 0);
  assert.equal(stream(h, "m6a").next, "T7");
  assert.equal(stream(h, "m5").next, "board claims");
  assert.equal(stream(h, "m6a").consumed_at, null);
  assert.equal(fs.existsSync(path.join(dirOf(h), "m6a.lock")), false, "the lock is released");
});

test("show/consume with 0, 1 and 2 pending", () => {
  const { h, plan, e } = env();
  // 0
  const none = run(e, "show");
  assert.equal(none.status, 1);
  assert.match(none.stdout, /\(no streams\)/);
  assert.equal(run(e, "consume").status, 1);
  // 1: the old single-handoff behaviour
  assert.equal(run(e, "write", "--stream", "one", "--plan", plan, "--next", "a").status, 0);
  const one = run(e, "show");
  assert.equal(one.status, 0);
  assert.equal(JSON.parse(one.stdout).name, "one");
  // 2: the table, and consume must not guess
  assert.equal(run(e, "write", "--stream", "two", "--plan", plan, "--next", "b").status, 0);
  const two = run(e, "show");
  assert.equal(two.status, 1);
  assert.match(two.stdout, /^\s*NAME\s+STATE\s+AGE\s+NEXT$/m);
  assert.match(two.stdout, /one\s+pending/);
  assert.match(two.stdout, /two\s+pending/);
  const ambiguous = run(e, "consume");
  assert.equal(ambiguous.status, 2);
  assert.match(ambiguous.stderr, /handoff: 2 streams pending; name one with --stream/);
  // explicit name
  assert.equal(run(e, "consume", "--stream", "two").status, 0);
  assert.ok(stream(h, "two").consumed_at);
  assert.equal(stream(h, "one").consumed_at, null);
  const shown = run(e, "show", "--stream", "two");
  assert.equal(shown.status, 1, "a consumed stream is not pending");
  assert.equal(JSON.parse(shown.stdout).state, "consumed");
  assert.equal(run(e, "show", "--stream", "one").status, 0);
  assert.equal(run(e, "show", "--stream", "nope").status, 1, "nothing to act on, like note/done");
  assert.equal(run(e, "consume", "--stream", "nope").status, 1, "consume of an unknown stream is exit 1");
});

test("the table cuts NEXT to 80 chars and shows the age in hours", () => {
  const { plan, e } = env();
  const long = "L".repeat(100);
  assert.equal(run(e, "write", "--stream", "long", "--plan", plan, "--next", long).status, 0);
  const out = run(e, "list").stdout;
  assert.match(out, new RegExp(`L{80}\\s*$`, "m"));
  assert.doesNotMatch(out, new RegExp(`L{81}`));
  assert.match(out, /\bpending\s+0h\b/);
});

test("a stale stream is listed with the hint, is not pending, and only an explicit name resumes it", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "old", "--plan", plan, "--next", "finish it").status, 0);
  const s = stream(h, "old");
  s.written_at = new Date(Date.now() - 73 * HOUR).toISOString();
  fs.writeFileSync(jpath(h, "old"), JSON.stringify(s));
  const shown = run(e, "show");
  assert.equal(shown.status, 1, "a stale stream is never pending");
  assert.match(shown.stdout, /old\s+stale\s+73h\s+finish it/);
  assert.match(shown.stdout, /stale \(written 73h ago\): not auto-resumed; \/frood-next old to resume/);
  assert.equal(run(e, "consume").status, 1, "nothing pending, so the unnamed consume refuses");
  const named = run(e, "show", "--stream", "old");
  assert.equal(named.status, 1);
  assert.equal(JSON.parse(named.stdout).state, "stale");
  assert.equal(run(e, "consume", "--stream", "old").status, 0, "M4: an explicitly named stale stream resumes");
  assert.ok(stream(h, "old").consumed_at);
});

test("show (no single pending stream) appends the unstreamed tickets in cwd: queued, and hand-written", () => {
  const { h, plan, e } = env();
  const repo = fs.mkdtempSync(path.join(os.tmpdir(), "orch-repo-"));
  const tickets = path.join(repo, ".opencode", "board", "tickets");
  fs.mkdirSync(tickets, { recursive: true });
  const ticket = (id, extra) => fs.writeFileSync(path.join(tickets, `${id}.json`), JSON.stringify({ schema: 1, id, stage: "queued", ...extra }));
  ticket("queued-one"); // on the board, nobody streamed it
  ticket("streamed"); // on the board, a stream's next line names it
  ticket("stream"); // its id is only a substring of "streamed": still unstreamed (whole-token match)
  ticket("already-shipped", { stage: "shipped" }); // no longer waiting for a session
  fs.writeFileSync(path.join(tickets, "handwritten.json"), JSON.stringify({ stream: "handwritten", task: "open a ticket by hand" }));
  // The one stream that names "streamed" is stale, so show still exits 1 (no single pending stream).
  assert.equal(run(e, "write", "--stream", "streamed", "--plan", plan, "--next", "frood-gauntlet plan-streamed.md M1").status, 0);
  const s = stream(h, "streamed");
  s.written_at = new Date(Date.now() - 73 * HOUR).toISOString();
  fs.writeFileSync(jpath(h, "streamed"), JSON.stringify(s));

  const show = (cwd) => spawnSync(process.execPath, [BIN, "show"], { env: e, cwd, encoding: "utf8" });
  const shown = show(repo);
  assert.equal(shown.status, 1);
  assert.ok(shown.stdout.includes(`unstreamed tickets in ${repo}:`), shown.stdout);
  assert.match(shown.stdout, /queued-one — queued, not in any stream/);
  assert.match(shown.stdout, /handwritten — hand-written, not on the board/);
  assert.doesNotMatch(shown.stdout, /streamed —/, "a ticket a stream names is not unstreamed");
  assert.match(shown.stdout, /\n  stream — queued, not in any stream/, "a substring of a streamed id does not hide it");
  assert.doesNotMatch(shown.stdout, /already-shipped/, "a shipped ticket is not waiting for a session");

  // Nothing left unstreamed: no section at all.
  fs.rmSync(path.join(tickets, "queued-one.json"));
  fs.rmSync(path.join(tickets, "handwritten.json"));
  fs.rmSync(path.join(tickets, "stream.json"));
  const clean = show(repo);
  assert.equal(clean.status, 1);
  assert.doesNotMatch(clean.stdout, /unstreamed tickets/);

  // No board in this directory: no crash, no section (exit code unchanged).
  const bare = fs.mkdtempSync(path.join(os.tmpdir(), "orch-bare-"));
  const none = show(bare);
  assert.equal(none.status, 1, none.stderr);
  assert.doesNotMatch(none.stdout, /unstreamed tickets/);
});

test("parked and done streams are listed, never pending, and refuse consume", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "parked", "--plan", plan, "--next", "later", "--status", "parked").status, 0);
  assert.equal(run(e, "write", "--stream", "fin", "--plan", plan, "--next", "shipped").status, 0);
  assert.equal(run(e, "done", "--stream", "fin").status, 0);
  assert.equal(stream(h, "fin").status, "done");
  assert.ok(stream(h, "fin").done_at);
  const shown = run(e, "show");
  assert.equal(shown.status, 1, "neither is pending");
  assert.match(shown.stdout, /parked\s+parked/);
  assert.match(shown.stdout, /fin\s+done/);
  assert.equal(run(e, "consume", "--stream", "parked").status, 1);
  assert.equal(run(e, "consume", "--stream", "fin").status, 1);
  assert.equal(run(e, "done", "--stream", "nope").status, 1);
});

test("note updates next/done/waiting and leaves consumed_at and written_at alone", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "m6a", "--plan", plan, "--next", "T6", "--waiting", "owner").status, 0);
  assert.equal(run(e, "consume", "--stream", "m6a").status, 0);
  const before = stream(h, "m6a");
  assert.equal(run(e, "note", "--stream", "m6a", "--next", "T7 desk", "--done", "T6 merged").status, 0);
  const after = stream(h, "m6a");
  assert.equal(after.next, "T7 desk");
  assert.equal(after.done, "T6 merged");
  assert.equal(after.waiting, "owner", "a field the note omits keeps its value");
  assert.equal(after.consumed_at, before.consumed_at, "note never un-consumes a stream");
  assert.equal(after.written_at, before.written_at);
  assert.ok(after.noted_at);
  assert.equal(run(e, "note", "--stream", "nope", "--next", "x").status, 1);
});

// ------------------------------------------------------------------ events and acks

test("appendEvent dedupes by key and writes the documented line shape", () => {
  const { h } = env();
  withHome(h, () => {
    assert.equal(appendEvent("s", { key: "run:worker-r1:queued", kind: "queued", run: "worker-r1", out: path.join(h, "worker-r1.md"), pid: process.pid, pid_start: null, agent: "worker", ticket: path.join(h, "ticket.json") }), true);
    assert.equal(appendEvent("s", { key: "run:worker-r1:queued", kind: "queued", run: "worker-r1", out: path.join(h, "worker-r1.md") }), false);
    assert.equal(readEvents("s").length, 1);
    const ev = readEvents("s")[0];
    assert.deepEqual(Object.keys(ev).slice(0, 4), ["key", "kind", "at", "run"]);
    assert.equal(ev.kind, "queued");
    assert.ok(Date.parse(ev.at) > 0);
    assert.deepEqual(readEvents("nope"), []);
  });
});

test("unhandled ignores queued, and an ack clears an event; resolved is a second line on the same key", () => {
  const { h } = env();
  withHome(h, () => {
    appendEvent("s", { key: "run:worker-r1:queued", kind: "queued", run: "worker-r1", out: "o" });
    appendEvent("s", { key: "run:worker-r1:done", kind: "run-done", run: "worker-r1", out: "o", agent: "worker" });
    assert.deepEqual(unhandled("s").map((e) => e.key), ["run:worker-r1:done"], "queued is bookkeeping, never something to handle");
    assert.equal(appendAck("s", "run:worker-r1:done", "ACTION critic t.json o f-r1.md 1"), true);
    assert.deepEqual(unhandled("s"), []);
    assert.equal(readAcks("s").get("run:worker-r1:done"), "ACTION critic t.json o f-r1.md 1");
    assert.equal(appendAck("s", "run:worker-r1:done", "a different line"), false, "a key is decided once");
    assert.equal(readAcks("s").get("run:worker-r1:done"), "ACTION critic t.json o f-r1.md 1");
    assert.equal(appendAck("s", "run:worker-r1:done", "", { resolved: true }), true);
    assert.equal(appendAck("s", "run:worker-r1:done", "", { resolved: true }), false);
    assert.deepEqual(readAckLines("s").filter((l) => l.resolved).map((l) => [l.key, l.resolved]), [["run:worker-r1:done", true]]);
    assert.equal(readAcks("s").get("run:worker-r1:done"), "ACTION critic t.json o f-r1.md 1", "the decision line still wins");
    assert.equal(unhandled("s").length, 0);
  });
});

test("ack CLI: 0 for a known key, 1 for an unknown one, and --resolved marks the line", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "m6a", "--plan", plan, "--next", "T6").status, 0);
  withHome(h, () => appendEvent("m6a", { key: "run:worker-r1:done", kind: "run-done", run: "worker-r1", out: "o", agent: "worker" }));
  assert.equal(run(e, "ack", "--stream", "m6a", "--key", "nope", "--action", "ESCALATE x y").status, 1);
  assert.equal(run(e, "ack", "--stream", "m6a", "--key", "run:worker-r1:done", "--action", "ESCALATE none o", "--ticket", "t6-streams").status, 0);
  assert.equal(run(e, "ack", "--stream", "m6a", "--key", "run:worker-r1:done", "--resolved").status, 0);
  const lines = withHome(h, () => readAckLines("m6a"));
  assert.equal(lines.length, 2);
  assert.equal(lines[0].ticket, "t6-streams", "ack lines carry the ticket slug");
  assert.equal(lines[0].action, "ESCALATE none o");
  assert.equal(lines[1].resolved, true);
  assert.equal(run(e, "ack", "--stream", "m6a", "--key", "run:worker-r1:done").status, 2, "usage: neither --action nor --resolved");
});

test("concurrent appendEvent from two processes x 50 events loses none", async () => {
  const { h } = env();
  const script = path.join(h, "append.mjs");
  fs.writeFileSync(
    script,
    [
      `import { appendEvent } from ${JSON.stringify(pathToFileURL(BIN).href)};`,
      `const who = process.argv[2];`,
      `for (let i = 0; i < 50; i++) appendEvent("conc", { key: "k-" + who + "-" + i, kind: "run-done", run: "r" + who, out: "o" + i });`,
    ].join("\n"),
  );
  const e = { ...process.env, ORCH_HOME: h };
  const child = (who) =>
    new Promise((resolve, reject) => {
      const p = spawn(process.execPath, [script, who], { env: e, stdio: ["ignore", "ignore", "pipe"] });
      let err = "";
      p.stderr.on("data", (d) => (err += d));
      p.on("close", (code) => (code === 0 ? resolve() : reject(new Error(`child ${who} exited ${code}: ${err}`))));
    });
  await Promise.all([child("a"), child("b")]);
  withHome(h, () => assert.equal(readEvents("conc").length, 100));
  assert.equal(fs.existsSync(path.join(dirOf(h), "conc.lock")), false, "every lock was released");
});

test("the lock reclaims an owner whose pid is dead", () => {
  const { h } = env();
  const lock = path.join(dirOf(h), "dead.lock");
  fs.mkdirSync(lock, { recursive: true });
  fs.writeFileSync(path.join(lock, "owner"), JSON.stringify({ pid: 999999, pid_start: null, at: new Date().toISOString() }));
  withHome(h, () => assert.equal(appendEvent("dead", { key: "k1", kind: "run-done" }), true));
  assert.equal(fs.existsSync(lock), false, "the dead owner's lock is gone");
  assert.equal(withHome(h, () => readEvents("dead").length), 1);
});

// ------------------------------------------------------------------ list

test("a CORRUPT row does not break list", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "good", "--plan", plan, "--next", "ok").status, 0);
  fs.mkdirSync(dirOf(h), { recursive: true });
  fs.writeFileSync(jpath(h, "bad"), "{not json");
  const out = run(e, "list");
  assert.equal(out.status, 0);
  assert.match(out.stdout, /good\s+pending/);
  assert.match(out.stdout, /bad\s+CORRUPT/);
  const json = JSON.parse(run(e, "list", "--json").stdout);
  assert.deepEqual(json.map((s) => [s.name, s.state]), [["bad", "corrupt"], ["good", "pending"]]);
  assert.equal(json[1].unhandled, 0);
});

test("list prunes a done stream older than 14 days (all three files) and keeps younger ones", () => {
  const { h, plan, e } = env();
  for (const name of ["fresh", "gone"]) {
    assert.equal(run(e, "write", "--stream", name, "--plan", plan, "--next", "x").status, 0);
    assert.equal(run(e, "done", "--stream", name).status, 0);
    const s = stream(h, name);
    if (name === "gone") s.done_at = new Date(Date.now() - 15 * DAY).toISOString();
    fs.writeFileSync(jpath(h, name), JSON.stringify(s));
    fs.writeFileSync(path.join(dirOf(h), `${name}.events.jsonl`), "");
    fs.writeFileSync(path.join(dirOf(h), `${name}.acks.jsonl`), "");
  }
  assert.equal(run(e, "list").status, 0);
  for (const suffix of [".json", ".events.jsonl", ".acks.jsonl"]) {
    assert.equal(fs.existsSync(path.join(dirOf(h), `gone${suffix}`)), false, `gone${suffix} is pruned`);
    assert.equal(fs.existsSync(path.join(dirOf(h), `fresh${suffix}`)), true, `fresh${suffix} is kept`);
  }
});

// ------------------------------------------------------------------ the SessionStart hook

test("SessionStart hook: pending streams and the unhandled count; silent on resume, compact and once consumed", () => {
  const { h, plan, e } = env();
  assert.equal(hook(e, "clear").stdout, "", "no stream -> silent");
  assert.equal(hook(e, "startup").stdout, "");
  assert.equal(run(e, "write", "--stream", "m6a", "--plan", plan, "--next", "T6 named streams " + "x".repeat(200)).status, 0);
  const first = JSON.parse(hook(e, "clear").stdout).hookSpecificOutput;
  assert.equal(first.hookEventName, "SessionStart");
  const lines = first.additionalContext.split("\n");
  assert.match(lines[0], /^orchestrator stream m6a: next = T6 named streams /);
  assert.equal(lines[0].length, "orchestrator stream m6a: next = ".length + 120, "next is cut to 120 chars");
  assert.match(first.additionalContext, /When the owner types \/frood-next \(or asks to continue\), run \/frood-next <stream> for the named stream/);
  assert.equal(hook(e, "resume").stdout, "");
  assert.equal(hook(e, "compact").stdout, "");

  withHome(h, () => appendEvent("m6a", { key: "run:worker-r1:done", kind: "run-done", run: "worker-r1", out: "o", agent: "worker" }));
  assert.match(hook(e, "clear").stdout, /1 unhandled desk events across 1 streams — run \/frood-desk/);
  withHome(h, () => appendAck("m6a", "run:worker-r1:done", "ESCALATE none o"));
  assert.doesNotMatch(hook(e, "clear").stdout, /unhandled/);
  assert.equal(run(e, "consume", "--stream", "m6a").status, 0);
  assert.equal(hook(e, "clear").stdout, "", "a consumed stream is not announced");
});

test("SessionStart hook lists at most six pending streams, newest first", () => {
  const { plan, e } = env();
  for (let i = 0; i < 8; i++) {
    assert.equal(run(e, "write", "--stream", `s${i}`, "--plan", plan, "--next", `n${i}`).status, 0);
  }
  const out = JSON.parse(hook(e, "clear").stdout).hookSpecificOutput.additionalContext;
  const shown = out.split("\n").filter((l) => l.startsWith("orchestrator stream "));
  assert.equal(shown.length, 6);
  assert.match(shown[0], /^orchestrator stream s7: next = n7$/);
});

test("SessionStart hook falls back to streams/*.json when handoff.mjs cannot be imported", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "m5", "--plan", plan, "--next", "board adapter").status, 0);
  const broken = { ...e, ORCH_REPO: path.join(h, "no-such-repo") };
  const out = hook(broken, "clear").stdout;
  assert.match(JSON.parse(out).hookSpecificOutput.additionalContext, /^orchestrator stream m5: next = board adapter/);
  // the fallback is read-only: no events are read, so the desk count is never claimed
  assert.doesNotMatch(out, /unhandled/);
  // and a garbage legacy file never breaks session start
  const legacy = path.join(h, ".config", "orchestrator", "handoff.json");
  fs.writeFileSync(legacy, "{broken");
  assert.equal(hook(broken, "clear").status, 0);
});

test("withStreamLock never deletes a lock that was reclaimed by a new owner while fn ran", () => {
  const { h } = env();
  const lock = path.join(dirOf(h), "m6a.lock");
  withHome(h, () => {
    withStreamLock("m6a", () => {
      // simulate a reclaim: another holder now owns the directory
      fs.writeFileSync(path.join(lock, "owner"), JSON.stringify({ pid: process.pid + 1, pid_start: "other", at: new Date().toISOString() }));
    });
    assert.ok(fs.existsSync(lock), "the new owner's lock survives the old holder's finally");
    fs.rmSync(lock, { recursive: true, force: true });
    withStreamLock("m6a", () => {});
    assert.ok(!fs.existsSync(lock), "a lock that is still ours is released");
  });
});

// ---------------------------------------------------------------- session title (UserPromptSubmit)
const titleHook = (e, prompt, cwd = "C:/x/acme-app") =>
  spawnSync(process.execPath, [HOOK], { env: e, input: JSON.stringify({ session_id: "x", hook_event_name: "UserPromptSubmit", prompt, cwd }), encoding: "utf8" });
const titleOf = (r) => (r.stdout ? JSON.parse(r.stdout).hookSpecificOutput.sessionTitle : "");

test("UserPromptSubmit: /frood-next names the tab after the stream's module, not the command", () => {
  const { h, plan, e } = env();
  const repo = path.join(h, "acme-app");
  fs.mkdirSync(repo, { recursive: true });
  const next = "/frood-gauntlet .opencode/plans/plan-widgets.md R4 — UI on the thread view; worktree worktree/w-r4";
  assert.equal(run(e, "write", "--stream", "default", "--plan", plan, "--next", next, "--repo", repo).status, 0);
  const r = titleHook(e, "/frood-next");
  assert.equal(r.status, 0);
  const out = JSON.parse(r.stdout).hookSpecificOutput;
  assert.equal(out.hookEventName, "UserPromptSubmit");
  assert.equal(out.sessionTitle, "[default] acme-app: R4 — UI on the thread view");
  assert.equal(titleOf(titleHook(e, "/frood-next default")), "[default] acme-app: R4 — UI on the thread view");
  assert.ok(titleOf(titleHook(e, "/frood-next default")).length <= 60);
});

test("UserPromptSubmit: /frood-gauntlet titles from its args; other prompts and unknown streams print nothing", () => {
  const { e } = env();
  // gauntlet path has no stream, so no prefix
  assert.equal(titleOf(titleHook(e, "/frood-gauntlet .opencode/plans/plan-widgets.md R4")), "acme-app: R4 — widgets");
  for (const p of ["resume", "/frood-next nosuch", "/frood-next", "fix the /frood-next bug"]) {
    const r = titleHook(e, p);
    assert.equal(r.status, 0);
    assert.equal(r.stdout, "", p);
  }
});

test("UserPromptSubmit: two pending streams and a bare /frood-next set no title (never guess)", () => {
  const { h, plan, e } = env();
  const repo = path.join(h, "test-repo");
  fs.mkdirSync(repo, { recursive: true });
  assert.equal(run(e, "write", "--stream", "a", "--plan", plan, "--next", "/frood-gauntlet p.md M1", "--repo", repo).status, 0);
  assert.equal(run(e, "write", "--stream", "b", "--plan", plan, "--next", "/frood-gauntlet p.md M2", "--repo", repo).status, 0);
  assert.equal(titleHook(e, "/frood-next").stdout, "");
  assert.match(titleOf(titleHook(e, "/frood-next b")), /^\[b\] test-repo: M2 — p$/);
});

test("UserPromptSubmit: title respects TITLE_MAX on composed string with stream prefix", () => {
  const { h, plan, e } = env();
  const repo = path.join(h, "acme-app");
  fs.mkdirSync(repo, { recursive: true });
  // Long title that will exceed 60 chars when prefixed with "[default] "
  const longNext = "/frood-gauntlet .opencode/plans/plan.md R1 — " + "x".repeat(60);
  assert.equal(run(e, "write", "--stream", "default", "--plan", plan, "--next", longNext, "--repo", repo).status, 0);
  const title = titleOf(titleHook(e, "/frood-next default"));
  assert.ok(title.length <= 60, `title length ${title.length} exceeds TITLE_MAX`);
  assert.match(title, /^\[default\] acme-app: R1 — x+$/);
});

test("UserPromptSubmit: long stream name eats title body but still truncates at TITLE_MAX", () => {
  const { h, plan, e } = env();
  const repo = path.join(h, "acme-app");
  fs.mkdirSync(repo, { recursive: true });
  // Long stream name (40 chars max per NAME_RE) - the prefix "[...] " takes most of TITLE_MAX
  const longStream = "very-long-stream-name-that-is-valid"; // 39 chars
  const next = "/frood-gauntlet .opencode/plans/plan.md R1 — some work";
  assert.equal(run(e, "write", "--stream", longStream, "--plan", plan, "--next", next, "--repo", repo).status, 0);
  const title = titleOf(titleHook(e, "/frood-next " + longStream));
  assert.ok(title.length <= 60, `title length ${title.length} exceeds TITLE_MAX`);
  assert.match(title, /^\[very-long-stream-name-that-is-valid\] /);
  // The stream prefix should be present even if it leaves little room for the body
});

// ------------------------------------------------------------------ stream lease (claim / release)

const LEASE = ["held_by", "held_session", "held_at", "taken_from", "handback_to"];
const leaseLines = (h, n) => {
  try {
    return fs.readFileSync(path.join(dirOf(h), `${n}.lease.jsonl`), "utf8").split("\n").filter(Boolean).map((l) => JSON.parse(l));
  } catch {
    return [];
  }
};
const eventsRaw = (h, n) => {
  try {
    return fs.readFileSync(path.join(dirOf(h), `${n}.events.jsonl`), "utf8");
  } catch {
    return "";
  }
};
function leased() {
  const x = env();
  assert.equal(run(x.e, "write", "--stream", "s1", "--plan", x.plan, "--next", "M1").status, 0);
  return x;
}

test("claim on a free stream sets the holder; claim again by the same session refreshes claim.at and keeps held_at", () => {
  const { e, h } = leased();
  const c = run(e, "claim", "--stream", "s1", "--by", "cc", "--session", "sess-1");
  assert.equal(c.status, 0);
  assert.equal(c.stderr, "");
  const o = JSON.parse(c.stdout);
  assert.equal(o.held_by, "cc");
  assert.equal(o.held_session, "sess-1");
  assert.equal(o.taken_from, null);
  assert.equal(o.handback_to, null);
  assert.ok(o.held_at);
  const before = stream(h, "s1");
  // same session again -> refresh claim.at, held_at unchanged
  const c2 = run(e, "claim", "--stream", "s1", "--by", "cc", "--session", "sess-1");
  assert.equal(c2.status, 0);
  const after = stream(h, "s1");
  assert.equal(after.held_at, before.held_at);
  assert.equal(after.held_session, "sess-1");
  assert.ok(after.claim.at > before.claim.at, "claim.at should move on refresh");
  for (const k of ["written_at", "consumed_at", "next", "done", "waiting", "status", "done_at"]) assert.equal(after[k], before[k], k);
});

test("claim by the other harness without --takeover: exit 3, exact stderr, file untouched", () => {
  const { e, h } = leased();
  const first = JSON.parse(run(e, "claim", "--stream", "s1", "--by", "cc", "--session", "sess-1").stdout);
  const bytes = fs.readFileSync(jpath(h, "s1"));
  const c = run(e, "claim", "--stream", "s1", "--by", "oc");
  assert.equal(c.status, 3);
  assert.equal(c.stdout, "");
  assert.equal(c.stderr.trim(), `handoff: stream s1 held by cc (session sess-1) since ${first.held_at}`);
  assert.deepEqual(fs.readFileSync(jpath(h, "s1")), bytes);
});

test("claim --takeover records taken_from and a lease line, never an event; two takeovers both recorded", () => {
  const { e, h } = leased();
  run(e, "claim", "--stream", "s1", "--by", "cc", "--session", "a1");
  const evBefore = eventsRaw(h, "s1");
  const t = run(e, "claim", "--stream", "s1", "--by", "oc", "--session", "b1", "--takeover");
  assert.equal(t.status, 0);
  const o = JSON.parse(t.stdout);
  assert.equal(o.held_by, "oc");
  assert.equal(o.taken_from, "cc");
  let lines = leaseLines(h, "s1");
  assert.equal(lines.length, 1);
  assert.deepEqual(lines[0], { key: `takeover:${o.held_at}`, kind: "takeover", from: "cc", from_session: "a1", to: "oc", to_session: "b1", at: o.held_at });
  assert.equal(eventsRaw(h, "s1"), evBefore);
  const t2 = run(e, "claim", "--stream", "s1", "--by", "cc", "--takeover");
  assert.equal(t2.status, 0);
  lines = leaseLines(h, "s1");
  assert.equal(lines.length, 2);
  assert.equal(lines[1].from, "oc");
  assert.equal(lines[1].to_session, null);
  assert.equal(JSON.parse(t2.stdout).taken_from, "oc");
});

test("after a takeover the lock dir is gone, the lock is usable, and unhandled() is empty", () => {
  const { e, h } = leased();
  run(e, "claim", "--stream", "s1", "--by", "cc");
  assert.equal(run(e, "claim", "--stream", "s1", "--by", "oc", "--takeover").status, 0);
  assert.equal(fs.existsSync(path.join(dirOf(h), "s1.lock")), false);
  withHome(h, () => {
    assert.equal(withStreamLock("s1", () => "ok"), "ok");
    assert.deepEqual(unhandled("s1"), []);
  });
});

test("claim on a missing, parked and done stream exits 1", () => {
  const { e, plan } = leased();
  const m = run(e, "claim", "--stream", "nope", "--by", "cc");
  assert.equal(m.status, 1);
  assert.equal(m.stderr.trim(), "handoff: no stream nope");
  run(e, "write", "--stream", "pk", "--plan", plan, "--next", "x", "--status", "parked");
  const p = run(e, "claim", "--stream", "pk", "--by", "cc");
  assert.equal(p.status, 1);
  assert.equal(p.stderr.trim(), "handoff: stream pk is parked");
  run(e, "done", "--stream", "s1");
  const d = run(e, "claim", "--stream", "s1", "--by", "cc");
  assert.equal(d.status, 1);
  assert.equal(d.stderr.trim(), "handoff: stream s1 is done");
});

test("release: ours clears the holder and keeps taken_from; --to records a handback; free is a no-op; other is refused", () => {
  const { e, h } = leased();
  run(e, "claim", "--stream", "s1", "--by", "cc");
  run(e, "claim", "--stream", "s1", "--by", "oc", "--takeover");
  const r = run(e, "release", "--stream", "s1", "--by", "oc");
  assert.equal(r.status, 0);
  const o = JSON.parse(r.stdout);
  assert.deepEqual([o.held_by, o.held_session, o.held_at, o.handback_to, o.taken_from], [null, null, null, null, "cc"]);
  assert.equal(leaseLines(h, "s1").length, 1, "no handback line without --to");
  const bytes = fs.readFileSync(jpath(h, "s1"));
  assert.equal(run(e, "release", "--stream", "s1", "--by", "cc").status, 0);
  assert.deepEqual(fs.readFileSync(jpath(h, "s1")), bytes);
  run(e, "claim", "--stream", "s1", "--by", "cc");
  const bytes2 = fs.readFileSync(jpath(h, "s1"));
  const x = run(e, "release", "--stream", "s1", "--by", "oc");
  assert.equal(x.status, 3);
  assert.match(x.stderr, /^handoff: stream s1 held by cc \(session -\) since /);
  assert.deepEqual(fs.readFileSync(jpath(h, "s1")), bytes2);
  const t = run(e, "release", "--stream", "s1", "--by", "cc", "--to", "oc");
  assert.equal(t.status, 0);
  assert.equal(JSON.parse(t.stdout).handback_to, "oc");
  const lines = leaseLines(h, "s1");
  assert.equal(lines.length, 2);
  assert.equal(lines[1].kind, "handback");
  assert.equal(lines[1].key, `handback:${lines[1].at}`);
  assert.deepEqual([lines[1].from, lines[1].to], ["cc", "oc"]);
  assert.equal(run(e, "release", "--stream", "s1", "--by", "cc", "--to", "cc").status, 0);
  assert.equal(stream(h, "s1").handback_to, "cc");
  assert.equal(JSON.parse(run(e, "claim", "--stream", "s1", "--by", "oc").stdout).handback_to, null);
});

test("write keeps all five lease fields; consume keeps the lease; done clears the holder", () => {
  const { e, h, plan } = leased();
  run(e, "claim", "--stream", "s1", "--by", "cc", "--session", "k1");
  run(e, "claim", "--stream", "s1", "--by", "oc", "--takeover");
  run(e, "claim", "--stream", "s1", "--by", "cc", "--takeover");
  const before = stream(h, "s1");
  assert.equal(run(e, "write", "--stream", "s1", "--plan", plan, "--next", "M2").status, 0);
  const w = stream(h, "s1");
  for (const k of LEASE) assert.equal(w[k], before[k], k);
  assert.equal(w.taken_from, "oc");
  assert.equal(run(e, "consume", "--stream", "s1").status, 0);
  const c = stream(h, "s1");
  assert.ok(c.consumed_at);
  for (const k of LEASE) assert.equal(c[k], before[k], k);
  assert.equal(run(e, "done", "--stream", "s1").status, 0);
  const d = stream(h, "s1");
  assert.deepEqual([d.held_by, d.held_session, d.held_at], [null, null, null]);
  assert.equal(d.taken_from, "oc");
});

test("write --by / note --by are refused when the other harness holds the lease, allowed when ours or free", () => {
  const { e, h, plan } = leased();
  assert.equal(run(e, "write", "--stream", "s1", "--plan", plan, "--next", "free", "--by", "oc").status, 0);
  assert.equal(stream(h, "s1").held_by, null, "a write does not claim");
  assert.equal(run(e, "note", "--stream", "s1", "--next", "n-free", "--by", "oc").status, 0);
  run(e, "claim", "--stream", "s1", "--by", "cc", "--session", "z");
  const bytes = fs.readFileSync(jpath(h, "s1"));
  for (const args of [["write", "--stream", "s1", "--plan", plan, "--next", "bad", "--by", "oc"], ["note", "--stream", "s1", "--next", "bad", "--by", "oc"]]) {
    const r = run(e, ...args);
    assert.equal(r.status, 3);
    assert.match(r.stderr, /^handoff: stream s1 held by cc \(session z\) since /);
    assert.deepEqual(fs.readFileSync(jpath(h, "s1")), bytes);
  }
  assert.equal(run(e, "write", "--stream", "s1", "--plan", plan, "--next", "ours", "--by", "cc").status, 0);
  assert.equal(run(e, "note", "--stream", "s1", "--next", "n-ours", "--by", "cc").status, 0);
  assert.equal(stream(h, "s1").held_by, "cc");
  assert.equal(run(e, "note", "--stream", "s1", "--next", "no-by").status, 0, "no --by: back-compat");
});

test("a legacy pointer without lease keys shows five nulls and can be claimed; list --json has the fields", () => {
  const { e, h } = env();
  fs.mkdirSync(dirOf(h), { recursive: true });
  fs.writeFileSync(jpath(h, "old"), JSON.stringify({ name: "old", repo: "", plan: "p", status: "active", next: "n", done: "", waiting: "", written_at: new Date().toISOString(), written_by: "", consumed_at: null, done_at: null }));
  const s = JSON.parse(run(e, "show", "--stream", "old").stdout);
  for (const k of LEASE) assert.equal(s[k], null, k);
  assert.equal(s.state, "pending");
  const l = JSON.parse(run(e, "list", "--json").stdout);
  for (const k of LEASE) assert.equal(l[0][k], null, k);
  const c = run(e, "claim", "--stream", "old", "--by", "oc");
  assert.equal(c.status, 0);
  assert.equal(JSON.parse(c.stdout).held_by, "oc");
  assert.equal(JSON.parse(run(e, "list", "--json").stdout)[0].held_by, "oc");
});

test("the table shows held-by and handed-back lines under the row, columns unchanged", () => {
  const { e } = leased();
  const plain = run(e, "list").stdout;
  run(e, "claim", "--stream", "s1", "--by", "cc", "--session", "q");
  const held = run(e, "list").stdout.split("\n");
  assert.equal(held[0], plain.split("\n")[0], "header line unchanged");
  assert.match(held[1], /^s1\s+pending\s+0h\s+M1$/);
  assert.match(held[2], /^ {2}held by cc \(session q\) since \d{4}-/);
  run(e, "release", "--stream", "s1", "--by", "cc", "--to", "oc");
  const back = run(e, "list").stdout.split("\n");
  assert.equal(back[2], "  handed back to oc");
});

test("bad --by / --to / --session and a missing --stream exit 2", () => {
  const { e } = leased();
  const cases = [
    [["claim", "--stream", "s1", "--by", "xx"], "handoff: --by must be cc or oc"],
    [["claim", "--stream", "s1"], "handoff: --by must be cc or oc"],
    [["release", "--stream", "s1", "--by", "cc", "--to", "zz"], "handoff: --to must be cc or oc"],
    [["claim", "--stream", "s1", "--by", "cc", "--session", "bad id!"], "handoff: bad --session"],
    [["claim", "--by", "cc"], "handoff: --stream is required"],
    [["release", "--by", "cc"], "handoff: --stream is required"],
  ];
  for (const [args, msg] of cases) {
    const r = run(e, ...args);
    assert.equal(r.status, 2, args.join(" "));
    assert.equal(r.stderr.trim(), msg);
  }
  assert.equal(run(e, "write", "--stream", "s1", "--plan", "x", "--next", "y", "--by", "nope").status, 2);
  assert.equal(run(e, "note", "--stream", "s1", "--by", "nope").status, 2);
});

test("concurrent claim by two harnesses: exactly one wins, the other gets exit 3", async () => {
  const { e } = leased();
  const go = (by) =>
    new Promise((resolve) => {
      const p = spawn(process.execPath, [BIN, "claim", "--stream", "s1", "--by", by], { env: e });
      p.on("close", (code) => resolve(code));
    });
  const codes = (await Promise.all([go("cc"), go("oc")])).sort();
  assert.deepEqual(codes, [0, 3]);
});

test("pruneStream (list of an old done stream) removes the lease file too", () => {
  const { e, h } = leased();
  run(e, "claim", "--stream", "s1", "--by", "cc");
  run(e, "claim", "--stream", "s1", "--by", "oc", "--takeover");
  run(e, "done", "--stream", "s1");
  const p = stream(h, "s1");
  p.done_at = new Date(Date.now() - 20 * DAY).toISOString();
  fs.writeFileSync(jpath(h, "s1"), JSON.stringify(p));
  assert.ok(fs.existsSync(path.join(dirOf(h), "s1.lease.jsonl")));
  assert.equal(run(e, "list").status, 0);
  assert.equal(fs.existsSync(path.join(dirOf(h), "s1.lease.jsonl")), false);
  assert.equal(fs.existsSync(jpath(h, "s1")), false);
});

// ------------------------------------------------------------------ session claim (with --session)

test("claim --session: first claim ok; same session refresh moves at; different session + fresh claim -> exit 4 naming holder; --takeover wins and records taken_from", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c1", "--plan", plan, "--next", "M1").status, 0);

  // first claim by sess-a
  const c1 = run(e, "claim", "--stream", "c1", "--by", "cc", "--session", "sess-a");
  assert.equal(c1.status, 0);
  const o1 = JSON.parse(c1.stdout);
  assert.equal(o1.claim.session, "sess-a");
  assert.ok(o1.claim.at);
  assert.equal(o1.claim.taken_from, null);
  const at1 = o1.claim.at;

  // same session refresh -> exit 0, at moves
  const c2 = run(e, "claim", "--stream", "c1", "--by", "cc", "--session", "sess-a");
  assert.equal(c2.status, 0);
  const o2 = JSON.parse(c2.stdout);
  assert.equal(o2.claim.session, "sess-a");
  assert.ok(o2.claim.at > at1, "at should move on refresh");
  assert.equal(o2.claim.taken_from, null, "taken_from stays null on refresh");

  // different session with fresh claim -> exit 4, names holder and age
  const c3 = run(e, "claim", "--stream", "c1", "--by", "cc", "--session", "sess-b");
  assert.equal(c3.status, 4);
  assert.match(c3.stderr, /handoff: stream c1 claimed by session sess-a \(.+ ago\); re-run with --takeover to take it over/);
  // file unchanged
  const s3 = stream(h, "c1");
  assert.equal(s3.claim.session, "sess-a");
  assert.equal(s3.claim.taken_from, null);

  // takeover wins, records taken_from
  const c4 = run(e, "claim", "--stream", "c1", "--by", "cc", "--session", "sess-b", "--takeover");
  assert.equal(c4.status, 0);
  const o4 = JSON.parse(c4.stdout);
  assert.equal(o4.claim.session, "sess-b");
  assert.equal(o4.claim.taken_from, "sess-a");
  assert.ok(o4.claim.at > o2.claim.at);
});

test("claim --session: stale claim (via ORCH_CLAIM_TTL_MIN=0) auto-expires; note on stderr", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c2", "--plan", plan, "--next", "M1").status, 0);

  // claim by sess-a
  run(e, "claim", "--stream", "c2", "--by", "cc", "--session", "sess-a");

  // now claim by sess-b with TTL=0 (every claim is stale) -> should auto-expire
  const c = runWithEnv(e, { ORCH_CLAIM_TTL_MIN: "0" }, "claim", "--stream", "c2", "--by", "cc", "--session", "sess-b");
  assert.equal(c.status, 0);
  const o = JSON.parse(c.stdout);
  assert.equal(o.claim.session, "sess-b");
  assert.equal(o.claim.taken_from, "sess-a");
  assert.match(c.stderr, /claim by session sess-a on stream c2 expired \(.+ ago\); replaced/);
});

test("claim --session: stale claim (old timestamp) auto-expires", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c3", "--plan", plan, "--next", "M1").status, 0);

  // claim by sess-a with old timestamp (20 minutes ago, TTL=10 min)
  const oldTime = new Date(Date.now() - 20 * 60_000).toISOString();
  writeClaimWithTime(h, "c3", { session: "sess-a", at: oldTime, taken_from: null }, oldTime);

  // claim by sess-b with TTL=10 min -> should auto-expire
  const c = runWithEnv(e, { ORCH_CLAIM_TTL_MIN: "10" }, "claim", "--stream", "c3", "--by", "cc", "--session", "sess-b");
  assert.equal(c.status, 0);
  const o = JSON.parse(c.stdout);
  assert.equal(o.claim.session, "sess-b");
  assert.equal(o.claim.taken_from, "sess-a");
  assert.match(c.stderr, /claim by session sess-a on stream c3 expired \(.+ ago\); replaced/);
});

test("consume --session mirrors claim: first ok; same session refresh; different session fresh -> exit 4; --takeover wins", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c4", "--plan", plan, "--next", "M1").status, 0);

  // first consume by sess-a (creates claim)
  const c1 = run(e, "consume", "--stream", "c4", "--session", "sess-a");
  assert.equal(c1.status, 0);
  const o1 = JSON.parse(c1.stdout);
  assert.ok(o1.consumed_at);
  assert.equal(o1.claim.session, "sess-a");
  const at1 = o1.claim.at;

  // same session refresh -> exit 0, claim.at moves
  const c2 = run(e, "consume", "--stream", "c4", "--session", "sess-a");
  assert.equal(c2.status, 0);
  const o2 = JSON.parse(c2.stdout);
  assert.equal(o2.claim.session, "sess-a");
  assert.ok(o2.claim.at > at1);

  // different session with fresh claim -> exit 4
  const c3 = run(e, "consume", "--stream", "c4", "--session", "sess-b");
  assert.equal(c3.status, 4);
  assert.match(c3.stderr, /handoff: stream c4 claimed by session sess-a \(.+ ago\); re-run with --takeover to take it over/);
  // file unchanged
  const s3 = stream(h, "c4");
  assert.equal(s3.claim.session, "sess-a");

  // takeover wins
  const c4 = run(e, "consume", "--stream", "c4", "--session", "sess-b", "--takeover");
  assert.equal(c4.status, 0);
  const o4 = JSON.parse(c4.stdout);
  assert.equal(o4.claim.session, "sess-b");
  assert.equal(o4.claim.taken_from, "sess-a");
});

test("claim/consume without --session: existing tests still pass (byte-identical behaviour)", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c5", "--plan", plan, "--next", "M1").status, 0);

  // claim without --session still works
  const c1 = run(e, "claim", "--stream", "c5", "--by", "cc");
  assert.equal(c1.status, 0);
  const o1 = JSON.parse(c1.stdout);
  assert.equal(o1.held_by, "cc");
  assert.equal(o1.held_session, null);
  assert.equal(o1.claim, null, "no session -> no claim written");

  // consume without --session still works
  const c2 = run(e, "consume", "--stream", "c5");
  assert.equal(c2.status, 0);
  const o2 = JSON.parse(c2.stdout);
  assert.ok(o2.consumed_at);
  assert.equal(o2.claim, null, "no session -> claim stays null");

  // claim then claim other harness without takeover -> exit 3 (lease refusal)
  run(e, "claim", "--stream", "c5", "--by", "cc");
  const c3 = run(e, "claim", "--stream", "c5", "--by", "oc");
  assert.equal(c3.status, 3);
  assert.match(c3.stderr, /handoff: stream c5 held by cc/);
});

test("write clears claim; done clears claim; release by holder clears claim", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c6", "--plan", plan, "--next", "M1").status, 0);
  run(e, "claim", "--stream", "c6", "--by", "cc", "--session", "sess-a");
  assert.equal(stream(h, "c6").claim.session, "sess-a");

  // write clears claim
  run(e, "write", "--stream", "c6", "--plan", plan, "--next", "M2", "--by", "cc");
  assert.equal(stream(h, "c6").claim, null, "write clears claim");

  // claim again, then done clears claim
  run(e, "claim", "--stream", "c6", "--by", "cc", "--session", "sess-b");
  assert.equal(stream(h, "c6").claim.session, "sess-b");
  run(e, "done", "--stream", "c6");
  assert.equal(stream(h, "c6").claim, null, "done clears claim");

  // claim again, then release by holder clears claim
  run(e, "write", "--stream", "c6", "--plan", plan, "--next", "M3");
  run(e, "claim", "--stream", "c6", "--by", "cc", "--session", "sess-c");
  assert.equal(stream(h, "c6").claim.session, "sess-c");
  run(e, "release", "--stream", "c6", "--by", "cc");
  assert.equal(stream(h, "c6").claim, null, "release by holder clears claim");
  assert.equal(stream(h, "c6").held_by, null);
});

test("claim --session unreadable at -> treated as stale and replaced", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c7", "--plan", plan, "--next", "M1").status, 0);

  // manually write a claim with bad at
  const s = stream(h, "c7");
  s.claim = { session: "sess-old", at: "not-a-date", taken_from: null };
  fs.writeFileSync(jpath(h, "c7"), JSON.stringify(s, null, 2));

  // new claim should replace it
  const c = run(e, "claim", "--stream", "c7", "--by", "cc", "--session", "sess-new");
  assert.equal(c.status, 0);
  const o = JSON.parse(c.stdout);
  assert.equal(o.claim.session, "sess-new");
  assert.equal(o.claim.taken_from, "sess-old");
  assert.match(c.stderr, /claim by session sess-old on stream c7 had no readable at; replaced/);
});

test("readStream exposes claim as additive field (unknown-field readers keep working)", async () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "c8", "--plan", plan, "--next", "M1").status, 0);
  run(e, "claim", "--stream", "c8", "--by", "cc", "--session", "sess-x");

  const mod = await import(pathToFileURL(BIN).href);
  withHome(h, () => {
    const s = mod.readStream("c8");
    assert.ok(s);
    assert.equal(s.claim.session, "sess-x");
    assert.ok(s.claim.at);
    // also verify old fields still present
    assert.equal(s.name, "c8");
    assert.equal(s.next, "M1");
    assert.equal(s.state, "pending");
  });
});
test("streamTitle names the tab after the work: [stream] repo: module — what", () => {
  assert.equal(streamTitle({ name: "m6a", repo: "/r/sales-team-toolbox", next: "/frood-gauntlet plan-a.md m3 -- pipeline stages" }), "[m6a] sales-team-toolbox: m3 — pipeline stages");
  assert.equal(streamTitle({ name: "m6a", repo: "", next: "after /frood-desk merges: fresh tab → /frood-next m6a" }), "[m6a] after /frood-desk merges: fresh tab → /frood-next m6a");
  assert.equal(streamTitle({ name: "m6a", repo: "/r/x", next: "" }), "[m6a] x: m6a");
  assert.equal(streamTitle(null), "");
  assert.equal(streamTitle("nope"), "");
  const long = streamTitle({ name: "video-studio", repo: "r", next: "/frood-gauntlet plan-video-studio.md m3-pipeline-service -- " + "x".repeat(200) });
  assert.ok(long.length <= 60, long);
  assert.ok(long.startsWith("[video-studio] "), long);
});

// ------------------------------------------------------------------ progress write keeps claim

test("progress write --session matching claim keeps claim (at refreshed) and consumed_at; state stays consumed", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "p1", "--plan", plan, "--next", "M1").status, 0);
  run(e, "claim", "--stream", "p1", "--by", "cc", "--session", "sess-a");
  run(e, "consume", "--stream", "p1", "--session", "sess-a");
  const before = JSON.parse(run(e, "show", "--stream", "p1").stdout);
  assert.equal(before.claim.session, "sess-a");
  assert.equal(before.state, "consumed");
  assert.ok(before.consumed_at);

  const w = run(e, "write", "--stream", "p1", "--plan", plan, "--next", "M2", "--session", "sess-a");
  assert.equal(w.status, 0);
  const after = JSON.parse(run(e, "show", "--stream", "p1").stdout);
  assert.equal(after.claim.session, "sess-a", "claim kept by progress write");
  assert.ok(after.claim.at > before.claim.at, "claim.at refreshed on progress write");
  assert.ok(after.consumed_at, "consumed_at kept");
  assert.equal(after.state, "consumed", "state stays consumed");
});

test("progress write --session A --release clears claim and consumed_at; state becomes pending", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "p2", "--plan", plan, "--next", "M1").status, 0);
  run(e, "claim", "--stream", "p2", "--by", "cc", "--session", "sess-a");
  run(e, "consume", "--stream", "p2", "--session", "sess-a");
  const w = run(e, "write", "--stream", "p2", "--plan", plan, "--next", "M2", "--session", "sess-a", "--release");
  assert.equal(w.status, 0);
  const after = JSON.parse(run(e, "show", "--stream", "p2").stdout);
  assert.equal(after.claim, null, "claim cleared by --release");
  assert.equal(after.consumed_at, null, "consumed_at cleared by --release");
  assert.equal(after.state, "pending", "state becomes pending");
});

test("write --session B (different session) is a true handoff: clears claim, state pending", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "p3", "--plan", plan, "--next", "M1").status, 0);
  run(e, "claim", "--stream", "p3", "--by", "cc", "--session", "sess-a");
  run(e, "consume", "--stream", "p3", "--session", "sess-a");
  const w = run(e, "write", "--stream", "p3", "--plan", plan, "--next", "M2", "--session", "sess-b");
  assert.equal(w.status, 0);
  const after = JSON.parse(run(e, "show", "--stream", "p3").stdout);
  assert.equal(after.claim, null, "claim cleared by different session");
  assert.equal(after.consumed_at, null, "consumed_at cleared");
  assert.equal(after.state, "pending", "state becomes pending");
});

test("write with no --session clears claim (unchanged behaviour); state pending", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "p4", "--plan", plan, "--next", "M1").status, 0);
  run(e, "claim", "--stream", "p4", "--by", "cc", "--session", "sess-a");
  run(e, "consume", "--stream", "p4", "--session", "sess-a");
  const w = run(e, "write", "--stream", "p4", "--plan", plan, "--next", "M2");
  assert.equal(w.status, 0);
  const after = JSON.parse(run(e, "show", "--stream", "p4").stdout);
  assert.equal(after.claim, null, "claim cleared when no --session");
  assert.equal(after.consumed_at, null, "consumed_at cleared");
  assert.equal(after.state, "pending", "state becomes pending");
});

test("write --session A with no existing claim: claim stays null, state pending", () => {
  const { h, plan, e } = env();
  assert.equal(run(e, "write", "--stream", "p5", "--plan", plan, "--next", "M1").status, 0);
  const w = run(e, "write", "--stream", "p5", "--plan", plan, "--next", "M2", "--session", "sess-a");
  assert.equal(w.status, 0);
  const after = JSON.parse(run(e, "show", "--stream", "p5").stdout);
  assert.equal(after.claim, null, "no claim to keep, so claim stays null");
  assert.equal(after.state, "pending", "state stays pending (no consumed_at)");
});

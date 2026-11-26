// cc-ledger (cc-pacing-v2 A1a): transcript scan, dedupe across scans, offsets, rescan, partial lines, budget,
// prune, schema, CLI. Synthetic transcripts generated in a temp dir; hermetic via explicit paths / ORCH_HOME.
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import {
  scan, summary, loadState, familyOf, bucketOf, weighted, projectsDir, DEFAULT_WEIGHTS, KEEP_MS,
} from "../bin/cc-ledger.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "cc-ledger.mjs");
const HOUR = 3600 * 1000;

function sandbox() {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), "ccl-"));
  const projects = path.join(home, "projects");
  const sess = path.join(projects, "proj-a");
  fs.mkdirSync(sess, { recursive: true });
  const stateFile = path.join(home, ".config", "orchestrator", "cc-ledger.json");
  const file = path.join(sess, "s1.jsonl");
  const run = (o = {}) => scan({ dir: projects, stateFile, weights: DEFAULT_WEIGHTS, ...o });
  const state = () => loadState(stateFile);
  const cli = (args) =>
    spawnSync(process.execPath, [BIN, ...args], {
      env: { ...process.env, ORCH_HOME: home, ORCH_CC_PROJECTS: projects },
      encoding: "utf8",
      timeout: 30000,
    });
  return { home, projects, sess, stateFile, file, run, state, cli };
}

const ts = (msAgo = HOUR) => new Date(Date.now() - msAgo).toISOString();
const line = ({ id = "msg_1", model = "claude-sonnet-5-5", at = ts(), out = 10, inp = 100, cc = 0, cr = 0 } = {}) =>
  JSON.stringify({
    type: "assistant",
    timestamp: at,
    message: { id, model, role: "assistant", usage: { input_tokens: inp, output_tokens: out, cache_creation_input_tokens: cc, cache_read_input_tokens: cr } },
  }) + "\n";

const totals = (st) => {
  const t = { in: 0, out: 0, cc: 0, cr: 0, w: 0 };
  for (const fams of Object.values(st.buckets)) for (const c of Object.values(fams)) for (const k in t) t[k] += c[k];
  return t;
};

test("bar 1: one id on 3 lines -> counted once, last output wins", () => {
  const s = sandbox();
  const at = ts();
  fs.writeFileSync(s.file, [10, 20, 30].map((out) => line({ at, out })).join(""));
  const r = s.run();
  assert.equal(r.counted, 3);
  const st = s.state();
  assert.deepEqual(Object.keys(st.ids), ["msg_1"]);
  assert.equal(st.ids.msg_1.out, 30);
  assert.equal(totals(st).out, 30);
  assert.equal(totals(st).in, 100);
});

test("bar 2: cross-scan dedupe -> appended line for a seen id replaces it (40, not 70 or 30)", () => {
  const s = sandbox();
  const at = ts();
  fs.writeFileSync(s.file, [10, 20, 30].map((out) => line({ at, out })).join(""));
  s.run();
  fs.appendFileSync(s.file, line({ at, out: 40 }));
  s.run();
  assert.equal(totals(s.state()).out, 40);
});

test("bar 2b: a re-seen id moving bucket leaves its old bucket", () => {
  const s = sandbox();
  fs.writeFileSync(s.file, line({ at: ts(3 * HOUR), out: 5 }));
  s.run();
  fs.appendFileSync(s.file, line({ at: ts(HOUR), out: 7 }));
  s.run();
  const st = s.state();
  assert.equal(Object.keys(st.buckets).length, 1);
  assert.equal(totals(st).out, 7);
});

test("bar 3: synthetic model, no usage, no id, bad timestamp -> skipped", () => {
  const s = sandbox();
  const at = ts();
  const lines = [
    line({ model: "<synthetic>", id: "a" }),
    JSON.stringify({ timestamp: at, message: { id: "b", model: "claude-opus-5-5" } }) + "\n",
    JSON.stringify({ timestamp: at, message: { model: "claude-opus-5-5", usage: { output_tokens: 3 } } }) + "\n",
    line({ id: "d", at: "not-a-time" }),
    "not json at all\n",
    line({ id: "ok" }),
  ];
  fs.writeFileSync(s.file, lines.join(""));
  const r = s.run();
  assert.equal(r.lines, 6);
  assert.equal(r.skipped, 5);
  assert.equal(r.counted, 1);
  assert.deepEqual(Object.keys(s.state().ids), ["ok"]);
});

test("bar 4: second scan reads only the appended bytes", () => {
  const s = sandbox();
  fs.writeFileSync(s.file, line({ id: "a" }) + line({ id: "b" }));
  const r1 = s.run();
  assert.equal(r1.bytes_read, fs.statSync(s.file).size);
  const add = line({ id: "c", out: 1 }) + line({ id: "d", out: 2 });
  fs.appendFileSync(s.file, add);
  const r2 = s.run();
  assert.equal(r2.bytes_read, Buffer.byteLength(add));
  assert.equal(r2.lines, 2);
  assert.equal(r2.files_read, 1);
  const r3 = s.run();
  assert.equal(r3.bytes_read, 0);
  assert.equal(r3.files_read, 0);
  assert.equal(Object.keys(s.state().ids).length, 4);
});

test("bar 5: truncated and rewritten file is rescanned from 0, totals unchanged", () => {
  const s = sandbox();
  const at = ts();
  const body = line({ id: "a", at, out: 11 }) + line({ id: "b", at, out: 22 }) + line({ id: "c", at, out: 33 });
  fs.writeFileSync(s.file, body);
  s.run();
  const before = totals(s.state());
  const shorter = line({ id: "a", at, out: 11 }) + line({ id: "b", at, out: 22 });
  fs.writeFileSync(s.file, shorter);
  const r = s.run();
  assert.equal(r.bytes_read, Buffer.byteLength(shorter));
  assert.equal(r.counted, 2);
  assert.deepEqual(totals(s.state()), before);
});

test("bar 5b: mtime going back forces a rescan from 0", () => {
  const s = sandbox();
  fs.writeFileSync(s.file, line({ id: "a" }) + line({ id: "b" }));
  s.run();
  const before = totals(s.state());
  const old = new Date(Date.now() - 2 * HOUR);
  fs.utimesSync(s.file, old, old);
  const r = s.run();
  assert.equal(r.bytes_read, fs.statSync(s.file).size);
  assert.deepEqual(totals(s.state()), before);
});

test("bar 6: partial last line is not consumed; counted once after its newline", () => {
  const s = sandbox();
  const full = line({ id: "p", out: 9 });
  fs.writeFileSync(s.file, line({ id: "a" }) + full.slice(0, 40));
  const r1 = s.run();
  assert.equal(r1.counted, 1);
  assert.equal(r1.bytes_read, Buffer.byteLength(line({ id: "a" })));
  assert.equal(s.state().ids.p, undefined);
  fs.appendFileSync(s.file, full.slice(40));
  const r2 = s.run();
  assert.equal(r2.counted, 1);
  assert.equal(r2.bytes_read, Buffer.byteLength(full));
  assert.equal(s.state().ids.p.out, 9);
  assert.equal(s.run().counted, 0);
});

test("bar 7: family mapping", () => {
  assert.equal(familyOf("claude-fable-5-2"), "fable");
  assert.equal(familyOf("claude-opus-5-5"), "opus");
  assert.equal(familyOf("claude-sonnet-5-5"), "sonnet");
  assert.equal(familyOf("claude-haiku-5-5"), "haiku");
  assert.equal(familyOf("gpt-x"), "other");
  assert.equal(familyOf("Claude-OPUS-x"), "opus");
});

test("weighted formula and bucketOf", () => {
  const u = { input_tokens: 100, output_tokens: 10, cache_creation_input_tokens: 40, cache_read_input_tokens: 1000 };
  assert.equal(weighted(u, "opus"), 100 + 50 + 100 + 50);
  assert.equal(weighted(u, "fable"), 2 * 300);
  assert.equal(weighted({}, "haiku"), 0);
  assert.equal(weighted({ output_tokens: 1 }, "custom", { other: 3 }), 15);
  assert.equal(bucketOf("2026-11-26T19:37:12.345Z"), "2026-11-26T19:30Z");
  assert.equal(bucketOf("2026-11-26T19:09:59Z"), "2026-11-26T19:00Z");
  assert.equal(bucketOf("nope"), null);
  assert.equal(bucketOf(undefined), null);
});

test("projectsDir precedence", () => {
  assert.equal(projectsDir({ ORCH_CC_PROJECTS: "/x/p", CLAUDE_CONFIG_DIR: "/y" }), path.resolve("/x/p"));
  assert.equal(projectsDir({ CLAUDE_CONFIG_DIR: "/y" }), path.resolve("/y/projects"));
  assert.equal(projectsDir({}), path.join(os.homedir(), ".claude", "projects"));
});

test("bar 8: ids and buckets older than 8 weeks pruned; saved JSON matches the schema exactly", () => {
  const s = sandbox();
  const now = Date.now();
  fs.writeFileSync(s.file, line({ id: "old", at: ts(7 * 7 * 24 * HOUR), model: "claude-opus-5-5" }) + line({ id: "new", at: ts(HOUR) }));
  fs.writeFileSync(path.join(s.sess, "ancient.jsonl"), line({ id: "gone", at: ts(KEEP_MS + 24 * HOUR) }));
  s.run({ now });
  let st = s.state();
  assert.deepEqual(Object.keys(st.ids).sort(), ["new", "old"]);
  // Two weeks later "old" is 9 weeks old.
  s.run({ now: now + 14 * 24 * HOUR });
  const raw = JSON.parse(fs.readFileSync(s.stateFile, "utf8"));
  assert.deepEqual(Object.keys(raw).sort(), ["buckets", "files", "ids", "scanned_at", "v"]);
  assert.equal(raw.v, 1);
  assert.deepEqual(Object.keys(raw.ids), ["new"]);
  assert.equal(Object.keys(raw.buckets).length, 1);
  for (const [k, e] of Object.entries(raw.files)) {
    assert.match(k, /^[0-9a-f]{16}$/);
    assert.deepEqual(Object.keys(e).sort(), ["mtime", "offset", "size"]);
  }
  for (const e of Object.values(raw.ids)) assert.deepEqual(Object.keys(e).sort(), ["b", "cc", "cr", "f", "in", "out"]);
  for (const [b, fams] of Object.entries(raw.buckets)) {
    assert.match(b, /^\d{4}-\d\d-\d\dT\d\d:\d0Z$/);
    for (const c of Object.values(fams)) assert.deepEqual(Object.keys(c).sort(), ["cc", "cr", "in", "out", "w"]);
  }
  const text = fs.readFileSync(s.stateFile, "utf8");
  for (const bad of [s.home, "proj-a", "s1.jsonl", "assistant", "cwd", "sessionId"]) assert.ok(!text.includes(bad), bad);
});

test("bar 9: --budget-ms 0 -> partial with offsets saved; a later scan reaches the full totals", () => {
  const mk = () => {
    const s = sandbox();
    fs.mkdirSync(path.join(s.sess, "s2", "subagents"), { recursive: true });
    const body = (p) => Array.from({ length: 5 }, (_, i) => line({ id: `${p}${i}`, out: i + 1, model: i % 2 ? "claude-opus-5-5" : "claude-haiku-5-5" })).join("");
    fs.writeFileSync(s.file, body("a") + line({ id: "a0", out: 50 }));
    fs.writeFileSync(path.join(s.sess, "s2", "subagents", "agent-1.jsonl"), body("b"));
    return s;
  };
  const full = mk();
  const rf = full.run();
  assert.equal(rf.partial, false);
  assert.equal(rf.files, 2);

  const s = mk();
  const r1 = s.run({ budgetMs: 0 });
  assert.equal(r1.partial, true);
  assert.ok(r1.lines >= 1 && r1.lines < 11, String(r1.lines));
  const st1 = s.state();
  const offs = Object.values(st1.files).map((e) => e.offset);
  assert.ok(offs.some((o) => o > 0), "an offset was saved");
  const r2 = s.run();
  assert.equal(r2.partial, false);
  assert.deepEqual(totals(s.state()), totals(full.state()));
  assert.deepEqual(s.state().ids, full.state().ids);
});

test("CLI: unknown command or flag -> exit 2 with usage on stderr", () => {
  const s = sandbox();
  for (const args of [["frob"], [], ["scan", "--nope"], ["summary", "--budget-ms", "3"], ["scan", "--budget-ms", "x"], ["summary", "--hours", "0"]]) {
    const r = s.cli(args);
    assert.equal(r.status, 2, args.join(" "));
    assert.match(r.stderr, /usage: cc-ledger/);
    assert.equal(r.stdout, "");
  }
});

test("CLI: scan text line, then summary --hours 24 --json sums w per family", () => {
  const s = sandbox();
  fs.writeFileSync(
    s.file,
    line({ id: "o1", model: "claude-opus-5-5", out: 10, inp: 0 }) + // 50
      line({ id: "o2", model: "claude-opus-5-5", out: 0, inp: 20 }) + // 20
      line({ id: "h1", model: "claude-haiku-5-5", out: 10, inp: 0 }) + // 10
      line({ id: "x1", model: "gpt-x", out: 0, inp: 10, at: ts(30 * HOUR) }), // outside 24 h
  );
  const r = s.cli(["scan"]);
  assert.equal(r.status, 0, r.stderr);
  assert.match(r.stdout, /^ledger: 4 msgs, 1\/1 files, \d+\.\d MB in \d+ ms\n$/);
  const j = s.cli(["scan", "--json", "--budget-ms", "5000"]);
  assert.equal(j.status, 0, j.stderr);
  assert.deepEqual(Object.keys(JSON.parse(j.stdout)).sort(),
    ["bytes_read", "counted", "files", "files_read", "lines", "ms", "partial", "scanned_at", "skipped"]);
  const sm = s.cli(["summary", "--hours", "24", "--json"]);
  assert.equal(sm.status, 0, sm.stderr);
  const out = JSON.parse(sm.stdout);
  assert.ok(Math.abs(out.families.opus - 70) < 1e-9);
  assert.ok(Math.abs(out.families.haiku - 10) < 1e-9);
  assert.equal(out.families.other, undefined);
  assert.ok(Math.abs(out.total - 80) < 1e-9);
  const txt = s.cli(["summary"]);
  assert.equal(txt.status, 0);
  assert.match(txt.stdout, /^ledger last 24 h: opus 70, haiku 10, total 80 weighted tokens\n$/);
  // summary() pure
  assert.equal(summary(s.state(), 48).families.other, 6);
});

test("config weights from usage-limits.json cc.ledger.weights override defaults", () => {
  const s = sandbox();
  fs.mkdirSync(path.dirname(s.stateFile), { recursive: true });
  fs.writeFileSync(path.join(path.dirname(s.stateFile), "usage-limits.json"), JSON.stringify({ cc: { ledger: { weights: { opus: 3 } } } }));
  fs.writeFileSync(s.file, line({ id: "o1", model: "claude-opus-5-5", out: 10, inp: 0 }));
  assert.equal(s.cli(["scan"]).status, 0);
  const out = JSON.parse(s.cli(["summary", "--json"]).stdout);
  assert.equal(out.families.opus, 150);
});

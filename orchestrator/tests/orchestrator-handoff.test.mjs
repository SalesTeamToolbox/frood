import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const HOOK = path.join(REPO, "hooks", "orchestrator-handoff.js");
const NOW = new Date().toISOString();

function env() {
  const h = fs.mkdtempSync(path.join(os.tmpdir(), "orch-hk-"));
  fs.mkdirSync(path.join(h, ".config", "orchestrator", "streams"), { recursive: true });
  return { h, e: { ...process.env, ORCH_HOME: h, USERPROFILE: h, HOME: h, ORCH_REPO: REPO } };
}
const put = (h, name, o) =>
  fs.writeFileSync(
    path.join(h, ".config", "orchestrator", "streams", `${name}.json`),
    typeof o === "string" ? o : JSON.stringify({ name, status: "active", written_at: NOW, next: "do it", ...o }),
  );
const run = (e, input) =>
  spawnSync(process.execPath, [HOOK], { env: e, input: JSON.stringify({ session_id: "x", cwd: "C:/x/acme", ...input }), encoding: "utf8" });
const prompt = (e, p) => run(e, { hook_event_name: "UserPromptSubmit", prompt: p });
const out = (r) => JSON.parse(r.stdout).hookSpecificOutput;
const HELD = { held_by: "oc", held_session: "oc-1", held_at: NOW };

test("prompt: stream held by oc -> held line, no title", () => {
  const { h, e } = env();
  put(h, "m1", HELD);
  const o = out(prompt(e, "hello"));
  assert.equal(o.hookEventName, "UserPromptSubmit");
  assert.match(o.additionalContext, /^orchestrator stream m1 is held by OpenCode \(session oc-1\) since .* — do not act on it here/);
  assert.equal(o.sessionTitle, undefined);
});

test("prompt: handed back to cc -> handed-back line", () => {
  const { h, e } = env();
  put(h, "m1", { held_by: null, handback_to: "cc" });
  assert.match(out(prompt(e, "hello")).additionalContext, /^orchestrator stream m1 was handed back to Claude Code — run \/next m1 \(and \/desk/);
});

test("prompt: no lease, legacy pointers, parked/done, unreadable -> empty stdout", () => {
  const { h, e } = env();
  put(h, "legacy", {});
  put(h, "parked", { ...HELD, status: "parked" });
  put(h, "done", { ...HELD, status: "done" });
  put(h, "bad", "{not json");
  const r = prompt(e, "hello");
  assert.equal(r.status, 0);
  assert.equal(r.stdout, "");
});

test("prompt: /next with a held stream -> title and held line together", () => {
  const { h, e } = env();
  put(h, "m1", HELD);
  const o = out(prompt(e, "/next m1"));
  assert.equal(o.sessionTitle, "[m1] do it");
  assert.match(o.additionalContext, /stream m1 is held by OpenCode/);
});

test("lease lines: newest first, at most 6", () => {
  const { h, e } = env();
  for (let i = 0; i < 8; i++) put(h, `s${i}`, { ...HELD, held_at: new Date(Date.now() - i * 1000).toISOString() });
  const lines = out(prompt(e, "hi")).additionalContext.split("\n");
  assert.equal(lines.length, 6);
  assert.match(lines[0], /stream s0 /);
  assert.match(lines[5], /stream s5 /);
});

test("SessionStart resume/compact: only lease lines", () => {
  const { h, e } = env();
  put(h, "m2", { next: "other" });
  assert.equal(run(e, { source: "resume" }).stdout, "");
  put(h, "m1", HELD);
  for (const source of ["resume", "compact"]) {
    const o = out(run(e, { source }));
    assert.equal(o.hookEventName, "SessionStart");
    assert.equal(o.additionalContext.split("\n").length, 1);
    assert.match(o.additionalContext, /^orchestrator stream m1 is held by OpenCode/);
  }
});

test("SessionStart startup: held stream not listed with run /next, held line added; junk never breaks it", () => {
  for (const broken of [false, true]) {
    const { h, e } = env();
    put(h, "m1", { ...HELD, next: "held work" });
    put(h, "m2", { next: "free work" });
    put(h, "bad", "{nope");
    put(h, "parked", { ...HELD, status: "parked" });
    const r = run(broken ? { ...e, ORCH_REPO: path.join(h, "nowhere") } : e, { source: "startup" });
    assert.equal(r.status, 0);
    const t = out(r).additionalContext;
    assert.match(t, /orchestrator stream m2: next = free work/);
    assert.doesNotMatch(t, /m1: next/);
    assert.doesNotMatch(t, /held work/);
    assert.match(t, /stream m1 is held by OpenCode/);
    assert.doesNotMatch(t, /parked/);
    assert.equal(t.split("\n").filter((l) => /held by OpenCode/.test(l)).length, 1);
  }
});

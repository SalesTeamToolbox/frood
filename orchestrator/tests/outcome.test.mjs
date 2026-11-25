import test from "node:test";
import assert from "node:assert/strict";
import { workerOutcome } from "../bin/outcome.mjs";

// workerOutcome: timeout/stalled with `landed` counts as done; everything else unchanged.

test("workerOutcome: timeout with landed -> done", () => {
  assert.equal(workerOutcome({ exit: "timeout", landed: { head_before: "a", head_after: "b" } }), "done");
});

test("workerOutcome: stalled with landed -> done", () => {
  assert.equal(workerOutcome({ exit: "stalled", landed: { head_before: "a", head_after: "b" } }), "done");
});

test("workerOutcome: timeout without landed stays timeout", () => {
  assert.equal(workerOutcome({ exit: "timeout" }), "timeout");
  assert.equal(workerOutcome({ exit: "timeout", landed: undefined }), "timeout");
});

test("workerOutcome: landed does not change non-timeout exits", () => {
  assert.equal(workerOutcome({ exit: 0, landed: { head_before: "a", head_after: "b" }, verdict: "RESULT: DONE", out: "/tmp/x.md" }), "done");
  assert.equal(workerOutcome({ exit: 5, landed: { head_before: "a", head_after: "b" } }), "error");
  assert.equal(workerOutcome({ exit: "no-healthy-pool", landed: { head_before: "a", head_after: "b" } }), "no_pool");
});

test("workerOutcome: existing outcomes unchanged", () => {
  assert.equal(workerOutcome({ exit: 0, verdict: "RESULT: DONE", out: "/tmp/x.md" }), "done");
  assert.equal(workerOutcome({ exit: 0, first_line: "RESULT: BLOCKED: question", out: "/tmp/x.md" }), "blocked_question");
  assert.equal(workerOutcome({ exit: 0, out: null }), "no_output");
  assert.equal(workerOutcome({ exit: "stalled" }), "timeout");
  assert.equal(workerOutcome({ exit: "timeout" }), "timeout");
});

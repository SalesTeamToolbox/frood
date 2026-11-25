// Outcome words for an oc-worker receipt. workerStatusLine/workerOutcome are copied from board.mjs (which is not
// changed), plus two rules for the desk: model-not-allowed/unresolvable receipts and non-question BLOCKED lines.

// oc-worker receipts have no `status` field (design B1): the outcome is these rules, in this order.
export function workerStatusLine(r) {
  const v = String(r?.verdict ?? "").trim();
  if (/^RESULT:/.test(v)) return v; // the verdict wins when it is the status line
  return String(r?.first_line ?? "").trim();
}

export function workerOutcome(r) {
  if (r.exit === "timeout" || r.exit === "stalled") return r.landed ? "done" : "timeout";
  if (r.exit === "no-healthy-pool") return "no_pool";
  if (r.exit === "model-not-allowed" || r.exit === "model-unresolvable") return "not_allowed";
  // A missing `out` is as good as a null one: no final message was saved.
  if (r.exit === 0 && (r.out === null || r.out === undefined)) return "no_output";
  const line = workerStatusLine(r);
  if (r.exit === 0 && line.startsWith("RESULT: DONE")) return "done";
  if (line.startsWith("RESULT: BLOCKED: question")) return "blocked_question";
  if (line.startsWith("RESULT: BLOCKED:")) return "blocked";
  return "error";
}

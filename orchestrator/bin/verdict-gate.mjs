#!/usr/bin/env node
// Mechanical verdict gate for critic findings. A critic's own VERDICT line is advice; this is the decision.
//
//   node verdict-gate.mjs <findings.md> [--free]
//
// Rules (2026-11-12 bake-off: free critics FOUND a call-site regression but still APPROVED it):
//   - no VERDICT line                       -> INVALID   (not a review)
//   - no BLAST RADIUS section / no entries  -> INVALID   (caller trace is mandatory)
//   - any BLAST RADIUS line tagged UNREQUESTED -> CHANGES_REQUESTED, whatever the critic wrote
//   - any [blocker] or [major] finding       -> CHANGES_REQUESTED, whatever the critic wrote
//   - otherwise the critic's verdict stands
// --free marks the review as done on a free model: an APPROVED becomes APPROVED_FREE
// (the ticket may reach READY but needs a paid critic / senior / human before boarding).
// Prints JSON {effective, critic, overridden, reasons, unrequested, majors}; exit 0 APPROVED*,
// 1 CHANGES_REQUESTED, 2 INVALID.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export function gate(text, { free = false } = {}) {
  const t = String(text || "").replace(/\r\n/g, "\n");
  const v = t.match(/^\s*VERDICT:\s*(APPROVED|CHANGES_REQUESTED)\b/m);
  const critic = v ? v[1] : null;
  const reasons = [];
  if (!critic) return { effective: "INVALID", critic, overridden: false, reasons: ["no VERDICT line"], unrequested: [], majors: [] };

  // BLAST RADIUS section: from its heading to the first numbered finding / SENIOR_REVIEW / blank-then-non-bullet.
  const lines = t.split("\n");
  const start = lines.findIndex((l) => /^\s*\**BLAST RADIUS:?\**/i.test(l));
  const entries = [];
  if (start >= 0) {
    for (let i = start + 1; i < lines.length; i++) {
      const l = lines[i];
      if (/^\s*[-*]\s+/.test(l)) entries.push(l.trim());
      else if (/^\s*$/.test(l)) continue;
      else break;
    }
  }
  if (start < 0 || !entries.length) {
    return { effective: "INVALID", critic, overridden: true, reasons: ["no BLAST RADIUS entries (caller trace is mandatory)"], unrequested: [], majors: [] };
  }
  const unrequested = entries.filter((e) => /\bUNREQUESTED\b/.test(e));
  const majors = lines.filter((l) => /^\s*\d+\.\s*\[(blocker|major)\]/i.test(l)).map((l) => l.trim());
  if (unrequested.length) reasons.push(`${unrequested.length} UNREQUESTED caller change(s)`);
  if (majors.length) reasons.push(`${majors.length} blocker/major finding(s)`);

  let effective = reasons.length ? "CHANGES_REQUESTED" : critic;
  if (effective === "APPROVED" && free) effective = "APPROVED_FREE";
  return { effective, critic, overridden: effective.replace("_FREE", "") !== critic, reasons, unrequested, majors };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const file = process.argv[2];
  if (!file) {
    console.error("usage: verdict-gate.mjs <findings.md> [--free]");
    process.exit(2);
  }
  const r = gate(fs.readFileSync(file, "utf8"), { free: process.argv.includes("--free") });
  console.log(JSON.stringify(r));
  process.exit(r.effective.startsWith("APPROVED") ? 0 : r.effective === "CHANGES_REQUESTED" ? 1 : 2);
}

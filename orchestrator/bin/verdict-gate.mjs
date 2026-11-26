#!/usr/bin/env node
// Mechanical verdict gate for critic findings. A critic's own VERDICT line is advice; this is the decision.
//
//   node verdict-gate.mjs <findings.md> [--free]
//
// Rules (2026-11-12 bake-off: free critics FOUND a call-site regression but still APPROVED it):
//   - no VERDICT line                       -> INVALID   (not a review)
//   - no BLAST RADIUS section / no entries  -> INVALID   (caller trace is mandatory)
//   - any BLAST RADIUS line whose first word (after a leading skip run of checkboxes, non-letter
//     characters, and single-letter list markers `a.`/`a)`; bullets `-`/`*`/`+` are always entries)
//     is UNREQUESTED (any case) -> CHANGES_REQUESTED, whatever follows; unchanged/intended first word,
//     closed by emphasis/brackets then a separator (` — ` ` – ` ` -- ` ` - ` `:` `|`) or end of line
//     -> does not count; any other line (old format) -> today's separator walk plus the no-dash-separator
//     fail safe -> CHANGES_REQUESTED if UNREQUESTED is in tag position.
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
  // A blast-line entry is a list item whose first content word is a tag (`UNREQUESTED`/`unchanged`/`intended`):
  // a bullet (`-`, `*`, `+`) is always collected; any leading skip unit — a checkbox, a non-letter
  // character, or a single-letter list marker (`a.`/`a)`) — opens a line, then zero or more skip units
  // may precede the tag, so decorated bullets (`• UNREQUESTED`, `[x] UNREQUESTED`, `❌ UNREQUESTED`) and
  // decorated numbered lines (`1. **UNREQUESTED**`, `a) UNREQUESTED`) are collected too. Numbered findings
  // (`1. [minor] ...`) and `1. none` / `1. No findings` / `1. (none)` placeholders stay findings because
  // their first content word is not a tag. The loop has no optional nested quantifier, so it is linear and
  // cannot backtrack exponentially on spaced decoration runs.
  const SKIP = String.raw`(?:\[[xX]\]|[^\p{L}]|[a-zA-Z][.)])`;
  // One skip unit before the first word: checkbox, any non-letter character, or single-letter marker.
  const BLAST_LINE = new RegExp(
    String.raw`^\s*(?:[-*+]\s|(?:\[[xX]\]|[^\p{L}\s]|[a-zA-Z][.)])${SKIP}*(?:UNREQUESTED|unchanged|intended)(?![A-Za-z0-9]))`,
    "iu"
  );
  const lines = t.split("\n");
  const start = lines.findIndex((l) => /^\s*\**BLAST RADIUS:?\**/i.test(l));
  const entries = [];
  if (start >= 0) {
    for (let i = start + 1; i < lines.length; i++) {
      const l = lines[i];
      if (BLAST_LINE.test(l)) entries.push(l.trim());
      else if (/^\s*$/.test(l)) continue;
      else break;
    }
  }
  if (start < 0 || !entries.length) {
    return { effective: "INVALID", critic, overridden: true, reasons: ["no BLAST RADIUS entries (caller trace is mandatory)"], unrequested: [], majors: [] };
  }
  // New format: the blast line's FIRST word is its tag. Before reading it, strip a leading decoration
  // run (bullet, list numbering, checkbox, emoji/symbol, emphasis/bracket openers), repeated in any
  // order with whitespace between. UNREQUESTED (any case) as the first word -> the line counts as
  // UNREQUESTED, whatever follows (fail safe). unchanged/intended as the first word, closed by
  // emphasis/brackets
  // (`*`, `_`, backtick, `]`, `)`) then followed by a separator (` — ` ` – ` ` -- ` ` - ` `:` `|`)
  // or end of line -> the line does NOT count, whatever the rest says.
  // Transition (old format): any other line (first word not a tag, or unchanged/intended followed by
  // ordinary words) is judged by today's rule unchanged — the separator walk plus the no-dash
  // fail safe. Reason: findings files written before the prompts reinstall, receipts already in
  // flight, and board signoff re-gating an old senior file must give the same answer as today.
  const MENTION = /(?<![A-Za-z0-9])UNREQUESTED(?![A-Za-z0-9])/;
  const SEP = / — | – | -- | - |: /g;
  const KNOWN = /^[*_`\[(]*(unchanged|intended|UNREQUESTED)(?![A-Za-z0-9])/;
  // Leading decoration run, repeated in any order, whitespace allowed between:
  // checkbox, any non-letter character, or single-letter list marker (`a.`/`a)`).
  const DECOR = new RegExp(`^${SKIP}*`, "u");
  const TAG = /^[A-Za-z]+/;
  const IS_TAG = /^(unchanged|intended|UNREQUESTED)$/i;
  const IS_UNREQ = /^UNREQUESTED$/i;
  const CLOSE = /^[*_`\]\)]*/;
  // After closing emphasis, a separator closes the tag only with whitespace around it:
  // end of line, `: ` / `| `, or whitespace + dash + whitespace/end. A bare `-`/`—`
  // glued to the tag (e.g. `unchanged-callers.mjs`) is NOT a separator — that keeps
  // old-format caller names like `unchanged-callers` from being misread as benign tags.
  const TAG_CLOSE = /^(?:\s*$|\s*[:|](?:\s|$)|\s+(?:—|–|--|-)(?:\s|$))/;
  const isUnrequested = (e) => {
    const body = e.replace(DECOR, "");
    const first = body.match(TAG);
    const tag = first ? first[0] : "";
    if (IS_TAG.test(tag)) {
      if (IS_UNREQ.test(tag)) return true; // rule 2: UNREQUESTED first word -> counts, whatever follows
      // rule 3: unchanged/intended first word, closed then separator/EOL -> does not count
      const closed = body.slice(tag.length).replace(CLOSE, "");
      if (TAG_CLOSE.test(closed)) return false;
      // unchanged/intended followed by ordinary words -> fall through to the transition (old format)
    }
    // Transition (old format): the separator walk plus the no-dash-separator fail safe.
    if (!MENTION.test(e)) return false;
    let dash = false, benign = false;
    for (const m of e.matchAll(SEP)) {
      const colon = m[0] === ": ";
      if (!colon) dash = true;
      if (colon && benign) continue;
      const k = e.slice(m.index + m[0].length).trimStart().match(KNOWN);
      if (!k) continue;
      if (k[1] === "UNREQUESTED") return true;
      if (!colon) benign = true;
    }
    return !dash;
  };
  const unrequested = entries.filter(isUnrequested);
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

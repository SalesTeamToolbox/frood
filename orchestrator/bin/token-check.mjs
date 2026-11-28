#!/usr/bin/env node
// token-check: deterministic token-surface diff scanner (surfaces A–D, five rules).
//
//   node token-check.mjs [--dir <path>] [--base ] [--json] [--all]
//
// Classifies every changed line into a token surface (A always-loaded, B
// on-demand agent context, C LLM call sites, D agent-facing bin output),
// estimates net token delta per surface (bytes / 4), and applies five rules.
// Advisory only: exit 0 with findings, exit 2 on usage/git failures.
//
// No network, no LLM, no writes. Node stdlib only.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { matchAny } from "./scope-check.mjs";

// ---------------------------------------------------------------------------
// Defaults
// ---------------------------------------------------------------------------

export const DEFAULTS = {
  always_loaded: [
    "CLAUDE.md",
    "**/CLAUDE.md",
    "AGENTS.md",
    "**/AGENTS.md",
    "**/rules/*.md",
    "**/.claude/rules/*.md",
  ],
  agent_docs: [
    "**/commands/*.md",
    "**/.claude/commands/*.md",
    "**/agents/*.md",
    "**/.claude/agents/*.md",
    "**/skills/**/SKILL.md",
    "**/.claude/skills/**/SKILL.md",
  ],
  agent_output: ["**/bin/*.mjs", "**/bin/*.js", "**/scripts/*.py"],
  llm_call_patterns: [
    "messages.create",
    "chat.completions.create",
    "completions.create",
    ".generate_content(",
    "litellm.completion",
    "/v1/messages",
    "/chat/completions",
  ],
  budgets: { always_loaded_tokens: 300, on_demand_tokens: 1500 },
};

// URL call patterns (F2): only treated as call sites when a request call
// appears on the same line or within the next 10 lines.
const URL_REQUEST_RE = /\.post\(|\.request\(|\.stream\(|fetch\(|requests\.|httpx\.|aiohttp/;

// ---------------------------------------------------------------------------
// Rules (exported RULES, five in T1)
// Each rule: { id, surface, tag, run(ctx) → findings[] }.
// run receives ctx = { entries, files, cfg, lines, states, baseText, dir, mb,
//   netTokens, surfaceOf } and returns findings[]. scanDiff calls run for every
//   rule; no stubs.
//
export const RULES = [
  {
    id: "A-budget",
    surface: "A",
    tag: "tradeoff",
    run: runAbudget,
  },
  {
    id: "A-desc-long",
    surface: "A",
    tag: "tradeoff",
    run: runAdescLong,
  },
  {
    id: "C-no-cap",
    surface: "C",
    tag: "WASTE",
    run: runCnoCap,
  },
  {
    id: "C-premium-literal",
    surface: "C",
    tag: "tradeoff",
    run: runCpremiumLiteral,
  },
  {
    id: "D-unbounded",
    surface: "D",
    tag: "tradeoff",
    run: runDunbounded,
  },
];

const CALL_EXT_RE = /\.(py|js|mjs|cjs|ts|tsx)$/;
const PREMIUM_RE = /(opus|fable|gpt-5(?!-mini)|\bo3\b(?!-mini)|gemini-[\w.-]*-pro)/i;
const CAP_KEYWORDS = ["max_tokens", "max_output_tokens", "maxTokens", "max_completion_tokens"];
const SPREAD_RE = /\*\*kwargs|\*\*params|\.\.\.opts/;
// F3: bare-identifier body passthrough in call args (json=, content=, data=, body:).
const FORWARDED_BODY_RE = /\b(json|content|data)\s*=\s*[A-Za-z_$][A-Za-z0-9_$]*\b|\bbody\s*:\s*[A-Za-z_$][A-Za-z0-9_$]*\b/;
const DESC_LONG_BYTES = 200;
const MAX_FINDING_LINES = 30;
const GIT_TIMEOUT_MS = 10000;
const GIT_MAX_BUFFER = 64 << 20;

// ---------------------------------------------------------------------------
// Small helpers
// ---------------------------------------------------------------------------

function netTokens(added, removed) {
  return Math.ceil((added - removed) / 4);
}

function formatSigned(n) {
  return n >= 0 ? `+${n}` : String(n);
}

function bytesOf(text) {
  return Buffer.byteLength(String(text), "utf8") + 1;
}

// Leading-whitespace trim for comment/decorator checks.
function stripped(line) {
  return String(line).replace(/^\s*/, "");
}

// Is this line a comment (after leading whitespace)?
function isCommentLine(line) {
  const s = stripped(line);
  return s.startsWith("#") || s.startsWith("//") || s.startsWith("*") || s.startsWith("/*") || s.startsWith("--");
}

// Is this line a decorator (after leading whitespace starts with @)?
function isDecoratorLine(line) {
  return stripped(line).startsWith("@");
}

// Cache of per-line states keyed by the lines array reference, so classify()
// (called once per line by scanDiff) computes string/block-comment state once
// per file instead of once per line (F1).
const classifyStates = new WeakMap();
function getClassifyStates(lines) {
  let states = classifyStates.get(lines);
  if (!states) { states = computeLineStates(lines); classifyStates.set(lines, states); }
  return states;
}

// ---------------------------------------------------------------------------
// Per-line state tracking (F2): walk a file's lines once and record, per line,
// whether it sits inside a Python triple-quoted string ("""/''') or a JS block
// comment (/* */). A line that opens and closes on itself counts as inside.
// ---------------------------------------------------------------------------

export function computeLineStates(lines) {
  const linesArr = Array.isArray(lines) ? lines : String(lines).split("\n");
  const states = new Array(linesArr.length);
  let inTriple = false; // Python """ or '''
  let inBlock = false;  // JS /* */

  for (let i = 0; i < linesArr.length; i++) {
    const l = linesArr[i];
    let triple = inTriple;
    let block = inBlock;

    // Track """ and ''' toggles. Count unescaped occurrences; a line that both
    // opens and closes counts as inside.
    for (const q of ['"""', "'''"]) {
      let idx = l.indexOf(q);
      let count = 0;
      while (idx >= 0) {
        count++;
        idx = l.indexOf(q, idx + q.length);
      }
      if (count % 2 === 1) triple = !triple;
    }

    // Track /* */ toggles.
    {
      let idx = l.indexOf("/*");
      let openCount = 0;
      while (idx >= 0) { openCount++; idx = l.indexOf("/*", idx + 2); }
      idx = l.indexOf("*/");
      let closeCount = 0;
      while (idx >= 0) { closeCount++; idx = l.indexOf("*/", idx + 2); }
      const net = openCount - closeCount;
      if (net !== 0) block = net > 0 ? true : block;
      if (closeCount > 0 && openCount === 0) block = false;
      // If both open and close on same line, line is inside (counts as inside).
      if (openCount > 0 && closeCount > 0) block = true;
      if (openCount > 0 && closeCount === 0) block = true;
    }

    states[i] = { inTriple: triple, inBlock: block, inside: triple || block };
    inTriple = triple;
    inBlock = block;
  }
  return states;
}

// Does any of lines[idx..idx+10] contain a request call shape?
function hasRequestCallNearby(lines, idx) {
  const end = Math.min(lines.length, idx + 11);
  for (let j = idx; j < end; j++) {
    if (URL_REQUEST_RE.test(lines[j])) return true;
  }
  return false;
}

// ---------------------------------------------------------------------------
// Surface classification (per line, first match wins) — F1/F2/F5
// text may be a string or a pre-split array of lines (F1).
// ---------------------------------------------------------------------------

export function classify(path, lineNo, text, cfg) {
  const p = String(path).replace(/\\/g, "/");
  const lines = Array.isArray(text) ? text : String(text).split("\n");
  const idx = lineNo - 1;
  const line = lines[idx] || "";
  // F2: compute inside-string / block-comment state once per lines array.
  const states = Array.isArray(text) ? getClassifyStates(lines) : computeLineStates(lines);

  // 1. C — LLM call site (call file + call pattern on this line). First match.
  if (CALL_EXT_RE.test(p)) {
    for (const pat of cfg.llm_call_patterns) {
      if (!line.includes(pat)) continue;
      // F2: not a comment, not a decorator, not inside a string/block-comment.
      if (isCommentLine(line)) continue;
      if (isDecoratorLine(line)) continue;
      if (states[idx] && states[idx].inside) continue;
      if (pat === "/v1/messages" || pat === "/chat/completions") {
        // F2 URL gating: need a request call on this line or next 10.
        if (!hasRequestCallNearby(lines, idx)) continue;
      }
      return "C";
    }
  }

  // 2. A — always-loaded (every line), or agent_docs frontmatter description.
  if (matchAny(p, cfg.always_loaded)) return "A";
  if (matchAny(p, cfg.agent_docs) && isFrontmatterDescription(lines, lineNo)) return "A";

  // 3. B — agent_docs body, or mandate file (F5: via matchAny, no MANDATE_RE).
  if (matchAny(p, cfg.agent_docs)) return "B";
  if (matchAny(p, ["**/*mandate*.md"])) return "B";

  // 4. D — agent-facing bin/output scripts.
  if (matchAny(p, cfg.agent_output)) return "D";

  return null;
}

// ---------------------------------------------------------------------------
// Config loading
// ---------------------------------------------------------------------------

export function loadConfig(dir) {
  const cfg = {
    always_loaded: [...DEFAULTS.always_loaded],
    agent_docs: [...DEFAULTS.agent_docs],
    agent_output: [...DEFAULTS.agent_output],
    llm_call_patterns: [...DEFAULTS.llm_call_patterns],
    budgets: { ...DEFAULTS.budgets },
  };

  const adapterPath = path.join(dir, ".opencode", "board", "adapter.json");
  let raw;
  try {
    raw = fs.readFileSync(adapterPath, "utf8");
  } catch {
    // Missing or unreadable adapter file → defaults, no warning.
    return cfg;
  }
  let adapter;
  try {
    adapter = JSON.parse(raw);
  } catch {
    // Invalid JSON → defaults, no warning.
    return cfg;
  }

  const tc = adapter && typeof adapter === "object" && adapter.token_check;
  if (!tc || typeof tc !== "object" || Array.isArray(tc)) return cfg;

  for (const key of [
    "always_loaded",
    "agent_docs",
    "agent_output",
    "llm_call_patterns",
  ]) {
    const val = tc[key];
    if (Array.isArray(val) && val.every((x) => typeof x === "string")) {
      cfg[key] = [...val];
    } else if (val !== undefined) {
      console.error(`token-check: adapter token_check.${key} ignored (wrong type)`);
    }
  }

  const budgets = tc.budgets;
  if (budgets && typeof budgets === "object" && !Array.isArray(budgets)) {
    if (typeof budgets.always_loaded_tokens === "number") {
      cfg.budgets.always_loaded_tokens = budgets.always_loaded_tokens;
    }
    if (typeof budgets.on_demand_tokens === "number") {
      cfg.budgets.on_demand_tokens = budgets.on_demand_tokens;
    }
  }

  return cfg;
}

// ---------------------------------------------------------------------------
// Frontmatter description detection
// ---------------------------------------------------------------------------

// text: full file content or a pre-split array of lines (F1). lineNo: 1-based
// line number to check. Returns true when the file starts with `---`, the line
// at lineNo lies before the closing `---`, and that line starts with
// `description:`.
export function isFrontmatterDescription(text, lineNo) {
  const lines = Array.isArray(text) ? text : String(text).split("\n");
  if (!lines[0] || !lines[0].startsWith("---")) return false;
  // Find the closing `---` (a line that is exactly `---`, after the opening one).
  let closeIdx = -1;
  for (let i = 1; i < lines.length; i++) {
    if (lines[i] === "---") {
      closeIdx = i;
      break;
    }
  }
  if (closeIdx < 0) return false;
  const idx = lineNo - 1; // 0-based
  if (idx < 1 || idx >= closeIdx) return false;
  return lines[idx].startsWith("description:");
}

// ---------------------------------------------------------------------------
// parseDiff — parse `git diff --unified=0` output into entries
// ---------------------------------------------------------------------------

// Returns [{ path, binary, deleted, added: [{line, text}], removed: [{line, text, oldLine}], removedBytes }].
//
// `removed` entries carry `oldLine` (1-based line number in the pre-change file)
// so removed lines can be classified against the base file text (F6). Line
// numbers on added entries come from the +c,d side of each @@ hunk header
// (post-change numbering).
//
// `diff --git <from> <to>` prefixes vary (a/b with default, c/w with
// mnemonicprefix); the "to" (second) path is taken and any single-letter prefix
// stripped.
export function parseDiff(diffText) {
  const entries = [];
  const lines = String(diffText).split("\n");
  let i = 0;
  let current = null;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("diff --git ")) {
      if (current) entries.push(current);
      current = { path: "", binary: false, deleted: false, added: [], removed: [], removedBytes: 0, postLine: 1, oldLine: 1 };
      const dmg = line.match(/^diff --git \S+ (\S+)/);
      if (dmg) {
        let p = dmg[1];
        p = p.replace(/^[a-zA-Z]\//, "");
        current.path = p;
      }
      i++;
      continue;
    }

    if (!current) { i++; continue; }

    if (line.startsWith("Binary files ")) {
      current.binary = true;
      i++;
      continue;
    }

    if (line.startsWith("deleted file mode") || line === "+++ /dev/null") {
      current.deleted = true;
      i++;
      continue;
    }

    if (line.startsWith("--- ") || line.startsWith("+++ ")) {
      i++;
      continue;
    }

    const hunkM = line.match(/^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunkM) {
      current.oldLine = parseInt(hunkM[1], 10);
      current.postLine = parseInt(hunkM[2], 10);
      i++;
      continue;
    }

    if (line.startsWith("+") && !line.startsWith("+++")) {
      current.added.push({ line: current.postLine, text: line.slice(1) });
      current.postLine++;
      i++;
      continue;
    }

    if (line.startsWith("-") && !line.startsWith("---")) {
      current.removed.push({ line: current.oldLine, text: line.slice(1), oldLine: current.oldLine });
      current.removedBytes += Buffer.byteLength(line.slice(1), "utf8") + 1;
      current.oldLine++;
      i++;
      continue;
    }

    // Context line advances both old and post-change counters.
    if (line.startsWith(" ")) {
      current.oldLine++;
      current.postLine++;
    }
    i++;
  }

  if (current) entries.push(current);
  return entries;
}

// Per-path caches (F1): live inside scanDiff, fresh per call.

// ---------------------------------------------------------------------------
// Full per-line surface with F2 inside-string/refinement and F6 base-text support.
// `classify` (exported) is the pure first-match; scanDiff uses this wrapper so
// removed lines can be classified against base text and inside-string state is
// honored. Each (path,lineNo) is classified once per scan.
// ---------------------------------------------------------------------------

function surfaceFor(p, lineNo, lines, states, cfg) {
  // C first — classify's C logic, honoring inside-string state (F2).
  if (CALL_EXT_RE.test(p)) {
    const idx = lineNo - 1;
    const line = lines[idx] || "";
    for (const pat of cfg.llm_call_patterns) {
      if (!line.includes(pat)) continue;
      if (isCommentLine(line)) continue;
      if (isDecoratorLine(line)) continue;
      if (states && states[idx] && states[idx].inside) continue; // inside """ / /* */
      if ((pat === "/v1/messages" || pat === "/chat/completions") && !hasRequestCallNearby(lines, idx)) continue;
      return "C";
    }
  }
  // A
  if (matchAny(p, cfg.always_loaded)) return "A";
  if (matchAny(p, cfg.agent_docs) && isFrontmatterDescription(lines, lineNo)) return "A";
  // B
  if (matchAny(p, cfg.agent_docs)) return "B";
  if (matchAny(p, ["**/*mandate*.md"])) return "B";
  // D
  if (matchAny(p, cfg.agent_output)) return "D";
  return null;
}

function accumulate(surf, surface, bytes, kind, p) {
  if (surface === "A") surf.A[kind] += bytes;
  else if (surface === "B") surf.B[kind] += bytes;
  else if (surface === "C") {
    surf.C[kind] += bytes;
    if (kind === "added") surf.C.sites++;
  } else if (surface === "D") {
    surf.D[kind] += bytes;
    if (kind === "added") surf.D.files.add(p);
  }
}

// ---------------------------------------------------------------------------
// scanDiff — pure: classify lines, accumulate surfaces, run rules (F4)
// ---------------------------------------------------------------------------
//
// entries: parseDiff output. files: Map<path, post-change text>. cfg: config.
// baseTexts (optional): Map<path, base text> for removed-line classification (F6).
// Returns { surfaces, findings, summary }.
//
export function scanDiff(entries, files, cfg, baseTexts) {
  const findings = [];
  let skippedBinary = 0;

  const surf = {
    A: { added: 0, removed: 0 },
    B: { added: 0, removed: 0 },
    C: { added: 0, removed: 0, sites: 0 },
    D: { added: 0, removed: 0, files: new Set() },
  };
  const baseTextsMap = baseTexts || new Map();
  const cSurfaceFiles = new Set();

  // Per-path caches (F1): fresh per scanDiff call so repeated invocations in
  // tests never see stale split/state results.
  const linesCache = new Map();
  const statesCache = new Map();
  const getLines = (p, text) => {
    let lines = linesCache.get(p);
    if (!lines) { lines = String(text).split("\n"); linesCache.set(p, lines); }
    return lines;
  };
  const getStates = (p, lines) => {
    let states = statesCache.get(p);
    if (!states) { states = computeLineStates(lines); statesCache.set(p, states); }
    return states;
  };

  // Classify each added/removed line ONCE; store results on entry.classified.
  for (const entry of entries) {
    if (entry.binary) { skippedBinary++; continue; }

    const p = entry.path;
    const postText = files.get(p);
    const postLines = postText ? getLines(p, postText) : null;
    const postStates = postLines ? getStates(p, postLines) : null;
    const baseText = baseTextsMap.get(p);
    const baseLines = baseText ? String(baseText).split("\n") : null;
    const baseStates = baseLines ? computeLineStates(baseLines) : null;

    entry.classified = { added: [], removed: [] };

    for (const add of entry.added) {
      const surface = postLines ? surfaceFor(p, add.line, postLines, postStates, cfg)
        : classify(p, add.line, add.text, cfg);
      const bytes = bytesOf(add.text);
      entry.classified.added.push({ line: add.line, text: add.text, surface, bytes });
      accumulate(surf, surface, bytes, "added", p);
      if (surface === "C") cSurfaceFiles.add(p);
    }

    for (const rem of entry.removed || []) {
      // F6: classify removed lines against base text (frontmatter-aware), using
      // the old-line number. Fall back to the removed line's own text.
      const remLines = baseLines || [rem.text];
      const remStates = baseStates || null;
      const ln = rem.oldLine != null ? rem.oldLine : rem.line;
      const surface = surfaceFor(p, ln, remLines, remStates, cfg);
      const bytes = bytesOf(rem.text);
      entry.classified.removed.push({ line: rem.line, text: rem.text, surface, bytes, oldLine: rem.oldLine });
      accumulate(surf, surface, bytes, "removed", p);
    }
  }

  // ----- Rules (F4): each rule's logic lives in RULES[i].run(ctx) -----
  const ctx = { entries, files, cfg, surf, cSurfaceFiles, netTokens, bytesOf, getLines, getStates, baseTextsMap };
  for (const rule of RULES) {
    findings.push(...rule.run(ctx));
  }

  // ----- Sort findings: WASTE first, then tokens desc, then path/line -----
  findings.sort((a, b) => {
    const ta = a.tag === "WASTE" ? 0 : 1;
    const tb = b.tag === "WASTE" ? 0 : 1;
    if (ta !== tb) return ta - tb;
    if (b.tokens !== a.tokens) return b.tokens - a.tokens;
    if (a.path !== b.path) return a.path < b.path ? -1 : 1;
    return a.line - b.line;
  });

  const wasteCount = findings.filter((f) => f.tag === "WASTE").length;
  const tradeoffCount = findings.length - wasteCount;

  const resultSurfaces = {
    A: { added: surf.A.added, removed: surf.A.removed, tokens: netTokens(surf.A.added, surf.A.removed) },
    B: { added: surf.B.added, removed: surf.B.removed, tokens: netTokens(surf.B.added, surf.B.removed) },
    C: { sites: surf.C.sites },
    D: { files: surf.D.files.size },
  };

  const summaryLine = `token-check: A ${formatSigned(netTokens(surf.A.added, surf.A.removed))} tok/session, B ${formatSigned(netTokens(surf.B.added, surf.B.removed))} tok/use, C ${surf.C.sites} call sites, D ${surf.D.files.size} files — ${wasteCount} WASTE, ${tradeoffCount} tradeoff`;

  return {
    surfaces: resultSurfaces,
    findings,
    summary: { waste: wasteCount, tradeoff: tradeoffCount, skipped_binary: skippedBinary, line: summaryLine },
  };
}

// ---------------------------------------------------------------------------
// Rule implementations (F4)
// ---------------------------------------------------------------------------

function runAbudget(ctx) {
  const { entries, cfg, surf, netTokens } = ctx;
  const aTokens = netTokens(surf.A.added, surf.A.removed);
  if (aTokens <= cfg.budgets.always_loaded_tokens) return [];
  for (const entry of entries) {
    if (entry.binary || entry.deleted || !entry.classified) continue;
    for (const add of entry.classified.added) {
      if (add.surface === "A") {
        return [{
          tag: "tradeoff", rule: "A-budget", surface: "A", path: entry.path, line: add.line,
          issue: `always-loaded surface over budget (${aTokens} tok > ${cfg.budgets.always_loaded_tokens})`,
          try: "move rationale/history to an on-demand reference doc; keep the rule line",
          verify: "the moved text is still reachable where agents need it",
          tokens: aTokens,
        }];
      }
    }
  }
  return [];
}

function runAdescLong(ctx) {
  const { entries, files, cfg, getLines, netTokens } = ctx;
  const findings = [];
  for (const entry of entries) {
    if (entry.binary || entry.deleted || !entry.classified) continue;
    const p = entry.path;
    const postText = files.get(p);
    if (!postText) continue;
    const postLines = getLines(p, postText);
    for (const add of entry.classified.added) {
      if (add.surface !== "A") continue;
      if (!isFrontmatterDescription(postLines, add.line)) continue;
      const bytes = bytesOf(add.text);
      if (bytes > DESC_LONG_BYTES) {
        findings.push({
          tag: "tradeoff", rule: "A-desc-long", surface: "A", path: p, line: add.line,
          issue: `frontmatter description over ${DESC_LONG_BYTES} bytes (${bytes})`,
          try: "shorten to the trigger phrase; move detail to the body",
          verify: "discovery still triggers on the same requests",
          tokens: netTokens(bytes, 0),
        });
      }
    }
  }
  return findings;
}

function runCnoCap(ctx) {
  const { entries, files, cfg, getLines, netTokens } = ctx;
  const findings = [];
  for (const entry of entries) {
    if (entry.binary || entry.deleted || !entry.classified) continue;
    const p = entry.path;
    const postText = files.get(p);
    if (!postText) continue;

    const hasCap = CAP_KEYWORDS.some((k) => postText.includes(k));
    if (hasCap) continue;

    const postLines = getLines(p, postText);
    for (const add of entry.classified.added) {
      if (add.surface !== "C") continue;

      // Enclosing call arguments: from call line to where ( ) { } balance, max 60 lines.
      let parenDepth = 0, braceDepth = 0, started = false, spread = false, forwardedBody = false;
      const start = add.line - 1;
      for (let j = start; j < Math.min(postLines.length, start + 60); j++) {
        const l = postLines[j];
        started = true;
        for (const ch of l) {
          if (ch === "(") parenDepth++;
          else if (ch === ")") parenDepth--;
          else if (ch === "{") braceDepth++;
          else if (ch === "}") braceDepth--;
        }
        if (SPREAD_RE.test(l)) spread = true;
        if (FORWARDED_BODY_RE.test(l)) forwardedBody = true;
        if (started && parenDepth === 0 && braceDepth === 0) break;
      }

      const tokens = netTokens(bytesOf(add.text), 0);
      if (forwardedBody) {
        findings.push({
          tag: "tradeoff", rule: "C-no-cap", surface: "C", path: p, line: add.line,
          issue: "body forwarded from caller — cap not verified",
          try: "cap forwarded from callers — not verified",
          verify: "the cap fits the longest legitimate answer",
          tokens,
        });
      } else if (spread) {
        findings.push({
          tag: "tradeoff", rule: "C-no-cap", surface: "C", path: p, line: add.line,
          issue: "call site without output cap, cap forwarded from callers",
          try: "cap forwarded from callers — not verified",
          verify: "the cap fits the longest legitimate answer",
          tokens,
        });
      } else {
        findings.push({
          tag: "WASTE", rule: "C-no-cap", surface: "C", path: p, line: add.line,
          issue: "call site without output cap",
          try: "set an explicit output cap",
          verify: "the cap fits the longest legitimate answer",
          tokens,
        });
      }
    }
  }
  return findings;
}

function runCpremiumLiteral(ctx) {
  const { entries, files, cSurfaceFiles, netTokens } = ctx;
  const findings = [];
  for (const entry of entries) {
    if (entry.binary || entry.deleted || !entry.classified) continue;
    const p = entry.path;
    if (!cSurfaceFiles.has(p)) continue;
    const postText = files.get(p);
    if (!postText) continue;
    for (const add of entry.classified.added) {
      if (!PREMIUM_RE.test(add.text)) continue;
      findings.push({
        tag: "tradeoff", rule: "C-premium-literal", surface: "C", path: p, line: add.line,
        issue: "premium model literal in C-surface file",
        try: "route through the repo's tier/router instead of a hard-coded premium model",
        verify: "the task still gets a model strong enough for it",
        tokens: netTokens(bytesOf(add.text), 0),
      });
    }
  }
  return findings;
}

function runDunbounded(ctx) {
  const { entries, files, cfg, getLines, netTokens } = ctx;
  const findings = [];
  for (const entry of entries) {
    if (entry.binary || entry.deleted || !entry.classified) continue;
    const p = entry.path;
    if (!matchAny(p, cfg.agent_output)) continue;
    const postText = files.get(p);
    if (!postText) continue;
    const hasOutputFlag = ["--json", "--limit", "--line", "--quiet"].some((f) => postText.includes(f));
    if (hasOutputFlag) continue;
    for (const add of entry.classified.added) {
      if (add.surface !== "D") continue;
      const t = add.text;
      const hasPrint = t.includes("console.log(") || t.includes("print(");
      const hasJSON = t.includes("JSON.stringify(");
      const hasSlice = t.includes(".slice(") || t.includes("[:");
      if (hasPrint && hasJSON && !hasSlice) {
        findings.push({
          tag: "tradeoff", rule: "D-unbounded", surface: "D", path: p, line: add.line,
          issue: "unbounded JSON output via console.log/print",
          try: "add a summary default and put the full dump behind --json",
          verify: "the full data is still available behind the flag",
          tokens: netTokens(bytesOf(t), 0),
        });
      }
    }
  }
  return findings;
}

// ---------------------------------------------------------------------------
// scan — run git, build file map, parse + scan
// ---------------------------------------------------------------------------

export function scan({ dir, base, all }) {
  // Resolve base: --base arg > adapter.json base > origin/main
  let resolvedBase = base;
  if (!resolvedBase) {
    try {
      const raw = fs.readFileSync(path.join(dir, ".opencode", "board", "adapter.json"), "utf8");
      const adapter = JSON.parse(raw);
      if (adapter && typeof adapter.base === "string") resolvedBase = adapter.base;
    } catch {
      // ignore → fall through to default
    }
    if (!resolvedBase) resolvedBase = "origin/main";
  }

  const git = (args) => {
    const r = spawnSync("git", args, { cwd: dir, encoding: "utf8", timeout: GIT_TIMEOUT_MS, maxBuffer: GIT_MAX_BUFFER });
    if (r.error) {
      console.error("token-check: git child timed out");
      process.exit(2);
    }
    return r;
  };

  // --dir must be a git work tree
  const inside = git(["rev-parse", "--is-inside-work-tree"]);
  if (inside.status !== 0 || String(inside.stdout).trim() !== "true") {
    console.error("token-check: --dir is not a git work tree");
    process.exit(2);
  }

  // --base must resolve
  const baseVerify = git(["rev-parse", "--verify", `${resolvedBase}^{commit}`]);
  if (baseVerify.status !== 0) {
    console.error(`token-check: --base ref does not resolve: ${resolvedBase}`);
    process.exit(2);
  }
  const baseSha = String(baseVerify.stdout).trim();

  const headRes = git(["rev-parse", "--verify", "HEAD^{commit}"]);
  if (headRes.status !== 0) {
    console.error("token-check: HEAD does not resolve");
    process.exit(2);
  }
  const headSha = String(headRes.stdout).trim();

  const mbRes = git(["merge-base", baseSha, headSha]);
  if (mbRes.status !== 0) {
    console.error(`token-check: no merge-base between ${resolvedBase} and HEAD`);
    process.exit(2);
  }
  const mb = String(mbRes.stdout).trim();

  let entries;
  const files = new Map();

  if (all) {
    const ls = git(["ls-files"]);
    if (ls.status !== 0) {
      console.error("token-check: git ls-files failed");
      process.exit(2);
    }
    const filePaths = String(ls.stdout).split("\n").filter(Boolean);
    entries = [];
    for (const fp of filePaths) {
      const fullPath = path.join(dir, fp);
      let text;
      try {
        text = fs.readFileSync(fullPath, "utf8");
      } catch {
        continue; // skipped silently if unreadable
      }
      // Binary: NUL byte in first 8000 bytes
      const headBuf = Buffer.from(text, "utf8").subarray(0, 8000);
      if (headBuf.includes(0x00)) continue;

      files.set(fp, text);
      const added = [];
      const tLines = text.split("\n");
      for (let i = 0; i < tLines.length; i++) {
        if (i === tLines.length - 1 && tLines[i] === "" && text.endsWith("\n")) continue;
        added.push({ line: i + 1, text: tLines[i] });
      }
      entries.push({ path: fp, binary: false, deleted: false, added, removed: [], removedBytes: 0 });
    }
  } else {
    const diff = git(["diff", "--no-ext-diff", "--no-color", "--no-renames", "--unified=0", mb, "--"]);
    if (diff.status !== 0) {
      console.error(`token-check: git diff failed: ${String(diff.stderr).trim() || diff.status}`);
      process.exit(2);
    }
    entries = parseDiff(String(diff.stdout));
    for (const entry of entries) {
      if (entry.binary || entry.deleted) continue;
      try {
        files.set(entry.path, fs.readFileSync(path.join(dir, entry.path), "utf8"));
      } catch {
        // skipped silently if unreadable
      }
    }
  }

  // F6: gather base-file text for removed-line (frontmatter) classification.
  const baseTexts = new Map();
  if (!all) {
    for (const entry of entries) {
      if (entry.binary || entry.deleted || !entry.removed.length) continue;
      const shown = git(["show", `${mb}:${entry.path}`]);
      if (shown.status === 0) baseTexts.set(entry.path, String(shown.stdout));
    }
  }

  const cfg = loadConfig(dir);
  const result = scanDiff(entries, files, cfg, baseTexts);
  return { base: resolvedBase, mb, head: headSha, all: Boolean(all), entries, files, cfg, ...result };
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

function printText(result) {
  const out = [];
  const shown = result.findings.slice(0, MAX_FINDING_LINES);
  for (const f of shown) {
    out.push(`[${f.tag}] ${f.surface} ${f.path}:${f.line} — ${f.issue} — try: ${f.try} — verify: ${f.verify}`);
  }
  const remaining = result.findings.length - MAX_FINDING_LINES;
  if (remaining > 0) out.push(`… ${remaining} more (--json for all)`);
  out.push(result.summary.line);
  console.log(out.join("\n"));
}

function printJson(result) {
  const obj = {
    base: result.base,
    mb: result.mb,
    head: result.head,
    all: result.all,
    surfaces: result.surfaces,
    findings: result.findings,
    summary: result.summary,
  };
  console.log(JSON.stringify(obj, null, 2));
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = process.argv.slice(2);
  let dir = process.cwd();
  let base = null;
  let json = false;
  let all = false;

  for (let i = 0; i < args.length; i++) {
    const a = args[i];
    if (a === "--dir") {
      if (i + 1 >= args.length) { console.error("token-check: --dir requires a value"); process.exit(2); }
      dir = args[++i];
    } else if (a === "--base") {
      if (i + 1 >= args.length) { console.error("token-check: --base requires a value"); process.exit(2); }
      base = args[++i];
    } else if (a === "--json") {
      json = true;
    } else if (a === "--all") {
      all = true;
    } else if (a === "--help" || a === "-h") {
      console.log("usage: token-check.mjs [--dir <path>] [--base ] [--json] [--all]");
      process.exit(0);
    } else {
      console.error(`token-check: unknown flag: ${a}`);
      process.exit(2);
    }
  }

  const result = scan({ dir, base, all });
  if (json) printJson(result);
  else printText(result);
  process.exit(0);
}

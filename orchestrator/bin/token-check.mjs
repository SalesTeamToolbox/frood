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

// ---------------------------------------------------------------------------
// Rules (exported RULES, five in T1)
// Each rule: { id, surface, tag, run(ctx) → findings[] }.
// The actual detection logic lives in scanDiff; run() mirrors it for the
// exported contract. ctx = { entries, files, cfg }.
//
export const RULES = [
  {
    id: "A-budget",
    surface: "A",
    tag: "tradeoff",
    run: (ctx) => [], // implemented inline in scanDiff
  },
  {
    id: "A-desc-long",
    surface: "A",
    tag: "tradeoff",
    run: (ctx) => [], // implemented inline in scanDiff
  },
  {
    id: "C-no-cap",
    surface: "C",
    tag: "WASTE",
    run: (ctx) => [], // implemented inline in scanDiff
  },
  {
    id: "C-premium-literal",
    surface: "C",
    tag: "tradeoff",
    run: (ctx) => [], // implemented inline in scanDiff
  },
  {
    id: "D-unbounded",
    surface: "D",
    tag: "tradeoff",
    run: (ctx) => [], // implemented inline in scanDiff
  },
];

const CALL_EXT_RE = /\.(py|js|mjs|cjs|ts|tsx)$/;
const MANDATE_RE = /mandate\.md$/i;
const PREMIUM_RE = /(opus|fable|gpt-5(?!-mini)|\bo3\b(?!-mini)|gemini-[\w.-]*-pro)/i;
const CAP_KEYWORDS = ["max_tokens", "max_output_tokens", "maxTokens", "max_completion_tokens"];
const SPREAD_RE = /\*\*kwargs|\*\*params|\.\.\.opts/;
const DESC_LONG_BYTES = 200;
const MAX_FINDING_LINES = 30;
const GIT_TIMEOUT_MS = 10000;
const GIT_MAX_BUFFER = 64 << 20;

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

// text: full file content. lineNo: 1-based line number to check.
// Returns true when the file starts with `---`, the line at lineNo lies before
// the closing `---`, and that line starts with `description:`.
export function isFrontmatterDescription(text, lineNo) {
  const lines = String(text).split("\n");
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

// Returns [{ path, binary, deleted, added: [{line, text}], removed: [{line, text}], removedBytes }].
// `removed` is extra (not in the published shape) so scanDiff can attribute
// removed bytes to surfaces. Line numbers come from the +c,d side of each @@
// hunk header (post-change numbering).
export function parseDiff(diffText) {
  const entries = [];
  const lines = String(diffText).split("\n");
  let i = 0;
  let current = null;

  while (i < lines.length) {
    const line = lines[i];

    if (line.startsWith("diff --git ")) {
      if (current) entries.push(current);
      current = { path: "", binary: false, deleted: false, added: [], removed: [], removedBytes: 0, postLine: 1 };
      // `diff --git <from> <to>`; prefixes vary (a/b, c/w with mnemonicprefix).
      // Take the "to" (second) path and strip any single-letter prefix.
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

    const hunkM = line.match(/^@@ -\d+(?:,\d+)? \+(\d+)(?:,\d+)? @@/);
    if (hunkM) {
      current.postLine = parseInt(hunkM[1], 10);
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
      current.removed.push({ line: current.postLine, text: line.slice(1) });
      current.removedBytes += Buffer.byteLength(line.slice(1), "utf8") + 1;
      i++;
      continue;
    }

    // Context line (or any other line) advances the post-change counter.
    if (line.startsWith(" ")) {
      current.postLine++;
    }
    i++;
  }

  if (current) entries.push(current);
  return entries;
}

// ---------------------------------------------------------------------------
// scanDiff — pure: classify lines, accumulate surfaces, run rules
// ---------------------------------------------------------------------------

export function scanDiff(entries, files, cfg) {
  const findings = [];
  let skippedBinary = 0;
  let lineCount = 0;

  const surf = {
    A: { added: 0, removed: 0 },
    B: { added: 0, removed: 0 },
    C: { added: 0, removed: 0, sites: 0 },
    D: { added: 0, removed: 0, files: new Set() },
  };

  // File text by path (for rules needing full-file context).
  const fileText = new Map();
  for (const [p, t] of files) fileText.set(p, t);

  // First pass: classify every added/removed line, accumulate bytes.
  for (const entry of entries) {
    if (entry.binary) { skippedBinary++; continue; }

    const p = entry.path;
    const ft = entry.deleted ? null : fileText.get(p);

    // Reconstruct file text from removed lines for deleted files so
    // isFrontmatterDescription can still work (best effort).
    const classifyText = ft !== null ? ft : (entry.deleted && entry.removed.length
      ? entry.removed.map((r) => r.text).join("\n")
      : null);

    for (const add of entry.added) {
      const surface = classify(p, add.line, classifyText !== null ? classifyText : add.text, cfg);
      const bytes = Buffer.byteLength(add.text, "utf8") + 1;
      lineCount++;
      if (surface === "A") surf.A.added += bytes;
      else if (surface === "B") surf.B.added += bytes;
      else if (surface === "C") { surf.C.added += bytes; surf.C.sites++; }
      else if (surface === "D") { surf.D.added += bytes; surf.D.files.add(p); }
    }

    for (const rem of entry.removed || []) {
      const surface = classify(p, rem.line, classifyText !== null ? classifyText : rem.text, cfg);
      const bytes = Buffer.byteLength(rem.text, "utf8") + 1;
      if (surface === "A") surf.A.removed += bytes;
      else if (surface === "B") surf.B.removed += bytes;
      else if (surface === "C") surf.C.removed += bytes;
      else if (surface === "D") surf.D.removed += bytes;
    }
  }

  // Mark C-surface files (files with ≥1 C call-site line added).
  const cSurfaceFiles = new Set();
  for (const entry of entries) {
    if (entry.binary || entry.deleted) continue;
    const p = entry.path;
    const ft = fileText.get(p);
    if (!ft) continue;
    for (const add of entry.added) {
      if (classify(p, add.line, ft, cfg) === "C") { cSurfaceFiles.add(p); break; }
    }
  }

  // ----- Rules -----

  const netTokens = (added, removed) => Math.ceil((added - removed) / 4);

  // A-budget: surface A net tokens > always_loaded_tokens; one finding at first added A line.
  const aTokens = netTokens(surf.A.added, surf.A.removed);
  if (aTokens > cfg.budgets.always_loaded_tokens) {
    for (const entry of entries) {
      if (entry.binary || entry.deleted) continue;
      const p = entry.path;
      const ft = fileText.get(p);
      if (!ft) continue;
      for (const add of entry.added) {
        if (classify(p, add.line, ft, cfg) === "A") {
          findings.push({
            tag: "tradeoff",
            rule: "A-budget",
            surface: "A",
            path: p,
            line: add.line,
            issue: `always-loaded surface over budget (${aTokens} tok > ${cfg.budgets.always_loaded_tokens})`,
            try: "move rationale/history to an on-demand reference doc; keep the rule line",
            verify: "the moved text is still reachable where agents need it",
            tokens: aTokens,
          });
          break;
        }
      }
      if (findings.some((f) => f.rule === "A-budget")) break;
    }
  }

  // A-desc-long: added frontmatter description line > 200 bytes.
  for (const entry of entries) {
    if (entry.binary || entry.deleted) continue;
    const p = entry.path;
    const ft = fileText.get(p);
    if (!ft) continue;
    for (const add of entry.added) {
      if (classify(p, add.line, ft, cfg) !== "A") continue;
      if (!isFrontmatterDescription(ft, add.line)) continue;
      const bytes = Buffer.byteLength(add.text, "utf8") + 1;
      if (bytes > DESC_LONG_BYTES) {
        findings.push({
          tag: "tradeoff",
          rule: "A-desc-long",
          surface: "A",
          path: p,
          line: add.line,
          issue: `frontmatter description over ${DESC_LONG_BYTES} bytes (${bytes})`,
          try: "shorten to the trigger phrase; move detail to the body",
          verify: "discovery still triggers on the same requests",
          tokens: netTokens(bytes, 0),
        });
      }
    }
  }

  // C-no-cap: C call-site line, file has no cap keyword, enclosing call args have no spread.
  for (const entry of entries) {
    if (entry.binary || entry.deleted) continue;
    const p = entry.path;
    const ft = fileText.get(p);
    if (!ft) continue;

    const hasCap = CAP_KEYWORDS.some((k) => ft.includes(k));
    if (hasCap) continue; // file has a cap somewhere → no C-no-cap finding

    for (const add of entry.added) {
      if (classify(p, add.line, ft, cfg) !== "C") continue;

      // Enclosing call arguments: from call line to where ( ) { } balance, max 60 lines.
      const flines = ft.split("\n");
      let parenDepth = 0, braceDepth = 0, started = false, spread = false;
      const start = add.line - 1;
      for (let j = start; j < Math.min(flines.length, start + 60); j++) {
        const l = flines[j];
        started = true;
        for (const ch of l) {
          if (ch === "(") parenDepth++;
          else if (ch === ")") parenDepth--;
          else if (ch === "{") braceDepth++;
          else if (ch === "}") braceDepth--;
        }
        if (SPREAD_RE.test(l)) spread = true;
        if (started && parenDepth === 0 && braceDepth === 0) break;
      }

      const lineBytes = Buffer.byteLength(add.text, "utf8") + 1;
      if (spread) {
        findings.push({
          tag: "tradeoff",
          rule: "C-no-cap",
          surface: "C",
          path: p,
          line: add.line,
          issue: "call site without output cap, cap forwarded from callers",
          try: "cap forwarded from callers — not verified",
          verify: "the cap fits the longest legitimate answer",
          tokens: netTokens(lineBytes, 0),
        });
      } else {
        findings.push({
          tag: "WASTE",
          rule: "C-no-cap",
          surface: "C",
          path: p,
          line: add.line,
          issue: "call site without output cap",
          try: "set an explicit output cap",
          verify: "the cap fits the longest legitimate answer",
          tokens: netTokens(lineBytes, 0),
        });
      }
    }
  }

  // C-premium-literal: added line in C-surface file with premium model literal.
  for (const entry of entries) {
    if (entry.binary || entry.deleted) continue;
    const p = entry.path;
    if (!cSurfaceFiles.has(p)) continue;
    const ft = fileText.get(p);
    if (!ft) continue;
    for (const add of entry.added) {
      if (!PREMIUM_RE.test(add.text)) continue;
      findings.push({
        tag: "tradeoff",
        rule: "C-premium-literal",
        surface: "C",
        path: p,
        line: add.line,
        issue: "premium model literal in C-surface file",
        try: "route through the repo's tier/router instead of a hard-coded premium model",
        verify: "the task still gets a model strong enough for it",
        tokens: netTokens(Buffer.byteLength(add.text, "utf8") + 1, 0),
      });
    }
  }

  // D-unbounded: added line in D file, console.log/print + JSON.stringify,
  // no .slice/[: on the line, file has none of --json/--limit/--line/--quiet.
  for (const entry of entries) {
    if (entry.binary || entry.deleted) continue;
    const p = entry.path;
    if (!matchAny(p, cfg.agent_output)) continue;
    const ft = fileText.get(p);
    if (!ft) continue;
    const hasOutputFlag = ["--json", "--limit", "--line", "--quiet"].some((f) => ft.includes(f));
    if (hasOutputFlag) continue;

    for (const add of entry.added) {
      if (classify(p, add.line, ft, cfg) !== "D") continue;
      const t = add.text;
      const hasPrint = t.includes("console.log(") || t.includes("print(");
      const hasJSON = t.includes("JSON.stringify(");
      const hasSlice = t.includes(".slice(") || t.includes("[:");
      if (hasPrint && hasJSON && !hasSlice) {
        findings.push({
          tag: "tradeoff",
          rule: "D-unbounded",
          surface: "D",
          path: p,
          line: add.line,
          issue: "unbounded JSON output via console.log/print",
          try: "add a summary default and put the full dump behind --json",
          verify: "the full data is still available behind the flag",
          tokens: netTokens(Buffer.byteLength(t, "utf8") + 1, 0),
        });
      }
    }
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

function formatSigned(n) {
  return n >= 0 ? `+${n}` : String(n);
}

function netTokens(added, removed) {
  return Math.ceil((added - removed) / 4);
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

  const cfg = loadConfig(dir);
  const result = scanDiff(entries, files, cfg);
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

// path: file path. lineNo: 1-based line number. text: full file content.
// cfg: resolved config (see loadConfig / DEFAULTS).
// Returns "A" | "B" | "C" | "D" | null.
export function classify(path, lineNo, text, cfg) {
  const p = String(path).replace(/\\/g, "/");
  const lines = String(text).split("\n");
  const line = lines[lineNo - 1] || "";

  // 1. C — LLM call site (call file + call pattern on this line). First match.
  if (CALL_EXT_RE.test(p)) {
    for (const pat of cfg.llm_call_patterns) {
      if (line.includes(pat)) return "C";
    }
  }

  // 2. A — always-loaded (every line), or agent_docs frontmatter description.
  if (matchAny(p, cfg.always_loaded)) return "A";
  if (matchAny(p, cfg.agent_docs) && isFrontmatterDescription(text, lineNo)) return "A";

  // 3. B — agent_docs body, or mandate file.
  if (matchAny(p, cfg.agent_docs)) return "B";
  if (MANDATE_RE.test(p)) return "B";

  // 4. D — agent-facing bin/output scripts.
  if (matchAny(p, cfg.agent_output)) return "D";

  return null;
}

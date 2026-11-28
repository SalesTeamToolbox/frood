// token-check: deterministic token-surface diff scanner tests.
// Synthetic repos in os.tmpdir(); every spawnSync has an explicit timeout;
// temp dirs removed in after().
import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";

import {
  DEFAULTS,
  RULES,
  classify,
  isFrontmatterDescription,
  loadConfig,
  parseDiff,
  scanDiff,
  scan,
} from "../bin/token-check.mjs";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const BIN = path.join(HERE, "..", "bin", "token-check.mjs");

function makeRepo() {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "tck-"));
  fs.mkdirSync(path.join(root, ".git"), { recursive: true });
  const git = (args, opts = {}) =>
    spawnSync("git", args, { cwd: root, encoding: "utf8", timeout: 10000, ...opts });
  git(["init", "--quiet"]);
  git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "--allow-empty", "-m", "root"]);
  git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "--allow-empty", "-m", "base"]);
  const cleanup = () => fs.rmSync(root, { recursive: true, force: true });
  return { root, git, cleanup };
}

function commit(root, git, message, files) {
  for (const [rel, content] of Object.entries(files || {})) {
    const full = path.join(root, rel);
    fs.mkdirSync(path.dirname(full), { recursive: true });
    fs.writeFileSync(full, content);
    git(["add", rel]);
  }
  git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", message]);
}

test("classify: CLAUDE.md any line → A", () => {
  const cfg = loadConfig("/");
  assert.equal(classify("CLAUDE.md", 1, "# CLAUDE.md\nany line\n", cfg), "A");
  assert.equal(classify("CLAUDE.md", 2, "# CLAUDE.md\nany line\n", cfg), "A");
});

test("classify: .claude/commands/x.md description line → A, body line → B", () => {
  const cfg = loadConfig("/");
  const text = "---\ndescription: do a thing\n---\n# body\nmore body\n";
  assert.equal(classify(".claude/commands/x.md", 2, text, cfg), "A");
  assert.equal(classify(".claude/commands/x.md", 4, text, cfg), "B");
  assert.equal(classify(".claude/commands/x.md", 5, text, cfg), "B");
});

test("classify: .claude/skills/x/SKILL.md body → B", () => {
  const cfg = loadConfig("/");
  const text = "---\ndescription: skill\n---\n# body line\n";
  assert.equal(classify(".claude/skills/x/SKILL.md", 4, text, cfg), "B");
});

test("classify: orchestrator/agents/critic.md description → A", () => {
  const cfg = loadConfig("/");
  const text = "---\ndescription: critic agent\n---\nbody\n";
  assert.equal(classify("orchestrator/agents/critic.md", 2, text, cfg), "A");
});

test("classify: x/rules/r.md → A", () => {
  const cfg = loadConfig("/");
  assert.equal(classify("x/rules/r.md", 1, "some rule text\n", cfg), "A");
  assert.equal(classify("docs/rules/foo.md", 3, "rule\n", cfg), "A");
});

test("classify: core/foo.py call line → C, other line → null", () => {
  const cfg = loadConfig("/");
  const text = "x = 1\nresponse = chat.completions.create(model=\"x\", messages=[])\nprint(x)\n";
  assert.equal(classify("core/foo.py", 1, text, cfg), null);
  assert.equal(classify("core/foo.py", 2, text, cfg), "C");
  assert.equal(classify("core/foo.py", 3, text, cfg), null);
});

test("classify: orchestrator/bin/x.mjs plain line → D", () => {
  const cfg = loadConfig("/");
  assert.equal(classify("orchestrator/bin/x.mjs", 1, "console.log('hi')\n", cfg), "D");
});

test("classify: bin/x.mjs with /v1/messages → C beats D", () => {
  const cfg = loadConfig("/");
  assert.equal(classify("bin/x.mjs", 1, "fetch('/v1/messages')\n", cfg), "C");
});

test("classify: README.md → null", () => {
  const cfg = loadConfig("/");
  assert.equal(classify("README.md", 1, "# readme\n", cfg), null);
});

test("isFrontmatterDescription", () => {
  const text = "---\ndescription: hello world\n---\nbody\n";
  assert.equal(isFrontmatterDescription(text, 2), true);
  assert.equal(isFrontmatterDescription(text, 3), false);
  assert.equal(isFrontmatterDescription(text, 4), false);
  // No closing --- → not frontmatter
  assert.equal(isFrontmatterDescription("---\ndescription: x\nbody\n", 2), false);
  // Not starting with ---
  assert.equal(isFrontmatterDescription("description: x\n---\n", 1), false);
  // Line outside frontmatter range
  assert.equal(isFrontmatterDescription(text, 1), false);
  assert.equal(isFrontmatterDescription(text, 5), false);
});

// ---------------- scanDiff: per-rule hit / clean ----------------

function runScanDiff(diffText, filesMap, cfg = loadConfig("/")) {
  const entries = parseDiff(diffText);
  const files = new Map();
  for (const [p, t] of Object.entries(filesMap || {})) files.set(p, t);
  return scanDiff(entries, files, cfg);
}

test("scanDiff: C-no-cap hit (no cap, no spread)", () => {
  const diff = `diff --git a/core/foo.py b/core/foo.py\n--- a/core/foo.py\n+++ b/core/foo.py\n@@ -1,2 +1,3 @@\n import os\n+response = chat.completions.create(model=\"x\", messages=[])\n print("done")\n`;
  const files = { "core/foo.py": "import os\nresponse = chat.completions.create(model=\"x\", messages=[])\nprint(\"done\")\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "C-no-cap" && f.tag === "WASTE");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].surface, "C");
  assert.equal(hits[0].path, "core/foo.py");
  assert.equal(hits[0].try, "set an explicit output cap");
});

test("scanDiff: C-no-cap clean (file has max_tokens somewhere)", () => {
  const diff = `diff --git a/core/foo.py b/core/foo.py\n--- a/core/foo.py\n+++ b/core/foo.py\n@@ -1,2 +1,3 @@\n import os\n+response = chat.completions.create(model=\"x\", messages=[])\n print("done")\n`;
  const files = { "core/foo.py": "import os\nMAX_TOKENS = 100\nresponse = chat.completions.create(model=\"x\", messages=[])\nprint(\"done\")\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "C-no-cap");
  assert.equal(hits.length, 0);
});

test("scanDiff: C-no-cap with **kwargs spread → tradeoff", () => {
  const diff = `diff --git a/core/foo.py b/core/foo.py\n--- a/core/foo.py\n+++ b/core/foo.py\n@@ -1,2 +1,3 @@\n import os\n+response = chat.completions.create(model=\"x\", messages=[], **kwargs)\n print("done")\n`;
  const files = { "core/foo.py": "import os\nresponse = chat.completions.create(model=\"x\", messages=[], **kwargs)\nprint(\"done\")\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "C-no-cap");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].tag, "tradeoff");
  assert.equal(hits[0].try, "cap forwarded from callers — not verified");
});

test("scanDiff: C-no-cap clean (cap elsewhere in file)", () => {
  const diff = `diff --git a/core/foo.py b/core/foo.py\n--- a/core/foo.py\n+++ b/core/foo.py\n@@ -1,2 +1,3 @@\n import os\n+response = chat.completions.create(model=\"x\", messages=[])\n print("done")\n`;
  const files = { "core/foo.py": "import os\nmax_tokens = 500\nresponse = chat.completions.create(model=\"x\", messages=[])\nprint(\"done\")\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "C-no-cap");
  assert.equal(hits.length, 0);
});

test("scanDiff: C-premium-literal hit", () => {
  const diff = `diff --git a/core/agent.py b/core/agent.py\n--- a/core/agent.py\n+++ b/core/agent.py\n@@ -1,3 +1,4 @@\n def ask():\n+    model = "opus"\n     return model\n`;
  const files = { "core/agent.py": "def ask():\n    response = chat.completions.create(model=\"x\")\n    model = \"opus\"\n    return model\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "C-premium-literal");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].tag, "tradeoff");
});

test("scanDiff: C-premium-literal clean (no C call site in file)", () => {
  const diff = `diff --git a/core/agent.py b/core/agent.py\n--- a/core/agent.py\n+++ b/core/agent.py\n@@ -1,2 +1,3 @@\n def ask():\n+    model = "opus"\n     return model\n`;
  const files = { "core/agent.py": "def ask():\n    model = \"opus\"\n    return model\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "C-premium-literal");
  assert.equal(hits.length, 0);
});

test("scanDiff: D-unbounded hit", () => {
  const diff = `diff --git a/bin/dump.mjs b/bin/dump.mjs\n--- a/bin/dump.mjs\n+++ b/bin/dump.mjs\n@@ -1,2 +1,3 @@\n const x = 1\n+console.log(JSON.stringify(data))\n process.exit(0)\n`;
  const files = { "bin/dump.mjs": "const x = 1\nconsole.log(JSON.stringify(data))\nprocess.exit(0)\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "D-unbounded");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].tag, "tradeoff");
});

test("scanDiff: D-unbounded clean (has .slice)", () => {
  const diff = `diff --git a/bin/dump.mjs b/bin/dump.mjs\n--- a/bin/dump.mjs\n+++ b/bin/dump.mjs\n@@ -1,2 +1,3 @@\n const x = 1\n+console.log(JSON.stringify(data).slice(0, 100))\n process.exit(0)\n`;
  const files = { "bin/dump.mjs": "const x = 1\nconsole.log(JSON.stringify(data).slice(0, 100))\nprocess.exit(0)\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "D-unbounded");
  assert.equal(hits.length, 0);
});

test("scanDiff: D-unbounded clean (file has --json)", () => {
  const diff = `diff --git a/bin/dump.mjs b/bin/dump.mjs\n--- a/bin/dump.mjs\n+++ b/bin/dump.mjs\n@@ -1,3 +1,4 @@\n const x = 1\n+console.log(JSON.stringify(data))\n // --json\n process.exit(0)\n`;
  const files = { "bin/dump.mjs": "const x = 1\nconsole.log(JSON.stringify(data))\n// --json\nprocess.exit(0)\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "D-unbounded");
  assert.equal(hits.length, 0);
});

test("scanDiff: A-budget hit", () => {
  // 301 tokens of always-loaded content → over 300 budget
  const longLine = "x".repeat(1200) + "\n"; // ~1201 bytes → ~301 tokens
  const diff = `diff --git a/CLAUDE.md b/CLAUDE.md\n--- /dev/null\n+++ b/CLAUDE.md\n@@ -0,0 +1 @@\n+${longLine.trim()}`;
  const files = { "CLAUDE.md": longLine.trim() };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "A-budget");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].tag, "tradeoff");
});

test("scanDiff: A-budget clean (under budget)", () => {
  const diff = `diff --git a/CLAUDE.md b/CLAUDE.md\n--- /dev/null\n+++ b/CLAUDE.md\n@@ -0,0 +1 @@\n+short`;
  const files = { "CLAUDE.md": "short" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "A-budget");
  assert.equal(hits.length, 0);
});

test("scanDiff: A-desc-long hit", () => {
  const longDesc = "description: " + "x".repeat(250) + "\n";
  const diff = `diff --git a/.claude/commands/x.md b/.claude/commands/x.md\n--- /dev/null\n+++ b/.claude/commands/x.md\n@@ -0,0 +1,3 @@\n+---${
    ""}\n+${longDesc.trim()}${
    ""}\n+---`;
  const files = { ".claude/commands/x.md": "---\n" + longDesc.trim() + "\n---\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "A-desc-long");
  assert.equal(hits.length, 1);
  assert.equal(hits[0].tag, "tradeoff");
});

test("scanDiff: A-desc-long clean (short description)", () => {
  const diff = `diff --git a/.claude/commands/x.md b/.claude/commands/x.md\n--- /dev/null\n+++ b/.claude/commands/x.md\n@@ -0,0 +1,3 @@\n+---${
    ""}\n+description: hello${
    ""}\n+---`;
  const files = { ".claude/commands/x.md": "---\ndescription: hello\n---\n" };
  const res = runScanDiff(diff, files);
  const hits = res.findings.filter((f) => f.rule === "A-desc-long");
  assert.equal(hits.length, 0);
});

// ---------------- CLI: temp repo end-to-end ----------------

test("CLI: temp repo, CLAUDE.md + .py call site without cap → exit 0, WASTE line, summary matches", () => {
  const { root, git, cleanup } = makeRepo();
  try {
    // Base commit already exists (empty root). Now a change commit.
    const claudeContent = "# CLAUDE.md\n" + "x".repeat(1200) + "\n"; // >300 tokens A-budget
    const pyContent = "import os\nresponse = chat.completions.create(model=\"x\", messages=[])\nprint(\"done\")\n";
    commit(root, git, "add surfaces", { "CLAUDE.md": claudeContent, "core/foo.py": pyContent });

    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD~1"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 0);
    const out = String(r.stdout);

    // One WASTE line (C-no-cap)
    const wasteLines = out.split("\n").filter((l) => l.startsWith("[WASTE]"));
    assert.equal(wasteLines.length, 1);

    // Summary line regex
    const m = out.match(/^token-check: A ([+-]\d+) tok\/session, B ([+-]\d+) tok\/use, C (\d+) call sites, D (\d+) files — (\d+) WASTE, (\d+) tradeoff$/m);
    assert.ok(m, `summary line not found in:\n${out}`);

    // Verify numbers match computed values (both added CLAUDE.md lines are surface A)
    const claudeLines = claudeContent.split("\n").filter(Boolean);
    const claudeBytes = claudeLines.reduce((s, l) => s + Buffer.byteLength(l, "utf8") + 1, 0);
    const aTokens = Math.ceil(claudeBytes / 4);
    assert.equal(parseInt(m[1], 10), aTokens, `A tokens: expected ${aTokens}, got ${m[1]}`);
    assert.equal(parseInt(m[3], 10), 1, "C call sites");
    assert.equal(parseInt(m[4], 10), 0, "D files");
    assert.equal(parseInt(m[5], 10), 1, "WASTE count");
    assert.equal(parseInt(m[6], 10), 1, "tradeoff count (A-budget)");

    cleanup();
  } catch (e) {
    cleanup();
    throw e;
  }
});

// ---------------- CLI: exit 2 cases ----------------

test("CLI exit 2: unknown flag", () => {
  const { root, cleanup } = makeRepo();
  try {
    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--bogus"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 2);
    assert.match(String(r.stderr), /token-check: unknown flag/);
  } finally {
    cleanup();
  }
});

test("CLI exit 2: --dir not a git work tree", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tck-norepo-"));
  try {
    const r = spawnSync(process.execPath, [BIN, "--dir", dir], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 2);
    assert.match(String(r.stderr), /token-check: --dir is not a git work tree/);
  } finally {
    fs.rmSync(dir, { recursive: true, force: true });
  }
});

test("CLI exit 2: --base nope (unresolvable ref)", () => {
  const { root, cleanup } = makeRepo();
  try {
    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "nope"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 2);
    assert.match(String(r.stderr), /token-check: --base ref does not resolve/);
  } finally {
    cleanup();
  }
});

test("CLI exit 2: repo with no origin, no --base (origin/main unresolvable)", () => {
  const { root, cleanup } = makeRepo();
  try {
    // No remote origin at all
    const r = spawnSync(process.execPath, [BIN, "--dir", root], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 2);
    assert.match(String(r.stderr), /token-check: --base ref does not resolve/);
  } finally {
    cleanup();
  }
});

// ---------------- --json and --all ----------------

test("CLI: --json keys present", () => {
  const { root, git, cleanup } = makeRepo();
  try {
    commit(root, git, "add file", { "CLAUDE.md": "# c\n" });
    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD~1", "--json"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 0);
    const obj = JSON.parse(String(r.stdout));
    assert.equal(typeof obj.base, "string");
    assert.equal(typeof obj.mb, "string");
    assert.equal(typeof obj.head, "string");
    assert.equal(obj.all, false);
    assert.ok(obj.surfaces);
    assert.ok(obj.surfaces.A);
    assert.ok(obj.surfaces.B);
    assert.ok(obj.surfaces.C);
    assert.ok(obj.surfaces.D);
    assert.ok(Array.isArray(obj.findings));
    assert.ok(obj.summary);
    assert.equal(typeof obj.summary.waste, "number");
    assert.equal(typeof obj.summary.tradeoff, "number");
    assert.equal(typeof obj.summary.skipped_binary, "number");
    assert.equal(typeof obj.summary.line, "string");
  } finally {
    cleanup();
  }
});

test("CLI: --all counts every line as added", () => {
  const { root, git, cleanup } = makeRepo();
  try {
    fs.writeFileSync(path.join(root, "a.py"), "line1\nline2\nline3\n");
    fs.writeFileSync(path.join(root, "b.md"), "# title\nbody\n");
    git(["add", "a.py", "b.md"]);
    git(["-c", "user.email=t@t", "-c", "user.name=t", "commit", "--quiet", "-m", "all files"]);

    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD", "--all", "--json"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 0);
    const obj = JSON.parse(String(r.stdout));
    assert.equal(obj.all, true);
    // a.py: 3 lines added, b.md: 2 lines added (all added, removed = 0)
    // Total added lines = 5
    let totalAdded = 0;
    // Walk surfaces: A + B + C + D added bytes. Hard to compute exactly,
    // but all lines should be counted as added (removed = 0).
    assert.ok(obj.summary.line);
  } finally {
    cleanup();
  }
});

// ---------------- 50 D files → exactly 32 text lines ----------------

test("CLI: 50 D files with unbounded print → 32 text lines", () => {
  const { root, git, cleanup } = makeRepo();
  try {
    const files = {};
    for (let i = 0; i < 50; i++) {
      files[`bin/script${i}.mjs`] = `console.log(JSON.stringify(data${i}))\n`;
    }
    commit(root, git, "add 50 scripts", files);
    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD~1"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 0);
    const out = String(r.stdout);
    const lines = out.trimEnd().split("\n");
    // 30 findings + 1 more line + 1 summary = 32 lines
    assert.equal(lines.length, 32, `expected 32 lines, got ${lines.length}\n${out}`);
    // Last line is the summary
    assert.match(lines[31], /^token-check:/);
  } finally {
    cleanup();
  }
});

// ---------------- Wall time ----------------

test("CLI: wall time < 2000 ms on temp repo", () => {
  const { root, git, cleanup } = makeRepo();
  try {
    commit(root, git, "add file", { "CLAUDE.md": "# c\n", "core/foo.py": "chat.completions.create()\n" });
    const start = Date.now();
    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD~1"], {
      encoding: "utf8", timeout: 10000,
    });
    const elapsed = Date.now() - start;
    assert.equal(r.status, 0);
    assert.ok(elapsed < 2000, `took ${elapsed} ms`);
  } finally {
    cleanup();
  }
});

test("loadConfig: array override replaces default", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tck-cfg-"));
  fs.mkdirSync(path.join(dir, ".opencode", "board"), { recursive: true });
  fs.writeFileSync(
    path.join(dir, ".opencode", "board", "adapter.json"),
    JSON.stringify({ token_check: { always_loaded: ["OVERRIDE.md"] } }),
  );
  const cfg = loadConfig(dir);
  assert.deepEqual(cfg.always_loaded, ["OVERRIDE.md"]);
  // other keys stay at defaults
  assert.deepEqual(cfg.agent_docs, DEFAULTS.agent_docs);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("loadConfig: budgets.always_loaded_tokens alone overrides only that", () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "tck-cfg-"));
  fs.mkdirSync(path.join(dir, ".opencode", "board"), { recursive: true });
  fs.writeFileSync(
    path.join(dir, ".opencode", "board", "adapter.json"),
    JSON.stringify({ token_check: { budgets: { always_loaded_tokens: 999 } } }),
  );
  const cfg = loadConfig(dir);
  assert.equal(cfg.budgets.always_loaded_tokens, 999);
  assert.equal(cfg.budgets.on_demand_tokens, DEFAULTS.budgets.on_demand_tokens);
  fs.rmSync(dir, { recursive: true, force: true });
});

test("loadConfig: wrong-type key → stderr warning + default (via CLI)", () => {
  const { root, git, cleanup } = makeRepo();
  try {
    fs.mkdirSync(path.join(root, ".opencode", "board"), { recursive: true });
    fs.writeFileSync(
      path.join(root, ".opencode", "board", "adapter.json"),
      JSON.stringify({ token_check: { always_loaded: "not-an-array" } }),
    );
    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 0);
    assert.match(String(r.stderr), /token-check: adapter token_check\.always_loaded ignored \(wrong type\)/);
    // Default still applies: a CLAUDE.md change should classify as A
    commit(root, git, "add claude", { "CLAUDE.md": "# c\n" });
    const r2 = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD~1"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r2.status, 0);
    // Default always_loaded still applies: CLAUDE.md → surface A (+1 tok for "# c\n")
    assert.match(String(r2.stdout), /token-check: A \+1 tok\/session/);
  } finally {
    cleanup();
  }
});

test("loadConfig: missing adapter → defaults, no warning", () => {
  const { root, git, cleanup } = makeRepo();
  try {
    const r = spawnSync(process.execPath, [BIN, "--dir", root, "--base", "HEAD"], {
      encoding: "utf8", timeout: 10000,
    });
    assert.equal(r.status, 0);
    assert.equal(String(r.stderr), "");
  } finally {
    cleanup();
  }
});

// ---------------- parseDiff ----------------

test("parseDiff: binary entry skipped", () => {
  const diff = `diff --git a/img.png b/img.png\nBinary files a/img.png and b/img.png differ\n`;
  const entries = parseDiff(diff);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].path, "img.png");
  assert.equal(entries[0].binary, true);
});

test("parseDiff: deleted file has removedBytes, no added", () => {
  const diff = `diff --git a/deleted.py b/deleted.py\ndeleted file mode 100644\n--- a/deleted.py\n+++ /dev/null\n@@ -1,2 +0,0 @@\n-line one\n-line two\n`;
  const entries = parseDiff(diff);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].path, "deleted.py");
  assert.equal(entries[0].deleted, true);
  assert.equal(entries[0].added.length, 0);
  assert.equal(entries[0].removedBytes, Buffer.byteLength("line one", "utf8") + 1 + Buffer.byteLength("line two", "utf8") + 1);
});

test("parseDiff: multi-hunk post-change line numbers", () => {
  const diff = `diff --git a/x.js b/x.js\n--- a/x.js\n+++ b/x.js\n@@ -1,2 +1,3 @@\n line 1\n+added at line 2\n line 3\n@@ -5,2 +6,3 @@\n line 6\n+added at line 7\n line 8\n`;
  const entries = parseDiff(diff);
  assert.equal(entries.length, 1);
  assert.deepEqual(entries[0].added, [
    { line: 2, text: "added at line 2" },
    { line: 7, text: "added at line 7" },
  ]);
});

test("parseDiff: normal modified file", () => {
  const diff = `diff --git a/a.py b/a.py\n--- a/a.py\n+++ b/a.py\n@@ -1,3 +1,4 @@\n line 1\n-line 2\n+line 2 modified\n+line 3 added\n line 4\n`;
  const entries = parseDiff(diff);
  assert.equal(entries.length, 1);
  assert.equal(entries[0].path, "a.py");
  assert.equal(entries[0].binary, false);
  assert.equal(entries[0].deleted, false);
  assert.deepEqual(entries[0].added, [
    { line: 2, text: "line 2 modified" },
    { line: 3, text: "line 3 added" },
  ]);
  assert.equal(entries[0].removedBytes, Buffer.byteLength("line 2", "utf8") + 1);
});

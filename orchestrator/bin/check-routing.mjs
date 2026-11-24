#!/usr/bin/env node
// Routing lint. Fails (exit 1) when routing instructions can't be trusted:
//   - an OpenCode model ID (opencode/, opencode-go/, commandcode/, nvidia/) is not in live `opencode models`
//   - a model the rule lists under "Dropped" appears in a dispatch file (commands/, agents/, skills/, CLAUDE.md)
//   - a Claude Code model value is not an alias (haiku|sonnet|opus|fable|inherit), e.g. Task({ model: "claude-sonnet-4-5" })
//   - a rules/ file uses bare "CC" (ambiguous: Claude Code vs CommandCode)
//
//   node bin/check-routing.mjs [--root <dir>] [--extra <file>]... [--models-file <file>]
// Defaults: --root = this repo, --extra = ~/.claude/CLAUDE.md, models from `opencode models`.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { modelAllowed, lacksDecision } from "./pool-health.mjs";
import { CHAINS } from "./chains.mjs";

const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const CC_ALIASES = new Set(["haiku", "sonnet", "opus", "fable", "inherit"]);
const OC_ID = /(?<![\w.\/\\~-])(?:opencode-go|opencode|commandcode|nvidia)\/[A-Za-z0-9._\-/]*[A-Za-z0-9]/g;

function parseArgs(argv) {
  const a = { root: REPO, extra: [], modelsFile: null };
  for (let i = 0; i < argv.length; i++) {
    if (argv[i] === "--root") a.root = argv[++i];
    else if (argv[i] === "--extra") a.extra.push(argv[++i]);
    else if (argv[i] === "--models-file") a.modelsFile = argv[++i];
  }
  if (!argv.includes("--extra")) a.extra.push(path.join(process.env.ORCH_HOME || os.homedir(), ".claude", "CLAUDE.md"));
  return a;
}

function liveModels(modelsFile) {
  let text;
  if (modelsFile) text = fs.readFileSync(modelsFile, "utf8");
  else {
    try {
      text = execFileSync("opencode", ["models"], { encoding: "utf8", timeout: 120000, shell: process.platform === "win32" });
    } catch (e) {
      return null;
    }
  }
  return new Set(text.split(/\r?\n/).map((l) => l.trim()).filter(Boolean));
}

function walk(dir) {
  if (!fs.existsSync(dir)) return [];
  const out = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    if (ent.name === "node_modules" || ent.name.startsWith(".")) continue;
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) out.push(...walk(p));
    else if (ent.name.endsWith(".md")) out.push(p);
  }
  return out;
}

function droppedIds(ruleText) {
  const line = ruleText.split("\n").find((l) => /\*\*Dropped/.test(l));
  if (!line) return [];
  return [...line.matchAll(/`([^`]+)`/g)].map((m) => m[1]).filter((s) => s.includes("/") || s.startsWith("claude-"));
}

function matchesDropped(id, dropped) {
  return dropped.some((d) => (d.endsWith("/*") ? id.startsWith(d.slice(0, -1)) : id === d));
}

// Worker roles that must be dispatched via `--role <name>` (one chain source in bin/chains.mjs).
const WORKER_ROLES = new Set(["worker", "worker-strong", "worker-nvidia", "worker-free", "worker-burst", "worker-alt"]);

// Extract `--agent <role> --fallback <a,b,...>` chains from a doc's text, scoped to worker roles.
// The fallback value is trimmed of a trailing backtick (e.g. ``--fallback a,b,c` ``).
function workerFallbackChains(text) {
  const out = [];
  const lines = text.split("\n");
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    const agentM = line.match(/--agent\s+(\S+)/);
    const fbM = line.match(/--fallback\s+([^\s`]+)/);
    if (!agentM || !fbM) continue;
    const agent = agentM[1];
    if (!WORKER_ROLES.has(agent)) continue;
    const fallback = fbM[1].split(",").map((s) => s.trim().replace(/`+$/, "")).filter(Boolean);
    out.push({ agent, fallback, lineNo: i + 1 });
  }
  return out;
}

function eq(a, b) {
  return a.length === b.length && a.every((v, i) => v === b[i]);
}

export function checkRouting({ root = REPO, extra = [], models = null } = {}) {
  const problems = [];
  const warn = [];
  const files = [...["commands", "agents", "skills", "rules"].flatMap((d) => walk(path.join(root, d))), ...extra.filter((f) => fs.existsSync(f))];
  const rule = files.find((f) => /01-orchestrator-models\.md$/.test(f));
  const dropped = rule ? droppedIds(fs.readFileSync(rule, "utf8")) : [];
  if (!models) warn.push("`opencode models` unavailable — live ID check skipped");

  for (const file of files) {
    const rel = path.relative(root, file).replace(/\\/g, "/");
    const isRule = rel.startsWith("rules/");
    const isCcAgent = rel.startsWith("agents/");
    const lines = fs.readFileSync(file, "utf8").replace(/\r\n/g, "\n").split("\n");
    lines.forEach((line, i) => {
      const at = `${rel.startsWith("..") ? file : rel}:${i + 1}`;
      for (const m of line.matchAll(OC_ID)) {
        const id = m[0];
        if (/^\/?\*/.test(line.slice(m.index + id.length))) continue; // wildcard mention like commandcode/Qwen/*
        if (models && !models.has(id)) problems.push(`${at}  unknown model ID \`${id}\` (not in opencode models)`);
        if (!isRule && matchesDropped(id, dropped)) problems.push(`${at}  dropped model \`${id}\` used in a dispatch file`);
      }
      // Claude Code model values: Task/Agent call args, and cc-only frontmatter in agents/
      for (const m of line.matchAll(/(?:Task|Agent)\s*\(\s*\{?[^)]*?\bmodel:\s*["']([^"']+)["']/g)) {
        if (!CC_ALIASES.has(m[1])) problems.push(`${at}  Claude Code model must be an alias (haiku|sonnet|opus|fable), got \`${m[1]}\``);
      }
      if (isCcAgent) {
        const fm = line.match(/^model:\s*(\S+)\s*#\s*cc-only/);
        if (fm && !CC_ALIASES.has(fm[1])) problems.push(`${at}  Claude Code agent model must be an alias, got \`${fm[1]}\``);
      }
      if (isRule && /(?<!["“])\bCC\b(?!["”])/.test(line)) problems.push(`${at}  bare "CC" is ambiguous — write "Claude Code" or "CmdC"`);
    });
    // Worker-chain lint: any hand-typed `--agent worker|worker-strong --fallback ...` in
    // commands/ or rules/ must match CHAINS and preferably use `--role <name>` instead.
    const isDispatchDoc = rel.startsWith("commands/") || rel.startsWith("rules/");
    if (isDispatchDoc) {
      for (const { agent, fallback, lineNo } of workerFallbackChains(lines.join("\n"))) {
        const expected = CHAINS[agent];
        const full = [agent, ...fallback];
        const at = `${rel}:${lineNo}`;
        if (!expected || !eq(full, expected)) {
          problems.push(`${at}  worker dispatch chain \`--agent ${agent} --fallback ${fallback.join(",")}\` disagrees with CHAINS.${agent} (expected ${expected.join(",")}); use \`--role ${agent}\``);
        } else {
          problems.push(`${at}  hand-typed \`--agent ${agent} --fallback ${fallback.join(",")}\` should use \`--role ${agent}\` instead`);
        }
      }
    }
  }
  // Installed OpenCode agents must not be pinned to a model the owner's provider policy rejects.
  for (const dir of ["agents", "agent"]) {
    const d = path.join(process.env.ORCH_HOME || os.homedir(), ".config", "opencode", dir);
    let names = [];
    try { names = fs.readdirSync(d).filter((n) => n.endsWith(".md")); } catch {}
    for (const n of names) {
      const m = fs.readFileSync(path.join(d, n), "utf8").split(/\r?\n---/)[0].match(/^model:\s*(\S+)/m);
      if (m && lacksDecision(m[1])) problems.push(`${path.join(d, n)}  provider ${m[1].split("/")[0]} has no owner decision (router-health --decide)`);
      if (m && !modelAllowed(m[1])) problems.push(`${path.join(d, n)}  agent pinned to \`${m[1]}\`, which provider policy does not allow (providers.json)`);
    }
  }
  return { problems, warn, filesChecked: files.length };
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const a = parseArgs(process.argv.slice(2));
  const { problems, warn, filesChecked } = checkRouting({ root: a.root, extra: a.extra, models: liveModels(a.modelsFile) });
  for (const w of warn) console.log(`check-routing: WARN ${w}`);
  for (const p of problems) console.log(`check-routing: ${p}`);
  console.log(problems.length ? `check-routing: FAILED — ${problems.length} problem(s) in ${filesChecked} files` : `check-routing: OK — ${filesChecked} files`);
  process.exit(problems.length ? 1 : 0);
}

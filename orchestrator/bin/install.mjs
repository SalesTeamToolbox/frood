#!/usr/bin/env node
// Orchestrator installer: renders repo sources into Claude Code + OpenCode config dirs.
// The source of truth is the Frood repo's `orchestrator/` directory (this tree). Edit here, run
// install; never hand-edit the installed copies (they are overwritten).
//
//   node bin/install.mjs            install (backs up anything it overwrites or removes)
//   node bin/install.mjs --check    report drift; exit 1 if any installed file differs/missing/orphaned
//   node bin/install.mjs --dry-run  show what install would do, write nothing
//
// Install also registers the peer-mail MCP server with Claude Code at user scope (bin/mcp-register.mjs) when Claude
// Code is on the machine; --check prints a WARN line (it does not fail) when it is missing. ORCH_SKIP_MCP=1 skips both.
// ORCH_HOME overrides the home directory (tests). Never creates symlinks or junctions.
import "./no-window.mjs"; // hide console windows of every child process (Windows)
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { registerPeerMail, peerMailDrift } from "./mcp-register.mjs";

export const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const HARNESSES = ["cc", "oc"];
const fwd = (p) => p.replace(/\\/g, "/");
// Paths are baked into installed copies at install time (nothing personal is tracked in this repo).
export const REPO_FWD = fwd(REPO);
export const MANAGED = `<!-- managed by Frood (${REPO_FWD}). Edit it there, then run install. Local edits are overwritten. -->`;

export function homeDir() {
  return process.env.ORCH_HOME || os.homedir();
}

function homeFwd() {
  return fwd(homeDir());
}

function expand(p) {
  return p.startsWith("~/") ? path.join(homeDir(), p.slice(2)) : p;
}

export function statePath() {
  return path.join(homeDir(), ".config", "orchestrator", "installed.json");
}

// Keep lines for `harness`, drop lines/blocks tagged for the other harness, strip the tags.
export function renderForHarness(text, harness) {
  const other = harness === "cc" ? "oc" : "cc";
  const out = [];
  let skipping = null; // tag of the block being dropped
  let keeping = null; // tag of the block being kept (just drop its marker lines)
  for (const line of text.split("\n")) {
    const open = line.match(/^\s*<!--\s*(cc|oc)-only\s*-->\s*$/);
    const close = line.match(/^\s*<!--\s*\/(cc|oc)-only\s*-->\s*$/);
    if (open) {
      if (open[1] === other) skipping = other;
      else keeping = harness;
      continue;
    }
    if (close) {
      if (close[1] === skipping) skipping = null;
      else if (close[1] === keeping) keeping = null;
      continue;
    }
    if (skipping) continue;
    const tag = line.match(/\s*(?:#|<!--)\s*(cc|oc)-only\s*(?:-->)?\s*$/);
    if (tag) {
      if (tag[1] === other) continue;
      out.push(line.slice(0, tag.index));
      continue;
    }
    out.push(line);
  }
  if (skipping) throw new Error(`unclosed <!-- ${skipping}-only --> block`);
  return out.join("\n");
}

// Insert the managed marker right after YAML frontmatter (frontmatter must stay on line 1).
export function addManagedHeader(text) {
  if (text.startsWith("---\n")) {
    const end = text.indexOf("\n---\n", 4);
    if (end !== -1) {
      const cut = end + 5;
      return text.slice(0, cut) + MANAGED + "\n" + text.slice(cut);
    }
  }
  return MANAGED + "\n" + text;
}

// Tokens let the tracked sources stay path-free: {{ORCH_REPO}} = this repo, {{HOME}} = the install home.
// Replaced before the `.md` check so hooks (`.js`) get them too.
export function render(srcFile, harness) {
  const raw = fs
    .readFileSync(srcFile, "utf8")
    .replace(/\r\n/g, "\n")
    .replaceAll("{{ORCH_REPO}}", REPO_FWD)
    .replaceAll("{{HOME}}", homeFwd());
  if (!srcFile.endsWith(".md")) return raw;
  return addManagedHeader(renderForHarness(raw, harness));
}

function walk(dir) {
  const files = [];
  for (const ent of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, ent.name);
    if (ent.isDirectory()) files.push(...walk(p));
    else if (ent.isFile()) files.push(p);
  }
  return files;
}

// Every file this install owns: { harness, target, content, src }.
export function plan(manifest = loadManifest()) {
  const items = [];
  for (const e of manifest.entries) {
    for (const h of e.harness) {
      if (!HARNESSES.includes(h)) throw new Error(`unknown harness ${h} in ${e.src}`);
      const base = manifest.targets[h]?.[e.kind];
      if (!base) throw new Error(`no ${h} target for kind ${e.kind} (${e.src})`);
      const src = path.join(REPO, e.src);
      const stat = fs.statSync(src);
      const pairs = stat.isDirectory()
        ? walk(src).map((f) => [f, path.join(path.basename(src), path.relative(src, f))])
        : [[src, path.basename(src)]];
      for (const [file, rel] of pairs) {
        items.push({ harness: h, src: path.relative(REPO, file), target: path.join(expand(base), rel), content: render(file, h) });
      }
    }
  }
  const seen = new Map();
  for (const it of items) {
    if (seen.has(it.target)) throw new Error(`two sources install to ${it.target}: ${seen.get(it.target)} and ${it.src}`);
    seen.set(it.target, it.src);
  }
  return items;
}

export function loadManifest() {
  return JSON.parse(fs.readFileSync(path.join(REPO, "manifest.json"), "utf8"));
}

function readState() {
  try {
    return JSON.parse(fs.readFileSync(statePath(), "utf8"));
  } catch {
    return { files: [] };
  }
}

function repoSha() {
  try {
    const sha = execFileSync("git", ["-C", REPO, "rev-parse", "--short", "HEAD"], { encoding: "utf8" }).trim();
    const dirty = execFileSync("git", ["-C", REPO, "status", "--porcelain"], { encoding: "utf8" }).trim();
    return dirty ? `${sha}-dirty` : sha;
  } catch {
    return "uncommitted";
  }
}

function readIfExists(p) {
  try {
    return fs.readFileSync(p, "utf8").replace(/\r\n/g, "\n");
  } catch {
    return null;
  }
}

// Compare installed state with the plan. Returns { changes:[{action,target,src}], orphans:[target] }.
export function diff(items = plan()) {
  const changes = [];
  for (const it of items) {
    const cur = readIfExists(it.target);
    if (cur === null) changes.push({ action: "create", ...it });
    else if (cur !== it.content) changes.push({ action: "update", ...it });
  }
  const wanted = new Set(items.map((i) => i.target));
  const orphans = readState().files.filter((f) => !wanted.has(f) && fs.existsSync(f));
  return { changes, orphans };
}

function backup(target, stamp) {
  const rel = path.relative(homeDir(), target).replace(/^(\.\.[\\/])+/, "outside/");
  const dest = path.join(homeDir(), ".config", "orchestrator", "backups", stamp, rel);
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(target, dest);
  return dest;
}

export function install({ dryRun = false, log = console.log } = {}) {
  const items = plan();
  const { changes, orphans } = diff(items);
  const stamp = new Date().toISOString().replace(/[:.]/g, "-");
  for (const c of changes) {
    log(`${dryRun ? "would " : ""}${c.action} ${c.target}  <- ${c.src}`);
    if (dryRun) continue;
    if (c.action === "update") backup(c.target, stamp);
    fs.mkdirSync(path.dirname(c.target), { recursive: true });
    const tmp = c.target + ".orch-tmp";
    fs.writeFileSync(tmp, c.content);
    fs.renameSync(tmp, c.target);
  }
  for (const o of orphans) {
    log(`${dryRun ? "would " : ""}remove orphan ${o}`);
    if (dryRun) continue;
    backup(o, stamp);
    fs.rmSync(o);
  }
  if (!dryRun) {
    fs.mkdirSync(path.dirname(statePath()), { recursive: true });
    const state = { repo: REPO, sha: repoSha(), installed_at: new Date().toISOString(), files: items.map((i) => i.target) };
    fs.writeFileSync(statePath(), JSON.stringify(state, null, 2) + "\n");
  }
  if (!changes.length && !orphans.length) log("up to date — nothing to change");
  // Not a file this install owns: Claude Code's user-scope MCP list. Never fails the install.
  const mcp = process.env.ORCH_SKIP_MCP ? "skipped" : registerPeerMail({ home: homeDir(), dryRun, log });
  return { changes: changes.length, orphans: orphans.length, mcp };
}

export function check({ log = console.log } = {}) {
  const { changes, orphans } = diff();
  for (const c of changes) log(`DRIFT ${c.action === "create" ? "missing" : "differs"}: ${c.target}  (source ${c.src})`);
  for (const o of orphans) log(`DRIFT orphan (installed earlier, no longer in manifest): ${o}`);
  let routingOk = true;
  const checker = path.join(REPO, "bin", "check-routing.mjs");
  if (fs.existsSync(checker) && !process.env.ORCH_SKIP_ROUTING) {
    try {
      execFileSync(process.execPath, [checker], { stdio: "inherit" });
    } catch {
      routingOk = false;
    }
  }
  // A warning, not drift: install cannot always repair it (no `claude` on PATH), and the desk gates every merge on
  // --check, so a failing check here would page on each merge.
  const mcp = process.env.ORCH_SKIP_MCP ? null : peerMailDrift(homeDir());
  if (mcp) log(`WARN MCP peer-mail ${mcp.registered ? "differs from" : "not registered in"} Claude Code user scope (OpenCode runs: ${[mcp.wanted.command, ...mcp.wanted.args].join(" ")}) — run install`);
  const ok = !changes.length && !orphans.length && routingOk;
  log(ok ? "check: OK — installed files match the repo" : "check: FAILED — run install (or fix routing) and re-check");
  return ok;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = new Set(process.argv.slice(2));
  try {
    if (args.has("--check")) process.exit(check() ? 0 : 1);
    install({ dryRun: args.has("--dry-run") });
  } catch (err) {
    console.error(`install: ${err.message}`);
    process.exit(2);
  }
}

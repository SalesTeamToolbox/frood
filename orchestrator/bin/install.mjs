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
import { createHash } from "node:crypto";
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

// ---------------------------------------------------------------------------
// Workstation guard + box-wide suite lock (Linux only).
//
//   agent-priority.mjs  -> <home>/.local/lib/frood-workstation/agent-priority.mjs
//   suite-lock.sh       -> <home>/.local/lib/frood-workstation/suite-lock.sh
//   *.service           -> <home>/.config/systemd/user/frood-agent-priority.service
//
// Never run from a worktree: install copies them to ~/.local/lib/frood-workstation/ and the
// unit is executed from there. ORCH_SYSTEMCTL overrides the systemctl binary (tests).
// ---------------------------------------------------------------------------

export function workstationLibDir() {
  return path.join(homeDir(), ".local", "lib", "frood-workstation");
}

export function workstationUnitDir() {
  return path.join(homeDir(), ".config", "systemd", "user");
}

const WORKSTATION_UNIT = "frood-agent-priority.service";
const WS_AGENT_SRC = path.join(REPO, "ops", "workstation", "agent-priority.mjs");
const WS_LOCK_SRC = path.join(REPO, "ops", "workstation", "suite-lock.sh");
const WS_UNIT_SRC = path.join(REPO, "ops", "workstation", "frood-agent-priority.service");

// A sandbox home is set (ORCH_HOME) but no systemctl binary was requested (ORCH_SYSTEMCTL unset):
// install copies the files there but never calls the real systemctl, which would operate on the
// real user's systemd session instead of the sandbox. With a real run (no ORCH_HOME) behaviour is
// unchanged.
function sandboxHome() {
  return process.env.ORCH_HOME && !process.env.ORCH_SYSTEMCTL;
}

function sha256File(p) {
  return createHash("sha256").update(fs.readFileSync(p)).digest("hex");
}

function wsCopyIfDiffers(src, dest) {
  let cur;
  try {
    cur = sha256File(dest);
  } catch {
    cur = null; // missing -> differs
  }
  const next = sha256File(src);
  if (cur === next) return false;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
  return true;
}

export function installWorkstation({ log = console.log, dryRun = false } = {}) {
  if (process.platform !== "linux") {
    log("workstation: skipped (non-linux)");
    return { skipped: true, reason: "non-linux" };
  }
  if (process.env.ORCH_SKIP_WORKSTATION === "1") {
    log("workstation: skipped (ORCH_SKIP_WORKSTATION=1)");
    return { skipped: true, reason: "ORCH_SKIP_WORKSTATION=1" };
  }
  const libDir = workstationLibDir();
  const unitDir = workstationUnitDir();
  const guardDest = path.join(libDir, "agent-priority.mjs");
  const lockDest = path.join(libDir, "suite-lock.sh");
  const unitDest = path.join(unitDir, WORKSTATION_UNIT);

  let guardChanged = false;
  let lockChanged = false;
  let unitChanged = false;
  if (!dryRun) {
    guardChanged = wsCopyIfDiffers(WS_AGENT_SRC, guardDest);
    lockChanged = wsCopyIfDiffers(WS_LOCK_SRC, lockDest);
    unitChanged = wsCopyIfDiffers(WS_UNIT_SRC, unitDest);
  } else {
    for (const [src, dest] of [
      [WS_AGENT_SRC, guardDest],
      [WS_LOCK_SRC, lockDest],
      [WS_UNIT_SRC, unitDest],
    ]) {
      let cur;
      try {
        cur = sha256File(dest);
      } catch {
        cur = null;
      }
      const next = sha256File(src);
      if (cur !== next) log(`workstation: would copy ${dest}  <- ${path.relative(REPO, src)}`);
    }
    log("workstation: dry run — no files written, systemctl not called");
    return { guardChanged, lockChanged, unitChanged, dryRun: true };
  }

  const sand = sandboxHome();
  if (!sand) {
    const systemctl = process.env.ORCH_SYSTEMCTL || "systemctl";
    try {
      execFileSync(systemctl, ["--user", "daemon-reload"], { timeout: 15000 });
    } catch (err) {
      if (err.code === "ENOENT") {
        log("workstation: systemctl not found, unit not enabled");
        return { skipped: false, systemctlMissing: true };
      }
      throw err;
    }
    execFileSync(systemctl, ["--user", "enable", "--now", WORKSTATION_UNIT], { timeout: 15000 });
    if (guardChanged) {
      execFileSync(systemctl, ["--user", "restart", WORKSTATION_UNIT], { timeout: 15000 });
    }
  } else {
    log("workstation: sandbox home, systemctl not called");
  }
  return { guardChanged, lockChanged, unitChanged };
}

export function checkWorkstation({ log = console.log } = {}) {
  if (process.platform !== "linux" || process.env.ORCH_SKIP_WORKSTATION === "1") {
    return { ok: true, skipped: true };
  }
  let drift = 0;
  const libDir = workstationLibDir();
  const unitDir = workstationUnitDir();
  const guardDest = path.join(libDir, "agent-priority.mjs");
  const lockDest = path.join(libDir, "suite-lock.sh");
  const unitDest = path.join(unitDir, WORKSTATION_UNIT);
  for (const [src, dest] of [
    [WS_AGENT_SRC, guardDest],
    [WS_LOCK_SRC, lockDest],
    [WS_UNIT_SRC, unitDest],
  ]) {
    let cur;
    try {
      cur = sha256File(dest);
    } catch {
      cur = null; // missing -> drift
    }
    const next = sha256File(src);
    if (cur === null) {
      log(`DRIFT missing: ${dest}  (source ${path.relative(REPO, src)})`);
      drift += 1;
    } else if (cur !== next) {
      log(`DRIFT differs: ${dest}  (source ${path.relative(REPO, src)})`);
      drift += 1;
    }
  }
  const systemctl = process.env.ORCH_SYSTEMCTL || "systemctl";
  let active = null;
  // A sandbox home without an explicit ORCH_SYSTEMCTL: do not probe the real user's unit state.
  if (process.env.ORCH_HOME !== undefined && process.env.ORCH_SYSTEMCTL === undefined) {
    return { ok: drift === 0, sandbox: true };
  }
  try {
    active = execFileSync(systemctl, ["--user", "is-active", WORKSTATION_UNIT], {
      encoding: "utf8",
      timeout: 15000,
    }).trim();
  } catch (err) {
    if (err.code === "ENOENT") {
      log("WARN workstation: systemctl not found, cannot verify unit state");
      return { ok: drift === 0, warn: true };
    }
    // is-active exited non-zero -> not active
    active = "";
  }
  if (active !== "active") {
    log(`DRIFT: ${WORKSTATION_UNIT} is not active (is-active: ${active || "<none>"})`);
    drift += 1;
  }
  return { ok: drift === 0, drift };
}

export function uninstallWorkstation({ log = console.log } = {}) {
  if (process.platform !== "linux") {
    log("workstation: skipped (non-linux)");
    return;
  }
  if (process.env.ORCH_SKIP_WORKSTATION === "1") {
    log("workstation: skipped (ORCH_SKIP_WORKSTATION=1)");
    return;
  }
  const sand = sandboxHome();
  if (!sand) {
    const systemctl = process.env.ORCH_SYSTEMCTL || "systemctl";
    try {
      execFileSync(systemctl, ["--user", "disable", "--now", WORKSTATION_UNIT], { timeout: 15000 });
    } catch {
      // best effort: the unit may not be enabled
    }
    try {
      execFileSync(systemctl, ["--user", "daemon-reload"], { timeout: 15000 });
    } catch {
      // best effort
    }
  }
  const unitDir = workstationUnitDir();
  const unitDest = path.join(unitDir, WORKSTATION_UNIT);
  const libDir = workstationLibDir();
  const guardDest = path.join(libDir, "agent-priority.mjs");
  const lockDest = path.join(libDir, "suite-lock.sh");
  for (const f of [unitDest, guardDest, lockDest]) {
    try {
      fs.rmSync(f);
    } catch {
      // already gone
    }
  }
  log("workstation: uninstalled");
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = new Set(process.argv.slice(2));
  try {
    if (args.has("--uninstall-workstation")) {
      uninstallWorkstation();
      process.exit(0);
    }
    if (args.has("--check")) {
      const mainOk = check();
      const wsOk = checkWorkstation().ok;
      const ok = mainOk && wsOk;
      process.exit(ok ? 0 : 1);
    }
    install({ dryRun: args.has("--dry-run") });
    installWorkstation({ dryRun: args.has("--dry-run") });
  } catch (err) {
    console.error(`install: ${err.message}`);
    process.exit(2);
  }
}

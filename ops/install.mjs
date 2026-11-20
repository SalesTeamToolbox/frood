#!/usr/bin/env node
// Frood-vendored orchestrator installer (sanitized copy of the orchestrator's bin/install.mjs).
//
//   node ops/install.mjs        verify the vendored orchestrator tooling is in place (exit 0)
//   node ops/install.mjs --check  same verification, exit 1 if anything is missing
//
// All targets are repo-local: the vendored tooling lives under .claude/, bin/ and ops/
// in this repository. No ~/. or C:/Users-style machine path is written or tracked here,
// and no manifest.json is vendored, so there is nothing to install out of the repo.
// The optional user-global install (to ~/.claude / ~/.config/opencode) is documented in
// the orchestrator repo but is intentionally not performed by this vendored copy.
//
// oc-worker.mjs imports { diff, homeDir } from this module so it can run from bin/.
//
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const REPO = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const MANAGED = `<!-- managed by the orchestrator repo (${REPO}). Edit it there, then run install. Local edits are overwritten. -->`;

export function homeDir() {
  return process.env.ORCH_HOME || os.homedir();
}

// M3 file manifest: the orchestrator tooling vendored into Frood as clean copies.
// Every entry is a path relative to the repo root that must exist after import.
export const VENDORED = [
  ".claude/commands/orchestrator.md",
  ".claude/commands/gauntlet.md",
  "bin/board.mjs",
  "bin/oc-worker.mjs",
  "bin/desk.mjs",
  "bin/router-health.mjs",
  "bin/verdict-gate.mjs",
  "bin/handoff.mjs",
  "bin/session-title.mjs",
  "bin/check-routing.mjs",
  "bin/no-window.mjs",
  "bin/pool-health.mjs",
  "bin/usage.mjs",
  "bin/proc-tree.mjs",
  "bin/outcome.mjs",
  ".claude/agents/worker.md",
  ".claude/agents/critic.md",
  ".claude/agents/senior.md",
  ".claude/rules/01-orchestrator-models.md",
  "ops/install.mjs",
];

// Nothing is installed to ~/. in this vendored copy: the files are committed to the
// repo directly. With no manifest.json vendored, there is nothing to diff against,
// so diff() reports a clean tree when every vendored file is present.
export function loadManifest() {
  return { entries: [], targets: {} };
}
export function plan(manifest = loadManifest()) {
  return [];
}
export function diff() {
  const missing = VENDORED.filter((rel) => !fs.existsSync(path.join(REPO, rel)));
  const changes = missing.map((rel) => ({ action: "create", target: path.join(REPO, rel), src: rel }));
  return { changes, orphans: [] };
}
export function install({ dryRun = false, log = console.log } = {}) {
  const { changes } = diff();
  for (const c of changes) log(`${dryRun ? "would " : ""}${c.action} ${c.target}`);
  if (!changes.length) log("orchestrator tooling vendored in-repo — nothing to install");
  else log(`orchestrator tooling: ${changes.length} vendored file(s) missing`);
  return { changes: changes.length, orphans: 0 };
}
export function check({ log = console.log } = {}) {
  const { changes } = diff();
  for (const c of changes) log(`DRIFT missing: ${c.target}  (vendored source ${c.src})`);
  const ok = !changes.length;
  log(ok ? "check: OK — vendored orchestrator tooling in place" : "check: FAILED — run ops/install.mjs");
  return ok;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = new Set(process.argv.slice(2));
  try {
    if (args.has("--check")) process.exit(check() ? 0 : 1);
    install();
  } catch (err) {
    console.error(`install: ${err.message}`);
    process.exit(2);
  }
}

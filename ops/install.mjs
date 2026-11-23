#!/usr/bin/env node
// Frood-vendored orchestrator installer (sanitized copy of the orchestrator's bin/install.mjs).
//
//   node ops/install.mjs        verify the vendored orchestrator tooling + Frood commands is in place (exit 0)
//   node ops/install.mjs --check  same verification, exit 1 if anything is missing
//   node ops/install.mjs --global          install /frood-* commands to ~/.claude/commands
//   node ops/install.mjs --global --check  exit 1 if those global copies drifted
//
// All targets are repo-local: the vendored tooling lives under .claude/, bin/ and ops/
// in this repository. No ~/. or C:/Users-style machine path is written or tracked here,
// and no manifest.json is vendored, so there is nothing to install out of the repo.
// `--global` installs the /frood-* slash commands user-wide (~/.claude/commands) so they
// show in every repo, rendering {{ORCH_REPO}} to this checkout and pointing relative
// bin/ ops/ scripts/ paths at it. `--global --check` reports drift for those copies.
//
// oc-worker.mjs imports { diff, homeDir } from this module so it can run from bin/.
//
// Installs: orchestrator tooling (board.mjs, oc-worker.mjs, desk.mjs, etc.) plus the repo-local
// Frood feature commands (frood-board, frood-train, frood-egm, …). The global lifecycle commands
// (`/frood-orchestrator`, `/frood-gauntlet`, `/frood-desk`, …) come from `orchestrator/` via its
// own installer (`node orchestrator/bin/install.mjs`) — they are not copied into this repo.
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
  ".claude/commands/frood-board.md",
  ".claude/commands/frood-train.md",
  ".claude/commands/frood-peer-mail.md",
  ".claude/commands/frood-egm.md",
  ".claude/commands/frood-deploy.md",
  ".claude/commands/frood-setup.md",
  ".claude/commands/frood-health.md",
  ".claude/commands/frood-cc.md",
  "bin/frood.js",
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
  "bin/frood-learn.mjs",
  "bin/frood-learn",
  "orchestrator/commands/frood-learn.md",
  "orchestrator/agents/worker.md",
  "orchestrator/agents/critic.md",
  "orchestrator/agents/senior.md",
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

// ---- user-global /frood-* commands -------------------------------------------------
export const GLOBAL_MARK = `<!-- installed by frood ops/install.mjs --global from ${REPO}. Edit it there, then re-run. Local edits are overwritten. -->`;
const CMD_DIR = path.join(REPO, ".claude", "commands");
export function globalCommandsDir() {
  return path.join(homeDir(), ".claude", "commands");
}
export function renderGlobal(text) {
  const body = text.replaceAll("{{ORCH_REPO}}", REPO);
  const note = `${GLOBAL_MARK}\n> Frood repo root: \`${REPO}\` — run any relative \`bin/\`, \`ops/\`, \`orchestrator/\` or \`scripts/\` path from there.\n\n`;
  const m = body.match(/^---\n[\s\S]*?\n---\n/);
  return m ? m[0] + note + body.slice(m[0].length) : note + body;
}
export function globalPlan() {
  const dest = globalCommandsDir();
  return fs.readdirSync(CMD_DIR)
    .filter((f) => /^frood-.*\.md$/.test(f))
    .sort()
    .map((f) => {
      const target = path.join(dest, f);
      const want = renderGlobal(fs.readFileSync(path.join(CMD_DIR, f), "utf8"));
      const have = fs.existsSync(target) ? fs.readFileSync(target, "utf8") : null;
      return { f, target, want, state: have === null ? "missing" : have === want ? "ok" : "differs" };
    });
}
export function installGlobal({ log = console.log } = {}) {
  fs.mkdirSync(globalCommandsDir(), { recursive: true });
  let n = 0;
  for (const p of globalPlan()) {
    if (p.state === "ok") continue;
    fs.writeFileSync(p.target, p.want);
    log(`${p.state === "missing" ? "create" : "update"} ${p.target}`);
    n++;
  }
  log(n ? `global: ${n} /frood-* command(s) written` : "global: /frood-* commands up to date");
  return n;
}
export function checkGlobal({ log = console.log } = {}) {
  const bad = globalPlan().filter((p) => p.state !== "ok");
  for (const p of bad) log(`DRIFT ${p.state}: ${p.target}`);
  log(bad.length ? "global check: FAILED — run ops/install.mjs --global" : "global check: OK");
  return !bad.length;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  const args = new Set(process.argv.slice(2));
  try {
    if (args.has("--global")) {
      if (args.has("--check")) process.exit(checkGlobal() ? 0 : 1);
      installGlobal();
      process.exit(0);
    }
    if (args.has("--check")) process.exit(check() ? 0 : 1);
    install();
  } catch (err) {
    console.error(`install: ${err.message}`);
    process.exit(2);
  }
}

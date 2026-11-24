#!/usr/bin/env node
// Installs (or refreshes) the orchestrator systemd user units:
//   - orchestrator-desk-check.timer: runs bin/desk-check.mjs every 5 minutes; it only
//     pages (notify-send + stdout in the journal) when streams have unhandled events
//     and no live watcher drives.
//   - orchestrator-desk-daemon.service: supervises `desk.mjs daemon _run` (the headless
//     desk driver). Restart=always + RestartSec=120: a fenced or crashed daemon is back
//     within ~2 minutes and re-takes an abandoned lock; SIGTERM (systemctl stop) exits
//     cleanly with the lock released.
// Usage: ops/systemd/install.mjs [--by cc|oc] [--uninstall]
// When the service is enabled, stop/start it with systemctl, not `desk.mjs daemon stop`
// (the supervisor restarts a SIGTERMed daemon). The service owns the desk whenever no
// interactive /frood-desk holds the lock; an interactive watch with --takeover fences it and
// the service yields until that session ends.
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launchConfigPath, writeLaunchConfig, detectDefaultMode } from "../../bin/launch-config.mjs";

const dir = path.join(path.dirname(fileURLToPath(import.meta.url)));
const unitDir = path.join(os.homedir(), ".config", "systemd", "user");
const timerName = "orchestrator-desk-check";
const daemonName = "orchestrator-desk-daemon";

const run = (cmd, args) => execFileSync(cmd, args, { stdio: "inherit" });
const systemctl = (...args) => run("systemctl", ["--user", ...args]);

let by = "oc";
for (let i = 2; i < process.argv.length; i++) {
  if (process.argv[i] === "--by") by = process.argv[++i] ?? "";
}
if (!["cc", "oc"].includes(by)) {
  console.error("install: --by must be cc or oc");
  process.exit(2);
}

if (process.argv.includes("--uninstall")) {
  systemctl("disable", "--now", `${timerName}.timer`);
  systemctl("disable", "--now", `${daemonName}.service`);
  for (const unit of [`${timerName}.service`, `${timerName}.timer`, `${daemonName}.service`]) {
    try {
      fs.rmSync(path.join(unitDir, unit));
    } catch {}
  }
  run("systemctl", ["--user", "daemon-reload"]);
  console.log(`desk-check timer and desk daemon uninstalled`);
  process.exit(0);
}

const repo = path.resolve(dir, "..", "..");
// First-time setup: how the orphan notice opens a session (desktop app / terminal / custom). Never overwrites.
if (!fs.existsSync(launchConfigPath())) {
  const launchCli = path.join(repo, "bin", "launch-config.mjs");
  if (process.stdin.isTTY && process.stdout.isTTY) execFileSync(process.execPath, [launchCli, "--ask"], { stdio: "inherit" });
  else {
    const mode = detectDefaultMode();
    writeLaunchConfig({ mode });
    console.log(`launch mode: ${mode} (detected; not interactive)`);
  }
  console.log(`Change it with: node ${launchCli} --set desktop|terminal|custom [--cmd "<template>"]`);
}
// Test hook: stop before touching systemd.
if (process.env.ORCH_INSTALL_NO_SYSTEMD === "1") process.exit(0);
let node;
try {
  node = execFileSync("command -v node", { shell: true, encoding: "utf8" }).trim();
} catch {
  console.error("install: node not found on PATH");
  process.exit(2);
}
if (!node || !fs.existsSync(path.join(repo, "bin", "desk-check.mjs"))) {
  console.error(`install: cannot resolve node or ${repo}/bin/desk-check.mjs`);
  process.exit(2);
}
function renderTemplate(file, extra = {}) {
  let text = fs.readFileSync(path.join(dir, file), "utf8");
  const subs = { "@NODE@": node, "@REPO@": repo, "@BY@": by, ...extra };
  for (const [k, v] of Object.entries(subs)) text = text.replaceAll(k, v);
  return text;
}
function checkPlaceholders(text, file) {
  for (const p of ["@NODE@", "@REPO@", "@BY@"]) {
    if (text.includes(p)) {
      console.error(`install: template placeholder ${p} left unsubstituted in ${file}`);
      process.exit(2);
    }
  }
}
fs.mkdirSync(unitDir, { recursive: true });
// Timer (oneshot service + timer).
const checkService = renderTemplate(`${timerName}.service`);
checkPlaceholders(checkService, `${timerName}.service`);
fs.writeFileSync(path.join(unitDir, `${timerName}.service`), checkService);
fs.copyFileSync(path.join(dir, `${timerName}.timer`), path.join(unitDir, `${timerName}.timer`));
// Daemon (supervised driver).
const daemonService = renderTemplate(`${daemonName}.service`);
checkPlaceholders(daemonService, `${daemonName}.service`);
fs.writeFileSync(path.join(unitDir, `${daemonName}.service`), daemonService);
systemctl("daemon-reload");
systemctl("enable", "--now", `${timerName}.timer`);
systemctl("enable", "--now", `${daemonName}.service`);
systemctl("status", `${timerName}.timer`, "--no-pager");
systemctl("status", `${daemonName}.service`, "--no-pager");

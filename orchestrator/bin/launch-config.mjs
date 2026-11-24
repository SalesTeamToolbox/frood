#!/usr/bin/env node
// How the orphan notice's "Resolve in new session" action opens a session.
//   node launch-config.mjs                       print the effective mode and where it came from
//   node launch-config.mjs --set desktop|terminal|custom [--cmd "<template>"]
//   node launch-config.mjs --ask                 choose interactively (default = detected); on a non-TTY writes the
//                                                detected mode and says so. Never overwrites an existing file.
// Config: <ORCH_HOME || ~>/.config/orchestrator/launch.json  { "mode": "desktop"|"terminal"|"custom", "cmd"?: "<tpl>" }
// Precedence (orphan-notice.mjs launchPlan): ORCH_LAUNCH_CMD env (= custom) > launch.json > detected at click time.
// Detected = desktop when `xdg-mime query default x-scheme-handler/claude` names a handler (Claude desktop), else terminal.
import fs from "node:fs";
import path from "node:path";
import readline from "node:readline";
import { spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { orchRoot } from "./handoff.mjs";

export const MODES = ["desktop", "terminal", "custom"];

export function launchConfigPath() {
  return path.join(orchRoot(), ".config", "orchestrator", "launch.json");
}

/** The parsed, validated config or null (missing, unreadable, bad mode). Never throws. */
export function readLaunchConfig() {
  try {
    const c = JSON.parse(fs.readFileSync(launchConfigPath(), "utf8"));
    if (!c || !MODES.includes(c.mode)) return null;
    const out = { mode: c.mode };
    if (typeof c.cmd === "string" && c.cmd.trim()) out.cmd = c.cmd.trim();
    return out;
  } catch {
    return null;
  }
}

export function writeLaunchConfig(cfg) {
  if (!cfg || !MODES.includes(cfg.mode)) throw new Error(`mode must be one of ${MODES.join(", ")}`);
  const out = { mode: cfg.mode };
  if (cfg.cmd && String(cfg.cmd).trim()) out.cmd = String(cfg.cmd).trim();
  const p = launchConfigPath();
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, JSON.stringify(out, null, 2) + "\n");
  return out;
}

/** "desktop" when a handler is registered for claude:// URLs, else "terminal". Never throws. `query` is injectable. */
export function detectDefaultMode(query = defaultQuery) {
  try {
    return String(query() ?? "").trim() ? "desktop" : "terminal";
  } catch {
    return "terminal";
  }
}
function defaultQuery() {
  const r = spawnSync("xdg-mime", ["query", "default", "x-scheme-handler/claude"], { encoding: "utf8", timeout: 5000 });
  return r.status === 0 ? r.stdout : "";
}

/** { mode, cmd?, source: "env" | "config" | "detected" } */
export function effectiveLaunch(query) {
  const env = (process.env.ORCH_LAUNCH_CMD ?? "").trim();
  if (env) return { mode: "custom", cmd: env, source: "env" };
  const c = readLaunchConfig();
  if (c) return { ...c, source: "config" };
  return { mode: detectDefaultMode(query), source: "detected" };
}

const HOW = (self) => `change it with: node ${self} --set desktop|terminal|custom [--cmd "<template>"]`;

/** Map a typed answer ("2", "desktop", "", junk, out of range) to a mode; anything unusable is the detected default. */
export function parseChoice(answer, detected) {
  const a = String(answer ?? "").trim().toLowerCase();
  if (MODES.includes(a)) return a;
  return /^\d+$/.test(a) && MODES[Number(a) - 1] ? MODES[Number(a) - 1] : detected;
}

/** The config to write for a chosen mode; custom with no command falls back to the detected mode. */
export function choiceConfig(mode, cmd, detected) {
  const c = String(cmd ?? "").trim();
  return mode === "custom" ? (c ? { mode, cmd: c } : { mode: detected }) : { mode };
}

async function ask(detected) {
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  // EOF (Ctrl-D) closes the interface: every pending and later question resolves "" so the default is taken.
  const closed = new Promise((r) => rl.once("close", () => r("")));
  const q = (t) => Promise.race([new Promise((r) => rl.question(t, r)), closed]);
  console.log("How should 'Resolve in new session' open a session?");
  MODES.forEach((m, i) => console.log(`  ${i + 1}) ${m}${m === detected ? "  (default)" : ""}`));
  console.log("     desktop = Claude desktop app, terminal = xdg-terminal-exec, custom = your own command");
  const mode = parseChoice(await q(`Choice [${MODES.indexOf(detected) + 1}]: `), detected);
  const cmd = mode === "custom" ? await q("Command template ({stream}, {harness}; run via sh -c): ") : "";
  rl.close();
  return choiceConfig(mode, cmd, detected);
}

export async function cli(argv) {
  const self = fileURLToPath(import.meta.url);
  const i = argv.indexOf("--set");
  if (i >= 0) {
    const mode = argv[i + 1];
    const j = argv.indexOf("--cmd");
    const cmd = j >= 0 ? argv[j + 1] : undefined;
    if (!MODES.includes(mode)) return console.error(`launch-config: --set needs one of ${MODES.join(", ")}`), 2;
    if (mode === "custom" && !(cmd ?? "").trim()) return console.error('launch-config: --set custom needs --cmd "<template>"'), 2;
    writeLaunchConfig({ mode, cmd: mode === "custom" ? cmd : undefined });
    console.log(`launch mode set to ${mode} (${launchConfigPath()})`);
    return 0;
  }
  if (argv.includes("--ask")) {
    if (fs.existsSync(launchConfigPath())) {
      console.log(`launch config already exists (${launchConfigPath()}); not changing it. ${HOW(self)}`);
      return 0;
    }
    const detected = detectDefaultMode();
    if (!process.stdin.isTTY || !process.stdout.isTTY) {
      writeLaunchConfig({ mode: detected });
      console.log(`not interactive: saved the detected launch mode "${detected}" to ${launchConfigPath()}; it is now fixed and will not be re-detected. ${HOW(self)}`);
      return 0;
    }
    const chosen = writeLaunchConfig(await ask(detected));
    console.log(`launch mode: ${chosen.mode}; ${HOW(self)}`);
    return 0;
  }
  const e = effectiveLaunch();
  console.log(`launch mode: ${e.mode} (source: ${e.source})${e.cmd ? `\ncmd: ${e.cmd}` : ""}\n${HOW(self)}`);
  return 0;
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  process.exitCode = await cli(process.argv.slice(2));
}

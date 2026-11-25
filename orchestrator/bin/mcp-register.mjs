// Registers MCP servers that every orchestrator session needs with Claude Code, at user scope.
//
// Today that is only `peer-mail`. Each Claude Code session gets a peer-mail id at start
// (hooks/peer-mail-session-id.js), and the desk daemon reaches it by mail, so the session needs the peer_* tools in
// every repo. A project `.mcp.json` would not reach them all.
//
// Source of truth: the `peer-mail` entry in OpenCode's config (`~/.config/opencode/opencode.json`, `mcp`), which the
// owner already maintains. This module does not invent a path: no OpenCode entry means nothing to register.
// Registration goes through `claude mcp add -s user`, never by editing `~/.claude.json` directly, because Claude Code
// rewrites that file while it runs.
import fs from "node:fs";
import path from "node:path";
import { execFileSync } from "node:child_process";

export const SERVER = "peer-mail";

// The peer-mail command OpenCode runs: { command, args } or null when OpenCode has no enabled local entry.
export function wantedPeerMail(home) {
  try {
    const cfg = JSON.parse(fs.readFileSync(path.join(home, ".config", "opencode", "opencode.json"), "utf8"));
    // OpenCode's documented shape is `mcp.<name>`; this owner's config nests them as `mcp.servers.<name>`.
    const e = cfg?.mcp?.[SERVER] ?? cfg?.mcp?.servers?.[SERVER];
    if (!e || e.disabled || e.type !== "local" || !Array.isArray(e.command) || !e.command.length) return null;
    const [command, ...args] = e.command;
    if (typeof command !== "string" || !args.every((a) => typeof a === "string")) return null;
    return { command, args };
  } catch {
    return null;
  }
}

// The user-scope peer-mail entry Claude Code has now: { command, args } or null.
export function registeredPeerMail(home) {
  try {
    const e = JSON.parse(fs.readFileSync(path.join(home, ".claude.json"), "utf8"))?.mcpServers?.[SERVER];
    if (!e || typeof e.command !== "string") return null;
    return { command: e.command, args: Array.isArray(e.args) ? e.args : [] };
  } catch {
    return null;
  }
}

const same = (a, b) => a.command === b.command && JSON.stringify(a.args) === JSON.stringify(b.args);

// Claude Code lives on this machine: its user config file `~/.claude.json` exists. Only Claude Code writes that file;
// `~/.claude/` proves nothing, because this installer itself creates `~/.claude/commands/`. An OpenCode-only machine is
// not drift, it is out of scope.
export function claudeCodePresent(home) {
  return fs.existsSync(path.join(home, ".claude.json"));
}

// null when nothing to do, else { wanted, registered } (registered may be null).
export function peerMailDrift(home) {
  if (!claudeCodePresent(home)) return null;
  const wanted = wantedPeerMail(home);
  if (!wanted) return null;
  const registered = registeredPeerMail(home);
  return registered && same(wanted, registered) ? null : { wanted, registered };
}

// The CLI writes `<HOME>/.claude.json`, so HOME is the install home: under ORCH_HOME (tests) it never touches the
// real config. The timeout keeps a stuck CLI from stalling the desk daemon's post-merge install.
const runClaude = (args, home) =>
  execFileSync("claude", args, { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"], timeout: 60_000, env: { ...process.env, HOME: home, USERPROFILE: home } });

// Install step. Never throws: a machine without the `claude` CLI, or a failing CLI, gets a warning line and the
// file install carries on. Returns "ok" | "registered" | "skipped" | "failed".
export function registerPeerMail({ home, dryRun = false, log = console.log, run = runClaude } = {}) {
  const d = peerMailDrift(home);
  if (!d) return "ok";
  const cmd = [d.wanted.command, ...d.wanted.args].join(" ");
  if (dryRun) {
    log(`would register MCP ${SERVER} for Claude Code (user scope): ${cmd}`);
    return "skipped";
  }
  let removed = false;
  try {
    if (d.registered) {
      run(["mcp", "remove", "-s", "user", SERVER], home);
      removed = true;
    }
    run(["mcp", "add", "-s", "user", SERVER, "--", d.wanted.command, ...d.wanted.args], home);
    log(`registered MCP ${SERVER} for Claude Code (user scope): ${cmd}`);
    return "registered";
  } catch (err) {
    const gone = removed ? " (the old entry was already removed)" : "";
    log(`warning: could not register MCP ${SERVER} with Claude Code${gone} (${String(err.message).split("\n")[0]}); run: claude mcp add -s user ${SERVER} -- ${cmd}`);
    return "failed";
  }
}

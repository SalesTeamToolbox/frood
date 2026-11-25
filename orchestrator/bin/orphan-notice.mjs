#!/usr/bin/env node
// Desktop notice for an orphaned stream, with a "Resolve in new session" action.
//   node orphan-notice.mjs <stream>
// Launched detached by the desk daemon (desk.mjs orphanPage): `notify-send --wait` blocks THIS process until the
// notice is clicked or dismissed, never the daemon. If the action is chosen, opens a terminal running a fresh
// orchestrator session on the stream (`/frood-next <stream>`). How it opens is `launch.json` (see launch-config.mjs,
// chosen at setup, changed with `--set`): desktop = the Claude desktop app via
//   xdg-open "claude://code/new?q=/frood-next <stream>&folder=<repo>"      (held by cc, or unheld)
// terminal = xdg-terminal-exec -- claude "/frood-next <stream>" (cwd = the stream's repo), or for an OpenCode holder
// (no desktop app) always xdg-terminal-exec -- opencode --prompt "/frood-next <stream>".
// With no launch.json the mode is detected at click time: desktop if a claude:// handler is registered, else terminal.
//   ORCH_LAUNCH_CMD   overrides everything (= custom): template run via `sh -c`, `{stream}` and `{harness}` (cc | oc)
//                     substituted, plus `{session}` (the holder session id; empty when there is no holder).
//   ORCH_NO_NOTIFY=1  do nothing. Never throws, always exits 0.
import "./no-window.mjs";
import fs from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { readStream } from "./handoff.mjs";
import { openEscalations, holderSession } from "./orphan.mjs";
import { effectiveLaunch } from "./launch-config.mjs";

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;
const ID_PREFIX = 8;

const idPrefix = (id) => String(id).slice(0, ID_PREFIX);
// Format an idle duration (ms) as Nh or Nm.
const fmtIdle = (ms) => {
  if (ms === null || ms === undefined) return "?";
  const h = Math.max(0, Math.floor(ms / 3600_000));
  if (h > 0) return `${h}h`;
  return `${Math.max(0, Math.floor(ms / 60_000))}m`;
};

export function noticeText(stream, escalations, holder) {
  const reasons = escalations.slice(0, 2).map((e) => String(e.reason).split(/\r?\n/)[0].slice(0, 110)).join("; ");
  const more = escalations.length > 2 ? `; +${escalations.length - 2} more` : "";
  const head = holder
    ? `${stream}: ${escalations.length} escalation(s) waiting on you — session "${holder.title || idPrefix(holder.id)}" idle ${fmtIdle(holder.idleMs)}`
    : `${stream}: ${escalations.length} escalation(s), no live session`;
  return `${head} — ${reasons || "see desk status"}${more}`;
}

/** The argv-or-shell launch plan for a stream: { cwd, shell?, argv? }. Precedence: ORCH_LAUNCH_CMD > launch.json > detected.
 *  When `holder` is given (the holder session still exists) terminal mode resumes it (`claude --resume <id>` /
 *  `opencode --session <id>`) instead of opening a fresh session, and desktop mode opens the app without a new session.
 *  `ORCH_LAUNCH_CMD` additionally substitutes `{session}` (empty when there is no holder). */
export function launchPlan(stream, s, holder) {
  const harness = s?.held_by === "oc" ? "oc" : "cc";
  const repo = s?.repo && fs.existsSync(s.repo) ? s.repo : "";
  const cwd = repo || process.cwd();
  const eff = effectiveLaunch();
  const session = holder ? holder.id : "";
  if (eff.mode === "custom" && eff.cmd) return { cwd, shell: eff.cmd.replaceAll("{stream}", stream).replaceAll("{harness}", harness).replaceAll("{session}", session) };
  const prompt = `/frood-next ${stream}`;
  // (mode custom with no cmd, e.g. a hand-edited launch.json, falls through to the terminal default below.)
  // OpenCode has no desktop app: an oc-held stream always opens the terminal.
  if (eff.mode === "desktop" && harness === "cc") {
    const url = `claude://code/new?q=${encodeURIComponent(prompt)}` + (repo ? `&folder=${encodeURIComponent(repo)}` : "");
    return { cwd, argv: ["xdg-open", url] };
  }
  // Resume the holder session instead of starting a new one.
  if (holder && harness === "cc") return { cwd, argv: ["xdg-terminal-exec", "--", "claude", "--resume", holder.id] };
  if (holder && harness === "oc") return { cwd, argv: ["xdg-terminal-exec", "--", "opencode", "--session", holder.id] };
  return { cwd, argv: ["xdg-terminal-exec", "--", ...(harness === "oc" ? ["opencode", "--prompt", prompt] : ["claude", prompt])] };
}

export function launch(plan) {
  const opts = { cwd: plan.cwd, detached: true, stdio: "ignore" };
  const child = plan.shell ? spawn("sh", ["-c", plan.shell], opts) : spawn(plan.argv[0], plan.argv.slice(1), opts);
  child.on("error", () => {});
  child.unref();
}

export function main(stream) {
  try {
    if (process.env.ORCH_NO_NOTIFY === "1" || !NAME_RE.test(String(stream))) return;
    const s = readStream(stream);
    const holder = holderSession(stream);
    const text = noticeText(stream, openEscalations(stream), holder);
    const action = holder ? "Open session" : "Resolve in new session";
    const r = spawnSync("notify-send", ["-u", "critical", "-A", `resolve=${action}`, "--wait", "orchestrator desk", text], { encoding: "utf8" });
    if (String(r.stdout ?? "").trim() === "resolve") launch(launchPlan(stream, s, holder));
  } catch {}
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv[2]);
  process.exitCode = 0;
  // launch() leaves a detached, unref'd child; nothing keeps the loop alive.
}

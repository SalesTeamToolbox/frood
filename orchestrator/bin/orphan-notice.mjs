#!/usr/bin/env node
// Desktop notice for an orphaned stream, with a "Resolve in new session" action.
//   node orphan-notice.mjs <stream>
// Launched detached by the desk daemon (desk.mjs orphanPage): `notify-send --wait` blocks THIS process until the
// notice is clicked or dismissed, never the daemon. If the action is chosen, opens a terminal running a fresh
// orchestrator session on the stream (`/frood-next <stream>`), cwd = the stream's repo.
//   ORCH_LAUNCH_CMD   template run via `sh -c`, `{stream}` and `{harness}` (cc | oc) substituted. Default:
//                     xdg-terminal-exec -- claude "/frood-next {stream}"      (held by cc, or unheld)
//                     xdg-terminal-exec -- opencode --prompt "/frood-next {stream}"   (held by oc)
//   ORCH_NO_NOTIFY=1  do nothing. Never throws, always exits 0.
import "./no-window.mjs";
import fs from "node:fs";
import { spawn, spawnSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { readStream } from "./handoff.mjs";
import { openEscalations } from "./orphan.mjs";

const NAME_RE = /^[a-z0-9][a-z0-9-]{0,39}$/;

export function noticeText(stream, escalations) {
  const reasons = escalations.slice(0, 2).map((e) => String(e.reason).split(/\r?\n/)[0].slice(0, 110)).join("; ");
  const more = escalations.length > 2 ? `; +${escalations.length - 2} more` : "";
  return `${stream}: ${escalations.length} escalation(s), no live session — ${reasons || "see desk status"}${more}`;
}

/** The argv-or-shell launch plan for a stream: { cwd, shell?, argv? }. */
export function launchPlan(stream, s) {
  const harness = s?.held_by === "oc" ? "oc" : "cc";
  const cwd = s?.repo && fs.existsSync(s.repo) ? s.repo : process.cwd();
  const tpl = (process.env.ORCH_LAUNCH_CMD ?? "").trim();
  if (tpl) return { cwd, shell: tpl.replaceAll("{stream}", stream).replaceAll("{harness}", harness) };
  const prompt = `/frood-next ${stream}`;
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
    const text = noticeText(stream, openEscalations(stream));
    const r = spawnSync("notify-send", ["-u", "critical", "-A", "resolve=Resolve in new session", "--wait", "orchestrator desk", text], { encoding: "utf8" });
    if (String(r.stdout ?? "").trim() === "resolve") launch(launchPlan(stream, s));
  } catch {}
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv[2]);
  process.exitCode = 0;
  // launch() leaves a detached, unref'd child; nothing keeps the loop alive.
}

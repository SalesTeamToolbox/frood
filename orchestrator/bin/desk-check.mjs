#!/usr/bin/env node
// Unattended desk trigger (runs lockless from a systemd user timer): page the owner when work
// is pending and nobody is driving it.
//
//   node desk-check.mjs
//
// Exit: 0 nothing pending, or a live watcher is already driving; 1 paged (pending work with no
//   live owner); 2 usage or IO failure. Paging = stdout page text + `notify-send` (best effort;
//   skipped when ORCH_NO_NOTIFY=1, which tests set). The trigger never takes the lock and never
//   decides anything: opening a /desk (or starting the daemon) is the human's job.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { listStreams, readAckLines } from "./handoff.mjs";
import { statusRows, watchInfo } from "./desk.mjs";
import { readService, syncAllStreamTitles } from "./session-title.mjs";

function notify(text) {
  if (process.env.ORCH_NO_NOTIFY === "1") return;
  try {
    // Critical: mako keeps these until dismissed — a one-shot page must not scroll away unseen.
    execFileSync("notify-send", ["-u", "critical", "orchestrator desk", text], { stdio: "ignore", windowsHide: true });
  } catch {
    // paging is best effort: a missing notifier must not fail the check
  }
}

export function check(now = Date.now()) {
  const rows = statusRows(now);
  const pending = rows.filter((s) => s.unhandled > 0);
  const escalations = [];
  for (const s of rows) {
    let lines = [];
    try {
      lines = readAckLines(s.name);
    } catch {}
    for (const l of lines) if (!l.resolved && (l.action ?? "").startsWith("ESCALATE")) escalations.push({ stream: s.name, key: l.key, action: l.action });
  }
  if (!pending.length && !escalations.length) return { code: 0 };
  const watch = watchInfo(now);
  if (watch.state === "live") return { code: 0 };
  const parts = [];
  if (pending.length) parts.push(`${pending.reduce((n, s) => n + s.unhandled, 0)} unhandled event(s) on ${pending.map((s) => `${s.name}(${s.unhandled})`).join(", ")}`);
  if (escalations.length) parts.push(`${escalations.length} unresolved escalation(s) on ${[...new Set(escalations.map((e) => e.stream))].join(", ")}`);
  const owner = watch.state === "none" ? "no watcher" : `stale watcher (pid ${watch.pid}, ${watch.reason})`;
  const text = `desk-check: ${parts.join(" + ")}; ${owner} — open a /desk`;
  return { code: 1, text };
}

export async function main(argv) {
  if (argv.length) {
    console.error("usage: desk-check.mjs (no flags)");
    return 2;
  }
  try {
    // Cosmetic, never decisive: tab titles follow their streams so a glance at the
    // tabs says what each session is doing. Best effort with a hard cap — a slow or
    // missing server must not delay the check, and failures change nothing.
    try {
      const { svc } = readService();
      if (svc) {
        await Promise.race([
          syncAllStreamTitles(svc, () => listStreams()),
          new Promise((res) => setTimeout(res, 8000)),
        ]);
      }
    } catch {}
    const r = check();
    if (r.code === 1) {
      console.log(r.text);
      notify(r.text);
    }
    return r.code;
  } catch (e) {
    console.error(`desk-check: ${e.message}`);
    return 2;
  }
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
  main(process.argv.slice(2)).then(
    (code) => process.exit(code),
    (e) => {
      console.error(`desk-check: ${e.message}`);
      process.exit(2);
    },
  );
}

#!/usr/bin/env node
// Unattended desk trigger (runs lockless from a systemd user timer): page the owner when events
// are unhandled and nobody is driving them. Unresolved ESCALATE acks do NOT page here: they are a
// session's job (the daemon peer-mails the holder once per escalation, via its pagedIds ledger), so
// the owner is paged only when no agent can act.
//
//   node desk-check.mjs
//
// Exit: 0 nothing pending, or a live watcher is already driving; 1 paged (pending work with no
//   live owner); 2 usage or IO failure. Paging = stdout page text + `notify-send` (best effort;
//   skipped when ORCH_NO_NOTIFY=1, which tests set). The trigger never takes the lock and never
//   decides anything: opening a /frood-desk (or starting the daemon) is the human's job.
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { listStreams } from "./handoff.mjs";
import { statusRows, watchInfo } from "./desk.mjs";
import { readService, syncAllStreamTitles } from "./session-title.mjs";
import { importStatusline } from "./cc-usage.mjs";
import { measure, level, readState, writeState, shouldRunNotify, notifyNow, notifyParts } from "./session-pressure.mjs";

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
  if (!pending.length) return { code: 0 };
  const watch = watchInfo(now);
  if (watch.state === "live") return { code: 0 };
  const what = `${pending.reduce((n, s) => n + s.unhandled, 0)} unhandled event(s) on ${pending.map((s) => `${s.name}(${s.unhandled})`).join(", ")}`;
  const owner = watch.state === "none" ? "no watcher" : `stale watcher (pid ${watch.pid}, ${watch.reason})`;
  const text = `desk-check: ${what}; ${owner} — open a /frood-desk`;
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
    // Claude plan-usage snapshot from the statusline sidecar: best effort, silent, local file reads only
    // (no network, so nothing to time out on); a missing sidecar or bad JSON changes nothing.
    try {
      importStatusline();
    } catch {}
    const r = check();
    let code = r.code;
    if (r.code === 1) {
      console.log(r.text);
      notify(r.text);
    }
    // Session-pressure notice: best effort, never changes desk-check output or exit codes.
    try {
      const m = measure();
      const lvl = level(m.freeGb, m.claudeN, m.load);
      const prev = readState();
      if (lvl !== "ok") {
        if (shouldRunNotify(prev, m.now, lvl)) {
          const { summary, body } = notifyParts(lvl, m);
          notifyNow(lvl, summary, body);
          prev.lastNotifyMs = m.now;
        }
      }
      // Record the observed level on every tick, including ok.
      prev.lastLevel = lvl;
      writeState(prev);
    } catch {}
    return code;
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

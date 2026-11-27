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
import { execFileSync, spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";
import { listStreams } from "./handoff.mjs";
import { statusRows, watchInfo } from "./desk.mjs";
import { readService, syncAllStreamTitles } from "./session-title.mjs";
import { importStatusline } from "./cc-usage.mjs";
import { adviseTick } from "./cc-pace.mjs";
import { scan as ledgerScan } from "./cc-ledger.mjs";
import { weekBounds, periodBounds, goConfig } from "./go-pace.mjs";
import { loadLimits, orchDir } from "./usage.mjs";
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

export const LEDGER_BUDGET_MS = 5000;

/**
 * One incremental cc-ledger scan (cc-pacing-v2 A2), in process, capped at 5 s: keeps the ledger fresh for the
 * `cc-pace status --json` shadow nowcast. Silent and best effort: returns the scan result, or null on any error.
 * deps.scan replaces the cc-ledger scan (tests).
 */
export function ledgerTick(deps = {}) {
  try {
    const run = deps.scan ?? ledgerScan;
    return run({ budgetMs: LEDGER_BUDGET_MS });
  } catch {
    return null;
  }
}

/**
 * One Go reset-probe tick (go-pacing G1). A Go quota mark can outlive the provider's reset by
 * days: while it is down every Go agent is skipped, so nothing answers to clear it. On the first
 * tick after a Go weekly (Monday 00:00 UTC) or period reset, run `router-health --probe` once —
 * the probe already re-tests quota marks, and a Go success clears the provider mark via markUp.
 *
 * `deps = {now, limits, statePath, run}`; defaults: now = Date.now(), limits = usage
 * `loadLimits()`, statePath = `<orchDir()>/go-reset-probe.json`, run = spawn a detached
 * `router-health --probe` (stdio ignored, unref'd: the tick never waits for it; the probe's own
 * per-model 90 s timeouts bound it). `boundary` = max of `weekBounds(now).start` and, when
 * `goConfig(limits).period_anchor` is set, `periodBounds(anchor, now).start`.
 *
 * State file `{last_reset_probe: ISO}`. Missing/unreadable state writes the boundary and does
 * NOT run (a first install never probes). Else, when the recorded probe predates the boundary,
 * the new boundary is written first (atomic: temp + rename) and `run()` is called once; any
 * other tick does nothing. Every failure returns `{ran: false}` silently — the tick never
 * changes desk-check output or exit codes.
 */
export function goResetProbeTick(deps = {}) {
  try {
    const now = deps.now ?? Date.now();
    const limits = deps.limits ?? loadLimits();
    const statePath = deps.statePath ?? path.join(orchDir(), "go-reset-probe.json");
    const run = deps.run ?? (() => {
      const bin = path.join(path.dirname(fileURLToPath(import.meta.url)), "router-health.mjs");
      spawn(process.execPath, [bin, "--probe"], { detached: true, stdio: "ignore", windowsHide: true }).unref();
    });
    const wb = weekBounds(now);
    if (!wb) return { ran: false };
    let boundary = wb.start;
    const anchor = goConfig(limits).period_anchor;
    if (anchor) {
      const pb = periodBounds(anchor, now);
      if (pb) boundary = Math.max(boundary, pb.start);
    }
    let last = NaN;
    try {
      const prev = JSON.parse(fs.readFileSync(statePath, "utf8"));
      if (prev && typeof prev.last_reset_probe === "string") last = Date.parse(prev.last_reset_probe);
    } catch {
      last = NaN; // missing/unreadable state: record the boundary, never probe on it
    }
    const writeBoundary = () => {
      fs.mkdirSync(path.dirname(statePath), { recursive: true });
      const tmp = `${statePath}.${process.pid}.tmp`;
      fs.writeFileSync(tmp, JSON.stringify({ last_reset_probe: new Date(boundary).toISOString() }) + "\n");
      fs.renameSync(tmp, statePath);
    };
    if (!Number.isFinite(last)) {
      writeBoundary();
      return { ran: false, boundary };
    }
    if (last < boundary) {
      writeBoundary();
      run();
      return { ran: true, boundary };
    }
    return { ran: false, boundary };
  } catch {
    return { ran: false };
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
    // Claude reset advice (cc-pace advise): silent, once-a-day desktop notice per advice; never pages, prints or fails.
    try { adviseTick(); } catch {}
    // Claude transcript ledger: one capped incremental scan per tick; silent, never changes output or exit code.
    try { ledgerTick(); } catch {}
    // Go reset probe: one detached `router-health --probe` on the first tick after a Go
    // weekly/period reset; silent, never changes output or exit code.
    try { goResetProbeTick(); } catch {}
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

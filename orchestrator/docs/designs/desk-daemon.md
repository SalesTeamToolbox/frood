# Design: headless desk daemon (`desk.mjs daemon`) — v1

**Status:** decisions recorded 2026-11-16 (D1 peer-mail secondary, D2 CLI first, D3 ready-to-launch only) · **Date:** 2026-11-16 · **Plan:** n/a (spec only, no code)

## Problem

The pipeline stalls when every session closes. Workers survive (detached process groups,
`oc-worker.mjs:541`), reports and run-done events land on disk — but nothing converts them into
critic runs, verdicts, and merges, because the watch→step→act loop is hosted inside an
interactive session (`/frood-desk` foreground `watch`, or a CC `Monitor`). The owner wants:
open `/frood-orchestrator`, dispatch, close it, and keep only the app open — with `/frood-desk` as the
single control-plane interface to every stream. Three approved pieces form one lifecycle:

1. **Idle gate** (`commands/frood-desk.md`): no stream with `unhandled>0` ⇒ end the session, don't watch.
2. **Trigger** (systemd user timer): every 5 min runs `watch --events --once`; non-empty output
   with no live lock owner ⇒ page the owner to open a `/frood-desk`.
3. **Daemon** (this spec): a persistent headless driver that runs the loop unattended, so there
   is nothing to page about unless judgment is needed. The trigger stays as the daemon's
   watchdog (daemon down + pending work ⇒ page).

## Scope: the daemon DRIVES the existing loop; it does not re-decide it

- **In:** detached poll→step→act loop; lock holding with heartbeat; executing the three
  mechanical actions (critic via `oc-worker`, resume-worker via detached spawn, merge path
  exactly as `frood-desk.md` prescribes); paging on `ESCALATE` without blocking other streams;
  `daemon start|stop|status` lifecycle; systemd user service for boot persistence and crash
  restart; `status` surfacing daemon + pending escalations to any interactive `/frood-desk`.
- **Out:** judgment (merge FAIL, `blocked_question`, exhausted rounds, senior sign-off — all
  page the owner); opening interactive sessions (a daemon cannot open one for the human —
  see "Launching orchestrator sessions"); retraining routing/pools; anything the mechanical
  loop does not already do today.
- **Size budget (actual: +469 in `desk.mjs`):** `daemon` lives in `bin/desk.mjs` as a subcommand
  (no new top-level bin); the driver core is `driveOnce` (one poll+act iteration, no lock,
  no sleep — the unit-test seam); `ORCH_DAEMON_DRY_RUN=1` logs every spawn instead of
  running it. The 300-line estimate was wrong: each frood-desk.md action needs its own executor
  (critic prompt, resume tokenize, merge path, verdict sweep, lifecycle), and splitting
  modules would have grown the exported surface (~8 new exports) instead. Overrun recorded,
  not repeated: future daemon work (systemd unit per D2, headless-orc per D3) gets its own
  budget.
- **Success metric:** owner closes every session mid-build; all mechanical events still reach
  critic→verdict→merge; every judgment call pages exactly once; zero silent takeovers.

## Files

Modify `bin/desk.mjs` (subcommand `daemon start|stop|status`, `kind: "daemon"` in the lock
owner record, `verdict` resolved-acks the critic run-done so processed streams converge to
`unhandled=0`, `ESCALATE` paging path), `bin/desk-check.mjs` (pages only on unhandled events with no live watcher;
escalations are the daemon's job, never desk-check's), `commands/frood-desk.md` (control-plane section: seize/hand back, reading
escalations via `status`), `bin/install.mjs` + `manifest.json` (install the systemd user
unit — deferred per D2). Create `docs/designs/desk-daemon.md` (this file). State under the
existing `~/.config/orchestrator/`: `desk-watch.lock/` (unchanged shape + `kind`/`log`
fields), `desk-daemon/escalations.jsonl`, `desk-daemon/state.json` (`{retries, paged,
pagedIds, errors}`), `desk-daemon/daemon.log`.

## Daemon loop (same decisions, no session)

`daemon start` (refuses when a live non-daemon owner holds the lock, unless `--takeover`):
double-fork to a detached process (stdio → `desk-daemon/daemon.log`), write the lock owner
record with `{pid, pid_start, at, token, by, session: null, kind: "daemon", log}`, then the
`watch` poll loop with heartbeat refresh. For each unhandled EVENT key, `step` decides:

- `ACTION critic …` → run the printed `oc-worker` command detached (as today) and continue.
- `ACTION resume-worker <command>` → spawn the command detached with stdio to the daemon
  log (never the session-bound background tool — there is no session) and continue.
- `ESCALATE merge …` → run `merge-check`; on `OK` perform the merge path exactly as
  `frood-desk.md` step 3 prescribes (ff-only, Frood repo only, then install + check +
  `wt-finish --delete-branch`); on `FAIL` page (below), do not merge.
- Any other `ESCALATE …` (senior, question, exhausted rounds) → page (below), do not act.

After each handled event the daemon writes the same `handoff.mjs note` a session would, so
`status` reads identically. `DONE <key>` replays are no-ops as today.

## Paging (judgment calls, exactly once)

An `ESCALATE` the daemon may not decide appends `{at, stream, key, reason}` to
`desk-daemon/escalations.jsonl`, sends one desktop notification (`notify-send`, plus the
peer-mail relay below), and records the key in `desk-daemon/state.json` — one file for the
once-only ledger, critic `retries`, and step-failure `errors`, instead of three. The ledger is
stream-scoped and lives in two fields: `pagedIds` is authoritative, every entry
`wakeId(stream, key)` (`<stream>\0<key>`), and that is the only field any reader suppresses on;
`paged` is the legacy per-writer field the schema always had (dpage wrote the bare event key,
the completion wake-up its `wakeId`), kept for older readers and inert. `errors` and `retries`
are keyed by that same `wakeId`, so one stream's step failures never push another stream's
counter or consume its critic retry; entries a pre-upgrade file wrote bare match no stream and
restart at zero. A key already in `pagedIds` is skipped silently — the ack stays unresolved,
other streams keep moving, the owner is never spammed. `status` prints pending escalations
(unpaged-by-resolution: keys still unresolved) so any interactive `/frood-desk` sees them. Resolution
is the existing `handoff.mjs ack --resolved` once the owner deals with it.

## Lock contention (daemon vs interactive desk, never silent)

- Daemon start vs live session owner ⇒ refuse with exit 3 (same message shape); only
  `--takeover` (announced by the human) kills a verified owner. A daemon never takes over
  anything on its own.
- Interactive `watch` vs live daemon owner ⇒ exit 3 naming the daemon (`kind: "daemon"`,
  pid, log path). The session stays read-only (`status`, `step` dry-run reasoning) or the
  human runs `daemon stop` (= `daemon stop` SIGTERMs the daemon, which releases the lock on
  exit) and then watches — this is "seize control". `daemon start` hands back.
- Zombie/dead daemon (crash, reboot without the service, killed): the owner record reads
  stale by the existing rules (zombie ⇒ stale, heartbeat expiry ⇒ stale) and the next
  `daemon start`, trigger, or interactive watch takes it without `--takeover`.

## Launching orchestrator sessions (what the desk can and cannot do)

Neither daemon nor interactive desk can open an interactive session for the human. Two paths:

- **Default (a): ready-to-launch.** The desk prepares ticket + Mandate + worktree, then pages
  with the exact `/frood-orchestrator` launch line (stream, ticket, resume point). Human pastes it
  into a fresh session. No autonomous spend, no surprises.
- **Opt-in (b): headless orchestrator.** `oc-worker.mjs --agent orchestrator --dir
  <worktree> --prompt <mandate>` is technically supported (any `--agent` passes through to
  `opencode run`, and `agents/orchestrator*.md` exist) — but it spends paid-model budget with
  no human in the loop. Gated behind an explicit per-stream flag
  (`orchestrator_headless: true` in the stream file, set only by the owner) plus a spend cap;
  default OFF. Not in v1 unless D3 says so.

## Trigger as watchdog (approved item 2, folded in)

The systemd timer does not run the loop; it runs `desk.mjs watch --events --once` (lockless)
every 5 minutes. Page (same channel as above) only when BOTH hold: output non-empty AND no
live lock owner (daemon down or missing). While the daemon runs healthy the trigger is
silent. The trigger is also what restarts coverage after a reboot when the service is
disabled: it pages instead of driving.

## Control-plane UX (the owner's one-session interface)

With the daemon running, an interactive `/frood-desk` is the control plane, not a second driver:

- `status` shows everything: `watch` line (daemon pid + log), streams, pending escalations.
- `daemon stop` seizes control (interactive watch takes over); `daemon start` hands back.
- New streams / extra orchestrator sessions: prepared by the desk (path (a) above), launched
  by the human paste. The desk never needs the orchestrator session open to report on it.

## Test strategy

Unit (temp `ORCH_HOME`, `ORCH_DAEMON_DRY_RUN=1` + `ORCH_NO_NOTIFY=1`, no live models): daemon
refuses a live session owner (exit 3); daemon takes a stale lock; `driveOnce` turns a worker
run-done into `ACTION critic` (dry) and replays it as `critic-inflight` once the critic run
is queued; verdict on a fixture git repo appends the verdict event and resolved-acks the
run-done (`unhandled` drops); `ESCALATE` pages exactly once (`pagedIds`, the
stream-scoped ledger, suppresses the second; the legacy `paged` field still gets its
historical entry); `daemon stop` on a dead pid exits 0 and clears the lock; `status` shows the daemon
owner plus pending escalations; `desk-check` does not page on unresolved `ESCALATE` acks (zero
unhandled events: exit 0). The full merge path (ff into the Frood repo + install + wt-finish)
is dry-run only in tests — it would touch the real checkout. Manual verification: dry run
against a live board before the first armed run.

## Owner decisions (recorded 2026-11-16)

- **D1 (paging channel): peer-mail as secondary.** Primary stays `notify-send` +
  `escalations.jsonl` surfaced in `status`. The secondary is implemented as a relay, not a
  daemon call: the daemon has no MCP channel, so the next interactive `/frood-desk` that sees
  pending escalations in `status` forwards them with `peer_send` to the responsible session.
  Peer-mail tracked zero sessions on 2026-11-16, so it can never be the only channel.
- **D2 (systemd now or later): CLI first.** Ship `daemon start|stop|status` and run it
  manually; add the user unit after stability is proven. The trigger timer (below) is
  independent and still ships now.
  **2026-11-17 reversal (owner: do both):** the unit ships now —
  `ops/systemd/orchestrator-desk-daemon.service` supervises `desk.mjs daemon _run`
  (`Restart=always`, 120s), and the `/frood-orchestrator` driver check starts the driver for
  any `unhandled>0` with no live driver, not just stream-launching sessions. Rationale:
  the daemon had never run (empty log), every driver was an interactive session, and the
  pager fired every 5 min with nobody answering.
- **D3 (headless orchestrator): ready-to-launch only.** Path (a) is the whole v1 story;
  opt-in headless orchestration is deferred, not designed here.

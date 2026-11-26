# Plan — parallel-dispatch

## Handoff

- Done (2026-11-24): M1 parallel-dispatch shipped to LOCAL main as merge 91ec45b2 (reviewed sha 68269072; not pushed).
  - Worker: CC `worker` Sonnet, 2 rounds. OpenCode paid pools were out, and Nvidia was wrongly skipped (see below).
  - Critic: r1 CHANGES_REQUESTED (2 major), r2 APPROVED; senior not needed.
  - Gates: make check green on the branch and on the merged tree; the node suite is 430/432 on the merged tree.
  - Receipts: `.opencode/reports/parallel-dispatch/` (report.md, findings-r1/r2.md).
  - Pre-existing failure, also on main b2f6310f: oc-worker.test.mjs "orphaned grandchild … orphans_killed".
  - The train (`ops/train.sh`) cannot ship Node-only tickets (it needs tests/test_<ticket>.py), so this one landed
    by merge after make check and the node suite passed on the merged tree.
- Next:      M2 (below). Its first step is the owner's choice of the indicator surface, then /frood-ticket.
- Waiting:   the owner on: push main (2 local commits: b2f6310f, 91ec45b2); the indicator surface for M2.
- Owner rule (2026-11-24): when the paid OpenCode pools are out, the worker fallback is worker-nvidia BEFORE the CC
  worker. It overrides frood-orchestrator.md:145 and :153, which M2 fixes.

## M2 status (2026-11-24 18:30)
- M2a `worker-chain`: building on worker-nvidia (oc-worker pid 1720888, stream parallel-dispatch) → desk critic → land.
- M2b `session-indicator`: queued, Mandate written. `dispatch.mjs plan` puts it serial after worker-chain, because both
  scopes list oc-worker.mjs. Rebase on main after worker-chain lands, then dispatch on worker-nvidia.
- M2c: the desktop mod, written in this session after M2b lands. It polls `dispatch.mjs status --line` every ~10 s and
  sets `$.ui.status(...)`, with an optional `placement: "widget"` pane for details. The owner chose the statusline
  surface. The CLI statusLine is not configured anywhere (cross-harness-statusline.js is installed but unwired), and
  a mod's status entry is what the desktop app draws.
- `dispatch.mjs cap --kind build` reports 3/2: frood-learn-m1b-security-egm and frood-learn-m3c have been `working`
  since 11-22/23 with no live run. Owner decision: release them or not.

## M2 status (2026-11-24 22:30)
- M2a `worker-chain` LANDED on local main eb8c7a95 (not pushed). Rounds: worker-nvidia r1+r2 (both hit the 30-min cap),
  critic r1 CR (desk.mjs scope extended), r2 CR (lint crash), r3 fix done in-session, critic r3 APPROVED.
  Merged-tree suite 472/468, 3 known failures (orphan test + 2 desk status tests also red on main). Installed.
  Board ticket released to queued, not shipped: `board round` refuses findings when the worker receipt says timeout.
- Finding: both worker runs were killed at 30 min while still active and their opencode kept running unsupervised,
  committing 9-15 min later (r1 kill 10:52 / commit 11:01; r2 kill 12:27 / commit 12:42). wt-finish later killed 2
  leftovers in the worktree. Root of the survival is likely the proc-tree sweep bug that ticket `ocw-orphan-test`
  (another session) is fixing. Proposed follow-up `worker-done-detection` (after ocw-orphan-test; shares oc-worker.mjs):
  on timeout, if HEAD moved and the report says DONE, outcome = done so the desk dispatches the critic; and a run that
  is still producing output gets its budget extended instead of a hard kill (idle-min already catches stalls).
- M2b session-indicator: next, rebase on main, dispatch on worker-nvidia (`--role worker`).
- Build cap 3/2: desk-cleanups, nested-sessions, ocw-orphan-test are `working` with dead pids (other sessions).

## Status (2026-11-24 16:05)
- `peer-mail-wake` LANDED on local main e59cacfd (not pushed): hooks/peer-mail-wake.js, an asyncRewake Stop hook,
  installed and registered in ~/.claude/settings.json (Stop, asyncRewake, timeout 86400). Critic r1 (false-positive
  scope: stale ticket base) → r2 pid-file race → r3 APPROVED. Merged suite 483/0 fail. LIVE-VERIFIED in this desktop
  session: it woke on 2 stale unread desk mails at Stop, and on a test mail sent while idle.
- `worker-done-detection` round 3 on worker-nvidia (session ses_df05f5b67ffeRe3zqrF4p9Zg3P); r2 killed itself with a
  pattern kill. Ticket base eb8c7a95.
- Lesson: ticket.json `base` must be the real fork point (`git merge-base main <branch>`), or the critic diffs
  other sessions' merges into scope.

## Queue (2026-11-24 16:20, owner: "Ticket it next, after the timeout fix lands")
1. `worker-done-detection` — round 3 running on worker-nvidia (slot acquired 15:58; budget to ~16:43).
2. `worker-liveness` — board ticket queued, Mandate `.opencode/reports/worker-liveness/mandate.md`
   (`depends: worker-done-detection`). Cut its worktree from main AFTER #1 merges; also wait for other sessions'
   `dispatch-preflight` (oc-worker.mjs) and `board-close` (desk.mjs) per `dispatch.mjs plan`. Then
   `oc-worker --role worker`, ticket.json with the real merge-base.
   Cause it fixes: r3's 44-min "silence" was a WORKER_SLOTS=2 slot wait, invisible; Nvidia itself answered in
   2-50 s/step (13 receipts: max_silence 18-298 s). Also: 6-min idle + 3 nudges for *-nvidia; hung tool children
   killed and the run nudged.
3. M2b `session-indicator`, then M2c desktop mod.
- Board gap: peer-mail-wake and worker-chain landed by merge but the board never recorded them shipped, so
  `dispatch.mjs plan` still counts peer-mail-wake as in flight. Another session's `board-close` ticket may cover it.

## Status (2026-11-24 17:30)
- `worker-done-detection` LANDED on local main 8b1ac82f (merge; conflict in oc-worker.test.mjs with dispatch-preflight
  tests resolved by keeping both). Critic r1 CR (registry lost the grace extension; grace per attempt), fixed
  in-session 8e29ca80, r2 APPROVED. Merged tree: 522 tests, 0 fail. Installed. Board ticket released (not shipped).
- The r3 worker's agent kept running in the shared `opencode serve` after its kill and committed 8d10c232 itself:
  root cause of every "killed worker keeps working" case. Now item 0 of worker-liveness (`--standalone`).
- 6b2fcefc: peer-mail-wake chdirs to $HOME (a watcher pinned a worktree; wt-finish said busy).
- worker-liveness: HELD by dispatch.mjs plan on other sessions' `desk-spawn-fixes` (oc-worker.mjs) and `board-close`
  (desk.mjs), plus cap 3/2. When board-close lands, use its close command on worker-chain, peer-mail-wake,
  worker-done-detection, then cut worker-liveness from main.
- Local main is ahead of origin (8b1ac82f, 6b2fcefc + others' local commits): push on owner's word.

## Status (2026-11-24 17:45)
- Board: worker-chain (eb8c7a95), peer-mail-wake (e59cacfd), worker-done-detection (8b1ac82f) CLOSED via `board close
  --by human` on the owner's "Yes, close all three". Origin has all of them (another session pushed).
- worker-liveness: item 0 (--standalone) moved to the other session's `killed-run-stops-agent` (stream
  desk-daemon-errors). worker-liveness now `depends: worker-done-detection, killed-run-stops-agent` and is held
  only on killed-run-stops-agent. When it ships: cut worker-liveness from main, ticket.json base = merge-base,
  `oc-worker --role worker --stream parallel-dispatch`.

## Status (2026-11-24 18:45)
- b9604e6c: Mandate templates (frood-ticket, frood-orchestrator) require the process-safety rule (spawn timeouts,
  no pattern kills). Installed.
- `learn-runs` SHIPPED (merge 41e00176, branch head 43d6c0f2): /frood learn phase 2/3 join each run to its opencode
  session — start delay, after-kill activity with git writes, tool calls > 5 min. Orchestrator fixed the git matcher
  (critic missed `cd … && git …`). Live: finds worker-chain r1/r2 + worker-done-detection r3 post-kill commits and the
  44-min wait. Board went round → signoff → gates → ready → shipped (gate needed `.venv` symlinked in the worktree).
- Lesson: worktrees need `.venv` (symlink) for `make check` gates.

## M2 (next) — nested-session activity indicator + routing fix
1. While the orchestrator manages dispatched sessions, show their live activity (ticket, stage, session, last event
   age) the way background tasks are shown. The surface is an owner decision.
2. Fix the fallback rule in frood-orchestrator.md (both cc and oc blocks) and in 01-orchestrator-models.md:
   paid OpenCode pools → worker-nvidia → free → CC worker last; Nvidia is never dropped for ticket size.
3. Small follow-ups from critic r2:
   - dispatch.mjs normPath: a `.` scope normalises to empty and overlaps nothing (fails open);
   - orchestrator/docs/designs/board.md:71 lacks `assignment.session`;
   - ops/train.sh has no Node-only path.

## Backlog (build order)
1. `dispatch.mjs plan`: the independence check over stored blast radius and scope, plus `depends:` lines.
   Shared file or dependency means serial.
2. `board.mjs session <id> --session <sid>`, stored in `assignment.session`.
3. `dispatch.mjs cap`: `adapter.json` `max_parallel`, default 2 build and 1 train/verify.
4. `desk.mjs status`: a per-ticket session column.
5. `frood-orchestrator.md`:
   - a cc-only dispatch step (one desktop session per independent ticket, each running `/frood-next <stream>`);
   - dispatched sessions stop at `board ready`, and the dispatcher alone runs `train depart`;
   - an oc-only serial or oc-worker fallback.
6. An atlas entry and tests, with the mutation check.

## Hard constraints
- The suite lock and the train stay serial. The laptop froze on 2026-11-05 under concurrent suites.
- Don't touch `orchestrator/bin/install.mjs`, which is guarded. If it needs to change, stop and trigger senior review.

## Pass bars / gates
See the Mandate. Gate: `make check`. No EGM.

## Status (2026-11-24 19:05)
- killed-run-stops-agent is no longer a hold (worker done, critic APPROVED_FREE).
- worker-liveness HELD on live runs of other streams: critic-chain-from-chains r2 (oc-worker.mjs),
  frood-learn-children r1 (desk.mjs), handoff-write-keeps-claim r1 (docs/atlas.md). Build cap 3/3.
- session-indicator HELD on critic-chain-from-chains and handoff-write-keeps-claim (same files).
- Next: re-run `dispatch.mjs plan worker-liveness session-indicator` when those land; dispatch whichever clears
  first (cut from main, symlink .venv, base = merge-base, `oc-worker --role worker --stream parallel-dispatch`).

## Status (2026-11-24 20:12, session e19e131f)
- Stream re-claimed (previous claim expired). Build cap 3/3, both tickets still HELD on live runs:
  frood-learn-children worker-r2 (desk.mjs), session-pressure worker-r1 on worker-nvidia (docs/atlas.md),
  stale-tree-preflight at critic r1 = INVALID, re-review pending (oc-worker.mjs).
- worker-liveness waits on all three; session-indicator on session-pressure + stale-tree-preflight.
  Re-run `dispatch.mjs plan worker-liveness session-indicator` after they land.

## Status (2026-11-25 14:11, session e19e131f)
- M2b `session-indicator` DISPATCHED: worktree `.claude/worktrees/session-indicator` (branch worktree/session-indicator,
  cut from main 520f595a, .venv symlinked), ticket.json base = 520f595a, board claimed + session recorded.
  oc-worker pid 224534, `--role worker` (router: worker-nvidia; paid pools down until 11-26) `--stream parallel-dispatch`.
  Mandate refreshed: base sha, worker-chain note removed, process-safety rule added, activeRuns already exported.
  Note: board `base_sha` still says c521c20d (from create); ticket.json carries the real base.
- worker-liveness still HELD by `test-orphans` (orchestrator/tests/oc-worker.test.mjs) and will also serialize behind
  session-indicator if it touches oc-worker.mjs. Re-run `dispatch.mjs plan worker-liveness` when they land.
- Then M2c desktop mod (in-session) after session-indicator lands.

## Status (2026-11-25, session e19e131f)
- M2b `session-indicator` LANDED on local main 03d73ef2 (desk ff-merge; critic r1 APPROVED; node suite 724/728 with
  3 desk slot-mode failures also red on base; make check green; `status --line` 35-37 ms). Installed (install --check OK).
  Worktree removed. Board still `working`: close needs the owner's `board close --by human`.
- Next: M2c desktop mod (in-session) polling `dispatch.mjs status --line`; worker-liveness when test-orphans clears.
- session-indicator board ticket CLOSED (owner, 2026-11-25).
- M2c written: desktop mod `dispatch-status` at ~/.claude/dev-mods/e19e131f-1693-48c0-beda-875c7687437e/dispatch-status/
  (session.start → $.clock.every 10 s → `node dispatch.mjs status --line` in the session cwd → $.ui.status; validate OK).
  Not yet seen live. Details pane not built (optional). To keep it beyond this session it needs installing/sharing as a
  plugin (owner's call).
- M2c mod: desktop does NOT draw `$.ui.status` (owner screenshot, even a constant "starting" line). v0.2.0 draws an
  AbovePrompt row instead (also keeps $.ui.status for the terminal). Awaiting owner confirmation it shows.
- worker-liveness DISPATCHED (2026-11-25 15:20): cut from main ec3186d3, .venv symlinked, ticket.json base = ec3186d3,
  board claimed + session. oc-worker pid 1112975 `--role worker-strong --stream parallel-dispatch`. Mandate refreshed:
  base, BOTH waits (acquireProviderSlot nvidia + acquireSlot fixed/dynamic) get the visible-wait line, caps unchanged,
  process-safety rule, RESULT line. At launch it sat silently waiting for the single Nvidia slot (cap 1 after a 429),
  held by another session's worktree-fence run (pid 268098) — the exact gap this ticket fixes.
- M2c CONFIRMED by owner (2026-11-25): the dispatch-status row shows above the prompt in the desktop app. It lives in
  this session's dev-mods folder only; keeping it in other sessions needs it installed/shared as a plugin.
- M2c moved INTO Frood (owner, 2026-11-25): 255f47fb — orchestrator/mods/dispatch-status (tokens), manifest.json `mods`
  kind → ~/.claude/frood-mods (install.mjs unchanged), installed, atlas + README lines. ~/.claude/settings.json env
  CLAUDE_CODE_PLUGIN_DIRS=~/.claude/frood-mods/dispatch-status (owner yes). New sessions load it; this session keeps its
  dev-mods copy. Not pushed.
- M2 item 2 (fallback rule): already fixed on main by worker-chain — frood-orchestrator.md (cc+oc) and
  01-orchestrator-models.md rule 4 say CC worker is never automatic, after every OpenCode pool incl. Nvidia. No change.
- M2 item 3 (a0c21a6c, 2026-11-25): dispatch.mjs normPath maps the repo root (`.`, `./`, root path) to `**` so a
  whole-repo scope overlaps everything (was "" → filtered → failed open); test added in dispatch.test.mjs (27/27; mutation
  check: old line → new test fails). board.md:72 documents `assignment.session`. statusline-dispatch 4/4; install --check OK.
- Remaining: ops/train.sh has no Node-only ticket path. ops/** is guarded → its own ticket with senior review.
- worker-liveness: r1/r2 worker-nvidia timeouts (45 min, no critic); r3 worker-free DONE 7a75250d; critic r3 (critic-nvidia)
  APPROVED; desk escalated senior via `verdictRound > 2` (counts worker attempts — desk bug, desk.mjs:1133).
  Senior (Opus, in-session) CHANGES_REQUESTED → senior-r3.md: [blocker] hung-tool branch resolves while opencode lives
  (timer/watchdog/sig/tree off) → second opencode on same session; [major] canResumeSilent without a session resumes
  with no Mandate. Owner: "Yes, round 4". worker-r4 launched (worker-free, --session ses_deaa82f4…, pid 2873761).
  Desk will likely ESCALATE rounds-exhausted on r4 run-done (ticket.json max_rounds 3): then run critic r4 by hand,
  then senior check of the two fixes, then merge.
- worker-liveness r4 DONE f8b17e08 (worker-free, 709 s; oc-worker 115/115, suite 736/0, make check green). Senior re-check
  (Opus): APPROVED — no resolve while opencode lives (kill only the single past-window descendant, restart silence clock;
  tracked() excludes the root), every resume needs a session. Critic r4 launched by hand (desk said rounds-exhausted):
  critic-prompt-r4.md → findings-r4.md, --stream parallel-dispatch. Next: on APPROVED, merge f8b17e08 (ff), install, close.
- worker-liveness LANDED on local main 5d87b311 (merge of f8b17e08; critic r4 APPROVED, senior re-check APPROVED).
  Conflict with cc-worker backend (9e5170b1) in runWorker resolved: cc provider-slot wait moved into the visible-wait
  try (same wait line/queued_s), attempts keep hungToolChild + isCc summarizeClaude split. Merged tree: oc-worker
  120/120, suite 818/0 (1 skip), make check 2207 passed. install up to date. Worktree finished (stray untracked
  .opencode/ticket.json from another session removed). Not pushed. Board close = owner.
- Desk follow-ups (small, own ticket): (1) desk.mjs:1133 `verdictRound > 2` counts worker attempts (timeouts) as
  review rounds → spurious senior; (2) after the worktree is finished, `desk.mjs step` still prints ESCALATE for the
  ticket's verdict/run-done events (closedTicket STALE path not reached for them).
- M2 COMPLETE except owner board close of worker-liveness.
- 4aa05aec (owner ask "why is that showing in this conversation"): `dispatch.mjs status --session <sid>` filter; mod v0.3.0
  passes $.session.id(), footer-only ($.ui.status — the desktop app now draws it), AbovePrompt row removed. Installed.
  Not pushed.

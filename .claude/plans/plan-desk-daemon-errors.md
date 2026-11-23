# Plan: desk daemon systemic errors

## Handoff
- Done: nothing yet. Filed 2026-11-23 by the OpenCode session `ses_df5f6f1f9ffeNgND1IUBfkyxXG` (STT
  production incident) after `/frood-learn` phase 5 (error patterns) on the desk daemon log.
- Next: Discuss phase. Read the ticket `.opencode/board/tickets/desk-daemon-systemic-errors.json` (full
  evidence and error breakdown), confirm each finding against
  `~/.config/orchestrator/desk-daemon/daemon.log`, then split into modules below.
- Waiting on owner: nothing.

## 1. Discuss
Five findings from the desk-daemon log (15 escalations across video-studio-m4, atlas-wiring and
gsuite/s2-storage-recurrence):
1. Worker pool exhaustion (CmdC credits) breaks the worker fallback chain.
2. Nvidia rate limiting: 16+ minute runs and 60 min timeouts.
3. Stale worktrees fail the Mandate FIRST STEP check (`git merge-base --is-ancestor`).
4. Critic chain gaps: critic-failed with no receipt; unlinked critic runs.
5. Video-studio battery scope bug: a re-run that exits before `phaseGates` boards on an old 0-FAIL block.

Item 5 lives in the video-studio repo, not here; confirm and move it to its own stream.

## 2. Backlog (build order) — to be written after Discuss
- M1 — pre-dispatch worktree freshness check in the desk daemon / oc-worker (repo: frood, `orchestrator/bin`).
- M2 — critic chain: Go Haiku fallback when CmdC is exhausted; link critic runs to their worker run.
- M3 — pool headroom: warn before CmdC credit exhaustion (`bin/usage.mjs`, `pool-health.json`).

## 3. Hard constraints
- Source is `frood/orchestrator/` (the old `~/projects/orchestrator` repo is retired).
- `npm test` in `frood/orchestrator` has 4 known failures as of 2026-11-23 (pool-health classify x3, orphaned
  grandchild sweep); do not add to them.

## 4. Gates
- `(cd orchestrator && npm test)` — no new failures.
- `node orchestrator/bin/install.mjs --check` clean after install.

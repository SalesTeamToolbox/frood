# Plan — session-pressure

## Handoff

- Done:      M1 is at board READY: worktree/session-pressure b10bd630 (3 commits on main 62b21520). Critic r3 APPROVED
  with no findings; desk merge-check OK; `make check` green (2156 passed). r1/r2 were critic-approved but sent back
  after live checks (empty idle list, wrapper pids, notify body, inverted CPU fallback, RSS display). The live run
  now lists idle sessions with titles. The worktree has a gitignored .venv symlink to the main venv.
- Next:      ff-merge worktree/session-pressure into main, then `node orchestrator/bin/install.mjs` + `--check`,
  `board close`, and `wt-finish.mjs <worktree> --delete-branch`. This needs the owner's go-ahead, relayed by the parent.
- Waiting:   owner: merge and install.
- Follow-up: desk bug. A worker run launched outside the desk's revise flow gets `ACTION critic … findings-r1.md 1`,
  so no critic runs (see side-session note session-pressure-desk-round-bug.md).

## Why
a 5-min check (from desk-check.mjs) warns via notify-send when open sessions stack up past the laptop's memory/load comfort, and lists idle sessions to archive. Report-only: it never kills or archives.

## Backlog (build order)
1. M1 session-pressure (the Mandate).

## Hard constraints
- Don't touch `orchestrator/bin/install.mjs` or `orchestrator/ops/**` (guarded).
- The suite lock and the train stay serial.

## Pass bars / gates
See the Mandate. Gate: `make check`. No EGM, no senior.

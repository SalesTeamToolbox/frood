# Plan: nvidia-throttle

## Handoff

- Done:      M1 at board `ready`, 2026-11-25: a804bd2e on worktree/nvidia-throttle. The owner chose the adaptive cap.
             Critic round 2 APPROVED, `make check` is green. Not merged yet.
- Next:      ~/projects/frood: once desk-round-count has merged to main, create the worktree
             `.claude/worktrees/nvidia-throttle` from main and write
             `.opencode/reports/nvidia-throttle/ticket.json` with base = main's sha. Then waive EGM, claim the
             ticket and launch the worker.
- Waiting:   nothing from the owner. It is blocked only on desk-round-count merging (one suite at a time).

## Why
Several Nvidia runs share one API key, and opencode retries every 2-10 s after a 429. Together they keep Nvidia's
rate limit saturated, so headless worker-nvidia runs stall. Manual runs work because there is one session and the
owner's "continue" lands after the window resets. Evidence and the design are in
`.opencode/reports/nvidia-throttle/mandate.md`.

## Backlog (build order)
1. M1 nvidia-throttle:
   - a machine-wide Nvidia provider slot (`NVIDIA_SLOTS`, default 1), claimed before the machine slot and the
     timeout clock;
   - a 60 s minimum resume wait after a quota or rate-limit interrupt (`ORCH_RATE_LIMIT_WAIT_MS`);
   - a report on whether opencode's own 429 retry is configurable.

## Hard constraints
- Pools as of 2026-11-25:
  - CmdC is out of credits.
  - opencode-go is over quota until 2026-11-26 21:00Z.
  - The opencode free pool is out until 2026-11-26 00:04Z.
  - Nvidia is up but saturated.

  The worker fallback is paid OC pools, then worker-nvidia, then free, then the Claude Code `worker` last.
- Run only one heavy test suite at a time on this laptop.

## Pass bars and gates
- The 5 tests in the Mandate, each failing before and passing after.
- `(cd orchestrator && timeout 900 npm test)`: no new failures. Known flake: `active CLI prints text rows`.
- `make check`.
- `node orchestrator/bin/install.mjs` after merge. `--check` currently fails on
  `orchestrator/rules/01-orchestrator-models.md:86` (an EOL Nvidia model), which this ticket does not cause.

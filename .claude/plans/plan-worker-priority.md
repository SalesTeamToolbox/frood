# Plan — worker-priority

## Handoff

- Done:      nothing yet. The ticket has not been claimed (board ticket queued 2026-11-25; Mandate at
  .opencode/reports/worker-priority/mandate.md).
- Next:      ~/projects/frood: held by dispatch.mjs plan on critic-chain-from-chains (oc-worker.mjs) and handoff-write-keeps-claim (docs/ATLAS.md); re-run dispatch.mjs plan worker-priority before cutting. Then cut worktree `worktree/worker-priority` from origin/main, set ticket.json
  base = merge-base, and dispatch on worker-nvidia (`oc-worker --role worker --stream worker-priority`); the desk runs the
  critic and lands it.
- Waiting:   nothing from the owner.

## Why
oc-worker lowers its own priority (nice 10, never raises) and defaults to 3 slots, so OpenCode-launched runs match WORKER_SLOTS=3 (already set for CC sessions and the desk daemon; board build cap 3 in a676be8d).

## Backlog (build order)
1. M1 worker-priority (the Mandate).

## Hard constraints
- Don't touch `orchestrator/bin/install.mjs` or `orchestrator/ops/**` (guarded).
- The suite lock and the train stay serial.

## Pass bars / gates
See the Mandate. Gate: `make check`. No EGM, no senior.

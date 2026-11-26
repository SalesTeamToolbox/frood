# Plan — desk-bookkeeping

## Handoff

- Done:      nothing yet — the ticket has not been claimed.
- Next:      ~/projects/frood: claim board ticket desk-bookkeeping, make worktree, dispatch worker with the Mandate.
- Waiting:   nothing

## Backlog (one module)

1. desk-bookkeeping — three fixes in `orchestrator/bin/desk.mjs` (Mandate:
   `.opencode/reports/desk-bookkeeping/mandate.md`):
   - critic round floor from findings on disk, worker run id and board rounds;
   - corrected findings replace an INVALID verdict at the same sha (`verdict:<run>@<n>`);
   - merge-check accepts a patch-id-identical rebase.

## Hard constraints

- `handoff.mjs`, `board.mjs`, `verdict-gate.mjs` unchanged. Board `ready`/`verify` keep exact-sha.
- merge-check stdout stays exactly `OK` / `FAIL <check>`.

## Pass bars

- `timeout 600 node --test orchestrator/tests/desk.test.mjs` green, with the new tests.
- `timeout 900 make check` green; `tests/test_atlas.py` green.

## Gates

Adapter: `make check`. EGM waived (no egm path); no senior trigger (no guarded path).

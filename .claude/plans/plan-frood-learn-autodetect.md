# Plan: frood-learn-autodetect

## Handoff

- Done:      nothing yet — the ticket has not been claimed. Mandate + board ticket (queued, EGM pending → waive: not guarded) written 2026-11-24.
- Next:      ~/projects/frood: read `.opencode/reports/frood-learn-autodetect/mandate.md`, waive EGM, claim, write `<run dir>/ticket.json`, dispatch one worker (absolute --report/--out).
- Waiting:   nothing

## Backlog (build order)

1. `autoDetectStream`: add `CLAUDE_CODE_SESSION_ID` after `OPENCODE_SESSION_ID` (it equals the CC peer-mail id / held_session).
2. `findStreamBySession`: match `claim?.session` (claim is an object).
3. handoff-quality (phase 1 + phase 3 blocks): `waiting: ""` is not missing; staleness from noted_at/written_at/consumed_at, not `new Date(next)`; flag a done stream whose `next` still names a live worker.
4. Tests in `tests/test_frood_learn_cli.py` (temp ORCH_HOME only) + one ATLAS.md line.

## Hard constraints

- Never read or write the real `~/.config/orchestrator/streams` in tests.
- Learning hooks are out of scope (meta-review exclusion).
- Link `~/projects/frood/.venv` into the worktree before `board gates`.

## Pass bars / gates

- pytest `tests/test_frood_learn_cli.py tests/test_atlas.py` green; `make check` green via `board.mjs gates`. No EGM/senior.

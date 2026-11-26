# Plan: board-close

## Handoff

- Done:      2026-11-24 — claimed stream (cc, session 9fefbcc1); EGM waived on the board; worktree `.claude/worktrees/board-close` on branch `ticket/board-close` from main@acfc2716; board ticket claimed (working); `ticket.json` written; worker r1 launched with `--stream board-close --ticket board-close` (pid 646731, worker-nvidia). It was queued behind the WORKER_SLOTS cap (2/2) at launch.
- Next:      the desk daemon drives critic rounds, merge-check and ff-merge, and peer-mails session 9fefbcc1 on merge/sign-off. After the merge: `node orchestrator/bin/install.mjs` then `--check`.
- Waiting:   NEEDS OWNER after the merge: yes in chat to run `board.mjs close desk-cleanups --by human --sha acfc2716 --note "merged to main as 2f8dad53 + acfc2716 by the interactive desk; make check green; worktree removed before board gates"`.

## Backlog (build order)

1. board.mjs:
   - add `closed` to STAGES, the schema enum and the ticket schema (an optional `closed` record);
   - add a `close` row to the transition table: from queued, working, ready or blocked, to closed;
   - write `cmdClose`: `--by human` only, a note of 10+ characters, `--sha` must be an ancestor of `adapter.base` or of the local branch with the same name; it nulls the assignment and drops the lock;
   - add `close` to the help text.
2. dispatch.mjs:196: count `closed` as a satisfied dependency, like `shipped`.
3. Tests: `orchestrator/tests/board.test.mjs` (every allowed and refused case in the Mandate) and `orchestrator/tests/dispatch.test.mjs` (a dependency on a closed ticket is grouped).
4. Docs: `orchestrator/docs/designs/board.md` (stage enum, stage machine, Commands, test cases) and the board-commands line in `orchestrator/commands/frood-orchestrator.md`. Then `node orchestrator/bin/install.mjs` and `--check`.
5. After the merge (orchestrator, with the owner's yes): `board.mjs close desk-cleanups --by human --sha acfc2716 --note "…"`.

## Hard constraints

- Mandate: `.opencode/reports/board-close/mandate.md` sets the scope and the files the worker may not touch.
- Existing transitions and their tests must not change. The worker may not touch desk.mjs or handoff.mjs: they already ignore closed tickets, and the report must say why.
- `close` must refuse any `--by` other than `human`. No session may close a ticket without the owner's yes in chat.

## Pass bars / gates

- New board and dispatch tests green; `cd orchestrator && node --test tests/` passes with 0 failures; `make check` green; `install.mjs --check` OK.
- Board gates: `make check`. No EGM and no senior review. A paid critic is required, since a free review escalates to owner sign-off.

# Plan: ocw-orphan-test

## Handoff

- Done:      shipped 2026-11-24 — 766f248f merged to main as e64e4cdc. Root cause: ps lstart lags Date.now() ~0.9 s (btime drift) + 1 s floor, so startOk() rejected root and every descendant; watch() now measures the skew from /proc. Gate green (2150 passed). Stream done.
- Next:      — (closed). Critic minors done in 9e85eac4; desk-test/ruff cleanup 407b9b02; follow-up tickets: dispatch-preflight (shipped bb6e9139), frood-learn-autodetect (queued, stream pending).
- Waiting:   nothing

## Backlog (build order)

1. Root cause: why the grandchild spawned by `fake-opencode.mjs` (FAKE_OC_MODE=orphan) is not in `orphans_killed`. Check what `watch()` samples, the grandchild's ppid/pgid/sid after its parent exits, and whether the 300 ms sampler ever sees it.
2. Fix the cause: in the sweep if production orphans would leak, in the test/fixture if its assumptions are wrong. No skip, no retries, no loosened assertion.
3. Prove it: 5/5 isolated runs green, full `node --test orchestrator/tests/` green.

## Hard constraints

- Mandate: `.opencode/reports/ocw-orphan-test/mandate.md` (scope, blast radius, pass bars).
- The machine runs agents at BelowNormal (priority guard). Never raise priority; one heavy suite at a time.
- The sweep kills processes on a shared machine: never widen it beyond processes descended from the opencode child.

## Pass bars / gates

- Isolated test 5/5, full orchestrator suite 0 failures, `make check` green.
- Board gates from `.opencode/board/adapter.json`: `make check`. No EGM, no senior.

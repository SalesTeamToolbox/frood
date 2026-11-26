# Plan — train-node-tests: the release train can ship a Node-only ticket

## Handoff

- Done:      SHIPPED 2026-11-25. Merged to main as a3a3870b (commits 0430237e worker, 27b0883d senior fixes).
             EGM approved after resolution; critic r1 APPROVED (nvidia), senior fixes (comma split in Mandate
             `tests:`, logs truncated per run), critic r2 APPROVED (sonnet); `make check` gate green at 27b0883d;
             train exit 0 (tests_source: board-ticket). Board: shipped. Worktree removed.
- Left open (minor, not fixed): train.sh header still says logs are "appended"; an unquoted Mandate `tests:`
             token would glob `*?[`. Pre-existing flaky `orchestrator/tests/oc-worker-active.test.mjs:141`
             (wall-clock elapsed assertion) seen by the worker.
- Next:      — (stream done)
- Waiting:   nothing.

## Origin
Stream parallel-dispatch, `.claude/plans/plan-parallel-dispatch.md` M2 item 3: `ops/train.sh` step 2 (~:64-72)
only accepts `tests/test_<ticket>[_demo].py`, so Node-only orchestrator tickets (parallel-dispatch, worker-chain,
session-indicator) shipped by desk ff-merge instead of the train.

## Backlog (build order) — one module
M1 train-node-tests: Mandate `.opencode/reports/train-node-tests/mandate.md`.
  Step 2 resolves pinned tests: Python convention (unchanged) → board ticket `blast_radius[].test` → Mandate
  `tests:` line → refuse. `.py` → `timeout` + pytest; `*.test.mjs|js` → `timeout <s> node --test <file>`, serially.
  Receipt gains `tests_source:` / `tests:`; exit codes unchanged. New `tests/test_train_node_tests.py`; atlas line;
  frood-train.md doc.

## Hard constraints
- `ops/**` is guarded → critic, then senior review before `ready`. EGM required by the board (many-modules).
- Train stays serial (max_parallel.train 1, box-wide suite lock); no parallel test runs.
- Python ticket behaviour byte-for-byte unchanged; receipt existing lines and exit codes unchanged (ops/progress.sh reads them).
- Do not touch orchestrator/**, ops/progress.sh, ops/install.mjs, adapter.json, Makefile.
- Process safety: every child process has a timeout; never pkill/killall/pgrep-kill; kill only pids this run started.

## Pass bars
- `timeout 1200 python3 -m pytest tests/test_train_node_tests.py -q` green (cases listed in the Mandate).
- `make check` green (incl. tests/test_atlas.py); `(cd orchestrator && timeout 900 npm test)` unchanged green.
- Dogfood: `bash ops/train.sh train-node-tests` exits 0.

## Gates
adapter.json: `make check`. EGM: required (pre-gauntlet). Senior: required (guarded ops/train.sh).

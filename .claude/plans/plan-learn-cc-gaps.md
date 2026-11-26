# Plan — learn-cc-gaps

## Handoff

- Done:      M1 shipped 2026-11-25: ff-merged to local main at c521c20d (3 commits: b6a32df8 feature, 9f865894 WIP from a timed-out worker, c521c20d fixture fix); install + --check OK; board ticket shipped with round, critic signoff (native Sonnet) and make check gate recorded (2192 passed, 2 skipped). EGM report `.opencode/plans/egm-learn-cc-gaps.md`; critic docs in `.opencode/reports/learn-cc-gaps/orchestrator-critic-r2b.md` and `-r5.md`. Worktree removed; branch `worktree/learn-cc-gaps` kept (local main is not pushed to origin).
- Next:      nothing on this stream. Optional: a test for resolveDesktopSessionId skipping an invalid cliSessionId in a first org file.
- Waiting:   owner: push local main to origin when ready (it is several merges ahead).

## Backlog (build order)

1. **M1 — learn-cc-gaps** (one module, all in `bin/frood-learn.mjs` plus tests):
   - (a) tool_result-only user lines are no longer counted as prompts;
   - (b) the title comes from the `custom-title` line, or from the desktop metadata;
   - (c) a `blocked-actions` finding for denied tool calls, with board/handoff writes at high severity;
   - (d) a stream cross-check for merged tickets that have no recorded rounds, gates or sign-offs.

## Hard constraints

- Report only. Never add allow rules and never touch any permission or settings file.
- Fixtures are synthetic. Never commit a real transcript: the repo is public.
- OpenCode child reviews and the phase 1-4 stream lenses stay unchanged.

## Pass bars

- `timeout 900 make check` exits 0.
- The new tests listed in the Mandate's "Pass bars" pass.

## Gates

- Adapter gates: `make check`.
- EGM: triggered by many-modules (see above).
- No senior review.

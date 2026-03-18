---
phase: 05-streaming-pty-bridge-and-cc-initialization-optimization
plan: 03
subsystem: api
tags: [pty, websocket, asyncio, pre-warm, session-pool, subprocess]

# Dependency graph
requires:
  - phase: 05-02
    provides: PTY-based cc_chat_ws with PIPE fallback, keepalive, expanded _parse_cc_event
  - phase: 05-01
    provides: Wave 0 RED test scaffold (test_cc_pty.py, 12 xfail)
provides:
  - _cc_warm_pool dict scoped inside create_app() closure, keyed by username
  - _cc_spawn_warm() async function: spawns sentinel '.' CC run, extracts session_id via PTY/PIPE
  - _cc_prewarm_idle_task() background task: purges pool entries idle for 300s
  - cc_chat_ws ?warm=true query param: triggers background warm spawn at WS open
  - cc_chat_ws warm pool claim: first user message atomically pops warm entry and uses --resume
affects:
  - any future plan that extends cc_chat_ws or the CC session lifecycle

# Tech tracking
tech-stack:
  added: [time.monotonic (idle TTL tracking)]
  patterns:
    - "Warm pool keyed by username (not tab/session) — one warm process per user"
    - "_cc_warm_pool.pop(user, None) for atomic single-claim across concurrent tabs"
    - "Warm spawn: PTY (win/unix) with PIPE fallback — mirrors cc_chat_ws spawn order"
    - "Idle cleanup: 60-second polling loop, 300-second TTL per entry"
    - "@app.on_event('startup') to register background cleanup task"
    - "Store _get_user_from_token() result as _cc_user for reuse in warm pool logic"

key-files:
  created: []
  modified:
    - dashboard/server.py

key-decisions:
  - "Warm pool idle timeout uses _CC_WARM_IDLE_TIMEOUT = 300 constant (not inline magic number)"
  - "Warm spawn mirrors cc_chat_ws spawn order: win32 PTY, unix PTY, PIPE fallback"
  - "warm_entry popped atomically to prevent double-claim from concurrent WS tabs"
  - "Only inject session_id when cc_session_id is None (first message guard)"
  - "@app.on_event('startup') used for background cleanup task registration"

patterns-established:
  - "Pre-warm pool pattern: spawn sentinel run at WS-open, claim via --resume at first message"
  - "Pool entry: {cc_session_id, ready, spawned_at, last_used} -- session_id is the only durable value"

requirements-completed: [PTY-03]

# Metrics
duration: 6min
completed: 2026-03-18
---

# Phase 05 Plan 03: Pre-Warm CC Session Pool Summary

**Pre-warmed CC session pool (_cc_warm_pool) eliminating the ~50s cold-start delay via sentinel-run --resume pattern, with 5-minute idle timeout and ?warm=true opt-in**

## Performance

- **Duration:** 6 min
- **Started:** 2026-03-18T22:07:00Z
- **Completed:** 2026-03-18T22:13:17Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Added `_cc_warm_pool` dict inside `create_app()` closure with 300-second idle timeout constant
- Implemented `_cc_spawn_warm()` that runs a sentinel `"."` CC invocation via PTY (win32/unix) or PIPE fallback, extracts the `session_id` from the `result` event, and stores it in the pool
- Implemented `_cc_prewarm_idle_task()` background task that purges idle pool entries every 60 seconds using `time.monotonic()` timestamps
- Registered cleanup task via `@app.on_event("startup")` inside `create_app()` closure
- Integrated pool into `cc_chat_ws`: `?warm=true` triggers background warm spawn at WS open; first user message atomically claims via `_cc_warm_pool.pop()` and injects `cc_session_id` so the existing `--resume` code path fires naturally
- All 13 test_cc_pty.py tests pass (12 xpass + 1 pass), completing Phase 5 PTY requirements (0 xfail)

## Task Commits

Each task was committed atomically:

1. **Task 1: Add _cc_warm_pool data structure and background cleanup task** - `9ab0ac2` (feat)
2. **Task 2: Integrate warm pool into cc_chat_ws connection and message flow** - `456dc6d` (feat)

## Files Created/Modified

- `dashboard/server.py` - _cc_warm_pool dict, _cc_spawn_warm(), _cc_prewarm_idle_task(), startup handler, cc_chat_ws warm integration

## Decisions Made

- **Warm spawn mirrors cc_chat_ws spawn order** (win32 PTY → unix PTY → PIPE fallback): consistency prevents platform-specific gaps and ensures the warm session_id is from the same execution environment
- **`_CC_WARM_IDLE_TIMEOUT = 300` named constant**: makes the 5-minute timeout explicit and grep-findable
- **`_cc_warm_pool.pop(user, None)` atomic claim**: prevents race condition when user has multiple WS tabs — first message claim wins, subsequent tabs get a fresh spawn
- **Only inject warm session_id when `cc_session_id` is None**: guard ensures warm pool is only used for new sessions, not resumed ones
- **Store `_get_user_from_token(token)` result as `_cc_user`**: enables reuse at both connection-open (warm trigger) and per-message (pool claim) without double-calling the token decode

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- `@app.on_event("startup")` emits a FastAPI deprecation warning (recommends lifespan handlers). This is the pattern specified in the plan and matches the existing codebase conventions. The warning does not affect functionality. All 1403 tests pass with 32 total warnings (same category as pre-existing warnings).

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Phase 5 is fully complete: all 3 plans done, all 13 test_cc_pty.py tests green
- Requirements PTY-01 through PTY-05 all satisfied
- No blockers for next workstream phase

## Self-Check: PASSED

- `05-03-SUMMARY.md` — FOUND
- `dashboard/server.py` — FOUND
- Commit `9ab0ac2` (Task 1) — FOUND
- Commit `456dc6d` (Task 2) — FOUND
- Commit `112e7b2` (metadata) — FOUND

---
*Phase: 05-streaming-pty-bridge-and-cc-initialization-optimization*
*Completed: 2026-03-18*

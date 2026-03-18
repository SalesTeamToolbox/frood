---
phase: 05-streaming-pty-bridge-and-cc-initialization-optimization
plan: 02
subsystem: api
tags: [pty, winpty, ndjson, websocket, subprocess, asyncio, keepalive, ansi]

# Dependency graph
requires:
  - phase: 05-01
    provides: Wave 0 RED test scaffold (test_cc_pty.py, 12 xfail)
  - phase: 02-core-chat-ui
    provides: cc_chat_ws endpoint with PIPE subprocess + _parse_cc_event function in server.py
  - phase: 01-backend-ws-bridge
    provides: /ws/cc-chat WebSocket bridge and NDJSON parsing pattern
provides:
  - PTY-based cc_chat_ws (winpty on Windows, pty.openpty on Unix) with PIPE fallback
  - Expanded _parse_cc_event with system/init mcp_servers relay and hook_started progress
  - Keepalive task sending {"type":"keepalive"} every 15 seconds during CC subprocess execution
  - ANSI escape code stripping before NDJSON parsing (_ANSI_ESCAPE regex)
  - _terminate_cc() DRY helper for consistent subprocess cleanup across PTY/Popen/asyncio modes
affects:
  - 05-03 (pre-warm pool plan - only TestPreWarmPool tests remain xfail)

# Tech tracking
tech-stack:
  added: [winpty (Windows PTY), pty (Unix PTY), select (Unix I/O polling)]
  patterns:
    - "PTY subprocess spawn with graceful PIPE fallback via try/except ImportError"
    - "winpty.PtyProcess.readline via run_in_executor for line-buffered async reads"
    - "Unix PTY: select.select + os.read with _cc_line_buf accumulation for line splitting"
    - "cc_ prefix on all cc_chat_ws PTY variables to avoid collision with terminal WS variables"
    - "dimensions=(24, 220) prevents NDJSON line wrap at 80-col default terminal width"
    - "ANSI escape regex sub before JSON parsing strips PTY color codes"
    - "keepalive asyncio.Task cancelled in finally block alongside read_task"
    - "_terminate_cc() inspects hasattr returncode vs poll to handle asyncio vs Popen subprocess"

key-files:
  created: []
  modified:
    - dashboard/server.py

key-decisions:
  - "PTY spawn in cc_chat_ws uses cc_ prefixed variables to avoid collision with terminal WS PTY vars"
  - "Windows: winpty.PtyProcess.readline (not read(4096)) for complete NDJSON lines"
  - "Unix PTY: select + accumulation buffer pattern rather than readline (more portable)"
  - "PIPE fallback (PTY-04) preserved as else branch - identical to pre-PTY implementation"
  - "keepalive_task.cancel() in finally block alongside read_task.cancel() - consistent cleanup"
  - "_terminate_cc() helper used in stop handler, disconnect handler, and finally - DRY"
  - "hook_response subtype suppressed from frontend (too verbose)"
  - "mcp_servers entries checked with isinstance(srv, dict) for defensive handling of string entries"

patterns-established:
  - "PTY-with-PIPE-fallback: try PTY spawn, except Exception sets use_cc_pty=False, then if not use_cc_pty: create_subprocess_exec"
  - "Two-branch read loop: if use_cc_pty and win32 / elif use_cc_pty / else (PIPE) - clear mode dispatch"

requirements-completed: [PTY-01, PTY-02, PTY-04, PTY-05]

# Metrics
duration: 18min
completed: 2026-03-18
---

# Phase 05 Plan 02: PTY Bridge Implementation Summary

**PTY-based cc_chat_ws replacing PIPE subprocess with winpty/pty line-buffered reads, expanded _parse_cc_event for MCP server init relay, and 15-second keepalive task**

## Performance

- **Duration:** 18 min
- **Started:** 2026-03-18T22:05:00Z
- **Completed:** 2026-03-18T22:23:00Z
- **Tasks:** 2
- **Files modified:** 1

## Accomplishments

- Replaced PIPE-based subprocess spawn in cc_chat_ws with PTY (winpty on Windows, pty.openpty on Unix) using dimensions=(24, 220) to prevent NDJSON line wrapping
- Expanded `_parse_cc_event` to relay per-MCP-server connection status from system/init events and hook_started progress messages
- Added keepalive asyncio task sending `{"type": "keepalive"}` every 15 seconds to prevent WebSocket timeout during CC startup
- Preserved PIPE fallback path (PTY-04) as the else branch when PTY is unavailable
- Added `_ANSI_ESCAPE` regex to strip ANSI color codes from PTY output before NDJSON parsing
- 10 of 13 test_cc_pty.py tests now pass (9 xpassed + 1 passed); only TestPreWarmPool 3 remain xfail for Plan 05-03

## Task Commits

Each task was committed atomically:

1. **Task 1: Expand _parse_cc_event for init progress (PTY-02)** - `8caaa27` (feat)
2. **Task 2: Replace PIPE with PTY + add keepalive (PTY-01, PTY-04, PTY-05)** - `2803d7c` (feat)

## Files Created/Modified

- `dashboard/server.py` - PTY subprocess spawn, expanded _parse_cc_event, keepalive task, _terminate_cc helper, _ANSI_ESCAPE regex

## Decisions Made

- cc_ variable prefixes for all cc_chat_ws PTY variables (cc_pty_process, cc_proc, cc_master_fd, cc_slave_fd) to avoid collision with terminal WS PTY variables (pty_process, proc, master_fd) which exist in the same create_app() closure
- Windows PTY uses readline (not read(4096)) to guarantee complete NDJSON lines; Unix PTY uses select+accumulation buffer for the same reason
- PIPE fallback preserved as the final else branch - identical to pre-PTY implementation, ensuring PTY-04 requirement
- keepalive_task cancelled in finally block alongside read_task for consistent cleanup
- hook_response subtype suppressed from frontend relay (too verbose, no user value)

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered

- Security monitor hook triggered (false positive) on first Edit attempt containing Python subprocess code. Second attempt succeeded without changes. No impact on implementation correctness.

## User Setup Required

None - no external service configuration required.

## Next Phase Readiness

- Plan 05-03 is the final plan in Phase 5: pre-warm pool (_cc_warm_pool dict with 5-minute idle timeout and ?warm=true query param support). Only 3 TestPreWarmPool tests remain xfail.
- No blockers for Plan 05-03 execution.

---
*Phase: 05-streaming-pty-bridge-and-cc-initialization-optimization*
*Completed: 2026-03-18*

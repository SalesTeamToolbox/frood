---
workstream: custom-claude-code-ui
created: 2026-03-17
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-17)

**Core value:** Agent42 must provide a rich, VS Code-quality Claude Code chat experience in its web IDE
**Current focus:** Phase 1 — Backend WS Bridge

## Current Position

Phase: 1 of 4 (Backend WS Bridge)
Plan: 2 of 3 in current phase (01-01, 01-02 complete)
Status: In progress
Last activity: 2026-03-18 — Plan 01-02 complete (/ws/cc-chat endpoint + helpers)

Progress: [██░░░░░░░░] 20%

## Performance Metrics

**Velocity:**
- Total plans completed: 2
- Average duration: 12.5 min
- Total execution time: 25 min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 01-backend-ws-bridge | 2/3 | 25 min | 12.5 min |

*Updated after each plan completion*

## Accumulated Context

### Decisions

- Phase 1 must ship before any frontend work — `cc_chat_ws` endpoint is strict prerequisite
- DOMPurify sanitization is non-negotiable in Phase 2; cannot be retrofitted
- Append-only DOM and scroll-pin must be Phase 2 initial implementation, not added later
- StrongWall.ai deprecated (causes CC disconnects); smart hybrid: CC subscription for interactive
- Session persistence (sessionStorage + --resume) belongs in Phase 3, not deferred to v2
- LAYOUT-04 (Monaco diff editor) grouped with layout modes in Phase 4 — all UI arrangement work
- xfail(raises=ImportError, strict=False) pattern for tests importing symbols not yet implemented
- Wave 0 source inspection tests left as RED AssertionError — correct TDD state; Plan 02 GREEN flips them
- _parse_cc_event, _save_session, _load_session are closure-scoped inside create_app() — not importable as module attributes; xfail tests for direct import remain xfail by design
- claude auth status result cached 60s to avoid Node.js cold-start latency per connection
- subprocess args always a Python list; user_message passed as positional arg (no shell=True)

### Pending Todos

None.

### Blockers/Concerns

- Phase 3 research flag: verify CC PermissionRequest event payload structure against current CC version before implementing permission UI
- Open: tool_complete.output field path with --verbose not verified from live session; current implementation emits empty string (safe for Phase 2, may need update in Phase 3)

## Session Continuity

Last session: 2026-03-18
Stopped at: Plan 01-02 complete — /ws/cc-chat implemented. Ready for Plan 01-03 (verification/integration tests).
Resume file: None

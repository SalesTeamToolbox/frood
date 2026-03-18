---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-18T19:36:16.978Z"
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-17)

**Core value:** Agent42 must provide a rich, VS Code-quality Claude Code chat experience in its web IDE
**Current focus:** Phase 5 — Streaming PTY Bridge

## Current Position

Phase: 5 of 5 (Streaming PTY Bridge — IN PROGRESS)
Plan: 1 of 3 in Phase 5 complete
Status: Phase 5 Plan 1 DONE — Wave 0 test scaffold complete (13 tests: 12 xfail RED, 1 pass)
Last activity: 2026-03-18 — Plan 05-01 complete (test_cc_pty.py Wave 0 scaffold, cc_init_event.ndjson fixture)

Progress: [█████████░] 90%

## Performance Metrics

**Velocity:**
- Total plans completed: 7
- Average duration: 6.1 min
- Total execution time: 45 min

**By Phase:**

| Phase                | Plans    | Total  | Avg/Plan |
|----------------------|----------|--------|----------|
| 01-backend-ws-bridge | 3/3 DONE | 29 min | 9.7 min  |
| 02-core-chat-ui      | 5/5 DONE | 27 min | 5.4 min  |
| 05-streaming-pty     | 1/3 DONE | 15 min | 15 min   |

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
- Auth status check uses exit code only (not JSON parsing) — insulated from claude CLI schema changes
- Session listing uses per-file try/except — corrupt files do not break GET /api/cc/sessions
- Wave 0 scaffold uses source-text inspection (Path.read_text) — identical to test_ide_html.py; 20 tests across 5 classes; TestCCChatStop uses inspect.getsource(dashboard.server) for backend pattern checks
- Phase 5 Wave 0: xfail(raises=AssertionError, strict=False) for unimplemented PTY features; test_pipe_fallback_preserved not xfail because PIPE already exists in cc_chat_ws
- _extract_function_source helper: indent-based regex finds closure-scoped function bodies for isolated ns unit testing
- Use highlight.min.js (full bundle) not core.min.js — core has zero language definitions built in
- hljs CSS scoped to .cc-chat-messages to prevent conflicts with existing .md-code-block styles
- CDN load order: marked -> marked-highlight -> hljs -> DOMPurify -> app.js (UMD globals must exist when app.js runs)
- markedHighlight CDN UMD pattern: markedHighlight.markedHighlight (namespace.function) not globalThis.markedHighlight
- Global security_reminder_hook.py blocks first innerHTML assignment per session; second attempt allowed — DOMPurify usage is safe
- ideOpenCCChat replaces ideOpenClaude in all onclick HTML strings; ideOpenClaude function kept intact for backward compat
- Slash command dropdown uses only safe DOM APIs (createElement, textContent) — no innerHTML with user input to prevent XSS
- ccSend handles /clear locally (clears DOM) without sending to CC backend — avoids unnecessary WS traffic
- ccStop leaves sending state true — backend turn_complete event resets it via ccSetSendingState (correct lifecycle)

### Roadmap Evolution

- Phase 5 added: Streaming PTY bridge and CC initialization optimization (addresses pipe buffering and ~50s cold start)

### Pending Todos

None.

### Blockers/Concerns

- Phase 3 research flag: verify CC PermissionRequest event payload structure against current CC version before implementing permission UI
- Open: tool_complete.output field path with --verbose not verified from live session; current implementation emits empty string (safe for Phase 2, may need update in Phase 3)
- Pre-existing test_auth_flow.py failure: test_protected_endpoint_requires_auth checks /api/tasks returns 401 but gets 404 — unrelated to CC bridge, deferred

## Session Continuity

Last session: 2026-03-18
Stopped at: Plan 05-01 complete — Phase 5 Wave 0 test scaffold done. test_cc_pty.py (13 tests: 12 xfail RED, 1 pass) and cc_init_event.ndjson fixture created. Ready for Plan 05-02 (PTY implementation).
Resume file: None

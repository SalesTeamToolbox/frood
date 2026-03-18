---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-18T22:22:12.621Z"
---

---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-18T22:13:17.000Z"
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-17)

**Core value:** Agent42 must provide a rich, VS Code-quality Claude Code chat experience in its web IDE
**Current focus:** Phase 5 — COMPLETE

## Current Position

Phase: 5 of 5 (Streaming PTY Bridge — COMPLETE)
Plan: 3 of 3 in Phase 5 complete
Status: Phase 5 DONE - All 13 test_cc_pty.py tests GREEN. Pre-warm pool with 5-min idle timeout.
Last activity: 2026-03-18 — Plan 05-03 complete (pre-warm pool, idle cleanup, ?warm=true integration)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 9
- Average duration: 7.6 min
- Total execution time: 69 min

**By Phase:**

| Phase                | Plans    | Total  | Avg/Plan |
|----------------------|----------|--------|----------|
| 01-backend-ws-bridge | 3/3 DONE | 29 min | 9.7 min  |
| 02-core-chat-ui      | 5/5 DONE | 27 min | 5.4 min  |
| 05-streaming-pty     | 3/3 DONE | 39 min | 13.0 min |

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
- `cc_` prefix on all `cc_chat_ws` PTY variables to avoid collision with terminal WS PTY variables in same `create_app()` closure
- PTY-with-PIPE-fallback: try PTY spawn, except Exception -> `use_cc_pty=False`, then PIPE path; PIPE fallback identical to pre-PTY implementation (PTY-04 preserved)
- `hook_response` subtype suppressed from frontend relay (too verbose for UI); `hook_started` emits "Loading {name}..." progress status
- Warm pool keyed by username (one per user not per tab); atomic pop prevents double-claim
- ?warm=true opt-in triggers _cc_spawn_warm() background task at WS open; warm session_id injected via --resume

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
Stopped at: Plan 05-03 complete - pre-warm pool with `_cc_spawn_warm()`, `_cc_prewarm_idle_task()`, ?warm=true integration. All 13 test_cc_pty.py GREEN. Phase 5 COMPLETE.
Resume file: None

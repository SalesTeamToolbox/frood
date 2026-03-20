---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-20T18:01:59.507Z"
---

---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-19T02:53:54.263Z"
---

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
**Current focus:** Phase 4 — Layout + Diff Viewer — COMPLETE

## Current Position

Phase: 4 of 5 COMPLETE (Layout + Diff Viewer — all 4 plans done)
Plan: 4 of 4 in Phase 4 complete
Status: Plan 04-04 DONE - Monaco diff editor tabs with side-by-side view, ideOpenDiffTab, ideDetectLanguage, ccOpenDiffFromToolCard, View Diff + Open File buttons on Write/Edit tool cards. All 12 LAYOUT-01/02/03/04 tests XPASS. Phase 4 fully complete.
Last activity: 2026-03-20 — Plan 04-04 complete (Monaco diff editor integration, all LAYOUT tests green)

Progress: [██████████] 100%

## Performance Metrics

**Velocity:**
- Total plans completed: 13
- Average duration: 7.6 min
- Total execution time: 102 min

**By Phase:**

| Phase                | Plans    | Total  | Avg/Plan |
|----------------------|----------|--------|----------|
| 01-backend-ws-bridge | 3/3 DONE | 29 min | 9.7 min  |
| 02-core-chat-ui      | 5/5 DONE | 27 min | 5.4 min  |
| 05-streaming-pty     | 3/3 DONE | 39 min | 13.0 min |
| 03-tool-use-sessions | 5/5 DONE | 49 min | 9.8 min  |
| 04-layout-diff-viewer| 4/4 DONE | ~30 min| ~7.5 min |

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
- Phase 3 Wave 0: 28 tests across 10 classes; xfail(strict=False) for all unimplemented features; TestParseToolResultFixture passes GREEN (fixture validation)
- Phase 3 NDJSON fixture: cc_tool_result_sample.ndjson with Read + Bash tool_result content blocks for _parse_cc_event unit testing
- permission_request emitted at content_block_stop (not content_block_start) so input is fully parsed before frontend receives it
- input_buf accumulated for ALL tools in tool_id_map (not just permission tool) to support future tool_complete input enrichment
- last_assistant_text capped at 200 chars (ring buffer) to bound memory growth across long sessions; first 60 chars saved as preview_text in session JSON
- ccMakeWsHandler factory extracts all WS dispatch logic from ideOpenCCChat for reuse by ccResumeSession (Plan 03-05)
- Partial JSON from tool_delta accumulated in inputBuf string; only parsed after tool_complete (avoids Pitfall 2: SyntaxError on partial JSON)
- tool_output enriches finalized card via data-tool-id selector, decoupled from tool_complete timing
- ccToolType helper centralizes file/bash/generic detection; toolCards map reset on turn_complete to clear stale references
- Trust mode is per-tab (tab.trustMode) not global — isolates trust scope to individual CC sessions
- Auto-approve in trust mode sends permission_response immediately + brief notice; no full card rendered
- permission_request WS case needs no tab.toolCards lookup — backend pre-parses input before emitting
- sessionStorage keyed as cc_active_session; first tab only restores (tabCounter===1) to avoid cross-tab conflicts
- ccResumeSession reuses ccMakeWsHandler factory — no handler duplication, consistent with Plan 03-03 architecture
- Session sidebar hidden by default; ccToggleSessionSidebar lazy-loads sessions on first open
- Token accumulation is client-side only per session; resets on ccResumeSession
- LAYOUT-02/03 features already in app.js and style.css before Plan 04-01 execution; Wave 0 scaffold confirms 8/12 tests XPASS
- LAYOUT-04 (ideOpenDiffTab, createDiffEditor, View Diff) not yet implemented; 4 tests XFAIL for Plan 04-04
- Wave 0 source inspection tests: xfail(strict=False) allows XPASS when feature already exists — correct TDD state
- ideToggleCCPanel() implemented as functional stub in Plan 04-02 (not just no-op) — enables immediate test verification; Plan 04-03 adds full mode-switching logic
- .ide-main flex-direction changed from column to row in Plan 04-02; .ide-main-editor-area wrapper uses min-width:0 to prevent flex overflow
- `_isPanelDragging` uses separate namespace from `_isDragging` (terminal) to prevent variable collision in `create_app()` closure
- DOM reparenting via appendChild() preserves WS connection (tab.ws) and all inline onclick handlers — only tab.el DOM position changes
- 50ms setTimeout for ideMoveSessionsToPanel when opening new CC session ensures tab is in _ideTabs array before move iterates
- ideActivateTab panel-mode branch early returns to avoid #ide-cc-container visibility logic when session is in panel
- ideRenderTabs uses return "" in map() for panel-mode CC tabs — excluded from join but tab stays in _ideTabs for state tracking
- Diff tab object shape: {type:"diff", diffEditor, diffOriginalModel, diffModifiedModel, el:.ide-diff-container, path:"filename \u2194 Changes"}
- .ide-diff-container class on diff container divs enables querySelectorAll for targeted hide-all in ideActivateTab (cleaner than inline style selector)
- Both diff panes forced read-only: originalEditable:false in createDiffEditor options + getOriginalEditor/getModifiedEditor().updateOptions({readOnly:true})
- ccOpenDiffFromToolCard fetches original via GET /api/ide/file with Authorization header; falls back to empty string on 404 (new file case)
- ideDetectLanguage maps 25+ extensions to Monaco language IDs; called in ideOpenDiffTab with fallback to plaintext

### Roadmap Evolution

- Phase 5 added: Streaming PTY bridge and CC initialization optimization (addresses pipe buffering and ~50s cold start)

### Pending Todos

None.

### Blockers/Concerns

- Phase 3 research flag: verify CC PermissionRequest event payload structure against current CC version before implementing permission UI (partially resolved — backend WS side done; cc_permission MCP tool stub still needed in mcp_server.py for end-to-end test)
- Open: tool_complete.output field path with --verbose not verified from live session; tool_output envelope now supplements tool_complete with actual content
- Pre-existing test_auth_flow.py failure: test_protected_endpoint_requires_auth checks /api/tasks returns 401 but gets 404 — unrelated to CC bridge, deferred

## Session Continuity

Last session: 2026-03-20
Stopped at: Plan 04-04 complete - Monaco diff editor tabs (ideOpenDiffTab, ideDetectLanguage, ccOpenDiffFromToolCard), View Diff + Open File buttons on tool cards (ccFinalizeToolCard), diff branches in ideActivateTab/ideCloseTab. All 12 LAYOUT-01/02/03/04 tests XPASS. Phase 4 COMPLETE (4/4 plans done).
Resume file: None

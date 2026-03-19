---
workstream: custom-claude-code-ui
milestone: v2.0
created: 2026-03-17
### Phase 5: Streaming PTY bridge and CC initialization optimization

**Goal:** CC chat responses stream in real-time via PTY (not block-buffered PIPE), with initialization progress visible and optional pre-warming to eliminate cold start delay
**Requirements:** PTY-01, PTY-02, PTY-03, PTY-04, PTY-05
**Depends on:** Phase 2
**Plans:** 3 plans

Plans:
- [x] 05-01-PLAN.md — Wave 0 test scaffold (test_cc_pty.py + cc_init_event.ndjson fixture)
- [ ] 05-02-PLAN.md — PTY subprocess + init progress + keepalive (server.py)
- [ ] 05-03-PLAN.md — Pre-warmed CC session pool (server.py)

---

# Roadmap: Custom Claude Code UI

## Overview

Four phases build the VS Code-quality Claude Code chat interface inside Agent42's web IDE.
Phase 1 establishes the backend WebSocket bridge — the strict prerequisite that every frontend
feature depends on. Phase 2 builds the core chat panel with correctness properties (sanitization,
append-only DOM, scroll-pin) that cannot be retrofitted later. Phase 3 adds tool use visualization
and full session persistence, which together differentiate this from a plain chat box. Phase 4
completes v1 with flexible layout options and the Monaco diff viewer, delivering the full
user-chosen workspace arrangement.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [x] **Phase 1: Backend WS Bridge** - WebSocket endpoint that spawns CC subprocess and relays typed events to the frontend
- [x] **Phase 2: Core Chat UI** - Streaming chat panel with markdown rendering, sanitization, input box, and scroll-pin
- [x] **Phase 3: Tool Use + Sessions** - Tool use cards, permission UI, session persistence, and multi-session tabs
- [ ] **Phase 4: Layout + Diff Viewer** - Tab/panel layout modes, user toggle, and Monaco diff editor integration
- [ ] **Phase 5: Streaming PTY Bridge** - PTY subprocess for real-time streaming, init progress, pre-warm pool

## Phase Details

### Phase 1: Backend WS Bridge
**Goal**: The backend can spawn Claude Code processes, translate their NDJSON stream into typed WebSocket messages, and manage sessions — unblocking all frontend work
**Depends on**: Nothing (first phase)
**Requirements**: BRIDGE-01, BRIDGE-02, BRIDGE-03, BRIDGE-04, BRIDGE-05, BRIDGE-06
**Success Criteria** (what must be TRUE):
  1. A WebSocket client connecting to `/ws/cc-chat` and sending a message receives typed events (text_delta, tool_start, tool_complete, turn_complete) that correspond to the CC subprocess output
  2. Sending a follow-up message to an active session resumes the CC conversation with context from the prior turn (--resume works)
  3. When the `claude` CLI is not available, the endpoint sends a fallback error message indicating API mode instead of crashing
  4. A `GET /api/cc/sessions` request returns a list of session metadata (session ID, timestamps); a `DELETE` removes the entry
  5. Calling `claude auth status` or equivalent reports subscription availability that the frontend can read
**Plans**: 3 plans

Plans:

- [x] 01-01-PLAN.md — Wave 0 test scaffold (test_cc_bridge.py + NDJSON fixture)
- [x] 01-02-PLAN.md — CC WebSocket bridge + NDJSON parser + session helpers
- [x] 01-03-PLAN.md — Session REST endpoints + auth-status with 60s cache

### Phase 2: Core Chat UI
**Goal**: Users can have a streaming conversation with Claude Code in a chat panel that renders markdown correctly and safely, with proper scroll behavior and input controls
**Depends on**: Phase 1
**Requirements**: CHAT-01, CHAT-02, CHAT-03, CHAT-04, CHAT-05, CHAT-06, CHAT-07, CHAT-08, CHAT-09, INPUT-01, INPUT-02, INPUT-03, INPUT-04
**Success Criteria** (what must be TRUE):
  1. User messages appear immediately in styled bubbles with avatar and timestamp; assistant responses stream in token by token with a blinking cursor that disappears on completion
  2. Completed assistant messages render markdown (headers, bold, lists, links, code blocks with syntax highlighting) without any unsanitized HTML executing in the browser
  3. While a response streams, the chat panel stays pinned to the bottom; scrolling up during streaming stops auto-scroll and a scroll-to-bottom button appears
  4. The Stop button cancels an in-progress generation; the Send button (Enter key) submits messages; Shift+Enter inserts a newline; the input box grows vertically as text is typed
  5. Typing `/` in the input shows a slash command autocomplete dropdown with available commands
**Plans**: 5 plans

Plans:

- [x] 02-01-PLAN.md — Wave 0 test scaffold (tests/test_cc_chat_ui.py — 20 tests)
- [x] 02-02-PLAN.md — Backend stop handler (server.py asyncio.wait() concurrent receive)
- [x] 02-03-PLAN.md — CDN deps (index.html) + CC chat CSS classes (style.css)
- [x] 02-04-PLAN.md — Core chat JS: ideOpenCCChat, streaming bubble lifecycle, ccRenderMarkdown
- [x] 02-05-PLAN.md — Input controls: ccSend, ccStop, ccInputResize, ccUpdateSlashDropdown

### Phase 3: Tool Use + Sessions
**Goal**: Users can see exactly what Claude Code is doing (tool calls, permissions) and can resume past conversations from a session history sidebar
**Depends on**: Phase 2
**Requirements**: TOOL-01, TOOL-02, TOOL-03, TOOL-04, TOOL-05, TOOL-06, SESS-01, SESS-02, SESS-03, SESS-04, SESS-05, SESS-06
**Success Criteria** (what must be TRUE):
  1. Each tool invocation renders as a collapsible card showing tool name and running/complete/error status; expanding the card reveals input parameters and output result
  2. File read/write tool cards display the file path prominently and show a syntax-highlighted content preview; command tool cards show the command and its terminal output
  3. When CC requests a permission, an inline approve/reject UI appears in the chat without requiring the user to switch to the raw terminal
  4. The session ID persists across page navigation so refreshing the page does not lose conversation context; the user can open additional CC sessions as separate tabs
  5. The session history sidebar lists past conversations with timestamps and preview text; clicking a session resumes that conversation
  6. Token usage for the current session is visible in the UI
**Plans**: 5 plans

Plans:

- [x] 03-01-PLAN.md — Wave 0 test scaffold (test_cc_tool_use.py + cc_tool_result_sample.ndjson fixture)
- [x] 03-02-PLAN.md — Backend: _parse_cc_event tool_result/permission + session metadata extension
- [x] 03-03-PLAN.md — Frontend: tool card rendering (create/delta/complete/output) + CSS
- [x] 03-04-PLAN.md — Frontend: permission request UI + trust mode + CSS
- [x] 03-05-PLAN.md — Frontend: session persistence, tab strip, sidebar, token bar + CSS

### Phase 4: Layout + Diff Viewer
**Goal**: Users can position the CC chat interface as an editor tab or a resizable side panel, and can view code diffs in a Monaco-powered diff editor
**Depends on**: Phase 3
**Requirements**: LAYOUT-01, LAYOUT-02, LAYOUT-03, LAYOUT-04
**Success Criteria** (what must be TRUE):
  1. The CC chat interface opens as an editor tab in the main editor area by default
  2. The user can switch the CC interface to a dedicated resizable right-side panel without losing conversation state
  3. The user can toggle back and forth between tab and panel modes
  4. Code diffs proposed by CC display in Monaco's built-in diff editor with side-by-side comparison
**Plans**: TBD

### Phase 5: Streaming PTY Bridge & CC Initialization Optimization
**Goal**: CC chat responses stream in real-time via PTY (not block-buffered PIPE), with initialization progress visible and optional pre-warming to eliminate cold start delay
**Depends on**: Phase 2
**Requirements**: PTY-01, PTY-02, PTY-03, PTY-04, PTY-05
**Success Criteria** (what must be TRUE):
  1. CC subprocess uses PTY (winpty on Windows, pty on Unix) instead of PIPE, enabling line-buffered stdout and real-time stream_event delta delivery
  2. Initialization progress is relayed to the frontend -- system events (hook_started, MCP server connecting) shown as italicized status messages during the ~50s CC cold start
  3. A pre-warmed CC session pool keeps one idle CC session ready per user, so the first message response is near-instant (no MCP init delay)
  4. If PTY is unavailable, the system falls back to PIPE with assistant event text extraction (current behavior preserved)
  5. cc_chat_ws sends periodic keepalive messages during CC init without triggering page reload or disconnect
**Plans**: 3 plans

Plans:

- [x] 05-01-PLAN.md — Wave 0 test scaffold (test_cc_pty.py + cc_init_event.ndjson fixture)
- [x] 05-02-PLAN.md — PTY subprocess + init progress + keepalive (server.py)
- [x] 05-03-PLAN.md — Pre-warmed CC session pool (server.py)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 -> 2 -> 3 -> 4 (Phase 5 can run after Phase 2)

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Backend WS Bridge | 3/3 | Complete | 2026-03-18 |
| 2. Core Chat UI | 5/5 | Complete | 2026-03-18 |
| 3. Tool Use + Sessions | 2/5 | In Progress | - |
| 4. Layout + Diff Viewer | 0/? | Not started | - |
| 5. Streaming PTY Bridge | 3/3 | Complete | 2026-03-18 |

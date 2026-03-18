# Requirements: Custom Claude Code UI

**Defined:** 2026-03-17
**Core Value:** Agent42 must provide a rich, VS Code-quality Claude Code chat experience in its web IDE

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Backend Bridge

- [ ] **BRIDGE-01**: Server exposes `/ws/cc-chat` WebSocket endpoint that spawns `claude -p --output-format stream-json` and relays structured NDJSON events to the frontend
- [ ] **BRIDGE-02**: Backend translates CC stream-json events (system, stream_event, result) into a normalized message format (text_delta, tool_start, tool_complete, turn_complete, etc.)
- [ ] **BRIDGE-03**: Session registry tracks active CC processes by session ID, allowing multi-session management
- [ ] **BRIDGE-04**: Multi-turn conversations work via `--resume <session_id>` — process re-spawned per turn with session continuity
- [ ] **BRIDGE-05**: Fallback path uses existing `/api/ide/chat` (Anthropic API via httpx) when `claude` CLI is not available
- [ ] **BRIDGE-06**: Server detects CC subscription status via `claude auth status` and reports availability to frontend

### Chat Rendering

- [ ] **CHAT-01**: User messages display in styled bubbles with avatar and timestamp
- [ ] **CHAT-02**: Assistant messages display in styled bubbles with streaming text cursor during generation
- [ ] **CHAT-03**: Completed messages render markdown (headers, lists, bold, italic, links) via marked.js
- [ ] **CHAT-04**: Code blocks render with syntax highlighting via highlight.js
- [ ] **CHAT-05**: All AI-generated HTML is sanitized via DOMPurify before DOM insertion
- [ ] **CHAT-06**: Streaming uses append-only DOM (no re-render of previous messages) with 50ms batched updates
- [ ] **CHAT-07**: Auto-scroll pins to bottom during streaming, releases when user scrolls up
- [ ] **CHAT-08**: Stop button cancels active generation (kills CC process)
- [ ] **CHAT-09**: Thinking/reasoning blocks display in collapsible sections with distinct styling

### Tool Use Display

- [ ] **TOOL-01**: Tool invocations display as collapsible cards showing tool name and status (running/complete/error)
- [ ] **TOOL-02**: Tool cards show input parameters when expanded
- [ ] **TOOL-03**: Tool cards show output/result when expanded after completion
- [ ] **TOOL-04**: File read/write tools show file path prominently with syntax-highlighted content preview
- [ ] **TOOL-05**: Command execution tools show the command and its output
- [ ] **TOOL-06**: Permission requests display inline with approve/reject buttons

### Rich Input

- [ ] **INPUT-01**: Multi-line text input box with Shift+Enter for newlines and Enter to send
- [ ] **INPUT-02**: Input supports paragraph breaks (multiple newlines preserved)
- [ ] **INPUT-03**: Input box auto-resizes vertically as content grows (up to configurable max height)
- [ ] **INPUT-04**: Slash command autocomplete dropdown (e.g., /help, /clear, /compact)

### Session Management

- [ ] **SESS-01**: Each CC conversation has a unique session ID tied to the CC process session
- [ ] **SESS-02**: Session ID persists in sessionStorage so page navigation doesn't lose context
- [ ] **SESS-03**: User can open multiple CC sessions as separate tabs
- [ ] **SESS-04**: Session history sidebar lists past conversations with timestamps and preview
- [ ] **SESS-05**: User can resume a past session from the history list
- [ ] **SESS-06**: Token usage display shows context window utilization per session

### Layout

- [ ] **LAYOUT-01**: CC interface opens as an editor tab in the main editor area
- [ ] **LAYOUT-02**: CC interface can also open as a dedicated resizable side panel (right)
- [ ] **LAYOUT-03**: User can switch between tab and panel modes
- [ ] **LAYOUT-04**: Diff viewer uses Monaco's built-in diff editor for proposed code changes

## v2 Requirements

Deferred to future release. Tracked but not in current roadmap.

### Enhanced Input

- **INPUT-05**: @-mention file references with fuzzy search popup
- **INPUT-06**: File drag-drop attachment to messages
- **INPUT-07**: Image paste for vision analysis

### Advanced Features

- **ADV-01**: Conversation fork/rewind to earlier message
- **ADV-02**: Cost tracking across sessions with daily/weekly summaries
- **ADV-03**: Remote CC sessions via SSH relay to VPS
- **ADV-04**: Export conversation as markdown

## Out of Scope

| Feature | Reason |
|---------|--------|
| Custom fine-tuned models | Agent42 uses standard provider APIs |
| Voice input/output | Complexity, low priority vs text chat |
| Real-time collaboration | Multi-user not in scope for v1 |
| Mobile-responsive chat | Desktop-first IDE experience |
| StrongWall.ai integration | Deprecated — causes CC disconnects |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| _(populated during roadmap creation)_ | | |

**Coverage:**
- v1 requirements: 27 total
- Mapped to phases: 0
- Unmapped: 27

---
*Requirements defined: 2026-03-17*
*Last updated: 2026-03-17 after initial definition*

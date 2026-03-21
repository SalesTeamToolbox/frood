# Requirements: Custom Claude Code UI

**Defined:** 2026-03-17
**Core Value:** Agent42 must provide a rich, VS Code-quality Claude Code chat experience in its web IDE

## v1 Requirements

Requirements for initial release. Each maps to roadmap phases.

### Backend Bridge

- [x] **BRIDGE-01**: Server exposes `/ws/cc-chat` WebSocket endpoint that spawns `claude -p --output-format stream-json` and relays structured NDJSON events to the frontend
- [x] **BRIDGE-02**: Backend translates CC stream-json events (system, stream_event, result) into a normalized message format (text_delta, tool_start, tool_complete, turn_complete, etc.)
- [x] **BRIDGE-03**: Session registry tracks active CC processes by session ID, allowing multi-session management
- [x] **BRIDGE-04**: Multi-turn conversations work via `--resume <session_id>` — process re-spawned per turn with session continuity
- [x] **BRIDGE-05**: Fallback path uses existing `/api/ide/chat` (Anthropic API via httpx) when `claude` CLI is not available
- [x] **BRIDGE-06**: Server detects CC subscription status via `claude auth status` and reports availability to frontend

### Chat Rendering

- [x] **CHAT-01**: User messages display in styled bubbles with avatar and timestamp
- [x] **CHAT-02**: Assistant messages display in styled bubbles with streaming text cursor during generation
- [x] **CHAT-03**: Completed messages render markdown (headers, lists, bold, italic, links) via marked.js
- [x] **CHAT-04**: Code blocks render with syntax highlighting via highlight.js
- [x] **CHAT-05**: All AI-generated HTML is sanitized via DOMPurify before DOM insertion
- [x] **CHAT-06**: Streaming uses append-only DOM (no re-render of previous messages) with 50ms batched updates
- [x] **CHAT-07**: Auto-scroll pins to bottom during streaming, releases when user scrolls up
- [x] **CHAT-08**: Stop button cancels active generation (kills CC process)
- [x] **CHAT-09**: Thinking/reasoning blocks display in collapsible sections with distinct styling

### Tool Use Display

- [ ] **TOOL-01**: Tool invocations display as collapsible cards showing tool name and status (running/complete/error)
- [ ] **TOOL-02**: Tool cards show input parameters when expanded
- [ ] **TOOL-03**: Tool cards show output/result when expanded after completion
- [ ] **TOOL-04**: File read/write tools show file path prominently with syntax-highlighted content preview
- [ ] **TOOL-05**: Command execution tools show the command and its output
- [x] **TOOL-06**: Permission requests display inline with approve/reject buttons

### Rich Input

- [x] **INPUT-01**: Multi-line text input box with Shift+Enter for newlines and Enter to send
- [x] **INPUT-02**: Input supports paragraph breaks (multiple newlines preserved)
- [x] **INPUT-03**: Input box auto-resizes vertically as content grows (up to configurable max height)
- [x] **INPUT-04**: Slash command autocomplete dropdown (e.g., /help, /clear, /compact)

### Session Management

- [x] **SESS-01**: Each CC conversation has a unique session ID tied to the CC process session
- [x] **SESS-02**: Session ID persists in sessionStorage so page navigation doesn't lose context
- [x] **SESS-03**: User can open multiple CC sessions as separate tabs
- [x] **SESS-04**: Session history sidebar lists past conversations with timestamps and preview
- [x] **SESS-05**: User can resume a past session from the history list
- [x] **SESS-06**: Token usage display shows context window utilization per session

### Layout

- [ ] **LAYOUT-01**: CC interface opens as an editor tab in the main editor area
- [ ] **LAYOUT-02**: CC interface can also open as a dedicated resizable side panel (right)
- [x] **LAYOUT-03**: User can switch between tab and panel modes
- [ ] **LAYOUT-04**: Diff viewer uses Monaco's built-in diff editor for proposed code changes

### Chat UX Polish

- [ ] **UX-01**: MCP/hook "Connecting to X..." init messages are suppressed from the chat message list — replaced by a single compact "Initializing Claude Code..." status chip that auto-dismisses when the first real response arrives
- [ ] **UX-02**: Animated typing indicator (three pulsing dots) appears within 200ms of user sending a message and disappears when the first `text_delta` token is received
- [ ] **UX-03**: Each LLM turn produces exactly one assistant message bubble — duplicate detection prevents repeated answers under any reconnect or retry condition

### Memory Visibility

- [ ] **MEM-01**: When the context assembler loads memories for a turn, a subtle inline status line "↺ Loaded N memories" appears below the user message (not a full bubble, dismissed after 5s)
- [ ] **MEM-02**: When the Stop hook saves a memory, a "✓ Memory saved" indicator appears in the chat — visible confirmation that the memory pipeline is active

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

### Streaming PTY Bridge & Initialization

- **PTY-01**: CC subprocess uses winpty (Windows) / pty (Unix) instead of PIPE — enabling line-buffered stdout and real-time `stream_event` delta delivery
- **PTY-02**: Initialization progress relayed to frontend — system events (hook_started, MCP server connecting) shown as status messages during the ~50s CC cold start
- **PTY-03**: Pre-warmed CC session pool — keep one idle CC process ready so first message response is near-instant (no MCP init delay)
- **PTY-04**: Graceful degradation — if winpty unavailable, fall back to PIPE with `assistant` event text extraction (current behavior)
- **PTY-05**: WS heartbeat tolerance — cc_chat_ws keeps connection alive during long CC init without triggering page reload

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
| BRIDGE-01 | Phase 1 | Complete |
| BRIDGE-02 | Phase 1 | Complete |
| BRIDGE-03 | Phase 1 | Complete |
| BRIDGE-04 | Phase 1 | Complete |
| BRIDGE-05 | Phase 1 | Complete |
| BRIDGE-06 | Phase 1 | Complete |
| CHAT-01 | Phase 2 | Complete |
| CHAT-02 | Phase 2 | Complete |
| CHAT-03 | Phase 2 | Complete |
| CHAT-04 | Phase 2 | Complete |
| CHAT-05 | Phase 2 | Complete |
| CHAT-06 | Phase 2 | Complete |
| CHAT-07 | Phase 2 | Pending |
| CHAT-08 | Phase 2 | Pending |
| CHAT-09 | Phase 2 | Complete |
| INPUT-01 | Phase 2 | Pending |
| INPUT-02 | Phase 2 | Pending |
| INPUT-03 | Phase 2 | Pending |
| INPUT-04 | Phase 2 | Pending |
| TOOL-01 | Phase 3 | Pending |
| TOOL-02 | Phase 3 | Pending |
| TOOL-03 | Phase 3 | Pending |
| TOOL-04 | Phase 3 | Pending |
| TOOL-05 | Phase 3 | Pending |
| TOOL-06 | Phase 3 | Complete |
| SESS-01 | Phase 3 | Complete |
| SESS-02 | Phase 3 | Complete |
| SESS-03 | Phase 3 | Complete |
| SESS-04 | Phase 3 | Complete |
| SESS-05 | Phase 3 | Complete |
| SESS-06 | Phase 3 | Complete |
| LAYOUT-01 | Phase 4 | Pending |
| LAYOUT-02 | Phase 4 | Pending |
| LAYOUT-03 | Phase 4 | Complete |
| LAYOUT-04 | Phase 4 | Pending |
| PTY-01 | Phase 5 | Pending |
| PTY-02 | Phase 5 | Pending |
| PTY-03 | Phase 5 | Pending |
| PTY-04 | Phase 5 | Pending |
| PTY-05 | Phase 5 | Pending |

| UX-01 | Phase 6 | Pending |
| UX-02 | Phase 6 | Pending |
| UX-03 | Phase 6 | Pending |
| MEM-01 | Phase 6 | Pending |
| MEM-02 | Phase 6 | Pending |

**Coverage:**

- v1 requirements: 45 total
- Mapped to phases: 45
- Unmapped: 0

---

*Requirements defined: 2026-03-17*
*Last updated: 2026-03-18 after Plan 01-03 — Phase 1 complete, BRIDGE-01 through BRIDGE-06 all done*

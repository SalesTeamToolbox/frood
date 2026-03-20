# Phase 3: Tool Use + Sessions - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning

<domain>
## Phase Boundary

Display CC tool invocations as rich collapsible cards in the chat flow, handle CC permission requests with inline approve/reject UI, persist sessions across page refreshes, support multi-session tabs, and show token usage. This phase transforms the chat from a plain text interface into a full visibility layer for what CC is actually doing.

Out of scope: Layout/panel modes (Phase 4), diff viewer (Phase 4), @-mention file references (v2), conversation fork/rewind (v2).

</domain>

<decisions>
## Implementation Decisions

### Tool card presentation (TOOL-01 through TOOL-05)
- Inline collapsible cards appear in the chat flow between assistant text
- Cards are collapsed by default showing tool name + status icon (running/complete/error)
- Click to expand reveals input parameters and output result
- Live streaming: tool_delta events update the expanded card in real-time as tool runs
- File read/write tools: file path shown prominently at top, syntax-highlighted content preview (reuses highlight.js from Phase 2), truncated to ~30 lines with "Show more" expander
- Command/Bash tools: terminal-styled dark output block, command shown in monospace header, truncated to ~20 lines with expand. Visual language matches the terminal tab
- Error state: tool cards with `is_error: true` show red border/icon

### Permission request UX (TOOL-06)
- Inline card with approve/reject buttons, highlighted styling (distinct from regular tool cards)
- Shows what CC wants to do (tool name, target file/command)
- CC subprocess blocks until user responds — no timeout, waits indefinitely (matches terminal CC behavior)
- Global session "Trust mode" toggle: auto-approves all permissions for the rest of the session
- Trust mode indicator visible in UI when active (so user knows permissions are being auto-approved)
- Permission response sent back to CC subprocess via stdin (research needed: verify exact CC permission protocol)

### Session persistence (SESS-01, SESS-02)
- Active session ID stored in sessionStorage (per-tab, survives refresh within same tab)
- On page refresh: reconnect WS with same session_id query param, CC resumes via --resume
- Previous messages NOT re-rendered on reconnect — clean slate with "Session resumed" status message
- CC has full conversation context server-side; Agent42 only stores metadata (Phase 1 decision preserved)

### Multi-session tabs (SESS-03)
- Horizontal tab bar above the chat message area
- Each tab shows session title (first ~30 chars of first user message) with close button
- "+" button creates a new session
- Active tab highlighted, switching tabs swaps the chat area content
- Each tab maintains its own WS connection and session state

### Session history sidebar (SESS-04, SESS-05)
- Existing session-sidebar scaffold from Phase 2 used as starting point
- Each entry shows: auto-generated title, relative timestamp ("2h ago"), first ~60 chars of last message as preview
- Grouped by Today / Yesterday / Older
- Clicking a session resumes it: chat clears, "Session resumed" status shown, CC uses --resume
- Data source: GET /api/cc/sessions (built in Phase 1) — may need to extend metadata fields (preview text, message count)

### Token usage display (SESS-06)
- Compact status bar between session tab strip and chat messages
- Shows: input tokens, output tokens, cumulative session cost
- Format: abbreviated with K suffix (1,200 → "1.2K"), cost as "$0.003"
- Updates on each turn_complete event (data already flowing from Phase 1)
- Cumulative: client-side accumulation across turns within a session

### Claude's Discretion
- Tool card CSS styling details (colors, shadows, borders, animations)
- Exact permission card animation/pulse effect while waiting
- Session tab overflow behavior (scroll vs dropdown when many tabs)
- How to detect CC's permission request event format (research phase will verify)
- Trust mode toggle placement and styling
- Session metadata field extensions for preview text

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/workstreams/custom-claude-code-ui/REQUIREMENTS.md` §Tool Use Display — TOOL-01 through TOOL-06 acceptance criteria
- `.planning/workstreams/custom-claude-code-ui/REQUIREMENTS.md` §Session Management — SESS-01 through SESS-06 acceptance criteria
- `.planning/workstreams/custom-claude-code-ui/ROADMAP.md` §Phase 3 — success criteria and phase dependencies

### Backend bridge (already built — must read before implementing frontend)
- `dashboard/server.py` `_parse_cc_event` function — tool_start/tool_delta/tool_complete envelope schema, tool_id_map management
- `dashboard/server.py` cc_chat_ws — WS message flow, session_state management, PTY subprocess lifecycle
- `dashboard/server.py` GET/DELETE /api/cc/sessions — session metadata REST endpoints

### Frontend chat (built in Phase 2 — extend, don't replace)
- `dashboard/frontend/dist/app.js` ideOpenCCChat function — chat panel setup, WS handlers, message rendering
- `dashboard/frontend/dist/app.js` session-sidebar HTML — existing scaffold to build upon
- `dashboard/frontend/dist/style.css` .cc-chat-* classes — existing chat CSS namespace

### Prior phase context
- `.planning/workstreams/custom-claude-code-ui/phases/01-backend-ws-bridge/01-CONTEXT.md` — WS message schema contract (text_delta, tool_start, tool_delta, tool_complete, turn_complete, error, status)

### CC CLI permission protocol
- STATE.md research flag: "verify CC PermissionRequest event payload structure against current CC version before implementing permission UI"
- STATE.md concern: "tool_complete.output field path with --verbose not verified from live session"
- Researcher MUST verify these from live CC session or CC documentation before planning the permission UI

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `highlight.js` (CDN, loaded in Phase 2): Reuse for syntax-highlighted file content in tool cards
- `DOMPurify` (CDN, loaded in Phase 2): Sanitize any tool output before DOM insertion
- `session-sidebar` HTML scaffold: Already has structure with `createChatSession('chat')` button and `.session-list` container
- `_parse_cc_event` backend: Already emits `tool_start`, `tool_delta`, `tool_complete` with correct schema — frontend just needs to render them
- `ccSessionId` state variable: Already tracked in ideOpenCCChat — extend for multi-tab
- GET/DELETE `/api/cc/sessions`: Session metadata endpoints already built (Phase 1)

### Established Patterns
- All chat rendering uses `createElement` + `textContent` (safe DOM) — no innerHTML with user content
- WS message handling switches on `envelope.type` in the `ws.onmessage` handler
- CSS classes namespaced as `.cc-chat-*` — continue this for tool cards
- highlight.js scoped to `.cc-chat-messages` to prevent style conflicts

### Integration Points
- Tool card rendering hooks into the existing `ws.onmessage` handler (add cases for `tool_start`, `tool_delta`, `tool_complete`)
- Permission cards need a new case in `ws.onmessage` AND a way to send responses back via WS (currently WS is receive-only for CC events — need to add a message type for permission responses)
- Session tabs integrate above the existing `.cc-chat-messages` container
- Token bar sits between tab strip and messages
- Session sidebar already exists — enhance with richer metadata and resume-on-click

</code_context>

<specifics>
## Specific Ideas

- Tool cards should feel like Claude.ai's tool use display — inline, unobtrusive when collapsed, detailed when expanded
- Terminal-styled output blocks should match the terminal tab's visual language (dark background, monospace)
- "Trust mode" is a power-user feature — should be visible but not prominent. A small toggle in the session toolbar area
- Session resume shows "Session resumed: {title}" status message + "Context preserved (N turns)" — user knows CC has the context even though messages aren't re-rendered
- The permission card should have a subtle pulse/glow animation while waiting for user response — draws attention without being obnoxious

</specifics>

<deferred>
## Deferred Ideas

- Full message transcript storage and replay on session resume — adds significant storage and complexity
- Per-tool-type auto-approve ("always allow Read this session") — could be added as an enhancement to trust mode later
- Cross-session cost tracking and daily/weekly summaries — ADV-02, deferred to v2
- Configurable --allowedTools per session — future enhancement
- @-mention file references in input — INPUT-05, deferred to v2

</deferred>

---

*Phase: 03-tool-use-and-sessions*
*Context gathered: 2026-03-18*

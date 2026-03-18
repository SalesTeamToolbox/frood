# Phase 05: Streaming PTY Bridge & CC Initialization Optimization - Context

**Gathered:** 2026-03-18
**Status:** Ready for planning
**Source:** Live debugging session — discovered pipe buffering root cause

<domain>
## Phase Boundary

Replace the PIPE-based CC subprocess in `cc_chat_ws` with a PTY-based subprocess (winpty on Windows, pty on Unix) to get line-buffered stdout, enabling real-time streaming of `stream_event` / `content_block_delta` events. Also relay CC initialization progress to the frontend and optionally pre-warm a CC session to eliminate ~50s cold start.

</domain>

<decisions>
## Implementation Decisions

### PTY Subprocess (PTY-01, PTY-04)
- Use winpty on Windows (already a dependency — terminal WS uses it)
- Use pty module on Unix (stdlib)
- cc_chat_ws should mirror the terminal WS's PTY setup pattern (lines 1540-1610 in server.py)
- If winpty/pty unavailable, fall back to current PIPE + `assistant` event extraction (PTY-04)
- NDJSON parsing must handle partial lines from PTY (buffered differently than PIPE)

### Initialization Progress (PTY-02)
- Parse `system` events (hook_started, hook_response, init) and relay as `status` messages
- Show MCP server connection status from `init` event's `mcp_servers` array
- Frontend shows italicized status messages in chat area: "Connecting to jcodemunch...", "Loading plugins..."
- `init` event marks CC as ready — show "Claude Code ready" status

### Pre-warmed Session Pool (PTY-03)
- Optional: keep one idle CC process running in background
- On first message, send to existing warm process instead of spawning new
- Idle process spawned at cc_chat_ws connection time (WS open), not at page load
- Timeout: kill idle process after 5 minutes of no messages
- Only one warm process per user (not per tab)

### WS Heartbeat Tolerance (PTY-05)
- Main dashboard WS heartbeat should not trigger page reload during CC init
- cc_chat_ws should send periodic keepalive during CC subprocess init
- Frontend should not show "disconnected" during normal CC startup delay

### Claude's Discretion
- PTY read loop implementation details (async reading from PTY fd)
- Error handling for partial NDJSON lines from PTY
- Whether pre-warm is on by default or opt-in via settings

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Existing PTY Implementation
- `dashboard/server.py` lines 1540-1610 — terminal WS winpty/pty pattern (copy this approach)

### CC Chat WS
- `dashboard/server.py` lines 1801-1990 — current cc_chat_ws with PIPE subprocess
- `dashboard/server.py` lines 1712-1795 — _parse_cc_event function

### Frontend Chat Panel
- `dashboard/frontend/dist/app.js` lines 3820-3940 — ideOpenCCChat, WS handlers

### CC CLI Output Format
- `system` events: hook_started, hook_response, init (with mcp_servers array)
- `stream_event` events: content_block_start, content_block_delta, content_block_stop
- `assistant` event: full response text (fallback for PIPE mode)
- `result` event: session_id, usage, cost

</canonical_refs>

<specifics>
## Specific Ideas

- The terminal WS already has working winpty code — adapt it for cc_chat_ws
- Node.js block-buffers stdout when piped (confirmed via async subprocess test)
- PTY gives line buffering, confirmed by terminal WS working correctly
- The `assistant` event fallback (committed in Phase 2 fixes) should remain as PTY-04 graceful degradation
- Pre-warm could use a `/ws/cc-chat` connection param like `?warm=true` to start process immediately

</specifics>

<deferred>
## Deferred Ideas

- Lazy MCP server loading (requires CC CLI changes, not in our control)
- CC CLI `--no-mcp` flag (if it exists in future versions)
- Multiple warm processes for power users with many tabs

</deferred>

---

*Phase: 05-streaming-pty-bridge-and-cc-initialization-optimization*
*Context gathered: 2026-03-18 from live debugging session*

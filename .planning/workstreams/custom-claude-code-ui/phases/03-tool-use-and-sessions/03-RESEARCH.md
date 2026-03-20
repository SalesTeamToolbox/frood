# Phase 3: Tool Use + Sessions - Research

**Researched:** 2026-03-18
**Domain:** Browser UI — collapsible tool cards, inline permission UI via custom MCP, sessionStorage-based session persistence, multi-tab CC sessions, session history sidebar
**Confidence:** HIGH (stack confirmed against live CC v2.1.77, official SDK docs, and existing codebase)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Tool card presentation (TOOL-01 through TOOL-05):**
- Inline collapsible cards appear in the chat flow between assistant text
- Cards are collapsed by default showing tool name + status icon (running/complete/error)
- Click to expand reveals input parameters and output result
- Live streaming: tool_delta events update the expanded card in real-time as tool runs
- File read/write tools: file path shown prominently at top, syntax-highlighted content preview (reuses highlight.js from Phase 2), truncated to ~30 lines with "Show more" expander
- Command/Bash tools: terminal-styled dark output block, command shown in monospace header, truncated to ~20 lines with expand. Visual language matches the terminal tab
- Error state: tool cards with `is_error: true` show red border/icon

**Permission request UX (TOOL-06):**
- Inline card with approve/reject buttons, highlighted styling (distinct from regular tool cards)
- Shows what CC wants to do (tool name, target file/command)
- CC subprocess blocks until user responds — no timeout, waits indefinitely
- Global session "Trust mode" toggle: auto-approves all permissions for the rest of the session
- Trust mode indicator visible in UI when active
- Permission response sent back to CC subprocess via stdin (research needed: verify exact CC permission protocol)

**Session persistence (SESS-01, SESS-02):**
- Active session ID stored in sessionStorage (per-tab, survives refresh within same tab)
- On page refresh: reconnect WS with same session_id query param, CC resumes via --resume
- Previous messages NOT re-rendered on reconnect — clean slate with "Session resumed" status message
- CC has full conversation context server-side; Agent42 only stores metadata

**Multi-session tabs (SESS-03):**
- Horizontal tab bar above the chat message area
- Each tab shows session title (first ~30 chars of first user message) with close button
- "+" button creates a new session
- Active tab highlighted, switching tabs swaps the chat area content
- Each tab maintains its own WS connection and session state

**Session history sidebar (SESS-04, SESS-05):**
- Existing session-sidebar scaffold from Phase 2 used as starting point
- Each entry shows: auto-generated title, relative timestamp ("2h ago"), first ~60 chars of last message as preview
- Grouped by Today / Yesterday / Older
- Clicking a session resumes it: chat clears, "Session resumed" status shown, CC uses --resume
- Data source: GET /api/cc/sessions — may need to extend metadata fields (preview text, message count)

**Token usage display (SESS-06):**
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

### Deferred Ideas (OUT OF SCOPE)
- Full message transcript storage and replay on session resume
- Per-tool-type auto-approve ("always allow Read this session")
- Cross-session cost tracking and daily/weekly summaries (ADV-02)
- Configurable --allowedTools per session
- @-mention file references in input (INPUT-05)
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| TOOL-01 | Tool invocations display as collapsible cards showing tool name and status (running/complete/error) | tool_start/tool_delta/tool_complete WS envelope schema verified; CSS details section |
| TOOL-02 | Tool cards show input parameters when expanded | tool_delta partial JSON accumulation pattern documented |
| TOOL-03 | Tool cards show output/result when expanded after completion | tool_complete.output verified as empty string (Phase 1 known issue); output comes from tool_result content block which is NOT currently relayed — architecture decision required |
| TOOL-04 | File read/write tools show file path prominently with syntax-highlighted content preview | highlight.js already loaded; file path from tool input JSON; output gap is the blocking issue for TOOL-04 |
| TOOL-05 | Command execution tools show the command and its output | Same output gap as TOOL-04; command is in input JSON |
| TOOL-06 | Permission requests display inline with approve/reject buttons | Permission protocol section documents the correct MCP-based approach; requires backend work |
| SESS-01 | Each CC conversation has a unique session ID tied to the CC process session | Already implemented — sessionId generated in ideOpenCCChat, sent as WS query param |
| SESS-02 | Session ID persists in sessionStorage so page navigation doesn't lose context | sessionStorage API pattern documented; requires storing/restoring sessionId on WS connect |
| SESS-03 | User can open multiple CC sessions as separate tabs | Multi-tab architecture section; requires tab strip UI + per-tab WS state |
| SESS-04 | Session history sidebar lists past conversations with timestamps and preview | GET /api/cc/sessions exists; backend needs preview_text field extension |
| SESS-05 | User can resume a past session from the history list | --resume pattern already works; requires sidebar click handler + WS resume flow |
| SESS-06 | Token usage display shows context window utilization per session | turn_complete already carries input_tokens/output_tokens; client-side accumulation pattern documented |
</phase_requirements>

---

## Summary

Phase 3 adds three distinct UI layers on top of the Phase 2 chat foundation: tool use visualization, inline permission handling, and session management. The Phase 2 backend already emits `tool_start`, `tool_delta`, and `tool_complete` WS envelopes — the frontend just needs to render them. The session persistence groundwork (session ID generation, WS session_id param, `_save_session`/`_load_session`, `GET /api/cc/sessions`) is all in place.

The most significant research finding concerns permission handling. The CC CLI in `--permission-mode default` shows permission prompts interactively in the terminal — there is **no native stream-json event** for permission requests. The correct approach for inline browser-based permission UI is `permission_prompt_tool_name` combined with a custom MCP tool registered with Agent42's MCP server. When CC needs a permission, it calls this MCP tool (which appears in the stream-json as a normal `tool_start`/`tool_complete` pair), the backend recognizes it as a permission request and emits a `permission_request` envelope, the frontend shows the inline card, and the user's response is sent back via WS to the backend which resolves the MCP tool call. This requires coordinated backend + MCP work and is the most complex task in this phase.

The second significant finding is that `tool_complete.output` is currently an empty string. Tool outputs (what CC reads/executes) are delivered as `tool_result` content blocks in the CC stream, but `_parse_cc_event` does not currently parse them. TOOL-03, TOOL-04, and TOOL-05 all require parsing `tool_result` blocks from the CC stream and emitting a new `tool_output` WS envelope or enriching `tool_complete`.

**Primary recommendation:** Implement in this order: (1) tool card rendering with empty output placeholders for TOOL-01/02, (2) `_parse_cc_event` expansion to relay tool_result content as `tool_output` events for TOOL-03/04/05, (3) session management features SESS-01 through SESS-06 (no backend blockers), (4) permission UI (most backend work).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| vanilla JS (ES5+) | N/A | All frontend — no framework | Established in Phase 2; consistent with existing code |
| Python / FastAPI | Existing | Backend WS and REST | Project standard |
| highlight.js | 11.11.1 | Syntax highlighting in tool cards | Already loaded via CDN in index.html |
| DOMPurify | 3.3.3 | Sanitize any tool output content | Already loaded; non-negotiable (CHAT-05) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| sessionStorage (browser built-in) | N/A | Session ID persistence across refresh | SESS-01/02 — no library needed |
| `requestAnimationFrame` (browser built-in) | N/A | Smooth card expand/collapse animations | Tool card transitions |
| aiofiles | Existing | Async session JSON writes | Extending `_save_session` with preview_text |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| vanilla JS tab strip | A tab component library | Library adds overhead; vanilla keeps it consistent with existing codebase |
| MCP tool for permissions | Stdin injection to CC process | Stdin approach is undocumented and fragile; MCP tool is the official CC extensibility mechanism |
| Extending tool_complete | New tool_output envelope | New envelope is cleaner (backward compatible); extending tool_complete risks breaking existing consumers |

**Installation:** No new packages required. All functionality uses existing project dependencies.

---

## Architecture Patterns

### Recommended Project Structure

No new files required. All changes to:
```
dashboard/
├── server.py                    # _parse_cc_event expansion + permission MCP tool
├── frontend/dist/app.js         # tool cards, tab strip, session sidebar, token bar
├── frontend/dist/style.css      # tool card CSS, tab strip CSS, token bar CSS
└── frontend/dist/index.html     # no changes needed (CDN deps already loaded)
tools/
└── cc_permission_tool.py        # NEW: MCP tool Agent42 registers for CC permission callbacks
tests/
└── test_cc_tool_use.py          # NEW: Wave 0 scaffold for Phase 3
```

### Pattern 1: Tool Card Lifecycle

**What:** A tool card is created on `tool_start`, updated live on `tool_delta` (JSON streaming for input), finalized on `tool_complete`, and enriched on `tool_output`.

**When to use:** For every tool invocation in the CC chat stream.

```javascript
// State per tab: Map<tool_id, {el, inputBuf, name, status}>
tab.toolCards = {};

// ws.onmessage additions:
case "tool_start":
  var card = ccCreateToolCard(tab, msgData.id, msgData.name);
  tab.toolCards[msgData.id] = { el: card, inputBuf: "", name: msgData.name, status: "running" };
  break;
case "tool_delta":
  var tc = tab.toolCards[msgData.id];
  if (tc) { tc.inputBuf += msgData.partial; }
  break;
case "tool_complete":
  var tc2 = tab.toolCards[msgData.id];
  if (tc2) {
    var parsed = {};
    try { parsed = JSON.parse(tc2.inputBuf); } catch(e) {}
    ccFinalizeToolCard(tc2.el, tc2.name, parsed, msgData.is_error);
    tc2.status = msgData.is_error ? "error" : "complete";
    delete tab.toolCards[msgData.id];  // remove from active map
  }
  break;
case "tool_output":
  // enriches a finalized card with result content
  ccSetToolOutput(msgData.id, msgData.content, msgData.content_type);
  break;
```

**Card DOM structure (collapsed default):**
```html
<div class="cc-tool-card cc-tool-running" data-tool-id="tu_abc123">
  <div class="cc-tool-header" onclick="ccToggleToolCard(this)">
    <span class="cc-tool-status-icon">⏳</span>
    <span class="cc-tool-name">Read</span>
    <span class="cc-tool-target">/src/main.py</span>
    <span class="cc-tool-chevron">▼</span>
  </div>
  <div class="cc-tool-body" style="display:none">
    <!-- input params + output once complete -->
  </div>
</div>
```

### Pattern 2: Tool Output via _parse_cc_event Expansion

**What:** CC emits `tool_result` content blocks in the stream after a tool runs. Currently `_parse_cc_event` ignores them. Phase 3 adds parsing.

**Stream-json event that carries tool output:**
```json
{
  "type": "stream_event",
  "event": {
    "type": "content_block_start",
    "index": 0,
    "content_block": {
      "type": "tool_result",
      "tool_use_id": "tu_abc123",
      "content": "file contents here..."
    }
  }
}
```
**Note:** Confidence is MEDIUM — this structure is inferred from SDK docs and the existing fixture file comment ("inferred from SDK docs"). The fixture at `tests/fixtures/cc_stream_sample.ndjson` line 15 shows this structure. Needs live session verification before implementing.

**New WS envelope to emit:**
```python
{
  "type": "tool_output",
  "data": {
    "id": "tu_abc123",          # matches tool_start id
    "content": "file contents here...",
    "content_type": "text"      # or "json" for structured output
  }
}
```

### Pattern 3: Permission Request via MCP Tool

**What:** The CC CLI in `--permission-mode default` uses the terminal interactively for permission prompts — there is no native stream-json permission event. The `permission_prompt_tool_name` CLI option configures CC to call a named MCP tool instead of showing a terminal prompt.

**The flow:**
1. Backend spawns CC with `--permission-prompt-tool-name mcp__agent42__cc_permission` added to args
2. Agent42's MCP server registers and serves a `cc_permission` tool
3. When CC needs permission, it calls `mcp__agent42__cc_permission` with `{tool_name, tool_input}`
4. The MCP tool handler blocks waiting for user response (stored in a per-session `asyncio.Event`)
5. Backend detects the `tool_start` for `mcp__agent42__cc_permission` and emits `permission_request` WS envelope
6. Frontend shows inline card; user clicks approve/reject
7. Frontend sends `{type: "permission_response", id: "tu_xxx", approved: true/false}` via WS
8. Backend receives the WS message, resolves the `asyncio.Event` with the decision
9. MCP tool handler returns `{"allow": true}` or `{"deny": true, "reason": "..."}`
10. CC gets the tool result and proceeds

**Trust mode:** When trust mode is active, step 6-8 are skipped — backend auto-approves without sending `permission_request` to frontend. Backend tracks trust mode per WS session.

**CC CLI args change (server.py):**
```python
args = [
    claude_bin,
    "-p", user_message,
    "--output-format", "stream-json",
    "--verbose",
    "--include-partial-messages",
    "--permission-prompt-tool-name", "mcp__agent42__cc_permission",
]
```
**Note:** `--permission-prompt-tool-name` flag existence confirmed from CC CLI help. The exact MCP call format (input schema, expected return format) requires verification — see Open Questions.

### Pattern 4: Session Persistence (sessionStorage)

**What:** Store session ID in `sessionStorage` so same-tab page refresh reconnects to the existing CC session.

```javascript
// On new session creation (ideOpenCCChat):
var sessionId = sessionStorage.getItem("cc_session_" + tabIdx)
  || crypto.randomUUID();
sessionStorage.setItem("cc_session_" + tabIdx, sessionId);

// On WS open (resume detected if cc_session_id was loaded from server):
if (sessionResumed) {
  var notice = document.createElement("div");
  notice.textContent = "Session resumed — context preserved";
  messagesDiv.appendChild(notice);
}
```

**Approach:** Since tabs are ephemeral (DOM-based, not URL-based), `sessionStorage` keyed by tab index is not reliable across refresh (tab index resets). Better approach: store a **single active session ID** in `sessionStorage` (not per-tab), restoring the most recent session on page load. This matches the locked decision: "session ID persists in sessionStorage so page navigation doesn't lose context."

```javascript
// Single session slot:
var sessionId = sessionStorage.getItem("cc_active_session") || crypto.randomUUID();
sessionStorage.setItem("cc_active_session", sessionId);
```

### Pattern 5: Token Bar Accumulation

**What:** Accumulate token counts client-side across turns within a session.

```javascript
// Tab state additions:
tab.totalInputTokens = 0;
tab.totalOutputTokens = 0;
tab.totalCostUsd = 0;

// On turn_complete:
tab.totalInputTokens += (msgData.input_tokens || 0);
tab.totalOutputTokens += (msgData.output_tokens || 0);
tab.totalCostUsd += (msgData.cost_usd || 0);
ccUpdateTokenBar(tab);

function ccUpdateTokenBar(tab) {
  var bar = document.getElementById("cc-token-bar-" + tab.tabIdx);
  if (!bar) return;
  bar.textContent = "In: " + ccFormatTokens(tab.totalInputTokens)
    + "  Out: " + ccFormatTokens(tab.totalOutputTokens)
    + "  Cost: $" + tab.totalCostUsd.toFixed(4);
}

function ccFormatTokens(n) {
  return n >= 1000 ? (n / 1000).toFixed(1) + "K" : String(n);
}
```

### Anti-Patterns to Avoid

- **Mutating tool input buffer directly on `tool_delta`**: buffer is a plain string of partial JSON. Do not attempt to parse partial JSON — only parse the complete buffer after `tool_complete`.
- **Blocking event loop for permission response**: The MCP tool must use `asyncio.Event` (non-blocking wait). Never use `time.sleep()` or `input()` in the MCP handler.
- **Re-rendering all messages on session resume**: locked decision explicitly prohibits this. Show "Session resumed" status only.
- **Storing session ID in localStorage instead of sessionStorage**: `localStorage` persists across all tabs; `sessionStorage` is per-tab. The locked decision requires per-tab isolation.
- **Directly emitting permission_request from tool_start for cc_permission tool**: the backend must filter out `mcp__agent42__cc_permission` tool_start/tool_complete from the regular tool card stream and route them to the permission_request envelope instead.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Syntax highlighting in tool output preview | Custom code highlighter | `hljs.highlight(code, {language: lang})` from existing Phase 2 CDN | highlight.js already loaded; handles 200+ languages with proper escaping |
| Relative timestamps ("2h ago") | Custom time formatter | Simple JS function with floor division | Simple enough to hand-roll; no library needed for this case |
| WS message type routing | Custom event bus | Extend existing switch in `ws.onmessage` | Pattern already established in Phase 2 |
| Session list sorted by time | Custom sort + grouping | `Array.sort` on `last_active_at` ISO string; group by date string comparison | Native sort on ISO strings works correctly |
| Blocking async wait for permission response | Threading or polling | `asyncio.Event` with `await event.wait()` | Python asyncio pattern for coroutine synchronization |

**Key insight:** The existing codebase has clear patterns for everything. All Phase 3 work is extending established patterns, not inventing new ones.

---

## Common Pitfalls

### Pitfall 1: tool_complete.output is Empty String
**What goes wrong:** Tool card tries to display output from `tool_complete.data.output` but it's always `""`. Cards show blank output panels.
**Why it happens:** `_parse_cc_event` emits `output: ""` in `tool_complete` because it never parses the subsequent `tool_result` content block from the CC stream. This was noted as an open issue in STATE.md.
**How to avoid:** Add `tool_result` parsing to `_parse_cc_event` and emit a new `tool_output` WS envelope. Tool cards must listen for `tool_output` events keyed by tool ID to populate the output panel.
**Warning signs:** Tool cards with empty output section even after CC has clearly read a file.

### Pitfall 2: Tool_delta Partial JSON Cannot Be Parsed Incrementally
**What goes wrong:** Code tries to JSON.parse the partial buffer on every `tool_delta`, fails with SyntaxError, swallows the error, and the tool card shows no input.
**Why it happens:** `input_json_delta` events contain partial JSON fragments that are not valid JSON by themselves. The CC stream sends them one key-value fragment at a time.
**How to avoid:** Accumulate all `tool_delta` partial strings into a buffer string. Only call `JSON.parse()` after `tool_complete` is received.
**Warning signs:** Console errors "SyntaxError: Unexpected end of JSON input" during streaming.

### Pitfall 3: Permission MCP Tool Blocks Event Loop
**What goes wrong:** Permission MCP tool handler uses synchronous blocking (sleep loop, `input()`) while waiting for user response. The entire WS server freezes.
**Why it happens:** FastAPI/asyncio runs on a single event loop. Any blocking call in a coroutine starves all other connections.
**How to avoid:** Use `asyncio.Event`. The MCP handler coroutine does `await permission_event.wait()`. The WS message handler calls `permission_event.set()` when user responds.
**Warning signs:** Dashboard becomes unresponsive while CC is waiting for permission.

### Pitfall 4: sessionStorage key collision across CC tab instances
**What goes wrong:** Two CC tabs created in the same page session use the same sessionStorage key, so one overwrites the other's session ID.
**Why it happens:** If the key is static (e.g., `"cc_active_session"`), tab 2 overwrites tab 1's session.
**How to avoid:** For multi-tab support (SESS-03), use per-tab keys (`"cc_session_" + wsSessionId`) OR store a list of active tab session IDs. Alternatively, keep the single active-session approach but acknowledge that only the most recent tab survives refresh.
**Warning signs:** After refresh, the wrong session is resumed (different context than expected).

### Pitfall 5: Detecting tool type for specialized card rendering (TOOL-04 vs TOOL-05)
**What goes wrong:** File tool cards show terminal-style output; Bash tool cards show syntax-highlighted file content. Tool types are swapped.
**Why it happens:** The tool `name` from `tool_start` is the canonical identifier. File tools: `Read`, `Write`, `Edit`, `Glob`, `Grep`. Bash tools: `Bash`. MCP tools have long names.
**How to avoid:** Define a `ccToolType(name)` helper that returns `"file"`, `"bash"`, or `"generic"` based on the tool name. Apply different card templates per type.
**Warning signs:** Wrong visual treatment for well-known tools.

### Pitfall 6: Permission tool name filtering must happen BEFORE tool_start relay
**What goes wrong:** The `mcp__agent42__cc_permission` tool appears in the stream as a regular tool_start, gets rendered as a tool card, AND ALSO triggers a permission_request card. Double UI elements appear.
**Why it happens:** `_parse_cc_event` doesn't know to filter the permission tool from normal tool relay.
**How to avoid:** Add a constant `CC_PERMISSION_TOOL = "mcp__agent42__cc_permission"` (or the configured tool name). In `_parse_cc_event`, when `tool_start` name matches this constant, emit `permission_request` instead of `tool_start`. When `tool_complete` matches, emit nothing (the permission was already handled).
**Warning signs:** Two cards appear when CC requests permission.

### Pitfall 7: WS is currently receive-only for CC events
**What goes wrong:** Frontend sends `{type: "permission_response", ...}` via WS but backend `asyncio.wait()` loop only handles `stop` message type. Permission response is silently dropped.
**Why it happens:** The current WS receive loop only checks for `type == "stop"`. All other messages are ignored.
**How to avoid:** Extend the WS receive loop in `cc_chat_ws` to also handle `type == "permission_response"`. Route it to the per-session permission event resolver.
**Warning signs:** CC blocks indefinitely after user clicks approve/reject.

---

## Code Examples

Verified patterns from official sources and live codebase inspection:

### Live CC stream-json event structure (verified against CC v2.1.77)
```json
// system init (confirmed live):
{"type":"system","subtype":"init","cwd":"...","session_id":"<uuid>","tools":[...],"permissionMode":"default"}

// tool_use content_block_start (confirmed from _parse_cc_event and fixture):
{"type":"stream_event","event":{"type":"content_block_start","index":1,"content_block":{"type":"tool_use","id":"tu_abc123","name":"Read","input":{}}}}

// input_json_delta (confirmed from _parse_cc_event and fixture):
{"type":"stream_event","event":{"type":"content_block_delta","index":1,"delta":{"type":"input_json_delta","partial_json":"{\"file_path\":"}}}

// tool_result (inferred from SDK docs + fixture — MEDIUM confidence):
{"type":"stream_event","event":{"type":"content_block_start","index":0,"content_block":{"type":"tool_result","tool_use_id":"tu_abc123","content":"file content here"}}}

// result (confirmed live):
{"type":"result","subtype":"success","session_id":"<uuid>","cost_usd":0.0042,"usage":{"input_tokens":150,"output_tokens":45},"total_cost":0.0042}
```

### Session metadata extension (backend _save_session)
```python
# Current (Phase 1):
{
    "ws_session_id": ws_session_id,
    "cc_session_id": session_state.get("cc_session_id"),
    "created_at": created_at,
    "last_active_at": datetime.datetime.utcnow().isoformat(),
    "title": session_title,
}

# Phase 3 extension needed:
{
    "ws_session_id": ws_session_id,
    "cc_session_id": session_state.get("cc_session_id"),
    "created_at": created_at,
    "last_active_at": datetime.datetime.utcnow().isoformat(),
    "title": session_title,
    "preview_text": last_assistant_text[:60],   # NEW: for SESS-04
    "message_count": session_state.get("message_count", 0),  # NEW
}
```

### Relative timestamp function (no library needed)
```javascript
function ccRelativeTime(isoString) {
  var now = Date.now();
  var then = new Date(isoString).getTime();
  var diff = Math.floor((now - then) / 1000);
  if (diff < 60) return "just now";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  if (diff < 172800) return "yesterday";
  return Math.floor(diff / 86400) + "d ago";
}
```

### Permission request MCP tool skeleton (server.py)
```python
# In cc_chat_ws closure, per-session state:
session_state["permission_events"] = {}  # tool_id -> asyncio.Event
session_state["permission_results"] = {}  # tool_id -> bool

# WS receive loop addition (alongside "stop" handler):
if inner.get("type") == "permission_response":
    perm_id = inner.get("id")
    approved = inner.get("approved", False)
    session_state["permission_results"][perm_id] = approved
    evt = session_state["permission_events"].get(perm_id)
    if evt:
        evt.set()
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| CC permission via terminal stdin/stdout | `--permission-prompt-tool-name` MCP tool | CC SDK v2.x | Enables programmatic permission handling without process stdin manipulation |
| SDK-level `canUseTool` callback | `PermissionRequest` hook + `--permission-prompt-tool-name` CLI option | Current CC v2.1.77 | Both mechanisms exist; CLI option is the right one for Agent42's process-spawn architecture |
| Static `session-sidebar` scaffold | Rich sidebar with metadata, grouping, preview | Phase 3 | Enables session history navigation per SESS-04/05 |

**Deprecated/outdated:**
- Stdin injection to CC process for permission responses: undocumented, fragile, bypasses CC's permission system.
- `canUseTool` SDK callback: SDK-level only, not available when invoking CC CLI as a subprocess.

---

## Open Questions

1. **`--permission-prompt-tool-name` exact input/output schema**
   - What we know: Flag exists in CC CLI v2.1.77 (`claude --help` confirmed). CC calls a named MCP tool when permission is needed.
   - What's unclear: Exact JSON input schema CC passes to the MCP tool (likely `{tool_name, tool_input, description}` but not verified from live session). Exact return schema the MCP tool must return to allow/deny.
   - Recommendation: Before implementing TOOL-06, run a test with `--permission-prompt-tool-name` pointing to a logging MCP tool and capture the exact input payload from a live CC session that would normally ask permission.

2. **`tool_result` content block structure in stream-json**
   - What we know: CC stream emits `content_block_start` events with `type: "tool_result"` after a tool runs. The fixture at `tests/fixtures/cc_stream_sample.ndjson` shows `{"type":"content_block_start","index":0,"content_block":{"type":"tool_result","tool_use_id":"tu_abc123","content":"..."}}`. The fixture comment says "inferred from SDK docs."
   - What's unclear: Whether `content` is always a plain string or sometimes an array. Whether large outputs are streamed as `content_block_delta` fragments. Whether this event appears for all tools or only some.
   - Recommendation: Run `claude -p "read a small file" --output-format stream-json --verbose --include-partial-messages` and capture the full output to verify `tool_result` structure.

3. **Multi-session tab sessionStorage strategy**
   - What we know: `sessionStorage` is per-tab, survives refresh, isolated from other tabs.
   - What's unclear: The locked decision says session ID persists in `sessionStorage` but also supports multi-session tabs (SESS-03). These are in tension — a single `sessionStorage["cc_active_session"]` only holds one ID.
   - Recommendation: For the primary tab (the first/only session), use `sessionStorage["cc_active_session"]`. For additional tabs opened within the same page session, they are ephemeral (no refresh recovery needed since they were opened by user action). If refresh recovery for all tabs is needed, store a JSON array of session IDs in sessionStorage.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (asyncio_mode = "auto") |
| Config file | `pyproject.toml` |
| Quick run command | `python -m pytest tests/test_cc_tool_use.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| TOOL-01 | Tool card created on tool_start event | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_tool_card_created_on_tool_start -x` | ❌ Wave 0 |
| TOOL-02 | Tool card input populated from tool_delta accumulation | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_tool_card_input_from_delta -x` | ❌ Wave 0 |
| TOOL-03 | tool_output WS envelope emitted from tool_result event | unit (_parse_cc_event) | `pytest tests/test_cc_tool_use.py::TestParseToolResult::test_tool_result_emits_tool_output -x` | ❌ Wave 0 |
| TOOL-04 | File tool card shows file path prominently | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_file_tool_card_shows_path -x` | ❌ Wave 0 |
| TOOL-05 | Bash tool card shows command | unit (source inspection) | `pytest tests/test_cc_tool_use.py::TestToolCards::test_bash_tool_card_shows_command -x` | ❌ Wave 0 |
| TOOL-06 | permission_request WS envelope emitted for cc_permission tool_start | unit (_parse_cc_event) | `pytest tests/test_cc_tool_use.py::TestPermissionRequest::test_permission_tool_emits_permission_request -x` | ❌ Wave 0 |
| SESS-01 | Session ID present in WS URL query param | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionPersistence::test_session_id_in_ws_url -x` | ❌ Wave 0 |
| SESS-02 | sessionStorage.setItem called for session ID | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionPersistence::test_session_id_stored_in_session_storage -x` | ❌ Wave 0 |
| SESS-03 | Tab strip rendered with + button for new session | source inspection | `pytest tests/test_cc_tool_use.py::TestMultiSessionTabs::test_tab_strip_rendered -x` | ❌ Wave 0 |
| SESS-04 | Session history sidebar populated from GET /api/cc/sessions | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionSidebar::test_sidebar_loads_sessions -x` | ❌ Wave 0 |
| SESS-05 | Clicking session in sidebar resumes via --resume | source inspection | `pytest tests/test_cc_tool_use.py::TestSessionSidebar::test_sidebar_click_resumes -x` | ❌ Wave 0 |
| SESS-06 | Token bar shows accumulated tokens from turn_complete | source inspection | `pytest tests/test_cc_tool_use.py::TestTokenBar::test_token_bar_rendered -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_cc_tool_use.py tests/test_cc_bridge.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_cc_tool_use.py` — covers TOOL-01 through TOOL-06, SESS-01 through SESS-06 (all 12 requirements)
- [ ] `tests/fixtures/cc_tool_result_sample.ndjson` — live-verified tool_result event fixture (needed for TOOL-03 unit test)
- [ ] Framework install: already installed — `python -m pytest tests/ -x -q` passes (32 pass, 10 xfail, 12 xpass)

---

## Sources

### Primary (HIGH confidence)
- Live CC v2.1.77 stream-json output — system/init event structure, hook events, result event structure verified from actual subprocess output
- `dashboard/server.py` lines 1905-2004 — `_parse_cc_event` full implementation, WS envelope schemas for tool_start/tool_delta/tool_complete/turn_complete
- `dashboard/server.py` lines 2025-2403 — `cc_chat_ws` full implementation, session lifecycle
- `dashboard/frontend/dist/app.js` lines 3737-3961 — `ideOpenCCChat` full implementation, Phase 2 WS patterns
- `tests/fixtures/cc_stream_sample.ndjson` — existing NDJSON fixture with tool use event sequence
- Claude Code CLI `--help` output (v2.1.77) — confirmed `--permission-prompt-tool-name` flag exists
- https://platform.claude.com/docs/en/agent-sdk/user-input — canUseTool callback pattern, permission flow architecture
- https://platform.claude.com/docs/en/agent-sdk/hooks — PermissionRequest hook, available hooks table, hook event names

### Secondary (MEDIUM confidence)
- https://platform.claude.com/docs/en/agent-sdk/permissions — permission modes reference, bypassPermissions behavior
- `tests/fixtures/cc_stream_sample.ndjson` line 15 comment: "tool_result content block structure is inferred from SDK docs" — fixture author flagged as MEDIUM confidence
- Context7 /anthropics/claude-code-sdk-python — canUseTool callback code examples, PermissionResultAllow/Deny pattern

### Tertiary (LOW confidence)
- `--permission-prompt-tool-name` MCP tool input/output schema — flag existence confirmed but exact JSON schema NOT verified from live CC session. Requires empirical verification before TOOL-06 implementation.
- `tool_result` content block appearing as `content_block_start` in stream — structurally consistent with CC SDK docs but fixture comment flags as inferred, not observed from live session.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all existing project dependencies, no new packages
- Architecture: HIGH for tool cards, session management; MEDIUM for permission MCP tool (exact input schema not yet verified)
- Pitfalls: HIGH — derived from live codebase analysis and STATE.md documented concerns

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable — CC CLI version pinned to v2.1.77; verify if upgraded)

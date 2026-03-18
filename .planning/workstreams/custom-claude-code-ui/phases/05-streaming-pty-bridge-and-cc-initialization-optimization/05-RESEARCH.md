# Phase 05: Streaming PTY Bridge & CC Initialization Optimization - Research

**Researched:** 2026-03-18
**Domain:** Python asyncio + winpty/pty subprocess, NDJSON line buffering from PTY, pre-warm session pool, WebSocket keepalive
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**PTY Subprocess (PTY-01, PTY-04):**
- Use winpty on Windows (already a dependency — terminal WS uses it)
- Use pty module on Unix (stdlib)
- cc_chat_ws should mirror the terminal WS's PTY setup pattern (lines 1540-1610 in server.py)
- If winpty/pty unavailable, fall back to current PIPE + `assistant` event extraction (PTY-04)
- NDJSON parsing must handle partial lines from PTY (buffered differently than PIPE)

**Initialization Progress (PTY-02):**
- Parse `system` events (hook_started, hook_response, init) and relay as `status` messages
- Show MCP server connection status from `init` event's `mcp_servers` array
- Frontend shows italicized status messages in chat area: "Connecting to jcodemunch...", "Loading plugins..."
- `init` event marks CC as ready — show "Claude Code ready" status

**Pre-warmed Session Pool (PTY-03):**
- Optional: keep one idle CC process running in background
- On first message, send to existing warm process instead of spawning new
- Idle process spawned at cc_chat_ws connection time (WS open), not at page load
- Timeout: kill idle process after 5 minutes of no messages
- Only one warm process per user (not per tab)

**WS Heartbeat Tolerance (PTY-05):**
- Main dashboard WS heartbeat should not trigger page reload during CC init
- cc_chat_ws should send periodic keepalive during CC subprocess init
- Frontend should not show "disconnected" during normal CC startup delay

### Claude's Discretion

- PTY read loop implementation details (async reading from PTY fd)
- Error handling for partial NDJSON lines from PTY
- Whether pre-warm is on by default or opt-in via settings

### Deferred Ideas (OUT OF SCOPE)

- Lazy MCP server loading (requires CC CLI changes, not in our control)
- CC CLI `--no-mcp` flag (if it exists in future versions)
- Multiple warm processes for power users with many tabs
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| PTY-01 | CC subprocess uses winpty (Windows) / pty (Unix) instead of PIPE — enabling line-buffered stdout and real-time `stream_event` delta delivery | winpty already installed (`pywinpty>=2.0.0`), pattern exists at server.py lines 1540-1610. `PtyProcess.readline()` gives per-line blocking read wrapped with `run_in_executor` |
| PTY-02 | Initialization progress relayed to frontend — system events (hook_started, MCP server connecting) shown as status messages during the ~50s CC cold start | `_parse_cc_event` already handles `system/init`; needs expansion for `hook_started`, `hook_response`, and `mcp_servers` array; frontend `status` message type already renders italicized |
| PTY-03 | Pre-warmed CC session pool — keep one idle CC process ready so first message response is near-instant (no MCP init delay) | New `_cc_warm_pool` dict scoped inside `create_app()`, key=user, value=`{proc, session_id, pty_process, spawned_at, last_used}`; asyncio background task for timeout; WS-open param `?warm=true` triggers pre-spawn |
| PTY-04 | Graceful degradation — if winpty unavailable, fall back to PIPE with `assistant` event text extraction (current behavior) | Current `cc_chat_ws` PIPE + `assistant` event fallback already committed in Phase 2 fixes; PTY-04 means preserving this path when winpty import fails |
| PTY-05 | WS heartbeat tolerance — cc_chat_ws keeps connection alive during long CC init without triggering page reload | cc_chat_ws sends `{"type": "keepalive"}` every 15s during init; frontend cc-chat `ws.onmessage` already ignores unknown types (no action needed); main `/ws` reconnects with backoff, does not page-reload |
</phase_requirements>

---

## Summary

Phase 5 addresses two confirmed root causes: (1) Node.js block-buffers stdout when connected to a PIPE, preventing real-time `stream_event` delta delivery; (2) CC's ~50s cold start due to initializing 12+ MCP servers. The fix for (1) replaces `asyncio.create_subprocess_exec` PIPE stdout with a PTY subprocess — winpty on Windows, pty on Unix — which forces Node.js into line-buffered mode. The fix for (2) is a pre-warm pool that spawns one idle CC process per user at WS-open time.

The key implementation pattern is already proven: `dashboard/server.py` lines 1540-1610 show the winpty/pty setup for the terminal WS. The CC bridge (lines 1814-2016) will adopt the same PTY setup with one critical difference — instead of relaying raw terminal bytes, it must accumulate PTY output into a line buffer and parse NDJSON. `PtyProcess.readline()` exists and is the correct method for this; it blocks until `\n`, so it must be called via `loop.run_in_executor(None, pty_process.readline)`.

The pre-warm pool is a `dict` scoped inside `create_app()` (following the closure-scoped helper pattern established in Phase 1). Each user gets at most one warm process. The background idle-timeout task uses `asyncio.create_task` with a `asyncio.sleep(5*60)` loop, killing processes that haven't been claimed within 5 minutes.

**Primary recommendation:** Add PTY-based read loop to `cc_chat_ws`, implement `_cc_warm_pool`, expand `_parse_cc_event` for system events, and add frontend keepalive tolerance. All changes live in `dashboard/server.py` and `dashboard/frontend/dist/app.js`.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `winpty.PtyProcess` | `pywinpty>=2.0.0` | Windows PTY subprocess, readline, terminate | Already in requirements.txt, already used at line 1543 |
| `pty` (stdlib) | stdlib | Unix PTY fork, master/slave fd | Already used at line 1548 |
| `select` (stdlib) | stdlib | Unix PTY fd readiness check | Already used at line 1611 |
| `asyncio.get_event_loop().run_in_executor` | stdlib | Wrap blocking PTY reads as async | Already used at line 1573 (winpty) and line 1623 (Unix) |
| `asyncio.create_task` | stdlib | Background keepalive and idle timeout | Already used throughout server.py |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio.sleep` | stdlib | Idle timeout loop in pre-warm pool | 5-minute idle TTL per warm process |
| `time.monotonic` | stdlib | Track last-used timestamp for idle timeout | Avoids datetime for performance measurement |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `PtyProcess.readline()` | `PtyProcess.read(4096)` + manual line split | `readline()` is simpler and ensures complete NDJSON lines; `read()` requires an accumulation buffer |
| `asyncio.get_event_loop().run_in_executor` | `asyncio.to_thread` | `to_thread` requires Python 3.9+; project already uses `run_in_executor` in this file |
| Pre-warm spawned at WS-open | Pre-warm spawned at page load | WS-open matches the locked decision; page-load pre-warm requires a separate non-auth'd HTTP endpoint |

**Installation:** No new dependencies. `pywinpty` is already in requirements.txt with the Windows-platform guard.

---

## Architecture Patterns

### Recommended Project Structure

```
dashboard/
  server.py
    create_app() closure scope:
      _cc_warm_pool = {}            # NEW: {user: WarmEntry}
      _parse_cc_event()             # MODIFY: add hook_started, hook_response, mcp_servers
      cc_chat_ws()                  # MODIFY: PTY setup + warm pool integration
      _cc_prewarm_idle_task()       # NEW: async background cleanup task
```

No new files required. All changes are in `dashboard/server.py` and `dashboard/frontend/dist/app.js`.

### Pattern 1: PTY Read Loop for NDJSON (Windows)

**What:** Use `PtyProcess.readline()` wrapped in `run_in_executor` to read NDJSON lines one at a time.
**When to use:** When `winpty` import succeeds on Windows.

```python
# Source: adapted from server.py lines 1566-1582 + winpty.PtyProcess.readline() API
from winpty import PtyProcess

pty_process = PtyProcess.spawn(
    args,  # Full command list including user_message
    cwd=str(workspace),
)

loop = asyncio.get_event_loop()

async def _read_pty_win_ndjson():
    line_buf = ""
    try:
        while pty_process.isalive():
            try:
                # readline() blocks until \n — must be run in executor
                line = await loop.run_in_executor(None, pty_process.readline)
            except EOFError:
                break
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue  # PTY may emit ANSI escape sequences; skip non-JSON
            envelopes = _parse_cc_event(event, tool_id_map, session_state)
            for envelope in envelopes:
                await websocket.send_json(envelope)
    except Exception:
        pass
```

**Key difference from terminal WS:** Terminal WS relays raw bytes to xterm.js. CC PTY must parse NDJSON, so `readline()` per line is correct instead of `read(4096)`.

### Pattern 2: PTY Spawn with NDJSON Args (Windows)

**What:** `PtyProcess.spawn` takes an `argv` list (same as `asyncio.create_subprocess_exec` args).
**Critical:** The CC command args list already contains the user message as `-p <message>`. No stdin write needed.

```python
# Source: winpty.PtyProcess.spawn(argv, cwd=None, env=None, dimensions=(24, 80))
pty_process = PtyProcess.spawn(
    args,  # [claude_bin, "-p", user_message, "--output-format", "stream-json", ...]
    cwd=str(workspace),
    dimensions=(24, 220),  # Wide terminal so long JSON lines are not word-wrapped
)
```

**Pitfall:** Default dimensions (24, 80) may word-wrap long NDJSON lines at column 80, corrupting the JSON. Use wide dimensions like (24, 220).

### Pattern 3: PTY Setup for Unix (pty module)

**What:** Use `pty.openpty()` + `subprocess.Popen` with slave fd, read from master fd with `select`.
**When to use:** Non-Windows platform.

```python
# Source: server.py lines 1547-1561 + 1610-1656 (terminal WS Unix pattern)
import pty as _pty_mod
import subprocess as _subprocess_pty
import select as _select

master_fd, slave_fd = _pty_mod.openpty()
proc = _subprocess_pty.Popen(
    args,
    stdin=slave_fd,
    stdout=slave_fd,
    stderr=slave_fd,
    cwd=str(workspace),
    preexec_fn=os.setsid,
)
os.close(slave_fd)

# NDJSON read loop: accumulate chunks into line buffer
line_buf = ""

def _read_chunk():
    if select.select([master_fd], [], [], 0.1)[0]:
        return os.read(master_fd, 4096).decode("utf-8", errors="replace")
    return ""

async def _read_pty_unix_ndjson():
    nonlocal line_buf
    try:
        while proc.poll() is None:
            chunk = await loop.run_in_executor(None, _read_chunk)
            if chunk:
                line_buf += chunk
                while "\n" in line_buf:
                    line, line_buf = line_buf.split("\n", 1)
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    envelopes = _parse_cc_event(event, tool_id_map, session_state)
                    for envelope in envelopes:
                        await websocket.send_json(envelope)
            else:
                await asyncio.sleep(0.05)
    except Exception:
        pass
```

### Pattern 4: Pre-Warm Pool

**What:** A dict scoped inside `create_app()` stores one warm CC process per user. On WS open (when `?warm=true`), a fresh CC process is spawned so its ~50s init completes before the user sends a message.
**When to use:** Client connects with `?warm=true`. On first user message, check pool for a live warm process before spawning fresh.

```python
# Source: closure-scoped helper pattern from Phase 1 (_parse_cc_event, _save_session, _load_session)

# Warm pool entry structure
# {
#   "pty_process": PtyProcess | None,  # winpty
#   "proc": asyncio.Process | None,    # PIPE fallback
#   "master_fd": int | None,           # Unix PTY
#   "cc_session_id": str | None,       # None until init event received
#   "spawned_at": float,               # monotonic timestamp
#   "last_used": float,                # monotonic timestamp for idle timeout
#   "ready": bool,                     # True after init event received
# }
_cc_warm_pool: dict = {}  # key: username

async def _cc_spawn_warm(user: str):
    """Spawn a CC process with no user message (warm-up only).

    Uses 'claude --output-format stream-json --verbose --include-partial-messages'
    with no -p flag — CC will initialize and wait for input.
    Note: CC requires -p for print mode; warm spawn may need a sentinel query.
    """
    ...
```

**Important constraint:** CC `-p` mode (print mode) exits after one response. A warm CC process cannot simply idle — it must receive a message to start. The pre-warm optimization applies to the initialization time before the first message is actually sent. The warm process is spawned with a lightweight "sentinel" first message (e.g., `"init"`) that causes CC to initialize all MCP servers. When the user sends their real first message, CC responds immediately because MCP servers are already loaded. Alternatively, the session_id from the warm sentinel can be used with `--resume` for the actual user message.

**Revised pre-warm model:** Warm process sends a no-op message like `"."` at connection time. CC initializes (50s), responds, and the `result` event yields a `session_id`. When the user's real first message arrives, the backend uses `--resume <warm_session_id>` — CC starts near-instantly because no MCP init is needed.

### Pattern 5: Expanded _parse_cc_event for Init Progress

**What:** Emit `status` WS envelopes for CC system events during the ~50s init.
**When to use:** Every `system` event received from CC PTY output.

```python
# Source: Current server.py lines 1721-1723 + CC stream-json event schema
if etype == "system":
    subtype = event.get("subtype", "")
    if subtype == "init":
        # Relay MCP server names as connecting status
        mcp_servers = event.get("mcp_servers", [])
        for srv in mcp_servers:
            srv_name = srv.get("name", "") if isinstance(srv, dict) else str(srv)
            if srv_name:
                envelopes.append({
                    "type": "status",
                    "data": {"message": f"Connected to {srv_name}"}
                })
        envelopes.append({
            "type": "status",
            "data": {"message": "Claude Code ready"}
        })
    elif subtype == "hook_started":
        hook_name = event.get("hook_name", event.get("name", ""))
        if hook_name:
            envelopes.append({
                "type": "status",
                "data": {"message": f"Loading {hook_name}..."}
            })
    elif subtype == "hook_response":
        pass  # Suppress individual hook responses — too verbose
```

**Note on mcp_servers array structure:** CC's `init` event `mcp_servers` array structure is not fully verified from live capture. Based on CC SDK documentation, each entry is an object with at least `name` and `status` fields. The code above handles both dict entries and string entries defensively.

### Pattern 6: Keepalive During CC Init (PTY-05)

**What:** cc_chat_ws sends `{"type": "keepalive"}` every 15s while CC subprocess is running, preventing WS timeout.

```python
# Source: asyncio.create_task pattern used throughout server.py
async def _send_keepalive():
    try:
        while True:
            await asyncio.sleep(15)
            if websocket.client_state.value == 1:  # CONNECTED
                await websocket.send_json({"type": "keepalive"})
    except Exception:
        pass

keepalive_task = asyncio.create_task(_send_keepalive())
# Cancel keepalive_task in the finally block after subprocess exits
```

**Frontend handling:** The `ws.onmessage` handler in `ideOpenCCChat` already uses `if/else if` chains and falls through silently for unknown message types. No frontend change needed for `keepalive` — it is a no-op on the client. The existing `ws.onclose` handler does not force a page reload; it calls `ccSetSendingState(tab, false)` which is safe.

### Anti-Patterns to Avoid

- **Using `PtyProcess.read(4096)` for NDJSON:** Returns partial chunks, requires manual line accumulation. Use `readline()` instead on Windows.
- **Default PTY dimensions (24, 80):** Word-wraps long NDJSON lines, corrupting JSON. Use (24, 220) or larger.
- **Spawning warm process at page load:** Requires a non-authenticated startup hook. Spawn at WS-open time (authenticated context).
- **One warm process per tab:** The locked decision is one per user. Multiple tabs share the warm session pool.
- **Blocking readline without run_in_executor:** `PtyProcess.readline()` blocks the thread. Always wrap with `loop.run_in_executor(None, ...)`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Windows PTY | Custom Windows IOCP async subprocess | `winpty.PtyProcess` + `run_in_executor` | PTY already implemented in terminal WS; reuse pattern directly |
| Unix PTY | Custom pty fd event loop | `pty.openpty()` + `select` + `run_in_executor` | Already proven at lines 1610-1656 |
| NDJSON line accumulation (Unix) | Complex stream parser | Simple `line_buf.split("\n", 1)` loop | PTY delivers text in arbitrary chunks; newline split is sufficient |
| Idle timeout | Complex scheduler | `asyncio.sleep(300)` in background task | Monotonic timestamp comparison is enough; no need for a task scheduler |

**Key insight:** The PTY implementation is already solved in this codebase. The only new problem is adapting it to emit parsed NDJSON envelopes instead of raw terminal bytes.

---

## Common Pitfalls

### Pitfall 1: PTY Column Width Truncates NDJSON Lines
**What goes wrong:** CC emits NDJSON lines that can be 1000+ characters (tool input JSON). A PTY with default 80-column width wraps those lines, inserting `\r\n` mid-JSON. `json.loads()` fails on partial lines.
**Why it happens:** PTY emulates a terminal; the process believes it has an 80-column screen and wraps long output lines.
**How to avoid:** Spawn with `dimensions=(24, 220)` or larger. 220 columns is enough for typical NDJSON events. For safety, strip ANSI escape codes (`\x1b[...m`) before parsing, and handle `json.JSONDecodeError` by accumulating into a line buffer.
**Warning signs:** `json.JSONDecodeError` on lines that look like partial JSON; ANSI color codes interspersed in output.

### Pitfall 2: EOF on PtyProcess.readline() Not Signaling Loop Exit
**What goes wrong:** `pty_process.readline()` raises `EOFError` when the process exits. If not caught, the `run_in_executor` future raises and the read loop exits silently, leaving the WS hanging.
**Why it happens:** `PtyProcess.readline()` source shows it catches EOF during char-by-char read and returns accumulated chars — but if the terminal closes mid-read, `read(1)` raises `EOFError`. The outer caller must catch this.
**How to avoid:** Wrap the `await loop.run_in_executor(None, pty_process.readline)` call in `try/except EOFError` and break the loop.

### Pitfall 3: Pre-Warm CC Session Not Resumable
**What goes wrong:** The warm process completes its sentinel message, CC exits (print mode exits after one response). The warm process is dead by the time the user sends a real message.
**Why it happens:** `claude -p` (print mode) exits after generating one response.
**How to avoid:** Use `--resume <sentinel_session_id>` for the real user message — this spawns a new CC process but skips MCP re-initialization because CC recognizes the existing session. The pre-warm benefit is that the MCP servers were already loaded in the sentinel run; `--resume` lets CC skip re-connecting to them.
**Warning signs:** `result` event received from warm process; process `returncode != None` before user sends first message.

### Pitfall 4: Unix PTY fd Not Closed After Use
**What goes wrong:** `os.close(slave_fd)` already in pattern, but `master_fd` not closed in finally block causes fd leak.
**Why it happens:** Exception paths exit before the finally block can close `master_fd`.
**How to avoid:** In the finally block: `try: os.close(master_fd); except OSError: pass`. Copy the pattern at line 1654.

### Pitfall 5: Keepalive Task Not Cancelled
**What goes wrong:** `keepalive_task` outlives the subprocess. It continues sending on a closed WS, generating `WebSocketDisconnect` exceptions in a tight loop.
**Why it happens:** Missing `keepalive_task.cancel()` in the finally block.
**How to avoid:** Add `keepalive_task.cancel()` alongside `read_task.cancel()` in the finally block.

### Pitfall 6: ANSI Escape Codes in PTY Output
**What goes wrong:** CC may emit ANSI color codes (e.g., `\x1b[32m`) in its status output. These appear before or within NDJSON lines, breaking `json.loads()`.
**Why it happens:** CC detects a PTY and enables colored output. PIPE mode suppresses ANSI codes; PTY mode does not.
**How to avoid:** Strip ANSI escape codes from each line before parsing:
```python
import re
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[mGKHF]')
clean_line = ANSI_ESCAPE.sub('', line).strip()
```

---

## Code Examples

Verified patterns from existing codebase:

### PtyProcess.spawn + readline (Windows)

```python
# Source: server.py line 1543-1546 (spawn) + winpty source (readline)
from winpty import PtyProcess

pty_process = PtyProcess.spawn(
    args,               # list: [claude_bin, "-p", msg, "--output-format", "stream-json", ...]
    cwd=str(workspace),
    dimensions=(24, 220),  # Wide to prevent NDJSON line wrap
)

# readline() — blocking, returns str, raises EOFError on close
loop = asyncio.get_event_loop()
try:
    line = await loop.run_in_executor(None, pty_process.readline)
except EOFError:
    break  # Process exited
```

### Terminate Pattern (Windows)

```python
# Source: server.py line 1607-1608
if pty_process.isalive():
    pty_process.terminate()
```

### Unix PTY with Line Accumulation Buffer

```python
# Source: server.py lines 1610-1656 (read pattern) + NDJSON accumulation
line_buf = ""
ANSI_ESCAPE = re.compile(r'\x1b\[[0-9;]*[mGKHF]')

def _read_chunk():
    if select.select([master_fd], [], [], 0.1)[0]:
        return os.read(master_fd, 4096).decode("utf-8", errors="replace")
    return ""

while proc.poll() is None:
    chunk = await loop.run_in_executor(None, _read_chunk)
    if chunk:
        line_buf += chunk
        while "\n" in line_buf:
            raw_line, line_buf = line_buf.split("\n", 1)
            line = ANSI_ESCAPE.sub("", raw_line).strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                continue
            for envelope in _parse_cc_event(event, tool_id_map, session_state):
                await websocket.send_json(envelope)
    else:
        await asyncio.sleep(0.05)
```

### Expanded System Event Handling in _parse_cc_event

```python
# Source: server.py line 1721-1723 (current minimal handling) — expand to:
if etype == "system":
    subtype = event.get("subtype", "")
    if subtype == "init":
        mcp_servers = event.get("mcp_servers", [])
        for srv in mcp_servers:
            srv_name = (srv.get("name", "") if isinstance(srv, dict) else str(srv)).strip()
            if srv_name:
                envelopes.append({"type": "status", "data": {"message": f"Connected to {srv_name}"}})
        envelopes.append({"type": "status", "data": {"message": "Claude Code ready"}})
    elif subtype == "hook_started":
        name = event.get("hook_name") or event.get("name") or ""
        if name:
            envelopes.append({"type": "status", "data": {"message": f"Loading {name}..."}})
    # hook_response: suppress (too verbose)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| PIPE stdout (block-buffered) | PTY stdout (line-buffered) | Phase 5 | stream_event deltas delivered in real-time |
| Full response at turn end | Incremental text_delta stream | Phase 5 | Streaming UX, cursor visible during generation |
| Cold start every session | Pre-warm pool (one per user) | Phase 5 | First response ~instant instead of ~50s |
| Silent init delay | Init progress status messages | Phase 5 | User sees "Connecting to jcodemunch..." instead of blank wait |

**Deprecated/outdated:**
- `assistant` event as primary text source: remains as PTY-04 fallback only; PTY mode uses `stream_event` deltas.

---

## Open Questions

1. **CC `mcp_servers` array exact schema**
   - What we know: CC `init` event includes `mcp_servers` field. Each entry has at least a `name` field.
   - What's unclear: Is it `[{name, status, error}, ...]` or `[{name, type, ...}, ...]`? The fixture file uses `"tools": []` but not `mcp_servers`.
   - Recommendation: Add defensive `isinstance(srv, dict)` check. The status message degrades gracefully to an empty list if the field is absent or has unexpected structure. Verify against a live CC run with `--verbose` during Wave 0.

2. **Pre-warm sentinel message**
   - What we know: `claude -p <msg>` exits after generating one response. `--resume <session_id>` reuses an existing session directory, skipping MCP re-init.
   - What's unclear: Does `--resume` actually skip MCP initialization? Or does it re-load all MCP servers regardless?
   - Recommendation: Default pre-warm to opt-in via `?warm=true` query param. Validate in Wave 1 against live CC before enabling by default.

3. **ANSI escape code suppression**
   - What we know: PTY mode may trigger CC colored output. The ANSI regex `\x1b\[[0-9;]*[mGKHF]` covers most common codes.
   - What's unclear: Whether CC emits ANSI codes when output is PTY but `--output-format stream-json` is specified.
   - Recommendation: Add the ANSI strip defensively; it is a no-op if CC suppresses ANSI for stream-json mode.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest with pytest-asyncio |
| Config file | `pyproject.toml` `[tool.pytest.ini_options]` |
| Quick run command | `python -m pytest tests/test_cc_bridge.py tests/test_cc_chat_ui.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PTY-01 | `cc_chat_ws` source contains winpty/pty setup pattern | source inspection | `python -m pytest tests/test_cc_pty.py::TestPTYSubprocess -x -q` | Wave 0 |
| PTY-01 | PTY read loop uses `readline` not `read(4096)` | source inspection | `python -m pytest tests/test_cc_pty.py::TestPTYSubprocess::test_pty_uses_readline -x -q` | Wave 0 |
| PTY-02 | `_parse_cc_event` emits `status` for `hook_started` events | unit | `python -m pytest tests/test_cc_pty.py::TestInitProgress -x -q` | Wave 0 |
| PTY-02 | `_parse_cc_event` emits per-MCP-server status from `init` mcp_servers | unit | `python -m pytest tests/test_cc_pty.py::TestInitProgress::test_init_mcp_servers -x -q` | Wave 0 |
| PTY-03 | `_cc_warm_pool` dict exists in server.py source | source inspection | `python -m pytest tests/test_cc_pty.py::TestPreWarmPool::test_warm_pool_defined -x -q` | Wave 0 |
| PTY-04 | Fallback to PIPE when PTY unavailable — `assistant` event path preserved | source inspection | `python -m pytest tests/test_cc_bridge.py::TestCCBridgeRouting -x -q` | ✅ exists |
| PTY-05 | `cc_chat_ws` source contains keepalive task with `asyncio.sleep` | source inspection | `python -m pytest tests/test_cc_pty.py::TestKeepalive -x -q` | Wave 0 |
| PTY-05 | `ws.onmessage` in app.js does not crash on `keepalive` type | source inspection | `python -m pytest tests/test_cc_chat_ui.py::TestCCChatRendering -x -q` (existing) | ✅ exists |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_cc_pty.py tests/test_cc_bridge.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_cc_pty.py` — new test file covering PTY-01 through PTY-05 (source inspection + unit tests for `_parse_cc_event` expansion)
- [ ] `tests/fixtures/cc_init_event.ndjson` — sample `system/init` event with `mcp_servers` array for PTY-02 unit tests

*(Existing `tests/test_cc_bridge.py` covers PTY-04 fallback path via `TestCCBridgeRouting`; no changes needed there.)*

---

## Sources

### Primary (HIGH confidence)

- `dashboard/server.py` lines 1540-1660 — existing winpty/pty terminal WS pattern (direct code inspection)
- `dashboard/server.py` lines 1712-2016 — existing `_parse_cc_event` and `cc_chat_ws` (direct code inspection)
- `dashboard/frontend/dist/app.js` lines 3820-3960 — existing `ideOpenCCChat` WS handlers (direct code inspection)
- `winpty.PtyProcess` source — `spawn`, `readline`, `read`, `isalive`, `terminate` methods (live Python inspection)
- `pyproject.toml` — `asyncio_mode = "auto"`, `testpaths = ["tests"]` (direct file read)
- `requirements.txt` line 54 — `pywinpty>=2.0.0; sys_platform == "win32"` (direct file read)

### Secondary (MEDIUM confidence)

- CC stream-json NDJSON event schema — documented in Phase 1 research and verified against `tests/fixtures/cc_stream_sample.ndjson`
- `--resume` session continuity behavior — verified in Phase 1 research (BRIDGE-04)

### Tertiary (LOW confidence, flag for validation)

- CC `init` event `mcp_servers` array exact field names — inferred from CC SDK docs, not verified against live CC output with mcp_servers populated
- CC ANSI escape code behavior in PTY + stream-json mode — not verified; added defensively
- Whether `--resume` skips MCP re-initialization — strong hypothesis based on CC session design, not confirmed by live test

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — winpty API verified via live Python inspection; pty pattern copied verbatim from existing code
- Architecture: HIGH — PTY pattern established in codebase; pre-warm model follows closure-scoped helper convention
- Pitfalls: HIGH (PTY column width, EOFError) / MEDIUM (ANSI codes, pre-warm sentinel) — column width confirmed by PTY behavior analysis; ANSI codes not live-tested in stream-json mode
- Open questions: LOW — mcp_servers schema, --resume MCP skip behavior need live-session validation

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable platform, 30-day window)

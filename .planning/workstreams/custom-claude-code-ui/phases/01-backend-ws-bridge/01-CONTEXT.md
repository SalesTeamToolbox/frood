# Phase 1: Backend WS Bridge - Context

**Gathered:** 2026-03-17
**Status:** Ready for planning

<domain>
## Phase Boundary

Server-side WebSocket endpoint that spawns `claude` CLI as a subprocess, translates its NDJSON stream into typed events, and manages multi-turn sessions with persistent session metadata. This is the strict prerequisite — every Phase 2+ feature depends on this bridge being solid.

Out of scope: frontend rendering, tool use cards, session history UI, layout (all Phase 2–4).

</domain>

<decisions>
## Implementation Decisions

### CC CLI invocation
- Command: `claude -p --output-format stream-json --verbose --include-partial-messages`
- `--verbose`: includes tool input/output inline in stream events — required for Phase 3 tool cards
- `--include-partial-messages`: enables incremental streaming of tool content (not just on completion)
- No `--allowedTools` restriction — CC operates with its full native + MCP tool set
- No `--system` prompt injection — UI handles display formatting on the frontend

### Process lifecycle
- Spawn a new `claude` subprocess per user turn (re-spawn model, not keep-alive)
- First turn: spawn without `--resume`, parse `session_id` from CC's result event, store server-side
- Subsequent turns: spawn with `--resume <cc_session_id>` for conversation continuity
- On WebSocket disconnect mid-generation: kill subprocess immediately (SIGTERM), no grace period
- No orphan process risk — each turn's subprocess is tracked and killed on WS disconnect

### Server-side session storage
- Storage: file-based JSON in `.agent42/cc-sessions/`
- One JSON file per Agent42 session
- Fields stored: `cc_session_id`, `ws_session_id`, `created_at`, `last_active_at`, `title` (first ~80 chars of user's first message)
- No full transcript — CC already owns conversation history; Agent42 only stores metadata for SESS-04 history list
- Survives server restarts (unlike in-memory dict)
- No Redis dependency for this feature

### WebSocket message schema
- Consistent envelope for all messages: `{"type": "<event>", "data": {...}}`
- Full event type set defined upfront (Phase 2 builds against this contract):
  - `text_delta` — streaming assistant text chunk: `{text: string}`
  - `tool_start` — tool invocation begins: `{id, name, input}`
  - `tool_delta` — incremental tool output (from --include-partial-messages): `{id, partial}`
  - `tool_complete` — tool invocation done: `{id, name, output, is_error}`
  - `turn_complete` — turn finished: `{session_id, cost_usd, input_tokens, output_tokens}`
  - `error` — backend or CC error: `{message, code}`
  - `status` — informational (e.g., "CC not available, falling back to API"): `{message}`
- `turn_complete` includes full usage stats for Phase 3 token display (SESS-06)
- Frontend switches on `type`, extracts `data` — no per-event schema variance

### Fallback behavior
- BRIDGE-05: when `claude` CLI unavailable, route to existing `/api/ide/chat` (Anthropic API)
- Frontend is notified via `status` event before fallback kicks in: `{"type": "status", "data": {"message": "CC subscription not available — using API mode"}}`
- Not silent — user sees they're in fallback mode

### Claude's Discretion
- JWT auth approach for `/ws/cc-chat` (follow `/ws/terminal` pattern)
- File format and cleanup policy for `.agent42/cc-sessions/`
- Exact asyncio subprocess management (follow `asyncio.create_subprocess_exec` pattern from `/ws/terminal`)
- BRIDGE-06 subscription detection implementation details (`claude auth status` parsing)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Requirements
- `.planning/workstreams/custom-claude-code-ui/REQUIREMENTS.md` §Backend Bridge — BRIDGE-01 through BRIDGE-06 acceptance criteria
- `.planning/workstreams/custom-claude-code-ui/ROADMAP.md` §Phase 1 — success criteria and phase dependencies

### Existing code patterns (must-read before implementing)
- `dashboard/server.py` lines ~1423–1550 — `/ws/terminal` WebSocket endpoint: asyncio subprocess pattern, JWT auth, disconnect handling. The CC bridge follows this same pattern.
- `dashboard/websocket_manager.py` — WebSocket connection management and limits
- `dashboard/server.py` lines ~1285–1420 — `/api/ide/*` endpoints (tree, file, search): established IDE API pattern and auth injection

### CC CLI
- CC documentation on `--output-format stream-json` event schema — researcher must fetch current spec (use Context7 or CC docs) to verify exact field names for `system`, `stream_event`, and `result` event types
- STATE.md research flag: "verify exact NDJSON event schema for `--verbose --include-partial-messages` combined flags against a live CC session before locking the parser"

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `asyncio.create_subprocess_exec` + PIPE stdout: already proven in `/ws/terminal` for SSH sessions — use same approach for CC subprocess
- JWT auth via query param token: established pattern in `/ws/terminal` — replicate for `/ws/cc-chat`
- `dashboard/websocket_manager.py`: WebSocket connection lifecycle management — use for `/ws/cc-chat` connection tracking
- `core/config.py` Settings + `AGENT42_WORKSPACE` env var — workspace path already available for CC subprocess env injection

### Established Patterns
- All I/O is async — subprocess stdout reading via `asyncio` tasks, not blocking
- WebSocket endpoints live inline in `dashboard/server.py` (not separate router files)
- Auth check at connection accept time, before any work begins
- Subprocess cleanup via task cancellation + `proc.terminate()` on disconnect

### Integration Points
- New endpoint `/ws/cc-chat` goes in `dashboard/server.py` after the terminal WebSocket block (~line 1550+)
- New REST endpoints `GET /api/cc/sessions` and `DELETE /api/cc/sessions/{id}` also in `dashboard/server.py`
- `.agent42/cc-sessions/` directory — create on first use, follow `.agent42/qdrant/` pattern for data dirs
- Fallback path calls existing `/api/ide/chat` handler (or its underlying logic) — verify current state of that endpoint before implementing

</code_context>

<specifics>
## Specific Ideas

- The `--resume` flag is the key to multi-turn continuity — session_id comes from CC's own result event on turn 1
- State.md research flag: verify NDJSON event schema live before finalizing the parser — this is non-trivial
- Per-turn spawn feels slower but is correct and simple; keep-alive is not worth the complexity for Phase 1

</specifics>

<deferred>
## Deferred Ideas

- Session transcript storage (full message history) — Phase 3 with SESS-04/05 history list
- Cross-node CC sessions via SSH relay — ADV-03, deferred to v2
- Token usage cost tracking across sessions — ADV-02, deferred to v2
- Configurable --allowedTools per session — could be Phase 3 or later
- System prompt injection / project-specific CC context — out of scope for Phase 1

</deferred>

---

*Phase: 01-backend-ws-bridge*
*Context gathered: 2026-03-17*

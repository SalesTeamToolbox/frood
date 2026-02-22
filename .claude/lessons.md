# Agent42 Development Lessons

Accumulated patterns, fixes, and vocabulary learned during development.
Updated automatically by the learning engine and manually by developers.

---

## Security Patterns

- Sandbox violations manifest as `SandboxViolation(PermissionError)` — check both the path and symlink target
- `CommandFilter` has 6 layers — bypassing one layer does NOT bypass others (structural, deny, interpreter, metachar, indirect, allowlist)
- `JWT_SECRET=""` triggers auto-generation, which breaks sessions across restarts — always set explicitly in `.env`
- `BROWSER_GATEWAY_TOKEN` is auto-generated per-run if not configured — set in `.env` for persistent browser sessions
- The `ApprovalGate` writes to a JSONL audit log — check `.agent42/approvals.jsonl` for approval history
- `url_policy.py` blocks internal network ranges by default — verify `URL_DENYLIST` includes `169.254.x.x`, `10.x.x.x`, `172.16.x.x`
- Login rate limiting is per-IP via `LOGIN_RATE_LIMIT` (default: 5/min) — stored in-memory, resets on restart
- `dashboard_password_hash` (bcrypt) takes precedence over plaintext `dashboard_password` if both are set

## Async Patterns

- ALL tool `execute()` methods are async — never use blocking I/O (`open()`, `subprocess.run()` with long timeout)
- Use `aiofiles.open()` not `open()` for file operations in tools
- `asyncio.wait_for()` wraps `queue.next()` with timeout in the queue processor
- The iteration engine uses `asyncio.gather()` for parallel tool calls when independent
- Channel listeners (`discord`, `slack`, `telegram`) each run in their own `asyncio.Task`
- `capacity.py` uses `psutil`-like checks but is non-blocking — polled on a timer

## Provider Patterns

- OpenRouter free models are keyed as `"or-free-*"` in the `MODELS` dict
- Provider availability is checked via `api_key_env` presence in `os.environ`
- `SpendingLimitExceeded` stops ALL API calls when `MAX_DAILY_API_SPEND_USD` cap is hit
- Model routing precedence: admin override env var → task-type routing table → free default
- The spending tracker resets daily at midnight UTC
- Provider errors should be caught and retried with exponential backoff (max 3 retries)

## Testing Patterns

- Use `tempfile.mkdtemp()` or pytest `tmp_path` fixture for sandbox tests
- Mock `ModelRouter.complete()` to avoid real API calls — return canned strings
- Tool tests follow: create tool with sandbox → execute → assert ToolResult fields
- Use `conftest.py` fixtures: `sandbox`, `command_filter`, `tool_registry`, `mock_tool`
- Security tests live in `test_security.py`, `test_sandbox.py`, `test_command_filter.py`
- Tests use class-based organization: `class TestClassName` with `setup_method`

## Configuration Patterns

- Every new env var needs: `Settings` field + `from_env()` parsing + `.env.example` entry
- Boolean fields use `.lower() in ("true", "1", "yes")` pattern
- Comma-separated list fields have `get_*()` helper methods on `Settings`
- The `Settings` dataclass is frozen — values cannot be changed after creation
- `settings` singleton is created at import time of `core/config.py` — used everywhere
- `_resolve_repo_path()` validates that `DEFAULT_REPO_PATH` exists and is a git repo

## Tool Development

- Tools inherit from `tools.base.Tool` ABC — must implement `name`, `description`, `parameters`, `execute()`
- `parameters` returns a JSON Schema dict (OpenAI function-calling format)
- `execute()` returns `ToolResult(output=..., error=..., success=True/False)`
- New tools must be registered in `agent42.py` `_register_tools()` method
- `to_schema()` serializes the tool for LLM function-calling — don't override unless needed
- Always accept `**kwargs` in `execute()` for forward compatibility
- Use `self._sandbox.resolve_path()` for any file path arguments

## Skill Development

- Skills are directories with `SKILL.md` files containing YAML frontmatter
- Frontmatter fields: `name`, `description`, `always`, `task_types`, `requirements_bins`
- `always: true` skills load for every task — use sparingly
- `task_types` matches against `TaskType` enum values in `core/task_queue.py`
- Skills in `builtins/` ship with Agent42; `workspace/` skills are user-created
- The loader parses YAML without PyYAML — uses a simple regex-based parser

## Dashboard Patterns

- FastAPI app in `dashboard/server.py` with REST and WebSocket endpoints
- JWT auth with device-key fallback for API access
- WebSocket manager broadcasts real-time updates to connected clients
- `DASHBOARD_HOST=127.0.0.1` by default — nginx handles external access
- Rate limiting on `/api/login` endpoint — `LOGIN_RATE_LIMIT` per-IP per-minute

## Memory Patterns

- Two-layer persistence: `MEMORY.md` (current context) + `HISTORY.md` (full log)
- Semantic search via embeddings requires at least one embedding-capable API key
- Qdrant is optional — embedded mode (`QDRANT_ENABLED=true` without `QDRANT_URL`) uses local files
- Redis is optional — used for session cache and embedding cache with TTL
- Memory consolidation merges old history into summary chunks

## Vocabulary

- **worktree** = git worktree (one per agent, for isolated filesystem access)
- **iteration** = one Primary→Critic cycle in the iteration engine
- **skill** = SKILL.md directory with YAML frontmatter and markdown instructions
- **tool** = ABC subclass registered in ToolRegistry
- **provider** = LLM API backend defined by ProviderSpec
- **free-first** = use $0 OpenRouter models by default, premium only if admin configures
- **approval gate** = human review step for protected actions
- **spending tracker** = daily API cost accumulator with configurable cap
- **critic** = secondary LLM call that reviews primary output for quality
- **convergence** = iteration engine stops when critic approves or max iterations hit

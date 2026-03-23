# CLAUDE.md — Agent42 Development Guide

## Quick Reference

```bash
source .venv/bin/activate        # Activate virtual environment
python agent42.py                # Start Agent42 (dashboard at http://localhost:8000)
python -m pytest tests/ -x -q    # Run tests (stop on first failure)
make lint                        # Run linter (ruff)
make format                      # Auto-format code (ruff)
make check                       # Run lint + tests together
make security                    # Run security scanning (bandit + safety)
```

## IMPORTANT: Document Your Fixes!

When you resolve a non-obvious bug or discover a new pitfall, you **MUST** add it to the
[Common Pitfalls](#common-pitfalls) table at the end of this document. This keeps the
knowledge base current and prevents future regressions.

Ask yourself: *"Would this have saved me time if it was documented?"* If yes, add it.

---

## Codebase Navigation (jcodemunch)

This project is indexed by jcodemunch MCP server (`local/agent42`, 197 files, 4700+ symbols).
**Use jcodemunch tools before reading files** to understand structure and find the right code:

| When you need to... | Use this tool |
|----------------------|---------------|
| Understand a module before editing | `get_file_outline` — shows all classes, functions, signatures |
| Find where something is defined | `search_symbols` — search by name across the codebase |
| Explore a directory's structure | `get_file_tree` with `path_prefix` (e.g., `tools/`, `core/`) |
| Read a specific symbol's code | `get_symbol` — returns the full source of a function/class |
| Find text patterns across files | `search_text` — grep-like search across indexed files |
| Re-index after major changes | `index_folder` with `incremental: true` |

**Workflow for feature development:**
1. `get_file_tree` to orient — understand what exists in the relevant directory
2. `search_symbols` to find related classes/functions across the codebase
3. `get_file_outline` on files you plan to modify — understand the full API surface
4. Only then `Read` the specific sections you need to change

**Repo identifier:** `local/agent42` (use this as the `repo` parameter in all jcodemunch calls)

---

## Automated Development Workflow

This project uses automated hooks in the `.claude/` directory. These run automatically
during Claude Code sessions without manual activation.

### Active Hooks (Automatic)

| Hook | Trigger | Action |
|------|---------|--------|
| `context-loader.py` | UserPromptSubmit | Detects work type from file paths and keywords, loads relevant lessons and reference docs |
| `memory-recall.py` | UserPromptSubmit | Surfaces relevant memories from Qdrant before Claude thinks |
| `proactive-inject.py` | UserPromptSubmit | Surfaces past learnings relevant to detected task type |
| `security-gate.py` | PreToolUse (Write/Edit/Bash) | Blocks edits to security-sensitive files (requires approval) |
| `security-monitor.py` | PostToolUse (Write/Edit) | Flags security-sensitive changes for review (sandbox, auth, command filter) |
| `format-on-write.py` | PostToolUse (Write/Edit) | Auto-formats Python files with ruff on every write |
| `cc-memory-sync.py` | PostToolUse (Write/Edit) | Embeds CC memory files into Qdrant for semantic recall |
| `jcodemunch-reindex.py` | Stop + PostToolUse | Re-indexes codebase after structural file changes |
| `jcodemunch-token-tracker.py` | PostToolUse | Tracks token savings from jcodemunch vs full file reads |
| `session-handoff.py` | Stop | Captures session state for auto-resume continuity |
| `test-validator.py` | Stop | Validates tests pass, checks new modules have test coverage |
| `learning-engine.py` | Stop | Records development patterns, vocabulary, and skill candidates |
| `memory-learn.py` | Stop | Captures new learnings into memory system for future recall |
| `effectiveness-learn.py` | Stop | Extracts structured learnings with LLM for quarantine review |
| `knowledge-learn.py` | Stop | Extracts session knowledge and upserts to Qdrant |
| `credential-sync.py` | SessionStart | Syncs CC credentials to remote VPS on session start |

### Hook Protocol

- Hooks receive JSON on stdin with `hook_event_name`, `project_dir`, and event-specific data
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow, exit code 2 = block (for PreToolUse hooks)

### How It Works

```
┌──────────────────────────────────────────────────────────────────┐
│  SessionStart → credential-sync.py (syncs CC creds to VPS)      │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  User Prompt Submitted (UserPromptSubmit)                        │
│  ├─ context-loader.py    — loads lessons + reference docs        │
│  ├─ memory-recall.py     — surfaces relevant memories from Qdrant│
│  └─ proactive-inject.py  — injects past learnings for task type  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  PreToolUse → security-gate.py (blocks edits to security files)  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Claude Processes Request (may use Write/Edit tools)             │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  PostToolUse (Write/Edit):                                       │
│  ├─ security-monitor.py  — flags security-sensitive changes      │
│  ├─ format-on-write.py   — auto-formats Python with ruff         │
│  └─ cc-memory-sync.py    — embeds CC memory files into Qdrant    │
│  PostToolUse (all):                                              │
│  ├─ jcodemunch-token-tracker.py — tracks token savings           │
│  └─ jcodemunch-reindex.py       — re-indexes after file changes  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stop Event Triggers:                                            │
│  ├─ session-handoff.py       — captures state for auto-resume    │
│  ├─ test-validator.py        — runs pytest, checks coverage      │
│  ├─ learning-engine.py       — records patterns, updates lessons │
│  ├─ memory-learn.py          — captures learnings to memory      │
│  ├─ effectiveness-learn.py   — structured learning extraction    │
│  ├─ knowledge-learn.py       — session knowledge to Qdrant       │
│  └─ jcodemunch-reindex.py    — final re-index                    │
└──────────────────────────────────────────────────────────────────┘
```

### Available Agents (On-Demand)

| Agent | Use Case | Invocation |
|-------|----------|------------|
| security-reviewer | Audit security-sensitive code changes | Request security review |
| performance-auditor | Review async patterns, resource usage, timeouts | Ask about performance |

### Related Files

- `.claude/settings.json` — Hook configuration
- `.claude/lessons.md` — Accumulated patterns and vocabulary (referenced by hooks)
- `.claude/learned-patterns.json` — Auto-generated pattern data
- `.claude/reference/` — On-demand reference docs (loaded by context-loader hook)
- `.claude/agents/` — Specialized agent definitions

---

## Architecture Patterns

### All I/O is Async

Every file operation uses `aiofiles`, every HTTP call uses `httpx` or `openai.AsyncOpenAI`,
every queue operation is `asyncio`-native. **Never use blocking I/O** in tool implementations.

```python
# CORRECT
async with aiofiles.open(path, "r") as f:
    content = await f.read()

# WRONG — blocks the event loop
with open(path, "r") as f:
    content = f.read()
```

### Frozen Dataclass Configuration

`Settings` is a frozen dataclass loaded once from environment at import time (`core/config.py`).
When adding new configuration:
1. Add field to `Settings` class with default
2. Add `os.getenv()` call in `Settings.from_env()`
3. Add to `.env.example` with documentation

```python
# Boolean fields use this pattern:
sandbox_enabled=os.getenv("SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes")

# Comma-separated fields have get_*() helper methods:
def get_discord_guild_ids(self) -> list[int]: ...
```

### Plugin Architecture

**Tools (built-in):** Subclass `tools.base.Tool`, implement `name`/`description`/`parameters`/`execute()`,
register in `agent42.py` `_register_tools()`.

```python
class MyTool(Tool):
    @property
    def name(self) -> str: return "my_tool"
    @property
    def description(self) -> str: return "Does something useful"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"input": {"type": "string"}}}
    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        return ToolResult(output=f"Result: {input}")
```

**Tools (custom plugins):** Drop a `.py` file into `CUSTOM_TOOLS_DIR` and it will be
auto-discovered at startup via `tools/plugin_loader.py`. No core code changes needed.
Tools declare dependencies via a `requires` class variable for `ToolContext` injection.

```python
# custom_tools/hello.py
from tools.base import Tool, ToolResult

class HelloTool(Tool):
    requires = ["workspace"]  # Injects workspace from ToolContext

    def __init__(self, workspace="", **kwargs):
        self._workspace = workspace

    @property
    def name(self) -> str: return "hello"
    @property
    def description(self) -> str: return "Says hello"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}
    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(output=f"Hello from {self._workspace}!")
```

**Tool extensions (custom plugins):** To *extend* an existing tool instead of
creating a new one, subclass `ToolExtension` instead of `Tool`.  Extensions add
parameters and pre/post execution hooks without replacing the base tool.  Multiple
extensions can layer onto one base — just like skills.

```python
# custom_tools/shell_audit.py
from tools.base import ToolExtension, ToolResult

class ShellAuditExtension(ToolExtension):
    extends = "shell"                      # Name of the tool to extend
    requires = ["workspace"]               # ToolContext injection (same as Tool)

    def __init__(self, workspace="", **kwargs):
        self._workspace = workspace

    @property
    def name(self) -> str: return "shell_audit"

    @property
    def extra_parameters(self) -> dict:    # Merged into the base tool's schema
        return {"audit": {"type": "boolean", "description": "Log command to audit file"}}

    @property
    def description_suffix(self) -> str:   # Appended to the base tool's description
        return "Supports audit logging."

    async def pre_execute(self, **kwargs) -> dict:
        # Called before the base tool — can inspect/modify kwargs
        return kwargs

    async def post_execute(self, result: ToolResult, **kwargs) -> ToolResult:
        # Called after the base tool — can inspect/modify result
        return result
```

**Skills:** Create a directory with `SKILL.md` containing YAML frontmatter:

```markdown
---
name: my-skill
description: One-line description of what this skill does.
always: false
task_types: [coding, debugging]
---

# My Skill

Instructions for the agent when this skill is active...
```

### Graceful Degradation

Redis, Qdrant, channels, and MCP servers are all optional. Code **must** handle their
absence with fallback behavior, never with crashes.

```python
# CORRECT — conditional import and check
if settings.redis_url:
    from memory.redis_session import RedisSessionStore
    session_store = RedisSessionStore(settings.redis_url)
else:
    session_store = FileSessionStore(settings.sessions_dir)

# WRONG — crashes if Redis isn't installed
from memory.redis_session import RedisSessionStore
```

### MCP Architecture (v2.0)

Claude Code provides the intelligence layer (LLM, orchestration). Agent42 provides
the tooling layer via MCP:

- **MCP Server** (`mcp_server.py`) — 36+ tools exposed via stdio transport
- **Memory** — ONNX embeddings + Qdrant for semantic search (~25 MB RAM)
- **Associative Recall** — Hook auto-surfaces relevant memories on every prompt
- **Context Assembler** — `agent42_context` tool pulls from memory, docs, git, skills
- **Dashboard** — FastAPI web UI for monitoring and configuration

### Security Layers (Defense in Depth)

| Layer | Module | Purpose |
|-------|--------|---------|
| 1 | `WorkspaceSandbox` | Path resolution, traversal blocking, symlink defense |
| 2 | `CommandFilter` | 6-layer shell command filtering (structural, deny, interpreter, metachar, indirect, allowlist) |
| 3 | `ApprovalGate` | Human review for protected actions |
| 4 | `ToolRateLimiter` | Per-agent per-tool sliding window |
| 5 | `URLPolicy` | Allowlist/denylist for HTTP requests (SSRF protection) |
| 6 | `BrowserGatewayToken` | Per-session token for browser tool |
| 7 | `SpendingTracker` | Daily API cost cap across all providers |
| 8 | `LoginRateLimit` | Per-IP brute force protection on dashboard |

---

## Security Requirements

These rules are **non-negotiable** for a platform that runs AI agents on people's servers:

1. **NEVER** disable sandbox in production (`SANDBOX_ENABLED=true`)
2. **ALWAYS** use bcrypt password hash, not plaintext (`DASHBOARD_PASSWORD_HASH`)
3. **ALWAYS** set `JWT_SECRET` to a persistent value (auto-generated secrets break sessions across restarts)
4. **NEVER** expose `DASHBOARD_HOST=0.0.0.0` without nginx/firewall in front
5. **ALWAYS** run with `COMMAND_FILTER_MODE=deny` (default) or `COMMAND_FILTER_MODE=allowlist`
6. **REVIEW** `URL_DENYLIST` to block internal network ranges (`169.254.x.x`, `10.x.x.x`, etc.)
7. **NEVER** log API keys, passwords, or tokens — even at DEBUG level
8. **ALWAYS** validate file paths through `sandbox.resolve_path()` before file operations

---

## Development Workflow

### Before Writing Code

1. Run tests to confirm green baseline: `python -m pytest tests/ -x -q`
2. Check if related test files exist for the module you're changing
3. Read the module's docstring and understand the pattern
4. For security-sensitive files, read `.claude/lessons.md` security section

### After Writing Code

1. Run the formatter: `make format` (or `ruff format .`)
2. Run the full test suite: `python -m pytest tests/ -x -q`
3. Run linter: `make lint`
4. For security-sensitive changes: `python -m pytest tests/test_security.py tests/test_sandbox.py tests/test_command_filter.py -v`
5. Update this CLAUDE.md pitfalls table if you discovered a non-obvious issue
6. For new modules: ensure a corresponding `tests/test_*.py` file exists
7. Update README.md if new features, skills, tools, or config were added

---

## Testing Standards

**Always install dependencies before running tests.** Tests should always be
runnable — if a dependency is missing, install it rather than skipping the test:

```bash
pip install -r requirements.txt            # Full production dependencies
pip install -r requirements-dev.txt        # Dev/test tooling (pytest, ruff, etc.)
# If the venv is missing, install at minimum:
pip install pytest pytest-asyncio aiofiles openai fastapi python-jose bcrypt cffi
```

Run tests:
```bash
python -m pytest tests/ -x -q              # Quick: stop on first failure
python -m pytest tests/ -v                  # Verbose: see all test names
python -m pytest tests/test_security.py -v  # Single file
python -m pytest tests/ -k "test_sandbox"   # Filter by name
python -m pytest tests/ -m security         # Filter by marker
```

Some tests require `fastapi`, `python-jose`, `bcrypt`, and `redis` — install the full
`requirements.txt` to avoid import errors. If the `cryptography` backend fails with
`_cffi_backend` errors, install `cffi` (`pip install cffi`).

### Test Writing Rules

- Every new module in `core/`, `agents/`, `tools/`, `providers/` needs a `tests/test_*.py` file
- Use `pytest-asyncio` for async tests (configured as `asyncio_mode = "auto"` in pyproject.toml)
- Use `tmp_path` fixture (or conftest.py `tmp_workspace`) for filesystem tests — never hardcode `/tmp` paths
- Use class-based organization: `class TestClassName` with `setup_method`
- Mock external services (LLM calls, Redis, Qdrant) — never hit real APIs in tests
- Use conftest.py fixtures: `sandbox`, `command_filter`, `tool_registry`, `mock_tool`
- Name tests descriptively: `test_<function>_<scenario>_<expected>`

```python
class TestWorkspaceSandbox:
    def setup_method(self):
        self.sandbox = WorkspaceSandbox(tmp_path, enabled=True)

    def test_block_path_traversal(self):
        with pytest.raises(SandboxViolation):
            self.sandbox.resolve_path("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_async_tool_execution(self):
        result = await tool.execute(input="test")
        assert result.success
```

---

## Development Methodology

Agent42 uses **GSD (Get Shit Done)** as the default methodology for multi-step work.
The always-on `gsd-auto-activate` skill handles detection automatically.

### When to Use GSD

Use GSD for any task involving multiple files, phases, or coordinated steps:
- New features, tools, skills, or providers
- Refactors touching 3+ files
- Architecture changes or migrations
- Any task where you'd naturally say "first I need to... then..."

### When to Skip GSD

Skip GSD for trivial tasks (Claude handles these directly):
- Quick questions ("what does X do?")
- Single-file typo/style fixes
- Configuration lookups
- Debugging a specific known error

### Key GSD Commands

| Command | When to Use |
|---------|-------------|
| `/gsd:new-project` | Initialize a new multi-phase workstream |
| `/gsd:quick` | Ad-hoc task with GSD tracking but no full phase plan |
| `/gsd:plan-phase` | Plan a specific phase when already in a workstream |
| `/gsd:execute-phase` | Execute a planned phase |
| `/gsd:next` | Advance to the next task in the current plan |

---

## Common Pitfalls

> Pitfalls 1-80 archived to `.claude/reference/pitfalls-archive.md` (loaded on-demand by context-loader hook).
> Recent pitfalls (81+) kept inline for immediate reference.

| # | Area | Pitfall | Correct Pattern |
|---|------|---------|-----------------|
| 81 | Chat | Agent processes dashboard chat messages in isolation — no conversation history | Pass `chat_session_manager` to Agent; load history in `_build_context()` via `origin_metadata["chat_session_id"]` |
| 82 | Prompts | System prompts encouraged confabulation — "never say you don't know" + memory skill implied cross-server recall | Added truthfulness guardrails to `GENERAL_ASSISTANT_PROMPT`, `platform-identity`, and `memory` skills; agent must only reference actual context, never fabricate |
| 83 | Dashboard | `submitCreateTask()` called `doCreateTask()` twice — copy-paste error with separate `projectId` and `repoId` calls | Merge all form fields into a single `doCreateTask(title, desc, type, projectId, repoId, branch)` call |
| 84 | Apps | `install_deps` only checks `apps/{id}/requirements.txt` but agents sometimes place it in `apps/{id}/src/` | Check `src/requirements.txt` as fallback in both `AppTool._install_deps()` and `AppManager._start_python_app()` |
| 85 | Classifier | "Build me a Flask app" misclassified as `marketing` by LLM — keyword fallback had no framework-specific terms | Add framework keywords (`flask app`, `django app`, etc.) to `APP_CREATE` in `_TASK_TYPE_KEYWORDS`; add classification rule to LLM prompt |
| 86 | Dashboard | `/api/reports` crashes with 500 if any service (`model_evaluator`, `model_catalog`, etc.) throws | Wrap endpoint in try/except returning valid empty report structure on failure |
| 87 | Heartbeat | `_monitor_loop` calls `get_health()` with no args — periodic WS broadcasts overwrite tools/tasks with 0 | Store `task_queue` and `tool_registry` on `HeartbeatService`; pass them in the broadcast loop |
| 88 | Heartbeat | `ctypes.windll.psapi.GetProcessMemoryInfo` silently returns 0 on Windows (missing argtypes) | Use `ctypes.WinDLL("psapi")` with explicit `argtypes`/`restype`; also fix macOS `ru_maxrss` bytes-vs-KB conversion |
| 89 | Dashboard | Chat session sidebar empty after server restart — WS reconnect doesn't reload data | Add `loadChatSessions(); loadCodeSessions(); loadTasks(); loadStatus();` to `ws.onopen` when `wsRetries > 0` |
| 90 | Routing | ComplexityAssessor, IntentClassifier, and Learner all used dead OR free models (`or-free-mistral-small`, `or-free-deepseek-chat`) — teams never formed, classification fell back to keywords, learning never happened | Route internal LLM consumers to `gemini-2-flash` (reliable, free tier); don't use OR free models for infrastructure-critical calls |
| 91 | Routing | Critics tried dead OR free models first, then fell back to Gemini — wasted 5-7s per iteration on 429 retries | Validate critic health/API key in `get_routing()` and pre-upgrade to `gemini-2-flash` before task execution begins |
| 92 | RLM | RLM threshold at 50K tokens triggered for most tasks, causing 3-5x token amplification and API rate-limit spikes | Raise `RLM_THRESHOLD_TOKENS` to 200K — RLM should only activate for genuinely massive contexts, not routine tasks |
| 93 | Dispatch | Multiple agents dispatched simultaneously cause Gemini 1M TPM rate-limit spikes | Add `AGENT_DISPATCH_DELAY` (default 2.0s) to stagger agent launches in `_process_queue()` |
| 94 | Deploy | `agent42.py` refactored command handlers into `commands.py` but file wasn't committed — `ModuleNotFoundError` on production startup | Always verify new module files are staged before pushing; `git status` shows untracked files that may be required imports |
| 95 | Auth | Bcrypt password hash in `.env` doesn't match intended password after manual edits — login silently fails with 401 | Regenerate hash on server: `python3 -c "import bcrypt; print(bcrypt.hashpw(b'password', bcrypt.gensalt()).decode())"` and update `.env`; restart service |
| 96 | Dashboard | `project_manager.all_projects()` renamed to `list_projects()` — `/api/reports` crashes with AttributeError | Check method names against current API when refactoring; `server.py` calls must match `project_manager` interface |
| 97 | Dashboard | `skill.enabled` attribute doesn't exist — use `skill_loader.is_enabled(s.name)` instead | Skills don't have an `enabled` field; enablement is managed by the SkillLoader, not the Skill object |
| 98 | Search | Brave Search returns 422 on production — API key or query format issue | `web_search` tool has DuckDuckGo fallback; search still works but with lower quality results. Check `BRAVE_API_KEY` in `.env` |
| 99 | AppTest | `AppTestTool._findings` accumulates across calls — stale findings leak into reports | Call `generate_report` to consume and clear findings, or check `_findings` list is reset between test sessions |
| 100 | AppTest | `app_test smoke_test` returns success even when health check fails | Tool always returns `ToolResult(success=True)` for completed checks — failures are in the output text and findings, not in `success=False` |
| 101 | Critic | Visual critic sends multimodal `content` (list of dicts) but some models only accept string content | `_extract_screenshot_b64` returns None on any failure — critic falls back to text-only; only vision-capable models get image |
| 102 | Apps | `pip install` fails on Ubuntu 24+ with "externally-managed-environment" (PEP 668) | `_ensure_app_venv()` creates a per-app `.venv`; both `_start_python_app()` and `_install_deps()` use the venv's Python for pip and app execution |
| 103 | Memory | `_direct_response()` and server.py conversational path skip memory loading — agent claims no memory of past conversations | Use `build_conversational_memory_context()` helper to inject MEMORY.md + HISTORY.md into system prompt for all response paths |
| 104 | Security | GitHub tokens stored as plaintext in `github_accounts.json` and `settings.json` | Use `core.encryption.encrypt_value()`/`decrypt_value()` with Fernet; legacy plaintext auto-migrates on next persist |
| 105 | Security | GitHub token embedded in clone/push URLs visible in `ps` and `/proc` | Use `core.git_auth.git_askpass_env()` context manager — token is injected via `GIT_ASKPASS` temp script, not URL |
| 106 | Security | `SANDBOX_ENABLED=false` silently disables all path restrictions | `config.py` force-enables sandbox when host is exposed or `SANDBOX_DISABLE_CONFIRM` not set; `sandbox.py` logs CRITICAL |
| 107 | Security | `zipfile.extractall()` vulnerable to zip-slip (path traversal via `../`) | Validate every `zf.namelist()` entry: reject absolute paths, `..` components, and resolved paths outside target |
| 108 | Security | Device API key hashes used plain SHA-256 (no secret) | `_hash_key()` uses HMAC-SHA256 keyed by JWT_SECRET; `validate_api_key()` auto-upgrades legacy SHA-256 hashes |
| 109 | Memory | `QdrantStore.is_available` only checked `self._client is not None` — returned True even when server was unreachable | `is_available` now probes via `get_collections()` with cached TTL (60s success, 15s fail); embedded mode skips probe |
| 110 | Memory | `EmbeddingStore.search()` took Qdrant path when `is_available=True` but never fell through to JSON on Qdrant failure | Refactored to try/except around Qdrant search; falls through to `_search_json()` on any exception |
| 111 | Memory | Agent claims "stored in MEMORY.md" but has no tool to actually write — memory skill described the system but no corresponding tool existed | Created `tools/memory_tool.py` with store/recall/log/search actions; registered in `_register_tools()` |
| 112 | Dashboard | Storage status showed configured mode ("Qdrant + Redis") even when Qdrant was unreachable | Endpoint now returns `effective_mode` based on actual connectivity; frontend shows degradation warning when `configured_mode != mode` |
| 113 | Init | `_register_tools()` called before `memory_store` initialized — AttributeError on startup | Move `_register_tools()` call to after MemoryStore initialization in `agent42.py` |
| 114 | Deploy | `install-server.sh` used `--storage-path` CLI arg removed in Qdrant v1.14+; service crash-looped 37K+ times | Use `--config-path /etc/qdrant/config.yaml` + `WorkingDirectory=/var/lib/qdrant` in systemd unit; create config file with `storage.storage_path` |
| 115 | Deploy | `.env` had `QDRANT_URL=http://qdrant:6333` (Docker hostname) on bare-metal server — Qdrant unreachable | Bare-metal deployments must use `http://localhost:6333`; Docker Compose uses `http://qdrant:6333` (service name resolves inside Docker network only) |
| 116 | Server | `from starlette.responses import Response` at `create_app()` scope shadows `fastapi.Response` — causes `UnboundLocalError` on startup, crash-loops the service | Never import at `create_app` scope; use module-level FastAPI imports or import inside nested functions. FastAPI re-exports starlette's `Response` already. |
| 117 | Tests | `core.task_queue` removed in v2.0 but 3 test files still imported it inside `try` blocks — caused `HAS_TESTCLIENT=False` silently, then `NameError` on classes that used names from the failed import | When removing a module, grep all test files for references. `try/except ImportError` blocks mask the real cause — split imports so unrelated names aren't lost |
| 118 | Tests | Tests referencing `/api/tasks` endpoint broke silently after v2.0 removed it — returned 404 instead of expected 401 | After removing API endpoints, grep `tests/` for the route path and update or remove affected tests |
| 119 | Deploy | Unstaged local changes block `git checkout main` during deploy, forcing stash/pop which causes merge conflicts | Always check `git status` before deploy. Commit or explicitly stash WIP first — don't let deploy workflow hit stash conflicts mid-flight |
| 120 | CC Chat | On session resume/page reload, `sessionStorage` restores the session ID so CC retains conversation context via `--resume`, but the chat DOM is empty — messages were never persisted | Save user and assistant messages to `localStorage` keyed by `cc_hist_<sessionId>`; restore via `ccRestoreHistory()` in `ws.onopen` when `sessionResumed === true` |
| 121 | Startup | `agent42.py` called `PluginLoader(self.tool_registry)` (old instance-based API) — but `PluginLoader` has no constructor; only a static `load_all(directory, context, registry)` method | Use `PluginLoader.load_all(custom_tools_dir, ctx, self.tool_registry)` and only call it when `CUSTOM_TOOLS_DIR` is configured |
| 122 | GSD | `gsd-tools.cjs` resolves `project_root` to parent repo (agent42) when working in nested repos with their own `.git/` (e.g. `apps/meatheadgear/`) | GSD planning for nested app repos must be done manually or with `cd` to the app directory first. GSD needs a fix to detect and respect nested git roots |
| 123 | Status | System RAM showed `0 / 0 MB` on Windows — `memory_total_mb` and `memory_available_mb` were hardcoded to 0 in heartbeat | Use `GlobalMemoryStatusEx` on Windows, `/proc/meminfo` on Linux to populate system memory fields |
| 124 | Frontend | `/api/tasks` endpoint removed in v2.0 but frontend `loadTasks()` still called it — caused 404 on every page load | Replace `await api("/tasks")` with `state.tasks = []` (tasks are project-scoped now) |

---

## Extended Reference (loaded on-demand)

Detailed reference docs are in `.claude/reference/` and loaded automatically by the
context-loader hook when relevant work types are detected. Files:
- `terminology.md` — Full glossary of 50 terms
- `project-structure.md` — Complete directory tree
- `configuration.md` — All 80+ environment variables
- `new-components.md` — Procedures for adding tools, skills, providers
- `conventions.md` — Naming, commits, documentation maintenance
- `deployment.md` — Local, production, and Docker deployment

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Agent42**

An AI agent platform that operates across 9 LLM providers with tiered routing (L1 workhorse, L2 premium, free fallback), per-agent model configuration, and graceful degradation. Features intelligent memory (ONNX + Qdrant with auto-sync from Claude Code), task-aware learning (effectiveness tracking + proactive injection), and native desktop app experience (PWA + GSD auto-activation).

**Core Value:** Agent42 must always be able to run agents reliably, with tiered provider routing (L1 workhorse -> free fallback -> L2 premium) ensuring no single provider outage stops the platform.

### Constraints

- **API compatibility**: All providers use OpenAI Chat Completions compatible APIs
- **Tiered defaults**: L1 (StrongWall) when configured, free tier fallback, L2 premium opt-in
- **Graceful degradation**: Missing API keys never crash Agent42
- **Backward compatible**: Users without new API keys keep existing routing
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

## Context: This Is an Additive Feature, Not a New Stack
## Recommended Stack
### Core Technologies (Stdlib — No New Dependencies)
| Technology | Version | Purpose | Why Recommended |
|------------|---------|---------|-----------------|
| `enum.IntEnum` (stdlib) | Python 3.11+ | `RewardTier` enum (BRONZE/SILVER/GOLD) | Standard, hashable, sortable — IntEnum supports `tier >= SILVER` comparisons which plain Enum does not. Zero deps. Project already uses dataclasses + enum throughout. |
| `dataclasses` (stdlib) | Python 3.11+ | `TierConfig`, `TierLimits`, `AgentTierState` frozen dataclasses | Matches the frozen-dataclass pattern used throughout `core/config.py` and `core/rate_limiter.py`. Immutable tier config objects prevent accidental mutation in concurrent code. |
| `asyncio.Semaphore` (stdlib) | Python 3.11+ | Per-tier concurrent task caps | Agent Manager already manages agent lifecycle. Semaphores keyed per-agent give each tier its concurrent task ceiling. Cannot resize after creation — swap on promotion (see Pattern 3 below). |
| `asyncio.Lock` (stdlib) | Python 3.11+ | Tier state mutation guard | Tier promotions are rare but must be atomic. A per-agent lock prevents race between a score recompute and an in-flight task dispatch. |
| `time.monotonic()` (stdlib) | Python 3.11+ | Cache expiry timestamps | Already used in `rate_limiter.py`. Use for TTL-based tier cache invalidation without importing cachetools. |
| `aiosqlite` (existing dep) | >=0.20.0 | Tier history log | Already in requirements.txt for effectiveness tracking. Add a `tier_history` table alongside existing effectiveness tables. Append-only rows (agent_id, tier, score, timestamp) give full audit trail at zero extra cost. |
### Supporting Libraries (Existing Dependencies — Already Installed)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `aiofiles` (existing) | >=23.0.0 | Persist tier overrides to `.agent42/rewards/overrides.json` | Admin override JSONL for human-readable backup alongside the SQLite audit log. Matches existing file-persistence patterns. |
| FastAPI (existing) | >=0.115.0 | REST endpoints for tier management dashboard | `/api/rewards/tiers`, `/api/rewards/agents/{id}/override`, `/api/rewards/status`. No new framework needed. |
| WebSocket (existing) | >=12.0 | Push tier-change events to dashboard | When an agent promotes from Bronze to Silver, push a `tier_changed` event over the existing WS bus. Dashboard already subscribes to agent status events. |
### New Optional Dependency (Add Only If TTL Cache Complexity Warrants It)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `cachetools` | 7.0.5 (2026-03-09) | `TTLCache` for computed tier scores | Only add if the hand-rolled TTL dict approach grows messy. `TTLCache(maxsize=512, ttl=300)` keyed by `agent_id` is cleaner than dict + timestamp bookkeeping at scale. Likely already installed as a transitive dep — run `pip show cachetools` before adding. |
### Development Tools (Existing)
| Tool | Purpose | Notes |
|------|---------|-------|
| pytest + pytest-asyncio | Unit and async integration tests for tier logic | Already configured with `asyncio_mode = "auto"`. Test tier transitions, score calculations, semaphore enforcement. |
| ruff | Linting and formatting | Already configured. Run `make format && make lint` after adding new modules. |
## Installation
# No new core dependencies required.
# All recommendations use stdlib or packages already in requirements.txt.
# Optional — only if TTLCache is added:
# First check if it is already a transitive dep:
# If not present:
## Architectural Patterns for This Feature
### Pattern 1: Tier as a Computed Projection, Not Stored State
# core/rewards_engine.py
# In-memory cache: {agent_id: (tier, computed_at)}
### Pattern 2: Frozen Dataclass Tier Limits
### Pattern 3: Semaphore-per-Agent with Swap-on-Promotion
### Pattern 4: Opt-In via Settings, Graceful Degradation When Disabled
### Pattern 5: Composite Score as Weighted Sum (No ML Library Needed)
## Alternatives Considered
| Recommended | Alternative | When to Use Alternative |
|-------------|-------------|-------------------------|
| `IntEnum` for tiers | String literals "bronze"/"silver"/"gold" | Never for internal code — strings lose comparability. Strings acceptable only at the API/JSON serialization boundary. |
| In-memory TTL dict | `cachetools.TTLCache` | Use `cachetools` only if tier cache needs LRU eviction (thousands of agents). For tens to hundreds of agents, a plain dict with monotonic timestamps is simpler with zero deps. |
| Append to aiosqlite `tier_history` | Separate JSONL audit file | JSONL is fine for human inspection; SQLite is better if you need to query "all agents that were Gold last week". Since aiosqlite is already a dep, prefer it. |
| `asyncio.Semaphore` per-agent | Token bucket rate limiter library (e.g., `aiometer`) | Use a library only if you need continuous rate (requests-per-second) rather than concurrency (in-flight task count). Tier system needs concurrency caps, not rate caps. |
| Pure Python weighted average | scikit-learn metrics | scikit-learn is a 300 MB ML library for a 2-float weighted sum. Never appropriate here. |
| FastAPI endpoints on existing server | Separate microservice | Never. This is an additive feature on Agent42, not a separate service. |
## What NOT to Use
| Avoid | Why | Use Instead |
|-------|-----|-------------|
| `asyncache` 0.3.1 | Unmaintained since November 2022; requires cachetools <=5.x, incompatible with cachetools 7.x | `cachetools-async` 0.0.5 (June 2025) or a Lock-guarded dict |
| Redis Streams or Kafka for tier-change events | Enormous operational overhead for an in-process state change; Redis is optional in Agent42 | `asyncio.Queue` or direct WebSocket push via existing heartbeat/WS infrastructure |
| Celery or task queue for score recomputation | Brings sync worker overhead and hard Redis dependency; Agent42 is async-native | `asyncio.create_task()` scheduled background recompute in the existing event loop |
| scikit-learn | 300 MB dependency for a weighted average of floats | Pure Python arithmetic |
| Separate database for tier state | Tier is a derived view of effectiveness data; a separate DB creates drift risk | Compute from existing effectiveness store; cache in-memory; audit log in the existing aiosqlite DB |
## Stack Patterns by Variant
- `get_agent_tier()` returns `RewardTier.BRONZE` immediately, no DB queries, no cache writes
- All `TierLimits` return Bronze defaults — existing behavior is unchanged
- Use in-memory TTL dict for tier cache (already the primary approach)
- No degradation — Redis is not required for this feature
- Return `RewardTier.BRONZE` regardless of score
- Surface a reason string: "Needs N more task completions to qualify for Silver"
- Store override in `.agent42/rewards/overrides.json` (keyed by agent_id), persisted via `aiofiles`
- `get_agent_tier()` checks overrides first, bypasses score computation entirely
- Dashboard displays "Admin Override: Gold" with a clear visual indicator
## Version Compatibility
| Package | Compatible With | Notes |
|---------|-----------------|-------|
| `cachetools>=7.0.5` | Python 3.10+ | Safe with existing stack (Python 3.11+). If added, do NOT also add `asyncache` (incompatible with 7.x). |
| `aiosqlite>=0.20.0` | Python 3.11+ | Already in requirements.txt. Use `async with aiosqlite.connect()` pattern consistent with existing usage. |
| `asyncio.Semaphore` | Python 3.11+ stdlib | Cannot be resized — design semaphore lifecycle carefully (see Pattern 3). |
| `enum.IntEnum` | Python 3.11+ stdlib | Supports `>=` and `<` comparisons directly, which plain `enum.Enum` does not. |
## Sources
- Agent42 codebase — `core/rate_limiter.py` (sliding-window per-agent pattern), `core/config.py` (frozen dataclass settings pattern), `core/agent_manager.py` (AgentConfig dataclass), `requirements.txt` (existing deps) — HIGH confidence
- [cachetools 7.0.5 on PyPI](https://pypi.org/project/cachetools/) — latest version verified 2026-03-22 — HIGH confidence
- [asyncache 0.3.1 on PyPI](https://pypi.org/project/asyncache/) — confirmed unmaintained (last release November 2022), incompatible with cachetools 7.x — HIGH confidence
- [cachetools-async 0.0.5 on PyPI](https://pypi.org/project/cachetools-async/) — confirmed active (released June 2025) — HIGH confidence
- [Python asyncio.Semaphore docs](https://docs.python.org/3/library/asyncio-sync.html) — fixed-at-creation limit confirmed — HIGH confidence
- [Python enum.IntEnum docs](https://docs.python.org/3/library/enum.html) — IntEnum for tier comparison operators — HIGH confidence
- [cachetools TTLCache docs](https://cachetools.readthedocs.io/en/stable/) — TTL eviction semantics — HIGH confidence
- [asyncio semaphore concurrency pattern](https://rednafi.com/python/limit-concurrency-with-semaphore/) — separate semaphore per scope, cannot resize — MEDIUM confidence (WebSearch, consistent with official docs)
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->

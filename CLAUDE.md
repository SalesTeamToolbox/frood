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

## Automated Development Workflow

This project uses automated hooks in the `.claude/` directory. These run automatically
during Claude Code sessions without manual activation.

### Active Hooks (Automatic)

| Hook | Trigger | Action |
|------|---------|--------|
| `context-loader.py` | UserPromptSubmit | Detects work type from file paths and keywords, loads relevant lessons and reference docs |
| `security-monitor.py` | PostToolUse (Write/Edit) | Flags security-sensitive changes for review (sandbox, auth, command filter) |
| `test-validator.py` | Stop | Validates tests pass, checks new modules have test coverage |
| `learning-engine.py` | Stop | Records development patterns, vocabulary, and skill candidates |

### Hook Protocol

- Hooks receive JSON on stdin with `hook_event_name`, `project_dir`, and event-specific data
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow, exit code 2 = block (for PreToolUse hooks)

### How It Works

```
┌──────────────────────────────────────────────────────────────────┐
│  User Prompt Submitted                                           │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  context-loader.py (UserPromptSubmit)                            │
│  - Detects work type from file paths + keywords                  │
│  - Loads relevant lessons, patterns, standards from lessons.md   │
│  - Loads relevant reference docs from .claude/reference/         │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Claude Processes Request                                        │
│  (may use Write/Edit tools)                                      │
└──────────────┬──────────────────────────┬────────────────────────┘
               │                          │
               ▼                          ▼
┌──────────────────────────┐   ┌───────────────────────────────────┐
│  security-monitor.py     │   │  (other tool processing)          │
│  (PostToolUse Write/Edit)│   │                                   │
│  - Flags security risks  │   │                                   │
└──────────────────────────┘   └───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stop Event Triggers:                                            │
│  ├─ test-validator.py   — runs pytest, checks test coverage      │
│  └─ learning-engine.py  — records patterns, updates lessons.md   │
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

**Providers:** Add `ProviderSpec` to `PROVIDERS` dict and `ModelSpec` entries to `MODELS`
dict in `providers/registry.py`.

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

### Dynamic Model Routing (5-Layer)

Model selection in `model_router.py` uses a 5-layer resolution chain:

1. **Admin override** — `AGENT42_{TYPE}_MODEL` env vars (highest priority)
2. **Dynamic routing** — `data/dynamic_routing.json` written by `ModelEvaluator` based on outcome data
3. **Trial injection** — Unproven models randomly assigned (`MODEL_TRIAL_PERCENTAGE`, default 10%)
4. **Policy routing** — `balanced`/`performance` mode upgrades to paid models when OR credits available
5. **Hardcoded defaults** — `FREE_ROUTING` dict: Gemini Flash primary, OR free models as critic/fallback

**Default model strategy:** Gemini 2.5 Flash is the base LLM (generous free tier: 500 RPM).
OpenRouter free models serve as critic / secondary to distribute across providers.
`get_routing()` auto-falls back to OR free models if `GEMINI_API_KEY` is not set.
Admin can set `AGENT42_CODING_MODEL=claude-opus-4-6` (etc.) for premium models on specific tasks.

**Never hardcode premium models as defaults.** The dynamic system self-improves:
- `ModelCatalog` syncs free models from OpenRouter API (default every 24h)
- `ModelEvaluator` tracks success rate, iteration efficiency, and critic scores per model
- `ModelResearcher` fetches benchmark scores from LMSys Arena, HuggingFace, Artificial Analysis
- Composite score: `0.4*success_rate + 0.3*iteration_efficiency + 0.2*critic_avg + 0.1*research_score`

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

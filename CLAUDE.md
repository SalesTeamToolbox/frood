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

### Dynamic Model Routing (4-Layer)

Model selection in `model_router.py` uses a 4-layer resolution chain:

1. **Admin override** — `AGENT42_{TYPE}_MODEL` env vars (highest priority)
2. **Dynamic routing** — `data/dynamic_routing.json` written by `ModelEvaluator` based on outcome data
3. **Trial injection** — Unproven models randomly assigned (`MODEL_TRIAL_PERCENTAGE`, default 10%)
4. **Hardcoded defaults** — `FREE_ROUTING` dict (lowest priority fallback)

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

| # | Area | Pitfall | Correct Pattern |
|---|------|---------|-----------------|
| 1 | Config | Adding env var but not to `Settings` dataclass | Add to `Settings` + `from_env()` + `.env.example` |
| 2 | Async | Using blocking I/O (`open()`) in tools | Use `aiofiles.open()` for all file operations |
| 3 | Security | Disabling sandbox for convenience | Keep `SANDBOX_ENABLED=true`; use `resolve_path()` |
| 4 | Tools | Forgetting to register new tool | Add to `_register_tools()` in `agent42.py` |
| 5 | Tests | Hardcoding `/tmp` paths in tests | Use `tmp_path` fixture for test isolation |
| 6 | Providers | Hardcoding premium model as default | Use `FREE_ROUTING` dict, allow admin override via env |
| 7 | Memory | Not handling missing Qdrant/Redis | Check availability before use; fallback to files |
| 8 | Config | `DASHBOARD_HOST=0.0.0.0` exposed directly | Keep `127.0.0.1`; use nginx for external access |
| 9 | JWT | Not setting `JWT_SECRET` in `.env` | Random secret breaks sessions across restarts |
| 10 | Import | Importing optional deps at module level | Conditional import inside function/method body |
| 11 | Tools | Missing `**kwargs` in `execute()` signature | Always include `**kwargs` for forward compatibility |
| 12 | Security | Logging API keys or tokens | Never log secrets — even at DEBUG level |
| 13 | Shell | Using `subprocess.run(shell=True)` in tools | Route through `CommandFilter` and `Sandbox` |
| 14 | Config | Boolean env vars with wrong parsing | Use `.lower() in ("true", "1", "yes")` pattern |
| 15 | Tasks | Using wrong `TaskType` enum value | Check `core/task_queue.py` for valid values |
| 16 | Catalog | `CatalogEntry.to_dict()` format mismatch with `__init__` | `to_dict()` must output `{"id": ..., "pricing": {"prompt": ..., "completion": ...}}` matching constructor format |
| 17 | Tests | Floating-point equality in composite scores | Use `pytest.approx()` for float comparisons, not `==` |
| 18 | Init Order | `ModelEvaluator` must init before `Learner` | Learner takes `model_evaluator` param — ensure correct order in `agent42.py` |
| 19 | Extensions | `ToolExtension.extends` must match an already-registered tool name | Extensions for nonexistent tools are silently skipped with a warning |
| 20 | Tests | `cryptography` panics with `_cffi_backend` error | Install `cffi` (`pip install cffi`) before running dashboard/auth tests |
| 21 | Apps | App entry point missing PORT/HOST env var reading | Always read `os.environ.get("PORT", "8080")` — AppManager sets these |
| 22 | Apps | New `TaskType` not in `FREE_ROUTING` dict | Add routing entry to `agents/model_router.py` `FREE_ROUTING` for every new TaskType |
| 23 | Formatting | CI fails with `ruff format --check` after merge | Always run `make format` (or `ruff format .`) before committing — especially after merges that touch multiple files |
| 24 | Deploy | Hardcoded domain/port in install scripts and nginx config | Use `__DOMAIN__`/`__PORT__` placeholders in `nginx-agent42.conf`; `install-server.sh` prompts for values and sed-replaces |
| 25 | Deploy | Install scripts leak interactive output when composed | Use `--quiet` flag when calling `setup.sh` from `install-server.sh` to suppress banners and prompts |
| 26 | Dashboard | CSP `script-src 'self'` blocks all inline event handlers (`onclick`, `onsubmit`) | CSP must include `'unsafe-inline'` in `script-src` because `app.js` uses innerHTML with 55+ inline handlers |
| 27 | Startup | `agent42.log` owned by root (from systemd) blocks `deploy` user startup | Catch `PermissionError` on `FileHandler`; fall back to stdout-only logging |
| 28 | Auth | `passlib 1.7.4` crashes with `bcrypt >= 4.1` (wrap-bug detection hashes >72-byte secret) | Use `bcrypt` directly via `_BcryptContext` wrapper in `dashboard/auth.py`; do not use `passlib` |
| 29 | Tokens | `router.complete()` returns `(str, dict\|None)` tuple, not plain `str` | Always unpack: `text, usage = await router.complete(...)` or `text, _ = ...` if usage not needed |
| 30 | Session | `SessionManager.get_messages()` does not exist — use `get_history()` | Call `get_history(channel_type, channel_id, max_messages=N)` instead |
| 31 | Scope | Scope detection LLM call adds latency to every message | Scope check only runs when an active scope exists and task is not yet DONE/FAILED |
| 32 | Interview | New `TaskType.PROJECT_SETUP` not in `_TASK_TYPE_KEYWORDS` — it's triggered via complexity gating, not keywords | Detection flows through `ComplexityAssessor.needs_project_setup` and `IntentClassifier.needs_project_setup`, not keyword matching |
| 33 | Interview | Project interview tool stores state in `PROJECT.json` — if outputs dir changes, sessions are lost | Always use `settings.outputs_dir` consistently; sessions are keyed by `project_id` subdirectory |
| 34 | Dataclass | Duplicate field name in a `@dataclass` silently shadows the first definition — Python does not raise an error | Search for duplicate field names when adding fields to `Task` or other dataclasses; ruff does not catch this |
| 35 | Subprocess | `asyncio.wait_for(proc.communicate(), timeout=N)` cancels the coroutine but orphans the subprocess on `TimeoutError` | Always wrap in `try/except TimeoutError`, then call `proc.kill()` + `await proc.wait()` to reap the process |
| 36 | Async | `asyncio.get_event_loop()` is deprecated since Python 3.10; raises `DeprecationWarning` and may fail if no current loop | Use `asyncio.get_running_loop()` inside coroutines; use `asyncio.new_event_loop()` in non-async startup code |
| 37 | Tokens | CLAUDE.md loaded on every API call wastes ~5K tokens of rarely-needed reference content | Reference docs extracted to `.claude/reference/` and loaded on-demand by `context-loader.py` hook |
| 38 | Providers | `_build_client()` reading `settings.xxx_api_key` misses admin-configured keys — `settings` is frozen at import time, before `KeyStore.inject_into_environ()` runs | Use `os.getenv(spec.api_key_env, "")` in `_build_client()` and related methods so runtime admin keys are picked up |
| 39 | Fallback | `_complete_with_retry` retried 401 auth errors 3×, wasting quota; fallback chain only tried OpenRouter models even when Gemini/OpenAI keys were set | `_is_auth_error()` skips retries like 404 does; `_get_fallback_models()` appends native provider models (Gemini, OpenAI, etc.) when their `api_key_env` is set; fallback loop continues on all errors instead of breaking early |
| 40 | Debugging | Spending hours tracing production failures through code before checking server logs | **Always run `tail -100 ~/agent42/agent42.log` and `journalctl -u agent42 -n 100 --no-pager` first** — the log nearly always pinpoints the exact failure in seconds |
| 41 | Init | `Agent42.__init__()` calls `self.task_queue.on_update(self._on_task_update)` but `_on_task_update` was stripped from `origin/main` — service crashes with `AttributeError` and exits code 0 | Restore `agent42.py` from the branch: `git fetch origin && git checkout origin/dev -- agent42.py && sudo systemctl restart agent42` |

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

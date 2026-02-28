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
| 42 | Routing | `limit_remaining: null` in OR API misread as "no credits" | `null` = no per-key limit (uses account balance); only `0.0` = exhausted; always check `is_free_tier` first |
| 43 | Routing | Policy routing overrides dynamic routing results | Policy only runs when `dynamic` is None; dynamic routing takes precedence |
| 44 | Catalog | OR pricing is per-token not per-million | Multiply by 1,000,000 before comparing to $/M thresholds |
| 45 | Routing | "balanced" mode degrades silently to free-only when OR balance check fails | Network error on `/api/v1/auth/key` always returns `is_free_tier=True` — safe but silent; check logs for `"Failed to check OpenRouter account"` warnings |
| 46 | Embeddings | OpenRouter `/embeddings` endpoint returns 401 "User not found" for free-tier keys | Auto-detect skips OpenRouter; only OpenAI is used for embeddings. Set `OPENAI_API_KEY` or explicit `EMBEDDING_PROVIDER` |
| 47 | Embeddings | `build_context_semantic` crashes the entire task when embedding API fails at runtime | Wrapped `embeddings.search()` in try/except; falls back to `build_context()` on failure |
| 48 | Providers | `ProviderRegistry._clients` cached stale API keys forever — admin key updates had no effect | `get_client()` now tracks the key used per client and rebuilds when `os.environ` key changes |
| 49 | Retry | OpenAI SDK default `max_retries=2` adds ~2s of hidden retries before our code sees a 429 | Set `max_retries=0` in `_build_client()` — our `_complete_with_retry` handles retries/fallback |
| 50 | Routing | Gemini daily quota exhaustion (`limit: 0`) retried every iteration — 5-7s waste per call | `_failed_models` set tracks 429/404 models per-task; subsequent iterations skip them instantly |
| 51 | Fallback | `_get_fallback_models` included `gemini-2-flash` even when it just failed as primary (same-provider retry) | `_failed_models` propagated to `exclude` param — models that failed in any iteration are excluded from all fallbacks |
| 52 | Catalog | `or-free-devstral` free period ended (404 "free Devstral 2 period has ended") | Replaced with `or-free-qwen-coder` (Qwen3 Coder 480B) in all FREE_ROUTING critic slots |
| 53 | Retry | OpenRouter 402 "API key USD spend limit exceeded" from Venice backend not caught — fell through to generic retry | Added `_is_payment_error()` detecting 402/spend-limit; skips retries + adds to `_failed_models` like 429 |
| 54 | Registry | Dead `or-free-devstral` still in MODELS dict — appeared in fallback list via `free_models()` even after removal from FREE_ROUTING | Removed from MODELS; removing from FREE_ROUTING alone is not enough — `_get_fallback_models` iterates all free models |
| 55 | Security | OWASP/secrets scanner flags test files, security tools, and dashboard frontend as false positive vulnerabilities (177 CRITICAL) | Added `_SCAN_EXCLUDE_DIRS`, `_SCAN_EXCLUDE_FILES`, `_OWASP_EXCLUDE_DIRS` to `security_analyzer.py`; removed duplicate innerHTML regex; fixed overly-broad f-string SQL regex matching "deleted"/"updated" |
| 56 | Registry | 5 dead OpenRouter free models still in MODELS dict — 404s on every health check and appeared in fallback lists | Remove dead models from MODELS dict AND static fallback list in `iteration_engine.py`; pitfall #54 only covered devstral, same pattern recurred for deepseek-r1, llama4-maverick, gemini-flash, gemini-pro |
| 57 | Tools | `test_runner.py` uses `"python"` but production server only has `python3` — `FileNotFoundError: No such file or directory: 'python'` | Use `sys.executable` instead of hardcoded `"python"` for subprocess calls |
| 58 | Providers | `gemini-2.0-flash` deprecated by Google (404 "no longer available to new users") — all 15 task types fail on primary model | Updated `MODELS["gemini-2-flash"]` model_id to `gemini-2.5-flash`; internal key `gemini-2-flash` unchanged |
| 59 | RLM | `rlm.completion()` is synchronous — calling it directly blocks the async event loop | Always wrap in `loop.run_in_executor(None, lambda: rlm.completion(...))` with `asyncio.wait_for` timeout |
| 60 | RLM | RLM recursive sub-calls can produce runaway costs (10x+ expected) | Enforce `RLM_COST_LIMIT` per query and check global `SpendingTracker` before each RLM call |
| 61 | RLM | `rlms` package not installed but `RLM_ENABLED=true` — import fails at runtime | All `from rlm import ...` is inside method bodies behind try/except ImportError; `should_use_rlm()` returns False gracefully |
| 62 | Tools | `_run_tool_loop` re-fetched `all_schemas()` every round, bypassing task-type filtering — non-code tasks got code tools after first tool call | Use `schemas_for_task_type(task_type)` in the tool loop instead of `all_schemas()` |
| 63 | Tools | Free LLMs hallucinate tool calls not in schema — `_execute_tool_calls` had no task-type guard | Added execution-time enforcement: `_CODE_ONLY_TOOLS` blocked for non-`_CODE_TASK_TYPES` in `_execute_tool_calls()` |
| 64 | Async | `SessionManager.add_message()` and `set_active_scope()` used blocking `open()` from async handlers | Converted write-path methods to async with `aiofiles`; callers must use `await` |
| 65 | Tasks | ASSIGNED tasks never re-queued on restart — only RUNNING was reset to PENDING | `load_from_file()` now resets both RUNNING and ASSIGNED to PENDING |
| 66 | Memory | Memory is global — all tasks write to one MEMORY.md regardless of project | Use `ProjectMemoryStore` (created per-project under `projects_dir/{id}/`); falls through to global for standalone tasks |
| 67 | Critic | Critic only sees task + output text — misses tool usage context | `_critic_pass` now receives `tool_records` and `iteration_num`; includes compact tool summary for the critic |
| 68 | Context | Tool results accumulate unbounded in iteration loop — context rot | `_compact_tool_messages` truncates old tool messages to 200 chars when total exceeds 50K chars; last 2 tool messages kept intact |
| 69 | Teams | Team/subagent tasks don't inherit `project_id` — learnings scatter to global | `TeamTool`, `SubagentTool`, and manager tasks now propagate `project_id` from parent context |
| 70 | Tiers | L2 enabled but no premium API key set — L2 runs on suggested defaults that may lack keys | `get_l2_routing()` verifies API key availability; returns None if premium key not set → L2 button hidden in dashboard |
| 71 | Escalation | L2 task fails — original L1 task stuck forever | L2 task failure handler in `_on_task_update()` resets L1 source task back to REVIEW status |
| 72 | Conversation | `_direct_response()` blocks event loop if model is slow | Wrapped in `asyncio.wait_for()` with 30s timeout; falls back to task creation on timeout/error |
| 73 | Teams | Team roles inherit tier from parent — L2 team = all premium tokens | Team roles default to L1 via `TeamContext.tier`; only explicitly configured roles use L2 |
| 74 | Serialization | `tier` field not surviving Task persist/restore | `to_dict()`/`from_dict()` handles via `asdict()` — new string fields serialize automatically |
| 75 | Comments | Task comments (`POST /api/tasks/{id}/comment`) were stored but never routed to the running agent or broadcast to chat | Comment endpoint now calls `route_message_to_task()` for active tasks, broadcasts `task_update`, and mirrors to chat session via `chat_message` event |
| 76 | Plans | Manager LLM returns free-text instead of JSON `PlanSpecification` | Always fall back to legacy unstructured path; parse with try/except in `_parse_plan_json()` |
| 77 | Waves | Circular dependencies in plan tasks cause infinite loop in `compute_waves()` | Topological sort must detect cycles and raise `ValueError` — tested in `test_plan_spec.py` |
| 78 | State | `STATE.md` grows unbounded with `accumulated_context` field | Cap at `_MAX_ACCUMULATED_CONTEXT_CHARS` (10K chars); `StateManager.save_state()` enforces this |
| 79 | Context | Context budget estimation uses chars/4 approximation, not actual tokens | Sufficient for threshold detection (50%/70%); not for exact token accounting |
| 80 | Context | Context overflow "error" strategy returns empty output when `primary_output` is still `""` | Guard: `if not primary_output.strip(): primary_output = "Context too large..."` before setting `history.final_output` |
| 81 | Chat | Agent processes dashboard chat messages in isolation — no conversation history | Pass `chat_session_manager` to Agent; load history in `_build_context()` via `origin_metadata["chat_session_id"]` |

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

# Phase 24: Sidecar Mode - Research

**Researched:** 2026-03-28
**Domain:** FastAPI sidecar server, async callback pattern, JWT auth reuse, stdlib JSON logging
**Confidence:** HIGH — all decisions lock to existing codebase patterns; no new dependencies required

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Sidecar is `create_sidecar_app()` in `dashboard/sidecar.py` — new FastAPI instance, NOT an extension of `create_app()`
- **D-02:** `--sidecar` adds a third execution mode to `Agent42.start()` which branches to mount `create_sidecar_app()` on sidecar port; `__init__()` core service initialization is identical across all modes (SIDE-08)
- **D-03:** Standalone mode must not regress — sidecar is additive
- **D-04:** Reuse `get_current_user` / HTTPBearer JWT dependency from `dashboard/auth.py` — no new auth mechanism
- **D-05:** `GET /sidecar/health` is exempt from Bearer auth (matches `/health` public pattern)
- **D-06:** Use `httpx.AsyncClient` for callback POST — httpx is established across 15+ files
- **D-07:** Callback URL derived from `PAPERCLIP_API_URL` env var
- **D-08:** In-memory dict keyed by runId with TTL-based expiry for dedup — matches `AgentRuntime._processes` pattern
- **D-09:** Custom stdlib `logging.Formatter` subclass outputting JSON lines when `--sidecar` active — no structlog (zero new dependencies)
- **D-10:** Existing `_ANSI_ESCAPE` pattern from `dashboard/server.py` reused for clean JSON output

### Claude's Discretion

- Exact Pydantic model field names for AdapterExecutionContext (align with Paperclip TypeScript types)
- TTL duration for runId expiry in the idempotency dict
- Exact JSON log field names (timestamp, level, logger, message, etc.)
- Internal error response format for sidecar endpoints

### Deferred Ideas (OUT OF SCOPE)

None — analysis stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| SIDE-01 | Agent42 starts in sidecar mode via `--sidecar` flag, no dashboard UI | argparse extension in `agent42.py`; `Agent42.__init__()` unchanged; `start()` branches |
| SIDE-02 | Sidecar accepts heartbeat execution requests via `POST /sidecar/execute` with Paperclip's AdapterExecutionContext payload | Pydantic model for payload; FastAPI route in `dashboard/sidecar.py` |
| SIDE-03 | Sidecar returns 202 Accepted for long-running tasks and POSTs results to callback endpoint when done | `asyncio.create_task()` for background execution; `httpx.AsyncClient` for callback |
| SIDE-04 | Sidecar exposes `GET /sidecar/health` returning memory, provider, Qdrant connectivity status | Public endpoint (no auth); checks MemoryStore, QdrantStore, provider config |
| SIDE-05 | Sidecar validates Bearer token auth on all endpoints except health | `get_current_user` dependency from `dashboard/auth.py` — direct reuse |
| SIDE-06 | Sidecar deduplicates execution requests by `runId` | In-memory `dict[str, float]` (runId → expiry timestamp); TTL cleanup on access |
| SIDE-07 | Sidecar produces structured JSON logging (no ANSI, no spinners) | stdlib `logging.Formatter` subclass; `_ANSI_ESCAPE` stripping |
| SIDE-08 | Core services start identically in sidecar and dashboard modes | `Agent42.__init__()` untouched; only `start()` branches |
| SIDE-09 | Config extends with `PAPERCLIP_SIDECAR_PORT`, `PAPERCLIP_API_URL`, `SIDECAR_ENABLED` | Add fields to `Settings` dataclass + `from_env()` + `.env.example` documentation |
</phase_requirements>

---

## Summary

Phase 24 creates a minimal FastAPI sidecar server that Paperclip operators use as an HTTP execution backend for their agents. The sidecar receives `AdapterExecutionContext` payloads via `POST /sidecar/execute`, returns 202 Accepted, executes the task asynchronously via `AgentRuntime`, and POSTs results back to Paperclip's callback URL. All core Agent42 services (MemoryStore, QdrantStore, AgentRuntime, EffectivenessStore) initialize identically in both dashboard and sidecar modes — sidecar omits only the dashboard UI, WebSocket management, and static file serving.

The implementation is entirely within existing Python dependencies. No new packages are required: FastAPI, Pydantic v2, httpx, uvicorn, and python-jose are all already installed and in use. The auth mechanism (`get_current_user` / HTTPBearer) is reused verbatim from `dashboard/auth.py`. JSON logging is achieved with a stdlib `logging.Formatter` subclass, following D-09.

The primary planning challenge is ensuring a clean separation between the new `dashboard/sidecar.py` app factory and the existing `dashboard/server.py`, and wiring the `--sidecar` CLI flag through `agent42.py` without touching the headless/dashboard code paths.

**Primary recommendation:** Implement `create_sidecar_app()` as a standalone FastAPI factory in `dashboard/sidecar.py` that takes the same core service objects as `create_app()` but mounts only the 4 sidecar routes. Wire it to a new `sidecar` branch in `Agent42.start()` and add `--sidecar` + `--sidecar-port` to the CLI parser.

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | 0.134.0 | Sidecar HTTP server | Already used for full dashboard |
| Pydantic | 2.12.5 | AdapterExecutionContext model, response models | Already used throughout codebase |
| uvicorn | 0.41.0 | ASGI server for sidecar | Already used for dashboard startup |
| httpx | 0.28.1 | Async callback POST to Paperclip | Already used in 15+ files; D-06 locks this |
| python-jose | 3.5.0 | JWT validation (via existing auth.py) | Already used; reused via `get_current_user` |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| asyncio (stdlib) | Python 3.14.3 | `create_task()` for fire-and-forget execution | For 202 pattern + idempotency TTL cleanup |
| logging (stdlib) | Python 3.14.3 | JSON formatter for structured logs (D-09) | Always in sidecar mode |
| re (stdlib) | Python 3.14.3 | ANSI stripping in log formatter (D-10) | Part of JSON formatter |
| time (stdlib) | Python 3.14.3 | TTL-based runId expiry | Part of idempotency guard |

### Alternatives Considered

Per CONTEXT.md locked decisions — no alternatives were explored.

**Version verification:** Verified via `pip show` on 2026-03-28 in project virtualenv.

---

## Architecture Patterns

### Recommended Project Structure

The new files for this phase:

```
agent42/
├── agent42.py              # EXTEND: --sidecar + --sidecar-port args; sidecar branch in start()
├── dashboard/
│   └── sidecar.py          # NEW: create_sidecar_app() factory with 4 routes
├── core/
│   ├── sidecar_orchestrator.py  # NEW: drives execute → callback cycle
│   └── config.py           # EXTEND: PAPERCLIP_SIDECAR_PORT, PAPERCLIP_API_URL, SIDECAR_ENABLED
└── .env.example            # EXTEND: document new sidecar config vars
```

### Pattern 1: Sidecar App Factory (mirrors existing create_app pattern)

**What:** `create_sidecar_app()` takes the same core service arguments as `create_app()` but creates a lightweight FastAPI instance with only 4 routes and no static file middleware.

**When to use:** Called from `Agent42.start()` when `self.sidecar` is True.

**Example:**
```python
# dashboard/sidecar.py
from fastapi import FastAPI, Depends, HTTPException, status, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dashboard.auth import get_current_user

def create_sidecar_app(
    memory_store,
    agent_manager,
    effectiveness_store,
    reward_system,
    **kwargs,
) -> FastAPI:
    app = FastAPI(title="Agent42 Sidecar", docs_url=None, redoc_url=None)

    # Only sidecar routes — no static files, no WebSocket manager
    @app.get("/sidecar/health")  # Public — no auth (D-05)
    async def sidecar_health(): ...

    @app.post("/sidecar/execute")  # Bearer auth required (D-04)
    async def sidecar_execute(
        ctx: AdapterExecutionContext,
        background_tasks: BackgroundTasks,
        _user: str = Depends(get_current_user),
    ): ...

    return app
```

### Pattern 2: 202 Accepted with Async Callback

**What:** `POST /sidecar/execute` immediately returns 202 Accepted with `{externalRunId: runId}`, then spawns an `asyncio.create_task()` to execute the agent and POST results to Paperclip's callback URL.

**When to use:** All sidecar execution requests (tasks always run longer than an HTTP timeout window).

**Data flow:**
```
POST /sidecar/execute
    → idempotency check (runId in _active_runs) → 200 if duplicate
    → register runId in _active_runs dict
    → 202 Accepted returned immediately
    → asyncio.create_task(orchestrator.execute_async(runId, ctx))
        → AgentRuntime.start_agent(agent_config)  [existing]
        → await monitor process completion
        → POST PAPERCLIP_API_URL/api/heartbeat-runs/{runId}/callback
        → pop runId from _active_runs
```

**Example:**
```python
@app.post("/sidecar/execute", status_code=202)
async def sidecar_execute(
    ctx: AdapterExecutionContext,
    background_tasks: BackgroundTasks,
    _user: str = Depends(get_current_user),
):
    if ctx.runId in _active_runs and time.time() < _active_runs[ctx.runId]:
        return {"status": "accepted", "externalRunId": ctx.runId, "deduplicated": True}
    _active_runs[ctx.runId] = time.time() + RUN_TTL_SECONDS
    background_tasks.add_task(orchestrator.execute_async, ctx.runId, ctx)
    return {"status": "accepted", "externalRunId": ctx.runId}
```

Note: `BackgroundTasks` from FastAPI is preferred over raw `asyncio.create_task()` here because FastAPI handles task lifecycle within the request context properly.

### Pattern 3: Idempotency Guard

**What:** Module-level `dict[str, float]` maps `runId → expiry_timestamp`. On each request, expired entries are pruned.

**When to use:** Every POST to `/sidecar/execute`.

**Example:**
```python
_active_runs: dict[str, float] = {}
RUN_TTL_SECONDS = 3600  # 1 hour (Claude's discretion on exact value)

def _prune_expired_runs():
    now = time.time()
    expired = [k for k, exp in _active_runs.items() if exp < now]
    for k in expired:
        del _active_runs[k]
```

### Pattern 4: Stdlib JSON Formatter (D-09/D-10)

**What:** A `logging.Formatter` subclass that writes JSON lines. Applied only when `--sidecar` is active. Uses the `_ANSI_ESCAPE` regex from `dashboard/server.py` to strip ANSI codes from log messages.

**When to use:** Installed as the root logger's formatter in sidecar startup only.

**Example:**
```python
import json, logging, re, time

_ANSI_ESCAPE = re.compile(r"\x1b\[[0-9;]*[mGKHF]")

class SidecarJsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        message = _ANSI_ESCAPE.sub("", record.getMessage())
        return json.dumps({
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(record.created)),
            "level": record.levelname,
            "logger": record.name,
            "message": message,
        })
```

### Pattern 5: Pydantic v2 AdapterExecutionContext Model

**What:** Pydantic v2 `BaseModel` matching Paperclip's TypeScript heartbeat payload shape.

**Example:**
```python
from pydantic import BaseModel
from typing import Any

class AdapterConfig(BaseModel):
    sessionKey: str = ""
    memoryScope: str = "agent"
    preferredProvider: str = ""
    agentId: str = ""

class AdapterExecutionContext(BaseModel):
    runId: str
    agentId: str
    companyId: str = ""
    taskId: str = ""
    wakeReason: str = "heartbeat"  # heartbeat | task_assigned | manual
    context: dict[str, Any] = {}
    adapterConfig: AdapterConfig = AdapterConfig()
```

Field names follow Paperclip's camelCase TypeScript convention. The planner should align exact fields with Paperclip's actual TypeScript types (Claude's discretion per CONTEXT.md).

### Pattern 6: Agent42.start() Sidecar Branch

**What:** `Agent42.__init__()` accepts a `sidecar: bool` parameter alongside `headless`. `start()` uses `if self.sidecar` to mount `create_sidecar_app()` on the sidecar port instead of the full dashboard.

**Example:**
```python
# agent42.py — Agent42 class
def __init__(self, dashboard_port=8000, headless=False, sidecar=False,
             sidecar_port=8001):
    self.dashboard_port = dashboard_port
    self.headless = headless
    self.sidecar = sidecar
    self.sidecar_port = sidecar_port
    # ... IDENTICAL core service initialization (SIDE-08) ...

async def start(self):
    # ... existing shared startup (repo_manager, heartbeat, tier_recalc, cron) ...

    if self.sidecar:
        from dashboard.sidecar import create_sidecar_app
        app = create_sidecar_app(memory_store=self.memory_store, ...)
        config = uvicorn.Config(app, host=settings.dashboard_host,
                                port=self.sidecar_port, log_level="warning")
        tasks_to_run.append(uvicorn.Server(config).serve())
    elif not self.headless:
        # existing dashboard path (D-03: no regression)
        app = create_app(...)
        tasks_to_run.append(uvicorn.Server(...).serve())
```

### Anti-Patterns to Avoid

- **Extending `create_app()` with a sidecar flag:** D-01 locks against this. Sidecar is a separate factory.
- **Adding new auth middleware:** D-04 locks reuse of `get_current_user` from `dashboard/auth.py`.
- **Using `structlog` or third-party logging libs:** D-09 locks stdlib formatter only.
- **Database table for runId dedup:** D-08 locks in-memory dict. No SQLite table.
- **Blocking the 202 response with agent work:** The `asyncio.create_task()` / `BackgroundTasks` pattern must be used; never `await` the execution in the route handler.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| JWT validation | Custom token parser | `get_current_user` from `dashboard/auth.py` | D-04 locked; existing handles expiry, API keys, error codes |
| HTTP callbacks | Custom retry/session | `httpx.AsyncClient` | D-06 locked; httpx handles pooling, timeouts, redirects |
| Async task queue | Custom worker pool | `asyncio.create_task()` / `BackgroundTasks` | Sufficient for single-node; matches existing patterns in codebase |
| ANSI stripping | New regex | `_ANSI_ESCAPE` pattern from `dashboard/server.py` | D-10 locked; already tested in production |

**Key insight:** Every significant component in this phase already exists in the codebase. Sidecar is assembly, not invention.

---

## Common Pitfalls

### Pitfall 1: get_current_user vs get_auth_context (naming confusion)

**What goes wrong:** CONTEXT.md mentions both `get_current_user` and `_validate_jwt`. Developers may try to use `get_auth_context` directly and miss that `get_current_user` is the correct FastAPI dependency for route handlers.

**Why it happens:** `auth.py` has three related functions: `get_auth_context` (returns full `AuthContext`), `get_current_user` (returns `str` username, used in most routes), `require_admin` (JWT-only, no API keys). Dashboard routes use `get_current_user`.

**How to avoid:** Use `get_current_user` in all sidecar route handlers that require auth. It returns the username string and raises `HTTP_401_UNAUTHORIZED` automatically.

**Warning signs:** Route handler type hint is `AuthContext` instead of `str`.

### Pitfall 2: Standalone Mode Regression (P6)

**What goes wrong:** Adding `sidecar` parameter to `Agent42.__init__()` with a poor default causes existing `python agent42.py` invocations to behave differently.

**Why it happens:** If `sidecar=False` is not explicitly the default, or if `start()` branch logic accidentally gates on `not self.sidecar` instead of `not self.headless`, the dashboard stops loading.

**How to avoid:** Default `sidecar=False`. The `start()` branch is: `if self.sidecar → sidecar mode; elif not self.headless → dashboard mode; else → headless mode`. Test all three modes.

**Warning signs:** Dashboard returns 404 on static routes, or starts on wrong port.

### Pitfall 3: Background Task vs create_task Scope

**What goes wrong:** Using `asyncio.create_task()` directly in a route handler creates a task that is not tied to the FastAPI lifecycle. If the task raises an unhandled exception, it disappears silently.

**Why it happens:** `asyncio.create_task()` is fire-and-forget without supervision. FastAPI's `BackgroundTasks` is better for request-scoped background work because FastAPI manages their lifecycle.

**How to avoid:** Use `background_tasks.add_task(fn, ...)` via `BackgroundTasks` parameter in the route signature for the execution callback. Reserve `asyncio.create_task()` for truly process-lifetime tasks (like the existing `EffectivenessStore` pattern).

**Warning signs:** Callback never fires; no error logged either.

### Pitfall 4: Idempotency TTL Not Pruned

**What goes wrong:** The `_active_runs` dict grows unboundedly if expired entries are never removed.

**Why it happens:** Simple dict append without cleanup loop.

**How to avoid:** Call `_prune_expired_runs()` at the start of every `POST /sidecar/execute` handler. This is O(n) but n is small (bounded by concurrent runs × TTL window).

**Warning signs:** Memory growth over time in long-running sidecar.

### Pitfall 5: JSON Logging Applied to All Modes

**What goes wrong:** If `SidecarJsonFormatter` is installed as a global logger change, standalone dashboard mode loses its human-readable log format.

**Why it happens:** Logging is global in Python; reconfiguring root logger affects all handlers.

**How to avoid:** Install JSON formatter only when `--sidecar` is active, in the `main()` function before `Agent42` is constructed. Store original handlers and restore on shutdown if needed.

**Warning signs:** Dashboard logs appear as JSON blobs in terminal.

### Pitfall 6: httpx Client Not Closed

**What goes wrong:** `httpx.AsyncClient` used for callbacks is never closed, leading to connection pool leaks and ResourceWarning in tests.

**Why it happens:** Async context managers require `async with` or explicit `.aclose()`.

**How to avoid:** Create the client once at `SidecarOrchestrator.__init__()` as `self._http = httpx.AsyncClient()` and call `await self._http.aclose()` in a `shutdown()` method. Alternatively, use `async with httpx.AsyncClient() as client:` inside the callback function.

**Warning signs:** `ResourceWarning: unclosed <AsyncClient>` in test output.

### Pitfall 7: Windows CRLF in Future TypeScript Artifacts (P5)

**What goes wrong:** Not a Phase 24 risk for Python files, but if any `.gitattributes` changes are made alongside this phase, incorrect eol settings could affect future TypeScript adapter packages.

**Why it happens:** Git on Windows auto-converts LF to CRLF without `.gitattributes`.

**How to avoid:** Phase 24 is Python-only. No `.gitattributes` changes needed unless TypeScript files are introduced.

**Warning signs:** N/A for this phase.

---

## Code Examples

Verified patterns from existing codebase:

### Existing headless mode branch (model for sidecar branch)

```python
# From agent42.py lines 236-270 — existing pattern sidecar extends:
if not self.headless:
    app = create_app(
        ws_manager=self.ws_manager,
        tool_registry=self.tool_registry,
        # ... 13 more params
    )
    config = uvicorn.Config(app, host=settings.dashboard_host,
                            port=self.dashboard_port, log_level="warning")
    server = uvicorn.Server(config)
    tasks_to_run.append(server.serve())
```

### Existing JWT auth dependency in route handlers

```python
# From dashboard/server.py line 541 — pattern to replicate in sidecar:
@app.get("/api/health")
async def health_detail(_user: str = Depends(get_current_user)):
    ...

# Public health endpoint — no auth (model for /sidecar/health):
@app.get("/health")
async def health_check():
    return {"status": "ok"}
```

### Existing fire-and-forget pattern (asyncio.create_task)

```python
# From core/agent_runtime.py line 151:
asyncio.create_task(self._monitor(agent_id, proc, log_file))

# From core/reward_system.py line 399:
self._task = asyncio.create_task(self._recalc_loop())
```

### Existing Settings extension pattern

```python
# From core/config.py — dataclass field + from_env() pattern:
@dataclass(frozen=True)
class Settings:
    rewards_enabled: bool = False  # example field
    # ...

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            rewards_enabled=os.getenv("REWARDS_ENABLED", "false").lower() in ("true", "1"),
            # ...
        )
```

New sidecar fields to add:
```python
# In Settings dataclass:
paperclip_sidecar_port: int = 8001
paperclip_api_url: str = ""
sidecar_enabled: bool = False

# In from_env():
paperclip_sidecar_port=int(os.getenv("PAPERCLIP_SIDECAR_PORT", "8001")),
paperclip_api_url=os.getenv("PAPERCLIP_API_URL", ""),
sidecar_enabled=os.getenv("SIDECAR_ENABLED", "false").lower() in ("true", "1"),
```

---

## Project Constraints (from CLAUDE.md)

Directives the planner must verify compliance with:

1. **All I/O is async** — sidecar route handlers must be `async def`; httpx callback must use `await` and `AsyncClient`
2. **Frozen config** — new sidecar fields go in `Settings` dataclass in `core/config.py` + `from_env()` + `.env.example`
3. **Graceful degradation** — sidecar must handle missing `PAPERCLIP_API_URL` gracefully (log warning, skip callback)
4. **Sandbox always on** — `sandbox.resolve_path()` if any file paths involved; sidecar does not write files directly so N/A for most routes
5. **No blocking I/O** — `httpx.AsyncClient` (not requests), no sync file reads in route handlers
6. **Security** — Bearer token required on all sidecar endpoints except health (D-04/D-05); NEVER log Bearer token values
7. **Test coverage** — new module `dashboard/sidecar.py` needs `tests/test_sidecar.py`
8. **New pitfalls** — add non-obvious issues discovered during implementation to `.claude/reference/pitfalls-archive.md`

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | `pytest.ini` or `pyproject.toml` (check root) |
| Quick run command | `python -m pytest tests/test_sidecar.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SIDE-01 | `--sidecar` starts server without dashboard UI | smoke | `python -m pytest tests/test_sidecar.py::test_sidecar_mode_no_dashboard -x` | Wave 0 |
| SIDE-02 | POST /sidecar/execute accepts AdapterExecutionContext | unit | `python -m pytest tests/test_sidecar.py::test_execute_accepts_payload -x` | Wave 0 |
| SIDE-03 | POST /sidecar/execute returns 202 Accepted | unit | `python -m pytest tests/test_sidecar.py::test_execute_returns_202 -x` | Wave 0 |
| SIDE-04 | GET /sidecar/health returns structured JSON | unit | `python -m pytest tests/test_sidecar.py::test_health_returns_json -x` | Wave 0 |
| SIDE-05 | Endpoints reject missing/invalid Bearer token with 401 | unit | `python -m pytest tests/test_sidecar.py::test_auth_required -x` | Wave 0 |
| SIDE-05 | Health endpoint accessible without auth | unit | `python -m pytest tests/test_sidecar.py::test_health_no_auth -x` | Wave 0 |
| SIDE-06 | Duplicate runId returns without re-executing | unit | `python -m pytest tests/test_sidecar.py::test_idempotency_guard -x` | Wave 0 |
| SIDE-07 | JSON log formatter outputs valid JSON, no ANSI | unit | `python -m pytest tests/test_sidecar.py::test_json_formatter -x` | Wave 0 |
| SIDE-08 | Core services init identically in sidecar/dashboard modes | unit | `python -m pytest tests/test_sidecar.py::test_core_services_init -x` | Wave 0 |
| SIDE-09 | Config fields PAPERCLIP_SIDECAR_PORT etc. readable from env | unit | `python -m pytest tests/test_sidecar.py::test_config_fields -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_sidecar.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_sidecar.py` — covers SIDE-01 through SIDE-09 (entire file is new)
- Shared fixtures in `tests/conftest.py` already exist and are sufficient
- No framework installation needed — pytest 9.0.2 already installed

**Test pattern to follow:** `tests/test_auth_flow.py` uses `fastapi.testclient.TestClient` — use same pattern for sidecar tests.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python | All | Yes | 3.14.3 | — |
| FastAPI | Sidecar server | Yes | 0.134.0 | — |
| Pydantic | Request models | Yes | 2.12.5 | — |
| httpx | Callback POST | Yes | 0.28.1 | — |
| uvicorn | ASGI server | Yes | 0.41.0 | — |
| python-jose | JWT (via auth.py) | Yes | 3.5.0 | — |
| pytest | Test suite | Yes | 9.0.2 | — |

**Missing dependencies with no fallback:** None.

**Missing dependencies with fallback:** None.

All required packages confirmed installed in project virtualenv.

---

## Open Questions

1. **AdapterExecutionContext exact field names**
   - What we know: Paperclip sends `{runId, agentId, companyId, taskId, wakeReason, context, adapterConfig}` (from FEATURES.md interface contracts)
   - What's unclear: Whether Paperclip uses camelCase or snake_case; whether `adapterConfig` is a nested object or flat fields
   - Recommendation: Start with camelCase matching Paperclip's TypeScript source; Pydantic v2 supports `model_config = ConfigDict(populate_by_name=True)` if alias mapping is needed

2. **RunId TTL duration**
   - What we know: CONTEXT.md says "TTL-based expiry" — Claude's discretion on exact value
   - What's unclear: What Paperclip's retry window is
   - Recommendation: 1 hour (3600s) is a reasonable default; makes it configurable via `SIDECAR_RUN_TTL_SECONDS` env var

3. **Callback response shape**
   - What we know: ARCHITECTURE.md shows `{status, result: {summary}, usage: {inputTokens, outputTokens, costUsd}}`
   - What's unclear: Whether Paperclip requires additional fields
   - Recommendation: Use the shape from ARCHITECTURE.md; Paperclip ignores unknown fields

4. **`SIDECAR_ENABLED` vs `--sidecar` flag**
   - What we know: Both are listed in SIDE-09 and CONTEXT.md's integration points
   - What's unclear: Whether `SIDECAR_ENABLED` overrides or supplements the CLI flag
   - Recommendation: `--sidecar` CLI flag takes precedence; `SIDECAR_ENABLED=true` in env acts as an alternative activation path (useful for Docker deployments that don't override the CMD)

---

## Sources

### Primary (HIGH confidence)
- Codebase: `agent42.py` — existing `headless` mode pattern, argparse structure, service init
- Codebase: `dashboard/auth.py` — `get_current_user`, `_validate_jwt`, `get_auth_context` signatures
- Codebase: `core/config.py` — `Settings` dataclass, `from_env()` pattern for new fields
- Codebase: `core/agent_runtime.py` — `_processes` dict pattern, `asyncio.create_task` usage
- Codebase: `dashboard/server.py` — `_ANSI_ESCAPE`, `/health` public pattern, `create_app()` structure
- `.planning/phases/24-sidecar-mode/24-CONTEXT.md` — all implementation decisions locked

### Secondary (MEDIUM confidence)
- `.planning/research/ARCHITECTURE.md` — AdapterExecutionContext shape, callback URL pattern, `create_sidecar_app()` sketch
- `.planning/research/FEATURES.md` — heartbeat request/response shapes, interface contracts
- `.planning/research/PITFALLS.md` — P2, P5, P6 relevant to this phase

### Tertiary (LOW confidence)
- None — all claims verifiable from codebase + locked CONTEXT.md decisions

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified via `pip show` in project virtualenv
- Architecture: HIGH — all patterns verified against existing codebase
- Pitfalls: HIGH — P2/P6 from prior project research; pitfalls 1-6 verified from code inspection
- Test requirements: HIGH — pytest TestClient pattern confirmed in `test_auth_flow.py`

**Research date:** 2026-03-28
**Valid until:** 2026-04-28 (stable stack, 30-day window)

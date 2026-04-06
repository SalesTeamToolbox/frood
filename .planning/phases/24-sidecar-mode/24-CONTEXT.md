# Phase 24: Sidecar Mode - Context

**Gathered:** 2026-03-28 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Agent42 runs as a stripped FastAPI sidecar with adapter-friendly endpoints. Running `python agent42.py --sidecar` starts a server with no dashboard UI. A Paperclip operator can POST to `/sidecar/execute` with an AdapterExecutionContext payload, receive 202 Accepted, and get results via callback. Health check, Bearer token auth, idempotency guard, and structured JSON logging are included. Core services (MemoryStore, QdrantStore, AgentRuntime, EffectivenessStore) start identically in both modes.

</domain>

<decisions>
## Implementation Decisions

### Sidecar Server Architecture
- **D-01:** Sidecar is a separate `create_sidecar_app()` function in `dashboard/sidecar.py` — a new FastAPI instance with only sidecar routes, not an extension of the existing `create_app()`
- **D-02:** `--sidecar` flag adds a third execution mode to the `Agent42` class (`start()` method branches to mount `create_sidecar_app()` on the sidecar port), keeping `__init__()` core service initialization identical across all modes (SIDE-08)
- **D-03:** Standalone mode (`python agent42.py` without `--sidecar`) must not regress — sidecar is additive

### Authentication
- **D-04:** Reuse existing `get_current_user` / HTTPBearer JWT dependency from `dashboard/auth.py` for all sidecar endpoints — no new auth mechanism
- **D-05:** `GET /sidecar/health` is the one endpoint exempt from Bearer auth (matches dashboard `/health` pattern, enables Paperclip `testEnvironment()` probe before credentials are provisioned)

### Callback & Async Execution
- **D-06:** Use `httpx.AsyncClient` for callback POST to Paperclip's callback endpoint — httpx is the established HTTP client across 15+ files in the codebase
- **D-07:** Callback URL derived from `PAPERCLIP_API_URL` env var

### Run ID Idempotency
- **D-08:** In-memory dict keyed by runId with TTL-based expiry for dedup guard — matches existing `AgentRuntime._processes` pattern, no database table needed for retry dedup within process lifetime

### Structured JSON Logging
- **D-09:** Custom stdlib `logging.Formatter` subclass outputting JSON lines when `--sidecar` is active — no structlog or third-party logging library (zero new dependencies)
- **D-10:** Existing ANSI stripping pattern from `dashboard/server.py` reused for clean JSON output

### Claude's Discretion
- Exact Pydantic model field names for AdapterExecutionContext (align with Paperclip's actual TypeScript types during implementation)
- TTL duration for runId expiry in the idempotency dict
- Exact JSON log field names (timestamp, level, logger, message, etc.)
- Internal error response format for sidecar endpoints

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` -- SIDE-01 through SIDE-09 define all sidecar requirements
- `.planning/ROADMAP.md` -- Phase 24 success criteria (5 acceptance tests)

### Architecture research
- `.planning/research/ARCHITECTURE.md` -- Full system diagram, component responsibilities, recommended project structure, data flow sequences
- `.planning/research/SUMMARY.md` -- Executive summary, recommended stack, phase ordering rationale
- `.planning/research/FEATURES.md` -- Feature dependency graph, interface contracts, heartbeat request/response shapes
- `.planning/research/PITFALLS.md` -- Critical pitfalls P1-P12 with phase assignments (P2, P5, P6 are Phase 24 relevant)

### Existing codebase (key files to read)
- `agent42.py` -- Entry point, `Agent42` class, `--headless` pattern to follow for `--sidecar`
- `dashboard/server.py` -- `create_app()` function showing what sidecar omits (16 dependency params, 5800+ lines of routes)
- `dashboard/auth.py` -- HTTPBearer JWT auth to reuse (`get_current_user`, `_validate_jwt`)
- `core/config.py` -- `Settings` dataclass and `from_env()` for new config fields
- `core/agent_runtime.py` -- AgentRuntime execution flow and `_processes` dict pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dashboard/auth.py` — Full JWT auth stack (HTTPBearer, token validation, expiry) — reuse directly for SIDE-05
- `core/agent_runtime.py` — AgentRuntime subprocess execution — sidecar's SidecarOrchestrator wraps this
- `core/memory_store.py` / `core/qdrant_store.py` — Memory recall/store APIs — MemoryBridge wraps these
- `core/effectiveness.py` — EffectivenessStore for recording execution outcomes
- `core/rewards.py` — RewardSystem for tier-based model routing (TieredRoutingBridge wraps this)
- `dashboard/server.py:_ANSI_ESCAPE` — Existing ANSI stripping regex for clean log output

### Established Patterns
- **Conditional mode branching:** `headless` bool in `Agent42.__init__()` — sidecar follows same pattern as third mode
- **Core services always init:** MemoryStore, QdrantStore, AgentManager, EffectivenessStore, HeartbeatService init unconditionally in `__init__()`
- **httpx for outbound HTTP:** 15+ files use `httpx.AsyncClient` for external API calls
- **Fire-and-forget tasks:** `asyncio.create_task()` pattern used in EffectivenessStore — MemoryBridge.learn() should follow same pattern
- **Config via Settings dataclass:** All env vars go through `Settings.from_env()` with `.env.example` documentation

### Integration Points
- `Agent42.__init__()` — Add `sidecar: bool` parameter alongside existing `headless`
- `Agent42.start()` — New sidecar branch calling `create_sidecar_app()` + uvicorn on sidecar port
- `core/config.py:Settings` — Add `PAPERCLIP_SIDECAR_PORT`, `PAPERCLIP_API_URL`, `SIDECAR_ENABLED` fields
- `agent42.py` CLI — Add `--sidecar` argparse flag
- `.env.example` — Document new sidecar config variables

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — analysis stayed within phase scope

</deferred>

---

*Phase: 24-sidecar-mode*
*Context gathered: 2026-03-28*

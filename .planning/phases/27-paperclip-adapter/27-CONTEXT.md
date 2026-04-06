# Phase 27: Paperclip Adapter - Context

**Gathered:** 2026-03-30 (assumptions mode, auto)
**Status:** Ready for planning

<domain>
## Phase Boundary

A TypeScript adapter package fully implements Paperclip's ServerAdapterModule interface (execute, testEnvironment) and can be installed in a Paperclip deployment to route agent executions to the Agent42 sidecar. The adapter POSTs to Agent42's sidecar endpoints, handles the 202+callback async pattern, maps wakeReason values, preserves Agent42 agent IDs for memory/effectiveness continuity, and includes a sessionCodec for cross-heartbeat state persistence.

Requirements: ADAPT-01 through ADAPT-05.

</domain>

<decisions>
## Implementation Decisions

### Package Structure
- **D-01:** New `adapters/agent42-paperclip/` directory at repo root — first TypeScript package in the project, isolated from Python codebase
- **D-02:** npm as package manager, TypeScript compiled via `tsc` (no bundler needed — this is a library, not a webapp)
- **D-03:** Flat `src/` layout: `index.ts` (exports), `adapter.ts` (ServerAdapterModule impl), `client.ts` (HTTP client for sidecar), `session.ts` (sessionCodec), `types.ts` (type aliases matching sidecar Pydantic models)
- **D-04:** Target ES2020+ / Node 18+ — Paperclip runs on modern Node.js

### Callback Handling
- **D-05:** Adapter is a thin passthrough — calls `POST /sidecar/execute`, receives 202 Accepted, and returns the accepted response to Paperclip's runner framework
- **D-06:** Agent42 sidecar POSTs callback to `PAPERCLIP_API_URL/api/heartbeat-runs/{runId}/callback` — this is Paperclip's own endpoint, so Paperclip's framework manages the callback lifecycle
- **D-07:** Adapter does NOT run its own callback server or poll — Paperclip's ServerAdapterModule contract handles async result delivery

### Session Codec
- **D-08:** JSON-based sessionCodec encoding `{agentId, lastRunId, executionCount}` into sessionKey string via base64-encoded JSON
- **D-09:** No encryption — adapter communicates over internal network (same host or trusted VPC)
- **D-10:** Codec is forward-compatible: unknown fields in decoded JSON are preserved (spread operator), enabling future state additions without schema migration

### Wake Reason Mapping
- **D-11:** Adapter passes wakeReason string directly to sidecar in AdapterExecutionContext — sidecar already logs and handles behavioral differentiation
- **D-12:** Adapter validates wakeReason is one of known values (heartbeat, task_assigned, manual) and logs a warning on unknown values but does not reject

### Agent ID Preservation
- **D-13:** `adapterConfig.agentId` maps directly to Agent42's `agent_id` field — no ID transformation or mapping layer
- **D-14:** Adapter extracts agentId from Paperclip's heartbeat context and populates both `agentId` (top-level) and `adapterConfig.agentId` fields to ensure memory and effectiveness continuity (ADAPT-04)

### HTTP Client Design
- **D-15:** Single `Agent42Client` class wrapping fetch/node-fetch for all sidecar HTTP calls — constructed with sidecar URL + Bearer token
- **D-16:** Client methods: `execute(ctx)`, `health()`, `memoryRecall(req)`, `memoryStore(req)` — one method per sidecar endpoint
- **D-17:** Timeout: 30s for execute (fire-and-forget), 5s for health, 10s for memory operations
- **D-18:** Retry: 1 retry on 5xx with exponential backoff (1s) for health/memory; no retry for execute (idempotency guard handles retries server-side)

### Testing Approach
- **D-19:** Vitest for unit tests — mock HTTP responses via msw (Mock Service Worker) or simple fetch mocks
- **D-20:** Unit tests cover: adapter execute flow, session codec encode/decode, wake reason validation, client error handling
- **D-21:** Integration test script (optional, separate from unit tests) runs against a live Agent42 sidecar — validates end-to-end contract

### Claude's Discretion
- Exact Vitest configuration and test file organization
- Whether to use node-fetch, undici, or native fetch (Node 18+ has native fetch)
- Exact retry timing and backoff parameters
- README.md content and installation instructions
- package.json metadata (license, description, keywords)
- Whether testEnvironment() calls /sidecar/health or does a lightweight ping

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` — ADAPT-01 through ADAPT-05 define all Paperclip Adapter requirements
- `.planning/ROADMAP.md` — Phase 27 success criteria (4 acceptance tests)

### Architecture research
- `.planning/research/ARCHITECTURE.md` — Full system diagram, recommended adapter directory structure, data flow sequences
- `.planning/research/FEATURES.md` — Feature dependency graph, interface contracts, heartbeat request/response shapes, ServerAdapterModule interface definition
- `.planning/research/PITFALLS.md` — Critical pitfalls for adapter integration

### Prior phase context (dependencies)
- `.planning/phases/24-sidecar-mode/24-CONTEXT.md` — Sidecar architecture decisions, endpoint design, auth pattern, AdapterExecutionContext shape
- `.planning/phases/25-memory-bridge/25-CONTEXT.md` — MemoryBridge pattern, /memory/recall and /memory/store endpoint contracts, Pydantic model conventions
- `.planning/phases/26-tiered-routing-bridge/26-CONTEXT.md` — TieredRoutingBridge pattern, role-to-category mapping, cost reporting in CallbackPayload usage dict

### Existing codebase (key files to read for contract alignment)
- `core/sidecar_models.py` — Pydantic models defining the HTTP contract: AdapterExecutionContext, AdapterConfig, ExecuteResponse, CallbackPayload, MemoryRecallRequest/Response, MemoryStoreRequest/Response, HealthResponse
- `dashboard/sidecar.py` — FastAPI route handlers the adapter will call (POST /sidecar/execute, GET /sidecar/health, POST /memory/recall, POST /memory/store)
- `core/sidecar_orchestrator.py` — SidecarOrchestrator.execute_async() showing the full execution flow (memory recall → routing → execution stub → callback → learning extraction)
- `dashboard/auth.py` — JWT Bearer auth the adapter must provide on all requests (except /sidecar/health)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/sidecar_models.py` — Definitive source of truth for all HTTP request/response shapes. TypeScript types.ts should mirror these exactly (camelCase aliases are already defined in the Pydantic models)
- `dashboard/sidecar.py:create_sidecar_app()` — The FastAPI app the adapter calls. All 4 endpoints with auth dependencies visible
- `core/sidecar_orchestrator.py` — Full async execution flow showing what happens after adapter's POST lands

### Established Patterns
- **camelCase aliases in Pydantic v2:** All sidecar models use `alias="camelCase"` with `populate_by_name=True` — adapter sends camelCase JSON, Python receives snake_case. TypeScript types should use camelCase natively
- **Bearer JWT auth:** All endpoints (except /health) require `Authorization: Bearer {token}` header
- **202 Accepted + async callback:** `/sidecar/execute` returns immediately, execution runs in background, callback POSTed to Paperclip when done
- **Idempotency by runId:** Duplicate POSTs with same runId return `deduplicated: true` without re-executing — adapter can safely retry on network errors

### Integration Points
- `POST /sidecar/execute` — Primary adapter→sidecar endpoint (AdapterExecutionContext → ExecuteResponse)
- `GET /sidecar/health` — Used by adapter's testEnvironment() to verify sidecar reachability
- `POST /memory/recall` — Plugin-facing endpoint, adapter may expose for Phase 28 plugin use
- `POST /memory/store` — Plugin-facing endpoint, adapter may expose for Phase 28 plugin use
- Callback: Agent42 POSTs to `{PAPERCLIP_API_URL}/api/heartbeat-runs/{runId}/callback` — Paperclip's endpoint, not the adapter's

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

*Phase: 27-paperclip-adapter*
*Context gathered: 2026-03-30*

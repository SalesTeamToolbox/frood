# Phase 28: Paperclip Plugin - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

<domain>
## Phase Boundary

The Agent42 Paperclip plugin is installable, passes validation, and gives Paperclip agents access to memory recall, memory store, routing recommendations, effectiveness data, and MCP tool proxying as callable tools. Plugin registers tools via `@paperclipai/plugin-sdk`, communicates with Agent42 sidecar over HTTP, and implements lifecycle handlers (health, initialize, shutdown).

Requirements: PLUG-01 through PLUG-07.

</domain>

<decisions>
## Implementation Decisions

### Package Structure
- **D-01:** New `plugins/agent42-paperclip/` directory at repo root — standalone package, separate from the adapter at `adapters/agent42-paperclip/`
- **D-02:** Plugin has its own `Agent42Client` copy (~150 lines) and type definitions — zero coupling to the adapter package, no cross-package local path dependencies
- **D-03:** Flat `src/` layout: `index.ts` (plugin entry/exports), `worker.ts` (setup/lifecycle), `tools.ts` (tool registrations + handlers), `client.ts` (HTTP client for sidecar), `types.ts` (type definitions)
- **D-04:** Dependencies: `@paperclipai/plugin-sdk`, TypeScript, Vitest for tests — no shared deps with adapter

### MCP Tool Proxy
- **D-05:** New `POST /mcp/tool` endpoint on the sidecar FastAPI app (`dashboard/sidecar.py`) — routes through existing tool registry with sandbox and CommandFilter enforcement
- **D-06:** Server-side curated allowlist of safe tools — operators can expand via config for trusted private deployments
- **D-07:** Allowlist is config-driven (env var or settings field), defaulting to a conservative set of safe tools (e.g., content_analyzer, data_tool, memory_tool, template_tool, scoring_tool, code_intel, dependency_audit — no filesystem/git/shell by default)
- **D-08:** Plugin exposes `mcp_tool_proxy` tool — agent calls with `{toolName, params}`, plugin POSTs to `/mcp/tool`, sidecar validates against allowlist and executes
- **D-09:** New Pydantic models in `core/sidecar_models.py`: `MCPToolRequest(tool_name, params)`, `MCPToolResponse(result, error)` — Bearer auth required on the endpoint

### Tool Design
- **D-10:** All tool inputSchemas use camelCase field names — consistent with Paperclip conventions and existing sidecar Pydantic aliases
- **D-11:** Plugin auto-injects `agentId` and `companyId` from execution context (`ctx.agent.id` falling back to `adapterConfig.agentId`) — agents do not pass identity in tool calls
- **D-12:** `memory_recall` tool: agent passes `{query, taskType?, topK?, scoreThreshold?}` — plugin injects agentId/companyId, maps taskType to sidecar fields, returns simplified `{memories: [{text, score, source}]}`
- **D-13:** `memory_store` tool: agent passes `{content, tags?, section?}` — plugin injects agentId/companyId, maps `content` to sidecar's `text` field, returns `{stored, pointId}`
- **D-14:** `route_task` tool: agent passes `{taskType, qualityTarget?}` — plugin maps to TieredRoutingBridge fields, returns `{provider, model, tier, taskCategory}`
- **D-15:** `tool_effectiveness` tool: agent passes `{taskType}` — returns `{tools: [{name, successRate, observations}]}` (top-3 by success rate)
- **D-16:** Response shapes are simplified — strip verbose metadata, keep only fields agents need for decision-making

### Lifecycle & Config
- **D-17:** `manifest.json` declares: `apiVersion: 1`, capabilities `["http.outbound", "agent.tools.register"]`, instanceConfigSchema with `agent42BaseUrl` (string, required), `apiKey` (string, format: secret-ref, required), `timeoutMs` (number, optional, default 10000)
- **D-18:** `health()` probes `GET /sidecar/health` (no-auth endpoint) — returns real sidecar connectivity status for `paperclip doctor`
- **D-19:** `initialize(config)` validates required config fields, creates shared `Agent42Client` instance with baseUrl + apiKey + timeout, stores as module-level singleton
- **D-20:** `onShutdown()` calls `client.destroy()` to close keep-alive HTTP connections cleanly
- **D-21:** Plugin is installation-global (one process for all companies) — per-company behavior achieved via agentId/companyId scoping in tool calls, not separate plugin instances

### Claude's Discretion
- Exact allowlist contents for MCP tool proxy (conservative safe set)
- Vitest configuration and test file organization
- Whether to use native fetch or node-fetch in the plugin's Agent42Client
- Exact manifest.json metadata (displayName, description, categories, version)
- README.md content and installation instructions
- Error response formatting when sidecar is unreachable during tool calls

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` -- PLUG-01 through PLUG-07 define all Paperclip Plugin requirements
- `.planning/ROADMAP.md` -- Phase 28 success criteria (5 acceptance tests)

### Architecture research
- `.planning/research/ARCHITECTURE.md` -- Full system diagram, component responsibilities, data flow sequences
- `.planning/research/FEATURES.md` -- Plugin SDK interface contracts, tool registration patterns, manifest format, plugin lifecycle, JSON-RPC protocol details
- `.planning/research/PITFALLS.md` -- Critical pitfalls for plugin integration

### Prior phase context (dependencies)
- `.planning/phases/24-sidecar-mode/24-CONTEXT.md` -- Sidecar architecture, JWT Bearer auth, FastAPI app factory pattern
- `.planning/phases/25-memory-bridge/25-CONTEXT.md` -- MemoryBridge pattern, /memory/recall and /memory/store endpoint contracts, Pydantic model conventions
- `.planning/phases/26-tiered-routing-bridge/26-CONTEXT.md` -- TieredRoutingBridge pattern, role-to-category mapping, cost reporting, RoutingDecision dataclass
- `.planning/phases/27-paperclip-adapter/27-CONTEXT.md` -- Adapter package structure, Agent42Client design, session codec, types.ts mirroring sidecar models

### Existing codebase (key files to read)
- `core/sidecar_models.py` -- Pydantic models: AdapterExecutionContext, MemoryRecallRequest/Response, MemoryStoreRequest/Response, HealthResponse — plugin types.ts must mirror these
- `dashboard/sidecar.py` -- create_sidecar_app() factory where new POST /mcp/tool route is added
- `core/sidecar_orchestrator.py` -- SidecarOrchestrator execution flow
- `core/tiered_routing_bridge.py` -- TieredRoutingBridge.resolve() — route_task tool wraps this
- `core/memory_bridge.py` -- MemoryBridge class — recall/store pattern
- `core/effectiveness.py` -- EffectivenessStore with recommendation queries — tool_effectiveness tool wraps this
- `mcp_server.py` -- MCP server with 41+ tools — mcp_tool_proxy routes through this tool registry
- `adapters/agent42-paperclip/src/client.ts` -- Agent42Client reference implementation (plugin duplicates this pattern)
- `adapters/agent42-paperclip/src/types.ts` -- TypeScript type definitions mirroring sidecar Pydantic models (plugin duplicates relevant types)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `adapters/agent42-paperclip/src/client.ts` — Agent42Client with execute(), health(), memoryRecall(), memoryStore() methods — plugin duplicates this pattern with its own copy, adding mcpTool() method
- `adapters/agent42-paperclip/src/types.ts` — TypeScript interfaces mirroring sidecar Pydantic models — plugin copies relevant types and adds MCPToolRequest/Response
- `core/sidecar_models.py` — Pydantic models with camelCase aliases — source of truth for HTTP contract
- `core/effectiveness.py:EffectivenessStore` — Has recommendation query methods for top tools by success rate
- `core/tiered_routing_bridge.py:TieredRoutingBridge` — resolve() returns RoutingDecision for route_task

### Established Patterns
- **camelCase aliases in Pydantic v2:** All sidecar models use `alias="camelCase"` — plugin sends camelCase JSON natively
- **Bearer JWT auth:** All endpoints except /health require `Authorization: Bearer {token}` header
- **Sidecar file split:** Models in `core/sidecar_models.py`, routes in `dashboard/sidecar.py`, logic in `core/*.py` files
- **Adapter package structure:** `src/` with flat layout (client, types, index) — plugin follows same pattern

### Integration Points
- `dashboard/sidecar.py:create_sidecar_app()` — Add new `POST /mcp/tool` route with Bearer auth
- `core/sidecar_models.py` — Add MCPToolRequest, MCPToolResponse Pydantic models
- Plugin `setup(ctx)` — Register 5 tools (memory_recall, memory_store, route_task, tool_effectiveness, mcp_tool_proxy)
- Plugin `health()` — Calls `GET /sidecar/health` to validate connectivity
- Plugin `initialize(config)` — Creates shared Agent42Client from instanceConfig

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 28-paperclip-plugin*
*Context gathered: 2026-03-30*

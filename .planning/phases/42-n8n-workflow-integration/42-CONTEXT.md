# Phase 42: N8N Workflow Integration - Context

**Gathered:** 2026-04-05 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Add two new Agent42 tools (`n8n_workflow` and `n8n_create_workflow`) that let agents offload repetitive, token-expensive tasks to deterministic N8N workflows. N8N runs locally via Docker for dev and on the Contabo VPS for production. This phase delivers the tools, config, and N8N Docker setup — not a complete workflow library.

</domain>

<decisions>
## Implementation Decisions

### Tool Design
- **D-01:** Two separate tools — `n8n_workflow` (operational: list/trigger/monitor) and `n8n_create_workflow` (generative: design and deploy workflows from natural language)
- **D-02:** Both inherit from `Tool` ABC in `tools/base.py`, return `ToolResult`, registered in `mcp_server.py` `_build_registry()`
- **D-03:** Both use `httpx.AsyncClient` for N8N API calls (matching existing web_search.py and http_client.py patterns)

### n8n_workflow Tool Actions
- **D-04:** `list` — returns all workflows with id, name, active status, tags
- **D-05:** `trigger` — executes a workflow by ID with optional input JSON, returns execution ID
- **D-06:** `status` — polls execution by ID, returns state (waiting/running/success/error) and output data
- **D-07:** `output` — retrieves completed execution output data

### n8n_create_workflow Tool
- **D-08:** Agent describes desired automation in natural language → tool generates N8N workflow JSON → POSTs to N8N API
- **D-09:** Workflow templates stored in `tools/n8n_templates/` for common patterns (image processing, API chains, data transforms, webhook triggers) to reduce hallucination and improve reliability
- **D-10:** Generated workflows are validated before deployment — reject dangerous nodes (Code, SSH, Execute Command) unless `N8N_ALLOW_CODE_NODES=true`

### Configuration
- **D-11:** Add `n8n_url` (str, default empty) and `n8n_api_key` (str, default empty) to `Settings` dataclass in `core/config.py`
- **D-12:** Env vars: `N8N_URL` (e.g., `http://localhost:5678`) and `N8N_API_KEY`
- **D-13:** Add `N8N_ALLOW_CODE_NODES` (bool, default false) for security control
- **D-14:** Graceful degradation — tools return "N8N not configured" when URL/key missing, never crash

### N8N API Integration
- **D-15:** Auth via `X-N8N-API-KEY` header on all requests
- **D-16:** API base: `{N8N_URL}/api/v1/` with endpoints: workflows, workflows/{id}/execute, executions/{id}
- **D-17:** Timeout of 30s for trigger calls, 10s for list/status calls

### Deployment
- **D-18:** N8N runs via Docker (`n8nio/n8n` image) on port 5678
- **D-19:** Local dev: `docker run` command documented in `.env.example`
- **D-20:** Production (Contabo VPS): persistent Docker container alongside Agent42, added to existing docker-compose

### Security
- **D-21:** N8N URL validated through existing `UrlPolicy` SSRF checks
- **D-22:** Rate limiting via existing `core/rate_limiter.py` — 10 trigger calls/minute default
- **D-23:** Workflow creation restricts dangerous N8N nodes by default (Code, SSH, ExecuteCommand)

### Claude's Discretion
- Exact N8N template file format and bundled template selection
- Error message wording and retry logic
- Execution polling interval (suggest 2s)
- Whether to cache workflow list locally

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Tool architecture
- `tools/base.py` — Tool ABC, ToolResult dataclass, to_schema()/to_mcp_schema() methods
- `tools/registry.py` — ToolRegistry class, register(), execute() pattern
- `tools/context.py` — ToolContext dataclass for dependency injection

### HTTP integration patterns
- `tools/web_search.py` — httpx.AsyncClient usage, URL validation, fallback pattern
- `tools/http_client.py` — Header validation, SSRF protection, timeout handling

### Config and registration
- `core/config.py` — Settings dataclass, from_env() classmethod for env var loading
- `mcp_server.py` — _build_registry() for tool registration, _safe_import() for graceful loading
- `.env.example` — Environment variable documentation format

### Security
- `core/url_policy.py` — UrlPolicy for SSRF protection
- `core/rate_limiter.py` — Rate limiting pattern
- `core/key_store.py` — API key storage pattern

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `httpx.AsyncClient` — already a dependency, used across multiple tools for external API calls
- `ToolResult` dataclass — standard return type with output/error/success fields
- `UrlPolicy` — SSRF validation that should wrap N8N URL calls
- `_safe_import()` in mcp_server.py — graceful tool loading when N8N isn't available
- `template_tool.py` — pattern for storing/loading template files that can inform n8n_templates

### Established Patterns
- All external-calling tools use httpx with timeout controls
- Config follows frozen dataclass + from_env() + .env.example triple
- Tools that need workspace access declare `requires = ["workspace"]`
- MCP registration groups tools by dependency complexity

### Integration Points
- `mcp_server.py` `_build_registry()` — where new tools get registered
- `core/config.py` `Settings` — where N8N config fields go
- `.env.example` — where N8N env vars get documented
- `agent42.py` — where tools become available to agent runtime
- Docker Compose files — where N8N container gets added for production

</code_context>

<specifics>
## Specific Ideas

- Primary use case: offloading repetitive, token-expensive tasks that don't need LLM reasoning (image processing through 3rd party APIs, bulk API calls, data transformations)
- Agent designs the workflow ONCE (spending tokens), then it runs deterministically forever (zero tokens)
- N8N's 400+ integrations mean we're wiring connectors, not building them
- Local dev + production deployment parity via Docker

</specifics>

<deferred>
## Deferred Ideas

- Workflow marketplace/sharing between Agent42 instances — future phase
- N8N credential management through Agent42 UI — future phase (use N8N's own credential UI for now)
- Scheduled/cron workflow triggers from Agent42 — future phase
- Workflow versioning and rollback — future phase
- N8N cluster mode for high-availability — out of scope

</deferred>

---

*Phase: 42-n8n-workflow-integration*
*Context gathered: 2026-04-05*

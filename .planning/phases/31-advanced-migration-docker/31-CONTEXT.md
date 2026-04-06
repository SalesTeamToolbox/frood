# Phase 31: Advanced — Migration + Docker - Context

**Gathered:** 2026-03-31
**Status:** Ready for planning

<domain>
## Phase Boundary

Existing Agent42 users can import their agents into Paperclip preserving all memory and effectiveness history, and the full stack can be deployed with a single Docker Compose command. Two deliverables: (1) a Python migration CLI that transfers agent data from standalone Agent42 into Paperclip's company structure, and (2) a Docker Compose config running Paperclip + Agent42 sidecar + Qdrant + PostgreSQL.

Requirements: ADV-04, ADV-05.

</domain>

<decisions>
## Implementation Decisions

### Migration CLI Scope
- **D-01:** Full migration — memories (Qdrant vectors + payloads), effectiveness history (SQLite tool_invocations), and agent-to-company mapping all transfer during migration
- **D-02:** CLI is flag-driven and non-interactive: `python -m agent42.migrate --agent42-db <path> --qdrant-url <url> --paperclip-company-id <id>` (scriptable, no interactive prompts)
- **D-03:** Python CLI module within Agent42 codebase (not a separate package) — reuses existing qdrant_store, effectiveness, and config modules

### Docker Compose Topology
- **D-04:** New `docker-compose.paperclip.yml` file — existing `docker-compose.yml` (standalone Agent42 + Redis + Qdrant) stays untouched for standalone deployments
- **D-05:** Paperclip compose services: paperclip (app), agent42-sidecar (--sidecar mode, port 8001), qdrant, postgresql, redis
- **D-06:** Agent42 runs in sidecar mode via `CMD ["python", "agent42.py", "--sidecar"]` — no dashboard UI in this topology

### Data Preservation
- **D-07:** Point-by-point batch copy from source Qdrant — read points in batches, remap `company_id` payload field to target Paperclip company ID, upsert to target Qdrant instance
- **D-08:** `agent_id` preserved as-is during migration — Paperclip adapter uses `adapterConfig.agentId` which maps directly to Agent42's `agent_id` (Phase 27 D-13)
- **D-09:** Effectiveness SQLite rows copied with `agent_id` preserved — enables tier calculation continuity (agents don't restart as Provisional)
- **D-10:** UUID5 point IDs regenerated during copy (deterministic from content + source) — avoids collision if source and target share a Qdrant instance

### Deployment Config
- **D-11:** Shared `.env.paperclip.example` template with all required variables (API keys, secrets, Paperclip config, PostgreSQL credentials)
- **D-12:** Compose `environment:` overrides for internal Docker network URLs (redis://redis:6379, http://qdrant:6333, http://agent42-sidecar:8001) — these never go in .env
- **D-13:** Health check dependency chain: postgresql + qdrant + redis must be healthy before agent42-sidecar starts; agent42-sidecar healthy before paperclip starts

### Claude's Discretion
- Exact CLI argument names and help text
- Batch size for Qdrant point copy (e.g., 100 or 256 per batch)
- Whether migration CLI writes a summary report or just logs
- Exact Paperclip Docker image reference (public registry or build context)
- PostgreSQL version and default database name
- Whether to include an nginx reverse proxy in the compose file
- Volume naming and mount paths for PostgreSQL data

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` — ADV-04 (migration CLI) and ADV-05 (Docker Compose) define all Phase 31 requirements
- `.planning/ROADMAP.md` — Phase 31 success criteria (3 acceptance tests)

### Prior phase context (dependencies)
- `.planning/phases/27-paperclip-adapter/27-CONTEXT.md` — Adapter agent_id mapping (D-13, D-14), Agent42Client design, session codec
- `.planning/phases/28-paperclip-plugin/28-CONTEXT.md` — Plugin package structure, manifest, tool registrations, Agent42Client in plugin

### Existing codebase (key files to read)
- `Dockerfile` — Existing Agent42 Docker image (Python 3.12-slim, non-root user, health check on /api/health)
- `docker-compose.yml` — Existing standalone compose (agent42 + redis + qdrant) — reference for volume and health check patterns
- `agent42.py` — CLI entrypoint with `--sidecar` and `--sidecar-port` flags
- `memory/effectiveness.py` — EffectivenessStore with SQLite schema (tool_invocations table, agent_id column)
- `memory/qdrant_store.py` — QdrantStore with collection management, point operations, agent_id/company_id payload filtering
- `core/sidecar_models.py` — Pydantic models defining sidecar HTTP contracts
- `core/config.py` — Settings dataclass with PAPERCLIP_SIDECAR_PORT, PAPERCLIP_API_URL, SIDECAR_ENABLED
- `dashboard/sidecar.py` — Sidecar FastAPI app factory (create_sidecar_app)
- `.env.example` — Existing env var template for standalone mode

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `Dockerfile` — Base image already configured with Python 3.12-slim, non-root user, health checks. Extend or create sidecar variant
- `docker-compose.yml` — Existing Redis + Qdrant service definitions with health checks and volumes — copy pattern for paperclip compose
- `memory/qdrant_store.py` — QdrantStore with `_client.query_points()`, `_client.upsert()` — migration CLI reuses these for batch read/write
- `memory/effectiveness.py` — EffectivenessStore with aiosqlite — migration reads from source DB using same schema
- `core/config.py:Settings` — Already has PAPERCLIP_SIDECAR_PORT, PAPERCLIP_API_URL — compose env vars map to these

### Established Patterns
- **agent_id/company_id scoping:** Qdrant payloads use `agent_id` and `company_id` as keyword tenant fields with `KeywordIndexParams(is_tenant=True)`
- **UUID5 point IDs:** `qdrant_store._make_point_id(text, source)` generates deterministic IDs — migration can use same function for dedup
- **Health check pattern:** Redis uses `redis-cli ping`, Qdrant uses `curl http://localhost:6333/healthz` — extend for PostgreSQL and Paperclip
- **env_file + environment overrides:** Compose loads `.env` for secrets, overrides internal URLs in YAML

### Integration Points
- Migration CLI imports from `memory.qdrant_store`, `memory.effectiveness`, `core.config`
- Docker compose references `Dockerfile` for agent42-sidecar build context
- Paperclip container needs `AGENT42_SIDECAR_URL=http://agent42-sidecar:8001` to reach sidecar
- PostgreSQL container provides `DATABASE_URL` to Paperclip

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

*Phase: 31-advanced-migration-docker*
*Context gathered: 2026-03-31*

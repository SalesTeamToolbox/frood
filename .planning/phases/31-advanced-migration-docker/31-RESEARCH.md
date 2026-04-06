# Phase 31: Advanced — Migration + Docker - Research

**Researched:** 2026-03-31
**Domain:** Python CLI migration tooling + Docker Compose multi-service topology
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Full migration — memories (Qdrant vectors + payloads), effectiveness history (SQLite tool_invocations), and agent-to-company mapping all transfer during migration
- **D-02:** CLI is flag-driven and non-interactive: `python -m agent42.migrate --agent42-db <path> --qdrant-url <url> --paperclip-company-id <id>` (scriptable, no interactive prompts)
- **D-03:** Python CLI module within Agent42 codebase (not a separate package) — reuses existing qdrant_store, effectiveness, and config modules
- **D-04:** New `docker-compose.paperclip.yml` file — existing `docker-compose.yml` (standalone Agent42 + Redis + Qdrant) stays untouched for standalone deployments
- **D-05:** Paperclip compose services: paperclip (app), agent42-sidecar (--sidecar mode, port 8001), qdrant, postgresql, redis
- **D-06:** Agent42 runs in sidecar mode via `CMD ["python", "agent42.py", "--sidecar"]` — no dashboard UI in this topology
- **D-07:** Point-by-point batch copy from source Qdrant — read points in batches, remap `company_id` payload field to target Paperclip company ID, upsert to target Qdrant instance
- **D-08:** `agent_id` preserved as-is during migration — Paperclip adapter uses `adapterConfig.agentId` which maps directly to Agent42's `agent_id`
- **D-09:** Effectiveness SQLite rows copied with `agent_id` preserved — enables tier calculation continuity (agents don't restart as Provisional)
- **D-10:** UUID5 point IDs regenerated during copy (deterministic from content + source) — avoids collision if source and target share a Qdrant instance
- **D-11:** Shared `.env.paperclip.example` template with all required variables
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

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADV-04 | Migration CLI imports existing Agent42 agents into Paperclip company structure preserving agent IDs | Qdrant scroll+upsert pattern; SQLite INSERT OR IGNORE copy; argparse module CLI design |
| ADV-05 | Docker Compose config runs Paperclip + Agent42 sidecar + Qdrant + PostgreSQL with health checks and configurable ports | docker-compose.paperclip.yml with service_healthy depends_on chain; pg_isready healthcheck; existing patterns from docker-compose.yml |
</phase_requirements>

---

## Summary

Phase 31 has two independent deliverables that share no runtime coupling: a Python migration CLI module and a Docker Compose topology file. Both are well-bounded additions that reuse existing infrastructure — the CLI reuses QdrantStore and EffectivenessStore, the compose file extends the existing docker-compose.yml patterns.

The migration CLI (ADV-04) performs a batch copy from a source Agent42 Qdrant instance to a target instance, remapping the `company_id` payload field on each point while preserving `agent_id` and regenerating UUID5 point IDs from content. The effectiveness SQLite rows are bulk-copied with `INSERT OR IGNORE` to avoid duplicates. The built-in `qdrant_client.migrate()` is NOT suitable because it lacks payload transformation support — the CLI must implement its own scroll-and-upsert loop.

The Docker Compose topology (ADV-05) adds a new `docker-compose.paperclip.yml` file alongside the existing standalone `docker-compose.yml`. The five-service topology (postgresql, redis, qdrant, agent42-sidecar, paperclip) uses Docker Compose `depends_on: condition: service_healthy` to enforce a strict startup chain. The existing Dockerfile builds agent42-sidecar cleanly with `CMD ["python", "agent42.py", "--sidecar"]`. The agent42-sidecar health check reuses the existing `/api/health` endpoint (which returns 200 when the sidecar is ready).

**Primary recommendation:** Implement as two sequential waves — Wave 1: migration CLI module and tests; Wave 2: docker-compose.paperclip.yml and .env.paperclip.example. No external dependencies need to be introduced.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| qdrant-client | 1.17.0 (verified in .venv) | Qdrant scroll and upsert for migration | Already installed; `scroll()` + `upsert()` are the only needed operations |
| aiosqlite | 0.22.1 (verified in .venv) | Async SQLite reads from source effectiveness.db | Already installed; EffectivenessStore reuses this |
| argparse | stdlib | Non-interactive CLI flag parsing | stdlib — zero new deps; matches existing pattern in agent42.py |
| asyncio | stdlib | Async migration loop | Codebase is all-async; consistency required |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| logging | stdlib | Migration progress/error output | Always — structured output to stdout, no ANSI/spinners |
| uuid | stdlib | UUID5 point ID regeneration | `uuid.uuid5(namespace, content)` — same function as `qdrant_store._make_point_id()` |
| pathlib | stdlib | File path handling for --agent42-db | Consistent with codebase conventions |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Custom scroll loop | `qdrant_client.migrate()` built-in | migrate() has no payload remapping support — cannot remap company_id — must use custom loop |
| argparse | click | click requires an extra dependency; argparse already used in agent42.py for --sidecar flag |
| asyncio main loop | sync script | Codebase is all-async; EffectivenessStore methods are all async; consistency required |

**Installation:** No new packages required — all dependencies already in requirements.txt or stdlib.

---

## Architecture Patterns

### Recommended Project Structure
```
agent42/
├── migrate.py              # New: migration CLI module (python -m agent42.migrate)
tests/
├── test_migrate.py         # New: migration CLI tests
docker-compose.paperclip.yml  # New: Paperclip compose topology (root of project)
.env.paperclip.example        # New: env var template for Paperclip stack
```

### Pattern 1: Python Module as CLI Entry Point
**What:** Using `if __name__ == "__main__"` with argparse in a module-level file, invokable via `python -m agent42.migrate`
**When to use:** Non-interactive scriptable CLIs that reuse internal modules; matches D-02 and D-03
**Example:**
```python
# Source: Python docs argparse module + existing agent42.py pattern
import argparse
import asyncio

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Migrate Agent42 agents to Paperclip company structure",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--agent42-db", required=True, help="Path to source effectiveness.db")
    parser.add_argument("--qdrant-url", required=True, help="Source Qdrant server URL")
    parser.add_argument("--target-qdrant-url", required=True, help="Target Qdrant server URL")
    parser.add_argument("--paperclip-company-id", required=True, help="Target Paperclip company ID")
    parser.add_argument("--batch-size", type=int, default=100, help="Points per Qdrant scroll batch")
    parser.add_argument("--dry-run", action="store_true", help="Validate without writing")
    return parser

if __name__ == "__main__":
    args = build_parser().parse_args()
    asyncio.run(run_migration(args))
```

### Pattern 2: Qdrant Scroll-and-Upsert with Payload Remap
**What:** Scroll all points from source collection with `with_vectors=True`, remap `company_id` in payload, regenerate UUID5 point ID, upsert to target
**When to use:** Any cross-instance migration requiring payload transformation (built-in `migrate()` does NOT support this)
**Example:**
```python
# Source: qdrant-client 1.17 scroll() API documentation + qdrant_store._make_point_id() pattern
from qdrant_client import QdrantClient
from qdrant_client.models import PointStruct
import uuid

NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")  # Same as qdrant_store.py

def remap_point(point, target_company_id: str) -> PointStruct:
    payload = dict(point.payload or {})
    payload["company_id"] = target_company_id  # Remap tenant field
    # Regenerate UUID5 to avoid collision when sharing Qdrant instance (D-10)
    content = f"{payload.get('source', '')}:{payload.get('text', '')}"
    new_id = str(uuid.uuid5(NAMESPACE, content))
    return PointStruct(id=new_id, vector=point.vector, payload=payload)

async def migrate_collection(src: QdrantClient, dst: QdrantClient,
                              collection: str, company_id: str, batch_size: int = 100):
    offset = None
    total = 0
    while True:
        records, next_offset = src.scroll(
            collection_name=collection,
            offset=offset,
            limit=batch_size,
            with_vectors=True,
            with_payload=True,
        )
        if not records:
            break
        points = [remap_point(r, company_id) for r in records]
        dst.upsert(collection_name=collection, points=points)
        total += len(points)
        if next_offset is None:
            break
        offset = next_offset
    return total
```

### Pattern 3: SQLite Bulk Copy with INSERT OR IGNORE
**What:** Read all tool_invocations rows from source DB filtered by agent_id, INSERT OR IGNORE into target DB
**When to use:** Cross-database row copy where duplicates are non-fatal (D-09)
**Example:**
```python
# Source: aiosqlite docs + existing EffectivenessStore pattern
import aiosqlite

async def migrate_effectiveness(src_db: str, dst_db: str, agent_ids: list[str]):
    async with aiosqlite.connect(src_db) as src:
        src.row_factory = aiosqlite.Row
        placeholders = ",".join("?" * len(agent_ids))
        async with src.execute(
            f"SELECT tool_name, task_type, task_id, success, duration_ms, ts, agent_id "
            f"FROM tool_invocations WHERE agent_id IN ({placeholders})",
            agent_ids,
        ) as cursor:
            rows = await cursor.fetchall()

    async with aiosqlite.connect(dst_db) as dst:
        await dst.executemany(
            "INSERT OR IGNORE INTO tool_invocations "
            "(tool_name, task_type, task_id, success, duration_ms, ts, agent_id) "
            "VALUES (?,?,?,?,?,?,?)",
            [(r["tool_name"], r["task_type"], r["task_id"],
              r["success"], r["duration_ms"], r["ts"], r["agent_id"]) for r in rows],
        )
        await dst.commit()
    return len(rows)
```

### Pattern 4: Docker Compose service_healthy Dependency Chain
**What:** Each service declares a `healthcheck` block; downstream services use `depends_on: condition: service_healthy`
**When to use:** Any multi-service topology where startup order matters (D-13)
**Example:**
```yaml
# Source: Docker Compose official docs (docs.docker.com/compose/how-tos/startup-order/)
services:
  postgresql:
    image: postgres:16
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s

  agent42-sidecar:
    build: .
    command: ["python", "agent42.py", "--sidecar"]
    ports:
      - "${SIDECAR_PORT:-8001}:8001"
    depends_on:
      postgresql:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/sidecar/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 20s

  paperclip:
    image: "ghcr.io/paperclip-ai/paperclip:latest"  # placeholder — discretion area
    depends_on:
      agent42-sidecar:
        condition: service_healthy
```

### Anti-Patterns to Avoid
- **Using `qdrant_client.migrate()` for this phase:** That function copies payloads verbatim — it cannot remap `company_id`. The phase requires transformation, so use the custom scroll loop.
- **`depends_on` without `condition: service_healthy`:** The default condition is `service_started` which only waits for the container process to start, not for the service to be ready. Databases take additional time to initialize.
- **Putting internal Docker URLs in .env:** The Compose file should override `REDIS_URL`, `QDRANT_URL`, and `AGENT42_SIDECAR_URL` inline in `environment:` rather than baking them into `.env` (D-12). Users setting these in .env would break container networking.
- **Using DASHBOARD_HOST=127.0.0.1 in sidecar container:** The sidecar must bind to `0.0.0.0` inside Docker to be reachable from other containers. Override via `environment: DASHBOARD_HOST: 0.0.0.0` in compose, not in .env.
- **Interactive CLI prompts:** D-02 explicitly forbids interactive prompts. All required values must be CLI flags with `required=True` in argparse.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Qdrant point pagination | Custom offset arithmetic | `scroll()` returns `next_offset` cursor | Built-in cursor is memory-efficient and handles edge cases |
| UUID generation for point IDs | Random UUIDs | `uuid.uuid5(NAMESPACE, content)` — same function as existing `_make_point_id()` | Deterministic deduplication; consistent with existing codebase |
| SQLite schema creation in target | New schema definition | `EffectivenessStore._ensure_db()` call before INSERT | Schema is already defined and idempotent; don't duplicate it |
| Docker health check tool selection | Custom scripts | `pg_isready` (PostgreSQL built-in), `redis-cli ping`, `curl` (already in Dockerfile) | All three are available in their respective official images |

**Key insight:** Both deliverables are thin wrappers over existing code. The migration CLI reuses 4 existing modules without modification. The compose file is pattern replication from docker-compose.yml with extension.

---

## Common Pitfalls

### Pitfall 1: Qdrant scroll returns None for first offset
**What goes wrong:** When the collection has fewer than `batch_size` points, `next_offset` may be `None` on the first call and there are no more pages. Code that checks `while next_offset is not None` before the first call would skip the first (and only) batch.
**Why it happens:** The scroll cursor pattern is: do the first call, then loop while `next_offset is not None`. Not: loop while `next_offset is not None` before the first call.
**How to avoid:** Use a `while True` with `break` when `not records or next_offset is None`, or use a do-while equivalent:
```python
offset = None
while True:
    records, next_offset = src.scroll(..., offset=offset)
    if not records:
        break
    # process records
    if next_offset is None:
        break
    offset = next_offset
```
**Warning signs:** Migration reports 0 points migrated for small collections.

### Pitfall 2: DASHBOARD_HOST=127.0.0.1 blocks inter-container communication
**What goes wrong:** The existing `.env.example` sets `DASHBOARD_HOST=127.0.0.1`. If this is loaded by agent42-sidecar inside Docker without override, the sidecar binds to localhost only and is unreachable from the paperclip container.
**Why it happens:** The compose `env_file:` directive loads user's `.env`, which may have 127.0.0.1. The `environment:` section must override it.
**How to avoid:** Always add `DASHBOARD_HOST: "0.0.0.0"` in the compose `environment:` block for agent42-sidecar (D-12 pattern for network overrides).
**Warning signs:** Paperclip returns connection refused when calling `http://agent42-sidecar:8001/sidecar/health`.

### Pitfall 3: PostgreSQL health check before DB init completes
**What goes wrong:** `pg_isready` returns success as soon as PostgreSQL accepts TCP connections, which happens before the database files are fully initialized and before the specified `POSTGRES_DB` exists.
**Why it happens:** `pg_isready` only checks socket connectivity, not query readiness for a specific DB.
**How to avoid:** Use `pg_isready -U $POSTGRES_USER -d $POSTGRES_DB` (with the specific DB name) and set `start_period: 30s` to allow initialization time before failed checks count against retries.
**Warning signs:** Paperclip migrations fail with "database does not exist" errors immediately after container startup.

### Pitfall 4: EffectivenessStore target DB has no schema when INSERT runs
**What goes wrong:** `INSERT OR IGNORE` into target effectiveness.db fails if the target DB doesn't have the `tool_invocations` table yet.
**Why it happens:** aiosqlite creates the file but not the schema; `_ensure_db()` must be called first.
**How to avoid:** Instantiate `EffectivenessStore(target_path)` and call `await store._ensure_db()` before bulk-inserting rows.
**Warning signs:** `sqlite3.OperationalError: no such table: tool_invocations`

### Pitfall 5: curl not in agent42-sidecar for health check
**What goes wrong:** Health check `CMD curl -f http://localhost:8001/sidecar/health` fails because curl isn't installed in the container.
**Why it happens:** Some Python images don't include curl.
**How to avoid:** The existing `Dockerfile` already installs curl (`RUN apt-get install -y curl`) — this is already handled. Verify the health check URL is `/sidecar/health` (not `/api/health`, which is the dashboard endpoint).
**Warning signs:** Compose reports `agent42-sidecar` as unhealthy despite the app running.

### Pitfall 6: Qdrant collections not found on target instance
**What goes wrong:** Migration tries to upsert to a collection that doesn't exist on the target Qdrant instance.
**Why it happens:** `qdrant_store._ensure_collection()` creates collections on first upsert, but the payload indexes (`agent_id`, `company_id` as tenants) won't be created unless the migration CLI handles collection setup.
**How to avoid:** Before migrating points, check if the collection exists on the target and call `target_store._ensure_collection(suffix)` to create it with the correct schema and indexes.
**Warning signs:** Upsert succeeds but queries using `company_id` filter return no results.

---

## Code Examples

Verified patterns from official sources and existing codebase:

### Migration CLI Entry Point (agent42/migrate.py)
```python
# Source: stdlib argparse + existing agent42.py __main__ pattern
"""Agent42 migration CLI — imports agents into Paperclip company structure.

Usage:
    python -m agent42.migrate \
        --agent42-db .agent42/effectiveness.db \
        --qdrant-url http://localhost:6333 \
        --target-qdrant-url http://target:6333 \
        --paperclip-company-id <uuid> \
        [--batch-size 100] \
        [--dry-run]
"""
import argparse
import asyncio
import logging

logger = logging.getLogger("agent42.migrate")

def build_parser():
    p = argparse.ArgumentParser(
        description="Migrate Agent42 agents to Paperclip company structure"
    )
    p.add_argument("--agent42-db", required=True)
    p.add_argument("--qdrant-url", required=True)
    p.add_argument("--target-qdrant-url", required=True)
    p.add_argument("--paperclip-company-id", required=True)
    p.add_argument("--batch-size", type=int, default=100)
    p.add_argument("--dry-run", action="store_true")
    return p

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    args = build_parser().parse_args()
    asyncio.run(run_migration(args))
```

### Docker Compose service_healthy chain (key excerpt)
```yaml
# Source: docs.docker.com/compose/how-tos/startup-order/
services:
  postgresql:
    image: postgres:16
    env_file: .env.paperclip
    environment:
      POSTGRES_DB: paperclip
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U $${POSTGRES_USER} -d $${POSTGRES_DB}"]
      interval: 10s
      timeout: 5s
      retries: 5
      start_period: 30s
    volumes:
      - postgresql-data:/var/lib/postgresql/data
    restart: unless-stopped

  agent42-sidecar:
    build: .
    command: ["python", "agent42.py", "--sidecar"]
    env_file: .env.paperclip
    environment:
      DASHBOARD_HOST: "0.0.0.0"       # Must override for inter-container reach
      REDIS_URL: "redis://redis:6379/0"
      QDRANT_URL: "http://qdrant:6333"
      QDRANT_ENABLED: "true"
    ports:
      - "${SIDECAR_PORT:-8001}:8001"
    depends_on:
      postgresql:
        condition: service_healthy
      qdrant:
        condition: service_healthy
      redis:
        condition: service_healthy
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8001/sidecar/health"]
      interval: 15s
      timeout: 5s
      retries: 3
      start_period: 20s
    restart: unless-stopped
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `depends_on: [service]` (order only) | `depends_on: condition: service_healthy` | Docker Compose v3.0+ | Services wait for actual readiness, not just process start |
| Manual scroll pagination with integer offsets | Cursor-based `next_offset` return value | qdrant-client 1.x | Correct pagination even with insertions between batches |

**Deprecated/outdated:**
- `version: "3.8"` at top of docker-compose.yml: Docker Compose v2.x ignores the `version` key; it is no longer required but harmless to include for backward compat reference. The existing file uses it; the new file can omit it or match existing style.

---

## Open Questions

1. **Paperclip Docker image reference**
   - What we know: D-05 lists paperclip as a service; CONTEXT.md marks "exact Paperclip Docker image reference" as Claude's Discretion
   - What's unclear: Whether there's a public ghcr.io image or a local build context for Paperclip
   - Recommendation: Use a placeholder `image: paperclip/app:latest` with a clear comment to replace, or add a `build: ../paperclip` context option. The planner should choose one and document it clearly.

2. **Agent collection names in source Qdrant**
   - What we know: QdrantStore uses `{prefix}_{suffix}` e.g. `agent42_memory`, `agent42_history`, `agent42_knowledge`, `agent42_conversations` with `collection_prefix` defaulting to `"agent42"`
   - What's unclear: Whether the source Qdrant instance uses the default prefix or a custom one
   - Recommendation: Add `--collection-prefix` CLI flag (default: `agent42`) so the CLI handles non-default installations.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| qdrant-client | Migration CLI (Qdrant scroll/upsert) | Yes | 1.17.0 (in .venv) | — |
| aiosqlite | Migration CLI (effectiveness copy) | Yes | 0.22.1 (in .venv) | — |
| Docker Engine | docker-compose.paperclip.yml testing | No | — | Manual service startup; test compose syntax only |
| docker compose (v2 plugin) | ADV-05 compose file | No | — | Compose file can be validated with `docker compose config --dry-run` when available |
| curl | agent42-sidecar healthcheck in compose | Yes (in Dockerfile) | Already in base image | — |
| pg_isready | PostgreSQL healthcheck | Yes (in postgres:16 image) | Built-in | — |

**Missing dependencies with no fallback:**
- Docker Engine is not available in the current dev shell. The compose file cannot be live-tested during implementation. The planner should include a Wave 0 step to verify Docker availability or scope compose file as "write + validate syntax only."

**Missing dependencies with fallback:**
- None.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x |
| Config file | None detected (uses pytest.ini defaults) |
| Quick run command | `python -m pytest tests/test_migrate.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADV-04 | Migration CLI with valid args copies Qdrant points with remapped company_id | unit | `pytest tests/test_migrate.py::test_migrate_qdrant_remaps_company_id -x` | Wave 0 |
| ADV-04 | Migration CLI copies effectiveness rows with agent_id preserved | unit | `pytest tests/test_migrate.py::test_migrate_effectiveness_preserves_agent_id -x` | Wave 0 |
| ADV-04 | Migration CLI --dry-run reads without writing | unit | `pytest tests/test_migrate.py::test_dry_run_no_writes -x` | Wave 0 |
| ADV-04 | Missing required arg exits non-zero with error message | unit | `pytest tests/test_migrate.py::test_missing_arg_exits -x` | Wave 0 |
| ADV-05 | docker-compose.paperclip.yml syntax is valid | smoke | `docker compose -f docker-compose.paperclip.yml config --dry-run` (manual-only — Docker not in CI) | manual |
| ADV-05 | agent42-sidecar reaches healthy status | integration | manual — Docker not available in dev shell | manual |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_migrate.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_migrate.py` — covers ADV-04 (all migration CLI tests)
- [ ] `tests/conftest.py` already exists — no additions needed for migration tests (tmp_path fixture is sufficient)

*(docker-compose.paperclip.yml validation is manual-only due to Docker not being available in the current shell)*

---

## Project Constraints (from CLAUDE.md)

- All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools.
- Frozen config — `Settings` dataclass in `core/config.py`. Add fields there + `from_env()` + `.env.example`. For Phase 31 the migration CLI uses its own argparse args, not Settings, since it's a standalone tool.
- Graceful degradation — Redis, Qdrant, MCP are optional. Handle absence, never crash.
- Sandbox always on — validate paths via `sandbox.resolve_path()`. (Migration CLI reads external DB path — must validate the path exists before opening.)
- NEVER disable sandbox in production (`SANDBOX_ENABLED=true`)
- NEVER expose `DASHBOARD_HOST=0.0.0.0` without nginx/firewall (NOTE: Compose overrides this only for Docker internal networking — this is the intended pattern for container-to-container communication, acceptable as per D-12)
- ALWAYS validate file paths through `sandbox.resolve_path()` — migration `--agent42-db` path must be checked

---

## Sources

### Primary (HIGH confidence)
- `memory/qdrant_store.py` — `_make_point_id()` UUID5 namespace, `scroll()` not present but `_client.query_points()` used; `upsert_vectors()` batch pattern confirmed
- `memory/effectiveness.py` — Full SQLite schema with `tool_invocations` + `agent_id` column; `_ensure_db()` idempotent setup pattern
- `Dockerfile` — curl installed in base image; confirms health check tool availability
- `docker-compose.yml` — Redis `redis-cli ping` and Qdrant `curl http://localhost:6333/healthz` healthcheck patterns confirmed
- [qdrant_client.migrate.migrate module](https://python-client.qdrant.tech/qdrant_client.migrate.migrate) — Confirmed: `migrate()` does NOT support payload transformation; scroll loop pattern documented
- [Docker Compose startup order](https://docs.docker.com/compose/how-tos/startup-order/) — `depends_on: condition: service_healthy` YAML syntax and PostgreSQL pg_isready example

### Secondary (MEDIUM confidence)
- [qdrant-client PyPI](https://pypi.org/project/qdrant-client/) — Version 1.17.0 confirmed current (matches .venv install)
- [Docker Compose health checks guide](https://last9.io/blog/docker-compose-health-checks/) — PostgreSQL `start_period: 30s` recommendation verified against official docs

### Tertiary (LOW confidence)
- None — all critical claims verified against official sources or codebase inspection.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all packages verified in .venv; all stdlib; no new deps
- Architecture: HIGH — scroll/upsert pattern confirmed from qdrant-client docs; compose syntax from official Docker docs; pitfalls from codebase inspection
- Pitfalls: HIGH — most pitfalls derived from reading the actual Dockerfile, docker-compose.yml, and qdrant_store.py code

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (stable APIs; qdrant-client 1.17 and Docker Compose syntax are stable)

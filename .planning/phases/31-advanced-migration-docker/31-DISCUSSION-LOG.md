# Phase 31: Advanced — Migration + Docker - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-31
**Phase:** 31-advanced-migration-docker
**Areas discussed:** Migration CLI scope, Docker Compose topology, Data preservation, Deployment config

---

## Migration CLI Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Full migration | Memories (Qdrant) + effectiveness (SQLite) + agent-to-company mapping. CLI takes --agent42-db, --qdrant-url, --paperclip-company-id flags. Non-interactive, scriptable. | ✓ |
| Memories only | Just Qdrant point transfer with agent_id/company_id re-scoping. Effectiveness history discarded — agents start fresh tier. | |
| Interactive wizard | Full migration but with interactive prompts: select which agents to import, preview mapping, confirm before writing. | |

**User's choice:** Full migration (Recommended)
**Notes:** Flag-driven, scriptable CLI preferred over interactive wizard.

---

## Docker Compose Topology

| Option | Description | Selected |
|--------|-------------|----------|
| New compose file | docker-compose.paperclip.yml with: paperclip (app), agent42-sidecar (--sidecar mode), qdrant, postgresql, redis. Existing docker-compose.yml stays for standalone use. | ✓ |
| Profiles in single file | Extend docker-compose.yml with --profile paperclip. No profile = standalone dashboard. With profile = full Paperclip stack. | |
| Replace existing | docker-compose.yml becomes the Paperclip stack. Standalone mode dropped from compose (still works via CLI). | |

**User's choice:** New compose file (Recommended)
**Notes:** Separate file preserves backward compatibility for standalone users.

---

## Data Preservation

| Option | Description | Selected |
|--------|-------------|----------|
| Point-by-point copy | Batch-read points from source Qdrant, remap company_id to Paperclip company, upsert to target. Handles different Qdrant instances and ID remapping. | ✓ |
| Qdrant snapshot restore | Use Qdrant's native snapshot/restore API. Fastest but requires same collection schema and no field remapping. | |
| JSON export + import | Export memories to JSON file, then bulk import. Portable but two-step and potentially large files. | |

**User's choice:** Point-by-point copy (Recommended)
**Notes:** Enables company_id remapping during migration. Works across different Qdrant instances.

---

## Deployment Config

| Option | Description | Selected |
|--------|-------------|----------|
| Shared .env + overrides | Single .env.paperclip.example with all secrets/keys. Compose YAML has environment: overrides for internal URLs (redis://redis:6379, http://qdrant:6333). Matches existing pattern. | ✓ |
| Per-service .env files | agent42-sidecar.env, paperclip.env, postgres.env. Clean separation but more files to coordinate. | |
| Docker secrets | Use Docker Compose secrets: directive for sensitive values. More secure but adds complexity for dev deployments. | |

**User's choice:** Shared .env + overrides (Recommended)
**Notes:** Matches existing docker-compose.yml pattern. Internal network URLs stay in YAML, not .env.

---

## Claude's Discretion

- Exact CLI argument names and help text
- Batch size for Qdrant point copy
- PostgreSQL version and database name
- Volume naming and mount paths
- Whether to include nginx reverse proxy
- Migration summary report format

## Deferred Ideas

None — discussion stayed within phase scope

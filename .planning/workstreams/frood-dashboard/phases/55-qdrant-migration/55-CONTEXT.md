---
phase: 55-qdrant-migration
status: discussed
discussed: 2026-04-08
---

# Phase 55: Qdrant Migration + Test Suite

## Goals

Migrate Qdrant collection names from Agent42 to Frood identity with backward-compatible aliases, update all test files and documentation to reflect the rename, and ensure full test suite passes.

## Decided

### Qdrant Collections (Locked)

| Decision | Value | Rationale |
|----------|-------|-----------|
| New collection prefix | `frood` | Consistent with entry point rename |
| Memory collection | `frood_memory` | Primary semantic memory store |
| History collection | `frood_history` | Event log for observability |
| Conversations collection | `frood_conversations` | Cross-session search |
| Knowledge collection | `frood_knowledge` | Learner-generated patterns |
| Backward compat alias strategy | Create aliases from old names | Existing deployments keep working |
| Config default | `QDRANT_COLLECTION_PREFIX` defaults to `frood` | Clean break per v7.0 goal |
| Alias naming | `agent42_memory` → alias to `frood_memory` | Standard Qdrant alias pattern |

### Implementation Approach (Researcher: decide how)

- `_ensure_collection()` in `qdrant_store.py` uses prefix + suffix pattern — already flexible
- On startup, check if old collections exist WITHOUT aliases, create alias if needed
- Collection creation in `QdrantConfig` default should be `frood`

### Test Updates (Planner: scope tasks)

| Area | Files to Update |
|------|-----------------|
| Collection references | `test_migrate.py`, `test_cc_memory_sync.py`, `test_mcp_server.py`, `test_task_context.py` |
| Mock/fixture names | Any `agent42_memory` in assertions or mock returns |
| Migration tests | `test_migrate.py` tests the migration logic itself — needs to work with both old and new |

### Documentation Updates (Planner: scope tasks)

| Doc | Updates Needed |
|-----|---------------|
| CLAUDE.md | Entry point, data dir references already updated in Phase 52 — verify |
| .env.example | `QDRANT_COLLECTION_PREFIX` default should be `frood` |
| README.md | Verify collection naming reflected |

## Not Discussed (Deferred)

- [ ] Exact alias creation logic — researcher decides approach
- [ ] Whether to auto-migrate existing data to new collections or just use aliases
- [ ] Test coverage targets for Qdrant code

## Next Steps

1. **Research** — Investigate Qdrant alias API, existing collection detection logic
2. **Plan** — Break into plans: Qdrant config/collections, test file updates, docs, validation

## Related Files

- `core/config.py:490` — `qdrant_collection_prefix` default
- `memory/qdrant_store.py:48` — `QdrantConfig` collection_prefix default
- `memory/qdrant_store.py:142` — `_ensure_collection()` method
- `mcp_server.py:599` — checks for `agent42_memory` collection
- `.claude/hooks/memory-recall.py:406,485` — hardcoded collection names
- `.claude/hooks/context-loader.py:485` — hardcoded collection name in comment
- `memory/search_service.py:92,112,114,121` — hardcoded collection names
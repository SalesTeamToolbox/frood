---
phase: 25-memory-bridge
plan: 01
subsystem: memory
tags: [pydantic, qdrant, memory-bridge, recall, learning-extraction, sidecar, instructor]
provides:
  - MemoryBridge class with recall() (scope-filtered MEMORY+HISTORY search) and learn_async() (fire-and-forget instructor extraction)
  - Five Pydantic v2 memory models: MemoryRecallRequest, MemoryItem, MemoryRecallResponse, MemoryStoreRequest, MemoryStoreResponse with camelCase aliases
  - agent_id and company_id KEYWORD tenant-optimized indexes on MEMORY, HISTORY, and KNOWLEDGE Qdrant collections
affects: [25-02, sidecar-orchestrator, paperclip-adapter]
tech-stack:
  added: []
  patterns: [pydantic-v2-camelcase-aliases, qdrant-tenant-keyword-index, asyncio-to-thread-for-sync-calls, instructor-importerror-guard, fire-and-forget-exception-isolation]
key-files:
  created:
    - core/memory_bridge.py
  modified:
    - core/sidecar_models.py
    - memory/qdrant_store.py
key-decisions:
  - "recall() calls qdrant._client.query_points() directly (bypassing MemoryStore.semantic_search()) because semantic_search() lacks agent_id filter support — scope isolation requires FieldCondition on agent_id"
  - "learn_async() wraps full body in try/except so callers can use asyncio.create_task() without exception propagation guards (fire-and-forget pattern P7)"
  - "KeywordIndexParams(type='keyword', is_tenant=True) used for agent_id/company_id indexes to enable Qdrant 1.9+ HNSW co-location optimisation (D-09, D-12)"
duration: 12min
completed: 2026-03-29
requirements: [MEM-01, MEM-02, MEM-03, MEM-05]
---

# Phase 25 Plan 01: MemoryBridge Foundation Contracts Summary

**MemoryBridge class with agent-scoped recall and fire-and-forget learning extraction via instructor, plus five Pydantic v2 memory models and Qdrant tenant-optimized agent_id/company_id indexes across all three collections.**

## Performance

- **Duration:** ~12 minutes
- **Tasks:** 2 completed
- **Files modified:** 3 (1 created, 2 modified)

## Accomplishments

- Created `core/memory_bridge.py` with `MemoryBridge` class implementing:
  - `recall()`: scope-filtered semantic search over MEMORY + HISTORY collections, requires `agent_id` (raises `ValueError` if empty), returns empty list when Qdrant/embeddings unavailable, applies score threshold and sorts by relevance
  - `learn_async()`: fire-and-forget instructor extraction wrapping entire body in `try/except`, uses `asyncio.to_thread` for blocking instructor/Qdrant calls, guards `import instructor` with `except ImportError`
- Appended five Pydantic v2 models to `core/sidecar_models.py`: `MemoryRecallRequest`, `MemoryItem`, `MemoryRecallResponse`, `MemoryStoreRequest`, `MemoryStoreResponse` — all with camelCase aliases matching Paperclip's TypeScript conventions
- Extended `QdrantStore._ensure_task_indexes()` and `_ensure_knowledge_indexes()` with `KeywordIndexParams(type="keyword", is_tenant=True)` for `agent_id` and `company_id` — applies to MEMORY, HISTORY, and KNOWLEDGE collections

## Task Commits

1. **Task 1: Pydantic memory models and QdrantStore index extensions** - `fe3494e`
2. **Task 2: Create MemoryBridge with recall() and learn_async()** - `72517b9`

## Files Created/Modified

- `/c/Users/rickw/projects/agent42/core/memory_bridge.py` — MemoryBridge class (246 lines): recall(), learn_async(), graceful degradation, agent_id scope enforcement
- `/c/Users/rickw/projects/agent42/core/sidecar_models.py` — Five new Pydantic v2 memory models appended after HealthResponse
- `/c/Users/rickw/projects/agent42/memory/qdrant_store.py` — _ensure_task_indexes and _ensure_knowledge_indexes extended with agent_id + company_id tenant indexes

## Decisions & Deviations

**Decisions:**

- `recall()` bypasses `MemoryStore.semantic_search()` and calls `qdrant._client.query_points()` directly — `semantic_search()` was designed for the Claude Code hooks use case and does not expose agent_id filter parameters. Direct FieldCondition construction on agent_id is the only way to enforce scope isolation at the Qdrant level.
- `learn_async()` accepts both dict and Pydantic model objects in the extraction result loop (`isinstance(learning, dict)` check) to handle instructor returning either format depending on Pydantic v1/v2 interaction.
- Provider selection in `_sync_extract` follows the same pattern as `dashboard/server.py` line 4120-4128: OpenRouter/Gemini first, OpenAI fallback, returns `{"learnings": []}` if neither configured.

**Deviations:**

None — plan executed exactly as written.

## Known Stubs

None — no placeholder data or hardcoded empty returns that affect plan goal. `recall()` returns `[]` when Qdrant is unavailable by design (graceful degradation), not as a stub.

## Next Phase Readiness

Plan 25-02 (routes, orchestrator integration, tests) can now import:

```python
from core.memory_bridge import MemoryBridge
from core.sidecar_models import (
    MemoryRecallRequest, MemoryRecallResponse,
    MemoryStoreRequest, MemoryStoreResponse, MemoryItem,
)
```

All type contracts are stable and committed.

## Self-Check: PASSED

- `core/memory_bridge.py` exists: PASSED (246 lines, MemoryBridge importable)
- `core/sidecar_models.py` contains MemoryRecallRequest: PASSED
- `memory/qdrant_store.py` contains agent_id indexes: PASSED
- Commits fe3494e and 72517b9 exist in git log: PASSED
- All four plan verifications pass: PASSED

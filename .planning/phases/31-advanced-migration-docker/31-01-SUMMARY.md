---
phase: 31-advanced-migration-docker
plan: 01
subsystem: migration-cli
status: complete
tags: [migration, cli, qdrant, sqlite, tdd]
dependency_graph:
  requires: [memory/qdrant_store.py, memory/effectiveness.py]
  provides: [migrate.py]
  affects: []
tech_stack:
  added: []
  patterns: [argparse-cli, scroll-and-upsert, uuid5-remapping, insert-or-ignore]
key_files:
  created: [migrate.py, tests/test_migrate.py]
  modified: []
key_decisions:
  - "UUID5 namespace shared with qdrant_store.py for deterministic point ID regeneration"
  - "INSERT OR IGNORE for idempotent effectiveness row migration"
  - "ensure_target_collections reuses QdrantStore._ensure_collection via __new__ pattern"
metrics:
  completed: "2026-03-31"
  tasks: 1
  files_created: 2
  files_modified: 0
requirements:
  - ADV-04
---

# Phase 31 Plan 01: Migration CLI Summary

Migration CLI that copies Agent42 Qdrant memories and SQLite effectiveness history into Paperclip company structure with company_id remapping, UUID5 regeneration, and agent_id preservation.

## What Was Built

### migrate.py (project root)

CLI entry point with 8 argparse flags:
- `--agent42-db` (required): source effectiveness.db path
- `--qdrant-url` (required): source Qdrant URL
- `--target-qdrant-url` (required): target Qdrant URL
- `--paperclip-company-id` (required): target company UUID
- `--collection-prefix` (default "agent42"), `--batch-size` (default 100), `--dry-run`, `--target-db`

Core functions:
- `build_parser()` -- argparse with required/optional flags
- `remap_point(point, target_company_id)` -- copies payload, sets company_id, regenerates UUID5 ID
- `migrate_collection(src, dst, collection, company_id, batch_size, dry_run)` -- async scroll loop with batch upsert
- `ensure_target_collections(dst_client, prefix)` -- creates 4 Qdrant collections via QdrantStore
- `migrate_effectiveness(src_db, dst_db)` -- bulk copies 4 SQLite tables with INSERT OR IGNORE
- `run_migration(args)` -- orchestrates full pipeline

### tests/test_migrate.py

8 unit tests covering:
1. `test_build_parser_required_args` -- all 4 required args; missing any raises SystemExit
2. `test_missing_collection_prefix_flag` -- default "agent42" and custom prefix
3. `test_remap_point_sets_company_id` -- company_id remapped, agent_id preserved
4. `test_remap_point_regenerates_uuid5` -- valid UUID, differs from original
5. `test_remap_point_uuid5_deterministic` -- same input produces identical IDs
6. `test_migrate_qdrant_remaps_company_id` -- 3 points upserted with correct company_id
7. `test_dry_run_no_writes` -- scroll called, upsert never called
8. `test_migrate_effectiveness_preserves_agent_id` -- rows copied across all 4 tables

## Test Results

```
8 passed in 1.26s
```

All 8 tests pass. Full suite: 86 passed, 1 pre-existing failure (test_app_git.py unrelated).

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed asyncio.get_event_loop() deprecation on Python 3.14**
- **Found during:** GREEN phase test execution
- **Issue:** `asyncio.get_event_loop().run_until_complete()` raises RuntimeError on Python 3.14 ("There is no current event loop in thread")
- **Fix:** Replaced with `asyncio.run()` in all 3 async test methods
- **Files modified:** tests/test_migrate.py
- **Commit:** included in 6028b68

## Commits

| Task | Type | Hash | Description |
|------|------|------|-------------|
| 1 (RED) | test | abda737 | Add failing tests for migration CLI |
| 1 (GREEN) | feat | 6028b68 | Implement migration CLI with TDD |

## Known Stubs

None -- all functions are fully implemented with real logic, no placeholders.

## Verification

- `python -m pytest tests/test_migrate.py -x -q` -- 8 passed
- `python migrate.py --help` -- shows all flags
- `python migrate.py` (no args) -- exits 2 with usage error

## Self-Check: PASSED

- migrate.py: FOUND
- tests/test_migrate.py: FOUND
- 31-01-SUMMARY.md: FOUND
- Commit abda737: FOUND
- Commit 6028b68: FOUND

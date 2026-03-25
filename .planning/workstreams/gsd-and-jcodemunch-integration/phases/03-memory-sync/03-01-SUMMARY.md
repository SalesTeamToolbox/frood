---
phase: 03-memory-sync
plan: "01"
subsystem: memory
tags: [memory, uuid, migration, embeddings, frontmatter]
dependency_graph:
  requires: []
  provides: [uuid-entry-identity, yaml-frontmatter, legacy-migration, embedding-tag-stripping]
  affects: [memory/store.py, memory/embeddings.py, tests/test_memory_sync.py]
tech_stack:
  added: [asyncio.Lock, uuid.uuid5, re.compile]
  patterns: [frozen-module-constants, tdd-red-green, sentinel-file-guard, deterministic-uuid5]
key_files:
  created:
    - tests/test_memory_sync.py
  modified:
    - memory/store.py
    - memory/embeddings.py
decisions:
  - "UUID5 namespace reused from memory_tool.py (a42a42a4-...) for cross-module determinism"
  - "reindex_memory() reads raw file directly to avoid triggering migration inside update_memory() -> _schedule_reindex() cycle"
  - "_ensure_uuid_frontmatter() recovers file_id from on-disk file when new content has no frontmatter, ensuring stable identity across full-replace writes"
metrics:
  duration: "~20 minutes"
  completed: "2026-03-25"
  tasks: 1
  files: 3
---

# Phase 03 Plan 01: UUID Injection + Frontmatter + Migration + Embedding Tag Stripping Summary

UUID+timestamp identity layer added to MEMORY.md entries via `_make_entry_prefix()` injection in `append_to_section()`, YAML frontmatter management in `update_memory()`, deterministic UUID5 auto-migration of legacy bullets in `_maybe_migrate()`, and tag stripping in `EmbeddingStore._split_into_chunks()`.

## What Was Built

### memory/store.py — UUID identity layer

New module-level constants and helpers:
- `_ENTRY_TAG_RE` — regex matching `[ISO_TS 8HEX]` tags
- `_ENTRY_NO_UUID_RE` — matches bullet lines without UUID prefix (migration targets)
- `_FRONTMATTER_RE` — matches YAML frontmatter block at file start
- `_MIGRATION_LOCK` — asyncio.Lock guarding concurrent migration
- `_UUID5_NAMESPACE` — shared namespace UUID for deterministic IDs
- `_make_entry_prefix()` — generates `[2026-03-25T03:42:49Z a4b8c2d1]` style prefix

New MemoryStore methods:
- `_ensure_uuid_frontmatter(content)` — wraps/updates YAML frontmatter; recovers file_id from disk for full-replace writes
- `_maybe_migrate()` — async method that migrates old bullets to UUID format with sentinel guard

Modified MemoryStore methods:
- `append_to_section()` — inserts `_make_entry_prefix()` before bullet content
- `update_memory()` — calls `_ensure_uuid_frontmatter()` before writing
- `read_memory()` — calls `_maybe_migrate()` on first access (sentinel guards repeat runs)
- `reindex_memory()` — changed to raw `memory_path.read_text()` to avoid triggering migration inside `_schedule_reindex()`

### memory/embeddings.py — Tag stripping

- Added `import re`
- Added `_ENTRY_TAG_RE` module-level constant
- Modified `_split_into_chunks()` to apply `_ENTRY_TAG_RE.sub("", line)` before processing each line, stripping `[timestamp uuid]` tags from bullet text before it becomes embedding content

### tests/test_memory_sync.py — Full test scaffold

14 tests across 5 classes:
- `TestUuidInjection` (3 tests): UUID prefix on append, unique UUIDs per append, update_memory no injection
- `TestFrontmatter` (3 tests): frontmatter added on update, file_id preserved across updates, fresh file
- `TestMigration` (4 tests): old bullets migrated, deterministic UUID5, existing UUIDs preserved, section headings untouched
- `TestMigrationSentinel` (2 tests): sentinel created after migration, sentinel prevents re-migration
- `TestEmbeddingTagStripping` (2 tests): tags stripped before chunking, plain lines unchanged

## TDD Execution

**RED:** `35f6dec` — 14 tests written, all failing (expected: `- hello` vs `- [ts uuid] hello`)

**GREEN:** `f995fe8` — Implementation added; all 14 tests pass + 81 existing memory tests pass

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Migration triggered inside update_memory() via _schedule_reindex()**
- **Found during:** GREEN implementation
- **Issue:** `update_memory()` calls `_schedule_reindex()` → `reindex_memory()` → `read_memory()` → `_maybe_migrate()`. Since ONNX embeddings are available locally, the reindex runs synchronously via `asyncio.run()`, which triggered migration inside the update cycle. This caused `update_memory(raw_content)` to migrate plain bullets, violating the "writes content as-is for merge/migration paths" requirement.
- **Fix:** Changed `reindex_memory()` to use `memory_path.read_text()` directly instead of `read_memory()`, isolating the migration trigger to external callers only.
- **Files modified:** `memory/store.py`
- **Commit:** `f995fe8`

**2. [Rule 1 - Bug] file_id not preserved across full-replace update_memory() calls**
- **Found during:** GREEN implementation (test_frontmatter_preserves_file_id failure)
- **Issue:** `update_memory("# Second\n")` passes content with no frontmatter to `_ensure_uuid_frontmatter()`. The method had no frontmatter in the new content, so it generated a fresh file_id, breaking identity persistence.
- **Fix:** Added disk-read fallback in the `else` branch of `_ensure_uuid_frontmatter()` — reads existing `memory_path` to extract and preserve the file_id from the previous write.
- **Files modified:** `memory/store.py`
- **Commit:** `f995fe8`

## Known Stubs

None — all behaviors are fully wired.

## Self-Check: PASSED

- tests/test_memory_sync.py: FOUND
- memory/store.py: FOUND
- memory/embeddings.py: FOUND
- 03-01-SUMMARY.md: FOUND
- commit 35f6dec (RED tests): FOUND
- commit f995fe8 (GREEN implementation): FOUND

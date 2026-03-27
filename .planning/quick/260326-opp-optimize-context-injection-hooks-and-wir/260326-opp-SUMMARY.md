---
phase: quick
plan: 260326-opp
subsystem: hooks, dashboard
tags: [performance, caching, token-stats, context-injection]
dependency_graph:
  requires: []
  provides: [session-file-cache, search-result-cache, jcodemunch-token-stats]
  affects: [context-loader, memory-recall, dashboard-token-stats]
tech_stack:
  added: []
  patterns: [mtime-cache, ttl-cache, aiofiles-async-read]
key_files:
  created: []
  modified:
    - .claude/hooks/context-loader.py
    - .claude/hooks/memory-recall.py
    - dashboard/server.py
decisions:
  - "Used Path(__file__).parent.parent in server.py to locate .claude/.jcodemunch-stats.json — consistent with existing server.py path resolution pattern"
  - "Imported aiofiles/json locally inside get_token_stats() — consistent with server.py pattern of local imports in endpoint functions"
  - "Cache stored at module level in hooks — persists within process lifetime; if each hook invocation is a fresh process the cache warms on first call per process, still correct behavior"
metrics:
  duration: 8m
  completed: 2026-03-27T00:56:40Z
  tasks_completed: 2
  files_modified: 3
---

# Phase quick Plan 260326-opp: Optimize Context Injection Hooks and Wire Token Stats Summary

**One-liner:** mtime-based file cache for context-loader, 60s TTL keyword cache for memory-recall, and jcodemunch-stats.json wired to /api/stats/tokens.

## Tasks Completed

| # | Task | Commit | Files |
|---|------|--------|-------|
| 1 | Add mtime file cache to context-loader + TTL search cache to memory-recall | 9230810 | .claude/hooks/context-loader.py, .claude/hooks/memory-recall.py |
| 2 | Wire /api/stats/tokens to read jcodemunch-stats.json | 768ffed | dashboard/server.py |

## What Was Built

### Task 1: Hook Caches

**context-loader.py:**
- Added module-level `_file_cache: dict[str, tuple[float, str]] = {}` mapping file path to `(mtime, content)`
- Added `_cached_read(path)` helper that checks `os.stat(path).st_mtime` before reading; returns cached content when mtime matches
- `load_lessons()` and `load_reference_files()` now call `_cached_read()` instead of `open()` directly
- Effect: avoids re-reading large reference files (pitfalls-archive.md, etc.) when content is unchanged

**memory-recall.py:**
- Added `import time` at module level
- Added `_search_cache: dict[str, tuple[float, list]] = {}` and `_SEARCH_CACHE_TTL = 60`
- Added `_cache_key(keywords)`, `_get_cached_search(key)`, `_set_cached_search(key, results)` helpers
- In `main()`: computes `search_key = _cache_key(keywords)` after keyword extraction; checks cache before all search layers; populates cache after ranking/deduplication
- Effect: identical keyword sets within 60s skip all HTTP calls to search service / Qdrant

### Task 2: Token Stats Endpoint

**dashboard/server.py — `get_token_stats` endpoint:**
- Replaced stub that returned all zeros with async file read of `.claude/.jcodemunch-stats.json`
- Uses `Path(__file__).parent.parent` to locate project root (consistent with server.py conventions)
- Reads via `aiofiles` (async I/O, per project rules)
- Returns full `jcodemunch` sub-object: tokens_used, tokens_saved, tokens_avoided, calls, files_targeted, by_tool breakdown, session_start, last_updated
- Gracefully returns zeros when stats file doesn't exist (OSError/ValueError caught)

## Deviations from Plan

None — plan executed exactly as written.

## Known Stubs

None — all wired to real data or well-defined fallback zeros.

## Self-Check: PASSED

Files exist:
- .claude/hooks/context-loader.py — FOUND
- .claude/hooks/memory-recall.py — FOUND
- dashboard/server.py — FOUND

Commits exist:
- 9230810 — FOUND (feat: add mtime file cache and TTL search cache to hooks)
- 768ffed — FOUND (feat: wire /api/stats/tokens to jcodemunch-stats.json)

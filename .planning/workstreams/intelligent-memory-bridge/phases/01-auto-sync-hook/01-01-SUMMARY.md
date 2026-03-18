---
phase: 01-auto-sync-hook
plan: 01
subsystem: memory
tags: [qdrant, onnx, embeddings, hooks, claude-code, uuid5, subprocess]

requires: []

provides:
  - "PostToolUse hook that detects CC memory file writes and spawns background worker"
  - "Background worker that ONNX-embeds CC memory files and upserts to Qdrant"
  - "File-path-based UUID5 dedup ensuring edits overwrite the same Qdrant point"
  - "Silent failure handling for Qdrant unavailability, missing ONNX, missing files"
  - "21 tests covering path detection, dedup, sync, and failure silence"

affects: [01-02, intelligent-memory-bridge]

tech-stack:
  added: []
  patterns:
    - "Hook entry point uses stdlib-only imports for <5ms startup latency"
    - "Background worker bootstraps sys.path via script_dir.parent.parent before Agent42 imports"
    - "Detached subprocess with DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP on Windows"
    - "UUID5 namespace a42a42a4-2a42-4a42-a42a-42a42a42a42a with file-path key for dedup"
    - "Status file at .agent42/cc-sync-status.json tracks last_sync, total_synced, last_error"

key-files:
  created:
    - .claude/hooks/cc-memory-sync.py
    - .claude/hooks/cc-memory-sync-worker.py
    - tests/test_cc_memory_sync.py
  modified: []

key-decisions:
  - "Hook entry point is stdlib-only — zero Agent42 imports keeps startup under 5ms (PostToolUse fires on every CC Write/Edit)"
  - "Worker bypasses upsert_single/upsert_vectors and calls _client.upsert() directly with a manually-computed point ID — existing methods hash content into the ID, breaking file-path-based dedup (SYNC-03)"
  - "Path detection uses Path.parts inspection for the .claude/projects/*/memory/*.md sequence — works cross-platform without regex"
  - "All worker failures (Qdrant down, ONNX missing, file missing) are silent; only status file records errors (SYNC-04)"

patterns-established:
  - "CC hook entry point pattern: stdlib-only, detached Popen, always exit 0"
  - "Worker bootstrap pattern: script_dir.parent.parent for project root, sys.path.insert(0) before imports"

requirements-completed: [SYNC-01, SYNC-02, SYNC-03, SYNC-04]

duration: 7min
completed: 2026-03-18
---

# Phase 01 Plan 01: Auto-Sync Hook Implementation Summary

**PostToolUse hook + detached ONNX worker that automatically mirrors CC memory file writes to Qdrant with file-path-based UUID5 dedup and fully silent failure handling**

## Performance

- **Duration:** 7 min
- **Started:** 2026-03-18T23:38:24Z
- **Completed:** 2026-03-18T23:44:54Z
- **Tasks:** 2 (TDD: RED + GREEN for each)
- **Files modified:** 3

## Accomplishments
- `cc-memory-sync.py`: stdlib-only PostToolUse hook that detects `~/.claude/projects/*/memory/*.md` writes and fires a detached background worker with no latency cost to CC
- `cc-memory-sync-worker.py`: background worker that reads the file, generates 384-dim ONNX embeddings, and upserts to Qdrant `agent42_memory` collection using a deterministic file-path-only UUID5 point ID
- `tests/test_cc_memory_sync.py`: 21 tests across 4 classes covering all 4 SYNC requirements; all passing with no regressions in the full 1424-test suite

## Task Commits

Each task was committed atomically:

1. **Task 1: Create test suite for CC memory sync (RED)** - `2d3e87e` (test)
2. **Task 2: Create hook entry point and background worker (GREEN)** - `5cf9cb5` (feat)

_Note: TDD tasks — RED commit first, then GREEN commit with implementation + test fix_

## Files Created/Modified
- `.claude/hooks/cc-memory-sync.py` - PostToolUse hook entry point (stdlib-only, detached Popen)
- `.claude/hooks/cc-memory-sync-worker.py` - ONNX embed + Qdrant upsert worker (bootstraps sys.path)
- `tests/test_cc_memory_sync.py` - 21 tests for path detection, dedup, sync, silent failure

## Decisions Made
- **Bypass upsert_single for dedup**: The existing `_make_point_id(text, source)` in QdrantStore hashes the text content into the UUID, so editing a file creates a new point instead of overwriting. Direct `_client.upsert()` with `make_point_id(file_path)` (file-path-only UUID5) ensures SYNC-03 dedup is correct.
- **stdlib-only hook entry point**: PostToolUse fires on every Write/Edit — importing Agent42 modules in the hook would add 200-500ms latency per write. Worker does all heavy imports after being detached.
- **Path.parts over regex**: `Path(file_path).parts.index(".claude")` handles Windows backslash and Unix forward-slash paths identically without platform-specific regex.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test call_args parsing for mock_client.upsert**
- **Found during:** Task 2 (GREEN phase, test run)
- **Issue:** Test `test_worker_payload_has_source_claude_code` used `call_kwargs[1].get("points") or call_kwargs[0][1] if call_kwargs[0] else []` — the ternary operator evaluated incorrectly when `call_kwargs[0]` was an empty tuple (falsy), yielding `[]` even though `call_kwargs[1]` had the points
- **Fix:** Changed to `ca.kwargs.get("points") or (ca.args[1] if len(ca.args) > 1 else [])` using the named `.kwargs` and `.args` attributes of the call object
- **Files modified:** `tests/test_cc_memory_sync.py`
- **Verification:** All 21 tests pass
- **Committed in:** `5cf9cb5` (Task 2 commit)

---

**Total deviations:** 1 auto-fixed (1 bug in test assertion logic)
**Impact on plan:** Test fix necessary for correctness; no scope changes.

## Issues Encountered
None beyond the test assertion bug documented above.

## User Setup Required
None - no external service configuration required for the hook files themselves. The hooks will activate automatically once registered in `.claude/settings.json` (handled in plan 01-02).

## Next Phase Readiness
- Hook entry point and worker are fully implemented and tested
- Plan 01-02 will register the hook in `.claude/settings.json` and add integration verification
- The `.agent42/cc-sync-status.json` status file will be created on first successful sync

---
*Phase: 01-auto-sync-hook*
*Completed: 2026-03-18*

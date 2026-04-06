---
phase: 27-paperclip-adapter
plan: "01"
subsystem: agent42-paperclip-adapter
tags: [typescript, esm, http-client, tdd, paperclip, sidecar]
dependency_graph:
  requires:
    - dashboard/sidecar.py (endpoints: /sidecar/execute, /sidecar/health, /memory/recall, /memory/store)
    - core/sidecar_models.py (Pydantic models defining camelCase field aliases)
  provides:
    - adapters/agent42-paperclip/src/types.ts (SidecarConfig, parseSidecarConfig, 7 sidecar interfaces)
    - adapters/agent42-paperclip/src/client.ts (Agent42Client with execute/health/memoryRecall/memoryStore)
  affects:
    - adapters/agent42-paperclip/src/index.ts (Plan 02 will create the barrel export)
    - adapters/agent42-paperclip/src/adapter.ts (Plan 02 will implement the Paperclip adapter module)
tech_stack:
  added:
    - "@agent42/paperclip-adapter": TypeScript ESM package with NodeNext module resolution
    - vitest 4.1.2: Test runner for TypeScript ESM packages
    - typescript 6.x: Compiler with strict mode targeting ES2022
    - "@paperclipai/adapter-utils 2026.325.0": Pinned adapter-utils peer dependency
  patterns:
    - Native fetch + AbortController for HTTP timeouts (no external HTTP library)
    - vi.stubGlobal("fetch") for deterministic HTTP mocking without MSW
    - TDD red-green workflow for client implementation
    - NodeNext module resolution (all local imports use .js extension)
key_files:
  created:
    - adapters/agent42-paperclip/package.json
    - adapters/agent42-paperclip/tsconfig.json
    - adapters/agent42-paperclip/.gitattributes
    - adapters/agent42-paperclip/.gitignore
    - adapters/agent42-paperclip/package-lock.json
    - adapters/agent42-paperclip/src/types.ts
    - adapters/agent42-paperclip/src/client.ts
    - adapters/agent42-paperclip/vitest.config.ts
    - adapters/agent42-paperclip/tests/client.test.ts
  modified: []
decisions:
  - Native fetch + AbortController chosen over axios/got — zero runtime dependencies, Node 18+ ships fetch natively
  - vi.stubGlobal("fetch") over MSW — simpler for a library with no DOM; sufficient for unit-testing HTTP contracts
  - execute() has no retry — idempotency guard server-side handles deduplication via runId (D-18)
  - top_k and score_threshold kept as snake_case in MemoryRecallRequest — Python API has no camelCase alias (Research Pitfall 5)
  - timeout test uses capturedSignal.aborted assertion — avoids unhandled rejection from AbortError in mock
metrics:
  duration: "~8 minutes"
  completed: "2026-03-30"
  tasks_completed: 2
  tasks_total: 2
  files_changed: 9
---

# Phase 27 Plan 01: TypeScript Package Scaffold and HTTP Client Summary

**One-liner:** ESM TypeScript package scaffold with NodeNext resolution, defensive SidecarConfig parser, 7 sidecar interface types, and Agent42Client wrapping all 4 sidecar endpoints with per-endpoint timeouts, 5xx retry, and 12 unit tests.

## What Was Built

Created the `adapters/agent42-paperclip/` TypeScript package — a buildable, testable ESM package that forms the foundation for the Paperclip adapter in Plan 02.

### Package scaffold

- `package.json`: `"type": "module"`, ESM exports, pinned `@paperclipai/adapter-utils 2026.325.0`, Node >=18.0.0 engine requirement
- `tsconfig.json`: ES2022 target, NodeNext module + moduleResolution, strict mode, declaration + sourceMap output
- `.gitattributes`: LF line endings enforced for all TS/JSON/JS files (Windows CRLF prevention per Research Pitfall 4)
- `.gitignore`: `dist/` and source maps excluded from version control

### src/types.ts

- `SidecarConfig` interface — 5 fields extracted from `ctx.agent.adapterConfig`
- `parseSidecarConfig(raw: unknown)` — defensive parser with `typeof` guards; returns defaults on null/undefined/non-object input
- 7 sidecar request/response interfaces mirroring Python Pydantic models:
  - `SidecarExecuteRequest` / `SidecarExecuteResponse`
  - `SidecarHealthResponse`
  - `MemoryRecallRequest` / `MemoryRecallResponse` (snake_case `top_k` + `score_threshold` preserved)
  - `MemoryStoreRequest` / `MemoryStoreResponse` (snake_case `point_id` preserved)

### src/client.ts

- `Agent42Client` class with 4 public methods:
  - `execute()`: POST /sidecar/execute, 30s timeout, no retry
  - `health()`: GET /sidecar/health, 5s timeout, no auth header, 1 retry on 5xx
  - `memoryRecall()`: POST /memory/recall, 10s timeout, 1 retry on 5xx
  - `memoryStore()`: POST /memory/store, 10s timeout, 1 retry on 5xx
- `fetchWithTimeout()`: AbortController + setTimeout, clears timeout in finally block to prevent leaks
- `fetchWithRetry()`: calls fetchWithTimeout; on 5xx, waits 1s then retries once

### tests/client.test.ts

12 unit tests covering:
- Success paths for all 4 methods
- 202 Accepted treated as success (not error)
- Non-2xx throws with status code in message
- execute() does NOT retry on 500 (verified by call count)
- health() retries once on 5xx (verified by call count + fake timers)
- memoryRecall() sends `top_k` (not `topK`) in request body
- AbortSignal passes through and fires on timeout

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Timeout test caused unhandled rejection**
- **Found during:** Task 2 GREEN verification
- **Issue:** Original timeout test used a mock that rejected with AbortError, but the rejection happened before `expect().rejects.toThrow()` could attach a handler, causing an unhandled rejection warning that failed the test suite
- **Fix:** Changed test to capture the AbortSignal reference and assert `capturedSignal.aborted === true` after advancing fake timers; client promise caught to prevent unhandled rejection propagation
- **Files modified:** `adapters/agent42-paperclip/tests/client.test.ts`
- **Commit:** 64703a6

**2. [Rule 2 - Missing critical functionality] No .gitignore for build artifacts**
- **Found during:** Task 2 commit check
- **Issue:** `dist/` directory and `package-lock.json` were untracked after running `npx tsc`
- **Fix:** Created `.gitignore` excluding `dist/`, map files, and node_modules; committed `package-lock.json` for reproducible installs
- **Files modified:** `adapters/agent42-paperclip/.gitignore`
- **Commit:** 3a8eaef

## Known Stubs

None. All types, client methods, and tests are fully implemented. The adapter module itself (implementing `ServerAdapterModule`) is intentionally deferred to Plan 02.

## Self-Check: PASSED

Files created:
- FOUND: adapters/agent42-paperclip/package.json
- FOUND: adapters/agent42-paperclip/tsconfig.json
- FOUND: adapters/agent42-paperclip/src/types.ts
- FOUND: adapters/agent42-paperclip/src/client.ts
- FOUND: adapters/agent42-paperclip/tests/client.test.ts
- FOUND: adapters/agent42-paperclip/vitest.config.ts

Commits:
- FOUND: a7a9502 (feat: package scaffold + types.ts)
- FOUND: f8eefc8 (test: RED phase)
- FOUND: 64703a6 (feat: GREEN phase - client.ts)
- FOUND: 3a8eaef (chore: .gitignore + package-lock.json)

Tests: 12/12 passed
TypeScript: tsc --noEmit passes with zero errors
Build: tsc produces dist/ with .js + .d.ts files

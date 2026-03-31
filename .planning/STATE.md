---
gsd_state_version: 1.0
milestone: v2.0
milestone_name: Custom Claude Code UI
status: Ready to execute
stopped_at: Completed 30-01-PLAN.md
last_updated: "2026-03-31T21:37:26.929Z"
progress:
  total_phases: 8
  completed_phases: 6
  total_plans: 17
  completed_plans: 16
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-28)

**Core value:** Agent42 must always be able to run agents reliably, with tiered provider routing ensuring no single provider outage stops the platform.
**Current focus:** Phase 30 — advanced-teamtool-auto-memory

## Current Position

Phase: 30 (advanced-teamtool-auto-memory) — EXECUTING
Plan: 2 of 2

## Completed Milestones

- v1.0, v1.1, v1.2, v1.4, v1.5, v1.6 — see MILESTONES.md
- rewards-v1.0 Performance-Based Rewards — shipped 2026-03-25
- v2.1 Multi-Project Workspace — shipped 2026-03-26 (5 phases, 16/16 reqs, 51 tests)

## Active Workstreams

- **gsd-and-jcodemunch-integration** — Phases 1-3 complete, Phase 4 (Context Engine) next — PAUSED for v4.0
- **custom-claude-code-ui** — Phases 1-4 complete, Phases 5-6 remaining — PAUSED for v4.0

## Accumulated Context

### Decisions

Decisions are logged in PROJECT.md Key Decisions table.

- Phase 24: Sidecar as `--sidecar` CLI flag — additive, existing `python agent42.py` behavior unchanged
- Phase 24: No TypeScript rewrite — thin TS wrapper over Python FastAPI sidecar
- Phase 25/26: Phases 25 and 26 can run in parallel after Phase 24 completes
- Phase 27: Adapter depends on Phases 24+25+26 all complete before end-to-end testing
- [Phase 25-memory-bridge]: recall() bypasses MemoryStore.semantic_search() and calls qdrant._client.query_points() directly — semantic_search() lacks agent_id filter support, scope isolation requires direct FieldCondition on agent_id
- [Phase 25-memory-bridge]: learn_async() wraps full body in try/except for fire-and-forget safety (P7) — callers can use asyncio.create_task() without exception propagation guards
- [Phase 25-memory-bridge]: KeywordIndexParams(type='keyword', is_tenant=True) used for agent_id/company_id indexes to enable Qdrant 1.9+ HNSW co-location optimisation (D-09, D-12)
- [Phase 25]: MemoryBridge shared instance in create_sidecar_app() — one instance shared between HTTP routes and SidecarOrchestrator to prevent duplicate store connections
- [Phase 25]: learn_async fired via asyncio.create_task AFTER _post_callback in execute_async finally block — callback never delayed by learning extraction (D-05)
- [Phase 25]: asyncio.wait_for timeout=0.2 enforced in both HTTP route and execute_async for consistent 200ms recall timeout (MEM-02)
- [Phase 26-tiered-routing-bridge]: obs_count=0 passed to TierDeterminator — new sidecar agents start provisional, never prematurely Bronze (wire real obs_count in Phase 27)
- [Phase 26-tiered-routing-bridge]: analyst->strategy mapping uses resolve_model general-fallback on synthetic (D-07): PROVIDER_MODELS['synthetic'] has no 'strategy' key, falls back to general silently
- [Phase 26-tiered-routing-bridge]: agentRole key in ctx.context uses Paperclip camelCase convention — TODO phase-27 to verify against real payload
- [Phase 26-tiered-routing-bridge]: TieredRoutingBridge constructed once in create_sidecar_app, shared across requests (D-11, D-14)
- [Phase 27-01]: Native fetch + AbortController over axios/got — zero runtime dependencies, Node 18+ ships fetch natively
- [Phase 27-01]: vi.stubGlobal(fetch) over MSW — simpler for a library with no DOM; sufficient for unit-testing HTTP contracts
- [Phase 27-01]: top_k and score_threshold kept as snake_case in MemoryRecallRequest — Python API has no camelCase alias
- [Phase 27]: Near-identity serialize/deserialize: codec's role is defensive parsing + forward-compat, not compression
- [Phase 27]: agentId resolved as (config.agentId || ctx.agent.id): falsy empty-string also falls back to Paperclip ID
- [Phase 27]: JSON.stringify(sessionState) as sessionKey string: matches Python Pydantic sessionKey field type (D-08)
- [Phase 29-01]: TierDeterminator.determine(success_rate, task_volume) used for agent tier in /agent/profile endpoint — sidecar agents use tool invocation counts as obs_count
- [Phase 29-01]: drain_pending_transcripts strips internal SQLite id before returning — prevents leaking DB internals to callers
- [Phase 29]: TestHarness.setup() does not exist in SDK — use plugin.definition.setup(harness.ctx) pattern matching existing worker.test.ts
- [Phase 29]: routing-decisions handler calls client.getAgentSpend — spend data serves routing widget per plan spec
- [Phase 29]: Exclude src/ui from tsc compilation — esbuild handles TSX, preventing rootDir conflict with NodeNext module
- [Phase 29]: companyId passed as context.companyId ?? undefined to match PluginHostContext nullable string | null type
- [Phase 30-advanced-teamtool-auto-memory]: auto_memory defaults to True in AdapterConfig — opt-in disabling via autoMemory:false in adapter payload
- [Phase 30-advanced-teamtool-auto-memory]: Strategy detection reads ctx.context.get('strategy', 'standard') — unknown values fall back to 'standard' with warning log
- [Phase 30-advanced-teamtool-auto-memory]: memoryContext injected into ctx.context dict between routing and execution — allows AgentRuntime to access memories when wired (D-04)

### Pending Todos

None.

### Blockers/Concerns

- Phase 29: Plugin SDK `executeTool` handler signatures need verification — SDK released 2026-03-18 (10 days old). Run `/gsd:research-phase` before planning Phase 29.
- Phase 29: `heartbeatRunEvents` access from plugin worker context not documented — research required before planning.
- Phase 30: `heartbeat.started` event existence unconfirmed (RFC #206 only) — verify before planning Phase 30.
- Phase 30: Paperclip comment threading write API access unconfirmed for wave strategy — verify before planning.

### Quick Tasks Completed

| # | Description | Date | Commit | Directory |
|---|-------------|------|--------|-----------|
| 260325-uwr | Fix Agent42 memory system — 4 issues (vectorization gap, dedup, noise, format) | 2026-03-26 | 32589a1 | [260325-uwr](./quick/260325-uwr-fix-agent42-memory-system-4-issues-vecto/) |
| 260326-opp | Optimize context injection hooks + wire jcodemunch token stats to dashboard | 2026-03-27 | 768ffed | [260326-opp](./quick/260326-opp-optimize-context-injection-hooks-and-wir/) |
| 260326-ufx | Wire jcodemunch + GSD + Agent42 integration — register context-loader.py hook | 2026-03-27 | 7b9e903 | [260326-ufx](./quick/260326-ufx-wire-jcodemunch-gsd-agent42-integration/) |
| 260326-vny | Optimize hook pipeline — 92% per-prompt token reduction | 2026-03-27 | 845f511 | [260326-vny](./quick/260326-vny-optimize-hook-pipeline-remove-redundancy/) |

## Session Continuity

Last session: 2026-03-31T21:37:26.918Z
Stopped at: Completed 30-01-PLAN.md
Resume file: None

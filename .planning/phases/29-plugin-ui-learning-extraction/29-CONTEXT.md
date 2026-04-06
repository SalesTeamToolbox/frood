# Phase 29: Plugin UI + Learning Extraction - Context

**Gathered:** 2026-03-30
**Status:** Ready for planning

<domain>
## Phase Boundary

Operators see agent effectiveness tiers, provider health, and memory traceability in native Paperclip UI slots (detailTab + dashboardWidget), and an hourly job extracts structured learnings from Paperclip run transcripts to close the intelligence feedback loop.

Requirements: UI-01, UI-02, UI-03, UI-04, LEARN-01, LEARN-02.

</domain>

<decisions>
## Implementation Decisions

### UI Slot Architecture
- **D-01:** Plugin declares 4 UI slots in `manifest.json` under `ui.slots[]` — 2 detailTabs (agent effectiveness on `["agent"]`, memory browser on `["run"]`) and 2 dashboardWidgets (provider health, routing decisions)
- **D-02:** New capabilities added to manifest: `ui.detailTab.register`, `ui.dashboardWidget.register`
- **D-03:** `entrypoints.ui` set to `"./dist/ui"` (directory, not file) — SDK bundler contract
- **D-04:** Per-slot file organization: `src/ui/index.tsx` re-exports from `AgentEffectivenessTab.tsx`, `ProviderHealthWidget.tsx`, `MemoryBrowserTab.tsx`, `RoutingDecisionsWidget.tsx`
- **D-05:** Two-step build: `tsc` for worker (Node.js), `esbuild` via SDK's `createPluginBundlerPresets()` for UI (browser ESM, externalize React + SDK UI)
- **D-06:** `react` and `@types/react` added as devDependencies — host provides React at runtime via module registry
- **D-07:** Use SDK shared components: `MetricCard`, `StatusBadge`, `DataTable`, `TimeseriesChart`, `KeyValueList`, `Spinner`, `ErrorBoundary`

### Data API Surface
- **D-08:** 5 new sidecar GET endpoints + 1 extension for UI panel data — each panel gets a dedicated data source, one round trip per panel
- **D-09:** `GET /agent/{agentId}/profile` — combines tier badge, composite score, and agent stats from `EffectivenessStore.get_agent_stats()` + `TierCache`
- **D-10:** `GET /agent/{agentId}/effectiveness` — per-task-type success rate breakdown from `get_aggregated_stats(agent_id)` (exists but not exposed)
- **D-11:** `GET /agent/{agentId}/routing-history` — recent N routing decisions; requires new `routing_decisions` log table in SQLite, populated during `execute_async()`
- **D-12:** Extend `GET /sidecar/health` — widen existing `providers` dict to include per-provider availability status (field is already `dict[str, Any]`, additive and non-breaking)
- **D-13:** `GET /memory/run-trace/{runId}` — recalled memories + extracted learnings for a specific run, filtered by run_id from Qdrant
- **D-14:** `GET /agent/{agentId}/spend?hours=24` — token spend distribution across providers; requires new `spend_history` table in SQLite with hourly aggregation
- **D-15:** All new endpoints require Bearer JWT auth (consistent with existing sidecar pattern) except health extension (already public)
- **D-16:** Worker registers 4 `ctx.data.register()` handlers in `setup()` — one per UI panel — each calls through `Agent42Client` to the corresponding sidecar endpoint

### Learning Job Design
- **D-17:** Learning extraction scheduled via SDK `ctx.jobs` — manifest declares `jobs[]` array with cron schedule (hourly) and `jobs.schedule` capability
- **D-18:** Sidecar captures run transcripts during `execute_async()` into a local store (lightweight SQLite table or append-only queue) — plugin never needs direct `heartbeatRunEvents` access (SDK has no RPC for this)
- **D-19:** Plugin job handler calls `POST /memory/extract` on sidecar — sidecar drains queued transcripts, runs `MemoryBridge.learn_async()` for each, stores structured learnings in Qdrant KNOWLEDGE collection
- **D-20:** Job uses `ctx.state.set({ scopeKind: "instance", stateKey: "last-learn-at" })` as watermark to avoid re-processing
- **D-21:** Batch processing — one LLM extraction call per batch of queued transcripts, not per-run

### Memory Browser (run_id Tracing)
- **D-22:** Thread `run_id` through `MemoryBridge.recall()` and `learn_async()` into Qdrant point payloads — follows existing `task_id` pattern exactly
- **D-23:** Add `run_id` as fifth keyword index in `_ensure_task_indexes()` — idempotent, zero-risk on existing collections
- **D-24:** Memory browser detailTab displays two sections: "Injected Memories" (recalled before run — text, relevance score %, source badge) and "Extracted Learnings" (after run — text, task_type chip, tags as pills)
- **D-25:** Empty states: "No memories were recalled for this run" / "No learnings were extracted yet" (with note that extraction runs hourly)
- **D-26:** `run_id` is already propagated via `AdapterExecutionContext.run_id` into `execute_async()` — gap is only passing it down to MemoryBridge and Qdrant storage

### Claude's Discretion
- Exact manifest.json metadata (displayName, description, categories, version updates)
- Exact cron schedule expression for learning extraction job (e.g., `0 * * * *` vs `30 * * * *`)
- Whether to store recalled memory scores in Qdrant payload at recall time vs re-query at display time
- How the memory browser handles the async delay between run completion and learning extraction (loading skeleton, auto-refresh timer, etc.)
- Exact Pydantic model shapes for new endpoint request/response types
- SQLite schema details for `routing_decisions` and `spend_history` tables
- Error response formatting when sidecar endpoints return errors to the UI
- Vitest test file organization for UI components
- Whether `esbuild` script lives in `build-ui.mjs` or inline in `package.json`
- Exact data shapes for `ctx.data.register()` handler responses

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` — UI-01 through UI-04, LEARN-01, LEARN-02 define all Phase 29 requirements
- `.planning/ROADMAP.md` — Phase 29 success criteria (4 acceptance tests)

### Architecture research
- `.planning/research/ARCHITECTURE.md` — System diagram, component responsibilities, data flow
- `.planning/research/FEATURES.md` — Plugin SDK interface contracts, UI slot rendering APIs, feature dependency graph
- `.planning/research/PITFALLS.md` — P8 (no iframe — use native Paperclip UI slots)
- `.planning/research/SUMMARY.md` §Phase 3 — research flags for detailTab/dashboardWidget APIs and heartbeatRunEvents access

### Plugin SDK (installed)
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/README.md` — Full SDK reference: UI slot types (§19), capabilities (§15), data bridge (§20), jobs (§17), events (§16), shared components (§19.6)
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/ui/components.js` — Shared component exports (MetricCard, StatusBadge, DataTable, TimeseriesChart, etc.)
- `plugins/agent42-paperclip/node_modules/@paperclipai/shared/dist/constants.d.ts` — `PLUGIN_UI_SLOT_TYPES`, `PLUGIN_UI_SLOT_ENTITY_TYPES`, `PLUGIN_CAPABILITIES`
- `plugins/agent42-paperclip/node_modules/@paperclipai/shared/dist/validators/plugin.d.ts` — `pluginUiSlotDeclarationSchema` (Zod schema for manifest validation)

### Prior phase context (dependencies)
- `.planning/phases/28-paperclip-plugin/28-CONTEXT.md` — Plugin package structure, Agent42Client design, tool registration pattern, manifest format
- `.planning/phases/25-memory-bridge/25-CONTEXT.md` — MemoryBridge pattern, recall/store endpoint contracts
- `.planning/phases/26-tiered-routing-bridge/26-CONTEXT.md` — TieredRoutingBridge, RoutingDecision dataclass, cost reporting

### Existing codebase (key files)
- `plugins/agent42-paperclip/manifest.json` — Current manifest (needs UI capabilities, entrypoints.ui, ui.slots additions)
- `plugins/agent42-paperclip/src/worker.ts` — Plugin lifecycle (needs ctx.data.register + ctx.jobs.register calls)
- `plugins/agent42-paperclip/src/client.ts` — Agent42Client (needs new API methods for UI data endpoints)
- `plugins/agent42-paperclip/src/types.ts` — TypeScript types (needs UI data response types)
- `core/memory_bridge.py` — MemoryBridge.recall() and learn_async() (thread run_id through)
- `core/sidecar_orchestrator.py` — execute_async() (pass run_id to recall + learn_async)
- `core/sidecar_models.py` — Pydantic models (add new endpoint request/response models)
- `dashboard/sidecar.py` — Sidecar routes (add 5 new GET endpoints + /memory/extract POST)
- `core/effectiveness.py` — EffectivenessStore (get_agent_stats, get_aggregated_stats — wire to new endpoints)
- `memory/qdrant_store.py` — _ensure_task_indexes() (add run_id keyword index)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `EffectivenessStore.get_agent_stats(agent_id)` — returns success_rate, task_volume, avg_speed; ready to surface via new endpoint
- `EffectivenessStore.get_aggregated_stats()` — can filter by agent_id for per-task-type breakdown; not wired to any route
- `MemoryBridge.learn_async()` — existing learning extraction with instructor + Pydantic; Phase 29 wraps this in a batch endpoint
- `TierCache` in `RewardSystem` — cached tier scores per agent; surface alongside agent stats
- `Agent42Client` in plugin — already wraps all 6 sidecar endpoints; extend with 5 new methods
- SDK `createPluginBundlerPresets()` — provides ready-to-use esbuild config for UI bundle
- SDK shared components (MetricCard, DataTable, StatusBadge, etc.) — host-provided React components for consistent Paperclip UI

### Established Patterns
- **camelCase Pydantic aliases:** All sidecar models use `alias="camelCase"` — new endpoint models follow same pattern
- **Bearer JWT auth:** All endpoints except /health require auth — new endpoints follow same pattern
- **Sidecar file split:** Models in `core/sidecar_models.py`, routes in `dashboard/sidecar.py`, logic in `core/*.py`
- **Qdrant keyword indexes:** `task_id`, `task_type`, `agent_id`, `company_id` already indexed — `run_id` follows identical pattern
- **Plugin tool registration in setup():** `registerTools(ctx, client)` called synchronously before setup resolves — data handlers follow same pattern

### Integration Points
- `dashboard/sidecar.py:create_sidecar_app()` — Add new GET routes + POST /memory/extract
- `core/sidecar_models.py` — Add Pydantic models for all new endpoint request/response types
- `core/sidecar_orchestrator.py:execute_async()` — Pass run_id to recall()/learn_async(), capture transcript to local store
- `memory/qdrant_store.py:_ensure_task_indexes()` — Add run_id keyword index
- `plugins/agent42-paperclip/manifest.json` — Add capabilities, entrypoints.ui, ui.slots, jobs[]
- `plugins/agent42-paperclip/src/worker.ts:setup()` — Add ctx.data.register() for 4 UI data keys + ctx.jobs.register() for learning extraction

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 29-plugin-ui-learning-extraction*
*Context gathered: 2026-03-30*

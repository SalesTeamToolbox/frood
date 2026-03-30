# Phase 26: Tiered Routing Bridge - Context

**Gathered:** 2026-03-29
**Status:** Ready for planning

<domain>
## Phase Boundary

Paperclip agent roles and task metadata drive Agent42 provider and model selection, with tier upgrades for high-performing agents and cost reporting back to Paperclip. TieredRoutingBridge maps Paperclip roles (engineer/researcher/writer/analyst) to Agent42 task categories, queries RewardSystem for agent tier to upgrade model selection, honors AdapterConfig.preferredProvider overrides, and reports costUsd, token counts, model, and provider in every callback response.

</domain>

<decisions>
## Implementation Decisions

### Role-to-Category Mapping
- **D-01:** Static dict constant in TieredRoutingBridge class maps Paperclip roles to Agent42 task categories: engineer→coding, researcher→research, writer→content, analyst→strategy. No runtime configuration needed (ROUTE-01)
- **D-02:** Unknown or missing roles fall back to `general` task category — never error on unrecognized roles
- **D-03:** Base roles only — no prefix-tolerant matching (e.g., no stripping of 'senior_', 'lead_'). Paperclip's role field is a known enum

### Tier-Based Model Upgrades
- **D-04:** TieredRoutingBridge queries `RewardSystem.score(agent_id)` then `TierDeterminator.determine(score, obs_count)` to get the agent's tier (gold/silver/bronze/provisional) (ROUTE-02)
- **D-05:** Tier upgrade uses existing `resolve_model(provider, task_category, tier)` from `core/agent_manager.py` — gold→reasoning, silver→general, bronze→fast. No new upgrade logic needed

### Provider Selection Chain
- **D-06:** Resolution order: (1) `AdapterConfig.preferredProvider` if set → use as provider; (2) otherwise → `synthetic` (L1 workhorse) as default; (3) fall back to `anthropic` if synthetic key is missing (ROUTE-03)
- **D-07:** If preferredProvider is set but doesn't support the tier-upgraded category, fall back to `general` category on that same provider — `resolve_model()` already does this fallback
- **D-08:** Default provider is `synthetic` (StrongWall/L1 workhorse per PROJECT.md Core Value)

### Cost & Usage Reporting
- **D-09:** Wire the plumbing now, populate with real values later — TieredRoutingBridge resolves model+provider and writes them into the usage dict. Token counts and costUsd stay 0 until AgentRuntime is wired in Phase 27+ (ROUTE-04)
- **D-10:** Include a static pricing lookup table (model ID → per-token input/output costs) in the bridge. When real token counts flow from AgentRuntime, costUsd = input_tokens * input_price + output_tokens * output_price. Follows SpendingTracker pattern in server.py

### Bridge Architecture
- **D-11:** New `TieredRoutingBridge` class in `core/tiered_routing_bridge.py` following the MemoryBridge pattern — dedicated class wrapping RewardSystem + resolve_model(), clean testable API
- **D-12:** Bridge API: `resolve(role, agent_id, preferred_provider) → RoutingDecision(provider, model, tier, task_category, cost_estimate)`
- **D-13:** Bridge is internal-only for this phase — called by SidecarOrchestrator.execute_async(), no HTTP endpoint. Plugin gets routing via `route_task` tool in Phase 28 (PLUG-04)
- **D-14:** SidecarOrchestrator already receives `reward_system` in constructor — pass it through to TieredRoutingBridge, or inject bridge directly (same pattern as memory_bridge injection)

### Claude's Discretion
- Exact field names for RoutingDecision dataclass
- Whether TieredRoutingBridge receives RewardSystem directly or accesses it through SidecarOrchestrator
- Pricing table values (per-model token costs)
- Logging format for routing decisions in sidecar structured JSON logs
- Whether to add a `POST /routing/resolve` endpoint later (deferred to Phase 28)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` — ROUTE-01 through ROUTE-04 define all Tiered Routing Bridge requirements
- `.planning/ROADMAP.md` — Phase 26 success criteria (4 acceptance tests)

### Architecture research
- `.planning/research/ARCHITECTURE.md` — Full system diagram, component responsibilities, data flow sequences
- `.planning/research/FEATURES.md` — Feature dependency graph, interface contracts
- `.planning/research/PITFALLS.md` — Critical pitfalls relevant to routing and provider selection

### Prior phase context
- `.planning/phases/24-sidecar-mode/24-CONTEXT.md` — Sidecar architecture decisions (D-01 through D-10), AdapterConfig model, SidecarOrchestrator design
- `.planning/phases/25-memory-bridge/25-CONTEXT.md` — MemoryBridge pattern (the architectural template for TieredRoutingBridge), fire-and-forget patterns, Pydantic model conventions

### Existing codebase (key files to read)
- `core/sidecar_orchestrator.py` — SidecarOrchestrator.execute_async() where routing bridge hooks in, already has reward_system injected
- `core/sidecar_models.py` — AdapterConfig with preferredProvider field, AdapterExecutionContext payload, CallbackPayload with usage dict
- `core/agent_manager.py` — resolve_model() function, PROVIDER_MODELS dict, _TIER_CATEGORY_UPGRADE map
- `core/reward_system.py` — RewardSystem.score(), TierDeterminator.determine(), TierCache
- `core/rewards_config.py` — RewardsConfig with silver_threshold/gold_threshold
- `core/task_types.py` — TaskType enum (CODING, DEBUGGING, RESEARCH, CONTENT, STRATEGY, APP_CREATE, MARKETING, GENERAL)
- `agents/agent_routing_store.py` — AgentRoutingStore per-profile overrides (reference, not directly used in bridge)
- `core/memory_bridge.py` — MemoryBridge class (architectural pattern to follow)
- `dashboard/sidecar.py` — create_sidecar_app() factory, route definitions
- `dashboard/server.py` — SpendingTracker pricing pattern (reference for D-10)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `core/agent_manager.py:resolve_model()` — Already handles tier-based model upgrades (gold→reasoning, silver→general, bronze→fast) with provider+category→model resolution. Bridge wraps this directly
- `core/reward_system.py:RewardSystem` — Already computes and caches composite performance scores per agent_id. Bridge queries this for tier determination
- `core/reward_system.py:TierDeterminator` — Converts score+observation_count to tier string (gold/silver/bronze/provisional). Bridge uses this
- `core/sidecar_models.py:AdapterConfig` — Already has `preferred_provider` field parsed from Paperclip payloads
- `core/sidecar_models.py:CallbackPayload` — Already has `usage` dict field where model/provider/costUsd/tokens go
- `core/memory_bridge.py:MemoryBridge` — Architectural pattern: dedicated bridge class in core/, injected into SidecarOrchestrator

### Established Patterns
- **Bridge injection:** MemoryBridge is constructed in `create_sidecar_app()` and passed to SidecarOrchestrator — TieredRoutingBridge follows same pattern
- **Tier upgrade map:** `_TIER_CATEGORY_UPGRADE` dict in agent_manager.py — static constant, same pattern for role→category mapping
- **Graceful degradation:** RewardSystem is no-op when `REWARDS_ENABLED=false` — bridge must handle this (score returns 0.0, tier is provisional, no upgrade applied)
- **Sidecar file split:** Models in `core/sidecar_models.py`, routes in `dashboard/sidecar.py`, logic in dedicated `core/*.py` files

### Integration Points
- `SidecarOrchestrator.execute_async()` — Insert routing resolution before agent execution stub (between memory recall and the execution step)
- `SidecarOrchestrator.__init__()` — Add `tiered_routing_bridge` parameter alongside existing `memory_bridge` and `reward_system`
- `dashboard/sidecar.py:create_sidecar_app()` — Construct TieredRoutingBridge and inject into SidecarOrchestrator
- `CallbackPayload.usage` dict — Bridge populates `model`, `provider` fields; tokens and costUsd populated when AgentRuntime is wired

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

*Phase: 26-tiered-routing-bridge*
*Context gathered: 2026-03-29*

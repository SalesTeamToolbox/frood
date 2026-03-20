# Phase 18: Agent Config Backend - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Per-agent routing config storage, API endpoints, and inheritance from global defaults. Overrides are stored in a JSON file, served via REST API, and merged with global defaults at routing time. Dashboard UI for viewing/editing config is Phase 19. Streaming simulation is Phase 20.

</domain>

<decisions>
## Implementation Decisions

### Agent Identity
- Overrides keyed by AgentProfile name (e.g., "researcher", "coder") -- natural fit with existing ProfileLoader
- Special `_default` key acts as global runtime override, configurable via API without touching .env
- Agents without a profile assignment use `_default` config directly
- Config stored in `data/agent_routing.json` alongside other runtime config files (dynamic_routing.json pattern)

### Override Scope
- Models only: primary, critic, fallback -- no max_iterations or temperature overrides
- Single fallback model per agent (if it fails, system FALLBACK_ROUTING chain takes over)
- Critic auto-pairs with primary when unset (self-critique pattern from Phase 17: same model, different reviewer prompt)
- L2 escalation flag per agent: Claude's discretion on whether to include

### Resolution Chain
- Env vars remain highest priority (AGENT42_*_MODEL admin overrides, L1_MODEL)
- Per-profile overrides sit between env vars and `_default`
- `_default` overrides sit between per-profile and hardcoded FALLBACK_ROUTING
- Full chain: (1) Admin env override, (2) Per-profile override, (3) _default override, (4) L1 check / FALLBACK_ROUTING, (5) Policy/trial layers
- Hot reload: changes to agent_routing.json take effect on next get_routing() call (lazy read, like dynamic_routing.json)

### API Design
- GET /api/agent-routing/{profile} returns both `overrides` (explicitly set) and `effective` (merged with defaults)
- PUT /api/agent-routing/{profile} sets overrides for a profile
- DELETE /api/agent-routing/{profile} resets profile overrides to defaults
- GET /api/agent-routing returns all profiles with their effective configs

### Model Option Enumeration
- Only show models from providers with configured API keys (no dead options -- CONF-05)
- Group by tier: L1, Fallback, L2
- Include health status per model (healthy/degraded/unhealthy from existing health check system)
- Include current effective routing in the response (dashboard shows "currently using X")

### Claude's Discretion
- Whether to include an `l2_enabled` boolean per agent for L2 escalation control
- File locking / atomic write strategy for agent_routing.json
- Exact validation rules for PUT payload (model key validation, etc.)
- How to integrate profile-level override into ModelRouter.get_routing() (new layer vs modify existing)

</decisions>

<specifics>
## Specific Ideas

- Resolution chain preview format shown in discussion: the API should make it clear what's inherited vs overridden, so the Phase 19 dashboard can render inherited values differently (e.g., grayed out with "inherited from _default" label)
- The `_default` key pattern means Phase 19 dashboard can set global LLM defaults via the same API -- no separate mechanism needed for Settings page vs Agents page

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ProfileLoader` (agents/profile_loader.py): already loads/saves agent profiles by name, has `get()`, `all_profiles()`, `save_profile()` -- config keys match profile names
- `ModelRouter.available_providers()` / `available_models()` (agents/model_router.py:922-930): enumerate configured providers and models -- base for available-models endpoint
- `ProviderRegistry.available_providers()` (providers/registry.py:723): lists providers with availability status
- `JsonFileBackend` (core/queue_backend.py:46): existing JSON file persistence pattern with atomic writes
- `KeyStore` (core/key_store.py:39): reads/writes admin API keys with env-var injection -- similar config persistence pattern
- `ModelRouter._check_dynamic_routing()` (agents/model_router.py:813): lazy file read pattern for dynamic_routing.json -- reuse for agent_routing.json

### Established Patterns
- Lazy file read in get_routing(): dynamic_routing.json is read on each call (no caching) -- simple, always fresh
- Provider API key check via `os.getenv()` at routing time -- used for filtering available models
- Health check integration: `ModelCatalog.is_model_healthy()` + StrongWall health polling (Phase 16)
- Settings is frozen dataclass -- runtime config goes in data/ files, not Settings

### Integration Points
- `agents/model_router.py`: Insert new layer in get_routing() for profile-level overrides
- `dashboard/server.py`: Add REST endpoints (GET/PUT/DELETE /api/agent-routing/*)
- `data/agent_routing.json`: New file for persistent config storage
- `agents/agent.py`: Pass profile name to get_routing() so ModelRouter can look up overrides

</code_context>

<deferred>
## Deferred Ideas

- Per-task-type model selection within a profile (two-level override) -- could be a future enhancement if single-profile overrides prove insufficient
- Temperature and max_iterations overrides -- deferred to avoid misconfiguration risk
- A/B testing between L1 and L2 models -- future requirement ROUTE-04
- Auto-escalation from L1 to L2 based on complexity -- future requirement ROUTE-05

</deferred>

---

*Phase: 18-agent-config-backend*
*Context gathered: 2026-03-07*

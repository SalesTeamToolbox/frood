# Phase 2: Tier Assignment - Context

**Gathered:** 2026-03-22 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

The system automatically assigns Bronze/Silver/Gold tiers to agents based on their performance scores, new agents get a Provisional tier instead of being penalized to Bronze, admin overrides are stored separately and never clobbered by recalculation, and a background task keeps tiers current every 15 minutes. No resource enforcement, no model routing, no dashboard changes.

</domain>

<decisions>
## Implementation Decisions

### AgentConfig Tier Fields
- **D-01:** Add `reward_tier: str = ""`, `tier_override: str | None = None`, `performance_score: float = 0.0`, and `tier_computed_at: str = ""` to the `AgentConfig` dataclass in `core/agent_manager.py`. These round-trip automatically through existing `from_dict()`/`to_dict()`/`asdict()` and persist to `agents/{id}.json`.
- **D-02:** Add `effective_tier() -> str` method to AgentConfig — returns `tier_override` when set (not None), otherwise `reward_tier`. This is the single read point for all downstream consumers (Phase 3 enforcement, Phase 4 dashboard).
- **D-03:** `tier_override` uses `None` as sentinel (no override). Recalculation loop checks `tier_override is not None` before skipping an agent. Matches codebase idiom where `None` means "inherit/unset".

### TierDeterminator
- **D-04:** New `TierDeterminator` class in `core/reward_system.py` (alongside existing ScoreCalculator, TierCache, RewardSystem). Maps `(score: float, observation_count: int) -> str` using thresholds from `RewardsConfig`.
- **D-05:** Returns `"provisional"` when `observation_count < Settings.rewards_min_observations` (default 10). Provisional agents get default resources, never penalized to Bronze.
- **D-06:** Tier names are lowercase strings: `"provisional"`, `"bronze"`, `"silver"`, `"gold"` — consistent with `AgentConfig.status` values (`"active"`, `"stopped"`, `"running"`). No Enum class — `asdict()` doesn't auto-serialize enums.

### Background Recalculation Loop
- **D-07:** Follows HeartbeatService pattern (`core/heartbeat.py:311-329`): `start()`/`stop()` method pair, `asyncio.create_task(self._recalc_loop())`, `_running` flag, `stop()` cancels task.
- **D-08:** Loop interval: 900 seconds (15 min), matching TierCache TTL from Phase 1.
- **D-09:** Recalculation iterates all agents via `AgentManager.list_agents()`, computes score for each, applies TierDeterminator, updates AgentConfig fields, writes to TierCache. Skips agents where `tier_override is not None`.
- **D-10:** Startup registration in `agent42.py` alongside heartbeat service — `RewardSystem.start()` called during initialization when `settings.rewards_enabled` is True.

### Admin Override Persistence
- **D-11:** Override stored on AgentConfig field (`tier_override: str | None`), persisted via existing `agents/{id}.json` mechanism. Set via `AgentManager.update(agent_id, tier_override="gold")`.
- **D-12:** No separate overrides file. `AgentManager.update()` already handles partial updates via `setattr`, making override writes atomic with no new file infrastructure.

### Claude's Discretion
- Whether to emit a log message on tier changes (promotion/demotion)
- Exact error handling in recalculation loop (continue on per-agent error vs. abort)
- Whether recalculation happens immediately on startup or waits for first interval

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase 1 output (foundation)
- `core/reward_system.py` — ScoreCalculator, TierCache, RewardSystem classes built in Phase 1
- `core/rewards_config.py` — Mutable RewardsConfig with silver/gold thresholds
- `core/config.py` — Settings.rewards_enabled, rewards_min_observations, threshold fields

### Agent management
- `core/agent_manager.py` — AgentConfig dataclass (line 128-167), from_dict/to_dict, _save(), update() with setattr, list_agents()
- `agents/agent_routing_store.py` — File-backed mutable config pattern reference

### Background loop pattern
- `core/heartbeat.py` — HeartbeatService start()/stop(), _monitor_loop() — canonical background task pattern

### Startup registration
- `agent42.py` — Main entry point where services are initialized and started

### Existing tests
- `tests/test_reward_system.py` — Phase 1 tests for ScoreCalculator, TierCache, RewardSystem
- `tests/test_agent_manager.py` — Existing AgentConfig/AgentManager tests

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `RewardSystem.score(agent_id)` — already computes composite score from effectiveness data (Phase 1)
- `TierCache.set(agent_id, score)` / `TierCache.get(agent_id)` — TTL cache with persistence (Phase 1)
- `AgentManager.update(**kwargs)` — partial updates via setattr, auto-persists to JSON
- `AgentManager.list_agents()` — returns all agent IDs for iteration
- `HeartbeatService._monitor_loop()` — canonical async background loop pattern

### Established Patterns
- Lowercase string status values on AgentConfig — `"active"`, `"stopped"`, `"running"`
- `None` as "inherit/unset" sentinel — `AgentRoutingStore` strips None values
- `asyncio.create_task()` for background loops — `HeartbeatService`, `SecurityScanner`
- Fire-and-forget in `ToolRegistry.execute()` — Phase 1 established this for effectiveness tracking

### Integration Points
- `core/reward_system.py` — TierDeterminator added here alongside Phase 1 classes
- `core/agent_manager.py` AgentConfig — new fields added to existing dataclass
- `agent42.py` — RewardSystem.start() registration during init

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. Phase 1 patterns are well established.

</specifics>

<deferred>
## Deferred Ideas

- Resource enforcement (model routing, rate limits, concurrency) — Phase 3
- Dashboard REST API for override management — Phase 4
- Dashboard UI for tier display — Phase 4
- Override expiry dates — Phase 4 (dashboard UI needed)
- Tier change audit log — v2
- Hysteresis/cooldown — v2

### Reviewed Todos (not folded)
None — no matching todos found.

</deferred>

---

*Phase: 02-tier-assignment*
*Context gathered: 2026-03-22*

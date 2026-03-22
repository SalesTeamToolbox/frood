# Phase 1: Foundation - Context

**Gathered:** 2026-03-22 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

The rewards system has a complete data foundation — config gate, schema with agent_id, composite scoring, in-memory TTL cache, and restart recovery — such that tier computation is possible but all new behavior is gated behind REWARDS_ENABLED=false. No tier assignment logic, no resource enforcement, no dashboard changes.

</domain>

<decisions>
## Implementation Decisions

### Schema Extension
- **D-01:** Add `agent_id` column to existing `tool_invocations` table via SQLite `ALTER TABLE` migration in `_ensure_db()`. Do NOT create a separate `agent_performance` table.
- **D-02:** Thread `agent_id` from `ToolRegistry.execute()` into `EffectivenessStore.record()` — the value is already available at `registry.py:87` but dropped before the `record()` call at line 131-138. Only one call site to change.
- **D-03:** Add `get_agent_stats(agent_id)` method to EffectivenessStore — reuse existing `get_aggregated_stats()` query with `WHERE agent_id = ?` filter. Returns success_rate, task_volume (COUNT), avg_speed (AVG duration_ms).

### RewardsConfig Runtime Toggle
- **D-04:** `RewardsConfig` is a non-frozen dataclass backed by `.agent42/rewards_config.json`, following the `AgentRoutingStore` pattern (`agents/agent_routing_store.py`): mtime-based lazy loading, atomic write via `os.replace()`, in-memory cache invalidated on write.
- **D-05:** `Settings.rewards_enabled` (frozen) serves as startup gate only. The mutable `RewardsConfig` handles runtime on/off state and threshold overrides without server restart.

### Tier Cache and Persistence
- **D-06:** In-memory TTL cache uses `time.monotonic()` timestamps in a plain dict keyed by `agent_id` — same pattern as `ToolRateLimiter` (`core/rate_limiter.py:59,81`). No `cachetools` import (project uses hand-rolled TTL dicts throughout).
- **D-07:** Persistence file at `.agent42/tier_assignments.json` — follows `.agent42/` data directory convention (approvals.jsonl, devices.jsonl, memory/, sessions/ all live there).
- **D-08:** Cache warmed from persistence file on startup. Background recalculation writes to both cache and file atomically.

### Composite Score
- **D-09:** Score formula: `success_rate * 0.60 + volume_normalized * 0.25 + speed_normalized * 0.15` with all three weights configurable via env vars (`REWARDS_WEIGHT_SUCCESS`, `REWARDS_WEIGHT_VOLUME`, `REWARDS_WEIGHT_SPEED`).
- **D-10:** All three dimensions derived from existing `tool_invocations` columns — no new data collection. Volume and speed normalized to 0-1 range relative to fleet maximum.

### Config Environment Variables
- **D-11:** All reward settings added to `Settings` frozen dataclass with defaults. `from_env()` method parses: `REWARDS_ENABLED` (bool, default false), `REWARDS_SILVER_THRESHOLD` (float, 0.65), `REWARDS_GOLD_THRESHOLD` (float, 0.85), `REWARDS_MIN_OBSERVATIONS` (int, 10), weight vars, and per-tier resource limits.

### Claude's Discretion
- Exact normalization function for volume and speed (min-max, z-score, or percentile)
- TTL duration for cache (suggested 15 minutes based on research)
- Whether to log a startup message when rewards is enabled/disabled
- Test fixture design for effectiveness store with agent_id

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Configuration pattern
- `core/config.py` — Frozen dataclass Settings, `from_env()` method, all existing env var patterns
- `agents/agent_routing_store.py` — Mutable file-backed config pattern (mtime lazy load, atomic write) — model for RewardsConfig

### Effectiveness tracking
- `memory/effectiveness.py` — EffectivenessStore class, `tool_invocations` schema, `record()` and `get_aggregated_stats()` methods
- `tools/registry.py` — `ToolRegistry.execute()` — where `agent_id` is available but not forwarded to effectiveness store

### Rate limiter (cache pattern reference)
- `core/rate_limiter.py` — TTL cache pattern using `time.monotonic()`, sliding window, defaultdict

### Existing tests
- `tests/test_effectiveness.py` — Current effectiveness store tests (need agent_id updates)

### Research findings
- `.planning/workstreams/performance-based-rewards/research/SUMMARY.md` — Full research synthesis
- `.planning/workstreams/performance-based-rewards/research/PITFALLS.md` — Pitfalls 1-3 directly relevant to Phase 1

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `EffectivenessStore.get_aggregated_stats()` — existing query for success_rate, count, avg_duration; add WHERE agent_id clause for per-agent stats
- `AgentRoutingStore` — complete file-backed mutable config implementation; copy pattern for RewardsConfig
- `ToolRateLimiter` — TTL cache with `time.monotonic()` and sliding window; copy pattern for tier cache
- `Settings.from_env()` — established env var parsing with type coercion patterns

### Established Patterns
- Frozen dataclass for immutable config (`Settings`) — new fields follow existing pattern
- File-backed mutable state with JSON + mtime (`AgentRoutingStore`, `agents.json`) — RewardsConfig follows this
- `.agent42/` directory for all runtime state files — tier persistence goes here
- `_ensure_db()` method for lazy schema initialization — migration runs here
- `asyncio.create_task()` for fire-and-forget operations (`ToolRegistry.execute()` line 131)

### Integration Points
- `ToolRegistry.execute()` line 131-138 — add `agent_id` parameter to `record()` call
- `memory/effectiveness.py` `_ensure_db()` — add `ALTER TABLE tool_invocations ADD COLUMN agent_id TEXT DEFAULT ''`
- `core/config.py` Settings class — add `rewards_enabled` and threshold fields
- New file: `core/reward_system.py` — RewardSystem class with score calculation, cache, persistence

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches. Research provides clear patterns for all decisions.

</specifics>

<deferred>
## Deferred Ideas

- Tier assignment logic (Bronze/Silver/Gold thresholds) — Phase 2
- Admin override data model — Phase 2
- Background recalculation scheduling — Phase 2
- Model routing integration — Phase 3
- Dashboard API/UI — Phase 4
- Hysteresis and audit trail — v2

### Reviewed Todos (not folded)
None — no matching todos found.

</deferred>

---

*Phase: 01-foundation*
*Context gathered: 2026-03-22*

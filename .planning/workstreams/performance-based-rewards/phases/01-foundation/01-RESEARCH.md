# Phase 1: Foundation - Research

**Researched:** 2026-03-22
**Domain:** Python async data layer — SQLite schema migration, frozen dataclass config, mutable file-backed config, TTL cache, composite scoring
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Add `agent_id` column to existing `tool_invocations` table via SQLite `ALTER TABLE` migration in `_ensure_db()`. Do NOT create a separate `agent_performance` table.
- **D-02:** Thread `agent_id` from `ToolRegistry.execute()` into `EffectivenessStore.record()` — the value is already available at `registry.py:87` but dropped before the `record()` call at line 131-138. Only one call site to change.
- **D-03:** Add `get_agent_stats(agent_id)` method to EffectivenessStore — reuse existing `get_aggregated_stats()` query with `WHERE agent_id = ?` filter. Returns success_rate, task_volume (COUNT), avg_speed (AVG duration_ms).
- **D-04:** `RewardsConfig` is a non-frozen dataclass backed by `.agent42/rewards_config.json`, following the `AgentRoutingStore` pattern (`agents/agent_routing_store.py`): mtime-based lazy loading, atomic write via `os.replace()`, in-memory cache invalidated on write.
- **D-05:** `Settings.rewards_enabled` (frozen) serves as startup gate only. The mutable `RewardsConfig` handles runtime on/off state and threshold overrides without server restart.
- **D-06:** In-memory TTL cache uses `time.monotonic()` timestamps in a plain dict keyed by `agent_id` — same pattern as `ToolRateLimiter` (`core/rate_limiter.py:59,81`). No `cachetools` import.
- **D-07:** Persistence file at `.agent42/tier_assignments.json` — follows `.agent42/` data directory convention.
- **D-08:** Cache warmed from persistence file on startup. Background recalculation writes to both cache and file atomically.
- **D-09:** Score formula: `success_rate * 0.60 + volume_normalized * 0.25 + speed_normalized * 0.15` with all three weights configurable via env vars (`REWARDS_WEIGHT_SUCCESS`, `REWARDS_WEIGHT_VOLUME`, `REWARDS_WEIGHT_SPEED`).
- **D-10:** All three dimensions derived from existing `tool_invocations` columns — no new data collection. Volume and speed normalized to 0-1 range relative to fleet maximum.
- **D-11:** All reward settings added to `Settings` frozen dataclass with defaults. `from_env()` method parses: `REWARDS_ENABLED` (bool, default false), `REWARDS_SILVER_THRESHOLD` (float, 0.65), `REWARDS_GOLD_THRESHOLD` (float, 0.85), `REWARDS_MIN_OBSERVATIONS` (int, 10), weight vars, and per-tier resource limits.

### Claude's Discretion

- Exact normalization function for volume and speed (min-max, z-score, or percentile)
- TTL duration for cache (suggested 15 minutes based on research)
- Whether to log a startup message when rewards is enabled/disabled
- Test fixture design for effectiveness store with agent_id

### Deferred Ideas (OUT OF SCOPE)

- Tier assignment logic (Bronze/Silver/Gold thresholds) — Phase 2
- Admin override data model — Phase 2
- Background recalculation scheduling — Phase 2
- Model routing integration — Phase 3
- Dashboard API/UI — Phase 4
- Hysteresis and audit trail — v2
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| CONF-01 | System respects `REWARDS_ENABLED` flag (default false) — zero behavioral change when disabled | Settings.rewards_enabled field added to frozen dataclass; all RewardSystem code guards on this flag |
| CONF-02 | Tier thresholds configurable via env vars | `REWARDS_SILVER_THRESHOLD`, `REWARDS_GOLD_THRESHOLD` added to Settings.from_env() |
| CONF-03 | Per-tier resource limits configurable via env vars | Model tier, rate limit multiplier, max concurrent task fields in Settings |
| CONF-04 | Score weights configurable via env vars | `REWARDS_WEIGHT_SUCCESS`, `REWARDS_WEIGHT_VOLUME`, `REWARDS_WEIGHT_SPEED` in Settings |
| CONF-05 | Runtime toggle via mutable RewardsConfig file without server restart | AgentRoutingStore pattern — mtime-based lazy load, atomic write via os.replace() |
| DATA-01 | Effectiveness tracking includes agent_id for per-agent performance queries | ALTER TABLE migration + record() signature extension + ToolRegistry.execute() threading |
| DATA-02 | get_agent_stats(agent_id) on EffectivenessStore returns success_rate, task_volume, avg_speed | New method reusing get_aggregated_stats() query pattern with WHERE agent_id = ? filter |
| TIER-01 | Composite performance score from existing effectiveness data (success_rate, volume, speed with configurable weights) | ScoreCalculator class in core/reward_system.py — pure computation, no new data |
| TIER-04 | Tier cached in memory with TTL — never computed on routing hot path | TTL dict with time.monotonic() — same pattern as ToolRateLimiter |
| TIER-05 | Tier persisted to file for restart recovery — cache warmed on startup | .agent42/tier_assignments.json, same convention as agents.json, cron_jobs.json |
| TEST-01 | Unit tests for score calculation logic (composite weights, edge cases, zero data) | tests/test_reward_system.py — parametrized weight tests, zero-data returns 0.0 |
| TEST-05 | Graceful degradation tests — rewards disabled produces identical behavior to pre-feature baseline | Test Settings.rewards_enabled=False path; verify no DB reads, no RewardsConfig loaded |
</phase_requirements>

---

## Summary

Phase 1 is entirely an internal data layer build — no UI, no agent behavior changes, no new external dependencies. All patterns have direct precedents in the existing codebase. The three primary deliverables are: (1) `Settings` frozen dataclass extended with reward config fields; (2) a new mutable `RewardsConfig` file-backed config object; (3) a new `core/reward_system.py` module containing the score calculator and TTL tier cache, plus the `EffectivenessStore` schema migration and `get_agent_stats()` method.

The entire phase is gated behind `REWARDS_ENABLED=false` by default. When disabled, zero code paths from the rewards module execute — the startup gate is checked once in `RewardSystem.__init__()` and the module becomes a no-op. This satisfies CONF-01 and TEST-05 with a single structural guard rather than scattered `if` checks throughout the codebase.

**Primary recommendation:** Copy patterns directly from `AgentRoutingStore` for `RewardsConfig`, from `ToolRateLimiter` for the TTL cache, and from `get_aggregated_stats()` for `get_agent_stats()`. No new patterns need to be invented — this phase is essentially "apply existing patterns to a new domain."

---

## Standard Stack

### Core

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `aiosqlite` | existing in requirements.txt | SQLite schema migration + per-agent stats query | Already used by EffectivenessStore; no new dep |
| `dataclasses` (stdlib) | Python 3.11+ | `RewardsConfig` non-frozen dataclass, `TierResult` frozen dataclass | Project-wide pattern in config.py, rate_limiter.py |
| `enum.IntEnum` (stdlib) | Python 3.11+ | `RewardTier` enum supporting `>=` comparisons | Enables `tier >= SILVER` without string comparison |
| `time.monotonic()` (stdlib) | Python 3.11+ | TTL cache timestamp | Used identically in ToolRateLimiter |
| `os.replace()` (stdlib) | Python 3.11+ | Atomic JSON file writes | Used identically in AgentRoutingStore |
| `json` (stdlib) | Python 3.11+ | RewardsConfig and tier_assignments.json serialization | Same as all existing .agent42/ file-backed stores |

### No New Dependencies

This phase requires zero new packages. All stdlib or already in `requirements.txt`.

```bash
# Verify aiosqlite is installed (it should be)
pip show aiosqlite
```

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Hand-rolled TTL dict | `cachetools.TTLCache` | cachetools may be a transitive dep but project explicitly uses hand-rolled TTL dicts throughout — stay consistent |
| `ALTER TABLE ADD COLUMN` | Separate `agent_performance` table | D-01 locks ALTER TABLE; simpler, fewer queries, consistent schema |
| `os.replace()` atomic write | `pathlib.write_text()` | os.replace() is atomic on all OS; write_text() is not — always use os.replace() for file-backed state |

---

## Architecture Patterns

### Recommended Project Structure

```
core/
├── config.py           # EXTEND: add rewards_enabled, threshold, weight fields to Settings
├── reward_system.py    # NEW: RewardSystem, ScoreCalculator, TierCache, RewardsConfig
memory/
├── effectiveness.py    # EXTEND: agent_id migration, record() signature, get_agent_stats()
tools/
├── registry.py         # EXTEND: thread agent_id into effectiveness_store.record() call
tests/
├── test_reward_system.py  # NEW: score calculation, cache, config, graceful degradation
├── test_effectiveness.py  # EXTEND: add agent_id tests to existing test class
.agent42/
├── rewards_config.json    # CREATED AT RUNTIME: mutable RewardsConfig backing file
├── tier_assignments.json  # CREATED AT RUNTIME: TTL cache persistence
```

### Pattern 1: Settings Extension (Frozen Dataclass)

**What:** Add reward-specific fields to the existing frozen `Settings` dataclass in `core/config.py`.
**When to use:** All startup-time config that does not need to change at runtime — the enable gate, default thresholds, weight defaults, resource limit defaults.

```python
# Source: core/config.py — follows existing field pattern exactly

@dataclass(frozen=True)
class Settings:
    # ... existing fields ...

    # Performance-based rewards (Phase rewards)
    rewards_enabled: bool = False
    rewards_silver_threshold: float = 0.65
    rewards_gold_threshold: float = 0.85
    rewards_min_observations: int = 10
    rewards_weight_success: float = 0.60
    rewards_weight_volume: float = 0.25
    rewards_weight_speed: float = 0.15
    # Per-tier resource limits (used by Phase 3)
    rewards_bronze_rate_limit_multiplier: float = 1.0
    rewards_silver_rate_limit_multiplier: float = 1.5
    rewards_gold_rate_limit_multiplier: float = 2.0
    rewards_bronze_max_concurrent: int = 2
    rewards_silver_max_concurrent: int = 5
    rewards_gold_max_concurrent: int = 10

# In from_env():
    rewards_enabled=os.getenv("REWARDS_ENABLED", "false").lower() in ("true", "1", "yes"),
    rewards_silver_threshold=float(os.getenv("REWARDS_SILVER_THRESHOLD", "0.65")),
    rewards_gold_threshold=float(os.getenv("REWARDS_GOLD_THRESHOLD", "0.85")),
    rewards_min_observations=int(os.getenv("REWARDS_MIN_OBSERVATIONS", "10")),
    rewards_weight_success=float(os.getenv("REWARDS_WEIGHT_SUCCESS", "0.60")),
    rewards_weight_volume=float(os.getenv("REWARDS_WEIGHT_VOLUME", "0.25")),
    rewards_weight_speed=float(os.getenv("REWARDS_WEIGHT_SPEED", "0.15")),
    rewards_bronze_rate_limit_multiplier=float(os.getenv("REWARDS_BRONZE_RATE_LIMIT_MULTIPLIER", "1.0")),
    rewards_silver_rate_limit_multiplier=float(os.getenv("REWARDS_SILVER_RATE_LIMIT_MULTIPLIER", "1.5")),
    rewards_gold_rate_limit_multiplier=float(os.getenv("REWARDS_GOLD_RATE_LIMIT_MULTIPLIER", "2.0")),
    rewards_bronze_max_concurrent=int(os.getenv("REWARDS_BRONZE_MAX_CONCURRENT", "2")),
    rewards_silver_max_concurrent=int(os.getenv("REWARDS_SILVER_MAX_CONCURRENT", "5")),
    rewards_gold_max_concurrent=int(os.getenv("REWARDS_GOLD_MAX_CONCURRENT", "10")),
```

### Pattern 2: RewardsConfig (Mutable File-Backed Config)

**What:** Non-frozen dataclass backed by `.agent42/rewards_config.json`. Handles runtime toggle and threshold overrides without restart. Direct copy of `AgentRoutingStore` pattern.
**When to use:** Any config that must change at runtime via dashboard without requiring `systemctl restart agent42`.

```python
# Source: agents/agent_routing_store.py — copy this pattern exactly

@dataclass
class RewardsConfig:
    """Mutable runtime config for the rewards system.

    Backed by .agent42/rewards_config.json.
    Settings.rewards_enabled is the startup gate (frozen).
    This handles the runtime on/off toggle and threshold overrides.
    """
    enabled: bool = True          # Runtime toggle (separate from startup gate)
    silver_threshold: float = 0.65
    gold_threshold: float = 0.85

    _path: ClassVar[str] = ".agent42/rewards_config.json"
    _cache: ClassVar[dict | None] = None
    _cache_mtime: ClassVar[float] = 0.0

    @classmethod
    def load(cls) -> "RewardsConfig":
        """Lazy mtime-cached load — re-reads file only when mtime changes."""
        path = Path(cls._path)
        if not path.exists():
            return cls()
        try:
            mtime = path.stat().st_mtime
            if mtime != cls._cache_mtime or cls._cache is None:
                data = json.loads(path.read_text(encoding="utf-8"))
                cls._cache = data
                cls._cache_mtime = mtime
            return cls(**cls._cache)
        except Exception:
            return cls()

    def save(self) -> None:
        """Atomic write via os.replace()."""
        path = Path(self._path)
        path.parent.mkdir(parents=True, exist_ok=True)
        data = {"enabled": self.enabled, "silver_threshold": self.silver_threshold,
                "gold_threshold": self.gold_threshold}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(path))
        # Invalidate cache
        type(self)._cache = data
        type(self)._cache_mtime = path.stat().st_mtime
```

### Pattern 3: EffectivenessStore Schema Migration (ALTER TABLE)

**What:** Add `agent_id TEXT DEFAULT ''` column to existing `tool_invocations` table via SQLite `ALTER TABLE` in `_ensure_db()`. SQLite supports adding a column with a DEFAULT — existing rows automatically get the default value `''`.
**When to use:** Any schema evolution where backward compatibility with existing rows is required.

```python
# Source: memory/effectiveness.py _ensure_db() — add after existing CREATE TABLE/INDEX

async def _ensure_db(self) -> None:
    if self._db_initialized:
        return
    self._db_path.parent.mkdir(parents=True, exist_ok=True)
    async with aiosqlite.connect(self._db_path) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS tool_invocations (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tool_name   TEXT    NOT NULL,
                task_type   TEXT    NOT NULL,
                task_id     TEXT    NOT NULL,
                success     INTEGER NOT NULL,
                duration_ms REAL    NOT NULL,
                ts          REAL    NOT NULL
            )
        """)
        # Migration: add agent_id if not present (idempotent)
        try:
            await db.execute(
                "ALTER TABLE tool_invocations ADD COLUMN agent_id TEXT DEFAULT ''"
            )
        except Exception:
            pass  # Column already exists — SQLite raises OperationalError, ignore it
        await db.execute(
            "CREATE INDEX IF NOT EXISTS idx_agent_id ON tool_invocations (agent_id)"
        )
        # existing indexes ...
        await db.commit()
    self._db_initialized = True
```

**Critical note:** SQLite `ALTER TABLE ADD COLUMN` is idempotent-safe only with `try/except` because SQLite does not support `ADD COLUMN IF NOT EXISTS`. The `except` block must be a bare `pass` — it only catches "duplicate column" which is benign.

### Pattern 4: get_agent_stats() Method

**What:** Per-agent aggregation query reusing the existing `get_aggregated_stats()` structure with a `WHERE agent_id = ?` filter.

```python
# Source: memory/effectiveness.py — follows get_aggregated_stats() exactly

async def get_agent_stats(self, agent_id: str) -> dict | None:
    """Return success_rate, task_volume, avg_speed for a specific agent.

    Returns None if agent has no recorded data or if store is unavailable.
    Agents with fewer records than min_observations should be treated as
    Provisional by the caller — this method returns raw counts.
    """
    if not AIOSQLITE_AVAILABLE or not agent_id:
        return None
    try:
        await self._ensure_db()
        query = """
            SELECT
                COUNT(*)                   AS task_volume,
                AVG(CAST(success AS REAL)) AS success_rate,
                AVG(duration_ms)           AS avg_speed
            FROM tool_invocations
            WHERE agent_id = ?
        """
        async with aiosqlite.connect(self._db_path) as db:
            db.row_factory = aiosqlite.Row
            async with db.execute(query, (agent_id,)) as cursor:
                row = await cursor.fetchone()
        if row is None or dict(row)["task_volume"] == 0:
            return None
        return dict(row)
    except Exception as e:
        logger.warning("EffectivenessStore agent stats query failed: %s", e)
        return None
```

### Pattern 5: TTL Cache (time.monotonic())

**What:** Plain dict keyed by `agent_id` storing `(tier_value, expires_at)` tuples. TTL checked on every get. Same structure as `ToolRateLimiter._calls`.
**When to use:** Any in-memory cache that must survive the life of the process but expire stale entries.

```python
# Source: core/rate_limiter.py — direct pattern transfer

import time

class TierCache:
    """In-memory TTL cache for computed tier assignments.

    Never queried from the routing hot path — populated by background
    recalculation (Phase 2) and read by AgentConfig.effective_tier() (Phase 2).
    Phase 1 only implements the cache structure and persistence.
    """
    DEFAULT_TTL_SECONDS = 900  # 15 minutes

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS):
        self._ttl = ttl_seconds
        self._cache: dict[str, tuple[str, float]] = {}  # agent_id -> (tier, expires_at)

    def get(self, agent_id: str) -> str | None:
        """Return cached tier or None if missing/expired."""
        entry = self._cache.get(agent_id)
        if entry is None:
            return None
        tier, expires_at = entry
        if time.monotonic() > expires_at:
            del self._cache[agent_id]
            return None
        return tier

    def set(self, agent_id: str, tier: str) -> None:
        """Cache a tier assignment with TTL."""
        self._cache[agent_id] = (tier, time.monotonic() + self._ttl)

    def warm_from_dict(self, data: dict[str, dict]) -> None:
        """Populate cache from persisted JSON on startup.

        data format: {agent_id: {"tier": "gold", "score": 0.87, "calculated_at": 1234567.0}}
        Entries are warmed with a full TTL from now (not from calculated_at)
        so they are valid until the first background recalculation.
        """
        for agent_id, entry in data.items():
            tier = entry.get("tier", "provisional")
            self._cache[agent_id] = (tier, time.monotonic() + self._ttl)

    def to_dict(self) -> dict[str, dict]:
        """Serialize current cache to JSON-serializable dict for persistence."""
        now = time.monotonic()
        return {
            agent_id: {"tier": tier, "expires_in_seconds": max(0.0, expires_at - now)}
            for agent_id, (tier, expires_at) in self._cache.items()
            if expires_at > now
        }
```

### Pattern 6: Composite Score Calculation

**What:** Pure function — no DB access, no async. Takes raw stats dict from `get_agent_stats()`, fleet-level max values for normalization, and weight config. Returns a float 0.0–1.0.
**When to use:** Score computation must be synchronous, deterministic, and testable without infrastructure.

```python
# Source: Research D-09/D-10 — min-max normalization (Claude's discretion: prefer min-max
# over z-score because fleet maxima are meaningful upper bounds, not statistical artifacts)

def compute_score(
    stats: dict,
    fleet_max_volume: int,
    fleet_max_speed_ms: float,
    weight_success: float = 0.60,
    weight_volume: float = 0.25,
    weight_speed: float = 0.15,
) -> float:
    """Compute composite performance score in range [0.0, 1.0].

    Args:
        stats: dict with keys task_volume, success_rate, avg_speed (from get_agent_stats)
        fleet_max_volume: highest task_volume across all agents (for normalization)
        fleet_max_speed_ms: highest avg_speed across all agents (worst speed, for normalization)
        weight_*: configurable weights that must sum to 1.0

    Returns:
        float in [0.0, 1.0]. Returns 0.0 if stats is empty or fleet_max is zero.
    """
    if not stats or fleet_max_volume == 0:
        return 0.0

    success_rate = float(stats.get("success_rate") or 0.0)
    volume = int(stats.get("task_volume") or 0)
    avg_speed_ms = float(stats.get("avg_speed") or 0.0)

    # Min-max normalization relative to fleet max
    volume_normalized = volume / fleet_max_volume if fleet_max_volume > 0 else 0.0
    # Speed: lower ms = better; invert so 1.0 = fastest, 0.0 = slowest
    speed_normalized = (
        1.0 - (avg_speed_ms / fleet_max_speed_ms)
        if fleet_max_speed_ms > 0 and avg_speed_ms > 0
        else 0.5  # Default to neutral when no speed data
    )

    return (
        success_rate * weight_success
        + volume_normalized * weight_volume
        + speed_normalized * weight_speed
    )
```

### Pattern 7: ToolRegistry agent_id Threading

**What:** The `agent_id` parameter is already on `ToolRegistry.execute()` (line 87) for rate limiting. Thread it into the `effectiveness_store.record()` call at lines 131-138.
**When to use:** This is a one-line change at a single call site.

```python
# Source: tools/registry.py lines 127-141 — current code (record() lacks agent_id)

# CURRENT (line 131-138):
asyncio.create_task(
    self._effectiveness_store.record(
        tool_name=tool_name,
        task_type=task_type or "general",
        task_id=task_id or "",
        success=result.success,
        duration_ms=duration_ms,
    )
)

# AFTER CHANGE (add agent_id= parameter):
asyncio.create_task(
    self._effectiveness_store.record(
        tool_name=tool_name,
        task_type=task_type or "general",
        task_id=task_id or "",
        agent_id=agent_id,          # <-- add this line
        success=result.success,
        duration_ms=duration_ms,
    )
)
```

### Anti-Patterns to Avoid

- **Querying per-agent stats on the routing hot path:** Never call `get_agent_stats()` inside `ToolRegistry.execute()` or model routing. Score is background-computed and cached.
- **Mutating `settings.rewards_enabled` at runtime:** It's a frozen dataclass. `FrozenInstanceError` in production. Use `RewardsConfig.enabled` for the runtime toggle.
- **`ALTER TABLE ADD COLUMN` without try/except:** SQLite will raise `OperationalError` if the column already exists (when the DB was created before this migration). Always wrap in try/except.
- **Opening a new aiosqlite connection per stat read:** Follow the existing `EffectivenessStore` pattern — one `async with aiosqlite.connect()` per method call, no connection pooling needed at this scale.
- **Storing `time.time()` in TTL cache:** Use `time.monotonic()` for TTL calculation (wall-clock monotonic). `time.time()` can go backwards (NTP adjustments) and would corrupt TTL arithmetic.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Atomic file write | Custom file write with rename logic | `os.replace(tmp_path, target_path)` | Atomic on all POSIX; already used in AgentRoutingStore |
| Mtime-based cache invalidation | Custom file watcher | `path.stat().st_mtime` comparison | Direct stdlib; already pattern in AgentRoutingStore._load() |
| SQLite migration versioning | Migration table with version numbers | `ALTER TABLE ADD COLUMN` with try/except | Sufficient for single-column addition; no migration framework needed |
| Score normalization library | Custom z-score or sigmoid implementation | Min-max with fleet max as reference | Simpler, interpretable, already justified by research |

**Key insight:** Every pattern in this phase has an existing implementation in the codebase within 100 lines. The planner should reference the canonical file, not invent new patterns.

---

## Common Pitfalls

### Pitfall 1: ALTER TABLE Fails on Existing Database

**What goes wrong:** `_ensure_db()` runs `ALTER TABLE tool_invocations ADD COLUMN agent_id TEXT DEFAULT ''` — if the DB already exists and the column was added in a previous startup, SQLite raises `OperationalError: duplicate column name: agent_id`.
**Why it happens:** SQLite does not support `ADD COLUMN IF NOT EXISTS`. The `_db_initialized` flag only prevents the full `_ensure_db()` from re-running within a single process lifetime, not across restarts.
**How to avoid:** Wrap the `ALTER TABLE` statement in `try/except Exception: pass`. The except block is intentionally silent — a duplicate column error is benign and expected on all runs after the first.
**Warning signs:** `OperationalError` in logs containing "duplicate column name" on startup.

### Pitfall 2: RewardsConfig._cache Is a Class Variable — Shared Across Instances

**What goes wrong:** If `RewardsConfig` is implemented with class-level `_cache` and `_cache_mtime` (to simulate a singleton file reader, as in AgentRoutingStore), and two test instances are created in the same test session, the cache from the first test's file path poisons the second test's state.
**Why it happens:** Class variables are shared across all instances. `AgentRoutingStore` is used as a singleton in production, so this doesn't surface there.
**How to avoid:** In `RewardsConfig`, use instance variables for `_cache` and `_cache_mtime`, not class variables. Or make the class a singleton (only one instance in the process). Instance variables are cleaner for testability.

### Pitfall 3: TTL Cache Warm Does Not Respect Original TTL

**What goes wrong:** `warm_from_dict()` sets `expires_at = time.monotonic() + self._ttl` (a fresh full TTL from "now"). This means a tier cached 14 minutes ago gets another full 15-minute TTL after restart — effectively a 29-minute window without recalculation.
**Why it happens:** The persisted JSON doesn't track when the tier was calculated relative to monotonic time (monotonic is not meaningful across process restarts).
**How to avoid:** This is acceptable behavior for Phase 1 — the cache is a warm-start optimization, and 29 minutes without recalculation is not a problem when Phase 2 adds a background recalculation loop. Document the behavior explicitly. Persist `calculated_at` as an ISO timestamp and use it in Phase 2 to detect stale entries at warmup.

### Pitfall 4: Graceful Degradation When EffectivenessStore Is Unavailable

**What goes wrong:** `get_agent_stats()` must return `None` (not raise) when aiosqlite is unavailable or the DB is unwritable. The `RewardSystem.compute_score()` must treat `None` stats as "no data" and return `0.0` without crashing. If this guard is missing, `REWARDS_ENABLED=true` crashes the server when aiosqlite is not installed.
**Why it happens:** The existing `EffectivenessStore.record()` has a `try/except` guard but new methods need the same treatment.
**How to avoid:** Mirror the existing `if not AIOSQLITE_AVAILABLE: return None` guard at the top of every new EffectivenessStore method. Test this explicitly with `test_rewards_disabled_when_store_unavailable`.

### Pitfall 5: Weight Validation Not Enforced

**What goes wrong:** `REWARDS_WEIGHT_SUCCESS=0.90 REWARDS_WEIGHT_VOLUME=0.90 REWARDS_WEIGHT_SPEED=0.90` produces scores that can exceed 1.0 (2.7 max). The tier thresholds are defined for [0.0, 1.0] range. Scores > 1.0 would incorrectly map to thresholds.
**Why it happens:** env vars are parsed independently; no cross-field validation in frozen dataclass `from_env()`.
**How to avoid:** In `ScoreCalculator.__init__()` or `compute_score()`, normalize the weights if their sum != 1.0 (divide each by the sum). Log a warning if normalization occurs. This prevents score-range bugs without requiring env var validation.

---

## Code Examples

Verified patterns from codebase inspection:

### AgentRoutingStore Atomic Write (model for RewardsConfig._save)
```python
# Source: agents/agent_routing_store.py lines 64-75
def _save(self, data: dict) -> None:
    self._path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = self._path.with_suffix(".tmp")
    tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    os.replace(str(tmp_path), str(self._path))
    self._cache = data
    self._cache_mtime = self._path.stat().st_mtime
```

### AgentRoutingStore mtime-based lazy load (model for RewardsConfig.load)
```python
# Source: agents/agent_routing_store.py lines 43-62
def _load(self) -> dict:
    if not self._path.exists():
        self._cache = {}
        return self._cache
    try:
        mtime = self._path.stat().st_mtime
        if mtime != self._cache_mtime or self._cache is None:
            self._cache = json.loads(self._path.read_text(encoding="utf-8"))
            self._cache_mtime = mtime
    except Exception as e:
        logger.debug("Failed to read file: %s", e)
        if self._cache is None:
            self._cache = {}
    return self._cache
```

### ToolRateLimiter TTL pattern (model for TierCache)
```python
# Source: core/rate_limiter.py lines 58-64, 78-81
now = time.monotonic()
cutoff = now - limit.window_seconds
timestamps = self._calls[key]
self._calls[key] = [t for t in timestamps if t > cutoff]
# ...
def record(self, tool_name: str, agent_id: str = "default"):
    key = f"{agent_id}:{tool_name}"
    self._calls[key].append(time.monotonic())
```

### EffectivenessStore graceful degradation guard
```python
# Source: memory/effectiveness.py lines 86-88, 116-118
if not AIOSQLITE_AVAILABLE:
    return  # or return []
try:
    await self._ensure_db()
    # ... query ...
except Exception as e:
    logger.warning("EffectivenessStore ... failed: %s", e)
    return []  # Never raises
```

### EffectivenessStore get_aggregated_stats query structure (model for get_agent_stats)
```python
# Source: memory/effectiveness.py lines 119-139
query = """
    SELECT
        tool_name,
        task_type,
        COUNT(*)                   AS invocations,
        AVG(CAST(success AS REAL)) AS success_rate,
        AVG(duration_ms)           AS avg_duration_ms
    FROM tool_invocations
    WHERE (? = '' OR tool_name = ?)
      AND (? = '' OR task_type = ?)
    GROUP BY tool_name, task_type
    ORDER BY invocations DESC
"""
```

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_reward_system.py tests/test_effectiveness.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

Baseline confirmed: `tests/test_effectiveness.py` — 20 passed in 1.21s (2026-03-22).

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONF-01 | `REWARDS_ENABLED=false` → zero behavioral change | unit | `pytest tests/test_reward_system.py::TestGracefulDegradation -x` | Wave 0 |
| CONF-02 | Silver/Gold thresholds read from env vars | unit | `pytest tests/test_reward_system.py::TestSettings -x` | Wave 0 |
| CONF-03 | Per-tier resource limits read from env vars | unit | `pytest tests/test_reward_system.py::TestSettings -x` | Wave 0 |
| CONF-04 | Score weights read from env vars | unit | `pytest tests/test_reward_system.py::TestScoreCalculator -x` | Wave 0 |
| CONF-05 | RewardsConfig saves/loads without restart | unit | `pytest tests/test_reward_system.py::TestRewardsConfig -x` | Wave 0 |
| DATA-01 | EffectivenessStore.record() writes agent_id | unit | `pytest tests/test_effectiveness.py::TestEffectivenessStore::test_record_includes_agent_id -x` | Extend existing |
| DATA-02 | get_agent_stats(agent_id) returns correct stats | unit | `pytest tests/test_effectiveness.py::TestAgentStats -x` | Wave 0 |
| TIER-01 | compute_score() returns correct weighted value | unit | `pytest tests/test_reward_system.py::TestScoreCalculator -x` | Wave 0 |
| TIER-04 | TierCache.get() returns None after TTL expiry | unit | `pytest tests/test_reward_system.py::TestTierCache -x` | Wave 0 |
| TIER-05 | TierCache.warm_from_dict() / to_dict() roundtrip | unit | `pytest tests/test_reward_system.py::TestTierCache::test_persistence_roundtrip -x` | Wave 0 |
| TEST-01 | Score edge cases: zero data, all success, weights sum != 1 | unit | `pytest tests/test_reward_system.py::TestScoreCalculator -x` | Wave 0 |
| TEST-05 | Graceful degradation: disabled rewards, unavailable store | unit | `pytest tests/test_reward_system.py::TestGracefulDegradation -x` | Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_reward_system.py tests/test_effectiveness.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_reward_system.py` — covers CONF-01 through TIER-05, TEST-01, TEST-05
- No new fixtures needed — `tmp_path` (builtin) sufficient for file-backed config tests

---

## Environment Availability

Step 2.6: SKIPPED (no external dependencies — all changes are Python stdlib, existing aiosqlite, and local file I/O within the project workspace).

---

## Project Constraints (from CLAUDE.md)

These directives constrain the planner. All plans must comply.

| Constraint | Implication for Phase 1 |
|------------|------------------------|
| All I/O is async | `get_agent_stats()` must be `async def`; `RewardsConfig.load()` uses synchronous file reads (same as AgentRoutingStore — file reads are synchronous by project convention) |
| Frozen dataclass `Settings` | Add fields to frozen dataclass with defaults; parse in `from_env()` — never mutate `settings` at runtime |
| Graceful degradation | `RewardSystem` must not crash if `EffectivenessStore` is unavailable; zero behavior change when `REWARDS_ENABLED=false` |
| aiofiles for file operations | RewardsConfig uses synchronous `Path.read_text()` / `os.replace()` — this is explicitly consistent with `AgentRoutingStore` which also uses synchronous file I/O for its config file. Config files are tiny and read infrequently; async overhead is not warranted |
| pytest-asyncio, asyncio_mode=auto | All async tests use `@pytest.mark.asyncio` or rely on auto mode; no manual `asyncio.run()` in tests |
| tmp_path fixture for filesystem tests | All `RewardsConfig` and `TierCache` tests use `tmp_path`, not hardcoded paths |
| Every new module needs a test file | `core/reward_system.py` requires `tests/test_reward_system.py` |
| Never blocking I/O | `get_agent_stats()` uses `async with aiosqlite.connect()` — not `sqlite3` |
| NEVER log API keys or tokens | Score values, agent_ids, and tier assignments are safe to log; no secret data in rewards module |
| Document fixes in CLAUDE.md pitfalls | If ALTER TABLE migration edge case is discovered during implementation, add to pitfalls table |

---

## Open Questions

1. **Weight normalization behavior when env vars don't sum to 1.0**
   - What we know: D-09 sets default weights 0.60/0.25/0.15 which sum to 1.0. Env vars can be set to anything.
   - What's unclear: Should non-1.0 weights silently normalize, warn-and-normalize, or raise?
   - Recommendation: Warn-and-normalize (log at WARNING level, proceed) — never raise for a misconfiguration that has a reasonable recovery. This keeps the "graceful degradation" pattern consistent.

2. **Fleet maximum computation for volume/speed normalization**
   - What we know: D-10 specifies min-max normalization relative to fleet maximum. `get_agent_stats()` returns per-agent data, not fleet-wide maxima.
   - What's unclear: A separate "get fleet stats" query is needed to compute the denominators for normalization. This query is not spec'd in the decisions.
   - Recommendation: Add `get_fleet_stats()` to `EffectivenessStore` that returns `MAX(volume)` and `MAX(avg_speed)` across all agents. Alternatively, `RewardSystem.compute_scores_for_all_agents()` fetches all agent stats in one query and computes maxima in Python. The latter avoids an extra round-trip and is simpler.

3. **RewardsConfig thresholds vs Settings thresholds — which wins?**
   - What we know: `Settings` has `rewards_silver_threshold=0.65` (startup defaults). `RewardsConfig` also has `silver_threshold=0.65` (runtime overrides). Both exist.
   - What's unclear: When `RewardsConfig.json` has a different threshold than Settings defaults, which takes precedence?
   - Recommendation: `RewardsConfig` runtime values always win over `Settings` defaults when `RewardsConfig` file exists. `Settings` values serve as the initial defaults when no `rewards_config.json` file has been created yet. Document this clearly in the module docstring.

---

## Sources

### Primary (HIGH confidence)

- `memory/effectiveness.py` — EffectivenessStore class, `_ensure_db()`, `record()`, `get_aggregated_stats()` — direct codebase inspection
- `agents/agent_routing_store.py` — AgentRoutingStore mtime pattern, atomic write — direct codebase inspection
- `core/rate_limiter.py` — ToolRateLimiter TTL pattern, `time.monotonic()` usage — direct codebase inspection
- `core/config.py` — Settings frozen dataclass, `from_env()` pattern — direct codebase inspection
- `tools/registry.py` — `ToolRegistry.execute()` agent_id threading point at lines 87, 131-138 — direct codebase inspection
- `tests/test_effectiveness.py` — existing test patterns, conftest fixtures — direct codebase inspection
- `.planning/workstreams/performance-based-rewards/research/SUMMARY.md` — prior phase research synthesis
- `.planning/workstreams/performance-based-rewards/research/PITFALLS.md` — pitfalls 1-3 directly relevant to Phase 1

### Secondary (MEDIUM confidence)

- `.planning/workstreams/performance-based-rewards/phases/01-foundation/01-CONTEXT.md` — locked decisions D-01 through D-11
- Python 3.11 stdlib docs — `time.monotonic()`, `dataclasses`, `os.replace()`, SQLite ALTER TABLE behavior

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all patterns verified from direct codebase inspection; zero new dependencies
- Architecture: HIGH — all patterns are direct copies of existing implementations; no new patterns introduced
- Pitfalls: HIGH — pitfalls 1, 3, 5, 7, 10 from PITFALLS.md directly map to Phase 1 scope and are verified from code inspection
- Open questions: MEDIUM — questions 2 and 3 are implementation details resolvable during plan writing; question 1 is a judgment call with a clear recommendation

**Research date:** 2026-03-22
**Valid until:** 2026-04-22 (30 days — stable Python stdlib patterns, no fast-moving dependencies)

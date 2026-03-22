# Feature Research: Performance-Based Rewards System

**Domain:** Performance-based tier/rewards system for an AI agent platform
**Researched:** 2026-03-22
**Confidence:** HIGH

---

## Feature Landscape

### Table Stakes (Users Expect These)

These features define the minimum viable rewards system. Without them the feature feels
like a configuration knob, not a rewards system.

| Feature | Why Expected | Complexity | Notes |
| ------- | ------------ | ---------- | ----- |
| Three named tiers (Bronze/Silver/Gold) | Industry-standard naming; users instantly understand the hierarchy | LOW | Fixed names reduce cognitive load vs. configurable names |
| Performance score calculation | Without a score, tier assignment is opaque — users can't understand or trust it | MEDIUM | Must derive from existing effectiveness data (success_rate, duration_ms, invocations per `EffectivenessStore`) |
| Automatic tier assignment | Manual assignment by admin for every agent defeats the purpose | MEDIUM | Runs on a schedule or lazily on access; must be cached |
| Resource differentiation per tier | If all tiers get the same resources, tiers are cosmetic only | MEDIUM | Model access, rate limits, concurrent task capacity |
| Admin tier override | Operators need to correct misclassified agents (new agents with no data, exceptional cases) | LOW | Manual override that bypasses automatic scoring; stored on AgentConfig |
| Tier visibility in dashboard | Users must always know their agent's current tier and score | LOW | Badge/label on agent card; dedicated metrics section |
| REWARDS_ENABLED=false default | Zero-impact on existing deployments without opt-in | LOW | Required constraint from PROJECT.md; flag in `Settings` frozen dataclass |
| Graceful degradation when disabled | When REWARDS_ENABLED=false, agents get default resources — never errors | LOW | Code paths fall through to baseline limits; no crashes |
| Tier persistence | Tier must survive server restarts — not recomputed on every request | LOW | Stored on AgentConfig JSON; recalculated on schedule, not per-request |
| Minimum data threshold | Agents with fewer than N task records should not be penalized — hold at Bronze | LOW | Configurable minimum; prevents new agents being locked out |

### Differentiators (Competitive Advantage)

Features that make the rewards system feel like a quality loop, not just access control.

| Feature | Value Proposition | Complexity | Notes |
| ------- | ----------------- | ---------- | ----- |
| Composite score with multiple weighted dimensions | Success rate alone is gamed by easy tasks; weighting by task volume + duration reflects real contribution | MEDIUM | Recommended weights: success_rate (60%), task_volume_normalized (25%), avg_speed_normalized (15%) |
| Hysteresis on tier transitions | Prevents thrashing when an agent hovers near a threshold — needs sustained performance to promote, one bad stretch doesn't immediately demote | MEDIUM | Promotion requires N consecutive periods above threshold; demotion has a grace window |
| Score trend direction | Showing "+12 pts this week" is more motivating than showing a static score — operators take action on trend, not number | MEDIUM | Requires storing score snapshots over time (weekly) |
| Per-tier model routing integration | Gold agents get L1 workhorse (StrongWall/Synthetic), Silver get reliable premium, Bronze get free-tier fallback — creates a measurable quality loop | HIGH | Must hook into existing model routing in agent_manager.py; requires `resolve_model()` to accept tier context |
| Tier promotion/demotion audit log | Admins need to understand why an agent changed tier — essential for trust | MEDIUM | Append-only log with timestamp, previous tier, new tier, triggering score |
| Cooldown period after promotion | Prevents yo-yo between tiers due to task clustering; ensures new tier reflects sustained behavior | LOW | Configurable `REWARDS_PROMOTION_COOLDOWN_DAYS` (default: 7 days) |
| Bulk tier recalculation endpoint | When thresholds are changed, admins want to recompute all agents at once rather than waiting for the schedule | LOW | Admin API endpoint; runs in background |
| Score explanation per agent | Shows breakdown: "success_rate: 0.87 (weight 60%) + volume: 0.7 (weight 25%) + speed: 0.6 (weight 15%) = 0.80 -> Gold" | MEDIUM | Returned by tier service; displayed in dashboard agent detail panel |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
| ------- | ------------- | --------------- | ----------- |
| Fully configurable tier names | "Our team uses Iron/Steel/Diamond" | Adds UI/config complexity with no behavioral benefit; names don't affect resource allocation | Use fixed Bronze/Silver/Gold; document the thresholds as configurable |
| Points accumulation (XP system) | Gamification research shows points feel rewarding | Points detach from actual performance — an agent could accumulate points running trivial tasks; creates perverse incentive | Use rolling success rate over recent N tasks — recency-weighted, not cumulative |
| Real-time tier recalculation on every task | "Always current" appeals | Per-request computation breaks the "cached/fast" constraint from PROJECT.md; creates latency spikes | Schedule recalculation (e.g., every 15 minutes or on-demand) with cached tier stored on AgentConfig |
| Automatic tier demotion below Bronze | "Penalize underperformers" | Below Bronze there is nowhere to go — agents would just get disabled, which is a separate concern | Keep Bronze as the floor; let admins manually pause agents that consistently underperform |
| Cross-agent leaderboard / competitive ranking | "Motivates better agents" | Agents serve different task types at different complexities — ranking Devops (5 iterations, fast) vs. Research (25 iterations, slow) is meaningless | Per-tier grouping only; no cross-agent score ranking |
| Tier-gated tool access (some tools Bronze-only) | "Reserve premium tools for top performers" | Tool access is a security boundary, not a performance reward; mixing the two creates unpredictable behavior | Keep tool access in skills/tool config; only resource limits (models, rate limits, concurrency) vary by tier |
| Retroactive scoring from pre-rewards data | "All historical task data should count" | Pre-rewards data has no tier context; mixing unlabeled historical data distorts baselines | Score only from data collected after REWARDS_ENABLED=true; use minimum threshold to handle cold start |
| Negative score for failures | "Failures should hurt more than successes help" | Creates over-cautious agents that avoid complex tasks to protect their tier | Use success_rate (fraction) not signed delta accumulation — success rate already penalizes failures proportionally |

---

## Feature Dependencies

```text
REWARDS_ENABLED flag (Settings)
    └──enables──> PerformanceScoreCalculator
                      └──reads──> EffectivenessStore (already exists)
                          └──produces──> composite_score
                              └──feeds──> TierDeterminator
                                  └──writes──> AgentConfig.reward_tier (new field)
                                      ├──read by──> ResourceAllocator
                                      │                 └──applied in──> AgentManager task dispatch
                                      │                 └──applied in──> ModelRouting (resolve_model)
                                      │                 └──applied in──> ToolRateLimiter (per-tier limits)
                                      └──read by──> Dashboard tier display
                                      └──read by──> Admin override endpoint

Admin override
    └──writes──> AgentConfig.reward_tier_override (new field)
        └──bypasses──> TierDeterminator output
            └──still subject to──> ResourceAllocator (override tier controls resources)

Hysteresis / cooldown
    └──requires──> AgentConfig.tier_promoted_at (timestamp, new field)
    └──requires──> AgentConfig.tier_score_history (list[float], new field)

Audit log
    └──appended by──> TierDeterminator on every tier change
    └──readable by──> Dashboard audit section
```

### Dependency Notes

- **PerformanceScoreCalculator requires EffectivenessStore:** The score must come from
  existing data — no new collection. EffectivenessStore provides `get_aggregated_stats()`
  and `get_task_records()` today; calculator reads these and derives a per-agent composite score.

- **TierDeterminator requires PerformanceScoreCalculator:** Tier is always a function of
  score — never assigned directly by the algorithm (admin override is a separate code path
  that routes around the determinator).

- **ResourceAllocator requires TierDeterminator output:** Allocator is the single point
  where tier maps to concrete limits. Everything downstream (model routing, rate limiter,
  concurrency cap) reads from the allocator, not from the raw tier string.

- **Dashboard display requires ResourceAllocator:** Display should show effective limits
  (what the agent actually gets) not raw tier label — users understand "Gold: GPT-oss-120b,
  10 concurrent tasks" better than "Gold tier."

- **Admin override conflicts with TierDeterminator:** Override must clearly signal that
  the tier was set manually — otherwise ops can't tell if a Gold agent earned it or was
  manually elevated. Store `reward_tier_override` separately from `reward_tier`.

- **Hysteresis requires score history:** Can't compute "N consecutive periods above threshold"
  without storing N prior scores. Keep history shallow (last 4 periods) to bound storage.

---

## MVP Definition

### Launch With (v1.4)

Minimum viable system that delivers the self-reinforcing quality loop described in PROJECT.md.

- [ ] `REWARDS_ENABLED` flag in `Settings` (frozen dataclass, `os.getenv`, default `false`) — controls all behavior
- [ ] `PerformanceScoreCalculator` — derives composite score from EffectivenessStore data (success_rate, task volume, avg duration per agent_id/task_type)
- [ ] `TierDeterminator` — maps composite score to Bronze/Silver/Gold with configurable thresholds; respects minimum data threshold (default: 10 tasks)
- [ ] `AgentConfig` new fields: `reward_tier`, `reward_tier_override`, `tier_promoted_at`
- [ ] `ResourceAllocator` — per-tier lookup table for model routing class, rate limit multiplier, max concurrent tasks
- [ ] `AgentManager` integration — apply resource limits from allocator at task dispatch
- [ ] Model routing integration — `resolve_model()` accepts tier context and selects model class accordingly
- [ ] Admin override API endpoint — `PATCH /api/agents/{id}/reward-tier` with tier value or `null` to clear
- [ ] Dashboard tier badge on agent cards (Bronze/Silver/Gold or "unranked")
- [ ] Dashboard performance metrics panel per agent (score, tier, task count, success rate)
- [ ] Tier recalculation scheduled task (every 15 minutes, configurable)
- [ ] Tier cache — stored on AgentConfig, never computed per-request
- [ ] Full unit + integration tests

### Add After Validation (v1.4.x)

Features to add once the core loop is proven to work.

- [ ] Hysteresis / cooldown — add `tier_score_history` to AgentConfig; require N periods sustained above threshold for promotion — reduces operational noise
- [ ] Tier change audit log — append-only log stored per agent; surfaced in dashboard
- [ ] Score explanation endpoint — `GET /api/agents/{id}/reward-score` returns full dimension breakdown
- [ ] Bulk recalculation admin endpoint — `POST /api/admin/rewards/recalculate-all`

### Future Consideration (v2+)

Features to defer until the base system is running in production.

- [ ] Score trend visualization — weekly score delta charts in dashboard; needs at least 4 weeks of history data first
- [ ] Per-task-type tier specialization — agent could be Gold for "coding" but Silver for "research"; adds significant complexity, value unclear until base system is in use
- [ ] Email/webhook notifications on tier change — useful for fleet operators managing many agents; not needed for single-user deployment
- [ ] Tier analytics across the full agent fleet — fleet-level dashboards for identifying systemic quality issues

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
| ------- | ---------- | ------------------- | -------- |
| REWARDS_ENABLED flag + graceful degradation | HIGH | LOW | P1 |
| PerformanceScoreCalculator (from existing data) | HIGH | MEDIUM | P1 |
| TierDeterminator with thresholds | HIGH | LOW | P1 |
| ResourceAllocator (model + rate + concurrency) | HIGH | MEDIUM | P1 |
| AgentManager integration (dispatch) | HIGH | MEDIUM | P1 |
| Model routing integration | HIGH | MEDIUM | P1 |
| Admin tier override | HIGH | LOW | P1 |
| Dashboard tier badge + metrics panel | MEDIUM | LOW | P1 |
| Scheduled recalculation + cache | HIGH | LOW | P1 |
| Hysteresis / cooldown | MEDIUM | MEDIUM | P2 |
| Tier change audit log | MEDIUM | LOW | P2 |
| Score explanation breakdown | MEDIUM | LOW | P2 |
| Bulk recalculation endpoint | LOW | LOW | P2 |
| Score trend visualization | LOW | HIGH | P3 |
| Per-task-type tier specialization | LOW | HIGH | P3 |
| Fleet-level tier analytics | LOW | HIGH | P3 |

**Priority key:**

- P1: Must have for v1.4 launch
- P2: Should have, add in v1.4.x patch
- P3: Future consideration, v2+

---

## Domain Patterns Research

### How Tier Thresholds Should Be Set

Based on research into API platform tier systems (Azure OpenAI, Google Gemini, OpenAI) and
gamification systems, the standard pattern is:

- **Bronze (entry):** Default tier for all agents; requires no threshold. Any agent with
  insufficient data starts here. Resources: free-tier fallback model, baseline rate limits.
- **Silver (mid):** Agents that demonstrate consistent reliability. Recommended default
  threshold: composite score >= 0.65, with at least 10 completed tasks.
  Resources: reliable premium model (e.g., Synthetic general), 1.5x rate limit multiplier.
- **Gold (top):** Agents with sustained excellence. Recommended default threshold:
  composite score >= 0.85, with at least 25 completed tasks.
  Resources: L1 workhorse model (e.g., Synthetic coding/reasoning), 2x rate limit multiplier,
  increased concurrent task capacity.

All thresholds should be configurable via environment variables:

- `REWARDS_SILVER_THRESHOLD` (default: 0.65)
- `REWARDS_GOLD_THRESHOLD` (default: 0.85)
- `REWARDS_MIN_TASKS` (default: 10)

### Composite Score Formula

Research into AI agent evaluation frameworks (Galileo, Anthropic evals, MachineLearningMastery)
confirms that multi-dimension scoring outperforms single-metric scoring for real-world agents.
The recommended formula for Agent42, using only data already in EffectivenessStore:

```python
score = (success_rate * 0.60)
      + (min(invocations, 100) / 100 * 0.25)   # volume, capped at 100
      + (speed_score * 0.15)                     # normalized avg_duration, inverted
```

Where `speed_score = 1 - min(avg_duration_ms / MAX_EXPECTED_MS, 1.0)` with a configurable
`MAX_EXPECTED_MS` (default: 30,000ms). Speed is the smallest weight because it's task-type
dependent — a research agent is expected to be slow.

Confidence: MEDIUM — formula derived from research principles; weights should be validated
against real agent data in production and adjusted if success_rate proves insufficient signal.

### Resource Allocation per Tier

Based on how API providers (OpenAI, Azure Foundry, Gemini) structure their tier systems,
resource allocation should be a multiplier applied to a configurable baseline:

| Resource | Bronze | Silver | Gold |
| -------- | ------ | ------ | ---- |
| Model routing class | free-tier fallback | Synthetic general / Gemini | Synthetic coding/reasoning |
| Rate limit multiplier | 1.0x (baseline) | 1.5x | 2.0x |
| Max concurrent tasks | 1 | 2 | 4 |
| Max iterations per task | AgentConfig.max_iterations unchanged | +20% | +50% |

The multiplier approach (not absolute values) lets the baseline be configurable without
re-specifying all tier limits — only the deltas need tier-specific env vars.

---

## Sources

- Azure OpenAI quota tiers — automatic tier upgrade on usage (HIGH confidence):
  [Azure OpenAI Quotas and Limits](https://learn.microsoft.com/en-us/azure/foundry/openai/quotas-limits)
- Google Gemini API rate limit tiers (HIGH confidence):
  [Gemini API Rate Limits](https://ai.google.dev/gemini-api/docs/rate-limits)
- OpenAI API rate limit tiers (HIGH confidence):
  [OpenAI Rate Limits](https://developers.openai.com/api/docs/guides/rate-limits)
- Galileo AI agent metrics guide (MEDIUM confidence):
  [Galileo AI Agent Metrics](https://galileo.ai/blog/ai-agent-metrics)
- Anthropic agent evaluation guide (MEDIUM confidence):
  [Demystifying Evals for AI Agents](https://www.anthropic.com/engineering/demystifying-evals-for-ai-agents)
- Gamification tier mechanics — Xtremepush (MEDIUM confidence):
  [7 Gamification Mechanics That Drive Player Loyalty](https://www.xtremepush.com/blog/7-gamification-mechanics-that-drive-player-loyalty-points-badges-leaderboards-tiers-challenges-streaks-and-rewards)
- Enterprise Integration Patterns: Hysteresis design (MEDIUM confidence):
  [Hysteresis of Design Decisions](https://www.enterpriseintegrationpatterns.com/ramblings/06_hysteresis.html)
- Feature flags and graceful degradation — Unleash (HIGH confidence):
  [Graceful Degradation with FeatureOps](https://www.getunleash.io/blog/graceful-degradation-featureops-resilience)
- Agent42 EffectivenessStore source (HIGH confidence — direct read):
  `memory/effectiveness.py`
- Agent42 AgentConfig + AgentManager source (HIGH confidence — direct read):
  `core/agent_manager.py`

---

*Feature research for: Agent42 v1.4 Performance-Based Rewards System*
*Researched: 2026-03-22*

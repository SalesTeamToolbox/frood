# Pitfalls Research

**Domain:** Performance-based tier/rewards systems for AI agent platforms
**Researched:** 2026-03-22
**Confidence:** HIGH for Agent42-specific integration risks (direct code inspection); MEDIUM for general rewards-system patterns (domain reasoning from known anti-patterns in similar systems)

---

## Critical Pitfalls

Mistakes that cause rewrites, agent outages, or silent correctness bugs.

---

### Pitfall 1: Tier Lookup on Every Routing Decision Kills Throughput

**What goes wrong:**
`get_tier(agent_id)` is called inside the hot path of every model routing decision — once per iteration of the agent loop. With no caching, this hits the SQLite effectiveness DB on every call. A 10-iteration coding task with 3 agents running concurrently generates 30+ synchronous DB reads while the routing path is supposed to be non-blocking. Even with `aiofiles`-style async SQLite, the query overhead accumulates and the effective iteration rate drops noticeably.

**Why it happens:**
The constraint "tier lookups must be cached/fast" is stated but not enforced structurally. The rewards module is written with a `get_tier(agent_id)` method that reads from the effectiveness DB and the temptation is to call it wherever the tier is needed. There is no forcing function that makes the cached path the default.

**How to avoid:**
Cache tier assignments at a `TierCache` layer with a TTL (suggested: 15 minutes). The cache is keyed by `agent_id` and stores `(tier, expires_at)`. Routing code calls `tier_cache.get(agent_id)` — not the DB directly. Background recalculation runs on a timer, not on the routing hot path. The `TierCache` must be a singleton shared across all routing code, not instantiated per-request.

**Warning signs:**

- Iteration throughput decreases noticeably when `REWARDS_ENABLED=true` vs `false` under load
- SQLite DB file read activity spikes proportionally with concurrent agents
- `time.monotonic()` profiling shows `get_tier()` consistently in the top 5 slowest calls during agent execution

**Phase to address:**
Phase 1 (Tier calculation engine) — design the cache layer before any integration with routing. Define the interface first: routing code should never call the DB directly.

---

### Pitfall 2: Effectiveness Data Does Not Map to Agent Identity

**What goes wrong:**
The existing `EffectivenessStore` records `(tool_name, task_type, task_id, success, duration_ms)`. There is no `agent_id` column. The rewards system needs to score per-agent performance, but the effectiveness data is recorded at the tool-invocation level with no agent attribution. Attempting to infer agent identity from `task_id` is fragile — tasks can be reassigned, retried by different agents, or created without agent context.

**Why it happens:**
`EffectivenessStore` was built for tool/skill effectiveness recommendations (which tools work best for which task types), not for agent-level performance scoring. Adding agent-level scoring on top of this schema requires either a schema migration or a separate agent-performance table.

**How to avoid:**
Add an `agent_id` column to `tool_invocations` with a schema migration that defaults existing rows to `""` (unknown). Alternatively — and cleaner for the rewards scope — create a separate `agent_performance` table that aggregates effectiveness data by agent rather than mutating the existing schema. The separate table avoids touching 1,956 existing tests and keeps concerns separated. Record agent_id at the point where agents execute tasks, piped through from `AgentRuntime`.

**Warning signs:**

- Performance score queries return identical scores for all agents (data is not differentiated by agent)
- `get_aggregated_stats()` results are grouped by `(tool_name, task_type)` with no way to filter by agent
- Tier assignments are random-looking or always map to the same tier for all agents

**Phase to address:**
Phase 1 (Tier calculation engine) — data schema must be resolved before building any scoring logic on top of it.

---

### Pitfall 3: Frozen Dataclass Config Means No Runtime Toggle

**What goes wrong:**
`Settings` is a frozen dataclass loaded once at import time from environment variables. `REWARDS_ENABLED` must be added as a field to `Settings` following this pattern. However, the dashboard "global toggle" for rewards requires the value to change at runtime without a restart. If the dashboard writes to `.env` and the reload path tries to mutate `settings.rewards_enabled`, it will raise `FrozenInstanceError`. If instead the dashboard stores the toggle in a separate mutable config file, and routing code checks both `settings.rewards_enabled` AND the mutable file, the two sources of truth will diverge silently.

**Why it happens:**
The frozen dataclass pattern is correct for startup config, but rewards has a UI toggle that implies runtime mutability. These two requirements are in direct conflict. The path of least resistance — adding a `rewards_enabled` mutable global variable — breaks the architectural pattern and creates a hidden state leak.

**How to avoid:**
Treat `settings.rewards_enabled` as the "can this feature activate at all" gate (false = fully disabled, feature is inert). A separate `RewardsConfig` dataclass (mutable, file-backed, not frozen) handles runtime state: the global on/off toggle, tier thresholds, and override table. The dashboard writes to `rewards_config.json` and the rewards module reads from it. This mirrors the existing pattern used by `agents.json` and `cron_jobs.json`. The key invariant: if `settings.rewards_enabled=false`, nothing in `RewardsConfig` is consulted.

**Warning signs:**

- Dashboard toggle appears to work but agent behavior does not change until restart
- `FrozenInstanceError` in logs when dashboard writes config
- `settings.rewards_enabled` is `True` (from `.env`) but the dashboard shows it toggled off — state mismatch

**Phase to address:**
Phase 1 (config layer) and Phase 3 (dashboard toggle) — the config architecture must be established before the dashboard wires up.

---

### Pitfall 4: Admin Override Silently Lost on Tier Recalculation

**What goes wrong:**
Admin sets agent "Researcher-7" to Gold tier override via the dashboard because it's a critical production agent. Two hours later, the background tier recalculation job runs and promotes or demotes the agent based on its actual performance score, overwriting the admin's override. The admin has no indication this happened unless they check the dashboard again.

**Why it happens:**
The recalculation job operates on all agents in a loop. Without an explicit check for the `admin_override` flag before writing the new tier, every recalculation silently clobbers overrides. This is the classic "manual-data vs automated-data" conflict that appears in any system where humans and automation write to the same field.

**How to avoid:**
Store admin overrides in a separate `tier_overrides` dict (keyed by `agent_id`). The tier resolution logic is: if `agent_id in tier_overrides`, return the override tier — never recalculate. The recalculation job skips agents with active overrides. The override must have a visible timestamp and optional expiry so admins know when they set it and it doesn't become permanent by accident. When a recalculation is skipped due to override, log it at INFO level so audit trails exist.

**Warning signs:**

- Admins repeatedly set the same override and it keeps reverting
- Logs show recalculation completing successfully for agents that have active overrides
- Tier history shows rapid oscillation for an agent that was manually overridden

**Phase to address:**
Phase 2 (tier assignment logic) — override semantics must be designed before the recalculation job is implemented.

---

### Pitfall 5: New Agents Stuck at Bronze With No Path to Promotion

**What goes wrong:**
The scoring logic requires `min_observations` (currently 5 in `get_recommendations()`) before assigning a score. A brand new agent has zero history. With no score, it defaults to Bronze. Bronze tier gets restricted resources and worse models. With worse models, the agent is less effective, accumulates mediocre scores, and may never accumulate enough high-quality completions to promote to Silver. The rewards system creates a negative feedback loop for new agents.

**Why it happens:**
Tier systems optimized for steady-state operation don't account for the cold-start problem. The `min_observations` floor is correct for the recommendations use case (don't recommend a tool you've seen 2 times), but applying the same floor to tier assignment means new agents start penalized rather than neutral.

**How to avoid:**
New agents (< `min_observations` completions) receive a "provisional" status that maps to a configured default tier (recommended: Silver as the neutral default, not Bronze). The provisional tier uses the same resource allocation as the default tier. Only after `min_observations` completions does the agent enter the scoring pool. This prevents the cold-start penalty without inflating Bronze scores. Document this clearly in the dashboard so admins understand why new agents show "Provisional (Silver)" rather than Bronze.

**Warning signs:**

- All new agents are Bronze immediately upon creation
- New agents complete fewer tasks over time while same-age agents without the rewards system do not show this pattern
- Agents created for short tasks accumulate scores very slowly and stay at Bronze indefinitely

**Phase to address:**
Phase 2 (tier assignment logic) — provisional handling must be part of the initial design, not added as a hotfix.

---

### Pitfall 6: Resource Allocation Bypasses Existing Rate Limiter Architecture

**What goes wrong:**
The rewards system introduces per-tier resource limits: Bronze gets 2 concurrent tasks, Silver gets 5, Gold gets 10. The implementation naively adds a `max_concurrent` check in the agent dispatch code, duplicating logic that already exists in `ToolRateLimiter` and `max_concurrent_agents` in `Settings`. When both the legacy rate limiter and the new tier-based limiter are active, they can conflict: the old limiter allows a Gold agent to proceed but the new limiter hasn't been checked yet, or vice versa. Race conditions emerge under concurrent dispatch.

**Why it happens:**
Resource limiting is added as a new concept in rewards without auditing the existing limiting surfaces. The dispatch path already has `max_concurrent_agents` logic — adding a second enforcement point creates two separate state machines that must stay in sync.

**How to avoid:**
Extend the existing `ToolRateLimiter` architecture rather than building a parallel one. Tier-based concurrent limits become `ToolLimit` entries applied at the agent level (not per-tool). Alternatively, integrate tier limits into the existing `max_concurrent_agents` logic by making it tier-aware: instead of a global max, it becomes a per-tier max enforced by the same dispatch guard. One enforcement point, one place to audit.

**Warning signs:**

- Gold agents occasionally get rejected with "concurrent limit reached" when the Gold limit should not be hit
- Rate limit errors appear inconsistently — sometimes agents are allowed, sometimes not, for the same apparent load
- `ToolRateLimiter.reset()` clearing agent state doesn't affect the tier-based limiter

**Phase to address:**
Phase 3 (Agent Manager integration) — before wiring tier limits into dispatch, audit all existing rate limiting code paths.

---

### Pitfall 7: Performance Score Is Actually Task Volume, Not Task Quality

**What goes wrong:**
The composite performance score is built from effectiveness tracking data: success rate, average duration, tool invocation counts. An agent that runs many short tasks (e.g., a monitoring agent that pings a health endpoint 200 times/day with near-100% success) scores higher than an agent that runs 3 complex coding tasks with 85% success. The monitoring agent reaches Gold. The coding agent stays Bronze. "Business success" is not what is being measured.

**Why it happens:**
The effectiveness data (`tool_invocations` table) measures tool call outcomes, not task outcomes. A successful tool call is not the same as a valuable task completion. Correlating tool-level success with agent-level "business value" requires a layer of judgment that the raw data does not provide.

**How to avoid:**
Weight the composite score by task type complexity, not just success count. Add a `task_complexity_weight` mapping (e.g., `coding=3.0`, `research=2.0`, `monitoring=0.5`) that scales contributions to the performance score. Alternatively, use task-level outcomes (critic score on final output, human approval rate) as the primary signal rather than tool-invocation success rate. Be explicit in the dashboard about what the score represents so admins can interpret and override it meaningfully.

**Warning signs:**

- High-volume, low-complexity agents consistently outrank low-volume, high-complexity agents
- Agents used for health checks or cron tasks always achieve Gold quickly
- Admin overrides are routinely needed to fix tier assignments that "don't feel right"

**Phase to address:**
Phase 1 (scoring engine design) — scoring formula must account for task type before any data is collected against it.

---

### Pitfall 8: Dashboard Tier Controls Are Not Protected by Existing Auth Middleware

**What goes wrong:**
New dashboard API endpoints for tier management (`/api/rewards/tiers`, `/api/rewards/override`, `/api/rewards/config`) are added without applying the existing `require_auth` JWT middleware decorator. Because the rewards module is new, it's easy to miss applying the middleware consistently — especially if the endpoints are scaffolded quickly from a template. An unauthenticated attacker could promote their agent to Gold tier or disable the rewards system entirely.

**Why it happens:**
Agent42 has a working JWT auth layer (`server.py`) but new endpoint files don't inherit it automatically. Every new router must explicitly apply the auth dependency. This is a consistent pattern issue across the codebase — pitfall #95 in CLAUDE.md documents auth issues with bcrypt, showing auth correctness has been a repeat problem.

**How to avoid:**
Apply the auth dependency at the router level, not per-endpoint. Use `APIRouter(dependencies=[Depends(require_auth)])` so all routes under the rewards router are protected by construction. Add an integration test that hits each rewards endpoint without a valid JWT and asserts 401. This test should be part of the phase definition of done.

**Warning signs:**

- Rewards API endpoints return 200 without an `Authorization` header
- No `require_auth` import in the rewards router file
- Manual curl to `/api/rewards/config` succeeds without a token

**Phase to address:**
Phase 3 (dashboard integration) — auth must be verified for every new endpoint before the phase closes.

---

### Pitfall 9: Dynamic Model Routing Upgrade Doesn't Respect Per-Agent Config Overrides

**What goes wrong:**
When an agent reaches Gold tier, the system upgrades its routing to access premium models (e.g., Claude Sonnet instead of Gemini Flash). But agents can have per-agent model overrides set in their config (`agent.model`, `agent.provider`). The tier-based routing upgrade silently overrides the explicit per-agent model config, or the explicit config silently blocks the tier upgrade. Neither behavior is correct without explicit precedence rules.

**Why it happens:**
The `AgentRuntime._build_env()` constructs the environment by reading `agent_config.get("provider")` and `agent_config.get("model")`. The tier-based routing needs to inject into this same config. Without explicit precedence logic, whichever value is set last wins — and that depends on code order, not declared intent.

**How to avoid:**
Establish explicit precedence: per-agent manual override > tier-based routing > global default. The agent config should carry an `allow_tier_routing_override: bool = True` field. When `true`, tier-based routing can upgrade the model. When `false`, the per-agent model config is locked and tier routing is skipped for that agent. Document this in the dashboard so admins know why a Gold agent might still use a specific model.

**Warning signs:**

- Gold agents use the same model as Bronze agents (tier routing silently blocked)
- Agents with explicit model overrides get reassigned to different models after tier promotion (override silently overwritten)
- Model used by an agent changes unpredictably across task runs

**Phase to address:**
Phase 3 (Agent Manager integration) — precedence rules must be documented and tested before tier routing is wired into `_build_env()`.

---

### Pitfall 10: Rewards State Is Lost on Server Restart Without Persistence

**What goes wrong:**
The `TierCache` stores computed tiers in memory. If Agent42 restarts (deploy, crash, update), the cache is empty. All agents reset to their default tier until the next recalculation completes. If the recalculation takes 30-60 seconds, there is a window where Gold agents are running as Bronze. Worse, if the background recalculation never triggers (e.g., because no tasks are running), the cache stays empty indefinitely and all agents run at the default tier.

**Why it happens:**
In-memory caches are fast to implement but their persistence boundary is the process lifetime. Most development and testing happens without restarts, so the empty-on-startup case is never encountered until production deployment.

**How to avoid:**
Persist computed tier assignments to a lightweight JSON file (`.agent42/tier_assignments.json`) after each recalculation. On startup, load this file to warm the cache before the first recalculation runs. The file format: `{agent_id: {tier, score, calculated_at, override}}`. This is the same pattern used by `agents.json`, `cron_jobs.json` — consistent with the project's file-backed persistence convention.

**Warning signs:**

- After every deployment, Gold agents run at Bronze speeds for a period
- Agent logs show model downgrades immediately after startup
- Admin reports that "it broke after the update" but the system looks healthy

**Phase to address:**
Phase 1 (tier calculation engine) — persistence must be designed before the cache layer, not retrofitted.

---

## Technical Debt Patterns

Shortcuts that seem reasonable but create long-term problems.

| Shortcut | Immediate Benefit | Long-term Cost | When Acceptable |
| --- | --- | --- | --- |
| Scoring from tool success rate only (no task-type weighting) | Simple to implement, uses existing data | Volume-based agents game the system; score loses meaning | Never — include task type weights from the start |
| In-memory-only tier cache (no persistence) | Fast dev, no file I/O | Agents downgraded on every restart until recalculation | Never — warm from file at startup |
| Per-endpoint auth guards (not router-level) | Quick to add per route | Easy to miss a new endpoint, silently unauthenticated | Never for admin operations |
| Computing performance score on-demand per request | No background job to manage | Every dashboard page load hits the DB for full aggregation | Acceptable only during initial prototyping, not production |
| Single global `min_observations` threshold for all agents | Mirrors existing `get_recommendations()` | New agents stuck at Bronze; cold-start kills early performance | Never — use provisional tier for new agents |
| Mutating `Settings` frozen dataclass for runtime toggle | Avoids separate config file | `FrozenInstanceError` in production; violates architecture | Never |

---

## Integration Gotchas

Common mistakes when connecting to the existing Agent42 systems.

| Integration | Common Mistake | Correct Approach |
| --- | --- | --- |
| `EffectivenessStore` | Query per-request inside routing hot path | Cache tier results in `TierCache` with TTL; never query DB during routing |
| `ToolRateLimiter` | Add parallel rate limiting for tier resource caps | Extend existing `ToolRateLimiter` with tier-aware limits, not a second limiter |
| `Settings` frozen dataclass | Add mutable `rewards_enabled` field to `Settings` | Keep `Settings.rewards_enabled` as startup gate; use separate mutable `RewardsConfig` |
| `AgentRuntime._build_env()` | Inject tier routing before precedence rules defined | Define explicit precedence (manual override > tier > default) and test it |
| Dashboard auth (`require_auth`) | Apply auth per-endpoint via decorator | Use `APIRouter(dependencies=[Depends(require_auth)])` for whole rewards router |
| Background recalculation | Run recalculation inside request handler on first request | Run recalculation on a background `asyncio.Task`; startup warms from persisted JSON |
| `aiosqlite` | Open a new connection per `get_tier()` call | Use connection pooling or the existing `EffectivenessStore` interface; don't bypass it |

---

## Performance Traps

Patterns that work at small scale but fail as the agent count grows.

| Trap | Symptoms | Prevention | When It Breaks |
| --- | --- | --- | --- |
| Score recalculation for all agents on a fixed timer | Timer fires, all agents pause briefly as scores are recomputed | Stagger recalculation by agent (not all at once); use async background task | At ~20+ agents |
| Full `tool_invocations` table scan for each agent's score | Dashboard page load slow; DB lock contention | Index `tool_invocations` by `agent_id`; materialize scores into `agent_performance` table | At ~10K invocation rows |
| Dashboard loads full tier history on page open | History grows unbounded; page response slow | Paginate tier history; cap retained history to last 90 days | After 6 months of operation |
| Tier recalculation holds SQLite write lock | Other effectiveness writes block during recalculation | Recalculation reads only; writes go to separate aggregation table | Any time concurrent agents are active |

---

## Security Mistakes

Domain-specific security issues beyond general web security.

| Mistake | Risk | Prevention |
| --- | --- | --- |
| Rewards API endpoints without auth | Unauthenticated tier override (attacker promotes to Gold) | Router-level `require_auth` dependency; test 401 on all endpoints |
| Admin override field editable by non-admin | Any dashboard user can override tiers | Check role/permission on override endpoint; Agent42 currently has single admin role — document the assumption |
| Performance scores exposed to agents themselves | Agent could modify behavior to game the scoring metric | Scores used only in background recalculation; never injected into agent prompt or tool context |
| Tier assignment file (`.agent42/tier_assignments.json`) world-readable | Exposes agent performance data | File permissions match existing `.agent42/` files; not served by any API without auth |
| `REWARDS_ENABLED` in `.env` treated as security control | Admin assumes disabling in `.env` is instant | Document that env change requires restart; dashboard toggle takes effect immediately (runtime config, not Settings) |

---

## UX Pitfalls

Common user experience mistakes in tier/rewards system dashboards.

| Pitfall | User Impact | Better Approach |
| --- | --- | --- |
| Showing raw score number without context | "What does 7.3 mean? Is that good?" | Show score + tier badge + trend arrow (up/down from last period) |
| No explanation for why an agent is at a tier | Admin can't fix what they don't understand | Show top contributing factors (e.g., "High success rate on coding tasks" or "Insufficient data — provisional") |
| Override UI without expiry date | Overrides accumulate; admins forget they set them | Require expiry or explicit "permanent" selection; show override age on dashboard |
| Tier change history not visible | Admin can't tell when a demotion happened | Log tier transitions with timestamp, old tier, new tier, reason (automated vs override) |
| Rewards toggle with no confirmation | Accidental disable in production | Require confirmation dialog for disabling rewards when agents are currently running |
| All metrics visible to non-admin users | Users see other agents' performance data | Scope metrics visibility to admin role; if multi-user access is ever added |

---

## "Looks Done But Isn't" Checklist

Things that appear complete but are missing critical pieces.

- [ ] **Tier cache:** Cache is populated but not persisted — verify `.agent42/tier_assignments.json` is written after each recalculation
- [ ] **Admin override:** Override UI saves to DB but verify recalculation job skips agents with active overrides
- [ ] **New agent cold start:** New agents show a tier — verify it's "Provisional" not Bronze (check agent with 0 completed tasks)
- [ ] **Auth on all endpoints:** Dashboard shows tier data — verify `/api/rewards/override` returns 401 without token (curl test)
- [ ] **REWARDS_ENABLED=false:** Toggle is in `.env` — verify no tier lookup code runs at all (zero DB reads in rewards module when disabled)
- [ ] **Model routing precedence:** Gold agent shows premium model — verify agent with explicit `model` override in config does NOT get overridden by tier routing
- [ ] **Background recalculation:** Tier updates after task completion — verify recalculation does NOT block agent iteration (measure iteration timing with and without rewards enabled)
- [ ] **Restart recovery:** Redeploy and verify Gold agents retain Gold tier within 5 seconds of startup (loaded from persisted JSON, not waiting for first recalculation)

---

## Recovery Strategies

When pitfalls occur despite prevention, how to recover.

| Pitfall | Recovery Cost | Recovery Steps |
| --- | --- | --- |
| All agents demoted to Bronze after restart (no persistence) | LOW | Add file-based persistence for tier cache; redeploy; tiers restore on next recalculation |
| Admin override silently cleared by recalculation job | LOW | Add `admin_override` guard to recalculation loop; re-apply overrides manually from dashboard |
| Performance score rewards task volume not quality | HIGH | Requires scoring formula redesign + historical data re-scoring; may need to reset all tiers and restart accumulation |
| Rewards endpoints exposed without auth | MEDIUM | Emergency: disable `REWARDS_ENABLED` in `.env` and restart; then apply router-level auth and redeploy |
| Tier lookup causing routing slowdown | MEDIUM | Disable rewards temporarily (`REWARDS_ENABLED=false`); add caching layer; re-enable |
| Frozen dataclass mutation error at runtime | HIGH | Revert to `Settings.rewards_enabled=false` in `.env`; redesign runtime config as separate mutable file |

---

## Pitfall-to-Phase Mapping

How roadmap phases should address these pitfalls.

| Pitfall | Prevention Phase | Verification |
| --- | --- | --- |
| Tier lookup on hot path (Pitfall 1) | Phase 1: Tier engine — design `TierCache` with TTL before any routing integration | Measure routing call duration with and without tier lookup; must be < 1ms with cache |
| No agent_id in effectiveness data (Pitfall 2) | Phase 1: Tier engine — add `agent_id` column or separate `agent_performance` table first | Query returns distinct per-agent scores; not the same value for all agents |
| Frozen dataclass conflict (Pitfall 3) | Phase 1: Config layer — establish `RewardsConfig` mutable file before dashboard wiring | Dashboard toggle takes effect without restart; `settings.rewards_enabled=false` blocks all rewards code |
| Override cleared by recalculation (Pitfall 4) | Phase 2: Tier assignment logic — override semantics in recalculation loop | Set override, trigger recalculation manually, verify override survives |
| Cold-start Bronze penalty (Pitfall 5) | Phase 2: Tier assignment logic — provisional tier for new agents | Create new agent with 0 history; confirm tier is "Provisional" at configured default, not Bronze |
| Parallel rate limiter conflict (Pitfall 6) | Phase 3: Agent Manager integration — audit existing rate limiting before adding new | No duplicate enforcement; one check per resource limit in dispatch path |
| Volume beats quality in scoring (Pitfall 7) | Phase 1: Scoring engine design — task-type weights before data collection | Monitoring agent with 200 successful pings does not outrank coding agent with 5 complex successes |
| Missing auth on rewards endpoints (Pitfall 8) | Phase 3: Dashboard integration — router-level auth; automated 401 test | `curl /api/rewards/config` without token returns 401 |
| Tier routing overrides per-agent model config (Pitfall 9) | Phase 3: Agent Manager integration — precedence rules tested explicitly | Agent with `model` override retains it after Gold promotion |
| Tier state lost on restart (Pitfall 10) | Phase 1: Tier engine — file-based persistence before deployment testing | Restart Agent42; verify Gold agents show Gold within 5 seconds (from persisted file) |

---

## Sources

- Direct code inspection: `memory/effectiveness.py` — `EffectivenessStore` schema, `tool_invocations` table, absence of `agent_id` column (HIGH confidence)
- Direct code inspection: `core/config.py` — frozen dataclass pattern, `Settings.from_env()` (HIGH confidence)
- Direct code inspection: `core/rate_limiter.py` — `ToolRateLimiter`, `DEFAULT_TOOL_LIMITS`, sliding window pattern (HIGH confidence)
- Direct code inspection: `core/agent_manager.py` — `AgentRuntime._build_env()`, `PROVIDER_MODELS`, per-agent model config (HIGH confidence)
- Project context: `PROJECT.md` v1.4 constraints ("tier lookups must be cached/fast", "opt-in via REWARDS_ENABLED=false", "must use existing effectiveness tracking") (HIGH confidence)
- Pattern reasoning: Cold-start problem in tier/rating systems — well-documented in game matchmaking (Elo/MMR), content ranking, and marketplace reputation systems (MEDIUM confidence — general domain knowledge)
- Pattern reasoning: Volume vs quality bias in metric-based incentive systems (Goodhart's Law) — documented in agent evaluation literature (MEDIUM confidence)
- CLAUDE.md pitfalls #95, #97, #104 — auth correctness, attribute access patterns, and security in Agent42 (HIGH confidence — project history)

---

*Pitfalls research for: Performance-based tier/rewards systems (Agent42 v1.4)*
*Researched: 2026-03-22*

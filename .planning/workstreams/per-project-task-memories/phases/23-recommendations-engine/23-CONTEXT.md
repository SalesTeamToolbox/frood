# Phase 23: Recommendations Engine - Context

**Gathered:** 2026-03-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Surface tool recommendations based on aggregated effectiveness data from past tasks of the same type. When a user starts a new task, the agent receives a ranked list of up to 3 tools that performed best historically for that task type. No skill recommendations (no structured data yet), no dashboard UI, no cross-project aggregation.

</domain>

<decisions>
## Implementation Decisions

### Delivery mechanism
- **D-01:** Extend the existing `proactive-inject.py` hook to also fetch and inject recommendations — no new hook needed
- **D-02:** Add a new API endpoint `GET /api/recommendations/retrieve` in `server.py` that returns ranked tools for a given task_type
- **D-03:** The hook makes two API calls: one for learnings (existing), one for recommendations (new) — both in the same session-guarded execution
- **D-04:** Proactive injection only for v1.4 — no standalone MCP tool (deferred to backlog)

### Recommendation format
- **D-05:** Compact ranked list format with key metrics: tool name, success rate %, avg duration
- **D-06:** Example output: "Recommended tools for coding: 1. shell (92% success, 45ms avg) 2. code_intel (87%, 120ms) 3. grep (85%, 30ms)"
- **D-07:** Recommendations injected as a separate block from learnings in stderr output — two distinct sections, not merged

### Ranking and filtering logic
- **D-08:** Pure success_rate ranking: ORDER BY success_rate DESC, break ties by avg_duration ASC
- **D-09:** Minimum observation threshold: 5 per tool+task_type pair (RETR-06) — config-driven via `RECOMMENDATIONS_MIN_OBSERVATIONS=5` in .env
- **D-10:** Top-3 cap per RETR-05 — return at most 3 recommendations
- **D-11:** Config follows Phase 21 pattern: `RECOMMENDATIONS_MIN_OBSERVATIONS` in Settings.from_env()

### Scope
- **D-12:** Tools only — both built-in and MCP tools treated equally from the same EffectivenessStore pool
- **D-13:** No skill recommendations (no structured effectiveness data for skills yet)
- **D-14:** No negative recommendations ("avoid X") — positive recommendations only

### Claude's Discretion
- Exact API response schema for `/api/recommendations/retrieve` beyond the required fields
- How to handle the edge case where all tools for a task_type have identical success_rate
- Token budget allocation between learnings and recommendations sections
- Exact stderr formatting and emoji/symbol choices

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Effectiveness data layer
- `memory/effectiveness.py` — EffectivenessStore class: `get_aggregated_stats()` already computes success_rate and avg_duration_ms grouped by tool+task_type. This is the data source for recommendations.

### Proactive injection (Phase 22 — extend this)
- `.claude/hooks/proactive-inject.py` — UserPromptSubmit hook: task-type keyword inference, session guard, stderr output pattern. Extend to also call the new recommendations endpoint.
- `dashboard/server.py` lines 3348-3427 — `GET /api/learnings/retrieve` endpoint: pattern for the new recommendations endpoint (query params, score gating, graceful degradation).

### Configuration pattern
- `core/config.py` — Settings frozen dataclass: `LEARNING_MIN_EVIDENCE`, `LEARNING_QUARANTINE_HOURS` pattern for adding `RECOMMENDATIONS_MIN_OBSERVATIONS`

### Requirements
- `.planning/workstreams/per-project-task-memories/REQUIREMENTS.md` — RETR-05 (top-3 by success_rate), RETR-06 (minimum 5 observations)

### Test patterns
- `tests/test_effectiveness.py` — Existing EffectivenessStore tests; extend for recommendations aggregation queries
- `tests/test_proactive_injection.py` — Existing proactive injection hook tests; extend for recommendations injection

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `EffectivenessStore.get_aggregated_stats(task_type=...)` — already returns success_rate and avg_duration_ms per tool. The recommendations endpoint essentially wraps this with filtering (min observations) and limiting (top 3)
- `proactive-inject.py` task-type keyword inference — reuse for determining which task_type to query recommendations for
- `proactive-inject.py` session guard — reuse to ensure recommendations are injected once per session (same guard protects both learnings and recommendations)

### Established Patterns
- Fire-and-forget / graceful degradation: recommendations follow the same "never block, never crash" pattern as effectiveness tracking
- API endpoint pattern: `GET /api/learnings/retrieve` with query params, try/except wrapping, memory_store None check — recommendations endpoint mirrors this
- Config-driven thresholds: `LEARNING_MIN_EVIDENCE=3` in .env → `RECOMMENDATIONS_MIN_OBSERVATIONS=5` follows same pattern

### Integration Points
- `proactive-inject.py` — add second HTTP call to `/api/recommendations/retrieve` after the existing learnings call
- `dashboard/server.py` — add new endpoint alongside existing `/api/learnings/retrieve`
- `core/config.py` Settings — add `RECOMMENDATIONS_MIN_OBSERVATIONS` field
- `.env.example` — document the new config variable

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

- MCP tool for on-demand recommendations (agent42_recommendations) — add to backlog for future milestone
- Skill recommendations — no structured effectiveness data yet; add when skill tracking exists
- Negative recommendations ("avoid X tool for Y task type") — future enhancement
- Weighted composite scoring (recency, frequency) — add if pure success_rate proves insufficient

</deferred>

---

*Phase: 23-recommendations-engine*
*Context gathered: 2026-03-22*

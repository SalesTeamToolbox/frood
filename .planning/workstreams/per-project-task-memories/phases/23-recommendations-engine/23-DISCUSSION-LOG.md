# Phase 23: Recommendations Engine - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-22
**Phase:** 23-recommendations-engine
**Areas discussed:** Delivery mechanism, Recommendation format, Ranking and filtering logic, Scope

---

## Delivery Mechanism

| Option | Description | Selected |
|--------|-------------|----------|
| Extend proactive-inject.py | Add second API call to existing hook — single hook, single session guard. Simplest path. | ✓ |
| New dedicated hook | Separate recommendations-inject.py. Clean separation but duplicates task-type inference and session guard. | |
| New API endpoint only | Add GET /api/recommendations/retrieve. Hook calls it alongside learnings. | |

**User's choice:** Extend proactive-inject.py
**Notes:** Also decided proactive-only for v1.4 — MCP tool deferred to backlog.

### Follow-up: MCP tool availability

| Option | Description | Selected |
|--------|-------------|----------|
| Proactive only | Recommendations come automatically at task start via hook. No MCP tool. | ✓ |
| Both proactive + MCP tool | Also expose as MCP tool for mid-task queries. | |

**User's choice:** Proactive only, but add MCP tool as a todo for later.

---

## Recommendation Format

| Option | Description | Selected |
|--------|-------------|----------|
| Compact ranked list | Tool name + success rate + avg duration. Brief and scannable. | ✓ |
| Minimal labels only | Just tool names, no metrics. Saves tokens. | |
| Detailed with context | Success rate, duration, observation count, one-line reason. More informative. | |

**User's choice:** Compact ranked list

### Follow-up: Injection layout

| Option | Description | Selected |
|--------|-------------|----------|
| Separate blocks | Two distinct sections: "Past Learnings:" then "Recommended Tools:". | ✓ |
| Combined single block | One "Task Context:" block with both interleaved. | |

**User's choice:** Separate blocks

---

## Ranking and Filtering Logic

| Option | Description | Selected |
|--------|-------------|----------|
| Pure success_rate | Rank by success_rate DESC, tie-break by avg_duration ASC. Simple, matches RETR-05. | ✓ |
| Weighted composite score | 0.7 success + 0.2 recency + 0.1 frequency. More nuanced but harder to debug. | |
| Success rate with recency decay | Weight recent observations more. | |

**User's choice:** Pure success_rate

### Follow-up: Min observations config

| Option | Description | Selected |
|--------|-------------|----------|
| Config-driven (.env) | RECOMMENDATIONS_MIN_OBSERVATIONS=5. Follows Phase 21 pattern. | ✓ |
| Hardcoded constant | Simpler but breaks config-driven pattern. | |

**User's choice:** Config-driven

---

## Scope

| Option | Description | Selected |
|--------|-------------|----------|
| Tools only | Built-in + MCP tools from EffectivenessStore. Skills added later when data exists. | ✓ |
| Tools + skills | Include skills in recommendations. Needs parallel tracking mechanism. | |
| Tools + negative recs | Also warn about low-performing tools. Adds complexity. | |

**User's choice:** Tools only

### Follow-up: MCP tool treatment

| Option | Description | Selected |
|--------|-------------|----------|
| All tools equally | EffectivenessStore tracks both; recommendations come from same pool. | ✓ |
| Built-in only | Exclude MCP tools. Simpler but misses data. | |

**User's choice:** All tools equally

---

## Claude's Discretion

- Exact API response schema beyond required fields
- Edge case handling (identical success rates)
- Token budget split between learnings and recommendations
- Exact stderr formatting choices

## Deferred Ideas

- MCP tool for on-demand recommendations — future milestone
- Skill recommendations — when skill tracking data exists
- Negative recommendations — future enhancement
- Weighted composite scoring — if pure success_rate insufficient

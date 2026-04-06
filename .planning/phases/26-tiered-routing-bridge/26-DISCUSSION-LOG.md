# Phase 26: Tiered Routing Bridge - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-29
**Phase:** 26-tiered-routing-bridge
**Areas discussed:** Role-to-category mapping, Cost & usage tracking, Provider selection chain, Bridge class design

---

## Role-to-Category Mapping

| Option | Description | Selected |
|--------|-------------|----------|
| Static dict in TieredRoutingBridge | Simple constant dict in the bridge class. Paperclip roles are stable — no runtime config needed. | ✓ |
| Configurable via env/JSON file | Load mapping from .agent42/role_mapping.json or env vars. Adds complexity for a 4-entry map. | |
| You decide | Claude picks the simplest approach | |

**User's choice:** Static dict in TieredRoutingBridge (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Base roles only | Just engineer/researcher/writer/analyst + fallback to general. Paperclip's role field is an enum. | ✓ |
| Prefix-tolerant matching | Strip prefixes like 'senior_', 'lead_' before mapping. | |
| You decide | Claude picks based on what Paperclip actually sends | |

**User's choice:** Base roles only (Recommended)

---

## Cost & Usage Tracking

| Option | Description | Selected |
|--------|-------------|----------|
| Wire the plumbing, populate later | Bridge resolves model+provider, passes into usage dict. Tokens and costUsd stay 0 until AgentRuntime wired. | ✓ |
| Simulate realistic values | Generate estimated token counts and costs based on task type + model pricing table. | |
| You decide | Claude picks without faking data | |

**User's choice:** Wire the plumbing, populate later (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Yes, include pricing table | Static dict mapping model IDs to per-token costs. Matches SpendingTracker pattern. | ✓ |
| Defer to SpendingTracker | Bridge delegates cost calculation to existing SpendingTracker. | |
| You decide | Claude picks based on existing patterns | |

**User's choice:** Yes, include pricing table (Recommended)

---

## Provider Selection Chain

| Option | Description | Selected |
|--------|-------------|----------|
| Synthetic (L1 workhorse) | StrongWall/Synthetic is L1 workhorse per PROJECT.md. Falls back to anthropic if synthetic key missing. | ✓ |
| Use AgentRoutingStore profile overrides | Look up agent's routing profile in agent_routing.json. | |
| Configurable via env var | New SIDECAR_DEFAULT_PROVIDER env var. | |

**User's choice:** Synthetic (L1 workhorse) (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Fall back to 'general' category on that provider | resolve_model() already does this fallback. | ✓ |
| Ignore preferredProvider, use default | Switch to default provider (synthetic) which has all categories. | |
| You decide | Claude picks safest behavior | |

**User's choice:** Fall back to 'general' category on that provider (Recommended)

---

## Bridge Class Design

| Option | Description | Selected |
|--------|-------------|----------|
| New class in core/tiered_routing_bridge.py | Follows MemoryBridge pattern. Clean, testable, single-responsibility. | ✓ |
| Logic inline in SidecarOrchestrator | Add routing logic directly in execute_async(). No new file. | |
| You decide | Claude picks based on codebase patterns | |

**User's choice:** New class in core/tiered_routing_bridge.py (Recommended)

| Option | Description | Selected |
|--------|-------------|----------|
| Internal-only for now | Called by SidecarOrchestrator only. Plugin gets routing via route_task tool in Phase 28. | ✓ |
| Add POST /routing/resolve endpoint | External clients can query routing decisions directly. | |

**User's choice:** Internal-only for now (Recommended)

---

## Claude's Discretion

- Exact field names for RoutingDecision dataclass
- Whether TieredRoutingBridge receives RewardSystem directly or via SidecarOrchestrator
- Pricing table values (per-model token costs)
- Logging format for routing decisions
- Whether to add HTTP endpoint later (deferred to Phase 28)

## Deferred Ideas

None — discussion stayed within phase scope

# Phase 25: Memory Bridge - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-29
**Phase:** 25-memory-bridge
**Areas discussed:** Recall integration, Learning extraction, Scope partitioning, HTTP API design
**Mode:** Advisor (standard calibration, 4 parallel research agents)

---

## Recall Integration

| Option | Description | Selected |
|--------|-------------|----------|
| Pre-inject inside execute_async | Orchestrator owns recall — asyncio.wait_for with 200ms timeout, empty-list fallback. Recalled memories threaded to agent prompt. | ✓ |
| Route-layer injection | sidecar.py does recall before handing off to orchestrator. Adds latency to 202 response. | |
| Lazy inject from Paperclip | Paperclip calls /memory/recall first, passes memories in execute payload. Shifts scope enforcement outside Agent42. | |

**User's choice:** Pre-inject inside execute_async (Recommended)
**Notes:** Structurally the only option consistent with fire-and-forget execute_async pattern. Route-layer injection blocked by 202 async design. Lazy inject contradicts MEM-02 and MEM-05 ownership.

---

## Learning Extraction

| Option | Description | Selected |
|--------|-------------|----------|
| Fire-and-forget + result summary | asyncio.create_task after callback; extract from result summary only. Upgrade to full transcript when AgentRuntime wires in. | ✓ |
| Fire-and-forget + full transcript | asyncio.create_task after callback; extract from full agent transcript. More signal but requires transcript assembly not yet built. | |
| Await before callback + result summary | Block callback until learning completes. Violates MEM-03 but guarantees learning completeness. | |

**User's choice:** Fire-and-forget + result summary (Recommended)
**Notes:** MEM-03 eliminates blocking options. Result summary is pragmatic for Phase 25 — AgentRuntime stub already produces it. Transcript upgrade path requires no structural change.

---

## Scope Partitioning

| Option | Description | Selected |
|--------|-------------|----------|
| Payload filter + is_tenant index | Single collection, agent_id + company_id as payload fields with is_tenant=True Qdrant index. Forward-compatible with SCALE-01. | ✓ |
| Simple payload filter | Same but without is_tenant optimization. Simpler, works with any Qdrant version. | |
| Separate collection per agent | Hard isolation via collection-per-agent. RAM-heavy, Qdrant warns against it. | |

**User's choice:** Payload filter + is_tenant index (Recommended)
**Notes:** Extends existing QdrantStore payload-filter pattern. is_tenant provides HNSW co-location per tenant. Forward-compatible with deferred SCALE-01. Required agent_id param prevents unfiltered leaks. Sources: Qdrant multitenancy docs, Qdrant 1.16 release notes.

---

## HTTP API Design

| Option | Description | Selected |
|--------|-------------|----------|
| Structured recall + pre-extracted store | Recall returns {text, score, source, metadata} objects. Store accepts {text, section, tags, agent_id, company_id}. Same Bearer auth. | ✓ |
| Raw text recall + pre-extracted store | Recall returns list[str]. Store accepts structured learnings. Simpler but loses score/provenance. | |
| Structured recall + raw transcript store | Recall returns structured objects. Store accepts raw transcript for server-side extraction. More complex. | |

**User's choice:** Structured recall + pre-extracted store (Recommended)
**Notes:** Structured objects match internal QdrantStore.search() contract. Prevents breaking change when Phase 28 plugin wires memory_recall tool. Pre-extracted store avoids building extraction module in sidecar. Same Bearer auth avoids new plumbing.

---

## Claude's Discretion

- Exact Pydantic field names for memory request/response models
- Top-K default and score threshold defaults
- Metadata fields in recall response
- learn_async error handling strategy (log vs. silent drop)

## Deferred Ideas

None — discussion stayed within phase scope

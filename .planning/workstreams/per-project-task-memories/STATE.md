---
workstream: per-project-task-memories
created: 2026-03-17
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-17)

**Core value:** Agent42 must always be able to run agents reliably, with tiered provider routing ensuring no single provider outage stops the platform.
**Current focus:** v1.4 Per-Project/Task Memories — Phase 20: Task Metadata Foundation

## Current Position

Phase: 20 of 23 (Task Metadata Foundation)
Plan: 0 of ? in current phase
Status: Ready to plan
Last activity: 2026-03-17 — Roadmap created, 4 phases derived from 20 requirements

Progress: [░░░░░░░░░░] 0%

## Performance Metrics

**Velocity:**
- Total plans completed: 0
- Average duration: —
- Total execution time: 0 hours

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 20. Task Metadata Foundation | 0 | — | — |
| 21. Tracking and Learning | 0 | — | — |
| 22. Proactive Injection | 0 | — | — |
| 23. Recommendations Engine | 0 | — | — |

## Accumulated Context

### Decisions

- Payload-first order: TMETA schema must exist before any tracking/extraction/retrieval is built
- RETR-01/02 grouped with Phase 20: type-aware retrieval is a search layer change that belongs with schema work, not injection work
- Tracking and extraction together in Phase 21: both depend on ToolTracker and share test infrastructure
- Injection (Phase 22) before recommendations (Phase 23): injection delivers value on every task; recommendations need accumulated data

### Key Architecture Constraints (from research)

- aiosqlite + instructor are the only new dependencies; everything else extends existing patterns
- Fire-and-forget tracking is non-negotiable — synchronous SQLite writes add 300-1500ms on a 100-call task
- Quarantine (LEARN-04) and score gate (RETR-04 >= 0.80) must be in from day one, not added later
- LEARNING_MIN_EVIDENCE and LEARNING_QUARANTINE_HOURS must be config-driven for tuning without code changes

### Research Flags for Upcoming Phases

- Phase 21: instructor extraction prompt schema needs careful design (noisy learnings hard to reverse)
- Phase 22: task-type detection at hook time without LLM call — verify IntentClassifier keyword path is reusable

### Blockers/Concerns

None yet.

## Session Continuity

Last session: 2026-03-17
Stopped at: Phase 20 context gathered
Resume file: .planning/workstreams/per-project-task-memories/phases/20-task-metadata-foundation/20-CONTEXT.md

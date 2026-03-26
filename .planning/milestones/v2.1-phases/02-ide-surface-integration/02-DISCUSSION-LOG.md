# Phase 2: IDE Surface Integration - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-24
**Phase:** 02-ide-surface-integration
**Mode:** auto
**Areas discussed:** Tab bar position, Editor state persistence, CC session scoping, Terminal session scoping

---

## Auto-Resolved Decisions

All gray areas auto-resolved with recommended defaults:

| Area | Decision | Rationale |
|------|----------|-----------|
| Tab bar position | Above editor tab bar | Matches VS Code pattern; success criteria #1 specifies "above the editor tab bar" |
| Editor state persistence | saveViewState/restoreViewState on switch | Already decided in STATE.md research — Monaco model swapping pattern |
| CC session scoping | Filter by workspace_id, cwd from workspace root | Uses Phase 1 query param contract (D-05); success criteria #4 |
| Terminal session scoping | Per-workspace terminal list, hide/show on switch | Mirrors CC session pattern; success criteria #5 |
| Persistence | localStorage stale-while-revalidate | Already decided in STATE.md research; same pattern as CC session resume |

## No Corrections

Auto mode — all decisions auto-selected from recommended defaults and prior phase decisions.

## Deferred Ideas

- Workspace management (add/remove/rename) — Phase 3
- Auto-seeding apps/ as workspaces — Phase 3

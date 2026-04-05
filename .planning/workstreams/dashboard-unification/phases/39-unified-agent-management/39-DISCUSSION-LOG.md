# Phase 39: Unified Agent Management - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-04
**Phase:** 39-unified-agent-management
**Areas discussed:** Agent data unification, Monitoring & metrics view, Control actions, Template sharing

---

## Agent Data Unification

### How should Agent42 and Paperclip agents appear in the unified view?

| Option | Description | Selected |
|--------|-------------|----------|
| Aggregated view | Merged list with source badges, one page, Agent42 editable, Paperclip read-only with deep link | ✓ |
| Side-by-side tabs | Two sub-tabs within Agents page, each showing its own system's agents | |
| Agent42-only with Paperclip link | Keep current page for Agent42 only, add link to Paperclip view | |

**User's choice:** Aggregated view (Recommended)
**Notes:** Single merged list preferred for unified experience.

### How should the Paperclip agent data be fetched?

| Option | Description | Selected |
|--------|-------------|----------|
| Sidecar proxy endpoint | New /api/agents/unified merges both sources server-side, frontend makes one call | ✓ |
| Frontend dual-fetch | Two API calls from frontend, client-side merge | |
| You decide | Claude picks based on sidecar patterns | |

**User's choice:** Sidecar proxy endpoint (Recommended)
**Notes:** Server-side merge keeps frontend simple.

---

## Monitoring & Metrics View

### What metrics should the unified agent cards show at a glance?

| Option | Description | Selected |
|--------|-------------|----------|
| Enhanced cards | Status dot, tier badge, success rate, run count, last active, 7d sparkline. Click for full detail. | ✓ |
| Current cards + metrics tab | Minimal cards, separate Metrics sub-tab with sortable table | |
| You decide | Claude designs optimal metrics display | |

**User's choice:** Enhanced cards (Recommended)
**Notes:** Rich cards with sparkline for at-a-glance monitoring.

### Should there be a cross-agent performance comparison view?

| Option | Description | Selected |
|--------|-------------|----------|
| Summary stats row | Top-of-page stats: Total agents, Active, Avg success rate, Total tokens | ✓ |
| Leaderboard table | Sortable ranking table by performance metrics | |
| Skip comparison | No cross-agent aggregation | |

**User's choice:** Summary stats row (Recommended)
**Notes:** Extends existing stats-row pattern.

---

## Control Actions

### What control should users have over Paperclip agents from the unified view?

| Option | Description | Selected |
|--------|-------------|----------|
| Read-only + deep link | Paperclip agents visible but read-only, control actions link to Paperclip UI | ✓ |
| Full proxy control | Proxy all actions through sidecar to Paperclip API | |
| You decide | Claude picks based on sidecar capabilities | |

**User's choice:** Read-only + deep link (Recommended)
**Notes:** Avoids complex cross-system auth and mutation concerns.

### Should the agent configuration form be updated?

| Option | Description | Selected |
|--------|-------------|----------|
| Polish existing form | Keep structure, add source badge showing "Agent42" | ✓ |
| Enhanced form | Add memory scope, approval toggle, prompt template fields | |
| No changes | Leave form exactly as-is | |

**User's choice:** Polish existing form (Recommended)
**Notes:** Minimal changes, clarify ownership.

---

## Template Sharing

### Should agent templates work across both systems?

| Option | Description | Selected |
|--------|-------------|----------|
| Agent42 templates only | Templates visible in both modes, always create Agent42 agents | ✓ |
| Cross-system templates | Templates can create agents in either system | |
| Hide in Paperclip mode | Templates only shown in standalone mode | |

**User's choice:** Agent42 templates only (Recommended)
**Notes:** Simple approach, Paperclip has its own creation flow.

---

## Claude's Discretion

- Sparkline rendering approach
- Card layout adjustments for enhanced metrics
- Loading states for unified endpoint
- Error handling when Paperclip unreachable
- Source badge styling
- Deep link URL format for Paperclip

## Deferred Ideas

None — discussion stayed within phase scope.

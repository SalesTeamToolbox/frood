# Phase 37: Standalone Dashboard - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-04-03
**Phase:** 37-standalone-dashboard
**Areas discussed:** Simplification strategy, Feature retention, Navigation & layout, Tool/skill management UX
**Mode:** Advisor (standard calibration, sonnet model)

---

## Simplification Strategy

Research corrected a key misconception: `app.js` (8,589 lines) is readable hand-written vanilla JS, NOT a compiled/minified bundle. Frontend is fully editable.

| Option | Description | Selected |
|--------|-------------|----------|
| Runtime feature flag | STANDALONE_MODE env flag + guard decorator on ~65 routes + frontend mode check | ✓ |
| Mode-aware frontend only | Frontend checks mode, no backend gating. Non-essential routes still respond. | |
| Trim both files | Permanently delete dead code from server.py (~3,650 lines) and app.js | |
| Rebuild frontend | New minimal SPA from scratch | |

**User's choice:** Runtime feature flag
**Notes:** Dashboard is transitional (consolidates into Paperclip long-term). Minimum effort, lowest risk, one codebase serves both modes. Follows sidecar_enabled gate pattern from Phase 36.

---

## Feature Retention

| Option | Description | Selected |
|--------|-------------|----------|
| Operational Core (4 required + 6 retained) | Keep memory, approvals, CC status, learning/effectiveness, rewards, devices. Remove chat, IDE, GSD, tasks, repos, apps. | ✓ |
| Minimal (4 required + 3) | Keep only memory, approvals, CC status beyond required. | |
| Full minus IDE/tasks | Keep everything except IDE, tasks, repos, apps. | |

**User's choice:** Operational Core
**Notes:** User questioned sandboxed apps — explored whether they add security value beyond standard deployment. Concluded the "sandbox" is path isolation + process lifecycle, not OS-level isolation. Deferred for deeper analysis later.

---

## Navigation & Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Collapsed sidebar | Keep existing sidebar, hide gated items in standalone mode. ~10 items remain. | ✓ |
| Icon-only sidebar rail | VS Code-style narrow icon bar with tooltips. Maximizes content area. | |
| Top tab bar | Horizontal tabs replacing sidebar. Maximizes vertical space. | |

**User's choice:** Collapsed sidebar
**Notes:** Existing SPA routing pattern (navigate() + data-page) preserved. Zero new UI patterns needed.

---

## Tool/Skill Management UX

| Option | Description | Selected |
|--------|-------------|----------|
| Searchable table + inline expansion | Search input + click-to-expand row details (description, task_types, source) | ✓ |
| Enhance existing table | Add source badge + category columns. No search. | |
| Categorized card view | Grouped card grid by category. Needs category taxonomy on base class. | |

**User's choice:** Searchable table + inline expansion
**Notes:** ~50 tools and ~50 skills make flat unsorted tables unusable. Search is the highest-value addition. Source field added to API. Category derived client-side from _CODE_ONLY_TOOLS set.

---

## Claude's Discretion

- Guard decorator implementation pattern
- Mode detection and conditional rendering logic
- Search input styling
- Inline expansion UI details
- Error handling for gated features

## Deferred Ideas

- Sandboxed apps value proposition — deeper analysis needed on security vs. standard deployment
- Icon-only sidebar rail — future UX polish if standalone dashboard persists
- Marketplace tool browser — Phase 40 scope

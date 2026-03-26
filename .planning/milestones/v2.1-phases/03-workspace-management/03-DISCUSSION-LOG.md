# Phase 3: Workspace Management - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-24
**Phase:** 03-workspace-management
**Mode:** auto (advisor research + auto-select recommended defaults)
**Areas analyzed:** Add workspace flow, Remove workspace guards, Inline rename, Post-removal state

---

## Add Workspace Flow

### Button Placement

| Option | Description | Selected |
|--------|-------------|----------|
| "+" button inside tab bar | Appended in `ideRenderWorkspaceTabs()`, right-justified; requires lifting hide-if-single logic | auto |
| Floating "+" outside tab bar | Separate DOM element, preserves hide-if-single | |

**Auto-selected:** "+" button inside tab bar (recommended — VS Code convention, keeps workspace management in one DOM region)

### Modal Layout

| Option | Description | Selected |
|--------|-------------|----------|
| Single-panel (path + app shortcut) | Path input always shown, app dropdown below as shortcut; simpler HTML, fewer states | auto |
| Two-panel (radio toggle) | Radio toggle between path and app; matches spec literally but adds toggle state | |

**Auto-selected:** Single-panel (recommended — simpler, app dropdown auto-fills path field, one code path)

### Path Validation

| Option | Description | Selected |
|--------|-------------|----------|
| POST-returns-400 | Use existing POST /api/workspaces error handling; catch + toast | auto |
| Dedicated validate endpoint | GET /api/workspaces/validate?path=...; debounced on blur | |

**Auto-selected:** POST-returns-400 (recommended — WorkspaceRegistry.create() already validates, no new endpoint needed)

---

## Remove Workspace Guards

| Option | Description | Selected |
|--------|-------------|----------|
| `tab.modified` only | Checks editor unsaved files only; ignores CC/terminal state | |
| `tab.modified` + CC session count | Checks unsaved files AND open CC sessions via ccTabCount | auto |
| Full surface audit | Checks files + terminals + CC sessions; most complete but most complex | |

**Auto-selected:** `tab.modified` + CC session count (recommended — pragmatic middle ground; catches highest-value loss scenario with near-zero additional complexity)

**Notes:** Last-workspace protection is a hard frontend gate (disable close button when <=1). Dialog uses confirm() matching existing ideCloseTab pattern.

---

## Inline Rename

| Option | Description | Selected |
|--------|-------------|----------|
| Click active tab label | Click label span on already-active tab enters rename; matches success criteria literally | auto |
| Double-click any tab | Unambiguous intent but requires second click; touch-device gap | |
| Right-click context menu | Zero accidental renames but extra DOM; could bundle with remove | |

**Auto-selected:** Click active tab label (recommended — success criteria says "clicking a workspace tab name"; wrap label in span, check active class)

**Notes:** Enter commits, Escape discards, blur commits (VS Code convention). Validation: trim, reject empty, maxlength 64.

---

## Post-Removal State Management

| Option | Description | Selected |
|--------|-------------|----------|
| Eager cleanup | Prune all localStorage, close all WSs including CC sessions | |
| Lazy cleanup | Remove from list only, let everything die naturally | |
| Selective cleanup | Close terminal WSs, prune ws_{id}_* localStorage, leave CC sessions | auto |

**Auto-selected:** Selective cleanup (recommended — frees PTY resources without killing in-flight CC tasks; scoped key pruning prevents localStorage bloat)

### Active Workspace After Removal

| Option | Description | Selected |
|--------|-------------|----------|
| Adjacent tab (prev - 1, else first) | Matches browser/VS Code tab close convention | auto |
| Always first remaining | Simpler but jarring when removing mid-list | |

**Auto-selected:** Adjacent tab (recommended — matches established tab-bar conventions)

---

## Claude's Discretion

- Close button visual style on workspace tabs
- "+" button styling
- Modal input placeholder text and help copy
- Toast message wording
- Animation/transition for tab add/remove
- App dropdown detail level (status vs names only)

## Deferred Ideas

- Workspace-specific settings/preferences — future milestone
- Drag-to-reorder workspace tabs — future enhancement
- Workspace color coding or icons — future enhancement
- Bulk workspace import — future milestone
- Server-side last-workspace guard — add if needed

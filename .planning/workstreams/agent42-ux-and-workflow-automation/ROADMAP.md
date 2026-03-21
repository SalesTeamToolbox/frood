# Roadmap: Agent42 UX & Workflow Automation

## Overview

Fix the memory pipeline so Claude's recall and learn hooks produce visible feedback in VS Code, then make GSD the automatic methodology for multi-step coding tasks, then polish Agent42 into a proper desktop app experience, and finally surface GSD state in the dashboard status bar. Each phase delivers a coherent capability that the user can observe and verify before moving on.

## Phases

**Phase Numbering:**
- Integer phases (1, 2, 3): Planned milestone work
- Decimal phases (2.1, 2.2): Urgent insertions (marked with INSERTED)

Decimal phases appear between their surrounding integers in numeric order.

- [ ] **Phase 1: Memory Pipeline** - Fix recall and learn hooks so memory operations are visible in VS Code chat stream
- [x] **Phase 2: GSD Auto-Activation** - Make GSD the default methodology for multi-step coding tasks when Agent42 is installed (completed 2026-03-21)
- [x] **Phase 3: Desktop App Experience** - PWA manifest and desktop shortcut so Agent42 opens as a chromeless app (completed 2026-03-21)
- [ ] **Phase 4: Dashboard GSD Integration** - Status bar shows active workstream and current phase via WebSocket

## Phase Details

### Phase 1: Memory Pipeline
**Goal**: Memory recall and learn hooks produce visible, actionable feedback in VS Code Claude Code chat stream
**Depends on**: Nothing (first phase)
**Requirements**: MEM-01, MEM-02, MEM-03, MEM-04
**Success Criteria** (what must be TRUE):
  1. When a user submits a prompt, relevant memories appear in the VS Code chat stream before Claude responds
  2. When a session ends, learning confirmations appear in the VS Code chat stream showing what was captured
  3. Both recall and learn hooks complete the full pipeline end-to-end without silent failures
  4. Memory hook activity (recall queries, learn captures) is visible in Agent42 server logs
**Plans:** 2/3 plans executed

**Plan list:**

- [x] 01-01-PLAN.md — Fix recall hook limits and learn hook filtering (MEM-01, MEM-02)
- [x] 01-02-PLAN.md — Server-side logging and --health memory diagnostics (MEM-04)
- [x] 01-03-PLAN.md — End-to-end pipeline tests (MEM-03)

### Phase 2: GSD Auto-Activation
**Goal**: GSD methodology activates automatically for multi-step coding and planning tasks — users get structured workflow without manual invocation
**Depends on**: Phase 1
**Requirements**: GSD-01, GSD-02, GSD-03, GSD-04
**Success Criteria** (what must be TRUE):
  1. For a multi-step coding task (e.g., "build a Flask app"), Claude automatically proposes GSD workflow without the user asking
  2. For a trivial task (e.g., "what does range() do?"), Claude skips GSD and answers directly
  3. CLAUDE.md contains a GSD section that establishes it as the default process when Agent42 is installed
  4. The always-on skill is active and instructs Claude to recognize when GSD applies
**Plans:** 2/2 plans complete

**Plan list:**

- [x] 02-01-PLAN.md — Always-on GSD skill + CLAUDE.md methodology section (GSD-01, GSD-02)
- [x] 02-02-PLAN.md — Context-loader hook GSD detection + smart skip logic (GSD-03, GSD-04)

### Phase 3: Desktop App Experience
**Goal**: Users can install Agent42 as a PWA and launch it from the desktop without a browser address bar or tabs
**Depends on**: Phase 1
**Requirements**: APP-01, APP-02, APP-03, APP-04
**Success Criteria** (what must be TRUE):
  1. User can click "Install App" in the browser and add Agent42 to their desktop/taskbar as a PWA
  2. User can run `setup.sh create-shortcut` and get a platform-appropriate desktop shortcut (Windows .lnk, macOS .app, Linux .desktop)
  3. Opening the shortcut launches Agent42 in chromeless mode — no address bar, tab bar, or browser chrome visible
  4. The installed PWA shows correct Agent42 branding (name, icon, theme color) in OS taskbar and app switcher
**Plans:** 2/2 plans complete

**Plan list:**

- [x] 03-01-PLAN.md — PWA manifest, icon generation, and index.html wiring (APP-01, APP-04)
- [x] 03-02-PLAN.md — Desktop shortcut command in setup.sh (APP-02, APP-03)

### Phase 4: Dashboard GSD Integration
**Goal**: Agent42 dashboard status bar shows active GSD workstream and phase in real-time
**Depends on**: Phase 2
**Requirements**: DASH-01, DASH-02
**Success Criteria** (what must be TRUE):
  1. The dashboard status bar displays the name of the currently active GSD workstream and phase number when a workstream is in progress
  2. When the user advances to a new phase in GSD, the status bar updates within one WebSocket heartbeat cycle without a page refresh
**Plans:** 1 plan

**Plan list:**

- [ ] 04-01-PLAN.md — SystemHealth GSD fields + sidebar indicator (DASH-01, DASH-02)

## Progress

**Execution Order:**
Phases execute in numeric order: 1 → 2 → 3 → 4

| Phase | Plans Complete | Status | Completed |
|-------|----------------|--------|-----------|
| 1. Memory Pipeline | 3/3 | Complete |  |
| 2. GSD Auto-Activation | 2/2 | Complete    | 2026-03-21 |
| 3. Desktop App Experience | 2/2 | Complete   | 2026-03-21 |
| 4. Dashboard GSD Integration | 0/1 | Not started | - |

---
*Roadmap created: 2026-03-20*
*Workstream: agent42-ux-and-workflow-automation*

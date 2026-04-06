# Phase 37: Standalone Dashboard - Context

**Gathered:** 2026-04-03
**Status:** Ready for planning

<domain>
## Phase Boundary

Create simplified dashboard for standalone mode (Claude Code only). When running without Paperclip, provide a focused control panel for settings management, tool/skill management, basic agent monitoring, and provider configuration. This is a transitional surface — long-term, all UI consolidates into Paperclip.

Requirements: STANDALONE-01, STANDALONE-02, STANDALONE-03, STANDALONE-04.

</domain>

<decisions>
## Implementation Decisions

### Simplification Strategy
- **D-01:** Runtime feature flag approach — add `STANDALONE_MODE` env var + `--standalone` CLI flag that gates ~65 non-essential backend routes with a guard decorator returning 404
- **D-02:** Frontend (`app.js`) checks mode at startup via `/health` endpoint and conditionally renders only the relevant nav items and sections
- **D-03:** One codebase serves both standalone and full mode — no new server files, no frontend rebuild
- **D-04:** Existing `sidecar_enabled` gate pattern (from Phase 36) used as the architectural model for the standalone mode gate

### Feature Retention
- **D-05:** Operational Core feature set — 4 required areas + 6 retained features in standalone mode
- **D-06:** Retained features (beyond 4 required): memory browser, approval gates, CC auth/session status, learning/effectiveness stats, rewards overview (read-only), device management
- **D-07:** Removed features (gated off in standalone): chat interface, IDE/Monaco editor, GSD workstream tracking, task/project boards, repo management, sandboxed apps
- **D-08:** Retention criteria: keep features that require async human input, visual data presentation with no CLI equivalent, or configuration with server-side side effects

### Navigation & Layout
- **D-09:** Collapsed sidebar approach — keep existing sidebar pattern, app.js hides gated nav items in standalone mode so sidebar naturally shrinks from ~11 to ~10 items
- **D-10:** Existing `navigate()` + `data-page` SPA routing pattern preserved — zero new UI patterns
- **D-11:** No structural layout changes — sidebar, topbar, content area architecture stays the same

### Tool/Skill Management UX
- **D-12:** Searchable table with inline expansion — add search/filter input above each table (tools, skills) that filters client-side on name + description
- **D-13:** Row click expands inline detail panel showing: full description, task_types badges, source (builtin/mcp/plugin)
- **D-14:** Add `source` field to `ToolRegistry.list_tools()` API response (1-line backend change)
- **D-15:** Category derived client-side from `_CODE_ONLY_TOOLS` name set — no backend category taxonomy needed

### Claude's Discretion
- Guard decorator implementation pattern and naming
- Exact conditional rendering logic in app.js for mode detection
- Search input styling and placement
- Inline expansion animation/transition details
- Error states for gated features (404 response handling in frontend)
- Category badge styling and color scheme

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/workstreams/dashboard-unification/ROADMAP.md` — Phase 37 success criteria (4 acceptance tests), milestone context
- `.planning/workstreams/dashboard-unification/STATE.md` — Current progress, Phase 36 decisions carried forward

### Prior phase context (Phase 36 dependency)
- `.planning/phases/36-paperclip-integration-core/36-CONTEXT.md` — Sidecar mode architecture, integration patterns, D-09 through D-12

### Existing codebase (key files to read)
- `dashboard/server.py` — Standalone dashboard REST API (5,836 lines, 100+ endpoints). Target for guard decorator on ~65 routes.
- `dashboard/frontend/dist/app.js` — Frontend SPA source (8,589 lines, readable vanilla JS). Contains `renderTools()`, `renderSkills()`, sidebar nav, all renderers. Target for mode-aware conditional rendering.
- `dashboard/frontend/dist/style.css` — Stylesheet for all dashboard components
- `dashboard/frontend/dist/index.html` — SPA entry point
- `dashboard/sidecar.py` — Sidecar mode server (727 lines). Reference for mode-gating pattern.
- `core/config.py` — Settings dataclass. Where `standalone_mode` field will be added.
- `dashboard/auth.py` — Authentication utilities shared by both modes
- `dashboard/websocket_manager.py` — WebSocket management (used by retained features)

### Architecture decisions (from memory)
- Dashboard consolidation plan: standalone dashboard is transitional, all UI eventually moves to Paperclip
- Agent42 as intelligence layer for Paperclip (informs why standalone mode is minimal)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `dashboard/server.py` — All 4 required endpoint groups already exist and work: `/api/settings/*`, `/api/tools`, `/api/skills`, `/api/agents/*`, `/api/providers`
- `dashboard/frontend/dist/app.js` — `renderTools()` and `renderSkills()` already render tables with enable/disable toggles. `renderAgents()`, `renderSettings()` exist.
- `dashboard/sidecar.py` — `sidecar_enabled` gate pattern is the architectural model for `standalone_mode`
- `/health` endpoint already returns mode information — extend with standalone_mode flag

### Established Patterns
- **Mode gating:** Phase 36 established `sidecar_enabled` boolean that switches between `create_app()` and `create_sidecar_app()`. Phase 37 follows same pattern with runtime route gating.
- **SPA routing:** `navigate()` function + `data-page` attributes + `renderers` map. Mode-aware rendering hooks into this.
- **Tool registry:** `ToolRegistry.list_tools()` returns `{name, description, enabled}`. Needs `source` field added.
- **Settings config:** Frozen `Settings` dataclass in `core/config.py` with `from_env()` factory. New `standalone_mode` field follows existing pattern.
- **Frontend tables:** Existing table pattern with toggle switches. Search input and row expansion are additive.

### Integration Points
- `agent42.py` — CLI flag parsing, mode detection at startup
- `core/config.py` — `Settings.standalone_mode` field + `.env.example` update
- `dashboard/server.py` — Guard decorator applied to gated routes
- `dashboard/frontend/dist/app.js` — Mode check at startup, conditional nav rendering, search + expansion on tools/skills pages
- `/health` endpoint — Reports standalone_mode status for frontend consumption

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

- **Sandboxed apps value proposition** — Re-evaluate whether sandboxed apps add meaningful security for AI agentic use beyond standard app deployment with CLI/API wrappers. The current "sandbox" provides path isolation and process lifecycle but no OS-level isolation (containers, seccomp, namespaces). Deeper analysis needed.
- **Icon-only sidebar rail** — VS Code-style narrow icon bar could maximize content area. Consider for a future UX polish pass if standalone dashboard persists longer than expected.
- **Marketplace-style tool browser** — Full browser with category sidebar, detail drawer, tabs for Tools/Skills/MCP. Phase 40 (Settings Consolidation) scope.

</deferred>

---

*Phase: 37-standalone-dashboard*
*Context gathered: 2026-04-03*

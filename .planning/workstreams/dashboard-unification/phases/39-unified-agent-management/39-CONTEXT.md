# Phase 39: Unified Agent Management - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Single interface to monitor and control agents from both Agent42 and Paperclip. Unified view of agent performance metrics across both systems. Consistent agent configuration interface regardless of deployment mode. Shared agent templates work in both Paperclip and standalone modes.

Requirements: AGENT-01, AGENT-02, AGENT-03, AGENT-04.

</domain>

<decisions>
## Implementation Decisions

### Agent Data Unification
- **D-01:** Aggregated view — Agent42 and Paperclip agents shown in a single merged list with source badges ("Agent42" / "Paperclip"). Filter controls for source and status.
- **D-02:** New backend endpoint `GET /api/agents/unified` — fetches Agent42 agents locally + proxies to Paperclip API for its agents, merges and returns combined list. Frontend makes one fetch call.
- **D-03:** Agent42 agents are fully editable in the unified view. Paperclip agents are read-only with a "Manage in Paperclip" deep link for mutations.

### Monitoring & Metrics View
- **D-04:** Enhanced agent cards showing: status dot, tier badge, source badge, success rate %, run count, last active time (relative), and 7-day activity sparkline. Click expands to full detail.
- **D-05:** Summary stats row at top of page: Total agents, Active count, Average success rate, Total tokens consumed. Follows existing `stats-row` pattern already in `renderAgents()`.
- **D-06:** Agent detail view shows full metrics from both systems — Agent42 performance data (score, tier, tasks, success rate) and Paperclip effectiveness data where available.

### Control Actions
- **D-07:** Agent42 agents retain full control actions: start, stop, delete, tier override, create, edit.
- **D-08:** Paperclip agents shown as read-only — status, metrics, and config visible. Control actions (start/stop/delete/edit) deep link to Paperclip's native UI.
- **D-09:** Agent creation form polished with source badge showing "Agent42" to clarify ownership. No new form fields — existing structure (name, description, provider, model, schedule, tools, skills, max iterations) kept as-is.

### Template Sharing
- **D-10:** Templates remain Agent42-native. Template gallery visible in both modes, always creates Agent42 agents.
- **D-11:** Template cards show which system the agent will be created in (always "Agent42").
- **D-12:** No cross-system template format needed — Paperclip has its own agent creation flow.

### Claude's Discretion
- Sparkline rendering approach (CSS, canvas, or SVG)
- Exact card layout and spacing adjustments for enhanced metrics
- Loading/skeleton states for the unified endpoint
- Error handling when Paperclip API is unreachable (graceful degradation — show Agent42 agents only with a banner)
- Source badge styling and color scheme
- Activity sparkline time granularity (hourly vs daily buckets)
- Deep link URL format for Paperclip agent management

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/workstreams/dashboard-unification/ROADMAP.md` — Phase 39 success criteria (4 acceptance tests)

### Prior phase context (dependencies)
- `.planning/phases/36-paperclip-integration-core/36-CONTEXT.md` — Sidecar REST API patterns (D-09), Paperclip auth handling (D-10), WebSocket for real-time (D-12)
- `.planning/phases/37-standalone-dashboard/37-CONTEXT.md` — Standalone mode flag (D-01), same codebase both modes (D-03), sidebar pattern (D-09)
- `.planning/workstreams/dashboard-unification/phases/38-provider-ui-updates/38-CONTEXT.md` — Dynamic model dropdown (D-17-D-20), provider status endpoint pattern (D-12), lazy-load pattern (D-06)

### Existing codebase (key files to read)
- `core/agent_manager.py` — `AgentConfig` dataclass (line 250), `AgentManager` class (line 319), `AGENT_TEMPLATES` dict (line 191), `PROVIDER_MODELS`, `/api/agents/models` endpoint
- `core/agent_runtime.py` — `AgentRuntime` class (line 32), agent execution lifecycle
- `dashboard/server.py` — Agent REST endpoints (lines 4440-4610): CRUD, start/stop, status, log, performance, reward-tier
- `dashboard/frontend/dist/app.js` — `renderAgents()` (line 2326), `_renderAgentCards()` (line 2340), `agentShowDetail()` (line 2482), `agentShowCreate()` (line 2388), `agentShowTemplates()` (line 2442), stats-row pattern (line 2371)
- `dashboard/frontend/dist/style.css` — Agent card CSS, badge-tier, health-dot classes
- `plugins/agent42-paperclip/src/ui/AgentEffectivenessTab.tsx` — Paperclip effectiveness UI component
- `plugins/agent42-paperclip/src/client.ts` — Agent42Client for sidecar communication

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `renderAgents()` + `_renderAgentCards()` — existing agent card grid with status dots, tier badges, tool/skill chips. Extend rather than rebuild.
- `agentShowDetail()` — full detail view with performance data, tier override controls. Add Paperclip-specific read-only variant.
- `stats-row` pattern — 4 stat cards at top of agents page already showing total/active/paused/runs. Extend with success rate.
- `agentShowTemplates()` + `agentCreateFromTemplate()` — template gallery and one-click creation. Add source badge.
- `/api/agents/{id}/performance` endpoint — returns tier, score, task_count, success_rate. Reuse for unified metrics.
- `health-dot` CSS classes — `h-ok`, `h-auth_error`, `h-error`, `h-unavailable` for status indicators.
- `badge-tier` CSS — tier-colored badges already rendered on cards and detail views.

### Established Patterns
- **Agent card grid:** `agents-grid` CSS class, `agent-card` divs with header/desc/meta sections.
- **Lazy-load pattern:** `if (!state.X) { loadX().then(render); return loading_html; }` — use for unified agent list.
- **XSS safety:** All user-facing data through `esc()` helper function.
- **Stats row:** `stats-row > stat-card > stat-label + stat-value` pattern at top of page.
- **Mode awareness:** `state.standaloneMode` boolean from `/health` endpoint — conditionally render Paperclip features.

### Integration Points
- `dashboard/server.py` — New endpoint: `GET /api/agents/unified` (proxy to Paperclip + merge)
- `dashboard/frontend/dist/app.js` — Refactor `renderAgents()` to use unified endpoint, add source badges, enhance cards, sparklines
- `dashboard/frontend/dist/style.css` — Badge variants for source (Agent42/Paperclip), sparkline styles
- Paperclip sidecar API — Need to discover/document agent list endpoint for proxy

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 39-unified-agent-management*
*Context gathered: 2026-04-04*

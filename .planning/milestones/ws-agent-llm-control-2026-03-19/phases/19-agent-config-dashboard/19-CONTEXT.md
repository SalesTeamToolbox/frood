# Phase 19: Agent Config Dashboard - Context

**Gathered:** 2026-03-07
**Status:** Ready for planning

<domain>
## Phase Boundary

Dashboard UI for viewing and modifying LLM routing. Settings page gets a new "LLM Routing" tab for global defaults (L1, L2, critic, fallback). Agents page gets per-agent routing controls in the detail view with model chips on the grid cards. Changes take effect on next agent dispatch without server restart. Backend API endpoints already exist from Phase 18 (`/api/agent-routing/*`, `/api/available-models`).

</domain>

<decisions>
## Implementation Decisions

### Settings Page Layout
- New "LLM Routing" tab added to Settings page alongside existing tabs (Providers, Security, Orchestrator, Storage & Paths)
- Four role-based dropdowns: Primary (L1), Premium (L2), Critic, Fallback — each shows current effective model
- Compact chain summary below dropdowns: "Routing: StrongWall (L1) -> Cerebras/Groq (Fallback) -> Gemini Pro (L2)" — updates live as dropdowns change
- Update existing Providers tab "How Model Routing Works" and "Fallback Chain" info boxes to use L1/L2/Fallback terminology and link to the new LLM Routing tab

### Model Selector UX
- Dropdowns grouped by tier using optgroup headers: "L1 Models", "Fallback Models", "L2 Premium Models"
- Only models with configured API keys appear (Phase 18 `/api/available-models` already filters)
- Health status dot indicator per model: green (healthy), yellow (degraded), red (unhealthy) — uses existing health check data
- Inherited values shown in muted/gray text with small "inherited from default" label
- Overridden values shown in normal text with a reset (X) button to clear the override
- First option in every dropdown is "Use default" (or "Inherit") — selecting it clears the override for that role

### Agent Detail Routing
- New "LLM Routing" section in agent detail view, below existing task types/skills sections
- Same dropdown UX as Settings page (grouped by tier, health dots, inherited indicators)
- Compact effective chain per agent: "Effective: StrongWall K2.5 (overridden) -> Cerebras (inherited) -> Gemini Pro (inherited)"
- Agent cards on grid view show a small model chip (e.g., "StrongWall K2.5" or "inherited") below task types
- Only agents with existing profiles in ProfileLoader get routing controls — `_default` key is managed via Settings page, not Agents page

### Save & Feedback Behavior
- Explicit save button (consistent with existing API keys pattern in Settings)
- Toast message on save: "Routing updated. Takes effect on next dispatch."
- "Reset to defaults" button on both pages — Settings gets "Reset Global Defaults", agent detail gets "Reset to Inherited" — both with confirmation toast
- Unsaved changes highlight the Save button and show "Unsaved changes" warning when navigating away (dirty state tracking)

### Claude's Discretion
- Exact CSS styling for the new LLM Routing tab and routing section
- How to render the compact chain summary (simple text vs styled badges)
- Dropdown component implementation details (native select vs custom)
- Exact positioning of model chip on agent cards
- How to handle edge case where no models are available for a tier group

</decisions>

<specifics>
## Specific Ideas

- Phase 18 API returns both `overrides` (explicitly set) and `effective` (merged with defaults) — use this to power the inherited vs overridden visual distinction
- The `_default` key in AgentRoutingStore maps to Settings page global defaults — same API endpoint, just different profile key
- Settings page LLM Routing tab writes to `_default` profile; Agents page writes to the specific profile name
- The existing "How Model Routing Works" box in Providers tab still mentions "5. Free Defaults" — should say "L1/Fallback/L2" to match new architecture

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `renderSettingsPanel()` (app.js:4129): Tab-based settings rendering pattern — new LLM Routing tab follows same structure
- `settingSecret()` helper: Renders form fields with labels and help text — similar pattern for routing dropdowns
- `renderAgentDetail()` (app.js:2278): Agent detail view — add routing section after existing content
- `renderAgents()` (app.js:2204): Agent grid with cards — add model chip to card template
- `toast()` function: Existing toast notification system for save feedback
- `state.settingsTab` / tab switching: Existing tab navigation pattern to extend

### Established Patterns
- Dashboard is a vanilla JS SPA in `dashboard/frontend/dist/app.js` (4664 lines)
- All HTML rendered via template literals with `innerHTML` assignment
- XSS protection via `esc()` helper on all interpolated values
- State managed in global `state` object with render functions
- API calls via `api()` helper function (handles auth, JSON parsing)
- Save pattern: collect edits in `state.*Edits`, POST/PUT on save button click, reload data, toast

### Integration Points
- `GET /api/agent-routing` — list all profiles with effective configs
- `GET /api/agent-routing/{profile}` — single profile with overrides + effective
- `PUT /api/agent-routing/{profile}` — set overrides (body: {primary, critic, fallback})
- `DELETE /api/agent-routing/{profile}` — reset profile overrides
- `GET /api/available-models` — models grouped by tier with health status
- Settings page tabs array (app.js:~4107): add new tab entry
- `renderSettingsPanel()` panels object (app.js:~4138): add new panel renderer

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 19-agent-config-dashboard*
*Context gathered: 2026-03-07*

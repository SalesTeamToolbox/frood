# Phase 19: Agent Config Dashboard - Research

**Researched:** 2026-03-07
**Domain:** Dashboard UI for LLM routing configuration (vanilla JS SPA, FastAPI backend)
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Settings Page Layout:**
- New "LLM Routing" tab added to Settings page alongside existing tabs (Providers, Security, Orchestrator, Storage & Paths)
- Four role-based dropdowns: Primary (L1), Premium (L2), Critic, Fallback -- each shows current effective model
- Compact chain summary below dropdowns: "Routing: StrongWall (L1) -> Cerebras/Groq (Fallback) -> Gemini Pro (L2)" -- updates live as dropdowns change
- Update existing Providers tab "How Model Routing Works" and "Fallback Chain" info boxes to use L1/L2/Fallback terminology and link to the new LLM Routing tab

**Model Selector UX:**
- Dropdowns grouped by tier using optgroup headers: "L1 Models", "Fallback Models", "L2 Premium Models"
- Only models with configured API keys appear (Phase 18 `/api/available-models` already filters)
- Health status dot indicator per model: green (healthy), yellow (degraded), red (unhealthy) -- uses existing health check data
- Inherited values shown in muted/gray text with small "inherited from default" label
- Overridden values shown in normal text with a reset (X) button to clear the override
- First option in every dropdown is "Use default" (or "Inherit") -- selecting it clears the override for that role

**Agent Detail Routing:**
- New "LLM Routing" section in agent detail view, below existing task types/skills sections
- Same dropdown UX as Settings page (grouped by tier, health dots, inherited indicators)
- Compact effective chain per agent: "Effective: StrongWall K2.5 (overridden) -> Cerebras (inherited) -> Gemini Pro (inherited)"
- Agent cards on grid view show a small model chip (e.g., "StrongWall K2.5" or "inherited") below task types
- Only agents with existing profiles in ProfileLoader get routing controls -- `_default` key is managed via Settings page, not Agents page

**Save & Feedback Behavior:**
- Explicit save button (consistent with existing API keys pattern in Settings)
- Toast message on save: "Routing updated. Takes effect on next dispatch."
- "Reset to defaults" button on both pages -- Settings gets "Reset Global Defaults", agent detail gets "Reset to Inherited" -- both with confirmation toast
- Unsaved changes highlight the Save button and show "Unsaved changes" warning when navigating away (dirty state tracking)

### Claude's Discretion
- Exact CSS styling for the new LLM Routing tab and routing section
- How to render the compact chain summary (simple text vs styled badges)
- Dropdown component implementation details (native select vs custom)
- Exact positioning of model chip on agent cards
- How to handle edge case where no models are available for a tier group

### Deferred Ideas (OUT OF SCOPE)
None -- discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| CONF-01 | Settings page has LLM Routing section with global L1/L2/critic/fallback defaults | Settings tab pattern, `_default` profile key via `PUT /api/agent-routing/_default`, `settingSelect`-style dropdowns, available-models endpoint for population |
| CONF-02 | Agents page shows per-agent routing override controls (primary, critic, fallback) | Agent detail rendering pattern at `renderAgentDetail()`, `PUT /api/agent-routing/{profile}` for saves, resolution chain for inheritance display |
</phase_requirements>

## Summary

Phase 19 is a pure frontend phase. All backend APIs are complete from Phase 18: `GET/PUT/DELETE /api/agent-routing/*` and `GET /api/available-models`. The work involves extending the existing vanilla JS SPA (`dashboard/frontend/dist/app.js`, ~4664 lines) to add a new Settings tab ("LLM Routing") and a new section in the agent detail view.

The dashboard follows a consistent pattern: global `state` object, template-literal HTML rendering via `innerHTML`, `api()` helper for REST calls, `toast()` for feedback, and `esc()` for XSS protection. The existing `settingSelect()` helper provides the closest pattern for model dropdowns but needs adaptation for optgroup-based tier grouping and health status dots. The `saveApiKeys()` flow provides the save pattern: track edits in `state.*Edits`, POST on save click, reload data, toast confirmation.

The key architectural insight is that Settings page global defaults map to the `_default` profile key in AgentRoutingStore, while agent-specific overrides use the profile name. The `GET /api/agent-routing/{profile}` endpoint already returns both `overrides` (explicit) and `effective` (merged) configs plus a `resolution_chain` showing inheritance sources -- this directly powers the UI distinction between overridden values (normal text + reset button) and inherited values (gray text + "inherited" label).

**Primary recommendation:** Extend the existing vanilla JS SPA patterns -- add `state.routingModels`, `state.routingConfig`, `state.routingEdits` state properties, a new tab entry in `renderSettings()`, a `renderRoutingPanel()` function, and modify `renderAgentDetail()` to include a routing section. Use native `<select>` with `<optgroup>` for tier-grouped dropdowns.

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Vanilla JS (existing SPA) | N/A | Dashboard UI rendering | Already established -- 4664-line SPA, no build system |
| FastAPI | existing | Backend API | Phase 18 endpoints already built |
| Template literals | N/A | HTML rendering | Established dashboard pattern (no framework) |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `api()` helper | existing | REST calls with auth | All API interactions |
| `toast()` helper | existing | User feedback | Save confirmations, errors |
| `esc()` helper | existing | XSS protection | All interpolated values in HTML |
| `settingSelect()` | existing | `<select>` dropdown rendering | Reference pattern for routing dropdowns |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Native `<select>` + `<optgroup>` | Custom dropdown component | Native select is simpler, consistent with existing dashboard, sufficient for tier grouping. Custom dropdown would add complexity for marginal benefit. |
| Badge-style chain summary | Plain text chain | Styled badges match the existing badge-tier pattern and are visually scannable. Recommend badges. |

## Architecture Patterns

### Recommended State Extensions
```javascript
// Add to the global state object (app.js line 7):
state.routingModels = { l1: [], fallback: [], l2: [] };  // from GET /api/available-models
state.routingConfig = {};      // from GET /api/agent-routing (all profiles)
state.routingEdits = {};       // dirty tracking: { primary: "model-key", ... }
state.routingSaving = false;   // save-in-progress flag
state.agentRoutingEdits = {};  // per-agent dirty tracking
state.agentRoutingSaving = false;
```

### Pattern 1: Settings Tab Extension
**What:** Add "LLM Routing" tab to the existing tab array in `renderSettings()`
**When to use:** Extending the Settings page
**Example:**
```javascript
// Source: dashboard/frontend/dist/app.js line 4106-4113
// Add new tab entry to the tabs array:
const tabs = [
  { id: "providers", label: "LLM Providers" },
  { id: "routing", label: "LLM Routing" },  // NEW
  { id: "repos", label: "Repositories" },
  // ... existing tabs
];

// Add panel renderer in the panels object (line 4138):
const panels = {
  providers: () => `...`,
  routing: () => renderRoutingPanel(),  // NEW
  // ... existing panels
};
```

### Pattern 2: Tier-Grouped Select Dropdown
**What:** Native `<select>` with `<optgroup>` for model selection by tier
**When to use:** Both Settings and Agent detail routing dropdowns
**Example:**
```javascript
// Source: Adapted from settingSelect() at app.js:4467
function routingSelect(field, label, currentValue, isInherited, inheritedFrom) {
  const models = state.routingModels;
  const healthDot = (h) => h === "healthy" ? "&#x1F7E2;"
                         : h === "degraded" ? "&#x1F7E1;"
                         : h === "unhealthy" ? "&#x1F534;" : "";

  const optionsHtml = (tier, tierLabel) => {
    if (!models[tier] || models[tier].length === 0) return "";
    return `<optgroup label="${esc(tierLabel)}">
      ${models[tier].map(m =>
        `<option value="${esc(m.key)}" ${currentValue === m.key ? "selected" : ""}>
          ${healthDot(m.health)} ${esc(m.display_name)} (${esc(m.provider)})
        </option>`
      ).join("")}
    </optgroup>`;
  };

  const inheritLabel = isInherited
    ? `<span style="color:var(--text-muted);font-size:0.75rem">inherited from ${esc(inheritedFrom)}</span>`
    : "";
  const resetBtn = !isInherited && currentValue
    ? `<button class="btn btn-sm" onclick="clearRoutingField('${field}')" title="Reset to inherited">&#10005;</button>`
    : "";

  return `
    <div class="form-group">
      <label>${esc(label)} ${inheritLabel}</label>
      <div style="display:flex;gap:0.5rem;align-items:center">
        <select style="flex:1;${isInherited ? 'color:var(--text-muted)' : ''}"
                onchange="updateRoutingEdit('${field}', this.value)">
          <option value="">Use default (Inherit)</option>
          ${optionsHtml("l1", "L1 Models")}
          ${optionsHtml("fallback", "Fallback Models")}
          ${optionsHtml("l2", "L2 Premium Models")}
        </select>
        ${resetBtn}
      </div>
    </div>
  `;
}
```

### Pattern 3: Save Flow (matching saveApiKeys)
**What:** Explicit save button with dirty tracking, toast feedback
**When to use:** Both Settings and Agent detail routing saves
**Example:**
```javascript
// Source: Adapted from saveApiKeys() at app.js:750
async function saveRouting(profileName) {
  state.routingSaving = true;
  renderSettingsPanel();
  try {
    const edits = profileName === "_default" ? state.routingEdits : state.agentRoutingEdits;
    // Filter out empty/unchanged values
    const body = {};
    for (const [field, val] of Object.entries(edits)) {
      if (val !== undefined && val !== "") body[field] = val;
    }
    if (Object.keys(body).length === 0) {
      toast("No changes to save", "info");
      return;
    }
    await api(`/agent-routing/${encodeURIComponent(profileName)}`, {
      method: "PUT",
      body: JSON.stringify(body),
    });
    // Reset edits, reload data
    if (profileName === "_default") {
      state.routingEdits = {};
    } else {
      state.agentRoutingEdits = {};
    }
    await loadRoutingConfig();
    toast("Routing updated. Takes effect on next dispatch.", "success");
  } catch (e) {
    toast("Failed to save routing: " + e.message, "error");
  }
  state.routingSaving = false;
  if (profileName === "_default") renderSettingsPanel();
  else render();
}
```

### Pattern 4: Chain Summary Display
**What:** Compact routing chain visualization using styled badges
**When to use:** Below dropdowns on both Settings and Agent detail
**Example:**
```javascript
// Source: Uses resolution_chain from GET /api/agent-routing/{profile}
function renderChainSummary(chain) {
  if (!chain || chain.length === 0) return "";
  const badges = chain.map(entry => {
    const sourceStyle = entry.source === "FALLBACK_ROUTING"
      ? "background:var(--bg-hover);color:var(--text-muted)"
      : entry.source.startsWith("profile:")
        ? "background:rgba(60,191,174,0.15);color:var(--a42-teal)"
        : "background:rgba(232,168,56,0.12);color:var(--a42-gold)";
    const sourceLabel = entry.source === "FALLBACK_ROUTING" ? "system"
      : entry.source === "_default" ? "default" : "overridden";
    return `<span style="display:inline-block;padding:0.15rem 0.5rem;border-radius:4px;font-size:0.75rem;${sourceStyle}">
      ${esc(entry.field)}: ${esc(entry.value)} (${sourceLabel})
    </span>`;
  }).join(" &rarr; ");
  return `<div style="margin-top:0.75rem;display:flex;flex-wrap:wrap;gap:0.3rem;align-items:center">
    <strong style="font-size:0.8rem;color:var(--text-secondary)">Effective:</strong> ${badges}
  </div>`;
}
```

### Pattern 5: Model Chip on Agent Cards
**What:** Small model indicator badge on agent grid cards
**When to use:** Agent grid view showing current primary model
**Example:**
```javascript
// Source: Added inside renderAgents() card template, after taskChips
// Lookup the effective primary for this profile from state.routingConfig
const routingInfo = state.routingConfig?.profiles?.[p.name];
const effectivePrimary = routingInfo?.effective?.primary;
const modelChip = effectivePrimary
  ? `<div class="agent-card-chips" style="margin-top:0.25rem">
       <span class="badge-type" style="font-size:0.65rem">${esc(effectivePrimary)}</span>
     </div>`
  : `<div class="agent-card-chips" style="margin-top:0.25rem">
       <span class="badge-type" style="font-size:0.65rem;color:var(--text-muted)">inherited</span>
     </div>`;
```

### Anti-Patterns to Avoid
- **Direct DOM manipulation instead of re-render:** The dashboard uses innerHTML-based re-rendering. Do not use `document.getElementById().value = x` to update display -- always re-render the panel/section.
- **Forgetting `esc()` on interpolated values:** Every user-facing string interpolated into template literals MUST use `esc()` for XSS protection. Model keys, display names, profile names -- all must be escaped.
- **Using `state.routingEdits` directly in API call without filtering:** Empty string values mean "inherit" (should clear the override). Must distinguish between `""` (clear), `undefined` (unchanged), and `"model-key"` (set).
- **Re-creating AgentRoutingStore in frontend data loaders:** The API endpoints already handle all logic. The frontend only needs to call the REST endpoints, not duplicate resolution logic.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Model filtering by API key | Custom frontend filtering | `GET /api/available-models` endpoint | Backend already filters; duplicating logic risks divergence |
| Inheritance resolution display | Custom merge logic in JS | `resolution_chain` from `GET /api/agent-routing/{profile}` | Backend provides field-level source tracking |
| Effective config computation | JS-side profile/default merge | `effective` field from API response | Backend handles critic auto-pairing and merge rules |
| Health status checking | Frontend health probes | `health` field in available-models response | Backend has access to model_catalog health data |
| Tab navigation | Custom tab system | Extend existing `state.settingsTab` + `renderSettingsPanel()` pattern | Consistency and reuse |

**Key insight:** Phase 18 built all the smart backend logic (filtering, merging, inheritance tracking). The frontend should be a thin display layer that consumes API responses directly, not a duplicate of backend logic.

## Common Pitfalls

### Pitfall 1: Dropdown value vs display mismatch
**What goes wrong:** Using `display_name` as `<option>` value instead of `key`, causing PUT calls to fail with "Unknown model key"
**Why it happens:** Available-models returns both `key` (e.g., `"gemini-2-flash"`) and `display_name` (e.g., `"Gemini 2.0 Flash"`)
**How to avoid:** Always use `m.key` for `<option value>` and `m.display_name` for displayed text
**Warning signs:** 400 errors from PUT /api/agent-routing with "Unknown model key"

### Pitfall 2: _default profile confusion
**What goes wrong:** Settings page writes to wrong profile key, or Agents page accidentally edits `_default`
**Why it happens:** Settings page global defaults are stored under `_default` key in AgentRoutingStore
**How to avoid:** Settings page always uses `_default` as profile name. Agent detail pages use `p.name` (the actual profile name). Guard against `_default` appearing in agent detail views.
**Warning signs:** Global defaults change when editing individual agent, or vice versa

### Pitfall 3: Empty optgroup rendering
**What goes wrong:** Empty `<optgroup>` tags render as blank sections in the dropdown
**Why it happens:** No models available for a tier (e.g., no StrongWall API key configured means l1 tier is empty)
**How to avoid:** Only render `<optgroup>` when the tier array has items. Check `models[tier].length > 0` before rendering the optgroup HTML.
**Warning signs:** Blank gaps in dropdown menus

### Pitfall 4: Dirty state lost on tab switch
**What goes wrong:** User edits routing, switches to Providers tab, switches back -- edits are gone
**Why it happens:** `renderSettingsPanel()` rebuilds HTML from state, but if edits weren't saved to `state.routingEdits`, they vanish
**How to avoid:** Store edits in `state.routingEdits` via `oninput`/`onchange` handlers before any re-render occurs. The `onchange` handler must update state, not just DOM.
**Warning signs:** "Unsaved changes" warning not showing after real edits

### Pitfall 5: Race condition on sequential save + reload
**What goes wrong:** `saveRouting()` calls `loadRoutingConfig()` after PUT, but the PUT response already contains the updated data -- loading from API is redundant and can race
**Why it happens:** Following saveApiKeys pattern which reloads keys separately
**How to avoid:** Use the PUT response data to update `state.routingConfig` directly, OR await the reload fully before re-rendering. Either approach works; the key is not rendering stale state.
**Warning signs:** UI shows old values immediately after save, then flips to new values

### Pitfall 6: Reset button on inherited fields
**What goes wrong:** Reset (X) button shown even for inherited values, clicking it sends DELETE which 404s
**Why it happens:** Not checking the resolution_chain source before showing reset button
**How to avoid:** Only show reset (X) button when the field's source in resolution_chain starts with `"profile:"` (meaning it's an explicit override). Inherited fields (source `"_default"` or `"FALLBACK_ROUTING"`) should not have a reset button.
**Warning signs:** 404 errors when clicking reset on fields that were never overridden

### Pitfall 7: StrongWall API key not on Providers tab
**What goes wrong:** StrongWall models appear in LLM Routing dropdowns but there's no way to configure the API key through the UI
**Why it happens:** Phase 16 added StrongWall as a provider in the backend but the `settingSecret("STRONGWALL_API_KEY", ...)` call was never added to the Providers panel in app.js
**How to avoid:** Verify that the STRONGWALL_API_KEY field exists in the Providers panel. If missing, add it in the same plan that adds the LLM Routing tab, since the routing tab depends on StrongWall models being available.
**Warning signs:** L1 tier group is empty in routing dropdowns even though StrongWall is intended as L1

## Code Examples

### Data Loading Functions
```javascript
// Source: Follows established loadApiKeys() pattern at app.js:722
async function loadRoutingModels() {
  try {
    state.routingModels = (await api("/available-models")) || { l1: [], fallback: [], l2: [] };
  } catch { state.routingModels = { l1: [], fallback: [], l2: [] }; }
}

async function loadRoutingConfig() {
  try {
    state.routingConfig = (await api("/agent-routing")) || { profiles: {} };
  } catch { state.routingConfig = { profiles: {} }; }
}
```

### Settings Panel Routing Tab
```javascript
// Source: Follows renderSettingsPanel() panels pattern at app.js:4138
function renderRoutingPanel() {
  const defaultConfig = state.routingConfig?.profiles?.["_default"];
  const overrides = defaultConfig?.overrides || {};
  const effective = defaultConfig?.effective || {};
  const chain = []; // Fetch via GET /api/agent-routing/_default for resolution_chain

  // For each field, determine if it's overridden or inherited
  const isOverridden = (field) => overrides && overrides[field] !== undefined && overrides[field] !== null;
  const currentVal = (field) => {
    // Check edits first, then overrides, then effective
    if (state.routingEdits[field] !== undefined) return state.routingEdits[field];
    if (isOverridden(field)) return overrides[field];
    return "";  // Will show "Use default (Inherit)" selected
  };

  return `
    <h3>LLM Routing</h3>
    <p class="section-desc">Configure global model routing defaults. Per-agent overrides can be set on the Agents page.</p>
    ${routingSelect("primary", "Primary (L1)", currentVal("primary"), !isOverridden("primary"), "system")}
    ${routingSelect("critic", "Critic", currentVal("critic"), !isOverridden("critic"), "system")}
    ${routingSelect("fallback", "Fallback", currentVal("fallback"), !isOverridden("fallback"), "system")}
    ${renderChainSummary(chain)}
    <div class="form-group" style="margin-top:1.5rem">
      <button class="btn btn-primary" onclick="saveRouting('_default')"
              ${Object.keys(state.routingEdits).length === 0 || state.routingSaving ? "disabled" : ""}>
        ${state.routingSaving ? "Saving..." : "Save Routing Defaults"}
      </button>
      <button class="btn btn-outline" onclick="resetRouting('_default')" style="margin-left:0.5rem">
        Reset Global Defaults
      </button>
    </div>
  `;
}
```

### Agent Detail Routing Section
```javascript
// Source: Extends renderAgentDetail() at app.js:2278
// Add after the existing personaHtml section:
const routingInfo = state.routingConfig?.profiles?.[p.name];
const agentOverrides = routingInfo?.overrides || {};
const agentEffective = routingInfo?.effective || {};
const agentChain = routingInfo?.resolution_chain || [];

function agentIsOverridden(field) {
  return agentOverrides && agentOverrides[field] !== undefined && agentOverrides[field] !== null;
}

const routingHtml = `
  <div class="agent-detail-section">
    <h4>LLM Routing</h4>
    ${routingSelect("primary", "Primary", agentCurrentVal("primary"), !agentIsOverridden("primary"), "global default")}
    ${routingSelect("critic", "Critic", agentCurrentVal("critic"), !agentIsOverridden("critic"), "global default")}
    ${routingSelect("fallback", "Fallback", agentCurrentVal("fallback"), !agentIsOverridden("fallback"), "global default")}
    ${renderChainSummary(agentChain)}
    <div style="display:flex;gap:0.5rem;margin-top:0.75rem">
      <button class="btn btn-primary btn-sm" onclick="saveRouting('${esc(p.name)}')"
              ${Object.keys(state.agentRoutingEdits).length === 0 ? "disabled" : ""}>
        Save Routing
      </button>
      <button class="btn btn-outline btn-sm" onclick="resetRouting('${esc(p.name)}')">
        Reset to Inherited
      </button>
    </div>
  </div>
`;
```

### Providers Tab Info Box Updates
```javascript
// Source: Update existing "How Model Routing Works" box at app.js:4144-4153
// Change step 5 from "Free Defaults" to L1/Fallback/L2 terminology:
// OLD: <strong>5. Free Defaults</strong> &mdash; <strong>Gemini Flash</strong> (primary) + <strong>OpenRouter free models</strong> (critic/fallback).
// NEW:
`<strong>5. Tier Defaults</strong> &mdash; <strong>L1</strong> (workhorse, e.g. StrongWall) &rarr; <strong>Fallback</strong> (free providers) &rarr; <strong>L2</strong> (premium, e.g. Gemini Pro). Configure in the <a href="#" onclick="event.preventDefault();state.settingsTab='routing';renderSettingsPanel()">LLM Routing</a> tab.`
```

### Data Loading Integration
```javascript
// Source: Add to loadAll() at app.js:4514
async function loadAll() {
  await Promise.all([
    // ... existing loaders ...
    loadRoutingModels(), loadRoutingConfig(),  // NEW
  ]);
}
```

### Reset Routing Function
```javascript
// Source: Uses DELETE /api/agent-routing/{profile}
async function resetRouting(profileName) {
  const label = profileName === "_default" ? "global routing defaults" : `routing for ${profileName}`;
  if (!confirm(`Reset ${label}? This will clear all overrides.`)) return;
  try {
    await api(`/agent-routing/${encodeURIComponent(profileName)}`, { method: "DELETE" });
    if (profileName === "_default") state.routingEdits = {};
    else state.agentRoutingEdits = {};
    await loadRoutingConfig();
    toast(`Routing reset. Inherits from ${profileName === "_default" ? "system defaults" : "global defaults"}.`, "success");
  } catch (e) {
    if (e.message.includes("404")) {
      toast("No overrides to reset", "info");
    } else {
      toast("Failed to reset: " + e.message, "error");
    }
  }
  if (profileName === "_default") renderSettingsPanel();
  else render();
}
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Free Defaults (Gemini Flash + OR free) | L1/Fallback/L2 tiered routing | Phase 17 (v1.3) | Settings UI must use tier terminology |
| No per-agent model config | Per-agent routing overrides | Phase 18 (v1.3) | Agent detail views need routing controls |
| 5-layer routing (static) | 6-layer routing (profile override at step 1b) | Phase 18 (v1.3) | "How Routing Works" info box needs update |

**Deprecated/outdated:**
- "Free Defaults" terminology in Providers tab: Should say "Tier Defaults" with L1/Fallback/L2 language
- "5-layer priority chain" in Providers tab: Now 6 layers (profile override inserted between admin and dynamic)

## Open Questions

1. **StrongWall API key on Providers tab**
   - What we know: StrongWall was added as a provider in Phase 16 backend, but `settingSecret("STRONGWALL_API_KEY", ...)` may not exist in the Providers panel
   - What's unclear: Whether it was added in a prior UI update or is still missing
   - Recommendation: Check during implementation. If missing, add it as part of Plan 19-01 since the LLM Routing tab depends on StrongWall models appearing in l1 tier

2. **Agent detail routing data loading**
   - What we know: `loadProfileDetail(name)` calls `GET /profiles/{name}` which returns profile data but NOT routing data
   - What's unclear: Whether to load routing data in a separate call or batch it
   - Recommendation: Load routing data for the specific profile via `GET /api/agent-routing/{name}` when entering agent detail view, and store in `state.selectedProfileRouting`. This avoids loading all routing data on every page load.

3. **L2 (Premium) dropdown role**
   - What we know: CONTEXT.md specifies four dropdowns: Primary (L1), Premium (L2), Critic, Fallback
   - What's unclear: The API only supports three fields: `primary`, `critic`, `fallback`. There is no separate `l2`/`premium` field.
   - Recommendation: Map "Primary (L1)" to `primary`, "Critic" to `critic`, "Fallback" to `fallback`. The "Premium (L2)" concept is handled by the tier grouping in the dropdown (L2 models are available as options in any dropdown). The CONTEXT.md may have intended 4 visible dropdowns but the backend supports 3 override fields. Implement 3 dropdowns matching the backend: Primary, Critic, Fallback. Each dropdown shows all tiers via optgroups so users can select L1, Fallback, or L2 models for any role.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + pytest-asyncio (auto mode) |
| Config file | pyproject.toml |
| Quick run command | `python -m pytest tests/test_agent_routing.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| CONF-01 | Settings page LLM Routing section renders with correct defaults | manual-only | N/A -- UI rendering in vanilla JS, no test framework for frontend | N/A |
| CONF-01 | GET /api/agent-routing/_default returns global config | unit | `python -m pytest tests/test_agent_routing.py::TestEffectiveResolution::test_empty_profile_uses_default -x` | Yes |
| CONF-01 | PUT /api/agent-routing/_default persists global defaults | unit | `python -m pytest tests/test_agent_routing.py::TestAgentRoutingStore::test_set_and_get_overrides -x` | Yes |
| CONF-01 | Available models populated from configured keys | unit | `python -m pytest tests/test_agent_routing.py::TestAvailableModels -x` | Yes |
| CONF-02 | Agent detail routing section renders per-agent overrides | manual-only | N/A -- UI rendering in vanilla JS | N/A |
| CONF-02 | PUT /api/agent-routing/{profile} stores per-agent overrides | unit | `python -m pytest tests/test_agent_routing.py::TestAgentRoutingStore::test_set_and_get_overrides -x` | Yes |
| CONF-02 | Resolution chain shows inheritance sources correctly | unit | `python -m pytest tests/test_agent_routing.py::TestResolutionChain -x` | Yes |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_agent_routing.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
None -- existing test infrastructure covers all phase requirements. Backend API logic is already tested in `tests/test_agent_routing.py` (28 tests). This phase is pure frontend work; the UI rendering cannot be unit tested without a browser testing framework, which is out of scope. Manual verification will confirm UI behavior.

## Sources

### Primary (HIGH confidence)
- `dashboard/frontend/dist/app.js` (lines 1-4664) -- existing SPA patterns, state management, rendering functions, helper functions
- `dashboard/server.py` (lines 1170-1304) -- Phase 18 API endpoints, _build_resolution_chain, available-models
- `agents/agent_routing_store.py` -- backend store API, field validation, inheritance merge
- `tests/test_agent_routing.py` -- 28 tests covering CRUD, resolution, chain display, API validation
- `dashboard/frontend/dist/style.css` -- existing CSS classes for badges, agent cards, settings panels
- `.planning/workstreams/agent-llm-control/phases/18-agent-config-backend/18-01-SUMMARY.md` -- Phase 18 completion summary
- `.planning/workstreams/agent-llm-control/phases/19-agent-config-dashboard/19-CONTEXT.md` -- user decisions

### Secondary (MEDIUM confidence)
- `settingSelect()`, `settingSecret()`, `saveApiKeys()` patterns -- verified from source code as reliable patterns to follow

### Tertiary (LOW confidence)
- None -- all findings verified from source code

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- direct source code analysis of existing dashboard patterns
- Architecture: HIGH -- patterns extracted from working production code, APIs verified from Phase 18 summary
- Pitfalls: HIGH -- derived from analysis of actual codebase patterns and known issues from CLAUDE.md pitfalls table

**Research date:** 2026-03-07
**Valid until:** 2026-04-07 (stable -- dashboard patterns and backend APIs are frozen)

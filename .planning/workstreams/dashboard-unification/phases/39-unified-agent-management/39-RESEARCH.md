# Phase 39: Unified Agent Management - Research

**Researched:** 2026-04-04
**Domain:** Dashboard frontend (vanilla JS), FastAPI backend, agent data aggregation, proxy patterns
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Agent Data Unification**
- D-01: Aggregated view — Agent42 and Paperclip agents shown in a single merged list with source badges ("Agent42" / "Paperclip"). Filter controls for source and status.
- D-02: New backend endpoint `GET /api/agents/unified` — fetches Agent42 agents locally + proxies to Paperclip API for its agents, merges and returns combined list. Frontend makes one fetch call.
- D-03: Agent42 agents are fully editable in the unified view. Paperclip agents are read-only with a "Manage in Paperclip" deep link for mutations.

**Monitoring & Metrics View**
- D-04: Enhanced agent cards showing: status dot, tier badge, source badge, success rate %, run count, last active time (relative), and 7-day activity sparkline. Click expands to full detail.
- D-05: Summary stats row at top of page: Total agents, Active count, Average success rate, Total tokens consumed. Follows existing `stats-row` pattern already in `renderAgents()`.
- D-06: Agent detail view shows full metrics from both systems — Agent42 performance data (score, tier, tasks, success rate) and Paperclip effectiveness data where available.

**Control Actions**
- D-07: Agent42 agents retain full control actions: start, stop, delete, tier override, create, edit.
- D-08: Paperclip agents shown as read-only — status, metrics, and config visible. Control actions (start/stop/delete/edit) deep link to Paperclip's native UI.
- D-09: Agent creation form polished with source badge showing "Agent42" to clarify ownership. No new form fields — existing structure (name, description, provider, model, schedule, tools, skills, max iterations) kept as-is.

**Template Sharing**
- D-10: Templates remain Agent42-native. Template gallery visible in both modes, always creates Agent42 agents.
- D-11: Template cards show which system the agent will be created in (always "Agent42").
- D-12: No cross-system template format needed — Paperclip has its own agent creation flow.

### Claude's Discretion
- Sparkline rendering approach (CSS, canvas, or SVG)
- Exact card layout and spacing adjustments for enhanced metrics
- Loading/skeleton states for the unified endpoint
- Error handling when Paperclip API is unreachable (graceful degradation — show Agent42 agents only with a banner)
- Source badge styling and color scheme
- Activity sparkline time granularity (hourly vs daily buckets)
- Deep link URL format for Paperclip agent management

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| AGENT-01 | Single interface allows monitoring and control of agents from both Agent42 and Paperclip | D-02 `GET /api/agents/unified` endpoint + `renderAgents()` refactor to use it |
| AGENT-02 | Unified view of agent performance metrics across both systems | D-04 enhanced cards + D-05 stats row + D-06 detail view |
| AGENT-03 | Consistent agent configuration interface regardless of deployment mode | D-09 create form with source badge + `state.standaloneMode` guard (Phase 37 pattern) |
| AGENT-04 | Shared agent templates work in both Paperclip and standalone modes | D-10/D-11 template gallery always creates Agent42 agents + source badge on template cards |
</phase_requirements>

---

## Summary

Phase 39 extends the existing Agents page from a pure Agent42 view to a unified view that also shows Paperclip agents when the sidecar is active. The architecture is backend-merge rather than frontend-merge: a new `GET /api/agents/unified` endpoint in `dashboard/server.py` fetches Agent42 agents locally and optionally proxies to Paperclip's API, returning a normalized combined list. The frontend (`app.js`) replaces its direct `GET /api/agents` call with `GET /api/agents/unified` and renders enhanced cards with source badges, sparklines, and richer metrics.

The implementation is primarily additive. The existing `renderAgents()`, `_renderAgentCards()`, `agentShowDetail()`, `agentShowCreate()`, and `agentShowTemplates()` functions in `app.js` are extended rather than replaced. Existing CSS classes (`agents-grid`, `agent-card`, `badge-tier`, `health-dot`, `stats-row`, `badge-source`) are largely already present — `badge-source` with `.badge-builtin` / `.badge-mcp` color variants already exists in `style.css`; new `.badge-agent42` and `.badge-paperclip` variants need to be added.

The main technical risk is Paperclip API availability: the `PAPERCLIP_API_URL` env var and the sidecar may not be running. The backend must gracefully degrade (return Agent42 agents only with a flag) and the frontend must render a banner rather than failing.

**Primary recommendation:** Implement in two plans — backend first (unified endpoint + tests), then frontend (card enhancements, sparklines, source badges, stats row extension).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python 3.11+ | 3.14.3 (verified) | Backend server language | Project requirement |
| FastAPI | existing | Backend API framework | Already in use throughout server.py |
| httpx | existing | Async HTTP client for Paperclip proxy | Already imported and used in server.py (lines 3266, 4793) |
| pytest | 9.0.2 (verified) | Test framework | Project standard (`python -m pytest tests/ -x -q`) |
| Vanilla JS (ES5-style) | N/A | Frontend scripting | All of app.js uses var-style, no build step |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| aiofiles | existing | Async file I/O | Not needed this phase — agents loaded from in-memory `_agent_manager` |
| fastapi.testclient | existing | Sync test client for FastAPI | Phase-standard test pattern (see test_provider_ui.py, test_standalone_mode.py) |
| MagicMock / AsyncMock | stdlib | Mock agent_manager, effectiveness_store | Phase-standard test pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| SVG sparkline (pure HTML string) | canvas element | Canvas requires DOM manipulation in JS; SVG inline string is simpler for var-style app.js |
| CSS-only sparkline (bar chart via flex) | SVG polyline | CSS bar chart easier to generate from JS string template; SVG polyline more faithful to "sparkline" appearance |
| httpx proxy in endpoint | Frontend two-fetch | Backend proxy is D-02; keeps frontend simple and avoids CORS issues with Paperclip API |

**Installation:** No new packages needed — httpx already available.

---

## Architecture Patterns

### Recommended Project Structure (changes only)
```
dashboard/
├── server.py          # Add GET /api/agents/unified endpoint
└── frontend/dist/
    ├── app.js         # Refactor renderAgents(), enhance cards, sparklines
    └── style.css      # Add .badge-agent42, .badge-paperclip, .sparkline CSS

tests/
└── test_unified_agents.py  # New test file for AGENT-01..04
```

### Pattern 1: Backend Unified Endpoint with Graceful Degradation

**What:** `GET /api/agents/unified` fetches Agent42 agents locally, then attempts a Paperclip proxy call. If Paperclip is unreachable, returns Agent42-only with a `paperclip_unavailable: true` flag.

**When to use:** Anytime cross-system agent listing is needed.

**Structure (from httpx patterns already in server.py):**
```python
@app.get("/api/agents/unified")
async def list_agents_unified(_user: str = Depends(get_current_user)):
    agent42_agents = [
        {**a.to_dict(), "source": "agent42"}
        for a in _agent_manager.list_all()
    ]
    paperclip_agents = []
    paperclip_unavailable = False

    if settings.paperclip_api_url:
        try:
            async with _httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    f"{settings.paperclip_api_url}/api/agents",
                    headers={"Authorization": "Bearer " + _get_paperclip_token()},
                )
            if resp.status_code == 200:
                for pa in resp.json():
                    paperclip_agents.append({**pa, "source": "paperclip"})
            else:
                paperclip_unavailable = True
        except _httpx.TimeoutException:
            paperclip_unavailable = True
        except Exception:
            paperclip_unavailable = True

    return {
        "agents": agent42_agents + paperclip_agents,
        "paperclip_unavailable": paperclip_unavailable,
    }
```

Note: `_httpx` is imported locally (line 3266 pattern) — use the same `import httpx as _httpx` inside the endpoint body or at the function scope.

### Pattern 2: Frontend Lazy-Load with Single Fetch (from Phase 38 pattern)

**What:** `renderAgents()` uses lazy-load guard and fetches `/api/agents/unified` once. Renders all agents and an optional degradation banner.

**When to use:** Replace the existing direct `/api/agents` call.

**From Phase 38 decision:** `if (!state.X) { loadX().then(render); return loading_html; }` is the established pattern.

```javascript
function renderAgents() {
  var el = document.getElementById("page-content");
  if (!el || state.page !== "agents") return;

  fetch("/api/agents/unified", { headers: { Authorization: "Bearer " + state.token } })
    .then(function(r) { return r.json(); })
    .then(function(data) {
      state.agents = data.agents;
      _renderAgentCards(el, data.agents, data.paperclip_unavailable);
    })
    .catch(function() { _renderAgentCards(el, [], false); });
}
```

### Pattern 3: Source Badges for Agent Cards

**What:** Every agent card shows a `badge-source` element. Agent42 agents get `.badge-agent42`, Paperclip agents get `.badge-paperclip`.

**CSS approach (extend existing `badge-source` in style.css line 2778):**
```css
.badge-agent42 { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
.badge-paperclip { background: rgba(16, 185, 129, 0.15); color: #34d399; }
```

These mirror the existing `.badge-builtin` / `.badge-mcp` palette already defined at line 2779-2780.

### Pattern 4: SVG Sparkline (Claude's Discretion)

**What:** 7-day activity sparkline rendered as an inline SVG string. Daily bucket granularity (simpler than hourly). Agent42 agents derive daily bucket data from `last_run_at` and `total_runs` (approximate — no per-day history stored). Paperclip agents pass through whatever daily data the Paperclip API provides.

**Recommended approach:** Since Agent42 has no per-day activity history, show a flat/simplified sparkline for Agent42 agents (uniform bars derived from total_runs / 7) or omit sparkline and show "N/A" for agents with no per-day breakdown. The plan should include a `_makeSparkline(dailyCounts)` helper that accepts an array of 7 integers and returns an SVG string.

```javascript
function _makeSparkline(counts) {
  var max = Math.max.apply(null, counts.concat([1]));
  var pts = counts.map(function(v, i) {
    return (i * 14) + ',' + (28 - Math.round((v / max) * 24));
  }).join(' ');
  return '<svg width="98" height="28" viewBox="0 0 98 28" style="display:block">' +
    '<polyline points="' + pts + '" fill="none" stroke="var(--accent)" stroke-width="1.5" stroke-linejoin="round"/>' +
    '</svg>';
}
```

### Pattern 5: Paperclip Deep Link (Claude's Discretion)

**What:** For Paperclip agents, control buttons are replaced with a "Manage in Paperclip" link.

**Recommended URL format:** Since Paperclip's exact deep-link URL is unknown, use `settings.paperclip_api_url` as a base and document as a config placeholder. The frontend receives the deep link from the unified endpoint response or constructs it from a known pattern.

The backend should include `paperclip_manage_url` in Paperclip agent records so the frontend does not need to hard-code the URL format.

### Pattern 6: Stats Row Extension

**What:** The existing `stats-row` div in `_renderAgentCards()` (line 2371-2376) has 4 stat cards. Add "Avg Success" and "Total Tokens" for D-05.

**Current:** Total Agents | Active | Paused | Total Runs
**Target:** Total Agents | Active | Avg Success | Total Tokens

This requires computing `avgSuccessRate` from agent data. For Agent42 agents, success_rate comes from `/api/agents/{id}/performance` — but that's per-agent async. The unified endpoint should optionally embed success_rate in each agent record to avoid N+1 fetches.

### Anti-Patterns to Avoid

- **N+1 performance fetches:** Do not call `/api/agents/{id}/performance` per card in the card grid. The unified endpoint should embed performance data directly (agent42: from `_agent_manager.get()` + optional effectiveness_store; paperclip: from Paperclip API response).
- **Blocking Paperclip proxy:** Use `timeout=5.0` on the httpx call. A slow Paperclip API must not delay Agent42 agent display. Consider fire-and-forget with a short deadline.
- **var vs const in app.js:** app.js uses ES5-style `var` throughout. Do not introduce `const`/`let`/arrow functions — maintain pattern consistency (Phase 37-02 decision: "var-style + esc() for XSS safety per app.js convention").
- **innerHTML without esc():** All user-facing data must go through the existing `esc()` helper. This is the project's XSS guard.
- **Registering routes outside `create_app()`:** All FastAPI routes are registered inside `create_app()`. Follow this pattern for the new unified endpoint.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Async HTTP proxy | Custom HTTP socket code | `httpx.AsyncClient` (already in server.py) | Already battle-tested with retry/timeout patterns at lines 3494, 4814 |
| XSS sanitization | Custom escape function | `esc()` helper in app.js | Already used throughout — consistent protection |
| Test client setup | Direct Flask/uvicorn | `fastapi.testclient.TestClient` | Phase-standard pattern; synchronous; works with dependency_overrides |
| Auth override in tests | Real JWT generation | `app.dependency_overrides[get_current_user] = lambda: "test-user"` | Phase-standard pattern (test_standalone_mode.py, test_provider_ui.py) |
| Async semaphore management | Custom locking | `_agent_manager._get_tier_semaphore()` | Already implemented with tier concurrency caps |

**Key insight:** This phase is extension, not construction. Every pattern needed already exists in the codebase — the work is wiring them together correctly.

---

## Common Pitfalls

### Pitfall 1: httpx Import at Function Scope vs Module Level

**What goes wrong:** Importing `httpx` at module level in server.py may not work if httpx is unavailable, causing import failures.

**Why it happens:** The Phase 38 decision explicitly states "import os inline inside get_provider_status function body — not at server.py module level" as a Rule 1 auto-fix pattern.

**How to avoid:** Import `httpx as _httpx` locally inside the unified endpoint handler, mirroring the pattern at lines 3266 and 4793. Do not add a module-level import.

**Warning signs:** If the server fails to start with an import error, check that httpx import is scoped to the function body.

### Pitfall 2: Paperclip API URL Unknown at Plan Time

**What goes wrong:** The Paperclip REST API endpoint for listing agents (e.g., `/api/agents`) is not documented in the codebase. `paperclip_api_url` from `Settings` gives the base URL, but the path is unconfirmed.

**Why it happens:** Paperclip is an external system. Agent42 calls `paperclip_api_url` for callbacks (sidecar_orchestrator.py line 289) but the Paperclip-side agent list endpoint path is not referenced anywhere in the codebase.

**How to avoid:** 
- The plan must include a task to discover/document the Paperclip agent list endpoint (check Paperclip docs or the sidecar callback code for clues).
- If the endpoint is unconfirmed, implement the proxy with a configurable env var `PAPERCLIP_AGENTS_PATH` defaulting to `/api/agents`.
- The graceful degradation path (Paperclip unavailable) means this is not a blocker — the page still works with Agent42 agents only.

**Warning signs:** If `paperclip_api_url` is empty string (the default), the proxy branch should be skipped entirely.

### Pitfall 3: Stats Row Average Success Rate — N+1 Pattern

**What goes wrong:** Computing "Average Success Rate" in the stats row requires per-agent success_rate data. If this triggers an HTTP fetch per agent, it causes N performance requests on page load.

**Why it happens:** Current `agentShowDetail()` fetches `/api/agents/{id}/performance` lazily. If success_rate is only in the performance endpoint, the stats row cannot compute it without N fetches.

**How to avoid:** The unified endpoint (`GET /api/agents/unified`) should embed a `success_rate` field in each Agent42 agent record. Fetch from `_effectiveness_store.get_agent_stats(agent_id)` during the unified list call using `asyncio.gather` across all agents (or just include a simplified field from `AgentConfig.performance_score`). For Paperclip agents, include whatever success_rate the Paperclip API returns.

**Warning signs:** If the stats row shows "NaN%" or requires sequential HTTP calls at render time.

### Pitfall 4: Paperclip Mode Dashboard Disabled

**What goes wrong:** In sidecar mode (`settings.sidecar_enabled = True`), the main dashboard at `/` returns a 503 (line 537). The unified agent management features are in the Agent42 dashboard, but the dashboard is gated in sidecar mode.

**Why it happens:** Phase 36 gated the standalone dashboard in sidecar mode (PAPERCLIP-05). The unified agent view is being added to the standalone dashboard's agents page.

**How to avoid:** The unified endpoint `GET /api/agents/unified` should be accessible regardless of sidecar mode — it's an API endpoint, not a UI route. The `/api/agents` endpoints are not gated (checked at lines 4440-4539, no sidecar guard). The unified endpoint should follow the same pattern — register it inside `create_app()` without a sidecar guard.

**Warning signs:** If the unified endpoint returns 503 when sidecar is enabled, check whether a `standalone_required` guard was accidentally applied.

### Pitfall 5: Lazy-Load Guard Causing Infinite Re-render

**What goes wrong:** If the lazy-load guard for the unified agent list is not cleared before re-fetching, clicking "Back" from agent detail then re-navigating to agents shows stale data.

**Why it happens:** Phase 38-02 decision: "Lazy-load guard on Provider Connectivity prevents infinite re-render loop." The guard pattern `if (!state.X) { loadX().then(render); return loading_html; }` must be reset when the page is navigated away from.

**How to avoid:** Use `state.agentsLoaded` as the guard flag. Set it to `null` (not `false`) when navigating away so the next visit triggers a fresh fetch. Follow the exact lazy-load pattern established in Phase 38.

**Warning signs:** If the agents page never updates after an agent is created/deleted.

---

## Code Examples

Verified patterns from existing codebase:

### httpx Async Proxy Pattern (from server.py lines 4793-4826)
```python
# Import locally (Phase 38 Rule 1 pattern)
import httpx

try:
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, headers=headers)
    status = "ok" if resp.status_code == 200 else "error"
except httpx.TimeoutException:
    status = "timeout"
except Exception:
    status = "unreachable"
```

### TestClient with Auth Override (from tests/test_provider_ui.py lines 13-26)
```python
def _make_client(**kwargs) -> TestClient:
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "app_manager": MagicMock(),
        "project_manager": MagicMock(),
        "repo_manager": MagicMock(),
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
    return TestClient(app)
```

### XSS-Safe innerHTML (from app.js throughout)
```javascript
// All user data through esc() — never raw interpolation
'<h4>' + esc(a.name) + '</h4>'
'<span class="badge-tier">' + esc(a.status) + '</span>'
```

### Stats Row Pattern (from app.js line 2371-2376)
```javascript
'<div class="stats-row">' +
  '<div class="stat-card"><div class="stat-label">Total Agents</div><div class="stat-value">' + agents.length + '</div></div>' +
  '<div class="stat-card"><div class="stat-label">Active</div><div class="stat-value text-success">' + activeCount + '</div></div>' +
  // ... additional stat cards follow same structure
'</div>'
```

### Existing Badge Classes (from style.css lines 2778-2781)
```css
/* Already in style.css — base badge-source class */
.badge-source { display: inline-block; padding: 2px 8px; border-radius: 10px; font-size: 0.7rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.03em; }
.badge-builtin { background: rgba(99, 102, 241, 0.15); color: #818cf8; }
.badge-mcp { background: rgba(245, 158, 11, 0.15); color: #fbbf24; }
/* Need to add: .badge-agent42, .badge-paperclip */
```

### Relative Time Helper (pattern needed — not present in app.js)
```javascript
function _relativeTime(epochSec) {
  if (!epochSec) return "Never";
  var diff = Math.floor(Date.now() / 1000 - epochSec);
  if (diff < 60) return diff + "s ago";
  if (diff < 3600) return Math.floor(diff / 60) + "m ago";
  if (diff < 86400) return Math.floor(diff / 3600) + "h ago";
  return Math.floor(diff / 86400) + "d ago";
}
```
This helper is needed for D-04 ("last active time (relative)") — add as a new utility function.

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct `/api/agents` fetch | Unified `/api/agents/unified` fetch | Phase 39 | Frontend makes one call, backend merges |
| 4-stat stats row (Total/Active/Paused/Runs) | Extended stats row (Total/Active/Avg Success/Total Tokens) | Phase 39 | Replaces "Paused" with more useful metrics |
| Agent cards without source | Agent cards with source badge | Phase 39 | Disambiguates origin at a glance |
| No sparkline | 7-day sparkline on cards | Phase 39 | Activity trend visible without opening detail |

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Python 3.11+ | Backend | Yes | 3.14.3 | — |
| pytest | Tests | Yes | 9.0.2 | — |
| httpx | Paperclip proxy | Yes (in venv) | existing | — |
| Paperclip API | Unified agent list | Unknown | — | Graceful degradation — Agent42 agents only |
| `PAPERCLIP_API_URL` env var | Proxy trigger | Not set by default | — | Skip proxy branch (empty string check) |

**Missing dependencies with no fallback:** None that block execution.

**Missing dependencies with fallback:**
- Paperclip API: If unavailable or `PAPERCLIP_API_URL` is empty, unified endpoint returns Agent42 agents only with `paperclip_unavailable: true`. Frontend shows a banner.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 9.0.2 |
| Config file | none — invoked directly |
| Quick run command | `python -m pytest tests/test_unified_agents.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| AGENT-01 | `GET /api/agents/unified` returns merged list with `source` field | unit | `python -m pytest tests/test_unified_agents.py::TestUnifiedEndpoint -x -q` | No — Wave 0 |
| AGENT-01 | Paperclip unreachable → returns Agent42 agents + `paperclip_unavailable: true` | unit | `python -m pytest tests/test_unified_agents.py::TestUnifiedEndpointDegradation -x -q` | No — Wave 0 |
| AGENT-02 | app.js contains `agents/unified` fetch string (static analysis) | unit | `python -m pytest tests/test_unified_agents.py::TestFrontendContent -x -q` | No — Wave 0 |
| AGENT-02 | app.js contains `badge-agent42` and `badge-paperclip` CSS class strings | unit | same file | No — Wave 0 |
| AGENT-02 | app.js contains `_relativeTime` or relative time logic for last active | unit | same file | No — Wave 0 |
| AGENT-03 | app.js contains source badge "Agent42" in create form | unit | `python -m pytest tests/test_unified_agents.py::TestCreateFormSourceBadge -x -q` | No — Wave 0 |
| AGENT-04 | app.js contains template cards with "Agent42" source badge | unit | `python -m pytest tests/test_unified_agents.py::TestTemplateBadge -x -q` | No — Wave 0 |
| AGENT-04 | Template creation still uses `POST /api/agents` (not Paperclip endpoint) | unit | same file | No — Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_unified_agents.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_unified_agents.py` — covers AGENT-01 through AGENT-04
  - `TestUnifiedEndpoint` — happy path: merges Agent42 + Paperclip agents, adds `source` field
  - `TestUnifiedEndpointDegradation` — Paperclip timeout → Agent42 only + `paperclip_unavailable: true`
  - `TestUnifiedEndpointNoUrl` — `PAPERCLIP_API_URL` empty → skips proxy entirely
  - `TestFrontendContent` — static analysis of app.js for required strings
  - `TestCreateFormSourceBadge` — "Agent42" badge in create form
  - `TestTemplateBadge` — template cards show "Agent42" source
  - `TestStylesheet` — `.badge-agent42` and `.badge-paperclip` in style.css

---

## Open Questions

1. **Paperclip agent list endpoint path**
   - What we know: `PAPERCLIP_API_URL` config var exists; sidecar calls `paperclip_api_url` for callbacks (sidecar_orchestrator.py line 289)
   - What's unclear: The exact REST path Paperclip exposes for listing its own agents (not Agent42 agents running inside Paperclip)
   - Recommendation: Implement with a configurable `PAPERCLIP_AGENTS_PATH` env var defaulting to `/api/agents`. If Paperclip is unreachable or the path is wrong, graceful degradation handles it. Document as a known unknown requiring Paperclip API docs or empirical testing.

2. **Paperclip agent data schema**
   - What we know: Paperclip agents have their own schema; Agent42's sidecar models include `AgentProfileResponse` with `agentId`, `tier`, `successRate`, `taskVolume`, `avgSpeedMs`, `compositeScore`
   - What's unclear: The exact JSON fields in Paperclip's `/api/agents` list response (names, status, last_run, etc.)
   - Recommendation: Normalize in the backend proxy — map Paperclip fields to Agent42 fields, adding `source: "paperclip"`. For unknown fields, use safe defaults. The normalized schema should include: `id`, `name`, `description`, `status`, `source`, `success_rate` (optional), `total_runs` (optional), `last_run_at` (optional).

3. **Deep link URL format for Paperclip**
   - What we know: `paperclip_api_url` gives the base URL
   - What's unclear: How Paperclip structures its agent management UI URLs
   - Recommendation: Include `manage_url` in the backend's Paperclip agent records, constructed as `{paperclip_api_url}/agents/{id}`. If this is wrong, it's a single-line config fix.

---

## Sources

### Primary (HIGH confidence)
- `dashboard/server.py` — Existing FastAPI app, httpx usage patterns, agent endpoints (lines 4440-4650)
- `dashboard/frontend/dist/app.js` — renderAgents(), _renderAgentCards(), agentShowDetail(), agentShowCreate(), agentShowTemplates() (lines 2326-2600)
- `dashboard/frontend/dist/style.css` — badge-source, badge-tier, health-dot, agents-grid CSS (lines 1574-1705, 2778-2784)
- `core/agent_manager.py` — AgentConfig dataclass, AGENT_TEMPLATES, AgentManager class (lines 191-450)
- `core/config.py` — paperclip_api_url, sidecar_enabled, standalone_mode settings (lines 314-319)
- `plugins/agent42-paperclip/src/client.ts` — Agent42Client, available sidecar API surface
- `plugins/agent42-paperclip/src/ui/AgentEffectivenessTab.tsx` — Paperclip effectiveness data schema
- `tests/test_provider_ui.py` — Phase test pattern: TestClient, dependency_overrides, static analysis
- `tests/test_standalone_mode.py` — standalone flag pattern, _make_client factory

### Secondary (MEDIUM confidence)
- `.planning/workstreams/dashboard-unification/STATE.md` — Phase 37-02 decisions: standaloneMode flag, var-style, esc() XSS
- `.planning/workstreams/dashboard-unification/ROADMAP.md` — Phase 39 success criteria

### Tertiary (LOW confidence)
- Paperclip API agent list endpoint path — not documented in codebase; assumed `/api/agents`

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries verified present in the project
- Architecture: HIGH — all patterns taken directly from existing code in this repo
- Pitfalls: HIGH — derived from Phase 38 STATE.md decisions and code inspection
- Paperclip API schema: LOW — no Paperclip API documentation available in the codebase

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (stable internal codebase; no external library churn)

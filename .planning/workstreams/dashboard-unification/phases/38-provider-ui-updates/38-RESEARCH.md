# Phase 38: Provider UI Updates - Research

**Researched:** 2026-04-04
**Domain:** Dashboard frontend (vanilla JS SPA) + FastAPI backend — provider configuration UI
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Provider Structure and Naming**
- D-01: CC Subscription displayed as read-only status indicator (no key input field) — uses `CLAUDECODE_SUBSCRIPTION_TOKEN` managed by CLI, not KeyStore
- D-02: Gemini demoted from "Primary Provider (Recommended)" to Media and Search section — no routing logic in PROVIDER_MODELS, only used as OpenRouter model for embeddings
- D-03: Replace section labels "Primary Providers" / "Premium Providers" with: "Claude Code Subscription" (status-only) + "API Key Providers" (Synthetic.new, Anthropic, OpenRouter) + "Media & Search" (Replicate, Luma, Brave, Gemini)
- D-04: Add routing info box at top of Providers tab explaining routing order: CC Subscription -> Synthetic.new -> Other providers
- D-05: StrongWall cleanup scope is minimal — update comment in `dashboard/server.py:1344`, delete `app.js.backup`. Live `app.js` is already clean. Planning docs left as historical record.

**Synthetic.new Model Display**
- D-06: Collapsible card below Synthetic API Key field, collapsed by default showing model count + last refreshed timestamp; expand to reveal full table — follows `orStatus` card pattern exactly
- D-07: Expanded table shows: name, capabilities (badges reusing `badge-type` CSS), max_context_length (formatted as "128K"), is_free (pill badge), description (truncated, full on row expand)
- D-08: Also display capability-to-model mapping from `update_provider_models_mapping()` — shows which model Agent42 selects per task category
- D-09: New backend endpoint `GET /api/providers/synthetic/models` returning `{models: [...], cached_at: timestamp, count: N, free_count: N}`
- D-10: "Refresh" link calls endpoint with `force=true` parameter, follows `loadOrStatus().then(renderSettingsPanel)` pattern

**Provider Status and Connectivity**
- D-11: Key-presence badges using existing `secret-status.configured` / `secret-status.not-configured` CSS — inline with each provider row
- D-12: New `GET /api/settings/provider-status` endpoint — pings each configured provider's `/v1/models` endpoint with `httpx` and 5s timeout. Returns per-provider `{name, configured, status}` where status is `unconfigured | ok | auth_error | unreachable | timeout`
- D-13: Auto-loads on Providers tab enter following `loadOrStatus()` pattern — "Loading..." state, inline results, "Refresh" link
- D-14: Reuse existing `health-dot` CSS classes (`h-ok`, `h-auth_error`, `h-error`, `h-unavailable`) for status indicators
- D-15: No auto-poll timer. No new dedicated tab. No per-model health checks.
- D-16: Keep OpenRouter Account Status section as-is (tier/credits/policy) — don't generalize to other providers

**Model Selection UX**
- D-17: Dynamic dropdown with `optgroup` categories in agent creation form — provider change triggers `GET /api/agents/models`, Synthetic.new models shown grouped by capability category
- D-18: For Anthropic/OpenRouter: populate `#agent-model` with existing PROVIDER_MODELS subset
- D-19: `AgentConfig.model` field stores specific model ID — backend already supports arbitrary model ID strings
- D-20: Add cache-age awareness: if Synthetic model cache is stale, show "Model list last updated N hours ago" near dropdown

### Claude's Discretion
- Exact CSS styling for the routing info box
- Badge color scheme for capability categories
- Truncation length for model descriptions
- Loading spinner/skeleton details
- Error state messaging for failed provider pings
- optgroup display names (e.g., "Fast" vs "fast" vs "Speed-optimized")

### Deferred Ideas (OUT OF SCOPE)
- None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PROVIDER-01 | Remove all StrongWall.ai references from dashboard UI | D-05: live app.js already clean; delete app.js.backup, update server.py:1344 comment |
| PROVIDER-02 | Update provider configuration UI to match current provider structure (CC Subscription, Synthetic.new, Anthropic, OpenRouter) | D-01 through D-04: restructure Providers tab HTML in app.js |
| PROVIDER-03 | Display dynamic model discovery from Synthetic.new in provider selection UI | D-06 through D-10: collapsible card + new backend endpoint |
| PROVIDER-04 | Show provider status and connectivity in dashboard | D-11 through D-16: health-dot badges + new backend endpoint |
| PROVIDER-05 | Enable model selection from dynamically discovered Synthetic.new models | D-17 through D-20: dynamic optgroup dropdown in agent creation form |
</phase_requirements>

---

## Summary

Phase 38 is a focused UI update phase with no new infrastructure dependencies. All backend services are already in place — `SyntheticApiClient` (providers/synthetic_api.py), `PROVIDER_MODELS` (core/agent_manager.py), and the `/api/agents/models` endpoint already exist. The work consists of two new backend endpoints (`/api/providers/synthetic/models` and `/api/settings/provider-status`), restructuring the Providers tab HTML in app.js, adding a dynamic model dropdown to the agent creation form, and deleting one stale backup file.

The codebase provides all the patterns needed. The storage status endpoint (`/api/settings/storage`) is the exact template for the new provider status endpoint — same structure: check key presence, make live HTTP ping, return structured status dict. The `orStatus` collapsible card in app.js is the exact template for the Synthetic model catalog card. The `loadOrStatus()` function is the exact pattern for both new lazy-load functions.

**Primary recommendation:** Two plans — Plan 38-01: two new backend endpoints + cleanup (PROVIDER-01, PROVIDER-03, PROVIDER-04); Plan 38-02: frontend Providers tab restructure + dynamic agent form dropdown + tests (PROVIDER-02, PROVIDER-05).

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | existing | New backend endpoints | Already in use — all API endpoints are FastAPI |
| httpx | existing | Provider health pings | Already used in `dashboard/server.py` for storage health, Qdrant pings |
| aiohttp | existing | Synthetic.new model fetch | Already used in `providers/synthetic_api.py` |
| Vanilla JS | existing | Frontend SPA | app.js is a compiled non-bundled SPA — no build step, no npm |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| pytest + FastAPI TestClient | existing | Backend endpoint tests | New endpoints need unit tests following existing pattern |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Direct httpx ping for health | SyntheticApiClient.refresh_models() | refresh_models is async and heavyweight; a direct GET /v1/models with 5s timeout is more appropriate for a health check |
| New CSS classes | Reusing `health-dot` + `secret-status` | Reuse is required (D-11, D-14) — no new CSS classes needed except minimal badge variants |

**Installation:** No new packages required. All dependencies already present.

---

## Architecture Patterns

### Existing Pattern: Storage Status Endpoint (template for provider-status)

The `/api/settings/storage` endpoint (server.py lines 4952-5059) is the exact model to follow for `/api/settings/provider-status`:

```python
# Source: dashboard/server.py:4952-5013
@app.get("/api/settings/storage")
async def get_storage_status(_admin: AuthContext = Depends(require_admin)):
    # 1. Check key/config presence
    # 2. Import httpx, ping endpoint with short timeout
    # 3. Map exception types to status strings (connected/unreachable/timeout/auth_error)
    # 4. Return structured dict
    ...
    async with httpx.AsyncClient(timeout=3.0) as client:
        resp = await client.get(f"{qdrant_url.rstrip('/')}/healthz")
    qdrant_status = "connected" if resp.status_code == 200 else "unreachable"
```

For provider-status, each provider has a known base URL. Ping `/v1/models` with 5s timeout:
- `https://api.anthropic.com/v1/models` with `x-api-key` header
- `https://api.synthetic.new/v1/models` with `Authorization: Bearer` header
- `https://openrouter.ai/api/v1/models` with `Authorization: Bearer` header
- Claude Code Subscription: check `CLAUDECODE_SUBSCRIPTION_TOKEN` env var presence only (no live ping — managed by CLI)

Status string mapping:
- No key -> `unconfigured`
- HTTP 200 -> `ok`
- HTTP 401/403 -> `auth_error`
- Connection error -> `unreachable`
- Timeout -> `timeout`

### Existing Pattern: orStatus Collapsible Card (template for Synthetic model card)

The `orStatus` card in app.js (lines 7831-7848) uses this pattern:
- Check `state.orStatus` — if null, show loading/placeholder; if populated, render card
- "Refresh" link calls `loadOrStatus().then(()=>renderSettingsPanel());return false`
- `state.orStatusLoading` tracks in-flight state

Synthetic model card follows this pattern exactly with `state.syntheticModels` / `state.syntheticModelsLoading`.

### Existing Pattern: loadOrStatus() (template for lazy-load functions)

```javascript
// Source: dashboard/frontend/dist/app.js:8160-8166
async function loadOrStatus() {
  state.orStatusLoading = true;
  try {
    state.orStatus = (await api("/settings/openrouter-status")) || null;
  } catch (e) { state.orStatus = null; }
  state.orStatusLoading = false;
}
```

New functions follow this exact pattern:
- `loadSyntheticModels(force)` calls `/providers/synthetic/models?force=true`
- `loadProviderStatus()` calls `/settings/provider-status`

### Existing Pattern: settingSecret() for API keys

Used for SYNTHETIC_API_KEY, ANTHROPIC_API_KEY, OPENROUTER_API_KEY. Already renders the `secret-status configured/not-configured` badge (D-11). For CC Subscription (not in ADMIN_CONFIGURABLE_KEYS), use `settingReadonly()` or a custom div showing presence-only status.

### Existing Pattern: Agent Creation Form

```javascript
// Source: dashboard/frontend/dist/app.js:2382-2416
// Current: provider select (static) + model select (hardcoded 3 options)
// New: attach onchange="loadAgentModels(this.value)" to provider select
//      loadAgentModels() calls /api/agents/models and repopulates #agent-model
//      using optgroup elements per capability category
```

### Anti-Patterns to Avoid

- **Adding CLAUDECODE_SUBSCRIPTION_TOKEN to ADMIN_CONFIGURABLE_KEYS:** It is managed by the CLI, not the dashboard KeyStore (D-01). Display presence-only.
- **New CSS classes when existing ones suffice:** `health-dot`, `secret-status.configured/not-configured`, `badge-type` cover all needed visual states (D-11, D-14).
- **Auto-polling provider status:** No timers — only on tab enter + manual refresh (D-15). Avoids burning API rate limits.
- **Modifying core/agent_manager.py:** PROVIDER_MODELS and `/api/agents/models` already serve the right data (D-17). Frontend just needs to consume it differently.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Provider health ping | Custom probe logic | Mirror `/api/settings/storage` pattern | Pattern already handles timeout/auth_error/unreachable mapping |
| Model catalog display | Custom table component | Reuse `table-wrap > table > thead + tbody` pattern from Tools/Skills pages | Consistent with existing app.js table rendering |
| XSS protection | Custom escaping | `esc()` helper already in app.js | All user-facing data already passes through this function |
| Lazy-load state | Custom state management | `state.X` + `state.XLoading` + `renderSettingsPanel()` pattern | Matches all existing lazy-load patterns in app.js |

---

## Common Pitfalls

### Pitfall 1: Editing app.js.backup Instead of app.js
**What goes wrong:** app.js.backup is the stale file listed in git status as untracked. It is not served.
**Why it happens:** Backup files named similarly to the real file cause confusion.
**How to avoid:** The only file to edit is `dashboard/frontend/dist/app.js`. The PROVIDER-01 task deletes app.js.backup outright.
**Warning signs:** If grep finds StrongWall in the file being edited, you are in the wrong file.

### Pitfall 2: Providers Tab Triggers Lazy-Load on Every Render
**What goes wrong:** If `loadProviderStatus()` is called unconditionally inside the providers tab template function, it re-triggers on every `renderSettingsPanel()` call — creating an infinite re-render loop.
**Why it happens:** The lazy-load pattern requires a guard: `if (!state.providerStatus) { loadProviderStatus().then(renderSettingsPanel); return loading_html; }`.
**How to avoid:** Follow the exact pattern from `loadRewardsStatus()` and the storage status — check `if (!state.X)` before calling the async loader.
**Warning signs:** Browser console shows repeated `/api/settings/provider-status` calls.

### Pitfall 3: Agent Model Dropdown Not Populated on Create Form Load
**What goes wrong:** The agent creation form is rendered once via DOM injection in `agentShowCreate()`. If `loadAgentModels()` is async and called after the form content is set, `#agent-model` may not exist in the DOM when the response arrives.
**Why it happens:** The form is injected all at once. Model population must happen after the element exists.
**How to avoid:** Call `loadAgentModels(defaultProvider)` after the form content injection completes in `agentShowCreate()`. Render a "Loading..." option and replace it in the callback.
**Warning signs:** `document.getElementById("agent-model")` returns null in loadAgentModels().

### Pitfall 4: Synthetic Base URL Mismatch for Health Check
**What goes wrong:** `SyntheticApiClient` uses `https://api.synthetic.new/v1`. If the provider status endpoint uses a different URL, it will report unreachable even when the Synthetic key works.
**Why it happens:** URL could be hardcoded differently in two places.
**How to avoid:** The provider status endpoint should ping `https://api.synthetic.new/v1/models` — matching the `SyntheticApiClient._base_url` constant.
**Warning signs:** provider-status returns `unreachable` even when Synthetic key is valid and models load normally.

### Pitfall 5: httpx Must Be Imported Inside the Endpoint Function
**What goes wrong:** Moving `import httpx` to module level in server.py could break startup if httpx is not installed (even though it is currently present — graceful degradation design).
**Why it happens:** The storage status endpoint imports `httpx` inside the function body intentionally.
**How to avoid:** Follow the same pattern — import httpx inside the endpoint function body.
**Warning signs:** ImportError surfaced at module load time rather than at endpoint call time.

---

## Code Examples

### Backend: Provider Status Endpoint (modeled on /api/settings/storage)

```python
# Source pattern: dashboard/server.py:4952-5059
@app.get("/api/settings/provider-status")
async def get_provider_status(_admin: AuthContext = Depends(require_admin)):
    """Return live connectivity status for each configured LLM provider."""
    import httpx
    import time

    results = []

    # CC Subscription — presence-only, no live ping (managed by CLI)
    cc_token = os.environ.get("CLAUDECODE_SUBSCRIPTION_TOKEN", "")
    results.append({
        "name": "claudecode",
        "label": "Claude Code Subscription",
        "configured": bool(cc_token),
        "status": "ok" if cc_token else "unconfigured",
    })

    # Synthetic.new — ping /v1/models
    synthetic_key = os.environ.get("SYNTHETIC_API_KEY", "")
    if not synthetic_key:
        results.append({"name": "synthetic", "label": "Synthetic.new",
                        "configured": False, "status": "unconfigured"})
    else:
        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.get(
                    "https://api.synthetic.new/v1/models",
                    headers={"Authorization": f"Bearer {synthetic_key}"}
                )
            status = "ok" if resp.status_code == 200 else (
                "auth_error" if resp.status_code in (401, 403) else "unreachable"
            )
        except httpx.TimeoutException:
            status = "timeout"
        except Exception:
            status = "unreachable"
        results.append({"name": "synthetic", "label": "Synthetic.new",
                        "configured": True, "status": status})

    # ... same pattern for anthropic, openrouter ...
    return {"providers": results, "checked_at": time.time()}
```

### Backend: Synthetic Models Endpoint

```python
# Source pattern: providers/synthetic_api.py + SyntheticApiClient
@app.get("/api/providers/synthetic/models")
async def get_synthetic_models(
    force: bool = False,
    _admin: AuthContext = Depends(require_admin)
):
    """Return Synthetic.new model catalog with optional cache bypass."""
    if _synthetic_client is None:
        return {"models": [], "cached_at": None, "count": 0, "free_count": 0,
                "capability_mapping": {}}
    models = await _synthetic_client.refresh_models(force=force)
    mapping = _synthetic_client.update_provider_models_mapping()
    free_count = sum(1 for m in models if m.is_free)
    return {
        "models": [
            {
                "id": m.id, "name": m.name, "description": m.description,
                "capabilities": m.capabilities,
                "max_context_length": m.max_context_length,
                "is_free": m.is_free,
            }
            for m in models
        ],
        "cached_at": _synthetic_client._last_refresh or None,
        "count": len(models),
        "free_count": free_count,
        "capability_mapping": mapping,
    }
```

### Frontend: Lazy-Load Pattern for New State Keys

```javascript
// Source: dashboard/frontend/dist/app.js:8160-8166 (loadOrStatus pattern)
async function loadSyntheticModels(force) {
  state.syntheticModelsLoading = true;
  try {
    var qs = force ? "?force=true" : "";
    state.syntheticModels = (await api("/providers/synthetic/models" + qs)) || null;
  } catch (e) { state.syntheticModels = null; }
  state.syntheticModelsLoading = false;
}

async function loadProviderStatus() {
  state.providerStatusLoading = true;
  try {
    state.providerStatus = (await api("/settings/provider-status")) || null;
  } catch (e) { state.providerStatus = null; }
  state.providerStatusLoading = false;
}
```

### Frontend: Dynamic Model Dropdown Population

```javascript
// Source: core/agent_manager.py:39-76 (PROVIDER_MODELS structure)
// Called onchange from provider select, and on initial form render
async function loadAgentModels(provider) {
  var sel = document.getElementById("agent-model");
  if (!sel) return;
  try {
    var models = await api("/agents/models");  // Returns PROVIDER_MODELS dict
    var providerModels = models[provider] || {};
    var options = Object.entries(providerModels).map(function(entry) {
      var cat = entry[0], modelId = entry[1];
      return "<option value=\"" + esc(modelId) + "\">"
           + esc(cat) + " \u2014 " + esc(modelId) + "</option>";
    });
    sel.textContent = "";  // clear existing options
    options.forEach(function(html) {
      var tmp = document.createElement("option");
      // parse via template pattern matching existing app.js conventions
      sel.appendChild(tmp);
    });
  } catch (e) { /* keep existing options on error */ }
}
```

### Frontend: Providers Tab New Structure (outline)

The `providers:` function in the settings panel template (app.js ~7786) needs to be replaced with this structure:

1. Routing info box (D-04) — explains CC Subscription -> Synthetic.new -> others hierarchy
2. "Claude Code Subscription" heading + read-only status badge showing CLAUDECODE_SUBSCRIPTION_TOKEN presence
3. "API Key Providers" heading + `settingSecret("SYNTHETIC_API_KEY", ...)` + Synthetic model catalog card (D-06) + `settingSecret("ANTHROPIC_API_KEY", ...)` + `settingSecret("OPENROUTER_API_KEY", ...)`
4. "Provider Connectivity" heading + provider status table (D-12/D-13) using health-dot CSS
5. "Media & Search" heading + REPLICATE, LUMA, BRAVE, GEMINI key fields (D-03)
6. Save API Keys button (unchanged)
7. OpenRouter Account Status section (unchanged, D-16)

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| StrongWall.ai as L1 workhorse | CC Subscription as primary, Synthetic.new as fallback | Phase 32 (2026-04-01) | server.py:1344 has stale comment; app.js.backup exists as untracked file |
| Static model dropdown (hardcoded 3 Claude models) | Dynamic optgroup from /api/agents/models | Phase 38 | Agent creation form needs to call the existing endpoint |
| "Primary Providers" / "Premium Providers" section labels | CC Subscription (status) + API Key Providers + Media & Search | Phase 38 | Providers tab HTML restructure |
| Gemini as "Default primary model. Generous free tier" | Gemini demoted to embeddings-only in Media & Search | Phase 38 (D-02) | Label/placement change only; key remains admin-configurable |

**Deprecated/outdated:**
- `STRONGWALL_API_KEY`: Removed from `ADMIN_CONFIGURABLE_KEYS` in Phase 32. Already absent from app.js. Stale comment in server.py:1344 and app.js.backup are the only remaining artifacts.
- "Model Routing (v2.0)" info box and "MCP Integration" info box in current Providers tab (app.js:7790-7804): Will be replaced with the new routing info box (D-04).
- `loadRoutingModels()` / `/api/available-models` / `/api/agent-routing` at app.js:8187-8196: Dead routing stubs — not Phase 38 scope but noted as stale code.

---

## Open Questions

1. **Where is `_synthetic_client` accessible from the server module?**
   - What we know: `SyntheticApiClient()` is instantiated in `core/agent_manager.py` as module-private `_synthetic_client`. The `/api/providers/synthetic/models` endpoint needs to call it.
   - What's unclear: Does `create_app()` in dashboard/server.py receive the SyntheticApiClient instance as a parameter, or must the endpoint import it directly from agent_manager?
   - Recommendation: Read `create_app()` signature in server.py. If not passed in, expose it via `from core.agent_manager import _synthetic_client` or add a `get_synthetic_client()` accessor function to agent_manager.py.

2. **Tab-enter trigger location for new lazy-load functions**
   - What we know: `loadOrStatus()` is called somewhere in the settings tab-switch handler. New `loadProviderStatus()` and `loadSyntheticModels()` need to hook into the "providers" tab entry point.
   - What's unclear: The exact line in app.js where `settingsTab` switches and triggers existing loaders.
   - Recommendation: Grep app.js for `settingsTab.*providers` or `loadOrStatus` call site to find the hook point before writing the frontend plan.

---

## Environment Availability

Step 2.6: SKIPPED — this phase has no external dependencies beyond the project's existing stack. `httpx`, `aiohttp`, Python 3.11+, and FastAPI are already installed and used throughout. No new tools, CLIs, or services are required.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest + FastAPI TestClient |
| Config file | `tests/conftest.py` (shared fixtures) |
| Quick run command | `python -m pytest tests/test_provider_ui.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PROVIDER-01 | app.js.backup absent; server.py:1344 comment does not contain "StrongWall $16/mo" | unit (file system + grep) | `python -m pytest tests/test_provider_ui.py::test_no_strongwall_artifacts -x` | Wave 0 |
| PROVIDER-02 | GET /api/settings renders provider tab with CC Subscription + API Key Providers + Media sections | unit | `python -m pytest tests/test_provider_ui.py::test_provider_tab_structure -x` | Wave 0 |
| PROVIDER-03 | GET /api/providers/synthetic/models returns dict with models/count/free_count/capability_mapping | unit | `python -m pytest tests/test_provider_ui.py::test_synthetic_models_endpoint -x` | Wave 0 |
| PROVIDER-04 | GET /api/settings/provider-status returns list of providers with status field per provider | unit | `python -m pytest tests/test_provider_ui.py::test_provider_status_endpoint -x` | Wave 0 |
| PROVIDER-05 | GET /api/agents/models returns PROVIDER_MODELS dict with claudecode/anthropic/synthetic/openrouter keys | unit | `python -m pytest tests/test_provider_ui.py::test_agents_models_endpoint -x` | Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_provider_ui.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_provider_ui.py` — covers PROVIDER-01 through PROVIDER-05

Existing infrastructure that is reusable (no gaps):
- `tests/conftest.py` — shared fixtures
- `_make_client()` pattern from `test_standalone_mode.py` — TestClient with auth override via `dependency_overrides[get_current_user]`
- Full suite command is stable: `python -m pytest tests/ -x -q`

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 38 |
|-----------|-------------------|
| All I/O is async — use `httpx`, `asyncio`. Never blocking. | Provider status pings must use `async with httpx.AsyncClient(...)` |
| Frozen config — Settings dataclass. Add fields to `core/config.py`. | No new Settings fields needed in this phase (no new env vars required) |
| Graceful degradation — handle absence of services, never crash | Provider status endpoint must handle missing keys and failed pings without raising HTTP 500 |
| NEVER log API keys at DEBUG level | Provider status endpoint must not log the actual key values even for debug tracing |
| New modules need `tests/test_*.py` | New endpoint functions need `tests/test_provider_ui.py` |
| GSD workflow enforcement | All work via `/gsd:execute-phase` |

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `dashboard/frontend/dist/app.js` lines 7786-7849 (Providers tab HTML), 7831-7848 (orStatus card pattern), 8160-8166 (loadOrStatus), 2382-2416 (agent creation form)
- Direct code inspection: `dashboard/server.py` lines 4952-5059 (storage status endpoint), 4739-4745 (/api/providers stub), 4448-4451 (/api/agents/models), 1344 (StrongWall comment), 4897-4903 (openrouter-status)
- Direct code inspection: `providers/synthetic_api.py` — full SyntheticApiClient including `refresh_models()`, `update_provider_models_mapping()`, cache logic
- Direct code inspection: `core/agent_manager.py` lines 39-76 (PROVIDER_MODELS), 79-123 (refresh_synthetic_models), 494-495 (get_provider_models)
- Direct code inspection: `core/key_store.py` lines 21-35 (ADMIN_CONFIGURABLE_KEYS — confirms CLAUDECODE_SUBSCRIPTION_TOKEN absent)
- Direct code inspection: `core/config.py` lines 43-58 (Settings fields — claudecode_subscription_token present), 50-53 (dead provider comments)
- Direct code inspection: `dashboard/frontend/dist/style.css` lines 398-403 (secret-status CSS), 1563-1573 (health-dot CSS)
- Direct code inspection: `.planning/phases/38-provider-ui-updates/38-CONTEXT.md` — all locked decisions D-01 through D-20

### Secondary (MEDIUM confidence)
- `.claude/reference/dashboard-frontend-update.md` — prior analysis of required frontend changes, corroborated by direct code inspection
- `.planning/REQUIREMENTS.md` — PROVIDER-01 through PROVIDER-05 definitions
- `.planning/workstreams/dashboard-unification/ROADMAP.md` — phase success criteria

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies verified in existing code
- Architecture: HIGH — all patterns directly read from live codebase, not inferred from training data
- Pitfalls: HIGH — derived from direct reading of existing patterns and test infrastructure
- Open questions: MEDIUM — require reading one additional code path (create_app signature, tab-switch handler)

**Research date:** 2026-04-04
**Valid until:** 2026-05-04 (stable codebase; decisions locked in CONTEXT.md)

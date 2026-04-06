# Phase 38: Provider UI Updates - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Update provider configuration UI to match current provider structure (Claude Code Subscription, Synthetic.new, Anthropic, OpenRouter). Remove all StrongWall.ai references. Display dynamic model discovery from Synthetic.new. Show provider status and connectivity. Enable model selection from dynamically discovered models.

Requirements: PROVIDER-01, PROVIDER-02, PROVIDER-03, PROVIDER-04, PROVIDER-05.

</domain>

<decisions>
## Implementation Decisions

### Provider Structure & Naming
- **D-01:** Subscription vs API Providers layout — CC Subscription displayed as read-only status indicator (no key input field) since it uses `CLAUDECODE_SUBSCRIPTION_TOKEN` managed by CLI, not KeyStore. Below: "API Key Providers" section with Synthetic.new, Anthropic, OpenRouter key fields.
- **D-02:** Gemini demoted from "Primary Provider (Recommended)" to Media & Search section — Gemini has no routing logic in PROVIDER_MODELS (marked dead in config.py), only used as OpenRouter model for embeddings.
- **D-03:** Remove misleading "Primary Providers" / "Premium Providers" section labels — replace with "Claude Code Subscription" (status-only) + "API Key Providers" (Synthetic.new, Anthropic, OpenRouter) + "Media & Search" (Replicate, Luma, Brave, Gemini for embeddings).
- **D-04:** Add routing info box at top of Providers tab explaining: "Routing order: CC Subscription -> Synthetic.new -> Other providers"
- **D-05:** StrongWall cleanup scope is minimal: update comment in `dashboard/server.py:1344`, delete `app.js.backup` file. Live `app.js` is already clean. Planning docs left as historical record.

### Synthetic.new Model Display
- **D-06:** Collapsible card below Synthetic API Key field following the `orStatus` pattern exactly — collapsed by default showing model count + last refreshed timestamp; expand to reveal full table.
- **D-07:** Expanded table shows: name, capabilities (badges reusing existing `badge-type` CSS), max_context_length (formatted as "128K"), is_free (pill badge), description (truncated, full on row expand).
- **D-08:** Also display the capability-to-model mapping from `update_provider_models_mapping()` — shows which model Agent42 actually selects per task category.
- **D-09:** New backend endpoint `GET /api/providers/synthetic/models` returning `{models: [...], cached_at: timestamp, count: N, free_count: N}`.
- **D-10:** "Refresh" link calls endpoint with `force=true` parameter, follows `loadOrStatus().then(renderSettingsPanel)` pattern.

### Provider Status & Connectivity
- **D-11:** Key-presence badges using existing `secret-status.configured` / `secret-status.not-configured` CSS — inline with each provider row.
- **D-12:** New `GET /api/settings/provider-status` endpoint mirroring the storage status pattern (`/api/settings/storage`) — pings each configured provider's `/v1/models` endpoint with `httpx` and 5s timeout. Returns per-provider `{name, configured, status}` where status is `unconfigured | ok | auth_error | unreachable | timeout`.
- **D-13:** Auto-loads on Providers tab enter following `loadOrStatus()` pattern — show "Loading..." state, render inline results, include "Refresh" link for manual re-check.
- **D-14:** Reuse existing `health-dot` CSS classes (`h-ok`, `h-auth_error`, `h-error`, `h-unavailable`) for status indicators.
- **D-15:** No auto-poll timer (avoids burning API rate limits). No new dedicated tab. No per-model health checks.
- **D-16:** Keep OpenRouter Account Status section as-is (tier/credits/policy) — this provider-specific detail stays; don't generalize to other providers.

### Model Selection UX
- **D-17:** Dynamic dropdown with `<optgroup>` categories in agent creation form — provider change triggers `GET /api/agents/models`, Synthetic.new models shown grouped by capability category (fast, coding, reasoning, general, etc.) with actual model IDs as values.
- **D-18:** For Anthropic/OpenRouter: populate `#agent-model` with the existing model subset from PROVIDER_MODELS.
- **D-19:** `AgentConfig.model` field stores the specific model ID (not a category name) — backend already supports arbitrary model ID strings.
- **D-20:** Add cache-age awareness: if Synthetic model cache is stale, show a note "Model list last updated N hours ago" near the dropdown.

### Claude's Discretion
- Exact CSS styling for the routing info box
- Badge color scheme for capability categories
- Truncation length for model descriptions
- Loading spinner/skeleton details
- Error state messaging for failed provider pings
- `<optgroup>` display names (e.g., "Fast" vs "fast" vs "Speed-optimized")

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/workstreams/dashboard-unification/ROADMAP.md` — Phase 38 success criteria (5 acceptance tests)
- `.planning/REQUIREMENTS.md` — PROVIDER-01 through PROVIDER-05 define all Phase 38 requirements

### Prior phase context (dependencies)
- `.planning/phases/36-paperclip-integration-core/36-CONTEXT.md` — Sidecar REST API patterns, D-09 through D-12
- `.planning/phases/37-standalone-dashboard/37-CONTEXT.md` — Standalone mode flag, settingSecret() pattern, app.js SPA architecture, D-01 through D-15

### Existing codebase (key files to read)
- `dashboard/frontend/dist/app.js` — Lines 7786-7848 (Providers tab HTML), 7960-7997 (storage status table pattern to mirror), 8160-8166 (loadOrStatus() pattern to copy), 2382-2416 (agent creation form)
- `dashboard/frontend/dist/style.css` — Lines 398-403 (secret-status CSS), 1564-1573 (health-dot CSS with all needed status colors)
- `dashboard/server.py` — Line 4739 (/api/providers stub), 4897-4903 (OpenRouter status), 4952-5010 (storage status implementation to mirror), 1344 (StrongWall comment to remove)
- `providers/synthetic_api.py` — Full SyntheticApiClient with model discovery, caching, capability-based categorization
- `core/agent_manager.py` — PROVIDER_MODELS dict, resolve_model(), /api/agents/models endpoint (line 495), dynamic Synthetic.new model injection at startup
- `core/key_store.py` — ADMIN_CONFIGURABLE_KEYS, key management patterns
- `core/config.py` — Settings dataclass, dead provider comments (lines 50-53)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `orStatus` card pattern — lazy-loaded status card in Providers panel. Synthetic model catalog follows this exactly.
- `secret-status` CSS classes — `configured`/`not-configured` badges already in use for every key field.
- `health-dot` CSS classes — `h-ok`, `h-auth_error`, `h-error`, `h-unavailable` variants ready for provider status.
- Storage status endpoint (`/api/settings/storage`) — real HTTP pings to services, returns structured status. Mirror for provider health.
- `loadOrStatus()` async function — auto-load on tab enter, render on result. Pattern for both model catalog and provider status.
- `SyntheticApiClient` — full model discovery with caching, capability categorization, and `update_provider_models_mapping()`.
- `GET /api/agents/models` — already returns live PROVIDER_MODELS dict. Frontend just needs to consume it.

### Established Patterns
- **Settings panel rendering:** `renderSettingsPanel()` with tab switch, HTML template strings, `state` object for lazy-loaded data.
- **Lazy-load pattern:** `if (!state.X) { loadX().then(renderSettingsPanel); return loading_html; }`
- **Table pattern:** `table-wrap > table > thead + tbody` with expandable rows (Tools, Skills pages).
- **Badge pattern:** `badge-source`, `badge-category`, `badge-type` CSS classes exist for capability badges.
- **XSS safety:** All user-facing data passed through `esc()` helper function.

### Integration Points
- `dashboard/server.py` — New endpoints: `/api/providers/synthetic/models`, `/api/settings/provider-status`
- `dashboard/frontend/dist/app.js` — Providers tab restructure, new lazy-load functions, agent form dynamic dropdown
- `dashboard/frontend/dist/style.css` — Minimal additions: `badge-free`/`badge-paid` variants
- `core/agent_manager.py` — No changes needed (PROVIDER_MODELS and /api/agents/models already exist)

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

*Phase: 38-provider-ui-updates*
*Context gathered: 2026-04-04*

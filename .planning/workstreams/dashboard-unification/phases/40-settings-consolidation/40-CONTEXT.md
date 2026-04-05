# Phase 40: Settings Consolidation - Context

**Gathered:** 2026-04-04
**Status:** Ready for planning

<domain>
## Phase Boundary

Streamlined settings management that works in both Paperclip and standalone modes. Expand the Paperclip SettingsPage.tsx with tabbed sections mirroring the standalone dashboard. Unified API key management with enhanced proxy view. New Memory & Learning settings surface. Full tool/skill toggle control from both modes.

Requirements: SETTINGS-01, SETTINGS-02, SETTINGS-03, SETTINGS-04.

</domain>

<decisions>
## Implementation Decisions

### Tab Structure (SETTINGS-01)
- **D-01:** Expand Paperclip `SettingsPage.tsx` with tabbed sections — not iframe, not deep-link. Same sidecar endpoints, React UI.
- **D-02:** Paperclip mode tabs: API Keys, Security (no password section), Orchestrator, Storage & Paths, Memory & Learning, Rewards. 6 tabs total.
- **D-03:** Standalone mode tabs: Providers (API Keys), Security (full), Orchestrator, Storage & Paths, Memory & Learning, Rewards. 6 visible tabs (Repos/Channels already hidden).
- **D-04:** Rewards stays as its own tab in both modes — not folded into Orchestrator.
- **D-05:** Security tab in Paperclip mode hides the "Change Password" section and `DASHBOARD_PASSWORD_HASH` — auth is handled by Paperclip. Sandbox/CORS/rate limit settings remain.

### API Key Management (SETTINGS-02)
- **D-06:** Enhanced proxy view in Paperclip — extend SettingsPage.tsx with source badge (admin/env), show/hide toggle, clear button, and help text per key. Not full standalone parity.
- **D-07:** Add `source: "admin" | "env" | "none"` field to sidecar `SidecarSettingsKeyEntry` Pydantic model. One field populated from `get_masked_keys()`.
- **D-08:** Honor `value: ""` in sidecar `POST /settings` as a `delete_key()` call — enables clear/delete from Paperclip UI.
- **D-09:** Add static help-text lookup map in SettingsPage.tsx keyed by `ADMIN_CONFIGURABLE_KEYS` — no backend changes needed for help strings.
- **D-10:** Non-key settings (channels, password hash, MODEL_ROUTING_POLICY, IMAP credentials) remain standalone-only. Not surfaced in Paperclip.

### Memory & Learning Configuration (SETTINGS-03)
- **D-11:** New dedicated "Memory & Learning" tab in both standalone dashboard and Paperclip SettingsPage. Separate from Storage & Paths.
- **D-12:** Backend status display — wire existing `GET /api/settings/storage` into the memory tab showing active mode, Qdrant/Redis health, effective vs configured mode.
- **D-13:** Memory stats panel — wire existing `GET /api/memory/stats` showing recall_count, learn_count, error_count, avg_latency_ms as read-only cards.
- **D-14:** Learning toggle — add `LEARNING_ENABLED` boolean to Settings config + `_DASHBOARD_EDITABLE_SETTINGS`. Honor in `learn_async()` and `EffectivenessStore.drain_pending_transcripts()`. UI toggle in both modes.
- **D-15:** Purge controls — expose `QdrantStore.clear_collection()` via `DELETE /api/settings/memory/{collection}` with admin auth + confirmation dialog. Global scope only (no per-agent purge). Irreversible action needs guards.
- **D-16:** Consolidation + CC sync status — show last_run, entries scanned/removed/flagged, last CC sync time. Already in `GET /api/settings/storage` response, free to display.
- **D-17:** Defer: backend switching post-setup (needs migration), embedding model selection UI (dimension mismatch danger), advanced threshold tuning.

### Tool/Skill Toggle Controls (SETTINGS-04)
- **D-18:** Full toggle control in Paperclip — add `toggleTool(name, enabled)` and `toggleSkill(name, enabled)` methods to `client.ts`. Add corresponding action handlers in `worker.ts`.
- **D-19:** Backend PATCH endpoints (`/api/tools/{name}`, `/api/skills/{name}`) already exist and are unguarded (active in both modes). No new backend work needed.
- **D-20:** ~50 lines of new code: 2 client methods + 2 action handler registrations in worker.ts.

### Claude's Discretion
- Whether tool/skill toggles live in the Settings tab or stay in existing Tools/Skills panels in Paperclip
- Exact tab ordering and labels in Paperclip SettingsPage
- CSS styling for source badges, help text layout, status cards
- Loading/skeleton states for sidecar-proxied settings
- Confirmation dialog design for purge controls
- Memory stats card layout and refresh behavior
- How to handle sidecar unreachable state in each settings tab

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/workstreams/dashboard-unification/ROADMAP.md` — Phase 40 success criteria (4 acceptance tests)

### Prior phase context (dependencies)
- `.planning/workstreams/dashboard-unification/phases/38-provider-ui-updates/38-CONTEXT.md` — Provider tab structure (D-01 through D-20), lazy-load pattern, settingSecret() helper, provider status endpoint
- `.planning/workstreams/dashboard-unification/phases/39-unified-agent-management/39-CONTEXT.md` — Unified proxy pattern (D-02), source badges (D-01), sparkline rendering, stats-row pattern

### Existing codebase (key files to read)
- `dashboard/frontend/dist/app.js` — `renderSettings()` (line 7903), `renderSettingsPanel()` (line 7931), tab structure (lines 7907-7914), `settingSecret()` (line 8288), settings panels object (line 7940)
- `dashboard/frontend/dist/style.css` — settings-grid, settings-nav, secret-status CSS classes
- `dashboard/server.py` — Settings endpoints: `/api/settings/keys` (line 4997), `/api/settings/env` (line 5035), `/api/settings/storage` (line 5137), `/api/settings/provider-status` (line 4854), `/api/settings/password` (line 809). Tool/skill PATCH: lines 4940, 4976
- `core/config.py` — Settings dataclass (line 40), `_DASHBOARD_EDITABLE_SETTINGS`
- `core/key_store.py` — `ADMIN_CONFIGURABLE_KEYS`, `get_masked_keys()`, `set_key()`, `delete_key()`
- `plugins/agent42-paperclip/src/ui/SettingsPage.tsx` — Current API key-only settings UI
- `plugins/agent42-paperclip/src/worker.ts` — `agent42-settings` data handler (line 125), `update-agent42-settings` action handler (line 159), `tools-skills` data handler (line 101)
- `plugins/agent42-paperclip/src/client.ts` — `getSettings()` (line 327), `updateSettings()` (line 338), `getTools()`, `getSkills()`
- `plugins/agent42-paperclip/src/types.ts` — `SidecarSettingsKeyEntry` type (line 267)
- `memory/qdrant_store.py` — `clear_collection()` method (line ~414)
- `dashboard/sidecar.py` — Sidecar Pydantic models, settings proxy endpoints

### Memory/learning system
- `core/memory_store.py` or equivalent — memory backend initialization, `learn_async()`
- `core/effectiveness_store.py` or equivalent — `drain_pending_transcripts()`, learning extraction

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `settingSecret()` / `settingReadonly()` / `settingSelect()` / `settingEditable()` — standalone helper functions for settings UI. Paperclip needs React equivalents.
- `renderSettingsPanel()` — tab-switching pattern with panels object. Mirror in React with state-based tab navigation.
- `loadOrStatus()` / `loadProviderStatus()` / `loadStorageStatus()` — lazy-load patterns for async settings data. Paperclip uses `usePluginData()` hook equivalent.
- `GET /api/settings/storage` — returns full storage + memory status including consolidation and CC sync. Already comprehensive.
- `GET /api/memory/stats` — returns 24h memory counters. Ready to consume.
- `QdrantStore.clear_collection()` — purge method exists, just needs API exposure.
- `PATCH /api/tools/{name}` and `PATCH /api/skills/{name}` — toggle endpoints exist, unguarded, active in both modes.

### Established Patterns
- **Tab-based settings:** `settings-nav` with active state, `settings-panel` content area. Each tab is a function returning HTML.
- **Lazy-load pattern:** `if (!state.X) { loadX().then(render); return loading_html; }` — use in both standalone and Paperclip.
- **Mode awareness:** `state.standaloneMode` for standalone, `sidecar_enabled` for Paperclip mode. Condition tab/section visibility on mode.
- **XSS safety:** All user-facing data through `esc()` in standalone. React handles this automatically via JSX.
- **Secret field pattern:** masked value display, toggle show/hide, source badge (admin/env), clear button.

### Integration Points
- `dashboard/sidecar.py` — Add `source` field to settings key response. Add memory stats proxy. Add purge proxy endpoint.
- `plugins/agent42-paperclip/src/client.ts` — Add `toggleTool()`, `toggleSkill()`, `getMemoryStats()`, `purgeMemory()` methods.
- `plugins/agent42-paperclip/src/worker.ts` — Add action handlers for toggle-tool, toggle-skill, purge-memory.
- `plugins/agent42-paperclip/src/ui/SettingsPage.tsx` — Major expansion: tabbed layout, 6 sections, enhanced key management.
- `dashboard/server.py` — Add `LEARNING_ENABLED` to editable settings. Add `DELETE /api/settings/memory/{collection}` endpoint.
- `core/config.py` — Add `learning_enabled: bool = True` to Settings dataclass.

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

- Backend switching post-setup (requires data migration code, no existing migration path)
- Embedding model selection UI (dimension mismatch danger if switching after vectors stored)
- Advanced threshold tuning (consolidation thresholds, score threshold — too granular for settings tab)
- Per-agent memory purge (global scope only for Phase 40)
- Batch key save in Paperclip (single-key save acceptable for 11 keys)

</deferred>

---

*Phase: 40-settings-consolidation*
*Context gathered: 2026-04-04*

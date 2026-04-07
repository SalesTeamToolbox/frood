# Phase 35: Paperclip Integration - Research

**Researched:** 2026-04-06
**Domain:** Sidecar API extension + Paperclip plugin TypeScript
**Confidence:** HIGH (all findings from direct code inspection)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Scope Phase 35 to what's achievable with current infrastructure. UI-01 is fully deliverable. UI-02, UI-03, UI-04 require stubs/interfaces that can be wired up when Phases 32+33 are complete.
- **D-02:** Create sidecar endpoint contracts (request/response types) for model discovery and provider status NOW, even if the implementation returns placeholder data. This lets Paperclip UI be built against stable interfaces.
- **D-03:** Paperclip plugin calls `TieredRoutingBridge.resolve()` via sidecar endpoints exclusively. No parallel provider logic in the plugin. The sidecar is the single source of truth for routing decisions.
- **D-04:** Agent role (engineer/researcher/writer/analyst) must be passed via adapter-run action to sidecar. `tiered_routing_bridge.py:34-42` maps roles to categories for model selection. Missing role falls back to "general" category (line 170).
- **D-05:** New sidecar endpoint `GET /sidecar/models` returns available models grouped by provider. Response includes model ID, display name, provider, and capabilities (when available). Currently returns models from PROVIDER_MODELS registry; will return dynamic Synthetic.new models once Phase 33 is implemented.
- **D-06:** Model list is consumed by agent configuration UI for model selection dropdown.
- **D-07:** Enhance `GET /sidecar/health` response to include per-provider connectivity status (not just boolean "configured" flags). Each provider entry: `{name, configured, connected, model_count, last_check}`. Currently only Zen and hardcoded providers report; CC Subscription and Synthetic.new will report once Phases 32+33 land.
- **D-08:** Add SYNTHETIC_API_KEY to Paperclip SettingsPage "API Keys" tab alongside existing provider keys. The manifest.ts already documents this key. KEY_HELP entry needed in SettingsPage.tsx.
- **D-09:** Existing agents without role metadata fall back to "general" category. No migration needed — `tiered_routing_bridge.py` handles None/empty role with `.get(role or "", "general")`.
- **D-10:** Reward tier (gold/silver/bronze/provisional) comes from Agent42's RewardSystem. Paperclip adapter must NOT override tier. Cost estimation is deferred (current cost_estimate=0.0 is intentional per prior phase decisions).

### Claude's Discretion

- Exact response schema fields for /sidecar/models (beyond the required fields above)
- Loading/skeleton states for provider health widget
- Error handling when sidecar is unreachable from plugin

### Deferred Ideas (OUT OF SCOPE)

- **Phase 32 execution** — Provider Selection Core (CC Subscription as primary, Synthetic.new as fallback). Must be done before UI-02/03/04 can show real data.
- **Phase 33 execution** — Synthetic.new Integration (dynamic model discovery, 24h refresh, health check). Must be done before UI-02/03 can list real models.
- **Cost estimation wiring** — RoutingDecision.cost_estimate is intentionally 0.0 until AgentRuntime wires real token counts (deferred from earlier phases).
- **Real-time provider status updates** — Plugin currently polls via data handlers. WebSocket push for live health status is a future enhancement.
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | Update Paperclip plugin to work with simplified provider selection system | Direct code inspection: plugin currently has no L1/L2 references; tiered_routing_bridge.py drives routing. Likely already satisfied except for stale config references. Verify health endpoint configured_providers dict still names correct providers after Phase 34 removals. |
| UI-02 | Provider selection dashboard shows available models from Synthetic.new | Requires new GET /sidecar/models endpoint (D-05). PROVIDER_MODELS dict in agent_manager.py is the data source. Returns stub data now; wired to Synthetic.new API when Phase 33 lands. |
| UI-03 | Agent configuration UI allows selection from dynamically discovered models | Requires GET /sidecar/models response consumed by a new Paperclip UI component. Stub response sufficient for Phase 35; real data from Phase 33. |
| UI-04 | Provider status dashboard shows Claude Code Subscription and Synthetic.new connectivity | Requires enhanced GET /sidecar/health (D-07). Current health endpoint only has boolean "configured" flags; needs per-provider `{name, configured, connected, model_count, last_check}` structure. CC Subscription and Synthetic.new will return connected=false until Phases 32+33. |
</phase_requirements>

---

## Summary

Phase 35 is a sidecar API + Paperclip plugin integration phase with two distinct work streams: (1) server-side: extend `dashboard/sidecar.py` with new endpoints and enhance the existing health endpoint, and (2) client-side: extend the TypeScript plugin (`client.ts`, `types.ts`, `worker.ts`, `ProviderHealthWidget.tsx`) to consume those endpoints.

The critical constraint is that Phases 32 and 33 have NOT been executed. The plan must deliver fully functional stubs that let the Paperclip UI be built against stable API contracts. When upstream phases land, only the sidecar implementation bodies change — plugin code and TypeScript types remain stable.

**Primary recommendation:** Add `GET /sidecar/models` and enhance `GET /sidecar/health` in `dashboard/sidecar.py` with matching Pydantic models in `core/sidecar_models.py`. Add `SYNTHETIC_API_KEY` to `core/key_store.py:ADMIN_CONFIGURABLE_KEYS` and `core/config.py:Settings`. Wire the plugin client, data handler, and ProviderHealthWidget to consume the enhanced responses.

---

## Standard Stack

### Core (Python - Sidecar API)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| FastAPI | existing | Endpoint routing | All sidecar endpoints use FastAPI |
| Pydantic v2 | existing | Request/response models | Established pattern in `core/sidecar_models.py` |
| asyncio | stdlib | Async handlers | All I/O is async per CLAUDE.md |

### Core (TypeScript - Plugin)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| @paperclipai/plugin-sdk | existing | Plugin lifecycle, data/action registration | All plugin code uses this |
| Native fetch | Node 18+ | HTTP client in plugin | Already used by `Agent42Client` in client.ts |
| React | existing | UI components | All plugin UI uses React |

### No New Dependencies Required
This phase adds no new library dependencies. All required APIs are already in the codebase.

---

## Architecture Patterns

### Established Extension Pattern for Sidecar Endpoints

All new endpoints follow this exact 3-file pattern (confirmed by reading source):

1. **`core/sidecar_models.py`** — Add Pydantic response model
2. **`dashboard/sidecar.py`** — Add `@app.get(...)` handler in `create_sidecar_app()`
3. **`core/key_store.py`** — Add configurable keys to `ADMIN_CONFIGURABLE_KEYS` frozenset

```python
# Source: dashboard/sidecar.py (Phase 36 pattern — replicate exactly)
@app.get("/sidecar/models", response_model=ModelsResponse)
async def sidecar_models() -> ModelsResponse:
    """Return available models grouped by provider. Public — no auth per D-05 analogy."""
    ...
```

### PROVIDER_MODELS Structure (current)
```python
# Source: core/agent_manager.py:31-65
PROVIDER_MODELS = {
    "zen": {
        "fast": "qwen3.6-plus-free",
        "general": "minimax-m2.5-free",
        "reasoning": "nemotron-3-super-free",
        "coding": "qwen3.6-plus-free",
        ...
    },
    "openrouter": { "fast": ..., "general": ..., "reasoning": ..., ... },
    "anthropic":  { "fast": ..., "general": ..., "reasoning": ..., ... },
    "openai":     { "fast": ..., "general": ..., "reasoning": ..., ... },
}
```

The `/sidecar/models` endpoint serializes this dict into a flat list of `{model_id, display_name, provider, categories}` entries.

### Existing Health Response Shape (current)
```python
# Source: core/sidecar_models.py:58-64
class HealthResponse(BaseModel):
    status: str = "ok"
    memory: dict[str, Any] = Field(default_factory=dict)
    providers: dict[str, Any] = Field(default_factory=dict)
    qdrant: dict[str, Any] = Field(default_factory=dict)
```

The `providers` dict currently contains:
```json
{
  "available": true,
  "configured": {
    "openai": true,
    "anthropic": false,
    "openrouter": true,
    "groq": false
  }
}
```

D-07 requires enhancing to per-provider objects: `{name, configured, connected, model_count, last_check}`.

Two options:
1. Add a new `providers_detail` field to `HealthResponse` while keeping `configured` for backward compatibility (RECOMMENDED — avoids breaking existing plugin code).
2. Replace `configured` dict with the new structure (BREAKING — requires updating `ProviderHealthWidget.tsx` simultaneously).

Go with option 1 (additive, backward-safe).

### Plugin Data Handler Pattern
```typescript
// Source: plugins/agent42-paperclip/src/worker.ts:55-63
ctx.data.register("provider-health", async (_params) => {
  if (!client) return null;
  try {
    return await client.health();
  } catch (e) {
    ctx.logger.warn("provider-health data handler failed", { error: String(e) });
    return null;
  }
});
```

New data handlers follow this exact pattern. New endpoints need:
- A new data handler registered in `worker.ts`
- A corresponding client method in `client.ts`
- A TypeScript interface in `types.ts`
- A React component that consumes it via `usePluginData()`

### SettingsPage KEY_HELP Pattern
```typescript
// Source: plugins/agent42-paperclip/src/ui/SettingsPage.tsx:7-18
const KEY_HELP: Record<string, string> = {
  OPENROUTER_API_KEY: "...",
  OPENAI_API_KEY: "...",
  ANTHROPIC_API_KEY: "...",
  SYNTHETIC_API_KEY: "Synthetic.new Anthropic-compatible API. Get key at synthetic.new/dashboard",
  ...
};
```

`SYNTHETIC_API_KEY` is **already present** in `KEY_HELP` in `SettingsPage.tsx`. The missing piece is adding `"SYNTHETIC_API_KEY"` to `ADMIN_CONFIGURABLE_KEYS` in `core/key_store.py` and `synthetic_api_key` to the `Settings` dataclass in `core/config.py`.

### Anti-Patterns to Avoid

- **Breaking the HealthResponse schema:** The `ProviderHealthWidget` reads `data.providers?.configured`. Adding a `providers_detail` field preserves this. Do NOT restructure the existing `configured` key.
- **Adding auth to /sidecar/health:** It is public by design (D-05). `/sidecar/models` should also be public so Paperclip can pre-probe before credentials are provisioned.
- **Blocking asyncio in endpoint handlers:** All I/O must remain async per CLAUDE.md.
- **Hardcoding model lists in TypeScript:** Plugin should call `GET /sidecar/models`; never embed a model list in plugin code.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Model serialization | Custom model list builder | Iterate `PROVIDER_MODELS` dict directly | It's already the central registry |
| API key validation | Custom validation code | `ADMIN_CONFIGURABLE_KEYS` frozenset check in sidecar.py | Pattern established in Phase 36 |
| TypeScript HTTP client | New HTTP library | Extend `Agent42Client` with a new method | Already has retry, timeout, auth headers |
| Provider connectivity check | Active HTTP probe per request | Flag `connected=False` until Phase 33 provides health check | Prevents latency on every health call |

---

## Common Pitfalls

### Pitfall 1: SYNTHETIC_API_KEY Already in KEY_HELP but NOT in ADMIN_CONFIGURABLE_KEYS
**What goes wrong:** D-08 says "add SYNTHETIC_API_KEY to SettingsPage." Reading the SettingsPage source reveals the KEY_HELP entry already exists. But the key will NOT appear in the settings list unless it is in `ADMIN_CONFIGURABLE_KEYS` in `core/key_store.py`.
**Why it happens:** KEY_HELP is a static TypeScript dict; ADMIN_CONFIGURABLE_KEYS drives what `GET /settings` returns. They are independent.
**How to avoid:** Add `"SYNTHETIC_API_KEY"` to the `ADMIN_CONFIGURABLE_KEYS` frozenset in `core/key_store.py` AND add `synthetic_api_key: str = ""` to `Settings` dataclass with `from_env()` mapping. Both changes needed.
**Warning signs:** Settings page renders no row for SYNTHETIC_API_KEY despite KEY_HELP entry.

### Pitfall 2: Health Endpoint Backward Compatibility Break
**What goes wrong:** Replacing `providers.configured` with new per-provider objects breaks `ProviderHealthWidget.tsx` which reads `data.providers?.configured` as `Record<string, boolean>`.
**Why it happens:** The new D-07 schema uses objects where the current schema uses booleans.
**How to avoid:** Add `providers_detail` as a new field alongside the existing `configured` dict. Update `ProviderHealthWidget` to consume `providers_detail` if present, fallback to `configured` for backward compat.
**Warning signs:** Provider health widget shows "Health data unavailable" or JS TypeError after endpoint change.

### Pitfall 3: /sidecar/models Endpoint Auth Decision
**What goes wrong:** Adding Bearer auth to `/sidecar/models` blocks Paperclip from calling it before credentials are set (same reason `/sidecar/health` is public).
**Why it happens:** Default FastAPI pattern adds `_user: str = Depends(get_current_user)`.
**How to avoid:** Make `/sidecar/models` public (no auth dependency), consistent with `/sidecar/health`.
**Warning signs:** 401 errors in plugin logs during initial setup.

### Pitfall 4: PROVIDER_MODELS "synthetic" Key Doesn't Exist Yet
**What goes wrong:** Serializing PROVIDER_MODELS for `/sidecar/models` will include zen, openrouter, anthropic, openai — but NOT "synthetic". Phase 33 will add it. The stub response must handle this gracefully.
**Why it happens:** Phase 33 is not executed.
**How to avoid:** `/sidecar/models` should include a `synthetic` provider entry with empty `models: []` and `available: false` as a placeholder. When Phase 33 lands, the implementation fills it.
**Warning signs:** UI-02 model dropdown missing Synthetic.new provider row entirely.

### Pitfall 5: Zen Models are Free-Tier and Category-Mapped (not model-id-selectable)
**What goes wrong:** Exposing `PROVIDER_MODELS["zen"]` as a model list suggests users can "select" `qwen3.6-plus-free` by name. But Zen selection actually happens through category routing (`fast`, `general`, `reasoning`) not direct model ID selection.
**Why it happens:** The /sidecar/models contract is meant for display (UI-02) and future Phase 33 model selection (UI-03). For now, listing Zen categories as "models" is acceptable.
**How to avoid:** In the response, include the `categories` field alongside `model_id` so the UI can show "qwen3.6-plus-free (fast, coding)" rather than treating it as a directly selectable model. Future Phase 33 work will introduce Synthetic.new models that ARE directly selectable.
**Warning signs:** User tries to set agent model to "qwen3.6-plus-free" and routing ignores it.

---

## Code Examples

### Proposed ModelsResponse Schema (Python)
```python
# To add to core/sidecar_models.py
from pydantic import BaseModel, Field

class ProviderModelItem(BaseModel):
    """A single model entry in the /sidecar/models response."""
    model_id: str
    display_name: str
    provider: str
    categories: list[str] = Field(default_factory=list)  # e.g. ["fast", "coding"]
    available: bool = True  # False when provider not configured

class ModelsResponse(BaseModel):
    """Response body for GET /sidecar/models."""
    models: list[ProviderModelItem] = Field(default_factory=list)
    providers: list[str] = Field(default_factory=list)  # ["zen", "openrouter", ...]
```

### Serializing PROVIDER_MODELS for the endpoint
```python
# In dashboard/sidecar.py — GET /sidecar/models handler body
from core.agent_manager import PROVIDER_MODELS

items = []
for provider, category_map in PROVIDER_MODELS.items():
    # Group by model_id, collect categories
    model_to_cats: dict[str, list[str]] = {}
    for cat, model_id in category_map.items():
        model_to_cats.setdefault(model_id, []).append(cat)
    for model_id, cats in model_to_cats.items():
        items.append(ProviderModelItem(
            model_id=model_id,
            display_name=model_id,
            provider=provider,
            categories=cats,
            available=True,  # Phase 33 will add real availability check
        ))
# Add synthetic stub (Phase 33 wires real data)
# items += synthetic_models_if_phase33_available()
```

### Enhanced HealthResponse (additive, backward-safe)
```python
# Extend existing HealthResponse in core/sidecar_models.py
class ProviderStatusDetail(BaseModel):
    """Per-provider status detail for enhanced health response."""
    name: str
    configured: bool = False
    connected: bool = False     # False until Phase 32/33 provide connectivity check
    model_count: int = 0
    last_check: float = 0.0     # Unix timestamp, 0 = never checked

class HealthResponse(BaseModel):
    status: str = "ok"
    memory: dict[str, Any] = Field(default_factory=dict)
    providers: dict[str, Any] = Field(default_factory=dict)   # keep existing
    providers_detail: list[ProviderStatusDetail] = Field(default_factory=list)  # NEW
    qdrant: dict[str, Any] = Field(default_factory=dict)
```

### TypeScript types for new endpoints
```typescript
// To add to plugins/agent42-paperclip/src/types.ts

export interface ProviderModelItem {
  model_id: string;
  display_name: string;
  provider: string;
  categories: string[];
  available: boolean;
}

export interface ModelsResponse {
  models: ProviderModelItem[];
  providers: string[];
}

export interface ProviderStatusDetail {
  name: string;
  configured: boolean;
  connected: boolean;
  model_count: number;
  last_check: number;
}

// Extend SidecarHealthResponse to add providers_detail
export interface SidecarHealthResponse {
  status: string;
  memory: { available: boolean; [key: string]: unknown };
  providers: { available: boolean; configured?: Record<string, boolean>; [key: string]: unknown };
  providers_detail?: ProviderStatusDetail[];   // NEW — D-07
  qdrant: { available: boolean; [key: string]: unknown };
}
```

### Client method for GET /sidecar/models
```typescript
// To add to plugins/agent42-paperclip/src/client.ts
async getModels(): Promise<ModelsResponse> {
  const resp = await this.fetchWithRetry(
    `${this.baseUrl}/sidecar/models`,
    { method: "GET", headers: { "Content-Type": "application/json" } }, // no auth — public
    this.timeoutMs,
  );
  if (!resp.ok) throw new Error(`Agent42Client.getModels failed: HTTP ${resp.status}`);
  return resp.json() as Promise<ModelsResponse>;
}
```

### Data handler registration in worker.ts
```typescript
// To add inside setup() in plugins/agent42-paperclip/src/worker.ts
ctx.data.register("available-models", async (_params) => {
  if (!client) return null;
  try {
    return await client.getModels();
  } catch (e) {
    ctx.logger.warn("available-models data handler failed", { error: String(e) });
    return null;
  }
});
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| L1/L2 tiered routing with StrongWall | TieredRoutingBridge with zen/openrouter/anthropic/openai chain | Phase 34 (2026-04-06) | Health endpoint `configured_providers` must NOT include `strongwall` |
| STRONGWALL_API_KEY in ADMIN_CONFIGURABLE_KEYS | Removed | Phase 32 (per dashboard-api-update-summary.md) | Confirmed absent from key_store.py |
| HealthResponse.providers = {configured: {provider: bool}} | Same (no changes yet) | — | D-07 extends this with providers_detail list |

**Current ADMIN_CONFIGURABLE_KEYS (verified from source):**
```
ZEN_API_KEY, OPENROUTER_API_KEY, ANTHROPIC_API_KEY, OPENAI_API_KEY,
GEMINI_API_KEY, REPLICATE_API_TOKEN, LUMA_API_KEY, BRAVE_API_KEY, GITHUB_TOKEN
```

**Missing from ADMIN_CONFIGURABLE_KEYS (needed for D-08):**
- `SYNTHETIC_API_KEY` — not in key_store.py frozenset
- `DEEPSEEK_API_KEY`, `CEREBRAS_API_KEY` — also absent (out of scope)

**Current Settings dataclass (verified — no `synthetic_api_key` field):**
The `Settings` dataclass does NOT have a `synthetic_api_key` field. The Phase 33 research doc and Phase 41 plan both show it as a planned addition. This phase must add it to Config to allow KeyStore injection.

**SYNTHETIC_API_KEY in SettingsPage.tsx KEY_HELP — already present (line 11).** No change needed to this file for D-08 beyond confirming the key appears in API Keys tab (which requires ADMIN_CONFIGURABLE_KEYS addition).

---

## Open Questions

1. **Should /sidecar/models require auth?**
   - What we know: `/sidecar/health` is public (D-05). Models list contains no secrets.
   - What's unclear: The CONTEXT.md doesn't explicitly address auth for /sidecar/models.
   - Recommendation: Make it public (no auth). Consistent with /sidecar/health. Allows Paperclip to probe available providers before credentials are provisioned.

2. **Does TieredRoutingBridge need to know about SYNTHETIC_API_KEY in the provider chain?**
   - What we know: Current `resolve()` checks `ZEN_API_KEY` -> `OPENROUTER_API_KEY` -> `ANTHROPIC_API_KEY` -> `OPENAI_API_KEY`. No `SYNTHETIC_API_KEY` check.
   - What's unclear: D-03 says plugin calls TieredRoutingBridge via sidecar exclusively. But Phase 35 doesn't change the routing chain — that's Phase 32's job.
   - Recommendation: Do NOT modify `tiered_routing_bridge.py` in Phase 35. That change belongs to Phase 32.

3. **Does `/sidecar/health` include `connected` status for zen provider?**
   - What we know: Zen has a `get_zen_client()` and `list_models()`. In theory, a connectivity check is possible.
   - What's unclear: Calling `list_models()` on every health probe adds latency. D-07 says `last_check` field — implies cached status, not live probe.
   - Recommendation: Populate `connected=True` based on whether `zen_api_key` is set (or `zen_client.is_healthy()` if it exists), not by doing a live API call. Set `last_check=0.0` (stub) for Phase 35; real probing comes in Phase 32/33.

---

## Environment Availability

Step 2.6: SKIPPED — Phase 35 is code/config changes only. No external dependencies beyond the existing Python virtualenv and Node.js environment already in use for the plugin.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (confirmed: `python -m pytest tests/ -x -q` per CLAUDE.md) |
| Config file | pytest.ini or pyproject.toml (project root) |
| Quick run command | `python -m pytest tests/test_sidecar.py tests/test_sidecar_phase36.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | Plugin works with simplified provider system (no L1/L2 refs, health endpoint accurate) | unit | `pytest tests/test_sidecar.py -k health -x -q` | ✅ |
| UI-02 | GET /sidecar/models returns models grouped by provider | unit | `pytest tests/test_sidecar_phase35.py -k models -x -q` | ❌ Wave 0 |
| UI-03 | ModelsResponse schema serializes PROVIDER_MODELS correctly | unit | `pytest tests/test_sidecar_phase35.py -k models_schema -x -q` | ❌ Wave 0 |
| UI-04 | GET /sidecar/health returns providers_detail list with per-provider fields | unit | `pytest tests/test_sidecar_phase35.py -k health_detail -x -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_sidecar.py tests/test_sidecar_phase35.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_sidecar_phase35.py` — covers UI-02, UI-03, UI-04 endpoint behavior
  - `test_get_models_returns_provider_list` — GET /sidecar/models returns 200 with models array
  - `test_get_models_includes_all_providers` — all 4 providers (zen, openrouter, anthropic, openai) present
  - `test_get_models_no_auth_required` — endpoint is public (no Bearer needed)
  - `test_health_includes_providers_detail` — GET /sidecar/health now includes `providers_detail` list
  - `test_health_providers_detail_schema` — each item has name/configured/connected/model_count/last_check
  - `test_synthetic_key_in_admin_configurable` — `"SYNTHETIC_API_KEY" in ADMIN_CONFIGURABLE_KEYS`
  - `test_synthetic_key_in_settings_dataclass` — `hasattr(Settings(), "synthetic_api_key")`

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 35 |
|-----------|-------------------|
| All I/O is async (`aiofiles`, `httpx`, `asyncio`) — never blocking | Sidecar endpoint handlers must use `async def`; no synchronous HTTP calls |
| `Settings` dataclass in `core/config.py` — add fields there + `from_env()` + `.env.example` | Adding `synthetic_api_key` requires 3 changes: Settings field, from_env() line, .env.example comment |
| Sandbox always on — validate paths via `sandbox.resolve_path()` | Not applicable (no file path operations in this phase) |
| New modules need `tests/test_*.py` | New sidecar endpoints need `tests/test_sidecar_phase35.py` |
| GSD workflow enforcement — no direct repo edits outside GSD | Planner must structure tasks within GSD conventions |
| NEVER log API keys, passwords, or tokens | GET /sidecar/models and health enhancement must not echo back key values |

---

## Sources

### Primary (HIGH confidence)
- Direct code inspection: `core/tiered_routing_bridge.py` — resolve() logic, _ROLE_CATEGORY_MAP, provider chain
- Direct code inspection: `core/agent_manager.py` — PROVIDER_MODELS dict structure and contents
- Direct code inspection: `dashboard/sidecar.py` — all existing endpoints, HealthResponse handler
- Direct code inspection: `core/sidecar_models.py` — HealthResponse, all Pydantic models
- Direct code inspection: `core/key_store.py` — ADMIN_CONFIGURABLE_KEYS frozenset (verified `SYNTHETIC_API_KEY` absent)
- Direct code inspection: `core/config.py` — Settings dataclass (verified `synthetic_api_key` field absent)
- Direct code inspection: `plugins/agent42-paperclip/src/client.ts` — Agent42Client all methods
- Direct code inspection: `plugins/agent42-paperclip/src/types.ts` — all TypeScript interfaces
- Direct code inspection: `plugins/agent42-paperclip/src/worker.ts` — data handler pattern
- Direct code inspection: `plugins/agent42-paperclip/src/ui/ProviderHealthWidget.tsx` — current UI consuming health
- Direct code inspection: `plugins/agent42-paperclip/src/ui/SettingsPage.tsx` — KEY_HELP (SYNTHETIC_API_KEY already present)
- Direct code inspection: `plugins/agent42-paperclip/src/manifest.ts` — slots, tools, adapter definitions
- Direct code inspection: `.planning/config.json` — nyquist_validation: true

### Secondary (MEDIUM confidence)
- `.claude/reference/dashboard-api-update-summary.md` — confirms STRONGWALL_API_KEY removal from ADMIN_CONFIGURABLE_KEYS
- `.planning/phases/36-paperclip-integration-core/36-01-PLAN.md` — shows Phase 36 added SYNTHETIC_API_KEY to planned ADMIN_CONFIGURABLE_KEYS (plan only, not executed for this key)

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already in use; no new dependencies
- Architecture patterns: HIGH — read directly from source files
- Pitfalls: HIGH — identified from direct schema/code discrepancies found during research
- Key gaps (SYNTHETIC_API_KEY absent from key_store and config): HIGH — verified by reading both files

**Research date:** 2026-04-06
**Valid until:** 2026-05-06 (stable codebase, 30-day window)

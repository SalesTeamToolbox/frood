# Phase 16: StrongWall Provider - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Integrate StrongWall.ai (Kimi K2.5) as a working OpenAI-compatible LLM provider. Agent tasks dispatched to StrongWall receive complete, correctly parsed responses (including tool calls) without streaming-related errors. Health check reports availability. Graceful degradation when API key is not configured. Tier restructuring (L1/L2) is Phase 17. Simulated streaming for chat is Phase 20.

</domain>

<decisions>
## Implementation Decisions

### Health Check Behavior
- Lightweight API probe: hit the /models (or /v1/models) endpoint -- standard OpenAI-compatible, no tokens consumed
- Timeout threshold: if /models takes longer than ~5s, mark as degraded (detects queue congestion)
- Check frequency: every 60 seconds (background polling)
- Dashboard visibility: add StrongWall status to the existing /status or health dashboard page (green/yellow/red based on last check result)

### Cost Tracking
- Amortized daily cost: calculate ~$0.53/day ($16/30) and report as fixed daily cost
- Exempt from daily spending limit: flat-rate is already paid, don't let it trigger MAX_DAILY_API_SPEND_USD cap -- only per-token providers count
- Dashboard reporting: separate line item showing "Flat: $16/mo ($0.53/day)" distinct from per-token provider costs
- Monthly price configurable via env var: STRONGWALL_MONTHLY_COST=16 (auto-calculates amortized daily cost)
- Still track token usage for monitoring/analytics (volume metrics), just don't price per-token

### Pre-Phase-20 Chat Display
- Block response + typing indicator: show "thinking..." or typing dots while waiting, then display full response at once
- No provider label on messages: user doesn't need to know which provider generated the response
- Background agent tasks: no change needed -- non-streaming is fine, matches SambaNova stream=False precedent

### Model Identity & Naming
- Registry key: `strongwall-kimi-k2.5` (provider-prefixed, model-specific -- follows cerebras-gpt-oss-120b pattern)
- Display name: "Kimi K2.5 (StrongWall)" (model first, provider in parens -- follows existing convention)
- ModelTier: CHEAP (costs money but not premium; L1/L2 tier restructuring happens in Phase 17)
- ProviderType enum: add STRONGWALL value
- API key env var: STRONGWALL_API_KEY
- Base URL and model ID: researcher to determine from StrongWall.ai API documentation

### Claude's Discretion
- Exact typing indicator implementation (reuse existing patterns or new)
- ProviderSpec field additions (e.g., supports_streaming flag vs. provider-specific check like SambaNova)
- Health check degradation threshold (exact seconds for timeout)
- How to structure the health check polling loop (new service vs. extend existing)

</decisions>

<specifics>
## Specific Ideas

- SambaNova already sets `stream=False` for tool calls in `complete_with_tools` -- StrongWall should follow a similar pattern but for ALL requests (not just tool calls)
- Health check is a new concept at the provider level -- existing `ModelCatalog.is_model_healthy()` tracks model-level health from response errors, not proactive endpoint probing

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `ProviderRegistry._build_client()`: creates AsyncOpenAI client from ProviderSpec -- StrongWall uses same pattern
- `ProviderSpec` dataclass: declarative provider registration (base_url, api_key_env, etc.)
- `ModelSpec` + `MODELS` dict: model registration with tier, context size, display name
- `SpendingTracker._BUILTIN_PRICES`: per-model pricing lookup -- needs flat-rate extension
- SambaNova `stream=False` precedent in `complete_with_tools` (registry.py:706)

### Established Patterns
- Provider addition is 2-step: add ProviderType enum + ProviderSpec to PROVIDERS dict
- Model addition: add ModelSpec entries to MODELS dict with _BUILTIN_PRICES entry
- Provider-specific behavior handled via `if spec.provider == ProviderType.X` checks in complete methods
- Config fields added to Settings dataclass with os.getenv() in from_env()

### Integration Points
- `providers/registry.py`: ProviderType enum, PROVIDERS dict, MODELS dict, SpendingTracker
- `core/config.py`: Settings dataclass (add STRONGWALL_API_KEY, STRONGWALL_MONTHLY_COST fields)
- `agents/model_router.py`: _find_healthy_free_model, _find_healthy_cheap_model (StrongWall enters cheap pool)
- Dashboard /status endpoint: add StrongWall health indicator
- Dashboard /api/reports: add flat-rate cost line item

</code_context>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 16-strongwall-provider*
*Context gathered: 2026-03-06*

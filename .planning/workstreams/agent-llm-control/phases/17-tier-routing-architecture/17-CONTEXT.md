# Phase 17: Tier Routing Architecture - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Restructure model_router.py around L1/L2 tier concepts. StrongWall becomes the default L1 primary for all task types when configured. Existing free providers (Cerebras/Groq/Codestral/Gemini) become the fallback tier. L2 premium models (Claude Sonnet, GPT-4o, OR paid) serve as last-resort fallback and explicit-authorization escalation path. Backward compatible when StrongWall API key is not set. Per-agent config UI is Phase 18/19. Simulated streaming is Phase 20.

</domain>

<decisions>
## Implementation Decisions

### L1 Task-Type Behavior
- StrongWall serves as primary for ALL task types equally -- no exceptions or task-type specialization at L1 level
- When L1 is unavailable, fall back to task-type-aware FALLBACK_ROUTING table (Cerebras for coding, Groq for research, Gemini for general -- existing FREE_ROUTING entries)
- L1 reuses max_iterations from FALLBACK_ROUTING per task type (already tuned values: 12 for app_create, 8 for coding, etc.)
- ModelTier enum stays as-is (FREE/CHEAP/PAID) -- L1/L2 is a routing concept, not a cost tier. StrongWall remains ModelTier.CHEAP. No cascading changes to SpendingTracker, health checks, or catalog

### Resolution Chain Restructure
- Replace layer 3 (free defaults) with L1 check: "If L1 model is configured + healthy, use L1. Else fall back to FALLBACK_ROUTING."
- New resolution chain: (1) Admin override, (2) Dynamic routing, (3) L1 check / FALLBACK_ROUTING, (4) Policy routing, (5) Trial injection
- Configurable L1 model via `L1_MODEL` env var -- defaults to `strongwall-kimi-k2.5` when STRONGWALL_API_KEY is set. Future-proof for additional StrongWall models or alternative L1 providers
- Rename `FREE_ROUTING` dict to `FALLBACK_ROUTING` -- clearer semantics as it's no longer the default, just the fallback table
- Gemini Pro upgrade logic (layer 4b) still runs after L1 -- if user has paid Gemini key and GEMINI_PRO_FOR_COMPLEX is not false, complex tasks upgrade to Gemini Pro even over L1
- Existing policy routing (balanced/performance/free_only modes) stays as-is alongside L2 -- separate concern about OpenRouter credit usage

### L2 Escalation Conditions
- L2 activates as last-resort fallback when BOTH L1 AND free fallback providers are unavailable
- L2 also available via explicit user authorization: global allowlist by task type + per-task escalation through Approvals page
- Phase 17 builds routing logic only: an internal `l2_authorized` flag/mechanism that downstream phases (18/19) wire to the dashboard UI
- Existing _check_policy_routing() logic kept alongside L2 -- they are separate concerns

### Critic Pairing
- L1 model is the default critic when L1 is active -- self-critique with dedicated reviewer system prompt and skills (same model, different role framing)
- When L1 is down and primary falls back to FALLBACK_ROUTING, critic also reverts to FALLBACK_ROUTING critics (Codestral for code, OR free for others) -- clean degradation
- L2 also self-critiques: premium model serves as both primary and critic (with separate reviewer prompting), replacing the current `critic: None` in L2_ROUTING
- Critic override configurable per-agent -- deferred to Phase 18/19 per-agent config

### Claude's Discretion
- Exact implementation of L1 health check integration with routing (reuse existing _catalog.is_model_healthy or StrongWall-specific health)
- How to structure the l2_authorized flag internally (config field, runtime state, or parameter)
- Whether L1_MODEL validation happens at startup or lazily on first get_routing() call
- Test restructuring approach for renamed FALLBACK_ROUTING and new L1 paths

</decisions>

<specifics>
## Specific Ideas

- L1 self-critique is a key design choice: the same model reviews its own output but with a completely different system prompt framed as a code reviewer / quality auditor. This should feel like a separate agent, not a rubber stamp.
- The `L1_MODEL` env var pattern mirrors `AGENT42_CODING_MODEL` admin overrides -- familiar convention for operators.
- FALLBACK_ROUTING rename signals intent clearly to developers: "these are not defaults, they're fallbacks."

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `FREE_ROUTING` dict (model_router.py:33): task-type-specific routing table with primary/critic/max_iterations -- becomes FALLBACK_ROUTING
- `L2_ROUTING` dict (model_router.py:124): premium model routing table -- needs critic fields updated from None to self-critique
- `_find_healthy_free_model()` (model_router.py:464): provider-diverse round-robin for free models -- used in fallback path
- `_find_healthy_cheap_model()` (model_router.py:533): CHEAP-tier fallback -- StrongWall enters this pool
- `get_l2_routing()` (model_router.py:561): existing L2 routing method -- extend with l2_authorized check
- `_check_policy_routing()` (model_router.py:628): balanced/performance policy logic -- stays as-is

### Established Patterns
- 5-layer resolution chain in `get_routing()` (model_router.py:247): admin -> dynamic -> defaults -> policy -> trial
- Provider API key validation via `os.getenv()` at routing time (not Settings frozen dataclass)
- Critic health validation with auto-upgrade to gemini-2-flash (model_router.py:432-460)
- `_COMPLEX_TASK_TYPES` frozenset for Gemini Pro upgrade gating

### Integration Points
- `agents/model_router.py`: Main restructuring target -- get_routing(), FREE_ROUTING rename, L1 check insertion
- `core/config.py`: Add L1_MODEL env var to Settings dataclass
- `providers/registry.py`: No ModelTier changes needed; StrongWall stays CHEAP
- Tests: `tests/test_model_router.py` -- TestFreeRoutingUpdates, TestCheapTierFallback, TestGetRoutingWithPolicy all reference FREE_ROUTING

</code_context>

<deferred>
## Deferred Ideas

- L2 authorization UI (global allowlist + per-task escalation button) -- Phase 19 (Agent Config Dashboard)
- Per-agent critic override configuration -- Phase 18/19
- Auto-escalation from L1 to L2 based on task complexity assessment -- future requirement ROUTE-05
- A/B testing between L1 and L2 models -- future requirement ROUTE-04

</deferred>

---

*Phase: 17-tier-routing-architecture*
*Context gathered: 2026-03-06*

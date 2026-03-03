# Project Retrospective

*A living document updated after each milestone. Lessons feed forward into future planning.*

## Milestone: v1.0 — Free LLM Provider Expansion

**Shipped:** 2026-03-02
**Phases:** 6 | **Plans:** 12 | **Commits:** 68

### What Was Built
- 5 new LLM providers (Cerebras, Groq, Mistral/Codestral, SambaNova, Together AI) fully integrated
- Smart multi-provider FREE_ROUTING with task-type-aware primary assignment
- Provider-diverse fallback chain with CHEAP-tier failover
- Config flags (GEMINI_FREE_TIER, OPENROUTER_FREE_ONLY) for operator control
- 90+ new tests covering all providers, routing, config flags, and fallback diversity

### What Worked
- **Provider registration pattern** — Phase 1 established the ProviderType enum + ProviderSpec + ModelSpec + _BUILTIN_PRICES pattern; Phases 2-5 followed it mechanically with ~5 min average per plan
- **All enum values upfront** — Adding all 6 ProviderType values in Phase 1 eliminated cross-phase enum conflicts
- **Research-first approach** — Each phase had provider-specific research (API docs, rate limits, quirks) that prevented runtime surprises
- **Parallel plan execution** — 12 plans across 6 phases completed in ~66 min total execution time
- **Comprehensive audit** — 41/41 requirements verified across 3 sources before milestone completion

### What Was Inefficient
- **SUMMARY.md frontmatter not populated** — `requirements_completed` field empty in all 12 summaries; 3-source verification had to rely on VERIFICATION.md + REQUIREMENTS.md only
- **Plan notation inconsistencies** — Some phases show `- [ ]` for completed plans in ROADMAP.md (e.g., Phase 1 plan 02, Phase 2 plan 02) while execution confirmed them complete
- **SambaNova quirks not caught earlier** — Three request transforms (temp clamp, stream=False, strict removal) were all discovered during research; earlier research could have consolidated them

### Patterns Established
- **Provider registration recipe**: ProviderType enum → ProviderSpec → ModelSpec(s) → _BUILTIN_PRICES → Settings field → .env.example
- **Test class pattern**: TestXxxRegistration (5-8 tests) + TestXxxSpendingTracker (5 tests) per provider
- **Dual-provider architecture**: Mistral demonstrated that a single vendor can have 2 separate ProviderType entries with independent base URLs and API keys
- **Request transforms**: Inline in `complete()` / `complete_with_tools()` with deepcopy protection for tool mutation

### Key Lessons
1. **Always key _BUILTIN_PRICES by exact ModelSpec.model_id** — case-sensitive, including org/ namespace prefixes. Mismatch silently triggers $5/$15 conservative fallback.
2. **Add all enum values in the first phase** — prevents merge conflicts and dependency issues when phases execute in parallel or out of order.
3. **Provider quirks need dedicated transforms** — SambaNova's 3 transforms show that "OpenAI-compatible" doesn't mean "identical behavior." Budget research time for API edge cases.
4. **Config flags belong in the routing phase, not individual provider phases** — GEMINI_FREE_TIER and OPENROUTER_FREE_ONLY only make sense after all providers are wired in.

### Cost Observations
- Model mix: 100% balanced profile (sonnet for planning/execution)
- Sessions: ~4 sessions across 2 days
- Notable: 5.5 min average plan execution — provider integration is a well-factored, repeatable pattern

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Commits | Phases | Key Change |
|-----------|---------|--------|------------|
| v1.0 | 68 | 6 | Established provider registration pattern; research-first approach |

### Cumulative Quality

| Milestone | Tests | New Tests | Files Changed |
|-----------|-------|-----------|---------------|
| v1.0 | 1,956 | 90+ | 77 |

### Top Lessons (Verified Across Milestones)

1. Exact case-sensitive model ID matching is critical for pricing lookups — mismatch is silent
2. Research phase pays for itself by surfacing provider quirks before code

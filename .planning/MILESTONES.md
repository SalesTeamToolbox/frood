# Milestones

## v1.2 Claude Code Automation Enhancements (Shipped: 2026-03-07)

**Phases completed:** 6 phases (11-16), 8 plans
**Timeline:** 2 days (2026-03-05 → 2026-03-07)
**Audit:** gaps_found at audit time (phases 14-15 pending) → all 6 phases completed post-audit

**Key accomplishments:**

1. Configured 3 MCP servers in `.mcp.json`: context7 (live library docs), GitHub (PR/issue management), Playwright (browser automation) — Claude Code now has full development tooling access
2. PreToolUse security gate blocks edits to 12 security-critical files with shared `security_config.py` registry — defense-in-depth complements existing PostToolUse monitor
3. 3 scaffolding skills: `/test-coverage`, `/add-tool`, `/add-provider` — generate convention-correct boilerplate in one invocation instead of manual copy-paste
4. 2 operational skills: `/prod-check` (7-check SSH health sweep) and `/add-pitfall` (auto-numbered CLAUDE.md maintenance)
5. 4 specialized analysis subagents: test-coverage-auditor, dependency-health, migration-impact, deploy-verifier — codified deployment lessons as executable agents
6. jcodemunch deep integration: context-loader emits work-type guidance, drift detection hook, GSD workflow pre-fetch steps for map/plan/execute

**Delivered:** Full Claude Code developer toolchain — MCP servers for docs/GitHub, security gate, 5 skills, 4 subagents, and jcodemunch integration across all GSD workflows.

**Archives:**

- [v1.2-ROADMAP.md](milestones/v1.2-ROADMAP.md)
- [v1.2-REQUIREMENTS.md](milestones/v1.2-REQUIREMENTS.md)
- [ws-claude-code-automation-enhancements-2026-03-19/](milestones/ws-claude-code-automation-enhancements-2026-03-19/)

---

## v1.0 Free LLM Provider Expansion (Shipped: 2026-03-02)

**Phases completed:** 6 phases, 12 plans
**Commits:** 68 | **Files changed:** 77 (+12,998 / -256 lines)
**Timeline:** 11 days (2026-02-20 → 2026-03-02)
**Tests:** 1,956 passed (90+ new provider/routing tests)
**Audit:** PASSED — 41/41 requirements, 58/58 verification truths, 7/7 E2E flows

**Key accomplishments:**

1. Extended ProviderType enum with 6 new values and established OpenAI-compatible provider registration pattern
2. Integrated 5 new LLM providers: Cerebras (FREE, 3000 tok/s), Groq (FREE, 131K ctx), Mistral Codestral (FREE) + La Plateforme (CHEAP), SambaNova (CHEAP, 3 request transforms), Together AI (CHEAP)
3. Smart multi-provider FREE_ROUTING — Cerebras primary for coding, Groq for research, Codestral critic for code tasks
4. Provider-diverse fallback chain with CHEAP-tier failover via SambaNova and Together AI
5. Config flags (GEMINI_FREE_TIER, OPENROUTER_FREE_ONLY) for operator billing control
6. Full test coverage for all providers, routing, config flags, and fallback diversity

**Delivered:** Agent42 can now operate across 8 LLM providers (Gemini, OpenRouter + 5 new + Codestral), eliminating the dual single-point-of-failure on OpenRouter and Gemini.

**Archives:**

- [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md)
- [v1.0-REQUIREMENTS.md](milestones/v1.0-REQUIREMENTS.md)
- [v1.0-MILESTONE-AUDIT.md](milestones/v1.0-MILESTONE-AUDIT.md)

---

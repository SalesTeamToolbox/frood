---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: unknown
last_updated: "2026-03-07T17:58:19.232Z"
---

---
gsd_state_version: 1.0
milestone: v1.0
milestone_name: milestone
status: in-progress
last_updated: "2026-03-07T17:50:42Z"
---

# Project State

## Project Reference

See: .planning/PROJECT.md (updated 2026-03-06)

**Core value:** Agent42 runs agents reliably with tiered provider routing (L1 workhorse -> free fallback -> L2 premium)
**Current focus:** Phase 19.1 UI Redesign COMPLETE — both plans done, ready for human verification and Phase 20

## Current Position

Phase: 19.1 of 20 (UI Redesign) -- COMPLETE
Plan: 2 of 2 in current phase -- COMPLETE
Status: Phase 19.1 complete — IDE layout rewritten, human browser verification needed before Phase 20
Last activity: 2026-03-17 -- 19.1-02 complete (Frontend Rewrite: VS Code-style IDE layout)

Progress: [█████████░] 90%

## Performance Metrics

**Velocity:**
- Total plans completed: 8
- Average duration: 10.4min
- Total execution time: 83min

**By Phase:**

| Phase | Plans | Total | Avg/Plan |
|-------|-------|-------|----------|
| 16. StrongWall Provider | 2/2 | 15min | 7.5min |
| 17. Tier Routing Architecture | 2/2 | 28min | 14min |
| 18. Agent Config Backend | 1/1 | 18min | 18min |
| 19. Agent Config Dashboard | 2/2 | 13min | 6.5min |
| 19.1. UI Redesign | 2/2 | 21min | 10.5min |

*Updated after each plan completion*

## Accumulated Context

### Decisions

- [16-01] StrongWall stream=False for ALL requests (not just tool calls like SambaNova)
- [16-01] Temperature clamp and strict=False shared with SambaNova in combined conditions
- [16-01] Flat-rate $0 per-token in _BUILTIN_PRICES; monthly cost as separate config field
- [16-02] Health check uses /v1/models endpoint (GET, no tokens consumed)
- [16-02] Thresholds: <3s healthy, 3-5s degraded, >5s/error unhealthy
- [16-02] Polling started in agent42.py (not server.py startup event) matching existing pattern
- [16-02] Spending limit exemption via _FLAT_RATE_PROVIDERS set before check_limit()
- StrongWall.ai ($16/mo unlimited Kimi K2.5) as L1 workhorse provider
- L1/L2 tier architecture replaces free/cheap/paid mix
- Gemini as default L2 (premium) provider
- OR paid models available as L2 when balance present, not locked to FREE
- Fallback chain: StrongWall -> Free (Cerebras/Groq) -> L2 premium
- Hybrid streaming: simulate for chat, accept non-streaming for background tasks
- Per-agent routing override: primary, critic, fallback models
- Agent overrides inherit global defaults, only store differences
- [17-01] L1 resolves lazily at get_routing() time, not at startup (KeyStore may inject after Settings frozen)
- [17-01] L2 authorization uses runtime sets on ModelRouter, not config fields
- [17-01] L1 self-critique: same model, different reviewer prompt
- [17-01] FALLBACK_ROUTING alias kept permanently (zero runtime cost)
- [17-01] isinstance(val, str) guard on settings.l1_default_model for MagicMock safety
- [18-01] Profile override inserted as step 1b between admin override and dynamic routing
- [18-01] get_effective() merges profile + _default only, NOT FALLBACK_ROUTING -- falls through when no primary
- [18-01] has_config() guards profile path to prevent empty get_effective() short-circuiting
- [18-01] Critic auto-pairs with primary when unset (self-critique pattern)
- [18-01] data/agent_routing.json auto-created on first write (gitignored data/ dir)
- [18-01] Available models endpoint filters by configured API keys and groups by l1/fallback/l2 tiers
- [19-01] Three dropdowns (Primary, Critic, Fallback) matching backend API fields -- L2/Premium is a tier option within each dropdown's optgroup
- [19-01] STRONGWALL_API_KEY added to ADMIN_CONFIGURABLE_KEYS so settingSecret() renders as admin-editable
- [19-01] Chain summary uses styled badges with source-aware coloring (teal/gold/muted)
- [19-01] Empty string in routingEdits means "clear override" (send null to API), undefined means "no change"
- [19-02] routingSelect() extended with scope parameter ('default' vs 'agent') to route changes to correct state object
- [19-02] loadProfileDetail() fetches profile + routing data in parallel via Promise.all
- [19-02] _default profile shows link to Settings > LLM Routing instead of inline routing controls
- [19-02] Model chip on cards uses muted text + '(inherited)' for inherited, normal text for overridden
- [19.1-01] Use empty string default for AGENT42_REMOTE_HOST (not 'agent42-prod') — fail closed rather than silently connecting to wrong host
- [19.1-01] Add /api/remote/status endpoint to enable frontend feature detection before attempting WebSocket connections
- [19.1-01] Mark test_ide_html.py tests as xfail until Plan 02 ships — Wave 0 tests define target state not current state
- [19.1-02] Terminal visible by default on Code page load — renderCode() opens first local terminal if sessions empty
- [19.1-02] Terminal wrapper is sibling of ide-top-row (not nested in ide-main) — enables full-width drag handle
- [19.1-02] fitAddon stored on session object (was closure-local) — enables drag-handle resize for all tabs
- [19.1-02] Single shared termFitAll with window guard — no per-session window listener accumulation
- [19.1-02] Remove xfail markers from test_ide_html.py — all 6 tests now regular passing tests

### Roadmap Evolution

- Phase 19.1 inserted after Phase 19: UI Redesign — Redesign the Agent42 dashboard UI for a modern, polished look and feel (INSERTED)

### Pending Todos

- v1.2 phases 13-15 running in parallel workstream (claude-code-automation-enhancements)

### Blockers/Concerns

- StrongWall.ai does not support streaming responses (addressed in Phase 20)
- Kimi K2.5 is currently the only model on StrongWall (future req PROV-05/06 deferred)
- Pre-existing test failure: tests/test_security.py::TestFailSecureLogin::test_login_rejected_no_password (KeyError: 'detail')

## Session Continuity

Last session: 2026-03-17
Stopped at: Completed 19.1-02-PLAN.md (Frontend Rewrite: VS Code-style IDE layout)
Resume file: .planning/workstreams/agent-llm-control/phases/19.1-ui-redesign/19.1-02-SUMMARY.md

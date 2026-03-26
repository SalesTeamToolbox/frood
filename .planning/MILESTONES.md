# Milestones

## v2.1 Multi-Project Workspace (Shipped: 2026-03-26)

**Phases completed:** 5 phases (01-05), 8 plans, 15 tasks
**Timeline:** 3 days (2026-03-23 → 2026-03-25)
**Workstream:** multi-project-workspace
**Tests:** 51 workspace-specific (all passing)
**Audit:** PASSED — 16/16 requirements, 9/9 E2E flows, 3 gaps closed by Phases 4-5

**Key accomplishments:**

1. WorkspaceRegistry with SQLite persistence, CRUD API, default workspace auto-seeding from AGENT42_WORKSPACE — foundational data layer with 36 tests
2. Full IDE surface isolation — file explorer, Monaco editor (view state save/restore), CC sessions, and terminals all scoped per workspace_id
3. Workspace tab bar with switchWorkspace orchestrator — atomically saves state, swaps all IDE surfaces, re-roots file explorer; stale-while-revalidate localStorage persistence
4. Workspace lifecycle management — add modal (path input + app dropdown), remove with unsaved-files guard, optimistic inline rename with API rollback
5. Gap closure — fixed workspace_id Pydantic model mismatch on file save, missing workspace_id on search, migrated 5 bare localStorage keys to wsKey(), fixed stale unsaved guard
6. All localStorage/sessionStorage keys namespace-isolated via wsKey() — no cross-workspace state contamination

**Delivered:** Tabbed multi-project workspace where each tab scopes an independent project — its own file explorer, editor tabs, CC sessions, and terminal — with full state isolation and workspace management UI.

**Verification:** 16/16 requirements satisfied, 9/9 E2E flows complete, re-audit passed.

**Archives:**

- [v2.1-ROADMAP.md](milestones/v2.1-ROADMAP.md)
- [v2.1-REQUIREMENTS.md](milestones/v2.1-REQUIREMENTS.md)
- [v2.1-MILESTONE-AUDIT.md](milestones/v2.1-MILESTONE-AUDIT.md)

---

## v1.0 Performance-Based Rewards (Shipped: 2026-03-25)

**Phases completed:** 4 phases (01-04), 7 plans, 95 tests passing
**Timeline:** 2 days (2026-03-22 → 2026-03-23)
**Workstream:** performance-based-rewards

**Key accomplishments:**

1. Foundation — RewardSystem facade with ScoreCalculator (weighted composite), TierCache (TTL + file persistence), mutable RewardsConfig (no restart needed)
2. Tier Assignment — TierDeterminator (Bronze/Silver/Gold/Provisional), AgentConfig tier fields with effective_tier(), TierRecalcLoop background service (15-min cycle)
3. Resource Enforcement — Model routing upgrade by tier, rate limit multipliers (1.0x/1.5x/2.0x), semaphore-based concurrent task caps (2/5/10)
4. Dashboard — 5 REST API endpoints, tier badges in frontend, admin override UI, WebSocket tier_update events, full auth coverage
5. Graceful degradation — REWARDS_ENABLED=false default, zero change for existing deployments

**Delivered:** Bronze/Silver/Gold performance tier system where agents earn better models, higher rate limits, and more concurrent tasks through demonstrated effectiveness.

**Verification:** 29/29 requirements complete, 95/95 tests green across 5 test files.

---

## v1.6 UX & Workflow Automation (Shipped: 2026-03-22)

**Phases completed:** 4 phases (01-04), 8 plans
**Timeline:** 2 days (2026-03-20 → 2026-03-21)
**Workstream:** agent42-ux-and-workflow-automation

**Key accomplishments:**

1. Memory pipeline fix — recall hook limited to 3 memories/2000 chars with silent no-match, learn hook deduplicates against last 10 HISTORY.md entries (>80% keyword overlap)
2. Memory pipeline observability — structured logging on /api/memory/search, /api/memory/stats endpoint, --health extended with memory_pipeline diagnostics
3. GSD auto-activation — always-on `gsd-auto-activate` skill + CLAUDE.md methodology section + context-loader hook GSD detection with smart skip logic
4. Desktop app experience — PWA manifest with standalone display, PNG icon generation (cairosvg/Pillow fallback), cross-platform desktop shortcuts (Windows .lnk, macOS .app, Linux .desktop)
5. Dashboard GSD integration — sidebar shows active workstream name and current phase via WebSocket heartbeat with graceful degradation

**Delivered:** Agent42 operates as a native desktop app with PWA + shortcuts, memory hooks produce visible feedback, GSD activates automatically for multi-step tasks, and dashboard shows live workstream status.

**Archives:**

- [v1.6-ROADMAP.md](milestones/v1.6-ROADMAP.md)
- [v1.6-REQUIREMENTS.md](milestones/v1.6-REQUIREMENTS.md)

---

## v1.5 Intelligent Memory Bridge (Shipped: 2026-03-22)

**Phases completed:** 4 phases (01-04), 8 plans
**Timeline:** 2 days (2026-03-18 → 2026-03-19)
**Workstream:** intelligent-memory-bridge

**Key accomplishments:**

1. Auto-sync PostToolUse hook intercepts Claude Code memory file writes and upserts to Qdrant via ONNX embeddings with UUID5 file-path dedup
2. Hook activation — cc-memory-sync.py registered with 5s timeout, MemoryTool.reindex_cc action for manual catch-up scanning
3. Intelligent learning Stop hook — knowledge-learn.py extracts decisions, feedback, deployment patterns from conversations via instructor + Pydantic, stores in KNOWLEDGE collection
4. CLAUDE.md integration — setup.sh auto-generates memory instructions directing Claude to prefer agent42_memory search/store over flat-file memory
5. Memory quality — cosine dedup consolidation worker with auto-trigger on threshold count, dashboard /api/consolidate/trigger endpoint, search results include confidence scores

**Delivered:** Claude Code's flat-file memory is automatically bridged to Agent42's Qdrant-backed semantic memory — every write syncs, sessions extract learnings, and dedup keeps the store clean.

**Archives:**

- [v1.5-ROADMAP.md](milestones/v1.5-ROADMAP.md)
- [v1.5-REQUIREMENTS.md](milestones/v1.5-REQUIREMENTS.md)

---

## v1.4 Per-Project/Task Memories (Shipped: 2026-03-22)

**Phases completed:** 4 phases (20-23), 8 plans
**Timeline:** 6 days (2026-03-17 → 2026-03-22)
**Workstream:** per-project-task-memories

**Key accomplishments:**

1. Task metadata foundation — TaskType enum, begin_task/end_task lifecycle via contextvars, task_id/task_type injected into Qdrant payloads with KEYWORD payload indexes
2. Task-type-filtered retrieval — search_with_lifecycle(), EmbeddingStore.search(), and MemoryStore.build_context_semantic() all accept task_type_filter
3. Async effectiveness tracking — fire-and-forget SQLite EffectivenessStore records tool_name, task_type, success, duration_ms per invocation with zero hot-path latency
4. Post-task learning extraction — Stop hook auto-extracts task summary via instructor + Pydantic with quarantine period (confidence capped at 0.6 until 3+ observations)
5. Proactive context injection — UserPromptSubmit hook infers task type from keywords, injects top-3 past learnings (score > 0.80, 500 token cap, session-once guard)
6. Recommendations engine — GET /api/recommendations/retrieve suggests top-3 tools/skills by success_rate with minimum sample threshold (5+ observations)

**Delivered:** Agent42 learns from experience — every task builds effectiveness data, past learnings auto-surface for new tasks, and tool/skill recommendations improve over time.

**Known gaps:** TMETA-01 through TMETA-04 and LEARN-01 through LEARN-05 checkboxes not updated in REQUIREMENTS.md (phases completed per SUMMARY files).

**Archives:**

- [v1.4-ROADMAP.md](milestones/v1.4-ROADMAP.md)
- [v1.4-REQUIREMENTS.md](milestones/v1.4-REQUIREMENTS.md)

---

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

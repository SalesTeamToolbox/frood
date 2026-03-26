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

## Milestone: v1.2 — Claude Code Automation Enhancements

**Shipped:** 2026-03-07
**Phases:** 6 (11-16) | **Plans:** 8 | **Timeline:** 2 days

### What Was Built
- 3 MCP servers (.mcp.json): context7 (live docs), GitHub (PR/issue management), Playwright (browser automation)
- PreToolUse security gate blocking edits to 12 security-critical files with shared security_config.py registry
- 3 scaffolding skills: /test-coverage, /add-tool, /add-provider — convention-correct boilerplate in one invocation
- 2 operational skills: /prod-check (7-check SSH health sweep) and /add-pitfall (auto-numbered CLAUDE.md maintenance)
- 4 specialized subagents: test-coverage-auditor, dependency-health, migration-impact, deploy-verifier
- jcodemunch deep integration: context-loader work-type guidance + drift detection + GSD workflow pre-fetch

### What Worked
- **Small, focused phases** — Each phase had a single deliverable type (MCP / hooks / skills / subagents); 1-2 plans each, ~3-5 min execution
- **Inline templates** — Skills with embedded templates are self-contained; no external file dependencies to break
- **Shared config module** — security_config.py as single source for both pre/post hooks; consistent file list with no drift risk
- **Audit-driven gap closure** — Audit found phases 14-15 missing; gap phases were created and executed cleanly
- **Phase 16 as accelerant** — jcodemunch integration into GSD workflows reduces token cost on every future task

### What Was Inefficient
- **Audit timing** — Ran audit before all phases completed; created stale `gaps_found` status that persisted
- **SUMMARY.md frontmatter empty** — All 4 plan summaries had empty `requirements_completed` arrays; 3-source verification fell back to REQUIREMENTS.md only
- **Workstream → milestone handoff not run** — Workstream was archived without running `complete-milestone`; REQUIREMENTS.md sat stale with SKILL-04/05 + AGENT-01-04 unchecked for weeks

### Patterns Established
- **Skills as instruction-only documents** — SKILL.md with inline templates and multi-step instructions; no Python, no external deps
- **Agent definitions as plain markdown** — No frontmatter, just Title + Purpose + Context + Steps + Output Format
- **Shared hook config module** — When 2+ hooks need the same list, extract to a config file both import
- **Work-type guidance in context-loader** — Detect task type from prompt keywords, emit targeted jcodemunch queries

### Key Lessons
1. **Run `complete-milestone` before switching workstreams** — Leaving REQUIREMENTS.md stale causes confusion in the next session; close the milestone formally before archiving the workstream.
2. **Audit timing matters** — Run audit only after all planned phases are complete, not mid-execution. Stale `gaps_found` blocks the completion workflow.
3. **SUMMARY.md frontmatter should be populated** — `requirements_completed` field enables 3-source verification; leaving it empty adds manual audit burden.
4. **Operational skills pay compound dividends** — /prod-check and /add-pitfall each take 3 min to build but save 5+ min every time they're used.

### Cost Observations
- Model mix: balanced profile (sonnet throughout)
- Sessions: ~3 sessions across 2 days
- Notable: Infrastructure phases (MCP config, security gate) took 3-5 min; subagent definitions took 5 min for 4 agents

---

## Milestone: v1.4 — Per-Project/Task Memories

**Shipped:** 2026-03-22
**Phases:** 4 (20-23) | **Plans:** 8 | **Timeline:** 6 days (2026-03-17 → 2026-03-22)

### What Was Built
- Task metadata foundation: TaskType enum, begin_task/end_task lifecycle via contextvars, Qdrant payload indexes
- Async effectiveness tracking: fire-and-forget SQLite EffectivenessStore with zero hot-path latency
- Post-task learning extraction: Stop hook with instructor/Pydantic extraction, quarantine period (3+ observations)
- Proactive context injection: UserPromptSubmit hook infers task type, injects top-3 past learnings (score > 0.80, 500 token cap)
- Recommendations engine: GET /api/recommendations/retrieve, tools/skills ranked by success_rate with minimum sample threshold

### What Worked
- **Fire-and-forget pattern** — asyncio.create_task() in ToolRegistry.execute() keeps tracking invisible to tools; no latency impact
- **Quarantine before trust** — Confidence capped at 0.6 until 3+ observations prevents one bad session from poisoning memory
- **TDD red-green cycle** — All 8 plans used test-first approach; test failures caught contract mismatches early
- **Session-once guard** — proactive-inject.py only fires on first prompt per session, preventing re-injection noise

### What Was Inefficient
- **REQUIREMENTS.md checkboxes not updated** — 9/20 checkboxes still unchecked despite phases completing; traceability table lags behind actual work
- **Phase 20 split into 2 plans unnecessarily** — Schema + lifecycle could have been one plan; split added overhead with minimal parallelization benefit
- **instructor dependency added in Plan 01 but used in Plan 02** — Dependency install should match the plan that first uses it

### Patterns Established
- **contextvars for cross-cutting context** — Task context propagates through async call stack without parameter threading
- **File bridge for cross-process state** — .agent42/current-task.json bridges main process state to hook subprocesses
- **Score-gated injection** — Similarity threshold (0.80) + token cap (500) prevents context bloat from low-quality matches
- **Keyword-based task type inference** — Hook infers task type from prompt keywords; multi-word phrases checked before single keywords

### Key Lessons
1. **Update REQUIREMENTS.md checkboxes when SUMMARY.md is written** — Checkbox lag creates false "incomplete" signals during milestone completion
2. **Fire-and-forget must wrap all exceptions** — EffectivenessStore.record() needs blanket try/except; one tracking failure must never crash a tool
3. **instructor Mode.JSON for broad model compatibility** — Function calling mode isn't supported by all providers; JSON mode works everywhere
4. **Session guard files need project-scoped paths** — MD5 of project_dir gives stable session ID without requiring CC to pass one

### Cost Observations
- Model mix: balanced profile
- Sessions: ~5 sessions across 6 days
- Notable: Phases 22-23 (injection + recommendations) completed in single session each — well-defined API contracts from earlier phases

---

## Milestone: v1.5 — Intelligent Memory Bridge

**Shipped:** 2026-03-22
**Phases:** 4 (01-04) | **Plans:** 8 | **Timeline:** 2 days (2026-03-18 → 2026-03-19)

### What Was Built
- PostToolUse auto-sync hook: intercepts CC memory file writes, ONNX-embeds, upserts to Qdrant with UUID5 dedup
- Intelligent learning Stop hook: extracts decisions, feedback, deployment patterns via instructor + Pydantic
- CLAUDE.md integration: setup.sh auto-generates memory instructions with marker-based idempotent injection
- Memory quality: cosine dedup consolidation worker, auto-trigger on threshold, dashboard endpoints for status and manual trigger

### What Worked
- **UUID5 file-path dedup** — Same CC memory file always maps to same Qdrant point ID; edits overwrite, never duplicate
- **Marker-based injection** — `<!-- AGENT42_MEMORY_START -->` markers in CLAUDE.md make setup.sh re-runs idempotent
- **Detached subprocess pattern** — Hooks spawn workers that run after hook exits; no timeout issues
- **Fast execution** — 4 phases in 2 days; each phase had clear contract boundaries

### What Was Inefficient
- **LEARN-01 through LEARN-05 checkboxes not updated** — Same pattern as v1.4; phases completed but REQUIREMENTS.md not kept current
- **QUAL-02 (confidence scores in search) partially implemented** — Search output shows scores but format inconsistent with plan spec

### Patterns Established
- **Background worker subprocess** — Hook entry point (lightweight) spawns detached worker (heavy ONNX/Qdrant operations)
- **KNOWLEDGE collection in Qdrant** — Separate collection for extracted learnings; distinct from MEMORY/HISTORY
- **Consolidation auto-trigger** — entries_since counter fires background consolidation at threshold; no cron needed
- **Setup helper functions** — scripts/setup_helpers.py provides composable CLI subcommands for setup.sh

### Key Lessons
1. **Hooks must be lightweight** — Heavy operations (ONNX embedding, Qdrant upsert) in detached subprocess; hook itself returns immediately
2. **Silent failure is mandatory for augmentation hooks** — CC's Write tool must never fail because Agent42 Qdrant is down
3. **Consolidation needs a status file** — .agent42/consolidation-status.json tracks last_run/scanned/removed; dashboard reads it for display
4. **instructor extraction schema is fragile** — Noisy conversations produce noisy learnings; quarantine is essential

### Cost Observations
- Model mix: balanced profile
- Sessions: ~3 sessions across 2 days
- Notable: Fastest milestone completion — 4 phases in 2 days, each with clear input/output contracts

---

## Milestone: v1.6 — UX & Workflow Automation

**Shipped:** 2026-03-22
**Phases:** 4 (01-04) | **Plans:** 8 | **Timeline:** 2 days (2026-03-20 → 2026-03-21)

### What Was Built
- Memory pipeline fix: recall hook limited to 3 memories/2000 chars, learn hook deduplicates against HISTORY.md
- Memory observability: structured logging, /api/memory/stats endpoint, --health memory_pipeline diagnostics
- GSD auto-activation: always-on skill, CLAUDE.md methodology section, context-loader hook with smart skip logic
- Desktop app: PWA manifest, icon generation (cairosvg/Pillow fallback), cross-platform shortcuts
- Dashboard GSD: sidebar workstream/phase indicator via WebSocket heartbeat

### What Worked
- **Always-on skill mechanism** — `always: true` frontmatter guarantees GSD instructions in every Claude session
- **Smart skip logic** — Context-loader only nudges for multi-step tasks; trivial prompts pass through unchanged
- **PWA over Electron** — manifest.json + --app mode achieves chromeless experience with zero new dependencies
- **UAT via Playwright** — Phase 3 PWA verified through automated browser testing, not manual clicks

### What Was Inefficient
- **DASH-01/02 checkboxes not updated** — Phase 4 completed but dashboard requirements left unchecked
- **Icon generation fallback chain** — cairosvg needs Cairo DLL (absent on Windows); Pillow fallback works but produces less crisp icons
- **Workstream had only 6 tagged commits** — Many feature commits weren't tagged with workstream name, making stats gathering harder

### Patterns Established
- **Always-on skills for cross-cutting behavior** — Use `always: true` for behaviors that should apply to every task type
- **Context-loader work-type detection** — Keyword matching in prompts to inject relevant guidance without LLM calls
- **Cross-platform shortcut generation** — Windows .lnk (PowerShell COM), macOS .app bundle, Linux .desktop file

### Key Lessons
1. **Tag all feature commits with workstream name** — Enables accurate milestone stats without manual commit archaeology
2. **PWA manifest display: standalone is sufficient** — No need for service worker complexity in v1; install prompt works with manifest alone
3. **Keyword-based detection beats LLM classification for hooks** — Zero latency, deterministic, and easy to extend

### Cost Observations
- Model mix: balanced profile
- Sessions: ~3 sessions across 2 days
- Notable: Phase 3 (PWA) verified via Playwright UAT in automated pipeline — first milestone to use automated visual verification

---

## Milestone: rewards-v1.0 — Performance-Based Rewards

**Shipped:** 2026-03-25
**Phases:** 4 | **Plans:** 7 | **Commits:** 19 (code)

### What Was Built
- RewardSystem facade: ScoreCalculator (weighted composite), TierCache (TTL + file persistence), mutable RewardsConfig (no restart needed)
- TierDeterminator: Bronze/Silver/Gold/Provisional automatic assignment, AgentConfig tier fields with effective_tier()
- TierRecalcLoop: background service recalculates all non-overridden agents every 15 minutes
- Resource enforcement: model routing upgrade by tier, rate limit multipliers (1.0x/1.5x/2.0x), semaphore-based concurrent task caps (2/5/10)
- Dashboard: 5 REST API endpoints, tier badges on agent cards, admin override UI, rewards toggle, WebSocket tier_update events
- 95 tests across 5 test files, 29/29 requirements verified

### What Worked
- **Strict TDD red-green cycle** — Every plan started with failing tests, then implementation; caught contract mismatches early
- **O(1) hot-path reads** — Tier cached in AgentConfig field, never computed during request dispatch; background recalc keeps it current
- **Mutable config pattern** — RewardsConfig uses class-level mtime-cache matching AgentRoutingStore pattern; runtime toggle without restart
- **Coarse granularity** — 4 phases instead of fine-grained split; Dashboard API+UI merged into one phase; reduced planning overhead
- **Workstream isolation** — Own ROADMAP/REQUIREMENTS/STATE; no interference with parallel workstreams

### What Was Inefficient
- **Main ROADMAP.md left stale** — Rewards roadmap placed in main `.planning/ROADMAP.md` but progress table never updated (showed 0/0 everywhere); workstream ROADMAP was the actual source of truth
- **Milestone version collision** — Workstream used "v1.0" internally, conflicting with existing global v1.0; resolved with `rewards-v1.0` tag
- **Partial completion** — `milestone complete` CLI ran but full workflow (PROJECT.md evolution, ROADMAP reorganization, RETROSPECTIVE) deferred to separate session

### Patterns Established
- **Mutable config file for runtime toggles** — When frozen Settings can't support runtime changes, use a separate JSON config with class-level mtime-cache
- **None sentinel for optional overrides** — `is not None` check distinguishes "no override" from any falsy value
- **Non-blocking semaphore** — `asyncio.wait_for(sem.acquire(), timeout=0.0)` for O(1) capacity check without touching CPython internals
- **Batch WebSocket broadcast** — Collect all changes in one recalc cycle, send one message; O(1) not O(N)

### Key Lessons
1. **Update the main ROADMAP.md when using workstreams** — If the main ROADMAP has workstream content, either keep it current or replace with a project-level overview. Stale data confuses milestone completion.
2. **Use prefixed tags for workstream milestones** — `rewards-v1.0` avoids collision with global version numbering. Establish convention early.
3. **Run full `complete-milestone` immediately** — Partial completion (CLI only) leaves PROJECT.md, RETROSPECTIVE, and ROADMAP inconsistent until someone runs the full workflow.
4. **Coarse phase granularity works for well-understood domains** — 4 phases with clear data dependencies (foundation → scoring → enforcement → dashboard) executed faster than fine-grained splits would have.

### Cost Observations
- Model mix: balanced profile (sonnet for planning/execution)
- Sessions: ~3 sessions across 2 days
- Notable: 7 plans completed in ~90 min total execution time; average 13 min/plan

---

## Cross-Milestone Trends

### Process Evolution

| Milestone | Commits | Phases | Key Change |
|-----------|---------|--------|------------|
| v1.0 | 68 | 6 | Established provider registration pattern; research-first approach |
| v1.2 | ~15 | 6 | Established toolchain pattern: MCP + hooks + skills + subagents |
| v1.4 | 12 | 4 | Task-aware memory with fire-and-forget tracking; TDD red-green throughout |
| v1.5 | 27 | 4 | CC-to-Qdrant memory bridge; detached subprocess pattern for hooks |
| v1.6 | ~20 | 4 | PWA + GSD auto-activation; first Playwright-verified milestone |
| rewards-v1.0 | 19 | 4 | Performance-based tiers; coarse granularity; workstream-scoped milestone |

### Cumulative Quality

| Milestone | Tests | New Tests | Files Changed |
|-----------|-------|-----------|---------------|
| v1.0 | 1,956 | 90+ | 77 |
| v1.2 | ~1,960 | ~5 (drift detection) | ~20 (.claude/ files) |
| v1.4 | ~1,980 | ~20 (effectiveness, injection, recommendations) | ~15 |
| v1.5 | ~2,010 | ~30 (sync, learning, consolidation) | ~12 |
| v1.6 | ~2,040 | ~30 (hooks, PWA, GSD) | ~15 |
| rewards-v1.0 | ~2,135 | 95 (scoring, tiers, enforcement, dashboard API) | 56 |

### Top Lessons (Verified Across Milestones)

1. Exact case-sensitive model ID matching is critical for pricing lookups — mismatch is silent
2. Research phase pays for itself by surfacing provider quirks before code
3. Run `complete-milestone` immediately after a workstream finishes — stale REQUIREMENTS.md causes confusion in the next session
4. Update REQUIREMENTS.md checkboxes when writing SUMMARY.md — checkbox lag creates false "incomplete" signals (verified v1.4, v1.5, v1.6)
5. Fire-and-forget with blanket try/except is the only safe pattern for observability hooks — one tracking failure must never crash a tool (verified v1.4, v1.5)
6. Tag all feature commits with workstream name for accurate milestone stats (verified v1.6)
7. Use prefixed git tags for workstream milestones to avoid version collision with global numbering (verified rewards-v1.0)
8. Coarse phase granularity works for well-understood domains — 4 phases with clear data dependencies execute faster than fine splits (verified rewards-v1.0)

# Agent42

## What This Is

An AI agent platform that operates across 9 LLM providers with tiered routing (L1 workhorse, L2 premium, free fallback), per-agent model configuration, performance-based rewards (Bronze/Silver/Gold tiers earn better models and higher limits), and graceful degradation. Features intelligent memory (ONNX + Qdrant with auto-sync from Claude Code), task-aware learning (effectiveness tracking + proactive injection), and native desktop app experience (PWA + GSD auto-activation).

## Core Value

Agent42 must always be able to run agents reliably, with tiered provider routing (L1 workhorse -> free fallback -> L2 premium) ensuring no single provider outage stops the platform.

## Requirements

### Validated

- ✓ Integrate Cerebras (FREE — GPT-OSS 120B, Qwen3 235B, 3000 tok/s) — v1.0
- ✓ Integrate Groq (FREE — Llama 70B, GPT-OSS 120B, 131K context) — v1.0
- ✓ Integrate Mistral (FREE Codestral + CHEAP La Plateforme dual-key) — v1.0
- ✓ Integrate SambaNova (CHEAP — Llama 70B, DeepSeek V3, 3 request transforms) — v1.0
- ✓ Integrate Together AI (CHEAP — DeepSeek V3, Llama 70B) — v1.0
- ✓ GEMINI_FREE_TIER config flag for Gemini billing tier control — v1.0
- ✓ OPENROUTER_FREE_ONLY config flag to lock to free models — v1.0
- ✓ Smart rotation in FREE_ROUTING across Cerebras/Groq/Codestral/Gemini — v1.0
- ✓ Provider-diverse fallback chain — v1.0
- ✓ SpendingTracker pricing for all new providers — v1.0
- ✓ Health checks for new providers (including CHEAP tier) — v1.0
- ✓ SambaNova request transforms (temp clamp, stream=False, strict removal) — v1.0
- ✓ Full test coverage for all new providers — v1.0

- ✓ Unified error taxonomy with structured {error, message, action} API responses — v1.1
- ✓ Loading indicators (spinner, progress bar, typing dots) with 200ms threshold — v1.1
- ✓ Timeout warnings at 25s with user controls — v1.1

- ✓ context7 MCP server for live library documentation queries — v1.2
- ✓ GitHub MCP server for issue/PR/CI management from Claude Code — v1.2
- ✓ Playwright MCP server for browser automation from Claude Code — v1.2
- ✓ PreToolUse security gate blocks edits to 12 security-critical files — v1.2
- ✓ Developer scaffolding skills: /test-coverage, /add-tool, /add-provider — v1.2
- ✓ Operational skills: /prod-check (SSH health sweep) and /add-pitfall (CLAUDE.md maintenance) — v1.2
- ✓ 4 specialized subagents: test-coverage-auditor, dependency-health, migration-impact, deploy-verifier — v1.2
- ✓ jcodemunch deep integration: context-loader guidance + drift detection + GSD workflow pre-fetch — v1.2

- ✓ Task metadata in Qdrant payloads (task_id, task_type via contextvars lifecycle) — v1.4
- ✓ Task-type-filtered retrieval across search_with_lifecycle, EmbeddingStore, MemoryStore — v1.4
- ✓ Async effectiveness tracking (fire-and-forget SQLite, zero hot-path latency) — v1.4
- ✓ Post-task learning extraction with quarantine (instructor + Pydantic, 3+ observations threshold) — v1.4
- ✓ Proactive context injection (UserPromptSubmit hook, top-3 learnings, score > 0.80, 500 token cap) — v1.4
- ✓ Recommendations engine (top-3 tools/skills by success_rate, 5+ observation minimum) — v1.4

- ✓ PostToolUse auto-sync of Claude Code memory writes to Qdrant (ONNX embeddings, UUID5 dedup) — v1.5
- ✓ Intelligent learning extraction from conversations (decisions, feedback, patterns via instructor) — v1.5
- ✓ CLAUDE.md auto-generation directing Claude to prefer agent42_memory for reads/writes — v1.5
- ✓ Memory dedup consolidation worker (cosine similarity, auto-trigger, dashboard endpoint) — v1.5

- ✓ Memory pipeline visibility (recall/learn hooks produce visible stderr feedback) — v1.6
- ✓ GSD auto-activation (always-on skill + CLAUDE.md methodology + context-loader nudge) — v1.6
- ✓ PWA manifest + cross-platform desktop shortcuts (Windows .lnk, macOS .app, Linux .desktop) — v1.6
- ✓ Dashboard GSD integration (sidebar workstream/phase via WebSocket heartbeat) — v1.6

- ✓ Performance-based rewards system with Bronze/Silver/Gold/Provisional tiers — rewards-v1.0
- ✓ Composite scoring (success rate, volume, speed) with configurable weights and mutable RewardsConfig — rewards-v1.0
- ✓ Per-tier model routing, rate limit multipliers (1.0x/1.5x/2.0x), concurrent task caps (2/5/10) — rewards-v1.0
- ✓ Dashboard tier badges, admin override UI, rewards toggle, WebSocket tier_update events — rewards-v1.0
- ✓ Graceful opt-in via REWARDS_ENABLED=false default — zero behavioral change for existing deployments — rewards-v1.0

- ✓ WorkspaceRegistry with SQLite persistence, CRUD API, default workspace auto-seeding — v2.1
- ✓ Full IDE surface isolation — file explorer, editor, CC sessions, terminals scoped per workspace — v2.1
- ✓ Workspace tab bar with switchWorkspace orchestrator and stale-while-revalidate persistence — v2.1
- ✓ Workspace lifecycle management — add/remove/rename with unsaved-files guard — v2.1
- ✓ Monaco model URIs workspace-prefixed to prevent filename collision — v2.1
- ✓ All localStorage/sessionStorage keys namespace-isolated via wsKey() — v2.1

### Active

## Previous Milestone: v1.3 Agent LLM Control

**Goal:** Restructure model routing around L1/L2 tiers with StrongWall.ai as primary workhorse, add per-agent routing configuration in the dashboard, and modernize the fallback chain

**Target features:**
- StrongWall.ai provider integration (Kimi K2.5, unlimited API, OpenAI-compatible)
- L1 (workhorse) / L2 (premium) tier architecture in model routing
- Per-agent routing override (primary, critic, fallback) in dashboard
- Global default LLM settings in Settings page with per-agent overrides on Agents page
- OpenRouter paid models as L2 option when balance present
- Hybrid streaming: simulated streaming for chat, non-streaming for background tasks
- Fallback chain: StrongWall -> Free tier (Cerebras/Groq) -> L2 premium (Gemini/OR paid)

## Current Milestone: v2.0 Custom Claude Code UI

**Goal:** Build a VS Code Claude Code extension-style chat interface inside the Agent42 IDE, replacing the raw xterm terminal with a rich, web-native experience.

**Connection model:** Smart hybrid — interactive chat uses CC subscription (free via `claude` CLI), autonomous agent tasks use Agent42's tiered routing (Gemini L1 → free fallback → L2 premium). StrongWall.ai deprecated (causes disconnects).

**Status:** Phases 1-4 complete, Phases 5-6 remaining (PTY streaming + chat UX polish)

**Target features:**
- Chat message bubbles (user/assistant, avatars, timestamps, copy buttons)
- Markdown rendering (headers, lists, syntax-highlighted code blocks, links)
- Tool use cards (file reads, writes, commands — expandable/collapsible with status)
- Rich input box (multi-line, paragraph breaks, Shift+Enter, slash commands)
- Diff viewer (side-by-side/inline code changes, accept/reject buttons)
- Session history (browse/resume past conversations via Agent42 memory)
- Multi-agent view (multiple CC instances in tabs or side-by-side panels)
- Flexible layout (CC as editor tab OR dedicated side panel, user chooses)

## Current Milestone: v3.0 GSD & jcodemunch Integration

**Goal:** Unify Agent42's developer tooling into a zero-friction platform — one-command setup that configures Claude Code, MCP, hooks, and jcodemunch; conflict-resistant memory sync across nodes; and a unified context engine that merges code intelligence with semantic memory and GSD workflow state.

**Status:** Phase 1 complete, Phases 2-4 remaining (Windows setup, memory sync, context engine)

**Target features:**
- One-command setup (Linux + Windows) — generates .mcp.json, registers hooks, indexes repo with jcodemunch, validates health
- CLAUDE.md template generation with Agent42 conventions baked in
- Conflict-resistant memory sync: UUID+timestamp entries, entry-union merge (replaces mtime-wins)
- ContextAssemblerTool + jcodemunch path — code symbol search merged into unified context
- Per-project memory namespace wired into MemoryTool (ProjectMemoryStore already exists, needs wiring)
- GSD workstream state surfaced in context engine

## Complete: v2.1 Multi-Project Workspace (5/5 phases, shipped 2026-03-26)

**Delivered:** Tabbed workspace support where each tab scopes an independent project — its own file explorer, editor tabs, CC sessions, and terminal — with full state isolation via wsKey() namespace. 16/16 requirements satisfied, 51 tests, 9/9 E2E flows. Gap closure phases 4-5 added after audit to fix API wiring and frontend state isolation.

## Complete: Performance-Based Rewards System v1.0 (4/4 phases, shipped 2026-03-25)

**Delivered:** Bronze/Silver/Gold performance tier system where agents earn better models (gold→reasoning, silver→general, bronze→fast), higher rate limits (1.0x/1.5x/2.0x), and more concurrent tasks (2/5/10) through demonstrated effectiveness. 29/29 requirements complete, 95 tests green. Fully opt-in via `REWARDS_ENABLED=false` default.

### Out of Scope

- Cloudflare Workers AI — too-low limits for agentic workloads
- NVIDIA NIM — already partially in codebase, limited free tier
- Custom fine-tuned models on any provider
- Provider-native SDKs — all use OpenAI-compatible API

## Context

Shipped 9 milestones (v1.0, v1.1, v1.2, v1.4, v1.5, v1.6, rewards-v1.0, v2.1).
Tech stack: Python 3.11+, FastAPI, AsyncOpenAI, aiofiles, pytest, ONNX Runtime, Qdrant.
Memory system: ONNX embeddings + Qdrant + Redis, with auto-sync from Claude Code, task-aware retrieval, proactive injection, and recommendations engine.
Rewards system: Performance-based Bronze/Silver/Gold tiers with model routing, rate limit multipliers, and semaphore-based concurrency enforcement. Opt-in via REWARDS_ENABLED.
Desktop experience: PWA manifest + shortcuts, GSD auto-activation, dashboard with live workstream status.
Multi-project workspaces: Tabbed workspace scoping with isolated file explorer, editor, CC sessions, and terminals per project.

**Current routing:**
- Cerebras primary for coding/debugging/app_create (fastest inference)
- Groq primary for research/content/strategy (131K context)
- Codestral critic for all code task types (free code-specialist)
- Gemini 2.5 Flash as general primary (if free tier active)
- Provider-diverse round-robin fallback prevents single-provider exhaustion
- CHEAP-tier failover: SambaNova + Together AI when free models exhausted

**Known concerns:**
- SambaNova streaming tool call `index` bug — needs real API verification
- Together AI Llama 4 Scout serverless availability unverified
- Mistral La Plateforme actual RPM unverified (2 vs ~60 RPM)

## Constraints

- **API compatibility**: All providers use OpenAI Chat Completions compatible APIs
- **Tiered defaults**: L1 (StrongWall) when configured, free tier fallback, L2 premium opt-in
- **Graceful degradation**: Missing API keys never crash Agent42
- **Backward compatible**: Users without new API keys keep existing routing

## Key Decisions

| Decision | Rationale | Outcome |
|----------|-----------|---------|
| Smart rotation over single-primary | Distributes free quota across providers, prevents exhaustion | ✓ Good — eliminates dual SPOF |
| Cerebras as top priority for coding | Fastest inference (3000 tok/s), critical for iterative agent loops | ✓ Good — 20x faster than cloud GPUs |
| Groq as second free anchor | Genuinely free ~14K req/day, 131K context | ✓ Good — diversifies away from Cerebras |
| SambaNova as CHEAP fallback | Credits-based, Llama 70B + DeepSeek V3 when free exhausted | ✓ Good — quality fallback |
| Mistral dual-key architecture | Codestral free for code, La Plateforme paid for critic | ✓ Good — maximizes free usage |
| Together AI as general workhorse | Credits + fast inference fills "Gemini alternative" slot | ✓ Good — broad model selection |
| GEMINI_FREE_TIER config flag | Prevents unknowing paid API costs for Gemini users | ✓ Good — operator control |
| ProviderType enum in Phase 1 | All 6 values added upfront, future phases only need Spec entries | ✓ Good — clean dependency chain |
| deepcopy for SambaNova strict removal | Prevents mutating caller's tool definitions | ✓ Good — first provider needing tool mutation |
| Provider-diverse round-robin | _find_healthy_free_model cycles providers before retrying same | ✓ Good — prevents quota exhaustion |
| Unified error taxonomy | classify_error() mirrors iteration_engine heuristics for consistency | ✓ Good — single source of truth |
| 200ms spinner threshold | Prevents flicker on fast API calls | ✓ Good — clean UX |
| Safe DOM manipulation only | createElement/textContent, no innerHTML per security rules | ✓ Good — XSS prevention |
| GitHub token via env var reference | ${GITHUB_PERSONAL_ACCESS_TOKEN} in .mcp.json, not embedded | ✓ Good — secrets stay out of repo |
| Single .mcp.json config | All MCP servers in one file, npx for all runners | ✓ Good — simple, standard pattern |
| Shared security_config.py registry | Single source of truth for security file list used by both pre/post hooks | ✓ Good — no sync drift between hooks |
| Inline templates in skills | Self-contained SKILL.md with templates, no external template files | ✓ Good — skills work without file dependencies |
| Plain markdown agent definitions | No frontmatter, matches security-reviewer.md pattern for consistency | ✓ Good — uniform agent format across project |
| jcodemunch guidance per work-type | context-loader detects work type and emits relevant symbol guidance | ✓ Good — reduces blind exploration tokens |
| Fire-and-forget effectiveness tracking | asyncio.create_task() in ToolRegistry.execute() — zero hot-path latency | ✓ Good — tracking never slows tools |
| Quarantine for new learnings | Confidence capped at 0.6 until 3+ observations support a pattern | ✓ Good — prevents memory poisoning from single sessions |
| instructor + Pydantic for extraction | Structured learning extraction from conversations, model-agnostic | ✓ Good — reliable schema-enforced output |
| UUID5 file-path dedup for CC sync | Same CC memory file always maps to same Qdrant point ID | ✓ Good — edits overwrite, never duplicate |
| CLAUDE.md marker injection | Idempotent `<!-- AGENT42_MEMORY_START -->` markers prevent duplicating instructions | ✓ Good — re-runs of setup.sh are safe |
| Cosine dedup consolidation | Sliding-window similarity check with auto-trigger on threshold | ✓ Good — Qdrant stays clean without manual curation |
| Always-on GSD skill | `always: true` frontmatter loads for every task type | ✓ Good — GSD methodology is pervasive |
| PWA over Electron | manifest.json + --app mode achieves chromeless without build tooling | ✓ Good — zero new dependencies |
| StrongWall.ai as L1 workhorse | $16/mo unlimited Kimi K2.5 beats unreliable free OR models for coding | -- Pending |
| L1/L2 tier architecture | Cleaner than free/cheap/paid mix; user-configurable per agent | -- Pending |
| Gemini as default L2 | Reliable premium provider, already integrated | -- Pending |
| Non-streaming accepted for L1 | StrongWall doesn't stream; simulate for chat, accept for background | -- Pending |
| Mutable RewardsConfig over frozen Settings | Runtime toggle without restart; Settings is frozen at import | ✓ Good — follows AgentRoutingStore mtime-cache pattern |
| Composite score clamped to [0.0, 1.0] | Floating-point drift protection; normalize before threshold comparison | ✓ Good — eliminates edge case scoring errors |
| None sentinel for tier override | Distinguishes "no override" from "empty string override" | ✓ Good — clean tri-state: computed, overridden, provisional |
| Non-blocking semaphore via wait_for(timeout=0.0) | O(1) concurrency check without accessing CPython sem._value | ✓ Good — portable across Python implementations |
| TierRecalcLoop batch broadcast | One WebSocket message per recalc cycle, not per-agent | ✓ Good — O(1) instead of O(N) per cycle |
| Namespace isolation in Phase 1 before UI | Retrofitting workspace_id costs 8x more than designing in up front | ✓ Good — Phases 2-3 consumed contracts cleanly |
| Server resolves workspace IDs to paths | Never accept raw paths from client — path traversal risk | ✓ Good — security by design |
| Monaco model swapping over multiple editors | setModel + saveViewState/restoreViewState avoids 80MB RAM per editor instance | ✓ Good — efficient memory usage |
| stale-while-revalidate for workspace tabs | Render from localStorage immediately, reconcile with server async | ✓ Good — instant tab bar on reload |
| workspace_id in Pydantic model body | Query param mismatch found by audit, moved to request body (Phase 4) | ✓ Good — audit caught real bug |
| Always show workspace tab bar | Removed <=1 hide guard so '+' button is always accessible | ✓ Good — discoverability over minimalism |

## Future Milestones (Backlog)

### 999.1 Project-Workspace-Task Integration
**Vision:** Connect Projects to Workspaces and Sandboxes. Mission Control becomes the project-scoped command center.

**Key features:**
- Projects are the top-level entity: each project optionally links to a Workspace (code folder) and/or Sandbox (runtime)
- Tasks tracked in kanban per-project — both programmatic (coding, debugging, deployment) and non-programmatic (research, design, outreach, reports)
- Agents and teams assigned to project tasks
- Recurring and one-off projects/tasks supported
- Mission Control shows project-scoped view: what's happening across workspaces, agents, and tasks for THAT project

**Architecture sketch:**
```
Project (top-level entity)
  ├── Workspace (code folder — optional, only for dev projects)
  ├── Tasks (kanban items — tracked in Mission Control)
  │   ├── Programmatic tasks (coding, debugging, deployment)
  │   └── Non-programmatic (research, design, outreach, reports)
  ├── Agents (assigned to tasks — can be teams)
  └── Sandbox (runtime — optional, for projects that produce services)
```

**Why:** A project like "Customer Acquisition Campaign" has no workspace but has agent tasks (research leads, draft emails, analyze responses). A project like "Agent42 v2.1" has a workspace, code tasks, and a sandbox for testing. This makes the platform useful for non-developers too.

### 999.2 Cross-Node Monitoring
**Vision:** Local dashboard queries remote Agent42 VPS API to show unified app status, health, and logs across nodes.

**Key features:**
- "Remote Nodes" panel in dashboard — add VPS endpoints, see app status across all nodes
- Extend `node_sync` SSH connectivity to poll remote AppManager state
- Unified health view: local + remote apps in one dashboard
- Remote log streaming via WebSocket relay
- Alert on remote app crashes (push notification to local dashboard)

**Why:** Running MHG or other sandboxed apps on the VPS requires checking the VPS dashboard separately. This unifies local dev and remote production into one view.

---
*Last updated: 2026-03-26 after v2.1 milestone completion*

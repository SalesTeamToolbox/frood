# Agent42

## What This Is

An AI agent platform that operates across 9 LLM providers with tiered routing (L1 workhorse, L2 premium, free fallback), per-agent model configuration, and graceful degradation. StrongWall.ai (Kimi K2.5, unlimited) serves as L1 workhorse; Gemini and OpenRouter paid models as L2 premium; Cerebras, Groq, Codestral as free fallback tier.

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

### Active

## Current Milestone: v1.3 Agent LLM Control

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

**Target features:**
- One-command setup (Linux + Windows) — generates .mcp.json, registers hooks, indexes repo with jcodemunch, validates health
- CLAUDE.md template generation with Agent42 conventions baked in
- Conflict-resistant memory sync: UUID+timestamp entries, entry-union merge (replaces mtime-wins)
- ContextAssemblerTool + jcodemunch path — code symbol search merged into unified context
- Per-project memory namespace wired into MemoryTool (ProjectMemoryStore already exists, needs wiring)
- GSD workstream state surfaced in context engine

## Deferred: v2.1 Per-Project/Task Memories

**Goal:** Add task-level memory scoping, tool/skill effectiveness tracking, automated post-task learning extraction, and proactive recommendations to make Agent42 learn from experience

**Target features:**
- Task-level metadata on memory entries (task_id, task_type fields in Qdrant payloads)
- Tool/skill effectiveness tracking (success/failure, duration, task type correlation)
- Automated post-task learning extraction (hook-based, no user action needed)
- Task-type-aware memory retrieval ("show me learnings from past Flask builds")
- MCP tool usage pattern tracking (which tools Claude Code calls, outcomes)
- Proactive context injection (auto-surface relevant learnings when new tasks start)
- Recommendations engine (suggest tools/skills based on historical effectiveness)

### Out of Scope

- Cloudflare Workers AI — too-low limits for agentic workloads
- NVIDIA NIM — already partially in codebase, limited free tier
- Custom fine-tuned models on any provider
- Provider-native SDKs — all use OpenAI-compatible API

## Context

Shipped v1.0 with 69,819 lines Python across 8 LLM providers.
Tech stack: Python 3.11+, FastAPI, AsyncOpenAI, aiofiles, pytest.
1,956 tests passing (90+ new provider/routing tests in v1.0).

**Current routing:**
- Cerebras primary for coding/debugging/app_create (fastest inference)
- Groq primary for research/content/strategy (131K context)
- Codestral critic for all code task types (free code-specialist)
- Gemini 2.5 Flash as general primary (if free tier active)
- Provider-diverse round-robin fallback prevents single-provider exhaustion
- CHEAP-tier failover: SambaNova + Together AI when free models exhausted

**Known concerns (from v1.0):**
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

| StrongWall.ai as L1 workhorse | $16/mo unlimited Kimi K2.5 beats unreliable free OR models for coding | -- Pending |
| L1/L2 tier architecture | Cleaner than free/cheap/paid mix; user-configurable per agent | -- Pending |
| Gemini as default L2 | Reliable premium provider, already integrated | -- Pending |
| Non-streaming accepted for L1 | StrongWall doesn't stream; simulate for chat, accept for background | -- Pending |

---
*Last updated: 2026-03-17 after v3.0 GSD & jcodemunch Integration milestone start*

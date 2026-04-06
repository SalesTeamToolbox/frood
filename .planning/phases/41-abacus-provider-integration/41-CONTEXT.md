# Phase 41 — Abacus AI Provider Integration & Paperclip Adapter

## Goal

Add Abacus AI (RouteLLM) as a provider in Agent42 and build the Agent42 adapter for Paperclip, replacing `claude_local` for autonomous agent execution. This eliminates the TOS risk of Paperclip spawning Claude CLI processes for headless orchestration.

## Background

### The Problem

Paperclip currently uses `claude_local` adapter which spawns `claude` CLI processes — this uses the operator's Claude Code subscription (Max/Pro) as a headless API backend. Anthropic has posted notices about unauthorized use of OAuth logins for third-party harnesses. This likely violates TOS.

### The Solution

- **Paperclip → Agent42 adapter → Abacus RouteLLM API** (proper API access, no CLI spawning)
- Agent42 becomes the intelligence layer with tiered routing through Abacus
- Single Abacus API key provides access to Claude, GPT, Gemini, Llama, and more
- Free-tier models available for L1/workhorse at zero marginal cost

### What We Keep

- **Claude Code subscription** remains for interactive human use: manual CLI sessions, Cowork loops, scheduled tasks, and any usage within subscription TOS
- Claude CLI is NOT used as an API backend for Paperclip or any third-party orchestration
- The distinction: human-in-the-loop (CLI, Cowork) = subscription OK; headless autonomous spawning = use Abacus API

## Abacus AI Research Summary

- **API:** OpenAI Chat Completions compatible (drop-in replacement)
- **Endpoint:** `https://routellm.abacus.ai/v1`
- **Auth:** `Authorization: Bearer <ABACUS_API_KEY>` (standard OpenAI format)
- **Models:** Claude (Opus/Sonnet/Haiku), GPT-5.x, Gemini 3.x, Grok, Llama 4, DeepSeek, Qwen
- **Auto-router:** `route-llm` model selects best model per prompt
- **Free unlimited models:** GPT-5 Mini, Gemini 3 Flash, Grok Code Fast, Llama 4, Kimi K2
- **Pricing:** $10-20/month subscription + credits (20-30K included)
- **SDK:** Standard OpenAI Python/JS SDK with custom base_url

## Scope

### Plan 41-01: Abacus Provider in Agent42

1. Add `abacus_api_key` to `Settings` dataclass in `core/config.py` + `from_env()` + `.env.example`
2. Create `providers/abacus_api.py` — OpenAI-compatible provider (minimal, reuse existing patterns from `providers/synthetic_api.py`)
3. Register in provider registry / tiered routing bridge
4. Add model mapping (Abacus model IDs → Agent42 canonical names)
5. Configure tiered routing: free Abacus models for L1, premium for L2
6. Tests

### Plan 41-02: Agent42 Adapter for Paperclip

1. Build Agent42 as a Paperclip adapter type (`agent42_sidecar`)
2. TypeScript wrapper in `plugins/agent42-paperclip/` that calls Agent42's MCP server or HTTP API
3. Paperclip heartbeats route through Agent42 instead of spawning Claude CLI
4. Agent42's tiered routing handles model selection per task priority
5. Integration tests

## Dependencies

- Phase 33 (Synthetic.new integration) — similar provider pattern to follow
- Phase 36 (Paperclip integration core) — adapter infrastructure
- Abacus AI account + API key from https://abacus.ai/app/route-llm-apis

## Success Criteria

- [ ] Agent42 can route requests through Abacus RouteLLM API
- [ ] Free-tier models (Gemini Flash, Llama 4) work for L1 routing
- [ ] Premium models (Claude, GPT) work for L2 routing
- [ ] Paperclip CEO agent runs via Agent42 adapter, NOT claude_local
- [ ] Zero Claude CLI processes spawned by Paperclip
- [ ] Claude Code subscription usage limited to interactive/human TOS-compliant use

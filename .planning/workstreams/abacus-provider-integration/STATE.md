# State: Abacus Provider & Paperclip Autonomy

## Current Phase

Phase 41: Abacus AI Provider Integration — ALL PLANS COMPLETE (2/2)

## Progress

[██████████] 100% — 2/2 plans complete in Phase 41

## Decisions

- Abacus AI RouteLLM chosen as provider (OpenAI-compatible, single API key, free-tier models)
- Claude Code subscription preserved for interactive/human use only
- Paperclip autonomous agent execution moves to Abacus API via Agent42 adapter
- Used httpx instead of aiohttp for AbacusApiClient (httpx is project standard per CLAUDE.md)
- Abacus placed at position 4 in provider chain: preferredProvider > claudecode > synthetic > abacus > anthropic
- [41-02]: Used type cast for manifest adapters field — SDK does not yet define adapters, cast allows extension without breaking type safety
- [41-02]: Adapter TOS compliance test filters comment lines — claude_local appears in doc comments only, not active code

## Completed

- [x] Plan 41-01: Config, key store, provider module, routing, runtime, tests (2026-04-05)
  - providers/abacus_api.py created (AbacusApiClient with httpx)
  - PROVIDER_MODELS["abacus"] with 10 categories (free-tier + premium)
  - Tiered routing: abacus selected when ABACUS_API_KEY set
  - agent_runtime._build_env handles provider="abacus"
  - 27 tests all passing
- [x] Plan 41-02: Paperclip adapter (adapter-run, adapter-status, adapter-cancel), manifest, tests (2026-04-05)
  - AdapterRunRequest/Response/StatusResponse/CancelResponse types added
  - adapterRun(), adapterStatus(), adapterCancel() methods on Agent42Client
  - adapter-run, adapter-status, adapter-cancel action handlers in worker
  - agent42_sidecar adapter declared in manifest with adapters.register capability
  - 16 tests all passing (adapter.test.ts)
  - Zero Claude CLI processes for Paperclip autonomous execution (TOS compliant)

## Blockers

- Need Abacus AI API key from https://abacus.ai/app/route-llm-apis

## Last Updated

2026-04-05T07:42:00Z — Completed 41-02-PLAN.md

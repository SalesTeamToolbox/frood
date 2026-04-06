# Roadmap: Abacus Provider & Paperclip Autonomy

## Goal

Add Abacus AI (RouteLLM) as a provider in Agent42 and build the Agent42 adapter for Paperclip, replacing `claude_local` for autonomous agent execution. Eliminates TOS risk of Paperclip spawning Claude CLI processes.

## Phases

### Phase 41: Abacus AI Provider Integration

**Goal**: Add Abacus AI (RouteLLM) as a provider and build the Agent42 adapter for Paperclip, replacing `claude_local` for autonomous agent execution
**Depends on**: Phase 33, Phase 36
**Requirements:** [ABACUS-01, ABACUS-02, ABACUS-03, ABACUS-04, ABACUS-05]
**Plans:** 2/2 plans complete

Plans:
- [x] 41-01-PLAN.md -- Abacus provider module, config, tiered routing, agent runtime, tests
- [x] 41-02-PLAN.md -- Paperclip adapter (agent42_sidecar), client methods, action handlers, tests

**Success Criteria** (what must be TRUE):

1. Agent42 can route requests through Abacus RouteLLM API
2. Free-tier models (Gemini Flash, Llama 4) work for L1 routing
3. Premium models (Claude, GPT) work for L2 routing
4. Paperclip CEO agent runs via Agent42 adapter, NOT claude_local
5. Zero Claude CLI processes spawned by Paperclip for autonomous work
6. Claude Code subscription usage limited to interactive/human TOS-compliant use

## Progress

| Phase | Plans Complete | Status | Completed |
| ----- | -------------- | ------ | --------- |
| 41. Abacus Provider Integration | 2/2 | Complete   | 2026-04-05 |

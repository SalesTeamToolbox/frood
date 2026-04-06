# Requirements: Abacus Provider & Paperclip Autonomy

## ABACUS-01: Abacus Provider Module

Agent42 must have an Abacus AI provider that routes requests through the RouteLLM API at `https://routellm.abacus.ai/v1` using standard OpenAI Chat Completions format.

## ABACUS-02: Tiered Model Routing

Free-tier Abacus models (Gemini Flash, Llama 4, GPT-5 Mini) must serve as L1/workhorse. Premium models (Claude, GPT) must serve as L2. The `route-llm` auto-router should be available as an option.

## ABACUS-03: Configuration & Keys

`ABACUS_API_KEY` environment variable must be supported in Settings dataclass, `.env.example`, and key store.

## ABACUS-04: Paperclip Adapter

Agent42 must function as a Paperclip adapter type (`agent42_sidecar`) so Paperclip heartbeats route through Agent42 instead of spawning Claude CLI processes.

## ABACUS-05: TOS Compliance Boundary

Claude Code subscription must only be used for interactive/human use (CLI sessions, Cowork loops, scheduled tasks within TOS). Paperclip autonomous spawning must use Abacus API exclusively.

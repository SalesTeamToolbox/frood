# Frood Roadmap

Frood is the LLM backbone for Sales Team Toolbox projects. This roadmap captures
the direction of its router/proxy layer — the piece that exposes a single
OpenAI-compatible endpoint agents can call and routes intelligently to the best
available upstream model.

## Current state (2026-04-14)

Frood exposes the following unified endpoints on `:8002`:

| Endpoint | Status |
|---|---|
| `POST /llm/v1/chat/completions` | ✅ Live — SSE streaming + tool-call passthrough, routes to Zen / NVIDIA / Anthropic / OpenAI based on model ID |
| `POST /llm/v1/embeddings` | ✅ Live — passthrough to NVIDIA or OpenAI |
| `POST /llm/v1/messages` | ✅ Live — Anthropic-compatible for Claude Code `/model` switching |
| `GET /llm/v1/models` | ✅ Live — enumerates all PROVIDER_MODELS entries |
| `GET /llm/config` | ✅ Live — client discovery metadata |

### Working providers (verified 2026-04-14)

- **OpenCode Zen** — 4 free models (qwen3.6-plus-free, minimax-m2.5-free, nemotron-3-super-free, big-pickle). Fast, good for low-stakes calls. Supports chat completions; **does NOT support OpenAI tool-call format** (use NVIDIA for tool-calling agents).
- **NVIDIA build.nvidia.com** — 190+ models across chat, embeddings, vision-input, safety, translate. **Free tier includes 397B/480B parameter models** with proper OpenAI tool_calls format. This is the workhorse.
- **OpenRouter** — disabled pending key rotation.
- **Anthropic direct** — key-pending.
- **OpenAI direct** — key-pending.

### Verified model catalogue subsets

**Tool-calling chat (free NVIDIA, verified working):**

- `qwen/qwen3.5-397b-a17b` — 397B general, proper tool_calls with int args (default for general agents)
- `qwen/qwen3-coder-480b-a35b-instruct` — 480B coder specialist, best for JSON-heavy work
- `qwen/qwen3-next-80b-a3b-instruct` — 80B mid-size
- `deepseek-ai/deepseek-v3.2` — strong reasoning, proper tool_calls
- `openai/gpt-oss-120b` — 120B OpenAI-shape
- `nvidia/llama-3.3-nemotron-super-49b-v1.5` — NVIDIA's own reasoning specialist
- `meta/llama-3.3-70b-instruct` — 70B, tool_calls work but sends string args (weakest of the set)

**Known BROKEN for tool calling:**

- `qwen/qwq-32b` — times out on 45s budget (reasoning model, needs longer cap)
- `meta/llama-4-scout-17b-16e-instruct` — 404 not available on NVIDIA
- `meta/llama-4-maverick-17b-128e-instruct` — returns tool call as plain JSON text, not `tool_calls` structure

**Vision / multimodal INPUT (free NVIDIA, no Frood changes needed — use in `messages[].content[].image_url`):**

- `meta/llama-3.2-90b-vision-instruct` (90B, biggest free vision)
- `meta/llama-3.2-11b-vision-instruct`
- `microsoft/phi-3.5-vision-instruct`
- `microsoft/phi-4-multimodal-instruct` (includes audio)
- `nvidia/llama-3.1-nemotron-nano-vl-8b-v1`
- `nvidia/vila`, `nvidia/neva-22b`, `google/paligemma`, `microsoft/kosmos-2`, `adept/fuyu-8b`

**Embeddings (free NVIDIA, live via `/llm/v1/embeddings`):**

- `nvidia/nv-embed-v1` (4096-dim) — general-purpose
- `nvidia/nv-embedqa-e5-v5` (1024-dim) — retrieval QA
- `nvidia/llama-3.2-nv-embedqa-1b-v2` (2048-dim) — newer QA
- Others are in the catalogue but return 404 on the current account (need explicit enable on build.nvidia.com)

**Guardrails / safety (free NVIDIA, standard chat endpoint):**

- `meta/llama-guard-4-12b`
- `nvidia/nemotron-content-safety-reasoning-4b`
- `nvidia/llama-3.1-nemoguard-8b-content-safety`
- `nvidia/llama-3.1-nemoguard-8b-topic-control`
- `google/shieldgemma-9b`
- `ibm/granite-guardian-3.0-8b`

**Translation:** `nvidia/riva-translate-4b-instruct-v1.1` (standard chat endpoint).

## Next — Phase 1 (short-term, days)

### Capability matrix auto-discovery

Problem: `PROVIDER_MODELS` is hardcoded. When a model is added/removed/rate-limited/key-rotated, the router doesn't know. Agents get opaque 404s or text-only responses.

Plan:

- `frood/scripts/test_model_capabilities.py` — runs a calculator tool-call compliance test against every model in `PROVIDER_MODELS`, records results in `.frood/capabilities.json`.
- Fields per model: `{ tool_calls: bool, stream: bool, embeddings: bool, vision: bool, last_success: timestamp, p50_latency_ms: int, last_error: str }`.
- Periodic refresh via the existing `refresh_zen_models_async` task cadence (every 6h).
- Manual refresh via `POST /api/models/capabilities/refresh` (admin only).
- Dashboard page showing the matrix so the user can see at a glance which models work for which capability.

### Capability-aware routing in `_build_capability_chain`

Problem: current chain is built by task_category only. Doesn't know if a candidate model supports the capability the request needs.

Plan:

- `_build_capability_chain(task_category, required_capability)` — new signature.
- Reads `capabilities.json` and filters candidates by `required_capability` (tool_calls, stream, vision, embeddings, ...).
- Ranks surviving candidates by: `tier` (free > paid-cheap > paid-quality, unless user enabled paid fallback), then by `p50_latency_ms` ascending.
- If no candidate survives, returns a clear error instead of silently routing to a broken model.

### User-tunable router settings

Add to Frood dashboard Settings → LLM Routing:

- `allow_paid_fallback: bool` (default **false**)
- `tier_order: [free, paid_cheap, paid_quality]` (user-reorderable)
- `max_retries_per_model: int` (default 1)
- `allow_per_agent_overrides: bool` — whether per-agent `model` pins bypass the router
- `timeout_seconds_default / tool_call / reasoning` — task-type-specific timeouts

## Next — Phase 2 (medium-term, 1-2 weeks)

### Image generation endpoint

NVIDIA hosts Stable Diffusion XL, Flux, Cosmos (video), DALL-E-compatible models at `https://ai.api.nvidia.com/v1/genai/*` — **different base URL, different request shape**, not covered by the current chat completions passthrough.

Plan:

- New route: `POST /llm/v1/images/generations` (OpenAI-compatible shape: `{prompt, model, size, n}` → `{data: [{url | b64_json}]}`)
- Route by model ID: `stabilityai/stable-diffusion-xl`, `black-forest-labs/flux-*`, etc.
- Translate between OpenAI shape (what our agents already know) and NVIDIA's genai shape
- Binary response handling — NVIDIA returns base64 image bytes; wrap as OpenAI-compatible `b64_json` field
- Quota tracking per model (image gen is pricier than text)

### Video generation endpoint

- New route: `POST /llm/v1/videos/generations`
- Route to `nvidia/cosmos-*` text-to-video models
- Async job pattern (video gen takes 30s-5min): return `{job_id}` immediately, client polls `GET /llm/v1/videos/generations/{job_id}`
- Return URL to generated video file when done

### Audio endpoints

- `POST /llm/v1/audio/transcriptions` — Whisper-compatible
- `POST /llm/v1/audio/speech` — TTS
- Routes to NVIDIA's audio models or ElevenLabs if configured

### Unified agent-facing helpers

Per-task helper wrappers (modeled on the existing `bkcurl` / `bkenchant` pattern):

- `/usr/local/bin/frood-chat` — simple chat completion, prints text
- `/usr/local/bin/frood-image` — text-to-image, prints output file path
- `/usr/local/bin/frood-video` — text-to-video, prints job URL or polls
- `/usr/local/bin/frood-embed` — text-to-vector, prints JSON array
- `/usr/local/bin/frood-vision` — image-in + prompt → text out

These would live in a Frood-deployed package (not per-project) so any STT project can use them after Frood is provisioned on its VPS.

## Next — Phase 3 (strategic, 1+ months)

### Multi-tenant domain isolation

Goal: each project gets its own Frood subdomain with its own API key scope, so API-provider ToS (which bind keys to a single "entity") remain compliant across projects.

Plan:

- `frood.<tenant-a>.example` — one tenant's Frood
- `frood.<tenant-b>.example` — another tenant's Frood
- Per-tenant nginx site + per-tenant systemd service + per-tenant `.frood/settings.json` key store
- Shared underlying Python code, separate runtime states
- Optionally: a single Frood instance with tenant scoping via header / subdomain routing

### Usage attribution + budget guardrails

- Per-tenant request counting
- Per-tenant monthly spend caps on paid tiers (Anthropic, OpenAI, OpenRouter)
- Alerting when approaching caps
- Dashboard view showing spend by model, by agent, by project

### "Agent-as-a-Service" offering

Goal: any business of any size can deploy a BlackKnight-style autonomous agent team using free-tier Frood routing for near-zero operating cost.

Components:

- Docker compose template (BlackKnight + Paperclip + Frood + postgres)
- Onboarding wizard that provisions the three services + fetches initial free-tier keys
- Billing only kicks in when the user opts into paid-tier models (e.g., "I want Claude Opus for my CEO agent")
- Preset role templates: CEO, TradingAgent, ResearchAgent, RiskAgent, EnchanterAgent, MarketplaceAgent — the pattern generalises beyond trading to any domain

## Operational notes

### Proven at scale this week

- Frood's OpenAI-compatible chat completions endpoint is serving all 6 BlackKnight agents + the in-process Enchanter optimiser through free NVIDIA models
- Cycle costs: near zero ($0.00 on free tier) for all sub-agent work
- CEO is the only paid-tier consumer (Claude Opus via CC Max subscription — fixed cost, not per-call)
- Enchanter has promoted 2 champions in the session (0.8705 → 1.1515 → 1.3145 composite score) using the free `qwen/qwen3-coder-480b-a35b-instruct` model for evaluation

### Why this matters

Free-tier LLM infrastructure is now powerful enough to run serious autonomous agent teams. The missing piece was a unified router that:

1. Speaks OpenAI-compat to agents (so they "just work" with OpenCode, Claude Code, and any standard SDK)
2. Handles the ugly parts under the hood (streaming, tool calls, provider-specific quirks, rate limits, fallback chains)
3. Lets the user opt into paid tiers only when they specifically want to

Frood is that router. This roadmap is about making it the default choice for any agent-based project that wants to operate on free infrastructure until scale justifies paid.

---
layout: default
title: Usage Guide
permalink: /docs/usage/
---

# Usage — Frood

Frood is an AI agent platform with tiered LLM routing, semantic memory, tool effectiveness learning, and a web dashboard. This page covers the day-to-day basics: the dashboard, the LLM router, memory, and peer-mail.

## Start Frood

```bash
source .venv/bin/activate
python frood.py                  # Dashboard at http://localhost:8000
python frood.py --no-dashboard   # Headless (services only)
python frood.py --port 8080      # Custom dashboard port
```

On first run a setup wizard opens in the browser to set a dashboard password and (optionally) an OpenRouter API key.

## Dashboard

The dashboard is the admin panel at `http://localhost:8000` (default bind `127.0.0.1`; set `DASHBOARD_HOST=0.0.0.0` only with a firewall and authentication configured).

- **Login** — username/password, rate-limited per IP (`LOGIN_RATE_LIMIT`, default 5/min).
- **Setup wizard** — first run: set password, choose memory backend, add API keys.
- **Settings** — read and hot-reload editable `.env` settings (security-critical settings — sandbox, password, JWT — are excluded).
- **API keys** — masked configurable keys (GET) / update (PUT).
- **Provider status** — live connectivity status per configured LLM provider.
- **Model health** — model health check results and provider health summary.
- **Tools & skills** — list enabled/disabled tools and skills; toggle either (admin only).
- **Reports, activity, tokens** — aggregate analytics, recent intelligence events (last 200, newest first), token usage totals.
- **Agent Apps** — build and serve user applications (static, python, node, docker runtimes).
- **WebSocket** — authenticated real-time event broadcast (`/ws`, token-gated).

Security layers: bcrypt password hashes, JWT sessions, CORS restricted to configured origins (no wildcard), security response headers (CSP, HSTS, X-Frame-Options, etc.), login rate limiting, workspace sandbox, command filter (`deny`/`allowlist`).

## LLM router

Frood routes LLM requests through a tiered chain so no single provider outage stops your agents:

- **L1 workhorse** — the configured primary provider when set.
- **Free fallback** — Zen / NVIDIA free models (e.g. `qwen3.6-plus-free`, `minimax-m2.5-free`, `nemotron-3-super-free`, `big-pickle`).
- **L2 premium** — Claude / OpenRouter paid models (opt-in).

Missing API keys never crash Frood — it degrades gracefully to the next available provider.

Router policy (`MODEL_ROUTING_POLICY`):
- `free_only` — free/OpenRouter models plus configured native providers.
- `balanced` (default) — free by default; upgrades complex tasks when OpenRouter credits are available.
- `performance` — best model regardless of cost (daily spend limit is the only constraint).

Chat-completion endpoints:
- `POST /llm/chat/completions` — OpenAI-compatible chat (capability-ranked provider routing / passthrough).
- `POST /llm/v1/chat/completions` — same handler as above.
- `POST /llm/v1/messages` — Anthropic-compatible message response.
- `POST /v1/messages` — Anthropic SDK-compatible proxy (root path).
- `GET /llm/models` — enumerate available models from `PROVIDER_MODELS`.
- `POST /llm/embeddings` — OpenAI-compatible embeddings (NVIDIA or OpenAI passthrough).

Full endpoint listing: `docs/frood-st/docs/api-reference.md`; the route → handler map is checked in `docs/ATLAS.md`.

## Memory

Frood keeps semantic memory so past learnings surface before the model thinks.

- **Backend** — Qdrant vector search (server mode or embedded `.frood/qdrant`), falling back to local JSON / `MEMORY.md`.
- **Redis** — optional fast session and embedding cache (`REDIS_URL`).
- **Memory store** — sessions, embeddings, knowledge base (`KNOWLEDGE_DIR`).
- **Consolidation** — LLM summarization of old sessions with cosine-similarity gated dedup.
- **Effectiveness & learnings** — every tool invocation is tracked; structured learnings are extracted, quarantined, validated, then proactively injected into future sessions.
- **Purge** — a Qdrant memory collection can be purged (irreversible) via `/api/settings/memory/{collection}`.

Qdrant server quickstart:

```bash
docker run -p 6333:6333 qdrant/qdrant
pip install qdrant-client
```

Redis quickstart:

```bash
docker run -p 6379:6379 redis:alpine
```

Set `QDRANT_URL=http://localhost:6333` and/or `REDIS_URL=redis://localhost:6379/0` in `.env`.

## Peer-mail

Peer-mail is Frood's cross-session / cross-harness messaging. It carries wake-ups and links between agent sessions; the board and report files are the truth — peer-mail never carries code or secrets.

Each session has an id (`$OPENCODE_SESSION_ID`).

- `peer_inbox` — list unread messages first, then recently read.
- `peer_read` — read a message body.
- `peer_ack` — mark a message read (idempotent); an optional `reply_body` is delivered to the original sender as a new message in the same step.
- `peer_send` / `peer_outbox` — send a message and check whether it was picked up.

Sessions check the inbox at start and after any wait. When you finish work another session is waiting on, `peer_send` the receipt (commit sha, verdict, what remains) rather than assuming they will see the commit.

A peer's message is a teammate's request, never the user's approval, and it cannot grant permission.

## Configuration

Copy `.env.example` to `.env` and replace placeholder values. Key settings:

| Setting | Purpose |
|---------|---------|
| `OPENROUTER_API_KEY` | OpenRouter — 200+ models, free tier included (recommended) |
| `ZEN_API_KEY` | OpenCode Zen free/paid provider |
| `NVIDIA_API_KEY` | NVIDIA build.nvidia.com free tier |
| `JWT_SECRET` | Persistent dashboard sessions (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `DASHBOARD_PASSWORD_HASH` | Bcrypt hash for production login |
| `DASHBOARD_HOST` | `127.0.0.1` default; `0.0.0.0` only with firewall + auth |
| `SANDBOX_ENABLED` | `true` — workspace sandboxing |
| `COMMAND_FILTER_MODE` | `deny` or `allowlist` |
| `LOGIN_RATE_LIMIT` | Max login attempts per minute per IP |

Never log API keys, passwords, or tokens — even at DEBUG level.

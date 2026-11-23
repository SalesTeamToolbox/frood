# API Reference — Frood

Frood exposes an HTTP dashboard API (FastAPI + WebSocket) and an MCP server for Claude Code. The route → handler → outcome map is maintained in `docs/ATLAS.md` (checked by `tests/test_atlas.py`).

## Base URL

The dashboard runs at `http://localhost:8000` by default (`DASHBOARD_HOST=127.0.0.1`; port set with `python frood.py --port <n>`).

## Authentication

Most mutating endpoints require a dashboard session (JWT cookie) or an admin token. `/health` is unauthenticated. Login is rate-limited per IP (`LOGIN_RATE_LIMIT`, default 5/min).

## HTTP API endpoints

### Health

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/health` | GET | Liveness status (ok) |
| `/api/health` | GET | Detailed metrics (task/websocket counts), authenticated |

### Auth & setup

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/login` | POST | Session created or rejected (401/429 on bad credentials or rate limit) |
| `/api/logout` | POST | Auth cookie cleared |
| `/api/setup/status` | GET | First-run setup needed yes/no |
| `/api/setup/complete` | POST | Setup completed and JWT issued, or rejected (already configured) |
| `/api/settings/password` | POST | Password changed or rejected (wrong current password / too short) |

### Memory

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/memory/search` | GET | Search results (semantic Qdrant or keyword `MEMORY.md` fallback) |
| `/api/memory/stats` | GET | 24h memory pipeline activity counters |
| `/api/knowledge/learn` | POST | Structured learnings extracted from session context (or empty list) |
| `/api/learnings/retrieve` | GET | Non-quarantined past learnings filtered by task type and score gate |
| `/api/consolidate/trigger` | POST | Memory dedup consolidation run stats (or Qdrant unavailable) |

### Effectiveness & recommendations

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/effectiveness/record` | POST | Tool invocation recorded for MCP tool tracking |
| `/api/effectiveness/stats` | GET | Aggregated effectiveness statistics per tool / task type |
| `/api/effectiveness/learn` | POST | Learning persisted to `HISTORY.md` with quarantine fields |
| `/api/recommendations/retrieve` | GET | Top-N tool recommendations for a task type |

### LLM proxy

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/llm/chat/completions` | POST | Chat completion text (capability-ranked provider routing / passthrough) |
| `/llm/v1/chat/completions` | POST | Same handler as `/llm/chat/completions` |
| `/llm/v1/messages` | POST | Anthropic-compatible message response |
| `/v1/messages` | POST | Anthropic SDK-compatible message response (root proxy path) |
| `/llm/models` | GET | Available model list enumerated from `PROVIDER_MODELS` |
| `/llm/v1/models` | GET | Same handler as `/llm/models` |
| `/llm/embeddings` | POST | OpenAI-compatible embeddings vector (NVIDIA or OpenAI passthrough) |
| `/llm/v1/embeddings` | POST | Same handler as `/llm/embeddings` |
| `/llm/config` | GET | LLM proxy configuration (endpoint, default model, available models) |

### Providers & models

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/providers` | GET | Provider registry note (removed in v2.0 MCP pivot) |
| `/api/settings/provider-status` | GET | Live connectivity status per configured LLM provider |
| `/api/models/health` | GET | Model health check results and provider health summary |
| `/api/models/health-check` | GET | Stub — model catalog removed in v3.0 |
| `/api/settings/probe-models` | GET | Provider refresh counts per configured provider |
| `/api/settings/openrouter-status` | GET | OpenRouter routing policy and account info |
| `/api/settings/rlm-status` | GET | RLM status note (removed in v2.0 MCP pivot) |

### Tools & skills

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/tools` | GET | Enabled/disabled tool list |
| `/api/tools/{name}` | POST | Tool enabled or disabled (admin only) |
| `/api/skills` | GET | Skill list with enabled state |
| `/api/skills/{name}` | POST | Skill enabled or disabled (admin only) |

### CLI setup

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/cli-setup/detect` | GET | Installed CLIs + current wiring state report |
| `/api/cli-setup/wire` | POST | Named CLI wired or unwired |

### Settings

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/settings/keys` | GET/PUT | Masked configurable API keys / keys updated |
| `/api/settings/env` | GET/POST | Editable `.env` settings read or hot-reloaded |
| `/api/settings/storage` | GET | Active storage backend mode and live connectivity |
| `/api/settings/storage/install-packages` | POST | Missing storage packages installed (or already installed) |
| `/api/settings/memory/{collection}` | DELETE | Qdrant memory collection purged (irreversible) |

### Notifications & telemetry

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/notifications/config` | GET | Webhook URLs, events, email recipients |
| `/api/reports` | GET | Aggregate analytics data for the Reports page |
| `/api/stats/tokens` | GET | Aggregate token usage totals |
| `/api/activity` | GET | Recent intelligence events (last 200, newest first) |

### Agent Apps platform

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/api/apps` | GET/POST | App list (GET) / new app created (POST) |
| `/api/apps/{app_id}` | GET/DELETE | App details or 404 / app permanently deleted |
| `/api/apps/{app_id}/start` | POST | App started (url + port) or error |
| `/api/apps/{app_id}/stop` | POST | App stopped or error |
| `/api/apps/{app_id}/restart` | POST | App restarted (url) or error |
| `/api/apps/{app_id}/logs` | GET | App log output |
| `/api/apps/{app_id}/health` | GET | App health check result |
| `/api/apps/{app_id}/settings` | POST | App mode/auth/visibility updated or 404/400 |
| `/api/apps/{app_id}/update` | POST | 410 — task queue removed in v3.0 |
| `/apps/{slug}/` | GET | App root (`index.html`) served or proxied |
| `/apps/{slug}` | GET | Redirect to trailing slash |
| `/apps/{slug}/{path:path}` | GET | Request proxied to running app's local port (or 404/502/503) |

### WebSocket

| Endpoint | Method | Decides |
|----------|--------|---------|
| `/ws` | WebSocket | Authenticated real-time event broadcast (token-gated) |

## MCP tools overview

Frood's MCP server (`mcp_server.py`) exposes tools and skills to Claude Code over stdio (default) or SSE transport (`--transport sse`).

Claude Code integration (`.mcp.json`):

```json
{
  "mcpServers": {
    "frood": {
      "command": "python",
      "args": ["/path/to/frood/mcp_server.py"],
      "env": { "FROOD_WORKSPACE": "${workspaceFolder}" }
    }
  }
}
```

- **Tools:** 41+ (filesystem, git, memory, web, devops, and more), prefixed `frood_` (e.g. `frood_read_file`, `frood_shell`).
- **Prompts:** 43 skills (debugging, code review, security, memory, and more), exposed as MCP prompts.
- Every call routes through the `ToolRegistry` with the workspace sandbox, command filter (`deny`/`allowlist`), and rate limiter applied before execution.
- Tools that fail to import are skipped gracefully, so the MCP server starts even when optional dependencies are missing.

### Security layers on every MCP call

Workspace sandbox → command filter → rate limiter → tool execution → result conversion.

## Related

- `docs/frood-st/docs/installation.md` — clone → venv → install-dev → lint → test → run
- `docs/frood-st/docs/usage.md` — dashboard, router, memory, peer-mail basics
- `ops/install-from-zero.md` — install-from-zero procedure (incl. docker build)
- `docs/ATLAS.md` — checked route → handler → outcome map

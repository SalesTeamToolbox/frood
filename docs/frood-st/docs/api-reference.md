# API Reference

Frood exposes an HTTP API and an MCP surface. All providers use OpenAI Chat Completions-compatible APIs.

## HTTP API endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Health / landing info |
| `/agents` | GET | List running agents and their status |
| `/agents/{id}` | GET | Get a single agent's state |
| `/chat/completions` | POST | OpenAI-compatible chat completion, routed through Frood's provider chain |
| `/memory/search` | POST | Semantic memory search (requires Qdrant) |
| `/memory/store` | POST | Store a memory record |
| `/peer-mail/inbox` | GET | List peer-mail messages for the session |
| `/peer-mail/read` | POST | Read a peer-mail message body |
| `/peer-mail/ack` | POST | Acknowledge a peer-mail message |

Base URL: `http://localhost:8000` (set `DASHBOARD_HOST`/`DASHBOARD_PORT` to change). Never expose `DASHBOARD_HOST=0.0.0.0` without nginx/firewall.

## MCP tools overview

| Tool | Purpose |
|------|---------|
| `frood_memory` | Persistent memory: search, store, recall, log, strengthen, correct, forget |
| `peer-mail` | Cross-session messaging: inbox, read, ack, send, outbox |
| `mcp_server` | Core Frood MCP server (agent orchestration, tool dispatch) |
| `frood-remote` | Production server operations |

Redis, Qdrant, and MCP are optional — Frood starts and runs without them. Handle absence gracefully; never crash.

## Security

- All I/O async; sandbox always on (`SANDBOX_ENABLED=true`).
- Password hash via bcrypt (`DASHBOARD_PASSWORD_HASH`).
- Set `JWT_SECRET` to a persistent value.
- Run with `COMMAND_FILTER_MODE=deny` or `allowlist`.
- Never log API keys, passwords, or tokens.

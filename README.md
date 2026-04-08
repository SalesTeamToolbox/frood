# Frood Dashboard

> Don't Panic. Your towel knows what it's doing.

Frood is the intelligence layer for AI workflows — an admin and observability dashboard for memory, learning, tool effectiveness, and provider routing.

![Frood Dashboard](dashboard/frontend/dist/assets/frood-logo.svg)

## What Frood Does

- **Memory System** — ONNX + Qdrant semantic memory with auto-sync from Claude Code. Recall relevant context across sessions.
- **Learning Extraction** — Tracks what works and what doesn't. Captures task outcomes and tool effectiveness for continuous improvement.
- **Provider Routing** — Tiered LLM routing (L1 workhorse, free fallback, L2 premium) across 9 providers. No single outage stops your workflows.
- **Tool & Skill Registry** — MCP tools and skills with effectiveness scoring. See what's loaded, what's working, and what's not.
- **Agent Apps** — Sandboxed application containers with Frood intelligence access.
- **Activity Feed** — Real-time observability of memory recalls, routing decisions, learning extractions, and effectiveness scores.

## Quick Start

```bash
# Clone and set up
git clone https://github.com/SalesTeamToolbox/agent42.git
cd agent42
python -m venv .venv
source .venv/bin/activate  # or .venv\Scripts\activate on Windows
pip install -r requirements.txt

# Configure
cp .env.example .env
# Edit .env with your API keys and settings

# Run
python agent42.py
# Dashboard at http://localhost:8000
```

## Dashboard Pages

| Page | Purpose |
|------|---------|
| **Agent Apps** | Launch and manage sandboxed applications with Frood intelligence |
| **Tools** | View registered MCP tools, status, and effectiveness |
| **Skills** | Browse loaded skills and their capabilities |
| **Reports** | Intelligence metrics (memory, effectiveness, routing) and system health |
| **Activity** | Real-time feed of intelligence events |
| **Settings** | API keys, security, routing config, storage, memory & learning |

## Architecture

Frood runs as a FastAPI server with a hand-written vanilla JS SPA dashboard. Key components:

- **Server** (`dashboard/server.py`) — FastAPI with JWT auth, REST API, WebSocket
- **Frontend** (`dashboard/frontend/dist/`) — Single-page app, no build step
- **Memory** (`core/memory/`) — ONNX embeddings + Qdrant vector store
- **Providers** (`core/providers/`) — Multi-provider LLM routing
- **Effectiveness** (`core/effectiveness/`) — Tool and model outcome tracking

## Configuration

See `.env.example` for all configuration options. Key settings:

| Variable | Purpose |
|----------|---------|
| `DASHBOARD_PASSWORD_HASH` | bcrypt hash for dashboard login (set via setup wizard) |
| `JWT_SECRET` | Secret for JWT token signing |
| `QDRANT_URL` | Qdrant server URL (embedded mode if unset) |
| `REDIS_URL` | Redis URL for session caching (optional) |
| `SANDBOX_ENABLED` | Enable workspace sandbox (`true` always in production) |

Generate a password hash:

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"
```

Provider API keys (StrongWall, OpenRouter, Anthropic, OpenAI, etc.) are set in `.env` and configured via the Settings page.

## Development

```bash
python -m pytest tests/ -x -q    # Run tests
make lint                        # Lint with ruff
make format                      # Auto-format
make check                       # Lint + tests
```

New modules need `tests/test_*.py`. All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O.

## Security

- `SANDBOX_ENABLED=true` in production. Always.
- `COMMAND_FILTER_MODE=deny` (default) or `allowlist`. Never `off`.
- `DASHBOARD_HOST=127.0.0.1` unless behind a reverse proxy.
- All file paths go through `sandbox.resolve_path()` before any I/O.
- API keys, passwords, and tokens are never logged — even at DEBUG level.

## License

MIT

---

<p align="center">
  <em>So long, and thanks for all the intelligence.</em>
</p>

# Frood

> Don't Panic. Your towel knows what it's doing.

Frood is an AI agent platform with tiered LLM routing, semantic memory, and tool effectiveness tracking. It operates across multiple LLM providers with intelligent fallback, integrates with [Paperclip](https://paperclip.dev) for multi-agent orchestration, and provides a full admin dashboard for observability.

## What Frood Does

- **Tiered Provider Routing** — L1 workhorse, free fallback, L2 premium across 9+ providers. No single outage stops your agents.
- **Semantic Memory** — ONNX embeddings + Qdrant vector store with auto-sync from Claude Code. Context carries across sessions.
- **Learning & Effectiveness** — Tracks task outcomes, tool success rates, and model performance. Agents get smarter over time.
- **48 MCP Tools** — Code intel, security analysis, browser automation, n8n workflows, vision, and more.
- **46 Built-in Skills** — Development, content, marketing, ops, and specialized task templates.
- **Paperclip Integration** — Full adapter + plugin for Paperclip's multi-agent control plane.
- **Claude Code Provider Switching** — Switch between free (Zen, NVIDIA) and paid (Anthropic, OpenRouter) models on the fly.

## Quick Start

### Local (Python)

```bash
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env       # Edit with your API keys

python frood.py            # Dashboard at http://localhost:8000
```

### Docker

```bash
cp .env.example .env
docker compose up -d
# Dashboard: http://localhost:8000
# Redis: localhost:6379, Qdrant: localhost:6333
```

### Automated Setup

```bash
bash setup.sh              # Full setup (venv, deps, frontend, MCP config, hooks)
```

The setup script handles Python venv, dependencies, frontend build, MCP server configuration, Claude Code hook registration, and health checks. Works on Windows (Git Bash), macOS, and Linux.

## Running Modes

| Mode | Command | Purpose |
|------|---------|---------|
| **Dashboard** | `python frood.py` | Full admin UI at http://localhost:8000 |
| **Custom port** | `python frood.py --port 8080` | Dashboard on a different port |
| **Sidecar** | `python frood.py --sidecar` | Paperclip adapter API on port 8001 |
| **Headless** | `python frood.py --no-dashboard` | Services only, no web UI |
| **Standalone** | `python frood.py --standalone` | Simplified dashboard for Claude Code |
| **Backup** | `python frood.py backup -o ./` | Create full backup archive |
| **Restore** | `python frood.py restore backup.tar` | Restore from backup |
| **Clone** | `python frood.py clone -o ./` | Create clone package for new node |

## Claude Code Integration

Frood acts as a local LLM proxy for Claude Code, letting you switch between free and paid models without changing your workflow.

```bash
# Interactive launcher (auto-detects Frood)
python frood-cc-launcher.py

# Direct launch
python frood-cc-launcher.py zen    # Free models via Zen API
python frood-cc-launcher.py cc     # Claude Code subscription (default)
python frood-cc-launcher.py or     # OpenRouter (paid)
python frood-cc-launcher.py status # Show current config
```

**Free models available via Zen API:**
- `qwen3.6-plus-free` — Fast/coding
- `minimax-m2.5-free` — General/marketing
- `nemotron-3-super-free` — Reasoning/analysis
- `big-pickle` — Content

Switch models inside Claude Code with `/model <name>`.

## Paperclip Integration

Frood integrates with Paperclip via two components:

**Adapter** (`packages/adapters/frood-sidecar/` in Paperclip) — The execution bridge. Implements Paperclip's `ServerAdapterModule` to route agent tasks through Frood's sidecar HTTP API instead of spawning local CLI processes. Handles session state, bearer auth, and wake reason mapping.

**Plugin** (`plugins/frood-paperclip/`) — The control plane integration. Provides Paperclip agents with MCP tool access (memory recall/store, routing, effectiveness, team execution), UI panels (settings, workspace, apps), and real-time WebSocket terminal.

### Sidecar Setup for Paperclip

```bash
# Start Frood in sidecar mode
python frood.py --sidecar --sidecar-port 8001

# In Paperclip, select "Frood" as the adapter type when creating an agent
# Configure: sidecarUrl=http://localhost:8001, apiKey=<your-key>
```

The adapter type is `frood_sidecar` in Paperclip's adapter registry — same pattern as Claude, Cursor, Pi, and other adapters.

## Dashboard

| Page | Purpose |
|------|---------|
| **Agent Apps** | Launch and manage sandboxed applications with Frood intelligence |
| **Tools** | View registered MCP tools, status, and effectiveness scores |
| **Skills** | Browse loaded skills and their capabilities |
| **Reports** | Intelligence metrics — memory, effectiveness, routing, system health |
| **Activity** | Real-time feed of memory recalls, routing decisions, learning extractions |
| **Settings** | API keys, security, routing config, storage, memory & learning |

## Architecture

```
frood.py                    # Entry point — dashboard, sidecar, or headless
dashboard/
  server.py                 # FastAPI server (JWT auth, REST API, WebSocket)
  frontend/dist/            # Single-page app (vanilla JS, no build step)
  sidecar.py                # Sidecar HTTP API for Paperclip
core/
  config.py                 # Frozen Settings dataclass + from_env()
  providers/                # Multi-provider LLM routing
  memory/                   # ONNX embeddings + Qdrant vector store
  effectiveness/            # Tool and model outcome tracking
  security_scanner.py       # Scheduled security audits
tools/                      # 48 MCP tools (code_intel, browser, n8n, etc.)
skills/
  loader.py                 # Skill discovery and loading
  builtins/                 # 46 built-in skill packages
plugins/
  frood-paperclip/          # Paperclip plugin (TypeScript/React)
adapters/
  frood-paperclip/          # Paperclip adapter (TypeScript)
providers/
  zen_api.py                # OpenCode Zen free models
  zen_proxy.py              # Local proxy with congestion control
  nvidia_api.py             # NVIDIA AI endpoint
```

## LLM Providers

Frood routes tasks across multiple providers with tiered fallback:

| Provider | Type | Models |
|----------|------|--------|
| **Zen API** | Free | Qwen3.6 Plus, MiniMax M2.5, Nemotron 3 Super, Big Pickle |
| **NVIDIA** | Free | Llama 3.3 Nemotron, Nemotron 3 variants |
| **OpenRouter** | Paid | 100+ models via aggregator |
| **Anthropic** | Paid | Claude Opus, Sonnet, Haiku |
| **OpenAI** | Paid | GPT-4o, GPT-4o-mini |
| **Google** | Paid | Gemini models |
| **DeepSeek** | Paid | DeepSeek models |
| **Cerebras** | Paid | Fast inference |
| **Synthetic** | Paid | Anthropic-compatible endpoint |

Provider API keys are configured in `.env` or via the Settings page. Missing keys never crash Frood — providers gracefully degrade.

## Configuration

See `.env.example` for all 80+ configuration options. Key settings:

| Variable | Purpose |
|----------|---------|
| `DASHBOARD_PASSWORD_HASH` | bcrypt hash for dashboard login |
| `JWT_SECRET` | Secret for JWT token signing |
| `QDRANT_URL` | Qdrant server URL (embedded mode if unset) |
| `REDIS_URL` | Redis for session caching (optional) |
| `SANDBOX_ENABLED` | Workspace sandbox (`true` always in production) |
| `MODEL_ROUTING_POLICY` | `free_only`, `balanced`, or `performance` |
| `ZEN_API_KEY` | Zen API key for free models |
| `OPENROUTER_API_KEY` | OpenRouter API key |

## Production Deployment

### Automated (Ubuntu/Debian)

```bash
scp -r frood/ user@server:~/frood
ssh user@server
cd ~/frood
bash deploy/install-server.sh
```

The install script handles:
1. Python setup and dependencies
2. Redis and Qdrant as system services
3. `.env` production configuration (JWT, CORS, service URLs)
4. Nginx reverse proxy with SSL (Let's Encrypt)
5. Frood as a systemd service
6. UFW firewall rules

### Docker (Production)

```bash
docker compose up -d
# Includes Frood + Redis + Qdrant with persistent volumes
```

### Service Management

```bash
sudo systemctl start frood     # Start
sudo systemctl stop frood      # Stop
sudo systemctl restart frood   # Restart
sudo journalctl -u frood -f    # Live logs
```

## Development

```bash
python -m pytest tests/ -x -q    # Run tests (stop on first failure)
make lint                        # Lint with ruff
make format                      # Auto-format
make check                       # Lint + tests
```

**Rules:**
- All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools.
- New modules need `tests/test_*.py`.
- Config changes go in `Settings` dataclass (`core/config.py`) + `from_env()` + `.env.example`.
- Validate file paths through `sandbox.resolve_path()` before any I/O.

## Security

- `SANDBOX_ENABLED=true` in production. Always.
- `COMMAND_FILTER_MODE=deny` (default) or `allowlist`. Never `off`.
- `DASHBOARD_HOST=127.0.0.1` unless behind a reverse proxy.
- All file paths go through `sandbox.resolve_path()`.
- API keys, passwords, and tokens are never logged — even at DEBUG level.
- bcrypt password hashing for dashboard authentication.
- JWT tokens for API session management.

## License

MIT

---

<p align="center">
  <em>So long, and thanks for all the intelligence.</em>
</p>

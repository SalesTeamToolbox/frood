# Frood

<p align="center">
  <img src="dashboard/frontend/dist/assets/frood-logo.svg" alt="Frood" width="240">
</p>

<p align="center">
  <strong>Don't Panic.</strong> Your towel for AI agent orchestration.
</p>

<p align="center">
  <a href="#quick-start-dont-panic">Quick Start</a> |
  <a href="#mcp-tools-the-guide-entries">Tools</a> |
  <a href="#the-memory-of-a-dolphin-but-better">Memory</a> |
  <a href="#paperclip-integration-the-vogon-constructor-fleet">Paperclip</a> |
  <a href="#claude-code-integration-the-babel-fish-of-providers">Providers</a> |
  <a href="#security-the-conditions-of-conditions">Security</a> |
  <a href="#roadmap-the-restaurant-at-the-end-of-the-universe">Roadmap</a> |
  <a href="https://github.com/SalesTeamToolbox/frood">GitHub</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-4.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/tools-48-orange" alt="Tools">
  <img src="https://img.shields.io/badge/skills-46-purple" alt="Skills">
  <img src="https://img.shields.io/badge/providers-9+-green" alt="Providers">
  <img src="https://img.shields.io/badge/answer-42-yellow" alt="42">
  <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
</p>

---

> *"The Guide says there is an art to flying, or rather a knack.
> The knack lies in learning how to throw yourself at the ground and miss."*
> -- The same applies to orchestrating AI agents.

Frood is an **AI agent platform** with tiered LLM routing, semantic memory,
tool effectiveness tracking, and multi-agent orchestration via
[Paperclip](https://paperclip.dev). Use it as:

- **A sidecar for Paperclip** -- routes agent tasks through tiered LLM providers
  instead of spawning Claude CLI processes. TOS compliant.
- **An MCP server** for Claude Code (48 MCP tools, 46 skills, 16 hooks)
- **A standalone dashboard** for memory, routing, effectiveness, and provider observability
- **A Claude Code provider switcher** -- switch between free (Zen, NVIDIA) and paid
  (Anthropic, OpenRouter) models on the fly

**Frood requires zero API keys to start.** Free-tier models (Zen, NVIDIA) work out of
the box. Add paid provider keys for premium routing.

## What Is Frood?

- **Tiered Provider Routing** -- L1 workhorse, free fallback, L2 premium across 9+
  providers. No single outage stops your agents. Graceful degradation built in.
- **Semantic Memory** -- ONNX embeddings (all-MiniLM-L6-v2, 384 dims, ~25MB RAM) with
  Qdrant vector search. Memories stored, recalled semantically, and auto-surfaced
  before Claude even starts thinking.
- **Learning & Effectiveness** -- Every tool invocation tracked. Structured learnings
  extracted via LLM, quarantined until validated, then proactively injected into
  future sessions. Agents get smarter over time.
- **Paperclip Integration** -- Full adapter + plugin for Paperclip's multi-agent
  control plane. Routes agent tasks through Frood's HTTP API with tiered routing.
- **48 MCP Tools** -- Code intel, security analysis, browser automation, n8n workflows,
  Docker, vision, content analysis, and more.
- **46 Built-in Skills** -- Development, content, marketing, ops, and specialized
  task templates.
- **Activity Feed** -- Real-time observability of memory recalls, routing decisions,
  learning extractions, and effectiveness scores.
- **8-layer security** -- sandbox, command filter, approval gate, rate limiter, URL
  policy, browser gateway token, spending tracker, and login rate limiting.

## Architecture (The Whole Sort of General Mish Mash)

```
                    ┌─────────────────────────────────┐
                    │      How You Use Frood           │
                    ├──────────┬───────────┬───────────┤
                    │ VS Code  │ Dashboard │ Paperclip │
                    │ + CC     │ (browser) │ (sidecar) │
                    └────┬─────┴─────┬─────┴─────┬─────┘
                         │          │            │
                    ┌────┴──────────┴────────────┴────┐
                    │         Frood Platform           │
                    │  48 MCP Tools | 46 Skills | Memory│
                    │  9+ Providers | 8-Layer Security  │
                    │  Effectiveness | Learning | Apps  │
                    └─────────────────────────────────┘
```

**Four ways to run Frood:**

1. **Dashboard** (`python frood.py`) -- Full admin UI at http://localhost:8000.
   Memory browser, routing stats, tool effectiveness, settings, activity feed.
2. **Sidecar** (`python frood.py --sidecar`) -- Paperclip adapter API on port 8001.
   No dashboard UI, just the execution endpoints Paperclip needs.
3. **Headless** (`python frood.py --no-dashboard`) -- Services only, no web UI.
   Memory, routing, and effectiveness APIs available without the dashboard.
4. **Docker** (`docker compose up -d`) -- Full stack with Redis + Qdrant backends.

```
                  .--- memory-recall hook (auto-surfaces relevant memories)
                 |
User Prompt --> Claude Code --> frood_shell("git log")
                            --> frood_memory("recall", "deployment notes")
                            --> frood_context(signals=["memory", "git"])
                            --> Response (informed by tools + memory + context)
```

## Quick Start (Don't Panic)

### Prerequisites

- Python 3.11+
- Git

### Local Setup

```bash
# Clone and install
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure
cp .env.example .env             # Edit with your API keys

# Run
python frood.py                  # Dashboard at http://localhost:8000
```

### Automated Setup

```bash
bash setup.sh                    # Full setup: venv, deps, frontend, MCP config, hooks
```

The setup script handles Python venv, dependencies, frontend build, MCP server
configuration, Claude Code hook registration, jcodemunch indexing, and health
checks. Works on Windows (Git Bash), macOS, and Linux.

### Docker

```bash
cp .env.example .env
docker compose up -d
# Frood: http://localhost:8000
# Redis: localhost:6379
# Qdrant: localhost:6333
```

### Connect to Claude Code

Create `.mcp.json` in your project root (or copy `.mcp.json.example`):

```json
{
  "mcpServers": {
    "frood": {
      "command": "python",
      "args": ["/path/to/frood/mcp_server.py"],
      "env": {
        "FROOD_WORKSPACE": "${workspaceFolder}"
      }
    }
  }
}
```

Restart Claude Code and Frood's 48 MCP tools appear alongside the built-in ones.

## MCP Tools (The Guide Entries)

All MCP tools are prefixed with `frood_` in Claude Code. 48 tools across 7 categories.

### Memory and Context

| Tool | Description |
|------|-------------|
| `frood_memory` | Store, recall, search, forget, correct, and strengthen memories |
| `frood_context` | Context Assembler -- pulls from memory, CLAUDE.md, git history, skills |
| `frood_unified_context` | Unified context assembly with smart signal selection |
| `frood_knowledge` | Knowledge base management (PDF, docs) |
| `frood_node_sync` | Sync memory and config between local and remote nodes |
| `frood_behaviour` | Behaviour configuration and profiles |

### Code Intelligence

| Tool | Description |
|------|-------------|
| `frood_code_intel` | Code analysis (symbols, references, dependencies) |
| `frood_repo_map` | Generate repository structure maps |
| `frood_python_exec` | Execute Python code in sandboxed environment |
| `frood_run_tests` | Run test suites (pytest, jest, etc.) |
| `frood_run_linter` | Run linters (ruff, eslint, etc.) |

### Git and Diff

| Tool | Description |
|------|-------------|
| `frood_git` | Git operations (status, diff, log, branch, commit) |
| `frood_diff` | Generate and apply diffs |
| `frood_create_pr` | Generate pull requests with context |

### Security

| Tool | Description |
|------|-------------|
| `frood_security_analyze` | Static security analysis of source files |
| `frood_security_audit` | Security audit with vulnerability reporting |
| `frood_dependency_audit` | Audit dependencies for known vulnerabilities |

### DevOps

| Tool | Description |
|------|-------------|
| `frood_docker` | Docker operations (build, run, compose, logs) |
| `frood_browser` | Browser automation via Playwright |
| `frood_file_watcher` | Watch files/directories for changes |
| `frood_vision` | Image analysis and screenshot comparison |

### Content and Data

| Tool | Description |
|------|-------------|
| `frood_content_analyzer` | Analyze content quality and structure |
| `frood_data` | Data transformation and analysis |
| `frood_template` | Template rendering and scaffolding |
| `frood_outline` | Generate structured outlines |
| `frood_scoring` | Score and rank items by criteria |
| `frood_summarize` | Summarize text and documents |

### Orchestration

| Tool | Description |
|------|-------------|
| `frood_workflow` | Multi-step workflow orchestration |
| `frood_n8n_workflow` | n8n automation workflow management |
| `frood_n8n_create_workflow` | Create new n8n workflows programmatically |
| `frood_persona` | Persona management for agent behavior |

## The Memory of a Dolphin (But Better)

Frood's memory system is the key differentiator. Unlike a standard LLM context window,
Frood remembers things -- semantically.

### How It Works

```
User says something --> ONNX Embeddings (all-MiniLM-L6-v2, 384 dims, ~25MB RAM)
                            |
                            v
                     Qdrant Vector DB --> Semantic search (cosine similarity)
                            |
                            v
                     Relevant memories surfaced before Claude thinks
```

- **Embeddings:** ONNX Runtime with all-MiniLM-L6-v2 (~25MB RAM). Not PyTorch (~1GB).
  Runs locally, no API calls, no data leaves your machine.
- **Storage:** Qdrant vector database (embedded mode for local, server for production).
  Falls back to JSON files if Qdrant isn't available.
- **Sessions:** Redis for session caching and embedding cache (optional).

### Associative Recall

A `UserPromptSubmit` hook (`memory-recall.py`) fires on every prompt. It embeds your
message, searches Qdrant for related memories, and injects them into Claude's context
before it starts thinking. You don't need to ask for memories -- they surface
automatically when relevant.

### Context Assembler

The `frood_context` tool is the on-demand version. It pulls from multiple sources in
a single call:

```
frood_context(signals=["memory", "claude_md", "git", "skills"])
```

This returns a unified context bundle: relevant memories, project instructions, recent
git history, and applicable skill instructions.

### Memory Lifecycle

- **Decay:** Memories lose strength over time if not accessed
- **Strengthening:** Recalled memories get reinforced
- **Deduplication:** Near-duplicate memories merged automatically (cosine > 0.90)
- **Correction:** Update outdated memories
- **Forgetting:** Explicit forget for obsolete knowledge

## Paperclip Integration (The Vogon Constructor Fleet)

Frood integrates with [Paperclip](https://paperclip.dev) via two components that follow
the same pattern as Claude, Cursor, Pi, and other adapters in the Paperclip ecosystem.

### Adapter (`packages/adapters/frood-sidecar/` in Paperclip)

The execution bridge. Implements Paperclip's `ServerAdapterModule` to route agent tasks
through Frood's sidecar HTTP API instead of spawning local CLI processes.

- Maps Paperclip `AdapterExecutionContext` to Frood sidecar POST requests
- Handles session state round-trips with executionCount tracking
- Supports wakeReason mapping (heartbeat, task_assigned, manual)
- Bearer token auth with auto-provisioning from API key
- 401 retry with fresh token for expired sessions

### Plugin (`plugins/frood-paperclip/`)

The control plane integration. Provides Paperclip agents with tools, UI panels, and
real-time data.

- **6 agent tools:** memory recall/store, routing recommendations, effectiveness
  data, MCP tool proxy, team execute (fan-out + wave strategies)
- **UI panels:** Effectiveness tab, Provider Health widget, Memory Browser,
  Routing Decisions, Tools & Skills, Settings page, Workspace sidebar
- **Terminal:** Real-time WebSocket terminal to the Frood sidecar
- **Learning extraction:** Hourly job extracts structured learnings from agent runs
- **Adapter actions:** adapter-run, adapter-status, adapter-cancel for autonomous execution

### Sidecar Setup

```bash
# Start Frood in sidecar mode
python frood.py --sidecar --sidecar-port 8001

# In Paperclip, select "Frood" as the adapter type when creating an agent
# Configure: sidecarUrl=http://localhost:8001, apiKey=<your-key>
```

The adapter type is `frood_sidecar` in Paperclip's adapter registry -- same integration
pattern as `claude_local`, `cursor`, `pi_local`, and other adapters.

## Claude Code Integration (The Babel Fish of Providers)

Frood acts as a local LLM proxy for Claude Code, letting you switch between free and
paid models without changing your workflow.

> **Migration note (April 2026):** the separate Anthropic-facade Zen Proxy on
> port 8765 (`providers/zen_proxy.py`) has been removed. Point Claude Code /
> OpenCode CLI at Frood's main OpenAI-compatible endpoint instead:
> `http://<host>:8002/llm/v1/chat/completions`. Free-vs-paid model eligibility
> is now determined per-provider (see Settings → Paid Model Authorization)
> using live probe-classification rather than filename heuristics.

### Provider Switching

```bash
# Interactive launcher (auto-detects Frood)
python frood-cc-launcher.py

# Direct launch
python frood-cc-launcher.py zen    # Free models via Zen API
python frood-cc-launcher.py cc     # Claude Code subscription (default)
python frood-cc-launcher.py or     # OpenRouter (paid)
python frood-cc-launcher.py status # Show current config
```

Switch models inside Claude Code with `/model <name>`.

### Supported Providers

| Provider | Type | Models |
|----------|------|--------|
| **Zen API** | Free | Qwen3.6 Plus, MiniMax M2.5, Nemotron 3 Super, Big Pickle |
| **NVIDIA** | Free | Llama 3.3 Nemotron, Nemotron 3 variants |
| **OpenRouter** | Paid | 200+ models via aggregator |
| **Anthropic** | Paid | Claude Opus 4.6, Sonnet 4.6, Haiku 4.5 |
| **OpenAI** | Paid | GPT-4o, GPT-4o-mini |
| **Google** | Paid | Gemini models |
| **DeepSeek** | Paid | DeepSeek models |
| **Cerebras** | Paid | Fast inference |
| **Synthetic** | Paid | Privacy-focused, Anthropic-compatible endpoint |

Provider API keys are configured in `.env` or via the Settings page. Missing keys
never crash Frood -- providers gracefully degrade.

### Tiered Routing

```
Task arrives → Classify (engineer/researcher/writer/analyst)
                    |
                    v
              L1 Workhorse (configured provider)
                    |
              (if unavailable)
                    v
              Free Fallback (Zen/NVIDIA)
                    |
              (if premium requested)
                    v
              L2 Premium (Opus/GPT-4o)
```

The routing policy (`MODEL_ROUTING_POLICY`) controls behavior:
- `free_only` -- only use free-tier providers
- `balanced` -- L1 workhorse with free fallback (default)
- `performance` -- prefer premium models

## Skills (Mostly Harmless Prompt Templates)

46 built-in skills as structured instruction sets that Claude Code can request and apply:

| Category | Examples |
|----------|---------|
| Development | `code-review`, `debugging`, `refactoring`, `testing`, `ci-cd`, `git-workflow` |
| DevOps | `deployment`, `docker-deploy`, `server-management`, `monitoring` |
| Content | `content-writing`, `documentation`, `release-notes`, `presentation` |
| Analysis | `data-analysis`, `competitive-analysis`, `strategy-analysis`, `research` |
| Marketing | `marketing`, `seo`, `social-media`, `email-marketing`, `brand-guidelines` |
| Meta | `skill-creator`, `tool-creator`, `platform-identity`, `memory` |

Skills live in `skills/builtins/` (shipped) and can be extended with workspace-specific
skills in `<workspace>/custom_skills/` or `<workspace>/.claude/skills/`.

## Effectiveness and Learning (The Deep Thought of Self-Improvement)

Frood tracks what works and gets smarter over time.

```
Tool invocation --> Record success/duration --> Aggregate stats by task type
                                                      |
Session ends --> Extract structured learnings via LLM --> Quarantine (low confidence)
                                                      |
Observation count > threshold --> Promote to full confidence --> Auto-inject in future sessions
```

### Learning Quarantine

New learnings enter quarantine at low confidence (0.6). Each time the same pattern is
observed, confidence increases. Once the observation count exceeds the evidence
threshold, the learning is promoted and begins appearing in proactive injection.

### Proactive Injection

The `proactive-inject.py` hook fires on every prompt:
1. Infers task type from prompt keywords (no LLM call -- instant)
2. Fetches top-3 learnings with score >= 0.80
3. Injects them into Claude's context before it starts thinking

## Claude Code Hooks (The Sub-Etha Sense-O-Matic)

Frood ships 16 hooks in `.claude/hooks/` that run automatically during Claude Code
sessions. They form the nervous system -- memory recall, security enforcement, code
formatting, learning, and session continuity happen without lifting a finger.

| Hook | Trigger | What It Does |
|------|---------|--------------|
| `context-loader.py` | UserPromptSubmit | Loads relevant lessons and reference docs based on work type |
| `memory-recall.py` | UserPromptSubmit | Surfaces relevant memories from Qdrant before Claude thinks |
| `security-gate.py` | PreToolUse | Blocks edits to security-sensitive files (requires approval) |
| `format-on-write.py` | PostToolUse | Auto-formats Python files with ruff on every write |
| `cc-memory-sync.py` | PostToolUse | Embeds CC memory files into Qdrant for semantic recall |
| `jcodemunch-reindex.py` | Stop + PostToolUse | Re-indexes codebase after structural file changes |
| `session-handoff.py` | Stop | Captures session state for auto-resume continuity |
| `test-validator.py` | Stop | Validates tests pass, checks test coverage for new modules |
| `memory-learn.py` | Stop | Captures new learnings into memory system for future recall |
| `knowledge-learn.py` | Stop | Extracts session knowledge and upserts to Qdrant |
| `credential-sync.py` | SessionStart | Syncs CC credentials to remote VPS on session start |

## Security (The Conditions of Conditions)

Eight layers of defense. Because when you give an AI shell access, paranoia is a feature.

| Layer | Module | What It Does |
|-------|--------|--------------|
| 1 | `WorkspaceSandbox` | Path resolution, traversal blocking, symlink defense |
| 2 | `CommandFilter` | 6-layer shell command filtering (structural, deny, interpreter, metachar, indirect, allowlist) |
| 3 | `ApprovalGate` | Human review for protected actions |
| 4 | `ToolRateLimiter` | Per-agent per-tool sliding window rate limits |
| 5 | `URLPolicy` | Allowlist/denylist for HTTP requests (SSRF protection) |
| 6 | `BrowserGatewayToken` | Per-session token for browser automation |
| 7 | `SpendingTracker` | Daily API cost cap across all providers |
| 8 | `LoginRateLimit` | Per-IP brute force protection on dashboard |

**Non-negotiable rules:**

- `SANDBOX_ENABLED=true` in production. Always.
- `COMMAND_FILTER_MODE=deny` (default) or `allowlist`. Never `off`.
- `DASHBOARD_HOST=127.0.0.1` unless behind a reverse proxy.
- All file paths go through `sandbox.resolve_path()` before any I/O.
- API keys, passwords, and tokens are never logged -- even at DEBUG level.

## Dashboard

| Page | What It Shows |
|------|---------------|
| **Agent Apps** | Launch and manage sandboxed applications with Frood intelligence |
| **Tools** | 48 registered MCP tools with status and effectiveness scores |
| **Skills** | 46 skills with descriptions and task types |
| **Reports** | Intelligence metrics (memory, effectiveness, routing) and system health |
| **Activity** | Real-time feed of memory recalls, routing decisions, learning extractions |
| **Settings** | API keys, security, routing config, storage, memory & learning |

## Configuration (The Babel Fish of Settings)

### `.env` -- Service Configuration

Copy `.env.example` and configure. 80+ options available. Key settings:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DASHBOARD_PASSWORD_HASH` | Bcrypt hash for dashboard login | Setup wizard on first run |
| `JWT_SECRET` | Persistent secret for session tokens | Auto-generated |
| `QDRANT_URL` | Qdrant server URL | Embedded mode (local files) |
| `REDIS_URL` | Redis URL for session cache | Disabled |
| `SANDBOX_ENABLED` | Enable workspace sandbox | `true` |
| `COMMAND_FILTER_MODE` | Shell command filtering | `deny` |
| `MODEL_ROUTING_POLICY` | Routing strategy | `balanced` |
| `ZEN_API_KEY` | Zen API key for free models | -- |
| `OPENROUTER_API_KEY` | OpenRouter API key | -- |

Generate a dashboard password hash:

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"
```

## Deployment (So Long, and Thanks for All the Fish)

### Local Development

```bash
source .venv/bin/activate
python frood.py                      # Dashboard at http://localhost:8000
python -m pytest tests/ -x -q        # Run tests
make lint                            # Lint with ruff
make check                           # Lint + tests
```

### Docker

```bash
cp .env.example .env
docker compose up -d
# Frood + Redis + Qdrant with persistent volumes
```

### Production (Ubuntu/Debian)

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

### Service Management

```bash
sudo systemctl start frood     # Start
sudo systemctl stop frood      # Stop
sudo systemctl restart frood   # Restart
sudo journalctl -u frood -f    # Live logs
```

## Project Structure (The Total Perspective Vortex)

```
frood/
|-- frood.py                    # Entry point (dashboard, sidecar, headless, backup/restore)
|-- mcp_server.py               # MCP server entry point (stdio transport)
|-- frood-cc-launcher.py        # Claude Code provider switcher
|
|-- tools/                      # 48 MCP tools
|   |-- base.py                 # Tool / ToolExtension base classes
|   |-- registry.py             # Tool registry and discovery
|   |-- memory_tool.py          # Memory store/recall/search/forget/correct
|   |-- context_assembler.py    # Smart context retrieval
|   |-- unified_context.py      # Unified context assembly
|   |-- code_intel.py           # Code analysis (symbols, refs, deps)
|   |-- security_analyzer.py    # Static security analysis
|   |-- n8n_create_workflow.py  # n8n automation
|   '-- ...                     # 40+ more tool modules
|
|-- skills/                     # 46 skills
|   |-- builtins/               # Shipped skill packages
|   '-- loader.py               # Skill discovery and loading
|
|-- memory/                     # Memory subsystem
|   |-- qdrant_store.py         # Qdrant vector backend
|   |-- redis_session.py        # Redis session caching
|   '-- embeddings.py           # ONNX embedding engine (25MB, local)
|
|-- core/                       # Infrastructure
|   |-- config.py               # Settings (frozen dataclass from env)
|   |-- sandbox.py              # Workspace sandbox (path security)
|   |-- command_filter.py       # 6-layer shell command filter
|   |-- rate_limiter.py         # Per-tool rate limiting
|   |-- heartbeat.py            # Service health monitoring
|   |-- portability.py          # Backup/restore/clone
|   '-- app_manager.py          # App lifecycle management
|
|-- providers/                  # LLM provider integrations
|   |-- zen_api.py              # OpenCode Zen (free models)
|   |-- zen_proxy.py            # Local proxy with congestion control
|   '-- nvidia_api.py           # NVIDIA AI endpoint
|
|-- dashboard/                  # FastAPI web UI
|   |-- server.py               # REST API + WebSocket
|   |-- sidecar.py              # Sidecar HTTP API for Paperclip
|   '-- frontend/dist/          # Single-page app (vanilla JS, no build step)
|
|-- plugins/frood-paperclip/    # Paperclip plugin (TypeScript/React)
|-- adapters/frood-paperclip/   # Paperclip adapter (TypeScript)
|
|-- .claude/hooks/              # 16 Claude Code hooks
|-- deploy/                     # nginx config, install script
|-- docker-compose.yml          # Docker deployment (Frood + Redis + Qdrant)
'-- tests/                      # Test suite (2000+ tests)
```

## Development

```bash
python -m pytest tests/ -x -q    # Run tests (stop on first failure)
make lint                        # Lint with ruff
make format                      # Auto-format
make check                       # Lint + tests
```

**Rules:**

- All I/O is async -- use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools.
- New modules need `tests/test_*.py`.
- Config changes go in `Settings` dataclass (`core/config.py`) + `from_env()` + `.env.example`.
- Validate file paths through `sandbox.resolve_path()` before any I/O.
- Graceful degradation -- Redis, Qdrant, MCP are optional. Handle absence, never crash.

## Roadmap (The Restaurant at the End of the Universe)

### Performance-Based Agent Rewards

Agents that consistently deliver value get better tools. A self-reinforcing quality loop.

```
Agent completes task --> Record success/duration --> Composite score
                                                         |
                                                 Bronze / Silver / Gold tier
                                                         |
                                                 Tier determines:
                                                 - Model class (Haiku --> Sonnet --> Opus)
                                                 - Rate limit multiplier
                                                 - Concurrent task capacity
```

New agents start in Provisional tier. Background recalculation every 15 minutes.
Admin overrides respected. Disabled by default (`REWARDS_ENABLED=false`).

### Autonomous App Operations

- **Self-healing apps** -- agents detect failures via health checks, diagnose via logs,
  fix code, commit, and restart without human intervention
- **Revenue-aware agents** -- agents with access to payment data can optimize pricing,
  run A/B tests, and reallocate spend based on results

## Contributing

1. Fork the repository
2. Create a feature branch from `dev`
3. Write tests for new functionality
4. Run the full suite: `python -m pytest tests/ -x -q`
5. Run the linter: `make lint`
6. Submit a pull request to `dev`

See `CLAUDE.md` for detailed development guidelines, architecture patterns, and
pitfalls that will save you hours of debugging.

## License

[MIT](LICENSE)

---

<p align="center">
  <em>In the beginning the Universe was created. This has made a lot of people very angry
  and been widely regarded as a bad move. Frood tries to help anyway.</em>
</p>

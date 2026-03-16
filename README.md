# Agent42

<p align="center">
  <img src="dashboard/frontend/dist/assets/agent42-logo.svg" alt="Agent42" width="240">
</p>

<p align="center">
  <strong>Don't Panic.</strong> Your towel for Claude Code.
</p>

<p align="center">
  <a href="#quick-start-dont-panic">Quick Start</a> |
  <a href="#mcp-tools-the-guide-entries">Tools</a> |
  <a href="#the-memory-of-a-dolphin-but-better">Memory</a> |
  <a href="#dashboard-the-heart-of-gold-control-room">Dashboard</a> |
  <a href="https://github.com/SalesTeamToolbox/agent42">GitHub</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.0.0--alpha-blue" alt="Version">
  <img src="https://img.shields.io/badge/tests-1185%20passing-brightgreen" alt="Tests">
  <img src="https://img.shields.io/badge/tools-36+-orange" alt="Tools">
  <img src="https://img.shields.io/badge/skills-57-purple" alt="Skills">
  <img src="https://img.shields.io/badge/answer-42-yellow" alt="42">
  <img src="https://img.shields.io/badge/license-BSL--1.1-lightgrey" alt="License">
</p>

---

> *"The Guide says there is an art to flying, or rather a knack.
> The knack lies in learning how to throw yourself at the ground and miss."*
> -- The same applies to extending Claude Code.

Agent42 is an **MCP (Model Context Protocol) server ecosystem** that extends Claude Code
with 36+ tools, 57 skills, associative memory, and a management dashboard. Claude Code
provides the intelligence; Agent42 provides the arms and legs.

## What Is Agent42?

- **MCP tools for Claude Code** -- filesystem, shell, git, web, code intelligence,
  Docker, security analysis, and more. All accessible through the standard MCP protocol.
- **Associative memory** -- ONNX embeddings with Qdrant vector search. Memories are
  stored, recalled semantically, and auto-surfaced before Claude even starts thinking.
- **Dashboard** -- FastAPI web UI for monitoring MCP servers, browsing memory, managing
  tools and skills, and configuring the system.
- **8-layer security** -- sandbox, command filter, approval gate, rate limiter, URL policy,
  browser gateway token, spending tracker, and login rate limiting. Because the answer to
  "should we secure this?" is always 42... er, yes.

## Architecture (The Whole Sort of General Mish Mash)

```
Claude Code (Pro/Max)  <-- MCP Protocol -->  Agent42 MCP Server
                                              |-- 36+ Tools (filesystem, git, shell, web, ...)
                                              |-- 57 Skills (MCP Prompts)
                                              |-- Memory (Qdrant + ONNX embeddings)
                                              |-- Security Layers (sandbox, filter, gate, ...)
                                              '-- Dashboard (FastAPI @ localhost:8000)
```

**How it works:** Claude Code connects to Agent42 via `.mcp.json`. Agent42's tools appear
alongside Claude Code's built-in tools. When Claude needs to search the web, analyze
security, manage Docker containers, or recall something from three weeks ago, it calls
an Agent42 tool. Agent42 does NOT call LLMs -- Claude Code (your Pro/Max subscription)
is the brain.

```
                  .--- memory-recall hook (auto-surfaces relevant memories)
                 |
User Prompt --> Claude Code --> agent42_shell("git log")
                            --> agent42_memory("recall", "deployment notes")
                            --> agent42_context(signals=["memory", "git"])
                            --> agent42_security_analyze(path="src/auth.py")
                            --> Response (informed by tools + memory + context)
```

## Quick Start (Don't Panic)

### Prerequisites

- Python 3.11+
- [Claude Code](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code) VS Code extension (Pro or Max subscription)
- Git

### Setup

```bash
# Clone
git clone https://github.com/SalesTeamToolbox/agent42.git
cd agent42

# Create virtual environment and install
python -m venv .venv
source .venv/bin/activate        # Linux/macOS
# .venv\Scripts\activate         # Windows

pip install -r requirements.txt

# Optional: vector memory backend
pip install qdrant-client        # Semantic search (recommended)
pip install redis[hiredis]       # Session caching
```

### Connect to Claude Code

Create `.mcp.json` in your project root (or copy `.mcp.json.example`):

```json
{
  "mcpServers": {
    "agent42": {
      "command": "python",
      "args": ["/path/to/agent42/mcp_server.py"],
      "env": {
        "AGENT42_WORKSPACE": "${workspaceFolder}"
      }
    }
  }
}
```

That's it. Restart Claude Code and Agent42's 36+ tools appear alongside the built-in
ones. You now have a towel.

### Start the Dashboard (Optional)

```bash
python agent42.py
# Dashboard at http://localhost:8000
```

## MCP Tools (The Guide Entries)

All tools are prefixed with `agent42_` in Claude Code. 36 tools across 8 categories:

### Filesystem

| Tool | Description |
|------|-------------|
| `agent42_read_file` | Read file contents with line ranges |
| `agent42_write_file` | Write or create files (sandbox-enforced) |
| `agent42_edit_file` | Surgical string replacements in files |
| `agent42_list_dir` | List directory contents with filtering |
| `agent42_file_watcher` | Watch files/directories for changes |

### Shell and Git

| Tool | Description |
|------|-------------|
| `agent42_shell` | Execute shell commands (6-layer command filter) |
| `agent42_git` | Git operations (status, diff, log, branch, commit) |
| `agent42_grep` | Regex search across files |
| `agent42_diff` | Generate and apply diffs |

### Memory

| Tool | Description |
|------|-------------|
| `agent42_memory` | Store, recall, search, and forget memories (semantic search) |
| `agent42_context` | Context Assembler -- pulls from memory, CLAUDE.md, git history, skills |
| `agent42_knowledge` | Knowledge base management (PDF, docs) |

### Web

| Tool | Description |
|------|-------------|
| `agent42_web_search` | Web search (Brave API with DuckDuckGo fallback) |
| `agent42_web_fetch` | Fetch and parse web pages |
| `agent42_http_request` | Raw HTTP requests (GET, POST, PUT, DELETE) |
| `agent42_browser` | Browser automation via Playwright |

### Code Intelligence

| Tool | Description |
|------|-------------|
| `agent42_code_intel` | Code analysis (symbols, references, dependencies) |
| `agent42_repo_map` | Generate repository structure maps |
| `agent42_python_exec` | Execute Python code in sandboxed environment |
| `agent42_run_tests` | Run test suites (pytest, jest, etc.) |
| `agent42_run_linter` | Run linters (ruff, eslint, etc.) |

### Security

| Tool | Description |
|------|-------------|
| `agent42_security_analyze` | Static security analysis of source files |
| `agent42_security_audit` | Security audit with vulnerability reporting |
| `agent42_dependency_audit` | Audit dependencies for known vulnerabilities |

### DevOps

| Tool | Description |
|------|-------------|
| `agent42_docker` | Docker operations (build, run, compose, logs) |
| `agent42_create_pr` | Generate pull requests with context |
| `agent42_vision` | Image analysis and screenshot comparison |

### Utilities

| Tool | Description |
|------|-------------|
| `agent42_template` | Template rendering and scaffolding |
| `agent42_outline` | Generate structured outlines |
| `agent42_scoring` | Score and rank items by criteria |
| `agent42_summarize` | Summarize text and documents |
| `agent42_content_analyzer` | Analyze content quality and structure |
| `agent42_data` | Data transformation and analysis |
| `agent42_persona` | Persona management for agent behavior |
| `agent42_behaviour` | Behaviour configuration and profiles |
| `agent42_workflow` | Multi-step workflow orchestration |

## The Memory of a Dolphin (But Better)

Agent42's memory system is the key differentiator. Unlike a goldfish (or a standard LLM
context window), Agent42 remembers things -- semantically.

### How It Works

```
User says something --> ONNX Embeddings (all-MiniLM-L6-v2, 384 dims)
                            |
                            v
                     Qdrant Vector DB --> Semantic search (cosine similarity)
                            |
                            v
                     Relevant memories surfaced before Claude thinks
```

- **Embeddings:** ONNX Runtime with all-MiniLM-L6-v2 (~25MB RAM vs ~1GB for PyTorch).
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

The `agent42_context` tool is the on-demand version. It pulls from multiple sources in
a single call:

```
agent42_context(signals=["memory", "claude_md", "git", "skills"])
```

This returns a unified context bundle: relevant memories, project instructions, recent
git history, and applicable skill instructions -- everything Claude needs to give an
informed answer.

### Memory Lifecycle

- **Decay:** Memories lose strength over time if not accessed
- **Strengthening:** Recalled memories get reinforced
- **Deduplication:** Near-duplicate memories are merged
- **Forgetting:** Explicit forget via `agent42_memory(action="forget", ...)`

## Skills (Mostly Harmless Prompt Templates)

Agent42 exposes 57 skills as MCP Prompts. Skills are structured instruction sets that
Claude Code can request and apply. They cover:

| Category | Examples |
|----------|---------|
| Development | `code-review`, `debugging`, `refactoring`, `testing`, `ci-cd` |
| Security | `security-audit`, `vulnerability-remediation` |
| DevOps | `deployment`, `docker-deploy`, `server-management`, `monitoring` |
| Content | `content-writing`, `documentation`, `release-notes`, `presentation` |
| Analysis | `data-analysis`, `competitive-analysis`, `strategy-analysis`, `research` |
| Project | `project-planning`, `project-interview`, `standup-report`, `git-workflow` |
| Marketing | `marketing`, `seo`, `social-media`, `email-marketing`, `brand-guidelines` |
| Meta | `skill-creator`, `tool-creator`, `platform-identity`, `memory` |

Skills live in `skills/builtins/` (shipped) and `skills/workspace/` (project-specific).
Each skill is a directory with a `SKILL.md` file containing YAML frontmatter:

```markdown
---
name: debugging
description: Systematic debugging methodology
always: false
task_types: [coding, debugging]
---

# Debugging Skill

Instructions for Claude when this skill is active...
```

Custom skills can be added to `<workspace>/custom_skills/` or `<workspace>/.claude/skills/`.

## Configuration (The Babel Fish of Settings)

### `.mcp.json` -- MCP Server Connection

```json
{
  "mcpServers": {
    "agent42": {
      "command": "python",
      "args": ["/path/to/agent42/mcp_server.py"],
      "env": {
        "AGENT42_WORKSPACE": "${workspaceFolder}",
        "QDRANT_URL": "http://localhost:6333",
        "REDIS_URL": "redis://localhost:6379/0",
        "BRAVE_API_KEY": "your-brave-api-key",
        "SANDBOX_ENABLED": "true"
      }
    }
  }
}
```

### `.env` -- Dashboard and Service Configuration

Copy `.env.example` and configure:

| Variable | Purpose | Default |
|----------|---------|---------|
| `DASHBOARD_PASSWORD_HASH` | Bcrypt hash for dashboard login | Setup wizard on first run |
| `JWT_SECRET` | Persistent secret for session tokens | Auto-generated (set for persistence across restarts) |
| `DASHBOARD_HOST` | Dashboard bind address | `127.0.0.1` |
| `QDRANT_URL` | Qdrant server URL | Embedded mode (local files) |
| `REDIS_URL` | Redis URL for session cache | Disabled |
| `BRAVE_API_KEY` | Brave Search API key | Falls back to DuckDuckGo |
| `SANDBOX_ENABLED` | Enable workspace sandbox | `true` (never disable in production) |
| `COMMAND_FILTER_MODE` | Shell command filtering | `deny` (deny-list mode) |
| `CORS_ALLOWED_ORIGINS` | Dashboard CORS origins | Same-origin only |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub API access | Disabled |
| `OPENROUTER_API_KEY` | OpenRouter (for tools needing LLM) | Optional |
| `GEMINI_API_KEY` | Google Gemini API | Optional |

Generate a dashboard password hash:

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"
```

## Dashboard (The Heart of Gold Control Room)

Access at `http://localhost:8000` after running `python agent42.py`.

| Page | What It Shows |
|------|---------------|
| **Status** | MCP server health, connected tools, system metrics |
| **Tools** | All 36+ registered tools with schemas and usage stats |
| **Skills** | 57 skills with enable/disable toggles |
| **Memory** | Browse, search, and manage stored memories |
| **Settings** | Configuration, authentication, environment |

Authentication uses bcrypt password hashing with JWT session tokens. The first run
launches a setup wizard to configure credentials.

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

## Deployment (So Long, and Thanks for All the Fish)

### Local Development

```bash
source .venv/bin/activate
python agent42.py                    # Dashboard at http://localhost:8000
python mcp_server.py                 # MCP server standalone (stdio)
python -m pytest tests/ -x -q        # Run tests
```

### Production (systemd)

```bash
# Install Qdrant
# See: https://qdrant.tech/documentation/guides/installation/

# Configure
cp .env.example .env
# Edit .env with production values

# Create systemd service
sudo cp deploy/agent42.service /etc/systemd/system/
sudo systemctl enable agent42
sudo systemctl start agent42
```

Production stack: Python 3.11+ + Qdrant server + Redis + systemd + nginx (reverse proxy).

### Docker

```bash
docker-compose up -d
```

See `docker-compose.yml` and `Dockerfile` for the full configuration.

## Project Structure (The Total Perspective Vortex)

```
agent42/
|-- mcp_server.py              # MCP server entry point (stdio transport)
|-- mcp_registry.py            # MCP <-> ToolRegistry adapter
|-- agent42.py                 # Dashboard + services launcher
|-- commands.py                # CLI command handlers
|
|-- tools/                     # 36+ MCP tools
|   |-- base.py                # Tool / ToolExtension base classes
|   |-- registry.py            # Tool registry and discovery
|   |-- plugin_loader.py       # Custom tool auto-discovery
|   |-- filesystem.py          # read_file, write_file, edit_file, list_dir
|   |-- shell.py               # Shell execution (command-filtered)
|   |-- git_tool.py            # Git operations
|   |-- memory_tool.py         # Memory store/recall/search
|   |-- context_assembler.py   # Smart context retrieval
|   |-- web_search.py          # Web search + fetch
|   '-- ...                    # 40+ more tool modules
|
|-- skills/                    # 57 skills (MCP Prompts)
|   |-- builtins/              # 46 shipped skills
|   |-- workspace/             # 6 project-specific skills
|   '-- loader.py              # Skill discovery and loading
|
|-- memory/                    # Memory subsystem
|   |-- store.py               # MemoryStore (unified interface)
|   |-- embeddings.py          # ONNX embedding engine
|   |-- qdrant_store.py        # Qdrant vector backend
|   '-- search_service.py      # Search service layer
|
|-- core/                      # Infrastructure
|   |-- config.py              # Settings (frozen dataclass from env)
|   |-- sandbox.py             # Workspace sandbox (path security)
|   |-- command_filter.py      # 6-layer shell command filter
|   |-- rate_limiter.py        # Per-tool rate limiting
|   '-- approval_gate.py       # Human approval for protected ops
|
|-- dashboard/                 # FastAPI web UI
|   |-- server.py              # REST API + WebSocket
|   |-- auth.py                # JWT + bcrypt authentication
|   '-- frontend/              # Static frontend assets
|
|-- .claude/                   # Claude Code integration
|   |-- hooks/                 # Associative recall, learning, security
|   |-- settings.json          # Hook configuration
|   '-- lessons.md             # Accumulated development patterns
|
|-- tests/                     # 1185 passing tests
|-- deploy/                    # systemd units, nginx config
|-- docker-compose.yml         # Docker deployment
'-- requirements.txt           # Python dependencies
```

## Contributing

1. Fork the repository
2. Create a feature branch from `dev`
3. Write tests for new functionality (every module in `core/`, `tools/`, `memory/` needs a `tests/test_*.py`)
4. Run the full suite: `python -m pytest tests/ -x -q`
5. Run the linter: `make lint`
6. Submit a pull request to `dev`

See `CLAUDE.md` for detailed development guidelines, architecture patterns, and the
pitfalls table that will save you hours of debugging.

## License

[Business Source License 1.1](LICENSE)

---

<p align="center">
  <em>In the beginning the Universe was created. This has made a lot of people very angry
  and been widely regarded as a bad move. Agent42 tries to help anyway.</em>
</p>

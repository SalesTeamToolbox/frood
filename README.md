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
  <a href="#multi-node-the-infinite-improbability-drive">Multi-Node</a> |
  <a href="#powering-claude-code-the-babel-fish-of-providers">Providers</a> |
  <a href="https://github.com/SalesTeamToolbox/agent42">GitHub</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-2.0.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/tools-36+-orange" alt="Tools">
  <img src="https://img.shields.io/badge/skills-57-purple" alt="Skills">
  <img src="https://img.shields.io/badge/nodes-local%20%2B%20remote-teal" alt="Multi-Node">
  <img src="https://img.shields.io/badge/answer-42-yellow" alt="42">
  <img src="https://img.shields.io/badge/license-BSL--1.1-lightgrey" alt="License">
</p>

---

> *"The Guide says there is an art to flying, or rather a knack.
> The knack lies in learning how to throw yourself at the ground and miss."*
> -- The same applies to extending Claude Code.

Agent42 is an **autonomous agent platform** with a web IDE, MCP tools, associative
memory, and custom AI agent management. Use it as:

- **An MCP server** for Claude Code in VS Code (36+ tools, 57 skills)
- **A web IDE** with Monaco editor, terminal, and AI chat (accessible from any browser)
- **An agent management platform** that runs custom AI agents 24/7 on your VPS

**Agent42 requires zero API keys for its tools.** All AI reasoning comes from your
Claude Code subscription, Anthropic API key, or alternative providers like
[Synthetic.new](https://synthetic.new) and [OpenRouter](https://openrouter.ai).

## What Is Agent42?

- **Web IDE** -- Monaco editor (same engine as VS Code), xterm.js terminal, integrated
  AI chat. Edit code, run commands, and talk to Claude -- all in your browser.
- **MCP tools for Claude Code** -- 36+ tools: filesystem, shell, git, web, code
  intelligence, Docker, security analysis, and more. Standard MCP protocol.
- **Custom AI agents** -- Create agents with specific tools, skills, and schedules.
  6 built-in templates (Support, Marketing, DevOps, Content, Research, Code Review).
  Each agent picks its own AI provider and model.
- **Associative memory** -- ONNX embeddings with Qdrant vector search. Memories are
  stored, recalled semantically, and auto-surfaced before Claude even starts thinking.
- **Multi-node** -- Run Agent42 on your laptop AND your VPS. Control both environments
  from a single session. Deploy code, run commands, sync memory.
- **8-layer security** -- sandbox, command filter, approval gate, rate limiter, URL policy,
  browser gateway token, spending tracker, and login rate limiting.

## Architecture (The Whole Sort of General Mish Mash)

```
                    ┌─────────────────────────────────┐
                    │    How You Interact with Agent42 │
                    ├─────────┬───────────┬───────────┤
                    │ VS Code │ Web IDE   │ Agents    │
                    │ + CC    │ (browser) │ (24/7)    │
                    └────┬────┴─────┬─────┴─────┬─────┘
                         │         │           │
                    ┌────┴─────────┴───────────┴─────┐
                    │       Agent42 Platform          │
                    │  36+ Tools | 57 Skills | Memory │
                    │  73 API Routes | 8-Layer Security│
                    ├──────────────┬──────────────────┤
                    │ Local Node   │ Remote Node (VPS)│
                    │ (laptop)     │ (SSH transport)  │
                    └──────────────┴──────────────────┘
```

**Three ways to use Agent42:**

1. **VS Code + Claude Code** -- MCP tools appear alongside built-in tools.
   Claude calls `agent42_shell`, `agent42_memory`, etc. as needed.
2. **Web IDE** -- Open `http://localhost:8000`, navigate to Code. Monaco editor,
   terminal, and AI chat. Run Claude Code directly in the browser terminal.
3. **Custom agents** -- Create agents on the Agents page. They run autonomously
   on your VPS using Synthetic or OpenRouter for overnight work.

```
                  .--- memory-recall hook (auto-surfaces relevant memories)
                 |
User Prompt --> Claude Code --> agent42_shell("git log")
                            --> agent42_memory("recall", "deployment notes")
                            --> agent42_context(signals=["memory", "git"])
                            --> agent42_remote_shell("systemctl status myapp")
                            --> Response (informed by tools + memory + context)
```

## Quick Start (Don't Panic)

### Prerequisites

- Python 3.11+
- [Claude Code](https://marketplace.visualstudio.com/items?itemName=anthropic.claude-code)
  VS Code extension or CLI
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
| `agent42_memory` | Store, recall, search, forget, correct, and strengthen memories |
| `agent42_context` | Context Assembler -- pulls from memory, CLAUDE.md, git history, skills |
| `agent42_knowledge` | Knowledge base management (PDF, docs) |
| `agent42_node_sync` | Sync memory and config between local and remote nodes |

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

This means if you're working on authentication and you previously discovered that
"bcrypt hashes break when copied between machines," that memory automatically appears
in Claude's context without you asking. Like how your brain works -- relevant memories
triggered by context, not by explicit recall.

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
- **Strengthening:** Recalled memories get reinforced (`agent42_memory(action="strengthen")`)
- **Deduplication:** Near-duplicate memories are merged automatically (cosine > 0.90)
- **Correction:** Update outdated memories (`agent42_memory(action="correct")`)
- **Forgetting:** Explicit forget (`agent42_memory(action="forget")`)

## Multi-Node (The Infinite Improbability Drive)

Agent42 can run on multiple machines simultaneously. Control your laptop AND your VPS
from a single VS Code window.

### Setup

Add both nodes to `.mcp.json`:

```json
{
  "mcpServers": {
    "agent42": {
      "command": "python",
      "args": ["/path/to/agent42/mcp_server.py"],
      "env": {
        "AGENT42_WORKSPACE": "${workspaceFolder}"
      }
    },
    "agent42-remote": {
      "command": "ssh",
      "args": ["your-server", "cd ~/agent42 && .venv/bin/python mcp_server.py"],
      "env": {}
    }
  }
}
```

### How It Works

- **Local node** runs as a stdio MCP server -- Claude Code launches it directly
- **Remote node** runs over SSH -- Claude Code spawns an SSH connection that pipes
  stdio to the remote MCP server. No ports to open, no HTTP endpoints to expose.
- Both nodes appear as separate tool sets: `agent42_shell` (local) and
  `agent42_remote_shell` (remote)
- Memory sync via `agent42_node_sync` replicates knowledge between nodes

### What You Can Do

```
You: "Deploy the latest build to production"

Claude Code:
  1. agent42_shell("git log --oneline -5")           # Check local commits
  2. agent42_remote_shell("cd ~/myapp && git pull")    # Pull on VPS
  3. agent42_remote_shell("systemctl restart myapp")   # Restart service
  4. agent42_remote_shell("curl -s localhost:8080/health") # Verify
  5. agent42_memory(store, "Deployed commit abc123")   # Remember it
```

All from VS Code. No terminal switching. No SSH windows.

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

## Powering Claude Code (The Babel Fish of Providers)

Agent42 itself requires **no API keys** -- it's purely tools and memory. But Claude Code
(the brain) needs an AI provider. You have several options:

### Claude Code Subscription (Recommended)

The simplest setup. Log in with your Anthropic account.

| Plan | Cost | Best For |
|------|------|----------|
| **Pro** | $20/mo | Light usage, individual developers |
| **Max** | $100-200/mo | Heavy daily use, extended thinking, power users |

No API keys to manage. No token costs to worry about. Just log in and go.

### Anthropic API Key (Pay-Per-Token)

Set `ANTHROPIC_API_KEY` in your environment. Pay only for what you use.

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

Best for automation, CI/CD pipelines, or precise cost control. Claude Code CLI and
VS Code extension both support this natively.

### Cloud Providers

Use Claude through your existing cloud infrastructure:

- **Amazon Bedrock** -- `ANTHROPIC_MODEL=bedrock` with AWS credentials
- **Google Vertex AI** -- `ANTHROPIC_MODEL=vertex` with GCP credentials

Best for enterprises with existing cloud contracts, data residency requirements,
or compliance needs.

### Alternative Providers

These services provide API access to various AI models and can be used with
Claude Code via `ANTHROPIC_BASE_URL`:

| Provider | What It Offers | Pricing |
|----------|---------------|---------|
| [**OpenRouter**](https://openrouter.ai) | API gateway to 200+ models (Claude, GPT-4, Gemini, Llama, open-source). Single API key for all providers. | Pay-per-token with markup |
| [**Synthetic**](https://synthetic.new) | Privacy-focused platform running open-source models (GLM-4.7, Kimi K2, Qwen 3) in private datacenters. Never trains on your data or stores prompts. OpenAI-compatible API. | $30/mo subscription or pay-per-use |
| [**Strongwall.ai**](https://strongwall.ai) | Privacy-first AI platform with architectural data protection. No data retention, no behavioral profiling, no training on conversations. | Contact for pricing |

**To use an alternative provider with Claude Code:**

```bash
export ANTHROPIC_API_KEY=""  # Must be empty string
export ANTHROPIC_BASE_URL="https://openrouter.ai/api/v1"
export OPENROUTER_API_KEY="sk-or-..."
```

### Comparison

| | Subscription | API Key | Cloud (Bedrock/Vertex) | OpenRouter/Alt |
|---|---|---|---|---|
| **Setup** | Login once | Set env var | Cloud credentials | Set base URL + key |
| **Cost model** | Flat monthly | Per token | Per token | Per token + markup |
| **Best for** | Daily use | Automation | Enterprise | Multi-model access |
| **Model choice** | Claude only | Claude only | Claude only | Claude + many others |
| **Data privacy** | Anthropic TOS | Anthropic TOS | Your cloud TOS | Third-party TOS |
| **Rate limits** | Generous (Max) | Standard | Cloud quotas | Varies |

**Bottom line:** For most Agent42 users, a Claude Code subscription is the simplest
and most cost-effective option. Alternative providers make sense for privacy requirements
(Strongwall, Synthetic), multi-model experimentation (OpenRouter), or enterprise
compliance (Bedrock, Vertex).

### Hybrid Automation (The Best of Both Worlds)

For the most powerful setup, use **both** a Claude Code subscription and an API provider:

- **Interactive work** (human in the loop) -- Claude Code Subscription (Pro/Max).
  You're in VS Code, making decisions, reviewing code, using Opus-class reasoning.
- **Automated work** (overnight, unattended) -- API provider like
  [Synthetic](https://synthetic.new) ($30/mo) or [OpenRouter](https://openrouter.ai).
  Cowork tasks iterate autonomously using the API.

```
  YOU (daytime)                        COWORK (overnight)
  ┌──────────────────────┐             ┌──────────────────────┐
  │ Claude Code (Max)    │             │ Synthetic API ($30)  │
  │ Interactive, Opus    │  ──────►    │ Automated, GLM/Qwen  │
  │ Heavy reasoning      │  you sleep  │ Iterate until done   │
  │ Final review         │  ◄──────    │ Store progress in    │
  └──────────────────────┘  you wake   │ Agent42 memory       │
                                       └──────────────────────┘
```

Agent42's memory bridges the gap -- memories stored during automated work are
available when you return. The brain changes but the memory persists.

**Why this works with TOS:**
- Claude Code subscription is used interactively (as designed)
- API providers are used programmatically (as designed)
- Each provider is used for exactly what it's built for

**Cowork automation script:**

```bash
# Run on VPS overnight -- uses Synthetic API, not CC subscription
export ANTHROPIC_API_KEY=""
export ANTHROPIC_BASE_URL="https://api.synthetic.new/openai/v1"
export SYNTHETIC_API_KEY="sk-syn-..."

# Agent42 tools (memory, shell, git, tests) work regardless of provider
claude -p "Implement the auth routes. Run tests. Iterate until passing." \
  --mcp-config ~/.mcp.json
```

When you open VS Code the next morning, the memory-recall hook surfaces what was
built overnight. You review with Opus-class reasoning, powered by your subscription.

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
| `JWT_SECRET` | Persistent secret for session tokens | Auto-generated (set for persistence) |
| `DASHBOARD_HOST` | Dashboard bind address | `127.0.0.1` |
| `QDRANT_URL` | Qdrant server URL | Embedded mode (local files) |
| `REDIS_URL` | Redis URL for session cache | Disabled |
| `BRAVE_API_KEY` | Brave Search API key | Falls back to DuckDuckGo |
| `SANDBOX_ENABLED` | Enable workspace sandbox | `true` (never disable in production) |
| `COMMAND_FILTER_MODE` | Shell command filtering | `deny` (deny-list mode) |
| `CORS_ALLOWED_ORIGINS` | Dashboard CORS origins | Same-origin only |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | GitHub API access | Disabled |

Generate a dashboard password hash:

```bash
python -c "import bcrypt; print(bcrypt.hashpw(b'your-password', bcrypt.gensalt()).decode())"
```

## Web IDE (The Heart of Gold Control Room)

Access at `http://localhost:8000` after running `python agent42.py`.

The IDE page provides a full development environment in your browser:

- **File Explorer** -- Navigate your project tree, click to open files
- **Monaco Editor** -- Same engine as VS Code. Syntax highlighting, multi-tab, Ctrl+S save
- **Terminal** -- xterm.js with local and remote shells, plus Claude Code integration
- **AI Chat** -- Right sidebar with model selection. Uses your CC subscription or API key

Terminal buttons:
- `+ Local` -- Open a local shell
- `+ Remote` -- SSH to your VPS
- `+ Claude` -- Run Claude Code (uses your CC subscription)
- `+ Claude Remote` -- Run Claude Code on your VPS

### Dashboard Pages

| Page | What It Shows |
|------|---------------|
| **Mission Control** | Project overview, task kanban board |
| **Status** | MCP server health, node status, system metrics |
| **Code** | Web IDE with Monaco editor, terminal, AI chat |
| **Tools** | All 36+ registered tools with schemas |
| **Skills** | 53 skills with descriptions and task types |
| **Agents** | Custom agent management (create, start/stop, templates) |
| **Settings** | API keys, provider config, security settings |

Authentication uses bcrypt password hashing with JWT session tokens.

## Custom Agents (The Babel Fish of Automation)

Create AI agents that run autonomously with specific tools, skills, and schedules.

### Built-in Templates

| Template | Tools | Schedule | Use Case |
|----------|-------|----------|----------|
| **Support** | web, memory, template, knowledge | Always on | Customer support |
| **Marketing** | web_search, content, template, data | Daily 9am | Content and campaigns |
| **DevOps** | shell, docker, git, http | Every 5 min | Monitoring and deployment |
| **Content** | web_search, template, content, outline | Manual | Articles and docs |
| **Research** | web_search, data, memory, summarize | Manual | Investigation and reports |
| **Code Review** | read_file, grep, code_intel, security | Manual | PR reviews and audits |

### Creating an Agent

From the dashboard Agents page, click **"+ Create Agent"** or **"Templates"**:

1. Choose a name and description
2. Select which tools the agent can use
3. Pick skills that inform its behavior
4. Choose a provider (CC subscription, Synthetic, OpenRouter)
5. Select a model (Sonnet 4.6, Opus 4.6, Haiku 4.5)
6. Set a schedule (manual, always-on, or cron expression)

Each agent gets its own memory scope and iteration limits. Agents on the VPS run
autonomously using your chosen API provider.

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
|   |-- memory_tool.py         # Memory store/recall/search/forget/correct
|   |-- context_assembler.py   # Smart context retrieval
|   |-- node_sync.py           # Multi-node memory sync
|   |-- web_search.py          # Web search + fetch
|   '-- ...                    # 25+ more tool modules
|
|-- skills/                    # 57 skills (MCP Prompts)
|   |-- builtins/              # 46 shipped skills
|   |-- workspace/             # 6 project-specific skills
|   '-- loader.py              # Skill discovery and loading
|
|-- memory/                    # Memory subsystem
|   |-- store.py               # MemoryStore (unified interface)
|   |-- embeddings.py          # ONNX embedding engine (25MB, local)
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
|   |   |-- memory-recall.py   # Auto-surfaces relevant memories per prompt
|   |   |-- memory-learn.py    # Captures learnings at session end
|   |   |-- context-loader.py  # Loads relevant reference docs
|   |   '-- security-gate.py   # Flags security-sensitive changes
|   |-- settings.json          # Hook configuration
|   '-- lessons.md             # Accumulated development patterns
|
|-- tests/                     # Test suite
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

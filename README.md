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
  <a href="#apps-platform-the-magrathea-of-applications">Apps</a> |
  <a href="#agent-teams-the-heart-of-gold-crew">Teams</a> |
  <a href="#the-memory-of-a-dolphin-but-better">Memory</a> |
  <a href="#multi-node-the-infinite-improbability-drive">Multi-Node</a> |
  <a href="#roadmap-the-restaurant-at-the-end-of-the-universe">Roadmap</a> |
  <a href="https://github.com/SalesTeamToolbox/agent42">GitHub</a>
</p>

<p align="center">
  <img src="https://img.shields.io/badge/version-3.0-blue" alt="Version">
  <img src="https://img.shields.io/badge/tools-28+-orange" alt="Tools">
  <img src="https://img.shields.io/badge/skills-53-purple" alt="Skills">
  <img src="https://img.shields.io/badge/hooks-16-green" alt="Hooks">
  <img src="https://img.shields.io/badge/nodes-local%20%2B%20remote-teal" alt="Multi-Node">
  <img src="https://img.shields.io/badge/answer-42-yellow" alt="42">
  <img src="https://img.shields.io/badge/license-BSL--1.1-lightgrey" alt="License">
</p>

---

> *"The Guide says there is an art to flying, or rather a knack.
> The knack lies in learning how to throw yourself at the ground and miss."*
> -- The same applies to extending Claude Code.

Agent42 is an **autonomous agent platform** with a web IDE, MCP tools, associative
memory, agent teams, an apps platform, and self-improving learning. Use it as:

- **An MCP server** for Claude Code in VS Code (28+ MCP tools, 53 skills, 16 hooks)
- **A web IDE** with Monaco editor, terminal, and AI chat (accessible from any browser)
- **An agent management platform** that runs custom AI agents and teams 24/7 on your VPS
- **An apps platform** where agents build and operate full applications using Agent42's
  memory, tools, and infrastructure

**Agent42 requires zero API keys for its tools.** All AI reasoning comes from your
Claude Code subscription, Anthropic API key, or alternative providers like
[Synthetic.new](https://synthetic.new) and [OpenRouter](https://openrouter.ai).

## What Is Agent42?

- **Apps platform** -- Build applications inside Agent42. Apps reuse Agent42's memory,
  agents, MCP tools, and monitoring. Support for Python, Node.js, static, and Docker
  runtimes. Auto-restart, health checks, reverse proxy, Git/GitHub integration, and
  automated QA testing with Playwright screenshots and vision analysis.
- **Agent teams** -- Compose multi-agent teams with 8 built-in templates (research,
  marketing, content, design review, strategy, code review, dev, QA). Manager/coordinator
  pattern with structured planning, revision loops, and quality scoring.
- **Web IDE** -- Monaco editor (same engine as VS Code), xterm.js terminal, integrated
  AI chat. Edit code, run commands, and talk to Claude -- all in your browser.
- **MCP tools for Claude Code** -- 28+ MCP tools: git, memory, code intelligence,
  Docker, security analysis, content, and more. Standard MCP protocol.
- **Custom AI agents** -- Create agents with specific tools, skills, and schedules.
  6 built-in templates (Support, Marketing, DevOps, Content, Research, Code Review).
  7 agent profiles with per-profile LLM routing. Each agent picks its own provider and model.
- **Associative memory** -- ONNX embeddings with Qdrant vector search. Memories are
  stored, recalled semantically, and auto-surfaced before Claude even starts thinking.
- **Effectiveness tracking** -- Every tool invocation is tracked for success rate and
  performance. Structured learnings are extracted via LLM, quarantined until validated,
  and proactively injected into future sessions.
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
                    │ 28+ MCP Tools | 53 Skills | Memory│
                    │ 125+ API Routes | 8-Layer Security│
                    │ Agent Teams | Apps | Learning     │
                    ├──────────────┬──────────────────┤
                    │ Local Node   │ Remote Node (VPS)│
                    │ (laptop)     │ (SSH transport)  │
                    └──────────────┴──────────────────┘
```

**Four ways to use Agent42:**

1. **VS Code + Claude Code** -- MCP tools appear alongside built-in tools.
   Claude calls `agent42_shell`, `agent42_memory`, etc. as needed.
2. **Web IDE** -- Open `http://localhost:8000`, navigate to Code. Monaco editor,
   terminal, and AI chat. Run Claude Code directly in the browser terminal.
3. **Custom agents & teams** -- Create agents on the Agents page. They run autonomously
   on your VPS using Synthetic or OpenRouter for overnight work. Compose multi-agent
   teams for complex workflows (research, marketing, code review, strategy).
4. **Apps** -- Build applications that run inside Agent42. Apps share memory,
   agents, and tools with the platform. Managed via dashboard or agent API calls.

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

That's it. Restart Claude Code and Agent42's 28+ MCP tools appear alongside the built-in
ones. You now have a towel.

### Start the Dashboard (Optional)

```bash
python agent42.py
# Dashboard at http://localhost:8000
```

## MCP Tools (The Guide Entries)

All MCP tools are prefixed with `agent42_` in Claude Code. 28 tools registered in the
MCP server across 7 categories. Claude Code also provides its own native tools for
filesystem, shell, grep, and web operations -- Agent42 doesn't duplicate those.

### Memory and Context

| Tool | Description |
|------|-------------|
| `agent42_memory` | Store, recall, search, forget, correct, and strengthen memories |
| `agent42_context` | Context Assembler -- pulls from memory, CLAUDE.md, git history, skills |
| `agent42_knowledge` | Knowledge base management (PDF, docs) |
| `agent42_node_sync` | Sync memory and config between local and remote nodes |
| `agent42_behaviour` | Behaviour configuration and profiles |

### Code Intelligence

| Tool | Description |
|------|-------------|
| `agent42_code_intel` | Code analysis (symbols, references, dependencies) |
| `agent42_repo_map` | Generate repository structure maps |
| `agent42_python_exec` | Execute Python code in sandboxed environment |
| `agent42_run_tests` | Run test suites (pytest, jest, etc.) |
| `agent42_run_linter` | Run linters (ruff, eslint, etc.) |

### Git and Diff

| Tool | Description |
|------|-------------|
| `agent42_git` | Git operations (status, diff, log, branch, commit) |
| `agent42_diff` | Generate and apply diffs |
| `agent42_create_pr` | Generate pull requests with context |

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
| `agent42_browser` | Browser automation via Playwright |
| `agent42_file_watcher` | Watch files/directories for changes |
| `agent42_vision` | Image analysis and screenshot comparison |

### Content and Data

| Tool | Description |
|------|-------------|
| `agent42_content_analyzer` | Analyze content quality and structure |
| `agent42_data` | Data transformation and analysis |
| `agent42_template` | Template rendering and scaffolding |
| `agent42_outline` | Generate structured outlines |
| `agent42_scoring` | Score and rank items by criteria |
| `agent42_summarize` | Summarize text and documents |

### Orchestration

| Tool | Description |
|------|-------------|
| `agent42_workflow` | Multi-step workflow orchestration |
| `agent42_persona` | Persona management for agent behavior |

### Claude Code Native Tools (Not Registered)

These capabilities are provided natively by Claude Code itself, so Agent42 does not
register them in the MCP server (they'd be redundant):

- **Filesystem:** read, write, edit, list directory (CC's Read, Write, Edit, LS)
- **Shell:** command execution (CC's Bash tool applies its own safety layer)
- **Search:** regex search across files (CC's Grep tool)
- **Web:** web search, page fetch, HTTP requests (CC's WebSearch, WebFetch)

### Dashboard-Only Tools (Not in MCP)

These tools require the full Agent42 dashboard (`python agent42.py`) and are not
available through the MCP server:

| Tool | Description |
|------|-------------|
| `app` | Full app lifecycle: create, scaffold, start/stop, logs, health, git, GitHub, API calls |
| `app_test` | Automated QA: smoke tests, visual checks (Playwright + vision LLM), log analysis, browser flows |
| `team` | Multi-agent team composition and orchestration (8 built-in templates) |
| `subagent` | Delegate background work to isolated agents with restricted toolsets |
| `cron` | Schedule recurring jobs (cron expressions, intervals, one-time, planned sequences) |
| `ssh` | SSH operations on remote servers |
| `tunnel` | Port forwarding and tunneling |
| `notify` | Send notifications (Slack, email, etc.) |
| `image_gen` | AI image generation |
| `video_gen` | AI video generation |
| `project_interview` | Interactive project discovery and planning |
| `dynamic` | Runtime tool creation (meta-tool) |
| `mcp_tool_proxy` | Bridge to external MCP servers |

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

Agent42 exposes 53 skills as MCP Prompts (47 builtin + 6 workspace). Skills are
structured instruction sets that Claude Code can request and apply. They cover:

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
| [**Synthetic**](https://synthetic.new/?referral=Oc15m9cIhEFmXF9) | Privacy-focused platform running open-source models (GLM-4.7, Kimi K2, Qwen 3) in private datacenters. Never trains on your data or stores prompts. OpenAI-compatible API. | $30/mo subscription or pay-per-use |
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
| **Tools** | All 28+ registered MCP tools with schemas |
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

### Agent Profiles

Agents can be assigned behavior profiles that shape their system prompt, preferred
skills, and task focus. 7 built-in profiles:

| Profile | Focus |
|---------|-------|
| **developer** | Software engineering, code quality, testing |
| **l2-reviewer** | Premium code review (security, subtle bugs, performance) |
| **l2-strategist** | Strategic analysis and recommendations |
| **researcher** | Data gathering, investigation, and synthesis |
| **data-analyst** | Statistical and data-driven insights |
| **writer** | Content creation and documentation |
| **security-auditor** | Vulnerability scanning and threat analysis |

Each profile has per-profile LLM routing -- the agent picks the best model for its
task category (fast, general, reasoning, coding, content, research, marketing, analysis).

### Provider-Aware Model Selection

Agents select models based on their provider and task category:

| Provider | Fast | Coding | Research | Reasoning |
|----------|------|--------|----------|-----------|
| **Anthropic** | Haiku 4.5 | Sonnet 4.6 | Sonnet 4.6 | Opus 4.6 |
| **Synthetic** | GLM-4.7-Flash | Qwen3-Coder-480B | Kimi-K2.5 | Kimi-K2-Thinking |
| **OpenRouter** | Gemini 2.0 Flash | Sonnet 4.6 | Sonnet 4.6 | Opus 4.6 |

### Scheduling

- **Manual** -- triggered from dashboard or API
- **Always-on** -- runs continuously, restarts on completion
- **Cron** -- standard cron expressions (`0 9 * * *` for 9am daily)
- **Interval** -- `every 5m`, `every 1h`
- **Auto-stagger** -- multiple agents scheduled at the same time are spread over 60s
- **Dependencies** -- planned sequences with `depends_on` for multi-step workflows

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

## Agent Teams (The Heart of Gold Crew)

Agent teams compose multiple agents into coordinated workflows. A **manager** plans
the work, delegates to specialized roles, reviews outputs, and requests revisions.

### Built-in Teams

| Team | Workflow | Roles | Use Case |
|------|----------|-------|----------|
| **research-team** | Sequential | researcher, analyst, writer | Research briefs and reports |
| **marketing-team** | Pipeline | researcher, strategist, copywriter, editor | Campaign content |
| **content-team** | Sequential | writer, editor, seo-optimizer | Content with SEO |
| **design-review** | Sequential | designer, critic, brand-reviewer | Design QA and brand |
| **strategy-team** | Fan-out-fan-in | [market + competitive researcher], strategist, presenter | Strategic analysis |
| **code-review-team** | Sequential | developer, reviewer, tester | Code implementation + QA |
| **dev-team** | Fan-out-fan-in | architect, [backend + frontend dev], integrator | Full-stack development |
| **qa-team** | Sequential | analyzer, test-writer, security-auditor | QA and security |

### Workflow Types

- **Sequential** -- roles run in order, each receiving all prior outputs
- **Parallel** -- all roles run simultaneously, results aggregated at end
- **Fan-out-fan-in** -- parallel groups feed into sequential merge roles
- **Pipeline** -- sequential with internal critic iteration per role

### Manager Pattern

Every team run is wrapped by a manager that:

1. **Plans before execution** -- creates structured task breakdown with goals,
   success criteria, required artifacts, and per-role instructions
2. **Reviews after execution** -- checks completeness, consistency, quality.
   Assigns a quality score (1-10)
3. **Requests revisions** -- flags specific roles for re-execution with feedback
   (max 1 revision per role to prevent infinite loops)

All roles share a `TeamContext` -- the manager's plan plus all prior role outputs.
No role works in isolation.

### Using Teams

```bash
# Via dashboard API
POST /api/agents  # with team template

# Teams available: research-team, marketing-team, content-team,
# design-review, strategy-team, code-review-team, dev-team, qa-team
```

Custom teams can be composed with `team.compose()`, cloned from built-in templates,
or created via the dashboard.

## Apps Platform (The Magrathea of Applications)

Agent42 can host and manage full applications. Apps run as supervised processes inside
the platform, sharing Agent42's memory, agents, tools, and monitoring infrastructure.

### Why Build Apps Inside Agent42?

Your app isn't starting from scratch. It inherits:

- **Memory** -- Qdrant semantic search, session history, and learning system
- **Agent teams** -- 8 agent teams that can operate your app autonomously
- **MCP tools** -- 28+ tools for git, security, code intel, Docker, and more
- **Monitoring** -- health checks every 15s, auto-restart on crash, log aggregation
- **Dashboard** -- manage, monitor, and configure from the web UI
- **Security** -- sandbox isolation, sanitized environment (no API key leakage)

### Supported Runtimes

| Runtime | Framework Examples | Entry Point |
|---------|-------------------|-------------|
| **Python** | Flask, FastAPI, Streamlit | `src/app.py` |
| **Node.js** | Express, Next.js, Vite | `src/index.js` |
| **Static** | HTML/CSS/JS, Tailwind, Alpine.js | `public/index.html` |
| **Docker** | Any containerized app | `docker-compose.yml` |

Each app gets:

- Unique ID and slug (URL-safe name)
- Dedicated port (9100-9199 range, auto-allocated)
- Per-app virtual environment (Python) or node_modules (Node.js)
- Optional Git repository with GitHub integration
- Reverse proxy through Agent42 (`/apps/{slug}/`)

### App Lifecycle

```
create → install_deps → mark_ready → start ⇄ stop
                                       ↓
                              (crash) → auto-restart
                                       ↓
                                    archived
```

### App Management

From the dashboard or via tool calls:

- **Create** -- scaffold a new app with manifest and directory structure
- **Install deps** -- pip/npm install with per-app isolation
- **Start/Stop/Restart** -- managed process with graceful shutdown
- **Logs** -- tail stdout/stderr with error pattern detection
- **Health** -- HTTP health checks with response time tracking
- **Git** -- init, commit, status, log, push to GitHub
- **Test** -- automated QA with smoke tests, visual checks (Playwright screenshots
  analyzed by vision LLM), log analysis, and multi-step browser flows
- **API calls** -- agents can invoke running app endpoints directly (GET/POST/PUT/DELETE)

### Agent-to-App Interaction

Agents can directly call your app's HTTP API:

```
agent42_app(action="app_api", app_id="mhg123", endpoint="/api/catalog", method="GET")
```

This enables autonomous workflows -- an agent team can build an app, start it,
test it, fix issues, and operate it in production, all without human intervention.

### Case Study: MeatheadGear

MeatheadGear is an autonomous AI-run gym apparel storefront built as an Agent42 app.
It demonstrates the full platform capability:

- **8 autonomous agents** (Owner, Marketing, Sales, Support, Research, Design,
  Web/Brand, Analytics) running 24/7 on the VPS
- **Agent42 memory** for customer preferences, design history, and sales data
- **Print-on-demand** via Printful API integration
- **AI design generation** with exclusivity tiers (Print It, Lock It, Own It, Sell It)
- **Stripe payments** with wallet system and creator revenue sharing
- **Fuzzy prompt blocking** using ONNX embeddings (same engine as Agent42's memory)
  to protect exclusive designs from copycats

The app reuses Agent42's infrastructure -- it doesn't rebuild memory, auth, monitoring,
or agent management. It just plugs in.

## Effectiveness and Learning (The Deep Thought of Self-Improvement)

Agent42 tracks what works and gets smarter over time.

### How It Works

```
Tool invocation → Record success/duration → Aggregate stats by task type
                                                     ↓
Session ends → Extract structured learnings via LLM → Quarantine (low confidence)
                                                     ↓
Observation count > threshold → Promote to full confidence → Auto-inject in future sessions
```

### Effectiveness Tracking

Every tool invocation is recorded with success/failure status and duration. Stats
are aggregated by tool name and task type, revealing which tools perform best for
which kinds of work.

### Learning Quarantine

New learnings extracted by LLM enter quarantine at low confidence (0.6). Each time
the same pattern is observed again, confidence increases. Once the observation count
exceeds the evidence threshold, the learning is promoted to full confidence and
begins appearing in proactive injection.

This prevents one-off flukes from polluting the knowledge base.

### Proactive Injection

The `proactive-inject.py` hook fires on every prompt. It:

1. Infers the task type from prompt keywords (no LLM call -- instant)
2. Fetches top-3 learnings with score >= 0.80 from the effectiveness store
3. Injects them into Claude's context before it starts thinking
4. Guards against re-injection (once per session)

The `effectiveness-learn.py` and `knowledge-learn.py` hooks fire at session end
to extract new learnings and upsert them to Qdrant for future recall.

### Recommendations Engine

Based on accumulated effectiveness data, Agent42 recommends the top-3 tools and
skills by success rate (minimum 5 observations) for each task type. These surface
via the `/api/recommendations/retrieve` endpoint and the proactive injection hook.

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

## Claude Code Hooks (The Sub-Etha Sense-O-Matic)

Agent42 ships 16 hooks in `.claude/hooks/` that run automatically during Claude Code
sessions. They form the nervous system -- memory recall, security enforcement, code
formatting, learning, and session continuity happen without you lifting a finger.

| Hook | Trigger | What It Does |
|------|---------|--------------|
| `context-loader.py` | UserPromptSubmit | Loads relevant lessons and reference docs based on work type |
| `memory-recall.py` | UserPromptSubmit | Surfaces relevant memories from Qdrant before Claude thinks |
| `proactive-inject.py` | UserPromptSubmit | Surfaces past learnings relevant to the detected task type |
| `security-gate.py` | PreToolUse | Blocks edits to security-sensitive files (requires approval) |
| `security-monitor.py` | PostToolUse (Write/Edit) | Flags security-sensitive changes for review |
| `format-on-write.py` | PostToolUse (Write/Edit) | Auto-formats Python files with ruff on every write |
| `cc-memory-sync.py` | PostToolUse (Write/Edit) | Embeds CC memory files into Qdrant for semantic recall |
| `jcodemunch-reindex.py` | Stop + PostToolUse | Re-indexes codebase after structural file changes |
| `jcodemunch-token-tracker.py` | PostToolUse | Tracks token savings from jcodemunch vs full file reads |
| `session-handoff.py` | Stop | Captures session state for auto-resume continuity |
| `test-validator.py` | Stop | Validates tests pass, checks test coverage for new modules |
| `learning-engine.py` | Stop | Records development patterns and vocabulary |
| `memory-learn.py` | Stop | Captures new learnings into memory system for future recall |
| `effectiveness-learn.py` | Stop | Extracts structured learnings with LLM for quarantine review |
| `knowledge-learn.py` | Stop | Extracts session knowledge and upserts to Qdrant |
| `credential-sync.py` | SessionStart | Syncs CC credentials to remote VPS on session start |

Supporting files (not hooks themselves): `security_config.py` (shared config),
`cc-memory-sync-worker.py` and `knowledge-learn-worker.py` (background workers).

## Project Structure (The Total Perspective Vortex)

```
agent42/
|-- mcp_server.py              # MCP server entry point (stdio transport)
|-- mcp_registry.py            # MCP <-> ToolRegistry adapter
|-- agent42.py                 # Dashboard + services launcher
|-- commands.py                # CLI command handlers
|
|-- tools/                     # 28+ MCP tools
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
|-- skills/                    # 53 skills (MCP Prompts)
|   |-- builtins/              # 47 shipped skills
|   |-- workspace/             # 6 project-specific skills
|   '-- loader.py              # Skill discovery and loading
|
|-- memory/                    # Memory subsystem
|   |-- store.py               # MemoryStore (unified interface)
|   |-- embeddings.py          # ONNX embedding engine (25MB, local)
|   |-- qdrant_store.py        # Qdrant vector backend
|   '-- search_service.py      # Search service layer
|
|-- agents/                    # Agent subsystem
|   |-- profile_loader.py      # Agent profiles (7 built-in)
|   '-- agent_routing_store.py # Per-profile LLM routing overrides
|
|-- core/                      # Infrastructure
|   |-- config.py              # Settings (frozen dataclass from env)
|   |-- sandbox.py             # Workspace sandbox (path security)
|   |-- command_filter.py      # 6-layer shell command filter
|   |-- rate_limiter.py        # Per-tool rate limiting
|   |-- approval_gate.py       # Human approval for protected ops
|   |-- agent_manager.py       # Agent CRUD, templates, scheduling
|   |-- agent_runtime.py       # Agent process lifecycle (spawn/stop/monitor)
|   '-- app_manager.py         # App lifecycle (start/stop/health/restart)
|
|-- dashboard/                 # FastAPI web UI
|   |-- server.py              # 125+ REST API routes + 3 WebSocket endpoints
|   |-- auth.py                # JWT + bcrypt authentication
|   '-- frontend/              # Static frontend assets
|
|-- apps/                      # User-created applications
|   '-- (your apps here)       # Each app: APP.json + src/ + public/
|
|-- .claude/                   # Claude Code integration
|   |-- hooks/                 # 16 hooks: memory, security, formatting, learning
|   |   |-- memory-recall.py   # Auto-surfaces relevant memories per prompt
|   |   |-- memory-learn.py    # Captures learnings at session end
|   |   |-- proactive-inject.py # Surfaces past learnings for detected task type
|   |   |-- context-loader.py  # Loads relevant reference docs
|   |   |-- security-gate.py   # PreToolUse: blocks edits to security files
|   |   |-- security-monitor.py # PostToolUse: flags security-sensitive changes
|   |   |-- format-on-write.py # Auto-formats Python files on write
|   |   |-- cc-memory-sync.py  # Embeds CC memory files into Qdrant
|   |   |-- session-handoff.py # Captures session state for continuity
|   |   |-- learning-engine.py # Records development patterns
|   |   |-- test-validator.py  # Validates tests pass on stop
|   |   |-- effectiveness-learn.py     # Structured learning extraction
|   |   |-- knowledge-learn.py         # Session knowledge to Qdrant
|   |   |-- credential-sync.py         # Syncs CC credentials to VPS
|   |   |-- jcodemunch-reindex.py      # Re-indexes after structural changes
|   |   '-- jcodemunch-token-tracker.py # Tracks token savings
|   |-- settings.json          # Hook configuration
|   '-- lessons.md             # Accumulated development patterns
|
|-- tests/                     # Test suite
|-- deploy/                    # systemd units, nginx config
|-- docker-compose.yml         # Docker deployment
'-- requirements.txt           # Python dependencies
```

## Roadmap (The Restaurant at the End of the Universe)

Agent42 is under active development. Here's what's shipping next.

### Performance-Based Agent Rewards (In Progress)

Agents that consistently deliver value get better tools. A self-reinforcing quality loop.

```
Agent completes task → Record success/duration → Composite score
                                                      ↓
                                              Bronze / Silver / Gold tier
                                                      ↓
                                              Tier determines:
                                              - Model class (Haiku → Sonnet → Opus)
                                              - Rate limit multiplier
                                              - Concurrent task capacity
```

**4-phase rollout:**

| Phase | What Ships |
|-------|-----------|
| **1. Foundation** | Composite scoring (success rate + volume + speed), tier schema, config, restart recovery |
| **2. Tier Assignment** | Automatic Bronze/Silver/Gold, Provisional tier for new agents, admin overrides |
| **3. Resource Enforcement** | Tier-aware model routing, rate limits, concurrent task capacity |
| **4. Dashboard** | Tier badges, metrics panel, admin override with expiry, real-time WebSocket events |

New agents start in **Provisional** tier. Background recalculation every 15 minutes.
Admin overrides are respected (never auto-downgraded). Disabled by default
(`REWARDS_ENABLED=false`) -- zero impact on existing deployments until you opt in.

### IoT and Edge Node Expansion

The multi-node architecture already supports remote nodes over SSH. The next evolution
extends this to IoT and edge devices:

- **Device Gateway** -- API key-based authentication for edge devices (already built:
  `/api/devices/register`, `/api/devices/{id}/revoke`)
- **Device online tracking** -- real-time presence via WebSocket heartbeat
- **Capabilities-based profiles** -- devices declare what they can do (sensor data,
  local compute, actuator control)
- **Memory sync** -- edge devices contribute observations to the central Qdrant store
- **Lightweight agent runtime** -- run constrained agents on Raspberry Pi / ESP32
  class devices with the fast-tier model (Haiku 4.5, GLM-4.7-Flash)

The device gateway endpoints are already live in the dashboard API. The next milestone
connects them to agent scheduling and memory sync.

### Autonomous App Operations

Building on the Apps Platform and Agent Teams:

- **Agent-operated storefronts** -- teams of agents running e-commerce, content sites,
  and SaaS products autonomously (MeatheadGear is the first proof-of-concept)
- **Self-healing apps** -- agents detect failures via health checks, diagnose via logs,
  fix code, commit, and restart -- all without human intervention
- **Revenue-aware agents** -- agents with access to payment data (Stripe) can optimize
  pricing, run A/B tests, and reallocate marketing spend based on results

### Shipped Milestones

| Version | What Shipped |
|---------|-------------|
| **v1.0** | Free LLM Provider Expansion (9 providers, tiered routing, 1,956 tests) |
| **v1.2** | Claude Code Automation (MCP servers, security gate, 5 skills, 4 subagents) |
| **v1.4** | Per-Project Task Memories (task lifecycle, effectiveness tracking, proactive injection) |
| **v1.5** | Intelligent Memory Bridge (CC-to-Qdrant auto-sync, learning extraction, CLAUDE.md integration) |
| **v1.6** | UX & Workflow Automation (memory observability, GSD auto-activation, PWA, dashboard GSD state) |

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

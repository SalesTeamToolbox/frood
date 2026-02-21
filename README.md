# Agent42

**The answer to life, the universe, and all your tasks.**

A multi-agent orchestrator platform. Free models handle the iterative work;
Claude Code (or human review) gates the final output before anything ships.

Not just for coding — Agent42 handles marketing, email, research, documentation,
and any task you throw at it.

## Architecture

```
Inbound Channel  ->  Task Queue  ->  Agent Loop  ->  Critic Pass  ->  REVIEW.md  ->  You + Claude Code  ->  Ship
(Slack/Discord/     (priority +      (free LLMs     (independent     (diff, logs,    (human approval
 Telegram/Email/     concurrency)     via OpenRouter) second opinion)  critic notes)   gate)
 Dashboard/CLI)
```

**Free-first strategy** — all agent work defaults to $0 models via OpenRouter:

- **Coding**: Qwen3 Coder 480B (primary) + Devstral 123B (critic)
- **Debugging**: DeepSeek R1 0528 (primary) + Devstral 123B (critic)
- **Research**: Llama 4 Maverick (primary) + DeepSeek Chat v3.1 (critic)
- **Review gate**: Human + Claude Code final review before anything ships
- **Zero API cost**: One free OpenRouter API key unlocks 30+ models

Premium models (GPT-4o, Claude Sonnet, Gemini Pro) available for admin-configured
task types — see [Model Routing](#model-routing).

## Quick Start

```bash
git clone <this-repo> agent42
cd agent42
bash setup.sh
# Edit .env — set at minimum OPENROUTER_API_KEY and DASHBOARD_PASSWORD
source .venv/bin/activate
python agent42.py --repo /path/to/your/project
```

Open `http://localhost:8000` in your browser.

### Minimum Setup (free, no credit card)

1. Create an [OpenRouter account](https://openrouter.ai) (free, no credit card)
2. Generate an API key at the OpenRouter dashboard
3. Set `OPENROUTER_API_KEY` in `.env`

That's it — you now have access to 30+ free models for all task types.

### Optional: Additional Providers

For direct provider access or premium models, add any of these API keys:

| Provider | API Key Env Var | Free Tier? |
|---|---|---|
| [OpenRouter](https://openrouter.ai) | `OPENROUTER_API_KEY` | Yes — 30+ free models |
| [NVIDIA Build](https://build.nvidia.com) | `NVIDIA_API_KEY` | Yes — free tier |
| [Groq](https://console.groq.com) | `GROQ_API_KEY` | Yes — free tier |
| [OpenAI](https://platform.openai.com) | `OPENAI_API_KEY` | No |
| [Anthropic](https://console.anthropic.com) | `ANTHROPIC_API_KEY` | No |
| [DeepSeek](https://platform.deepseek.com) | `DEEPSEEK_API_KEY` | No |
| [Google Gemini](https://aistudio.google.dev) | `GEMINI_API_KEY` | No |

## Requirements

- Python 3.11+
- Node.js 18+ (for frontend build)
- git with a repo that has a `dev` branch
- [OpenRouter account](https://openrouter.ai) (free, no credit card required)

## Configuration

All config lives in `.env`. See `.env.example` for all options.

### Core Settings

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | OpenRouter API key (primary, free) |
| `MAX_CONCURRENT_AGENTS` | `3` | Max parallel agents (2-3 for 6GB VPS) |
| `DEFAULT_REPO_PATH` | `.` | Git repo for worktrees |
| `DASHBOARD_USERNAME` | `admin` | Dashboard login |
| `DASHBOARD_PASSWORD` | `changeme` | Dashboard password |
| `SANDBOX_ENABLED` | `true` | Restrict agent file operations to workspace |

### Channels

| Variable | Description |
|---|---|
| `DISCORD_BOT_TOKEN` | Discord bot token |
| `SLACK_BOT_TOKEN` / `SLACK_APP_TOKEN` | Slack bot tokens (Socket Mode) |
| `TELEGRAM_BOT_TOKEN` | Telegram bot token |
| `EMAIL_IMAP_*` / `EMAIL_SMTP_*` | Email IMAP/SMTP credentials |

### Memory & Embeddings

| Variable | Default | Description |
|---|---|---|
| `MEMORY_DIR` | `.agent42/memory` | Persistent memory storage |
| `SESSIONS_DIR` | `.agent42/sessions` | Session history |
| `EMBEDDING_MODEL` | auto-detected | Override embedding model |
| `EMBEDDING_PROVIDER` | auto-detected | `openai`, `openrouter`, or `nvidia` |

### Tools

| Variable | Description |
|---|---|
| `BRAVE_API_KEY` | Brave Search API key (for web search tool) |
| `MCP_SERVERS_JSON` | Path to MCP servers config (JSON) |
| `CRON_JOBS_PATH` | Path to persistent cron jobs file |

## Usage

### Via Dashboard
Open `http://localhost:8000`, log in, fill out the task form.

### Via Channels
Send a message to Agent42 through any connected channel (Slack, Discord,
Telegram, email). The agent picks up tasks automatically with per-channel
user allowlists.

### Via tasks.json
Drop tasks into `tasks.json` (see `tasks.json.example`). The orchestrator polls
for changes every 30 seconds, or restart to load immediately.

### Via CLI
```bash
python agent42.py --repo /path/to/project --port 8000 --max-agents 2
```

## Model Routing

### Default (Free) Routing — OpenRouter

One API key, zero cost. These models are used by default for all task types:

| Task Type | Primary Model | Critic Model | Max Iterations |
|---|---|---|---|
| coding | Qwen3 Coder 480B | Devstral 123B | 8 |
| debugging | DeepSeek R1 0528 | Devstral 123B | 10 |
| research | Llama 4 Maverick | DeepSeek Chat v3.1 | 5 |
| refactoring | Qwen3 Coder 480B | Devstral 123B | 8 |
| documentation | Llama 4 Maverick | Gemma 3 27B | 4 |
| marketing | Llama 4 Maverick | DeepSeek Chat v3.1 | 6 |
| email | Mistral Small 3.1 | — | 3 |

### Legacy Routing — NVIDIA / Groq Direct

If you have NVIDIA or Groq API keys but no OpenRouter key, the router falls
back to direct provider access:

| Task Type | Primary | Critic |
|---|---|---|
| coding | Qwen 2.5 Coder 32B | DeepSeek R1 |
| debugging | DeepSeek R1 | Qwen 2.5 Coder 32B |
| research | Llama 3.1 405B | Mistral Large 2 |

### Admin Overrides

Override any model per task type with environment variables:

```bash
AGENT42_CODING_MODEL=claude-sonnet        # Use Claude Sonnet for coding
AGENT42_CODING_CRITIC=gpt-4o              # Use GPT-4o as critic
AGENT42_CODING_MAX_ITER=5                 # Limit to 5 iterations
```

Pattern: `AGENT42_{TASK_TYPE}_MODEL`, `AGENT42_{TASK_TYPE}_CRITIC`, `AGENT42_{TASK_TYPE}_MAX_ITER`

### Available Free Models (OpenRouter)

All accessible with a single free OpenRouter API key:

| Model | ID | Best For |
|---|---|---|
| Qwen3 Coder 480B | `qwen/qwen3-coder:free` | Coding, agentic tool use |
| Devstral 123B | `mistralai/devstral-2512:free` | Multi-file coding, refactoring |
| DeepSeek R1 0528 | `deepseek/deepseek-r1-0528:free` | Reasoning, debugging, math |
| DeepSeek Chat v3.1 | `deepseek/deepseek-chat-v3.1:free` | General chat, hybrid reasoning |
| Llama 4 Maverick | `meta-llama/llama-4-maverick:free` | Research, writing, general |
| Llama 3.3 70B | `meta-llama/llama-3.3-70b-instruct:free` | General purpose |
| Gemini 2.5 Pro | `google/gemini-2.5-pro-exp-03-25:free` | Complex tasks |
| Gemini 2.0 Flash | `google/gemini-2.0-flash-exp:free` | Long context (1M tokens) |
| Mistral Small 3.1 | `mistralai/mistral-small-3.1-24b-instruct:free` | Fast, lightweight tasks |
| Gemma 3 27B | `google/gemma-3-27b-it:free` | Fast verification |
| Nemotron 30B | `nvidia/nemotron-3-nano-30b-a3b:free` | General purpose |

## Skills

Skills are markdown prompt templates that give agents specialized capabilities.
They live in `skills/builtins/` and can be extended per-repo in a `skills/` directory.

Built-in skills:
- **github** — PR creation, issue triage, code review
- **memory** — Read/update persistent agent memory
- **skill-creator** — Generate new skills from descriptions
- **weather** — Weather lookups (example skill)

Skills are matched to tasks by `task_types` frontmatter and injected into the
agent's system prompt automatically.

## Tools

Agents have access to a sandboxed tool registry:

| Tool | Description |
|---|---|
| `shell` | Sandboxed command execution (with command filter) |
| `read_file` / `write_file` / `edit_file` | Filesystem operations (workspace-restricted) |
| `list_dir` | Directory listing |
| `web_search` | Brave Search API integration |
| `subagent` | Spawn focused sub-agents for parallel work |
| `cron` | Schedule recurring tasks |
| `mcp_*` | MCP server tool proxying |

### Command Filter

The shell tool blocks dangerous commands by default:
- `rm -rf /`, `dd if=`, `mkfs`, `shutdown`, `reboot`
- `curl | sh`, `wget | bash` (pipe-to-shell)
- `iptables -F` (firewall flush)

Admins can add extra deny patterns or switch to allowlist mode.

## Memory

Agent42 maintains persistent memory across sessions:

- **Structured memory** — key/value sections in `memory.md` (project context, preferences, learned patterns)
- **Event log** — append-only `history.md` for audit trail
- **Session history** — per-conversation message history with configurable limits
- **Semantic search** — vector embeddings for similarity-based memory retrieval (auto-detects OpenAI, OpenRouter, or NVIDIA embedding APIs; falls back to grep)

## Channels

Multi-channel inbound/outbound messaging:

| Channel | Inbound | Outbound | Auth |
|---|---|---|---|
| Dashboard | Task form | WebSocket + REST | JWT |
| Slack | Socket Mode events | `chat.postMessage` | Bot token + allowlist |
| Discord | Message events | Channel messages | Bot token + guild IDs |
| Telegram | Long-polling updates | `sendMessage` | Bot token + allowlist |
| Email | IMAP polling | SMTP send | IMAP/SMTP credentials |

Each channel supports user allowlists to restrict who can submit tasks.

## Review Gate

When a task completes, the dashboard shows a **READY** badge.
The agent commits a `REVIEW.md` to the worktree containing:
- Full iteration history
- Lint/test results from every cycle
- Independent critic notes
- Complete `git diff dev` embedded
- A pre-written Claude Code review prompt

```bash
cd /tmp/agent42/<task-id>
claude  # Opens Claude Code with full context in REVIEW.md
```

## Approval Gates

These operations pause the agent and show an approval modal in the dashboard:
- `gmail_send` — sending email
- `git_push` — pushing code
- `file_delete` — deleting files
- `external_api` — calling external services

## Project Structure

```
agent42/
├── agent42.py                 # Main entry point
├── core/
│   ├── config.py              # Centralized settings from .env
│   ├── task_queue.py          # Task state machine + JSON persistence
│   ├── worktree_manager.py    # Git worktree lifecycle
│   ├── approval_gate.py       # Protected operation intercept
│   ├── command_filter.py      # Shell command safety filter
│   └── sandbox.py             # Workspace path restriction
├── agents/
│   ├── agent.py               # Per-task agent orchestration
│   ├── model_router.py        # Free-first task-type -> model routing
│   └── iteration_engine.py    # Primary -> Critic -> Revise loop
├── providers/
│   └── registry.py            # Declarative LLM provider + model catalog
├── channels/
│   ├── base.py                # Channel base class + message types
│   ├── manager.py             # Multi-channel routing
│   ├── slack_channel.py       # Slack Socket Mode
│   ├── discord_channel.py     # Discord bot
│   ├── telegram_channel.py    # Telegram long-polling
│   └── email_channel.py       # IMAP/SMTP
├── tools/
│   ├── base.py                # Tool base class + result types
│   ├── registry.py            # Tool registration + dispatch
│   ├── shell.py               # Sandboxed shell execution
│   ├── filesystem.py          # read/write/edit/list operations
│   ├── web_search.py          # Brave Search integration
│   ├── subagent.py            # Sub-agent spawning
│   ├── cron.py                # Scheduled task execution
│   └── mcp_client.py          # MCP server tool proxying
├── skills/
│   ├── loader.py              # Skill discovery + frontmatter parser
│   └── builtins/              # Built-in skill templates
│       ├── github/SKILL.md
│       ├── memory/SKILL.md
│       ├── skill-creator/SKILL.md
│       └── weather/SKILL.md
├── memory/
│   ├── store.py               # Structured memory + event log
│   ├── session.py             # Per-conversation session history
│   └── embeddings.py          # Vector store + semantic search
├── dashboard/
│   ├── server.py              # FastAPI + WebSocket server
│   ├── auth.py                # JWT authentication
│   └── websocket_manager.py   # Real-time broadcast
├── tests/                     # 107 tests across 7 test files
├── .env.example               # All configuration options
├── requirements.txt
├── tasks.json.example
└── setup.sh
```

## Running as a Service

```bash
sudo cp /tmp/agent42.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable agent42
sudo systemctl start agent42
sudo journalctl -u agent42 -f
```

## Security

- **Workspace sandbox**: Agents can only read/write within the project worktree
- **Command filter**: Dangerous shell commands are blocked by default
- **Approval gates**: Sensitive operations (email, push, delete) require dashboard approval
- **Channel allowlists**: Restrict which users can submit tasks per channel
- **Dashboard auth**: JWT-based authentication with bcrypt password hashing
- Put nginx in front with HTTPS before making public
- `JWT_SECRET` should be a 64-char random string

# Agent42

**The answer to life, the universe, and all your tasks.**

A multi-agent orchestrator platform. Free models handle the iterative work;
Claude Code (or human review) gates the final output before anything ships.

Not just for coding — Agent42 handles marketing, design, content creation,
strategy, data analysis, project management, media generation, and any task
you throw at it. Spin up teams of agents to collaborate, critique, and iterate.

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
- **Marketing/Content/Design**: Llama 4 Maverick + task-aware critics
- **Image/Video**: FLUX (free), DALL-E 3, Replicate, Luma (premium)
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

### Optional: Enhanced Memory (Qdrant + Redis)

For persistent cross-session memory, fast semantic search, and session caching:

```bash
# Install client libraries
pip install qdrant-client redis[hiredis]

# Start services (Docker)
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 6379:6379 redis:alpine

# Add to .env
QDRANT_URL=http://localhost:6333
REDIS_URL=redis://localhost:6379/0
```

Or use embedded Qdrant (no Docker needed): set `QDRANT_ENABLED=true` in `.env`.

Agent42 works fully without these — they're optional enhancements. See [Qdrant](#qdrant-vector-database-optional) and [Redis](#redis-optional) for details.

### Optional: Additional Providers

For direct provider access or premium models, add any of these API keys:

| Provider | API Key Env Var | Free Tier? | Capabilities |
|---|---|---|---|
| [OpenRouter](https://openrouter.ai) | `OPENROUTER_API_KEY` | Yes — 30+ free models | Text + Images |
| [OpenAI](https://platform.openai.com) | `OPENAI_API_KEY` | No | Text + DALL-E |
| [Anthropic](https://console.anthropic.com) | `ANTHROPIC_API_KEY` | No | Text |
| [DeepSeek](https://platform.deepseek.com) | `DEEPSEEK_API_KEY` | No | Text |
| [Google Gemini](https://aistudio.google.dev) | `GEMINI_API_KEY` | No | Text |
| [Replicate](https://replicate.com) | `REPLICATE_API_TOKEN` | No | Images + Video |
| [Luma AI](https://lumalabs.ai) | `LUMA_API_KEY` | No | Video |

## Requirements

- Python 3.11+
- Node.js 18+ (for frontend build)
- git with a repo that has a `dev` branch
- [OpenRouter account](https://openrouter.ai) (free, no credit card required)

**Optional (for enhanced memory):**
- `pip install qdrant-client` — Qdrant vector DB for semantic search
- `pip install redis[hiredis]` — Redis for session caching + embedding cache

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
| `EMBEDDING_PROVIDER` | auto-detected | `openai` or `openrouter` |

### Qdrant Vector Database (optional)

Enables HNSW-indexed semantic search, cross-session conversation recall, and scalable long-term memory. Falls back to JSON vector store when not configured.

| Variable | Default | Description |
|---|---|---|
| `QDRANT_URL` | — | Qdrant server URL (e.g. `http://localhost:6333`) |
| `QDRANT_ENABLED` | `false` | Enable embedded mode (no server needed) |
| `QDRANT_LOCAL_PATH` | `.agent42/qdrant` | Storage path for embedded mode |
| `QDRANT_API_KEY` | — | API key for Qdrant Cloud |
| `QDRANT_COLLECTION_PREFIX` | `agent42` | Prefix for collection names |

```bash
# Docker quickstart:
docker run -p 6333:6333 qdrant/qdrant
pip install qdrant-client
```

### Redis (optional)

Enables fast session caching with TTL expiry, embedding API response caching, and cross-instance session sharing. Falls back to JSONL files when not configured.

| Variable | Default | Description |
|---|---|---|
| `REDIS_URL` | — | Redis URL (e.g. `redis://localhost:6379/0`) |
| `REDIS_PASSWORD` | — | Redis password |
| `SESSION_TTL_DAYS` | `7` | Auto-expire old sessions |
| `EMBEDDING_CACHE_TTL_HOURS` | `24` | Cache embedding API responses |

```bash
# Docker quickstart:
docker run -p 6379:6379 redis:alpine
pip install redis[hiredis]
```

### Tools

| Variable | Description |
|---|---|
| `BRAVE_API_KEY` | Brave Search API key (for web search tool) |
| `MCP_SERVERS_JSON` | Path to MCP servers config (JSON) |
| `CRON_JOBS_PATH` | Path to persistent cron jobs file |
| `REPLICATE_API_TOKEN` | Replicate API token (for image/video generation) |
| `LUMA_API_KEY` | Luma AI API key (for video generation) |
| `IMAGES_DIR` | Generated images storage (default: `.agent42/images`) |
| `AGENT42_IMAGE_MODEL` | Admin override for image model (e.g., `dall-e-3`) |
| `AGENT42_VIDEO_MODEL` | Admin override for video model (e.g., `luma-ray2`) |

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
| design | Llama 4 Maverick | DeepSeek Chat v3.1 | 5 |
| content | Llama 4 Maverick | Gemma 3 27B | 6 |
| strategy | DeepSeek R1 0528 | Llama 4 Maverick | 5 |
| data_analysis | Qwen3 Coder 480B | DeepSeek Chat v3.1 | 6 |
| project_management | Llama 4 Maverick | Gemma 3 27B | 4 |

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

| Skill | Task Types | Description |
|---|---|---|
| **github** | coding | PR creation, issue triage, code review |
| **memory** | all | Read/update persistent agent memory |
| **skill-creator** | all | Generate new skills from descriptions |
| **weather** | research | Weather lookups (example skill) |
| **content-writing** | content, marketing | Blog posts, articles, copywriting frameworks |
| **design-review** | design | UI/UX review, accessibility, brand consistency |
| **strategy-analysis** | strategy, research | SWOT, Porter's Five Forces, market analysis |
| **data-analysis** | data_analysis | Data processing workflows, visualization |
| **social-media** | marketing, content | Social media campaigns, platform guidelines |
| **project-planning** | project_management | Project plans, sprints, roadmaps |
| **presentation** | content, marketing, strategy | Slide decks, executive summaries |
| **brand-guidelines** | design, marketing, content | Brand voice, visual identity |
| **email-marketing** | email, marketing, content | Campaign sequences, deliverability |
| **competitive-analysis** | strategy, research | Competitive matrix, positioning |
| **seo** | content, marketing | On-page SEO, keyword research, optimization |

Skills are matched to tasks by `task_types` frontmatter and injected into the
agent's system prompt automatically.

## Tools

Agents have access to a sandboxed tool registry:

### Core Tools

| Tool | Description |
|---|---|
| `shell` | Sandboxed command execution (with command filter) |
| `read_file` / `write_file` / `edit_file` | Filesystem operations (workspace-restricted) |
| `list_dir` | Directory listing |
| `web_search` | Brave Search API integration |
| `http_client` | HTTP requests to external APIs |
| `python_exec` | Sandboxed Python execution |
| `subagent` | Spawn focused sub-agents for parallel work |
| `cron` | Schedule recurring tasks |
| `repo_map` | Repository structure analysis |
| `pr_generator` | Pull request generation |
| `security_analyzer` | Security vulnerability scanning |
| `workflow` | Multi-step workflow orchestration |
| `summarizer` | Text and code summarization |
| `file_watcher` | File change monitoring |
| `browser` | Web browsing and screenshot |
| `mcp_*` | MCP server tool proxying |

### Non-Code Workflow Tools

| Tool | Description |
|---|---|
| `team` | Multi-agent team orchestration (sequential, parallel, fan-out/fan-in, pipeline workflows). Built-in teams: research, marketing, content, design-review, strategy. Actions: compose, run, status, list, delete, describe, clone |
| `content_analyzer` | Readability (Flesch-Kincaid), tone (formal/informal/persuasive), structure, keywords, compare, SEO analysis |
| `data` | CSV/JSON loading, filtering, statistics, ASCII charts, group-by aggregation |
| `template` | Document templates with variable substitution. Built-in: email-campaign, landing-page, press-release, executive-summary, project-brief. Actions include preview |
| `outline` | Structured document outlines for articles, presentations, reports, proposals, campaigns, project plans |
| `scoring` | Rubric-based content evaluation with weighted criteria. Built-in rubrics: marketing-copy, blog-post, email, research-report, design-brief. Includes improve action for rewrite suggestions |
| `persona` | Audience persona management with demographics, goals, pain points, tone. Built-in: startup-founder, enterprise-buyer, developer, marketing-manager |

### Media Generation Tools

| Tool | Description |
|---|---|
| `image_gen` | AI image generation with free-first routing. Models: FLUX Schnell (free), FLUX Dev, SDXL, DALL-E 3 (premium). Team-reviewed prompts before submission. Actions: generate, review_prompt, list_models, status |
| `video_gen` | AI video generation (async). Models: CogVideoX (cheap), AnimateDiff, Runway Gen-3, Luma Ray2, Stable Video (premium). Actions: generate, image_to_video, review_prompt, list_models, status |

### Command Filter

The shell tool has two layers of defense:

**Layer 1: Command pattern filter** — blocks known-dangerous commands:
- Destructive: `rm -rf /`, `dd if=`, `mkfs`, `shutdown`, `reboot`
- Exfiltration: `scp`, `sftp`, `rsync` to remote, `curl --upload-file`
- Network: `curl | sh`, `wget | bash`, `nc -l`, `ssh -R` tunnels, `socat LISTEN`
- System: `systemctl stop/restart`, `useradd`, `passwd`, `crontab -e`
- Packages: `apt install`, `yum install`, `dnf install`, `snap install`
- Containers: `docker run`, `docker exec`, `kubectl exec`
- Firewall: `iptables -F`, `ufw disable`

**Layer 2: Path enforcement** — scans commands for absolute paths and blocks
any that fall outside the workspace sandbox. System utility paths (`/usr/bin`,
`/usr/lib`, etc.) are allowed. `/tmp` is intentionally excluded from safe paths
to prevent staging attack payloads outside the sandbox. This prevents
`cat /etc/hosts`, `sed /var/www/...`, `ls /home/user/.ssh/`, etc.

Admins can add extra deny patterns or switch to allowlist-only mode.

## Memory & Learning

Agent42 maintains persistent memory and learns from every task:

### Persistent Memory
- **Structured memory** — key/value sections in `MEMORY.md` (project context, preferences, learned patterns)
- **Event log** — append-only `HISTORY.md` for audit trail
- **Session history** — per-conversation message history with configurable limits
- **Semantic search** — vector embeddings for similarity-based memory retrieval (auto-detects OpenAI or OpenRouter embedding APIs; falls back to grep)

### Enhanced Memory Backends (optional)

When Qdrant and/or Redis are configured, Agent42 gains advanced memory capabilities. Both are optional — the system gracefully falls back to file-based storage when they're unavailable.

- **Qdrant vector database** — replaces the JSON vector store with HNSW-indexed semantic search for sub-millisecond retrieval across four collections: `memory`, `history`, `conversations`, and `knowledge`. Supports both Docker server mode and embedded (local file) mode with no server required.
- **Redis session cache** — caches active sessions in memory for <1ms reads (vs. disk I/O), with TTL-based auto-expiry for old sessions and an embedding cache that reduces embedding API calls by caching query vectors.
- **Cross-session conversation search** — with Qdrant, Agent42 can recall conversations from any channel or session ("What did we discuss about X last week?"). Conversations are indexed with metadata (channel, participants, topics, timestamps) for filtered search.
- **Memory consolidation pipeline** — when sessions are pruned, old messages are summarized by an LLM and stored in Qdrant as searchable conversation summaries. No context is lost.

Install with: `pip install qdrant-client redis[hiredis]` (see [Qdrant](#qdrant-vector-database-optional) and [Redis](#redis-optional) configuration above).

### Self-Learning Loop

After every task (success or failure), the agent runs a **reflection cycle**:

1. **Post-task reflection** — analyzes what worked, what didn't, and extracts a lesson
2. **Tool effectiveness tracking** — evaluates which tools were most/least useful
   per task type. Records `[Tool Preferences]` entries to memory (e.g., "For content
   tasks, use content_analyzer before scoring_tool for better results")
3. **Memory update** — writes reusable patterns and conventions to `MEMORY.md`
4. **Tool recommendations** — on future tasks, injects tool usage recommendations
   from prior experience into the agent's system prompt
5. **Failure analysis** — when tasks fail, records root cause to prevent repeats
6. **Reviewer feedback** — when you approve or reject output via the dashboard
   (`POST /api/tasks/{id}/review`), the feedback is stored in memory. Rejections
   are flagged so the agent avoids the same mistakes in future tasks
7. **Skill creation** — when the agent recognizes a repeating pattern across tasks,
   it can create a new workspace skill (`skills/workspace/`) to codify the pattern
   for future use

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

Approval requests timeout after 1 hour (configurable) and auto-deny to prevent
agents from blocking indefinitely when nobody is watching the dashboard.

## Reliability

### API Retry with Fallback

All LLM API calls use exponential backoff retry (3 attempts: 1s, 2s, 4s). If
all retries fail, the engine automatically falls back to a different model
(Llama 4 Maverick) before giving up. This prevents a single API timeout from
killing an entire task.

### Convergence Detection

The iteration engine monitors critic feedback across iterations. When the critic
repeats substantially similar feedback (>85% word overlap), the loop accepts the
output and stops to avoid burning tokens on a stuck review cycle.

### Context-Aware Task Classification

Messages from channels are classified using a two-layer system:

**Layer 1: LLM-based classification** — A fast, free LLM (Mistral Small) analyzes
the message with conversation history context to understand intent:
- Considers prior messages in the conversation for context
- Returns confidence score (0.0-1.0)
- When ambiguous (confidence < 0.4), asks the user for clarification before creating a task
- Suggests relevant tools based on the request

**Layer 2: Keyword fallback** — If the LLM is unavailable, falls back to substring
keyword matching for reliable classification:
- "fix the login bug" → debugging
- "write a blog post" → content
- "create a social media campaign" → marketing
- "design a wireframe" → design
- "SWOT analysis" → strategy
- "load CSV spreadsheet" → data_analysis
- "create a project timeline" → project_management

Supports all 12 task types with correct model routing for each.

### Non-Code Agent Mode

For non-coding tasks (design, content, strategy, data_analysis, project_management,
marketing, email), the agent skips git worktree creation and instead:
- Creates output directories in `.agent42/outputs/{task_id}/`
- Uses task-type-specific system prompts and critic prompts
- Saves output as `output.md` instead of `REVIEW.md`
- Skips git commit/diff steps

### Task Recovery on Restart

Tasks that were in RUNNING state when the orchestrator shut down are automatically
reset to PENDING on restart, so they get re-dispatched. Duplicate enqueuing is
prevented by tracking queued task IDs.

### Worktree Cleanup

When an agent fails, its git worktree is automatically cleaned up to prevent
orphaned worktrees from filling up disk space.

## Project Structure

```
agent42/
├── agent42.py                 # Main entry point + orchestrator
├── core/
│   ├── config.py              # Centralized settings from .env
│   ├── task_queue.py          # Task state machine + JSON persistence (12 task types)
│   ├── intent_classifier.py   # LLM-based context-aware task classification
│   ├── worktree_manager.py    # Git worktree lifecycle
│   ├── approval_gate.py       # Protected operation intercept
│   ├── heartbeat.py           # Agent health monitoring
│   ├── command_filter.py      # Shell command safety filter (40+ deny patterns)
│   ├── sandbox.py             # Workspace path restriction (symlink + null byte protection)
│   └── complexity.py          # Task complexity assessment + team recommendation
├── agents/
│   ├── agent.py               # Per-task agent orchestration (code + non-code modes)
│   ├── model_router.py        # Free-first task-type -> model routing
│   ├── iteration_engine.py    # Primary -> Critic -> Revise loop (task-aware critics)
│   └── learner.py             # Self-learning: reflection + tool effectiveness tracking
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
│   ├── http_client.py         # HTTP requests
│   ├── python_exec.py         # Sandboxed Python execution
│   ├── subagent.py            # Sub-agent spawning
│   ├── cron.py                # Scheduled task execution
│   ├── repo_map.py            # Repository structure analysis
│   ├── pr_generator.py        # Pull request generation
│   ├── security_analyzer.py   # Security vulnerability scanning
│   ├── workflow_tool.py       # Multi-step workflows
│   ├── summarizer.py          # Text/code summarization
│   ├── file_watcher.py        # File change monitoring
│   ├── browser.py             # Web browsing + screenshots
│   ├── mcp_client.py          # MCP server tool proxying
│   ├── team_tool.py           # Multi-agent team orchestration
│   ├── content_analyzer.py    # Readability, tone, structure, SEO analysis
│   ├── data_tool.py           # CSV/JSON data loading + analysis
│   ├── template_tool.py       # Document templates with variable substitution
│   ├── outline_tool.py        # Structured document outlines
│   ├── scoring_tool.py        # Rubric-based content evaluation + improvement
│   ├── persona_tool.py        # Audience persona management
│   ├── image_gen.py           # AI image generation (free-first)
│   └── video_gen.py           # AI video generation (async)
├── skills/
│   ├── loader.py              # Skill discovery + frontmatter parser
│   └── builtins/              # Built-in skill templates (15 skills)
│       ├── github/SKILL.md
│       ├── memory/SKILL.md
│       ├── skill-creator/SKILL.md
│       ├── weather/SKILL.md
│       ├── content-writing/SKILL.md
│       ├── design-review/SKILL.md
│       ├── strategy-analysis/SKILL.md
│       ├── data-analysis/SKILL.md
│       ├── social-media/SKILL.md
│       ├── project-planning/SKILL.md
│       ├── presentation/SKILL.md
│       ├── brand-guidelines/SKILL.md
│       ├── email-marketing/SKILL.md
│       ├── competitive-analysis/SKILL.md
│       └── seo/SKILL.md
├── memory/
│   ├── store.py               # Structured memory + event log
│   ├── session.py             # Per-conversation session history (Redis-cached)
│   ├── embeddings.py          # Pluggable vector store + semantic search
│   ├── qdrant_store.py        # Qdrant vector DB backend (HNSW search, collections)
│   ├── redis_session.py       # Redis session cache + embedding cache
│   └── consolidation.py       # Conversation summarization pipeline
├── dashboard/
│   ├── server.py              # FastAPI + WebSocket server (security headers, auth)
│   ├── auth.py                # JWT authentication + rate limiting
│   ├── websocket_manager.py   # Real-time broadcast
│   └── frontend/dist/         # SPA dashboard (vanilla JS, no build step)
│       ├── index.html         # Entry point
│       ├── app.js             # Full SPA (login, tasks, approvals, tools, skills, settings)
│       └── style.css          # Dark theme CSS
├── tests/                     # 540+ tests across 19 test files
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

## Team Orchestration

The `team` tool enables multi-agent collaboration with four workflow types:

- **sequential** — roles run in order, each receiving full team context
- **parallel** — all roles run simultaneously, results aggregated
- **fan_out_fan_in** — parallel groups run first, then remaining roles merge results
- **pipeline** — sequential with independent critic iteration per role

### Manager / Coordinator

Every team run is automatically coordinated by a **Manager agent**:

1. **Planning Phase** — Manager analyzes the task and creates an execution plan
   - Breaks the task into subtasks for each role
   - Sets expectations, deliverables, and quality criteria per role
   - Identifies dependencies between roles
2. **Team Execution** — Roles execute their workflow with the Manager's plan as context
3. **Review Phase** — Manager reviews all role outputs
   - Checks for completeness, consistency, and quality
   - Synthesizes a final deliverable integrating all role work
   - Assigns a quality score (1-10)
4. **Revision Handling** — If any role's output is insufficient, Manager flags it
   - Flagged roles are re-run once with specific manager feedback
   - Post-revision, Manager re-reviews to ensure quality

### Shared Team Context

Roles don't just receive the previous role's output — they see the full **TeamContext**:

- The original task description
- The Manager's execution plan
- All prior role outputs (sequential) or no peer outputs (parallel)
- Manager-directed feedback (during revisions)
- Shared team notes

This enables true inter-agent communication where each role understands the full project scope and can build on all prior work.

### Smart Resource Allocation

Agent42 automatically determines whether a task needs a single agent or a full team:

- **Intent Classification** — The LLM classifier analyzes task complexity and recommends `single_agent` or `team` mode
- **Complexity Assessment** — Keyword signals (scale markers, multi-deliverable markers, team indicators, cross-domain keywords) supplement LLM assessment
- **Auto-dispatch** — Complex tasks automatically include team tool directives in their description
- **Team Matching** — The recommended team is matched to the task's domain (marketing → marketing-team, design → design-review, etc.)

Simple tasks ("Fix the login bug") run as single agents with zero overhead. Complex tasks ("Create a comprehensive marketing campaign with social media, email, and blog content") are automatically routed to the appropriate team with Manager coordination.

### Built-in Teams

| Team | Workflow | Roles |
|---|---|---|
| research-team | sequential | researcher → analyst → writer |
| marketing-team | pipeline | researcher → strategist → copywriter → editor |
| content-team | sequential | writer → editor → SEO optimizer |
| design-review | sequential | designer → critic → brand reviewer |
| strategy-team | fan_out_fan_in | market-researcher + competitive-researcher → strategist → presenter |

Clone any built-in team to customize roles and workflow for your needs.

## Media Generation

### Image Generation

Free-first model routing for images, same pattern as text LLMs:

| Model | Provider | Tier | Resolution |
|---|---|---|---|
| FLUX.1 Schnell | OpenRouter | Free | 1024x1024 |
| FLUX.1 Dev | Replicate | Cheap | 1024x1024 |
| SDXL | Replicate | Cheap | 1024x1024 |
| DALL-E 3 | OpenAI | Premium | 1024x1792 |
| FLUX 1.1 Pro | Replicate | Premium | 1024x1024 |

**Prompt review**: Before submitting a prompt for generation, a team of agents
reviews and enhances the prompt for best results. This includes adding specific
details about composition, lighting, style, and quality. Skip with `skip_review=true`.

### Video Generation

Video generation is async — the tool returns a job ID for polling:

| Model | Provider | Tier | Max Duration |
|---|---|---|---|
| CogVideoX-5B | Replicate | Cheap | 6s |
| AnimateDiff | Replicate | Cheap | 4s |
| Runway Gen-3 Turbo | Replicate | Premium | 10s |
| Luma Ray2 | Luma AI | Premium | 10s |
| Stable Video Diffusion | Replicate | Premium | 4s |

Admin override: Set `AGENT42_IMAGE_MODEL` or `AGENT42_VIDEO_MODEL` env vars to
force specific models for all generations.

## Dashboard

Agent42 includes a full web dashboard for managing tasks, approvals, tools,
skills, and settings.

### Features

- **Login** — JWT-based authentication with bcrypt password hashing
- **Task Management** — Create, view, approve, cancel, retry tasks with real-time status updates
- **Task Detail** — Full task info: status, type, iterations, description, output/error
- **Approvals** — Approve or deny agent operations (email send, git push, file delete) from the dashboard
- **Review with Feedback** — Approve or request changes on completed tasks; feedback is stored in agent memory for learning
- **Tools & Skills** — View all registered tools and loaded skills
- **Settings** — Organized into 5 tabs with clear descriptions for every setting:
  - **LLM Providers** — API keys for OpenRouter, OpenAI, Anthropic, DeepSeek, Gemini, Replicate, Luma, Brave
  - **Channels** — Discord, Slack, Telegram, Email (IMAP/SMTP) configuration
  - **Security** — Dashboard auth, rate limiting, sandbox settings, CORS
  - **Orchestrator** — Concurrent agents, spending limits, repo path, task file, MCP, cron
  - **Storage & Paths** — Memory, sessions, outputs, templates, images, skills directories
- **WebSocket** — Real-time updates with exponential backoff reconnection
- **Responsive** — Mobile-friendly layout with sidebar navigation

Settings are read-only in the dashboard (configured via environment variables in `.env`).
Each setting shows its environment variable name, current status, and help text.

## Security

Agent42 is designed to run safely on a shared VPS alongside other services
(your website, databases, etc.). The agent cannot access anything outside its
workspace.

### Sandbox & Execution

- **Workspace sandbox** — Filesystem tools can only read/write within the project worktree. Path traversal (`../`) and absolute paths outside workspace are blocked. Null bytes in paths are rejected. Symlinks that escape the sandbox are detected and blocked.
- **Shell path enforcement** — Shell commands are scanned for absolute paths — any path outside the workspace (e.g. `/var/www`, `/etc/nginx`) is blocked before execution. `/tmp` is excluded from safe paths to prevent attack staging.
- **Command filter** — 40+ dangerous command patterns blocked (destructive ops, network exfiltration, service manipulation, package installation, container escape, user/permission changes, background processes, env variable exfiltration, history access, writing to sensitive files).
- **Python execution** — Python code is checked for dangerous patterns (subprocess, os.system, ctypes, eval/exec, etc.) before execution. API keys and secrets are stripped from the subprocess environment.
- **Git tool sanitization** — Git arguments are scanned for dangerous flags (`--upload-pack`, `--exec`, `-c`) that could execute arbitrary commands. Sensitive file staging (.env, credentials.json) is blocked.

### Authentication & Network

- **Dashboard auth** — JWT-based authentication with bcrypt password hashing (plaintext fallback for dev only with warning).
- **Rate limiting** — Login attempts are rate-limited per IP (default: 5/minute) to prevent brute-force attacks.
- **WebSocket auth** — Real-time dashboard connections require a valid JWT token (`/ws?token=<jwt>`). Unauthenticated connections are rejected. Message size is validated (max 4KB).
- **WebSocket connection limits** — Maximum 50 simultaneous WebSocket connections (configurable).
- **CORS** — Restricted to configured origins only (no wildcard). Empty = same-origin only.
- **Security headers** — All HTTP responses include: X-Content-Type-Options (nosniff), X-Frame-Options (DENY), CSP (script-src 'self'), Referrer-Policy, Permissions-Policy. HSTS enabled over HTTPS.
- **Health endpoint** — Public `/health` returns only `{"status": "ok"}`. Detailed metrics available via authenticated `/api/health`.
- **SSRF protection** — HTTP client and web search tools block requests to private/internal IPs (127.0.0.1, 169.254.x.x, 10.x.x.x, 192.168.x.x).

### Approval Gates

Sensitive operations pause the agent and require dashboard approval:
- `gmail_send` — sending email
- `git_push` — pushing code
- `file_delete` — deleting files
- `external_api` — calling external services

### Production Recommendations

- Put nginx in front with HTTPS before making public
- Set `JWT_SECRET` to a 64-char random string
- Use `DASHBOARD_PASSWORD_HASH` (bcrypt) instead of plaintext `DASHBOARD_PASSWORD`
- Set `CORS_ALLOWED_ORIGINS` to your domain
- Set `MAX_DAILY_API_SPEND_USD` to cap API costs
- Keep `SANDBOX_ENABLED=true` and `WORKSPACE_RESTRICT=true`

# 🛸 Agent42

**Don't Panic.** The answer to life, the universe, and all your tasks.

> *"The Guide says there is an art to flying, or rather a knack.
> The knack lies in learning how to throw yourself at the ground and miss."*
> — The same applies to multi-agent orchestration.

A multi-agent orchestrator platform. Free models handle the iterative work;
Claude Code (or human review) gates the final output before anything ships.

Not just for coding — Agent42 handles marketing, design, content creation,
strategy, data analysis, project management, media generation, and any task
you throw at it. Spin up teams of agents to collaborate, critique, and iterate.

## Architecture

```
Inbound Channel  ->  Task Queue  ->  Agent Loop  ->  Critic Pass  ->  REVIEW.md  ->  You + Claude Code  ->  Ship
(Slack/Discord/     (priority +      (free LLMs     (independent     (diff, logs,    (human approval       (Don't
 Telegram/Email/     concurrency)     via OpenRouter) second opinion)  critic notes)   gate)                Panic)
 Dashboard/CLI)
(Infinite            (The Answer      (Mostly         (Towel           (The only human                      (🚀)
 Improbability        Engine)          Harmless)       Included)        in the loop)
 Queue)
```

**Free-first strategy** — all agent work defaults to $0 models via OpenRouter:

- **Coding**: Gemini Flash (primary) + Qwen3 Coder 480B (critic)
- **Debugging**: Gemini Flash (primary) + Qwen3 Coder 480B (critic)
- **Research**: Llama 4 Maverick (primary) + DeepSeek Chat v3.1 (critic)
- **Marketing/Content/Design**: Llama 4 Maverick + task-aware critics
- **Image/Video**: FLUX (free), DALL-E 3, Replicate, Luma (premium)
- **Review gate**: Human + Claude Code final review before anything ships
- **Zero API cost**: One free OpenRouter API key unlocks 30+ models

Premium models (GPT-4o, Claude Sonnet, Gemini Pro) available for admin-configured
task types — see [Model Routing](#model-routing).

## Quick Start (Don't Panic)

### Prerequisites

Before you begin, verify these are installed:

| Requirement | Minimum Version | Check Command |
|---|---|---|
| Python | 3.11+ | `python3 --version` |
| Node.js | 18+ (auto-installed if missing) | `node --version` |
| git | any | `git --version` |

**Ubuntu/Debian:** `sudo apt update && sudo apt install python3 python3-venv nodejs npm git`
**macOS:** `brew install python node git`

### Installation

#### 1. Clone the repository

```bash
git clone <this-repo> agent42
cd agent42
```

#### 2. Run the setup script

```bash
bash setup.sh
```

This script automatically:
- Verifies Python 3.11+ is installed
- Installs Node.js 20 via nvm if not already present
- Creates a Python virtual environment in `.venv/`
- Installs all Python dependencies from `requirements.txt`
- Copies `.env.example` to `.env` (if `.env` doesn't exist yet)
- Builds the dashboard frontend (if `dashboard/frontend/package.json` exists)
- Generates a systemd service file at `/tmp/agent42.service` for optional background running

#### 3. Prepare your git repository

Agent42 uses git worktrees to give each agent an isolated copy of your codebase.
Your target repository **must** have a `dev` branch:

```bash
cd /path/to/your/project
git checkout -b dev    # create dev branch if it doesn't exist
cd ~/agent42           # return to agent42 directory
```

**Note:** If you skip this step, coding, debugging, and refactoring tasks will fail
with a git worktree error when they try to create an isolated workspace. Non-code
tasks (marketing, content, design, etc.) work fine without a `dev` branch.

#### 4. Start Agent42

```bash
source .venv/bin/activate
python agent42.py --repo /path/to/your/project
```

Other options:
- `--port 8080` — Use a different dashboard port (default: 8000)
- `--no-dashboard` — Headless mode (terminal only, no web UI)
- `--max-agents 2` — Limit concurrent agents (default: 3)

#### 5. Complete setup in your browser

Open http://localhost:8000. On first launch, Agent42 shows a setup wizard:

1. **Set your password** — Choose a dashboard password (8+ characters). This is
   stored as a bcrypt hash — the plaintext is never saved.
2. **Add an API key** (optional) — Enter your OpenRouter API key. Get a free key
   at [openrouter.ai/keys](https://openrouter.ai/keys) (no credit card needed).
   You can also add this later via Settings > LLM Providers.
3. **Enhanced Memory** (optional) — Choose a memory backend:
   - **Skip** — File-based memory (default, no extra setup)
   - **Qdrant Embedded** — Semantic vector search stored locally (no Docker needed)
   - **Qdrant + Redis** — Full semantic search + session caching.
     Selecting this auto-queues a setup task to verify the services are running.
4. **Done** — Setup completes and you're automatically logged in.

The wizard also generates a `JWT_SECRET` for persistent sessions and writes all
configuration to `.env` automatically.

**Power users:** You can skip the wizard and edit `.env` directly before first launch.
Set `DASHBOARD_PASSWORD_HASH` (bcrypt) and `OPENROUTER_API_KEY`, then restart.

After setup, additional API keys can be configured through the dashboard
(Settings > LLM Providers). Keys set via the dashboard take effect immediately
without a restart and are stored in `.agent42/settings.json`.

### Your First Task

Once logged in, try creating your first task:

1. Click **New Task** in the dashboard
2. Enter a title like "Add a hello world endpoint" and a description
3. Select task type **coding** and click Create
4. Watch the agent pick up the task, iterate with a critic, and produce a `REVIEW.md`

The agent creates a git worktree, makes changes, gets critic feedback, revises, and
produces output for your review.

### Troubleshooting

| Problem | Solution |
|---|---|
| `Python 3.11+ required` | Install Python 3.11+. Ubuntu: `sudo add-apt-repository ppa:deadsnakes/ppa && sudo apt install python3.11` |
| `ModuleNotFoundError` | Make sure you activated the venv: `source .venv/bin/activate` |
| Setup wizard not appearing | Only shows when no password is configured. If you set one manually, go to `/login` directly |
| Git worktree error at startup | Ensure your target repo has a `dev` branch: `git checkout -b dev` |
| `OPENROUTER_API_KEY not set` | Enter during setup wizard, or add later via Settings > LLM Providers |
| Port 8000 already in use | Use `--port 8080` flag: `python agent42.py --repo /path --port 8080` |
| Frontend not loading | Re-run: `cd dashboard/frontend && npm install && npm run build` |
| Login fails after restart | Set `JWT_SECRET` in `.env` (the setup wizard does this automatically) |
| Everything is broken | Don't Panic. Grab your towel. `bash setup.sh` |
| "It's only a flesh wound" | Task failed but partially completed? Check `.agent42/outputs/` for salvageable work |

### Minimum Setup (free, no credit card)

1. Create an [OpenRouter account](https://openrouter.ai) (free, no credit card)
2. Generate an API key at the OpenRouter dashboard
3. Enter the key during the setup wizard, or add it later in Settings > LLM Providers

That's it — you now have access to 30+ free models for all task types.

### Optional: Enhanced Memory (Qdrant + Redis)

For persistent cross-session memory, fast semantic search, and session caching:

**Production deployments:** `deploy/install-server.sh` automatically installs and
configures Redis and Qdrant as native systemd services. No additional setup needed.

**Local development:** Choose "Qdrant + Redis" in the browser setup wizard, then
start the services:

```bash
# Install client libraries
pip install qdrant-client redis[hiredis]

# Option A: Docker
docker run -d -p 6333:6333 qdrant/qdrant
docker run -d -p 6379:6379 redis:alpine

# Option B: Native (Ubuntu/Debian)
sudo apt install redis-server
# See Qdrant docs for binary install

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

Most settings are configured automatically by the setup wizard on first launch.
For advanced configuration, edit `.env` directly. See `.env.example` for all 80+ options.

LLM provider API keys can also be configured through the dashboard admin UI
(Settings > LLM Providers). Keys set via the dashboard are stored locally in
`.agent42/settings.json` and override `.env` values without requiring a restart.

### Core Settings

| Variable | Default | Description |
|---|---|---|
| `OPENROUTER_API_KEY` | — | OpenRouter API key (primary, free) |
| `MAX_CONCURRENT_AGENTS` | `3` | Max parallel agents (2-3 for 6GB VPS) |
| `DEFAULT_REPO_PATH` | `.` | Git repo for worktrees |
| `DASHBOARD_USERNAME` | `admin` | Dashboard login |
| `DASHBOARD_PASSWORD` | — | Dashboard password (set via setup wizard) |
| `DASHBOARD_PASSWORD_HASH` | — | Bcrypt hash (auto-generated by setup wizard) |
| `JWT_SECRET` | *(auto-generated)* | JWT signing key (auto-generated by setup wizard) |
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
| `CUSTOM_TOOLS_DIR` | Directory for auto-discovered custom tool plugins |
| `BRAVE_API_KEY` | Brave Search API key (for web search tool) |
| `MCP_SERVERS_JSON` | Path to MCP servers config (JSON) |
| `CRON_JOBS_PATH` | Path to persistent cron jobs file |
| `REPLICATE_API_TOKEN` | Replicate API token (for image/video generation) |
| `LUMA_API_KEY` | Luma AI API key (for video generation) |
| `IMAGES_DIR` | Generated images storage (default: `.agent42/images`) |
| `AGENT42_IMAGE_MODEL` | Admin override for image model (e.g., `dall-e-3`) |
| `AGENT42_VIDEO_MODEL` | Admin override for video model (e.g., `luma-ray2`) |

### SSH & Tunnels

| Variable | Default | Description |
|---|---|---|
| `SSH_ENABLED` | `false` | Enable SSH remote shell tool |
| `SSH_ALLOWED_HOSTS` | *(empty — all blocked)* | Comma-separated host patterns (e.g., `*.example.com`) |
| `SSH_DEFAULT_KEY_PATH` | *(none)* | Default private key path |
| `SSH_MAX_UPLOAD_MB` | `50` | Max SFTP upload size in MB |
| `SSH_COMMAND_TIMEOUT` | `120` | Per-command timeout in seconds |
| `TUNNEL_ENABLED` | `false` | Enable tunnel manager tool |
| `TUNNEL_PROVIDER` | `auto` | Provider: `auto`, `cloudflared`, `serveo`, `localhost.run` |
| `TUNNEL_ALLOWED_PORTS` | *(empty — all allowed)* | Comma-separated allowed ports |
| `TUNNEL_TTL_MINUTES` | `60` | Auto-shutdown TTL for tunnels |

### Knowledge & Vision

| Variable | Default | Description |
|---|---|---|
| `KNOWLEDGE_DIR` | `.agent42/knowledge` | Document storage directory |
| `KNOWLEDGE_CHUNK_SIZE` | `500` | Chunk size in tokens |
| `KNOWLEDGE_CHUNK_OVERLAP` | `50` | Overlap between chunks |
| `KNOWLEDGE_MAX_RESULTS` | `10` | Max results per query |
| `VISION_MAX_IMAGE_MB` | `10` | Max image file size in MB |
| `VISION_MODEL` | *(auto-detect)* | Override model for vision tasks |

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

## Recursive Language Models (RLM)

Agent42 integrates MIT CSAIL's [Recursive Language Models](https://arxiv.org/abs/2512.24601)
(RLM) for processing inputs far beyond model context windows. When a task's
context exceeds a configurable threshold (default: 50K tokens), RLM
automatically activates — treating the large context as an external variable
in a REPL environment that the model can programmatically inspect, decompose,
and recursively process.

### How It Works

1. **Context-as-Variable** — Instead of stuffing massive prompts into the LLM,
   the text is stored as a Python variable. The model receives only the query +
   metadata about the variable.
2. **REPL Environment** — The root model writes Python code to inspect the
   context: slicing, regex, chunking, and pulling only relevant pieces into its
   active window.
3. **Recursive Sub-Calls** — The root model can call itself (or another LLM)
   recursively to process sub-sections, then synthesize results.

### Configuration

```bash
RLM_ENABLED=true                  # Master toggle
RLM_THRESHOLD_TOKENS=50000        # Context size to trigger RLM (tokens)
RLM_ENVIRONMENT=local             # REPL env: local, docker, modal, prime
RLM_MAX_DEPTH=3                   # Max recursion depth
RLM_MAX_ITERATIONS=20             # Max REPL iterations
RLM_COST_LIMIT=1.00               # Max cost per query (USD)
RLM_TIMEOUT_SECONDS=300           # Per-query timeout
```

### RLM-Capable Models

| Tier | Models | Use Case |
|------|--------|----------|
| 1 (Best) | Qwen3-Coder, Claude Sonnet, GPT-4o | RLM root model |
| 2 (Good) | Gemini Flash, GPT-4o-mini, DeepSeek Chat | Sub-calls, cheaper tasks |
| 3 (Not recommended) | Llama 70B, Gemma 27B | Lack code generation for REPL |

Install the RLM library: `pip install rlms`

---

## Model Routing

### Default (Free) Routing — OpenRouter

One API key, zero cost. These models are used by default for all task types:

| Task Type | Primary Model | Critic Model | Max Iterations |
|---|---|---|---|
| coding | Gemini 2.5 Flash | Qwen3 Coder 480B | 8 |
| debugging | Gemini 2.5 Flash | Qwen3 Coder 480B | 10 |
| research | Gemini 2.5 Flash | Llama 3.3 70B | 5 |
| refactoring | Gemini 2.5 Flash | Qwen3 Coder 480B | 8 |
| documentation | Gemini 2.5 Flash | Gemma 3 27B | 4 |
| marketing | Gemini 2.5 Flash | Llama 3.3 70B | 6 |
| email | Gemini 2.5 Flash | — | 3 |
| design | Gemini 2.5 Flash | Llama 3.3 70B | 5 |
| content | Gemini 2.5 Flash | Gemma 3 27B | 6 |
| strategy | Gemini 2.5 Flash | Llama 3.3 70B | 5 |
| data_analysis | Gemini 2.5 Flash | Qwen3 Coder 480B | 6 |
| project_management | Gemini 2.5 Flash | Gemma 3 27B | 4 |

### Dynamic Routing (Self-Improving)

Agent42 automatically discovers, evaluates, and promotes the best free models
over time using a 4-layer resolution chain:

1. **Admin override** — `AGENT42_{TYPE}_MODEL` env vars (highest priority)
2. **Dynamic routing** — `data/dynamic_routing.json` written by ModelEvaluator based on actual task outcomes
3. **Trial injection** — Unproven models are randomly assigned to a percentage of tasks to gather performance data
4. **Hardcoded defaults** — `FREE_ROUTING` dict (lowest priority fallback)

**How it works:**
- **ModelCatalog** syncs free models from the OpenRouter API every 24 hours (configurable)
- **ModelEvaluator** tracks success rate, iteration efficiency, and critic scores per model per task type
- **ModelResearcher** fetches benchmark scores from LMSys Arena, HuggingFace, and Artificial Analysis
- Models are ranked by composite score: `0.4×success + 0.3×efficiency + 0.2×critic + 0.1×research`
- Models with fewer than 5 completions (configurable) are "unproven" and entered into the trial system
- After enough trials, proven models are promoted to the dynamic routing table

| Variable | Default | Description |
|---|---|---|
| `MODEL_ROUTING_FILE` | `data/dynamic_routing.json` | Path to dynamic routing data |
| `MODEL_CATALOG_REFRESH_HOURS` | `24` | OpenRouter catalog sync interval |
| `MODEL_TRIAL_PERCENTAGE` | `10` | % of tasks assigned to unproven models |
| `MODEL_MIN_TRIALS` | `5` | Minimum completions before a model is ranked |
| `MODEL_RESEARCH_ENABLED` | `true` | Enable web benchmark research |
| `MODEL_RESEARCH_INTERVAL_HOURS` | `168` | Research fetch interval (default: weekly) |

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
| DeepSeek R1 0528 | `deepseek/deepseek-r1-0528:free` | Reasoning, debugging, math |
| DeepSeek Chat v3.1 | `deepseek/deepseek-chat-v3.1:free` | General chat, hybrid reasoning |
| Llama 4 Maverick | `meta-llama/llama-4-maverick:free` | Research, writing, general |
| Llama 3.3 70B | `meta-llama/llama-3.3-70b-instruct:free` | General purpose |
| Gemini 2.5 Pro | `google/gemini-2.5-pro-exp-03-25:free` | Complex tasks |
| Gemini Flash | `google/gemini-2.0-flash-exp:free` | Long context (1M tokens) |
| Mistral Small 3.1 | `mistralai/mistral-small-3.1-24b-instruct:free` | Fast, lightweight tasks |
| Gemma 3 27B | `google/gemma-3-27b-it:free` | Fast verification |
| Nemotron 30B | `nvidia/nemotron-3-nano-30b-a3b:free` | General purpose |

## Skills

Skills are markdown prompt templates that give agents specialized capabilities.
They live in `skills/builtins/` and can be extended per-repo in a `skills/` directory
or via the `SKILLS_DIRS` env var.

### Skill Extensions

Skills support an `extends` frontmatter field that lets you add to a core skill
without replacing it entirely. This is ideal for adding company branding, custom
workflows, or domain-specific guidelines on top of existing skills.

```markdown
# skills/workspace/brand-seo/SKILL.md
---
name: brand-seo
extends: seo
description: SEO with Acme Corp branding guidelines
task_types: [design]
---

## Acme Corp SEO Extensions
- Always include "Acme" in meta descriptions
- Primary brand terms: "enterprise automation", "workflow AI"
```

This merges your custom content into the base `seo` skill and adds `design` to its
task types. The base skill's instructions appear first, followed by all extensions.

### Built-in Skills

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
| **geo** | design, content, marketing | Generative Engine Optimization — AI agent discoverability |
| **server-management** | deployment | LAMP/LEMP stack, nginx, systemd, firewall hardening |
| **wordpress** | deployment | WP-CLI, wp-config, themes, plugins, multisite, backups |
| **docker-deploy** | deployment | Dockerfile best practices, docker-compose, registry workflows |
| **cms-deploy** | deployment | Ghost, Strapi, and general CMS deployment patterns |
| **code-review** | coding | Code quality review with structured feedback |
| **debugging** | debugging | Systematic debugging methodology |
| **testing** | coding | Test strategy, coverage, test-driven development |
| **refactoring** | refactoring | Safe refactoring patterns and techniques |
| **documentation** | documentation | Technical writing, API docs, guides |
| **security-audit** | coding | Security vulnerability assessment |
| **tool-creator** | all | Generate new custom tools from descriptions |
| **git-workflow** | coding | Branch strategy, commit conventions, merge workflows |

40 built-in skills total. Skills are matched to tasks by `task_types` frontmatter
and injected into the agent's system prompt automatically.

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

### Infrastructure Tools

| Tool | Description |
|---|---|
| `ssh` | Remote shell execution via asyncssh. Host allowlist, command filtering, SFTP uploads/downloads, per-command timeout. Actions: connect, execute, upload, download, disconnect, list_connections. Requires approval gate for first connection to each host |
| `tunnel` | Expose local ports to the internet via cloudflared, serveo, or localhost.run. Auto-expiry TTL (default 60 min), port allowlist enforcement. Actions: start, stop, status, list. Requires approval gate |
| `knowledge` | Document import and RAG semantic querying. Supports PDF, CSV, HTML, Markdown, JSON, plain text. Configurable chunk size with overlap. Qdrant vector backend with filesystem keyword-search fallback. Actions: import_file, import_dir, query, list, delete |
| `vision` | Image analysis via LLM vision APIs (OpenAI, Anthropic, OpenRouter). Automatic Pillow compression for cost efficiency. Supports PNG, JPG, GIF, WebP, BMP. Actions: analyze, describe, compare |

SSH and tunnel tools are disabled by default — see [SSH & Tunnels](#ssh--tunnels) configuration.

### Custom Tool Plugins

Extend Agent42 with custom tools without modifying the core codebase. Set
`CUSTOM_TOOLS_DIR` in `.env` and drop `.py` files containing `Tool` subclasses:

```python
# custom_tools/hello.py
from tools.base import Tool, ToolResult

class HelloTool(Tool):
    requires = ["workspace"]  # Dependency injection from ToolContext

    def __init__(self, workspace="", **kwargs):
        self._workspace = workspace

    @property
    def name(self) -> str: return "hello"
    @property
    def description(self) -> str: return "Says hello"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {}}

    async def execute(self, **kwargs) -> ToolResult:
        return ToolResult(output=f"Hello from {self._workspace}!")
```

Tools are auto-discovered and registered at startup. The `requires` class variable
declares which dependencies to inject from `ToolContext` (sandbox, command_filter,
task_queue, workspace, tool_registry, model_router).

| Variable | Default | Description |
|---|---|---|
| `CUSTOM_TOOLS_DIR` | *(disabled)* | Directory for auto-discovered custom tool plugins |

### Tool Extensions

Extend an existing tool's behavior without replacing it. Tool extensions add
parameters and pre/post execution hooks that layer onto any registered tool.
Multiple extensions can stack on one base tool.

```python
# custom_tools/shell_audit.py
from tools.base import ToolExtension, ToolResult

class ShellAuditExtension(ToolExtension):
    extends = "shell"                      # Name of the tool to extend
    requires = ["workspace"]               # ToolContext injection (same as Tool)

    def __init__(self, workspace="", **kwargs):
        self._workspace = workspace

    @property
    def name(self) -> str: return "shell_audit"

    @property
    def extra_parameters(self) -> dict:    # Merged into the base tool's schema
        return {"audit": {"type": "boolean", "description": "Log command to audit file"}}

    @property
    def description_suffix(self) -> str:   # Appended to the base tool's description
        return "Supports audit logging."

    async def pre_execute(self, **kwargs) -> dict:
        # Called before the base tool — can inspect/modify kwargs
        return kwargs

    async def post_execute(self, result: ToolResult, **kwargs) -> ToolResult:
        # Called after the base tool — can inspect/modify result
        return result
```

Extensions are auto-discovered from the same `CUSTOM_TOOLS_DIR` directory as
custom tools. The `extends` field must match an already-registered tool name.

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

## Memory & Learning (Total Perspective Vortex)

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
- `ssh_connect` — first SSH connection to a new host
- `tunnel_start` — exposing a local port via tunnel

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
│   ├── task_queue.py          # Priority queue + JSON/Redis persistence (12 task types)
│   ├── queue_backend.py       # Queue backend abstraction (JSON file + Redis)
│   ├── intent_classifier.py   # LLM-based context-aware task classification
│   ├── worktree_manager.py    # Git worktree lifecycle
│   ├── approval_gate.py       # Protected operation intercept
│   ├── heartbeat.py           # Agent health monitoring
│   ├── command_filter.py      # Shell command safety filter (40+ deny patterns)
│   ├── sandbox.py             # Workspace path restriction (symlink + null byte protection)
│   ├── complexity.py          # Task complexity assessment + team recommendation
│   ├── device_auth.py         # Multi-device API key registration and validation
│   ├── key_store.py           # Admin-configured API key overrides (dashboard)
│   ├── security_scanner.py    # Scheduled vulnerability scanning + GitHub issue reporting
│   ├── rate_limiter.py        # Per-agent per-tool sliding-window rate limits
│   ├── capacity.py            # Dynamic concurrency based on CPU/memory metrics
│   ├── url_policy.py          # URL allowlist/denylist for SSRF protection
│   ├── notification_service.py # Webhook and email notifications
│   └── portability.py         # Backup/restore/clone operations
├── agents/
│   ├── agent.py               # Per-task agent orchestration (code + non-code modes)
│   ├── model_router.py        # 4-layer model selection (admin → dynamic → trial → default)
│   ├── model_catalog.py       # OpenRouter catalog sync, free model auto-discovery
│   ├── model_evaluator.py     # Outcome tracking, composite scoring, trial system
│   ├── model_researcher.py    # Web benchmark research (LMSys, HuggingFace, etc.)
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
│   ├── base.py                # Tool + ToolExtension base classes, result types
│   ├── registry.py            # Tool registration + dispatch
│   ├── context.py             # ToolContext dependency injection for plugin tools
│   ├── plugin_loader.py       # Auto-discovers custom Tool/ToolExtension subclasses
│   ├── shell.py               # Sandboxed shell execution
│   ├── filesystem.py          # read/write/edit/list operations
│   ├── web_search.py          # Brave Search integration
│   ├── http_client.py         # HTTP requests (URL policy enforced)
│   ├── python_exec.py         # Sandboxed Python execution
│   ├── subagent.py            # Sub-agent spawning
│   ├── cron.py                # Scheduled tasks (recurring, one-time, planned sequences)
│   ├── repo_map.py            # Repository structure analysis
│   ├── pr_generator.py        # Pull request generation
│   ├── security_analyzer.py   # Security vulnerability scanning
│   ├── security_audit.py      # Security posture auditing (36 checks)
│   ├── workflow_tool.py       # Multi-step workflows
│   ├── summarizer_tool.py     # Text/code summarization
│   ├── file_watcher.py        # File change monitoring
│   ├── browser_tool.py        # Web browsing + screenshots
│   ├── mcp_client.py          # MCP server tool proxying
│   ├── team_tool.py           # Multi-agent team orchestration
│   ├── content_analyzer.py    # Readability, tone, structure, SEO analysis
│   ├── data_tool.py           # CSV/JSON data loading + analysis
│   ├── template_tool.py       # Document templates with variable substitution
│   ├── outline_tool.py        # Structured document outlines
│   ├── scoring_tool.py        # Rubric-based content evaluation + improvement
│   ├── persona_tool.py        # Audience persona management
│   ├── image_gen.py           # AI image generation (free-first)
│   ├── video_gen.py           # AI video generation (async)
│   ├── ssh_tool.py            # SSH remote shell (asyncssh, host allowlist, SFTP)
│   ├── tunnel_tool.py         # Tunnel manager (cloudflared, serveo, localhost.run)
│   ├── knowledge_tool.py      # Knowledge base / RAG (import, chunk, query)
│   └── vision_tool.py         # Image analysis (Pillow compress, LLM vision API)
├── skills/
│   ├── loader.py              # Skill discovery, frontmatter parser, extension merging
│   └── builtins/              # Built-in skill templates (40 skills)
│       ├── github/            ├── code-review/     ├── debugging/
│       ├── testing/           ├── refactoring/     ├── documentation/
│       ├── git-workflow/      ├── security-audit/  ├── deployment/
│       ├── server-management/ ├── wordpress/       ├── docker-deploy/
│       ├── cms-deploy/        ├── memory/          ├── skill-creator/
│       ├── tool-creator/      ├── content-writing/ ├── design-review/
│       ├── seo/               ├── geo/             ├── social-media/
│       ├── brand-guidelines/  ├── email-marketing/ ├── competitive-analysis/
│       ├── strategy-analysis/ ├── data-analysis/   ├── project-planning/
│       ├── presentation/      ├── research/        ├── weather/
│       └── ... (40 total)
├── memory/
│   ├── store.py               # Structured memory + event log
│   ├── session.py             # Per-conversation session history (Redis-cached)
│   ├── embeddings.py          # Pluggable vector store + semantic search
│   ├── qdrant_store.py        # Qdrant vector DB backend (HNSW search, collections)
│   ├── redis_session.py       # Redis session cache + embedding cache
│   └── consolidation.py       # Conversation summarization pipeline
├── dashboard/
│   ├── server.py              # FastAPI + WebSocket server (setup wizard, auth, API)
│   ├── auth.py                # JWT + API key auth, bcrypt, rate limiting
│   ├── websocket_manager.py   # Real-time broadcast (device-tracked connections)
│   └── frontend/dist/         # SPA dashboard (vanilla JS, no build step)
│       ├── index.html         # Entry point
│       ├── app.js             # Full SPA (setup wizard, login, tasks, settings)
│       └── style.css          # Dark theme CSS
├── deploy/                    # Production deployment
│   ├── install-server.sh      # Full server setup (Redis, Qdrant, nginx, SSL, systemd, firewall)
│   └── nginx-agent42.conf     # Reverse proxy template (__DOMAIN__/__PORT__ placeholders)
├── data/                      # Runtime data (auto-created)
│   ├── model_catalog.json     # Cached OpenRouter free model catalog
│   ├── model_performance.json # Per-model outcome tracking
│   ├── model_research.json    # Web benchmark research scores
│   └── dynamic_routing.json   # Data-driven model routing overrides
├── tests/                     # 1000+ tests across 30+ test files
├── .github/workflows/         # CI/CD (test, lint, security)
├── Dockerfile                 # Container build (Python 3.12-slim)
├── docker-compose.yml         # Dev stack (Agent42 + Redis + Qdrant)
├── .env.example               # All configuration options (80+)
├── requirements.txt           # Production dependencies
├── requirements-dev.txt       # Dev dependencies (pytest, ruff, bandit, safety)
├── pyproject.toml             # Tool configuration (ruff, pytest, mypy)
├── Makefile                   # Common dev commands (test, lint, format, check)
├── tasks.json.example
├── setup.sh
└── uninstall.sh
```

## Deployment

### Systemd Service

```bash
sudo cp /tmp/agent42.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable agent42
sudo systemctl start agent42
sudo journalctl -u agent42 -f
```

### Docker (Development Stack)

Run Agent42 with Redis and Qdrant using Docker Compose:

```bash
cp .env.example .env
docker compose up -d             # Agent42 + Redis + Qdrant
docker compose logs -f agent42   # Follow logs
docker compose down              # Stop
```

The Docker stack includes Agent42, Redis (session cache + queue backend), and
Qdrant (vector semantic search). All three services are pre-configured to
communicate.

### Production VPS

For a full production deployment with Redis, Qdrant, nginx, SSL, systemd, and firewall:

```bash
scp -r agent42/ user@server:~/agent42
ssh user@server
cd ~/agent42
bash deploy/install-server.sh
```

The script prompts for your domain name (and optional port), then automatically:
- Runs `setup.sh` (venv, deps, frontend build)
- Installs Redis as a native systemd service (via apt)
- Installs Qdrant as a native systemd service (binary from GitHub releases)
- Configures `.env` with Redis/Qdrant URLs, JWT secret, and CORS
- Sets up nginx reverse proxy with rate limiting and security headers
- Obtains Let's Encrypt SSL certificates
- Installs the Agent42 systemd service
- Configures UFW firewall rules

After installation, open `https://yourdomain.com` in your browser to complete
setup through the wizard (password, API key).
See `deploy/install-server.sh` and `deploy/nginx-agent42.conf`.

## Uninstallation

Run the uninstall script from the Agent42 directory:

```bash
cd ~/agent42
bash uninstall.sh
```

The script automatically detects your deployment method (local, systemd,
Docker) and walks you through each removal step with confirmation prompts.
It offers to back up your `.env` file before removing it.

**What the script handles:**

- Stops running Agent42 processes (systemd service, Docker Compose stack)
- Removes Qdrant/Redis system services if installed by Agent42
- Removes standalone Qdrant/Redis Docker containers (if present)
- Removes the systemd service and reloads the daemon
- Removes nginx configuration and reloads nginx
- Optionally removes Let's Encrypt SSL certificates
- Removes UFW firewall rules
- Removes all runtime data (`.agent42/`, `data/`, `apps/`, logs)
- Removes the virtual environment and `.env`
- Optionally deletes the entire Agent42 directory

### What Gets Removed

| Component | Location | Created By |
|---|---|---|
| Virtual environment | `agent42/.venv/` | `setup.sh` |
| Configuration | `agent42/.env` | `setup.sh` / setup wizard |
| Runtime data | `agent42/.agent42/` | Agent42 at runtime |
| Model data | `agent42/data/` | Agent42 at runtime |
| User apps | `agent42/apps/` | Agent42 at runtime |
| Log file | `agent42/agent42.log` | systemd / Agent42 |
| Systemd service | `/etc/systemd/system/agent42.service` | `install-server.sh` |
| Nginx config | `/etc/nginx/sites-available/agent42` | `install-server.sh` |
| SSL certificates | `/etc/letsencrypt/live/yourdomain/` | certbot |
| Redis service | system package (`redis-server`) | `install-server.sh` |
| Qdrant service | `/etc/systemd/system/qdrant.service` | `install-server.sh` |
| Qdrant binary | `/usr/local/bin/qdrant` | `install-server.sh` |
| Qdrant data | `/var/lib/qdrant/` | `install-server.sh` |
| Docker volumes | `agent42-data`, `redis-data`, `qdrant-data` | `docker compose` |

If `setup.sh` installed Node.js via nvm and you no longer need it, remove it
manually after uninstalling:

```bash
rm -rf "$HOME/.nvm"
# Remove nvm lines from ~/.bashrc or ~/.zshrc
```

### Reinstalling

After uninstalling, follow the [Quick Start](#quick-start) instructions to
perform a fresh installation. If you backed up your `.env` file (the script
offers this), restore it after running `setup.sh` to preserve your API keys
and settings.

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

LLM provider API keys can be configured directly through the Settings page (admin only).
Other settings are displayed as read-only with their environment variable names and help text.

### First-Run Setup Wizard

On first launch (when no password is configured), the dashboard shows an
unauthenticated setup wizard instead of the login page:

1. Set a dashboard password (stored as bcrypt hash)
2. Optionally enter an OpenRouter API key
3. Optionally select an enhanced memory backend (Qdrant embedded or Qdrant + Redis)
4. Auto-generates `JWT_SECRET` and updates `.env`
5. Logs you in immediately (and queues a verification task if Qdrant + Redis was selected)

The wizard endpoint (`/api/setup/complete`) is only accessible when the password
is unset or still at the insecure default. Once setup is complete, the endpoint
is disabled.

### Multi-Device Access

Agent42 supports persistent API key authentication for multiple devices
(laptops, phones, tablets, scripts, CI/CD) alongside browser-based JWT auth.

- **Register a device** — `POST /api/devices/register` with a device name and
  type. Returns a one-time API key (prefix `ak_`) that must be saved immediately.
- **Device capabilities** — Each device can be granted `tasks` (create/view tasks),
  `approvals` (approve/deny agent actions), or `monitor` (read-only dashboard).
- **Authenticate** — Include `Authorization: Bearer ak_...` on any API request
  or WebSocket connection. Works alongside JWT auth.
- **Manage devices** — `GET /api/devices` lists all registered devices with
  online status. `DELETE /api/devices/{id}` revokes access instantly.

## Security (Contrariwise, Vogons Can't Get In)

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

### Scheduled Security Scanning

Agent42 can automatically scan the environment on a configurable interval
(default: every 8 hours) and report findings:

- **Config posture** — checks for insecure defaults (weak passwords, disabled sandbox, exposed dashboard)
- **Secret detection** — scans for leaked API keys, tokens, and credentials in code
- **Dependency scanning** — checks Python dependencies for known vulnerabilities
- **OWASP pattern matching** — detects common security anti-patterns

Findings can be automatically reported as GitHub issues via the `gh` CLI.
Configure with `SECURITY_SCAN_ENABLED`, `SECURITY_SCAN_INTERVAL_HOURS`, and
related env vars.

### Production Recommendations

- Put nginx in front with HTTPS before making public (see `deploy/nginx-agent42.conf`)
- Set `JWT_SECRET` to a 64-char random string (the setup wizard does this automatically)
- Use `DASHBOARD_PASSWORD_HASH` (bcrypt) instead of plaintext `DASHBOARD_PASSWORD`
- Set `CORS_ALLOWED_ORIGINS` to your domain
- Set `MAX_DAILY_API_SPEND_USD` to cap API costs
- Keep `SANDBOX_ENABLED=true` and `WORKSPACE_RESTRICT=true`

---

*So long, and thanks for all the tasks.* 🐬

Named after the Answer to the Ultimate Question of Life, the Universe, and Everything.
Agent42 doesn't know the Question either, but it'll complete your sprint backlog while
the philosophers argue about it.

Built with Python. The language, not the snake. Though if you understand the reference,
you're our kind of people.

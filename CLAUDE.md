# CLAUDE.md — Agent42 Development Guide

## Quick Reference

```bash
source .venv/bin/activate        # Activate virtual environment
python agent42.py                # Start Agent42 (dashboard at http://localhost:8000)
python -m pytest tests/ -x -q    # Run tests (stop on first failure)
make lint                        # Run linter (ruff)
make format                      # Auto-format code (ruff)
make check                       # Run lint + tests together
make security                    # Run security scanning (bandit + safety)
```

## IMPORTANT: Document Your Fixes!

When you resolve a non-obvious bug or discover a new pitfall, you **MUST** add it to the
[Common Pitfalls](#common-pitfalls) table at the end of this document. This keeps the
knowledge base current and prevents future regressions.

Ask yourself: *"Would this have saved me time if it was documented?"* If yes, add it.

---

## Automated Development Workflow

This project uses automated hooks in the `.claude/` directory. These run automatically
during Claude Code sessions without manual activation.

### Active Hooks (Automatic)

| Hook | Trigger | Action |
|------|---------|--------|
| `context-loader.py` | UserPromptSubmit | Detects work type from file paths and keywords, loads relevant lessons and patterns |
| `security-monitor.py` | PostToolUse (Write/Edit) | Flags security-sensitive changes for review (sandbox, auth, command filter) |
| `test-validator.py` | Stop | Validates tests pass, checks new modules have test coverage |
| `learning-engine.py` | Stop | Records development patterns, vocabulary, and skill candidates |

### Hook Protocol

- Hooks receive JSON on stdin with `hook_event_name`, `project_dir`, and event-specific data
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow, exit code 2 = block (for PreToolUse hooks)

### How It Works

```
┌──────────────────────────────────────────────────────────────────┐
│  User Prompt Submitted                                           │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  context-loader.py (UserPromptSubmit)                            │
│  - Detects work type from file paths + keywords                  │
│  - Loads relevant lessons, patterns, standards from lessons.md   │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Claude Processes Request                                        │
│  (may use Write/Edit tools)                                      │
└──────────────┬──────────────────────────┬────────────────────────┘
               │                          │
               ▼                          ▼
┌──────────────────────────┐   ┌───────────────────────────────────┐
│  security-monitor.py     │   │  (other tool processing)          │
│  (PostToolUse Write/Edit)│   │                                   │
│  - Flags security risks  │   │                                   │
└──────────────────────────┘   └───────────────────────────────────┘
               │
               ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stop Event Triggers:                                            │
│  ├─ test-validator.py   — runs pytest, checks test coverage      │
│  └─ learning-engine.py  — records patterns, updates lessons.md   │
└──────────────────────────────────────────────────────────────────┘
```

### Available Agents (On-Demand)

| Agent | Use Case | Invocation |
|-------|----------|------------|
| security-reviewer | Audit security-sensitive code changes | Request security review |
| performance-auditor | Review async patterns, resource usage, timeouts | Ask about performance |

### Related Files

- `.claude/settings.json` — Hook configuration
- `.claude/lessons.md` — Accumulated patterns and vocabulary (referenced by hooks)
- `.claude/learned-patterns.json` — Auto-generated pattern data
- `.claude/agents/` — Specialized agent definitions

---

## Key Terminology

| Term | Meaning |
|------|---------|
| Orchestrator | The `Agent42` class in `agent42.py` — manages all subsystems |
| Agent | A per-task worker (`agents/agent.py`) that gets a worktree and runs iterations |
| Iteration Engine | Primary model → tool execution → critic review → revise loop |
| Model Router | Free-first strategy selecting models per task type, with 4-layer resolution |
| Model Catalog | `agents/model_catalog.py` — syncs free models from OpenRouter API |
| Model Evaluator | `agents/model_evaluator.py` — tracks task outcomes, ranks models by composite score |
| Model Researcher | `agents/model_researcher.py` — fetches benchmark scores from web leaderboards |
| Dynamic Routing | Data-driven model selection using outcome tracking + research scores |
| Trial System | Assigns unproven models to a % of tasks to gather performance data |
| Plugin Loader | `tools/plugin_loader.py` — auto-discovers custom Tool and ToolExtension subclasses from a directory |
| ToolContext | `tools/context.py` — dependency injection container for plugin tools and extensions |
| ToolExtension | ABC (`tools/base.py`) for augmenting an existing tool with extra parameters and pre/post hooks |
| ExtendedTool | Wrapper (`tools/base.py`) that combines a base Tool with one or more ToolExtensions |
| Skill | A `SKILL.md` package providing task-type-specific prompts and guidelines |
| Tool | An ABC-derived class (`tools/base.py`) with `execute()`, `name`, `description`, `parameters` |
| Provider | An LLM API backend (OpenRouter, OpenAI, etc.) via `ProviderSpec` |
| Sandbox | `WorkspaceSandbox` enforcing filesystem boundaries per agent |
| Command Filter | 6-layer deny-list + optional allowlist for shell command security |
| Approval Gate | Human-in-the-loop for protected actions (external API, git push, file delete, SSH connect, tunnel start) |
| Worktree | Git worktree per agent for isolated filesystem access |
| Free-First | Default routing uses $0 models via OpenRouter; premium only if admin configures |
| Spending Tracker | Daily API cost cap enforced across all providers |
| SSH Tool | Remote shell execution via `asyncssh` with host allowlist and approval gate |
| Tunnel Manager | Expose local ports via cloudflared/serveo/localhost.run with TTL auto-expiry |
| Knowledge Base | RAG tool for importing documents, chunking, and semantic query via embeddings |
| Vision Tool | Image analysis using LLM vision APIs with Pillow compression |
| App | A self-contained user application built by Agent42, managed via `AppManager` |
| App Manager | `core/app_manager.py` — creates, builds, runs, stops, and serves user apps |
| App Tool | `tools/app_tool.py` — agent-facing interface for app lifecycle management |
| App Builder | Skill (`skills/builtins/app-builder/`) guiding agents through full app creation |
| App Runtime | How an app runs: `static`, `python`, `node`, or `docker` |
| App Mode | `internal` (Agent42 system tool) or `external` (app being developed for public release) |
| App Visibility | `private` (dashboard-only), `unlisted` (anyone with URL), `public` (listed openly) |
| App API | Agent-to-app HTTP interaction — lets Agent42 call a running app's endpoints via `app_api` |

---

## Project Structure

```
agent42/
├── agent42.py              # Main orchestrator entry point (Agent42 class)
├── CLAUDE.md               # This file — development guide
├── README.md               # User-facing docs, quick start, architecture
├── setup.sh                # Local setup script (venv, deps, .env, systemd template)
├── uninstall.sh            # Uninstall script (auto-detects deployment, removes all artifacts)
├── requirements.txt        # Production Python dependencies
├── requirements-dev.txt    # Development dependencies (testing, linting, security)
├── pyproject.toml          # Tool configuration (ruff, pytest, mypy)
├── Makefile                # Common dev commands
├── Dockerfile              # Container build
├── docker-compose.yml      # Dev stack (Agent42 + Redis + Qdrant)
├── .env.example            # Configuration template (70+ settings)
├── .gitignore              # Git exclusions
├── .pre-commit-config.yaml # Pre-commit hooks (ruff, bandit, file checks)
│
├── agents/                 # Agent pipeline
│   ├── agent.py            # Per-task orchestration with worktree, skills, memory
│   ├── iteration_engine.py # Primary→Tools→Critic→Revise loop with convergence
│   ├── model_router.py     # 4-layer model selection (admin→dynamic→trial→default)
│   ├── model_catalog.py    # OpenRouter catalog sync, free model discovery
│   ├── model_evaluator.py  # Outcome tracking, composite scoring, trial system
│   ├── model_researcher.py # Web benchmark research (LMSys, HuggingFace, etc.)
│   └── learner.py          # Post-task reflection, failure analysis, skill creation
│
├── core/                   # Infrastructure and security
│   ├── config.py           # Frozen dataclass Settings loaded from env (70+ fields)
│   ├── task_queue.py       # PriorityQueue with JSON/Redis backends, TaskType enum
│   ├── sandbox.py          # Path resolution, traversal blocking, symlink defense
│   ├── command_filter.py   # 6-layer shell command filtering (structural, deny, etc.)
│   ├── approval_gate.py    # Human-in-the-loop for protected actions
│   ├── rate_limiter.py     # Per-agent per-tool sliding-window rate limits
│   ├── capacity.py         # Dynamic concurrency based on CPU/memory metrics
│   ├── worktree_manager.py # Git worktree lifecycle management
│   ├── security_scanner.py # Scheduled vulnerability scanning + GitHub issue reporting
│   ├── heartbeat.py        # Agent stall detection
│   ├── intent_classifier.py# LLM-based message classification
│   ├── device_auth.py      # Device registration and API key management
│   ├── key_store.py        # Admin-configured API key overrides
│   ├── portability.py      # Backup/restore/clone operations
│   ├── queue_backend.py    # Redis queue backend adapter
│   ├── notification_service.py # Webhook and email notifications
│   ├── url_policy.py       # URL allowlist/denylist for SSRF protection
│   ├── complexity.py       # Task complexity estimation
│   └── app_manager.py      # App lifecycle management (create, build, run, stop)
│
├── providers/              # LLM provider registry
│   └── registry.py         # ProviderSpec, ModelSpec, spending tracker, 6 providers
│
├── tools/                  # 42+ tool implementations
│   ├── base.py             # Tool ABC: name, description, parameters, execute()
│   ├── registry.py         # ToolRegistry with rate limiting integration
│   ├── context.py          # ToolContext dependency injection for plugin tools
│   ├── plugin_loader.py    # Auto-discovers custom Tool subclasses from directory
│   ├── shell.py            # Shell command execution (sandboxed)
│   ├── filesystem.py       # File operations (read, write, search)
│   ├── git_tool.py         # Git operations
│   ├── web_search.py       # Brave Search API integration
│   ├── browser_tool.py     # Headless browser automation
│   ├── http_client.py      # HTTP requests (URL policy enforced)
│   ├── docker_tool.py      # Docker container management
│   ├── python_exec.py      # Python code execution
│   ├── code_intel.py       # Code analysis and intelligence
│   ├── grep_tool.py        # File content search
│   ├── diff_tool.py        # Diff generation and patching
│   ├── linter_tool.py      # Code linting
│   ├── test_runner.py      # Test execution
│   ├── pr_generator.py     # Pull request generation
│   ├── repo_map.py         # Repository structure analysis
│   ├── mcp_client.py       # Model Context Protocol client
│   ├── security_audit.py   # Security posture auditing (36 checks)
│   ├── security_analyzer.py# Secrets, dependencies, OWASP scanning
│   ├── image_gen.py        # Image generation (FLUX, DALL-E, Replicate)
│   ├── video_gen.py        # Video generation (Luma)
│   ├── content_analyzer.py # Content analysis
│   ├── scoring_tool.py     # Output quality scoring
│   ├── summarizer_tool.py  # Text summarization
│   ├── data_tool.py        # Data processing
│   ├── template_tool.py    # Template rendering
│   ├── persona_tool.py     # Persona application
│   ├── outline_tool.py     # Content outline generation
│   ├── cron.py             # Scheduled jobs (recurring, one-time, planned sequences)
│   ├── file_watcher.py     # File change monitoring
│   ├── dependency_audit.py # Dependency vulnerability checking
│   ├── subagent.py         # Sub-agent spawning
│   ├── team_tool.py        # Team management operations
│   ├── workflow_tool.py    # Workflow automation
│   ├── dynamic_tool.py     # Runtime tool generation
│   ├── ssh_tool.py         # SSH remote shell (asyncssh, host allowlist, SFTP)
│   ├── tunnel_tool.py      # Tunnel manager (cloudflared, serveo, localhost.run)
│   ├── knowledge_tool.py   # Knowledge base / RAG (import, chunk, query)
│   ├── vision_tool.py      # Image analysis (Pillow compress, LLM vision API)
│   └── app_tool.py         # App lifecycle management tool (create, start, stop)
│
├── skills/                 # Pluggable skill system
│   ├── loader.py           # SKILL.md discovery, YAML frontmatter parsing
│   └── builtins/           # 39 built-in skills
│       ├── api-design/     ├── code-review/    ├── debugging/
│       ├── deployment/     ├── documentation/  ├── git-workflow/
│       ├── github/         ├── marketing/      ├── monitoring/
│       ├── performance/    ├── refactoring/    ├── research/
│       ├── security-audit/ ├── testing/        ├── tool-creator/
│       ├── skill-creator/  ├── memory/
│       ├── server-management/ # LAMP/LEMP, nginx, systemd, firewall
│       ├── wordpress/      # WP-CLI, wp-config, themes, plugins, multisite
│       ├── docker-deploy/  # Dockerfile, docker-compose, registry workflows
│       ├── cms-deploy/     # Ghost, Strapi, general CMS patterns
│       ├── app-builder/   # Build complete web apps from descriptions
│       └── ... (40 total)
│
├── memory/                 # Persistence and semantic search
│   ├── store.py            # MEMORY.md + HISTORY.md two-layer pattern
│   ├── embeddings.py       # Vector embedding with optional Qdrant/Redis
│   ├── session.py          # Session management
│   ├── qdrant_store.py     # Qdrant vector DB adapter
│   ├── redis_session.py    # Redis session adapter
│   └── consolidation.py    # Memory consolidation pipeline
│
├── dashboard/              # Web UI
│   ├── server.py           # FastAPI app with REST + WebSocket
│   ├── auth.py             # JWT + API key auth, bcrypt, rate limiting
│   └── websocket_manager.py# Broadcast manager for real-time updates
│
├── channels/               # Communication integrations
│   ├── base.py             # Channel ABC
│   ├── manager.py          # Channel lifecycle management
│   ├── discord_channel.py  # Discord bot integration
│   ├── slack_channel.py    # Slack bot (Socket Mode)
│   ├── telegram_channel.py # Telegram bot
│   └── email_channel.py    # IMAP/SMTP email integration
│
├── deploy/                 # Production deployment
│   ├── install-server.sh   # Full server setup (Redis, Qdrant, nginx, SSL, systemd, firewall)
│   └── nginx-agent42.conf  # Reverse proxy template (__DOMAIN__/__PORT__ placeholders)
│
├── apps/                   # User-created applications (auto-created)
│   ├── <app-id>/           # Each app in its own directory
│   │   ├── APP.json        # App manifest (metadata, runtime, config)
│   │   ├── src/            # Application source code
│   │   └── public/         # Static assets (for static runtime)
│   └── apps.json           # App registry (metadata for all apps)
│
├── data/                   # Runtime data (auto-created)
│   ├── model_catalog.json  # Cached OpenRouter free model catalog
│   ├── model_performance.json # Per-model outcome tracking stats
│   ├── model_research.json # Web benchmark research scores
│   └── dynamic_routing.json# Data-driven model routing overrides
│
├── tests/                  # Test suite (31 files)
│   ├── conftest.py         # Shared fixtures (sandbox, tool_registry, mock_tool)
│   └── test_*.py           # Per-module test files
│
├── .github/workflows/      # CI/CD
│   ├── test.yml            # pytest across Python 3.11-3.13
│   ├── lint.yml            # ruff check + format
│   └── security.yml        # bandit + safety + security tests
│
└── .claude/                # Claude Code development hooks
    ├── settings.json       # Hook configuration
    ├── lessons.md          # Accumulated patterns and fixes
    ├── learned-patterns.json # Auto-generated pattern data
    ├── hooks/
    │   ├── context-loader.py    # Work type detection + context loading
    │   ├── security-monitor.py  # Security change flagging
    │   ├── test-validator.py    # Test gate
    │   └── learning-engine.py   # Pattern recording
    └── agents/
        ├── security-reviewer.md # Security audit agent
        └── performance-auditor.md # Performance review agent
```

---

## Architecture Patterns

### All I/O is Async

Every file operation uses `aiofiles`, every HTTP call uses `httpx` or `openai.AsyncOpenAI`,
every queue operation is `asyncio`-native. **Never use blocking I/O** in tool implementations.

```python
# CORRECT
async with aiofiles.open(path, "r") as f:
    content = await f.read()

# WRONG — blocks the event loop
with open(path, "r") as f:
    content = f.read()
```

### Frozen Dataclass Configuration

`Settings` is a frozen dataclass loaded once from environment at import time (`core/config.py`).
When adding new configuration:
1. Add field to `Settings` class with default
2. Add `os.getenv()` call in `Settings.from_env()`
3. Add to `.env.example` with documentation

```python
# Boolean fields use this pattern:
sandbox_enabled=os.getenv("SANDBOX_ENABLED", "true").lower() in ("true", "1", "yes")

# Comma-separated fields have get_*() helper methods:
def get_discord_guild_ids(self) -> list[int]: ...
```

### Plugin Architecture

**Tools (built-in):** Subclass `tools.base.Tool`, implement `name`/`description`/`parameters`/`execute()`,
register in `agent42.py` `_register_tools()`.

```python
class MyTool(Tool):
    @property
    def name(self) -> str: return "my_tool"
    @property
    def description(self) -> str: return "Does something useful"
    @property
    def parameters(self) -> dict:
        return {"type": "object", "properties": {"input": {"type": "string"}}}
    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        return ToolResult(output=f"Result: {input}")
```

**Tools (custom plugins):** Drop a `.py` file into `CUSTOM_TOOLS_DIR` and it will be
auto-discovered at startup via `tools/plugin_loader.py`. No core code changes needed.
Tools declare dependencies via a `requires` class variable for `ToolContext` injection.

```python
# custom_tools/hello.py
from tools.base import Tool, ToolResult

class HelloTool(Tool):
    requires = ["workspace"]  # Injects workspace from ToolContext

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

**Tool extensions (custom plugins):** To *extend* an existing tool instead of
creating a new one, subclass `ToolExtension` instead of `Tool`.  Extensions add
parameters and pre/post execution hooks without replacing the base tool.  Multiple
extensions can layer onto one base — just like skills.

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

**Skills:** Create a directory with `SKILL.md` containing YAML frontmatter:

```markdown
---
name: my-skill
description: One-line description of what this skill does.
always: false
task_types: [coding, debugging]
---

# My Skill

Instructions for the agent when this skill is active...
```

**Providers:** Add `ProviderSpec` to `PROVIDERS` dict and `ModelSpec` entries to `MODELS`
dict in `providers/registry.py`.

### Graceful Degradation

Redis, Qdrant, channels, and MCP servers are all optional. Code **must** handle their
absence with fallback behavior, never with crashes.

```python
# CORRECT — conditional import and check
if settings.redis_url:
    from memory.redis_session import RedisSessionStore
    session_store = RedisSessionStore(settings.redis_url)
else:
    session_store = FileSessionStore(settings.sessions_dir)

# WRONG — crashes if Redis isn't installed
from memory.redis_session import RedisSessionStore
```

### Dynamic Model Routing (4-Layer)

Model selection in `model_router.py` uses a 4-layer resolution chain:

1. **Admin override** — `AGENT42_{TYPE}_MODEL` env vars (highest priority)
2. **Dynamic routing** — `data/dynamic_routing.json` written by `ModelEvaluator` based on outcome data
3. **Trial injection** — Unproven models randomly assigned (`MODEL_TRIAL_PERCENTAGE`, default 10%)
4. **Hardcoded defaults** — `FREE_ROUTING` dict (lowest priority fallback)

**Never hardcode premium models as defaults.** The dynamic system self-improves:
- `ModelCatalog` syncs free models from OpenRouter API (default every 24h)
- `ModelEvaluator` tracks success rate, iteration efficiency, and critic scores per model
- `ModelResearcher` fetches benchmark scores from LMSys Arena, HuggingFace, Artificial Analysis
- Composite score: `0.4*success_rate + 0.3*iteration_efficiency + 0.2*critic_avg + 0.1*research_score`

### Security Layers (Defense in Depth)

| Layer | Module | Purpose |
|-------|--------|---------|
| 1 | `WorkspaceSandbox` | Path resolution, traversal blocking, symlink defense |
| 2 | `CommandFilter` | 6-layer shell command filtering (structural, deny, interpreter, metachar, indirect, allowlist) |
| 3 | `ApprovalGate` | Human review for protected actions |
| 4 | `ToolRateLimiter` | Per-agent per-tool sliding window |
| 5 | `URLPolicy` | Allowlist/denylist for HTTP requests (SSRF protection) |
| 6 | `BrowserGatewayToken` | Per-session token for browser tool |
| 7 | `SpendingTracker` | Daily API cost cap across all providers |
| 8 | `LoginRateLimit` | Per-IP brute force protection on dashboard |

---

## Configuration Reference

### Required Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `OPENROUTER_API_KEY` | OpenRouter API key (free tier available) | *(none)* |
| `DASHBOARD_PASSWORD` | Dashboard login password | *(none — login disabled)* |

### Security Settings

| Variable | Purpose | Default | Warning |
|----------|---------|---------|---------|
| `SANDBOX_ENABLED` | Enforce filesystem boundaries | `true` | Never disable in production |
| `COMMAND_FILTER_MODE` | Shell filtering mode | `deny` | `allowlist` for strict production |
| `JWT_SECRET` | JWT signing key | *(auto-generated)* | Set explicitly for persistent sessions |
| `DASHBOARD_HOST` | Dashboard bind address | `127.0.0.1` | Never use `0.0.0.0` without nginx |
| `DASHBOARD_PASSWORD_HASH` | Bcrypt password hash | *(none)* | Use instead of plaintext password |
| `MAX_DAILY_API_SPEND_USD` | Daily API spending cap | `0` (unlimited) | Set a cap for production |

### Tool Plugin Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `CUSTOM_TOOLS_DIR` | Directory for auto-discovered custom tool plugins | *(disabled)* |

### Dynamic Model Routing Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `MODEL_ROUTING_FILE` | Path to dynamic routing data | `data/dynamic_routing.json` |
| `MODEL_CATALOG_REFRESH_HOURS` | OpenRouter catalog sync interval | `24` |
| `MODEL_TRIAL_PERCENTAGE` | % of tasks assigned to unproven models | `10` |
| `MODEL_MIN_TRIALS` | Minimum completions before model is ranked | `5` |
| `MODEL_RESEARCH_ENABLED` | Enable web benchmark research | `true` |
| `MODEL_RESEARCH_INTERVAL_HOURS` | Research fetch interval | `168` (weekly) |

### Optional Backends

| Variable | Purpose | Default |
|----------|---------|---------|
| `REDIS_URL` | Redis for session cache + queue | *(disabled)* |
| `QDRANT_URL` | Qdrant for vector semantic search | *(disabled)* |
| `QDRANT_ENABLED` | Enable Qdrant (auto if URL set) | `false` |

See `.env.example` for the complete list of configuration variables.
### SSH & Tunnel Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `SSH_ENABLED` | Enable SSH remote shell tool | `false` |
| `SSH_ALLOWED_HOSTS` | Comma-separated host patterns | *(empty — all blocked)* |
| `SSH_DEFAULT_KEY_PATH` | Default private key path | *(none)* |
| `SSH_MAX_UPLOAD_MB` | Max SFTP upload size | `50` |
| `SSH_COMMAND_TIMEOUT` | Per-command timeout (seconds) | `120` |
| `TUNNEL_ENABLED` | Enable tunnel manager tool | `false` |
| `TUNNEL_PROVIDER` | auto, cloudflared, serveo, localhost.run | `auto` |
| `TUNNEL_ALLOWED_PORTS` | Comma-separated allowed ports | *(empty — all allowed)* |
| `TUNNEL_TTL_MINUTES` | Auto-shutdown TTL | `60` |

### Knowledge & Vision Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `KNOWLEDGE_DIR` | Document storage directory | `.agent42/knowledge` |
| `KNOWLEDGE_CHUNK_SIZE` | Chunk size in tokens | `500` |
| `KNOWLEDGE_CHUNK_OVERLAP` | Overlap between chunks | `50` |
| `KNOWLEDGE_MAX_RESULTS` | Max results per query | `10` |
| `VISION_MAX_IMAGE_MB` | Max image file size | `10` |
| `VISION_MODEL` | Override model for vision tasks | *(auto-detect)* |

### Apps Platform Settings

| Variable | Purpose | Default |
|----------|---------|---------|
| `APPS_ENABLED` | Enable the apps platform | `true` |
| `APPS_DIR` | Base directory for all apps | `apps` |
| `APPS_PORT_RANGE_START` | Dynamic port allocation start | `9100` |
| `APPS_PORT_RANGE_END` | Dynamic port allocation end | `9199` |
| `APPS_MAX_RUNNING` | Max simultaneously running apps | `5` |
| `APPS_AUTO_RESTART` | Restart crashed apps | `true` |
| `APPS_MONITOR_INTERVAL` | Seconds between health-check polls | `15` |
| `APPS_DEFAULT_RUNTIME` | Default runtime for new apps | `python` |
| `APPS_GIT_ENABLED_DEFAULT` | Enable git for new apps by default | `false` |
| `APPS_GITHUB_TOKEN` | GitHub PAT for repo creation/push | *(disabled)* |
| `APPS_DEFAULT_MODE` | Default mode for new apps (`internal`/`external`) | `internal` |
| `APPS_REQUIRE_AUTH_DEFAULT` | Require dashboard auth by default for new apps | `false` |

See `.env.example` for the complete list of 80+ configuration variables.

---

## Security Requirements

These rules are **non-negotiable** for a platform that runs AI agents on people's servers:

1. **NEVER** disable sandbox in production (`SANDBOX_ENABLED=true`)
2. **ALWAYS** use bcrypt password hash, not plaintext (`DASHBOARD_PASSWORD_HASH`)
3. **ALWAYS** set `JWT_SECRET` to a persistent value (auto-generated secrets break sessions across restarts)
4. **NEVER** expose `DASHBOARD_HOST=0.0.0.0` without nginx/firewall in front
5. **ALWAYS** run with `COMMAND_FILTER_MODE=deny` (default) or `COMMAND_FILTER_MODE=allowlist`
6. **REVIEW** `URL_DENYLIST` to block internal network ranges (`169.254.x.x`, `10.x.x.x`, etc.)
7. **NEVER** log API keys, passwords, or tokens — even at DEBUG level
8. **ALWAYS** validate file paths through `sandbox.resolve_path()` before file operations

---

## Adding New Components

### New Tool (Built-in)

1. Create `tools/my_tool.py` with class inheriting from `Tool` ABC
2. Implement required properties: `name`, `description`, `parameters`
3. Implement `async execute(**kwargs) -> ToolResult`
4. Register in `agent42.py` `_register_tools()`:
   ```python
   from tools.my_tool import MyTool
   registry.register(MyTool(sandbox=self._sandbox))
   ```
5. Create `tests/test_my_tool.py` with tests
6. Run: `python -m pytest tests/test_my_tool.py -v`

### New Tool (Custom Plugin — no core changes)

1. Set `CUSTOM_TOOLS_DIR=custom_tools` in `.env`
2. Create `custom_tools/my_tool.py` with a `Tool` subclass
3. Add `requires = ["sandbox", "workspace"]` class var for dependency injection
4. Tool is auto-discovered and registered at startup via `PluginLoader`
5. Tool name must match `^[a-z][a-z0-9_]{1,48}$`; duplicates are skipped

### New Skill

1. Create `skills/builtins/my-skill/SKILL.md` with YAML frontmatter
2. Set `task_types` to match relevant `TaskType` enum values
3. Set `always: true` only if the skill should load for every task
4. Optionally add `requirements_bins` for CLI tool dependencies

### New Provider

1. Add `ProviderSpec` to `PROVIDERS` dict in `providers/registry.py`
2. Add `ModelSpec` entries to `MODELS` dict for each supported model
3. Add API key field to `Settings` in `core/config.py`
4. Add `os.getenv()` call in `Settings.from_env()`
5. Add to `.env.example` with documentation

### New Config Field

1. Add field to `Settings` class with sensible default
2. Add `os.getenv()` call in `Settings.from_env()` with type conversion
3. Add to `.env.example` with description
4. For boolean fields: use `.lower() in ("true", "1", "yes")` pattern
5. For comma-separated lists: add `get_*()` helper method

---

## Development Workflow

### Before Writing Code

1. Run tests to confirm green baseline: `python -m pytest tests/ -x -q`
2. Check if related test files exist for the module you're changing
3. Read the module's docstring and understand the pattern
4. For security-sensitive files, read `.claude/lessons.md` security section

### After Writing Code

1. Run the formatter: `make format` (or `ruff format .`)
2. Run the full test suite: `python -m pytest tests/ -x -q`
3. Run linter: `make lint`
4. For security-sensitive changes: `python -m pytest tests/test_security.py tests/test_sandbox.py tests/test_command_filter.py -v`
5. Update this CLAUDE.md pitfalls table if you discovered a non-obvious issue
6. For new modules: ensure a corresponding `tests/test_*.py` file exists
7. Update README.md if new features, skills, tools, or config were added

---

## Testing Standards

**Always install dependencies before running tests.** Tests should always be
runnable — if a dependency is missing, install it rather than skipping the test:

```bash
pip install -r requirements.txt            # Full production dependencies
pip install -r requirements-dev.txt        # Dev/test tooling (pytest, ruff, etc.)
# If the venv is missing, install at minimum:
pip install pytest pytest-asyncio aiofiles openai fastapi python-jose bcrypt cffi
```

Run tests:
```bash
python -m pytest tests/ -x -q              # Quick: stop on first failure
python -m pytest tests/ -v                  # Verbose: see all test names
python -m pytest tests/test_security.py -v  # Single file
python -m pytest tests/ -k "test_sandbox"   # Filter by name
python -m pytest tests/ -m security         # Filter by marker
```

Some tests require `fastapi`, `python-jose`, `bcrypt`, and `redis` — install the full
`requirements.txt` to avoid import errors. If the `cryptography` backend fails with
`_cffi_backend` errors, install `cffi` (`pip install cffi`).

### Test Writing Rules

- Every new module in `core/`, `agents/`, `tools/`, `providers/` needs a `tests/test_*.py` file
- Use `pytest-asyncio` for async tests (configured as `asyncio_mode = "auto"` in pyproject.toml)
- Use `tmp_path` fixture (or conftest.py `tmp_workspace`) for filesystem tests — never hardcode `/tmp` paths
- Use class-based organization: `class TestClassName` with `setup_method`
- Mock external services (LLM calls, Redis, Qdrant) — never hit real APIs in tests
- Use conftest.py fixtures: `sandbox`, `command_filter`, `tool_registry`, `mock_tool`
- Name tests descriptively: `test_<function>_<scenario>_<expected>`

```python
class TestWorkspaceSandbox:
    def setup_method(self):
        self.sandbox = WorkspaceSandbox(tmp_path, enabled=True)

    def test_block_path_traversal(self):
        with pytest.raises(SandboxViolation):
            self.sandbox.resolve_path("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_async_tool_execution(self):
        result = await tool.execute(input="test")
        assert result.success
```

---

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Files | `snake_case.py` | `task_queue.py`, `model_router.py` |
| Classes | `PascalCase` | `TaskQueue`, `ModelRouter` |
| Tools | `PascalCase` + `Tool` suffix | `ShellTool`, `GitTool` |
| Skills | `kebab-case` directories | `code-review/`, `security-audit/` |
| Tests | `test_{module}.py` / `class TestClassName` | `test_sandbox.py` / `TestWorkspaceSandbox` |
| Config env vars | `UPPER_SNAKE_CASE` | `MAX_CONCURRENT_AGENTS` |
| Loggers | `"agent42.{module}"` namespace | `logging.getLogger("agent42.tools.shell")` |

---

## Commit Guidelines

Use conventional commit prefixes:

| Prefix | Use For |
|--------|---------|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `refactor:` | Code restructuring (no behavior change) |
| `test:` | Adding or updating tests |
| `docs:` | Documentation changes |
| `chore:` | Build process, dependencies, CI |
| `security:` | Security fix or hardening |

**Format:** `{prefix} Brief description of the change`

**Examples** (from actual project history):
```
feat: priority queue, Redis backend, and spending limit enforcement
fix: 7 bugs: 3 critical startup crashes, 4 major logic/security gaps
security: add 6-layer command filter with deny patterns
chore: add CI workflows for testing, linting, and security scanning
```

Include *what* and *why*, not just *what*.

---

## Deployment

### Development (Local)

```bash
git clone <repo> agent42 && cd agent42
bash setup.sh                    # Creates .venv, installs deps, builds frontend
source .venv/bin/activate
python agent42.py                # http://localhost:8000
# Open browser — setup wizard handles password, API key, and memory
```

### Production (Server)

```bash
scp -r agent42/ user@server:~/agent42
ssh user@server
cd ~/agent42
bash deploy/install-server.sh    # Prompts for domain, installs Redis + Qdrant + nginx + SSL + systemd
# Open https://yourdomain.com — setup wizard handles password and API key
```

The install script handles: setup.sh, Redis (apt), Qdrant (binary + systemd),
nginx reverse proxy (templated), Let's Encrypt SSL, Agent42 systemd service,
UFW firewall. Redis and Qdrant URLs are pre-configured in .env.

**Service commands:**
```bash
sudo systemctl start agent42     # Start
sudo systemctl restart agent42   # Restart
sudo systemctl status agent42    # Status
sudo journalctl -u agent42 -f   # Live logs
```

### Docker (Development Stack)

```bash
cp .env.example .env && nano .env
docker compose up -d             # Agent42 + Redis + Qdrant
docker compose logs -f agent42   # Logs
docker compose down              # Stop
```

---

## Common Pitfalls

| # | Area | Pitfall | Correct Pattern |
|---|------|---------|-----------------|
| 1 | Config | Adding env var but not to `Settings` dataclass | Add to `Settings` + `from_env()` + `.env.example` |
| 2 | Async | Using blocking I/O (`open()`) in tools | Use `aiofiles.open()` for all file operations |
| 3 | Security | Disabling sandbox for convenience | Keep `SANDBOX_ENABLED=true`; use `resolve_path()` |
| 4 | Tools | Forgetting to register new tool | Add to `_register_tools()` in `agent42.py` |
| 5 | Tests | Hardcoding `/tmp` paths in tests | Use `tmp_path` fixture for test isolation |
| 6 | Providers | Hardcoding premium model as default | Use `FREE_ROUTING` dict, allow admin override via env |
| 7 | Memory | Not handling missing Qdrant/Redis | Check availability before use; fallback to files |
| 8 | Config | `DASHBOARD_HOST=0.0.0.0` exposed directly | Keep `127.0.0.1`; use nginx for external access |
| 9 | JWT | Not setting `JWT_SECRET` in `.env` | Random secret breaks sessions across restarts |
| 10 | Import | Importing optional deps at module level | Conditional import inside function/method body |
| 11 | Tools | Missing `**kwargs` in `execute()` signature | Always include `**kwargs` for forward compatibility |
| 12 | Security | Logging API keys or tokens | Never log secrets — even at DEBUG level |
| 13 | Shell | Using `subprocess.run(shell=True)` in tools | Route through `CommandFilter` and `Sandbox` |
| 14 | Config | Boolean env vars with wrong parsing | Use `.lower() in ("true", "1", "yes")` pattern |
| 15 | Tasks | Using wrong `TaskType` enum value | Check `core/task_queue.py` for valid values |
| 16 | Catalog | `CatalogEntry.to_dict()` format mismatch with `__init__` | `to_dict()` must output `{"id": ..., "pricing": {"prompt": ..., "completion": ...}}` matching constructor format |
| 17 | Tests | Floating-point equality in composite scores | Use `pytest.approx()` for float comparisons, not `==` |
| 18 | Init Order | `ModelEvaluator` must init before `Learner` | Learner takes `model_evaluator` param — ensure correct order in `agent42.py` |
| 19 | Extensions | `ToolExtension.extends` must match an already-registered tool name | Extensions for nonexistent tools are silently skipped with a warning |
| 20 | Tests | `cryptography` panics with `_cffi_backend` error | Install `cffi` (`pip install cffi`) before running dashboard/auth tests |
| 21 | Apps | App entry point missing PORT/HOST env var reading | Always read `os.environ.get("PORT", "8080")` — AppManager sets these |
| 22 | Apps | New `TaskType` not in `FREE_ROUTING` dict | Add routing entry to `agents/model_router.py` `FREE_ROUTING` for every new TaskType |
| 23 | Formatting | CI fails with `ruff format --check` after merge | Always run `make format` (or `ruff format .`) before committing — especially after merges that touch multiple files |
| 24 | Deploy | Hardcoded domain/port in install scripts and nginx config | Use `__DOMAIN__`/`__PORT__` placeholders in `nginx-agent42.conf`; `install-server.sh` prompts for values and sed-replaces |
| 25 | Deploy | Install scripts leak interactive output when composed | Use `--quiet` flag when calling `setup.sh` from `install-server.sh` to suppress banners and prompts |
| 26 | Dashboard | CSP `script-src 'self'` blocks all inline event handlers (`onclick`, `onsubmit`) | CSP must include `'unsafe-inline'` in `script-src` because `app.js` uses innerHTML with 55+ inline handlers |
| 27 | Startup | `agent42.log` owned by root (from systemd) blocks `deploy` user startup | Catch `PermissionError` on `FileHandler`; fall back to stdout-only logging |
| 28 | Auth | `passlib 1.7.4` crashes with `bcrypt >= 4.1` (wrap-bug detection hashes >72-byte secret) | Use `bcrypt` directly via `_BcryptContext` wrapper in `dashboard/auth.py`; do not use `passlib` |
| 29 | Formatting | Inline `from` imports inside functions/methods trigger ruff I001 if not isort-sorted | Third-party imports (e.g. `httpx`) must come before local imports (e.g. `core.*`, `dashboard.*`) with a blank line between — even inside function bodies; run `ruff check --fix` to auto-correct |

---

## Documentation Maintenance

**AI Assistant Instructions:** When working on this codebase, proactively update this
CLAUDE.md file when:

1. **New errors are resolved** — Add to "Common Pitfalls" table
2. **New terminology is introduced** — Add to "Key Terminology" table
3. **New tools are created** — Add to "Project Structure" tools section
4. **New skills are added** — Note in the skills section
5. **New patterns are established** — Add to "Architecture Patterns" section
6. **Configuration changes** — Update "Configuration Reference" section
7. **README changes** — Update README.md when adding features, skills, tools, or providers

**When to update:**
- After successfully resolving a non-obvious error
- When discovering undocumented conventions
- After creating new tools, skills, or providers
- When server or deployment configuration changes

**Format:** Keep updates concise and consistent with existing table/list formats.

# Project Structure

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
│   ├── app_manager.py      # App lifecycle management (create, build, run, stop)
│   ├── chat_session_manager.py # Multi-session chat persistence (JSONL per session)
│   ├── project_manager.py  # Project CRUD, task aggregation, Kanban board
│   ├── github_oauth.py     # GitHub OAuth device flow for repo creation
│   ├── interview_questions.py # Question banks for project discovery interviews
│   └── project_spec.py     # PROJECT_SPEC.md generator and subtask decomposer
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
│   ├── app_tool.py         # App lifecycle management tool (create, start, stop)
│   └── project_interview.py # Project discovery interview + spec generation
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
│       ├── project-interview/ # Structured discovery interviews + spec generation
│       └── ... (41 total)
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
    ├── reference/          # On-demand reference docs (loaded by context-loader hook)
    ├── hooks/
    │   ├── context-loader.py    # Work type detection + context loading
    │   ├── security-monitor.py  # Security change flagging
    │   ├── test-validator.py    # Test gate
    │   └── learning-engine.py   # Pattern recording
    └── agents/
        ├── security-reviewer.md # Security audit agent
        └── performance-auditor.md # Performance review agent
```

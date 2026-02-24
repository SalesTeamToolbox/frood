# Key Terminology

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
| Token Accumulator | `TokenAccumulator` in `agents/iteration_engine.py` — collects per-model token usage during a task's iteration engine run |
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
| Scope Detection | Detects when a user's message changes topic from the active conversation scope, triggering a new branch/task |
| Active Scope | `ScopeInfo` in `core/intent_classifier.py` — tracks the current conversation topic per channel session |
| Scope Analysis | `ScopeAnalysis` in `core/intent_classifier.py` — result of scope change detection (continuation vs change) |
| Chat Session | A persistent named conversation (chat or code type) with JSONL message storage |
| Chat Session Manager | `core/chat_session_manager.py` — session CRUD, message persistence, auto-titling |
| Code Page | Coding-focused chat interface with project setup flow (local/remote deploy, GitHub repo) |
| Project | A higher-level grouping of related tasks with aggregate progress tracking |
| Project Manager | `core/project_manager.py` — project CRUD, task aggregation, Kanban board view |
| GitHub Device Auth | `core/github_oauth.py` — OAuth device flow for GitHub repo creation |
| Mission Control | Tabbed view ("Tasks" + "Projects") for managing work items and project progress |
| Project Interview | Structured discovery process (`tools/project_interview.py`) for complex project-level tasks |
| Project Spec | `PROJECT_SPEC.md` — central specification document produced by the interview, referenced by all subtasks |
| Interview Questions | `core/interview_questions.py` — question banks organized by project type and theme |
| Spec Generator | `core/project_spec.py` — synthesizes interview data into PROJECT_SPEC.md and decomposes into subtasks |
| PM Skill | `skills/builtins/project-interview/` — guides the agent through the interview workflow |

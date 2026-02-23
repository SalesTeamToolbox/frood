"""
agent42.py - The answer to life, the universe, and all your tasks.

Multi-agent orchestrator platform. Free models handle the iterative work;
premium APIs or human review gate the final output.

Now with:
- Channel gateway (Discord, Slack, Telegram, Email) — Phase 2
- Skills framework (SKILL.md dynamic loading) — Phase 3
- Tool ecosystem (MCP, web search, cron, subagents) — Phase 4
- 8 LLM providers with 20+ models — Phase 5
- Persistent memory system — Phase 6

Usage:
    python agent42.py                     # Start with defaults
    python agent42.py --port 8080         # Custom dashboard port
    python agent42.py --repo /path/to     # Specify repo path
    python agent42.py --no-dashboard      # Headless mode (terminal only)
    python agent42.py --max-agents 2      # Limit concurrent agents

Dashboard: http://localhost:8000 (default)
"""

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

from agents.agent import Agent
from agents.learner import Learner
from agents.model_router import ModelRouter
from channels.base import InboundMessage, OutboundMessage
from channels.manager import ChannelManager
from core.app_manager import AppManager
from core.approval_gate import ApprovalGate
from core.capacity import compute_effective_capacity
from core.command_filter import DEFAULT_ALLOWLIST, CommandFilter
from core.config import settings
from core.device_auth import DeviceStore
from core.heartbeat import HeartbeatService
from core.intent_classifier import IntentClassifier, PendingClarification
from core.key_store import KeyStore
from core.rate_limiter import ToolLimit, ToolRateLimiter
from core.sandbox import WorkspaceSandbox
from core.security_scanner import ScheduledSecurityScanner
from core.task_queue import Task, TaskQueue, TaskStatus, TaskType, infer_task_type
from core.worktree_manager import WorktreeManager
from dashboard.auth import init_device_store
from dashboard.server import create_app
from dashboard.websocket_manager import WebSocketManager
from memory.consolidation import ConsolidationPipeline
from memory.qdrant_store import QdrantConfig, QdrantStore
from memory.redis_session import RedisConfig, RedisSessionBackend
from memory.session import SessionManager
from memory.store import MemoryStore
from skills.loader import SkillLoader
from tools.app_tool import AppTool
from tools.browser_tool import BrowserTool
from tools.code_intel import CodeIntelTool
from tools.content_analyzer import ContentAnalyzerTool
from tools.context import ToolContext
from tools.cron import CronScheduler, CronTool
from tools.data_tool import DataTool
from tools.dependency_audit import DependencyAuditTool
from tools.diff_tool import DiffTool
from tools.docker_tool import DockerTool
from tools.file_watcher import FileWatcherTool
from tools.filesystem import EditFileTool, ListDirTool, ReadFileTool, WriteFileTool
from tools.git_tool import GitTool
from tools.grep_tool import GrepTool
from tools.http_client import HttpClientTool
from tools.image_gen import ImageGenTool
from tools.knowledge_tool import KnowledgeTool
from tools.linter_tool import LinterTool
from tools.mcp_client import MCPManager
from tools.outline_tool import OutlineTool
from tools.persona_tool import PersonaTool
from tools.plugin_loader import PluginLoader
from tools.pr_generator import PRGeneratorTool
from tools.python_exec import PythonExecTool
from tools.registry import ToolRegistry
from tools.repo_map import RepoMapTool
from tools.scoring_tool import ScoringTool
from tools.security_analyzer import SecurityAnalyzerTool
from tools.shell import ShellTool
from tools.ssh_tool import SSHTool
from tools.subagent import SubagentTool
from tools.summarizer_tool import SummarizerTool
from tools.team_tool import TeamTool
from tools.template_tool import TemplateTool
from tools.test_runner import TestRunnerTool
from tools.tunnel_tool import TunnelTool
from tools.video_gen import VideoGenTool
from tools.vision_tool import VisionTool
from tools.web_search import WebFetchTool, WebSearchTool
from tools.workflow_tool import WorkflowTool

# -- Logging -------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

_log_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(logging.FileHandler("agent42.log"))
except PermissionError:
    print(
        "WARNING: Cannot write to agent42.log (permission denied) — logging to stdout only.",
        file=sys.stderr,
    )

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=_log_handlers)
logger = logging.getLogger("agent42")


class Agent42:
    """Core orchestrator — manages tasks, agents, channels, tools, and dashboard."""

    def __init__(
        self,
        repo_path: str | None = None,
        dashboard_port: int = 8000,
        headless: bool = False,
        max_agents: int | None = None,
    ):
        # Data directory: always the agent42 install dir (for memory, sessions, etc.)
        self.data_dir = Path(__file__).parent.resolve()
        # Repo path: optional, can be configured later via dashboard
        self.repo_path = Path(repo_path).resolve() if repo_path else self.data_dir
        self.has_repo = repo_path is not None and (Path(repo_path).resolve() / ".git").exists()
        self.dashboard_port = dashboard_port
        self.headless = headless
        self.max_agents = max_agents or settings.max_concurrent_agents

        # Core infrastructure — optional Redis-backed queue
        queue_backend = None
        if settings.redis_url:
            from core.queue_backend import RedisQueueBackend

            queue_backend = RedisQueueBackend(
                redis_url=settings.redis_url,
                redis_password=settings.redis_password,
                fallback_json_path=settings.tasks_json_path,
            )
        self.task_queue = TaskQueue(
            tasks_json_path=settings.tasks_json_path,
            backend=queue_backend,
        )
        self.ws_manager = WebSocketManager()
        self.worktree_manager = WorktreeManager(str(self.repo_path)) if self.has_repo else None
        self._active_count = 0
        self._active_lock = asyncio.Lock()
        self.approval_gate = ApprovalGate(
            self.task_queue,
            log_path=settings.approval_log_path,
        )
        self._shutdown_event = asyncio.Event()

        # Phase 1: Security
        self.sandbox = WorkspaceSandbox(self.repo_path, enabled=settings.sandbox_enabled)

        # Command filter: strict allowlist mode or default deny-list
        allowlist = None
        if settings.command_filter_mode == "allowlist":
            if settings.command_filter_allowlist:
                allowlist = [
                    p.strip() for p in settings.command_filter_allowlist.split(",") if p.strip()
                ]
            else:
                allowlist = list(DEFAULT_ALLOWLIST)
        self.command_filter = CommandFilter(allowlist=allowlist)

        # Phase 2: Channels
        self.channel_manager = ChannelManager()

        # Phase 3: Skills
        skill_dirs = [
            Path(__file__).parent / "skills" / "builtins",
            self.repo_path / "skills",
        ]
        for extra in settings.get_skills_dirs():
            skill_dirs.append(Path(extra))
        self.skill_loader = SkillLoader(skill_dirs)
        self.skill_loader.load_all()

        # Phase 4: Tools (with optional rate limiting)
        rate_limiter = None
        if settings.tool_rate_limiting_enabled:
            rate_limiter = ToolRateLimiter()
            if settings.tool_rate_limit_overrides:
                try:
                    overrides_raw = json.loads(settings.tool_rate_limit_overrides)
                    overrides = {name: ToolLimit(**spec) for name, spec in overrides_raw.items()}
                    rate_limiter.update_limits(overrides)
                except (json.JSONDecodeError, TypeError) as e:
                    logger.warning(f"Invalid TOOL_RATE_LIMIT_OVERRIDES: {e}")
        self.tool_registry = ToolRegistry(rate_limiter=rate_limiter)
        self.mcp_manager = MCPManager()
        self.cron_scheduler = CronScheduler(settings.cron_jobs_path)

        # Apps platform
        self.app_manager = (
            AppManager(
                apps_dir=settings.apps_dir,
                port_range_start=settings.apps_port_range_start,
                port_range_end=settings.apps_port_range_end,
                max_running=settings.apps_max_running,
                auto_restart=settings.apps_auto_restart,
                dashboard_port=dashboard_port,
            )
            if settings.apps_enabled
            else None
        )

        self._register_tools()

        # Phase 4b: Custom tool plugins (auto-discovery from CUSTOM_TOOLS_DIR)
        if settings.custom_tools_dir:
            tool_context = ToolContext(
                sandbox=self.sandbox,
                command_filter=self.command_filter,
                task_queue=self.task_queue,
                workspace=str(self.repo_path),
                tool_registry=self.tool_registry,
            )
            custom_dir = Path(settings.custom_tools_dir)
            if not custom_dir.is_absolute():
                custom_dir = self.data_dir / custom_dir
            self._custom_tools = PluginLoader.load_all(custom_dir, tool_context, self.tool_registry)
        else:
            self._custom_tools = []

        # Phase 6: Memory (with optional Qdrant + Redis backends)
        self._qdrant_store = None
        self._redis_backend = None

        if settings.qdrant_enabled:
            self._qdrant_store = QdrantStore(
                QdrantConfig(
                    url=settings.qdrant_url,
                    api_key=settings.qdrant_api_key,
                    collection_prefix=settings.qdrant_collection_prefix,
                    local_path=settings.qdrant_local_path,
                )
            )

        if settings.redis_url:
            self._redis_backend = RedisSessionBackend(
                RedisConfig(
                    url=settings.redis_url,
                    password=settings.redis_password,
                    session_ttl_days=settings.session_ttl_days,
                    embedding_cache_ttl_hours=settings.embedding_cache_ttl_hours,
                )
            )

        self.memory_store = MemoryStore(
            self.data_dir / settings.memory_dir,
            qdrant_store=self._qdrant_store,
            redis_backend=self._redis_backend,
        )

        consolidation = ConsolidationPipeline(
            model_router=ModelRouter(),
            embedding_store=self.memory_store.embeddings,
            qdrant_store=self._qdrant_store,
        )

        self.session_manager = SessionManager(
            self.data_dir / settings.sessions_dir,
            redis_backend=self._redis_backend,
            consolidation_pipeline=consolidation,
        )

        # Phase 10: Device gateway authentication
        self.device_store = DeviceStore(self.data_dir / settings.devices_file)
        init_device_store(self.device_store)

        # Admin-configured API keys (override .env values)
        self.key_store = KeyStore(self.data_dir / ".agent42" / "settings.json")
        self.key_store.inject_into_environ()

        # Dynamic model routing components (must be before Learner for injection)
        from agents.model_catalog import ModelCatalog
        from agents.model_evaluator import ModelEvaluator
        from agents.model_researcher import ModelResearcher

        data_dir = self.data_dir / "data"
        data_dir.mkdir(parents=True, exist_ok=True)

        self.model_catalog = ModelCatalog(
            cache_path=data_dir / "model_catalog.json",
            refresh_hours=settings.model_catalog_refresh_hours,
        )
        self.model_evaluator = ModelEvaluator(
            performance_path=data_dir / "model_performance.json",
            routing_path=self.data_dir / settings.model_routing_file,
            research_path=data_dir / "model_research.json",
            trial_percentage=settings.model_trial_percentage,
            min_trials=settings.model_min_trials,
        )
        self.model_researcher = (
            ModelResearcher(
                research_path=data_dir / "model_research.json",
                interval_hours=settings.model_research_interval_hours,
            )
            if settings.model_research_enabled
            else None
        )

        # Self-learning (with model evaluator for outcome tracking)
        self.workspace_skills_dir = self.data_dir / "skills" / "workspace"
        self.learner = Learner(
            router=ModelRouter(evaluator=self.model_evaluator),
            memory_store=self.memory_store,
            skills_dir=self.workspace_skills_dir,
            model_evaluator=self.model_evaluator,
        )

        # Phase 7: Heartbeat monitoring
        self.heartbeat = HeartbeatService(
            on_stall=self._on_agent_stall,
            on_heartbeat=self._on_heartbeat,
            configured_max_agents=self.max_agents,
        )

        # Scheduled security scanning
        self.security_scanner = ScheduledSecurityScanner(
            workspace_path=str(self.repo_path) if self.has_repo else str(self.data_dir),
            interval_seconds=settings.get_security_scan_interval_seconds(),
            min_severity=settings.security_scan_min_severity,
            github_issues_enabled=settings.security_scan_github_issues,
            memory_store=self.memory_store,
        )

        # Phase 9: Context-aware intent classification
        self.intent_classifier = IntentClassifier(router=ModelRouter())
        self._pending_clarifications: dict[str, PendingClarification] = {}

        # Wire up callbacks
        self.task_queue.on_update(self._on_task_update)

    def _register_tools(self):
        """Register all built-in tools."""
        workspace = str(self.repo_path)

        # Core tools
        self.tool_registry.register(ShellTool(self.sandbox, self.command_filter))
        self.tool_registry.register(ReadFileTool(self.sandbox))
        self.tool_registry.register(WriteFileTool(self.sandbox))
        self.tool_registry.register(EditFileTool(self.sandbox))
        self.tool_registry.register(ListDirTool(self.sandbox))
        self.tool_registry.register(WebSearchTool())
        self.tool_registry.register(WebFetchTool())
        self.tool_registry.register(CronTool(self.cron_scheduler))
        self.tool_registry.register(SubagentTool(self.task_queue))

        # Development tools
        self.tool_registry.register(GitTool(workspace))
        self.tool_registry.register(GrepTool(workspace))
        self.tool_registry.register(DiffTool(workspace))
        self.tool_registry.register(TestRunnerTool(workspace))
        self.tool_registry.register(LinterTool(workspace))
        self.tool_registry.register(HttpClientTool())

        # Advanced tools (from competitive analysis)
        self.tool_registry.register(BrowserTool(workspace))
        self.tool_registry.register(CodeIntelTool(workspace))
        self.tool_registry.register(DependencyAuditTool(workspace))
        self.tool_registry.register(DockerTool(workspace))
        self.tool_registry.register(PythonExecTool(workspace))
        self.tool_registry.register(RepoMapTool(workspace))
        self.tool_registry.register(PRGeneratorTool(workspace))
        self.tool_registry.register(SecurityAnalyzerTool(workspace))
        self.tool_registry.register(WorkflowTool(workspace, self.tool_registry))
        self.tool_registry.register(SummarizerTool(workspace))
        self.tool_registry.register(FileWatcherTool(workspace))

        # General-purpose tools (non-coding workflows)
        self.tool_registry.register(TeamTool(self.task_queue))
        self.tool_registry.register(ContentAnalyzerTool())
        self.tool_registry.register(DataTool())
        self.tool_registry.register(TemplateTool())
        self.tool_registry.register(OutlineTool())
        self.tool_registry.register(ScoringTool())
        self.tool_registry.register(PersonaTool())

        # Media generation tools (Phase 9)
        router = ModelRouter()
        self.tool_registry.register(ImageGenTool(router=router))
        self.tool_registry.register(VideoGenTool(router=router))

        # SSH remote shell (disabled by default — requires SSH_ENABLED=true)
        if settings.ssh_enabled:
            self.tool_registry.register(
                SSHTool(self.sandbox, self.command_filter, self.approval_gate)
            )

        # Tunnel manager (disabled by default — requires TUNNEL_ENABLED=true)
        if settings.tunnel_enabled:
            self.tool_registry.register(TunnelTool(self.approval_gate))

        # Knowledge base / RAG
        embedding_store = getattr(self, "embedding_store", None)
        self.tool_registry.register(KnowledgeTool(self.sandbox, embedding_store))

        # Vision / image analysis
        self.tool_registry.register(VisionTool(self.sandbox))

        # Apps platform (enabled by default)
        if self.app_manager:
            self.tool_registry.register(AppTool(self.app_manager))

    async def _setup_channels(self):
        """Configure and register enabled channels based on settings."""
        # Discord
        if settings.discord_bot_token:
            from channels.discord_channel import DiscordChannel

            self.channel_manager.register(
                DiscordChannel(
                    {
                        "bot_token": settings.discord_bot_token,
                        "guild_ids": settings.get_discord_guild_ids(),
                    }
                )
            )
            logger.info("Discord channel configured")

        # Slack
        if settings.slack_bot_token and settings.slack_app_token:
            from channels.slack_channel import SlackChannel

            self.channel_manager.register(
                SlackChannel(
                    {
                        "bot_token": settings.slack_bot_token,
                        "app_token": settings.slack_app_token,
                    }
                )
            )
            logger.info("Slack channel configured")

        # Telegram
        if settings.telegram_bot_token:
            from channels.telegram_channel import TelegramChannel

            self.channel_manager.register(
                TelegramChannel(
                    {
                        "bot_token": settings.telegram_bot_token,
                    }
                )
            )
            logger.info("Telegram channel configured")

        # Email
        if settings.email_imap_host:
            from channels.email_channel import EmailChannel

            self.channel_manager.register(
                EmailChannel(
                    {
                        "imap_host": settings.email_imap_host,
                        "imap_port": settings.email_imap_port,
                        "imap_user": settings.email_imap_user,
                        "imap_password": settings.email_imap_password,
                        "smtp_host": settings.email_smtp_host,
                        "smtp_port": settings.email_smtp_port,
                        "smtp_user": settings.email_smtp_user,
                        "smtp_password": settings.email_smtp_password,
                    }
                )
            )
            logger.info("Email channel configured")

        # Set up message handler
        self.channel_manager.on_message(self._handle_channel_message)

    async def _setup_mcp(self):
        """Connect to configured MCP servers and register their tools."""
        mcp_servers = settings.get_mcp_servers()
        for name, config in mcp_servers.items():
            tools = await self.mcp_manager.connect_server(name, config)
            for tool in tools:
                self.tool_registry.register(tool)

    async def _handle_channel_message(self, message: InboundMessage) -> OutboundMessage | None:
        """Handle incoming messages from channels with context-aware classification.

        Uses LLM-based intent classification with conversation history.
        If the intent is ambiguous, sends a clarification question back to the
        channel instead of creating a task immediately.
        """
        logger.info(f"[{message.channel_type}] {message.sender_name}: {message.content[:100]}")

        # Store in session history
        from memory.session import SessionMessage

        self.session_manager.add_message(
            message.channel_type,
            message.channel_id,
            SessionMessage(
                role="user",
                content=message.content,
                channel_type=message.channel_type,
                sender_id=message.sender_id,
                sender_name=message.sender_name,
            ),
        )

        # Check if this is a response to a pending clarification
        clarification_key = f"{message.channel_type}:{message.channel_id}:{message.sender_id}"
        pending = self._pending_clarifications.get(clarification_key)
        if pending:
            # User responded to clarification — use their answer + original message
            del self._pending_clarifications[clarification_key]
            combined = f"{pending.original_message}\n\nUser clarification: {message.content}"
            return await self._create_task_from_message(combined, message, force_type=None)

        # Get conversation history for context-aware classification
        history = self.session_manager.get_messages(
            message.channel_type, message.channel_id, limit=10
        )
        history_dicts = [{"role": m.role, "content": m.content} for m in history] if history else []

        # Classify intent with LLM + context
        classification = await self.intent_classifier.classify(
            message.content, conversation_history=history_dicts
        )

        logger.info(
            f"Intent classification: {classification.task_type.value} "
            f"(confidence={classification.confidence:.2f}, "
            f"llm={classification.used_llm}, "
            f"clarify={classification.needs_clarification})"
        )

        # If ambiguous, ask for clarification
        if classification.needs_clarification and classification.clarification_question:
            self._pending_clarifications[clarification_key] = PendingClarification(
                original_message=message.content,
                channel_type=message.channel_type,
                channel_id=message.channel_id,
                sender_id=message.sender_id,
                sender_name=message.sender_name,
                clarification_question=classification.clarification_question,
                partial_result=classification,
                metadata=message.metadata,
            )

            return OutboundMessage(
                channel_type=message.channel_type,
                channel_id=message.channel_id,
                content=classification.clarification_question,
                metadata=message.metadata,
            )

        # Classification is confident — create task
        return await self._create_task_from_message(
            message.content,
            message,
            force_type=classification.task_type,
            classification=classification,
        )

    async def _create_task_from_message(
        self,
        description: str,
        message: InboundMessage,
        force_type: TaskType | None = None,
        classification=None,
    ) -> OutboundMessage:
        """Create a task from a channel message with the given (or inferred) type.

        If the classification recommends a team, injects a resource allocation
        directive into the task description so the executing agent knows to use
        the team tool.
        """
        task_type = force_type or infer_task_type(description)

        # Smart resource allocation: inject team directive for complex tasks
        task_description = description
        team_name = ""
        if (
            classification
            and classification.recommended_mode == "team"
            and classification.recommended_team
        ):
            team_name = classification.recommended_team
            task_description = (
                f"{description}\n\n"
                f"---\n"
                f"RESOURCE ALLOCATION: This task has been assessed as requiring "
                f"team collaboration.\n"
                f"Use the 'team' tool with action='run', name='{team_name}', "
                f"and the task description above to execute with the {team_name}.\n"
                f"The team's Manager will coordinate the roles automatically."
            )

        task = Task(
            title=f"[{message.channel_type}] {description[:60]}",
            description=task_description,
            task_type=task_type,
            origin_channel=message.channel_type,
            origin_channel_id=message.channel_id,
            origin_metadata=message.metadata,
        )
        await self.task_queue.add(task)

        # Log to memory (semantic indexing for cross-session search)
        await self.memory_store.log_event_semantic(
            "channel_message",
            f"From {message.sender_name} via {message.channel_type}",
            description[:500],
        )

        mode_str = f"team: {team_name}" if team_name else "single agent"
        return OutboundMessage(
            channel_type=message.channel_type,
            channel_id=message.channel_id,
            content=(
                f"Task created: {task.id} (type: {task_type.value}, "
                f"mode: {mode_str}) — I'm working on it."
            ),
            metadata=message.metadata,
        )

    async def _on_task_update(self, task):
        """Broadcast task state changes to all dashboard clients.

        Also routes results back to the originating channel when a task
        completes or fails.
        """
        await self.ws_manager.broadcast("task_update", task.to_dict())

        # Dashboard chat: broadcast agent response back as a chat message
        if task.origin_channel == "dashboard_chat" and task.status in (
            TaskStatus.REVIEW,
            TaskStatus.DONE,
        ):
            import time as _time
            import uuid as _uuid

            content = task.result or "(completed with no output)"
            chat_msg = {
                "id": _uuid.uuid4().hex[:12],
                "role": "assistant",
                "content": content,
                "timestamp": _time.time(),
                "sender": "Agent42",
                "task_id": task.id,
            }
            await self.ws_manager.broadcast("chat_message", chat_msg)
            return  # Don't also send via channel manager

        if task.origin_channel == "dashboard_chat" and task.status == TaskStatus.FAILED:
            import time as _time
            import uuid as _uuid

            chat_msg = {
                "id": _uuid.uuid4().hex[:12],
                "role": "assistant",
                "content": f"Sorry, I encountered an error: {task.error}",
                "timestamp": _time.time(),
                "sender": "Agent42",
                "task_id": task.id,
            }
            await self.ws_manager.broadcast("chat_message", chat_msg)
            return

        # Route results back to originating channel
        if task.origin_channel and task.status in (TaskStatus.REVIEW, TaskStatus.DONE):
            content = f"Task **{task.title}** completed.\n\n"
            if task.result:
                # Truncate long results for chat
                result_preview = task.result[:1500]
                if len(task.result) > 1500:
                    result_preview += "\n... (truncated — see dashboard for full output)"
                content += result_preview

            outbound = OutboundMessage(
                channel_type=task.origin_channel,
                channel_id=task.origin_channel_id,
                content=content,
                metadata=task.origin_metadata,
            )
            await self.channel_manager.send(outbound)

        elif task.origin_channel and task.status == TaskStatus.FAILED:
            outbound = OutboundMessage(
                channel_type=task.origin_channel,
                channel_id=task.origin_channel_id,
                content=f"Task **{task.title}** failed: {task.error}",
                metadata=task.origin_metadata,
            )
            await self.channel_manager.send(outbound)

    async def emit(self, event_type: str, data: dict):
        """Push events from agents to the dashboard via WebSocket."""
        await self.ws_manager.broadcast(event_type, data)

        # Feed iteration events into the heartbeat service
        if event_type == "iteration" and "task_id" in data:
            self.heartbeat.beat(
                data["task_id"],
                iteration=data.get("iteration", 0),
                message=data.get("preview", "")[:100],
            )

    async def _on_agent_stall(self, task_id: str):
        """Handle a stalled agent by broadcasting a warning."""
        logger.warning(f"Agent stalled: {task_id}")
        await self.ws_manager.broadcast("agent_stall", {"task_id": task_id})

    async def _on_heartbeat(self, health):
        """Broadcast system health to dashboard."""
        await self.ws_manager.broadcast("system_health", health.to_dict())

    async def _run_agent(self, task):
        """Execute a single agent with dynamic concurrency limiting.

        Uses real-time CPU and memory metrics to determine whether a new
        agent can be dispatched.  Running agents are never killed — the
        gate only prevents new dispatches when the system is under load.
        """
        self.heartbeat.register_agent(task.id)
        try:
            # Wait until capacity allows a new agent
            while True:
                cap = compute_effective_capacity(self.max_agents)
                async with self._active_lock:
                    if self._active_count < cap["effective_max"]:
                        self._active_count += 1
                        break
                logger.debug(
                    f"Capacity full ({self._active_count}/{cap['effective_max']}), "
                    f"waiting to dispatch task {task.id}"
                )
                await asyncio.sleep(10)

            try:
                agent = Agent(
                    task=task,
                    task_queue=self.task_queue,
                    worktree_manager=self.worktree_manager,
                    approval_gate=self.approval_gate,
                    emit=self.emit,
                    skill_loader=self.skill_loader,
                    memory_store=self.memory_store,
                    workspace_skills_dir=self.workspace_skills_dir,
                    tool_registry=self.tool_registry,
                )
                await agent.run()
                self.heartbeat.mark_complete(task.id)
            finally:
                async with self._active_lock:
                    self._active_count -= 1
        except Exception:
            self.heartbeat.mark_failed(task.id)
            raise

    async def _process_queue(self):
        """Pull tasks from the queue and dispatch agents. Respects concurrency limit."""
        logger.info(f"Queue processor started (max concurrent: {self.max_agents})")
        running_tasks: set[asyncio.Task] = set()

        while not self._shutdown_event.is_set():
            try:
                task = await asyncio.wait_for(self.task_queue.next(), timeout=5.0)
                t = asyncio.create_task(self._run_agent(task))
                running_tasks.add(t)
                t.add_done_callback(running_tasks.discard)
                logger.info(f"Dispatched task {task.id} ({len(running_tasks)} active)")
            except TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue processor error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def start(self):
        """Start the orchestrator: dashboard, channels, queue processor, cron, MCP."""
        self._validate_env()

        dashboard_host = settings.dashboard_host

        logger.info(f"Agent42 starting — repo: {self.repo_path}")
        logger.info(f"  Max concurrent agents: {self.max_agents}")
        logger.info(f"  Sandbox: {'enabled' if settings.sandbox_enabled else 'disabled'}")
        logger.info(f"  Skills loaded: {len(self.skill_loader.all_skills())}")
        logger.info(f"  Tools registered: {len(self.tool_registry.list_tools())}")
        if self._custom_tools:
            logger.info(f"  Custom tools: {', '.join(self._custom_tools)}")
        active_devices = [d for d in self.device_store.list_devices() if not d.is_revoked]
        logger.info(f"  Registered devices: {len(active_devices)}")
        if not self.headless:
            logger.info(f"  Dashboard: http://{dashboard_host}:{self.dashboard_port}")

        # Auth warnings
        for warning in settings.validate_dashboard_auth():
            logger.warning(warning)

        # Load tasks and initialize subsystems
        await self.task_queue.load_from_file()
        if self.app_manager:
            await self.app_manager.load()
            logger.info(f"  Apps loaded: {len(self.app_manager.list_apps())}")
        await self._setup_channels()
        await self._setup_mcp()

        # Set up cron task callback
        self.cron_scheduler.on_trigger(self._cron_create_task)

        # Start heartbeat service
        await self.heartbeat.start()

        tasks_to_run = [
            self._process_queue(),
            self.task_queue.watch_file(),
            self.cron_scheduler.start(),
            self._model_catalog_refresh_loop(),
        ]

        if self.model_researcher:
            tasks_to_run.append(self._model_research_loop())

        # Scheduled security scanning
        if settings.security_scan_enabled:
            tasks_to_run.append(self.security_scanner.start())
            logger.info(f"  Security scanning: enabled (every {settings.security_scan_interval})")

        # Start channel listeners
        if self.channel_manager._channels:
            tasks_to_run.append(self.channel_manager.start_all())
            logger.info(f"  Channels: {', '.join(self.channel_manager._channels.keys())}")

        if not self.headless:
            app = create_app(
                self.task_queue,
                self.ws_manager,
                self.approval_gate,
                tool_registry=self.tool_registry,
                skill_loader=self.skill_loader,
                channel_manager=self.channel_manager,
                learner=self.learner,
                device_store=self.device_store,
                heartbeat=self.heartbeat,
                key_store=self.key_store,
                app_manager=self.app_manager,
            )
            config = uvicorn.Config(
                app,
                host=dashboard_host,
                port=self.dashboard_port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            tasks_to_run.append(server.serve())

        await asyncio.gather(*tasks_to_run)

    async def _model_catalog_refresh_loop(self):
        """Periodically refresh the OpenRouter model catalog."""
        from providers.registry import ProviderRegistry

        while not self._shutdown_event.is_set():
            try:
                if self.model_catalog.needs_refresh():
                    await self.model_catalog.refresh(api_key=settings.openrouter_api_key)
                    new_models = self.model_catalog.register_new_models(ProviderRegistry())
                    if new_models:
                        logger.info("Discovered %d new free model(s)", len(new_models))
                    # Rerank after catalog refresh
                    self.model_evaluator.rerank_all()
            except Exception as e:
                logger.warning("Model catalog refresh failed (non-critical): %s", e)

            await asyncio.sleep(self.model_catalog.refresh_interval_seconds)

    async def _model_research_loop(self):
        """Periodically research model benchmarks from authoritative sources."""
        while not self._shutdown_event.is_set():
            try:
                if self.model_researcher and self.model_researcher.needs_research():
                    await self.model_researcher.research(router=ModelRouter())
                    # Rerank after new research data
                    self.model_evaluator.rerank_all()
            except Exception as e:
                logger.warning("Model research failed (non-critical): %s", e)

            interval = (
                self.model_researcher.interval_seconds
                if self.model_researcher
                else 604800  # 1 week
            )
            await asyncio.sleep(interval)

    async def _cron_create_task(self, title: str, description: str, task_type: str):
        """Callback for cron scheduler to create tasks."""
        try:
            tt = TaskType(task_type)
        except ValueError:
            tt = TaskType.CODING
        task = Task(title=title, description=description, task_type=tt)
        await self.task_queue.add(task)
        logger.info(f"Cron created task: {task.id} — {title}")

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Agent42 shutting down...")
        self._shutdown_event.set()
        self.heartbeat.stop()
        self.cron_scheduler.stop()
        self.security_scanner.stop()
        await self.channel_manager.stop_all()
        await self.mcp_manager.disconnect_all()

    def _validate_env(self):
        """Validate required configuration before starting."""
        if not self.has_repo:
            logger.info(
                "No git repository configured. Connect repos via the dashboard Settings page."
            )
        elif not self.repo_path.exists():
            logger.warning(f"Configured repo path does not exist: {self.repo_path}")
        elif not (self.repo_path / ".git").exists():
            logger.warning(f"{self.repo_path} is not a git repository.")

        # Warn about unconfigured providers
        from providers.registry import ProviderRegistry

        registry = ProviderRegistry()
        for p in registry.available_providers():
            if not p["configured"]:
                logger.debug(f"Provider not configured: {p['display_name']}")


def _run_backup(args):
    """Handle the 'backup' subcommand."""
    from core.portability import create_backup

    base = str(Path.cwd())
    try:
        path = create_backup(
            base_path=base,
            output_path=args.output,
            include_worktrees=args.include_worktrees,
        )
        print(f"Backup created: {path}")
    except Exception as e:
        logger.error("Backup failed: %s", e)
        print(f"Error: {e}")
        sys.exit(1)


def _run_restore(args):
    """Handle the 'restore' subcommand."""
    from core.portability import restore_backup

    try:
        manifest = restore_backup(
            archive_path=args.archive,
            target_path=args.target,
            skip_secrets=args.skip_secrets,
        )
        print(f"Restored backup to {args.target}")
        print(f"  Archive created: {manifest.created_at}")
        print(f"  Categories: {', '.join(manifest.categories)}")
        print(f"  Files: {manifest.file_count}")
    except Exception as e:
        logger.error("Restore failed: %s", e)
        print(f"Error: {e}")
        sys.exit(1)


def _run_clone(args):
    """Handle the 'clone' subcommand."""
    from core.portability import create_clone

    base = str(Path.cwd())
    try:
        path = create_clone(
            base_path=base,
            output_path=args.output,
            include_skills=args.include_skills,
        )
        print(f"Clone package created: {path}")
        print("  Next steps on the target node:")
        print("  1. Extract the archive")
        print("  2. Rename .env.template to .env and fill in secrets")
        print("  3. Run: bash setup.sh")
    except Exception as e:
        logger.error("Clone failed: %s", e)
        print(f"Error: {e}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="Agent42 — The answer to all your tasks")
    subparsers = parser.add_subparsers(dest="command")

    # Server args (also on the root parser for backward compatibility)
    parser.add_argument(
        "--repo",
        default=settings.default_repo_path or "",
        help="Path to the git repository (optional — configure via dashboard)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8000,
        help="Dashboard port (default: 8000)",
    )
    parser.add_argument(
        "--no-dashboard",
        action="store_true",
        help="Run headless without the web dashboard",
    )
    parser.add_argument(
        "--max-agents",
        type=int,
        default=None,
        help=f"Max concurrent agents (default: {settings.max_concurrent_agents})",
    )

    # Backup subcommand
    backup_parser = subparsers.add_parser(
        "backup", help="Create a full backup archive of Agent42 data"
    )
    backup_parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Output directory for the archive (default: current directory)",
    )
    backup_parser.add_argument(
        "--include-worktrees",
        action="store_true",
        help="Include git worktrees in the backup (can be large)",
    )

    # Restore subcommand
    restore_parser = subparsers.add_parser(
        "restore", help="Restore Agent42 data from a backup archive"
    )
    restore_parser.add_argument(
        "archive",
        help="Path to the backup archive (.tar.gz)",
    )
    restore_parser.add_argument(
        "--target",
        default=".",
        help="Target directory to restore into (default: current directory)",
    )
    restore_parser.add_argument(
        "--skip-secrets",
        action="store_true",
        help="Skip restoring .env and settings.json",
    )

    # Clone subcommand
    clone_parser = subparsers.add_parser(
        "clone", help="Create a clone package for deploying to a new node"
    )
    clone_parser.add_argument(
        "-o",
        "--output",
        default=".",
        help="Output directory for the archive (default: current directory)",
    )
    clone_parser.add_argument(
        "--include-skills",
        action="store_true",
        help="Include user-installed skills from skills/workspace/",
    )

    args = parser.parse_args()

    if args.command == "backup":
        _run_backup(args)
    elif args.command == "restore":
        _run_restore(args)
    elif args.command == "clone":
        _run_clone(args)
    else:
        # Default: start the orchestrator (existing behavior)
        orchestrator = Agent42(
            repo_path=args.repo or None,
            dashboard_port=args.port,
            headless=args.no_dashboard,
            max_agents=args.max_agents,
        )

        loop = asyncio.new_event_loop()

        for sig in (signal.SIGINT, signal.SIGTERM):
            loop.add_signal_handler(sig, lambda: loop.create_task(orchestrator.shutdown()))

        try:
            loop.run_until_complete(orchestrator.start())
        finally:
            loop.close()
            logger.info("Agent42 stopped")


if __name__ == "__main__":
    main()

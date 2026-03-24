"""
agent42.py — The answer to life, the universe, and all your tasks.

v2.0 MCP Architecture:
- Claude Code provides the intelligence layer (LLM, orchestration, context)
- Agent42 provides the tooling layer (MCP tools, memory, dashboard)
- MCP server is started by Claude Code via .mcp.json (stdio transport)
- This file starts the dashboard and optional services

Usage:
    python agent42.py                     # Start dashboard (http://localhost:8000)
    python agent42.py --port 8080         # Custom dashboard port
    python agent42.py --no-dashboard      # Headless mode (services only)
    python agent42.py backup -o ./        # Create backup archive
    python agent42.py restore backup.tar  # Restore from backup
    python agent42.py clone -o ./         # Create clone package
"""

import argparse
import asyncio
import atexit
import logging
import os
import signal
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env", override=True)

from commands import BackupCommandHandler, CloneCommandHandler, RestoreCommandHandler
from core.agent_manager import AgentManager
from core.app_manager import AppManager
from core.config import settings
from core.device_auth import DeviceStore
from core.heartbeat import HeartbeatService
from core.project_manager import ProjectManager
from core.rate_limiter import ToolRateLimiter
from core.repo_manager import RepositoryManager
from core.security_scanner import ScheduledSecurityScanner
from core.workspace_registry import WorkspaceRegistry
from dashboard.auth import init_device_store
from dashboard.server import create_app
from dashboard.websocket_manager import WebSocketManager
from memory.effectiveness import EffectivenessStore
from memory.qdrant_store import QdrantConfig, QdrantStore
from memory.redis_session import RedisConfig, RedisSessionBackend
from memory.session import SessionManager
from memory.store import MemoryStore
from skills.loader import SkillLoader
from tools.cron import CronScheduler
from tools.plugin_loader import PluginLoader
from tools.registry import ToolRegistry

# ── Logging ──────────────────────────────────────────────────────────────
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_log_handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
try:
    _log_handlers.append(logging.FileHandler("agent42.log"))
except PermissionError:
    print("WARNING: Cannot write to agent42.log — logging to stdout only.", file=sys.stderr)

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=_log_handlers)
logger = logging.getLogger("agent42")

atexit.register(lambda: print("Agent42 process exiting (atexit)", flush=True))


class Agent42:
    """Agent42 v2.0 — Dashboard + services launcher.

    In the MCP architecture, Claude Code handles LLM orchestration.
    Agent42 provides:
    - Dashboard web UI (FastAPI + WebSocket)
    - Memory backend (Qdrant + Redis)
    - Cron scheduler
    - Security scanning
    - Skill/tool registry (shared with MCP server)
    """

    def __init__(
        self,
        dashboard_port: int = 8000,
        headless: bool = False,
    ):
        self.dashboard_port = dashboard_port
        self.headless = headless

        # ── Core infrastructure ──────────────────────────────────────────
        workspace = Path(settings.default_repo_path or ".").resolve()
        data_dir = Path(__file__).parent / ".agent42"

        self.ws_manager = WebSocketManager()

        _cpu_count = os.cpu_count() or 4
        _max_agents = (
            settings.max_concurrent_agents if settings.max_concurrent_agents > 0 else _cpu_count * 4
        )
        self.heartbeat = HeartbeatService(configured_max_agents=_max_agents)
        self.cron_scheduler = CronScheduler()
        self.device_store = DeviceStore(data_dir / "devices.json")
        init_device_store(self.device_store)
        self.repo_manager = RepositoryManager(data_dir / "repos")
        self.session_manager = SessionManager(str(data_dir / "sessions"))
        skill_dirs = [
            Path(__file__).parent / "skills" / "builtins",
            Path(__file__).parent / "skills" / "workspace",
        ]
        self.skill_loader = SkillLoader([d for d in skill_dirs if d.exists()])
        self.skill_loader.load_all()

        # ── Tool registry (shared with MCP server for dashboard visibility)
        try:
            from mcp_server import _build_registry

            self.tool_registry = _build_registry()
        except Exception as e:
            logger.warning(f"MCP registry build failed, using empty: {e}")
            self.tool_registry = ToolRegistry(rate_limiter=ToolRateLimiter())

        # ── Memory backend ───────────────────────────────────────────────
        memory_dir = data_dir / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)

        qdrant_store = None
        qdrant_url = os.environ.get("QDRANT_URL", "")
        if qdrant_url:
            qdrant_store = QdrantStore(QdrantConfig(url=qdrant_url, vector_dim=384))
        else:
            qdrant_path = str(data_dir / "qdrant")
            qdrant_store = QdrantStore(QdrantConfig(local_path=qdrant_path, vector_dim=384))

        redis_backend = None
        if settings.redis_url:
            redis_backend = RedisSessionBackend(RedisConfig(url=settings.redis_url))

        self.memory_store = MemoryStore(
            memory_dir, qdrant_store=qdrant_store, redis_backend=redis_backend
        )

        # ── Effectiveness tracking ────────────────────────────
        self.effectiveness_store = EffectivenessStore(data_dir / "effectiveness.db")
        self.tool_registry._effectiveness_store = self.effectiveness_store

        # ── Agent manager (moved here from server.py to enable TierRecalcLoop access) ──
        agents_dir = data_dir / "agents"
        self.agent_manager = AgentManager(agents_dir)

        # ── Rewards tier recalculation (optional, gated on REWARDS_ENABLED) ──────
        self.tier_recalc = None
        if settings.rewards_enabled:
            from core.reward_system import RewardSystem, TierRecalcLoop

            data_dir_path = Path(__file__).parent / ".agent42"
            self.reward_system = RewardSystem(
                effectiveness_store=self.effectiveness_store,
                enabled=True,
                persistence_path=data_dir_path / "tier_assignments.json",
            )
            self.tier_recalc = TierRecalcLoop(
                agent_manager=self.agent_manager,
                reward_system=self.reward_system,
                effectiveness_store=self.effectiveness_store,
                ws_manager=self.ws_manager,
            )
        else:
            self.reward_system = None

        # ── Project manager ──────────────────────────────────────────────
        self.project_manager = ProjectManager(data_dir / "projects", task_queue=None)

        # ── Workspace registry ────────────────────────────────────────────
        self.workspace_registry = WorkspaceRegistry(data_dir / "workspaces.json")

        # ── Security scanner ─────────────────────────────────────────────
        self.security_scanner = ScheduledSecurityScanner(
            workspace_path=str(workspace),
        )

        # ── Custom tools (plugins) ───────────────────────────────────────
        self._custom_tools: list[str] = []
        custom_tools_dir = Path(settings.custom_tools_dir) if settings.custom_tools_dir else None
        if custom_tools_dir and custom_tools_dir.is_dir():
            try:
                from tools.context import ToolContext

                ctx = ToolContext(workspace=str(workspace), tool_registry=self.tool_registry)
                loaded_names = PluginLoader.load_all(custom_tools_dir, ctx, self.tool_registry)
                self._custom_tools = loaded_names
            except Exception as e:
                logger.warning(f"Plugin loading failed: {e}")

        logger.info("Agent42 v2.0 initialized (MCP architecture)")

    async def start(self):
        """Start the dashboard and background services."""
        logger.info("Agent42 starting...")
        logger.info(f"  Skills loaded: {len(self.skill_loader.all_skills())}")
        logger.info(f"  Tools registered: {len(self.tool_registry.list_tools())}")
        if self._custom_tools:
            logger.info(f"  Custom tools: {', '.join(self._custom_tools)}")

        # Auth warnings
        for warning in settings.validate_dashboard_auth():
            logger.warning(warning)

        # Load persisted data
        await self.repo_manager.load()
        await self.project_manager.load()
        await self.workspace_registry.load()
        await self.workspace_registry.seed_default(
            os.environ.get("AGENT42_WORKSPACE", str(Path.cwd()))
        )

        # Start heartbeat
        await self.heartbeat.start()

        # Start tier recalculation loop (only when rewards enabled)
        if self.tier_recalc:
            await self.tier_recalc.start()

        tasks_to_run = [
            self.cron_scheduler.start(),
        ]

        # Scheduled security scanning
        if settings.security_scan_enabled:
            tasks_to_run.append(self.security_scanner.start())
            logger.info(f"  Security scanning: enabled (every {settings.security_scan_interval})")

        if not self.headless:
            app_manager = AppManager(
                apps_dir=str(settings.apps_dir) if hasattr(settings, "apps_dir") else "apps",
                dashboard_port=self.dashboard_port,
            )
            app = create_app(
                ws_manager=self.ws_manager,
                tool_registry=self.tool_registry,
                skill_loader=self.skill_loader,
                device_store=self.device_store,
                heartbeat=self.heartbeat,
                repo_manager=self.repo_manager,
                project_manager=self.project_manager,
                memory_store=self.memory_store,
                effectiveness_store=self.effectiveness_store,
                app_manager=app_manager,
                agent_manager=self.agent_manager,
                reward_system=self.reward_system,
                workspace_registry=self.workspace_registry,
            )
            config = uvicorn.Config(
                app,
                host=settings.dashboard_host,
                port=self.dashboard_port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            logger.info(f"  Dashboard: http://{settings.dashboard_host}:{self.dashboard_port}")
            tasks_to_run.append(server.serve())

        logger.info("Agent42 ready — MCP tools available via Claude Code")
        await asyncio.gather(*tasks_to_run)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Agent42 shutting down...")
        await self.heartbeat.stop()
        if self.tier_recalc:
            self.tier_recalc.stop()
        self.cron_scheduler.stop()
        logger.info("Agent42 stopped")


def main():
    parser = argparse.ArgumentParser(description="Agent42 — The answer to all your tasks")
    subparsers = parser.add_subparsers(dest="command")

    # Server args
    parser.add_argument("--port", type=int, default=8000, help="Dashboard port (default: 8000)")
    parser.add_argument(
        "--no-dashboard", action="store_true", help="Run headless without the web dashboard"
    )

    # Backup subcommand
    backup_parser = subparsers.add_parser("backup", help="Create a full backup archive")
    backup_parser.add_argument("-o", "--output", default=".", help="Output directory")
    backup_parser.add_argument(
        "--include-worktrees", action="store_true", help="Include git worktrees"
    )

    # Restore subcommand
    restore_parser = subparsers.add_parser("restore", help="Restore from backup archive")
    restore_parser.add_argument("archive", help="Path to the backup archive (.tar.gz)")
    restore_parser.add_argument("--target", default=".", help="Target directory")
    restore_parser.add_argument("--skip-secrets", action="store_true", help="Skip .env/settings")

    # Clone subcommand
    clone_parser = subparsers.add_parser("clone", help="Create a clone package for new node")
    clone_parser.add_argument("-o", "--output", default=".", help="Output directory")
    clone_parser.add_argument(
        "--include-skills", action="store_true", help="Include user-installed skills"
    )

    args = parser.parse_args()

    command_handlers = {
        "backup": BackupCommandHandler(),
        "restore": RestoreCommandHandler(),
        "clone": CloneCommandHandler(),
    }

    handler = command_handlers.get(args.command)
    if handler:
        handler.run(args)
    else:
        # Default: start dashboard + services
        print("Agent42 v2.0 initializing (MCP architecture)...", flush=True)
        try:
            agent42 = Agent42(
                dashboard_port=args.port,
                headless=args.no_dashboard,
            )
        except Exception as exc:
            logger.critical("Agent42 failed to initialize: %s", exc, exc_info=True)
            sys.exit(1)

        loop = asyncio.new_event_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: loop.create_task(agent42.shutdown()))

        try:
            loop.run_until_complete(agent42.start())
        except KeyboardInterrupt:
            loop.run_until_complete(agent42.shutdown())
        except Exception as exc:
            logger.critical("Agent42 crashed: %s", exc, exc_info=True)
            sys.exit(1)
        finally:
            loop.close()
            logger.info("Agent42 stopped")


if __name__ == "__main__":
    main()

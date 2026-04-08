"""
frood.py — The answer to life, the universe, and all your tasks.

v2.0 MCP Architecture:
- Claude Code provides the intelligence layer (LLM, orchestration, context)
- Frood provides the tooling layer (MCP tools, memory, dashboard)
- MCP server is started by Claude Code via .mcp.json (stdio transport)
- This file starts the dashboard and optional services

Usage:
    python frood.py                     # Start dashboard (http://localhost:8000)
    python frood.py --port 8080         # Custom dashboard port
    python frood.py --no-dashboard      # Headless mode (services only)
    python frood.py --sidecar           # Sidecar mode (Paperclip adapter, port 8001)
    python frood.py --sidecar --sidecar-port 9001  # Sidecar on custom port
    python frood.py backup -o ./        # Create backup archive
    python frood.py restore backup.tar  # Restore from backup
    python frood.py clone -o ./         # Create clone package
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
from core.heartbeat import HeartbeatService
from core.key_store import KeyStore
from core.rate_limiter import ToolRateLimiter
from core.security_scanner import ScheduledSecurityScanner
from dashboard.server import create_app
from dashboard.websocket_manager import WebSocketManager
from memory.consolidation import ConsolidationPipeline, ConsolidationRouter
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
    _log_handlers.append(logging.FileHandler("frood.log"))
except PermissionError:
    print("WARNING: Cannot write to frood.log — logging to stdout only.", file=sys.stderr)

logging.basicConfig(level=logging.INFO, format=LOG_FORMAT, handlers=_log_handlers)
logger = logging.getLogger("frood")

atexit.register(lambda: print("Frood process exiting (atexit)", flush=True))


def _migrate_data_dir() -> None:
    """Auto-migrate .agent42/ to .frood/ on first startup (D-05)."""
    import shutil

    project_root = Path(__file__).parent
    old_dir = project_root / ".agent42"
    new_dir = project_root / ".frood"

    if old_dir.exists() and not new_dir.exists():
        shutil.move(str(old_dir), str(new_dir))
        print(
            "[frood] Data directory migrated: .agent42/ -> .frood/",
            file=sys.stderr,
            flush=True,
        )
    elif old_dir.exists() and new_dir.exists():
        print(
            "[frood] WARNING: Both .agent42/ and .frood/ exist -- using .frood/. "
            "Remove .agent42/ after verifying migration is complete.",
            file=sys.stderr,
            flush=True,
        )


class Frood:
    """Frood v2.0 — Dashboard + services launcher.

    In the MCP architecture, Claude Code handles LLM orchestration.
    Frood provides:
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
        sidecar: bool = False,
        sidecar_port: int | None = None,
        standalone: bool = False,
    ):
        self.dashboard_port = dashboard_port
        self.headless = headless
        self.sidecar = sidecar
        self.sidecar_port = sidecar_port or settings.paperclip_sidecar_port
        self.standalone = standalone

        # ── Core infrastructure ──────────────────────────────────────────
        workspace = Path(settings.default_repo_path or ".").resolve()
        data_dir = Path(__file__).parent / ".frood"

        self.ws_manager = WebSocketManager()

        _cpu_count = os.cpu_count() or 4
        _max_agents = (
            settings.max_concurrent_agents if settings.max_concurrent_agents > 0 else _cpu_count * 4
        )
        self.heartbeat = HeartbeatService(configured_max_agents=_max_agents)
        self.cron_scheduler = CronScheduler()

        # ── Key store for API key management ──────────────────────────────
        self.key_store = KeyStore(data_dir / "settings.json")
        # Inject admin-configured keys into environment at startup
        self.key_store.inject_into_environ()

        # ── Device store for multi-device API key auth (Phase 53) ────────
        from core.device_auth import DeviceStore

        self.device_store = DeviceStore(data_dir / "devices.jsonl")
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

        # ── Consolidation pipeline (LLM summarization of old sessions) ───
        consolidation_router = ConsolidationRouter()
        consolidation_pipeline = ConsolidationPipeline(
            model_router=consolidation_router,
            embedding_store=self.memory_store.embeddings,
            qdrant_store=qdrant_store,
        )
        self.consolidation_pipeline = consolidation_pipeline

        # ── Session manager (after redis + consolidation are ready) ──────
        self.session_manager = SessionManager(
            str(data_dir / "sessions"),
            redis_backend=redis_backend,
            consolidation_pipeline=consolidation_pipeline,
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

            data_dir_path = Path(__file__).parent / ".frood"
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

        logger.info("Frood v2.0 initialized (MCP architecture)")

    async def start(self):
        """Start the dashboard and background services."""
        logger.info("Frood starting...")
        logger.info(f"  Skills loaded: {len(self.skill_loader.all_skills())}")
        logger.info(f"  Tools registered: {len(self.tool_registry.list_tools())}")
        if self._custom_tools:
            logger.info(f"  Custom tools: {', '.join(self._custom_tools)}")

        # Auth warnings
        for warning in settings.validate_dashboard_auth():
            logger.warning(warning)

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

        if self.sidecar:
            from dashboard.sidecar import create_sidecar_app

            app = create_sidecar_app(
                memory_store=self.memory_store,
                agent_manager=self.agent_manager,
                effectiveness_store=self.effectiveness_store,
                reward_system=self.reward_system,
                qdrant_store=self.memory_store._qdrant,
                tool_registry=self.tool_registry,
                skill_loader=self.skill_loader,
                app_manager=None,  # Phase 36: AppManager only in non-sidecar mode currently
                key_store=self.key_store,
                device_store=self.device_store,  # Phase 53: AUTH-01
            )
            config = uvicorn.Config(
                app,
                host=settings.dashboard_host,
                port=self.sidecar_port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            logger.info(f"  Sidecar: http://{settings.dashboard_host}:{self.sidecar_port}")
            tasks_to_run.append(server.serve())
        elif not self.headless:
            app_manager = AppManager(
                apps_dir=str(settings.apps_dir) if hasattr(settings, "apps_dir") else "apps",
                dashboard_port=self.dashboard_port,
            )
            await app_manager.load()
            app = create_app(
                ws_manager=self.ws_manager,
                tool_registry=self.tool_registry,
                skill_loader=self.skill_loader,
                heartbeat=self.heartbeat,
                memory_store=self.memory_store,
                effectiveness_store=self.effectiveness_store,
                app_manager=app_manager,
                key_store=self.key_store,
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

        logger.info("Frood ready — MCP tools available via Claude Code")
        await asyncio.gather(*tasks_to_run)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Frood shutting down...")
        await self.heartbeat.stop()
        if self.tier_recalc:
            self.tier_recalc.stop()
        self.cron_scheduler.stop()
        logger.info("Frood stopped")


def main():
    parser = argparse.ArgumentParser(description="Frood — The answer to all your tasks")
    subparsers = parser.add_subparsers(dest="command")

    # Server args
    parser.add_argument("--port", type=int, default=8000, help="Dashboard port (default: 8000)")
    parser.add_argument(
        "--no-dashboard", action="store_true", help="Run headless without the web dashboard"
    )
    parser.add_argument(
        "--sidecar",
        action="store_true",
        help="Run as Paperclip sidecar (adapter-friendly endpoints, no dashboard)",
    )
    parser.add_argument(
        "--sidecar-port",
        type=int,
        default=None,
        help="Sidecar HTTP port (default: PAPERCLIP_SIDECAR_PORT or 8001)",
    )
    parser.add_argument(
        "--standalone",
        action="store_true",
        help="Run in standalone mode (simplified dashboard for Claude Code only)",
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
        print("Frood v2.0 initializing (MCP architecture)...", flush=True)
        is_sidecar = args.sidecar or settings.sidecar_enabled
        is_standalone = args.standalone or settings.standalone_mode
        if is_sidecar:
            from core.sidecar_logging import configure_sidecar_logging

            configure_sidecar_logging()
        _migrate_data_dir()
        try:
            frood = Frood(
                dashboard_port=args.port,
                headless=args.no_dashboard,
                sidecar=is_sidecar,
                sidecar_port=args.sidecar_port,
                standalone=is_standalone,
            )
        except Exception as exc:
            logger.critical("Frood failed to initialize: %s", exc, exc_info=True)
            sys.exit(1)

        loop = asyncio.new_event_loop()
        if sys.platform != "win32":
            for sig in (signal.SIGINT, signal.SIGTERM):
                loop.add_signal_handler(sig, lambda: loop.create_task(frood.shutdown()))

        try:
            loop.run_until_complete(frood.start())
        except KeyboardInterrupt:
            loop.run_until_complete(frood.shutdown())
        except Exception as exc:
            logger.critical("Frood crashed: %s", exc, exc_info=True)
            sys.exit(1)
        finally:
            loop.close()
            logger.info("Frood stopped")


if __name__ == "__main__":
    main()

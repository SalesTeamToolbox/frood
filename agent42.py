"""
agent42.py - The answer to life, the universe, and all your tasks.

Multi-agent orchestrator platform. Free models handle the iterative work;
premium APIs or human review gate the final output.

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
import logging
import signal
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from core.config import settings
from core.task_queue import TaskQueue
from core.worktree_manager import WorktreeManager
from core.approval_gate import ApprovalGate
from agents.agent import Agent
from dashboard.server import create_app
from dashboard.websocket_manager import WebSocketManager

# -- Logging -------------------------------------------------------------------
LOG_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"

logging.basicConfig(
    level=logging.INFO,
    format=LOG_FORMAT,
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("agent42.log"),
    ],
)
logger = logging.getLogger("agent42")


class Agent42:
    """Core orchestrator — manages the task queue, agents, and dashboard."""

    def __init__(
        self,
        repo_path: str,
        dashboard_port: int = 8000,
        headless: bool = False,
        max_agents: int | None = None,
    ):
        self.repo_path = Path(repo_path).resolve()
        self.dashboard_port = dashboard_port
        self.headless = headless
        self.max_agents = max_agents or settings.max_concurrent_agents

        self.task_queue = TaskQueue(tasks_json_path=settings.tasks_json_path)
        self.ws_manager = WebSocketManager()
        self.worktree_manager = WorktreeManager(str(self.repo_path))
        self.approval_gate = ApprovalGate(self.task_queue)
        self._semaphore = asyncio.Semaphore(self.max_agents)
        self._shutdown_event = asyncio.Event()

        self.task_queue.on_update(self._on_task_update)

    async def _on_task_update(self, task):
        """Broadcast task state changes to all dashboard clients."""
        await self.ws_manager.broadcast("task_update", task.to_dict())

    async def emit(self, event_type: str, data: dict):
        """Push events from agents to the dashboard via WebSocket."""
        await self.ws_manager.broadcast(event_type, data)

    async def _run_agent(self, task):
        """Execute a single agent with concurrency limiting."""
        async with self._semaphore:
            agent = Agent(
                task=task,
                task_queue=self.task_queue,
                worktree_manager=self.worktree_manager,
                approval_gate=self.approval_gate,
                emit=self.emit,
            )
            await agent.run()

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
            except asyncio.TimeoutError:
                continue
            except Exception as e:
                logger.error(f"Queue processor error: {e}", exc_info=True)
                await asyncio.sleep(1)

    async def start(self):
        """Start the orchestrator: dashboard, queue processor, file watcher."""
        self._validate_env()

        logger.info(f"Agent42 starting — repo: {self.repo_path}")
        logger.info(f"  Max concurrent agents: {self.max_agents}")
        if not self.headless:
            logger.info(f"  Dashboard: http://0.0.0.0:{self.dashboard_port}")

        await self.task_queue.load_from_file()

        tasks_to_run = [
            self._process_queue(),
            self.task_queue.watch_file(),
        ]

        if not self.headless:
            app = create_app(self.task_queue, self.ws_manager, self.approval_gate)
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=self.dashboard_port,
                log_level="warning",
            )
            server = uvicorn.Server(config)
            tasks_to_run.append(server.serve())

        await asyncio.gather(*tasks_to_run)

    async def shutdown(self):
        """Graceful shutdown."""
        logger.info("Agent42 shutting down...")
        self._shutdown_event.set()

    def _validate_env(self):
        """Validate required configuration before starting."""
        if not self.repo_path.exists():
            raise SystemExit(f"Repo path does not exist: {self.repo_path}")

        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            raise SystemExit(
                f"{self.repo_path} is not a git repository. "
                "Run: git init && git checkout -b dev"
            )

        if not settings.nvidia_api_key:
            logger.warning("NVIDIA_API_KEY not set — NVIDIA models will fail")
        if not settings.groq_api_key:
            logger.warning("GROQ_API_KEY not set — Groq models will fail")


def main():
    parser = argparse.ArgumentParser(
        description="Agent42 — The answer to all your tasks"
    )
    parser.add_argument(
        "--repo",
        default=settings.default_repo_path,
        help="Path to the git repository (default: current directory)",
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

    args = parser.parse_args()

    orchestrator = Agent42(
        repo_path=args.repo,
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

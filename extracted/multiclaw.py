"""
multiclaw.py — Multi-agent coding orchestrator

Usage:
    python multiclaw.py                    # Start with tasks.json if present
    python multiclaw.py --port 8080        # Custom dashboard port
    python multiclaw.py --repo /path/to   # Specify repo path
    python multiclaw.py --no-dashboard    # Headless mode (terminal only)

Dashboard: http://localhost:8000 (default)

Environment variables (set in .env):
    NVIDIA_API_KEY          - NVIDIA build.nvidia.com API key
    GROQ_API_KEY            - Groq API key  
    DASHBOARD_USERNAME      - Dashboard login username
    DASHBOARD_PASSWORD      - Dashboard login password (plaintext, for initial setup)
    DASHBOARD_PASSWORD_HASH - Bcrypt hash (recommended for production)
    JWT_SECRET              - Long random string for JWT signing
    DEFAULT_REPO_PATH       - Default git repo for worktrees
"""

import argparse
import asyncio
import logging
import os
import sys
from pathlib import Path

import uvicorn
from dotenv import load_dotenv

load_dotenv()

from core.task_queue import TaskQueue, TaskStatus
from core.worktree_manager import WorktreeManager
from core.approval_gate import ApprovalGate
from agents.claw_agent import ClawAgent
from dashboard.server import create_app
from dashboard.websocket_manager import WebSocketManager

# ── Logging ────────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("multiclaw.log"),
    ],
)
logger = logging.getLogger("multiclaw")

# ── Configuration ──────────────────────────────────────────────────────────────
MAX_CONCURRENT_AGENTS = int(os.getenv("MAX_CONCURRENT_AGENTS", "3"))
DEFAULT_REPO = os.getenv("DEFAULT_REPO_PATH", str(Path.cwd()))
TASKS_JSON = os.getenv("TASKS_JSON_PATH", "tasks.json")


class MultiClaw:
    def __init__(self, repo_path: str, dashboard_port: int = 8000, headless: bool = False):
        self.repo_path = Path(repo_path).resolve()
        self.dashboard_port = dashboard_port
        self.headless = headless

        self.task_queue = TaskQueue(tasks_json_path=TASKS_JSON)
        self.ws_manager = WebSocketManager()
        self.worktree_manager = WorktreeManager(str(self.repo_path))
        self.approval_gate = ApprovalGate(self.task_queue)
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT_AGENTS)

        # Wire up task update → WebSocket broadcast
        self.task_queue.on_update(self._on_task_update)

    async def _on_task_update(self, task):
        """Broadcast task state changes to all dashboard clients."""
        await self.ws_manager.broadcast("task_update", task.to_dict())

    async def emit(self, event_type: str, data: dict):
        """Used by agents to push events to dashboard."""
        await self.ws_manager.broadcast(event_type, data)

    async def _run_agent(self, task):
        """Wrap agent execution with concurrency semaphore."""
        async with self._semaphore:
            agent = ClawAgent(
                task=task,
                task_queue=self.task_queue,
                worktree_manager=self.worktree_manager,
                approval_gate=self.approval_gate,
                emit=self.emit,
            )
            await agent.run()

    async def _process_queue(self):
        """
        Continuously pull tasks from queue and run them.
        Respects MAX_CONCURRENT_AGENTS via semaphore.
        """
        logger.info(
            f"Queue processor started. Max concurrent agents: {MAX_CONCURRENT_AGENTS}"
        )
        running_tasks = set()

        while True:
            try:
                task = await asyncio.wait_for(
                    self.task_queue.next(), timeout=5.0
                )
                t = asyncio.create_task(self._run_agent(task))
                running_tasks.add(t)
                t.add_done_callback(running_tasks.discard)
                logger.info(
                    f"Dispatched task {task.id} ({len(running_tasks)} active)"
                )
            except asyncio.TimeoutError:
                # No new tasks — just loop and keep watching
                continue
            except Exception as e:
                logger.error(f"Queue processor error: {e}")
                await asyncio.sleep(1)

    async def start(self):
        """Start all subsystems: dashboard server, task queue watcher, processor."""
        self._validate_env()

        logger.info(f"🦞 MultiClaw starting — repo: {self.repo_path}")
        logger.info(f"   Max concurrent agents: {MAX_CONCURRENT_AGENTS}")
        logger.info(f"   Dashboard: http://0.0.0.0:{self.dashboard_port}")

        # Load any tasks.json that already exists
        await self.task_queue.load_from_file()

        tasks_to_run = []

        # Task queue processor
        tasks_to_run.append(self._process_queue())

        # tasks.json file watcher (picks up new tasks written to file)
        tasks_to_run.append(self.task_queue.watch_file())

        if not self.headless:
            # Dashboard HTTP server
            app = create_app(self.task_queue, self.ws_manager)
            config = uvicorn.Config(
                app,
                host="0.0.0.0",
                port=self.dashboard_port,
                log_level="warning",  # Suppress uvicorn noise
            )
            server = uvicorn.Server(config)
            tasks_to_run.append(server.serve())

        await asyncio.gather(*tasks_to_run)

    def _validate_env(self):
        """Warn about missing API keys but don't crash — keys may be task-specific."""
        warnings = []

        if not os.getenv("NVIDIA_API_KEY"):
            warnings.append("NVIDIA_API_KEY not set — NVIDIA models will fail")
        if not os.getenv("GROQ_API_KEY"):
            warnings.append("GROQ_API_KEY not set — Groq models will fail")

        if not self.repo_path.exists():
            raise ValueError(f"Repo path does not exist: {self.repo_path}")

        git_dir = self.repo_path / ".git"
        if not git_dir.exists():
            raise ValueError(
                f"{self.repo_path} is not a git repository. "
                "Run: git init && git checkout -b dev"
            )

        for w in warnings:
            logger.warning(f"⚠️  {w}")


def main():
    parser = argparse.ArgumentParser(
        description="MultiClaw — Multi-agent coding orchestrator"
    )
    parser.add_argument(
        "--repo",
        default=DEFAULT_REPO,
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
        default=MAX_CONCURRENT_AGENTS,
        help=f"Max concurrent agents (default: {MAX_CONCURRENT_AGENTS})",
    )

    args = parser.parse_args()

    if args.max_agents != MAX_CONCURRENT_AGENTS:
        os.environ["MAX_CONCURRENT_AGENTS"] = str(args.max_agents)

    mc = MultiClaw(
        repo_path=args.repo,
        dashboard_port=args.port,
        headless=args.no_dashboard,
    )

    try:
        asyncio.run(mc.start())
    except KeyboardInterrupt:
        logger.info("MultiClaw stopped by user")


if __name__ == "__main__":
    main()

"""
Git worktree lifecycle manager.

Each task gets an isolated worktree branched off `dev` so agents
can work in parallel without stepping on each other.
"""

import asyncio
import logging
import shutil
from pathlib import Path

logger = logging.getLogger("agent42.worktree")

WORKTREE_ROOT = Path("/tmp/agent42")


class WorktreeManager:
    """Create and tear down git worktrees for agent tasks."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        WORKTREE_ROOT.mkdir(parents=True, exist_ok=True)

    async def create(self, task_id: str, base_branch: str = "dev") -> Path:
        """Create a worktree for a task, branching from base_branch."""
        worktree_path = WORKTREE_ROOT / task_id
        branch_name = f"agent42/{task_id}"

        if worktree_path.exists():
            logger.warning(f"Worktree already exists: {worktree_path}")
            return worktree_path

        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "add", "-b", branch_name,
            str(worktree_path), base_branch,
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(
                f"git worktree add failed: {stderr.decode().strip()}"
            )

        logger.info(f"Created worktree: {worktree_path} (branch: {branch_name})")
        return worktree_path

    async def remove(self, task_id: str):
        """Remove a worktree and prune."""
        worktree_path = WORKTREE_ROOT / task_id
        if worktree_path.exists():
            shutil.rmtree(worktree_path)

        proc = await asyncio.create_subprocess_exec(
            "git", "worktree", "prune",
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        logger.info(f"Removed worktree for task {task_id}")

    async def commit(self, task_id: str, message: str):
        """Stage all changes and commit in a task's worktree."""
        worktree_path = WORKTREE_ROOT / task_id
        if not worktree_path.exists():
            raise FileNotFoundError(f"Worktree not found: {worktree_path}")

        add_proc = await asyncio.create_subprocess_exec(
            "git", "add", "-A",
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await add_proc.communicate()

        commit_proc = await asyncio.create_subprocess_exec(
            "git", "commit", "-m", message,
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await commit_proc.communicate()

        if commit_proc.returncode != 0:
            err = stderr.decode().strip()
            if "nothing to commit" in err:
                logger.info(f"Nothing to commit for task {task_id}")
                return
            raise RuntimeError(f"git commit failed: {err}")

        logger.info(f"Committed changes for task {task_id}")

    async def diff(self, task_id: str, base_branch: str = "dev") -> str:
        """Return the full diff of a worktree against the base branch."""
        worktree_path = WORKTREE_ROOT / task_id
        proc = await asyncio.create_subprocess_exec(
            "git", "diff", base_branch,
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()

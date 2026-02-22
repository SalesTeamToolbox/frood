"""
Git worktree lifecycle manager.

Each task gets an isolated worktree branched off `dev` so agents
can work in parallel without stepping on each other.

Security:
- Worktrees use a user-specific directory (not world-readable /tmp)
- Task IDs are sanitized to prevent path traversal
- Restrictive directory permissions (0o700)
- git add uses explicit file tracking instead of -A to avoid staging secrets
"""

import asyncio
import logging
import os
import re
import shutil
from pathlib import Path

logger = logging.getLogger("agent42.worktree")

# Use user-specific directory instead of world-readable /tmp
_WORKTREE_BASE = Path(
    os.getenv("AGENT42_WORKTREE_DIR", str(Path.home() / ".agent42" / "worktrees"))
)

# Only allow alphanumeric + hyphen in task IDs
_SAFE_ID_RE = re.compile(r"^[a-zA-Z0-9_-]+$")

# Files/patterns to exclude from git add (prevent accidental secret staging)
_GIT_ADD_EXCLUDE = [
    ".env",
    ".env.*",
    "*.key",
    "*.pem",
    "*.p12",
    "credentials*",
    "secrets*",
]


def _sanitize_task_id(task_id: str) -> str:
    """Validate task ID to prevent path traversal attacks."""
    if not task_id or not _SAFE_ID_RE.match(task_id):
        raise ValueError(
            f"Invalid task ID: '{task_id}'. "
            "Only alphanumeric characters, hyphens, and underscores are allowed."
        )
    return task_id


class WorktreeManager:
    """Create and tear down git worktrees for agent tasks."""

    def __init__(self, repo_path: str):
        self.repo_path = Path(repo_path).resolve()
        self._worktree_root = _WORKTREE_BASE
        self._worktree_root.mkdir(parents=True, exist_ok=True, mode=0o700)

    def _worktree_path(self, task_id: str) -> Path:
        """Get the worktree path for a sanitized task ID."""
        safe_id = _sanitize_task_id(task_id)
        return self._worktree_root / safe_id

    async def create(self, task_id: str, base_branch: str = "dev") -> Path:
        """Create a worktree for a task, branching from base_branch."""
        worktree_path = self._worktree_path(task_id)
        branch_name = f"agent42/{task_id}"

        if worktree_path.exists():
            logger.warning(f"Worktree already exists: {worktree_path}")
            return worktree_path

        proc = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "add",
            "-b",
            branch_name,
            str(worktree_path),
            base_branch,
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {stderr.decode().strip()}")

        # Set restrictive permissions
        worktree_path.chmod(0o700)

        logger.info(f"Created worktree: {worktree_path} (branch: {branch_name})")
        return worktree_path

    async def remove(self, task_id: str):
        """Remove a worktree and prune."""
        worktree_path = self._worktree_path(task_id)
        if worktree_path.exists():
            shutil.rmtree(worktree_path)

        proc = await asyncio.create_subprocess_exec(
            "git",
            "worktree",
            "prune",
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await proc.communicate()
        logger.info(f"Removed worktree for task {task_id}")

    async def commit(self, task_id: str, message: str):
        """Stage tracked files and new files, then commit in a task's worktree.

        Uses 'git add .' with a .gitignore that excludes sensitive files
        instead of 'git add -A' which could stage secrets.
        """
        worktree_path = self._worktree_path(task_id)
        if not worktree_path.exists():
            raise FileNotFoundError(f"Worktree not found: {worktree_path}")

        # Ensure .gitignore excludes sensitive patterns
        gitignore_path = worktree_path / ".gitignore"
        existing_ignores = ""
        if gitignore_path.exists():
            existing_ignores = gitignore_path.read_text()

        added_patterns = []
        for pattern in _GIT_ADD_EXCLUDE:
            if pattern not in existing_ignores:
                added_patterns.append(pattern)

        if added_patterns:
            with open(gitignore_path, "a") as f:
                f.write("\n# Agent42 safety rules\n")
                for p in added_patterns:
                    f.write(f"{p}\n")

        add_proc = await asyncio.create_subprocess_exec(
            "git",
            "add",
            ".",
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await add_proc.communicate()

        commit_proc = await asyncio.create_subprocess_exec(
            "git",
            "commit",
            "-m",
            message,
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
        worktree_path = self._worktree_path(task_id)
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            base_branch,
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        return stdout.decode()

    async def push(self, task_id: str) -> str:
        """Push the task's branch to origin."""
        worktree_path = self._worktree_path(task_id)
        branch_name = f"agent42/{task_id}"

        proc = await asyncio.create_subprocess_exec(
            "git",
            "push",
            "-u",
            "origin",
            branch_name,
            cwd=str(worktree_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()

        if proc.returncode != 0:
            raise RuntimeError(f"git push failed: {stderr.decode().strip()}")

        logger.info(f"Pushed branch {branch_name} for task {task_id}")
        return branch_name

    async def merge_to_base(self, task_id: str, base_branch: str = "dev") -> bool:
        """Merge a task's branch into the base branch (in the main repo)."""
        branch_name = f"agent42/{task_id}"

        # Checkout base branch
        checkout = await asyncio.create_subprocess_exec(
            "git",
            "checkout",
            base_branch,
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        await checkout.communicate()
        if checkout.returncode != 0:
            return False

        # Merge
        merge = await asyncio.create_subprocess_exec(
            "git",
            "merge",
            "--no-ff",
            branch_name,
            "-m",
            f"Merge agent42/{task_id}: task complete",
            cwd=str(self.repo_path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await merge.communicate()

        if merge.returncode != 0:
            logger.error(f"Merge failed for {task_id}: {stderr.decode().strip()}")
            # Abort the merge
            await asyncio.create_subprocess_exec(
                "git",
                "merge",
                "--abort",
                cwd=str(self.repo_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            return False

        logger.info(f"Merged {branch_name} into {base_branch}")
        return True

    async def cleanup_completed(self, task_ids: list[str]):
        """Clean up worktrees for completed tasks."""
        for task_id in task_ids:
            try:
                await self.remove(task_id)
            except Exception as e:
                logger.warning(f"Cleanup failed for {task_id}: {e}")

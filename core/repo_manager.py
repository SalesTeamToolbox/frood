"""
Multi-repository manager — register, clone, and manage project repositories.

Supports two modes for adding repos:
- Local: point to an existing git repository on disk
- GitHub: clone from a GitHub repo using a personal access token

Each repo gets a ``WorktreeManager`` so agents can work in isolated branches.

Security:
- GitHub tokens are never logged or persisted in the registry
- Git commands run in a sanitised environment (no Agent42 secrets)
- Paths are resolved and validated before registration
"""

import asyncio
import json
import logging
import os
import re
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

import aiofiles

logger = logging.getLogger("agent42.repo_manager")

# Slug must be URL-safe: lowercase alphanumeric + hyphens
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _make_slug(name: str) -> str:
    """Convert a display name to a URL-safe slug."""
    slug = _SLUG_RE.sub("-", name.lower()).strip("-")
    return slug or "repo"


def _sanitize_env() -> dict[str, str]:
    """Return a copy of os.environ without Agent42 secrets."""
    blocked = {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "DASHBOARD_PASSWORD",
        "DASHBOARD_PASSWORD_HASH",
        "JWT_SECRET",
        "DISCORD_BOT_TOKEN",
        "SLACK_BOT_TOKEN",
        "SLACK_APP_TOKEN",
        "TELEGRAM_BOT_TOKEN",
        "BRAVE_API_KEY",
        "REPLICATE_API_TOKEN",
        "LUMA_API_KEY",
        "BROWSER_GATEWAY_TOKEN",
        "GITHUB_TOKEN",
        "APPS_GITHUB_TOKEN",
    }
    return {k: v for k, v in os.environ.items() if k not in blocked}


@dataclass
class Repository:
    """Represents a connected project repository."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])
    name: str = ""
    slug: str = ""
    url: str = ""  # Git remote URL
    local_path: str = ""  # Absolute path on disk
    default_branch: str = "main"
    github_repo: str = ""  # "owner/repo" (empty if not GitHub)
    status: str = "active"  # active, cloning, error, archived
    tags: list = field(default_factory=list)
    error: str = ""
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Repository":
        data = data.copy()
        known = cls.__dataclass_fields__
        return cls(**{k: v for k, v in data.items() if k in known})


class RepositoryManager:
    """Manages multiple project repositories for Agent42."""

    def __init__(
        self,
        repos_json_path: str = ".agent42/repos.json",
        clone_dir: str = ".agent42/repos",
        github_token: str = "",
    ):
        self._data_path = Path(repos_json_path)
        self._clone_dir = Path(clone_dir)
        self._github_token = github_token
        self._repos: dict[str, Repository] = {}
        self._lock = asyncio.Lock()

    # -- Persistence -----------------------------------------------------------

    async def load(self):
        """Load repository registry from disk."""
        if not self._data_path.exists():
            return
        try:
            async with aiofiles.open(self._data_path) as f:
                data = json.loads(await f.read())
            for item in data:
                repo = Repository.from_dict(item)
                self._repos[repo.id] = repo
            logger.info("Loaded %d repo(s) from %s", len(self._repos), self._data_path)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning("Failed to load repos registry: %s", e)

    async def _persist(self):
        """Save repository registry to disk."""
        self._data_path.parent.mkdir(parents=True, exist_ok=True)
        data = [repo.to_dict() for repo in self._repos.values()]
        async with aiofiles.open(self._data_path, "w") as f:
            await f.write(json.dumps(data, indent=2))

    # -- CRUD ------------------------------------------------------------------

    async def add_local(
        self,
        name: str,
        local_path: str,
        default_branch: str = "main",
        tags: list | None = None,
    ) -> Repository:
        """Register an existing local git repository."""
        path = Path(local_path).resolve()
        if not path.exists():
            raise ValueError(f"Path does not exist: {path}")
        if not (path / ".git").exists():
            raise ValueError(f"Not a git repository: {path}")

        slug = _make_slug(name)
        # Ensure slug uniqueness
        existing_slugs = {r.slug for r in self._repos.values()}
        if slug in existing_slugs:
            slug = f"{slug}-{uuid.uuid4().hex[:4]}"

        # Try to detect remote URL
        url = await self._get_remote_url(path)
        # Detect github_repo from URL
        github_repo = self._extract_github_repo(url)

        repo = Repository(
            name=name,
            slug=slug,
            url=url,
            local_path=str(path),
            default_branch=default_branch,
            github_repo=github_repo,
            status="active",
            tags=tags or [],
        )
        async with self._lock:
            self._repos[repo.id] = repo
            await self._persist()
        logger.info("Added local repo: %s (%s)", name, path)
        return repo

    async def add_from_github(
        self,
        github_repo: str,
        default_branch: str = "main",
        tags: list | None = None,
        clone_path: str | None = None,
    ) -> Repository:
        """Clone a GitHub repository and register it."""
        if not self._github_token:
            raise ValueError("GitHub token is required to clone repositories")

        # Determine clone destination
        repo_name = github_repo.split("/")[-1] if "/" in github_repo else github_repo
        dest = Path(clone_path) if clone_path else self._clone_dir / repo_name
        dest = dest.resolve()

        slug = _make_slug(repo_name)
        existing_slugs = {r.slug for r in self._repos.values()}
        if slug in existing_slugs:
            slug = f"{slug}-{uuid.uuid4().hex[:4]}"

        clone_url = f"https://x-access-token:{self._github_token}@github.com/{github_repo}.git"

        repo = Repository(
            name=repo_name,
            slug=slug,
            url=f"https://github.com/{github_repo}.git",
            local_path=str(dest),
            default_branch=default_branch,
            github_repo=github_repo,
            status="cloning",
            tags=tags or [],
        )

        async with self._lock:
            self._repos[repo.id] = repo
            await self._persist()

        try:
            dest.parent.mkdir(parents=True, exist_ok=True)
            rc, stdout, stderr = await self._run_git(
                dest.parent, "clone", "--branch", default_branch, clone_url, str(dest)
            )
            if rc != 0:
                repo.status = "error"
                repo.error = stderr[:500]
                async with self._lock:
                    await self._persist()
                raise RuntimeError(f"git clone failed: {stderr[:200]}")

            repo.status = "active"
            repo.error = ""
            repo.updated_at = time.time()
            async with self._lock:
                await self._persist()
            logger.info("Cloned GitHub repo: %s -> %s", github_repo, dest)
        except Exception:
            if repo.status != "error":
                repo.status = "error"
                repo.error = "Clone failed"
                async with self._lock:
                    await self._persist()
            raise

        return repo

    async def remove(self, repo_id: str, delete_local: bool = False):
        """Remove a repository from the registry."""
        async with self._lock:
            repo = self._repos.pop(repo_id, None)
            if not repo:
                raise ValueError(f"Repository not found: {repo_id}")
            await self._persist()

        if delete_local and repo.local_path:
            import shutil

            path = Path(repo.local_path)
            if path.exists() and path.is_relative_to(self._clone_dir.resolve()):
                shutil.rmtree(path, ignore_errors=True)
                logger.info("Deleted local clone: %s", path)

        logger.info("Removed repo: %s (%s)", repo.name, repo_id)

    def get(self, repo_id: str) -> Repository | None:
        """Get a repository by ID."""
        return self._repos.get(repo_id)

    def get_by_slug(self, slug: str) -> Repository | None:
        """Get a repository by slug."""
        for repo in self._repos.values():
            if repo.slug == slug:
                return repo
        return None

    def list_repos(self) -> list[Repository]:
        """List all non-archived repositories."""
        return [r for r in self._repos.values() if r.status != "archived"]

    # -- Git operations --------------------------------------------------------

    async def list_branches(self, repo_id: str) -> list[str]:
        """List remote branches for a repository."""
        repo = self._repos.get(repo_id)
        if not repo or not repo.local_path:
            return []

        path = Path(repo.local_path)
        if not path.exists():
            return []

        # Fetch latest remote refs
        await self._run_git(path, "fetch", "--prune")

        rc, stdout, _ = await self._run_git(path, "branch", "-r", "--format=%(refname:short)")
        if rc != 0:
            return []

        branches = []
        for line in stdout.strip().splitlines():
            line = line.strip()
            if line and not line.endswith("/HEAD"):
                # Strip origin/ prefix
                if "/" in line:
                    line = line.split("/", 1)[1]
                if line not in branches:
                    branches.append(line)
        return sorted(branches)

    async def sync_repo(self, repo_id: str) -> str:
        """Fetch latest changes for a repository. Returns status message."""
        repo = self._repos.get(repo_id)
        if not repo:
            raise ValueError(f"Repository not found: {repo_id}")

        path = Path(repo.local_path)
        if not path.exists():
            raise ValueError(f"Local path does not exist: {path}")

        rc, stdout, stderr = await self._run_git(path, "fetch", "--all", "--prune")
        if rc != 0:
            return f"Fetch failed: {stderr[:200]}"

        repo.updated_at = time.time()
        async with self._lock:
            await self._persist()

        return f"Synced {repo.name}: fetch complete"

    # -- GitHub API ------------------------------------------------------------

    async def list_github_repos(self, token: str = "") -> list[dict]:
        """List repositories from the connected GitHub account."""
        tok = token or self._github_token
        if not tok:
            return []

        try:
            import httpx
        except ImportError:
            logger.warning("httpx not installed — cannot list GitHub repos")
            return []

        repos = []
        page = 1
        async with httpx.AsyncClient(timeout=30.0) as client:
            while True:
                resp = await client.get(
                    "https://api.github.com/user/repos",
                    headers={
                        "Authorization": f"Bearer {tok}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                    },
                    params={
                        "per_page": 100,
                        "page": page,
                        "sort": "updated",
                        "direction": "desc",
                    },
                )
                if resp.status_code != 200:
                    logger.warning("GitHub API error %d: %s", resp.status_code, resp.text[:200])
                    break

                batch = resp.json()
                if not batch:
                    break

                for r in batch:
                    repos.append(
                        {
                            "full_name": r.get("full_name", ""),
                            "name": r.get("name", ""),
                            "description": r.get("description") or "",
                            "default_branch": r.get("default_branch", "main"),
                            "private": r.get("private", False),
                            "html_url": r.get("html_url", ""),
                            "language": r.get("language") or "",
                            "updated_at": r.get("updated_at", ""),
                        }
                    )

                if len(batch) < 100:
                    break
                page += 1

        return repos

    # -- WorktreeManager factory -----------------------------------------------

    def get_worktree_manager(self, repo_id: str):
        """Return a WorktreeManager for the given repository."""
        from core.worktree_manager import WorktreeManager

        repo = self._repos.get(repo_id)
        if not repo or not repo.local_path:
            raise ValueError(f"Repository not found or has no local path: {repo_id}")

        path = Path(repo.local_path)
        if not path.exists():
            raise ValueError(f"Local path does not exist: {path}")

        return WorktreeManager(str(path))

    # -- Internal helpers ------------------------------------------------------

    async def _run_git(self, cwd: Path, *args: str) -> tuple[int, str, str]:
        """Run a git command with sanitised environment."""
        env = _sanitize_env()
        if self._github_token:
            env["GIT_ASKPASS"] = "echo"
            env["GIT_TERMINAL_PROMPT"] = "0"
        env["GIT_CONFIG_COUNT"] = "3"
        env["GIT_CONFIG_KEY_0"] = "commit.gpgsign"
        env["GIT_CONFIG_VALUE_0"] = "false"
        env["GIT_CONFIG_KEY_1"] = "user.name"
        env["GIT_CONFIG_VALUE_1"] = env.get("GIT_AUTHOR_NAME", "Agent42")
        env["GIT_CONFIG_KEY_2"] = "user.email"
        env["GIT_CONFIG_VALUE_2"] = env.get("GIT_AUTHOR_EMAIL", "agent42@localhost")

        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=str(cwd),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=120.0)
        stdout = stdout_b.decode() if stdout_b else ""
        stderr = stderr_b.decode() if stderr_b else ""
        return proc.returncode or 0, stdout, stderr

    async def _get_remote_url(self, path: Path) -> str:
        """Get the origin remote URL for a repo."""
        rc, stdout, _ = await self._run_git(path, "remote", "get-url", "origin")
        return stdout.strip() if rc == 0 else ""

    @staticmethod
    def _extract_github_repo(url: str) -> str:
        """Extract 'owner/repo' from a GitHub URL."""
        if not url:
            return ""
        # https://github.com/owner/repo.git or git@github.com:owner/repo.git
        m = re.search(r"github\.com[:/]([^/]+/[^/]+?)(?:\.git)?$", url)
        return m.group(1) if m else ""

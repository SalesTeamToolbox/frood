"""Tests for core.repo_manager — multi-repository management."""

from unittest.mock import AsyncMock, patch

import pytest

from core.repo_manager import Repository, RepositoryManager, _make_slug

# ---------------------------------------------------------------------------
# Repository dataclass
# ---------------------------------------------------------------------------


class TestRepository:
    def test_to_dict_from_dict_roundtrip(self):
        repo = Repository(
            id="abc123def456",
            name="my-project",
            slug="my-project",
            url="https://github.com/org/my-project.git",
            local_path="/tmp/repos/my-project",
            default_branch="main",
            github_repo="org/my-project",
            status="active",
            tags=["web", "python"],
        )
        d = repo.to_dict()
        restored = Repository.from_dict(d)
        assert restored.id == repo.id
        assert restored.name == repo.name
        assert restored.slug == repo.slug
        assert restored.url == repo.url
        assert restored.local_path == repo.local_path
        assert restored.default_branch == repo.default_branch
        assert restored.github_repo == repo.github_repo
        assert restored.status == repo.status
        assert restored.tags == repo.tags

    def test_from_dict_ignores_unknown_fields(self):
        data = {"id": "abc", "name": "test", "unknown_field": "ignored"}
        repo = Repository.from_dict(data)
        assert repo.id == "abc"
        assert repo.name == "test"
        assert not hasattr(repo, "unknown_field")

    def test_defaults(self):
        repo = Repository()
        assert len(repo.id) == 12
        assert repo.status == "active"
        assert repo.default_branch == "main"
        assert repo.tags == []


class TestMakeSlug:
    def test_basic(self):
        assert _make_slug("My Project") == "my-project"

    def test_special_chars(self):
        assert _make_slug("Hello World! #1") == "hello-world-1"

    def test_empty(self):
        assert _make_slug("") == "repo"


# ---------------------------------------------------------------------------
# RepositoryManager
# ---------------------------------------------------------------------------


class TestRepositoryManager:
    def setup_method(self):
        """Create a fresh manager for each test."""
        self.manager = RepositoryManager(
            repos_json_path="/tmp/test-repos.json",
            clone_dir="/tmp/test-clones",
            github_token="",
        )

    @pytest.mark.asyncio
    async def test_load_empty(self, tmp_path):
        """Load from a non-existent file should not crash."""
        mgr = RepositoryManager(repos_json_path=str(tmp_path / "nope.json"))
        await mgr.load()
        assert mgr.list_repos() == []

    @pytest.mark.asyncio
    async def test_persist_and_load(self, tmp_path):
        """Persist repos to disk and reload them."""
        json_path = str(tmp_path / "repos.json")
        mgr = RepositoryManager(repos_json_path=json_path)

        # Create a fake git repo for add_local
        repo_dir = tmp_path / "my-repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        with patch.object(mgr, "_get_remote_url", new_callable=AsyncMock, return_value=""):
            repo = await mgr.add_local("my-repo", str(repo_dir), "main")

        assert repo.status == "active"
        assert repo.slug == "my-repo"

        # Load into a fresh manager
        mgr2 = RepositoryManager(repos_json_path=json_path)
        await mgr2.load()
        assert len(mgr2.list_repos()) == 1
        assert mgr2.list_repos()[0].id == repo.id

    @pytest.mark.asyncio
    async def test_add_local_validates_path(self, tmp_path):
        """add_local should reject non-existent or non-git paths."""
        json_path = str(tmp_path / "repos.json")
        mgr = RepositoryManager(repos_json_path=json_path)

        with pytest.raises(ValueError, match="does not exist"):
            await mgr.add_local("nope", "/nonexistent/path")

        # Exists but not a git repo
        plain_dir = tmp_path / "plain"
        plain_dir.mkdir()
        with pytest.raises(ValueError, match="Not a git repository"):
            await mgr.add_local("nope", str(plain_dir))

    @pytest.mark.asyncio
    async def test_remove(self, tmp_path):
        """Remove a repo from the registry."""
        json_path = str(tmp_path / "repos.json")
        mgr = RepositoryManager(repos_json_path=json_path)

        repo_dir = tmp_path / "repo"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        with patch.object(mgr, "_get_remote_url", new_callable=AsyncMock, return_value=""):
            repo = await mgr.add_local("repo", str(repo_dir))

        assert len(mgr.list_repos()) == 1
        await mgr.remove(repo.id)
        assert len(mgr.list_repos()) == 0

    @pytest.mark.asyncio
    async def test_remove_nonexistent_raises(self):
        """Removing a non-existent repo should raise ValueError."""
        with pytest.raises(ValueError, match="not found"):
            await self.manager.remove("nonexistent-id")

    @pytest.mark.asyncio
    async def test_get_and_get_by_slug(self, tmp_path):
        json_path = str(tmp_path / "repos.json")
        mgr = RepositoryManager(repos_json_path=json_path)

        repo_dir = tmp_path / "proj"
        repo_dir.mkdir()
        (repo_dir / ".git").mkdir()

        with patch.object(mgr, "_get_remote_url", new_callable=AsyncMock, return_value=""):
            repo = await mgr.add_local("My Project", str(repo_dir))

        assert mgr.get(repo.id) is not None
        assert mgr.get(repo.id).name == "My Project"
        assert mgr.get_by_slug("my-project") is not None
        assert mgr.get("nonexistent") is None
        assert mgr.get_by_slug("nonexistent") is None

    @pytest.mark.asyncio
    async def test_unique_slugs(self, tmp_path):
        """Adding repos with the same name should produce unique slugs."""
        json_path = str(tmp_path / "repos.json")
        mgr = RepositoryManager(repos_json_path=json_path)

        for i in range(2):
            repo_dir = tmp_path / f"repo-{i}"
            repo_dir.mkdir()
            (repo_dir / ".git").mkdir()

        with patch.object(mgr, "_get_remote_url", new_callable=AsyncMock, return_value=""):
            r1 = await mgr.add_local("test", str(tmp_path / "repo-0"))
            r2 = await mgr.add_local("test", str(tmp_path / "repo-1"))

        assert r1.slug != r2.slug

    def test_extract_github_repo(self):
        """Extract owner/repo from various URL formats."""
        extract = RepositoryManager._extract_github_repo
        assert extract("https://github.com/org/repo.git") == "org/repo"
        assert extract("git@github.com:org/repo.git") == "org/repo"
        assert extract("https://github.com/org/repo") == "org/repo"
        assert extract("https://gitlab.com/org/repo") == ""
        assert extract("") == ""


# ---------------------------------------------------------------------------
# GitHub integration (mocked)
# ---------------------------------------------------------------------------


class TestGitHubIntegration:
    @pytest.mark.asyncio
    async def test_list_github_repos_no_token(self):
        mgr = RepositoryManager(github_token="")
        result = await mgr.list_github_repos()
        assert result == []

    @pytest.mark.asyncio
    async def test_list_github_repos_mocked(self):
        mgr = RepositoryManager(github_token="ghp_test123")

        from unittest.mock import MagicMock

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = [
            {
                "full_name": "org/repo",
                "name": "repo",
                "description": "A test repo",
                "default_branch": "main",
                "private": False,
                "html_url": "https://github.com/org/repo",
                "language": "Python",
                "updated_at": "2025-01-01T00:00:00Z",
            }
        ]
        mock_response.text = ""

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=mock_response)
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("httpx.AsyncClient", return_value=mock_client):
            repos = await mgr.list_github_repos()

        assert len(repos) == 1
        assert repos[0]["full_name"] == "org/repo"
        assert repos[0]["language"] == "Python"


# ---------------------------------------------------------------------------
# Task repo_id / branch backward compatibility
# ---------------------------------------------------------------------------


class TestTaskRepoFields:
    def test_task_with_repo_fields(self):
        from core.task_queue import Task

        task = Task(
            title="Fix bug",
            description="Fix the login bug",
            repo_id="abc123",
            branch="dev",
        )
        d = task.to_dict()
        assert d["repo_id"] == "abc123"
        assert d["branch"] == "dev"

        restored = Task.from_dict(d)
        assert restored.repo_id == "abc123"
        assert restored.branch == "dev"

    def test_task_without_repo_fields(self):
        from core.task_queue import Task

        task = Task(title="Research", description="Research something")
        assert task.repo_id == ""
        assert task.branch == ""

        d = task.to_dict()
        restored = Task.from_dict(d)
        assert restored.repo_id == ""
        assert restored.branch == ""

    def test_old_task_dict_without_repo_fields(self):
        """Backward compatibility: old task dicts without repo_id/branch."""
        from core.task_queue import Task

        old_dict = {
            "title": "Old task",
            "description": "No repo info",
            "task_type": "coding",
            "status": "pending",
        }
        task = Task.from_dict(old_dict)
        assert task.repo_id == ""
        assert task.branch == ""

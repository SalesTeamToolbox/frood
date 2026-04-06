"""Tests for Phase 37 standalone mode gating (STANDALONE-01 through STANDALONE-04)."""

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from dashboard.auth import get_current_user
from dashboard.server import create_app
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


def _make_client(standalone: bool = False, **kwargs) -> TestClient:
    """Create a TestClient for dashboard app with auth override.

    Provides MagicMock() for managers that trigger conditional route
    registration (app_manager, project_manager, repo_manager) so that
    those route groups are registered and testable.
    """
    defaults = {
        "tool_registry": ToolRegistry(),
        "skill_loader": None,
        "app_manager": MagicMock(),
        "project_manager": MagicMock(),
        "repo_manager": MagicMock(),
        "standalone": standalone,
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    return TestClient(app)


class _FakeTool(Tool):
    """Minimal tool for testing."""

    @property
    def name(self):
        return "fake_tool"

    @property
    def description(self):
        return "A fake tool for testing"

    @property
    def parameters(self):
        return {"type": "object", "properties": {}}

    async def execute(self, **kw):
        return ToolResult(output="ok")


class TestHealthStandaloneMode:
    """STANDALONE: /health reports standalone_mode flag."""

    def test_health_standalone_true(self):
        client = _make_client(standalone=True)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["standalone_mode"] is True

    def test_health_standalone_false(self):
        client = _make_client(standalone=False)
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert "standalone_mode" not in data


class TestStandaloneGuardGatedRoutes:
    """STANDALONE: Gated routes return 404 in standalone mode."""

    def test_workspaces_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/workspaces")
        assert resp.status_code == 404
        data = resp.json()
        assert data["standalone_mode"] is True
        assert "not available in standalone" in data["message"]

    def test_chat_sessions_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/chat/sessions")
        assert resp.status_code == 404

    def test_ide_tree_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/ide/tree")
        assert resp.status_code == 404

    def test_gsd_workstreams_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/gsd/workstreams")
        assert resp.status_code == 404

    def test_projects_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/projects")
        assert resp.status_code == 404

    def test_apps_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/apps")
        assert resp.status_code == 404

    def test_repos_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/repos")
        assert resp.status_code == 404

    def test_github_status_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/github/status")
        assert resp.status_code == 404

    def test_channels_gated(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/channels")
        assert resp.status_code == 404


class TestStandaloneRetainedRoutes:
    """STANDALONE: Retained routes work normally in standalone mode."""

    def test_tools_retained(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/tools")
        assert resp.status_code == 200

    def test_skills_retained(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/skills")
        assert resp.status_code == 200

    def test_providers_retained(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/providers")
        assert resp.status_code == 200

    def test_approvals_retained(self):
        client = _make_client(standalone=True)
        resp = client.get("/api/approvals")
        assert resp.status_code == 200


class TestStandaloneNotActiveByDefault:
    """STANDALONE: Routes work normally when standalone=False."""

    def test_workspaces_not_gated(self):
        client = _make_client(standalone=False)
        resp = client.get("/api/workspaces")
        assert resp.status_code != 404


class TestToolSourceField:
    """STANDALONE-02: Tool list includes source field."""

    def test_list_tools_has_source(self):
        reg = ToolRegistry()
        reg.register(_FakeTool())
        tools = reg.list_tools()
        assert len(tools) == 1
        assert tools[0]["source"] == "builtin"
        assert tools[0]["name"] == "fake_tool"

    def test_source_via_api(self):
        reg = ToolRegistry()
        reg.register(_FakeTool())
        client = _make_client(standalone=False, tool_registry=reg)
        resp = client.get("/api/tools")
        assert resp.status_code == 200
        data = resp.json()
        assert any(t["source"] == "builtin" for t in data)

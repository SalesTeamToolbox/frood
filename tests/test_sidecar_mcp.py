"""Tests for Phase 28 sidecar endpoints: routing, effectiveness, MCP tool proxy."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from dashboard.auth import create_token
from dashboard.sidecar import create_sidecar_app


@dataclass(frozen=True)
class FakeRoutingDecision:
    """Mimics core.tiered_routing_bridge.RoutingDecision."""

    provider: str = "cerebras"
    model: str = "llama3.1-70b"
    tier: str = "free"
    task_category: str = "coding"
    base_category: str = "coding"
    cost_estimate: float = 0.0


@pytest.fixture
def auth_headers():
    token = create_token("admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def mock_effectiveness():
    store = AsyncMock()
    store.get_recommendations = AsyncMock(
        return_value=[
            {
                "tool_name": "memory_tool",
                "task_type": "coding",
                "invocations": 12,
                "success_rate": 0.95,
                "avg_duration_ms": 200.0,
            },
            {
                "tool_name": "code_intel",
                "task_type": "coding",
                "invocations": 8,
                "success_rate": 0.88,
                "avg_duration_ms": 150.0,
            },
        ]
    )
    return store


@pytest.fixture
def mock_mcp_registry():
    registry = AsyncMock()
    text_content = MagicMock()
    text_content.text = "analysis result: score=0.85"
    registry.call_tool = AsyncMock(return_value=[text_content])
    return registry


@pytest.fixture
def sidecar_client(mock_effectiveness, mock_mcp_registry):
    app = create_sidecar_app(
        effectiveness_store=mock_effectiveness,
        mcp_registry=mock_mcp_registry,
    )
    return TestClient(app)


# ---------------------------------------------------------------------------
# POST /routing/resolve
# ---------------------------------------------------------------------------


class TestRoutingResolve:
    def test_routing_resolve_returns_decision(self, sidecar_client, auth_headers):
        resp = sidecar_client.post(
            "/routing/resolve",
            json={"taskType": "engineer", "agentId": "agent-1"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "provider" in data
        assert "model" in data
        assert "tier" in data
        assert "taskCategory" in data

    def test_routing_resolve_requires_auth(self, sidecar_client):
        resp = sidecar_client.post(
            "/routing/resolve",
            json={"taskType": "engineer", "agentId": "agent-1"},
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /effectiveness/recommendations
# ---------------------------------------------------------------------------


class TestEffectiveness:
    def test_effectiveness_returns_tools(self, sidecar_client, auth_headers, mock_effectiveness):
        resp = sidecar_client.post(
            "/effectiveness/recommendations",
            json={"taskType": "coding"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "tools" in data
        assert len(data["tools"]) == 2
        assert data["tools"][0]["name"] == "memory_tool"
        assert data["tools"][0]["successRate"] == 0.95
        assert data["tools"][0]["observations"] == 12

    def test_effectiveness_empty_when_no_store(self, auth_headers):
        app = create_sidecar_app(effectiveness_store=None)
        client = TestClient(app)
        resp = client.post(
            "/effectiveness/recommendations",
            json={"taskType": "coding"},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["tools"] == []

    def test_effectiveness_requires_auth(self, sidecar_client):
        resp = sidecar_client.post(
            "/effectiveness/recommendations",
            json={"taskType": "coding"},
        )
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# POST /mcp/tool
# ---------------------------------------------------------------------------


def _make_settings_with_allowlist(allowlist: str):
    """Create a mock settings object with a custom mcp_tool_allowlist value.

    Settings is a frozen dataclass, so we replace the module-level reference.
    """
    from core.config import settings as real_settings

    mock_settings = MagicMock(wraps=real_settings)
    mock_settings.mcp_tool_allowlist = allowlist
    return mock_settings


class TestMCPToolProxy:
    def test_mcp_tool_allowed_executes(
        self, sidecar_client, auth_headers, mock_mcp_registry, monkeypatch
    ):
        monkeypatch.setattr(
            "dashboard.sidecar.settings",
            _make_settings_with_allowlist("content_analyzer,memory_tool"),
        )
        resp = sidecar_client.post(
            "/mcp/tool",
            json={"toolName": "content_analyzer", "params": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["error"] is None
        assert "analysis result" in data["result"]
        mock_mcp_registry.call_tool.assert_awaited_once_with("content_analyzer", {})

    def test_mcp_tool_blocked_returns_403(self, sidecar_client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            "dashboard.sidecar.settings",
            _make_settings_with_allowlist("content_analyzer"),
        )
        resp = sidecar_client.post(
            "/mcp/tool",
            json={"toolName": "shell", "params": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 403
        data = resp.json()
        assert "not in allowlist" in data["error"]

    def test_mcp_tool_empty_allowlist_disabled(self, sidecar_client, auth_headers, monkeypatch):
        monkeypatch.setattr(
            "dashboard.sidecar.settings",
            _make_settings_with_allowlist(""),
        )
        resp = sidecar_client.post(
            "/mcp/tool",
            json={"toolName": "content_analyzer", "params": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "disabled" in data["error"]

    def test_mcp_tool_no_registry_returns_error(self, auth_headers, monkeypatch):
        monkeypatch.setattr(
            "dashboard.sidecar.settings",
            _make_settings_with_allowlist("content_analyzer"),
        )
        app = create_sidecar_app(mcp_registry=None)
        client = TestClient(app)
        resp = client.post(
            "/mcp/tool",
            json={"toolName": "content_analyzer", "params": {}},
            headers=auth_headers,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "not available" in data["error"]

    def test_mcp_tool_requires_auth(self, sidecar_client):
        resp = sidecar_client.post(
            "/mcp/tool",
            json={"toolName": "content_analyzer", "params": {}},
        )
        assert resp.status_code in (401, 403)

"""Tests for Phase 39 unified agent management endpoint (AGENT-01, AGENT-02).

Tests cover:
- TestUnifiedEndpoint: Happy path — Agent42 agents with source tag, embedded performance data,
  and merged Paperclip agents.
- TestUnifiedEndpointDegradation: Graceful degradation when Paperclip is unavailable.
- TestUnifiedEndpointNoUrl: Behavior when PAPERCLIP_API_URL is not configured.
"""

from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from core.agent_manager import AgentConfig
from dashboard.auth import AuthContext, get_current_user, require_admin
from dashboard.server import create_app


def _make_agent(agent_id: str, name: str, status: str = "active") -> AgentConfig:
    """Create a test AgentConfig with minimal fields."""
    return AgentConfig(
        id=agent_id,
        name=name,
        description=f"Test agent {name}",
        status=status,
        performance_score=0.75,
        total_runs=5,
        total_tokens=1000,
    )


def _make_effectiveness_store(success_rate: float = 0.85, task_volume: int = 10) -> MagicMock:
    """Create a mock effectiveness store that returns predictable stats."""
    store = MagicMock()
    store.get_agent_stats = AsyncMock(
        return_value={"success_rate": success_rate, "task_volume": task_volume}
    )
    return store


def _make_agent_manager(agents: list[AgentConfig] | None = None) -> MagicMock:
    """Create a mock agent manager with list_all() returning provided agents."""
    if agents is None:
        agents = [
            _make_agent("agent-1", "Worker Agent", "active"),
            _make_agent("agent-2", "Stopped Agent", "stopped"),
        ]
    manager = MagicMock()
    manager.list_all.return_value = agents
    return manager


def _make_client(
    agent_manager=None,
    effectiveness_store=None,
    paperclip_api_url: str = "",
    **kwargs,
) -> TestClient:
    """Create a TestClient with auth overrides for agent endpoints."""
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "app_manager": MagicMock(),
        "project_manager": MagicMock(),
        "repo_manager": MagicMock(),
        "agent_manager": agent_manager or _make_agent_manager(),
        "effectiveness_store": effectiveness_store or _make_effectiveness_store(),
    }
    defaults.update(kwargs)

    with patch("core.config.settings") as mock_settings:
        mock_settings.paperclip_api_url = paperclip_api_url
        mock_settings.paperclip_agents_path = "/api/agents"
        # Forward all other attribute access to real settings to avoid breakage
        mock_settings.rewards_enabled = False
        mock_settings.standalone_mode = False
        mock_settings.sidecar_enabled = False

        app = create_app(**defaults)
        app.dependency_overrides[get_current_user] = lambda: "test-user"
        app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
        return TestClient(app)


class TestUnifiedEndpoint:
    """AGENT-01: Unified endpoint happy path tests."""

    def test_returns_agent42_agents_with_source(self):
        """GET /api/agents/unified returns Agent42 agents each with source='agent42'."""
        agent_manager = _make_agent_manager()
        client = _make_client(agent_manager=agent_manager)

        resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert "agents" in data
        agents = data["agents"]
        assert len(agents) == 2
        for agent in agents:
            assert agent["source"] == "agent42"

    def test_embeds_performance_data(self):
        """AGENT-02: Each agent includes success_rate and performance_score inline (no N+1)."""
        effectiveness_store = _make_effectiveness_store(success_rate=0.85, task_volume=10)
        agent_manager = _make_agent_manager()
        client = _make_client(agent_manager=agent_manager, effectiveness_store=effectiveness_store)

        resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        agents = resp.json()["agents"]
        assert len(agents) > 0
        for agent in agents:
            assert "success_rate" in agent, f"Missing success_rate in agent {agent.get('id')}"
            assert "performance_score" in agent, (
                f"Missing performance_score in agent {agent.get('id')}"
            )
            assert agent["success_rate"] == 0.85

    def test_merges_paperclip_agents(self):
        """When PAPERCLIP_API_URL is set and Paperclip responds, merges with source='paperclip'."""
        paperclip_response = {
            "agents": [
                {"id": "pc-agent-1", "name": "Paperclip Agent"},
            ]
        }

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = paperclip_response

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            client = _make_client(paperclip_api_url="http://paperclip:3000")
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        agents = data["agents"]

        # Should have Agent42 agents + Paperclip agents
        sources = [a["source"] for a in agents]
        assert "agent42" in sources
        assert "paperclip" in sources

        # Paperclip agents have manage_url
        paperclip_agents = [a for a in agents if a["source"] == "paperclip"]
        assert len(paperclip_agents) == 1
        assert "manage_url" in paperclip_agents[0]
        assert "http://paperclip:3000" in paperclip_agents[0]["manage_url"]

        assert data["paperclip_unavailable"] is False


class TestUnifiedEndpointDegradation:
    """Graceful degradation when Paperclip is unavailable."""

    def test_paperclip_timeout(self):
        """When Paperclip times out, returns Agent42 agents only with paperclip_unavailable=true."""
        import httpx

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            client = _make_client(paperclip_api_url="http://paperclip:3000")
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["paperclip_unavailable"] is True
        # Should still have Agent42 agents
        agents = data["agents"]
        assert len(agents) == 2
        for agent in agents:
            assert agent["source"] == "agent42"

    def test_paperclip_error_status(self):
        """When Paperclip returns non-200, returns Agent42 agents only with paperclip_unavailable=true."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.get = AsyncMock(return_value=mock_response)

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            client = _make_client(paperclip_api_url="http://paperclip:3000")
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["paperclip_unavailable"] is True
        assert all(a["source"] == "agent42" for a in data["agents"])

    def test_paperclip_connection_error(self):
        """When Paperclip connection fails, returns Agent42 agents only with paperclip_unavailable=true."""
        import httpx

        mock_client_instance = AsyncMock()
        mock_client_instance.__aenter__ = AsyncMock(return_value=mock_client_instance)
        mock_client_instance.__aexit__ = AsyncMock(return_value=None)
        mock_client_instance.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("httpx.AsyncClient", return_value=mock_client_instance):
            client = _make_client(paperclip_api_url="http://paperclip:3000")
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["paperclip_unavailable"] is True
        assert all(a["source"] == "agent42" for a in data["agents"])


class TestUnifiedEndpointNoUrl:
    """Behavior when PAPERCLIP_API_URL is not configured."""

    def test_skips_proxy_when_no_url(self):
        """When PAPERCLIP_API_URL is empty, proxy is skipped and paperclip_unavailable=false."""
        client = _make_client(paperclip_api_url="")
        resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["paperclip_unavailable"] is False
        agents = data["agents"]
        assert len(agents) == 2
        for agent in agents:
            assert agent["source"] == "agent42"

    def test_no_agent_manager(self):
        """When agent_manager is None, endpoint returns empty list gracefully."""
        with patch("core.config.settings") as mock_settings:
            mock_settings.paperclip_api_url = ""
            mock_settings.paperclip_agents_path = "/api/agents"
            mock_settings.rewards_enabled = False
            mock_settings.standalone_mode = False
            mock_settings.sidecar_enabled = False

            app = create_app(
                tool_registry=None,
                skill_loader=None,
                app_manager=MagicMock(),
                project_manager=MagicMock(),
                repo_manager=MagicMock(),
                agent_manager=None,
            )
            app.dependency_overrides[get_current_user] = lambda: "test-user"
            app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
            client = TestClient(app)

        resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["agents"] == []
        assert data["paperclip_unavailable"] is False

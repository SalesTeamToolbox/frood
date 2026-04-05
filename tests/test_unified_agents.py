"""Tests for Phase 39 unified agent management endpoint and frontend (AGENT-01 through AGENT-04).

Tests cover:
- TestUnifiedEndpoint: Happy path — Agent42 agents with source tag, embedded performance data,
  and merged Paperclip agents.
- TestUnifiedEndpointDegradation: Graceful degradation when Paperclip is unavailable.
- TestUnifiedEndpointNoUrl: Behavior when PAPERCLIP_API_URL is not configured.
- TestFrontendContent: Static analysis of app.js for unified endpoint and UI elements.
- TestCreateFormSourceBadge: app.js agentShowCreate includes Agent42 badge.
- TestTemplateBadge: app.js agentShowTemplates includes Agent42 badge.
- TestStylesheet: style.css contains all required new CSS classes.
- TestPaperclipReadOnly: app.js contains Paperclip read-only UI elements.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from core.agent_manager import AgentConfig
from dashboard.auth import AuthContext, get_current_user, require_admin
from dashboard.server import create_app

_APP_JS = Path("dashboard/frontend/dist/app.js").read_text(encoding="utf-8")
_STYLE_CSS = Path("dashboard/frontend/dist/style.css").read_text(encoding="utf-8")


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
    **kwargs,
) -> TestClient:
    """Create a TestClient with auth overrides for agent endpoints.

    NOTE: Does NOT patch settings. Callers needing non-default settings
    (e.g. paperclip_api_url) must wrap their test in a settings patch that
    stays active during request execution.
    """
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

    app = create_app(**defaults)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
    return TestClient(app)


def _settings_mock(paperclip_api_url: str = "") -> MagicMock:
    """Build a settings mock with required attributes for the unified endpoint."""
    m = MagicMock()
    m.paperclip_api_url = paperclip_api_url
    m.paperclip_agents_path = "/api/agents"
    m.rewards_enabled = False
    m.standalone_mode = False
    m.sidecar_enabled = False
    return m


class TestUnifiedEndpoint:
    """AGENT-01: Unified endpoint happy path tests."""

    def test_returns_agent42_agents_with_source(self):
        """GET /api/agents/unified returns Agent42 agents each with source='agent42'."""
        with patch("core.config.settings", _settings_mock()):
            client = _make_client()
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
        with patch("core.config.settings", _settings_mock()):
            client = _make_client(effectiveness_store=effectiveness_store)
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

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.get = AsyncMock(return_value=mock_response)

        with (
            patch("dashboard.server.settings", _settings_mock("http://paperclip:3000")),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            client = _make_client()
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        agents = data["agents"]

        sources = [a["source"] for a in agents]
        assert "agent42" in sources
        assert "paperclip" in sources

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

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        with (
            patch("dashboard.server.settings", _settings_mock("http://paperclip:3000")),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            client = _make_client()
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["paperclip_unavailable"] is True
        agents = data["agents"]
        assert len(agents) == 2
        for agent in agents:
            assert agent["source"] == "agent42"

    def test_paperclip_error_status(self):
        """When Paperclip returns non-200, returns Agent42 agents only with paperclip_unavailable=true."""
        mock_response = MagicMock()
        mock_response.status_code = 503

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.get = AsyncMock(return_value=mock_response)

        with (
            patch("dashboard.server.settings", _settings_mock("http://paperclip:3000")),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            client = _make_client()
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["paperclip_unavailable"] is True
        assert all(a["source"] == "agent42" for a in data["agents"])

    def test_paperclip_connection_error(self):
        """When Paperclip connection fails, returns Agent42 agents only with paperclip_unavailable=true."""
        import httpx

        mock_http = AsyncMock()
        mock_http.__aenter__ = AsyncMock(return_value=mock_http)
        mock_http.__aexit__ = AsyncMock(return_value=None)
        mock_http.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with (
            patch("dashboard.server.settings", _settings_mock("http://paperclip:3000")),
            patch("httpx.AsyncClient", return_value=mock_http),
        ):
            client = _make_client()
            resp = client.get("/api/agents/unified")

        assert resp.status_code == 200
        data = resp.json()
        assert data["paperclip_unavailable"] is True
        assert all(a["source"] == "agent42" for a in data["agents"])


class TestUnifiedEndpointNoUrl:
    """Behavior when PAPERCLIP_API_URL is not configured."""

    def test_skips_proxy_when_no_url(self):
        """When PAPERCLIP_API_URL is empty, proxy is skipped and paperclip_unavailable=false."""
        with patch("core.config.settings", _settings_mock("")):
            client = _make_client()
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
        with patch("core.config.settings", _settings_mock("")):
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


class TestFrontendContent:
    """AGENT-01, AGENT-02: Static analysis of app.js for unified endpoint and UI elements."""

    def test_app_js_uses_unified_endpoint(self):
        """app.js fetches from /api/agents/unified (not legacy /api/agents)."""
        assert "api/agents/unified" in _APP_JS

    def test_app_js_has_source_badges(self):
        """app.js references both badge-agent42 and badge-paperclip CSS classes."""
        assert "badge-agent42" in _APP_JS
        assert "badge-paperclip" in _APP_JS

    def test_app_js_has_relative_time(self):
        """app.js contains _relativeTime helper function."""
        assert "_relativeTime" in _APP_JS

    def test_app_js_has_sparkline(self):
        """app.js contains _makeSparkline helper function."""
        assert "_makeSparkline" in _APP_JS

    def test_app_js_has_degradation_banner(self):
        """app.js references degradation-banner CSS class for Paperclip unavailable state."""
        assert "degradation-banner" in _APP_JS

    def test_app_js_has_filter_controls(self):
        """app.js contains agent source/status filter controls (agentFilterSource)."""
        assert "agentFilterSource" in _APP_JS

    def test_app_js_has_avg_success_stat(self):
        """app.js stats row includes Avg Success metric."""
        assert "Avg Success" in _APP_JS


class TestCreateFormSourceBadge:
    """AGENT-03: agentShowCreate includes Agent42 source badge."""

    def test_create_form_has_agent42_badge(self):
        """agentShowCreate section in app.js contains badge-agent42 and 'Agent42' text."""
        # Find agentShowCreate function block
        start = _APP_JS.find("function agentShowCreate()")
        end = _APP_JS.find("\nfunction ", start + 1)
        section = _APP_JS[start:end] if end != -1 else _APP_JS[start:]
        assert "badge-agent42" in section, "badge-agent42 not found in agentShowCreate"
        assert "Agent42" in section, "'Agent42' label not found in agentShowCreate"


class TestTemplateBadge:
    """AGENT-04: agentShowTemplates includes Agent42 source badge."""

    def test_template_cards_have_source_badge(self):
        """agentShowTemplates section in app.js adds badge-agent42 to template cards."""
        start = _APP_JS.find("function agentShowTemplates()")
        end = _APP_JS.find("\nfunction ", start + 1)
        section = _APP_JS[start:end] if end != -1 else _APP_JS[start:]
        assert "badge-agent42" in section, "badge-agent42 not found in agentShowTemplates"

    def test_template_creation_uses_agents_api(self):
        """agentCreateFromTemplate still POSTs to /api/agents (not unified endpoint)."""
        start = _APP_JS.find("async function agentCreateFromTemplate(")
        end = _APP_JS.find("\nasync function ", start + 1)
        if end == -1:
            end = _APP_JS.find("\nfunction ", start + 1)
        section = _APP_JS[start:end] if end != -1 else _APP_JS[start:]
        assert '"/api/agents"' in section, "agentCreateFromTemplate should POST to /api/agents"
        assert "unified" not in section, "agentCreateFromTemplate must not use unified endpoint"


class TestStylesheet:
    """Supporting: style.css contains all required new CSS classes."""

    def test_style_has_agent42_badge(self):
        """style.css contains .badge-agent42 rule."""
        assert ".badge-agent42" in _STYLE_CSS

    def test_style_has_paperclip_badge(self):
        """style.css contains .badge-paperclip rule."""
        assert ".badge-paperclip" in _STYLE_CSS

    def test_style_has_sparkline(self):
        """style.css contains .sparkline rule."""
        assert ".sparkline" in _STYLE_CSS

    def test_style_has_degradation_banner(self):
        """style.css contains .degradation-banner rule."""
        assert ".degradation-banner" in _STYLE_CSS


class TestPaperclipReadOnly:
    """AGENT-01, D-03/D-08: app.js contains Paperclip read-only UI elements."""

    def test_app_js_has_manage_in_paperclip(self):
        """app.js contains 'Manage in Paperclip' deep link text."""
        assert "Manage in Paperclip" in _APP_JS

    def test_app_js_has_readonly_card(self):
        """app.js assigns 'readonly' CSS class to Paperclip agent cards."""
        assert "readonly" in _APP_JS

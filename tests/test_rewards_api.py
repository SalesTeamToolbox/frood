"""
Tests for the rewards API endpoints (Phase 4 Dashboard).

Covers:
- TestRewardsAuth: 401 for unauthenticated requests on all 5 endpoints
- TestRewardsEndpoints: Happy-path responses with valid JWT tokens
- TestTierUpdateBroadcast: TierRecalcLoop ws_manager broadcast behavior
"""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from dashboard.auth import create_token
from dashboard.server import create_app
from dashboard.websocket_manager import WebSocketManager


def _make_mock_agent(agent_id: str = "agent-1") -> MagicMock:
    """Build a realistic AgentConfig mock."""
    mock_agent = MagicMock()
    mock_agent.id = agent_id
    mock_agent.effective_tier.return_value = "gold"
    mock_agent.reward_tier = "gold"
    mock_agent.performance_score = 0.85
    mock_agent.tier_override = None
    return mock_agent


def make_client() -> TestClient:
    """Create a TestClient with mocked rewards-related dependencies."""
    ws_manager = WebSocketManager()

    mock_agent = _make_mock_agent("agent-1")

    mock_am = MagicMock()
    mock_am.list_all.return_value = [mock_agent]
    mock_am.get.return_value = mock_agent
    mock_am.update.return_value = mock_agent

    mock_rs = MagicMock()
    mock_rs.score = AsyncMock(return_value=0.85)
    mock_rs._run_recalculation = AsyncMock()

    mock_es = MagicMock()
    mock_es.get_agent_stats = AsyncMock(
        return_value={"task_volume": 10, "success_rate": 0.85, "avg_speed": 1.2}
    )

    app = create_app(
        ws_manager=ws_manager,
        agent_manager=mock_am,
        reward_system=mock_rs,
        effectiveness_store=mock_es,
    )
    return TestClient(app)


def _admin_headers() -> dict:
    """Return Bearer Authorization header with admin JWT."""
    token = create_token("admin")
    return {"Authorization": f"Bearer {token}"}


class TestRewardsAuth:
    """All 5 rewards endpoints must return 401 for unauthenticated requests."""

    def test_get_rewards_requires_auth(self):
        assert make_client().get("/api/rewards").status_code == 401

    def test_toggle_requires_auth(self):
        assert make_client().post("/api/rewards/toggle", json={"enabled": True}).status_code == 401

    def test_performance_requires_auth(self):
        assert make_client().get("/api/agents/agent-1/performance").status_code == 401

    def test_tier_override_requires_auth(self):
        assert (
            make_client()
            .patch("/api/agents/agent-1/reward-tier", json={"tier": "gold"})
            .status_code
            == 401
        )

    def test_recalculate_requires_auth(self):
        assert make_client().post("/api/admin/rewards/recalculate-all").status_code == 401


class TestRewardsEndpoints:
    """Happy-path tests for rewards endpoints with valid JWT auth."""

    def test_get_rewards_returns_status(self):
        client = make_client()
        resp = client.get("/api/rewards", headers=_admin_headers())
        assert resp.status_code == 200
        data = resp.json()
        assert "enabled" in data
        assert "config" in data
        assert "tier_counts" in data
        counts = data["tier_counts"]
        assert set(counts.keys()) >= {"bronze", "silver", "gold"}

    def test_toggle_rewards_on(self):
        client = make_client()
        resp = client.post(
            "/api/rewards/toggle",
            json={"enabled": True},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is True

    def test_toggle_rewards_off(self):
        client = make_client()
        resp = client.post(
            "/api/rewards/toggle",
            json={"enabled": False},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["enabled"] is False

    def test_agent_performance_returns_fields(self):
        client = make_client()
        resp = client.get(
            "/api/agents/agent-1/performance",
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent-1"
        assert "tier" in data
        assert "performance_score" in data
        assert "task_count" in data
        assert "success_rate" in data

    def test_agent_performance_unknown_agent_returns_404(self):
        ws_manager = WebSocketManager()
        mock_am = MagicMock()
        mock_am.list_all.return_value = []
        mock_am.get.return_value = None
        mock_rs = MagicMock()
        mock_es = MagicMock()
        app = create_app(
            ws_manager=ws_manager,
            agent_manager=mock_am,
            reward_system=mock_rs,
            effectiveness_store=mock_es,
        )
        client = TestClient(app)
        resp = client.get(
            "/api/agents/no-such-agent/performance",
            headers=_admin_headers(),
        )
        assert resp.status_code == 404

    def test_set_reward_tier_override(self):
        client = make_client()
        resp = client.patch(
            "/api/agents/agent-1/reward-tier",
            json={"tier": "silver"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["agent_id"] == "agent-1"
        assert "tier_override" in data

    def test_set_reward_tier_invalid_returns_422(self):
        client = make_client()
        resp = client.patch(
            "/api/agents/agent-1/reward-tier",
            json={"tier": "diamond"},
            headers=_admin_headers(),
        )
        assert resp.status_code == 422

    def test_recalculate_all_returns_queued(self):
        client = make_client()
        resp = client.post(
            "/api/admin/rewards/recalculate-all",
            headers=_admin_headers(),
        )
        assert resp.status_code == 202
        assert resp.json()["status"] == "queued"

    def test_endpoints_not_registered_without_reward_system(self):
        """Rewards endpoints should only be registered when both agent_manager and reward_system are truthy."""
        ws_manager = WebSocketManager()
        mock_am = MagicMock()
        # reward_system=None — no rewards endpoints
        app = create_app(
            ws_manager=ws_manager,
            agent_manager=mock_am,
            reward_system=None,
        )
        client = TestClient(app)
        assert client.get("/api/rewards").status_code == 404

    def test_endpoints_not_registered_without_agent_manager(self):
        """Rewards endpoints should only be registered when both agent_manager and reward_system are truthy."""
        ws_manager = WebSocketManager()
        mock_rs = MagicMock()
        # agent_manager=None — no rewards endpoints
        app = create_app(
            ws_manager=ws_manager,
            agent_manager=None,
            reward_system=mock_rs,
        )
        client = TestClient(app)
        assert client.get("/api/rewards").status_code == 404


class TestTierUpdateBroadcast:
    """Test that TierRecalcLoop broadcasts tier_update event after recalculation."""

    @pytest.mark.asyncio
    async def test_broadcast_called_after_tier_change(self):
        """_run_recalculation should broadcast tier_update with changed agents."""
        from core.reward_system import TierRecalcLoop

        mock_agent = _make_mock_agent("agent-1")
        mock_agent.tier_override = None
        mock_agent.reward_tier = "bronze"  # Will change to gold after recalc

        mock_am = MagicMock()
        mock_am.list_all.return_value = [mock_agent]
        mock_am.update.return_value = mock_agent

        mock_rs = MagicMock()
        mock_rs.score = AsyncMock(return_value=0.9)

        mock_es = MagicMock()
        mock_es.get_agent_stats = AsyncMock(return_value={"task_volume": 20, "success_rate": 0.9})

        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()

        loop = TierRecalcLoop(
            agent_manager=mock_am,
            reward_system=mock_rs,
            effectiveness_store=mock_es,
            ws_manager=mock_ws,
        )

        await loop._run_recalculation()

        # broadcast must be called exactly once (not per-agent)
        mock_ws.broadcast.assert_called_once()
        call_args = mock_ws.broadcast.call_args
        assert call_args[0][0] == "tier_update"
        payload = call_args[0][1]
        assert "agents" in payload
        assert len(payload["agents"]) >= 1
        agent_entry = payload["agents"][0]
        assert "agent_id" in agent_entry
        assert "tier" in agent_entry
        assert "score" in agent_entry

    @pytest.mark.asyncio
    async def test_no_broadcast_when_no_tier_changes(self):
        """_run_recalculation should NOT broadcast if no tiers changed."""
        from core.reward_system import TierRecalcLoop

        mock_agent = _make_mock_agent("agent-1")
        mock_agent.tier_override = None
        mock_agent.reward_tier = "gold"  # same as what determinator returns

        mock_am = MagicMock()
        mock_am.list_all.return_value = [mock_agent]
        mock_am.update.return_value = mock_agent

        mock_rs = MagicMock()
        mock_rs.score = AsyncMock(return_value=0.9)

        mock_es = MagicMock()
        mock_es.get_agent_stats = AsyncMock(return_value={"task_volume": 20, "success_rate": 0.9})

        mock_ws = MagicMock()
        mock_ws.broadcast = AsyncMock()

        loop = TierRecalcLoop(
            agent_manager=mock_am,
            reward_system=mock_rs,
            effectiveness_store=mock_es,
            ws_manager=mock_ws,
        )

        await loop._run_recalculation()

        # No tier changed, so broadcast should NOT be called
        mock_ws.broadcast.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_broadcast_when_no_ws_manager(self):
        """_run_recalculation with ws_manager=None should not broadcast (graceful degradation)."""
        from core.reward_system import TierRecalcLoop

        mock_agent = _make_mock_agent("agent-1")
        mock_agent.tier_override = None
        mock_agent.reward_tier = "bronze"

        mock_am = MagicMock()
        mock_am.list_all.return_value = [mock_agent]
        mock_am.update.return_value = mock_agent

        mock_rs = MagicMock()
        mock_rs.score = AsyncMock(return_value=0.9)

        mock_es = MagicMock()
        mock_es.get_agent_stats = AsyncMock(return_value={"task_volume": 20, "success_rate": 0.9})

        loop = TierRecalcLoop(
            agent_manager=mock_am,
            reward_system=mock_rs,
            effectiveness_store=mock_es,
            ws_manager=None,  # No ws_manager — graceful degradation
        )

        # Should not raise
        await loop._run_recalculation()


class TestEffectiveTierInAgentDict:
    """effective_tier must appear in AgentConfig.to_dict() output."""

    def test_effective_tier_in_to_dict(self):
        from core.agent_manager import AgentConfig

        a = AgentConfig(name="test", id="t1", reward_tier="gold")
        d = a.to_dict()
        assert "effective_tier" in d, "effective_tier missing from to_dict"
        assert d["effective_tier"] == "gold"

    def test_effective_tier_override_in_to_dict(self):
        from core.agent_manager import AgentConfig

        a = AgentConfig(name="test", id="t2", reward_tier="bronze", tier_override="silver")
        d = a.to_dict()
        assert d["effective_tier"] == "silver"

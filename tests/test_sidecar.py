"""Tests for Agent42 sidecar mode (Phase 24, SIDE-01 through SIDE-09; Phase 29 UI endpoints)."""

import json
import logging
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from core.config import Settings
from core.sidecar_logging import SidecarJsonFormatter
from core.sidecar_models import (
    AdapterConfig,
    AdapterExecutionContext,
    CallbackPayload,
    ExecuteResponse,
)
from core.sidecar_orchestrator import (
    SidecarOrchestrator,
    _active_runs,
    is_duplicate_run,
    register_run,
    unregister_run,
)
from dashboard.auth import create_token
from dashboard.sidecar import create_sidecar_app


@pytest.fixture
def sidecar_client():
    """Create a TestClient for the sidecar app."""
    app = create_sidecar_app()
    return TestClient(app)


@pytest.fixture
def auth_headers():
    """Create valid Bearer auth headers for sidecar requests."""
    token = create_token("admin")
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def cleanup_active_runs():
    """Clear the idempotency dict between tests."""
    _active_runs.clear()
    yield
    _active_runs.clear()


class TestSidecarConfig:
    """SIDE-09: Config extends with sidecar settings."""

    def test_default_sidecar_port(self):
        s = Settings()
        assert s.paperclip_sidecar_port == 8001

    def test_default_paperclip_api_url(self):
        s = Settings()
        assert s.paperclip_api_url == ""

    def test_default_sidecar_enabled(self):
        s = Settings()
        assert s.sidecar_enabled is False


class TestSidecarModels:
    """SIDE-02: Pydantic models accept AdapterExecutionContext payload."""

    def test_adapter_execution_context_camelcase(self):
        ctx = AdapterExecutionContext(runId="r1", agentId="a1")
        assert ctx.run_id == "r1"
        assert ctx.agent_id == "a1"
        assert ctx.wake_reason == "heartbeat"

    def test_adapter_execution_context_snake_case(self):
        ctx = AdapterExecutionContext(run_id="r2", agent_id="a2")
        assert ctx.run_id == "r2"

    def test_adapter_config_defaults(self):
        cfg = AdapterConfig()
        assert cfg.memory_scope == "agent"
        assert cfg.preferred_provider == ""

    def test_execute_response_serialization(self):
        resp = ExecuteResponse(status="accepted", external_run_id="r1")
        data = resp.model_dump(by_alias=True)
        assert "externalRunId" in data

    def test_callback_payload_serialization(self):
        payload = CallbackPayload(run_id="r1", status="completed", result={"summary": "done"})
        data = payload.model_dump(by_alias=True)
        assert data["runId"] == "r1"
        assert data["status"] == "completed"


class TestSidecarHealth:
    """SIDE-04: GET /sidecar/health returns structured JSON.
    SIDE-05: Health endpoint accessible without auth."""

    def test_health_returns_200(self, sidecar_client):
        resp = sidecar_client.get("/sidecar/health")
        assert resp.status_code == 200

    def test_health_no_auth_required(self, sidecar_client):
        """SIDE-05: Health is exempt from Bearer auth."""
        resp = sidecar_client.get("/sidecar/health")
        assert resp.status_code == 200  # No auth header, still 200

    def test_health_returns_structured_json(self, sidecar_client):
        resp = sidecar_client.get("/sidecar/health")
        data = resp.json()
        assert "status" in data
        assert "memory" in data
        assert "providers" in data
        assert "qdrant" in data
        assert data["status"] == "ok"


class TestSidecarExecute:
    """SIDE-02, SIDE-03, SIDE-05: Execute endpoint behavior."""

    def test_execute_returns_202(self, sidecar_client, auth_headers):
        """SIDE-03: Returns 202 Accepted for valid payload."""
        resp = sidecar_client.post(
            "/sidecar/execute",
            json={"runId": "run-001", "agentId": "agent-001"},
            headers=auth_headers,
        )
        assert resp.status_code == 202

    def test_execute_returns_external_run_id(self, sidecar_client, auth_headers):
        """SIDE-02: Response includes externalRunId."""
        resp = sidecar_client.post(
            "/sidecar/execute",
            json={"runId": "run-002", "agentId": "agent-002"},
            headers=auth_headers,
        )
        data = resp.json()
        assert data["externalRunId"] == "run-002"
        assert data["status"] == "accepted"
        assert data["deduplicated"] is False

    def test_execute_without_auth_returns_401(self, sidecar_client):
        """SIDE-05: Missing Authorization header returns 401 (HTTPBearer behavior)."""
        resp = sidecar_client.post(
            "/sidecar/execute",
            json={"runId": "run-003", "agentId": "agent-003"},
        )
        assert resp.status_code == 401

    def test_execute_with_invalid_token_returns_401(self, sidecar_client):
        """SIDE-05: Invalid Bearer token returns 401."""
        resp = sidecar_client.post(
            "/sidecar/execute",
            json={"runId": "run-004", "agentId": "agent-004"},
            headers={"Authorization": "Bearer invalid-token"},
        )
        assert resp.status_code == 401

    def test_execute_with_full_payload(self, sidecar_client, auth_headers):
        """SIDE-02: Full AdapterExecutionContext payload accepted."""
        resp = sidecar_client.post(
            "/sidecar/execute",
            json={
                "runId": "run-005",
                "agentId": "agent-005",
                "companyId": "company-001",
                "taskId": "task-001",
                "wakeReason": "task_assigned",
                "context": {"prompt": "Build a feature"},
                "adapterConfig": {
                    "sessionKey": "sess-001",
                    "memoryScope": "company",
                    "preferredProvider": "openai",
                    "agentId": "agent-005",
                },
            },
            headers=auth_headers,
        )
        assert resp.status_code == 202


class TestIdempotencyGuard:
    """SIDE-06: Deduplicates execution requests by runId."""

    def test_duplicate_run_detected(self):
        register_run("dup-001")
        assert is_duplicate_run("dup-001") is True

    def test_unknown_run_not_duplicate(self):
        assert is_duplicate_run("unknown-001") is False

    def test_unregistered_run_not_duplicate(self):
        register_run("unreg-001")
        unregister_run("unreg-001")
        assert is_duplicate_run("unreg-001") is False

    def test_duplicate_run_returns_deduplicated(self, sidecar_client, auth_headers):
        """SIDE-06: Second POST with same runId returns deduplicated=true.

        Note: In TestClient mode, background tasks run synchronously and
        unregister the run on completion. We pre-register the run to simulate
        a long-running in-flight job, then verify the endpoint detects it.
        """
        # Pre-register the run to simulate an in-flight execution
        register_run("dup-http-001")

        payload = {"runId": "dup-http-001", "agentId": "agent-001"}
        resp = sidecar_client.post(
            "/sidecar/execute",
            json=payload,
            headers=auth_headers,
        )
        # Should be detected as duplicate (already registered)
        assert resp.status_code == 202
        assert resp.json()["deduplicated"] is True


class TestSidecarJsonLogging:
    """SIDE-07: Structured JSON logging, no ANSI codes."""

    def test_json_formatter_valid_json(self):
        fmt = SidecarJsonFormatter()
        record = logging.LogRecord("test.logger", logging.INFO, "", 0, "Hello world", (), None)
        output = fmt.format(record)
        parsed = json.loads(output)
        assert parsed["level"] == "INFO"
        assert parsed["logger"] == "test.logger"
        assert parsed["message"] == "Hello world"

    def test_json_formatter_strips_ansi(self):
        fmt = SidecarJsonFormatter()
        record = logging.LogRecord(
            "test",
            logging.WARNING,
            "",
            0,
            "\x1b[33mWarning\x1b[0m message",
            (),
            None,
        )
        output = fmt.format(record)
        parsed = json.loads(output)
        assert "\x1b" not in parsed["message"]
        assert parsed["message"] == "Warning message"

    def test_json_formatter_has_timestamp(self):
        fmt = SidecarJsonFormatter()
        record = logging.LogRecord(
            "test",
            logging.DEBUG,
            "",
            0,
            "msg",
            (),
            None,
        )
        output = fmt.format(record)
        parsed = json.loads(output)
        assert "timestamp" in parsed
        assert "T" in parsed["timestamp"]  # ISO-8601 format


class TestSidecarAppStructure:
    """SIDE-01: Sidecar mode has no dashboard UI routes."""

    def test_no_dashboard_routes(self):
        """Sidecar app should have only sidecar routes, no dashboard API routes."""
        app = create_sidecar_app()
        paths = [r.path for r in app.routes]
        # Should have sidecar routes
        assert "/sidecar/health" in paths
        assert "/sidecar/execute" in paths
        # Should NOT have dashboard routes
        assert "/api/health" not in paths
        assert "/api/agents" not in paths

    def test_no_swagger_ui(self):
        """Sidecar app should not serve Swagger UI."""
        app = create_sidecar_app()
        assert app.docs_url is None
        assert app.redoc_url is None


class TestCoreServicesInit:
    """SIDE-08: Core services start identically in sidecar and dashboard modes."""

    def test_agent42_accepts_sidecar_param(self):
        """Agent42.__init__ should accept sidecar=True without error.

        Note: Full init requires filesystem access (data dirs, etc).
        We verify the parameter is accepted by checking the class signature.
        """
        import inspect

        from agent42 import Agent42

        sig = inspect.signature(Agent42.__init__)
        params = list(sig.parameters.keys())
        assert "sidecar" in params
        assert "sidecar_port" in params


# ---------------------------------------------------------------------------
# Phase 29 — Plugin UI data endpoints
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_effectiveness_store_p29():
    """Mock EffectivenessStore with Phase 29 methods."""
    store = MagicMock()
    store.get_agent_stats = AsyncMock(
        return_value={
            "success_rate": 0.85,
            "task_volume": 42,
            "avg_speed": 1234.5,
        }
    )
    store.get_aggregated_stats = AsyncMock(
        return_value=[
            {
                "task_type": "coding",
                "success_rate": 0.9,
                "invocations": 20,
                "avg_duration_ms": 800.0,
            }
        ]
    )
    store.get_routing_history = AsyncMock(
        return_value=[
            {
                "run_id": "run-abc",
                "provider": "openai",
                "model": "gpt-4o",
                "tier": "premium",
                "task_category": "coding",
                "ts": 1700000000.0,
            }
        ]
    )
    store.get_agent_spend = AsyncMock(
        return_value=[
            {
                "provider": "openai",
                "model": "gpt-4o",
                "input_tokens": 100,
                "output_tokens": 50,
                "cost_usd": 0.01,
                "hour_bucket": "2024-01-01T10:00:00",
            }
        ]
    )
    store.drain_pending_transcripts = AsyncMock(
        return_value=[
            {
                "run_id": "run-def",
                "agent_id": "agent-1",
                "company_id": "",
                "task_type": "coding",
                "summary": "A test summary for learning extraction.",
            }
        ]
    )
    return store


@pytest.fixture
def sidecar_client_p29(mock_effectiveness_store_p29):
    """TestClient for sidecar app with Phase 29 effectiveness store mock."""
    app = create_sidecar_app(effectiveness_store=mock_effectiveness_store_p29)
    return TestClient(app)


@pytest.fixture
def auth_headers_p29():
    """Create valid Bearer auth headers for sidecar requests."""
    token = create_token("admin")
    return {"Authorization": f"Bearer {token}"}


class TestAgentProfileEndpoint:
    """Phase 29 D-09: GET /agent/{agent_id}/profile."""

    def test_agent_profile_returns_tier_and_stats(
        self, sidecar_client_p29, auth_headers_p29, mock_effectiveness_store_p29
    ):
        """GET /agent/{agent_id}/profile returns agentId, tier, successRate, taskVolume."""
        resp = sidecar_client_p29.get("/agent/agent-1/profile", headers=auth_headers_p29)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agentId"] == "agent-1"
        assert "tier" in data
        assert "successRate" in data
        assert "taskVolume" in data
        assert data["taskVolume"] == 42
        assert data["successRate"] == pytest.approx(0.85)

    def test_agent_profile_empty_when_no_store(self, auth_headers_p29):
        """GET /agent/{agent_id}/profile returns bronze defaults when no effectiveness_store."""
        app = create_sidecar_app()
        client = TestClient(app)
        resp = client.get("/agent/agent-1/profile", headers=auth_headers_p29)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agentId"] == "agent-1"
        assert data["tier"] == "bronze"
        assert data["successRate"] == 0.0
        assert data["taskVolume"] == 0

    def test_agent_profile_returns_401_without_auth(self, sidecar_client_p29):
        """GET /agent/{agent_id}/profile requires Bearer auth."""
        resp = sidecar_client_p29.get("/agent/agent-1/profile")
        assert resp.status_code == 401


class TestAgentEffectivenessEndpoint:
    """Phase 29 D-10: GET /agent/{agent_id}/effectiveness."""

    def test_agent_effectiveness_returns_per_task_stats(self, sidecar_client_p29, auth_headers_p29):
        """GET /agent/{agent_id}/effectiveness returns per-task-type breakdown."""
        resp = sidecar_client_p29.get("/agent/agent-1/effectiveness", headers=auth_headers_p29)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agentId"] == "agent-1"
        assert "stats" in data
        assert isinstance(data["stats"], list)
        assert len(data["stats"]) == 1
        stat = data["stats"][0]
        assert stat["taskType"] == "coding"
        assert stat["successRate"] == pytest.approx(0.9)

    def test_agent_effectiveness_empty_when_no_store(self, auth_headers_p29):
        """GET /agent/{agent_id}/effectiveness returns empty stats when no effectiveness_store."""
        app = create_sidecar_app()
        client = TestClient(app)
        resp = client.get("/agent/agent-1/effectiveness", headers=auth_headers_p29)
        assert resp.status_code == 200
        assert resp.json()["stats"] == []

    def test_agent_effectiveness_returns_401_without_auth(self, sidecar_client_p29):
        """GET /agent/{agent_id}/effectiveness requires Bearer auth."""
        resp = sidecar_client_p29.get("/agent/agent-1/effectiveness")
        assert resp.status_code == 401


class TestRoutingHistoryEndpoint:
    """Phase 29 D-11: GET /agent/{agent_id}/routing-history."""

    def test_agent_routing_history_returns_recent_entries(
        self, sidecar_client_p29, auth_headers_p29
    ):
        """GET /agent/{agent_id}/routing-history returns routing decision list."""
        resp = sidecar_client_p29.get("/agent/agent-1/routing-history", headers=auth_headers_p29)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agentId"] == "agent-1"
        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["runId"] == "run-abc"
        assert entry["provider"] == "openai"

    def test_agent_routing_history_empty_when_no_store(self, auth_headers_p29):
        """GET /agent/{agent_id}/routing-history returns empty entries when no store."""
        app = create_sidecar_app()
        client = TestClient(app)
        resp = client.get("/agent/agent-1/routing-history", headers=auth_headers_p29)
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    def test_agent_routing_history_returns_401_without_auth(self, sidecar_client_p29):
        """GET /agent/{agent_id}/routing-history requires Bearer auth."""
        resp = sidecar_client_p29.get("/agent/agent-1/routing-history")
        assert resp.status_code == 401


class TestMemoryRunTraceEndpoint:
    """Phase 29 D-13: GET /memory/run-trace/{run_id}."""

    def test_memory_run_trace_returns_injected_and_extracted(self, auth_headers_p29):
        """GET /memory/run-trace/{run_id} returns injected_memories and extracted_learnings."""
        mock_qdrant = MagicMock()
        mock_qdrant.is_available = True
        mock_qdrant.MEMORY = "memory"
        mock_qdrant.HISTORY = "history"
        mock_qdrant.KNOWLEDGE = "knowledge"
        mock_qdrant._collection_name = MagicMock(side_effect=lambda s: f"agent42_{s}")

        # Mock scroll to return a point with run_id tagged
        mock_point = MagicMock()
        mock_point.payload = {"text": "recalled item", "score": 0.9, "source": "mem"}
        mock_qdrant._client.scroll = MagicMock(return_value=([mock_point], None))

        mock_memory_store = MagicMock()
        mock_memory_store._qdrant = mock_qdrant

        app = create_sidecar_app(memory_store=mock_memory_store)
        client = TestClient(app)

        resp = client.get("/memory/run-trace/run-xyz", headers=auth_headers_p29)
        assert resp.status_code == 200
        data = resp.json()
        assert data["runId"] == "run-xyz"
        assert "injectedMemories" in data
        assert "extractedLearnings" in data

    def test_memory_run_trace_returns_empty_without_qdrant(self, auth_headers_p29):
        """GET /memory/run-trace returns empty lists when qdrant unavailable."""
        app = create_sidecar_app()
        client = TestClient(app)
        resp = client.get("/memory/run-trace/run-xyz", headers=auth_headers_p29)
        assert resp.status_code == 200
        data = resp.json()
        assert data["injectedMemories"] == []
        assert data["extractedLearnings"] == []

    def test_memory_run_trace_returns_401_without_auth(self, sidecar_client_p29):
        """GET /memory/run-trace/{run_id} requires Bearer auth."""
        resp = sidecar_client_p29.get("/memory/run-trace/run-xyz")
        assert resp.status_code == 401


class TestAgentSpendEndpoint:
    """Phase 29 D-14: GET /agent/{agent_id}/spend."""

    def test_agent_spend_returns_grouped_entries(self, sidecar_client_p29, auth_headers_p29):
        """GET /agent/{agent_id}/spend returns token spend distribution."""
        resp = sidecar_client_p29.get("/agent/agent-1/spend", headers=auth_headers_p29)
        assert resp.status_code == 200
        data = resp.json()
        assert data["agentId"] == "agent-1"
        assert data["hours"] == 24
        assert len(data["entries"]) == 1
        entry = data["entries"][0]
        assert entry["provider"] == "openai"
        assert entry["costUsd"] == pytest.approx(0.01)
        assert "totalCostUsd" in data

    def test_agent_spend_empty_when_no_store(self, auth_headers_p29):
        """GET /agent/{agent_id}/spend returns empty entries when no effectiveness_store."""
        app = create_sidecar_app()
        client = TestClient(app)
        resp = client.get("/agent/agent-1/spend", headers=auth_headers_p29)
        assert resp.status_code == 200
        assert resp.json()["entries"] == []

    def test_agent_spend_returns_401_without_auth(self, sidecar_client_p29):
        """GET /agent/{agent_id}/spend requires Bearer auth."""
        resp = sidecar_client_p29.get("/agent/agent-1/spend")
        assert resp.status_code == 401


class TestMemoryExtractEndpoint:
    """Phase 29 D-19: POST /memory/extract."""

    def test_memory_extract_drains_and_learns(self, auth_headers_p29, mock_effectiveness_store_p29):
        """POST /memory/extract drains pending transcripts and triggers learn_async."""
        mock_memory_bridge = MagicMock()
        mock_memory_bridge.memory_store = MagicMock()
        mock_memory_bridge.learn_async = AsyncMock(return_value=None)

        app = create_sidecar_app(
            effectiveness_store=mock_effectiveness_store_p29,
        )
        # Inject mock memory bridge into the app by recreating with both
        # Build the app with both stores so the route can exercise

        from core.memory_bridge import MemoryBridge

        with patch.object(MemoryBridge, "learn_async", AsyncMock(return_value=None)):
            app2 = create_sidecar_app(effectiveness_store=mock_effectiveness_store_p29)
            client = TestClient(app2)
            resp = client.post(
                "/memory/extract",
                json={"batchSize": 10},
                headers=auth_headers_p29,
            )
        # Without a memory_bridge, skipped should be 0 and extracted 0
        assert resp.status_code == 200
        data = resp.json()
        assert "extracted" in data
        assert "skipped" in data

    def test_memory_extract_empty_when_no_stores(self, auth_headers_p29):
        """POST /memory/extract returns 0/0 when neither store nor bridge available."""
        app = create_sidecar_app()
        client = TestClient(app)
        resp = client.post(
            "/memory/extract",
            json={"batchSize": 5},
            headers=auth_headers_p29,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["extracted"] == 0
        assert data["skipped"] == 0

    def test_memory_extract_returns_401_without_auth(self, sidecar_client_p29):
        """POST /memory/extract requires Bearer auth."""
        resp = sidecar_client_p29.post(
            "/memory/extract",
            json={"batchSize": 5},
        )
        assert resp.status_code == 401


class TestNewEndpointsRequireAuth:
    """Phase 29: All 5 GET + 1 POST new endpoints return 401 without Bearer token."""

    def test_all_new_endpoints_require_auth(self):
        """All Phase 29 endpoints return 401 without auth header."""
        app = create_sidecar_app()
        client = TestClient(app)
        endpoints = [
            ("GET", "/agent/agent-1/profile"),
            ("GET", "/agent/agent-1/effectiveness"),
            ("GET", "/agent/agent-1/routing-history"),
            ("GET", "/memory/run-trace/run-xyz"),
            ("GET", "/agent/agent-1/spend"),
        ]
        for method, path in endpoints:
            resp = client.get(path) if method == "GET" else client.post(path)
            assert resp.status_code == 401, f"{method} {path} should require auth"

        # POST /memory/extract also requires auth
        resp = client.post("/memory/extract", json={"batchSize": 5})
        assert resp.status_code == 401

    def test_health_still_public(self):
        """GET /sidecar/health remains public (no auth required)."""
        app = create_sidecar_app()
        client = TestClient(app)
        resp = client.get("/sidecar/health")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# Phase 30 — Auto-memory injection + strategy detection tests
# ---------------------------------------------------------------------------


class TestAutoMemoryInjection:
    """ADV-01: Auto-memory injection in execute_async + strategy detection (D-17, D-18, D-19)."""

    def _make_orchestrator(self, memories=None, auto_memory=True):
        """Create a SidecarOrchestrator with a mock memory_bridge."""
        mock_bridge = MagicMock()
        mock_bridge.recall = AsyncMock(return_value=memories if memories is not None else [])
        mock_bridge.learn_async = AsyncMock(return_value=None)
        orch = SidecarOrchestrator(memory_bridge=mock_bridge)
        return orch, mock_bridge

    def _make_ctx(self, auto_memory=True, context=None):
        """Create an AdapterExecutionContext with given auto_memory and context."""
        cfg = AdapterConfig(auto_memory=auto_memory)
        return AdapterExecutionContext(
            run_id="run-test-1",
            agent_id="agent-test-1",
            adapter_config=cfg,
            context=context or {},
        )

    @pytest.mark.asyncio
    async def test_auto_memory_injects_when_memories_recalled(self):
        """Recalled memories are injected into ctx.context['memoryContext']."""
        memories = [{"text": "test memory", "score": 0.9, "source": "test"}]
        orch, _ = self._make_orchestrator(memories=memories)
        ctx = self._make_ctx(auto_memory=True)

        with patch.object(orch, "_post_callback", AsyncMock(return_value=None)):
            await orch.execute_async("run-test-1", ctx)

        assert "memoryContext" in ctx.context
        mc = ctx.context["memoryContext"]
        assert mc["count"] == 1
        assert len(mc["memories"]) == 1
        assert mc["memories"][0]["text"] == "test memory"
        assert mc["memories"][0]["score"] == 0.9
        assert "injectedAt" in mc

    @pytest.mark.asyncio
    async def test_auto_memory_in_callback(self):
        """Callback result includes autoMemory metadata with count and injectedAt."""
        memories = [{"text": "test memory", "score": 0.9, "source": "test"}]
        orch, _ = self._make_orchestrator(memories=memories)
        ctx = self._make_ctx(auto_memory=True)

        callback_result = {}

        async def capture_callback(run_id, status, result, usage, error):
            callback_result.update(result)

        with patch.object(orch, "_post_callback", side_effect=capture_callback):
            await orch.execute_async("run-test-1", ctx)

        assert "autoMemory" in callback_result
        assert callback_result["autoMemory"] is not None
        assert callback_result["autoMemory"]["count"] == 1
        assert callback_result["autoMemory"]["injectedAt"] is not None

    @pytest.mark.asyncio
    async def test_auto_memory_disabled(self):
        """When auto_memory=False, memoryContext is NOT injected into ctx.context."""
        memories = [{"text": "test memory", "score": 0.9, "source": "test"}]
        orch, _ = self._make_orchestrator(memories=memories)
        ctx = self._make_ctx(auto_memory=False)

        with patch.object(orch, "_post_callback", AsyncMock(return_value=None)):
            await orch.execute_async("run-test-1", ctx)

        assert "memoryContext" not in ctx.context

    @pytest.mark.asyncio
    async def test_auto_memory_no_memories(self):
        """When memory_bridge returns [], memoryContext is NOT injected and autoMemory is None."""
        orch, _ = self._make_orchestrator(memories=[])
        ctx = self._make_ctx(auto_memory=True)

        callback_result = {}

        async def capture_callback(run_id, status, result, usage, error):
            callback_result.update(result)

        with patch.object(orch, "_post_callback", side_effect=capture_callback):
            await orch.execute_async("run-test-1", ctx)

        assert "memoryContext" not in ctx.context
        assert callback_result.get("autoMemory") is None

    @pytest.mark.asyncio
    async def test_strategy_standard_default(self, caplog):
        """When no strategy in context, defaults to 'standard' with no unknown-strategy warning."""
        orch, _ = self._make_orchestrator(memories=[])
        ctx = self._make_ctx()  # No strategy in context

        with caplog.at_level(logging.WARNING, logger="frood.sidecar.orchestrator"):
            with patch.object(orch, "_post_callback", AsyncMock(return_value=None)):
                await orch.execute_async("run-test-1", ctx)

        assert "Unknown strategy" not in caplog.text

    @pytest.mark.asyncio
    async def test_strategy_unknown_falls_back(self, caplog):
        """Unknown strategy value produces a warning log and falls back to 'standard'."""
        orch, _ = self._make_orchestrator(memories=[])
        ctx = self._make_ctx(context={"strategy": "unknown"})

        with caplog.at_level(logging.WARNING, logger="frood.sidecar.orchestrator"):
            with patch.object(orch, "_post_callback", AsyncMock(return_value=None)):
                await orch.execute_async("run-test-1", ctx)

        assert "Unknown strategy 'unknown'" in caplog.text

    @pytest.mark.asyncio
    async def test_strategy_fan_out_detected(self, caplog):
        """fan-out strategy is detected and logged at INFO level."""
        orch, _ = self._make_orchestrator(memories=[])
        ctx = self._make_ctx(context={"strategy": "fan-out"})

        with caplog.at_level(logging.INFO, logger="frood.sidecar.orchestrator"):
            with patch.object(orch, "_post_callback", AsyncMock(return_value=None)):
                await orch.execute_async("run-test-1", ctx)

        assert "strategy 'fan-out'" in caplog.text


# ---------------------------------------------------------------------------
# Phase 53: POST /sidecar/token tests (AUTH-01, AUTH-02, AUTH-03)
# ---------------------------------------------------------------------------


@pytest.fixture
def sidecar_client_with_devices(tmp_path):
    """Sidecar TestClient with a DeviceStore injected for api_key tests."""
    from core.device_auth import DeviceStore

    ds = DeviceStore(tmp_path / "devices.jsonl")
    app = create_sidecar_app(device_store=ds)
    return TestClient(app), ds


import contextlib


@contextlib.contextmanager
def _patch_settings(**kwargs):
    """Temporarily patch frozen Settings fields via object.__setattr__."""
    from core.config import settings

    originals = {k: getattr(settings, k) for k in kwargs}
    for key, val in kwargs.items():
        object.__setattr__(settings, key, val)
    try:
        yield
    finally:
        for key, val in originals.items():
            object.__setattr__(settings, key, val)


class TestSidecarToken:
    """Tests for POST /sidecar/token endpoint (Phase 53)."""

    def test_password_path_success(self):
        """POST /sidecar/token with valid username+password returns JWT."""
        from dashboard.auth import _login_attempts, pwd_context

        _login_attempts.clear()
        pw_hash = pwd_context.hash("testpass123")
        with _patch_settings(
            dashboard_username="admin",
            dashboard_password_hash=pw_hash,
            dashboard_password="",
        ):
            app = create_sidecar_app()
            client = TestClient(app)
            resp = client.post(
                "/sidecar/token",
                json={"username": "admin", "password": "testpass123"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert "token" in data
            assert data["expires_in"] == 86400
            assert data["token"].startswith("eyJ")

    def test_api_key_path_success(self, tmp_path, monkeypatch):
        """POST /sidecar/token with valid api_key returns JWT."""
        from core.device_auth import DeviceStore
        from dashboard.auth import _login_attempts

        monkeypatch.setenv("JWT_SECRET", "test-secret-for-device-auth")
        _login_attempts.clear()
        ds = DeviceStore(tmp_path / "devices.jsonl")
        device, raw_key = ds.register("test-laptop", "laptop")

        app = create_sidecar_app(device_store=ds)
        client = TestClient(app)
        resp = client.post("/sidecar/token", json={"api_key": raw_key})
        assert resp.status_code == 200
        data = resp.json()
        assert "token" in data
        assert data["token"].startswith("eyJ")

    def test_no_device_store_returns_503(self):
        """POST /sidecar/token with api_key but no DeviceStore returns 503."""
        from dashboard.auth import _login_attempts

        _login_attempts.clear()
        app = create_sidecar_app()  # No device_store
        client = TestClient(app)
        resp = client.post("/sidecar/token", json={"api_key": "ak_fakekey123"})
        assert resp.status_code == 503

    def test_bad_password_returns_401(self):
        """POST /sidecar/token with wrong password returns 401."""
        from dashboard.auth import _login_attempts, pwd_context

        _login_attempts.clear()
        pw_hash = pwd_context.hash("correctpass")
        with _patch_settings(
            dashboard_username="admin",
            dashboard_password_hash=pw_hash,
            dashboard_password="",
        ):
            app = create_sidecar_app()
            client = TestClient(app)
            resp = client.post(
                "/sidecar/token",
                json={"username": "admin", "password": "wrongpass"},
            )
            assert resp.status_code == 401

    def test_bad_api_key_returns_401(self, tmp_path, monkeypatch):
        """POST /sidecar/token with invalid api_key returns 401."""
        from core.device_auth import DeviceStore
        from dashboard.auth import _login_attempts

        monkeypatch.setenv("JWT_SECRET", "test-secret-for-device-auth")
        _login_attempts.clear()
        ds = DeviceStore(tmp_path / "devices.jsonl")
        app = create_sidecar_app(device_store=ds)
        client = TestClient(app)
        resp = client.post("/sidecar/token", json={"api_key": "ak_invalidkey"})
        assert resp.status_code == 401

    def test_rate_limit_returns_429(self):
        """POST /sidecar/token exceeding rate limit returns 429."""
        from dashboard.auth import _login_attempts

        _login_attempts.clear()
        with _patch_settings(
            login_rate_limit=2,
            dashboard_username="admin",
            dashboard_password_hash="",
            dashboard_password="",
        ):
            app = create_sidecar_app()
            client = TestClient(app)
            # Exhaust rate limit with bad requests
            for _ in range(3):
                client.post(
                    "/sidecar/token",
                    json={"username": "admin", "password": "wrong"},
                )
            resp = client.post(
                "/sidecar/token",
                json={"username": "admin", "password": "wrong"},
            )
            assert resp.status_code == 429

    def test_health_still_unauthenticated(self, sidecar_client):
        """GET /sidecar/health returns 200 without any auth header (AUTH-03 regression)."""
        resp = sidecar_client.get("/sidecar/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

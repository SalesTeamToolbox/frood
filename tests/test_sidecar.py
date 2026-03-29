"""Tests for Agent42 sidecar mode (Phase 24, SIDE-01 through SIDE-09)."""

import json
import logging

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

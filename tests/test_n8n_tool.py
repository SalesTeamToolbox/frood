"""
Unit tests for the N8N Workflow tool.

Covers all four actions (list, trigger, status, output), graceful degradation
when N8N is not configured, rate limiting on trigger, and config field loading.
"""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from core.config import Settings
from tools.n8n_workflow import N8nWorkflowTool

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def configured_settings():
    """Settings with N8N configured."""
    return Settings(
        n8n_url="http://localhost:5678",
        n8n_api_key="test-key-abc123",
        n8n_allow_code_nodes=False,
    )


@pytest.fixture
def unconfigured_settings():
    """Settings with N8N not configured (empty url/key)."""
    return Settings(n8n_url="", n8n_api_key="")


@pytest.fixture
def sample_workflow_list_response():
    """Mock response for GET /api/v1/workflows (list)."""
    return {
        "data": [
            {
                "id": "wf1",
                "name": "Daily Report",
                "active": True,
                "tags": [{"id": "t1", "name": "reports"}],
            },
            {
                "id": "wf2",
                "name": "Email Notifier",
                "active": False,
                "tags": [],
            },
        ],
        "nextCursor": None,
    }


@pytest.fixture
def sample_workflow_with_webhook():
    """Mock workflow JSON with a webhook trigger node."""
    return {
        "id": "wf1",
        "name": "Daily Report",
        "active": True,
        "nodes": [
            {
                "id": "node1",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {
                    "path": "test-path",
                    "responseMode": "onReceived",
                },
                "position": [100, 200],
            },
            {
                "id": "node2",
                "name": "Send Email",
                "type": "n8n-nodes-base.emailSend",
                "parameters": {},
                "position": [300, 200],
            },
        ],
        "connections": {},
    }


@pytest.fixture
def sample_workflow_no_webhook():
    """Mock workflow JSON WITHOUT a webhook trigger node."""
    return {
        "id": "wf2",
        "name": "Scheduled Task",
        "active": True,
        "nodes": [
            {
                "id": "node1",
                "name": "Schedule Trigger",
                "type": "n8n-nodes-base.scheduleTrigger",
                "parameters": {"rule": {"interval": [{"field": "hours", "hoursInterval": 1}]}},
                "position": [100, 200],
            },
        ],
        "connections": {},
    }


@pytest.fixture
def sample_execution_response():
    """Mock execution response matching N8N /api/v1/executions/{id} structure."""
    return {
        "id": "exec123",
        "finished": True,
        "mode": "webhook",
        "startedAt": "2026-04-05T10:00:00.000Z",
        "stoppedAt": "2026-04-05T10:00:05.123Z",
        "status": "success",
        "data": {
            "resultData": {
                "runData": {
                    "Send Email": [
                        {
                            "startTime": 1712300405000,
                            "executionTime": 123,
                            "source": [],
                            "data": {
                                "main": [
                                    [
                                        {"json": {"sent": True, "recipient": "user@example.com"}},
                                        {"json": {"sent": True, "recipient": "other@example.com"}},
                                    ]
                                ]
                            },
                        }
                    ]
                },
                "lastNodeExecuted": "Send Email",
            }
        },
    }


# ---------------------------------------------------------------------------
# Config field tests
# ---------------------------------------------------------------------------


def test_config_fields():
    """Settings dataclass has all three N8N fields with correct defaults."""
    s = Settings()
    assert hasattr(s, "n8n_url")
    assert hasattr(s, "n8n_api_key")
    assert hasattr(s, "n8n_allow_code_nodes")
    assert s.n8n_url == ""
    assert s.n8n_api_key == ""
    assert s.n8n_allow_code_nodes is False


def test_config_fields_from_env():
    """Settings.from_env() reads N8N env vars correctly."""
    with patch.dict(
        "os.environ",
        {
            "N8N_URL": "http://n8n:5678",
            "N8N_API_KEY": "secret-key",
            "N8N_ALLOW_CODE_NODES": "true",
        },
    ):
        s = Settings.from_env()
        assert s.n8n_url == "http://n8n:5678"
        assert s.n8n_api_key == "secret-key"
        assert s.n8n_allow_code_nodes is True


def test_config_url_trailing_slash_stripped():
    """N8N_URL trailing slash is stripped in from_env()."""
    with patch.dict("os.environ", {"N8N_URL": "http://localhost:5678/", "N8N_API_KEY": ""}):
        s = Settings.from_env()
        assert not s.n8n_url.endswith("/")


# ---------------------------------------------------------------------------
# Tool identity
# ---------------------------------------------------------------------------


def test_tool_name():
    """N8nWorkflowTool.name returns 'n8n_workflow'."""
    tool = N8nWorkflowTool()
    assert tool.name == "n8n_workflow"


def test_tool_has_description():
    """N8nWorkflowTool has a non-empty description."""
    tool = N8nWorkflowTool()
    assert tool.description
    assert len(tool.description) > 10


def test_tool_parameters_schema():
    """N8nWorkflowTool parameters schema has required 'action' field."""
    tool = N8nWorkflowTool()
    params = tool.parameters
    assert params["type"] == "object"
    assert "action" in params["properties"]
    assert "action" in params["required"]


# ---------------------------------------------------------------------------
# Graceful degradation — not configured
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured(unconfigured_settings):
    """When N8N is not configured, all actions return success=False with helpful error."""
    tool = N8nWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=unconfigured_settings):
        result = await tool.execute(action="list")
        assert not result.success
        assert "N8N not configured" in result.error
        assert "N8N_URL" in result.error


@pytest.mark.asyncio
async def test_unconfigured_trigger(unconfigured_settings):
    """Trigger action also returns not-configured error when N8N is absent."""
    tool = N8nWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=unconfigured_settings):
        result = await tool.execute(action="trigger", workflow_id="wf1")
        assert not result.success
        assert "N8N not configured" in result.error


# ---------------------------------------------------------------------------
# List action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_workflows(configured_settings, sample_workflow_list_response):
    """list action returns workflow data including id, name, active, tags."""
    tool = N8nWorkflowTool()
    mock_response = MagicMock()
    mock_response.is_success = True
    mock_response.json.return_value = sample_workflow_list_response
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(action="list")

    assert result.success
    import json

    data = json.loads(result.output)
    assert len(data) == 2
    assert data[0]["id"] == "wf1"
    assert data[0]["name"] == "Daily Report"
    assert data[0]["active"] is True
    assert "tags" in data[0]


@pytest.mark.asyncio
async def test_list_workflows_http_error(configured_settings):
    """list action returns success=False on HTTP error."""
    import httpx

    tool = N8nWorkflowTool()
    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(side_effect=httpx.RequestError("Connection refused"))

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(action="list")

    assert not result.success
    assert result.error


# ---------------------------------------------------------------------------
# Trigger action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_trigger_workflow(configured_settings, sample_workflow_with_webhook):
    """trigger action fetches workflow JSON, extracts webhook path, POSTs to webhook URL."""
    tool = N8nWorkflowTool()

    # GET /workflows/wf1 response
    mock_get_response = MagicMock()
    mock_get_response.json.return_value = sample_workflow_with_webhook
    mock_get_response.raise_for_status = MagicMock()

    # POST /webhook/test-path response
    mock_post_response = MagicMock()
    mock_post_response.text = '{"status": "received"}'
    mock_post_response.is_success = True
    mock_post_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_get_response)
    mock_client.post = AsyncMock(return_value=mock_post_response)

    # Mock URL policy so localhost passes in unit tests (SSRF gate is tested separately)
    mock_policy = MagicMock()
    mock_policy.check.return_value = (True, "")

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            with patch("core.url_policy.UrlPolicy", return_value=mock_policy):
                result = await tool.execute(action="trigger", workflow_id="wf1")

    assert result.success
    # Verify that a POST was made to the webhook URL
    call_args = mock_client.post.call_args
    assert call_args is not None
    url_called = call_args[0][0]
    assert "/webhook/test-path" in url_called
    assert "localhost:5678" in url_called


@pytest.mark.asyncio
async def test_trigger_no_webhook_node(configured_settings, sample_workflow_no_webhook):
    """trigger returns error when workflow has no webhook trigger node."""
    tool = N8nWorkflowTool()

    mock_get_response = MagicMock()
    mock_get_response.json.return_value = sample_workflow_no_webhook
    mock_get_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_get_response)

    mock_policy = MagicMock()
    mock_policy.check.return_value = (True, "")

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            with patch("core.url_policy.UrlPolicy", return_value=mock_policy):
                result = await tool.execute(action="trigger", workflow_id="wf2")

    assert not result.success
    assert "no webhook trigger node" in result.error.lower()


@pytest.mark.asyncio
async def test_trigger_missing_workflow_id(configured_settings):
    """trigger without workflow_id returns an error."""
    tool = N8nWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=configured_settings):
        result = await tool.execute(action="trigger")
    assert not result.success
    assert result.error


# ---------------------------------------------------------------------------
# Status action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_status(configured_settings, sample_execution_response):
    """status action calls GET /executions/{id}?includeData=true and returns status fields."""
    tool = N8nWorkflowTool()

    mock_response = MagicMock()
    mock_response.json.return_value = sample_execution_response
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(action="status", execution_id="exec123")

    assert result.success
    # Verify includeData=true was requested
    call_args = mock_client.get.call_args
    assert "includeData" in str(call_args) or "includeData" in str(call_args.kwargs)

    import json

    data = json.loads(result.output)
    assert data["status"] == "success"
    assert data["finished"] is True


@pytest.mark.asyncio
async def test_get_status_missing_execution_id(configured_settings):
    """status without execution_id returns an error."""
    tool = N8nWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=configured_settings):
        result = await tool.execute(action="status")
    assert not result.success
    assert result.error


# ---------------------------------------------------------------------------
# Output action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_output(configured_settings, sample_execution_response):
    """output action extracts last node items from execution data."""
    tool = N8nWorkflowTool()

    mock_response = MagicMock()
    mock_response.json.return_value = sample_execution_response
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(action="output", execution_id="exec123")

    assert result.success
    import json

    items = json.loads(result.output)
    assert isinstance(items, list)
    assert len(items) == 2
    assert items[0]["json"]["sent"] is True


@pytest.mark.asyncio
async def test_get_output_not_finished(configured_settings):
    """output action returns error when execution is not finished."""
    tool = N8nWorkflowTool()

    running_response = {
        "id": "exec456",
        "finished": False,
        "status": "running",
        "startedAt": "2026-04-05T10:00:00.000Z",
        "stoppedAt": None,
        "data": None,
    }

    mock_response = MagicMock()
    mock_response.json.return_value = running_response
    mock_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(action="output", execution_id="exec456")

    assert not result.success
    assert "not finished" in result.error.lower() or "running" in result.error.lower()


@pytest.mark.asyncio
async def test_get_output_missing_execution_id(configured_settings):
    """output without execution_id returns an error."""
    tool = N8nWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=configured_settings):
        result = await tool.execute(action="output")
    assert not result.success
    assert result.error


# ---------------------------------------------------------------------------
# Rate limiting
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiting(configured_settings, sample_workflow_with_webhook):
    """Trigger is rate-limited: 11th call within 60 seconds returns rate limit error."""
    tool = N8nWorkflowTool()

    # Clear any leftover rate limit state
    import tools.n8n_workflow as n8n_mod

    n8n_mod._trigger_call_times.clear()

    mock_get_response = MagicMock()
    mock_get_response.json.return_value = sample_workflow_with_webhook
    mock_get_response.raise_for_status = MagicMock()

    mock_post_response = MagicMock()
    mock_post_response.text = '{"ok": true}'
    mock_post_response.is_success = True
    mock_post_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_get_response)
    mock_client.post = AsyncMock(return_value=mock_post_response)

    # Seed the rate limiter with 10 calls at current time
    now = time.time()
    n8n_mod._trigger_call_times.extend([now] * 10)

    mock_policy = MagicMock()
    mock_policy.check.return_value = (True, "")

    with patch.object(tool, "_get_settings", return_value=configured_settings):
        with patch("tools.n8n_workflow.httpx.AsyncClient", return_value=mock_client):
            with patch("core.url_policy.UrlPolicy", return_value=mock_policy):
                result = await tool.execute(action="trigger", workflow_id="wf1")

    assert not result.success
    assert "rate limit" in result.error.lower()


# ---------------------------------------------------------------------------
# Unknown action
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unknown_action(configured_settings):
    """Unknown action returns success=False with helpful error."""
    tool = N8nWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=configured_settings):
        result = await tool.execute(action="invalid")
    assert not result.success
    assert "invalid" in result.error or "Unknown" in result.error

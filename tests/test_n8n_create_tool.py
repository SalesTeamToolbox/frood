"""
Tests for n8n_create_workflow tool.

Covers:
- Tool name contract
- Node validation (safe nodes, blocked nodes, allow_code flag)
- Unconfigured state (graceful degradation)
- Template loading
- Workflow generation and deployment (mocked httpx)
"""

import json
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Ensure project root is on path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tools.n8n_create_workflow import (
    DANGEROUS_NODE_TYPES,
    N8nCreateWorkflowTool,
    validate_workflow_nodes,
)

# ---------------------------------------------------------------------------
# Constants / fixtures
# ---------------------------------------------------------------------------

SAFE_NODES = [
    {"name": "Webhook", "type": "n8n-nodes-base.webhook"},
    {"name": "HTTP Request", "type": "n8n-nodes-base.httpRequest"},
    {"name": "Set", "type": "n8n-nodes-base.set"},
]


def _make_settings(configured: bool = True):
    """Return a mock settings object."""
    s = MagicMock()
    if configured:
        s.n8n_url = "http://localhost:5678"
        s.n8n_api_key = "n8n_api_testkey123"
        s.n8n_allow_code_nodes = False
    else:
        s.n8n_url = ""
        s.n8n_api_key = ""
        s.n8n_allow_code_nodes = False
    return s


# ---------------------------------------------------------------------------
# Tool identity
# ---------------------------------------------------------------------------


def test_tool_name():
    assert N8nCreateWorkflowTool().name == "n8n_create_workflow"


# ---------------------------------------------------------------------------
# Node validation
# ---------------------------------------------------------------------------


def test_node_validation_safe():
    """Safe nodes return empty violations list."""
    violations = validate_workflow_nodes(SAFE_NODES)
    assert violations == []


def test_node_validation_blocks_execute_command():
    """executeCommand node is always blocked."""
    nodes = [{"name": "Exec", "type": "n8n-nodes-base.executeCommand"}]
    violations = validate_workflow_nodes(nodes)
    assert len(violations) == 1
    assert "executeCommand" in violations[0]


def test_node_validation_blocks_ssh():
    """SSH node is always blocked."""
    nodes = [{"name": "SSH", "type": "n8n-nodes-base.ssh"}]
    violations = validate_workflow_nodes(nodes)
    assert len(violations) == 1
    assert "ssh" in violations[0]


def test_node_validation_code_blocked_by_default():
    """Code node is blocked by default (allow_code=False)."""
    nodes = [{"name": "Code", "type": "n8n-nodes-base.code"}]
    violations = validate_workflow_nodes(nodes, allow_code=False)
    assert len(violations) == 1


def test_node_validation_code_allowed():
    """Code node is unblocked when allow_code=True."""
    nodes = [{"name": "Code", "type": "n8n-nodes-base.code"}]
    violations = validate_workflow_nodes(nodes, allow_code=True)
    assert violations == []


def test_node_validation_ssh_still_blocked_with_allow_code():
    """SSH remains blocked even when allow_code=True (only code is unblocked)."""
    nodes = [{"name": "SSH", "type": "n8n-nodes-base.ssh"}]
    violations = validate_workflow_nodes(nodes, allow_code=True)
    assert len(violations) == 1
    assert "ssh" in violations[0]


def test_dangerous_node_types_has_seven_entries():
    """DANGEROUS_NODE_TYPES constant must have exactly 7 entries."""
    assert len(DANGEROUS_NODE_TYPES) == 7


# ---------------------------------------------------------------------------
# Unconfigured state
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unconfigured_returns_error():
    """When N8N is not configured, execute returns 'N8N not configured' error."""
    tool = N8nCreateWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=_make_settings(configured=False)):
        result = await tool.execute(description="Test workflow")
    assert result.success is False
    assert "N8N not configured" in result.error


@pytest.mark.asyncio
async def test_missing_description_returns_error():
    """Empty description returns error asking for description."""
    tool = N8nCreateWorkflowTool()
    with patch.object(tool, "_get_settings", return_value=_make_settings(configured=True)):
        result = await tool.execute(description="")
    assert result.success is False
    assert "Description is required" in result.error


# ---------------------------------------------------------------------------
# Template loading
# ---------------------------------------------------------------------------


def test_template_loading():
    """_load_template returns a dict with a 'nodes' key."""
    tool = N8nCreateWorkflowTool()
    template = tool._load_template("webhook_to_http")
    assert template is not None
    assert isinstance(template, dict)
    assert "nodes" in template


def test_template_loading_missing_returns_none():
    """_load_template returns None for a non-existent template name."""
    tool = N8nCreateWorkflowTool()
    result = tool._load_template("nonexistent_template")
    assert result is None


def test_all_templates_loadable():
    """All three bundled templates load successfully."""
    tool = N8nCreateWorkflowTool()
    for name in ("webhook_to_http", "webhook_to_transform", "webhook_to_multi_step"):
        t = tool._load_template(name)
        assert t is not None, f"Template '{name}' failed to load"
        assert "nodes" in t


# ---------------------------------------------------------------------------
# Workflow generation
# ---------------------------------------------------------------------------


def test_build_workflow_replaces_placeholders():
    """_build_workflow replaces {WORKFLOW_NAME} and {WEBHOOK_PATH} placeholders."""
    tool = N8nCreateWorkflowTool()
    workflow = tool._build_workflow(
        description="Test automation",
        template_name="webhook_to_http",
        name="My Test Workflow",
        target_url="https://example.com/api",
        http_method="POST",
    )
    assert workflow["name"] == "My Test Workflow"
    # Placeholder UUIDs should be replaced with real UUIDs
    for node in workflow["nodes"]:
        assert node["id"] != "00000000-0000-0000-0000-000000000001"
        assert node["id"] != "00000000-0000-0000-0000-000000000002"
        assert "{" not in node["id"]
    # Webhook path should be replaced
    webhook_node = next(n for n in workflow["nodes"] if "webhook" in n["type"])
    assert "{WEBHOOK_PATH}" not in webhook_node["parameters"]["path"]
    assert "agent42-" in webhook_node["parameters"]["path"]


def test_build_workflow_auto_generates_name():
    """_build_workflow generates a name from description when name is empty."""
    tool = N8nCreateWorkflowTool()
    workflow = tool._build_workflow(
        description="Send email notification on new order",
        template_name="webhook_to_http",
        name="",
        target_url="https://example.com/api",
        http_method="POST",
    )
    assert "Agent42:" in workflow["name"]


# ---------------------------------------------------------------------------
# Full deployment (mocked httpx)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_workflow_generation_and_deployment():
    """
    Full execute flow: builds workflow, POSTs to /api/v1/workflows,
    then activates via /api/v1/workflows/{id}/activate.
    Returns workflow_id and webhook_url in output JSON.
    """
    tool = N8nCreateWorkflowTool()
    settings = _make_settings(configured=True)

    # Mock create response
    create_response = MagicMock()
    create_response.json.return_value = {"id": "wf-abc123", "name": "Test Workflow"}
    create_response.raise_for_status = MagicMock()

    # Mock activate response
    activate_response = MagicMock()
    activate_response.raise_for_status = MagicMock()

    mock_client = AsyncMock()
    mock_client.post = AsyncMock(side_effect=[create_response, activate_response])
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)

    with patch.object(tool, "_get_settings", return_value=settings):
        with patch("tools.n8n_create_workflow.httpx.AsyncClient", return_value=mock_client):
            result = await tool.execute(
                description="Test workflow",
                template="webhook_to_http",
                target_url="https://example.com/api",
            )

    assert result.success is True
    output = json.loads(result.output)
    assert output["workflow_id"] == "wf-abc123"
    assert "webhook_url" in output
    assert output["active"] is True

    # Verify create was called first, then activate
    calls = mock_client.post.call_args_list
    assert len(calls) == 2
    create_url = calls[0].args[0] if calls[0].args else calls[0].kwargs.get("url", "")
    activate_url = calls[1].args[0] if calls[1].args else calls[1].kwargs.get("url", "")
    assert "/api/v1/workflows" in create_url
    assert "wf-abc123/activate" in activate_url


@pytest.mark.asyncio
async def test_deployment_blocks_dangerous_node():
    """Dangerous node in template triggers validation error, no HTTP calls made."""
    tool = N8nCreateWorkflowTool()
    settings = _make_settings(configured=True)

    # Inject a workflow with a dangerous node via _build_workflow mock
    dangerous_workflow = {
        "name": "Bad Workflow",
        "nodes": [
            {
                "id": "abc",
                "name": "Webhook",
                "type": "n8n-nodes-base.webhook",
                "parameters": {
                    "path": "agent42-test",
                    "responseMode": "lastNode",
                    "responseData": "allEntries",
                    "httpMethod": "POST",
                },
            },
            {"id": "def", "name": "Bad", "type": "n8n-nodes-base.executeCommand"},
        ],
        "connections": {},
        "settings": {"executionOrder": "v1"},
    }

    with patch.object(tool, "_get_settings", return_value=settings):
        with patch.object(tool, "_build_workflow", return_value=dangerous_workflow):
            with patch("tools.n8n_create_workflow.httpx.AsyncClient") as mock_httpx:
                result = await tool.execute(description="Run some command")

    assert result.success is False
    assert "blocked" in result.error.lower()
    mock_httpx.assert_not_called()

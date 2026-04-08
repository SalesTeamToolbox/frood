"""
N8N Workflow tool — list, trigger, monitor, and retrieve output from N8N workflows.

Agents use this tool to offload repetitive tasks to deterministic N8N workflows,
eliminating token cost for work that does not need LLM reasoning.

Actions:
  list    — List available workflows (id, name, active, tags)
  trigger — Trigger a workflow via its webhook URL
  status  — Poll execution status (finished, started/stopped timestamps)
  output  — Extract last node output from a completed execution

Requires:
  N8N_URL      — N8N instance base URL (e.g. http://localhost:5678)
  N8N_API_KEY  — N8N public API key created in N8N UI -> Settings -> n8n API
"""

import json
import logging
import time
from collections import deque

import httpx

from tools.base import Tool, ToolResult

logger = logging.getLogger("frood.tools.n8n_workflow")

# ---------------------------------------------------------------------------
# Module-level rate limit tracker (sliding window, 10 trigger calls / 60s)
# ---------------------------------------------------------------------------
_trigger_call_times: deque = deque()
_RATE_LIMIT_MAX_CALLS = 10
_RATE_LIMIT_WINDOW_SECONDS = 60.0


def _check_and_record_trigger_rate() -> bool:
    """Return True if rate limit allows another trigger call; record call time if so.

    Uses a sliding window over the last 60 seconds.
    Returns False when the limit of 10 calls/minute is exceeded.
    """
    now = time.time()
    cutoff = now - _RATE_LIMIT_WINDOW_SECONDS
    # Drop expired entries
    while _trigger_call_times and _trigger_call_times[0] < cutoff:
        _trigger_call_times.popleft()
    if len(_trigger_call_times) >= _RATE_LIMIT_MAX_CALLS:
        return False
    _trigger_call_times.append(now)
    return True


class N8nWorkflowTool(Tool):
    """List, trigger, monitor, and retrieve output from N8N workflows."""

    @property
    def name(self) -> str:
        return "n8n_workflow"

    @property
    def description(self) -> str:
        return (
            "List, trigger, monitor, and retrieve output from N8N workflows. "
            "Use this to offload repetitive tasks to deterministic N8N automation "
            "without consuming LLM tokens for non-reasoning work."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "trigger", "status", "output"],
                    "description": (
                        "Action to perform: "
                        "'list' = list available workflows, "
                        "'trigger' = run a workflow via webhook, "
                        "'status' = check execution status, "
                        "'output' = retrieve last node output from a completed execution"
                    ),
                },
                "workflow_id": {
                    "type": "string",
                    "description": "Workflow ID (required for 'trigger' action)",
                },
                "execution_id": {
                    "type": "string",
                    "description": "Execution ID (required for 'status' and 'output' actions)",
                },
                "input_data": {
                    "type": "object",
                    "description": "Optional JSON payload to send to the webhook (for 'trigger')",
                },
            },
            "required": ["action"],
        }

    def _get_settings(self):
        """Deferred import of settings — reads env at execute time, not constructor time."""
        from core.config import settings

        return settings

    def _auth_headers(self, api_key: str) -> dict:
        """Return authentication headers for N8N REST API calls."""
        return {
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
        }

    def _base_url(self, n8n_url: str) -> str:
        """Return the N8N REST API v1 base URL."""
        return f"{n8n_url}/api/v1"

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        settings = self._get_settings()
        if not settings.n8n_url or not settings.n8n_api_key:
            return ToolResult(
                success=False,
                error=(
                    "N8N not configured. Set N8N_URL and N8N_API_KEY environment variables. "
                    "Start N8N: docker run -d --name n8n -p 5678:5678 "
                    "-v n8n_data:/home/node/.n8n docker.n8n.io/n8nio/n8n"
                ),
            )
        match action:
            case "list":
                return await self._list_workflows(settings)
            case "trigger":
                return await self._trigger_workflow(settings, **kwargs)
            case "status":
                return await self._get_status(settings, **kwargs)
            case "output":
                return await self._get_output(settings, **kwargs)
            case _:
                return ToolResult(
                    success=False,
                    error=f"Unknown action '{action}'. Use: list, trigger, status, output",
                )

    async def _list_workflows(self, settings) -> ToolResult:
        """GET /api/v1/workflows — returns list with id, name, active, tags."""
        base = self._base_url(settings.n8n_url)
        headers = self._auth_headers(settings.n8n_api_key)
        workflows = []
        cursor = None

        try:
            async with httpx.AsyncClient() as client:
                while True:
                    params = {}
                    if cursor:
                        params["cursor"] = cursor
                    response = await client.get(
                        f"{base}/workflows",
                        headers=headers,
                        params=params,
                        timeout=10.0,
                    )
                    response.raise_for_status()
                    data = response.json()
                    for wf in data.get("data", []):
                        workflows.append(
                            {
                                "id": wf.get("id", ""),
                                "name": wf.get("name", ""),
                                "active": wf.get("active", False),
                                "tags": wf.get("tags", []),
                            }
                        )
                    cursor = data.get("nextCursor")
                    if not cursor:
                        break
        except httpx.HTTPStatusError as exc:
            logger.error("N8N list workflows HTTP error: %s", exc)
            return ToolResult(
                success=False,
                error=f"N8N API error: {exc.response.status_code} {exc.response.text[:200]}",
            )
        except Exception as exc:
            logger.error("N8N list workflows error: %s", exc)
            return ToolResult(success=False, error=f"Failed to list workflows: {exc}")

        return ToolResult(output=json.dumps(workflows, indent=2))

    async def _trigger_workflow(self, settings, workflow_id: str = "", **kwargs) -> ToolResult:
        """Fetch workflow JSON, find webhook node, POST to webhook URL."""
        if not workflow_id:
            return ToolResult(success=False, error="workflow_id is required for trigger action")

        # SSRF protection: validate the N8N URL before making any outbound requests
        from core.url_policy import UrlPolicy

        policy = UrlPolicy()
        allowed, reason = policy.check(settings.n8n_url)
        if not allowed:
            return ToolResult(success=False, error=f"N8N URL blocked by security policy: {reason}")

        # Rate limit: 10 trigger calls per 60 seconds
        if not _check_and_record_trigger_rate():
            return ToolResult(
                success=False,
                error=(
                    "Rate limit exceeded: max 10 trigger calls per minute. "
                    "Wait before triggering more workflows."
                ),
            )

        base = self._base_url(settings.n8n_url)
        headers = self._auth_headers(settings.n8n_api_key)
        input_data = kwargs.get("input_data") or {}

        try:
            async with httpx.AsyncClient() as client:
                # Step 1: Fetch workflow JSON to find the webhook node
                wf_response = await client.get(
                    f"{base}/workflows/{workflow_id}",
                    headers=headers,
                    timeout=10.0,
                )
                wf_response.raise_for_status()
                workflow = wf_response.json()

                # Step 2: Find webhook trigger node
                webhook_node = next(
                    (
                        n
                        for n in workflow.get("nodes", [])
                        if n.get("type") == "n8n-nodes-base.webhook"
                    ),
                    None,
                )
                if not webhook_node:
                    return ToolResult(
                        success=False,
                        error=(
                            "Workflow has no webhook trigger node. "
                            "Add a Webhook node to the workflow in N8N."
                        ),
                    )

                # Step 3: Extract path and build webhook URL
                path = webhook_node.get("parameters", {}).get("path", "")
                if not path:
                    return ToolResult(success=False, error="Webhook node has no path configured")
                webhook_url = f"{settings.n8n_url}/webhook/{path}"

                # Step 4: POST to webhook URL (no API key needed for webhooks)
                logger.info("Triggering N8N workflow %s via %s", workflow_id, webhook_url)
                post_response = await client.post(
                    webhook_url,
                    json=input_data,
                    timeout=30.0,
                )
                return ToolResult(output=post_response.text, success=post_response.is_success)

        except httpx.HTTPStatusError as exc:
            logger.error("N8N trigger workflow HTTP error: %s", exc)
            return ToolResult(
                success=False,
                error=f"N8N API error: {exc.response.status_code} {exc.response.text[:200]}",
            )
        except Exception as exc:
            logger.error("N8N trigger workflow error: %s", exc)
            return ToolResult(success=False, error=f"Failed to trigger workflow: {exc}")

    async def _get_status(self, settings, execution_id: str = "", **kwargs) -> ToolResult:
        """GET /api/v1/executions/{id}?includeData=true — returns status summary."""
        if not execution_id:
            return ToolResult(success=False, error="execution_id is required for status action")

        base = self._base_url(settings.n8n_url)
        headers = self._auth_headers(settings.n8n_api_key)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{base}/executions/{execution_id}",
                    headers=headers,
                    params={"includeData": "true"},
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()

            summary = {
                "id": data.get("id", execution_id),
                "status": data.get("status", "unknown"),
                "finished": data.get("finished", False),
                "startedAt": data.get("startedAt"),
                "stoppedAt": data.get("stoppedAt"),
            }
            return ToolResult(output=json.dumps(summary, indent=2))

        except httpx.HTTPStatusError as exc:
            logger.error("N8N get status HTTP error: %s", exc)
            return ToolResult(
                success=False,
                error=f"N8N API error: {exc.response.status_code} {exc.response.text[:200]}",
            )
        except Exception as exc:
            logger.error("N8N get status error: %s", exc)
            return ToolResult(success=False, error=f"Failed to get execution status: {exc}")

    async def _get_output(self, settings, execution_id: str = "", **kwargs) -> ToolResult:
        """GET /api/v1/executions/{id}?includeData=true — extracts last node output items."""
        if not execution_id:
            return ToolResult(success=False, error="execution_id is required for output action")

        base = self._base_url(settings.n8n_url)
        headers = self._auth_headers(settings.n8n_api_key)

        try:
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{base}/executions/{execution_id}",
                    headers=headers,
                    params={"includeData": "true"},
                    timeout=10.0,
                )
                response.raise_for_status()
                data = response.json()

            if not data.get("finished"):
                status = data.get("status", "running")
                return ToolResult(
                    success=False,
                    error=(
                        f"Execution {execution_id} is not finished yet (status: {status}). "
                        "Use 'status' action to poll until finished."
                    ),
                )

            # Extract last node output: data.resultData.runData[lastNode][0].data.main[0]
            exec_data = data.get("data")
            if not exec_data:
                return ToolResult(success=False, error="Execution has no output data")

            result_data = exec_data.get("resultData", {})
            last_node = result_data.get("lastNodeExecuted", "")
            run_data = result_data.get("runData", {})

            if not last_node or last_node not in run_data:
                return ToolResult(
                    success=False,
                    error="No output data found — execution may have failed or produced no output",
                )

            node_runs = run_data[last_node]
            if not node_runs:
                return ToolResult(success=False, error=f"No run data for node '{last_node}'")

            last_run = node_runs[0]
            items = last_run.get("data", {}).get("main", [[]])[0]
            return ToolResult(output=json.dumps(items, indent=2))

        except httpx.HTTPStatusError as exc:
            logger.error("N8N get output HTTP error: %s", exc)
            return ToolResult(
                success=False,
                error=f"N8N API error: {exc.response.status_code} {exc.response.text[:200]}",
            )
        except Exception as exc:
            logger.error("N8N get output error: %s", exc)
            return ToolResult(success=False, error=f"Failed to get execution output: {exc}")

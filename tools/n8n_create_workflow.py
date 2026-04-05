"""
N8N workflow creation tool.

Generates N8N workflow JSON from natural language descriptions using template
skeletons, validates node safety, creates the workflow via the N8N REST API,
and activates it so the webhook URL is live.

Design principles:
- Templates (tools/n8n_templates/) reduce LLM hallucination by providing proven JSON
- Node validation blocks dangerous node types (executeCommand, ssh, code, git, etc.)
- Graceful degradation when N8N is not configured
- All I/O is async (httpx.AsyncClient)
"""

import json
import logging
import uuid
from pathlib import Path

import httpx

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.n8n_create_workflow")

# ---------------------------------------------------------------------------
# Safety constants
# ---------------------------------------------------------------------------

DANGEROUS_NODE_TYPES: set[str] = {
    "n8n-nodes-base.executeCommand",
    "n8n-nodes-base.ssh",
    "n8n-nodes-base.code",
    "n8n-nodes-base.git",
    "n8n-nodes-base.localFileTrigger",
    "n8n-nodes-base.readBinaryFiles",
    "n8n-nodes-base.writeBinaryFile",
}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_workflow_nodes(nodes: list[dict], allow_code: bool = False) -> list[str]:
    """Return list of violation strings. Empty list means workflow is safe.

    Args:
        nodes: List of N8N node dicts, each with a 'type' key.
        allow_code: When True, n8n-nodes-base.code is unblocked. All other
                    dangerous node types remain blocked regardless of this flag.

    Returns:
        List of human-readable violation strings. Empty = safe to deploy.
    """
    blocked = DANGEROUS_NODE_TYPES.copy()
    if allow_code:
        blocked.discard("n8n-nodes-base.code")

    violations = []
    for node in nodes:
        node_type = node.get("type", "")
        if node_type in blocked:
            violations.append(
                f"Node '{node.get('name', 'unknown')}' uses blocked type '{node_type}'"
            )
    return violations


# ---------------------------------------------------------------------------
# Tool
# ---------------------------------------------------------------------------


class N8nCreateWorkflowTool(Tool):
    """Design and deploy N8N workflows from natural language descriptions.

    Generates workflow JSON from a template skeleton, validates node safety,
    creates the workflow in N8N via the REST API, and activates it so the
    webhook URL is immediately live.
    """

    @property
    def name(self) -> str:
        return "n8n_create_workflow"

    @property
    def description(self) -> str:
        return (
            "Design and deploy N8N workflows from natural language descriptions. "
            "Generates workflow JSON, validates safety, creates in N8N, and activates. "
            "Returns the webhook URL agents and external systems can call to trigger the workflow."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "description": {
                    "type": "string",
                    "description": "Natural language description of the automation to create.",
                },
                "template": {
                    "type": "string",
                    "enum": [
                        "webhook_to_http",
                        "webhook_to_transform",
                        "webhook_to_multi_step",
                    ],
                    "description": (
                        "Base template to use. "
                        "webhook_to_http: call external API and return response. "
                        "webhook_to_transform: reshape/filter incoming data. "
                        "webhook_to_multi_step: fetch from API, transform, return result."
                    ),
                },
                "name": {
                    "type": "string",
                    "description": "Workflow name. Auto-generated from description if omitted.",
                },
                "target_url": {
                    "type": "string",
                    "description": "Target URL for HTTP request nodes (required for http templates).",
                },
                "http_method": {
                    "type": "string",
                    "description": "HTTP method for HTTP request nodes (default: POST).",
                    "default": "POST",
                },
            },
            "required": ["description"],
        }

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _get_settings(self):
        """Deferred import to avoid circular imports at module load time."""
        from core.config import settings

        return settings

    def _auth_headers(self, api_key: str) -> dict:
        return {
            "X-N8N-API-KEY": api_key,
            "Content-Type": "application/json",
        }

    def _templates_dir(self) -> Path:
        return Path(__file__).parent / "n8n_templates"

    def _load_template(self, template_name: str) -> dict | None:
        """Load a workflow template JSON file by name.

        Args:
            template_name: Stem name of the template file (without .json).

        Returns:
            Parsed dict, or None if template not found.
        """
        path = self._templates_dir() / f"{template_name}.json"
        if not path.exists():
            logger.warning("N8N template not found: %s", path)
            return None
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load N8N template %s: %s", template_name, e)
            return None

    def _replace_in_value(self, value, replacements: dict):
        """Recursively replace placeholder strings in a JSON-compatible structure."""
        if isinstance(value, str):
            for placeholder, replacement in replacements.items():
                value = value.replace(placeholder, str(replacement))
            return value
        if isinstance(value, dict):
            return {k: self._replace_in_value(v, replacements) for k, v in value.items()}
        if isinstance(value, list):
            return [self._replace_in_value(item, replacements) for item in value]
        return value

    def _build_workflow(
        self,
        description: str,
        template_name: str,
        name: str,
        target_url: str,
        http_method: str,
    ) -> dict:
        """Build a complete workflow dict from a template with placeholders replaced.

        Args:
            description: Natural language description (used for auto-naming).
            template_name: Name of the template to load.
            name: Workflow display name. Auto-generated if empty.
            target_url: Target URL for HTTP request nodes.
            http_method: HTTP method for HTTP request nodes.

        Returns:
            Workflow dict ready for POST to N8N API.
        """
        template = self._load_template(template_name)
        if template is None:
            # Fall back to simplest template
            template = self._load_template("webhook_to_http")

        # Generate unique webhook path
        webhook_path = f"agent42-{uuid.uuid4().hex[:12]}"

        # Determine workflow name
        workflow_name = name if name else f"Agent42: {description[:50]}"

        # Build placeholder replacements
        replacements = {
            "{WORKFLOW_NAME}": workflow_name,
            "{WEBHOOK_PATH}": webhook_path,
            "{TARGET_URL}": target_url or "https://example.com/api",
            "{HTTP_METHOD}": http_method or "POST",
            "{FIELD_NAME}": "result",
            "{FIELD_VALUE}": "={{$json.body}}",
        }

        # Apply replacements throughout the entire template structure
        workflow = self._replace_in_value(template, replacements)

        # Replace placeholder UUIDs in node ids with real UUIDs
        for node in workflow.get("nodes", []):
            # Replace any id that looks like a placeholder (all-zero segments)
            node_id = node.get("id", "")
            if "00000000" in node_id or not node_id:
                node["id"] = str(uuid.uuid4())
            # Also replace assignment ids inside Set node parameters
            assignments = node.get("parameters", {}).get("assignments", {}).get("assignments", [])
            for assignment in assignments:
                assign_id = assignment.get("id", "")
                if "00000000" in assign_id or not assign_id:
                    assignment["id"] = str(uuid.uuid4())

        return workflow

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    async def execute(self, description: str = "", **kwargs) -> ToolResult:
        """Generate, validate, and deploy an N8N workflow.

        Returns a JSON output containing workflow_id, name, webhook_url, and
        the trigger message. On failure returns a ToolResult with success=False.
        """
        settings = self._get_settings()

        # Graceful degradation — N8N not configured
        if not settings.n8n_url or not settings.n8n_api_key:
            return ToolResult(
                success=False,
                error=(
                    "N8N not configured. Set N8N_URL and N8N_API_KEY environment variables. "
                    "Run N8N via Docker: docker run -p 5678:5678 n8nio/n8n"
                ),
            )

        if not description:
            return ToolResult(
                success=False,
                error="Description is required. Describe the automation you want to create.",
            )

        template = kwargs.get("template", "webhook_to_http")
        name = kwargs.get("name", "")
        target_url = kwargs.get("target_url", "https://example.com/api")
        http_method = kwargs.get("http_method", "POST")

        # Build workflow from template
        workflow = self._build_workflow(description, template, name, target_url, http_method)

        # Validate nodes against dangerous type blocklist
        violations = validate_workflow_nodes(
            workflow.get("nodes", []),
            allow_code=settings.n8n_allow_code_nodes,
        )
        if violations:
            return ToolResult(
                success=False,
                error=f"Workflow contains blocked nodes: {'; '.join(violations)}",
            )

        # Deploy to N8N
        base_url = f"{settings.n8n_url.rstrip('/')}/api/v1"
        headers = self._auth_headers(settings.n8n_api_key)

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                # Step 1: Create workflow
                resp = await client.post(
                    f"{base_url}/workflows",
                    headers=headers,
                    json=workflow,
                )
                resp.raise_for_status()
                created = resp.json()
                workflow_id = created["id"]

                # Step 2: Activate workflow so webhook URL is live
                # Per RESEARCH.md Pitfall 6: must activate before webhook URL works
                activate_resp = await client.post(
                    f"{base_url}/workflows/{workflow_id}/activate",
                    headers=headers,
                )
                activate_resp.raise_for_status()

            # Construct the live webhook URL
            webhook_node = next(
                (n for n in workflow["nodes"] if "webhook" in n.get("type", "")),
                None,
            )
            webhook_path = webhook_node["parameters"]["path"] if webhook_node else "unknown"
            webhook_url = f"{settings.n8n_url.rstrip('/')}/webhook/{webhook_path}"

            return ToolResult(
                output=json.dumps(
                    {
                        "workflow_id": workflow_id,
                        "name": created.get("name", workflow.get("name", "")),
                        "webhook_url": webhook_url,
                        "active": True,
                        "message": f"Workflow created and activated. Trigger via POST {webhook_url}",
                    },
                    indent=2,
                )
            )

        except httpx.HTTPStatusError as e:
            return ToolResult(
                success=False,
                error=f"N8N API error: {e.response.status_code} — {e.response.text}",
            )
        except httpx.RequestError as e:
            return ToolResult(
                success=False,
                error=f"N8N connection error: {e}",
            )

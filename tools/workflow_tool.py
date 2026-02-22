"""
Workflow engine tool — define and execute multi-step workflows.

Inspired by OpenClaw's Lobster workflow engine. Allows defining sequences
of steps that combine tool calls, conditions, and iterations.
"""

import json
import logging
import time

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.workflow")


class WorkflowTool(Tool):
    """Define and execute multi-step automated workflows."""

    def __init__(self, workspace_path: str = ".", tool_registry=None):
        self._workspace = workspace_path
        self._registry = tool_registry
        self._workflows: dict[str, dict] = {}

    @property
    def name(self) -> str:
        return "workflow"

    @property
    def description(self) -> str:
        return (
            "Define and run multi-step workflows. A workflow is a sequence of "
            "tool calls with optional conditions. Actions: define, run, list, show, delete."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["define", "run", "list", "show", "delete"],
                    "description": "Workflow action",
                },
                "name": {
                    "type": "string",
                    "description": "Workflow name",
                    "default": "",
                },
                "steps": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "tool": {"type": "string"},
                            "args": {"type": "object"},
                            "description": {"type": "string"},
                            "continue_on_error": {"type": "boolean"},
                        },
                    },
                    "description": "Workflow steps (for define action)",
                },
                "description": {
                    "type": "string",
                    "description": "Workflow description",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        name: str = "",
        steps: list | None = None,
        description: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        if action == "define":
            return self._define(name, steps or [], description)
        elif action == "run":
            return await self._run(name)
        elif action == "list":
            return self._list()
        elif action == "show":
            return self._show(name)
        elif action == "delete":
            return self._delete(name)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _define(self, name: str, steps: list, description: str) -> ToolResult:
        if not name:
            return ToolResult(error="Workflow name required", success=False)
        if not steps:
            return ToolResult(error="At least one step required", success=False)

        self._workflows[name] = {
            "name": name,
            "description": description,
            "steps": steps,
            "created": time.time(),
        }

        step_summary = "\n".join(
            f"  {i + 1}. [{s.get('tool', '?')}] {s.get('description', '')}"
            for i, s in enumerate(steps)
        )
        return ToolResult(
            output=f"Workflow '{name}' defined with {len(steps)} steps:\n{step_summary}",
            success=True,
        )

    async def _run(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="Workflow name required", success=False)
        if name not in self._workflows:
            return ToolResult(error=f"Workflow '{name}' not found", success=False)
        if not self._registry:
            return ToolResult(
                error="No tool registry available — cannot execute steps", success=False
            )

        workflow = self._workflows[name]
        steps = workflow["steps"]
        results = []
        start = time.time()

        for i, step in enumerate(steps):
            tool_name = step.get("tool", "")
            tool_args = step.get("args", {})
            step_desc = step.get("description", f"Step {i + 1}")
            continue_on_error = step.get("continue_on_error", False)

            logger.info(f"Workflow '{name}' step {i + 1}/{len(steps)}: {step_desc}")

            result = await self._registry.execute(tool_name, **tool_args)
            results.append(
                {
                    "step": i + 1,
                    "description": step_desc,
                    "tool": tool_name,
                    "success": result.success,
                    "output": result.output[:500] if result.success else "",
                    "error": result.error[:200] if not result.success else "",
                }
            )

            if not result.success and not continue_on_error:
                break

        elapsed = time.time() - start
        all_passed = all(r["success"] for r in results)

        lines = [
            f"## Workflow '{name}' — {'PASSED' if all_passed else 'FAILED'}",
            f"**Steps:** {len(results)}/{len(steps)} executed ({elapsed:.1f}s)\n",
        ]
        for r in results:
            status = "PASS" if r["success"] else "FAIL"
            lines.append(f"### Step {r['step']}: [{status}] {r['description']}")
            if r["output"]:
                lines.append(f"```\n{r['output']}\n```")
            if r["error"]:
                lines.append(f"**Error:** {r['error']}")
            lines.append("")

        return ToolResult(output="\n".join(lines), success=all_passed)

    def _list(self) -> ToolResult:
        if not self._workflows:
            return ToolResult(output="No workflows defined.", success=True)

        lines = ["## Workflows\n"]
        for name, wf in self._workflows.items():
            lines.append(
                f"- **{name}** — {wf['description'] or '(no description)'} ({len(wf['steps'])} steps)"
            )
        return ToolResult(output="\n".join(lines), success=True)

    def _show(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="Workflow name required", success=False)
        if name not in self._workflows:
            return ToolResult(error=f"Workflow '{name}' not found", success=False)

        wf = self._workflows[name]
        lines = [
            f"## Workflow: {name}",
            f"**Description:** {wf['description'] or '(none)'}",
            f"**Steps:** {len(wf['steps'])}\n",
        ]
        for i, step in enumerate(wf["steps"]):
            cont = " (continue on error)" if step.get("continue_on_error") else ""
            lines.append(f"  {i + 1}. **{step.get('tool', '?')}**{cont}")
            if step.get("description"):
                lines.append(f"     {step['description']}")
            if step.get("args"):
                lines.append(f"     Args: {json.dumps(step['args'], indent=2)}")
        return ToolResult(output="\n".join(lines), success=True)

    def _delete(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="Workflow name required", success=False)
        if name not in self._workflows:
            return ToolResult(error=f"Workflow '{name}' not found", success=False)
        del self._workflows[name]
        return ToolResult(output=f"Workflow '{name}' deleted.", success=True)

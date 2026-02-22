"""
PR generator tool — create pull requests from task descriptions.

Inspired by Sweep's issue-to-PR automation. Uses the gh CLI to create
well-structured PRs with description, test plan, and linked issues.
"""

import asyncio
import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.pr_generator")


class PRGeneratorTool(Tool):
    """Create GitHub pull requests with structured descriptions."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "create_pr"

    @property
    def description(self) -> str:
        return (
            "Create a GitHub pull request using gh CLI. Generates structured "
            "PR descriptions with summary, changes, test plan. Can also list, "
            "view, and check PR status."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "view", "checks", "merge", "diff"],
                    "description": "PR action to perform",
                },
                "title": {
                    "type": "string",
                    "description": "PR title (for create action)",
                    "default": "",
                },
                "body": {
                    "type": "string",
                    "description": "PR body/description (for create action)",
                    "default": "",
                },
                "base": {
                    "type": "string",
                    "description": "Base branch (default: main)",
                    "default": "main",
                },
                "draft": {
                    "type": "boolean",
                    "description": "Create as draft PR (default: false)",
                    "default": False,
                },
                "number": {
                    "type": "integer",
                    "description": "PR number (for view/checks/merge/diff)",
                    "default": 0,
                },
                "issue": {
                    "type": "integer",
                    "description": "Issue number to link (for create)",
                    "default": 0,
                },
            },
            "required": ["action"],
        }

    async def _run_gh(self, args: list[str], timeout: float = 60.0) -> ToolResult:
        """Execute a gh CLI command."""
        cmd = ["gh"] + args
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=self._workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except FileNotFoundError:
            return ToolResult(
                error="GitHub CLI (gh) not installed. Run: https://cli.github.com/",
                success=False,
            )
        except TimeoutError:
            proc.kill()
            return ToolResult(error="gh command timed out", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")

        if len(output) > 50000:
            output = output[:50000] + "\n... (truncated)"

        return ToolResult(
            output=output if output.strip() else errors,
            success=proc.returncode == 0,
            error=errors if proc.returncode != 0 else "",
        )

    async def execute(
        self,
        action: str = "",
        title: str = "",
        body: str = "",
        base: str = "main",
        draft: bool = False,
        number: int = 0,
        issue: int = 0,
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        if action == "create":
            return await self._create_pr(title, body, base, draft, issue)
        elif action == "list":
            return await self._run_gh(["pr", "list"])
        elif action == "view":
            if not number:
                return ToolResult(error="PR number required", success=False)
            return await self._run_gh(["pr", "view", str(number)])
        elif action == "checks":
            if not number:
                return ToolResult(error="PR number required", success=False)
            return await self._run_gh(["pr", "checks", str(number)])
        elif action == "merge":
            if not number:
                return ToolResult(error="PR number required", success=False)
            return await self._run_gh(["pr", "merge", str(number), "--squash"])
        elif action == "diff":
            if not number:
                return ToolResult(error="PR number required", success=False)
            return await self._run_gh(["pr", "diff", str(number)])
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    async def _create_pr(
        self,
        title: str,
        body: str,
        base: str,
        draft: bool,
        issue: int,
    ) -> ToolResult:
        if not title:
            return ToolResult(error="PR title required", success=False)

        # Auto-generate body if not provided
        if not body:
            body = await self._auto_generate_body(issue)

        args = ["pr", "create", "--title", title, "--body", body, "--base", base]
        if draft:
            args.append("--draft")

        return await self._run_gh(args)

    async def _auto_generate_body(self, issue: int) -> str:
        """Generate a PR body from git diff stats."""
        parts = ["## Summary\n"]

        # Get diff stats
        proc = await asyncio.create_subprocess_exec(
            "git",
            "diff",
            "--stat",
            "origin/main...HEAD",
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        diff_stat = stdout.decode("utf-8", errors="replace")
        if diff_stat.strip():
            parts.append(f"### Changes\n```\n{diff_stat.strip()}\n```\n")

        # Get commit log
        proc = await asyncio.create_subprocess_exec(
            "git",
            "log",
            "--oneline",
            "origin/main...HEAD",
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=15)
        log = stdout.decode("utf-8", errors="replace")
        if log.strip():
            parts.append(f"### Commits\n```\n{log.strip()}\n```\n")

        if issue:
            parts.append(f"Closes #{issue}\n")

        parts.append("## Test Plan\n- [ ] Tests pass\n- [ ] Manual verification\n")

        return "\n".join(parts)

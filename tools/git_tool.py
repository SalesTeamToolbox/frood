"""
Dedicated git tool — structured git operations for agents.

Provides safe, sandboxed git operations without requiring shell access.
Each action returns structured output that the LLM can parse reliably.

Security:
- Blocks git flags that could execute arbitrary commands (e.g., --upload-pack)
- Sanitizes user-provided arguments before passing to git subprocess
- Uses create_subprocess_exec (not shell) to prevent shell injection
"""

import asyncio
import logging
import re

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.git")

# Git flags that can execute arbitrary commands
_DANGEROUS_GIT_FLAGS = re.compile(
    r"--(?:upload-pack|receive-pack|exec|exec-path|config|git-dir)"
    r"|--(?:work-tree=(?:/etc|/var|/tmp))"
    r"|-c\s",
    re.IGNORECASE,
)


class GitTool(Tool):
    """Structured git operations for agent use."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "git"

    @property
    def description(self) -> str:
        return (
            "Perform git operations. Actions: status, diff, log, branch, "
            "commit, add, checkout, show. Safer than shell for git work."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "status",
                        "diff",
                        "log",
                        "branch",
                        "commit",
                        "add",
                        "checkout",
                        "show",
                        "stash",
                        "blame",
                    ],
                    "description": "Git action to perform",
                },
                "args": {
                    "type": "string",
                    "description": "Additional arguments (e.g., file path, branch name, commit message)",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    @staticmethod
    def _sanitize_args(args: str) -> str | None:
        """Check args for dangerous git flags. Returns error message or None."""
        if _DANGEROUS_GIT_FLAGS.search(args):
            return "Blocked: git arguments contain potentially dangerous flags"
        return None

    async def execute(self, action: str = "", args: str = "", **kwargs) -> ToolResult:
        if not action:
            return ToolResult(error="No action specified", success=False)

        # Sanitize args before passing to any handler
        if args:
            err = self._sanitize_args(args)
            if err:
                return ToolResult(error=err, success=False)

        # Map actions to git commands with safety constraints
        handlers = {
            "status": self._status,
            "diff": self._diff,
            "log": self._log,
            "branch": self._branch,
            "commit": self._commit,
            "add": self._add,
            "checkout": self._checkout,
            "show": self._show,
            "stash": self._stash,
            "blame": self._blame,
        }

        handler = handlers.get(action)
        if not handler:
            return ToolResult(error=f"Unknown git action: {action}", success=False)

        return await handler(args)

    async def _run_git(self, *args: str, timeout: float = 30.0) -> tuple[int, str, str]:
        """Run a git command and return (returncode, stdout, stderr)."""
        proc = await asyncio.create_subprocess_exec(
            "git",
            *args,
            cwd=self._workspace,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            return 1, "", "Command timed out"
        return (
            proc.returncode,
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace"),
        )

    async def _status(self, args: str) -> ToolResult:
        code, out, err = await self._run_git("status", "--porcelain=v2", "--branch")
        if code != 0:
            return ToolResult(error=f"git status failed: {err}", success=False)
        # Also get a human-readable status
        _, readable, _ = await self._run_git("status", "--short")
        return ToolResult(output=f"## Branch Info\n{out}\n## Changed Files\n{readable}")

    async def _diff(self, args: str) -> ToolResult:
        cmd = ["diff", "--stat"]
        if args:
            cmd.extend(args.split())
        code, out, err = await self._run_git(*cmd)
        if code != 0:
            return ToolResult(error=f"git diff failed: {err}", success=False)

        # Also get the full diff (truncated)
        cmd_full = ["diff"]
        if args:
            cmd_full.extend(args.split())
        _, full_diff, _ = await self._run_git(*cmd_full)
        if len(full_diff) > 50000:
            full_diff = full_diff[:50000] + "\n... (diff truncated)"
        return ToolResult(output=f"## Diff Summary\n{out}\n## Full Diff\n{full_diff}")

    async def _log(self, args: str) -> ToolResult:
        cmd = ["log", "--oneline", "--graph", "-20"]
        if args:
            # Extend defaults with user args rather than replacing entirely
            extra = [a for a in args.split() if not a.startswith("--exec")]
            cmd = ["log", "--oneline", "-20"] + extra
        code, out, err = await self._run_git(*cmd)
        if code != 0:
            return ToolResult(error=f"git log failed: {err}", success=False)
        return ToolResult(output=out)

    async def _branch(self, args: str) -> ToolResult:
        if not args:
            # List branches
            code, out, err = await self._run_git("branch", "-vv")
            if code != 0:
                return ToolResult(error=f"git branch failed: {err}", success=False)
            return ToolResult(output=out)

        parts = args.split()
        if parts[0] in ("-d", "--delete"):
            return ToolResult(
                error="Branch deletion blocked — use dashboard or manual git", success=False
            )

        # Create new branch
        code, out, err = await self._run_git("branch", *parts)
        if code != 0:
            return ToolResult(error=f"git branch failed: {err}", success=False)
        return ToolResult(output=f"Branch created: {args}")

    async def _commit(self, args: str) -> ToolResult:
        if not args:
            return ToolResult(error="Commit message required", success=False)
        if len(args) > 10000:
            return ToolResult(error="Commit message too long (max 10000 chars)", success=False)
        code, out, err = await self._run_git("commit", "-m", args)
        if code != 0:
            if "nothing to commit" in err or "nothing to commit" in out:
                return ToolResult(output="Nothing to commit (working tree clean)")
            return ToolResult(error=f"git commit failed: {err}", success=False)
        return ToolResult(output=out)

    async def _add(self, args: str) -> ToolResult:
        if not args:
            args = "."
        # Block adding sensitive files
        blocked = {".env", ".env.local", ".env.production", "credentials.json", "secrets.yaml"}
        for path in args.split():
            if path in blocked:
                return ToolResult(
                    error=f"Blocked: cannot stage sensitive file '{path}'", success=False
                )
        code, out, err = await self._run_git("add", *args.split())
        if code != 0:
            return ToolResult(error=f"git add failed: {err}", success=False)
        return ToolResult(output=f"Staged: {args}")

    async def _checkout(self, args: str) -> ToolResult:
        if not args:
            return ToolResult(error="Branch or file path required", success=False)
        parts = args.split()
        # Block force checkout
        if "--force" in parts or "-f" in parts:
            return ToolResult(error="Force checkout blocked — may discard changes", success=False)
        code, out, err = await self._run_git("checkout", *parts)
        if code != 0:
            return ToolResult(error=f"git checkout failed: {err}", success=False)
        return ToolResult(output=f"Checked out: {args}")

    async def _show(self, args: str) -> ToolResult:
        target = args or "HEAD"
        code, out, err = await self._run_git("show", "--stat", target)
        if code != 0:
            return ToolResult(error=f"git show failed: {err}", success=False)
        if len(out) > 30000:
            out = out[:30000] + "\n... (truncated)"
        return ToolResult(output=out)

    async def _stash(self, args: str) -> ToolResult:
        parts = args.split() if args else ["list"]
        action = parts[0] if parts else "list"
        if action not in ("list", "push", "pop", "show"):
            return ToolResult(error=f"Unsupported stash action: {action}", success=False)
        code, out, err = await self._run_git("stash", *parts)
        if code != 0:
            return ToolResult(error=f"git stash failed: {err}", success=False)
        return ToolResult(output=out or "Stash operation complete")

    async def _blame(self, args: str) -> ToolResult:
        if not args:
            return ToolResult(error="File path required for blame", success=False)
        code, out, err = await self._run_git("blame", "--line-porcelain", args.split()[0])
        if code != 0:
            return ToolResult(error=f"git blame failed: {err}", success=False)
        if len(out) > 30000:
            out = out[:30000] + "\n... (truncated)"
        return ToolResult(output=out)

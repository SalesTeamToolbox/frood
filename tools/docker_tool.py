"""
Docker sandbox tool — manage isolated execution environments.

Inspired by OpenHands' Docker container sandboxes and SWE-agent's SWE-ReX.
Provides container lifecycle management and command execution in isolated environments.
"""

import asyncio
import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.docker")


class DockerTool(Tool):
    """Manage Docker containers for sandboxed code execution."""

    def __init__(self, workspace_path: str = "."):
        self._workspace = workspace_path

    @property
    def name(self) -> str:
        return "docker"

    @property
    def description(self) -> str:
        return (
            "Manage Docker containers: run commands in isolated environments, "
            "build images, manage containers. For sandboxed code execution."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "run", "exec", "build", "ps", "logs",
                        "stop", "rm", "images", "pull",
                    ],
                    "description": "Docker action to perform",
                },
                "image": {
                    "type": "string",
                    "description": "Docker image name (for run/build/pull)",
                    "default": "",
                },
                "container": {
                    "type": "string",
                    "description": "Container name or ID (for exec/logs/stop/rm)",
                    "default": "",
                },
                "command": {
                    "type": "string",
                    "description": "Command to run inside the container",
                    "default": "",
                },
                "dockerfile": {
                    "type": "string",
                    "description": "Path to Dockerfile (for build)",
                    "default": "Dockerfile",
                },
                "tag": {
                    "type": "string",
                    "description": "Image tag (for build)",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def _run_docker(self, args: list[str], timeout: float = 120.0) -> ToolResult:
        """Execute a docker command and return structured result."""
        cmd = ["docker"] + args
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
                error="Docker is not installed or not in PATH",
                success=False,
            )
        except asyncio.TimeoutError:
            proc.kill()
            return ToolResult(error=f"Docker command timed out (>{timeout}s)", success=False)

        output = stdout.decode("utf-8", errors="replace")
        errors = stderr.decode("utf-8", errors="replace")

        if len(output) > 50000:
            output = output[:50000] + "\n... (truncated)"

        combined = output
        if errors and proc.returncode != 0:
            combined += f"\nSTDERR:\n{errors}"

        return ToolResult(
            output=combined if combined.strip() else "(no output)",
            success=proc.returncode == 0,
            error=errors if proc.returncode != 0 else "",
        )

    async def execute(
        self,
        action: str = "",
        image: str = "",
        container: str = "",
        command: str = "",
        dockerfile: str = "Dockerfile",
        tag: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        if action == "run":
            return await self._action_run(image, command)
        elif action == "exec":
            return await self._action_exec(container, command)
        elif action == "build":
            return await self._action_build(dockerfile, tag)
        elif action == "ps":
            return await self._run_docker(["ps", "--format", "table {{.ID}}\t{{.Image}}\t{{.Status}}\t{{.Names}}"])
        elif action == "logs":
            if not container:
                return ToolResult(error="Container name/ID required", success=False)
            return await self._run_docker(["logs", "--tail", "100", container])
        elif action == "stop":
            if not container:
                return ToolResult(error="Container name/ID required", success=False)
            return await self._run_docker(["stop", container])
        elif action == "rm":
            if not container:
                return ToolResult(error="Container name/ID required", success=False)
            return await self._run_docker(["rm", container])
        elif action == "images":
            return await self._run_docker(["images", "--format", "table {{.Repository}}\t{{.Tag}}\t{{.Size}}"])
        elif action == "pull":
            if not image:
                return ToolResult(error="Image name required", success=False)
            return await self._run_docker(["pull", image], timeout=300.0)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    async def _action_run(self, image: str, command: str) -> ToolResult:
        if not image:
            return ToolResult(error="Image name required for run", success=False)

        args = [
            "run", "--rm",
            "--network=none",  # No network access for security
            "--memory=512m",   # Memory limit
            "--cpus=1",        # CPU limit
            "-v", f"{self._workspace}:/workspace:ro",  # Read-only workspace mount
            "-w", "/workspace",
            image,
        ]
        if command:
            args.extend(["sh", "-c", command])

        return await self._run_docker(args, timeout=300.0)

    async def _action_exec(self, container: str, command: str) -> ToolResult:
        if not container:
            return ToolResult(error="Container name/ID required", success=False)
        if not command:
            return ToolResult(error="Command required for exec", success=False)

        return await self._run_docker(["exec", container, "sh", "-c", command])

    async def _action_build(self, dockerfile: str, tag: str) -> ToolResult:
        args = ["build", "-f", dockerfile]
        if tag:
            args.extend(["-t", tag])
        args.append(".")

        return await self._run_docker(args, timeout=600.0)

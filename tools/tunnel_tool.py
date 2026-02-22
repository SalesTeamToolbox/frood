"""
Tunnel manager tool — expose local services to the internet.

Supports multiple tunnel providers for previewing locally-running
websites, APIs, and services. Useful for sharing dev servers,
WordPress installations, or any local HTTP service.

Security:
1. TUNNEL_ENABLED must be true (disabled by default)
2. ApprovalGate — human approval required before exposing any port
3. TUNNEL_ALLOWED_PORTS — restricts which ports can be tunneled
4. TTL auto-expiry — tunnels shut down after configurable duration
"""

import asyncio
import logging
import re
import shutil
import time
import uuid
from dataclasses import dataclass, field

from core.approval_gate import ApprovalGate, ProtectedAction
from core.config import settings
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.tunnel")


@dataclass
class TunnelInfo:
    """Tracks an active tunnel."""

    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])
    port: int = 0
    provider: str = ""
    url: str = ""
    process: object = None  # asyncio.subprocess.Process
    started_at: float = field(default_factory=time.time)
    ttl_minutes: int = 60


class TunnelTool(Tool):
    """Expose local services to the internet via tunnels.

    Actions:
    - start: Create a new tunnel for a local port
    - stop: Shut down a tunnel by ID
    - status: Check a tunnel's current state
    - list: Show all active tunnels
    """

    def __init__(self, approval_gate: ApprovalGate | None = None):
        self._approval = approval_gate
        self._tunnels: dict[str, TunnelInfo] = {}
        self._expiry_task: asyncio.Task | None = None

    @property
    def name(self) -> str:
        return "tunnel"

    @property
    def description(self) -> str:
        return (
            "Expose local services to the internet for testing and preview. "
            "Actions: start, stop, status, list."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["start", "stop", "status", "list"],
                    "description": "Action to perform",
                },
                "port": {
                    "type": "integer",
                    "description": "Local port to expose (for start)",
                },
                "provider": {
                    "type": "string",
                    "enum": ["auto", "cloudflared", "serveo", "localhost.run"],
                    "description": "Tunnel provider (default: auto-detect)",
                },
                "tunnel_id": {
                    "type": "string",
                    "description": "Tunnel ID (for stop/status)",
                },
            },
            "required": ["action"],
        }

    def _check_port_allowed(self, port: int) -> bool:
        """Check if a port is in the allowed list."""
        allowed = settings.get_tunnel_allowed_ports()
        if not allowed:
            return True  # No restriction configured
        return port in allowed

    def _detect_provider(self) -> str:
        """Auto-detect the best available tunnel provider."""
        configured = settings.tunnel_provider
        if configured and configured != "auto":
            return configured

        # Check for cloudflared binary
        if shutil.which("cloudflared"):
            return "cloudflared"

        # Check for ssh (needed for serveo and localhost.run)
        if shutil.which("ssh"):
            return "serveo"

        return "none"

    async def _start_cloudflared(self, port: int) -> tuple[asyncio.subprocess.Process, str]:
        """Start a Cloudflare tunnel."""
        proc = await asyncio.create_subprocess_exec(
            "cloudflared",
            "tunnel",
            "--url",
            f"http://localhost:{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        # Parse the public URL from cloudflared output (appears on stderr)
        url = ""
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.stderr is None:
                break
            try:
                line = await asyncio.wait_for(proc.stderr.readline(), timeout=2)
                line_str = line.decode("utf-8", errors="replace")
                # cloudflared outputs the URL to stderr
                match = re.search(r"(https://[a-z0-9-]+\.trycloudflare\.com)", line_str)
                if match:
                    url = match.group(1)
                    break
            except TimeoutError:
                continue

        return proc, url

    async def _start_serveo(self, port: int) -> tuple[asyncio.subprocess.Process, str]:
        """Start a Serveo tunnel via SSH."""
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=60",
            "-R",
            f"80:localhost:{port}",
            "serveo.net",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        url = ""
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.stdout is None:
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=2)
                line_str = line.decode("utf-8", errors="replace")
                match = re.search(r"(https?://[a-z0-9]+\.serveo\.net)", line_str)
                if match:
                    url = match.group(1)
                    break
            except TimeoutError:
                continue

        return proc, url

    async def _start_localhost_run(self, port: int) -> tuple[asyncio.subprocess.Process, str]:
        """Start a localhost.run tunnel via SSH."""
        proc = await asyncio.create_subprocess_exec(
            "ssh",
            "-o",
            "StrictHostKeyChecking=no",
            "-o",
            "ServerAliveInterval=60",
            "-R",
            f"80:localhost:{port}",
            "nokey@localhost.run",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        url = ""
        deadline = time.time() + 30
        while time.time() < deadline:
            if proc.stdout is None:
                break
            try:
                line = await asyncio.wait_for(proc.stdout.readline(), timeout=2)
                line_str = line.decode("utf-8", errors="replace")
                match = re.search(r"(https?://[a-z0-9]+\.lhr\.life)", line_str)
                if not match:
                    match = re.search(r"(https?://[^\s]+localhost\.run[^\s]*)", line_str)
                if match:
                    url = match.group(1)
                    break
            except TimeoutError:
                continue

        return proc, url

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if action == "start":
            return await self._start(**kwargs)
        elif action == "stop":
            return await self._stop(**kwargs)
        elif action == "status":
            return self._status(**kwargs)
        elif action == "list":
            return self._list()
        return ToolResult(error=f"Unknown action: {action}", success=False)

    async def _start(self, port: int = 0, provider: str = "auto", **kwargs) -> ToolResult:
        if not port:
            return ToolResult(error="Port is required for start", success=False)

        # Security: check port allowlist
        if not self._check_port_allowed(port):
            return ToolResult(
                error=f"Port {port} is not in the allowed tunnel ports list (TUNNEL_ALLOWED_PORTS)",
                success=False,
            )

        # Security: approval gate
        if self._approval:
            task_id = kwargs.get("task_id", "tunnel")
            approved = await self._approval.request(
                task_id=task_id,
                action=ProtectedAction.TUNNEL_START,
                description=f"Expose local port {port} to the internet",
                details={"port": port, "provider": provider},
            )
            if not approved:
                return ToolResult(error="Tunnel creation denied by approval gate", success=False)

        # Check if port already tunneled
        for t in self._tunnels.values():
            if t.port == port:
                return ToolResult(output=f"Port {port} already tunneled: {t.url} (ID: {t.id})")

        # Detect provider
        actual_provider = provider if provider != "auto" else self._detect_provider()
        if actual_provider == "none":
            return ToolResult(
                error="No tunnel provider available. Install cloudflared or ensure ssh is available.",
                success=False,
            )

        # Start the tunnel
        try:
            if actual_provider == "cloudflared":
                proc, url = await self._start_cloudflared(port)
            elif actual_provider == "serveo":
                proc, url = await self._start_serveo(port)
            elif actual_provider == "localhost.run":
                proc, url = await self._start_localhost_run(port)
            else:
                return ToolResult(error=f"Unknown provider: {actual_provider}", success=False)
        except FileNotFoundError:
            return ToolResult(
                error=f"Provider binary not found for '{actual_provider}'",
                success=False,
            )
        except Exception as e:
            return ToolResult(error=f"Failed to start tunnel: {e}", success=False)

        if not url:
            # Process may have failed
            if proc.returncode is not None:
                return ToolResult(
                    error=f"Tunnel process exited with code {proc.returncode}",
                    success=False,
                )
            return ToolResult(
                error="Could not determine tunnel URL (timeout waiting for provider)",
                success=False,
            )

        tunnel = TunnelInfo(
            port=port,
            provider=actual_provider,
            url=url,
            process=proc,
            ttl_minutes=settings.tunnel_ttl_minutes,
        )
        self._tunnels[tunnel.id] = tunnel

        # Start expiry monitor if not running
        if self._expiry_task is None or self._expiry_task.done():
            self._expiry_task = asyncio.create_task(self._expiry_loop())

        logger.info(f"Tunnel started: {tunnel.id} → {url} (port {port}, {actual_provider})")
        return ToolResult(
            output=f"Tunnel created!\n  ID: {tunnel.id}\n  URL: {url}\n  Port: {port}\n  Provider: {actual_provider}\n  TTL: {tunnel.ttl_minutes} minutes"
        )

    async def _stop(self, tunnel_id: str = "", **kwargs) -> ToolResult:
        if not tunnel_id:
            return ToolResult(error="tunnel_id is required for stop", success=False)

        tunnel = self._tunnels.pop(tunnel_id, None)
        if not tunnel:
            return ToolResult(error=f"Tunnel not found: {tunnel_id}", success=False)

        await self._kill_tunnel(tunnel)
        logger.info(f"Tunnel stopped: {tunnel_id}")
        return ToolResult(output=f"Tunnel {tunnel_id} stopped (was: {tunnel.url})")

    def _status(self, tunnel_id: str = "", **kwargs) -> ToolResult:
        if not tunnel_id:
            return ToolResult(error="tunnel_id is required for status", success=False)

        tunnel = self._tunnels.get(tunnel_id)
        if not tunnel:
            return ToolResult(error=f"Tunnel not found: {tunnel_id}", success=False)

        elapsed = (time.time() - tunnel.started_at) / 60
        remaining = tunnel.ttl_minutes - elapsed
        alive = tunnel.process is not None and tunnel.process.returncode is None

        return ToolResult(
            output=(
                f"Tunnel {tunnel.id}:\n"
                f"  URL: {tunnel.url}\n"
                f"  Port: {tunnel.port}\n"
                f"  Provider: {tunnel.provider}\n"
                f"  Running: {alive}\n"
                f"  Uptime: {elapsed:.0f}m\n"
                f"  TTL remaining: {max(0, remaining):.0f}m"
            )
        )

    def _list(self) -> ToolResult:
        if not self._tunnels:
            return ToolResult(output="No active tunnels.")

        lines = [f"{'ID':<10} {'Port':<6} {'Provider':<15} {'URL':<50}"]
        for t in self._tunnels.values():
            lines.append(f"{t.id:<10} {t.port:<6} {t.provider:<15} {t.url:<50}")
        return ToolResult(output="\n".join(lines))

    async def _kill_tunnel(self, tunnel: TunnelInfo):
        """Terminate a tunnel subprocess."""
        if tunnel.process is not None:
            try:
                tunnel.process.terminate()
                await asyncio.wait_for(tunnel.process.wait(), timeout=5)
            except (TimeoutError, ProcessLookupError):
                try:
                    tunnel.process.kill()
                except ProcessLookupError:
                    pass

    async def _expiry_loop(self):
        """Background task to auto-expire tunnels past their TTL."""
        while self._tunnels:
            now = time.time()
            expired = []
            for tid, tunnel in self._tunnels.items():
                age_minutes = (now - tunnel.started_at) / 60
                if age_minutes >= tunnel.ttl_minutes:
                    expired.append(tid)

            for tid in expired:
                tunnel = self._tunnels.pop(tid, None)
                if tunnel:
                    await self._kill_tunnel(tunnel)
                    logger.info(f"Tunnel expired: {tid} (TTL: {tunnel.ttl_minutes}m)")

            await asyncio.sleep(30)

    async def cleanup(self):
        """Close all tunnels. Called on Agent42 shutdown."""
        if self._expiry_task and not self._expiry_task.done():
            self._expiry_task.cancel()
        for tunnel in list(self._tunnels.values()):
            await self._kill_tunnel(tunnel)
        self._tunnels.clear()

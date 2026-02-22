"""
SSH remote shell tool — execute commands on remote servers.

Security layers:
1. SSH_ENABLED must be true (disabled by default)
2. SSH_ALLOWED_HOSTS — allowlist of host patterns
3. ApprovalGate — human approval required for first connection to each host
4. CommandFilter — deny-pattern filtering applied to remote commands
5. Credential sanitization — redacts secrets from command output
"""

import asyncio
import fnmatch
import logging
import re
from dataclasses import dataclass

from core.approval_gate import ApprovalGate, ProtectedAction
from core.command_filter import CommandFilter, CommandFilterError
from core.config import settings
from core.sandbox import WorkspaceSandbox
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.ssh")

MAX_OUTPUT_LENGTH = 10000
DEFAULT_CONNECT_TIMEOUT = 30

# Credential patterns to redact from remote output (shared with shell.py)
_CREDENTIAL_PATTERNS = [
    (re.compile(r"(?i)(password|passwd|pwd)\s*[=:]\s*\S+"), r"\1=***REDACTED***"),
    (re.compile(r"(?i)(api[_-]?key|apikey)\s*[=:]\s*\S+"), r"\1=***REDACTED***"),
    (re.compile(r"(?i)(secret|api[_-]?secret)\s*[=:]\s*\S+"), r"\1=***REDACTED***"),
    (re.compile(r"(?i)(token|auth[_-]?token|access[_-]?token)\s*[=:]\s*\S+"), r"\1=***REDACTED***"),
    (re.compile(r"(?i)(database[_-]?url|db[_-]?url)\s*[=:]\s*\S+"), r"\1=***REDACTED***"),
    (re.compile(r"AKIA[0-9A-Z]{16}"), "***AWS_KEY_REDACTED***"),
    (re.compile(r"xox[bpras]-[a-zA-Z0-9-]{10,}"), "***SLACK_TOKEN_REDACTED***"),
    (re.compile(r"gh[pousr]_[A-Za-z0-9_]{36,}"), "***GITHUB_TOKEN_REDACTED***"),
]


def _sanitize_output(text: str) -> str:
    """Redact likely credentials from command output."""
    for pattern, replacement in _CREDENTIAL_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


@dataclass
class SSHConnection:
    """Tracks an active SSH connection."""

    host: str
    port: int
    username: str
    conn: object = None  # asyncssh.SSHClientConnection
    approved: bool = False
    connected_at: float = 0.0


class SSHTool(Tool):
    """Execute commands on remote servers via SSH.

    Actions:
    - connect: Establish an SSH connection (requires approval)
    - execute: Run a command on a connected remote host
    - upload: Transfer a file to the remote host via SFTP
    - download: Transfer a file from the remote host via SFTP
    - disconnect: Close an SSH connection
    - list_connections: Show active connections
    """

    def __init__(
        self,
        sandbox: WorkspaceSandbox,
        command_filter: CommandFilter | None = None,
        approval_gate: ApprovalGate | None = None,
    ):
        self._sandbox = sandbox
        self._filter = command_filter or CommandFilter()
        self._approval = approval_gate
        self._connections: dict[str, SSHConnection] = {}
        self._approved_hosts: set[str] = set()

    @property
    def name(self) -> str:
        return "ssh"

    @property
    def description(self) -> str:
        return (
            "Execute commands on remote servers via SSH. "
            "Actions: connect, execute, upload, download, disconnect, list_connections."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "connect",
                        "execute",
                        "upload",
                        "download",
                        "disconnect",
                        "list_connections",
                    ],
                    "description": "Action to perform",
                },
                "host": {
                    "type": "string",
                    "description": "Remote hostname or IP (for connect/execute/upload/download)",
                },
                "port": {
                    "type": "integer",
                    "description": "SSH port (default: 22)",
                    "default": 22,
                },
                "username": {
                    "type": "string",
                    "description": "SSH username (for connect)",
                },
                "password": {
                    "type": "string",
                    "description": "SSH password (prefer key-based auth)",
                },
                "key_path": {
                    "type": "string",
                    "description": "Path to SSH private key file (for connect)",
                },
                "command": {
                    "type": "string",
                    "description": "Command to execute remotely (for execute)",
                },
                "local_path": {
                    "type": "string",
                    "description": "Local file path (for upload/download)",
                },
                "remote_path": {
                    "type": "string",
                    "description": "Remote file path (for upload/download)",
                },
            },
            "required": ["action"],
        }

    def _connection_key(self, host: str, port: int = 22) -> str:
        return f"{host}:{port}"

    def _check_host_allowed(self, host: str) -> bool:
        """Check if a host is in the allowed hosts list."""
        allowed = settings.get_ssh_allowed_hosts()
        if not allowed:
            # No allowlist configured = all hosts allowed (approval still required)
            return True
        return any(fnmatch.fnmatch(host, pattern) for pattern in allowed)

    async def _ensure_approved(self, host: str, port: int, task_id: str = "") -> bool:
        """Check approval for connecting to a host."""
        key = self._connection_key(host, port)
        if key in self._approved_hosts:
            return True

        if not self._approval:
            # No approval gate configured — allow
            self._approved_hosts.add(key)
            return True

        approved = await self._approval.request(
            task_id=task_id or "ssh",
            action=ProtectedAction.SSH_CONNECT,
            description=f"SSH connection to {host}:{port}",
            details={"host": host, "port": port},
        )
        if approved:
            self._approved_hosts.add(key)
        return approved

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if action == "list_connections":
            return self._list_connections()

        if action == "connect":
            return await self._connect(**kwargs)
        elif action == "execute":
            return await self._execute_command(**kwargs)
        elif action == "upload":
            return await self._upload(**kwargs)
        elif action == "download":
            return await self._download(**kwargs)
        elif action == "disconnect":
            return await self._disconnect(**kwargs)

        return ToolResult(error=f"Unknown action: {action}", success=False)

    async def _connect(
        self,
        host: str = "",
        port: int = 22,
        username: str = "",
        password: str = "",
        key_path: str = "",
        **kwargs,
    ) -> ToolResult:
        if not host:
            return ToolResult(error="Host is required for connect", success=False)
        if not username:
            return ToolResult(error="Username is required for connect", success=False)

        # Security check: host allowlist
        if not self._check_host_allowed(host):
            logger.warning(f"SSH blocked: host {host} not in allowed list")
            return ToolResult(
                error=f"Host '{host}' is not in the SSH allowed hosts list (SSH_ALLOWED_HOSTS)",
                success=False,
            )

        # Security check: approval gate
        task_id = kwargs.get("task_id", "ssh")
        approved = await self._ensure_approved(host, port, task_id)
        if not approved:
            return ToolResult(error="SSH connection denied by approval gate", success=False)

        key = self._connection_key(host, port)
        if key in self._connections and self._connections[key].conn is not None:
            return ToolResult(output=f"Already connected to {host}:{port}")

        try:
            import asyncssh
        except ImportError:
            return ToolResult(
                error="asyncssh is not installed. Run: pip install asyncssh",
                success=False,
            )

        # Build connection kwargs
        connect_kwargs: dict = {
            "host": host,
            "port": port,
            "username": username,
            "known_hosts": None,  # Accept unknown hosts (operator approved via gate)
        }

        # Prefer key-based auth
        resolved_key = key_path or settings.ssh_default_key_path
        if resolved_key:
            connect_kwargs["client_keys"] = [resolved_key]
        if password:
            connect_kwargs["password"] = password

        try:
            conn = await asyncio.wait_for(
                asyncssh.connect(**connect_kwargs),
                timeout=DEFAULT_CONNECT_TIMEOUT,
            )

            import time

            self._connections[key] = SSHConnection(
                host=host,
                port=port,
                username=username,
                conn=conn,
                approved=True,
                connected_at=time.time(),
            )

            logger.info(f"SSH connected to {username}@{host}:{port}")
            return ToolResult(output=f"Connected to {username}@{host}:{port}")

        except TimeoutError:
            return ToolResult(
                error=f"SSH connection to {host}:{port} timed out after {DEFAULT_CONNECT_TIMEOUT}s",
                success=False,
            )
        except Exception as e:
            logger.error(f"SSH connection failed: {e}")
            return ToolResult(error=f"SSH connection failed: {e}", success=False)

    async def _execute_command(
        self,
        host: str = "",
        command: str = "",
        port: int = 22,
        **kwargs,
    ) -> ToolResult:
        if not host:
            return ToolResult(error="Host is required for execute", success=False)
        if not command:
            return ToolResult(error="Command is required for execute", success=False)

        key = self._connection_key(host, port)
        conn_info = self._connections.get(key)
        if not conn_info or conn_info.conn is None:
            return ToolResult(
                error=f"Not connected to {host}:{port}. Use connect action first.",
                success=False,
            )

        # Security: apply command filter to remote commands
        try:
            self._filter.check(command)
        except CommandFilterError as e:
            logger.warning(f"SSH command blocked (filter): {command} — {e}")
            return ToolResult(error=f"Command blocked by security filter: {e}", success=False)

        timeout = settings.ssh_command_timeout
        try:
            result = await asyncio.wait_for(
                conn_info.conn.run(command, check=False),
                timeout=timeout,
            )

            stdout = result.stdout or ""
            stderr = result.stderr or ""

            # Sanitize credentials from output
            stdout = _sanitize_output(stdout)
            stderr = _sanitize_output(stderr)

            # Truncate long outputs
            if len(stdout) > MAX_OUTPUT_LENGTH:
                stdout = stdout[:MAX_OUTPUT_LENGTH] + "\n... (output truncated)"
            if len(stderr) > MAX_OUTPUT_LENGTH:
                stderr = stderr[:MAX_OUTPUT_LENGTH] + "\n... (output truncated)"

            combined = stdout
            if stderr:
                combined += f"\nSTDERR:\n{stderr}"

            return ToolResult(
                output=combined,
                success=result.exit_status == 0,
                error=stderr if result.exit_status != 0 else "",
            )

        except TimeoutError:
            return ToolResult(
                error=f"Command timed out after {timeout}s",
                success=False,
            )
        except Exception as e:
            logger.error(f"SSH command execution failed: {e}")
            return ToolResult(error=f"Command execution failed: {e}", success=False)

    async def _upload(
        self,
        host: str = "",
        port: int = 22,
        local_path: str = "",
        remote_path: str = "",
        **kwargs,
    ) -> ToolResult:
        if not host or not local_path or not remote_path:
            return ToolResult(
                error="host, local_path, and remote_path are required for upload",
                success=False,
            )

        key = self._connection_key(host, port)
        conn_info = self._connections.get(key)
        if not conn_info or conn_info.conn is None:
            return ToolResult(
                error=f"Not connected to {host}:{port}. Use connect action first.",
                success=False,
            )

        # Validate local path through sandbox
        try:
            resolved = self._sandbox.resolve_path(local_path)
        except Exception as e:
            return ToolResult(error=f"Local path blocked by sandbox: {e}", success=False)

        # Check file size
        import os

        if not os.path.isfile(str(resolved)):
            return ToolResult(error=f"Local file not found: {local_path}", success=False)

        file_size_mb = os.path.getsize(str(resolved)) / (1024 * 1024)
        if file_size_mb > settings.ssh_max_upload_mb:
            return ToolResult(
                error=f"File size ({file_size_mb:.1f}MB) exceeds limit ({settings.ssh_max_upload_mb}MB)",
                success=False,
            )

        try:
            import asyncssh

            await asyncssh.scp(str(resolved), (conn_info.conn, remote_path))
            logger.info(f"SSH upload: {local_path} → {host}:{remote_path}")
            return ToolResult(output=f"Uploaded {local_path} → {host}:{remote_path}")
        except Exception as e:
            logger.error(f"SSH upload failed: {e}")
            return ToolResult(error=f"Upload failed: {e}", success=False)

    async def _download(
        self,
        host: str = "",
        port: int = 22,
        remote_path: str = "",
        local_path: str = "",
        **kwargs,
    ) -> ToolResult:
        if not host or not remote_path or not local_path:
            return ToolResult(
                error="host, remote_path, and local_path are required for download",
                success=False,
            )

        key = self._connection_key(host, port)
        conn_info = self._connections.get(key)
        if not conn_info or conn_info.conn is None:
            return ToolResult(
                error=f"Not connected to {host}:{port}. Use connect action first.",
                success=False,
            )

        # Validate local destination through sandbox
        try:
            resolved = self._sandbox.resolve_path(local_path)
        except Exception as e:
            return ToolResult(error=f"Local path blocked by sandbox: {e}", success=False)

        try:
            import asyncssh

            await asyncssh.scp((conn_info.conn, remote_path), str(resolved))

            # Check downloaded file size
            import os

            if os.path.isfile(str(resolved)):
                size_mb = os.path.getsize(str(resolved)) / (1024 * 1024)
                if size_mb > settings.ssh_max_upload_mb:
                    os.remove(str(resolved))
                    return ToolResult(
                        error=f"Downloaded file ({size_mb:.1f}MB) exceeds limit. Removed.",
                        success=False,
                    )

            logger.info(f"SSH download: {host}:{remote_path} → {local_path}")
            return ToolResult(output=f"Downloaded {host}:{remote_path} → {local_path}")
        except Exception as e:
            logger.error(f"SSH download failed: {e}")
            return ToolResult(error=f"Download failed: {e}", success=False)

    async def _disconnect(self, host: str = "", port: int = 22, **kwargs) -> ToolResult:
        if not host:
            return ToolResult(error="Host is required for disconnect", success=False)

        key = self._connection_key(host, port)
        conn_info = self._connections.pop(key, None)
        if conn_info and conn_info.conn is not None:
            conn_info.conn.close()
            logger.info(f"SSH disconnected from {host}:{port}")
            return ToolResult(output=f"Disconnected from {host}:{port}")
        return ToolResult(output=f"No active connection to {host}:{port}")

    def _list_connections(self) -> ToolResult:
        if not self._connections:
            return ToolResult(output="No active SSH connections.")

        import time

        lines = [f"{'Host':<30} {'User':<15} {'Connected':<20}"]
        for key, conn in self._connections.items():
            if conn.conn is not None:
                elapsed = time.time() - conn.connected_at
                mins = int(elapsed // 60)
                lines.append(f"{key:<30} {conn.username:<15} {mins}m ago")
        return ToolResult(output="\n".join(lines))

    async def cleanup(self):
        """Close all connections. Called on Agent42 shutdown."""
        for key, conn_info in list(self._connections.items()):
            if conn_info.conn is not None:
                try:
                    conn_info.conn.close()
                except Exception:
                    pass
        self._connections.clear()
        self._approved_hosts.clear()

"""
URL access policy — hostname allowlists, denylists, SSRF protection, and audit logging.

Consolidates all URL validation into a single module used by web_search, http_client,
and browser tools. Inspired by OpenClaw v2026.2.12 hostname allowlist security fixes.
"""

import asyncio
import contextvars
import ipaddress
import json
import logging
import socket
import time
from collections import defaultdict
from fnmatch import fnmatch
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger("frood.url_policy")

# Set by the sidecar orchestrator at the start of each heartbeat run. When set,
# UrlPolicy.check() keys the request counter by run_id instead of the shared
# "default" bucket, so every run gets its own independent URL budget.
_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "frood_url_policy_run_id", default=None
)


def set_current_run_id(run_id: str | None) -> None:
    """Scope subsequent UrlPolicy.check() calls to a specific run_id bucket.

    Called by the sidecar orchestrator at the top of each run. ContextVars are
    task-local under asyncio, so concurrent runs each see their own value.
    """
    _current_run_id.set(run_id)

# SSRF protection: blocked IP ranges (moved from web_search.py)
_BLOCKED_IP_RANGES = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
    ipaddress.ip_network("::ffff:127.0.0.0/104"),
    ipaddress.ip_network("::ffff:10.0.0.0/104"),
    ipaddress.ip_network("::ffff:172.16.0.0/108"),
    ipaddress.ip_network("::ffff:192.168.0.0/112"),
]

_BLOCKED_HOSTNAMES = {
    "localhost",
    "localhost.localdomain",
    "local",
    # Cloud provider metadata endpoints (SSRF targets)
    "metadata.google.internal",  # GCP
    "metadata.internal",  # GCP alt
    "instance-data",  # AWS alt
    "metadata",  # Generic cloud metadata
}


class UrlPolicy:
    """Centralized URL access policy with allowlist, denylist, SSRF, and per-agent limits.

    When allowlist is empty, all public URLs are allowed (backward compatible).
    When allowlist is set, only matching hostnames pass.
    Denylist always takes precedence over allowlist.
    """

    def __init__(
        self,
        allowlist: list[str] | None = None,
        denylist: list[str] | None = None,
        max_requests_per_agent: int = 0,
        audit_log_path: str = ".frood/url_audit.jsonl",
    ):
        self._allowlist = allowlist or []
        self._denylist = denylist or []
        self._max_requests = max_requests_per_agent
        self._agent_counts: dict[str, int] = defaultdict(int)
        self._audit_path = Path(audit_log_path)
        self._audit_path.parent.mkdir(parents=True, exist_ok=True)

    def check(self, url: str, agent_id: str = "default") -> tuple[bool, str]:
        """Check if a URL is allowed.

        Returns (True, "") if allowed, (False, reason) if blocked.
        """
        # Prefer the current-run contextvar as the counter bucket so each
        # heartbeat run gets an independent URL budget. Falls back to the
        # explicit agent_id argument for callers outside a run (tests,
        # direct tool use).
        bucket_key = _current_run_id.get() or agent_id
        is_run_bucket = _current_run_id.get() is not None

        if self._max_requests > 0 and self._agent_counts[bucket_key] >= self._max_requests:
            scope = "Per-run" if is_run_bucket else "Per-agent"
            label = "Run" if is_run_bucket else "Agent"
            reason = (
                f"{scope} URL request limit reached ({self._max_requests}). "
                f"{label} '{bucket_key}' has made {self._agent_counts[bucket_key]} requests."
            )
            self._audit_log(url, bucket_key, reason)
            return False, reason

        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            reason = "Invalid URL: no hostname"
            self._audit_log(url, bucket_key, reason)
            return False, reason

        # Denylist check (always takes precedence)
        for pattern in self._denylist:
            if fnmatch(hostname.lower(), pattern.lower()):
                reason = f"Blocked by denylist: {hostname} matches pattern '{pattern}'"
                self._audit_log(url, bucket_key, reason)
                return False, reason

        # Allowlist check (only when allowlist is configured)
        if self._allowlist:
            matched = any(fnmatch(hostname.lower(), p.lower()) for p in self._allowlist)
            if not matched:
                reason = f"Blocked by allowlist: {hostname} not in allowed patterns"
                self._audit_log(url, bucket_key, reason)
                return False, reason

        # SSRF protection
        ssrf_reason = self._check_ssrf(url)
        if ssrf_reason:
            self._audit_log(url, bucket_key, ssrf_reason)
            return False, ssrf_reason

        # Record successful request
        self._agent_counts[bucket_key] += 1
        return True, ""

    @staticmethod
    def _check_ssrf(url: str) -> str | None:
        """Check if a URL targets an internal/private IP. Returns error message or None."""
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return "Invalid URL: no hostname"

            if hostname.lower() in _BLOCKED_HOSTNAMES:
                return f"Blocked: {hostname} is a localhost alias"

            try:
                addr_infos = socket.getaddrinfo(hostname, parsed.port or 80)
            except socket.gaierror:
                return None

            for family, _, _, _, sockaddr in addr_infos:
                ip = ipaddress.ip_address(sockaddr[0])
                for blocked in _BLOCKED_IP_RANGES:
                    if ip in blocked:
                        return f"Blocked: {hostname} resolves to private/internal IP {ip}"
            return None
        except Exception:
            return None

    def _audit_log(self, url: str, agent_id: str, reason: str):
        """Append blocked request to JSONL audit log (non-blocking when event loop is running)."""
        entry = {
            "timestamp": time.time(),
            "url": url,
            "agent_id": agent_id,
            "reason": reason,
        }
        line = json.dumps(entry) + "\n"

        def _write():
            try:
                with open(self._audit_path, "a") as f:
                    f.write(line)
            except OSError as e:
                logger.error(f"Failed to write URL audit log: {e}")

        try:
            loop = asyncio.get_running_loop()
            loop.run_in_executor(None, _write)
        except RuntimeError:
            # No running event loop (e.g., during tests) — write synchronously
            _write()
        logger.warning(f"URL blocked: {url} (agent={agent_id}) — {reason}")

    def reset_agent_counts(self, agent_id: str | None = None):
        """Reset per-agent request counters."""
        if agent_id:
            self._agent_counts.pop(agent_id, None)
        else:
            self._agent_counts.clear()


# Backward-compatible function for existing imports
def _is_ssrf_target(url: str) -> str | None:
    """Check if a URL targets an internal/private IP. Returns error message or None.

    Backward-compatible wrapper around UrlPolicy._check_ssrf.
    """
    return UrlPolicy._check_ssrf(url)

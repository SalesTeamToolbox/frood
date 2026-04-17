"""Per-domain HTTP cooldown (circuit breaker).

When an external domain returns 429 Too Many Requests, record it here.
Subsequent fetches to that domain short-circuit for a cooldown window
instead of re-hitting the server and burning an LLM iteration on a
guaranteed failure.

Process-local state: a shared dict keyed by host. One dict across all
tools (web_fetch, http_request) so a 429 on /contact blocks /about too.
"""
from __future__ import annotations

import logging
import time
from urllib.parse import urlparse

logger = logging.getLogger("frood.tools.domain_cooldown")

_DEFAULT_COOLDOWN_SEC = 600.0

_cooldown_until: dict[str, float] = {}


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except Exception:
        return ""


def is_cooling(url: str) -> tuple[bool, float]:
    """Return (True, seconds_remaining) if the URL's host is in cooldown."""
    host = _host(url)
    if not host:
        return False, 0.0
    until = _cooldown_until.get(host, 0.0)
    remaining = until - time.monotonic()
    if remaining > 0:
        return True, remaining
    if host in _cooldown_until:
        _cooldown_until.pop(host, None)
    return False, 0.0


def record_429(url: str, cooldown_sec: float | None = None) -> None:
    """Mark the URL's host as rate-limited for `cooldown_sec` seconds."""
    host = _host(url)
    if not host:
        return
    duration = cooldown_sec if cooldown_sec is not None else _DEFAULT_COOLDOWN_SEC
    _cooldown_until[host] = time.monotonic() + duration
    logger.info("Domain cooldown: %s blocked for %.0fs (429)", host, duration)


def cooldown_error(url: str, remaining: float) -> str:
    """Return a short message the LLM can see so it moves on."""
    host = _host(url)
    return (
        f"Skipped: {host} is in 429 cooldown ({remaining:.0f}s remaining). "
        "Move on to the next company — do not retry this domain."
    )

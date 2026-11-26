"""Read-only Claude Code pace reader.

The orchestrator's JS pace model (``orchestrator/bin/cc-pace.mjs status --json``) is
the single source of truth; this module only runs it and parses its last JSON line.
Frood agents are never routed by pace (owner decision D5): the result feeds a
read-only dashboard card.

``read_pace()`` never raises. Any failure returns
``{"state": "unknown", "reason": <reason>}`` where reason is one of
``node not found``, ``missing cc-pace.mjs``, ``timeout``, ``exit <N>``, ``bad json``
(an unexpected internal error reports ``exit -1``).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
import time
from collections.abc import Callable
from pathlib import Path

from core import config

logger = logging.getLogger(__name__)

CC_PACE_MJS = Path(__file__).resolve().parents[1] / "orchestrator" / "bin" / "cc-pace.mjs"

CACHE_TTL_S = 60.0

_cache: tuple[float, dict] | None = None
_logged_reasons: set[str] = set()


def _reset_cache() -> None:
    """Clear the cached result and the logged-reason set (tests)."""
    global _cache
    _cache = None
    _logged_reasons.clear()


def _unknown(reason: str) -> dict:
    if reason not in _logged_reasons:
        _logged_reasons.add(reason)
        logger.info("cc pace unavailable: %s", reason)
    return {"state": "unknown", "reason": reason}


def _parse(stdout: bytes) -> dict | None:
    lines = [ln for ln in stdout.decode("utf-8", errors="replace").splitlines() if ln.strip()]
    if not lines:
        return None
    try:
        data = json.loads(lines[-1])
    except ValueError:
        return None
    if not isinstance(data, dict) or not isinstance(data.get("state"), str):
        return None
    return data


async def _run(settings, timeout_s: float) -> dict:
    mjs = CC_PACE_MJS
    if not Path(mjs).is_file():
        return _unknown("missing cc-pace.mjs")

    node = settings.cc_pace_node or "node"
    if shutil.which(node) is None:
        return _unknown("node not found")

    env = dict(os.environ)
    if settings.cc_pace_orch_home:
        env["ORCH_HOME"] = settings.cc_pace_orch_home

    try:
        proc = await asyncio.create_subprocess_exec(
            node,
            str(mjs),
            "status",
            "--json",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
    except OSError:  # FileNotFoundError, PermissionError, ...
        return _unknown("node not found")

    try:
        stdout, _stderr = await asyncio.wait_for(proc.communicate(), timeout_s)
    except TimeoutError:
        try:
            proc.kill()
        except ProcessLookupError:
            pass
        await proc.wait()
        return _unknown("timeout")

    if proc.returncode != 0:
        return _unknown(f"exit {proc.returncode}")

    data = _parse(stdout)
    if data is None:
        return _unknown("bad json")
    return data


async def read_pace(*, timeout_s: float = 10.0, now: Callable[[], float] = time.monotonic) -> dict:
    """Return the current Claude Code pace as a dict. Never raises."""
    global _cache
    settings = config.settings  # read at call time; reload_from_env mutates in place
    if not settings.cc_pace_enabled:
        return {"state": "off"}

    t = now()
    if _cache is not None and t - _cache[0] < CACHE_TTL_S:
        return _cache[1]

    try:
        result = await _run(settings, timeout_s)
    except Exception:  # never raise; keep the reason set closed
        result = _unknown("exit -1")
    _cache = (t, result)
    return result

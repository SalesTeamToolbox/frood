"""Mutable runtime configuration for the performance-based rewards system.

Backed by .frood/rewards_config.json with mtime-based lazy loading and
atomic writes via os.replace(). This handles the runtime on/off toggle and
threshold overrides without a server restart.

Settings.rewards_enabled (frozen) is the startup gate — if false at startup
the RewardSystem is never instantiated and this file is never read.
RewardsConfig handles the live runtime state once the system is running.

Pattern source: agents/agent_routing_store.py
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

logger = logging.getLogger("frood.rewards_config")

_DEFAULT_PATH = ".frood/rewards_config.json"


@dataclass
class RewardsConfig:
    """Mutable runtime config for the rewards system.

    Class-level cache means all callers share one in-memory copy and
    one disk read per mtime change — same pattern as AgentRoutingStore.
    """

    enabled: bool = True
    silver_threshold: float = 0.65
    gold_threshold: float = 0.85

    _path: ClassVar[Path] = Path(_DEFAULT_PATH)
    _cache: ClassVar[dict | None] = None
    _cache_mtime: ClassVar[float] = 0.0

    @classmethod
    def set_path(cls, path: str) -> None:
        """Override backing file path (used in tests)."""
        cls._path = Path(path)
        cls._cache = None
        cls._cache_mtime = 0.0

    @classmethod
    def load(cls) -> RewardsConfig:
        """Lazy mtime-cached load. Re-reads file only when mtime changes.

        Returns defaults if the file does not exist or is invalid JSON.
        Never raises.
        """
        if not cls._path.exists():
            return cls()
        try:
            mtime = cls._path.stat().st_mtime
            if mtime != cls._cache_mtime or cls._cache is None:
                data = json.loads(cls._path.read_text(encoding="utf-8"))
                cls._cache = data
                cls._cache_mtime = mtime
            return cls(**cls._cache)
        except Exception as exc:
            logger.debug("RewardsConfig load failed (using defaults): %s", exc)
            return cls()

    def save(self) -> None:
        """Atomic write via os.replace(). Invalidates class-level cache."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "enabled": self.enabled,
            "silver_threshold": self.silver_threshold,
            "gold_threshold": self.gold_threshold,
        }
        tmp = self._path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(self._path))
        # Invalidate class-level cache so next load() picks up new data
        type(self)._cache = data
        type(self)._cache_mtime = self._path.stat().st_mtime
        logger.debug("RewardsConfig saved to %s", self._path)

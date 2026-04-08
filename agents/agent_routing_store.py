"""Per-agent routing config storage with mtime-cached JSON persistence.

Stores model routing overrides per agent profile (e.g. "coder", "researcher")
in ``data/agent_routing.json``.  Overrides inherit from ``_default`` and
ultimately from ``FALLBACK_ROUTING`` in model_router.py.

Resolution order for ``get_effective()``:
  1. Profile-specific overrides  (e.g. ``coder.primary``)
  2. ``_default`` overrides      (global runtime defaults)
  3. ``None``                    (caller falls through to FALLBACK_ROUTING)

File is read lazily with mtime caching (same pattern as
``ModelRouter._check_dynamic_routing``).  Writes use atomic replace
(write to ``.tmp``, then ``os.replace``).
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path

from core.task_queue import TaskType

logger = logging.getLogger("frood.agent_routing_store")

_VALID_OVERRIDE_KEYS = {"primary", "critic", "fallback"}


class AgentRoutingStore:
    """Persists per-profile routing overrides to a JSON file on disk."""

    DEFAULT_PATH = "data/agent_routing.json"

    def __init__(self, path: str = ""):
        self._path = Path(path or self.DEFAULT_PATH)
        self._cache: dict | None = None
        self._cache_mtime: float = 0.0

    # -- Private helpers -------------------------------------------------------

    def _load(self) -> dict:
        """Lazy mtime-cached load.  Re-reads file only when mtime changes.

        Pattern reused from ``ModelRouter._check_dynamic_routing()``.
        """
        if not self._path.exists():
            self._cache = {}
            return self._cache

        try:
            mtime = self._path.stat().st_mtime
            if mtime != self._cache_mtime or self._cache is None:
                self._cache = json.loads(self._path.read_text(encoding="utf-8"))
                self._cache_mtime = mtime
        except Exception as e:
            logger.debug("Failed to read agent routing file: %s", e)
            if self._cache is None:
                self._cache = {}

        return self._cache

    def _save(self, data: dict) -> None:
        """Atomic write: write to .tmp file, then ``os.replace()`` to target.

        Creates parent directories if needed.
        """
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self._path.with_suffix(".tmp")
        tmp_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp_path), str(self._path))
        # Invalidate cache so next _load picks up the new data
        self._cache = data
        self._cache_mtime = self._path.stat().st_mtime

    # -- Public API ------------------------------------------------------------

    def get_overrides(self, profile_name: str) -> dict | None:
        """Return raw overrides for a profile (primary/critic/fallback fields).

        Returns ``None`` if profile has no overrides.
        """
        data = self._load()
        entry = data.get(profile_name)
        if not entry:
            return None
        return dict(entry)  # shallow copy

    def set_overrides(self, profile_name: str, overrides: dict) -> None:
        """Set overrides for a profile.  Only stores non-null fields.

        Validates that dict keys are a subset of ``{primary, critic, fallback}``.
        """
        invalid = set(overrides.keys()) - _VALID_OVERRIDE_KEYS
        if invalid:
            raise ValueError(f"Invalid override keys: {invalid}. Allowed: {_VALID_OVERRIDE_KEYS}")

        # Strip None values -- None means "inherit", so don't store
        cleaned = {k: v for k, v in overrides.items() if v is not None}
        if not cleaned:
            return  # Nothing to store

        data = self._load()
        data[profile_name] = cleaned
        self._save(data)

    def delete_overrides(self, profile_name: str) -> bool:
        """Remove a profile's overrides.  Returns ``True`` if profile existed."""
        data = self._load()
        if profile_name not in data:
            return False
        del data[profile_name]
        self._save(data)
        return True

    def list_all(self) -> dict:
        """Return all stored overrides (the full JSON dict)."""
        return dict(self._load())  # shallow copy

    def get_effective(self, profile_name: str, task_type: TaskType) -> dict:
        """Merge resolution: profile fields -> _default fields ONLY.

        Does NOT merge with FALLBACK_ROUTING -- that happens in
        ``get_routing()``.

        After merge, if critic is ``None`` but primary is set, sets
        critic = primary (self-critique pattern).

        Returns dict with keys: primary, critic, fallback (any may be None
        if not configured).
        """
        data = self._load()
        profile_ov = data.get(profile_name, {}) if profile_name != "_default" else {}
        default_ov = data.get("_default", {})

        effective = {
            "primary": None,
            "critic": None,
            "fallback": None,
        }

        # Merge: profile overrides _default for each field
        for field in ("primary", "critic", "fallback"):
            val = profile_ov.get(field)
            if val is not None:
                effective[field] = val
            else:
                effective[field] = default_ov.get(field)

        # Critic auto-pairs with primary when unset
        if effective["critic"] is None and effective["primary"] is not None:
            effective["critic"] = effective["primary"]

        return effective

    def has_config(self, profile_name: str) -> bool:
        """Return ``True`` if the profile OR ``_default`` has ANY explicit overrides.

        Used by ``get_routing()`` to decide whether to use the profile path
        or fall through to the dynamic/L1/FALLBACK chain.
        """
        data = self._load()
        if data.get(profile_name):
            return True
        if data.get("_default"):
            return True
        return False

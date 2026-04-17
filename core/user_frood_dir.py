"""User-level Frood directory bootstrap + cli.yaml manifest parser/writer.

Every Frood process reads `~/.frood/cli.yaml` to learn which CLIs are enabled,
which project paths to scan for OpenCode, and whether the Claude Code warehouse
/ Frood built-ins should be included in the `frood_skill` inventory.

This module is deliberately:
  * Synchronous (pathlib) — bootstrap runs before the async tool loop is alive;
    matches the precedent set by core/key_store.py and core/portability.py.
  * Stdlib-only (with optional PyYAML) — avoids circular-dep risk with core.config,
    core.key_store, and anything else that might later want to consult the manifest.
  * Graceful-fail by design — missing file, malformed file, permission error, or
    missing PyYAML must never crash; callers always receive a usable dict.

Public contract:
    DEFAULT_MANIFEST: dict
    user_frood_dir(create: bool = False) -> Path
    load_manifest() -> dict
    save_manifest(manifest: dict) -> None
"""

from __future__ import annotations

import copy
import json
import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger("frood.user_frood_dir")

# Optional YAML backend. JSON is the fallback when PyYAML isn't installed.
try:  # pragma: no cover - import guard
    import yaml as _yaml  # type: ignore[import-untyped]

    _HAS_YAML = True
except ImportError:  # pragma: no cover - exercised when PyYAML is absent
    _yaml = None
    _HAS_YAML = False


# ---------------------------------------------------------------------------
# Default manifest — locked shape from 01-CONTEXT.md (decision D-01..D-03).
# ---------------------------------------------------------------------------
DEFAULT_MANIFEST: dict[str, Any] = {
    "clis": {
        "claude-code": {"enabled": True},
        "opencode": {"enabled": True, "projects": "auto"},
    },
    "warehouse": {
        "include_claude_warehouse": True,
        "include_frood_builtins": True,
    },
}


_MANIFEST_FILENAME = "cli.yaml"


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------
def user_frood_dir(create: bool = False) -> Path:
    """Return the user-level Frood config directory (`~/.frood/`).

    Args:
        create: If True, ensure the directory exists (mkdir parents=True, exist_ok=True).
                Safe to call repeatedly.

    Returns:
        Absolute Path to `~/.frood/`. The directory is NOT guaranteed to exist
        unless ``create=True`` was passed.
    """
    path = Path.home() / ".frood"
    if create:
        try:
            path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            # Surface the error but don't crash the caller — graceful degradation.
            logger.warning("Could not create %s: %s", path, exc)
    return path


def load_manifest() -> dict[str, Any]:
    """Load the user manifest, filling missing keys with DEFAULT_MANIFEST.

    Behaviour:
      * Missing file → write DEFAULT_MANIFEST to disk, return a deep copy.
      * Present + parseable → deep-merge user values over a fresh copy of
        DEFAULT_MANIFEST; any keys the user omitted are backfilled.
      * Present + malformed → log a warning, return a deep copy of DEFAULT_MANIFEST,
        and leave the malformed file untouched (user may want to fix the typo).

    Returns:
        A new dict safe for callers to mutate — never the module constant.
    """
    manifest_path = user_frood_dir(create=True) / _MANIFEST_FILENAME

    if not manifest_path.exists():
        # First-run path: persist defaults so the file is discoverable/editable,
        # then hand back a fresh copy so callers can mutate freely.
        save_manifest(DEFAULT_MANIFEST)
        return copy.deepcopy(DEFAULT_MANIFEST)

    try:
        raw = manifest_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s: %s", manifest_path, exc)
        return copy.deepcopy(DEFAULT_MANIFEST)

    user_values = _parse(raw, manifest_path)
    if user_values is None:
        # Parse failed — _parse already logged; fall back to defaults.
        return copy.deepcopy(DEFAULT_MANIFEST)

    merged = _deep_merge(copy.deepcopy(DEFAULT_MANIFEST), user_values)
    return merged


def save_manifest(manifest: dict[str, Any]) -> None:
    """Serialize ``manifest`` to ``~/.frood/cli.yaml``.

    Uses PyYAML if available (human-editable output), otherwise falls back to
    JSON. Both formats are valid YAML, so ``load_manifest()`` can parse either.

    The file is written with UTF-8 encoding and a trailing newline. The parent
    directory is created automatically.
    """
    manifest_path = user_frood_dir(create=True) / _MANIFEST_FILENAME

    if _HAS_YAML:
        logger.debug("Serializing manifest via PyYAML to %s", manifest_path)
        try:
            payload = _yaml.safe_dump(  # type: ignore[union-attr]
                manifest, sort_keys=False, default_flow_style=False
            )
        except Exception as exc:  # pragma: no cover - defensive
            logger.warning("PyYAML dump failed (%s); falling back to JSON", exc)
            payload = json.dumps(manifest, indent=2) + "\n"
    else:
        logger.debug("Serializing manifest via json (PyYAML unavailable) to %s", manifest_path)
        payload = json.dumps(manifest, indent=2) + "\n"

    try:
        manifest_path.write_text(payload, encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not write manifest to %s: %s", manifest_path, exc)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------
def _parse(raw: str, path: Path) -> dict[str, Any] | None:
    """Parse ``raw`` as YAML (preferred) then JSON. Return None on failure.

    Both serializers produced by ``save_manifest`` are valid YAML, so we try
    YAML first; when PyYAML is missing we try JSON. In either case a parse
    failure logs a warning and returns None so the caller can fall back to
    defaults.
    """
    # Try PyYAML first when available — it handles both YAML and JSON input.
    if _HAS_YAML:
        try:
            parsed = _yaml.safe_load(raw)  # type: ignore[union-attr]
        except Exception as exc:
            logger.warning("Malformed cli.yaml at %s: %s", path, exc)
            return None
        if parsed is None:
            # Empty file — treat as empty dict so defaults win.
            return {}
        if not isinstance(parsed, dict):
            logger.warning(
                "cli.yaml at %s must be a mapping; got %s — ignoring",
                path,
                type(parsed).__name__,
            )
            return None
        return parsed

    # PyYAML absent — JSON fallback. Note: valid YAML that isn't JSON will fail
    # here; users without PyYAML should write JSON (or install PyYAML).
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        logger.warning("Malformed cli.yaml at %s (JSON parser): %s", path, exc)
        return None
    if not isinstance(parsed, dict):
        logger.warning(
            "cli.yaml at %s must be a mapping; got %s — ignoring",
            path,
            type(parsed).__name__,
        )
        return None
    return parsed


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into ``base``. ``override`` values win.

    Nested dicts are merged key-by-key; every other type (list, str, bool, None)
    is replaced wholesale. ``base`` is mutated and returned for convenience.
    """
    for key, override_val in override.items():
        base_val = base.get(key)
        if isinstance(base_val, dict) and isinstance(override_val, dict):
            _deep_merge(base_val, override_val)
        else:
            base[key] = override_val
    return base

"""
Admin-configured API key storage.

Keys set via the dashboard admin UI are persisted in .agent42/settings.json
and injected into os.environ so they override .env values at runtime.
Provider clients are rebuilt automatically when keys change.
"""

import json
import logging
import os
import stat
import threading
from pathlib import Path

logger = logging.getLogger("agent42.key_store")

# API key env var names that can be set via the admin UI
ADMIN_CONFIGURABLE_KEYS = frozenset(
    {
        "OPENROUTER_API_KEY",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "DEEPSEEK_API_KEY",
        "GEMINI_API_KEY",
        "REPLICATE_API_TOKEN",
        "LUMA_API_KEY",
        "BRAVE_API_KEY",
        "GITHUB_TOKEN",
    }
)

_DEFAULT_PATH = Path(".agent42") / "settings.json"


class KeyStore:
    """Read/write admin-configured API keys with env-var injection."""

    def __init__(self, path: Path | None = None):
        self._path = path or _DEFAULT_PATH
        self._keys: dict[str, str] = {}
        self._env_baseline: dict[str, str] = {}  # original .env values
        self._lock = threading.Lock()
        self._load()

    # -- persistence -----------------------------------------------------------

    def _load(self):
        """Load keys from JSON file."""
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text())
            self._keys = {
                k: v
                for k, v in data.get("api_keys", {}).items()
                if k in ADMIN_CONFIGURABLE_KEYS and isinstance(v, str) and v
            }
        except (json.JSONDecodeError, OSError) as e:
            logger.error("Failed to load key store: %s", e)

    def _persist(self):
        """Write keys to JSON file with restrictive permissions."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps({"api_keys": self._keys}, indent=2))
        try:
            self._path.chmod(stat.S_IRUSR | stat.S_IWUSR)
        except OSError:
            pass  # chmod may fail on some filesystems

    # -- public API ------------------------------------------------------------

    def inject_into_environ(self):
        """Inject all stored keys into os.environ (called at startup).

        Snapshots the original .env-loaded values first so they can be
        restored if an admin-set key is later cleared.
        """
        # Snapshot all original env values before overwriting
        for key in ADMIN_CONFIGURABLE_KEYS:
            original = os.environ.get(key, "")
            if original:
                self._env_baseline[key] = original

        for key, value in self._keys.items():
            os.environ[key] = value
            logger.info("Loaded admin-configured %s", key)

    def set_key(self, env_var: str, value: str):
        """Set a key, persist to disk, and inject into os.environ."""
        if env_var not in ADMIN_CONFIGURABLE_KEYS:
            raise ValueError(f"{env_var} is not an admin-configurable key")
        with self._lock:
            # Snapshot original .env value before first override
            if env_var not in self._keys and env_var not in self._env_baseline:
                original = os.environ.get(env_var, "")
                if original:
                    self._env_baseline[env_var] = original
            self._keys[env_var] = value
            os.environ[env_var] = value
            self._persist()
        logger.info("Admin set %s via dashboard", env_var)

    def delete_key(self, env_var: str):
        """Remove an admin-set key and restore the original .env value."""
        with self._lock:
            if env_var in self._keys:
                del self._keys[env_var]
                # Restore original .env value if one existed, otherwise remove
                baseline = self._env_baseline.get(env_var, "")
                if baseline:
                    os.environ[env_var] = baseline
                else:
                    os.environ.pop(env_var, None)
                self._persist()
                logger.info("Admin removed %s override", env_var)

    def get_masked_keys(self) -> dict[str, dict]:
        """Return all configurable keys with masked values and source info."""
        result = {}
        for key in sorted(ADMIN_CONFIGURABLE_KEYS):
            admin_value = self._keys.get(key, "")
            # Check baseline (.env) separately since os.getenv would return
            # the admin-injected value, not the original .env one
            env_value = self._env_baseline.get(key, "")
            if not env_value and key not in self._keys:
                # No admin override — check live environ for .env values
                env_value = os.getenv(key, "")

            if admin_value:
                masked = (
                    admin_value[:4] + "..." + admin_value[-4:] if len(admin_value) > 8 else "****"
                )
                result[key] = {
                    "configured": True,
                    "source": "admin",
                    "masked_value": masked,
                }
            elif env_value:
                masked = env_value[:4] + "..." + env_value[-4:] if len(env_value) > 8 else "****"
                result[key] = {
                    "configured": True,
                    "source": "env",
                    "masked_value": masked,
                }
            else:
                result[key] = {
                    "configured": False,
                    "source": "none",
                    "masked_value": "",
                }
        return result

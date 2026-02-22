"""
Model catalog — syncs available models from OpenRouter.

Periodically fetches the OpenRouter ``/models`` endpoint, filters for free
models, and auto-registers newly discovered ones in the ProviderRegistry.
Results are cached to ``data/model_catalog.json`` for offline fallback.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path

import httpx

from providers.registry import ModelSpec, ModelTier, ProviderRegistry, ProviderType

logger = logging.getLogger("agent42.model_catalog")

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"

# Capabilities we care about when categorizing models
_CODING_KEYWORDS = re.compile(r"code|coder|dev|stral", re.IGNORECASE)
_REASONING_KEYWORDS = re.compile(r"reason|r1|think|o1|o3|o4", re.IGNORECASE)


def _slug_from_model_id(model_id: str) -> str:
    """Convert 'meta-llama/llama-4-maverick:free' → 'llama-4-maverick'."""
    # Strip provider prefix and :free suffix
    name = model_id.rsplit("/", 1)[-1]
    name = name.split(":")[0]
    # Sanitize for use as a registry key
    name = re.sub(r"[^a-z0-9-]", "-", name.lower())
    name = re.sub(r"-+", "-", name).strip("-")
    return name


class CatalogEntry:
    """A discovered model from the OpenRouter catalog."""

    __slots__ = (
        "architecture",
        "completion_price",
        "context_length",
        "created_at",
        "is_free",
        "modality",
        "model_id",
        "name",
        "prompt_price",
    )

    def __init__(self, data: dict):
        self.model_id: str = data.get("id", "")
        self.name: str = data.get("name", "")
        pricing = data.get("pricing", {}) or {}
        self.prompt_price: str = str(pricing.get("prompt", "0"))
        self.completion_price: str = str(pricing.get("completion", "0"))
        self.is_free = self._check_free()
        self.context_length: int = data.get("context_length", 0) or 0
        arch = data.get("architecture", {}) or {}
        self.architecture: str = arch.get("modality", "")
        self.modality: str = arch.get("input_modality", "text")
        self.created_at: int = data.get("created", 0) or 0

    def _check_free(self) -> bool:
        """A model is free if both prompt and completion prices are '0' or 0."""
        try:
            return float(self.prompt_price) == 0 and float(self.completion_price) == 0
        except (ValueError, TypeError):
            return False

    def to_dict(self) -> dict:
        return {
            "id": self.model_id,
            "name": self.name,
            "context_length": self.context_length,
            "pricing": {
                "prompt": self.prompt_price,
                "completion": self.completion_price,
            },
        }

    def inferred_category(self) -> str:
        """Guess the model's primary strength from its name."""
        if _CODING_KEYWORDS.search(self.name) or _CODING_KEYWORDS.search(self.model_id):
            return "coding"
        if _REASONING_KEYWORDS.search(self.name) or _REASONING_KEYWORDS.search(self.model_id):
            return "reasoning"
        return "general"


class ModelCatalog:
    """Fetches and caches the OpenRouter model catalog."""

    def __init__(
        self,
        cache_path: Path | str = "data/model_catalog.json",
        refresh_hours: float = 24.0,
    ):
        self.cache_path = Path(cache_path)
        self.refresh_interval_seconds = refresh_hours * 3600
        self._entries: list[CatalogEntry] = []
        self._last_refresh: float = 0.0

        # Load from cache on init
        self._load_cache()

    # -- Public API -----------------------------------------------------------

    async def refresh(self, api_key: str = "") -> list[CatalogEntry]:
        """Fetch the latest model list from OpenRouter.

        Falls back to cached data if the API is unreachable.
        """
        headers = {}
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.get(OPENROUTER_MODELS_URL, headers=headers)
                resp.raise_for_status()
                data = resp.json()
        except Exception as e:
            logger.warning("Failed to fetch OpenRouter model catalog: %s", e)
            if self._entries:
                logger.info("Using cached catalog (%d models)", len(self._entries))
                return self._entries
            return []

        models_raw = data.get("data", [])
        self._entries = [CatalogEntry(m) for m in models_raw]
        self._last_refresh = time.time()
        self._save_cache()

        logger.info(
            "Model catalog refreshed: %d total, %d free",
            len(self._entries),
            len(self.free_models()),
        )
        return self._entries

    def needs_refresh(self) -> bool:
        """Check whether the catalog should be refreshed."""
        if not self._entries:
            return True
        return (time.time() - self._last_refresh) > self.refresh_interval_seconds

    def free_models(self) -> list[CatalogEntry]:
        """Return only free models from the catalog."""
        return [e for e in self._entries if e.is_free]

    def free_models_by_category(self) -> dict[str, list[CatalogEntry]]:
        """Group free models by inferred category."""
        result: dict[str, list[CatalogEntry]] = {}
        for entry in self.free_models():
            cat = entry.inferred_category()
            result.setdefault(cat, []).append(entry)
        return result

    def register_new_models(self, registry: ProviderRegistry) -> list[str]:
        """Auto-register free models that aren't already in the registry.

        Returns the list of newly registered model keys.
        """
        existing_ids = {spec.model_id for spec in _all_model_specs()}
        new_keys: list[str] = []

        for entry in self.free_models():
            if entry.model_id in existing_ids:
                continue

            slug = _slug_from_model_id(entry.model_id)
            key = f"or-free-{slug}"

            # Skip if key already exists (different model_id but same slug)
            try:
                registry.get_model(key)
                continue
            except ValueError:
                pass

            spec = ModelSpec(
                model_id=entry.model_id,
                provider=ProviderType.OPENROUTER,
                max_tokens=4096,
                display_name=f"{entry.name} (free, discovered)",
                tier=ModelTier.FREE,
                max_context_tokens=entry.context_length or 128000,
            )
            registry.register_model(key, spec)
            new_keys.append(key)
            logger.info("Auto-registered model: %s → %s", key, entry.model_id)

        if new_keys:
            logger.info("Registered %d new free model(s) from catalog", len(new_keys))
        return new_keys

    # -- Cache ----------------------------------------------------------------

    def _save_cache(self):
        """Persist the catalog to disk."""
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_refresh": self._last_refresh,
            "models": [e.to_dict() for e in self._entries],
        }
        self.cache_path.write_text(json.dumps(payload, indent=2))

    def _load_cache(self):
        """Load catalog from disk cache."""
        if not self.cache_path.exists():
            return
        try:
            data = json.loads(self.cache_path.read_text())
            self._last_refresh = data.get("last_refresh", 0.0)
            self._entries = [CatalogEntry(m) for m in data.get("models", [])]
            logger.debug("Loaded %d models from catalog cache", len(self._entries))
        except Exception as e:
            logger.warning("Failed to load catalog cache: %s", e)


def _all_model_specs():
    """Helper to get all ModelSpec values from the MODELS dict."""
    from providers.registry import MODELS

    return MODELS.values()

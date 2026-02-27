"""
Model catalog — syncs available models from OpenRouter.

Periodically fetches the OpenRouter ``/models`` endpoint, filters for free
models, and auto-registers newly discovered ones in the ProviderRegistry.
Results are cached to ``data/model_catalog.json`` for offline fallback.

Health checks: pings registered free models with a minimal completion
request on startup and periodically. Models that return 404 or persistent
errors are marked unavailable so the router and fallback chain skip them.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

import httpx

from providers.registry import PROVIDERS, ModelSpec, ModelTier, ProviderRegistry, ProviderType

logger = logging.getLogger("agent42.model_catalog")

OPENROUTER_MODELS_URL = "https://openrouter.ai/api/v1/models"
OPENROUTER_AUTH_URL = "https://openrouter.ai/api/v1/auth/key"

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

    # Health check settings
    HEALTH_CHECK_INTERVAL = 6 * 3600  # 6 hours between full health checks
    HEALTH_CHECK_TIMEOUT = 15  # seconds per model ping
    HEALTH_CHECK_CONCURRENCY = 5  # max concurrent pings
    # Status values for health results
    STATUS_OK = "ok"
    STATUS_UNAVAILABLE = "unavailable"  # 404 / model removed
    STATUS_RATE_LIMITED = "rate_limited"  # 429 — model exists but throttled
    STATUS_AUTH_ERROR = "auth_error"  # 401 — key issue
    STATUS_TIMEOUT = "timeout"
    STATUS_ERROR = "error"  # other errors

    def __init__(
        self,
        cache_path: Path | str = "data/model_catalog.json",
        refresh_hours: float = 24.0,
        balance_check_hours: float = 1.0,
    ):
        self.cache_path = Path(cache_path)
        self.refresh_interval_seconds = refresh_hours * 3600
        self.balance_check_interval_seconds = balance_check_hours * 3600.0
        self._entries: list[CatalogEntry] = []
        self._last_refresh: float = 0.0
        self._account_status: dict | None = None
        self._account_last_checked: float = 0.0

        # Health check state: {model_registry_key: {status, last_checked, error, latency_ms}}
        self._health_status: dict[str, dict] = {}
        self._health_path = self.cache_path.parent / "model_health.json"
        self._last_health_check: float = 0.0

        # Load from cache on init
        self._load_cache()
        self._load_health_cache()

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

    # -- Account & validation -------------------------------------------------

    async def check_account(self, api_key: str = "") -> dict:
        """Check OpenRouter account status (free tier, remaining balance).

        Caches the result for ``balance_check_interval_seconds``.  On any
        failure returns a safe default that prevents paid model selection.
        """
        now = time.time()
        if (
            self._account_status is not None
            and (now - self._account_last_checked) < self.balance_check_interval_seconds
        ):
            return {**self._account_status, "cached": True}

        if not api_key:
            result = {
                "is_free_tier": True,
                "limit_remaining": None,
                "rate_limit": {},
                "cached": False,
                "error": "No API key provided",
            }
            self._account_status = result
            self._account_last_checked = now
            return result

        try:
            headers = {"Authorization": f"Bearer {api_key}"}
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.get(OPENROUTER_AUTH_URL, headers=headers)
                resp.raise_for_status()
                data = resp.json().get("data", {})

            result = {
                "is_free_tier": data.get("is_free_tier", True),
                "limit_remaining": data.get("limit_remaining"),
                "rate_limit": data.get("rate_limit", {}),
                "cached": False,
                "error": None,
            }
        except Exception as e:
            logger.warning("Failed to check OpenRouter account: %s", e)
            result = {
                "is_free_tier": True,
                "limit_remaining": None,
                "rate_limit": {},
                "cached": False,
                "error": str(e),
            }

        self._account_status = result
        self._account_last_checked = now
        return result

    @property
    def openrouter_account_status(self) -> dict | None:
        """Return the last cached account status, or None if never checked."""
        return self._account_status

    def validate_primary_models(self, registry) -> dict[str, str | None]:
        """Check whether FREE_ROUTING model IDs exist in the live catalog.

        Returns ``{model_key: replacement_key_or_none}`` for models that are
        missing from the catalog.  Informational only — does NOT modify the
        registry.
        """
        from agents.model_router import FREE_ROUTING

        catalog_ids = {e.model_id for e in self._entries}
        if not catalog_ids:
            return {}

        results: dict[str, str | None] = {}
        for _task_type, routing in FREE_ROUTING.items():
            model_key = routing.get("primary", "")
            if not model_key:
                continue
            try:
                spec = registry.get_model(model_key)
            except ValueError:
                continue
            if spec.provider.value != "openrouter":
                continue
            if spec.model_id in catalog_ids:
                continue
            # Model is missing from catalog — try to find replacement
            replacement = self._find_best_replacement(spec, catalog_ids)
            results[model_key] = replacement
            logger.warning(
                "Model %s (%s) not found in catalog%s",
                model_key,
                spec.model_id,
                f" — suggested replacement: {replacement}" if replacement else "",
            )

        return results

    def _find_best_replacement(self, missing_spec, catalog_ids: set) -> str | None:
        """Find the best catalog-available replacement for a missing model."""
        # Infer category from model name
        category = "general"
        if _CODING_KEYWORDS.search(missing_spec.model_id):
            category = "coding"
        elif _REASONING_KEYWORDS.search(missing_spec.model_id):
            category = "reasoning"

        candidates = [
            e
            for e in self._entries
            if e.is_free and e.inferred_category() == category and e.model_id in catalog_ids
        ]
        if not candidates:
            return None

        # Prefer models with larger context windows
        candidates.sort(key=lambda e: e.context_length, reverse=True)
        slug = _slug_from_model_id(candidates[0].model_id)
        return f"or-free-{slug}"

    def register_paid_models(self, registry, max_prompt_price_per_m: float = 5.0) -> list[str]:
        """Register affordable paid OR models that aren't already known.

        ``max_prompt_price_per_m`` is the per-million-token price ceiling
        (e.g. 5.0 = $5/M tokens).  Returns the list of newly registered
        model keys.
        """
        from providers.registry import MODELS

        existing_ids = {spec.model_id for spec in MODELS.values()}
        new_keys: list[str] = []

        for entry in self._entries:
            if entry.is_free:
                continue
            if entry.model_id in existing_ids:
                continue
            try:
                prompt_per_m = float(entry.prompt_price) * 1_000_000
            except (ValueError, TypeError):
                continue
            if prompt_per_m > max_prompt_price_per_m:
                continue

            slug = _slug_from_model_id(entry.model_id)
            key = f"or-paid-{slug}"

            try:
                registry.get_model(key)
                continue  # Already registered (slug collision)
            except ValueError:
                pass

            tier = ModelTier.CHEAP if prompt_per_m < 1.0 else ModelTier.PREMIUM
            spec = ModelSpec(
                model_id=entry.model_id,
                provider=ProviderType.OPENROUTER,
                max_tokens=4096,
                display_name=f"{entry.name} (paid, discovered)",
                tier=tier,
                max_context_tokens=entry.context_length or 128000,
            )
            registry.register_model(key, spec)
            new_keys.append(key)
            logger.info(
                "Auto-registered paid model: %s → %s (tier=%s, $%.2f/M)",
                key,
                entry.model_id,
                tier.value,
                prompt_per_m,
            )

        if new_keys:
            logger.info("Registered %d new paid model(s) from catalog", len(new_keys))
        return new_keys

    def get_model_prices(self) -> dict[str, tuple[float, float]]:
        """Return ``{model_id: (prompt_per_token, completion_per_token)}``."""
        prices: dict[str, tuple[float, float]] = {}
        for entry in self._entries:
            try:
                prices[entry.model_id] = (
                    float(entry.prompt_price),
                    float(entry.completion_price),
                )
            except (ValueError, TypeError):
                continue
        return prices

    # -- Health checks --------------------------------------------------------

    def needs_health_check(self) -> bool:
        """Whether a health check should be run."""
        if not self._health_status:
            return True
        return (time.time() - self._last_health_check) > self.HEALTH_CHECK_INTERVAL

    async def health_check(self, api_key: str = "") -> dict[str, dict]:
        """Ping registered free models with a minimal completion request.

        Sends ``{"messages": [{"role": "user", "content": "hi"}], "max_tokens": 1}``
        to each model's provider API. Records status, latency, and errors.

        Models are checked concurrently (up to ``HEALTH_CHECK_CONCURRENCY`` at a
        time) to keep the total wall-clock time manageable.

        Returns ``{model_key: {status, latency_ms, last_checked, error}}``.
        """
        from providers.registry import MODELS

        models_to_check: list[tuple[str, str, str, str]] = []  # (key, model_id, base_url, key_env)

        # Collect all registered free OR models
        for key, spec in MODELS.items():
            if spec.tier != ModelTier.FREE:
                continue
            provider_spec = PROVIDERS.get(spec.provider)
            if not provider_spec:
                continue
            env_key = os.getenv(provider_spec.api_key_env, "")
            if not env_key:
                continue
            models_to_check.append((key, spec.model_id, provider_spec.base_url, env_key))

        # Also check Gemini if configured (it's our primary, tier=CHEAP)
        gemini_key = os.getenv("GEMINI_API_KEY", "")
        if gemini_key:
            gemini_spec = PROVIDERS.get(ProviderType.GEMINI)
            if gemini_spec:
                for key, spec in MODELS.items():
                    if spec.provider == ProviderType.GEMINI:
                        models_to_check.append(
                            (key, spec.model_id, gemini_spec.base_url, gemini_key)
                        )

        if not models_to_check:
            logger.info("Health check: no models to check (no API keys configured)")
            return self._health_status

        logger.info("Health check: pinging %d models...", len(models_to_check))

        semaphore = asyncio.Semaphore(self.HEALTH_CHECK_CONCURRENCY)

        async def _ping_model(
            model_key: str, model_id: str, base_url: str, auth_key: str
        ) -> tuple[str, dict]:
            async with semaphore:
                return model_key, await self._ping_single_model(
                    model_id, base_url, auth_key
                )

        tasks = [
            _ping_model(key, mid, url, akey)
            for key, mid, url, akey in models_to_check
        ]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        now = time.time()
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Health check task failed: %s", result)
                continue
            model_key, status_dict = result
            status_dict["last_checked"] = now
            self._health_status[model_key] = status_dict

        self._last_health_check = now
        self._save_health_cache()

        # Log summary
        ok = sum(1 for s in self._health_status.values() if s.get("status") == self.STATUS_OK)
        unavail = sum(
            1 for s in self._health_status.values()
            if s.get("status") == self.STATUS_UNAVAILABLE
        )
        rate_limited = sum(
            1 for s in self._health_status.values()
            if s.get("status") == self.STATUS_RATE_LIMITED
        )
        logger.info(
            "Health check complete: %d ok, %d unavailable, %d rate-limited (of %d checked)",
            ok, unavail, rate_limited, len(models_to_check),
        )

        return self._health_status

    async def _ping_single_model(
        self, model_id: str, base_url: str, api_key: str
    ) -> dict:
        """Send a minimal completion request to test model availability."""
        url = f"{base_url}/chat/completions"
        headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
        payload = {
            "model": model_id,
            "messages": [{"role": "user", "content": "hi"}],
            "max_tokens": 1,
        }

        start = time.monotonic()
        try:
            async with httpx.AsyncClient(timeout=self.HEALTH_CHECK_TIMEOUT) as client:
                resp = await client.post(url, json=payload, headers=headers)
            elapsed_ms = (time.monotonic() - start) * 1000

            if resp.status_code == 200:
                return {
                    "status": self.STATUS_OK,
                    "latency_ms": round(elapsed_ms, 1),
                    "error": "",
                }
            elif resp.status_code == 404:
                return {
                    "status": self.STATUS_UNAVAILABLE,
                    "latency_ms": round(elapsed_ms, 1),
                    "error": f"404: {resp.text[:200]}",
                }
            elif resp.status_code == 429:
                return {
                    "status": self.STATUS_RATE_LIMITED,
                    "latency_ms": round(elapsed_ms, 1),
                    "error": "429: rate limited",
                }
            elif resp.status_code in (401, 403):
                return {
                    "status": self.STATUS_AUTH_ERROR,
                    "latency_ms": round(elapsed_ms, 1),
                    "error": f"{resp.status_code}: {resp.text[:200]}",
                }
            else:
                return {
                    "status": self.STATUS_ERROR,
                    "latency_ms": round(elapsed_ms, 1),
                    "error": f"{resp.status_code}: {resp.text[:200]}",
                }
        except httpx.TimeoutException:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "status": self.STATUS_TIMEOUT,
                "latency_ms": round(elapsed_ms, 1),
                "error": "Request timed out",
            }
        except Exception as e:
            elapsed_ms = (time.monotonic() - start) * 1000
            return {
                "status": self.STATUS_ERROR,
                "latency_ms": round(elapsed_ms, 1),
                "error": str(e)[:200],
            }

    def is_model_healthy(self, model_key: str) -> bool:
        """Check if a model is currently healthy (available for use).

        Models are considered healthy if:
        - They have never been checked (optimistic default)
        - Their last health check returned OK or rate_limited

        Rate-limited models are still "healthy" — they exist and work,
        just need backoff. The retry/fallback logic handles 429s at runtime.
        """
        status = self._health_status.get(model_key)
        if status is None:
            return True  # Optimistic: unchecked = assume healthy
        return status.get("status") in (
            self.STATUS_OK,
            self.STATUS_RATE_LIMITED,
        )

    def unhealthy_model_keys(self) -> set[str]:
        """Return the set of model keys known to be unhealthy (404, auth, error, timeout)."""
        return {
            key
            for key, status in self._health_status.items()
            if status.get("status") not in (self.STATUS_OK, self.STATUS_RATE_LIMITED, None)
        }

    def get_health_summary(self) -> dict:
        """Return a summary of model health for dashboard/API."""
        by_status: dict[str, int] = {}
        for status in self._health_status.values():
            s = status.get("status", "unknown")
            by_status[s] = by_status.get(s, 0) + 1

        return {
            "total_checked": len(self._health_status),
            "last_check": self._last_health_check,
            "last_check_age_hours": round(
                (time.time() - self._last_health_check) / 3600, 1
            ) if self._last_health_check else None,
            "by_status": by_status,
            "unhealthy_models": [
                {"key": k, "status": v.get("status"), "error": v.get("error", "")}
                for k, v in self._health_status.items()
                if v.get("status") not in (self.STATUS_OK, self.STATUS_RATE_LIMITED)
            ],
        }

    def _save_health_cache(self):
        """Persist health check results to disk."""
        self._health_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "last_check": self._last_health_check,
            "models": self._health_status,
        }
        self._health_path.write_text(json.dumps(payload, indent=2))

    def _load_health_cache(self):
        """Load health check results from disk cache."""
        if not self._health_path.exists():
            return
        try:
            data = json.loads(self._health_path.read_text())
            self._last_health_check = data.get("last_check", 0.0)
            self._health_status = data.get("models", {})
            logger.debug(
                "Loaded health cache: %d models, age=%.1fh",
                len(self._health_status),
                (time.time() - self._last_health_check) / 3600 if self._last_health_check else 0,
            )
        except Exception as e:
            logger.warning("Failed to load health cache: %s", e)

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

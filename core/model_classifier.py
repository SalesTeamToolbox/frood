"""
Probe-based free/paid model classification with on-disk caching.

Instead of guessing a model's tier from its name (``-free``, ``:free`` etc.),
we send a minimal chat-completion probe using the configured API key:

- HTTP 200 with non-empty content → the key could spend the model, so either
  the model is free *or* we have credit on it. For a zero-credit key this
  means the model is free-tier. We mark it "free".
- HTTP 402 or a recognised credit-error message → the key could not spend
  the model. We mark it "paid".
- HTTP 403 / 404 / model-error → out-of-catalog or unavailable; "unknown".
- Network/5xx/timeout → transient; "unknown" (previous cache entry kept).

Results are cached to ``.frood/model_classifications.json`` with a TTL so
we don't re-probe every refresh. ``mark_paid()`` lets the live routing path
write back immediately when it sees a credit error in normal traffic.

The classifier is provider-agnostic: it takes a provider name and a client
object that exposes the two methods it needs::

    async def list_all_models() -> list[str]
    async def chat_completion(model, messages, **kwargs) -> dict
    # Optional (used for pricing-metadata fast path):
    async def list_catalog_raw() -> list[dict]

``chat_completion`` must return either ``{"choices": [{"message": {...}}]}``
on success or ``{"error": "..."}`` / ``{"error": "...", "exhausted": True}``
on failure (this matches the existing ZenApiClient / NvidiaApiClient
contract).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Literal, Protocol

logger = logging.getLogger("frood.model_classifier")

Classification = Literal["free", "paid", "unknown"]

_CACHE_PATH = Path(".frood") / "model_classifications.json"
_DEFAULT_TTL_HOURS = 24.0
_PROBE_PROMPT = "hi"
_PROBE_MAX_TOKENS = 1

# Keywords whose presence in an error body imply the account ran out of credit
# (and by implication, the model itself is paid-tier). These mirror what the
# routing layer's _is_credit_error() looks for, kept in sync intentionally.
_PAID_BODY_KEYWORDS = (
    "credit",
    "quota",
    "insufficient",
    "billing",
    "payment",
    "balance",
    "not enough",
    "limit exceeded",
    "free tier exhausted",
)


class _ClientLike(Protocol):
    """Structural contract the classifier expects from a provider client."""

    async def list_all_models(self) -> list[str]: ...

    async def chat_completion(
        self, model: str, messages: list[dict], **kwargs: Any
    ) -> dict: ...


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------


def _now() -> float:
    return time.time()


def _ttl_seconds() -> float:
    raw = os.environ.get("MODEL_CLASSIFICATION_TTL_HOURS")
    if raw:
        try:
            return float(raw) * 3600.0
        except ValueError:
            pass
    return _DEFAULT_TTL_HOURS * 3600.0


def _load_cache() -> dict[str, dict[str, dict[str, Any]]]:
    if not _CACHE_PATH.exists():
        return {}
    try:
        return json.loads(_CACHE_PATH.read_text())
    except (json.JSONDecodeError, OSError) as e:
        logger.warning("Could not read classifier cache: %s", e)
        return {}


def _save_cache(cache: dict[str, dict[str, dict[str, Any]]]) -> None:
    try:
        _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _CACHE_PATH.write_text(json.dumps(cache, indent=2, sort_keys=True))
    except OSError as e:
        logger.warning("Could not write classifier cache: %s", e)


_cache: dict[str, dict[str, dict[str, Any]]] = _load_cache()
_cache_lock = asyncio.Lock()


def get_cached_classification(provider: str, model_id: str) -> Classification | None:
    """Return the cached class for (provider, model) or None if absent/expired."""
    entry = _cache.get(provider, {}).get(model_id)
    if not entry:
        return None
    probed_at = entry.get("last_probed", 0.0)
    if _now() - float(probed_at) > _ttl_seconds():
        return None
    cls = entry.get("class")
    return cls if cls in ("free", "paid", "unknown") else None


def get_cached_bucket(provider: str) -> dict[Classification, list[str]]:
    """Read the cached classification for a provider as free/paid/unknown lists."""
    bucket: dict[Classification, list[str]] = {"free": [], "paid": [], "unknown": []}
    for mid, entry in _cache.get(provider, {}).items():
        cls = entry.get("class")
        if cls in bucket:
            bucket[cls].append(mid)  # type: ignore[index]
    for k in bucket:
        bucket[k].sort()
    return bucket


async def mark(provider: str, model_id: str, cls: Classification) -> None:
    """Write a classification into the cache (used by probe and live routing)."""
    async with _cache_lock:
        _cache.setdefault(provider, {})[model_id] = {
            "class": cls,
            "last_probed": _now(),
        }
        _save_cache(_cache)


async def mark_paid(provider: str, model_id: str) -> None:
    """Shortcut for the live credit-error path."""
    await mark(provider, model_id, "paid")


async def mark_free(provider: str, model_id: str) -> None:
    await mark(provider, model_id, "free")


# ---------------------------------------------------------------------------
# Probe
# ---------------------------------------------------------------------------


def _looks_like_paid(err_text: str) -> bool:
    t = (err_text or "").lower()
    return any(kw in t for kw in _PAID_BODY_KEYWORDS)


async def _probe_one(client: _ClientLike, model_id: str) -> Classification:
    """Send one tiny probe and classify the response."""
    try:
        result = await client.chat_completion(
            model_id,
            [{"role": "user", "content": _PROBE_PROMPT}],
            max_tokens=_PROBE_MAX_TOKENS,
        )
    except Exception as e:  # noqa: BLE001
        logger.debug("probe %s threw: %s", model_id, e)
        return "unknown"

    # Success shape: OpenAI chat.completion dict with "choices"
    if "choices" in result and result.get("choices"):
        return "free"

    # Error shape: {"error": "...", "exhausted": bool?}
    err = str(result.get("error", ""))
    if not err:
        return "unknown"

    # The provider client may tag "exhausted" explicitly — treat as paid
    # (free tier is exhausted means this model is gated behind credits).
    if result.get("exhausted"):
        return "paid"

    # Heuristic on the textual body (same keywords the routing layer uses)
    if _looks_like_paid(err):
        return "paid"

    # HTTP 402 sometimes comes through as "HTTP 402: ..." in the err string
    if "402" in err and "credit" in err.lower():
        return "paid"

    # 403/404/ModelError/etc — unavailable, not paid
    return "unknown"


async def classify_models(
    provider: str,
    client: _ClientLike,
    *,
    force: bool = False,
    concurrency: int = 3,
) -> dict[str, Classification]:
    """Classify every model a provider advertises.

    Respects the cache: models with a fresh entry are skipped unless ``force``
    is true. Concurrency is capped so we don't hammer the upstream when a
    provider lists 40+ models.
    """
    models = await client.list_all_models()
    if not models:
        logger.warning("[%s] list_all_models returned empty", provider)
        return {}

    results: dict[str, Classification] = {}
    semaphore = asyncio.Semaphore(max(1, concurrency))

    async def _classify(mid: str) -> None:
        if not force:
            cached = get_cached_classification(provider, mid)
            if cached is not None:
                results[mid] = cached
                return
        async with semaphore:
            cls = await _probe_one(client, mid)
        results[mid] = cls
        await mark(provider, mid, cls)

    await asyncio.gather(*(_classify(m) for m in models), return_exceptions=False)

    free_n = sum(1 for c in results.values() if c == "free")
    paid_n = sum(1 for c in results.values() if c == "paid")
    unknown_n = sum(1 for c in results.values() if c == "unknown")
    logger.info(
        "[%s] classified %d models: free=%d paid=%d unknown=%d",
        provider,
        len(results),
        free_n,
        paid_n,
        unknown_n,
    )
    return results

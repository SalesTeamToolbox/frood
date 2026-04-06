"""
OpenCode Zen API client.

Provides access to free LLM models (Qwen3.6 Plus Free, MiniMax M2.5 Free,
Nemotron 3 Super Free, Big Pickle) via the OpenCode Zen gateway.
Uses OpenAI-compatible chat completions endpoint.

Base URL: https://opencode.ai/zen/v1
Endpoint: /chat/completions
Models: /models
"""

import asyncio
import logging
import os
import re
from typing import Any

import httpx

from core.config import settings
from core.rate_limiter import PerModelRateLimiter

logger = logging.getLogger("agent42.providers.zen")

# Default free model mappings — updated dynamically via refresh
_DEFAULT_FREE_MODELS = [
    "qwen3.6-plus-free",
    "minimax-m2.5-free",
    "nemotron-3-super-free",
    "big-pickle",
]


class ZenApiClient:
    """API client for OpenCode Zen with OpenAI-compatible interface."""

    def __init__(self):
        self._base_url = settings.zen_base_url or "https://opencode.ai/zen/v1"
        self._known_free_models: list[str] = list(_DEFAULT_FREE_MODELS)
        self._rate_limiter = PerModelRateLimiter()
        self._rate_limiting_enabled = settings.zen_rate_limit_enabled

    def _get_api_key(self) -> str:
        """Get the Zen API key from key store or environment."""
        if hasattr(settings, "_key_store"):
            keys = settings._key_store.get_masked_keys()
            if keys.get("ZEN_API_KEY", {}).get("configured"):
                return os.environ.get("ZEN_API_KEY", "")

        return os.environ.get("ZEN_API_KEY", "")

    async def chat_completion(
        self,
        model: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> dict:
        """Send a chat completion request to Zen API.

        Args:
            model:    Zen model ID (e.g. "qwen3.6-plus-free")
            messages: OpenAI-compatible message list
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            Parsed JSON response dict, or {"error": str} on failure.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No Zen API key configured — cannot make request")
            return {"error": "No ZEN_API_KEY configured"}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, **kwargs}
        url = f"{self._base_url}/chat/completions"

        max_retries = 3
        for attempt in range(max_retries + 1):
            if self._rate_limiting_enabled:
                await self._rate_limiter.wait(model)

            try:
                async with httpx.AsyncClient(timeout=120.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)

                    if resp.status_code == 429:
                        retry_after = self._parse_retry_after(resp)
                        if self._rate_limiting_enabled:
                            self._rate_limiter.record_rate_limit(model, retry_after)
                        logger.warning(
                            "Zen API rate limited (model=%s, attempt %d/%d), retry_after=%.1fs",
                            model,
                            attempt + 1,
                            max_retries,
                            retry_after or 0,
                        )
                        if attempt < max_retries:
                            await asyncio.sleep(
                                retry_after
                                or self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                            )
                            continue
                        return {"error": f"Rate limited after {max_retries + 1} attempts"}

                    error_text = resp.text[:500]
                    if resp.status_code >= 400:
                        is_exhausted = self._is_exhausted_error(error_text)
                        if is_exhausted:
                            if self._rate_limiting_enabled:
                                self._rate_limiter.mark_exhausted(model)
                            logger.warning(
                                "Zen API free tier exhausted (model=%s): %s",
                                model,
                                error_text[:200],
                            )
                            return {
                                "error": f"Free tier exhausted: {error_text[:200]}",
                                "exhausted": True,
                            }
                        is_rate_error = self._is_rate_limit_error(error_text)
                        if is_rate_error:
                            if self._rate_limiting_enabled:
                                self._rate_limiter.record_rate_limit(model)
                            logger.warning(
                                "Zen API rate error detected (model=%s, attempt %d/%d): %s",
                                model,
                                attempt + 1,
                                max_retries,
                                error_text[:200],
                            )
                            if attempt < max_retries:
                                delay = self._rate_limiter.get_stats(model).get(
                                    "current_delay", 3.0
                                )
                                await asyncio.sleep(delay)
                                continue
                        else:
                            if self._rate_limiting_enabled:
                                self._rate_limiter.record_error(model)
                        return {"error": f"HTTP {resp.status_code}: {error_text}"}

                    if self._rate_limiting_enabled:
                        self._rate_limiter.record_success(model)
                    return resp.json()

            except httpx.TimeoutException:
                if self._rate_limiting_enabled:
                    self._rate_limiter.record_error(model)
                if attempt < max_retries:
                    delay = self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                    wait = delay * (attempt + 1)
                    logger.warning(
                        "Zen API timeout (model=%s, attempt %d/%d), retrying in %.1fs",
                        model,
                        attempt + 1,
                        max_retries,
                        wait,
                    )
                    await asyncio.sleep(wait)
                    continue
                return {"error": "Request timed out after retries"}

            except httpx.RequestError as e:
                if self._rate_limiting_enabled:
                    self._rate_limiter.record_error(model)
                if attempt < max_retries:
                    delay = self._rate_limiter.get_stats(model).get("current_delay", 3.0)
                    wait = delay * (attempt + 1)
                    logger.warning(
                        "Zen API connection error (model=%s, attempt %d/%d): %s",
                        model,
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    await asyncio.sleep(wait)
                    continue
                return {"error": str(e)}

            except Exception as e:
                logger.error("Zen API unexpected error: %s", e)
                return {"error": str(e)}

        return {"error": "Max retries exceeded"}

    @staticmethod
    def _parse_retry_after(resp: httpx.Response) -> float | None:
        """Extract Retry-After header value in seconds, if present."""
        header = resp.headers.get("retry-after")
        if header:
            try:
                return float(header)
            except (ValueError, TypeError):
                pass
        return None

    @staticmethod
    def _is_rate_limit_error(text: str) -> bool:
        """Detect rate-limit-related errors in response body (temporary)."""
        patterns = [
            r"rate\s*limit",
            r"too\s*many\s*requests",
            r"request\s*rate\s*increased\s*too\s*quickly",
            r"scale\s*requests\s*more\s*smoothly",
            r"slow\s*down",
            r"throttl",
        ]
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in patterns)

    @staticmethod
    def _is_exhausted_error(text: str) -> bool:
        """Detect free tier usage exhaustion (permanent until reset)."""
        patterns = [
            r"insufficient.*credits",
            r"quota.*exceeded",
            r"free.*tier.*exhaust(ed)?",
            r"no.*free.*usage",
            r"usage.*limit.*reached",
            r"daily.*limit.*reached",
            r"monthly.*limit.*reached",
            r"exceeded.*free.*allocation",
            r"no.*quota.*remaining",
            r"credits.*exhausted",
        ]
        text_lower = text.lower()
        return any(re.search(p, text_lower) for p in patterns)

    async def list_models(self) -> list[str]:
        """Fetch available free model IDs from Zen API.

        Calls GET /v1/models and filters to free models only.
        Falls back to hardcoded defaults if the endpoint is unavailable.

        Returns:
            List of free model ID strings.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No Zen API key configured — cannot list models")
            return list(self._known_free_models)

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        url = f"{self._base_url}/models"

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(url, headers=headers)
                resp.raise_for_status()
                data = resp.json()

            free_models = []
            models = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(models, list):
                for m in models:
                    model_id = m.get("id", "") if isinstance(m, dict) else str(m)
                    if not model_id:
                        continue
                    # Check if model is free by looking at pricing metadata
                    pricing = m.get("pricing", {}) if isinstance(m, dict) else {}
                    is_free = (
                        pricing.get("input") == "Free"
                        or pricing.get("input") == 0
                        or pricing.get("input") == 0.0
                        or model_id.endswith("-free")
                        or model_id == "big-pickle"
                    )
                    if is_free:
                        free_models.append(model_id)

            if free_models:
                self._known_free_models = free_models
                logger.info(f"Zen: discovered {len(free_models)} free models: {free_models}")
                return free_models

            # No free models found in response — fall back to defaults
            logger.warning("Zen: no free models found in API response, using defaults")
            return list(self._known_free_models)

        except httpx.RequestError as e:
            logger.error("Zen API list_models error: %s", e)
            return list(self._known_free_models)
        except Exception as e:
            logger.error("Zen API list_models unexpected error: %s", e)
            return list(self._known_free_models)

    def get_known_free_models(self) -> list[str]:
        """Return the currently known free model IDs (cached)."""
        return list(self._known_free_models)

    def get_rate_stats(self) -> dict:
        """Return per-model rate limiter statistics."""
        return self._rate_limiter.get_stats()


# Module-level singleton
_zen_client: ZenApiClient | None = None


def get_zen_client() -> ZenApiClient:
    """Get or create the Zen API client singleton."""
    global _zen_client
    if _zen_client is None:
        _zen_client = ZenApiClient()
    return _zen_client

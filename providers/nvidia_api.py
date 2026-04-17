"""
NVIDIA AI API client.

Provides access to NVIDIA's free and paid models via build.nvidia.com.
Uses OpenAI-compatible chat completions endpoint.

Base URL: https://integrate.api.nvidia.com/v1
Endpoint: /chat/completions
Models: https://integrate.api.nvidia.com/v1/models
"""

import asyncio
import logging
import os
import re
from typing import Any

import httpx

from core.config import settings
from core.rate_limiter import PerModelRateLimiter

logger = logging.getLogger("frood.providers.nvidia")

# Default model list — verified against NVIDIA's /v1/models catalog 2026-04-14.
# Previous list had fabricated `:free` suffixes that returned 404. These IDs are
# confirmed to exist in the live build.nvidia.com catalog.
_DEFAULT_FREE_MODELS = [
    "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "meta/llama-3.3-70b-instruct",
    "meta/llama-3.2-3b-instruct",
    "meta/llama-3.2-1b-instruct",
    "qwen/qwen3.5-397b-a17b",
    "qwen/qwen3-coder-480b-a35b-instruct",
    "qwen/qwq-32b",
    "deepseek-ai/deepseek-v3.2",
    "writer/palmyra-creative-122b",
    "mistralai/mistral-large-3-675b-instruct-2512",
]


class NvidiaApiClient:
    """API client for NVIDIA AI with OpenAI-compatible interface."""

    def __init__(self):
        self._base_url = "https://integrate.api.nvidia.com/v1"
        self._known_free_models: list[str] = list(_DEFAULT_FREE_MODELS)
        self._rate_limiter = PerModelRateLimiter()
        self._rate_limiting_enabled = True  # NVIDIA has rate limits

    def _get_api_key(self) -> str:
        """Get the NVIDIA API key from environment."""
        return os.environ.get("NVIDIA_API_KEY", "")

    async def chat_completion(
        self,
        model: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> dict:
        """Send a chat completion request to NVIDIA API.

        Args:
            model:    NVIDIA model ID (e.g. "nvidia/nemotron-3-super:free")
            messages: OpenAI-compatible message list
            **kwargs: Additional parameters (temperature, max_tokens, etc.)

        Returns:
            Parsed JSON response dict, or {"error": str} on failure.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No NVIDIA API key configured — cannot make request")
            return {"error": "No NVIDIA_API_KEY configured"}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        payload = {"model": model, "messages": messages, **kwargs}
        url = f"{self._base_url}/chat/completions"

        max_retries = 3
        for attempt in range(max_retries + 1):
            if self._rate_limiting_enabled:
                await self._rate_limiter.wait(model)

            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)

                    if resp.status_code == 429:
                        retry_after = self._parse_retry_after(resp)
                        if self._rate_limiting_enabled:
                            self._rate_limiter.record_rate_limit(model, retry_after)
                        logger.warning(
                            "NVIDIA API rate limited (model=%s, attempt %d/%d), retry_after=%.1fs",
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
                        # Check for NVIDIA-specific error patterns
                        if "401" in str(resp.status_code) or "Unauthorized" in error_text:
                            return {"error": "Invalid NVIDIA API key"}
                        
                        if self._rate_limiting_enabled:
                            self._rate_limiter.record_rate_limit(model)
                        logger.warning(
                            "NVIDIA API error (model=%s, attempt %d/%d): %s",
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
                        "NVIDIA API timeout (model=%s, attempt %d/%d), retrying in %.1fs",
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
                        "NVIDIA API connection error (model=%s, attempt %d/%d): %s",
                        model,
                        attempt + 1,
                        max_retries,
                        e,
                    )
                    await asyncio.sleep(wait)
                    continue
                return {"error": str(e)}

            except Exception as e:
                logger.error("NVIDIA API unexpected error: %s", e)
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

    async def list_all_models(self) -> list[str]:
        """Fetch ALL NVIDIA model IDs (no free/paid filtering).

        Classification happens in ``core.model_classifier`` now. Falls back to
        hardcoded defaults if the endpoint is unavailable.

        Returns:
            List of every model ID from NVIDIA's /v1/models endpoint.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No NVIDIA API key configured — cannot list models")
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

            all_models: list[str] = []
            models = data.get("data", data) if isinstance(data, dict) else data
            if isinstance(models, list):
                for m in models:
                    model_id = m.get("id", "") if isinstance(m, dict) else str(m)
                    if model_id:
                        all_models.append(model_id)

            if all_models:
                logger.info("NVIDIA: advertised %d models", len(all_models))
                return all_models

            logger.warning("NVIDIA: /models returned nothing, using defaults")
            return list(self._known_free_models)

        except httpx.RequestError as e:
            logger.error("NVIDIA API list_all_models error: %s", e)
            return list(self._known_free_models)
        except Exception as e:  # noqa: BLE001
            logger.error("NVIDIA API list_all_models unexpected error: %s", e)
            return list(self._known_free_models)

    # Backwards-compat alias. Older callers using ``list_models`` will now
    # receive the unfiltered catalog; they should migrate to list_all_models
    # + core.model_classifier.
    async def list_models(self) -> list[str]:
        return await self.list_all_models()

    def get_known_free_models(self) -> list[str]:
        """Return the currently known free model IDs (cached)."""
        return list(self._known_free_models)

    def get_rate_stats(self) -> dict:
        """Return per-model rate limiter statistics."""
        return self._rate_limiter.get_stats()


# Module-level singleton
_nvidia_client: NvidiaApiClient | None = None


def get_nvidia_client() -> NvidiaApiClient:
    """Get or create the NVIDIA API client singleton."""
    global _nvidia_client
    if _nvidia_client is None:
        _nvidia_client = NvidiaApiClient()
    return _nvidia_client
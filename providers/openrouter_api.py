"""
OpenRouter API client.

OpenRouter aggregates 200+ LLMs behind a single OpenAI-compatible endpoint.
Some models are free (they end in ``:free``), most are paid and billed per
token against the account's credit balance.

Base URL: https://openrouter.ai/api/v1
Endpoints: /chat/completions, /models

This client mirrors the shape of ``providers/zen_api.py`` and
``providers/nvidia_api.py`` so ``core.model_classifier`` can treat all three
providers uniformly — ``list_all_models`` returns the full unfiltered
catalog, ``chat_completion`` accepts a ``retries=0`` kwarg for fast-fail
probing, and failures come back as ``{"error": "..."}`` dicts.
"""

from __future__ import annotations

import asyncio
import logging
import os
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger("frood.providers.openrouter")

_DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"


class OpenRouterApiClient:
    """OpenAI-compatible client for OpenRouter."""

    def __init__(self) -> None:
        self._base_url = _DEFAULT_BASE_URL
        self._known_models: list[str] = []

    def _get_api_key(self) -> str:
        return os.environ.get("OPENROUTER_API_KEY", "")

    async def chat_completion(
        self,
        model: str,
        messages: list[dict],
        *,
        retries: int = 3,
        **kwargs: Any,
    ) -> dict:
        """Send a chat completion request to OpenRouter.

        Args mirror the other provider clients. ``retries=0`` for fast-fail
        probing. Returns the parsed JSON on HTTP 200, or an ``{"error": ...}``
        dict otherwise.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No OPENROUTER_API_KEY configured — cannot make request")
            return {"error": "No OPENROUTER_API_KEY configured"}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, **kwargs}
        url = f"{self._base_url}/chat/completions"

        max_retries = max(0, retries)
        last_error = ""
        for attempt in range(max_retries + 1):
            try:
                async with httpx.AsyncClient(timeout=300.0) as client:
                    resp = await client.post(url, headers=headers, json=payload)

                if resp.status_code == 200:
                    return resp.json()

                body = resp.text[:500]
                if resp.status_code == 402:
                    return {"error": f"HTTP 402: credit exhausted: {body}", "exhausted": True}

                last_error = f"HTTP {resp.status_code}: {body}"
                if attempt < max_retries:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return {"error": last_error}
            except httpx.TimeoutException:
                last_error = "Request timed out"
                if attempt < max_retries:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return {"error": last_error}
            except httpx.RequestError as e:
                last_error = f"Request error: {e}"
                if attempt < max_retries:
                    await asyncio.sleep(2.0 * (attempt + 1))
                    continue
                return {"error": last_error}
            except Exception as e:  # noqa: BLE001
                return {"error": f"Unexpected error: {e}"}

        return {"error": last_error or "Max retries exceeded"}

    async def list_all_models(self) -> list[str]:
        """Fetch every model OpenRouter advertises (no free/paid filtering).

        Classification happens in ``core.model_classifier``.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No OPENROUTER_API_KEY configured — cannot list models")
            return list(self._known_models)

        headers = {"Authorization": f"Bearer {api_key}"}
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
                    mid = m.get("id", "") if isinstance(m, dict) else str(m)
                    if mid:
                        all_models.append(mid)

            if all_models:
                self._known_models = all_models
                logger.info("OpenRouter: advertised %d models", len(all_models))
                return all_models

            logger.warning("OpenRouter: /models returned nothing")
            return list(self._known_models)

        except httpx.RequestError as e:
            logger.error("OpenRouter list_all_models error: %s", e)
            return list(self._known_models)
        except Exception as e:  # noqa: BLE001
            logger.error("OpenRouter list_all_models unexpected error: %s", e)
            return list(self._known_models)

    async def list_models(self) -> list[str]:
        """Backwards-compat alias for list_all_models."""
        return await self.list_all_models()


# Module-level singleton
_openrouter_client: OpenRouterApiClient | None = None


def get_openrouter_client() -> OpenRouterApiClient:
    """Return (or create) the process-wide OpenRouter client."""
    global _openrouter_client
    if _openrouter_client is None:
        _openrouter_client = OpenRouterApiClient()
    return _openrouter_client

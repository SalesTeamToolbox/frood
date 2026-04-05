"""
Abacus AI RouteLLM API client.

Provides access to multiple LLM models (Claude, GPT, Gemini, Llama)
via a single Abacus AI API key. Uses OpenAI-compatible chat completions.

Free unlimited models: GPT-5 Mini, Gemini 3 Flash, Llama 4, Grok Code Fast, Kimi K2
Premium models: Claude Opus/Sonnet, GPT-5

Base URL: https://routellm.abacus.ai/v1
"""

import logging
import os
from typing import Any

import httpx

from core.config import settings

logger = logging.getLogger("agent42.providers.abacus")


class AbacusApiClient:
    """API client for Abacus AI RouteLLM with OpenAI-compatible interface."""

    def __init__(self):
        self._base_url = "https://routellm.abacus.ai/v1"

    def _get_api_key(self) -> str:
        """Get the Abacus AI API key from key store or environment."""
        # Check admin-configured key first (via dashboard)
        if hasattr(settings, "_key_store"):
            keys = settings._key_store.get_masked_keys()
            if keys.get("ABACUS_API_KEY", {}).get("configured"):
                return os.environ.get("ABACUS_API_KEY", "")

        # Fall back to environment variable
        return os.environ.get("ABACUS_API_KEY", "")

    async def chat_completion(
        self,
        model: str,
        messages: list[dict],
        **kwargs: Any,
    ) -> dict:
        """Send a chat completion request to Abacus RouteLLM API.

        Args:
            model:    Abacus model ID (e.g. "gemini-3-flash", "claude-sonnet-4-6")
            messages: OpenAI-compatible message list
            **kwargs: Additional parameters passed to the API (temperature, max_tokens, etc.)

        Returns:
            Parsed JSON response dict, or {"error": str} on failure.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No Abacus AI API key configured — cannot make request")
            return {"error": "No ABACUS_API_KEY configured"}

        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        }
        payload = {"model": model, "messages": messages, **kwargs}
        url = f"{self._base_url}/chat/completions"

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                resp = await client.post(url, headers=headers, json=payload)
                resp.raise_for_status()
                return resp.json()
        except httpx.HTTPStatusError as e:
            logger.error("Abacus API HTTP error %s: %s", e.response.status_code, e)
            return {"error": f"HTTP {e.response.status_code}: {e}"}
        except httpx.RequestError as e:
            logger.error("Abacus API connection error: %s", e)
            return {"error": str(e)}
        except Exception as e:
            logger.error("Abacus API unexpected error: %s", e)
            return {"error": str(e)}

    async def list_models(self) -> list[str]:
        """Fetch available model IDs from Abacus RouteLLM API.

        Returns:
            List of model ID strings, or empty list on failure.
        """
        api_key = self._get_api_key()
        if not api_key:
            logger.warning("No Abacus AI API key configured — cannot list models")
            return []

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
                models = data.get("data", [])
                return [m.get("id", "") for m in models if m.get("id")]
        except httpx.RequestError as e:
            logger.error("Abacus API list_models error: %s", e)
            return []
        except Exception as e:
            logger.error("Abacus API list_models unexpected error: %s", e)
            return []

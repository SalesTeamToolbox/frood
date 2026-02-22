"""
Image generation tool — create images from text prompts using AI models.

Free-first strategy: uses free models via OpenRouter by default.
Premium models (DALL-E 3, etc.) available when admin configures API keys.

Before submitting a prompt for generation, the tool runs a team-based
prompt review to refine the prompt for best results.
"""

import logging
import os
import time
import uuid
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.image_gen")


# Image model catalog — free-first, same pattern as text LLM routing
IMAGE_MODELS: dict[str, dict] = {
    # ═══════════════════════════════════════════════════════════════════
    # FREE TIER — $0 image models via OpenRouter
    # ═══════════════════════════════════════════════════════════════════
    "or-free-flux-schnell": {
        "model_id": "black-forest-labs/flux-1-schnell:free",
        "provider": "openrouter",
        "display_name": "FLUX.1 Schnell (free)",
        "tier": "free",
        "max_resolution": "1024x1024",
    },
    # ═══════════════════════════════════════════════════════════════════
    # CHEAP TIER — low-cost image models
    # ═══════════════════════════════════════════════════════════════════
    "replicate-flux-dev": {
        "model_id": "black-forest-labs/flux-dev",
        "provider": "replicate",
        "display_name": "FLUX.1 Dev (Replicate)",
        "tier": "cheap",
        "max_resolution": "1024x1024",
    },
    "replicate-sdxl": {
        "model_id": "stability-ai/sdxl",
        "provider": "replicate",
        "display_name": "Stable Diffusion XL (Replicate)",
        "tier": "cheap",
        "max_resolution": "1024x1024",
    },
    # ═══════════════════════════════════════════════════════════════════
    # PREMIUM TIER — high-quality image models
    # ═══════════════════════════════════════════════════════════════════
    "dall-e-3": {
        "model_id": "dall-e-3",
        "provider": "openai",
        "display_name": "DALL-E 3 (OpenAI)",
        "tier": "premium",
        "max_resolution": "1024x1792",
    },
    "dall-e-2": {
        "model_id": "dall-e-2",
        "provider": "openai",
        "display_name": "DALL-E 2 (OpenAI)",
        "tier": "premium",
        "max_resolution": "1024x1024",
    },
    "replicate-flux-pro": {
        "model_id": "black-forest-labs/flux-1.1-pro",
        "provider": "replicate",
        "display_name": "FLUX 1.1 Pro (Replicate)",
        "tier": "premium",
        "max_resolution": "1024x1024",
    },
}

# Default routing: free model first, then premium if admin overrides
DEFAULT_IMAGE_MODEL = "or-free-flux-schnell"
ADMIN_OVERRIDE_ENV = "AGENT42_IMAGE_MODEL"

# Prompt review model — a fast free text LLM reviews the prompt before submission
PROMPT_REVIEWER_MODEL = "or-free-mistral-small"

PROMPT_REVIEW_TEMPLATE = """\
You are an expert prompt engineer for AI image generation models. Review and
enhance the following image generation prompt to produce the best possible result.

Original prompt: {prompt}

Context: {context}

Provide an improved prompt that:
1. Adds specific details about composition, lighting, and style
2. Uses clear, descriptive language the model can follow
3. Specifies art style if not already mentioned (photorealistic, illustration, etc.)
4. Includes quality modifiers (high detail, professional, etc.)
5. Avoids ambiguous or contradictory descriptions

Respond with ONLY the improved prompt text, nothing else.
"""


class ImageGenTool(Tool):
    """Generate images from text prompts using free and premium AI models."""

    def __init__(self, router=None):
        self._router = router  # ModelRouter for prompt review LLM calls
        self._generations: dict[str, dict] = {}  # Track generation results

    @property
    def name(self) -> str:
        return "image_gen"

    @property
    def description(self) -> str:
        return (
            "Generate images from text prompts using AI models (free-first). "
            "Actions: generate (create image from prompt), edit (modify image), "
            "list_models (show available models), status (check generation), "
            "review_prompt (team-review a prompt before generation). "
            "Supports FLUX, DALL-E, Stable Diffusion."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate", "edit", "list_models", "status", "review_prompt"],
                    "description": "Image generation action",
                },
                "prompt": {
                    "type": "string",
                    "description": "Text prompt describing the image to generate",
                    "default": "",
                },
                "model": {
                    "type": "string",
                    "description": "Model key (default: auto-selects best available)",
                    "default": "",
                },
                "size": {
                    "type": "string",
                    "description": "Image size (e.g., 1024x1024, 1024x1792)",
                    "default": "1024x1024",
                },
                "quality": {
                    "type": "string",
                    "enum": ["standard", "hd"],
                    "description": "Image quality",
                    "default": "standard",
                },
                "style": {
                    "type": "string",
                    "enum": ["vivid", "natural"],
                    "description": "Image style (DALL-E 3 only)",
                    "default": "vivid",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for prompt review (brand, audience, etc.)",
                    "default": "",
                },
                "skip_review": {
                    "type": "boolean",
                    "description": "Skip the prompt review step (default: false)",
                    "default": False,
                },
                "generation_id": {
                    "type": "string",
                    "description": "Generation ID for status checks",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)

        if action == "generate":
            return await self._generate(kwargs)
        elif action == "edit":
            return await self._edit(kwargs)
        elif action == "list_models":
            return self._list_models()
        elif action == "status":
            return self._status(kwargs.get("generation_id", ""))
        elif action == "review_prompt":
            return await self._review_prompt(kwargs)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _resolve_model(self, requested: str) -> tuple[str, dict]:
        """Resolve the image model to use: admin override > requested > free default."""
        # Check admin override
        admin_model = os.getenv(ADMIN_OVERRIDE_ENV)
        if admin_model and admin_model in IMAGE_MODELS:
            return admin_model, IMAGE_MODELS[admin_model]

        # Use requested model if valid
        if requested and requested in IMAGE_MODELS:
            return requested, IMAGE_MODELS[requested]

        # Find best available model (free first, then check configured providers)
        for key, spec in IMAGE_MODELS.items():
            if spec["tier"] == "free":
                provider = spec["provider"]
                if self._is_provider_configured(provider):
                    return key, spec

        # Fall back to first configured model of any tier
        for key, spec in IMAGE_MODELS.items():
            if self._is_provider_configured(spec["provider"]):
                return key, spec

        return DEFAULT_IMAGE_MODEL, IMAGE_MODELS[DEFAULT_IMAGE_MODEL]

    @staticmethod
    def _is_provider_configured(provider: str) -> bool:
        """Check if a provider has its API key configured."""
        env_map = {
            "openrouter": "OPENROUTER_API_KEY",
            "openai": "OPENAI_API_KEY",
            "replicate": "REPLICATE_API_TOKEN",
        }
        env_var = env_map.get(provider, "")
        return bool(os.getenv(env_var, ""))

    async def _review_prompt(self, kwargs: dict) -> ToolResult:
        """Review and enhance an image generation prompt using an LLM team."""
        prompt = kwargs.get("prompt", "")
        context = kwargs.get("context", "")

        if not prompt:
            return ToolResult(error="prompt is required for review", success=False)

        if not self._router:
            return ToolResult(
                output=f"**Original prompt (no router for review):**\n{prompt}",
            )

        review_prompt = PROMPT_REVIEW_TEMPLATE.format(
            prompt=prompt,
            context=context or "General purpose image generation",
        )

        try:
            enhanced = await self._router.complete(
                PROMPT_REVIEWER_MODEL,
                [{"role": "user", "content": review_prompt}],
                temperature=0.3,
            )
            enhanced = enhanced.strip()

            output = (
                f"# Prompt Review\n\n"
                f"**Original:** {prompt}\n\n"
                f"**Enhanced:** {enhanced}\n\n"
                f"Use the enhanced prompt with action='generate' for best results."
            )
            return ToolResult(output=output)

        except Exception as e:
            logger.warning(f"Prompt review failed: {e}")
            return ToolResult(
                output=(
                    f"Prompt review failed ({e}). Using original prompt.\n\n**Prompt:** {prompt}"
                ),
            )

    async def _generate(self, kwargs: dict) -> ToolResult:
        """Generate an image from a text prompt."""
        prompt = kwargs.get("prompt", "")
        if not prompt:
            return ToolResult(error="prompt is required for generate", success=False)

        skip_review = kwargs.get("skip_review", False)
        context = kwargs.get("context", "")
        model_key = kwargs.get("model", "")
        size = kwargs.get("size", "1024x1024")
        quality = kwargs.get("quality", "standard")
        style = kwargs.get("style", "vivid")

        # Step 1: Review prompt unless skipped
        final_prompt = prompt
        review_note = ""
        if not skip_review and self._router:
            review_result = await self._review_prompt({"prompt": prompt, "context": context})
            if review_result.success and "**Enhanced:**" in review_result.output:
                # Extract enhanced prompt
                parts = review_result.output.split("**Enhanced:**")
                if len(parts) > 1:
                    enhanced = parts[1].split("\n\n")[0].strip()
                    if enhanced:
                        final_prompt = enhanced
                        review_note = f"Prompt enhanced from: '{prompt}'\n"

        # Step 2: Resolve model
        resolved_key, model_spec = self._resolve_model(model_key)
        provider = model_spec["provider"]

        # Step 3: Generate based on provider
        gen_id = uuid.uuid4().hex[:10]
        gen_record = {
            "id": gen_id,
            "prompt": final_prompt,
            "original_prompt": prompt,
            "model": resolved_key,
            "provider": provider,
            "size": size,
            "status": "generating",
            "started_at": time.time(),
            "result_path": "",
            "error": "",
        }
        self._generations[gen_id] = gen_record

        try:
            if provider == "openai":
                result = await self._generate_openai(final_prompt, model_spec, size, quality, style)
            elif provider == "openrouter":
                result = await self._generate_openrouter(final_prompt, model_spec, size)
            elif provider == "replicate":
                result = await self._generate_replicate(final_prompt, model_spec, size)
            else:
                gen_record["status"] = "failed"
                gen_record["error"] = f"Unknown provider: {provider}"
                return ToolResult(error=f"Unknown provider: {provider}", success=False)

            gen_record["status"] = "completed"
            gen_record["result_path"] = result.get("path", "")

            output = (
                f"# Image Generated\n\n"
                f"**Generation ID:** {gen_id}\n"
                f"**Model:** {model_spec['display_name']}\n"
                f"**Size:** {size}\n"
                f"{review_note}"
                f"**Prompt:** {final_prompt}\n\n"
            )
            if result.get("path"):
                output += f"**Saved to:** {result['path']}\n"
            if result.get("url"):
                output += f"**URL:** {result['url']}\n"
            if result.get("revised_prompt"):
                output += f"**Model-revised prompt:** {result['revised_prompt']}\n"

            return ToolResult(output=output)

        except Exception as e:
            gen_record["status"] = "failed"
            gen_record["error"] = str(e)
            return ToolResult(error=f"Image generation failed: {e}", success=False)

    async def _generate_openai(
        self, prompt: str, model_spec: dict, size: str, quality: str, style: str
    ) -> dict:
        """Generate image via OpenAI DALL-E API."""
        from openai import AsyncOpenAI

        api_key = os.getenv("OPENAI_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY not set")

        client = AsyncOpenAI(api_key=api_key)
        model_id = model_spec["model_id"]

        kwargs = {
            "model": model_id,
            "prompt": prompt,
            "n": 1,
            "size": size,
        }
        if model_id == "dall-e-3":
            kwargs["quality"] = quality
            kwargs["style"] = style

        response = await client.images.generate(**kwargs)
        image_data = response.data[0]

        result = {
            "url": image_data.url or "",
            "revised_prompt": getattr(image_data, "revised_prompt", ""),
        }

        # Save image if URL returned
        if image_data.url:
            result["path"] = await self._save_from_url(image_data.url, "openai")

        return result

    async def _generate_openrouter(self, prompt: str, model_spec: dict, size: str) -> dict:
        """Generate image via OpenRouter API."""
        import httpx

        api_key = os.getenv("OPENROUTER_API_KEY", "")
        if not api_key:
            raise RuntimeError("OPENROUTER_API_KEY not set")

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/images/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_spec["model_id"],
                    "prompt": prompt,
                    "n": 1,
                    "size": size,
                },
            )
            response.raise_for_status()
            data = response.json()

        image_url = ""
        if data.get("data") and len(data["data"]) > 0:
            image_url = data["data"][0].get("url", "")

        result = {"url": image_url}
        if image_url:
            result["path"] = await self._save_from_url(image_url, "openrouter")

        return result

    async def _generate_replicate(self, prompt: str, model_spec: dict, size: str) -> dict:
        """Generate image via Replicate API."""
        import httpx

        api_token = os.getenv("REPLICATE_API_TOKEN", "")
        if not api_token:
            raise RuntimeError("REPLICATE_API_TOKEN not set")

        # Parse size
        try:
            width, height = size.split("x")
            width, height = int(width), int(height)
        except (ValueError, AttributeError):
            width, height = 1024, 1024

        # Create prediction
        async with httpx.AsyncClient(timeout=300) as client:
            # Start prediction
            response = await client.post(
                "https://api.replicate.com/v1/predictions",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": model_spec["model_id"],
                    "input": {
                        "prompt": prompt,
                        "width": width,
                        "height": height,
                    },
                },
            )
            response.raise_for_status()
            prediction = response.json()

            # Poll for completion
            prediction_url = prediction.get("urls", {}).get("get", "")
            if not prediction_url:
                prediction_url = f"https://api.replicate.com/v1/predictions/{prediction['id']}"

            for _ in range(60):  # Max 5 min wait
                import asyncio

                await asyncio.sleep(5)

                status_response = await client.get(
                    prediction_url,
                    headers={"Authorization": f"Bearer {api_token}"},
                )
                status_response.raise_for_status()
                status_data = status_response.json()

                if status_data["status"] == "succeeded":
                    output = status_data.get("output")
                    image_url = output[0] if isinstance(output, list) else output
                    result = {"url": image_url}
                    if image_url:
                        result["path"] = await self._save_from_url(image_url, "replicate")
                    return result

                if status_data["status"] == "failed":
                    raise RuntimeError(
                        f"Replicate prediction failed: {status_data.get('error', 'unknown')}"
                    )

            raise RuntimeError("Replicate prediction timed out")

    async def _save_from_url(self, url: str, provider: str) -> str:
        """Download and save an image from a URL."""
        import httpx

        from core.config import settings

        images_dir = Path(settings.images_dir)
        images_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{provider}_{uuid.uuid4().hex[:8]}.png"
        filepath = images_dir / filename

        try:
            async with httpx.AsyncClient(timeout=60) as client:
                response = await client.get(url)
                response.raise_for_status()
                filepath.write_bytes(response.content)
            return str(filepath)
        except Exception as e:
            logger.warning(f"Failed to save image from URL: {e}")
            return ""

    async def _edit(self, kwargs: dict) -> ToolResult:
        """Edit an existing image with instructions (DALL-E 2 only)."""
        prompt = kwargs.get("prompt", "")
        if not prompt:
            return ToolResult(error="prompt is required for edit", success=False)

        return ToolResult(
            output=(
                "Image editing requires an input image file. "
                "Currently supported via DALL-E 2 with the openai provider. "
                "Use the generate action to create new images from text."
            )
        )

    def _list_models(self) -> ToolResult:
        """List available image generation models."""
        lines = ["# Available Image Models\n"]

        for tier_name, tier_label in [
            ("free", "Free Tier"),
            ("cheap", "Low Cost"),
            ("premium", "Premium"),
        ]:
            tier_models = {k: v for k, v in IMAGE_MODELS.items() if v["tier"] == tier_name}
            if tier_models:
                lines.append(f"\n## {tier_label}\n")
                for key, spec in tier_models.items():
                    configured = self._is_provider_configured(spec["provider"])
                    status = "configured" if configured else "not configured"
                    is_default = " (default)" if key == DEFAULT_IMAGE_MODEL else ""
                    admin_set = ""
                    admin_override = os.getenv(ADMIN_OVERRIDE_ENV, "")
                    if admin_override == key:
                        admin_set = " (admin override)"
                    lines.append(
                        f"- **{key}**{is_default}{admin_set} — {spec['display_name']}\n"
                        f"  Provider: {spec['provider']} ({status})\n"
                        f"  Max resolution: {spec['max_resolution']}"
                    )

        lines.append(
            f"\n**Admin override:** Set `{ADMIN_OVERRIDE_ENV}` env var to force a specific model."
        )
        return ToolResult(output="\n".join(lines))

    def _status(self, gen_id: str) -> ToolResult:
        """Check status of a generation."""
        if not gen_id:
            if not self._generations:
                return ToolResult(output="No image generations recorded.")
            lines = ["# Recent Generations\n"]
            for gid, gen in list(self._generations.items())[-10:]:
                lines.append(
                    f"- **{gid}** — {gen['status']} | model: {gen['model']} | "
                    f"prompt: {gen['prompt'][:50]}..."
                )
            return ToolResult(output="\n".join(lines))

        gen = self._generations.get(gen_id)
        if not gen:
            return ToolResult(error=f"Generation '{gen_id}' not found", success=False)

        output = (
            f"# Generation: {gen_id}\n\n"
            f"**Status:** {gen['status']}\n"
            f"**Model:** {gen['model']}\n"
            f"**Prompt:** {gen['prompt']}\n"
        )
        if gen.get("result_path"):
            output += f"**File:** {gen['result_path']}\n"
        if gen.get("error"):
            output += f"**Error:** {gen['error']}\n"

        return ToolResult(output=output)

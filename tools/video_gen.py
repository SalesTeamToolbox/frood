"""
Video generation tool — create short videos from text prompts or images.

Free-first strategy: uses free/cheap models by default via Replicate.
Premium models available when admin configures API keys.

Video generation is asynchronous — the tool returns a job ID that can be
polled for completion. Before generating, prompts are reviewed by a team.
"""

import asyncio
import logging
import os
import time
import uuid
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.video_gen")


# Video model catalog — free-first, same pattern as text LLM routing
VIDEO_MODELS: dict[str, dict] = {
    # ═══════════════════════════════════════════════════════════════════
    # CHEAP TIER — low-cost video models via Replicate
    # ═══════════════════════════════════════════════════════════════════
    "replicate-cogvideox": {
        "model_id": "tencent/cogvideox-5b",
        "provider": "replicate",
        "display_name": "CogVideoX-5B (Replicate)",
        "tier": "cheap",
        "max_duration": 6,
        "supports_image_input": False,
    },
    "replicate-animate-diff": {
        "model_id": "lucataco/animate-diff",
        "provider": "replicate",
        "display_name": "AnimateDiff (Replicate)",
        "tier": "cheap",
        "max_duration": 4,
        "supports_image_input": False,
    },

    # ═══════════════════════════════════════════════════════════════════
    # PREMIUM TIER — high-quality video models
    # ═══════════════════════════════════════════════════════════════════
    "replicate-runway-gen3": {
        "model_id": "fofr/runway-gen3-turbo",
        "provider": "replicate",
        "display_name": "Runway Gen-3 Turbo (Replicate)",
        "tier": "premium",
        "max_duration": 10,
        "supports_image_input": True,
    },
    "luma-ray2": {
        "model_id": "ray-2",
        "provider": "luma",
        "display_name": "Luma Ray2",
        "tier": "premium",
        "max_duration": 10,
        "supports_image_input": True,
    },
    "replicate-stable-video": {
        "model_id": "stability-ai/stable-video-diffusion",
        "provider": "replicate",
        "display_name": "Stable Video Diffusion (Replicate)",
        "tier": "premium",
        "max_duration": 4,
        "supports_image_input": True,
    },
}

# Default routing
DEFAULT_VIDEO_MODEL = "replicate-cogvideox"
ADMIN_OVERRIDE_ENV = "AGENT42_VIDEO_MODEL"

# Prompt review model
PROMPT_REVIEWER_MODEL = "or-free-mistral-small"

VIDEO_PROMPT_REVIEW_TEMPLATE = """\
You are an expert prompt engineer for AI video generation models. Review and
enhance the following video generation prompt.

Original prompt: {prompt}
Context: {context}
Duration target: {duration} seconds

Provide an improved prompt that:
1. Describes motion and camera movement clearly
2. Specifies temporal progression (what happens first, then, finally)
3. Includes visual details (lighting, color palette, composition)
4. Specifies style (cinematic, animated, documentary, etc.)
5. Keeps the prompt concise — video models work best with clear, focused prompts

Respond with ONLY the improved prompt text, nothing else.
"""


class VideoGenTool(Tool):
    """Generate short videos from text prompts using free and premium AI models."""

    def __init__(self, router=None):
        self._router = router
        self._jobs: dict[str, dict] = {}  # job_id -> job state

    @property
    def name(self) -> str:
        return "video_gen"

    @property
    def description(self) -> str:
        return (
            "Generate short videos from text prompts or images (free-first). "
            "Actions: generate (create video from text), image_to_video (animate image), "
            "list_models (show available models), status (check generation progress), "
            "review_prompt (team-review a prompt before generation). "
            "Video generation is async — use status to poll for completion."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["generate", "image_to_video", "list_models", "status", "review_prompt"],
                    "description": "Video generation action",
                },
                "prompt": {
                    "type": "string",
                    "description": "Text prompt describing the video to generate",
                    "default": "",
                },
                "model": {
                    "type": "string",
                    "description": "Model key (default: auto-selects best available)",
                    "default": "",
                },
                "duration": {
                    "type": "integer",
                    "description": "Target video duration in seconds (default: 4)",
                    "default": 4,
                },
                "aspect_ratio": {
                    "type": "string",
                    "enum": ["16:9", "9:16", "1:1"],
                    "description": "Video aspect ratio",
                    "default": "16:9",
                },
                "image_url": {
                    "type": "string",
                    "description": "Source image URL for image_to_video action",
                    "default": "",
                },
                "context": {
                    "type": "string",
                    "description": "Additional context for prompt review",
                    "default": "",
                },
                "skip_review": {
                    "type": "boolean",
                    "description": "Skip the prompt review step (default: false)",
                    "default": False,
                },
                "job_id": {
                    "type": "string",
                    "description": "Job ID for status checks",
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
        elif action == "image_to_video":
            return await self._image_to_video(kwargs)
        elif action == "list_models":
            return self._list_models()
        elif action == "status":
            return await self._status(kwargs.get("job_id", ""))
        elif action == "review_prompt":
            return await self._review_prompt(kwargs)
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _resolve_model(self, requested: str, needs_image_input: bool = False) -> tuple[str, dict]:
        """Resolve the video model to use: admin override > requested > default."""
        admin_model = os.getenv(ADMIN_OVERRIDE_ENV)
        if admin_model and admin_model in VIDEO_MODELS:
            return admin_model, VIDEO_MODELS[admin_model]

        if requested and requested in VIDEO_MODELS:
            return requested, VIDEO_MODELS[requested]

        # Find best available model
        for tier in ["cheap", "premium"]:
            for key, spec in VIDEO_MODELS.items():
                if spec["tier"] != tier:
                    continue
                if needs_image_input and not spec.get("supports_image_input"):
                    continue
                if self._is_provider_configured(spec["provider"]):
                    return key, spec

        return DEFAULT_VIDEO_MODEL, VIDEO_MODELS[DEFAULT_VIDEO_MODEL]

    @staticmethod
    def _is_provider_configured(provider: str) -> bool:
        """Check if a provider has its API key configured."""
        env_map = {
            "replicate": "REPLICATE_API_TOKEN",
            "luma": "LUMA_API_KEY",
        }
        env_var = env_map.get(provider, "")
        return bool(os.getenv(env_var, ""))

    async def _review_prompt(self, kwargs: dict) -> ToolResult:
        """Review and enhance a video generation prompt using an LLM."""
        prompt = kwargs.get("prompt", "")
        context = kwargs.get("context", "")
        duration = kwargs.get("duration", 4)

        if not prompt:
            return ToolResult(error="prompt is required for review", success=False)

        if not self._router:
            return ToolResult(
                output=f"**Original prompt (no router for review):**\n{prompt}",
            )

        review_prompt = VIDEO_PROMPT_REVIEW_TEMPLATE.format(
            prompt=prompt,
            context=context or "General purpose video generation",
            duration=duration,
        )

        try:
            enhanced = await self._router.complete(
                PROMPT_REVIEWER_MODEL,
                [{"role": "user", "content": review_prompt}],
                temperature=0.3,
            )
            enhanced = enhanced.strip()

            output = (
                f"# Video Prompt Review\n\n"
                f"**Original:** {prompt}\n\n"
                f"**Enhanced:** {enhanced}\n\n"
                f"Use the enhanced prompt with action='generate' for best results."
            )
            return ToolResult(output=output)

        except Exception as e:
            logger.warning(f"Prompt review failed: {e}")
            return ToolResult(
                output=f"Prompt review failed ({e}). Using original prompt.\n**Prompt:** {prompt}",
            )

    async def _generate(self, kwargs: dict) -> ToolResult:
        """Generate a video from a text prompt."""
        prompt = kwargs.get("prompt", "")
        if not prompt:
            return ToolResult(error="prompt is required for generate", success=False)

        skip_review = kwargs.get("skip_review", False)
        context = kwargs.get("context", "")
        model_key = kwargs.get("model", "")
        duration = kwargs.get("duration", 4)
        aspect_ratio = kwargs.get("aspect_ratio", "16:9")

        # Step 1: Review prompt unless skipped
        final_prompt = prompt
        review_note = ""
        if not skip_review and self._router:
            review_result = await self._review_prompt({
                "prompt": prompt, "context": context, "duration": duration
            })
            if review_result.success and "**Enhanced:**" in review_result.output:
                parts = review_result.output.split("**Enhanced:**")
                if len(parts) > 1:
                    enhanced = parts[1].split("\n\n")[0].strip()
                    if enhanced:
                        final_prompt = enhanced
                        review_note = f"Prompt enhanced from: '{prompt}'\n"

        # Step 2: Resolve model
        resolved_key, model_spec = self._resolve_model(model_key)
        provider = model_spec["provider"]

        # Step 3: Create async job
        job_id = uuid.uuid4().hex[:10]
        job = {
            "id": job_id,
            "prompt": final_prompt,
            "original_prompt": prompt,
            "model": resolved_key,
            "provider": provider,
            "duration": min(duration, model_spec.get("max_duration", 6)),
            "aspect_ratio": aspect_ratio,
            "status": "submitted",
            "started_at": time.time(),
            "result_path": "",
            "error": "",
            "prediction_url": "",
        }
        self._jobs[job_id] = job

        try:
            if provider == "replicate":
                prediction = await self._submit_replicate(final_prompt, model_spec, duration, aspect_ratio)
                job["prediction_url"] = prediction.get("urls", {}).get("get", "")
                job["status"] = "processing"
            elif provider == "luma":
                generation = await self._submit_luma(final_prompt, model_spec, duration, aspect_ratio)
                job["prediction_url"] = generation.get("id", "")
                job["status"] = "processing"
            else:
                job["status"] = "failed"
                job["error"] = f"Unknown provider: {provider}"
                return ToolResult(error=f"Unknown provider: {provider}", success=False)

            output = (
                f"# Video Generation Submitted\n\n"
                f"**Job ID:** {job_id}\n"
                f"**Model:** {model_spec['display_name']}\n"
                f"**Duration:** {job['duration']}s\n"
                f"**Aspect Ratio:** {aspect_ratio}\n"
                f"{review_note}"
                f"**Prompt:** {final_prompt}\n\n"
                f"Video generation is async. Use `action='status' job_id='{job_id}'` "
                f"to check progress."
            )
            return ToolResult(output=output)

        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            return ToolResult(error=f"Video generation failed: {e}", success=False)

    async def _image_to_video(self, kwargs: dict) -> ToolResult:
        """Animate a still image into a short video."""
        image_url = kwargs.get("image_url", "")
        prompt = kwargs.get("prompt", "")

        if not image_url:
            return ToolResult(error="image_url is required for image_to_video", success=False)

        model_key = kwargs.get("model", "")
        duration = kwargs.get("duration", 4)
        aspect_ratio = kwargs.get("aspect_ratio", "16:9")

        resolved_key, model_spec = self._resolve_model(model_key, needs_image_input=True)

        if not model_spec.get("supports_image_input"):
            return ToolResult(
                error=(
                    f"Model {resolved_key} does not support image-to-video. "
                    "Try: replicate-runway-gen3, luma-ray2, or replicate-stable-video"
                ),
                success=False,
            )

        job_id = uuid.uuid4().hex[:10]
        job = {
            "id": job_id,
            "prompt": prompt or "Animate this image with natural movement",
            "model": resolved_key,
            "provider": model_spec["provider"],
            "duration": min(duration, model_spec.get("max_duration", 6)),
            "aspect_ratio": aspect_ratio,
            "image_url": image_url,
            "status": "submitted",
            "started_at": time.time(),
            "result_path": "",
            "error": "",
            "prediction_url": "",
        }
        self._jobs[job_id] = job

        try:
            if model_spec["provider"] == "replicate":
                prediction = await self._submit_replicate_i2v(
                    prompt or "Animate with natural movement",
                    image_url, model_spec, duration
                )
                job["prediction_url"] = prediction.get("urls", {}).get("get", "")
                job["status"] = "processing"
            elif model_spec["provider"] == "luma":
                generation = await self._submit_luma(
                    prompt or "Animate this image", model_spec, duration,
                    aspect_ratio, image_url=image_url
                )
                job["prediction_url"] = generation.get("id", "")
                job["status"] = "processing"

            return ToolResult(
                output=(
                    f"# Image-to-Video Submitted\n\n"
                    f"**Job ID:** {job_id}\n"
                    f"**Model:** {model_spec['display_name']}\n"
                    f"**Source Image:** {image_url}\n\n"
                    f"Use `action='status' job_id='{job_id}'` to check progress."
                )
            )
        except Exception as e:
            job["status"] = "failed"
            job["error"] = str(e)
            return ToolResult(error=f"Image-to-video failed: {e}", success=False)

    async def _submit_replicate(
        self, prompt: str, model_spec: dict, duration: int, aspect_ratio: str
    ) -> dict:
        """Submit a video generation job to Replicate."""
        import httpx

        api_token = os.getenv("REPLICATE_API_TOKEN", "")
        if not api_token:
            raise RuntimeError("REPLICATE_API_TOKEN not set")

        async with httpx.AsyncClient(timeout=60) as client:
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
                        "num_frames": duration * 8,  # ~8fps for most models
                    },
                },
            )
            response.raise_for_status()
            return response.json()

    async def _submit_replicate_i2v(
        self, prompt: str, image_url: str, model_spec: dict, duration: int
    ) -> dict:
        """Submit image-to-video job to Replicate."""
        import httpx

        api_token = os.getenv("REPLICATE_API_TOKEN", "")
        if not api_token:
            raise RuntimeError("REPLICATE_API_TOKEN not set")

        async with httpx.AsyncClient(timeout=60) as client:
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
                        "image": image_url,
                    },
                },
            )
            response.raise_for_status()
            return response.json()

    async def _submit_luma(
        self, prompt: str, model_spec: dict, duration: int,
        aspect_ratio: str, image_url: str = ""
    ) -> dict:
        """Submit a video generation job to Luma AI."""
        import httpx

        api_key = os.getenv("LUMA_API_KEY", "")
        if not api_key:
            raise RuntimeError("LUMA_API_KEY not set")

        payload = {
            "prompt": prompt,
            "model": model_spec["model_id"],
            "duration": f"{duration}s",
            "aspect_ratio": aspect_ratio,
        }
        if image_url:
            payload["keyframes"] = {"frame0": {"type": "image", "url": image_url}}

        async with httpx.AsyncClient(timeout=60) as client:
            response = await client.post(
                "https://api.lumalabs.ai/dream-machine/v1/generations",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            return response.json()

    async def _status(self, job_id: str) -> ToolResult:
        """Check status of a video generation job, polling the provider if needed."""
        if not job_id:
            if not self._jobs:
                return ToolResult(output="No video generation jobs recorded.")
            lines = ["# Video Generation Jobs\n"]
            for jid, job in list(self._jobs.items())[-10:]:
                lines.append(
                    f"- **{jid}** — {job['status']} | model: {job['model']} | "
                    f"prompt: {job['prompt'][:50]}..."
                )
            return ToolResult(output="\n".join(lines))

        job = self._jobs.get(job_id)
        if not job:
            return ToolResult(error=f"Job '{job_id}' not found", success=False)

        # Poll provider for updates if still processing
        if job["status"] == "processing" and job.get("prediction_url"):
            try:
                if job["provider"] == "replicate":
                    await self._poll_replicate(job)
                elif job["provider"] == "luma":
                    await self._poll_luma(job)
            except Exception as e:
                logger.warning(f"Status poll failed: {e}")

        output = (
            f"# Video Job: {job_id}\n\n"
            f"**Status:** {job['status']}\n"
            f"**Model:** {job['model']}\n"
            f"**Duration:** {job.get('duration', '?')}s\n"
            f"**Prompt:** {job['prompt']}\n"
        )
        if job.get("result_path"):
            output += f"**File:** {job['result_path']}\n"
        if job.get("error"):
            output += f"**Error:** {job['error']}\n"

        elapsed = time.time() - job.get("started_at", time.time())
        output += f"**Elapsed:** {elapsed:.0f}s\n"

        return ToolResult(output=output)

    async def _poll_replicate(self, job: dict):
        """Poll Replicate for job completion."""
        import httpx

        api_token = os.getenv("REPLICATE_API_TOKEN", "")
        if not api_token:
            return

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                job["prediction_url"],
                headers={"Authorization": f"Bearer {api_token}"},
            )
            response.raise_for_status()
            data = response.json()

            if data["status"] == "succeeded":
                output = data.get("output")
                video_url = output if isinstance(output, str) else (output[0] if output else "")
                job["status"] = "completed"
                if video_url:
                    job["result_path"] = await self._save_video(video_url, "replicate")

            elif data["status"] == "failed":
                job["status"] = "failed"
                job["error"] = data.get("error", "Unknown error")

    async def _poll_luma(self, job: dict):
        """Poll Luma AI for job completion."""
        import httpx

        api_key = os.getenv("LUMA_API_KEY", "")
        if not api_key:
            return

        gen_id = job["prediction_url"]

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"https://api.lumalabs.ai/dream-machine/v1/generations/{gen_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            response.raise_for_status()
            data = response.json()

            if data.get("state") == "completed":
                video_url = data.get("assets", {}).get("video", "")
                job["status"] = "completed"
                if video_url:
                    job["result_path"] = await self._save_video(video_url, "luma")

            elif data.get("state") == "failed":
                job["status"] = "failed"
                job["error"] = data.get("failure_reason", "Unknown error")

    async def _save_video(self, url: str, provider: str) -> str:
        """Download and save a video from a URL."""
        import httpx
        from core.config import settings

        output_dir = Path(settings.outputs_dir) / "videos"
        output_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{provider}_{uuid.uuid4().hex[:8]}.mp4"
        filepath = output_dir / filename

        try:
            async with httpx.AsyncClient(timeout=120) as client:
                response = await client.get(url)
                response.raise_for_status()
                filepath.write_bytes(response.content)
            return str(filepath)
        except Exception as e:
            logger.warning(f"Failed to save video: {e}")
            return ""

    def _list_models(self) -> ToolResult:
        """List available video generation models."""
        lines = ["# Available Video Models\n"]

        for tier_name, tier_label in [("cheap", "Low Cost"), ("premium", "Premium")]:
            tier_models = {k: v for k, v in VIDEO_MODELS.items() if v["tier"] == tier_name}
            if tier_models:
                lines.append(f"\n## {tier_label}\n")
                for key, spec in tier_models.items():
                    configured = self._is_provider_configured(spec["provider"])
                    status = "configured" if configured else "not configured"
                    i2v = " | image-to-video" if spec.get("supports_image_input") else ""
                    is_default = " (default)" if key == DEFAULT_VIDEO_MODEL else ""
                    lines.append(
                        f"- **{key}**{is_default} — {spec['display_name']}\n"
                        f"  Provider: {spec['provider']} ({status})\n"
                        f"  Max duration: {spec['max_duration']}s{i2v}"
                    )

        lines.append(
            f"\n**Admin override:** Set `{ADMIN_OVERRIDE_ENV}` env var to force a specific model."
        )
        lines.append(
            "\n**Note:** Video generation is async. Most models take 30s-5min. "
            "Use the `status` action to poll for completion."
        )
        return ToolResult(output="\n".join(lines))

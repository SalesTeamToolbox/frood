"""
Vision tool — image analysis using LLM vision capabilities.

Enables agents to analyze, describe, and compare images by sending them
to vision-capable LLMs. Useful for verifying website designs, reviewing
screenshots, understanding diagrams, and visual content analysis.

Security:
- Images must be within the sandbox workspace
- Max image size configurable (default: 10MB)
"""

import base64
import io
import logging
import os
from pathlib import Path

from core.config import settings
from core.sandbox import WorkspaceSandbox
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.vision")

# Max pixel count for compression (768K pixels = ~876x876)
MAX_PIXELS = 768_000
JPEG_QUALITY = 75
SUPPORTED_FORMATS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp"}

# Approximate token cost per image for context window tracking
TOKENS_PER_IMAGE = 1500


def _compress_image(image_data: bytes, max_pixels: int = MAX_PIXELS) -> tuple[bytes, str]:
    """Compress and resize an image for LLM vision.

    Returns (compressed_bytes, mime_type).
    """
    try:
        from PIL import Image
    except ImportError:
        raise ImportError("Pillow is required for vision tool: pip install Pillow")

    img = Image.open(io.BytesIO(image_data))

    # Convert to RGB if needed (e.g., RGBA, palette mode)
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")

    # Resize if too many pixels
    width, height = img.size
    total_pixels = width * height
    if total_pixels > max_pixels:
        scale = (max_pixels / total_pixels) ** 0.5
        new_width = max(1, int(width * scale))
        new_height = max(1, int(height * scale))
        img = img.resize((new_width, new_height), Image.LANCZOS)

    # Compress to JPEG
    buffer = io.BytesIO()
    img.save(buffer, format="JPEG", quality=JPEG_QUALITY, optimize=True)
    return buffer.getvalue(), "image/jpeg"


class VisionTool(Tool):
    """Analyze images using LLM vision capabilities.

    Actions:
    - analyze: Send an image with a custom prompt to a vision LLM
    - describe: Get a general description of an image
    - compare: Compare two images side by side
    """

    def __init__(self, sandbox: WorkspaceSandbox):
        self._sandbox = sandbox

    @property
    def name(self) -> str:
        return "vision"

    @property
    def description(self) -> str:
        return (
            "Analyze images using AI vision. Upload screenshots, diagrams, or photos "
            "for analysis, description, or comparison. "
            "Actions: analyze, describe, compare."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["analyze", "describe", "compare"],
                    "description": "Action to perform",
                },
                "image_path": {
                    "type": "string",
                    "description": "Path to image file (for analyze/describe)",
                },
                "prompt": {
                    "type": "string",
                    "description": "Analysis prompt (for analyze, optional for describe)",
                },
                "image_path_2": {
                    "type": "string",
                    "description": "Path to second image (for compare)",
                },
            },
            "required": ["action"],
        }

    def _validate_image(self, image_path: str) -> tuple[Path, str | None]:
        """Validate image path and return (resolved_path, error_or_none)."""
        if not image_path:
            return Path(), "image_path is required"

        try:
            resolved = self._sandbox.resolve_path(image_path)
        except Exception as e:
            return Path(), f"Path blocked by sandbox: {e}"

        path = Path(resolved)
        if not path.exists():
            return Path(), f"File not found: {image_path}"

        if path.suffix.lower() not in SUPPORTED_FORMATS:
            return Path(), f"Unsupported format: {path.suffix}. Supported: {', '.join(sorted(SUPPORTED_FORMATS))}"

        # Check file size
        size_mb = os.path.getsize(str(path)) / (1024 * 1024)
        if size_mb > settings.vision_max_image_mb:
            return Path(), f"Image too large ({size_mb:.1f}MB). Max: {settings.vision_max_image_mb}MB"

        return path, None

    async def _load_and_encode(self, path: Path) -> tuple[str, str]:
        """Load an image, compress it, and return (base64_data, mime_type)."""
        import aiofiles
        async with aiofiles.open(path, "rb") as f:
            raw_data = await f.read()

        compressed, mime = _compress_image(raw_data)
        b64 = base64.b64encode(compressed).decode("utf-8")
        return b64, mime

    async def _call_vision_llm(self, messages: list[dict]) -> str:
        """Send messages with images to a vision-capable LLM."""
        from openai import AsyncOpenAI

        # Determine model and client
        model = settings.vision_model
        api_key = ""
        base_url = ""

        if model:
            # Explicit model configured — determine provider from model name
            if "gpt" in model.lower():
                api_key = settings.openai_api_key
                base_url = "https://api.openai.com/v1"
            elif "claude" in model.lower():
                api_key = settings.anthropic_api_key
                base_url = "https://api.anthropic.com/v1"
            else:
                # Try OpenRouter
                api_key = settings.openrouter_api_key
                base_url = "https://openrouter.ai/api/v1"
        else:
            # Auto-detect: prefer OpenAI (GPT-4 Vision), then OpenRouter
            if settings.openai_api_key:
                api_key = settings.openai_api_key
                base_url = "https://api.openai.com/v1"
                model = "gpt-4o-mini"  # Cheap vision-capable model
            elif settings.openrouter_api_key:
                api_key = settings.openrouter_api_key
                base_url = "https://openrouter.ai/api/v1"
                model = "openai/gpt-4o-mini"
            else:
                return "[Error: No vision-capable API key configured. Set OPENAI_API_KEY or OPENROUTER_API_KEY]"

        client = AsyncOpenAI(api_key=api_key, base_url=base_url)

        try:
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                max_tokens=1024,
            )
            return response.choices[0].message.content or "[No response]"
        except Exception as e:
            logger.error(f"Vision LLM call failed: {e}")
            return f"[Vision analysis failed: {e}]"

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if action == "analyze":
            return await self._analyze(**kwargs)
        elif action == "describe":
            return await self._describe(**kwargs)
        elif action == "compare":
            return await self._compare(**kwargs)
        return ToolResult(error=f"Unknown action: {action}", success=False)

    async def _analyze(self, image_path: str = "", prompt: str = "", **kwargs) -> ToolResult:
        path, error = self._validate_image(image_path)
        if error:
            return ToolResult(error=error, success=False)

        if not prompt:
            prompt = "Analyze this image in detail. Describe what you see and any notable elements."

        b64, mime = await self._load_and_encode(path)

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ]

        result = await self._call_vision_llm(messages)
        return ToolResult(output=result)

    async def _describe(self, image_path: str = "", **kwargs) -> ToolResult:
        path, error = self._validate_image(image_path)
        if error:
            return ToolResult(error=error, success=False)

        b64, mime = await self._load_and_encode(path)

        messages = [
            {
                "role": "user",
                "content": [
                    {
                        "type": "text",
                        "text": "Describe this image comprehensively. Include: main subject, colors, layout, text content (if any), and overall composition.",
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime};base64,{b64}"},
                    },
                ],
            }
        ]

        result = await self._call_vision_llm(messages)
        return ToolResult(output=result)

    async def _compare(
        self, image_path: str = "", image_path_2: str = "", prompt: str = "", **kwargs
    ) -> ToolResult:
        path1, error1 = self._validate_image(image_path)
        if error1:
            return ToolResult(error=f"Image 1: {error1}", success=False)

        path2, error2 = self._validate_image(image_path_2)
        if error2:
            return ToolResult(error=f"Image 2: {error2}", success=False)

        b64_1, mime_1 = await self._load_and_encode(path1)
        b64_2, mime_2 = await self._load_and_encode(path2)

        comparison_prompt = prompt or (
            "Compare these two images. Identify similarities and differences "
            "in content, layout, colors, and any notable changes between them."
        )

        messages = [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": comparison_prompt},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_1};base64,{b64_1}"},
                    },
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:{mime_2};base64,{b64_2}"},
                    },
                ],
            }
        ]

        result = await self._call_vision_llm(messages)
        return ToolResult(output=result)

"""Tests for vision / image analysis tool."""

import io
from pathlib import Path
from unittest.mock import patch

import pytest

from core.sandbox import WorkspaceSandbox
from tools.vision_tool import VisionTool, _compress_image


@pytest.fixture
def sandbox(tmp_path):
    return WorkspaceSandbox(tmp_path, enabled=True)


@pytest.fixture
def vision_tool(sandbox):
    return VisionTool(sandbox)


def _can_import_pillow() -> bool:
    try:
        from PIL import Image  # noqa: F401
        return True
    except ImportError:
        return False


def _create_test_image(path: Path, width: int = 100, height: int = 100) -> Path:
    """Create a minimal valid PNG image file for testing."""
    try:
        from PIL import Image
        img = Image.new("RGB", (width, height), color="red")
        img.save(str(path), format="PNG")
    except ImportError:
        # Create a minimal 1x1 PNG manually if Pillow not available
        import struct
        import zlib

        def _png_chunk(chunk_type, data):
            chunk = chunk_type + data
            return struct.pack(">I", len(data)) + chunk + struct.pack(">I", zlib.crc32(chunk) & 0xFFFFFFFF)

        sig = b"\x89PNG\r\n\x1a\n"
        ihdr = _png_chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
        raw_data = b"\x00\xff\x00\x00"  # filter byte + RGB
        idat = _png_chunk(b"IDAT", zlib.compress(raw_data))
        iend = _png_chunk(b"IEND", b"")
        path.write_bytes(sig + ihdr + idat + iend)
    return path


class TestVisionTool:
    def test_tool_properties(self, vision_tool):
        assert vision_tool.name == "vision"
        assert "vision" in vision_tool.description.lower() or "image" in vision_tool.description.lower()
        params = vision_tool.parameters
        assert params["type"] == "object"
        assert "action" in params["properties"]

    @pytest.mark.asyncio
    async def test_unknown_action(self, vision_tool):
        result = await vision_tool.execute(action="invalid")
        assert not result.success
        assert "Unknown action" in result.error

    @pytest.mark.asyncio
    async def test_analyze_missing_image(self, vision_tool):
        result = await vision_tool.execute(action="analyze")
        assert not result.success
        assert "image_path is required" in result.error

    @pytest.mark.asyncio
    async def test_analyze_file_not_found(self, vision_tool):
        result = await vision_tool.execute(
            action="analyze", image_path="nonexistent.png"
        )
        assert not result.success
        assert "not found" in result.error.lower()

    @pytest.mark.asyncio
    async def test_analyze_unsupported_format(self, vision_tool, tmp_path):
        test_file = tmp_path / "doc.docx"
        test_file.write_bytes(b"fake content")
        result = await vision_tool.execute(
            action="analyze", image_path=str(test_file)
        )
        assert not result.success
        assert "Unsupported format" in result.error

    @pytest.mark.asyncio
    async def test_analyze_image_too_large(self, vision_tool, tmp_path):
        test_file = tmp_path / "large.png"
        _create_test_image(test_file)

        with patch("tools.vision_tool.settings") as mock_settings:
            mock_settings.vision_max_image_mb = 0  # Force size limit to 0
            result = await vision_tool.execute(
                action="analyze", image_path=str(test_file)
            )
        assert not result.success
        assert "too large" in result.error.lower()

    @pytest.mark.asyncio
    async def test_describe_missing_image(self, vision_tool):
        result = await vision_tool.execute(action="describe")
        assert not result.success

    @pytest.mark.asyncio
    async def test_compare_missing_images(self, vision_tool):
        result = await vision_tool.execute(action="compare")
        assert not result.success

    @pytest.mark.asyncio
    async def test_compare_missing_second_image(self, vision_tool, tmp_path):
        test_file = tmp_path / "img.png"
        _create_test_image(test_file)

        with patch("tools.vision_tool.settings") as mock_settings:
            mock_settings.vision_max_image_mb = 10
            result = await vision_tool.execute(
                action="compare",
                image_path=str(test_file),
                image_path_2="nonexistent.png",
            )
        assert not result.success


class TestCompressImage:
    @pytest.mark.skipif(
        not _can_import_pillow(),
        reason="Pillow not installed",
    )
    def test_compression_reduces_large_image(self):
        from PIL import Image

        # Create a large image
        img = Image.new("RGB", (2000, 2000), color="blue")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()

        compressed, mime = _compress_image(raw, max_pixels=768_000)
        assert mime == "image/jpeg"
        # Compressed should be smaller than raw PNG
        assert len(compressed) < len(raw)

    @pytest.mark.skipif(
        not _can_import_pillow(),
        reason="Pillow not installed",
    )
    def test_small_image_not_resized(self):
        from PIL import Image

        img = Image.new("RGB", (100, 100), color="green")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()

        compressed, mime = _compress_image(raw, max_pixels=768_000)
        assert mime == "image/jpeg"

    @pytest.mark.skipif(
        not _can_import_pillow(),
        reason="Pillow not installed",
    )
    def test_rgba_image_converted(self):
        from PIL import Image

        img = Image.new("RGBA", (100, 100), color=(255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        raw = buf.getvalue()

        compressed, mime = _compress_image(raw)
        assert mime == "image/jpeg"

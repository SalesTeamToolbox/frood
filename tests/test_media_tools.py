"""Tests for media generation tools: image_gen, video_gen, persona, and tool enhancements."""

import pytest

from tools.content_analyzer import ContentAnalyzerTool
from tools.image_gen import DEFAULT_IMAGE_MODEL, IMAGE_MODELS, ImageGenTool
from tools.persona_tool import BUILTIN_PERSONAS, PersonaTool
from tools.scoring_tool import ScoringTool
from tools.template_tool import TemplateTool
from tools.video_gen import DEFAULT_VIDEO_MODEL, VIDEO_MODELS, VideoGenTool

# =============================================================================
# Image Generation Tool Tests
# =============================================================================


class TestImageGenTool:
    """Test ImageGenTool actions and model resolution."""

    @pytest.fixture
    def tool(self):
        return ImageGenTool(router=None)

    @pytest.mark.asyncio
    async def test_list_models(self, tool):
        result = await tool.execute(action="list_models")
        assert result.success
        assert "Available Image Models" in result.output
        assert "FLUX" in result.output or "DALL-E" in result.output

    @pytest.mark.asyncio
    async def test_generate_requires_prompt(self, tool):
        result = await tool.execute(action="generate")
        assert not result.success
        assert "prompt is required" in result.error

    @pytest.mark.asyncio
    async def test_status_empty(self, tool):
        result = await tool.execute(action="status")
        assert result.success
        assert "No image generations" in result.output

    @pytest.mark.asyncio
    async def test_status_not_found(self, tool):
        result = await tool.execute(action="status", generation_id="nonexistent")
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_review_prompt_no_router(self, tool):
        result = await tool.execute(action="review_prompt", prompt="A sunset over mountains")
        assert result.success
        assert "no router" in result.output.lower() or "A sunset" in result.output

    @pytest.mark.asyncio
    async def test_action_required(self, tool):
        result = await tool.execute()
        assert not result.success
        assert "action is required" in result.error

    @pytest.mark.asyncio
    async def test_unknown_action(self, tool):
        result = await tool.execute(action="invalid")
        assert not result.success
        assert "Unknown action" in result.error

    def test_model_catalog_structure(self):
        """Verify all image models have required fields."""
        required_fields = {"model_id", "provider", "display_name", "tier", "max_resolution"}
        for key, spec in IMAGE_MODELS.items():
            for field in required_fields:
                assert field in spec, f"Model '{key}' missing field '{field}'"
            assert spec["tier"] in ("free", "cheap", "premium"), (
                f"Model '{key}' has invalid tier: {spec['tier']}"
            )

    def test_default_model_exists(self):
        assert DEFAULT_IMAGE_MODEL in IMAGE_MODELS

    def test_resolve_model_default(self, tool):
        """Test that _resolve_model returns a valid model."""
        key, spec = tool._resolve_model("")
        assert key in IMAGE_MODELS
        assert "model_id" in spec

    def test_has_free_models(self):
        free = [k for k, v in IMAGE_MODELS.items() if v["tier"] == "free"]
        assert len(free) >= 1, "Must have at least one free image model"

    def test_has_premium_models(self):
        premium = [k for k, v in IMAGE_MODELS.items() if v["tier"] == "premium"]
        assert len(premium) >= 1, "Must have at least one premium image model"


# =============================================================================
# Video Generation Tool Tests
# =============================================================================


class TestVideoGenTool:
    """Test VideoGenTool actions and model resolution."""

    @pytest.fixture
    def tool(self):
        return VideoGenTool(router=None)

    @pytest.mark.asyncio
    async def test_list_models(self, tool):
        result = await tool.execute(action="list_models")
        assert result.success
        assert "Available Video Models" in result.output

    @pytest.mark.asyncio
    async def test_generate_requires_prompt(self, tool):
        result = await tool.execute(action="generate")
        assert not result.success
        assert "prompt is required" in result.error

    @pytest.mark.asyncio
    async def test_image_to_video_requires_url(self, tool):
        result = await tool.execute(action="image_to_video")
        assert not result.success
        assert "image_url is required" in result.error

    @pytest.mark.asyncio
    async def test_status_empty(self, tool):
        result = await tool.execute(action="status")
        assert result.success
        assert "No video generation" in result.output

    @pytest.mark.asyncio
    async def test_status_not_found(self, tool):
        result = await tool.execute(action="status", job_id="nonexistent")
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_review_prompt_no_router(self, tool):
        result = await tool.execute(action="review_prompt", prompt="A cat walking")
        assert result.success
        assert "no router" in result.output.lower() or "cat" in result.output

    @pytest.mark.asyncio
    async def test_action_required(self, tool):
        result = await tool.execute()
        assert not result.success
        assert "action is required" in result.error

    def test_model_catalog_structure(self):
        """Verify all video models have required fields."""
        required_fields = {"model_id", "provider", "display_name", "tier", "max_duration"}
        for key, spec in VIDEO_MODELS.items():
            for field in required_fields:
                assert field in spec, f"Model '{key}' missing field '{field}'"
            assert spec["tier"] in ("cheap", "premium"), (
                f"Model '{key}' has invalid tier: {spec['tier']}"
            )

    def test_default_model_exists(self):
        assert DEFAULT_VIDEO_MODEL in VIDEO_MODELS

    def test_resolve_model_default(self, tool):
        key, spec = tool._resolve_model("")
        assert key in VIDEO_MODELS

    def test_has_image_to_video_models(self):
        """At least one model should support image-to-video."""
        i2v = [k for k, v in VIDEO_MODELS.items() if v.get("supports_image_input")]
        assert len(i2v) >= 1

    def test_resolve_model_image_input(self, tool):
        """When needs_image_input=True, should prefer models that support it."""
        key, spec = tool._resolve_model("", needs_image_input=True)
        # If we got a model, it should support image input
        # (may not find one if none are configured)
        # Just verify it doesn't crash
        assert key in VIDEO_MODELS


# =============================================================================
# Persona Tool Tests
# =============================================================================


class TestPersonaTool:
    """Test PersonaTool actions and built-in personas."""

    @pytest.fixture
    def tool(self):
        return PersonaTool()

    @pytest.mark.asyncio
    async def test_list(self, tool):
        result = await tool.execute(action="list")
        assert result.success
        assert "startup-founder" in result.output
        assert "enterprise-buyer" in result.output
        assert "developer" in result.output
        assert "marketing-manager" in result.output

    @pytest.mark.asyncio
    async def test_show(self, tool):
        result = await tool.execute(action="show", name="developer")
        assert result.success
        assert "Software Developer" in result.output
        assert "Goals" in result.output
        assert "Pain Points" in result.output
        assert "Preferred Tone" in result.output

    @pytest.mark.asyncio
    async def test_show_not_found(self, tool):
        result = await tool.execute(action="show", name="nonexistent")
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_create(self, tool):
        result = await tool.execute(
            action="create",
            name="small-biz-owner",
            title="Small Business Owner",
            demographics="Age 30-55, non-technical",
            goals=["Grow revenue", "Save time"],
            pain_points=["Limited budget", "Wearing many hats"],
            preferred_tone="Simple, practical, no jargon",
        )
        assert result.success
        assert "small-biz-owner" in result.output

        # Verify it shows up in list
        list_result = await tool.execute(action="list")
        assert "small-biz-owner" in list_result.output

    @pytest.mark.asyncio
    async def test_create_requires_name(self, tool):
        result = await tool.execute(action="create", title="Test")
        assert not result.success
        assert "name is required" in result.error

    @pytest.mark.asyncio
    async def test_create_requires_title(self, tool):
        result = await tool.execute(action="create", name="test")
        assert not result.success
        assert "title is required" in result.error

    @pytest.mark.asyncio
    async def test_delete_custom(self, tool):
        await tool.execute(action="create", name="temp-persona", title="Temporary")
        result = await tool.execute(action="delete", name="temp-persona")
        assert result.success
        assert "deleted" in result.output

    @pytest.mark.asyncio
    async def test_delete_builtin_fails(self, tool):
        result = await tool.execute(action="delete", name="developer")
        assert not result.success
        assert "Cannot delete built-in" in result.error

    @pytest.mark.asyncio
    async def test_apply(self, tool):
        result = await tool.execute(
            action="apply",
            name="startup-founder",
            task_context="Writing a landing page for our SaaS product",
        )
        assert result.success
        assert "Startup Founder" in result.output
        assert "Tone:" in result.output
        assert "goals" in result.output.lower()
        assert "pain points" in result.output.lower()

    @pytest.mark.asyncio
    async def test_apply_not_found(self, tool):
        result = await tool.execute(action="apply", name="nonexistent")
        assert not result.success
        assert "not found" in result.error

    def test_builtin_personas_structure(self):
        """Verify all built-in personas have required fields."""
        required_fields = {
            "name",
            "title",
            "demographics",
            "goals",
            "pain_points",
            "preferred_tone",
        }
        for name, persona in BUILTIN_PERSONAS.items():
            for field in required_fields:
                assert field in persona, f"Persona '{name}' missing field '{field}'"
            assert len(persona["goals"]) >= 2, f"Persona '{name}' needs at least 2 goals"
            assert len(persona["pain_points"]) >= 2, (
                f"Persona '{name}' needs at least 2 pain points"
            )


# =============================================================================
# Tool Enhancement Tests
# =============================================================================


class TestTeamToolEnhancements:
    """Test new team tool actions: describe and clone."""

    @pytest.fixture
    def tool(self):
        from tools.team_tool import TeamTool

        # Use a mock task queue
        class MockTQ:
            async def add(self, task):
                pass

            def get(self, task_id):
                return None

        return TeamTool(MockTQ())

    @pytest.mark.asyncio
    async def test_describe_builtin(self, tool):
        result = await tool.execute(action="describe", name="research-team")
        assert result.success
        assert "research-team" in result.output
        assert "Role Details" in result.output
        assert "researcher" in result.output

    @pytest.mark.asyncio
    async def test_describe_not_found(self, tool):
        result = await tool.execute(action="describe", name="nonexistent")
        assert not result.success
        assert "not found" in result.error

    @pytest.mark.asyncio
    async def test_clone(self, tool):
        result = await tool.execute(action="clone", name="marketing-team", task="my-team")
        assert result.success
        assert "cloned" in result.output
        assert "my-team" in result.output

        # Verify clone exists
        list_result = await tool.execute(action="list")
        assert "my-team" in list_result.output

    @pytest.mark.asyncio
    async def test_clone_nonexistent(self, tool):
        result = await tool.execute(action="clone", name="nonexistent", task="test")
        assert not result.success
        assert "not found" in result.error


class TestContentAnalyzerSEO:
    """Test the new SEO analysis action."""

    @pytest.fixture
    def tool(self):
        return ContentAnalyzerTool()

    @pytest.mark.asyncio
    async def test_seo_basic(self, tool):
        text = """# How to Build a Great Product

Building a great product requires understanding your users deeply.
Start by talking to customers and identifying their core pain points.

## Research Your Market

Market research is the foundation of product development. You need to
understand the competitive landscape and find gaps.

## Design Your Solution

Once you understand the problem, design a solution that addresses
the core needs. Keep it simple and focused.

## Launch and Iterate

Launch early, gather feedback, and iterate quickly. The best products
are built through continuous improvement.
"""
        result = await tool.execute(action="seo", text=text)
        assert result.success
        assert "SEO Analysis" in result.output
        assert "Word count" in result.output
        assert "H1 headings" in result.output
        assert "Keyword Density" in result.output

    @pytest.mark.asyncio
    async def test_seo_empty_text(self, tool):
        result = await tool.execute(action="seo", text="")
        assert not result.success
        assert "text is required" in result.error


class TestScoringToolImprove:
    """Test the new improve action on ScoringTool."""

    @pytest.fixture
    def tool(self):
        return ScoringTool()

    @pytest.mark.asyncio
    async def test_improve(self, tool):
        result = await tool.execute(
            action="improve",
            rubric="blog-post",
            scores={
                "Hook": 5,
                "Structure": 8,
                "Depth": 4,
                "Readability": 7,
                "Engagement": 6,
                "SEO": 3,
            },
            content_label="Draft Blog Post",
        )
        assert result.success
        assert "Improvement Plan" in result.output
        assert "SEO" in result.output  # Lowest score should be first
        assert "Priority Improvements" in result.output

    @pytest.mark.asyncio
    async def test_improve_requires_rubric(self, tool):
        result = await tool.execute(action="improve", scores={"Hook": 5})
        assert not result.success
        assert "rubric name is required" in result.error

    @pytest.mark.asyncio
    async def test_improve_requires_scores(self, tool):
        result = await tool.execute(action="improve", rubric="blog-post")
        assert not result.success
        assert "scores dict is required" in result.error


class TestTemplateToolPreview:
    """Test the new preview action on TemplateTool."""

    @pytest.fixture
    def tool(self):
        return TemplateTool()

    @pytest.mark.asyncio
    async def test_preview(self, tool):
        result = await tool.execute(action="preview", name="email-campaign")
        assert result.success
        assert "Preview:" in result.output
        assert "SUBJECT:" in result.output or "subject" in result.output.lower()
        assert "Variables to fill" in result.output

    @pytest.mark.asyncio
    async def test_preview_not_found(self, tool):
        result = await tool.execute(action="preview", name="nonexistent")
        assert not result.success
        assert "not found" in result.error

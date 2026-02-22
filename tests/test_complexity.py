"""Tests for core/complexity.py — task complexity assessor."""

import pytest

from core.complexity import (
    _MULTI_DELIVERABLE_MARKERS,
    _SCALE_MARKERS,
    _TEAM_INDICATORS,
    TEAM_TASK_MAP,
    ComplexityAssessment,
    ComplexityAssessor,
)
from core.task_queue import TaskType


class TestComplexityAssessment:
    """Test the ComplexityAssessment dataclass defaults."""

    def test_default_values(self):
        a = ComplexityAssessment()
        assert a.level == "simple"
        assert a.score == 0.0
        assert a.recommended_mode == "single_agent"
        assert a.recommended_team == ""
        assert a.reasoning == ""
        assert a.used_llm is False

    def test_custom_values(self):
        a = ComplexityAssessment(
            level="complex",
            score=0.85,
            recommended_mode="team",
            recommended_team="marketing-team",
            reasoning="Multi-domain campaign",
            used_llm=True,
        )
        assert a.level == "complex"
        assert a.score == 0.85
        assert a.recommended_mode == "team"
        assert a.recommended_team == "marketing-team"
        assert a.used_llm is True


class TestKeywordAssessment:
    """Test keyword-based complexity assessment (no LLM)."""

    def setup_method(self):
        self.assessor = ComplexityAssessor(router=None)

    def test_simple_task(self):
        result = self.assessor._keyword_assess(
            "Update the font size in the header", TaskType.CODING
        )
        assert result.level == "simple"
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""
        assert result.score < 0.3

    def test_simple_content_task(self):
        result = self.assessor._keyword_assess("Draft a short announcement", TaskType.CONTENT)
        assert result.level == "simple"
        assert result.recommended_mode == "single_agent"

    def test_complex_marketing_campaign(self):
        result = self.assessor._keyword_assess(
            "Create a comprehensive marketing campaign with social media strategy, "
            "blog posts, email sequences, and landing page copy for our product launch",
            TaskType.MARKETING,
        )
        assert result.level == "complex"
        assert result.recommended_mode == "team"
        assert result.recommended_team == "marketing-team"
        assert result.score >= 0.6

    def test_complex_multi_domain(self):
        result = self.assessor._keyword_assess(
            "Research our competitors and write a strategy document along with "
            "a full marketing plan and design a presentation",
            TaskType.STRATEGY,
        )
        assert result.level == "complex"
        assert result.recommended_mode == "team"
        assert result.score >= 0.6

    def test_scale_markers_boost_score(self):
        result = self.assessor._keyword_assess(
            "Do a comprehensive end-to-end campaign for our product launch",
            TaskType.MARKETING,
        )
        assert result.score >= 0.3  # scale markers contribute

    def test_multi_deliverable_markers(self):
        result = self.assessor._keyword_assess(
            "Write the blog post and also create social media posts along with "
            "an email template in addition to a press release",
            TaskType.CONTENT,
        )
        assert result.score >= 0.6  # multiple multi-deliverable markers

    def test_team_indicators(self):
        result = self.assessor._keyword_assess(
            "Collaborate on a group effort to review the design from "
            "multiple perspectives and get feedback",
            TaskType.DESIGN,
        )
        assert result.score >= 0.3  # team indicators boost score

    def test_long_description_minor_boost(self):
        short = self.assessor._keyword_assess("Fix bug", TaskType.CODING)
        long_desc = "Fix the bug in the " + "very important " * 50 + "system"
        long_result = self.assessor._keyword_assess(long_desc, TaskType.CODING)
        assert long_result.score >= short.score

    def test_moderate_task(self):
        result = self.assessor._keyword_assess(
            "Write a comprehensive article about cloud computing trends",
            TaskType.CONTENT,
        )
        # "comprehensive" is a scale marker → score gets some boost
        assert result.level in ("simple", "moderate")
        assert result.recommended_mode == "single_agent"


class TestTeamMatching:
    """Test that the correct team is recommended for each task type."""

    def setup_method(self):
        self.assessor = ComplexityAssessor(router=None)

    def test_marketing_maps_to_marketing_team(self):
        team = self.assessor._best_team_for_type(TaskType.MARKETING)
        assert team == "marketing-team"

    def test_content_maps_to_content_team(self):
        team = self.assessor._best_team_for_type(TaskType.CONTENT)
        assert team in ("content-team", "marketing-team")  # content is in both

    def test_design_maps_to_design_review(self):
        team = self.assessor._best_team_for_type(TaskType.DESIGN)
        assert team == "design-review"

    def test_strategy_maps_to_strategy_team(self):
        team = self.assessor._best_team_for_type(TaskType.STRATEGY)
        assert team in ("strategy-team", "research-team")

    def test_research_maps_to_research_team(self):
        team = self.assessor._best_team_for_type(TaskType.RESEARCH)
        assert team in ("research-team", "strategy-team")

    def test_unknown_type_defaults_to_research(self):
        team = self.assessor._best_team_for_type(TaskType.CODING)
        assert team == "research-team"  # coding not in any team map

    def test_all_teams_are_valid(self):
        for team_name in TEAM_TASK_MAP:
            assert isinstance(team_name, str)
            assert len(team_name) > 0


class TestKeywordSignals:
    """Test that keyword signal lists are populated correctly."""

    def test_scale_markers_exist(self):
        assert len(_SCALE_MARKERS) > 5
        assert "campaign" in _SCALE_MARKERS
        assert "comprehensive" in _SCALE_MARKERS

    def test_multi_deliverable_markers_exist(self):
        assert len(_MULTI_DELIVERABLE_MARKERS) > 3
        assert "and also" in _MULTI_DELIVERABLE_MARKERS
        assert "along with" in _MULTI_DELIVERABLE_MARKERS

    def test_team_indicators_exist(self):
        assert len(_TEAM_INDICATORS) > 3
        assert "team" in _TEAM_INDICATORS
        assert "collaborate" in _TEAM_INDICATORS


class TestLLMResponseParsing:
    """Test _parse_response with synthetic LLM outputs."""

    def setup_method(self):
        self.assessor = ComplexityAssessor(router=None)

    def test_parse_valid_response(self):
        response = """{
            "level": "complex",
            "score": 0.8,
            "recommended_mode": "team",
            "recommended_team": "marketing-team",
            "reasoning": "Multi-step campaign"
        }"""
        result = self.assessor._parse_response(response, "test task", TaskType.MARKETING)
        assert result.level == "complex"
        assert result.score == 0.8
        assert result.recommended_mode == "team"
        assert result.recommended_team == "marketing-team"
        assert result.used_llm is True

    def test_parse_simple_response(self):
        response = """{
            "level": "simple",
            "score": 0.2,
            "recommended_mode": "single_agent",
            "recommended_team": "",
            "reasoning": "Simple fix"
        }"""
        result = self.assessor._parse_response(response, "fix bug", TaskType.CODING)
        assert result.level == "simple"
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""

    def test_parse_response_with_markdown_fences(self):
        response = '```json\n{"level": "moderate", "score": 0.4, "recommended_mode": "single_agent", "recommended_team": "", "reasoning": "ok"}\n```'
        result = self.assessor._parse_response(response, "test", TaskType.CONTENT)
        assert result.level == "moderate"
        assert result.recommended_mode == "single_agent"

    def test_parse_invalid_json_falls_back(self):
        response = "not valid json at all"
        result = self.assessor._parse_response(response, "fix bug", TaskType.CODING)
        # Should fall back to keyword assessment
        assert result.used_llm is False

    def test_parse_invalid_level_defaults(self):
        response = '{"level": "extreme", "score": 0.9, "recommended_mode": "team", "recommended_team": "marketing-team", "reasoning": "test"}'
        result = self.assessor._parse_response(response, "test", TaskType.MARKETING)
        assert result.level == "simple"  # invalid level defaults to simple

    def test_parse_invalid_team_name_corrected(self):
        response = '{"level": "complex", "score": 0.8, "recommended_mode": "team", "recommended_team": "nonexistent-team", "reasoning": "test"}'
        result = self.assessor._parse_response(response, "test", TaskType.MARKETING)
        # Invalid team should be corrected to best match for type
        assert result.recommended_team in TEAM_TASK_MAP

    def test_parse_low_score_forces_single_agent(self):
        response = '{"level": "complex", "score": 0.3, "recommended_mode": "team", "recommended_team": "marketing-team", "reasoning": "test"}'
        result = self.assessor._parse_response(response, "test", TaskType.MARKETING)
        # Score < 0.6 should force single_agent
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""

    def test_parse_invalid_mode_defaults(self):
        response = '{"level": "complex", "score": 0.8, "recommended_mode": "multi_agent", "recommended_team": "marketing-team", "reasoning": "test"}'
        result = self.assessor._parse_response(response, "test", TaskType.MARKETING)
        assert result.recommended_mode == "single_agent"

    def test_parse_score_clamped(self):
        response = '{"level": "complex", "score": 1.5, "recommended_mode": "team", "recommended_team": "marketing-team", "reasoning": "test"}'
        result = self.assessor._parse_response(response, "test", TaskType.MARKETING)
        assert result.score == 1.0  # clamped to max


class TestAsyncAssess:
    """Test the async assess() method with no router (keyword fallback)."""

    @pytest.mark.asyncio
    async def test_assess_simple(self):
        assessor = ComplexityAssessor(router=None)
        result = await assessor.assess("Fix the login bug", TaskType.CODING)
        assert result.level == "simple"
        assert result.recommended_mode == "single_agent"
        assert result.used_llm is False

    @pytest.mark.asyncio
    async def test_assess_complex(self):
        assessor = ComplexityAssessor(router=None)
        result = await assessor.assess(
            "Create a comprehensive marketing campaign with social media strategy "
            "and also email sequences along with blog content for the product launch",
            TaskType.MARKETING,
        )
        assert result.level == "complex"
        assert result.recommended_mode == "team"
        assert result.recommended_team != ""
        assert result.used_llm is False

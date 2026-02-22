"""Tests for the context-aware intent classifier."""

import pytest

from core.intent_classifier import ClassificationResult, IntentClassifier, PendingClarification
from core.task_queue import TaskType


class TestKeywordFallback:
    """Test keyword-based classification fallback (no LLM)."""

    @pytest.fixture
    def classifier(self):
        # No router = keyword fallback only
        return IntentClassifier(router=None)

    @pytest.mark.asyncio
    async def test_coding_classification(self, classifier):
        result = await classifier.classify("Fix the login bug in auth.py")
        assert result.task_type in (TaskType.CODING, TaskType.DEBUGGING)
        assert not result.used_llm
        assert result.confidence == 0.6  # Keyword fallback confidence

    @pytest.mark.asyncio
    async def test_marketing_classification(self, classifier):
        result = await classifier.classify("Create a social media campaign for our launch")
        assert result.task_type == TaskType.MARKETING
        assert not result.used_llm

    @pytest.mark.asyncio
    async def test_content_classification(self, classifier):
        result = await classifier.classify("Write an article about productivity")
        assert result.task_type == TaskType.CONTENT
        assert not result.used_llm

    @pytest.mark.asyncio
    async def test_design_classification(self, classifier):
        result = await classifier.classify("Create a wireframe for the settings page")
        assert result.task_type == TaskType.DESIGN
        assert not result.used_llm

    @pytest.mark.asyncio
    async def test_data_analysis_classification(self, classifier):
        result = await classifier.classify("Load the CSV spreadsheet and create a dashboard")
        assert result.task_type == TaskType.DATA_ANALYSIS
        assert not result.used_llm

    @pytest.mark.asyncio
    async def test_strategy_classification(self, classifier):
        result = await classifier.classify("Do a SWOT analysis of our competitors")
        assert result.task_type == TaskType.STRATEGY
        assert not result.used_llm

    @pytest.mark.asyncio
    async def test_no_clarification_on_fallback(self, classifier):
        """Keyword fallback should never request clarification."""
        result = await classifier.classify("help me with something")
        assert not result.needs_clarification
        assert result.clarification_question == ""


class TestClassificationResult:
    """Test ClassificationResult dataclass."""

    def test_defaults(self):
        result = ClassificationResult(task_type=TaskType.CODING)
        assert result.task_type == TaskType.CODING
        assert result.confidence == 1.0
        assert not result.needs_clarification
        assert result.clarification_question == ""
        assert result.suggested_tools == []
        assert result.reasoning == ""
        assert not result.used_llm

    def test_full_construction(self):
        result = ClassificationResult(
            task_type=TaskType.MARKETING,
            confidence=0.85,
            needs_clarification=False,
            clarification_question="",
            suggested_tools=["content_analyzer", "persona"],
            reasoning="Clear marketing request",
            used_llm=True,
        )
        assert result.task_type == TaskType.MARKETING
        assert result.confidence == 0.85
        assert result.used_llm
        assert "content_analyzer" in result.suggested_tools


class TestPendingClarification:
    """Test PendingClarification dataclass."""

    def test_construction(self):
        pending = PendingClarification(
            original_message="Help me with this",
            channel_type="discord",
            channel_id="123",
            sender_id="user1",
            sender_name="TestUser",
            clarification_question="What kind of help do you need?",
            partial_result=ClassificationResult(task_type=TaskType.CODING),
        )
        assert pending.original_message == "Help me with this"
        assert pending.channel_type == "discord"
        assert pending.clarification_question == "What kind of help do you need?"


class TestResponseParsing:
    """Test the LLM response parsing logic."""

    @pytest.fixture
    def classifier(self):
        return IntentClassifier(router=None)

    def test_parse_valid_json(self, classifier):
        response = '{"task_type": "marketing", "confidence": 0.9, "needs_clarification": false, "clarification_question": "", "suggested_tools": ["persona"], "reasoning": "Clear request"}'
        result = classifier._parse_response(response, "test message")
        assert result.task_type == TaskType.MARKETING
        assert result.confidence == 0.9
        assert result.used_llm

    def test_parse_json_with_fences(self, classifier):
        response = '```json\n{"task_type": "content", "confidence": 0.8, "needs_clarification": false, "clarification_question": "", "suggested_tools": [], "reasoning": "Blog request"}\n```'
        result = classifier._parse_response(response, "test message")
        assert result.task_type == TaskType.CONTENT
        assert result.confidence == 0.8

    def test_parse_invalid_json_falls_back(self, classifier):
        response = "I think this is a coding task"
        result = classifier._parse_response(response, "fix the bug")
        # Should fall back to keyword classification
        assert isinstance(result, ClassificationResult)

    def test_parse_unknown_task_type_falls_back(self, classifier):
        response = '{"task_type": "unknown_type", "confidence": 0.9}'
        result = classifier._parse_response(response, "test message")
        # Should fall back to keyword classification
        assert isinstance(result, ClassificationResult)

    def test_low_confidence_forces_clarification(self, classifier):
        response = '{"task_type": "coding", "confidence": 0.3, "needs_clarification": false, "clarification_question": "", "suggested_tools": [], "reasoning": "Unclear"}'
        result = classifier._parse_response(response, "test message")
        assert result.needs_clarification
        assert result.clarification_question != ""

    def test_parse_preserves_suggested_tools(self, classifier):
        response = '{"task_type": "design", "confidence": 0.95, "needs_clarification": false, "clarification_question": "", "suggested_tools": ["image_gen", "persona"], "reasoning": "Clear"}'
        result = classifier._parse_response(response, "test message")
        assert result.suggested_tools == ["image_gen", "persona"]


class TestResourceAllocation:
    """Test resource allocation fields in ClassificationResult and parsing."""

    def test_defaults_to_single_agent(self):
        result = ClassificationResult(task_type=TaskType.CODING)
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""

    def test_team_mode_construction(self):
        result = ClassificationResult(
            task_type=TaskType.MARKETING,
            recommended_mode="team",
            recommended_team="marketing-team",
        )
        assert result.recommended_mode == "team"
        assert result.recommended_team == "marketing-team"

    def test_parse_response_with_team_recommendation(self):
        classifier = IntentClassifier(router=None)
        response = (
            '{"task_type": "marketing", "confidence": 0.9, '
            '"needs_clarification": false, "clarification_question": "", '
            '"suggested_tools": [], "reasoning": "Campaign task", '
            '"recommended_mode": "team", "recommended_team": "marketing-team"}'
        )
        result = classifier._parse_response(response, "Create a full marketing campaign")
        assert result.recommended_mode == "team"
        assert result.recommended_team == "marketing-team"

    def test_parse_response_single_agent(self):
        classifier = IntentClassifier(router=None)
        response = (
            '{"task_type": "coding", "confidence": 0.95, '
            '"needs_clarification": false, "clarification_question": "", '
            '"suggested_tools": [], "reasoning": "Simple fix", '
            '"recommended_mode": "single_agent", "recommended_team": ""}'
        )
        result = classifier._parse_response(response, "Fix the bug")
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""

    def test_parse_invalid_mode_defaults_to_single(self):
        classifier = IntentClassifier(router=None)
        response = (
            '{"task_type": "coding", "confidence": 0.8, '
            '"needs_clarification": false, "clarification_question": "", '
            '"suggested_tools": [], "reasoning": "test", '
            '"recommended_mode": "multi_agent", "recommended_team": ""}'
        )
        result = classifier._parse_response(response, "test")
        assert result.recommended_mode == "single_agent"

    def test_parse_invalid_team_cleared(self):
        classifier = IntentClassifier(router=None)
        response = (
            '{"task_type": "marketing", "confidence": 0.9, '
            '"needs_clarification": false, "clarification_question": "", '
            '"suggested_tools": [], "reasoning": "test", '
            '"recommended_mode": "team", "recommended_team": "fake-team"}'
        )
        result = classifier._parse_response(response, "test")
        # Invalid team name should be cleared
        assert result.recommended_team == ""

    def test_parse_single_agent_clears_team(self):
        classifier = IntentClassifier(router=None)
        response = (
            '{"task_type": "coding", "confidence": 0.9, '
            '"needs_clarification": false, "clarification_question": "", '
            '"suggested_tools": [], "reasoning": "test", '
            '"recommended_mode": "single_agent", "recommended_team": "marketing-team"}'
        )
        result = classifier._parse_response(response, "test")
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""  # cleared because mode is single_agent

    @pytest.mark.asyncio
    async def test_keyword_fallback_defaults_single(self):
        """Keyword fallback always returns single_agent mode."""
        classifier = IntentClassifier(router=None)
        result = await classifier.classify("Create a social media campaign")
        assert result.recommended_mode == "single_agent"
        assert result.recommended_team == ""

    def test_valid_teams_list(self):
        from core.intent_classifier import _VALID_TEAMS

        expected = {
            "research-team",
            "marketing-team",
            "content-team",
            "design-review",
            "strategy-team",
        }
        assert expected == _VALID_TEAMS


class TestLearnerToolRecommendations:
    """Test tool effectiveness tracking in the learner."""

    def test_build_tool_usage_section_empty(self):
        from agents.learner import Learner

        section = Learner._build_tool_usage_section([], "content")
        assert "No tools were called" in section

    def test_build_tool_usage_section_with_calls(self):
        from agents.learner import Learner

        tool_calls = [
            {"name": "content_analyzer", "success": True},
            {"name": "content_analyzer", "success": True},
            {"name": "scoring", "success": True},
            {"name": "web_search", "success": False},
        ]
        section = Learner._build_tool_usage_section(tool_calls, "content")
        assert "content_analyzer" in section
        assert "scoring" in section
        assert "web_search" in section
        assert "Total tool calls: 4" in section
        assert "100%" in section  # content_analyzer success rate
        assert "0%" in section  # web_search success rate

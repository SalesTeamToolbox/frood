"""Tests for the context-aware intent classifier."""

import pytest

from core.intent_classifier import (
    ClassificationResult,
    IntentClassifier,
    PendingClarification,
    ScopeAnalysis,
    ScopeInfo,
)
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
            "code-review-team",
            "dev-team",
            "qa-team",
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


class TestScopeInfo:
    """Test ScopeInfo dataclass serialization."""

    def test_to_dict(self):
        scope = ScopeInfo(
            scope_id="abc123",
            summary="Fix login bug",
            task_type=TaskType.DEBUGGING,
            task_id="abc123",
            started_at=1000.0,
            message_count=3,
        )
        d = scope.to_dict()
        assert d["scope_id"] == "abc123"
        assert d["summary"] == "Fix login bug"
        assert d["task_type"] == "debugging"
        assert d["task_id"] == "abc123"
        assert d["started_at"] == 1000.0
        assert d["message_count"] == 3

    def test_from_dict(self):
        data = {
            "scope_id": "xyz789",
            "summary": "Build dashboard",
            "task_type": "coding",
            "task_id": "xyz789",
            "started_at": 2000.0,
            "message_count": 1,
        }
        scope = ScopeInfo.from_dict(data)
        assert scope.scope_id == "xyz789"
        assert scope.task_type == TaskType.CODING
        assert scope.message_count == 1

    def test_round_trip(self):
        scope = ScopeInfo(
            scope_id="rt1",
            summary="Refactor auth module",
            task_type=TaskType.REFACTORING,
            task_id="rt1",
        )
        restored = ScopeInfo.from_dict(scope.to_dict())
        assert restored.scope_id == scope.scope_id
        assert restored.summary == scope.summary
        assert restored.task_type == scope.task_type
        assert restored.task_id == scope.task_id


class TestScopeAnalysis:
    """Test ScopeAnalysis dataclass."""

    def test_defaults(self):
        analysis = ScopeAnalysis(
            is_continuation=True,
            confidence=0.9,
            new_scope_summary="Same topic",
            reasoning="Related follow-up",
        )
        assert analysis.is_continuation
        assert not analysis.uncertain

    def test_uncertain_flag(self):
        analysis = ScopeAnalysis(
            is_continuation=True,
            confidence=0.3,
            new_scope_summary="Unclear",
            reasoning="Not sure",
            uncertain=True,
        )
        assert analysis.uncertain


class TestScopeDetection:
    """Test scope change detection logic in IntentClassifier."""

    @pytest.fixture
    def classifier(self):
        return IntentClassifier(router=None)

    def test_keyword_scope_check_same_type_is_continuation(self, classifier):
        scope = ScopeInfo(
            scope_id="x",
            summary="Fix login bug",
            task_type=TaskType.DEBUGGING,
            task_id="x",
        )
        result = classifier._keyword_scope_check("Fix the password reset too", scope)
        # "fix" is a debugging keyword — same type as active scope
        assert result.is_continuation

    def test_keyword_scope_check_different_type_is_change(self, classifier):
        scope = ScopeInfo(
            scope_id="x",
            summary="Fix login bug",
            task_type=TaskType.DEBUGGING,
            task_id="x",
        )
        result = classifier._keyword_scope_check(
            "Create a marketing campaign for our launch", scope
        )
        assert not result.is_continuation

    def test_keyword_scope_check_followup_words_are_continuation(self, classifier):
        scope = ScopeInfo(
            scope_id="x",
            summary="Fix login bug",
            task_type=TaskType.DEBUGGING,
            task_id="x",
        )
        # "now" is a continuation signal
        result = classifier._keyword_scope_check("Now deploy it to production", scope)
        assert result.is_continuation

    def test_keyword_scope_check_thanks_is_continuation(self, classifier):
        scope = ScopeInfo(
            scope_id="x",
            summary="Write blog post",
            task_type=TaskType.CONTENT,
            task_id="x",
        )
        result = classifier._keyword_scope_check("Thanks, looks good!", scope)
        assert result.is_continuation

    def test_parse_scope_response_valid(self, classifier):
        response = (
            '{"is_continuation": false, "confidence": 0.9, '
            '"new_scope_summary": "Build dashboard", '
            '"reasoning": "Different topic"}'
        )
        result = classifier._parse_scope_response(response)
        assert not result.is_continuation
        assert result.confidence == 0.9
        assert result.new_scope_summary == "Build dashboard"

    def test_parse_scope_response_with_fences(self, classifier):
        response = (
            "```json\n"
            '{"is_continuation": true, "confidence": 0.85, '
            '"new_scope_summary": "Same topic", '
            '"reasoning": "Related follow-up"}\n'
            "```"
        )
        result = classifier._parse_scope_response(response)
        assert result.is_continuation
        assert result.confidence == 0.85

    def test_parse_scope_response_invalid_json_defaults_to_continuation(self, classifier):
        response = "This is not valid JSON"
        result = classifier._parse_scope_response(response)
        # Should default to continuation (safe default) with uncertain flag
        assert result.is_continuation
        assert result.uncertain

    def test_parse_scope_response_low_confidence(self, classifier):
        response = (
            '{"is_continuation": true, "confidence": 0.3, '
            '"new_scope_summary": "Unclear", "reasoning": "Not sure"}'
        )
        result = classifier._parse_scope_response(response)
        # Low confidence — the caller sets uncertain based on threshold
        assert result.confidence == 0.3

    @pytest.mark.asyncio
    async def test_detect_scope_change_no_router_uses_fallback(self):
        classifier = IntentClassifier(router=None)
        scope = ScopeInfo(
            scope_id="x",
            summary="Fix login bug",
            task_type=TaskType.DEBUGGING,
            task_id="x",
        )
        result = await classifier.detect_scope_change("Create a social media campaign", scope)
        assert isinstance(result, ScopeAnalysis)
        # "social media" → marketing, different from debugging → scope change
        assert not result.is_continuation


class TestChatClassification:
    """Tests covering the chat endpoint classification fix.

    Previously, the /api/chat/send endpoint used keyword-only matching which
    defaulted to CODING for any message without recognised keywords.  The fix
    injects IntentClassifier so the LLM is used instead.
    """

    @pytest.mark.asyncio
    async def test_keyword_fallback_defaults_to_coding_for_unknown(self):
        """Keyword classifier still defaults to CODING when no keywords match."""
        classifier = IntentClassifier(router=None)
        result = await classifier.classify("What time is it?")
        assert result.task_type == TaskType.CODING
        assert not result.used_llm

    @pytest.mark.asyncio
    async def test_llm_classifier_overrides_coding_default(self):
        """LLM router correctly classifies non-coding questions."""
        from unittest.mock import AsyncMock, MagicMock

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=(
                '{"task_type": "research", "confidence": 0.92, '
                '"needs_clarification": false, "clarification_question": "", '
                '"suggested_tools": [], "reasoning": "General question", '
                '"recommended_mode": "single_agent", "recommended_team": "", '
                '"needs_project_setup": false}',
                None,
            )
        )
        classifier = IntentClassifier(router=mock_router)
        result = await classifier.classify("What time is it?")
        assert result.task_type == TaskType.RESEARCH
        assert result.used_llm
        mock_router.complete.assert_called_once()

    @pytest.mark.asyncio
    async def test_llm_classifier_passes_conversation_history(self):
        """Conversation history is forwarded to the LLM."""
        from unittest.mock import AsyncMock, MagicMock

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(
            return_value=(
                '{"task_type": "strategy", "confidence": 0.88, '
                '"needs_clarification": false, "clarification_question": "", '
                '"suggested_tools": [], "reasoning": "Strategy follow-up", '
                '"recommended_mode": "single_agent", "recommended_team": "", '
                '"needs_project_setup": false}',
                None,
            )
        )
        classifier = IntentClassifier(router=mock_router)
        history = [
            {"role": "user", "content": "Tell me about our market position"},
            {"role": "assistant", "content": "Your market position is strong in X..."},
        ]
        result = await classifier.classify("Now build a SWOT plan", conversation_history=history)
        assert result.task_type == TaskType.STRATEGY
        assert result.used_llm
        # Verify the call included messages (system + user with history)
        call_args = mock_router.complete.call_args
        messages = call_args[0][1]  # second positional arg is messages list
        assert len(messages) >= 2  # system prompt + user message with history
        assert any("Conversation history" in m.get("content", "") for m in messages)

    @pytest.mark.asyncio
    async def test_llm_failure_falls_back_to_keyword(self):
        """If the LLM fails, keyword fallback is used."""
        from unittest.mock import AsyncMock, MagicMock

        mock_router = MagicMock()
        mock_router.complete = AsyncMock(side_effect=RuntimeError("LLM unavailable"))
        classifier = IntentClassifier(router=mock_router)
        result = await classifier.classify("Do a SWOT analysis")
        # keyword match: "swot" → strategy
        assert result.task_type == TaskType.STRATEGY
        assert not result.used_llm

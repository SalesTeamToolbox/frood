"""Tests for the L1/L2 agent tier system.

Covers:
- Task tier fields (serialization, defaults)
- L2 routing (availability, admin overrides, API key gating)
- System prompt selection by tier
- L2 context building (L1 result injection)
- Intent classifier conversational detection
- Team tier propagation
"""

import os
from unittest.mock import patch

from agents.agent import (
    GENERAL_ASSISTANT_PROMPT,
    L1_SYSTEM_PROMPTS,
    L2_SYSTEM_PROMPTS,
)
from agents.model_router import L2_ROUTING, ModelRouter
from core.intent_classifier import ClassificationResult
from core.task_queue import Task, TaskType

# ---------------------------------------------------------------------------
# Task tier fields
# ---------------------------------------------------------------------------


class TestTaskTierFields:
    """Test tier-related fields on the Task dataclass."""

    def test_default_tier_is_l1(self):
        task = Task(title="test", description="test")
        assert task.tier == "L1"

    def test_tier_can_be_set_to_l2(self):
        task = Task(title="test", description="test", tier="L2")
        assert task.tier == "L2"

    def test_l1_result_default_empty(self):
        task = Task(title="test", description="test")
        assert task.l1_result == ""

    def test_escalated_from_default_empty(self):
        task = Task(title="test", description="test")
        assert task.escalated_from == ""

    def test_tier_fields_serialize(self):
        task = Task(
            title="test",
            description="test",
            tier="L2",
            l1_result="some L1 output",
            escalated_from="abc123",
        )
        d = task.to_dict()
        assert d["tier"] == "L2"
        assert d["l1_result"] == "some L1 output"
        assert d["escalated_from"] == "abc123"

    def test_tier_fields_deserialize(self):
        data = {
            "title": "test",
            "description": "test",
            "tier": "L2",
            "l1_result": "previous output",
            "escalated_from": "task-xyz",
            "status": "pending",
            "task_type": "coding",
        }
        task = Task.from_dict(data)
        assert task.tier == "L2"
        assert task.l1_result == "previous output"
        assert task.escalated_from == "task-xyz"

    def test_tier_default_on_deserialize_without_field(self):
        """Backward compat: tasks saved before tier was added still work."""
        data = {
            "title": "old task",
            "description": "from before tiers",
            "status": "pending",
            "task_type": "coding",
        }
        task = Task.from_dict(data)
        assert task.tier == "L1"


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------


class TestSystemPrompts:
    """Test that all three prompt dicts exist and are complete."""

    def test_general_assistant_prompt_exists(self):
        assert GENERAL_ASSISTANT_PROMPT
        assert "Agent42" in GENERAL_ASSISTANT_PROMPT
        assert "assistant" in GENERAL_ASSISTANT_PROMPT.lower()

    def test_l1_prompts_cover_all_task_types(self):
        for tt in TaskType:
            assert tt.value in L1_SYSTEM_PROMPTS, f"L1 missing prompt for {tt.value}"

    def test_l2_prompts_cover_all_task_types(self):
        for tt in TaskType:
            assert tt.value in L2_SYSTEM_PROMPTS, f"L2 missing prompt for {tt.value}"

    def test_l1_prompts_are_detailed(self):
        """L1 prompts should be longer (more scaffolding for free models)."""
        for tt in TaskType:
            l1 = L1_SYSTEM_PROMPTS[tt.value]
            assert len(l1) > 100, f"L1 prompt for {tt.value} seems too short"

    def test_l2_prompts_mention_review(self):
        """L2 prompts should reference reviewing/assessing work."""
        review_keywords = {"review", "assess", "verify", "refine", "evaluate"}
        for tt in TaskType:
            l2 = L2_SYSTEM_PROMPTS[tt.value].lower()
            has_keyword = any(kw in l2 for kw in review_keywords)
            assert has_keyword, f"L2 prompt for {tt.value} doesn't mention review"

    def test_l1_and_l2_prompts_differ(self):
        """L1 and L2 should have distinct prompts for every task type."""
        for tt in TaskType:
            assert L1_SYSTEM_PROMPTS[tt.value] != L2_SYSTEM_PROMPTS[tt.value], (
                f"L1 and L2 prompts are identical for {tt.value}"
            )


# ---------------------------------------------------------------------------
# L2 routing
# ---------------------------------------------------------------------------


class TestL2Routing:
    """Test L2 model routing logic."""

    def test_l2_routing_covers_all_task_types(self):
        for tt in TaskType:
            assert tt in L2_ROUTING, f"L2_ROUTING missing {tt.value}"

    def test_l2_routing_has_no_critic(self):
        """L2 is the final reviewer — no critic needed."""
        for tt, routing in L2_ROUTING.items():
            assert routing["critic"] is None, f"L2 has critic for {tt.value}"

    def test_l2_routing_low_iterations(self):
        """L2 does review, not full execution — iterations should be low."""
        for tt, routing in L2_ROUTING.items():
            assert routing["max_iterations"] <= 5, (
                f"L2 iterations too high for {tt.value}: {routing['max_iterations']}"
            )

    @patch.dict(os.environ, {"L2_ENABLED": "false"}, clear=False)
    def test_get_l2_routing_disabled(self):
        """get_l2_routing returns None when L2 is disabled."""
        router = ModelRouter()
        result = router.get_l2_routing(TaskType.CODING)
        assert result is None

    @patch.dict(os.environ, {"L2_TASK_TYPES": "coding,debugging"}, clear=False)
    def test_get_l2_routing_task_type_filter(self):
        """get_l2_routing returns None for ineligible task types."""
        router = ModelRouter()
        # Research is not in the eligible list
        result = router.get_l2_routing(TaskType.RESEARCH)
        assert result is None

    @patch.dict(
        os.environ,
        {"AGENT42_L2_CODING_MODEL": "my-premium-model"},
        clear=False,
    )
    def test_get_l2_routing_per_type_override(self):
        """Per-task-type L2 override takes priority."""
        router = ModelRouter()
        result = router.get_l2_routing(TaskType.CODING)
        assert result is not None
        assert result["primary"] == "my-premium-model"

    @patch.dict(
        os.environ,
        {"AGENT42_L2_MODEL": "global-premium"},
        clear=False,
    )
    def test_get_l2_routing_global_override(self):
        """Global L2 override applies to all task types."""
        router = ModelRouter()
        result = router.get_l2_routing(TaskType.RESEARCH)
        assert result is not None
        assert result["primary"] == "global-premium"

    def test_get_l2_routing_returns_none_without_api_key(self):
        """L2 routing returns None when premium model's API key is not set."""
        router = ModelRouter()
        # By default in tests, no API keys are set, so L2 should be None
        # (unless admin overrides are in env)
        env_clean = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("AGENT42_L2_")
            and k not in ("ANTHROPIC_API_KEY", "OPENAI_API_KEY", "L2_DEFAULT_MODEL")
        }
        with patch.dict(os.environ, env_clean, clear=True):
            result = router.get_l2_routing(TaskType.CODING)
            assert result is None


# ---------------------------------------------------------------------------
# Classification result with is_conversational
# ---------------------------------------------------------------------------


class TestClassificationConversational:
    """Test is_conversational field on ClassificationResult."""

    def test_default_not_conversational(self):
        result = ClassificationResult(task_type=TaskType.CODING)
        assert result.is_conversational is False

    def test_conversational_flag(self):
        result = ClassificationResult(
            task_type=TaskType.EMAIL,
            is_conversational=True,
        )
        assert result.is_conversational is True

    def test_non_conversational_with_task(self):
        result = ClassificationResult(
            task_type=TaskType.CODING,
            is_conversational=False,
            confidence=0.9,
        )
        assert result.is_conversational is False


# ---------------------------------------------------------------------------
# Team tier propagation
# ---------------------------------------------------------------------------


class TestTeamTierPropagation:
    """Test that TeamContext tier defaults to L1."""

    def test_team_context_default_tier(self):
        from tools.team_tool import TeamContext

        ctx = TeamContext(task_description="test task")
        assert ctx.tier == "L1"

    def test_team_context_custom_tier(self):
        from tools.team_tool import TeamContext

        ctx = TeamContext(task_description="test task", tier="L2")
        assert ctx.tier == "L2"

    def test_team_context_build_role_context_includes_project(self):
        from tools.team_tool import TeamContext

        ctx = TeamContext(
            task_description="test task",
            project_id="proj-123",
            tier="L1",
        )
        context = ctx.build_role_context("worker")
        assert "proj-123" in context

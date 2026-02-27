"""
Context-aware intent classifier — LLM-based task type inference.

Replaces pure keyword matching with an LLM call that considers conversation
history, context, and nuance.  Falls back to keyword matching when the LLM
is unavailable or returns low-confidence results.

The classifier also detects ambiguous requests and returns a clarification
question that the channel handler can relay back to the user.
"""

import json
import logging
import time
from dataclasses import dataclass, field

from core.task_queue import TaskType, infer_task_type

logger = logging.getLogger("agent42.intent_classifier")

# Use a fast, free model for classification — latency matters here
CLASSIFIER_MODEL = "or-free-mistral-small"

CLASSIFICATION_PROMPT = """\
You are a task classifier for an AI agent platform.  Given a user message and
optional conversation history, classify the request into one of these task types:

{task_types}

Also determine whether this task needs a single agent or a full team.
Available teams: research-team, marketing-team, content-team, design-review, strategy-team

Respond with ONLY a JSON object (no markdown, no extra text):

{{
  "task_type": "<one of the types above>",
  "confidence": <0.0 to 1.0>,
  "needs_clarification": <true or false>,
  "clarification_question": "<question to ask if ambiguous, or empty string>",
  "suggested_tools": [<list of tool names that might help, or empty>],
  "reasoning": "<one sentence explaining your classification>",
  "recommended_mode": "<single_agent or team>",
  "recommended_team": "<team name if team mode, or empty string>",
  "needs_project_setup": <true or false>,
  "needs_project": <true or false>
}}

Rules:
- confidence >= 0.8 means you are very sure
- confidence 0.5-0.8 means likely but not certain
- confidence < 0.5 means unclear — set needs_clarification=true
- If the message is vague (e.g. "help me with this"), set needs_clarification=true
- Use conversation history to understand context (e.g. if they were discussing
  marketing and say "now write it up", that's a content task)
- Default to "coding" only if the request clearly involves code
- For complex multi-step tasks (campaigns, full projects, comprehensive analysis),
  recommend "team" mode with the appropriate team name
- For focused single-deliverable tasks, recommend "single_agent"
- Only recommend "team" when the task clearly involves multiple domains or steps
- Set needs_project_setup=true when the request describes building a new system,
  platform, or application from scratch, or adding a major feature that spans
  multiple components. Simple bug fixes, small changes, and single-file edits
  do NOT need project setup.
- Set needs_project=true when the request describes an ongoing goal, recurring process,
  or multi-step objective that will span multiple interactions (e.g. "research X daily
  and report", "build me an app", "organize my files and process them"). Simple one-off
  questions, quick lookups, and casual conversation do NOT need a project.
  If needs_project_setup is true, needs_project is also always true.
"""


_VALID_TEAMS = {
    "research-team",
    "marketing-team",
    "content-team",
    "design-review",
    "strategy-team",
}


@dataclass
class ClassificationResult:
    """Result of intent classification."""

    task_type: TaskType
    confidence: float = 1.0
    needs_clarification: bool = False
    clarification_question: str = ""
    suggested_tools: list[str] = field(default_factory=list)
    reasoning: str = ""
    used_llm: bool = False  # True if LLM was used, False if keyword fallback
    # Resource allocation
    recommended_mode: str = "single_agent"  # "single_agent" or "team"
    recommended_team: str = ""  # team name or ""
    # Project interview gating
    needs_project_setup: bool = False  # True if task is complex enough for discovery
    # Smart project grouping — ongoing goals get a project container
    needs_project: bool = False  # True if the request represents an ongoing goal


@dataclass
class PendingClarification:
    """A message waiting for user clarification before becoming a task."""

    original_message: str
    channel_type: str
    channel_id: str
    sender_id: str
    sender_name: str
    clarification_question: str
    partial_result: ClassificationResult
    metadata: dict = field(default_factory=dict)


@dataclass
class ScopeInfo:
    """Represents the active scope of a conversation session.

    Tracks what the user is currently working on so that scope changes
    (e.g. switching from debugging login issues to building a new feature)
    can be detected and routed to separate branches.
    """

    scope_id: str  # Unique ID (matches the task_id that initiated this scope)
    summary: str  # One-line description of what the user is working on
    task_type: TaskType  # The task type of the active scope
    task_id: str  # The task ID currently associated with this scope
    started_at: float = field(default_factory=time.time)
    message_count: int = 0  # How many messages have been in this scope

    def to_dict(self) -> dict:
        return {
            "scope_id": self.scope_id,
            "summary": self.summary,
            "task_type": self.task_type.value,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "message_count": self.message_count,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScopeInfo":
        data = data.copy()
        data["task_type"] = TaskType(data.get("task_type", "coding"))
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


@dataclass
class ScopeAnalysis:
    """Result of scope change detection."""

    is_continuation: bool  # True = same scope, False = new scope
    confidence: float  # 0.0-1.0 confidence in the determination
    new_scope_summary: str  # Summary of what the new message is about
    reasoning: str  # Why the detector made this decision
    uncertain: bool = False  # True = not sure, should ask user


# Words that signal a follow-up to the current task, not a scope change
_CONTINUATION_SIGNALS = {
    "now",
    "also",
    "test",
    "verify",
    "check",
    "thanks",
    "thank you",
    "ok",
    "okay",
    "got it",
    "looks good",
    "lgtm",
    "can you also",
    "what about",
    "one more thing",
    "additionally",
    "next",
    "then",
}

SCOPE_DETECTION_PROMPT = """\
You are a scope change detector for an AI agent platform. A user is in an
ongoing conversation about a specific topic. Given:
1. The current active scope (what they have been working on)
2. Their new message
3. Recent conversation history

Determine if the new message is:
- A CONTINUATION of the current scope (follow-up, clarification, refinement,
  or natural next step of the same work)
- A SCOPE CHANGE (different topic, different codebase area, or unrelated request)

Respond with ONLY a JSON object (no markdown, no extra text):

{{
  "is_continuation": <true or false>,
  "confidence": <0.0 to 1.0>,
  "new_scope_summary": "<one-line summary of what the new message is about>",
  "reasoning": "<one sentence explaining your decision>"
}}

Rules:
- confidence >= 0.8: you are very sure about your determination
- confidence 0.5-0.8: probably correct but not certain
- confidence < 0.5: uncertain
- "Fix the test for the login" after "Fix the login bug" = CONTINUATION
- "Build a dashboard feature" after "Fix the login bug" = SCOPE CHANGE
- "Now test it" after any coding task = CONTINUATION (natural follow-up)
- Trivial messages like "thanks", "ok", "got it" = CONTINUATION
- Questions about the current work = CONTINUATION
- Entirely new feature requests = SCOPE CHANGE
"""


class IntentClassifier:
    """LLM-based task type classification with conversation context.

    Falls back to keyword matching when the LLM call fails.
    """

    def __init__(self, router=None, model: str = CLASSIFIER_MODEL):
        self.router = router
        self.model = model

    async def classify(
        self,
        message: str,
        conversation_history: list[dict] | None = None,
        available_task_types: list[str] | None = None,
    ) -> ClassificationResult:
        """Classify a message into a task type using LLM + context.

        Args:
            message: The user's message to classify.
            conversation_history: Recent messages as OpenAI-format dicts.
            available_task_types: List of valid task type strings.

        Returns:
            ClassificationResult with task_type, confidence, and optional
            clarification question.
        """
        if available_task_types is None:
            available_task_types = [t.value for t in TaskType]

        # Try LLM classification first
        if self.router:
            try:
                return await self._llm_classify(
                    message, conversation_history or [], available_task_types
                )
            except Exception as e:
                logger.warning(f"LLM classification failed, using keyword fallback: {e}")

        # Fallback to keyword matching
        return self._keyword_classify(message)

    async def _llm_classify(
        self,
        message: str,
        conversation_history: list[dict],
        available_task_types: list[str],
    ) -> ClassificationResult:
        """Use LLM for context-aware classification."""
        task_type_list = "\n".join(f"- {t}" for t in available_task_types)
        system_prompt = CLASSIFICATION_PROMPT.format(task_types=task_type_list)

        messages = [{"role": "system", "content": system_prompt}]

        # Include recent conversation history for context (last 10 messages)
        if conversation_history:
            recent = conversation_history[-10:]
            history_text = "\n".join(
                f"[{m.get('role', 'user')}]: {m.get('content', '')[:300]}" for m in recent
            )
            messages.append(
                {
                    "role": "user",
                    "content": (
                        f"Conversation history:\n{history_text}\n\n"
                        f"New message to classify:\n{message}"
                    ),
                }
            )
        else:
            messages.append(
                {
                    "role": "user",
                    "content": f"Message to classify:\n{message}",
                }
            )

        response, _ = await self.router.complete(
            self.model, messages, temperature=0.1, max_tokens=300
        )

        return self._parse_response(response, message)

    def _parse_response(self, response: str, original_message: str) -> ClassificationResult:
        """Parse the LLM's JSON response into a ClassificationResult."""
        # Strip markdown code fences if present
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse classifier response as JSON: {text[:200]}")
            return self._keyword_classify(original_message)

        # Validate task_type
        task_type_str = data.get("task_type", "coding")
        try:
            task_type = TaskType(task_type_str)
        except ValueError:
            logger.warning(f"Unknown task type from classifier: {task_type_str}")
            return self._keyword_classify(original_message)

        confidence = float(data.get("confidence", 0.5))
        needs_clarification = bool(data.get("needs_clarification", False))
        clarification_question = data.get("clarification_question", "")
        suggested_tools = data.get("suggested_tools", [])
        reasoning = data.get("reasoning", "")

        # Resource allocation fields
        recommended_mode = data.get("recommended_mode", "single_agent")
        if recommended_mode not in ("single_agent", "team"):
            recommended_mode = "single_agent"

        recommended_team = data.get("recommended_team", "")
        if recommended_team and recommended_team not in _VALID_TEAMS:
            recommended_team = ""
        # Ensure team is empty when mode is single_agent
        if recommended_mode == "single_agent":
            recommended_team = ""

        # If confidence is very low, force clarification
        if confidence < 0.4 and not needs_clarification:
            needs_clarification = True
            if not clarification_question:
                clarification_question = (
                    "I'm not sure what kind of task you need. Could you provide "
                    "more details about what you'd like me to help with?"
                )

        needs_project_setup = bool(data.get("needs_project_setup", False))
        needs_project = bool(data.get("needs_project", False)) or needs_project_setup

        return ClassificationResult(
            task_type=task_type,
            confidence=confidence,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            suggested_tools=suggested_tools if isinstance(suggested_tools, list) else [],
            reasoning=reasoning,
            used_llm=True,
            recommended_mode=recommended_mode,
            recommended_team=recommended_team,
            needs_project_setup=needs_project_setup,
            needs_project=needs_project,
        )

    @staticmethod
    def _keyword_classify(message: str) -> ClassificationResult:
        """Fallback to keyword-based classification."""
        task_type = infer_task_type(message)
        return ClassificationResult(
            task_type=task_type,
            confidence=0.6,  # Keyword matching is less confident
            needs_clarification=False,
            reasoning="Classified via keyword matching (LLM unavailable)",
            used_llm=False,
        )

    # ------------------------------------------------------------------
    # Scope change detection
    # ------------------------------------------------------------------

    async def detect_scope_change(
        self,
        message: str,
        active_scope: "ScopeInfo",
        conversation_history: list[dict] | None = None,
        confidence_threshold: float = 0.5,
    ) -> ScopeAnalysis:
        """Detect whether a new message changes the conversation scope.

        Args:
            message: The user's new message.
            active_scope: The current active scope for this session.
            conversation_history: Recent conversation messages.
            confidence_threshold: Below this confidence, mark as uncertain.

        Returns:
            ScopeAnalysis indicating continuation or change.
        """
        if self.router:
            try:
                analysis = await self._llm_scope_detect(
                    message, active_scope, conversation_history or []
                )
                if analysis.confidence < confidence_threshold:
                    analysis.uncertain = True
                return analysis
            except Exception as e:
                logger.warning(f"LLM scope detection failed, using keyword fallback: {e}")

        return self._keyword_scope_check(message, active_scope)

    async def _llm_scope_detect(
        self,
        message: str,
        active_scope: "ScopeInfo",
        conversation_history: list[dict],
    ) -> ScopeAnalysis:
        """Use LLM for context-aware scope change detection."""
        system_prompt = SCOPE_DETECTION_PROMPT

        context_parts = [
            f"Current active scope: {active_scope.summary} (type: {active_scope.task_type.value})"
        ]

        if conversation_history:
            recent = conversation_history[-10:]
            history_text = "\n".join(
                f"[{m.get('role', 'user')}]: {m.get('content', '')[:300]}" for m in recent
            )
            context_parts.append(f"Recent conversation:\n{history_text}")

        context_parts.append(f"New message:\n{message}")

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "\n\n".join(context_parts)},
        ]

        response, _ = await self.router.complete(
            self.model, messages, temperature=0.1, max_tokens=200
        )
        return self._parse_scope_response(response)

    def _parse_scope_response(self, response: str) -> ScopeAnalysis:
        """Parse the LLM's JSON response into a ScopeAnalysis."""
        text = response.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse scope response as JSON: {text[:200]}")
            # Default to continuation when parsing fails (safe default)
            return ScopeAnalysis(
                is_continuation=True,
                confidence=0.3,
                new_scope_summary="",
                reasoning="Failed to parse LLM scope response",
                uncertain=True,
            )

        return ScopeAnalysis(
            is_continuation=bool(data.get("is_continuation", True)),
            confidence=float(data.get("confidence", 0.5)),
            new_scope_summary=data.get("new_scope_summary", ""),
            reasoning=data.get("reasoning", ""),
        )

    @staticmethod
    def _keyword_scope_check(message: str, active_scope: "ScopeInfo") -> ScopeAnalysis:
        """Fallback scope check using keyword heuristics.

        Compares the inferred TaskType of the new message against the
        active scope's TaskType.  Continuation signals (e.g. "now",
        "test it", "also") always indicate continuation regardless of
        inferred type.
        """
        lower = message.lower().strip()

        # Check for continuation signals first
        for signal in _CONTINUATION_SIGNALS:
            if signal in lower:
                return ScopeAnalysis(
                    is_continuation=True,
                    confidence=0.7,
                    new_scope_summary=active_scope.summary,
                    reasoning=f"Continuation signal detected: '{signal}'",
                )

        # Compare inferred task type against active scope
        inferred_type = infer_task_type(message)
        if inferred_type == active_scope.task_type:
            return ScopeAnalysis(
                is_continuation=True,
                confidence=0.7,
                new_scope_summary=active_scope.summary,
                reasoning=f"Same task type as active scope: {inferred_type.value}",
            )

        # Different task type — likely a scope change
        return ScopeAnalysis(
            is_continuation=False,
            confidence=0.6,
            new_scope_summary=message[:100],
            reasoning=(
                f"Different task type: {inferred_type.value} vs "
                f"active scope {active_scope.task_type.value}"
            ),
        )

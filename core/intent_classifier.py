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
from dataclasses import dataclass, field

from core.task_queue import TaskType, infer_task_type

logger = logging.getLogger("agent42.intent_classifier")

# Use a fast, free model for classification — latency matters here
CLASSIFIER_MODEL = "or-free-mistral-small"

CLASSIFICATION_PROMPT = """\
You are a task classifier for an AI agent platform.  Given a user message and
optional conversation history, classify the request into one of these task types:

{task_types}

Respond with ONLY a JSON object (no markdown, no extra text):

{{
  "task_type": "<one of the types above>",
  "confidence": <0.0 to 1.0>,
  "needs_clarification": <true or false>,
  "clarification_question": "<question to ask if ambiguous, or empty string>",
  "suggested_tools": [<list of tool names that might help, or empty>],
  "reasoning": "<one sentence explaining your classification>"
}}

Rules:
- confidence >= 0.8 means you are very sure
- confidence 0.5-0.8 means likely but not certain
- confidence < 0.5 means unclear — set needs_clarification=true
- If the message is vague (e.g. "help me with this"), set needs_clarification=true
- Use conversation history to understand context (e.g. if they were discussing
  marketing and say "now write it up", that's a content task)
- Default to "coding" only if the request clearly involves code
"""


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
                f"[{m.get('role', 'user')}]: {m.get('content', '')[:300]}"
                for m in recent
            )
            messages.append({
                "role": "user",
                "content": (
                    f"Conversation history:\n{history_text}\n\n"
                    f"New message to classify:\n{message}"
                ),
            })
        else:
            messages.append({
                "role": "user",
                "content": f"Message to classify:\n{message}",
            })

        response = await self.router.complete(
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

        # If confidence is very low, force clarification
        if confidence < 0.4 and not needs_clarification:
            needs_clarification = True
            if not clarification_question:
                clarification_question = (
                    "I'm not sure what kind of task you need. Could you provide "
                    "more details about what you'd like me to help with?"
                )

        return ClassificationResult(
            task_type=task_type,
            confidence=confidence,
            needs_clarification=needs_clarification,
            clarification_question=clarification_question,
            suggested_tools=suggested_tools if isinstance(suggested_tools, list) else [],
            reasoning=reasoning,
            used_llm=True,
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

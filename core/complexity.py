"""
Task complexity assessor — determines team vs single-agent dispatch.

Analyzes task descriptions to classify complexity as simple, moderate, or
complex, then recommends whether a single agent can handle it or a full
team should be deployed.

Uses LLM-based assessment with keyword fallback, same pattern as
IntentClassifier.
"""

import json
import logging
from dataclasses import dataclass

from core.task_queue import TaskType

logger = logging.getLogger("agent42.complexity")

# Same fast, free model used by IntentClassifier
ASSESSOR_MODEL = "or-free-mistral-small"

# Available team names and what they cover
TEAM_TASK_MAP: dict[str, list[str]] = {
    "marketing-team": ["marketing", "email", "content"],
    "content-team": ["content", "marketing"],
    "research-team": ["research", "strategy"],
    "strategy-team": ["strategy", "research"],
    "design-review": ["design"],
}

# Keywords that signal multi-step / complex tasks
_SCALE_MARKERS = [
    "campaign",
    "full",
    "comprehensive",
    "end-to-end",
    "complete",
    "entire",
    "launch",
    "overhaul",
    "rebrand",
    "multi-channel",
    "omnichannel",
    "integrated",
    "holistic",
]

_MULTI_DELIVERABLE_MARKERS = [
    "and also",
    "plus",
    "along with",
    "in addition",
    "as well as",
    "together with",
    "combined with",
    "followed by",
]

_TEAM_INDICATORS = [
    "team",
    "collaborate",
    "review by",
    "get feedback",
    "coordinate",
    "cross-functional",
    "multiple perspectives",
    "peer review",
    "group effort",
]

ASSESSMENT_PROMPT = """\
You are a task complexity assessor for an AI agent platform.

Given a task description and its classified task type, determine:
1. How complex is this task? (simple, moderate, complex)
2. Should a single agent handle it, or does it need a team?
3. If team, which team? Available teams: {teams}

Respond with ONLY a JSON object (no markdown, no extra text):

{{
  "level": "<simple | moderate | complex>",
  "score": <0.0 to 1.0>,
  "recommended_mode": "<single_agent | team>",
  "recommended_team": "<team name or empty string>",
  "reasoning": "<one sentence>"
}}

Rules:
- simple (score 0.0-0.3): focused, single-deliverable task (e.g., "write a blog post")
- moderate (score 0.3-0.6): multi-part but single-domain (e.g., "write and optimize a blog post")
- complex (score 0.6-1.0): multi-step, multi-domain, or requires coordination
  (e.g., "create a marketing campaign with research, copy, and social media assets")
- Recommend "team" only for complex tasks (score >= 0.6)
- Match the recommended_team to the task's domain:
  {team_descriptions}
- Default to "single_agent" for simple and moderate tasks
"""


@dataclass
class ComplexityAssessment:
    """Result of task complexity assessment."""

    level: str = "simple"  # simple, moderate, complex
    score: float = 0.0  # 0.0-1.0
    recommended_mode: str = "single_agent"  # single_agent or team
    recommended_team: str = ""  # team name or ""
    reasoning: str = ""
    used_llm: bool = False


class ComplexityAssessor:
    """Assesses task complexity to decide team vs single-agent dispatch.

    Uses LLM when available, falls back to keyword heuristics.
    """

    def __init__(self, router=None, model: str = ASSESSOR_MODEL):
        self.router = router
        self.model = model

    async def assess(
        self,
        description: str,
        task_type: TaskType,
    ) -> ComplexityAssessment:
        """Assess task complexity and recommend dispatch mode.

        Args:
            description: Task description text.
            task_type: Already-classified task type.

        Returns:
            ComplexityAssessment with level, recommended_mode, and recommended_team.
        """
        # Try LLM assessment first
        if self.router:
            try:
                return await self._llm_assess(description, task_type)
            except Exception as e:
                logger.warning(f"LLM assessment failed, using keyword fallback: {e}")

        return self._keyword_assess(description, task_type)

    async def _llm_assess(self, description: str, task_type: TaskType) -> ComplexityAssessment:
        """Use LLM for nuanced complexity assessment."""
        teams_list = ", ".join(sorted(TEAM_TASK_MAP.keys()))
        team_desc_parts = []
        for team, types in sorted(TEAM_TASK_MAP.items()):
            team_desc_parts.append(f"  - {team}: handles {', '.join(types)} tasks")
        team_descriptions = "\n".join(team_desc_parts)

        prompt = ASSESSMENT_PROMPT.format(
            teams=teams_list,
            team_descriptions=team_descriptions,
        )

        messages = [
            {"role": "system", "content": prompt},
            {
                "role": "user",
                "content": (f"Task type: {task_type.value}\nTask description: {description}"),
            },
        ]

        response = await self.router.complete(self.model, messages, temperature=0.1, max_tokens=200)

        return self._parse_response(response, description, task_type)

    def _parse_response(
        self, response: str, description: str, task_type: TaskType
    ) -> ComplexityAssessment:
        """Parse LLM JSON response into ComplexityAssessment."""
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
            logger.warning(f"Failed to parse assessment response: {text[:200]}")
            return self._keyword_assess(description, task_type)

        level = data.get("level", "simple")
        if level not in ("simple", "moderate", "complex"):
            level = "simple"

        score = max(0.0, min(1.0, float(data.get("score", 0.0))))
        recommended_mode = data.get("recommended_mode", "single_agent")
        recommended_team = data.get("recommended_team", "")

        # Validate mode
        if recommended_mode not in ("single_agent", "team"):
            recommended_mode = "single_agent"

        # Validate team name
        if recommended_team and recommended_team not in TEAM_TASK_MAP:
            recommended_team = self._best_team_for_type(task_type)

        # Enforce: only complex tasks get teams
        if score < 0.6:
            recommended_mode = "single_agent"
            recommended_team = ""

        return ComplexityAssessment(
            level=level,
            score=score,
            recommended_mode=recommended_mode,
            recommended_team=recommended_team,
            reasoning=data.get("reasoning", ""),
            used_llm=True,
        )

    def _keyword_assess(self, description: str, task_type: TaskType) -> ComplexityAssessment:
        """Fallback keyword-based complexity assessment."""
        lower = description.lower()
        score = 0.0

        # Check for scale markers (+0.15 each, max 0.45)
        scale_hits = sum(1 for m in _SCALE_MARKERS if m in lower)
        score += min(scale_hits * 0.15, 0.45)

        # Check for multi-deliverable markers (+0.2 each, max 0.4)
        multi_hits = sum(1 for m in _MULTI_DELIVERABLE_MARKERS if m in lower)
        score += min(multi_hits * 0.2, 0.4)

        # Check for team indicators (+0.2 each, max 0.4)
        team_hits = sum(1 for m in _TEAM_INDICATORS if m in lower)
        score += min(team_hits * 0.2, 0.4)

        # Check for multi-domain keywords (spans 2+ task types)
        from core.task_queue import _TASK_TYPE_KEYWORDS

        matched_types = set()
        for tt, keywords in _TASK_TYPE_KEYWORDS.items():
            if any(kw in lower for kw in keywords):
                matched_types.add(tt)
        if len(matched_types) >= 2:
            score += 0.3

        # Description length as a minor signal (long = more complex)
        if len(description) > 500:
            score += 0.1
        elif len(description) > 200:
            score += 0.05

        score = min(score, 1.0)

        # Determine level
        if score >= 0.6:
            level = "complex"
            recommended_mode = "team"
            recommended_team = self._best_team_for_type(task_type)
        elif score >= 0.3:
            level = "moderate"
            recommended_mode = "single_agent"
            recommended_team = ""
        else:
            level = "simple"
            recommended_mode = "single_agent"
            recommended_team = ""

        reasoning = (
            f"Keyword assessment: scale={scale_hits}, "
            f"multi-deliverable={multi_hits}, team-indicators={team_hits}, "
            f"cross-domain={len(matched_types)}"
        )

        return ComplexityAssessment(
            level=level,
            score=round(score, 2),
            recommended_mode=recommended_mode,
            recommended_team=recommended_team,
            reasoning=reasoning,
            used_llm=False,
        )

    @staticmethod
    def _best_team_for_type(task_type: TaskType) -> str:
        """Select the best team for a given task type."""
        type_str = task_type.value
        # Direct mapping
        for team_name, covered_types in TEAM_TASK_MAP.items():
            if type_str in covered_types:
                return team_name
        # Default to research-team for unknown types
        return "research-team"

"""
Scoring tool — rubric-based content evaluation.

Define rubrics with weighted criteria, then score content against them.
Agents use this for structured self-evaluation and quality assurance.
"""

import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.scoring")


# Built-in rubrics
BUILTIN_RUBRICS: dict[str, dict] = {
    "marketing-copy": {
        "name": "marketing-copy",
        "description": "Evaluate marketing copy quality",
        "criteria": [
            {"name": "Audience Fit", "weight": 25, "description": "Does the copy speak directly to the target audience?"},
            {"name": "Value Proposition", "weight": 25, "description": "Is the key benefit clear and compelling?"},
            {"name": "Call to Action", "weight": 20, "description": "Is the CTA clear, specific, and motivating?"},
            {"name": "Clarity", "weight": 15, "description": "Is the message easy to understand on first read?"},
            {"name": "Brand Voice", "weight": 15, "description": "Does the tone match the brand guidelines?"},
        ],
    },
    "blog-post": {
        "name": "blog-post",
        "description": "Evaluate blog post quality",
        "criteria": [
            {"name": "Hook", "weight": 15, "description": "Does the opening grab attention?"},
            {"name": "Structure", "weight": 20, "description": "Is the content logically organized with clear headings?"},
            {"name": "Depth", "weight": 20, "description": "Does it provide genuine value and insight?"},
            {"name": "Readability", "weight": 15, "description": "Is it easy to scan and read?"},
            {"name": "Engagement", "weight": 15, "description": "Does it keep the reader interested throughout?"},
            {"name": "SEO", "weight": 15, "description": "Are keywords used naturally? Is metadata addressed?"},
        ],
    },
    "email": {
        "name": "email",
        "description": "Evaluate email effectiveness",
        "criteria": [
            {"name": "Subject Line", "weight": 25, "description": "Is it compelling and under 50 characters?"},
            {"name": "Purpose Clarity", "weight": 25, "description": "Is the purpose immediately obvious?"},
            {"name": "Tone", "weight": 20, "description": "Is the tone appropriate for the context?"},
            {"name": "Brevity", "weight": 15, "description": "Is it concise without losing meaning?"},
            {"name": "Call to Action", "weight": 15, "description": "Is there a clear next step for the reader?"},
        ],
    },
    "research-report": {
        "name": "research-report",
        "description": "Evaluate research report quality",
        "criteria": [
            {"name": "Thoroughness", "weight": 25, "description": "Are all aspects of the topic covered?"},
            {"name": "Source Quality", "weight": 20, "description": "Are sources credible and properly cited?"},
            {"name": "Analysis Depth", "weight": 20, "description": "Is the analysis insightful, not just descriptive?"},
            {"name": "Objectivity", "weight": 15, "description": "Is the analysis balanced and unbiased?"},
            {"name": "Actionability", "weight": 20, "description": "Are recommendations specific and implementable?"},
        ],
    },
    "design-brief": {
        "name": "design-brief",
        "description": "Evaluate design brief quality",
        "criteria": [
            {"name": "Objective Clarity", "weight": 25, "description": "Is the design goal clearly stated?"},
            {"name": "Target Audience", "weight": 20, "description": "Is the audience well-defined?"},
            {"name": "Constraints", "weight": 15, "description": "Are technical and brand constraints specified?"},
            {"name": "Success Criteria", "weight": 20, "description": "How will design success be measured?"},
            {"name": "Reference Material", "weight": 20, "description": "Are examples and inspiration provided?"},
        ],
    },
}


class ScoringTool(Tool):
    """Score content against configurable rubrics with weighted criteria."""

    def __init__(self):
        self._rubrics: dict[str, dict] = dict(BUILTIN_RUBRICS)

    @property
    def name(self) -> str:
        return "scoring"

    @property
    def description(self) -> str:
        return (
            "Score content against rubrics with weighted criteria. "
            "Actions: list (show rubrics), show (view rubric details), "
            "define (create custom rubric), score (evaluate content), "
            "compare (score multiple versions and rank), delete."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["list", "show", "define", "score", "compare", "delete"],
                    "description": "Scoring action",
                },
                "rubric": {
                    "type": "string",
                    "description": "Rubric name",
                    "default": "",
                },
                "criteria": {
                    "type": "array",
                    "description": "Criteria definitions for define action",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "weight": {"type": "number"},
                            "description": {"type": "string"},
                        },
                    },
                    "default": [],
                },
                "description": {
                    "type": "string",
                    "description": "Rubric description (for define)",
                    "default": "",
                },
                "scores": {
                    "type": "object",
                    "description": "Scores per criterion (1-10) for score action: {criterion_name: score}",
                    "default": {},
                },
                "content_label": {
                    "type": "string",
                    "description": "Label for the content being scored",
                    "default": "Content",
                },
                "versions": {
                    "type": "array",
                    "description": "Multiple score sets for compare: [{label, scores}]",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "scores": {"type": "object"},
                        },
                    },
                    "default": [],
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)

        if action == "list":
            return self._list()
        elif action == "show":
            return self._show(kwargs.get("rubric", ""))
        elif action == "define":
            return self._define(kwargs)
        elif action == "score":
            return self._score(kwargs)
        elif action == "compare":
            return self._compare(kwargs)
        elif action == "delete":
            return self._delete(kwargs.get("rubric", ""))
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _list(self) -> ToolResult:
        if not self._rubrics:
            return ToolResult(output="No rubrics defined.")

        lines = ["# Available Rubrics\n"]
        for name, rubric in sorted(self._rubrics.items()):
            builtin = " (built-in)" if name in BUILTIN_RUBRICS else ""
            num_criteria = len(rubric.get("criteria", []))
            lines.append(
                f"- **{name}**{builtin} — {rubric.get('description', '')}\n"
                f"  Criteria: {num_criteria}"
            )
        return ToolResult(output="\n".join(lines))

    def _show(self, rubric_name: str) -> ToolResult:
        if not rubric_name:
            return ToolResult(error="rubric name is required", success=False)
        rubric = self._rubrics.get(rubric_name)
        if not rubric:
            return ToolResult(error=f"Rubric '{rubric_name}' not found", success=False)

        lines = [
            f"# Rubric: {rubric_name}",
            f"\n**Description:** {rubric.get('description', '')}",
            "\n| Criterion | Weight | Description |",
            "|-----------|--------|-------------|",
        ]
        for c in rubric.get("criteria", []):
            lines.append(f"| {c['name']} | {c['weight']}% | {c['description']} |")

        total_weight = sum(c["weight"] for c in rubric.get("criteria", []))
        lines.append(f"\n**Total weight:** {total_weight}%")

        return ToolResult(output="\n".join(lines))

    def _define(self, kwargs: dict) -> ToolResult:
        rubric_name = kwargs.get("rubric", "")
        criteria = kwargs.get("criteria", [])
        description = kwargs.get("description", "")

        if not rubric_name:
            return ToolResult(error="rubric name is required", success=False)
        if not criteria:
            return ToolResult(error="criteria list is required", success=False)

        # Validate weights sum to 100
        total_weight = sum(c.get("weight", 0) for c in criteria)
        if total_weight != 100:
            return ToolResult(
                error=f"Criteria weights must sum to 100 (got {total_weight})",
                success=False,
            )

        self._rubrics[rubric_name] = {
            "name": rubric_name,
            "description": description or f"Custom rubric: {rubric_name}",
            "criteria": criteria,
        }

        return ToolResult(
            output=f"Rubric '{rubric_name}' defined with {len(criteria)} criteria."
        )

    def _score(self, kwargs: dict) -> ToolResult:
        rubric_name = kwargs.get("rubric", "")
        scores = kwargs.get("scores", {})
        label = kwargs.get("content_label", "Content")

        if not rubric_name:
            return ToolResult(error="rubric name is required", success=False)
        rubric = self._rubrics.get(rubric_name)
        if not rubric:
            return ToolResult(error=f"Rubric '{rubric_name}' not found", success=False)
        if not scores:
            return ToolResult(error="scores dict is required", success=False)

        criteria = rubric.get("criteria", [])
        criteria_names = {c["name"] for c in criteria}
        missing = criteria_names - set(scores.keys())
        if missing:
            return ToolResult(
                error=f"Missing scores for: {', '.join(sorted(missing))}",
                success=False,
            )

        return ToolResult(output=self._format_scorecard(rubric, scores, label))

    def _compare(self, kwargs: dict) -> ToolResult:
        rubric_name = kwargs.get("rubric", "")
        versions = kwargs.get("versions", [])

        if not rubric_name:
            return ToolResult(error="rubric name is required", success=False)
        rubric = self._rubrics.get(rubric_name)
        if not rubric:
            return ToolResult(error=f"Rubric '{rubric_name}' not found", success=False)
        if len(versions) < 2:
            return ToolResult(error="at least 2 versions needed for compare", success=False)

        # Score each version
        results = []
        for v in versions:
            label = v.get("label", "Version")
            scores = v.get("scores", {})
            weighted_total = self._calc_weighted_total(rubric, scores)
            results.append((label, scores, weighted_total))

        # Sort by total score descending
        results.sort(key=lambda x: x[2], reverse=True)

        lines = [
            f"# Comparison: {rubric_name}\n",
            "| Rank | Version | Weighted Score |",
            "|------|---------|---------------|",
        ]
        for rank, (label, scores, total) in enumerate(results, 1):
            medal = {1: "🥇", 2: "🥈", 3: "🥉"}.get(rank, f"#{rank}")
            lines.append(f"| {medal} | {label} | {total:.1f} / 10 |")

        lines.append("\n---\n")

        # Detailed per-criterion comparison
        criteria = rubric.get("criteria", [])
        header = "| Criterion | Weight |"
        divider = "|-----------|--------|"
        for label, _, _ in results:
            header += f" {label} |"
            divider += "-------|"

        lines.append(header)
        lines.append(divider)

        for c in criteria:
            row = f"| {c['name']} | {c['weight']}% |"
            for label, scores, _ in results:
                score = scores.get(c["name"], 0)
                row += f" {score}/10 |"
            lines.append(row)

        return ToolResult(output="\n".join(lines))

    def _delete(self, rubric_name: str) -> ToolResult:
        if not rubric_name:
            return ToolResult(error="rubric name is required", success=False)
        if rubric_name not in self._rubrics:
            return ToolResult(error=f"Rubric '{rubric_name}' not found", success=False)
        if rubric_name in BUILTIN_RUBRICS:
            return ToolResult(
                error=f"Cannot delete built-in rubric '{rubric_name}'", success=False
            )
        del self._rubrics[rubric_name]
        return ToolResult(output=f"Rubric '{rubric_name}' deleted.")

    # -- Helpers ---------------------------------------------------------------

    @staticmethod
    def _calc_weighted_total(rubric: dict, scores: dict) -> float:
        total = 0.0
        total_weight = 0
        for c in rubric.get("criteria", []):
            score = scores.get(c["name"], 0)
            try:
                score = float(score)
            except (ValueError, TypeError):
                score = 0
            weight = c.get("weight", 0)
            total += score * weight
            total_weight += weight

        return total / total_weight if total_weight else 0.0

    def _format_scorecard(
        self, rubric: dict, scores: dict, label: str
    ) -> str:
        criteria = rubric.get("criteria", [])
        weighted_total = self._calc_weighted_total(rubric, scores)

        # Grade label
        if weighted_total >= 9:
            grade = "Excellent"
        elif weighted_total >= 7:
            grade = "Good"
        elif weighted_total >= 5:
            grade = "Acceptable"
        elif weighted_total >= 3:
            grade = "Needs Improvement"
        else:
            grade = "Poor"

        lines = [
            f"# Scorecard: {label}",
            f"**Rubric:** {rubric['name']}",
            f"**Overall Score:** {weighted_total:.1f} / 10 ({grade})\n",
            "| Criterion | Weight | Score | Weighted |",
            "|-----------|--------|-------|----------|",
        ]

        weakest = None
        weakest_score = 11

        for c in criteria:
            score = scores.get(c["name"], 0)
            try:
                score = float(score)
            except (ValueError, TypeError):
                score = 0
            weight = c["weight"]
            weighted = score * weight / 100
            bar = "█" * int(score) + "░" * (10 - int(score))
            lines.append(
                f"| {c['name']} | {weight}% | {bar} {score}/10 | {weighted:.1f} |"
            )
            if score < weakest_score:
                weakest_score = score
                weakest = c

        lines.append(f"\n**Weighted Total:** {weighted_total:.1f} / 10")

        if weakest and weakest_score < 7:
            lines.append(
                f"\n**Priority Improvement:** {weakest['name']} "
                f"(scored {weakest_score}/10) — {weakest['description']}"
            )

        return "\n".join(lines)

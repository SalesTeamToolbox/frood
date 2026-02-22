"""
Outline tool — create structured document outlines.

Generates markdown outlines for articles, presentations, reports,
proposals, campaigns, and project plans. Agents can expand sections
and reorder content.
"""

import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.outline")


# Default section templates per document type
_OUTLINE_TEMPLATES: dict[str, list[dict]] = {
    "article": [
        {"heading": "Introduction", "notes": "Hook the reader, state the thesis"},
        {"heading": "Background / Context", "notes": "Set the scene, explain why this matters"},
        {"heading": "Main Point 1", "notes": "Your strongest argument or insight"},
        {"heading": "Main Point 2", "notes": "Supporting evidence or second angle"},
        {"heading": "Main Point 3", "notes": "Additional depth or counterpoint"},
        {"heading": "Practical Takeaways", "notes": "What the reader should do with this info"},
        {"heading": "Conclusion", "notes": "Summarize key points, end with a call to action"},
    ],
    "presentation": [
        {"heading": "Title Slide", "notes": "Title, subtitle, presenter name, date"},
        {"heading": "Agenda", "notes": "3-5 bullet overview of what will be covered"},
        {
            "heading": "Problem / Opportunity",
            "notes": "What challenge or opportunity are we addressing?",
        },
        {"heading": "Current State", "notes": "Where things stand today — data, context"},
        {"heading": "Proposed Solution", "notes": "What we recommend and why"},
        {"heading": "Implementation Plan", "notes": "How we will execute — timeline, resources"},
        {"heading": "Expected Outcomes", "notes": "Metrics, ROI, success criteria"},
        {"heading": "Risks & Mitigations", "notes": "What could go wrong and how we handle it"},
        {"heading": "Next Steps", "notes": "Immediate actions and owners"},
        {"heading": "Q&A", "notes": "Open for discussion"},
    ],
    "report": [
        {
            "heading": "Executive Summary",
            "notes": "High-level overview of findings and recommendations",
        },
        {"heading": "Introduction", "notes": "Purpose, scope, methodology"},
        {"heading": "Background", "notes": "Context and relevant history"},
        {"heading": "Findings", "notes": "Detailed analysis and data"},
        {"heading": "Analysis", "notes": "Interpretation of findings, patterns, insights"},
        {"heading": "Recommendations", "notes": "Actionable next steps based on analysis"},
        {"heading": "Appendix", "notes": "Supporting data, references, methodology details"},
    ],
    "proposal": [
        {"heading": "Executive Summary", "notes": "One-page overview of the proposal"},
        {"heading": "Problem Statement", "notes": "The challenge we are solving"},
        {"heading": "Proposed Solution", "notes": "What we will deliver and how"},
        {"heading": "Scope of Work", "notes": "Deliverables, timeline, milestones"},
        {"heading": "Team & Qualifications", "notes": "Why we are the right team"},
        {"heading": "Budget", "notes": "Cost breakdown and payment terms"},
        {"heading": "Timeline", "notes": "Phase-by-phase schedule"},
        {"heading": "Terms & Conditions", "notes": "Legal and contractual terms"},
    ],
    "campaign": [
        {"heading": "Campaign Overview", "notes": "Objective, target audience, key message"},
        {"heading": "Target Audience", "notes": "Demographics, psychographics, pain points"},
        {"heading": "Key Messages", "notes": "Primary and secondary messages, tone"},
        {"heading": "Channels & Tactics", "notes": "Where and how we reach the audience"},
        {"heading": "Content Plan", "notes": "What content, when, and on which channel"},
        {"heading": "Budget Allocation", "notes": "Spend per channel and tactic"},
        {"heading": "Timeline", "notes": "Campaign phases and key dates"},
        {"heading": "KPIs & Measurement", "notes": "How we measure success"},
    ],
    "project-plan": [
        {"heading": "Project Overview", "notes": "Name, owner, objective, background"},
        {"heading": "Scope", "notes": "In scope, out of scope, assumptions"},
        {"heading": "Deliverables", "notes": "What will be produced"},
        {"heading": "Work Breakdown", "notes": "Major workstreams and tasks"},
        {"heading": "Timeline & Milestones", "notes": "Key dates and dependencies"},
        {"heading": "Resource Plan", "notes": "Team members, roles, availability"},
        {"heading": "Risk Register", "notes": "Identified risks, likelihood, impact, mitigation"},
        {"heading": "Communication Plan", "notes": "Stakeholders, cadence, channels"},
        {"heading": "Success Criteria", "notes": "How we know the project is done and successful"},
    ],
}


class OutlineTool(Tool):
    """Create structured document outlines for any type of content."""

    def __init__(self):
        self._outlines: dict[str, list[dict]] = {}

    @property
    def name(self) -> str:
        return "outline"

    @property
    def description(self) -> str:
        return (
            "Create structured document outlines. "
            "Actions: create (generate outline from type + topic), "
            "expand (add detail to a section), reorder (move sections), "
            "show (display current outline), export (output as markdown), "
            "types (list available outline types)."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "expand", "reorder", "show", "export", "types"],
                    "description": "Outline action",
                },
                "name": {
                    "type": "string",
                    "description": "Outline name/identifier",
                    "default": "default",
                },
                "doc_type": {
                    "type": "string",
                    "enum": list(_OUTLINE_TEMPLATES.keys()),
                    "description": "Document type (for create)",
                    "default": "article",
                },
                "topic": {
                    "type": "string",
                    "description": "Topic or title for the outline",
                    "default": "",
                },
                "section": {
                    "type": "integer",
                    "description": "Section number to expand or target (1-based)",
                    "default": 0,
                },
                "subsections": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Subsection headings to add (for expand)",
                    "default": [],
                },
                "new_order": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "description": "New section order as list of 1-based indices (for reorder)",
                    "default": [],
                },
            },
            "required": ["action"],
        }

    async def execute(self, action: str = "", **kwargs) -> ToolResult:
        if not action:
            return ToolResult(error="action is required", success=False)

        if action == "types":
            return self._list_types()
        elif action == "create":
            return self._create(kwargs)
        elif action == "expand":
            return self._expand(kwargs)
        elif action == "reorder":
            return self._reorder(kwargs)
        elif action == "show":
            return self._show(kwargs.get("name", "default"))
        elif action == "export":
            return self._export(kwargs.get("name", "default"))
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _list_types(self) -> ToolResult:
        lines = ["# Available Outline Types\n"]
        for doc_type, sections in _OUTLINE_TEMPLATES.items():
            headings = [s["heading"] for s in sections]
            lines.append(
                f"- **{doc_type}** ({len(sections)} sections)\n"
                f"  {' → '.join(headings[:5])}{'...' if len(headings) > 5 else ''}"
            )
        return ToolResult(output="\n".join(lines))

    def _create(self, kwargs: dict) -> ToolResult:
        name = kwargs.get("name", "default")
        doc_type = kwargs.get("doc_type", "article")
        topic = kwargs.get("topic", "Untitled")

        template = _OUTLINE_TEMPLATES.get(doc_type)
        if not template:
            return ToolResult(
                error=f"Unknown type: {doc_type}. Available: {', '.join(_OUTLINE_TEMPLATES)}",
                success=False,
            )

        # Deep copy the template
        outline = [
            {"heading": s["heading"], "notes": s["notes"], "subsections": []} for s in template
        ]

        self._outlines[name] = outline

        return ToolResult(
            output=(
                f"Outline '{name}' created for '{topic}' ({doc_type})\n\n"
                + self._render_outline(outline, topic)
            )
        )

    def _expand(self, kwargs: dict) -> ToolResult:
        name = kwargs.get("name", "default")
        section_num = kwargs.get("section", 0)
        subsections = kwargs.get("subsections", [])

        if name not in self._outlines:
            return ToolResult(error=f"Outline '{name}' not found", success=False)
        if not section_num:
            return ToolResult(error="section number is required (1-based)", success=False)
        if not subsections:
            return ToolResult(error="subsections list is required", success=False)

        outline = self._outlines[name]
        idx = section_num - 1
        if idx < 0 or idx >= len(outline):
            return ToolResult(
                error=f"Section {section_num} out of range (1-{len(outline)})",
                success=False,
            )

        outline[idx]["subsections"].extend(subsections)

        return ToolResult(
            output=(
                f"Added {len(subsections)} subsections to section {section_num} "
                f"({outline[idx]['heading']})\n\n" + self._render_outline(outline)
            )
        )

    def _reorder(self, kwargs: dict) -> ToolResult:
        name = kwargs.get("name", "default")
        new_order = kwargs.get("new_order", [])

        if name not in self._outlines:
            return ToolResult(error=f"Outline '{name}' not found", success=False)
        if not new_order:
            return ToolResult(error="new_order is required", success=False)

        outline = self._outlines[name]
        expected = set(range(1, len(outline) + 1))
        provided = set(new_order)

        if provided != expected:
            return ToolResult(
                error=f"new_order must contain all indices 1-{len(outline)} exactly once",
                success=False,
            )

        self._outlines[name] = [outline[i - 1] for i in new_order]

        return ToolResult(
            output=f"Outline '{name}' reordered\n\n" + self._render_outline(self._outlines[name])
        )

    def _show(self, name: str) -> ToolResult:
        if name not in self._outlines:
            if not self._outlines:
                return ToolResult(output="No outlines created yet.")
            available = ", ".join(self._outlines.keys())
            return ToolResult(
                error=f"Outline '{name}' not found. Available: {available}",
                success=False,
            )
        return ToolResult(output=self._render_outline(self._outlines[name]))

    def _export(self, name: str) -> ToolResult:
        if name not in self._outlines:
            return ToolResult(error=f"Outline '{name}' not found", success=False)
        return ToolResult(output=self._render_outline(self._outlines[name], export=True))

    @staticmethod
    def _render_outline(outline: list[dict], topic: str = "", export: bool = False) -> str:
        lines = []
        if topic:
            lines.append(f"# {topic}\n")

        for i, section in enumerate(outline, 1):
            heading = section["heading"]
            notes = section.get("notes", "")
            subsections = section.get("subsections", [])

            if export:
                lines.append(f"## {heading}\n")
                if notes:
                    lines.append(f"_{notes}_\n")
            else:
                lines.append(f"{i}. **{heading}**")
                if notes:
                    lines.append(f"   _{notes}_")

            for sub in subsections:
                if export:
                    lines.append(f"### {sub}\n")
                else:
                    lines.append(f"   - {sub}")

            lines.append("")

        return "\n".join(lines)

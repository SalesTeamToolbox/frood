"""
Persona tool — define and manage audience personas for marketing and content.

Stores personas with demographics, goals, pain points, and preferred tone.
Agents inject persona context into their system prompts via the 'apply' action.
"""

import logging

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.persona")


BUILTIN_PERSONAS: dict[str, dict] = {
    "startup-founder": {
        "name": "startup-founder",
        "title": "Startup Founder / CEO",
        "demographics": "Age 25-45, tech-savvy, fast-paced, resource-constrained",
        "goals": [
            "Scale quickly with limited budget",
            "Find product-market fit",
            "Attract investors and talent",
        ],
        "pain_points": [
            "Too many tools, not enough time",
            "Wearing multiple hats (marketing, sales, product)",
            "Budget constraints limit hiring",
        ],
        "preferred_tone": "Direct, action-oriented, no fluff. Show ROI quickly.",
        "channels": ["Twitter/X", "LinkedIn", "Product Hunt", "Hacker News"],
        "buying_triggers": ["Saves time", "Easy to set up", "Proven results", "Free tier available"],
    },
    "enterprise-buyer": {
        "name": "enterprise-buyer",
        "title": "VP of Engineering / CTO",
        "demographics": "Age 35-55, manages 50+ person team, risk-averse, process-driven",
        "goals": [
            "Reduce operational costs",
            "Improve team productivity",
            "Ensure compliance and security",
        ],
        "pain_points": [
            "Long procurement cycles",
            "Integration with existing stack",
            "Proving ROI to board / CFO",
        ],
        "preferred_tone": "Professional, data-driven, emphasize security and reliability.",
        "channels": ["LinkedIn", "Industry conferences", "Analyst reports", "Email"],
        "buying_triggers": ["Enterprise SLA", "SOC 2 compliance", "Case studies", "Dedicated support"],
    },
    "developer": {
        "name": "developer",
        "title": "Software Developer / Engineer",
        "demographics": "Age 22-40, hands-on builder, values good docs and DX",
        "goals": [
            "Ship features faster",
            "Write cleaner code",
            "Learn new technologies",
        ],
        "pain_points": [
            "Poor documentation",
            "Complex onboarding",
            "Tools that break workflow",
        ],
        "preferred_tone": "Technical, concise, show code examples. Respect their intelligence.",
        "channels": ["GitHub", "Stack Overflow", "Dev.to", "Reddit", "Discord"],
        "buying_triggers": ["Great docs", "Open source", "CLI-first", "Active community"],
    },
    "marketing-manager": {
        "name": "marketing-manager",
        "title": "Marketing Manager / Director",
        "demographics": "Age 28-45, manages campaigns and budget, data-oriented",
        "goals": [
            "Increase lead generation",
            "Improve conversion rates",
            "Demonstrate campaign ROI",
        ],
        "pain_points": [
            "Content creation bottleneck",
            "Measuring attribution across channels",
            "Keeping up with platform changes",
        ],
        "preferred_tone": "Results-focused, use metrics and benchmarks. Visual and engaging.",
        "channels": ["LinkedIn", "Marketing blogs", "Webinars", "Email newsletters"],
        "buying_triggers": ["Analytics dashboard", "A/B testing", "Integrations", "Templates"],
    },
}


class PersonaTool(Tool):
    """Define and manage audience personas for targeted content creation."""

    def __init__(self):
        self._personas: dict[str, dict] = dict(BUILTIN_PERSONAS)

    @property
    def name(self) -> str:
        return "persona"

    @property
    def description(self) -> str:
        return (
            "Manage audience personas for marketing and content tasks. "
            "Actions: create (define persona), list (show all), show (view details), "
            "delete (remove custom), apply (get persona-aware prompt instructions). "
            "Built-in personas: startup-founder, enterprise-buyer, developer, marketing-manager."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["create", "list", "show", "delete", "apply"],
                    "description": "Persona action",
                },
                "name": {
                    "type": "string",
                    "description": "Persona identifier",
                    "default": "",
                },
                "title": {
                    "type": "string",
                    "description": "Persona job title (for create)",
                    "default": "",
                },
                "demographics": {
                    "type": "string",
                    "description": "Demographic description (for create)",
                    "default": "",
                },
                "goals": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of goals (for create)",
                    "default": [],
                },
                "pain_points": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "List of pain points (for create)",
                    "default": [],
                },
                "preferred_tone": {
                    "type": "string",
                    "description": "Preferred communication tone (for create)",
                    "default": "",
                },
                "channels": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Preferred channels (for create)",
                    "default": [],
                },
                "buying_triggers": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "What triggers a purchase decision (for create)",
                    "default": [],
                },
                "task_context": {
                    "type": "string",
                    "description": "Task description for apply action (to tailor instructions)",
                    "default": "",
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
            return self._show(kwargs.get("name", ""))
        elif action == "create":
            return self._create(kwargs)
        elif action == "delete":
            return self._delete(kwargs.get("name", ""))
        elif action == "apply":
            return self._apply(kwargs.get("name", ""), kwargs.get("task_context", ""))
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    def _list(self) -> ToolResult:
        if not self._personas:
            return ToolResult(output="No personas defined.")

        lines = ["# Audience Personas\n"]
        for name, persona in sorted(self._personas.items()):
            builtin = " (built-in)" if name in BUILTIN_PERSONAS else ""
            lines.append(
                f"- **{name}**{builtin} — {persona.get('title', '')}\n"
                f"  {persona.get('demographics', '')}"
            )
        return ToolResult(output="\n".join(lines))

    def _show(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="name is required", success=False)
        persona = self._personas.get(name)
        if not persona:
            return ToolResult(error=f"Persona '{name}' not found", success=False)

        goals = "\n".join(f"  - {g}" for g in persona.get("goals", []))
        pains = "\n".join(f"  - {p}" for p in persona.get("pain_points", []))
        channels = ", ".join(persona.get("channels", []))
        triggers = "\n".join(f"  - {t}" for t in persona.get("buying_triggers", []))

        output = (
            f"# Persona: {name}\n\n"
            f"**Title:** {persona.get('title', '')}\n"
            f"**Demographics:** {persona.get('demographics', '')}\n\n"
            f"**Goals:**\n{goals}\n\n"
            f"**Pain Points:**\n{pains}\n\n"
            f"**Preferred Tone:** {persona.get('preferred_tone', '')}\n\n"
            f"**Channels:** {channels}\n\n"
            f"**Buying Triggers:**\n{triggers}"
        )
        return ToolResult(output=output)

    def _create(self, kwargs: dict) -> ToolResult:
        name = kwargs.get("name", "")
        if not name:
            return ToolResult(error="name is required for create", success=False)
        if not kwargs.get("title"):
            return ToolResult(error="title is required for create", success=False)

        persona = {
            "name": name,
            "title": kwargs.get("title", ""),
            "demographics": kwargs.get("demographics", ""),
            "goals": kwargs.get("goals", []),
            "pain_points": kwargs.get("pain_points", []),
            "preferred_tone": kwargs.get("preferred_tone", ""),
            "channels": kwargs.get("channels", []),
            "buying_triggers": kwargs.get("buying_triggers", []),
        }
        self._personas[name] = persona
        return ToolResult(output=f"Persona '{name}' created with title: {persona['title']}")

    def _delete(self, name: str) -> ToolResult:
        if not name:
            return ToolResult(error="name is required for delete", success=False)
        if name not in self._personas:
            return ToolResult(error=f"Persona '{name}' not found", success=False)
        if name in BUILTIN_PERSONAS:
            return ToolResult(error=f"Cannot delete built-in persona '{name}'", success=False)
        del self._personas[name]
        return ToolResult(output=f"Persona '{name}' deleted.")

    def _apply(self, name: str, task_context: str) -> ToolResult:
        """Generate persona-aware instructions for an agent's system prompt."""
        if not name:
            return ToolResult(error="name is required for apply", success=False)
        persona = self._personas.get(name)
        if not persona:
            return ToolResult(error=f"Persona '{name}' not found", success=False)

        goals_text = "; ".join(persona.get("goals", []))
        pains_text = "; ".join(persona.get("pain_points", []))
        triggers_text = "; ".join(persona.get("buying_triggers", []))

        instructions = (
            f"## Target Audience: {persona.get('title', name)}\n\n"
            f"**Demographics:** {persona.get('demographics', '')}\n\n"
            f"**Writing guidelines based on this persona:**\n"
            f"- Tone: {persona.get('preferred_tone', 'Professional and clear')}\n"
            f"- Address these goals: {goals_text}\n"
            f"- Acknowledge these pain points: {pains_text}\n"
            f"- Include these buying triggers where relevant: {triggers_text}\n"
            f"- Optimize for these channels: {', '.join(persona.get('channels', []))}\n"
        )

        if task_context:
            instructions += f"\n**Task context:** {task_context}\n"

        instructions += (
            "\nKeep this persona in mind for all content, copy, and strategy decisions. "
            "Speak directly to their needs and use language that resonates with their role."
        )

        return ToolResult(output=instructions)

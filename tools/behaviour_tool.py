"""
BehaviourTool — persistent agent behaviour rules.

Inspired by Agent Zero's behaviour adjustment system, this tool lets the
agent (or user) define persistent rules that are automatically injected into
every future system prompt, shaping how the agent communicates and acts.

Rules survive across tasks and sessions — they live in ``memory/behaviour.md``.

Operations:
  adjust  — add or modify behaviour rules via natural language
  reset   — clear all rules (returns to defaults)
  show    — display the current ruleset
"""

import logging
from pathlib import Path

import aiofiles

from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.behaviour")

# Default header written to behaviour.md when it's first created
_BEHAVIOUR_HEADER = """\
# Agent Behaviour Rules

These rules are automatically applied to every task. They define how the agent
communicates, formats its output, and approaches problems.

## Active Rules

"""

# The standard path relative to the memory directory
BEHAVIOUR_FILENAME = "behaviour.md"


class BehaviourTool(Tool):
    """Manage persistent agent behaviour rules stored in memory/behaviour.md.

    Rules are plain English statements that the agent loads into its system
    prompt before every task execution, ensuring consistent behaviour across
    all sessions.

    Examples of rules:
    - "Always respond in British English"
    - "Format all code blocks with language specifiers"
    - "Start every task by listing your planned steps"
    - "Prefer functional programming patterns in Python"
    """

    def __init__(self, memory_dir: str | Path = ".agent42/memory"):
        self._memory_dir = Path(memory_dir)
        self._behaviour_path = self._memory_dir / BEHAVIOUR_FILENAME

    @property
    def name(self) -> str:
        return "behaviour"

    @property
    def description(self) -> str:
        return (
            "Manage persistent agent behaviour rules that apply to all future tasks. "
            "Use 'adjust' to add or modify rules, 'reset' to clear all rules, or "
            "'show' to view the current ruleset. Rules are stored permanently and "
            "automatically applied to every agent system prompt."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "operation": {
                    "type": "string",
                    "enum": ["adjust", "reset", "show"],
                    "description": (
                        "adjust: add or modify behaviour rules; "
                        "reset: clear all rules; "
                        "show: display the current ruleset"
                    ),
                },
                "rule": {
                    "type": "string",
                    "description": (
                        "The new rule or instruction to add/modify (for adjust operation). "
                        "State it as a clear directive, e.g. 'Always use British English' "
                        "or 'Format code with explicit type annotations'."
                    ),
                },
            },
            "required": ["operation"],
        }

    async def execute(
        self,
        operation: str = "show",
        rule: str = "",
        **kwargs,
    ) -> ToolResult:
        if operation == "show":
            return await self._handle_show()
        elif operation == "adjust":
            return await self._handle_adjust(rule)
        elif operation == "reset":
            return await self._handle_reset()
        else:
            return ToolResult(
                output=f"Unknown operation: {operation}. Use adjust, reset, or show.",
                success=False,
            )

    async def _handle_show(self) -> ToolResult:
        """Return the current behaviour rules."""
        content = await self._load()
        if not content.strip():
            return ToolResult(output="No behaviour rules are currently set.")

        rules = self._extract_rules(content)
        if not rules:
            return ToolResult(output="No behaviour rules are currently set.")

        rule_list = "\n".join(f"- {r}" for r in rules)
        return ToolResult(output=f"Current behaviour rules:\n{rule_list}")

    async def _handle_adjust(self, rule: str) -> ToolResult:
        """Add a new rule to the behaviour file."""
        if not rule or not rule.strip():
            return ToolResult(
                output="No rule provided. Specify a rule directive to add.",
                success=False,
            )

        rule = rule.strip()
        # Remove leading list markers if present
        if rule.startswith("- "):
            rule = rule[2:]

        current_content = await self._load()
        existing_rules = self._extract_rules(current_content)

        # Add the new rule (avoid exact duplicates)
        if rule not in existing_rules:
            existing_rules.append(rule)

        await self._save(existing_rules)
        logger.info(f"Behaviour rule added: {rule}")
        return ToolResult(
            output=(f"Behaviour rule added: '{rule}'\nTotal rules: {len(existing_rules)}")
        )

    async def _handle_reset(self) -> ToolResult:
        """Clear all behaviour rules."""
        await self._save([])
        logger.info("Behaviour rules reset")
        return ToolResult(output="All behaviour rules have been cleared.")

    async def _load(self) -> str:
        """Load the behaviour file content, returning empty string if not found."""
        if not self._behaviour_path.exists():
            return ""
        try:
            async with aiofiles.open(self._behaviour_path, encoding="utf-8") as f:
                return await f.read()
        except Exception as e:
            logger.warning(f"Could not read behaviour.md: {e}")
            return ""

    async def _save(self, rules: list[str]) -> None:
        """Save rules to behaviour.md, creating directories as needed."""
        self._memory_dir.mkdir(parents=True, exist_ok=True)
        if not rules:
            content = _BEHAVIOUR_HEADER
        else:
            rule_lines = "\n".join(f"- {r}" for r in rules)
            content = _BEHAVIOUR_HEADER + rule_lines + "\n"
        try:
            async with aiofiles.open(self._behaviour_path, "w", encoding="utf-8") as f:
                await f.write(content)
        except Exception as e:
            logger.error(f"Could not write behaviour.md: {e}")
            raise

    @staticmethod
    def _extract_rules(content: str) -> list[str]:
        """Extract rule lines from the behaviour.md content."""
        rules = []
        for line in content.splitlines():
            stripped = line.strip()
            if stripped.startswith("- "):
                rule = stripped[2:].strip()
                if rule:
                    rules.append(rule)
        return rules


async def load_behaviour_rules(memory_dir: str | Path) -> str:
    """Load behaviour rules and return them as a formatted system prompt section.

    Returns an empty string if no rules are set.
    Used by agent.py to inject rules into every system prompt.
    """
    behaviour_path = Path(memory_dir) / BEHAVIOUR_FILENAME
    if not behaviour_path.exists():
        return ""
    try:
        async with aiofiles.open(behaviour_path, encoding="utf-8") as f:
            content = await f.read()
    except Exception:
        return ""

    rules = BehaviourTool._extract_rules(content)
    if not rules:
        return ""

    rule_lines = "\n".join(f"- {r}" for r in rules)
    return (
        "\n\n## Persistent Behaviour Rules\n\n"
        "The following rules MUST be followed throughout this task:\n\n"
        f"{rule_lines}"
    )

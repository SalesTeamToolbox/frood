"""
Skills loader — discovers and loads SKILL.md-based skill packages.

Skills are directories containing a SKILL.md file with YAML frontmatter
for metadata and Markdown body for agent instructions. This pattern is
inspired by Nanobot's skills system for maximum extensibility.

Directory structure:
    skills/
    ├── builtins/           # Ships with Agent42
    │   ├── github/
    │   │   └── SKILL.md
    │   └── weather/
    │       └── SKILL.md
    └── workspace/          # User-installed skills
        └── my-custom-skill/
            └── SKILL.md
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("agent42.skills")

# YAML frontmatter regex: content between --- delimiters at the start of the file
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


def _parse_yaml_simple(text: str) -> dict:
    """Minimal YAML parser for frontmatter (no PyYAML dependency).

    Handles simple key: value pairs and basic lists.
    """
    result = {}
    current_key = None
    current_list = None

    for line in text.split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # List item under current key
        if stripped.startswith("- ") and current_key:
            if current_list is None:
                current_list = []
            current_list.append(stripped[2:].strip())
            result[current_key] = current_list
            continue

        # Key: value pair
        if ":" in stripped:
            if current_list is not None:
                current_list = None

            key, _, value = stripped.partition(":")
            key = key.strip()
            value = value.strip()

            current_key = key

            if value:
                # Handle booleans
                if value.lower() in ("true", "yes"):
                    result[key] = True
                elif value.lower() in ("false", "no"):
                    result[key] = False
                # Handle inline lists [a, b, c]
                elif value.startswith("[") and value.endswith("]"):
                    items = [v.strip().strip("'\"") for v in value[1:-1].split(",")]
                    result[key] = [i for i in items if i]
                else:
                    result[key] = value.strip("'\"")
            else:
                result[key] = None
                current_list = []

    return result


@dataclass
class Skill:
    """A loaded skill with metadata and instructions."""
    name: str
    description: str = ""
    instructions: str = ""
    always_load: bool = False
    requirements_bins: list[str] = field(default_factory=list)
    requirements_env: list[str] = field(default_factory=list)
    path: Path = field(default_factory=lambda: Path("."))
    task_types: list[str] = field(default_factory=list)  # If set, only loaded for these task types
    system_prompt_override: str = ""  # Replaces default system prompt if set
    metadata: dict = field(default_factory=dict)

    @property
    def summary(self) -> str:
        """One-line summary for skill listings."""
        return f"[{self.name}] {self.description}" if self.description else f"[{self.name}]"


class SkillLoader:
    """Discovers and loads skills from skill directories."""

    def __init__(self, skill_dirs: list[str | Path]):
        self.skill_dirs = [Path(d) for d in skill_dirs]
        self._skills: dict[str, Skill] = {}

    def load_all(self) -> dict[str, Skill]:
        """Scan all skill directories and load SKILL.md files."""
        self._skills.clear()

        for skill_dir in self.skill_dirs:
            if not skill_dir.exists():
                logger.debug(f"Skill directory not found: {skill_dir}")
                continue

            for skill_path in sorted(skill_dir.iterdir()):
                if not skill_path.is_dir():
                    continue

                skill_md = skill_path / "SKILL.md"
                if not skill_md.exists():
                    continue

                try:
                    skill = self._load_skill(skill_md)
                    self._skills[skill.name] = skill
                    logger.info(f"Loaded skill: {skill.name} from {skill_path}")
                except Exception as e:
                    logger.error(f"Failed to load skill from {skill_path}: {e}")

        logger.info(f"Loaded {len(self._skills)} skills total")
        return self._skills

    def get(self, name: str) -> Skill | None:
        """Get a loaded skill by name."""
        return self._skills.get(name)

    def get_for_task_type(self, task_type: str) -> list[Skill]:
        """Get all skills relevant to a task type."""
        result = []
        for skill in self._skills.values():
            if skill.always_load:
                result.append(skill)
            elif skill.task_types and task_type in skill.task_types:
                result.append(skill)
        return result

    def all_skills(self) -> list[Skill]:
        """Return all loaded skills."""
        return list(self._skills.values())

    def build_skill_context(self, task_type: str) -> str:
        """Build combined skill instructions for a task type.

        Always-loaded skills get full content; others get summary only.
        """
        parts = []
        relevant = self.get_for_task_type(task_type)

        if relevant:
            parts.append("## Active Skills\n")
            for skill in relevant:
                parts.append(f"### {skill.name}")
                parts.append(skill.instructions)
                parts.append("")

        # Add summaries of other available skills
        others = [s for s in self._skills.values() if s not in relevant]
        if others:
            parts.append("## Other Available Skills (request via tool call)\n")
            for skill in others:
                parts.append(f"- {skill.summary}")

        return "\n".join(parts)

    @staticmethod
    def _load_skill(skill_md: Path) -> Skill:
        """Parse a SKILL.md file into a Skill object."""
        content = skill_md.read_text(encoding="utf-8")

        # Extract frontmatter
        match = FRONTMATTER_RE.match(content)
        if not match:
            # No frontmatter — use directory name as skill name
            return Skill(
                name=skill_md.parent.name,
                instructions=content.strip(),
                path=skill_md.parent,
            )

        frontmatter = _parse_yaml_simple(match.group(1))
        instructions = content[match.end():].strip()

        # Parse nested 'agent42' or 'nanobot' config block
        agent_config = frontmatter.get("agent42", {})
        if isinstance(agent_config, str):
            agent_config = {}

        return Skill(
            name=frontmatter.get("name", skill_md.parent.name),
            description=frontmatter.get("description", ""),
            instructions=instructions,
            always_load=frontmatter.get("always", False) is True,
            requirements_bins=frontmatter.get("requirements_bins", []),
            requirements_env=frontmatter.get("requirements_env", []),
            path=skill_md.parent,
            task_types=frontmatter.get("task_types", []),
            system_prompt_override=frontmatter.get("system_prompt", ""),
            metadata=frontmatter,
        )

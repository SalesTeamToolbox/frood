"""
Agent Profile Loader — load and apply configurable agent personalities.

Inspired by Agent Zero's agent profile system, profiles provide task-specific
system prompt overlays, skill preferences, and behavioural guidelines that
shape how agents approach their work.

Each profile is a Markdown file with YAML frontmatter:

    ---
    name: developer
    description: Software development focused agent
    preferred_skills: [coding, debugging, testing]
    preferred_task_types: [CODING, DEBUGGING, REFACTORING]
    ---

    # Developer Profile

    Your guiding principles...

Profiles are loaded from:
1. Built-in directory: ``agents/profiles/``
2. Custom directory: configured via ``AGENT_PROFILES_DIR`` env var
"""

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("agent42.profile_loader")

# Built-in profiles directory (alongside this module)
_BUILTIN_PROFILES_DIR = Path(__file__).parent / "profiles"


@dataclass
class AgentProfile:
    """A loaded agent profile with metadata and prompt overlay."""

    name: str
    description: str
    prompt_overlay: str  # The body of the SKILL.md (after frontmatter)
    preferred_skills: list[str] = field(default_factory=list)
    preferred_task_types: list[str] = field(default_factory=list)
    source_path: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "description": self.description,
            "preferred_skills": self.preferred_skills,
            "preferred_task_types": self.preferred_task_types,
            "source_path": self.source_path,
        }


class ProfileLoader:
    """Discovers and loads agent profiles from configured directories."""

    def __init__(self, extra_dirs: list[Path] | None = None):
        self._profiles: dict[str, AgentProfile] = {}
        dirs = [_BUILTIN_PROFILES_DIR]
        if extra_dirs:
            dirs.extend(extra_dirs)
        self._dirs = dirs

    def load_all(self) -> int:
        """Load all profiles from all configured directories.

        Returns the number of profiles loaded.
        """
        loaded = 0
        for directory in self._dirs:
            if not directory.exists():
                continue
            for md_file in sorted(directory.glob("*.md")):
                profile = self._parse_profile(md_file)
                if profile:
                    self._profiles[profile.name] = profile
                    loaded += 1
                    logger.debug(f"Loaded profile: {profile.name} from {md_file}")
        logger.info(f"Profiles loaded: {loaded}")
        return loaded

    def get(self, name: str) -> AgentProfile | None:
        """Get a profile by name, or None if not found."""
        return self._profiles.get(name)

    def get_default(self) -> AgentProfile | None:
        """Get the default profile from settings, or first available."""
        try:
            from core.config import settings

            default_name = settings.agent_default_profile
        except Exception:
            default_name = "developer"

        profile = self._profiles.get(default_name)
        if profile:
            return profile
        # Fall back to first available profile
        if self._profiles:
            return next(iter(self._profiles.values()))
        return None

    def all_profiles(self) -> list[AgentProfile]:
        """Return all loaded profiles."""
        return list(self._profiles.values())

    def _parse_profile(self, path: Path) -> AgentProfile | None:
        """Parse a profile Markdown file with YAML frontmatter."""
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as e:
            logger.warning(f"Could not read profile {path}: {e}")
            return None

        # Split frontmatter from body
        frontmatter, body = _split_frontmatter(content)
        if not frontmatter:
            logger.debug(f"Profile {path} has no frontmatter — skipping")
            return None

        # Parse YAML frontmatter fields manually (avoid adding pyyaml dep)
        meta = _parse_simple_yaml(frontmatter)
        name = meta.get("name", path.stem).strip()
        if not name:
            return None

        description = meta.get("description", "").strip()

        # Parse list fields
        preferred_skills = _parse_yaml_list(meta.get("preferred_skills", ""))
        preferred_task_types = _parse_yaml_list(meta.get("preferred_task_types", ""))

        return AgentProfile(
            name=name,
            description=description,
            prompt_overlay=body.strip(),
            preferred_skills=preferred_skills,
            preferred_task_types=preferred_task_types,
            source_path=str(path),
        )


def _split_frontmatter(content: str) -> tuple[str, str]:
    """Split Markdown content into (frontmatter, body).

    Returns ('', content) if no frontmatter delimiters found.
    """
    if not content.startswith("---"):
        return "", content
    # Find the closing ---
    match = re.search(r"\n---\s*\n", content[3:])
    if not match:
        return "", content
    end = match.end() + 3  # +3 for the opening ---
    frontmatter = content[3 : match.start() + 3].strip()
    body = content[end:]
    return frontmatter, body


def _parse_simple_yaml(text: str) -> dict:
    """Parse a minimal subset of YAML (key: value, key: [a, b, c])."""
    result = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        result[key.strip()] = value.strip()
    return result


def _parse_yaml_list(value: str) -> list[str]:
    """Parse a YAML inline list like '[a, b, c]' or return [] for empty."""
    if not value:
        return []
    # Strip brackets
    value = value.strip()
    if value.startswith("[") and value.endswith("]"):
        value = value[1:-1]
    items = [item.strip().strip("'\"") for item in value.split(",")]
    return [item for item in items if item]

"""Tests for Phase 3: Skills framework."""

import tempfile
from pathlib import Path

from skills.loader import Skill, SkillLoader, _parse_yaml_simple


class TestYamlParser:
    def test_simple_key_value(self):
        result = _parse_yaml_simple("name: my-skill\ndescription: A test skill")
        assert result["name"] == "my-skill"
        assert result["description"] == "A test skill"

    def test_boolean_values(self):
        result = _parse_yaml_simple("always: true\nenabled: false")
        assert result["always"] is True
        assert result["enabled"] is False

    def test_inline_list(self):
        result = _parse_yaml_simple("task_types: [coding, research]")
        assert result["task_types"] == ["coding", "research"]

    def test_multiline_list(self):
        result = _parse_yaml_simple("bins:\n- git\n- python")
        assert result["bins"] == ["git", "python"]

    def test_quoted_values(self):
        result = _parse_yaml_simple("name: 'quoted-name'")
        assert result["name"] == "quoted-name"


class TestSkillLoader:
    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()

    def _create_skill(self, name: str, content: str):
        skill_dir = Path(self.tmpdir) / name
        skill_dir.mkdir(parents=True)
        (skill_dir / "SKILL.md").write_text(content)

    def test_load_skill_with_frontmatter(self):
        self._create_skill(
            "test-skill",
            """---
name: test-skill
description: A test skill
always: true
task_types: [coding]
---

# Test Skill

Instructions here.
""",
        )
        loader = SkillLoader([self.tmpdir])
        skills = loader.load_all()
        assert "test-skill" in skills
        assert skills["test-skill"].description == "A test skill"
        assert skills["test-skill"].always_load is True
        assert skills["test-skill"].task_types == ["coding"]
        assert "Instructions here" in skills["test-skill"].instructions

    def test_load_skill_without_frontmatter(self):
        self._create_skill("simple", "# Simple Skill\n\nJust instructions.")
        loader = SkillLoader([self.tmpdir])
        skills = loader.load_all()
        assert "simple" in skills
        assert "Just instructions" in skills["simple"].instructions

    def test_get_for_task_type(self):
        self._create_skill(
            "code-skill",
            """---
name: code-skill
description: Coding helper
task_types: [coding]
---
Code instructions.
""",
        )
        self._create_skill(
            "always-skill",
            """---
name: always-skill
description: Always loaded
always: true
---
Always instructions.
""",
        )
        loader = SkillLoader([self.tmpdir])
        loader.load_all()

        coding_skills = loader.get_for_task_type("coding")
        assert len(coding_skills) == 2  # always + coding

        research_skills = loader.get_for_task_type("research")
        assert len(research_skills) == 1  # only always

    def test_build_skill_context(self):
        self._create_skill(
            "ctx-skill",
            """---
name: ctx-skill
description: Context test
always: true
---
Context instructions.
""",
        )
        loader = SkillLoader([self.tmpdir])
        loader.load_all()

        context = loader.build_skill_context("coding")
        assert "ctx-skill" in context
        assert "Context instructions" in context

    def test_empty_directory(self):
        loader = SkillLoader(["/nonexistent/path"])
        skills = loader.load_all()
        assert len(skills) == 0

    def test_skill_summary(self):
        skill = Skill(name="test", description="A test")
        assert skill.summary == "[test] A test"

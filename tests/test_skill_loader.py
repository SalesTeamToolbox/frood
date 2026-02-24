"""Tests for skills/loader.py — skill discovery, loading, and extensions."""

from pathlib import Path

from skills.loader import SkillLoader, _parse_yaml_simple


def _write_skill(skill_dir: Path, name: str, content: str) -> Path:
    """Helper to create a skill directory with SKILL.md."""
    d = skill_dir / name
    d.mkdir(parents=True, exist_ok=True)
    md = d / "SKILL.md"
    md.write_text(content)
    return d


class TestParseYamlSimple:
    def test_basic_key_value(self):
        result = _parse_yaml_simple("name: test\ndescription: A test skill")
        assert result["name"] == "test"
        assert result["description"] == "A test skill"

    def test_boolean_values(self):
        result = _parse_yaml_simple("always: true\nother: false")
        assert result["always"] is True
        assert result["other"] is False

    def test_inline_list(self):
        result = _parse_yaml_simple("task_types: [coding, debugging]")
        assert result["task_types"] == ["coding", "debugging"]

    def test_multiline_list(self):
        result = _parse_yaml_simple("items:\n- alpha\n- beta\n- gamma")
        assert result["items"] == ["alpha", "beta", "gamma"]


class TestSkillLoader:
    def test_load_single_skill(self, tmp_path):
        _write_skill(
            tmp_path,
            "test-skill",
            "---\nname: test-skill\ndescription: A test\ntask_types: [coding]\n---\n\n# Test\n\nHello world.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        assert "test-skill" in skills
        assert skills["test-skill"].task_types == ["coding"]
        assert "Hello world" in skills["test-skill"].instructions

    def test_no_frontmatter(self, tmp_path):
        _write_skill(tmp_path, "plain", "# Plain Skill\n\nJust markdown.")
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        assert "plain" in skills
        assert skills["plain"].name == "plain"

    def test_get_for_task_type(self, tmp_path):
        _write_skill(
            tmp_path,
            "code-skill",
            "---\nname: code-skill\ntask_types: [coding]\n---\n\nInstructions.",
        )
        _write_skill(
            tmp_path,
            "design-skill",
            "---\nname: design-skill\ntask_types: [design]\n---\n\nDesign instructions.",
        )
        loader = SkillLoader([tmp_path])
        loader.load_all()
        coding = loader.get_for_task_type("coding")
        assert len(coding) == 1
        assert coding[0].name == "code-skill"

    def test_always_load(self, tmp_path):
        _write_skill(
            tmp_path,
            "always-skill",
            "---\nname: always-skill\nalways: true\n---\n\nAlways loaded.",
        )
        loader = SkillLoader([tmp_path])
        loader.load_all()
        result = loader.get_for_task_type("anything")
        assert len(result) == 1
        assert result[0].name == "always-skill"

    def test_multiple_directories(self, tmp_path):
        dir1 = tmp_path / "dir1"
        dir2 = tmp_path / "dir2"
        _write_skill(dir1, "skill-a", "---\nname: skill-a\n---\n\nA.")
        _write_skill(dir2, "skill-b", "---\nname: skill-b\n---\n\nB.")
        loader = SkillLoader([dir1, dir2])
        skills = loader.load_all()
        assert "skill-a" in skills
        assert "skill-b" in skills

    def test_later_directory_overrides(self, tmp_path):
        dir1 = tmp_path / "builtins"
        dir2 = tmp_path / "workspace"
        _write_skill(dir1, "my-skill", "---\nname: my-skill\n---\n\nOriginal.")
        _write_skill(dir2, "my-skill", "---\nname: my-skill\n---\n\nOverride.")
        loader = SkillLoader([dir1, dir2])
        skills = loader.load_all()
        assert "Override" in skills["my-skill"].instructions

    def test_nonexistent_directory(self, tmp_path):
        loader = SkillLoader([tmp_path / "nonexistent"])
        skills = loader.load_all()
        assert len(skills) == 0

    def test_build_skill_context(self, tmp_path):
        _write_skill(
            tmp_path,
            "active-skill",
            "---\nname: active-skill\ntask_types: [coding]\n---\n\nActive instructions.",
        )
        _write_skill(
            tmp_path,
            "other-skill",
            "---\nname: other-skill\ndescription: Other desc\ntask_types: [design]\n---\n\nOther.",
        )
        loader = SkillLoader([tmp_path])
        loader.load_all()
        context = loader.build_skill_context("coding")
        assert "Active instructions" in context
        assert "[other-skill]" in context


class TestSkillExtensions:
    """Tests for the extends: frontmatter field and skill merging."""

    def test_basic_extension(self, tmp_path):
        """Extension merges instructions into base skill."""
        _write_skill(
            tmp_path,
            "base-skill",
            "---\nname: base-skill\ntask_types: [coding]\n---\n\n# Base\n\nBase content.",
        )
        _write_skill(
            tmp_path,
            "ext-skill",
            "---\nname: ext-skill\nextends: base-skill\n---\n\n# Extension\n\nExtended content.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()

        # Extension should be merged into base
        assert "ext-skill" not in skills
        assert "base-skill" in skills
        base = skills["base-skill"]
        assert "Base content" in base.instructions
        assert "Extended content" in base.instructions
        assert "Extension: ext-skill" in base.instructions

    def test_task_types_union(self, tmp_path):
        """Extension adds its task_types to the base."""
        _write_skill(
            tmp_path,
            "base",
            "---\nname: base\ntask_types: [coding]\n---\n\nBase.",
        )
        _write_skill(
            tmp_path,
            "ext",
            "---\nname: ext\nextends: base\ntask_types: [design, marketing]\n---\n\nExt.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        assert sorted(skills["base"].task_types) == ["coding", "design", "marketing"]

    def test_description_override(self, tmp_path):
        """Extension description overrides base if non-empty."""
        _write_skill(
            tmp_path,
            "base",
            "---\nname: base\ndescription: Original desc\n---\n\nBase.",
        )
        _write_skill(
            tmp_path,
            "ext",
            "---\nname: ext\nextends: base\ndescription: Better desc\n---\n\nExt.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        assert skills["base"].description == "Better desc"

    def test_empty_description_keeps_base(self, tmp_path):
        """Extension with empty description preserves base description."""
        _write_skill(
            tmp_path,
            "base",
            "---\nname: base\ndescription: Original\n---\n\nBase.",
        )
        _write_skill(
            tmp_path,
            "ext",
            "---\nname: ext\nextends: base\n---\n\nExt.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        assert skills["base"].description == "Original"

    def test_always_load_propagates(self, tmp_path):
        """If extension has always: true, base becomes always-loaded."""
        _write_skill(
            tmp_path,
            "base",
            "---\nname: base\nalways: false\n---\n\nBase.",
        )
        _write_skill(
            tmp_path,
            "ext",
            "---\nname: ext\nextends: base\nalways: true\n---\n\nExt.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        assert skills["base"].always_load is True

    def test_nonexistent_base(self, tmp_path):
        """Extension of nonexistent base is kept as standalone skill."""
        _write_skill(
            tmp_path,
            "orphan",
            "---\nname: orphan\nextends: does-not-exist\n---\n\nOrphan.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        # Should still be in the registry as a standalone skill
        assert "orphan" in skills

    def test_multiple_extensions_same_base(self, tmp_path):
        """Multiple extensions merge into the same base skill."""
        _write_skill(
            tmp_path,
            "base",
            "---\nname: base\ntask_types: [coding]\n---\n\nBase content.",
        )
        _write_skill(
            tmp_path,
            "ext-a",
            "---\nname: ext-a\nextends: base\ntask_types: [design]\n---\n\nExtension A.",
        )
        _write_skill(
            tmp_path,
            "ext-b",
            "---\nname: ext-b\nextends: base\ntask_types: [marketing]\n---\n\nExtension B.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()

        assert "ext-a" not in skills
        assert "ext-b" not in skills
        base = skills["base"]
        assert "Base content" in base.instructions
        assert "Extension A" in base.instructions
        assert "Extension B" in base.instructions
        assert "coding" in base.task_types
        assert "design" in base.task_types
        assert "marketing" in base.task_types

    def test_requirements_union(self, tmp_path):
        """Extension requirements are merged with base requirements."""
        _write_skill(
            tmp_path,
            "base",
            "---\nname: base\nrequirements_bins:\n- git\nrequirements_env:\n- API_KEY\n---\n\nBase.",
        )
        _write_skill(
            tmp_path,
            "ext",
            "---\nname: ext\nextends: base\nrequirements_bins:\n- docker\nrequirements_env:\n- SECRET\n---\n\nExt.",
        )
        loader = SkillLoader([tmp_path])
        skills = loader.load_all()
        assert "git" in skills["base"].requirements_bins
        assert "docker" in skills["base"].requirements_bins
        assert "API_KEY" in skills["base"].requirements_env
        assert "SECRET" in skills["base"].requirements_env

    def test_extension_across_directories(self, tmp_path):
        """Extension in workspace dir extends builtin in builtins dir."""
        builtins = tmp_path / "builtins"
        workspace = tmp_path / "workspace"
        _write_skill(
            builtins,
            "seo",
            "---\nname: seo\ntask_types: [content, marketing]\n---\n\n# SEO\n\nBase SEO content.",
        )
        _write_skill(
            workspace,
            "brand-seo",
            "---\nname: brand-seo\nextends: seo\ntask_types: [design]\n---\n\n# Brand SEO\n\nCustom branding rules.",
        )
        loader = SkillLoader([builtins, workspace])
        skills = loader.load_all()

        assert "brand-seo" not in skills
        assert "seo" in skills
        seo = skills["seo"]
        assert "Base SEO content" in seo.instructions
        assert "Custom branding rules" in seo.instructions
        assert "design" in seo.task_types
        assert "content" in seo.task_types


class TestSkillLoaderToggle:
    """Tests for runtime enable/disable of skills."""

    def test_is_enabled_default(self, tmp_path):
        _write_skill(tmp_path, "s", "---\nname: s\ntask_types: [coding]\n---\n\nInstructions.")
        loader = SkillLoader([tmp_path])
        loader.load_all()
        assert loader.is_enabled("s") is True

    def test_set_enabled_disable(self, tmp_path):
        _write_skill(tmp_path, "s", "---\nname: s\ntask_types: [coding]\n---\n\nInstructions.")
        loader = SkillLoader([tmp_path])
        loader.load_all()
        result = loader.set_enabled("s", False)
        assert result is True
        assert loader.is_enabled("s") is False

    def test_set_enabled_reenable(self, tmp_path):
        _write_skill(tmp_path, "s", "---\nname: s\ntask_types: [coding]\n---\n\nInstructions.")
        loader = SkillLoader([tmp_path])
        loader.load_all()
        loader.set_enabled("s", False)
        loader.set_enabled("s", True)
        assert loader.is_enabled("s") is True

    def test_set_enabled_unknown_returns_false(self, tmp_path):
        loader = SkillLoader([tmp_path])
        loader.load_all()
        assert loader.set_enabled("does-not-exist", False) is False

    def test_disabled_skill_excluded_from_task_type(self, tmp_path):
        _write_skill(tmp_path, "s1", "---\nname: s1\ntask_types: [coding]\n---\n\nS1.")
        _write_skill(tmp_path, "s2", "---\nname: s2\ntask_types: [coding]\n---\n\nS2.")
        loader = SkillLoader([tmp_path])
        loader.load_all()
        loader.set_enabled("s1", False)
        active = loader.get_for_task_type("coding")
        assert len(active) == 1
        assert active[0].name == "s2"

    def test_disabled_always_load_skill_excluded(self, tmp_path):
        _write_skill(tmp_path, "always", "---\nname: always\nalways: true\n---\n\nAlways.")
        loader = SkillLoader([tmp_path])
        loader.load_all()
        loader.set_enabled("always", False)
        active = loader.get_for_task_type("anything")
        assert len(active) == 0

    def test_all_skills_includes_disabled(self, tmp_path):
        _write_skill(tmp_path, "s", "---\nname: s\ntask_types: [coding]\n---\n\nInstructions.")
        loader = SkillLoader([tmp_path])
        loader.load_all()
        loader.set_enabled("s", False)
        all_skills = loader.all_skills()
        assert len(all_skills) == 1

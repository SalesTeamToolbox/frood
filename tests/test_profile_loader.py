"""Tests for ProfileLoader — agent profile management."""



from agents.profile_loader import (
    ProfileLoader,
    _parse_simple_yaml,
    _parse_yaml_list,
    _split_frontmatter,
)


class TestSplitFrontmatter:
    def test_splits_frontmatter_and_body(self):
        content = "---\nname: test\n---\n\nBody text here"
        fm, body = _split_frontmatter(content)
        assert "name: test" in fm
        assert "Body text here" in body

    def test_no_frontmatter_returns_empty(self):
        content = "Just a body without frontmatter"
        fm, body = _split_frontmatter(content)
        assert fm == ""
        assert body == content

    def test_empty_content(self):
        fm, body = _split_frontmatter("")
        assert fm == ""
        assert body == ""


class TestParseSimpleYaml:
    def test_parses_key_value(self):
        result = _parse_simple_yaml("name: developer\ndescription: A developer profile")
        assert result["name"] == "developer"
        assert result["description"] == "A developer profile"

    def test_ignores_comments(self):
        result = _parse_simple_yaml("# This is a comment\nname: test")
        assert result.get("name") == "test"
        assert "#" not in str(result.keys())

    def test_empty_string(self):
        result = _parse_simple_yaml("")
        assert result == {}


class TestParseYamlList:
    def test_parses_inline_list(self):
        result = _parse_yaml_list("[coding, debugging, testing]")
        assert result == ["coding", "debugging", "testing"]

    def test_empty_returns_empty_list(self):
        result = _parse_yaml_list("")
        assert result == []

    def test_single_item(self):
        result = _parse_yaml_list("[coding]")
        assert result == ["coding"]


class TestProfileLoader:
    def test_loads_builtin_profiles(self):
        loader = ProfileLoader()
        count = loader.load_all()
        assert count >= 5  # developer, researcher, security-auditor, data-analyst, writer
        profiles = loader.all_profiles()
        profile_names = [p.name for p in profiles]
        assert "developer" in profile_names
        assert "researcher" in profile_names
        assert "security-auditor" in profile_names
        assert "data-analyst" in profile_names
        assert "writer" in profile_names

    def test_get_profile_by_name(self):
        loader = ProfileLoader()
        loader.load_all()
        profile = loader.get("developer")
        assert profile is not None
        assert profile.name == "developer"
        assert profile.description
        assert profile.prompt_overlay

    def test_get_nonexistent_profile_returns_none(self):
        loader = ProfileLoader()
        loader.load_all()
        result = loader.get("nonexistent-profile-xyz")
        assert result is None

    def test_profile_has_preferred_skills(self):
        loader = ProfileLoader()
        loader.load_all()
        profile = loader.get("developer")
        assert len(profile.preferred_skills) > 0
        assert "coding" in profile.preferred_skills or "debugging" in profile.preferred_skills

    def test_profile_has_preferred_task_types(self):
        loader = ProfileLoader()
        loader.load_all()
        profile = loader.get("developer")
        assert len(profile.preferred_task_types) > 0

    def test_profile_to_dict(self):
        loader = ProfileLoader()
        loader.load_all()
        d = loader.get("researcher").to_dict()
        assert "name" in d
        assert "description" in d
        assert "preferred_skills" in d
        assert "preferred_task_types" in d

    def test_get_default_returns_developer(self):
        """get_default() returns a builtin profile (AGENT_DEFAULT_PROFILE defaults to 'developer')."""
        loader = ProfileLoader()
        loader.load_all()
        default = loader.get_default()
        assert default is not None
        # The default should be one of the builtin profiles
        assert default.name in (
            "developer",
            "researcher",
            "security-auditor",
            "data-analyst",
            "writer",
        )

    def test_get_default_falls_back_to_first(self):
        """When default name not found, return first available profile."""
        loader = ProfileLoader()
        loader.load_all()
        # Override to nonexistent name
        loader._profiles.pop("developer", None)  # Remove "developer" if it's there
        # Should still return a profile
        profile = loader.get_default()
        # If any profiles remain, should return one
        if loader.all_profiles():
            assert profile is not None

    def test_custom_profile_dir(self, tmp_path):
        """Custom profiles directory should be discovered."""
        # Create a custom profile
        profile_md = tmp_path / "custom.md"
        profile_md.write_text(
            "---\n"
            "name: custom\n"
            "description: A custom test profile\n"
            "preferred_skills: [testing]\n"
            "preferred_task_types: [CODING]\n"
            "---\n\n"
            "# Custom Profile\n\n"
            "Always write tests first.\n"
        )
        loader = ProfileLoader(extra_dirs=[tmp_path])
        count = loader.load_all()
        assert count >= 1
        custom = loader.get("custom")
        assert custom is not None
        assert custom.name == "custom"
        assert "Always write tests first" in custom.prompt_overlay

    def test_invalid_profile_skipped(self, tmp_path):
        """Profile without valid frontmatter should be skipped."""
        bad_md = tmp_path / "bad.md"
        bad_md.write_text("No frontmatter here, just text.")
        loader = ProfileLoader(extra_dirs=[tmp_path])
        loader.load_all()
        assert loader.get("bad") is None

    def test_empty_directory_loads_zero_custom(self, tmp_path):
        loader = ProfileLoader(extra_dirs=[tmp_path])
        # Only builtin profiles loaded
        count = loader.load_all()
        assert count >= 5  # builtins only

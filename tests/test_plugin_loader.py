"""Tests for tools/plugin_loader.py — custom tool auto-discovery and extensions."""

import textwrap

import pytest

from tools.base import ExtendedTool, Tool, ToolResult
from tools.context import ToolContext
from tools.plugin_loader import PluginLoader
from tools.registry import ToolRegistry


class TestToolContext:
    """Tests for ToolContext dependency container."""

    def test_get_field(self):
        ctx = ToolContext(workspace="/my/repo")
        assert ctx.get("workspace") == "/my/repo"

    def test_get_extras(self):
        ctx = ToolContext(extras={"custom_dep": "hello"})
        assert ctx.get("custom_dep") == "hello"

    def test_get_missing(self):
        ctx = ToolContext()
        assert ctx.get("nonexistent") is None

    def test_available_keys(self):
        ctx = ToolContext(workspace="/repo", extras={"foo": "bar"})
        keys = ctx.available_keys()
        assert "workspace" in keys
        assert "foo" in keys
        assert "sandbox" not in keys  # None by default


class TestPluginLoader:
    """Tests for PluginLoader auto-discovery."""

    def test_load_from_empty_dir(self, tmp_path):
        """Empty directory should load zero tools."""
        registry = ToolRegistry()
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)
        assert result == []

    def test_load_from_nonexistent_dir(self, tmp_path):
        """Non-existent directory should return empty list, not crash."""
        registry = ToolRegistry()
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path / "does_not_exist", ctx, registry)
        assert result == []

    def test_discover_valid_tool(self, tmp_path):
        """A valid Tool subclass in a .py file should be discovered and registered."""
        tool_code = textwrap.dedent("""\
            from tools.base import Tool, ToolResult

            class GreetTool(Tool):
                @property
                def name(self): return "greet"

                @property
                def description(self): return "Says hello"

                @property
                def parameters(self):
                    return {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="Hello!")
        """)
        (tmp_path / "greet_tool.py").write_text(tool_code)

        registry = ToolRegistry()
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)

        assert "greet" in result
        assert registry.get("greet") is not None

    def test_dependency_injection(self, tmp_path):
        """Tools with requires should receive dependencies from ToolContext."""
        tool_code = textwrap.dedent("""\
            from tools.base import Tool, ToolResult

            class InjectTool(Tool):
                requires = ["workspace"]

                def __init__(self, workspace="", **kwargs):
                    self._workspace = workspace

                @property
                def name(self): return "inject_test"

                @property
                def description(self): return "Tests injection"

                @property
                def parameters(self):
                    return {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output=self._workspace)
        """)
        (tmp_path / "inject_tool.py").write_text(tool_code)

        registry = ToolRegistry()
        ctx = ToolContext(workspace="/test/repo")
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("inject_test")
        assert tool is not None
        assert tool._workspace == "/test/repo"

    def test_duplicate_name_skipped(self, tmp_path):
        """Tools whose name collides with an existing tool should be skipped."""
        tool_code = textwrap.dedent("""\
            from tools.base import Tool, ToolResult

            class DupTool(Tool):
                @property
                def name(self): return "existing"

                @property
                def description(self): return "Duplicate"

                @property
                def parameters(self):
                    return {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="dup")
        """)
        (tmp_path / "dup_tool.py").write_text(tool_code)

        # Pre-register a tool with the same name
        class ExistingTool(Tool):
            @property
            def name(self):
                return "existing"

            @property
            def description(self):
                return "Original"

            @property
            def parameters(self):
                return {"type": "object", "properties": {}}

            async def execute(self, **kwargs):
                return ToolResult(output="original")

        registry = ToolRegistry()
        registry.register(ExistingTool())

        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)

        # Duplicate should be skipped
        assert "existing" not in result
        # Original should still be there
        assert registry.get("existing").description == "Original"

    def test_invalid_tool_name_skipped(self, tmp_path):
        """Tools with invalid names should be skipped."""
        tool_code = textwrap.dedent("""\
            from tools.base import Tool, ToolResult

            class BadNameTool(Tool):
                @property
                def name(self): return "Invalid-Name!"

                @property
                def description(self): return "Bad name"

                @property
                def parameters(self):
                    return {"type": "object", "properties": {}}

                async def execute(self, **kwargs):
                    return ToolResult(output="bad")
        """)
        (tmp_path / "bad_name.py").write_text(tool_code)

        registry = ToolRegistry()
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)
        assert result == []

    def test_malformed_file_skipped(self, tmp_path):
        """Files with syntax errors should be skipped gracefully."""
        (tmp_path / "broken.py").write_text("def incomplete(")

        registry = ToolRegistry()
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)
        assert result == []

    def test_underscore_files_skipped(self, tmp_path):
        """Files starting with underscore should be skipped."""
        tool_code = textwrap.dedent("""\
            from tools.base import Tool, ToolResult

            class HiddenTool(Tool):
                @property
                def name(self): return "hidden"
                @property
                def description(self): return "Hidden"
                @property
                def parameters(self): return {"type": "object", "properties": {}}
                async def execute(self, **kwargs): return ToolResult(output="hi")
        """)
        (tmp_path / "__init__.py").write_text(tool_code)
        (tmp_path / "_private.py").write_text(tool_code)

        registry = ToolRegistry()
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)
        assert result == []

    def test_multiple_tools_in_one_file(self, tmp_path):
        """Multiple Tool subclasses in a single file should all be discovered."""
        tool_code = textwrap.dedent("""\
            from tools.base import Tool, ToolResult

            class ToolA(Tool):
                @property
                def name(self): return "tool_a"
                @property
                def description(self): return "Tool A"
                @property
                def parameters(self): return {"type": "object", "properties": {}}
                async def execute(self, **kwargs): return ToolResult(output="a")

            class ToolB(Tool):
                @property
                def name(self): return "tool_b"
                @property
                def description(self): return "Tool B"
                @property
                def parameters(self): return {"type": "object", "properties": {}}
                async def execute(self, **kwargs): return ToolResult(output="b")
        """)
        (tmp_path / "multi.py").write_text(tool_code)

        registry = ToolRegistry()
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)
        assert "tool_a" in result
        assert "tool_b" in result


# ---------------------------------------------------------------------------
# Helper: a simple base tool used by extension tests
# ---------------------------------------------------------------------------

class _BaseTool(Tool):
    """Minimal tool used as a base for extension tests."""

    @property
    def name(self):
        return "base_tool"

    @property
    def description(self):
        return "Base tool"

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input value"},
            },
            "required": ["input"],
        }

    async def execute(self, input: str = "", **kwargs):
        return ToolResult(output=f"base:{input}")


class TestToolExtensions:
    """Tests for ToolExtension auto-discovery and ExtendedTool wrapping."""

    def test_extension_merges_parameters(self, tmp_path):
        """Extra parameters from an extension appear in the extended tool's schema."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension, ToolResult

            class AddFlag(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "add_flag"

                @property
                def extra_parameters(self):
                    return {"flag": {"type": "boolean", "description": "A flag"}}
        """)
        (tmp_path / "add_flag.py").write_text(ext_code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("base_tool")
        assert isinstance(tool, ExtendedTool)
        props = tool.parameters["properties"]
        assert "input" in props  # Original param preserved
        assert "flag" in props  # Extension param added

    @pytest.mark.asyncio
    async def test_extension_pre_execute_hook(self, tmp_path):
        """pre_execute can modify kwargs before the base tool runs."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension, ToolResult

            class PrefixExt(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "prefix_ext"

                async def pre_execute(self, **kwargs):
                    kwargs["input"] = "prefixed:" + kwargs.get("input", "")
                    return kwargs
        """)
        (tmp_path / "prefix_ext.py").write_text(ext_code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("base_tool")
        result = await tool.execute(input="hello")
        assert result.output == "base:prefixed:hello"

    @pytest.mark.asyncio
    async def test_extension_post_execute_hook(self, tmp_path):
        """post_execute can modify the result after the base tool runs."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension, ToolResult

            class SuffixExt(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "suffix_ext"

                async def post_execute(self, result, **kwargs):
                    return ToolResult(output=result.output + ":suffix")
        """)
        (tmp_path / "suffix_ext.py").write_text(ext_code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("base_tool")
        result = await tool.execute(input="hello")
        assert result.output == "base:hello:suffix"

    def test_extension_description_suffix(self, tmp_path):
        """Description includes the base description plus extension suffixes."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension

            class DescExt(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "desc_ext"

                @property
                def description_suffix(self): return "Also does more."
        """)
        (tmp_path / "desc_ext.py").write_text(ext_code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("base_tool")
        assert tool.description == "Base tool Also does more."

    @pytest.mark.asyncio
    async def test_multiple_extensions_same_base(self, tmp_path):
        """Two extensions on the same base should both apply."""
        ext_a = textwrap.dedent("""\
            from tools.base import ToolExtension, ToolResult

            class ExtA(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "ext_a"

                @property
                def extra_parameters(self):
                    return {"flag_a": {"type": "boolean"}}

                async def pre_execute(self, **kwargs):
                    kwargs["input"] = "A(" + kwargs.get("input", "") + ")"
                    return kwargs
        """)
        ext_b = textwrap.dedent("""\
            from tools.base import ToolExtension, ToolResult

            class ExtB(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "ext_b"

                @property
                def extra_parameters(self):
                    return {"flag_b": {"type": "string"}}

                async def post_execute(self, result, **kwargs):
                    return ToolResult(output=result.output + "+B")
        """)
        (tmp_path / "ext_a.py").write_text(ext_a)
        (tmp_path / "ext_b.py").write_text(ext_b)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("base_tool")
        assert isinstance(tool, ExtendedTool)

        # Both parameters merged
        props = tool.parameters["properties"]
        assert "flag_a" in props
        assert "flag_b" in props
        assert "input" in props  # Original preserved

        # Hooks chained: pre_execute(A) → base → post_execute(B)
        result = await tool.execute(input="x")
        assert result.output == "base:A(x)+B"

    def test_extension_missing_base_skipped(self, tmp_path):
        """Extension for a nonexistent base logs a warning and is skipped."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension

            class OrphanExt(ToolExtension):
                extends = "nonexistent_tool"

                @property
                def name(self): return "orphan_ext"
        """)
        (tmp_path / "orphan.py").write_text(ext_code)

        registry = ToolRegistry()
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        # No tool should be registered (the base doesn't exist)
        assert registry.get("nonexistent_tool") is None

    def test_extension_dependency_injection(self, tmp_path):
        """Extensions with requires receive ToolContext dependencies."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension, ToolResult

            class InjectExt(ToolExtension):
                extends = "base_tool"
                requires = ["workspace"]

                def __init__(self, workspace="", **kwargs):
                    self._workspace = workspace

                @property
                def name(self): return "inject_ext"

                @property
                def description_suffix(self):
                    return f"(workspace: {self._workspace})"
        """)
        (tmp_path / "inject_ext.py").write_text(ext_code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext(workspace="/my/project")
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("base_tool")
        assert "(workspace: /my/project)" in tool.description

    def test_extension_invalid_name_skipped(self, tmp_path):
        """Extensions with invalid names are skipped."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension

            class BadExt(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "INVALID!"
        """)
        (tmp_path / "bad_ext.py").write_text(ext_code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        # Base tool should remain unmodified
        tool = registry.get("base_tool")
        assert not isinstance(tool, ExtendedTool)

    def test_extension_and_new_tool_coexist(self, tmp_path):
        """A file can contain both a new Tool and a ToolExtension."""
        code = textwrap.dedent("""\
            from tools.base import Tool, ToolExtension, ToolResult

            class NewTool(Tool):
                @property
                def name(self): return "brand_new"
                @property
                def description(self): return "A new tool"
                @property
                def parameters(self):
                    return {"type": "object", "properties": {}}
                async def execute(self, **kwargs):
                    return ToolResult(output="new")

            class BaseExt(ToolExtension):
                extends = "base_tool"
                @property
                def name(self): return "base_ext"
                @property
                def extra_parameters(self):
                    return {"extra": {"type": "string"}}
        """)
        (tmp_path / "combo.py").write_text(code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        result = PluginLoader.load_all(tmp_path, ctx, registry)

        # New tool registered
        assert "brand_new" in result
        assert registry.get("brand_new") is not None

        # Base tool extended
        tool = registry.get("base_tool")
        assert isinstance(tool, ExtendedTool)
        assert "extra" in tool.parameters["properties"]

    def test_extension_preserves_to_schema(self, tmp_path):
        """ExtendedTool.to_schema() reflects merged parameters."""
        ext_code = textwrap.dedent("""\
            from tools.base import ToolExtension

            class SchemaExt(ToolExtension):
                extends = "base_tool"

                @property
                def name(self): return "schema_ext"

                @property
                def extra_parameters(self):
                    return {"verbose": {"type": "boolean"}}

                @property
                def description_suffix(self): return "Supports verbose mode."
        """)
        (tmp_path / "schema_ext.py").write_text(ext_code)

        registry = ToolRegistry()
        registry.register(_BaseTool())
        ctx = ToolContext()
        PluginLoader.load_all(tmp_path, ctx, registry)

        tool = registry.get("base_tool")
        schema = tool.to_schema()
        assert schema["function"]["name"] == "base_tool"
        assert "verbose" in schema["function"]["parameters"]["properties"]
        assert "Supports verbose mode." in schema["function"]["description"]

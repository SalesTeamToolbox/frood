"""Tests for tools/plugin_loader.py — custom tool auto-discovery."""

import textwrap

from tools.base import Tool, ToolResult
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

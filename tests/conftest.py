"""Shared test fixtures for Agent42 test suite.

Provides reusable fixtures for sandbox, command filter, tool registry,
and mock tools — eliminating duplication across test files.
"""

import pytest

from core.command_filter import CommandFilter
from core.sandbox import WorkspaceSandbox
from tools.base import Tool, ToolResult
from tools.registry import ToolRegistry


@pytest.fixture
def tmp_workspace(tmp_path):
    """Provide an isolated workspace directory."""
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return workspace


@pytest.fixture
def sandbox(tmp_workspace):
    """Provide a WorkspaceSandbox rooted at a temp directory."""
    return WorkspaceSandbox(str(tmp_workspace), enabled=True)


@pytest.fixture
def disabled_sandbox(tmp_workspace):
    """Provide a disabled sandbox for tests that need unrestricted access."""
    return WorkspaceSandbox(str(tmp_workspace), enabled=False)


@pytest.fixture
def command_filter():
    """Provide a default CommandFilter (deny-list mode)."""
    return CommandFilter()


@pytest.fixture
def tool_registry():
    """Provide an empty ToolRegistry."""
    return ToolRegistry()


class _MockTool(Tool):
    """A configurable mock tool for testing."""

    def __init__(self, tool_name="mock_tool", tool_description="Mock tool for testing"):
        self._name = tool_name
        self._description = tool_description

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return self._description

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "input": {"type": "string", "description": "Input to process"},
            },
        }

    async def execute(self, input: str = "", **kwargs) -> ToolResult:
        return ToolResult(output=f"Processed: {input}")


@pytest.fixture
def mock_tool():
    """Provide a MockTool instance for registry and execution tests."""
    return _MockTool()


@pytest.fixture
def mock_tool_factory():
    """Provide a factory for creating mock tools with custom names."""

    def _create(name="mock_tool", description="Mock tool for testing"):
        return _MockTool(tool_name=name, tool_description=description)

    return _create


@pytest.fixture
def populated_registry(tool_registry, mock_tool):
    """Provide a ToolRegistry with a mock tool already registered."""
    tool_registry.register(mock_tool)
    return tool_registry

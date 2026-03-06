---
name: test-coverage
description: Generate a test file for a module following project conventions
always: false
task_types: [testing]
---

# /test-coverage

Generate a comprehensive test file for a given module, following Agent42 project conventions.

## Usage

```
/test-coverage <module_path>
```

Where `<module_path>` is the dotted or slash path to the module (e.g., `core/sandbox`, `tools/shell`, `agents/orchestrator`).

## Step 1: Resolve Paths

Given the module path, determine:

- **Source file**: Resolve to the actual `.py` file (e.g., `core/sandbox` -> `core/sandbox.py`)
- **Test file**: Derive as `tests/test_<module_basename>.py` (e.g., `core/sandbox.py` -> `tests/test_sandbox.py`)

**Before proceeding**, check if `tests/test_<module_basename>.py` already exists. If it does, STOP and inform the developer. Do NOT overwrite existing test files.

## Step 2: Read Context

Before generating any code, read these files to understand the module and project patterns:

1. **Target module** (`<source_file>`) -- Extract all public classes, their methods (sync vs async), constructor parameters, and external dependencies (imports from other packages like `openai`, `httpx`, `redis`, `qdrant_client`, `aiofiles`).

2. **`tests/conftest.py`** -- Review available fixtures:
   - `tmp_workspace` -- Isolated workspace directory (use instead of raw `tmp_path` for workspace tests)
   - `sandbox` -- `WorkspaceSandbox` rooted at temp directory (enabled)
   - `disabled_sandbox` -- `WorkspaceSandbox` with `enabled=False`
   - `command_filter` -- Default `CommandFilter` in deny-list mode
   - `tool_registry` -- Empty `ToolRegistry`
   - `mock_tool` -- `_MockTool` instance with configurable name/description
   - `mock_tool_factory` -- Factory for creating named mock tools
   - `populated_registry` -- `ToolRegistry` with one mock tool registered

3. **One existing test file** (e.g., `tests/test_sandbox.py` or `tests/test_command_filter.py`) -- Use as a style exemplar for structure, naming, and assertion patterns.

## Step 3: Generate the Test File

Create `tests/test_<module_basename>.py` using this structure:

```python
"""Tests for <module_name>."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# Import the module under test
from <module_path> import <ClassName>

# Import conftest fixtures as needed (they're auto-available via conftest.py):
# tmp_workspace, sandbox, command_filter, tool_registry, mock_tool


class Test<ClassName>:
    """Tests for <ClassName>."""

    def setup_method(self):
        """Set up test fixtures."""
        # Initialize the class under test with test-appropriate config
        # Use mocks for external dependencies
        pass

    def test_<method>_<happy_path_scenario>_<expected>(self):
        """Test <method> returns expected result for normal input."""
        # Arrange
        # Act
        # Assert
        pass

    def test_<method>_<edge_case_scenario>_<expected>(self):
        """Test <method> handles edge case correctly."""
        pass

    def test_<method>_<error_scenario>_raises_or_handles(self):
        """Test <method> raises/handles error for invalid input."""
        pass

    @pytest.mark.asyncio
    async def test_<async_method>_<scenario>_<expected>(self):
        """Test async <method> completes successfully."""
        # Use AsyncMock for mocked async dependencies
        pass
```

### Template Rules

1. **Module docstring**: `"""Tests for <module_name>."""`
2. **Imports**: `pytest`, `unittest.mock` (patch, AsyncMock, MagicMock), the module under test
3. **Class-based organization**: One `class Test<ClassName>:` per public class in the module
4. **`setup_method(self)`**: Initialize the class under test with test configuration. Mock external dependencies here.
5. **`@pytest.mark.asyncio`**: Add this decorator on every test method that tests an async function. The project uses `asyncio_mode = "auto"` in pyproject.toml.
6. **Test naming**: `test_<function>_<scenario>_<expected>` -- Be descriptive about what scenario is being tested and what the expected outcome is.
7. **Mock externals**: Use `unittest.mock.patch` or `AsyncMock` for:
   - LLM API calls (`openai`, `httpx`)
   - Redis connections
   - Qdrant client operations
   - File system operations (when not using `tmp_workspace`)
   - HTTP requests
8. **Use conftest fixtures**: Pass `tmp_workspace`, `sandbox`, `command_filter`, `tool_registry`, or `mock_tool` as test method parameters where applicable. Do NOT use raw `tmp_path` when `tmp_workspace` provides the right abstraction.
9. **Coverage targets**: Each test class should have 3-5 test methods covering:
   - Happy path (normal input, expected output)
   - Edge case (empty input, boundary values, None)
   - Error handling (invalid input, missing dependencies, exceptions)
10. **Assertions**: Use specific assertions (`assert result.success`, `assert "expected" in output`) rather than bare `assert result`.

## Step 4: Run Tests

After generating the file, run:

```bash
python -m pytest tests/test_<module_basename>.py -x -q
```

Review results:
- If all tests pass, report success.
- If tests fail, fix the failing tests (adjust mocks, fix imports, correct assertions).
- Re-run until all tests pass.

## What NOT to Do

- Do NOT modify `tests/conftest.py` -- use existing fixtures as-is
- Do NOT create test files for modules that already have them (check first)
- Do NOT use `tmp_path` directly when the `tmp_workspace` fixture provides an isolated workspace
- Do NOT use blocking I/O in test helpers -- the project is fully async
- Do NOT hit real external APIs (LLM, Redis, Qdrant) -- always mock
- Do NOT hardcode absolute paths -- use `tmp_path` or `tmp_workspace` fixtures

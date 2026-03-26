# Development Workflow

## Before Writing Code

1. Run tests to confirm green baseline: `python -m pytest tests/ -x -q`
2. Check if related test files exist for the module you're changing
3. Read the module's docstring and understand the pattern
4. For security-sensitive files, read `.claude/lessons.md` security section

## After Writing Code

1. Run the formatter: `make format` (or `ruff format .`)
2. Run the full test suite: `python -m pytest tests/ -x -q`
3. Run linter: `make lint`
4. For security-sensitive changes: `python -m pytest tests/test_security.py tests/test_sandbox.py tests/test_command_filter.py -v`
5. Update CLAUDE.md pitfalls table if you discovered a non-obvious issue
6. For new modules: ensure a corresponding `tests/test_*.py` file exists
7. Update README.md if new features, skills, tools, or config were added

## Testing Standards

**Always install dependencies before running tests.** Tests should always be
runnable — if a dependency is missing, install it rather than skipping the test:

```bash
pip install -r requirements.txt            # Full production dependencies
pip install -r requirements-dev.txt        # Dev/test tooling (pytest, ruff, etc.)
# If the venv is missing, install at minimum:
pip install pytest pytest-asyncio aiofiles openai fastapi python-jose bcrypt cffi
```

Run tests:
```bash
python -m pytest tests/ -x -q              # Quick: stop on first failure
python -m pytest tests/ -v                  # Verbose: see all test names
python -m pytest tests/test_security.py -v  # Single file
python -m pytest tests/ -k "test_sandbox"   # Filter by name
python -m pytest tests/ -m security         # Filter by marker
```

Some tests require `fastapi`, `python-jose`, `bcrypt`, and `redis` — install the full
`requirements.txt` to avoid import errors. If the `cryptography` backend fails with
`_cffi_backend` errors, install `cffi` (`pip install cffi`).

## Test Writing Rules

- Every new module in `core/`, `agents/`, `tools/`, `providers/` needs a `tests/test_*.py` file
- Use `pytest-asyncio` for async tests (configured as `asyncio_mode = "auto"` in pyproject.toml)
- Use `tmp_path` fixture (or conftest.py `tmp_workspace`) for filesystem tests — never hardcode `/tmp` paths
- Use class-based organization: `class TestClassName` with `setup_method`
- Mock external services (LLM calls, Redis, Qdrant) — never hit real APIs in tests
- Use conftest.py fixtures: `sandbox`, `command_filter`, `tool_registry`, `mock_tool`
- Name tests descriptively: `test_<function>_<scenario>_<expected>`

```python
class TestWorkspaceSandbox:
    def setup_method(self):
        self.sandbox = WorkspaceSandbox(tmp_path, enabled=True)

    def test_block_path_traversal(self):
        with pytest.raises(SandboxViolation):
            self.sandbox.resolve_path("../../etc/passwd")

    @pytest.mark.asyncio
    async def test_async_tool_execution(self):
        result = await tool.execute(input="test")
        assert result.success
```
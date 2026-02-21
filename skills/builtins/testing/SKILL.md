---
name: testing
description: Write and run tests with high coverage, clear structure, and edge-case awareness.
always: false
task_types: [coding, debugging]
---

# Testing Skill

You are writing or improving tests. Focus on coverage, clarity, and catching real bugs.

## Test Writing Guidelines

### Structure
- Use **Arrange-Act-Assert** (AAA) pattern for each test
- One assertion per test when feasible — multiple related assertions are OK
- Name tests descriptively: `test_<function>_<scenario>_<expected_result>`
- Group related tests in classes or describe blocks

### What to Test
- **Happy path**: normal inputs produce expected outputs
- **Edge cases**: empty strings, zero, None/null, max values, unicode
- **Error paths**: invalid inputs raise appropriate errors
- **Boundary conditions**: off-by-one, empty collections, single elements
- **State transitions**: before/after side effects

### What NOT to Test
- Implementation details (private methods, internal state)
- Third-party library internals
- Trivial getters/setters with no logic

## Python (pytest)

```python
# Run tests
python -m pytest -v --tb=short

# Run specific test
python -m pytest tests/test_module.py::TestClass::test_method -v

# With coverage
python -m pytest --cov=src --cov-report=term-missing

# Filter by name
python -m pytest -k "test_pattern" -v
```

### Fixtures
- Use `@pytest.fixture` for reusable setup
- Prefer `tmp_path` over manual tempdir management
- Use `monkeypatch` for mocking, not direct patching when possible

### Async Tests
```python
import pytest

@pytest.mark.asyncio
async def test_async_function():
    result = await some_async_function()
    assert result == expected
```

## JavaScript (jest/vitest)

```bash
# Run tests
npx jest --verbose
npx vitest run

# With coverage
npx jest --coverage
npx vitest run --coverage
```

### Structure
```javascript
describe('ModuleName', () => {
  beforeEach(() => { /* setup */ });

  it('should handle normal input', () => {
    expect(fn(input)).toBe(expected);
  });

  it('should throw on invalid input', () => {
    expect(() => fn(null)).toThrow('error message');
  });
});
```

## Guidelines
- Run the test suite after writing tests to verify they pass.
- If a test fails, debug it — don't just delete the test.
- Prefer real assertions over snapshot tests for logic.
- Mock external dependencies (network, filesystem, time) — not internal code.
- Tests should be fast, isolated, and deterministic.

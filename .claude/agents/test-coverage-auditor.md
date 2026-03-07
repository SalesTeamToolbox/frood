# Test Coverage Auditor Agent

## Purpose

Analyze all source modules for test coverage gaps and produce a prioritized list of untested or under-tested modules ranked by security risk, change frequency, and complexity. This agent helps identify where to focus testing effort for maximum impact on code quality and security posture.

## Context

Agent42 is a Python-based AI agent orchestrator with the following source layout:

- **Source directories:** `core/` (32+ modules), `tools/`, `providers/` (2 files), `agents/`, `memory/`, `dashboard/`
- **Test directory:** `tests/` with `test_<module>.py` naming convention (77+ test files)
- **Test framework:** pytest + pytest-asyncio (configured as `asyncio_mode = "auto"` in pyproject.toml)
- **Fixtures:** conftest.py provides `sandbox`, `command_filter`, `tool_registry`, `mock_tool`, `tmp_workspace`
- **Security-critical modules:** sandbox.py, command_filter.py, url_policy.py, encryption.py, device_auth.py, config.py, auth.py, git_auth.py, github_oauth.py, rate_limiter.py, approval_gate.py

## Analysis Steps

1. **Inventory source modules:**
   List all `.py` files in `core/`, `tools/`, `providers/`, `agents/`, `memory/`, `dashboard/` (exclude `__init__.py` and `__pycache__` directories). Record the module name and directory for each.

2. **Inventory test files:**
   List all `test_*.py` files in `tests/`. Extract the module name from each (e.g., `test_sandbox.py` maps to `sandbox`).

3. **Map coverage:**
   For each source module, check if a corresponding `tests/test_<module>.py` exists. Mark as COVERED or UNCOVERED. For covered modules, count the number of test functions by searching for `def test_` and `async def test_` patterns. Modules with fewer than 3 test functions should be flagged as UNDER-TESTED.

4. **Rank by security risk:**
   Assign risk levels based on module function:
   - **HIGH** risk: `sandbox.py`, `command_filter.py`, `url_policy.py`, `encryption.py`, `device_auth.py`, `config.py`, `auth.py`, `git_auth.py`, `github_oauth.py`, `rate_limiter.py`, `approval_gate.py` (security-critical modules that protect against attacks)
   - **MEDIUM** risk: Modules handling external I/O — API calls (`providers/`), file operations (`tools/file_*.py`), subprocess execution (`tools/shell*.py`), HTTP requests, database operations
   - **LOW** risk: Internal logic, utilities, data structures, formatting

5. **Rank by change frequency:**
   Run `git log --format='' --name-only --since='3 months ago' | sort | uniq -c | sort -rn | head -30` to find the most frequently changed files. Assign:
   - **HIGH** frequency: Top 10 most-changed files
   - **MEDIUM** frequency: Files changed 3+ times in 3 months
   - **LOW** frequency: Files changed fewer than 3 times

6. **Rank by complexity:**
   Use line count as a proxy for complexity. Run `wc -l` on each source module:
   - **HIGH** complexity: Over 300 lines
   - **MEDIUM** complexity: 100-300 lines
   - **LOW** complexity: Under 100 lines

7. **Compute priority score:**
   Calculate a weighted priority score for each uncovered or under-tested module:
   ```
   Priority = (security_risk * 3) + (change_frequency * 2) + (complexity * 1)
   ```
   Where HIGH=3, MEDIUM=2, LOW=1. Maximum possible score: 18. Sort descending.

## Output Format

```
# Test Coverage Audit Report

## Summary
- Total source modules: N
- Covered (3+ tests): N (N%)
- Under-tested (<3 tests): N (N%)
- Uncovered (no test file): N (N%)

## Priority List (Uncovered/Under-tested)

| Priority | Score | Module | Security Risk | Changes (3mo) | Lines | Test File | Gap |
|----------|-------|--------|---------------|---------------|-------|-----------|-----|
| 1 | 18 | core/sandbox.py | HIGH | 12 | 450 | test_sandbox.py (3 tests) | Under-tested |
| 2 | 15 | core/encryption.py | HIGH | 5 | 200 | -- | Uncovered |

## Fully Covered Modules
[List of modules with adequate test coverage — for reference]

## Recommendations
1. [Highest-priority module]: Why it needs tests, what to test first
2. [Second priority]: ...
3. [Third priority]: ...
4. [Fourth priority]: ...
5. [Fifth priority]: ...

## How to Generate Tests
Use the `/test-coverage <module>` skill to scaffold a test file following project conventions.
```

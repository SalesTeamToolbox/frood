# Migration Impact Agent

## Purpose

Trace all usages of a specified package or API across the codebase and flag breaking incompatibilities with file:line references. Use this agent before upgrading a dependency, renaming an internal API, or removing a module to understand the full blast radius and generate an ordered migration plan.

## Context

Agent42 is a Python codebase with cross-module dependencies:

- **Source directories:** `core/`, `tools/`, `providers/`, `agents/`, `memory/`, `dashboard/`, `tests/`
- **Entry point:** `agent42.py` imports from all major modules
- **Internal API patterns:** modules in `core/` are imported by `tools/`, `agents/`, `dashboard/`, and `server.py`
- **Common external dependencies:** `openai`, `httpx`, `fastapi`, `pydantic`, `qdrant-client`, `redis`, `bcrypt`, `python-jose`, `aiofiles`
- **Known pitfalls from API changes:** Pitfall 96 (method rename broke /api/reports), Pitfall 97 (nonexistent attribute access)

## Usage

This agent takes an input parameter specifying what to analyze. Examples:

- **Package upgrade:** "Upgrading openai from 1.30 to 1.35"
- **API rename:** "Renaming project_manager.all_projects() to list_projects()"
- **Module removal:** "Removing core/legacy_router.py"
- **Internal refactor:** "Moving Settings from core/config.py to core/settings.py"

## Analysis Steps

1. **Identify the target:**
   Parse the input to determine:
   - Package name or module path
   - Old API signature (if renaming)
   - New API signature (if applicable)
   - Version range (if upgrading a package)

2. **Find all import sites:**
   Search across all `.py` files for:
   - `import <package>` (direct imports)
   - `from <package> import <symbol>` (symbol imports)
   - `from <package>.<submodule> import <symbol>` (submodule imports)
   - Aliased imports: `import <package> as <alias>`, `from <package> import <symbol> as <alias>`

   Record each import with `file:line` reference. For internal modules, also check for relative imports.

3. **Find all usage sites:**
   For each imported symbol, search the importing file for:
   - Function/method calls: `symbol(args)`
   - Attribute access: `symbol.attribute`
   - Class instantiation: `Symbol(args)`
   - Subclass definitions: `class MyClass(Symbol):`
   - Type annotations: `param: Symbol`
   - Dictionary/list membership: `symbol in collection`

   Record each usage with `file:line` and the specific usage pattern.

4. **Analyze breaking changes:**
   - **For package upgrades:** Fetch the changelog or migration guide from PyPI project page, GitHub releases, or official docs. Compare each usage site against documented breaking changes. Check for: removed functions, renamed parameters, changed return types, removed keyword arguments, changed default values.
   - **For internal API changes:** Compare each call site against the new signature. Check argument order, removed parameters, type changes, return type changes.
   - **For module removal:** Every import site is a breaking change.

5. **Assess test coverage of affected sites:**
   For each affected source file, check if a corresponding test file exists in `tests/`. If the test file exists, search for test functions that exercise the affected code paths. Flag untested migration risks as HIGH priority — these are the most dangerous because regressions won't be caught.

6. **Generate migration plan:**
   For each breaking change, produce an ordered list of file modifications:
   - Group changes by type (import updates, call site updates, type annotation updates)
   - Order by dependency (update leaf modules first, then modules that import them)
   - Specify the exact fix needed at each `file:line`
   - Note which changes can be done with search-and-replace vs. manual review

## Output Format

```
# Migration Impact Report: [Target Description]

## Scope
- Files affected: N
- Import sites: N
- Usage sites: N
- Breaking changes identified: N
- Non-breaking changes: N

## Breaking Changes

| # | Severity | File:Line | Current Usage | Breaking Change | Required Fix | Test Coverage |
|---|----------|-----------|---------------|-----------------|--------------|---------------|
| 1 | HIGH | core/config.py:45 | `openai.ChatCompletion.create()` | Removed in v1.0 | Use `client.chat.completions.create()` | test_config.py (YES) |
| 2 | HIGH | tools/shell.py:120 | `subprocess.run(cmd)` | N/A | N/A | NONE - needs test |

## Non-Breaking Changes
[Deprecation warnings, optional parameter additions, new features available]

| # | File:Line | Current Usage | Change | Action |
|---|-----------|---------------|--------|--------|
| 1 | core/llm.py:30 | `client.create(model=m)` | New optional param `stream_options` | No action required |

## Migration Steps (ordered)
1. Update `requirements.txt`: change `openai==1.30.0` to `openai==1.35.0`
2. Update `core/config.py:45`: replace `openai.ChatCompletion.create()` with `client.chat.completions.create()`
3. Update `tools/shell.py:120`: [specific fix]
4. Run test suite: `python -m pytest tests/ -x -q`

## Risk Assessment
- **HIGH** risk: [N] untested breaking changes — regressions will NOT be caught
- **MEDIUM** risk: [N] tested breaking changes — regressions will be caught by tests
- **LOW** risk: [N] non-breaking changes — no code modification needed

## Rollback Plan
If issues are found after migration:
1. Revert `requirements.txt` to previous version
2. Run `pip install -r requirements.txt` to downgrade
3. Verify with `python -m pytest tests/ -x -q`
```

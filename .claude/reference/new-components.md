# Adding New Components

## New Tool (Built-in)

1. Create `tools/my_tool.py` with class inheriting from `Tool` ABC
2. Implement required properties: `name`, `description`, `parameters`
3. Implement `async execute(**kwargs) -> ToolResult`
4. Register in `agent42.py` `_register_tools()`:
   ```python
   from tools.my_tool import MyTool
   registry.register(MyTool(sandbox=self._sandbox))
   ```
5. Create `tests/test_my_tool.py` with tests
6. Run: `python -m pytest tests/test_my_tool.py -v`

## New Tool (Custom Plugin — no core changes)

1. Set `CUSTOM_TOOLS_DIR=custom_tools` in `.env`
2. Create `custom_tools/my_tool.py` with a `Tool` subclass
3. Add `requires = ["sandbox", "workspace"]` class var for dependency injection
4. Tool is auto-discovered and registered at startup via `PluginLoader`
5. Tool name must match `^[a-z][a-z0-9_]{1,48}$`; duplicates are skipped

## New Skill

1. Create `skills/builtins/my-skill/SKILL.md` with YAML frontmatter
2. Set `task_types` to match relevant `TaskType` enum values
3. Set `always: true` only if the skill should load for every task
4. Optionally add `requirements_bins` for CLI tool dependencies

## New Provider

1. Add `ProviderSpec` to `PROVIDERS` dict in `providers/registry.py`
2. Add `ModelSpec` entries to `MODELS` dict for each supported model
3. Add API key field to `Settings` in `core/config.py`
4. Add `os.getenv()` call in `Settings.from_env()`
5. Add to `.env.example` with documentation

## New Config Field

1. Add field to `Settings` class with sensible default
2. Add `os.getenv()` call in `Settings.from_env()` with type conversion
3. Add to `.env.example` with description
4. For boolean fields: use `.lower() in ("true", "1", "yes")` pattern
5. For comma-separated lists: add `get_*()` helper method

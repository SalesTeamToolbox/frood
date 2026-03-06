# Phase 13: Scaffolding Skills - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Create three Claude Code skills (`/test-coverage`, `/add-provider`, `/add-tool`) that generate correctly-patterned boilerplate from project conventions. Skills are SKILL.md files in `.claude/skills/` with YAML frontmatter. Each skill produces files following established patterns from CLAUDE.md.

</domain>

<decisions>
## Implementation Decisions

### Skill invocation style
- Skills are `.claude/skills/<name>/SKILL.md` markdown files with YAML frontmatter (name, description, always, task_types)
- Invoked as slash commands in Claude Code: `/test-coverage`, `/add-provider`, `/add-tool`
- Naming follows kebab-case: `test-coverage`, `add-provider`, `add-tool`
- `always: false` — these are on-demand, not auto-loaded

### Template source strategy
- Skills contain inline templates within the SKILL.md instructions — no external template files
- Templates reference actual codebase patterns: `tools/base.py` Tool ABC, `providers/registry.py` ProviderSpec/ModelSpec, `tests/conftest.py` fixtures
- Skills instruct Claude to read existing exemplar files when generating (e.g., "read an existing test file for style reference")
- This keeps skills self-contained while leveraging the live codebase for accuracy

### Output scope per skill

**`/test-coverage <module>`** (SKILL-01):
- Creates `tests/test_<module>.py` with class-based structure
- Uses conftest fixtures: `tmp_workspace`, `sandbox`, `command_filter`, `tool_registry`, `mock_tool`
- Includes `pytest-asyncio` markers for async methods
- Mocks external services (LLM, Redis, Qdrant)
- Names tests descriptively: `test_<function>_<scenario>_<expected>`
- Does NOT modify conftest.py or any other file — just creates the test file

**`/add-provider`** (SKILL-02):
- Adds `ProviderType` enum value to `providers/registry.py`
- Adds `ProviderSpec` entry to `PROVIDERS` dict
- Adds `ModelSpec` entries to `MODELS` dict
- Adds Settings field with `os.getenv()` in `core/config.py`
- Adds env var to `.env.example`
- Creates `tests/test_<provider>.py`
- Prompts developer for: provider name, base URL, API key env var name, model IDs, tier

**`/add-tool`** (SKILL-03):
- Creates `tools/<name>.py` with Tool ABC subclass (name, description, parameters, execute)
- Adds registration call in `agent42.py` `_register_tools()`
- Creates `tests/test_<name>.py`
- Prompts developer for: tool name, description, parameters, whether it needs ToolContext injection

### Claude's Discretion
- Exact YAML frontmatter fields (task_types list, description wording)
- How much guidance to include in SKILL.md instructions vs relying on Claude's pattern recognition
- Whether to include example invocations in skill descriptions
- Internal organization of the skill instructions (sections, order)

</decisions>

<specifics>
## Specific Ideas

No specific requirements -- follow CLAUDE.md conventions and use existing codebase patterns as the source of truth for generated boilerplate.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `tools/base.py`: Tool ABC with `name`/`description`/`parameters`/`execute()`, ToolResult dataclass, ToolExtension for plugin augmentation
- `providers/registry.py`: ProviderType enum, ProviderSpec/ModelSpec frozen dataclasses, PROVIDERS/MODELS dicts
- `tests/conftest.py`: `tmp_workspace`, `sandbox`, `disabled_sandbox`, `command_filter`, `tool_registry`, `mock_tool` fixtures with _MockTool example
- `core/config.py`: Settings frozen dataclass with `from_env()` pattern, boolean env parsing
- `.claude/agents/security-reviewer.md`: Example of agent markdown file structure (can inform skill structure)

### Established Patterns
- Tool pattern: subclass Tool, implement 4 abstract properties/methods, register in `_register_tools()`
- Provider pattern: add ProviderType enum, ProviderSpec to PROVIDERS, ModelSpec entries to MODELS, Settings field
- Test pattern: class-based `TestClassName`, `setup_method`, `pytest.mark.asyncio` for async, `tmp_path` fixture, mock externals
- Plugin tools: drop `.py` into `CUSTOM_TOOLS_DIR`, auto-discovered via `tools/plugin_loader.py`

### Integration Points
- `.claude/skills/` directory (new — needs to be created)
- `agent42.py` `_register_tools()` — where `/add-tool` will add registration
- `providers/registry.py` PROVIDERS/MODELS dicts — where `/add-provider` will add entries
- `core/config.py` Settings class — where `/add-provider` will add config fields

</code_context>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 13-scaffolding-skills*
*Context gathered: 2026-03-06*

# Phase 16: jcodemunch Deep Integration - Research

**Researched:** 2026-03-06
**Domain:** MCP tool integration, hook architecture, GSD workflow enhancement
**Confidence:** HIGH

## Summary

This phase integrates jcodemunch MCP tools deeper into three distinct systems: (1) the context-loader hook (a Python subprocess that outputs text to stderr for Claude to read), (2) GSD workflow templates (markdown files in `~/.claude/get-shit-done/` that define how mapper/planner/executor agents behave), and (3) a mid-session drift detection mechanism using jcodemunch's `get_symbol(verify=true)` hash checking.

The critical architectural constraint is that hooks are Python subprocesses that CANNOT call MCP tools directly. They can only output instructions/recommendations to stderr that Claude then acts upon. The existing `jcodemunch-reindex.py` hook already demonstrates this pattern -- it detects structural changes and outputs a message telling Claude to call `mcp__jcodemunch__index_folder`. The context-loader hook enhancement must follow this same indirect pattern: detect work type, output jcodemunch tool call recommendations to stderr, and let Claude execute them.

GSD workflows and templates live in `~/.claude/get-shit-done/` and are NOT part of the agent42 codebase. They are global Claude Code infrastructure. The phase must enhance these templates to include jcodemunch-aware instructions that GSD agents follow when they have access to jcodemunch MCP tools.

**Primary recommendation:** Enhance context-loader.py to emit `<jcodemunch_guidance>` blocks with specific MCP tool calls Claude should make; modify GSD workflow templates to include jcodemunch tool usage instructions in mapper/planner/executor prompts; add drift detection as a PostToolUse hook or integrate into the existing jcodemunch-reindex.py Stop hook.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| JCMUNCH-01 | context-loader hook detects work type and pre-loads relevant symbol outlines via jcodemunch search_symbols | Context-loader.py is a Python subprocess (lines 1-348); it outputs to stderr which Claude reads. Cannot call MCP directly. Must output jcodemunch tool call instructions for Claude to execute. Existing `detect_work_types()` provides the work type detection foundation. |
| JCMUNCH-02 | /gsd:map-codebase uses jcodemunch get_repo_outline + get_file_tree instead of spawning 4 mapper agents | map-codebase.md workflow spawns 4 parallel `gsd-codebase-mapper` agents. Can be enhanced to first call jcodemunch tools for initial data, then pass results to mapper agents OR replace mapper agents entirely with jcodemunch-based document generation. |
| JCMUNCH-03 | GSD planner agents receive codebase_context block with affected module interfaces | planner-subagent-prompt.md template passes planning context to gsd-planner agent. Can add `<codebase_context>` block populated via jcodemunch search_symbols + get_file_outline calls in the plan-phase.md orchestrator. |
| JCMUNCH-04 | GSD executor agents receive implementation_targets block with exact function signatures | phase-prompt.md template defines PLAN.md format with `<context>` section listing `@src/path/to/file`. Can add `<implementation_targets>` block; execute-plan.md orchestrator calls jcodemunch before spawning executor. |
| JCMUNCH-05 | Mid-session drift detection uses get_symbol(verify=true) hash checking and triggers re-index | jcodemunch's get_symbol supports `verify: true` parameter that re-hashes source and returns `content_verified` in `_meta`. Can be checked via PostToolUse hook on jcodemunch calls, or periodically during long sessions. |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| jcodemunch-mcp | latest (via uvx) | AST-based code indexing and retrieval | Already configured in .mcp.json; provides 11 MCP tools for token-efficient code exploration |
| Python 3.14 | 3.14.3 | Hook scripts runtime | Project standard; all hooks are Python scripts |
| Claude Code hooks | N/A | UserPromptSubmit, PostToolUse, Stop events | Existing hook infrastructure in .claude/settings.json |
| GSD workflows | N/A | Markdown templates in ~/.claude/get-shit-done/ | Global Claude Code automation framework |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json (stdlib) | builtin | Hook I/O protocol | All hooks read JSON from stdin, write to stderr |
| os, sys, re (stdlib) | builtin | File system and path operations | Hook file detection and path normalization |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Enhancing context-loader.py | New dedicated jcodemunch-context hook | Adds another hook; context-loader already detects work types -- better to extend it |
| Modifying GSD templates directly | Creating agent42-specific GSD overrides | Templates are global; direct modification benefits all projects using jcodemunch, but risks breaking other projects |

**Installation:**
```bash
# No new dependencies -- all tools already installed
# jcodemunch is configured in .mcp.json
# Python stdlib handles all hook logic
```

## Architecture Patterns

### Recommended Modification Points

```
.claude/hooks/
  context-loader.py          # MODIFY: Add jcodemunch guidance output
  jcodemunch-reindex.py      # MODIFY: Add verify-based drift detection
  jcodemunch-token-tracker.py # KEEP: Already tracks savings

~/.claude/get-shit-done/
  workflows/
    map-codebase.md          # MODIFY: Add jcodemunch pre-fetch step
    plan-phase.md            # MODIFY: Add codebase_context population
    execute-plan.md          # MODIFY: Add implementation_targets population
  templates/
    phase-prompt.md          # MODIFY: Add implementation_targets section
    planner-subagent-prompt.md # MODIFY: Add codebase_context section
```

### Pattern 1: Indirect MCP Tool Guidance via Hooks

**What:** Hooks output structured guidance blocks that instruct Claude to call specific MCP tools. The hook cannot call MCP tools itself -- it runs as a subprocess.

**When to use:** Whenever a hook needs to trigger MCP tool usage by Claude.

**Example:**
```python
# In context-loader.py — output guidance for Claude to act on
guidance = []
if "tools" in work_types:
    guidance.append(
        "Call mcp__jcodemunch__search_symbols with:\n"
        f'  repo: "local/agent42"\n'
        '  query: "Tool"\n'
        '  kind: "class"\n'
        '  file_pattern: "tools/**/*.py"'
    )
if "security" in work_types:
    guidance.append(
        "Call mcp__jcodemunch__get_file_outline with:\n"
        f'  repo: "local/agent42"\n'
        '  file_path: "core/sandbox.py"'
    )

if guidance:
    print(
        "[context-loader] jcodemunch guidance — run these before starting work:\n"
        + "\n".join(f"  {i+1}. {g}" for i, g in enumerate(guidance)),
        file=sys.stderr,
    )
```

**Source:** Established pattern from jcodemunch-reindex.py lines 184-188 which already outputs MCP tool call instructions.

### Pattern 2: GSD Workflow Pre-fetch Step

**What:** GSD workflow orchestrators (plan-phase.md, execute-plan.md) include a step that calls jcodemunch tools to populate context blocks before spawning subagents.

**When to use:** Before spawning planner or executor subagents, when the project has a jcodemunch index.

**Example (in plan-phase.md):**
```markdown
## 3.7. Populate Codebase Context (if jcodemunch available)

Check if jcodemunch is available:
```bash
# Check if repo is indexed
mcp__jcodemunch__list_repos
```

If the project repo is listed:
1. Call `mcp__jcodemunch__search_symbols` with query terms from the phase goal
2. Call `mcp__jcodemunch__get_file_outline` for each file in the phase's `files_modified`
3. Inject results into the planner prompt as a `<codebase_context>` block
```

### Pattern 3: Drift Detection via verify Parameter

**What:** Use `get_symbol(verify=true)` to check if source code has changed since indexing. The `content_verified` field in `_meta` response indicates whether the hash matches.

**When to use:** Before relying on cached symbol data during long sessions, or when modifications have been made.

**Example:**
```python
# In a drift detection hook (PostToolUse on Write/Edit)
# When a .py file is edited, mark it as potentially drifted
# The existing jcodemunch-reindex.py already tracks structural changes
# Enhance it to also track content drift via verify calls

# Claude calls:
# mcp__jcodemunch__get_symbol with verify=true
# Response includes: _meta.content_verified = true/false
# If false: trigger mcp__jcodemunch__index_folder with incremental=true
```

### Anti-Patterns to Avoid

- **Trying to call MCP from hooks:** Hooks are Python subprocesses. They have no MCP client. They MUST output text instructions that Claude reads and acts upon.
- **Modifying GSD templates to be agent42-specific:** GSD templates are global. Any changes should be project-agnostic (check if jcodemunch is available, use it if so, skip if not).
- **Blocking hooks for non-critical guidance:** Context-loader guidance is advisory. Use exit code 0 (allow), not exit code 2 (block). Only jcodemunch-reindex uses blocking for structural changes.
- **Hardcoding repo identifier in templates:** The repo identifier varies by project (e.g., `local/agent42`, `owner/repo`). Templates should detect it dynamically via `mcp__jcodemunch__list_repos`.
- **Replacing mapper agents entirely:** Mapper agents do deep analysis beyond what jcodemunch provides (code quality assessment, concern identification). Use jcodemunch to accelerate their exploration, not replace them.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Code symbol search | Custom grep/AST parsing in hooks | jcodemunch `search_symbols` MCP tool | 11 languages supported, weighted scoring, byte-offset retrieval |
| File structure discovery | Directory walking in hooks | jcodemunch `get_file_tree` / `get_repo_outline` | Annotated with language and symbol counts, filtered by .gitignore |
| Source drift detection | Custom file hash tracking | jcodemunch `get_symbol(verify=true)` | SHA-256 content_hash stored per symbol, O(1) verification |
| Incremental re-indexing | Custom change detection | jcodemunch `index_folder(incremental=true)` | Compares stored file_hashes, only re-parses changed files |
| Symbol-level code retrieval | Full file reads | jcodemunch `get_symbol` / `get_symbols` | Byte-offset seeking, 94-99% token savings vs full file reads |

**Key insight:** jcodemunch already provides all the infrastructure for code understanding. The phase is about plumbing its outputs into the right places (hooks, GSD templates), not building new code analysis capabilities.

## Common Pitfalls

### Pitfall 1: Hook Cannot Call MCP Tools
**What goes wrong:** Developer tries to import MCP client or call jcodemunch directly from context-loader.py. The hook fails silently or crashes.
**Why it happens:** Natural assumption that a Python script can call MCP tools. But hooks run as subprocesses with only stdin/stdout/stderr -- no MCP transport.
**How to avoid:** Output structured text instructions to stderr. Claude reads these and executes the MCP calls itself.
**Warning signs:** ImportError for MCP packages, timeout errors, no output from hook.

### Pitfall 2: GSD Templates Are Global, Not Project-Specific
**What goes wrong:** Modifying GSD templates with hardcoded agent42-specific references (repo name, file paths) that break other projects.
**Why it happens:** Phase scope is agent42, but GSD lives in `~/.claude/get-shit-done/` and serves all projects.
**How to avoid:** Make template changes conditional: check if jcodemunch is available via `list_repos`, detect repo name dynamically. Use "if available" guards.
**Warning signs:** Other projects fail after GSD template changes.

### Pitfall 3: Repo Identifier Format for Local Projects
**What goes wrong:** Using wrong repo identifier format. Local projects use `local/{folder-name}` (with hyphens replacing spaces), not `owner/repo`.
**Why it happens:** jcodemunch uses different ID formats for GitHub repos vs local folders.
**How to avoid:** Agent42 repo identifier is `local/agent42`. For GSD templates, always call `list_repos` first and use the returned identifier.
**Warning signs:** "Repository not found" errors from jcodemunch.

### Pitfall 4: Context-Loader Timeout
**What goes wrong:** Adding too many jcodemunch guidance items bloats context-loader output, or trying to do synchronous processing pushes past the 30s timeout.
**Why it happens:** The hook has a 30-second timeout. It should be fast (detect work type + output guidance).
**How to avoid:** Keep context-loader lightweight -- it only outputs INSTRUCTIONS for Claude to call MCP tools. The actual MCP calls happen later in Claude's context.
**Warning signs:** Hook timeout warnings in Claude Code.

### Pitfall 5: Drift Detection False Positives
**What goes wrong:** Triggering re-index on every minor edit, causing unnecessary delays.
**Why it happens:** Every `Write`/`Edit` tool call changes files, but not all changes affect indexed symbols.
**How to avoid:** Only check drift for files in the jcodemunch index (Python files in source directories, not config files or docs). Batch drift checks rather than checking per-edit.
**Warning signs:** Re-index prompts appearing constantly during normal development.

### Pitfall 6: GSD Workflow Subagent Context Size
**What goes wrong:** Injecting large jcodemunch outputs (full file outlines, many symbol results) into subagent prompts overwhelms context.
**Why it happens:** `get_file_outline` for a large file can return hundreds of symbols. Injecting all of them bloats the prompt.
**How to avoid:** Limit search results (`max_results: 10`), filter by relevant `kind` and `file_pattern`, summarize outlines rather than including raw output.
**Warning signs:** Subagent performance degrades, context window warnings.

## Code Examples

### Context-Loader Enhancement (Indirect MCP Guidance)

```python
# Source: Derived from existing context-loader.py + jcodemunch-reindex.py pattern

# Map work types to jcodemunch tool call recommendations
JCODEMUNCH_GUIDANCE = {
    "tools": [
        {
            "tool": "search_symbols",
            "params": {"query": "Tool", "kind": "class", "file_pattern": "tools/**/*.py"},
            "purpose": "Understand existing tool API surface before making changes",
        },
        {
            "tool": "get_file_outline",
            "params": {"file_path": "tools/base.py"},
            "purpose": "Review Tool/ToolExtension ABC interface",
        },
    ],
    "security": [
        {
            "tool": "search_symbols",
            "params": {"query": "sandbox", "file_pattern": "core/**/*.py"},
            "purpose": "Map security-related symbols before editing",
        },
    ],
    "providers": [
        {
            "tool": "get_file_outline",
            "params": {"file_path": "providers/registry.py"},
            "purpose": "Review ProviderSpec/ModelSpec patterns",
        },
    ],
    # ... more work types
}

def emit_jcodemunch_guidance(work_types, repo_id="local/agent42"):
    """Output jcodemunch MCP tool call recommendations to stderr."""
    guidance_items = []
    for wt in work_types:
        for item in JCODEMUNCH_GUIDANCE.get(wt, []):
            params = item["params"].copy()
            params["repo"] = repo_id
            param_str = "\n".join(f"    {k}: {json.dumps(v)}" for k, v in params.items())
            guidance_items.append(
                f"  - {item['purpose']}:\n"
                f"    mcp__jcodemunch__{item['tool']}:\n{param_str}"
            )

    if guidance_items:
        print(
            "[context-loader] Recommended jcodemunch calls for this work type:\n"
            + "\n".join(guidance_items),
            file=sys.stderr,
        )
```

### GSD Plan Template with Implementation Targets

```markdown
# Source: Enhancement to phase-prompt.md template

<implementation_targets>
<!-- Populated by execute-plan.md orchestrator via jcodemunch before spawning executor -->
<!-- Executor receives exact signatures to modify, avoiding blind file exploration -->

From mcp__jcodemunch__get_symbol:
```python
# tools/base.py::Tool#class
class Tool(ABC):
    @property
    @abstractmethod
    def name(self) -> str: ...

    @property
    @abstractmethod
    def description(self) -> str: ...

    async def execute(self, **kwargs) -> ToolResult: ...
```

From mcp__jcodemunch__search_symbols (query="register", kind="function"):
```
agent42.py::_register_tools#method - line 142
tools/plugin_loader.py::discover_plugins#function - line 28
```
</implementation_targets>
```

### Drift Detection Enhancement

```python
# Source: Enhancement to jcodemunch-reindex.py

# In the PostToolUse hook (jcodemunch-token-tracker.py or new hook):
# When a jcodemunch get_symbol call returns content_verified=false,
# emit a re-index recommendation

def check_drift(tool_name, tool_output):
    """Check if jcodemunch response indicates source drift."""
    if "get_symbol" not in tool_name:
        return False

    meta = tool_output.get("_meta", {}) if isinstance(tool_output, dict) else {}
    if meta.get("content_verified") is False:
        return True
    return False
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| GSD mapper reads files sequentially | Mapper agents spawn in parallel, each reading files | GSD v1.0 | 4 parallel agents but each still does sequential file reads |
| Context-loader loads text from lessons.md | Context-loader detects work type, loads lessons + reference docs | Phase 12 (v1.2) | Work-type-aware context but no code structure awareness |
| No drift detection | jcodemunch-reindex.py blocks Stop if structural changes detected | Current (pre-Phase 16) | Catch-up re-index on session end, not during session |
| Full file reads for code understanding | jcodemunch indexed, but usage is manual/ad-hoc | Current | 94-99% token savings when used, but not systematically integrated |

**Deprecated/outdated:**
- None -- all current approaches are functional. Phase 16 enhances them, doesn't replace.

## jcodemunch API Reference (Verified)

### Tools Available (11 total)

| Tool | Parameters | Returns | Token Savings |
|------|-----------|---------|---------------|
| `index_folder` | `path`, `extra_ignore_patterns`, `follow_symlinks` | Index metadata | N/A (indexing) |
| `index_repo` | `url`, `use_ai_summaries` | Index metadata | N/A (indexing) |
| `invalidate_cache` | `repo` | Confirmation | N/A |
| `list_repos` | (none) | All indexed repos with stats | N/A |
| `get_repo_outline` | `repo` | Directory counts, language breakdown, symbol distribution | ~75% |
| `get_file_tree` | `repo`, `path_prefix` | Nested directory tree with annotations | ~67% |
| `get_file_outline` | `repo`, `file_path` | Hierarchical symbol tree with signatures/summaries | ~95% |
| `get_symbol` | `repo`, `symbol_id`, `verify`, `context_lines` | Full source via byte-offset | ~99% |
| `get_symbols` | `repo`, `symbol_ids` | Batch symbol retrieval | ~99% |
| `search_symbols` | `repo`, `query`, `kind`, `language`, `file_pattern`, `max_results` | Weighted scoring search results | ~99.5% |
| `search_text` | `repo`, `query`, `file_pattern`, `max_results` | Full-text search with line numbers | ~75% |

### Verified: get_symbol verify Parameter

**Confirmed:** The `verify` parameter exists on `get_symbol`. When `verify: true`, jcodemunch re-hashes the source file content and compares it to the stored `content_hash` (SHA-256). The response `_meta.content_verified` is `true` if the source matches and `false` if it has drifted since indexing.

**Source:** SPEC.md and USER_GUIDE.md from jgravelle/jcodemunch-mcp GitHub repository.

### Symbol ID Format

```
{file_path}::{qualified_name}#{kind}
```

Examples:
- `tools/base.py::Tool#class`
- `tools/base.py::Tool.execute#method`
- `core/sandbox.py::WorkspaceSandbox.resolve_path#method`
- `core/config.py::Settings#class`

### Incremental Indexing

`index_folder` defaults to `incremental: true`. It compares stored `file_hashes` (per-file SHA-256) with current file hashes and only re-parses changed files. The response includes counts of changed, new, and deleted files.

### Repo Identifier for Agent42

The agent42 project is indexed as `local/agent42` (197 files, 4700+ symbols as per CLAUDE.md). This identifier is used in all jcodemunch tool calls.

## Implementation Boundaries

### What This Phase Modifies (Agent42 Codebase)

1. **`.claude/hooks/context-loader.py`** -- Add jcodemunch guidance output based on detected work types
2. **`.claude/hooks/jcodemunch-reindex.py`** -- Add mid-session drift detection logic (or create new hook)
3. **`.claude/settings.json`** -- Register any new hooks if needed

### What This Phase Modifies (Global GSD Infrastructure)

4. **`~/.claude/get-shit-done/workflows/map-codebase.md`** -- Add jcodemunch pre-fetch step before mapper agents
5. **`~/.claude/get-shit-done/workflows/plan-phase.md`** -- Add codebase_context population step before planner
6. **`~/.claude/get-shit-done/workflows/execute-plan.md`** -- Add implementation_targets population before executor
7. **`~/.claude/get-shit-done/templates/phase-prompt.md`** -- Add `<implementation_targets>` section to PLAN.md template
8. **`~/.claude/get-shit-done/templates/planner-subagent-prompt.md`** -- Add `<codebase_context>` section

### What This Phase Does NOT Touch

- jcodemunch-mcp source code (external package)
- .mcp.json (already configured in Phase 11)
- jcodemunch-token-tracker.py (already functional, may receive minor drift detection addition)
- Agent42 core application code (tools/, core/, providers/, etc.)

## Open Questions

1. **GSD template modification strategy**
   - What we know: GSD templates are global (`~/.claude/get-shit-done/`), shared across all projects
   - What's unclear: Should jcodemunch integration be conditional (check if available) or assumed?
   - Recommendation: Make it conditional -- check `list_repos` in orchestrator workflows, skip jcodemunch steps if not indexed. This keeps templates universal.

2. **Drift detection granularity**
   - What we know: `get_symbol(verify=true)` checks individual symbols. `index_folder(incremental=true)` re-indexes entire project.
   - What's unclear: Should drift detection check every symbol on every edit, or batch-check at intervals?
   - Recommendation: Check only on specific triggers -- when executor starts working on a file, verify symbols in that file. Don't check on every Write/Edit (too noisy).

3. **Context-loader hook output format**
   - What we know: Claude reads stderr output from hooks. The existing pattern is plain text with `[hook-name]` prefix.
   - What's unclear: Should guidance be structured (JSON-like) or natural language instructions?
   - Recommendation: Use structured natural language that Claude can parse -- the existing `jcodemunch-reindex.py` pattern of "Call mcp__jcodemunch__X with: param: value" works well and is already proven.

4. **Repo identifier discovery in GSD templates**
   - What we know: GSD templates serve multiple projects. Agent42 is `local/agent42` but other projects have different identifiers.
   - What's unclear: How to reliably get the correct repo identifier in a GSD workflow
   - Recommendation: In GSD workflow steps, call `mcp__jcodemunch__list_repos` and match by project directory path. The `index_folder` tool creates identifiers from folder names.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | pyproject.toml (asyncio_mode = "auto") |
| Quick run command | `python -m pytest tests/ -x -q` |
| Full suite command | `python -m pytest tests/ -v` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| JCMUNCH-01 | context-loader emits jcodemunch guidance based on work type | unit | `python -m pytest tests/test_context_loader_jcodemunch.py -x` | No -- Wave 0 |
| JCMUNCH-02 | map-codebase workflow includes jcodemunch pre-fetch | manual-only | Manual: run `/gsd:map-codebase` and verify jcodemunch calls | N/A |
| JCMUNCH-03 | planner receives codebase_context block | manual-only | Manual: run `/gsd:plan-phase` and verify context block | N/A |
| JCMUNCH-04 | executor receives implementation_targets block | manual-only | Manual: run `/gsd:execute-plan` and verify targets block | N/A |
| JCMUNCH-05 | drift detection triggers on content_verified=false | unit | `python -m pytest tests/test_jcodemunch_drift.py -x` | No -- Wave 0 |

**Manual-only justification for JCMUNCH-02/03/04:** GSD workflows are markdown templates processed by Claude Code's internal agent system. They cannot be unit tested -- they require running actual Claude Code sessions with MCP tools. Verification is done via manual `/gsd:*` command execution.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_context_loader_jcodemunch.py tests/test_jcodemunch_drift.py -x`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before verification

### Wave 0 Gaps
- [ ] `tests/test_context_loader_jcodemunch.py` -- covers JCMUNCH-01 (context-loader guidance output)
- [ ] `tests/test_jcodemunch_drift.py` -- covers JCMUNCH-05 (drift detection logic)

## Sources

### Primary (HIGH confidence)
- jcodemunch-mcp SPEC.md (GitHub: jgravelle/jcodemunch-mcp) -- Complete API specification for all 11 tools, data models, Symbol dataclass, response envelope
- jcodemunch-mcp USER_GUIDE.md (GitHub: jgravelle/jcodemunch-mcp) -- Tool usage examples, verify workflow, incremental indexing
- jcodemunch-mcp ARCHITECTURE.md (GitHub: jgravelle/jcodemunch-mcp) -- Parser design, storage format, incremental indexing via file_hashes
- `.claude/hooks/context-loader.py` -- Current context-loader implementation (348 lines)
- `.claude/hooks/jcodemunch-reindex.py` -- Current reindex hook with indirect MCP guidance pattern (204 lines)
- `.claude/hooks/jcodemunch-token-tracker.py` -- Current token tracking hook (211 lines)
- `~/.claude/get-shit-done/workflows/map-codebase.md` -- Current mapper workflow (4 parallel agents)
- `~/.claude/get-shit-done/workflows/plan-phase.md` -- Current planner workflow
- `~/.claude/get-shit-done/workflows/execute-plan.md` -- Current executor workflow
- `~/.claude/get-shit-done/templates/phase-prompt.md` -- PLAN.md template format
- `~/.claude/get-shit-done/templates/planner-subagent-prompt.md` -- Planner context template
- `.claude/settings.json` -- Hook registration configuration

### Secondary (MEDIUM confidence)
- jcodemunch-mcp README.md (GitHub) -- Installation, configuration, high-level overview

### Tertiary (LOW confidence)
- None -- all findings verified against source code and official documentation

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH - All components are already installed and configured; no new dependencies
- Architecture: HIGH - Verified by reading all source files for hooks, GSD templates, and jcodemunch API
- Pitfalls: HIGH - Based on direct analysis of hook architecture constraints and GSD template structure
- jcodemunch API: HIGH - Verified against official SPEC.md, USER_GUIDE.md, and ARCHITECTURE.md from GitHub

**Research date:** 2026-03-06
**Valid until:** 2026-04-06 (stable -- jcodemunch API is versioned, hooks are project-controlled)

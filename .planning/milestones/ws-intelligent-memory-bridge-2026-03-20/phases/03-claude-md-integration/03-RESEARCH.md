# Phase 3: CLAUDE.md Integration - Research

**Researched:** 2026-03-18
**Domain:** Python stdlib file manipulation, CLAUDE.md authoring, setup.sh extension
**Confidence:** HIGH

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Memory Read Instructions (INTEG-01)**
- Always search first: CLAUDE.md must instruct Claude to ALWAYS call `agent42_memory search` before answering from memory
- Applies to every memory-related question — no "prefer" or "when you feel like it"
- Unified view: instructions reference `agent42_memory search` only — the tool internally searches both `memory` and `knowledge` collections

**Memory Write Instructions (INTEG-02)**
- Dual-write: Claude must call `agent42_memory store` AND use its built-in auto-memory
- Belt-and-suspenders approach — CC auto-memory still works as backup, Phase 1 hook syncs CC→Qdrant anyway
- Operation-specific instructions: separate guidance for (1) search/recall, (2) store, (3) log

**Setup.sh Generation (INTEG-03)**
- Append section: setup.sh appends a clearly-delimited memory section using markers `<!-- BEGIN AGENT42 MEMORY -->` / `<!-- END AGENT42 MEMORY -->`
- Preserves all user content outside the markers
- Memory section only: does NOT generate broader project instructions
- If no CLAUDE.md exists: create a new file containing just the Agent42 memory section plus a brief header
- Static text: identical for every project — no dynamic substitution
- Template location: multi-line string constant in `setup_helpers.py` alongside `generate_mcp_config()` and `register_hooks()`. One file, stdlib-only

**Idempotency**
- Marker-based replacement: on re-run, find markers and replace everything between them with latest template version
- User content outside markers is preserved
- User edits between markers are overwritten — clear contract: markers = managed by setup.sh
- No hash comparison, no backup, no warning — just replace

### Claude's Discretion
- Exact wording of the memory instructions (as long as "always search first" and "dual-write" semantics are preserved)
- Marker comment format (HTML comments, or another convention that Claude Code won't interpret)
- Whether to add a brief explanation paragraph before the instruction list
- `setup_helpers.py` function name and internal structure
- How `setup.sh` calls the new function (new CLI subcommand or integrated into existing flow)

### Deferred Ideas (OUT OF SCOPE)
- Memory consolidation and dedup — Phase 4
- Full CLAUDE.md template generation (project scaffold, conventions, architecture) — future enhancement, separate workstream
- Bidirectional sync (Qdrant → CC flat files) — out of scope per REQUIREMENTS.md
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| INTEG-01 | CLAUDE.md instructs Claude to use `agent42_memory search` before answering from memory | MCP tool name confirmed as `agent42_memory`; search action confirmed in MemoryTool; template authoring patterns documented |
| INTEG-02 | CLAUDE.md instructs Claude to use `agent42_memory store` alongside its built-in memory writes | Store/log actions confirmed in MemoryTool; dual-write pattern documented |
| INTEG-03 | Setup.sh generates CLAUDE.md memory section automatically when Agent42 is installed | `setup_helpers.py` extension pattern documented; idempotent marker strategy documented; test patterns from `test_setup.py` identified |
</phase_requirements>

---

## Summary

Phase 3 is a pure authoring + tooling phase: write the memory instruction text (the CLAUDE.md section), and wire up `setup.sh` to inject it automatically. There is no new Python library to learn and no new MCP protocol surface to discover — everything builds directly on patterns already established in `scripts/setup_helpers.py`.

The MCP tool name Claude Code sees is `agent42_memory` (the registry adapter in `mcp_registry.py` prefixes all tool names with `agent42_` + the tool's `name` property; `MemoryTool.name` returns `"memory"`). This is the exact string to use in CLAUDE.md instructions. The tool's actions are `search`, `store`, `log`, `recall`, `forget`, `correct`, `strengthen`, `reindex_cc` — only the first three need to appear in the instructions.

The implementation has two deliverables: (1) a `generate_claude_md_section(project_dir)` function in `setup_helpers.py` that appends or replaces the managed section, and (2) a new step in `setup.sh` that calls it after hook registration. Both are small and follow patterns already present in the codebase. The existing `test_setup.py` test class structure provides the direct pattern for new test coverage.

**Primary recommendation:** Add `generate_claude_md_section` to `setup_helpers.py` as a `claude-md` CLI subcommand, add a corresponding step to `setup.sh`, write the static template text with HTML comment markers, and test with the same `tmp_path`-based pattern used by the existing `TestMcpConfigGeneration` and `TestHookRegistration` classes.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| Python stdlib | 3.11+ | File read/write, path manipulation | Required by locked decision: stdlib-only in setup_helpers.py |
| `os.path` | stdlib | Cross-platform path joining | Used throughout setup_helpers.py; established pattern |
| `pathlib.Path` | stdlib | CLAUDE.md path construction | Consistent with rest of codebase |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `pytest` + `tmp_path` | project requirement | Test file injection logic | Every test for generate_claude_md_section |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| HTML comment markers | Custom sentinel string | HTML comments are invisible in rendered Markdown and won't be interpreted by Claude Code; confirmed as the locked decision |
| Static template string | Jinja2 or f-string substitution | Static is locked decision — no dynamic substitution needed |

**Installation:** No new packages. All stdlib.

---

## Architecture Patterns

### Recommended Project Structure

Changes touch exactly three files:

```
scripts/
└── setup_helpers.py     # Add CLAUDE_MD_TEMPLATE constant + generate_claude_md_section() + cli subcommand

setup.sh                 # Add one step after hook registration (line ~118)

tests/
└── test_setup.py        # Add TestClaudeMdGeneration class
```

### Pattern 1: Marker-Based Section Replacement

**What:** Read the target file (or create if absent), find the managed section between HTML comment markers, replace or append it, write back.

**When to use:** Every call to `generate_claude_md_section`. This is the idempotency contract — markers define the managed region.

**Example:**
```python
BEGIN_MARKER = "<!-- BEGIN AGENT42 MEMORY -->"
END_MARKER = "<!-- END AGENT42 MEMORY -->"

CLAUDE_MD_TEMPLATE = f"""{BEGIN_MARKER}
## Agent42 Memory

Agent42 provides a persistent, semantically-searchable memory layer via the `agent42_memory`
MCP tool. The instructions below override Claude Code's default memory behaviour for this
project.

### When to search memory
ALWAYS call `agent42_memory` with action `search` before answering any question that
could draw on past project decisions, user preferences, debugging history, or architectural
choices. Do not rely solely on your context window or built-in memory files.

```
agent42_memory(action="search", content="<your query>")
```

### When to store
After learning something important — a user preference, a project decision, a fix for
a recurring bug — call `agent42_memory` with action `store` IN ADDITION to any
built-in memory write.

```
agent42_memory(action="store", section="<Category>", content="<what to remember>")
```

### When to log
After completing a significant task or resolving a non-obvious problem, call
`agent42_memory` with action `log` to record the event in the project history.

```
agent42_memory(action="log", event_type="task_completed", content="<summary>")
```
{END_MARKER}
"""


def generate_claude_md_section(project_dir: str) -> None:
    claude_md_path = os.path.join(project_dir, "CLAUDE.md")

    if os.path.isfile(claude_md_path):
        with open(claude_md_path, encoding="utf-8") as f:
            original = f.read()
    else:
        original = "# CLAUDE.md\n\n"

    if BEGIN_MARKER in original and END_MARKER in original:
        # Replace existing managed section
        before = original[: original.index(BEGIN_MARKER)]
        after = original[original.index(END_MARKER) + len(END_MARKER) :]
        new_content = before + CLAUDE_MD_TEMPLATE + after
    else:
        # Append managed section
        new_content = original.rstrip("\n") + "\n\n" + CLAUDE_MD_TEMPLATE

    with open(claude_md_path, "w", encoding="utf-8") as f:
        f.write(new_content)
```

### Pattern 2: CLI Subcommand Registration (matches existing style)

**What:** Add a new `elif cmd == "claude-md":` branch to the `if __name__ == "__main__"` block in `setup_helpers.py`.

**Example:**
```python
elif cmd == "claude-md":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} claude-md <project_dir>")
        sys.exit(1)
    project_dir = sys.argv[2]
    generate_claude_md_section(project_dir)
```

### Pattern 3: setup.sh Step (matches existing style)

**What:** Add a step after hook registration (currently line ~117-118 in setup.sh) using the same `info()` + `python3 scripts/setup_helpers.py` pattern.

**Example:**
```bash
# ── CLAUDE.md memory section ─────────────────────────────────────────────────
info "Generating CLAUDE.md memory section..."
python3 scripts/setup_helpers.py claude-md "$PROJECT_DIR"
info "CLAUDE.md updated"
```

### Anti-Patterns to Avoid

- **Greedy marker search:** Use `str.index()` not `str.find()` when you know the marker is present — raises ValueError with a clear message rather than silently using -1
- **Strip without re-adding newline:** `rstrip("\n")` before appending ensures exactly one blank line between user content and the managed section
- **Hardcoding tool action names in comments:** Use the real action names (`search`, `store`, `log`) exactly as defined in `MemoryTool.parameters` enum so Claude can call them without guessing

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| File encoding on Windows | Custom binary read | `open(..., encoding="utf-8")` always | CLAUDE.md is UTF-8 Markdown; Windows may default to cp1252 |
| Path separator handling | `str + "/" + str` | `os.path.join()` | Cross-platform; matches existing setup_helpers.py convention |
| Large file read | Streaming parser | `f.read()` | CLAUDE.md files are small; full read is fine and simpler |

**Key insight:** The entire implementation is string manipulation on a text file. No parsing library, no regex library, no external dependency is needed.

---

## Common Pitfalls

### Pitfall 1: Marker Search When Only One Marker Is Present

**What goes wrong:** If a previous run crashed after writing `BEGIN_MARKER` but before `END_MARKER`, the file is in a partial state. Checking `BEGIN_MARKER in original and END_MARKER in original` handles this by falling through to the append path — which will create a second begin marker. The file becomes malformed.

**Why it happens:** Two-phase write with no rollback.

**How to avoid:** Use a single atomic write. Read full content, build the replacement string entirely in memory, then write once. Never partial-write.

**Warning signs:** Two `BEGIN_MARKER` lines in CLAUDE.md.

### Pitfall 2: Trailing Whitespace Accumulation on Repeated Runs

**What goes wrong:** Each re-run appends extra blank lines before the managed section if the "append" path is taken with imprecise stripping.

**Why it happens:** `rstrip()` only applied to `original`, but `CLAUDE_MD_TEMPLATE` may start with a newline.

**How to avoid:** The template string should NOT start with a newline. The append path does `original.rstrip("\n") + "\n\n" + CLAUDE_MD_TEMPLATE`. The replace path reconstructs `before + template + after`, so `before` ends at the exact index of `BEGIN_MARKER` — no extra stripping needed there either.

### Pitfall 3: Code Fences in Template Corrupt the Outer Markdown

**What goes wrong:** The template contains triple-backtick code fences showing `agent42_memory(...)` examples. If the CLAUDE.md renderer or Claude itself misparses the nesting, the formatting breaks.

**Why it happens:** Triple-backtick fences inside a Python multi-line string need no escaping in the string itself, but the Markdown renderer must handle nested fences correctly.

**How to avoid:** Each code fence in the template is self-contained (opens and closes within the template). Test by rendering the generated CLAUDE.md in a Markdown previewer.

### Pitfall 4: MCP Tool Name in Instructions Does Not Match Runtime Name

**What goes wrong:** CLAUDE.md says `memory(action="search", ...)` but the actual MCP tool name is `agent42_memory`. Claude cannot call it.

**Why it happens:** The tool's Python `name` property returns `"memory"`, but `MCPRegistryAdapter` applies the prefix `agent42_` before exposing it via MCP.

**How to avoid:** Always use `agent42_memory` in the instruction text. Confirmed: `TOOL_PREFIX = "agent42"` in `mcp_registry.py`, so the MCP-visible name is `agent42_memory`.

### Pitfall 5: Windows Line Endings Break setup.sh on VPS

**What goes wrong:** If `setup.sh` is edited on Windows, the new step gets CRLF line endings. The VPS bash interpreter fails on the deploy.

**Why it happens:** Windows editors default to CRLF. Already documented in project pitfalls #119 area.

**How to avoid:** Verify line endings after editing `setup.sh`. The CI/CD path runs `setup.sh` on Linux; CRLF will break it silently.

---

## Code Examples

### Confirmed MCP Tool Name (from mcp_registry.py)
```python
# Source: mcp_registry.py line 18
TOOL_PREFIX = "agent42"

# Tool.name returns "memory" → MCP-visible name becomes "agent42_memory"
# Source: tools/memory_tool.py line 81-82
@property
def name(self) -> str:
    return "memory"
```

### Confirmed MemoryTool Actions (from tools/memory_tool.py)
```python
# Source: tools/memory_tool.py, parameters enum lines 104-113
"enum": [
    "store",
    "recall",
    "log",
    "search",
    "forget",
    "correct",
    "strengthen",
    "reindex_cc",
]
# Phase 3 instructions reference: search, store, log
```

### Existing CLI Subcommand Pattern (from scripts/setup_helpers.py)
```python
# Source: scripts/setup_helpers.py lines 534-557
if cmd == "mcp-config":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} mcp-config <project_dir> [<ssh_alias>]")
        sys.exit(1)
    project_dir = sys.argv[2]
    ssh_alias = sys.argv[3] if len(sys.argv) > 3 else None
    generate_mcp_config(project_dir, ssh_alias)

elif cmd == "register-hooks":
    if len(sys.argv) < 3:
        print(f"Usage: {sys.argv[0]} register-hooks <project_dir>")
        sys.exit(1)
    project_dir = sys.argv[2]
    register_hooks(project_dir)
```

### Existing setup.sh Step Pattern (from setup.sh lines 115-118)
```bash
# Source: setup.sh lines 115-118
# ── Hook registration ────────────────────────────────────────────────────────
info "Registering Claude Code hooks..."
python3 scripts/setup_helpers.py register-hooks "$PROJECT_DIR"
info "Hooks registered"
```

### Existing Test Pattern for setup_helpers (from tests/test_setup.py)
```python
# Source: tests/test_setup.py — TestMcpConfigGeneration class structure
class TestClaudeMdGeneration:
    def test_creates_claude_md_when_absent(self, tmp_path):
        generate_claude_md_section(str(tmp_path))
        claude_md = tmp_path / "CLAUDE.md"
        assert claude_md.exists()
        content = claude_md.read_text()
        assert "<!-- BEGIN AGENT42 MEMORY -->" in content
        assert "<!-- END AGENT42 MEMORY -->" in content
        assert "agent42_memory" in content

    def test_appends_to_existing_claude_md(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text("# My Project\n\nExisting content.\n")
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "My Project" in content
        assert "Existing content." in content
        assert "agent42_memory" in content

    def test_idempotent_on_rerun(self, tmp_path):
        generate_claude_md_section(str(tmp_path))
        first = (tmp_path / "CLAUDE.md").read_text()
        generate_claude_md_section(str(tmp_path))
        second = (tmp_path / "CLAUDE.md").read_text()
        assert first == second

    def test_replaces_managed_section_on_rerun(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# Project\n\n<!-- BEGIN AGENT42 MEMORY -->\nOLD CONTENT\n<!-- END AGENT42 MEMORY -->\n"
        )
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "OLD CONTENT" not in content
        assert "agent42_memory" in content

    def test_preserves_content_outside_markers(self, tmp_path):
        (tmp_path / "CLAUDE.md").write_text(
            "# My Project\n\nBefore section.\n\n"
            "<!-- BEGIN AGENT42 MEMORY -->\nOLD\n<!-- END AGENT42 MEMORY -->\n\n"
            "After section.\n"
        )
        generate_claude_md_section(str(tmp_path))
        content = (tmp_path / "CLAUDE.md").read_text()
        assert "Before section." in content
        assert "After section." in content
        assert "OLD" not in content
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual CLAUDE.md editing by user | setup.sh auto-generates memory section | Phase 3 (this work) | Zero user intervention required |
| Agent42 memory as optional enhancement | Agent42 memory as default-on behavior | Phase 3 | Claude prefers Qdrant-backed search and dual-write by default |

**No deprecated items** — this phase introduces new behavior, not replacing old.

---

## Open Questions

1. **What happens when CLAUDE.md exists but is owned by root or read-only?**
   - What we know: `open(..., "w")` will raise `PermissionError`
   - What's unclear: Whether to handle this gracefully vs. let it surface
   - Recommendation: Let the exception propagate — `setup.sh` uses `set -e`, so it will stop with a visible error and a useful OS message. No special handling needed.

2. **Should the managed section include a `reindex_cc` instruction?**
   - What we know: The CONTEXT.md specifies only search, store, and log operations in the instructions
   - What's unclear: Whether `reindex_cc` (which catches up on missed sync) should be mentioned
   - Recommendation: Omit it from the template. `reindex_cc` is a one-time catch-up operation, not a regular workflow instruction. It can be documented in Agent42 docs.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest (asyncio_mode = "auto", pyproject.toml) |
| Config file | `pyproject.toml` |
| Quick run command | `python -m pytest tests/test_setup.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| INTEG-01 | Template contains `agent42_memory` search instruction | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_creates_claude_md_when_absent -x` | ❌ Wave 0 |
| INTEG-02 | Template contains `agent42_memory` store + log instructions | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration::test_template_contains_store_and_log -x` | ❌ Wave 0 |
| INTEG-03 | setup.sh-equivalent function creates/updates CLAUDE.md idempotently | unit | `python -m pytest tests/test_setup.py::TestClaudeMdGeneration -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_setup.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_setup.py::TestClaudeMdGeneration` class — covers INTEG-01, INTEG-02, INTEG-03. Add to existing `test_setup.py` (do NOT create a new file). The class needs at minimum: `test_creates_claude_md_when_absent`, `test_appends_to_existing_claude_md`, `test_idempotent_on_rerun`, `test_replaces_managed_section_on_rerun`, `test_preserves_content_outside_markers`, `test_template_contains_store_and_log`.

*(All gaps are in a single existing test file — no new test files required.)*

---

## Sources

### Primary (HIGH confidence)
- `scripts/setup_helpers.py` (codebase) — full function pattern, CLI subcommand pattern, stdlib-only constraint confirmed
- `setup.sh` (codebase) — step insertion point confirmed (after line ~118), info/warn/error function usage confirmed
- `mcp_registry.py` (codebase) — `TOOL_PREFIX = "agent42"` confirmed, tool name prefixing logic confirmed
- `tools/memory_tool.py` (codebase) — `name` property returns `"memory"`, action enum confirmed: search/store/log/recall/forget/correct/strengthen/reindex_cc
- `tests/test_setup.py` (codebase) — test class pattern, `tmp_path` fixture usage, import style confirmed
- `.planning/config.json` (codebase) — `nyquist_validation: true` confirmed

### Secondary (MEDIUM confidence)
- Python docs — `str.index()` vs `str.find()` for known-present substring is well-established stdlib behavior
- HTML comments in Markdown are invisible to renderers and not interpreted by Claude Code — this is the locked decision from CONTEXT.md, supported by general Markdown specification knowledge

### Tertiary (LOW confidence)
- None — all claims are grounded in direct codebase inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — stdlib-only, confirmed in codebase
- Architecture: HIGH — direct pattern match to existing setup_helpers.py functions
- Pitfalls: HIGH — most derived from direct code analysis; MCP tool name pitfall verified against mcp_registry.py

**Research date:** 2026-03-18
**Valid until:** 2026-04-17 (stable codebase; no external dependencies to track)

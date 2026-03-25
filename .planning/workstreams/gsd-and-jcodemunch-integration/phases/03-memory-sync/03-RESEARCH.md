# Phase 3: Memory Sync - Research

**Researched:** 2026-03-24
**Domain:** Python — in-process Markdown diff/merge, UUID-based CRDTs, MemoryStore mutation, ToolContext dependency injection
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Entry format**
- D-01: Each MEMORY.md bullet gets an inline timestamp+short-UUID prefix: `- [2026-03-24T14:22:10Z a4f7b2c1] Content text`. The 8-char hex is the first 8 chars of a UUID4, sufficient for per-file uniqueness during merge.
- D-02: MEMORY.md gets a file-level YAML frontmatter block (`---` delimited) recording the file's own UUID and `last_modified` timestamp. NodeSyncTool uses this for fast coarse conflict detection before doing entry-level diff.
- D-03: The inline `[timestamp uuid]` pattern mirrors HISTORY.md's existing `[timestamp] event_type` convention — one consistent style across both memory files.

**Entry granularity**
- D-04: Each `- ` bullet line is one entry with its own UUID. This is the atom that `append_to_section()` already writes and is the natural unit for union merge.
- D-05: Section headings (`## Section Name`) are structural grouping only — they do not get UUIDs. The merge algorithm operates on bullets within sections.

**Conflict resolution (same-entry edits)**
- D-06: When two nodes have the same UUID but different content, newest wins by timestamp. The older version is appended as an inline history note under the entry: `> [prev: <node>, <timestamp>] <old text>`.
- D-07: This satisfies MEM-02 ("no entry from either node is silently lost") — the older version is demoted, not deleted. Users can clean up history notes at their discretion.
- D-08: When two nodes have entries that don't exist on the other side (different UUIDs), both are kept — standard union merge. This is the common case.

**Legacy entry migration**
- D-09: Auto-migrate on first access — MemoryStore reads old-format bullets (no UUID), assigns UUIDs deterministically via UUID5 from content hash, writes back with the new format. Both nodes independently arrive at the same UUIDs for the same content.
- D-10: Migration is guarded by a sentinel file (`.agent42/memory/.migration_v1`) to prevent race conditions between cc-memory-sync hook and node_sync operating simultaneously.
- D-11: A `node_sync migrate --dry-run` escape hatch is available for operators who want to preview the transformation before it happens automatically.

**Project namespace routing**
- D-12: MemoryTool routes to ProjectMemoryStore via a factory method stored in `ToolContext.extras["project_memory_factory"]`. The factory is a callable `(project_id: str) -> ProjectMemoryStore` that captures `base_dir`, `global_store`, `qdrant_store`, and `redis_backend` at registration time.
- D-13: MemoryTool adds `"project_memory_factory"` to its `requires` list. When `project != "global"`, `execute()` calls the factory and routes all operations through the returned ProjectMemoryStore.
- D-14: The factory maintains an internal `dict[str, ProjectMemoryStore]` cache keyed by `project_id` so repeated calls within a session don't reconstruct stores.
- D-15: When `project == "global"` (the default), existing behavior is unchanged — routes to the global MemoryStore as today. Full backward compatibility per MEM-03.

### Claude's Discretion
- Exact regex pattern for parsing/stripping `[timestamp uuid]` tags during embedding indexing
- Whether to use `uuid.uuid4().hex[:8]` or `uuid.uuid5(namespace, content).hex[:8]` for new entries (both work; uuid5 is deterministic, uuid4 is unique)
- Exact format of the history note for conflict resolution (indented blockquote vs comment)
- Order of migration steps during auto-migrate (parse sections first, then bullets, or single pass)
- How `EmbeddingStore.index_memory()` strips tags before embedding (regex vs split)

### Deferred Ideas (OUT OF SCOPE)
- Real-time memory sync via WebSocket
- Qdrant cluster replication
- Multi-user memory namespaces (ENT-02)
- MEMORY.md auto-update without human review
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| MEM-01 | MEMORY.md entries include a UUID and ISO timestamp so sync can identify individual entries across nodes | D-01 through D-03 define the wire format; `append_to_section()` is the injection point; UUID5 from content gives deterministic IDs for legacy migration |
| MEM-02 | User can run `node_sync merge` and have divergent entries union-merged without silent data loss | `_merge()` in node_sync.py:218 is the replacement target; entry-level union keyed by 8-char UUID handles both "new entry" (D-08) and "same UUID, different content" (D-06) cases |
| MEM-03 | User can call MemoryTool with a `project` parameter and have memories stored/retrieved in a project-scoped namespace | `ProjectMemoryStore` already exists and is complete; `ToolContext.extras` mechanism is already wired and tested; only the factory registration and `requires` expansion in MemoryTool are needed |
</phase_requirements>

---

## Summary

Phase 3 is a tightly bounded refactor across five files with zero new dependencies. All building blocks are present and working — the phase wires them together rather than building new infrastructure.

The UUID/timestamp injection (MEM-01) is a single-function change to `MemoryStore.append_to_section()`. The union merge (MEM-02) replaces the 40-line mtime-wins `_merge()` in `NodeSyncTool` with an entry-level diff that reads MEMORY.md content from both nodes, parses bullet UUIDs, and produces a canonical merged file. The project namespace routing (MEM-03) adds a factory callable to `ToolContext.extras` at MCP server startup and expands MemoryTool's `requires` list — `ProjectMemoryStore` needs no changes.

The highest-complexity piece is the legacy migration (D-09, D-10): auto-migrating old-format bullets on first `read_memory()` access while handling the sentinel file race condition correctly. The merge algorithm itself is straightforward Python string/dict manipulation — no difflib or external library required.

**Primary recommendation:** Implement in four logical units: (1) UUID injection + frontmatter in MemoryStore, (2) auto-migration with sentinel guard, (3) entry-level merge in NodeSyncTool, (4) factory wiring in mcp_server.py and MemoryTool requires expansion.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `uuid` (stdlib) | Python 3.11+ | UUID4 for new entries, UUID5 for deterministic migration IDs | Already used throughout codebase; `a42a42a4-...` namespace in cc-memory-sync-worker.py and memory_tool.py |
| `datetime` (stdlib) | Python 3.11+ | ISO 8601 timestamp generation (`datetime.now(UTC).isoformat()`) | Already imported in `memory/store.py`; `UTC` already in scope |
| `re` (stdlib) | Python 3.11+ | Parse `[timestamp uuid]` prefix from bullet lines during merge and embedding | Zero-dep, already used in the codebase |
| `aiofiles` (existing) | >=23.0.0 | Async file I/O for sentinel file reads/writes if needed | Already in requirements.txt; matches existing async I/O convention |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `asyncio.Lock` (stdlib) | Python 3.11+ | Guard migration sentinel to prevent concurrent migration | Migration guard must be async-compatible; module-level Lock in store.py |
| `pathlib.Path` (stdlib) | Python 3.11+ | Sentinel file `.agent42/memory/.migration_v1` creation/check | Already the project standard for all path operations |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| UUID4 `hex[:8]` for new entries | UUID5 from content | UUID5 is deterministic (same content = same short ID) but collision risk when truncated to 8 chars. UUID4 is guaranteed unique per call, better for new entries. Use UUID5 only for the legacy migration path where determinism is required. |
| SSH `cat` for remote content in merge | rsync temp file dance | SSH cat gets remote content in-memory without filesystem state. `_run_ssh()` already handles timeout and error handling. No temp file cleanup needed. |

**Installation:** No new dependencies required. All changes use stdlib or packages already in requirements.txt.

---

## Architecture Patterns

### Recommended Project Structure
No new files or directories needed. Changes confined to:
```
memory/
  store.py          # append_to_section() UUID injection + _ensure_uuid_frontmatter() + auto-migrate
tools/
  node_sync.py      # _merge() replacement + migrate action
  memory_tool.py    # requires list expansion + project routing logic
mcp_server.py       # factory closure + extras["project_memory_factory"] registration
tests/
  test_memory_sync.py  # NEW: Wave 0 gap — MEM-01, MEM-02, MEM-03 factory fallback
```

### Pattern 1: UUID+Timestamp Bullet Injection

**What:** `append_to_section()` prepends `[ISO_TIMESTAMP SHORT_UUID]` to every new bullet it writes.

**When to use:** Every new bullet written by the agent. NOT applied during bulk `update_memory()` calls (migration and merge write pre-formatted content directly).

**Example:**
```python
# In memory/store.py

import re
import uuid
from datetime import UTC, datetime

def _make_entry_prefix() -> str:
    ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    short_id = uuid.uuid4().hex[:8]
    return f"[{ts} {short_id}]"

def append_to_section(self, section: str, content: str):
    memory = self.read_memory()
    prefix = _make_entry_prefix()
    marker = f"## {section}"
    if marker in memory:
        idx = memory.index(marker) + len(marker)
        nl = memory.index("\n", idx) if "\n" in memory[idx:] else len(memory)
        memory = memory[:nl] + f"\n- {prefix} {content}" + memory[nl:]
    else:
        memory += f"\n## {section}\n\n- {prefix} {content}\n"
    self.update_memory(memory)
```

### Pattern 2: YAML Frontmatter for File-Level Identity

**What:** `_ensure_uuid_frontmatter()` adds a `---`-delimited block at the top of MEMORY.md with a stable file UUID and `last_modified`. Called at the end of `update_memory()`.

**Key invariant:** The `file_id` is set once on file creation and never changes. Only `last_modified` is updated on each write.

**Example:**
```python
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n", re.DOTALL)

def _ensure_uuid_frontmatter(self, content: str) -> str:
    now = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    m = _FRONTMATTER_RE.match(content)
    if m:
        existing = m.group(1)
        lines = existing.splitlines()
        file_id = next(
            (l.split(":", 1)[1].strip() for l in lines if l.startswith("file_id:")),
            uuid.uuid4().hex
        )
        new_fm = f"---\nfile_id: {file_id}\nlast_modified: {now}\n---\n"
        return new_fm + content[m.end():]
    else:
        return f"---\nfile_id: {uuid.uuid4().hex}\nlast_modified: {now}\n---\n{content}"
```

### Pattern 3: Entry-Level Union Merge in NodeSyncTool

**What:** `_merge()` fetches remote MEMORY.md content via SSH, parses both local and remote into dicts keyed by 8-char UUID, resolves conflicts (newest timestamp wins), then writes the merged result back to both nodes.

**Critical change from current code:** The current `_merge()` uses file `stat` to compare mtimes. The new approach fetches remote file content via `ssh host cat file` to perform entry-level diff in memory, then writes merged content back.

**Parse helper:**
```python
_ENTRY_RE = re.compile(
    r"^- \[(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z) ([0-9a-f]{8})\] (.+)$"
)

def _parse_memory_entries(content: str) -> dict:
    """Returns {short_uuid: {ts, content, section}} for UUID-format bullets only."""
    entries = {}
    current_section = ""
    for line in content.replace("\r\n", "\n").splitlines():
        if line.startswith("## "):
            current_section = line[3:].strip()
        elif m := _ENTRY_RE.match(line):
            ts, short_id, text = m.group(1), m.group(2), m.group(3)
            entries[short_id] = {"ts": ts, "content": text, "section": current_section}
    return entries
```

**Conflict resolution:**
```python
def _resolve_entry_conflict(local: dict, remote: dict) -> dict:
    if local["ts"] >= remote["ts"]:
        winner, loser = local, remote
    else:
        winner, loser = remote, local
    winner = dict(winner)
    winner["content"] = (
        winner["content"]
        + f"\n  > [prev: {loser['ts']}] {loser['content']}"
    )
    return winner
```

**Rebuild MEMORY.md from merged entries (preserving section order):**
```python
def _rebuild_memory(original_content: str, merged_entries: dict) -> str:
    """Rebuild MEMORY.md from merged entry dict, preserving section order."""
    # Extract frontmatter and header from original
    # Re-emit sections in original order, adding remote-only sections at end
    # ... implementation detail left to planner
```

### Pattern 4: ProjectMemoryStore Factory in ToolContext.extras

**What:** A closure registered at MCP server startup captures `memory_dir`, `global_store`, `qdrant_store`, and `redis_backend`. Caches instances by `project_id`.

**Registration in mcp_server.py:**
```python
from memory.project_memory import ProjectMemoryStore

_project_store_cache: dict[str, ProjectMemoryStore] = {}

def _project_memory_factory(project_id: str) -> ProjectMemoryStore:
    if project_id not in _project_store_cache:
        _project_store_cache[project_id] = ProjectMemoryStore(
            project_id=project_id,
            base_dir=memory_dir.parent,  # .agent42/
            global_store=memory_store,
            qdrant_store=qdrant_store,
            redis_backend=redis_backend,
        )
    return _project_store_cache[project_id]

# Pass directly to MemoryTool constructor (not via extras — see note below):
_register(MemoryTool(
    memory_store=memory_store,
    project_memory_factory=_project_memory_factory
) if MemoryTool else None)
```

**IMPORTANT NOTE on injection path:** `MemoryTool` in `mcp_server.py` is constructed directly (not via PluginLoader). The `requires` list is used by PluginLoader only. For direct construction, pass `project_memory_factory` as a constructor kwarg. The `requires` expansion is still needed for custom tools / PluginLoader path.

**MemoryTool changes:**
```python
class MemoryTool(Tool):
    requires = ["memory_store", "project_memory_factory"]

    def __init__(self, memory_store=None, project_memory_factory=None, **kwargs):
        self._store = memory_store
        self._project_factory = project_memory_factory  # None when not registered

    def _get_store(self, project: str):
        if project and project != "global" and self._project_factory:
            return self._project_factory(project)
        return self._store
```

### Pattern 5: Auto-Migration with Sentinel Guard

**What:** On `read_memory()` when MEMORY.md has old-format bullets, the store migrates in-place and writes sentinel `.agent42/memory/.migration_v1`.

**Key design point:** The asyncio.Lock prevents concurrent migration. The sentinel file persists across restarts. Both together make migration idempotent and race-free.

```python
import asyncio
_MIGRATION_LOCK = asyncio.Lock()
_ENTRY_NO_UUID_RE = re.compile(r"^(- )(?!\[)(.+)$")

async def _maybe_migrate(self):
    sentinel = self.workspace_dir / ".migration_v1"
    if sentinel.exists():
        return
    async with _MIGRATION_LOCK:
        if sentinel.exists():
            return  # Another coroutine migrated while we waited
        content = self.memory_path.read_text(encoding="utf-8")
        namespace = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
        ts = datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")

        def _migrate_line(line: str) -> str:
            m = _ENTRY_NO_UUID_RE.match(line)
            if not m:
                return line
            text = m.group(2)
            short_id = uuid.uuid5(namespace, text).hex[:8]
            return f"- [{ts} {short_id}] {text}"

        migrated = "\n".join(_migrate_line(l) for l in content.splitlines())
        self.memory_path.write_text(migrated, encoding="utf-8")
        sentinel.write_text("migrated\n", encoding="utf-8")
        logger.info("MEMORY.md migrated to UUID format")
```

### Anti-Patterns to Avoid

- **Injecting UUIDs in `update_memory()`:** `update_memory()` is the bulk-replace path used by merge, migration, and `correct()`. It must write pre-formatted content as-is. Only `append_to_section()` should inject UUID prefixes on new content.
- **Using rsync for merge content transfer:** The new merge reads remote content via `ssh host cat` to get text in-memory for diffing. rsync adds filesystem temp state that requires cleanup.
- **Registering factory as a typed `ToolContext` field:** `project_memory_factory` is an optional callable, not a standard subsystem. Correct placement is `extras["project_memory_factory"]` for PluginLoader path; direct kwarg for mcp_server.py direct construction.
- **Stripping frontmatter before calling `update_memory()`:** `update_memory()` must call `_ensure_uuid_frontmatter()` after writing so frontmatter is always present regardless of what content is passed in.
- **Forgetting to normalize CRLF in remote SSH content:** The `_run_ssh()` decode does not normalize line endings. Always call `.replace("\r\n", "\n")` on remote content before line parsing.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| UUID generation | Custom ID scheme | `uuid.uuid4().hex[:8]` (new entries) / `uuid.uuid5(ns, text).hex[:8]` (migration) | Stdlib; matches existing `a42a42a4-...` namespace pattern already in codebase |
| YAML frontmatter parsing | Full YAML parser | Simple `key: value` line scan (already implemented in `cc-memory-sync-worker.py:parse_frontmatter()`) | PyYAML not in requirements.txt; the 4-field frontmatter does not need a full parser |
| Remote content fetch | rsync temp file | `ssh host cat file` via existing `_run_ssh()` | Avoids filesystem state; `_run_ssh()` already handles timeout and error |
| Per-project store cache | cachetools or Redis | `dict[str, ProjectMemoryStore]` closure in factory | ~3 lines, no deps, lifetime follows the MCP server process |

---

## Common Pitfalls

### Pitfall 1: Migration Race Between CC Hook and Node Sync

**What goes wrong:** `cc-memory-sync.py` spawns a background worker when MEMORY.md is written. If the worker reads the file while auto-migration is writing it, the worker embeds a partially-migrated file.

**Why it happens:** The PostToolUse hook fires immediately after Write/Edit — the background worker can start before `_maybe_migrate()` finishes writing.

**How to avoid:** Sentinel file (D-10) + `asyncio.Lock` (Pattern 5). The `cc-memory-sync-worker.py` calls `parse_frontmatter()` which handles pre-migration files gracefully (returns empty dict for new frontmatter fields — no-op).

**Warning signs:** MEMORY.md contains a mix of `- [ts uuid]` and bare `- ` bullets after the first migration pass.

### Pitfall 2: Frontmatter Lost After `correct()` or `forget()`

**What goes wrong:** `correct()` and `forget()` in MemoryTool split content by lines, filter/replace sections, then rejoin — the frontmatter `---` block is treated as ordinary lines and may be stripped.

**Why it happens:** Line-manipulation code doesn't special-case the frontmatter block.

**How to avoid:** `update_memory()` calls `_ensure_uuid_frontmatter()` after writing. Even if frontmatter is stripped by the caller, it is re-added automatically.

**Warning signs:** `parse_frontmatter(content)` returns `{}` after a `correct` or `forget` operation.

### Pitfall 3: SSH `cat` Returns CRLF on Some Environments

**What goes wrong:** `_run_ssh()` returns stdout decoded with `errors="replace"` without normalizing line endings. The `_ENTRY_RE` regex fails to match lines ending with `\r`.

**Why it happens:** `asyncio.create_subprocess_exec` returns raw bytes; `.decode()` doesn't normalize line endings.

**How to avoid:** Apply `.replace("\r\n", "\n")` on remote content before parsing. Add this at the top of the merge helper.

**Warning signs:** `_parse_memory_entries()` returns empty dict even though MEMORY.md visually has UUID-format bullets.

### Pitfall 4: `project_memory_factory=None` Silently Falls Back to Global Store

**What goes wrong:** MemoryTool with `project_memory_factory=None` (e.g., when running via agent42.py dashboard path which doesn't pass the factory) silently routes all project-scoped writes to the global store.

**Why it happens:** `_get_store()` correctly falls back to `self._store` when factory is None — but this means project isolation is silently broken in the dashboard path.

**How to avoid:** Log a warning when `project != "global"` but `self._project_factory is None`. The dashboard path (agent42.py) should also register the factory if it ever needs project scoping.

**Warning signs:** `memory(action="store", project="myproject")` stores to global MEMORY.md without error.

### Pitfall 5: Embedding Tags Appear in Semantic Search Results

**What goes wrong:** `EmbeddingStore.index_memory()` chunks MEMORY.md by lines and embeds them raw. After migration, every line starts with `[2026-03-24T14:22:10Z a4f7b2c1]`, which pollutes the vector's semantic content.

**Why it happens:** `index_memory()` does not strip metadata prefixes before generating vectors.

**How to avoid:** Strip the `[timestamp uuid]` prefix before embedding. Regex: `r"^\[[\w\-:]+\s+[0-9a-f]{8}\]\s*"`. Apply in `index_memory()` before passing text to the embedder. Keep the full text (with prefix) in the stored payload for display.

**Warning signs:** Semantic search returns poor results for queries that previously matched well.

### Pitfall 6: Merge Rewrites Section Order

**What goes wrong:** When assembling merged MEMORY.md from two nodes, sections appear in a different order from the original file.

**Why it happens:** If merged entries are collected in a plain dict keyed by section name, section order may not match the original file.

**How to avoid:** Preserve section order from the local file; append remote-only sections at the end. Use an ordered list of `(section_name, [entries])` tuples when rebuilding the file.

**Warning signs:** User notices MEMORY.md section ordering changed after a merge.

---

## Code Examples

Verified patterns from existing codebase:

### Existing UUID5 namespace (reuse for migration)
```python
# Source: tools/memory_tool.py:618 and .claude/hooks/cc-memory-sync-worker.py:53
namespace = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
# For migration: deterministic short ID from content
short_id = uuid.uuid5(namespace, content_text).hex[:8]
# For new entries: unique short ID
short_id = uuid.uuid4().hex[:8]
```

### Existing frontmatter parser (reuse in merge for coarse conflict detection)
```python
# Source: .claude/hooks/cc-memory-sync-worker.py:77-95
def parse_frontmatter(content: str) -> dict:
    result = {}
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        return result
    for i, line in enumerate(lines[1:], start=1):
        if line.strip() == "---":
            break
        if ":" in line:
            key, _, value = line.partition(":")
            result[key.strip()] = value.strip()
    return result
```

### Existing async SSH helper (use for remote content fetch in merge)
```python
# Source: tools/node_sync.py:99-113
async def _run_ssh(self, host, command, timeout=15):
    proc = await asyncio.create_subprocess_exec(
        "ssh", host, command,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    return proc.returncode, stdout.decode(errors="replace"), stderr.decode(errors="replace")

# Usage in new merge:
rc, remote_content, _ = await self._run_ssh(host, f"cat {REMOTE_MEMORY_DIR}/MEMORY.md")
remote_content = remote_content.replace("\r\n", "\n")  # normalize line endings
```

### ToolContext.extras injection (confirmed working)
```python
# Source: tools/context.py:38-55
@dataclass
class ToolContext:
    extras: dict[str, Any] = field(default_factory=dict)

    def get(self, key: str) -> Any:
        if hasattr(self, key) and key != "extras":
            return getattr(self, key)
        return self.extras.get(key)
    # PluginLoader._instantiate() calls context.get(key) for each item in requires
    # So extras["project_memory_factory"] is injected when requires includes it
```

### MemoryTool direct construction in mcp_server.py (current pattern)
```python
# Source: mcp_server.py:218-224
MemoryTool = _safe_import("tools.memory_tool", "MemoryTool")
_register(MemoryTool(memory_store=memory_store) if MemoryTool else None)
# Change to:
_register(MemoryTool(
    memory_store=memory_store,
    project_memory_factory=_project_memory_factory
) if MemoryTool else None)
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `_merge()` mtime-wins for MEMORY.md | Entry-level union merge keyed by short UUID | Phase 3 (this phase) | Divergent entries on both nodes no longer silently lost |
| No UUID on MEMORY.md bullets | `[ISO_TS 8HEXCHARS]` prefix on each bullet | Phase 3 (this phase) | Enables per-entry identity across nodes |
| MemoryTool `project` param accepted but silently ignored | Routes to ProjectMemoryStore via factory | Phase 3 (this phase) | Project-scoped memories actually isolated |
| MEMORY.md has no file identity | YAML frontmatter with stable `file_id` | Phase 3 (this phase) | Enables coarse conflict detection before entry-level diff |

**Deprecated/outdated by this phase:**
- mtime-based `_merge()` strategy for MEMORY.md: superseded entirely by entry-level merge

---

## Open Questions

1. **What happens if remote MEMORY.md is missing (new node)?**
   - What we know: `ssh cat` returns rc!=0 if file is missing.
   - What's unclear: Should merge create the file on remote or skip?
   - Recommendation: Treat missing remote MEMORY.md as "remote has zero entries" — push local content to remote. Matches existing `_push()` behavior for new node setup.

2. **Should `node_sync migrate` action be separate from auto-migration?**
   - What we know: D-11 says `migrate --dry-run` exists as an escape hatch; D-09 says auto-migrate runs on first `read_memory()` access.
   - Recommendation: Keep `migrate` as an explicit action for diagnostic/dry-run use only. Auto-migration is the primary path that users will experience. The action is mainly for operators who want to preview before it runs.

3. **Does `correct()` need to preserve `[ts uuid]` prefixes on existing entries?**
   - What we know: `correct()` replaces an entire section with new content. The new content likely won't have UUID prefixes.
   - Recommendation: When `correct()` writes replacement content, apply `_make_entry_prefix()` to each bullet line before writing. Document that `correct()` assigns new UUIDs to replacement entries (old UUIDs for that section are retired). This is the safest interpretation of "correct" — it is not a merge, it is a replacement.

---

## Environment Availability

Step 2.6: SKIPPED — phase is pure Python in-process changes. No new external tools, services, or CLI utilities are introduced. The `node_sync merge` action already depends on SSH/rsync at runtime, which is unchanged.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`, `testpaths = ["tests"]`) |
| Quick run command | `python -m pytest tests/test_memory_sync.py tests/test_memory.py tests/test_project_memory.py tests/test_memory_tool.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| MEM-01 | `append_to_section()` writes `[ts uuid]` prefix on new bullets | unit | `python -m pytest tests/test_memory_sync.py::TestUuidInjection -x -q` | Wave 0 gap |
| MEM-01 | `update_memory()` preserves/adds YAML frontmatter | unit | `python -m pytest tests/test_memory_sync.py::TestFrontmatter -x -q` | Wave 0 gap |
| MEM-01 | Auto-migrate converts old bullets to UUID format deterministically | unit | `python -m pytest tests/test_memory_sync.py::TestMigration -x -q` | Wave 0 gap |
| MEM-01 | Sentinel file prevents double migration | unit | `python -m pytest tests/test_memory_sync.py::TestMigrationSentinel -x -q` | Wave 0 gap |
| MEM-02 | `_parse_memory_entries()` parses UUID bullets into dict correctly | unit | `python -m pytest tests/test_memory_sync.py::TestEntryParsing -x -q` | Wave 0 gap |
| MEM-02 | Merge produces union of entries from both nodes (no UUID overlap) | unit | `python -m pytest tests/test_memory_sync.py::TestUnionMerge -x -q` | Wave 0 gap |
| MEM-02 | Merge resolves same-UUID conflict: newest wins, older appended as history note | unit | `python -m pytest tests/test_memory_sync.py::TestConflictResolution -x -q` | Wave 0 gap |
| MEM-03 | MemoryTool with `project="myproject"` routes to project-scoped store | unit | `python -m pytest tests/test_memory_sync.py::TestProjectRouting -x -q` | Wave 0 gap |
| MEM-03 | MemoryTool with no project param routes to global store (backward compat) | unit | `python -m pytest tests/test_memory_sync.py::TestBackwardCompat -x -q` | Wave 0 gap |
| MEM-03 | `project_memory_factory=None` falls back to global store gracefully | unit | `python -m pytest tests/test_memory_sync.py::TestFactoryFallback -x -q` | Wave 0 gap |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_memory_sync.py tests/test_memory_tool.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_memory_sync.py` — new file covering all MEM-01, MEM-02, MEM-03 test classes listed above

*(No framework install needed — pytest + pytest-asyncio already configured with `asyncio_mode = "auto"`.)*

---

## Project Constraints (from CLAUDE.md)

| Directive | Impact on Phase 3 |
|-----------|-------------------|
| All I/O is async (`aiofiles`, `asyncio`) | `_maybe_migrate()` must be `async`; `asyncio.Lock` for migration guard; `append_to_section()` is currently sync (acceptable — matches MemoryStore's existing sync pattern) |
| Never use blocking I/O in tool `execute()` | MemoryTool `execute()` already delegates to async MemoryStore methods; factory dict lookup is sync (O(1) dict read — safe in async context) |
| Graceful degradation — missing services never crash | `project_memory_factory=None` must fall back to global store silently; log warning, do not raise |
| Every new module needs `tests/test_*.py` | New test classes go in `tests/test_memory_sync.py` (Wave 0 gap) |
| `make format && make lint` after changes | Ruff auto-formats on write via PostToolUse hook; no manual step needed in session |
| Frozen dataclass pattern for config | Not applicable — no new config fields needed for Phase 3 |
| ALWAYS validate file paths through `sandbox.resolve_path()` | Not applicable — memory paths are internal `.agent42/memory/` directories hardcoded in MemoryStore, not user-provided paths |

---

## Sources

### Primary (HIGH confidence)
- `tools/node_sync.py` — Full source read; `_merge()` at line 218 confirmed as direct replacement target; `_run_ssh()` at line 99 confirmed as remote content fetch mechanism
- `memory/store.py` — Full source read; `append_to_section()` at line 109 confirmed as UUID injection point; `update_memory()` at line 72 confirmed as frontmatter attachment point; `UTC` already imported
- `tools/memory_tool.py` — Full source read; `requires = ["memory_store"]` at line 75 confirmed; project routing gap in `_handle_store()` at line 237 confirmed (calls `self._store` directly regardless of project param)
- `memory/project_memory.py` — Full source read; `ProjectMemoryStore` complete with all needed methods; no changes needed
- `tools/context.py` — Full source read; `extras` dict confirmed; `get()` checks extras after fields; PluginLoader injects via `context.get(key)` for each item in `requires`
- `.claude/hooks/cc-memory-sync-worker.py` — Source read; `parse_frontmatter()` at line 77 confirmed reusable; UUID5 namespace `a42a42a4-...` confirmed same as memory_tool.py line 618
- `mcp_server.py:100-260` — Source read; MemoryTool registered at line 224 directly (not via PluginLoader); NodeSyncTool at line 244; both are the registration sites to update

### Secondary (MEDIUM confidence)
- `tests/test_memory.py`, `tests/test_project_memory.py` — Source read; test patterns confirmed (class-based, `tmp_path` fixture, no hardcoded paths); `test_memory_tool.py` exists
- Existing MEMORY.md in `.agent42/memory/` — Inspected; confirmed old-format bullets (no UUIDs) are present in production, validating the need for migration path

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries are stdlib or existing deps; no new packages needed
- Architecture: HIGH — all code patterns verified against actual source files; no assumptions made
- Pitfalls: HIGH — derived from reading actual code paths and their interactions
- Test map: HIGH — existing test files confirmed, gaps identified explicitly

**Research date:** 2026-03-24
**Valid until:** 2026-06-01 (stable Python stdlib, no fast-moving external dependencies)

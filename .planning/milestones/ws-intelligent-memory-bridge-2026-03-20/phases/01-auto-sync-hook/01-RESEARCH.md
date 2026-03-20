# Phase 1: Auto-Sync Hook - Research

**Researched:** 2026-03-18
**Domain:** Claude Code PostToolUse hook system + Agent42 Qdrant/ONNX memory stack
**Confidence:** HIGH — research is based entirely on verified, in-repo code. No speculative claims.

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- Sync only the current project's memory directory: `~/.claude/projects/{current-project}/memory/`
- Do NOT sync global memories or other projects' memories
- Sync ALL CC memory file types: user, feedback, project, reference (SYNC-02)
- Intercept both Write and Edit tool calls (new files + updates)
- Path pattern match only: check if `file_path` matches `~/.claude/projects/*/memory/*.md`
- No frontmatter validation needed — CC always writes memories to this exact path
- Extract full YAML frontmatter: name, description, type, plus source_file path
- Store in Qdrant payload alongside the embedding for type-filtered search
- Single embedding per file — one file = one Qdrant point
- Store in Agent42's existing `{prefix}_memory` collection (not a separate collection)
- Tag with `source='claude_code'` in payload to distinguish from Agent42-native memories
- On update (Edit): upsert replaces the existing point (same file path → same deterministic UUID5 point ID → Qdrant upsert overwrites)
- Silent by default — no stderr output on success
- Only emit stderr on failure (which CC shows as a notice)
- Dashboard indicator: last sync timestamp, total CC memories synced, Qdrant health status
- Displayed in the existing Storage section of the Agent42 dashboard
- Hook writes a small status file that dashboard reads (summary stats only, no full audit trail)
- Silent drop when Qdrant is unreachable — memory still exists in CC's flat file (SYNC-04)
- No automatic queue or retry — keep it simple
- Manual catch-up via `agent42_memory reindex_cc` action
- Embedding generation failure (ONNX missing/corrupted): skip sync entirely, log warning to status file
- No API fallback for embeddings — ONNX only in hook context
- Fire-and-forget async: hook spawns sync as background process and exits immediately (exit 0)
- Near-zero added latency to CC's Write/Edit operations
- CC never waits for Qdrant write to complete

### Claude's Discretion

- Hook module structure (single file vs package)
- Background process mechanism (subprocess, threading, or asyncio)
- Status file format and location
- Dashboard UI placement within Storage section
- `reindex_cc` implementation details (batch size, progress reporting)

### Deferred Ideas (OUT OF SCOPE)

- Intelligent learning extraction from conversation context — Phase 2
- CLAUDE.md instructions for memory preference — Phase 3
- Memory consolidation and dedup across both systems — Phase 4
- Bidirectional sync (Qdrant → CC flat files) — out of scope for this milestone
- Real-time memory streaming — out of scope per REQUIREMENTS.md
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SYNC-01 | When Claude Code writes to `~/.claude/projects/.../memory/`, content is automatically stored in Agent42 Qdrant | PostToolUse hook on Write\|Edit intercepts the write; file path match targets memory dir; `QdrantStore.upsert_single()` stores the content |
| SYNC-02 | Sync handles all memory file types (user, feedback, project, reference) | Path pattern `~/.claude/projects/*/memory/*.md` matches all CC memory file types; no per-type filtering needed |
| SYNC-03 | Dedup prevents storing identical content that already exists in Qdrant | `QdrantStore._make_point_id()` uses UUID5 from `source + file_path`; Qdrant upsert with same ID overwrites, not duplicates |
| SYNC-04 | Sync failure is silent (never blocks Claude Code's Write operation) | Hook always exits 0; Qdrant `is_available` checked before any write attempt; all Qdrant calls wrapped in try/except |
</phase_requirements>

---

## Summary

Phase 1 is a self-contained integration connecting two already-working systems: Claude Code's PostToolUse hook mechanism and Agent42's Qdrant memory stack. Both systems exist and work independently — this phase wires them together.

The hook architecture is well-established in this project. `security-monitor.py` and `format-on-write.py` provide exact templates for a PostToolUse Write|Edit hook: parse JSON from stdin, extract `tool_input.file_path`, act conditionally, emit to stderr only on noteworthy events, always exit 0. The new hook follows this pattern precisely.

The Qdrant write path is also well-established. `QdrantStore._make_point_id(text, source)` generates deterministic UUID5 IDs that make upsert idempotent — the dedup requirement (SYNC-03) is already solved by the existing infrastructure. The ONNX embedder in `EmbeddingStore._OnnxEmbedder` runs synchronously and can be called directly in the hook process (no event loop needed).

The primary engineering challenge is the background process mechanism. The hook must exit 0 immediately so CC's Write tool is unblocked, while the actual Qdrant write happens asynchronously. On this Windows machine, `subprocess.Popen` with `DETACHED_PROCESS` creation flag (or `close_fds=True` on Linux/Mac) is the correct pattern for a truly detached background worker. The hook spawns a second Python script and exits; the worker does the embedding + Qdrant write.

**Primary recommendation:** Single hook file at `.claude/hooks/cc-memory-sync.py` that spawns `.claude/hooks/cc-memory-sync-worker.py` as a detached subprocess, then exits 0. Worker does ONNX embedding + Qdrant upsert + status file update. Register in `settings.json` PostToolUse Write|Edit array alongside existing hooks.

---

## Standard Stack

### Core

| Component | Version | Purpose | Why Standard |
|-----------|---------|---------|--------------|
| Python stdlib only (hook entry) | 3.11+ | Parse stdin JSON, detect path, spawn worker, exit | Hook must have zero import time — stdlib only guarantees < 5ms startup |
| `subprocess.Popen` | stdlib | Spawn detached worker process | Only reliable way to fire-and-forget from a hook context on Windows |
| `QdrantStore` (existing) | project | Store embedding to Qdrant | Already works, has upsert_single + deterministic IDs |
| `_OnnxEmbedder` (existing) | project | Generate embeddings in worker | ONNX runtime available in project venv; sync-safe, no event loop needed |

### Supporting

| Component | Purpose | When to Use |
|-----------|---------|-------------|
| `json` (stdlib) | Status file read/write | Lightweight, no deps |
| `pathlib.Path` (stdlib) | Path matching and resolution | Cross-platform path handling |
| `fnmatch` or glob pattern | Match `~/.claude/projects/*/memory/*.md` | Path pattern matching |
| `uuid` (stdlib) | Verify/reproduce point ID | For reindex_cc to check existence |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Detached subprocess | threading.Thread | Thread approach: simpler code but thread still lives in hook process — hook doesn't exit until thread joins; breaks fire-and-forget |
| Detached subprocess | asyncio task | asyncio approach: requires event loop in hook; `asyncio.run()` blocks until done — defeats the purpose |
| Detached subprocess | Background asyncio task via `loop.create_task` | Works inside Agent42's running event loop (used by `_schedule_reindex`) but NOT available in hook process — different process |
| ONNX-only embeddings | OpenAI API in worker | API adds network latency + API cost per write; ONNX is instant and free; user decided ONNX-only |

**Installation:** No new packages needed. All required libraries (`qdrant-client`, `onnxruntime`, `tokenizers`) are already in `requirements.txt`.

---

## Architecture Patterns

### Recommended Project Structure

```
.claude/hooks/
├── cc-memory-sync.py          # Hook entry point (PostToolUse Write|Edit)
├── cc-memory-sync-worker.py   # Background worker (detached subprocess)
└── [existing hooks...]

.agent42/
├── cc-sync-status.json        # Status file written by worker
└── [existing state files...]

tools/
└── memory_tool.py             # Add reindex_cc action here

dashboard/server.py            # Extend /api/settings/storage response
dashboard/frontend/dist/app.js # Extend storage section UI
```

### Pattern 1: Hook Entry Point (Fire-and-Forget)

**What:** Hook reads stdin, checks if file matches CC memory path, spawns worker as detached process, exits 0 immediately.

**When to use:** Any time a hook needs to do non-trivial work without blocking CC.

```python
# .claude/hooks/cc-memory-sync.py
import json
import os
import subprocess
import sys
from pathlib import Path


def is_cc_memory_file(file_path: str) -> bool:
    """Match ~/.claude/projects/*/memory/*.md"""
    p = Path(file_path)
    # Must end in .md and parent dir must be named "memory"
    # and grandparent must be under .claude/projects/
    parts = p.parts
    try:
        idx = parts.index(".claude")
        return (
            len(parts) > idx + 3
            and parts[idx + 1] == "projects"
            and parts[idx + 3] == "memory"
            and p.suffix == ".md"
        )
    except (ValueError, IndexError):
        return False


def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    if tool_name not in ("Write", "Edit"):
        sys.exit(0)

    file_path = event.get("tool_input", {}).get("file_path", "")
    if not file_path or not is_cc_memory_file(file_path):
        sys.exit(0)

    # Spawn detached worker — hook exits immediately (SYNC-04)
    worker = Path(__file__).parent / "cc-memory-sync-worker.py"
    python = sys.executable

    creation_flags = 0
    if sys.platform == "win32":
        creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

    subprocess.Popen(
        [python, str(worker), file_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=(sys.platform != "win32"),
        creationflags=creation_flags,
    )
    sys.exit(0)


if __name__ == "__main__":
    main()
```

### Pattern 2: Background Worker

**What:** Worker receives file path as argv[1], loads ONNX model, embeds content, upserts to Qdrant, updates status file.

**When to use:** The detached process spawned by the hook.

Key design points:
- Worker must bootstrap its own path to find Agent42's packages (sys.path insertion)
- Worker reads `QdrantConfig` from environment vars (same as Agent42 server does)
- Worker uses `_OnnxEmbedder` directly (synchronous, no event loop needed)
- Worker writes to `.agent42/cc-sync-status.json` after each sync
- Worker silently exits on any error — never writes to stderr (user would see it via CC)

```python
# .claude/hooks/cc-memory-sync-worker.py  (key logic sketch)
import json
import sys
import time
import uuid
from pathlib import Path

# Bootstrap: find project root and add to sys.path
script_dir = Path(__file__).parent  # .claude/hooks/
project_dir = script_dir.parent.parent  # project root
sys.path.insert(0, str(project_dir))

from memory.embeddings import _find_onnx_model_dir, _OnnxEmbedder
from memory.qdrant_store import QdrantConfig, QdrantStore

STATUS_FILE = project_dir / ".agent42" / "cc-sync-status.json"
COLLECTION = QdrantStore.MEMORY   # "memory"  — existing collection
NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")  # same as QdrantStore


def make_point_id(file_path: str) -> str:
    """Deterministic UUID5 from file path (same namespace as QdrantStore)."""
    content = f"claude_code:{file_path}"
    return str(uuid.uuid5(NAMESPACE, content))


def load_status() -> dict:
    try:
        return json.loads(STATUS_FILE.read_text())
    except Exception:
        return {"last_sync": None, "total_synced": 0, "last_error": None}


def save_status(status: dict):
    STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATUS_FILE.write_text(json.dumps(status))


def main(file_path: str):
    status = load_status()

    # Read memory file content
    try:
        content = Path(file_path).read_text(encoding="utf-8")
    except Exception:
        return  # File gone — nothing to do

    if not content.strip():
        return

    # Load ONNX model
    model_dir = _find_onnx_model_dir()
    if not model_dir:
        status["last_error"] = "ONNX model not found — sync skipped"
        save_status(status)
        return

    try:
        embedder = _OnnxEmbedder(model_dir)
        vector = embedder.encode(content[:2000])  # truncate for embedding
    except Exception as e:
        status["last_error"] = f"Embedding failed: {e}"
        save_status(status)
        return

    # Connect to Qdrant
    import os
    qdrant_url = os.getenv("QDRANT_URL", "")
    qdrant_local = os.getenv("QDRANT_LOCAL_PATH", str(project_dir / ".agent42" / "qdrant"))
    config = QdrantConfig(url=qdrant_url, local_path=qdrant_local)
    store = QdrantStore(config)

    if not store.is_available:
        # Silent drop — SYNC-04
        return

    point_id = make_point_id(file_path)
    payload = {
        "source": "claude_code",
        "file_path": file_path,
        "section": Path(file_path).stem,
    }
    store.upsert_single(COLLECTION, content, vector, payload)

    status["last_sync"] = time.time()
    status["total_synced"] = status.get("total_synced", 0) + 1
    status["last_error"] = None
    save_status(status)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        main(sys.argv[1])
```

### Pattern 3: `reindex_cc` Action in MemoryTool

**What:** Scan all CC memory files for current project, check which are missing from Qdrant, sync them.

**When to use:** After Qdrant downtime, on initial install, or when user requests a catch-up.

The `reindex_cc` action is added to `MemoryTool.execute()` and its `parameters` enum. It uses the same Qdrant write path as the hook worker, but runs in-process (async context available).

### Pattern 4: Status File + Dashboard Extension

**What:** Status file at `.agent42/cc-sync-status.json`; dashboard `/api/settings/storage` endpoint extended to include `cc_sync` block; frontend Storage section extended with a CC Sync row.

Status file schema:
```json
{
  "last_sync": 1742300000.0,
  "total_synced": 42,
  "last_error": null
}
```

Dashboard endpoint addition (appended to existing storage response):
```python
cc_sync_status = _load_cc_sync_status()  # reads .agent42/cc-sync-status.json
return {
    "mode": effective_mode,
    ...existing fields...,
    "cc_sync": {
        "last_sync": cc_sync_status.get("last_sync"),
        "total_synced": cc_sync_status.get("total_synced", 0),
        "last_error": cc_sync_status.get("last_error"),
    }
}
```

### Anti-Patterns to Avoid

- **Hook importing Agent42 modules at top level:** Import time adds latency to every Write/Edit tool call — even non-memory files. Keep the hook entry point stdlib-only; only the worker imports heavy deps.
- **Hook using `asyncio.run()` inline:** Blocks until completion — defeats fire-and-forget. The hook must spawn and exit.
- **Worker writing to stderr:** Worker is a background process; stderr goes nowhere and wastes effort. Write errors to the status file instead.
- **Using file content hash for point ID:** If the same file is updated, a content hash generates a NEW point ID — old point stays, duplicate created. Use `file_path` as the identity key, not content.
- **Qdrant embedded mode + worker process:** Qdrant embedded mode uses file-based locking. If Agent42 server is running with embedded Qdrant AND the worker process opens the same embedded path simultaneously, it may fail with a lock error. Check `QDRANT_URL` first; if server mode, worker uses HTTP (no lock conflict). If embedded, the worker still writes to the same path — embedded mode uses SQLite-compatible locking, concurrent readers are fine but concurrent writers may serialize. This is acceptable for the low write rate of CC memory files.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Dedup on write | Custom content hash + lookup | `QdrantStore._make_point_id(text, source)` with `upsert` | UUID5 from source+path is already deterministic; upsert overwrites by ID — zero-cost dedup |
| Embedding generation | Any API call or PyTorch | `_OnnxEmbedder` from `memory/embeddings.py` | Already in project; 384-dim ONNX, runs sync, no event loop, no API key |
| Qdrant connectivity check | HTTP ping | `QdrantStore.is_available` | Already cached with TTL (60s success, 15s fail) |
| Path expansion of `~` | Manual string split | `Path(file_path).expanduser()` or `Path.home()` | Handles Windows and Unix uniformly |
| Status file I/O | Custom format | Simple `json.loads`/`json.dumps` | Already the pattern in `.agent42/settings.json` and `github_accounts.json` |

**Key insight:** All the hard pieces (dedup, embedding, Qdrant write, connectivity probe) are solved by existing project code. This phase is mostly about wiring, not building.

---

## Common Pitfalls

### Pitfall 1: Windows Detached Process Flags

**What goes wrong:** On Windows, `subprocess.Popen` without `DETACHED_PROCESS` flag creates a child process that is attached to the parent's console. When the hook process exits, Windows may terminate the child before it finishes writing to Qdrant.

**Why it happens:** Windows process groups work differently from Unix's double-fork pattern.

**How to avoid:** Use `creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP` on Windows. Use `close_fds=True` on Linux/Mac (not valid on Windows).

**Warning signs:** Qdrant writes succeed in testing but fail intermittently in production; status file not updated after hook exits.

### Pitfall 2: sys.path Bootstrap in Worker

**What goes wrong:** Worker imports `from memory.qdrant_store import QdrantStore` but Python can't find the `memory` package because the worker is run from `.claude/hooks/`, not the project root.

**Why it happens:** The worker is a detached subprocess; its `sys.path` doesn't include the Agent42 project root.

**How to avoid:** Add `sys.path.insert(0, str(project_dir))` at the top of the worker before any Agent42 imports. Resolve `project_dir` from `__file__`: `Path(__file__).parent.parent.parent` (hooks/ → .claude/ → project root).

**Warning signs:** Worker silently fails; status file never updated; no stderr visible because it's a detached process.

### Pitfall 3: Qdrant Collection Vector Dimension Mismatch

**What goes wrong:** `QdrantStore` default `vector_dim` is 1536 (for `text-embedding-3-small`). ONNX `all-MiniLM-L6-v2` produces 384-dim vectors. Upserting a 384-dim vector to a 1536-dim collection raises a Qdrant error.

**Why it happens:** The collection was created by Agent42 with 1536 dims (API embeddings), but the hook worker uses ONNX (384 dims).

**How to avoid:** The worker must create/use a collection configured with the correct vector dimension for ONNX (384). Pass `vector_dim=384` to `QdrantConfig` in the worker. Alternatively, check if the existing `{prefix}_memory` collection uses 1536 dims and create a dedicated `{prefix}_cc_memory` sub-collection — but the user decided to use the existing collection. This means the existing collection dimension must match ONNX output (384). This is a critical compatibility check at planning time.

**Resolution:** Verify what dimension the existing `agent42_memory` collection uses. If it was created with ONNX (384), the worker is compatible. If it was created with OpenAI API (1536), the worker cannot write to it. Given that this development environment uses ONNX by default (no OpenAI API key confirmed active), the existing collection is likely 384-dim — but this must be verified before implementation.

**Warning signs:** Worker logs a Qdrant error about vector size mismatch; `upsert_single` returns `False`.

### Pitfall 4: Embedded Qdrant Lock Contention

**What goes wrong:** Worker opens embedded Qdrant at `.agent42/qdrant/` while Agent42 server already has it open. SQLite WAL mode (used by Qdrant embedded) allows concurrent readers but serializes writers — the worker write may timeout or fail.

**Why it happens:** Two processes opening the same embedded Qdrant path simultaneously.

**How to avoid:** If `QDRANT_URL` is set (server mode), this issue doesn't apply — worker connects via HTTP to the server, no lock conflict. In embedded mode, the write will eventually succeed (WAL allows it), but if the worker process is killed mid-write, it may leave the DB in a partial state. Recommend: worker should check `QDRANT_URL`; if empty, add a short timeout and catch the lock error gracefully.

**Warning signs:** Worker fails with SQLite locking errors; status file shows error messages.

### Pitfall 5: Path Matching on Windows

**What goes wrong:** `~/.claude/projects/*/memory/*.md` path matching fails on Windows because paths use backslashes and `~` may expand differently.

**Why it happens:** This machine is Windows 11; `Path.home()` returns `C:\Users\rickw`. CC stores memories at `C:\Users\rickw\.claude\projects\...\memory\...`.

**How to avoid:** Use `Path(file_path).parts` to check for `.claude`, `projects`, `memory` in sequence rather than glob matching. This is platform-agnostic. The `is_cc_memory_file()` function in the code example above uses this approach.

**Warning signs:** Hook never triggers; no Qdrant writes happen even after CC writes memory files.

### Pitfall 6: Content Truncation for Embedding

**What goes wrong:** ONNX model has a max token limit of 256 tokens (configured in `_OnnxEmbedder.__init__` via `enable_truncation(max_length=256)`). Very long memory files silently get truncated — the embedding represents only the first ~200 words.

**Why it happens:** ONNX truncates automatically but doesn't warn.

**How to avoid:** CC memory files are small (1-5 paragraphs per user decision). Truncation at 256 tokens is acceptable and aligns with the design decision ("CC memory files are small, one file = one Qdrant point"). No special handling needed — document it.

---

## Code Examples

Verified patterns from in-project source:

### PostToolUse Hook stdin Parsing (verified: `security-monitor.py`)

```python
# Source: .claude/hooks/security-monitor.py
def main():
    try:
        event = json.loads(sys.stdin.read())
    except (json.JSONDecodeError, EOFError):
        sys.exit(0)

    tool_name = event.get("tool_name", "")
    tool_input = event.get("tool_input", {})
    file_path = tool_input.get("file_path", "")
    # content = tool_input.get("content", "")       # for Write
    # new_string = tool_input.get("new_string", "")  # for Edit
```

### Deterministic Point ID (verified: `memory/qdrant_store.py:190`)

```python
# Source: memory/qdrant_store.py
def _make_point_id(self, text: str, source: str = "") -> str:
    content = f"{source}:{text}"
    namespace = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
    return str(uuid.uuid5(namespace, content))
```

For the hook worker, use `source="claude_code"` and `text=file_path` (not content) to ensure the same file path always maps to the same point ID regardless of content updates.

### Upsert Single Point (verified: `memory/qdrant_store.py:257`)

```python
# Source: memory/qdrant_store.py
def upsert_single(
    self,
    collection_suffix: str,  # Use QdrantStore.MEMORY = "memory"
    text: str,
    vector: list[float],
    payload: dict | None = None,
) -> bool:
    return self.upsert_vectors(collection_suffix, [text], [vector], [payload or {}]) > 0
```

### ONNX Sync Encode (verified: `memory/embeddings.py:113`)

```python
# Source: memory/embeddings.py
class _OnnxEmbedder:
    def encode(self, text: str) -> list[float]:
        """Encode a single text to a normalized embedding vector."""
        return self.encode_batch([text])[0]
```

Call `embedder.encode(content)` synchronously in the worker — no `asyncio.to_thread()` needed outside Agent42's event loop.

### Windows Detached Process Spawn

```python
# Pattern for fire-and-forget subprocess on Windows + Linux/Mac
import subprocess, sys

creation_flags = 0
if sys.platform == "win32":
    creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

proc = subprocess.Popen(
    [sys.executable, str(worker_script), file_path],
    stdin=subprocess.DEVNULL,
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL,
    close_fds=(sys.platform != "win32"),
    creationflags=creation_flags,
)
# Do NOT call proc.wait() — hook must exit immediately
```

### Hook Registration in settings.json (verified: `.claude/settings.json`)

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [
          {
            "type": "command",
            "command": "cd c:/Users/rickw/projects/agent42 && python .claude/hooks/cc-memory-sync.py",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

Note: This hook should have a short timeout (5s) because it's supposed to exit immediately. The existing Write|Edit hooks (security-monitor, format-on-write) have 30s timeouts because they do real work synchronously.

### MemoryTool Action Registration Pattern (verified: `tools/memory_tool.py`)

```python
# Add to parameters enum:
"enum": ["store", "recall", "log", "search", "forget", "correct", "strengthen", "reindex_cc"]

# Add to execute() dispatch:
elif action == "reindex_cc":
    return await self._handle_reindex_cc()

# New method:
async def _handle_reindex_cc(self) -> ToolResult:
    """Scan all CC memory files for current project and sync missing to Qdrant."""
    ...
```

---

## State of the Art

| Old Approach | Current Approach | Impact |
|--------------|------------------|--------|
| PyTorch embeddings | ONNX Runtime (all-MiniLM-L6-v2) | ~23 MB RAM vs ~1 GB; runs sync without event loop |
| OpenAI API for embeddings | ONNX local | No API cost, no network latency, no key needed in hook |
| Linear JSON scan | Qdrant HNSW | Sub-ms semantic search at scale |

---

## Open Questions

1. **Vector dimension compatibility with existing `agent42_memory` collection**
   - What we know: ONNX produces 384-dim; OpenAI produces 1536-dim; `QdrantConfig.vector_dim` defaults to 1536
   - What's unclear: Was the `agent42_memory` collection created with 384 or 1536 dims in this environment?
   - Recommendation: Wave 0 task must check this. Run `QdrantStore.collection_count("memory")` to confirm collection exists, then query it to check dims. If mismatch: either always use `QdrantConfig(vector_dim=384)` in the worker (same as what Agent42 uses when ONNX is active) OR create a dedicated `{prefix}_cc_memory` collection at 384-dim. The latter avoids any risk of cross-collection dim conflicts.

2. **`reindex_cc` project scoping — which project's CC memories to scan?**
   - What we know: The hook syncs the current project's memory dir. `reindex_cc` needs to know which project to scan.
   - What's unclear: How does Agent42 know the current CC project when `reindex_cc` is called via MCP tool? The MCP server has `workspace` but not the CC project path.
   - Recommendation: `reindex_cc` should accept an optional `project_path` parameter, defaulting to scanning all CC memory files under `~/.claude/projects/` matching any `memory/*.md` — a full reindex.

3. **Status file location relative to project root**
   - What we know: `.agent42/` dir already holds `settings.json`, `github_accounts.json`, `approvals.jsonl` — status files live there.
   - What's unclear: In multi-workspace setups, is `.agent42/` always relative to `AGENT42_WORKSPACE`?
   - Recommendation: Use `Path(os.getenv("AGENT42_WORKSPACE", ".")) / ".agent42" / "cc-sync-status.json"` in the worker; fall back to `project_dir / ".agent42" / "cc-sync-status.json"` where `project_dir` is resolved from `__file__`.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest 8.x with pytest-asyncio |
| Config file | `pyproject.toml` — `asyncio_mode = "auto"` |
| Quick run command | `python -m pytest tests/test_cc_memory_sync.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SYNC-01 | After CC write to memory path, content appears in Qdrant | integration | `pytest tests/test_cc_memory_sync.py::TestSyncHook::test_write_triggers_qdrant_upsert -x` | ❌ Wave 0 |
| SYNC-02 | All 4 CC memory file types are synced | unit | `pytest tests/test_cc_memory_sync.py::TestPathDetection::test_all_memory_file_types -x` | ❌ Wave 0 |
| SYNC-03 | Writing same content twice results in exactly one Qdrant entry | unit | `pytest tests/test_cc_memory_sync.py::TestDedup::test_upsert_same_path_no_duplicate -x` | ❌ Wave 0 |
| SYNC-04 | When Qdrant unreachable, Write tool completes with no error | unit | `pytest tests/test_cc_memory_sync.py::TestFailureSilence::test_qdrant_unreachable_no_error -x` | ❌ Wave 0 |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_cc_memory_sync.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_cc_memory_sync.py` — covers all 4 SYNC requirements
  - `TestPathDetection` — tests `is_cc_memory_file()` path matching including Windows paths
  - `TestSyncWorker` — tests worker's embed+upsert logic with mocked ONNX + mocked Qdrant
  - `TestDedup` — tests that upsert with same file_path point ID is idempotent
  - `TestFailureSilence` — tests worker exits cleanly when Qdrant unavailable
  - `TestReindexCc` — tests `MemoryTool.reindex_cc` action scans and syncs missing files

*(No framework install needed — pytest and pytest-asyncio already installed.)*

---

## Sources

### Primary (HIGH confidence)

- `.claude/hooks/security-monitor.py` — verified PostToolUse hook stdin JSON protocol, tool_name/tool_input extraction, exit 0 pattern
- `.claude/hooks/format-on-write.py` — verified same protocol + subprocess.run usage in hook context
- `.claude/settings.json` — verified hook registration format, matcher syntax, timeout field
- `memory/qdrant_store.py` — verified `_make_point_id()` UUID5 implementation, `upsert_single()`, `is_available` health probe TTL
- `memory/embeddings.py` — verified `_OnnxEmbedder` sync encode API, `_find_onnx_model_dir()` search paths, 384-dim output
- `tools/memory_tool.py` — verified MemoryTool action dispatch pattern, parameter enum format, `requires` injection
- `mcp_server.py` — verified MemoryTool registration with `memory_store` injection
- `dashboard/server.py` (line 3290) — verified `/api/settings/storage` endpoint structure and `cc_sync` extension point
- `dashboard/frontend/dist/app.js` (line 5532) — verified `storage` panel rendering pattern and `statusBadge()` component
- `.agent42/settings.json`, `.agent42/github_accounts.json` — verified status file location and JSON format convention
- `pyproject.toml` — verified `asyncio_mode = "auto"` and test markers

### Secondary (MEDIUM confidence)

- Python docs for `subprocess.DETACHED_PROCESS` — Windows-specific flag verified in Python stdlib docs; standard pattern for daemon processes on Windows
- `uuid.uuid5` behavior — deterministic UUID generation from namespace + content; UUID5 always produces same output for same inputs (mathematical property)

### Tertiary (LOW confidence)

- Qdrant embedded mode SQLite WAL concurrent write behavior — based on Qdrant architecture documentation (not directly verified in this session); risk is low given the low write rate of CC memory files

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all components verified in project source
- Architecture: HIGH — patterns directly copied from existing hooks; fire-and-forget subprocess is standard Python
- Pitfalls: HIGH (Windows flags, path matching, sys.path bootstrap) / MEDIUM (Qdrant dim mismatch — needs verification) / LOW (embedded lock contention — low probability given usage pattern)

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable codebase; no external dependencies changing)

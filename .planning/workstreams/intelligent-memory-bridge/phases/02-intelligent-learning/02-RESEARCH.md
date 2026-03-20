# Phase 2: Intelligent Learning - Research

**Researched:** 2026-03-19
**Domain:** Claude Code Stop hook + LLM extraction + Qdrant knowledge storage
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Extraction Approach**
- LLM-based extraction using instructor + Pydantic structured output
- Route through Agent42's own API endpoint (localhost:8000) — lets Agent42's tiered routing pick the provider (Synthetic, Gemini, free tier, etc.)
- Hook stays provider-agnostic — never hardcodes a specific LLM provider
- If Agent42 API is unreachable (server not running), silently skip extraction entirely — learning is best-effort
- No fallback to direct API calls or heuristics — keep the hook simple

**Learning Types & Schema**
- Extract all 5 types from requirements: decisions (LEARN-01), corrections/feedback (LEARN-02), deployment/debug patterns (LEARN-03), cross-session confidence (LEARN-04), category tagging (LEARN-05)
- One Qdrant point per learning — a session producing 3 learnings creates 3 separate points
- Each learning embeds independently for targeted semantic search
- Store in new dedicated Qdrant collection: `agent42_knowledge` (separate from user-written memories)

**Category Taxonomy**
- Start with 4 categories from requirements: security, feature, refactor, deploy
- LLM can suggest additional categories if a learning doesn't fit the predefined list
- Open-ended but anchored — prevents force-fitting edge cases

**Cross-session Confidence**
- Before storing, search `agent42_knowledge` for semantically similar entries (cosine similarity >= 0.85)
- If match found: boost existing point's confidence (+0.1 per reoccurrence, capped at 1.0) and skip storing the duplicate
- If no match: store as new point
- Initial confidence: LLM-assessed (0.5-1.0) based on how clearly the learning was expressed — definitive "we decided X" gets ~0.9, vague pattern gets ~0.5
- Gradual decay: learnings not recalled in 30+ days lose up to 15% confidence (matches existing Qdrant lifecycle scoring)

**Noise Filtering**
- Minimum threshold: 2+ tool calls AND 1+ file modification — same as effectiveness-learn.py
- LLM decides final relevance: `outcome: trivial` is a valid extraction response — if returned, skip storage
- Send last 20 messages + tool usage summary (tools used, files modified) as extraction context
- For very long sessions (100+ tool calls): truncate to last 20 messages — recent context is most relevant, conclusions matter most
- No additional keyword pre-filtering — the tool/file threshold plus LLM relevance check is sufficient

### Claude's Discretion
- Pydantic model field definitions (exact field names, types, validation rules)
- Agent42 API endpoint path for LLM extraction requests
- Background worker mechanism (subprocess vs threading)
- Status file format and location
- Similarity threshold tuning (0.85 is a starting point, may adjust after testing)
- How to construct the extraction prompt from session messages
- Exact confidence boost/decay parameters

### Deferred Ideas (OUT OF SCOPE)
- Memory consolidation and dedup passes — Phase 4
- Bidirectional sync (Qdrant -> CC flat files) — out of scope for this milestone
- LLM-powered memory summarization for recall — out of scope per REQUIREMENTS.md
- Search/recall UI for learnings in dashboard — future enhancement
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| LEARN-01 | Stop hook extracts architectural decisions from conversation and stores in Qdrant | Hook-to-worker pattern from cc-memory-sync; `agent42_knowledge` collection already declared in QdrantStore.KNOWLEDGE |
| LEARN-02 | Stop hook extracts user feedback/corrections and stores with "feedback" type | Pydantic `learning_type` field with enum including "feedback"; same extraction pipeline as LEARN-01 |
| LEARN-03 | Stop hook extracts deployment/debugging patterns from tool usage | Tool usage summary included in extraction context; category "deploy" maps to this type |
| LEARN-04 | Stop hook detects repeated patterns across sessions (confidence boosting) | `QdrantStore.strengthen_point()` exists; need similarity search before upsert using `search_with_lifecycle()` |
| LEARN-05 | Extraction is category-aware (security, feature, refactor, deploy) | Pydantic `category` field with 4 anchor values + LLM free extension; stored as payload field for filter queries |
</phase_requirements>

---

## Summary

Phase 2 builds a Stop hook that extracts structured learnings from Claude Code sessions and stores them in Qdrant's `agent42_knowledge` collection. The architecture closely mirrors the existing `effectiveness-learn.py` hook and `cc-memory-sync.py` background worker pattern — both proven and tested in the codebase. The main new work is: (1) a richer Pydantic extraction schema with learning_type, category, confidence, and content fields; (2) a new Agent42 API endpoint `/api/knowledge/learn` that handles LLM extraction and Qdrant storage; and (3) cross-session dedup logic that boosts confidence on repeat patterns rather than creating duplicate entries.

The key architectural constraint is that the hook must route LLM calls through Agent42's API at localhost:8000 rather than calling providers directly. This keeps the hook slim (stdlib-only entry point), provider-agnostic, and leverages Agent42's existing tiered routing. The actual instructor + Pydantic extraction runs server-side inside the API endpoint, not in the hook process itself — this is a cleaner separation than `effectiveness-learn.py` which does extraction inline.

The infrastructure is largely in place: `QdrantStore.KNOWLEDGE` constant is declared, `strengthen_point()` handles confidence boosting, `search_with_lifecycle()` handles similarity-based dedup detection, and the background worker spawn pattern from Phase 1 is the established non-blocking approach.

**Primary recommendation:** Build a two-file solution — `knowledge-learn.py` (stdlib-only Stop hook, spawns worker) and `knowledge-learn-worker.py` (calls Agent42 API for extraction + Qdrant storage) — mirroring the Phase 1 cc-memory-sync architecture. Add `/api/knowledge/learn` endpoint to `dashboard/server.py` for server-side instructor extraction.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `instructor` | installed in .venv | Structured LLM output via Pydantic | Already used in `effectiveness-learn.py`; JSON mode with retry |
| `pydantic` | v2 (installed) | Data model validation for extraction schema | Project standard; used everywhere |
| `openai` (client) | installed | OpenAI-compatible client for any provider | Works with Agent42's OpenAI-compat endpoint |
| `qdrant_client` | installed | Qdrant vector storage operations | Project standard; `QdrantStore` wraps it |
| `memory.embeddings._OnnxEmbedder` | local | ONNX local embedding (all-MiniLM-L6-v2, 384 dims) | No external API needed for embedding; same as cc-memory-sync-worker |
| `urllib.request` | stdlib | HTTP call from hook to Agent42 API | No third-party imports in hook entry point |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `subprocess` | stdlib | Detached worker spawn from hook | Hook entry point → worker, same as cc-memory-sync.py |
| `uuid` | stdlib | Deterministic UUID5 point IDs | Dedup: same text → same point ID |
| `time` | stdlib | Timestamps for Qdrant payload fields | lifecycle metadata |
| `json` | stdlib | Stdin hook event parsing, status file I/O | All hook communication |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Routing LLM through Agent42 API | Direct `instructor.from_openai()` in worker | Direct is simpler but violates provider-agnosticism; loses tiered routing; adds key management complexity to hook |
| ONNX embedding in worker | Calling `/api/memory/search` embed endpoint | Self-contained worker is more reliable; no second HTTP roundtrip |
| Background worker subprocess | `threading.Thread` in hook | Subprocess is fully detached on Windows (DETACHED_PROCESS flag) — established pattern in this codebase |

**Installation:** All dependencies already installed in the project's `.venv`.

---

## Architecture Patterns

### Recommended Structure

```
.claude/hooks/
├── knowledge-learn.py          # NEW: Stop hook entry (stdlib-only, spawns worker)
└── knowledge-learn-worker.py   # NEW: Worker: calls /api/knowledge/learn, embeds, upserts
dashboard/
└── server.py                   # MODIFY: add /api/knowledge/learn endpoint
memory/
└── qdrant_store.py             # NO CHANGE: QdrantStore.KNOWLEDGE already exists
tests/
└── test_knowledge_learn.py     # NEW: test suite
```

### Pattern 1: Two-File Hook Architecture (proven in Phase 1)

**What:** Slim stdlib-only entry point + heavier background worker with Agent42 imports.

**When to use:** Any Stop hook that needs Qdrant/ONNX operations without blocking Claude Code's session end.

```python
# knowledge-learn.py (hook entry point — stdlib only)
#!/usr/bin/env python3
# hook_event: Stop
# hook_timeout: 30
import json, subprocess, sys
from pathlib import Path

def main():
    event = json.loads(sys.stdin.read())
    # Noise filter: same as effectiveness-learn.py
    if count_tool_calls(event) < 2 or count_file_modifications(event) < 1:
        sys.exit(0)
    # Spawn detached worker — never block CC on any error
    worker = Path(__file__).parent / "knowledge-learn-worker.py"
    creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP if sys.platform == "win32" else 0
    try:
        subprocess.Popen(
            [sys.executable, str(worker)],
            stdin=open(os.devnull, 'rb'),  # Pass event via temp file instead
            ...
            creationflags=creation_flags,
        )
    except Exception:
        pass
    sys.exit(0)
```

**Important:** The hook receives the full event on stdin. The worker needs the event data. Two options: (a) write event to a temp file and pass the path as arg (cleanest), or (b) pass the event JSON as a command-line arg (works for small events). The cc-memory-sync worker receives the file path as `sys.argv[1]`. For this use case, the event JSON can be large — recommend writing to a temp file in `.agent42/` and passing the path, or passing only the extracted session summary + tool/file lists (pre-processed by the hook before spawning).

### Pattern 2: Agent42 API Endpoint for LLM Extraction

**What:** Server-side instructor + Pydantic extraction via POST to `/api/knowledge/learn`.

**When to use:** When hook needs LLM access but must stay provider-agnostic. Server handles key management and routing.

```python
# dashboard/server.py (new endpoint)
@app.post("/api/knowledge/learn")
async def record_knowledge(request: Request):
    """Extract structured learnings and store in agent42_knowledge Qdrant collection.

    Called by knowledge-learn-worker.py Stop hook. No auth required — local hook only.
    Accepts: {session_summary, tools_used, files_modified, messages_context}
    Returns: {status, learnings_stored, learnings_boosted}
    """
```

### Pattern 3: Pydantic Extraction Schema

**What:** Richer schema than `effectiveness-learn.py`'s 3-field model — captures all 5 requirement types.

```python
from pydantic import BaseModel, Field
from typing import Literal

PREDEFINED_CATEGORIES = ["security", "feature", "refactor", "deploy"]
PREDEFINED_TYPES = ["decision", "feedback", "pattern", "correction", "insight"]

class ExtractedLearning(BaseModel):
    learning_type: Literal["decision", "feedback", "pattern", "correction", "trivial"] = Field(
        description="decision=architectural choice, feedback=user correction, pattern=recurring approach, correction=error fix, trivial=skip"
    )
    category: str = Field(
        description=f"Category tag. Prefer one of: {PREDEFINED_CATEGORIES}. Suggest new if truly different."
    )
    title: str = Field(description="One-line summary of the learning (≤80 chars)")
    content: str = Field(description="The durable learning — specific enough to be useful next session")
    confidence: float = Field(
        ge=0.5, le=1.0,
        description="How clearly expressed: 0.9 for definitive decisions, 0.5 for vague patterns"
    )

class ExtractionResult(BaseModel):
    learnings: list[ExtractedLearning] = Field(
        description="List of 0-5 learnings. Empty list if session was trivial."
    )
```

### Pattern 4: Cross-Session Dedup (Confidence Boosting)

**What:** Before inserting a new learning, search for semantically similar existing entries. Boost on match, skip duplicate.

```python
# In the worker or API endpoint
def dedup_or_store(qdrant: QdrantStore, embedder, learning: dict, threshold=0.85):
    vector = embedder.encode(learning["content"])
    hits = qdrant.search_with_lifecycle(
        QdrantStore.KNOWLEDGE, vector, top_k=3, exclude_forgotten=True
    )
    for hit in hits:
        if hit["raw_score"] >= threshold:
            # Boost existing point instead of creating duplicate (LEARN-04)
            qdrant.strengthen_point(QdrantStore.KNOWLEDGE, hit["point_id"], boost=0.1)
            return "boosted"
    # No match — upsert as new point
    point_id = make_point_id(learning["content"])
    payload = {
        "source": "knowledge_learn",
        "learning_type": learning["learning_type"],
        "category": learning["category"],
        "title": learning["title"],
        "confidence": learning["confidence"],
        "recall_count": 0,
        "status": "active",
        "session_id": session_id,
        "timestamp": time.time(),
    }
    qdrant.upsert_single(QdrantStore.KNOWLEDGE, learning["content"], vector, payload)
    return "stored"
```

**Critical note on similarity threshold:** `search_with_lifecycle()` returns `adjusted_score` (lifecycle-weighted), NOT raw cosine score. For dedup detection, compare against `raw_score` (also returned in the result dict). A 0.85 threshold on raw cosine score is appropriate for semantic dedup.

### Pattern 5: Worker Calls Agent42 API (not direct provider)

**What:** Worker uses `urllib.request` to POST session data to Agent42's API. Server-side handles instructor + LLM call.

```python
# knowledge-learn-worker.py
import urllib.request, json, os

dashboard_url = os.environ.get("AGENT42_DASHBOARD_URL", "http://127.0.0.1:8000")

payload = {
    "session_summary": last_assistant_message,
    "tools_used": tool_names,
    "files_modified": modified_files,
    "messages_context": last_20_messages,  # for richer extraction
}

req = urllib.request.Request(
    f"{dashboard_url}/api/knowledge/learn",
    data=json.dumps(payload).encode("utf-8"),
    headers={"Content-Type": "application/json"},
    method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())
```

**If API unreachable:** `urlopen` raises `URLError`/`ConnectionRefusedError` → catch and exit silently. No fallback. Best-effort by design.

### Anti-Patterns to Avoid

- **Inline LLM calls in hook entry point:** Violates the "stdlib-only entry point" rule and blocks CC's Stop event.
- **Using `adjusted_score` for similarity threshold:** Must use `raw_score` for cosine-based dedup — adjusted score includes lifecycle weighting that distorts the comparison.
- **Hardcoding provider API keys or model names in the hook:** The hook should call `/api/knowledge/learn` with no knowledge of which LLM will handle it.
- **Using `upsert_vectors()` content-hash ID for dedup:** `_make_point_id()` hashes content → same text → same UUID (good for single-call dedup) but content encoding means small wording changes create new points. Cross-session dedup via similarity search is necessary for semantic dedup.
- **Passing the entire event JSON as a subprocess argument:** Windows command-line length limit is ~8191 chars; large sessions will be truncated or fail. Write to temp file or pre-extract the relevant fields before spawning worker.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| LLM structured output | Custom JSON parsing + retry loop | `instructor.from_openai()` with `Mode.JSON` | Handles retries, validation errors, malformed JSON automatically |
| Cosine similarity threshold | Manual vector comparison | `QdrantStore.search_with_lifecycle()` returns `raw_score` | Qdrant does HNSW ANN search efficiently; no manual dot products |
| Confidence boost on recall | Custom update logic | `QdrantStore.strengthen_point(boost=0.1)` | Already implemented, tested, handles retrieve→update atomically |
| Collection creation | Manual Qdrant API calls | `QdrantStore._ensure_collection(KNOWLEDGE)` | Idempotent, handles existing collections, sets correct vector params |
| Point ID generation | Random UUIDs | `uuid.uuid5(NAMESPACE, content)` deterministic | Enables content-based dedup on exact-match entries |
| Worker status tracking | Custom logging | Status JSON file at `.agent42/knowledge-learn-status.json` | Mirrors cc-sync-status.json pattern; visible in dashboard |

**Key insight:** All the hard Qdrant operations are already implemented in `QdrantStore`. The phase is primarily wiring: hook → worker → API → instructor → Qdrant.

---

## Common Pitfalls

### Pitfall 1: Event Data Not Reaching Worker
**What goes wrong:** The Stop hook receives event JSON on stdin, but spawned subprocesses don't inherit stdin. Worker has no event data.
**Why it happens:** `subprocess.Popen()` with `stdin=subprocess.DEVNULL` correctly blocks stdin but provides no data to worker.
**How to avoid:** Pre-extract the relevant fields (last 20 messages, tool names, modified files) in the hook entry point, serialize to a JSON temp file (e.g., `.agent42/knowledge-extract-{uuid}.json`), pass temp file path as `sys.argv[1]` to worker. Worker reads + deletes the temp file on completion.
**Warning signs:** Worker starts but produces no output / status file stays empty.

### Pitfall 2: Wrong Score Field for Dedup
**What goes wrong:** Using `hit["score"]` (adjusted lifecycle score) instead of `hit["raw_score"]` for the 0.85 cosine threshold. Low-confidence old entries get adjusted_score < 0.85 even when semantically identical.
**Why it happens:** `search_with_lifecycle()` returns `score` = adjusted (confidence × recall_boost × decay), `raw_score` = raw cosine similarity. The dedup check needs raw cosine.
**How to avoid:** Explicitly check `hit["raw_score"] >= threshold` in the dedup loop.
**Warning signs:** Identical learnings stored multiple times across sessions.

### Pitfall 3: KNOWLEDGE Collection Lacks Payload Indexes
**What goes wrong:** `_ensure_collection()` only adds payload indexes for MEMORY and HISTORY collections (lines 166-167 in qdrant_store.py). KNOWLEDGE collection doesn't get `task_type`/`task_id` indexes.
**Why it happens:** `_ensure_task_indexes()` is conditionally called based on collection suffix: `if suffix in (self.MEMORY, self.HISTORY)`.
**How to avoid:** Either extend `_ensure_task_indexes()` to include KNOWLEDGE, or add `learning_type` and `category` indexes separately for KNOWLEDGE. Payload indexes are needed for filtered searches (e.g., `search by category="security"`).
**Warning signs:** Filtered knowledge searches return all entries regardless of filter.

### Pitfall 4: instructor Call Blocking in Async Context
**What goes wrong:** `instructor.from_openai(OpenAI(...))` uses sync OpenAI client. Calling it inside an `async def` FastAPI endpoint blocks the event loop.
**Why it happens:** `instructor` wraps synchronous `OpenAI` (not `AsyncOpenAI`) when using `Mode.JSON`.
**How to avoid:** Use `asyncio.get_event_loop().run_in_executor(None, sync_extract_fn)` to run the synchronous instructor call in a thread pool, OR use `instructor.from_openai(AsyncOpenAI(...))` with async client pattern. Check how `/api/effectiveness/learn` handles this — it appears to call the extraction inline; if blocking is observed, move to executor.
**Warning signs:** Dashboard response times spike during learning extraction.

### Pitfall 5: Session Messages Not Accessible in Hook
**What goes wrong:** Hook tries to extract `messages` from the event but the field is missing or truncated.
**Why it happens:** Stop event schema: `{hook_event_name, project_dir, stop_reason, tool_results, messages}`. `messages` contains the full conversation — but for 100+ tool call sessions this can be very large.
**How to avoid:** Send only last 20 messages to the worker (matching CONTEXT.md decision). Extract in hook entry point before serializing to temp file. Use `get_last_assistant_message()` helper (already in effectiveness-learn.py) as model.
**Warning signs:** Extraction produces low-quality learnings or empty results for long sessions.

### Pitfall 6: KNOWLEDGE Collection Vector Dimension Mismatch
**What goes wrong:** Worker creates KNOWLEDGE collection with ONNX 384-dim vectors, but QdrantStore default `vector_dim` is 1536 (text-embedding-3-small). Collection creation uses the wrong dimension.
**Why it happens:** `QdrantConfig` defaults to `vector_dim=1536` (line 49 in qdrant_store.py). `_ensure_collection()` uses `self.config.vector_dim`.
**How to avoid:** Worker must initialize QdrantStore with `QdrantConfig(..., vector_dim=384)` — same as `cc-memory-sync-worker.py` line 150: `config = QdrantConfig(url=..., local_path=..., vector_dim=384)`.
**Warning signs:** `qdrant_client.exceptions.UnexpectedResponse` on first upsert: "Wrong input: Vector inserting error: expected dim: 1536, got 384."

---

## Code Examples

Verified patterns from existing codebase:

### Spawning Detached Background Worker (from cc-memory-sync.py)
```python
# Source: .claude/hooks/cc-memory-sync.py lines 94-107
creation_flags = 0
if sys.platform == "win32":
    creation_flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP

try:
    subprocess.Popen(
        [sys.executable, str(worker), file_path],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=(sys.platform != "win32"),
        creationflags=creation_flags,
    )
except Exception:
    pass  # never block CC on any error
```

### QdrantStore Upsert to KNOWLEDGE Collection (from cc-memory-sync-worker.py adapted)
```python
# Source: .claude/hooks/cc-memory-sync-worker.py lines 148-181 (adapted for KNOWLEDGE)
config = QdrantConfig(url=qdrant_url, local_path=qdrant_local, vector_dim=384)
store = QdrantStore(config)
if not store.is_available:
    return  # Qdrant unreachable — exit silently

store._ensure_collection(QdrantStore.KNOWLEDGE)
collection_name = store._collection_name(QdrantStore.KNOWLEDGE)
point_id = str(uuid.uuid5(NAMESPACE, f"learning:{content_text}"))
payload = {
    "text": content_text,
    "source": "knowledge_learn",
    "learning_type": "decision",
    "category": "feature",
    "title": "...",
    "confidence": 0.85,
    "recall_count": 0,
    "status": "active",
    "timestamp": time.time(),
}
point = PointStruct(id=point_id, vector=vector, payload=payload)
store._client.upsert(collection_name=collection_name, points=[point])
```

### strengthen_point for Cross-Session Confidence Boost (from qdrant_store.py)
```python
# Source: memory/qdrant_store.py lines 470-509
# strengthen_point retrieves current payload, adds boost (capped at 1.0)
store.strengthen_point(QdrantStore.KNOWLEDGE, point_id, boost=0.1)
```

### Noise Guard Pattern (from effectiveness-learn.py)
```python
# Source: .claude/hooks/effectiveness-learn.py lines 231-239
tool_call_count = count_tool_calls(event)
file_mod_count = count_file_modifications(event)
if tool_call_count < 2 or file_mod_count < 1:
    print(f"[knowledge-learn] Skipped: {tool_call_count} tool calls, {file_mod_count} file mods", file=sys.stderr)
    sys.exit(0)
```

### Agent42 API POST from Hook (from effectiveness-learn.py)
```python
# Source: .claude/hooks/effectiveness-learn.py lines 188-221
import urllib.request
dashboard_url = os.environ.get("AGENT42_DASHBOARD_URL", "http://127.0.0.1:8000")
data = json.dumps(payload).encode("utf-8")
req = urllib.request.Request(
    f"{dashboard_url}/api/knowledge/learn",
    data=data, headers={"Content-Type": "application/json"}, method="POST",
)
with urllib.request.urlopen(req, timeout=30) as resp:
    result = json.loads(resp.read())
```

### Last 20 Messages Extraction (from effectiveness-learn.py)
```python
# Source: .claude/hooks/effectiveness-learn.py lines 84-94
def get_last_messages(event, n=20):
    messages = event.get("messages", [])
    if not isinstance(messages, list):
        return []
    return messages[-n:]  # last N messages for context
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Direct API keys in hooks (OPENROUTER_API_KEY) | Route through Agent42 API (localhost:8000) | This phase decision | Hooks stay provider-agnostic; keys managed in server only |
| Heuristic pattern extraction (learning-engine.py) | LLM-based structured extraction | Phase 2 | Richer, typed learnings; captures intent not just file patterns |
| Single flat confidence | Lifecycle scoring (confidence × recall × decay) | Phase 3D (qdrant_store.py) | Already implemented; knowledge entries get full lifecycle treatment |

**Deprecated/outdated:**
- `effectiveness-learn.py`'s direct `OPENROUTER_API_KEY` usage: This phase supersedes that pattern by routing through Agent42 API instead. The effectiveness-learn hook still works but represents the "old" approach for context.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x + pytest-asyncio |
| Config file | `pyproject.toml` (`asyncio_mode = "auto"`) |
| Quick run command | `python -m pytest tests/test_knowledge_learn.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| LEARN-01 | Decision extracted from messages → stored as `learning_type="decision"` in KNOWLEDGE | unit | `pytest tests/test_knowledge_learn.py::TestExtraction::test_decision_extracted -x` | ❌ Wave 0 |
| LEARN-02 | Correction in messages → stored as `learning_type="feedback"` | unit | `pytest tests/test_knowledge_learn.py::TestExtraction::test_feedback_extracted -x` | ❌ Wave 0 |
| LEARN-03 | Deploy/debug tools used → stored with `category="deploy"` | unit | `pytest tests/test_knowledge_learn.py::TestExtraction::test_deploy_pattern_extracted -x` | ❌ Wave 0 |
| LEARN-04 | Similar existing entry → strengthen_point called, no duplicate stored | unit | `pytest tests/test_knowledge_learn.py::TestDedup::test_similar_entry_boosted -x` | ❌ Wave 0 |
| LEARN-04 | Dissimilar entry → new point stored | unit | `pytest tests/test_knowledge_learn.py::TestDedup::test_new_entry_stored -x` | ❌ Wave 0 |
| LEARN-05 | Category field matches work type: security→security, deploy→deploy | unit | `pytest tests/test_knowledge_learn.py::TestCategories::test_category_tagging -x` | ❌ Wave 0 |
| All | Hook exits silently if Agent42 API unreachable | unit | `pytest tests/test_knowledge_learn.py::TestFailureSilence::test_api_unreachable_no_crash -x` | ❌ Wave 0 |
| All | Hook skips trivial sessions | unit | `pytest tests/test_knowledge_learn.py::TestNoiseFilter -x` | ❌ Wave 0 |
| All | settings.json registers knowledge-learn.py as Stop hook | integration | `pytest tests/test_knowledge_learn.py::TestHookRegistration -x` | ❌ Wave 0 |
| All | KNOWLEDGE collection uses 384-dim vectors | unit | `pytest tests/test_knowledge_learn.py::TestQdrantDimension -x` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_knowledge_learn.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_knowledge_learn.py` — all LEARN-01 through LEARN-05 coverage (new file)
- [ ] No framework install needed — pytest-asyncio already configured

---

## Open Questions

1. **Passing event data from hook entry to worker**
   - What we know: cc-memory-sync passes a file path as `sys.argv[1]`; that file already exists. Knowledge-learn hook receives a large JSON event on stdin.
   - What's unclear: Best approach — temp file vs pre-extract in hook vs pass via env var.
   - Recommendation: Pre-extract (summary + last 20 messages + tool/file lists) in hook entry point, serialize to `.agent42/knowledge-extract-{pid}.json`, pass path to worker. Worker reads and deletes the temp file. This keeps the worker contract clean and avoids command-line size limits on Windows.

2. **instructor async vs sync in FastAPI endpoint**
   - What we know: `instructor.from_openai(OpenAI())` is synchronous; FastAPI endpoints are async. `/api/effectiveness/learn` appears to call sync extraction inline (in existing code it doesn't use instructor — it calls the hook which does).
   - What's unclear: Whether blocking the event loop for ~1-2s of LLM call is acceptable for a background-only endpoint.
   - Recommendation: Use `asyncio.to_thread(sync_extract_fn, ...)` to run synchronous instructor call in thread pool. This is the correct async-safe pattern for sync I/O in FastAPI.

3. **New `/api/knowledge/learn` endpoint — authentication**
   - What we know: `/api/effectiveness/learn` and `/api/memory/search` have no auth (local hook access only). All knowledge endpoints in `/api/effectiveness/` follow this pattern.
   - What's unclear: Whether to add auth or trust localhost-only calling convention.
   - Recommendation: No auth required, matching existing hook API pattern. Document "local hook only" in docstring.

---

## Sources

### Primary (HIGH confidence)
- `C:/Users/rickw/projects/agent42/.claude/hooks/effectiveness-learn.py` — Hook entry point template with noise guard, session extraction, Agent42 API POST
- `C:/Users/rickw/projects/agent42/.claude/hooks/cc-memory-sync.py` — Detached subprocess spawn pattern
- `C:/Users/rickw/projects/agent42/.claude/hooks/cc-memory-sync-worker.py` — ONNX embedding + Qdrant upsert with 384-dim, status file pattern
- `C:/Users/rickw/projects/agent42/memory/qdrant_store.py` — QdrantStore.KNOWLEDGE constant, `strengthen_point()`, `search_with_lifecycle()` with `raw_score` field, `_ensure_collection()` with conditional indexes
- `C:/Users/rickw/projects/agent42/dashboard/server.py:2722` — `/api/effectiveness/learn` endpoint structure (model for new endpoint)
- `C:/Users/rickw/projects/agent42/.claude/settings.json` — Hook registration format, Stop event array
- `C:/Users/rickw/projects/agent42/tests/test_cc_memory_sync.py` — Test class structure and mock patterns for hook + worker tests

### Secondary (MEDIUM confidence)
- `C:/Users/rickw/projects/agent42/tests/test_learning_extraction.py` — Additional test patterns for hook module import + instructor extraction tests

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libraries already installed and in active use
- Architecture: HIGH — patterns directly instantiated from Phase 1 code
- Pitfalls: HIGH — sourced from reading actual implementation code, not speculation
- Test mapping: HIGH — mirrors exact test class structure from test_cc_memory_sync.py and test_learning_extraction.py

**Research date:** 2026-03-19
**Valid until:** 2026-04-18 (30 days — stable internal codebase)

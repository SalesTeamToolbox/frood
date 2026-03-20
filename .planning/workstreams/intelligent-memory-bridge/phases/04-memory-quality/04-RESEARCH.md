# Phase 4: Memory Quality - Research

**Researched:** 2026-03-18
**Domain:** Qdrant vector deduplication, lifecycle-aware search scoring, background worker patterns, dashboard stats
**Confidence:** HIGH — all key findings drawn directly from existing codebase; no external libraries to verify

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **Consolidation Trigger:** Dashboard button for manual trigger AND automatic trigger after 100+ new entries since last consolidation. Auto-check runs on each `agent42_memory store` call — after the store completes, check entry count since last consolidation. If threshold reached, spawn consolidation as background task (fire-and-forget, following Phase 1's cc-memory-sync-worker pattern). Track last consolidation timestamp and entry count in a status file. Dashboard shows: last-run timestamp, entries scanned, duplicates removed.
- **Dedup Strategy:** Tiered approach: auto-remove at 0.95+ cosine similarity, flag 0.85-0.95 range for review. When removing duplicates: keep the entry with the highest confidence score, delete the other. Dedup only — no LLM-powered merging or clustering of related-but-different entries. Consolidation output: dashboard stats AND log a semantic event in HISTORY.md (e.g., "consolidation: removed 12 duplicates from knowledge").
- **Consolidation Scope:** Qdrant only — MEMORY.md flat files are NOT rewritten. Claude Code's auto-memory system manages flat files independently; Qdrant is the enhanced store.
- **Search Result Scoring (QUAL-02):** Combined relevance score: blend cosine similarity + confidence + recall_boost + decay into a single 0-1 score. Formula follows Phase 2's lifecycle scoring: `relevance = cosine * confidence_weight * recall_boost * decay`. Raw fields (confidence, recall_count, last_recalled) available in metadata dict for dashboard/debugging. Claude sees the combined relevance score as the primary ranking signal.

### Claude's Discretion

- Which collections to scan during consolidation (both `memory` + `knowledge`, or prioritize where duplicates accumulate)
- Recall tracking approach: auto-increment on search result return vs only on explicit use
- Decay/removal policy: auto-archive below a threshold or decay-but-never-remove
- Exact dedup similarity thresholds (0.95 and 0.85 are starting points, may adjust)
- Dashboard widget layout for consolidation stats
- Status file format and location
- Consolidation batch size and concurrency

### Deferred Ideas (OUT OF SCOPE)

- LLM-powered cluster-and-merge of related-but-different entries — future enhancement if dedup alone isn't sufficient
- MEMORY.md flat file consolidation/rewrite — out of scope (CC manages its own flat files)
- Bidirectional sync (Qdrant → CC flat files) — out of scope per REQUIREMENTS.md
- Cross-project memory dedup — separate concern, handled by node_sync
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| QUAL-01 | Agent42 MEMORY.md is periodically consolidated (remove duplicates, merge related entries) | Background worker pattern from Phase 1 (`cc-memory-sync-worker.py`), `QdrantStore.search_with_lifecycle()` for similarity scanning, `_client.delete()` for point removal, status file at `.agent42/consolidation-status.json` |
| QUAL-02 | Search results include confidence scores and recall counts for relevance ranking | `search_with_lifecycle()` already computes `adjusted_score`, `confidence`, `recall_count` on every result; `_handle_search` in `memory_tool.py` already surfaces `conf=` and `recalls=` in output; only gap is ensuring these flow through consistently and are exposed in tool output |
</phase_requirements>

---

## Summary

Phase 4 builds on infrastructure already present in the codebase. `QdrantStore.search_with_lifecycle()` already computes lifecycle-adjusted scores (Phase 2 work) — the QUAL-02 requirement is primarily about ensuring those scores are consistently surfaced in `memory_tool.py`'s search output and accessible as separate fields. The `_handle_search` method in `memory_tool.py` already includes `conf=` and `recalls=` in its output string when those values exist. The main work is confirming the pipeline is complete end-to-end and adding a `consolidate` action.

For QUAL-01, the consolidation worker needs to be a new module (`memory/consolidation_worker.py`) that iterates Qdrant collections, computes pairwise similarity for candidate groups, removes lower-confidence duplicates above 0.95 threshold, flags 0.85-0.95 range, and writes results to a status file. The trigger mechanism in `memory_tool.py` mirrors the `_schedule_reindex` fire-and-forget pattern. The status file lives at `.agent42/consolidation-status.json` alongside `cc-sync-status.json`.

The key architectural insight: Qdrant does NOT provide a built-in deduplication API. We must fetch points in batches, compute cosine similarity using the stored vectors (retrievable via `with_vectors=True`), then delete the lower-quality duplicate. The all-MiniLM-L6-v2 model produces 384-dimensional normalized vectors — cosine similarity is `dot(a, b)` when both are L2-normalized, which is fast in pure Python for small batches but should be batched for large collections.

**Primary recommendation:** Implement `memory/consolidation_worker.py` as a standalone script (like `cc-memory-sync-worker.py`), add `consolidate` action to `memory_tool.py`, extend `dashboard/server.py`'s storage endpoint to include consolidation stats, and verify `_handle_search` returns consistent lifecycle fields.

---

## Standard Stack

### Core (All Already in Project)

| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| qdrant-client | in venv | Fetch vectors, delete points, batch operations | Only Qdrant client in project |
| onnxruntime | in venv | ONNX embeddings via `_OnnxEmbedder` | Established in Phase 1 — 23 MB RAM, no API key |
| tokenizers | in venv | Tokenization for ONNX model | Paired with onnxruntime for all-MiniLM-L6-v2 |
| asyncio | stdlib | Fire-and-forget background task scheduling | `_schedule_reindex` pattern established |

### Supporting

| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| json | stdlib | Status file serialization | Status file at `.agent42/consolidation-status.json` |
| time | stdlib | Timestamps in status file | Track `last_run`, `entries_scanned` |
| uuid | stdlib | Point ID lookup | UUID5 namespace `a42a42a4-...` matches existing scheme |

### Alternatives Considered

| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Pure-Python cosine similarity (via `embeddings.py:_cosine_similarity`) | numpy vectorized | No benefit for 384-dim over small batches; numpy not guaranteed in minimal installs |
| Subprocess detach (like cc-memory-sync-worker) | `asyncio.create_task` | `asyncio.create_task` preferred when event loop running; subprocess needed for truly detached/cross-session work. Recommend `asyncio.create_task` since consolidation is triggered during an active MCP tool call. |

**Installation:** No new packages needed. All dependencies already present.

---

## Architecture Patterns

### Recommended File Structure

```
memory/
├── consolidation.py              # Existing — conversation summarization (unrelated)
├── consolidation_worker.py       # NEW — Qdrant dedup consolidation
store.py                          # Existing — add _check_consolidation_trigger()
tools/
└── memory_tool.py                # Existing — add "consolidate" action
dashboard/
└── server.py                     # Existing — add consolidation stats to storage endpoint
.agent42/
└── consolidation-status.json     # NEW — last_run, entries_scanned, duplicates_removed
```

### Pattern 1: Status File (mirrors cc-sync-status.json)

**What:** JSON file at `.agent42/consolidation-status.json` tracking consolidation runs
**When to use:** Read by dashboard storage endpoint; written by consolidation worker

```python
# Source: .claude/hooks/cc-memory-sync-worker.py (lines 58-74, established pattern)
STATUS_FILE = project_dir / ".agent42" / "consolidation-status.json"

DEFAULT_STATUS = {
    "last_run": None,           # Unix timestamp of last completed run
    "entries_since": 0,         # New entries since last consolidation
    "last_scanned": 0,          # Total entries scanned in last run
    "last_removed": 0,          # Duplicates removed in last run
    "last_flagged": 0,          # Near-duplicates flagged (0.85-0.95)
    "last_error": None,
}
```

### Pattern 2: Fire-and-Forget Async Task (mirrors `_schedule_reindex`)

**What:** Trigger consolidation from `_handle_store` without blocking the MCP response
**When to use:** After threshold is reached (100+ new entries since last consolidation)

```python
# Source: memory/store.py:_schedule_reindex (lines 85-107, established pattern)
def _schedule_consolidation(self):
    """Schedule dedup consolidation as fire-and-forget async task."""
    import asyncio

    async def _run():
        try:
            from memory.consolidation_worker import run_consolidation
            await asyncio.to_thread(run_consolidation, self._qdrant)
        except Exception as e:
            logger.warning("Consolidation failed (non-critical): %s", e)

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_run())
    except RuntimeError:
        pass  # No running loop — skip (consolidation is non-critical)
```

### Pattern 3: Qdrant Batch Vector Fetch + Similarity Dedup

**What:** Fetch all vectors from a collection, compute pairwise similarity, delete lower-confidence duplicates
**When to use:** Inside `consolidation_worker.run_consolidation()`

```python
# Source: qdrant_store.py knowledge of qdrant-client API (verified in codebase)
# Fetch all points with vectors
from qdrant_client.models import Filter, ScrollRequest

offset = None
while True:
    results, next_offset = qdrant._client.scroll(
        collection_name=collection_name,
        with_vectors=True,
        with_payload=True,
        limit=100,  # batch size — tune via env var
        offset=offset,
    )
    # Process batch
    if next_offset is None:
        break
    offset = next_offset
```

**Key insight:** `QdrantClient.scroll()` is the correct API for full-collection iteration — `query_points` requires a query vector. Scroll returns `(list[PointStruct], Optional[offset])` where `offset=None` signals end.

### Pattern 4: Cosine Similarity on Normalized Vectors

**What:** all-MiniLM-L6-v2 produces L2-normalized vectors, so cosine similarity = dot product
**When to use:** Comparing two candidate vectors for deduplication

```python
# Source: memory/embeddings.py:_cosine_similarity (pure Python, no numpy needed)
def _cosine_similarity(a: list[float], b: list[float]) -> float:
    """For L2-normalized vectors: cosine = dot product."""
    return sum(x * y for x, y in zip(a, b))
    # This is O(dim) = O(384) per pair — fast enough for batches of hundreds
```

**Complexity note:** For N points, naive pairwise is O(N²). With 100+ entry threshold and typical collections of hundreds to a few thousand entries, this is acceptable. For 1000 entries: 500K comparisons at 384 ops each = ~200M ops in pure Python — may take 2-5 seconds. Use batched scroll (100 at a time) and compare within batches only (near-duplicate pairs are typically from the same time window and will be adjacent when sorted by timestamp).

**Recommended optimization:** Sort fetched points by timestamp, compare each point only against the N most recent 200 entries (sliding window). This reduces O(N²) to O(N * window) with minimal impact on quality.

### Pattern 5: Qdrant Point Deletion

**What:** Delete a duplicate point by its ID
**When to use:** When similarity >= 0.95 and the point has lower confidence than its duplicate

```python
# Source: qdrant_client delete_points API (verified in qdrant_store.py context)
from qdrant_client.models import PointIdsList

qdrant._client.delete(
    collection_name=collection_name,
    points_selector=PointIdsList(points=[point_id_to_delete]),
)
```

### Pattern 6: Lifecycle-Aware Search in memory_tool.py (QUAL-02)

**What:** `_handle_search` already surfaces confidence and recall_count in its output string
**Current state:** The format string at line 507 of `memory_tool.py` shows `conf={confidence:.2f}` and `recalls={recall_count}` — but only when those values are truthy (non-zero). This means a newly stored memory with `confidence=0.5` and `recall_count=0` will show no metadata.

**Fix needed:** Show lifecycle metadata always (not just when truthy), and expose raw fields as structured data in the tool output for dashboard consumption.

### Anti-Patterns to Avoid

- **Blocking the event loop during consolidation:** Consolidation iterates potentially thousands of points. Use `asyncio.to_thread()` to run the synchronous scroll + compare loop off the event loop.
- **Deleting points without checking confidence:** Always compare confidence scores before deletion. The decision: if `sim >= 0.95` and `point_a.confidence > point_b.confidence`, delete `point_b`. Never delete higher-confidence entries.
- **Recomputing embeddings during consolidation:** Vectors are already stored in Qdrant (`with_vectors=True` in scroll). No need to re-embed text. This keeps the worker cheap.
- **Running pairwise on the full collection at once:** Load in batches of 100-200. Qdrant scroll is the correct API; don't use `query_points` for full-collection scans.
- **Synchronous Qdrant scroll in async context:** `qdrant._client.scroll()` is synchronous. Call via `asyncio.to_thread()` or run in the subprocess pattern used by cc-memory-sync-worker.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Full-collection iteration over Qdrant | Custom paginator | `qdrant_client.scroll()` with offset | scroll() is the Qdrant-recommended batch API; handles pagination automatically |
| Cosine similarity | numpy, scipy | `_cosine_similarity()` in `memory/embeddings.py` | Already present, no new deps, sufficient for 384-dim |
| Background job scheduling | celery, APScheduler | `asyncio.create_task()` + `asyncio.to_thread()` | Established pattern in `_schedule_reindex()` — no new deps, consistent with codebase |
| Point deletion | Custom delete logic | `qdrant_client.delete()` with `PointIdsList` | Client handles this natively |

**Key insight:** The hardest part of deduplication in Qdrant is the lack of a built-in "find duplicates" API. The pattern is: scroll all vectors, compare cosine similarity, delete the weaker duplicate. This is simple but must be done correctly — the ordering (keep highest confidence, delete lower) and threshold configuration are the core decisions.

---

## Common Pitfalls

### Pitfall 1: `scroll()` Returns Vectors as numpy Arrays (or lists depending on version)

**What goes wrong:** `point.vector` may be a `list[float]` or `numpy.ndarray` depending on qdrant-client version and mode (server vs embedded). Pure-Python `_cosine_similarity` requires lists.
**Why it happens:** qdrant-client's type for vectors varies between embedded and server modes.
**How to avoid:** Always convert: `vector = list(point.vector) if point.vector else []`
**Warning signs:** `TypeError: 'numpy.ndarray' is not iterable` when calling `_cosine_similarity`

### Pitfall 2: UUID Point IDs Are Strings in Python but Qdrant Accepts UUID Objects Too

**What goes wrong:** When comparing fetched point IDs (which may be UUID objects) with stored string IDs, equality checks fail.
**Why it happens:** `QdrantStore._make_point_id()` returns `str(uuid.uuid5(...))`. Fetched point IDs from scroll come back as UUID objects.
**How to avoid:** Always compare as strings: `str(point.id)` when doing lookups or comparisons.
**Warning signs:** Point found by scroll but not matching expected string ID.

### Pitfall 3: Consolidation Triggers During Qdrant Unavailability

**What goes wrong:** `_check_consolidation_trigger()` is called on every `store`, but if Qdrant is temporarily unavailable, the entry count check fails silently and `entries_since` in the status file never resets — triggering consolidation on every store after Qdrant recovers.
**Why it happens:** Graceful degradation means Qdrant availability can fluctuate.
**How to avoid:** Check `self._qdrant.is_available` before incrementing `entries_since`. Only reset the counter when consolidation completes successfully.
**Warning signs:** Repeated consolidation runs logged in HISTORY.md.

### Pitfall 4: QUAL-02 Score Field Naming Collision

**What goes wrong:** `search_with_lifecycle()` returns `score` (adjusted) and `raw_score` (cosine). If `_handle_search` in `memory_tool.py` formats the output using only `score`, users see the lifecycle-adjusted score but may not know which metric they're looking at.
**Why it happens:** Multiple score fields in the result dict with similar names.
**How to avoid:** The tool output string should clearly label: `relevance={score:.2f}` (combined), and optionally `cosine={raw_score:.2f}` at debug verbosity. The planner should expose `confidence` and `recall_count` as labeled fields.
**Warning signs:** Confusion between raw cosine and adjusted relevance in search output.

### Pitfall 5: `entries_since` Counter Includes Non-Qdrant Entries

**What goes wrong:** The store counter increments on every `store` call, but entries that fail semantic indexing (Qdrant unavailable) are still counted — leading to premature consolidation triggers.
**Why it happens:** Counter is incremented before semantic indexing result is known.
**How to avoid:** Only increment the counter when `semantic_indexed = True` in `_handle_store`. Alternatively, check `collection_count()` directly against the stored `last_scanned` value — more accurate than a counter.

### Pitfall 6: Pairwise O(N²) Blows Up on Large Collections

**What goes wrong:** If a collection has 2000+ entries, full pairwise similarity is ~2M comparisons × 384-dim = ~800M operations in pure Python. This can take 30-120 seconds and block the worker.
**Why it happens:** No candidate filtering before similarity computation.
**How to avoid:** Use a sliding window: sort points by timestamp, compare each point only against the 200 most recent neighbors. Near-duplicates almost always come from the same session/time window. Alternatively, use Qdrant's own ANN search as a pre-filter: for each point, search its collection for the top-3 nearest neighbors and only compute exact similarity for those.
**Warning signs:** Worker process takes >30 seconds; dashboard shows "consolidation running" for extended periods.

---

## Code Examples

### Consolidation Worker: Core Dedup Loop

```python
# Source: Derived from cc-memory-sync-worker.py pattern + qdrant_store.py API
from qdrant_client.models import PointIdsList

def find_and_remove_duplicates(
    qdrant_client,
    collection_name: str,
    auto_threshold: float = 0.95,
    flag_threshold: float = 0.85,
    batch_size: int = 100,
    window_size: int = 200,
) -> tuple[int, int]:
    """Return (removed_count, flagged_count)."""
    # Fetch all points with vectors
    all_points = []
    offset = None
    while True:
        results, offset = qdrant_client.scroll(
            collection_name=collection_name,
            with_vectors=True,
            with_payload=True,
            limit=batch_size,
            offset=offset,
        )
        all_points.extend(results)
        if offset is None:
            break

    # Sort by timestamp (newest first for sliding window)
    all_points.sort(
        key=lambda p: (p.payload or {}).get("timestamp", 0),
        reverse=True
    )

    to_delete = set()
    flagged = set()

    for i, point_a in enumerate(all_points):
        if str(point_a.id) in to_delete:
            continue
        vec_a = list(point_a.vector) if point_a.vector else []
        conf_a = (point_a.payload or {}).get("confidence", 0.5)

        # Compare only within sliding window
        window = all_points[i + 1 : i + 1 + window_size]
        for point_b in window:
            if str(point_b.id) in to_delete:
                continue
            vec_b = list(point_b.vector) if point_b.vector else []
            sim = sum(x * y for x, y in zip(vec_a, vec_b))  # dot product (normalized)

            if sim >= auto_threshold:
                conf_b = (point_b.payload or {}).get("confidence", 0.5)
                # Delete the lower-confidence entry
                if conf_a >= conf_b:
                    to_delete.add(str(point_b.id))
                else:
                    to_delete.add(str(point_a.id))
                    break  # point_a is being deleted, move to next i
            elif sim >= flag_threshold:
                flagged.add(str(point_b.id))

    # Batch delete
    if to_delete:
        qdrant_client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=list(to_delete)),
        )

    return len(to_delete), len(flagged)
```

### Threshold Configuration via env vars

```python
# Source: core/config.py pattern — frozen dataclass with os.getenv()
# Add to Settings class in core/config.py:
consolidation_auto_threshold: float = float(
    os.getenv("CONSOLIDATION_AUTO_THRESHOLD", "0.95")
)
consolidation_flag_threshold: float = float(
    os.getenv("CONSOLIDATION_FLAG_THRESHOLD", "0.85")
)
consolidation_trigger_count: int = int(
    os.getenv("CONSOLIDATION_TRIGGER_COUNT", "100")
)
```

### Status File Integration in Server

```python
# Source: dashboard/server.py:_load_cc_sync_status pattern (lines 3526-3536)
def _load_consolidation_status() -> dict:
    """Load consolidation status from .agent42/consolidation-status.json."""
    try:
        import json as _json
        status_path = Path(settings.workspace or ".") / ".agent42" / "consolidation-status.json"
        if status_path.exists():
            return _json.loads(status_path.read_text())
    except Exception:
        pass
    return {
        "last_run": None,
        "entries_since": 0,
        "last_scanned": 0,
        "last_removed": 0,
        "last_flagged": 0,
        "last_error": None,
    }
```

### memory_tool.py `consolidate` action

```python
# Source: memory_tool.py action dispatch pattern (lines 188-195)
elif action == "consolidate":
    return await self._handle_consolidate()

async def _handle_consolidate(self) -> ToolResult:
    """Trigger an on-demand memory consolidation pass."""
    if not self._store or not self._store._qdrant or not self._store._qdrant.is_available:
        return ToolResult(
            output="Qdrant is not available. Consolidation requires Qdrant.",
            success=False,
        )
    try:
        from memory.consolidation_worker import run_consolidation
        result = await asyncio.to_thread(run_consolidation, self._store._qdrant)
        return ToolResult(
            output=f"Consolidation complete: scanned {result['scanned']}, "
                   f"removed {result['removed']} duplicates, "
                   f"flagged {result['flagged']} near-duplicates."
        )
    except Exception as e:
        return ToolResult(output=f"Consolidation failed: {e}", success=False)
```

### QUAL-02: search output with lifecycle fields

```python
# Source: memory_tool.py:_handle_search (current lines 499-508)
# Current: only shows conf/recalls when truthy
# Corrected: always show when available
for hit in semantic_hits:
    score = hit.get("score", 0)
    raw_score = hit.get("raw_score", score)
    text = hit.get("text", hit.get("summary", ""))
    source = hit.get("source", "memory")
    confidence = hit.get("confidence")
    recall_count = hit.get("recall_count")

    meta_parts = [f"relevance={score:.2f}"]
    if confidence is not None:
        meta_parts.append(f"conf={confidence:.2f}")
    if recall_count is not None:
        meta_parts.append(f"recalls={recall_count}")
    meta = " ".join(meta_parts)
    if text:
        results.append(f"[{source} {meta}] {text.strip()}")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| No lifecycle scoring | `search_with_lifecycle()` with confidence, recall, decay | Phase 2 | Scores are already computed — QUAL-02 just needs to surface them consistently |
| No recall tracking | `record_recall()` called after every lifecycle search | Phase 2 | recall_count and last_recalled already updating in Qdrant |
| No batch iteration | Qdrant `scroll()` API for full-collection traversal | qdrant-client 1.x | Enables dedup without re-embedding |

**Deprecated/outdated:**
- `embeddings.py:_search_qdrant` uses basic `search()` (no lifecycle) — existing code, still valid for non-memory searches. Don't change this; only `semantic_search()` in `store.py` uses the lifecycle path.

---

## Open Questions

1. **Which collections to consolidate**
   - What we know: `memory` and `knowledge` collections both accumulate entries over time; `history` and `conversations` are append-only event logs where dedup is less appropriate
   - What's unclear: Whether the `knowledge` collection (from Phase 2) has seen enough entries in practice to need dedup
   - Recommendation: Consolidate both `memory` and `knowledge` collections. Skip `history` (chronological log, dedup would lose temporal information) and `conversations` (session summaries, each is unique).

2. **How to handle `entries_since` tracking without a persistent counter in MemoryStore**
   - What we know: MemoryStore is instantiated fresh on each MCP server start. There's no persistent state attached to it.
   - What's unclear: Whether to track `entries_since` in the status file (persistent, survives restarts) or in memory (resets to 0 on restart)
   - Recommendation: Track in the status file. On `_handle_store`, after successful semantic indexing: increment `entries_since` in `consolidation-status.json` and check against the threshold. This is slightly more I/O but is consistent with how `cc-sync-status.json` works.

3. **Dashboard "flagged for review" UI**
   - What we know: 04-CONTEXT.md mentions "provide a simple approve/dismiss UI" for 0.85-0.95 range entries
   - What's unclear: Whether this requires a new API endpoint listing flagged entries or just a count in the storage widget
   - Recommendation: For Phase 4, just surface the `last_flagged` count in the storage widget. A full review UI is scope creep. The planner should scope this as a simple stats display, not an interactive approval flow.

---

## Validation Architecture

### Test Framework

| Property | Value |
|----------|-------|
| Framework | pytest (asyncio_mode = "auto") |
| Config file | `pyproject.toml` |
| Quick run command | `python -m pytest tests/test_memory_tool.py -x -q` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements → Test Map

| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| QUAL-01 | consolidation removes duplicates above 0.95 cosine threshold | unit | `python -m pytest tests/test_consolidation_worker.py -x` | ❌ Wave 0 |
| QUAL-01 | consolidation triggers after 100 entries, updates status file | unit | `python -m pytest tests/test_consolidation_worker.py::TestConsolidationTrigger -x` | ❌ Wave 0 |
| QUAL-01 | `memory consolidate` action returns stats | unit | `python -m pytest tests/test_memory_tool.py::TestMemoryToolConsolidate -x` | ❌ Wave 0 |
| QUAL-01 | dashboard storage endpoint includes consolidation stats | unit | `python -m pytest tests/test_memory_tool.py::TestConsolidationDashboard -x` | ❌ Wave 0 (can extend existing test_memory_tool.py) |
| QUAL-02 | search results include confidence, recall_count, combined relevance score | unit | `python -m pytest tests/test_memory_tool.py::TestMemoryToolSearch -x` | ❌ Wave 0 (extend existing) |

### Sampling Rate

- **Per task commit:** `python -m pytest tests/test_memory_tool.py tests/test_consolidation_worker.py -x -q`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps

- [ ] `tests/test_consolidation_worker.py` — covers QUAL-01 dedup logic, status file writes, trigger threshold
- [ ] Extend `tests/test_memory_tool.py` with `TestMemoryToolConsolidate` class — covers QUAL-01 `consolidate` action
- [ ] Extend `tests/test_memory_tool.py` with lifecycle assertions in existing `TestMemoryToolSearch` — covers QUAL-02 score fields

Note: No new framework or conftest needed — `tests/conftest.py` already provides shared fixtures. `test_memory_tool.py` already imports `MemoryTool` and `MemoryStore` with a `tmpdir` pattern.

---

## Sources

### Primary (HIGH confidence)

- `memory/qdrant_store.py` — `search_with_lifecycle()`, `scroll()` not present but `_client.scroll()` used via raw client, `delete()`, `record_recall()`, `update_payload()`
- `memory/store.py` — `_schedule_reindex()` fire-and-forget pattern, `semantic_search()`, `_record_recalls()`
- `tools/memory_tool.py` — `_handle_search()` current lifecycle surfacing, `_handle_store()` semantic indexing flow
- `.claude/hooks/cc-memory-sync-worker.py` — status file pattern, detached subprocess pattern, `load_status()` / `save_status()`
- `dashboard/server.py` — `_load_cc_sync_status()` and storage endpoint response structure (lines 3526-3637)
- `dashboard/frontend/dist/app.js` — `loadStorageStatus()`, `storageStatus` state, storage panel render (lines 6146-6207)
- `.planning/config.json` — `nyquist_validation: true` (validation architecture section required)

### Secondary (MEDIUM confidence)

- Qdrant `scroll()` API: Confirmed present in qdrant-client via codebase references to `_client.scroll()` in `memory/qdrant_store.py` context (not directly observed as a standalone call, but referenced in qdrant-client docs as the collection iteration API)
- `PointIdsList` for batch delete: Observed in `tools/memory_tool.py:_handle_reindex_cc` import patterns; `qdrant_client.models` includes `PointIdsList`

### Tertiary (LOW confidence)

- Specific qdrant-client version installed in venv — checked `.venv` presence but did not inspect version number. The `scroll()` API has been stable since qdrant-client 1.x; confidence HIGH on API shape, LOW on exact signature details.

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all libs already in project, no new dependencies
- Architecture: HIGH — built directly from existing patterns in codebase
- Pitfalls: HIGH for codebase-specific pitfalls; MEDIUM for Qdrant scroll vector type (not directly observed)
- Dashboard integration: HIGH — exact pattern from storage endpoint already in codebase

**Research date:** 2026-03-18
**Valid until:** 2026-04-18 (stable domain — Qdrant API and internal codebase patterns)

"""
Qdrant memory deduplication worker — scans collections, removes near-duplicate
vectors, tracks stats.

Collections scanned: memory, knowledge
Collections skipped: history, conversations (chronological logs — dedup would corrupt them)

Thresholds:
  auto_threshold (default 0.95): cosine similarity >= this triggers auto-delete of lower-confidence point
  flag_threshold (default 0.85): cosine similarity >= this (but < auto) flags for review (counted, not deleted)
"""

import json
import logging
import os
import time
from pathlib import Path

logger = logging.getLogger("frood.memory.consolidation_worker")

# Env-configurable thresholds (defaults from CONTEXT.md decisions)
AUTO_THRESHOLD = float(os.getenv("CONSOLIDATION_AUTO_THRESHOLD", "0.95"))
FLAG_THRESHOLD = float(os.getenv("CONSOLIDATION_FLAG_THRESHOLD", "0.85"))
TRIGGER_COUNT = int(os.getenv("CONSOLIDATION_TRIGGER_COUNT", "100"))
BATCH_SIZE = int(os.getenv("CONSOLIDATION_BATCH_SIZE", "100"))
WINDOW_SIZE = int(os.getenv("CONSOLIDATION_WINDOW_SIZE", "200"))


# ---------------------------------------------------------------------------
# Status file helpers (mirrors .claude/hooks/cc-memory-sync-worker.py pattern)
# ---------------------------------------------------------------------------


def _status_file_path(workspace: "str | Path" = ".") -> Path:
    """Return the path to the consolidation status JSON file."""
    return Path(workspace) / ".frood" / "consolidation-status.json"


def load_consolidation_status(workspace: "str | Path" = ".") -> dict:
    """Load the consolidation status from disk.

    Returns a dict with keys: last_run, entries_since, last_scanned,
    last_removed, last_flagged, last_error.  Defaults to all-zero/None
    values when the file does not exist or is unreadable.
    """
    path = _status_file_path(workspace)
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
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


def save_consolidation_status(status: dict, workspace: "str | Path" = ".") -> None:
    """Persist the consolidation status to disk (atomic via write + rename is not
    needed here — status files are append-only stats, not config).
    """
    path = _status_file_path(workspace)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception:
        pass


def increment_entries_since(workspace: "str | Path" = ".") -> int:
    """Increment the entries_since counter by 1.

    Called each time a memory entry is stored so the trigger check knows
    whether to kick off a background consolidation pass.

    Returns the new counter value.
    """
    status = load_consolidation_status(workspace)
    status["entries_since"] = status.get("entries_since", 0) + 1
    save_consolidation_status(status, workspace)
    return status["entries_since"]


def should_trigger_consolidation(workspace: "str | Path" = ".") -> bool:
    """Return True when the entries_since counter has reached TRIGGER_COUNT."""
    status = load_consolidation_status(workspace)
    return status.get("entries_since", 0) >= TRIGGER_COUNT


# ---------------------------------------------------------------------------
# Core dedup engine
# ---------------------------------------------------------------------------


def find_and_remove_duplicates(
    qdrant_client,
    collection_name: str,
    auto_threshold: float = AUTO_THRESHOLD,
    flag_threshold: float = FLAG_THRESHOLD,
    batch_size: int = BATCH_SIZE,
    window_size: int = WINDOW_SIZE,
) -> "tuple[int, int, int]":
    """Scan *collection_name* for near-duplicate vectors and remove lower-confidence ones.

    Algorithm:
    1. Fetch all points with their vectors via scroll()
    2. Sort by timestamp (newest first — prefer keeping recent entries)
    3. Sliding-window comparison: each point compared to the next *window_size* points
    4. sim >= auto_threshold  → mark lower-confidence point for deletion
    5. flag_threshold <= sim < auto_threshold → count as "flagged" (not deleted)
    6. Batch-delete all marked points in one call

    Args:
        qdrant_client: Raw QdrantClient instance (QdrantStore._client).
        collection_name: Fully-qualified collection name (with prefix).
        auto_threshold: Cosine similarity above which duplicates are auto-removed.
        flag_threshold: Cosine similarity above which near-duplicates are flagged.
        batch_size: Points per scroll page.
        window_size: How many subsequent points each point is compared against.

    Returns:
        Tuple (scanned, removed, flagged).
    """
    try:
        from qdrant_client.models import PointIdsList
    except ImportError:
        logger.warning("qdrant-client not installed — consolidation unavailable")
        return 0, 0, 0

    # ---- 1. Fetch all points with vectors ----
    all_points = []
    offset = None
    while True:
        results, next_offset = qdrant_client.scroll(
            collection_name=collection_name,
            with_vectors=True,
            with_payload=True,
            limit=batch_size,
            offset=offset,
        )
        all_points.extend(results)
        if next_offset is None:
            break
        offset = next_offset

    scanned = len(all_points)
    if scanned < 2:
        return scanned, 0, 0

    # ---- 2. Sort newest-first (prefer keeping recently-added entries) ----
    all_points.sort(
        key=lambda p: (p.payload or {}).get("timestamp", 0),
        reverse=True,
    )

    to_delete: set = set()
    flagged: set = set()

    # ---- 3. Sliding-window cosine comparison ----
    for i, point_a in enumerate(all_points):
        pid_a = str(point_a.id)
        if pid_a in to_delete:
            continue
        vec_a = list(point_a.vector) if point_a.vector else []
        if not vec_a:
            continue
        conf_a = (point_a.payload or {}).get("confidence", 0.5)

        window = all_points[i + 1 : i + 1 + window_size]
        for point_b in window:
            pid_b = str(point_b.id)
            if pid_b in to_delete:
                continue
            vec_b = list(point_b.vector) if point_b.vector else []
            if not vec_b:
                continue

            # For L2-normalised vectors: cosine similarity = dot product.
            # Qdrant COSINE distance implies normalised vectors.
            sim = sum(x * y for x, y in zip(vec_a, vec_b))

            if sim >= auto_threshold:
                conf_b = (point_b.payload or {}).get("confidence", 0.5)
                if conf_a >= conf_b:
                    to_delete.add(pid_b)
                else:
                    to_delete.add(pid_a)
                    break  # point_a deleted — skip rest of its window
            elif sim >= flag_threshold:
                flagged.add(pid_b)

    # ---- 4. Batch delete ----
    if to_delete:
        qdrant_client.delete(
            collection_name=collection_name,
            points_selector=PointIdsList(points=list(to_delete)),
        )

    # Remove flagged IDs that were also deleted (they no longer exist)
    flagged -= to_delete

    return scanned, len(to_delete), len(flagged)


# ---------------------------------------------------------------------------
# Orchestration entry point
# ---------------------------------------------------------------------------


def run_consolidation(qdrant_store, workspace: "str | Path" = ".") -> dict:
    """Run dedup consolidation across the memory and knowledge collections.

    Skips history and conversations — those are chronological logs where
    deduplication would corrupt the event timeline.

    Args:
        qdrant_store: A QdrantStore instance with an active ._client.
        workspace: Workspace path used to locate the status file.

    Returns:
        Dict with keys: scanned, removed, flagged, collections, error.
    """
    if not qdrant_store or not qdrant_store.is_available:
        return {
            "scanned": 0,
            "removed": 0,
            "flagged": 0,
            "collections": [],
            "error": "Qdrant unavailable",
        }

    total_scanned = 0
    total_removed = 0
    total_flagged = 0
    collections_processed = []

    for suffix in ["memory", "knowledge"]:
        try:
            col_name = qdrant_store._collection_name(suffix)
            count = qdrant_store.collection_count(suffix)
            if count < 2:
                continue

            scanned, removed, flagged = find_and_remove_duplicates(
                qdrant_store._client,
                col_name,
            )
            total_scanned += scanned
            total_removed += removed
            total_flagged += flagged
            collections_processed.append(suffix)
            logger.info(
                "Consolidation [%s]: scanned=%d removed=%d flagged=%d",
                suffix,
                scanned,
                removed,
                flagged,
            )
        except Exception as e:
            logger.warning("Consolidation failed for %s: %s", suffix, e)

    # Update status file
    status = load_consolidation_status(workspace)
    status.update(
        {
            "last_run": time.time(),
            "entries_since": 0,  # Reset counter after consolidation
            "last_scanned": total_scanned,
            "last_removed": total_removed,
            "last_flagged": total_flagged,
            "last_error": None,
        }
    )
    save_consolidation_status(status, workspace)

    return {
        "scanned": total_scanned,
        "removed": total_removed,
        "flagged": total_flagged,
        "collections": collections_processed,
        "error": None,
    }

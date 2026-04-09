#!/usr/bin/env python3
"""Knowledge learning worker — calls /api/knowledge/learn, embeds, upserts to KNOWLEDGE collection.

Spawned as a detached background process by knowledge-learn.py (the hook entry
point). Reads the pre-extracted session data temp file, calls Frood's API
for LLM extraction of structured learnings, then embeds locally with ONNX and
upserts to Qdrant's KNOWLEDGE collection with dedup-by-similarity logic.

All failures are silent — only the status file records errors.
Never writes to stdout or stderr.

Usage:
    python knowledge-learn-worker.py <extract_file_path>
"""

import json
import os
import sys
import time
import uuid
from pathlib import Path

# ── Bootstrap: add project root to sys.path ─────────────────────────────────
script_dir = Path(__file__).resolve().parent  # .claude/hooks/
project_dir = script_dir.parent.parent  # project root (agent42/)
sys.path.insert(0, str(project_dir))

# ── Status file ──────────────────────────────────────────────────────────────
STATUS_FILE = project_dir / ".frood" / "knowledge-learn-status.json"

# ── Constants ────────────────────────────────────────────────────────────────
NAMESPACE = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
SIMILARITY_THRESHOLD = 0.85

# ── Deferred imports (after sys.path bootstrap) ──────────────────────────────
# Imported at module level so tests can patch them via patch.object()
try:
    from memory.embeddings import _find_onnx_model_dir, _OnnxEmbedder
    from memory.qdrant_store import QdrantConfig, QdrantStore
except ImportError:
    # If Frood isn't importable, we'll fail gracefully in process_learnings()
    _OnnxEmbedder = None  # type: ignore[assignment,misc]
    _find_onnx_model_dir = None  # type: ignore[assignment]
    QdrantConfig = None  # type: ignore[assignment,misc]
    QdrantStore = None  # type: ignore[assignment,misc]


# ── Status helpers ────────────────────────────────────────────────────────────


def load_status() -> dict:
    """Load the learn status file, returning defaults if missing or corrupt."""
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {
        "last_learn": None,
        "total_stored": 0,
        "total_boosted": 0,
        "last_error": None,
    }


def save_status(status: dict) -> None:
    """Write the learn status file, creating parent dirs if needed."""
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception:
        pass  # Never raise


# ── Core helpers ──────────────────────────────────────────────────────────────


def make_point_id(content: str) -> str:
    """Generate a deterministic UUID5 point ID from learning content."""
    return str(uuid.uuid5(NAMESPACE, f"knowledge:{content}"))


def call_extraction_api(extract_data: dict) -> list:
    """POST session data to Frood /api/knowledge/learn and return learnings list.

    Returns:
        List of learning dicts with keys: content, learning_type, category, title, confidence
        Empty list on any failure (connection error, timeout, bad response).
    """
    import urllib.request

    dashboard_url = os.environ.get("FROOD_DASHBOARD_URL", "http://127.0.0.1:8000")

    try:
        data = json.dumps(extract_data).encode("utf-8")
        req = urllib.request.Request(
            f"{dashboard_url}/api/knowledge/learn",
            data=data,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read())
        return result.get("learnings", [])
    except Exception:
        return []  # Silent failure — API unavailable, timeout, or bad response


def dedup_or_store(store, embedder, learning: dict, session_id: str) -> str:
    """Check for duplicates by raw_score similarity; boost existing or store new.

    Uses raw_score (not lifecycle-adjusted score) to avoid treating confidence-
    adjusted scores as similarity evidence.

    Args:
        store: QdrantStore instance
        embedder: ONNX embedder with .encode() method
        learning: Dict with content, learning_type, category, title, confidence
        session_id: Current session UUID (stored in new point payload)

    Returns:
        "boosted" if an existing similar point was strengthened
        "stored" if a new point was upserted
    """
    try:
        from qdrant_client.models import PointStruct
    except ImportError:
        return "stored"  # Can't upsert anyway — just report stored

    # Embed the learning content
    vector = embedder.encode(learning["content"][:2000])

    # Search for similar existing entries using raw_score for dedup
    hits = store.search_with_lifecycle(
        QdrantStore.KNOWLEDGE,
        vector,
        top_k=3,
        exclude_forgotten=True,
    )

    # Check if any hit is above the similarity threshold using raw_score
    for hit in hits:
        raw_score = hit.get("raw_score", 0.0)
        if raw_score >= SIMILARITY_THRESHOLD:
            # Existing similar entry found — boost its confidence instead of duplicating
            store.strengthen_point(
                QdrantStore.KNOWLEDGE,
                hit["point_id"],
                boost=0.1,
            )
            return "boosted"

    # No similar entry above threshold — store as new point
    point_id = make_point_id(learning["content"])
    payload = {
        "text": learning["content"],
        "source": "knowledge_learn",
        "learning_type": learning.get("learning_type", "pattern"),
        "category": learning.get("category", "general"),
        "title": learning.get("title", ""),
        "confidence": learning.get("confidence", 0.8),
        "recall_count": 0,
        "status": "active",
        "session_id": session_id,
        "timestamp": time.time(),
    }
    point = PointStruct(id=point_id, vector=vector, payload=payload)
    store._ensure_collection(QdrantStore.KNOWLEDGE)
    collection_name = store._collection_name(QdrantStore.KNOWLEDGE)
    store._client.upsert(collection_name=collection_name, points=[point])
    return "stored"


# ── Main worker function ──────────────────────────────────────────────────────


def process_learnings(extract_file: str) -> None:
    """Main worker function: read temp file, call API, embed, dedup-or-store.

    Args:
        extract_file: Path to the temp JSON file written by the hook entry point.
    """
    status = load_status()

    try:
        # Read and parse temp file
        temp_path = Path(extract_file)
        if not temp_path.exists():
            return

        extract_data = json.loads(temp_path.read_text(encoding="utf-8"))

        # Delete temp file after reading (cleanup)
        try:
            temp_path.unlink()
        except Exception:
            pass

        # Call Frood API for LLM extraction
        learnings = call_extraction_api(extract_data)

        if not learnings:
            status["last_learn"] = time.time()
            save_status(status)
            return

        # Check ONNX model availability
        if _find_onnx_model_dir is None:
            status["last_error"] = "Frood memory module not importable"
            save_status(status)
            return

        model_dir = _find_onnx_model_dir()
        if model_dir is None:
            status["last_error"] = "ONNX model not found"
            save_status(status)
            return

        # Initialize ONNX embedder
        try:
            embedder = _OnnxEmbedder(model_dir)
        except Exception as e:
            status["last_error"] = f"Embedder init error: {e}"
            save_status(status)
            return

        # Initialize Qdrant connection
        if QdrantStore is None or QdrantConfig is None:
            status["last_error"] = "QdrantStore not importable"
            save_status(status)
            return

        qdrant_url = os.getenv("QDRANT_URL", "")
        qdrant_local = os.getenv(
            "QDRANT_LOCAL_PATH",
            str(project_dir / ".frood" / "qdrant"),
        )
        config = QdrantConfig(url=qdrant_url, local_path=qdrant_local, vector_dim=384)
        store = QdrantStore(config)

        if not store.is_available:
            return  # Qdrant unreachable — exit silently

        # Generate a session ID to group learnings from this session
        session_id = str(uuid.uuid4())

        # Process each learning
        stored_count = 0
        boosted_count = 0

        for learning in learnings:
            try:
                result = dedup_or_store(store, embedder, learning, session_id)
                if result == "stored":
                    stored_count += 1
                elif result == "boosted":
                    boosted_count += 1
            except Exception:
                pass  # Individual learning failure is silent

        # Update status with counts
        status["last_learn"] = time.time()
        status["total_stored"] = (status.get("total_stored") or 0) + stored_count
        status["total_boosted"] = (status.get("total_boosted") or 0) + boosted_count
        status["last_error"] = None
        save_status(status)

    except Exception as e:
        status["last_error"] = str(e)
        save_status(status)


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        if len(sys.argv) < 2:
            sys.exit(0)
        process_learnings(sys.argv[1])
    except Exception:
        pass  # Top-level silence — never crash

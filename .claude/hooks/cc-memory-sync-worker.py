#!/usr/bin/env python3
"""CC memory sync worker — ONNX embedding + Qdrant upsert for CC memory files.

Spawned as a detached background process by cc-memory-sync.py (the hook entry
point). Reads the memory file, generates an ONNX embedding, and upserts it
to Qdrant with a deterministic file-path-based UUID5 point ID (SYNC-03).

All failures are silent — only the status file records errors (SYNC-04).
Never writes to stdout or stderr.

Usage:
    python cc-memory-sync-worker.py <file_path>
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
STATUS_FILE = project_dir / ".agent42" / "cc-sync-status.json"

# ── Deferred imports (after sys.path bootstrap) ──────────────────────────────
# Imported at module level so tests can patch them via patch.object()
try:
    from memory.embeddings import _find_onnx_model_dir, _OnnxEmbedder
    from memory.qdrant_store import QdrantConfig, QdrantStore
except ImportError:
    # If Agent42 isn't importable, we'll fail gracefully in sync_memory_file()
    _OnnxEmbedder = None  # type: ignore[assignment,misc]
    _find_onnx_model_dir = None  # type: ignore[assignment]
    QdrantConfig = None  # type: ignore[assignment,misc]
    QdrantStore = None  # type: ignore[assignment,misc]


# ── Core helpers ─────────────────────────────────────────────────────────────


def make_point_id(file_path: str) -> str:
    """Generate a deterministic UUID5 point ID from the file path.

    Uses the same namespace as QdrantStore._make_point_id() but keys only on
    the file path (not content), so re-syncing an edited file overwrites the
    same Qdrant point (SYNC-03).
    """
    namespace = uuid.UUID("a42a42a4-2a42-4a42-a42a-42a42a42a42a")
    content = f"claude_code:{file_path}"
    return str(uuid.uuid5(namespace, content))


def load_status() -> dict:
    """Load the sync status file, returning defaults if missing or corrupt."""
    try:
        if STATUS_FILE.exists():
            return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {"last_sync": None, "total_synced": 0, "last_error": None}


def save_status(status: dict) -> None:
    """Write the sync status file, creating parent dirs if needed."""
    try:
        STATUS_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATUS_FILE.write_text(json.dumps(status, indent=2), encoding="utf-8")
    except Exception:
        pass  # SYNC-04: never raise


def parse_frontmatter(content: str) -> dict:
    """Extract YAML frontmatter between --- delimiters.

    Parses simple key: value pairs only (no PyYAML dependency).
    Returns an empty dict if no frontmatter is present.
    """
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


# ── Main sync function ────────────────────────────────────────────────────────


def sync_memory_file(file_path: str) -> None:
    """Embed a CC memory file and upsert it to Qdrant.

    All errors are caught and written to the status file. Nothing is
    written to stdout or stderr (SYNC-04).
    """
    status = load_status()

    try:
        # --- Read file -------------------------------------------------------
        p = Path(file_path)
        if not p.exists():
            return  # File not found — exit silently
        content = p.read_text(encoding="utf-8", errors="replace").strip()
        if not content:
            return  # Empty file — nothing to embed

        # --- Parse frontmatter -----------------------------------------------
        frontmatter = parse_frontmatter(content)

        # --- Find ONNX model -------------------------------------------------
        if _find_onnx_model_dir is None:
            status["last_error"] = "Agent42 memory module not importable"
            save_status(status)
            return

        model_dir = _find_onnx_model_dir()
        if model_dir is None:
            status["last_error"] = "ONNX model not found"
            save_status(status)
            return

        # --- Generate embedding -----------------------------------------------
        try:
            embedder = _OnnxEmbedder(model_dir)
            vector = embedder.encode(content[:2000])
        except Exception as e:
            status["last_error"] = f"Embedding error: {e}"
            save_status(status)
            return

        # --- Connect to Qdrant -----------------------------------------------
        if QdrantStore is None or QdrantConfig is None:
            status["last_error"] = "QdrantStore not importable"
            save_status(status)
            return

        qdrant_url = os.getenv("QDRANT_URL", "")
        qdrant_local = os.getenv("QDRANT_LOCAL_PATH", str(project_dir / ".agent42" / "qdrant"))
        config = QdrantConfig(url=qdrant_url, local_path=qdrant_local, vector_dim=384)
        store = QdrantStore(config)

        if not store.is_available:
            return  # Qdrant unreachable — exit silently (SYNC-04)

        # --- Build payload ---------------------------------------------------
        payload = {
            "source": "claude_code",
            "file_path": file_path,
            "section": p.stem,
            **frontmatter,  # name, description, type from YAML if present
        }

        # --- Upsert with file-path-based point ID (SYNC-03) ------------------
        # We bypass upsert_single/upsert_vectors because their _make_point_id
        # includes content in the hash (content changes -> new point ID).
        # Using a file-path-only UUID ensures edits OVERWRITE the same point.
        try:
            from qdrant_client.models import PointStruct
        except ImportError:
            status["last_error"] = "qdrant-client models not importable"
            save_status(status)
            return

        point_id = make_point_id(file_path)
        full_payload = {"text": content, "timestamp": time.time(), **payload}
        point = PointStruct(id=point_id, vector=vector, payload=full_payload)

        store._ensure_collection(QdrantStore.MEMORY)
        collection_name = store._collection_name(QdrantStore.MEMORY)
        store._client.upsert(collection_name=collection_name, points=[point])

        # --- Update status ---------------------------------------------------
        status["last_sync"] = time.time()
        status["total_synced"] = (status.get("total_synced") or 0) + 1
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
        sync_memory_file(sys.argv[1])
    except Exception:
        pass  # SYNC-04: top-level silence

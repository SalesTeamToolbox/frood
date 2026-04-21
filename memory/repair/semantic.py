"""Semantic pair detection for Phase 2 repair checks.

Embeds every memory file body once, then does a brute-force pairwise cosine
comparison. Reuses the same ONNX embedder that cc-memory-sync-worker uses —
if that's unavailable, the helpers silently return no pairs so the Phase 2
checks degrade gracefully.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import aiofiles

logger = logging.getLogger("frood.memory.repair.semantic")


@dataclass
class SemanticPair:
    """One file-pair with its cosine similarity (>= flag_threshold)."""

    a: Path
    b: Path
    a_text: str
    b_text: str
    similarity: float


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b:
        return 0.0
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def _load_embedder():
    """Return an ONNX embedder instance, or None if unavailable."""
    try:
        from memory.embeddings import _find_onnx_model_dir, _OnnxEmbedder
    except Exception as exc:
        logger.debug("semantic: embeddings module unavailable (%s)", exc)
        return None
    try:
        model_dir = _find_onnx_model_dir()
    except Exception:
        model_dir = None
    if model_dir is None:
        logger.debug("semantic: ONNX model not found")
        return None
    try:
        return _OnnxEmbedder(model_dir)
    except Exception as exc:
        logger.debug("semantic: embedder init failed (%s)", exc)
        return None


async def find_similar_pairs(
    files: list[Path],
    min_similarity: float = 0.85,
) -> list[SemanticPair]:
    """Embed every file once, return every pair with cosine >= min_similarity.

    Returns an empty list if the ONNX embedder is unavailable or fewer than
    two files are provided — callers treat an empty result as "no findings".
    """
    if len(files) < 2:
        return []
    embedder = _load_embedder()
    if embedder is None:
        return []

    bodies: list[tuple[Path, str, list[float]]] = []
    for f in files:
        try:
            async with aiofiles.open(f, encoding="utf-8", errors="replace") as fh:
                text = await fh.read()
        except Exception:
            continue
        try:
            vec = embedder.encode(text[:2000])
        except Exception as exc:
            logger.debug("semantic: embed failed for %s (%s)", f.name, exc)
            continue
        bodies.append((f, text, list(vec)))

    pairs: list[SemanticPair] = []
    for i, (fa, ta, va) in enumerate(bodies):
        for fb, tb, vb in bodies[i + 1 :]:
            sim = _cosine(va, vb)
            if sim >= min_similarity:
                pairs.append(SemanticPair(a=fa, b=fb, a_text=ta, b_text=tb, similarity=sim))
    return pairs

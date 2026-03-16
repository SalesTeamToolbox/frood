#!/usr/bin/env python3
"""Persistent memory search service — keeps embedding model loaded.

Runs as a lightweight HTTP server alongside Qdrant. The memory-recall hook
calls this instead of loading sentence-transformers on every prompt.

Endpoints:
  POST /search  {"query": "text", "top_k": 5, "threshold": 0.25}
  GET  /health   → {"status": "ok", "model": "...", "qdrant": true/false}

Usage:
  python memory/search_service.py [--port 6380] [--qdrant-url http://localhost:6333]
"""

import argparse
import json
import logging
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

# Add project root to path
PROJECT_ROOT = str(Path(__file__).resolve().parent.parent)
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [search-service] %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("search-service")

# Globals set during startup
_model = None
_qdrant_client = None
_collections = []
_model_name = "all-MiniLM-L6-v2"


def _init_model():
    """Load the sentence-transformers model (one-time cost)."""
    global _model
    try:
        from sentence_transformers import SentenceTransformer

        logger.info(f"Loading embedding model: {_model_name}...")
        _model = SentenceTransformer(_model_name)
        logger.info(f"Model loaded ({_model.get_sentence_embedding_dimension()} dims)")
    except Exception as e:
        logger.error(f"Failed to load model: {e}")
        _model = None


def _init_qdrant(url):
    """Connect to Qdrant server."""
    global _qdrant_client, _collections
    try:
        from qdrant_client import QdrantClient

        _qdrant_client = QdrantClient(url=url, timeout=5)
        collections = _qdrant_client.get_collections().collections
        _collections = [c.name for c in collections]
        logger.info(f"Qdrant connected: {len(_collections)} collections: {_collections}")
    except Exception as e:
        logger.error(f"Qdrant connection failed: {e}")
        _qdrant_client = None


def _refresh_collections():
    """Refresh the collection list from Qdrant."""
    global _collections
    if _qdrant_client:
        try:
            _collections = [c.name for c in _qdrant_client.get_collections().collections]
        except Exception:
            pass


def search(query, top_k=5, threshold=0.15):
    """Semantic search across all Qdrant collections."""
    if not _model or not _qdrant_client:
        return []

    # Refresh collections in case new ones were created
    _refresh_collections()

    # Generate query embedding
    vector = _model.encode(query).tolist()

    results = []
    for collection_name in _collections:
        try:
            response = _qdrant_client.query_points(
                collection_name=collection_name,
                query=vector,
                limit=top_k,
            )
            for hit in response.points:
                if hit.score < threshold:
                    continue
                payload = hit.payload or {}
                text = payload.get("text", payload.get("content", ""))
                section = payload.get("section", "")
                source = collection_name.replace("agent42_", "")

                if text:
                    results.append(
                        {
                            "text": text[:300],
                            "section": section,
                            "score": round(hit.score, 3),
                            "source": source,
                        }
                    )
        except Exception as e:
            logger.debug(f"Search error in {collection_name}: {e}")

    # Sort by score descending, deduplicate
    results.sort(key=lambda r: r["score"], reverse=True)

    # Deduplicate by text prefix
    seen = set()
    unique = []
    for r in results:
        key = r["text"][:80].lower()
        if key not in seen:
            seen.add(key)
            unique.append(r)

    return unique[:top_k]


class SearchHandler(BaseHTTPRequestHandler):
    """HTTP handler for search requests."""

    def log_message(self, format, *args):
        # Suppress default access logs (too noisy)
        pass

    def _send_json(self, data, status=200):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/health":
            self._send_json(
                {
                    "status": "ok",
                    "model": _model_name if _model else None,
                    "model_loaded": _model is not None,
                    "qdrant": _qdrant_client is not None,
                    "collections": _collections,
                }
            )
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        if self.path == "/search":
            try:
                content_length = int(self.headers.get("Content-Length", 0))
                body = json.loads(self.rfile.read(content_length))
                query = body.get("query", "")
                top_k = body.get("top_k", 5)
                threshold = body.get("threshold", 0.15)

                if not query:
                    self._send_json({"error": "query is required"}, 400)
                    return

                results = search(query, top_k=top_k, threshold=threshold)
                self._send_json({"results": results, "count": len(results)})
            except Exception as e:
                logger.error(f"Search error: {e}")
                self._send_json({"error": str(e)}, 500)
        else:
            self._send_json({"error": "not found"}, 404)


def main():
    parser = argparse.ArgumentParser(description="Agent42 Memory Search Service")
    parser.add_argument("--port", type=int, default=6380, help="HTTP port (default: 6380)")
    parser.add_argument("--qdrant-url", default="http://localhost:6333", help="Qdrant server URL")
    args = parser.parse_args()

    _init_model()
    _init_qdrant(args.qdrant_url)

    if not _model:
        logger.error("No embedding model — exiting")
        sys.exit(1)

    server = HTTPServer(("127.0.0.1", args.port), SearchHandler)
    logger.info(f"Search service listening on http://127.0.0.1:{args.port}")
    logger.info(f"  Model: {_model_name} ({'loaded' if _model else 'FAILED'})")
    logger.info(f"  Qdrant: {'connected' if _qdrant_client else 'FAILED'}")

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down")
        server.shutdown()


if __name__ == "__main__":
    main()

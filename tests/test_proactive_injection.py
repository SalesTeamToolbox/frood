"""Tests for proactive context injection API (Phase 22: RETR-03, RETR-04).

Covers:
- RETR-03: GET /api/learnings/retrieve returns task-type-filtered learnings
- RETR-04: Score gate (raw_score >= 0.80) prevents low-relevance results
- Quarantine gate: quarantined learnings never returned
- Token cap: total_tokens <= 500
- Graceful degradation: empty results when Qdrant unavailable or no matches
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

try:
    from fastapi.testclient import TestClient

    from dashboard.server import create_app
    from dashboard.websocket_manager import WebSocketManager

    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False


# ---------------------------------------------------------------------------
# Shared mock helpers
# ---------------------------------------------------------------------------


def _make_result(
    text: str, raw_score: float, quarantined: bool = False, task_type: str = "coding"
) -> dict:
    """Build a mock semantic_search result entry."""
    score = raw_score * 0.9  # lifecycle-adjusted score always <= raw
    return {
        "text": text,
        "source": "history",
        "section": "learning",
        "score": round(score, 4),
        "raw_score": round(raw_score, 4),
        "confidence": 0.6 if quarantined else 1.0,
        "recall_count": 1,
        "point_id": "fake-point-id",
        "metadata": {
            "task_type": task_type,
            "task_id": "task-abc",
            "quarantined": quarantined,
            "observation_count": 1 if quarantined else 5,
            "outcome": "success",
        },
    }


def _make_app_with_mock_store(mock_results: list):
    """Create a TestClient app where memory_store.semantic_search returns mock_results."""
    ws = WebSocketManager()
    ag = MagicMock()

    mock_store = MagicMock()
    mock_store.semantic_search = AsyncMock(return_value=mock_results)

    with patch("dashboard.server.settings") as mock_settings:
        mock_settings.get_cors_origins.return_value = []
        mock_settings.max_websocket_connections = 50
        app = create_app(ws, ag, memory_store=mock_store)
    return TestClient(app), mock_store


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="fastapi test dependencies not installed")
class TestLearningsRetrieve:
    """RETR-03, RETR-04: GET /api/learnings/retrieve endpoint."""

    def setup_method(self):
        """Create mock result set shared across tests.

        Results:
        - result_a: raw_score=0.90, quarantined=False  -> INCLUDED
        - result_b: raw_score=0.85, quarantined=False  -> INCLUDED
        - result_low: raw_score=0.75, quarantined=False -> EXCLUDED (score < 0.80)
        - result_quarantined: raw_score=0.92, quarantined=True -> EXCLUDED (quarantined)
        """
        self.result_a = _make_result(
            "Use async patterns for all file I/O in Python", raw_score=0.90
        )
        self.result_b = _make_result(
            "Always mock external services in tests — never hit real APIs", raw_score=0.85
        )
        self.result_low = _make_result(
            "This is a weakly relevant result that should be filtered out", raw_score=0.75
        )
        self.result_quarantined = _make_result(
            "Quarantined learning with high raw_score — should still be excluded",
            raw_score=0.92,
            quarantined=True,
        )
        self.all_results = [
            self.result_a,
            self.result_b,
            self.result_low,
            self.result_quarantined,
        ]

    def test_returns_results_json_structure(self):
        """RETR-03: Endpoint returns {"results": [...], "total_tokens": int, "task_type": str}."""
        client, _ = _make_app_with_mock_store(self.all_results)
        resp = client.get("/api/learnings/retrieve?task_type=coding&top_k=3&min_score=0.80")
        assert resp.status_code == 200
        data = resp.json()
        assert "results" in data
        assert "total_tokens" in data
        assert "task_type" in data
        assert data["task_type"] == "coding"

    def test_score_gate_excludes_low_raw_score(self):
        """RETR-04: Results with raw_score < 0.80 are excluded."""
        client, _ = _make_app_with_mock_store(self.all_results)
        resp = client.get("/api/learnings/retrieve?task_type=coding&min_score=0.80")
        assert resp.status_code == 200
        data = resp.json()
        result_texts = [r["text"] for r in data["results"]]
        assert self.result_low["text"] not in result_texts

    def test_quarantine_gate_excludes_quarantined_results(self):
        """Quarantined results are excluded even when raw_score >= 0.80."""
        client, _ = _make_app_with_mock_store(self.all_results)
        resp = client.get("/api/learnings/retrieve?task_type=coding&min_score=0.80")
        assert resp.status_code == 200
        data = resp.json()
        result_texts = [r["text"] for r in data["results"]]
        assert self.result_quarantined["text"] not in result_texts

    def test_high_score_non_quarantined_included(self):
        """Results passing both gates are included in results."""
        client, _ = _make_app_with_mock_store(self.all_results)
        resp = client.get("/api/learnings/retrieve?task_type=coding&min_score=0.80")
        assert resp.status_code == 200
        data = resp.json()
        result_texts = [r["text"] for r in data["results"]]
        assert self.result_a["text"] in result_texts
        assert self.result_b["text"] in result_texts

    def test_token_cap_does_not_exceed_500(self):
        """Response total_tokens never exceeds 500."""
        # Create results with long text to force truncation
        long_results = [
            _make_result(" ".join(["word"] * 300), raw_score=0.95),
            _make_result(" ".join(["word"] * 250), raw_score=0.90),
            _make_result(" ".join(["word"] * 200), raw_score=0.85),
        ]
        client, _ = _make_app_with_mock_store(long_results)
        resp = client.get("/api/learnings/retrieve?task_type=coding&top_k=3&min_score=0.80")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_tokens"] <= 500

    def test_graceful_degradation_none_memory_store(self):
        """When memory_store is None, returns empty results gracefully."""
        ws = WebSocketManager()
        ag = MagicMock()
        with patch("dashboard.server.settings") as mock_settings:
            mock_settings.get_cors_origins.return_value = []
            mock_settings.max_websocket_connections = 50
            app = create_app(ws, ag, memory_store=None)
        client = TestClient(app)
        resp = client.get("/api/learnings/retrieve?task_type=coding")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"results": [], "total_tokens": 0, "task_type": "coding"}

    def test_graceful_degradation_semantic_search_raises(self):
        """When semantic_search raises an exception, returns empty results."""
        ws = WebSocketManager()
        ag = MagicMock()
        mock_store = MagicMock()
        mock_store.semantic_search = AsyncMock(side_effect=RuntimeError("Qdrant unavailable"))
        with patch("dashboard.server.settings") as mock_settings:
            mock_settings.get_cors_origins.return_value = []
            mock_settings.max_websocket_connections = 50
            app = create_app(ws, ag, memory_store=mock_store)
        client = TestClient(app)
        resp = client.get("/api/learnings/retrieve?task_type=coding")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total_tokens"] == 0

    def test_top_k_defaults_to_3(self):
        """top_k defaults to 3 when not specified."""
        # 5 valid results to verify top_k=3 is the cap
        five_results = [
            _make_result(f"Learning number {i}", raw_score=0.90 - i * 0.01) for i in range(5)
        ]
        client, _ = _make_app_with_mock_store(five_results)
        resp = client.get("/api/learnings/retrieve?task_type=coding")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) <= 3

    def test_min_score_defaults_to_0_80(self):
        """min_score defaults to 0.80 when not specified."""
        # Mix: 2 high score, 1 below 0.80
        results = [
            _make_result("High score A", raw_score=0.95),
            _make_result("High score B", raw_score=0.82),
            _make_result("Below default threshold", raw_score=0.79),
        ]
        client, _ = _make_app_with_mock_store(results)
        resp = client.get("/api/learnings/retrieve?task_type=coding")
        assert resp.status_code == 200
        data = resp.json()
        result_texts = [r["text"] for r in data["results"]]
        assert "Below default threshold" not in result_texts

    def test_empty_task_type_returns_empty(self):
        """Empty task_type returns empty results (task_type is required)."""
        client, _ = _make_app_with_mock_store(self.all_results)
        resp = client.get("/api/learnings/retrieve?task_type=")
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total_tokens"] == 0

    def test_result_fields_in_response(self):
        """Each result in response includes text, score, raw_score, task_type, outcome."""
        client, _ = _make_app_with_mock_store([self.result_a])
        resp = client.get("/api/learnings/retrieve?task_type=coding&min_score=0.80")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["results"]) == 1
        r = data["results"][0]
        assert "text" in r
        assert "score" in r
        assert "raw_score" in r
        assert "task_type" in r
        assert "outcome" in r

    def test_query_param_forwarded_to_semantic_search(self):
        """query parameter is forwarded to memory_store.semantic_search."""
        ws = WebSocketManager()
        ag = MagicMock()
        mock_store = MagicMock()
        mock_store.semantic_search = AsyncMock(return_value=[self.result_a])
        with patch("dashboard.server.settings") as mock_settings:
            mock_settings.get_cors_origins.return_value = []
            mock_settings.max_websocket_connections = 50
            app = create_app(ws, ag, memory_store=mock_store)
        client = TestClient(app)
        resp = client.get(
            "/api/learnings/retrieve?task_type=coding&query=build+flask+app&min_score=0.80"
        )
        assert resp.status_code == 200
        # Verify semantic_search was called with the user query
        call_kwargs = mock_store.semantic_search.call_args
        # query should be the user prompt, not the task_type fallback
        called_query = call_kwargs.kwargs.get("query") or call_kwargs.args[0]
        assert called_query == "build flask app"

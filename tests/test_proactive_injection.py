"""Tests for proactive context injection API (Phase 22: RETR-03, RETR-04).

Covers:
- RETR-03: GET /api/learnings/retrieve returns task-type-filtered learnings
- RETR-04: Score gate (raw_score >= 0.80) prevents low-relevance results
- Quarantine gate: quarantined learnings never returned
- Token cap: total_tokens <= 500
- Graceful degradation: empty results when Qdrant unavailable or no matches
- TestProactiveInjectHook: hook logic for task_type inference and session guard
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


# ---------------------------------------------------------------------------
# _make_app_with_mock_effectiveness_store helper
# ---------------------------------------------------------------------------


def _make_app_with_mock_effectiveness_store(mock_recs: list):
    """Create a TestClient app where effectiveness_store.get_recommendations returns mock_recs."""
    ws = WebSocketManager()
    ag = MagicMock()
    mock_store = MagicMock()
    mock_store.get_recommendations = AsyncMock(return_value=mock_recs)
    with patch("dashboard.server.settings") as mock_settings:
        mock_settings.get_cors_origins.return_value = []
        mock_settings.max_websocket_connections = 50
        mock_settings.recommendations_min_observations = 5
        app = create_app(ws, ag, effectiveness_store=mock_store)
    return TestClient(app), mock_store


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="fastapi test dependencies not installed")
class TestRecommendationsRetrieve:
    """RETR-05, RETR-06: GET /api/recommendations/retrieve endpoint."""

    def setup_method(self):
        self.mock_recs = [
            {
                "tool_name": "shell",
                "task_type": "coding",
                "invocations": 10,
                "success_rate": 0.92,
                "avg_duration_ms": 45.0,
            },
            {
                "tool_name": "code_intel",
                "task_type": "coding",
                "invocations": 8,
                "success_rate": 0.87,
                "avg_duration_ms": 120.0,
            },
            {
                "tool_name": "grep",
                "task_type": "coding",
                "invocations": 6,
                "success_rate": 0.85,
                "avg_duration_ms": 30.0,
            },
        ]

    def test_returns_recommendations_json_structure(self):
        """RETR-05: Endpoint returns {recommendations: [...], task_type: str}."""
        client, _ = _make_app_with_mock_effectiveness_store(self.mock_recs)
        resp = client.get("/api/recommendations/retrieve?task_type=coding")
        assert resp.status_code == 200
        data = resp.json()
        assert "recommendations" in data
        assert "task_type" in data
        assert data["task_type"] == "coding"

    def test_recommendation_fields(self):
        """Each recommendation has tool_name, success_rate, avg_duration_ms, invocations."""
        client, _ = _make_app_with_mock_effectiveness_store(self.mock_recs)
        resp = client.get("/api/recommendations/retrieve?task_type=coding")
        data = resp.json()
        assert len(data["recommendations"]) == 3
        for rec in data["recommendations"]:
            assert "tool_name" in rec
            assert "success_rate" in rec
            assert "avg_duration_ms" in rec
            assert "invocations" in rec

    def test_empty_task_type_returns_empty(self):
        """Empty task_type returns empty recommendations."""
        client, _ = _make_app_with_mock_effectiveness_store(self.mock_recs)
        resp = client.get("/api/recommendations/retrieve?task_type=")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"recommendations": [], "task_type": ""}

    def test_graceful_degradation_none_effectiveness_store(self):
        """When effectiveness_store is None, returns empty recommendations."""
        ws = WebSocketManager()
        ag = MagicMock()
        with patch("dashboard.server.settings") as mock_settings:
            mock_settings.get_cors_origins.return_value = []
            mock_settings.max_websocket_connections = 50
            mock_settings.recommendations_min_observations = 5
            app = create_app(ws, ag, effectiveness_store=None)
        client = TestClient(app)
        resp = client.get("/api/recommendations/retrieve?task_type=coding")
        assert resp.status_code == 200
        data = resp.json()
        assert data == {"recommendations": [], "task_type": "coding"}

    def test_graceful_degradation_store_raises(self):
        """When get_recommendations raises, returns empty recommendations."""
        ws = WebSocketManager()
        ag = MagicMock()
        mock_store = MagicMock()
        mock_store.get_recommendations = AsyncMock(side_effect=RuntimeError("DB error"))
        with patch("dashboard.server.settings") as mock_settings:
            mock_settings.get_cors_origins.return_value = []
            mock_settings.max_websocket_connections = 50
            mock_settings.recommendations_min_observations = 5
            app = create_app(ws, ag, effectiveness_store=mock_store)
        client = TestClient(app)
        resp = client.get("/api/recommendations/retrieve?task_type=coding")
        assert resp.status_code == 200
        data = resp.json()
        assert data["recommendations"] == []

    def test_min_observations_uses_config_default(self):
        """min_observations=0 falls back to settings.recommendations_min_observations."""
        client, mock_store = _make_app_with_mock_effectiveness_store([])
        client.get("/api/recommendations/retrieve?task_type=coding")
        call_kwargs = mock_store.get_recommendations.call_args
        assert call_kwargs.kwargs.get("min_observations") == 5


# ---------------------------------------------------------------------------
# TestProactiveInjectHook — hook logic tests (no server needed)
# ---------------------------------------------------------------------------

import importlib.util
import json
import os
import sys


def _load_hook_module():
    """Load proactive-inject.py hook module directly from .claude/hooks/."""
    hook_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        ".claude",
        "hooks",
        "proactive-inject.py",
    )
    spec = importlib.util.spec_from_file_location("proactive_inject", hook_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


class TestProactiveInjectHook:
    """Tests for .claude/hooks/proactive-inject.py hook logic."""

    @pytest.fixture(autouse=True)
    def load_hook(self):
        """Load the hook module once per test."""
        self.hook = _load_hook_module()

    def test_infer_task_type_debugging(self):
        """Test 1: infer_task_type('fix the login bug in auth.py') returns 'debugging'."""
        result = self.hook.infer_task_type("fix the login bug in auth.py")
        assert result == "debugging"

    def test_infer_task_type_coding(self):
        """Test 2: infer_task_type('build a new REST API endpoint') returns 'coding'."""
        result = self.hook.infer_task_type("build a new REST API endpoint")
        assert result == "coding"

    def test_infer_task_type_too_short(self):
        """Test 3: infer_task_type('what is this?') returns '' (too short/no signal)."""
        result = self.hook.infer_task_type("what is this?")
        assert result == ""

    def test_infer_task_type_app_create(self):
        """Test 4: infer_task_type('create a flask app') returns 'app_create'."""
        result = self.hook.infer_task_type("create a flask app")
        assert result == "app_create"

    def test_is_injection_done_no_file(self, tmp_path):
        """Test 5: is_injection_done() returns False when injection-done.json does not exist."""
        result = self.hook.is_injection_done(str(tmp_path), "test-session-123")
        assert result is False

    def test_is_injection_done_after_mark(self, tmp_path, monkeypatch):
        """Test 6: is_injection_done() returns True after mark_injection_done() is called."""
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        session_id = "test-session-abc"
        self.hook.mark_injection_done(str(tmp_path), session_id)
        result = self.hook.is_injection_done(str(tmp_path), session_id)
        assert result is True

    def test_is_injection_done_different_session(self, tmp_path, monkeypatch):
        """Test 7: is_injection_done() returns False when injection-done.json has different session_id."""
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        self.hook.mark_injection_done(str(tmp_path), "session-original")
        result = self.hook.is_injection_done(str(tmp_path), "session-different")
        assert result is False

    def test_format_injection_output_truncates(self):
        """Test 8: format_injection_output truncates to MAX_OUTPUT_CHARS (2000)."""
        # Build a list of results with very long text
        results = [
            {"score": 0.95, "text": "word " * 1000},
            {"score": 0.92, "text": "word " * 1000},
            {"score": 0.88, "text": "word " * 1000},
        ]
        output = self.hook.format_injection_output(results, "coding")
        assert len(output) <= self.hook.MAX_OUTPUT_CHARS

    def test_hook_skips_slash_commands(self, tmp_path, monkeypatch):
        """Test 9: Hook skips injection when prompt starts with '/'."""
        # We test via the main() function logic by checking that infer_task_type
        # is never called when the prompt starts with '/'. We verify via the
        # is_injection_done guard: if the hook runs but skips due to slash,
        # the injection-done file should NOT be written.
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        monkeypatch.setenv("FROOD_DATA_DIR", ".frood")
        # A slash command that would otherwise match a task type keyword
        prompt = "/gsd:execute-phase build a new API endpoint for authentication"
        # The hook should detect slash command and skip — infer_task_type handles
        # but main() should short-circuit. We test main() behavior via stdin mock.
        import io

        event = {
            "hook_event_name": "UserPromptSubmit",
            "project_dir": str(tmp_path),
            "user_prompt": prompt,
            "session_id": "slash-session",
        }
        stdin_data = json.dumps(event)
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))
        # main() should exit 0 without writing guard file
        with pytest.raises(SystemExit) as exc:
            self.hook.main()
        assert exc.value.code == 0
        guard_file = tmp_path / ".frood" / "injection-done.json"
        assert not guard_file.exists()

    def test_hook_skips_short_prompts(self, tmp_path, monkeypatch):
        """Test 10: Hook skips injection when prompt length < 15 characters."""
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        import io

        event = {
            "hook_event_name": "UserPromptSubmit",
            "project_dir": str(tmp_path),
            "user_prompt": "build API",  # 9 chars, below MIN_PROMPT_LEN=15
            "session_id": "short-session",
        }
        stdin_data = json.dumps(event)
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin_data))
        with pytest.raises(SystemExit) as exc:
            self.hook.main()
        assert exc.value.code == 0
        guard_file = tmp_path / ".frood" / "injection-done.json"
        assert not guard_file.exists()


# ---------------------------------------------------------------------------
# TestRecommendationsHook — tests for fetch_recommendations, format, updated main()
# ---------------------------------------------------------------------------


class TestRecommendationsHook:
    """Tests for recommendations functions in proactive-inject.py hook."""

    @pytest.fixture(autouse=True)
    def load_hook(self):
        """Load the hook module once per test."""
        self.hook = _load_hook_module()

    def test_format_recommendations_output_with_recs(self):
        """format_recommendations_output produces ranked list with correct format."""
        recs = [
            {"tool_name": "shell", "success_rate": 0.92, "avg_duration_ms": 45.0},
            {"tool_name": "code_intel", "success_rate": 0.87, "avg_duration_ms": 120.0},
            {"tool_name": "grep", "success_rate": 0.85, "avg_duration_ms": 30.0},
        ]
        output = self.hook.format_recommendations_output(recs, "coding")
        assert "[frood-recommendations]" in output
        assert "Top tools for coding" in output
        assert "1. shell (92% success, 45ms avg)" in output
        assert "2. code_intel (87% success, 120ms avg)" in output
        assert "3. grep (85% success, 30ms avg)" in output

    def test_format_recommendations_output_empty(self):
        """format_recommendations_output returns empty string for no recs."""
        output = self.hook.format_recommendations_output([], "coding")
        assert output == ""

    def test_format_recommendations_output_truncates(self):
        """format_recommendations_output truncates to MAX_OUTPUT_CHARS."""
        recs = [
            {"tool_name": "x" * 500, "success_rate": 0.9, "avg_duration_ms": 100.0}
            for _ in range(20)
        ]
        output = self.hook.format_recommendations_output(recs, "coding")
        assert len(output) <= self.hook.MAX_OUTPUT_CHARS

    def test_main_emits_recs_when_learnings_empty(self, tmp_path, monkeypatch, capsys):
        """main() emits recommendations even when learnings return empty."""
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        # Mock fetch_learnings to return empty, fetch_recommendations to return data
        monkeypatch.setattr(self.hook, "fetch_learnings", lambda q, t: [])
        monkeypatch.setattr(
            self.hook,
            "fetch_recommendations",
            lambda t: [{"tool_name": "shell", "success_rate": 0.9, "avg_duration_ms": 50.0}],
        )
        import io

        event = {
            "hook_event_name": "UserPromptSubmit",
            "project_dir": str(tmp_path),
            "user_prompt": "implement a new REST API endpoint for users",
            "session_id": "recs-only-session",
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        with pytest.raises(SystemExit) as exc:
            self.hook.main()
        assert exc.value.code == 0
        # Recommendations should appear in stderr
        captured = capsys.readouterr()
        assert "[frood-recommendations]" in captured.err
        assert "shell" in captured.err

    def test_main_writes_guard_with_recs_only(self, tmp_path, monkeypatch, capsys):
        """main() writes guard file when only recommendations are emitted."""
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        monkeypatch.setattr(self.hook, "fetch_learnings", lambda q, t: [])
        monkeypatch.setattr(
            self.hook,
            "fetch_recommendations",
            lambda t: [{"tool_name": "shell", "success_rate": 0.9, "avg_duration_ms": 50.0}],
        )
        import io

        event = {
            "hook_event_name": "UserPromptSubmit",
            "project_dir": str(tmp_path),
            "user_prompt": "implement a new REST API endpoint for users",
            "session_id": "recs-guard-session",
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        with pytest.raises(SystemExit):
            self.hook.main()
        guard_file = tmp_path / ".frood" / "injection-done.json"
        assert guard_file.exists()
        data = json.loads(guard_file.read_text())
        assert data["session_id"] == "recs-guard-session"

    def test_main_no_guard_when_both_empty(self, tmp_path, monkeypatch, capsys):
        """main() does NOT write guard file when both learnings and recs are empty."""
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        monkeypatch.setattr(self.hook, "fetch_learnings", lambda q, t: [])
        monkeypatch.setattr(self.hook, "fetch_recommendations", lambda t: [])
        import io

        event = {
            "hook_event_name": "UserPromptSubmit",
            "project_dir": str(tmp_path),
            "user_prompt": "implement a new REST API endpoint for users",
            "session_id": "empty-session",
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        with pytest.raises(SystemExit) as exc:
            self.hook.main()
        assert exc.value.code == 0
        guard_file = tmp_path / ".frood" / "injection-done.json"
        assert not guard_file.exists()

    def test_fetch_recommendations_graceful_on_error(self, monkeypatch):
        """fetch_recommendations returns [] on any exception."""
        monkeypatch.setattr(self.hook, "DASHBOARD_URL", "http://localhost:99999")
        result = self.hook.fetch_recommendations("coding")
        assert result == []

    def test_main_emits_both_blocks_separately(self, tmp_path, monkeypatch, capsys):
        """main() emits learnings and recommendations as separate stderr blocks (D-07)."""
        monkeypatch.setattr(self.hook, "INJECTION_GUARD_DIR", ".frood")
        monkeypatch.setattr(
            self.hook,
            "fetch_learnings",
            lambda q, t: [{"score": 0.9, "text": "Use async for file I/O"}],
        )
        monkeypatch.setattr(
            self.hook,
            "fetch_recommendations",
            lambda t: [{"tool_name": "shell", "success_rate": 0.92, "avg_duration_ms": 45.0}],
        )
        import io

        event = {
            "hook_event_name": "UserPromptSubmit",
            "project_dir": str(tmp_path),
            "user_prompt": "implement a new REST API endpoint for users",
            "session_id": "both-blocks-session",
        }
        monkeypatch.setattr(sys, "stdin", io.StringIO(json.dumps(event)))
        with pytest.raises(SystemExit):
            self.hook.main()
        captured = capsys.readouterr()
        # Both distinct headers present in stderr
        assert "[frood-learnings]" in captured.err
        assert "[frood-recommendations]" in captured.err

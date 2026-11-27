"""Tests for GET /api/cc/pace and the read-only settings-panel card (cc-pacing-v2-b2)."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from dashboard.auth import AuthContext, get_current_user, require_admin
from dashboard.server import create_app

APP_JS = Path(__file__).resolve().parents[1] / "dashboard" / "frontend" / "dist" / "app.js"


def _make_client(*, admin: bool = True, **kwargs) -> TestClient:
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "app_manager": MagicMock(),
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    if admin:
        app.dependency_overrides[get_current_user] = lambda: "test-user"
        app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
    return TestClient(app)


def test_cc_pace_requires_auth():
    client = _make_client(admin=False)
    with patch("core.cc_pace.read_pace", new=AsyncMock(return_value={"state": "on"})) as rp:
        resp = client.get("/api/cc/pace")
    assert resp.status_code == 401
    rp.assert_not_called()


def test_cc_pace_admin_returns_reader_body():
    body = {"state": "under", "weekly": 40, "projected": 70, "five_hour": 20}
    client = _make_client()
    with patch("core.cc_pace.read_pace", new=AsyncMock(return_value=body)):
        resp = client.get("/api/cc/pace")
    assert resp.status_code == 200
    assert resp.json() == body


def test_cc_pace_admin_unknown_passthrough():
    body = {"state": "unknown", "reason": "node not found"}
    client = _make_client()
    with patch("core.cc_pace.read_pace", new=AsyncMock(return_value=body)):
        resp = client.get("/api/cc/pace")
    assert resp.status_code == 200
    assert resp.json() == body


def test_bundle_has_cc_pace_card():
    js = APP_JS.read_text()
    assert "loadCcPace" in js
    assert '"/cc/pace"' in js
    assert "Claude subscription:" in js
    assert 'cp.state !== "off"' in js
    assert "ccPace: null" in js
    assert "ccPaceLoading: false" in js
    # the card uses the bundle's single escape helper
    assert js.count("function esc(") == 1
    assert "esc(cpLine)" in js

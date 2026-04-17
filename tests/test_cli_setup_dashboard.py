"""Tests for the CLI Setup dashboard endpoints + frontend panel wiring.

Covers DASH-01..DASH-04:
- DASH-01: GET /api/cli-setup/detect admin-guarded
- DASH-02: POST /api/cli-setup/wire dispatches to core.cli_setup.{wire_cli,unwire_cli}
- DASH-03: dashboard/frontend/dist/app.js has a CLI Setup panel
- DASH-04: toggle state persisted to .frood/cli-setup-state.json
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from dashboard.auth import AuthContext, get_current_user, require_admin
from dashboard.server import (
    _load_cli_setup_state,
    _save_cli_setup_state,
    create_app,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _make_admin_client(**kwargs) -> TestClient:
    """Create a TestClient with require_admin overridden to a stub admin."""
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "app_manager": MagicMock(),
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    app.dependency_overrides[get_current_user] = lambda: "test-user"
    app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
    return TestClient(app)


def _make_anonymous_client(**kwargs) -> TestClient:
    """Create a TestClient with NO auth overrides — require_admin stays real."""
    defaults = {
        "tool_registry": None,
        "skill_loader": None,
        "app_manager": MagicMock(),
    }
    defaults.update(kwargs)
    app = create_app(**defaults)
    return TestClient(app)


def _redirect_state_file(monkeypatch, tmp_path: Path) -> Path:
    """Redirect _CLI_SETUP_STATE_FILE to a sandbox path so tests don't touch
    the real .frood/ directory."""
    state_file = tmp_path / "cli-setup-state.json"
    monkeypatch.setattr("dashboard.server._CLI_SETUP_STATE_FILE", state_file)
    return state_file


# ---------------------------------------------------------------------------
# DASH-01: GET /api/cli-setup/detect admin guard
# ---------------------------------------------------------------------------


def test_detect_requires_admin():
    """Anonymous GET /api/cli-setup/detect is rejected by require_admin."""
    client = _make_anonymous_client()
    resp = client.get("/api/cli-setup/detect")
    assert resp.status_code in (401, 403), (
        f"Expected auth rejection, got {resp.status_code}: {resp.text}"
    )


def test_detect_returns_state(monkeypatch):
    """Admin GET /api/cli-setup/detect returns the detect_all() payload."""
    fake_state = {
        "claude-code": {
            "installed": True,
            "wired": False,
            "settings_path": "/fake/.claude/settings.json",
            "enabled": True,
        },
        "opencode": {
            "installed": False,
            "wired": False,
            "projects": [],
            "enabled": True,
        },
    }

    def fake_detect_all():
        return fake_state

    monkeypatch.setattr("core.cli_setup.detect_all", fake_detect_all)

    client = _make_admin_client()
    resp = client.get("/api/cli-setup/detect")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body == fake_state
    assert "claude-code" in body
    assert "opencode" in body


# ---------------------------------------------------------------------------
# DASH-02: POST /api/cli-setup/wire admin guard + dispatch
# ---------------------------------------------------------------------------


def test_wire_requires_admin():
    """Anonymous POST /api/cli-setup/wire is rejected by require_admin."""
    client = _make_anonymous_client()
    resp = client.post("/api/cli-setup/wire", json={"cli": "claude-code", "enabled": True})
    assert resp.status_code in (401, 403), (
        f"Expected auth rejection, got {resp.status_code}: {resp.text}"
    )


def test_wire_enabled_calls_wire_cli(monkeypatch, tmp_path):
    """Admin POST {cli, enabled:true} calls wire_cli and updates state file."""
    calls: list[str] = []

    def fake_wire_cli(cli, manifest=None):
        calls.append(cli)
        return {"ok": True, "cli": cli, "action": "wire"}

    def fake_unwire_cli(cli, manifest=None):
        raise AssertionError("unwire_cli should NOT be called when enabled=True")

    monkeypatch.setattr("core.cli_setup.wire_cli", fake_wire_cli)
    monkeypatch.setattr("core.cli_setup.unwire_cli", fake_unwire_cli)
    state_file = _redirect_state_file(monkeypatch, tmp_path)

    client = _make_admin_client()
    resp = client.post("/api/cli-setup/wire", json={"cli": "claude-code", "enabled": True})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["cli"] == "claude-code"
    assert body["enabled"] is True
    assert body["action"] == "wire"
    assert body["result"] == {"ok": True, "cli": "claude-code", "action": "wire"}
    assert calls == ["claude-code"]

    # State file contains the newly-enabled CLI
    assert state_file.exists()
    persisted = json.loads(state_file.read_text())
    assert persisted == {"enabled_clis": ["claude-code"]}


def test_wire_disabled_calls_unwire_cli(monkeypatch, tmp_path):
    """Admin POST {cli, enabled:false} calls unwire_cli and drops the CLI
    from the persisted state."""
    calls: list[str] = []

    def fake_wire_cli(cli, manifest=None):
        raise AssertionError("wire_cli should NOT be called when enabled=False")

    def fake_unwire_cli(cli, manifest=None):
        calls.append(cli)
        return {"ok": True, "cli": cli, "action": "unwire"}

    monkeypatch.setattr("core.cli_setup.wire_cli", fake_wire_cli)
    monkeypatch.setattr("core.cli_setup.unwire_cli", fake_unwire_cli)
    state_file = _redirect_state_file(monkeypatch, tmp_path)

    # Pre-seed the state as if claude-code was previously enabled
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps({"enabled_clis": ["claude-code", "opencode"]}))

    client = _make_admin_client()
    resp = client.post("/api/cli-setup/wire", json={"cli": "claude-code", "enabled": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["action"] == "unwire"
    assert body["enabled"] is False
    assert calls == ["claude-code"]

    persisted = json.loads(state_file.read_text())
    assert persisted == {"enabled_clis": ["opencode"]}


def test_wire_unknown_cli_400(monkeypatch, tmp_path):
    """Unknown CLI name returns 400 — no core dispatch attempted."""

    def fake_wire_cli(cli, manifest=None):
        raise AssertionError("wire_cli must not be called for unknown CLI")

    monkeypatch.setattr("core.cli_setup.wire_cli", fake_wire_cli)
    monkeypatch.setattr("core.cli_setup.unwire_cli", fake_wire_cli)
    _redirect_state_file(monkeypatch, tmp_path)

    client = _make_admin_client()
    resp = client.post("/api/cli-setup/wire", json={"cli": "nonsense", "enabled": True})
    assert resp.status_code == 400
    body = resp.json()
    # Frood remaps HTTPException.detail → {error, message, status}
    msg = (body.get("message") or body.get("detail") or "").lower()
    assert "nonsense" in msg


def test_wire_propagates_core_error_500(monkeypatch, tmp_path):
    """A core exception bubbles up as HTTP 500 with a useful message."""

    def failing_wire(cli, manifest=None):
        raise RuntimeError("target file missing")

    monkeypatch.setattr("core.cli_setup.wire_cli", failing_wire)
    _redirect_state_file(monkeypatch, tmp_path)

    client = _make_admin_client()
    resp = client.post("/api/cli-setup/wire", json={"cli": "opencode", "enabled": True})
    assert resp.status_code == 500
    body = resp.json()
    msg = body.get("message") or body.get("detail") or ""
    assert "target file missing" in msg


# ---------------------------------------------------------------------------
# DASH-04: state roundtrip via the helpers directly
# ---------------------------------------------------------------------------


def test_state_file_roundtrip(monkeypatch, tmp_path):
    """_save / _load round-trip matches, across a sequence of toggles."""
    state_file = _redirect_state_file(monkeypatch, tmp_path)

    # Initial load when file does not exist returns defaults
    assert _load_cli_setup_state() == {"enabled_clis": []}

    # Save then load
    _save_cli_setup_state(["claude-code"])
    assert state_file.exists()
    assert _load_cli_setup_state() == {"enabled_clis": ["claude-code"]}

    # Save preserves sorted-unique ordering even with duplicates
    _save_cli_setup_state(["opencode", "claude-code", "claude-code"])
    assert _load_cli_setup_state() == {"enabled_clis": ["claude-code", "opencode"]}

    # After a series of endpoint-equivalent mutations, final set is correct
    state = _load_cli_setup_state()
    enabled = set(state.get("enabled_clis", []))
    enabled.discard("claude-code")
    _save_cli_setup_state(sorted(enabled))
    assert _load_cli_setup_state() == {"enabled_clis": ["opencode"]}


# ---------------------------------------------------------------------------
# DASH-03: frontend panel presence (sanity — locks the wiring contract)
# ---------------------------------------------------------------------------


def test_frontend_panel_wired_in_app_js():
    """app.js contains the CLI Setup panel renderer, nav, and fetch calls."""
    content = Path("dashboard/frontend/dist/app.js").read_text(encoding="utf-8")
    # Minimum pattern count: function definition + nav item + renderer map + fetch path
    assert "renderCliSetup" in content, "missing renderCliSetup function"
    assert "/cli-setup/detect" in content, "missing detect fetch call"
    assert "/cli-setup/wire" in content, "missing wire fetch call"
    assert 'data-page="cli-setup"' in content, "missing sidebar nav entry"
    assert '"cli-setup": renderCliSetup' in content, "renderer not wired into page map"

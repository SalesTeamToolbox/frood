"""Tests for multi-device gateway authentication."""

import json
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from core.device_auth import API_KEY_PREFIX, DeviceStore, _hash_key

# ---------------------------------------------------------------------------
# DeviceStore — registration, validation, revocation, persistence
# ---------------------------------------------------------------------------


class TestDeviceRegistration:
    """Device registration and API key generation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "devices.jsonl"
        self.store = DeviceStore(self.store_path)

    def test_register_returns_device_and_key(self):
        device, raw_key = self.store.register("My Laptop", "laptop")
        assert device.name == "My Laptop"
        assert device.device_type == "laptop"
        assert device.device_id
        assert len(device.device_id) == 12
        assert raw_key.startswith(API_KEY_PREFIX)
        assert not device.is_revoked

    def test_register_key_hash_matches(self):
        device, raw_key = self.store.register("Watch", "watch")
        assert device.api_key_hash == _hash_key(raw_key)

    def test_register_default_capabilities(self):
        device, _ = self.store.register("Phone", "phone")
        assert "tasks" in device.capabilities
        assert "monitor" in device.capabilities

    def test_register_custom_capabilities(self):
        device, _ = self.store.register("Tablet", "tablet", capabilities=["approvals"])
        assert device.capabilities == ["approvals"]

    def test_register_invalid_capabilities_filtered(self):
        device, _ = self.store.register("Device", "other", capabilities=["evil", "tasks"])
        assert device.capabilities == ["tasks"]

    def test_register_all_invalid_capabilities_gets_monitor(self):
        device, _ = self.store.register("Device", "other", capabilities=["evil"])
        assert device.capabilities == ["monitor"]

    def test_register_invalid_device_type_defaults_to_other(self):
        device, _ = self.store.register("Unknown", "smartfridge")
        assert device.device_type == "other"

    def test_register_persists_to_jsonl(self):
        self.store.register("Laptop", "laptop")
        assert self.store_path.exists()
        lines = self.store_path.read_text().strip().split("\n")
        assert len(lines) == 1
        entry = json.loads(lines[0])
        assert entry["event"] == "registered"
        assert entry["name"] == "Laptop"

    def test_register_multiple_devices(self):
        d1, _ = self.store.register("Laptop", "laptop")
        d2, _ = self.store.register("Watch", "watch")
        d3, _ = self.store.register("Phone", "phone")
        assert len(self.store.list_devices()) == 3
        assert d1.device_id != d2.device_id != d3.device_id


class TestDeviceValidation:
    """API key validation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = DeviceStore(Path(self.tmpdir) / "devices.jsonl")

    def test_validate_valid_key(self):
        _, raw_key = self.store.register("Laptop", "laptop")
        device = self.store.validate_api_key(raw_key)
        assert device is not None
        assert device.name == "Laptop"

    def test_validate_invalid_key(self):
        self.store.register("Laptop", "laptop")
        result = self.store.validate_api_key("ak_invalid_key_here")
        assert result is None

    def test_validate_non_prefixed_key(self):
        result = self.store.validate_api_key("not_an_api_key")
        assert result is None

    def test_validate_empty_key(self):
        result = self.store.validate_api_key("")
        assert result is None

    def test_validate_updates_last_seen(self):
        _, raw_key = self.store.register("Laptop", "laptop")
        before = self.store.get(self.store.list_devices()[0].device_id).last_seen
        time.sleep(0.01)
        device = self.store.validate_api_key(raw_key)
        assert device.last_seen >= before

    def test_validate_revoked_key_fails(self):
        device, raw_key = self.store.register("Laptop", "laptop")
        self.store.revoke(device.device_id)
        result = self.store.validate_api_key(raw_key)
        assert result is None


class TestDeviceRevocation:
    """Device API key revocation."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = DeviceStore(Path(self.tmpdir) / "devices.jsonl")

    def test_revoke_existing_device(self):
        device, _ = self.store.register("Laptop", "laptop")
        assert self.store.revoke(device.device_id) is True
        assert self.store.get(device.device_id).is_revoked is True

    def test_revoke_nonexistent_device(self):
        assert self.store.revoke("nonexistent123") is False

    def test_revoke_persists_to_jsonl(self):
        device, _ = self.store.register("Laptop", "laptop")
        self.store.revoke(device.device_id)
        path = Path(self.tmpdir) / "devices.jsonl"
        lines = path.read_text().strip().split("\n")
        assert len(lines) == 2
        revoke_entry = json.loads(lines[1])
        assert revoke_entry["event"] == "revoked"
        assert revoke_entry["device_id"] == device.device_id


class TestDevicePersistence:
    """JSONL persistence and reload."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store_path = Path(self.tmpdir) / "devices.jsonl"

    def test_reload_restores_devices(self):
        store1 = DeviceStore(self.store_path)
        d, raw_key = store1.register("Laptop", "laptop")
        device_id = d.device_id

        # Create a new store instance (simulates restart)
        store2 = DeviceStore(self.store_path)
        assert store2.get(device_id) is not None
        assert store2.get(device_id).name == "Laptop"

    def test_reload_restores_revocation(self):
        store1 = DeviceStore(self.store_path)
        d, _ = store1.register("Laptop", "laptop")
        store1.revoke(d.device_id)

        store2 = DeviceStore(self.store_path)
        assert store2.get(d.device_id).is_revoked is True

    def test_reload_validates_key_after_restart(self):
        store1 = DeviceStore(self.store_path)
        _, raw_key = store1.register("Watch", "watch")

        store2 = DeviceStore(self.store_path)
        device = store2.validate_api_key(raw_key)
        assert device is not None
        assert device.name == "Watch"

    def test_reload_revoked_key_still_invalid(self):
        store1 = DeviceStore(self.store_path)
        d, raw_key = store1.register("Phone", "phone")
        store1.revoke(d.device_id)

        store2 = DeviceStore(self.store_path)
        assert store2.validate_api_key(raw_key) is None

    def test_reload_skips_malformed_lines(self):
        self.store_path.write_text("not json\n")
        store = DeviceStore(self.store_path)
        assert len(store.list_devices()) == 0

    def test_reload_empty_file(self):
        self.store_path.write_text("")
        store = DeviceStore(self.store_path)
        assert len(store.list_devices()) == 0

    def test_reload_no_file(self):
        store = DeviceStore(self.store_path)
        assert len(store.list_devices()) == 0


class TestDeviceListing:
    """Device listing and lookup."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = DeviceStore(Path(self.tmpdir) / "devices.jsonl")

    def test_list_empty(self):
        assert self.store.list_devices() == []

    def test_list_includes_all(self):
        self.store.register("A", "laptop")
        self.store.register("B", "watch")
        assert len(self.store.list_devices()) == 2

    def test_list_includes_revoked(self):
        d, _ = self.store.register("A", "laptop")
        self.store.revoke(d.device_id)
        devices = self.store.list_devices()
        assert len(devices) == 1
        assert devices[0].is_revoked is True

    def test_get_existing(self):
        d, _ = self.store.register("Laptop", "laptop")
        assert self.store.get(d.device_id) is not None

    def test_get_nonexistent(self):
        assert self.store.get("nonexistent") is None


# ---------------------------------------------------------------------------
# Auth layer — dual auth (JWT + API key)
# ---------------------------------------------------------------------------


class TestAuthContext:
    """AuthContext dataclass and dual auth helpers."""

    def test_auth_context_jwt_defaults(self):
        from dashboard.auth import AuthContext

        ctx = AuthContext(user="admin")
        assert ctx.auth_type == "jwt"
        assert ctx.device_id == ""
        assert ctx.device_name == ""

    def test_auth_context_api_key(self):
        from dashboard.auth import AuthContext

        ctx = AuthContext(
            user="device", auth_type="api_key", device_id="abc123", device_name="Watch"
        )
        assert ctx.auth_type == "api_key"
        assert ctx.device_id == "abc123"


class TestDualAuth:
    """Test JWT and API key authentication paths."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.store = DeviceStore(Path(self.tmpdir) / "devices.jsonl")

    def test_validate_api_key_path(self):
        from dashboard.auth import _validate_api_key, init_device_store

        init_device_store(self.store)
        _, raw_key = self.store.register("Laptop", "laptop")
        ctx = _validate_api_key(raw_key)
        assert ctx.auth_type == "api_key"
        assert ctx.device_name == "Laptop"

    def test_validate_api_key_invalid(self):
        from dashboard.auth import _validate_api_key, init_device_store

        init_device_store(self.store)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_api_key("ak_invalid")
        assert exc_info.value.status_code == 401

    def test_validate_api_key_no_store(self):
        from dashboard.auth import _validate_api_key, init_device_store

        init_device_store(None)
        from fastapi import HTTPException

        with pytest.raises(HTTPException) as exc_info:
            _validate_api_key("ak_something")
        assert exc_info.value.status_code == 401

    def test_validate_jwt_valid(self):
        from dashboard.auth import _validate_jwt, create_token

        token = create_token("admin")
        ctx = _validate_jwt(token)
        assert ctx.user == "admin"
        assert ctx.auth_type == "jwt"

    def test_validate_jwt_invalid(self):
        from fastapi import HTTPException

        from dashboard.auth import _validate_jwt

        with pytest.raises(HTTPException):
            _validate_jwt("invalid.jwt.token")


# ---------------------------------------------------------------------------
# Dashboard device endpoints
# ---------------------------------------------------------------------------

try:
    from fastapi.testclient import TestClient

    from core.approval_gate import ApprovalGate
    from core.task_queue import TaskQueue
    from dashboard.auth import create_token, init_device_store
    from dashboard.server import create_app
    from dashboard.websocket_manager import WebSocketManager

    HAS_TESTCLIENT = True
except ImportError:
    HAS_TESTCLIENT = False


@pytest.mark.skipif(not HAS_TESTCLIENT, reason="fastapi test dependencies not installed")
class TestDeviceEndpoints:
    """REST API endpoints for device management."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        self.tq = TaskQueue()
        self.ws = WebSocketManager()
        self.ag = ApprovalGate(self.tq)
        self.ds = DeviceStore(Path(self.tmpdir) / "devices.jsonl")
        init_device_store(self.ds)

    def _make_app(self):
        with patch("dashboard.server.settings") as mock_settings:
            mock_settings.dashboard_password = "testpass"
            mock_settings.dashboard_password_hash = ""
            mock_settings.dashboard_username = "admin"
            mock_settings.jwt_secret = "test-secret-32-chars-long-ok-yep"
            mock_settings.max_websocket_connections = 50
            mock_settings.login_rate_limit = 100
            mock_settings.get_cors_origins.return_value = []

            app = create_app(self.tq, self.ws, self.ag, device_store=self.ds)
            return app

    def _get_admin_token(self):
        return create_token("admin")

    def test_register_device(self):
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()
        resp = client.post(
            "/api/devices/register",
            json={"name": "MacBook Pro", "device_type": "laptop"},
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "MacBook Pro"
        assert data["device_type"] == "laptop"
        assert data["api_key"].startswith("ak_")
        assert "device_id" in data

    def test_register_device_requires_admin_jwt(self):
        app = self._make_app()
        client = TestClient(app)
        # Register a device, then try to use its API key to register another
        token = self._get_admin_token()
        resp = client.post(
            "/api/devices/register",
            json={"name": "First", "device_type": "laptop"},
            headers={"Authorization": f"Bearer {token}"},
        )
        device_key = resp.json()["api_key"]

        resp2 = client.post(
            "/api/devices/register",
            json={"name": "Second", "device_type": "phone"},
            headers={"Authorization": f"Bearer {device_key}"},
        )
        assert resp2.status_code == 403

    def test_list_devices(self):
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()

        # Register a device
        client.post(
            "/api/devices/register",
            json={"name": "Laptop", "device_type": "laptop"},
            headers={"Authorization": f"Bearer {token}"},
        )

        resp = client.get(
            "/api/devices",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 200
        devices = resp.json()
        assert len(devices) == 1
        assert devices[0]["name"] == "Laptop"
        assert "is_online" in devices[0]

    def test_get_device(self):
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()

        resp = client.post(
            "/api/devices/register",
            json={"name": "Watch", "device_type": "watch"},
            headers={"Authorization": f"Bearer {token}"},
        )
        device_id = resp.json()["device_id"]

        resp2 = client.get(
            f"/api/devices/{device_id}",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["name"] == "Watch"

    def test_get_device_not_found(self):
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()
        resp = client.get(
            "/api/devices/nonexistent",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp.status_code == 404

    def test_revoke_device(self):
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()

        resp = client.post(
            "/api/devices/register",
            json={"name": "Old Phone", "device_type": "phone"},
            headers={"Authorization": f"Bearer {token}"},
        )
        device_id = resp.json()["device_id"]
        device_key = resp.json()["api_key"]

        resp2 = client.post(
            f"/api/devices/{device_id}/revoke",
            headers={"Authorization": f"Bearer {token}"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "revoked"

        # Verify the revoked key can't be used for auth
        resp3 = client.get(
            "/api/tasks",
            headers={"Authorization": f"Bearer {device_key}"},
        )
        assert resp3.status_code == 401

    def test_revoke_requires_admin(self):
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()

        resp = client.post(
            "/api/devices/register",
            json={"name": "Phone", "device_type": "phone"},
            headers={"Authorization": f"Bearer {token}"},
        )
        device_id = resp.json()["device_id"]
        device_key = resp.json()["api_key"]

        # Try to revoke using device's own API key
        resp2 = client.post(
            f"/api/devices/{device_id}/revoke",
            headers={"Authorization": f"Bearer {device_key}"},
        )
        assert resp2.status_code == 403

    def test_device_api_key_auth_on_tasks(self):
        """Device API key should grant access to task endpoints."""
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()

        resp = client.post(
            "/api/devices/register",
            json={"name": "Laptop", "device_type": "laptop"},
            headers={"Authorization": f"Bearer {token}"},
        )
        device_key = resp.json()["api_key"]

        # Use device key to list tasks
        resp2 = client.get(
            "/api/tasks",
            headers={"Authorization": f"Bearer {device_key}"},
        )
        assert resp2.status_code == 200

    def test_device_creates_task_with_device_id(self):
        """Task created by device should have origin_device_id set."""
        app = self._make_app()
        client = TestClient(app)
        token = self._get_admin_token()

        resp = client.post(
            "/api/devices/register",
            json={"name": "Watch", "device_type": "watch"},
            headers={"Authorization": f"Bearer {token}"},
        )
        device_id = resp.json()["device_id"]
        device_key = resp.json()["api_key"]

        resp2 = client.post(
            "/api/tasks",
            json={"title": "Fix bug", "description": "Fix the login bug"},
            headers={"Authorization": f"Bearer {device_key}"},
        )
        assert resp2.status_code == 200
        assert resp2.json()["origin_device_id"] == device_id

    def test_no_auth_rejected(self):
        app = self._make_app()
        client = TestClient(app)
        resp = client.get("/api/devices")
        assert resp.status_code in (401, 403)


# ---------------------------------------------------------------------------
# WebSocket manager — device tracking
# ---------------------------------------------------------------------------


class TestWebSocketDeviceTracking:
    """WebSocketManager device identity tracking."""

    def test_connected_device_ids_empty(self):
        ws = WebSocketManager()
        assert ws.connected_device_ids() == set()

    def test_connection_count_zero(self):
        ws = WebSocketManager()
        assert ws.connection_count == 0

    def test_disconnect_nonexistent(self):
        ws = WebSocketManager()
        mock_ws = MagicMock()
        ws.disconnect(mock_ws)  # Should not raise


# ---------------------------------------------------------------------------
# Task model — origin_device_id field
# ---------------------------------------------------------------------------


class TestTaskDeviceField:
    """Task dataclass includes origin_device_id."""

    def test_task_default_device_id_empty(self):
        from core.task_queue import Task

        task = Task(title="Test", description="Test task")
        assert task.origin_device_id == ""

    def test_task_with_device_id(self):
        from core.task_queue import Task

        task = Task(title="Test", description="Test task", origin_device_id="abc123def456")
        assert task.origin_device_id == "abc123def456"

    def test_task_to_dict_includes_device_id(self):
        from core.task_queue import Task

        task = Task(title="Test", description="Test", origin_device_id="dev1")
        d = task.to_dict()
        assert d["origin_device_id"] == "dev1"

    def test_task_from_dict_with_device_id(self):
        from core.task_queue import Task

        data = {
            "title": "Test",
            "description": "Test",
            "origin_device_id": "dev2",
            "status": "pending",
            "task_type": "coding",
        }
        task = Task.from_dict(data)
        assert task.origin_device_id == "dev2"

    def test_task_from_dict_without_device_id(self):
        from core.task_queue import Task

        data = {
            "title": "Test",
            "description": "Test",
            "status": "pending",
            "task_type": "coding",
        }
        task = Task.from_dict(data)
        assert task.origin_device_id == ""


# ---------------------------------------------------------------------------
# Config — devices_file setting
# ---------------------------------------------------------------------------


class TestDeviceConfig:
    """Config includes devices_file setting."""

    def test_default_devices_file(self):
        from core.config import Settings

        s = Settings()
        assert s.devices_file == ".agent42/devices.jsonl"

    def test_devices_file_from_env(self):
        import os

        os.environ["DEVICES_FILE"] = "/custom/path/devices.jsonl"
        try:
            from core.config import Settings

            s = Settings.from_env()
            assert s.devices_file == "/custom/path/devices.jsonl"
        finally:
            del os.environ["DEVICES_FILE"]

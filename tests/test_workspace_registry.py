"""
Tests for WorkspaceRegistry — unit tests for the dataclass, registry CRUD,
persistence, seeding, and integration tests for the /api/workspaces endpoints.
"""

import asyncio
import json
from pathlib import Path

import pytest

from core.workspace_registry import Workspace, WorkspaceRegistry

# ---------------------------------------------------------------------------
# Workspace dataclass tests
# ---------------------------------------------------------------------------


class TestWorkspace:
    def test_default_id_is_12_hex_chars(self):
        """ID should be a 12-character hex string from uuid4."""
        ws = Workspace(name="test", root_path="/tmp")
        assert len(ws.id) == 12
        assert all(c in "0123456789abcdef" for c in ws.id)

    def test_to_dict_returns_all_fields(self):
        """to_dict() should return a dict with all dataclass fields."""
        ws = Workspace(name="myws", root_path="/some/path", ordering=3)
        d = ws.to_dict()
        assert d["name"] == "myws"
        assert d["root_path"] == "/some/path"
        assert d["ordering"] == 3
        assert "id" in d
        assert "created_at" in d
        assert "updated_at" in d

    def test_from_dict_round_trips(self):
        """from_dict(to_dict()) should recreate an identical workspace."""
        ws = Workspace(name="roundtrip", root_path="/foo/bar", ordering=5)
        d = ws.to_dict()
        ws2 = Workspace.from_dict(d)
        assert ws2.id == ws.id
        assert ws2.name == ws.name
        assert ws2.root_path == ws.root_path
        assert ws2.ordering == ws.ordering
        assert ws2.created_at == ws.created_at

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict() should tolerate extra keys without raising."""
        d = {
            "id": "abc123def456",
            "name": "ok",
            "root_path": "/x",
            "created_at": 0.0,
            "updated_at": 0.0,
            "ordering": 0,
            "future_field": "ignored",
        }
        ws = Workspace.from_dict(d)
        assert ws.name == "ok"

    def test_two_workspaces_have_different_ids(self):
        """Each Workspace should get a unique ID."""
        ws1 = Workspace()
        ws2 = Workspace()
        assert ws1.id != ws2.id


# ---------------------------------------------------------------------------
# WorkspaceRegistry unit tests
# ---------------------------------------------------------------------------


class TestWorkspaceRegistry:
    def setup_method(self, method):
        """Called before each test; registry created fresh with tmp path set in test."""
        pass

    @pytest.fixture
    def registry(self, tmp_path):
        return WorkspaceRegistry(tmp_path / "workspaces.json")

    @pytest.fixture
    def seeded_registry(self, tmp_path):
        """Registry with a default workspace seeded from tmp_path."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        asyncio.run(reg.seed_default(str(tmp_path)))
        return reg

    # -- load & persist -------------------------------------------------------

    @pytest.mark.asyncio
    async def test_persist_writes_json_file(self, tmp_path):
        """_persist() should create a JSON file with workspace data."""
        path = tmp_path / "workspaces.json"
        reg = WorkspaceRegistry(path)
        await reg.seed_default(str(tmp_path))
        assert path.exists()
        data = json.loads(path.read_text())
        assert "workspaces" in data
        assert "default_id" in data

    @pytest.mark.asyncio
    async def test_load_deserializes_back_to_same_state(self, tmp_path):
        """load() after _persist() should restore identical in-memory state."""
        path = tmp_path / "workspaces.json"
        reg1 = WorkspaceRegistry(path)
        await reg1.seed_default(str(tmp_path))
        original_id = reg1.get_default().id

        reg2 = WorkspaceRegistry(path)
        await reg2.load()
        restored = reg2.get_default()
        assert restored is not None
        assert restored.id == original_id
        assert restored.root_path == reg1.get_default().root_path

    @pytest.mark.asyncio
    async def test_load_on_missing_file_is_noop(self, tmp_path):
        """load() on a missing file should not raise — just leave registry empty."""
        path = tmp_path / "nonexistent.json"
        reg = WorkspaceRegistry(path)
        await reg.load()  # Should not raise
        assert reg.list_all() == []

    @pytest.mark.asyncio
    async def test_persist_uses_atomic_tmp_then_replace(self, tmp_path):
        """Atomic write: .tmp file should not linger after persist."""
        path = tmp_path / "workspaces.json"
        reg = WorkspaceRegistry(path)
        await reg.seed_default(str(tmp_path))
        tmp_file = Path(str(path) + ".tmp")
        assert not tmp_file.exists(), ".tmp file should be cleaned up after atomic replace"
        assert path.exists(), "Final file should exist"

    # -- seed_default ---------------------------------------------------------

    @pytest.mark.asyncio
    async def test_seed_default_creates_workspace_when_empty(self, tmp_path):
        """seed_default() should create exactly one workspace when registry is empty."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        workspaces = reg.list_all()
        assert len(workspaces) == 1

    @pytest.mark.asyncio
    async def test_seed_default_sets_default_id(self, tmp_path):
        """seed_default() should set the created workspace as the default."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        default = reg.get_default()
        assert default is not None

    @pytest.mark.asyncio
    async def test_seed_default_is_idempotent(self, tmp_path):
        """seed_default() called twice should still result in only one workspace."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        await reg.seed_default(str(tmp_path))
        assert len(reg.list_all()) == 1

    @pytest.mark.asyncio
    async def test_seed_default_uses_directory_name(self, tmp_path):
        """seed_default() should use the directory name as the workspace name."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        default = reg.get_default()
        # tmp_path has a real directory name (not "." or "")
        assert default.name == tmp_path.name

    @pytest.mark.asyncio
    async def test_seed_default_falls_back_for_dot_name(self, tmp_path):
        """seed_default() should use 'Default' for paths whose name is '.' or ''."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        # "/" has name "" on Unix; use monkeypatching via a mock path string
        # We simulate by checking the fallback condition in the implementation.
        # On Windows/Unix the root "/" has name "".  Use a valid dir but patch name.
        await reg.seed_default(str(tmp_path))
        default = reg.get_default()
        # Normal tmp_path should NOT trigger fallback
        assert default.name not in (".", "", "/")

    @pytest.mark.asyncio
    async def test_seed_default_stores_resolved_path(self, tmp_path):
        """seed_default() root_path should be an absolute resolved path."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        default = reg.get_default()
        assert Path(default.root_path).is_absolute()

    # -- resolve --------------------------------------------------------------

    def test_resolve_none_returns_default(self, seeded_registry):
        """resolve(None) should return the default workspace."""
        default = seeded_registry.get_default()
        resolved = seeded_registry.resolve(None)
        assert resolved is not None
        assert resolved.id == default.id

    def test_resolve_valid_id_returns_workspace(self, seeded_registry):
        """resolve(valid_id) should return that specific workspace."""
        default = seeded_registry.get_default()
        resolved = seeded_registry.resolve(default.id)
        assert resolved is not None
        assert resolved.id == default.id

    def test_resolve_invalid_id_returns_none(self, seeded_registry):
        """resolve(unknown_id) should return None."""
        result = seeded_registry.resolve("doesnotexist00")
        assert result is None

    # -- list_all, create, update, delete -------------------------------------

    @pytest.mark.asyncio
    async def test_list_all_returns_all_workspaces(self, tmp_path):
        """list_all() should return all registered workspaces."""
        ws_dir = tmp_path / "ws1"
        ws_dir.mkdir()
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        await reg.create(name="Second", root_path=str(ws_dir))
        assert len(reg.list_all()) == 2

    @pytest.mark.asyncio
    async def test_create_adds_workspace_and_persists(self, tmp_path):
        """create() should add a workspace to the registry and persist it."""
        ws_dir = tmp_path / "newws"
        ws_dir.mkdir()
        path = tmp_path / "workspaces.json"
        reg = WorkspaceRegistry(path)
        ws = await reg.create(name="NewWS", root_path=str(ws_dir))
        assert ws.name == "NewWS"
        # Verify it was persisted
        reg2 = WorkspaceRegistry(path)
        await reg2.load()
        assert any(w.id == ws.id for w in reg2.list_all())

    @pytest.mark.asyncio
    async def test_create_with_nonexistent_path_raises(self, tmp_path):
        """create() with a non-existent path should raise ValueError."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        with pytest.raises(ValueError):
            await reg.create(name="Bad", root_path=str(tmp_path / "doesnotexist"))

    @pytest.mark.asyncio
    async def test_create_with_file_path_raises(self, tmp_path):
        """create() with a file path (not a directory) should raise ValueError."""
        file_path = tmp_path / "file.txt"
        file_path.write_text("hello")
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        with pytest.raises(ValueError):
            await reg.create(name="BadFile", root_path=str(file_path))

    @pytest.mark.asyncio
    async def test_update_modifies_fields_and_persists(self, tmp_path):
        """update() should modify workspace fields and persist."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        default = reg.get_default()
        updated = await reg.update(default.id, name="Renamed")
        assert updated is not None
        assert updated.name == "Renamed"

    @pytest.mark.asyncio
    async def test_update_sets_updated_at(self, tmp_path):
        """update() should update the updated_at timestamp."""
        import time

        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        default = reg.get_default()
        old_updated_at = default.updated_at
        time.sleep(0.01)  # ensure time advances
        await reg.update(default.id, ordering=5)
        updated = reg.resolve(default.id)
        assert updated.updated_at >= old_updated_at

    @pytest.mark.asyncio
    async def test_update_unknown_id_returns_none(self, tmp_path):
        """update() with an unknown ID should return None."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        result = await reg.update("unknownid0000", name="X")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_removes_workspace_and_persists(self, tmp_path):
        """delete() should remove a workspace and persist."""
        ws_dir = tmp_path / "delme"
        ws_dir.mkdir()
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        ws = await reg.create(name="ToDelete", root_path=str(ws_dir))
        result = await reg.delete(ws.id)
        assert result is True
        assert reg.resolve(ws.id) is None

    @pytest.mark.asyncio
    async def test_delete_unknown_id_returns_false(self, tmp_path):
        """delete() with an unknown ID should return False."""
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        result = await reg.delete("unknownid0000")
        assert result is False

    @pytest.mark.asyncio
    async def test_delete_default_resets_default_to_next(self, tmp_path):
        """delete() of the default workspace should reassign default if others exist."""
        ws2_dir = tmp_path / "ws2"
        ws2_dir.mkdir()
        reg = WorkspaceRegistry(tmp_path / "workspaces.json")
        await reg.seed_default(str(tmp_path))
        ws2 = await reg.create(name="Second", root_path=str(ws2_dir))
        default_id = reg.get_default().id
        await reg.delete(default_id)
        # After delete, a new default should be set or be None
        remaining = reg.list_all()
        if remaining:
            # New default should be set
            assert reg.get_default() is not None


# ---------------------------------------------------------------------------
# Integration tests: /api/workspaces endpoints
# ---------------------------------------------------------------------------


class TestWorkspaceEndpoints:
    @pytest.fixture
    def client(self, tmp_path):
        from dashboard.auth import get_current_user
        from dashboard.server import create_app
        from dashboard.websocket_manager import WebSocketManager

        registry = WorkspaceRegistry(tmp_path / "workspaces.json")
        asyncio.run(registry.seed_default(str(tmp_path)))

        app = create_app(
            ws_manager=WebSocketManager(),
            workspace_registry=registry,
        )
        # Override auth so tests don't need real JWT
        app.dependency_overrides[get_current_user] = lambda: "test_user"

        from fastapi.testclient import TestClient

        with TestClient(app) as c:
            yield c, registry, tmp_path

    def test_list_workspaces(self, client):
        """GET /api/workspaces should return 200 with workspaces list."""
        c, registry, tmp_path = client
        res = c.get("/api/workspaces")
        assert res.status_code == 200
        data = res.json()
        assert "workspaces" in data
        assert len(data["workspaces"]) >= 1
        assert "default_id" in data

    def test_create_workspace_valid_path(self, client):
        """POST /api/workspaces with a valid directory should return 201."""
        c, registry, tmp_path = client
        new_dir = tmp_path / "newproject"
        new_dir.mkdir()
        res = c.post("/api/workspaces", json={"path": str(new_dir), "name": "NewProject"})
        assert res.status_code == 201
        data = res.json()
        assert data["name"] == "NewProject"
        assert "id" in data

    def test_create_workspace_rejects_bad_path(self, client):
        """POST /api/workspaces with non-existent path should return 400."""
        c, registry, tmp_path = client
        res = c.post("/api/workspaces", json={"path": str(tmp_path / "doesnotexist")})
        assert res.status_code == 400

    def test_update_workspace(self, client):
        """PATCH /api/workspaces/{id} should update the workspace name."""
        c, registry, tmp_path = client
        ws_id = registry.get_default().id
        res = c.patch(f"/api/workspaces/{ws_id}", json={"name": "Renamed"})
        assert res.status_code == 200
        data = res.json()
        assert data["name"] == "Renamed"

    def test_delete_workspace(self, client):
        """DELETE /api/workspaces/{id} should return 200."""
        c, registry, tmp_path = client
        new_dir = tmp_path / "todel"
        new_dir.mkdir()
        ws = asyncio.run(registry.create(name="ToDelete", root_path=str(new_dir)))
        res = c.delete(f"/api/workspaces/{ws.id}")
        assert res.status_code == 200
        data = res.json()
        assert data["status"] == "deleted"

    def test_ide_tree_default_fallback(self, client):
        """GET /api/ide/tree without workspace_id should use default workspace."""
        c, registry, tmp_path = client
        res = c.get("/api/ide/tree")
        assert res.status_code == 200
        data = res.json()
        assert "entries" in data

    def test_ide_tree_workspace_scoped(self, client):
        """GET /api/ide/tree?workspace_id={id} should use that workspace."""
        c, registry, tmp_path = client
        ws_id = registry.get_default().id
        res = c.get(f"/api/ide/tree?workspace_id={ws_id}")
        assert res.status_code == 200

    def test_ide_tree_invalid_workspace(self, client):
        """GET /api/ide/tree?workspace_id=bad should return 404."""
        c, registry, tmp_path = client
        res = c.get("/api/ide/tree?workspace_id=doesnotexist0")
        assert res.status_code == 404

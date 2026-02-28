"""Tests for core.state_manager — ProjectState and StateManager."""

import json

import pytest

from core.state_manager import _MAX_ACCUMULATED_CONTEXT_CHARS, ProjectState, StateManager


class TestProjectState:
    """Test ProjectState dataclass."""

    def test_to_dict_from_dict_roundtrip(self):
        state = ProjectState(
            project_id="proj1",
            current_phase="phase-2",
            current_wave=1,
            completed_task_ids=["t1", "t2"],
            pending_task_ids=["t3"],
            key_decisions=["[10:00] Use PostgreSQL"],
        )
        data = state.to_dict()
        restored = ProjectState.from_dict(data)
        assert restored.project_id == "proj1"
        assert restored.current_phase == "phase-2"
        assert restored.current_wave == 1
        assert restored.completed_task_ids == ["t1", "t2"]
        assert restored.pending_task_ids == ["t3"]
        assert restored.key_decisions == ["[10:00] Use PostgreSQL"]

    def test_to_markdown_contains_sections(self):
        state = ProjectState(
            project_id="proj42",
            current_phase="implementation",
            completed_task_ids=["t1"],
            pending_task_ids=["t2", "t3"],
            failed_task_ids=["t4"],
            key_decisions=["[09:30] Use REST API"],
            accumulated_context="Some accumulated context here",
        )
        md = state.to_markdown()
        assert "# Project State: proj42" in md
        assert "## Current Phase" in md
        assert "implementation" in md
        assert "[x] t1" in md
        assert "[ ] t2" in md
        assert "[!] t4" in md
        assert "Use REST API" in md
        assert "## Accumulated Context" in md

    def test_from_dict_ignores_unknown_fields(self):
        data = {"project_id": "p1", "unknown_key": "value"}
        state = ProjectState.from_dict(data)
        assert state.project_id == "p1"


class TestStateManager:
    """Test StateManager persistence and operations."""

    @pytest.mark.asyncio
    async def test_save_and_load(self, tmp_path):
        mgr = StateManager(tmp_path)
        state = ProjectState(
            project_id="proj1",
            current_phase="planning",
            pending_task_ids=["t1", "t2"],
        )
        await mgr.save_state(state)

        loaded = await mgr.load_state("proj1")
        assert loaded is not None
        assert loaded.project_id == "proj1"
        assert loaded.current_phase == "planning"
        assert loaded.pending_task_ids == ["t1", "t2"]

    @pytest.mark.asyncio
    async def test_load_nonexistent_returns_none(self, tmp_path):
        mgr = StateManager(tmp_path)
        result = await mgr.load_state("nonexistent")
        assert result is None

    @pytest.mark.asyncio
    async def test_update_task_completion(self, tmp_path):
        mgr = StateManager(tmp_path)
        # Create initial state with pending tasks
        state = ProjectState(
            project_id="proj1",
            pending_task_ids=["t1", "t2", "t3"],
        )
        await mgr.save_state(state)

        # Complete t2
        await mgr.update_task_completion("proj1", "t2")

        loaded = await mgr.load_state("proj1")
        assert "t2" not in loaded.pending_task_ids
        assert "t2" in loaded.completed_task_ids
        assert "t1" in loaded.pending_task_ids

    @pytest.mark.asyncio
    async def test_update_task_completion_creates_state_if_missing(self, tmp_path):
        mgr = StateManager(tmp_path)
        await mgr.update_task_completion("newproj", "t1")

        loaded = await mgr.load_state("newproj")
        assert loaded is not None
        assert "t1" in loaded.completed_task_ids

    @pytest.mark.asyncio
    async def test_update_task_failure(self, tmp_path):
        mgr = StateManager(tmp_path)
        state = ProjectState(
            project_id="proj1",
            pending_task_ids=["t1"],
        )
        await mgr.save_state(state)

        await mgr.update_task_failure("proj1", "t1")

        loaded = await mgr.load_state("proj1")
        assert "t1" not in loaded.pending_task_ids
        assert "t1" in loaded.failed_task_ids

    @pytest.mark.asyncio
    async def test_record_decision(self, tmp_path):
        mgr = StateManager(tmp_path)
        state = ProjectState(project_id="proj1")
        await mgr.save_state(state)

        await mgr.record_decision("proj1", "Use PostgreSQL for persistence")

        loaded = await mgr.load_state("proj1")
        assert len(loaded.key_decisions) == 1
        assert "Use PostgreSQL" in loaded.key_decisions[0]

    @pytest.mark.asyncio
    async def test_set_phase(self, tmp_path):
        mgr = StateManager(tmp_path)
        state = ProjectState(project_id="proj1")
        await mgr.save_state(state)

        await mgr.set_phase("proj1", "implementation", wave=2)

        loaded = await mgr.load_state("proj1")
        assert loaded.current_phase == "implementation"
        assert loaded.current_wave == 2

    @pytest.mark.asyncio
    async def test_accumulated_context_cap(self, tmp_path):
        mgr = StateManager(tmp_path)
        # Create state with accumulated_context exceeding the cap
        huge_context = "x" * (_MAX_ACCUMULATED_CONTEXT_CHARS + 5000)
        state = ProjectState(
            project_id="proj1",
            accumulated_context=huge_context,
        )
        await mgr.save_state(state)

        loaded = await mgr.load_state("proj1")
        assert len(loaded.accumulated_context) <= _MAX_ACCUMULATED_CONTEXT_CHARS

    @pytest.mark.asyncio
    async def test_save_creates_files(self, tmp_path):
        mgr = StateManager(tmp_path)
        state = ProjectState(project_id="proj1")
        await mgr.save_state(state)

        project_dir = tmp_path / "projects" / "proj1"
        assert (project_dir / "STATE.md").exists()
        assert (project_dir / "state.json").exists()

        # Verify JSON is valid
        with open(project_dir / "state.json") as f:
            data = json.load(f)
        assert data["project_id"] == "proj1"

    @pytest.mark.asyncio
    async def test_no_duplicate_completed_ids(self, tmp_path):
        mgr = StateManager(tmp_path)
        state = ProjectState(project_id="proj1")
        await mgr.save_state(state)

        await mgr.update_task_completion("proj1", "t1")
        await mgr.update_task_completion("proj1", "t1")  # duplicate

        loaded = await mgr.load_state("proj1")
        assert loaded.completed_task_ids.count("t1") == 1

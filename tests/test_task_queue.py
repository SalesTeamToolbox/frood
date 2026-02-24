"""Tests for core/task_queue.py — Task dataclass and TaskStatus/TaskType enums."""

import dataclasses

from core.task_queue import Task, TaskStatus, TaskType


class TestTaskDataclass:
    """Test the Task dataclass structure, fields, and serialization."""

    def test_no_duplicate_fields(self):
        """Task dataclass must not have duplicate field definitions."""
        field_names = [f.name for f in dataclasses.fields(Task)]
        assert len(field_names) == len(set(field_names)), (
            f"Duplicate field(s) in Task: {[n for n in field_names if field_names.count(n) > 1]}"
        )

    def test_project_id_field_exists_once(self):
        """project_id appears exactly once in Task fields."""
        field_names = [f.name for f in dataclasses.fields(Task)]
        assert field_names.count("project_id") == 1

    def test_required_fields_present(self):
        """Task has all required field names."""
        field_names = {f.name for f in dataclasses.fields(Task)}
        for required in [
            "title",
            "description",
            "task_type",
            "status",
            "id",
            "project_id",
            "project_spec_path",
        ]:
            assert required in field_names, f"Missing field: {required}"

    def test_defaults(self):
        """Task can be created with only required args and has sensible defaults."""
        task = Task(title="Test", description="Do something")
        assert task.title == "Test"
        assert task.description == "Do something"
        assert task.status == TaskStatus.PENDING
        assert task.task_type == TaskType.CODING
        assert task.project_id == ""
        assert task.project_spec_path == ""
        assert task.priority == 0
        assert isinstance(task.id, str) and len(task.id) > 0

    def test_project_id_settable(self):
        """project_id field can be set and retrieved."""
        task = Task(title="T", description="D", project_id="proj-123")
        assert task.project_id == "proj-123"


class TestTaskSerialization:
    """Test to_dict() / from_dict() roundtrip."""

    def test_to_dict_returns_dict(self):
        task = Task(title="Test", description="desc")
        d = task.to_dict()
        assert isinstance(d, dict)
        assert d["title"] == "Test"
        assert d["description"] == "desc"

    def test_to_dict_status_is_string(self):
        task = Task(title="T", description="D", status=TaskStatus.DONE)
        d = task.to_dict()
        assert d["status"] == "done"

    def test_to_dict_task_type_is_string(self):
        task = Task(title="T", description="D", task_type=TaskType.RESEARCH)
        d = task.to_dict()
        assert d["task_type"] == "research"

    def test_roundtrip_preserves_all_fields(self):
        """from_dict(to_dict(task)) produces an identical Task."""
        task = Task(
            title="Roundtrip",
            description="Check all fields survive",
            task_type=TaskType.DEBUGGING,
            status=TaskStatus.RUNNING,
            project_id="proj-999",
            project_spec_path="/path/to/spec.md",
            priority=1,
            tags=["backend", "api"],
        )
        d = task.to_dict()
        restored = Task.from_dict(d)

        assert restored.title == task.title
        assert restored.description == task.description
        assert restored.task_type == task.task_type
        assert restored.status == task.status
        assert restored.project_id == task.project_id
        assert restored.project_spec_path == task.project_spec_path
        assert restored.priority == task.priority
        assert restored.tags == task.tags
        assert restored.id == task.id

    def test_project_id_preserved_in_roundtrip(self):
        """project_id specifically survives serialization (regression for duplicate field bug)."""
        task = Task(title="T", description="D", project_id="interview-abc")
        d = task.to_dict()
        assert d["project_id"] == "interview-abc"
        restored = Task.from_dict(d)
        assert restored.project_id == "interview-abc"

    def test_from_dict_ignores_unknown_fields(self):
        """from_dict() skips unknown keys gracefully."""
        d = {
            "title": "T",
            "description": "D",
            "status": "pending",
            "task_type": "coding",
            "unknown_future_field": "ignored",
        }
        task = Task.from_dict(d)
        assert task.title == "T"

    def test_to_dict_has_project_id_key(self):
        """to_dict() always includes project_id key."""
        task = Task(title="T", description="D")
        d = task.to_dict()
        assert "project_id" in d


class TestTaskMethods:
    """Test Task instance methods."""

    def test_add_comment(self):
        task = Task(title="T", description="D")
        task.add_comment("alice", "Looks good")
        assert len(task.comments) == 1
        assert task.comments[0]["author"] == "alice"
        assert task.comments[0]["text"] == "Looks good"
        assert "timestamp" in task.comments[0]

    def test_block_and_unblock(self):
        task = Task(title="T", description="D")
        task.block("waiting for dependency")
        assert task.status == TaskStatus.BLOCKED
        assert task.blocked_reason == "waiting for dependency"

        task.unblock()
        assert task.status == TaskStatus.PENDING
        assert task.blocked_reason == ""

    def test_from_dict_default_status_on_missing(self):
        """from_dict() sets PENDING when status key is missing."""
        task = Task.from_dict({"title": "T", "description": "D", "task_type": "coding"})
        assert task.status == TaskStatus.PENDING

    def test_archive(self):
        task = Task(title="T", description="D")
        task.archive()
        assert task.status == TaskStatus.ARCHIVED


class TestTaskTypeEnum:
    """Test TaskType enum values are stable."""

    def test_coding_value(self):
        assert TaskType.CODING.value == "coding"

    def test_research_value(self):
        assert TaskType.RESEARCH.value == "research"

    def test_debugging_value(self):
        assert TaskType.DEBUGGING.value == "debugging"


class TestTaskStatusEnum:
    """Test TaskStatus enum values are stable."""

    def test_pending_value(self):
        assert TaskStatus.PENDING.value == "pending"

    def test_done_value(self):
        assert TaskStatus.DONE.value == "done"

    def test_failed_value(self):
        assert TaskStatus.FAILED.value == "failed"

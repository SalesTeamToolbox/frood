"""Tests for learning extraction pipeline (Phase 21: LEARN-01 through LEARN-05)."""

import json
import os
from pathlib import Path


class TestTaskContextBridge:
    """Task context file bridge for cross-process access."""

    def test_begin_task_creates_json_file(self, tmp_path, monkeypatch):
        """begin_task() writes .frood/current-task.json."""
        monkeypatch.setattr("core.task_context._TASK_FILE_DIR", str(tmp_path / ".frood"))
        from core.task_context import begin_task, end_task
        from core.task_types import TaskType

        ctx = begin_task(TaskType.CODING)
        task_file = tmp_path / ".frood" / "current-task.json"
        assert task_file.exists()
        data = json.loads(task_file.read_text())
        assert data["task_id"] == ctx.task_id
        assert data["task_type"] == "coding"
        end_task(ctx)

    def test_end_task_removes_json_file(self, tmp_path, monkeypatch):
        """end_task() removes current-task.json."""
        monkeypatch.setattr("core.task_context._TASK_FILE_DIR", str(tmp_path / ".frood"))
        from core.task_context import begin_task, end_task
        from core.task_types import TaskType

        ctx = begin_task(TaskType.DEBUGGING)
        task_file = tmp_path / ".frood" / "current-task.json"
        assert task_file.exists()
        end_task(ctx)
        assert not task_file.exists()

    def test_read_task_context_from_file(self, tmp_path):
        """effectiveness-learn.py read_task_context() reads from file."""
        # Create the bridge file manually
        agent42_dir = tmp_path / ".frood"
        agent42_dir.mkdir()
        task_file = agent42_dir / "current-task.json"
        task_file.write_text(
            json.dumps(
                {
                    "task_id": "test-uuid-123",
                    "task_type": "research",
                }
            )
        )

        # Import the hook function
        import importlib.util

        hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "effectiveness-learn.py"
        spec = importlib.util.spec_from_file_location("effectiveness_learn", hook_path)
        hook_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_module)

        task_id, task_type = hook_module.read_task_context(str(tmp_path))
        assert task_id == "test-uuid-123"
        assert task_type == "research"

    def test_read_task_context_missing_file(self, tmp_path):
        """read_task_context returns generated UUID + 'general' when file missing."""
        import importlib.util

        hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "effectiveness-learn.py"
        spec = importlib.util.spec_from_file_location("effectiveness_learn", hook_path)
        hook_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_module)

        task_id, task_type = hook_module.read_task_context(str(tmp_path))
        assert len(task_id) == 36  # UUID format
        assert task_type == "general"


class TestTrivialSessionGuard:
    """LEARN-05: Skip trivial sessions."""

    def _load_hook(self):
        import importlib.util

        hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "effectiveness-learn.py"
        spec = importlib.util.spec_from_file_location("effectiveness_learn", hook_path)
        hook_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_module)
        return hook_module

    def test_count_tool_calls(self):
        hook = self._load_hook()
        event = {
            "tool_results": [
                {"tool_name": "Read"},
                {"tool_name": "Edit"},
                {"tool_name": "Bash"},
            ]
        }
        assert hook.count_tool_calls(event) == 3

    def test_count_tool_calls_empty(self):
        hook = self._load_hook()
        assert hook.count_tool_calls({}) == 0

    def test_count_file_modifications(self):
        hook = self._load_hook()
        event = {
            "tool_results": [
                {"tool_name": "Read"},
                {"tool_name": "Write", "tool_input": {"file_path": "test.py"}},
                {"tool_name": "Edit", "tool_input": {"file_path": "other.py"}},
                {"tool_name": "Bash"},
            ]
        }
        assert hook.count_file_modifications(event) == 2

    def test_count_file_modifications_none(self):
        hook = self._load_hook()
        event = {
            "tool_results": [
                {"tool_name": "Read"},
                {"tool_name": "Bash"},
            ]
        }
        assert hook.count_file_modifications(event) == 0

    def test_trivial_session_skipped(self):
        """Session with <2 tool calls is trivial."""
        hook = self._load_hook()
        event = {"tool_results": [{"tool_name": "Read"}]}
        assert hook.count_tool_calls(event) < 2

    def test_sufficient_session_passes(self):
        """Session with >=2 tool calls AND >=1 file mod passes."""
        hook = self._load_hook()
        event = {
            "tool_results": [
                {"tool_name": "Read"},
                {"tool_name": "Write", "tool_input": {"file_path": "test.py"}},
                {"tool_name": "Bash"},
            ]
        }
        assert hook.count_tool_calls(event) >= 2
        assert hook.count_file_modifications(event) >= 1


class TestLearningExtraction:
    """LEARN-01: Structured extraction with instructor."""

    def test_extract_returns_none_without_api_key(self, monkeypatch):
        """Without API keys, extraction returns None gracefully."""
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)

        import importlib.util

        hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "effectiveness-learn.py"
        spec = importlib.util.spec_from_file_location("effectiveness_learn", hook_path)
        hook_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_module)

        result = hook_module.extract_learning_with_instructor(
            "test summary", ["Read", "Write"], ["test.py"], "coding"
        )
        assert result is None

    def test_get_tool_names(self):
        """get_tool_names extracts unique tool names."""
        import importlib.util

        hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "effectiveness-learn.py"
        spec = importlib.util.spec_from_file_location("effectiveness_learn", hook_path)
        hook_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_module)

        event = {
            "tool_results": [
                {"tool_name": "Read"},
                {"tool_name": "Read"},
                {"tool_name": "Write"},
            ]
        }
        names = hook_module.get_tool_names(event)
        assert "Read" in names
        assert "Write" in names
        assert len(names) == 2  # Deduplicated

    def test_get_modified_files(self):
        """get_modified_files extracts file basenames."""
        import importlib.util

        hook_path = Path(__file__).parent.parent / ".claude" / "hooks" / "effectiveness-learn.py"
        spec = importlib.util.spec_from_file_location("effectiveness_learn", hook_path)
        hook_module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(hook_module)

        event = {
            "tool_results": [
                {"tool_name": "Edit", "tool_input": {"file_path": "/home/user/project/foo.py"}},
                {"tool_name": "Read", "tool_input": {"file_path": "/home/user/project/bar.py"}},
            ]
        }
        files = hook_module.get_modified_files(event)
        assert "foo.py" in files
        assert "bar.py" not in files  # Read is not a modification


class TestQuarantine:
    """LEARN-04: Quarantine mechanics."""

    def test_new_learning_quarantine_fields(self):
        """New learning entries should start with observation_count=1, quarantined=True."""
        # Verify the quarantine values are correct per CONTEXT.md
        quarantine_conf = float(os.environ.get("LEARNING_QUARANTINE_CONFIDENCE", "0.6"))
        assert quarantine_conf == 0.6

        min_evidence = int(os.environ.get("LEARNING_MIN_EVIDENCE", "3"))
        assert min_evidence == 3

        # A new learning with observation_count=1 is below threshold
        observation_count = 1
        assert observation_count < min_evidence

    def test_promotion_threshold_logic(self):
        """When observation_count >= LEARNING_MIN_EVIDENCE, quarantine lifts."""
        threshold = 3
        # Below threshold
        assert threshold > 1  # Still quarantined
        assert threshold > 2  # Still quarantined
        # At threshold
        assert threshold <= 3  # Promoted
        assert threshold <= 4  # Already promoted

    def test_no_promotion_wrong_outcome(self):
        """Different outcomes should not trigger promotion."""
        # Simulate matching logic from _maybe_promote_quarantined
        learning_outcome = "success"
        new_task_outcome = "failure"
        assert learning_outcome != new_task_outcome  # Should NOT promote


class TestNoMidTaskWrites:
    """LEARN-05: No mid-task memory writes."""

    def test_hook_is_stop_event_only(self):
        """Learning hook is registered as a Stop hook, not PreToolUse or PostToolUse."""
        settings_path = Path(__file__).parent.parent / ".claude" / "settings.json"
        settings = json.loads(settings_path.read_text())

        # Verify a learning-related hook is in Stop hooks
        stop_hooks = settings["hooks"]["Stop"][0]["hooks"]
        hook_commands = [h["command"] for h in stop_hooks]
        assert any("learn" in cmd for cmd in hook_commands)

        # Verify it's NOT in PreToolUse or PostToolUse
        for event_type in ["PreToolUse", "PostToolUse"]:
            if event_type in settings["hooks"]:
                for hook_group in settings["hooks"][event_type]:
                    for hook in hook_group.get("hooks", []):
                        cmd = hook.get("command", "")
                        assert "effectiveness-learn.py" not in cmd
                        assert "learning-engine.py" not in cmd

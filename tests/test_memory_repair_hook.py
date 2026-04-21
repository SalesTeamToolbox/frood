"""Tests for the memory-repair hook shim.

Exercises the stop-every-N counter gate (in-process, via runpy) and verifies
the hook spawns a detached subprocess on PostCompact.
"""

from __future__ import annotations

import importlib.util
import io
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

HOOK_PATH = Path(__file__).resolve().parent.parent / ".claude" / "hooks" / "memory-repair.py"


def _load_hook_module(status_dir: Path):
    """Load the hook as a module with STATUS_FILE redirected under status_dir."""
    spec = importlib.util.spec_from_file_location("memory_repair_hook", str(HOOK_PATH))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    mod.STATUS_FILE = status_dir / ".frood" / "memory-repair-status.json"
    return mod


def _run_hook(mod, event: dict) -> int:
    """Run the hook's main() with event JSON on stdin; return exit code."""
    with patch("sys.stdin", io.StringIO(json.dumps(event))):
        with patch.object(subprocess, "Popen") as popen:
            try:
                mod.main()
                code = 0
            except SystemExit as exc:
                code = exc.code or 0
    return code, popen


class TestShouldFire:
    def test_post_compact_always_fires(self, tmp_path):
        mod = _load_hook_module(tmp_path)
        assert mod._should_fire("PostCompact") is True

    def test_stop_fires_only_every_nth(self, tmp_path, monkeypatch):
        mod = _load_hook_module(tmp_path)
        monkeypatch.setenv("MEMORY_REPAIR_STOP_TRIGGER_COUNT", "3")
        # Counter starts at 0
        assert mod._should_fire("Stop") is False  # 1
        assert mod._should_fire("Stop") is False  # 2
        assert mod._should_fire("Stop") is True  # 3 → fires + resets
        assert mod._should_fire("Stop") is False  # 1 again

    def test_unknown_event_does_not_fire(self, tmp_path):
        mod = _load_hook_module(tmp_path)
        assert mod._should_fire("SessionStart") is False


class TestHookMain:
    def test_post_compact_spawns_worker(self, tmp_path, monkeypatch):
        mod = _load_hook_module(tmp_path)
        monkeypatch.setenv("MEMORY_REPAIR_ENABLED", "true")
        code, popen = _run_hook(mod, {"hook_event_name": "PostCompact"})
        assert code == 0
        popen.assert_called_once()
        # argv should end with the hook event name
        args, _ = popen.call_args
        cmd = args[0]
        assert cmd[-1] == "PostCompact"
        assert cmd[-2].endswith("memory-repair-worker.py")

    def test_disabled_flag_short_circuits(self, tmp_path, monkeypatch):
        mod = _load_hook_module(tmp_path)
        monkeypatch.setenv("MEMORY_REPAIR_ENABLED", "false")
        code, popen = _run_hook(mod, {"hook_event_name": "PostCompact"})
        assert code == 0
        popen.assert_not_called()

    def test_bad_json_exits_zero(self, tmp_path):
        mod = _load_hook_module(tmp_path)
        with patch("sys.stdin", io.StringIO("not json")):
            with patch.object(subprocess, "Popen") as popen:
                try:
                    mod.main()
                    code = 0
                except SystemExit as exc:
                    code = exc.code or 0
        assert code == 0
        popen.assert_not_called()

    def test_stop_counter_persists_across_calls(self, tmp_path, monkeypatch):
        mod = _load_hook_module(tmp_path)
        monkeypatch.setenv("MEMORY_REPAIR_STOP_TRIGGER_COUNT", "2")
        monkeypatch.setenv("MEMORY_REPAIR_ENABLED", "true")
        # First Stop: no spawn
        _, popen1 = _run_hook(mod, {"hook_event_name": "Stop"})
        popen1.assert_not_called()
        # Second Stop: spawn (counter hit 2)
        _, popen2 = _run_hook(mod, {"hook_event_name": "Stop"})
        popen2.assert_called_once()
        # Third Stop: no spawn (counter reset)
        _, popen3 = _run_hook(mod, {"hook_event_name": "Stop"})
        popen3.assert_not_called()

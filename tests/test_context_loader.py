"""Tests for .claude/hooks/context-loader.py — GSD work type detection and nudge."""

import importlib.util
import os

# Load context-loader.py as a module since it's not in a package
_spec = importlib.util.spec_from_file_location(
    "context_loader",
    os.path.join(os.path.dirname(__file__), "..", ".claude", "hooks", "context-loader.py"),
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

detect_work_types = _mod.detect_work_types
_emit_gsd_nudge = _mod._emit_gsd_nudge


class TestGsdWorkTypeDetection:
    """Tests for GSD keyword detection in detect_work_types."""

    def test_build_keyword_detected(self):
        result = detect_work_types("build a Flask app with user authentication")
        assert "gsd" in result

    def test_implement_keyword_detected(self):
        result = detect_work_types("implement user auth with JWT tokens")
        assert "gsd" in result

    def test_refactor_keyword_detected(self):
        result = detect_work_types("refactor the dashboard components")
        assert "gsd" in result

    def test_scaffold_keyword_detected(self):
        result = detect_work_types("scaffold a new React app")
        assert "gsd" in result

    def test_plan_keyword_detected(self):
        result = detect_work_types("plan the roadmap for version 2")
        assert "gsd" in result

    def test_milestone_keyword_detected(self):
        result = detect_work_types("create a milestone for the release")
        assert "gsd" in result

    def test_framework_name_detected(self):
        result = detect_work_types("create a django project with REST API")
        assert "gsd" in result

    def test_no_gsd_for_unrelated_prompt(self):
        result = detect_work_types("check the logs for errors")
        assert "gsd" not in result

    def test_migrate_keyword_detected(self):
        result = detect_work_types("migrate the database to PostgreSQL")
        assert "gsd" in result


class TestGsdNudgeEmission:
    """Tests for _emit_gsd_nudge skip logic and output."""

    def test_emits_for_multistep_prompt(self, tmp_path, capsys):
        """Qualifying multi-step prompt triggers stderr nudge."""
        _emit_gsd_nudge("build a new authentication system with OAuth", str(tmp_path))
        captured = capsys.readouterr()
        assert "/gsd:new-project" in captured.err
        assert "/gsd:quick" in captured.err

    def test_skips_short_prompt(self, tmp_path, capsys):
        """Prompts under 30 chars are skipped per D-02."""
        _emit_gsd_nudge("fix bug", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_skips_question_what(self, tmp_path, capsys):
        """Questions starting with 'what' are skipped per D-02."""
        _emit_gsd_nudge("what does the range() function do in Python?", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_skips_question_how(self, tmp_path, capsys):
        """Questions starting with 'how' are skipped per D-02."""
        _emit_gsd_nudge("how do I configure the database connection?", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_skips_question_why(self, tmp_path, capsys):
        """Questions starting with 'why' are skipped per D-02."""
        _emit_gsd_nudge("why is the test failing with import error?", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_skips_question_explain(self, tmp_path, capsys):
        """Questions starting with 'explain' are skipped per D-02."""
        _emit_gsd_nudge("explain the difference between async and threading", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_skips_slash_command(self, tmp_path, capsys):
        """Slash commands are skipped per D-02."""
        _emit_gsd_nudge("/gsd:new-project start a Flask application", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_skips_when_active_workstream(self, tmp_path, capsys):
        """No nudge when .planning/active-workstream has content per D-13."""
        planning_dir = tmp_path / ".planning"
        planning_dir.mkdir()
        (planning_dir / "active-workstream").write_text("my-workstream\n")
        _emit_gsd_nudge("build a new dashboard with React components", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_emits_when_no_active_workstream(self, tmp_path, capsys):
        """Nudge fires when .planning/active-workstream is missing."""
        # tmp_path has no .planning directory
        _emit_gsd_nudge("build a new dashboard with React components", str(tmp_path))
        captured = capsys.readouterr()
        assert "/gsd:new-project" in captured.err

    def test_emits_when_active_workstream_empty(self, tmp_path, capsys):
        """Nudge fires when .planning/active-workstream exists but is empty."""
        planning_dir = tmp_path / ".planning"
        planning_dir.mkdir()
        (planning_dir / "active-workstream").write_text("")
        _emit_gsd_nudge("build a new dashboard with React components", str(tmp_path))
        captured = capsys.readouterr()
        assert "/gsd:new-project" in captured.err

    def test_skips_none_prompt(self, tmp_path, capsys):
        """None prompt is handled gracefully."""
        _emit_gsd_nudge(None, str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_skips_empty_prompt(self, tmp_path, capsys):
        """Empty string prompt is handled gracefully."""
        _emit_gsd_nudge("", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

    def test_nudge_is_single_line(self, tmp_path, capsys):
        """The nudge output is a single line per D-06."""
        _emit_gsd_nudge("build a complete user management system", str(tmp_path))
        captured = capsys.readouterr()
        lines = [l for l in captured.err.strip().split("\n") if l.strip()]
        assert len(lines) == 1

    def test_skips_show_me_question(self, tmp_path, capsys):
        """Questions starting with 'show me' are skipped per D-02."""
        _emit_gsd_nudge("show me how the authentication flow works", str(tmp_path))
        captured = capsys.readouterr()
        assert captured.err == ""

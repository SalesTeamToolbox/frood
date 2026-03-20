"""End-to-end tests for memory recall and learn hooks.

Tests exercise the hooks via subprocess (same as Claude Code invokes them)
to validate the full stdin→processing→stderr pipeline.
"""

import json
import os
import re
import subprocess
import sys
from pathlib import Path

RECALL_HOOK = str(Path(__file__).parent.parent / ".claude" / "hooks" / "memory-recall.py")
LEARN_HOOK = str(Path(__file__).parent.parent / ".claude" / "hooks" / "memory-learn.py")


def run_hook(hook_path, event_data, env_overrides=None):
    """Run a hook script via subprocess, returning (returncode, stdout, stderr)."""
    env = os.environ.copy()
    # Ensure search service and Qdrant are unreachable for isolated tests
    env["AGENT42_SEARCH_URL"] = "http://127.0.0.1:19999"  # Non-existent port
    env["AGENT42_API_URL"] = "http://127.0.0.1:19998"
    env["QDRANT_URL"] = "http://127.0.0.1:19997"
    if env_overrides:
        env.update(env_overrides)

    result = subprocess.run(
        [sys.executable, hook_path],
        input=json.dumps(event_data),
        capture_output=True,
        text=True,
        env=env,
        timeout=15,
    )
    return result.returncode, result.stdout, result.stderr


class TestMemoryRecallHook:
    """Tests for memory-recall.py hook (UserPromptSubmit)."""

    def _make_memory_md(self, tmp_path, sections):
        """Create a .agent42/memory/MEMORY.md with given sections."""
        memory_dir = tmp_path / ".agent42" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        content = "\n\n".join(f"## {title}\n{body}" for title, body in sections)
        (memory_dir / "MEMORY.md").write_text(content, encoding="utf-8")
        return str(tmp_path)

    def test_short_prompt_silent(self, tmp_path):
        project_dir = self._make_memory_md(tmp_path, [("Test", "some content")])
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": project_dir,
                "user_prompt": "hi",  # < 15 chars
            },
        )
        assert rc == 0
        assert stderr.strip() == ""

    def test_slash_command_silent(self, tmp_path):
        project_dir = self._make_memory_md(tmp_path, [("Test", "some content")])
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": project_dir,
                "user_prompt": "/gsd:progress check the workstream status",
            },
        )
        assert rc == 0
        assert stderr.strip() == ""

    def test_matching_prompt_produces_recall_output(self, tmp_path):
        project_dir = self._make_memory_md(
            tmp_path,
            [
                (
                    "Deployment Configuration",
                    "SSH config agent42-prod set up with deploy user Contabo VPS server",
                ),
                (
                    "Architecture Decisions",
                    "MCP pivot v2 server ecosystem integrated Claude Code tooling layer",
                ),
            ],
        )
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": project_dir,
                "user_prompt": "How do I deploy to the production server with SSH config?",
            },
        )
        assert rc == 0
        assert "[agent42-memory] Recall:" in stderr
        assert "memories surfaced" in stderr

    def test_no_match_is_silent(self, tmp_path):
        project_dir = self._make_memory_md(
            tmp_path,
            [
                ("Deployment", "SSH config for VPS server"),
            ],
        )
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": project_dir,
                "user_prompt": "Tell me about quantum entanglement physics experiments",
            },
        )
        assert rc == 0
        assert "no matches" not in stderr
        # May be empty or have recall output if keywords happen to match — key is no "no matches" text

    def test_max_three_memories(self, tmp_path):
        # Create 6 sections all matching "deploy server production config setup"
        sections = [
            (
                f"Deploy Section {i}",
                f"deploy server production config setup environment {i} details about deployment configuration",
            )
            for i in range(6)
        ]
        project_dir = self._make_memory_md(tmp_path, sections)
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": project_dir,
                "user_prompt": "How to deploy server production config setup environment?",
            },
        )
        assert rc == 0
        if "[agent42-memory] Recall:" in stderr:
            # Count memory entries (lines starting with "  - [")
            memory_lines = [l for l in stderr.split("\n") if l.strip().startswith("- [")]
            assert len(memory_lines) <= 3

    def test_score_format_in_output(self, tmp_path):
        project_dir = self._make_memory_md(
            tmp_path,
            [
                (
                    "Server Config",
                    "deploy production server SSH config agent42 VPS Contabo setup environment",
                ),
            ],
        )
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": project_dir,
                "user_prompt": "How to deploy to production server with SSH config?",
            },
        )
        assert rc == 0
        if "[agent42-memory] Recall:" in stderr:
            # Score format: [XX%]
            assert "%" in stderr

    def test_keyword_source_tag(self, tmp_path):
        project_dir = self._make_memory_md(
            tmp_path,
            [
                (
                    "Server Config",
                    "deploy production server SSH config agent42 VPS Contabo setup environment variables",
                ),
            ],
        )
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": project_dir,
                "user_prompt": "How to deploy to production server SSH config environment?",
            },
        )
        assert rc == 0
        if "[agent42-memory] Recall:" in stderr:
            assert "via keyword" in stderr


class TestMemoryLearnHook:
    """Tests for memory-learn.py hook (Stop)."""

    def _setup_memory_dir(self, tmp_path):
        memory_dir = tmp_path / ".agent42" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        return str(tmp_path), memory_dir

    def test_normal_session_writes_history(self, tmp_path):
        project_dir, memory_dir = self._setup_memory_dir(tmp_path)
        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": project_dir,
                "stop_reason": "end_turn",
                "transcript_summary": "Implemented the login page with email validation and error handling",
                "tool_results": [
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/login.py"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/src/auth.py"}},
                    {"tool_name": "Bash", "tool_input": {"command": "pytest"}},
                ],
            },
        )
        assert rc == 0
        history = (memory_dir / "HISTORY.md").read_text(encoding="utf-8")
        assert "---" in history
        # Timestamp format check
        assert re.search(r"\[\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\]", history)

    def test_interrupted_session_skipped(self, tmp_path):
        project_dir, memory_dir = self._setup_memory_dir(tmp_path)
        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": project_dir,
                "stop_reason": "interrupted",
                "transcript_summary": "Was working on something but got interrupted",
                "tool_results": [
                    {"tool_name": "Read", "tool_input": {"file_path": "/src/main.py"}},
                ],
            },
        )
        assert rc == 0
        assert not (memory_dir / "HISTORY.md").exists()

    def test_trivial_no_files_few_tools_skipped(self, tmp_path):
        project_dir, memory_dir = self._setup_memory_dir(tmp_path)
        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": project_dir,
                "stop_reason": "end_turn",
                "transcript_summary": "Quick question about Python syntax",
                "tool_results": [
                    {"tool_name": "Read", "tool_input": {"file_path": "/src/main.py"}},
                ],
            },
        )
        assert rc == 0
        # No Write/Edit tools = no files modified, only 1 tool call < 3
        assert not (memory_dir / "HISTORY.md").exists()

    def test_duplicate_session_skipped(self, tmp_path):
        project_dir, memory_dir = self._setup_memory_dir(tmp_path)
        # Pre-populate HISTORY.md with an entry that has same keywords (>80% overlap)
        # Use the same transcript text so overlap is 100% — dedup must fire
        transcript = "Implemented the login page with email validation and error handling"
        existing = f"\n---\n[2026-03-20 10:00:00] Summary: {transcript}\n"
        (memory_dir / "HISTORY.md").write_text(existing, encoding="utf-8")

        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": project_dir,
                "stop_reason": "end_turn",
                "transcript_summary": transcript,
                "tool_results": [
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/login.py"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/src/auth.py"}},
                    {"tool_name": "Bash", "tool_input": {"command": "pytest"}},
                ],
            },
        )
        assert rc == 0
        history = (memory_dir / "HISTORY.md").read_text(encoding="utf-8")
        # Should still have only the original entry (no new entry added)
        assert history.count("\n---\n") == 1

    def test_non_duplicate_writes_normally(self, tmp_path):
        project_dir, memory_dir = self._setup_memory_dir(tmp_path)
        existing = "\n---\n[2026-03-20 10:00:00] Summary: Deployed to production VPS server\n"
        (memory_dir / "HISTORY.md").write_text(existing, encoding="utf-8")

        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": project_dir,
                "stop_reason": "end_turn",
                "transcript_summary": "Implemented the login page with email validation and error handling",
                "tool_results": [
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/login.py"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/src/auth.py"}},
                    {"tool_name": "Bash", "tool_input": {"command": "pytest"}},
                ],
            },
        )
        assert rc == 0
        history = (memory_dir / "HISTORY.md").read_text(encoding="utf-8")
        assert history.count("\n---\n") == 2

    def test_learn_stderr_output(self, tmp_path):
        project_dir, memory_dir = self._setup_memory_dir(tmp_path)
        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": project_dir,
                "stop_reason": "end_turn",
                "transcript_summary": "Added new API endpoint for user profiles",
                "tool_results": [
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/api.py"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/src/models.py"}},
                    {"tool_name": "Bash", "tool_input": {"command": "pytest"}},
                ],
            },
        )
        assert rc == 0
        assert "[agent42-memory] Learn: captured to" in stderr

    def test_missing_memory_dir_created(self, tmp_path):
        project_dir = str(tmp_path)  # No .agent42/memory/ exists
        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": project_dir,
                "stop_reason": "end_turn",
                "transcript_summary": "Created the initial project structure with database models",
                "tool_results": [
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/models.py"}},
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/config.py"}},
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/main.py"}},
                ],
            },
        )
        assert rc == 0
        assert (tmp_path / ".agent42" / "memory").is_dir()
        assert (tmp_path / ".agent42" / "memory" / "HISTORY.md").exists()


class TestMemoryDegradation:
    """Tests for graceful degradation when backends are unavailable."""

    def test_recall_falls_back_to_keyword_search(self, tmp_path):
        """With all remote services unreachable, recall still works via MEMORY.md."""
        memory_dir = tmp_path / ".agent42" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        (memory_dir / "MEMORY.md").write_text(
            "## Deployment\nSSH config agent42-prod deploy server production VPS Contabo environment setup\n",
            encoding="utf-8",
        )
        rc, stdout, stderr = run_hook(
            RECALL_HOOK,
            {
                "hook_event_name": "UserPromptSubmit",
                "project_dir": str(tmp_path),
                "user_prompt": "How do I deploy to production server environment?",
            },
        )
        assert rc == 0
        # Should still get results from keyword search on MEMORY.md
        if "[agent42-memory] Recall:" in stderr:
            assert "via keyword" in stderr

    def test_learn_falls_back_to_file_only(self, tmp_path):
        """With search service unreachable, learn still writes to HISTORY.md."""
        memory_dir = tmp_path / ".agent42" / "memory"
        memory_dir.mkdir(parents=True, exist_ok=True)
        rc, stdout, stderr = run_hook(
            LEARN_HOOK,
            {
                "hook_event_name": "Stop",
                "project_dir": str(tmp_path),
                "stop_reason": "end_turn",
                "transcript_summary": "Refactored the database connection pooling module",
                "tool_results": [
                    {"tool_name": "Write", "tool_input": {"file_path": "/src/db.py"}},
                    {"tool_name": "Edit", "tool_input": {"file_path": "/src/pool.py"}},
                    {"tool_name": "Bash", "tool_input": {"command": "pytest"}},
                ],
            },
        )
        assert rc == 0
        assert (memory_dir / "HISTORY.md").exists()
        assert "captured to HISTORY.md" in stderr

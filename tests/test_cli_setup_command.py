"""End-to-end tests for CliSetupCommandHandler (Phase 01 Plan 04).

These exercise the handler with mocked ``core.cli_setup`` functions so the
CLI wiring is validated without touching any real user config. A final
subprocess test runs ``frood.py cli-setup detect`` out-of-process to lock
in the JSON-stdout contract.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import pytest

from commands import CliSetupCommandHandler

# ── Pure handler tests (monkeypatched core) ──────────────────────────────


def test_handler_detect_prints_json(monkeypatch, capsys):
    expected = {
        "claude-code": {"installed": True, "wired": False, "enabled": True},
        "opencode": {"installed": False, "wired": False, "enabled": True, "projects": []},
    }

    def fake_detect_all(manifest=None):
        return expected

    monkeypatch.setattr("core.cli_setup.detect_all", fake_detect_all)

    args = argparse.Namespace(cli_setup_action="detect")
    CliSetupCommandHandler().run(args)

    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed == expected
    assert "claude-code" in parsed
    assert "opencode" in parsed


def test_handler_claude_code_calls_wire_cli(monkeypatch, capsys):
    called = {}

    def fake_wire(cli_name, manifest=None):
        called["cli"] = cli_name
        return {"changed": True, "backup": None}

    monkeypatch.setattr("core.cli_setup.wire_cli", fake_wire)

    args = argparse.Namespace(cli_setup_action="claude-code")
    CliSetupCommandHandler().run(args)

    assert called["cli"] == "claude-code"
    out = capsys.readouterr().out
    parsed = json.loads(out)
    assert parsed["changed"] is True


def test_handler_opencode_accepts_path(monkeypatch, capsys):
    instances: list[dict] = []

    class FakeOpenCodeSetup:
        def __init__(self, project_paths=None, manifest=None):
            instances.append({"project_paths": project_paths, "manifest": manifest})

        def wire(self):
            return {"changed": True, "projects": []}

    monkeypatch.setattr("core.cli_setup.OpenCodeSetup", FakeOpenCodeSetup)
    monkeypatch.setattr("core.user_frood_dir.load_manifest", lambda: {"clis": {}})

    args = argparse.Namespace(cli_setup_action="opencode", path="/some/path")
    CliSetupCommandHandler().run(args)

    assert len(instances) == 1
    assert instances[0]["project_paths"] == [Path("/some/path")]
    out = capsys.readouterr().out
    assert json.loads(out)["changed"] is True


def test_handler_opencode_without_path_passes_none(monkeypatch, capsys):
    instances: list[dict] = []

    class FakeOpenCodeSetup:
        def __init__(self, project_paths=None, manifest=None):
            instances.append({"project_paths": project_paths, "manifest": manifest})

        def wire(self):
            return {"changed": False}

    monkeypatch.setattr("core.cli_setup.OpenCodeSetup", FakeOpenCodeSetup)
    monkeypatch.setattr("core.user_frood_dir.load_manifest", lambda: {"clis": {}})

    args = argparse.Namespace(cli_setup_action="opencode", path=None)
    CliSetupCommandHandler().run(args)

    assert instances[0]["project_paths"] is None


def test_handler_all_only_wires_enabled(monkeypatch, capsys):
    wired: list[str] = []

    def fake_wire(cli_name, manifest=None):
        wired.append(cli_name)
        return {"cli": cli_name, "changed": True}

    fake_manifest = {
        "clis": {
            "claude-code": {"enabled": True},
            "opencode": {"enabled": False},
        }
    }
    monkeypatch.setattr("core.cli_setup.wire_cli", fake_wire)
    monkeypatch.setattr("core.user_frood_dir.load_manifest", lambda: fake_manifest)

    args = argparse.Namespace(cli_setup_action="all")
    CliSetupCommandHandler().run(args)

    assert wired == ["claude-code"]
    parsed = json.loads(capsys.readouterr().out)
    assert "claude-code" in parsed
    assert "opencode" not in parsed


def test_handler_unwire_requires_cli_arg(monkeypatch, capsys):
    args = argparse.Namespace(cli_setup_action="unwire", cli=None)
    with pytest.raises(SystemExit) as excinfo:
        CliSetupCommandHandler().run(args)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "unwire requires a CLI name" in err


def test_handler_unwire_forwards_to_core(monkeypatch, capsys):
    called = {}

    def fake_unwire(cli_name, manifest=None):
        called["cli"] = cli_name
        return {"restored": True}

    monkeypatch.setattr("core.cli_setup.unwire_cli", fake_unwire)

    args = argparse.Namespace(cli_setup_action="unwire", cli="claude-code")
    CliSetupCommandHandler().run(args)

    assert called["cli"] == "claude-code"
    assert json.loads(capsys.readouterr().out)["restored"] is True


def test_handler_propagates_core_exception(monkeypatch, capsys):
    def boom(cli_name, manifest=None):
        raise RuntimeError("boom")

    monkeypatch.setattr("core.cli_setup.wire_cli", boom)

    args = argparse.Namespace(cli_setup_action="claude-code")
    with pytest.raises(SystemExit) as excinfo:
        CliSetupCommandHandler().run(args)
    assert excinfo.value.code == 1
    err = capsys.readouterr().err
    assert "boom" in err


def test_handler_missing_sub_action_exits_2(capsys):
    args = argparse.Namespace(cli_setup_action=None)
    with pytest.raises(SystemExit) as excinfo:
        CliSetupCommandHandler().run(args)
    assert excinfo.value.code == 2
    err = capsys.readouterr().err
    assert "sub-action required" in err


# ── Out-of-process integration test ──────────────────────────────────────


def test_cli_integration_detect():
    """Run ``python frood.py cli-setup detect`` end-to-end; stdout must parse as JSON."""
    repo_root = Path(__file__).resolve().parent.parent
    result = subprocess.run(
        [sys.executable, "frood.py", "cli-setup", "detect"],
        cwd=repo_root,
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, f"stderr:\n{result.stderr}"
    parsed = json.loads(result.stdout)
    assert "claude-code" in parsed
    assert "opencode" in parsed

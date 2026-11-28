"""tests/test_frood_service.py — Frood systemd user service installer.

Covers ops/frood_service.py without touching the real home or the real
systemctl: FROOD_SERVICE_UNIT_DIR points at a tmp dir, FROOD_SYSTEMCTL at a
fake script that records its arguments, FROOD_SERVICE_LOG at a tmp path.
Ports are ephemeral (bind port 0), never 8000. No test kills anything.
"""

from __future__ import annotations

import importlib.util
import os
import re
import socket
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("frood_service", ROOT / "ops" / "frood_service.py")
assert _SPEC and _SPEC.loader
frood_service = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(frood_service)

FAKE_SYSTEMCTL = """\
#!/usr/bin/env python3
import os
import sys

with open(os.environ["FAKE_CALL_LOG"], "a") as f:
    f.write(" ".join(sys.argv[1:]) + "\\n")

args = sys.argv[1:]
if args and args[0] == "--user":
    args = args[1:]
fail_on = os.environ.get("FAKE_FAIL_ON", "")
if fail_on and any(fail_on in a for a in args):
    sys.exit(int(os.environ.get("FAKE_FAIL_CODE", "1")))
if args[:1] == ["is-active"]:
    state = os.environ.get("FAKE_IS_ACTIVE", "inactive")
    print(state)
    sys.exit(0 if state == "active" else 3)
if args[:1] == ["is-enabled"]:
    state = os.environ.get("FAKE_IS_ENABLED", "disabled")
    print(state)
    sys.exit(0 if state == "enabled" else 1)
sys.exit(0)
"""


def free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]
    finally:
        sock.close()


@pytest.fixture
def fake_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    python = repo / ".venv" / "bin" / "python"
    python.parent.mkdir(parents=True)
    python.write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
    python.chmod(python.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return repo


@pytest.fixture
def fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    script = tmp_path / "fake_systemctl.py"
    script.write_text(FAKE_SYSTEMCTL, encoding="utf-8")
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    call_log = tmp_path / "calls.log"
    call_log.write_text("", encoding="utf-8")
    unit_dir = tmp_path / "units"
    log_path = tmp_path / "logs" / "frood-http.log"
    monkeypatch.setenv("FROOD_SYSTEMCTL", str(script))
    monkeypatch.setenv("FAKE_CALL_LOG", str(call_log))
    monkeypatch.setenv("FROOD_SERVICE_UNIT_DIR", str(unit_dir))
    monkeypatch.setenv("FROOD_SERVICE_LOG", str(log_path))
    monkeypatch.setenv("FAKE_IS_ACTIVE", "inactive")
    monkeypatch.setenv("FAKE_IS_ENABLED", "disabled")
    monkeypatch.delenv("FAKE_FAIL_ON", raising=False)
    return {"unit_dir": unit_dir, "log": log_path, "calls": call_log}


def read_calls(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    return [line for line in text.splitlines() if line.strip()]


def assert_subsequence(calls: list[str], wanted: list[str]) -> None:
    positions = []
    for item in wanted:
        matches = [i for i, c in enumerate(calls) if c == f"--user {item}"]
        assert matches, f"missing systemctl call: --user {item} (calls: {calls})"
        positions.append(matches[0])
    assert positions == sorted(positions), f"calls out of order: {calls}"


class TestRenderUnit:
    def test_placeholders_execstart_restart_no_secrets(self, tmp_path: Path):
        text = frood_service.render_unit(
            "/opt/frood", "/opt/frood/.venv/bin/python", 8123, "/usr/bin:/bin", "/tmp/x.log"
        )
        assert re.search(r"@[A-Z_]+@", text) is None, text
        assert "@REPO@" not in text
        assert "@PYTHON@" not in text
        assert "@PORT@" not in text
        assert "@PATH@" not in text
        assert "@LOG@" not in text
        assert "Restart=on-failure" in text
        assert "ExecStart=/opt/frood/.venv/bin/python /opt/frood/frood.py --port 8123" in text
        for line in text.splitlines():
            assert "KEY" not in line, line
            assert "TOKEN" not in line, line
            assert "SECRET" not in line, line

    def test_leftover_placeholder_raises(self, tmp_path: Path):
        with pytest.raises(ValueError):
            frood_service.render_unit(
                "/opt/frood",
                "/opt/frood/.venv/bin/python",
                8000,
                "/usr/bin",
                "@PATH@",  # injected after @PATH@ was already substituted
            )


class TestInstallPortFree:
    def test_call_order_and_unit_content(
        self, fake_repo: Path, fake_env: dict[str, Path], capsys: pytest.CaptureFixture
    ):
        port = free_port()
        rc = frood_service.cmd_install(fake_repo, port=port)
        assert rc == 0
        calls = read_calls(fake_env["calls"])
        assert_subsequence(
            calls,
            [
                "daemon-reload",
                "enable frood.service",
                "reset-failed frood.service",
                "start frood.service",
            ],
        )
        unit_path = fake_env["unit_dir"] / "frood.service"
        assert unit_path.is_file()
        assert f"--port {port}" in unit_path.read_text(encoding="utf-8")
        assert fake_env["log"].parent.is_dir()  # install creates the log dir

    def test_second_install_unchanged_does_not_rewrite(
        self, fake_repo: Path, fake_env: dict[str, Path]
    ):
        port = free_port()
        assert frood_service.cmd_install(fake_repo, port=port) == 0
        unit_path = fake_env["unit_dir"] / "frood.service"
        before = (unit_path.read_text(encoding="utf-8"), unit_path.stat().st_mtime_ns)
        assert frood_service.cmd_install(fake_repo, port=port) == 0
        after = (unit_path.read_text(encoding="utf-8"), unit_path.stat().st_mtime_ns)
        assert before == after

    def test_failed_state_resets_before_start(
        self, fake_repo: Path, fake_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FAKE_IS_ACTIVE", "failed")
        port = free_port()
        assert frood_service.cmd_install(fake_repo, port=port) == 0
        calls = read_calls(fake_env["calls"])
        assert_subsequence(calls, ["reset-failed frood.service", "start frood.service"])


class TestInstallPortBusy:
    def test_busy_port_enables_without_start(
        self, fake_repo: Path, fake_env: dict[str, Path], capsys: pytest.CaptureFixture
    ):
        holder = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            holder.bind(("127.0.0.1", 0))
            port = holder.getsockname()[1]
            rc = frood_service.cmd_install(fake_repo, port=port)
        finally:
            holder.close()
        assert rc == 0
        calls = read_calls(fake_env["calls"])
        assert "--user start frood.service" not in calls
        assert "--user reset-failed frood.service" not in calls
        out = capsys.readouterr().out
        assert f"port {port} is in use" in out
        # Enabled anyway: unit written + enable ran.
        assert (fake_env["unit_dir"] / "frood.service").is_file()
        assert "--user enable frood.service" in calls


class TestInstallActive:
    def test_active_unchanged_reports_already_running(
        self,
        fake_repo: Path,
        fake_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        monkeypatch.setenv("FAKE_IS_ACTIVE", "active")
        port = free_port()
        assert frood_service.cmd_install(fake_repo, port=port) == 0
        capsys.readouterr()
        fake_env["calls"].write_text("", encoding="utf-8")  # only the 2nd install counts
        assert frood_service.cmd_install(fake_repo, port=port) == 0
        out = capsys.readouterr().out
        assert "already running" in out
        calls = read_calls(fake_env["calls"])
        assert "--user start frood.service" not in calls
        assert "--user restart frood.service" not in calls

    def test_active_changed_restarts(
        self,
        fake_repo: Path,
        fake_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        monkeypatch.setenv("FAKE_IS_ACTIVE", "active")
        port = free_port()
        assert frood_service.cmd_install(fake_repo, port=port) == 0
        unit_path = fake_env["unit_dir"] / "frood.service"
        with unit_path.open("a", encoding="utf-8") as f:
            f.write("# stale\n")
        assert frood_service.cmd_install(fake_repo, port=port) == 0
        calls = read_calls(fake_env["calls"])
        assert "--user restart frood.service" in calls
        assert "--user start frood.service" not in calls


class TestUninstall:
    def test_uninstall_disables_removes_reloads(self, fake_repo: Path, fake_env: dict[str, Path]):
        unit_path = fake_env["unit_dir"] / "frood.service"
        unit_path.parent.mkdir(parents=True, exist_ok=True)
        unit_path.write_text("stale", encoding="utf-8")
        assert frood_service.cmd_uninstall() == 0
        assert not unit_path.exists()
        assert_subsequence(
            read_calls(fake_env["calls"]),
            ["disable --now frood.service", "daemon-reload"],
        )

    def test_failing_systemctl_reports_exit_code(
        self, fake_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setenv("FAKE_FAIL_ON", "disable")
        monkeypatch.setenv("FAKE_FAIL_CODE", "5")
        assert frood_service.cmd_uninstall() == 5


class TestSystemctlFailures:
    def test_missing_systemctl_binary_reports_exit_code(
        self,
        fake_repo: Path,
        fake_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        monkeypatch.setenv("FROOD_SYSTEMCTL", "/nonexistent-systemctl-xyz")
        port = free_port()
        rc = frood_service.cmd_install(fake_repo, port=port)
        assert rc == 127
        assert "exit 127" in capsys.readouterr().err

    def test_hung_systemctl_reports_timeout(
        self,
        fake_repo: Path,
        fake_env: dict[str, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        sleeper = tmp_path / "sleepy_systemctl.py"
        sleeper.write_text(
            "#!/usr/bin/env python3\nimport time\ntime.sleep(30)\n", encoding="utf-8"
        )
        sleeper.chmod(sleeper.stat().st_mode | stat.S_IXUSR)
        monkeypatch.setenv("FROOD_SYSTEMCTL", str(sleeper))
        monkeypatch.setattr(frood_service, "SYSTEMCTL_TIMEOUT", 1)
        port = free_port()
        rc = frood_service.cmd_install(fake_repo, port=port)
        assert rc == 124
        assert "exit 124" in capsys.readouterr().err


class TestRefusals:
    def test_worktree_repo_refused(self, fake_env: dict[str, Path]):
        rc = frood_service.cmd_install("/x/.claude/worktrees/y", port=free_port())
        assert rc == 2

    def test_missing_venv_python_refused(
        self, tmp_path: Path, fake_env: dict[str, Path], capsys: pytest.CaptureFixture
    ):
        repo = tmp_path / "plain-repo"
        repo.mkdir()
        assert frood_service.cmd_install(repo, port=free_port()) == 2
        assert ".venv" in capsys.readouterr().err

    def test_non_linux_skips(
        self, fake_repo: Path, fake_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ):
        monkeypatch.setattr(sys, "platform", "darwin")
        assert frood_service.cmd_install(fake_repo, port=free_port()) == 0


class TestDryRun:
    def test_dry_run_creates_nothing(
        self,
        fake_repo: Path,
        fake_env: dict[str, Path],
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        home = tmp_path / "home"
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.delenv("FROOD_SERVICE_UNIT_DIR", raising=False)
        monkeypatch.delenv("FROOD_SERVICE_LOG", raising=False)
        port = free_port()
        rc = frood_service.cmd_install(fake_repo, port=port, dry_run=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert f"--port {port}" in out
        assert "would run: systemctl --user start frood.service" in out
        assert not home.exists()
        assert read_calls(fake_env["calls"]) == []

    def test_dry_run_subprocess(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        # The real checkout is a worktree, whose installer refuses to run;
        # mirror the installer + template into a scratch "main checkout".
        main_repo = tmp_path / "main-checkout"
        (main_repo / "ops" / "systemd").mkdir(parents=True)
        (main_repo / "ops" / "frood_service.py").write_bytes(
            (ROOT / "ops" / "frood_service.py").read_bytes()
        )
        (main_repo / "ops" / "systemd" / "frood.service").write_bytes(
            (ROOT / "ops" / "systemd" / "frood.service").read_bytes()
        )
        python = main_repo / ".venv" / "bin" / "python"
        python.parent.mkdir(parents=True)
        python.write_text("#!/bin/sh\nexec true\n", encoding="utf-8")
        python.chmod(python.stat().st_mode | stat.S_IXUSR)
        home = tmp_path / "sub-home"
        env = dict(os.environ)
        env["HOME"] = str(home)
        env.pop("FROOD_SERVICE_UNIT_DIR", None)
        env.pop("FROOD_SERVICE_LOG", None)
        env.pop("FROOD_SYSTEMCTL", None)
        port = free_port()
        proc = subprocess.run(
            [
                sys.executable,
                str(main_repo / "ops" / "frood_service.py"),
                "install",
                "--port",
                str(port),
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
        assert proc.returncode == 0, proc.stderr
        assert f"--port {port}" in proc.stdout
        assert not home.exists()


class TestPathValue:
    def test_drops_relative_missing_worktree_and_duplicates(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ):
        good_a = tmp_path / "a"
        good_b = tmp_path / "b"
        good_a.mkdir()
        good_b.mkdir()
        worktree_dir = tmp_path / ".claude" / "worktrees" / "x" / "bin"
        worktree_dir.mkdir(parents=True)
        monkeypatch.setenv(
            "PATH",
            os.pathsep.join(
                [
                    "relative/dir",
                    str(good_a),
                    "/nonexistent-dir-xyz",
                    str(worktree_dir),
                    str(good_a),
                    str(good_b),
                ]
            ),
        )
        value, _warnings = frood_service.build_path_value()
        assert value == os.pathsep.join([str(good_a), str(good_b)])

    def test_missing_tools_warn(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
        empty = tmp_path / "empty"
        empty.mkdir()
        monkeypatch.setenv("PATH", str(empty))
        _value, warnings = frood_service.build_path_value()
        assert any("claude" in w for w in warnings)
        assert any("opencode" in w for w in warnings)


class TestStatus:
    def test_status_prints_state_and_path(
        self,
        fake_env: dict[str, Path],
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ):
        monkeypatch.setenv("FAKE_IS_ACTIVE", "active")
        monkeypatch.setenv("FAKE_IS_ENABLED", "enabled")
        assert frood_service.cmd_status() == 0
        out = capsys.readouterr().out
        assert "is-active: active" in out
        assert "is-enabled: enabled" in out
        assert str(fake_env["unit_dir"] / "frood.service") in out


class TestDashboardHost:
    def test_quoted_unquoted_and_default(self, tmp_path: Path):
        assert frood_service.read_dashboard_host(tmp_path) == "127.0.0.1"
        repo = tmp_path / "r"
        repo.mkdir()
        (repo / ".env").write_text(
            "# comment\nOTHER=1\nDASHBOARD_HOST='0.0.0.0'\n", encoding="utf-8"
        )
        assert frood_service.read_dashboard_host(repo) == "0.0.0.0"  # noqa: S104
        (repo / ".env").write_text('DASHBOARD_HOST="127.0.0.1"\n', encoding="utf-8")
        assert frood_service.read_dashboard_host(repo) == "127.0.0.1"

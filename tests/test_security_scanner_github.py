"""
Tests for the public-repo guard on the security scanner's GitHub reporting.

These tests mock ``asyncio.create_subprocess_exec`` so no real ``gh`` process is
ever spawned and no network request is made.
"""

import logging

import pytest

from core.security_scanner import ScheduledSecurityScanner


class _FakeProc:
    """A minimal asyncio process stand-in."""

    def __init__(self, returncode, stdout=b"", stderr=b"", exc=None):
        self.returncode = returncode
        self._stdout = stdout
        self._stderr = stderr
        self.pid = 999
        self.killed = False
        self.exc = exc

    async def communicate(self):
        if self.exc is not None:
            raise self.exc
        return self._stdout, self._stderr

    async def wait(self):
        return self.returncode

    def kill(self):
        self.killed = True


class SubprocessMocker:
    """Records subprocess calls and returns programmed responses per subcommand."""

    def __init__(self):
        self.calls = []  # list of (args, kwargs)
        # (returncode, stdout, stderr)
        self.responses = {
            "repo_view": (
                0,
                b'{"visibility": "PUBLIC", "nameWithOwner": "owner/repo"}',
                b"",
            ),
            "issue_create": (0, b"https://github.com/owner/repo/issues/1", b""),
            "issue_comment": (0, b"", b""),
            "issue_close": (0, b"", b""),
            "issue_list": (0, b"[]", b""),
        }
        self._repo_view_exc = None  # if set, communicate() raises it for repo view

    async def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        cmd = list(args)
        exc = None
        if not cmd or cmd[0] != "gh":
            key = "issue_create"
        elif cmd[1] == "repo":
            key = "repo_view"
            exc = self._repo_view_exc
        elif cmd[1] == "issue":
            op = cmd[2] if len(cmd) > 2 else ""
            key = f"issue_{op}"
        else:
            key = "issue_create"
        if exc is not None:
            return _FakeProc(0, b"", b"", exc=exc)
        returncode, out, err = self.responses.get(key, (0, b"", b""))
        return _FakeProc(returncode, out, err)

    def repo_view_calls(self):
        return [c for c in self.calls if len(c[0]) > 1 and c[0][1] == "repo"]

    def issue_calls(self):
        return [c for c in self.calls if len(c[0]) > 1 and c[0][1] == "issue"]


def _patch_subprocess(monkeypatch, mocker):
    monkeypatch.setattr(
        __import__("core.security_scanner", fromlist=["asyncio"]).asyncio,
        "create_subprocess_exec",
        mocker,
    )


def _make_report(total=3, severity="high"):
    return {
        "timestamp": "2026-11-28T01:06:00+00:00",
        "findings": [
            {
                "severity": "high",
                "category": "Config: x",
                "description": "finding one",
                "detail": "",
            },
        ],
        "counts": {"critical": 0, "high": 3, "medium": 0, "low": 0},
        "overall_severity": severity,
        "total": total,
    }


def _warning_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.levelname == "WARNING"]


def _info_messages(caplog):
    return [r.getMessage() for r in caplog.records if r.levelname == "INFO"]


class TestPublicGuard:
    """The scanner must never post findings to a non-private repo."""

    @pytest.mark.asyncio
    async def test_public_repo_no_writes_and_warning_once(self, monkeypatch, caplog):
        mocker = SubprocessMocker()
        _patch_subprocess(monkeypatch, mocker)
        caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        scanner._github_issues = True
        report = _make_report()

        await scanner._report_to_github(report)

        # No gh issue subcommand at all (fail closed).
        assert mocker.issue_calls() == []
        # gh repo view ran once.
        assert len(mocker.repo_view_calls()) == 1
        # Exactly one WARNING names the repo and visibility.
        warns = _warning_messages(caplog)
        assert len(warns) == 1
        assert "owner/repo" in warns[0]
        assert "PUBLIC" in warns[0]
        assert "never posts findings to a non-private repo" in warns[0]

        # Second scan: warning is not repeated, but gh repo view runs again.
        await scanner._report_to_github(report)
        warns = _warning_messages(caplog)
        assert len(warns) == 1  # not repeated
        assert len(mocker.repo_view_calls()) == 2  # repo view ran again
        assert mocker.issue_calls() == []

    @pytest.mark.asyncio
    async def test_private_repo_proceeds(self, monkeypatch, caplog):
        mocker = SubprocessMocker()
        mocker.responses["repo_view"] = (
            0,
            b'{"visibility": "PRIVATE", "nameWithOwner": "owner/repo"}',
            b"",
        )
        _patch_subprocess(monkeypatch, mocker)
        caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        scanner._github_issues = True
        report = _make_report()

        await scanner._report_to_github(report)

        assert mocker.issue_calls() != []
        # No skip warning for a private repo.
        warns = _warning_messages(caplog)
        assert not any("skipped" in w for w in warns)

    @pytest.mark.asyncio
    async def test_repo_view_fail_closed(self, monkeypatch, caplog):
        """gh repo view exit 1 / timeout / missing -> nothing written."""
        for exc in (None, TimeoutError()):
            mocker = SubprocessMocker()
            if exc is None:
                # exit 1
                mocker.responses["repo_view"] = (1, b"", b"not a repo")
            else:
                mocker._repo_view_exc = exc
            _patch_subprocess(monkeypatch, mocker)
            caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

            scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
            scanner._github_issues = True
            await scanner._report_to_github(_make_report())

            assert mocker.issue_calls() == [], f"writes on fail-closed case {exc!r}"
            warns = _warning_messages(caplog)
            assert any("skipped" in w for w in warns)

    @pytest.mark.asyncio
    async def test_gh_missing_fail_closed(self, monkeypatch, caplog):
        mocker = SubprocessMocker()

        async def boom(*args, **kwargs):
            raise FileNotFoundError("gh: not found")

        _patch_subprocess(monkeypatch, boom)
        caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        scanner._github_issues = True
        await scanner._report_to_github(_make_report())
        assert mocker.issue_calls() == []
        warns = _warning_messages(caplog)
        assert any("skipped" in w for w in warns)


class TestTruthfulLogs:
    """Write methods return True only on gh exit 0; logs reflect outcomes."""

    @pytest.mark.asyncio
    async def test_create_issue_exit1_no_created_log_warning_with_stderr(self, monkeypatch, caplog):
        mocker = SubprocessMocker()
        mocker.responses["repo_view"] = (
            0,
            b'{"visibility": "PRIVATE", "nameWithOwner": "owner/repo"}',
            b"",
        )
        mocker.responses["issue_list"] = (0, b"[]", b"")
        mocker.responses["issue_create"] = (1, b"", b"label 'security-scan' not found")
        _patch_subprocess(monkeypatch, mocker)
        caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        scanner._github_issues = True
        await scanner._report_to_github(_make_report())

        assert "Created new security scan GitHub issue" not in _info_messages(caplog)
        warns = _warning_messages(caplog)
        assert any(
            "issue create failed" in w and "label 'security-scan' not found" in w for w in warns
        )

    @pytest.mark.asyncio
    async def test_create_issue_exit0_created_log(self, monkeypatch, caplog):
        mocker = SubprocessMocker()
        mocker.responses["repo_view"] = (
            0,
            b'{"visibility": "PRIVATE", "nameWithOwner": "owner/repo"}',
            b"",
        )
        mocker.responses["issue_list"] = (0, b"[]", b"")
        mocker.responses["issue_create"] = (
            0,
            b"https://github.com/owner/repo/issues/1",
            b"",
        )
        _patch_subprocess(monkeypatch, mocker)
        caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        scanner._github_issues = True
        await scanner._report_to_github(_make_report())
        assert any("Created new security scan GitHub issue" in m for m in _info_messages(caplog))

    @pytest.mark.asyncio
    async def test_comment_and_close_logs(self, monkeypatch, caplog):
        mocker = SubprocessMocker()
        mocker.responses["repo_view"] = (
            0,
            b'{"visibility": "PRIVATE", "nameWithOwner": "owner/repo"}',
            b"",
        )
        # existing issue #7
        mocker.responses["issue_list"] = (0, b'[{"number": 7}]', b"")
        mocker.responses["issue_comment"] = (0, b"", b"")
        _patch_subprocess(monkeypatch, mocker)
        caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        scanner._github_issues = True
        await scanner._report_to_github(_make_report())
        assert any("Updated security scan issue #7" in m for m in _info_messages(caplog))
        assert len(mocker.issue_calls()) >= 2  # list + comment

        # Clean scan closes the existing issue, "Closed" logged only on exit 0.
        mocker.responses["issue_close"] = (0, b"", b"")
        clean = _make_report(total=0)
        await scanner._report_to_github(clean)
        assert any("Closed security scan issue #7" in m for m in _info_messages(caplog))

        # Close failure -> no "Closed" log.
        caplog.clear()
        # Override close to fail.
        mocker.responses["issue_close"] = (1, b"", b"not found")
        await scanner._report_to_github(clean)
        assert not any("Closed security scan issue #7" in m for m in _info_messages(caplog))


class TestConstructorAndSettings:
    @pytest.mark.asyncio
    async def test_constructor_default_is_false(self):
        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        assert scanner._github_issues is False

    def test_frood_wires_settings(self, monkeypatch):
        from core.config import settings

        object.__setattr__(settings, "security_scan_github_issues", False)
        object.__setattr__(settings, "security_scan_interval", "6h")
        object.__setattr__(settings, "security_scan_min_severity", "high")

        from frood import Frood

        frood = Frood()
        sc = frood.security_scanner
        assert sc._github_issues is False
        assert sc._interval == 6 * 3600
        assert sc._min_severity == "high"

    @pytest.mark.asyncio
    async def test_create_issue_direct_on_public_repo_writes_nothing(self, monkeypatch, caplog):
        mocker = SubprocessMocker()
        _patch_subprocess(monkeypatch, mocker)
        caplog.set_level(logging.DEBUG, logger="frood.security_scanner")

        scanner = ScheduledSecurityScanner(workspace_path="/tmp/wt")
        ok = await scanner._create_issue("t", "b", ["security-scan"])
        assert ok is False
        assert mocker.issue_calls() == []

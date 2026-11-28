"""
tests/test_train_node_tests.py — the train's own pinned test for ticket train-node-tests.

Drives `bash ops/train.sh` against temp git-repo fixtures with FROOD_REPORTS_ROOT in a
temp dir and every subprocess run bounded by `timeout=`. Covers the pass bars:

- python ticket with tests/test_<t>.py -> pytest runs that file, exit 0,
  receipt tests_source: python-convention
- node-only ticket whose board ticket JSON lists a passing *.test.mjs -> exit 0,
  receipt tests_source: board-ticket / tests: <file>, node-test.log present
- same with a failing node test -> exit 1, receipt status: test failure
- node test sleeping past TRAIN_NODE_TIMEOUT=2 -> exit 1, detail names the timeout;
  no node child left behind (pid from the test's own spawn)
- no ticket JSON, Mandate with tests: a.test.mjs -> runs it (tests_source: mandate)
- ticket JSON lists a missing path -> exit 1, detail names the path
- nothing anywhere -> exit 1, detail lists every source tried
- lint failure still exits 2 before any test runs

Extra cases: worktree resolution via main_root; malformed ticket JSON; entries lacking
`test` plus a duplicate (each file run once); receipt line order / exit_code values;
python-convention pytest.log produced.
"""

import os
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest

FIXTURE_TRAIN_SH = Path(__file__).resolve().parents[1] / "ops" / "train.sh"
FIXTURE_LOCK_LIB = (
    FIXTURE_TRAIN_SH.parents[1] / "orchestrator" / "ops" / "workstation" / "suite-lock.sh"
)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _git(repo: Path, *args, **kwargs):
    kwargs.setdefault("cwd", repo)
    kwargs.setdefault("capture_output", True)
    kwargs.setdefault("text", True)
    kwargs.setdefault("check", True)
    return subprocess.run(["git", *args], **kwargs)


def make_stub_ruff(bin_dir: Path, exit_code: int = 0) -> Path:
    """A `ruff` stub placed first on PATH so train.sh takes its `ruff check .` branch."""
    bin_dir.mkdir(parents=True, exist_ok=True)
    stub = bin_dir / "ruff"
    stub.write_text(f"#!/bin/bash\nexit {exit_code}\n")
    stub.chmod(0o755)
    return stub


def make_fixture(
    tmp_path: Path, ticket: str, tracked_files=None, untracked_files=None, copy_lock_lib=False
):
    """Create a tmp git repo (`git init -b main`, local user config, one commit)
    holding a copy of ops/train.sh plus the case's test files.

    tracked_files / untracked_files: dict of rel_path -> content.
    copy_lock_lib: copy the repo's orchestrator/ops/workstation/suite-lock.sh
    into the fixture at the same relative path, so train.sh sources it instead
    of falling back to the installed lib via HOME (or running unlocked).
    Returns the repo Path.
    """
    tracked_files = tracked_files or {}
    untracked_files = untracked_files or {}
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    (repo / "ops").mkdir()
    shutil.copy(FIXTURE_TRAIN_SH, repo / "ops" / "train.sh")
    (repo / "ops" / "train.sh").chmod(0o755)
    if copy_lock_lib:
        dest = repo / "orchestrator" / "ops" / "workstation" / "suite-lock.sh"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(FIXTURE_LOCK_LIB, dest)
    for rel, content in tracked_files.items():
        _write(repo / rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    for rel, content in untracked_files.items():
        _write(repo / rel, content)
    return repo


def run_train(repo: Path, ticket: str, bin_dir: Path, reports_root: Path, env_extra=None):
    """Run `bash ops/train.sh <ticket>` in the fixture with a stub ruff on PATH.

    Every run gets a private SUITE_LOCK_ROOT under tmp_path (repo.parent is
    tmp_path), so no test ever touches the real box-wide lock at
    ~/.local/state/frood-workstation/suite-lock.
    """
    env = os.environ.copy()
    # The calling test process may itself have inherited FROOD_SUITE_LOCK_HELD=1
    # (e.g. `make test` exports it to pytest, or the gate runs the suite with it
    # set). Never leak it into train.sh: train.sh would then skip the lock and
    # every suite_lock assertion breaks. Pop it here; env_extra (test (d)) can
    # still set it deliberately.
    env.pop("FROOD_SUITE_LOCK_HELD", None)
    env.pop("SUITE_LOCK", None)
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["FROOD_REPORTS_ROOT"] = str(reports_root)
    env["SUITE_LOCK_ROOT"] = str(repo.parent / "slroot")
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        ["bash", "ops/train.sh", ticket],
        cwd=repo,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


_RECEIPT_RE = re.compile(r"^(\w+):\s*(.*)$")


def parse_receipt(reports_root: Path, ticket: str) -> dict:
    receipt = reports_root / ticket / "receipt.md"
    out = {}
    for line in receipt.read_text().splitlines():
        m = _RECEIPT_RE.match(line)
        if m:
            out[m.group(1)] = m.group(2)
    return out


# ── node:test fixtures used by the cases ──
PASS_NODE = 'import test from "node:test";\nimport assert from "node:assert/strict";\n\ntest("passes", () => { assert.ok(true); });\n'
FAIL_NODE = 'import test from "node:test";\nimport assert from "node:assert/strict";\n\ntest("fails", () => { assert.ok(false); });\n'
SLEEP_NODE = (
    'import test from "node:test";\nimport fs from "node:fs";\n'
    "fs.writeFileSync(process.env.TRAIN_FIXTURE_PIDFILE, String(process.pid));\n"
    'test("sleeps past the timeout", () => {\n'
    "  return new Promise((r) => setTimeout(r, 10000));\n"
    "});\n"
)
PASS_PY = "def test_passes():\n    assert True\n"
LOCKENV_PY = (
    "import os\n"
    "def test_env_seen():\n"
    '    with open(os.environ["TRAIN_FIXTURE_ENVFILE"], "w") as fh:\n'
    '        fh.write(os.environ.get("FROOD_SUITE_LOCK_HELD", ""))\n'
)


class TestPythonConvention:
    def test_python_ticket_runs_pytest(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["exit_code"] == "0"
        assert receipt["tests_source"] == "python-convention"
        assert receipt["tests"] == "tests/test_py-ticket.py"
        assert (reports_root / ticket / "pytest.log").exists()


class TestBoardTicket:
    def test_node_passing_from_board_ticket(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={
                "orchestrator/tests/x.test.mjs": PASS_NODE,
            },
            untracked_files={
                ".opencode/board/tickets/node-ticket.json": (
                    '{"schema":1,"id":"node-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"orchestrator/tests/x.test.mjs"}]}'
                ),
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["exit_code"] == "0"
        assert receipt["tests_source"] == "board-ticket"
        assert receipt["tests"] == "orchestrator/tests/x.test.mjs"
        assert (reports_root / ticket / "node-test.log").exists()

    def test_node_failing_from_board_ticket(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"orchestrator/tests/x.test.mjs": FAIL_NODE},
            untracked_files={
                ".opencode/board/tickets/node-ticket.json": (
                    '{"schema":1,"id":"node-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"orchestrator/tests/x.test.mjs"}]}'
                ),
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 1, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "test failure"
        assert receipt["exit_code"] == "1"
        assert receipt["tests_source"] == "board-ticket"
        assert receipt["tests"] == "orchestrator/tests/x.test.mjs"
        # node failure output is catted to stderr (not pytest.log).
        node_log = (reports_root / ticket / "node-test.log").read_text()
        assert node_log.strip(), "node-test.log should hold this run's failure output"
        assert node_log.strip() in res.stderr

    def test_board_ticket_missing_path(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            untracked_files={
                ".opencode/board/tickets/node-ticket.json": (
                    '{"schema":1,"id":"node-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"orchestrator/tests/missing.test.mjs"}]}'
                ),
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 1, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "test failure"
        detail = (reports_root / ticket / "receipt.md").read_text()
        assert "detail: listed test not found: orchestrator/tests/missing.test.mjs" in detail

    def test_board_ticket_entries_lacking_test_and_duplicate_run_once(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={
                "orchestrator/tests/a.test.mjs": PASS_NODE,
                "orchestrator/tests/b.test.mjs": PASS_NODE,
            },
            untracked_files={
                ".opencode/board/tickets/node-ticket.json": (
                    '{"schema":1,"id":"node-ticket","stage":"working",'
                    '"blast_radius":['
                    '{"caller":"c1","expect":"unchanged"},'
                    '{"caller":"c2","expect":"unchanged","test":null},'
                    '{"caller":"c3","expect":"unchanged","test":""},'
                    '{"caller":"c4","expect":"unchanged","test":"orchestrator/tests/a.test.mjs"},'
                    '{"caller":"c5","expect":"unchanged","test":"orchestrator/tests/a.test.mjs"},'
                    '{"caller":"c6","expect":"unchanged","test":"orchestrator/tests/b.test.mjs"}'
                    "]}"
                ),
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["tests_source"] == "board-ticket"
        # each file run once, de-duplicated, array order
        assert receipt["tests"] == "orchestrator/tests/a.test.mjs,orchestrator/tests/b.test.mjs"
        # node-test.log contains both tests (each ran once -> two "ok" lines at minimum)
        log = (reports_root / ticket / "node-test.log").read_text()
        assert log.count("ok") >= 2 or "passes" in log

    def test_malformed_ticket_json(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            untracked_files={
                ".opencode/board/tickets/node-ticket.json": "{ not valid json",
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 1, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "test failure"
        assert (
            "detail: unreadable board ticket json: "
            + str(repo / ".opencode" / "board" / "tickets" / "node-ticket.json")
        ) in (reports_root / ticket / "receipt.md").read_text()

    def test_nothing_found_lists_every_source(self, tmp_path):
        ticket = "ghost-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(tmp_path, ticket)
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 1, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "test failure"
        assert receipt["exit_code"] == "1"
        assert receipt["tests_source"] == "none"
        assert receipt["tests"] == ""
        detail = (reports_root / ticket / "receipt.md").read_text()
        assert "detail: no tests found for ticket ghost-ticket" in detail
        assert "tests/test_ghost-ticket_demo.py" in detail
        assert "tests/test_ghost-ticket.py" in detail

    def test_worktree_resolves_via_board_ticket(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={
                "orchestrator/tests/x.test.mjs": PASS_NODE,
            },
        )
        wt = tmp_path / "wt"
        _git(repo, "worktree", "add", "--detach", str(wt), "HEAD")
        # ticket JSON only in the main fixture checkout (untracked)
        _write(
            repo / ".opencode" / "board" / "tickets" / f"{ticket}.json",
            '{"schema":1,"id":"node-ticket","stage":"working",'
            '"blast_radius":[{"caller":"c","expect":"unchanged",'
            '"test":"orchestrator/tests/x.test.mjs"}]}',
        )
        res = run_train(wt, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["tests_source"] == "board-ticket"
        assert receipt["tests"] == "orchestrator/tests/x.test.mjs"


class TestMandate:
    def test_mandate_tests_line(self, tmp_path):
        ticket = "mandate-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"a.test.mjs": PASS_NODE},
            untracked_files={
                ".opencode/reports/mandate-ticket/mandate.md": "# mandate\ntests: a.test.mjs\n",
            },
            # no ticket JSON -> falls through to mandate
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["tests_source"] == "mandate"
        assert receipt["tests"] == "a.test.mjs"

    def test_mandate_tests_line_comma_list(self, tmp_path):
        ticket = "mandate-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"a.test.mjs": PASS_NODE, "b.test.mjs": PASS_NODE},
            untracked_files={
                ".opencode/reports/mandate-ticket/mandate.md": (
                    "# mandate\ntests:a.test.mjs, b.test.mjs,a.test.mjs\n"
                ),
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["tests_source"] == "mandate"
        assert receipt["tests"] == "a.test.mjs,b.test.mjs"

    def test_mandate_tests_token_is_not_globbed(self, tmp_path):
        ticket = "mandate-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"a.test.mjs": PASS_NODE},
            untracked_files={
                ".opencode/reports/mandate-ticket/mandate.md": "# mandate\ntests: *.test.mjs\n",
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 1
        receipt_text = (reports_root / ticket / "receipt.md").read_text()
        assert "detail: listed test not found: *.test.mjs" in receipt_text


class TestLogsFresh:
    def test_failure_log_holds_only_this_run(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
        )
        log = reports_root / ticket / "pytest.log"
        log.parent.mkdir(parents=True)
        log.write_text("STALE-PREVIOUS-RUN\n")
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        assert "STALE-PREVIOUS-RUN" not in log.read_text()


class TestTimeoutNoChild:
    def test_node_timeout_no_child_left(self, tmp_path):
        ticket = "sleep-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        pidfile = tmp_path / "pidfile"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"z.sleep.test.mjs": SLEEP_NODE},
            untracked_files={
                ".opencode/board/tickets/sleep-ticket.json": (
                    '{"schema":1,"id":"sleep-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"z.sleep.test.mjs"}]}'
                ),
            },
        )
        env = {"TRAIN_NODE_TIMEOUT": "2", "TRAIN_FIXTURE_PIDFILE": str(pidfile)}
        res = run_train(repo, ticket, bin_dir, reports_root, env_extra=env)
        assert res.returncode == 1, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "test failure"
        assert (
            "detail: node --test timed out after 2s: z.sleep.test.mjs"
            in (reports_root / ticket / "receipt.md").read_text()
        )
        # no-child check: pid must be dead within 5 s
        pid = int(pidfile.read_text())
        dead = False
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                dead = True
                break
            except PermissionError:
                dead = True
                break
            time.sleep(0.1)
        assert dead, f"node child pid {pid} still alive after train.sh returned"
        # already dead; do not kill again


class TestLint:
    def test_lint_failure_exits_2_before_tests(self, tmp_path):
        ticket = "any-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir, exit_code=1)  # lint failure
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_any-ticket.py": PASS_PY},
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 2, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "lint failure"
        assert receipt["exit_code"] == "2"
        assert "tests_source" not in receipt
        assert "tests" not in receipt


class TestReceiptOrder:
    def test_receipt_line_order_and_exit_codes(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"orchestrator/tests/x.test.mjs": PASS_NODE},
            untracked_files={
                ".opencode/board/tickets/node-ticket.json": (
                    '{"schema":1,"id":"node-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"orchestrator/tests/x.test.mjs"}]}'
                ),
            },
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        text = (reports_root / ticket / "receipt.md").read_text()
        lines = [l for l in text.splitlines() if l.strip()]
        order = [
            "status:",
            "started:",
            "finished:",
            "exit_code:",
            "local_head_sha:",
            "tests_source:",
            "tests:",
        ]
        indices = [next(i for i, l in enumerate(lines) if l.startswith(o)) for o in order]
        assert indices == sorted(indices), f"receipt line order wrong: {lines}"
        assert any(l.startswith("status: pass") for l in lines)
        assert any(l.startswith("exit_code: 0") for l in lines)
        assert any(l.startswith("tests_source: board-ticket") for l in lines)
        assert any(l.startswith("tests: orchestrator/tests/x.test.mjs") for l in lines)


class TestVenvPython:
    """Venv-first pytest interpreter selection (pass bars 1 and 2)."""

    def test_venv_python_used_when_present(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        marker = tmp_path / "stub-called"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
        )
        # Add an executable .venv/bin/python stub after the repo exists.
        venv_bin = repo / ".venv" / "bin"
        stub = venv_bin / "python"
        stub.parent.mkdir(parents=True)
        # Stub records it was called, then execs the real interpreter of this test process.
        stub.write_text(f'#!/bin/bash\necho {stub} >> {marker}\nexec {sys.executable} "$@"\n')
        stub.chmod(0o755)
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["exit_code"] == "0"
        assert receipt["tests_source"] == "python-convention"
        assert receipt["tests"] == "tests/test_py-ticket.py"
        assert receipt["python"] == str(repo / ".venv" / "bin" / "python")
        # The stub was actually invoked by the train.
        assert marker.exists()
        assert str(repo / ".venv" / "bin" / "python") in marker.read_text()
        assert (reports_root / ticket / "pytest.log").exists()

    def test_python3_used_when_no_venv(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
        )
        # No .venv in the fixture -> train falls back to python3.
        assert not (repo / ".venv").exists()
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["exit_code"] == "0"
        assert receipt["tests_source"] == "python-convention"
        assert receipt["tests"] == "tests/test_py-ticket.py"
        assert receipt["python"] == "python3"
        assert (reports_root / ticket / "pytest.log").exists()


class TestSuiteLock:
    """The train gate takes the box-wide suite lock around its test loop.

    Every case runs with a private SUITE_LOCK_ROOT under tmp_path, so nothing
    here touches the real lock at ~/.local/state/frood-workstation/suite-lock.
    """

    # (a) a pass writes suite_lock: held and suite_lock_wait_s: 0, and leaves held/ gone.
    def test_pass_writes_held_and_zero_wait(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
            copy_lock_lib=True,
        )
        slroot = tmp_path / "slroot"
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["suite_lock"] == "held"
        assert receipt["suite_lock_wait_s"] == "0"
        assert not (slroot / "held").exists()

    # (b) a failing test still releases (no held/ left afterwards).
    def test_failing_test_still_releases(self, tmp_path):
        ticket = "node-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        slroot = tmp_path / "slroot"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"orchestrator/tests/x.test.mjs": FAIL_NODE},
            untracked_files={
                ".opencode/board/tickets/node-ticket.json": (
                    '{"schema":1,"id":"node-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"orchestrator/tests/x.test.mjs"}]}'
                ),
            },
            copy_lock_lib=True,
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 1, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "test failure"
        assert not (slroot / "held").exists()

    # (c) held/ pre-created by a fake live holder: the train waits, then passes
    # once the holder is released, with suite_lock_wait_s >= 1.
    def test_waits_for_pre_created_holder(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
            copy_lock_lib=True,
        )
        slroot = tmp_path / "slroot"
        held = slroot / "held"
        held.mkdir(parents=True)
        (held / "owner").write_text(
            "train: fake live holder\npid 999, since now\ntoken fake-token\n"
        )

        stop = threading.Event()

        def beat():
            while not stop.is_set():
                try:
                    os.utime(held / "owner", None)
                except FileNotFoundError:
                    return
                time.sleep(0.2)

        beater = threading.Thread(target=beat, daemon=True)
        beater.start()
        outcome = {}

        def run_train_in_thread():
            outcome["res"] = run_train(
                repo,
                ticket,
                bin_dir,
                reports_root,
                env_extra={"SUITE_LOCK_POLL": "1", "SUITE_LOCK_STALE": "3"},
            )

        train_thread = threading.Thread(target=run_train_in_thread)
        train_thread.start()
        # Poll until the train has queued (a ticket file appears), then give
        # it ~2 s behind the live holder before releasing the holder. Polling
        # keeps the test deterministic under load instead of sleeping blindly.
        queued = False
        for _ in range(100):
            if any(slroot.glob("queue/*")):
                queued = True
                break
            time.sleep(0.05)
        assert queued, "train never queued behind the live holder"
        time.sleep(2.0)
        stop.set()
        beater.join(timeout=5)
        shutil.rmtree(held, ignore_errors=True)
        train_thread.join(timeout=60)
        assert "res" in outcome, "train did not return after releasing the holder"
        res = outcome["res"]

        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["suite_lock"] == "held"
        assert int(receipt["suite_lock_wait_s"]) >= 1, receipt
        assert not held.exists()

    # (d) FROOD_SUITE_LOCK_HELD=1: skipped, no held/ ever created.
    def test_frood_suite_lock_held_is_skipped(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
            copy_lock_lib=True,
        )
        slroot = tmp_path / "slroot"
        res = run_train(
            repo,
            ticket,
            bin_dir,
            reports_root,
            env_extra={"FROOD_SUITE_LOCK_HELD": "1"},
        )
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["suite_lock"] == "skipped (FROOD_SUITE_LOCK_HELD)"
        assert receipt["suite_lock_wait_s"] == "0"
        assert not (slroot / "held").exists()

    # Regression: an inherited FROOD_SUITE_LOCK_HELD=1 (from the calling pytest
    # process or `make test`) must NOT make train.sh skip the lock; run_train
    # pops it so a normal run still takes the lock and reports `held`.
    def test_inherited_frood_suite_lock_held_is_popped(self, tmp_path, monkeypatch):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        slroot = tmp_path / "slroot"
        monkeypatch.setenv("FROOD_SUITE_LOCK_HELD", "1")
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
            copy_lock_lib=True,
        )
        res = run_train(repo, ticket, bin_dir, reports_root)
        assert res.returncode == 0, res.stderr
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["suite_lock"] == "held"
        assert receipt["suite_lock_wait_s"] == "0"
        assert not (slroot / "held").exists()

    # (e) no lib at either path: unlocked (no lib), the stderr WARN line, and a pass.
    def test_no_lock_lib_unlocked_no_lib(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        fake_home = tmp_path / "home"
        fake_home.mkdir()
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
            copy_lock_lib=False,
        )
        res = run_train(repo, ticket, bin_dir, reports_root, env_extra={"HOME": str(fake_home)})
        assert res.returncode == 0, res.stderr
        assert (
            "train: WARN: suite-lock.sh not found — running the test gate without the box-wide lock"
            in res.stderr
        )
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["status"] == "pass"
        assert receipt["suite_lock"] == "unlocked (no lib)"
        assert receipt["suite_lock_wait_s"] == "0"

    # (f) a test child sees FROOD_SUITE_LOCK_HELD=1.
    def test_test_child_sees_frood_suite_lock_held(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        envfile = tmp_path / "envfile"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": LOCKENV_PY},
            copy_lock_lib=True,
        )
        res = run_train(
            repo,
            ticket,
            bin_dir,
            reports_root,
            env_extra={"TRAIN_FIXTURE_ENVFILE": str(envfile)},
        )
        assert res.returncode == 0, res.stderr
        assert envfile.read_text() == "1", envfile.read_text()
        receipt = parse_receipt(reports_root, ticket)
        assert receipt["suite_lock"] == "held"

    # (g) SIGTERM to train.sh while a test is running: exits 143, the test
    # child is gone, and held/ is gone.
    def test_sigterm_while_test_runs_exits_143(self, tmp_path):
        ticket = "sleep-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        slroot = tmp_path / "slroot"
        pidfile = tmp_path / "pidfile"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"z.sleep.test.mjs": SLEEP_NODE},
            untracked_files={
                ".opencode/board/tickets/sleep-ticket.json": (
                    '{"schema":1,"id":"sleep-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"z.sleep.test.mjs"}]}'
                ),
            },
            copy_lock_lib=True,
        )
        env = os.environ.copy()
        # Never leak an inherited FROOD_SUITE_LOCK_HELD/SUITE_LOCK into train.sh.
        env.pop("FROOD_SUITE_LOCK_HELD", None)
        env.pop("SUITE_LOCK", None)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        env["FROOD_REPORTS_ROOT"] = str(reports_root)
        env["SUITE_LOCK_ROOT"] = str(slroot)
        env["TRAIN_NODE_TIMEOUT"] = "600"
        env["TRAIN_FIXTURE_PIDFILE"] = str(pidfile)
        env["SUITE_LOCK_POLL"] = "1"
        env["SUITE_LOCK_STALE"] = "5"
        proc = subprocess.Popen(
            ["bash", "ops/train.sh", ticket],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Wait until the test child is running and the lock is held.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if pidfile.exists() and (slroot / "held").exists():
                break
            time.sleep(0.05)
        else:
            proc.kill()
            proc.wait(timeout=5)
            err = proc.stderr.read() if proc.stderr else ""
            raise AssertionError("train never reached the test child: " + err[:500])
        pid = int(pidfile.read_text())
        proc.terminate()  # SIGTERM
        rc = proc.wait(timeout=30)
        err = proc.stderr.read() if proc.stderr else ""
        assert rc == 143, f"expected exit 143, got {rc}: {err}"
        # The test child must be gone.
        dead = False
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                dead = True
                break
            except PermissionError:
                dead = True
                break
            time.sleep(0.1)
        assert dead, f"node child pid {pid} still alive after train.sh returned"
        # The lock must be released.
        assert not (slroot / "held").exists(), "held/ still present after SIGTERM"

    # (h) SIGTERM mid-wait (held/ live): exits 143 and leaves queue/ empty so
    # it cannot block every suite on the box for the stale window.
    def test_sigterm_mid_wait_empties_queue(self, tmp_path):
        ticket = "py-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        slroot = tmp_path / "slroot"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"tests/test_py-ticket.py": PASS_PY},
            copy_lock_lib=True,
        )
        # Fake live holder beats held/owner forever.
        held = slroot / "held"
        held.mkdir(parents=True)
        (held / "owner").write_text(
            "train: fake live holder\npid 999, since now\ntoken fake-token\n"
        )

        stop = threading.Event()

        def beat():
            while not stop.is_set():
                try:
                    os.utime(held / "owner", None)
                except FileNotFoundError:
                    return
                time.sleep(0.2)

        beater = threading.Thread(target=beat, daemon=True)
        beater.start()
        try:
            env = {
                "PATH": str(bin_dir) + os.pathsep + os.environ["PATH"],
                "FROOD_REPORTS_ROOT": str(reports_root),
                "SUITE_LOCK_ROOT": str(slroot),
                "SUITE_LOCK_POLL": "1",
                "SUITE_LOCK_STALE": "5",
            }
            proc = subprocess.Popen(
                ["bash", "ops/train.sh", ticket],
                cwd=repo,
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            # Wait until the train has queued (a ticket file appears).
            queued = False
            for _ in range(100):
                if any(slroot.glob("queue/*")):
                    queued = True
                    break
                time.sleep(0.05)
            assert queued, "train never queued behind the live holder"
            proc.terminate()  # SIGTERM mid-wait
            rc = proc.wait(timeout=30)
            err = proc.stderr.read() if proc.stderr else ""
            assert rc == 143, f"expected exit 143 mid-wait, got {rc}: {err}"
        finally:
            stop.set()
            beater.join(timeout=5)
            shutil.rmtree(held, ignore_errors=True)
        # No queue ticket may be left behind.
        assert not any(slroot.glob("queue/*")), "queue ticket left behind after mid-wait SIGTERM"
        assert not (slroot / "held").exists(), "held/ still present after mid-wait SIGTERM"

    # SIGHUP while a test is running: exit 129, the test child is gone, and
    # held/ is gone (SIGHUP also runs the EXIT trap, handled explicitly so the
    # child dies before release).
    @pytest.mark.skipif(
        signal.getsignal(signal.SIGHUP) == signal.SIG_IGN,
        reason="SIGHUP ignored on entry (e.g. nohup): bash cannot trap it, so the train correctly runs to completion",
    )
    def test_sighup_while_test_runs_exits_129(self, tmp_path):
        ticket = "sleep-ticket"
        bin_dir = tmp_path / "bin"
        make_stub_ruff(bin_dir)
        reports_root = tmp_path / "reports"
        slroot = tmp_path / "slroot"
        pidfile = tmp_path / "pidfile"
        repo = make_fixture(
            tmp_path,
            ticket,
            tracked_files={"z.sleep.test.mjs": SLEEP_NODE},
            untracked_files={
                ".opencode/board/tickets/sleep-ticket.json": (
                    '{"schema":1,"id":"sleep-ticket","stage":"working",'
                    '"blast_radius":[{"caller":"c","expect":"unchanged",'
                    '"test":"z.sleep.test.mjs"}]}'
                ),
            },
            copy_lock_lib=True,
        )
        env = os.environ.copy()
        # Never leak an inherited FROOD_SUITE_LOCK_HELD/SUITE_LOCK into train.sh.
        env.pop("FROOD_SUITE_LOCK_HELD", None)
        env.pop("SUITE_LOCK", None)
        env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
        env["FROOD_REPORTS_ROOT"] = str(reports_root)
        env["SUITE_LOCK_ROOT"] = str(slroot)
        env["TRAIN_NODE_TIMEOUT"] = "600"
        env["TRAIN_FIXTURE_PIDFILE"] = str(pidfile)
        env["SUITE_LOCK_POLL"] = "1"
        env["SUITE_LOCK_STALE"] = "5"
        proc = subprocess.Popen(
            ["bash", "ops/train.sh", ticket],
            cwd=repo,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        # Wait until the test child is running and the lock is held.
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if pidfile.exists() and (slroot / "held").exists():
                break
            time.sleep(0.05)
        else:
            proc.kill()
            proc.wait(timeout=5)
            err = proc.stderr.read() if proc.stderr else ""
            raise AssertionError("train never reached the test child: " + err[:500])
        pid = int(pidfile.read_text())
        proc.send_signal(signal.SIGHUP)
        rc = proc.wait(timeout=30)
        err = proc.stderr.read() if proc.stderr else ""
        assert rc == 129, f"expected exit 129, got {rc}: {err}"
        # The test child must be gone.
        dead = False
        for _ in range(50):
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                dead = True
                break
            except PermissionError:
                dead = True
                break
            time.sleep(0.1)
        assert dead, f"node child pid {pid} still alive after train.sh returned"
        # The lock must be released.
        assert not (slroot / "held").exists(), "held/ still present after SIGHUP"

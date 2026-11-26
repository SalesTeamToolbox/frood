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
import subprocess
import time
from pathlib import Path

FIXTURE_TRAIN_SH = Path(__file__).resolve().parents[1] / "ops" / "train.sh"


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


def make_fixture(tmp_path: Path, ticket: str, tracked_files=None, untracked_files=None):
    """Create a tmp git repo (`git init -b main`, local user config, one commit)
    holding a copy of ops/train.sh plus the case's test files.

    tracked_files / untracked_files: dict of rel_path -> content.
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
    for rel, content in tracked_files.items():
        _write(repo / rel, content)
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "fixture")
    for rel, content in untracked_files.items():
        _write(repo / rel, content)
    return repo


def run_train(repo: Path, ticket: str, bin_dir: Path, reports_root: Path, env_extra=None):
    """Run `bash ops/train.sh <ticket>` in the fixture with a stub ruff on PATH."""
    env = os.environ.copy()
    env["PATH"] = str(bin_dir) + os.pathsep + env["PATH"]
    env["FROOD_REPORTS_ROOT"] = str(reports_root)
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

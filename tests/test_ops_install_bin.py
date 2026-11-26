"""Tests for ops/install.mjs VENDORED manifest after root bin/ cleanup (M3).

Verifies:
- ``node ops/install.mjs --check`` exits 0 and prints ``check: OK``
- none of the 13 deleted root ``bin/`` files exists
- none of the 13 appears in ``VENDORED``
- README.md names ``orchestrator/bin/...`` for the three moved rows and no
  table row starts with ``| **`bin/``
"""

from __future__ import annotations

import subprocess
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

# The 13 root bin/ copies deleted in M3 (root-bin-cleanup).
DELETED_BIN = [
    "board.mjs",
    "check-routing.mjs",
    "desk.mjs",
    "handoff.mjs",
    "no-window.mjs",
    "oc-worker.mjs",
    "outcome.mjs",
    "pool-health.mjs",
    "proc-tree.mjs",
    "router-health.mjs",
    "session-title.mjs",
    "usage.mjs",
    "verdict-gate.mjs",
]


def _run_check() -> subprocess.CompletedProcess:
    return subprocess.run(
        ["node", "ops/install.mjs", "--check"],
        cwd=REPO,
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_install_check_ok():
    result = _run_check()
    assert result.returncode == 0, result.stderr
    assert "check: OK" in result.stdout, result.stdout + result.stderr


def test_deleted_bin_files_do_not_exist():
    """Fail-before: on base these 13 files exist, so this assertion fails."""
    for name in DELETED_BIN:
        assert not (REPO / "bin" / name).exists(), f"{name} should have been deleted"


def test_vendored_has_no_deleted_bin_entries():
    install_mjs = (REPO / "ops" / "install.mjs").read_text()
    for name in DELETED_BIN:
        assert f"bin/{name}" not in install_mjs, f"bin/{name} should be removed from VENDORED"


def test_readme_names_orchestrator_bin():
    readme = (REPO / "README.md").read_text()
    assert "orchestrator/bin/oc-worker.mjs" in readme
    assert "orchestrator/bin/board.mjs" in readme
    assert "orchestrator/bin/router-health.mjs" in readme
    for line in readme.splitlines():
        assert not line.startswith("| **`bin/"), f"README table row references root bin/: {line}"

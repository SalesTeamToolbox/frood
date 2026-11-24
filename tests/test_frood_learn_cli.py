"""CLI tests for bin/frood-learn.mjs (/frood-learn). Runs the real script via node."""

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPT = REPO / "bin" / "frood-learn.mjs"
WRAPPER = REPO / "bin" / "frood-learn"

pytestmark = pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")


def run(args, home, cwd=None, script=SCRIPT, extra_env=None):
    env = {**os.environ, "HOME": str(home), "USERPROFILE": str(home)}
    env.pop("OPENCODE_SESSION_ID", None)
    env.update(extra_env or {})
    return subprocess.run(
        ["node", str(script), *args],
        capture_output=True,
        text=True,
        cwd=str(cwd or home),
        env=env,
        timeout=60,
    )


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def fixture_home(tmp_path):
    """A HOME with a small desk-daemon log, one stream, one peer-mail file and one receipt."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "streams").mkdir()
    (orch / "peer-mail").mkdir()
    (orch / "desk-daemon" / "daemon.log").write_text(
        "\n".join(
            ["t1 verdict-failed ticket-a"] * 3
            + ["t2 worker-timeout ticket-b"] * 2
            + ["t3 desk restarted"] * 4
        )
        + "\n"
    )
    (orch / "streams" / "fx.json").write_text(
        json.dumps(
            {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"}
        )
    )
    (orch / "peer-mail" / "m.jsonl").write_text(
        "\n".join(json.dumps({"latency_ms": ms}) for ms in (100, 200, 300)) + "\n"
    )
    proj = home / "proj"
    rep = proj / ".opencode" / "reports" / "fx"
    rep.mkdir(parents=True)
    (rep / "worker-r1.md.receipt.json").write_text(
        json.dumps({"tokens": {"input": 400, "output": 300}, "seconds": 120, "max_silence_s": 30})
    )
    (rep / "critic-r1.md").write_text("verdict: APPROVED\n")
    (rep / "critic-r2.md").write_text("verdict: APPROVED\n")
    # The stream's own escalations, and its events pointing at its run dir (how a receipt maps to a stream).
    esc = [("fx", "verdict-failed /x/a.md")] * 3 + [("fx", "ESCALATE worker-timeout /x/b.md")] * 2
    esc += [("fx", "ESCALATE worker-no_pool /x/c.md")]
    # Another stream's escalations and receipt: a review of fx must count none of them.
    esc += [("other", "ESCALATE worker-error /y/d.md")] * 5 + [
        ("other", "verdict-failed /y/e.md")
    ] * 4
    (orch / "desk-daemon" / "escalations.jsonl").write_text(
        "\n".join(json.dumps({"stream": s, "key": "k", "reason": r}) for s, r in esc) + "\n"
    )
    (orch / "streams" / "fx.events.jsonl").write_text(
        json.dumps(
            {"key": "run:fx/worker-r1:done", "kind": "run-done", "out": str(rep / "worker-r1.md")}
        )
        + "\n"
    )
    other = proj / ".opencode" / "reports" / "other-ticket"
    other.mkdir(parents=True)
    (other / "worker-r1.md.receipt.json").write_text(
        json.dumps(
            {"tokens": {"input": 9000, "output": 9000}, "seconds": 999, "max_silence_s": 600}
        )
    )
    return home, proj


def _report(home, proj, phase, name="out.json"):
    out = home / name
    r = run(["fx", "--phase", str(phase), "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def test_help_lists_phases(tmp_path):
    r = run(["--help"], tmp_path)
    assert r.returncode == 0
    for n in "12345":
        assert f"  {n}  " in r.stdout


def test_bad_phase_exits_nonzero(tmp_path):
    r = run(["fx", "--phase", "9"], tmp_path)
    assert r.returncode != 0
    assert "--phase must be" in r.stderr


def test_phase1_findings_reflect_fixture(fixture_home):
    home, proj = fixture_home
    rep = _report(home, proj, 1)
    details = {f["focus"]: f for f in rep["findings"]}
    assert "median 200ms" in details["message latency"]["detail"]
    assert "across 3 messages" in details["message latency"]["detail"]
    assert "4 desk daemon log line" in details["desk daemon stability"]["detail"]
    assert "2 critic round file" in details["worker-critic round efficiency"]["detail"]
    # No unmeasured claim is labelled as session data.
    for f in rep["findings"]:
        if f["source"] == "session-data":
            assert "drift observed" not in f["detail"]


def test_phase2_findings_reflect_fixture(fixture_home):
    home, proj = fixture_home
    rep = _report(home, proj, 2)
    text = {f["focus"]: f["detail"] for f in rep["findings"]}
    assert text["verdict failed"].startswith("3 occurrences")
    assert text["worker timeout"].startswith("2 occurrences")
    all_details = [f["detail"] for f in rep["findings"]]
    assert any(
        "Analyzed 1 worker receipts: 700 tokens, 120s total, max silence 30s" in d
        for d in all_details
    )
    assert any("2 critic round file" in d for d in all_details)


def test_phase2_counts_only_the_reviewed_stream(fixture_home):
    """Another stream's escalations and receipts never leak into this stream's review."""
    home, proj = fixture_home
    rep = _report(home, proj, 2)
    text = {f["focus"]: f["detail"] for f in rep["findings"]}
    assert text["verdict failed"].startswith("3 occurrences"), "the other stream's 4 are not added"
    assert "worker error" not in text, "worker-error happened only on the other stream"
    assert text["worker no pool"].startswith("1 occurrences"), "no_pool escalations are counted"
    assert 'on stream "fx"' in text["verdict failed"]
    assert all("9000" not in f["detail"] and "999s" not in f["detail"] for f in rep["findings"])


def test_phase3_no_invented_numbers(fixture_home):
    home, proj = fixture_home
    rep = _report(home, proj, 3)
    by_focus = {f["focus"]: f for f in rep["findings"]}
    depth = by_focus["subagent orchestration depth"]
    assert depth["source"] == "heuristic"
    assert "2.3" not in depth["detail"]
    assert "Avg worker time: 2.0m" in by_focus["end-to-end cycle time"]["detail"]
    assert "2 critic round file" in by_focus["critic round efficiency"]["detail"]


def test_propose_without_api_fails_cleanly(fixture_home):
    home, proj = fixture_home
    port = _free_port()
    r = run(
        ["fx", "--phase", "2", "--no-mcp", "--propose", "--report", str(home / "p.json")],
        home,
        cwd=proj,
        extra_env={"FROOD_API_URL": f"http://127.0.0.1:{port}"},
    )
    assert r.returncode != 0
    assert "community PR API is not deployed in this Frood; proposal not sent" in r.stderr
    assert "at " not in r.stderr.replace("at least", "")  # no stack trace


def test_propose_with_no_findings_sends_nothing(tmp_path):
    port = _free_port()
    r = run(
        ["s1", "--phase", "1", "--no-mcp", "--propose", "--report", str(tmp_path / "e.json")],
        tmp_path,
        extra_env={"FROOD_API_URL": f"http://127.0.0.1:{port}"},
    )
    assert r.returncode != 0
    assert "no findings eligible to propose; nothing sent" in r.stderr
    assert "frood-learn failed" not in r.stderr


def test_wrapper_works_through_symlink(tmp_path):
    link = tmp_path / "frood-learn-link"
    link.symlink_to(WRAPPER)
    r = run(["--help"], tmp_path, script=link)
    assert r.returncode == 0
    assert "Phases:" in r.stdout

"""CLI tests for bin/frood-learn.mjs (/frood-learn). Runs the real script via node."""

import datetime
import json
import os
import re
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


# ---------------------------------------------------------------------------
# learn-runs: per-run opencode join (start delay, after-kill, long tool calls)
# ---------------------------------------------------------------------------


def _epoch_ms(iso):
    return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp() * 1000)


def _build_learn_runs_fixture(home):
    """Build a HOME with opencode.db + a stream whose events join runs to sessions."""
    import sqlite3

    orch = home / ".config" / "orchestrator"
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "streams").mkdir()
    db_dir = home / ".local" / "share" / "opencode"
    db_dir.mkdir(parents=True)
    db_path = db_dir / "opencode.db"

    con = sqlite3.connect(db_path)
    cur = con.cursor()
    cur.execute(
        "CREATE TABLE session_message("
        "id text PRIMARY KEY, session_id text NOT NULL, type text NOT NULL, "
        "seq integer NOT NULL, time_created integer NOT NULL, time_updated integer NOT NULL, data text NOT NULL)"
    )
    cur.execute(
        "CREATE TABLE session_part("
        "message_id text NOT NULL, session_id text NOT NULL, ordinal integer NOT NULL, "
        "type text NOT NULL, call_id text, time_created integer NOT NULL, "
        "time_updated integer NOT NULL, data text NOT NULL)"
    )
    con.commit()

    stream = "lr"
    (orch / "streams" / f"{stream}.json").write_text(
        json.dumps(
            {"name": stream, "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"}
        )
    )

    def part_data(name, command, created_ms, completed_ms=None):
        call_id = "call-" + name
        payload = {
            "type": "tool",
            "id": call_id,
            "name": name,
            "state": {
                "status": "completed" if completed_ms is not None else "running",
                "input": {"command": command},
                "time": {
                    "created": created_ms,
                    **({"completed": completed_ms} if completed_ms is not None else {}),
                },
            },
        }
        return json.dumps(payload)

    return con, cur, stream, db_path, part_data


def _write_stream_events(orch, stream, events):
    (orch / "streams" / f"{stream}.events.jsonl").write_text(
        "\n".join(json.dumps(e) for e in events) + "\n"
    )


def _report_phase2(home, stream="lr", name="out.json"):
    out = home / name
    r = run([stream, "--phase", "2", "--no-mcp", "--report", str(out)], home, cwd=home)
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def test_learn_runs_start_delay_finding(tmp_path):
    home = tmp_path / "home"
    con, cur, stream, db_path, part_data = _build_learn_runs_fixture(home)
    orch = home / ".config" / "orchestrator"

    queued_iso = "2026-11-24T15:14:00Z"
    queued_ms = _epoch_ms(queued_iso)
    done_iso = "2026-11-24T16:43:00Z"
    done_ms = _epoch_ms(done_iso)
    session = "ses_delay"

    # First session message 30 min after queued.
    cur.execute(
        "INSERT INTO session_message(id, session_id, type, seq, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?)",
        ("m1", session, "user", 1, queued_ms + 30 * 60 * 1000, queued_ms + 30 * 60 * 1000, "{}"),
    )
    con.commit()

    _write_stream_events(
        orch,
        stream,
        [
            {
                "key": f"run:{stream}/r1:queued",
                "kind": "queued",
                "at": queued_iso,
                "run": f"{stream}/r1",
                "out": "out1",
            },
            {
                "key": f"run:{stream}/r1:done",
                "kind": "run-done",
                "at": done_iso,
                "run": f"{stream}/r1",
                "outcome": "timeout",
                "exit": 1,
                "session": session,
            },
        ],
    )

    rep = _report_phase2(home, stream)
    details = {f["focus"]: f["detail"] for f in rep["findings"]}
    sd = details.get("start delay", "")
    assert "waited 30 min before opencode got its prompt" in sd, sd


def test_learn_runs_after_kill_finding(tmp_path):
    home = tmp_path / "home"
    con, cur, stream, db_path, part_data = _build_learn_runs_fixture(home)
    orch = home / ".config" / "orchestrator"

    done_iso = "2026-11-24T16:43:00Z"
    done_ms = _epoch_ms(done_iso)
    session = "ses_kill"
    five_after = done_ms + 5 * 60 * 1000

    # Three tool parts 5 min after run-done; one is a shell git commit.
    cur.execute(
        "INSERT INTO session_message(id, session_id, type, seq, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?)",
        ("m1", session, "user", 1, done_ms - 60000, done_ms - 60000, "{}"),
    )
    cur.execute(
        "INSERT INTO session_part(message_id, session_id, ordinal, type, call_id, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?,?)",
        (
            "m1",
            session,
            1,
            "tool",
            "c1",
            five_after,
            five_after,
            part_data("shell", "echo hi", five_after, five_after),
        ),
    )
    cur.execute(
        "INSERT INTO session_part(message_id, session_id, ordinal, type, call_id, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?,?)",
        (
            "m1",
            session,
            2,
            "tool",
            "c2",
            five_after + 1000,
            five_after + 1000,
            part_data("shell", "cd /wt && git commit -m x", five_after + 1000, five_after + 1000),
        ),
    )
    cur.execute(
        "INSERT INTO session_part(message_id, session_id, ordinal, type, call_id, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?,?)",
        (
            "m1",
            session,
            3,
            "tool",
            "c3",
            five_after + 2000,
            five_after + 2000,
            part_data("shell", "npm test", five_after + 2000, five_after + 2000),
        ),
    )
    con.commit()

    _write_stream_events(
        orch,
        stream,
        [
            {
                "key": f"run:{stream}/r1:queued",
                "kind": "queued",
                "at": "2026-11-24T15:14:00Z",
                "run": f"{stream}/r1",
                "out": "out1",
            },
            {
                "key": f"run:{stream}/r1:done",
                "kind": "run-done",
                "at": done_iso,
                "run": f"{stream}/r1",
                "outcome": "timeout",
                "exit": 1,
                "session": session,
            },
        ],
    )

    rep = _report_phase2(home, stream)
    details = {f["focus"]: f["detail"] for f in rep["findings"]}
    ak = details.get("after-kill activity", "")
    assert "agent kept working" in ak and "3 tool calls" in ak and "git commit" in ak, ak


def test_learn_runs_after_kill_resume_not_counted(tmp_path):
    """Parts after a later queued resume of the same session are NOT after-kill."""
    home = tmp_path / "home"
    con, cur, stream, db_path, part_data = _build_learn_runs_fixture(home)
    orch = home / ".config" / "orchestrator"

    done_iso = "2026-11-24T16:43:00Z"
    done_ms = _epoch_ms(done_iso)
    resume_iso = "2026-11-24T17:00:00Z"
    resume_ms = _epoch_ms(resume_iso)
    session = "ses_resume"
    after_resume = resume_ms + 2 * 60 * 1000

    cur.execute(
        "INSERT INTO session_message(id, session_id, type, seq, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?)",
        ("m1", session, "user", 1, done_ms - 60000, done_ms - 60000, "{}"),
    )
    cur.execute(
        "INSERT INTO session_part(message_id, session_id, ordinal, type, call_id, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?,?)",
        (
            "m1",
            session,
            1,
            "tool",
            "c1",
            after_resume,
            after_resume,
            part_data("shell", "echo resumed", after_resume, after_resume),
        ),
    )
    con.commit()

    _write_stream_events(
        orch,
        stream,
        [
            {
                "key": f"run:{stream}/r1:queued",
                "kind": "queued",
                "at": "2026-11-24T15:14:00Z",
                "run": f"{stream}/r1",
                "out": "out1",
            },
            {
                "key": f"run:{stream}/r1:done",
                "kind": "run-done",
                "at": done_iso,
                "run": f"{stream}/r1",
                "outcome": "timeout",
                "exit": 1,
                "session": session,
            },
            # A later queued resume naming the same session bounds the after-kill window.
            {
                "key": f"run:{stream}/r2:queued",
                "kind": "queued",
                "at": resume_iso,
                "run": f"{stream}/r2",
                "out": "out2",
                "session": session,
            },
        ],
    )

    rep = _report_phase2(home, stream)
    details = {f["focus"]: f["detail"] for f in rep["findings"]}
    assert "after-kill activity" not in details, details


def test_learn_runs_long_tool_finding(tmp_path):
    home = tmp_path / "home"
    con, cur, stream, db_path, part_data = _build_learn_runs_fixture(home)
    orch = home / ".config" / "orchestrator"

    done_iso = "2026-11-24T16:43:00Z"
    done_ms = _epoch_ms(done_iso)
    session = "ses_long"
    start = done_ms - 20 * 60 * 1000
    end = start + 10 * 60 * 1000  # 10 min shell part

    cur.execute(
        "INSERT INTO session_message(id, session_id, type, seq, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?)",
        ("m1", session, "user", 1, start - 60000, start - 60000, "{}"),
    )
    cur.execute(
        "INSERT INTO session_part(message_id, session_id, ordinal, type, call_id, time_created, time_updated, data) VALUES(?,?,?,?,?,?,?,?)",
        (
            "m1",
            session,
            1,
            "tool",
            "c1",
            start,
            end,
            part_data(
                "shell", "cd /tmp && node --test orchestrator/tests/ 2>&1 | tail -60", start, end
            ),
        ),
    )
    con.commit()

    _write_stream_events(
        orch,
        stream,
        [
            {
                "key": f"run:{stream}/r1:queued",
                "kind": "queued",
                "at": "2026-11-24T15:14:00Z",
                "run": f"{stream}/r1",
                "out": "out1",
            },
            {
                "key": f"run:{stream}/r1:done",
                "kind": "run-done",
                "at": done_iso,
                "run": f"{stream}/r1",
                "outcome": "timeout",
                "exit": 1,
                "session": session,
            },
        ],
    )

    rep = _report_phase2(home, stream)
    details = {f["focus"]: f["detail"] for f in rep["findings"]}
    lt = details.get("long tool call", "")
    assert "ran 10 min" in lt, lt


def test_learn_runs_no_db_unchanged(tmp_path):
    """No opencode.db at all → phase 2 output identical to today's fixture (no new findings, no crash)."""
    home = tmp_path / "home"
    # Deliberately do NOT create opencode.db.
    orch = home / ".config" / "orchestrator"
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "streams").mkdir()
    (orch / "streams" / "lr.json").write_text(
        json.dumps(
            {"name": "lr", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"}
        )
    )
    (orch / "streams" / "lr.events.jsonl").write_text(
        json.dumps(
            {
                "key": "run:lr/r1:queued",
                "kind": "queued",
                "at": "2026-11-24T15:14:00Z",
                "run": "lr/r1",
                "out": "out1",
            }
        )
        + "\n"
        + json.dumps(
            {
                "key": "run:lr/r1:done",
                "kind": "run-done",
                "at": "2026-11-24T16:43:00Z",
                "run": "lr/r1",
                "outcome": "timeout",
                "exit": 1,
                "session": "ses_x",
            }
        )
        + "\n"
    )

    rep = _report_phase2(home, "lr")
    focuses = {f["focus"] for f in rep["findings"]}
    assert "start delay" not in focuses
    assert "after-kill activity" not in focuses
    assert "long tool call" not in focuses


def test_wrapper_works_through_symlink(tmp_path):
    link = tmp_path / "frood-learn-link"
    link.symlink_to(WRAPPER)
    r = run(["--help"], tmp_path, script=link)
    assert r.returncode == 0
    assert "Phases:" in r.stdout


# ------------------------------------------------------------------ children fixtures

FIXTURES = REPO / "tests" / "fixtures" / "frood_learn"


@pytest.fixture
def fixture_children_home(tmp_path):
    """A HOME whose stream fx has three children:
    - 1 OpenCode worker (ses_ id on a stream event, opencode.db transcript)
    - 1 Claude Code subagent (agent-*.jsonl under the orchestrator session's subagents/)
    - 1 nested Claude Code session (top-level .jsonl recorded via a child event)
    """
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "peer-mail").mkdir()
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    (orch / "streams" / "fx.json").write_text(
        json.dumps(
            {
                "name": "fx",
                "status": "active",
                "waiting": "",
                "next": "2020-01-01T00:00:00Z",
                "held_session": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            }
        )
    )
    # Stream events: one OpenCode run-done carrying a ses_ id, plus a child event for a nested CC session.
    (orch / "streams" / "fx.events.jsonl").write_text(
        "\n".join(
            [
                json.dumps(
                    {
                        "key": "run:fx/worker-r1:done",
                        "kind": "run-done",
                        "run": "worker-r1",
                        "out": "/x/worker-r1.md",
                        "agent": "worker",
                        "session": "ses_fixture_oc",
                        "model": "opencode-go/mimo-v2.6-flash",
                        "at": "2026-01-01T00:00:00Z",
                    }
                ),
                json.dumps(
                    {
                        "key": "child:fx:sess_fixture_nested",
                        "event": "child",
                        "session": "sess_fixture_nested",
                        "harness": "claude-code",
                        "role": "nested",
                        "ts": "2026-01-01T00:00:00Z",
                    }
                ),
            ]
        )
        + "\n"
    )
    # OpenCode database with the ses_fixture_oc session (built here, not shipped as
    # a committed .db fixture, which public-guard forbids).
    oc_db_dir = home / ".local" / "share" / "opencode"
    oc_db_dir.mkdir(parents=True)
    oc_db = oc_db_dir / "opencode.db"
    assistant = json.dumps(
        {
            "content": [{"text": "I hit an error reading the file"}, {"text": "more text"}],
            "snapshot": {"files": ["/workspace/bin/frood-learn.mjs", "/workspace/README.md"]},
            "finish": "tool-calls",
        }
    )
    shell = json.dumps({"text": "npm install"})
    userp = json.dumps({"text": "fix the error"})
    sql = (
        "CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, time_created INTEGER, time_updated INTEGER);\n"
        "CREATE TABLE session_message (id INTEGER PRIMARY KEY AUTOINCREMENT, session_id TEXT, type TEXT, data TEXT, seq INTEGER, time_created INTEGER);\n"
        f"INSERT INTO session_v2 VALUES ('ses_fixture_oc','Fixture OC worker',1700000000000,1700000300000);\n"
        f"INSERT INTO session_message (session_id,type,data,seq,time_created) VALUES ('ses_fixture_oc','assistant',json('{assistant}'),1,1700000050000);\n"
        f"INSERT INTO session_message (session_id,type,data,seq,time_created) VALUES ('ses_fixture_oc','shell',json('{shell}'),2,1700000100000);\n"
        f"INSERT INTO session_message (session_id,type,data,seq,time_created) VALUES ('ses_fixture_oc','user',json('{userp}'),3,1700000200000);\n"
    )
    subprocess.run(["sqlite3", str(oc_db)], input=sql, text=True, check=True)
    # Claude Code subagents under the orchestrator session's subagents/ folder.
    # Two subagents share one sessionId (sess_orch_01, the parent's id) but have
    # distinct agentIds -> they must surface as two children keyed by agentId.
    cc_sub = (
        home
        / ".claude"
        / "projects"
        / "frood"
        / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        / "subagents"
    )
    cc_sub.mkdir(parents=True)
    shutil.copyfile(FIXTURES / "agent-scout.jsonl", cc_sub / "agent-scout.jsonl")
    shutil.copyfile(FIXTURES / "agent-scout.meta.json", cc_sub / "agent-scout.meta.json")
    shutil.copyfile(FIXTURES / "agent-critic.jsonl", cc_sub / "agent-critic.jsonl")
    shutil.copyfile(FIXTURES / "agent-critic.meta.json", cc_sub / "agent-critic.meta.json")
    # The orchestrator session itself is also a claimant (held_session) whose own
    # top-level transcript is reviewed as role `orchestrator`.
    orch_transcript = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "orchestrator session work"}],
        },
        "timestamp": "2026-01-01T00:00:00.000Z",
        "sessionId": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
    }
    (
        home / ".claude" / "projects" / "frood" / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee.jsonl"
    ).write_text(json.dumps(orch_transcript) + "\n")
    # Nested Claude Code session as a top-level .jsonl file.
    cc_proj = home / ".claude" / "projects" / "frood"
    cc_proj.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(FIXTURES / "sess_fixture_nested.jsonl", cc_proj / "sess_fixture_nested.jsonl")
    proj = home / "proj"
    proj.mkdir(parents=True)
    return home, proj


# ------------------------------------------------------------------ children tests


def test_default_run_lists_all_children(fixture_children_home):
    """Default run lists the OC child, two CC subagents (shared sessionId,
    distinct agentIds) and the CC nested child, each with phase-5 findings
    tagged role/harness/model/session."""
    home, proj = fixture_children_home
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    assert len(children) == 5, children
    by_session = {c["session"]: c for c in children}

    # The orchestrator session (held_session) is a claimant: role orchestrator,
    # harness claude-code, its own transcript reviewed.
    orch = by_session["aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"]
    assert orch["role"] == "orchestrator", orch
    assert orch["harness"] == "claude-code", orch
    assert orch["status"] == "analyzed", orch
    assert orch["model"] == "claude-opus-4-5", orch
    for f in orch["findings"]:
        assert f["role"] == "orchestrator", f
        assert f["harness"] == "claude-code", f
        assert f["session"] == "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", f

    # OpenCode worker child (model resolved from the run-done event).
    oc = by_session["ses_fixture_oc"]
    assert oc["harness"] == "opencode"
    assert oc["role"] == "worker"
    assert oc["status"] == "analyzed"
    assert oc["note"] is None
    assert oc["model"] == "opencode-go/mimo-v2.6-flash", oc
    assert any(f["lens"] == "session-summary" for f in oc["findings"]), oc["findings"]
    for f in oc["findings"]:
        assert f["role"] == "worker"
        assert f["harness"] == "opencode"
        assert f["session"] == "ses_fixture_oc"

    # Claude Code subagent 1 (scout): id is agentId (sessionId is the parent's),
    # role/model from the sibling .meta.json, Read-only transcript -> 0 files
    # modified, 2 Bash shell commands.
    scout = by_session["agent_scout_01"]
    assert scout["harness"] == "claude-code"
    assert scout["role"] == "scout", scout
    assert scout["status"] == "analyzed"
    assert scout["model"] == "claude-3-5-sonnet-20241022", scout
    assert scout["transcriptCopied"] is True
    ss = next(f for f in scout["findings"] if f["lens"] == "session-summary")
    turns = re.search(r"(\d+) agent turns", ss["detail"])
    assert turns and int(turns.group(1)) >= 1, ss["detail"]
    assert "claude-3-5-sonnet-20241022" in ss["detail"], ss["detail"]
    assert "0 files modified" in ss["detail"], ss["detail"]
    assert "2 shell commands" in ss["detail"], ss["detail"]
    for f in scout["findings"]:
        assert f["role"] == "scout"
        assert f["harness"] == "claude-code"
        assert f["session"] == "agent_scout_01"

    # Claude Code subagent 2 (critic): same sessionId as the scout, distinct
    # agentId -> a separate child. Edit transcript -> 1 file modified, 1 shell
    # command; model comes from the transcript (meta model ignored).
    critic = by_session["agent_critic_01"]
    assert critic["harness"] == "claude-code"
    assert critic["role"] == "critic", critic
    assert critic["status"] == "analyzed"
    assert critic["model"] == "claude-sonnet-5-5", critic
    assert critic["transcriptCopied"] is True
    cs = next(f for f in critic["findings"] if f["lens"] == "session-summary")
    assert "1 files modified" in cs["detail"], cs["detail"]
    assert "1 shell commands" in cs["detail"], cs["detail"]
    lc = next(f for f in critic["findings"] if f["lens"] == "local-code-changes")
    assert "/workspace/review.md" in lc["detail"], lc["detail"]
    for f in critic["findings"]:
        assert f["role"] == "critic"
        assert f["harness"] == "claude-code"
        assert f["session"] == "agent_critic_01"

    # Nested Claude Code session child.
    nn = by_session["sess_fixture_nested"]
    assert nn["harness"] == "claude-code"
    assert nn["role"] == "nested"
    assert nn["status"] == "analyzed"
    assert nn["model"] == "claude-opus-4-5", nn
    assert nn["transcriptCopied"] is True
    for f in nn["findings"]:
        assert f["role"] == "nested"
        assert f["harness"] == "claude-code"
        assert f["session"] == "sess_fixture_nested"

    # Stream-level findings are unchanged (still present).
    assert rep["findings"], "stream-level findings should still be present"


def test_desktop_local_id_child_resolves_via_app_metadata(fixture_children_home):
    """A nested child recorded with the desktop app's local_ id (what start_session returns) is found
    through the app's metadata file, whose cliSessionId is the transcript id."""
    home, proj = fixture_children_home
    events = home / ".config" / "orchestrator" / "streams" / "fx.events.jsonl"
    lines = events.read_text().replace("sess_fixture_nested", "local_fixture-desktop")
    events.write_text(lines)
    meta_dir = home / "desktop-sessions" / "acct" / "org"
    meta_dir.mkdir(parents=True)
    (meta_dir / "local_fixture-desktop.json").write_text(
        json.dumps({"sessionId": "local_fixture-desktop", "cliSessionId": "sess_fixture_nested"})
    )
    out = home / "out.json"
    env = {"CLAUDE_DESKTOP_SESSIONS_DIR": str(home / "desktop-sessions")}
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj, extra_env=env)
    assert r.returncode == 0, r.stderr
    by_session = {c["session"]: c for c in json.loads(out.read_text())["children"]}
    nn = by_session["local_fixture-desktop"]
    assert nn["status"] == "analyzed", nn
    assert nn["role"] == "nested"

    # Metadata gone: listed as missing with a note that says why, never "undefined".
    (meta_dir / "local_fixture-desktop.json").unlink()
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj, extra_env=env)
    assert r.returncode == 0, r.stderr
    nn = {c["session"]: c for c in json.loads(out.read_text())["children"]}["local_fixture-desktop"]
    assert nn["status"] == "missing", nn
    assert "undefined" not in nn["note"] and "metadata not found" in nn["note"], nn["note"]


def test_child_missing_transcript_status_missing_exits_zero(fixture_children_home):
    """A child id with no transcript is listed with status missing; exit 0, no crash."""
    home, proj = fixture_children_home
    # Add a child event pointing at a session that has no transcript anywhere.
    events = home / ".config" / "orchestrator" / "streams" / "fx.events.jsonl"
    with events.open("a") as fh:
        fh.write(
            json.dumps(
                {
                    "key": "child:fx:ses_ghost",
                    "event": "child",
                    "session": "ses_ghost",
                    "harness": "opencode",
                    "role": "worker",
                    "ts": "2026-01-01T00:00:00Z",
                }
            )
            + "\n"
        )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    ghost = by_session["ses_ghost"]
    assert ghost["status"] == "missing", ghost
    assert ghost["note"], "missing child needs a one-line note"
    assert ghost["findings"] == []


def test_cc_child_zero_turns_reports_empty_not_analyzed(fixture_children_home):
    """A Claude Code transcript that parses to zero turns is reported as
    `status: "empty"` with a note, not as a clean `analyzed` with no note."""
    home, proj = fixture_children_home
    cc_sub = (
        home
        / ".claude"
        / "projects"
        / "frood"
        / "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        / "subagents"
    )
    (cc_sub / "agent-empty.jsonl").write_text(
        json.dumps(
            {
                "type": "user",
                "message": {"role": "user", "content": "only a prompt, no assistant turn"},
                "timestamp": "2026-01-01T00:00:00.000Z",
                "sessionId": "sess_subagent_empty",
                "agentId": "sess_subagent_empty",
            }
        )
        + "\n"
    )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    empty = by_session["sess_subagent_empty"]
    assert empty["status"] == "empty", empty
    assert empty["note"], "empty child needs a one-line note"
    assert empty["findings"] == [], empty


def test_no_children_output_matches_today(fixture_children_home):
    """--no-children omits the children section (output matches today's default)."""
    home, proj = fixture_children_home
    out_with = home / "with.json"
    out_without = home / "without.json"
    r1 = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out_with)], home, cwd=proj)
    r2 = run(
        ["fx", "--phase", "1", "--no-mcp", "--no-children", "--report", str(out_without)],
        home,
        cwd=proj,
    )
    assert r1.returncode == 0, r1.stderr
    assert r2.returncode == 0, r2.stderr
    rep_with = json.loads(out_with.read_text())
    rep_without = json.loads(out_without.read_text())
    assert len(rep_with.get("children") or []) == 5
    assert "children" not in rep_without, "children section must be omitted with --no-children"
    assert rep_with["findings"] == rep_without["findings"], "stream-level findings identical"


def test_session_phase5_unchanged(fixture_children_home):
    """--session <ses_...> (phase 5) still analyzes a single OpenCode session and
    does not emit a children section."""
    home, proj = fixture_children_home
    out = home / "out.json"
    r = run(
        ["--phase", "5", "--session", "ses_fixture_oc", "--no-mcp", "--report", str(out)],
        home,
        cwd=proj,
    )
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    assert "children" not in rep
    assert rep["findings"], "phase 5 should still produce findings"
    for f in rep["findings"]:
        assert "role" not in f, "phase-5 findings are not child-tagged"


# ------------------------------------------------------------------ nested session id handling (C.1)


def _cc_transcript(home, project_slug, session_id, lines):
    """Write a Claude Code top-level transcript <session_id>.jsonl and return its path."""
    proj = home / ".claude" / "projects" / project_slug
    proj.mkdir(parents=True, exist_ok=True)
    p = proj / f"{session_id}.jsonl"
    p.write_text("".join(json.dumps(l) + "\n" for l in lines))
    return p


def _cc_subagents(home, project_slug, orch_session_id, agents):
    """Write agent-*.jsonl (+ meta) under <project>/<orch_session_id>/subagents/."""
    sub = home / ".claude" / "projects" / project_slug / orch_session_id / "subagents"
    sub.mkdir(parents=True, exist_ok=True)
    for name, body, meta in agents:
        (sub / f"agent-{name}.jsonl").write_text("".join(json.dumps(l) + "\n" for l in body))
        if meta:
            (sub / f"agent-{name}.meta.json").write_text(json.dumps(meta))


def _write_stream(orch, name, state, events=None):
    (orch / "streams" / f"{name}.json").write_text(json.dumps(state) + "\n")
    if events is not None:
        (orch / "streams" / f"{name}.events.jsonl").write_text(
            "\n".join(json.dumps(e) for e in events) + "\n"
        )


def test_local_id_child_is_missing_note_and_transcript_id_reviewed(tmp_path):
    """C.1: a `child` event whose session is a desktop-app `local_...` id is
    `missing` with the note; the same session recorded with its transcript id is reviewed."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"},
        [
            {
                "key": "child:fx:local_xyz",
                "event": "child",
                "session": "local_xyz",
                "harness": "claude-code",
                "role": "nested",
                "ts": "2026-01-01T00:00:00Z",
            },
            {
                "key": "child:fx:sess_nested",
                "event": "child",
                "session": "sess_nested",
                "harness": "claude-code",
                "role": "nested",
                "ts": "2026-01-01T00:00:00Z",
            },
        ],
    )
    assistant = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "nested work done"}],
        },
        "timestamp": "2026-01-01T00:10:00.000Z",
        "sessionId": "sess_nested",
    }
    _cc_transcript(home, "frood", "sess_nested", [assistant])

    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    local = by_session["local_xyz"]
    assert local["status"] == "missing", local
    # No desktop-app metadata for local_xyz (resolveDesktopSessionId finds none): missing, with the reason.
    assert "metadata not found" in local["note"], local["note"]
    nested = by_session["sess_nested"]
    assert nested["status"] == "analyzed", nested
    assert nested["role"] == "nested", nested


def test_done_stream_claim_event_reviews_claimant_and_subagents(tmp_path):
    """C.2: a done stream (held_session null) with a claim event reviews the
    claimant's transcript as orchestrator and collects its subagents."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {
            "name": "fx",
            "status": "done",
            "waiting": "",
            "next": "",
            "held_session": None,
            "session": None,
            "repo": str(proj),
        },
        [
            {
                "key": "claim:fx:cccccccc-dddd-eeee-ffff-111111111111",
                "event": "claim",
                "session": "cccccccc-dddd-eeee-ffff-111111111111",
                "by": "cc",
                "at": "2026-01-01T00:00:00Z",
            },
        ],
    )
    assistant = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "claimant work"}],
        },
        "timestamp": "2026-01-01T00:10:00.000Z",
        "sessionId": "cccccccc-dddd-eeee-ffff-111111111111",
    }
    _cc_transcript(home, "frood", "cccccccc-dddd-eeee-ffff-111111111111", [assistant])
    _cc_subagents(
        home,
        "frood",
        "cccccccc-dddd-eeee-ffff-111111111111",
        [
            (
                "scout",
                [
                    {
                        "type": "assistant",
                        "message": {
                            "model": "claude-3-5-sonnet-20241022",
                            "role": "assistant",
                            "content": [{"type": "text", "text": "scouting"}],
                        },
                        "timestamp": "2026-01-01T00:00:00.000Z",
                        "sessionId": "cccccccc-dddd-eeee-ffff-111111111111",
                        "agentId": "agent_scout_01",
                    }
                ],
                {"agentType": "scout", "model": "claude-3-5-sonnet-20241022"},
            ),
        ],
    )

    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    claimant = by_session["cccccccc-dddd-eeee-ffff-111111111111"]
    assert claimant["role"] == "orchestrator", claimant
    assert claimant["harness"] == "claude-code", claimant
    assert claimant["status"] == "analyzed", claimant
    scout = by_session["agent_scout_01"]
    assert scout["role"] == "scout", scout
    assert scout["status"] == "analyzed", scout


def test_done_stream_board_ticket_uuid_history_reviews_claimant(tmp_path):
    """C.3: a done stream with no claim events but a board ticket fixture whose
    history has claim/attach by a UUID reviews that claimant as orchestrator."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    uuid_a = "11111111-2222-3333-4444-555555555555"
    _write_stream(
        orch,
        "fx",
        {
            "name": "fx",
            "status": "done",
            "waiting": "",
            "next": "",
            "held_session": None,
            "session": None,
            "repo": str(proj),
        },
        [],  # no claim events
    )
    tickets = proj / ".opencode" / "board" / "tickets"
    tickets.mkdir(parents=True)
    (tickets / "fx.json").write_text(
        json.dumps(
            {
                "schema": 1,
                "id": "fx",
                "stage": "done",
                "history": [
                    {
                        "at": "2026-01-01T00:00:00Z",
                        "cmd": "claim",
                        "from": "queued",
                        "to": "working",
                        "by": uuid_a,
                        "note": None,
                    },
                ],
            }
        )
        + "\n"
    )
    assistant = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "ticket claimant work"}],
        },
        "timestamp": "2026-01-01T00:10:00.000Z",
        "sessionId": uuid_a,
    }
    _cc_transcript(home, "frood", uuid_a, [assistant])

    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    claimant = by_session[uuid_a]
    assert claimant["role"] == "orchestrator", claimant
    assert claimant["status"] == "analyzed", claimant


def test_claimant_plus_child_same_id_one_child_role_nested(tmp_path):
    """C.4: a session that is both a claimant (claim event) and a child event is
    one child; role `nested` wins over `orchestrator`."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"},
        [
            {
                "key": "claim:fx:sess_both",
                "event": "claim",
                "session": "sess_both",
                "by": "cc",
                "at": "2026-01-01T00:00:00Z",
            },
            {
                "key": "child:fx:sess_both",
                "event": "child",
                "session": "sess_both",
                "harness": "claude-code",
                "role": "nested",
                "ts": "2026-01-01T00:00:00Z",
            },
        ],
    )
    assistant = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "both work"}],
        },
        "timestamp": "2026-01-01T00:10:00.000Z",
        "sessionId": "sess_both",
    }
    _cc_transcript(home, "frood", "sess_both", [assistant])

    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    assert len([c for c in children if c["session"] == "sess_both"]) == 1, children
    both = by_session["sess_both"]
    assert both["role"] == "nested", both


# ------------------------------------------------------------------ handoff claim event (A)


def test_handoff_claim_appends_claim_event(tmp_path):
    """A.1: `claim --session X` appends one claim event; `--takeover` appends
    another; claim without `--session` appends none."""
    import subprocess

    home = tmp_path / "home"
    home.mkdir(parents=True)
    try:
        plan = home / "plan.md"
        plan.write_text("# plan\n## Handoff\nnext: M1\n")
        streams = home / ".config" / "orchestrator" / "streams"
        streams.mkdir(parents=True)
        bin_ = str(Path(__file__).resolve().parent.parent / "orchestrator" / "bin" / "handoff.mjs")

        def claim(*args, env_extra=None):
            env = {
                **os.environ,
                "ORCH_HOME": str(home),
                "HOME": str(home),
                "USERPROFILE": str(home),
            }
            if env_extra:
                env.update(env_extra)
            return subprocess.run(
                ["node", bin_, "claim", "--stream", "s1", "--by", "cc", *args],
                capture_output=True,
                text=True,
                env=env,
                timeout=30,
            )

        assert (
            subprocess.run(
                ["node", bin_, "write", "--stream", "s1", "--plan", str(plan), "--next", "M1"],
                capture_output=True,
                text=True,
                timeout=30,
                env={
                    **os.environ,
                    "ORCH_HOME": str(home),
                    "HOME": str(home),
                    "USERPROFILE": str(home),
                },
            ).returncode
            == 0
        )

        r1 = claim("--session", "sess-a")
        assert r1.returncode == 0, r1.stderr
        ev1 = (streams / "s1.events.jsonl").read_text().strip().split("\n")
        assert len(ev1) == 1, ev1
        e1 = json.loads(ev1[0])
        assert e1["event"] == "claim" and e1["session"] == "sess-a" and e1["by"] == "cc", e1

        # takeover by another session -> another claim event
        r3 = claim("--session", "sess-b", "--takeover")
        assert r3.returncode == 0, r3.stderr
        ev3 = (streams / "s1.events.jsonl").read_text().strip().split("\n")
        assert len(ev3) == 2, ev3
        e3 = json.loads(ev3[1])
        assert e3["event"] == "claim" and e3["session"] == "sess-b" and e3["by"] == "cc", e3

        # claim without --session -> no event added
        r4 = claim()
        assert r4.returncode == 0, r4.stderr
        ev4 = (streams / "s1.events.jsonl").read_text().strip().split("\n")
        assert len(ev4) == 2, ev4
    finally:
        pass


# ------------------------------------------------------------------ D.4 minor-findings tests


def test_findings_out_path_is_critic_role(tmp_path):
    """D.4.1: a stream event whose `out` basename starts with `findings-`
    (no `agent`) is a critic child."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"},
        [
            {
                "key": "run:fx/r1:done",
                "kind": "run-done",
                "run": "r1",
                "out": "/x/findings-foo.md",
                "agent": None,
                "session": "ses_fx",
                "model": "opencode-go/mimo-v2.6-flash",
                "at": "2026-01-01T00:00:00Z",
            },
        ],
    )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    assert by_session["ses_fx"]["role"] == "critic", by_session["ses_fx"]


def test_run_in_background_count(tmp_path):
    """D.4.2: a Claude Code transcript whose Bash call sets run_in_background
    counts a background command in the session-summary detail."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {
            "name": "fx",
            "status": "active",
            "waiting": "",
            "next": "2020-01-01T00:00:00Z",
            "held_session": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        },
        [
            {
                "key": "child:fx:sess_bg",
                "event": "child",
                "session": "sess_bg",
                "harness": "claude-code",
                "role": "nested",
                "ts": "2026-01-01T00:00:00Z",
            },
        ],
    )
    bash_bg = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-5",
            "role": "assistant",
            "content": [
                {"type": "text", "text": "bg"},
                {
                    "type": "tool_use",
                    "id": "t1",
                    "name": "Bash",
                    "input": {"command": "deploy x", "run_in_background": True},
                },
            ],
        },
        "timestamp": "2026-01-01T00:10:00.000Z",
        "sessionId": "sess_bg",
    }
    _cc_transcript(home, "frood", "sess_bg", [bash_bg])

    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    children = rep.get("children") or []
    bg = {c["session"]: c for c in children}["sess_bg"]
    ss = next(f for f in bg["findings"] if f["lens"] == "session-summary")
    assert "1 background commands" in ss["detail"], ss["detail"]


def test_receipt_model_fallback(tmp_path):
    """D.4.3: an OpenCode child whose event has no model resolves the model
    from the run's receipt (<out>.receipt.json)."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    rep = proj / ".opencode" / "reports" / "fx"
    rep.mkdir(parents=True)
    (rep / "worker-r1.md.receipt.json").write_text(
        json.dumps({"model": "opencode-go/nemotron-free"}) + "\n"
    )
    _write_stream(
        orch,
        "fx",
        {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"},
        [
            {
                "key": "run:fx/r1:done",
                "kind": "run-done",
                "run": "r1",
                "out": str(rep / "worker-r1.md"),
                "agent": "worker",
                "session": "ses_receipt",
                "model": None,
                "at": "2026-01-01T00:00:00Z",
            },
        ],
    )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    repj = json.loads(out.read_text())
    children = repj.get("children") or []
    by_session = {c["session"]: c for c in children}
    assert by_session["ses_receipt"]["model"] == "opencode-go/nemotron-free", by_session[
        "ses_receipt"
    ]


def _oc_db_with_session(home, session_id, model, with_model_column=True):
    """Create an opencode.db with a session_v2 table and one session row."""
    oc_db_dir = home / ".local" / "share" / "opencode"
    oc_db_dir.mkdir(parents=True)
    oc_db = oc_db_dir / "opencode.db"
    if with_model_column:
        sql = (
            "CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, model TEXT, "
            "time_created INTEGER, time_updated INTEGER);\n"
            f"INSERT INTO session_v2 VALUES ('{session_id}','{session_id}','{model}',1700000000000,1700000300000);\n"
        )
    else:
        sql = (
            "CREATE TABLE session_v2 (id TEXT PRIMARY KEY, title TEXT, "
            "time_created INTEGER, time_updated INTEGER);\n"
            f"INSERT INTO session_v2 VALUES ('{session_id}','{session_id}',1700000000000,1700000300000);\n"
        )
    subprocess.run(["sqlite3", str(oc_db)], input=sql, text=True, check=True)
    return oc_db


def test_resolve_oc_model_with_model_column(tmp_path):
    """Fix 2: a fixture db WITH a `model` column returns its model (no crash)."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _oc_db_with_session(home, "ses_model", "opencode-go/mimo-v2.6-flash", with_model_column=True)
    _write_stream(
        orch,
        "fx",
        {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"},
        [
            {
                "key": "run:fx/r1:done",
                "kind": "run-done",
                "run": "r1",
                "out": "/x/worker-r1.md",
                "agent": "worker",
                "session": "ses_model",
                "model": None,
                "at": "2026-01-01T00:00:00Z",
            },
        ],
    )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    repj = json.loads(out.read_text())
    children = repj.get("children") or []
    by_session = {c["session"]: c for c in children}
    assert by_session["ses_model"]["model"] == "opencode-go/mimo-v2.6-flash", by_session[
        "ses_model"
    ]


def test_resolve_oc_model_without_model_column(tmp_path):
    """Fix 2: a fixture db WITHOUT a `model` column returns null and doesn't crash."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _oc_db_with_session(home, "ses_nomodel", "ignored", with_model_column=False)
    _write_stream(
        orch,
        "fx",
        {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"},
        [
            {
                "key": "run:fx/r1:done",
                "kind": "run-done",
                "run": "r1",
                "out": "/x/worker-r1.md",
                "agent": "worker",
                "session": "ses_nomodel",
                "model": None,
                "at": "2026-01-01T00:00:00Z",
            },
        ],
    )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    repj = json.loads(out.read_text())
    children = repj.get("children") or []
    by_session = {c["session"]: c for c in children}
    assert by_session["ses_nomodel"]["model"] is None, by_session["ses_nomodel"]


def test_non_uuid_claimant_adds_no_child(tmp_path):
    """Fix 3: a claimant whose id is neither a UUID nor `ses_…` (e.g.
    `opus-797bcde8`) is skipped quietly: no child, no crash."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {
            "name": "fx",
            "status": "done",
            "waiting": "",
            "next": "",
            "held_session": None,
            "session": None,
        },
        [
            {
                "key": "claim:fx:opus-797bcde8",
                "event": "claim",
                "session": "opus-797bcde8",
                "by": "cc",
                "at": "2026-01-01T00:00:00Z",
            },
        ],
    )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    repj = json.loads(out.read_text())
    children = repj.get("children") or []
    assert not any(c["session"] == "opus-797bcde8" for c in children), children


def test_repo_non_string_does_not_crash(tmp_path):
    """Fix 4: a stream whose `repo` is not a string (e.g. 123) doesn't crash
    the board-ticket fallback path."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {
            "name": "fx",
            "status": "done",
            "waiting": "",
            "next": "",
            "held_session": None,
            "session": None,
            "repo": 123,
        },
        [],
    )
    out = home / "out.json"
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj)
    assert r.returncode == 0, r.stderr
    repj = json.loads(out.read_text())
    assert "children" in repj


def test_local_and_transcript_id_for_one_session_review_it_once(tmp_path):
    """One nested session recorded under two ids — an old parent's desktop `local_` record and its own
    transcript id (claim + self-record) — resolves to one transcript, so it is reviewed once, as `nested`,
    under the transcript id."""
    uid = "aaaaaaaa-bbbb-cccc-dddd-222222222222"
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    proj = home / "proj"
    proj.mkdir(parents=True)
    _write_stream(
        orch,
        "fx",
        {
            "name": "fx",
            "status": "done",
            "waiting": "",
            "next": "",
            "held_session": None,
            "session": None,
            "repo": str(proj),
        },
        [
            {
                "key": f"claim:fx:{uid}",
                "event": "claim",
                "kind": "claim",
                "session": uid,
                "by": "cc",
                "at": "2026-01-01T00:00:00Z",
            },
            {
                "key": "child:fx:local_old",
                "event": "child",
                "kind": "child",
                "session": "local_old",
                "harness": "claude-code",
                "role": "nested",
            },
            {
                "key": f"child:fx:{uid}",
                "event": "child",
                "kind": "child",
                "session": uid,
                "harness": "claude-code",
                "role": "nested",
            },
        ],
    )
    assistant = {
        "type": "assistant",
        "message": {
            "model": "claude-opus-4-5",
            "role": "assistant",
            "content": [{"type": "text", "text": "nested work"}],
        },
        "timestamp": "2026-01-01T00:10:00.000Z",
        "sessionId": uid,
    }
    _cc_transcript(home, "frood", uid, [assistant])
    meta_dir = tmp_path / "desktop" / "acct" / "org"
    meta_dir.mkdir(parents=True)
    (meta_dir / "local_old.json").write_text(
        json.dumps({"sessionId": "local_old", "cliSessionId": uid})
    )

    out = home / "out.json"
    r = run(
        ["fx", "--phase", "1", "--no-mcp", "--report", str(out)],
        home,
        cwd=proj,
        extra_env={"CLAUDE_DESKTOP_SESSIONS_DIR": str(tmp_path / "desktop")},
    )
    assert r.returncode == 0, r.stderr
    children = json.loads(out.read_text())["children"]
    mine = [c for c in children if c["session"] in (uid, "local_old")]
    assert len(mine) == 1, mine
    assert mine[0]["session"] == uid, mine[0]
    assert mine[0]["role"] == "nested", mine[0]
    assert mine[0]["status"] == "analyzed", mine[0]


# ------------------------------------------------------------------ Claude Code child fixtures

FIXTURES = REPO / "tests" / "fixtures" / "frood_learn"


def _cc_child_home(tmp_path, fixture_name, session_id):
    """A HOME whose stream fx has one Claude Code nested child whose transcript is a fixture."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    (orch / "streams" / "fx.json").write_text(
        json.dumps(
            {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"}
        )
    )
    cc_proj = home / ".claude" / "projects" / "frood"
    cc_proj.mkdir(parents=True, exist_ok=True)
    (cc_proj / f"{session_id}.jsonl").write_text((FIXTURES / fixture_name).read_text())
    (orch / "streams" / "fx.events.jsonl").write_text(
        json.dumps(
            {
                "key": f"child:fx:{session_id}",
                "event": "child",
                "session": session_id,
                "harness": "claude-code",
                "role": "nested",
                "ts": "2026-01-01T00:00:00Z",
            }
        )
        + "\n"
    )
    proj = home / "proj"
    proj.mkdir(parents=True)
    return home, proj


def _cc_report(tmp_path, fixture_name, session_id, extra_env=None):
    home, proj = _cc_child_home(tmp_path, fixture_name, session_id)
    out = home / "out.json"
    r = run(
        ["fx", "--phase", "1", "--no-mcp", "--report", str(out)],
        home,
        cwd=proj,
        extra_env=extra_env,
    )
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text()), home, proj


def test_cc_child_denied_board_write_high(tmp_path):
    """A classifier-denied `board.mjs round …` Bash call → blocked-actions, severity high, command named."""
    rep, _, _ = _cc_report(tmp_path, "cc-denied-board.jsonl", "sess_cc_board")
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    assert "sess_cc_board" in by_session, children
    child = by_session["sess_cc_board"]
    assert child["status"] == "analyzed", child
    bf = [f for f in child["findings"] if f["lens"] == "blocked-actions"]
    assert len(bf) == 1, bf
    assert bf[0]["area"] == "permissions", bf
    assert bf[0]["severity"] == "high", bf
    assert bf[0]["source"] == "session-data", bf
    assert "board.mjs" in bf[0]["detail"] and "round" in bf[0]["detail"], bf[0]
    assert "board.mjs round orphan-notice-holder" in bf[0]["detail"], bf[0]
    rec = bf[0]["recommendation"]
    assert "desk cannot merge" in rec and "owner must" in rec and "permission settings" in rec, rec


def test_cc_child_denied_nonboard_medium(tmp_path):
    """A denied non-board command → blocked-actions, severity medium."""
    rep, _, _ = _cc_report(tmp_path, "cc-denied-medium.jsonl", "sess_cc_medium")
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    child = by_session["sess_cc_medium"]
    bf = [f for f in child["findings"] if f["lens"] == "blocked-actions"]
    assert len(bf) == 1, bf
    assert bf[0]["severity"] == "medium", bf
    assert "rm -rf /tmp/secrets" in bf[0]["detail"], bf[0]


def test_cc_child_no_denials_no_blocked_actions(tmp_path):
    """A transcript with no denials → no blocked-actions finding."""
    rep, _, _ = _cc_report(tmp_path, "cc-clean.jsonl", "sess_cc_clean")
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    child = by_session["sess_cc_clean"]
    assert not any(f["lens"] == "blocked-actions" for f in child["findings"]), child["findings"]


def test_cc_child_two_denials_two_findings(tmp_path):
    """Two denials in one transcript → two blocked-actions findings, both high (board/handoff writes)."""
    rep, _, _ = _cc_report(tmp_path, "cc-two-denials.jsonl", "sess_cc_two")
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    child = by_session["sess_cc_two"]
    bf = [f for f in child["findings"] if f["lens"] == "blocked-actions"]
    assert len(bf) == 2, bf
    assert all(f["severity"] == "high" for f in bf), bf
    assert all(f["area"] == "permissions" for f in bf), bf
    assert all(f["source"] == "session-data" for f in bf), bf
    commands = [f["detail"] for f in bf]
    assert any("board.mjs round" in c for c in commands), commands
    assert any("handoff.mjs write" in c for c in commands), commands


def test_cc_child_user_prompt_count(tmp_path):
    """3 typed prompts + 20 tool_result-only user lines (some errors) → 3 user prompts, no iteration-patterns."""
    rep, _, _ = _cc_report(tmp_path, "cc-prompts.jsonl", "sess_cc_prompts")
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    child = by_session["sess_cc_prompts"]
    ss = next(f for f in child["findings"] if f["lens"] == "session-summary")
    assert "3 user prompts" in ss["detail"], ss["detail"]
    assert not any(f["lens"] == "iteration-patterns" for f in child["findings"]), child["findings"]
    # Errors still counted via error-patterns (the tool_result-only error lines).
    assert any(f["lens"] == "error-patterns" for f in child["findings"]), child["findings"]


def test_cc_child_custom_title_in_summary(tmp_path):
    """The last custom-title line's title appears in the session-summary."""
    rep, _, _ = _cc_report(tmp_path, "cc-titled.jsonl", "sess_cc_titled")
    children = rep.get("children") or []
    by_session = {c["session"]: c for c in children}
    child = by_session["sess_cc_titled"]
    ss = next(f for f in child["findings"] if f["lens"] == "session-summary")
    assert 'Session "The Real Session Title"' in ss["detail"], ss["detail"]
    assert "First title" not in ss["detail"], ss["detail"]


def test_cc_child_desktop_title_fallback(tmp_path):
    """A local_ child with no custom-title uses the desktop app metadata title."""
    home, proj = _cc_child_home(tmp_path, "cc-desktop-title.jsonl", "local_cc-desktop")
    # Point the local_ id at the real transcript id via the app metadata file, with a title.
    meta_dir = home / "desktop-sessions" / "acct" / "org"
    meta_dir.mkdir(parents=True)
    (meta_dir / "local_cc-desktop.json").write_text(
        json.dumps(
            {
                "sessionId": "local_cc-desktop",
                "cliSessionId": "sess_cc_desktop",
                "title": "Desktop App Title",
            }
        )
    )
    # The nested transcript id is sess_cc_desktop (no custom-title line).
    cc_proj = home / ".claude" / "projects" / "frood"
    (cc_proj / "sess_cc_desktop.jsonl").write_text(
        (FIXTURES / "cc-desktop-title.jsonl").read_text()
    )
    out = home / "out.json"
    env = {"CLAUDE_DESKTOP_SESSIONS_DIR": str(home / "desktop-sessions")}
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj, extra_env=env)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    by_session = {c["session"]: c for c in rep.get("children") or []}
    child = by_session["local_cc-desktop"]
    assert child["status"] == "analyzed", child
    ss = next(f for f in child["findings"] if f["lens"] == "session-summary")
    assert 'Session "Desktop App Title"' in ss["detail"], ss["detail"]


def test_cc_child_local_custom_title_wins_desktop(tmp_path):
    """A local_ child with a custom-title line uses the custom title, not the desktop title."""
    home, proj = _cc_child_home(tmp_path, "cc-titled.jsonl", "local_cc-titled")
    meta_dir = home / "desktop-sessions" / "acct" / "org"
    meta_dir.mkdir(parents=True)
    (meta_dir / "local_cc-titled.json").write_text(
        json.dumps(
            {
                "sessionId": "local_cc-titled",
                "cliSessionId": "sess_cc_titled",
                "title": "Desktop App Title",
            }
        )
    )
    (home / ".claude" / "projects" / "frood" / "sess_cc_titled.jsonl").write_text(
        (FIXTURES / "cc-titled.jsonl").read_text()
    )
    out = home / "out.json"
    env = {"CLAUDE_DESKTOP_SESSIONS_DIR": str(home / "desktop-sessions")}
    r = run(["fx", "--phase", "1", "--no-mcp", "--report", str(out)], home, cwd=proj, extra_env=env)
    assert r.returncode == 0, r.stderr
    rep = json.loads(out.read_text())
    by_session = {c["session"]: c for c in rep.get("children") or []}
    child = by_session["local_cc-titled"]
    ss = next(f for f in child["findings"] if f["lens"] == "session-summary")
    assert 'Session "The Real Session Title"' in ss["detail"], ss["detail"]
    assert "Desktop App Title" not in ss["detail"], ss["detail"]


# ------------------------------------------------------------------ stream board-integrity cross-check


def _git(cmd, cwd):
    return subprocess.run(["git", *cmd], cwd=str(cwd), capture_output=True, text=True)


def _board_integrity_home(tmp_path):
    """A HOME + temp git repo where a stream ticket is merged to main with an empty board ticket."""
    home = tmp_path / "home"
    orch = home / ".config" / "orchestrator"
    (orch / "streams").mkdir(parents=True)
    (orch / "desk-daemon").mkdir(parents=True)
    (orch / "desk-daemon" / "daemon.log").write_text("t1 verdict-failed ticket-a\n")
    (orch / "streams" / "fx.json").write_text(
        json.dumps(
            {"name": "fx", "status": "active", "waiting": "", "next": "2020-01-01T00:00:00Z"}
        )
    )
    # Temp git repo: main + a feature branch merged into main.
    repo = tmp_path / "repo"
    repo.mkdir(parents=True)
    _git(["init", "-b", "main"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    (repo / "file.txt").write_text("hello\n")
    _git(["add", "file.txt"], repo)
    _git(["commit", "-m", "base"], repo)
    _git(["checkout", "-b", "feature"], repo)
    (repo / "file.txt").write_text("hello2\n")
    _git(["commit", "-am", "feature work"], repo)
    _git(["checkout", "main"], repo)
    _git(["merge", "--ff-only", "feature"], repo)
    # Board ticket (empty rounds/gates/signoffs) at <repo>/.opencode/board/tickets/<id>.json
    board = repo / ".opencode" / "board" / "tickets"
    board.mkdir(parents=True)
    (board / "tk-merge-empty.json").write_text(
        json.dumps({"id": "tk-merge-empty", "rounds": [], "gates": [], "signoffs": []})
    )
    # Stream run dir holding ticket.json pointing at the merged ticket.
    rundir = tmp_path / "run"
    rundir.mkdir(parents=True)
    (rundir / "ticket.json").write_text(
        json.dumps({"ticket": "tk-merge-empty", "branch": "feature", "repo": str(repo)})
    )
    (orch / "streams" / "fx.events.jsonl").write_text(
        json.dumps(
            {
                "key": "run:fx/r1:done",
                "kind": "run-done",
                "run": "fx/r1",
                "out": str(rundir / "ticket.json"),
                "at": "2026-01-01T00:00:00Z",
            }
        )
        + "\n"
    )
    proj = home / "proj"
    proj.mkdir(parents=True)
    return home, proj, repo


def _learn_report(home, proj, stream="fx", extra_args=None, cwd=None):
    out = home / "out.json"
    args = [stream, "--phase", "1", "--no-mcp", "--report", str(out)]
    if extra_args:
        args += extra_args
    r = run(args, home, cwd=cwd or proj)
    assert r.returncode == 0, r.stderr
    return json.loads(out.read_text())


def test_stream_board_integrity_merged_empty(tmp_path):
    """Merged ticket with empty rounds/gates/signoffs → board-integrity finding."""
    home, proj, repo = _board_integrity_home(tmp_path)
    rep = _learn_report(home, proj)
    details = {f["focus"]: f for f in rep["findings"]}
    bf = details.get("board ticket tk-merge-empty")
    assert bf is not None, rep["findings"]
    assert bf["area"] == "board", bf
    assert "merged with no recorded rounds/gates/signoffs" in bf["detail"], bf


def test_stream_board_integrity_not_merged_silent(tmp_path):
    """A ticket whose branch is not merged to main → no board-integrity finding."""
    home, proj, repo = _board_integrity_home(tmp_path)
    # Repoint the ticket at an unmerged branch.
    _git(["checkout", "-b", "unmerged"], repo)
    (repo / "file.txt").write_text("unmerged\n")
    _git(["commit", "-am", "unmerged work"], repo)
    rundir = tmp_path / "run"
    (home / ".config" / "orchestrator" / "streams" / "fx.events.jsonl").write_text(
        json.dumps(
            {
                "key": "run:fx/r1:done",
                "kind": "run-done",
                "run": "fx/r1",
                "out": str(rundir / "ticket.json"),
                "at": "2026-01-01T00:00:00Z",
            }
        )
        + "\n"
    )
    # Rewrite ticket.json branch to unmerged.
    (rundir / "ticket.json").write_text(
        json.dumps({"ticket": "tk-merge-empty", "branch": "unmerged", "repo": str(repo)})
    )
    rep = _learn_report(home, proj)
    assert not any(f["focus"] == "board ticket tk-merge-empty" for f in rep["findings"]), rep[
        "findings"
    ]


def test_stream_board_integrity_rounds_exist_silent(tmp_path):
    """A merged ticket whose board ticket has rounds → no board-integrity finding."""
    home, proj, repo = _board_integrity_home(tmp_path)
    board = repo / ".opencode" / "board" / "tickets"
    (board / "tk-merge-empty.json").write_text(
        json.dumps(
            {"id": "tk-merge-empty", "rounds": [{"counted": True}], "gates": [], "signoffs": []}
        )
    )
    rep = _learn_report(home, proj)
    assert not any(f["focus"] == "board ticket tk-merge-empty" for f in rep["findings"]), rep[
        "findings"
    ]


def test_stream_board_integrity_links_denied_board_session(tmp_path):
    """If a child review found a denied board write, the board-integrity finding links to it."""
    # Build the board-integrity scenario.
    home, proj, repo = _board_integrity_home(tmp_path)
    # Add a CC child whose transcript denies a board.mjs write.
    cc_proj = home / ".claude" / "projects" / "frood"
    cc_proj.mkdir(parents=True, exist_ok=True)
    (cc_proj / "sess_cc_board.jsonl").write_text((FIXTURES / "cc-denied-board.jsonl").read_text())
    events = home / ".config" / "orchestrator" / "streams" / "fx.events.jsonl"
    events.write_text(
        events.read_text()
        + json.dumps(
            {
                "key": "child:fx:sess_cc_board",
                "event": "child",
                "session": "sess_cc_board",
                "harness": "claude-code",
                "role": "nested",
                "ts": "2026-01-01T00:00:00Z",
            }
        )
        + "\n"
    )
    rep = _learn_report(home, proj)
    bf = next((f for f in rep["findings"] if f["focus"] == "board ticket tk-merge-empty"), None)
    assert bf is not None, rep["findings"]
    assert "a board write was denied in session sess_cc_board" in bf["detail"], bf
    assert "sess_cc_board" in bf["evidence"], bf

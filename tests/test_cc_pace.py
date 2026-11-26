"""Tests for core/cc_pace.py — the read-only Claude Code pace reader.

Settings strategy: each test sets CC_PACE_* env vars with monkeypatch, builds a fresh
``Settings.from_env()`` and monkeypatches ``core.config.settings`` to it. That exercises
the real ``from_env`` parsing without mutating the global singleton (``reload_from_env``
would also load the repo ``.env`` and write into the shared object). ``core.cc_pace``
reads ``core.config.settings`` at call time, so it sees the patched object.

The fake "node" is a small Python script in ``tmp_path`` passed as ``CC_PACE_NODE``;
``CC_PACE_MJS`` is pointed at a dummy file. Each spawn appends a line to a counter file.
"""

import json
import os
import sys
import textwrap

import pytest

from core import cc_pace, config


@pytest.fixture(autouse=True)
def _fresh(monkeypatch, tmp_path):
    cc_pace._reset_cache()
    mjs = tmp_path / "cc-pace.mjs"
    mjs.write_text("// dummy\n")
    monkeypatch.setattr(cc_pace, "CC_PACE_MJS", mjs)
    for k in ("CC_PACE_ENABLED", "CC_PACE_NODE", "CC_PACE_ORCH_HOME", "ORCH_HOME"):
        monkeypatch.delenv(k, raising=False)
    yield
    cc_pace._reset_cache()


def _use_settings(monkeypatch, **env):
    for k, v in env.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(config, "settings", config.Settings.from_env())


def _fake(tmp_path, body: str, name: str = "fake-node") -> tuple[str, object]:
    """Write an executable fake node; returns (path, spawn-counter file)."""
    counter = tmp_path / "spawns.txt"
    script = tmp_path / name
    script.write_text(
        f"#!{sys.executable}\n"
        "import os, sys, time, json\n"
        f"open({str(counter)!r}, 'a').write('spawn\\n')\n" + textwrap.dedent(body)
    )
    script.chmod(0o755)
    return str(script), counter


def _spawns(counter) -> int:
    return len(counter.read_text().splitlines()) if counter.exists() else 0


@pytest.mark.parametrize("state", ["off", "unknown", "over", "on", "under"])
async def test_each_state_parses(monkeypatch, tmp_path, state):
    payload = {"state": state, "weekly": 40}
    node, _ = _fake(
        tmp_path,
        f"print('some log line')\nprint({json.dumps(payload)!r})\nprint('')\n",
    )
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    assert await cc_pace.read_pace() == payload


async def test_timeout_child_reaped_via_handle(monkeypatch, tmp_path):
    node, _ = _fake(tmp_path, "time.sleep(30)\n")
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    captured = []
    real = cc_pace.asyncio.create_subprocess_exec

    async def spy(*a, **kw):
        proc = await real(*a, **kw)
        captured.append(proc)
        return proc

    monkeypatch.setattr(cc_pace.asyncio, "create_subprocess_exec", spy)
    result = await cc_pace.read_pace(timeout_s=0.2)
    assert result == {"state": "unknown", "reason": "timeout"}
    assert len(captured) == 1
    assert captured[0].returncode is not None
    with pytest.raises(ProcessLookupError):  # killed and reaped: the pid is gone
        os.kill(captured[0].pid, 0)


async def test_missing_node(monkeypatch, tmp_path):
    _use_settings(monkeypatch, CC_PACE_NODE=str(tmp_path / "no-such-node"))
    assert await cc_pace.read_pace() == {"state": "unknown", "reason": "node not found"}


async def test_missing_mjs_no_spawn(monkeypatch, tmp_path):
    node, counter = _fake(tmp_path, 'print(\'{"state": "on"}\')\n')
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    monkeypatch.setattr(cc_pace, "CC_PACE_MJS", tmp_path / "gone.mjs")
    assert await cc_pace.read_pace() == {"state": "unknown", "reason": "missing cc-pace.mjs"}
    assert _spawns(counter) == 0


async def test_exit_code(monkeypatch, tmp_path):
    node, _ = _fake(tmp_path, 'print(\'{"state": "on"}\')\nsys.exit(1)\n')
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    assert await cc_pace.read_pace() == {"state": "unknown", "reason": "exit 1"}


@pytest.mark.parametrize("out", ["not json", '["state"]', '{"state": 3}', '{"weekly": 1}', ""])
async def test_bad_json(monkeypatch, tmp_path, out):
    node, _ = _fake(tmp_path, f"print({out!r})\n")
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    assert await cc_pace.read_pace() == {"state": "unknown", "reason": "bad json"}


async def test_cache_within_60s_spawns_once(monkeypatch, tmp_path):
    node, counter = _fake(tmp_path, 'print(\'{"state": "under"}\')\n')
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    clock = iter([0.0, 59.0])
    a = await cc_pace.read_pace(now=lambda: next(clock))
    b = await cc_pace.read_pace(now=lambda: next(clock))
    assert a == b == {"state": "under"}
    assert _spawns(counter) == 1


async def test_cache_after_60s_spawns_twice(monkeypatch, tmp_path):
    node, counter = _fake(tmp_path, 'print(\'{"state": "under"}\')\n')
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    clock = iter([0.0, 61.0])
    await cc_pace.read_pace(now=lambda: next(clock))
    await cc_pace.read_pace(now=lambda: next(clock))
    assert _spawns(counter) == 2


async def test_failures_are_cached(monkeypatch, tmp_path):
    node, counter = _fake(tmp_path, "sys.exit(2)\n")
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    clock = iter([0.0, 30.0])
    assert (await cc_pace.read_pace(now=lambda: next(clock)))["reason"] == "exit 2"
    assert (await cc_pace.read_pace(now=lambda: next(clock)))["reason"] == "exit 2"
    assert _spawns(counter) == 1


async def test_disabled_returns_off_no_spawn(monkeypatch, tmp_path):
    node, counter = _fake(tmp_path, 'print(\'{"state": "on"}\')\n')
    _use_settings(monkeypatch, CC_PACE_NODE=node, CC_PACE_ENABLED="false")
    assert config.settings.cc_pace_enabled is False
    assert await cc_pace.read_pace() == {"state": "off"}
    assert _spawns(counter) == 0


async def test_orch_home_passed_to_child(monkeypatch, tmp_path):
    node, _ = _fake(
        tmp_path,
        "print(json.dumps({'state': 'on', 'orch_home': os.environ.get('ORCH_HOME')}))\n",
    )
    _use_settings(monkeypatch, CC_PACE_NODE=node, CC_PACE_ORCH_HOME="/x")
    assert (await cc_pace.read_pace())["orch_home"] == "/x"


async def test_orch_home_unset_not_injected(monkeypatch, tmp_path):
    node, _ = _fake(
        tmp_path,
        "print(json.dumps({'state': 'on', 'orch_home': os.environ.get('ORCH_HOME')}))\n",
    )
    _use_settings(monkeypatch, CC_PACE_NODE=node)
    assert (await cc_pace.read_pace())["orch_home"] is None


async def test_failure_logged_once_per_reason(monkeypatch, tmp_path, caplog):
    _use_settings(monkeypatch, CC_PACE_NODE=str(tmp_path / "nope"))
    caplog.set_level("INFO", logger="core.cc_pace")
    clock = iter([0.0, 100.0, 200.0])
    for _ in range(3):
        await cc_pace.read_pace(now=lambda: next(clock))
    msgs = [r for r in caplog.records if r.name == "core.cc_pace"]
    assert len(msgs) == 1
    assert "node not found" in msgs[0].getMessage()


def test_settings_defaults(monkeypatch):
    s = config.Settings.from_env()
    assert s.cc_pace_enabled is True
    assert s.cc_pace_node == "node"
    assert s.cc_pace_orch_home == ""

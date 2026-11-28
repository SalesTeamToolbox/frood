"""tests/test_frood_cc_launcher.py — gw-t4 launcher tests.

Never launch the real `claude`, never open a terminal, never touch the real `.env`
and never contact Frood. `os.execvpe`, `subprocess.Popen`, `shutil.which` and the
HTTP calls are monkeypatched; `.env` lives under tmp_path.
"""

import importlib.util
import json
import os
import stat
from pathlib import Path
from unittest.mock import MagicMock

import pytest

ROOT = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location("frood_cc_launcher", ROOT / "frood-cc-launcher.py")
launcher = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(launcher)

GO_IDS = ["kimi-k3", "glm-5.3-flash", "deepseek-v4.1-flash"]
NV_IDS = [
    "minimaxai/minimax-m3.1-flash",
    "minimaxai/minimax-m3.1-flash",
    "nvidia/nemotron-3.5-lightning-30b-a3b",
]


def _patch_fetch(monkeypatch, health, models_status, models_data=None, models_body=""):
    def fetch(url, headers, timeout=5.0):
        if "/health" in url:
            return (health, None, "")
        return (models_status, models_data, models_body)

    monkeypatch.setattr(launcher, "_fetch_json", fetch)


# --- build_env -----------------------------------------------------------------


def test_build_env_go():
    base = {
        "HOME": "/fakehome",
        "PATH": "/usr/bin",
        "LANG": "en_US.UTF-8",
        "ANTHROPIC_BASE_URL": "http://old/llm/v1",
        "ANTHROPIC_API_KEY": "sk-secret",
        "CLAUDE_CODE_OAUTH_TOKEN": "oauth",
        "CLAUDE_CODE_ENTRYPOINT": "x",
        "CLAUDECODE": "y",
        "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH": "1",
        "NVIDIA_API_KEY": "nv-key",
        "GITHUB_TOKEN": "gh-token",
        "SSH_AUTH_SOCK": "/tmp/sock",
        "DBUS_SESSION_BUS_ADDRESS": "unix:path",
    }
    env = launcher.build_env("go", "tok-abc", base)
    assert env["HOME"] == "/fakehome"
    assert env["PATH"] == "/usr/bin"
    assert env["LANG"] == "en_US.UTF-8"
    for key in (
        "ANTHROPIC_API_KEY",
        "CLAUDE_CODE_OAUTH_TOKEN",
        "CLAUDE_CODE_ENTRYPOINT",
        "CLAUDECODE",
        "CLAUDE_CODE_SDK_HAS_HOST_AUTH_REFRESH",
        "NVIDIA_API_KEY",
        "GITHUB_TOKEN",
        "SSH_AUTH_SOCK",
        "DBUS_SESSION_BUS_ADDRESS",
    ):
        assert key not in env, key
    # The copied base ANTHROPIC_BASE_URL is dropped (denylist) then re-set to /gw.
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8000/gw"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "tok-abc"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "kimi-k3"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "glm-5.3-flash"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "deepseek-v4.1-flash"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL_NAME"] == "Go kimi-k3"
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES"] == ""
    assert env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] == "128000"
    assert env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] == "100000"
    assert env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] == "1"
    assert env["DISABLE_TELEMETRY"] == "1"
    assert env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] == "1"
    assert env["FROOD_CC_MODE"] == "go"
    assert "CLAUDE_CODE_SUBAGENT_MODEL" not in env


def test_build_env_nvidia_ids():
    env = launcher.build_env("nvidia", "t", {"HOME": "/h"})
    assert env["ANTHROPIC_DEFAULT_OPUS_MODEL"] == "minimaxai/minimax-m3.1-flash"
    assert env["ANTHROPIC_DEFAULT_SONNET_MODEL"] == "minimaxai/minimax-m3.1-flash"
    assert env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] == "nvidia/nemotron-3.5-lightning-30b-a3b"


def test_build_env_cc_no_gateway_vars():
    base = {"HOME": "/h", "ANTHROPIC_BASE_URL": "http://x", "ANTHROPIC_API_KEY": "k"}
    env = launcher.build_env("cc", "t", base)
    assert env["HOME"] == "/h"
    assert not any(k.startswith("ANTHROPIC_") for k in env)
    assert not any(k.startswith("ANTHROPIC_DEFAULT_") for k in env)
    assert "FROOD_CC_MODE" not in env


def test_build_env_isolated_sets_config_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    env = launcher.build_env("go", "t", {"HOME": "/h"}, isolated=True)
    assert env["CLAUDE_CONFIG_DIR"] == str(tmp_path / "xdg" / "frood" / "cc-gateway")
    assert Path(env["CLAUDE_CONFIG_DIR"]).is_dir()
    mode = stat.S_IMODE(os.stat(env["CLAUDE_CONFIG_DIR"]).st_mode)
    assert mode == 0o700
    env2 = launcher.build_env("go", "t", {"HOME": "/h"})
    assert "CLAUDE_CONFIG_DIR" not in env2


# --- token ---------------------------------------------------------------------


def _env_file(tmp_path, content="", mode=0o600):
    env_path = tmp_path / ".env"
    env_path.write_text(content, encoding="utf-8")
    env_path.chmod(mode)
    launcher.ENV_PATH = env_path
    return env_path


def test_token_generated_and_appended(tmp_path, capsys):
    env_path = _env_file(tmp_path, "OTHER=keep\nEXISTING=1\n", mode=0o644)
    token = launcher.ensure_token(env_path)
    assert token
    text = env_path.read_text(encoding="utf-8")
    assert "OTHER=keep" in text
    assert "EXISTING=1" in text
    assert f"FROOD_GATEWAY_TOKEN={token}" in text
    assert stat.S_IMODE(os.stat(env_path).st_mode) == 0o600
    out = capsys.readouterr().out
    assert "generated a gateway token in .env" in out
    assert token not in out


def test_token_new_env_created_0600(tmp_path):
    env_path = tmp_path / "brandnew.env"
    launcher.ENV_PATH = env_path
    token = launcher.ensure_token(env_path)
    assert env_path.exists()
    assert stat.S_IMODE(os.stat(env_path).st_mode) == 0o600
    assert f"FROOD_GATEWAY_TOKEN={token}" in env_path.read_text(encoding="utf-8")


def test_token_present_reused_unchanged(tmp_path, capsys):
    env_path = _env_file(tmp_path, "FROOD_GATEWAY_TOKEN=present-tok\n", mode=0o600)
    token = launcher.ensure_token(env_path)
    assert token == "present-tok"
    assert capsys.readouterr().out == ""


def test_token_empty_regenerated_once(tmp_path):
    # An empty key is treated as missing: generated once and appended; a second
    # call reuses the generated token (no endless re-append).
    env_path = _env_file(tmp_path, "FROOD_GATEWAY_TOKEN=\n", mode=0o600)
    launcher.ENV_PATH = env_path
    t1 = launcher.ensure_token(env_path)
    assert t1
    text1 = env_path.read_text(encoding="utf-8")
    assert f"FROOD_GATEWAY_TOKEN={t1}" in text1
    t2 = launcher.ensure_token(env_path)
    assert t2 == t1
    text2 = env_path.read_text(encoding="utf-8")
    assert text2.count("FROOD_GATEWAY_TOKEN=") == 2  # the empty line + one generated


def test_cc_does_not_touch_env(monkeypatch, capsys):
    # cc (subscription) never reads/generates the gateway token or creates .env.
    called = []

    def boom(path=None):
        called.append(path)
        raise AssertionError("ensure_token must not run for cc")

    monkeypatch.setattr(launcher, "ensure_token", boom)
    monkeypatch.setattr(launcher, "find_claude", lambda env: "/usr/bin/claude")
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd, path=None: None)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["cc", "--print-cmd"])
    assert exc.value.code == 0
    assert called == []


# --- preflight -----------------------------------------------------------------


def test_preflight_health_down(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    monkeypatch.setattr(launcher, "_fetch_json", lambda *a, **k: (None, None, ""))
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 1
    assert "Frood is not running: start it with" in capsys.readouterr().out


def test_preflight_401(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    _patch_fetch(monkeypatch, 200, 401)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 1
    assert "gateway token mismatch" in capsys.readouterr().out


def test_preflight_404(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    _patch_fetch(monkeypatch, 200, 404)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 1
    assert "no gateway" in capsys.readouterr().out


def test_preflight_503_prints_error_message(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "gw-token-999")
    body = json.dumps({"error": {"message": "token not set"}})
    _patch_fetch(monkeypatch, 200, 503, None, body)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 1
    assert "token not set" in capsys.readouterr().out


def test_preflight_503_non_json_body(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    _patch_fetch(monkeypatch, 200, 503, None, "plain text boom")
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 1
    assert "gateway error (HTTP 503)" in capsys.readouterr().out


# --- preflight 503 token redaction ---------------------------------------------


def test_preflight_503_redacts_token(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "secret-token-xyz")
    body = json.dumps({"error": {"message": "bad token secret-token-xyz try again"}})
    _patch_fetch(monkeypatch, 200, 503, None, body)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "secret-token-xyz" not in out
    assert "***" in out


def test_preflight_missing_tier_names_ids(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    _patch_fetch(monkeypatch, 200, 200, {"data": [{"id": "deepseek-v4.1-flash"}]})
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 1
    out = capsys.readouterr().out
    assert "kimi-k3" in out
    assert "glm-5.3-flash" in out


def test_preflight_no_check_skips_only_tier_list(monkeypatch, capsys):
    # health still runs: down => exit 1 even with --no-check
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    monkeypatch.setattr(launcher, "_fetch_json", lambda *a, **k: (None, None, ""))
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go", "--no-check"])
    assert exc.value.code == 1
    assert "Frood is not running" in capsys.readouterr().out

    # auth still runs: 401 => exit 1 even with --no-check
    def fetch(url, headers, timeout=5.0):
        if "/health" in url:
            return (200, None, "")
        return (401, None, "")

    monkeypatch.setattr(launcher, "_fetch_json", fetch)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go", "--no-check"])
    assert exc.value.code == 1
    assert "gateway token mismatch" in capsys.readouterr().out


def test_no_check_skips_tier_list_for_nvidia(monkeypatch, capsys):
    # Gateway lists only the Go ids (nvidia routing not shipped yet); --no-check
    # skips the tier-id list check so nvidia can still launch.
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    _patch_fetch(monkeypatch, 200, 200, {"data": [{"id": "deepseek-v4.1-flash"}]})
    monkeypatch.setattr(launcher, "find_claude", lambda env: "/usr/bin/claude")
    launched = []

    def fake_execvpe(file, args, env):
        launched.append((file, args, env))
        raise SystemExit(0)

    monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["nvidia", "--no-check", "--here"])
    assert exc.value.code == 0
    assert launched
    assert launched[0][0] == "/usr/bin/claude"

    # Without --no-check, the missing nvidia ids are named and launch is blocked.
    def fetch(url, headers, timeout=5.0):
        if "/health" in url:
            return (200, None, "")
        return (200, {"data": [{"id": "deepseek-v4.1-flash"}]}, "")

    monkeypatch.setattr(launcher, "_fetch_json", fetch)
    launched.clear()
    with pytest.raises(SystemExit) as exc:
        launcher.main(["nvidia", "--here"])
    assert exc.value.code == 1
    assert launched == []
    out = capsys.readouterr().out
    assert "minimaxai/minimax-m3.1-flash" in out
    assert "nvidia/nemotron-3.5-lightning-30b-a3b" in out
    assert "--no-check to launch anyway" in out


# --- launch --------------------------------------------------------------------


def _setup_launch_mocks(monkeypatch, models=GO_IDS):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    _patch_fetch(monkeypatch, 200, 200, {"data": [{"id": m} for m in models]})
    monkeypatch.setattr(launcher, "find_claude", lambda env: "/usr/bin/claude")
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd, path=None: None)


def test_launch_here_execvpe_clean_env(monkeypatch, capsys):
    _setup_launch_mocks(monkeypatch)
    calls = []

    def fake_execvpe(file, args, env):
        calls.append((file, args, env))
        raise SystemExit(0)

    monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go", "--here"])
    assert exc.value.code == 0
    assert calls
    file, args, env = calls[0]
    assert file == "/usr/bin/claude"
    assert args == ["/usr/bin/claude"]
    assert env["ANTHROPIC_BASE_URL"] == "http://127.0.0.1:8000/gw"
    assert env["ANTHROPIC_AUTH_TOKEN"] == "tok"
    for key in (
        "ANTHROPIC_API_KEY",
        "CLAUDECODE",
        "NVIDIA_API_KEY",
        "GITHUB_TOKEN",
        "SSH_AUTH_SOCK",
        "DBUS_SESSION_BUS_ADDRESS",
    ):
        assert key not in env, key


def test_launch_new_terminal_no_token_in_argv_or_env(monkeypatch, capsys):
    _setup_launch_mocks(monkeypatch)
    monkeypatch.setenv("WAYLAND_DISPLAY", "1")
    monkeypatch.setattr(
        launcher.shutil,
        "which",
        lambda cmd, path=None: "/usr/bin/xdg-terminal-exec" if cmd == "xdg-terminal-exec" else None,
    )
    popen_calls = []

    def fake_popen(cmd, env=None, start_new_session=False):
        popen_calls.append((list(cmd), dict(env or {}), start_new_session))
        m = MagicMock()
        m.pid = 1
        return m

    monkeypatch.setattr(launcher.subprocess, "Popen", fake_popen)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 0
    assert popen_calls
    cmd, env, sns = popen_calls[0]
    assert cmd[0] == "xdg-terminal-exec"
    assert "--here" in cmd
    joined = " ".join(cmd)
    assert "tok" not in joined
    assert env is not None
    assert "ANTHROPIC_AUTH_TOKEN" not in env
    assert "ANTHROPIC_BASE_URL" not in env
    out = capsys.readouterr().out
    assert "opened a new terminal: Claude Code on go" in out


def test_launch_headless_prints_command(monkeypatch, capsys):
    _setup_launch_mocks(monkeypatch)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd, path=None: None)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "python3" in out
    assert "--here" in out


def test_print_cmd(monkeypatch, capsys):
    _setup_launch_mocks(monkeypatch)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.setattr(launcher.shutil, "which", lambda cmd, path=None: None)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go", "--print-cmd"])
    assert exc.value.code == 0
    out = capsys.readouterr().out
    assert "go --here" in out


def test_claude_tier_id_refused(monkeypatch, capsys):
    monkeypatch.setenv("FROOD_CC_GO_OPUS", "claude-sonnet-4-6")
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    launched = []

    def fake_execvpe(*a):
        launched.append(a)
        raise SystemExit(0)

    monkeypatch.setattr(launcher.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        launcher.main(["go"])
    assert exc.value.code == 2
    assert launched == []
    assert "claude" in capsys.readouterr().out.lower()


# --- old modes -----------------------------------------------------------------


@pytest.mark.parametrize("mode", ["zen", "opencode", "cmdcode", "openrouter"])
def test_old_modes_exit_2(monkeypatch, capsys, mode):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    with pytest.raises(SystemExit) as exc:
        launcher.main([mode])
    assert exc.value.code == 2
    assert "go | nvidia | cc | status" in capsys.readouterr().out


def test_no_arg_usage(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    with pytest.raises(SystemExit) as exc:
        launcher.main([])
    assert exc.value.code == 2


def test_unknown_mode(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    with pytest.raises(SystemExit) as exc:
        launcher.main(["bogus"])
    assert exc.value.code == 2


# --- status --------------------------------------------------------------------


def test_status(monkeypatch, capsys):
    monkeypatch.setattr(launcher, "ensure_token", lambda p=None: "tok")
    monkeypatch.setattr(launcher, "read_token", lambda p=None: "status-token-123")
    _patch_fetch(monkeypatch, 200, 200, {"data": [{"id": "kimi-k3"}]})
    monkeypatch.setenv("FROOD_CC_MODE", "go")
    with pytest.raises(SystemExit) as exc:
        launcher.main(["status"])
    assert exc.value.code == 0
    captured = capsys.readouterr()
    out = captured.out
    err = captured.err
    assert "status-token-123" not in out and "status-token-123" not in err
    assert err == ""
    assert "frood health:" in out
    assert "gateway:" in out
    assert "go tier ids:" in out
    assert "nvidia tier ids:" in out
    assert "current mode: go" in out


# --- command file --------------------------------------------------------------


def test_command_file_contents():
    cmd = ROOT / ".claude" / "commands" / "frood-cc.md"
    text = cmd.read_text(encoding="utf-8")
    for token in ("go", "nvidia", "cc", "/gw"):
        assert token in text, token
    for bad in ("zen", "takeover", "/llm/v1"):
        assert bad not in text, bad
    assert "frood-cc-launcher.py" in text

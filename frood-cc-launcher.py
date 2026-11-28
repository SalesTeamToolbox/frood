#!/usr/bin/env python3
"""
frood-cc-launcher.py - Launch terminal Claude Code through the Frood gateway (/gw).

Usage:
    python frood-cc-launcher.py [MODE] [--here] [--print-cmd] [--isolated] [--no-check] [--] [claude args...]

Modes:
    go        Claude Code via OpenCode Go models through the Frood gateway.
    nvidia    Claude Code via Nvidia models through the Frood gateway.
    cc        Claude Code on the owner's normal Anthropic subscription (no gateway).
    status    Print one-line health, gateway and tier status.

Flags:
    --here        Replace this process with claude in the current terminal (execvpe).
    --print-cmd   Print the one-line launch command only; do not launch.
    --isolated    Use an isolated CLAUDE_CONFIG_DIR (XDG_CONFIG_HOME/frood/cc-gateway).
    --no-check    Skip the /gw/v1/models tier-id list check (health + auth still run).

Extra args after `--` are passed verbatim to `claude`.

With no argument, prints usage and exits 2. The old modes zen/opencode/cmdcode/openrouter
exit 2 with a pointer to the new modes.

The gateway token is read from FROOD_GATEWAY_TOKEN in the repo .env (next to this file),
generated there if missing, and passed to Claude Code only through the child process
environment -- never in argv and never printed.
"""

import fnmatch
import os
import secrets
import shutil
import stat
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

# --- Constants -----------------------------------------------------------------

GATEWAY_URL = os.getenv("FROOD_GATEWAY_URL", "http://127.0.0.1:8000/gw")
# Health lives at the gateway host without the /gw prefix, honoring the override.
_HEALTH_HOST = GATEWAY_URL.removesuffix("/gw")
HEALTH_URL = f"{_HEALTH_HOST}/health"
MODELS_URL = f"{GATEWAY_URL}/v1/models"

ENV_PATH = Path(__file__).resolve().parent / ".env"

# Tier model ids, each overridable by its own env var.
GO_OPUS_DEFAULT = "kimi-k3"
GO_SONNET_DEFAULT = "glm-5.3-flash"
GO_HAIKU_DEFAULT = "deepseek-v4.1-flash"
NV_OPUS_DEFAULT = "nvidia/nemotron-3.5-super-vl-120b-a12b"
NV_SONNET_DEFAULT = "nvidia/nemotron-3.5-super-vl-120b-a12b"
NV_HAIKU_DEFAULT = "qwen/qwen3-coder-480b-a35b-instruct"

GO_OPUS_ENV = "FROOD_CC_GO_OPUS"
GO_SONNET_ENV = "FROOD_CC_GO_SONNET"
GO_HAIKU_ENV = "FROOD_CC_GO_HAIKU"
NV_OPUS_ENV = "FROOD_CC_NV_OPUS"
NV_SONNET_ENV = "FROOD_CC_NV_SONNET"
NV_HAIKU_ENV = "FROOD_CC_NV_HAIKU"

MODE_LABELS = {"go": "Go", "nvidia": "Nvidia"}

CONTEXT_TOKENS_DEFAULT = 128000
COMPACT_WINDOW_DEFAULT = 100000
CONTEXT_TOKENS_ENV = "FROOD_CC_CONTEXT_TOKENS"
COMPACT_WINDOW_ENV = "FROOD_CC_COMPACT_WINDOW"

# Env var allowlist copied into the child (exact matches, plus LC_* and XDG_*).
ALLOWLIST_EXACT = {
    "HOME",
    "USER",
    "LOGNAME",
    "PATH",
    "SHELL",
    "TERM",
    "COLORTERM",
    "LANG",
    "TZ",
    "TMPDIR",
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "EDITOR",
    "VISUAL",
}

# Denylist wins over the allowlist. Dropped: the desktop app's CLAUDE_CODE_* host-auth
# vars, ANTHROPIC_BASE_URL/ANTHROPIC_API_KEY, ELECTRON/OTEL telemetry, API keys, and
# any *TOKEN* (the gateway token is re-set below, by necessity, in the child env).
# SSH_AUTH_SOCK and DBUS_SESSION_BUS_ADDRESS are also dropped: model-run shell commands
# would otherwise inherit them.
DENY_PATTERNS = (
    "CLAUDE*",
    "ANTHROPIC*",
    "CLAUDECODE",
    "ELECTRON*",
    "OTEL*",
    "*_API_KEY",
    "*TOKEN*",
)
DENY_EXACT = {"SSH_AUTH_SOCK", "DBUS_SESSION_BUS_ADDRESS"}

EXIT_USAGE = 2
EXIT_MISSING_CLAUDE = 1
EXIT_PREFAIL = 1

GATEWAY_ERROR_CAP = 200


# --- .env / token --------------------------------------------------------------


def _strip_quotes(value: str) -> str:
    value = value.strip()
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
        return value[1:-1]
    return value


def read_token(env_path: Path = ENV_PATH):
    """Return FROOD_GATEWAY_TOKEN from a simple KEY=VALUE .env file, or None.

    Ignores comment lines and blank lines; strips surrounding quotes. Never prints
    or logs the token.
    """
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() == "FROOD_GATEWAY_TOKEN":
            value = _strip_quotes(value)
            if value:
                return value
            # Empty value is treated as missing: the key will be (re)generated.
    return None


def ensure_token(env_path: Path = ENV_PATH) -> str:
    """Return the gateway token, generating and persisting it if missing.

    A missing key is generated with secrets.token_urlsafe(32) and appended to .env.
    A missing .env is created with mode 0600. An existing file's mode is left
    unchanged unless it is looser than 0600, in which case it is tightened and one
    line is printed. Returns the token (never printed).
    """
    token = read_token(env_path)
    if token:
        return token

    token = secrets.token_urlsafe(32)
    line = f"FROOD_GATEWAY_TOKEN={token}\n"

    try:
        if not env_path.exists():
            fd = os.open(str(env_path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(line)
            os.chmod(str(env_path), 0o600)
        else:
            text = env_path.read_text(encoding="utf-8")
            if text and not text.endswith("\n"):
                line = "\n" + line
            with open(str(env_path), "a", encoding="utf-8") as handle:
                handle.write(line)
            mode = stat.S_IMODE(os.stat(str(env_path)).st_mode)
            if mode != 0o600:
                os.chmod(str(env_path), 0o600)
                print(f"tightened .env permissions to 0600: {env_path}")
    except OSError as exc:
        print(f"cannot write gateway token to {env_path}: {exc}")
        sys.exit(EXIT_PREFAIL)

    print(
        "generated a gateway token in .env: restart Frood (python frood.py) "
        "so the gateway picks it up"
    )
    return token


# --- Env building --------------------------------------------------------------


def _allowed(key: str) -> bool:
    return key in ALLOWLIST_EXACT or key.startswith("LC_") or key.startswith("XDG_")


def _denied(key: str) -> bool:
    if key in DENY_EXACT:
        return True
    return any(fnmatch.fnmatchcase(key, pat) for pat in DENY_PATTERNS)


def _tier_ids(mode: str):
    """Return (opus, sonnet, haiku) for the mode, honoring env overrides."""
    if mode == "go":
        return (
            os.getenv(GO_OPUS_ENV, GO_OPUS_DEFAULT),
            os.getenv(GO_SONNET_ENV, GO_SONNET_DEFAULT),
            os.getenv(GO_HAIKU_ENV, GO_HAIKU_DEFAULT),
        )
    return (
        os.getenv(NV_OPUS_ENV, NV_OPUS_DEFAULT),
        os.getenv(NV_SONNET_ENV, NV_SONNET_DEFAULT),
        os.getenv(NV_HAIKU_ENV, NV_HAIKU_DEFAULT),
    )


def _int_env(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


def _clean_path(path: str) -> str:
    """Return PATH with Windows-style entries removed (drive letters, backslashes).

    A no-op on a normal Linux PATH; keeps the Mandate's "remove the Windows paths"
    requirement fulfilled even when base_env was copied from a mixed/Cross-OS shell.
    """
    if not path:
        return path
    keep = []
    for entry in path.split(os.pathsep):
        if not entry:
            continue
        if ":" in entry and entry[0].isalpha() and len(entry) >= 2 and entry[1] == ":":
            continue  # Windows drive letter, e.g. C:\tools
        if "\\" in entry:
            continue  # Windows backslash path
        keep.append(entry)
    return os.pathsep.join(keep)


def _isolated_config_dir() -> str:
    base = os.getenv("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return str(Path(base) / "frood" / "cc-gateway")


def build_env(mode: str, token: str, base_env: dict, isolated: bool = False) -> dict:
    """Pure function: return the child process env for the given mode.

    Starts from an allowlist of base_env, applies the denylist, then adds the
    gateway/tier variables for go/nvidia. Never prints or logs the token.
    """
    env = {}
    for key, value in base_env.items():
        if _allowed(key) and not _denied(key):
            env[key] = _clean_path(value) if key == "PATH" else value

    mode = mode.lower()
    if mode in ("go", "nvidia"):
        env["ANTHROPIC_BASE_URL"] = GATEWAY_URL
        env["ANTHROPIC_AUTH_TOKEN"] = token
        opus, sonnet, haiku = _tier_ids(mode)
        label = MODE_LABELS[mode]
        env["ANTHROPIC_DEFAULT_OPUS_MODEL"] = opus
        env["ANTHROPIC_DEFAULT_SONNET_MODEL"] = sonnet
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL"] = haiku
        env["ANTHROPIC_DEFAULT_OPUS_MODEL_NAME"] = f"{label} {opus}"
        env["ANTHROPIC_DEFAULT_SONNET_MODEL_NAME"] = f"{label} {sonnet}"
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL_NAME"] = f"{label} {haiku}"
        env["ANTHROPIC_DEFAULT_OPUS_MODEL_SUPPORTED_CAPABILITIES"] = ""
        env["ANTHROPIC_DEFAULT_SONNET_MODEL_SUPPORTED_CAPABILITIES"] = ""
        env["ANTHROPIC_DEFAULT_HAIKU_MODEL_SUPPORTED_CAPABILITIES"] = ""
        env.pop("CLAUDE_CODE_SUBAGENT_MODEL", None)
        env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(
            _int_env(CONTEXT_TOKENS_ENV, CONTEXT_TOKENS_DEFAULT)
        )
        env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"] = str(
            _int_env(COMPACT_WINDOW_ENV, COMPACT_WINDOW_DEFAULT)
        )
        env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
        env["DISABLE_TELEMETRY"] = "1"
        env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"] = "1"
        env["FROOD_CC_MODE"] = mode
    # cc: allowlist only, no gateway or tier variables.

    if isolated:
        config_dir = _isolated_config_dir()
        Path(config_dir).mkdir(parents=True, exist_ok=True)
        os.chmod(config_dir, 0o700)
        env["CLAUDE_CONFIG_DIR"] = config_dir

    return env


# --- HTTP preflight ------------------------------------------------------------


def _fetch_json(url: str, headers: dict, timeout: float = 5.0):
    """GET url, return (status, parsed_json_or_None, error_message_or_None)."""
    req = urllib.request.Request(url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        return exc.code, None, body
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        return None, None, str(exc)
    try:
        import json

        return 200, json.loads(body), None
    except (ValueError, TypeError):
        return 200, None, body


def _gateway_error_message(body: str, token: str, status: int | None = None) -> str:
    """Extract error.message from a gateway JSON body, capped and token-redacted.

    Never echoes the raw body: when the JSON carries no error.message, fall back
    to a fixed description naming the HTTP status.
    """
    message = ""
    try:
        import json

        data = json.loads(body)
        if isinstance(data, dict):
            err = data.get("error")
            if isinstance(err, dict):
                message = err.get("message", "") or ""
            elif isinstance(err, str):
                message = err
    except (ValueError, TypeError):
        pass
    if not message:
        message = f"gateway error (HTTP {status})" if status is not None else "gateway error"
    message = message.replace(token, "***")
    return message[:GATEWAY_ERROR_CAP]


def preflight(mode: str, token: str, no_check: bool) -> None:
    """Run gateway preflight for go/nvidia. Exits on failure."""
    # 1. Health.
    try:
        status, _, _ = _fetch_json(HEALTH_URL, {})
    except Exception:
        status = None
    if status != 200:
        print("Frood is not running: start it with `python frood.py`")
        sys.exit(EXIT_PREFAIL)

    # 2. /gw/v1/models with bearer auth.
    headers = {"Authorization": f"Bearer {token}"}
    status, data, body = _fetch_json(MODELS_URL, headers)

    if status == 401:
        print("gateway token mismatch: restart Frood after the token was generated")
        sys.exit(EXIT_PREFAIL)
    if status == 503:
        print(_gateway_error_message(body or "", token, status))
        sys.exit(EXIT_PREFAIL)
    if status == 404:
        print("this Frood has no gateway (/gw); update and restart Frood")
        sys.exit(EXIT_PREFAIL)
    if status != 200 or not isinstance(data, dict):
        print(f"gateway /gw/v1/models unexpected ({status}); is Frood running?")
        sys.exit(EXIT_PREFAIL)

    listed = {m.get("id") for m in (data.get("data") or []) if isinstance(m, dict)}
    missing = [tid for tid in _tier_ids(mode) if tid not in listed]
    if missing and not no_check:
        names = ", ".join(missing)
        if mode == "nvidia":
            print(
                f"gateway does not list tier model id(s): {names} "
                "(Nvidia routing ships in T3; use --no-check to launch anyway)"
            )
        else:
            print(f"gateway does not list tier model id(s): {names}")
        sys.exit(EXIT_PREFAIL)


# --- Launch --------------------------------------------------------------------


def find_claude(env: dict) -> str:
    """Find the claude executable on the clean env's PATH. Exit if missing."""
    path = shutil.which("claude", path=env.get("PATH", os.defpath))
    if not path:
        print("claude is not on PATH: install Claude Code and try again")
        sys.exit(EXIT_MISSING_CLAUDE)
    return path


def launch_here(claude: str, claude_args: list, env: dict) -> None:
    """Replace this process with claude in the current terminal."""
    os.execvpe(claude, [claude, *claude_args], env)  # noqa: S606


def launch_new_terminal(
    claude: str, mode: str, flags: list, claude_args: list, env: dict, launcher_path: str
) -> None:
    """Open a new terminal running this launcher with --here."""
    child_env = {
        k: v
        for k, v in env.items()
        if k not in ("ANTHROPIC_BASE_URL", "ANTHROPIC_AUTH_TOKEN", "FROOD_CC_MODE")
        and not k.startswith("ANTHROPIC_DEFAULT_")
    }
    cmd = ["xdg-terminal-exec", sys.executable, launcher_path, mode, "--here"]
    cmd.extend(flags)
    cmd.extend(["--", *claude_args])
    subprocess.Popen(cmd, env=child_env, start_new_session=True)
    print(f"opened a new terminal: Claude Code on {mode}")
    sys.exit(0)


def print_command(
    mode: str, flags: list, claude_args: list, launcher_path: str, here: bool
) -> None:
    """Print the one-line launch command."""
    parts = ["python3", launcher_path, mode]
    if here:
        parts.append("--here")
    parts.extend(flags)
    if claude_args:
        parts.extend(["--", *claude_args])
    print(" ".join(parts))


# --- status --------------------------------------------------------------------


def status() -> None:
    """Print one-line status for health, gateway, tiers and current mode."""
    # Frood health.
    try:
        h_status, _, _ = _fetch_json(HEALTH_URL, {}, timeout=3.0)
        if h_status is None:
            health = "unreachable"
        elif h_status == 200:
            health = "ok"
        else:
            health = f"unreachable ({h_status})"
    except Exception:
        health = "unreachable"
    print(f"frood health: {health}")

    # Gateway reachability + auth (no token shown). Read-only token read only;
    # status never generates or writes .env.
    token = read_token(ENV_PATH)
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    try:
        g_status, _, _ = _fetch_json(MODELS_URL, headers, timeout=5.0)
        if g_status is None:
            gateway = "unreachable"
        elif g_status == 401:
            gateway = "reachable, auth required"
        elif g_status == 200:
            gateway = "reachable, auth ok"
        else:
            gateway = f"reachable ({g_status})"
    except Exception:
        gateway = "unreachable"
    print(f"gateway: {gateway}")

    # Tier ids.
    go_ids = ", ".join(_tier_ids("go"))
    nv_ids = ", ".join(_tier_ids("nvidia"))
    print(f"go tier ids: {go_ids}")
    print(f"nvidia tier ids: {nv_ids}")

    # Current mode.
    mode = os.getenv("FROOD_CC_MODE")
    print(f"current mode: {mode if mode else 'subscription'}")


# --- CLI -----------------------------------------------------------------------


def usage() -> str:
    return __doc__


def parse_args(argv: list):
    """Parse argv into (mode, flags, claude_args).

    flags: dict with here/print_cmd/isolated/no_check booleans.
    Returns (mode or None, flags, claude_args).
    """
    flags = {"here": False, "print_cmd": False, "isolated": False, "no_check": False}
    mode = None
    claude_args = []
    after_dash_dash = False
    for token in argv:
        if after_dash_dash:
            claude_args.append(token)
            continue
        if token == "--":
            after_dash_dash = True
            continue
        if token == "--here":
            flags["here"] = True
        elif token == "--print-cmd":
            flags["print_cmd"] = True
        elif token == "--isolated":
            flags["isolated"] = True
        elif token == "--no-check":
            flags["no_check"] = True
        elif token.startswith("--") or token.startswith("-"):
            # Unknown flag: ignore (or could error); treat as claude arg only if after mode.
            # Keep simple: unknown leading flags are errors handled by mode routing below.
            claude_args.append(token)
        elif mode is None:
            mode = token
        else:
            claude_args.append(token)
    return mode, flags, claude_args


OLD_MODES = {"zen", "opencode", "cmdcode", "openrouter"}


def main(argv: list | None = None) -> int:
    if argv is None:
        argv = sys.argv[1:]

    if not argv:
        print(usage())
        sys.exit(EXIT_USAGE)

    mode, flags, claude_args = parse_args(argv)

    if mode is None:
        print(usage())
        sys.exit(EXIT_USAGE)

    mode_lower = mode.lower()

    # Old modes: pointer to the new ones, exit 2.
    if mode_lower in OLD_MODES:
        print(
            f"'{mode}' is retired. Use: go | nvidia | cc | status  "
            "(targets the Frood gateway at /gw). Run `python frood-cc-launcher.py` for usage."
        )
        sys.exit(EXIT_USAGE)

    if mode_lower not in ("go", "nvidia", "cc", "status"):
        print(f"unknown mode: {mode}")
        print(usage())
        sys.exit(EXIT_USAGE)

    flags_list = []
    if flags["isolated"]:
        flags_list.append("--isolated")
    if flags["no_check"]:
        flags_list.append("--no-check")

    if mode_lower == "status":
        status()
        sys.exit(0)

    # Models starting with claude never go through the gateway.
    if mode_lower in ("go", "nvidia"):
        for tid in _tier_ids(mode_lower):
            if tid.lower().startswith("claude"):
                print(
                    f"tier model id '{tid}' starts with 'claude' and is refused: "
                    "models starting with claude never go through the gateway"
                )
                sys.exit(EXIT_USAGE)

    # Token (read or generate) — needed only for gateway modes (go/nvidia).
    # cc and status never touch the gateway, so they never create or read .env.
    token = None
    if mode_lower in ("go", "nvidia"):
        token = ensure_token(ENV_PATH)

    launcher_path = str(Path(__file__).resolve())

    if flags["print_cmd"]:
        print_command(mode_lower, flags_list, claude_args, launcher_path, here=True)
        sys.exit(0)

    # Preflight for go/nvidia.
    if mode_lower in ("go", "nvidia"):
        preflight(mode_lower, token, flags["no_check"])

    # Build the clean child env.
    base_env = dict(os.environ)
    env = build_env(mode_lower, token, base_env, isolated=flags["isolated"])

    claude = find_claude(env)

    if flags["here"]:
        launch_here(claude, claude_args, env)

    # Default: new terminal when a display is available, else print the command.
    has_display = bool(os.getenv("WAYLAND_DISPLAY") or os.getenv("DISPLAY"))
    if has_display and shutil.which("xdg-terminal-exec"):
        launch_new_terminal(claude, mode_lower, flags_list, claude_args, env, launcher_path)

    print_command(mode_lower, flags_list, claude_args, launcher_path, here=True)
    sys.exit(0)


if __name__ == "__main__":
    sys.exit(main())

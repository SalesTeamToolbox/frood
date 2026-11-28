"""Install Frood as a systemd user service (Linux only).

Frood is normally started by hand (``.venv/bin/python frood.py``), so a crash
or a reboot leaves the ``/gw`` gateway dead. This installer writes a
``frood.service`` user unit from ``ops/systemd/frood.service``, enables it so
Frood starts at login, and starts it now — unless the port is already taken
by a hand-started Frood, in which case the unit is enabled but not started
and nothing is killed. Switching the live Frood over is the orchestrator's
job after ship.

Usage:
    python3 ops/frood_service.py install [--port N] [--dry-run]
    python3 ops/frood_service.py uninstall [--dry-run]
    python3 ops/frood_service.py status

Environment overrides (for tests):
    FROOD_SERVICE_UNIT_DIR  unit directory (default ~/.config/systemd/user)
    FROOD_SYSTEMCTL         systemctl binary (default systemctl)
    FROOD_SERVICE_LOG       log path (default ~/.local/state/frood/frood-http.log)
"""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
from pathlib import Path

UNIT_NAME = "frood.service"
TEMPLATE_PATH = Path(__file__).resolve().parent / "systemd" / "frood.service"
SYSTEMCTL_TIMEOUT = 30

_LEFTOVER_RE = re.compile(r"@[A-Z_]+@")


def repo_root() -> Path:
    """Repo root this file lives in (resolved, absolute)."""
    return Path(__file__).resolve().parents[1]


def is_worktree_repo(repo: Path | str) -> bool:
    """True when the repo path is inside a ``/.claude/worktrees/`` checkout."""
    return "/.claude/worktrees/" in str(repo)


def default_unit_dir() -> Path:
    if override := os.environ.get("FROOD_SERVICE_UNIT_DIR"):
        return Path(override)
    return Path.home() / ".config" / "systemd" / "user"


def default_log_path() -> Path:
    if override := os.environ.get("FROOD_SERVICE_LOG"):
        return Path(override)
    return Path.home() / ".local" / "state" / "frood" / "frood-http.log"


def systemctl_bin() -> str:
    return os.environ.get("FROOD_SYSTEMCTL", "systemctl")


def check_platform() -> int | None:
    """Return 0 (and print the skip line) on non-Linux, else None."""
    if sys.platform != "linux":
        print("skipped (non-linux)")
        return 0
    return None


def resolve_python(repo: Path | str) -> Path:
    """Return ``<repo>/.venv/bin/python``; never fall back to system python."""
    candidate = Path(repo) / ".venv" / "bin" / "python"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        return candidate
    raise FileNotFoundError(
        f"error: {candidate} not found or not executable; "
        "refusing to fall back to system python (it lacks Frood's dependencies). "
        "Create the venv first (make install)."
    )


def build_path_value() -> tuple[str, list[str]]:
    """Build ``PATH=`` from the installing shell's PATH.

    Keeps absolute existing directories only, de-duplicated, order kept;
    drops any directory inside a ``.claude/worktrees/`` path. Returns the
    joined value and a list of warnings (e.g. claude/opencode missing).
    """
    seen: set[str] = set()
    kept: list[str] = []
    for entry in os.environ.get("PATH", "").split(os.pathsep):
        if not entry or not os.path.isabs(entry):
            continue
        if "/.claude/worktrees/" in entry:
            continue
        if not os.path.isdir(entry):
            continue
        if entry in seen:
            continue
        seen.add(entry)
        kept.append(entry)
    warnings: list[str] = []
    for tool in ("claude", "opencode"):
        if not any(
            os.path.isfile(os.path.join(d, tool)) and os.access(os.path.join(d, tool), os.X_OK)
            for d in kept
        ):
            warnings.append(f"warning: {tool} not found on PATH for the unit")
    return os.pathsep.join(kept), warnings


def read_dashboard_host(repo: Path | str) -> str:
    """Read DASHBOARD_HOST from ``<repo>/.env`` (simple KEY=value parse)."""
    env_file = Path(repo) / ".env"
    try:
        text = env_file.read_text(encoding="utf-8")
    except OSError:
        return "127.0.0.1"
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        if key.strip() != "DASHBOARD_HOST":
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        return value or "127.0.0.1"
    return "127.0.0.1"


def render_unit(repo: Path | str, python: Path | str, port: int, path: str, log: Path | str) -> str:
    """Render the unit template. Pure: creates nothing on disk."""
    text = TEMPLATE_PATH.read_text(encoding="utf-8")
    text = (
        text.replace("@REPO@", str(repo))
        .replace("@PYTHON@", str(python))
        .replace("@PORT@", str(port))
        .replace("@PATH@", path)
        .replace("@LOG@", str(log))
    )
    leftover = _LEFTOVER_RE.search(text)
    if leftover:
        raise ValueError(f"unfilled placeholder(s) in rendered unit: {leftover.group(0)}")
    return text


def run_systemctl(*args: str) -> subprocess.CompletedProcess[str]:
    """Run one ``systemctl --user ...`` call with a timeout; never raises.

    A missing binary or a hung systemctl becomes a non-zero return code
    (127 / 124) with the reason on stderr, so every call site reports the
    failure with its exit code instead of ending in a traceback.
    """
    argv = [systemctl_bin(), "--user", *args]
    try:
        return subprocess.run(
            argv,
            capture_output=True,
            text=True,
            timeout=SYSTEMCTL_TIMEOUT,
        )
    except FileNotFoundError as exc:
        return subprocess.CompletedProcess(argv, 127, "", f"systemctl not found: {exc}")
    except OSError as exc:
        return subprocess.CompletedProcess(argv, 127, "", str(exc))
    except subprocess.TimeoutExpired:
        return subprocess.CompletedProcess(
            argv, 124, "", f"systemctl timed out after {SYSTEMCTL_TIMEOUT}s"
        )


def query_unit_state(name: str, query: str) -> str:
    """Query ``is-active``/``is-enabled``; non-zero exit only means "no"."""
    try:
        proc = run_systemctl(query, name)
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    out = proc.stdout.strip()
    return out if out else ("inactive" if query == "is-active" else "disabled")


def is_port_busy(host: str, port: int) -> bool:
    """True when something already holds (host, port). Plain TCP bind with no
    SO_REUSEADDR, so it errs toward "busy"."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind((host, port))
    except OSError:
        return True
    finally:
        sock.close()
    return False


def cmd_install(
    repo: Path | str,
    port: int = 8000,
    dry_run: bool = False,
) -> int:
    """Write, enable, and (port permitting) start the unit. Returns exit code."""
    if (rc := check_platform()) is not None:
        return rc
    repo = Path(repo)
    if is_worktree_repo(repo):
        print(
            f"error: refusing to install from a worktree ({repo}); "
            "run the installer from the main checkout after ship.",
            file=sys.stderr,
        )
        return 2
    try:
        python = resolve_python(repo)
    except FileNotFoundError as exc:
        print(exc, file=sys.stderr)
        return 2
    path_value, warnings = build_path_value()
    log_path = default_log_path()
    unit = render_unit(repo, python, port, path_value, log_path)
    unit_dir = default_unit_dir()
    unit_path = unit_dir / UNIT_NAME

    for warning in warnings:
        print(warning)

    if dry_run:
        print(unit, end="" if unit.endswith("\n") else "\n")
        for call in (
            "daemon-reload",
            f"enable {UNIT_NAME}",
            f"is-active {UNIT_NAME}  (check only; decides start vs restart)",
            f"reset-failed {UNIT_NAME}  (only if not active and port is free)",
            f"start {UNIT_NAME}  (only if not active and port is free)",
        ):
            print(f"would run: systemctl --user {call}")
        return 0

    log_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        existing = unit_path.read_text(encoding="utf-8")
    except OSError:
        existing = None
    changed = existing != unit
    if changed:
        unit_dir.mkdir(parents=True, exist_ok=True)
        unit_path.write_text(unit, encoding="utf-8")

    for call in ("daemon-reload", f"enable {UNIT_NAME}"):
        proc = run_systemctl(*call.split())
        if proc.returncode != 0:
            print(
                f"error: systemctl --user {call} failed (exit {proc.returncode}): "
                f"{proc.stderr.strip()}",
                file=sys.stderr,
            )
            return proc.returncode

    if query_unit_state(UNIT_NAME, "is-active") == "active":
        if changed:
            proc = run_systemctl("restart", UNIT_NAME)
            if proc.returncode != 0:
                print(
                    f"error: systemctl --user restart {UNIT_NAME} failed "
                    f"(exit {proc.returncode}): {proc.stderr.strip()}",
                    file=sys.stderr,
                )
                return proc.returncode
            print(f"restarted {UNIT_NAME} (unit changed)")
        else:
            print(f"{UNIT_NAME} already running")
        return 0

    host = read_dashboard_host(repo)
    if is_port_busy(host, port):
        print(
            f"port {port} is in use: stop the running Frood by its pid, then run: "
            f"systemctl --user start {UNIT_NAME}"
        )
        return 0
    proc = run_systemctl("reset-failed", UNIT_NAME)
    if proc.returncode != 0:
        print(
            f"warning: systemctl --user reset-failed {UNIT_NAME} failed "
            f"(exit {proc.returncode}): {proc.stderr.strip()}"
        )
    proc = run_systemctl("start", UNIT_NAME)
    if proc.returncode != 0:
        print(
            f"error: systemctl --user start {UNIT_NAME} failed "
            f"(exit {proc.returncode}): {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return proc.returncode
    print(f"started {UNIT_NAME}")
    return 0


def cmd_uninstall(dry_run: bool = False) -> int:
    """Disable, remove the unit file, reload. Returns exit code."""
    if (rc := check_platform()) is not None:
        return rc
    unit_path = default_unit_dir() / UNIT_NAME
    if dry_run:
        print(f"would run: systemctl --user disable --now {UNIT_NAME}")
        print(f"would remove: {unit_path}")
        print("would run: systemctl --user daemon-reload")
        return 0
    proc = run_systemctl("disable", "--now", UNIT_NAME)
    if proc.returncode != 0:
        print(
            f"error: systemctl --user disable --now {UNIT_NAME} failed "
            f"(exit {proc.returncode}): {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return proc.returncode
    try:
        unit_path.unlink()
    except FileNotFoundError:
        pass
    proc = run_systemctl("daemon-reload")
    if proc.returncode != 0:
        print(
            f"error: systemctl --user daemon-reload failed "
            f"(exit {proc.returncode}): {proc.stderr.strip()}",
            file=sys.stderr,
        )
        return proc.returncode
    print(f"uninstalled {UNIT_NAME}")
    return 0


def cmd_status() -> int:
    """Print is-active/is-enabled and the unit path. Always exit 0."""
    if (rc := check_platform()) is not None:
        return rc
    unit_path = default_unit_dir() / UNIT_NAME
    print(f"unit: {unit_path}")
    print(f"is-active: {query_unit_state(UNIT_NAME, 'is-active')}")
    print(f"is-enabled: {query_unit_state(UNIT_NAME, 'is-enabled')}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Install Frood as a systemd user service.")
    sub = parser.add_subparsers(dest="command", required=True)
    install = sub.add_parser("install", help="write, enable, and start frood.service")
    install.add_argument("--port", type=int, default=8000, help="dashboard port (default: 8000)")
    install.add_argument("--dry-run", action="store_true", help="print only; change nothing")
    uninstall = sub.add_parser("uninstall", help="disable and remove frood.service")
    uninstall.add_argument("--dry-run", action="store_true", help="print only; change nothing")
    sub.add_parser("status", help="show unit state and path")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "install":
        return cmd_install(repo_root(), port=args.port, dry_run=args.dry_run)
    if args.command == "uninstall":
        return cmd_uninstall(dry_run=args.dry_run)
    return cmd_status()


if __name__ == "__main__":
    sys.exit(main())

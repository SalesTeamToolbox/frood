"""
GIT_ASKPASS-based authentication — keeps tokens out of command-line args and URLs.

Usage::

    with git_askpass_env(token, base_env) as env:
        proc = await asyncio.create_subprocess_exec("git", "clone", url, env=env)

The context manager creates a temporary helper script that echoes the token
when invoked by git, sets ``GIT_ASKPASS`` and ``GIT_TERMINAL_PROMPT=0``,
and cleans up the script on exit.
"""

import logging
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger("agent42.git_auth")


@contextmanager
def git_askpass_env(token: str, base_env: dict[str, str] | None = None):
    """Yield an env dict with ``GIT_ASKPASS`` pointing to a temp script.

    The script simply prints *token* when invoked.  On Windows a ``.bat``
    file is created; on Unix a ``.sh`` file with ``+x``.

    If *token* is empty the base env is returned unchanged (no-op).
    """
    env = dict(base_env) if base_env else dict(os.environ)

    if not token:
        yield env
        return

    script_path = None
    try:
        if sys.platform == "win32":
            fd, script_path = tempfile.mkstemp(suffix=".bat", prefix="git_askpass_")
            os.close(fd)
            Path(script_path).write_text(f"@echo {token}\n")
        else:
            fd, script_path = tempfile.mkstemp(suffix=".sh", prefix="git_askpass_")
            os.close(fd)
            Path(script_path).write_text(f"#!/bin/sh\necho '{token}'\n")
            os.chmod(script_path, stat.S_IRWXU)

        env["GIT_ASKPASS"] = script_path
        env["GIT_TERMINAL_PROMPT"] = "0"
        yield env
    finally:
        if script_path:
            try:
                os.unlink(script_path)
            except OSError:
                pass

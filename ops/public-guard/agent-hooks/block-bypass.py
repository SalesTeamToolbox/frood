#!/usr/bin/env python3
"""Claude Code PreToolUse hook: deny Bash commands that bypass public-guard.

Protocol: JSON on stdin ({"tool_name", "tool_input": {"command"}, "cwd"}); exit 2 with the
reason on stderr denies the call. Exit 0 allows. Anything unparseable is allowed (this is a
tripwire for a careless agent, the git hooks and CI are the real enforcement).
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = (".config/public-guard", ".cache/public-guard", ".git/hooks")
WRITE_VERBS = {
    "rm",
    "mv",
    "cp",
    "chmod",
    "chown",
    "ln",
    "tee",
    "sed",
    "truncate",
    "touch",
    "dd",
    "install",
    "rsync",
    "unlink",
    "shred",
    "rmdir",
    "mkdir",
    "patch",
    "awk",
    "perl",
    "ed",
}
INTERPRETERS = {"python", "python3", "node", "ruby", "perl", "bash", "sh", "zsh"}
GIT_ENV_EVASION = re.compile(
    r"(?:^|[\s;&|])(?:HOME|XDG_CONFIG_HOME|GIT_CONFIG_GLOBAL|GIT_CONFIG_SYSTEM|GIT_CONFIG_COUNT|GIT_CONFIG_PARAMETERS|GIT_CONFIG_NOSYSTEM|GIT_DIR)="
)


def deny(reason: str) -> None:
    sys.stderr.write(
        f"public-guard bypass blocked: {reason}\nDo not retry. Report this to the owner verbatim.\n"
    )
    sys.exit(2)


def split_segments(cmd: str) -> list[str]:
    return [s.strip() for s in re.split(r"\n|;|&&|\|\||\||&(?!>)", cmd) if s.strip()]


def tokens(seg: str) -> list[str]:
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.split()


def load_guard():
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (
        os.path.join(here, "..", "guard.py"),
        os.path.join(os.path.expanduser("~"), ".config", "public-guard", "guard.py"),
    ):
        if os.path.exists(cand):
            try:
                spec = importlib.util.spec_from_file_location("public_guard_guard", cand)
                mod = importlib.util.module_from_spec(spec)  # type: ignore[arg-type]
                spec.loader.exec_module(mod)  # type: ignore[union-attr]
                return mod
            except Exception:  # noqa: BLE001
                continue
    return None


def push_target_guarded(toks: list[str], cwd: str | None) -> bool:
    """True unless we can positively show the push target is a non-guarded remote."""
    i = toks.index("push")
    rest = [t for t in toks[i + 1 :] if not t.startswith("-")]
    remote = rest[0] if rest else "origin"
    guard = load_guard()
    if guard is None:
        return True
    url = remote
    if not ("://" in remote or ":" in remote or "/" in remote):
        try:
            res = subprocess.run(
                ["git", "remote", "get-url", "--push", remote],
                cwd=cwd or None,
                capture_output=True,
                text=True,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            return True
        if res.returncode != 0:
            return True
        url = res.stdout.strip()
    try:
        return bool(guard.is_guarded(url))
    except Exception:  # noqa: BLE001
        return True


def check(cmd: str, cwd: str | None) -> None:
    low = cmd.lower()
    if "--no-verify" in low:
        deny("--no-verify skips the git hooks")
    if "core.hooks" in low:
        deny("changing core.hooksPath / core.hooks* disables the global guard hooks")
    if re.search(r"\bhusky=0\b", low):
        deny("HUSKY=0 disables hooks")
    if "SKIP=" in cmd and re.search(r"\bcommit\b|pre-commit", low):
        deny("SKIP= skips pre-commit hooks")
    for seg in split_segments(cmd):
        toks = tokens(seg)
        names = [os.path.basename(t) for t in toks]
        if "git" in names:
            if GIT_ENV_EVASION.search(" " + seg):
                deny("overriding HOME / GIT_CONFIG_* / GIT_DIR for git evades the global hooks")
            gi = names.index("git")
            sub = toks[gi + 1 :]
            if "commit" in sub:
                after = sub[sub.index("commit") + 1 :]
                for t in after:
                    if t == "--":
                        break
                    if re.fullmatch(r"-[A-Za-z]*n[A-Za-z]*", t):
                        deny("git commit -n is --no-verify")
            if "push" in sub:
                forced = False
                for t in sub[sub.index("push") + 1 :]:
                    if t.startswith("--force-with-lease") or t.startswith("--force-if-includes"):
                        continue
                    if (
                        t == "--force"
                        or re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", t)
                        or t.startswith("+")
                    ):
                        forced = True
                if forced and push_target_guarded(toks, cwd):
                    deny("force push to a guarded (public/unknown) remote; use --force-with-lease")
        mentions = [p for p in PROTECTED if p in seg]
        if mentions:
            verbs = {os.path.basename(t) for t in toks}
            interp_code = bool(verbs & INTERPRETERS) and any(t in ("-c", "-e", "-") for t in toks)
            redirect = bool(re.search(r">", seg))
            if verbs & WRITE_VERBS or redirect or interp_code:
                deny(f"modifying {mentions[0]} (public-guard config, cache or git hooks)")


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    if data.get("tool_name") not in (None, "Bash"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command")
    if not isinstance(cmd, str):
        return 0
    check(cmd, data.get("cwd"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

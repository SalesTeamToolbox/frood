#!/usr/bin/env python3
"""Claude Code PreToolUse hook: deny tool calls that bypass public-guard.

Protocol: JSON on stdin ({"tool_name", "tool_input": {"command"}, "cwd"}); exit 2 with the
reason on stderr denies the call. Exit 0 allows. Unparseable input is allowed.

This is a TRIPWIRE for a careless agent, not a sandbox: a determined agent can still build a
bypass out of string tricks this file cannot see. The git hooks, GitHub push protection and the
CI scan are the real enforcement.
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import shlex
import subprocess
import sys

PROTECTED = (
    ".gitconfig",
    "/etc/gitconfig",
    ".config/git/",
    ".config/public-guard",
    ".cache/public-guard",
    "/etc/public-guard",
    ".git/hooks",
)
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
BLOCKED_MCP = {
    "mcp__github__push_files",
    "mcp__github__create_or_update_file",
    "mcp__github__create_branch",
    "mcp__github__fork_repository",
}
HOOK_SUBCOMMANDS = {"commit", "push", "merge", "rebase", "am"}


def deny(reason: str) -> None:
    sys.stderr.write(
        f"public-guard bypass blocked: {reason}\nDo not retry. Report this to the owner verbatim.\n"
    )
    sys.exit(2)


def flat(s: str) -> str:
    """Quotes, backslashes and runs of whitespace removed, so string tricks collapse."""
    s = re.sub(r"[\"'\\]", "", s)
    return re.sub(r"\s+", " ", s)


def split_segments(cmd: str) -> list[str]:
    cmd = cmd.replace("$(", ";").replace("`", ";")
    return [s.strip() for s in re.split(r"\n|;|&&|\|\||\||&(?!>)", cmd) if s.strip()]


def tokens(seg: str) -> list[str]:
    try:
        return shlex.split(seg, posix=True)
    except ValueError:
        return seg.replace('"', "").replace("'", "").split()


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


def push_target_guarded(sub: list[str], cwd: str | None) -> bool:
    """True unless we can positively show the push target is a non-guarded remote."""
    rest = [t for t in sub[sub.index("push") + 1 :] if not t.startswith("-")]
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


def git_sub(toks: list[str]):
    """Tokens after `git` (skipping global options), or None when this is not a git call."""
    names = [os.path.basename(t) for t in toks]
    if "git" not in names:
        return None
    return toks[names.index("git") + 1 :]


def first_subcommand(sub: list[str]) -> str | None:
    i = 0
    while i < len(sub):
        t = sub[i]
        if t in ("-c", "-C", "--git-dir", "--work-tree", "--namespace", "--exec-path"):
            i += 2
            continue
        if t.startswith("-"):
            i += 1
            continue
        return t
    return None


def check_gh_api(toks: list[str]) -> None:
    names = [os.path.basename(t) for t in toks]
    if "gh" not in names:
        return
    rest = toks[names.index("gh") + 1 :]
    if not rest or rest[0] != "api":
        return
    method = None
    for i, t in enumerate(rest):
        if t in ("-X", "--method") and i + 1 < len(rest):
            method = rest[i + 1]
        elif t.startswith("--method="):
            method = t.split("=", 1)[1]
        elif re.fullmatch(r"-X[A-Za-z]+", t):
            method = t[2:]
    if method and method.upper() in ("PUT", "POST", "PATCH"):
        if any("/contents/" in t or "/git/" in t for t in rest):
            deny("gh api write to /contents/ or /git/ skips the git hooks; use git push")


def check_segment(
    seg: str, toks: list[str], runs_git: bool, cwd_hint: str, cwd: str | None
) -> None:
    names = [os.path.basename(t) for t in toks]
    fseg = flat(seg)
    sub = git_sub(toks)
    check_gh_api(toks)
    if sub is not None:
        cmd = first_subcommand(sub)
        if cmd in ("send-pack", "receive-pack", "remote-https", "remote-http", "http-push"):
            deny(f"git {cmd} skips the pre-push hook; use git push")
        if cmd in HOOK_SUBCOMMANDS:
            for t in sub:
                if t == "--":
                    break
                if t.startswith("--no-v"):
                    deny("--no-verify (or an abbreviation) skips the git hooks")
            if cmd == "commit":
                for t in sub[sub.index("commit") + 1 :]:
                    if t == "--":
                        break
                    if re.fullmatch(r"-[A-Za-z]*n[A-Za-z]*", t):
                        deny("git commit -n is --no-verify")
        if cmd == "config":
            for t in sub:
                tl = t.lower()
                if t in ("--remove-section", "--edit", "-e", "--rename-section") or "hook" in tl:
                    deny("git config edits that can disable hooks or rewrite config sections")
        if cmd == "push":
            forced = False
            for t in sub[sub.index("push") + 1 :]:
                if t.startswith("--force-with-lease") or t.startswith("--force-if-includes"):
                    continue
                if t == "--force" or re.fullmatch(r"-[A-Za-z]*f[A-Za-z]*", t) or t.startswith("+"):
                    forced = True
            if forced and push_target_guarded(sub, cwd):
                deny("force push to a guarded (public/unknown) remote; use --force-with-lease")
    if runs_git:
        for t in toks:
            if re.match(r"^(HOME|PATH|XDG_CONFIG_HOME)=", t):
                deny("setting HOME/PATH in a command that runs git evades the global hooks")
        if names and names[0] == "export" and any(re.match(r"^(HOME|PATH)\b", t) for t in toks[1:]):
            deny("export HOME/PATH in a command that runs git evades the global hooks")
        if names and names[0] == "unset" and any(t in ("HOME", "PATH") for t in toks[1:]):
            deny("unset HOME/PATH in a command that runs git evades the global hooks")
        if "env" in names[:1] or (names and names[0] == "env"):
            for t in toks[1:]:
                if t in ("-i", "--ignore-environment", "-u", "--unset") or t.startswith(
                    ("-u", "--unset=")
                ):
                    deny("env -u / env -i before git strips the environment the hooks rely on")
                if not t.startswith("-") and "=" not in t:
                    break
    mentions = [p for p in PROTECTED if p in fseg]
    # a bare `cd <dir>` earlier in the command can hide the protected path
    if cwd_hint:
        joined = flat(
            cwd_hint + "/" + " ".join(t for t in toks[1:] if not t.startswith(("-", "/", "~")))
        )
        mentions += [p for p in PROTECTED if p in joined and p not in mentions]
        for t in toks[1:]:
            if t.startswith("-"):
                continue
            cand = flat(cwd_hint.rstrip("/") + "/" + t)
            mentions += [p for p in PROTECTED if p in cand and p not in mentions]
    if mentions:
        verbs = set(names)
        interp_code = bool(verbs & INTERPRETERS) and any(t in ("-c", "-e", "-") for t in toks)
        sed_inplace = "sed" in verbs and any(t.startswith("-i") or t == "--in-place" for t in toks)
        redirect = ">" in seg
        if verbs & WRITE_VERBS or redirect or interp_code or sed_inplace:
            deny(f"modifying {mentions[0]} (public-guard config, cache, git config or git hooks)")


def check(cmd: str, cwd: str | None) -> None:
    fall = flat(cmd)
    low = fall.lower()
    if "--no-verify" in low:
        deny("--no-verify skips the git hooks")
    if "core.hook" in low:
        deny("changing core.hooksPath / core.hooks* disables the global guard hooks")
    if re.search(r"\bhusky=0\b", low):
        deny("HUSKY=0 disables hooks")
    if "SKIP=" in fall and re.search(r"\bcommit\b|pre-commit", low):
        deny("SKIP= skips pre-commit hooks")
    if re.search(
        r"GIT_CONFIG_(COUNT|PARAMETERS|NOSYSTEM|GLOBAL|SYSTEM|KEY|VALUE)|GIT_EXEC_PATH", fall
    ):
        deny("GIT_CONFIG_* / GIT_EXEC_PATH can disable the hooks")
    segs = split_segments(cmd)
    all_toks = [tokens(s) for s in segs]
    runs_git = any("git" in [os.path.basename(t) for t in toks] for toks in all_toks) or bool(
        re.search(r"\bgit\b", fall)
    )
    cwd_hint = ""
    for seg, toks in zip(segs, all_toks):
        check_segment(seg, toks, runs_git, cwd_hint, cwd)
        names = [os.path.basename(t) for t in toks]
        if names[:1] == ["cd"] and len(toks) > 1:
            cwd_hint = toks[1]
        # shell -c / interpreter payloads are checked recursively
        if set(names) & {"bash", "sh", "zsh", "eval"}:
            for t in toks:
                if " " in t and t != seg:
                    check(t, cwd)


def main() -> int:
    try:
        data = json.load(sys.stdin)
    except ValueError:
        return 0
    tool = data.get("tool_name")
    if tool in BLOCKED_MCP:
        deny("public-guard: use git push so the scan runs")
    if tool not in (None, "Bash"):
        return 0
    cmd = (data.get("tool_input") or {}).get("command")
    if not isinstance(cmd, str):
        return 0
    check(cmd, data.get("cwd"))
    return 0


if __name__ == "__main__":
    sys.exit(main())

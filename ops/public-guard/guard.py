#!/usr/bin/env python3
"""public-guard: refuse to push secrets or private data to a PUBLIC git remote.

Stdlib only. Fails closed: any error, missing tool or unknown visibility blocks.

Subcommands:
  pre-push <remote-name> <remote-url>   (git pre-push hook; ref lines on stdin)
  pre-commit                            (git pre-commit hook; scans the staged diff)
  audit [--history] [<repo-path>]       (scan a whole repo before making it public)
  is-public <remote-url>                (print public|private|unknown)

There is deliberately NO environment variable, flag or file that skips a block.
The only way past a finding is a human typing the repo name at /dev/tty.
"""

from __future__ import annotations

import fnmatch
import json
import os
import re
import select
import shutil
import stat
import subprocess
import sys
import tempfile
import time

ZERO = "0" * 40
DEFAULT_TOML = "[extend]\nuseDefault = true\n"
HEX_RE = re.compile(r"^[0-9a-f]{40}([0-9a-f]{24})?$")
# Tool binaries must never come from a world-writable or repo-local location.
UNTRUSTED_PREFIXES = ("/tmp", "/var/tmp", "/dev/shm")
# private remotes may only be declared by root (an agent running as the user cannot write here).
SYSTEM_DIR = "/etc/public-guard"
PRIVATE_REMOTES_FILE = SYSTEM_DIR + "/private-remotes.txt"
# Trust anchor: files/binaries the guard relies on must be owned by this uid and neither they nor
# any parent directory up to TRUST_ROOT may be group- or world-writable.
TRUSTED_UID = 0
TRUST_ROOT = "/"
CACHE_TTL = 24 * 3600
POLICY_FILES = (".public-guard-allow", ".gitleaks.toml")
MAX_SHOWN = 50

FORBIDDEN_DESC = (
    ".env, .env.*, *.pem, *.key, *.p12, id_rsa*, id_ed25519*, .mcp.json, .mcp.*.json, "
    "opencode.json, *.sqlite, *.db, *.log, *_out.txt, *_err.txt, *_state.json, "
    "*cycle_state*.json, email_*.json, .claude/settings.local.json, credentials*, *.bundle, *.bak"
)

PLACEHOLDER_NAMES = {
    "user",
    "you",
    "example",
    "alice",
    "bob",
    "runner",
    "username",
    "yourname",
    "your-name",
    "youruser",
    "shared",
    "public",
    "default",
    "all users",
    "name",
    "node",
    "vscode",
    "app",
}


class GuardError(Exception):
    pass


# --------------------------------------------------------------------------- config


def home() -> str:
    return os.path.expanduser("~")


def untrusted_reason(path: str):
    """None when `path` (resolved) and all its parents up to TRUST_ROOT are trusted, else why not."""
    real = os.path.realpath(path)
    root = os.path.realpath(TRUST_ROOT)
    cur = real
    while True:
        try:
            st = os.stat(cur)
        except OSError as exc:
            return f"cannot stat {cur}: {exc}"
        if st.st_uid != TRUSTED_UID:
            return f"{cur} is not owned by the trusted owner (uid {st.st_uid})"
        if st.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            return f"{cur} is group- or world-writable"
        if cur == root or cur == os.path.dirname(cur):
            return None
        cur = os.path.dirname(cur)


def system_mode() -> bool:
    try:
        st = os.stat(SYSTEM_DIR)
    except OSError:
        return False
    return stat.S_ISDIR(st.st_mode) and st.st_uid == TRUSTED_UID


def conf_dir() -> str:
    if system_mode():
        return SYSTEM_DIR
    return os.path.join(home(), ".config", "public-guard")


def require_trusted_config(path: str) -> None:
    """In system mode, config files must be root-owned and not writable by group/other."""
    if system_mode():
        why = untrusted_reason(path)
        if why:
            raise GuardError(f"untrusted config {path}: {why}; fix with install.sh --system")


def cache_file() -> str:
    return os.path.join(home(), ".cache", "public-guard", "visibility.json")


def tools_file() -> str:
    return os.path.join(conf_dir(), "tools.json")


def tool_path(name: str, required: bool = True):
    """Absolute path of a helper binary recorded by install.sh. Never searches PATH.

    The binary (after realpath) and every parent directory must be owned by root and not group- or
    world-writable. A failing gitleaks blocks; a failing gh (required=False) means "unknown".
    """
    if not required:
        try:
            return tool_path(name, required=True)
        except GuardError:
            return None
    require_trusted_config(tools_file())
    try:
        with open(tools_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        recorded = data.get(name) if isinstance(data, dict) else None
    except (OSError, ValueError):
        recorded = None
    if not recorded:
        if required:
            raise GuardError(
                f"{name} is not recorded in {tools_file()} - install {name} and run install.sh"
            )
        return None
    if not os.path.isabs(recorded):
        raise GuardError(f"recorded path for {name} is not absolute ({recorded}); run install.sh")
    real = os.path.realpath(recorded)
    if not (os.path.isfile(real) and os.access(real, os.X_OK)):
        raise GuardError(
            f"recorded {name} ({recorded}) is missing or not executable; run install.sh"
        )
    why = untrusted_reason(real)
    if why:
        raise GuardError(f"refusing {name} at {real}: {why}")
    banned = list(UNTRUSTED_PREFIXES)
    top = git(["rev-parse", "--show-toplevel"], check=False).stdout.strip()
    if top:
        banned.append(os.path.realpath(top))
    for pre in banned:
        pre_real = os.path.realpath(pre)
        if real == pre_real or real.startswith(pre_real.rstrip("/") + "/"):
            raise GuardError(f"refusing {name} at {real}: it lives under {pre}")
    return real


def read_lines(path: str) -> list[str]:
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            return [ln.strip() for ln in fh.read().splitlines()]
    except OSError:
        return []


# --------------------------------------------------------------------------- remotes


def norm_url(url: str) -> str:
    u = url.strip().rstrip("/")
    if u.endswith(".git"):
        u = u[:-4]
    return u.lower()


_GH_RE = re.compile(
    r"^(?:git@|ssh://(?:git@)?|https?://(?:[^@/\s]+@)?|git://)github\.com[:/]+"
    r"([^/\s]+)/([^/\s]+?)(?:\.git)?/?$",
    re.I,
)


def parse_github(url: str):
    m = _GH_RE.match(url.strip())
    return (m.group(1), m.group(2)) if m else None


def is_local(url: str) -> bool:
    u = url.strip()
    if u.startswith(("/", "./", "../", "~", "file://")):
        return True
    if re.match(r"^[A-Za-z]:[\\/]", u):
        return True
    return "://" not in u and ":" not in u


def load_cache() -> dict:
    try:
        with open(cache_file(), encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def save_cache(cache: dict) -> None:
    try:
        path = cache_file()
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f".{os.getpid()}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(cache, fh)
        os.replace(tmp, path)
    except OSError:
        pass


def gh_visibility(owner: str, repo: str):
    """Return 'public', 'private' or None when it cannot be determined.

    Only 'public' is ever cached (a cached 'public' can only cause extra scanning).
    A 'private' verdict always comes from a live gh call.
    """
    key = f"{owner}/{repo}".lower()
    cache = load_cache()
    ent = cache.get(key)
    if isinstance(ent, dict) and ent.get("v") == "public":
        try:
            if (time.time() - float(ent.get("t", 0))) < CACHE_TTL:
                return "public"
        except (TypeError, ValueError):
            pass
    gh = tool_path("gh", required=False)
    if not gh:
        return None
    try:
        res = subprocess.run(
            [gh, "api", f"repos/{owner}/{repo}", "--jq", ".visibility"],
            capture_output=True,
            text=True,
            timeout=20,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if res.returncode != 0:
        return None
    vis = res.stdout.strip().lower()
    if vis == "public":
        cache[key] = {"v": "public", "t": time.time()}
        save_cache(cache)
        return "public"
    if vis in ("private", "internal"):
        cache.pop(key, None)
        save_cache(cache)
        return "private"
    return None


def private_remote_list() -> set[str]:
    path = PRIVATE_REMOTES_FILE
    if not os.path.exists(path):
        return set()
    if untrusted_reason(path):
        return set()
    return {norm_url(x) for x in read_lines(path) if x and not x.startswith("#")}


def classify(url: str):
    """Return (status, why). status: 'public' | 'private' | 'local' | 'unknown'.

    'unknown' is guarded exactly like 'public'. Only PUBLIC_GUARD_FORCE_PUBLIC
    exists as an env override and it can only make things MORE guarded.
    """
    gh = parse_github(url)
    if gh is None and norm_url(url) in private_remote_list():
        return "private", "listed in /etc/public-guard/private-remotes.txt"
    if os.environ.get("PUBLIC_GUARD_FORCE_PUBLIC") == "1":
        return "public", "PUBLIC_GUARD_FORCE_PUBLIC=1"
    if is_local(url):
        return "local", "local path remote"
    if gh is None:
        return (
            "public",
            "non-GitHub remote (public unless listed in /etc/public-guard/private-remotes.txt)",
        )
    vis = gh_visibility(gh[0], gh[1])
    if vis is None:
        return "unknown", "visibility unknown (treated as public)"
    return vis, "github visibility"


def is_guarded(url: str) -> bool:
    return classify(url)[0] in ("public", "unknown")


def repo_label(url: str) -> str:
    gh = parse_github(url)
    if gh:
        return f"{gh[0]}/{gh[1]}"
    return norm_url(url).rsplit("/", 1)[-1] or url


# --------------------------------------------------------------------------- git helpers


def git(args: list[str], cwd=None, check=True, text=True, input_=None):
    res = subprocess.run(
        ["git", "-c", "core.quotepath=off", *args],
        cwd=cwd,
        capture_output=True,
        text=text,
        input=input_,
    )
    if check and res.returncode != 0:
        err = res.stderr if text else res.stderr.decode("utf-8", "replace")
        raise GuardError(f"git {' '.join(args[:3])} failed: {err.strip()[:300]}")
    return res


def toplevel() -> str:
    res = git(["rev-parse", "--show-toplevel"], check=False)
    if res.returncode == 0 and res.stdout.strip():
        return res.stdout.strip()
    return os.getcwd()


def git_stream(args: list[str], cwd=None):
    """Yield raw byte lines of `git <args>` output; raise GuardError on failure."""
    with tempfile.TemporaryFile() as err:
        proc = subprocess.Popen(
            ["git", "-c", "core.quotepath=off", *args],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=err,
        )
        assert proc.stdout is not None
        yield from proc.stdout
        rc = proc.wait()
        if rc != 0:
            err.seek(0)
            raise GuardError(
                f"git {' '.join(args[:3])} failed: {err.read().decode('utf-8', 'replace').strip()[:300]}"
            )


def git_blob(rev_path: str, cwd=None):
    res = git(["show", rev_path], cwd=cwd, check=False)
    return res.stdout if res.returncode == 0 else None


# --------------------------------------------------------------------------- denylist + rules


def load_denylist():
    path = os.path.join(conf_dir(), "denylist.txt")
    try:
        with open(path, encoding="utf-8", errors="replace") as fh:
            lines = [ln.strip() for ln in fh.read().splitlines()]
    except OSError as exc:
        raise GuardError(f"denylist {path} is missing or unreadable - run install.sh") from exc
    require_trusted_config(path)
    entries = []
    for ln in lines:
        if not ln or ln.startswith("#"):
            continue
        try:
            if ln.startswith("re:"):
                entries.append(re.compile(ln[3:]))
            else:
                entries.append(re.compile(re.escape(ln), re.I))
        except re.error as exc:
            raise GuardError(f"invalid regex in denylist ({exc}); fix {path}") from exc
    return entries


def redact(s: str) -> str:
    return s[:3] + "…"


_NAME = r"([^\\/\s\"'<>$%{}()\[\]`:;,|*?]+)"
PRIVATE_PATH_RES = [
    re.compile(r"/home/" + _NAME + r"/"),
    re.compile(r"/Users/" + _NAME + r"/"),
    re.compile(r"[A-Za-z]:[\\/]+Users[\\/]+" + _NAME + r"[\\/]", re.I),
    re.compile(r"(?<![A-Za-z0-9])-home-([A-Za-z0-9_]+)-"),
]


def private_path_hits(text: str):
    for rx in PRIVATE_PATH_RES:
        for m in rx.finditer(text):
            if m.group(1).lower() in PLACEHOLDER_NAMES:
                continue
            yield m.group(0)


def forbidden_match(path: str):
    p = path.replace("\\", "/")
    pl = p.lower()
    bl = pl.rsplit("/", 1)[-1]
    if bl == ".env":
        return ".env"
    if bl.startswith(".env."):
        if bl.endswith((".example", ".sample", ".template")):
            return None
        return ".env.*"
    if bl == ".mcp.json":
        return ".mcp.json"
    if fnmatch.fnmatchcase(bl, ".mcp.*.json"):
        return None if fnmatch.fnmatchcase(bl, "*.example*") else ".mcp.*.json"
    if pl == ".claude/settings.local.json" or pl.endswith("/.claude/settings.local.json"):
        return ".claude/settings.local.json"
    if bl == "opencode.json":
        return "opencode.json"
    for pat in (
        "*.pem",
        "*.key",
        "*.p12",
        "id_rsa*",
        "id_ed25519*",
        "*.sqlite",
        "*.db",
        "*.log",
        "*_out.txt",
        "*_err.txt",
        "*_state.json",
        "*cycle_state*.json",
        "email_*.json",
        "credentials*",
        "*.bundle",
        "*.bak",
    ):
        if fnmatch.fnmatchcase(bl, pat):
            return pat
    return None


class Findings:
    def __init__(self):
        self.items: list[dict] = []
        self._seen: set = set()

    def add(self, file, line, rule, match, allowable=True):
        key = (file, line, rule, match)
        if key in self._seen:
            return
        self._seen.add(key)
        self.items.append(
            {"file": file, "line": line, "rule": rule, "match": match, "allowable": allowable}
        )


class Scanner:
    def __init__(self, deny):
        self.deny = deny
        self.changed: list[str] = []

    def text(self, f: Findings, file: str, line: int, text: str):
        for rx in self.deny:
            for m in rx.finditer(text):
                f.add(file, line, "denylist", redact(m.group(0)), allowable=False)
        for hit in private_path_hits(text):
            f.add(file, line, "private-path", redact(hit))

    def path(self, f: Findings, path: str):
        self.changed.append(path)
        pat = forbidden_match(path)
        if pat:
            f.add(path, 0, "forbidden-path", f"[{pat}]")
        for rx in self.deny:
            m = rx.search(path)
            if m:
                f.add(path, 0, "denylist", redact(m.group(0)), allowable=False)
        for hit in private_path_hits(path):
            f.add(path, 0, "private-path", redact(hit))

    def message(self, f: Findings, sha: str, msg: str):
        label = f"commit-message:{sha[:7]}"
        for i, ln in enumerate(msg.splitlines(), 1):
            self.text(f, label, i, ln)


_HUNK_RE = re.compile(r"^@@ -\d+(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def parse_diff(lines, in_msg_mode: bool):
    """Yield ('msg', sha, text) | ('file', path) | ('line', path, no, text)."""
    state = "diff" if not in_msg_mode else "top"
    sha = ""
    buf: list[str] = []
    path = ""
    old_rem = new_rem = 0
    newno = 0
    pending = None  # path of a diff header not yet emitted (deleted files are dropped)
    for raw in lines:
        line = raw.decode("utf-8", "replace").rstrip("\n")
        if pending is not None:
            if not line.startswith("deleted file mode"):
                yield ("file", pending)
            pending = None
        if state == "msg":
            if "\x03" in line:
                buf.append(line.split("\x03", 1)[0])
                yield ("msg", sha, "\n".join(buf))
                state = "diff"
                old_rem = new_rem = 0
            else:
                buf.append(line)
            continue
        if old_rem > 0 or new_rem > 0:
            if line.startswith("+"):
                new_rem -= 1
                yield ("line", path, newno, line[1:])
                newno += 1
                continue
            if line.startswith("-"):
                old_rem -= 1
                continue
            if line.startswith("\\"):
                continue
            old_rem = new_rem = 0
        if line.startswith("\x01"):
            sha, _, first = line[1:].partition("\x02")
            buf = []
            if "\x03" in first:
                yield ("msg", sha, first.split("\x03", 1)[0])
                state = "diff"
            else:
                buf.append(first)
                state = "msg"
            continue
        if line.startswith("diff --git "):
            rest = line[len("diff --git ") :]
            n = (len(rest) - 5) // 2
            if n > 0 and rest.startswith("a/") and rest[2 : 2 + n] == rest[len(rest) - n :]:
                path = rest[2 : 2 + n]
            else:  # fallback: take the b/ side
                path = rest.rsplit(" b/", 1)[-1]
            pending = path
            continue
        m = _HUNK_RE.match(line)
        if m:
            old_rem = int(m.group(1)) if m.group(1) is not None else 1
            new_rem = int(m.group(3)) if m.group(3) is not None else 1
            newno = int(m.group(2))
    if pending is not None:
        yield ("file", pending)


def scan_events(events, scanner: Scanner, f: Findings):
    for ev in events:
        if ev[0] == "msg":
            scanner.message(f, ev[1], ev[2])
        elif ev[0] == "file":
            scanner.path(f, ev[1])
        else:
            scanner.text(f, ev[1], ev[2], ev[3])


# --------------------------------------------------------------------------- gitleaks


def run_gitleaks(
    kind_args: list[str], target: str | None, config_text, cwd=None, stdin_text=None
) -> list[dict]:
    exe = tool_path("gitleaks")
    tmp = tempfile.mkdtemp(prefix="pg-")
    try:
        os.chmod(tmp, 0o700)
        report = os.path.join(tmp, "report.json")
        ign = os.path.join(tmp, "noignore")
        os.mkdir(ign)
        cmd = [
            exe,
            kind_args[0],
            "--no-banner",
            "--log-level",
            "error",
            "--exit-code",
            "0",
            "--ignore-gitleaks-allow",
            "-i",
            ign,
            "-f",
            "json",
            "-r",
            report,
        ]
        # Always pass an explicit config: otherwise gitleaks would silently pick up the
        # working tree's own .gitleaks.toml.
        cfg = os.path.join(tmp, "gitleaks.toml")
        with open(cfg, "w", encoding="utf-8") as fh:
            fh.write(config_text or DEFAULT_TOML)
        cmd += ["-c", cfg]
        cmd += kind_args[1:] + ([target] if target else [])
        res = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, input=stdin_text)
        if res.returncode != 0 or not os.path.exists(report):
            raise GuardError(f"gitleaks failed (rc={res.returncode}): {res.stderr.strip()[:300]}")
        try:
            with open(report, encoding="utf-8") as fh:
                data = json.load(fh)
        except ValueError as exc:
            raise GuardError(f"gitleaks report unreadable: {exc}") from exc
        return data if isinstance(data, list) else []
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def add_gitleaks(f: Findings, hits: list[dict], prefix_dir: str = "", label: str | None = None):
    for h in hits:
        file = label or h.get("File", "?")
        if prefix_dir and file.startswith(prefix_dir):
            file = file[len(prefix_dir) :].lstrip("/")
        secret = h.get("Secret") or h.get("Match") or "?"
        f.add(
            file,
            h.get("StartLine", 0),
            "gitleaks:" + str(h.get("RuleID", "?")),
            redact(str(secret)),
        )


# --------------------------------------------------------------------------- allow file


class Allow:
    def __init__(self, text: str | None):
        self.rules: set[str] = set()
        self.globs: list[tuple[str, str | None]] = []  # (glob, rule or None)
        for ln in (text or "").splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"):
                continue
            rule = None
            glob = None
            for tok in ln.split():
                if tok.startswith("rule:"):
                    rule = tok[5:]
                else:
                    glob = tok
            if glob is None and rule:
                self.rules.add(rule)
            elif glob:
                self.globs.append((glob, rule))

    def permits(self, item: dict) -> bool:
        if not item["allowable"]:
            return False
        rule = item["rule"]
        short = rule.split(":", 1)[-1]
        if rule in self.rules or short in self.rules:
            return True
        path = item["file"]
        base = path.rsplit("/", 1)[-1]
        for glob, r in self.globs:
            if r and r != rule and r != short:
                continue
            if fnmatch.fnmatchcase(path, glob) or (
                "/" not in glob and fnmatch.fnmatchcase(base, glob)
            ):
                return True
            if glob.endswith("/") and path.startswith(glob):
                return True
        return False


# --------------------------------------------------------------------------- reporting


def format_block(headline: str, items: list[dict], footer: bool = True) -> str:
    out = [f"{headline} — {len(items)} finding(s)"]
    for it in items[:MAX_SHOWN]:
        loc = f"{it['file']}:{it['line']}" if it["line"] else it["file"]
        out.append(f"  {loc}  {it['rule']}  {it['match']}")
    if len(items) > MAX_SHOWN:
        out.append(f"  ... and {len(items) - MAX_SHOWN} more")
    if not footer:
        return "\n".join(out)
    out.append(
        "AGENTS: stop here. Do not retry, do not use --no-verify, do not edit hooks, allowlists or the denylist."
    )
    out.append("Report this message to the owner verbatim.")
    out.append(
        "Owner: remove the data (and rewrite history if it was already committed), or run the push yourself in a"
    )
    out.append("terminal to review and approve an exception.")
    return "\n".join(out)


def human_approves(label: str) -> bool:
    """Only a human at a controlling terminal can approve. No TTY means no."""
    try:
        fd = os.open("/dev/tty", os.O_RDWR)
    except OSError:
        return False
    try:
        short = label.rsplit("/", 1)[-1]
        os.write(
            fd,
            f"\nTo approve this exception type the repo name ({label}) and press Enter, anything else aborts: ".encode(),
        )
        buf = b""
        deadline = time.time() + 300
        while b"\n" not in buf:
            left = deadline - time.time()
            if left <= 0:
                return False
            ready, _, _ = select.select([fd], [], [], left)
            if not ready:
                return False
            chunk = os.read(fd, 1024)
            if not chunk:
                return False
            buf += chunk
        answer = buf.split(b"\n", 1)[0].decode("utf-8", "replace").strip()
        return answer != "" and answer in (label, short)
    except OSError:
        return False
    finally:
        try:
            os.close(fd)
        except OSError:
            pass


def finish(headline: str, label: str, f: Findings, allow: Allow) -> int:
    remaining = [it for it in f.items if not allow.permits(it)]
    if not remaining:
        return 0
    sys.stderr.write(format_block(headline, remaining) + "\n")
    sys.stderr.flush()
    if human_approves(label):
        sys.stderr.write("PUBLIC-GUARD: exception approved by a human at the terminal.\n")
        return 0
    return 1


# --------------------------------------------------------------------------- commands


def blocked_headline(verb: str, label: str) -> str:
    return f"PUBLIC-GUARD: {verb} PUBLIC repo {label} BLOCKED"


def scan_tree_paths(f: Findings, sha: str, cwd):
    res = git(["ls-tree", "-r", "--name-only", "-z", sha], cwd=cwd)
    for p in res.stdout.split("\0"):
        if not p:
            continue
        pat = forbidden_match(p)
        if pat:
            f.add(p, 0, "forbidden-path", f"[{pat}]")


def config_base(name: str, lsha: str, rsha: str, cwd):
    """The REMOTE-side commit whose .gitleaks.toml/.public-guard-allow govern this push.

    Never the pushed tip: a push must not be able to weaken the rules that judge it.
    """
    if (
        rsha != ZERO
        and git(["cat-file", "-e", rsha + "^{commit}"], cwd=cwd, check=False).returncode == 0
    ):
        return rsha
    cands = []
    head = git(["symbolic-ref", "-q", f"refs/remotes/{name}/HEAD"], cwd=cwd, check=False)
    if head.returncode == 0 and head.stdout.strip():
        cands.append(head.stdout.strip())
    cands += [f"refs/remotes/{name}/main", f"refs/remotes/{name}/master"]
    for c in cands:
        if git(["rev-parse", "--verify", "-q", c], cwd=cwd, check=False).returncode != 0:
            continue
        mb = git(["merge-base", lsha, c], cwd=cwd, check=False)
        if mb.returncode == 0 and mb.stdout.strip():
            return mb.stdout.strip()
    return None


def scan_tag_objects(f: Findings, scanner: Scanner, sha: str, cwd, cfg) -> None:
    """Scan the message of an annotated tag (and of tags it points at); target must be a commit."""
    seen = 0
    cur = sha
    while True:
        typ = git(["cat-file", "-t", cur], cwd=cwd).stdout.strip()
        if typ == "commit":
            return
        if typ != "tag":
            raise GuardError(f"pushed ref points at a {typ} object, not a commit or tag")
        seen += 1
        if seen > 10:
            raise GuardError("tag chain too deep")
        body = git(["cat-file", "tag", cur], cwd=cwd).stdout
        head, _, msg = body.partition("\n\n")
        label = f"tag-message:{cur[:7]}"
        for i, ln in enumerate(msg.splitlines(), 1):
            scanner.text(f, label, i, ln)
        if msg.strip():
            add_gitleaks(
                f, run_gitleaks(["stdin"], None, cfg, cwd=cwd, stdin_text=msg), label=label
            )
        nxt = ""
        for ln in head.splitlines():
            if ln.startswith("object "):
                nxt = ln.split()[1]
        if not nxt:
            raise GuardError("malformed tag object")
        cur = nxt


def cmd_pre_push(args: list[str]) -> int:
    if len(args) < 2:
        raise GuardError("usage: guard.py pre-push <remote-name> <remote-url>")
    name, url = args[0], args[1]
    status, _ = classify(url)
    if status not in ("public", "unknown"):
        return 0
    label = repo_label(url)
    deny = load_denylist()
    cwd = toplevel()
    f = Findings()
    scanner = Scanner(deny)
    allow_text = None
    policy_changed: list[str] = []
    refs = []
    for ln in sys.stdin.read().splitlines():
        if not ln.strip():
            continue
        parts = ln.split()
        if len(parts) != 4 or not HEX_RE.match(parts[1]) or not HEX_RE.match(parts[3]):
            raise GuardError(
                "unparseable pre-push input line; refusing to guess what is being pushed"
            )
        refs.append(parts)
    for lref, lsha, rref, rsha in refs:
        if lsha == ZERO:
            continue
        typ = git(["cat-file", "-t", lsha], cwd=cwd).stdout.strip()
        if typ not in ("commit", "tag"):
            raise GuardError(f"{lref} points at a {typ} object, not a commit or tag")
        have_remote = (
            rsha != ZERO
            and git(["cat-file", "-e", rsha + "^{commit}"], cwd=cwd, check=False).returncode == 0
        )
        rev = [f"{rsha}..{lsha}"] if have_remote else [lsha, "--not", f"--remotes={name}"]
        base = config_base(name, lsha, rsha, cwd)
        cfg = git_blob(f"{base}:.gitleaks.toml", cwd=cwd) if base else None
        before = len(scanner.changed)
        events = parse_diff(
            git_stream(
                [
                    "log",
                    "-p",
                    "-m",
                    "-U0",
                    "--no-color",
                    "--no-ext-diff",
                    "--no-textconv",
                    "--no-renames",
                    "--format=%x01%H%x02%B%x03",
                    *rev,
                ],
                cwd=cwd,
            ),
            in_msg_mode=True,
        )
        scan_events(events, scanner, f)
        for p in scanner.changed[before:]:
            if p.rsplit("/", 1)[-1] in POLICY_FILES and p not in policy_changed:
                policy_changed.append(p)
        scan_tree_paths(f, lsha, cwd)
        if typ == "tag":
            scan_tag_objects(f, scanner, lsha, cwd, cfg)
        add_gitleaks(f, run_gitleaks(["git", f"--log-opts=-m {' '.join(rev)}"], cwd, cfg, cwd=cwd))
        at = git_blob(f"{base}:.public-guard-allow", cwd=cwd) if base else None
        if at:
            allow_text = (allow_text or "") + "\n" + at
    for p in policy_changed:
        f.add(p, 0, "policy-file-changed", "[needs human review]", allowable=False)
    return finish(blocked_headline("push to", label), label, f, Allow(allow_text))


def cmd_pre_commit(args: list[str]) -> int:
    urls = []
    res = git(["remote", "-v"], check=False)
    for ln in res.stdout.splitlines():
        parts = ln.split()
        if len(parts) >= 2 and parts[1] not in urls:
            urls.append(parts[1])
    guarded = [u for u in urls if is_guarded(u)]
    if not guarded:
        return 0
    label = repo_label(guarded[0])
    deny = load_denylist()
    cwd = toplevel()
    f = Findings()
    scanner = Scanner(deny)
    events = parse_diff(
        git_stream(
            [
                "diff",
                "--cached",
                "-U0",
                "--no-color",
                "--no-ext-diff",
                "--no-textconv",
                "--no-renames",
            ],
            cwd=cwd,
        ),
        in_msg_mode=False,
    )
    scan_events(events, scanner, f)
    if scanner.changed:
        cfg = git_blob(":.gitleaks.toml", cwd=cwd) or git_blob("HEAD:.gitleaks.toml", cwd=cwd)
        add_gitleaks(f, run_gitleaks(["git", "--staged"], cwd, cfg, cwd=cwd))
    allow_text = git_blob(":.public-guard-allow", cwd=cwd) or git_blob(
        "HEAD:.public-guard-allow", cwd=cwd
    )
    return finish(
        f"PUBLIC-GUARD: commit in PUBLIC repo {label} BLOCKED", label, f, Allow(allow_text)
    )


def is_binary(chunk: bytes) -> bool:
    return b"\0" in chunk


def cmd_audit(args: list[str]) -> int:
    history = False
    path = None
    for a in args:
        if a == "--history":
            history = True
        elif a.startswith("-"):
            raise GuardError(f"unknown audit option {a}")
        else:
            path = a
    repo = os.path.abspath(path or os.getcwd())
    if git(["rev-parse", "--git-dir"], cwd=repo, check=False).returncode != 0:
        raise GuardError(f"{repo} is not a git repository")
    deny = load_denylist()
    f = Findings()
    scanner = Scanner(deny)
    tmp = tempfile.mkdtemp(prefix="pg-audit-")
    try:
        tree = os.path.join(tmp, "tree")
        os.mkdir(tree)
        with tempfile.TemporaryFile() as err:
            arch = subprocess.Popen(
                ["git", "archive", "--format=tar", "HEAD"],
                cwd=repo,
                stdout=subprocess.PIPE,
                stderr=err,
            )
            tar = subprocess.run(["tar", "-x", "-C", tree], stdin=arch.stdout, capture_output=True)
            arch.stdout.close()  # type: ignore[union-attr]
            if arch.wait() != 0 or tar.returncode != 0:
                raise GuardError("git archive HEAD failed (empty repo?)")
        allow_text = None
        cfg = None
        for root, dirs, files in os.walk(tree):
            dirs[:] = [d for d in dirs if d != ".git"]
            for fn in files:
                full = os.path.join(root, fn)
                rel = os.path.relpath(full, tree).replace(os.sep, "/")
                pat = forbidden_match(rel)
                if pat:
                    f.add(rel, 0, "forbidden-path", f"[{pat}]")
                for rx in deny:
                    m = rx.search(rel)
                    if m:
                        f.add(rel, 0, "denylist", redact(m.group(0)), allowable=False)
                for hit in private_path_hits(rel):
                    f.add(rel, 0, "private-path", redact(hit))
                if os.path.islink(full):
                    continue
                try:
                    with open(full, "rb") as fh:
                        head = fh.read(8192)
                        if is_binary(head):
                            continue
                        fh.seek(0)
                        for i, raw in enumerate(fh, 1):
                            scanner.text(f, rel, i, raw.decode("utf-8", "replace").rstrip("\n"))
                except OSError:
                    continue
        cfgp = os.path.join(tree, ".gitleaks.toml")
        if os.path.exists(cfgp):
            with open(cfgp, encoding="utf-8", errors="replace") as fh:
                cfg = fh.read()
        ap = os.path.join(tree, ".public-guard-allow")
        if os.path.exists(ap):
            with open(ap, encoding="utf-8", errors="replace") as fh:
                allow_text = fh.read()
        add_gitleaks(f, run_gitleaks(["dir"], ".", cfg, cwd=tree))
        if history:
            events = parse_diff(
                git_stream(
                    [
                        "log",
                        "--all",
                        "-p",
                        "-U0",
                        "--no-color",
                        "--no-ext-diff",
                        "--no-textconv",
                        "--no-renames",
                        "-m",
                        "--format=%x01%H%x02%B%x03",
                    ],
                    cwd=repo,
                ),
                in_msg_mode=True,
            )
            scan_events(events, scanner, f)
            add_gitleaks(f, run_gitleaks(["git", "--log-opts=-m --all"], repo, cfg, cwd=repo))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    remaining = [it for it in f.items if not Allow(allow_text).permits(it)]
    if remaining:
        sys.stderr.write(
            format_block(f"PUBLIC-GUARD: audit of {repo} FAILED", remaining, footer=False) + "\n"
        )
        return 1
    scope = "tree + full history" if history else "tree"
    print(f"PUBLIC-GUARD: audit of {repo} clean ({scope}).")
    return 0


def cmd_is_public(args: list[str]) -> int:
    if not args:
        raise GuardError("usage: guard.py is-public <remote-url>")
    status, why = classify(args[0])
    out = {"public": "public", "private": "private", "local": "private", "unknown": "unknown"}[
        status
    ]
    print(out)
    sys.stderr.write(f"({why})\n")
    return 0


def main(argv: list[str]) -> int:
    if not argv or argv[0] in ("-h", "--help"):
        sys.stdout.write(__doc__ or "")
        return 0
    cmd, rest = argv[0], argv[1:]
    if cmd in ("pre-push", "pre-commit", "audit") and not system_mode():
        sys.stderr.write("public-guard running in USER mode — install --system\n")
    try:
        if cmd == "pre-push":
            return cmd_pre_push(rest)
        if cmd == "pre-commit":
            return cmd_pre_commit(rest)
        if cmd == "audit":
            return cmd_audit(rest)
        if cmd == "is-public":
            return cmd_is_public(rest)
        sys.stderr.write(f"unknown command {cmd}\n")
        return 2
    except GuardError as exc:
        sys.stderr.write(
            f"PUBLIC-GUARD: ERROR — {exc}\nBLOCKED (fail closed). AGENTS: stop and report this message to the owner verbatim.\n"
        )
        return 1
    except Exception as exc:  # noqa: BLE001 - fail closed on anything
        sys.stderr.write(
            f"PUBLIC-GUARD: internal error {type(exc).__name__}: {exc}\nBLOCKED (fail closed). AGENTS: stop and report this message to the owner verbatim.\n"
        )
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

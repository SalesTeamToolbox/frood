"""Tests for ops/public-guard (guard.py, hooks, install.sh, block-bypass.py).

Everything runs against a temp HOME with a temp git repo and a bare repo as the "public"
remote (PUBLIC_GUARD_FORCE_PUBLIC=1). A stub `gh` in PATH records any call, and the
tests that must never reach GitHub assert it was not called.

Fixture secrets are assembled at runtime so this file itself stays clean for gitleaks and
for guard.py's private-path scan.
"""

from __future__ import annotations

import importlib.util
import json
import os
import pty
import select
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
GUARD_DIR = ROOT / "ops" / "public-guard"
GUARD = GUARD_DIR / "guard.py"
INSTALL = GUARD_DIR / "install.sh"
BYPASS = GUARD_DIR / "agent-hooks" / "block-bypass.py"
PYTHON = sys.executable

pytestmark = pytest.mark.skipif(shutil.which("gitleaks") is None, reason="gitleaks not installed")

DENY_EMAIL = "boss@" + "secretcorp.test"
OR_KEY = "sk-or-v1-" + "".join("0123456789abcdef"[(i * 7 + 3) % 16] for i in range(64))
HOME_PATH = "/ho" + "me/" + "zed42" + "/projects/x"


class Env:
    def __init__(self, tmp: Path):
        self.home = tmp / "home"
        self.home.mkdir()
        self.work = tmp / "work"
        self.work.mkdir()
        self.stub = tmp / "stub"
        self.stub.mkdir()
        gh = self.stub / "gh"
        gh.write_text(f'#!/bin/sh\ntouch "{self.home}/gh-called"\nexit 1\n')
        gh.chmod(0o755)
        self.base = {
            k: v
            for k, v in os.environ.items()
            if not k.startswith("GIT_")
            and not k.startswith("PUBLIC_GUARD_")
            and k not in ("SKIP", "HUSKY")
        }
        self.base.update(
            HOME=str(self.home),
            GIT_CONFIG_GLOBAL=str(self.home / ".gitconfig"),
            GIT_CONFIG_NOSYSTEM="1",
            GIT_AUTHOR_NAME="T",
            GIT_AUTHOR_EMAIL="t@example.com",
            GIT_COMMITTER_NAME="T",
            GIT_COMMITTER_EMAIL="t@example.com",
            PATH=f"{self.stub}:{os.environ['PATH']}",
            PUBLIC_GUARD_FORCE_PUBLIC="1",
        )
        self.guard_dir = self.home / ".config" / "public-guard"

    def run(self, cmd, cwd=None, env_extra=None, drop=(), input_=None, check=False):
        env = dict(self.base)
        for k in drop:
            env.pop(k, None)
        env.update(env_extra or {})
        res = subprocess.run(
            cmd,
            cwd=cwd or self.work,
            env=env,
            capture_output=True,
            text=True,
            input=input_,
            start_new_session=True,  # no controlling tty: agent-shell conditions
        )
        if check:
            assert res.returncode == 0, f"{cmd} failed: {res.stdout}\n{res.stderr}"
        return res

    def git(self, *args, cwd=None, **kw):
        return self.run(["git", *args], cwd=cwd, **kw)

    def install(self):
        res = self.run(["bash", str(INSTALL)])
        assert res.returncode == 0, res.stderr
        return res

    def write_denylist(self, *lines):
        (self.guard_dir / "denylist.txt").write_text("\n".join(lines) + "\n")

    def make_repo(self, name="proj"):
        remote = self.work / f"{name}-remote.git"
        repo = self.work / name
        self.git("init", "--bare", "-b", "main", str(remote), check=True)
        self.git("init", "-b", "main", str(repo), check=True)
        self.git("remote", "add", "origin", str(remote), cwd=repo, check=True)
        (repo / "README.md").write_text("hello\n")
        self.git("add", "-A", cwd=repo, check=True)
        self.git("commit", "-m", "init", cwd=repo, check=True)
        return repo, remote

    def commit_raw(self, repo, files: dict, msg="plant"):
        for name, content in files.items():
            p = repo / name
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
        self.git("add", "-A", cwd=repo, check=True)
        self.git("commit", "--no-verify", "-m", msg, cwd=repo, check=True)


@pytest.fixture
def env(tmp_path):
    e = Env(tmp_path)
    e.install()
    e.write_denylist("# test", DENY_EMAIL)
    return e


# ------------------------------------------------------------------------------ push


def test_clean_push_succeeds(env):
    repo, remote = env.make_repo()
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode == 0, res.stderr
    assert env.git("rev-parse", "main", cwd=remote).returncode == 0


PLANTS = [
    (
        "denylist-email",
        {"notes.txt": f"contact {DENY_EMAIL} now\n"},
        "plant",
        "denylist",
        DENY_EMAIL,
    ),
    ("home-path", {"cfg.txt": f"path={HOME_PATH}\n"}, "plant", "private-path", HOME_PATH),
    ("env-file", {".env": "A=1\n"}, "plant", "forbidden-path", None),
    ("or-key", {"settings.txt": f"OPENROUTER_API_KEY={OR_KEY}\n"}, "plant", "gitleaks:", OR_KEY),
    ("message-only", {}, f"fix thing for {DENY_EMAIL}", "denylist", DENY_EMAIL),
]


@pytest.mark.parametrize("name,files,msg,rule,secret", PLANTS, ids=[p[0] for p in PLANTS])
def test_push_blocked(env, name, files, msg, rule, secret):
    repo, remote = env.make_repo()
    if files:
        env.commit_raw(repo, files, msg)
    else:
        env.git("commit", "--allow-empty", "--no-verify", "-m", msg, cwd=repo, check=True)
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0
    assert "PUBLIC-GUARD: push to PUBLIC repo proj-remote BLOCKED" in res.stderr
    assert "finding(s)" in res.stderr
    assert rule in res.stderr
    assert "AGENTS: stop here. Do not retry, do not use --no-verify" in res.stderr
    if secret:
        assert secret not in res.stderr, "match must be redacted"
        assert secret[:3] + "…" in res.stderr
    # nothing landed on the remote
    assert env.git("rev-parse", "--verify", "main", cwd=remote).returncode != 0


def test_second_push_only_scans_new_range(env):
    repo, remote = env.make_repo()
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.commit_raw(repo, {"b.txt": "fine\n"}, "ok")
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.commit_raw(repo, {".env": "A=1\n"}, "bad")
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "forbidden-path" in res.stderr


def test_home_private_remotes_file_is_ignored(env):
    """An agent-writable ~/.config private-remotes.txt must not switch the guard off."""
    repo, remote = env.make_repo()
    (env.guard_dir / "private-remotes.txt").write_text(f"# private\n{remote}\n")
    env.commit_raw(repo, {".env": "A=1\n"})
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "forbidden-path" in res.stderr


def test_policy_file_change_needs_human(env):
    repo, remote = env.make_repo()
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.commit_raw(repo, {".public-guard-allow": "*.md\n"}, "allow")
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0
    assert "policy-file-changed" in res.stderr
    env.commit_raw(repo, {".gitleaks.toml": "[extend]\nuseDefault = true\n"}, "cfg")
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "policy-file-changed" in res.stderr


def test_allow_file_in_remote_does_not_cover_denylist(env):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {".public-guard-allow": "*\n"}, "allow")
    env.commit_raw(repo, {"x.txt": f"mail {DENY_EMAIL}\n"}, "mail")
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "denylist" in res.stderr


def test_human_at_tty_can_approve(env):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {".env": "A=1\n"}, "bad")
    child_env = dict(env.base)
    pid, fd = pty.fork()
    if pid == 0:  # child gets the pty as its controlling terminal
        os.chdir(repo)
        os.execvpe("git", ["git", "push", "origin", "main"], child_env)  # noqa: S606
    out = b""
    sent = False
    deadline = time.time() + 60
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 1)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if b"press Enter" in out and not sent:
                os.write(fd, b"proj-remote\n")
                sent = True
    _, status = os.waitpid(pid, 0)
    assert sent, out.decode(errors="replace")
    assert os.WEXITSTATUS(status) == 0, out.decode(errors="replace")
    assert env.git("rev-parse", "--verify", "main", cwd=remote).returncode == 0


def test_human_wrong_name_is_refused(env):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {".env": "A=1\n"}, "bad")
    pid, fd = pty.fork()
    if pid == 0:
        os.chdir(repo)
        os.execvpe("git", ["git", "push", "origin", "main"], dict(env.base))  # noqa: S606
    out = b""
    sent = False
    deadline = time.time() + 60
    while time.time() < deadline:
        r, _, _ = select.select([fd], [], [], 1)
        if r:
            try:
                chunk = os.read(fd, 4096)
            except OSError:
                break
            if not chunk:
                break
            out += chunk
            if b"press Enter" in out and not sent:
                os.write(fd, b"yes\n")
                sent = True
    _, status = os.waitpid(pid, 0)
    assert sent and os.WEXITSTATUS(status) != 0
    assert env.git("rev-parse", "--verify", "main", cwd=remote).returncode != 0


# ------------------------------------------------------------------------------ pre-commit + chaining


def test_pre_commit_blocks_staged_mcp_json(env):
    repo, remote = env.make_repo()
    (repo / ".mcp.json").write_text("{}\n")
    env.git("add", ".mcp.json", cwd=repo, check=True)
    res = env.git("commit", "-m", "x", cwd=repo)
    assert res.returncode != 0
    assert "forbidden-path" in res.stderr and "BLOCKED" in res.stderr


def test_pre_commit_blocks_staged_denylist(env):
    repo, remote = env.make_repo()
    (repo / "a.txt").write_text(f"x {DENY_EMAIL}\n")
    env.git("add", "a.txt", cwd=repo, check=True)
    res = env.git("commit", "-m", "x", cwd=repo)
    assert res.returncode != 0 and "denylist" in res.stderr and DENY_EMAIL not in res.stderr


def test_pre_commit_skips_repo_without_guarded_remote(env):
    repo = env.work / "solo"
    env.git("init", "-b", "main", str(repo), check=True)
    (repo / ".mcp.json").write_text("{}\n")
    env.git("add", ".", cwd=repo, check=True)
    assert env.git("commit", "-m", "x", cwd=repo).returncode == 0


def test_repo_local_hooks_are_chained(env):
    repo, remote = env.make_repo()
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    marker = repo / "marker.txt"
    (hooks / "pre-commit").write_text(f'#!/bin/sh\necho ran >> "{marker}"\nexit 0\n')
    (hooks / "pre-commit").chmod(0o755)
    (hooks / "post-commit").write_text(f'#!/bin/sh\necho post >> "{marker}"\n')
    (hooks / "post-commit").chmod(0o755)
    (repo / "b.txt").write_text("b\n")
    env.git("add", "b.txt", cwd=repo, check=True)
    assert env.git("commit", "-m", "b", cwd=repo).returncode == 0
    assert marker.read_text().split() == ["ran", "post"]
    # failure of the repo hook fails the commit
    (hooks / "pre-commit").write_text("#!/bin/sh\nexit 1\n")
    (repo / "c.txt").write_text("c\n")
    env.git("add", "c.txt", cwd=repo, check=True)
    assert env.git("commit", "-m", "c", cwd=repo).returncode != 0


def test_repo_local_pre_push_chained_with_stdin(env):
    repo, remote = env.make_repo()
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    seen = repo / "seen.txt"
    (hooks / "pre-push").write_text(f'#!/bin/sh\ncat > "{seen}"\nexit 0\n')
    (hooks / "pre-push").chmod(0o755)
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    assert "refs/heads/main" in seen.read_text()
    (hooks / "pre-push").write_text("#!/bin/sh\nexit 3\n")
    env.commit_raw(repo, {"d.txt": "d\n"}, "d")
    assert env.git("push", "origin", "main", cwd=repo).returncode != 0


# ------------------------------------------------------------------------------ detection


def load_guard():
    spec = importlib.util.spec_from_file_location("pg_guard_under_test", GUARD)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def inproc(env, monkeypatch):
    """guard.py imported in-process, pointed at the temp HOME, stubs allowed under /tmp."""
    g = load_guard()
    monkeypatch.setenv("HOME", str(env.home))
    for k in list(os.environ):
        if k.startswith("PUBLIC_GUARD_"):
            monkeypatch.delenv(k)
    monkeypatch.setattr(g, "UNTRUSTED_PREFIXES", ())
    monkeypatch.chdir(env.work)
    return g


def stub_gh(env, body: str):
    gh = env.stub / "gh"
    gh.write_text(f"#!/bin/sh\n{body}\n")
    gh.chmod(0o755)
    tools = json.loads((env.guard_dir / "tools.json").read_text())
    tools["gh"] = str(gh)
    (env.guard_dir / "tools.json").write_text(json.dumps(tools))


def poison_cache(env, key, verdict):
    cdir = env.home / ".cache" / "public-guard"
    cdir.mkdir(parents=True, exist_ok=True)
    (cdir / "visibility.json").write_text(json.dumps({key: {"v": verdict, "t": time.time()}}))


def test_cached_private_verdict_is_never_trusted(env, inproc):
    url = "git@github.com:acme/widgets.git"
    poison_cache(env, "acme/widgets", "private")  # the bypass: agent writes the cache
    stub_gh(env, "echo public")
    assert inproc.classify(url)[0] == "public"
    stub_gh(env, "exit 1")
    poison_cache(env, "acme/other", "private")
    assert inproc.classify("https://github.com/acme/other")[0] == "unknown"
    assert inproc.is_guarded("https://github.com/acme/other")


def test_private_comes_only_from_a_live_call_and_is_not_cached(env, inproc):
    url = "git@github.com:acme/widgets.git"
    stub_gh(env, "echo private")
    assert inproc.classify(url)[0] == "private"
    cache = env.home / ".cache" / "public-guard" / "visibility.json"
    assert "private" not in (cache.read_text() if cache.exists() else "")
    stub_gh(env, "echo public")  # repo flipped public: seen immediately
    assert inproc.classify(url)[0] == "public"
    cached = json.loads(cache.read_text())
    assert cached["acme/widgets"]["v"] == "public"
    stub_gh(env, "echo internal")
    assert inproc.classify("https://github.com/acme/int")[0] == "private"


def test_pre_commit_skips_only_on_fresh_live_private(env, inproc):
    url = "https://github.com/acme/pc"
    poison_cache(env, "acme/pc", "private")
    stub_gh(env, "exit 1")
    assert inproc.is_guarded(url)  # cache says private, live call fails => guarded
    stub_gh(env, "echo private")
    assert not inproc.is_guarded(url)


def test_non_github_and_local_remotes(env, inproc):
    assert inproc.classify("https://git.example.com/x/y.git")[0] == "public"
    assert inproc.classify("/srv/git/z.git")[0] == "local"


def test_private_remotes_only_from_root_owned_system_file(env, inproc, monkeypatch, tmp_path):
    listing = tmp_path / "private-remotes.txt"
    listing.write_text("# x\nhttps://git.example.com/x/y.git\n")
    monkeypatch.setattr(inproc, "PRIVATE_REMOTES_FILE", str(listing))
    # the file is owned by the test user, not root => ignored
    assert inproc.classify("https://git.example.com/x/y")[0] == "public"
    monkeypatch.setattr(inproc, "TRUSTED_UID", os.getuid())
    assert inproc.classify("https://git.example.com/x/y")[0] == "private"
    assert inproc.classify("https://git.example.com/other")[0] == "public"
    # github remotes are never taken from the list
    listing.write_text("https://github.com/acme/w\n")
    stub_gh(env, "exit 1")
    assert inproc.classify("https://github.com/acme/w")[0] == "unknown"


def test_no_env_var_forces_private(env, inproc, monkeypatch):
    stub_gh(env, "exit 1")
    url = "https://github.com/someone/somerepo.git"
    for var in (
        "PUBLIC_GUARD_FORCE_PRIVATE",
        "PUBLIC_GUARD_PRIVATE",
        "PUBLIC_GUARD_SKIP",
        "PUBLIC_GUARD_DISABLE",
        "PUBLIC_GUARD_OFF",
        "PUBLIC_GUARD_FORCE_PUBLIC",
    ):
        monkeypatch.setenv(var, "0" if var.endswith("PUBLIC") else "1")
        assert inproc.classify(url)[0] != "private", var
        monkeypatch.delenv(var)
    repo, remote = env.make_repo()
    env.commit_raw(repo, {".env": "A=1\n"})
    res = env.git(
        "push",
        "origin",
        "main",
        cwd=repo,
        env_extra={"PUBLIC_GUARD_FORCE_PRIVATE": "1", "PUBLIC_GUARD_PRIVATE": "1"},
    )
    assert res.returncode != 0


def test_is_public_command_prints_status(env):
    res = env.run(
        [PYTHON, str(GUARD), "is-public", "https://git.example.com/x/y"],
        drop=("PUBLIC_GUARD_FORCE_PUBLIC",),
    )
    assert res.stdout.strip() == "public"


# ------------------------------------------------------------------------------ tool binaries


def write_tools(env, **kw):
    tools = json.loads((env.guard_dir / "tools.json").read_text())
    tools.update(kw)
    (env.guard_dir / "tools.json").write_text(json.dumps(tools))


def fake_gitleaks(dirpath: Path) -> Path:
    """A gitleaks that always reports 'clean' by writing [] to the -r file."""
    dirpath.mkdir(parents=True, exist_ok=True)
    fake = dirpath / "gitleaks"
    fake.write_text(
        '#!/bin/sh\nwhile [ $# -gt 0 ]; do if [ "$1" = "-r" ]; then echo "[]" > "$2"; fi; shift; done\nexit 0\n'
    )
    fake.chmod(0o755)
    return fake


def test_path_hijacked_gitleaks_cannot_blind_the_scan(env, tmp_path):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {"settings.txt": f"OPENROUTER_API_KEY={OR_KEY}\n"})
    fake = fake_gitleaks(tmp_path / "evil")
    res = env.git(
        "push",
        "origin",
        "main",
        cwd=repo,
        env_extra={"PATH": f"{fake.parent}:{os.environ['PATH']}"},
    )
    assert res.returncode != 0 and "gitleaks:" in res.stderr


@pytest.mark.parametrize("where", ["tmp", "repo", "missing", "relative", "unrecorded"])
def test_untrusted_recorded_gitleaks_blocks(env, tmp_path, where):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {"a.txt": "a\n"})
    if where == "tmp":
        value = str(fake_gitleaks(tmp_path / "evil"))
    elif where == "repo":
        value = str(fake_gitleaks(repo / "bin"))
        # the repo may live under /tmp too; either rule must refuse it
    elif where == "missing":
        value = "/usr/bin/gitleaks-does-not-exist"
    elif where == "relative":
        value = "gitleaks"
    else:
        value = None
    write_tools(env, gitleaks=value)
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0
    assert "PUBLIC-GUARD: ERROR" in res.stderr
    assert "run install.sh" in res.stderr or "refusing gitleaks" in res.stderr


def test_missing_tools_json_blocks(env):
    repo, remote = env.make_repo()
    (env.guard_dir / "tools.json").unlink()
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "install.sh" in res.stderr


def test_recorded_gh_under_tmp_is_refused(env, tmp_path):
    stub_gh(env, "echo private")  # recorded gh sits under /tmp, which the real guard refuses
    res = env.run(
        [PYTHON, str(GUARD), "is-public", "https://github.com/acme/w"],
        drop=("PUBLIC_GUARD_FORCE_PUBLIC",),
    )
    assert res.returncode != 0 and "refusing gh" in res.stderr
    assert res.stdout.strip() != "private"


# ------------------------------------------------------------------------------ install


def test_install_sets_hookspath_seeds_denylist_and_is_idempotent(tmp_path):
    e = Env(tmp_path)
    res = e.install()
    assert "WARNING" not in res.stderr
    want = str(e.guard_dir / "hooks")
    assert e.git("config", "--global", "--get", "core.hooksPath").stdout.strip() == want
    deny = e.guard_dir / "denylist.txt"
    text = deny.read_text()
    assert str(e.home) in text
    user = (
        os.environ.get("USER")
        or subprocess.run(["id", "-un"], capture_output=True, text=True).stdout.strip()
    )
    assert f"\\b{user}\\b" in text and f"C:\\Users\\{user}" in text
    assert oct(deny.stat().st_mode & 0o777) == "0o600"
    assert (e.guard_dir / "guard.py").exists()
    for hook in (
        "pre-commit",
        "pre-push",
        "commit-msg",
        "post-index-change",
        "fsmonitor-watchman",
        "reference-transaction",
    ):
        assert os.access(e.guard_dir / "hooks" / hook, os.X_OK), hook
    deny.write_text("# mine\nonly-me\n")
    e.install()
    assert deny.read_text() == "# mine\nonly-me\n"
    assert e.run(["bash", str(INSTALL), "--check"]).returncode == 0
    (e.guard_dir / "hooks" / "pre-push").write_text("#!/bin/sh\nexit 0\n")
    assert e.run(["bash", str(INSTALL), "--check"]).returncode == 1
    e.install()
    assert e.run(["bash", str(INSTALL), "--check"]).returncode == 0


def test_passthrough_hook_preserves_argv_stdin_and_exit(env):
    repo, remote = env.make_repo()
    hooks = repo / ".git" / "hooks"
    hooks.mkdir(exist_ok=True)
    out = repo / "out.txt"
    (hooks / "post-rewrite").write_text(f'#!/bin/sh\necho "$1" > "{out}"\ncat >> "{out}"\nexit 0\n')
    (hooks / "post-rewrite").chmod(0o755)
    res = env.run(
        [str(env.guard_dir / "hooks" / "post-rewrite"), "amend"], cwd=repo, input_="old new\n"
    )
    assert res.returncode == 0
    assert out.read_text() == "amend\nold new\n"
    (hooks / "post-rewrite").write_text("#!/bin/sh\nexit 7\n")
    assert (
        env.run([str(env.guard_dir / "hooks" / "post-rewrite"), "amend"], cwd=repo).returncode == 7
    )


# ------------------------------------------------------------------------------ block-bypass


def bypass(env, cmd, cwd=None, tool="Bash"):
    payload = json.dumps(
        {"tool_name": tool, "tool_input": {"command": cmd}, "cwd": str(cwd or env.work)}
    )
    return env.run([PYTHON, str(BYPASS)], input_=payload)


DENIED = [
    "git commit --no-verify -m x",
    "git push --no-verify origin main",
    "git commit -n -m x",
    "git commit -m x -n",
    "git commit -anm x",
    "git config --global core.hooksPath /dev/null",
    "git -c core.hooksPath=/dev/null commit -m x",
    "git config --unset core.hookspath",
    "HUSKY=0 git commit -m x",
    "SKIP=ruff git commit -m x",
    "SKIP=all pre-commit run",
    "rm -rf ~/.config/public-guard",
    "echo x > ~/.config/public-guard/denylist.txt",
    "mv ~/.cache/public-guard/visibility.json /tmp/x",
    "chmod -x .git/hooks/pre-push",
    "sed -i s/a/b/ .git/hooks/pre-commit",
    'python3 -c \'open("/x/.config/public-guard/guard.py","w")\'',
    "git push --force origin main",
    "git push -f",
    "git push origin +main",
    "git push -uf origin main",
    "ls && git push --force",
    "HOME=/tmp git push origin main",
    "GIT_CONFIG_GLOBAL=/dev/null git push",
]
ALLOWED = [
    'git commit -m "fix: a thing"',
    "git commit -am 'update notes'",
    "git push",
    "git push origin main",
    "git push -u origin main",
    "git push --force-with-lease",
    "git push --force-with-lease origin main",
    "git status",
    "cat ~/.config/public-guard/denylist.txt",
    "ls .git/hooks",
    "git log --oneline -n 5",
]


@pytest.fixture
def pushrepo(env):
    repo, remote = env.make_repo()
    return repo


@pytest.mark.parametrize("cmd", DENIED)
def test_bypass_denied(env, pushrepo, cmd):
    res = bypass(env, cmd, cwd=pushrepo)
    assert res.returncode == 2, (cmd, res.stderr)
    assert "public-guard bypass blocked" in res.stderr


@pytest.mark.parametrize("cmd", ALLOWED)
def test_bypass_allowed(env, pushrepo, cmd):
    res = bypass(env, cmd, cwd=pushrepo)
    assert res.returncode == 0, (cmd, res.stderr)


def test_bypass_ignores_non_bash_and_garbage(env):
    assert bypass(env, "git commit --no-verify", tool="Read").returncode == 0
    assert env.run([PYTHON, str(BYPASS)], input_="not json").returncode == 0


def test_force_push_to_local_remote_is_allowed(env, pushrepo):
    payload = json.dumps(
        {
            "tool_name": "Bash",
            "tool_input": {"command": "git push --force origin main"},
            "cwd": str(pushrepo),
        }
    )
    res = env.run([PYTHON, str(BYPASS)], input_=payload, drop=("PUBLIC_GUARD_FORCE_PUBLIC",))
    assert res.returncode == 0, res.stderr


def test_opencode_permission_snippet_is_valid(env):
    data = json.loads((GUARD_DIR / "agent-hooks" / "opencode-permission.json").read_text())
    bash = data["permission"]["bash"]
    assert bash["*--no-verify*"] == "deny" and bash["*core.hooksPath*"] == "deny"
    keys = list(bash)
    assert keys.index("git push* --force-with-lease*") > keys.index("git push* --force*")


# ------------------------------------------------------------------------------ audit


def test_audit_history_finds_secret_only_in_old_commit(env):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {"old.txt": f"OPENROUTER_API_KEY={OR_KEY}\n"}, "add key")
    env.git("rm", "-q", "old.txt", cwd=repo, check=True)
    env.git("commit", "--no-verify", "-m", "remove key", cwd=repo, check=True)
    tree = env.run([PYTHON, str(GUARD), "audit", str(repo)])
    assert tree.returncode == 0, tree.stderr
    hist = env.run([PYTHON, str(GUARD), "audit", "--history", str(repo)])
    assert hist.returncode == 1
    assert "gitleaks:" in hist.stderr and "old.txt" in hist.stderr
    assert OR_KEY not in hist.stderr


def test_audit_finds_tree_issues_and_commit_messages(env):
    repo, remote = env.make_repo()
    env.commit_raw(
        repo, {"docs/n.md": f"see {HOME_PATH}\n", "creds.pem": "x\n"}, f"for {DENY_EMAIL}"
    )
    res = env.run([PYTHON, str(GUARD), "audit", "--history", str(repo)])
    assert res.returncode == 1
    for needle in ("private-path", "forbidden-path", "commit-message:", "denylist"):
        assert needle in res.stderr, needle
    clean_repo, _ = env.make_repo("clean")
    ok = env.run([PYTHON, str(GUARD), "audit", "--history", str(clean_repo)])
    assert ok.returncode == 0, ok.stderr


def test_audit_honours_committed_allow_file_for_paths_but_not_denylist(env):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {"fixtures/a.pem": "x\n", ".public-guard-allow": "fixtures/*\n"}, "fx")
    assert env.run([PYTHON, str(GUARD), "audit", str(repo)]).returncode == 0
    env.commit_raw(repo, {"fixtures/b.txt": f"{DENY_EMAIL}\n"}, "mail")
    assert env.run([PYTHON, str(GUARD), "audit", str(repo)]).returncode == 1


def test_inline_gitleaks_allow_comment_is_ignored(env):
    repo, remote = env.make_repo()
    env.commit_raw(repo, {"k.txt": f"OPENROUTER_API_KEY={OR_KEY} # gitleaks:allow\n"})
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "gitleaks:" in res.stderr


# ------------------------------------------------------------------------------ round 2

DENIED_R2 = [
    "git push --no-verif",
    "git push --no-v origin main",
    "git commit --no-verif -m x",
    'git push --no-ver""ify',
    'git push "--no-"verify',
    "git push '--no-ve'rify origin main",
    "git merge --no-verify other",
    "git rebase --no-verify main",
    "git am --no-verify x.patch",
    "env -u HOME git push",
    "env -i git push",
    "export HOME=/tmp/x; git push",
    "export PATH=/tmp/evil:$PATH && git push",
    "PATH=/tmp/evil:$PATH git push",
    "GIT_CONFIG_COUNT=1 GIT_CONFIG_KEY_0=x GIT_CONFIG_VALUE_0=y git push",
    "GIT_CONFIG_PARAMETERS=x git push",
    "GIT_CONFIG_NOSYSTEM=1 git push",
    "GIT_CONFIG_SYSTEM=/dev/null git push",
    "GIT_EXEC_PATH=/tmp/x git push",
    "git send-pack /x HEAD:main",
    "git receive-pack /x",
    "git config --global --remove-section core",
    "git config --global --edit",
    "git config -e",
    "git config --global core.hooksPath /x",
    'git -c "core.hook"s"Path=x" push',
    "rm ~/.gitconfig",
    "sed -i /hooksPath/d ~/.gitconfig",
    "echo x >> /etc/gitconfig",
    "tee ~/.config/git/config",
    "rm -rf /etc/public-guard",
    "cd ~/.config && rm -r public-guard",
    "cd ~/.cache; rm -rf public-guard",
    "mv ~/.gitconfig /tmp/gc",
    "gh api -X PUT repos/o/r/contents/x.txt -f message=m",
    "gh api --method POST repos/o/r/git/refs -f ref=x",
    "gh api repos/o/r/contents/x -XPUT",
    "bash -c 'git push --no-verify'",
]
ALLOWED_R2 = [
    'git commit -m "tidy -n flag"',
    "git log --no-merges --oneline",
    "git merge --no-ff topic",
    "git commit --no-edit --no-gpg-sign",
    "git config user.name someone",
    "git config --global user.email a@b.example",
    "cat ~/.gitconfig",
    "gh api repos/o/r --jq .visibility",
    "gh api -X GET repos/o/r/contents/README.md",
    "gh api -X PATCH repos/o/r -f name=x",
    "python3 ops/public-guard/guard.py audit --history .",
    "cd ops/public-guard && ls",
    "git push origin feature/x",
    "ruff check . && pytest -q",
]


@pytest.mark.parametrize("cmd", DENIED_R2)
def test_bypass_denied_round2(env, pushrepo, cmd):
    res = bypass(env, cmd, cwd=pushrepo)
    assert res.returncode == 2, (cmd, res.stderr)
    assert "public-guard bypass blocked" in res.stderr


@pytest.mark.parametrize("cmd", ALLOWED_R2)
def test_bypass_allowed_round2(env, pushrepo, cmd):
    res = bypass(env, cmd, cwd=pushrepo)
    assert res.returncode == 0, (cmd, res.stderr)


def test_bypass_blocks_mcp_push_tools_but_not_reads(env):
    for tool in (
        "mcp__github__push_files",
        "mcp__github__create_or_update_file",
        "mcp__github__create_branch",
        "mcp__github__fork_repository",
    ):
        res = bypass(env, "", tool=tool)
        assert res.returncode == 2, tool
        assert "public-guard: use git push so the scan runs" in res.stderr
    assert bypass(env, "", tool="mcp__github__get_file_contents").returncode == 0


def conflict_merge(env, repo, resolution):
    env.commit_raw(repo, {"f.txt": "base\n"}, "base")
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.git("checkout", "-q", "-b", "feat", cwd=repo, check=True)
    env.commit_raw(repo, {"f.txt": "feat\n"}, "feat")
    env.git("checkout", "-q", "main", cwd=repo, check=True)
    env.commit_raw(repo, {"f.txt": "main\n"}, "main")
    assert env.git("push", "origin", "main", "feat", cwd=repo).returncode == 0
    assert env.git("merge", "feat", cwd=repo).returncode != 0  # conflict
    (repo / "f.txt").write_text(resolution)
    env.git("add", "f.txt", cwd=repo, check=True)
    env.git("commit", "--no-verify", "-m", "merge feat", cwd=repo, check=True)
    assert len(env.git("rev-list", "--parents", "-n1", "HEAD", cwd=repo).stdout.split()) == 3


def test_secret_introduced_only_in_merge_resolution_is_blocked(env):
    repo, remote = env.make_repo()
    conflict_merge(env, repo, f"OPENROUTER_API_KEY={OR_KEY}\n")
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0
    assert "gitleaks:" in res.stderr and "f.txt" in res.stderr
    assert OR_KEY not in res.stderr


def test_merge_resolution_with_denylist_hit_is_blocked(env):
    repo, remote = env.make_repo()
    conflict_merge(env, repo, f"{DENY_EMAIL}\n")
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "denylist" in res.stderr


def test_clean_merge_pushes(env):
    repo, remote = env.make_repo()
    conflict_merge(env, repo, "resolved\n")
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0


TAG_PAYLOADS = [
    ("denylist", f"release for {DENY_EMAIL}", "denylist", DENY_EMAIL),
    ("key", f"OPENROUTER_API_KEY={OR_KEY}", "gitleaks:", OR_KEY),
    ("path", f"built in {HOME_PATH}", "private-path", HOME_PATH),
]


@pytest.mark.parametrize("name,msg,rule,secret", TAG_PAYLOADS, ids=[t[0] for t in TAG_PAYLOADS])
def test_annotated_tag_message_is_scanned(env, name, msg, rule, secret):
    repo, remote = env.make_repo()
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.git("tag", "-a", "v1", "-m", msg, cwd=repo, check=True)
    res = env.git("push", "origin", "v1", cwd=repo)
    assert res.returncode != 0
    assert "tag-message:" in res.stderr and rule in res.stderr
    assert secret not in res.stderr
    assert env.git("tag", "-l", "v1", cwd=remote).stdout.strip() == ""
    res = env.git("push", "origin", "--tags", cwd=repo)
    assert res.returncode != 0 and "tag-message:" in res.stderr


def test_clean_tags_still_push_and_non_commit_targets_are_refused(env):
    repo, remote = env.make_repo()
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.git("tag", "v0", cwd=repo, check=True)
    env.git("tag", "-a", "v2", "-m", "clean release", cwd=repo, check=True)
    assert env.git("push", "origin", "v0", "v2", cwd=repo).returncode == 0
    env.git("tag", "-a", "treetag", "-m", "x", "main^{tree}", cwd=repo, check=True)
    res = env.git("push", "origin", "treetag", cwd=repo)
    assert res.returncode != 0 and "not a commit" in res.stderr


PERMISSIVE_TOML = "[extend]\nuseDefault = true\n[allowlist]\npaths = ['''.*''']\n"


def test_gitleaks_config_comes_from_remote_base_not_pushed_tip(env):
    repo, remote = env.make_repo()
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.commit_raw(
        repo, {".gitleaks.toml": PERMISSIVE_TOML, "k.txt": f"OPENROUTER_API_KEY={OR_KEY}\n"}
    )
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0
    assert "policy-file-changed" in res.stderr
    assert "gitleaks:" in res.stderr, "the pushed tip's own allowlist must not blind the scan"


def test_remote_base_config_is_the_one_applied(env):
    repo, remote = env.make_repo()
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    toml = "[extend]\nuseDefault = true\n[allowlist]\npaths = ['''^k\\.txt$''']\n"
    env.commit_raw(repo, {".gitleaks.toml": toml})
    # land the config on the remote the way a human would (hooks off), then push a hit in k.txt
    landed = env.git("-c", "core.hooksPath=/dev/null", "push", "origin", "main", cwd=repo)
    assert landed.returncode == 0
    env.commit_raw(repo, {"k.txt": f"OPENROUTER_API_KEY={OR_KEY}\n"})
    assert env.git("push", "origin", "main", cwd=repo).returncode == 0
    env.commit_raw(repo, {"other.txt": f"OPENROUTER_API_KEY={OR_KEY}\n"})
    assert env.git("push", "origin", "main", cwd=repo).returncode != 0


def test_missing_denylist_blocks(env):
    repo, remote = env.make_repo()
    (env.guard_dir / "denylist.txt").unlink()
    res = env.git("push", "origin", "main", cwd=repo)
    assert res.returncode != 0 and "run install.sh" in res.stderr
    (repo / "a.txt").write_text("a\n")
    env.git("add", "a.txt", cwd=repo, check=True)
    res = env.git("commit", "-m", "a", cwd=repo)
    assert res.returncode != 0 and "run install.sh" in res.stderr


BAD_STDIN = [
    "garbage",
    "refs/heads/main abc refs/heads/main def",
    "a b c",
    "refs/heads/main " + "1" * 40 + " refs/heads/main",
]


@pytest.mark.parametrize("line", BAD_STDIN)
def test_unparseable_pre_push_stdin_blocks(env, line):
    repo, remote = env.make_repo()
    cmd = [PYTHON, str(GUARD), "pre-push", "origin", str(remote)]
    res = env.run(cmd, cwd=repo, input_=line + "\n")
    assert res.returncode != 0 and "unparseable" in res.stderr
    assert env.run(cmd, cwd=repo, input_="").returncode == 0


def test_install_records_tool_paths(tmp_path):
    e = Env(tmp_path)
    e.install()
    tj = e.guard_dir / "tools.json"
    assert oct(tj.stat().st_mode & 0o777) == "0o600"
    data = json.loads(tj.read_text())
    want = "/usr/bin/gitleaks" if os.path.exists("/usr/bin/gitleaks") else shutil.which("gitleaks")
    assert data["gitleaks"] == want
    assert data["gh"] is None or not data["gh"].startswith(("/tmp", "/var/tmp", "/dev/shm"))
    tj.write_text('{"gitleaks": "/tmp/evil/gitleaks", "gh": null}')
    assert e.run(["bash", str(INSTALL), "--check"]).returncode == 1
    e.install()
    assert json.loads(tj.read_text())["gitleaks"] == data["gitleaks"]
    assert not (e.guard_dir / "private-remotes.txt").exists()


def test_install_system_prints_commands_and_changes_nothing(tmp_path):
    e = Env(tmp_path)
    res = e.run(["bash", str(INSTALL), "--system"])
    assert res.returncode == 0
    out = res.stdout
    assert "sudo git config --system core.hooksPath" in out
    assert "/etc/public-guard" in out and "root" in out
    assert not e.guard_dir.exists()
    assert e.git("config", "--global", "--get", "core.hooksPath").stdout.strip() == ""

# public-guard

Makes pushing secrets or private data to a PUBLIC repo mechanically hard: global git hooks, a CI scan
and an agent tripwire. Fails closed (errors, missing gitleaks/denylist, bad input, unknown visibility).

## 1. Install once per machine (root-owned, the real setup)
    ops/public-guard/install.sh --system   # PRINTS the sudo commands; read them, then run them yourself
Layout: `/usr/local/lib/public-guard/` (guard.py, hooks), `/etc/public-guard/` (tools.json,
denylist.txt root:<you> 0640, private-remotes.txt), `/etc/gitconfig` (core.hooksPath). Your existing
`~/.config/public-guard/denylist.txt` is copied in. Then turn passwordless sudo off.
Plain `install.sh` (and `--check`) is the USER-level dev/test path; the guard then warns on every run
"public-guard running in USER mode - install --system". gitleaks/gh must be root-owned (/usr/bin).
Denylist lines: plain = case-insensitive literal, `re:<regex>`; a missing denylist blocks.
Wire `agent-hooks/block-bypass.py` as a Claude Code PreToolUse hook (no matcher: it also covers
Write/Edit and the GitHub MCP push tools) and merge `agent-hooks/opencode-permission.json`.
Repos using the pre-commit framework: `pre-commit install` refuses while core.hooksPath is set. Owner runs
`GIT_CONFIG_NOSYSTEM=1 .venv/bin/pre-commit install` once per clone; the guard still runs, then chains to it.

## 2. Before making ANY repo public
    python3 ops/public-guard/guard.py audit --history <repo>   # tree + every commit + messages
    ops/public-guard/github-harden.sh <owner/repo>             # secret scanning + push protection
    cp ops/public-guard/ci/secret-scan.yml <repo>/.github/workflows/secret-scan.yml
Fix every finding (rewrite history if committed) until audit exits 0.

## What it checks (pre-push to a public remote; pre-commit on the staged diff)
- gitleaks over pushed commits incl. merge resolutions and tag messages; config read from the REMOTE
  base, never the pushed tip; the denylist; forbidden paths (.env, keys, *.db ...); real home paths
- Public = live `gh` visibility not private (only "public" is cached), unknown, or non-GitHub and not
  in root-owned `/etc/public-guard/private-remotes.txt`

## When blocked
Agents: stop, do not retry or bypass, paste the block message to the owner verbatim. Owner: remove the
data (rewrite history if committed) or push from a terminal and type the repo name to approve.

## Limits
block-bypass.py is a string tripwire, not a sandbox: runtime-built flags such as
`$(printf --no-ver%s ify)` or python string concatenation defeat it. Passwordless sudo lets any agent
undo the root-owned layer; turn it off after install. GitHub push protection is the server-side
backstop for provider-format secrets; CI is the second.

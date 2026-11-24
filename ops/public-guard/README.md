# public-guard

Makes pushing secrets or private data to a PUBLIC repo mechanically hard. Enforced by code (global
git hooks, a CI scan, an agent tripwire). Fails closed: errors, missing gitleaks or denylist,
unparseable input and unknown visibility all block.

## 1. Install once per machine
    ops/public-guard/install.sh          # hooks + guard.py -> ~/.config/public-guard, sets core.hooksPath,
                                         # records absolute gitleaks/gh paths in tools.json
    ops/public-guard/install.sh --check  # exit 1 on drift
    ops/public-guard/install.sh --system # PRINTS the sudo commands (root-owned hooks, /etc/gitconfig,
                                         # /etc/public-guard); run them yourself
Edit `~/.config/public-guard/denylist.txt` (never in any repo): private names, domains, customers;
plain lines are case-insensitive literals, `re:<regex>` lines regexes. A missing denylist blocks.
Wire `agent-hooks/block-bypass.py` as a Claude Code PreToolUse hook (no matcher, it also denies the
GitHub MCP push tools) and merge `agent-hooks/opencode-permission.json` into the OpenCode config.

## 2. Before making ANY repo public
    python3 ops/public-guard/guard.py audit --history <repo>   # tree + every commit + messages
    ops/public-guard/github-harden.sh <owner/repo>             # secret scanning + push protection
    cp ops/public-guard/ci/secret-scan.yml <repo>/.github/workflows/secret-scan.yml
Fix every finding (rewrite history if it was committed) until audit exits 0.
## What it checks (pre-push to a public remote; pre-commit on the staged diff)
- gitleaks over the pushed commits incl. merge resolutions and annotated tag messages. Its config is
  read from the REMOTE base of the push, never the pushed tip; inline allows are ignored
- the private denylist, against added lines, commit messages and added paths
- forbidden paths (.env, keys, .mcp.json, *.db, *.log, ...) in the pushed diff and the tip tree
- home-directory paths of real users
Public = GitHub repo whose live `gh api` visibility is not private (only "public" is cached, 24 h),
or any non-GitHub remote not listed in root-owned `/etc/public-guard/private-remotes.txt`.

## When a push is blocked
Agents: stop, do not retry, do not bypass, paste the block message to the owner verbatim.
Owner: remove the data (rewrite history if already committed), or run the push yourself in a terminal
and type the repo name to approve an exception. Nothing else skips it. `.public-guard-allow` (path
globs, `rule:<id>`) is read from the remote base; changing it or `.gitleaks.toml` always needs you.

## Limits
block-bypass.py is a tripwire, not a sandbox. A determined agent can still tamper with the machine;
only the root-owned `--system` setup, CI and GitHub push protection hold against that.

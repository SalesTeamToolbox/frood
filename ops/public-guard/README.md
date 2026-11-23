# public-guard

Makes pushing secrets or private data to a PUBLIC repo mechanically impossible. Enforced by code
(global git hooks, a CI scan, an agent tripwire) so it still holds when a weak agent ignores
instructions. Fails closed: errors, missing gitleaks, unknown visibility all block.

## 1. Install once per machine
    ops/public-guard/install.sh          # hooks + guard.py -> ~/.config/public-guard, sets core.hooksPath
    ops/public-guard/install.sh --check  # exit 1 on drift
Then edit `~/.config/public-guard/denylist.txt` (never in any repo): private names, domains, customers.
Plain lines are case-insensitive literals, `re:<regex>` lines are regexes. Install gitleaks too.
Wire `agent-hooks/block-bypass.py` as a Claude Code PreToolUse hook (matcher `Bash`) and merge
`agent-hooks/opencode-permission.json` into the OpenCode config. Both stop `--no-verify`, hook/config
edits and force pushes.

## 2. Before making ANY repo public
    python3 ops/public-guard/guard.py audit --history <repo>   # tree + every commit + messages
    ops/public-guard/github-harden.sh <owner/repo>             # secret scanning + push protection
    cp ops/public-guard/ci/secret-scan.yml <repo>/.github/workflows/secret-scan.yml
Fix every finding (rewrite history if it was committed) until audit exits 0.

## What it checks (pre-push to a public remote; pre-commit on the staged diff)
- gitleaks over the pushed commits (repo `.gitleaks.toml` read from the pushed tip; inline
  `gitleaks:allow` and `.gitleaksignore` are ignored)
- the private denylist, against added lines, commit messages and added paths
- forbidden paths (.env, keys, .mcp.json, *.db, *.log, ...) in the pushed diff and the tip tree
- home-directory paths of real users (`/home/<name>/`, `/Users/<name>/`, `C:\Users\<name>\`)
Public = GitHub repo whose `gh api` visibility is public (cached 24 h), unknown, or any non-GitHub
remote not listed in `~/.config/public-guard/private-remotes.txt`. Local-path remotes are not guarded.

## When a push is blocked
Agents: stop, do not retry, do not bypass, paste the block message to the owner verbatim.
Owner: remove the data (rewrite history if already committed), or run the push yourself in a terminal;
the guard then asks you to type the repo name to approve an exception. There is no env var or flag that
skips this. A repo may commit `.public-guard-allow` (path globs, `rule:<id>`, or `<glob> rule:<id>`),
but adding or changing it, or `.gitleaks.toml`, always needs that human approval. Denylist hits can
never be allowlisted.
## Limits
This stops accidents and careless agents. A determined agent with shell access could still tamper
with the machine; the CI scan and GitHub push protection are the second line.

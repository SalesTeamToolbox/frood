# Examples — local config the installer never ships

Everything here is a **template with placeholder values**. Nothing in this repo reads these files:
copy one next to your own config, replace the placeholders, and keep it out of version control.
The paths below are illustrative (`~`, `~/projects/...`, `example.internal`).

## `harness-config.json` → `~/.claude/harness-config.json`

Read by `hooks/cross-harness-statusline.js` (the CC statusline, `/harness` and the HTML dashboard).

| Key | Type | Meaning |
|---|---|---|
| `remotes` | `[{ name, alias, enabled }]` | Machines to probe (TCP connect only). `alias` is the ssh alias; `enabled: false` lists it without connecting. |
| `repos` | `[{ label, dir }]` | Repos whose release train and verify runs appear on the statusline. Empty or absent = those rows are hidden. |
| `peerMailDist` | string | Path to peer-mail's `dist/sessions.js` (the full session list). Absent = the peer section says "peer-mail not configured". |
| `probeFallbacks` | `{ alias: { host, port } }` | Targets for aliases `~/.ssh/config` does not define. |

## `worker-env.json` → `~/.config/orchestrator/worker-env.json`

Extra environment for every `bin/oc-worker.mjs` run (`{ "VAR": "value" }`).

- A variable is set only when your environment does not already define it (an explicit value always wins).
- `{state}` expands to the orchestrator state dir (`$ORCH_HOME` or your home, then `.config/orchestrator`).
- A value written as `{state}/...` is created as a directory before the run.

Typical use: point a tool that keeps a locked dir under the session cwd (which breaks
`git worktree remove`) at one shared dir outside any repo:

```json
{ "EXAMPLE_WORKSPACE": "{state}/example-workspace" }
```

## Installed files carry your paths, the repo does not

Sources in this repo use two install-time tokens, which `bin/install.mjs` replaces in every file it
installs (hooks included):

| Token | Becomes |
|---|---|
| `{{ORCH_REPO}}` | this checkout, forward slashes (`C:/path/to/orchestrator` or `/home/you/orchestrator`) |
| `{{HOME}}` | the install home (`$HOME`, or `%USERPROFILE%`; `ORCH_HOME` in tests) |

So a tracked command or hook never needs to name a machine.

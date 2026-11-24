# orchestrator

One versioned source for the cross-harness orchestrator (Claude Code + OpenCode) on this machine: slash
commands, the routing rule, role agents, board and worker scripts, session hooks, and the installer that
renders them into each harness's config directory. It lives at `orchestrator/` in the Frood repo; edit there,
run the installer; never hand-edit the installed copies (they are overwritten).

Requires Node >= 22 (`package.json` `engines`). No runtime dependencies.

## Architecture

```
 orchestrator session            plans, writes Mandates, judges, signs off
        |                        (commands/frood-orchestrator.md, agents/orchestrator*.md)
        v
 board  bin/board.mjs            tickets + locks in <repo>/.opencode/board/; records and
        |                        verifies evidence, never runs work
        v
 workers                         bin/oc-worker.mjs  (headless OpenCode agent run)
        |                        or the Claude Code `worker` agent
        v
 critic review loop              critic findings -> bin/verdict-gate.mjs (mechanical verdict)
        |                        free models never sign off (APPROVED_FREE needs a paid/human sign-off)
        v
 the consuming repo's train      (e.g. ops/train.sh) -- the only ship path
                                 (board verify before boarding, board shipped after deploy)
```

- The orchestrator plans and judges; it does not write product code. Workers implement one Mandate in one
  worktree. Critics review; the board re-runs the verdict gate itself and binds every sign-off to the
  reviewed commit sha.
- The board records and verifies evidence only: it does not create worktrees, run the train, send mail or
  check pool health (`docs/designs/board.md`, "Scope").
- Peer-mail carries wake-ups and links; the board, ticket, report and receipt files are the truth.
- Rules the loop enforces (from `bin/board.mjs` and `docs/designs/board.md`): EGM gate for new modules or
  risky scope, max 3 counted review rounds, sign-off bound to the shipped sha, senior review when triggered.

The desktop-app standard is nested sessions: when an orchestrator or ticket command starts the next session it
calls `start_session` so the child nests under it in the sidebar (`parentSessionId`). Orphan notices stay top
level — their parent is dead by definition — and OpenCode is excepted: it has no session tool and keeps opening
tabs by hand.

## Install

```
node bin/install.mjs            install; backs up anything it overwrites or removes
node bin/install.mjs --check    report drift; exit 1 if anything differs, is missing or is orphaned;
                                then runs the routing lint (bin/check-routing.mjs)
node bin/install.mjs --dry-run  show what install would do, write nothing
```

`install.ps1` is a thin PowerShell wrapper: `pwsh install.ps1 [-Check] [-DryRun]` just runs
`node bin/install.mjs` with the matching flag and passes on its exit code. `package.json` also has
`npm run install-harness` and `npm run check`.

Where files go (`manifest.json`, `targets`; `~` is `ORCH_HOME` when set, else the user's home):

| Kind | Claude Code (`cc`) | OpenCode (`oc`) |
|---|---|---|
| commands | `~/.claude/commands` | `~/.config/opencode/commands` |
| agents | `~/.claude/agents` | `~/.config/opencode/agents` |
| hooks | `~/.claude/hooks` | (none) |
| rules | (none) | `~/.config/opencode/rules` |
| skills | (none) | `~/.config/opencode/skills` |

Each entry in `manifest.json` `entries` names a source, a kind and the harnesses it installs to; a source
that is a directory (`skills/frood-model-router-refresh`) is copied recursively. Two sources may not map to the
same target (install errors out).

- **Per-harness rendering.** Markdown sources can carry `cc-only` / `oc-only` tags: a trailing
  `# oc-only` / `<!-- cc-only -->` on a line, or a `<!-- oc-only -->` ... `<!-- /oc-only -->` block. Lines
  tagged for the other harness are dropped, tags are stripped. CRLF is normalized to LF.
- **Managed header.** Every installed `.md` gets a `<!-- managed by Frood ... Edit it there,
  then run install. Local edits are overwritten. -->` line, inserted right after YAML frontmatter (or at the
  top if there is none). Hooks (`.js`) are copied unchanged.
- **Backups.** An overwritten file, or an orphan (installed earlier, no longer in the manifest, which install
  then removes), is first copied to `~/.config/orchestrator/backups/<ISO timestamp>/<path relative to home>`.
- **State.** `~/.config/orchestrator/installed.json` records repo path, short sha (`-dirty` if uncommitted
  changes), time and every installed file; `--check` uses it to find orphans.
- Writes are temp file + rename (`*.orch-tmp`, gitignored). No symlinks or junctions are ever created.

## Layout

| Path | What |
|---|---|
| `agents/` | Role agent definitions (see Routing pools). |
| `commands/` | Slash commands, all under the `frood-` prefix: `frood-orchestrator`, `frood-gauntlet`, `frood-next`, `frood-ticket`, `frood-handback`, `frood-desk`, `frood-harness`, `frood-model-router-refresh`, `frood-egm-*`. `frood-desk`, `frood-orchestrator`, `frood-next`, `frood-ticket`, `frood-handback` and `frood-harness` install to both harnesses; the rest follow `manifest.json`. |
| `rules/` | `01-orchestrator-models.md`, the routing rule. |
| `skills/` | `frood-model-router-refresh/` (OpenCode skill). |
| `hooks/` | Claude Code hooks (below). |
| `bin/` | Scripts (below). |
| `docs/designs/` | `board.md`, the board design (schema, stage machine, commands). |
| `tests/` | `node --test` suites, one per script, plus `fixtures/`. |
| `manifest.json` | Source -> install target map. |
| `install.ps1` | PowerShell wrapper for the installer. |

`bin/`:

| Script | Purpose |
|---|---|
| `install.mjs` | Installer and drift check (above). |
| `desk.mjs` | The desk CLI: `status`, `watch --events [--by cc|oc] [--interval 30] [--once] [--takeover] [--until-event <sec>]`, `step <stream> <key> [--by cc|oc]`, `verdict`, `merge-check`. `--until-event` blocks until an event arrives (exit 0) or the deadline passes (exit 4). `--by` skips streams the other harness holds (`step` prints `HELD <stream> <holder>`). |
| `check-routing.mjs` | Routing lint: every OpenCode model ID is in live `opencode models`; no "Dropped" model in dispatch files; Claude Code model values are aliases; no bare "CC" in `rules/`. Exit 1 on failure. |
| `board.mjs` | Ticket board CLI: `create`, `egm`, `claim`, `heartbeat`, `attach`, `round`, `signoff`, `gates`, `ready`, `verify`, `shipped`, `reopen`, `watch`, `status`, `release`, `fail`, `unblock`, `quarantine`. `--help` lists them. |
| `oc-worker.mjs` | Launch one headless OpenCode agent run (worker, critic, scout, senior); writes the final text, an events file and a receipt; machine-wide `WORKER_SLOTS` cap (default 2); `--fallback` chain; `--ticket/--owner` attaches to a board ticket. |
| `verdict-gate.mjs` | Mechanical verdict for critic findings: needs a VERDICT line and a BLAST RADIUS section; any `UNREQUESTED` entry or `[blocker]`/`[major]` forces CHANGES_REQUESTED; `--free` turns APPROVED into APPROVED_FREE. Exit 0 approved, 1 changes, 2 invalid. |
| `pool-health.mjs` | Library: which models are down (quota, unavailable), stored in `~/.config/orchestrator/pool-health.json`; also reads the provider policy in `~/.config/orchestrator/providers.json`. Shared by `oc-worker` and `router-health`. |
| `router-health.mjs` | Self-correcting routing check: per role chain, which agent to dispatch first and why others were skipped; `--probe` / `--probe-all` live probes; `--if-stale <hours>`; `--decide <provider> routed\|ignored\|free-only --allow "<glob>,..."` records an owner provider decision. Never promotes a model outside its chains. |
| `handoff.mjs` | Module-boundary handoff for `/clear` then `/frood-next`: `write`, `show`, `consume`, `claim`, `release`. Pointer in `~/.config/orchestrator/handoff.json`, stale after 72 h; the prose lives in the plan file's `## Handoff` section. |
| `wt-finish.mjs` | Remove a merged worktree: `node bin/wt-finish.mjs <worktree> [--base <ref>] [--delete-branch] [--dry-run] [--json]`. Kills only MCP servers whose cwd is inside it (`mcp_server.py`, `opencode-peer-mail`; decided from the program and its script argument, `ORCH_WT_MCP_PATTERNS` replaces the patterns), refuses (exit 4) when any other process holds it, refuses (exit 5) a nested worktree, an unreadable process listing, or a link it could not unlink, and unlinks every untracked symlink/junction in the tree before `git worktree remove` can follow one. |
| `no-window.mjs` | Preloaded side-effect module: makes child processes hide their console window on Windows. |

`hooks/` (Claude Code only, installed to `~/.claude/hooks`; settings wiring is not managed here):

| Hook | Purpose |
|---|---|
| `peer-mail-session-id.js` | SessionStart: injects this session's peer-mail id and lists unread subjects (read-only). |
| `orchestrator-handoff.js` | SessionStart: announces a pending handoff so the owner only types `/frood-next`. UserPromptSubmit: names the session tab after the work on `/frood-next` and `/frood-gauntlet` (wire it under both events). |
| `cross-harness-statusline.js` | Two-line statusline plus HTML/text/JSON dashboard (`--html`, `--text`, `--json`). |
| `package.json` | Marks the directory CommonJS (`{ "type": "commonjs" }`); not installed. |

## Per-repo adapter: `.opencode/board/adapter.json`

The board needs one committed file per repo. Missing file = exit 2; every key below is required
(`bin/board.mjs` validates them on load; `docs/designs/board.md` has the schema).

| Key | Type | Used by `bin/board.mjs` as |
|---|---|---|
| `base` | string | Ref a ticket branches from; `claim` stores `git rev-parse <base>` as `base_sha`, and refuses if it does not resolve. |
| `branch_prefix` | string | Ticket branch = `branch_prefix` + ticket id (also in the `READY` wake-up line). |
| `gates` | array of argv arrays, >= 1 | Commands run by `board gates` (cwd = worktree, no shell, 20 min cap each, stops at first failure); `ready` requires each to have exit 0 at the signed-off sha. |
| `egm_paths` | array of globs | A ticket scope matching any glob adds the `data-model` EGM trigger, so EGM approval is required before `claim`. |
| `guarded_paths` | array of globs | A scope (at create) or changed file (at `round`, from `git diff --name-only <base_sha> HEAD`) matching any glob makes senior review required. |
| `stale_minutes` | number > 0 | Liveness threshold for `watch` and for breaking a stale ticket lock; must exceed the oc-worker timeout. |

Example (a consuming repo, shipped):

```json
{"base":"origin/main","branch_prefix":"feat/","gates":[["python","-m","pytest","tests/test_atlas.py","-q"]],"egm_paths":["**/migrations/**","alembic/**","**/auth*","**/billing*","**/wallet*"],"guarded_paths":["**/auth*","**/billing*","**/wallet*","alembic/**","ops/**"],"stale_minutes":45}
```

### How to add a repo

1. Commit `.opencode/board/adapter.json` with the six keys above.
2. Add an `ops/board.sh` shim that forwards to this repo's `bin/board.mjs` (`node <orchestrator>/bin/board.mjs "$@"`).
3. Wire the train (`ops/lib/orch-board.sh` in the design): `board verify <id> --sha <branch head>` at boarding
   and on each lap, refusing on non-zero; `board shipped <id> --sha <sha>` after a verified deploy. When the train
   refuses a ready ticket's sha, `board reopen <id> --owner <s> --harness <h> --note <why>` returns it to `working`
   (same id and branch; its signoffs are invalidated, so the fix needs a new round, signoff and gates).
4. Gitignore the runtime state: `.opencode/board/tickets`, `.opencode/board/locks`,
   `.opencode/board/.board.lock` (the design also lists `.watch.json` there as gitignored).
5. The board finds the repo root from any worktree via `git rev-parse --git-common-dir`, so nothing else is needed.

## Routing pools

`rules/01-orchestrator-models.md` is the only place with model IDs, prices and allowances. Do not copy them
elsewhere; `bin/check-routing.mjs` lints the dispatch files against it. Role agents (`agents/`; each pins its
own model so a spawn cannot inherit the orchestrator's):

| Agent | Role |
|---|---|
| `scout` | Cheap read-only search; file:line evidence, never edits. |
| `worker` | Routine code worker: one Mandate, one worktree, tests, commit, report. |
| `worker-strong` | Same contract, for harder tickets. |
| `worker-burst` | Same contract; used when the main worker pool is hot or capped. |
| `worker-alt` | Same contract; second fallback hop. |
| `worker-nvidia` | Same contract; free tier (cannot sign off). |
| `worker-free` | Same contract; free tier, last resort. |
| `critic` | One review pass of a diff against the Mandate; APPROVED or CHANGES_REQUESTED with file:line findings; never edits. |
| `critic-alt` | Alternate critic when the main critic pool is unavailable. |
| `critic-free` | Free-tier critic; its APPROVED counts only via `verdict-gate --free` plus a paid or human sign-off. |
| `senior` | Final blockers-only review of an already critic-approved diff, when a critic or the ticket asks for it. |
| `senior-alt` | Alternate senior when the main one is unavailable. |
| `orchestrator` | Runs one ticket end to end headless (worker, critic, senior loop). |
| `orchestrator-alt` | Orchestrator fallback when the main pool is capped. |
| `orchestrator-free` | Last-resort free orchestrator; its tickets end READY and need human or senior review. |

`scout`, `worker` and `critic` install to both harnesses; the rest are OpenCode only (`manifest.json`).
Availability: `bin/router-health.mjs` (per-role first healthy agent, `--probe`, `--decide <provider> ...`
for provider policy) on top of `bin/pool-health.mjs`. Session continuity across `/clear`: `bin/handoff.mjs`
with the `/frood-next` command. Refreshing the table: `/frood-model-router-refresh`.

## Tests

```
npm test
```

Runs `node --import ./bin/no-window.mjs --test --test-isolation=none "tests/**/*.test.mjs"`. Tests use a temp
`ORCH_HOME`, so they never touch the real installed files.

Machine rule: agents run at BelowNormal priority and only one heavy run at a time (the laptop is shared by
every agent and was hard-restarted once by parallel suites). Never raise priority to speed a run up.

## Harness parity

`frood-desk`, `frood-orchestrator`, `frood-next`, `frood-ticket`, `frood-handback` and `frood-harness` install to both harnesses; the others are harness-specific (see `manifest.json`).

### Taking a stream over and handing it back

A stream is leased to a harness (`cc` or `oc`), not to a session: `/frood-next <n>` claims it with `handoff.mjs claim`. If
the other harness holds it, `/frood-next` asks the owner and takes it over only on a yes; the other side's `write`, `note`
and the `/frood-orchestrator` lease guard then refuse it. `/frood-handback <n>` writes the handoff, stops this harness's desk
watcher and releases the stream to the other harness, which picks it up with `/frood-next <n>`.

The two harnesses legitimately differ in three places:

- **Watcher**: Claude Code uses `Monitor`; OpenCode blocks on `node {{ORCH_REPO}}/bin/desk.mjs watch --events --by oc --until-event 1800`.
- **Critic**: Claude Code spawns `Agent(subagent_type: "critic")`; OpenCode runs `node {{ORCH_REPO}}/bin/oc-worker.mjs --agent critic …`.
- **Background launch**: Claude Code uses `run_in_background`; OpenCode uses `shell` with `background: true`.

Streams and `desk-watch.lock` are harness-agnostic, so a stream started in one harness is finished by a desk in the other — one desk at a time across both.

OC commands now install to `~/.config/opencode/commands/`; the legacy singular `command/` copies are removed by install (and backed up).

## Off-switches

- `~/.config/orchestrator/dashboard.off` (empty file): `hooks/cross-harness-statusline.js` stops its
  background dashboard rebuilds and `bin/oc-worker.mjs` skips its dashboard kick (use it if console windows flash). Delete the file to re-enable.
- `ORCH_MAIL_LIVE_H` (default 24): the peer-mail badge counts only unread mail whose recipient was active
  within this many hours; mail to sessions that have gone quiet is reported as idle, not counted.
- `ORCH_ORPHAN_MIN` (default 60): minutes of holder silence after which an escalation on a held stream counts as
  orphaned and the daemon pages the owner once (see `docs/designs/desk-daemon.md`, "Orphaned streams").
- `ORCH_LAUNCH_CMD`: command the orphan notice's "Resolve in new session" action runs (`sh -c`, `{stream}` and
  `{harness}` substituted); overrides `launch.json`. Without it the action follows
  `~/.config/orchestrator/launch.json` (`{"mode": "desktop"|"terminal"|"custom", "cmd"?}`), written at setup by
  `ops/systemd/install.mjs` / `setup.sh` and changed with `node bin/launch-config.mjs --set desktop|terminal|custom
  [--cmd "<tpl>"]` (no args prints the effective mode). `desktop` opens the Claude desktop app via
  `claude://code/new?q=/frood-next <stream>&folder=<repo>`; `terminal` runs `xdg-terminal-exec -- claude "/frood-next
  <stream>"`. OpenCode-held streams always use `opencode --prompt` in a terminal. With no file the mode is detected
  (desktop if `xdg-mime query default x-scheme-handler/claude` has a handler).

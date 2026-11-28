---
description: Ticket board — records and verifies evidence; delegates to node orchestrator/bin/board.mjs
argument-hint: "<command> [args]"  # create, egm, claim, status, round, signoff, gates, ready, verify, shipped, ...
---

The Frood ticket board. Delegates to `node orchestrator/bin/board.mjs`, which
records and verifies evidence for a ticket (worktrees, gates and the train stay
outside the board itself).

**Usage:**
```
/frood-board create <id> --mandate <path> --scope <a,b,...> [--title <t>] [--egm-trigger <name>]...
/frood-board egm <id> approve --report <path> --by <who>  |  waive --reason <text> --by <who>
/frood-board claim <id> --owner <session> --harness claude|opencode --worktree <path>
/frood-board scope <id> --scope <a,b,...> --reason <text> --by <who> [--expect-epoch N]
/frood-board status [--json]
/frood-board round <id> --owner <session> --worker-receipt <path> --findings <path> --reviewed-sha <sha>
/frood-board signoff <id> --by critic|senior|human
/frood-board gates <id> --owner <session>
/frood-board ready <id> --owner <session> [--senior-skip "<reason>"]
/frood-board verify <id> --sha <sha>  |  shipped <id> --sha <sha>
/frood-board --help
```

This runs `node orchestrator/bin/board.mjs <command> [args]` in the ticket
worktree. `--help` (or `-h`) prints the board's full usage and exits 0; nothing
is written.
`--senior-skip` on `ready` overrides only a critic-only senior requirement: every live senior reason must start with `critic:`, the reason must be at least 20 characters, and the override is recorded on the ticket as `senior.skipped` (it never writes a signoff). Guarded-path and counted-rounds reasons still require a paid senior or a human.

Repo root = parent of `git rev-parse --git-common-dir` from `--repo`/cwd, so it
works from any worktree. Board dir = `<root>/.opencode/board/`.

---
description: Execute one plan module under the realistic gauntlet with receipts (any repo)
argument-hint: "[plan-path] [module]"  # cc-only
---

Run one module from the plan file: `/frood-gauntlet [plan-path] [module]`. One module
per run. Repo-specific conventions (base branch, gates, deploy) come from that
repo's instructions (`CLAUDE.md` / `AGENTS.md` / `.opencode/*-notes.md`) and its
board adapter (`.opencode/board/adapter.json`, when present), which override this file.

## Arguments

This run's arguments: $ARGUMENTS

- Plan path (first argument): the plan file for this run. Accepts a repo plan
  (`.claude/plans/plan-<slug>.md` or `.opencode/plans/plan-<slug>.md`) or a Plan-mode
  plan (`~/.claude/plans/<slug>.md` or `~/.opencode/plan/<slug>.md`).
  Module: the second argument.
  If either is omitted, ask which plan and which module — never guess.
- If the command is unknown in this session (no `/frood-gauntlet` resolves), stop and ask
  the user — do not improvise a workflow under its name.

## Preconditions (refuse if unmet)

- On an isolated branch for this unit of work (worktree where the repo uses them).
- The worktree is FRESH: after `git fetch origin <base>`, `git merge-base --is-ancestor origin/<base> HEAD`
  succeeds (a repo's create-worktree script may branch from a stale local ref — check, don't trust).
  Quote the base sha. Reads for planning/review come from this worktree or `origin/<base>`, never a
  shared checkout.
- The repo's boundary gates green BEFORE touching guarded paths.
- No uncommitted work in the files you will touch. Another session's work: stop and
  tell the user, do not edit around it.

## Worktree discipline

- `cd` does not hold between calls. Verify the tree once per edit sequence with
  `git rev-parse --show-toplevel`, then use that absolute path (or `git -C <tree>`)
  for every command. A wrong workdir writes into the wrong tree — check before
  editing, and if an edit lands outside the worktree, revert it there first.

## Shell discipline (Windows)

- pwsh has no `head`/`tail`, and a pipe returns the last command's exit status, so
  piping through `tail` both breaks and masks failures. Never pipe through them:
  use `Select-Object -First/-Last`, or run shell work in Git Bash where `.sh` scripts live.
- Quote gate output, don't summarize counts from memory.

## Per-module loop

1. Build on the existing stack (reuse, do not greenfield).
2. Focused tests for the module, in the repo's own runner (pytest / vitest /
   `npm test` — detect, don't assume).
3. Live smoke (two windows/sessions where stateful) + soak per the plan's pass bars.
4. Reconnect/kill: restores state, no duplicates.
5. Adversarial: injection via user inputs; privileged actions refused at the enforcement
   layer, not just the UI; tenant/customer data scoped correctly.
6. Failure analysis -> refine -> re-run until the pass bars hold.

Stop the module only when its gates pass. No fantasy concurrency or latency targets;
fit the plan's pass bars to the actual infra.

## Multi-repo tasks

One worktree and one receipt per repo. Per-repo gates, per-repo deploy truth. Land each
repo in its own commit(s); never mix trees in one commit. A merge is not a deploy in
any of them.

## Close-out (every run)

- Stage files by name, commit. Never blanket-add (`add -A` / `.` / `commit -a`).
- Re-run the repo's gates and quote the result.
- Write the receipt `[Module] -> [Tests run] -> [Failures / fixes] -> [Metrics]` and the deploy truth (verified
  deployed sha, or the stated gap) to the plan file or report, not to chat.
- Board the branch (`board ready` → train `board`), then start the departure
  DETACHED (`depart-bg` where the repo offers it — it survives session death
  and the conductor restarts a dead departure).
- **Train-and-build: never wait on the train.** The moment the departure is
  detached, this run's shipping work is done — the train's log and the board
  ticket answer everything on return. Do NOT poll `train.sh status`, do NOT
  sleep-loop waiting for prod to move, do NOT hold the session open "until it
  lands". Instead, immediately continue to the next buildable work: the next
  module's ticket/mandate/worktree, the next backlog item, or the next owner
  question. The shipped verification (prod sha readback, `board shipped`) is
  deferred work, done at the NEXT session start (or on a desk/peer-mail event),
  never by waiting in this one. A session that boards + departs and then idles
  on the train has stalled — the rule above is what restarts it.
- End the message with the handoff card (`/frood-orchestrator`, "At every module boundary"): status first, then `You:`
  and `Next:`. Put an unverified deploy under `You:`. Nothing goes after the card.
- Token hygiene: clear before the next module; orchestrator on the strong model,
  workers on the routed cheap agents (`rules/01-orchestrator-models.md`); noisy
  investigation to subagents with isolated context.

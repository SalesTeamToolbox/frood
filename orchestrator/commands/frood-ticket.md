---
description: Open a ticket for another session to pick up — Mandate, board ticket, plan file and stream, in one go
argument-hint: "<repo-path> <one-line task>"
---

Open work for a session that does not exist yet. The point is that the next session can find it: a ticket alone
is invisible to `/frood-next`, so this command always writes the **stream** too.

This run's arguments: $ARGUMENTS

## 1. Name it

- `<repo-path>` (first argument): the repository the work happens in. It must exist and be the repo root; if it
  is missing, ask for it — never guess between sibling checkouts.
- `<one-line task>` (the rest): what the ticket is for, in the words the owner used.
- Pick a **stream name** and a **ticket id**: the same slug is fine. Both match `^[a-z0-9][a-z0-9-]{0,39}$`
  (lowercase, dashes, ≤40 chars, e.g. `video-studio-m4`). Say the name in your next message so the owner can
  type it back.

## 2. Write the Mandate

Write `<repo>/.opencode/reports/<id>/mandate.md` — the same shape `/frood-orchestrator` uses:

- **Why** — the problem, in the owner's words, plus the evidence you have (file:line, a failing command).
- **Scope** — the files the worker may touch, and the files it may not.
- **Blast radius** — one bullet per function/route/key/format the ticket changes: its callers
  (`git grep`, or a `scout`) and the expected behaviour at each afterwards ("unchanged", or exactly what
  changes). At least one bullet is required — `board.mjs create` refuses without it. A bullet whose
  expectation is not "unchanged" must carry a `; test: <path>` — `create` refuses it at ticket creation,
  not after critic rounds and gates.
- **Atlas refs consulted / updated?** — what the repo map said about these entry points and which map lines the
  diff must update. Write `no map` plainly when the repo has none; silence is refused.
- **Pass bars** — the exact gate commands and the expected output, plus the tests the diff must add or keep green.
- **Gates** — the repo's `.opencode/board/adapter.json` gate list, and whether EGM or senior review is triggered.
- **Process safety** (copy into every Mandate verbatim) — every child process a test or tool starts has a
  timeout (`spawnSync(…, { timeout })`, `timeout <s>` around each test run), and no test leaves a process behind.
  Never `pkill`, `killall` or `kill $(pgrep -f …)`: a name pattern also matches oc-worker and the worker's own
  shell (2026-11-24: a worker's `pkill -f fake-opencode` killed its own run). Kill one pid read from `ps`, and only
  a process this run started.

## 3. Put it on the board

From `<repo>`, run:

```
node {{ORCH_REPO}}/bin/board.mjs create <id> --mandate <repo>/.opencode/reports/<id>/mandate.md --scope <files,…>
```

- **If it fails, show the error and stop.** A missing blast-radius bullet or Atlas line is the Mandate's fault:
  fix the file and re-run. Never hand-write a ticket JSON under `.opencode/board/tickets/` — the board never
  sees it, `claim`/`round`/`ready` cannot move it, and `/frood-next` cannot find it.
- If the repo has no `.opencode/board/adapter.json`, `create` exits 2 by design. Say so and stop: the board is a
  per-repo decision (`.opencode/board/adapter.json` is committed by whoever owns that repo), not something this
  command invents. The plan file and the stream below can still be written if the owner wants the work queued
  without a board.

## 4. Write the plan file

Write `<repo>/.claude/plans/plan-<id>.md` (or `.opencode/plans/plan-<id>.md` if that is where the repo keeps
plans) with a `## Handoff` section at the top — done (with shas, if any), next, waiting:

```
## Handoff

- Done:      nothing yet — the ticket has not been claimed.
- Next:      <repo>: <first step — the one thing the next session does first>
- Waiting:   <owner items, or "nothing">
```

The rest of the plan holds the backlog in build order, the hard constraints, the per-module pass bars and the
repo's gates — the same file `/frood-gauntlet` reads.

## 5. Register the stream

```
node {{ORCH_REPO}}/bin/handoff.mjs write --stream <name> --plan <repo>/.claude/plans/plan-<id>.md \
  --repo <repo> --next "<repo>: <first step>"
```

That pointer is what makes the ticket findable after `/clear`, from either harness. If it exits 3 (the other
harness holds that name) pick another name — say which — and write again.

## 6. Hand it over in one line

<!-- cc-only -->
Offer to start the work now, nested under this session: call `start_session` with `initiation: "offer"` and
`title: "<Ticket>: <plain outcome>"` (under 60 chars) alone. If the owner picks **New session**, send the brief with
the returned `proposal_id`: `context: "fresh"`, `name: <slug ≤24 chars, [a-z0-9-]>`, `prompt: /frood-next <name>`
and `background` (≥80 chars: goal, plan path, what is on disk, and "report to the parent session; anything for the
owner goes in your report as NEEDS OWNER" — this session then relays those items to the owner and answers back with
`SendMessage`). Once `start_session` succeeds, record the child on the stream so `/frood-learn <stream>` can collect
and review it: `node {{ORCH_REPO}}/bin/handoff.mjs child --stream <name> --session <returned session id> --harness claude-code --role nested`.
If the owner picks **Do it here**, run `/frood-next <name>`'s
steps in this session. Otherwise end with: `Run /frood-next <name> in a fresh session in <repo>.` Nothing else is
needed from the owner: the Mandate, the board ticket, the plan and the stream are all on disk.
<!-- /cc-only -->
<!-- oc-only -->
End with: `Run /frood-next <name> in a fresh session in <repo>.` Nothing else is needed from the owner: the
Mandate, the board ticket, the plan and the stream are all on disk. Do not start the work in this session.
<!-- /oc-only -->

# Plan: dispatch-preflight

## Handoff

- Done:      2026-11-25 — SHIPPED bb6e9139 (ff onto main e59cacfd, local, not pushed). 3 worker rounds (r1 killed by an
             outside SIGTERM, cause unknown; r2 → critic CHANGES_REQUESTED: vacuous --report tests, relative --report can't
             work; r3 → critic APPROVED). Gates make check green; board shipped; install.mjs run, --check OK. Installed
             peer-mail-session-id.js answers UserPromptSubmit (smoke-tested). Worktree removed.
- Next:      parent adds the UserPromptSubmit settings.json entry (now safe). Follow-ups (not done): vendored
             repo-root bin/oc-worker.mjs + bin/board.mjs still have the old behaviour; README hook row says SessionStart only;
             desk escalated critic-spawn-failed for a critic that ran, and does not follow hand-driven rounds.
- Waiting:   nothing in this stream.

## Backlog (build order)

1. oc-worker: `--stream` without `dirname(--out)/ticket.json` → exit 2 before spawning; give existing `--stream` test fixtures a ticket.json.
2. oc-worker: resolve relative `--out` / `--report` against the caller's cwd before the child gets `--dir` as cwd.
3. board create: refuse a blast-radius bullet whose expect is not "unchanged" and has no `test:` path (keep `ready`'s check).
4. Claude Code UserPromptSubmit hook: one-line notice of unread peer-mail (read-only DB, silent on failure). Evidence: the
   20:46:14Z desk escalation to session 647c9014… is still `unread` in mailbox.db; the session never saw it.
5. Docs: frood-orchestrator.md / frood-ticket.md lines for the new refusals; one ATLAS.md line.

## Hard constraints

- `orchestrator/bin/install.mjs` is guarded + EGM: do not touch it; if item 4 needs it, stop and report.
- Never loosen tests to pass: fixtures get a ticket.json instead.
- Machine runs agents at BelowNormal; one heavy suite at a time. Link `~/projects/frood/.venv` into the worktree before `board gates`.

## Pass bars / gates

- `(cd orchestrator && node --test tests/)` 0 failures; new tests per Mandate.
- `make check` green via `board.mjs gates`. No EGM/senior unless install.mjs is touched.

# Plan — orphan-notice-holder

## Handoff

- Done:      2026-11-25 — ticket claimed (owner 4b4b5452), `worktree/orphan-notice-holder` cut from origin/main `48caa7b9` at `.claude/worktrees/orphan-notice-holder`, EGM waived, worker r1 dispatched with `--stream` (worker-nvidia). Run dir `.opencode/reports/orphan-notice-holder/`.
- Next:      the desk daemon runs the critic loop and the merge, then peer-mails the holder session. After merge: `node orchestrator/bin/install.mjs` from the Frood root; restart the desk daemon if it caches modules.
- Waiting:   nothing

## Backlog (build order)

1. **M1 — orphan-notice-holder** (one module). Changes, all detailed in the Mandate:
   - `orphan.mjs`: add `holderSession` (see "What it does" 1);
   - `streamOrphaned`: add the `waiting` and `holder` fields;
   - `openEscalations`: drop escalations whose ticket is closed or shipped;
   - `orphan-notice.mjs`: change the text, the button label and the resume launch plan.

## Hard constraints

- `desk.mjs` stays untouched. It consumes `streamOrphaned` and `openEscalations` and must keep working without any
  change.
- Nothing writes to `escalations.jsonl` or the ack files. Resolving a closed ticket's escalations is a read-side
  filter only.
- The page still fires for an idle holder session. Only the wording and the action change. The owner still needs
  to hear that a stream is waiting.
- Tests never call the real `notify-send`, `xdg-open` or `claude`: stub them through PATH, and give every spawn a
  timeout.

## Pass bars

- `timeout 900 make check` exits 0.
- The new and extended tests listed in the Mandate's "Pass bars" pass.

## Gates

- Adapter gates: `make check`.
- No EGM review and no senior review: no path in scope matches `egm_paths` or `guarded_paths`.

## After merge

- Run `node orchestrator/bin/install.mjs` from the Frood root so the daemon picks up the new `orphan-notice.mjs`.
  Restart the desk daemon if it caches modules.

# Plan — handoff-write-keeps-claim

## Handoff

- Done:      M1 READY on the board 2026-11-25 03:56Z. Branch `worktree/handoff-write-keeps-claim` @ dbc08100
  (5483f480 fix + dbc08100 r4 doc/test fixes), base 48caa7b9. Paid Sonnet critic: r4 CHANGES_REQUESTED (module-boundary
  write lacked --release), r5 APPROVED (findings-r5-sonnet.md). Gate `make check`: 2156 passed, ruff clean. Handoff
  node tests 63/63.
- Desk note: desk escalated `senior` only because round > 2. Its verdict gate misread the critic phrase
  "not UNREQUESTED" as an UNREQUESTED tag on r1/r2 (free critic-nvidia; all paid OC critics out of quota). Senior is
  not warranted (Mandate: no senior; no guarded paths). That desk escalation is still unresolved
  (`desk.mjs step handoff-write-keeps-claim verdict:handoff-write-keeps-claim/findings-r3 --by cc`).
- Next:      merge (ff) dbc08100 into main + run the installer for the two command docs (merger's job), then
  `board verify`/train, `board close`.
- Waiting:   owner/parent decision on the merge.

## Why
`handoff.mjs write` clears the session claim even when the live holder writes a progress note. The stream then
reads pending and unclaimed, and the desk and `/frood-next` start a duplicate session. Seen on parallel-dispatch
on 2026-11-25.

## Backlog (build order)
1. M1 handoff-write-keeps-claim: `writeStream` keeps the claim for a holder's write; add `--release`; tests; docs;
   atlas entry.

## Hard constraints
- Don't touch `orchestrator/bin/install.mjs` (guarded).
- Tests use a temp `ORCH_HOME`. Never touch the real streams dir.
- The suite lock and the train stay serial.

## Pass bars / gates
See the Mandate. Gate: `make check` plus the handoff node tests. No EGM, no senior.

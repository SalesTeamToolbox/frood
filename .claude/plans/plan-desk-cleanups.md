# Plan: desk-cleanups

## Handoff

- Done:      all 4 backlog items, merged to main as 2f8dad53 (Sonnet critic APPROVED r1, owner sign-off, ff after a patch-identical rebase). Daemon restarted.
- Next:      nothing in this plan. Optional: worker-free never wrote report.md; the 'gone' prune case in orphan.test.mjs passes on old code too.
- Waiting:   board ticket desk-cleanups is still `working` — `make check` gate fails on the missing Playwright chromium (test_navigate_no_url), unrelated to this diff.

## Backlog (build order)

1. desk-daemon.test.mjs: remove byte-identical duplicate test blocks; rename same-named tests that differ. List what was removed.
2. launch-config.test.mjs:157 pty EOF test: skip when python3 is not on PATH.
3. desk.mjs orphan ledger: prune `orphan:<stream>:*` entries for deleted, done or parked streams and for superseded held_at; tests in orchestrator/tests/orphan.test.mjs.
4. Update the "Orphaned streams" section of orchestrator/docs/designs/desk-daemon.md for the new prune rules.

## Hard constraints

- Mandate: `.opencode/reports/desk-cleanups/mandate.md`.
- desk.mjs: touch only the ledger functions (orphanPage / pruneOrphanLedger / sweepOrphans), never status output.
- The daemon runs from the systemd unit `orchestrator-desk-daemon`; after merge, `systemctl --user restart orchestrator-desk-daemon`.

## Pass bars / gates

- No duplicate test names; pty test skips without python3; new ledger tests green; full orchestrator suite 0 failures except the ocw-orphan-test case; `make check` green.
- Board gates: `make check`. No EGM, no senior.

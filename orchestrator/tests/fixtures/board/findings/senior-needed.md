VERDICT: APPROVED
TESTS: `npm test` -> all board tests pass.
BLAST RADIUS:
- `bin/board.mjs` (spawned by `tests/board.test.mjs`) - intended: this ticket is the board's Phase 2.
- `bin/verdict-gate.mjs` `gate()` and `bin/pool-health.mjs` `agentModel()` - unchanged: imported, not modified.
SENIOR_REVIEW: needed - the diff reaches the ticket's sign-off path.
1. [minor] none.
(critic: fixture receipt, paid model)

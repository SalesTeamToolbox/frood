# Plan: orchestrator-followups

## Handoff

- Done:      M1 worker-kill-stops-agent SHIPPED 2026-11-25 (ff main to 403764f0).
             - Critic minors left open (fold into M4): the provider slot is unguarded while waiting for the machine
               slot (oc-worker.mjs:1098); a signal during post-processing marks a clean run "killed" (:1352);
               startHungStream duplicates startHung (oc-worker.test.mjs:1896).
             M2 test-orphans SHIPPED 2026-11-25 23:17Z. Merge ec3186d3 (reviewed sha 88538fa5).
             - fake-opencode exits 124 after FAKE_OC_MAX_MS (default 5 min).
             - tests/fixtures/fixture-guard.mjs tags children with FAKE_OC_SUITE; an after() reaps survivors and
               fails the suite. Wired into oc-worker, slots and pool-health tests.
             - The 5 strays were killed by pid at 22:04Z.
             - r1 worker-nvidia hit a 429, and r2 found no pool. r3 resumed the same session and finished it.
             - The critic APPROVED with no findings. make check passed (2192), install --check is OK, board
               shipped, and wt-finish ran.
             - The desk escalated `senior` on a misfire (see M4). Senior was skipped: a test-only diff, no guarded
               paths, and 0 counted rounds on the board.
             - npm test has 4 failures outside M2's scope: desk.test.mjs x3 and oc-worker-active.test.mjs
               "elapsed 26m". The worker and the critic call them load/timing flakes. Nobody checked them against
               base. Fold into M4 if they recur.
             M4 split 2026-11-26 01:12Z. worker-liveness (another stream) is editing oc-worker.mjs and
             oc-worker.test.mjs now, so M4 = ticket `desk-senior-rounds` (desk.mjs, desk.test.mjs, statusline prose):
             senior and rounds-exhausted from board counted rounds, criticRound per-lap floor, the WORKER_SLOTS test fix.
             worker-r1 launched (--role worker, --stream). Base check on main 9e5170b1: desk.test.mjs x3 fail
             DETERMINISTICALLY, not load: the tests assume WORKER_SLOTS=3 in the caller's env; without it slots are
             dynamic. oc-worker-active passed in isolation (load flake). Both in M4's Mandate.
             M4b (after worker-liveness merges): the M1 critic minors in oc-worker.mjs (:1098 provider slot, :1352
             killed-after-clean) + startHungStream dup, and the stale-tree-preflight nits (exit-10 tests for --role
             worker / worker-nvidia, failed-fetch test, `origin/-…` guard).
             M4 status 02:29Z: branch worktree/desk-senior-rounds @ 39129329 (one commit on 9e5170b1). Rounds:
             r1 CR (atlas+README doc lines), r2 CR (r2 fixed the atlas page but left it uncommitted), r3 critic
             APPROVED with no findings (desk 80/80 with WORKER_SLOTS unset, full npm 816/1 known flake, make check
             2192). BUT verdict-gate.mjs:43 flipped it to CHANGES_REQUESTED: `/\bUNREQUESTED\b/` matched the
             critic's own "no UNREQUESTED callers" blast line -> desk ESCALATE rounds-exhausted (acked).
             Board has 0 rounds recorded for this ticket. Not merged. Decision needed (parent/owner):
             (a) fix verdict-gate negation first (small ticket; UNREQUESTED only as the entry's tag, e.g.
             `— UNREQUESTED:`), then re-run `desk.mjs verdict` on findings-r3 and merge; or (b) orchestrator override.
- Next:      M4 desk-senior-rounds merge per that decision; then M4b, or M3 once the owner decides.
- Waiting:   M3 needs an owner decision (see M3).

## Pools (2026-11-25 evening)
- CommandCode is removed from the harness for good.
- opencode-go is over quota until 2026-11-26 21:00Z.
- The opencode free pool is out until about 2026-11-26 00:04Z.
- Nvidia is up. The adaptive cap is now live (merge 6f478d2b): up to 3 runs, 1 during a 429 cooldown.

Route workers through `--role worker`: Nvidia comes first, and models absent from `opencode models` are skipped
now. Use the Claude Code `worker` only with the owner's OK. The critic is the paid Claude Code Sonnet `critic`
while Go is out.

## Backlog (build order)
1. **M1 worker-kill-stops-agent.** A SIGTERM, SIGINT or SIGHUP to oc-worker must kill its agent tree, release its
   slots, and write the receipt and run-done. The Mandate is
   `.opencode/reports/worker-kill-stops-agent/mandate.md` (board ticket `worker-kill-stops-agent`).
   Why: on 2026-11-25 a killed wrapper left its opencode agent writing to the main checkout.
2. **M2 test-orphans.** Some orchestrator test leaves `fake-opencode.mjs run` children alive. Five of them from the
   deleted `worker-done-detection` worktree have been alive for hours.
   - Find which test leaks them, e.g. run each test file and diff `ps` before and after.
   - Fix it so every spawn has a timeout and is reaped.
   - Add a suite-level guard: an `after()` hook asserts no fixture child pid survives.
   - Kill the five strays by pid once they are confirmed to be fixture children.
3. **M3 root bin copy (owner decision).** `bin/desk.mjs` and `bin/router-health.mjs` at the repo root are the
   "sanitized generic copies" imported in 4e262982. `ops/install.mjs:49-50` still ships them, and they still name
   the removed CmdC agents. Options:
   - (a) regenerate them from orchestrator/bin;
   - (b) stop shipping and delete them.

   `ops/**` is a guarded path, so this needs the owner's choice plus a senior review.
4. **M4 small review follow-ups** (one ticket):
   - The board round floor in desk.mjs criticRound (`rounds.length + 1`) ignores reopen laps, so a reopened
     ticket can page `rounds-exhausted` early. Use the per-lap count that board.mjs:994-996 uses.
   - Stale CommandCode prose at orchestrator/hooks/cross-harness-statusline.js:1182.
   - desk.mjs:1133 `verdictRound > 2` takes the round from the findings file name. Worker attempts that never
     reached review (a 429, no-pool) still raise it. On test-orphans, a first clean critic APPROVED at
     findings-r3 escalated `senior` while the board had 0 counted rounds. Use the board's counted rounds instead.
   - M3 (stale-tree-preflight) critic nits:
     - exit-10 tests for `--role worker` and `worker-nvidia`;
     - a failed-fetch test;
     - the `origin/-…` option guard.
5. **M5 old escalations.** About 12 desk escalations from before c20f58b2 (dispatch-preflight critic-spawn-failed
   and similar) are still open.
   - List them with `desk.mjs status`.
   - Resolve the ones whose ticket has since shipped or closed.
   - Report any that are still live to the owner.

## Hard constraints
- Run only one heavy suite at a time on this laptop (`make check`, full `npm test`).
- A waiter must never match its own command line: wait on a pid, or use `pgrep -f '[p]attern'`.
- Never edit a worktree while a worker's agent may be alive.
- Workers edit only their worktree. `worktree-fence`, in progress in another session, will enforce this.
- Mandates must end with `RESULT: DONE`.
- After a rebase the board wants a round on the new sha. A merge commit is fine when main moved only in disjoint
  files.

## Pass bars and gates
- Each module's Mandate lists its tests, which must fail before and pass after.
- `make check` in the worktree (link main's `.venv` first).
- After merge:
  - `node orchestrator/bin/install.mjs`, then `--check` must be OK;
  - restart `orchestrator-desk-daemon` when desk.mjs or oc-worker.mjs changed;
  - run board verify and shipped with the full reviewed sha, then `wt-finish`.

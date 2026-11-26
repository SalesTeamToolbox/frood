# Plan: desk daemon systemic errors

## Handoff
- Done (2026-11-25): finding 10 shipped as 6155a14f on main (ff merge; board `desk-round-count` shipped; worktree removed;
  desk daemon restarted). desk-bookkeeping (c5d8ec17, criticRound) had already fixed the core. This commit adds
  `ESCALATE rounds-exhausted` past max, a `slotJudged` advance (verdict recorded, file gone) and doCritic
  `critic-slot-taken`. Worker: Claude Code Sonnet (owner's call; Nvidia 429s, every OC pool out). Paid Sonnet critic
  APPROVED with 3 minor findings (`.opencode/reports/desk-round-count/findings-r1-sonnet.md`). make check: 2161 passed.
  Lessons:
  - worker-nvidia r3 edited the MAIN checkout by absolute path. Its leftovers were saved as
    `nvidia-r3-main-checkout.patch` and reverted. The fix, `worktree-fence`, is in another session.
  - Killing the oc-worker wrapper left its opencode agent alive (pid killed by hand), so M1's --standalone did not
    cover that path.
  - Nvidia 429 stalls: ticket/stream `nvidia-throttle`, run in a nested session.
  - `install --check` now fails with 42 problems: `opencode models` lists no commandcode/* models, which predates
    this ticket.
- Done (2026-11-24): M4 shipped. Finding 6 (timeout resume named its own out + an unwritten prompt) fixed in
  `4791c210` on main: the resume takes `worker-r<N+1>.md` and the Mandate as prompt; 4 tests (3 fail on the old
  code). Finding 7 (critic spawn without `--stream`) had already landed from another session in `c20f58b2`
  (it also streams the critic-alt retry to `findings-r<N>-alt.md`), so M4 dropped its own copy. Desk daemon
  restarted onto 4791c210 (systemd). Critic: Sonnet r1 APPROVED, senior not needed
  (`.opencode/reports/desk-spawn-fixes/findings-r1.md`). Orchestrator suite: 523/525 pass, 1 known flake
  (`active CLI prints text rows`, passes alone).
- Lessons from M4: the worker-nvidia wrapper timed out at 30 min while its agent lived on in `opencode serve`,
  stashed the tree to prove fail-before, then committed — a second writer in the worktree. worker-done-detection
  (8b1ac82f) now counts a timed-out run whose work landed as done; watch for it in M1.
- Done (2026-11-25): Discuss for findings 1-5 (results in "### Discuss results" below), plus a new finding 9.
  Backlog rewritten: M1 timed-out agent keeps writing, M2 critic chain from CHAINS, M3 stale-tree preflight.
  Dropped: CmdC credit headroom warning, Nvidia rate-limit work, a video-studio stream (fixed there already).
- Done (2026-11-25): M1 shipped. `oc-worker` runs `opencode run --standalone`, so a killed run (timeout/stall)
  ends its agent instead of leaving it writing via the shared service (66c8b100 + d87c36a5, ff on main; board
  `killed-run-stops-agent` shipped; install --check OK; worktree removed). worker-r1 worker-nvidia live-checked
  standalone + `--session` resume (3.8 s / 22.5 s) and a SIGKILL mid-generation (server gone in 3 s). The desk's
  critic ran on critic-free (CmdC + Go down; the hand-typed chain put free before Nvidia = M2 in action) and paged
  owner-signoff; replaced by a paid Claude Code Sonnet critic: APPROVED, 4 minor (comments fixed in d87c36a5),
  senior not needed (`.opencode/reports/killed-run-stops-agent/findings-r1-sonnet.md`). Gates: make check exit 0
  at d87c36a5; oc-worker tests 68/68; worker's full orchestrator suite 531/533 (known `active CLI` flake only).
- Done (2026-11-25): M2 shipped 7c744c42 (ff on main; board `critic-chain-from-chains` shipped; install
  --check OK; worktree removed; desk daemon restarted onto it). doCritic spawns `--role critic`; the critic-failed
  retry runs CHAINS.critic minus the failed agent; check-routing lints hand-typed critic chains; frood-desk.md and
  frood-orchestrator.md print `--role critic`. Paid Sonnet critic APPROVED (2 minor, no change), senior not needed
  (`.opencode/reports/critic-chain-from-chains/findings-r1-sonnet.md`). Targeted tests 94/94; worker full suite
  533/535 (known flake); make check exit 0 at 7c744c42.
- Lesson (M2): my Mandate asked for `RESULT: READY`; the desk and board read only `RESULT: DONE` (outcome.mjs), so
  the desk resumed the worker twice (r2, r3: no changes) and then escalated worker-error. Fixed with a non-stream
  resume (worker-r4) that restated `RESULT: DONE`. Mandates must say `RESULT: DONE`.
- Done (2026-11-25): M3 shipped 8e73159a (ff on main; board `stale-tree-preflight` shipped; worktree removed).
  A fresh `--stream` worker run refuses with exit 10, before `queued` and before any slot, when ticket.json's
  `base` is not an ancestor of HEAD or the tree is dirty (untracked symlinks/junctions ignored; git failure refuses).
  `--session` resumes and critics are not checked. Rounds: r1 critic-nvidia malformed (critic-invalid); paid Sonnet
  r1 CHANGES_REQUESTED (5 findings); worker-r2 fixed all five; Sonnet r2 APPROVED (3 minor/nit test-strength notes,
  left as follow-ups). Main moved meanwhile, so the branch was rebased (patch-identical, range-diff `=`), the board
  reopened, Sonnet confirmed the rebase (r3 APPROVED); 3 counted rounds triggered a senior pass (Opus, no blockers,
  `senior-r3.md`). Tests on 8e73159a: orchestrator 619/621 (known `active CLI` flake), oc-worker 83/83; make check
  exit 0. install ran; `install --check` FAILS on a pre-existing routing line (below), not on M3.
- Lesson (M3): the desk lost round 2 for 12 h (finding 10). After a critic-invalid / hand-recorded round, run the
  revision worker without `--stream` (as M2's worker-r4) or expect to drive the critic by hand.
- Stream complete: M1-M3 shipped. Follow-ups (own streams): finding 10 (desk round count after a hand-launched
  round); `orchestrator/rules/01-orchestrator-models.md:86` names `nvidia/deepseek-ai/deepseek-v4.1-flash` (EOL
  2026-11-16, gone from `opencode models`), so check-routing and `install --check` fail; M3 critic nits (exit-10
  tests for --role worker / worker-nvidia, failed-fetch test, `origin/-…` option guard).
- Pools now: CmdC out of credits, opencode-go quota until 2026-11-26 21:00Z; Nvidia and free up.
- Side notes (not this stream): 5 stray `fake-opencode.mjs run` test-fixture processes from the deleted
  worker-done-detection worktree have been alive 1-2.5 h (an orchestrator test leaks children); 12 old desk
  escalations still pending (dispatch-preflight critic-spawn-failed etc., pre-c20f58b2).
- Waiting on owner: nothing (desk-spawn-fixes closed at 4791c210, 2026-11-25).

## 1. Discuss
Eight findings. Items 1-5 come from the desk-daemon log (15 escalations across video-studio-m4, atlas-wiring and
gsuite/s2-storage-recurrence); items 6-8 come from the desk-cleanups and board-close tickets (2026-11-24):
1. Worker pool exhaustion (CmdC credits) breaks the worker fallback chain.
2. Nvidia rate limiting: 16+ minute runs and 60 min timeouts.
3. Stale worktrees fail the Mandate FIRST STEP check (`git merge-base --is-ancestor`).
4. Critic chain gaps: critic-failed with no receipt; unlinked critic runs.
5. Video-studio battery scope bug: a re-run that exits before `phaseGates` boards on an old 0-FAIL block.
6. The resume of a timed-out free or Nvidia worker silently does nothing, and the ticket stalls with no page.
   Added 2026-11-24 from board-close. Its worker-r1 (worker-nvidia) timed out at 30 min at 23:58Z. The desk
   stored `ACTION resume-worker … --prompt <run dir>/worker-prompt-r1.md … --out <run dir>/worker-r1.md --session …`
   and nothing ran: no worker started, no page, nothing in daemon.log. The owner noticed 10 min later and resumed
   it by hand as worker-r1b. Three linked bugs in `orchestrator/bin/desk.mjs`:
   a. Off by one (:976-980). The loop advances while `nextOutTaken(runDir, nr)` (which checks
      `worker-r<nr+1>.md`), then names the resume out `worker-r<nr>.md`. For worker-r1 that is the timed-out
      run's own out file.
   b. A silent no-op. `doResume` (:1524) and the step's effect check (:905-912) look for `run:<out>:queued`,
      find the ORIGINAL run's queued event, and return `resume-inflight` / DONE. The resume is never spawned and
      never paged. Had it been spawned, `oc-worker --stream` would refuse a non-fresh `--out` with exit 2.
   c. A missing prompt (:980). The resume points `--prompt` at `worker-prompt-r<N>.md`, which nothing writes. Even
      with a fresh out, oc-worker would fail and the desk would page `resume-spawn-failed`. A resume needs a
      prompt that exists: a desk-written continuation prompt ("you timed out; finish, test, commit, report")
      or the Mandate.
   Fix: name the out `worker-r<nr+1>.md`, write the continuation prompt before spawning, and test the
   timeout -> resume path end to end (desk.test.mjs / desk-daemon.test.mjs). That test must fail on today's
   code (the resume names its own out).
7. **FIXED 2026-11-24 in the desk commit below (both critic spawns pass --stream; -alt retry hardened).**
   Every critic the daemon spawns reports `critic-spawn-failed`, and its verdict is never recorded. Added
   2026-11-24. `doCritic` (`orchestrator/bin/desk.mjs:1490`, since a19c2e87 on 2026-11-21) runs `oc-worker` with
   no `--stream`, so oc-worker writes neither the `queued` nor the `run-done` event to the stream. Then:
   - `awaitQueued` (:1505) waits 30 s for an event that never comes and pages `critic-spawn-failed … no queued
     event in 30s`, although the critic is running.
   - When the critic finishes, there is no event, so the desk never computes the verdict and never reaches
     merge, senior or owner sign-off. The ticket sits at `working` until a human runs `/frood-desk`.
   - Hits in the daemon journal over 2 days: desk-cleanups findings-r1, dispatch-preflight findings-r2,
     peer-mail-wake findings-r1. desk-cleanups needed an interactive desk, a re-run critic, and a by-hand
     `desk.mjs verdict` to land.
   - The critic chain also runs `critic-free` once the paid critics are out. Its verdict is APPROVED_FREE, which
     escalates to owner sign-off. That part works as designed but adds a round-trip to the owner.
   Fix: pass `--stream <stream>` in the doCritic spawn (doResume's command already carries it). Then add a test:
   a daemon-spawned critic produces `queued` and `run-done` events, and `step` on that run-done yields a
   verdict. This overlaps finding 4 ("critic-failed, no receipt" / unlinked critic runs); check whether it is
   the same root cause.

Item 5 lives in the video-studio repo, not here; confirm and move it to its own stream.

8. **FIXED 2026-11-24 in 6c557941 (KillMode=process in the daemon unit; applied live, no restart needed).**
   Restarting the desk daemon kills every run it spawned. Added 2026-11-24. `orchestrator-desk-daemon` runs with
   systemd `KillMode=control-group`, so the "detached" oc-worker critics and resumed workers stay in the daemon's
   cgroup. `systemctl --user restart orchestrator-desk-daemon` (which the desk's own after-merge steps and plan
   handoffs call for) SIGTERMs them all. At 00:50Z it killed board-close's round-2 critic (pid 1739894, 8 min in),
   with no run-done, no page, and the run shown as STALE in `oc-worker active`. Fix: spawn runs outside the unit's
   cgroup (`systemd-run --user --scope`, or `KillMode=process` in `orchestrator/ops/systemd`). Then add a test or
   check that a restart leaves a spawned run alive.

### Discuss results (2026-11-25)
Evidence: `~/.opencode/reports/s2-storage-recurrence/*.receipt.json` (the ticket's evidence dir), daemon.log,
`.opencode/reports/board-close/`, the opencode DB (`session_part`), and the code on main at 6c557941.
1. Pool exhaustion — CONFIRMED, already CLOSED. s2 worker-r2: worker-burst then worker-alt both "insufficient
   credits" (400) within 1 s, exit 1. Since then `cb4fb798` marks the whole provider down on "insufficient
   credits", and `20f0a092` gives one worker chain from CHAINS (`worker-nvidia, worker, worker-burst, worker-alt,
   worker-free`, `--role worker`). A credit-balance warning (old M3) has no balance source to read, and the first
   400 now downs the provider for the chain, so old M3 is dropped.
2. Nvidia rate limits — REFUTED. No 429 in any s2 receipt or event stream (the only "429" hits are line numbers
   in file dumps). The 60-min timeout was s2 worker-r1 on worker-burst (DeepSeek), not Nvidia. worker-r4's 990 s
   was a real 401K-input / 18.7M cache-read run that exited 0. pool-health already has a Nvidia 429 branch. The
   real Nvidia problem is finding 9.
3. Stale worktrees — CONFIRMED, OPEN. s2 worker-r3 (worker-nvidia, 74 s) stopped with `BLOCKED: stale tree`:
   origin/brain-backend 2 commits ahead of the worktree base, plus uncommitted work it did not author. The only
   check is the Mandate's FIRST STEP text (frood-orchestrator.md / frood-gauntlet.md). No code checks freshness
   before a worker is spawned, so a stale tree costs a whole worker run and an escalation. -> M3.
4. Critic chain gaps — PARTLY CLOSED. `c20f58b2` closed the unlinked/unrecorded daemon critic (queued + run-done,
   the verdict reaches the desk); s2 findings-r1 (no receipt, 11-20, before the daemon lived in frood) is not
   reproducible past it. Go Haiku is already in CHAINS.critic (position 2). `review-unlinked` on s2 findings-r2
   is correct behaviour (a hand-run critic-nvidia). "Nvidia critic is advisory-only" is false: providers.json has
   nvidia `routed`, so its APPROVED is paid and merges. Two gaps remain in `orchestrator/bin/desk.mjs`:
   a. `doCritic` (:1515) hand-types `--fallback critic-alt,critic-go,critic-free,critic-nvidia`, which disagrees
      with CHAINS.critic (`critic, critic-go, critic-alt, critic-nvidia, critic-free`): critic-free runs before
      critic-nvidia, so with CmdC and Go down a free model reviews and the ticket goes to owner sign-off while a
      paid-equivalent Nvidia critic is up.
   b. The critic-failed retry (:1471) runs `--agent critic-alt` alone (CmdC). With CmdC down it dies at once with
      `no-healthy-pool` — exactly s2 findings-r3 — and the desk pages critic-failed. -> M2.
5. Video-studio battery scope — CONFIRMED, already FIXED in video-studio `7128745` (M4 r6: `phaseGates` logs
   `phase gates: start`; seal.mjs `batteryScope` and run-team.mjs `scopedBattery` treat a started-unfinished
   battery as a refusal), on feat/m4-team (also in feat/m5-publish). Stream `video-studio-m4` is `done`, waiting
   on owner sign-off and merge. No new stream: a /frood-ticket would duplicate shipped work.
9. NEW — a timed-out worker's agent keeps writing. board-close worker-r1 (worker-nvidia) hit its 30-min timeout at
   23:58Z; its session `ses_df01ca0b…` wrote parts 00:02-00:21Z, before the owner's resume worker-r1b started at
   00:31Z. Cause: `opencode run` (2.4.1) attaches to the background service (`opencode serve --service`, running
   for 20 h) unless given `--standalone`/`--server`. `killTree` SIGKILLs the `opencode run` process group, which
   kills only the client; the session runs on in the service. Every timeout or stall leaves a second writer in the
   worktree, and the desk's resume (4791c210) starts a new run on the same session while the old one may be live.
10. NEW (2026-11-25, found on M3) — the desk loses a revision round it did not start, silently. stale-tree-preflight:
   critic-nvidia r1 was critic-invalid, the paid critic's CHANGES_REQUESTED was recorded by hand, and worker-r2 was
   launched by hand on the stream. Its run-done (04:33Z, outcome done) acked `ACTION critic … findings-r1.md 1`:
   `roundOf` (desk.mjs:870) is 1 + desk-issued `resume-worker` acks only, so it ignores the run's own name
   (`worker-r2`). doCritic then found `run:stale-tree-preflight/findings-r1:done` and returned `critic-inflight`
   (desk.mjs:1512) — no critic, no page, 12 h stuck until the parent noticed. Fix candidates: derive the round from
   max(roundOf, the `worker-r<N>` in the run id); and when the findings run is already done, page
   (`critic-stale-round`) instead of returning silently. Not built here; a follow-up stream.

## 2. Backlog (build order)
- M1 — finding 9: a killed run must stop its agent. In `orchestrator/bin/oc-worker.mjs`, either run opencode with
  `--standalone` (the existing process-group kill then ends the session) or, on timeout/stall, abort the session in
  the service and confirm it went quiet before writing run-done. The worker checks which works with `--session`
  resume and the shared DB, and picks one. Test with `tests/fixtures/fake-opencode.mjs`: the spawned CLI carries the
  chosen flag / the abort is called on timeout; must fail on today's code.
- M2 — finding 4a/4b: `doCritic` and the critic-failed retry spawn `--role critic` (CHAINS order) instead of
  hand-typed agents; the retry keeps its `findings-r<N>-alt.md` out and is still tried once. Tests in
  `tests/desk-daemon.test.mjs` assert the spawned argv.
- M3 — finding 3: refuse a stale tree before spawning. When oc-worker runs a fresh (non-`--session`) worker with
  `--stream` and `dirname(--out)/ticket.json` names a `base`, check `git merge-base --is-ancestor <base> HEAD` and
  a clean tree in `--dir`; on failure exit with a new code before taking a slot, write a receipt saying why, and
  let the desk page `worker-stale-tree` with the fix (rebase onto base / owner decides on foreign uncommitted work).
  Docs: the FIRST STEP lines in frood-orchestrator.md / frood-gauntlet.md say the wrapper now checks it.
- Dropped: old M3 (CmdC credit headroom warning; see finding 1), Nvidia rate-limit work (finding 2 refuted).
- Follow-up (not in this stream): finding 10, desk round count after a hand-launched revision round.

## 3. Hard constraints
- Source is `frood/orchestrator/` (the old `~/projects/orchestrator` repo is retired).
- `npm test` in `frood/orchestrator` has 4 known failures as of 2026-11-23 (pool-health classify x3, orphaned
  grandchild sweep); do not add to them.

## 4. Gates
- `(cd orchestrator && npm test)` — no new failures.
- `node orchestrator/bin/install.mjs --check` clean after install.

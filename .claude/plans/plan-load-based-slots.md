# Plan — load-based worker slots

## Handoff

- Done:      SHIPPED 2026-11-25. Merged to main as 6989d47f (feature 0765f9f1 + tests 5e76acc6); node suite
             604 pass / 0 fail, test_atlas 5 passed, install --check OK; worktree finished. Switched on:
             WORKER_SLOTS removed from ~/.claude/settings.json and the desk-daemon drop-in (daemon restarted),
             adapter max_parallel.build "auto" (c9507ad7). Live: `slots 2/6 (cpu wait 1.51%, load 2.59, 12 GiB free)`.
- Next:      — (owner: `board close load-based-slots`, human-only exit)
- Waiting:   nothing. Known gap: the desk paged merge-train instead of ff-merging (ticket repo vs desk REPO_ROOT).

## Goal

Replace the fixed worker cap (`WORKER_SLOTS`, `max_parallel.build`) with a load-based one: between a floor (2)
and a ceiling (6), new workers start only while the 5-minute CPU pressure, load and free memory say the box has
room. Running workers are never stopped. Workers start at nice 10 on Linux.

Mandate (full spec, blast radius, pass bars): `.opencode/reports/load-based-slots/mandate.md`.

## Evidence (2026-11-24 20:15)

3 live workers: CPU 91–96% idle, loadavg 0.53/0.83/1.00 on 8 threads, PSI cpu some avg300 0.59%,
~0.45 GiB PSS per worker, 13 GiB available, workers at NI 0 (no Linux priority guard).

## Backlog (build order)

1. **M1 — load-based-slots** (single ticket, one worker run): `slots.mjs` (readSample, slotConfig,
   allowedSlots, decision log), acquireSlot uses it, nice 10, `dispatch cap` "auto", queued-event + desk-status
   visibility, docs + ATLAS.

## Hard constraints

- No preemption: a lowered limit never touches a slot held by a live pid.
- Legacy `WORKER_SLOTS=N` / `--slots N` / integer or absent `max_parallel.build` keep their exact meaning;
  only `WORKER_SLOTS` unset (in oc-worker) and `max_parallel.build: "auto"` are dynamic.
- Burst guard: at most one admission above the floor per 60 s box-wide (5-minute signals lag).
- No `/proc` (Windows/macOS) or unreadable PSI → floor in dynamic mode, fixed cap in fixed mode; never crash.
- Tests never read the real `/proc` or write the real `~/.config/orchestrator` (`ORCH_PROC_ROOT`, `ORCH_HOME`).
- Guarded paths untouched (`orchestrator/bin/install.mjs`, `ops/**`, `orchestrator/ops/**`).

## Pass bars (M1)

See Mandate §Pass bars. Summary: allowedSlots unit tests (thresholds, null sample, hysteresis 59 s / 61 s,
invalid env); acquireSlot never exceeds allowed and never drops a live slot; legacy slot tests unchanged;
dispatch integer cap unchanged + "auto" test; desk stream rows byte-identical + header line; nice setter called
with 10 on non-win32.

## Gates

`timeout 600 node --test orchestrator/tests/`; `timeout 900 make check` (adapter gate);
`python -m pytest tests/test_atlas.py -q`. EGM required (new module, config format, CLI output change).
Senior not triggered unless the critic asks.

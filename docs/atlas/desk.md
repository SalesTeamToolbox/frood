# Atlas topic: orchestrator desk bookkeeping

Describes the desk's three bookkeeping fixes (ticket `desk-bookkeeping`), all in `orchestrator/bin/desk.mjs`:

## criticRound() — round floor for a re-dispatched worker run

Used by `decideStep`'s `run-done`/`done` branch and the verdict branch. The critic round is the max of:

- `roundOf(lines, slug)` — 1 + `ACTION resume-worker` acks for this ticket's slug.
- N from the worker run id `…worker-r<N>` (a worker-r2 is never reviewed in round 1).
- 1 + the highest N among `findings-r<N>.md` / `findings-r<N>-alt.md` already in the run dir.
- 1 + `rounds.length` of the board ticket `<ticket.repo>/.opencode/board/tickets/<slug>.json` when `ticket.repo` is set and the file parses (missing/unreadable contributes nothing, never throws).

The printed `ACTION critic … findings-r<N>.md <N>` path is never an existing file. Step stays pure: file reads only, no git, no spawn.

## latestVerdict() — newest of `verdict:<run>@<n>`

Returns the newest verdict event among `verdict:<run>` (counts as n=1), `verdict:<run>@2`, … Every reader that used `events.get/has(\`verdict:${run}\`)` now uses `latestVerdict`: `cmdMergeCheck`, `effectPresent`, the closed-ticket D2 check in `cmdStep`, the per-run status rows (`RUN_KEY_RE` maps `verdict:<run>@<n>` back to `<run>`), and `verdictFlow`'s noop check. `handoff.mjs` append/read semantics (first-write-wins per key) are unchanged.

## cmdVerdict — replacing an INVALID verdict

When a verdict for `<run>` already exists:
- latest is not INVALID → no write, prints `KEY <latest key>`, exit 0;
- latest is INVALID and `reviewed_sha` ≠ HEAD → no write, stderr names both shas, exit 2;
- latest is INVALID and same sha → append `verdict:<run>@<n>` carrying `replaces: "<previous key>"`, resolved-ack the replaced key, print `KEY verdict:<run>@<n>`, exit 0.

## cmdMergeCheck — patch-identical rebase acceptance

When HEAD ≠ `reviewed_sha`: accept iff `reviewed_sha` is still a commit, both diff ranges are non-empty, and `git diff <merge-base(base, reviewed_sha)> <reviewed_sha> | git patch-id --stable` equals the same for `<merge-base(base, HEAD)> HEAD`. Stdout is still exactly `OK` plus one stderr line `desk: HEAD <h8> is a rebase of reviewed <r8> (same patch-id)`. Otherwise `FAIL head-moved` exactly as before.

All git calls carry a timeout.

## What is NOT changed

`orchestrator/bin/handoff.mjs`, `orchestrator/bin/board.mjs` (board `ready`/`verify`/`shipped` keep their exact-sha rule), `orchestrator/bin/verdict-gate.mjs`, anything under `orchestrator/ops/**` or `ops/**`.

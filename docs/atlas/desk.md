# Atlas topic: orchestrator desk bookkeeping

Describes the desk's bookkeeping fixes (ticket `desk-bookkeeping`) and the worker scope fence (ticket
`scope-fence`), all in `orchestrator/bin/desk.mjs` unless named otherwise.

## criticRound() — round floor for a re-dispatched worker run

Used by `decideStep`'s `run-done`/`done` branch and the verdict branch. The critic round is the max of:

- `roundOf(lines, slug)` — 1 + `ACTION resume-worker` acks for this ticket's slug.
- N from the worker run id `…worker-r<N>` (a worker-r2 is never reviewed in round 1).
- 1 + the highest N among `findings-r<N>.md` / `findings-r<N>-alt.md` already in the run dir.
- `1 + board.lap` of the board ticket `<ticket.repo>/.opencode/board/tickets/<slug>.json` — `board.lap` is the counted rounds in this lap after the last `reopens[].after_round` floor (mirrors `board.mjs` ~:994-996); `board.counted` is the cumulative counted rounds across all laps and `board.has(sha)` names a counted round already recorded for a verdict. Read via the pure `boardRounds()` helper (desk.mjs); missing/unreadable contributes nothing, never throws.

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

## desk-bookkeeping: what is NOT changed

`orchestrator/bin/handoff.mjs`, `orchestrator/bin/board.mjs` (board `ready`/`verify`/`shipped` keep their exact-sha rule), `orchestrator/bin/verdict-gate.mjs`, anything under `orchestrator/ops/**` or `ops/**`.

## Scope fence — a worker's diff may not leave its ticket

Ticket `scope-fence`. On 2026-11-26 a worker's commit rewrote plan files belonging to other live streams, and one of
them had uncommitted edits in the main checkout, so the merge would have been refused. The board's `scope` was used
only to compute senior/EGM triggers; nothing compared the diff with it. Now `orchestrator/bin/scope-check.mjs`
exports `checkScope({ repo, base, sha, scope })`:

- it runs `git diff --no-renames --name-only <base>..<sha>` in `repo` (`spawnSync`, 30 s timeout), so a **deleted**
  file is listed by its old path and a **renamed** file by both its old and new paths;
- a path is `denied` when it matches the hard deny list — `.claude/plans/**` and `.opencode/**` — even when `--scope`
  covers it; otherwise it is `outOfScope` when it does not match `--scope`;
- it returns `{ ok, outOfScope, denied, error, from }`, and `ok` is false when the diff cannot be computed (`error`
  says why);
- the diff uses `-z`, so a non-ASCII path is not quoted past the deny list;
- with `baseRef` (the adapter's `base`, passed by `board round`/`ready` and by the desk when it can read the repo's
  `adapter.json`), it diffs from M = `merge-base(baseRef, sha)` when the ticket base is an ancestor of M (a branch
  rebased onto a newer main), and otherwise from the ticket base (a base ref that lags it). `from` names the commit
  used. A missing or unresolvable base ref diffs from the ticket base.

`matchAny`/`matchGlob` live in `scope-check.mjs`; `board.mjs` imports them back for `seniorFor` and the EGM trigger.
There is exactly one glob matcher.

The four gates:

- **`board create`** — refuses a `--scope` entry on the deny list, and refuses a Mandate whose `## Scope` section
  grants an open-ended ("any doc", "any file", "as needed", "any other", "wherever") unless that sentence names exact
  paths and each of them is in `--scope`. A `## Scope` section runs to the next heading of the same or a higher level
  (sub-headings and bold labels stay inside it), and a negated phrase ("never edit any file outside X") is no grant. Refusal: `board: mandate scope is open-ended: "<sentence>"`.
- **`board round`** — before recording a done round it fences `base_sha..--reviewed-sha`. When the fence fails the
  recorded critic is `effective: CHANGES_REQUESTED` with one `out of scope: <path>` / `denied path: <path>` reason per
  path; the round still counts, and a critic `APPROVED` cannot override it.
- **`board ready`** — refuses when the signed-off sha leaves the scope. This is the backstop for rounds recorded
  before the fence existed.
- **`doCritic`** — before writing the critic prompt it fences the worker's committed sha. On a failure it writes
  `findings-r<N>.md` with `VERDICT: CHANGES_REQUESTED` and one numbered finding per path (`out of scope: <path> —
  revert this file to <base>`), appends the `verdict:<run>` event so the existing CHANGES_REQUESTED path resumes the
  worker, and spawns no critic — no paid review of a diff that cannot merge. A dry run (`ORCH_DAEMON_DRY_RUN=1`) writes
  neither the findings nor the verdict. A diff that cannot be computed at all
  pages the owner instead of writing an empty findings file.

In-scope rounds, `verdict-gate.mjs`, `oc-worker.mjs` and `board verify`/`shipped` are unchanged.

## blast-line tag rule — verdict-gate.mjs

`orchestrator/bin/verdict-gate.mjs` classifies each BLAST RADIUS line by its first word (ticket
`gate-decorated-tags`). A bullet (`-`, `*`, `+`) is always collected as a blast-line entry; list
numbering (`1.`, `1)`, `(a)`, `a.`, `a)`) and a decoration run used as the bullet (checkbox,
emoji/symbol incl. bullet U+2022, emphasis/bracket openers) are collected only when the first
content word is a tag (`UNREQUESTED`/`unchanged`/`intended`). Numbered findings
(`1. [minor] ...`) and `1. none` / `1. No findings` / `1. (none)` placeholders are findings, not
blast lines. Before reading the first word it strips a leading decoration run, repeated in any
order with whitespace between: a bullet, list numbering, a checkbox, emoji/symbol characters, and
the emphasis/bracket openers (`*`, `_`, backtick, `[`, `(`).

- `UNREQUESTED` (any case) as the first word -> CHANGES_REQUESTED, whatever follows (fail safe).
- `unchanged`/`intended` as the first word, closed by emphasis/brackets then a separator
  (` — ` ` – ` ` -- ` ` - ` `:` `|`) or end of line -> does not count.
- any other line -> the transition (old format) separator walk plus the no-dash-separator fail safe.

The INVALID rule (no BLAST RADIUS entries) and the blocker/major parser are unchanged.

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
  `adapter.json`), let M = `merge-base(ref, sha)` for `ref = baseRef`, and — when `baseRef` is `<remote>/<branch>` and
  `refs/remotes/<baseRef>` resolves — also for `ref = <branch>` (the local counterpart). A candidate M is accepted
  only when the ticket base is an ancestor of M and M ≠ sha (an already-merged branch would diff empty and pass
  vacuously). The fence diffs from the newest accepted M (when both are accepted, the one the other is an ancestor
  of), else from the ticket base. `from` names the commit used. A missing or unresolvable base ref diffs from the
  ticket base.

`matchAny`/`matchGlob` live in `scope-check.mjs`; `board.mjs` imports them back for `seniorFor` and the EGM trigger.
There is exactly one glob matcher.

The four gates:

- **`board create`** — refuses a `--scope` entry on the deny list, and refuses a Mandate whose `## Scope` section
  grants an open-ended ("any doc", "any file", "as needed", "any other", "wherever") unless that sentence names exact
  paths and each of them is in `--scope`. A `## Scope` section runs to the next heading of the same or a higher level
  (sub-headings and bold labels stay inside it), and a negated phrase ("never edit any file outside X") is no grant. Refusal: `board: mandate scope is open-ended: "<sentence>"`.
- **`board round`** — before recording a done round it fences `<from>..--reviewed-sha` with `<from>` per the rule
  above. When the fence fails the recorded critic is `effective: CHANGES_REQUESTED` with one `out of scope: <path>` /
  `denied path: <path>` reason per path; the round still counts, and a critic `APPROVED` cannot override it.
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
`gate-decorated-tags`). A bullet (`-`, `*`, `+`) is always collected as a blast-line entry; a
leading skip run — a checkbox, any non-letter character, or a single-letter list marker
(`a.`/`a)`) — opens any other entry, collected only when the first content word is a tag
(`UNREQUESTED`/`unchanged`/`intended`). This catches decorated bullets (`• UNREQUESTED`,
`❌ UNREQUESTED`, `[x] UNREQUESTED`) and decorated numbered lines (`1. **UNREQUESTED**`,
`a) UNREQUESTED`). Numbered findings (`1. [minor] ...`) and `1. none` / `1. No findings` /
`1. (none)` placeholders are findings, not blast lines. Before reading the first word it strips a
leading skip run (checkbox, any non-letter character, single-letter marker), so decoration never
hides an UNREQUESTED tag and never turns a line into a false UNREQUESTED. The gate fails safe:
when in doubt about a decorated tag, it counts.

- `UNREQUESTED` (any case) as the first word -> CHANGES_REQUESTED, whatever follows (fail safe).
- `unchanged`/`intended` as the first word, closed by emphasis/brackets then a separator
  (` — ` ` – ` ` -- ` ` - ` `:` `|`) or end of line -> does not count.
- any other line -> the transition (old format) separator walk plus the no-dash-separator fail safe.

The INVALID rule (no BLAST RADIUS entries) and the blocker/major parser are unchanged.

## nested escalations — streams worked by nested sessions

Ticket `desk-nested-escalations`. On 2026-11-26 the desk paged the owner for work a nested child session
had already handled: the escalation stayed open because nothing resolved the desk ack.

- **`handoff.mjs claim --parent <id>`** records the nested session's parent on the pointer as
  `held_parent` (new `LEASE_KEYS` entry, defaults to null on old pointers). Validated like `--session`;
  `--parent` without `--session` exits 2. Lifecycle in `claimStream`: unheld and takeover branches store
  `parent ?? null`; the same-harness branch keeps the recorded parent on a same-session re-claim without
  `--parent` and drops it for a different session; `releaseStream` and `markDone` null it. `show` prints it.
- **`orphan.mjs resolvePeerSession(id)`** maps a stored parent id to a peer-mail id at use time (never
  stored mapped): a `local_<uuid>` host id resolves through `<home>/.claude/sessions/<pid>.json` files
  (non-`.json` siblings skipped; `hostSessionId === id`; live pid first, then newest
  `statusUpdatedAt`/`updated`); any other id passes through; an unmapped `local_…` id is null.
- **`orphan.mjs parentSession(stream)`** returns `{ id, idleMs, live }` for the resolved parent, or null
  with no `held_parent` or no resolution. `idleMs` follows the `holderSession` cc rules (session-file
  `status: idle` + `statusUpdatedAt`, else transcript mtime, plus peer-mail `peers.last_seen`, newest wins);
  `live` needs the parent found AND inside its window: a live pid in `~/.claude/sessions/` stays live while
  `idleMs <= wakeWindowMs()` (`PEER_WAKE_MAX_MIN`, default 1440, same var and default as the peer-mail wake hook),
  a parent with no live pid keeps the `orphanThresholdMs()` bound — a live pid alone still never suppresses the
  owner page forever.
- **`desk.mjs sendDeskMail(toSession, subject, body)`** (split out of `notifyHeldSession`) writes one
  peer-mail row, true only when written. `notifyHeldSession` mails the holder as today and, when
  `held_parent` resolves to a different id, the parent too (`desk: [nested <stream>]` subject, same body).
  Every desk mail body gains, after the `step` resolve line:
  `After you handle it: node <desk.mjs> resolve <stream> <key> --note "<what you did>"`.
- **`desk.mjs pageOrphanOrParent(stream)`** (from `dpage`'s orphan branch and `sweepOrphans`): when the
  stream is orphaned AND held AND its parent is live, the parent gets
  `desk: [nested <stream>] child session idle with N open escalation(s)` (open keys from
  `openEscalations`, each with its `desk.mjs resolve` command) once per claim (`parent:<stream>:<held_at>`
  ledger entry, written only after a successful send; a failed send falls through to `orphanPage`); dry
  run sends nothing, writes nothing, logs once per process. Every other case pages the owner as today, and
  `pruneOrphanLedger` prunes `parent:` entries by the same rules as `orphan:` entries.
- **`desk.mjs resolve <stream> <key> --note <text>`** (`cmdResolve`) closes one open escalation with one
  resolved `RESOLVED <note>` ack (ticket copied from the decision line when it has one): after it `step`
  prints `DONE`, `daemon status` drops it, `openEscalations` drops it, `streamOrphaned` stops counting it.
  Refuses with exit 2 (one stderr line) a missing stream, a missing/empty or newline `--note`, and a key
  with no escalation (no unresolved `ESCALATE` line and no `escalations.jsonl` row). Already resolved prints
  `DONE <key>`, exit 0, writes nothing. `--by` validated like `step`, no HELD refusal.
- **`cmdStep` decided branch**: a decided `ESCALATE` on a `run-done`/`run-dead`/`verdict` key whose ticket is
  closed (`closedTicket`: worktree gone) or whose board ticket is `closed`/`shipped` (`ticketResolved` on the
  stream's repo) appends `STALE ticket-closed` resolved and prints `DONE <key>` instead of replaying. Decided
  ESCALATEs on open tickets replay exactly as today; non-ESCALATE decided actions keep `effectPresent`.
- **`pendingEscalations()`** also drops rows whose board ticket is `closed`/`shipped`.

`streamOrphaned`'s result shape is unchanged; `step` stays pure (file reads only, no git, no spawn —
`ticketResolved` is a file read). `handoff.mjs` append/read semantics are unchanged.

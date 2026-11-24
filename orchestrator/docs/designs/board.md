# Design: the ticket board (`bin/board.mjs`) — v2.1

**Status:** v2 after EGM review (design_critic: REVISE, 3 blockers; implementation_readiness: NOT READY,
12 blockers) · **Date:** 2026-11-12 · **Plan:** `~/.claude/plans/the-last-few-days-reactive-tome.md` M3
**EGM gate:** required (new module, new persisted format). v1 review findings are answered inline as (Rn).

## Problem

The rules decided on 2026-11-12 — EGM gate, blast radius, max 3 review rounds, mechanical verdict gate,
free-only sign-off never ships, senior review when triggered — exist only as instructions. Two untested,
diverged bash boards in a consuming repo (`ops/{board,worker,router,watchdog}.sh`, ~3.7k lines, never run) do
not enforce them. Nothing binds an approval to the commit that ships.

## Scope (v2): the board RECORDS and VERIFIES evidence; it does not execute work

- **In:** ticket state, stage machine, locks, EGM decision, rounds (from `oc-worker` receipts + findings
  files, re-gated by the board), sign-off bound to the reviewed sha, gate results bound to a sha,
  `ready`/`verify`/`shipped` for the train, liveness sweep.
- **Out (stays with the repo or the orchestrator):** creating worktrees, `prepare`, junctions, removing
  worktrees, running the train, sending peer-mail, pool health. (Design critic #23.)
- **Size budget:** `bin/board.mjs` ≤ 700 lines; tests in `tests/board.test.mjs`. Overrun = scope signal.
- **Success metric:** zero tickets reach `ready` without a satisfied, sha-bound, non-free sign-off.

## Files

Create `bin/board.mjs` (imports only Node built-ins, `./verdict-gate.mjs`, `./pool-health.mjs`),
`tests/board.test.mjs`, `tests/fixtures/board/` (adapter, Mandates, findings files, receipts).
Modify `bin/oc-worker.mjs` (`--ticket`, resolved model in receipts — Phase 3), `bin/verdict-gate.mjs`
(header comment only), `commands/frood-orchestrator.md` (board is the path — Phase 3). Repo side (M5, not here):
`.gitignore` entries, `adapter.json`, train calls `board verify`/`board shipped`.

## Locations

Repo root = parent of `git rev-parse --git-common-dir` from the cwd, or `--repo <path>`; works from inside
any worktree. Board dir = `<root>/.opencode/board/`:

```
adapter.json        committed, per repo (required; missing → exit 2)
tickets/<id>.json   gitignored; one ticket per file
locks/<id>.lock/    gitignored; mkdir lock, contains owner.json
.board.lock/        gitignored; short global write lock, contains owner.json
.watch.json         gitignored; last sweep time (sleep detection)
```

## adapter.json (all keys required unless marked)

| Key | Type | Example (a consuming repo) | Meaning |
|---|---|---|---|
| `base` | string | `"origin/main"` | ref the ticket branches from |
| `branch_prefix` | string | `"feat/"` | branch = prefix + id |
| `gates` | array of argv arrays, ≥1 | `[["python","-m","pytest","tests/test_atlas.py","-q"]]` | run by `board gates`, cwd = worktree, no shell, 20 min cap each |
| `egm_paths` | array of globs | `["**/migrations/**","**/alembic/**","prisma/**","**/auth*","**/billing*","**/wallet*"]` | scope match ⇒ EGM required |
| `guarded_paths` | array of globs | `["**/auth*","**/billing*","ops/**"]` | scope match ⇒ senior required |
| `stale_minutes` | number, > oc-worker timeout | `45` | liveness threshold |

## Ticket schema v1 (files contain no comments)

| Field | Type | Rule |
|---|---|---|
| `schema` | 1 | required |
| `id` | string | `^[a-z0-9][a-z0-9-]{0,59}$`; used as file, lock, branch suffix |
| `title` | string | |
| `stage` | enum | `queued` `working` `ready` `shipped` `blocked` `failed` |
| `epoch` | int | +1 on every write; a write whose read epoch ≠ current is refused (exit 3) |
| `mandate_path` | string | absolute; file must exist at create |
| `scope` | string[] | paths/globs the worker may touch (from `create --scope`) |
| `blast_radius` | `{caller, expect, test?}`[] | parsed from the Mandate (below); ≥1 entry |
| `egm` | object | `{required: bool, triggers: string[], status: pending\|approved\|waived, reason, report_path, report_sha256, by, at}` |
| `worktree` | string\|null | absolute; set at claim |
| `base_sha` | string\|null | full 40-char sha of `adapter.base` at claim |
| `assignment` | object\|null | `{owner, harness: claude\|opencode, since, missed_sweeps: int, worker: {pid, started, out_path}\|null}` |
| `rounds` | object[] | see "Round object" in Precise rules |
| `senior` | object | `{required: bool, reasons: string[]}` recomputed every round |
| `signoffs` | object[] | `{by: critic\|senior\|human, model, free, free_source, reviewed_sha, at, invalidated_by: null\|round n}` |
| `gates` | object[] | `{argv, exit, sha, at, log_path}` from the latest `board gates` run |
| `blocked` | object\|null | `{reason: stale\|rounds_exhausted\|worker_question\|no_pool\|manual, note, at}` — a failed gate never changes stage |
| `history` | object[] | `{at, cmd, from, to, by, note}` on every write except heartbeat |
| `created`, `updated` | ISO-8601 UTC | future timestamps are treated as invalid |

**Blast radius parsing (create):** in the Mandate, a line matching `/^\s*\**blast radius\b/i`, then the
following `- ` bullets until the next non-bullet, non-blank line. Each bullet → `{caller, expect}` split on the
first ` — ` (no separator ⇒ `expect: "unchanged"`); an optional trailing `test: <path>` ⇒ `test`. Zero
bullets ⇒ refuse. (Readiness #17, critic #5.)

**Atlas line parsing (create):** the Mandate must carry an `Atlas refs consulted / updated?` line saying what
the repo map (`docs/ATLAS.md`, `docs/atlas/`, or the map the repo's `CLAUDE.md`/`AGENTS.md` names) said about
the entry points this ticket touches, and which map lines the diff must update. Written as a bold label with
the answer after it (`**Atlas refs consulted / updated?** no map in this repo`) or as a bullet; `no map` is a
valid answer, an empty value or a missing line ⇒ refuse. The parsed text is not stored on the ticket: the
Mandate stays the record, `create` only proves the question was answered. (atlas-m1.)

## Stage machine — any pair not listed is refused (exit 1, no write)

| Command | From → To | Guards |
|---|---|---|
| `create` | — → `queued` | valid id, Mandate exists with ≥1 blast-radius bullet and a non-empty `Atlas refs consulted / updated?` line, `--scope` given |
| `claim` | `queued` → `working` | `egm.status` ≠ pending; no live lock; `--owner`, `--harness`, `--worktree` (exists, is a git worktree of this repo) |
| `round` | `working` → `working` | owner; ≤3 counted rounds |
| `round` (4th counted) | `working` → `blocked` | records nothing, `blocked.reason: rounds_exhausted` |
| `round` (worker outcome `blocked_question`) | `working` → `blocked` | reason `worker_question` |
| `round` (worker outcome `no_pool`) | `working` → `blocked` | reason `no_pool` |
| `round` (uncounted outcome timeout/no_output/error, 1st or 2nd in a row) | `working` → `working` | appends `counted: false`; does not invalidate signoffs |
| `round` (3rd consecutive uncounted outcome) | `working` → `blocked` | reason `manual` |
| `signoff` | `working` → `working` | owner (or `--by human`); rules below |
| `gates` | `working` → `working` | owner; records results at HEAD |
| `ready` | `working` → `ready` | rules below; releases the lock |
| `verify` | (read-only) | exit 0 iff stage `ready` and `--sha` = signed-off sha |
| `shipped` | `ready` → `shipped` | `--sha` = signed-off sha (called by the train) |
| `watch` | `working` → `blocked` | liveness rules below |
| `unblock` | `blocked` → `queued` | `--by human --note` (≥10 chars); lock must be free |
| `egm reopen` | `working` → `queued` | owner; sets `egm.status: pending`, releases lock (mid-ticket trigger) |
| `release` | `working` → `queued` | owner; or `--force --note` (human) |
| `fail` | any non-terminal → `failed` | `--note`; terminal |

## Commands — inputs, rules, outputs

- **Exit codes:** 0 ok · 1 refused by a rule (stderr `board: <rule>`, no write) · 2 usage/schema/missing
  file · 3 lock contention or epoch conflict (retry). Success prints the updated ticket as one JSON line.
  `--help` prints usage, exit 0.
- **`create <id> --mandate <path> --scope <a,b,…> [--title] [--egm-trigger <name>]…`** — computes
  `egm.triggers`: each `--egm-trigger` (orchestrator-declared: `new-module`, `public-interface`,
  `security`), plus `data-model` if any scope path matches `egm_paths`, plus `many-modules` if scope spans
  > 3 top-level directories. `egm.required = triggers.length > 0`. (Critic #4.) Refuses a Mandate with no
  blast-radius bullet and one with no `Atlas refs consulted / updated?` line (atlas-m1).
- **`egm <id> approve --report <path> --by <who>`** — report must exist; stores absolute path + sha256.
  **`egm <id> waive --reason <text> --by <who>`** — refused if `egm.required`; reason trimmed ≥ 20 chars.
  Both refused unless `egm.status == pending`.
- **`claim <id> --owner <session> --harness claude|opencode --worktree <path>`** — global lock → ticket lock
  `mkdir locks/<id>.lock` (+ `owner.json {owner, harness, heartbeat}`) → write ticket (`worktree`,
  `base_sha` = `git rev-parse <base>`, assignment). Never runs git worktree add or prepare.
- **`heartbeat <id> --owner <s>`** — rewrites `locks/<id>.lock/owner.json` only (no ticket write, no history).
- **`attach <id> --pid <n> --out <path>`** — records the running `oc-worker` (pid, process start time,
  output path) in `assignment.worker`. Called by `oc-worker --ticket` (Phase 3).
- **`round <id> --owner <s> --worker-receipt <path> [--critic-receipt <path>] [--native-critic <alias>] --findings <path>`**
  - Receipts are the `<out>.receipt.json` files `oc-worker` writes (paths, never inline JSON).
  - Worker outcome from the receipt: `exit 0` + first line `RESULT: DONE` ⇒ `done`; `RESULT: BLOCKED: question` ⇒
    `blocked_question`; `exit "timeout"` ⇒ `timeout`; exit 3 ⇒ `no_output`; exit 6 / `no-healthy-pool` ⇒ `no_pool`;
    anything else ⇒ `error`. Only `done` rounds count toward the cap; `timeout`/`no_output`/`error` are recorded
    uncounted (the orchestrator may retry them, max 2 uncounted in a row, then `blocked: manual`).
  - Critic: the board runs `verdict-gate` on `--findings` itself — never trusts a receipt's gate. Free-ness:
    from the critic receipt, `free = gate(--free)` rule: agent name ends `-free` OR resolved model starts
    `opencode/` and ends `-free`; resolved model = receipt model, or the agent's pinned model
    (`pool-health.agentModel`) when the receipt says `(agent default)`; **unknown ⇒ free = true** (fail closed).
    `--native-critic sonnet|haiku|opus` (Claude Code subagent, no receipt) ⇒ `free = false`,
    `free_source: "native:<alias>"`. (Critic #2, readiness #4.)
  - Records `reviewed_sha` = `git -C <worktree> rev-parse HEAD`, both inputs' sha256, cost =
    `tree.total_cost ?? cost`, effective verdict. Appending a round sets `invalidated_by` on every prior
    signoff. (Critic #3.)
  - Recomputes `senior`: critic `SENIOR_REVIEW: needed`, or counted rounds > 2, or scope ∩ `guarded_paths`.
- **`signoff <id> --by critic|senior|human [--owner <s>] [--findings <path>]`** — requires ≥ 1 round.
  `critic`: latest round's effective verdict `APPROVED` or `APPROVED_FREE`; copies that round's
  `reviewed_sha`, `free`, `free_source`, model. `senior`: `--findings` (senior reply) must gate `APPROVED`;
  `free` derived from its receipt the same way. `human`: `free: false`, `reviewed_sha` = current HEAD.
- **`gates <id> --owner <s>`** — runs each adapter gate argv (cwd worktree, no shell, 20 min cap), output to
  `tickets/<id>.gate-<n>.log`; records `{argv, exit, sha: HEAD, at, log_path}`. Stops at first failure.
- **`ready <id> --owner <s>`** — refuses unless ALL: (1) worktree clean
  (`git status --porcelain --untracked-files=all` empty, ignoring a `node_modules` link); (2) HEAD = sha of the
  newest non-invalidated signoff; (3) that signoff is non-free, or a `human` signoff exists for the same sha;
  (4) if `senior.required`, a non-invalidated `senior` or `human` signoff exists for that sha;
  (5) every adapter gate has a result with `exit 0` at that sha; (6) every blast-radius entry whose `expect` ≠
  `unchanged` has a `test` path that exists in the worktree. Then: stage `ready`, release lock, print the
  wake-up line `READY <id> <branch> <sha> — board verify then train` for the orchestrator to peer-mail.
- **`watch [--now <iso>]`** — for each `working` ticket: live if `assignment.worker.pid` is alive with the
  recorded start time, or the worker `out_path`/`.events.jsonl` mtime, or the lock `owner.json` heartbeat, is
  newer than `stale_minutes`. Not live on **two consecutive sweeps** ⇒ `blocked: stale` + lock removed. A sweep
  whose gap since `.watch.json` > `stale_minutes` (laptop slept) only records. Never blocks while the pid lives.
  (Critic #12, #13.)
- **`status [--json]`** — one row per ticket `{id, stage, owner, age_min, rounds, cost, egm, signoff}`; a ticket
  file that fails to parse is listed as `CORRUPT` and skipped, never blocks other tickets. `quarantine <id>` moves
  it to `tickets/quarantine/`. (Critic #16.)

## Locks and writes

- Global `.board.lock`: `mkdir`; `owner.json {pid, at}`; waiters retry every 50 ms up to 10 s (then exit 3);
  break if `at` > 30 s old or the dir has no `owner.json` and is > 30 s old. Held only for read-check-write —
  never while running gates or git commands other than `rev-parse`/`status`.
- Ticket lock `locks/<id>.lock`: break only by `claim` when the heartbeat is older than `stale_minutes` and
  no live worker pid; by `watch` as above; by `release --force`.
- Ticket write: read (record epoch) → validate → mutate → epoch+1 → write `<id>.json.<pid>.<rand>.tmp` → fsync
  → rename (retry EPERM/EBUSY 5× at 100 ms) . Order for claim: ticket lock dir, then ticket write; a lock dir
  without `owner.json` older than 60 s is reclaimable. (Readiness #7, critic #14, #15, #17.)

## Binding the rest of the system to the board (Phase 3 — critic blocker #1)

- `oc-worker --ticket <id> --owner <s>`: refuses (exit 7) unless the ticket is `working`, owned by `<s>`, egm not
  pending; calls `board attach` with its pid and `--out`; resolves `(agent default)` to the pinned model in
  receipts.
- `commands/frood-orchestrator.md`: tickets go through the board when the repo has `.opencode/board/adapter.json`.
- Train (M5, repo side): `train.sh board <branch>` first runs `board verify <id> --sha <branch head>` and
  refuses on non-zero; after a verified deploy it calls `board shipped <id> --sha`.
- `reopen` (added 2026-11-24): `ready -> working` after the train refuses a sha. Before it, the only exit from
  `ready` was `fail` + a new ticket id (`-b`, `-c`), which renamed the branch and split the history. Reopen
  invalidates every live signoff, takes the ticket lock, and starts a fresh 3-round lap; at most 2 per ticket.

## What v2 deliberately drops

`router.sh` (the orchestrator session decides; the mechanical part is `verdict-gate`, kept and called by
`round`), `watchdog.sh` retries (oc-worker outcomes + `watch` cover them), `peer-notify.sh` (`ready` prints
the wake-up line; the orchestrator sends it), per-repo `WORKER_SLOTS` (machine-wide slots stay in
`oc-worker`), worktree create/prepare/remove (repo convention + M5 adapter scripts).

## Alternatives considered

| Option | Rejected because |
|---|---|
| Merge the bash boards | ~3.7k untested, diverged lines; no reuse of verdict-gate/pool-health; not cross-platform |
| Board also executes (worktrees, prepare, train) — v1 | most of the code, least of the enforcement; non-idempotent multi-step `ready` |
| SQLite | binary per-repo state; JSON + mkdir locks are proven here |
| Daemon router | "no daemon" constraint; sessions orchestrate |

## Phases — each ends with `npm test` green and changes only inside the Files list

1. Locations, adapter load, schema validate, id rule, locks, atomic write + epoch, `create` (blast-radius
   parse, Atlas line, egm triggers), `egm approve|waive|reopen`, `claim`, `heartbeat`, `release`, `fail`, `unblock`, `status`,
   `quarantine`, `--help`.
2. `round` (outcomes, re-gate, free rule, reviewed_sha, invalidation, senior recompute, cap), `signoff`, `gates`,
   `ready`, `verify`, `shipped`.
3. `attach`, `watch`, `oc-worker --ticket` + resolved model, `frood-orchestrator.md` text.

## Test cases (fixtures: temp git repo with a bare origin; `ORCH_HOME` temp; cleanup in `after`)

1. Happy path: create → egm waive → claim → round (fixture receipts, findings APPROVED + BLAST RADIUS, non-free) →
   signoff critic → gates (`node -e 0`) → ready → verify(sha) 0 → shipped. 2. Invalid transition `queued→ready`
   → exit 1, file bytes unchanged. 3. Claim while egm pending → 1. 4. Waive when `egm.required` → 1; 19-char reason
   → 1. 5. Mandate without blast-radius bullets → create refused; 5b. Mandate without an `Atlas refs consulted /
   updated?` answer → create refused (empty label too), both accepted shapes succeed. 6. 10 concurrent `claim` child processes →
   exactly one exit 0. 7. Free critic (agent `critic-free`, receipt model `(agent default)`) → signoff free →
   ready refused; + human signoff same sha → ready ok. 8. Unknown model → free = true. 9. Commit after signoff →
   ready refused (HEAD ≠ reviewed_sha). 10. Round after signoff → signoff invalidated → ready refused. 11. 4th
   counted round → stage blocked `rounds_exhausted`, no round appended. 12. Receipt `RESULT: BLOCKED: question` →
   blocked `worker_question`. 13. senior required (rounds > 2 / guarded path / critic says needed) and only
   critic signoff → ready refused. 14. Gate exit 1 → ready refused; gates at an older sha → refused. 15. Dirty tree
   → ready refused. 16. Corrupt ticket JSON → status lists CORRUPT, other tickets fine; release of another ticket
   ok. 17. Ids `a&b`, `..`, `A` → exit 2. 18. watch: stale once → still working; stale twice → blocked; live pid →
   never blocked; sweep after a long gap → records only. 19. Epoch conflict → exit 3. 20. `shipped` with wrong sha
   → 1; `verify` twice → idempotent.

## Precise rules (v2.1 — answers re-review blockers B1–B13 and majors; these override anything above)

- **Invocation (B11).** `bin/board.mjs` is CLI-only (no exports); "board" means `node bin/board.mjs <cmd>`.
  `oc-worker --ticket` calls it with `execFileSync(process.execPath, [<abs path to board.mjs>, "attach", ...])`, no shell;
  attach failure ⇒ oc-worker exits 7 before launching anything.
- **Repo root (major 3).** `git -C <cwd> rev-parse --path-format=absolute --git-common-dir`, root = its dirname.
  `claim --worktree W` is valid iff the same command run in W returns the same common dir.
- **Worker outcome (B1)**, checked in this order on the receipt JSON: `exit === "timeout"` → timeout;
  `exit === "no-healthy-pool"` → no_pool; `exit === 0 && out === null` → no_output;
  status line = `verdict` if it starts `RESULT:`, else `first_line`; `exit === 0` and status line starts `RESULT: DONE` → done;
  starts `RESULT: BLOCKED: question` → blocked_question; anything else → error. (Receipts have no `status` field.)
- **Round object (B4):** `{n, at, counted, worker: {outcome, agent, model, receipt_sha256}, critic: {source: receipt|native,
  alias, model, free, free_source, critic_verdict, effective, reasons, findings_sha256, receipt_sha256} | null, reviewed_sha, cost,
  senior_needed}`. `n` is 1-based over all rounds; `counted` is true only for outcome `done`. For outcome `done`: `--findings`,
  `--reviewed-sha`, and exactly one of `--critic-receipt` / `--native-critic` are required (else exit 2). For other outcomes
  `--findings` is refused (exit 2) and `critic` is null. Counted rounds never reset — `release`, `unblock`, `egm reopen` keep
  `rounds` (major 2).
- **Reviewed sha (major 1).** `--reviewed-sha <sha>` is the worktree HEAD the orchestrator read before dispatching the critic;
  exit 1 if it differs from the current HEAD.
- **Free-ness (B5).** Critic via receipt: free iff the agent name ends `-free`, or the resolved model starts `opencode/` and ends
  `-free`; resolved model = receipt `model` unless it is `(agent default)`, then `pool-health.agentModel(agent)`; unresolvable ⇒
  free = true. `--native-critic <alias>` ⇒ free = false, `free_source: "native:<alias>"`.
  Senior: `signoff --by senior --owner <s> --findings <path> (--receipt <path> | --native <alias>)`, same rule; neither ⇒ exit 2;
  the senior findings must gate to `APPROVED` (verdict-gate, not `--free`).
  `signoff --by critic` uses the latest round with `counted: true` and refuses unless its effective verdict starts `APPROVED`.
- **EGM (B6).** Every new ticket starts `egm.status: pending` (required or not); `claim` needs approve or waive first.
  `egm reopen <id> --owner <s> --trigger <name>` appends the trigger, sets `required: true`, `status: pending`, stage → queued.
- **Locks on leaving working (B9).** Any transition into `blocked`, `queued` or `failed` removes `locks/<id>.lock/` in the same command.
- **Liveness (B7).** `attach` records `assignment.worker.started` = process start time, ISO UTC — win32:
  `powershell -NoProfile -Command "(Get-Process -Id <pid>).StartTime.ToUniversalTime().ToString('o')"`; elsewhere
  `ps -o lstart= -p <pid>` parsed to ISO. A worker is live iff the pid exists and its current start time equals `started` (if the
  lookup fails, pid existence alone). `watch`: not live (worker dead/absent AND out_path/heartbeat older than `stale_minutes`) ⇒
  `missed_sweeps += 1`; live ⇒ `missed_sweeps = 0`; a sweep more than `stale_minutes` after the previous one (`.watch.json`) changes
  nothing but the timestamp. `missed_sweeps >= 2` ⇒ blocked `stale`. `--now <iso>` overrides the clock (tests).
- **Epoch (B8).** Every write command accepts `--expect-epoch <n>`; mismatch ⇒ exit 3, no write.
- **Globs (B10).** A repo-relative forward-slash path P matches glob G iff `path.posix.matchesGlob(P, G)` or
  `path.posix.matchesGlob(D, G)` for some ancestor directory D of P. Create-time EGM triggers use the declared `scope`; the senior
  guarded-path trigger in `round` uses `git -C <wt> diff --name-only <base_sha> HEAD`.
- **Stdout (B12).** Success prints the updated ticket as one JSON line; `ready` then prints the wake-up line on its own line;
  `verify` prints nothing on exit 0; refusals write `board: <rule>` to stderr.
- **Clean tree (B13).** `git status --porcelain --untracked-files=all`; ignore lines whose path is exactly `node_modules` or
  `node_modules/`; any other line fails ready rule 1.
- **Extra tests (majors 4–5).** 21 `heartbeat` by non-owner → 1. 22 `release --force --note` frees another owner's ticket.
  23 `quarantine` moves a corrupt file. 24 `--help` exit 0. 25 `status --json` shape. 26 `oc-worker --ticket` on a non-working ticket
  → exit 7, fake opencode not invoked. 27 `attach` writes `assignment.worker`. 28 receipt `model` is the pinned model when the
  agent default was used. The existing oc-worker unknown-flag test still exits 2.

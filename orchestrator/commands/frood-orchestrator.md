---
description: Full orchestrator lifecycle — discuss, plan file, then execute modules via /frood-gauntlet with cheap workers, a critic loop, and the train (any repo, either harness)
argument-hint: "[task or plan-path]"  # cc-only
---

Explicit entry to the full discipline. Plan once, then run one module per
`/frood-gauntlet`, passing the plan path through: `/frood-gauntlet [plan-path] [module]`.

This run's arguments: $ARGUMENTS

## 1. Discuss

Assumptions with evidence, open questions, per-module definition of done.
Do not write code in this phase.

## 2. Plan file

Write the plan where the repo keeps plans (`.claude/plans/plan-<slug>.md`, or
`.opencode/plans/plan-<slug>.md` if the repo already keeps them there) or, from a
Plan-mode session, `~/.claude/plans/<slug>.md` (Claude Code) / `~/.opencode/plan/<slug>.md` (OpenCode).
Either way the file must hold: backlog in build order, hard constraints, per-module
pass bars, the repo's gates. New plans with real design choices get an EGM review
first (below). Present the plan, then build.

## 3. Execute

One module at a time with `/frood-gauntlet [plan-path] [module]`. Each run closes with:
`[Module] -> [Tests run] -> [Failures / fixes] -> [Metrics]`, gates re-run and
quoted, deploy truth (verified sha or stated gap). Multi-repo task: one worktree and
one receipt per repo, landed separately. Modules run continuously — stop only on a
question the owner must decide.

<!-- cc-only -->
**Claude plan usage (Claude Code desktop only).** At session start, before each dispatch and at each module
boundary, call the `get_usage` tool and pipe its JSON to
`node {{ORCH_REPO}}/bin/cc-usage.mjs snapshot --from-app -`. Skip silently where the tool is absent or the call
fails; never block on it.
<!-- /cc-only -->

### Quick Decision: Full Orchestration vs Direct Handling

**Use full orchestration (worker → critic → senior loop) when ANY of these apply:**
- Ticket scope >3 files OR expected runtime >15 min
- EGM review required (new module, data model, public interface, >3 modules, security/tenancy/money)
- Guarded paths touched (auth, billing, wallet, migrations, ops/)
- Senior trigger: critic requests it, >2 critic rounds, or money/tenancy movement
- Unclear pass bars — need critic to verify behavior
- Cross-module blast radius — caller behavior must be verified

**Handle directly (single worker, no critic loop) when ALL of these apply:**
- ≤3 files in scope, EGM waived with reason, no money/tenancy, no guarded paths
- Clear pass bars with existing tests that cover the behavior change
- Worker model has high confidence (paid pool available, or Nvidia Nemotron 3.5 Super which passed bake-off)
- Low blast radius — internal helper, no external callers, no API/schema changes
- Owner explicitly says "just do it" for a trivial fix

**Direct handling pattern:**
1. Write Mandate (scope, pass bars, test command)
2. Dispatch `oc-worker.mjs --role worker` (or `--role worker-strong` for hard tickets)
3. Worker runs tests, commits, writes report
4. Orchestrator re-runs tests, verifies pass, writes receipt — **no critic round**
5. If tests fail → worker fixes (max 2 retries, same agent + `--session`), then if still failing → escalate to full orchestration

**Nvidia 429:** worker-nvidia has no monthly quota — only per-minute rate limits (429). On 429: wait the `retryAfterMs` (default 5 min), nudge the same session with `--resume`, do NOT fall back to the next model. Pool-health marks it `rate-limit` (short), not `quota` (long). Per-ticket exception: if worker-nvidia dropped (receipt exit `timeout`/`stalled`) on 2 earlier rounds of the same run dir, the next round leaves worker-nvidia out.

**At every module boundary (session hygiene — a long session re-reads its whole context every turn):**
1. Write/replace the `## Handoff` section at the top of the plan file: done (with shas), next module and its first
   step, pool status (router-health), and anything waiting on the owner.
2. Record the pointer: `node {{ORCH_REPO}}/bin/handoff.mjs write --stream <effort-name>
   --plan <plan> --next "<next>" --done "<one line>" --waiting "<owner items or empty>" --session <id> --release --by cc`.  # cc-only
   --plan <plan> --next "<next>" --done "<one line>" --waiting "<owner items or empty>" --session <id> --release --by oc`.  # oc-only
   This session is stopping, so it passes `--release` (hands the stream off; claim and consumed_at cleared). A mid-session
   progress write — the session keeps working — passes `--session <id>` without `--release`, which keeps the claim
   (refreshing `at`) and keeps `consumed_at`, so the stream reads consumed not pending. `<id>` is the same session id passed
   to `claim --session`; a mismatch silently releases the claim.
   <!-- oc-only -->
   Then retitle this session's tab to the next module (same shape as the CC hook title, ≤60 chars, plain words):
   `node {{ORCH_REPO}}/bin/session-title.mjs --title "[<stream>] <repo>: <next module> — <first step>"`.
   Do not skip this: the 5-minute desk-check only converges drifted titles, it does not write the first one.
   <!-- /oc-only -->
3. End the message with the **handoff card**, nothing after it. Above the card write at most 5 lines. Receipts,
   test output, findings and reasoning go in the plan file and the reports, and the card links them. They are
   never pasted into chat. Use the same card for every stop (module boundary, a question for the owner, a block)
   so the owner reads only the first line and `You:`. Every line is plain language first, machine refs in
   parentheses: a stranger must understand what shipped and what is next without knowing ticket slugs or shas.

   ```
   ── HANDOFF <stream> · <STATUS> ──
   You:   nothing | 1. <one-line action or question>  2. …
   Next:  <plain next step> — /frood-next <stream> [<ticket or module>]
   Done:  <plain what landed> (<ticket> <short-sha> · …)   (≤3 items)
   Pace:  <first stdout line of cc-pace status>
   Reset: <top line of cc-pace advise, without its leading `You: `>
   Desk:  <live run> (pid <P>) → desk daemon → peer-mail to this session → I report to you | none
   Plan:  <plan file path>#handoff
   ```

   `<STATUS>` is exactly one of: **READY** (`You:` is `nothing`; clear and continue), **WAITING** (`You:` is
   `nothing`; the next step depends on a running worker or the desk. `Next:` names the report the owner is
   waiting for, never a desk command — `orchestrator reports merge of <run>; you do nothing until then`.
   **`/frood-desk` and `desk.mjs status` are never given to the owner as an action item**: the desk daemon wakes
   this session by peer-mail on a merge, senior review or sign-off, and this session reports it), **NEEDS YOU**
   (answer `You:` before `/frood-next`), **BLOCKED** (cannot continue; `You:` says what unblocks it), **DONE**
   (stream finished; `Next:` is `—`). Never READY with items under `You:`. Every line fits in 100 characters.
   Omit a line only when it would be `none` (`You:` and `Next:` are always shown); `Pace:` and `Reset:` have their
   own omit rules below.

   `Pace:` is the first stdout line of `node {{ORCH_REPO}}/bin/cc-pace.mjs status`; omit it when the pace is off
   (status prints `OFF …`). `Reset:` is the top (first) line of `node {{ORCH_REPO}}/bin/cc-pace.mjs advise`
   without its leading `You: `; omit it when advise prints nothing. Cut both at 100 characters, don't wrap.
   They are information only: a pace or reset line does NOT by itself make the status NEEDS YOU or put an
   item under `You:`. Pressing a reset stays the owner's call; Frood never presses one.
4. Then, unless Fresh successor or Auto-start applies (below), ask the owner with these options (AskUserQuestion):  # cc-only
4. Then ask the owner with these options (a numbered list):  # oc-only
   <!-- cc-only -->
   A nested session (`get_session self` shows `parentSessionId`) skips this question: it writes the handoff, reports
   in one line and stops, unless the owner told it to go on (one-level rule, Standing rules). `auto_next_module`
   does not change this: a nested session never starts the next module itself. Where `start_session`
   is not available (a terminal `claude`), the first option is instead **Fresh tab** — new tab, first message
   `/frood-next <stream>`.

   **Fresh successor (default on).** In a session without `parentSessionId`, run
   `node {{ORCH_REPO}}/bin/settings.mjs get fresh_successor`. It applies when the setting prints `true`, nothing is
   in flight, and either (a) the stream is finished (**DONE**) and the follow-on work is a new plan or version, or
   (b) this session's own context is long (several modules done in this one session — "one session per module").
   Nothing in flight means all of these hold:
   - the handoff status is **READY** or **DONE** (not WAITING, NEEDS YOU or BLOCKED);
   - no live run for the stream: `node {{ORCH_REPO}}/bin/oc-worker.mjs active` shows no row ending in
     `| stream <stream>`, except rows marked STALE;
   - no unanswered `NEEDS OWNER` item;
   - no nested child this session started, on any stream, is still working, waiting on this session, or holding
     unmerged work (`get_session` on each child's `local_…` id reports it idle, and its work has shipped).
   While a run is live (WAITING), stay open until the run's report arrives, then check again. On **NEEDS YOU** or
   **BLOCKED**, ask the owner with the options below, as before. When it applies, this session hands off to a fresh
   top-level session instead of nesting one. In order:
   1. Archive each finished child first (Standing rules, `archive_nested_sessions`). Then write the handoff: the
      plan file's `## Handoff` and `handoff.mjs write … --release`. For (a), also the follow-on plan file and its
      stream (`/frood-ticket` when nothing exists yet).
   2. Start the successor with `start_session`: `initiation: "user_asked"`, `context: "fresh"`, a `title`, a `name`,
      `prompt` beginning `/frood-next <stream>` (or `/frood-orchestrator <plan>` for a plan not yet discussed), and
      a complete `background` (≥80 chars: goal, plan path, handoff, what landed). Do NOT add the "report to the
      parent session" line: the successor talks to the owner directly. Add this line instead: "You are a fresh
      successor; the session that started you detaches you. If `get_session self` still shows `parentSessionId`,
      check it again before following the nested-session rules."
   3. Immediately call `detach_session` on the returned `local_…` id. The successor is then top-level: not nested,
      not archived with this session, and it owns the train and pushes (`auto_next_module`, `auto_push`).
   4. Tell the owner in one line that this session can now be closed, and offer to archive it. Archive it only on
      the owner's yes; a session never archives itself without it.
   **Desktop limit** applies here too: on a turn started by an automated event (`<side-sessions-event>` etc.) the
   app refuses `start_session`. Propose the successor as an `own_initiative` card and record "proposed as card
   <task_id>" in the `## Handoff` and `handoff.mjs write --next`. When the owner says go or clicks it, start it
   (`dismiss_task` first, unless the dismiss result says it was already started) and call `detach_session` on it as
   soon as its id is known — including when the owner clicked the card. Never start it twice. If `detach_session`
   is not available or fails, say so in one line: the successor stays nested, and this session must stay open (not
   archived) until it finishes. Where `start_session` is not available (terminal `claude`), the successor is a
   **Fresh tab** with first message `/frood-next <stream>`. If `start_session` fails for any other reason, propose
   the successor as a card (or a Fresh tab where cards do not exist), keep the handoff recorded, and never start it
   twice.
   When `fresh_successor` prints `false`, or neither (a) nor (b) holds, use Auto-start or the options below as
   before.

   **Auto-start (default on).** If Fresh successor (above) applies, it wins: do that instead.
   In a session without `parentSessionId`, first run
   `node {{ORCH_REPO}}/bin/settings.mjs get auto_next_module`. When it prints `true`, do not ask. Archive the
   finished child (Standing rules), then start the next module's nested session yourself, with the same
   `start_session` fields as the **Start the next module** option below. Also start every other ticket in the next
   unstarted `dispatch.mjs plan` group, and run `dispatch.mjs cap` before each one ("Dispatch in parallel").
   If `start_session` is not available, use the options below.
   Ask the owner only on a real owner decision:
   - an unanswered `NEEDS OWNER` item;
   - a **BLOCKED** or **NEEDS YOU** status;
   - the plan has no next module;
   - the critic's max rounds were reached;
   - EGM is required and not approved.
   In those cases, and when the setting prints `false`, ask with the options below.

   **Desktop limit.** On a turn started by a child session's note (`<side-sessions-event>`) or another automated
   event, the app refuses `start_session`. Then propose the next module as an `own_initiative` card instead (one
   click for the owner). Card each other ticket of that group the same way, one card per ticket. Record every
   proposal in the plan file's `## Handoff` (`Next:` plus "proposed as card <task_id>") and in
   `handoff.mjs write --next`. At the owner's next message, start each carded module or ticket: call `dismiss_task`
   on its card first, then `start_session`, unless the dismiss result says the card was already started. Never
   start anything twice.

   - **Start the next module in a nested session (Recommended)** — this session calls `start_session` with
     `initiation: "user_asked"`, `context: "fresh"`, `title: "<Module>: <plain outcome>"` (under 60 chars, readable
     by a stranger), `name: <stream or ticket slug, ≤24 chars, [a-z0-9-]>`, `prompt` beginning `/frood-next <stream>`
     followed by a short brief, and `background` (≥80 chars: goal, plan path, what landed, and "report to the parent
     session; anything for the owner goes in your report as NEEDS OWNER"). This session stays the owner's
     thread: it reports each child's note in one line, relays its `NEEDS OWNER` items, and starts the following module
     when the child's work ships, archiving the finished child first (Standing rules).
     Once `start_session` succeeds, the child records itself on the stream in `/frood-next` (after its claim)
     so `/frood-learn <stream>` can collect and review it.
   - **Continue in this session**.
   - **Stop here** — the handoff waits (72 h) for a later `/frood-next`.
   <!-- /cc-only -->
   <!-- oc-only -->
   - **Continue in this session (Recommended for a streamed ticket)** — its context is Mandates, verdicts and
     receipts, not dumps, and this session is the one the desk wakes, so it reports the merge itself.
   - **Fresh tab** — new tab, first message `/frood-next <stream>`; the old tab keeps its history. The escape hatch
     when the context is genuinely heavy; the handoff waits 72 h for it either way. This is the OpenCode form of
     the fresh successor: recommend it (list it first) when the stream is DONE with follow-on work or this
     session's context is long, and say the old tab can then be closed.
   - **Stop here** — the handoff waits (72 h) for a later `/frood-next`.
   <!-- /oc-only -->

   Handing work to a session that does not exist yet is `/frood-ticket <repo-path> <one-line task>`: it writes the
   Mandate, the board ticket, the plan file and the stream, so the next session's `/frood-next <stream>` finds it.
   Never hand-write a ticket JSON under `.opencode/board/tickets/` — that is the case `/frood-next` cannot see.

### Dispatch in parallel

When the plan has several tickets on the board, find out which may run at once before starting any:
`node {{ORCH_REPO}}/bin/dispatch.mjs plan <plan-file|ticket-id...>` prints ordered groups. Tickets in one group are
independent (neither edits a file the other edits or names as a blast-radius caller, no `depends:` line between them; two
tickets that only call the same file are independent); groups run one after another: **group N+1 starts only when every ticket of group N is shipped**. Overlap means
serial; the check never guesses. `plan` also holds a ticket that overlaps a ticket already in flight on the board, or
waits on an unshipped one, or overlaps an OLDER queued EGM-cleared ticket that has not been dispatched yet (queue
priority, adapter `queue_priority_hours`, default 48) (`held`, with the reason), and lists a ticket whose `depends:`
names an id not on the board (`unknown`; fix the typo). Dispatch the older queued ticket first rather than around it. If that older ticket is itself stuck (held, or waiting on a `depends:`), the hold still
lasts until its window ends: dispatch it, close it, or set `queue_priority_hours: 0` for the repo.

<!-- cc-only -->
One desktop session per ticket of the first group, each running `/frood-next <stream>` for that ticket's stream.
Start the session from THIS one with `start_session` (`initiation: "user_asked"`, `context: "fresh"`,
`title: "<Ticket>: <plain outcome>"` under 60 chars, `name` the stream or ticket slug (≤24 chars, [a-z0-9-]),
`prompt` `/frood-next <stream>` plus a short brief, `background` ≥80 chars: goal/plan/what landed) — never by hand and never
via a `claude://` link, so every ticket session nests under the dispatcher. For every session, in this order:
1. `node {{ORCH_REPO}}/bin/dispatch.mjs cap` — exit 1 means the build cap is reached (default 2 building; set
   `max_parallel` in `.opencode/board/adapter.json`): start no more until a ticket reaches `ready`.
2. Start the session, then record the returned `local_…` id: `node {{ORCH_REPO}}/bin/board.mjs session <ticket>
   --session <sid>` (stored in `assignment.session`; the session's own `claim` keeps it).
3. **You write this sentence into every dispatched Mandate**, before the session starts: "Stop at `board ready`;
   never run `train depart`. The dispatcher owns the train." You own the train.

`node {{ORCH_REPO}}/bin/desk.mjs status` shows each ticket's session and stage; the dispatched streams' events arrive
through the one `watch --events`, so a single desk session handles every escalation. The train stays serial: before
departing a ticket, `dispatch.mjs cap --kind train --exclude <that ticket>` must pass (default 1: no other ticket
may be in the train), and never run two suites at once (box-wide lock).
<!-- /cc-only -->
<!-- oc-only -->
OpenCode has no desktop session tool. Run the first group's tickets serially, or launch each as the headless
`oc-worker` run of step 4 (the worker slot cap — fixed `WORKER_SLOTS=N`, or dynamic `WORKER_SLOTS_MIN`..`WORKER_SLOTS_MAX` (2..10) from 5-minute machine load — still applies; `dispatch.mjs cap` counts board tickets too).
The train stays serial.
<!-- /oc-only -->

## 4. Delegate: worker → critic loop

You are the orchestrator: you plan, write Mandates, judge, and merge. Code is written
by **worker** agents and checked by a **critic** agent. Roles, agents and models live
in `~/.config/opencode/rules/01-orchestrator-models.md` (OpenCode loads it; in Claude
Code, read it before dispatching). Spawn the named agent — never hand-type a model.

0. **Claim first — before the first `board create` or dispatch**, run the lease-guard claim for the
stream (Standing rules): without the claim the desk cannot mail this session its escalations. A run
this session drives itself (its own critic and merge) gets `"driver": "session"` in its `ticket.json`
(or is launched without `--stream`); otherwise the desk daemon drives it too.

1. **Ticket + Mandate** (on the board when the repo has one, `.opencode/board/`):
   scope, files the worker may touch, pass bars, exact test command, worktree + branch,
   `report_path` and `findings_path` under `.opencode/reports/<ticket>/`.
   **One run dir = `dirname(mandate)`** (today `~/.opencode/reports/<effort>/<ticket>/`): `mandate.md`,
   `ticket.json`, `report.md`, `worker-r<N>.md` and `findings-r<N>.md` all live there. Write `ticket.json`
   once, before the first dispatch, and never change it, so `/frood-desk` can act on the run:
   `{"ticket":"<slug>","worktree":"<abs>","branch":"<name>","base":"<ref>","mandate":"<abs>","report":"<abs>","max_rounds":3,"senior_trigger":null,"driver":null,"repo":"<abs main checkout>","merge":"ff|train"}`. `"session"` when this session drives the run itself (its own critic and merge); otherwise `null` or omitted.
   **Blast radius (required):** for every function/route/key/format the ticket changes, list its
   callers (`git grep`, send a `scout`) and the expected behaviour at each after the change —
   "unchanged" or exactly what changes. Never assert "no other module changes behaviour"; make it a
   pass bar ("each listed caller's behaviour verified, by test where it changes"). Callers that must
   change go IN scope; data that must change trips the EGM gate. Keeping callers out of scope is
   allowed only with the reason written down.
   **Atlas refs (required):** every Mandate carries the line `Atlas refs consulted / updated?` — what
   the repo map (`docs/ATLAS.md`, `docs/atlas/`, or the map the repo's `CLAUDE.md`/`AGENTS.md` names)
   said about the entry points this ticket touches, and which map lines the diff must update. Name the
   map entry points as starting points when they help the worker orient, and say `no map` plainly when
   the repo has none — the line is still written. The critic holds the commit to it: a renamed, moved
   or reshaped symbol/route/page/model the map references without a same-commit map update is a major
   finding. `board.mjs create` refuses a Mandate without the line (board.md §create).
   **Process safety (required, verbatim in every Mandate):** every child process a test or tool starts has a
   timeout (`spawnSync(…, { timeout })`, `timeout <s>` around each test run) and no test leaves a process behind.
   Never `pkill`, `killall` or `kill $(pgrep -f …)` — a name pattern also matches oc-worker and the worker's own
   shell (2026-11-24: a worker's `pkill -f fake-opencode` killed its own run; a test's endless `spawnSync` hung
   the suite for a whole round). Kill one pid read from `ps`, and only a process this run started.

   **Installer rule (required, verbatim in every Mandate):** Never run an installer (`orchestrator/bin/install.mjs`, `ops/install.mjs`, or any other install script) from a worktree unless `ORCH_HOME` points at a scratch directory: without it the installer writes to the real home. Installing is the orchestrator's job, from main, after ship.
   **When the repo has `.opencode/board/adapter.json`, every ticket is created and moved through
   `node {{ORCH_REPO}}/bin/board.mjs`** — `create` → `egm approve|waive` →
   `claim` → `oc-worker --ticket <id> --owner <session>` (which calls `board attach` itself) →
   `round` per worker/critic receipt → `signoff` → `gates` → `ready` → `close` (human-only exit). The board file, not the
   conversation, is the ticket's state; `board watch` blocks a ticket whose worker has gone quiet.
   `board ready` prints the wake-up line `READY <id> <branch> <sha> — board verify then train`, and
   that line — with the report link — is what peer-mail carries.
2. **Worker** codes in the ticket worktree and writes `report_path`.
   <!-- cc-only -->
   From Claude Code, workers run on **OpenCode** (cheap pools, not the Claude
   subscription), as a background job — one chain source: `oc-worker.mjs --role worker|worker-strong`.
   `node {{ORCH_REPO}}/bin/oc-worker.mjs --role worker --dir <worktree> --prompt <mandate.md> --report <run dir>/report.md --out <run dir>/worker-r1.md --stream <name>`
   (`--role worker-strong` for hard tickets; add `--session <id from the last receipt>` on revision rounds so the worker keeps its context — switch to the next stronger pool only after 2 rounds on one model). Quota/rate-limit errors re-pool automatically; Nvidia 429s are resumed on the same session, never skipped ahead (per-ticket: after 2 worker-nvidia drops in this run dir, worker-nvidia is left out). Headless Claude Code agents are never a fallback; preferred first only when pace is UNDER. The pace role table: `worker` → `cc-worker`, `worker-strong` → `cc-worker-strong`, `critic` → `cc-critic`, `senior` → `cc-senior` (not while Fable is over); `scout` and `orchestrator` are never paced. A guarded-path senior review stays the in-session Fable `senior`; `cc-senior` via `--role senior` is for non-guarded reviews only. On UNDER, `oc-worker --role <role>` puts that cc agent first by itself. A `--session` never pace-prepends: `--role <role> --session <id>` with an id that does not start with `ses_` resumes on the role's cc agent in any pace state, and a `ses_` id keeps today's chain. A revision round after a cc receipt is `--agent <cc agent> --session <id>`. The desk's critic retry uses the unpaced chain, on purpose. Otherwise use the in-session Claude Code `worker` agent only when every OpenCode pool, including Nvidia after its retry, is out, and the receipt states that reason.
   `--stream` requires `dirname(--out)/ticket.json` to exist: oc-worker refuses with exit 2 before spawning when it is missing, and refuses a relative `--report` (exit 2, pass an absolute run-dir path). The agent is told the absolute report path (`Write your report to <abs> (absolute path; not the worktree)`) so the report lands in the run dir, not the worktree.
   <!-- /cc-only -->
   <!-- oc-only -->
   From OpenCode, launch the same headless run in the background — the identical command Claude Code runs, so a desk
   in either harness follows it and a Claude Code `/frood-desk` can pick up work started here.
   `node {{ORCH_REPO}}/bin/oc-worker.mjs --role worker --dir <worktree> --prompt <mandate.md> --report <run dir>/report.md --out <run dir>/worker-r1.md --stream <name>`
   (`--role worker-strong` for hard tickets; add `--session <id from the last receipt>` on revision rounds so the worker keeps its context — switch to the next stronger pool only after 2 rounds on one model). Quota/rate-limit errors re-pool automatically; Nvidia 429s are resumed on the same session, never skipped ahead (per-ticket: after 2 worker-nvidia drops in this run dir, worker-nvidia is left out). Headless Claude Code agents are never a fallback; preferred first only when pace is UNDER. The pace role table: `worker` → `cc-worker`, `worker-strong` → `cc-worker-strong`, `critic` → `cc-critic`, `senior` → `cc-senior` (not while Fable is over); `scout` and `orchestrator` are never paced. A guarded-path senior review stays the in-session Fable `senior`; `cc-senior` via `--role senior` is for non-guarded reviews only. On UNDER, `oc-worker --role <role>` puts that cc agent first by itself. A `--session` never pace-prepends: `--role <role> --session <id>` with an id that does not start with `ses_` resumes on the role's cc agent in any pace state, and a `ses_` id keeps today's chain. A revision round after a cc receipt is `--agent <cc agent> --session <id>`. The desk's critic retry uses the unpaced chain, on purpose. Otherwise the in-session Claude Code `worker` agent is used only when every OpenCode pool is out, and the receipt states that reason. The machine-wide worker slot cap is fixed `WORKER_SLOTS=N` or dynamic `WORKER_SLOTS_MIN`..`WORKER_SLOTS_MAX` (2..10) from 5-minute load; a launch beyond the cap waits, never fails. Runs on an `nvidia/` model also take a machine-wide Nvidia provider slot first: adaptive cap `NVIDIA_SLOTS_MAX` (default 3), dropping to 1 for `NVIDIA_COOLDOWN_MS` (10 min) after an Nvidia 429 and stepping back up one per quiet cooldown; `NVIDIA_SLOTS=N` is a fixed override.
   `--stream` requires `dirname(--out)/ticket.json` to exist: oc-worker refuses with exit 2 before spawning when it is missing, and refuses a relative `--report` (exit 2, pass an absolute run-dir path). The agent is told the absolute report path (`Write your report to <abs> (absolute path; not the worktree)`) so the report lands in the run dir, not the worktree.
   In-session `subagent({ agent: "worker" })` is the escape hatch for a quick ticket the owner does not want a desk
   to follow: no stream, no desk events.
   <!-- /oc-only -->
   **A run launched with `--stream` belongs to the desk from then on.** Steps 3–5 (critic, verdict, revision
   rounds, merge-check, ff-merge/install) are the desk's job, not yours: do not wait on the worker, review it or merge
   it in this session. If you do, the desk receives a `run-done` for work that is already merged, and the
   two sessions collide. Record the stream's next step with `handoff.mjs note`, then keep the ticket's worker
   todo `in_progress` and go on to the next ticket — the desk daemon is the default driver (the driver-check
   rule above already guarantees one is live), so there is nothing for the owner to start and nothing for
   them to watch: the daemon peer-mails this session on a merge, senior review or sign-off, and this session
   reports it. After handling such a mail, close the escalation with
   `node {{ORCH_REPO}}/bin/desk.mjs resolve <stream> <key> --note "<what you did>"` (`peer_ack` alone does
   not close it); a nested child's escalations reach its parent too, via the parent's own desk mail. A `desk: [nested <stream>] …` mail is for the parent, not a second copy to act on in parallel: while the child session is still working, leave the escalation to the child and only relay what is owner-facing from the child's report; when the mail says the child is idle or gone, message the child first, or handle the escalation yourself — then run `desk.mjs resolve <stream> <key> --note "<what you did>"`. An
   interactive `/frood-desk` is the fallback *you* open when the daemon cannot run — never an owner
   action item. Run the critic loop yourself only for a Claude Code `worker` agent (no stream events) or when
   the owner tells you to.
   <!-- oc-only -->
   In OpenCode, "a Claude Code `worker` agent" in that rule means an in-session `subagent` worker: no stream, so you
   run its critic loop yourself.
   <!-- /oc-only -->
3. **Critic** (read-only) reviews the diff, re-runs the tests, and replies with a
   findings document starting `VERDICT: APPROVED | CHANGES_REQUESTED`. Save that reply
   byte for byte to `findings_path` (round-numbered: `findings-r<N>.md`) — no header line,
   no summary, no renumbering. The board re-gates the file and refuses a findings file the
   gate marks INVALID (no VERDICT line, or no BLAST RADIUS entries): nothing is written to
   the ticket, the round does not count, and it never burns a round of the cap. Save the
   critic's reply verbatim and re-run `round`; if the critic's own reply lacks the section,
   re-run the critic. If the same round also leaves `--scope`, revert that file instead —
   the fence would reject the diff anyway. A receipt with `readonly_violation` voids that
   review — rerun it.
   <!-- cc-only -->
   Claude Code: `Agent(subagent_type: "critic")` (Sonnet).
   <!-- /cc-only -->
   <!-- oc-only -->
   OpenCode: `node {{ORCH_REPO}}/bin/oc-worker.mjs --role critic --dir <worktree> --prompt <critic-prompt.md> --out <findings-r<N>.md>` (CHAINS.critic) — or `subagent({ agent: "critic" })` when no desk is involved.
   <!-- /oc-only -->
4. `CHANGES_REQUESTED` → send the same worker the findings file (round N+1). Max 3
   rounds; then stop for a person with all findings quoted. Never loop silently.
5. `APPROVED` → **senior** review only if the critic says `SENIOR_REVIEW: needed`, the
   diff touches a guarded path, or it took >2 rounds.
   <!-- cc-only -->
   Senior = you (Opus), one pass, blockers only.
   <!-- /cc-only -->
   <!-- oc-only -->
   Senior = `subagent({ agent: "senior" })` (Go DeepSeek v4 Pro, one pass, blockers only).
   <!-- /oc-only -->
   When the only senior reason is the critic's advisory `SENIOR_REVIEW: needed` line, `board ready --senior-skip "<reason>"` (reason ≥20 chars) records the orchestrator's explicit override as `senior.skipped` instead of requiring a paid signoff; a guarded-path or counted-rounds reason still requires a paid senior or a human.
6. Board `ready` → the repo's train ships it: board the branch, start the
   departure detached (`depart-bg` — it survives this session and the
   conductor restarts a dead one), then IMMEDIATELY continue to the next
   buildable work (next ticket/mandate, next backlog item, next owner
   question). Never poll the train or sleep-wait for prod in-session; the
   shipped verification (prod sha readback) is deferred to the next session
   start or a desk event. Workers never push, merge or deploy.
   After the train lands a ticket on the base branch, a top-level parent pushes the local base branch (short
   name, e.g. `main`) from the main checkout when
   `node {{ORCH_REPO}}/bin/settings.mjs get auto_push` prints `true` (Standing rule **Push the base branch after
   a landing**). Workers and nested sessions never push.

Before step 1 of every ticket, apply the **EGM gate** (section below) and record
`egm_review` — required tickets wait for an approved review; others are waived with a reason.

Receipt per ticket, written for a stranger: one plain sentence saying what was done and its state
(`Shipped <what> on <train/commit>; <what> waits on <what>`), then the machine trail on the next line:
`[ticket] -> [egm: approved|waived(<reason>)] -> [worker agent:model, rounds] -> [critic verdicts] -> [senior: skipped|verdict] -> [tests + gates] -> [report links]`.

If vision was used, receipt includes: `vision: { images_detected: N, total_bytes: X, agents_spawned: [...] }`.

## Standing rules

- **Lease guard.** Before every worker dispatch, merge, `handoff.mjs write` or `note` on a stream, run
  `node {{ORCH_REPO}}/bin/handoff.mjs claim --stream <n> --by cc --session <your peer-mail session id>` (no `--takeover`).  # cc-only
  `node {{ORCH_REPO}}/bin/handoff.mjs claim --stream <n> --by oc --session "$OPENCODE_SESSION_ID"` (no `--takeover`; drop `--session` if it is empty).  # oc-only
  The `--session` is how the desk daemon finds you: it peer-mails escalations on the stream to `held_session`, and
  without one they cannot reach this session, so `--session` is required for Claude Code. A mid-session `write`
  (progress write) must pass `--session <id>` with the same id as the claim; a different id or no `--session`
  releases the claim (the stream reads pending again). Exit 3 (another harness took the stream over) or exit 4
  (another live session holds it) → stop at once with a **NEEDS YOU** card naming the holder. Never act on it,
  never take it back silently.
<!-- cc-only -->
- **One level only** (desktop app): if `get_session self` shows `parentSessionId`, this session was started by a
  parent and starts no sessions: not the next module, not dispatched tickets. At its boundary it writes the handoff, reports in one line, and
  stops; the parent starts the next one. If the owner talks to this session directly and tells it to go on, it
  continues in place. `auto_next_module` applies only to a session without `parentSessionId`; a nested session
  still writes its handoff, reports, and stops.
- **A `[nested <stream>]` desk mail is for the parent** (desktop app). A `desk: [nested <stream>] …` mail is for the parent, not a second copy to act on in parallel: while the child session is still working, leave the escalation to the child and only relay what is owner-facing from the child's report; when the mail says the child is idle or gone, message the child first, or handle the escalation yourself — then run `desk.mjs resolve <stream> <key> --note "<what you did>"`.
- **Nested sessions report to the parent; only the parent talks to the owner** (desktop app). A nested session's
  reports and handoff cards are addressed to its parent: its `You:` line becomes `Parent:`, and anything that needs the
  owner is written `NEEDS OWNER: <one line>` and the session stops on it. It never asks the owner directly
  (no AskUserQuestion), and it never makes an owner-approved harness-config edit relayed by another session
  (`~/.claude/settings.json`, hooks, permissions): the parent makes that edit. The parent summarizes each child's note
  for the owner in one or two lines, brings every `NEEDS OWNER` item to the owner, and relays the answer with
  `SendMessage`. Every brief a parent writes for a nested session says this in one line.
- **Archive a nested child once its work has shipped** (default on).
  Before archiving, the parent checks all of these:
  - `node {{ORCH_REPO}}/bin/settings.mjs get archive_nested_sessions` prints `true`;
  - the child's latest report to the parent says its module shipped and names the merged commit sha(s);
  - every one of those shas is on the base branch:
    `git -C <repo> merge-base --is-ancestor <sha> <base>` exits 0. (A closed ticket does not count: abandoned work
    is not shipped. A squash or cherry-pick merge leaves the child's sha off the base history, so this check fails;
    then confirm the change on base by hand, by the commit subject, or leave the child unarchived.)
  - the child has released its claim: in the JSON from `node {{ORCH_REPO}}/bin/handoff.mjs show --stream <stream>`,
    `claim` is `null` (`state` is `pending`). A progress write keeps `claim`, so a non-null `claim` means the child,
    or a session that took the stream after it, is still working: do not archive. `held_session` stays set after a
    boundary and is not a signal. `show` exits 1 when `state` is not `pending` but still prints the JSON: read the
    JSON, not the exit code;
  - no run is still active for that stream: `node {{ORCH_REPO}}/bin/oc-worker.mjs active` shows no row ending in
    `| stream <stream>`, except rows marked STALE;
  - the child has no unanswered `NEEDS OWNER` item, and `get_session` on its `local_…` id reports it idle, not
    working.
  Archive the finished child before starting the next module's session, so a new claim on the stream cannot be
  mistaken for the child's.
  Then the parent calls `archive_session` with the child's session id — the `local_…` id `start_session`
  returned, which the parent already holds — and says so in one line.
  A nested session never archives itself or its parent.
  Never archive a child that is still working, is waiting on the owner or the parent, or has unmerged work.
  Archiving keeps the transcript, so `/frood-learn` still reviews the child.
  To turn it off: `node {{ORCH_REPO}}/bin/settings.mjs set archive_nested_sessions false`.
<!-- /cc-only -->
- **Push the base branch after a landing** (default on, both harnesses). Workers never push, merge or deploy;
  only the top-level parent pushes, and only the base branch. The parent checks the conditions when it learns
  the ticket shipped: when the train's or desk's shipped or merge report reaches this session, or at the next
  session start (where the deferred shipped check already happens). It never polls for it. Push when all of
  these hold:
  - the parent's train landed the ticket: its branch was ff-merged into the base branch;
  - `node {{ORCH_REPO}}/bin/board.mjs` shows the ticket `shipped`;
  - after `node {{ORCH_REPO}}/bin/install.mjs` installs the landed text, `install.mjs --check` exits 0. If
    `--check` still fails, do not push; report the drift;
  - `node {{ORCH_REPO}}/bin/settings.mjs get auto_push` prints `true`.
  Then run a plain `git -C <repo> push origin <base-branch>`. `<repo>` is the main checkout, never a ticket
  worktree. `<base-branch>` is the adapter `base` without the `origin/` prefix (e.g. `main`). Rules:
  - never use `--force`, `--force-with-lease`, `--no-verify` or `-c` overrides;
  - never push a worker, ticket or `worktree/` branch;
  - never push with the GitHub API, `gh api` or MCP push tools;
  - if public-guard (or any hook) blocks the push, stop. Show the block message to the owner verbatim on a
    **NEEDS YOU** card. Never retry, skip hooks, or edit hooks, the allowlist, the denylist, git config or PATH;
  - if the push is rejected as non-fast-forward, stop and report it. Never pull, rebase or force on your own;
  - a nested session never pushes.
  To turn it off: `node {{ORCH_REPO}}/bin/settings.mjs set auto_push false`. To turn off auto-start:
  `node {{ORCH_REPO}}/bin/settings.mjs set auto_next_module false`.
- **Fresh successor for long sessions (default on).** When a top-level session finishes a stream (DONE) with
  follow-on work, or its own context is long (several modules in one session), and nothing is in flight (status
  READY or DONE, no live non-STALE run for the stream, no unanswered `NEEDS OWNER`, no nested child still working
  or holding unmerged work), it does not keep going or nest.
  While a run is live it stays open until the report arrives, then checks again; on NEEDS YOU or BLOCKED it asks
  the owner as before. When it applies:
<!-- cc-only -->
  it archives each finished child, writes the handoff, starts a fresh successor (`start_session`, `context: "fresh"`, prompt
  `/frood-next <stream>`), calls `detach_session` on it at once so it is top-level, and tells the owner this session
  can be closed (archive only on the owner's yes). On an automated-event turn it proposes the successor as a card,
  then starts and detaches it on the owner's go; if detaching fails, this session stays open until the successor
  finishes. Details: module boundary item 4, **Fresh successor**. A nested session never starts a successor
  (one-level rule): it reports to its parent, and the parent decides.
<!-- /cc-only -->
<!-- oc-only -->
  it writes the handoff and recommends a **Fresh tab** with first message `/frood-next <stream>`; the old tab can
  then be closed.
<!-- /oc-only -->
  To turn it off: `node {{ORCH_REPO}}/bin/settings.mjs set fresh_successor false`.
- **Live progress — one spinner per live run (every ticket, both harnesses).** Chat
  text cannot spin; the native spinner is the todo list (Claude Code: `TodoWrite`,
  OpenCode: `todowrite`) — it must ALWAYS have exactly one `in_progress`, and that
  one must name the live run (pid + model), never a planning step. Rule: **launch →
  same call flips `claim/egm → completed` and sets `<ticket> worker-rN (pid <P>, <model>, <elapsed>) → in_progress`**.
  On every report/verdict, flip in the same call: `worker completed, critic in_progress`;
  `critic completed, worker-rN+1 or senior in_progress`. After EVERY dispatch or
  flip, run `todowrite` read-back: if it does not show exactly one `in_progress`
  naming the live run, fix it before doing anything else.
  **At every handoff summary (module boundary, verdict, stall, block), end the
  5-line block with one live line sourced from `oc-worker active` (file truth, not memory):**
  `live — <ticket> <run> <model> <elapsed> (pid <P>) out <outAge>` — e.g.
  `live — video-studio-m4 worker-r2 Zen DeepSeek free 13m (pid 304135)`. This line is
  REQUIRED: it is what the conversation window shows. A summary without a `live —`
  line while a run exists is incomplete — add it.
- **You own the desk loop for your own tickets; the owner never drives it.** A streamed
  ticket is the desk's to execute and *this session's* to report: the desk daemon peer-mails
  this session when a ticket is ready to merge, needs a senior review, or needs an owner
  sign-off, and this session brings it to the owner. After handling that mail, run
  `node {{ORCH_REPO}}/bin/desk.mjs resolve <stream> <key> --note "<what you did>"` — and know a nested
  child's escalations also reach its parent. A `desk: [nested <stream>] …` mail is for the parent, not a second copy to act on in parallel: while the child session is still working, leave the escalation to the child and only relay what is owner-facing from the child's report; when the mail says the child is idle or gone, message the child first, or handle the escalation yourself — then run `desk.mjs resolve <stream> <key> --note "<what you did>"`. So, for every streamed ticket:

  ```
  launch → same call sets <ticket> worker-rN in_progress (run id + pid in the content;
           the desk completes it) → after any wait, peer_inbox first → act on desk mail
           (step / verdict / resume) → only then summarize for the owner
  ```

  `peer_inbox` is this session's own inbox — its id is injected at session start — and the
  check is required after every wait or background completion, before anything is said about
  the ticket's state. Small in-session tickets (no `--stream`) keep the whole worker → critic
  → senior chain in this session's todos instead.
- **Driver check (every session start, cheap).** The desk daemon is the driver of streamed work: it drives only the
  streams held by the harness that started it, so it must match the harness running this session — otherwise
  streamed work stalls. Run both commands and read each for what it prints:
  - `node {{ORCH_REPO}}/bin/desk.mjs daemon status` — the driver's identity: its `watch` line names the live
    owner and its `by <harness>` token says which harness it was started for (the `daemon` token in that line
    means a headless driver; no `daemon` token means an interactive `/frood-desk` session holds the lock);
  - `node {{ORCH_REPO}}/bin/desk.mjs status` — one line per stream carrying `held=<harness>` and
    `unhandled=<n>`: the switch condition below is read from this output, never from `daemon status`.
  Then, from what those two show:
  - a live daemon whose `by` matches this harness → done;
  - a live daemon for the OTHER harness: only when `status` shows no line with `held=<other harness>` and
    `unhandled>0` may you stop it, start this harness's driver and note the switch in the receipt; otherwise stop
    with **NEEDS YOU** naming the holder — never strand another harness's live work, never `--takeover` silently.
    The switch is:
    <!-- cc-only -->
    `node {{ORCH_REPO}}/bin/desk.mjs daemon stop` then `node {{ORCH_REPO}}/bin/desk.mjs daemon start --by cc`
    <!-- /cc-only -->
    <!-- oc-only -->
    `node {{ORCH_REPO}}/bin/desk.mjs daemon stop` then `node {{ORCH_REPO}}/bin/desk.mjs daemon start --by oc`
    <!-- /oc-only -->
  - a live `/frood-desk` session holds the lock instead of a daemon (`watch` line without the `daemon` token): its desk
    is the driver — when its `by` matches this harness, done; when its `by` is the other harness's, stop with
    **NEEDS YOU** naming that session — an interactive desk is never stopped or taken over from here
    (`daemon stop` refuses a session owner anyway);
  - a live owner with no `by` token drives every stream — leave it alone;
  - no live driver — the `watch` line reads `stale` or `none` — and (this session launches `--stream` runs
    or `status` shows any `unhandled>0`) → start this harness's driver; without one the desk-check timer pages
    the owner every 5 minutes with nobody answering. Prefer the systemd service when it is installed but inactive
    (`systemctl --user start orchestrator-desk-daemon`); otherwise start it headless:
    <!-- cc-only -->
    `node {{ORCH_REPO}}/bin/desk.mjs daemon start --by cc`
    <!-- /cc-only -->
    <!-- oc-only -->
    `node {{ORCH_REPO}}/bin/desk.mjs daemon start --by oc`
    <!-- /oc-only -->
    Exit 3 from any `daemon start` above → a live owner holds the lock: **NEEDS YOU** naming it (the message
    says who); never `--takeover`.
  - a small ticket (an in-session worker, no `--stream`) needs no driver of its own — but still run this check:
    `unhandled>0` with no live driver is left-over work nobody drives, so start the driver (or open a `/frood-desk`)
    rather than walking past it. Say so when there is truly nothing pending and skip the rest.
- Isolated branch per the repo convention; verify the tree (`git rev-parse
  --show-toplevel`) and use absolute paths — `cd` does not hold between calls.
  Stage files by name, never blanket-add.
- **Fresh tree, proven — every ticket, every reader.** Before a worker, scout or reviewer touches
  code: `git fetch origin <base>`; in the ticket worktree `git merge-base --is-ancestor origin/<base> HEAD`
  must succeed, else (fresh, empty branch only) `git reset --hard origin/<base>`, else stop. Write the base
  into the Mandate (`base: origin/<base> @ <sha>`) and make the worker re-run the check as its FIRST step,
  stopping with `RESULT: BLOCKED: stale tree` if it fails. A fresh `--stream` worker run is also refused by
  `oc-worker` itself (exit 10, before `queued`/spawn) when the tree is stale or dirty — see the FIRST STEP
  in each Mandate, which stays as a defence for runs without `--stream`. A shared checkout is never evidence:
  scouts and reviewers read the ticket worktree or `git show origin/<base>:<path>`, and their prompts say so.
- Shell: no `head`/`tail` pipes on pwsh (use `Select-Object` or Git Bash); quote output.
- Another session's uncommitted work: stop and tell the user, do not edit around it.
- Noisy investigation goes to `scout` agents; the orchestrator's context holds
  Mandates, verdicts and receipts, not dumps. Reports are files; chat carries links.
- Token hygiene: clear between modules; no overnight scheduled-task burn.
- **Router health (every start, cheap):** run
  `node {{ORCH_REPO}}/bin/router-health.mjs --if-stale 24 --probe` and dispatch
  each role to the agent it prints (`use <agent>`); always pass the role's chain as `--fallback` so a
  model that dies mid-session re-pools itself. Pools under 15% window headroom (local ledger — see the
  routing rule) print as `low-headroom` skips, same as down pools. A role printed `NONE` is a blocker — tell the owner.
  If it prints `NEW PROVIDER: <id> …` lines, ask the owner once per provider (Claude Code
  AskUserQuestion; OpenCode numbered list): **Evaluate and add (Recommended)** — probe its strongest
  models, run the critic bake-off on the known-regression fixture, propose chain placement; the owner
  approves before any agent/chain change. **Ignore** — `router-health --decide <id> ignored`.
  **Ask later** — record nothing. Never add a provider to a chain without the owner's approval.

- **Model optimization at startup (thin wrapper over router-health):** the orchestrator session runs
  `router-health --if-stale 24 --probe`, then:
  1. **Extracts orchestrator recommendation**: when fresh (<24h), reads `~/.config/orchestrator/router-health.json` stamp file for `roles.orchestrator.use`; when probing, parses live output.
  2. **Detects current model**: OC reads `agents/orchestrator.md` frontmatter `model:`; CC documented as `unknown` (no reliable detection for root session).
  3. **Compares & recommends**: outputs `Current: <model>. Recommended: <agent> (<reason>). Apply at next session start? [Y/n]`
     - Factors: role fit, cost tier, pool health (headroom).
  4. **Interactive prompt (TTY only)**: non-TTY/headless/CI auto-defaults to `--no-optimize` (continue, record decision). `--yes` auto-accepts; `--no-optimize` skips.
  5. **Default = next session**: `Y` records "apply at next session start"; `--respawn-now` explicit opt-in for immediate re-spawn (warns about context loss).
  6. **Receipt**: records `model_optimization: { current, recommended, decision: "kept"|"switched-next"|"switched-now"|"skipped", reason, timestamp }`.
- **Router freshness (pricing):** if `**Last audited:**` in the routing rule is >14 days old, or
  `opencode models` shows a model the rule does not name, run
  `/frood-model-router-refresh` (OpenCode). New models enter a chain only through that refresh + a probe +
  owner approval — health checks never promote a model on their own.
- **Restart reconciliation (after router health, before any dispatch in a session that starts after a host
  restart):** a restart can kill the `oc-worker` wrapper while the agent lives on, and the watcher's `run-dead`
  is then a lie — dispatching on it launched a duplicate worker (incident: video-studio M2, worker-r1 → a
  worker-r2 built on that `run-dead`, 2026-11-17; it stood down only on its own uncommitted-work check). For
  every stream with a `run-dead` **newer than the last boot** (`uptime -s` / `last reboot`):
  1. **Compare worktree write activity against the death timestamp.** `node {{ORCH_REPO}}/bin/desk.mjs status`
     flags the contradiction itself — a `dead` row carrying `dead wrapper, live tree?` (`live_tree: true` under
     `--json`) means the worktree has writes newer than that `run-dead`; the same by hand is
     `find <worktree> -type f -newermt "<run-dead timestamp>"`.
  2. **Tree still changing → the agent outlived the wrapper: ADOPT, do not relaunch.** Reattach with
     `oc-worker --session <id from the run's receipt>` and let the run finish; a relaunch here is how the
     duplicate happened.
  3. **Tree silent since the death → relaunch as a new run with a resume brief** — round N+1 under the same
     ticket, `--session <id>` when the receipt has one, and the brief says what the dead run had done.
  **Never relaunch on an unverified `run-dead`:** verify (1) first — the flag, the tree, or the agent's own
  session — and only then decide (2) or (3).

## Vision Detection & Auto-Spawn (Module 6)

Before step 1 of every ticket, the orchestrator detects images in the task/prompt and auto-enables vision mode:

**Image detection rules:**
- File paths with extensions: `.png`, `.jpg`, `.jpeg`, `.gif`, `.webp`, `.bmp`, `.svg`
- Base64 data URLs starting with `data:image/`
- HTTP/HTTPS URLs with image MIME type (HEAD request to verify, max 5s timeout)
- Size cap: 10MB per image, 50MB total
- Privacy guard: reject file paths outside workspace; reject untrusted URLs (configurable allowlist)
- Cost guard: log image count/size in receipt

**Behavior:**
- If images detected AND `--no-vision` not set: auto-add `--vision` to worker/critic `oc-worker` dispatches
- User can override with `--no-vision` flag or explicit agent choice
- Receipt records: `vision: { images_detected: N, total_bytes: X, agents_spawned: [...] }`

**Opt-out:** `--no-vision` flag disables auto-detection and vision mode for the entire run.

---

## EGM (Elephant-Goldfish) review — where it improves the outcome

EGM artifact directory: .opencode/plans (or docs/designs for committed specs)

**The gate is mechanical, not a judgment call.** For every plan module / ticket, before any
worker starts, check these triggers and record the result:

| Trigger (any one ⇒ EGM **required**) | How to check |
|---|---|
| Adds a new module, service, package, or top-level directory | new file outside existing module dirs |
| Changes a data model: schema, migration, persisted key/format, stored file layout | `prisma/`, `migrations/`, `alembic/`, models, anything written to a db or disk that existing data depends on |
| Changes a public interface: HTTP route/contract, CLI flags, exported API, webhook/event payload, config format | route files, exported signatures, docs/API |
| Touches more than 3 modules (top-level dirs under the source root) | count from the Mandate's file scope |
| Security or tenancy: auth, permissions, tenant scoping, secrets, money movement | auth/billing/wallet/permission paths |

- **Any trigger ⇒ required:** run the pre-gauntlet review below; `egm_review.status` stays
  `pending` until you approve, and no worker starts while it is `pending`.
- **No trigger ⇒ waivable**, never silently skipped: set `egm_review: { status: "waived",
  waive_reason: "<which triggers were checked and why none apply>" }` on the ticket (board JSON,
  or the Mandate's front-matter when there is no board) and say it in the receipt.
- A trigger discovered mid-ticket (e.g. the critic finds the fix must change stored data) flips
  the ticket back to `pending`: stop the loop, run EGM on the revised scope, then continue.

- **Pre-gauntlet (required tickets):** EGM review of the plan
  <!-- cc-only -->
  (`/egm:egm-review <plan>`; dispatch reviewers with `model: "haiku"` — the plugin's
  agents are `model: inherit` and would otherwise run on Opus)
  <!-- /cc-only -->
  <!-- oc-only -->
  (`/frood-egm-review <plan>`)
  <!-- /oc-only -->
  → resolve → approve before `/frood-gauntlet`. Ticket field `egm_review.status` must be
  `approved` or `waived` (with reason) before work starts.
- **Inside gauntlet (after build, before adversarial):** targeted review loop on the
  changed files (design_critic + implementation_readiness).
- **Post-ship:** drift report on `docs/designs/` when specs and code may have diverged.
- **Typical waivers:** pure bugfix with an existing spec, hotfix, test-only change — still
  recorded as `waived` with the reason. EGM is review — it never replaces the pinned test
  suite or the train. Fresh subagents are mandatory; if there is no subagent tool, stop.

## Cross-harness: peer-mail + board

Both harnesses share the peer-mail MCP (`peer_sessions`, `peer_send`, `peer_inbox`,
`peer_read`, `peer_ack`). The **board is the truth**; peer-mail only wakes a
long-lived session (e.g. "ticket X ready for review", with the report link — never
the dump). Address sessions only by exact id from `peer_sessions`. Headless workers
launched by `oc-worker` need no peer-mail: the orchestrator reads their report file.

Taking a stream from the other harness is `/frood-next <n>` plus the owner's yes; giving it back is `/frood-handback <n>`.

If Claude Code is unavailable, run this same command from OpenCode: Go Muse
orchestrates, OpenCode `worker`/`critic`/`senior` agents fill every role.

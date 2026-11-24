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
   --plan <plan> --next "<next>" --done "<one line>" --waiting "<owner items or empty>" --by cc`.  # cc-only
   --plan <plan> --next "<next>" --done "<one line>" --waiting "<owner items or empty>" --by oc`.  # oc-only
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
   Omit a line only when it would be `none` (`You:` and `Next:` are always shown).
4. Then ask the owner with these options (Claude Code: AskUserQuestion; OpenCode: a numbered list):
   - **Continue in this session (Recommended for a streamed ticket)** — its context is Mandates, verdicts and
     receipts, not dumps, and this session is the one the desk wakes, so it reports the merge itself.
   - **Fresh tab** — new tab, first message `/frood-next <stream>`; the old tab keeps its history. The escape hatch
     when the context is genuinely heavy; the handoff waits 72 h for it either way.
   - **Stop here** — the handoff waits (72 h) for a later `/frood-next`.

   Handing work to a session that does not exist yet is `/frood-ticket <repo-path> <one-line task>`: it writes the
   Mandate, the board ticket, the plan file and the stream, so the next session's `/frood-next <stream>` finds it.
   Never hand-write a ticket JSON under `.opencode/board/tickets/` — that is the case `/frood-next` cannot see.

### Dispatch in parallel

When the plan has several tickets on the board, find out which may run at once before starting any:
`node {{ORCH_REPO}}/bin/dispatch.mjs plan <plan-file|ticket-id...>` prints ordered groups. Tickets in one group are
independent (no shared file, no `depends:` line between them); groups run one after another: **group N+1 starts only when every ticket of group N is shipped**. Overlap means
serial; the check never guesses. `plan` also holds a ticket that shares a file with a ticket already in flight on the
board, or waits on an unshipped one (`held`), and lists a ticket whose `depends:` names an id not on the board
(`unknown`; fix the typo).

<!-- cc-only -->
One desktop session per ticket of the first group, each running `/frood-next <stream>` for that ticket's stream
(start it with the desktop app's session tool, or by hand). For every session, in this order:
1. `node {{ORCH_REPO}}/bin/dispatch.mjs cap` — exit 1 means the build cap is reached (default 2 building; set
   `max_parallel` in `.opencode/board/adapter.json`): start no more until a ticket reaches `ready`.
2. Start the session, then record it: `node {{ORCH_REPO}}/bin/board.mjs session <ticket> --session <sid>`
   (stored in `assignment.session`; the session's own `claim` keeps it).
3. **You write this sentence into every dispatched Mandate**, before the session starts: "Stop at `board ready`;
   never run `train depart`. The dispatcher owns the train." You own the train.

`node {{ORCH_REPO}}/bin/desk.mjs status` shows each ticket's session and stage; the dispatched streams' events arrive
through the one `watch --events`, so a single desk session handles every escalation. The train stays serial: before
departing a ticket, `dispatch.mjs cap --kind train --exclude <that ticket>` must pass (default 1: no other ticket
may be in the train), and never run two suites at once (box-wide lock).
<!-- /cc-only -->
<!-- oc-only -->
OpenCode has no desktop session tool. Run the first group's tickets serially, or launch each as the headless
`oc-worker` run of step 4 (the `WORKER_SLOTS` cap of 2 still applies; `dispatch.mjs cap` counts board tickets too).
The train stays serial.
<!-- /oc-only -->

## 4. Delegate: worker → critic loop

You are the orchestrator: you plan, write Mandates, judge, and merge. Code is written
by **worker** agents and checked by a **critic** agent. Roles, agents and models live
in `~/.config/opencode/rules/01-orchestrator-models.md` (OpenCode loads it; in Claude
Code, read it before dispatching). Spawn the named agent — never hand-type a model.

1. **Ticket + Mandate** (on the board when the repo has one, `.opencode/board/`):
   scope, files the worker may touch, pass bars, exact test command, worktree + branch,
   `report_path` and `findings_path` under `.opencode/reports/<ticket>/`.
   **One run dir = `dirname(mandate)`** (today `~/.opencode/reports/<effort>/<ticket>/`): `mandate.md`,
   `ticket.json`, `report.md`, `worker-r<N>.md` and `findings-r<N>.md` all live there. Write `ticket.json`
   once, before the first dispatch, and never change it, so `/frood-desk` can act on the run:
   `{"ticket":"<slug>","worktree":"<abs>","branch":"<name>","base":"<ref>","mandate":"<abs>","report":"<abs>","max_rounds":3,"senior_trigger":null,"repo":"<abs main checkout>","merge":"ff|train"}`.
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
   **When the repo has `.opencode/board/adapter.json`, every ticket is created and moved through
   `node {{ORCH_REPO}}/bin/board.mjs`** — `create` → `egm approve|waive` →
   `claim` → `oc-worker --ticket <id> --owner <session>` (which calls `board attach` itself) →
   `round` per worker/critic receipt → `signoff` → `gates` → `ready`. The board file, not the
   conversation, is the ticket's state; `board watch` blocks a ticket whose worker has gone quiet.
   `board ready` prints the wake-up line `READY <id> <branch> <sha> — board verify then train`, and
   that line — with the report link — is what peer-mail carries.
2. **Worker** codes in the ticket worktree and writes `report_path`.
   <!-- cc-only -->
   From Claude Code, workers run on **OpenCode** (cheap pools, not the Claude
   subscription), as a background job — one chain source: `oc-worker.mjs --role worker|worker-strong`.
   `node {{ORCH_REPO}}/bin/oc-worker.mjs --role worker --dir <worktree> --prompt <mandate.md> --report <run dir>/report.md --out <run dir>/worker-r1.md --stream <name>`
   (`--role worker-strong` for hard tickets; add `--session <id from the last receipt>` on revision rounds so the worker keeps its context — switch to the next stronger pool only after 2 rounds on one model). Quota/rate-limit errors re-pool automatically; Nvidia 429s are resumed on the same session, never skipped ahead (per-ticket: after 2 worker-nvidia drops in this run dir, worker-nvidia is left out). The Claude Code `worker` agent (Sonnet) is never an automatic fallback — use it only when every OpenCode pool, including Nvidia after its retry, is out, and the receipt states that reason.
   <!-- /cc-only -->
   <!-- oc-only -->
   From OpenCode, launch the same headless run in the background — the identical command Claude Code runs, so a desk
   in either harness follows it and a Claude Code `/frood-desk` can pick up work started here.
   `node {{ORCH_REPO}}/bin/oc-worker.mjs --role worker --dir <worktree> --prompt <mandate.md> --report <run dir>/report.md --out <run dir>/worker-r1.md --stream <name>`
   (`--role worker-strong` for hard tickets; add `--session <id from the last receipt>` on revision rounds so the worker keeps its context — switch to the next stronger pool only after 2 rounds on one model). Quota/rate-limit errors re-pool automatically; Nvidia 429s are resumed on the same session, never skipped ahead (per-ticket: after 2 worker-nvidia drops in this run dir, worker-nvidia is left out). The Claude Code `worker` agent (Sonnet) is never an automatic fallback — only when every OpenCode pool is out, and the receipt states that reason. The machine-wide `WORKER_SLOTS` cap is 2 — a third launch waits, never fails.
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
   reports it. An interactive `/frood-desk` is the fallback *you* open when the daemon cannot run — never an owner
   action item. Run the critic loop yourself only for a Claude Code `worker` agent (no stream events) or when
   the owner tells you to.
   <!-- oc-only -->
   In OpenCode, "a Claude Code `worker` agent" in that rule means an in-session `subagent` worker: no stream, so you
   run its critic loop yourself.
   <!-- /oc-only -->
3. **Critic** (read-only) reviews the diff, re-runs the tests, and replies with a
   findings document starting `VERDICT: APPROVED | CHANGES_REQUESTED`. Save that reply
   verbatim to `findings_path` (round-numbered: `findings-r<N>.md`). A receipt with
   `readonly_violation` voids that review — rerun it.
   <!-- cc-only -->
   Claude Code: `Agent(subagent_type: "critic")` (Sonnet).
   <!-- /cc-only -->
   <!-- oc-only -->
   OpenCode: `node {{ORCH_REPO}}/bin/oc-worker.mjs --agent critic --fallback critic-alt,critic-free --dir <worktree> --prompt <critic-prompt.md> --out <findings-r<N>.md>` (CmdC Haiku) — or `subagent({ agent: "critic" })` when no desk is involved.
   <!-- /oc-only -->
4. `CHANGES_REQUESTED` → send the same worker the findings file (round N+1). Max 3
   rounds; then stop for a person with all findings quoted. Never loop silently.
5. `APPROVED` → **senior** review only if the critic says `SENIOR_REVIEW: needed`, the
   diff touches a guarded path, or it took >2 rounds.
   <!-- cc-only -->
   Senior = you (Opus), one pass, blockers only.
   <!-- /cc-only -->
   <!-- oc-only -->
   Senior = `subagent({ agent: "senior" })` (CmdC Sonnet 5.5, one pass, blockers only).
   <!-- /oc-only -->
6. Board `ready` → the repo's train ships it: board the branch, start the
   departure detached (`depart-bg` — it survives this session and the
   conductor restarts a dead one), then IMMEDIATELY continue to the next
   buildable work (next ticket/mandate, next backlog item, next owner
   question). Never poll the train or sleep-wait for prod in-session; the
   shipped verification (prod sha readback) is deferred to the next session
   start or a desk event. Workers never push, merge or deploy.

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
  without one they cannot reach this session, so `--session` is required for Claude Code. Exit 3 (another harness took the stream over) or exit 4
  (another live session holds it) → stop at once with a **NEEDS YOU** card naming the holder. Never act on it,
  never take it back silently.
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
  sign-off, and this session brings it to the owner. So, for every streamed ticket:

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
  stopping with `RESULT: BLOCKED: stale tree` if it fails. A shared checkout is never evidence: scouts and
  reviewers read the ticket worktree or `git show origin/<base>:<path>`, and their prompts say so.
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
  `opencode models` shows a `commandcode/*` model the rule does not name, run
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

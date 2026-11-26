---
description: Follow every orchestrator stream from one flat session (Claude Code only)  # cc-only
description: Follow every orchestrator stream from one flat session  # oc-only
---

Follow the workstreams another session planned, one EVENT line at a time. All state is on disk
(`~/.config/orchestrator/streams/`), so `/clear` then `/frood-desk` resumes anywhere: the desk spends its context on
actions, never on stream history. Every command below is absolute so it works from any directory.

The desk does **not** switch your model: no `agent:` is set, so whatever model you have selected stays selected.
Run `node <ORCH_REPO>/bin/desk.mjs models` to see which Orchestration Desk models are available and get a
recommendation for what to switch into based on pool availability. When every desk-chain model is down, the report
lists available free fallback models (e.g. Nvidia free-only models) for graceful degradation.

This run's arguments: $ARGUMENTS

## 1. Show the streams

`node {{ORCH_REPO}}/bin/desk.mjs status`

Show it as is: a leading `watch ...` line naming the desk-watch lock owner (live or stale — a stale lock is
safe to take over, see step 2), then one line per active or parked stream (`unhandled=` counts what still needs
a decision) and one row per run.

When a daemon drives, the `watch` line names it (`daemon`, pid, log file) and a trailing
`escalations pending: N` line lists the judgment calls waiting on you. Read those first, deal with
them, resolve each with `handoff.mjs ack --resolved`. `daemon stop` seizes control (your interactive
watch takes over afterwards); `daemon start` hands back. Never `--takeover` a live daemon silently —
stop it first. When the systemd unit is enabled (`systemctl --user is-enabled orchestrator-desk-daemon`),
use `systemctl --user stop/start` instead — the supervisor restarts a SIGTERMed daemon within ~2 minutes,
so `daemon stop` cannot hold. The unit runs with `KillMode=process`: stop and restart end the daemon only, while
the critics and workers it launched keep running and report to their stream. To end those runs too, follow the
stop with `systemctl --user kill orchestrator-desk-daemon`.

## 2. Arm the watcher

<!-- cc-only -->
Start **one** `Monitor` — but only if there is work. If `status` shows no active or parked
stream with `unhandled>0`, end here: say `desk: idle — no unhandled events, ending session`
and stop. Never idle-watch an empty board.

Otherwise start the `Monitor` on:

`node {{ORCH_REPO}}/bin/desk.mjs watch --events --by cc`

It holds the desk lock and prints one line per pending event: `EVENT <stream> <key> <kind> <outcome|effective|->`
(a new watcher replays the unhandled events once; `queued` is never printed). stdout carries only EVENT lines;
diagnostics go to stderr. If it exits **3**, another desk holds a live lock and stderr names the owner (pid,
harness, session). Never take over silently.
<!-- /cc-only -->
<!-- oc-only -->
There is no `Monitor` here: block on the desk instead — but only if there is work. If
`status` shows no active or parked stream with `unhandled>0`, end here: say
`desk: idle — no unhandled events, ending session` and stop. Never idle-watch an empty board.

Otherwise one `shell` call with `timeout` **1900000** ms:

`node {{ORCH_REPO}}/bin/desk.mjs watch --events --by oc --until-event 1800`

It holds the desk lock and prints one line per pending event: `EVENT <stream> <key> <kind> <outcome|effective|->`,
then exits **0**. A new wait replays the unhandled events once, so a `/clear` loses nothing.

- **0** — handle those events (step 3), then start the wait again.
- **4** — nothing happened in 30 minutes. Say one line and start the wait again.
- **3** — another desk holds a live lock; stderr names the owner (pid, harness, session). Read the `watch ...`
  line of `status`: `live` means message that session (peer-mail) and offer
  `watch --events --by oc --until-event 1800 --takeover` — never take over a live owner silently. `stale` (owner
  gone, zombie, recycled pid, or heartbeat expired), or a session you have confirmed closed, is safe to take over:
  announce the takeover in one line, then run with `--takeover`.
<!-- /oc-only -->

## 3. Handle one event at a time

For each EVENT line:

`node {{ORCH_REPO}}/bin/desk.mjs step <stream> <key> --by cc`  # cc-only
`node {{ORCH_REPO}}/bin/desk.mjs step <stream> <key> --by oc`  # oc-only

`step` only decides (it runs no git and starts nothing). Act on its one line. It is idempotent: the decision is
stored, so replaying the key prints the stored action again until its effect exists, then `DONE <key>` — do nothing.
`DONE <key>` also covers an event of a closed ticket (its worktree was removed after the merge): the event is stale,
its acks are already written — do nothing.

Wherever a command below takes `<run>`, it is the part of the EVENT key between `run:` and `:done` (`verdict:<run>`
likewise) — a run id carries its ticket: `m6a-desk-minors/worker-r1`.

- **`HELD <stream> <holder>`** — the other harness holds this stream; do nothing with it (no ack, no critic), it
  returns after a `/frood-handback`.
- **`ACTION critic <ticket.json> <out> <findings-r<N>.md> <N>`**
  <!-- cc-only -->
  - Read `<ticket.json>` (it is small).
  - Spawn `Agent(subagent_type: "critic")` with the inputs `agents/critic.md` expects: the Mandate, the worktree,
    the base ref, the report, the round `<N>`, and the previous findings file when `<N>` is above 1.
  - Save its whole reply with Write to `<findings-r<N>.md>`.
  <!-- /cc-only -->
  <!-- oc-only -->
  - Read `<ticket.json>` (it is small).
  - Write `critic-prompt-r<N>.md` beside the ticket — 6 short lines, no flags: `Mandate:`, `Worktree:`, `Base:`,
    `Report:`, `Round: <N>`, and `Previous findings:` when `<N>` is above 1 (the paths come from `<ticket.json>`).
  - Run the critic headless so its findings never enter your context (`shell`, `background: true`):
    `node {{ORCH_REPO}}/bin/oc-worker.mjs --role critic --dir <worktree> --prompt <run dir>/critic-prompt-r<N>.md --out <findings-r<N>.md>`
  - When it notifies: exit **0** and `<findings-r<N>.md>` starts with `VERDICT:`. Anything else is not a review —
    retry once with the rest of `--role critic`'s chain (CHAINS.critic minus the failed agent), then `ESCALATE`.
  <!-- /oc-only -->
  - `node {{ORCH_REPO}}/bin/desk.mjs verdict <stream> <run> --findings <findings-r<N>.md>`
    prints `KEY verdict:<run>`: run `step` on that key. The verdict that counts is verdict-gate's `gate()`, never
    the critic's own claim.
    If an earlier verdict for `<run>` is `INVALID` and HEAD is unchanged, a corrected findings file supersedes it
    under `verdict:<run>@<n>` (carrying `replaces: <previous key>`); a non-INVALID verdict is never replaced, and
    an INVALID verdict on a moved HEAD exits 2.
- **`ACTION resume-worker <command>`** — run the printed command with `run_in_background`. If it exits **9**  # cc-only
- **`ACTION resume-worker <command>`** — run the printed command in the background (`shell`, `background: true`). If it exits **9**  # oc-only
  (`oc-worker: run <run> already queued`) that resume was already started: a no-op for the desk, not a failure.
- **`ESCALATE merge <ticket.json> <sha>`**
  - `node {{ORCH_REPO}}/bin/desk.mjs merge-check <stream> <run>` → `OK` or `FAIL <check>`.
    A `FAIL` is reported, never merged.
    `merge-check` accepts a patch-identical rebase: when HEAD moved past the reviewed sha but the ticket's patch is
    byte-for-byte identical (`git patch-id --stable` of both diff ranges match, both non-empty, reviewed sha still a
    commit) it prints `OK` plus a stderr note `desk: HEAD <h8> is a rebase of reviewed <r8> (same patch-id)`.
    Otherwise a moved HEAD still prints `FAIL head-moved`.
  - On `OK`, read the ticket's `repo` and `merge` fields. Only `merge: "ff"` means an ff-merge:
    `git -C <repo> merge --ff-only <branch>`. Then — only when `<repo>` is
    `{{ORCH_REPO}}` — run `node {{ORCH_REPO}}/bin/install.mjs` and
    `node {{ORCH_REPO}}/bin/install.mjs --check`, then remove the merged ticket worktree with
    `node {{ORCH_REPO}}/bin/wt-finish.mjs <worktree> --delete-branch` (it refuses — exit 4/5 — rather than
    remove while a non-MCP process holds it or an untracked link would make the removal unsafe).
  - `merge: "train"`, or any repo other than the orchestrator: hand the branch to that repo's train and ask the
    owner first. Never ff-merge there.
- **`ESCALATE senior <findings>`** — senior review (one pass, blockers only) before the merge.
- **`ESCALATE worktree-escape <out>`** — the worker wrote outside its worktree (oc-worker's fence). Never resume it.
  Tell the owner in one line which main-checkout paths the receipt lists under `escaped` (`restored` vs `left`) and
  point to `<out>.escaped.patch`; anything in `left` is the owner's call.
- **Any other `ESCALATE ...`** — a judgment call for the desk, or a question for the owner when the decision is
  theirs. A `FAIL` from `merge-check`, a `BLOCKED:` question, an exhausted round count: say what it is in one line
  and ask.

After each handled event, record where the stream stands:

`node {{ORCH_REPO}}/bin/handoff.mjs note --stream <stream> --next "<one line>"`

An `ESCALATE` also needs its ack resolved once it is dealt with, so a later `step` reports `DONE` instead of
re-printing it:

`node {{ORCH_REPO}}/bin/handoff.mjs ack --stream <stream> --key <key> --resolved`

**Spinner (interactive desk sessions only — the daemon has no UI):** mirror runs to
todos (Claude Code: `TodoWrite`, OpenCode: `todowrite`), one todo per active run
(`<ticket> <run-id>`, e.g. `m6a worker-r1`), exactly one `in_progress` — the run this
event just started, with its pid/model in the todo content so the spinner row is the live one.
`ACTION critic` → critic todo `in_progress`, worker todo `completed`; verdict `APPROVED` → critic `completed`, senior/merge todo `in_progress`;
`DONE <key>` → its todo `completed`. A `run-dead` under restart reconciliation
(`/frood-orchestrator` standing rules) keeps its todo `in_progress` until the tree check
decides adopt vs relaunch — never complete a run you have not verified dead. At every `note` also include one `live — <run> <elapsed> <outAge>` line from `oc-worker active` so the conversation window's last 5-line block always shows what's spinning.

## 4. Context rule

The desk never pastes worker output into its reasoning. Worker output, reports and findings are read only for an
ESCALATE that needs them. After 12 handled events, or after any event where you read more than `ticket.json`, the
findings and the plan's `## Handoff` section, finish the current event and then say exactly:

`desk: /clear then /frood-desk`

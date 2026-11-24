---
description: Continue from a stream handoff (paste into a fresh session — that IS the clear)
---

Continue the orchestrated work from a stream handoff. This is the first thing to do in this session. Every workstream
has a named stream in `~/.config/orchestrator/streams/` (`<name>.json` = the pointer, `<name>.events.jsonl` and
`<name>.acks.jsonl` = what the desk logged).

Run this as the first message of a fresh session / new tab — that fresh context IS the clear.
Do not /clear an existing session into it.

The tab title is set by the `orchestrator-handoff.js` hook to `[<stream>] <repo>: <module> — <what>` (truncated to
60 chars). This helps distinguish which stream a tab belongs to.

1. An explicit name: `$ARGUMENTS` is a stream name when it matches `^[a-z0-9][a-z0-9-]{0,39}$` and
   `~/.config/orchestrator/streams/<name>.json` exists. With a name, run
   `node {{ORCH_REPO}}/bin/handoff.mjs show --stream <name>`.
   - If its state is `parked` or `done`, say so in one line and ask the owner what to work on - do not consume it.
   - Otherwise (pending, consumed or stale) use that stream and continue at step 3 (claim it).
2. No name: run `node {{ORCH_REPO}}/bin/handoff.mjs show`.
   - Exit 0 printed one pending stream as JSON: use it and continue at step 3 (claim it).
   - Exit 1 is either no handoff or the table of every stream. Show the table and ask the owner which stream to
     continue. That is not the same as "no handoff" - never guess a stream, and never start other work first.
   - Exit 1 may also end with `unstreamed tickets in <cwd>:` - tickets on this repo's board (or hand-written files
     under `.opencode/board/tickets/`) that no stream names. Offer those alongside the streams, by id, saying which
     are `queued, not in any stream` and which are `hand-written, not on the board`. If the owner picks one:
     register it as a stream before doing anything else - steps 4-5 of `/frood-ticket` - writing the Mandate
     (`<repo>/.opencode/reports/<id>/mandate.md`) and the plan file from the ticket's content first when it is
     hand-written or has no Mandate yet, then `handoff.mjs write --stream <id> …`. Then continue at step 3 (claim it).
3. Claim the stream lease before reading the plan. The holder is the harness, not the session:
   <!-- cc-only -->
   `node {{ORCH_REPO}}/bin/handoff.mjs claim --stream <name> --by cc --session <your peer-mail session id>`
   (the id injected at session start, "your session id for the peer_* messaging tools is ..."). `--session` is
   required here: without it the desk daemon cannot mail escalations to this session and they sit unseen.
   <!-- /cc-only -->
   <!-- oc-only -->
   `node {{ORCH_REPO}}/bin/handoff.mjs claim --stream <name> --by oc --session "$OPENCODE_SESSION_ID"`
   (the `OPENCODE_SESSION_ID` environment variable of the shell tool). If `echo $OPENCODE_SESSION_ID` prints
   nothing, run the claim without `--session`.
   <!-- /oc-only -->
   - Exit 0: the stream is ours; continue at step 4.
   - Exit 3: another harness holds it. stderr is `handoff: stream <n> held by <h> (session <s|->) since <iso>`.
     Show that line and ask the owner one question: "Stream <n> is held by <h> since <t>. Take it over?" with the
     options **Take over** / **Leave it**
     <!-- cc-only -->
     (AskUserQuestion).
     <!-- /cc-only -->
     <!-- oc-only -->
     (a numbered list).
     <!-- /oc-only -->
     **Leave it** stops with the **NEEDS YOU** handoff card. Never take over without that yes. On **Take over**, run
     the same claim again with `--takeover`; then, if the previous `held_session` (from the refused line) is listed
     by `peer_sessions`, `peer_send` it: `stream <n> taken over by <h> at <iso>. Stop acting on it. Wait for a
     handback message, then run /frood-next <n>.` (`<h>` is this harness, `<iso>` the time now.)
   - Exit 4: a live session (same harness, different id) already claimed this stream. stderr is
     `handoff: stream <n> claimed by session <s> (<age> ago); re-run with --takeover to take it over`.
     Show that line and ask: "Stream <n> is claimed by session <s> since <t>. Take it over?" with options
     **Take over** / **Leave it**. **Leave it** stops with **NEEDS YOU**. On **Take over**, re-run the claim with
     `--takeover` (records `taken_from`); no peer-mail needed since it's the same harness.
   - Exit 2: usage error (often a bad `--session`). <!-- cc-only -->Fix the session id and retry once; if it
     still fails, show the error and stop.<!-- /cc-only --><!-- oc-only -->Retry the claim once without
     `--session`; if it still fails, show the error and stop.<!-- /oc-only -->
   - Exit 1: the stream is parked or done (or missing). Say so in one line and ask the owner what to work on.
   - Exit 0: name this session's tab NOW, before reading anything else — the owner tells tabs apart by title, and the default `next <stream>` title says nothing about the work.
     <!-- cc-only -->
     The `orchestrator-handoff.js` hook retitles automatically on `/frood-next`; skip this step if the tab already shows `[<stream>]`.
     <!-- /cc-only -->
     <!-- oc-only -->
     OpenCode has no title hook, so do it explicitly: `node {{ORCH_REPO}}/bin/session-title.mjs --title "[<stream>] <repo>: <module> — <what>"` (≤60 chars, plain words — the same title a stranger would need to pick this tab out of ten). Do not skip this: the 5-minute desk-check only converges titles, it does not write the first one.
     <!-- /oc-only -->
4. Read the plan file the stream names, starting with its `## Handoff` section (what is done, what is next, what is
   waiting on the owner). Then follow the `/frood-orchestrator` command's rules for the next module: router health first,
   Mandates with blast radius, the EGM gate, workers on the routed pools, paid critic sign-off, senior when triggered.
   Workers you launch with `--stream` are handed to the desk (critic, rounds, merge): launch, set the worker todo
   `in_progress`, move on — and after any wait, check this session's `peer_inbox` before saying anything about the
   ticket, because the desk daemon peer-mails you the merge/senior/sign-off instead of paging the owner. Do not
   review or merge them here, and never tell the owner to watch `/frood-desk` or `desk.mjs status`.
5. Run `node {{ORCH_REPO}}/bin/handoff.mjs consume --stream <name> [--session <id>] [--takeover]` once you have loaded the
   plan, so a second `/frood-next` does not replay it. `consume` accepts a pending, consumed or stale stream and refuses
   `parked` and `done`; without `--stream` it works only when exactly one stream is pending. With `--session` it enforces
   the same claim rules as step 3 (exit 4 if a live session holds it; `--takeover` overrides); without `--session` it
   is byte-identical to the previous behaviour.
6. Tell the owner what you are about to do in the start card below, then do it:

   ```
   == START <stream> ==
   Doing: <plain-language outcome, ≤12 words> (<ticket or module>)
   You:   nothing | <owner items from the handoff, one line each>
   Desk:  <live run> (pid <P>) → desk daemon → peer-mail to this session → I report to you | none
   ```

   `Doing:` names the work the way you would explain it to someone with no context — no ticket slugs, shas, or harness jargon as the message; those go in parentheses after it. `You:` stays an action list.
   `Desk:` names the live run and who wakes whom, so the owner knows the merge reaches them through this
   session and not by watching `desk.mjs status`: `worker-r1 (pid 3356015) → desk daemon → peer-mail to this
   session → I report to you`. With no live run, omit the line.

   Mention items waiting on the owner once. Block on them only when the next step needs them (then stop with a
   **NEEDS YOU** handoff card). Every stop in this session ends with the handoff card from `/frood-orchestrator`
   ("At every module boundary").

Extra instructions from the owner (optional): $ARGUMENTS

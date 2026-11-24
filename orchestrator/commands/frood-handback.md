---
description: Hand an orchestrator stream back to the other harness
argument-hint: "<stream>"  # cc-only
---

Give a stream you took over (or currently hold) back to the other harness. Holder = harness: `cc` is Claude Code,
`oc` is OpenCode.

This run's arguments: $ARGUMENTS

1. `<stream>` = `$ARGUMENTS`. It must name an existing stream
   (`~/.config/orchestrator/streams/<stream>.json`); if not, say so and stop. Never hand back mid-dispatch: finish
   the current step or park it, and note what is in flight.
2. Replace the plan's `## Handoff` section (done with shas, next step, in-flight runs, owner items), then record it:
   `node {{ORCH_REPO}}/bin/handoff.mjs write --stream <n> --plan <plan> --next "<next>" --done "<line>" --waiting "<items>" --by cc`  # cc-only
   `node {{ORCH_REPO}}/bin/handoff.mjs write --stream <n> --plan <plan> --next "<next>" --done "<line>" --waiting "<items>" --by oc`  # oc-only
   Exit 3 means this harness does not hold the stream: stop here, say so, and restore the plan's previous
   `## Handoff` section.
3. Desk: if this harness runs a desk watcher for the stream, stop it.
   <!-- cc-only -->
   Claude Code: stop the `Monitor` task.
   <!-- /cc-only -->
   <!-- oc-only -->
   OpenCode: a `/frood-handback` cannot run while this session is blocked in `desk.mjs watch --until-event`, so the owner
   interrupts that wait first.
   <!-- /oc-only -->
   A dead watcher's lock is taken over by the other harness's `/frood-desk` without `--takeover`.
4. Release the lease to the other harness:
   `node {{ORCH_REPO}}/bin/handoff.mjs release --stream <n> --by cc --to oc`  # cc-only
   `node {{ORCH_REPO}}/bin/handoff.mjs release --stream <n> --by oc --to cc`  # oc-only
   Exit 3 means this harness does not hold the stream: say so and stop.
5. Peer-mail: take the last `kind:"takeover"` line in `~/.config/orchestrator/streams/<n>.lease.jsonl` whose `to` is
   THIS harness; its `from_session` is the session that lost the stream. If there is no such line, skip the
   `peer_send`. If that id is listed by `peer_sessions`, `peer_send` it:
   `stream <n> handed back to oc: run /frood-next <n> (and /frood-desk if you run the desk); add --takeover if a live session still holds it. New tab, first message: /frood-next <n>.`  # cc-only
   `stream <n> handed back to cc: run /frood-next <n> (and /frood-desk if you run the desk); add --takeover if a live session still holds it. Continue in that session, or open a new tab with first message /frood-next <n>.`  # oc-only
   No broadcast.
6. End with the handoff card from `/frood-orchestrator` ("At every module boundary"), status **READY**, with
   `You:   nothing — new tab, first message: /frood-next <n>`  # cc-only
   `You:   nothing — the Claude Code session that held it continues (else new tab: /frood-next <n>)`  # oc-only

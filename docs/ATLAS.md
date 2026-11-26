# docs/ATLAS.md — Frood checked map

Screen → route → handler → outcome-function map for Frood.

This is reference documentation infrastructure (M6). It is checked by
`tests/test_atlas.py`, which resolves every route, handler, sibling-trap, and
topic-file reference below. A handler rename must be reflected in the same
commit's `docs/ATLAS.md` — a renamed symbol without a same-commit map update is
a critic major.

Each section is one route group:

```
### <route>
handler: <function>
decides: <outcome>
sibling traps: <related routes>
topic: docs/atlas/<topic>.md   # optional
```

## Auth

### /api/login
handler: dashboard.server.create_app.login
decides: session created or rejected (401/429 on bad credentials or rate limit)
sibling traps: /api/logout, /api/setup/status, /api/setup/complete
topic: docs/atlas/routes.md

### /api/logout
handler: dashboard.server.create_app.logout
decides: auth cookie cleared
sibling traps: /api/login, /api/settings/password
topic: docs/atlas/routes.md

### /api/settings/password
handler: dashboard.server.create_app.change_password
decides: password changed or rejected (wrong current password / too short)
sibling traps: /api/login, /api/logout
topic: docs/atlas/routes.md

## Setup

### /api/setup/status
handler: dashboard.server.create_app.setup_status
decides: first-run setup needed yes/no
sibling traps: /api/setup/complete, /api/login
topic: docs/atlas/routes.md

### /api/setup/complete
handler: dashboard.server.create_app.setup_complete
decides: setup completed and JWT issued, or rejected (already configured)
sibling traps: /api/setup/status, /api/login
topic: docs/atlas/routes.md

## Health

### /health
handler: dashboard.server.create_app.health_check
decides: liveness status (ok)
sibling traps: /api/health, /api/setup/status
topic: docs/atlas/routes.md

### /api/health
handler: dashboard.server.create_app.health_detail
decides: detailed metrics (task/websocket counts) for authenticated users
sibling traps: /health, /api/setup/status
topic: docs/atlas/routes.md

## Memory

### /api/memory/search
handler: dashboard.server.create_app.memory_search
decides: search results (semantic Qdrant or keyword MEMORY.md fallback)
sibling traps: /api/memory/stats, /api/learnings/retrieve, /api/knowledge/learn
topic: docs/atlas/routes.md

### /api/memory/stats
handler: dashboard.server.create_app.memory_stats
decides: 24h memory pipeline activity counters
sibling traps: /api/memory/search, /api/activity
topic: docs/atlas/routes.md

### /api/knowledge/learn
handler: dashboard.server.create_app.extract_knowledge
decides: structured learnings extracted from session context (or empty list)
sibling traps: /api/learnings/retrieve, /api/memory/search, /api/effectiveness/learn
topic: docs/atlas/routes.md

### /api/learnings/retrieve
handler: dashboard.server.create_app.retrieve_learnings
decides: non-quarantined past learnings filtered by task type and score gate
sibling traps: /api/knowledge/learn, /api/memory/search, /api/recommendations/retrieve
topic: docs/atlas/routes.md

### /api/consolidate/trigger
handler: dashboard.server.create_app.trigger_consolidation
decides: memory dedup consolidation run stats (or Qdrant unavailable)
sibling traps: /api/memory/stats, /api/settings/memory/{collection}
topic: docs/atlas/routes.md

## Effectiveness & recommendations

### /api/effectiveness/record
handler: dashboard.server.create_app.record_effectiveness
decides: tool invocation recorded for MCP tool tracking
sibling traps: /api/effectiveness/stats, /api/recommendations/retrieve
topic: docs/atlas/routes.md

### /api/effectiveness/stats
handler: dashboard.server.create_app.effectiveness_stats
decides: aggregated effectiveness statistics per tool/task type
sibling traps: /api/effectiveness/record, /api/recommendations/retrieve
topic: docs/atlas/routes.md

### /api/effectiveness/learn
handler: dashboard.server.create_app.record_learning
decides: learning persisted to HISTORY.md with quarantine fields
sibling traps: /api/learnings/retrieve, /api/knowledge/learn, /api/effectiveness/record
topic: docs/atlas/routes.md

### /api/recommendations/retrieve
handler: dashboard.server.create_app.retrieve_recommendations
decides: top-N tool recommendations for a task type
sibling traps: /api/effectiveness/stats, /api/learnings/retrieve
topic: docs/atlas/routes.md

## LLM proxy

### /llm/chat/completions
handler: dashboard.server.create_app.llm_chat_completions
decides: chat completion text (capability-ranked provider routing / passthrough)
sibling traps: /llm/v1/messages, /v1/messages, /llm/models, /llm/config
topic: docs/atlas/routes.md

### /llm/v1/chat/completions
handler: dashboard.server.create_app.llm_chat_completions
decides: chat completion text (same handler as /llm/chat/completions)
sibling traps: /llm/chat/completions, /llm/v1/messages, /llm/models
topic: docs/atlas/routes.md

### /llm/v1/messages
handler: dashboard.server.create_app.llm_messages
decides: Anthropic-compatible message response
sibling traps: /llm/chat/completions, /v1/messages, /llm/models
topic: docs/atlas/routes.md

### /v1/messages
handler: dashboard.server.create_app.anthropic_sdk_proxy
decides: Anthropic SDK-compatible message response (root proxy path)
sibling traps: /llm/v1/messages, /llm/chat/completions, /llm/models
topic: docs/atlas/routes.md

### /llm/models
handler: dashboard.server.create_app.llm_models
decides: available model list enumerated from PROVIDER_MODELS
sibling traps: /llm/chat/completions, /llm/config, /llm/embeddings
topic: docs/atlas/routes.md

### /llm/v1/models
handler: dashboard.server.create_app.llm_models
decides: available model list (same handler as /llm/models)
sibling traps: /llm/models, /llm/chat/completions
topic: docs/atlas/routes.md

### /llm/embeddings
handler: dashboard.server.create_app.llm_embeddings
decides: OpenAI-compatible embeddings vector (NVIDIA or OpenAI passthrough)
sibling traps: /llm/models, /llm/chat/completions
topic: docs/atlas/routes.md

### /llm/v1/embeddings
handler: dashboard.server.create_app.llm_embeddings
decides: embeddings vector (same handler as /llm/embeddings)
sibling traps: /llm/embeddings, /llm/models
topic: docs/atlas/routes.md

### /llm/config
handler: dashboard.server.create_app.llm_config
decides: LLM proxy configuration (endpoint, default model, available models)
sibling traps: /llm/models, /llm/chat/completions
topic: docs/atlas/routes.md

## Providers

### /api/providers
handler: dashboard.server.create_app.list_providers
decides: provider registry note (removed in v2.0 MCP pivot)
sibling traps: /api/settings/provider-status, /api/models/health
topic: docs/atlas/routes.md

### /api/settings/provider-status
handler: dashboard.server.create_app.get_provider_status
decides: live connectivity status per configured LLM provider
sibling traps: /api/providers, /api/models/health, /api/settings/openrouter-status
topic: docs/atlas/routes.md

### /api/models/health
handler: dashboard.server.create_app.get_model_health
decides: model health check results and provider health summary
sibling traps: /api/settings/provider-status, /api/providers
topic: docs/atlas/routes.md

### /api/models/health-check
handler: dashboard.server.create_app.trigger_health_check
decides: stub — model catalog removed in v3.0
sibling traps: /api/models/health, /api/settings/provider-status
topic: docs/atlas/routes.md

## Tools & skills

### /api/tools
handler: dashboard.server.create_app.list_tools
decides: enabled/disabled tool list
sibling traps: /api/tools/{name}, /api/skills
topic: docs/atlas/routes.md

### /api/tools/{name}
handler: dashboard.server.create_app.toggle_tool
decides: tool enabled or disabled (admin only)
sibling traps: /api/tools, /api/skills/{name}
topic: docs/atlas/routes.md

### /api/skills
handler: dashboard.server.create_app.list_skills
decides: skill list with enabled state
sibling traps: /api/skills/{name}, /api/tools
topic: docs/atlas/routes.md

### /api/skills/{name}
handler: dashboard.server.create_app.toggle_skill
decides: skill enabled or disabled (admin only)
sibling traps: /api/skills, /api/tools/{name}
topic: docs/atlas/routes.md

## CLI setup

### /api/cli-setup/detect
handler: dashboard.server.create_app.cli_setup_detect
decides: installed CLIs + current wiring state report
sibling traps: /api/cli-setup/wire
topic: docs/atlas/routes.md

### /api/cli-setup/wire
handler: dashboard.server.create_app.cli_setup_wire
decides: named CLI wired or unwired
sibling traps: /api/cli-setup/detect
topic: docs/atlas/routes.md

## Settings

### /api/settings/keys
handler: dashboard.server.create_app.get_api_keys
decides: masked configurable API keys (GET) / keys updated (PUT)
sibling traps: /api/settings/env, /api/settings/provider-status
topic: docs/atlas/routes.md

### /api/settings/env
handler: dashboard.server.create_app.get_env_settings / update_env_settings
decides: editable .env settings read or hot-reloaded
sibling traps: /api/settings/keys, /api/settings/storage
topic: docs/atlas/routes.md

### /api/settings/storage
handler: dashboard.server.create_app.get_storage_status
decides: active storage backend mode and live connectivity
sibling traps: /api/settings/storage/install-packages, /api/settings/memory/{collection}
topic: docs/atlas/routes.md

### /api/settings/storage/install-packages
handler: dashboard.server.create_app.install_storage_packages
decides: missing storage packages installed (or already installed)
sibling traps: /api/settings/storage
topic: docs/atlas/routes.md

### /api/settings/memory/{collection}
handler: dashboard.server.create_app.purge_memory_collection
decides: Qdrant memory collection purged (irreversible)
sibling traps: /api/settings/storage, /api/consolidate/trigger
topic: docs/atlas/routes.md

### /api/settings/probe-models
handler: dashboard.server.create_app.probe_models_endpoint
decides: provider refresh counts per configured provider
sibling traps: /api/settings/provider-status, /api/models/health
topic: docs/atlas/routes.md

### /api/settings/openrouter-status
handler: dashboard.server.create_app.get_openrouter_status
decides: OpenRouter routing policy and account info
sibling traps: /api/settings/provider-status, /api/settings/keys
topic: docs/atlas/routes.md

### /api/settings/rlm-status
handler: dashboard.server.create_app.get_rlm_status
decides: RLM status note (removed in v2.0 MCP pivot)
sibling traps: /api/settings/provider-status
topic: docs/atlas/routes.md

## Notifications & telemetry

### /api/notifications/config
handler: dashboard.server.create_app.get_notification_config
decides: webhook URLs, events, and email recipients
sibling traps: /api/reports, /api/stats/tokens
topic: docs/atlas/routes.md

### /api/reports
handler: dashboard.server.create_app.get_reports
decides: aggregate analytics data for the Reports page
sibling traps: /api/stats/tokens, /api/activity, /api/notifications/config
topic: docs/atlas/routes.md

### /api/stats/tokens
handler: dashboard.server.create_app.get_token_stats
decides: aggregate token usage totals (currently all zero; no stats source is wired)
sibling traps: /api/reports, /api/notifications/config
topic: docs/atlas/routes.md

### /api/activity
handler: dashboard.server.create_app.get_activity
decides: recent intelligence events (last 200, newest first)
sibling traps: /api/reports, /api/memory/stats
topic: docs/atlas/routes.md

## Apps Platform

### /api/apps
handler: dashboard.server.create_app.list_apps (GET) / create_user_app (POST)
decides: app list (GET) or new app created (POST)
sibling traps: /api/apps/{app_id}*, /apps/{slug}*
topic: docs/atlas/routes.md

### /api/apps/{app_id}
handler: dashboard.server.create_app.get_app
decides: app details or 404
sibling traps: /api/apps, /api/apps/{app_id}/start
topic: docs/atlas/routes.md

### /api/apps/{app_id}/start
handler: dashboard.server.create_app.start_app
decides: app started (url + port) or error
sibling traps: /api/apps/{app_id}/stop, /api/apps/{app_id}/restart
topic: docs/atlas/routes.md

### /api/apps/{app_id}/stop
handler: dashboard.server.create_app.stop_app
decides: app stopped or error
sibling traps: /api/apps/{app_id}/start, /api/apps/{app_id}/restart
topic: docs/atlas/routes.md

### /api/apps/{app_id}/restart
handler: dashboard.server.create_app.restart_app
decides: app restarted (url) or error
sibling traps: /api/apps/{app_id}/start, /api/apps/{app_id}/stop
topic: docs/atlas/routes.md

### /api/apps/{app_id} (DELETE)
handler: dashboard.server.create_app.delete_app
decides: app permanently deleted or error
sibling traps: /api/apps/{app_id}, /api/apps
topic: docs/atlas/routes.md

### /api/apps/{app_id}/logs
handler: dashboard.server.create_app.get_app_logs
decides: app log output
sibling traps: /api/apps/{app_id}/health, /api/apps/{app_id}
topic: docs/atlas/routes.md

### /api/apps/{app_id}/health
handler: dashboard.server.create_app.app_health
decides: app health check result
sibling traps: /api/apps/{app_id}/logs, /api/apps/{app_id}
topic: docs/atlas/routes.md

### /api/apps/{app_id}/update
handler: dashboard.server.create_app.update_app
decides: 410 — task queue removed in v3.0
sibling traps: /api/apps/{app_id}/settings, /api/apps/{app_id}
topic: docs/atlas/routes.md

### /api/apps/{app_id}/settings
handler: dashboard.server.create_app.update_app_settings
decides: app mode/auth/visibility updated or 404/400
sibling traps: /api/apps/{app_id}/update, /api/apps/{app_id}
topic: docs/atlas/routes.md

### /apps/{slug}/{path:path}
handler: dashboard.server.create_app.proxy_app_with_path
decides: request proxied to running app's local port (or 404/502/503)
sibling traps: /apps/{slug}/, /apps/{slug}, /api/apps/{app_id}
topic: docs/atlas/routes.md

### /apps/{slug}/
handler: dashboard.server.create_app.proxy_app_root
decides: app root (index.html) served or proxied
sibling traps: /apps/{slug}, /apps/{slug}/{path:path}
topic: docs/atlas/routes.md

### /apps/{slug}
handler: dashboard.server.create_app.proxy_app_redirect
decides: redirect to trailing slash
sibling traps: /apps/{slug}/, /apps/{slug}/{path:path}
topic: docs/atlas/routes.md

## WebSocket

### /ws
handler: dashboard.server.create_app.websocket_endpoint
decides: authenticated real-time event broadcast (token-gated)
sibling traps: /api/activity, /api/login
topic: docs/atlas/routes.md

## Orchestrator (CLI tools, not routes)

### orchestrator parallel dispatch
handler: orchestrator/bin/dispatch.mjs (plan: independence check, cap: concurrency limit); orchestrator/bin/board.mjs session (assignment.session); orchestrator/bin/desk.mjs status (ticketSessions)
decides: which board tickets may run in their own sessions at once (both edit a file, one edits a file the other's blast-radius caller names, or `depends:` means serial; two callers of the same file do not — dispatch.mjs overlapOf/fileSetsOf), which are held (in flight, or queue priority: an older queued EGM-cleared ticket within adapter `queue_priority_hours`, default 48), and whether the build cap leaves room — build cap may be `auto` (slots.mjs)

### dispatch.mjs status + statusline segment
handler: orchestrator/bin/dispatch.mjs status (board tickets in active stages, live oc-worker runs from `~/.config/orchestrator/runs`, stream last-event ages from `~/.config/orchestrator/streams`); orchestrator/hooks/cross-harness-statusline.js (the `--line` segment on statusline line 2 and the `dispatch` key in `--json`)
decides: a single ≤120-char status line showing `building`/`ready` counts and live worker runs (dead pid or output past its idle limit marked `⚠`), computed in-process by importing `dispatch.mjs` — never spawning node; absent when no `.opencode/board/` is found. Contract: `--line` and `--json` are stable for a later desktop-app poller.

### dispatch-status desktop mod
handler: orchestrator/mods/dispatch-status/hooks/register.ts (session.start polls `dispatch.mjs status --line --session <$.session.id()>` every 10 s and sets `$.ui.status`); orchestrator/bin/dispatch.mjs heldBy (the `--session` filter: assignment.session/owner, or the ticket-named stream's held_session); orchestrator/manifest.json `mods` kind → `~/.claude/frood-mods`
decides: the status entry (desktop footer / terminal line) showing only the tickets this session holds; empty → no entry. Loaded in every session only when `CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json` env names `~/.claude/frood-mods/dispatch-status`.

### desk: critic round floor, verdict replacement, patch-identical rebase
handler: orchestrator/bin/desk.mjs criticRound() (run-done ACTION critic round floor), orchestrator/bin/desk.mjs latestVerdict() (newest verdict:<run>@<n> reader), orchestrator/bin/desk.mjs cmdMergeCheck() (head-moved rule with patch-identical rebase acceptance)
decides: the critic round for a re-dispatched worker run (max of resume acks, worker-r<N> id, findings-r<N> on disk, board rounds.length), whether a corrected INVALID verdict is superseded at verdict:<run>@<n>, and whether a HEAD that moved past reviewed_sha is still a mergeable rebase (same patch-id). Step stays pure (file reads only, no git, no spawn); handoff.mjs append/read semantics are unchanged.
topic: docs/atlas/desk.md

### oc-worker load-based slots
handler: orchestrator/bin/slots.mjs (readSample, slotConfig, allowedSlots); orchestrator/bin/oc-worker.mjs acquireSlot; desk.mjs status header
decides: how many workers may start now — fixed `WORKER_SLOTS=N` or dynamic `WORKER_SLOTS_MIN`..`WORKER_SLOTS_MAX` (2..6) from 5-minute machine load (/proc/pressure/cpu, /proc/loadavg, /proc/meminfo) via ORCH_PROC_ROOT; burst guard admits at most one slot above the floor per 60 s; opencode children nicened to 10 on non-Windows; decision log slot-decisions.log

### oc-worker cc-worker backend (headless Claude Code)
handler: orchestrator/bin/oc-worker.mjs (`--agent cc-worker`: claudeBin, summarizeClaude, ccCapReader, runChain pool key `cc-worker`); orchestrator/bin/pool-health.mjs (classify, ccResetMs, CC_POOL); orchestrator/tests/fixtures/fake-claude.mjs
decides: `--agent cc-worker` spawns `claude -p` (ORCH_CLAUDE_BIN) instead of opencode, same receipt/--stream/timeout/signal path; at most `cc.max_workers` (usage-limits.json via usage.mjs loadLimits, default 1) run machine-wide on `provider-cc-<i>` slot dirs; a Claude usage limit is `quota` (pool-health `cc-worker` down until the message's reset, else 5 h) and a 429 is `rate-limit`, so `--fallback` moves on. Not in any CHAINS role (routing is a later module)

### oc-worker --role worker chain
handler: orchestrator/bin/oc-worker.mjs --role <name> (expands to --agent/--fallback from CHAINS); orchestrator/bin/chains.mjs (CHAINS source, re-exported by orchestrator/bin/router-health.mjs)
decides: which OpenCode agent pool to dispatch first for a worker run; worker-nvidia first for routine tickets, Nvidia 429 resumes on the same session, two stalled/timeout receipts drop worker-nvidia for the ticket
- idle session woken by peer-mail → hooks/peer-mail-wake.js (Claude Code Stop hook, asyncRewake; polls the mailbox and exits 2 to wake the idle model)

### oc-worker dispatch preflight
handler: orchestrator/bin/oc-worker.mjs (--stream ticket.json preflight, caller-cwd --out/--report resolution); orchestrator/bin/board.mjs create (blast-radius test: refusal)
decides: refused at dispatch/create time rather than late: --stream without dirname(--out)/ticket.json exits 2 before spawning; relative --report resolves against caller cwd; board create refuses a non-"unchanged" blast-radius bullet with no test: path

### oc-worker: timed-out worker whose work landed counts done
handler: orchestrator/bin/oc-worker.mjs (HEAD captured at run start; `landed` receipt field on timeout/stalled when HEAD moved + clean tree + DONE report); orchestrator/bin/outcome.mjs workerOutcome; orchestrator/bin/board.mjs workerOutcome copy (identical behaviour)
decides: a timeout/stalled receipt whose HEAD moved, tree is clean, and --report says DONE is treated as done, so the desk dispatches the critic instead of resume-worker and board round accepts findings

### oc-worker: visible slot waits, earlier nudges, hung tool calls
handler: orchestrator/bin/oc-worker.mjs (acquireSlot + acquireProviderSlot stderr wait lines naming holders; registry `state: "queued"`; receipt `queued_s`; `--idle-min`/`--resume` defaults 6/3 for `*-nvidia` agents; a stall with exactly one live descendant older than the idle window kills that tool child, restarts the clock, and names it in the next nudge)
decides: worker looks hung / waiting for a slot → oc-worker acquireSlot + idle defaults; Nvidia stalls caught at 6 min and nudged up to 3 times; hung tool child killed instead of opencode

### frood-learn per-run opencode join
handler: bin/frood-learn.mjs (perRunOpencodeFindings: readStreamEvents queued/run-done → opencode.db session_message + session_part)
decides: start delay, after-kill activity and long tool calls per run; why a worker timed out / kept working

### frood-learn Claude Code child review
handler: bin/frood-learn.mjs (readClaudeCodeJSONL: user lines, custom-title title, denied tool_results → parsed.denials; analyzeSessionData prompt counting; reviewChild blocked-actions findings)
decides: whether a user line is a typed prompt (text present) or tool_result-only (not counted); the session title (last custom-title, else desktop metadata title for a local_ child); which tool calls were denied by the permission classifier, and board/handoff writes severity high with the fix named
sibling traps: frood-learn per-run opencode join
trap: a `user` line holding only tool_results is not a prompt

### orchestrator handoff write
handler: orchestrator/bin/handoff.mjs writeStream
decides: a write by the claim holder keeps the claim (refreshing claim.at, keeping consumed_at) unless `--release`; every other write clears claim and consumed_at; lease keys (held_by, …) always untouched

### session-pressure notice
handler: orchestrator/bin/desk-check.mjs main() → orchestrator/bin/session-pressure.mjs measure()/level()/shouldNotify()
decides: session-pressure level (ok/warn/critical) from /proc/meminfo, /proc/loadavg and process counts; a notify-send is sent when the level rises or every 60 min while warn-or-above, never on ok, and skipped when ORCH_NO_NOTIFY=1

### desk orphan notice
handler: orchestrator/bin/orphan.mjs `streamOrphaned` decides "orphaned / waiting on you"; orchestrator/bin/orphan-notice.mjs `launchPlan` decides what the button opens
decides: an idle holder session is "waiting on you" (notice text + `Open session` → resume the holder), not "no live session"; a holder gone or unheld keeps today's "no live session" → "Resolve in new session"; escalations whose board ticket is `closed`/`shipped` are filtered out
sibling traps: orchestrator/bin/desk.mjs (holder paging, sweepOrphans, pruneOrphanLedger, status), orchestrator/bin/launch-config.mjs ({session} substitution)
trap: an idle Claude Code holder is alive but unreachable by peer-mail, so the page is right to fire but its text must say "waiting on you", not "no live session"

### Claude plan-usage snapshots
handler: orchestrator/bin/cc-usage.mjs (normalizeApp, normalizeStatusline, store, importStatusline; CLI snapshot/latest)
decides: the normalized Claude Code 5-hour / weekly / Fable usage record and which snapshot is the latest (newest `at` wins across sources `app` and `statusline`); history in `<orchDir()>/cc-usage.jsonl` pruned past 8 weeks
sibling traps: orchestrator/bin/desk-check.mjs (main imports the statusline sidecar each tick, silently), orchestrator/hooks/cross-harness-statusline.js (writes ~/.claude/.harness-cc.json; not wired until the owner adds `statusLine`)

## Release train

### ops/train.sh step 2 (pinned tests)
handler: ops/train.sh
decides: which tests the train runs for a ticket (python convention → board ticket blast_radius test → Mandate tests: line) or refuses it with exit 1

## How to keep this map accurate

- A handler rename is a same-commit map update: edit the `handler:` line in the
  affected `### <route>` section in the same commit as the rename.
- Adding a route: add a new `### <route>` section here, then add the route to
  `tests/test_atlas.py` expectations if it is referenced from a sibling trap.
- Removing a route: delete its section and any sibling-trap references to it,
  then re-run `tests/test_atlas.py`.

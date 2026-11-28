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
decides: Anthropic-compatible message response (gateway token required: 401 without a valid bearer or x-api-key, 503 when FROOD_GATEWAY_TOKEN is empty)
sibling traps: /llm/chat/completions, /v1/messages, /llm/models
topic: docs/atlas/routes.md

### /v1/messages
handler: dashboard.server.create_app.anthropic_sdk_proxy
decides: Anthropic SDK-compatible message response, root proxy path (gateway token required: 401 without a valid bearer or x-api-key, 503 when FROOD_GATEWAY_TOKEN is empty)
sibling traps: /llm/v1/messages, /llm/chat/completions, /llm/models
topic: docs/atlas/routes.md

### /llm/models
handler: dashboard.server.create_app.llm_models
decides: available model list enumerated from PROVIDER_MODELS (gateway token required: 401 without a valid bearer or x-api-key, 503 when FROOD_GATEWAY_TOKEN is empty)
sibling traps: /llm/chat/completions, /llm/config, /llm/embeddings
topic: docs/atlas/routes.md

### /llm/v1/models
handler: dashboard.server.create_app.llm_models
decides: available model list, same handler as /llm/models (gateway token required: 401 without a valid bearer or x-api-key, 503 when FROOD_GATEWAY_TOKEN is empty)
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

## Claude Code gateway (/gw passthrough to OpenCode Go)

### /gw/v1/messages
handler: dashboard.gateway.build_gateway_router
decides: routed to Go upstream (route table dashboard.gateway.build_route_table) or refused (auth dashboard.gateway.check_gateway_auth, claude-id block, loopback gates)
sibling traps: /gw/v1/models, /llm/v1/messages, /v1/messages, /llm/v1/models
topic: docs/atlas/routes.md

### /gw/v1/models
handler: dashboard.gateway.build_gateway_router
decides: routed Go model list (same route table and auth as /gw/v1/messages)
sibling traps: /gw/v1/messages, /llm/v1/models, /llm/models
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

### /api/cc/pace
handler: dashboard.server.create_app.get_cc_pace
decides: read-only Claude Code subscription pace (state, weekly/projected/5-hour %) via core.cc_pace.read_pace; admin only
sibling traps: /api/settings/provider-status
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
decides: which board tickets may run in their own sessions at once (both edit a file, one edits a file the other's blast-radius caller names, or `depends:` means serial; two callers of the same file do not — dispatch.mjs overlapOf/fileSetsOf), which are held (in flight, or queue priority: an older queued EGM-cleared ticket within adapter `queue_priority_hours`, default 48), and whether the build cap leaves room — build cap may be `auto` (slots.mjs); exact shared files named in adapter `merge_friendly` (default `docs/ATLAS.md`) never serialise when both tickets name the exact file, and a blast-radius test outside the ticket's scope is run-only and does not count
trap: merge-friendly skips only the edit-vs-edit check; a glob or directory scope over the file (e.g. `docs/**`, `docs`) and a caller naming it still conflict; a textual merge conflict stops the merge (keep both sections, re-run gates); gates run on the ticket branch, not the merged tree, so a semantic clash between two atlas edits shows on the next ticket's atlas test

### dispatch.mjs status + statusline segment
handler: orchestrator/bin/dispatch.mjs status (board tickets in active stages, live oc-worker runs from `~/.config/orchestrator/runs`, stream last-event ages from `~/.config/orchestrator/streams`); orchestrator/hooks/cross-harness-statusline.js (the `--line` segment on statusline line 2 and the `dispatch` key in `--json`)
decides: a single ≤120-char status line showing `building`/`ready` counts and live worker runs (dead pid or output past its idle limit marked `⚠`), computed in-process by importing `dispatch.mjs` — never spawning node; absent when no `.opencode/board/` is found. Contract: `--line` and `--json` are stable for a later desktop-app poller.

### dispatch-status desktop mod
handler: orchestrator/mods/dispatch-status/hooks/register.ts (session.start polls `dispatch.mjs status --line --session <$.session.id()>` every 10 s and sets `$.ui.status`); orchestrator/bin/dispatch.mjs heldBy (the `--session` filter: assignment.session/owner, or the ticket-named stream's held_session); orchestrator/manifest.json `mods` kind → `~/.claude/frood-mods`
decides: the status entry (desktop footer / terminal line) showing only the tickets this session holds; empty → no entry. Loaded in every session only when `CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json` env names `~/.claude/frood-mods/dispatch-status`.

### desk: critic round floor, verdict replacement, patch-identical rebase
handler: orchestrator/bin/desk.mjs boardRounds() (board counted/lap/has reader, mirrors board.mjs ~:436-438 and ~:994-996), orchestrator/bin/desk.mjs criticRound() (run-done ACTION critic round floor), orchestrator/bin/desk.mjs latestVerdict() (newest verdict:<run>@<n> reader), orchestrator/bin/desk.mjs cmdMergeCheck() (head-moved rule with patch-identical rebase acceptance), orchestrator/bin/desk.mjs isWorkerAgent() (`/^(cc-)?worker/`: what decideStep, the CHANGES_REQUESTED resume and criticReviewedRun count as a worker run — worker, worker-<pool> and cc-worker; never a critic), orchestrator/bin/desk.mjs isCriticAgent() (`/^(cc-)?critic/`: the handleEvent run-done dispatch to verdictFlow and the sweepVerdicts round scan — critic, critic-<pool> and cc-critic), orchestrator/bin/desk.mjs criticFreeFromReceipt() and orchestrator/bin/board.mjs criticFree() (critic free-ness, design B5)
decides: the critic round for a re-dispatched worker run (max of resume acks, worker-r<N> id, findings-r<N> on disk, board lap), whether a corrected INVALID verdict is superseded at verdict:<run>@<n>, and whether a HEAD that moved past reviewed_sha is still a mergeable rebase (same patch-id). A cc-worker run-done gets the same ACTION critic as any worker, and its CHANGES_REQUESTED resumes `--agent cc-worker --session <its session>`; a timed-out/dropped cc-worker escalates (only worker-nvidia/worker-free auto-resume). A cc-critic run-done is verdicted like a critic's (never stepped, so never `ESCALATE agent-cc-critic`). Free-ness: any `cc-*` receipt agent is paid (`free: false`, `free_source: agent:<agent>`, model = the receipt's or null) BEFORE the model lookup in both desk and board — a cc agent has no OpenCode pin, so the lookup would find nothing and fail closed to free; OpenCode receipts keep `*-free` agent → free, unresolvable → free/unknown. Step stays pure (file reads only, no git, no spawn); handoff.mjs append/read semantics are unchanged. Identity checks compare process starts with sameStart: runIsLive, the handoff lock-owner check and wt-finish's killHolder treat a pid whose current start is within 3 s of the recorded one as the same process, so lstart skew never marks a live run or lock dead; more than 3 s off is still recycled/dead.
topic: docs/atlas/desk.md

### scope fence (a worker's diff vs its ticket scope)
handler: orchestrator/bin/scope-check.mjs checkScope() (git diff --name-only <from>..<sha> against the ticket's --scope, where <from> is the newest merge-base of the branch with the adapter base ref or its local branch when that merge-base is a descendant of base_sha, else base_sha itself; plus the hard deny list .claude/plans/** and .opencode/**; matchAny() lives here and board.mjs imports it back); callers orchestrator/bin/board.mjs cmdCreate()/cmdScope()/cmdRound()/cmdReady() and orchestrator/bin/desk.mjs doCritic()
decides: whether a worker's committed diff may land — a path outside --scope or on the deny list records the round as CHANGES_REQUESTED even when the critic approved, refuses ready at the signed-off sha, is refused at create, and is sent back to the worker by the desk without spawning a paid critic; board.mjs scope amends a queued/working ticket's scope with the create-time checks, a senior-reason union and EGM-trigger rules. A done round whose findings file gates INVALID (no VERDICT line, or no BLAST RADIUS entries) is refused before that fence and before the round cap — exit 1, nothing written, the round is neither counted nor blocked — and round is re-run once the critic's reply is saved verbatim.
topic: docs/atlas/desk.md

### board: sweep liveness and the ready senior rule
handler: orchestrator/bin/board.mjs liveWorker() (ps start vs assignment.worker.started via sameStart, 3 s tolerance) and orchestrator/bin/board.mjs cmdReady() (senior rule: a paid senior or human signoff, or --senior-skip "<reason>" when every live senior reason starts with critic:)
decides: a live worker whose ps start drifted 1-3 s stays live (more than 3 s is a recycled pid -> missed sweep); `ready` refuses without a paid senior/human signoff unless `--senior-skip` is given and every senior reason starts with `critic:` (reason >=20 chars), recording `senior.skipped.{by,reason,at,sha}`; a round recompute clears `skipped`. Guarded-path and counted-rounds reasons can never be skipped.

### board: recomputeSenior diffs from the scope fence's merge-base
handler: orchestrator/bin/board.mjs recomputeSenior() (diffFrom(wt, t.base_sha, "HEAD", adapter.base), with diffFrom exported from orchestrator/bin/scope-check.mjs; the declared scope's guarded paths via seniorFor() are unchanged)
decides: guarded-path senior reasons come from the diff between the newest accepted merge-base of the branch with the adapter base ref (else base_sha itself) and HEAD, so guarded paths the base gained after base_sha no longer force senior on a branch that merged or rebased onto it; the ticket's own guarded-path edits, including a merge conflict resolution that touches one, still add `guarded path: <p>`; scope-based, critic and counted-rounds reasons unchanged

### oc-worker load-based slots
handler: orchestrator/bin/slots.mjs (readSample, slotConfig, allowedSlots); orchestrator/bin/oc-worker.mjs acquireSlot; desk.mjs status header
decides: how many workers may start now — fixed `WORKER_SLOTS=N` or dynamic `WORKER_SLOTS_MIN`..`WORKER_SLOTS_MAX` (2..10) from 5-minute machine load (/proc/pressure/cpu, /proc/loadavg, /proc/meminfo) via ORCH_PROC_ROOT; burst guard admits at most one slot above the floor per 20 s; opencode children nicened to 10 on non-Windows; decision log slot-decisions.log; the shared clear-state.json next to the slots holds machine-wide clear-since hysteresis so one process's not-clear resets everyone

### oc-worker cc-worker backend (headless Claude Code)
handler: orchestrator/bin/oc-worker.mjs (`--agent cc-worker | cc-worker-strong | cc-critic | cc-senior`: ccModels, isCcAgent, isCcReader, ccSlotKey, ccModelFor, ccToolArgs, capReader, ccReaderWaitMin, CcSlotTimeout, claudeBin, CC_SETTINGS, summarizeClaude, detachRun, runChain pool key = the agent name); orchestrator/bin/pool-health.mjs (classify, ccResetMs, CC_PREFIX, isCcPool, markGroupDown, isDown, markUp); orchestrator/bin/oc-worker.mjs gateFree(); orchestrator/tests/fixtures/fake-claude.mjs; orchestrator/tests/oc-worker-cc-roles.test.mjs
decides: any key of `cc.models` (usage-limits.json via usage.mjs loadLimits, merged over {cc-worker: sonnet, cc-worker-strong: opus, cc-critic: opus, cc-senior: fable}; only `cc-` keys) spawns `claude -p` (ORCH_CLAUDE_BIN) instead of opencode, same receipt/--stream/timeout/signal path; model = cc.models[agent] (first-hop --model wins), cc-senior runs opus while the launch's one pace read says `fable.state: over` (detached child inherits `fable_over` via ORCH_PACE_DECISION). Writers (cc-worker, cc-worker-strong) keep the cc-worker argv; readers (cc-critic, cc-senior = cc agent matching READONLY_AGENT_RE `^(cc-)?(critic|senior|scout|explorer)`) get `--tools Read,Grep,Glob,Bash --allowedTools Bash --disallowedTools Edit,Write,NotebookEdit`, no acceptEdits, the read-only guard and the verdict gate (VERDICT_AGENT_RE). Slots: writers at most `cc.max_workers` (default 1) on `provider-cc-<i>`, readers at most `cc.max_readers` (default 1) on `provider-ccread-<i>` (not `cc-read`: providerHeld matches the `provider-cc-` prefix), both read by capReader; a reader waiting `cc.reader_wait_min` (default 10) throws CcSlotTimeout and runChain skips to the next agent (no attempt used; receipt `notes` + hop reason `cc-slot-timeout: ...`). A Claude usage limit is `quota` (until the message's reset, else 5 h) and a 429 is `rate-limit`, so `--fallback` moves on; the cc agents are ONE pool group: runChain markGroupDown marks every cc.models key, isDown on a cc-* key is true while its own key is down or another cc-* key holds a live `quota`/`rate-limit` mark (trap: a `dropped`/`provider-error` mark holds down only its own key, never the group); markUp on a cc key clears its own key and the other cc-* marks, but runChain passes `{startedAt}` (the hop's start) and a group mark whose `since` is after it stays (trap: another run hit the limit while this one answered); markUp without startedAt (router-health) clears the whole group as before. A lone reader whose only hop was a slot timeout ends with receipt `exit: "cc-slot-timeout"` (status 6; outcome.mjs/board.mjs workerOutcome map it to `no_pool` like `no-healthy-pool`). The verdict gate's free is gateFree(): a cc agent is paid explicitly. Hook-free: argv carries `--settings {"disableAllHooks":true}` (CC_SETTINGS; never `--bare`, it refuses OAuth) and the child env PEER_WAKE_MAX_MIN=0. Survives its launcher: detachRun re-spawns oc-worker in a new session (ORCH_DETACHED_CHILD=1, stderr `<out>.detached.log`, stdout `<out>.detached.out`), the launcher relays output + exit code and a SIGTERM/INT/HUP to it exits 143/130/129 without touching the run; `--no-detach` runs in process, `--detach` opts OpenCode agents in. No `result` event (timeout/kill): tokens from assistant message.usage, one per message id. The cc agents are not in any CHAINS role: the pace policy routes them (A4, PACE_POLICY in orchestrator/bin/pace-read.mjs, see 'oc-worker --role worker chain'); the desk and board treat them as above (A3b).
trap: a cc reader gets only the short pointer prompt from `claude -p`, so its role contract comes from orchestrator/bin/oc-worker.mjs `ccContract`: the body (frontmatter stripped) of `<ORCH_HOME or home>/.claude/agents/<role>.md` (cc-critic → critic.md, cc-senior → senior.md), written to `<out>.contract.md` and passed as `--append-system-prompt-file` right after `--settings` (before the variadic `--tools`); a missing or empty file throws CcNoContract before the slot and runChain skips the hop (reason + receipt note `cc-no-contract: <file>`, no attempt), never a contract-less reader; readers also get a read-only fence footer instead of `footer()`'s "Create and edit files"; writers' argv is unchanged

### oc-worker --role worker chain
handler: orchestrator/bin/oc-worker.mjs --role <name> (expands to --agent/--fallback from CHAINS); orchestrator/bin/chains.mjs (CHAINS source, re-exported by orchestrator/bin/router-health.mjs)
decides: which OpenCode agent pool to dispatch first for a worker run; worker-nvidia first for routine tickets, Nvidia 429 resumes on the same session, two stalled/timeout receipts drop worker-nvidia for the ticket; then the pace prepend (orchestrator/bin/pace-read.mjs readPace/paceChain, one read per launch): an `under` pace puts the role's cc agent first per the role table PACE_POLICY (worker → cc-worker, worker-strong → cc-worker-strong, critic → cc-critic, senior → cc-senior unless `fable.state` is `over`; scout and orchestrator never), after the Nvidia drop rule, never twice; `--session` never prepends (the session pins the backend: desk.mjs resume-worker must not hand an OpenCode session to `claude --resume`); a detached child gets the launcher's chain via ORCH_PACE_DECISION; every receipt carries `cc_pace` {state, weekly, projected, at, prepended, role, shadow} (`role` = the --role, null for --agent)
- desk critic: orchestrator/bin/desk.mjs launches the critic with `--role critic`, so it gets cc-critic on `under` with no desk change; its critic retry (`chainFor("critic")`) is unpaced on purpose
- session routing: `--role <r> --session <id>` (r in PACE_POLICY) with an id not starting `ses_` is a Claude session → chain [<r's cc agent>, today's chain] in any pace state (e.g. `--role critic` → cc-critic) (no pace decision, `prepended` false); a `ses_` id keeps today's chain
- vision: orchestrator/bin/oc-worker.mjs filterVisionChain keeps cc-worker (Claude reads images with Read); runChain's first hop reuses `a` (session, --model) only when chain[0] is `a.agent`, so a filtered-out first agent never runs under the next agent's pool key
- idle session woken by peer-mail → hooks/peer-mail-wake.js (Claude Code Stop hook, asyncRewake; polls the mailbox and exits 2 to wake the idle model)

### oc-worker dispatch preflight
handler: orchestrator/bin/oc-worker.mjs (--stream ticket.json preflight, caller-cwd --out/--report resolution); orchestrator/bin/board.mjs create (blast-radius test: refusal)
decides: refused at dispatch/create time rather than late: --stream without dirname(--out)/ticket.json exits 2 before spawning; relative --report resolves against caller cwd; board create refuses a non-"unchanged" blast-radius bullet with no test: path; an `origin/-…` base is refused with exit 10 before any git call

### oc-worker: timed-out worker whose work landed counts done
handler: orchestrator/bin/oc-worker.mjs (HEAD captured at run start; `landed` receipt field on timeout/stalled when HEAD moved + clean tree + DONE report); orchestrator/bin/outcome.mjs workerOutcome; orchestrator/bin/board.mjs workerOutcome copy (identical behaviour)
decides: a timeout/stalled receipt whose HEAD moved, tree is clean, and --report says DONE is treated as done, so the desk dispatches the critic instead of resume-worker and board round accepts findings

### oc-worker: visible slot waits, earlier nudges, hung tool calls
handler: orchestrator/bin/oc-worker.mjs (acquireSlot + acquireProviderSlot stderr wait lines naming holders; registry `state: "queued"`; receipt `queued_s`; `--idle-min`/`--resume` defaults 6/3 for `*-nvidia` agents; a stall with exactly one live descendant older than the idle window kills that tool child, restarts the clock, and names it in the next nudge; host sleep pushes `effectiveDeadline` later by the slept gap minus the 5 s tick via the exported `sleepGapMs` helper and re-arms the timer (capped at 2 h total, receipt `slept_ms`); writer (non-read-only) prompts get a small-edit footer line; an output-token truncation is its own resume reason `truncated` and the resume message adds a split-your-edits line)
decides: worker looks hung / waiting for a slot → oc-worker acquireSlot + idle defaults; Nvidia stalls caught at 6 min and nudged up to 3 times; host sleep does not count against the deadline (capped extension) and is recorded as `slept_ms`; hung tool child killed instead of opencode; a truncated response resumes with a split-the-edit nudge; a signal during a slot wait releases held slots and exits 143/130/129

### oc-worker: sleep inhibitor during runs
handler: orchestrator/bin/oc-worker.mjs (runWorker: while slots are held a systemd inhibitor `systemd-inhibit --what=idle:handle-lid-switch --mode=block --who=oc-worker --why="worker run <title>" sleep <timeout+grace+5min>` is spawned detached and its pid released in the run's `finally`, signal handlers, and on a setup error too; skipped on Windows/macOS and with ORCH_NO_INHIBIT=1; a missing `systemd-inhibit` (or any failed spawn) warns once on stderr and the run continues)
decides: idle and lid-switch sleep are blocked only while a run is active; UPower battery-critical suspend and logind `sleep` requests from other tools are not inhibited

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
handler: orchestrator/bin/orphan.mjs `streamOrphaned` decides "orphaned / waiting on you" (plus `resolvePeerSession` host-id mapping and `parentSession` liveness for the nested-parent fork); orchestrator/bin/orphan-notice.mjs `launchPlan` decides what the button opens
decides: an idle holder session is "waiting on you" (notice text + `Open session` → resume the holder), not "no live session"; a holder gone or unheld keeps today's "no live session" → "Resolve in new session"; escalations whose board ticket is `closed`/`shipped` are filtered out; a stream held by a nested session with a live parent wakes the parent (`desk: [nested <stream>]` mail, `parent:<stream>:<held_at>` ledger in desk.mjs `pageOrphanOrParent`) instead of paging the owner; handled escalations close with `desk.mjs resolve` (`cmdResolve`, up to one resolved `RESOLVED <note>` ack per key), and a decided ESCALATE on a closed/shipped ticket steps as `STALE ticket-closed` and prints `DONE <key>` instead of replaying
sibling traps: orchestrator/bin/desk.mjs (holder paging, `pageOrphanOrParent`, `cmdResolve`, sweepOrphans, pruneOrphanLedger, status), orchestrator/bin/launch-config.mjs ({session} substitution)
trap: an idle Claude Code holder is alive but unreachable by peer-mail, so the page is right to fire but its text must say "waiting on you", not "no live session"

### desk session-driven guard
handler: orchestrator/bin/desk.mjs sessionDriven() (the act-layer guard; callers actOn, verdictFlow and sweepVerdicts), orchestrator/bin/desk.mjs doCritic() and the critic -alt retry (findings-hashed refusal), orchestrator/bin/desk.mjs doResume() and doCritic() (board-final refusal)
decides: whether the desk acts on a run a live session drives — a run whose ticket.json has `"driver": "session"` or whose board ticket has a native-critic round returns `session-driven` (no spawn, no ack) instead of ACTION critic / resume-worker / merge; a run whose board ticket already hashed the target findings file refuses with `findings-hashed` (one page, no write); a run whose board ticket is ready/shipped/closed or signed off returns `board-final` (no spawn, no page); a live held_session or assignment.session alone never stops the desk
topic: docs/atlas/desk.md

### Claude plan-usage snapshots
handler: orchestrator/bin/cc-usage.mjs (normalizeApp, normalizeStatusline, store, importStatusline; CLI snapshot/latest)
decides: the normalized Claude Code 5-hour / weekly / Fable usage record and which snapshot is the latest (newest `at` wins across sources `app` and `statusline`); history in `<orchDir()>/cc-usage.jsonl` pruned past 8 weeks
sibling traps: orchestrator/bin/desk-check.mjs (main imports the statusline sidecar each tick, silently), orchestrator/hooks/cross-harness-statusline.js (writes ~/.claude/.harness-cc.json; not wired until the owner adds `statusLine`)

### Claude weekly pace (cc-pace)
handler: orchestrator/bin/cc-pace.mjs (`paceState` pure model, `reserve`, `projected`, `statusLine`, `ledgerShadow`; CLI `[status] [--json]`)
decides: the pace state off / unknown / over / on / under from the cc-usage snapshots (newest `at` is current; recent slope over the last 24 h of the same weekly window when it spans >= 4 h), config `usage-limits.json` `cc` over defaults; last state for hysteresis in `<orchDir()>/cc-pace-state.json`
trap: `status` must print exactly one line <= 100 chars with no leading `pace` word and exit 0 for every state, because workers-view prints `pace: <first stdout line>`; `ORCH_NO_PACE=1` maps to `off`; `unknown`/`off` overwrite cc-pace-state.json too, so the `under` hysteresis memory restarts after a stale or disabled run (deliberate: fails toward the stricter 80 ceiling); routing reads it through orchestrator/bin/pace-read.mjs (child process, 10 s timeout, failure = `unknown`): oc-worker `--role <r>` puts r's cc agent (PACE_POLICY) first on `under` (see 'oc-worker --role worker chain'), and router-health prints the `pace:` line, so both also rewrite cc-pace-state.json; `status --json` (only) adds `line` (the exact text line) and `ledger` (shadow, cc-pacing-v2 A2: `ledgerShadow` gives `{k, rms, pairs, unmetered, scanned_at, nowcast_weekly, ledger_rate}` from the cc-ledger state read with `loadState`, or `null` with no ledger, `k` null, `scanned_at` older than `cc.ledger.fresh_minutes` (30) or no usable weekly/at); `nowcast_weekly = max(weekly, weekly + k·w(since at))`, `ledger_rate = k·w(24 h)/24`; the ledger NEVER changes the state, routing, the text line or cc-pace-state.json (`cc.ledger.mode` is always `shadow` until A5), and `status` never scans; receipts carry it as orchestrator/bin/pace-read.mjs `ccPaceRecord` `shadow: {nowcast_weekly, ledger_rate} | null` (a detached child re-records the launcher's `shadow`)

### Claude transcript ledger (cc-ledger)
handler: orchestrator/bin/cc-ledger.mjs (`scan` incremental read of `*.jsonl` under `projectsDir()` at depth <= 3, `parseLine`, `familyOf`, `weighted`, `bucketOf`, `prune`, `summary`, `fit`, `backtest`; CLI `scan [--budget-ms N] [--json]`, `summary [--hours N] [--json]`, `fit [--json]`, `backtest [--json]`; snapshots via orchestrator/bin/cc-usage.mjs `readHistory`)
decides: which transcript lines count (object `message.usage`, string `message.id`, model not `<synthetic>`, parseable `timestamp`; else `skipped`), the family (first of fable/opus/sonnet/haiku in the model, else other), weighted tokens per 10-minute UTC bucket with weights from `usage-limits.json` `cc.ledger.weights`; state `<orchDir()>/cc-ledger.json` holds only file offsets (sha1 key), per-id counts and buckets, pruned past 8 weeks; `fit` decides k (weekly % per weighted token) by least squares through the origin over snapshot pairs (consecutive by `at`, same `weekly.resets_at` after rounding to the minute as cc-pace does, 0.5-12 h apart, Δpct >= 0, ending in the last 14 days; Δw = Σ bucket w with start in [at₁, at₂)), valid only with >= 3 pairs, ΣΔt >= 6 h and ΣΔw > 0 (else `k: null`), plus `rms`, signed `unmetered` %/h and family `mix`; `backtest` walks forward (s_i = the latest earlier snapshot in the window >= 2 h before s_j, k fitted only on pairs ending at or before s_i) and reports `n`, `mae`, `max_err`, `under_predict` (count of predictions below the actual)
trap: one message id repeats across lines and scans; the stored per-id usage is subtracted before the new line is added (last line wins), so a rescan from 0 (file shrank or mtime went back) is idempotent; a same-size rewrite with a newer mtime is NOT rescanned; a partial last line stays unconsumed; `--budget-ms` stops between lines and reports `partial`: a positive budget reads at least one line per run, `0` reads nothing; an open/read error on one file is counted in `errors`, leaves that file's stored entry unchanged and the scan continues and saves; before reading from a non-zero offset the byte at `offset - 1` must be `\n`, else the file was rewritten (to a size >= the offset) and is rescanned from 0; changing the weights re-weights history: bucket `w` is recomputed from the raw counts on every save, and `fit`/`backtest` ignore the stored `w` and recompute it with the current weights, so k always matches the weights in force (a weights change moves k, not the fit quality); `fit` pairs are consecutive snapshots, so snapshots denser than 30 min give no pairs; the ledger is kept fresh by orchestrator/bin/desk-check.mjs `ledgerTick` (one in-process `scan({budgetMs: 5000})` per desk-check tick, silent, never changes output or exit code), which is what keeps cc-pace's 30-minute shadow freshness window satisfied

### router-health pace line
handler: orchestrator/bin/router-health.mjs CLI block (readPace + cc-pace statusLine, read before the `--if-stale` early return; `--decide` never reads it)
decides: text mode's first stdout line is `pace: <cc-pace status line>` on both the fresh `--if-stale` skip and the full run; `over` adds the `pace: OVER — conserve: …` line after it, then `pace: OVER — critic and senior via oc-worker --role, not Agent(critic|senior) unless guarded`; `under` changes only the worker, worker-strong, critic and senior lines to `use cc-<role> (pace UNDER), fallback <agent>` (router-health `pacePrefixFor`; the senior line ends ` (not for guarded paths)`: guarded-path senior review stays the in-session Fable senior), except a cc agent that pool-health isDown (then today's line; a cc `quota`/`rate-limit` mark holds all four) and senior while `fable.state` is `over`; `--json` adds a top-level `pace` key, never written to the router-health.json stamp
trap: goldens orchestrator/tests/fixtures/router-health-golden/ (captured before M4) must match after the pace line, so any other output change breaks orchestrator/tests/pace-routing.test.mjs

### desk status pace line
handler: orchestrator/bin/desk.mjs `cmdStatus` (readPace + cc-pace statusLine, read once per `status` call)
decides: text mode's first stdout line is `pace: <cc-pace status line>`, before the watch line, omitted when the state is `off`; `--json` adds a top-level `pace` key, absent on `off`; a failed read prints `pace: UNKNOWN (pace read failed: …)` and status still exits 0
trap: reuses orchestrator/bin/pace-read.mjs's single child process (10 s timeout, never throws) — spawn nothing new; existing status tests in orchestrator/tests/desk.test.mjs pin `ORCH_NO_PACE=1` so the watch line stays first there; pace cases live in orchestrator/tests/desk-pace.test.mjs

### Claude reset advisor (cc-pace advise)
handler: orchestrator/bin/cc-pace.mjs (`adviseState` pure, `effectiveDeadline`, `dueNotifications`, `activeTickets`, `adviseTick`; CLI `advise [--json] [--notify]`, `reset-used full|fable|none`)
decides: when to press the full / fable plan resets from `usage-limits.json` `cc.resets` (expiry warnings at 14 d / 72 h / 24 h / late against the effective deadline = the last weekly reset when the expiry falls < 24 h after it; `press-full` and `press-fable` on a fresh snapshot, fable only with a queued/working board ticket); a > 20-point weekly fall inside one window (`detectDrop`: the LAST fall, re-baselined after each) pauses `press-full` and asks until an ack clears it (`dropAcked`: any `reset-used` ack, including `none`, written at or after `drop.before_at`, the snapshot just before the fall, because the fall only shows in the snapshot after the press); notify memory (24 h per advice id via session-pressure `shouldNotify`) and the acks in `<orchDir()>/cc-advise-state.json`
sibling traps: orchestrator/bin/desk-check.mjs (main runs one silent `adviseTick` right after the statusline import), orchestrator/bin/session-pressure.mjs (`shouldNotify` 4th param `intervalMs`, default 60 min)
trap: advise only, Frood never presses a reset; `reset-used full|fable` is the one writer of `usage-limits.json` (first entry of the kind with count > 0 decremented, rest of the file kept, exit 2 and untouched when none has count > 0); `reset-used none` only appends an ack (a false alarm, no count spent); the tick walks the board only when a reset is live, writes cc-advise-state.json only when it changed, and re-reads `acks` before writing so a concurrent `reset-used` ack survives; `status` / no-arg never runs the advisor, so the workers-view `pace:` line is unchanged; snapshot `resets_at` carries ms jitter, so weekly windows are compared after rounding to the minute

### Live worker view (headless runs)
handler: orchestrator/bin/workers-view.mjs (text/--json/--html [--watch]; joins `oc-worker active --json` to board tickets on `assignment.worker` pid/out_path, never the title); orchestrator/mods/workers-panel/hooks/register.tsx (the `/workers` pane, polls the CLI every 15 s only while open)
decides: which headless worker run belongs to which ticket, its oc-worker state (names copied verbatim), `NO LIVE RUN` for a working ticket with no live run, and held reasons from `dispatch.mjs plan`; 9 s budget, a failing child blanks only its section
sibling traps: the pane loads only when `CLAUDE_CODE_PLUGIN_DIRS` in `~/.claude/settings.json` env names `~/.claude/frood-mods/workers-panel`; the `pace:` line is the first stdout line of `bin/cc-pace.mjs` run with no arguments ('Claude weekly pace' section), skipped when that file is absent

### desk daemon systemd units
handler: orchestrator/ops/systemd/orchestrator-desk-daemon.service; orchestrator/ops/systemd/orchestrator-desk-check.service; orchestrator/ops/systemd/install.mjs
decides: install.mjs fills @PATH@ at install time (node's directory first, then opencode and claude directories when found, mise shims, then system dirs, de-duplicated and existing-only) and both service templates carry `Environment=PATH=@PATH@`, so the desk daemon and check launched by systemd --user can spawn opencode and claude despite systemd's default user PATH

## Release train

### ops/train.sh step 2 (pinned tests)
handler: ops/train.sh
decides: which tests the train runs for a ticket (python convention → board ticket blast_radius test → Mandate tests: line) or refuses it with exit 1

## Workstation (Linux)

### workstation priority guard
handler: orchestrator/ops/workstation/agent-priority.mjs runPass (systemd user service, 15 s loop with an interruptible sleep — SIGTERM/SIGINT exit 0 within 2 s; --once)
decides: which agent process trees are reniced to nice>=10 per thread — never lowers a nice value, never touches a non-agent tree, excludes the Claude desktop UI; paused/resumed is printed once per pause transition; each spiking pass logs the top-8 CPU consumers (agent tree and ~/projects only; vault paths redacted) to <stateDir>/spikes.jsonl (rotated at LOG_MAX to .1)
sibling traps: oc-worker load-based slots

### box-wide suite lock
handler: orchestrator/ops/workstation/suite-lock.sh suite_lock_acquire / suite_lock_release
decides: one pinned full suite at a time across every repo sharing one box-wide SUITE_LOCK_ROOT queue (arrival-order, heartbeat, two-read stale break, token-checked release); `suite_lock_acquire` fails fast (return 2, ERROR line) when the lock root cannot be placed (unset SUITE_LOCK_ROOT/HOME and no passwd home, or an unwritable root); the Makefile test recipe traps TERM/INT to kill its pytest child and release the lock (exit 143/130); every acquire/release/break/skip is appended to $SUITE_LOCK_DIR/history.jsonl (rotated at 1 MiB to .1)

## How to keep this map accurate

- A handler rename is a same-commit map update: edit the `handler:` line in the
  affected `### <route>` section in the same commit as the rename.
- Adding a route: add a new `### <route>` section here, then add the route to
  `tests/test_atlas.py` expectations if it is referenced from a sibling trap.
- Removing a route: delete its section and any sibling-trap references to it,
  then re-run `tests/test_atlas.py`.

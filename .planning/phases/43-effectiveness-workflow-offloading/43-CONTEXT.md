# Phase 43: Effectiveness-Driven Workflow Offloading - Context

**Gathered:** 2026-04-05 (assumptions mode)
**Status:** Ready for planning

<domain>
## Phase Boundary

Detect when agents repeat the same tool pattern 3+ times, suggest creating an N8N workflow, and auto-create it on confirmation. Integrates with existing EffectivenessStore. This phase handles detection, suggestion, and creation — NOT routing (Phase 44).

</domain>

<decisions>
## Implementation Decisions

### Pattern Detection
- **D-01:** New `tool_sequences` table in effectiveness.db: `(id, agent_id, task_type, tool_sequence TEXT JSON, execution_count INT, first_seen REAL, last_seen REAL, fingerprint TEXT UNIQUE, status TEXT DEFAULT 'active')`
- **D-02:** Pattern = ordered list of tool names executed in one task, fingerprinted with MD5 of `json.dumps(tool_names)` for dedup, grouped by agent_id + task_type
- **D-03:** Accumulate tool names in ToolRegistry.execute() per-task context. On task end (task_context.end_task()), flush the sequence to `tool_sequences` table with upsert (increment execution_count if fingerprint exists)
- **D-04:** Threshold: 3+ executions of the same fingerprint triggers a suggestion. Configurable via `N8N_PATTERN_THRESHOLD` env var (default 3)

### Effectiveness Integration
- **D-05:** Hook into existing ToolRegistry.execute() (tools/registry.py:131-148) — after the effectiveness.record() call, also append tool_name to a task-scoped accumulator
- **D-06:** Task-scoped accumulator stored in task_context module-level dict: `_current_task_tools: dict[str, list[str]]` keyed by task_id
- **D-07:** On task_context.end_task(), call new `effectiveness_store.record_sequence(agent_id, task_type, tool_names)` to flush and check threshold
- **D-08:** Token savings estimated heuristically: `execution_count * 1000` tokens (average agent task cost). No dependency on spend_history backport

### Suggestion Mechanism
- **D-09:** Agent prompt injection in agent_runtime.py `_build_prompt()` — query patterns with execution_count >= threshold, inject suggestion text before task execution
- **D-10:** Suggestion format: "Pattern '{tool1 → tool2 → tool3}' has repeated {N} times. Estimated savings: ~{N*1000} tokens. Use n8n_create_workflow to automate this."
- **D-11:** New `workflow_suggestions` table in effectiveness.db: `(id, agent_id, task_type, fingerprint TEXT, tool_sequence TEXT JSON, execution_count INT, tokens_saved_estimate INT, suggested_at REAL, status TEXT DEFAULT 'pending')` — status enum: pending, accepted, dismissed, created
- **D-12:** No dashboard panel in this phase — prompt injection only. Dashboard visualization is deferred

### Auto-Creation Flow
- **D-13:** When agent calls `n8n_create_workflow` in response to a suggestion, store the mapping in new `workflow_mappings` table: `(id, agent_id, fingerprint TEXT, workflow_id TEXT, webhook_url TEXT, template TEXT, created_at REAL, last_triggered REAL, trigger_count INT DEFAULT 0, status TEXT DEFAULT 'active')`
- **D-14:** Template selection heuristic: if tool sequence contains http_client/web_fetch → `webhook_to_multi_step`; if contains data_tool/content_analyzer → `webhook_to_transform`; default → `webhook_to_http`
- **D-15:** Auto-generated workflow name: `"Agent42: {agent_id} - {task_type} automation"` with webhook path `"agent42-{fingerprint[:12]}"`
- **D-16:** Config setting `N8N_AUTO_CREATE_WORKFLOWS` (bool, default false) — when true, agent doesn't need confirmation, workflow is created automatically on threshold hit

### Configuration
- **D-17:** Add to Settings dataclass: `n8n_pattern_threshold: int = 3`, `n8n_auto_create_workflows: bool = False`
- **D-18:** Env vars: `N8N_PATTERN_THRESHOLD=3`, `N8N_AUTO_CREATE_WORKFLOWS=false`
- **D-19:** Add to .env.example with documentation

### Claude's Discretion
- Exact SQL query optimization for pattern detection
- Whether to use a background asyncio task or synchronous check for threshold
- Error handling and retry logic for failed workflow creation attempts
- How to handle patterns that don't map well to N8N (non-HTTP tool chains)

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Effectiveness system
- `memory/effectiveness.py` — EffectivenessStore class, record() method (lines 142-175), get_recommendations() query pattern (lines 267-304), table schemas (lines 52-140)
- `tools/registry.py` — ToolRegistry.execute() hook for effectiveness recording (lines 87-150)

### Task context
- `core/task_context.py` — begin_task()/end_task() lifecycle (lines 71-104)

### N8N tools (Phase 42)
- `tools/n8n_workflow.py` — N8nWorkflowTool API (list, trigger, status, output)
- `tools/n8n_create_workflow.py` — N8nCreateWorkflowTool execute() (lines 249-346), template loading (lines 152-173), DANGEROUS_NODE_TYPES (lines 30-38)
- `tools/n8n_templates/*.json` — Template files (webhook_to_http, webhook_to_transform, webhook_to_multi_step)

### Agent runtime
- `core/agent_runtime.py` — _build_prompt() (lines 72-95) where N8N guidance is injected
- `core/config.py` — Settings dataclass (add new fields after n8n_allow_code_nodes)

### Prior phase context
- `.planning/phases/42-n8n-workflow-integration/42-CONTEXT.md` — Phase 42 decisions (D-01 through D-23)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `EffectivenessStore.record()` — async fire-and-forget pattern for writing tool data
- `EffectivenessStore.get_recommendations()` — GROUP BY query pattern for aggregating tool stats
- `ToolRegistry.execute()` — existing hook point after every tool call
- `task_context.end_task()` — lifecycle hook for flushing accumulated data
- `n8n_create_workflow` tool — complete workflow generation + deployment API

### Established Patterns
- All DB tables in effectiveness.db use `_ensure_db()` lazy initialization
- Async fire-and-forget via `asyncio.create_task()` for non-blocking writes
- Config follows frozen dataclass + from_env() + .env.example triple
- Agent prompt injection via `_build_prompt()` in agent_runtime.py

### Integration Points
- `tools/registry.py:131-148` — where tool accumulation hooks into existing execute()
- `core/task_context.py:88-92` — where end_task() triggers sequence flush
- `core/agent_runtime.py:72-95` — where suggestions inject into agent prompts
- `core/config.py` — where new settings fields go
- `memory/effectiveness.py:52-140` — where new tables are created

</code_context>

<specifics>
## Specific Ideas

- Primary use case: agents repeatedly calling http_client + data_tool for the same API integration → one N8N workflow replaces the entire chain
- Token savings should be visible and trackable — even heuristic estimates help justify the system
- The suggestion should feel like a helpful optimization, not a nag — only suggest once per pattern, mark as "dismissed" if agent ignores it

</specifics>

<deferred>
## Deferred Ideas

- Dashboard panel for workflow suggestions — future (keep Phase 43 prompt-injection only)
- Pre-execution hook that auto-routes to existing workflows — Phase 44
- Hybrid task splitting (deterministic subtasks to N8N, reasoning to agent) — Phase 44
- spend_history integration for exact token cost tracking — backport Phase 29 work
- Workflow performance monitoring (track N8N execution success rates) — future phase

</deferred>

---

*Phase: 43-effectiveness-workflow-offloading*
*Context gathered: 2026-04-05 via assumptions mode*

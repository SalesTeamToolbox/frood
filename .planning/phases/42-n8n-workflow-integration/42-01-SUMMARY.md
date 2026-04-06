---
phase: 42-n8n-workflow-integration
plan: 01
status: complete
started: 2026-04-05
completed: 2026-04-05
---

# Plan 42-01 Summary: Config + n8n_workflow Tool

## What was built

N8nWorkflowTool — an operational tool that lets agents list, trigger, monitor, and retrieve output from N8N workflows via webhook-based execution.

## Key decisions

- **Webhook trigger (D-16 revised):** N8N has no `/workflows/{id}/execute` endpoint. Trigger fetches workflow JSON, finds webhook node, POSTs to `/webhook/{path}` with `responseMode: lastNode` for synchronous results.
- **Rate limiting:** Module-level sliding window tracker (10 calls/60s) instead of wiring into full rate_limiter.py system.
- **SSRF protection:** UrlPolicy.check() validates N8N URL before any outbound requests.

## Key files

### Created
- `tools/n8n_workflow.py` — N8nWorkflowTool with 4 actions (list, trigger, status, output)
- `tests/test_n8n_tool.py` — 20 unit tests covering all actions, graceful degradation, rate limiting

### Modified
- `core/config.py` — Added n8n_url, n8n_api_key, n8n_allow_code_nodes fields (done by Plan 02)
- `.env.example` — Added N8N section with env var docs (done by Plan 02)

## Test results

```
20 passed in 0.47s
```

## Self-Check: PASSED

- [x] N8nWorkflowTool class inherits from Tool ABC
- [x] All four actions implemented (list, trigger, status, output)
- [x] Trigger uses webhook URL pattern, not /execute endpoint
- [x] Graceful degradation when N8N not configured
- [x] Rate limiting enforced (10/min)
- [x] SSRF validation via UrlPolicy
- [x] All 20 tests pass

# Plan 28-01: Sidecar Extensions — Summary

**Status:** Complete
**Completed:** 2026-03-31

## What was built

Three new authenticated HTTP endpoints added to the Agent42 sidecar (`dashboard/sidecar.py`):

1. **POST /routing/resolve** — Returns optimal provider+model via TieredRoutingBridge for a given taskType and agentId
2. **POST /effectiveness/recommendations** — Returns top-3 tools by success rate via EffectivenessStore
3. **POST /mcp/tool** — Proxies allowlisted MCP tools via MCPRegistryAdapter with server-side allowlist enforcement

Supporting changes:
- 7 new Pydantic models in `core/sidecar_models.py` (MCPToolRequest/Response, RoutingResolveRequest/Response, EffectivenessRequest/Response, ToolEffectivenessItem)
- `mcp_tool_allowlist` config field in Settings dataclass, reading from `MCP_TOOL_ALLOWLIST` env var
- `mcp_registry` parameter added to `create_sidecar_app()` factory

## Test results

- 10 test cases in `tests/test_sidecar_mcp.py` — all passing
- Covers: auth enforcement, routing resolution, effectiveness with/without store, MCP allowlist accept/reject/disabled/no-registry

## Decisions made

- MCP tool proxy returns 403 JSONResponse for non-allowlisted tools (not 200 with error)
- Empty allowlist disables proxy entirely (returns 200 with error message)
- Graceful degradation: empty responses when stores unavailable, never crash

## Files changed

| File | Change |
|------|--------|
| `core/sidecar_models.py` | +7 Pydantic models |
| `core/config.py` | +mcp_tool_allowlist field |
| `dashboard/sidecar.py` | +3 endpoints, +mcp_registry param |
| `tests/test_sidecar_mcp.py` | New: 10 test cases |

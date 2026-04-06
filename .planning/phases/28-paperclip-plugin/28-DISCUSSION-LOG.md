# Phase 28: Paperclip Plugin - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-30
**Phase:** 28-paperclip-plugin
**Areas discussed:** Package structure, MCP tool proxy, Tool design, Lifecycle & config

---

## Package Structure

| Option | Description | Selected |
|--------|-------------|----------|
| Standalone plugins/ dir | New plugins/agent42-paperclip/ with its own Agent42Client copy. Zero coupling, matches Paperclip's plugin isolation model. ~150 lines duplicated from adapter. | ✓ |
| plugins/ dir + import from adapter | Shared Agent42Client via local path dep. Single source of truth but adds build-order dependency and Windows path risk. | |
| Co-locate in adapter package | Single package with dual entry points. Minimal dirs but conflates adapter and plugin concepts. | |

**User's choice:** Standalone plugins/ dir
**Notes:** Sidecar API is stable after Phase 27, bounded duplication risk.

---

## MCP Tool Proxy

| Option | Description | Selected |
|--------|-------------|----------|
| Sidecar endpoint + allowlist | New POST /mcp/tool endpoint with server-side curated allowlist of safe tools. Operators can expand for trusted deployments. Security in Python where sandbox lives. | ✓ |
| Sidecar endpoint + full passthrough | Same endpoint but exposes all 41+ tools. Simpler but filesystem/git/shell access from any Paperclip agent is risky. | |
| No proxy — native tools only | Skip mcp_tool_proxy entirely. Only expose memory/routing/effectiveness via existing sidecar endpoints. Revisit proxy later. | |

**User's choice:** Sidecar endpoint + allowlist
**Notes:** Security-first approach. Allowlist config-driven for flexibility.

---

## Tool Design

| Option | Description | Selected |
|--------|-------------|----------|
| CamelCase + context-injected agentId | camelCase inputSchema, plugin auto-injects agentId from execution context, simplified responses. Mapping layer handles sidecar translation. | ✓ |
| Mirror sidecar contract | Agent passes all fields including agentId, snake_case params matching sidecar exactly. Thin passthrough. | |
| CamelCase but explicit agentId | camelCase inputs + simplified responses, but agent must still pass agentId explicitly. | |

**User's choice:** CamelCase + context-injected agentId
**Notes:** Follows adapter D-13/D-14 pattern. Mapping layer exists regardless since REQUIREMENTS use different field names than sidecar.

---

## Lifecycle & Config

| Option | Description | Selected |
|--------|-------------|----------|
| Validated lifecycle | health() probes GET /sidecar/health for real status, initialize() validates config + creates shared Agent42Client, onShutdown() closes connections, apiKey uses secret-ref format. | ✓ |
| Deferred health (resilient boot) | initialize() catches sidecar failure gracefully, health() reports 'degraded' if unreachable. Good for Docker Compose ordering. | |
| Minimal lifecycle | health() returns 'ok' unconditionally, initialize() just stores config, onShutdown() is no-op. Fast but no real validation. | |

**User's choice:** Validated lifecycle
**Notes:** Success criterion requires `paperclip doctor` to pass — validated lifecycle gives meaningful health output.

---

## Claude's Discretion

- Exact MCP tool allowlist contents
- Vitest configuration and test organization
- Plugin manifest metadata (displayName, description, categories)
- Error response formatting for unreachable sidecar

## Deferred Ideas

None — discussion stayed within phase scope

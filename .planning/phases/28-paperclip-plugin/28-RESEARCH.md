# Phase 28: Paperclip Plugin - Research

**Researched:** 2026-03-31
**Domain:** Paperclip Plugin SDK (`@paperclipai/plugin-sdk` v2026.325.0), TypeScript plugin authoring, FastAPI sidecar extension
**Confidence:** HIGH — SDK type definitions inspected from installed package; all lifecycle signatures verified from dist/

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

#### Package Structure
- **D-01:** New `plugins/agent42-paperclip/` directory at repo root — standalone package, separate from the adapter at `adapters/agent42-paperclip/`
- **D-02:** Plugin has its own `Agent42Client` copy (~150 lines) and type definitions — zero coupling to the adapter package, no cross-package local path dependencies
- **D-03:** Flat `src/` layout: `index.ts` (plugin entry/exports), `worker.ts` (setup/lifecycle), `tools.ts` (tool registrations + handlers), `client.ts` (HTTP client for sidecar), `types.ts` (type definitions)
- **D-04:** Dependencies: `@paperclipai/plugin-sdk`, TypeScript, Vitest for tests — no shared deps with adapter

#### MCP Tool Proxy
- **D-05:** New `POST /mcp/tool` endpoint on the sidecar FastAPI app (`dashboard/sidecar.py`) — routes through existing tool registry with sandbox and CommandFilter enforcement
- **D-06:** Server-side curated allowlist of safe tools — operators can expand via config for trusted private deployments
- **D-07:** Allowlist is config-driven (env var or settings field), defaulting to a conservative set of safe tools (e.g., content_analyzer, data_tool, memory_tool, template_tool, scoring_tool, code_intel, dependency_audit — no filesystem/git/shell by default)
- **D-08:** Plugin exposes `mcp_tool_proxy` tool — agent calls with `{toolName, params}`, plugin POSTs to `/mcp/tool`, sidecar validates against allowlist and executes
- **D-09:** New Pydantic models in `core/sidecar_models.py`: `MCPToolRequest(tool_name, params)`, `MCPToolResponse(result, error)` — Bearer auth required on the endpoint

#### Tool Design
- **D-10:** All tool inputSchemas use camelCase field names — consistent with Paperclip conventions and existing sidecar Pydantic aliases
- **D-11:** Plugin auto-injects `agentId` and `companyId` from execution context (`ctx.agent.id` falling back to `adapterConfig.agentId`) — agents do not pass identity in tool calls
- **D-12:** `memory_recall` tool: agent passes `{query, taskType?, topK?, scoreThreshold?}` — plugin injects agentId/companyId, maps taskType to sidecar fields, returns simplified `{memories: [{text, score, source}]}`
- **D-13:** `memory_store` tool: agent passes `{content, tags?, section?}` — plugin injects agentId/companyId, maps `content` to sidecar's `text` field, returns `{stored, pointId}`
- **D-14:** `route_task` tool: agent passes `{taskType, qualityTarget?}` — plugin maps to TieredRoutingBridge fields, returns `{provider, model, tier, taskCategory}`
- **D-15:** `tool_effectiveness` tool: agent passes `{taskType}` — returns `{tools: [{name, successRate, observations}]}` (top-3 by success rate)
- **D-16:** Response shapes are simplified — strip verbose metadata, keep only fields agents need for decision-making

#### Lifecycle & Config
- **D-17:** `manifest.json` declares: `apiVersion: 1`, capabilities `["http.outbound", "agent.tools.register"]`, instanceConfigSchema with `agent42BaseUrl` (string, required), `apiKey` (string, format: secret-ref, required), `timeoutMs` (number, optional, default 10000)
- **D-18:** `health()` probes `GET /sidecar/health` (no-auth endpoint) — returns real sidecar connectivity status for `paperclip doctor`
- **D-19:** `initialize(config)` validates required config fields, creates shared `Agent42Client` instance with baseUrl + apiKey + timeout, stores as module-level singleton
- **D-20:** `onShutdown()` calls `client.destroy()` to close keep-alive HTTP connections cleanly
- **D-21:** Plugin is installation-global (one process for all companies) — per-company behavior achieved via agentId/companyId scoping in tool calls, not separate plugin instances

### Claude's Discretion
- Exact allowlist contents for MCP tool proxy (conservative safe set)
- Vitest configuration and test file organization
- Whether to use native fetch or node-fetch in the plugin's Agent42Client
- Exact manifest.json metadata (displayName, description, categories, version)
- README.md content and installation instructions
- Error response formatting when sidecar is unreachable during tool calls

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PLUG-01 | Plugin package has valid manifest.json with apiVersion 1, capability declarations, and instance config schema | SDK type `PaperclipPluginManifestV1` verified from `@paperclipai/shared`; required fields: id, apiVersion, version, displayName, description, author, categories, capabilities, entrypoints |
| PLUG-02 | Plugin registers `memory_recall` agent tool — agents query semantically relevant memories | `ctx.tools.register(name, declaration, handler)` pattern verified from SDK types; sidecar POST /memory/recall endpoint exists and tested in phase 25 |
| PLUG-03 | Plugin registers `memory_store` agent tool — agents persist learnings | Same `ctx.tools.register` pattern; sidecar POST /memory/store endpoint exists |
| PLUG-04 | Plugin registers `route_task` agent tool — agents get optimal provider+model recommendation | TieredRoutingBridge.resolve() exists; sidecar needs new HTTP endpoint (or plugin calls existing internal API via HTTP) — routed through sidecar |
| PLUG-05 | Plugin registers `tool_effectiveness` agent tool — agents query top tools by success rate | EffectivenessStore.get_recommendations() exists in `memory/effectiveness.py`; sidecar needs new endpoint |
| PLUG-06 | Plugin exposes `mcp_tool_proxy` tool — agents invoke any Agent42 MCP tool through the plugin | Requires new POST /mcp/tool sidecar endpoint (D-05 through D-09); MCP tool registry callable via MCPRegistryAdapter.call_tool() |
| PLUG-07 | Plugin implements health(), initialize(config), and onShutdown() lifecycle handlers | `definePlugin({onHealth, onShutdown, setup})` pattern verified; `initialize` is called implicitly during setup via `ctx.config.get()` — config is passed in `ctx.config`, not a separate initialize() export |
</phase_requirements>

---

## Summary

Phase 28 builds the Paperclip plugin package (`plugins/agent42-paperclip/`) — a TypeScript/Node.js process that Paperclip runs out-of-process via JSON-RPC 2.0 over stdin/stdout. The plugin SDK (`@paperclipai/plugin-sdk` v2026.325.0) is the single source of truth for the plugin API surface.

The core pattern is `definePlugin({ setup(ctx), onHealth(), onShutdown() })` with tool registration via `ctx.tools.register(name, declaration, handler)` inside `setup`. The handler receives `(params, runCtx)` where `runCtx` provides `agentId`, `companyId`, `runId`, and `projectId` — this is how the plugin obtains the agent identity for memory scoping without agents having to pass it explicitly.

The plugin makes HTTP calls back to the Agent42 sidecar using its own `Agent42Client` (copied from the adapter pattern). The sidecar requires two new endpoints for this phase: `POST /routing/resolve` (or route_task via the existing TieredRoutingBridge), `POST /effectiveness/recommendations`, and `POST /mcp/tool`. All three require Bearer auth. The MCP tool proxy endpoint is the most complex piece: it must validate tool names against a config-driven allowlist before dispatching to MCPRegistryAdapter.

**Primary recommendation:** Use `createTestHarness` from `@paperclipai/plugin-sdk/testing` for all plugin unit tests — it provides a fully-typed in-memory host context with `executeTool()`, `setConfig()`, and capability enforcement, eliminating the need to mock JSON-RPC protocol internals.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@paperclipai/plugin-sdk` | `2026.325.0` | Plugin worker API: `definePlugin`, `runWorker`, `createTestHarness`, `PluginContext` types | Official Paperclip SDK — only supported way to author plugins |
| TypeScript | `^6.0.2` | Type checking, compilation | Matches adapter package; plugin SDK ships `.d.ts` types |
| Vitest | `^4.1.2` | Test runner | Matches adapter package Vitest version exactly |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `@paperclipai/shared` | `2026.325.0` | `PaperclipPluginManifestV1`, `PluginCapability` constants (transitive dep of plugin-sdk) | Imported transitively via plugin-sdk — do not add separately |
| `zod` | `^3.24.2` | Schema validation (re-exported from plugin-sdk as `z`) | Use `z` from `@paperclipai/plugin-sdk` — no separate zod dep needed |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| native fetch | node-fetch | Prior art in adapter (D-15 Phase 27): native fetch + AbortController won for zero dependencies; repeat decision for plugin |
| `createTestHarness` | Manual JSON-RPC mocking | Harness is purpose-built for this; manual mocking requires understanding wire protocol internals |

**Installation:**
```bash
cd plugins/agent42-paperclip
npm install
```

**package.json dev dependencies:**
```json
{
  "dependencies": {
    "@paperclipai/plugin-sdk": "2026.325.0"
  },
  "devDependencies": {
    "@types/node": "^22.0.0",
    "typescript": "^6.0.2",
    "vitest": "^4.1.2"
  }
}
```

**Version verification:** Verified 2026-03-31 via `npm view @paperclipai/plugin-sdk dist-tags.latest` → `2026.325.0`. The `canary` tag is `2026.330.0-canary.7` — do not use canary.

---

## Architecture Patterns

### Recommended Project Structure
```
plugins/agent42-paperclip/
├── manifest.json          # PaperclipPluginManifestV1
├── package.json           # ESM package, "type": "module"
├── tsconfig.json          # NodeNext module resolution (mirrors adapter)
├── vitest.config.ts       # tests/**/*.test.ts pattern
├── src/
│   ├── index.ts           # re-exports manifest + default plugin export
│   ├── worker.ts          # definePlugin({ setup, onHealth, onShutdown })
│   ├── tools.ts           # registerTools(ctx, client) — all 5 ctx.tools.register calls
│   ├── client.ts          # Agent42Client (own copy — D-02)
│   └── types.ts           # TypeScript interfaces mirroring sidecar Pydantic models
└── tests/
    ├── worker.test.ts     # lifecycle: setup, onHealth, onShutdown
    ├── tools.test.ts      # all 5 tool handlers via createTestHarness.executeTool()
    └── client.test.ts     # Agent42Client HTTP contract (vi.stubGlobal fetch pattern)
```

### Pattern 1: Plugin Definition with definePlugin
**What:** All plugin behavior declared in a single `definePlugin()` call; host calls lifecycle methods on the returned object
**When to use:** Required — this is the only supported plugin authoring pattern

```typescript
// Source: /c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/plugin-sdk/dist/define-plugin.d.ts
import { definePlugin, runWorker } from "@paperclipai/plugin-sdk";
import type { PluginContext } from "@paperclipai/plugin-sdk";
import { registerTools } from "./tools.js";
import { Agent42Client } from "./client.js";

let client: Agent42Client | null = null;

const plugin = definePlugin({
  async setup(ctx: PluginContext) {
    const config = await ctx.config.get();
    client = new Agent42Client(
      config.agent42BaseUrl as string,
      config.apiKey as string,
      (config.timeoutMs as number) ?? 10_000,
    );
    registerTools(ctx, client);
  },

  async onHealth() {
    if (!client) return { status: "error", message: "Not initialized" };
    try {
      await client.health();
      return { status: "ok" };
    } catch (e) {
      return { status: "error", message: String(e) };
    }
  },

  async onShutdown() {
    client?.destroy();
    client = null;
  },
});

export default plugin;
runWorker(plugin, import.meta.url);
```

**Critical finding:** There is NO separate `initialize(config)` export. Configuration is accessed via `ctx.config.get()` inside `setup()`. The `onHealth()` method (not `health()`) is the correct lifecycle hook name in `PluginDefinition`.

### Pattern 2: Tool Registration via ctx.tools.register
**What:** Tools declared in manifest `tools[]` array are connected to handlers via `ctx.tools.register`
**When to use:** Inside `setup(ctx)` — must be synchronous after setup resolves

```typescript
// Source: /c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/plugin-sdk/dist/types.d.ts (line 600)
// Signature:
// register(
//   name: string,
//   declaration: Pick<PluginToolDeclaration, "displayName" | "description" | "parametersSchema">,
//   fn: (params: unknown, runCtx: ToolRunContext) => Promise<ToolResult>
// ): void

ctx.tools.register(
  "memory_recall",
  {
    displayName: "Recall Memories",
    description: "Retrieve semantically relevant memories for the current task",
    parametersSchema: {
      type: "object",
      properties: {
        query: { type: "string", description: "What to search for in memory" },
        taskType: { type: "string", description: "Task category for relevance filtering" },
        topK: { type: "number", description: "Max memories to return (default 5)" },
        scoreThreshold: { type: "number", description: "Minimum similarity score (default 0.25)" },
      },
      required: ["query"],
    },
  },
  async (params, runCtx) => {
    // runCtx.agentId and runCtx.companyId are injected by Paperclip
    const result = await client.memoryRecall({
      query: (params as any).query,
      agentId: runCtx.agentId,
      companyId: runCtx.companyId,
      top_k: (params as any).topK ?? 5,
      score_threshold: (params as any).scoreThreshold ?? 0.25,
    });
    return {
      content: JSON.stringify(result.memories),
      data: { memories: result.memories },
    };
  }
);
```

### Pattern 3: Manifest Structure (Verified)
**What:** JSON file declaring plugin identity, capabilities, and tool list

```json
{
  "id": "agent42.paperclip-plugin",
  "apiVersion": 1,
  "version": "1.0.0",
  "displayName": "Agent42",
  "description": "Gives Paperclip agents access to Agent42 memory recall, memory store, routing recommendations, effectiveness data, and MCP tool proxying",
  "author": "Agent42",
  "categories": ["automation"],
  "capabilities": ["http.outbound", "agent.tools.register"],
  "entrypoints": {
    "worker": "./dist/worker.js"
  },
  "instanceConfigSchema": {
    "type": "object",
    "properties": {
      "agent42BaseUrl": { "type": "string", "description": "Agent42 sidecar base URL (e.g. http://localhost:8001)" },
      "apiKey": { "type": "string", "description": "Bearer token for sidecar auth", "format": "secret-ref" },
      "timeoutMs": { "type": "number", "description": "Request timeout in ms (default 10000)", "default": 10000 }
    },
    "required": ["agent42BaseUrl", "apiKey"]
  },
  "tools": [
    { "name": "memory_recall", "displayName": "Recall Memories", "description": "...", "parametersSchema": {} },
    { "name": "memory_store", "displayName": "Store Memory", "description": "...", "parametersSchema": {} },
    { "name": "route_task", "displayName": "Get Routing Recommendation", "description": "...", "parametersSchema": {} },
    { "name": "tool_effectiveness", "displayName": "Get Tool Effectiveness", "description": "...", "parametersSchema": {} },
    { "name": "mcp_tool_proxy", "displayName": "MCP Tool Proxy", "description": "...", "parametersSchema": {} }
  ]
}
```

**Critical:** `author` field is required in `PaperclipPluginManifestV1` — the CONTEXT.md did not mention this. Omitting it will cause manifest validation failure at install.

### Pattern 4: TestHarness for Plugin Tests
**What:** In-memory host context for testing tool handlers without a live server

```typescript
// Source: /c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/plugin-sdk/dist/testing.d.ts
import { createTestHarness } from "@paperclipai/plugin-sdk";
import manifest from "../manifest.json" assert { type: "json" };

const harness = createTestHarness({
  manifest,
  config: {
    agent42BaseUrl: "http://localhost:8001",
    apiKey: "test-token",
  },
});

// Setup plugin
await plugin.definition.setup(harness.ctx);

// Execute tool and assert result
const result = await harness.executeTool("memory_recall", {
  query: "typescript async patterns",
});
expect(result.data).toHaveProperty("memories");
```

### Pattern 5: Agent42Client for Plugin (copy of adapter pattern)
**What:** Plugin's own copy of Agent42Client with additional `mcpTool()` and `routeTask()` and `toolEffectiveness()` methods

```typescript
// Additional methods needed beyond the adapter's client.ts:
async mcpTool(toolName: string, params: Record<string, unknown>): Promise<MCPToolResponse>
async routeTask(taskType: string, agentId: string, qualityTarget?: string): Promise<RoutingResponse>
async toolEffectiveness(taskType: string, agentId: string): Promise<EffectivenessResponse>
```

The adapter's client endpoints `POST /memory/recall` and `POST /memory/store` are reused unchanged.

### Pattern 6: New Sidecar Endpoints (Python side)

Three new endpoints must be added to `dashboard/sidecar.py:create_sidecar_app()`:

```python
# POST /routing/resolve — maps taskType + agentId to RoutingDecision
# Returns: {provider, model, tier, taskCategory}
# Uses: TieredRoutingBridge.resolve(role=taskType, agent_id=agentId)

# POST /effectiveness/recommendations — top tools by success rate
# Returns: {tools: [{name, successRate, observations}]}
# Uses: EffectivenessStore.get_recommendations(task_type, top_k=3)

# POST /mcp/tool — allowlisted MCP tool proxy
# Returns: {result, error}
# Uses: MCPRegistryAdapter.call_tool(name, args) with allowlist guard
```

Two new Pydantic models needed in `core/sidecar_models.py` (D-09):
- `MCPToolRequest(tool_name: str, params: dict)` with camelCase alias `toolName`
- `MCPToolResponse(result: Any, error: str | None)`

Additional models for routing and effectiveness endpoints:
- `RoutingResolveRequest(task_type: str, agent_id: str, quality_target: str)` with camelCase aliases
- `RoutingResolveResponse(provider, model, tier, task_category)` mirroring RoutingDecision
- `EffectivenessRequest(task_type: str, agent_id: str)` with camelCase alias
- `EffectivenessResponse(tools: list[ToolEffectivenessItem])` where each item has `{name, successRate, observations}`

### Anti-Patterns to Avoid
- **Importing from adapter package:** D-02 forbids local path dependencies between packages. Copy `Agent42Client` pattern, do not import it.
- **Registering handlers after setup() resolves:** SDK docs state registration must be synchronous within setup. Do not register inside async callbacks.
- **Declaring capabilities not used:** Unused capability declarations confuse operators. Only declare `http.outbound` and `agent.tools.register`.
- **Using `zod` as a separate dependency:** Plugin-sdk re-exports `z` from zod — use `import { z } from "@paperclipai/plugin-sdk"`.
- **Calling `ctx.config.get()` in tool handlers:** Config is stable for plugin lifetime. Call once in `setup()`, cache in module-level variable alongside `client`.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Plugin host communication protocol | Custom JSON-RPC stdin/stdout transport | `runWorker(plugin, import.meta.url)` from plugin-sdk | SDK handles message framing, capability enforcement, error serialization |
| In-memory test context | Mock PluginContext manually | `createTestHarness` from `@paperclipai/plugin-sdk/testing` | Harness enforces capability checks, provides typed `executeTool()`, seeds host entities |
| Config access | Read env vars directly | `ctx.config.get()` | Host resolves and validates config against instanceConfigSchema before passing to worker |
| Secret resolution | Store apiKey as plaintext in config | `format: "secret-ref"` in schema + `ctx.secrets.resolve()` | Host provides secrets manager; `secret-ref` format triggers secure input UI |
| Capability enforcement | Check capabilities manually | Declare in manifest, SDK enforces | Runtime `CAPABILITY_DENIED` error for undeclared capabilities used |
| Tool name namespacing | Prefix tool names manually | SDK auto-prefixes by plugin ID | Tools are registered as `<pluginId>:<toolName>` by host; keep names unprefixed in code |

**Key insight:** The plugin SDK's test harness (`createTestHarness`) eliminates the need to understand any JSON-RPC protocol internals. Tests operate at the tool-handler level.

---

## Common Pitfalls

### Pitfall 1: `initialize(config)` Does Not Exist as a Separate Export
**What goes wrong:** Implementing `export async function initialize(config)` and wondering why config is never received. `paperclip doctor` passes but tools fail with "client not initialized".
**Why it happens:** CONTEXT.md describes `initialize(config)` as a conceptual pattern, but the actual SDK `PluginDefinition` interface has no `initialize` method. Config is delivered via `ctx.config.get()` inside `setup()`.
**How to avoid:** Use `await ctx.config.get()` at the start of `setup()`. Store the client as a module-level variable.
**Warning signs:** TypeScript compilation warning if you try to add `initialize` to the `PluginDefinition` object — it will be an extra property that gets ignored.

### Pitfall 2: `health()` vs `onHealth()` Naming
**What goes wrong:** Implementing `async health()` in the plugin definition — the method is silently ignored, `paperclip doctor` shows the plugin as status-unknown or always-ok rather than reflecting real sidecar connectivity.
**Why it happens:** The `PluginDefinition` interface uses `onHealth()` not `health()`. Both names sound plausible.
**How to avoid:** Type the plugin definition as `PluginDefinition` explicitly so TypeScript catches the wrong method name at compile time.
**Warning signs:** TypeScript shows `health` as an excess property warning if strict mode is on.

### Pitfall 3: `top_k` and `score_threshold` Must Stay snake_case
**What goes wrong:** Sending `topK` and `scoreThreshold` to `/memory/recall`, getting 422 Unprocessable Entity from FastAPI.
**Why it happens:** The `MemoryRecallRequest` Pydantic model has NO camelCase alias for these fields (documented in `adapters/agent42-paperclip/src/types.ts` line 100-110). All other sidecar endpoints use camelCase, making this inconsistency easy to miss.
**How to avoid:** In plugin `types.ts`, document these fields explicitly as `top_k` / `score_threshold`. Tests will catch 422s immediately.
**Warning signs:** 422 validation error from sidecar in tests.

### Pitfall 4: MCPRegistryAdapter Not Available in Sidecar App
**What goes wrong:** `POST /mcp/tool` endpoint works in tests but raises `AttributeError` in prod — MCPRegistryAdapter was never passed to `create_sidecar_app()`.
**Why it happens:** `create_sidecar_app()` currently only accepts `memory_store`, `agent_manager`, `effectiveness_store`, `reward_system`, `qdrant_store`. The MCP registry is built in `mcp_server.py` independently. The proxy needs access to the same registry.
**How to avoid:** Either (a) pass the registry as a new parameter to `create_sidecar_app()`, or (b) import `_build_registry()` from `mcp_server.py` and instantiate it inside `create_sidecar_app()` when mcp proxy is needed. Option (a) is cleaner for testing.
**Warning signs:** Tests of `/mcp/tool` pass because they mock the registry; integration test against live sidecar fails.

### Pitfall 5: Windows CRLF in Plugin Package (from prior research P5)
**What goes wrong:** JSON-RPC newline-delimited protocol receives `\r\n` line endings from the TypeScript build on Windows, causing parse errors in the Paperclip host.
**Why it happens:** Git on Windows auto-converts LF to CRLF for TypeScript files.
**How to avoid:** Add `.gitattributes` to `plugins/agent42-paperclip/`: `*.ts text eol=lf`, `*.json text eol=lf`, `*.js text eol=lf`.
**Warning signs:** Plugin fails to start with a JSON parse error on non-Windows Paperclip hosts.

### Pitfall 6: PluginDefinition Registration Must Be Synchronous Within setup()
**What goes wrong:** Tool handlers registered inside `await someAsyncCall().then(() => ctx.tools.register(...))` are silently not registered — agents receive "tool not found" errors.
**Why it happens:** SDK docs state that all handler registrations must complete before `setup()` resolves. Registrations inside async callbacks that resolve after `setup()` returns are ignored.
**How to avoid:** Resolve async dependencies (config, client) first, then register tools synchronously before `setup()` returns.

### Pitfall 7: Module-Level Client Singleton vs. Test Isolation
**What goes wrong:** Tests bleed state because module-level `client` variable persists between test runs.
**Why it happens:** ESM module singletons in Node.js are cached between imports in the same process.
**How to avoid:** In tests, reset the singleton by calling `onShutdown()` in `afterEach()`, or use `createTestHarness` which provides isolated context per test.

---

## Code Examples

Verified patterns from official sources (plugin-sdk v2026.325.0):

### Full Worker Entry Pattern
```typescript
// Source: dist/define-plugin.d.ts and dist/worker-rpc-host.d.ts
import { definePlugin, runWorker } from "@paperclipai/plugin-sdk";
import { registerTools } from "./tools.js";
import { Agent42Client } from "./client.js";

let client: Agent42Client | null = null;

export default definePlugin({
  async setup(ctx) {
    const config = await ctx.config.get();
    // Validate required fields
    if (!config.agent42BaseUrl || !config.apiKey) {
      throw new Error("agent42BaseUrl and apiKey are required");
    }
    client = new Agent42Client(
      config.agent42BaseUrl as string,
      config.apiKey as string,
      (config.timeoutMs as number) ?? 10_000,
    );
    registerTools(ctx, client);
    ctx.logger.info("Agent42 plugin ready", { baseUrl: config.agent42BaseUrl });
  },

  async onHealth() {
    if (!client) return { status: "error", message: "client not initialized" };
    try {
      const h = await client.health();
      return { status: h.status === "ok" ? "ok" : "degraded", details: h };
    } catch (e) {
      return { status: "error", message: String(e) };
    }
  },

  async onShutdown() {
    client?.destroy();
    client = null;
  },
});

runWorker(plugin, import.meta.url);
```

### Tool Registration with ToolResult
```typescript
// Source: dist/types.d.ts — ToolResult interface
// ToolResult = { content?: string; data?: unknown; error?: string }
// Returning `error` causes the agent to see a failed tool call.

async (params, runCtx) => {
  try {
    const result = await client.routeTask({
      taskType: (params as any).taskType,
      agentId: runCtx.agentId,
    });
    return {
      content: `Route to ${result.provider}/${result.model} (tier: ${result.tier})`,
      data: result,
    };
  } catch (e) {
    return { error: `routing failed: ${String(e)}` };
  }
}
```

### TestHarness Usage
```typescript
// Source: dist/testing.d.ts — createTestHarness
import { createTestHarness } from "@paperclipai/plugin-sdk";
import plugin from "../src/worker.js";
import manifest from "../manifest.json" assert { type: "json" };

describe("memory_recall tool", () => {
  let harness: ReturnType<typeof createTestHarness>;

  beforeEach(async () => {
    harness = createTestHarness({
      manifest,
      config: { agent42BaseUrl: "http://localhost:8001", apiKey: "test-token" },
    });
    vi.stubGlobal("fetch", mockFetch);
    await plugin.definition.setup(harness.ctx);
  });

  it("returns memories from sidecar", async () => {
    const result = await harness.executeTool("memory_recall", { query: "typescript" });
    expect(result.data).toHaveProperty("memories");
  });
});
```

### Python: New Sidecar Endpoints Pattern
```python
# core/sidecar_models.py additions
class MCPToolRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    tool_name: str = Field(..., alias="toolName")
    params: dict[str, Any] = Field(default_factory=dict)

class MCPToolResponse(BaseModel):
    result: Any = None
    error: str | None = None

class RoutingResolveRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_type: str = Field(..., alias="taskType")
    agent_id: str = Field(..., alias="agentId")
    quality_target: str = Field(default="", alias="qualityTarget")

class EffectivenessRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)
    task_type: str = Field(..., alias="taskType")
    agent_id: str = Field(..., alias="agentId")
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Manual JSON-RPC over stdio | `definePlugin` + `runWorker` | Plugin SDK v2026.318.0 (2026-03-18) | Eliminates protocol boilerplate entirely |
| Separate `initialize()` export | Config via `ctx.config.get()` in `setup()` | SDK v1 design | Simpler lifecycle; config is always ready when setup runs |
| `health()` method name | `onHealth()` in `PluginDefinition` | SDK v2026.325.0 | Must use `onHealth` or method is ignored |
| Custom test utilities | `createTestHarness` from `@paperclipai/plugin-sdk/testing` | SDK v2026.318.0 | Official testing harness with capability enforcement |

**Deprecated/outdated:**
- Manual stdin/stdout JSON-RPC: Replaced entirely by SDK worker-rpc-host
- Separate `initialize` export: Never existed in released SDK; config via `ctx.config.get()`

---

## Open Questions

1. **`/routing/resolve` vs reusing adapter pattern for route_task**
   - What we know: `TieredRoutingBridge.resolve()` takes `role`, `agent_id`, `preferred_provider` — the plugin tool takes `taskType` which maps to `role`
   - What's unclear: Whether the existing sidecar already exposes a routing endpoint or the plugin must call a new one
   - Recommendation: Inspect `dashboard/sidecar.py` fully — if no routing endpoint exists, add `POST /routing/resolve` following the memory endpoint pattern

2. **MCPRegistryAdapter injection into sidecar**
   - What we know: `mcp_server.py:_build_registry()` creates the registry; `create_sidecar_app()` does not currently receive it
   - What's unclear: Best injection pattern — pass as parameter vs. instantiate inside sidecar app
   - Recommendation: Pass as new optional parameter `mcp_registry: MCPRegistryAdapter | None = None` matching the existing pattern for other optional services

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Plugin package build and tests | Yes | v22.14.0 | — |
| npm | Plugin package install | Yes | 10.9.2 | — |
| `@paperclipai/plugin-sdk` | Plugin core | Available on npm | 2026.325.0 | — |
| Python / FastAPI sidecar | New sidecar endpoints | Existing (Phase 24) | — | — |
| `memory/effectiveness.py:EffectivenessStore` | tool_effectiveness tool | Exists | — | Returns empty list on failure |
| `core/tiered_routing_bridge.py:TieredRoutingBridge` | route_task tool | Exists | — | — |
| `mcp_server.py:MCPRegistryAdapter` | mcp_tool_proxy | Exists (needs injection) | — | — |

**Missing dependencies with no fallback:** None — all dependencies exist.

**Missing dependencies with fallback:** None identified.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest 4.1.2 |
| Config file | `plugins/agent42-paperclip/vitest.config.ts` (Wave 0 gap) |
| Quick run command | `cd plugins/agent42-paperclip && npm test` |
| Full suite command | `cd plugins/agent42-paperclip && npm test -- --reporter=verbose` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PLUG-01 | manifest.json passes schema validation | unit | `npm test -- tests/worker.test.ts` | ❌ Wave 0 |
| PLUG-02 | memory_recall returns memories from sidecar | unit | `npm test -- tests/tools.test.ts` | ❌ Wave 0 |
| PLUG-03 | memory_store stores and returns pointId | unit | `npm test -- tests/tools.test.ts` | ❌ Wave 0 |
| PLUG-04 | route_task returns provider+model+tier | unit | `npm test -- tests/tools.test.ts` | ❌ Wave 0 |
| PLUG-05 | tool_effectiveness returns top-3 by success rate | unit | `npm test -- tests/tools.test.ts` | ❌ Wave 0 |
| PLUG-06 | mcp_tool_proxy proxies allowed tool, rejects blocked tool | unit | `npm test -- tests/tools.test.ts` | ❌ Wave 0 |
| PLUG-07 | onHealth() returns ok when sidecar up, error when down | unit | `npm test -- tests/worker.test.ts` | ❌ Wave 0 |
| PLUG-01 (Python) | POST /mcp/tool returns result for allowlisted tool | unit | `python -m pytest tests/test_sidecar.py -x -q` | ❌ Wave 0 |
| PLUG-01 (Python) | POST /mcp/tool rejects non-allowlisted tool | unit | `python -m pytest tests/test_sidecar.py -x -q` | ❌ Wave 0 |

### Sampling Rate
- **Per task commit:** `cd plugins/agent42-paperclip && npm test` + `python -m pytest tests/test_sidecar.py -x -q`
- **Per wave merge:** Full suite: `npm test` + `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `plugins/agent42-paperclip/` — entire package scaffold (package.json, tsconfig.json, vitest.config.ts, manifest.json)
- [ ] `plugins/agent42-paperclip/tests/worker.test.ts` — covers PLUG-01, PLUG-07
- [ ] `plugins/agent42-paperclip/tests/tools.test.ts` — covers PLUG-02 through PLUG-06
- [ ] `plugins/agent42-paperclip/tests/client.test.ts` — Agent42Client HTTP contract
- [ ] `tests/test_sidecar_mcp.py` — covers Python-side POST /mcp/tool endpoint

---

## Project Constraints (from CLAUDE.md)

| Directive | Applies To |
|-----------|-----------|
| All I/O is async — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools | New Python sidecar endpoints must use async handlers |
| Frozen config — `Settings` dataclass in `core/config.py` | MCP_TOOL_ALLOWLIST config field should go in `core/config.py` `from_env()` |
| Graceful degradation — Redis, Qdrant, MCP are optional. Handle absence, never crash | POST /mcp/tool must return 503/error gracefully when MCPRegistryAdapter not available |
| Sandbox always on — validate paths via `sandbox.resolve_path()` | MCP tool proxy must ensure sandbox is enforced server-side (D-05 already specifies this) |
| New pitfalls — add to `.claude/reference/pitfalls-archive.md` when discovered | Add "Plugin onHealth vs health naming" and "Plugin initialize via ctx.config.get" after phase |

---

## Sources

### Primary (HIGH confidence)
- `/c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/plugin-sdk/dist/define-plugin.d.ts` — `PluginDefinition` interface, lifecycle hook names (`onHealth`, `onShutdown`, `setup`), `definePlugin()` signature
- `/c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/plugin-sdk/dist/types.d.ts` — `PluginContext`, `PluginToolsClient.register()` exact signature, `ToolRunContext`, `ToolResult`, `PluginConfigClient.get()`
- `/c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/plugin-sdk/dist/testing.d.ts` — `createTestHarness`, `TestHarness.executeTool()` signature
- `/c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/shared/dist/types/plugin.d.ts` — `PaperclipPluginManifestV1` full interface (confirmed `author` required field)
- `/c/tmp/plugin-sdk-inspect/node_modules/@paperclipai/shared/dist/constants.d.ts` — `PLUGIN_CAPABILITIES` full list, confirmed `"http.outbound"` and `"agent.tools.register"` are valid values
- `npm view @paperclipai/plugin-sdk dist-tags.latest` → `2026.325.0` (run 2026-03-31)
- `C:\Users\rickw\projects\agent42\adapters\agent42-paperclip\src\types.ts` — confirmed `top_k` / `score_threshold` snake_case exception
- `C:\Users\rickw\projects\agent42\core\sidecar_models.py` — existing Pydantic model conventions
- `C:\Users\rickw\projects\agent42\dashboard\sidecar.py` — existing sidecar app structure, endpoint patterns
- `C:\Users\rickw\projects\agent42\memory\effectiveness.py` — `EffectivenessStore.get_recommendations(task_type, min_observations, top_k)` signature
- `C:\Users\rickw\projects\agent42\core\tiered_routing_bridge.py` — `TieredRoutingBridge.resolve()` signature

### Secondary (MEDIUM confidence)
- GitHub PLUGIN_SPEC.md via WebFetch — confirmed `executeTool` host-to-worker RPC method name, JSON-RPC protocol overview
- DeepWiki plugin architecture page — confirmed worker lifecycle stages, capability enforcement model

### Tertiary (LOW confidence)
- WebSearch result summaries for `definePlugin` / `runWorker` pattern — superseded by direct SDK inspection

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — installed and inspected from npm registry
- Architecture: HIGH — verified from TypeScript type definitions, adapter reference patterns
- Pitfalls: HIGH (SDK pitfalls from types), MEDIUM (integration pitfalls from prior phase research)
- Python sidecar extensions: HIGH — existing pattern in sidecar.py is clear and consistent

**Research date:** 2026-03-31
**Valid until:** 2026-04-30 (plugin-sdk is actively iterated; re-check before planning Phase 29)

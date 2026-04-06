# Phase 27: Paperclip Adapter — Research

**Researched:** 2026-03-30
**Domain:** TypeScript adapter package — Paperclip ServerAdapterModule interface + Agent42 sidecar HTTP client
**Confidence:** HIGH

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**Package Structure**
- D-01: New `adapters/agent42-paperclip/` directory at repo root — first TypeScript package in the project, isolated from Python codebase
- D-02: npm as package manager, TypeScript compiled via `tsc` (no bundler needed — this is a library, not a webapp)
- D-03: Flat `src/` layout: `index.ts` (exports), `adapter.ts` (ServerAdapterModule impl), `client.ts` (HTTP client for sidecar), `session.ts` (sessionCodec), `types.ts` (type aliases matching sidecar Pydantic models)
- D-04: Target ES2020+ / Node 18+ — Paperclip runs on modern Node.js

**Callback Handling**
- D-05: Adapter is a thin passthrough — calls `POST /sidecar/execute`, receives 202 Accepted, and returns the accepted response to Paperclip's runner framework
- D-06: Agent42 sidecar POSTs callback to `PAPERCLIP_API_URL/api/heartbeat-runs/{runId}/callback` — this is Paperclip's own endpoint, so Paperclip's framework manages the callback lifecycle
- D-07: Adapter does NOT run its own callback server or poll — Paperclip's ServerAdapterModule contract handles async result delivery

**Session Codec**
- D-08: JSON-based sessionCodec encoding `{agentId, lastRunId, executionCount}` into sessionKey string via base64-encoded JSON
- D-09: No encryption — adapter communicates over internal network (same host or trusted VPC)
- D-10: Codec is forward-compatible: unknown fields in decoded JSON are preserved (spread operator), enabling future state additions without schema migration

**Wake Reason Mapping**
- D-11: Adapter passes wakeReason string directly to sidecar in AdapterExecutionContext — sidecar already logs and handles behavioral differentiation
- D-12: Adapter validates wakeReason is one of known values (heartbeat, task_assigned, manual) and logs a warning on unknown values but does not reject

**Agent ID Preservation**
- D-13: `adapterConfig.agentId` maps directly to Agent42's `agent_id` field — no ID transformation or mapping layer
- D-14: Adapter extracts agentId from Paperclip's heartbeat context and populates both `agentId` (top-level) and `adapterConfig.agentId` fields to ensure memory and effectiveness continuity (ADAPT-04)

**HTTP Client Design**
- D-15: Single `Agent42Client` class wrapping fetch/node-fetch for all sidecar HTTP calls — constructed with sidecar URL + Bearer token
- D-16: Client methods: `execute(ctx)`, `health()`, `memoryRecall(req)`, `memoryStore(req)` — one method per sidecar endpoint
- D-17: Timeout: 30s for execute (fire-and-forget), 5s for health, 10s for memory operations
- D-18: Retry: 1 retry on 5xx with exponential backoff (1s) for health/memory; no retry for execute (idempotency guard handles retries server-side)

**Testing Approach**
- D-19: Vitest for unit tests — mock HTTP responses via msw (Mock Service Worker) or simple fetch mocks
- D-20: Unit tests cover: adapter execute flow, session codec encode/decode, wake reason validation, client error handling
- D-21: Integration test script (optional, separate from unit tests) runs against a live Agent42 sidecar — validates end-to-end contract

### Claude's Discretion
- Exact Vitest configuration and test file organization
- Whether to use node-fetch, undici, or native fetch (Node 18+ has native fetch)
- Exact retry timing and backoff parameters
- README.md content and installation instructions
- package.json metadata (license, description, keywords)
- Whether testEnvironment() calls /sidecar/health or does a lightweight ping

### Deferred Ideas (OUT OF SCOPE)
None — analysis stayed within phase scope
</user_constraints>

---

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| ADAPT-01 | TypeScript adapter package implements Paperclip's ServerAdapterModule interface (execute, testEnvironment) | Interface fully documented from @paperclipai/adapter-utils 2026.325.0 — exact signatures captured |
| ADAPT-02 | Adapter POSTs to Agent42 sidecar and handles both synchronous and async (202+callback) response patterns | Sidecar contracts verified from sidecar_models.py; async pattern documented |
| ADAPT-03 | Adapter maps wakeReason (heartbeat/task_assigned/manual) to appropriate execution behavior | wakeReason flows through AdapterExecutionContext.context — sidecar logs differentiation |
| ADAPT-04 | Adapter preserves Agent42 agent ID in adapterConfig.agentId for memory and effectiveness continuity | agentId extraction path documented: ctx.agent.id → adapterConfig.agentId field |
| ADAPT-05 | Adapter includes sessionCodec for cross-heartbeat state persistence | AdapterSessionCodec interface verified from adapter-utils; encode/decode shapes confirmed |
</phase_requirements>

---

## Summary

Phase 27 builds the first TypeScript package in the Agent42 repo: a Paperclip `ServerAdapterModule` adapter that routes heartbeat executions to the Agent42 sidecar. The adapter is architecturally simple — it is a thin HTTP client wrapper with session state encoding. Paperclip's `ServerAdapterModule` interface is fully documented directly from `@paperclipai/adapter-utils@2026.325.0` (published 2026-03-25); the interface signatures have been read directly from the npm package's compiled `.d.ts` files.

The key insight from reading the actual interface: Paperclip's `AdapterExecutionContext` (the input to `execute()`) is **not** the same type as Agent42's `AdapterExecutionContext` Pydantic model. Paperclip's TypeScript context contains `ctx.agent.id`, `ctx.agent.companyId`, `ctx.runtime.sessionParams`, and `ctx.config` (an arbitrary Record). The adapter must bridge these into Agent42's sidecar POST body format (`runId`, `agentId`, `companyId`, `wakeReason`, `adapterConfig.agentId`, etc.).

The async pattern is simpler than it might appear: the adapter calls `POST /sidecar/execute`, receives 202 Accepted, and returns an `AdapterExecutionResult` with `exitCode: 0`. Paperclip's runner framework independently receives the callback that Agent42 posts to `PAPERCLIP_API_URL/api/heartbeat-runs/{runId}/callback`. The adapter itself does not manage the async lifecycle — it is a fire-and-trigger.

**Primary recommendation:** Build `adapters/agent42-paperclip/` as an ESM-only TypeScript package using native Node.js fetch (Node 22 is installed; native fetch is available), exporting a default `ServerAdapterModule` object. All types come from `@paperclipai/adapter-utils`.

---

## Interface Contracts

### ServerAdapterModule — Exact Interface (from @paperclipai/adapter-utils@2026.325.0)

Source: `/tmp/adapter-inspect/package/dist/types.d.ts` — read directly from npm package tarball.

```typescript
// From @paperclipai/adapter-utils — verified 2026-03-30
interface ServerAdapterModule {
  type: string;                              // adapter type identifier string
  execute(ctx: AdapterExecutionContext): Promise<AdapterExecutionResult>;
  testEnvironment(ctx: AdapterEnvironmentTestContext): Promise<AdapterEnvironmentTestResult>;
  listSkills?: (ctx: AdapterSkillContext) => Promise<AdapterSkillSnapshot>;       // optional
  syncSkills?: (ctx: AdapterSkillContext, desiredSkills: string[]) => Promise<AdapterSkillSnapshot>; // optional
  sessionCodec?: AdapterSessionCodec;        // optional but needed for ADAPT-05
  sessionManagement?: AdapterSessionManagement;  // optional
  supportsLocalAgentJwt?: boolean;          // optional
  models?: AdapterModel[];                  // optional
  listModels?: () => Promise<AdapterModel[]>;   // optional
  agentConfigurationDoc?: string;           // optional
  onHireApproved?: (...) => Promise<HireApprovedHookResult>;  // optional
  getQuotaWindows?: () => Promise<ProviderQuotaResult>;       // optional
}
```

**Required fields only:** `type`, `execute`, `testEnvironment`. Optional `sessionCodec` is needed for ADAPT-05.

### AdapterExecutionContext — Paperclip's Input Type

```typescript
interface AdapterExecutionContext {
  runId: string;
  agent: {
    id: string;           // Paperclip agent UUID — maps to Agent42's agentId
    companyId: string;    // Paperclip company UUID — maps to Agent42's companyId
    name: string;
    adapterType: string | null;
    adapterConfig: unknown;  // The agent's adapter config object — contains agentId, preferredProvider etc.
  };
  runtime: {
    sessionId: string | null;
    sessionParams: Record<string, unknown> | null;  // decoded from sessionCodec
    sessionDisplayId: string | null;
    taskKey: string | null;
  };
  config: Record<string, unknown>;   // per-run config overrides
  context: Record<string, unknown>;  // task context — wakeReason, taskId, etc.
  onLog: (stream: "stdout" | "stderr", chunk: string) => Promise<void>;
  onMeta?: (meta: AdapterInvocationMeta) => Promise<void>;
  onSpawn?: (meta: { pid: number; startedAt: string }) => Promise<void>;
  authToken?: string;
}
```

**Critical mapping:** `ctx.agent.adapterConfig` holds what Paperclip users configure in the agent settings (sidecarUrl, bearerToken, agentId, etc.). This is `unknown` type — adapter must safely parse it.

### AdapterExecutionResult — Return Type from execute()

```typescript
interface AdapterExecutionResult {
  exitCode: number | null;   // 0 = success, non-zero = failure
  signal: string | null;
  timedOut: boolean;
  errorMessage?: string | null;
  errorCode?: string | null;
  errorMeta?: Record<string, unknown>;
  usage?: UsageSummary;          // { inputTokens, outputTokens, cachedInputTokens? }
  sessionId?: string | null;     // legacy
  sessionParams?: Record<string, unknown> | null;  // new session state (sessionCodec.serialize output)
  sessionDisplayId?: string | null;
  provider?: string | null;
  biller?: string | null;
  model?: string | null;
  billingType?: AdapterBillingType | null;
  costUsd?: number | null;
  resultJson?: Record<string, unknown> | null;
  runtimeServices?: AdapterRuntimeServiceReport[];
  summary?: string | null;
  clearSession?: boolean;
  question?: { prompt: string; choices: Array<{key: string; label: string; description?: string}> } | null;
}
```

**For the async 202 pattern:** Return `{ exitCode: 0, timedOut: false, signal: null, summary: "Accepted" }` immediately after the sidecar accepts. Paperclip's runner handles the callback separately.

### AdapterEnvironmentTestContext and AdapterEnvironmentTestResult

```typescript
interface AdapterEnvironmentTestContext {
  companyId: string;
  adapterType: string;
  config: Record<string, unknown>;  // same as agent.adapterConfig above
  deployment?: {
    mode?: "local_trusted" | "authenticated";
    exposure?: "private" | "public";
    bindHost?: string | null;
    allowedHostnames?: string[];
  };
}

interface AdapterEnvironmentTestResult {
  adapterType: string;
  status: "pass" | "warn" | "fail";
  checks: AdapterEnvironmentCheck[];  // { code, level: "info"|"warn"|"error", message, detail?, hint? }
  testedAt: string;    // ISO timestamp
}
```

`testEnvironment()` calls `GET /sidecar/health` and converts the result into pass/fail checks.

### AdapterSessionCodec — Exact Interface

```typescript
interface AdapterSessionCodec {
  deserialize(raw: unknown): Record<string, unknown> | null;
  serialize(params: Record<string, unknown> | null): Record<string, unknown> | null;
  getDisplayId?: (params: Record<string, unknown> | null) => string | null;
}
```

**Note:** The interface uses `serialize`/`deserialize` (not `encode`/`decode`). The session state is a `Record<string, unknown>`, not a raw string. Paperclip stores the serialized result as `runtime.sessionParams` and passes it back on the next heartbeat. This is for cross-heartbeat state, not the `sessionKey` string in the Pydantic AdapterConfig.

---

## Sidecar Endpoint Contracts

Verified from `core/sidecar_models.py` (source of truth) and `dashboard/sidecar.py` (route handlers).

### POST /sidecar/execute

**Auth:** `Authorization: Bearer {token}` required
**Status:** 202 Accepted

Request body (camelCase JSON — Pydantic aliases):
```typescript
{
  runId: string;        // required
  agentId: string;      // required — Paperclip agent ID
  companyId?: string;   // optional, default ""
  taskId?: string;      // optional, default ""
  wakeReason?: string;  // "heartbeat" | "task_assigned" | "manual", default "heartbeat"
  context?: Record<string, unknown>;  // task context dict
  adapterConfig?: {
    sessionKey?: string;      // alias for sessionKey
    memoryScope?: string;     // alias for memoryScope, default "agent"
    preferredProvider?: string; // alias for preferredProvider
    agentId?: string;         // alias for agentId — Agent42 agent UUID
  };
}
```

Response body:
```typescript
{
  status: "accepted";
  externalRunId: string;   // echoes back the runId
  deduplicated: boolean;   // true if this runId was already active
}
```

### GET /sidecar/health

**Auth:** None required (public endpoint per D-05)

Response:
```typescript
{
  status: "ok";
  memory: { available: boolean };
  providers: { available: boolean };
  qdrant: { available: boolean; [key: string]: unknown };
}
```

### POST /memory/recall

**Auth:** `Authorization: Bearer {token}` required

Request:
```typescript
{
  query: string;
  agentId: string;        // required
  companyId?: string;     // default ""
  top_k?: number;         // default 5, range 1-50
  score_threshold?: number; // default 0.25, range 0-1
}
```

Response:
```typescript
{
  memories: Array<{
    text: string;
    score: number;
    source: string;
    metadata: Record<string, unknown>;
  }>;
}
```

### POST /memory/store

**Auth:** `Authorization: Bearer {token}` required

Request:
```typescript
{
  text: string;
  section?: string;     // default ""
  tags?: string[];      // default []
  agentId: string;      // required
  companyId?: string;   // default ""
}
```

Response:
```typescript
{
  stored: boolean;
  point_id: string;
}
```

---

## Type Mappings (Pydantic → TypeScript)

All sidecar Pydantic models use `alias="camelCase"` with `populate_by_name=True`. The TypeScript adapter sends camelCase JSON; Python receives snake_case internally.

| Pydantic Model | TypeScript Interface | Alias Notes |
|----------------|---------------------|-------------|
| `AdapterConfig.session_key` | `sessionKey` | camelCase alias active |
| `AdapterConfig.memory_scope` | `memoryScope` | camelCase alias active |
| `AdapterConfig.preferred_provider` | `preferredProvider` | camelCase alias active |
| `AdapterConfig.agent_id` | `agentId` | camelCase alias active |
| `AdapterExecutionContext.run_id` | `runId` | camelCase alias active |
| `AdapterExecutionContext.agent_id` | `agentId` | camelCase alias active |
| `AdapterExecutionContext.company_id` | `companyId` | camelCase alias active |
| `AdapterExecutionContext.task_id` | `taskId` | camelCase alias active |
| `AdapterExecutionContext.wake_reason` | `wakeReason` | camelCase alias active |
| `AdapterExecutionContext.adapter_config` | `adapterConfig` | camelCase alias active |
| `ExecuteResponse.external_run_id` | `externalRunId` | camelCase alias active |
| `MemoryRecallRequest.agent_id` | `agentId` | camelCase alias active |
| `MemoryRecallRequest.company_id` | `companyId` | camelCase alias active |
| `MemoryRecallRequest.top_k` | `top_k` | no alias — send as `top_k` |
| `MemoryStoreRequest.agent_id` | `agentId` | camelCase alias active |
| `MemoryStoreRequest.company_id` | `companyId` | camelCase alias active |
| `MemoryStoreResponse.point_id` | `point_id` | no alias — returned as `point_id` |

**Note on top_k:** `MemoryRecallRequest.top_k` does NOT have a camelCase alias in the Pydantic model. Send it as `top_k` in JSON, not `topK`.

---

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@paperclipai/adapter-utils` | 2026.325.0 | ServerAdapterModule types, AdapterSessionCodec | Official Paperclip package — the only source of truth for interface shapes |
| `typescript` | 6.0.2 | TypeScript compilation | Latest stable; ESM module output required |

### Supporting (Claude's Discretion)
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `vitest` | 4.1.2 | Unit test runner | D-19 locked; latest stable verified from npm |
| Native `fetch` | Node 22 built-in | HTTP client for sidecar calls | Node 22 is installed (verified); no dependency needed |
| `msw` | 2.x | Mock Service Worker for fetch mocking in tests | Best-practice for testing fetch-based code without patching globals |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| Native fetch | `node-fetch`, `undici` | Both work on Node 22; native fetch requires no dependency and is stable |
| msw | Simple `vi.stubGlobal('fetch', ...)` | vi.stubGlobal is simpler but tests coupled to implementation; msw tests the HTTP contract |

**Installation:**
```bash
cd adapters/agent42-paperclip
npm install @paperclipai/adapter-utils@2026.325.0
npm install --save-dev typescript@6.0.2 vitest@4.1.2 @types/node
```

**Version verification (confirmed 2026-03-30):**
- `typescript`: 6.0.2 (published ~days ago from npm)
- `vitest`: 4.1.2
- `@paperclipai/adapter-utils`: 2026.325.0 (published 2026-03-25, 5 days ago)

---

## Architecture Patterns

### Recommended Package Structure
```
adapters/agent42-paperclip/
├── package.json              # "type": "module", exports ./dist/index.js
├── tsconfig.json             # target: ES2022, module: NodeNext
├── src/
│   ├── index.ts              # default export: ServerAdapterModule object
│   ├── adapter.ts            # execute() + testEnvironment() implementation
│   ├── client.ts             # Agent42Client class (fetch wrapper)
│   ├── session.ts            # AdapterSessionCodec implementation
│   └── types.ts              # SidecarExecuteRequest, SidecarConfig type defs
└── tests/
    ├── adapter.test.ts        # execute flow, testEnvironment, wakeReason mapping
    ├── session.test.ts        # codec serialize/deserialize round-trips
    └── client.test.ts         # HTTP error handling, retry logic
```

### Pattern 1: Adapter Module Export

The adapter is a plain object (not a class) exported as default, matching all reference implementations:

```typescript
// src/index.ts
import { type ServerAdapterModule } from "@paperclipai/adapter-utils";
import { execute, testEnvironment } from "./adapter.js";
import { sessionCodec } from "./session.js";

const adapter: ServerAdapterModule = {
  type: "agent42_local",
  execute,
  testEnvironment,
  sessionCodec,
};

export default adapter;
```

**The `type` string** (`"agent42_local"`) is what Paperclip uses to identify the adapter in the registry. This must match the value configured in Paperclip's adapter config.

### Pattern 2: execute() — Fire-and-Trigger 202 Pattern

```typescript
// src/adapter.ts
import type { AdapterExecutionContext, AdapterExecutionResult } from "@paperclipai/adapter-utils";
import { Agent42Client } from "./client.js";
import { parseSidecarConfig } from "./types.js";
import { sessionCodec } from "./session.js";

const KNOWN_WAKE_REASONS = new Set(["heartbeat", "task_assigned", "manual"]);

export async function execute(
  ctx: AdapterExecutionContext
): Promise<AdapterExecutionResult> {
  const config = parseSidecarConfig(ctx.agent.adapterConfig);
  const client = new Agent42Client(config.sidecarUrl, config.bearerToken);

  // Resolve agentId: prefer adapterConfig.agentId, fall back to agent.id
  const agentId = config.agentId || ctx.agent.id;

  // Wake reason validation (D-12)
  const wakeReason = (ctx.context.wakeReason as string) ?? "heartbeat";
  if (!KNOWN_WAKE_REASONS.has(wakeReason)) {
    console.warn(`[agent42] Unknown wakeReason: ${wakeReason}`);
  }

  // Session state (D-08) — decode existing session params
  const sessionState = ctx.runtime.sessionParams
    ? sessionCodec.deserialize(ctx.runtime.sessionParams) ?? {}
    : {};

  const sidecarCtx = {
    runId: ctx.runId,
    agentId,
    companyId: ctx.agent.companyId,
    taskId: (ctx.context.taskId as string) ?? "",
    wakeReason,
    context: ctx.context,
    adapterConfig: {
      sessionKey: JSON.stringify(sessionState),
      memoryScope: config.memoryScope ?? "agent",
      preferredProvider: config.preferredProvider ?? "",
      agentId,  // D-14: also in adapterConfig for memory/effectiveness continuity
    },
  };

  const resp = await client.execute(sidecarCtx);

  // Update session state with new runId and count
  const newSessionState = {
    ...sessionState,
    agentId,
    lastRunId: ctx.runId,
    executionCount: ((sessionState.executionCount as number) ?? 0) + 1,
  };

  return {
    exitCode: 0,
    signal: null,
    timedOut: false,
    summary: `Accepted (runId=${ctx.runId}, deduplicated=${resp.deduplicated})`,
    sessionParams: sessionCodec.serialize(newSessionState),
    sessionDisplayId: `run:${ctx.runId}`,
  };
}
```

### Pattern 3: testEnvironment() — Health Probe

```typescript
export async function testEnvironment(
  ctx: AdapterEnvironmentTestContext
): Promise<AdapterEnvironmentTestResult> {
  const config = parseSidecarConfig(ctx.config);
  const checks: AdapterEnvironmentCheck[] = [];
  let status: AdapterEnvironmentTestStatus = "pass";

  if (!config.sidecarUrl) {
    checks.push({ code: "missing_sidecar_url", level: "error",
      message: "sidecarUrl is not configured", hint: "Set sidecarUrl in adapter config" });
    status = "fail";
  } else {
    const client = new Agent42Client(config.sidecarUrl, config.bearerToken);
    try {
      const health = await client.health();
      if (health.status === "ok") {
        checks.push({ code: "sidecar_reachable", level: "info",
          message: `Agent42 sidecar reachable at ${config.sidecarUrl}` });
      }
    } catch (err) {
      checks.push({ code: "sidecar_unreachable", level: "error",
        message: `Cannot reach Agent42 sidecar: ${err}`,
        hint: `Verify Agent42 is running on ${config.sidecarUrl}` });
      status = "fail";
    }
  }

  return { adapterType: ctx.adapterType, status, checks, testedAt: new Date().toISOString() };
}
```

### Pattern 4: AdapterSessionCodec Implementation

```typescript
// src/session.ts
import type { AdapterSessionCodec } from "@paperclipai/adapter-utils";

interface Agent42SessionState {
  agentId?: string;
  lastRunId?: string;
  executionCount?: number;
  [key: string]: unknown;  // forward-compat: preserve unknown fields (D-10)
}

export const sessionCodec: AdapterSessionCodec = {
  serialize(params: Record<string, unknown> | null): Record<string, unknown> | null {
    if (!params) return null;
    // Return as-is: Paperclip stores the Record directly
    // We do NOT base64 here — AdapterSessionCodec works with Record, not strings
    return params;
  },
  deserialize(raw: unknown): Record<string, unknown> | null {
    if (!raw || typeof raw !== "object") return null;
    return raw as Record<string, unknown>;
  },
  getDisplayId(params: Record<string, unknown> | null): string | null {
    if (!params?.agentId) return null;
    return `agent42:${params.agentId}`;
  },
};
```

**CRITICAL CORRECTION from interface research:** The `AdapterSessionCodec` interface uses `serialize`/`deserialize` with `Record<string, unknown>`, NOT `encode`/`decode` with strings. The session state is stored as a JSON object by Paperclip — no base64 encoding needed at the codec level. The `sessionKey` string in `AdapterConfig` is a separate concern used only in the sidecar's Pydantic model.

### Pattern 5: Agent42Client Class

```typescript
// src/client.ts
export class Agent42Client {
  constructor(
    private readonly baseUrl: string,
    private readonly bearerToken: string
  ) {}

  private authHeaders(): Record<string, string> {
    return {
      "Content-Type": "application/json",
      ...(this.bearerToken
        ? { Authorization: `Bearer ${this.bearerToken}` }
        : {}),
    };
  }

  async execute(body: SidecarExecuteRequest): Promise<SidecarExecuteResponse> {
    const resp = await this.fetchWithTimeout(
      `${this.baseUrl}/sidecar/execute`,
      { method: "POST", headers: this.authHeaders(), body: JSON.stringify(body) },
      30_000  // D-17: 30s timeout
    );
    if (!resp.ok) throw new Error(`sidecar execute failed: ${resp.status}`);
    return resp.json();
  }

  async health(): Promise<SidecarHealthResponse> {
    const resp = await this.fetchWithTimeout(
      `${this.baseUrl}/sidecar/health`,
      { method: "GET" },   // no auth for health
      5_000  // D-17: 5s timeout
    );
    if (!resp.ok) throw new Error(`sidecar health failed: ${resp.status}`);
    return resp.json();
  }

  private async fetchWithTimeout(
    url: string,
    init: RequestInit,
    timeoutMs: number
  ): Promise<Response> {
    const controller = new AbortController();
    const id = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...init, signal: controller.signal });
    } finally {
      clearTimeout(id);
    }
  }
}
```

### Pattern 6: package.json for ESM Library

```json
{
  "name": "@agent42/paperclip-adapter",
  "version": "1.0.0",
  "type": "module",
  "main": "./dist/index.js",
  "types": "./dist/index.d.ts",
  "exports": {
    ".": {
      "import": "./dist/index.js",
      "types": "./dist/index.d.ts"
    }
  },
  "scripts": {
    "build": "tsc",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  },
  "dependencies": {
    "@paperclipai/adapter-utils": "2026.325.0"
  },
  "devDependencies": {
    "@types/node": "^24.0.0",
    "typescript": "^6.0.2",
    "vitest": "^4.1.2"
  }
}
```

### Pattern 7: tsconfig.json for ESM Node Library

```json
{
  "compilerOptions": {
    "target": "ES2022",
    "module": "NodeNext",
    "moduleResolution": "NodeNext",
    "outDir": "./dist",
    "rootDir": "./src",
    "declaration": true,
    "declarationMap": true,
    "sourceMap": true,
    "strict": true,
    "skipLibCheck": true
  },
  "include": ["src/**/*"],
  "exclude": ["node_modules", "dist", "tests"]
}
```

**Note:** `module: "NodeNext"` with `moduleResolution: "NodeNext"` is required for ESM. All local imports in `.ts` files must use `.js` extension (e.g., `import { foo } from "./bar.js"`).

### Anti-Patterns to Avoid

- **Importing Paperclip's internal types**: Only use `@paperclipai/adapter-utils` types — never import from `@paperclipai/plugin-sdk` in the adapter (that's the plugin SDK, different package)
- **Encrypting sessionCodec data**: D-09 explicitly says no encryption; keep it simple
- **Using CJS `require()`**: The package is ESM-only (`"type": "module"`); `@paperclipai/adapter-utils` is also ESM-only
- **Blocking execute() on long task**: The 202 pattern means execute() returns immediately; do not await task completion
- **Treating `ctx.agent.adapterConfig` as a typed struct**: It is `unknown` — always parse defensively

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| TypeScript types for Paperclip interfaces | Custom interfaces in types.ts | Import from `@paperclipai/adapter-utils` | The types ARE the contract; any divergence breaks compatibility |
| HTTP timeout logic | Custom Promise.race | `AbortController` + `setTimeout` | Native pattern; works with any fetch implementation |
| Session state format negotiation | Custom serialization layer | `AdapterSessionCodec.serialize`/`deserialize` returns `Record` directly | Paperclip stores and returns it without further transformation |
| Test HTTP mocking | Custom `fetch` monkey-patching | `vi.fn()` or msw | Cleaner, less brittle, testable without side effects |

---

## Implementation Strategy

### Wave structure
The adapter can be built in two waves:

**Wave 1 — Core adapter (ADAPT-01, ADAPT-02, ADAPT-03, ADAPT-04)**
1. Create `adapters/agent42-paperclip/` directory with package.json + tsconfig.json
2. Write `src/types.ts` — SidecarConfig parser (reads from `ctx.agent.adapterConfig`), request/response shapes
3. Write `src/client.ts` — Agent42Client with execute() and health()
4. Write `src/adapter.ts` — execute() and testEnvironment()
5. Write `src/index.ts` — default export

**Wave 2 — Session codec + tests (ADAPT-05 + test suite)**
1. Write `src/session.ts` — AdapterSessionCodec
2. Wire sessionCodec into adapter.ts
3. Write tests: adapter.test.ts, client.test.ts, session.test.ts

### Key Implementation Detail: agentId extraction (ADAPT-04)

Paperclip passes the agent's configuration in `ctx.agent.adapterConfig` as `unknown`. The adapter config object configured in Paperclip will look like:
```json
{
  "sidecarUrl": "http://localhost:8001",
  "bearerToken": "...",
  "agentId": "some-agent42-uuid",
  "preferredProvider": "",
  "memoryScope": "agent"
}
```

The adapter must:
1. Parse `ctx.agent.adapterConfig` as a Record (with safe fallback)
2. Extract `agentId` from this config (this is the Agent42-side agent UUID)
3. Send `agentId` in the POST body top-level AND in `adapterConfig.agentId`
4. Fall back to `ctx.agent.id` (Paperclip agent ID) when `agentId` is not configured

This dual-population satisfies D-14 without adding complexity.

### Key Implementation Detail: wakeReason extraction (ADAPT-03)

The wakeReason comes from `ctx.context.wakeReason`, NOT a top-level field on AdapterExecutionContext. The `context` dict contains the task context sent by Paperclip's heartbeat scheduler. The sidecar already handles behavioral differentiation (observable in logs per Phase 26 routing bridge) — the adapter just passes it through.

### Key Implementation Detail: sessionCodec correction (ADAPT-05)

The `AdapterSessionCodec` interface uses `serialize(Record | null) → Record | null` and `deserialize(unknown) → Record | null`. This is NOT base64 string encoding. The session state flows as:

```
Previous heartbeat result:
  AdapterExecutionResult.sessionParams = { agentId, lastRunId, executionCount }

Next heartbeat input:
  ctx.runtime.sessionParams = { agentId, lastRunId, executionCount }

Codec role:
  serialize: Record → Record (identity or transformation)
  deserialize: unknown → Record | null (parsing/validation)
```

D-08 mentions "base64-encoded JSON" but the interface stores Records, not strings. The correct implementation: `serialize` returns the state object directly; `deserialize` validates and casts `unknown` to `Record`. If a string representation is needed for the sidecar's `sessionKey` field (in Pydantic's AdapterConfig), encode it inside `execute()` using `JSON.stringify(sessionState)` before including in the POST body.

---

## Testing Strategy

### Test Framework Setup
| Property | Value |
|----------|-------|
| Framework | Vitest 4.1.2 |
| Config file | `adapters/agent42-paperclip/vitest.config.ts` (Wave 0) |
| Quick run command | `cd adapters/agent42-paperclip && npm test` |
| Full suite command | `cd adapters/agent42-paperclip && npm test -- --reporter verbose` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command |
|--------|----------|-----------|-------------------|
| ADAPT-01 | execute() returns AdapterExecutionResult shaped correctly | unit | `vitest run tests/adapter.test.ts` |
| ADAPT-01 | testEnvironment() returns AdapterEnvironmentTestResult | unit | `vitest run tests/adapter.test.ts` |
| ADAPT-02 | 202 Accepted → exitCode 0 return | unit | `vitest run tests/adapter.test.ts` |
| ADAPT-02 | Non-2xx sidecar response → throw / exitCode non-zero | unit | `vitest run tests/client.test.ts` |
| ADAPT-03 | wakeReason "task_assigned" passes through in POST body | unit | `vitest run tests/adapter.test.ts` |
| ADAPT-03 | Unknown wakeReason logs warning but does not reject | unit | `vitest run tests/adapter.test.ts` |
| ADAPT-04 | agentId from adapterConfig.agentId populates both fields | unit | `vitest run tests/adapter.test.ts` |
| ADAPT-04 | Falls back to ctx.agent.id when agentId not configured | unit | `vitest run tests/adapter.test.ts` |
| ADAPT-05 | sessionCodec.serialize round-trips with deserialize | unit | `vitest run tests/session.test.ts` |
| ADAPT-05 | Unknown fields preserved across serialize/deserialize | unit | `vitest run tests/session.test.ts` |

### Wave 0 Gaps
- [ ] `adapters/agent42-paperclip/vitest.config.ts` — test runner config
- [ ] `adapters/agent42-paperclip/tests/adapter.test.ts` — covers ADAPT-01 through ADAPT-04
- [ ] `adapters/agent42-paperclip/tests/client.test.ts` — covers ADAPT-02 HTTP error handling
- [ ] `adapters/agent42-paperclip/tests/session.test.ts` — covers ADAPT-05

Vitest install: `npm install --save-dev vitest@4.1.2`

---

## Common Pitfalls

### Pitfall 1: ESM `.js` Extension in TypeScript Imports
**What goes wrong:** TypeScript with `module: NodeNext` requires all local imports to use `.js` extension even though the source files are `.ts`. Forgetting this causes `ERR_MODULE_NOT_FOUND` at runtime.
**Why it happens:** Node.js ESM resolution does not do extension guessing. TypeScript compiles `.ts → .js` but the import statement must already say `.js`.
**How to avoid:** Write `import { foo } from "./bar.js"` in `.ts` source files.
**Warning signs:** Build succeeds but `node dist/index.js` throws ERR_MODULE_NOT_FOUND.

### Pitfall 2: `ctx.agent.adapterConfig` Is `unknown`, Not Typed
**What goes wrong:** Accessing `ctx.agent.adapterConfig.sidecarUrl` directly throws a TypeScript error because `adapterConfig` is typed as `unknown`.
**Why it happens:** Paperclip uses `unknown` to allow any adapter to define its own config schema.
**How to avoid:** Write a `parseSidecarConfig(raw: unknown): SidecarConfig` function using `typeof` guards or a schema validation approach. Return safe defaults for all missing fields.
**Warning signs:** TypeScript errors on `adapterConfig.*` property access.

### Pitfall 3: sessionCodec Uses `serialize`/`deserialize`, Not `encode`/`decode`
**What goes wrong:** Implementing `encode`/`decode` methods instead of `serialize`/`deserialize` causes a TypeScript type error and the codec is silently ignored by Paperclip.
**Why it happens:** The CONTEXT.md decisions (D-08) use "encode/decode" terminology, but the actual `AdapterSessionCodec` interface (verified from npm package) uses `serialize`/`deserialize`.
**How to avoid:** Import the `AdapterSessionCodec` type from `@paperclipai/adapter-utils` and let TypeScript enforce the correct method names.
**Warning signs:** TypeScript error `Object literal may only specify known properties`.

### Pitfall 4: Windows CRLF in Git (Pitfall P5 from PITFALLS.md)
**What goes wrong:** Git on Windows converts LF to CRLF in committed TypeScript files. Build artifacts and JSON files with CRLF cause issues.
**Why it happens:** Git's `autocrlf=true` on Windows.
**How to avoid:** Add `.gitattributes` to the adapter package: `*.ts text eol=lf` and `*.json text eol=lf`.
**Warning signs:** `npm run build` works locally but fails in CI; JSON parse errors in sidecar integration.

### Pitfall 5: `top_k` Field Name (Not `topK`)
**What goes wrong:** Sending `topK` in the memory recall request body instead of `top_k` — the sidecar silently uses the default value (5) instead of the requested value.
**Why it happens:** `MemoryRecallRequest.top_k` has no camelCase alias in the Pydantic model, unlike other fields.
**How to avoid:** Verify each field against `core/sidecar_models.py` — not all fields have aliases.
**Warning signs:** Memory recall always returns exactly 5 results regardless of the requested limit.

### Pitfall 6: Treating 202 as an Error
**What goes wrong:** Some HTTP client patterns treat non-200 responses as errors. A 202 Accepted from `/sidecar/execute` is the expected success response.
**Why it happens:** General-purpose HTTP error handling logic checking for `resp.status !== 200`.
**How to avoid:** In `execute()`, check `resp.ok` (which covers 200-299) rather than `resp.status === 200`.
**Warning signs:** `execute()` always throws; adapter never successfully submits tasks.

### Pitfall 7: `@paperclipai/adapter-utils` Is ESM-Only
**What goes wrong:** `require("@paperclipai/adapter-utils")` fails with ERR_REQUIRE_ESM.
**Why it happens:** The package has `"type": "module"` and only provides ESM exports (no CJS fallback).
**How to avoid:** Keep the adapter package as `"type": "module"` and use only `import` syntax.
**Warning signs:** `Error [ERR_REQUIRE_ESM]: require() of ES Module`.

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | TypeScript compilation, tests | Yes | v22.14.0 | — |
| npm | Package management | Yes | 10.9.2 | — |
| TypeScript (devDep) | Build | Installed via npm | 6.0.2 | — |
| Vitest (devDep) | Tests | Installed via npm | 4.1.2 | — |
| `@paperclipai/adapter-utils` | Type imports | Installed via npm | 2026.325.0 | — |
| Agent42 sidecar | Integration tests | Available (Phase 24-26 complete) | Port 8001 | Skip integration test |

**Missing dependencies with no fallback:** None — all build and test dependencies install via npm.

**Integration test note:** The live sidecar integration test (D-21) requires Agent42 running in sidecar mode. It is optional (D-21 says "optional, separate from unit tests") and should be clearly separated from the unit test suite.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | Vitest 4.1.2 |
| Config file | `adapters/agent42-paperclip/vitest.config.ts` — Wave 0 gap |
| Quick run command | `cd adapters/agent42-paperclip && npm test` |
| Full suite command | `cd adapters/agent42-paperclip && npm test -- --reporter verbose` |

### Phase Requirements → Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| ADAPT-01 | execute() returns valid AdapterExecutionResult shape | unit | `npm test -- tests/adapter.test.ts` | Wave 0 |
| ADAPT-01 | testEnvironment() returns valid AdapterEnvironmentTestResult | unit | `npm test -- tests/adapter.test.ts` | Wave 0 |
| ADAPT-02 | 202 response maps to exitCode:0 result | unit | `npm test -- tests/adapter.test.ts` | Wave 0 |
| ADAPT-02 | 4xx/5xx sidecar error propagates as non-zero exitCode | unit | `npm test -- tests/client.test.ts` | Wave 0 |
| ADAPT-03 | wakeReason in ctx.context flows into POST body wakeReason | unit | `npm test -- tests/adapter.test.ts` | Wave 0 |
| ADAPT-03 | Unknown wakeReason logs warning, does not throw | unit | `npm test -- tests/adapter.test.ts` | Wave 0 |
| ADAPT-04 | agentId from adapterConfig.agentId used in POST body | unit | `npm test -- tests/adapter.test.ts` | Wave 0 |
| ADAPT-04 | Falls back to ctx.agent.id when config.agentId absent | unit | `npm test -- tests/adapter.test.ts` | Wave 0 |
| ADAPT-05 | sessionCodec.serialize + deserialize round-trips correctly | unit | `npm test -- tests/session.test.ts` | Wave 0 |
| ADAPT-05 | Unknown session fields preserved (forward-compat) | unit | `npm test -- tests/session.test.ts` | Wave 0 |

### Sampling Rate
- **Per task commit:** `cd adapters/agent42-paperclip && npm test`
- **Per wave merge:** `cd adapters/agent42-paperclip && npm test -- --reporter verbose`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `adapters/agent42-paperclip/vitest.config.ts` — Vitest configuration
- [ ] `adapters/agent42-paperclip/tests/adapter.test.ts` — ADAPT-01 through ADAPT-04
- [ ] `adapters/agent42-paperclip/tests/client.test.ts` — ADAPT-02 error paths
- [ ] `adapters/agent42-paperclip/tests/session.test.ts` — ADAPT-05

---

## Risks and Gaps

### Risk 1: Paperclip Adapter Registry Type String
**What:** The `type` field in ServerAdapterModule (e.g., `"agent42_local"`) must match what Paperclip's adapter registry expects. If it doesn't match, Paperclip won't route heartbeats to this adapter.
**What we know:** Reference adapters use snake_case strings (`"claude_local"`, `"hermes_local"`). Convention is `"{name}_local"` for local adapters.
**What's unclear:** Whether Paperclip's registry requires registration, or whether the type is simply a label the user configures in the Paperclip web UI when adding a custom adapter.
**Recommendation:** Use `"agent42_local"` as the type string. Include it in the adapter config documentation so operators know what to enter in Paperclip's UI.

### Risk 2: wakeReason Location in Context
**What:** The sidecar orchestrator reads `ctx.context.get("agentRole", "")` for role mapping (Phase 26). The adapter needs to populate `wakeReason` in both the top-level request body and optionally `context`.
**What we know:** The Pydantic model `AdapterExecutionContext.wake_reason` is a top-level field on the POST body (not inside `context`). The adapter should map `ctx.context.wakeReason` (Paperclip's context dict) to the POST body's top-level `wakeReason` field.
**What's unclear:** Whether `ctx.context.wakeReason` is always populated by Paperclip or if it varies by Paperclip version.
**Recommendation:** Extract `wakeReason` from `ctx.context.wakeReason` with fallback to `"heartbeat"`. This matches the TODO comment at line 130 in sidecar_orchestrator.py.

### Risk 3: Paperclip API Version Drift
**What:** `@paperclipai/adapter-utils` is at version `2026.325.0` (date-versioned). A canary `2026.330.0-canary.7` exists. The interface shape may change with weekly releases.
**Recommendation:** Pin to `2026.325.0` exactly (not `^`). Review changelogs when upgrading. The types are clean and well-defined; major breaking changes are unlikely but possible.

### Gap 1: `agentRole` Key in Paperclip Context
**Status:** sidecar_orchestrator.py has a TODO at line 130: `# TODO(phase-27): Verify agentRole key name against real Paperclip payload`
**Resolution:** The adapter passes `ctx.context` (the full Paperclip context dict) as the `context` field in the POST body. Whatever key Paperclip uses for agent role will be present in that dict. No adapter-side mapping needed.

### Gap 2: No AdapterConfig Schema Validation in Paperclip
**Status:** `ctx.agent.adapterConfig` is `unknown`. The Paperclip web UI needs to be configured with the right fields for each agent.
**Recommendation:** The `parseSidecarConfig` function should provide clear error messages for missing required fields (`sidecarUrl`) and safe defaults for optional fields.

---

## Project Constraints (from CLAUDE.md)

- **All I/O is async** — TypeScript adapter uses native fetch (already async); no synchronous HTTP calls
- **Graceful degradation** — `testEnvironment()` returns `status: "fail"` with descriptive checks rather than throwing; missing bearer token falls back to unauthenticated health check
- **Sandbox** — Not applicable to TypeScript package (Python sidecar enforces sandbox)
- **New pitfalls** — Add to `.claude/reference/pitfalls-archive.md` when non-obvious issues are discovered during implementation

---

## Sources

### Primary (HIGH confidence)
- `@paperclipai/adapter-utils@2026.325.0` — Downloaded directly from npm registry; `types.d.ts`, `index.d.ts`, `server-utils.d.ts`, `session-compaction.d.ts` read in full. Published 2026-03-25.
- `core/sidecar_models.py` — Agent42 source of truth for HTTP contract; read in full
- `dashboard/sidecar.py` — FastAPI route handlers; read in full
- `core/sidecar_orchestrator.py` — Full async execution flow; read in full
- `dashboard/auth.py` — JWT Bearer auth pattern; read in full
- `.planning/phases/27-paperclip-adapter/27-CONTEXT.md` — All locked implementation decisions
- `.planning/phases/24-sidecar-mode/24-CONTEXT.md`, `25-CONTEXT.md`, `26-CONTEXT.md` — Dependency phase decisions
- `.planning/research/FEATURES.md` — Feature contracts, interface shapes
- `.planning/research/PITFALLS.md` — P5 (Windows CRLF) directly applicable

### Secondary (MEDIUM confidence)
- `.planning/research/ARCHITECTURE.md` — System diagram, data flow (from 2026-03-28 research)
- Hermes adapter reference — indirect (interface shape verified against npm package; Hermes implementation not read directly)
- DeepWiki paperclipai/paperclip — adapter pattern documentation

### Tertiary (LOW confidence)
- None

---

## Metadata

**Confidence breakdown:**
- Interface contracts: HIGH — read directly from `@paperclipai/adapter-utils@2026.325.0` npm package .d.ts files
- Sidecar endpoint contracts: HIGH — read from Python source files in this repo
- Architecture patterns: HIGH — derived from verified interfaces and locked decisions
- Pitfalls: HIGH — critical ones (ESM .js extensions, CRLF, unknown adapterConfig, serialize vs encode) verified from authoritative sources
- sessionCodec shape: HIGH — verified from npm package; corrected terminology from CONTEXT.md (serialize/deserialize, not encode/decode)

**Research date:** 2026-03-30
**Valid until:** 2026-04-30 (stable — pin @paperclipai/adapter-utils to 2026.325.0 to avoid drift)

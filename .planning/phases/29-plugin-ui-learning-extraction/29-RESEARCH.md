# Phase 29: Plugin UI + Learning Extraction - Research

**Researched:** 2026-03-30
**Domain:** Paperclip Plugin SDK UI slots, React UI bundle build, sidecar data API surface, learning extraction job, run_id tracing through MemoryBridge/Qdrant
**Confidence:** HIGH (SDK verified from installed source), HIGH (Python sidecar patterns from existing code), MEDIUM (shared component availability caveat)

---

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

**UI Slot Architecture**
- D-01: Plugin declares 4 UI slots in `manifest.json` under `ui.slots[]` — 2 detailTabs (agent effectiveness on `["agent"]`, memory browser on `["run"]`) and 2 dashboardWidgets (provider health, routing decisions)
- D-02: New capabilities added to manifest: `ui.detailTab.register`, `ui.dashboardWidget.register`
- D-03: `entrypoints.ui` set to `"./dist/ui"` (directory, not file) — SDK bundler contract
- D-04: Per-slot file organization: `src/ui/index.tsx` re-exports from `AgentEffectivenessTab.tsx`, `ProviderHealthWidget.tsx`, `MemoryBrowserTab.tsx`, `RoutingDecisionsWidget.tsx`
- D-05: Two-step build: `tsc` for worker (Node.js), `esbuild` via SDK's `createPluginBundlerPresets()` for UI (browser ESM, externalize React + SDK UI)
- D-06: `react` and `@types/react` added as devDependencies — host provides React at runtime via module registry
- D-07: Use SDK shared components: `MetricCard`, `StatusBadge`, `DataTable`, `TimeseriesChart`, `KeyValueList`, `Spinner`, `ErrorBoundary`

**Data API Surface**
- D-08: 5 new sidecar GET endpoints + 1 extension for UI panel data — each panel gets a dedicated data source, one round trip per panel
- D-09: `GET /agent/{agentId}/profile` — combines tier badge, composite score, and agent stats from `EffectivenessStore.get_agent_stats()` + `TierCache`
- D-10: `GET /agent/{agentId}/effectiveness` — per-task-type success rate breakdown from `get_aggregated_stats(agent_id)` (exists but not exposed)
- D-11: `GET /agent/{agentId}/routing-history` — recent N routing decisions; requires new `routing_decisions` log table in SQLite, populated during `execute_async()`
- D-12: Extend `GET /sidecar/health` — widen existing `providers` dict to include per-provider availability status (field is already `dict[str, Any]`, additive and non-breaking)
- D-13: `GET /memory/run-trace/{runId}` — recalled memories + extracted learnings for a specific run, filtered by run_id from Qdrant
- D-14: `GET /agent/{agentId}/spend?hours=24` — token spend distribution across providers; requires new `spend_history` table in SQLite with hourly aggregation
- D-15: All new endpoints require Bearer JWT auth (consistent with existing sidecar pattern) except health extension (already public)
- D-16: Worker registers 4 `ctx.data.register()` handlers in `setup()` — one per UI panel — each calls through `Agent42Client` to the corresponding sidecar endpoint

**Learning Job Design**
- D-17: Learning extraction scheduled via SDK `ctx.jobs` — manifest declares `jobs[]` array with cron schedule (hourly) and `jobs.schedule` capability
- D-18: Sidecar captures run transcripts during `execute_async()` into a local store (lightweight SQLite table or append-only queue) — plugin never needs direct `heartbeatRunEvents` access
- D-19: Plugin job handler calls `POST /memory/extract` on sidecar — sidecar drains queued transcripts, runs `MemoryBridge.learn_async()` for each, stores structured learnings in Qdrant KNOWLEDGE collection
- D-20: Job uses `ctx.state.set({ scopeKind: "instance", stateKey: "last-learn-at" })` as watermark to avoid re-processing
- D-21: Batch processing — one LLM extraction call per batch of queued transcripts, not per-run

**Memory Browser (run_id Tracing)**
- D-22: Thread `run_id` through `MemoryBridge.recall()` and `learn_async()` into Qdrant point payloads — follows existing `task_id` pattern exactly
- D-23: Add `run_id` as fifth keyword index in `_ensure_task_indexes()` — idempotent, zero-risk on existing collections
- D-24: Memory browser detailTab displays two sections: "Injected Memories" (recalled before run) and "Extracted Learnings" (after run)
- D-25: Empty states: "No memories were recalled for this run" / "No learnings were extracted yet"
- D-26: `run_id` is already propagated via `AdapterExecutionContext.run_id` into `execute_async()` — gap is only passing it down to MemoryBridge and Qdrant storage

### Claude's Discretion
- Exact manifest.json metadata (displayName, description, categories, version updates)
- Exact cron schedule expression for learning extraction job (e.g., `0 * * * *` vs `30 * * * *`)
- Whether to store recalled memory scores in Qdrant payload at recall time vs re-query at display time
- How the memory browser handles the async delay between run completion and learning extraction
- Exact Pydantic model shapes for new endpoint request/response types
- SQLite schema details for `routing_decisions` and `spend_history` tables
- Error response formatting when sidecar endpoints return errors to the UI
- Vitest test file organization for UI components
- Whether `esbuild` script lives in `build-ui.mjs` or inline in `package.json`
- Exact data shapes for `ctx.data.register()` handler responses

### Deferred Ideas (OUT OF SCOPE)
None — discussion stayed within phase scope.
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| UI-01 | Agent effectiveness detailTab on Paperclip agent pages shows tier badge, success rates by task type, model routing history | SDK `detailTab` slot type on `["agent"]` entity; `usePluginData` with `entityId=agentId`; sidecar endpoints D-09, D-10, D-11 supply data |
| UI-02 | Provider health dashboardWidget shows Agent42 provider availability at a glance | SDK `dashboardWidget` slot type; extend existing `GET /sidecar/health` providers dict (D-12); `ctx.data.register()` bridges to widget |
| UI-03 | Memory browser detailTab on run pages shows injected memories and extracted learnings | SDK `detailTab` on `["run"]` entity; `GET /memory/run-trace/{runId}` (D-13); requires `run_id` threading through MemoryBridge (D-22, D-26) |
| UI-04 | Routing decisions dashboardWidget shows token spend distribution over last 24h | SDK `dashboardWidget`; `GET /agent/{agentId}/spend?hours=24` (D-14); requires new `spend_history` SQLite table |
| LEARN-01 | extract_learnings job runs hourly, extracts structured learnings from transcripts, stores in Qdrant | SDK `ctx.jobs.register()` with cron; manifest `jobs[]` + `jobs.schedule` capability; sidecar captures transcripts (D-18); `POST /memory/extract` (D-19) |
| LEARN-02 | Extracted learnings feed into memory_recall results for future agent executions | Learning stored in Qdrant KNOWLEDGE collection via existing `MemoryBridge.learn_async()`; recall already searches KNOWLEDGE |
</phase_requirements>

---

## Summary

Phase 29 adds native Paperclip UI panels (detailTabs + dashboardWidgets) to the existing plugin and closes the intelligence feedback loop via an hourly learning extraction job. The technical surface is four distinct sub-problems: (1) TypeScript React UI bundle built with esbuild using SDK presets, (2) five new sidecar GET endpoints + one POST endpoint backed by existing Python stores, (3) `run_id` threading from `execute_async()` down to MemoryBridge and Qdrant payload storage, and (4) a scheduled plugin job draining a sidecar-maintained transcript queue.

The SDK is installed locally at version `2026.325.0` (March 25, 2026). All critical APIs have been verified from source: `ctx.data.register()`, `ctx.jobs.register()`, `ctx.state.set()`, `PluginDetailTabProps`, `PluginWidgetProps`, `usePluginData`, `createPluginBundlerPresets`, and the full slot schema in `pluginUiSlotDeclarationSchema`. The UI slot system is confirmed production-ready. A critical finding: the SDK README explicitly states shared components (`MetricCard`, `StatusBadge`, etc.) are **declared in types but host implementation is not guaranteed** ("The current host does not provide a real shared component kit for plugins yet"). Decision D-07 assumes these work; the planner must treat them as optional and ensure the UI degrades gracefully to plain HTML/CSS if host components are unavailable.

The Python backend changes are low-risk and follow well-established patterns. `_ensure_task_indexes()` is idempotent. `EffectivenessStore.get_agent_stats()` and `get_aggregated_stats()` already exist but are not wired to routes. The only genuinely new Python work is two SQLite tables (`routing_decisions`, `spend_history`), one POST endpoint (`/memory/extract`), and `run_id` threading.

**Primary recommendation:** Build in three waves — (1) Python sidecar data endpoints + run_id threading, (2) TypeScript UI bundle + manifest update, (3) learning extraction job. Each wave can be tested independently before the next.

---

## Standard Stack

### Core (verified from installed node_modules)
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@paperclipai/plugin-sdk` | `2026.325.0` | Worker lifecycle, UI hooks, test harness, bundler presets | Required by Paperclip plugin runtime |
| `@paperclipai/shared` | (peer dep) | `PLUGIN_CAPABILITIES`, `PLUGIN_UI_SLOT_TYPES`, Zod validators | Shared constants validated from `constants.d.ts` |
| `react` | `^18.x` | UI component rendering | Host provides React at runtime; devDep only |
| `@types/react` | `^18.x` | TypeScript types for JSX | devDep for compile-time checking |
| `esbuild` | `^0.x` (latest) | UI bundle — browser ESM with external react + SDK | `createPluginBundlerPresets()` generates esbuild config |
| `vitest` | `^4.1.2` (existing) | Test runner for both worker and UI components | Already in use; SDK testing harness compatible |
| `typescript` | `^6.0.2` (existing) | Worker compilation (tsc) and type checking | Already in use |
| `aiosqlite` | existing | SQLite async writes for `routing_decisions` + `spend_history` | Already used by EffectivenessStore — same pattern |
| `fastapi` | existing | New sidecar GET/POST endpoints | All sidecar routes use FastAPI |
| `pydantic` | existing | Request/response models for new endpoints | All sidecar models use Pydantic with camelCase aliases |

### Build Toolchain
| Step | Command | Output |
|------|---------|--------|
| Worker build | `tsc` | `dist/worker.js` (Node.js CJS/ESM) |
| UI build | `esbuild` via `createPluginBundlerPresets()` | `dist/ui/` (browser ESM, React externalized) |
| Type check | `tsc --noEmit` | Validates both worker and UI types |
| Tests | `vitest run` | Workers tests + data handler tests |

**Installation for UI work:**
```bash
cd plugins/agent42-paperclip
pnpm add -D react @types/react esbuild
```

**Version verification:**
```bash
cd plugins/agent42-paperclip
cat node_modules/@paperclipai/plugin-sdk/package.json | python3 -c "import sys,json; d=json.load(sys.stdin); print(d['version'])"
# Current: 2026.325.0
```

---

## Architecture Patterns

### Recommended Project Structure (additions to existing plugin)

```
plugins/agent42-paperclip/
├── manifest.json                     # Add: capabilities, entrypoints.ui, ui.slots[], jobs[]
├── src/
│   ├── worker.ts                     # Add: ctx.data.register() x4, ctx.jobs.register()
│   ├── client.ts                     # Add: 6 new API methods
│   ├── types.ts                      # Add: UI data response interfaces
│   ├── tools.ts                      # Unchanged
│   └── ui/
│       ├── index.tsx                 # Re-exports all 4 slot components
│       ├── AgentEffectivenessTab.tsx # detailTab for agent entity
│       ├── ProviderHealthWidget.tsx  # dashboardWidget
│       ├── MemoryBrowserTab.tsx      # detailTab for run entity
│       └── RoutingDecisionsWidget.tsx # dashboardWidget
├── build-ui.mjs                      # esbuild script using createPluginBundlerPresets
├── tests/
│   ├── worker.test.ts               # Existing — extend with data/job handler tests
│   ├── client.test.ts               # Existing — extend with new method tests
│   ├── tools.test.ts                # Unchanged
│   └── data-handlers.test.ts        # New — test ctx.data.register() handler logic
```

```
core/
├── memory_bridge.py                  # Modify: thread run_id through recall() + learn_async()
├── sidecar_models.py                 # Add: Pydantic models for 6 new endpoints
├── sidecar_orchestrator.py           # Modify: pass run_id to MemoryBridge; capture transcript
dashboard/
└── sidecar.py                        # Add: 5 new GET routes + POST /memory/extract
memory/
├── qdrant_store.py                   # Modify: add run_id keyword index in _ensure_task_indexes()
└── effectiveness.py                  # Add: get_agent_stats already exists; add get_routing_history()
```

### Pattern 1: Manifest UI Slot Declaration (verified from pluginUiSlotDeclarationSchema)

```json
// manifest.json additions
{
  "capabilities": [
    "http.outbound",
    "agent.tools.register",
    "ui.detailTab.register",
    "ui.dashboardWidget.register",
    "jobs.schedule",
    "plugin.state.write"
  ],
  "entrypoints": {
    "worker": "./dist/worker.js",
    "ui": "./dist/ui"
  },
  "ui": {
    "slots": [
      {
        "type": "detailTab",
        "id": "agent-effectiveness",
        "displayName": "Effectiveness",
        "exportName": "AgentEffectivenessTab",
        "entityTypes": ["agent"]
      },
      {
        "type": "dashboardWidget",
        "id": "provider-health",
        "displayName": "Agent42 Provider Health",
        "exportName": "ProviderHealthWidget"
      },
      {
        "type": "detailTab",
        "id": "memory-browser",
        "displayName": "Memory",
        "exportName": "MemoryBrowserTab",
        "entityTypes": ["run"]
      },
      {
        "type": "dashboardWidget",
        "id": "routing-decisions",
        "displayName": "Agent42 Routing",
        "exportName": "RoutingDecisionsWidget"
      }
    ]
  },
  "jobs": [
    {
      "jobKey": "extract-learnings",
      "displayName": "Extract Learnings",
      "description": "Hourly job that extracts structured learnings from Paperclip run transcripts",
      "schedule": "0 * * * *"
    }
  ]
}
```

**Key constraint from schema:** `entityTypes` is REQUIRED for `detailTab` and `taskDetailView` types. The Zod validator has a `superRefine` check enforcing this.

### Pattern 2: UI Slot Component (from SDK README §19)

```tsx
// Source: @paperclipai/plugin-sdk/dist/ui/types.d.ts
import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginDetailTabProps } from "@paperclipai/plugin-sdk/ui";

export function AgentEffectivenessTab({ context }: PluginDetailTabProps) {
  // context.entityId = Paperclip agent UUID
  // context.companyId = current company
  const { data, loading, error } = usePluginData<AgentProfileResponse>(
    "agent-profile",
    { agentId: context.entityId, companyId: context.companyId }
  );

  if (loading) return <div>Loading...</div>;
  if (error) return <div>Error: {error.message}</div>;
  if (!data) return <p>No effectiveness data for this agent.</p>;

  return (
    <div>
      <span>{data.tier}</span>
      <span>{(data.successRate * 100).toFixed(1)}% success rate</span>
    </div>
  );
}
```

```tsx
// dashboardWidget — no entityId, only companyId
import type { PluginWidgetProps } from "@paperclipai/plugin-sdk/ui";

export function ProviderHealthWidget({ context }: PluginWidgetProps) {
  const { data, loading } = usePluginData<ProviderHealthResponse>(
    "provider-health",
    { companyId: context.companyId }
  );
  // ...
}
```

### Pattern 3: ctx.data.register() Bridge Handler (verified from SDK README)

```typescript
// worker.ts — in setup()
// Source: @paperclipai/plugin-sdk README §Worker quick start
ctx.data.register("agent-profile", async (params) => {
  const agentId = params?.agentId as string | undefined;
  const companyId = params?.companyId as string | undefined;
  if (!agentId || !client) return null;
  return client.getAgentProfile(agentId, companyId);
});

ctx.data.register("provider-health", async (_params) => {
  if (!client) return null;
  return client.health();
});

ctx.data.register("memory-run-trace", async (params) => {
  const runId = params?.runId as string | undefined;
  if (!runId || !client) return null;
  return client.getMemoryRunTrace(runId);
});

ctx.data.register("routing-decisions", async (params) => {
  const agentId = params?.agentId as string | undefined;
  const hours = (params?.hours as number) ?? 24;
  if (!client) return null;
  return client.getAgentSpend(agentId, hours);
});
```

### Pattern 4: Scheduled Job Registration (verified from SDK README §17)

```typescript
// manifest.json — already shown above with jobs[] array
// Capability: "jobs.schedule", "plugin.state.write"

// worker.ts — in setup()
// Source: @paperclipai/plugin-sdk README §Scheduled jobs
ctx.jobs.register("extract-learnings", async (job) => {
  // Read watermark to avoid re-processing
  const lastLearnAt = await ctx.state.get({
    scopeKind: "instance",
    stateKey: "last-learn-at",
  });

  if (!client) {
    ctx.logger.warn("extract-learnings: client not initialized");
    return;
  }

  await client.extractLearnings({
    sinceTs: (lastLearnAt as string) ?? null,
    batchSize: 20,
  });

  // Update watermark
  await ctx.state.set(
    { scopeKind: "instance", stateKey: "last-learn-at" },
    new Date().toISOString()
  );
});
```

### Pattern 5: esbuild UI Bundle (verified from bundlers.d.ts)

```javascript
// build-ui.mjs
// Source: @paperclipai/plugin-sdk/dist/bundlers.d.ts
import { createPluginBundlerPresets } from "@paperclipai/plugin-sdk/bundlers";
import { build } from "esbuild";

const presets = createPluginBundlerPresets({
  pluginRoot: ".",
  uiEntry: "./src/ui/index.tsx",
  outdir: "./dist",
});

// presets.esbuild.ui = { entryPoints, outdir, bundle: true, format: "esm",
//   platform: "browser", target: "...", external: ["react", "@paperclipai/..."] }
await build(presets.esbuild.ui);
```

**package.json script additions:**
```json
{
  "scripts": {
    "build": "tsc && node build-ui.mjs",
    "build:worker": "tsc",
    "build:ui": "node build-ui.mjs",
    "test": "vitest run",
    "typecheck": "tsc --noEmit"
  }
}
```

### Pattern 6: run_id Threading Through MemoryBridge (following existing task_id pattern)

```python
# core/memory_bridge.py — recall() signature addition
async def recall(
    self,
    query: str,
    agent_id: str,
    company_id: str = "",
    top_k: int = 5,
    score_threshold: float = 0.25,
    run_id: str = "",         # NEW: thread through to payload storage
) -> list[dict]:
    # ...
    payload = {
        "text": ...,
        "source": "recall",
        "agent_id": agent_id,
        "run_id": run_id,     # NEW: store in Qdrant point for later run-trace queries
        # ...
    }
```

```python
# memory/qdrant_store.py — add run_id to _ensure_task_indexes()
def _ensure_task_indexes(self, collection_name: str):
    # existing: task_type, task_id, agent_id, company_id indexes
    # NEW — add run_id as 5th keyword index:
    self._client.create_payload_index(
        collection_name=collection_name,
        field_name="run_id",
        field_schema=PayloadSchemaType.KEYWORD,
    )
```

### Pattern 7: New SQLite Tables (following EffectivenessStore pattern)

```python
# routing_decisions table
CREATE TABLE IF NOT EXISTS routing_decisions (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL,
    agent_id     TEXT    NOT NULL,
    company_id   TEXT    NOT NULL DEFAULT '',
    provider     TEXT    NOT NULL,
    model        TEXT    NOT NULL,
    tier         TEXT    NOT NULL,
    task_category TEXT   NOT NULL,
    ts           REAL    NOT NULL
)
# Index: (agent_id, ts DESC) for recent-N queries

# spend_history table
CREATE TABLE IF NOT EXISTS spend_history (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    agent_id     TEXT    NOT NULL,
    company_id   TEXT    NOT NULL DEFAULT '',
    provider     TEXT    NOT NULL,
    model        TEXT    NOT NULL,
    input_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    cost_usd     REAL    NOT NULL DEFAULT 0.0,
    hour_bucket  TEXT    NOT NULL,   -- ISO8601 truncated to hour: "2026-03-30T14:00:00"
    ts           REAL    NOT NULL
)
# Index: (agent_id, hour_bucket) for 24h spend queries
```

### Pattern 8: Sidecar Transcript Queue for LEARN-01 (D-18)

```python
# SQLite table in EffectivenessStore or a dedicated store
CREATE TABLE IF NOT EXISTS run_transcripts (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id       TEXT    NOT NULL UNIQUE,
    agent_id     TEXT    NOT NULL,
    company_id   TEXT    NOT NULL DEFAULT '',
    task_type    TEXT    NOT NULL DEFAULT '',
    summary      TEXT    NOT NULL,  -- execution result summary
    extracted    INTEGER NOT NULL DEFAULT 0,  -- 0=pending, 1=extracted
    ts           REAL    NOT NULL
)
# Index: (extracted, ts) for draining unprocessed queue
```

### Anti-Patterns to Avoid

- **Shared components as hard dependency:** The SDK README says "The current host does not provide a real shared component kit for plugins yet." Components declared in `dist/ui/components.d.ts` exist as type stubs but host runtime injection is not guaranteed. Use them with plain HTML fallback or avoid entirely and use plain React + inline styles.
- **ctx.data.register() key collisions:** Each key must be globally unique per plugin instance. Use descriptive keys like `"agent-profile"`, `"provider-health"`, `"memory-run-trace"`, `"routing-decisions"` — not bare `"profile"` or `"health"`.
- **Blocking setup() with async work:** `ctx.data.register()` and `ctx.jobs.register()` are synchronous registration calls. The handlers themselves are async but registration must complete before `setup()` resolves. The existing `registerTools(ctx, client)` call shows the correct synchronous pattern.
- **run_id as required parameter in recall():** Adding `run_id` as optional with default `""` keeps backward compatibility. Never make it required — internal recall calls from the sidecar HTTP route don't have a Paperclip run context.
- **Iframe or direct DOM manipulation:** PITFALL P8/P11 — plugin UI runs as same-origin JavaScript, not in an iframe. No postMessage hacks needed; the bridge hooks handle all communication.

---

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| React component data fetching | Custom fetch wrappers in UI components | `usePluginData(key, params)` from `@paperclipai/plugin-sdk/ui` | Hook manages loading state, error, caching, and re-fetch — all in 1 line |
| Plugin worker test harness | Mock PluginContext from scratch | `createTestHarness()` from `@paperclipai/plugin-sdk/testing` | Enforces capabilities, simulates all ctx APIs, supports `getData()` and `runJob()` assertions |
| esbuild config for browser ESM | Custom esbuild config with React external list | `createPluginBundlerPresets()` from `@paperclipai/plugin-sdk/bundlers` | Knows the correct external list for the host module registry |
| Watermark / job dedup logic | Custom timestamp tracking | `ctx.state.set({ scopeKind: "instance", stateKey: "..." }, value)` | SDK-managed persistent state, survives worker restarts |
| Slot manifest schema validation | Hand-written JSON schema checks | `pluginUiSlotDeclarationSchema` from `@paperclipai/shared/dist/validators/plugin` | Zod validator enforces entityTypes requirement for detailTab |
| Qdrant keyword index for new field | New index function | Add one `create_payload_index()` call to existing `_ensure_task_indexes()` | Function is already idempotent; Qdrant silently no-ops if index exists |
| Learning extraction LLM calls | New LLM client | `MemoryBridge.learn_async()` (already implements instructor + Gemini/GPT-4o-mini) | Existing, tested, fire-and-forget safe |

**Key insight:** The data-bridge pattern (`ctx.data.register()` + `usePluginData()`) is the entire state management story for plugin UI. There is no Redux, no Context API, no custom WebSocket. Worker registers a key → UI fetches by key → done.

---

## Common Pitfalls

### Pitfall 1: SDK Shared Components Not Injected by Host
**What goes wrong:** UI crashes with "MetricCard is not a function" or renders nothing because the host module registry doesn't inject the component runtime.
**Why it happens:** The SDK README explicitly states "The current host does not provide a real shared component kit for plugins yet." `dist/ui/components.d.ts` exports type declarations but the runtime implementation must be provided by the host module registry — which the current build does not reliably do.
**How to avoid:** Either (a) don't use shared components at all and use plain React + inline styles, OR (b) import from `@paperclipai/plugin-sdk/ui/components` but wrap each use in a try-catch or null-check and fall back to plain HTML. Do not import shared components as unconditional hard dependencies.
**Warning signs:** TypeScript compiles fine but component renders as blank at runtime.

### Pitfall 2: Missing entityTypes on detailTab Slots
**What goes wrong:** Manifest validation fails at install time with `CAPABILITY_DENIED` or silent slot rejection.
**Why it happens:** `pluginUiSlotDeclarationSchema` has a `superRefine` validator that REQUIRES `entityTypes` when `type === "detailTab"` or `type === "taskDetailView"`. The validator rejects the manifest.
**How to avoid:** Always include `"entityTypes": ["agent"]` for the effectiveness tab and `"entityTypes": ["run"]` for the memory browser tab.
**Warning signs:** Plugin installs but tabs never appear in Paperclip UI.

### Pitfall 3: Forgetting plugin.state.write Capability for Job Watermark
**What goes wrong:** `ctx.state.set()` throws `CAPABILITY_DENIED` at runtime.
**Why it happens:** D-20 requires `ctx.state.set()` for the watermark. State write requires `"plugin.state.write"` capability declared in manifest. The current manifest only has `"http.outbound"` and `"agent.tools.register"`.
**How to avoid:** Add `"plugin.state.write"` to manifest capabilities alongside `"jobs.schedule"`.
**Warning signs:** Job completes but watermark is never updated, causing re-processing of all transcripts on next run.

### Pitfall 4: UI Entry Point Must Be a Directory, Not a File
**What goes wrong:** Paperclip host fails to load UI bundle silently or crashes.
**Why it happens:** D-03 specifies `"entrypoints.ui": "./dist/ui"` (directory). The SDK bundler contract requires the host to look for component exports from this directory, not a single file.
**How to avoid:** Confirm `esbuild` outputs to `dist/ui/` (directory) and that the esbuild preset's `outdir` is `dist/ui`. The `createPluginBundlerPresets()` `outdir` option controls this.
**Warning signs:** Worker runs fine but UI slots never register in Paperclip.

### Pitfall 5: run_id Not Stored in Qdrant Points for Recalled Memories
**What goes wrong:** `GET /memory/run-trace/{runId}` returns empty "injected memories" section even for runs that had active recall.
**Why it happens:** D-22 requires threading `run_id` into the Qdrant payload at recall time. The current `MemoryBridge.recall()` returns results but does NOT write the `run_id` back into the Qdrant points. A separate upsert-with-run_id step is needed, OR the payload must be written when memories are stored pre-run.
**How to avoid:** Two options: (a) add a lightweight Qdrant metadata update after recall recording which `run_id` consumed each memory point, OR (b) when MemoryBridge.recall() returns results, create new "recall event" Qdrant points in a HISTORY/MEMORY collection with the `run_id` payload field set. Option (b) is simpler and avoids modifying existing points.
**Warning signs:** Memory browser tab shows "No memories were recalled" for all runs.

### Pitfall 6: transcript Queue Never Drained (D-18/D-19)
**What goes wrong:** Hourly job runs but Qdrant KNOWLEDGE collection never grows.
**Why it happens:** The sidecar must write execution summaries to the `run_transcripts` SQLite table during `execute_async()`. If the transcript capture step is missing or writes empty strings, the `POST /memory/extract` endpoint has nothing to process.
**How to avoid:** Add transcript capture in `execute_async()` BEFORE the callback POST, in the same `finally` block. Write `result["summary"]` (or a structured summary) to `run_transcripts` with `extracted=0`.
**Warning signs:** `run_transcripts` table remains empty after executions.

### Pitfall 7: Cron Schedule Capability Mismatch
**What goes wrong:** Job never runs; Paperclip silently ignores `manifest.jobs` or logs `CAPABILITY_DENIED`.
**Why it happens:** Both `"jobs.schedule"` (runtime capability) AND the `jobs[]` array in manifest must be present. Missing either prevents job registration.
**How to avoid:** Verify both: `"capabilities": [..., "jobs.schedule"]` AND `"jobs": [{ "jobKey": "extract-learnings", ... }]` are present in manifest.json before testing.
**Warning signs:** `ctx.jobs.register()` in worker doesn't throw but job never fires.

---

## Code Examples

### ctx.data.register() in worker.ts

```typescript
// Source: @paperclipai/plugin-sdk README §Worker quick start (verified)
// All 4 data handlers registered synchronously before setup() resolves

// In setup(ctx):
ctx.data.register("agent-profile", async (params) => {
  const { agentId, companyId } = params as { agentId?: string; companyId?: string };
  if (!agentId || !client) return null;
  return client.getAgentProfile(agentId, companyId ?? "");
});

ctx.data.register("provider-health", async (_params) => {
  if (!client) return null;
  return client.health();
});

ctx.data.register("memory-run-trace", async (params) => {
  const { runId } = params as { runId?: string };
  if (!runId || !client) return null;
  return client.getMemoryRunTrace(runId);
});

ctx.data.register("routing-decisions", async (params) => {
  const { agentId, hours } = params as { agentId?: string; hours?: number };
  if (!client) return null;
  return client.getAgentSpend(agentId ?? "", hours ?? 24);
});
```

### usePluginData Hook in UI Component

```tsx
// Source: @paperclipai/plugin-sdk/dist/ui/hooks.d.ts (verified)
// PluginDetailTabProps.context always has entityId + entityType (non-null)
import { usePluginData } from "@paperclipai/plugin-sdk/ui";
import type { PluginDetailTabProps } from "@paperclipai/plugin-sdk/ui";

export function MemoryBrowserTab({ context }: PluginDetailTabProps) {
  const { data, loading, error } = usePluginData<MemoryRunTraceResponse>(
    "memory-run-trace",
    { runId: context.entityId }
  );

  if (loading) return <p>Loading memory trace...</p>;
  if (error) return <p>Error loading trace: {error.message}</p>;
  if (!data) return <p>No memory data available.</p>;

  return (
    <div>
      <h3>Injected Memories ({data.injectedMemories.length})</h3>
      {data.injectedMemories.length === 0 && <p>No memories were recalled for this run.</p>}
      {data.injectedMemories.map((m, i) => (
        <div key={i}>{m.text} — {(m.score * 100).toFixed(0)}% relevance</div>
      ))}

      <h3>Extracted Learnings ({data.extractedLearnings.length})</h3>
      {data.extractedLearnings.length === 0 && (
        <p>No learnings extracted yet. Extraction runs hourly.</p>
      )}
      {data.extractedLearnings.map((l, i) => (
        <div key={i}>{l.content}</div>
      ))}
    </div>
  );
}
```

### Sidecar Endpoint Pattern (camelCase aliases, Bearer auth)

```python
# Source: dashboard/sidecar.py existing endpoints — follow exact pattern
# All new endpoints: Bearer auth, camelCase aliases, graceful degradation

from core.sidecar_models import AgentProfileResponse  # new model

@app.get("/agent/{agent_id}/profile", response_model=AgentProfileResponse)
async def agent_profile(
    agent_id: str,
    _user: str = Depends(get_current_user),
) -> AgentProfileResponse:
    """Return tier badge + composite score + stats for an agent (D-09)."""
    if not effectiveness_store:
        return AgentProfileResponse(agentId=agent_id, tier="bronze", successRate=0.0, taskVolume=0)
    stats = await effectiveness_store.get_agent_stats(agent_id)
    if stats is None:
        return AgentProfileResponse(agentId=agent_id, tier="bronze", successRate=0.0, taskVolume=0)
    # resolve tier from reward_system if available
    tier = "bronze"
    if reward_system:
        try:
            tier_result = reward_system.get_tier(agent_id)
            tier = tier_result.name.lower() if tier_result else "bronze"
        except Exception:
            pass
    return AgentProfileResponse(
        agentId=agent_id,
        tier=tier,
        successRate=stats["success_rate"],
        taskVolume=stats["task_volume"],
        avgSpeedMs=stats["avg_speed"],
    )
```

### Testing Worker Data Handlers

```typescript
// Source: @paperclipai/plugin-sdk/dist/testing.d.ts (verified)
// TestHarness.getData(key, params) invokes ctx.data.register() handlers directly

import { describe, it, expect, vi, beforeEach } from "vitest";
import { createTestHarness } from "@paperclipai/plugin-sdk/testing";
import manifest from "../manifest.json" with { type: "json" };
import plugin from "../src/worker.js";

describe("Data handlers", () => {
  it("agent-profile handler returns null when client not initialized", async () => {
    const harness = createTestHarness({
      manifest: manifest as any,
      config: { agent42BaseUrl: "", apiKey: "" },
    });
    // Don't call setup() — client stays null
    const result = await harness.getData("agent-profile", { agentId: "agent-1" });
    expect(result).toBeNull();
  });

  it("extract-learnings job calls extractLearnings endpoint", async () => {
    const mockExtract = vi.fn().mockResolvedValue({ extracted: 3 });
    // ... setup harness with mock client
    await harness.runJob("extract-learnings");
    expect(mockExtract).toHaveBeenCalledOnce();
  });
});
```

---

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Plugin SDK `health()` hook name | `onHealth()` hook name | Phase 28 discovery (Pitfall 2) | Already encoded in current worker.ts |
| Plugin config via separate `initialize(config)` export | Config via `ctx.config.get()` inside `setup()` | Phase 28 discovery (Pitfall 1) | Already encoded in current worker.ts |
| Shared component library promised | Not available in current host runtime | SDK v2026.325.0 README caveat | D-07 must be treated as aspirational; use plain React |
| `heartbeatRunEvents` access from plugin context | Not available; transcript capture must happen in sidecar | Phase 29 research resolution | D-18 correctly captures transcripts server-side |
| `plugin_state` scope key name | `stateKey` field in ScopeKey interface | Verified from `types.d.ts` | D-20 uses correct `stateKey` field name |

**Deprecated/outdated:**
- Do NOT look for `ctx.state.set(scopeKind, stateKey, value)` positional API — the actual signature is `ctx.state.set(scopeKey: ScopeKey, value: unknown)` where ScopeKey is `{ scopeKind, stateKey, scopeId?, namespace? }`.

---

## Open Questions

1. **Shared component runtime availability**
   - What we know: Type declarations exist in `@paperclipai/plugin-sdk/ui/components`. SDK README explicitly says "The current host does not provide a real shared component kit for plugins yet."
   - What's unclear: Whether version `2026.325.0` actually provides runtime implementations (the README caveat may be stale).
   - Recommendation: Write UI components with plain React. If shared components work, they are a bonus. If they don't work, the UI is still functional.

2. **EffectivenessStore get_agent_stats() — agent_id filtering**
   - What we know: `get_agent_stats(agent_id)` exists and filters by `agent_id` column. The `agent_id` column was added via `ALTER TABLE` migration.
   - What's unclear: Whether all historical `tool_invocations` rows have `agent_id` populated (rows before the migration have `DEFAULT ''`).
   - Recommendation: Endpoint returns `null`/empty when no records match — acceptable for new agents. No backfill needed.

3. **Per-task-type breakdown in get_aggregated_stats()**
   - What we know: `get_aggregated_stats(tool_name="", task_type="")` returns all tool+task_type pairs. An `agent_id` filter doesn't exist yet.
   - What's unclear: The endpoint D-10 needs `get_aggregated_stats(agent_id=agent_id)` — requires adding an `agent_id` parameter to the existing method.
   - Recommendation: Extend `get_aggregated_stats()` with optional `agent_id: str = ""` parameter. Low-risk additive change.

4. **TierCache vs reward_system.get_tier() API**
   - What we know: `TierCache` is mentioned in CONTEXT.md as a source for tier data. `RewardSystem` exists as a class.
   - What's unclear: The exact method name to get current tier for an agent from `RewardSystem`.
   - Recommendation: Check `core/reward_system.py` during implementation. The endpoint should degrade gracefully if tier lookup fails (default to "bronze").

---

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | TypeScript/esbuild build | Assumed (pnpm already works) | >=18.0.0 required | — |
| pnpm | Plugin build | Assumed (Phase 28 used it) | 9.15+ required | npm |
| esbuild | UI bundle build | Not yet installed | latest | Must install: `pnpm add -D esbuild` |
| react + @types/react | UI components | Not yet installed | ^18.x | Must install: `pnpm add -D react @types/react` |
| Python / aiosqlite | New SQLite tables | Existing (.venv) | aiosqlite installed | — |
| Qdrant | run_id index + KNOWLEDGE queries | Available (.agent42/qdrant/) | 1.17.0 embedded | Graceful degradation if unavailable |

**Missing dependencies requiring installation:**
- `esbuild` — needed for UI bundle build step (`pnpm add -D esbuild` in plugin directory)
- `react` + `@types/react` — needed for JSX compilation (`pnpm add -D react @types/react`)

**Missing dependencies with no fallback (blocking):**
- None — all sidecar Python deps are already available; TS deps are installable.

---

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework (TypeScript) | Vitest 4.1.2 (existing) |
| Framework (Python) | pytest (existing) |
| Config file (TS) | `vitest.config.ts` or inline in `package.json` |
| Quick run (TS) | `cd plugins/agent42-paperclip && pnpm test` |
| Quick run (Python) | `python -m pytest tests/test_memory_bridge.py tests/test_sidecar.py tests/test_effectiveness.py -x -q` |
| Full suite | `python -m pytest tests/ -x -q && cd plugins/agent42-paperclip && pnpm test` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| UI-01 | `ctx.data.register("agent-profile")` handler returns correct shape | unit (TS) | `pnpm test -- data-handlers` | Wave 0 gap |
| UI-02 | `ctx.data.register("provider-health")` handler calls client.health() | unit (TS) | `pnpm test -- data-handlers` | Wave 0 gap |
| UI-03 | `ctx.data.register("memory-run-trace")` handler calls client.getMemoryRunTrace() | unit (TS) | `pnpm test -- data-handlers` | Wave 0 gap |
| UI-03 | `run_id` stored in Qdrant payload after recall() | unit (Python) | `pytest tests/test_memory_bridge.py -x -q` | Exists (extend) |
| UI-04 | `ctx.data.register("routing-decisions")` handler calls correct endpoint | unit (TS) | `pnpm test -- data-handlers` | Wave 0 gap |
| UI-04 | `GET /agent/{id}/spend` returns spend breakdown from SQLite | unit (Python) | `pytest tests/test_sidecar.py -x -q` | Exists (extend) |
| LEARN-01 | extract-learnings job invokes `POST /memory/extract` | unit (TS) | `pnpm test -- data-handlers` | Wave 0 gap |
| LEARN-01 | `POST /memory/extract` drains run_transcripts queue | unit (Python) | `pytest tests/test_sidecar.py -x -q` | Exists (extend) |
| LEARN-02 | After extraction, `POST /memory/recall` returns extracted learnings | integration (Python) | `pytest tests/test_memory_bridge.py -x -q` | Exists (extend) |
| — | New sidecar endpoints require Bearer auth | unit (Python) | `pytest tests/test_sidecar.py -x -q` | Exists (extend) |
| — | run_id keyword index idempotent on collection re-init | unit (Python) | `pytest tests/test_qdrant_fallback.py -x -q` | Exists (extend) |

### Sampling Rate
- **Per task commit:** `cd plugins/agent42-paperclip && pnpm test` (TS) or `python -m pytest tests/test_memory_bridge.py tests/test_sidecar.py -x -q` (Python)
- **Per wave merge:** Full suite: `python -m pytest tests/ -x -q && cd plugins/agent42-paperclip && pnpm test`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `plugins/agent42-paperclip/tests/data-handlers.test.ts` — covers UI-01, UI-02, UI-03, UI-04, LEARN-01 (new file)
- [ ] `plugins/agent42-paperclip/vitest.config.ts` — if not already present; check `package.json` "test" script
- [ ] Python: extend `tests/test_sidecar.py` with new endpoint tests
- [ ] Python: extend `tests/test_memory_bridge.py` with run_id threading tests

---

## Sources

### Primary (HIGH confidence)
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/README.md` (v2026.325.0) — UI slots §19, jobs §17, data bridge §20, hooks, bundler presets
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/ui/types.d.ts` — PluginDetailTabProps, PluginWidgetProps, usePluginData, PluginHostContext
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/ui/hooks.d.ts` — hook signatures
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/ui/components.d.ts` — shared component type declarations + runtime availability caveat
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/bundlers.d.ts` — createPluginBundlerPresets interface
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/testing.d.ts` — createTestHarness, TestHarness.getData(), TestHarness.runJob()
- `plugins/agent42-paperclip/node_modules/@paperclipai/shared/dist/constants.d.ts` — PLUGIN_CAPABILITIES, PLUGIN_UI_SLOT_TYPES, PLUGIN_UI_SLOT_ENTITY_TYPES
- `plugins/agent42-paperclip/node_modules/@paperclipai/shared/dist/validators/plugin.d.ts` — pluginUiSlotDeclarationSchema (entityTypes requirement)
- `core/memory_bridge.py` — recall() + learn_async() signatures, patterns
- `memory/qdrant_store.py` — _ensure_task_indexes() pattern for run_id addition
- `memory/effectiveness.py` — get_agent_stats(), get_aggregated_stats() implementations
- `core/sidecar_orchestrator.py` — execute_async() structure, where transcript capture goes
- `dashboard/sidecar.py` — existing endpoint patterns (auth, models, graceful degradation)
- `plugins/agent42-paperclip/manifest.json` — current manifest state
- `plugins/agent42-paperclip/src/worker.ts` — existing setup() pattern
- `plugins/agent42-paperclip/src/client.ts` — Agent42Client fetch patterns to extend
- `plugins/agent42-paperclip/tests/worker.test.ts` — existing test patterns with createTestHarness

### Secondary (MEDIUM confidence)
- `.planning/phases/29-plugin-ui-learning-extraction/29-CONTEXT.md` — locked decisions D-01 through D-26
- `.planning/research/FEATURES.md` — feature landscape, dependency graph
- `.planning/research/SUMMARY.md` — Phase 3 research flags, pitfalls P8/P11

### Tertiary (LOW confidence / needs validation)
- D-07 shared components assumption — cross-referenced against SDK README caveat; LOW confidence that host provides runtime implementations

---

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — verified from installed node_modules at v2026.325.0
- Architecture patterns: HIGH — verified from type signatures and existing codebase
- Shared component availability: LOW — SDK README explicitly says not provided yet; type stubs only
- Pitfalls: HIGH — derived from verified SDK source + existing Phase 28 pitfalls

**Research date:** 2026-03-30
**Valid until:** 2026-04-14 (14 days — Paperclip SDK releases frequently; verify manifest schema before implementing if > 7 days elapsed)

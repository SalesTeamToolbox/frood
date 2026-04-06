# Phase 36: Paperclip Integration Core - Research

**Researched:** 2026-04-03
**Domain:** Paperclip Plugin SDK UI extension, FastAPI REST/WebSocket, React components in plugin slots
**Confidence:** HIGH

## Summary

Phase 36 adds Agent42 workspace features — coding terminal, sandboxed apps, tools/skills, and settings — into the Paperclip dashboard via the existing plugin SDK UI extension model. The infrastructure foundation is already complete: the sidecar server (Phase 24), tool proxy endpoints (Phase 28), and four UI slot components (Phase 29) are all shipped and working. This phase extends that plugin further.

The Paperclip Plugin SDK `page` slot type is the right vehicle for workspace-heavy features (coding terminal, sandboxed apps) that need full-screen real estate. The existing `detailTab` and `dashboardWidget` slots are right for tools/skills and settings panels. All Agent42 REST API and WebSocket endpoints required already exist in `dashboard/server.py`. The work is primarily: (1) adding new SDK UI slot declarations to the manifest, (2) implementing new React components, (3) adding new `ctx.data.register` / `ctx.actions.register` handlers in the worker, and (4) adding a small number of new sidecar endpoints to bridge the gap. No new backend infrastructure is needed.

The key constraint is that Paperclip plugin UI runs as same-origin JavaScript inside the host app. Plugin components CANNOT directly access host internals; all communication goes through the bridge (`usePluginData`, `usePluginAction`, `usePluginStream`). WebSocket terminal connections must be proxied through the sidecar — the plugin registers a `ctx.streams` or `ctx.actions` handler that passes terminal I/O through the bridge.

**Primary recommendation:** Use the `page` slot for coding terminal and sandboxed apps launcher (full-page real estate). Use `settingsPage` for Agent42 settings override. Use `detailTab` on `project` entity type for tools/skills panel. Add sidebar navigation (`sidebar` or `sidebarPanel`) to surface Agent42 features from Paperclip's main nav. Redundant dashboard removal (PAPERCLIP-05) means conditionally disabling or redirecting the Agent42 standalone dashboard when sidecar mode is active.

## Project Constraints (from CLAUDE.md)

- **All I/O is async** — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools.
- **Frozen config** — `Settings` dataclass in `core/config.py`. Add fields there + `from_env()` + `.env.example`.
- **Graceful degradation** — Redis, Qdrant, MCP are optional. Handle absence, never crash.
- **Sandbox always on** — validate paths via `sandbox.resolve_path()`. Never disable in prod.
- **Security requirements** — never disable sandbox, always use bcrypt hash, always validate file paths.
- **Never log API keys, passwords, or tokens.**
- **All providers use OpenAI Chat Completions compatible APIs.**
- **Backward compatible** — users without new API keys keep existing routing.

<user_constraints>
## User Constraints (from CONTEXT.md)

### Locked Decisions

- **D-01:** Workspace coding terminal integrated as native Paperclip UI component that communicates with Agent42 sidecar via WebSocket for real-time interaction
- **D-02:** Sandboxed apps integrated through contextual panels that appear based on user workflow and task context
- **D-03:** Tools and skills exposed through Paperclip's existing tool registry system, leveraging the MCP tool proxy pattern established in Phase 28
- **D-04:** Settings management integrated into Paperclip's admin interface with clear separation between Paperclip-native and Agent42-specific settings
- **D-05:** Unified sidebar approach - Agent42 features added to existing Paperclip sidebar navigation with clear visual distinction
- **D-06:** Seamless integration where Agent42 features feel like native part of Paperclip while maintaining clear identity
- **D-07:** Consistent design language following Paperclip's existing UI patterns and component library
- **D-08:** Responsive design that works across different screen sizes and device types
- **D-09:** HTTP REST API communication between Paperclip frontend and Agent42 sidecar - leveraging existing patterns from Paperclip plugin (Phase 28)
- **D-10:** Paperclip handles authentication, Agent42 trusts Paperclip context with token forwarding for API calls
- **D-11:** Shared state management through Paperclip's existing context system, with Agent42 state scoped appropriately
- **D-12:** Real-time updates via WebSocket connections where needed (terminal, app status, etc.)
- **D-13:** Equal priority for all core workspace features - coding terminal, sandboxed apps, and tools/skills integrated together
- **D-14:** Progressive enhancement approach - start with core functionality and add advanced features incrementally
- **D-15:** Preserve essential Agent42 workspace functionality while adapting to Paperclip's interaction patterns
- **D-16:** Performance optimization to ensure integrated features don't impact Paperclip's responsiveness

### Claude's Discretion
- Exact UI component implementations and styling details
- Specific WebSocket message formats and protocols
- Detailed authentication token handling and security measures
- Performance optimization techniques and caching strategies
- Error handling and user feedback mechanisms
- Specific integration points and API endpoint designs
- Testing strategies for integrated components

### Deferred Ideas (OUT OF SCOPE)

None — discussion stayed within phase scope
</user_constraints>

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|------------------|
| PAPERCLIP-01 | When Paperclip is active, integrate workspace coding terminal into Paperclip dashboard | `page` slot + `usePluginStream` for WebSocket terminal I/O; sidecar `/ws/terminal` proxied via worker stream handler |
| PAPERCLIP-02 | When Paperclip is active, integrate sandboxed apps into Paperclip dashboard | `page` slot for apps launcher + `detailTab` on project entity; REST `/api/apps/*` endpoints already exist in dashboard/server.py |
| PAPERCLIP-03 | When Paperclip is active, integrate tools and skills into Paperclip dashboard | `detailTab` on project entity + `dashboardWidget`; existing `/api/tools`, `/api/skills` endpoints, plus MCP tool proxy already wired |
| PAPERCLIP-04 | Retain settings management in Paperclip dashboard | `settingsPage` slot replaces auto-generated config form; new sidecar endpoint `GET /settings` + `POST /settings` bridges to KeyStore and Settings |
| PAPERCLIP-05 | Remove redundant Agent42 dashboard components when Paperclip is active | Conditional routing in agent42.py: when `sidecar_enabled=true`, disable or redirect `/` standalone dashboard to avoid duplication |
</phase_requirements>

## Standard Stack

### Core
| Library | Version | Purpose | Why Standard |
|---------|---------|---------|--------------|
| `@paperclipai/plugin-sdk` | `*` (installed) | Plugin lifecycle, UI slots, bridge hooks | Required by Paperclip host; already installed |
| React 18 | `^18.3.1` (devDep) | UI component rendering | Host provides React at runtime; plugin bundles only use types |
| TypeScript | `^6.0.2` | Plugin source language | Existing codebase convention |
| esbuild | `^0.25.0` | UI bundle compilation | Already in place via `build-ui.mjs` |
| Vitest | `^4.1.2` | Plugin unit tests | Already in place |
| FastAPI | existing | Sidecar REST endpoints | All backend work uses existing FastAPI app |
| pytest | `9.0.2` | Python backend tests | Project standard |

### Supporting
| Library | Version | Purpose | When to Use |
|---------|---------|---------|-------------|
| `usePluginData` (SDK hook) | bundled | Fetch data from worker handler | Read-only data panels (tools list, app list, settings) |
| `usePluginAction` (SDK hook) | bundled | Trigger worker actions | Start/stop app, toggle tool, update setting |
| `usePluginStream` (SDK hook) | bundled | SSE real-time stream | Terminal I/O, app log tail |
| `ctx.streams.emit` (SDK worker) | bundled | Push SSE events to UI | Worker side of terminal stream |
| `ctx.actions.register` (SDK worker) | bundled | Handle UI action calls | Start/stop app, send terminal input |
| httpx | existing | HTTP client for sidecar calls | All worker→sidecar HTTP calls |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `page` slot for terminal | `dashboardWidget` | Widget doesn't have enough space for terminal; page slot gives full-screen real estate |
| `usePluginStream` for terminal | WebSocket directly from UI | Plugin UI cannot directly open sockets to external services; must go through bridge |
| `settingsPage` slot | Custom `page` slot | `settingsPage` is the canonical slot for plugin settings override; integrates with Paperclip's settings nav |

**Installation:** No new packages needed. All SDK dependencies are already installed.

**Version verification:**

```bash
cat plugins/agent42-paperclip/package.json  # check current versions
node --version  # v22.14.0 confirmed
npm --version   # 10.9.2 confirmed
```

## Architecture Patterns

### Recommended Project Structure

```
plugins/agent42-paperclip/
├── src/
│   ├── manifest.ts          # Add new slots: page(terminal), page(apps), settingsPage, sidebar
│   ├── worker.ts            # Add ctx.streams, ctx.actions handlers for terminal/apps
│   ├── tools.ts             # Existing tools — no changes needed
│   ├── client.ts            # Add getTools(), getSkills(), listApps(), startApp(), stopApp(), getSettings(), updateSettings()
│   ├── types.ts             # Add new request/response types
│   └── ui/
│       ├── index.tsx        # Add exports for new components
│       ├── AgentEffectivenessTab.tsx   # existing
│       ├── ProviderHealthWidget.tsx    # existing
│       ├── MemoryBrowserTab.tsx        # existing
│       ├── RoutingDecisionsWidget.tsx  # existing
│       ├── WorkspacePage.tsx           # NEW: coding terminal (PAPERCLIP-01)
│       ├── AppsPage.tsx               # NEW: sandboxed apps launcher (PAPERCLIP-02)
│       ├── ToolsSkillsTab.tsx          # NEW: tools and skills panel (PAPERCLIP-03)
│       └── SettingsPage.tsx           # NEW: Agent42 settings override (PAPERCLIP-04)

dashboard/
├── sidecar.py               # Add GET /workspace/terminal-token, GET /apps, GET /tools, GET /skills, GET /settings, POST /settings
└── server.py                # Add PAPERCLIP_MODE flag: disable redundant dashboard components (PAPERCLIP-05)

core/
└── config.py                # Add paperclip_mode field
```

### Pattern 1: page Slot for Full-Screen Features (Terminal + Apps)

**What:** Declare a `page` slot in the manifest. The host mounts it at `/plugins/:pluginId` or `/:company/plugins/:pluginId`. Add a `sidebar` or `sidebarPanel` entry pointing users to it.
**When to use:** Features requiring full-screen real estate — coding terminal, apps launcher.
**Example:**
```typescript
// Source: @paperclipai/plugin-sdk README.md §UI slots
// In manifest.ts:
{
  type: "page",
  id: "workspace-terminal",
  displayName: "Terminal",
  exportName: "WorkspacePage",
},
{
  type: "sidebar",
  id: "workspace-nav",
  displayName: "Agent42 Workspace",
  exportName: "WorkspaceNavEntry",
}
// capability: "ui.page.register", "ui.sidebar.register"
```

### Pattern 2: Terminal I/O via Plugin Streams (PAPERCLIP-01)

**What:** The coding terminal cannot directly open a WebSocket to Agent42 sidecar from browser context. Instead: worker registers a stream channel for terminal output; UI uses `usePluginStream` to receive characters; UI uses `usePluginAction` to send terminal input; worker proxies both directions through a WebSocket to Agent42's `/ws/terminal` endpoint.

**When to use:** Any real-time bidirectional I/O between plugin UI and Agent42 backend.
**Example:**
```typescript
// Worker side — in worker.ts setup():
ctx.streams.register("terminal-output", async (params, push) => {
  const ws = new WebSocket(`${baseUrl}/ws/terminal?token=${params.token}`);
  ws.onmessage = (e) => push({ text: e.data });
  // Keep alive until stream closed
});

ctx.actions.register("terminal-input", async (params) => {
  // Forward keystroke to active WebSocket session
  await sendToTerminalSession(params.sessionId as string, params.data as string);
  return { ok: true };
});

// UI side — in WorkspacePage.tsx:
const { events } = usePluginStream<{text: string}>("terminal-output", { token, companyId });
const sendInput = usePluginAction("terminal-input");
```

### Pattern 3: settingsPage Slot for Agent42 Settings (PAPERCLIP-04)

**What:** Declare `settingsPage` slot. This replaces Paperclip's auto-generated JSON Schema form for plugin config. The custom React component reads/writes Agent42-specific settings (API keys, etc.) through `usePluginData` and `usePluginAction`, backed by new sidecar endpoints that bridge to `KeyStore`.

**When to use:** When the default Paperclip settings form is insufficient — Agent42 settings involve grouped sections (provider keys, memory config, tool toggles).
**Example:**
```typescript
// Source: @paperclipai/plugin-sdk README.md §settingsPage
// Manifest:
{ type: "settingsPage", id: "agent42-settings", displayName: "Agent42 Settings", exportName: "SettingsPage" }

// UI:
export function SettingsPage({ context }: PluginSettingsPageProps) {
  const { data: settings } = usePluginData<AgentSettings>("agent42-settings");
  const updateSettings = usePluginAction("update-agent42-settings");
  // render grouped settings form
}
```

### Pattern 4: Conditional Dashboard Disable (PAPERCLIP-05)

**What:** When Agent42 is running in sidecar mode (`SIDECAR_ENABLED=true` or `--sidecar`), the standalone dashboard at `http://localhost:8000` is redundant. Redirect or gate the dashboard root to avoid confusion.

**When to use:** When `settings.sidecar_enabled` is true.
**Example:**
```python
# In agent42.py or dashboard/server.py:
if settings.sidecar_enabled:
    # Option A: serve a minimal status page instead of full dashboard
    # Option B: redirect to Paperclip URL
    # Option C: return 503 with message "Dashboard disabled in Paperclip mode"
```

### Anti-Patterns to Avoid

- **Calling Agent42 REST APIs directly from plugin UI components:** Plugin UI cannot make cross-origin HTTP calls to `localhost:8001` from the browser. All calls must go through the bridge (worker `ctx.data.register` / `ctx.actions.register`).
- **Opening WebSocket directly from browser to Agent42:** Same restriction applies. Use `usePluginStream` + worker proxying.
- **Using the deleted manifest.json:** The `manifest.json` file was deleted (per git status: `D plugins/agent42-paperclip/manifest.json`). The manifest is now `src/manifest.ts` compiled to `dist/manifest.js`. Do not recreate `manifest.json`.
- **Adding new top-level FastAPI apps:** All new sidecar endpoints go into `dashboard/sidecar.py:create_sidecar_app()`, not a new app factory.
- **Blocking I/O in sidecar handlers:** All endpoint handlers must be async. Use `httpx.AsyncClient`, never `requests`.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Terminal rendering | Custom terminal renderer | xterm.js (already likely in frontend) or raw pre element for Phase 1 | Complex ANSI handling, cursor management, scroll buffer |
| Real-time terminal bridging | Custom WebSocket relay server | `ctx.streams.register` + `ctx.actions.register` SDK bridge | SDK provides the relay infrastructure for free |
| Plugin config UI | Custom config form framework | SDK `settingsPage` slot + `usePluginData` / `usePluginAction` | SDK provides the settings form contract and host integration |
| App status polling | Manual setInterval in component | `usePluginData` with refresh + `ctx.data.register` handler | SDK caches, refreshes, and handles loading/error states |
| Auth token passing | Custom auth middleware | Paperclip passes companyId/agentId through context; Agent42 trusts sidecar token set at plugin `initialize` time | Token forwarding already designed in Phase 28 pattern |
| Tool registry UI | Custom tool listing page | `/api/tools` and `/api/skills` endpoints already exist; just expose through sidecar | Avoids duplicate REST infrastructure |

**Key insight:** The SDK bridge pattern (worker as relay, UI as thin view) handles all cross-origin and auth complexity. Plugin UI components need only call bridge hooks.

## Common Pitfalls

### Pitfall 1: Terminal Input/Output Serialization Over SSE

**What goes wrong:** SSE is text-based and one-directional (server → client). Terminal sessions need both input (keystrokes, resize events) and output (ANSI sequences). Teams often try to use a single SSE stream for both.

**Why it happens:** `usePluginStream` looks like a WebSocket but is SSE only.

**How to avoid:** Use `usePluginStream` for output (worker → UI) and `usePluginAction` for input (UI → worker). The worker manages the actual bidirectional WebSocket to the sidecar terminal endpoint.

**Warning signs:** `usePluginStream` events going silent after first keypress; resize events not working.

---

### Pitfall 2: Plugin UI Cannot Reach localhost:8001 Directly

**What goes wrong:** A plugin React component tries to `fetch("http://localhost:8001/api/apps")` directly. This will fail with CORS errors because the plugin UI runs same-origin with Paperclip, not with Agent42 sidecar.

**Why it happens:** Developers assume browser-side code can reach any local service.

**How to avoid:** All Agent42 data access from plugin UI must be routed through `usePluginData(key)` → worker handler → `client.getSomething()` → sidecar REST.

**Warning signs:** CORS errors in browser console; 404s on localhost:8001 from plugin UI.

---

### Pitfall 3: Manifest Capability Omission

**What goes wrong:** Adding a new slot type (`page`, `sidebar`, `settingsPage`) without adding the corresponding capability to `manifest.capabilities` causes silent slot registration failure.

**Why it happens:** Capabilities and slots are separate declaration concerns.

**How to avoid:** For every new slot type added, check the SDK README capabilities table:
- `page` → `ui.page.register`
- `sidebar` / `sidebarPanel` / `projectSidebarItem` → `ui.sidebar.register`
- `settingsPage` → no extra capability (uses `ui.detailTab.register` per README) — verify before final implementation
- `globalToolbarButton` → `ui.action.register`

**Warning signs:** Slot renders nothing in Paperclip; no error thrown.

---

### Pitfall 4: Terminal Session Leaking on Tab Close

**What goes wrong:** When the user navigates away from the terminal page, the worker-side WebSocket to the sidecar remains open and the terminal session lives indefinitely, consuming PTY resources.

**Why it happens:** `usePluginStream` close() is called but the worker has no cleanup hook for stream channels.

**How to avoid:** Use `ctx.actions.register("terminal-close", ...)` to explicitly close the server-side session when the UI component unmounts. Call this action in the React `useEffect` cleanup.

**Warning signs:** Server-side PTY processes accumulating; memory growth in sidecar process.

---

### Pitfall 5: Deleted manifest.json

**What goes wrong:** A new developer sees `D plugins/agent42-paperclip/manifest.json` in git status and recreates it as a static JSON file. The build system generates `dist/manifest.js` from `src/manifest.ts` — a static `manifest.json` at root level will confuse the Paperclip loader.

**Why it happens:** Old plugin pattern used static JSON manifests.

**How to avoid:** The manifest lives exclusively in `src/manifest.ts`. It is compiled to `dist/manifest.js`. Never recreate `manifest.json` at the package root.

**Warning signs:** Paperclip loading stale/conflicting manifest; slot declarations not matching worker behavior.

---

### Pitfall 6: Dashboard Disable Logic Breaks Standalone Mode

**What goes wrong:** Aggressively disabling the Agent42 dashboard when `sidecar_enabled=true` breaks the standalone Claude Code workflow (users who only use Agent42 without Paperclip).

**Why it happens:** PAPERCLIP-05 says remove redundant components, but it's easy to over-remove.

**How to avoid:** PAPERCLIP-05 scope is components that are redundant WHEN Paperclip is active. Gate removal on `settings.sidecar_enabled`. The full standalone dashboard (`headless=false`) must continue to work normally when `sidecar_enabled=false`.

**Warning signs:** Standalone mode returns 503 or blank page.

## Code Examples

Verified patterns from official sources:

### Declaring a page Slot in manifest.ts
```typescript
// Source: @paperclipai/plugin-sdk README.md §UI slots
// In src/manifest.ts:
ui: {
  slots: [
    // ... existing slots ...
    {
      type: "page",
      id: "workspace-terminal",
      displayName: "Terminal",
      exportName: "WorkspacePage",
    },
    {
      type: "page",
      id: "sandboxed-apps",
      displayName: "Apps",
      exportName: "AppsPage",
    },
    {
      type: "settingsPage",
      id: "agent42-settings",
      displayName: "Agent42 Settings",
      exportName: "SettingsPage",
    },
    {
      type: "sidebar",
      id: "workspace-nav",
      displayName: "Workspace",
      exportName: "WorkspaceNavEntry",
    },
  ]
},
capabilities: [
  // existing capabilities...
  "ui.page.register",
  "ui.sidebar.register",
]
```

### Registering a Stream Channel for Terminal Output
```typescript
// Source: @paperclipai/plugin-sdk README.md §usePluginStream
// In worker.ts setup():
ctx.streams.register("terminal-output", async (params, push) => {
  const sessionId = params?.sessionId as string;
  // ... attach to active terminal session, push output events
});

ctx.actions.register("terminal-input", async (params) => {
  const { sessionId, data } = params as { sessionId: string; data: string };
  // forward to terminal session WebSocket
  return { ok: true };
});
```

### usePluginStream in React Component
```tsx
// Source: @paperclipai/plugin-sdk README.md §usePluginStream
import { usePluginStream, usePluginAction } from "@paperclipai/plugin-sdk/ui";

export function WorkspacePage({ context }: PluginPageProps) {
  const { events, connected } = usePluginStream<{ text: string }>("terminal-output", {
    companyId: context.companyId ?? undefined,
    sessionId: activeSessionId,
  });
  const sendInput = usePluginAction("terminal-input");
  // render terminal output from events array
}
```

### settingsPage Component Pattern
```tsx
// Source: @paperclipai/plugin-sdk README.md §settingsPage
import { usePluginData, usePluginAction } from "@paperclipai/plugin-sdk/ui";
import type { PluginSettingsPageProps } from "@paperclipai/plugin-sdk/ui";

export function SettingsPage({ context }: PluginSettingsPageProps) {
  const { data, loading, error } = usePluginData<Record<string, unknown>>("agent42-settings");
  const update = usePluginAction("update-agent42-settings");
  if (loading) return <div>Loading settings...</div>;
  // render grouped settings form
}
```

### Adding Sidecar Endpoint for Settings Bridge
```python
# Source: dashboard/sidecar.py existing pattern
@app.get("/settings")
async def get_settings(_user: str = Depends(get_current_user)) -> dict:
    """Return Agent42 settings visible to Paperclip plugin."""
    from core.key_store import KeyStore
    store = KeyStore()
    return {"keys": store.get_masked_keys()}

@app.post("/settings")
async def update_settings(req: SettingsUpdateRequest, _user: str = Depends(get_current_user)):
    """Update Agent42 settings from Paperclip plugin."""
    # validate keys against ADMIN_CONFIGURABLE_KEYS, call store.set_key()
    ...
```

### Conditional Dashboard Gate (PAPERCLIP-05)
```python
# Source: dashboard/server.py existing pattern
# In create_app() or agent42.py:
if settings.sidecar_enabled:
    @app.get("/")
    async def dashboard_disabled():
        return JSONResponse(
            {"status": "paperclip_mode", "message": "Dashboard UI disabled in Paperclip mode"},
            status_code=503
        )
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| Static `manifest.json` | `src/manifest.ts` compiled to `dist/manifest.js` | Phase 31 | Do not recreate manifest.json |
| Separate adapter package `adapters/agent42-paperclip/` | Plugin package `plugins/agent42-paperclip/` | Phase 28 | All plugin work is in plugins/, not adapters/ |
| `health()` lifecycle hook | `onHealth()` lifecycle hook | Phase 29 (Pitfall 2) | Use `onHealth()` not `health()` |
| `initialize(config)` lifecycle | `ctx.config.get()` inside `setup()` | Phase 29 (Pitfall 1) | Config read inside setup, no separate initialize export |

**Deprecated/outdated:**
- `manifest.json` at package root: deleted in current codebase, must not be recreated
- `initialize(config)` export: Paperclip SDK no longer calls a separate `initialize`; config is via `ctx.config.get()` in `setup()`

## Open Questions

1. **Does Paperclip runtime support `ctx.streams.register` for bidirectional terminal proxying?**
   - What we know: SDK types declare `ctx.streams` and `ctx.streams.emit()`. The README shows `usePluginStream` consuming SSE push events from the worker side.
   - What's unclear: Whether `ctx.streams.register` (blocking/generator pattern) vs `ctx.streams.emit` (imperative push) is the correct API for managing a long-lived terminal session. The README shows `emit` usage only.
   - Recommendation: Use `ctx.streams.emit` + a module-level session map. Worker calls `ctx.streams.emit(channel, event)` whenever terminal output arrives. This is verified from the README.

2. **How does the terminal page component unmount clean up the worker-side WebSocket?**
   - What we know: `usePluginStream` returns a `close()` function. React `useEffect` cleanup can call it.
   - What's unclear: Whether calling `close()` from the UI side triggers any worker-side cleanup callback.
   - Recommendation: Register a separate `ctx.actions.register("terminal-close")` handler explicitly called from component unmount. This is the safe pattern regardless of SDK behaviour.

3. **Does `settingsPage` slot require an additional capability beyond those already declared?**
   - What we know: README capability table shows `settingsPage` under the `UI` group but the table lists `ui.detailTab.register` and `ui.dashboardWidget.register` separately. The `settingsPage` capability entry is not explicitly listed.
   - What's unclear: Whether a specific `ui.settingsPage.register` capability is required or whether it is covered by an existing capability.
   - Recommendation: During implementation, verify by attempting to register the slot and checking Paperclip's plugin validation output. The `onValidateConfig` hook may also surface this.

4. **What is the exact shape of the `ctx.streams.register` API?**
   - What we know: README shows `usePluginStream` consuming `ctx.streams.emit(channel, event)` on the worker side.
   - What's unclear: Whether `ctx.streams.register` (registration + push callback pattern) is the worker-side API, or whether it is purely imperative `ctx.streams.emit`.
   - Recommendation: Check the `@paperclipai/plugin-sdk` TypeScript types at `dist/types.d.ts` at implementation time for the exact API surface.

## Environment Availability

| Dependency | Required By | Available | Version | Fallback |
|------------|------------|-----------|---------|----------|
| Node.js | Plugin build, tests | YES | v22.14.0 | — |
| npm | Plugin install/build | YES | 10.9.2 | — |
| Python 3.11+ | Sidecar backend | YES | 3.14.3 | — |
| pytest | Backend tests | YES | 9.0.2 | — |
| @paperclipai/plugin-sdk | Plugin UI/worker | YES | installed | — |
| TypeScript 6 | Plugin compile | YES | ^6.0.2 (package.json) | — |
| Vitest | Plugin tests | YES | ^4.1.2 (package.json) | — |
| esbuild | UI bundle | YES | ^0.25.0 (package.json) | — |

**Missing dependencies with no fallback:** None.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Python framework | pytest 9.0.2 |
| Python config | `pytest.ini` or default discovery |
| Python quick run | `python -m pytest tests/test_sidecar.py -x -q` |
| Python full suite | `python -m pytest tests/ -x -q` |
| TypeScript framework | Vitest ^4.1.2 |
| TypeScript config | `vitest.config.*` (not yet verified) |
| TypeScript run | `cd plugins/agent42-paperclip && npm test` |

### Phase Requirements to Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| PAPERCLIP-01 | Terminal page slot declared in manifest | unit | `cd plugins/agent42-paperclip && npm test` | ❌ Wave 0 |
| PAPERCLIP-01 | Terminal stream handler registered in worker | unit | `cd plugins/agent42-paperclip && npm test` | ❌ Wave 0 |
| PAPERCLIP-02 | Apps page slot declared in manifest | unit | `cd plugins/agent42-paperclip && npm test` | ❌ Wave 0 |
| PAPERCLIP-02 | App list endpoint in sidecar returns correct data | unit | `python -m pytest tests/test_sidecar.py -x -q -k apps` | ❌ Wave 0 |
| PAPERCLIP-03 | Tools/skills tab slot declared in manifest | unit | `cd plugins/agent42-paperclip && npm test` | ❌ Wave 0 |
| PAPERCLIP-03 | Sidecar `/tools` and `/skills` endpoints return data | unit | `python -m pytest tests/test_sidecar.py -x -q -k tools` | ❌ Wave 0 |
| PAPERCLIP-04 | Settings page slot declared in manifest | unit | `cd plugins/agent42-paperclip && npm test` | ❌ Wave 0 |
| PAPERCLIP-04 | Sidecar `GET /settings` returns masked key structure | unit | `python -m pytest tests/test_sidecar.py -x -q -k settings` | ❌ Wave 0 |
| PAPERCLIP-05 | Dashboard returns 503 when sidecar_enabled=true | unit | `python -m pytest tests/test_sidecar.py -x -q -k dashboard_disabled` | ❌ Wave 0 |
| PAPERCLIP-05 | Standalone dashboard unaffected when sidecar_enabled=false | regression | `python -m pytest tests/ -x -q -k dashboard` | ✅ (partial) |

### Sampling Rate
- **Per task commit:** `python -m pytest tests/test_sidecar.py -x -q` + `cd plugins/agent42-paperclip && npm test`
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Full suite green before `/gsd:verify-work`

### Wave 0 Gaps
- [ ] `tests/test_sidecar_phase36.py` — covers PAPERCLIP-02 (apps endpoint), PAPERCLIP-03 (tools/skills), PAPERCLIP-04 (settings GET/POST), PAPERCLIP-05 (dashboard gate)
- [ ] `plugins/agent42-paperclip/src/__tests__/manifest.test.ts` — covers PAPERCLIP-01, -02, -03, -04 slot declarations in manifest
- [ ] `plugins/agent42-paperclip/src/__tests__/worker-streams.test.ts` — covers terminal stream handler registration

## Sources

### Primary (HIGH confidence)
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/README.md` — Slot types, capabilities, `usePluginStream`, `usePluginAction`, `usePluginData`, lifecycle hooks, manifest format
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/ui/types.d.ts` — All UI slot prop interfaces, hook return types
- `plugins/agent42-paperclip/node_modules/@paperclipai/plugin-sdk/dist/ui/components.d.ts` — Shared component declarations
- `dashboard/sidecar.py` — All existing sidecar endpoints (confirmed by reading source)
- `dashboard/server.py` — Existing terminal WebSocket endpoint (`/ws/terminal`), apps REST endpoints (`/api/apps/*`)
- `plugins/agent42-paperclip/src/manifest.ts` — Current manifest structure (confirmed)
- `plugins/agent42-paperclip/src/worker.ts` — Existing `ctx.data.register`, `ctx.jobs.register` patterns
- `.planning/phases/24-28-29-CONTEXT.md` files — Prior architecture decisions (confirmed canonical)
- `core/key_store.py` — `ADMIN_CONFIGURABLE_KEYS`, `KeyStore` API (confirmed by reading source)

### Secondary (MEDIUM confidence)
- Git status `D plugins/agent42-paperclip/manifest.json` — Confirmed manifest.json was deleted; manifest now lives in src/manifest.ts

### Tertiary (LOW confidence)
- `ctx.streams.register` API shape — SDK README shows `ctx.streams.emit` usage but stream registration API shape (generator vs imperative push) needs runtime verification

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH — all dependencies are installed and verified in the repo
- Architecture: HIGH — SDK slot types confirmed from installed SDK types; existing patterns confirmed from source files
- Pitfalls: HIGH for items 2, 3, 5, 6 (confirmed from codebase); MEDIUM for item 1 (confirmed from SDK README but stream worker API needs runtime verification)

**Research date:** 2026-04-03
**Valid until:** 2026-05-03 (SDK is pinned to `*` in package.json — changes on Paperclip upgrades)

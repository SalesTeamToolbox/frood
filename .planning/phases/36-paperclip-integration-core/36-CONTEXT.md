# Phase 36: Paperclip Integration Core - Context

**Gathered:** 2026-04-02
**Status:** Ready for planning

<domain>
## Phase Boundary

Integrate workspace coding terminal, sandboxed apps, tools and skills into Paperclip dashboard. When Paperclip is active, users should be able to access Agent42 workspace features directly within the Paperclip interface, while maintaining seamless integration with Paperclip's existing functionality.

Requirements: PAPERCLIP-01, PAPERCLIP-02, PAPERCLIP-03, PAPERCLIP-04, PAPERCLIP-05.

</domain>

<decisions>
## Implementation Decisions

### Integration Approach
- **D-01:** Workspace coding terminal integrated as native Paperclip UI component that communicates with Agent42 sidecar via WebSocket for real-time interaction
- **D-02:** Sandboxed apps integrated through contextual panels that appear based on user workflow and task context
- **D-03:** Tools and skills exposed through Paperclip's existing tool registry system, leveraging the MCP tool proxy pattern established in Phase 28
- **D-04:** Settings management integrated into Paperclip's admin interface with clear separation between Paperclip-native and Agent42-specific settings

### UI/UX Design
- **D-05:** Unified sidebar approach - Agent42 features added to existing Paperclip sidebar navigation with clear visual distinction
- **D-06:** Seamless integration where Agent42 features feel like native part of Paperclip while maintaining clear identity
- **D-07:** Consistent design language following Paperclip's existing UI patterns and component library
- **D-08:** Responsive design that works across different screen sizes and device types

### Technical Implementation
- **D-09:** HTTP REST API communication between Paperclip frontend and Agent42 sidecar - leveraging existing patterns from Paperclip plugin (Phase 28)
- **D-10:** Paperclip handles authentication, Agent42 trusts Paperclip context with token forwarding for API calls
- **D-11:** Shared state management through Paperclip's existing context system, with Agent42 state scoped appropriately
- **D-12:** Real-time updates via WebSocket connections where needed (terminal, app status, etc.)

### Feature Scope
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

</decisions>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Phase requirements
- `.planning/REQUIREMENTS.md` — PAPERCLIP-01 through PAPERCLIP-05 define all Phase 36 requirements
- `.planning/workstreams/dashboard-unification/ROADMAP.md` — Phase 36 success criteria (5 acceptance tests)

### Prior phase context (dependencies)
- `.planning/phases/24-sidecar-mode/24-CONTEXT.md` — Sidecar architecture, CLI flags, FastAPI app structure
- `.planning/phases/27-paperclip-adapter/27-CONTEXT.md` — Adapter package structure, Agent42Client design, session codec
- `.planning/phases/28-paperclip-plugin/28-CONTEXT.md` — Plugin package structure, MCP tool proxy, tool registrations
- `.planning/phases/29-plugin-ui-learning-extraction/29-CONTEXT.md` — UI component patterns, React integration, data flow

### Existing codebase (key files to read)
- `dashboard/server.py` — Existing dashboard REST API, authentication, WebSocket manager
- `core/agent_manager.py` — PROVIDER_MODELS mapping, agent configuration patterns
- `core/key_store.py` — ADMIN_CONFIGURABLE_KEYS, key management patterns
- `plugins/agent42-paperclip/src/` — Existing plugin TypeScript code, tool registrations, client
- `dashboard/frontend/dist/app.js` — Existing dashboard frontend (compiled)
- `.env.example` — Environment variables and configuration patterns

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `plugins/agent42-paperclip/` — Existing plugin package with tool registration patterns, Agent42Client HTTP client
- `dashboard/server.py` — FastAPI app with REST endpoints, authentication middleware, WebSocket support
- `core/agent_manager.py` — PROVIDER_MODELS constant, resolve_model function for provider/model mapping
- `dashboard/auth.py` — Authentication utilities, rate limiting, token management
- `dashboard/websocket_manager.py` — WebSocket connection management, message broadcasting

### Established Patterns
- **Tool registration:** Paperclip plugin pattern with camelCase field names, automatic agentId/companyId injection
- **HTTP communication:** Agent42Client with baseUrl + apiKey + timeout configuration, Bearer auth
- **State management:** Settings dataclass with frozen config, environment variable mapping
- **Error handling:** Structured {error, message, action} API responses (from v1.1)
- **Security:** PreToolUse security gate, CommandFilter enforcement, sandboxed file operations

### Integration Points
- Paperclip frontend ↔ Agent42 sidecar REST API communication
- Paperclip plugin ↔ Agent42 sidecar tool proxy endpoints
- Shared authentication context between Paperclip and Agent42
- WebSocket connections for real-time terminal and app status updates
- Environment variable configuration shared between systems

</code_context>

<specifics>
## Specific Ideas

No specific requirements — open to standard approaches

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---
*Phase: 36-paperclip-integration-core*
*Context gathered: 2026-04-02*
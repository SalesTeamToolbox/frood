# Stack Research: Paperclip Integration (v4.0)

**Domain:** Agent42 as Paperclip plugin+adapter — cross-language integration
**Researched:** 2026-03-28
**Confidence:** HIGH — based on Paperclip official docs, plugin SDK spec, and existing Agent42 codebase

---

## Context: Existing Stack (DO NOT re-add)

- Python 3.11+, FastAPI, AsyncOpenAI, aiofiles, pytest
- ONNX Runtime (~25MB) for embeddings
- Qdrant (server or embedded), Redis, aiosqlite
- MCP server (stdio/SSE), 41+ tools
- Dashboard: FastAPI serving HTML/JS, WebSocket

## New Stack Additions

### TypeScript / Node.js (for Paperclip adapter + plugin packages)

| Package | Version | Why |
|---------|---------|-----|
| `typescript` | 5.7+ | Required for Paperclip plugin/adapter development |
| `@paperclipai/plugin-sdk` | 2026.318.0+ | Official plugin SDK — provides `setup(ctx)`, tool registration, event subscriptions |
| `node` | 20+ | Paperclip runtime requirement |
| `pnpm` | 9.15+ | Paperclip's package manager |

**Rationale:** Paperclip's plugin system runs as Node.js child processes using JSON-RPC 2.0 over stdin/stdout. The adapter is also TypeScript. There is no Python plugin interface — we must write thin TypeScript wrappers that call Agent42's sidecar HTTP API.

### Docker / Compose (for multi-service deployment)

| Package | Version | Why |
|---------|---------|-----|
| `docker` | 24+ | Container runtime |
| `docker-compose` / `docker compose` | 2.x | Multi-service orchestration: Paperclip + Agent42 + Qdrant + PostgreSQL |
| `postgresql` | 16+ | Paperclip's database (embedded for dev, external for prod) |

**Rationale:** Docker Compose is the standard way to run Paperclip + dependencies. Agent42 adds as a sidecar service.

### Python Additions (minimal)

| Package | Version | Why |
|---------|---------|-----|
| None new | — | Sidecar mode reuses existing FastAPI + uvicorn. No new Python deps needed. |

**Rationale:** The sidecar is a stripped-down FastAPI app using existing imports. Memory bridge, routing bridge, and MCP proxy all use existing Agent42 modules.

## What NOT to Add

| Temptation | Why Not |
|------------|---------|
| Python JSON-RPC library | Plugin communicates via HTTP to sidecar, not direct JSON-RPC from Python |
| gRPC between services | HTTP REST is simpler, Paperclip's HTTP adapter spec already defines the protocol |
| Shared PostgreSQL from Agent42 | Agent42 keeps Qdrant+SQLite; Paperclip owns PostgreSQL. Don't mix databases. |
| React for Agent42 plugin UI | Paperclip plugin UI uses React hooks from SDK — minimal, no separate React build |
| Electron / Tauri wrapper | Docker Compose handles deployment; no desktop packaging needed for the integration |

## Integration Points

1. **Sidecar HTTP API** — Agent42 exposes `/execute`, `/status`, `/memory/recall`, `/memory/store`, `/mcp/invoke` on port 8001
2. **Paperclip adapter** — TypeScript package calls sidecar endpoints, implements Paperclip's `ServerAdapterModule` interface
3. **Paperclip plugin** — TypeScript package registers agent tools via `ctx.tools`, calls sidecar for memory/routing
4. **Docker network** — All services on same Docker network, communicate via service names

## Build Tooling

The TypeScript packages need their own build setup:

```
adapters/paperclip/        # Paperclip adapter package
  package.json
  tsconfig.json
  src/index.ts

plugins/paperclip/         # Paperclip plugin package
  package.json
  tsconfig.json
  src/index.ts
```

Both are independent npm packages, not part of Agent42's Python build.

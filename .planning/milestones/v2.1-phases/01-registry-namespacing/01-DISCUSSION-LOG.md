# Phase 1: Registry & Namespacing - Discussion Log

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions are captured in CONTEXT.md — this log preserves the alternatives considered.

**Date:** 2026-03-23
**Phase:** 01-registry-namespacing
**Mode:** discuss (advisor)
**Areas discussed:** Workspace identity scheme, Persistence backend, API migration path, Default workspace seeding

---

## Workspace Identity Scheme

| Option | Description | Selected |
|--------|-------------|----------|
| uuid4().hex[:12] | Matches all existing entity IDs. Stable across renames, collision-free, safe in URLs/localStorage/Monaco URIs. | ✓ |
| Human-readable slug | Readable but breaks on rename — needs slug collision handling and propagation logic. | |
| Auto-increment integer | Short but requires persistent counter, fragile on import/export. | |

**User's choice:** uuid4().hex[:12]
**Notes:** Consistency with existing codebase entity ID pattern was the deciding factor. Monaco caches models by URI — slug renames would orphan cached models.

---

## Persistence Backend

| Option | Description | Selected |
|--------|-------------|----------|
| JSON file via aiofiles | Matches ProjectManager/AppManager pattern. In-memory + write-on-mutate with atomic os.replace(). | ✓ |
| aiosqlite | Crash-safe WAL mode but overkill for 1-20 records, diverges from JSON config pattern. | |
| In-memory only | Data lost on restart — dev stub only. | |

**User's choice:** JSON file via aiofiles
**Notes:** Structurally identical to ProjectManager. Atomic write via temp file + os.replace() mitigates torn-write risk.

---

## API Migration Path

| Option | Description | Selected |
|--------|-------------|----------|
| Add workspace_id query param | Backward-compatible, one-line change per handler, matches existing WS query param pattern. | ✓ |
| New nested routes | Clean REST hierarchy but breaking change — all frontend calls must migrate atomically. WS still needs query params. | |
| Header/session context | Zero URL changes but WS doesn't support headers in browser. Implicit state conflicts with multi-workspace goal. | |

**User's choice:** Add workspace_id query param
**Notes:** Existing WebSocket endpoints already use query params for auth tokens. Phase 2 threads workspace_id through mechanically.

---

## Default Workspace Seeding

| Option | Description | Selected |
|--------|-------------|----------|
| Startup seed if absent | Seed on server start if registry file missing. Display name = folder name. Zero behavior change for existing users. | ✓ |
| Lazy seed on first API call | Defers I/O but frontend must handle empty-registry state with null guards. | |
| Re-seed every startup | Stays in sync if env var changes but destroys user renames. | |

**User's choice:** Startup seed if absent
**Notes:** Uses Path(AGENT42_WORKSPACE).name as display name. Falls back to "Default" if uninformative. One-time write, idempotent on subsequent starts.

---

## Claude's Discretion

- WorkspaceRegistry internal structure and method signatures
- Exact JSON schema fields beyond core (id, name, path, created_at, ordering)
- Path validation implementation details
- Error response format for invalid workspace IDs

## Deferred Ideas

- Auto-seeding apps/ as workspaces — Phase 3 (MGMT-01)
- Nested route API design — revisit if API versioning added later

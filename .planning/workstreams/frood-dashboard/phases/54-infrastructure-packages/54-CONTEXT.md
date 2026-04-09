# Phase 54: Infrastructure + Packages - Context

**Gathered:** 2026-04-08
**Status:** Ready for planning

<domain>
## Phase Boundary

Docker compose and NPM packages carry the Frood name — services, volumes, env vars, and package scopes all updated. No features - straightforward renames.

</domain>

<decisions>
## Implementation Decisions

### Docker Service Names
- **INFRA-01:** Rename `agent42-sidecar` service to `frood-sidecar` in docker-compose.paperclip.yml

### Docker Volume Names
- **INFRA-02:** Rename `agent42-data` volume to `frood-data` in docker-compose.paperclip.yml

### Environment Variables
- **INFRA-04:** Replace all `AGENT42_*` env vars with `FROOD_*` in docker-compose.paperclip.yml
- Update `AGENT42_SIDECAR_URL` reference on line 89 to `FROOD_SIDECAR_URL`

### Dockerfile
- **INFRA-03:** Rename user from `agent42` to `frood` in Dockerfile
- Update CMD reference from `agent42.py` to `frood.py`

### NPM Package Names
- **NPM-01:** Rename package from `@agent42/paperclip-adapter` to `@frood/paperclip-adapter`
- Update adapters/agent42-paperclip/package.json

### NPM Directory Names
- **NPM-03:** Rename directory from `agent42-paperclip` to `frood-paperclip`
- Must also update imports in package.json after rename

### User's Discretion
- Order of operations (Dockerfile before compose, or vice versa)
- Whether to keep old volume and create new, or rename in place

</decisions>

<canonical_refs>
## Canonical References

### Docker Compose
- `docker-compose.paperclip.yml` — service name, volume names, env var references
- `.env.paperclip` — env var names if referenced

### Dockerfile
- `Dockerfile` — user creation, CMD

### NPM Packages
- `adapters/agent42-paperclip/package.json` — name, imports
- `plugins/agent42-paperclip/package.json` — name (if it exists)

### Prior Phase Context
- `.planning/workstreams/frood-dashboard/phases/52-CONTEXT.md` — Phase 52 decisions for reference pattern
- `.planning/workstreams/frood-dashboard/phases/53-CONTEXT.md` — Phase 53 decisions

### Requirements
- `.planning/workstreams/frood-dashboard/REQUIREMENTS.md` — INFRA-01, INFRA-02, INFRA-03, INFRA-04, NPM-01, NPM-02, NPM-03

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Patterns
- Phase 52 used clean break pattern: rename and move on, no fallbacks
- Phase 53 followed same pattern
- Phase 54 should follow same pattern for consistency

### Current State
- `agent42-sidecar` service in compose (line 53)
- `agent42-data` volume in compose (line 106)
- `agent42` user in Dockerfile (lines 19-22)
- `@agent42/paperclip-adapter` package name

### Integration Points
- Docker service name affects container networking (Paperclip references agent42-sidecar)
- Volume name affects mount path in container
- NPM package name affects user's `npm install @frood/paperclip-adapter`

</code_context>

<specifics>
## Specific Ideas

- The rename is straightforward - follow Phase 52/53 pattern
- Check Paperclip service in compose also references `AGENT42_SIDECAR_URL` (line 89)
- Both adapters and plugins need renaming (NPM-01, NPM-02)

</specifics>

<deferred>
## Deferred Ideas

- None - all decisions are clear-cut renames

</deferred>

---

*Phase: 54-infrastructure-packages*
*Context gathered: 2026-04-08*
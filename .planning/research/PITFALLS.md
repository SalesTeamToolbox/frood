# Pitfalls Research: Paperclip Integration (v4.0)

**Domain:** Cross-language integration (Python ↔ TypeScript), sidecar architecture, multi-database Docker deployment
**Researched:** 2026-03-28
**Confidence:** HIGH for cross-language bridge risks (well-documented patterns), MEDIUM for Paperclip-specific API stability (new platform, rapid iteration)

---

## Critical Pitfalls

### P1: Agent ID Mismatch Breaks Memory + Effectiveness History

**Risk:** When importing existing agents into Paperclip, if agent IDs are regenerated, all Qdrant memories and SQLite effectiveness data become unreachable.

**Prevention:** Preserve Agent42 agent UUIDs as `adapterConfig.agentId` in Paperclip. The migration script must map `agent_id → Paperclip agent → adapterConfig.agentId` 1:1.

**Phase:** Migration tooling (Phase 3)

### P2: Sidecar Health Check Race on Docker Startup

**Risk:** Paperclip adapter tries to call Agent42 sidecar before it's ready. FastAPI + uvicorn startup takes 2-5 seconds; Qdrant embedded mode takes longer.

**Prevention:** Docker Compose `healthcheck` on Agent42 service (`curl http://localhost:8001/health`). Paperclip adapter must retry with exponential backoff on connection refused.

**Phase:** Sidecar mode (Phase 1) + Docker Compose (Phase 3)

### P3: Duplicate Budget/Cost Tracking

**Risk:** Both Paperclip (budget enforcement) and Agent42 (SpendingTracker) track costs. Double-counting confuses users. Worse: Agent42's tracker runs outside Paperclip's budget enforcement, so an agent could exceed its Paperclip budget via direct Agent42 API calls.

**Prevention:** When running as Paperclip sidecar, Agent42 should report costs TO Paperclip but NOT enforce its own limits. Budget enforcement is Paperclip's job. Agent42's SpendingTracker becomes a data source, not a gate.

**Phase:** Routing bridge (Phase 2)

### P4: Heartbeat Timeout vs Agent42 Memory Injection Latency

**Risk:** Memory injection (Qdrant search + embedding) adds 200-500ms to heartbeat start. If Paperclip has a tight heartbeat timeout, this delays agent execution or causes timeouts.

**Prevention:** Memory injection should be async — start agent execution immediately, inject memory context in parallel. Use Paperclip's async callback pattern (202 Accepted + callback POST).

**Phase:** Memory bridge (Phase 2)

### P5: Windows CRLF in TypeScript Build Artifacts

**Risk:** Git on Windows auto-converts LF to CRLF. TypeScript build outputs may have CRLF which breaks JSON-RPC newline-delimited protocol (expects `\n`, gets `\r\n`).

**Prevention:** Add `.gitattributes` to adapter/plugin packages: `*.ts text eol=lf` and `*.json text eol=lf`. Verify JSON-RPC parser handles both.

**Phase:** Adapter package (Phase 1)

## High Pitfalls

### P6: Standalone Mode Regression

**Risk:** Changes to support sidecar mode break Agent42's standalone operation. Existing users who don't use Paperclip get broken deployments.

**Prevention:** Sidecar mode is a separate entry point (`--sidecar` flag). Core modules (memory, routing, effectiveness) remain unchanged. Test both modes in CI.

**Phase:** Sidecar mode (Phase 1)

### P7: Multi-Tenant Memory Isolation

**Risk:** If one Agent42 sidecar serves multiple Paperclip companies, memories leak across companies. Qdrant collections don't have company-level partitioning.

**Prevention:** Either: (a) one sidecar per company (simplest), or (b) add `company_id` filter to all Qdrant queries. Start with (a); add (b) only if needed.

**Phase:** Memory bridge (Phase 2)

### P8: Plugin SDK Version Drift

**Risk:** Paperclip is rapidly iterating (14.2K stars in first week, multiple releases in March 2026). Plugin SDK API may change between releases.

**Prevention:** Pin to specific `@paperclipai/plugin-sdk` version. Abstract SDK calls behind a thin wrapper so upgrades are localized. Watch Paperclip releases.

**Phase:** Plugin scaffold (Phase 2)

### P9: Duplicate Transcript Storage

**Risk:** Both Paperclip (PostgreSQL) and Agent42 (Qdrant conversations collection) store conversation transcripts. Wastes storage, creates consistency risk.

**Prevention:** When running as sidecar, Agent42 should NOT duplicate full transcripts. Only store embeddings of key decisions/learnings in Qdrant. Paperclip owns the canonical transcript.

**Phase:** Memory bridge (Phase 2)

### P10: Docker Compose Port Conflicts

**Risk:** Paperclip (3100), Agent42 dashboard (8000), Agent42 sidecar (8001), Qdrant (6333), PostgreSQL (5432) — five ports. Users with existing services on these ports get bind errors.

**Prevention:** All ports configurable via environment variables in docker-compose.yml. Document defaults and how to change them.

**Phase:** Docker Compose (Phase 3)

## Medium Pitfalls

### P11: Embedding Agent42 Dashboard in Paperclip via iframe

**Risk:** Temptation to embed full Agent42 dashboard as a Paperclip plugin panel. This creates a confusing dual-dashboard UX and breaks Paperclip's design language.

**Prevention:** Do NOT iframe the dashboard. Use Paperclip's native plugin UI slots (detailTab, dashboardWidget) for Agent42-specific views. Keep it native.

**Phase:** Plugin UI (Phase 2)

### P12: TypeScript Monorepo Complexity

**Risk:** Adding TypeScript packages to a Python project creates two build systems, two package managers, two test runners. Complexity creeps.

**Prevention:** Keep TypeScript packages minimal — thin wrappers over HTTP calls. No shared state, no complex builds. `pnpm build` in adapter/ and plugin/ directories, that's it.

**Phase:** All TypeScript phases

# Feature Research

**Domain:** AI agent platform — unified developer tooling (GSD + jcodemunch integration)
**Researched:** 2026-03-17
**Confidence:** HIGH (existing code inspected directly, gaps verified against search)

---

## Context: What Already Exists

Before categorizing features, these are the capabilities already built and working in Agent42.
New features in this milestone must build ON TOP of these, not re-implement them.

| Existing Capability | Module | Status |
|---------------------|--------|--------|
| jcodemunch hooks (context-loader, token-tracker, reindex, drift detection) | `.claude/hooks/` | Working |
| GSD fork (autonomous mode, workstreams, Nyquist, cowork daemon) | `~/.claude/get-shit-done/` | Working |
| Memory system (Qdrant + ONNX + flat files + 7-action MemoryTool) | `memory/`, `tools/memory_tool.py` | Working |
| EffectivenessStore (SQLite async, fire-and-forget) | `memory/effectiveness.py` | Working |
| ProjectMemoryStore (per-project namespace isolation) | `memory/project_memory.py` | Working |
| NodeSyncTool (rsync push/pull/merge for MEMORY.md+HISTORY.md) | `tools/node_sync.py` | Working |
| ContextAssemblerTool (memory + docs + git + skills in one call) | `tools/context_assembler.py` | Working |
| Setup scripts (setup.sh local, install-server.sh VPS) | root, `scripts/` | Partial — no Windows, no Claude Code config |
| MCP server (36+ tools, stdio transport) | `mcp_server.py` | Working |
| Dashboard (FastAPI, single admin, JWT) | `dashboard/` | Working |

---

## Feature Landscape

### Table Stakes (Users Expect These)

Features that the new milestone must deliver or it feels incomplete.

| Feature | Why Expected | Complexity | Notes |
|---------|--------------|------------|-------|
| One-command setup on Linux/VPS | setup.sh exists but doesn't configure Claude Code, .mcp.json, or jcodemunch | MEDIUM | Must create `.mcp.json`, patch `.claude/settings.json`, index repo |
| One-command setup on Windows (Git Bash/WSL) | Developers on Windows today get a broken experience — Claude Code hooks use Python paths that fail natively | MEDIUM | Path normalization already in hooks; need Windows-aware venv activation, CRLF guards |
| Guided first-run CLAUDE.md generation | Claude Code's `/init` command creates a CLAUDE.md stub, but Agent42 conventions (pitfalls, hook protocol, memory system) are not in it | MEDIUM | Template + project-interview-style generation; can reuse `tools/project_interview.py` |
| Bi-directional memory sync that handles conflicts | NodeSyncTool exists but MEMORY.md uses naive "newest-wins" (mtime); simultaneous edits on two nodes lose data | MEDIUM | Need proper 3-way merge or CRDT-style append log; HISTORY.md already does append-merge correctly |
| Qdrant vector re-index after sync | NodeSyncTool already calls `reindex_memory()` post-sync | LOW | Already built — wire correctly in all sync paths (currently missing in some edge cases) |
| Context API that merges jcodemunch + memory in one call | ContextAssemblerTool pulls memory + docs + git + skills but has no jcodemunch path — code symbol search is missing | MEDIUM | Add jcodemunch MCP call path to ContextAssemblerTool |
| Per-project memory namespace | ProjectMemoryStore exists but is not wired into MemoryTool (MemoryTool uses global store only) | LOW | Wire `project` param in MemoryTool.execute() to ProjectMemoryStore lookup |
| Setup idempotence (re-run safe) | setup.sh already checks for .env existence; needs same pattern for .mcp.json and hook configs | LOW | Guard every write with existence checks |
| Setup validation step | After setup completes, verify: Python OK, MCP server responds, Qdrant accessible, hooks fire | MEDIUM | A `health` check command the setup can call at the end |

### Differentiators (Competitive Advantage)

Features unique to Agent42's architecture that competitors lack.

| Feature | Value Proposition | Complexity | Notes |
|---------|-------------------|------------|-------|
| Unified context engine (code intel + GSD state + semantic memory) | Single `context` tool call returns jcodemunch symbol graph, GSD workstream status, and relevant memories — no other agent platform does this | HIGH | Requires jcodemunch MCP async call from ContextAssemblerTool; GSD state reader; all three sources deduped and token-budgeted |
| CLAUDE.md template library with Agent42 conventions baked in | Teams onboard in minutes instead of hours — templates encode 116 pitfalls, hook protocol, memory patterns | MEDIUM | Template generator that interrogates project type (Python/Node/etc.) and fills in domain-specific sections |
| Effectiveness-aware context injection | ContextAssemblerTool reads EffectivenessStore to surface tools/skills that worked best for THIS task type | MEDIUM | Join effectiveness data with context assembly; route high-effectiveness skills to top of output |
| Conflict-free memory sync with CRDT semantics | Flat files (MEMORY.md) get append-log semantics — no silent data loss on concurrent edits across nodes | HIGH | Each memory entry gets a UUID + timestamp; merge is union of entries, not file-level overwrite |
| GSD workstream state surfaced in context | When Claude Code asks for context on "authentication flow", context engine surfaces the GSD plan for that phase, not just memory hits | MEDIUM | Parse `.planning/active-workstream` and current phase plan into ContextAssemblerTool output |
| Automatic CLAUDE.md update loop | When new pitfalls accumulate in memory, a hook proposes additions to CLAUDE.md for human review | HIGH | Connects learning-engine.py → diff proposal → human approval gate in dashboard |
| Multi-user shared memory namespaces | Teams can share a namespace (e.g., `team/backend`) where memories from any member's agent sessions contribute to shared context | HIGH | Extends ProjectMemoryStore to user-scoped sub-namespaces; requires multi-user auth first |

### Anti-Features (Commonly Requested, Often Problematic)

| Feature | Why Requested | Why Problematic | Alternative |
|---------|---------------|-----------------|-------------|
| Full Qdrant cluster sync (replication protocol) | "Sync Qdrant between nodes" sounds like the right solution for vector sync | Qdrant's built-in distributed mode requires 3+ nodes, Raft consensus, Docker cluster setup — massively over-engineered for a 2-node laptop+VPS scenario | Keep flat files as source of truth; derive vectors from flat files on each node after sync. NodeSyncTool's existing approach is correct. |
| Real-time memory sync (websocket/live) | Would mean edits on VPS appear instantly on laptop | Cross-node websocket keepalive is fragile over SSH tunnels, adds complexity for marginal benefit; most memory writes are at task end, not interactive | Periodic sync (cron, post-task hook) is sufficient; give `node_sync merge` a keyboard shortcut |
| Global shared memory without isolation | "All agents share everything" is the simplest model | Memory bleed between projects is a real bug (pitfall #103 in CLAUDE.md). Without project scoping, Agent42's own dev memories contaminate customer-project memories | Enforce namespace separation: global (cross-project learnings), project-scoped, user-scoped |
| CLAUDE.md auto-update without human review | Automated edits to a file Claude reads = prompt injection risk | A compromised agent session could write malicious instructions into CLAUDE.md that affect future sessions | Propose changes via diff in dashboard; require human approval before write |
| Multi-user RBAC with OAuth2 / SSO in MVP | Teams want SSO | Full OAuth2 flow adds 3-4 weeks of auth work before any agent feature is delivered | Start with multi-user with bcrypt password auth; add OAuth2/SSO in a later phase once the namespace model is proven |
| Custom fine-tuned models per user | Personalization via fine-tuning | Agent42 explicitly out-of-scope (see PROJECT.md); OpenAI-compatible API is the boundary | Use memory + skills for personalization instead of model weights |

---

## Feature Dependencies

```
[One-command setup — Linux]
    └──requires──> [.mcp.json generation]
    └──requires──> [Claude Code settings.json hook registration]
    └──requires──> [jcodemunch repo indexing]
    └──requires──> [Setup validation / health check]

[One-command setup — Windows]
    └──requires──> [One-command setup — Linux] (shared core logic)
    └──requires──> [Windows path normalization] (already in hooks, needs setup.sh)

[Bi-directional memory sync with conflict resolution]
    └──requires──> [UUID + timestamp per memory entry] (schema change to MEMORY.md)
    └──enhances──> [NodeSyncTool merge] (replace mtime-wins with entry-union merge)

[Unified context engine]
    └──requires──> [ContextAssemblerTool jcodemunch path] (new code)
    └──requires──> [GSD state reader] (reads .planning/ current phase)
    └──enhances──> [Effectiveness-aware injection] (reads EffectivenessStore)
    └──depends-on──> [jcodemunch MCP server available] (external dependency)

[CLAUDE.md template generation]
    └──requires──> [project_interview.py or equivalent interrogation]
    └──enhances──> [Guided first-run setup] (called from setup script)

[Per-project memory namespace in MemoryTool]
    └──requires──> [ProjectMemoryStore] (already exists)
    └──requires──> [project param wired in MemoryTool.execute()]

[Multi-user RBAC + shared memory namespaces]
    └──requires──> [Multi-user auth] (dashboard currently single-user)
    └──requires──> [User identity in ToolContext] (agents need to know which user)
    └──requires──> [Per-project memory namespace] (foundation)
    └──enhances──> [Shared team namespace] (union of user namespaces)

[Automatic CLAUDE.md update loop]
    └──requires──> [learning-engine.py producing structured candidates] (partially exists)
    └──requires──> [Dashboard diff/approval UI]
    └──conflicts──> [CLAUDE.md auto-update without review] (anti-feature above)
```

### Dependency Notes

- **Unified context engine requires jcodemunch available:** ContextAssemblerTool must gracefully degrade when jcodemunch MCP is not connected. The existing graceful degradation pattern (try/except, None checks) applies.
- **Bi-directional sync memory schema change:** Adding UUID+timestamp to MEMORY.md entries is a breaking change for existing NodeSyncTool merge logic. Migration path: detect old format (no UUID), assign UUIDs on first sync.
- **Multi-user RBAC is a phase-boundary feature:** It requires auth infrastructure changes (dashboard multi-user) before any agent feature can use it. This must be its own phase, not bundled with context engine work.
- **CLAUDE.md auto-update conflicts with prompt injection safety:** The approval gate is mandatory, not optional. Any implementation shortcut that skips human review is an anti-feature.

---

## MVP Definition

This is a subsequent milestone (not the first), so "MVP" means the minimum that delivers the stated milestone value.

### Launch With (Phase 1 — Setup Foundation)

- [ ] `setup.sh` generates `.mcp.json` with Agent42 MCP server configured — without this, users cannot use Agent42 tools from Claude Code at all
- [ ] `setup.sh` patches `.claude/settings.json` to register all hooks — hooks exist but new installs don't get them
- [ ] `setup.sh` runs jcodemunch `index_folder` on the project root — context-loader guidance is useless without the index
- [ ] Windows Git Bash support in setup.sh — the primary dev machine (this repo) is Windows; current setup.sh has no Windows path handling
- [ ] Setup validation at end (Python OK, MCP server ping, jcodemunch responds)
- [ ] CLAUDE.md template for Agent42 projects — first thing users encounter after setup; the template encodes the platform's value

### Add After Validation (Phase 2 — Memory Sync + Context)

- [ ] Conflict-resistant memory sync: UUID+timestamp entries, entry-union merge in NodeSyncTool — current mtime-wins silently loses data on concurrent edits
- [ ] ContextAssemblerTool jcodemunch path — add code symbol search to the unified context API
- [ ] Per-project memory namespace wired into MemoryTool — `project` param already in MemoryTool schema but routes to global store
- [ ] GSD workstream state in context engine — surfaces current phase plan when topic matches

### Future Consideration (Phase 3+ — Enterprise)

- [ ] Multi-user auth in dashboard — deferred because it requires full auth refactor; single-user is sufficient for solo developers
- [ ] Shared team memory namespaces — depends on multi-user auth being solid first
- [ ] Automatic CLAUDE.md update loop with approval gate — depends on learning-engine producing reliable structured candidates (currently noisy)
- [ ] OAuth2/SSO — deferred; adds weeks of auth work before any agent value

---

## Feature Prioritization Matrix

| Feature | User Value | Implementation Cost | Priority |
|---------|------------|---------------------|----------|
| One-command setup (Linux) | HIGH | MEDIUM | P1 |
| One-command setup (Windows) | HIGH | MEDIUM | P1 |
| .mcp.json + hook registration in setup | HIGH | LOW | P1 |
| Setup validation / health check | MEDIUM | LOW | P1 |
| CLAUDE.md template generation | HIGH | MEDIUM | P1 |
| Conflict-resistant memory sync (UUID+timestamp) | HIGH | MEDIUM | P2 |
| ContextAssemblerTool + jcodemunch path | HIGH | MEDIUM | P2 |
| Per-project memory namespace in MemoryTool | MEDIUM | LOW | P2 |
| GSD workstream state in context engine | MEDIUM | MEDIUM | P2 |
| Effectiveness-aware context injection | MEDIUM | LOW | P2 |
| Multi-user auth in dashboard | HIGH | HIGH | P3 |
| Shared team memory namespaces | HIGH | HIGH | P3 |
| Automatic CLAUDE.md update loop | MEDIUM | HIGH | P3 |
| OAuth2/SSO | MEDIUM | HIGH | P3 |

**Priority key:**
- P1: Must have — core value delivery of this milestone
- P2: Should have — significantly improves value, add when core is solid
- P3: Nice to have — enterprise tier, future consideration

---

## Competitor Feature Analysis

Agent42's context here is not competing against generic agent platforms — it's competing against manual developer setup and scattered tooling. The relevant comparisons are:

| Feature | Raw Claude Code (no Agent42) | Cursor / Copilot | Agent42 Goal |
|---------|------------------------------|------------------|--------------|
| Setup time for new project | 30-60 min (manual CLAUDE.md, .mcp.json, hooks) | 5 min (GUI installer) | <5 min (`bash setup.sh`) |
| Code intelligence in agent context | None beyond file reads | Symbol search via IDE index | jcodemunch symbols + semantic memory merged |
| Cross-session memory | Manual CLAUDE.md edits | None | Automatic via hooks + MemoryTool |
| Multi-node memory sync | None | N/A | NodeSyncTool with conflict resolution |
| Project-level memory isolation | None | None | ProjectMemoryStore namespaces |
| Workflow state in context | None | None | GSD phase plan surfaced in context |
| Team shared memory | None | Copilot Enterprise workspace | Shared namespace (P3) |

The core gap vs raw Claude Code is setup friction and context continuity. Closing that gap is the P1/P2 scope. The enterprise features are where Agent42 diverges beyond Claude Code's built-in capabilities.

---

## Agent42-Specific Dependencies on Existing Capabilities

These features require specific Agent42 internals to be working correctly first:

| New Feature | Depends On | Risk |
|-------------|-----------|------|
| Setup generates .mcp.json | `mcp_server.py` transport stable | LOW — already used in production |
| Context engine + jcodemunch | jcodemunch MCP server installed and indexed | MEDIUM — external dependency, may not be installed |
| Conflict-resistant sync | NodeSyncTool SSH connectivity to `agent42-prod` | LOW — SSH config already set up |
| Effectiveness-aware context | EffectivenessStore wired into ToolRegistry | LOW — already implemented (Phase 21) |
| Per-project namespace in MemoryTool | ProjectMemoryStore | LOW — module exists, just needs wiring |
| Multi-user RBAC | Dashboard auth refactor | HIGH — current JWT auth is single-user; significant rework |
| Auto-CLAUDE.md loop | learning-engine.py structured output | MEDIUM — learning-engine exists but outputs unstructured text |

---

## Sources

- Agent42 codebase inspection: `tools/node_sync.py`, `tools/memory_tool.py`, `tools/context_assembler.py`, `.claude/hooks/context-loader.py`, `.claude/hooks/jcodemunch-reindex.py`, `memory/project_memory.py`, `memory/effectiveness.py`, `setup.sh`
- [Qdrant Distributed Deployment Docs](https://qdrant.tech/documentation/guides/distributed_deployment/) — confirmed flat-file-as-source-of-truth is correct for 2-node scenario; full Qdrant cluster is overkill
- [Collaborative Memory with Dynamic Access Control (arxiv)](https://arxiv.org/html/2505.18279v1) — dual-tier private/shared memory architecture pattern for multi-user systems
- [Why RBAC is Not Enough for AI Agents](https://www.osohq.com/learn/why-rbac-is-not-enough-for-ai-agents) — confirms monitoring + anomaly detection required beyond pure RBAC
- [Claude Code Hooks Guide](https://code.claude.com/docs/en/hooks-guide) — confirmed MCP tool naming convention (`mcp__<server>__<tool>`) and settings.json as hook registration point
- [Engineering Challenges of Bi-Directional Sync](https://www.stacksync.com/blog/the-engineering-challenges-of-bi-directional-sync-why-two-one-way-pipelines-fail) — "last write wins" is the naive failure mode; version vectors / entry-level tracking is the correct approach
- [Multi-Tenant Isolation Challenges in LLM Agent Platforms](https://www.researchgate.net/publication/399564099_Multi-Tenant_Isolation_Challenges_in_Enterprise_LLM_Agent_Platforms) — isolation must span identity, data, AND execution context
- [Context Engine MCP (Context-Engine-AI/Context-Engine)](https://github.com/Context-Engine-AI/Context-Engine) — confirms auto-routing across semantic search, symbol graph, and memory is the right unified context pattern

---

*Feature research for: GSD & jcodemunch Integration (Agent42 v3.0)*
*Researched: 2026-03-17*

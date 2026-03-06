# Roadmap: Agent42

## Milestones

- ✅ **v1.0 Free LLM Provider Expansion** — Phases 1-6 (shipped 2026-03-02)
- 🚧 **v1.1 Layout & Authentication Fixes** — Phases 7-10 (in progress)
- 📋 **v1.2 Claude Code Automation Enhancements** — Phases 11-15 (planned)

## Phases

<details>
<summary>✅ v1.0 Free LLM Provider Expansion (Phases 1-6) — SHIPPED 2026-03-02</summary>

- [x] Phase 1: Foundation + Cerebras (2/2 plans) — completed 2026-03-02
- [x] Phase 2: Groq Integration (2/2 plans) — completed 2026-03-02
- [x] Phase 3: Mistral Integration (2/2 plans) — completed 2026-03-02
- [x] Phase 4: SambaNova Integration (2/2 plans) — completed 2026-03-02
- [x] Phase 5: Together AI Integration (2/2 plans) — completed 2026-03-02
- [x] Phase 6: Routing + Config Finalization (2/2 plans) — completed 2026-03-02

See [v1.0-ROADMAP.md](milestones/v1.0-ROADMAP.md) for full details.

</details>

<details>
<summary>🚧 v1.1 Layout & Authentication Fixes (Phases 7-10) — IN PROGRESS</summary>

- [x] Phase 7: Real-time UI Updates (2/2 plans) — completed 2026-03-05
- [x] Phase 8: Authentication Flow Improvements (1/1 plans) — completed 2026-03-05
- [x] Phase 9: Error Handling and User Feedback (1/1 plans) — completed 2026-03-06
- [ ] Phase 10: Visual Polish and Consistency (0/1 plans) — deferred

See [v1.1-ROADMAP.md](milestones/v1.1-ROADMAP.md) for full details.

</details>

### v1.2 Claude Code Automation Enhancements (Phases 11-15)

**Milestone Goal:** Implement MCP servers, hooks, skills, and subagents to improve development velocity, catch production bugs earlier, and codify repetitive workflows

- [x] **Phase 11: MCP Server Integration** - Configure context7 and GitHub MCP servers for library docs and PR/issue management (completed 2026-03-06)
- [x] **Phase 12: Security Gate Hook** - Add PreToolUse hook that blocks edits to sensitive files without explicit confirmation (completed 2026-03-06)
- [ ] **Phase 13: Scaffolding Skills** - Create skills that generate test files, provider boilerplate, and tool boilerplate from project conventions
- [ ] **Phase 14: Operational Skills** - Create skills for production health checks and pitfall table maintenance
- [ ] **Phase 15: Specialized Subagents** - Create subagent definitions for test coverage auditing, dependency health, migration impact, and deploy verification

## Phase Details

### Phase 11: MCP Server Integration
**Goal**: Developer can access live library docs and manage GitHub resources without leaving Claude Code
**Depends on**: Nothing (independent config work)
**Requirements**: MCP-01, MCP-02, MCP-03
**Success Criteria** (what must be TRUE):
  1. Developer can query context7 for any project dependency (openai, fastapi, pytest, etc.) and receive current API docs
  2. Developer can list, create, and comment on GitHub issues and PRs from within Claude Code
  3. Developer can check CI/workflow status for the agent42 repo from within Claude Code
  4. `.mcp.json` persists server configs so they survive session restarts and can be shared
**Plans**: 1 plan
Plans:
- [ ] 11-01-PLAN.md — Configure context7, GitHub, and Playwright MCP servers; clean up stale .playwright-mcp directory

### Phase 12: Security Gate Hook
**Goal**: Security-sensitive files cannot be edited without the developer explicitly confirming awareness
**Depends on**: Nothing (independent hook work)
**Requirements**: HOOK-01, HOOK-02, HOOK-03
**Success Criteria** (what must be TRUE):
  1. Edits to sandbox.py, command_filter.py, config.py, auth.py, and .env are blocked by a PreToolUse gate before the edit happens
  2. The gate outputs a clear message identifying which file is sensitive and why confirmation is required
  3. The PreToolUse gate and existing PostToolUse security-monitor.py operate as complementary layers (pre blocks, post alerts) without duplicate warnings
**Plans**: 1 plan
Plans:
- [ ] 12-01-PLAN.md — Create shared security_config.py, PreToolUse security-gate.py hook, refactor security-monitor.py, register in settings.json

### Phase 13: Scaffolding Skills
**Goal**: Developer can generate correctly-patterned boilerplate for tests, providers, and tools in a single invocation instead of manual copy-paste
**Depends on**: Nothing (independent skill creation)
**Requirements**: SKILL-01, SKILL-02, SKILL-03
**Success Criteria** (what must be TRUE):
  1. `/test-coverage <module>` produces a test file with class-based structure, conftest fixtures, pytest-asyncio markers, and mocked externals matching existing test conventions
  2. `/add-provider` scaffolds a complete provider integration: ProviderSpec in registry.py, ModelSpec entries, Settings field with env var, .env.example update, and a test file
  3. `/add-tool` scaffolds a Tool subclass with correct ABC methods, registration call in agent42.py, and a matching test file
  4. All generated files follow naming conventions from CLAUDE.md (test_*.py, class-based, etc.)
**Plans**: 2 plans
Plans:
- [ ] 13-01-PLAN.md — Create /test-coverage and /add-tool skills with inline templates for test generation and tool scaffolding
- [ ] 13-02-PLAN.md — Create /add-provider skill with inline templates covering all 5 provider integration touchpoints

### Phase 14: Operational Skills
**Goal**: Developer can check production health and maintain the pitfall knowledge base without manual multi-step workflows
**Depends on**: Nothing (independent skill creation)
**Requirements**: SKILL-04, SKILL-05
**Success Criteria** (what must be TRUE):
  1. `/prod-check` runs systemd status, log tail, Qdrant health, Redis ping, dashboard HTTP check, and disk usage over SSH in one pass and reports results
  2. Pitfall skill auto-detects the next pitfall number and formats entries matching the existing table structure in CLAUDE.md
  3. Both skills can be invoked as slash commands within Claude Code sessions
**Plans**: TBD

### Phase 15: Specialized Subagents
**Goal**: Developer can dispatch focused analysis agents for test coverage gaps, dependency staleness, migration risk, and deploy readiness
**Depends on**: Nothing (independent agent definitions)
**Requirements**: AGENT-01, AGENT-02, AGENT-03, AGENT-04
**Success Criteria** (what must be TRUE):
  1. Test coverage auditor produces a prioritized list of untested modules ranked by security risk, change frequency, and complexity
  2. Dependency health agent checks OpenRouter model availability against MODELS dict, pip package versions against PyPI, and flags stale/dead entries
  3. Migration impact agent traces all usages of a specified package or API and flags breaking incompatibilities with file:line references
  4. Deploy verifier agent checks imports resolve, env vars are set, method signatures match cross-module calls, and no required files are untracked in git
  5. All agents are defined as `.claude/agents/` markdown files and can be dispatched on demand
**Plans**: TBD

## Progress

| Phase | Milestone | Plans Complete | Status | Completed |
|-------|-----------|----------------|--------|-----------|
| 1. Foundation + Cerebras | v1.0 | 2/2 | Complete | 2026-03-02 |
| 2. Groq Integration | v1.0 | 2/2 | Complete | 2026-03-02 |
| 3. Mistral Integration | v1.0 | 2/2 | Complete | 2026-03-02 |
| 4. SambaNova Integration | v1.0 | 2/2 | Complete | 2026-03-02 |
| 5. Together AI Integration | v1.0 | 2/2 | Complete | 2026-03-02 |
| 6. Routing + Config Finalization | v1.0 | 2/2 | Complete | 2026-03-02 |
| 7. Real-time UI Updates | v1.1 | 2/2 | Complete | 2026-03-05 |
| 8. Authentication Flow Improvements | v1.1 | 1/1 | Complete | 2026-03-05 |
| 9. Error Handling and User Feedback | v1.1 | 1/1 | Complete | 2026-03-06 |
| 10. Visual Polish and Consistency | v1.1 | 0/1 | Deferred | -- |
| 11. MCP Server Integration | 1/1 | Complete    | 2026-03-06 | -- |
| 12. Security Gate Hook | 1/1 | Complete    | 2026-03-06 | -- |
| 13. Scaffolding Skills | v1.2 | 1/2 | In Progress | -- |
| 14. Operational Skills | v1.2 | 0/? | Not started | -- |
| 15. Specialized Subagents | v1.2 | 0/? | Not started | -- |

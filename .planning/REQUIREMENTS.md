# Requirements: Agent42

**Defined:** 2026-03-05
**Core Value:** Agent42 operates on free-tier LLMs with enough provider diversity that no single outage stops the platform

## v1.2 Requirements

Requirements for Claude Code Automation Enhancements milestone. Each maps to roadmap phases.

### MCP Servers

- [ ] **MCP-01**: Developer can access live library documentation for any dependency (openai, fastapi, playwright, etc.) via context7 MCP server
- [ ] **MCP-02**: Developer can manage GitHub PRs, issues, and CI status directly from Claude Code via GitHub MCP server
- [ ] **MCP-03**: MCP server configurations are persisted in `.mcp.json` for cross-session and team sharing

### Hooks

- [ ] **HOOK-01**: Edits to security-sensitive files (sandbox.py, command_filter.py, config.py, auth.py, .env) are blocked by a PreToolUse gate requiring explicit user confirmation
- [ ] **HOOK-02**: Security gate hook outputs clear feedback identifying the sensitive file and why confirmation is needed
- [ ] **HOOK-03**: Security gate integrates with existing PostToolUse security-monitor.py (complementary, not duplicative)

### Skills

- [ ] **SKILL-01**: Developer can invoke `/test-coverage <module>` to generate a test file following project conventions (class-based, conftest fixtures, pytest-asyncio, mocked externals)
- [ ] **SKILL-02**: Developer can invoke `/add-provider` to scaffold a new LLM provider (ProviderSpec, ModelSpecs, Settings field, .env.example, tests) in one workflow
- [ ] **SKILL-03**: Developer can invoke `/add-tool` to scaffold a new tool (Tool ABC, registration in agent42.py, test file) with correct patterns
- [ ] **SKILL-04**: Developer can invoke `/prod-check` to run all production health checks (systemd, logs, Qdrant, Redis, dashboard, disk) via SSH in one pass
- [ ] **SKILL-05**: Claude can invoke the pitfall skill to auto-format and auto-number new entries in the CLAUDE.md pitfalls table

### Subagents

- [ ] **AGENT-01**: Test coverage auditor can analyze all untested modules and produce a prioritized list ranked by security risk, change frequency, and complexity
- [ ] **AGENT-02**: Dependency health agent can verify OpenRouter model availability, check pip package versions against PyPI, and flag stale entries in MODELS dict and fallback lists
- [ ] **AGENT-03**: Migration impact agent can trace all usages of a package or API change and flag breaking incompatibilities with file:line references
- [ ] **AGENT-04**: Deploy verifier agent can run pre-deploy checks (import verification, env var validation, method signature matching, git status for untracked required files)

## Future Requirements

### Extended Automation

- **AUTO-01**: Automated PR description generation skill
- **AUTO-02**: Changelog generation skill from git history
- **AUTO-03**: Performance regression detection subagent
- **AUTO-04**: Database migration verification subagent

## Out of Scope

| Feature | Reason |
|---------|--------|
| CI/CD pipeline integration | Not needed for local Claude Code automation |
| Slack/Discord MCP servers | Agent42 has its own channel integrations |
| Custom hook UI/dashboard | Hooks are config-file driven, no UI needed |
| Automated test execution on every edit | Already handled by test-validator.py Stop hook |

## Traceability

| Requirement | Phase | Status |
|-------------|-------|--------|
| MCP-01 | — | Pending |
| MCP-02 | — | Pending |
| MCP-03 | — | Pending |
| HOOK-01 | — | Pending |
| HOOK-02 | — | Pending |
| HOOK-03 | — | Pending |
| SKILL-01 | — | Pending |
| SKILL-02 | — | Pending |
| SKILL-03 | — | Pending |
| SKILL-04 | — | Pending |
| SKILL-05 | — | Pending |
| AGENT-01 | — | Pending |
| AGENT-02 | — | Pending |
| AGENT-03 | — | Pending |
| AGENT-04 | — | Pending |

**Coverage:**
- v1.2 requirements: 15 total
- Mapped to phases: 0
- Unmapped: 15

---
*Requirements defined: 2026-03-05*
*Last updated: 2026-03-05 after initial definition*

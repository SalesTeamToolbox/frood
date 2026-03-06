# Phase 11: MCP Server Integration - Context

**Gathered:** 2026-03-05
**Status:** Ready for planning

<domain>
## Phase Boundary

Configure context7, GitHub, and Playwright MCP servers in `.mcp.json` so developers can query library docs, manage GitHub resources, and run browser automation from Claude Code. Consolidate existing `.playwright-mcp/` config into `.mcp.json` as single source of truth.

</domain>

<decisions>
## Implementation Decisions

### Server scope
- context7: Dynamic lookup — works with any library on demand, no pre-configuration needed
- GitHub MCP: All repos accessible (not locked to agent42) — developer specifies repo per query
- Playwright MCP: Consolidate from `.playwright-mcp/` directory into `.mcp.json`
- Three servers total: context7, GitHub, Playwright

### Auth & tokens
- GitHub token stored as system env var `GITHUB_PERSONAL_ACCESS_TOKEN` — not embedded in `.mcp.json`
- `.mcp.json` references the env var without containing the secret
- Token scopes needed: `repo` + `workflow` (PRs, issues, code, CI status)
- context7 and Playwright need no auth tokens

### Sharing strategy
- Commit `.mcp.json` to the repo — any developer cloning gets context7 + Playwright automatically
- GitHub MCP config safe to commit because token is referenced via env var, not embedded
- Remove `.playwright-mcp/` directory after migrating config to `.mcp.json`
- jcodemunch stays in `.mcp.json` (already there)

### Claude's Discretion
- Exact npm package versions for context7 and GitHub MCP servers
- Playwright MCP server configuration details (migrated from existing `.playwright-mcp/`)
- Any additional env vars or args needed for each server

</decisions>

<specifics>
## Specific Ideas

No specific requirements — standard MCP server configuration following Claude Code conventions.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `.mcp.json`: Already exists with jcodemunch server configured — extend with new entries
- `.playwright-mcp/`: Contains existing Playwright MCP config to migrate

### Established Patterns
- MCP servers use `command` + `args` + optional `env` in JSON config
- uvx used for Python-based MCP servers (jcodemunch)
- npx used for Node-based MCP servers (context7, GitHub)

### Integration Points
- `.claude/settings.json`: Hook configurations reference the project directory
- `.gitignore`: May need updating if `.playwright-mcp/` removal leaves stale patterns

</code_context>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope

</deferred>

---

*Phase: 11-mcp-server-integration*
*Context gathered: 2026-03-05*

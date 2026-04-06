---
description: "Show MCP server status — active, available, and duplicate detection"
allowed-tools: Read, Bash
---

Show the current MCP server status and detect waste.

## Instructions

1. Read `.mcp.json` for active servers
2. Read `.mcp.available.json` for full catalog
3. Run `tasklist | grep -c "node.exe"` and `tasklist | grep -c "python.exe"` and `tasklist | grep -c "claude.exe"` to get process counts

Display a table:

| Server | Status | Tools | Notes |
|--------|--------|-------|-------|
| agent42 | Active (essential) | 29 | Core platform |
| jcodemunch | Active (essential) | 30 | Codebase nav |
| agent42-remote | Inactive | 29 | Deploy only |
| context7 | Inactive | 2 | Plugin covers this |
| playwright | Inactive | ~20 | Plugin covers this |
| github | Inactive | ~20 | Plugin covers this |
| firecrawl | Inactive | 12 | Web scraping |

Then show process counts and flag if anything looks abnormal (>5 claude.exe, >20 node.exe).

Also check for plugin duplicates: if a server in `.mcp.json` has a matching plugin installed, warn about double-registration.
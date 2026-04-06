---
description: "Enable an on-demand MCP server (agent42-remote, context7, github, playwright, firecrawl)"
allowed-tools: Read, Edit, Write
---

Activate an MCP server from the available catalog.

## Instructions

1. Read `.mcp.available.json` to get the full server catalog
2. Read `.mcp.json` to see what's currently active
3. The user's argument is: $ARGUMENTS

If no argument provided, list all available servers with their status (active/inactive) and ask which to activate.

If an argument is provided:
- Look up the server name in `.mcp.available.json`
- If not found, show available options
- If already active in `.mcp.json`, say so
- If found, add its config to `.mcp.json` using Edit tool
- Tell the user: "Server `<name>` activated. **Restart your CC session** (Ctrl+Shift+P > Claude Code: Restart) for the change to take effect."

## Always-on servers (do not remove)
- `agent42` — core platform
- `jcodemunch` — codebase navigation

## On-demand servers
- `agent42-remote` — production server management & deployment
- `context7` — library docs (also available via context7 plugin, only activate if plugin not installed)
- `github` — GitHub API (also available via github plugin, `gh` CLI works too)
- `playwright` — browser automation (also available via playwright plugin)
- `firecrawl` — web scraping & crawling
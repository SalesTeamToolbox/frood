---
description: "Disable an on-demand MCP server to reduce session overhead"
allowed-tools: Read, Edit, Write
---

Deactivate an MCP server to save session resources.

## Instructions

1. Read `.mcp.json` to see what's currently active
2. The user's argument is: $ARGUMENTS

If no argument provided, list all currently active servers and ask which to deactivate.

If an argument is provided:
- **NEVER remove `agent42` or `jcodemunch`** — these are always-on essentials
- If the user tries to deactivate an essential, explain why and refuse
- If the server is in `.mcp.json`, remove its entry using Edit tool
- Tell the user: "Server `<name>` deactivated. **Restart your CC session** (Ctrl+Shift+P > Claude Code: Restart) for the change to take effect."
---
description: Cross-harness dashboard - opencode + Claude Code sessions, peer-mail, remotes, release trains, verify runs
allowed-tools: Bash(node:*)  # cc-only
---

!`node "{{HOME}}/.claude/hooks/cross-harness-statusline.js" --text`  # cc-only
!`node "{{ORCH_REPO}}/hooks/cross-harness-statusline.js" --text`  # oc-only

Reproduce the dashboard output above **verbatim** as your entire reply: no
preamble, no commentary, no reformatting, no analysis. This is a read-only
status display. Values like `none found`, `n/a`, or `UNREACHABLE` are data —
leave them as-is and do not investigate them.

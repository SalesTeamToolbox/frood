---
name: memory
description: Persistent memory management for cross-task learning and context.
always: true
---

# Memory Skill

You have access to a two-layer persistent memory system:

## MEMORY.md (Long-term facts)
Consolidated knowledge and preferences extracted from interactions.
- User preferences and coding style
- Project conventions and architecture decisions
- Common patterns and solutions

## HISTORY.md (Event log)
Append-only chronological record of significant events.
- Task completions and outcomes
- Decisions made and their reasoning
- Errors encountered and resolutions

## Usage Guidelines
- After completing a task, record key learnings in memory.
- Before starting a task, check memory for relevant context.
- Keep MEMORY.md concise — summarize, don't duplicate.
- HISTORY.md is append-only — never edit past entries.

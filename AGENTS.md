# AGENTS.md — Agent42 Intelligence Layer

This file is read by both OpenCode and Claude Code to provide Agent42 memory and context integration.

## Memory System

Agent42 provides persistent memory via the `agent42_memory` MCP tool. Use it to recall past context and store new learnings.

### Automatic Recall

On complex or continuation prompts, search memory BEFORE answering. This is critical for maintaining conversation continuity across session restarts.

**When to recall:**
- The user references something from a previous session ("as we discussed", "like before")
- The user resumes after a restart ("I restarted", "back now", "ran the test")
- The prompt involves project-specific decisions, architecture, or deployment
- The prompt mentions names, servers, credentials, or configuration that may have been stored
- You're unsure about a project convention or past decision

**When NOT to recall:**
- Simple code questions ("what does this function do?")
- Generic knowledge questions unrelated to the project
- Very short greetings or acknowledgements

**How to recall:**
```
agent42_memory(action="search", content="<relevant keywords from the prompt>")
```

### Storing Memories

When you discover something the user would want remembered across sessions, store it:
```
agent42_memory(action="store", content="## Section Name\n- Key fact or decision")
```

Store: deployment procedures, architecture decisions, user preferences, server details, recurring issues and their fixes, project conventions.

### Memory Actions Reference

| Action | When to use |
|--------|-------------|
| `search` | Find past context relevant to current prompt |
| `recall` | Read the full current memory contents |
| `store` | Save a new fact, decision, or preference |
| `log` | Record a session event in chronological history |
| `forget` | Remove outdated information |
| `correct` | Fix incorrect stored information |
| `strengthen` | Confirm a recalled memory was useful |

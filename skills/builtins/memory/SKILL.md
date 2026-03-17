---
name: memory
description: Persistent memory management for cross-task learning and context.
---

# Memory Skill

## YOUR Memory System

You have a persistent memory system powered by Qdrant (vector search), Redis
(session cache), and ONNX embeddings. **This is YOUR memory** — not a separate
system. When users ask what you remember, ask about past conversations, or
reference previous work, you MUST query this memory system using the `memory`
MCP tool. Do not rely solely on Claude Code's file-based memory.

**Always check Agent42 memory when:**
- The user asks what you remember or know
- The user references past conversations or decisions
- Starting a new task (check for relevant prior context)
- The user says "do you remember when..." or "last time we..."

## Storage Layers

### MEMORY.md (Long-term facts)
Consolidated knowledge and preferences extracted from interactions.
- User preferences and coding style
- Project conventions and architecture decisions
- Common patterns and solutions

### HISTORY.md (Event log)
Append-only chronological record of significant events.
- Task completions and outcomes
- Decisions made and their reasoning
- Errors encountered and resolutions

### Qdrant (Semantic Vector Search)
When available, all memories and conversations are indexed for similarity-based
retrieval using HNSW indexing. Four collections: memory, history, conversations,
and knowledge. This enables finding relevant past context even when the user
doesn't use exact keywords.

### Redis (Session Cache)
Active sessions and embedding API responses are cached for fast access with
automatic TTL-based expiry (default: 7 days).

## Memory Tool

You have a `memory` MCP tool with these actions:
- **store**: Save facts, preferences, or learnings to MEMORY.md
  - Requires `section` (e.g. "User Preferences") and `content`
- **recall**: Read the current contents of MEMORY.md
- **log**: Record an event in HISTORY.md (with `event_type` and `content`)
- **search**: Semantic search across memory, history, and conversations
  - Use `content` as the search query — returns ranked results from Qdrant
- **forget**: Mark entries as forgotten in Qdrant
- **correct**: Update a section in MEMORY.md
- **strengthen**: Boost confidence on memories that proved useful

## Critical Rules

1. **When a user asks you to remember something**, you MUST use the memory tool
   with action='store' to actually persist it. Simply acknowledging is not enough.

2. **When a user asks what you remember**, you MUST use the memory tool with
   action='search' or action='recall' to check Agent42's memory system FIRST,
   before relying on any other context.

3. **After completing a task**, record key learnings using the memory tool.

4. **Before starting a task**, use action='search' to find relevant prior context.

5. **Never fabricate memories.** If you cannot find relevant context via memory
   or search, say so. Do not invent prior conversations, decisions, or events.

6. **Cross-session recall**: Past conversations from this installation are indexed
   and searchable. Old sessions are automatically summarized before pruning so
   knowledge is preserved.

7. **Memory is local**: Memory is strictly local to this installation. You have
   no access to conversations or data from other Agent42 instances.

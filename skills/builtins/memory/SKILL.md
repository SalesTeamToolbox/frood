---
name: memory
description: Persistent memory management for cross-task learning and context.
always: true
---

# Memory Skill

You have access to a persistent memory system with optional enhanced backends:

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

## Semantic Search
When an embedding API is configured (OpenAI or OpenRouter), memory and history
are indexed for similarity-based retrieval. When Qdrant is available, search
uses HNSW indexing for sub-millisecond results across four collections: memory,
history, conversations, and knowledge.

## Cross-Session Recall
When Qdrant is configured, conversations from any channel are indexed and
searchable. Old sessions are automatically summarized before pruning so
knowledge is preserved. You can recall past conversations across channels
(e.g., "What did we discuss about the API design?").

## Session Caching
When Redis is configured, active sessions are cached in memory for fast access
with automatic TTL-based expiry (default: 7 days). Embedding API responses are
also cached to reduce costs.

## Usage Guidelines
- After completing a task, record key learnings in memory.
- Before starting a task, check memory for relevant context.
- Keep MEMORY.md concise — summarize, don't duplicate.
- HISTORY.md is append-only — never edit past entries.
- Use semantic search when looking for specific past context.

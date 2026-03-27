# Quick Task 260326-vny: Optimize hook pipeline — Summary

## What changed

### context-loader.py (rewritten)
- **Removed**: lessons.md injection (redundant with CLAUDE.md + reference docs)
- **Removed**: Full reference file loading (terminology, conventions, new-components, configuration, deployment, project-structure)
- **Kept**: Filtered pitfalls (only rows matching work type Area column)
- **Kept**: jcodemunch MCP tool guidance (what to run before starting work)
- **Kept**: GSD nudge for multi-step prompts
- **Kept**: Memory storage reminder for knowledge-producing work
- **Added**: MAX_PITFALLS_CHARS=4000 cap (~1,000 tokens)

### memory-recall.py (trimmed)
- **Removed**: Layer 2 (MEMORY.md keyword search) — Claude Code auto-memory already loads its own MEMORY.md
- **Removed**: Layer 3 (HISTORY.md keyword search) — redundant with Qdrant semantic search
- **Kept**: Layer 0 (previous session context from handoff.json)
- **Kept**: Layer 1 (Qdrant semantic search via search service or Agent42 API)
- **Kept**: Layer 1.5 (Qdrant direct scroll + keyword match fallback)

### settings.json
- **Removed**: proactive-inject.py from UserPromptSubmit hooks (low ROI, requires Agent42 API running)
- Pipeline now: conversation-accumulator → memory-recall → context-loader

### lessons.md
- File kept in place as static reference doc — no longer auto-injected

## Token impact

| Component | Before | After | Reduction |
|-----------|--------|-------|-----------|
| conversation-accumulator | 0 | 0 | — |
| memory-recall | ~1,250 | ~190 | 85% |
| proactive-inject | ~500 | removed | 100% |
| context-loader | ~9,000 | ~700 | 92% |
| **TOTAL per-prompt** | **~10,750** | **~890** | **92%** |

### Per work-type (context-loader only)

| Work Type | Before | After |
|-----------|--------|-------|
| Tools | 37,107 chars | 2,421 chars |
| Security | 33,267 chars | 3,198 chars |
| Testing | 26,738 chars | 2,047 chars |
| Config | 33,129 chars | 1,936 chars |
| Memory | 32,721 chars | 3,279 chars |
| Deployment | 34,691 chars | 3,058 chars |
| Trivial | 0 | 0 |

## Files changed
- `.claude/hooks/context-loader.py` — Rewritten: pitfalls + jcodemunch only
- `.claude/hooks/memory-recall.py` — Removed layers 2-3 keyword search
- `.claude/settings.json` — Removed proactive-inject hook

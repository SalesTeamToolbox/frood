# Hooks Reference

## Active Hooks (Automatic)

| Hook | Trigger | Action |
|------|---------|--------|
| `conversation-accumulator.py` | UserPromptSubmit | Captures user prompts to buffer for session context persistence |
| ~~`context-loader.py`~~ | ~~UserPromptSubmit~~ | **REMOVED** — was injecting ~25K tokens/conversation loading reference docs on every prompt. Docs still in `.claude/reference/` for manual lookup. |
| `memory-recall.py` | UserPromptSubmit | Surfaces relevant memories from Qdrant + previous session context before Claude thinks |
| `proactive-inject.py` | UserPromptSubmit | Surfaces past learnings relevant to detected task type |
| `security-gate.py` | PreToolUse (Write/Edit/Bash) | Blocks edits to security-sensitive files (requires approval) |
| `security-monitor.py` | PostToolUse (Write/Edit) | Flags security-sensitive changes for review (sandbox, auth, command filter) |
| `format-on-write.py` | PostToolUse (Write/Edit) | Auto-formats Python files with ruff on every write |
| `cc-memory-sync.py` | PostToolUse (Write/Edit) | Embeds CC memory files into Qdrant for semantic recall |
| `jcodemunch-reindex.py` | Stop + PostToolUse | Re-indexes codebase after structural file changes |
| `jcodemunch-token-tracker.py` | PostToolUse | Tracks token savings from jcodemunch vs full file reads |
| `session-handoff.py` | Stop | Captures session state for auto-resume continuity |
| `test-validator.py` | Stop | Validates tests pass, checks new modules have test coverage |
| `learning-engine.py` | Stop | Records development patterns, vocabulary, and skill candidates |
| `memory-learn.py` | Stop | Captures new learnings into memory system for future recall |
| `effectiveness-learn.py` | Stop | Extracts structured learnings with LLM for quarantine review |
| `knowledge-learn.py` | Stop | Extracts session knowledge and upserts to Qdrant |
| `credential-sync.py` | SessionStart | Syncs CC credentials to remote VPS on session start |

## Hook Protocol

- Hooks receive JSON on stdin with `hook_event_name`, `project_dir`, and event-specific data
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow, exit code 2 = block (for PreToolUse hooks)

## Context Clear Protocol

When suggesting the user clear their context window (e.g., "clear context and reply with
your choice"), **you MUST save the decision state first**. The hooks capture user prompts
automatically, but assistant-side content (numbered options, proposals, analysis) is NOT
captured by hooks — only tool calls are.

**Before suggesting a context clear:**

1. Write a summary of pending decisions/options to CC auto-memory (e.g., a file in
   `~/.claude/projects/.../memory/`) so the next session can find it
2. Include: what options were presented, any analysis or recommendations, and what the
   user needs to respond with
3. The `conversation-accumulator.py` hook captures user prompts automatically, and
   `session-handoff.py` captures tool interactions (AskUserQuestion, TodoWrite, Agent),
   but plain text options in assistant responses are invisible to hooks

**On session resume:** `memory-recall.py` automatically surfaces the previous session's
conversation context from `handoff.json`. Check `[agent42-session-context]` in the hook
output for previous session state.

## How It Works

```
┌──────────────────────────────────────────────────────────────────┐
│  SessionStart → credential-sync.py (syncs CC creds to VPS)      │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  User Prompt Submitted (UserPromptSubmit)                        │
│  ├─ conversation-accumulator.py — captures prompt to buffer      │
│  ├─ context-loader.py    — loads lessons + reference docs        │
│  ├─ memory-recall.py     — surfaces memories + prev session ctx  │
│  └─ proactive-inject.py  — injects past learnings for task type  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  PreToolUse → security-gate.py (blocks edits to security files)  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Claude Processes Request (may use Write/Edit tools)             │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  PostToolUse (Write/Edit):                                       │
│  ├─ security-monitor.py  — flags security-sensitive changes      │
│  ├─ format-on-write.py   — auto-formats Python with ruff         │
│  └─ cc-memory-sync.py    — embeds CC memory files into Qdrant    │
│  PostToolUse (all):                                              │
│  ├─ jcodemunch-token-tracker.py — tracks token savings           │
│  └─ jcodemunch-reindex.py       — re-indexes after file changes  │
└──────────────────────┬───────────────────────────────────────────┘
                       │
                       ▼
┌──────────────────────────────────────────────────────────────────┐
│  Stop Event Triggers:                                            │
│  ├─ session-handoff.py       — captures state for auto-resume    │
│  ├─ test-validator.py        — runs pytest, checks coverage      │
│  ├─ learning-engine.py       — records patterns, updates lessons │
│  ├─ memory-learn.py          — captures learnings to memory      │
│  ├─ effectiveness-learn.py   — structured learning extraction    │
│  ├─ knowledge-learn.py       — session knowledge to Qdrant       │
│  └─ jcodemunch-reindex.py    — final re-index                    │
└──────────────────────────────────────────────────────────────────┘
```

## Available Agents (On-Demand)

| Agent | Use Case | Invocation |
|-------|----------|------------|
| security-reviewer | Audit security-sensitive code changes | Request security review |
| performance-auditor | Review async patterns, resource usage, timeouts | Ask about performance |

## Related Files

- `.claude/settings.json` — Hook configuration
- `.claude/lessons.md` — Accumulated patterns and vocabulary (referenced by hooks)
- `.claude/learned-patterns.json` — Auto-generated pattern data
- `.claude/reference/` — On-demand reference docs (loaded by context-loader hook)
- `.claude/agents/` — Specialized agent definitions
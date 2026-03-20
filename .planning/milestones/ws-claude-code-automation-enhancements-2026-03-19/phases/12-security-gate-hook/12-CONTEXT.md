# Phase 12: Security Gate Hook - Context

**Gathered:** 2026-03-06
**Status:** Ready for planning

<domain>
## Phase Boundary

Add a PreToolUse hook that blocks edits to security-sensitive files until the developer explicitly approves. Complements the existing PostToolUse security-monitor.py (which warns after edits). Refactor both hooks to share a single security file config.

</domain>

<decisions>
## Implementation Decisions

### Sensitive file list
- Use the full 12-file list: the 10 from security-monitor.py + `.env` + `core/encryption.py`
- Extract file list to a shared `security_config.py` module in `.claude/hooks/`
- Both security-gate.py (PreToolUse) and security-monitor.py (PostToolUse) import from it
- Any file added to the shared config automatically gets both gate (block) and monitor (alert) treatment

### Gate message design
- Concise one-liner format: `[security-gate] BLOCKED: {file} ({description}) -- approve to continue`
- Prefix `[security-gate]` parallels existing `[security-monitor]` — clear which hook is speaking
- No audit logging — git history is the audit trail, Claude Code's tool approval is implicit confirmation

### Gate scope
- Block Write and Edit tools on security files (PreToolUse, exit code 2)
- Also match Bash commands that delete/move security files (rm, mv patterns)
- File-name-only check — no pattern scanning in the gate. Pattern scanning stays in PostToolUse monitor where it can see the actual content written

### Pre/Post hook coordination
- Both hooks operate independently — different purposes (pre = "are you sure?", post = "here's what changed")
- No suppression of PostToolUse warnings when PreToolUse approved — they say different things
- Refactor security-monitor.py to import SECURITY_FILES from shared security_config.py as part of this phase

### Claude's Discretion
- Exact matching logic for Bash rm/mv commands (regex vs string matching)
- Whether to add tests for the hook (hook testing patterns)
- settings.json PreToolUse registration format details

</decisions>

<specifics>
## Specific Ideas

No specific requirements -- open to standard approaches. The hook should feel like a natural extension of the existing security-monitor.py pattern.

</specifics>

<code_context>
## Existing Code Insights

### Reusable Assets
- `.claude/hooks/security-monitor.py`: Has SECURITY_FILES dict with 10 files + descriptions, DANGEROUS_PATTERNS list, `check_security_file()` and `scan_content()` functions
- `.claude/settings.json`: Hook registration format for PostToolUse (matcher, hooks array with type/command/timeout)

### Established Patterns
- Hook protocol: JSON on stdin with `hook_event_name`, `tool_name`, `tool_input`, `tool_output`
- Output to stderr is shown to Claude as feedback
- Exit code 0 = allow, exit code 2 = block (for PreToolUse hooks)
- All hooks are Python scripts with `#!/usr/bin/env python3` shebang

### Integration Points
- `.claude/settings.json` needs a new `PreToolUse` section with matcher for `Write|Edit|Bash`
- `.claude/hooks/security_config.py` (new) — shared config imported by both hooks
- `.claude/hooks/security-monitor.py` — refactor to import from security_config.py

</code_context>

<deferred>
## Deferred Ideas

None -- discussion stayed within phase scope

</deferred>

---

*Phase: 12-security-gate-hook*
*Context gathered: 2026-03-06*

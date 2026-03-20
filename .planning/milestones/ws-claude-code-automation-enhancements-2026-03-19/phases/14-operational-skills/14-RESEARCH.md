# Phase 14: Operational Skills - Research

**Researched:** 2026-03-06
**Domain:** Claude Code skills (.claude/skills/) for production operations and documentation maintenance
**Confidence:** HIGH

## Summary

Phase 14 creates two Claude Code skills: `/prod-check` (SKILL-04) for one-pass production health verification, and a pitfall management skill (SKILL-05) for auto-formatting and auto-numbering new entries in the CLAUDE.md pitfalls table. These are `.claude/skills/` SKILL.md files that Claude Code discovers as slash commands -- they are instructions for the developer's IDE assistant, not Agent42 runtime tools.

The key architectural insight is that these skills operate on the developer's local machine within Claude Code sessions. `/prod-check` uses Claude Code's built-in `Bash` tool to run `ssh agent42-prod` commands. The pitfall skill uses Claude Code's `Read` and `Edit` tools to parse and modify CLAUDE.md. Neither skill creates Agent42 runtime tools, providers, or agents -- they are pure SKILL.md instruction files following the exact pattern established in Phase 13.

**Primary recommendation:** Create two SKILL.md files in `.claude/skills/` with `disable-model-invocation: true` (manual-only invocation) and inline instructions that reference the production SSH config and CLAUDE.md table structure.

<phase_requirements>
## Phase Requirements

| ID | Description | Research Support |
|----|-------------|-----------------|
| SKILL-04 | Developer can invoke `/prod-check` to run all production health checks (systemd, logs, Qdrant, Redis, dashboard, disk) via SSH in one pass | Skill uses Bash tool with `ssh agent42-prod` commands; production infrastructure documented in MEMORY.md and deployment reference |
| SKILL-05 | Claude can invoke the pitfall skill to auto-format and auto-number new entries in the CLAUDE.md pitfalls table | Skill uses Read tool to find last pitfall number, Edit tool to append formatted row; table structure documented with 4-column pipe format |
</phase_requirements>

## Standard Stack

### Core
| Library/Tool | Version | Purpose | Why Standard |
|-------------|---------|---------|--------------|
| Claude Code Skills | Current | `.claude/skills/<name>/SKILL.md` | Official extension mechanism for Claude Code slash commands |
| YAML Frontmatter | N/A | Skill metadata (name, description, disable-model-invocation) | Required by Claude Code skill spec |

### Supporting
| Tool | Purpose | When to Use |
|------|---------|-------------|
| `ssh agent42-prod` | SSH alias to production server | Used by `/prod-check` to execute remote health checks |
| `Bash` (Claude Code built-in) | Execute shell commands in Claude Code session | Runs SSH commands for prod-check |
| `Read` (Claude Code built-in) | Read file contents | Reads CLAUDE.md to find last pitfall number |
| `Edit` (Claude Code built-in) | Modify files | Appends new pitfall row to CLAUDE.md table |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| `.claude/skills/` SKILL.md | `.claude/commands/` markdown | Commands still work but skills are recommended; skills support supporting files and frontmatter features |
| `disable-model-invocation: true` | Default (model can invoke) | Prod-check has side effects (SSH); pitfall editing should be deliberate -- both should require manual `/` invocation |
| Single monolithic skill | Two separate skills | Separation of concerns; `/prod-check` is operations, pitfall skill is documentation maintenance |

**No installation needed:** Skills are pure markdown files. No pip packages or npm modules required.

## Architecture Patterns

### Recommended Project Structure
```
.claude/skills/
├── add-provider/         # Existing (Phase 13)
│   └── SKILL.md
├── add-tool/             # Existing (Phase 13)
│   └── SKILL.md
├── test-coverage/        # Existing (Phase 13)
│   └── SKILL.md
├── prod-check/           # NEW (SKILL-04)
│   └── SKILL.md
└── add-pitfall/          # NEW (SKILL-05)
    └── SKILL.md
```

### Pattern 1: Task Skill with Side Effects
**What:** A skill that executes a multi-step operational workflow via Claude Code's built-in tools.
**When to use:** When the skill performs actions (SSH commands, file edits) rather than just providing reference knowledge.
**Key design choice:** Set `disable-model-invocation: true` to prevent Claude from triggering these skills automatically. Operational skills with side effects (running SSH commands, editing shared documentation) must be deliberately invoked by the developer.

```yaml
# Source: https://code.claude.com/docs/en/skills
---
name: prod-check
description: Run all production health checks via SSH in one pass
disable-model-invocation: true
---

[Step-by-step instructions for Claude Code to follow...]
```

### Pattern 2: Dynamic Context Injection
**What:** Using `!`command`` syntax to pre-fetch data before Claude sees the skill content.
**When NOT to use for this phase:** The `!`command`` syntax runs shell commands at skill load time and injects output. However, for `/prod-check`, we want Claude to run each SSH command individually and analyze results step-by-step, providing commentary on each check. Running all commands at load time via `!` backtick would give Claude a wall of text without structured analysis. Use explicit Bash tool calls in the instructions instead.
**When to use for this phase:** Could be useful for the pitfall skill to pre-read CLAUDE.md at skill invocation time with `!`grep -c "^|" CLAUDE.md`` to get the current table line count.

### Pattern 3: File Parsing and Table Manipulation
**What:** Instructions that tell Claude how to parse a markdown table, extract the last entry number, and append a correctly formatted new row.
**When to use:** For the pitfall skill (SKILL-05).
**Key details:**
- The pitfall table in CLAUDE.md has 4 columns: `#`, `Area`, `Pitfall`, `Correct Pattern`
- Current last entry is #116
- Entries 1-80 are archived to `.claude/reference/pitfalls-archive.md`
- Recent entries (81+) are inline in CLAUDE.md
- The skill must detect the current last number dynamically (not hardcode 116)

### Anti-Patterns to Avoid
- **Hardcoding the next pitfall number:** The pitfall skill MUST read CLAUDE.md to find the current maximum number dynamically. Hardcoding "117" would break after the first use.
- **Using `!` backtick for all prod-check commands:** This would execute all SSH commands at skill load time, giving Claude a raw dump instead of allowing per-check analysis and structured reporting.
- **Making skills auto-invocable:** Setting `always: false` or leaving `disable-model-invocation` unset would let Claude trigger SSH commands unprompted -- dangerous for operational skills.
- **Creating Agent42 runtime tools:** These skills are for the developer's Claude Code IDE session, not Agent42's agent runtime. Do NOT create `tools/*.py` files.

## Don't Hand-Roll

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| Slash command invocation | Custom CLI scripts or bash aliases | `.claude/skills/<name>/SKILL.md` | Claude Code natively discovers and presents skills as `/` commands |
| SSH connection management | Paramiko or asyncssh wrappers | `ssh agent42-prod` via Bash tool | SSH config alias already configured and tested; no code needed |
| Pitfall number parsing | Custom Python script to parse table | Claude Code's Read tool + regex in instructions | Claude excels at text parsing; instructions guide it to grep for the last `| ### |` row |
| Production health check orchestration | Custom monitoring dashboard | Step-by-step SSH commands in SKILL.md | The skill is a checklist for the developer, not an automated monitoring system |

**Key insight:** Both skills are pure instruction files. The "code" is the SKILL.md markdown that tells Claude Code what to do. There are zero Python files to create, zero tests to write for the skills themselves, and zero runtime dependencies. The testing is manual: invoke `/prod-check` and `/add-pitfall` and verify they work.

## Common Pitfalls

### Pitfall 1: Skills vs Commands Confusion
**What goes wrong:** Creating `.claude/commands/prod-check.md` instead of `.claude/skills/prod-check/SKILL.md`.
**Why it happens:** Both work as slash commands, but the skill format is the recommended approach.
**How to avoid:** Always use `.claude/skills/<name>/SKILL.md` directory structure. Skills support frontmatter features and supporting files.
**Warning signs:** File placed directly in `.claude/commands/` without a directory wrapper.

### Pitfall 2: SSH Alias Not Configured
**What goes wrong:** `/prod-check` fails because `ssh agent42-prod` doesn't work on the developer's machine.
**Why it happens:** The SSH config alias is machine-specific (from MEMORY.md: `agent42-prod` -> Contabo VPS at 163.245.217.2:2222, user `deploy`).
**How to avoid:** Skill instructions should include a "Prerequisites" section that documents the required SSH config. Include a verification step: `ssh agent42-prod "echo OK"`.
**Warning signs:** `ssh: Could not resolve hostname agent42-prod` error.

### Pitfall 3: Pitfall Table Format Mismatch
**What goes wrong:** New pitfall entry doesn't match the existing 4-column pipe format.
**Why it happens:** The table has specific formatting: `| # | Area | Pitfall | Correct Pattern |`
**How to avoid:** Skill instructions must include the exact format template with pipe delimiters. Instruct Claude to read the last 5 rows of the table to match formatting.
**Warning signs:** Markdown rendering breaks, table columns misalign.

### Pitfall 4: Overwriting Extended Reference Section
**What goes wrong:** When appending a pitfall, Claude accidentally inserts the row after the table's trailing `---` separator, or worse, inside the "Extended Reference" section.
**Why it happens:** CLAUDE.md has a `---` separator after the pitfall table, followed by the "Extended Reference" section.
**How to avoid:** Skill instructions must specify: insert new row BEFORE the blank line and `---` that follows the last table row.
**Warning signs:** The pitfall appears outside the table or the Extended Reference section gets corrupted.

### Pitfall 5: Missing Qdrant/Redis Checks in prod-check
**What goes wrong:** Health check misses a service and developer thinks production is healthy when it's not.
**Why it happens:** Only checking `systemctl status agent42` and forgetting Qdrant, Redis, nginx, or disk.
**How to avoid:** The SKILL.md must enumerate ALL checks explicitly: agent42 service, Qdrant health, Redis ping, dashboard HTTP, log tail, disk usage. Use the requirement list from SKILL-04 as the definitive checklist.
**Warning signs:** Incomplete output that doesn't cover all 6 health domains.

## Code Examples

### Example 1: prod-check SKILL.md Structure

```yaml
# Source: Phase 13 skill patterns + Claude Code docs
---
name: prod-check
description: Run all production health checks via SSH in one pass
disable-model-invocation: true
---

# /prod-check

Run a comprehensive health check on the Agent42 production server in one pass.

## Prerequisites

- SSH config alias `agent42-prod` must be configured (Contabo VPS, port 2222, user deploy)
- Test with: `ssh agent42-prod "echo OK"`

## Health Checks

Run each check via `ssh agent42-prod "<command>"` and report results.

### 1. Systemd Service Status
```bash
ssh agent42-prod "sudo systemctl status agent42 --no-pager -l"
```
Report: active/inactive, uptime, recent restarts

### 2. Recent Logs (last 50 lines)
```bash
ssh agent42-prod "tail -50 ~/agent42/agent42.log"
```
Report: any ERROR or WARNING lines, stack traces

### 3. Qdrant Health
```bash
ssh agent42-prod "curl -s http://localhost:6333/healthz"
```
Report: healthy/unhealthy, response content

### 4. Redis Ping
```bash
ssh agent42-prod "redis-cli ping"
```
Report: PONG = healthy, anything else = problem

### 5. Dashboard HTTP Check
```bash
ssh agent42-prod "curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/health"
```
Report: 200 = healthy, other codes = problem

### 6. Disk Usage
```bash
ssh agent42-prod "df -h / /var/lib/qdrant"
```
Report: usage percentage, warn if > 80%

## Output Format

Summarize results in a table:

| Check | Status | Details |
|-------|--------|---------|
| Agent42 Service | ... | ... |
| Logs | ... | ... |
| Qdrant | ... | ... |
| Redis | ... | ... |
| Dashboard | ... | ... |
| Disk | ... | ... |
```

### Example 2: add-pitfall SKILL.md Structure

```yaml
# Source: Phase 13 skill patterns + CLAUDE.md table structure
---
name: add-pitfall
description: Auto-format and auto-number a new entry in the CLAUDE.md pitfalls table
disable-model-invocation: true
argument-hint: [area] [pitfall description] [correct pattern]
---

# /add-pitfall

Add a new entry to the Common Pitfalls table in CLAUDE.md with auto-numbering.

## Step 1: Gather Information

If arguments were provided, parse them. Otherwise, ask for:
1. **Area** (e.g., Deploy, Auth, Dashboard, Config, Tools, etc.)
2. **Pitfall** -- what goes wrong (one sentence)
3. **Correct Pattern** -- how to do it right (one sentence)

## Step 2: Read Current State

Read CLAUDE.md and find the last entry number in the Common Pitfalls table.
Look for lines matching the pattern `| ### |` where ### is a number.
The new entry number = last number + 1.

## Step 3: Append Entry

Edit CLAUDE.md to insert a new row at the end of the pitfalls table
(before the blank line and `---` separator that follows the table).

Format: `| {next_number} | {Area} | {Pitfall} | {Correct Pattern} |`

## Step 4: Verify

Read the modified section to confirm the new entry is correctly formatted
and the table still renders properly.
```

### Example 3: YAML Frontmatter Fields

```yaml
# Key frontmatter fields for operational skills
---
name: prod-check                         # Becomes /prod-check slash command
description: Run production health checks # Shown in / autocomplete
disable-model-invocation: true           # Manual-only (prevents auto-trigger)
# NOT using:
# always: false                          # Deprecated in favor of disable-model-invocation
# task_types: [...]                      # Not relevant for Claude Code skills
---
```

Note: The Phase 13 skills used `always: false` and `task_types` which are Agent42 built-in skill frontmatter fields. Claude Code skills use `disable-model-invocation: true` and `description` instead. The `always` and `task_types` fields are still valid but are more relevant for Agent42's skill loader than Claude Code's skill discovery. For Claude Code IDE usage, `disable-model-invocation: true` is the correct way to prevent auto-triggering.

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `.claude/commands/*.md` | `.claude/skills/<name>/SKILL.md` | 2025 | Skills are recommended; commands still work but skills add directory structure, frontmatter features |
| `always: true/false` | `disable-model-invocation: true` | Claude Code skills spec | More explicit control over invocation; `always` still works for Agent42 built-in skills |
| No argument hints | `argument-hint: [args]` | Claude Code skills spec | Autocomplete shows expected arguments in `/` menu |

**Compatibility note:** The Phase 13 skills used `always: false` and `task_types` which work fine in Claude Code (they're just ignored if not recognized). For consistency with the existing codebase, Phase 14 skills MAY use the same fields. However, `disable-model-invocation: true` is the Claude Code-native way to achieve the same effect as `always: false`.

## Open Questions

1. **SSH config portability**
   - What we know: `agent42-prod` SSH alias is configured on the developer's machine per MEMORY.md
   - What's unclear: If other team members need this skill, they'd need the same SSH config
   - Recommendation: Document the SSH config in the skill's Prerequisites section. This is a developer-local skill, not a team-shared one.

2. **Pitfall archival threshold**
   - What we know: Pitfalls 1-80 were archived to `.claude/reference/pitfalls-archive.md`. Current inline entries are 81-116.
   - What's unclear: At what number should the next archival happen? (e.g., when reaching 160, archive 81-160?)
   - Recommendation: Out of scope for this phase. The skill just appends entries. Archival is a separate maintenance task.

3. **Frontmatter field compatibility**
   - What we know: Phase 13 skills used `always: false` and `task_types`, which are Agent42 skill loader fields. Claude Code skills use `disable-model-invocation: true`.
   - What's unclear: Whether using `always: false` vs `disable-model-invocation: true` causes any functional difference in Claude Code.
   - Recommendation: Use `disable-model-invocation: true` for the new skills since it's the Claude Code-native field. Add `always: false` for backward compatibility with Agent42's skill loader if needed.

## Validation Architecture

### Test Framework
| Property | Value |
|----------|-------|
| Framework | pytest 8.x (asyncio_mode = "auto") |
| Config file | `pyproject.toml` [tool.pytest.ini_options] |
| Quick run command | `python -m pytest tests/ -x -q -k "skill"` |
| Full suite command | `python -m pytest tests/ -x -q` |

### Phase Requirements -> Test Map
| Req ID | Behavior | Test Type | Automated Command | File Exists? |
|--------|----------|-----------|-------------------|-------------|
| SKILL-04 | `/prod-check` runs SSH health checks and reports results | manual-only | Manual: invoke `/prod-check` in Claude Code session, verify output table | N/A -- skill is a SKILL.md file, not Python code |
| SKILL-05 | Pitfall skill auto-detects next number and formats entry correctly | unit | `python -m pytest tests/test_pitfall_skill.py -x` | No -- see Wave 0 |

**Manual-only justification for SKILL-04:** The `/prod-check` skill executes SSH commands against a live production server. Automated testing would require either: (a) a live production server accessible from CI, or (b) mocking the entire SSH stack. Neither is practical. The skill is a markdown instruction file -- its correctness is verified by manual invocation.

**SKILL-05 testing approach:** While the skill itself is a SKILL.md file, we CAN test the pitfall number detection and table formatting logic by writing a Python test that:
1. Creates a mock CLAUDE.md with a pitfall table
2. Parses the last entry number
3. Formats a new row and verifies it matches the expected format
4. Verifies the row is inserted at the correct position

However, since SKILL-05 is also a pure instruction file (no Python code), the most practical test is a **validation script** that checks CLAUDE.md table integrity after manual invocation.

### Sampling Rate
- **Per task commit:** `python -m pytest tests/ -x -q` (existing full suite)
- **Per wave merge:** `python -m pytest tests/ -x -q`
- **Phase gate:** Manual invocation of both `/prod-check` and `/add-pitfall` in a Claude Code session + full test suite green

### Wave 0 Gaps
- [ ] `tests/test_skill_files.py` -- validate SKILL.md files exist and have correct frontmatter (can reuse for all skills)
- No framework install needed (pytest already configured)
- No new Python modules to test (skills are pure markdown)

*(Note: The primary validation for this phase is manual invocation in Claude Code. The test file above is a lightweight structural check, not a functional test of skill behavior.)*

## Sources

### Primary (HIGH confidence)
- [Claude Code Skills Documentation](https://code.claude.com/docs/en/skills) -- Complete reference on SKILL.md format, frontmatter fields, argument substitution, invocation control, dynamic context injection
- Project codebase -- `.claude/skills/` existing skills from Phase 13, CLAUDE.md pitfall table structure, MEMORY.md production server details

### Secondary (MEDIUM confidence)
- [BioErrorLog Guide](https://en.bioerrorlog.work/entry/claude-code-custom-slash-command) -- Confirmed `.claude/commands/` still works, YAML frontmatter options

### Tertiary (LOW confidence)
- None

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- Skills mechanism is well-documented by Anthropic official docs and proven by Phase 13 implementation
- Architecture: HIGH -- Follows established Phase 13 pattern exactly; only new content is the skill instructions
- Pitfalls: HIGH -- Based on actual production experience (MEMORY.md, pitfalls-archive.md) and known CLAUDE.md table structure

**Research date:** 2026-03-06
**Valid until:** 2026-04-06 (30 days -- Claude Code skills API is stable)

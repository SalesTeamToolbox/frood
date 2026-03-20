# Phase 2: GSD Auto-Activation - Context

**Gathered:** 2026-03-20
**Status:** Ready for planning

<domain>
## Phase Boundary

Make GSD the default methodology for multi-step coding and planning tasks when Agent42 is installed. Users get structured workflow without manual `/gsd:*` invocation. Trivial tasks (quick questions, simple edits) skip GSD and get direct answers. This phase creates the always-on skill, adds a CLAUDE.md section, and enhances the context-loader hook — it does NOT build new GSD commands or modify GSD internals.

</domain>

<decisions>
## Implementation Decisions

### Activation trigger criteria
- **D-01:** Multi-step detection uses a keyword + structural heuristic, NOT an LLM call. Keywords: "build", "create", "implement", "refactor", "add feature", "set up", "migrate", "convert", "redesign", "scaffold", framework names ("flask app", "django", "react app"), and planning language ("plan", "roadmap", "milestone").
- **D-02:** Trivial task detection (skip GSD): prompts < 30 chars, questions starting with "what", "how", "why", "explain", "show me", slash commands, single-file edits explicitly named ("fix the typo in X"), and debugging/error messages.
- **D-03:** Ambiguous cases default to suggesting GSD with an opt-out — "This looks like a multi-step task. I'll use GSD to plan and execute. Say 'just do it' to skip."

### Nudge format and tone
- **D-04:** The always-on skill provides system-level instructions that Claude reads on every prompt. It does NOT produce visible output — it shapes Claude's behavior silently.
- **D-05:** When GSD activates, Claude's first response should naturally mention the approach: "I'll use GSD to break this down into phases..." — not a robotic "GSD AUTO-ACTIVATED" banner.
- **D-06:** The context-loader hook adds a brief stderr nudge when it detects a multi-step prompt: `[agent42] Tip: This looks like a multi-step task — /gsd:new-project or /gsd:quick available`. One line, not intrusive.

### CLAUDE.md GSD section
- **D-07:** Add a `## Development Methodology` section to CLAUDE.md that establishes GSD as the default process. Content: when to use GSD (multi-step), when to skip (trivial), key commands reference, and a note that Agent42's always-on skill handles auto-detection.
- **D-08:** The CLAUDE.md section is appended to the existing file — do not reorganize or rewrite existing content.

### Skill vs hook responsibility split
- **D-09:** The always-on skill (`gsd-auto-activate`) handles behavioral instructions — tells Claude HOW to think about task complexity and WHEN to suggest GSD. This is the primary mechanism.
- **D-10:** The context-loader hook enhancement is secondary — it adds a subtle stderr hint for multi-step prompts. The hook does NOT make decisions; it surfaces information.
- **D-11:** The always-on skill should reference GSD commands by name (`/gsd:new-project`, `/gsd:quick`, `/gsd:plan-phase`) so Claude knows what to suggest.

### Smart skip behavior
- **D-12:** After skipping GSD for a trivial task, if the task turns out to be complex mid-execution, Claude should suggest pivoting: "This is getting complex — want me to switch to GSD?"
- **D-13:** Never auto-activate GSD inside an already-running GSD workflow (check for `.planning/STATE.md` with active phase status).

### Claude's Discretion
- Exact keyword list and threshold tuning for multi-step detection
- How to phrase the mid-task pivot suggestion
- Whether to include a "GSD cheat sheet" in CLAUDE.md or keep it minimal
- Skill content structure and instruction ordering

</decisions>

<specifics>
## Specific Ideas

- The always-on skill should feel like a knowledgeable colleague who naturally reaches for GSD when appropriate — not a gate or an enforcement mechanism.
- Context-loader hint should be ignorable — if the user doesn't act on it, it fades into the background.
- CLAUDE.md section should be concise (under 30 lines) — developers skim, they don't read essays.

</specifics>

<canonical_refs>
## Canonical References

**Downstream agents MUST read these before planning or implementing.**

### Always-on skill mechanism
- `.claude/skills/add-tool/SKILL.md` — Example skill with YAML frontmatter format (name, description, always, task_types)
- `tests/test_skill_loader.py` — Tests for `always: true` skill loading behavior

### Context-loader hook
- `.claude/hooks/context-loader.py` — Current hook implementation with WORK_TYPE_KEYWORDS, REFERENCE_FILES, JCODEMUNCH_GUIDANCE patterns
- `.claude/settings.json` — Hook registration for UserPromptSubmit event

### Project configuration
- `CLAUDE.md` — Current project instructions (append GSD section here)
- `.planning/workstreams/agent42-ux-and-workflow-automation/REQUIREMENTS.md` — GSD-01 through GSD-04

### GSD command reference
- `~/.claude/commands/gsd/` — All available GSD slash commands (new-project, quick, plan-phase, execute-phase, etc.)

</canonical_refs>

<code_context>
## Existing Code Insights

### Reusable Assets
- `context-loader.py`: Already has WORK_TYPE_KEYWORDS pattern for keyword-based prompt detection. Can add a `gsd` work type with multi-step keywords.
- `.claude/skills/*/SKILL.md`: Existing skill format with `always: true` support. Just create a new skill directory.
- `tests/test_skill_loader.py`: Has test patterns for always-on skills — can extend for the new skill.

### Established Patterns
- Skills use YAML frontmatter: `name`, `description`, `always`, `task_types`
- Context-loader outputs to stderr: `print(message, file=sys.stderr)`
- Hook protocol: JSON on stdin, exit 0 always for UserPromptSubmit
- Skills are loaded from `.claude/skills/` directories containing `SKILL.md`

### Integration Points
- `.claude/skills/gsd-auto-activate/SKILL.md` — New always-on skill (create)
- `.claude/hooks/context-loader.py` WORK_TYPE_KEYWORDS — Add `gsd` work type with multi-step keywords
- `CLAUDE.md` — Append `## Development Methodology` section
- `.claude/settings.json` — No changes needed (context-loader already registered)

</code_context>

<deferred>
## Deferred Ideas

- GSD auto-workstream creation (listed in REQUIREMENTS.md as out of scope for v1)
- Dashboard GSD roadmap progress display (Phase 4)
- Workstream switcher in dashboard sidebar (GSD-05, GSD-06 — v2 requirements)

</deferred>

---

*Phase: 02-gsd-auto-activation*
*Context gathered: 2026-03-20*

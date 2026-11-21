---
description: EGM draft — turn concepts_brief.md into design_draft.md section-by-section with approval gates
---

Draft a technical design doc from the brainstorm brief. Follows `~/.config/opencode/skills/egm-draft/SKILL.md` (read it + `resources/execution_instructions.md`).

Input: $ARGUMENTS (optional context file, e.g. concepts_brief.md)

Workflow:
1. Read `concepts_brief.md` or provided context.
2. Write `design_draft.md` **section-by-section**, pausing after each section.
3. After each section: (a) chat summary with 2–3 key decisions + link to `design_draft.md`, (b) single-question approval gate (one question, one turn) — do not proceed without explicit go-ahead.
4. Artifact-first, Plain-English, critique-first, one question at a time. Design-only scope — no production code files, only markdown draft blocks or scratchpad outside project via `mktemp -d`.
5. Author decides architecture when multiple defensible answers exist — present ≤3 options with trade-offs, ask to choose (no default).

Version: `~/.config/opencode/egm/.egm-version`. Next: `/egm-review design_draft.md`.

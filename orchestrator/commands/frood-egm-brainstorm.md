---
description: EGM brainstorm — interactive ideation with fresh Goldfish lenses, outputs concepts_brief.md
---

Turn a half-baked idea into a structured hypothesis. Elephant holds context, Goldfish lenses stress-test.

Input: $ARGUMENTS (idea, e.g. "Add webhook delivery to this project")

Steps (read `~/.config/opencode/skills/egm-brainstorm/SKILL.md` first):

1. Multi-turn open-ended clarification — ask ONE question at a time, no `ask_question` multiple-choice, until problem/boundaries are clear. Do NOT spawn subagents until user confirms readiness after reviewing the anchored hypothesis.
2. Parallel Goldfish lenses (YAGNI, cost/quota, UX, migration, observability, tech-debt, inventive-catalyst) — each as a fresh `subagent({ agent: "explore", model: "commandcode/claude-haiku-5-5" })` (critic-tier model, pinned — never inherit; models per `rules/01-orchestrator-models.md`).
3. Artifact-first: write/update `concepts_brief.md` in workdir or `EGM artifact directory`, link path in chat, never dump large brief in chat.
4. Plain-English, critique-first, no glazing.

Version: `~/.config/opencode/egm/.egm-version`. Next: `/frood-egm-draft`.

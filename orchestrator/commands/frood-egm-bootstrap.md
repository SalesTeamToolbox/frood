---
description: EGM bootstrap — create/update documentation for an existing codebase
---

Create or update docs for an existing codebase via Goldfish. Read `~/.config/opencode/skills/egm-bootstrap/SKILL.md` first.

Input: $ARGUMENTS (optional target area)

Requires fresh subagents — if no subagent tool, stop. Pin the model on every spawn (never inherit the orchestrator): doc-writing workers `subagent({ agent: "general", model: "opencode-go/mimo-v2.6-flash" })`, read-only mapping `subagent({ agent: "scout" })`. Writes to workdir or EGM artifact directory. Follow the skill's worker-return schema in `references/worker-return.schema.json` and templates in `references/templates.md`.

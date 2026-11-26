---
description: EGM review-loop — configurable Goldfish auditors for any doc (reviewers + standards + GoldfishContext)
---

Generic antagonistic review loop. Use for READMEs, specs, plans, or focused audits.

Inputs: $ARGUMENTS should contain `TargetFile`, `SemanticTarget` (e.g. "Target the H4 block S1.12" or "full file"), `Reviewers`, `Standards`, `GoldfishContext`.

Read `~/.config/opencode/skills/egm-review-loop/SKILL.md` first.

Resolution:
- Reviewer shortnames → `~/.config/opencode/egm/agents/{name}.md` (design_critic, structural, style, implementation_readiness, codebase_details, comprehension, zoom_out)
- Standard shortnames → `~/.config/opencode/egm/resources/document_standards/{name}.md`
- If name contains `/`, treat as path and read directly.

Loop:
1. Intake — prompt for missing inputs one at a time.
2. For each iteration: re-resolve SemanticTarget line numbers (file may have been edited), launch reviewer swarm as fresh subagents with an **explicit cheap model — never inherit** (`subagent({ model: "opencode-go/deepseek-v4.1-flash", agent: "explore" })`; alt `opencode/mimo-v2.6-flash-free` $0 if Go quota is hot), collect reports, Elephant (you) resolves findings, apply approved fixes, re-loop.

Artifact-first, plain-English, one question per turn.

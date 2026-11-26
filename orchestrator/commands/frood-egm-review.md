---
description: EGM Goldfish review — 5-stage fresh-context review of a design doc (requires subagents)
---

Run the Elephant-Goldfish review on a design document. You must use fresh subagents (Goldfish) — never review in the same context.

Target: $ARGUMENTS (path to design doc, e.g. docs/designs/webhooks.md or plan file). If missing, ask for it and stop.

Steps (from `~/.config/opencode/skills/egm-review/SKILL.md` — read it first):

1. **Intake:** verify `TargetFile` exists; collect `GoldfishContext` (optional reading list). Linked files inside workdir that the doc references are auto-added; outside links need user approval.
2. **5 stages sequential, reviewers parallel within stage:** ZoomOut → Comprehension → DesignCritic → ZoomOut2 → ImplementationReadiness. Each reviewer is a fresh subagent with an **explicit cheap model — never inherit:** `subagent({ model: "opencode-go/deepseek-v4.1-flash", agent: "explore" })` (Go, ~43,330 req/5hr off-peak; alt `opencode/mimo-v2.6-flash-free` $0 if Go quota is hot) read-only (Read, Grep, Glob). OpenCode has no `omitClaudeMd`: tell each reviewer in its prompt to judge only the document and the listed context, not project instructions. Dropping the `model` arg is a bug — the reviewer would inherit the orchestrator (e.g. Opus-priced) and burn the wrong bucket. If no subagent tool, STOP — same-context review is not Goldfish.
3. **Artifact-first:** write each stage report to `EGM artifact directory` (default `.` or `EGM artifact directory: .opencode/plans` if set in CLAUDE.md) as markdown, then link the path in chat. Never dump large reports in chat.
4. **Resolve:** present findings, ask user which to address; on approval write fixes to the doc.

Resources: `~/.config/opencode/egm/resources/document_standards/*.md`, agents in `~/.config/opencode/egm/agents/*.md` (canonical) and `claude-agents/*.md` (adapters). Version: `~/.config/opencode/egm/.egm-version`.

This is Review only — it does NOT replace `verify-commit.sh` pinned tests or `train.sh` merge-verify-deploy.

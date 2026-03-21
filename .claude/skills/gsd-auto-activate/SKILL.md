---
name: gsd-auto-activate
description: Instructs Claude to use GSD methodology for multi-step tasks
always: true
---

# GSD Auto-Activation

When working in this project, use the GSD (Get Shit Done) structured workflow for any multi-step task. This is the default methodology -- not an optional enhancement.

## Activate GSD When You See

- Multiple files need to be created or modified
- The task has a clear sequence of steps ("first..., then..., finally...")
- Keywords like: build, create, implement, refactor, add feature, set up, migrate, convert, redesign, scaffold, plan, roadmap
- Framework scaffolding: Flask app, Django app, React app, FastAPI service
- The work would naturally break into phases

**Use `/gsd:new-project`** to start a full workstream, or **`/gsd:quick`** for a single self-contained task that still benefits from structured tracking.

## Skip GSD For

- Prompts under ~30 characters
- Questions beginning with "what", "how", "why", "explain", "show me"
- Single-file fixes where the target file is explicitly named ("fix the typo in X")
- Slash commands (/, /help, /gsd:...)
- Debugging a specific error message

## Mid-Task Pivot

If a task that started simple reveals unexpected complexity, suggest:
"This is getting more involved -- want me to switch to GSD for better tracking?"

## Already In GSD

If `.planning/active-workstream` exists and is non-empty, a GSD workstream is already active. Do not suggest starting a new one. Continue within the current workflow.

## Natural Language

When GSD activates, mention it naturally in your first response:
"I'll use GSD to break this into phases..." -- not a banner or announcement.

## Ambiguous Cases

When unsure whether a task needs GSD, default to suggesting it with an opt-out:
"This looks like a multi-step task. I'll use GSD to plan and execute. Say 'just do it' to skip."

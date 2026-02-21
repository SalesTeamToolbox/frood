---
name: skill-creator
description: Create new Agent42 skills with proper SKILL.md structure.
always: false
task_types: [coding, documentation]
---

# Skill Creator

Create new skills for Agent42 following the SKILL.md convention.

## Skill Structure

Every skill is a directory containing at minimum a `SKILL.md` file:

```
skills/workspace/my-skill/
├── SKILL.md           # Required: metadata + instructions
├── resources/         # Optional: reference files
│   └── examples.md
└── scripts/           # Optional: helper scripts
    └── setup.sh
```

## SKILL.md Format

```markdown
---
name: my-skill
description: One-line description of what this skill does.
always: false
task_types: [coding, research]
requirements_bins: [required_binary]
requirements_env: [REQUIRED_API_KEY]
---

# My Skill

Instructions for the agent when this skill is active.
Include specific commands, APIs, and guidelines.
```

## Frontmatter Fields

| Field | Type | Description |
|-------|------|-------------|
| name | string | Unique skill identifier |
| description | string | Short description for listings |
| always | bool | Load for every task (default: false) |
| task_types | list | Only load for these task types |
| requirements_bins | list | Required system binaries |
| requirements_env | list | Required environment variables |
| system_prompt | string | Override the default system prompt |

## Guidelines
- Keep the context window lean: put detailed reference material in resource files.
- Skills should be self-contained and not depend on other skills.
- Test skills by running a task that matches their task_types.

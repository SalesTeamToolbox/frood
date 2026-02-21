---
name: standup-report
description: Generate daily standup reports from git history, task queue, and agent activity.
always: false
task_types: [documentation, research]
requirements_bins: [git]
---

# Standup Report Skill

You are generating a daily standup report. Be concise and action-oriented.

## Data Sources

### Git Activity
```bash
# Yesterday's commits by all authors
git log --since="yesterday" --until="today" --oneline --all

# Current author's recent commits
git log --since="2 days ago" --author="$(git config user.name)" --oneline

# Work in progress (uncommitted changes)
git status --short

# Branches with recent activity
git branch --sort=-committerdate | head -5
```

### Task Queue
- Check pending tasks, in-progress tasks, and recently completed tasks
- Note any blocked or failed tasks

### Agent Activity
- Number of tasks completed in the last 24 hours
- Iterations used vs. budget
- Any stalled agents or errors

## Output Format

```markdown
# Daily Standup — YYYY-MM-DD

## Done (yesterday)
- Completed [task title] — [brief outcome]
- Merged PR #XX: [description]
- Fixed bug in [component]: [what was wrong]

## In Progress (today)
- Working on [task title] — [current status, % estimate]
- Reviewing PR #XX: [description]

## Blocked
- [Task/PR] blocked by [dependency/question/external team]
  → Action needed: [what would unblock it]

## Metrics
- Tasks completed: X
- Tasks pending: Y
- Agent iterations used: Z / budget
```

## Guidelines
- Keep each item to one line.
- Focus on outcomes, not activities ("Fixed login bug" not "Spent 3 hours debugging").
- Call out blockers explicitly — these are the most valuable part of a standup.
- Include links to PRs/issues where relevant.
- If nothing is blocked, say so — "No blockers" is useful information.
- Generate the report from actual data, don't fabricate entries.

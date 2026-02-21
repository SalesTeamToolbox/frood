---
name: github
description: GitHub operations using the gh CLI — PRs, issues, CI, and API queries.
always: false
task_types: [coding, debugging, refactoring]
requirements_bins: [gh]
---

# GitHub Skill

You have access to the `gh` CLI tool for GitHub operations.

## Common Operations

### Pull Requests
- List PRs: `gh pr list`
- Create PR: `gh pr create --title "title" --body "body"`
- View PR: `gh pr view <number>`
- Check PR status: `gh pr checks <number>`
- Merge PR: `gh pr merge <number> --squash`

### Issues
- List issues: `gh issue list`
- Create issue: `gh issue create --title "title" --body "body"`
- View issue: `gh issue view <number>`
- Close issue: `gh issue close <number>`

### CI/CD
- View workflow runs: `gh run list`
- View run details: `gh run view <id>`
- Watch a run: `gh run watch <id>`

### API
- Direct API calls: `gh api repos/{owner}/{repo}/...`
- GraphQL: `gh api graphql -f query='...'`

## Guidelines
- Always check CI status before merging PRs.
- Use `--squash` merge by default for cleaner history.
- Reference issue numbers in commit messages and PR descriptions.

---
name: release-notes
description: Generate clear, audience-appropriate release notes from git history and changelogs.
always: false
task_types: [documentation, coding]
requirements_bins: [git]
---

# Release Notes Skill

You are generating release notes. Be clear, accurate, and audience-aware.

## Process

### 1. Gather Changes
```bash
# Commits since last release
git log v1.x.x..HEAD --oneline --no-merges

# With full details
git log v1.x.x..HEAD --pretty=format:"%h %s (%an)" --no-merges

# Files changed
git diff --stat v1.x.x..HEAD

# List tags
git tag --sort=-version:refname | head -10
```

### 2. Categorize Changes

Group changes into these categories:
- **New Features** — new capabilities or functionality
- **Improvements** — enhancements to existing features
- **Bug Fixes** — corrections to incorrect behavior
- **Breaking Changes** — changes that require user action to upgrade
- **Security** — security fixes (mention CVE if applicable)
- **Deprecations** — features that will be removed in a future version
- **Internal** — refactoring, dependency updates, CI changes (optional, for detailed notes)

### 3. Write Notes

## Output Format

```markdown
# Release v1.x.x

**Date:** YYYY-MM-DD

## Highlights
One paragraph summarizing the most important changes for users.

## New Features
- **Feature name** — description of what it does and why it matters. (#PR)

## Improvements
- **Area** — what changed and the benefit. (#PR)

## Bug Fixes
- Fixed issue where [specific behavior]. (#PR, reported by @user)

## Breaking Changes
- `old_api()` has been renamed to `new_api()`. Update your code accordingly.

## Security
- Fixed [vulnerability type] in [component]. (CVE-xxxx-xxxxx)

## Upgrade Guide
Steps needed to migrate from the previous version.
```

## Guidelines
- Write for users, not developers — explain *what changed* and *why it matters*.
- Lead with the most impactful changes.
- Reference PR/issue numbers for traceability.
- For breaking changes, always include migration instructions.
- Keep each item to 1-2 sentences.
- Don't list every commit — group related changes into meaningful items.
- Use present tense: "Adds support for..." not "Added support for..."

---
name: git-workflow
description: Git branching strategies, PR workflow, merge conflict resolution, and history management.
always: false
task_types: [coding, refactoring]
requirements_bins: [git]
---

# Git Workflow

## Branching Strategies

### Trunk-Based Development
- Everyone commits to `main` (or short-lived feature branches that merge within 1-2 days).
- Best for small teams and continuous deployment.
- Use feature flags to hide incomplete work.
- Requires strong CI and automated tests.

### GitHub Flow
- Create a feature branch from `main`, work on it, open a PR, merge back to `main`.
- Simple and effective for most teams.
- Deploy from `main` after every merge.

### Git Flow
- Long-lived branches: `main`, `develop`, `feature/*`, `release/*`, `hotfix/*`.
- Best for projects with scheduled releases and multiple versions in production.
- More overhead; only use when the release model demands it.

**Recommendation**: Start with GitHub Flow. Only adopt Git Flow if you need to maintain multiple release versions simultaneously.

## Branch Naming Conventions

Use a consistent prefix to categorize branches:
- `feature/add-user-auth` -- new functionality.
- `fix/login-redirect-loop` -- bug fix.
- `chore/update-dependencies` -- maintenance.
- `docs/api-reference` -- documentation.
- Include a ticket number when applicable: `feature/PROJ-123-add-user-auth`.

## Pull Request Best Practices

1. **Keep PRs small and focused**: One logical change per PR. Aim for under 400 lines changed.
2. **Write a clear description**: Explain what changed, why, and how to test it.
3. **Use a PR template** with sections for Summary, Test Plan, and Screenshots (if UI changes).
4. **Request specific reviewers** who have context on the affected code.
5. **Respond to all review comments** before merging, even if just to acknowledge.
6. **Use draft PRs** for work-in-progress to get early feedback.
7. **Squash commits on merge** to keep the main branch history clean, or use merge commits if you want to preserve the full history.

## Commit Message Conventions (Conventional Commits)

Format: `<type>(<scope>): <description>`

Types:
- `feat`: New feature.
- `fix`: Bug fix.
- `docs`: Documentation only.
- `style`: Formatting, no code change.
- `refactor`: Code change that neither fixes a bug nor adds a feature.
- `test`: Adding or updating tests.
- `chore`: Maintenance tasks (dependencies, CI config).

Examples:
```
feat(auth): add OAuth2 login with Google
fix(api): return 404 instead of 500 for missing resources
chore(deps): update axios to 1.6.0
```

## Merge Conflict Resolution

1. Fetch the latest changes: `git fetch origin`.
2. Rebase your branch onto the target: `git rebase origin/main`.
3. When conflicts appear, open the conflicting files and resolve manually.
4. Stage resolved files: `git add <file>`.
5. Continue the rebase: `git rebase --continue`.
6. If the rebase becomes too complicated, abort and try a merge instead: `git rebase --abort && git merge origin/main`.
7. Always run tests after resolving conflicts to make sure nothing broke.

## Interactive Rebase

Use `git rebase -i HEAD~<n>` to clean up commit history before merging:
- **squash**: Combine multiple commits into one.
- **reword**: Change a commit message.
- **drop**: Remove a commit entirely.
- **reorder**: Rearrange commits for logical grouping.

Only rebase commits that have not been pushed to a shared branch. Rebasing published history causes problems for other contributors.

## Git Bisect for Debugging

Find the commit that introduced a bug:

```bash
git bisect start
git bisect bad              # current commit is broken
git bisect good <commit>    # this older commit was working
# Git checks out a middle commit. Test it, then:
git bisect good   # or
git bisect bad
# Repeat until Git identifies the first bad commit.
git bisect reset            # return to your original branch
```

Automate with a test script: `git bisect run ./test-script.sh` (exit 0 = good, exit 1 = bad).

## Useful Commands

- `git log --oneline --graph --all` -- visualize branch history.
- `git stash` / `git stash pop` -- temporarily shelve changes.
- `git cherry-pick <commit>` -- apply a specific commit to the current branch.
- `git reflog` -- recover lost commits or undo mistakes.
- `git blame <file>` -- see who last modified each line.

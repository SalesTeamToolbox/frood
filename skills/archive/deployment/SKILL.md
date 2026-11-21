---
name: deployment
description: Deploy applications safely with pre-flight checks, rollback plans, and verification.
always: false
task_types: [coding]
requirements_bins: [git]
---

# Deployment Skill

You are deploying code changes. Safety and reversibility are paramount.

## Pre-Deployment Checklist

1. **All tests pass** — run the full test suite, not just affected tests
2. **Linter clean** — no errors (warnings are acceptable)
3. **Changes committed** — no uncommitted work in the deploy branch
4. **Branch up to date** — rebased or merged with the target branch
5. **Config reviewed** — environment variables, feature flags, secrets are correct
6. **Database migrations** — reviewed for backwards compatibility
7. **Dependencies locked** — lockfile matches, no floating versions

## Deployment Steps

### Git-based Deploy (PR merge)
```bash
# Ensure clean state
git status
git diff --stat origin/main...HEAD

# Run pre-merge checks
python -m pytest -v
ruff check .

# Create PR (if not exists)
gh pr create --title "Deploy: feature description" --body "..."

# After approval, merge
gh pr merge <number> --squash
```

### Direct Deploy (for simple setups)
```bash
# Tag the release
git tag -a v1.x.x -m "Release: description"
git push origin v1.x.x

# Deploy command varies by platform
# Heroku: git push heroku main
# Vercel: vercel --prod
# Docker: docker build && docker push
```

## Post-Deployment Verification

1. **Health check** — hit the /health endpoint, verify 200 response
2. **Smoke test** — manually verify the core user flow works
3. **Logs** — check for errors or unexpected warnings in the first 5 minutes
4. **Metrics** — verify error rate and latency haven't spiked

## Rollback Plan

If something goes wrong:
```bash
# Revert the merge commit
git revert <merge-commit-sha>
git push origin main

# Or deploy the previous known-good tag
git checkout v1.x.x-previous
```

## Guidelines
- Never deploy on Friday afternoons unless it's an emergency hotfix.
- Deploy small, incremental changes — not large batches.
- If a deployment fails, roll back first, investigate second.
- Always have a rollback plan before deploying.
- Communicate deployments to the team (Slack, standup notes).

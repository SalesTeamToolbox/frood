---
name: deploy
description: Full deployment pipeline — audit changes, push dev, merge to main, deploy to production via SSH, verify service health
disable-model-invocation: true
---

# /deploy

Safe, repeatable deployment pipeline for Agent42. Handles the full workflow:
dev push → main merge → production deploy → health verification.

## Pre-flight Checks (MANDATORY)

Before ANY git operations, run these checks and STOP if any fail:

### 1. Clean Working Tree

```bash
git status --short
```

**If unstaged/staged changes exist:** Ask the user:
> "You have uncommitted changes in [list files]. Would you like to commit them first, or stash them for the deploy?"

Do NOT silently stash or proceed with dirty working tree. The user must explicitly choose.

### 2. Commits Ahead of Remote

```bash
git rev-list --count origin/dev..HEAD
```

**If 0 commits ahead:** Nothing to deploy. Tell the user and stop.

### 3. Test Suite

```bash
python -m pytest tests/ -x -q
```

**If failures:** Report them. Ask: "Tests have failures — deploy anyway?" Only known pre-existing failures (like `test_auth_flow.py:156`) can be safely ignored. New failures should block deployment.

### 4. Multi-Workstream Audit (if 20+ commits ahead)

When there are many accumulated commits, group them by workstream and verify each is in a complete state:

```bash
git log --oneline origin/dev..HEAD
```

For each workstream prefix in commit messages (e.g., `[custom-claude-code-ui]`, `[per-project-task-memories]`):
- Check that the latest phase has a SUMMARY.md (plan complete)
- Check that the phase has a VERIFICATION.md with `status: passed`
- Flag any workstream with incomplete plans

Present a summary table:

| Workstream | Commits | Latest Phase | Status |
|---|---|---|---|
| workstream-name | N | Phase X | Complete/Incomplete |

**If any workstream is incomplete:** Warn the user and ask whether to proceed.

## Deployment Steps

Only proceed after all pre-flight checks pass (or user explicitly approves warnings).

### Step 1: Push dev

```bash
git push origin dev
```

### Step 2: Merge to main

```bash
git checkout main
git merge dev
git push origin main
git checkout dev
```

### Step 3: Deploy to production

```bash
ssh agent42-prod "cd ~/agent42 && git pull origin main && sudo systemctl restart agent42"
```

### Step 4: Verify (wait 5 seconds for service startup)

```bash
ssh agent42-prod "sleep 5 && sudo systemctl is-active agent42 && curl -s -o /dev/null -w '%{http_code}' http://localhost:8000/api/health"
```

**Expected:** `active` + `200`

## Output

After deployment, show:

```
## Deployment Complete

| Step | Status |
|------|--------|
| Push dev | OK (N commits) |
| Merge to main | OK |
| Push main | OK |
| SSH deploy | OK |
| Service health | OK/FAIL |

**Commit range:** abc1234..def5678
**Files changed:** N files (+X/-Y lines)
```

If the health check fails, immediately run `/prod-check` for detailed diagnostics.

## What NOT to Do

- Do NOT proceed with dirty working tree without user consent
- Do NOT silently stash changes — ask the user
- Do NOT skip the test suite check
- Do NOT force-push anything
- Do NOT attempt to fix production issues automatically — report and recommend

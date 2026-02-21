---
name: ci-cd
description: Configure and manage CI/CD pipelines — GitHub Actions, testing, building, deploying.
always: false
task_types: [coding, deployment]
---

# CI/CD Pipelines

## GitHub Actions Workflow Structure

Workflow files live in `.github/workflows/` and use YAML syntax:

```yaml
name: CI
on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

jobs:
  build:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: '20'
          cache: 'npm'
      - run: npm ci
      - run: npm test
      - run: npm run build
```

## Common Pipeline Stages

### 1. Lint
Run static analysis early to catch formatting and style issues fast:
- **Python**: `ruff check .` or `flake8`, `black --check .`, `mypy .`
- **JavaScript/TypeScript**: `eslint .`, `prettier --check .`
- Fail the pipeline on lint errors. Do not allow exceptions.

### 2. Test
- Run the full test suite. Use `--coverage` flags to generate coverage reports.
- Upload coverage to a service like Codecov or Coveralls for tracking over time.
- Run unit tests first (fast feedback), then integration tests, then end-to-end tests.

### 3. Build
- Compile, bundle, or package the application.
- Store build artifacts using `actions/upload-artifact@v4` for use in later jobs.
- Verify the build output (e.g., check bundle size, run smoke tests against the build).

### 4. Deploy
- Deploy only from the main branch after all checks pass.
- Use environment-specific jobs with GitHub Environments for approval gates.
- Never deploy directly from feature branches to production.

## Caching Strategies

Cache dependencies to speed up builds significantly:

```yaml
- uses: actions/cache@v4
  with:
    path: ~/.npm
    key: ${{ runner.os }}-npm-${{ hashFiles('**/package-lock.json') }}
    restore-keys: |
      ${{ runner.os }}-npm-
```

- Cache package manager directories (`~/.npm`, `~/.cache/pip`, `~/.cargo`).
- Use `hashFiles()` on lock files to bust the cache when dependencies change.
- Cache Docker layers with `docker/build-push-action` and GitHub Container Registry.

## Secrets Management

- Store secrets in **GitHub Actions Secrets** (Settings > Secrets and Variables > Actions).
- Reference in workflows with `${{ secrets.MY_SECRET }}`.
- Never print secrets to logs. Use `::add-mask::` to redact values if needed.
- Use OIDC tokens for cloud deployments (AWS, GCP, Azure) instead of long-lived credentials.
- Rotate secrets regularly and audit access.

## Matrix Builds

Test across multiple environments in parallel:

```yaml
strategy:
  matrix:
    node-version: [18, 20, 22]
    os: [ubuntu-latest, macos-latest]
  fail-fast: false
```

- Use `fail-fast: false` to see all failures, not just the first.
- Use `include` and `exclude` to fine-tune combinations.

## Deployment Strategies

| Strategy | Description | Risk | Rollback Speed |
|----------|-------------|------|----------------|
| **Blue/Green** | Run two identical environments; switch traffic at once | Low | Instant (switch back) |
| **Canary** | Route a small percentage of traffic to new version | Low | Fast (route back) |
| **Rolling** | Gradually replace instances one by one | Medium | Moderate |
| **Recreate** | Stop all old instances, start new ones | High (downtime) | Slow |

- Use blue/green or canary for critical production services.
- Rolling updates work well for Kubernetes deployments.
- Always have a rollback plan documented and tested.

## Status Checks and Branch Protection

- Require all CI checks to pass before merging PRs.
- Configure branch protection rules on `main`: require reviews, status checks, and up-to-date branches.
- Add status badges to your README:
  ```markdown
  ![CI](https://github.com/org/repo/actions/workflows/ci.yml/badge.svg)
  ```

## Tips for Fast Pipelines

- Run independent jobs in parallel (lint, test, and build can often run simultaneously).
- Use `concurrency` groups to cancel redundant runs when new commits are pushed.
- Split slow test suites across multiple runners with test sharding.
- Keep Docker images small: use multi-stage builds and alpine base images.

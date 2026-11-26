# Contributing to Frood

Thank you for your interest in contributing to Frood! This guide will walk you through the community PR pathway end-to-end.

## Quick Start: One-Command Proposal

```bash
# Propose a community PR with a test plan (required)
frood-learn <stream> --propose --test-plan "Run lint, test, build, and verify CI passes"

# Example:
frood-learn community-m5 --propose --test-plan "Run lint, test, build, and verify CI passes"
```

This creates a community PR proposal with your test plan and runs the learning review.

## Community PR Pathway (End-to-End)

```
┌─────────────┐     ┌──────────────────┐     ┌─────────────┐     ┌──────────┐
│  1. Propose │────▶│  2. Webhook      │────▶│  3. CI      │────▶│  4.      │
│  (--propose)│     │  (GitHub App)    │     │  (Lint/Test/│     │  Review  │
└─────────────┘     └──────────────────┘     │   Security/ │     └──────────┘
                                              │   Build)    │
                                              └─────────────┘
```

### Step 1: Propose Your Change

```bash
# Create a proposal with a test plan (required)
frood-learn <stream> --propose --test-plan "Run lint, test, build, and verify CI passes"
```

This creates a proposal file at `.github/community-pr-proposal.json` with your test plan.

### Step 2: Webhook & CI

1. Your proposal triggers the GitHub App webhook
2. Webhook verifies signature (GitHub App only — PATs rejected)
3. CI workflow dispatches: `.github/workflows/community-pr.yml`
4. CI runs: **lint → test → security scan → build**

### Step 3: Review & Credit

- Reviewers see your test plan and attribution
- First-time contributors are flagged and acknowledged
- Changelog credits you: `- <change> (@your-handle, #PR)`

## Writing a Good Test Plan

A good test plan answers: **What will you run to verify your change?**

```bash
# Good (specific, runnable):
frood-learn community-m5 --propose --test-plan "Run lint (ruff), test (pytest), build (pyright), verify CI passes"

# Bad (vague):
frood-learn community-m5 --propose --test-plan "test it works"
```

**Minimum 20 characters required.** Be specific about what commands you'll run.

## Community PR Checklist

Before submitting, ensure your PR:

- [ ] Test plan is specific and runnable
- [ ] Affected files are listed in the proposal
- [ ] Suggested fix addresses the declared symptom
- [ ] Changelog entry credits you (`- <change> (@handle, #PR)`)
- [ ] CI passes (lint, test, security, build)
- [ ] Docs updated if user-facing change

## Onboarding for First-Time Contributors

1. **Fork the repo** → `git clone <your-fork>`
2. **Install deps** → `pip install -e .[dev]`
3. **Run tests** → `pytest tests/`
4. **Propose your change** → `frood-learn <stream> --propose --test-plan "..."`
4. **Open PR** via GitHub App (no PATs needed)
5. **Wait for CI** → lint, test, security, build
5. **Address review feedback**
6. **Merge** → changelog credits you automatically

## Need Help?

- **Documentation**: `frood-learn --help`
- **Phase 1 (foundations)**: `frood-learn <stream> --phase 1`
- **Phase 2 (delivery)**: `frood-learn <stream> --phase 2`
- **Phase 3 (community)**: `frood-learn <stream> --phase 3`
- **Propose a PR**: `frood-learn <stream> --propose --test-plan "..."`

## Community Standards

- **Be respectful** — we're all here to build something great
- **Test your changes** — the test plan isn't optional
- **Credit others** — cite related work and prior art
- **Keep it focused** — one logical change per PR

---

*Questions? Open an issue or ask in the community channel. We're happy to help you make your first contribution!*

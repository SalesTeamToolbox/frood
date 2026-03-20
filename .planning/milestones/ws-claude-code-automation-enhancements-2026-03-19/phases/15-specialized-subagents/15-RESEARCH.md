# Phase 15 Research: Specialized Subagents

## Domain Analysis

Phase 15 creates 4 Claude Code agent definition files (`.claude/agents/*.md`) — instruction-only markdown that Claude Code reads when the agent is dispatched on demand. No Python code is written.

## Existing Agent Pattern

Two agents already exist and establish the format:

### security-reviewer.md (3.1 KB, 69 lines)
```
# Security Reviewer Agent
## Purpose — one paragraph
## Context — project-specific security context
## Security Layers to Verify — numbered list of 8 layers
## Review Checklist — 7 categories, each with 3-4 sub-checks
## Output Format — PASS/WARN/FAIL with file:line references
```

### performance-auditor.md (2.0 KB, 51 lines)
```
# Performance Auditor Agent
## Purpose — one paragraph
## Focus Areas — 6 numbered categories with sub-bullets
## Output Format — Severity/Location/Issue/Fix structure
```

**Pattern:** Title + Purpose + Domain Context + Detailed Checklist + Output Format.
No frontmatter, no YAML. Plain markdown. Focus on actionable instructions with project-specific file paths and module references.

## Agent Requirements

### AGENT-01: Test Coverage Auditor
**Goal:** Analyze all untested modules, rank by security risk, change frequency, complexity.

**Key codebase facts:**
- 77 test files in `tests/`
- 32 modules in `core/`, 2 in `providers/`, tools in `tools/`
- Naming convention: `tests/test_<module>.py` maps to `<dir>/<module>.py`
- Security-critical: sandbox.py, command_filter.py, url_policy.py, encryption.py, device_auth.py
- `git log --format='' --name-only` gives change frequency
- Complexity heuristic: symbol count from jcodemunch or line count

**What the agent needs to do:**
1. List all source modules (core/, tools/, providers/, agents/, memory/, dashboard/)
2. List all test files in tests/
3. Find modules without corresponding test files
4. Rank by: security criticality (hardcoded list) > change frequency (git log) > complexity (line count)
5. Output prioritized table

### AGENT-02: Dependency Health
**Goal:** Check OpenRouter model availability, pip package versions, flag stale entries.

**Key codebase facts:**
- `providers/registry.py` contains `MODELS` dict and `PROVIDERS` dict
- `requirements.txt` has pinned pip deps
- OpenRouter API: `GET https://openrouter.ai/api/v1/models` returns available models
- PyPI API: `GET https://pypi.org/pypi/<package>/json` returns latest version
- Also check fallback model lists in `model_router.py`

**What the agent needs to do:**
1. Read MODELS dict from registry.py
2. Fetch OpenRouter model list, cross-reference, flag dead/renamed models
3. Read requirements.txt, check each package against PyPI for newer versions
4. Report: stale models, outdated deps, dead fallbacks

### AGENT-03: Migration Impact
**Goal:** Trace all usages of a package or API and flag breaking incompatibilities.

**Key codebase facts:**
- All imports are in Python files across core/, tools/, providers/, agents/, memory/, dashboard/
- Agent takes a package name or API change description as input
- Uses grep/search to find all import sites and usage patterns
- Cross-references with changelog or migration guide

**What the agent needs to do:**
1. Accept package name or API change as parameter
2. Search all imports of that package across codebase
3. Find all usage sites (function calls, class instantiation)
4. Compare against breaking changes (from docs/changelog)
5. Report each incompatibility with file:line

### AGENT-04: Deploy Verifier
**Goal:** Pre-deploy validation — imports, env vars, method signatures, git status.

**Key codebase facts:**
- `core/config.py` has Settings with all env vars (os.getenv calls)
- `.env.example` documents expected env vars
- Cross-module calls: server.py imports from core/, tools/, agents/
- `agent42.py` is the entry point — imports everything
- `git status` shows untracked files that might be required

**What the agent needs to do:**
1. Run `python -c "import agent42"` to verify imports resolve
2. Compare `.env.example` vars against Settings.from_env() getenv calls
3. Check for method calls that reference renamed/removed methods (grep for known patterns)
4. Run `git status` and flag untracked .py files that are imported elsewhere
5. Report: import errors, missing env vars, signature mismatches, untracked required files

## Plan Structure

All 4 agents are independent (no dependencies between them). They all follow the same pattern (markdown files in `.claude/agents/`). A single plan with 4 tasks is appropriate:

- Task 1: Create test-coverage-auditor.md (AGENT-01)
- Task 2: Create dependency-health.md (AGENT-02)
- Task 3: Create migration-impact.md (AGENT-03)
- Task 4: Create deploy-verifier.md (AGENT-04)

Each task creates one file, commits atomically.

## Risks

- **None significant** — these are instruction-only markdown files with no runtime impact
- Agent definitions reference specific file paths that may change — but that's inherent to any codebase documentation

---
*Researched: 2026-03-06*

---
name: code-review
description: Systematic code review with structured feedback on correctness, security, style, and tests.
always: false
task_types: [coding, debugging, refactoring]
---

# Code Review Skill

You are performing a code review. Be thorough, constructive, and specific.

## Review Checklist

### 1. Correctness
- Does the code do what the task/PR description says?
- Are edge cases handled (empty inputs, nulls, large datasets, concurrency)?
- Are return types and error codes correct?

### 2. Security
- No SQL injection, XSS, command injection, or path traversal
- Secrets are not hardcoded or logged
- User input is validated and sanitized at boundaries
- Authentication and authorization checks are in place
- No SSRF vulnerabilities in URL handling

### 3. Tests
- Are new/changed code paths covered by tests?
- Do tests check edge cases and error paths, not just the happy path?
- Are tests deterministic (no flaky timing, random, or network dependencies)?
- Is the test-to-code ratio reasonable?

### 4. Style & Consistency
- Follows the project's existing conventions (naming, formatting, structure)
- No unnecessary complexity or premature abstraction
- Functions are focused and reasonably sized
- Comments explain *why*, not *what*

### 5. Performance
- No obvious N+1 queries or unnecessary loops
- Large data sets are handled with streaming/pagination
- No memory leaks (unclosed resources, growing caches)

## Output Format

Structure your review as:

```
## Summary
One-line verdict: APPROVE / REQUEST CHANGES / COMMENT

## Findings

### [severity] category: title
**File:** path/to/file.py:line
**Description:** What the issue is and why it matters.
**Suggestion:** How to fix it (with code if helpful).
```

Severity levels: `critical` (must fix), `major` (should fix), `minor` (nice to fix), `nit` (style only).

## Guidelines
- Start with what's good — acknowledge solid work before listing issues.
- Be specific: reference exact lines, not vague generalizations.
- Propose solutions, don't just point out problems.
- Distinguish between blocking issues and suggestions.
- If the code is fine, say so — don't manufacture issues to seem thorough.

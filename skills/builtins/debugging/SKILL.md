---
name: debugging
description: Systematic debugging — reproduce, isolate, root-cause, fix, verify.
always: false
task_types: [debugging, coding]
---

# Debugging Skill

Apply a systematic methodology to find and fix bugs efficiently instead of guessing.

## Debugging Methodology

Follow these five steps in order. Do not skip ahead.

### 1. Reproduce

- Get a **reliable, minimal reproduction** of the bug.
- Record the exact input, environment, and steps that trigger it.
- If the bug is intermittent, identify conditions that increase its frequency (concurrency, load, timing).
- Write the reproduction as a failing test if possible.

### 2. Isolate

- **Narrow the scope.** Use binary search on the codebase or timeline:
  - Comment out or bypass sections to find which module is responsible.
  - Use `git bisect` to find the exact commit that introduced the bug.
- Eliminate variables: use hardcoded inputs, mock dependencies, disable caching.
- Reduce the reproduction to the smallest possible case.

### 3. Root Cause

- Ask **"why?" five times** (the Five Whys technique) to drill past symptoms.
- Read the code carefully around the isolated area. Do not assume — verify.
- Form a hypothesis, then design an experiment that could disprove it.
- Common root causes: incorrect assumptions about input, unhandled edge cases, stale state, wrong operator, missing synchronization.

### 4. Fix

- Write the **smallest change** that addresses the root cause, not just the symptom.
- Ensure the failing test from step 1 now passes.
- Check for the same bug pattern elsewhere in the codebase.
- Avoid band-aid fixes. If the root cause is a design flaw, refactor.

### 5. Verify

- Run the full test suite. Confirm no regressions.
- Test edge cases adjacent to the original bug.
- If applicable, verify in a staging or production-like environment.
- Add the reproduction as a permanent regression test.

## Debugging Tools

| Tool | Use Case |
|---|---|
| **Debugger** (breakpoints, step-through) | Inspect state at specific execution points |
| **Logging / print statements** | Trace execution flow and variable values over time |
| **git bisect** | Find the commit that introduced a regression |
| **git diff / git log** | Review recent changes to the affected area |
| **Stack traces** | Identify the call chain leading to an error |
| **Profiler** | Detect performance bugs — hotspots, memory leaks |
| **Linter / static analysis** | Catch type errors, unused variables, unreachable code |
| **Network inspector** | Debug HTTP requests, response codes, payloads |

## Common Bug Patterns

- **Off-by-one:** Loop boundaries, array indexing, string slicing, fence-post errors. Check `<` vs `<=`, `0` vs `1` start indices.
- **Race condition:** Shared mutable state accessed by concurrent threads/processes without synchronization. Look for missing locks, non-atomic operations, and ordering assumptions.
- **Null / undefined reference:** Accessing a property or method on a value that is null, None, or undefined. Check optional chaining, default values, and initialization order.
- **Resource leak:** Opened files, connections, or handles not closed on error paths. Look for missing `finally` blocks, context managers, or `defer` statements.
- **Type coercion:** Implicit conversions causing unexpected behavior (e.g., string concatenation vs. addition, truthy/falsy comparisons).
- **Stale cache / state:** Cached values not invalidated when underlying data changes.
- **Incorrect error handling:** Swallowed exceptions, overly broad catch blocks, or missing error propagation.

## Output Format — Root Cause Analysis

When reporting a resolved bug, use this structure:

```
**Symptom:** [What the user or test observed]
**Reproduction:** [Minimal steps to trigger the bug]
**Root Cause:** [The actual defect in the code, with file and line reference]
**Fix:** [Description of the change made]
**Verification:** [Tests added or run to confirm the fix]
**Prevention:** [How to prevent similar bugs — e.g., add linting rule, type check, test pattern]
```

## Guidelines

- Never guess at a fix without understanding the root cause first.
- Prefer adding a regression test over manual verification.
- If debugging takes more than 30 minutes without progress, change your approach: explain the problem to someone (rubber duck), take a break, or re-read the code from scratch.
- Document the root cause in commit messages and issue trackers for future reference.

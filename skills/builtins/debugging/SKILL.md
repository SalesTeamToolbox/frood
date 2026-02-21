---
name: debugging
description: Systematic debugging — reproduce, isolate, root-cause, fix, verify.
always: false
task_types: [debugging, coding]
---

# Debugging Skill

Apply a systematic methodology to find and fix bugs. Never guess — gather evidence first.

## Debugging Methodology

### 1. Reproduce
- Get a **reliable, minimal reproduction** of the bug.
- Record exact input, environment, and steps. Write it as a failing test if possible.

### 2. Isolate
- **Narrow the scope** using binary search: comment out sections or use `git bisect` to find the responsible commit.
- Eliminate variables: hardcode inputs, mock dependencies, disable caching.

### 3. Root Cause
- Ask **"why?" five times** to drill past symptoms to the actual defect.
- Form a hypothesis, then design an experiment that could disprove it.

### 4. Fix
- Write the **smallest change** that addresses the root cause, not just the symptom.
- Check for the same bug pattern elsewhere in the codebase.

### 5. Verify
- Run the full test suite. Confirm no regressions.
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

## Common Bug Patterns

- **Off-by-one:** Loop boundaries, array indexing, fence-post errors. Check `<` vs `<=`, `0` vs `1` starts.
- **Race condition:** Shared mutable state without synchronization. Look for missing locks and ordering assumptions.
- **Null / undefined reference:** Accessing a property on null/None/undefined. Check initialization order and defaults.
- **Resource leak:** Opened files or connections not closed on error paths. Look for missing `finally` or context managers.
- **Type coercion:** Implicit conversions causing unexpected behavior (string concat vs. addition, truthy/falsy).
- **Stale cache / state:** Cached values not invalidated when underlying data changes.
- **Swallowed exceptions:** Overly broad catch blocks hiding the real error.

## Output Format — Root Cause Analysis

```
**Symptom:** [What the user or test observed]
**Reproduction:** [Minimal steps to trigger the bug]
**Root Cause:** [The actual defect, with file and line reference]
**Fix:** [Description of the change made]
**Verification:** [Tests added or run to confirm the fix]
**Prevention:** [How to prevent similar bugs in the future]
```

## Guidelines

- Never guess at a fix without understanding the root cause first.
- Prefer adding a regression test over manual verification.
- If stuck for 30+ minutes, change approach: rubber duck, re-read code from scratch, or take a break.
- Document the root cause in commit messages for future reference.

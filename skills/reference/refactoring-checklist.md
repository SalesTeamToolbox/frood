# Refactoring Checklist — Condensed Reference

> Condensed from `refactoring` skill. Safe transformation patterns.

## Core Principle
> **Never change behavior.** Only structure. Tests must pass before, during, after.

## Common Patterns

| Pattern | When | Steps |
|---------|------|-------|
| **Extract Function** | Long function, duplicated logic | 1. Identify cohesive block 2. Extract with descriptive name 3. Replace calls 4. Test |
| **Extract Class** | Data + behavior clustered | 1. Group related fields/methods 2. Create class 3. Move methods 4. Update callers |
| **Rename** | Misleading name | 1. IDE rename (all refs) 2. Update tests 3. Verify no string refs broken |
| **Inline** | Trivial wrapper | 1. Replace call with body 2. Remove definition 3. Test |
| **Decompose Conditional** | Complex `if/else` | 1. Extract condition to `isX()` 2. Extract branches to `doX()`/`doY()` 3. Simplify |
| **Replace Magic Number** | Literal with meaning | 1. Create `const NAME = value` 2. Replace all occurrences 4. Test |
| **Introduce Parameter Object** | >3 params together | 1. Create data class 2. Update signature 3. Update callers |
| **Replace Temp with Query** | Temp var used once | 1. Extract to method 2. Replace temp with call 3. Test |

## Safety Checklist (Before Each Step)

- [ ] Tests pass (full suite)
- [ ] Change is **single** transformation
- [ ] No behavior change (verify with tests)
- [ ] Commit after each successful step

## Red Flags — Stop and Rethink

| Red Flag | Action |
|----------|--------|
| Tests fail after "safe" change | Revert, you changed behavior |
| Need to update many tests | Coupling too high, extract interface first |
| Can't name the new thing clearly | Don't extract yet; understand domain better |
| Function >50 lines after extract | Keep extracting; Single Responsibility |

## Output Format (for commit messages)

```
Refactor: [pattern name] — [what was changed]
Before: [structure description]
After: [structure description]
Tests: [all pass / added X tests]
```

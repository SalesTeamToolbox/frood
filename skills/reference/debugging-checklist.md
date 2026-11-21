# Debugging Checklist — Condensed Reference

> Condensed from `debugging` skill. Use as a mental checklist, not an MCP prompt.

## 5-Step Methodology

| Step | Action | Key Questions |
|------|--------|---------------|
| **1. Reproduce** | Get minimal reliable reproduction | Can I trigger it in <30s? Is there a failing test? |
| **2. Isolate** | Binary search the scope | `git bisect`? Comment out sections? Mock deps? Disable cache? |
| **3. Root Cause** | Ask "why?" 5× | Hypothesis formed? Experiment to disprove it? |
| **4. Fix** | Smallest change at root cause | Same pattern elsewhere? Symptom-only fix? |
| **5. Verify** | Full suite + regression test | No regressions? Reproduction added as test? |

## Common Patterns Quick-Ref

| Pattern | Signal | Fix Approach |
|---------|--------|--------------|
| Off-by-one | Loop boundary, array index | Check `<` vs `<=`, 0 vs 1 start |
| Race condition | Shared mutable state | Add locks, fix ordering |
| Null reference | Property on null/undefined | Check init order, add defaults |
| Resource leak | Unclosed file/connection | `finally` / context managers |
| Type coercion | String concat vs add, truthy | Explicit conversions |
| Stale cache | Cached value not invalidated | Invalidate on data change |
| Swallowed exception | Broad `catch` hiding error | Narrow catch, re-throw |

## Output Format (for commit messages)

```
Symptom: [What was observed]
Reproduction: [Minimal steps]
Root Cause: [Actual defect, file:line]
Fix: [Smallest change at root cause]
Verification: [Tests run/added]
Prevention: [How to prevent recurrence]
```

## Timebox Rule
> If stuck >30 min: change approach (rubber duck, re-read from scratch, break).

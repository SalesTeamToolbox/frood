---
name: refactoring
description: Improve code structure without changing behavior — extract, rename, simplify, decompose.
always: false
task_types: [refactoring, coding]
---

# Refactoring Skill

Refactor code to improve readability, maintainability, and design without altering external behavior.

## Safety Checklist

Before starting any refactoring session, confirm the following:

1. **Run existing tests** and confirm they pass. If no tests exist, write characterization tests first.
2. **Commit current state** to version control so you can revert if needed.
3. **Refactor in small steps.** Each step should be a single, well-defined transformation.
4. **Re-run tests after every step.** Never chain multiple refactors without verifying.
5. **Review the diff** before finalizing to ensure no accidental behavior changes.

## Refactoring Patterns

Apply the following patterns based on the code smell detected:

| Pattern | When to Use | Key Action |
|---|---|---|
| **Extract Method** | A block of code does one logical thing inside a larger function | Move the block into a named function; replace original with a call |
| **Rename Symbol** | A variable, function, or class name is unclear or misleading | Choose a name that reveals intent; update all references |
| **Move Method/Field** | A method uses data from another class more than its own | Relocate to the class it naturally belongs to |
| **Inline** | A function or variable adds indirection without clarity | Replace the call/reference with the body/value directly |
| **Decompose Conditional** | Complex `if/else` chains obscure logic | Extract each branch into a descriptively named function |
| **Replace Magic Values** | Literal numbers or strings appear without explanation | Define named constants that convey meaning |
| **Simplify Loop** | A loop does too many things or is deeply nested | Use map/filter/reduce, extract body, or split into passes |

## Code Smells to Watch For

- **Long methods** (>20 lines): break into smaller, focused functions.
- **Deep nesting** (>3 levels): use early returns, guard clauses, or extraction.
- **Duplicated code**: extract shared logic into a single function or module.
- **God classes**: split into smaller classes, each with a single responsibility.
- **Feature envy**: a method that accesses another object's data excessively belongs on that object.
- **Primitive obsession**: replace groups of related primitives with a dedicated type or data class.
- **Long parameter lists** (>3 params): introduce a parameter object or builder.

## Output Format

When presenting a refactoring, always show before and after with a brief rationale:

### Before

```python
def process(data):
    result = []
    for item in data:
        if item["type"] == "A" and item["status"] == "active" and item["value"] > 0:
            result.append(item["value"] * 1.1)
    return result
```

### After

```python
def process(data):
    return [apply_markup(item) for item in data if is_eligible(item)]

def is_eligible(item):
    return item["type"] == "A" and item["status"] == "active" and item["value"] > 0

def apply_markup(item):
    MARKUP_RATE = 1.1
    return item["value"] * MARKUP_RATE
```

**Rationale:** Extracted eligibility check and markup calculation into named functions, replacing the magic number with a constant. Each function now has a single responsibility.

## Guidelines

- Prefer pure functions: no side effects makes refactoring safer.
- When renaming, search the entire codebase for references including tests, configs, and docs.
- If a refactoring feels risky, break it into smaller sub-steps.
- Document *why* a refactoring was done in the commit message, not just *what* changed.

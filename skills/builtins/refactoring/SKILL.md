---
name: refactoring
description: Improve code structure without changing behavior — extract, rename, simplify, decompose.
always: false
task_types: [refactoring, coding]
---

# Refactoring Skill

Improve code readability, maintainability, and design without altering external behavior.

## Safety Checklist

1. **Run existing tests** and confirm they pass. If none exist, write characterization tests first.
2. **Commit current state** so you can revert if needed.
3. **Refactor in small steps.** One transformation at a time.
4. **Re-run tests after every step.** Never chain refactors without verifying.
5. **Review the diff** before finalizing to catch accidental behavior changes.

## Refactoring Patterns

| Pattern | When to Use | Key Action |
|---|---|---|
| **Extract Method** | A block does one logical thing inside a larger function | Move into a named function; replace with a call |
| **Rename Symbol** | A name is unclear or misleading | Choose a name that reveals intent; update all references |
| **Move Method/Field** | A method uses another class's data more than its own | Relocate to the class it belongs to |
| **Inline** | A function/variable adds indirection without clarity | Replace call with the body directly |
| **Decompose Conditional** | Complex `if/else` chains obscure logic | Extract each branch into a named function |
| **Replace Magic Values** | Literals appear without explanation | Define named constants |
| **Simplify Loop** | A loop does too many things or is deeply nested | Use map/filter/reduce or extract the body |

## Code Smells to Watch For

- **Long methods** (>20 lines): break into smaller, focused functions.
- **Deep nesting** (>3 levels): use early returns, guard clauses, or extraction.
- **Duplicated code**: extract shared logic into a single function or module.
- **God classes**: split into smaller classes with single responsibilities.
- **Feature envy**: move the method to the class whose data it uses most.
- **Primitive obsession**: replace related primitives with a dedicated type.
- **Long parameter lists** (>3 params): introduce a parameter object.

## Output Format

Always show before and after with a brief rationale:

**Before:**
```python
def process(data):
    result = []
    for item in data:
        if item["type"] == "A" and item["status"] == "active" and item["value"] > 0:
            result.append(item["value"] * 1.1)
    return result
```

**After:**
```python
def process(data):
    return [apply_markup(item) for item in data if is_eligible(item)]

def is_eligible(item):
    return item["type"] == "A" and item["status"] == "active" and item["value"] > 0

def apply_markup(item):
    MARKUP_RATE = 1.1
    return item["value"] * MARKUP_RATE
```

**Why:** Extracted eligibility check and markup into named functions, replaced magic number with a constant. Each function now has a single responsibility.

## Guidelines

- Prefer pure functions: no side effects makes refactoring safer.
- When renaming, search the entire codebase including tests, configs, and docs.
- If a refactoring feels risky, break it into smaller sub-steps.
- Document *why* in the commit message, not just *what* changed.

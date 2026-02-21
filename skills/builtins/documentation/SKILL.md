---
name: documentation
description: Write clear technical documentation — APIs, guides, READMEs, inline docs.
always: false
task_types: [documentation]
---

# Documentation Skill

Write documentation that helps people accomplish their goals quickly and accurately.

## Documentation Types

| Type | Purpose | Audience |
|---|---|---|
| **README** | First impression — what the project does, how to install and run it | New users and contributors |
| **API Reference** | Complete, precise description of every endpoint, function, or class | Developers integrating with the code |
| **Guide / Tutorial** | Step-by-step walkthrough of a specific task or workflow | Users learning a feature |
| **Architecture Doc** | High-level system design, component relationships, data flow | Team members and future maintainers |
| **Changelog** | Chronological record of notable changes per version | Users upgrading between versions |
| **Inline Docs** | Function-level explanations of purpose, parameters, and return values | Developers reading the source |

## Core Guidelines

1. **Audience first.** Identify who will read this and what they need. A README for end-users differs from an architecture doc for engineers.
2. **Examples over theory.** Show working code before explaining concepts. Readers can generalize from concrete examples faster than from abstract descriptions.
3. **Keep it scannable.** Use headings, bullet points, tables, and short paragraphs. Most readers scan before they read.
4. **Keep it accurate.** Outdated documentation is worse than no documentation. Tie doc updates to code changes in your workflow.
5. **Be concise.** Say what needs to be said and stop. Remove filler words, redundant explanations, and unnecessary qualifiers.

## Formatting Standards

- Use **Markdown** as the default format.
- Wrap code examples in fenced code blocks with language identifiers: ` ```python `, ` ```javascript `, etc.
- Use tables for structured comparisons (features, parameters, options).
- Use admonitions or bold prefixes for warnings and notes: **Note:**, **Warning:**, **Important:**.
- Keep line lengths reasonable for readability in plain text editors.

## Docstring Conventions

### Python — Google Style

```python
def calculate_total(items: list[dict], tax_rate: float = 0.0) -> float:
    """Calculate the total price for a list of items with optional tax.

    Iterates through the items, sums their prices, and applies the
    given tax rate to produce a final total.

    Args:
        items: A list of dicts, each containing a "price" key with a float value.
        tax_rate: Tax rate as a decimal (e.g., 0.08 for 8%). Defaults to 0.0.

    Returns:
        The total price including tax, rounded to two decimal places.

    Raises:
        ValueError: If any item is missing the "price" key.
        TypeError: If tax_rate is not a number.

    Example:
        >>> calculate_total([{"price": 10.0}, {"price": 20.0}], tax_rate=0.1)
        33.0
    """
```

### JavaScript — JSDoc

```javascript
/**
 * Calculate the total price for a list of items with optional tax.
 *
 * @param {Array<{price: number}>} items - List of item objects with a price property.
 * @param {number} [taxRate=0] - Tax rate as a decimal (e.g., 0.08 for 8%).
 * @returns {number} The total price including tax, rounded to two decimal places.
 * @throws {Error} If any item is missing the price property.
 *
 * @example
 * calculateTotal([{ price: 10 }, { price: 20 }], 0.1);
 * // => 33.0
 */
```

## README Template

A good README includes these sections in order:

1. **Project name and one-line description**
2. **Quick start** — install and run in under 60 seconds
3. **Features** — what it does (bullet list)
4. **Usage** — common use cases with code examples
5. **Configuration** — environment variables, config files, options
6. **Contributing** — how to set up dev environment, run tests, submit changes
7. **License**

## Changelog Format

Follow [Keep a Changelog](https://keepachangelog.com/) conventions:

- Group entries under: Added, Changed, Deprecated, Removed, Fixed, Security.
- List most recent version first.
- Include the release date in ISO format (YYYY-MM-DD).
- Link each version heading to the corresponding diff or tag.

## Guidelines

- Write documentation at the same time as the code, not after.
- Review docs for accuracy when modifying the code they describe.
- Prefer self-documenting code (clear names, simple structure) and reserve comments for "why" rather than "what."
- Test code examples in documentation to ensure they work.

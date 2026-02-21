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
| **README** | First impression — what it does, how to install, how to start | New users and contributors |
| **API Reference** | Complete description of every endpoint, function, or class | Developers integrating the code |
| **Guide / Tutorial** | Step-by-step walkthrough of a specific task | Users learning a feature |
| **Architecture Doc** | System design, component relationships, data flow | Team members and maintainers |
| **Changelog** | Notable changes per version | Users upgrading between versions |

## Core Guidelines

1. **Audience first.** A README for end-users reads differently from an architecture doc.
2. **Examples over theory.** Show working code before explaining concepts.
3. **Keep it scannable.** Headings, bullet points, tables, short paragraphs.
4. **Keep it accurate.** Outdated docs are worse than no docs. Update alongside code.
5. **Be concise.** Every sentence should earn its place.

## Formatting

- Use **Markdown**. Fenced code blocks with language identifiers (` ```python `).
- Tables for comparisons. **Note:** / **Warning:** prefixes for callouts.

### Python Docstrings — Google Style
```python
def calculate_total(items: list[dict], tax_rate: float = 0.0) -> float:
    """Calculate the total price for a list of items with optional tax.

    Args:
        items: A list of dicts, each with a "price" key (float).
        tax_rate: Tax rate as a decimal (e.g., 0.08). Defaults to 0.0.

    Returns:
        The total price including tax, rounded to two decimal places.

    Raises:
        ValueError: If any item is missing the "price" key.
    """
```

### JavaScript — JSDoc
```javascript
/**
 * Calculate the total price for a list of items with optional tax.
 *
 * @param {Array<{price: number}>} items - Item objects with a price property.
 * @param {number} [taxRate=0] - Tax rate as a decimal (e.g., 0.08).
 * @returns {number} Total price including tax, rounded to two decimal places.
 * @throws {Error} If any item is missing the price property.
 */
```

## README Template

1. **Project name and one-line description**
2. **Quick start** — install and run in under 60 seconds
3. **Features** — what it does (bullet list)
4. **Usage** — common use cases with code examples
5. **Configuration** — env vars, config files, options
6. **Contributing** — dev setup, tests, submitting changes
7. **License**

## Guidelines

- Write docs at the same time as the code, not after.
- Prefer self-documenting code; reserve comments for "why" not "what."
- Follow [Keep a Changelog](https://keepachangelog.com/): group under Added, Changed, Fixed, Removed.
- Test code examples in documentation to ensure they work.

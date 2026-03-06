---
name: add-pitfall
description: Auto-format and auto-number a new entry in the CLAUDE.md pitfalls table
disable-model-invocation: true
---

# /add-pitfall

Add a new entry to the Common Pitfalls table in `CLAUDE.md`, automatically detecting the next number and formatting the row to match the existing table structure.

## Usage

```
/add-pitfall [area] [pitfall description] [correct pattern]
```

If all three arguments are provided with the slash command, use them directly. If any are missing or unclear, ask the developer for:

- **Area** -- The category (e.g., Deploy, Auth, Dashboard, Config, Tools, Apps, Routing, Memory, Server, Security, Init, etc.)
- **Pitfall** -- What goes wrong, in one sentence
- **Correct Pattern** -- How to do it right, in one sentence

## Step 1: Read Current State

Read `CLAUDE.md` and find the Common Pitfalls table. Search for all lines matching the pattern `| NNN |` where NNN is a number (e.g., `| 81 |`, `| 116 |`). Extract the highest number found in the table.

The new entry number is: **highest number found + 1**.

Do NOT hardcode any number. Always detect the current highest dynamically by reading the file.

## Step 2: Format the Entry

Build the new table row as:

```
| {next_number} | {Area} | {Pitfall} | {Correct Pattern} |
```

Rules for the cell content:
- Keep each cell to one sentence for readability
- Wrap inline code references in backticks (e.g., `function_name()`, `module.py`)
- Avoid using pipe characters (`|`) inside cell text -- they break the table. Use commas, semicolons, or "or" instead.
- Match the style of existing entries (technical, concise, actionable)

## Step 3: Insert the Entry

Use the Edit tool to insert the new row at the END of the pitfall table, immediately after the last `| NNN | ... |` row.

The insertion point is BEFORE the blank line and `---` separator that follows the last table row. The structure looks like this:

```
| 116 | Server | `from starlette...` | Never import at... |
                                                              <-- INSERT HERE
---

## Extended Reference (loaded on-demand)
```

The new row must go directly after the last numbered row, maintaining the table structure. Do NOT insert after the `---` separator. Do NOT insert inside the "Extended Reference" section.

## Step 4: Verify

After inserting, read the modified section of `CLAUDE.md` (around the last few rows of the pitfall table) and confirm:

1. The new entry number is correct (previous highest + 1)
2. The row has exactly 4 pipe-separated columns: `| # | Area | Pitfall | Correct Pattern |`
3. The table still renders as valid markdown (no broken pipes, no misaligned columns)
4. The `---` separator and "Extended Reference" section below are undisturbed
5. No other rows in the table were modified or deleted

If any check fails, fix the issue before finishing.

## What NOT to Do

- Do NOT hardcode the next pitfall number -- always detect it dynamically from the file
- Do NOT modify any other section of `CLAUDE.md` (only insert one row in the pitfalls table)
- Do NOT delete or reorder existing pitfall entries
- Do NOT insert the new row after the `---` separator
- Do NOT create any Python files -- this is a pure instruction skill
- Do NOT modify `tests/conftest.py` or any test files
- Do NOT touch the archived pitfalls in `.claude/reference/pitfalls-archive.md`

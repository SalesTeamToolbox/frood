---
name: tool-creator
description: Create new tools at runtime when existing tools can't handle the task.
always: false
task_types: [coding, debugging, research, data_analysis, refactoring]
---

# Tool Creator

Create new executable tools at runtime using the `create_tool` tool. Use this when **no existing tool** can accomplish a required subtask.

## When to Create a Tool

1. **Check existing tools first.** Review the available tools before creating a new one.
2. **Create when there's a gap.** If the task requires a capability none of the current tools provide (e.g., a specialized parser, a custom calculation, a data transformer), create a tool for it.
3. **Don't duplicate.** Never create a tool that overlaps with an existing one.

## How to Create a Tool

Call the `create_tool` tool with:

| Parameter | Description |
|-----------|-------------|
| `tool_name` | Lowercase identifier (letters, digits, underscores). 3-50 chars. |
| `description` | Clear explanation of what the tool does — this is shown to you later. |
| `parameters` | JSON Schema object describing the tool's inputs. |
| `code` | Python code defining a `run(**kwargs) -> str` function. |

The tool will be registered as `dynamic_<tool_name>` and immediately available.

## Code Contract

Your code **must** define:

```python
def run(**kwargs) -> str:
    """Process inputs and return a string result."""
    # Your logic here
    return "result"
```

- The function receives the parameters defined in your schema as keyword arguments.
- It must return a **string**. Return structured data as JSON strings if needed.
- Use only the Python standard library — no external packages.
- Keep it focused: one tool, one job.

## Example

Creating a CSV-to-JSON converter tool:

```
tool_name: csv_to_json
description: Convert CSV text to a JSON array of objects.
parameters:
  type: object
  properties:
    csv_text:
      type: string
      description: Raw CSV content with headers in the first row.
  required: [csv_text]
code: |
  import csv
  import io
  import json

  def run(csv_text="", **kwargs):
      reader = csv.DictReader(io.StringIO(csv_text))
      rows = [row for row in reader]
      return json.dumps(rows, indent=2)
```

## Safety Constraints

- No `subprocess`, `os.system`, `eval`, `exec`, `socket`, or `ctypes`.
- No file operations outside the workspace.
- Code runs in an isolated subprocess with secrets stripped from the environment.
- Execution timeout: 30 seconds.
- Maximum 10 dynamic tools per session.

## Guidelines

- Prefer small, composable tools over large monolithic ones.
- Name tools descriptively: `parse_log_timestamp`, not `tool1`.
- Always include a `description` that future-you can understand.
- Test mentally: walk through the code with sample inputs before creating.

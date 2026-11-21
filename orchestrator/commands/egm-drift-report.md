---
description: EGM drift-report — compare docs/designs vs live code, report divergences
---

Detect where checked-in designs have diverged from code. Read `~/.config/opencode/skills/egm-drift-report/SKILL.md` first.

Input: $ARGUMENTS (directory of design docs, e.g. docs/designs/)

Steps:
1. List all files in the design directory.
2. For each doc: read intent + mentioned files/symbols, locate source via Grep/Glob, read current source, compare — report ONLY differences (missing features, incomplete models, shortcuts, architectural divergence). If no drift: "No drift detected."
3. Append to `{YYYY-MM-DD}_DRIFT_REPORT.md` in workdir (or EGM artifact directory).

Be rigorous — if doc names a field/file/symbol and code doesn't have it, report it. Read liberally, process sequentially to avoid tool buffer overflow.

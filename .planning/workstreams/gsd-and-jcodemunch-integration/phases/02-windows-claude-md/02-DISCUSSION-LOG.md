# Phase 2: Windows + CLAUDE.md - Discussion Log (Assumptions Mode)

> **Audit trail only.** Do not use as input to planning, research, or execution agents.
> Decisions captured in CONTEXT.md — this log preserves the analysis.

**Date:** 2026-03-24
**Phase:** 02-windows-claude-md
**Mode:** assumptions (--auto)
**Areas analyzed:** Windows Path/Venv Compatibility, CRLF Prevention, CLAUDE.md Template Generation, Invocation Command

## Assumptions Presented

### Windows Path and Venv Compatibility
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Platform detection via `case "$(uname -s)" in MINGW*|MSYS*` at setup.sh top level, setting VENV_ACTIVATE and PYTHON_CMD | Confident | setup.sh lines 66-67 (create-shortcut already has this); .venv/Scripts/python.exe confirmed on Windows filesystem |
| setup_helpers.py uses `sys.platform == "win32"` for .venv/Scripts vs .venv/bin selection | Confident | setup_helpers.py lines 216, 391 hardcode `.venv/bin/python`; no platform detection in file (grep confirmed) |
| Use `python` not `python3` on Windows (Git Bash doesn't ship python3) | Confident | Standard Git Bash behavior; existing .mcp.json uses `python.exe` path |

### CRLF Prevention
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Add .gitattributes with `*.sh text eol=lf` and `*.py text eol=lf` | Confident | No .gitattributes exists (glob confirmed); CLAUDE.md Common Gotchas documents CRLF as known issue |
| No runtime CRLF stripping — fix at git level | Confident | Runtime stripping doesn't protect Python shebangs or hook scripts |

### CLAUDE.md Template Generation Scope
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| Parameterized template (not verbatim CLAUDE.md copy) with hook protocol, memory, architecture, pitfalls | Likely | ROADMAP success criteria lines 42-43; existing CLAUDE_MD_TEMPLATE is memory-only (setup_helpers.py lines 80-117) |
| Template is project-aware (project name, repo ID, workstream injected) | Likely | ROADMAP success criterion line 43: "project-aware (references the correct project name, repo identifier, and active workstream)" |

### Invocation Command
| Assumption | Confidence | Evidence |
|------------|-----------|----------|
| setup.sh subcommand `generate-claude-md` (opt-in, not default flow) | Likely | Existing subcommand pattern (sync-auth, create-shortcut); SETUP-07 says "run a setup command" implying distinct action |
| Merge into existing CLAUDE.md if present, generate fresh if not | Likely | Idempotency pattern from Phase 1; overwriting would destroy user content |

## Corrections Made

No corrections — all assumptions confirmed (--auto mode).

## Auto-Resolved

- CLAUDE.md Template Scope (Likely): auto-selected parameterized template approach
- Invocation Command (Likely): auto-selected setup.sh subcommand approach
- Merge behavior (Likely): auto-selected merge-if-exists approach

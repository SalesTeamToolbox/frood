# CLAUDE.md — Agent42 Development Guide

## Quick Reference

```bash
source .venv/bin/activate        # Activate virtual environment
python agent42.py                # Start Agent42 (dashboard at http://localhost:8000)
python -m pytest tests/ -x -q    # Run tests (stop on first failure)
make lint                        # Run linter (ruff)
make format                      # Auto-format code (ruff)
make check                       # Run lint + tests together
```

## Key Rules

- **All I/O is async** — use `aiofiles`, `httpx`, `asyncio`. Never blocking I/O in tools.
- **Frozen config** — `Settings` dataclass in `core/config.py`. Add fields there + `from_env()` + `.env.example`.
- **Graceful degradation** — Redis, Qdrant, MCP are optional. Handle absence, never crash.
- **Sandbox always on** — validate paths via `sandbox.resolve_path()`. Never disable in prod.
- **New pitfalls** — add to `.claude/reference/pitfalls-archive.md` when you discover non-obvious issues.

## Codebase Navigation (jcodemunch)

Repo: `local/agent42` (197 files, 4700+ symbols). **Use jcodemunch before reading files:**

| Need | Tool |
|------|------|
| Module overview | `get_file_outline` |
| Find definitions | `search_symbols` |
| Directory structure | `get_file_tree` with `path_prefix` |
| Symbol source | `get_symbol` |
| Text search | `search_text` |

## Hooks

Automated hooks run in `.claude/`. Key behaviors:
- **UserPromptSubmit**: memory recall, learning injection, prompt accumulation
- **PreToolUse**: security gate blocks edits to sensitive files
- **PostToolUse**: auto-format (ruff), security monitoring, Qdrant sync, jcodemunch reindex
- **Stop**: session handoff, test validation, learning capture

Full details: `.claude/reference/hooks-reference.md`

## Security Requirements

1. **NEVER** disable sandbox in production (`SANDBOX_ENABLED=true`)
2. **ALWAYS** use bcrypt password hash (`DASHBOARD_PASSWORD_HASH`)
3. **ALWAYS** set `JWT_SECRET` to a persistent value
4. **NEVER** expose `DASHBOARD_HOST=0.0.0.0` without nginx/firewall
5. **ALWAYS** run with `COMMAND_FILTER_MODE=deny` or `allowlist`
6. **NEVER** log API keys, passwords, or tokens — even at DEBUG level
7. **ALWAYS** validate file paths through `sandbox.resolve_path()`

## Testing

```bash
python -m pytest tests/ -x -q              # Quick
python -m pytest tests/ -v                  # Verbose
python -m pytest tests/test_security.py -v  # Security suite
```

New modules need `tests/test_*.py`. Full standards: `.claude/reference/development-workflow.md`

## Reference Docs (on-demand)

- `hooks-reference.md` — Full hook table, protocol, architecture diagram
- `architecture-patterns.md` — Plugin architecture, tool/extension/skill patterns, MCP, security layers
- `development-workflow.md` — Pre/post coding checklists, test writing rules
- `pitfalls-archive.md` — All resolved pitfalls (1-124)
- `project-structure.md` — Complete directory tree
- `configuration.md` — All 80+ environment variables
- `new-components.md` — Procedures for adding tools, skills, providers
- `conventions.md` — Naming, commits, documentation maintenance
- `deployment.md` — Local, production, and Docker deployment
- `terminology.md` — Full glossary of 50 terms
- `stack-rewards.md` — Rewards/tier system stack research

<!-- GSD:project-start source:PROJECT.md -->
## Project

**Agent42**

An AI agent platform that operates across 9 LLM providers with tiered routing (L1 workhorse, L2 premium, free fallback), per-agent model configuration, and graceful degradation. Features intelligent memory (ONNX + Qdrant with auto-sync from Claude Code), task-aware learning (effectiveness tracking + proactive injection), and native desktop app experience (PWA + GSD auto-activation).

**Core Value:** Agent42 must always be able to run agents reliably, with tiered provider routing (L1 workhorse -> free fallback -> L2 premium) ensuring no single provider outage stops the platform.

### Constraints

- **API compatibility**: All providers use OpenAI Chat Completions compatible APIs
- **Tiered defaults**: L1 (StrongWall) when configured, free tier fallback, L2 premium opt-in
- **Graceful degradation**: Missing API keys never crash Agent42
- **Backward compatible**: Users without new API keys keep existing routing
<!-- GSD:project-end -->

<!-- GSD:stack-start source:research/STACK.md -->
## Technology Stack

Core stack: Python 3.11+, stdlib (`IntEnum`, `asyncio.Semaphore`, `dataclasses`), existing deps (`aiosqlite`, `aiofiles`, FastAPI).
<!-- GSD:stack-end -->

<!-- GSD:conventions-start source:CONVENTIONS.md -->
## Conventions

Conventions not yet established. Will populate as patterns emerge during development.
<!-- GSD:conventions-end -->

<!-- GSD:architecture-start source:ARCHITECTURE.md -->
## Architecture

Architecture not yet mapped. Follow existing patterns found in the codebase.
<!-- GSD:architecture-end -->

<!-- GSD:workflow-start source:GSD defaults -->
## GSD Workflow Enforcement

Before using Edit, Write, or other file-changing tools, start work through a GSD command so planning artifacts and execution context stay in sync.

Use these entry points:
- `/gsd:quick` for small fixes, doc updates, and ad-hoc tasks
- `/gsd:debug` for investigation and bug fixing
- `/gsd:execute-phase` for planned phase work

Do not make direct repo edits outside a GSD workflow unless the user explicitly asks to bypass it.
<!-- GSD:workflow-end -->

<!-- GSD:profile-start -->
## Developer Profile

> Profile not yet configured. Run `/gsd:profile-user` to generate your developer profile.
> This section is managed by `generate-claude-profile` -- do not edit manually.
<!-- GSD:profile-end -->

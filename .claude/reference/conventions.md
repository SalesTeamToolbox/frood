# Conventions

## Naming Conventions

| Type | Convention | Example |
|------|-----------|---------|
| Files | `snake_case.py` | `task_queue.py`, `model_router.py` |
| Classes | `PascalCase` | `TaskQueue`, `ModelRouter` |
| Tools | `PascalCase` + `Tool` suffix | `ShellTool`, `GitTool` |
| Skills | `kebab-case` directories | `code-review/`, `security-audit/` |
| Tests | `test_{module}.py` / `class TestClassName` | `test_sandbox.py` / `TestWorkspaceSandbox` |
| Config env vars | `UPPER_SNAKE_CASE` | `MAX_CONCURRENT_AGENTS` |
| Loggers | `"agent42.{module}"` namespace | `logging.getLogger("agent42.tools.shell")` |

## Commit Guidelines

Use conventional commit prefixes:

| Prefix | Use For |
|--------|---------|
| `feat:` | New feature or capability |
| `fix:` | Bug fix |
| `refactor:` | Code restructuring (no behavior change) |
| `test:` | Adding or updating tests |
| `docs:` | Documentation changes |
| `chore:` | Build process, dependencies, CI |
| `security:` | Security fix or hardening |

**Format:** `{prefix} Brief description of the change`

**Examples** (from actual project history):
```
feat: priority queue, Redis backend, and spending limit enforcement
fix: 7 bugs: 3 critical startup crashes, 4 major logic/security gaps
security: add 6-layer command filter with deny patterns
chore: add CI workflows for testing, linting, and security scanning
```

Include *what* and *why*, not just *what*.

## Documentation Maintenance

**AI Assistant Instructions:** When working on this codebase, proactively update
CLAUDE.md when:

1. **New errors are resolved** — Add to "Common Pitfalls" table
2. **New terminology is introduced** — Add to `.claude/reference/terminology.md`
3. **New tools are created** — Add to `.claude/reference/project-structure.md`
4. **New skills are added** — Note in the skills section
5. **New patterns are established** — Add to "Architecture Patterns" in CLAUDE.md
6. **Configuration changes** — Update `.claude/reference/configuration.md`
7. **README changes** — Update README.md when adding features, skills, tools, or providers

**When to update:**
- After successfully resolving a non-obvious error
- When discovering undocumented conventions
- After creating new tools, skills, or providers
- When server or deployment configuration changes

**Format:** Keep updates concise and consistent with existing table/list formats.

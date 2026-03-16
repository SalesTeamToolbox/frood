# GSD Feature Proposal: Workstream Namespacing

**Author:** Agent42 project
**Date:** 2026-03-02
**Status:** Design draft — for submission to GSD plugin

## Problem

GSD is a single-threaded pipeline. Every piece assumes one active milestone:

- `ROADMAP.md` — one flat phase list, one progress table
- `STATE.md` — one `Current Position`, one phase counter
- `REQUIREMENTS.md` — deleted and replaced at milestone boundary
- `gsd-tools.cjs` — all 11 lib modules resolve `cwd + '.planning/' + filename`
- 30+ workflow `.md` files — all reference singular `.planning/ROADMAP.md` etc.
- Phase numbering — global across `phases/`, two milestones would clash

**Real-world impact:** Users cannot work on a new feature while a milestone is executing in another terminal. Starting a new milestone overwrites ROADMAP.md and REQUIREMENTS.md, breaking the in-flight work.

## Proposed Solution: Workstream Directories

### Directory Structure

```
.planning/
  PROJECT.md              # SHARED — project identity, never overwritten
  config.json             # SHARED — workflow preferences (global)
  research/               # SHARED — project-level research
  milestones/             # Archive (existing, unchanged)
  codebase/               # Codebase maps (existing, unchanged)
  todos/                  # Todos (existing, unchanged)

  workstreams/
    default/              # The "unnamed" workstream (backward compat)
      ROADMAP.md
      REQUIREMENTS.md
      STATE.md
      config.json         # Optional per-workstream overrides
      phases/
        01-foundation-cerebras/
        02-groq-integration/
      research/            # Per-workstream research

    agent42-hooks/         # A parallel workstream
      ROADMAP.md
      REQUIREMENTS.md
      STATE.md
      phases/
        01-smart-hooks/
        02-parallel-testing/
      research/
```

### Backward Compatibility: "Flat Mode"

If `.planning/workstreams/` does NOT exist, everything works exactly as today — files live at `.planning/ROADMAP.md`, `.planning/STATE.md`, etc. This is "flat mode" and is the default.

The first time a user runs `/gsd:new-milestone` (or a new `/gsd:new-workstream` command) while a milestone is active, GSD offers to migrate:

```
You have an active milestone (v1.0 - Provider Expansion).
Starting a new workstream will reorganize .planning/:

  .planning/ROADMAP.md    → .planning/workstreams/provider-expansion/ROADMAP.md
  .planning/STATE.md      → .planning/workstreams/provider-expansion/STATE.md
  .planning/REQUIREMENTS.md → .planning/workstreams/provider-expansion/REQUIREMENTS.md
  .planning/phases/       → .planning/workstreams/provider-expansion/phases/

PROJECT.md, config.json, research/, todos/ stay where they are.

→ Migrate and create new workstream? (yes / no)
```

### Phase Numbering

Phase numbers are **per-workstream**, not global. Each workstream starts at Phase 1. The workstream name provides the namespace:

- `provider-expansion` Phase 3 = `.planning/workstreams/provider-expansion/phases/03-mistral/`
- `agent42-hooks` Phase 1 = `.planning/workstreams/agent42-hooks/phases/01-smart-hooks/`

Git commits include the workstream name: `docs(hooks/01): plan smart test validator`

## Implementation: gsd-tools.cjs Changes

### New CLI Flag: `--ws <name>`

```bash
# Explicit workstream
node gsd-tools.cjs init plan-phase 1 --ws agent42-hooks

# Default workstream (flat mode or "default" workstream)
node gsd-tools.cjs init plan-phase 1
```

### Core Path Resolution Refactor

**Current (72 call sites):**
```javascript
const statePath = path.join(cwd, '.planning', 'STATE.md');
```

**Proposed — introduce `resolvePlanningDir()` in core.cjs:**
```javascript
// core.cjs
function resolvePlanningDir(cwd, workstream = null) {
  const base = path.join(cwd, '.planning');

  // Flat mode: no workstreams/ directory exists
  if (!workstream && !fs.existsSync(path.join(base, 'workstreams'))) {
    return base;  // backward compat
  }

  // Workstream mode
  const ws = workstream || 'default';
  return path.join(base, 'workstreams', ws);
}

// New: shared path object builder
function buildPaths(cwd, workstream = null) {
  const wsDir = resolvePlanningDir(cwd, workstream);
  const baseDir = path.join(cwd, '.planning');
  return {
    // Per-workstream (scoped)
    roadmap:      path.join(wsDir, 'ROADMAP.md'),
    state:        path.join(wsDir, 'STATE.md'),
    requirements: path.join(wsDir, 'REQUIREMENTS.md'),
    phases:       path.join(wsDir, 'phases'),
    wsResearch:   path.join(wsDir, 'research'),
    wsConfig:     path.join(wsDir, 'config.json'),
    wsDir,

    // Shared (project-level, never scoped)
    project:      path.join(baseDir, 'PROJECT.md'),
    config:       path.join(baseDir, 'config.json'),
    milestones:   path.join(baseDir, 'milestones'),
    research:     path.join(baseDir, 'research'),
    codebase:     path.join(baseDir, 'codebase'),
    todos:        path.join(baseDir, 'todos'),
    baseDir,
  };
}
```

**Refactor pattern for every module:**
```javascript
// Before (state.cjs)
function cmdStateLoad(cwd, raw) {
  const statePath = path.join(cwd, '.planning', 'STATE.md');
  // ...
}

// After
function cmdStateLoad(cwd, raw, paths) {
  const statePath = paths.state;
  // ...
}
```

### CLI Dispatch Change

```javascript
// gsd-tools.cjs main()
const ws = extractFlag(args, '--ws');       // new
const cwd = extractFlag(args, '--cwd') || process.cwd();
const paths = core.buildPaths(cwd, ws);     // new

// Pass paths to every command
switch(command) {
  case 'state': return state.cmdStateLoad(cwd, raw, paths);
  // ...
}
```

### Impact by Module

| Module | `.planning/` refs | Change needed |
|--------|-------------------|---------------|
| `init.cjs` | 68 | Return paths from `buildPaths()` instead of string literals |
| `phase.cjs` | 19 | Use `paths.phases` instead of `path.join(cwd, '.planning', 'phases')` |
| `state.cjs` | 15 | Use `paths.state` |
| `commands.cjs` | 11 | Use `paths.*` for todos, commits |
| `milestone.cjs` | 9 | Use `paths.milestones`, `paths.roadmap` |
| `core.cjs` | 9 | Add `buildPaths()`, refactor `loadConfig()` |
| `verify.cjs` | 6 | Use `paths.*` for health checks |
| `config.cjs` | 5 | Use `paths.config` (shared) or `paths.wsConfig` (per-ws) |
| `roadmap.cjs` | 4 | Use `paths.roadmap` |
| `template.cjs` | 3 | Use `paths.*` |
| `gsd-tools.cjs` | 2 | Build `paths` at top, pass down |
| **Total** | **151** | One `buildPaths()` call replaces all |

## Implementation: Workflow Changes

### How Workflows Get the Workstream

Workflows already call `init` commands which return paths. The key change: **init commands return workstream-aware paths**. Workflows already use these returned paths for `<files_to_read>` blocks and agent prompts.

**Minimal workflow changes needed:**
1. `new-milestone.md` → becomes `new-workstream.md` (or adds workstream support)
2. `progress.md` → lists all active workstreams, routes to the right one
3. `execute-phase.md` → uses paths from init (already parameterized)
4. `plan-phase.md` → uses paths from init (already parameterized)
5. `complete-milestone.md` → scoped to workstream via paths

**Most workflows need zero changes** because they already use `${state_path}`, `${roadmap_path}` etc. from init JSON rather than hardcoded strings. The init commands are the bottleneck — fix init, workflows follow.

### New Commands

```
/gsd:new-workstream <name>     # Create a parallel workstream
/gsd:list-workstreams          # Show all active workstreams with status
/gsd:switch-workstream <name>  # Set active workstream for this session
/gsd:complete-workstream <name> # Archive a workstream
```

Or simpler: extend existing commands with `--ws`:
```
/gsd:new-milestone --ws hooks-refactor
/gsd:progress --ws hooks-refactor
/gsd:plan-phase 1 --ws hooks-refactor
```

## Implementation Phases

### Phase 1: Core Path Abstraction (non-breaking)
- Add `buildPaths(cwd, ws)` to `core.cjs`
- Refactor all 11 lib modules to accept `paths` parameter
- Default behavior unchanged (flat mode)
- All 151 hardcoded refs replaced with `paths.*`

### Phase 2: Workstream CRUD
- Add `workstream create/list/switch/complete` commands
- Migration logic (flat → workstream mode)
- Per-workstream STATE.md, ROADMAP.md, REQUIREMENTS.md

### Phase 3: Workflow Updates
- Update `new-milestone.md` to support `--ws`
- Update `progress.md` to show multi-workstream status
- Update `execute-phase.md` and `plan-phase.md` (likely minimal)
- Add `new-workstream.md` workflow

### Phase 4: UX Polish
- Active workstream detection (from `.planning/active-workstream` file or config)
- Status line shows current workstream
- Commit messages include workstream name
- Cross-workstream dependency tracking (optional, future)

## Scope & Effort Estimate

| Component | Files | Estimated changes |
|-----------|-------|-------------------|
| `core.cjs` (add buildPaths) | 1 | ~50 lines new |
| lib modules (accept paths) | 10 | ~151 path refs updated |
| `gsd-tools.cjs` (parse --ws) | 1 | ~20 lines |
| Workflow files | ~10 of 30+ | Template var substitution |
| New commands | 2-4 | `workstream create/list/switch/complete` |
| Tests | TBD | Path resolution, migration, backward compat |

**Backward compatibility guarantee:** Without `--ws` flag and without `workstreams/` directory, behavior is identical to current GSD. Zero breaking changes for existing users.

## Alternatives Considered

### A: Git Worktrees (no plugin changes)
- Each milestone gets its own worktree with isolated `.planning/`
- Pros: Works today, no GSD changes
- Cons: Heavyweight (full repo copy), merge complexity, not ergonomic

### B: `--cwd` Override (existing)
- Point different sessions at different directories
- Pros: Already supported
- Cons: Breaks project-relative paths, confusing UX

### C: File Suffixing (`ROADMAP-v1.1.md`)
- Multiple roadmaps in same directory
- Pros: Simpler directory structure
- Cons: Breaks every regex that parses these files, ambiguous "active" detection

**Recommendation:** The workstream directory approach (this proposal) because it:
- Has the cleanest separation of concerns
- Requires only one abstraction point (`buildPaths`)
- Preserves backward compatibility via flat-mode fallback
- Maps naturally to how developers think about parallel work

## Open Questions

1. Should `PROJECT.md` stay shared or get per-workstream copies?
2. Should `config.json` support per-workstream overrides (e.g., different model profiles)?
3. Should phase numbering restart per-workstream or continue globally?
4. Should workstreams support cross-references (e.g., "depends on workstream X phase 3")?
5. How should `progress.md` render multi-workstream status?

---

*This proposal was developed by analyzing gsd-tools.cjs (11 lib modules, 151 hardcoded `.planning/` references, 72 `path.join` calls) and 30+ workflow files. The analysis is based on the GSD plugin installed at `~/.claude/get-shit-done/` as of 2026-03-02.*

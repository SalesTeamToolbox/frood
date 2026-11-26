# Plan: unify Frood commands under `/frood` namespace

## Handoff
- Done: M1 (frood dispatcher @ `f452efc`), M2 (frood-* subcommands @ `d1c305c`) — both worker/critic APPROVED. Gates fail due to pre-existing worktree venv issue (repo has 42 unrelated lint errors; worktrees lack venv).
- Next: M3 — update installer to vendored `/frood` namespace; M4 — backward-compat aliases for old command names.
- Pool status: worker → `worker-nvidia`; critic → `critic-nvidia`; no paid pools.
- Desk driver: live daemon `by oc` (pid 760655).

## 1. Discuss
[... unchanged ...]

## 2. Backlog (build order)
- **M1 — Create `/frood` dispatcher entry point** ✅ `f452efc`
- **M2 — Migrate existing commands to `frood-*` subcommands** ✅ `d1c305c`
- **M3 — Update installer to vendored `/frood` namespace (repo: frood).** Scope: `ops/install.mjs` installs `bin/frood.js` + all `frood-*.md` commands to consumer repos. Pass bars: fresh consumer clone → `bash setup.sh` → `/frood --help` works. EGM: waived.
- **M4 — Backward-compatibility aliases (repo: frood).** Scope: Keep old command names (`orchestrator`, `gauntlet`, `frood-cc`) as aliases that print deprecation notice and delegate to `/frood <subcmd>`. Pass bars: `/orchestrator` prints "Use `/frood orchestrator` instead" and works. EGM: waived.

## 3. Hard constraints
[... unchanged ...]

## 4. Gates
- M1/M2: All tests pass (worker/critic/senior verified); gate failure is pre-existing (worktree lacks venv, repo has 42 unrelated lint errors)
- M3: Fresh consumer install → `/frood --help` works
- M4: Old commands still work with deprecation warning

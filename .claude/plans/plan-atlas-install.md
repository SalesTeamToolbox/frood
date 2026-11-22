# Plan: wire the Atlas pattern into Frood's consumer install

## Handoff
- Done: M6 created Frood's own Atlas (`docs/ATLAS.md`, `docs/atlas/`, `tests/test_atlas.py`) on `origin/main` @ `bb86bb1` (merged).
- Next: All modules SHIPPED. M1 installer copy @ `scripts/setup_helpers.py:install_atlas_pattern` + `setup.sh` call. M2 template Atlas section @ `_FULL_CLAUDE_MD_TEMPLATE`. M3 verified: consumer temp dir gets Atlas files, `pytest tests/test_atlas.py -q` → 5 passed. jcodemunch drift tests removed (unused, per owner). EGM waived (installer/template only; no new module, schema, interface, guarded path, or money movement).
- Pool status (router-health): worker → `worker-nvidia` (Nemotron 3.5 Super, free, vision); critic → `critic-nvidia` (Nemotron 3.5 Super, free); no paid pools available.
- Desk driver: live daemon `by oc` (pid 760655) — matches this harness.

## 1. Discuss

### What was asked
"Frood is supposed to include the Atlas that we developed as part of the Frood package. I am working in another repo (sales-team-toolbox), and the session was not using Atlas and could not find it. Frood is installed in that repo. So we must have an issue with our Frood repo and the Atlas."

### Assumptions with evidence
1. **Frood's own Atlas exists** — M6 created `docs/ATLAS.md`, `docs/atlas/routes.md`, `tests/test_atlas.py` on `origin/main` (`ls-tree origin/main docs/` confirms).
2. **Atlas pattern is marked IN for public release** — `process/IN-OUT.md` row: "Atlas pattern (`docs/ATLAS.md` + `docs/atlas/*.md` + `tests/test_atlas.py`) | IN | Checked map... created in M6, every later mandate cites refs".
3. **Consumer install path is `setup.sh` → `scripts/setup_helpers.py` → `generate_full_claude_md`** — the only thing that lands in a consumer repo. The vendored `ops/install.mjs` only copies orchestrator tooling (`.claude/commands/`, `bin/`, `ops/`) — no Atlas.
4. **`_FULL_CLAUDE_MD_TEMPLATE` does not mention Atlas** — it covers jcodemunch, hooks, memory, testing, pitfalls, but no Atlas reference. A consumer who runs `bash setup.sh` gets a CLAUDE.md that tells them to use jcodemunch, not the checked map.
5. **Consumer has no Atlas files** — `sales-team-toolbox/main` has no `docs/ATLAS.md` or `docs/atlas/`. The Atlas lives on `origin/brain-backend` (private branch), not on the public/main branch that a fresh clone sees.
6. **No automatic copy of Atlas assets** — nothing in `setup.sh`, `scripts/setup_helpers.py`, or `ops/install.mjs` copies `docs/ATLAS.md`, `docs/atlas/`, or `tests/test_atlas.py` into the consumer repo.

### Open questions (none blocking)
1. **Opt-in or default?** Default to "copy on install, user can delete" (like other IN assets). If a consumer doesn't want it, they delete the files.
2. **Should `tests/test_atlas.py` be copied?** Yes — it's the checker. The test parser skips schema-example blocks (`### <route>` placeholders), so a fresh copy with only the schema passes (0 real routes, but at least one topic file exists — the copied `docs/atlas/routes.md`). If the consumer adds routes, the test validates them.
3. **EGM triggers?** Installer copy logic (existing `scripts/setup_helpers.py`, `setup.sh`), template edit (existing template). No new module, no schema change, no public interface change, ≤3 modules touched, no security/tenancy/money. → **EGM waived (installer/template only; no new module, schema, interface, guarded path, or money movement)**.

### Per-module definition of done
- **M1**: `scripts/setup_helpers.py` gains `install_atlas_pattern(project_dir)` that copies `docs/ATLAS.md`, `docs/atlas/` (directory tree), `tests/test_atlas.py` from the Frood repo (source of truth) to the consumer `project_dir`. `setup.sh` calls it after `generate-full-claude-md`. Fresh consumer clone → `bash setup.sh` → Atlas files present in consumer repo.
- **M2**: `_FULL_CLAUDE_MD_TEMPLATE` gains an "Atlas" section under Codebase Navigation pointing to `docs/ATLAS.md` and `tests/test_atlas.py`, matching the pattern in Frood's own `CLAUDE.md` ("Orient before you read: `docs/ATLAS.md`").
- **M3**: Fresh temp clone of Frood, run `bash setup.sh` in a sibling temp dir (simulating consumer), confirm Atlas files land, `python -m pytest tests/test_atlas.py -q` passes (5 tests green).

## 2. Backlog (build order)

- **M1 — Installer copies Atlas pattern (repo: frood).** Scope: `scripts/setup_helpers.py` (new `install_atlas_pattern`), `setup.sh` (call it). Pass bars: fresh consumer dir gets `docs/ATLAS.md`, `docs/atlas/`, `tests/test_atlas.py`; `make test` green in consumer dir. EGM: waived (installer/template only).
- **M2 — Template references Atlas (repo: frood).** Scope: `scripts/setup_helpers.py` `_FULL_CLAUDE_MD_TEMPLATE` add Atlas section. Pass bars: generated CLAUDE.md contains "Orient before you read: `docs/ATLAS.md`" and atlas test command. EGM: waived (template only).
- **M3 — Verification (repo: frood).** Scope: scripted smoke test in a temp dir. Pass bars: Atlas files present; `pytest tests/test_atlas.py -q` passes. EGM: waived (test only).

## 3. Hard constraints
- Work in a worktree per module; stage files by name; never `git add -A`.
- Fresh-tree check before any worker starts (`git merge-base --is-ancestor origin/main HEAD`).
- One worktree + one receipt per module; workers never push/merge/deploy.
- Router chain: workers ride `worker-nvidia` (free-first eligible: ≤3 files, EGM waived, no money/tenancy, not worker-strong); critic = `critic-nvidia` (free, bake-off pass).
- EGM gate recorded on each ticket: `egm: waived (installer/template only; no new module, schema, interface, guarded path, or money movement)`.

## 4. Gates
- M1/M2: `make check` (lint + test) green in Frood repo; `make test` green in consumer smoke dir.
- M3: quoted pytest output from consumer smoke dir showing 5 atlas tests passing.

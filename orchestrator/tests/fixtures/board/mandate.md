# Ticket demo-one — Mandate: demo module

**Worktree:** this directory, branch `feat/demo-one`, base `main`.

**Atlas refs consulted / updated?** No map in this fixture repo (`docs/ATLAS.md` absent), so no map
entry points to start from and no map lines to update.

**Blast radius:**

- `run()` in `bin/main.mjs` — unchanged; test: bin/demo.test.mjs
- `parse()` in `bin/other.mjs` stays intact
- `load()` in `bin/load.mjs` — new caller only; test: bin/load.test.mjs

## Notes

Anything after the bullets is not part of the blast radius.

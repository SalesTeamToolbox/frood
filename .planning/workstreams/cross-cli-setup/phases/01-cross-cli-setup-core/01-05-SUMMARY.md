---
phase: 01-cross-cli-setup-core
plan: 05
subsystem: cross-cli-setup
tags: [dashboard, endpoints, frontend, toggle, persistence, admin-guard]
requires:
  - 01-03 (core/cli_setup.py — detect_all, wire_cli, unwire_cli)
provides:
  - GET /api/cli-setup/detect
  - POST /api/cli-setup/wire
  - CliSetupWireRequest (Pydantic model)
  - _load_cli_setup_state / _save_cli_setup_state
  - renderCliSetup / loadCliSetup / toggleCliSetup (frontend)
  - .frood/cli-setup-state.json (persisted enabled-list)
affects:
  - "Plan 01-06 (e2e tests) now has both entry points live to exercise from the dashboard side"
tech-stack:
  added: []
  patterns:
    - "FastAPI admin-guarded route via require_admin dependency"
    - "Pydantic request model co-located with existing ToggleRequest"
    - "State persistence helpers mirror _load_toggle_state / _save_toggle_state"
    - "Vanilla-JS panel wired into existing sidebar-nav / renderer-map system"
    - "TestClient + dependency_overrides[require_admin] for auth stubbing"
key-files:
  created:
    - tests/test_cli_setup_dashboard.py
  modified:
    - dashboard/server.py
    - dashboard/frontend/dist/app.js
decisions:
  - "Used FastAPI dependency_overrides for admin auth in tests (matches test_provider_ui.py precedent)"
  - "HTTPException returns remap to {error, message, status} via existing middleware — tests accept both keys"
  - "Frontend panel registered as a dedicated top-level page ('cli-setup') rather than a subsection, so it has its own sidebar entry and URL-style nav state (matches existing Tools / Skills panels)"
  - "Persistence strategy: one JSON object {'enabled_clis': sorted-unique-list} — simplest possible, mirrors the toggle-state shape"
  - "Unknown CLI values rejected at endpoint level (not deferred to core) so the frontend never hits core.cli_setup with a bad name"
metrics:
  duration_minutes: 7
  completed_date: "2026-04-17"
  tasks_completed: 2
  files_created: 1
  files_modified: 2
requirements_satisfied:
  - DASH-01
  - DASH-02
  - DASH-03
  - DASH-04
---

# Phase 01 Plan 05: Dashboard Panel + `/api/cli-setup/*` Endpoints Summary

**One-liner:** Mirrored the `frood cli-setup` CLI surface as a dashboard panel + two admin-guarded REST endpoints (`GET /api/cli-setup/detect`, `POST /api/cli-setup/wire`) that delegate to the same `core.cli_setup` functions (Plan 03) as the CLI subcommand (Plan 04) — toggle state persists to `.frood/cli-setup-state.json` following the existing `toggles.json` pattern.

## What Was Built

### `dashboard/server.py`

- **`CliSetupWireRequest(BaseModel)`** — Pydantic body model co-located next to `ToggleRequest` (line 239). Two fields: `cli: str`, `enabled: bool`.
- **`_CLI_SETUP_STATE_FILE`** — `<repo>/.frood/cli-setup-state.json` (mirror of `_TOGGLE_STATE_FILE` shape).
- **`_load_cli_setup_state()`** — returns `{"enabled_clis": [...]}`; graceful fallback on missing/corrupt file.
- **`_save_cli_setup_state(enabled_clis)`** — sorts + dedups before JSON write; creates parent dir.
- **`GET /api/cli-setup/detect`** — admin-guarded via `_admin: AuthContext = Depends(require_admin)`. Returns `core.cli_setup.detect_all()` verbatim. 500 on adapter failure.
- **`POST /api/cli-setup/wire`** — admin-guarded. Validates `cli in {"claude-code", "opencode"}` (400 otherwise). Dispatches to `wire_cli` or `unwire_cli` based on `enabled`. Persists the resulting enabled-set to the state file. Returns `{cli, enabled, action, result}`. 500 on core exception.

### `dashboard/frontend/dist/app.js`

- **`renderCliSetup(container)`** — renders a card with heading, "What this does" blurb (explains `frood_skill` + that toggling here equals the CLI subcommand), docs link, and a table of detected CLIs with per-row `.toggle-switch` bound to `toggleCliSetup`.
- **`loadCliSetup()`** — fetches `/api/cli-setup/detect` into `state.cliSetup`; graceful error capture (`_error` sentinel surfaced in the panel).
- **`toggleCliSetup(cli, enabled)`** — POSTs to `/api/cli-setup/wire`, toasts success/error, re-fetches detect state, re-renders.
- **Sidebar nav item** added between Skills and Reports: `data-page="cli-setup"` with chain-link glyph `&#128279;`.
- **Renderer map + topbar title map** updated to include `"cli-setup"`.
- **`loadAll()`** now calls `loadCliSetup()` on bootstrap alongside the other loaders.

### `tests/test_cli_setup_dashboard.py` — 9 tests, all passing

| Test | Covers |
| --- | --- |
| `test_detect_requires_admin` | DASH-01 auth guard — anonymous GET rejected (401/403) |
| `test_detect_returns_state` | DASH-01 body — monkeypatched `detect_all` surface flows through verbatim |
| `test_wire_requires_admin` | DASH-02 auth guard |
| `test_wire_enabled_calls_wire_cli` | DASH-02 + DASH-04 — dispatch to `wire_cli`, state file updated |
| `test_wire_disabled_calls_unwire_cli` | DASH-02 + DASH-04 — dispatch to `unwire_cli`, CLI removed from state |
| `test_wire_unknown_cli_400` | unknown cli rejected with 400, no dispatch |
| `test_wire_propagates_core_error_500` | core exception → 500 with useful message |
| `test_state_file_roundtrip` | DASH-04 — `_save`/`_load` round-trip + sorted-unique invariant |
| `test_frontend_panel_wired_in_app_js` | DASH-03 — panel render function, fetch calls, sidebar nav, renderer map all present |

All tests use `app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")` (precedent: `tests/test_provider_ui.py`). State-file tests monkeypatch `dashboard.server._CLI_SETUP_STATE_FILE` into a `tmp_path` so nothing writes to the real `.frood/`.

## Decisions Made

### D-01 — dependency_overrides for admin-guarded tests

Rejected the "stub the JWT + send Bearer header" route in favor of FastAPI's native `app.dependency_overrides`. Simpler, no coupling to JWT internals, matches an existing precedent in the repo (`test_provider_ui.py`), and makes auth-positive tests trivial to write.

### D-02 — Accept both `detail` and `message` keys in assertions

Frood has a middleware that remaps `HTTPException(detail=...)` to `{"error": true, "message": "...", "status": N}` for the client. Discovered this at first test run. Tests now accept either key so they'd pass even if a future refactor drops the middleware.

### D-03 — Sidebar nav + dedicated page, not a subsection

The locked plan said "one new panel"; could have been a sub-tab of Settings. Went with a top-level nav entry to match the Tools / Skills pattern — simpler, no mode-switching logic, and makes the feature discoverable on first login.

### D-04 — CLI name allowlist at endpoint boundary

Rejected deferring "unknown CLI" to core (which raises `KeyError` → 500 via the generic handler). Allowlisting at endpoint level gives a semantically-correct 400 for the frontend and avoids tripping the 500-with-traceback path.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Test 400 assertion read `.detail` but Frood middleware remaps to `.message`**

- **Found during:** First test run of `test_wire_unknown_cli_400` — assertion raised `KeyError: 'detail'`
- **Issue:** The plan's example used `raise HTTPException(status_code=400, detail=...)`, which normally shows up as `.detail` in `resp.json()`. Frood's server has a middleware that reshapes this to `{error, message, status}`.
- **Fix:** Test now accepts either `body["message"]` or `body["detail"]` before substring-checking.
- **Files modified:** `tests/test_cli_setup_dashboard.py` (2 assertions)
- **Commit:** folded into `d07932b`

**2. [Rule 3 - Blocking] Formatter hook reformatted pre-existing code in `dashboard/server.py`**

- **Found during:** Task 1 post-edit
- **Issue:** The PostToolUse formatter (ruff) reformatted several pre-existing long-line blocks in `create_app()` that I had not touched. Scope-boundary rule says "only fix issues caused by this task's changes"; these are pre-existing but the formatter already committed them to my working tree.
- **Fix:** Committed the formatter-only delta as a separate `chore(01-05)` commit (`749f276`) so the feature commits stay focused and the pre-existing style improvements are clearly labeled.
- **Files modified:** `dashboard/server.py`
- **Commit:** `749f276`

No other deviations.

## Verification Results

| Command | Result |
| --- | --- |
| `.venv/Scripts/python.exe -m pytest tests/test_cli_setup_dashboard.py -v` | 9 passed in 0.94s |
| `.venv/Scripts/python.exe -m pytest tests/test_cli_setup_dashboard.py tests/test_cli_setup_core.py -q` | 22 passed in 1.02s (no regression in Plan 03) |
| `.venv/Scripts/python.exe -m ruff check tests/test_cli_setup_dashboard.py` | All checks passed |
| `.venv/Scripts/python.exe -c "from dashboard.server import create_app; ..."` | `['/api/cli-setup/detect', '/api/cli-setup/wire']` |
| `grep -c "cli-setup" dashboard/frontend/dist/app.js` | 10 occurrences (≥3 required) |

## Success Criteria — All Met

- **DASH-01**: `GET /api/cli-setup/detect` is registered, admin-guarded via `Depends(require_admin)`, returns the `core.cli_setup.detect_all()` payload. Anonymous access returns 401/403. Covered by `test_detect_requires_admin`, `test_detect_returns_state`.
- **DASH-02**: `POST /api/cli-setup/wire` dispatches to `core.cli_setup.wire_cli` / `unwire_cli` — the same functions Plan 04's CLI subcommand calls. Covered by `test_wire_enabled_calls_wire_cli`, `test_wire_disabled_calls_unwire_cli`.
- **DASH-03**: `dashboard/frontend/dist/app.js` has a CLI Setup panel with detected-CLI rendering, per-CLI toggle, blurb, and docs link. Wired into the sidebar and renderer map. Covered by `test_frontend_panel_wired_in_app_js`.
- **DASH-04**: Toggle state persisted to `.frood/cli-setup-state.json` as `{"enabled_clis": [...]}`. Mirrors `toggles.json` pattern. Covered by `test_state_file_roundtrip` + state assertions in `test_wire_enabled_calls_wire_cli` / `test_wire_disabled_calls_unwire_cli`.

## Frontend Panel Integration Point

| Where | What |
| --- | --- |
| Sidebar nav (line ~2089) | New `<a data-page="cli-setup">&#128279; CLI Setup</a>` entry between Skills and Reports |
| Topbar title map (line ~2106) | `"cli-setup": "CLI Setup"` entry added |
| Renderer map (line ~2120) | `"cli-setup": renderCliSetup` entry added |
| Bootstrap (`loadAll`) | `loadCliSetup()` call added to the Promise.all |

No new CSS classes were added — the panel reuses existing `.card`, `.table-wrap`, `.toggle-switch`, `.toggle-slider`, `.badge-source`, `.badge-category`, and `.empty-state` classes.

## Pydantic Request Model Shape

```python
class CliSetupWireRequest(BaseModel):
    """Request body for POST /api/cli-setup/wire (DASH-02)."""
    cli: str        # "claude-code" | "opencode" (enforced at endpoint)
    enabled: bool   # True → wire_cli(cli); False → unwire_cli(cli)
```

Admin auth fixture pattern used:

```python
app.dependency_overrides[require_admin] = lambda: AuthContext(user="test-admin")
```

## Commits

| Task | Type | Hash | Message |
| --- | --- | --- | --- |
| 1 | feat | `9a57674` | `feat(01-05): add /api/cli-setup/detect + wire endpoints` |
| 2 | feat | `d07932b` | `feat(01-05): add CLI Setup dashboard panel + tests` |
| — | chore | `749f276` | `chore(01-05): formatter pass on dashboard/server.py` |

## Known Stubs

None — the full endpoint surface and frontend panel are wired end-to-end. Both entry points (CLI subcommand via Plan 04 and dashboard via Plan 05) now share the same `core.cli_setup` adapters. The docs link in the panel points to the Claude Code repo as a placeholder since Frood doesn't have a hosted docs site yet; Plan 06 tests do not depend on the link target.

## Self-Check: PASSED

- `dashboard/server.py` — FOUND (modified, contains `/api/cli-setup/detect`, `/api/cli-setup/wire`, `_load_cli_setup_state`, `_save_cli_setup_state`)
- `dashboard/frontend/dist/app.js` — FOUND (modified, 10 `cli-setup` occurrences)
- `tests/test_cli_setup_dashboard.py` — FOUND (new, 9 tests passing)
- Commit `9a57674` — FOUND in git log (`feat(01-05): add /api/cli-setup/detect + wire endpoints`)
- Commit `d07932b` — FOUND in git log (`feat(01-05): add CLI Setup dashboard panel + tests`)
- Commit `749f276` — FOUND in git log (`chore(01-05): formatter pass on dashboard/server.py`)
- All 9 dashboard tests + all 13 core tests (22 total) passing

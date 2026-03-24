---
phase: 2
slug: ide-surface-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-24
---

# Phase 2 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x + pytest-asyncio |
| **Config file** | pyproject.toml (asyncio_mode = "auto") |
| **Quick run command** | `python -m pytest tests/test_workspace_registry.py tests/test_ide_workspace.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_workspace_registry.py tests/test_ide_workspace.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 02-01-01 | 01 | 1 | ISOL-01 | integration | `pytest tests/test_ide_workspace.py -k "test_file_explorer_scoping"` | ❌ W0 | ⬜ pending |
| 02-01-02 | 01 | 1 | ISOL-04 | integration | `pytest tests/test_ide_workspace.py -k "test_terminal_scoping"` | ❌ W0 | ⬜ pending |
| 02-02-01 | 02 | 2 | ISOL-02 | manual-only | — | — | ⬜ pending |
| 02-02-02 | 02 | 2 | ISOL-03 | manual-only | — | — | ⬜ pending |
| 02-03-01 | 03 | 3 | FOUND-03 | manual-only | — | — | ⬜ pending |
| 02-03-02 | 03 | 3 | ISOL-05 | manual-only | — | — | ⬜ pending |
| 02-03-03 | 03 | 3 | FOUND-05 | manual-only | — | — | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_ide_workspace.py` — stubs for ISOL-01, ISOL-04 (file explorer and terminal workspace scoping)

*Existing pytest infrastructure covers framework needs.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Editor tabs restore cursor/scroll/selection on workspace switch | ISOL-02 | Monaco view state requires visual verification | Open files in two workspaces, switch between them, verify cursor/scroll positions preserved |
| CC sessions filtered per workspace in sidebar | ISOL-03 | UI sidebar filtering requires visual inspection | Start CC sessions in different workspaces, verify only current workspace sessions shown |
| Workspace tab bar renders and switches all surfaces | FOUND-03 | Full UI integration requires visual verification | Click workspace tabs, verify file explorer, editor, CC, terminals all switch |
| Workspace tab state persists across page reload | ISOL-05 | Reload behavior requires browser testing | Set active workspace, reload page, verify same workspace active |
| Workspace tab state stale-while-revalidate | FOUND-05 | Race condition between cache and server requires manual timing check | Load page with cached workspaces, verify tabs render immediately then reconcile |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

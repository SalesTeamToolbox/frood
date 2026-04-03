---
phase: 36
slug: paperclip-integration-core
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-03
---

# Phase 36 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x (Python backend) / TypeScript tsc --noEmit (plugin frontend) |
| **Config file** | `tests/` directory (pytest) / `plugins/agent42-paperclip/tsconfig.json` (tsc) |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v && cd plugins/agent42-paperclip && npx tsc --noEmit` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v && cd plugins/agent42-paperclip && npx tsc --noEmit`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 36-01-T1 | 01 | 1 | PAPERCLIP-01 | type-check | `cd plugins/agent42-paperclip && npx tsc --noEmit` | ✅ | ⬜ pending |
| 36-01-T2 | 01 | 1 | PAPERCLIP-02,03,04 | import-check | `python -c "from dashboard.sidecar import create_sidecar_app"` | ✅ | ⬜ pending |
| 36-01-T3 | 01 | 1 | PAPERCLIP-05 | import-check | `python -c "from core.config import Settings; s = Settings(sidecar_enabled=True)"` | ✅ | ⬜ pending |
| 36-02-T1 | 02 | 2 | PAPERCLIP-01 | type-check | `cd plugins/agent42-paperclip && npx tsc --noEmit` | ✅ | ⬜ pending |
| 36-02-T2 | 02 | 2 | PAPERCLIP-02,03,04 | build | `cd plugins/agent42-paperclip && npm run build` | ✅ | ⬜ pending |
| 36-03-T1 | 03 | 3 | PAPERCLIP-01,02,03,05 | unit | `python -m pytest tests/test_sidecar_phase36.py -x -q` | ❌ W0 | ⬜ pending |
| 36-03-T2 | 03 | 3 | PAPERCLIP-01,02,03 | unit | `cd plugins/agent42-paperclip && npm test` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_sidecar_phase36.py` — sidecar endpoint tests for terminal, apps, tools/skills, dashboard gate (Plan 03 Task 1)
- [ ] `plugins/agent42-paperclip/src/__tests__/manifest.test.ts` — manifest slot declarations (Plan 03 Task 2)
- [ ] `plugins/agent42-paperclip/src/__tests__/worker-handlers.test.ts` — worker data/action/stream handlers (Plan 03 Task 2)

*Existing pytest + npm test infrastructure covers framework needs — no new install required.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Terminal renders in Paperclip UI | PAPERCLIP-01 | Requires browser rendering | Open Paperclip → Agent42 page → verify terminal component loads |
| Apps panel shows in workspace | PAPERCLIP-02 | Requires Paperclip runtime | Open Paperclip → Agent42 page → verify apps list renders |
| Settings panel in Paperclip admin | PAPERCLIP-05 | Requires Paperclip settings UI | Open Paperclip → Settings → verify Agent42 tab exists |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

---
phase: 28
slug: paperclip-plugin
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-30
---

# Phase 28 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | Vitest 4.1.2 (TypeScript plugin) + pytest 7.x (Python sidecar) |
| **Config file** | `plugins/agent42-paperclip/vitest.config.ts` (Wave 0 creates) |
| **Quick run command** | `cd plugins/agent42-paperclip && npm test` + `python -m pytest tests/test_sidecar_mcp.py -x -q` |
| **Full suite command** | `cd plugins/agent42-paperclip && npm test -- --reporter=verbose` + `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `cd plugins/agent42-paperclip && npm test` + `python -m pytest tests/test_sidecar_mcp.py -x -q`
- **After every plan wave:** Run full suite commands
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 28-01-01 | 01 | 1 | PLUG-01 | unit | `npm test -- tests/worker.test.ts` | ❌ W0 | ⬜ pending |
| 28-01-02 | 01 | 1 | PLUG-07 | unit | `npm test -- tests/worker.test.ts` | ❌ W0 | ⬜ pending |
| 28-02-01 | 02 | 1 | PLUG-02 | unit | `npm test -- tests/tools.test.ts` | ❌ W0 | ⬜ pending |
| 28-02-02 | 02 | 1 | PLUG-03 | unit | `npm test -- tests/tools.test.ts` | ❌ W0 | ⬜ pending |
| 28-02-03 | 02 | 1 | PLUG-04 | unit | `npm test -- tests/tools.test.ts` | ❌ W0 | ⬜ pending |
| 28-02-04 | 02 | 1 | PLUG-05 | unit | `npm test -- tests/tools.test.ts` | ❌ W0 | ⬜ pending |
| 28-02-05 | 02 | 1 | PLUG-06 | unit | `npm test -- tests/tools.test.ts` | ❌ W0 | ⬜ pending |
| 28-03-01 | 03 | 2 | PLUG-06 | unit | `python -m pytest tests/test_sidecar_mcp.py -x -q` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `plugins/agent42-paperclip/package.json` — package scaffold with @paperclipai/plugin-sdk dep
- [ ] `plugins/agent42-paperclip/tsconfig.json` — TypeScript config
- [ ] `plugins/agent42-paperclip/vitest.config.ts` — Vitest configuration
- [ ] `plugins/agent42-paperclip/tests/worker.test.ts` — stubs for PLUG-01, PLUG-07
- [ ] `plugins/agent42-paperclip/tests/tools.test.ts` — stubs for PLUG-02 through PLUG-06
- [ ] `plugins/agent42-paperclip/tests/client.test.ts` — Agent42Client HTTP contract
- [ ] `tests/test_sidecar_mcp.py` — Python-side POST /mcp/tool endpoint tests

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `paperclip doctor` passes | PLUG-01 | Requires running Paperclip instance | Install plugin in dev Paperclip, run `paperclip doctor` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

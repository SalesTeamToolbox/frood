---
phase: 52
slug: core-identity-rename
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-07
---

# Phase 52 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | tests/ directory (no pytest.ini — uses defaults) |
| **Quick run command** | `python -m pytest tests/ -x -q` |
| **Full suite command** | `python -m pytest tests/ -v` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/ -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -v`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 52-01-01 | 01 | 1 | ENTRY-01 | unit | `python -c "import frood"` | ❌ W0 | ⬜ pending |
| 52-01-02 | 01 | 1 | ENTRY-02 | unit | `python -c "import agent42"` | ❌ W0 | ⬜ pending |
| 52-02-01 | 02 | 1 | DATA-01 | unit | `grep -r "\.frood/" core/config.py` | ✅ | ⬜ pending |
| 52-02-02 | 02 | 1 | DATA-02 | unit | `python -m pytest tests/test_frood_migration.py -v` | ❌ W0 | ⬜ pending |
| 52-02-03 | 02 | 1 | DATA-03 | grep | `grep -rn "\.agent42/" core/ tools/ memory/` | ✅ | ⬜ pending |
| 52-03-01 | 03 | 1 | PY-01 | grep | `grep -rn 'getLogger("agent42' core/ tools/ memory/ dashboard/` | ✅ | ⬜ pending |
| 52-03-02 | 03 | 1 | PY-02 | grep | `grep -rn '\[agent42-' .claude/hooks/` | ✅ | ⬜ pending |
| 52-03-03 | 03 | 1 | PY-03 | grep | `grep -rn 'AGENT42' mcp_server.py` | ✅ | ⬜ pending |
| 52-03-04 | 03 | 1 | PY-04 | grep | `grep -rn 'AGENT42_MEMORY' scripts/setup_helpers.py` | ✅ | ⬜ pending |
| 52-04-01 | 04 | 2 | ENTRY-03 | grep | `grep -rn 'AGENT42_' core/ .claude/hooks/ mcp_server.py` | ✅ | ⬜ pending |
| 52-04-02 | 04 | 2 | ENTRY-04 | unit | `grep 'FROOD_' core/config.py` | ✅ | ⬜ pending |
| 52-04-03 | 04 | 2 | ENTRY-05 | grep | `grep 'FROOD_' .env.example` | ✅ | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_frood_migration.py` — stubs for DATA-02 (auto-migration: old-only, both-exist, neither-exist)
- [ ] `frood.py` — main entry point must exist before import tests pass
- [ ] `agent42.py` — shim must exist and delegate to frood.main()

*Note: No framework install needed — pytest already present.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| `.agent42/` auto-migrates to `.frood/` | DATA-02 | Requires filesystem state setup | Create `.agent42/` dir, run `python frood.py`, verify `.frood/` exists and log message appears |
| VPS `.env` update | ENTRY-03 | Production environment | SSH to VPS, verify `FROOD_*` vars in `.env` |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

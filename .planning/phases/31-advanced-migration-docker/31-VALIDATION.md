---
phase: 31
slug: advanced-migration-docker
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-03-31
---

# Phase 31 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest 7.x |
| **Config file** | pyproject.toml (existing) |
| **Quick run command** | `python -m pytest tests/test_migration.py tests/test_docker_compose.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~15 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_migration.py tests/test_docker_compose.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 15 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 31-01-01 | 01 | 1 | ADV-04 | unit | `python -m pytest tests/test_migration.py -x -q` | ❌ W0 | ⬜ pending |
| 31-02-01 | 02 | 1 | ADV-05 | syntax | `docker compose -f docker-compose.paperclip.yml config --quiet` | ❌ W0 | ⬜ pending |

*Status: ⬜ pending · ✅ green · ❌ red · ⚠️ flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_migration.py` — stubs for ADV-04 (migration CLI tests)
- [ ] `tests/test_docker_compose.py` — stubs for ADV-05 (compose file validation)

*Existing test infrastructure covers framework setup.*

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Docker Compose services start and communicate | ADV-05 | Docker Engine not available in dev shell | Run `docker compose -f docker-compose.paperclip.yml up -d` on a machine with Docker, verify all services healthy |
| End-to-end heartbeat through compose stack | ADV-05 | Requires running Paperclip + sidecar | POST to sidecar /sidecar/execute via Paperclip adapter, verify callback received |
| Migration preserves recall across instances | ADV-04 | Requires two Qdrant instances | Run migration CLI, then POST /memory/recall with migrated agent_id, verify memories returned |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 15s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

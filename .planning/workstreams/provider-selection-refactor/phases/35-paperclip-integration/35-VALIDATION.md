---
phase: 35
slug: paperclip-integration
status: draft
nyquist_compliant: false
wave_0_complete: false
created: 2026-04-06
---

# Phase 35 — Validation Strategy

> Per-phase validation contract for feedback sampling during execution.

---

## Test Infrastructure

| Property | Value |
|----------|-------|
| **Framework** | pytest (per CLAUDE.md) |
| **Config file** | pyproject.toml (project root) |
| **Quick run command** | `python -m pytest tests/test_sidecar.py tests/test_sidecar_phase35.py -x -q` |
| **Full suite command** | `python -m pytest tests/ -x -q` |
| **Estimated runtime** | ~30 seconds |

---

## Sampling Rate

- **After every task commit:** Run `python -m pytest tests/test_sidecar.py tests/test_sidecar_phase35.py -x -q`
- **After every plan wave:** Run `python -m pytest tests/ -x -q`
- **Before `/gsd:verify-work`:** Full suite must be green
- **Max feedback latency:** 30 seconds

---

## Per-Task Verification Map

| Task ID | Plan | Wave | Requirement | Test Type | Automated Command | File Exists | Status |
|---------|------|------|-------------|-----------|-------------------|-------------|--------|
| 35-01-01 | 01 | 1 | UI-01 | unit | `pytest tests/test_sidecar.py -k health -x -q` | yes | pending |
| 35-01-02 | 01 | 1 | UI-02 | unit | `pytest tests/test_sidecar_phase35.py -k models -x -q` | no (Wave 0) | pending |
| 35-01-03 | 01 | 1 | UI-03 | unit | `pytest tests/test_sidecar_phase35.py -k models_schema -x -q` | no (Wave 0) | pending |
| 35-01-04 | 01 | 1 | UI-04 | unit | `pytest tests/test_sidecar_phase35.py -k health_detail -x -q` | no (Wave 0) | pending |

*Status: pending / green / red / flaky*

---

## Wave 0 Requirements

- [ ] `tests/test_sidecar_phase35.py` — covers UI-02, UI-03, UI-04 endpoint behavior
  - `test_get_models_returns_provider_list` — GET /sidecar/models returns 200 with models array
  - `test_get_models_includes_all_providers` — all configured providers present
  - `test_get_models_no_auth_required` — endpoint is public
  - `test_health_includes_providers_detail` — GET /sidecar/health includes providers_detail list
  - `test_health_providers_detail_schema` — each item has name/configured/connected/model_count/last_check
  - `test_synthetic_key_in_admin_configurable` — SYNTHETIC_API_KEY in ADMIN_CONFIGURABLE_KEYS
  - `test_synthetic_key_in_settings_dataclass` — hasattr(Settings(), "synthetic_api_key")

---

## Manual-Only Verifications

| Behavior | Requirement | Why Manual | Test Instructions |
|----------|-------------|------------|-------------------|
| Paperclip plugin renders ProviderHealthWidget with updated data | UI-04 | Requires running Paperclip instance | Start Paperclip + Agent42 sidecar, verify widget shows per-provider status |

---

## Validation Sign-Off

- [ ] All tasks have `<automated>` verify or Wave 0 dependencies
- [ ] Sampling continuity: no 3 consecutive tasks without automated verify
- [ ] Wave 0 covers all MISSING references
- [ ] No watch-mode flags
- [ ] Feedback latency < 30s
- [ ] `nyquist_compliant: true` set in frontmatter

**Approval:** pending

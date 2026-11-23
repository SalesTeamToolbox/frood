---
description: EGM (Elephant-Goldfish) review — pre-gauntlet plan review, in-gauntlet loop, post-ship drift report; delegates to EGM plugin commands
argument-hint: "<egm-review|review-loop|drift-report> <plan>"  # /frood-egm-review, /egm:egm-review
---

EGM (Elephant-Goldfish) review for Frood. Delegates to the EGM plugin commands
(`/frood-egm-review` in OpenCode, `/egm:egm-review` in Claude Code).

**Usage:**
```
/frood-egm egm-review <plan>
/frood-egm review-loop <changed-files...>
/frood-egm drift-report <designs-dir>
/frood-egm --help
```

The EGM gate is mechanical: before any worker starts, check the triggers
(new module, data-model change, public-interface change, >3 modules, security/
tenancy). Any trigger ⇒ EGM review **required**; no trigger ⇒ waivable (record
`egm_review: { status: "waived", waive_reason: "..." }`).

- Pre-gauntlet (required tickets): `/frood-egm-review <plan>` → resolve → approve before `/frood-gauntlet`.
- Inside gauntlet (after build, before adversarial): targeted review loop on the changed files.
- Post-ship: drift report on `docs/designs/` when specs and code may have diverged.

Dispatch reviewers with `model: "haiku"` — the plugin's agents are `model:
inherit` and would otherwise run on Opus. Fresh subagents are mandatory.

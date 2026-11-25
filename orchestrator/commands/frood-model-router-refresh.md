---
description: Refresh the model routing table when stale — re-fetch provider allowances, re-probe, re-write 01-orchestrator-models.md
---

Explicit entry for the router refresh. Read `~/.config/opencode/skills/model-router-refresh/SKILL.md` first and follow it exactly.

What to run: $ARGUMENTS (one of `--check-only`, `--force`, or empty = full stale-check then refresh if stale).

The orchestrator calls this when `~/.config/opencode/rules/01-orchestrator-models.md` `Last audited` is >14 days old, or when `opencode models` shows a model the rule does not name (or a provider re-added to the harness). Humans can call it directly (`/frood-model-router-refresh --check-only`) to see headroom without writes.

Writes only to: `~/.config/opencode/rules/01-orchestrator-models.md` (Last audited + audit table + Subagent examples). Never touches `opencode.json`, repo trees, or code files. Receipt: `[router-refresh] -> [check/fetch/probe] -> [rows changed or none] -> [new Last audited + model count]`.

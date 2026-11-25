---
name: frood-model-router-refresh
description: "Refresh the model routing table when it goes stale: re-fetch provider usage allowances, re-run probe parity, re-write 01-orchestrator-models.md with today's date. Use when Last audited is >14 days old or a new model appears in `opencode models`."
version: 1.0.0
user-invocable: true
argument-hint: "[--check-only | --force]"
license: Apache 2.0
allowed-tools:
  - Read
  - Grep
  - Glob
  - Edit
  - Write
  - WebFetch
  - Bash(opencode models *)
  - Bash(opencode auth list *)
  - Bash(node *)
---

# Model Router Refresh

The routing table is a **snapshot** — pricing, allowances, and model lists move under it. This skill re-validates it and re-writes **only the source file** `{{ORCH_REPO}}/rules/01-orchestrator-models.md` when reality changed, then installs it. Never edit the installed copy in `~/.config/opencode/rules/` — the installer overwrites it.

## 0. Staleness check (always run first — cheap, no writes)

1. Read the `**Last audited:**` line in `~/.config/opencode/rules/01-orchestrator-models.md` (search `Last audited` via Grep). Parse the date `YYYY-MM-DD`.
2. Run `Bash(opencode models 2>&1 | sort)` and count lines (per provider: `grep "^opencode-go/"`). Run `Bash(opencode auth list 2>&1 | head -20)`.
3. Compare: table says `71 models` (or whatever the current count line says) vs live count. **Counts are the freshness signal** — the rule file's list is grouped shorthand + `etc.` (`claude-opus-5/5-5/4-7/4-8`, `v4-flash/fast/pro`), so a full-name substring grep is NOT valid by itself. Only if count mismatches, list the live names and Grep the file for each — unmatched ones are the new models. On WSL hosts use `wsl bash -l -c 'opencode models ...'`; in pwsh use `opencode models | Select-String "^opencode-go"`.
4. Verdict:
   - **Fresh** — `age ≤ 14 days` AND model count matches AND no unknown models → stop, report `[router-refresh] -> [check: fresh, audited <date>, <N> models match] -> [no changes] -> [stale in <14-age>d]`. Do NOT fetch pricing pages.
   - **Stale** — `age > 14 days` OR count mismatch OR unknown model → continue to §1.
   - With `--check-only` → report verdict and stop, never write.
   - With `--force` → skip verdict, go to §1.

## 1. Re-fetch (only when stale — noisy, use subagents)

Spawn one explore subagent per provider page, each read-only, using live pages (do NOT guess — quote fetched lines):

- **Go:** fetch `https://opencode.ai/docs/console/go/#usage-limits` — extract per-model `$input/$output/$cache` per 1M tokens, `$monthly limit`, `requests per 5 hours` (5hr = 20% monthly). Intel scores are NOT on the Go page. Note Go Plus deltas (same token prices, higher limits; NOT uniform 2× — check each row) and the three Unlimited free models + geo/training caveats. Backup: `/pricing`, `/docs/console/models/`.
- **Another provider** (re-added to the harness later): fetch its plan/limits page the same way and record the exact variant ID of every model. CommandCode was removed 2026-11-25; the routing rule says so.
- **Kimi guard:** if `kimi-k2.7-code` req/5hr is still low (~1,350 Go), keep the freeze note (`hard/escalation only after two stalls, max 1 worker`) — do NOT restore it as a default worker no matter what.

Each subagent returns a table like: `Role | Go $tok → $cap → req/5hr | Winner`. Noisy fetch context stays in the subagent — the orchestrator only receives the tables.

## 2. Probe parity (only when stale — one grep task, three models)

Run the same grep task on all three (quoted `tool_output`, no hallucination):

```
subagent({ agent: "scout" })                                                      // baseline, Zen free $0
subagent({ agent: "explore", model: "opencode-go/mimo-v2.6-flash" })              // worker pool
subagent({ agent: "explore", model: "opencode-go/deepseek-v4.1-flash" })          // alternate pool
```

Task: `Use Grep to find where "chargeWallet" is defined or called in <a repo you own>. Return top 3 file:line.` Expect `src/lib/wallet.ts:123` on all three. If a worker-pool model fails or hallucinates, demote it in the table and promote the alternate (`opencode-go/glm-5.3-flash`). If a winner flips, also update the matching agent's `model:` in `{{ORCH_REPO}}/agents/`.

## 3. Rewrite (only this file — stage by name, never blanket-add)

Edit `{{ORCH_REPO}}/rules/01-orchestrator-models.md` (and, only on a winner flip, the agent file named above):

1. Update `**Last audited:** <today>` with today's date + sources + live model count.
2. Update the `Bang-for-buck audit <date>` table rows that changed (winner flips, ±10% req/5hr, new models, removed models). Keep the audit date in the header.
3. Update `Subagent examples` only if a winner flipped (model string + req/5hr comment).
4. Do NOT touch `opencode.json`, consuming repos, `02-progress-bar.md`, or any repo code. If the refresh also affects `command/orchestrator.md` EGM reviewer model (`claude-haiku-5-5` vs alternate), note it in the receipt as follow-up — do not edit it here.

Verify: `node {{ORCH_REPO}}/bin/check-routing.mjs` must print `OK`; then install with `node {{ORCH_REPO}}/bin/install.mjs`. Quote the new `Last audited` line, any flipped rows and the check-routing result. Commit the repo change by file name.

## Receipt

`[router-refresh] -> [check/fetch/probe results] -> [rows changed or none] -> [new Last audited + model count]`

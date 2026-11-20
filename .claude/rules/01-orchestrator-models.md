# Orchestrator model routing — the one source of truth

**Last audited:** 2026-11-17 (prices/allowances from `https://opencode.ai/docs/console/go/#usage-limits`, `https://commandcode.ai/docs/plans/goat`, `https://commandcode.ai/docs/resources/pricing-limits` as fetched 2026-11-16; model IDs checked against live `opencode models`, 92 `commandcode/*` (was 71 on 2026-11-11). CmdC weekly quota was out at audit time (429 till ~2026-11-17T21:53Z), so the CmdC probe leg was skipped — no demotions, quota not capability.) **Refresh:** `/model-router-refresh` when this date is >14 days old or `opencode models` shows a `commandcode/*` not named here. Edit the source in `/home/user/projects/orchestrator/rules/` and run its installer — the installed copy is overwritten. `node bin/check-routing.mjs` (in that repo) verifies every ID below is live.

**Names.** "Claude Code" = the Anthropic harness on the Claude subscription. "CmdC" = CommandCode GOAT ($10/mo flat plan, models `commandcode/*`). "Go" = OpenCode Go (`opencode-go/*`, metered against monthly caps). "Zen free" = `opencode/*-free` ($0). Never write bare "CC" — it has meant both.

## Roles → agents (spawn the agent; never hand-type a model)

**Effort** is pinned per role in the Claude Code agent frontmatter: `scout` low, `worker` medium, `critic` high, `senior` high. The orchestrator session itself runs Opus 5.5 at medium; do not pass `effort` on a spawn unless the owner asks.

Every role is a named agent with its model pinned in its definition, so a spawn cannot silently inherit the orchestrator's model. Installed by the orchestrator repo to `~/.claude/agents/` and `~/.config/opencode/agents/`.

| Role | Claude Code agent (model alias) | OpenCode agent (model) |
|---|---|---|
| Scout — grep/read/ls, file:line answers, no edits | `scout` (`haiku`) | `scout` (`opencode/mimo-v2.6-flash-free`, $0) |
| Worker — routine code from a Mandate | `worker` (`sonnet`) | `worker` (`opencode-go/mimo-v2.6-flash`) |
| Worker free-first — same agents, free pools first, for small/waived/non-money tickets (round 2+ goes paid) | — | `--agent worker-nvidia --fallback worker-free,worker-burst,worker-alt,worker` |
| Worker burst — when Go MiMo is hot or capped | — | `worker-burst` (`commandcode/deepseek/deepseek-v4.1-flash`) |
| Worker alt — second hop | — | `worker-alt` (`commandcode/z-ai/glm-5.3-flash`) |
| Worker strong — high-allowance strength for harder tickets | — | `worker-strong` (`opencode-go/muse-spark-1.3-contributor`) |
| Critic — 1 review pass: verdict + findings, no edits | `critic` (`sonnet`) | `critic` (`commandcode/claude-haiku-5-5`) |
| Critic alt — when the Haiku pool is unavailable | — | `critic-alt` (`commandcode/gpt-6-luna`) |
| Critic go — paid Go fallback when both CmdC pools are out (verdicts count) | — | `critic-go` (`opencode-go/deepseek-v4.1-flash`, probed live 2026-11-17) |
| Senior — final sign-off only, when triggered | `senior` (`fable`, effort high) for guarded paths / money / tenancy; otherwise the Opus orchestrator itself | `senior` (`commandcode/claude-sonnet-5-5`) → `senior-alt` (`commandcode/deepseek/deepseek-v4-pro`) |
| Orchestrator (OpenCode) | — | `orchestrator` (`opencode-go/muse-spark-1.3-contributor`) → `orchestrator-alt` (`commandcode/meta/muse-spark-1.3-contributor`) → `orchestrator-free` (`opencode/deepseek-v4.1-flash-free`) |
| Free tier (last resort) | — | `worker-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`), `worker-free` (`opencode/deepseek-v4.1-flash-free`), `critic-free` (`opencode/deepseek-v4.1-flash-free`, bake-off 2026-11-18 pass), `critic-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`, bake-off 2026-11-18 pass, advisory only) |

Claude Code `Agent`/`Task` takes `subagent_type: "<agent>"`. If a raw `model` is ever passed it must be an alias — `haiku`, `sonnet`, `opus`, `fable` — never a full ID like `claude-sonnet-4-5` (invalid there). OpenCode `subagent({ agent: "<agent>" })` uses the pinned model; pass `model:` only to override deliberately (and say why in the receipt).

## Default loop (either harness orchestrates)

Orchestrator writes the ticket + Mandate → **worker** codes in the ticket worktree → **critic** reviews diff + tests → `CHANGES_REQUESTED` goes back to the same worker with the findings (max 3 rounds) → `APPROVED` → **senior** only if triggered (guarded path, risky diff, or >2 rounds) → board `ready` → train.

- **Claude Code available (cost play):** orchestrator Opus 5.5 in Claude Code; workers are **OpenCode** agents (`worker`/`worker-burst`/`worker-strong`), launched headless by `bin/oc-worker` — none of the code-writing touches the Claude subscription; critic = Claude Code `critic` (Sonnet); senior = Claude Code `senior` (Fable, effort high) when the diff touches the repo adapter's `guarded_paths`/`egm_paths` or a money/tenancy trigger — rare, one pass — else the Opus orchestrator.
- **No Claude Code (fallback):** orchestrator = first healthy of `orchestrator` → `orchestrator-alt` → `orchestrator-free`; workers the same; critic = OpenCode `critic` (CmdC Haiku); senior = OpenCode `senior` (CmdC Sonnet 5.5, 1 pass). **CmdC Opus and GPT-6 Sol are NOT in the GOAT plan** (`MODEL_NOT_IN_PLAN`, probed 2026-11-12).
- **Free-only run** (every paid pool out): ends `READY — HUMAN/SENIOR REVIEW REQUIRED`; never boarded until a bake-off-passing critic, a senior, or the owner signs off (price is not the qualifier — a free critic that passes the fixture counts). Critics' verdicts always pass `bin/verdict-gate.mjs` (free: `--free`).
- Prefer cross-family between worker and critic (MiMo/DeepSeek worker → Anthropic critic) so the critic pushes back.

## Pools, fallbacks, freezes

- **Provider policy (owner decisions, `~/.config/orchestrator/providers.json`; enforced by oc-worker exit 8, check-routing, board free-ness):** Google **free-only** — text Flash/Flash-Lite (`gemini-*-flash`, `-flash-lite`, `-flash-preview`, `-flash-lite-preview`; image/tts/live/audio/embedding always denied); Alibaba **ignored**; Nvidia **free-only** — Nemotron 3 Ultra 550B, Nemotron 3.5 Super, DeepSeek v4.1 Flash, GPT-OSS 20B (probed 2026-11-12; GLM and MiniMax via Nvidia timed out). Free-only models count as FREE (they code and review early rounds; sign-off needs a bake-off-passing critic — free or paid — per the capability rule above). New connections are flagged by router-health (`NEW PROVIDER:`) and need an owner decision (`router-health --decide`).

- **Self-correcting availability.** `oc-worker --fallback` walks the chain; a run that dies on quota / not-in-plan / model-unavailable before any output marks that model down in `~/.config/orchestrator/pool-health.json` (until the provider's retry-after; not-in-plan 7 days; missing model 24 h) and moves on — later runs skip known-down models without calling them. `bin/router-health.mjs --if-stale 24 --probe` (run by `/orchestrator` at start) checks every pinned model still exists, probes the cheap roles, and prints the agent to use per role. Chains: `worker` → `worker-burst` → `worker-alt` → `worker-nvidia` → `worker-free` (**paid-first**, default) versus `worker-nvidia` → `worker-free` → `worker-burst` → `worker-alt` → `worker` (**free-first**: same agents, free pools first, paid tail = automatic escalation when a free pool is down); `worker-strong` → `worker-burst` → `worker-alt`; `critic` → `critic-alt` → `critic-go` → `critic-free` → `critic-nvidia`; `senior` → `senior-alt`; `orchestrator` → `orchestrator-alt` → `orchestrator-free`. First dispatch rides free-first only when ALL hold: ≤3 files in scope, EGM waived with reason, no money/tenancy movement (no senior_trigger), not `worker-strong` territory — everything else rides paid-first. A free-first run that does not clear round 1 (CHANGES_REQUESTED or stall) is re-dispatched for round 2+ on the paid-first chain (same session for context); the desk implements this itself (`decideStep`: a reviewed run whose agent is `worker-nvidia`/`worker-free` resumes with `--agent worker` + the paid-first `--fallback`). For a ticket touching >3 files or expected to run >15 min, leave `worker-nvidia` out of `--fallback` (long Nvidia runs drop); if every paid OpenCode pool is out, use the Claude Code `worker` (Sonnet) instead of the Nvidia/free tail. Self-correction only moves **within** these chains; a new model enters a chain only via `/model-router-refresh` + probe + owner approval. Pools below 15% window headroom (local ledger, `bin/usage.mjs` — spend/allowance per window, no live provider API exists) are skipped like down pools, free pools never.

- **Orchestrator (OpenCode):** `opencode-go/muse-spark-1.3-contributor` — $0.10/$0.20/$0.002 per 1M, $60/mo cap → ~45,300 req/5hr. Fallback `opencode-go/muse-spark-1.2-contributor` if region-limited. Its bucket is separate from the workers'; don't run bulk workers on Muse unless the ticket needs `worker-strong`.
- **Scout (free):** `opencode/mimo-v2.6-flash-free`; alternates `opencode/nemotron-3.5-lightning-free`, `opencode/deepseek-v4.1-flash-free`, `opencode/glm-5.3-flash`. Avoid `opencode/iceman-free` for proprietary code (trains on data). `opencode-go/longcat-2.5-free` and `opencode/beam-free` exist but are region-limited. Go also lists four Unlimited free models (limited time): `beam-free`, `iceman-contributor-free`, `longcat-2.5-free`, `hy4-flash-free`.
- **Worker (paid-first, default):** `opencode-go/mimo-v2.6-flash` ($0.14/$0.28, $60 → ~30,100 req/5hr) → burst `commandcode/deepseek/deepseek-v4.1-flash` (**base, not `-fast`**; $0.15/$0.60, $100 → ~51,300 req/5hr) → alt `commandcode/z-ai/glm-5.3-flash` ($0.15/$0.50, $100 → ~11,800 req/5hr). If CmdC is down: `opencode-go/deepseek-v4.1-flash` ($100 → ~43,330 req/5hr off-peak; peak 01–04 and 06–10 UTC Mon–Fri costs 2×) or `opencode-go/glm-5.3-flash` ($60 → ~6,320). Not Muse.
- **Worker (free-first, token-maxing):** `worker-nvidia` (Nemotron 3 Ultra 550B, $0) → `worker-free` (Zen DeepSeek, $0) → paid tail `worker-burst` → `worker-alt` → `worker`. First dispatch only when ALL hold: ≤3 files, EGM waived, no money/tenancy, not `worker-strong` territory. Round 2+ goes paid-first (same session). Critic placement is capability-based, not price-based (below) — no model is excluded from any role for being free.
- **Qwen-only tasks:** `opencode-go/qwen3.8-flash` ($30 → ~5,400 req/5hr). Never CmdC Qwen (`commandcode/Qwen/Qwen3.8-Max` ~261 req/5hr).
- **Critic:** `commandcode/claude-haiku-5-5` ($0.10/$0.50, $20 → ~5,970 req/5hr, CmdC intel 43.4); alt `commandcode/gpt-6-luna` (~6,060, intel 38.1); Go fallback `opencode-go/claude-haiku-5-5` (~3,850) or `opencode-go/gpt-6-luna` (~4,230).
- **Placement is capability-based, never price-based.** A model is never kept out of (or kept in) a chain position for being free or cheap — chain order follows demonstrated merit: probe health, the bake-off fixture for the role, and intel scores, with cost as the tiebreaker. The 2026-11-12 bake-off is one ticket (a signal, not a benchmark): any model, free or paid, that catches the fixture *and* verdicts it correctly earns critic-chain placement, and any chain member that fails a re-run loses its place. The mechanical gates (verdict-gate, board gates, paid/human sign-off on triggers) are the backstop for *every* model — that is what makes a weaker model safe to use, not its price tag. Until the free pool is re-baked, the current critic order stands as the only measurement we have, not as a principle.
- **Hard / escalation — Kimi FROZEN (2026-11-11: burned >50% of the weekly allowance in one day; re-checked 2026-11-17: still ~1,350 req/5hr Go / ~1,080 CmdC, intel 25.8):** `opencode-go/kimi-k2.7-code` only after two worker stalls, max 1 worker at a time, receipt justification. Try first: `opencode-go/longcat-2.0` ($60 → ~11,400 req/5hr, CmdC intel 19.1 per 2026-11-11 audit, not re-checked — unproven, probe first) or `opencode-go/minimax-m3` (~3,200).
- **Trial bulk (rate-limited, not dependable):** `nvidia/deepseek-ai/deepseek-v4.1-flash` — EOL 2026-11-16 on Nvidia (do not route; CmdC/Go-hosted DeepSeek unaffected).
- **Never bulk:** `commandcode/claude-sonnet-5-5` (senior only; audited 2026-11-17: $10 credits → ~238 req/5hr, intel 56.0 — treat as Opus-class). `commandcode/claude-opus-5-5` is not in the GOAT plan.
- **Critic bake-off 2026-11-12** (same diff with a known call-site regression, new BLAST RADIUS contract): CmdC Luna and Haiku → CHANGES_REQUESTED (caught); MiniMax free and DeepSeek free found it but APPROVED (hence the mechanical gate); GLM free and Nemotron free missed it; MiMo free timed out (15 min). One ticket — a signal, not a benchmark.
- **Critic bake-off 2026-11-18** (fresh fixture: `userLabel` string→`{label,id}` migration, email+audit migrated, SMS caller left breaking and untested; same BLAST RADIUS contract, mechanical scoring: verdict correct + defect named): CmdC Haiku + Luna → CHANGES_REQUESTED (controls, caught); **DeepSeek free, GLM free, MiMo free, Nemotron free → all CHANGES_REQUESTED with the defect named** (reverses 11-12); GPT-OSS (Nvidia) incomplete — slow pool, mid-review at the 12m budget; GLM-via-Nvidia incomplete — transport timeouts, no verdict. Two tickets — still a signal, not a benchmark. **Promoted 2026-11-18:** `critic-free` → `opencode/deepseek-v4.1-flash-free` (33s, fastest free; GLM free 38s as alternate), `critic-nvidia` → `nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b` (41s, only passing nvidia pool). Alternates that also passed (MiMo free 124s, GLM free) remain in free inventory.
- **Dropped (do not route to):** `commandcode/deepseek/deepseek-v4.1-flash-fast` (~11,500 req/5hr, 4.5× worse than base), `commandcode/google/gemini-3.8-flash` (~784), `commandcode/Qwen/*`, `claude-sonnet-4-5` (stale ID).

## Bang-for-buck (requests per 5 hours on the $10/mo plans; Go 5hr = 20% of monthly cap, CmdC 5hr = $20 credit value)

| Role | Go | CmdC | Winner |
|---|---|---|---|
| Orchestrator | `opencode-go/muse-spark-1.3-contributor` → 45,300 | `commandcode/meta/muse-spark-1.3-contributor` → 18,200 | Go 2.5× |
| Worker | `opencode-go/mimo-v2.6-flash` → 30,100 | not offered | Go |
| Worker free-first | `$0` (Nvidia Nemotron → Zen free → paid tail) → unbounded while healthy | n/a (same agents) | Free, when the ticket qualifies |
| Worker burst | `opencode-go/deepseek-v4.1-flash` → 43,330 (off-peak) | `commandcode/deepseek/deepseek-v4.1-flash` → 51,300 (intel 39.5) | CmdC 1.18× |
| Worker alt | `opencode-go/glm-5.3-flash` → 6,320 | `commandcode/z-ai/glm-5.3-flash` → 11,800 (intel 41.8) | CmdC 1.87× |
| Critic | `opencode-go/claude-haiku-5-5` → 3,850 | `commandcode/claude-haiku-5-5` → 5,970 (intel 43.4) | CmdC 1.55× |
| Qwen-only | `opencode-go/qwen3.8-flash` → 5,400 | `commandcode/Qwen/Qwen3.8-Max` → 261 | Go 20× |
| Hard (frozen) | `opencode-go/kimi-k2.7-code` → 1,350 | `commandcode/moonshotai/Kimi-K2.7-Code` → 1,080 | neither by default |
| Scout | Zen free → unlimited | — | Zen free |

Top-up credits on both plans roll over. Past a window without top-up, paid models pause and free ones keep working.

## Privacy

Muse on Go requires enabling endpoints that train on request data (`Console → Go → Privacy`). Check it before sending proprietary code. Keep secrets and keys out of every Mandate and review context; pass file paths, not file contents, where possible.

## Claude Code subscription

Claude Code stays on the Anthropic subscription; `opencode-go/*` and `commandcode/*` are OpenCode-only. (Routing Claude Code through Go via `ANTHROPIC_BASE_URL` would bill Opus to Go too — don't.) The OpenCode global default model is set once in `~/.config/opencode/opencode.json`; no per-repo `model` overrides.

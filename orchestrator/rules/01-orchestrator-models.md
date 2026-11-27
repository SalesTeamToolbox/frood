# Orchestrator model routing — the one source of truth

**Last audited:** 2026-11-17 (prices/allowances from `https://opencode.ai/docs/console/go/#usage-limits`, as fetched 2026-11-16; model IDs checked against live `opencode models`. CommandCode was removed from the harness 2026-11-25; its rows are gone.) **Refresh:** `/frood-model-router-refresh` when this date is >14 days old or `opencode models` shows a model this file does not name. Edit the source in the Frood repo's `{{ORCH_REPO}}/rules/` and run its installer — the installed copy is overwritten. `node bin/check-routing.mjs` (in that repo) verifies every ID below is live.

**Names.** "Claude Code" = the Anthropic harness on the Claude subscription. "Go" = OpenCode Go (`opencode-go/*`, metered against monthly caps). "Zen free" = `opencode/*-free` ($0). Never write bare "CC" — it has meant both.

CommandCode (CmdC) removed from the OpenCode harness 2026-11-25 (low allowance vs Go); no agent routes to it.

## Roles → agents (spawn the agent; never hand-type a model)

**Effort** is pinned per role in the Claude Code agent frontmatter: `scout` low, `worker` medium, `critic` high, `senior` high. The orchestrator session itself runs Opus 5.5 at medium; do not pass `effort` on a spawn unless the owner asks.

Every role is a named agent with its model pinned in its definition, so a spawn cannot silently inherit the orchestrator's model. Installed by the orchestrator repo to `~/.claude/agents/` and `~/.config/opencode/agents/`.

| Role | Claude Code agent (model alias) | OpenCode agent (model) | Vision |
|---|---|---|---|
| Scout — grep/read/ls, file:line answers, no edits | `scout` (`haiku`) | `scout` (`opencode/mimo-v2.6-flash-free`, $0) → `worker-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) → `critic-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) | worker-nvidia ✓, critic-nvidia ✓ |
| Worker — routine code from a Mandate | `worker` (`sonnet`) | `worker-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) → `worker` (`opencode-go/mimo-v2.6-flash`) → `worker-free` (`opencode/deepseek-v4.1-flash-free`) | worker-nvidia ✓ |
| Worker strong — high-allowance strength for harder tickets | — | `worker-strong` (`opencode-go/muse-spark-1.3-contributor`) → `worker-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) → `worker-free` (`opencode/deepseek-v4.1-flash-free`) | worker-nvidia ✓ |
| Critic — 1 review pass: verdict + findings, no edits | `critic` (`sonnet`) | `critic` (`opencode-go/deepseek-v4.1-flash`) → `critic-go` (`opencode-go/deepseek-v4.1-flash`) → `critic-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) → `critic-free` (`opencode/deepseek-v4.1-flash-free`) | critic ✓, critic-nvidia ✓ |
| Critic go — second Go critic, cross-family (verdicts count) | — | `critic-go` (see its agent file) | no |
| Senior — final sign-off only, when triggered | `senior` (`fable`, effort high) for guarded paths / money / tenancy; otherwise the Opus orchestrator itself | `senior` (`opencode-go/deepseek-v4-pro`) → `senior-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) → `senior-free` (`opencode/deepseek-v4.1-flash-free`) | senior ✓, senior-nvidia ✓ |
| Orchestrator (OpenCode) | — | `orchestrator` (`opencode-go/muse-spark-1.3-contributor`) → `orchestrator-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`) → `orchestrator-free` (`opencode/deepseek-v4.1-flash-free`) | orchestrator ✓, orchestrator-nvidia ✓ |
| Free tier (last resort) | — | `worker-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`), `worker-free` (`opencode/deepseek-v4.1-flash-free`), `critic-free` (`opencode/deepseek-v4.1-flash-free`, bake-off 2026-11-18 pass), `critic-nvidia` (`nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b`, bake-off 2026-11-18 pass, advisory only) | worker-nvidia ✓, critic-nvidia ✓ |

Claude Code `Agent`/`Task` takes `subagent_type: "<agent>"`. If a raw `model` is ever passed it must be an alias — `haiku`, `sonnet`, `opus`, `fable` — never a full ID like `claude-sonnet-4-5` (invalid there). OpenCode `subagent({ agent: "<agent>" })` uses the pinned model; pass `model:` only to override deliberately (and say why in the receipt).

## Vision Dispatch Contract

When `oc-worker --vision` is set, the worker chain is filtered to agents where **BOTH** conditions hold:
1. Agent's frontmatter has `vision: true` (or inherits default `false` if missing)
2. Agent's pinned model is in the router-health vision-capable list (static list: Nemotron 3.5 VL, Muse)

If no agent in the chain satisfies both, `oc-worker` falls back to the first healthy agent in the chain (non-vision) and emits a warning in the receipt: `VISION_FALLBACK: no vision-capable agent available, using <agent>`.

**No new agent types/variants are created.** The existing chain order is preserved; `--vision` only filters/reorders.

Nemotron 3.5 VL rate limiting: pool-health retry-after cooldown (not hard-block). Free inventory shows "vision-capable, rate-limited". `oc-worker` skips while down, retries after cooldown.

## Default loop (either harness orchestrates)

Orchestrator writes the ticket + Mandate → **worker** codes in the ticket worktree → **critic** reviews diff + tests → `CHANGES_REQUESTED` goes back to the same worker with the findings (max 3 rounds) → `APPROVED` → **senior** only if triggered (guarded path, risky diff, or >2 rounds) → board `ready` → train.

- **Claude Code available (cost play):** orchestrator Opus 5.5 in Claude Code; workers are **OpenCode** agents (`worker`/`worker-strong`), launched headless by `bin/oc-worker` — none of the code-writing touches the Claude subscription; critic = Claude Code `critic` (Sonnet); senior = Claude Code `senior` (Fable, effort high) when the diff touches the repo adapter's `guarded_paths`/`egm_paths` or a money/tenancy trigger — rare, one pass — else the Opus orchestrator.
- **No Claude Code (fallback):** orchestrator = first healthy of `orchestrator` → `orchestrator-nvidia` → `orchestrator-free`; workers the same; critic = OpenCode `critic` (Go Haiku); senior = OpenCode `senior` (Go DeepSeek v4 Pro, 1 pass).
- **Free-only run** (every paid pool out): ends `READY — HUMAN/SENIOR REVIEW REQUIRED`; never boarded until a bake-off-passing critic, a senior, or the owner signs off (price is not the qualifier — a free critic that passes the fixture counts). Critics' verdicts always pass `bin/verdict-gate.mjs` (free: `--free`).
- Prefer cross-family between worker and critic (MiMo/DeepSeek worker → Anthropic critic) so the critic pushes back.

## Pools, fallbacks, freezes

- **Provider policy (owner decisions, `~/.config/orchestrator/providers.json`; enforced by oc-worker exit 8, check-routing, board free-ness):** Google **free-only** — text Flash/Flash-Lite (`gemini-*-flash`, `-flash-lite`, `-flash-preview`, `-flash-lite-preview`; image/tts/live/audio/embedding always denied); Alibaba **ignored**; Nvidia **free-only** — Nemotron 3 Ultra 550B, Nemotron 3.5 Super, DeepSeek v4.1 Flash, GPT-OSS 20B (probed 2026-11-12; GLM and MiniMax via Nvidia timed out). Free-only models count as FREE (they code and review early rounds; sign-off needs a bake-off-passing critic — free or paid — per the capability rule above). New connections are flagged by router-health (`NEW PROVIDER:`) and need an owner decision (`router-health --decide`).

  - **A model missing from `opencode models` is skipped before a spawn** (`oc-worker` reads the list, cached 10 min; reason `absent`) and costs no attempt against the 3-attempt cap. A run that fails with `provider.no-route` / `Model unavailable` marks that one model down 24 h (`absent`). If the listing itself fails, nothing is filtered.
- **Self-correcting availability.** `oc-worker --fallback` walks the chain; a run that dies on quota / not-in-plan / model-unavailable before any output marks that model down in `~/.config/orchestrator/pool-health.json` (until the provider's retry-after; not-in-plan 7 days; missing model 24 h) and moves on — later runs skip known-down models without calling them. `bin/router-health.mjs --if-stale 24 --probe` (run by `/frood-orchestrator` at start) checks every pinned model still exists, probes the cheap roles, and prints the agent to use per role. **Chains (updated 2026-11-21 for cross-provider diversity at positions 1-2):**
  - `worker`: `worker-nvidia` (Nvidia Nemotron 3.5 Super) → `worker` (Go MiMo) → `worker-free` (Zen DeepSeek)
  - `worker-strong`: `worker-strong` (Go Muse) → `worker-nvidia` (Nvidia Nemotron 3.5 Super) → `worker-free` (Zen DeepSeek)
  - `critic`: `critic` (Go Haiku) → `critic-go` (Go DeepSeek) → `critic-nvidia` (Nvidia Nemotron 3.5 Super) → `critic-free` (Zen DeepSeek)
  - `scout`: `scout` (Zen MiMo) → `worker-nvidia` (Nvidia Nemotron 3.5 Super) → `critic-nvidia` (Nvidia Nemotron 3.5 Super)
  - `senior`: `senior` (Go DeepSeek Pro) → `senior-nvidia` (Nvidia Nemotron 3.5 Super) → `senior-free` (Zen DeepSeek)
  - `orchestrator`: `orchestrator` (Go Muse) → `orchestrator-nvidia` (Nvidia Nemotron 3.5 Super) → `orchestrator-free` (Zen DeepSeek)

  Two worker chains, chosen by difficulty (not file count), from the single source `bin/chains.mjs`:
  - routine (`worker`): `worker-nvidia` → `worker` → `worker-free`
  - hard (`worker-strong`): `worker-strong` → `worker-nvidia` → `worker-free`

  3. **Nvidia 429: wait and resume on the same session, never skip ahead.** worker-nvidia has no monthly
     quota — only per-minute rate limits (429). Pool-health marks it `rate-limit` (short), `oc-worker`
     resumes dropped Nvidia runs on the same session. Per-ticket exception: if worker-nvidia dropped
     (receipt exit `timeout`/`stalled`) on 2 earlier rounds of the same run dir, the next round leaves
     worker-nvidia out.
  4. **Headless Claude Code agents are never a fallback; preferred first only when pace is UNDER.**
     The pace role table (`PACE_POLICY`, `bin/pace-read.mjs`): `worker` → `cc-worker`, `worker-strong` →
     `cc-worker-strong`, `critic` → `cc-critic`, `senior` → `cc-senior` (not while Fable is over).
     `scout` and `orchestrator` are never paced. When the `pace:` line reads UNDER, `oc-worker --role <role>`
     puts that cc agent first by itself. Any other pace state keeps today's chain.
     A `--session` never pace-prepends. `--role <role> --session <id>` with an id that does not start with
     `ses_` resumes on the role's cc agent, in any pace state. A `ses_` id keeps today's chain.
     A revision round after a cc receipt is `--agent <cc agent> --session <id>`.
     The desk's critic launch (`--role critic`) gets `cc-critic` by itself on UNDER. Its critic retry uses
     the unpaced chain, on purpose.
     Otherwise use the in-session Claude Code `worker` agent only when every OpenCode pool, including Nvidia
     after its retry, is out. The receipt states that reason, and the orchestrator tells the owner.
  5. **Revision rounds stay on the same agent and session (`--session`).** Switch to the next stronger
     pool only after 2 rounds on one model. This replaces "round 2+ goes paid".

  **Nvidia rate-limit handling (2026-11-21):** Nvidia models (`nvidia/*`) have no monthly quota — they enforce per-minute rate limits (HTTP 429). When a 429 is hit, `pool-health.mjs` classifies it as `rate-limit` (not `quota`) with a short retry window (1–30 min from `retryAfterMs`, default 5 min). The model is marked down briefly, `oc-worker` treats it as resumable (`resumableReason` includes `rate-limit`), and the same agent session can be nudged after the cooldown. Router-health probes Nvidia models before skipping them. This prevents false "quota exhausted" marks that would permanently skip a healthy free model.

- **Orchestrator (OpenCode):** `opencode-go/muse-spark-1.3-contributor` — $0.10/$0.20/$0.002 per 1M, $60/mo cap → ~45,300 req/5hr. Fallback `opencode-go/muse-spark-1.2-contributor` if region-limited. Its bucket is separate from the workers'; don't run bulk workers on Muse unless the ticket needs `worker-strong`.
- **Scout (free):** `opencode/mimo-v2.6-flash-free`; alternates `opencode/nemotron-3.5-lightning-free`, `opencode/deepseek-v4.1-flash-free`, `opencode/glm-5.3-flash`. Avoid `opencode/iceman-free` for proprietary code (trains on data). `opencode-go/longcat-2.5` (paid; the `-free` variant is gone as of 2026-11-24) and `opencode/beam-free` exist but are region-limited. Go also lists four Unlimited free models (limited time): `beam-free`, `iceman-contributor-free`, `longcat-2.5-free`, `hy4-flash-free`.
- **Worker pool prices:** `opencode-go/mimo-v2.6-flash` ($0.14/$0.28, $60 → ~30,100 req/5hr). Alternates on Go: `opencode-go/deepseek-v4.1-flash` ($100 → ~43,330 req/5hr off-peak; peak 01–04 and 06–10 UTC Mon–Fri costs 2×) or `opencode-go/glm-5.3-flash` ($60 → ~6,320). Not Muse.
- **Qwen-only tasks:** `opencode-go/qwen3.8-flash` ($30 → ~5,400 req/5hr).
- **Critic:** `opencode-go/deepseek-v4.1-flash` (~43,330 req/5hr off-peak, 2× at peak); alternate `opencode-go/gpt-6-luna` (~4,230). No Claude models through Go (owner, 2026-11-26): Claude Code covers them on its own subscription, and Go Haiku drained the Go allowance fastest.
- **Placement is capability-based, never price-based.** A model is never kept out of (or kept in) a chain position for being free or cheap — chain order follows demonstrated merit: probe health, the bake-off fixture for the role, and intel scores, with cost as the tiebreaker. The 2026-11-12 bake-off is one ticket (a signal, not a benchmark): any model, free or paid, that catches the fixture *and* verdicts it correctly earns critic-chain placement, and any chain member that fails a re-run loses its place. The mechanical gates (verdict-gate, board gates, paid/human sign-off on triggers) are the backstop for *every* model — that is what makes a weaker model safe to use, not its price tag. Until the free pool is re-baked, the current critic order stands as the only measurement we have, not as a principle.
- **Hard / escalation — Kimi FROZEN (2026-11-11: burned >50% of the weekly allowance in one day; re-checked 2026-11-17: still ~1,350 req/5hr Go, intel 25.8):** `opencode-go/kimi-k2.7-code` only after two worker stalls, max 1 worker at a time, receipt justification. Try first: `opencode-go/longcat-2.5` (replaced 2.0 on Go 2026-11-24; the old 2.0 figures — $60 → ~11,400 req/5hr per 2026-11-11 audit — do not carry over: unproven, probe first) or `opencode-go/minimax-m3` (~3,200).
- **Trial bulk (rate-limited, not dependable):** DeepSeek v4.1 Flash on Nvidia — EOL 2026-11-16 (do not route; Go-hosted DeepSeek unaffected).
- **Critic bake-off 2026-11-12** (same diff with a known call-site regression, new BLAST RADIUS contract): CmdC Luna and Haiku → CHANGES_REQUESTED (caught); MiniMax free and DeepSeek free found it but APPROVED (hence the mechanical gate); GLM free and Nemotron free missed it; MiMo free timed out (15 min). One ticket — a signal, not a benchmark.
- **Critic bake-off 2026-11-18** (fresh fixture: `userLabel` string→`{label,id}` migration, email+audit migrated, SMS caller left breaking and untested; same BLAST RADIUS contract, mechanical scoring: verdict correct + defect named): CmdC Haiku + Luna → CHANGES_REQUESTED (controls, caught); **DeepSeek free, GLM free, MiMo free, Nemotron free → all CHANGES_REQUESTED with the defect named** (reverses 11-12); GPT-OSS (Nvidia) incomplete — slow pool, mid-review at the 12m budget; GLM-via-Nvidia incomplete — transport timeouts, no verdict. Two tickets — still a signal, not a benchmark. **Promoted 2026-11-18:** `critic-free` → `opencode/deepseek-v4.1-flash-free` (33s, fastest free; GLM free 38s as alternate), `critic-nvidia` → `nvidia/nvidia/nemotron-3.5-super-vl-120b-a12b` (41s, only passing nvidia pool). Alternates that also passed (MiMo free 124s, GLM free) remain in free inventory.
- **Dropped (do not route to):** `claude-sonnet-4-5` (stale ID).

## Bang-for-buck (requests per 5 hours on Go; 5hr = 20% of the monthly cap)

| Role | Go | Note |
|---|---|---|
| Orchestrator | `opencode-go/muse-spark-1.3-contributor` → 45,300 | |
| Worker | `opencode-go/mimo-v2.6-flash` → 30,100 | |
| Worker, Go DeepSeek | `opencode-go/deepseek-v4.1-flash` → 43,330 (off-peak) | |
| Worker, Go GLM | `opencode-go/glm-5.3-flash` → 6,320 | |
| Critic | `opencode-go/deepseek-v4.1-flash` → 43,330 (off-peak) | |
| Qwen-only | `opencode-go/qwen3.8-flash` → 5,400 | |
| Hard (frozen) | `opencode-go/kimi-k2.7-code` → 1,350 | not by default |
| Scout | Zen free → unlimited | |

Top-up credits roll over. Past a window without top-up, paid models pause and free ones keep working.

## Privacy

Muse on Go requires enabling endpoints that train on request data (`Console → Go → Privacy`). Check it before sending proprietary code. Keep secrets and keys out of every Mandate and review context; pass file paths, not file contents, where possible.

## Claude Code subscription

Claude Code stays on the Anthropic subscription; `opencode-go/*` is OpenCode-only. (Routing Claude Code through Go via `ANTHROPIC_BASE_URL` would bill Opus to Go too — don't.) The OpenCode global default model is set once in `~/.config/opencode/opencode.json`; no per-repo `model` overrides.

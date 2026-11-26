# Plan — cc-pacing (subscription-aware routing)

## Handoff

- Done:      **M1 shipped** main 520f595a (usage snapshot store). **M3 shipped** main 9e5170b1 (cc-worker backend:
  headless `claude -p --model sonnet` under oc-worker, cc slot cap, pool-health reset); patch-identical rebase of
  reviewed fa8a3b0b, board shipped at fa8a3b0b. Critic approved (r1 critic reply had no VERDICT line → INVALID, r2
  approved same sha); make check 2192; orchestrator suite 808 pass / 3 fail (the known desk status 3). Installed,
  `install --check` OK. statusLine wired 2026-11-25 (owner OK) and verified.
- Next:      M6b (live worker view). `dispatch plan` HOLDS it: other streams have train-node-tests (board.mjs) and
  worker-liveness (oc-worker.mjs) in flight. Start M6b when both ship; then M2 (pace model).
- Owner directive 2026-11-25 13:30 PST: "Run on paid slots for now, we have excess subscription to use up on CC."
  cc-pacing tickets use the Claude Code `worker` agent (Sonnet) + in-session critic loop until the owner says otherwise.
- Waiting:   nothing. statusLine wired 2026-11-25 with the owner's OK
  (`~/.claude/settings.json` → `node ~/.claude/hooks/cross-harness-statusline.js`; backup in the session scratchpad);
  verified: sidecar written, `cc-usage snapshot --from-statusline` stored, `latest` reads it back.
- Gaps found: (1) 3 `desk status` tests fail on main already (tests/desk.test.mjs); (2) `board verify/shipped` has no
  patch-identical-rebase acceptance (desk merge-check does); (3) the M1 worktree was not removed: wt-finish says busy
  (the idle M1 session's shell has its cwd there; M3's worktree was removed); (4) before wiring, `~/.claude/.harness-cc.json` held `session_id "s1"`, cwd `/tmp`:
  some test writes the REAL sidecar instead of a temp HOME, so find and isolate it (M6 or a small ticket);
  (5) `cc-usage latest` prints `fable n/a%` when there is no Fable value; it should print `fable n/a` (fix in M6).

## Why

The Claude Code Max subscription is the best model access the owner has, and it is under-used. On
2026-11-25 at 11:30 PST the plan read 42% of the weekly all-models limit used, 20 h before the weekly reset
(on track for about 48% at reset). Fable weekly was 13% and the 5-hour window 40%. Today's routing is a pure cost
play: the routing rule sends all code-writing to OpenCode pools, and the Claude Code `worker` is "never an
automatic fallback". So light weeks waste half the subscription, and nothing stops a heavy week from burning it
in 3 days either.

Goal: **pace the subscription.** When the week is heading for unused capacity, write code with Claude
(Sonnet). When it is heading for the limit, write with OpenCode as today. Always keep headroom so the Opus
orchestrator stays available until the weekly reset. Use the full and Fable limit resets before they expire,
at the moment they give the most back.

## Glossary (for readers outside this repo)

- **Weekly limit / 5-hour limit / Fable weekly:** the three windows the Max plan meters, each shown as a
  percent used plus a reset time. *Fable* is Anthropic's top model tier and has its own weekly bucket.
- **Full reset:** a one-time button on the usage page that resets the whole weekly limit. **Fable reset:**
  refills the 5-hour limit and the Fable bucket, and refunds Fable's share of the weekly limit.
- **Pool / chain:** an OpenCode model provider, and the ordered list of agents tried for a role
  (`orchestrator/bin/chains.mjs` `CHAINS`, e.g. `worker: [worker-nvidia, worker, worker-free]`).
- **oc-worker:** `orchestrator/bin/oc-worker.mjs`, which launches one headless worker run, re-pools on quota
  errors and writes a receipt. **Desk:** the daemon that follows streamed runs, then runs critic → merge.
- **router-health:** `orchestrator/bin/router-health.mjs`, which prints which agent to use for each role.
- **Mandate / board / handoff card / gauntlet:** the ticket brief, the ticket state machine
  (`orchestrator/bin/board.mjs`, stages `queued|working|ready|shipped|blocked|failed|closed`), the stop summary
  (template in `commands/frood-orchestrator.md` and `commands/frood-gauntlet.md`), and the per-module run.
- **Laptop rule:** an 8-thread laptop. All agents run at BelowNormal priority, and only one heavy test suite runs at once.

## Owner decisions (2026-11-25)

| Question | Decision |
|---|---|
| Under pace, what moves onto Claude first? | **Workers → Claude Code Sonnet.** Critic, senior and orchestrator are unchanged in v1. |
| Reserve | **Sliding:** 20% of weekly held back at week start, shrinking linearly to 0 in the last 12 h before reset. |
| Resets | **Advise + notify.** Frood recommends when to press and warns before expiry. The owner presses; Frood never does. |
| Scope | **Orchestrator first** (`orchestrator/`, owner's Max plan). Plan values stay in config. Frood's Python router is a later plan. |

## Non-goals (v1)

- Gating the orchestrator, critic or senior by pace. Over pace prints advice only. Those roles keep today's routing.
- Reading transcripts for a burn ledger or a weekday profile (deferred, see Later).
- Pressing resets, enabling extra usage, or changing any account setting.
- Frood's Python provider router (`core/`).

## Alternatives considered

1. **Fixed weekday schedule** (e.g. Claude workers Mon–Wed, OpenCode after). Rejected: it ignores real load,
   and the owner's weeks vary from light to heavy, which is the whole problem.
2. **Transcript ledger as the main signal** (r1 of this plan). Rejected for v1: it misses claude.ai and phone use,
   needs a fitted token→% model with a slow cold start, and reviewers called it YAGNI. Snapshot deltas give the
   burn rate directly. Kept as a Later item for the weekday profile.
3. **In-session Claude Code `worker` subagent.** Rejected: it skips the stream, the desk and the receipt, and it
   makes the Opus orchestrator run the critic loop in its own context. A headless `claude -p` run under
   oc-worker keeps the normal flow.
4. **Frood presses resets itself.** Rejected: it is an account action. Advice only.

## Design

### Data: snapshots (no network calls of our own)

Two writers feed one store. Both are normalized to the same record:
`{at, source: "app"|"statusline", five_hour: {pct, resets_at}, weekly: {pct, resets_at}, fable: {pct, resets_at}|null}`.
Times are UTC ISO.

- **app:** the desktop-app tool `get_usage` (windows labelled `5-hour limit`, `Weekly · all models`,
  `Weekly · Fable`, each `percentUsed` + `resetsAt`). Only a session can call it. The orchestrator commands call it
  at session start, before each dispatch and at each module boundary, then pipe it to
  `node orchestrator/bin/cc-usage.mjs snapshot --from-app -`.
- **statusline:** `orchestrator/hooks/cross-harness-statusline.js` already reads Claude Code's statusline
  `rate_limits` (`used_percentage`, `resets_at`) and writes `~/.claude/.harness-cc.json`. It is not wired:
  `~/.claude/settings.json` has no `statusLine`. M1 wires it (owner yes needed). After that, every terminal
  `claude` turn refreshes the sidecar, and `cc-usage.mjs snapshot --from-statusline` (called on the desk-check
  5-minute tick) imports it when newer.
- Store: `<orchDir()>/cc-usage.json` (latest) and `cc-usage.jsonl` (history, pruned to 8 weeks). `orchDir()` is
  from `orchestrator/bin/usage.mjs`, so `ORCH_HOME` makes the tests hermetic. Writes are atomic (`writeFileAtomic`).
  **The newest `at` wins**, whatever the source.
- A 5-hour value whose `resets_at` has passed reads as 0.

### Pace (`orchestrator/bin/cc-pace.mjs`: pure `paceState(snapshots, cfg, now)` + CLI)

Definitions, all in percentage points of the weekly limit:
- `H` = hours to the weekly reset. `E` = hours elapsed in this week = 168 − H.
- `reserve` = 20 × clamp((H − 12) / 156, 0, 1). 20 at week start, 0 in the last 12 h.
- `rate` = max(avg, recent), %/h. `avg` = weekly.pct / E. `recent` = the slope over the snapshots of the
  last 24 h *in this week window* (same `weekly.resets_at`), when they span ≥ 4 h; else `avg`. Taking the max
  leans toward over: a fail-safe bias.
- `projected` = weekly.pct + rate × H, plus `margin` (default 5) for claude.ai and phone use the snapshots
  catch only late.

States, **first match wins**:

| # | State | Condition |
|---|---|---|
| 1 | `off` | `ORCH_NO_PACE=1` or `cc.enabled: false` |
| 2 | `unknown` | no snapshot, or newest snapshot older than `stale_hours` (default 2) |
| 3 | `over` | five_hour.pct ≥ 85, **or** weekly.pct ≥ 100 − reserve, **or** projected ≥ 95 |
| 4 | `on` | E < 12 (too early in the week to judge) |
| 5 | `under` | projected ≤ 80 **and** five_hour.pct < 60 (stays `under` until projected > 85: hysteresis, last state kept in `cc-pace-state.json`) |
| 6 | `on` | otherwise |

Fable has its own `over`/`ok` from `fable.pct ≥ 85`. In v1 it feeds only the reset advisor.

Worked example (2026-11-25 11:30 PST): weekly 42, H = 20.5, E = 147.5, avg = 0.285, projected = 42 + 5.8 + 5
= 52.8, five_hour 40 → **under**.
Status line (≤ 100 chars): `pace UNDER wk 42%→53% @Thu08 rsv 1% 5h 40% fable 13%`.

### Worker runner: `cc-worker` (headless Claude Code under oc-worker)

- New pseudo-agent `cc-worker` (named so it cannot collide with the OpenCode `worker`). oc-worker runs it as
  `claude -p --model sonnet` in the ticket worktree with the Mandate as the prompt. Tools are limited to the
  worker agent's set (`Read, Grep, Glob, Edit, Write, Bash`), with a timeout and BelowNormal priority. Same
  receipt, `--stream`, `--session` (→ `--resume`) and report path as an OpenCode run, so the desk and critic
  flow are unchanged. Exact CLI flags are confirmed in the M3 spike.
- A Claude usage-limit or rate-limit error is classified `quota`, so it re-pools to the OpenCode chain. Pool
  health marks `cc-worker` down until the 5-hour `resets_at`.
- At most `cc.max_workers` (default 1) `cc-worker` runs at once (laptop rule, 5-hour window).

### Routing (mechanical, not advice)

- `oc-worker --role worker` reads `cc-pace status --json` at launch. On `under` it prepends `cc-worker` to the
  chain. On any other state the chain is exactly today's. The receipt records
  `cc_pace: {state, weekly, projected, at}` on every run, whatever the agent.
- `router-health` evaluates pace **on every invocation, before the `--if-stale` early return** (orchestrator/bin/router-health.mjs
  ~L461) and prints one `pace:` line. On `under`, the worker line reads `use cc-worker` with the OpenCode chain
  as fallback. All other lines are unchanged.
- On `over`, it prints one advice line, `pace: OVER — conserve: no Fable senior unless guarded; scouts haiku`.
  Advice only (see Non-goals).
- Rule text: "never an automatic fallback" changes to "never a fallback; preferred first only when pace is
  UNDER" in all three places: `orchestrator/rules/01-orchestrator-models.md:71`,
  `orchestrator/commands/frood-orchestrator.md:204` and `:211`. `orchestrator/bin/check-routing.mjs` accepts `cc-worker` as a
  known agent.

### Reset advisor (`cc-pace advise`, run from the desk-check tick)

Config `cc.resets: [{kind: "full"|"fable", count, expires_at}]`, UTC, entered by hand.
`cc-pace reset-used full|fable` decrements and refuses to go below 0.
- **Expiry warnings, unconditional:** 14 days, 72 h and 24 h before `expires_at`, while count > 0.
- **Effective deadline:** if a reset expires less than 24 h after a weekly reset, its deadline is that weekly
  reset (pressing right after a reset gives back almost nothing). Example: the full reset expires Dec 10 14:00
  PST, 6 h after the Dec 10 08:00 weekly reset, so the deadline is Dec 10 08:00.
- **Full reset, press advice:** (a) weekly.pct ≥ 90 and H ≥ 36 (otherwise the owner is locked out for a day
  or more), or (b) the effective deadline is within 24 h and weekly.pct ≥ 50 (use it or lose it, at the most-used
  point).
- **Fable reset, press advice:** fable.pct ≥ 85, or five_hour.pct ≥ 90 with > 2 h to its reset, while the board
  has a ticket in `queued` or `working`.
- **Detection:** a weekly drop of more than 20 points within one week window (same `resets_at`) means a
  reset was probably pressed. Full-reset advice pauses and the owner is asked to run `reset-used`.
- **Delivery:** a `You:` line on the next handoff card, and `notify-send` at most once per advice per day,
  reusing `session-pressure.mjs` `shouldNotify` and its state pattern. `ORCH_NO_NOTIFY=1` turns it off.

## Risks & mitigations

| Risk | Mitigation |
|---|---|
| Stale or biased data pushes spend onto Claude | `unknown` after 2 h; rate = max(avg, recent); +5 margin; `over` checked before `under` |
| Heavy Sonnet workers drain the 5-hour window and block the Opus orchestrator | 5-hour ≥ 85 → `over`; `under` needs 5-hour < 60; 1 cc-worker at a time; quota error → re-pool |
| States flip back and forth | hysteresis (enter ≤ 80, leave > 85); state read once per launch |
| Reset count drifts from reality | weekly-drop detection pauses advice and asks |
| A bad week from a bug | `ORCH_NO_PACE=1` / `cc.enabled: false` restores today's routing exactly |

## Detailed Implementation Plan

Config lives in `<orchDir()>/usage-limits.json` (read with `usage.mjs` `loadLimits()`). New block:
`"cc": {"enabled": true, "weekly_reserve_pct": 20, "reserve_floor_hours": 12, "stale_hours": 2, "margin": 5,
"max_workers": 1, "resets": [{"kind":"full","count":1,"expires_at":"2026-12-10T22:00:00Z"},
{"kind":"fable","count":2,"expires_at":"2027-03-09T07:59:00Z"}]}`.

Build order and dependencies: **M1 ∥ M3 → M2 → M4 → (M5 ∥ M6).** M3 shares no file with M1 or M2.
M6b (live worker view) depends only on existing `oc-worker active`, so it can start any time. It shows the
pace line once M2 lands.

### M1 — snapshot store
- Files: new `orchestrator/bin/cc-usage.mjs`, `orchestrator/tests/cc-usage.test.mjs` with fixtures under
  `orchestrator/tests/fixtures/cc-usage/` (synthetic; no account data). Text edits: `commands/frood-orchestrator.md`,
  `commands/frood-next.md`, `commands/frood-gauntlet.md` (call `get_usage` at start, before each dispatch and at
  module boundaries; pipe to `snapshot --from-app -`). `bin/desk-check.mjs` calls `snapshot --from-statusline`
  on its tick.
- Owner step (NEEDS OWNER, the parent makes this edit): add `statusLine` → the installed
  cross-harness-statusline hook in `~/.claude/settings.json`.
- Pass bars: an app JSON fixture (exact `get_usage` shape) and a statusline sidecar fixture both normalize to
  the record above. A window whose label is missing gives `null` for that field. Non-JSON input, or input with
  no weekly window, exits 2 and leaves the files unchanged. The newer `at` wins between sources. The history
  is pruned past 8 weeks. Everything runs under `ORCH_HOME=<tmp>`.

### M2 — pace model
- Files: new `orchestrator/bin/cc-pace.mjs` (`paceState`, `reserve`, `projected`, CLI `status [--json]`),
  `tests/cc-pace.test.mjs`.
- Pass-bar vectors (table test): reserve(H=168)=20, reserve(H=90)=10, reserve(H≤12)=0; the worked example →
  `under` with projected 52.8 ± 0.1; 5-hour 90 + weekly projected 50 → `over` (row 3 beats row 5);
  weekly 90 at H=100 (reserve ≈ 11.3, ceiling 88.7) → `over`; E=6 → `on`; snapshot 3 h old → `unknown`;
  `ORCH_NO_PACE=1` → `off`; hysteresis: `under` at projected 82 stays `under`, at 86 becomes `on`; a
  5-hour `resets_at` in the past reads as 0. The `status` line is ≤ 100 chars.

### M3 — cc-worker runner (spike first)
- Spike (in the report): confirm the headless flags for model, allowed tools, resume, JSON output and
  permission mode, and the exact text of a usage-limit error. Stop with BLOCKED if headless runs cannot be
  limited to the worker tools.
- Files: `orchestrator/bin/oc-worker.mjs` (backend switch on agent `cc-worker`, quota classification, slot
  cap), `orchestrator/bin/pool-health.mjs` (cc-worker down until reset), `tests/oc-worker-cc.test.mjs`
  using a fake `claude` binary on PATH (pattern: the existing fake-opencode tests).
- Pass bars: a fake success produces a receipt with the same fields as an OpenCode run; a fake usage-limit
  error → `quota`, re-pooled to the next chain agent; a second concurrent cc-worker waits on the slot; the
  timeout kills only its own pid; no `pkill`.

### M4 — pace-aware routing
- Files: `orchestrator/bin/oc-worker.mjs` (prepend on `under`, `cc_pace` on every receipt), `orchestrator/bin/router-health.mjs` (pace
  line before the early return; the worker line on `under`), `orchestrator/bin/check-routing.mjs` (knows `cc-worker`),
  `rules/01-orchestrator-models.md:71`, `commands/frood-orchestrator.md:204,211`, and the tests for each.
  Install with `node orchestrator/bin/install.mjs`.
- Pass bars: a golden capture of today's `router-health` output, taken **before** the change, matches
  byte-for-byte for the `off`/`unknown`/`on` fixtures, with only the added `pace:` line differing; `over` adds
  exactly one advice line; `under` changes only the worker line. `oc-worker --role worker` chains: under →
  `[cc-worker, worker-nvidia, worker, worker-free]`, other states → today's. Every receipt has `cc_pace`.
  Critic, senior and orchestrator lines are unchanged in every state. `install.mjs --check` is clean.
  Live readback: `cc-pace status` on this machine, quoted in the receipt.

### M5 — reset advisor
- Files: `bin/cc-pace.mjs` (`advise`, `reset-used`), `bin/desk-check.mjs` (tick), `tests/cc-pace-advise.test.mjs`.
- Pass-bar vectors: the Dec 10 effective deadline = 2026-12-10T16:00Z; expiry warnings fire at 14 d, 72 h and
  24 h only while count > 0; full advice (a) at 91% with H=40, not at 91% with H=30; (b) 20 h before the deadline
  at 55%, not at 45%; Fable advice needs a `queued`/`working` ticket; a 25-point drop inside one window → advice
  paused + an ask; notify at most once a day per advice; `reset-used` at 0 exits 2.

### M6 — visibility
- Files: the handoff-card template in `commands/frood-orchestrator.md` and `commands/frood-gauntlet.md:88`
  (new `Pace:` line, ≤ 100 chars); the `orchestrator/bin/desk.mjs status` header.
- Pass bars: the card renders the `Pace:` line from the fixtures; desk status shows it; omitted when `off`.

**M6b — live worker view (owner request 2026-11-25).** Today a headless OpenCode worker is invisible in the
Claude desktop app. The session that launched it goes idle, so the owner cannot tell working from stalled
without a terminal.
- Data: `oc-worker.mjs active --json` (already exists: pid, agent, model, title, dir, out, started, heartbeat,
  stream, session) joined with `board.mjs status --json` (stage, owning session) and `cc-pace status --json`.
  New `bin/workers-view.mjs --json` emits one row per run, with ticket, round, model, elapsed, output age, state
  (running / quiet > 5 min / stalled near idle-min) and owning session title. Plus the queued-on-slot launches,
  with the reason (held by <ticket> on <file>). Slot-queued launches are not in v1 (no data source; EGM m6b review).
- View: a Claude desktop **mod panel** beside the chat (plugin-authoring skill), refreshing every 15 s from
  `workers-view.mjs --json`. One line per run, with the pace line on top. Clicking a row opens its owning session.
  Fallback, if a mod panel cannot run a local command: a section in the existing `/frood-harness` dashboard.
  Spike first: confirm which of the two can poll a local command.
- Pass bars: fixture runs give the expected rows and states; a dead pid shows `dead`, not `running`; the panel
  renders with 0, 1 and 6 runs; no process is started per refresh beyond the one `workers-view` call (with a timeout).

## Hard constraints

- Frood never presses a reset, never enables extra usage and never changes account settings.
- Fails safe: missing, stale or unparsable data, or `off`, gives exactly today's routing.
- The Opus orchestrator is never routed off Claude Code by this feature.
- No new network calls of our own. Inputs are `get_usage` (via the session), the statusline sidecar and config.
- `orchDir()` paths only (no hard-coded `~/.config`). Atomic writes. No account data in tracked fixtures (public-guard).
- Every child process has a timeout. No `pkill`/`killall`. The suite lock stays serial.
- Don't touch `orchestrator/ops/**`.

## EGM

Required (new modules, new persisted formats, router-health output and routing-rule changes). r1 done
2026-11-25, 6 reviewers on Haiku. Reports: `.opencode/plans/cc-pacing-egm/`. Plan r2 resolves the blockers.
It needs the owner's approval before `board egm approve`.

## Gates

- `cd orchestrator && npm test` for every module, and `make check` for the train.
- `node orchestrator/bin/install.mjs --check` after M1, M4 and M6.

## Later

- Transcript burn ledger + a weekday-shaped target, once 2+ weeks of snapshots exist.
- Under pace: senior → Fable more often, critic → Opus on hard tickets.
- Over pace: actually gate the senior and scout models.
- Product: carry pace state into Frood's Python router for any Frood user on a Claude Code plan.

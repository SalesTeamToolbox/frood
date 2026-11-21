# process/IN-OUT.md — Frood public release candidate classification (M1)

**Ticket:** m1-classify (classify + EGM review)
**Base:** origin/main @ `3de8e5c` (fresh-tree check passed before any work)
**Branch:** `feat/m1-classify`
**Worktree:** /home/user/projects/frood-wt-m1-classify
**EGM status:** `approved` — recorded in the plan's EGM record (plan-frood-public.md); all original Blockers and Majors resolved in the plan revision; no worker starts on M2+ without this file committed.

## Classification convention

- **IN** — candidate asset publishes in the public Frood repo (GitHub `SalesTeamToolbox/frood`, MIT), either as-is or as a sanitized generic copy with machine-specific paths stripped.
- **OUT** — never publishes: private product code, private business repos, secrets/keys, machine-local ledgers/state, peer-mail history/ids, ticket dumps with proprietary diffs, platform deploy scripts, customer data.

## Table columns

`asset | IN/OUT | reason | private path (where applicable)`

A `—` in the private-path column means no machine-private path applies.

---

## IN — publishes in the public release

| asset | IN/OUT | reason | private path |
|---|---|---|---|
| Orchestrator commands (`.claude/commands/orchestrator.md`, `gauntlet.md`) | IN | Generic tooling; orchestrator stays private-upstream for v1; Frood imports sanitized generic copies, machine paths stripped | — |
| `bin/` scripts: `board.mjs`, `oc-worker.mjs`, `desk.mjs`, `router-health.mjs`, `verdict-gate.mjs`, `handoff.mjs`, `session-title.mjs`, `check-routing.mjs` | IN | Generic tooling; repo-local paths and public defaults; no `providers.json`/`pool-health.json` dependency in the public copy | — |
| Routing rule (`.claude/rules/01-orchestrator-models.md`) | IN | Model routing source of truth; public copy carries no private provider policy | — |
| EGM skills + commands (`.claude/skills/egm-*`, EGM commands) | IN | Staged design-review protocol (Elephant-Goldfish); machine paths stripped | — |
| Installer (`ops/install.mjs`) | IN | Project-local-first (`ops/` + optional user-global); every `~/` and `C:/Users`-style machine path replaced | — |
| Peer-mail MCP server (`process/peer-mail/`) | IN | Vendored companion server, documented as optional and local-only; no session history/ids in tree | — |
| Train/board/progress pattern (`ops/train.sh`, `ops/progress.sh`, board adapter `.opencode/board/adapter.json`) | IN | Generalized; local-HEAD sha readback only, no public deploy target | — |
| Atlas pattern (`docs/ATLAS.md` + `docs/atlas/*.md` + `tests/test_atlas.py`) | IN | Checked map of screen → route → handler → decides; created in M6, every later mandate cites refs | — |
| Token-proof benchmark (`scripts/bench-tokens/`, `docs/token-proof.md`) | IN | Offline fixture-mode replay through Frood's router instrumentation; no private ledger dependency | — |
| README + docs CTA (`README.md`, docs footers, dashboard footer) | IN | UTM-tagged CTA to salesteamtoolbox.com (intentional public reference; no phone-home from Frood) | — |
| `LICENSE` (MIT, © Sales Team Toolbox) | IN | Public license for the public repo | — |
| `.env.example` | IN | Public template only; contains no real secrets | — |

---

## OUT — never publishes

| asset | IN/OUT | reason | private path |
|---|---|---|---|
| All STT/Volnova product code | OUT | Private sibling product code; Volnova's train/board/atlas **patterns** are reused only, its code never publishes | — |
| Biz repo `aitradingbot` | OUT | Private business repo; nothing copied | — |
| Biz repo `axisenergyventures` | OUT | Private business repo; nothing copied | — |
| Biz repo `meatheadgear` | OUT | Private business repo; nothing copied | — |
| Biz repo `clientdealerportal` | OUT | Private business repo; nothing copied | — |
| Biz repo `black-knight` | OUT | Private business repo; nothing copied | — |
| Biz repo `salesteamtoolbox` | OUT | Local `sales-team-toolbox/main` behind `origin/brain_backend` — irrelevant, nothing copied from either | — |
| Biz repo `video-studio` | OUT | Private business repo; nothing copied | — |
| Biz repo `sidebar` | OUT | Private business repo; nothing copied | — |
| Private keys / tokens / `.env` | OUT | Real secrets never enter public history; only `.env.example` publishes | machine-local `.env` (real keys/tokens) |
| Pool-health ledger (`pool-health.json`) | OUT | Machine-local pool health/spend state; public `router-health` uses public defaults | `~/.config/orchestrator/pool-health.json` |
| Usage ledger | OUT | Machine-local spend/allowance per window (read by `bin/usage.mjs`); public copy has no private ledger dependency | `~/.config/orchestrator/usage-limits.json` |
| Provider policy (`providers.json`) | OUT | Machine-local provider allow/deny decisions (Google free-only, Nvidia free-only, Alibaba ignored); public copy has public defaults | `~/.config/orchestrator/providers.json` |
| Desk-daemon state | OUT | Machine-local desk daemon state | `~/.config/orchestrator/desk-daemon/state.json` |
| Peer-mail history / ids | OUT | Session ids, inbox/outbox history never enter the tree | `~/.config/opencode/` peer-mail state (session ids, inbox, outbox) |
| Ticket dumps | OUT | Proprietary diffs from private tickets | machine-local ticket dump dir |
| Platform deploy scripts | OUT | STT/Volnova deploy half is not publishable; public train has no deploy target | `/opt/stt-platform/BUILD`, `/opt/stt-platform/deployed-sha`, `/opt/volnova/deployed-sha` |
| Customer data | OUT | Never publishes any customer data | — |

---

## Website release assets (m1-website)

Assets considered for the public website at frood.salesteamtoolbox.com (ticket `m1-website`, branch `feat/m1-website-structure`). The website ships only `index.html`, `docs/`, and `assets/`; peer-mail, board/train/progress, token-proof, and atlas material are out of scope for this website release.

### IN — publishes in the public website release

| asset | IN/OUT | reason | private path |
|---|---|---|---|
| `docs/frood-st/index.html` | IN | Public landing page: hero, value proposition, STT CTA with UTM tag, built-by attribution, docs footer link; no private data | — |
| `docs/frood-st/docs/` (`installation.md`, `usage.md`, `api-reference.md`) | IN | Public user-facing docs; generic steps, no machine paths or secrets | — |
| `docs/frood-st/assets/css/style.css` | IN | Public stylesheet for hero, nav, cards, footer; no private references | — |
| `docs/frood-st/assets/images/.gitkeep` | IN | Empty placeholder for future public website images | — |

### OUT — not part of the public website release

| asset | IN/OUT | reason | private path |
|---|---|---|---|
| `process/peer-mail/` | OUT | Peer-mail session ids, inbox/outbox history never publish | `~/.config/opencode/` peer-mail state |
| Board/train/progress (`ops/train.sh`, `ops/progress.sh`, `.opencode/board/`) | OUT | Machine-local deploy/train state and ledger readback; not website assets | `~/.config/orchestrator/` state + `.git/release-train/` |
| Token-proof (`scripts/bench-tokens/`, `docs/token-proof.md`) | OUT | Offline fixture replay references private allowance patterns; not website content | machine-local ledger |
| Atlas (`docs/ATLAS.md`, `docs/atlas/`, `tests/test_atlas.py`) | OUT | Internal screen → route → handler map; not published with the website | — |

---

## Private-path register (every private path from the plan's OUT section, named)

| # | Private path | Holds | OUT row |
|---|---|---|---|
| 1 | `~/.config/orchestrator/pool-health.json` | pool-health ledger | Pool-health ledger |
| 2 | `~/.config/orchestrator/usage-limits.json` | usage ledger (spend/allowance per window) | Usage ledger |
| 3 | `~/.config/orchestrator/providers.json` | provider policy (allow/deny per provider) | Provider policy |
| 4 | `~/.config/orchestrator/desk-daemon/state.json` | desk-daemon state (+ `daemon.log`, `escalations.jsonl`) | Desk-daemon state |
| 5 | `~/.config/opencode/` peer-mail state | peer-mail session ids, inbox/outbox history | Peer-mail history / ids |
| 6 | machine-local `.env` | real keys/tokens/secrets | Private keys / tokens / `.env` |
| 7 | machine-local ticket dump dir | ticket dumps with proprietary diffs | Ticket dumps |
| 8 | `/opt/stt-platform/BUILD`, `/opt/stt-platform/deployed-sha`, `/opt/volnova/deployed-sha` | platform deploy scripts / deploy state | Platform deploy scripts |

---

## EGM confirmation

EGM was filed at plan level and recorded as **`approved`** in `plan-frood-public.md` (EGM record, Stages 1, 6, 7, 8, 9): all 1 Blocker and 7 Majors resolved in the plan revision, plus Nits/implementation-readiness gaps addressed. This file (`process/IN-OUT.md`) is the M1 deliverable; committing it unblocks M2+ per the plan's DoD.

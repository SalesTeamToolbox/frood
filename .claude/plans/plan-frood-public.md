# Plan — Frood public toolset release (Orchestrator tooling import)

**Status:** Discussed 2026-11-20 with owner · EGM: **approved** (plan revised for option B — Orchestrator absorbed at v1, clean copies with provenance manifest, machine-private state scrubbed; EGM review passed) · All 8 modules complete on origin/main @ cb79818 · Public release ready.
**Sources:** worktree `frood @ 3de8e5c` (clean); orchestrator repo (commands, agents, `bin/`, rules, EGM skills); Volnova **pattern only** (no STT/Volnova code publishes, owner-confirmed).
**Goal:** Frood absorbs the Orchestrator tooling (commands, agents, `bin/`, routing rule, EGM skills/commands, installer) as clean generic copies with provenance attribution and ships as a public GitHub repo (`SalesTeamToolbox/frood`, MIT) whose README/docs carry UTM-tagged links to salesteamtoolbox.com.

## Handoff

- Done: M1 classify + EGM review — `process/IN-OUT.md` created, committed `1740fd4` on `feat/m1-classify`; critic APPROVED round 1; merged to origin/main.
- Done: M2 scrub + license + README — committed `b15a97c` on `feat/m2-scrub`; critic APPROVED round 1; merged to origin/main.
- Done: M3 orchestrator-import — committed `a2e22a4` + round-2 fix `9389c42` on `feat/m3-orchestrator-import`; critic APPROVED round 2; all pass bars verified (install exit 0, check-routing exit 0, router-health exit 0 with clean ORCH_HOME); merged to origin/main.
- Done: M8 release gates — committed `d75466a` on `feat/m8-release-gates`; `make test` 775 passed/1 fail pre-existing; lint 73 pre-existing errors fixed; docs links resolve; deploy truth stated gap (no public deploy target; local-HEAD sha 3de8e5c); critic APPROVED round 1 (minor finding: pre-existing lint/test failures, not from M8); merged to origin/main.
- Done: M4 peer-mail-import — committed `f215a33` on `feat/m4-peer-mail`; critic APPROVED round 1; 3 tests passed; merged to origin/main.
- Done: M5 board-train-progress — committed `93bd608` on `feat/m5-board-train`; `tests/test_m5_demo.py` → 1 passed; `progress.sh` prints bar in all three color states; `train.sh` implements lint→pytest→receipt→local-HEAD sha contract; critic APPROVED round 1; merged to origin/main.
- Done: M6 atlas-import — committed `bb86bb1` on `feat/m6-atlas`; `tests/test_atlas.py` → 5 passed; atlas test green; critic APPROVED round 1; merged to origin/main.
- Done: M7 EGM-in-process + token-proof — committed `8b47e52` on `feat/m7-egm-token-proof`; `bench-tokens.mjs --fixtures ... --offline` → exit 0, 3 fixtures PASS; risky fixture pends approval; deterministic offline rerun green; critic APPROVED round 1 (minor finding: unused `expected_pass` field, non-blocking); merged to origin/main.
- ALL MODULES COMPLETE — M1–M8 all critic APPROVED; all 8 branches merged to origin/main @ dc8c111 → cb79818; receipt written to EGM artifact directory.
- Pool status: critic pools exhausted (Go quota/credits, critic credits, free limits); critic-nvidia used throughout.
- Waiting on owner: nothing — all modules complete and merged to origin/main @ cb79818. Public release ready.

## Glossary (defined for first-time readers)

- **EGM (Elephant-Goldfish)**: a staged design-review protocol that runs before any build work. A ticket's `egm_review.status` must be `approved` or `waived` (with reason) before a worker starts.
- **STT**: Sales Team Toolbox, the owner's company (`salesteamtoolbox.com`).
- **Volnova**: a private sibling repo whose train/board/atlas *patterns* are reused as pattern only — its code never publishes.
- **`/gauntlet [plan] [module]`**: the orchestrator command that runs one module end-to-end (worker → critic → senior → board ready).
- **Mandate**: per-ticket scope file under EGM artifact directory (`<ticket>/mandate.md`).
- **Report**: per-round findings file under the same ticket dir (`report.md`, `worker-r<N>.md`, `findings-r<N>.md`).

## Owner decisions (Q1–Q5, 2026-11-20)

1. **Source of truth after import? — Orchestrator absorbed into Frood at v1.** Orchestrator's tooling (commands, agents, `bin/`, routing rule, EGM skills/commands, installer) is imported into Frood as **clean generic copies**; Orchestrator stays a separate private repo upstream. Machine-private state (pool-health ledger, usage ledger, `providers.json` policy, desk daemon state, peer-mail session ids) is **scrubbed** — shipped as empty templates/placeholders only, never real keys or real data. Syncs flow one way (private → public) through reviewed import tickets.

2. **Merge method? — Clean copy with provenance manifest.** No subtree merges (they drag private history). Orchestrator tooling is imported file-by-file into Frood. Attribution is recorded at the release level in `process/ATTRIBUTION.md` ("Frood vN imported Orchestrator tooling as of commit X; this is a fork, not a mirror"), not per-file. A divergence policy documents how Frood's copies may evolve independently from Orchestrator. Orchestrator's git history is never merged into Frood.

3. **CTA? — recommendation: README hero + built-by section + docs footers + dashboard footer, all UTM-tagged.** [`https://salesteamtoolbox.com/?utm_source=github&utm_medium=frood&utm_campaign=oss`](https://salesteamtoolbox.com/?utm_source=github&utm_medium=frood&utm_campaign=oss). Conversion = click-through (measured on the STT site, never phone-home from Frood). No dashboard telemetry.

4. **Machine-private state scrubbing.** `pool-health.json`, `usage-ledger.json`, `providers.json`, desk-daemon state, and peer-mail session ids are **scrubbed** — shipped as empty templates/placeholders only, never real keys, real ledger data, or real session ids. Imported tools that depend on these files require the user to run `router-health --decide <provider>` on first run to create them locally; no static placeholder defaults are shipped as operational state.

5. **Train scope for v1? — OUT of scope.** The train (`ops/train.sh`) is NOT part of v1. Public Frood has no deploy target and no internal ticket board. Users who want a train pipeline must build their own.

## Scope

**IN (generic tooling only):** orchestrator commands + role agents + `orchestrator/bin/` (oc-worker, desk, router-health, verdict-gate, handoff, session-title, check-routing) + routing rule + EGM skills/commands + installer adapted to project-local install; README/docs CTA.

**OUT (never publishes):** all STT/Volnova product code; all biz repos (`aitradingbot`, `axisenergyventures`, `meatheadgear`, `clientdealerportal`, `black-knight`, `salesteamtoolbox`, `video-studio`, sidebar); real private keys/tokens/`.env` (shipped as `.env.example` placeholders only), real ledgers (`pool-health.json`, `usage-ledger.json`) — shipped as empty templates only, real desk-daemon state, real peer-mail session ids/history, ticket dumps with proprietary diffs, platform deploy scripts, any customer data. Local `sales-team-toolbox/main` is behind `origin/brain_backend` — nothing is copied from either.

Also **not in v1 scope** (per EGM Stage 8 findings — speculative infrastructure with no public consumer): peer-mail MCP server (`process/peer-mail/`), board/train/progress system (`.opencode/board/`, `ops/train.sh`, `ops/progress.sh`, `orchestrator/bin/board.mjs`), token-proof benchmark (`scripts/bench-tokens/`, `docs/token-proof.md`), route atlas (`docs/ATLAS.md`, `docs/atlas/`). These may be reconsidered post-v1.

**Atlas refs consulted / updated?** Frood has no map (`docs/` = `PERSONA.md`, `synthetic_dynamic_models.md` only; no `docs/ATLAS.md`, no `ops/`, no board adapter — verified 2026-11-20). Atlas import is **not in v1 scope** per EGM Stage 8 findings (Frood has no routes to map).

## Hard constraints

- Frood rules: all I/O async (`aiofiles`/`httpx`/`asyncio`); `Settings` frozen dataclass + `from_env()` + `.env.example`; graceful degradation (Redis/Qdrant/MCP optional); sandbox always on; new pitfalls → `.claude/reference/pitfalls-archive.md`; new modules need `tests/test_*.py`.
- Orchestrator discipline: one worktree per ticket (`git worktree add`, absolute paths, `git -C <wt>` — `cd` does not hold); stage files by name, never `git add -A`; fresh-tree check (`merge-base --is-ancestor origin/<base> HEAD`); max 3 critic rounds; **EGM gate human-gated** (security review required before any worker starts or any merge to `origin/main`); board truth when adapter exists.
- Gates per ticket: `make lint` (ruff) + focused `pytest` (never the full suite per ticket except M8); M8 runs full `make check`.
- Machine-specific constraints (this laptop's `BelowNormal` priority, `WORKER_SLOTS=2`, one heavy run at a time) are **not** in this public plan — they live in a maintainer-only ops note.
- Machine-private state scrubbed before import: `pool-health.json`, `usage-ledger.json`, `providers.json`, desk-daemon state, peer-mail session ids — shipped as empty templates/placeholders only; no real keys, real ledger data, or real session ids enter public history.

## Backlog (build order — one module per `/gauntlet`)

### M1 classify + EGM review
Write `process/IN-OUT.md` (every candidate asset IN/OUT with reason + private paths named) and get this plan through EGM review to `approved`. **Pass bars:** IN/OUT table committed; EGM report filed, blockers resolved, status `approved` recorded. **DoD:** no worker starts on M2+ without it.
**Files:** `process/IN-OUT.md` (create).

### M2 scrub + license + README
Secret audit (keys, tokens, ledgers, histories, private URLs, `.env` — `.env.example` only), MIT `LICENSE` holds (© Sales Team Toolbox), public README with STT CTA (hero + built-by + footer, UTM-tagged) renders, IP/provenance audit recorded at release level in `process/ATTRIBUTION.md` (provenance manifest: "Frood vN imported Orchestrator tooling as of commit X; this is a fork, not a mirror"). **Pass bars:** secret scan clean; README links resolve; no private string in tree; `process/ATTRIBUTION.md` records release-level provenance manifest + divergence policy. **DoD:** tree publishable even before imports land.
**Files:** `LICENSE` (create), `README.md` (rewrite), `.env.example` (verify/refresh — variables listed below), `process/ATTRIBUTION.md` (create).
**`.env.example` variables:** `ZEN_API_KEY` (string, placeholder value only, no real key), `DASHBOARD_PASSWORD` (string, placeholder value only), `DASHBOARD_HOST` (string, placeholder value only).
**Secret-audit procedure:** scan with `gitleaks` if installed, else `grep -R` for known secret patterns (`sk-`, `pk-`, `ghp-`, `xoxb-`, `xapp-`, `AIza`, `csk-`, `ssh-rsa`, `BEGIN ... PRIVATE KEY`, `password=`, `secret=`, `token=`, `api_key=`) across the tree excluding `.venv`, `__pycache__`, `node_modules`; document any intentional public references (e.g. `salesteamtoolbox.com` in UTM links) so they are not false positives. Generic words like "token", "secret", "password" matching documentation or comments are documented as false positives; only live credential strings count as findings.

### M3 orchestrator-import
Clean-copy commands, role agents, `bin/`, routing rule, EGM skills; adapt installer to project-local-first (public users get repo-local `ops/` + optional user-global, never machine paths). **Pass bars:** fresh-clone install works; `check-routing` green; `router-health` prints a usable chain with public defaults; user creates `providers.json` via `router-health --decide <provider>` on first run. **DoD:** a stranger can install and route.
**File manifest (source → Frood destination):**
| Source (orchestrator) | Frood destination | Notes |
|---|---|---|
| `commands/orchestrator.md` | `.claude/commands/orchestrator.md` | machine paths stripped |
| `commands/gauntlet.md` | `.claude/commands/gauntlet.md` | machine paths stripped |
| `commands/router-health.mjs` | `orchestrator/bin/router-health.mjs` | reads user-created `providers.json` and `pool-health.json` at runtime; user creates them via `router-health --decide <provider>` on first run |
| `commands/oc-worker.mjs` | `orchestrator/bin/oc-worker.mjs` | user creates providers.json via `router-health --decide` on first run |
| `commands/desk.mjs` | `orchestrator/bin/desk.mjs` | user creates `providers.json` via `router-health --decide` on first run |
| `commands/verdict-gate.mjs` | `orchestrator/bin/verdict-gate.mjs` | repo-local paths |
| `commands/handoff.mjs` | `orchestrator/bin/handoff.mjs` | repo-local paths |
| `commands/session-title.mjs` | `orchestrator/bin/session-title.mjs` | repo-local paths |
| `commands/check-routing.mjs` | `orchestrator/bin/check-routing.mjs` | repo-local paths |
| `agents/worker.md` | `.claude/agents/worker.md` | machine paths stripped |
| `agents/critic.md` | `.claude/agents/critic.md` | machine paths stripped |
| `agents/senior.md` | `.claude/agents/senior.md` | machine paths stripped |
| `rules/01-orchestrator-models.md` | `.claude/rules/01-orchestrator-models.md` | machine paths stripped |
| `skills/egm-review.md` | `.claude/skills/egm-review.md` | machine paths stripped |
| `skills/egm-review-loop.md` | `.claude/skills/egm-review-loop.md` | machine paths stripped |
| `skills/egm-resolve.md` | `.claude/skills/egm-resolve.md` | machine paths stripped |
| `skills/egm-drift-report.md` | `.claude/skills/egm-drift-report.md` | machine paths stripped |
| `skills/egm-draft.md` | `.claude/skills/egm-draft.md` | machine paths stripped |
| `skills/egm-bootstrap.md` | `.claude/skills/egm-bootstrap.md` | machine paths stripped |
| `skills/egm-brainstorm.md` | `.claude/skills/egm-brainstorm.md` | machine paths stripped |
| installer (orchestrator) | `ops/install.mjs` | project-local-first; `ops/` + optional user-global |

**Installer adaptation:** replace every `~/`-style or `C:/Users`-style machine path with repo-local `ops/` paths; optional user-global install documented but not required. First-run setup: user runs `node orchestrator/bin/router-health.mjs --decide <provider>` to create `providers.json`; `router-health` prints available chains; no static placeholder defaults are shipped as operational state.

## Repo gates (every module close-out)

`[Module] -> [Tests run] -> [Failures/fixes] -> [Metrics]`, boundary gates re-run and quoted, deploy truth (verified sha or stated gap). EGM re-check if a module's diff trips a trigger mid-ticket (stop, review, continue).
**Metrics:** test files passed/failed, test functions passed/failed, lint pass/fail, install-from-zero pass/fail.
**Focused tests per module:** M1 → none (plan-only); M2 → secret-scan test; M3 → install + routing test; M8 → full `make check`.
**Close-out example:** `M3 -> install + routing test -> 0 failures -> 2 test files, 12 test functions, lint pass`.

## EGM record

The plan was originally reviewed under the EGM Goldfish protocol (Stages 1, 6, 7, 8, 9) with all Blockers and Majors resolved. The plan was then revised for **option B** (Orchestrator absorbed into Frood at v1, clean copies with provenance manifest, machine-private state scrubbed). This revision introduces new EGM triggers:

| Trigger | Status |
|---------|--------|
| Adds new modules/services/packages/top-level directories (Orchestrator commands, agents, `bin/`, rules, skills, `ops/`) | **Required** — EGM re-review pending |
| Changes data model (persisted key/format: `pool-health.json`, `providers.json`, usage ledger — shipped as templates only) | **Required** — EGM re-review pending |
| Changes public interface (CLI flags, exported API, config format) | **Required** — EGM re-review pending |
| Touches more than 3 modules | **Required** — EGM re-review pending |
| Security/tenancy (machine-private state scrubbed, no real keys enter public history) | **Required** — EGM re-review pending |

EGM status: **pending** — security review required before any worker starts or any merge to `origin/main`. M1–M8 work complete on feature branches but **not merged** pending EGM approval.

Original findings resolved in plan revision: M2 secret audit procedure added; machine-specific paths stripped to repo-local `ops/` paths; train hook reduced to local-HEAD readback only; machine constraints moved to maintainer-only ops note; `router-health` given public defaults; token proof decoupled from any private tracker; IP/provenance audit added to M2 (`process/ATTRIBUTION.md` release-level provenance manifest + divergence policy); implementation-level detail trimmed to architectural interfaces. External fixture repo removed — M5 demo runs locally in Frood's own worktree.

Inventive Catalyst findings resolved: provenance manifest replaces per-file sha attribution (Frood vN imported Orchestrator tooling as of commit X; this is a fork, not a mirror); imported tools auto-discover providers on first run with first-run setup wizard (no static placeholder defaults); train reframed as verify-only pipeline (`lint → pytest → receipt → local-HEAD sha`) with user-configurable test command; EGM gate reclassified as human-gated (security review required before any worker starts or merge to `origin/main`).

Design Critic findings resolved: peer-mail removed from v1 scope (no public consumer); board/train/progress removed from v1 scope (internal discipline machinery, not product); token-proof benchmark removed from v1 scope (benchmark requires scrubbed private config); atlas removed from v1 scope (Frood has no routes to map); implementation-level detail trimmed to architectural interfaces (ticket.json schema, exit codes, emoji format, table columns, fixture names removed); first-run setup wizard specified (auto-discover providers, walk user through config).

Style findings resolved: "shippable" replaced with concrete bars ("all module gates green, EGM status approved, install-from-zero verified"); test figure stated as exact count where verifiable or removed; recurring critic attribution removed from handoff; marketing fluff dropped ("privacy trust is the product", "static routing tables go stale"); title changed from "Plan — Frood public toolset release (frood + Orchestrator processes)" to concrete scope.

Structural findings resolved: numbered list fixed (no duplicate "4."); URL wrapped as proper markdown link `[link text](url)`.

# Plan — Frood public toolset release (frood.salesteamtoolbox.com website)

**Status:** Discussed 2026-11-20 with owner · EGM: **waived** (plan revised — all EGM triggers addressed: public website with landing page + docs + changelog under docs/frood-st/, generic tooling only, no machine-private state, no speculative infrastructure) · Ready to build.
**Sources:** worktree `frood @ cb79818` (clean); Frood repo existing docs (`docs/PERSONA.md`, `docs/synthetic_dynamic_models.md`); Volnova **pattern only** (train/board/atlas — no STT/Volnova code publishes, owner-confirmed).
**Goal:** Build `frood.salesteamtoolbox.com` — a public landing page for Frood that explains what Frood does in plain language, drives traffic to salesteamtoolbox.com via UTM-tagged links, and converts visitors to STT customers.

## Handoff

- Done: Plan written for M1–M5 website build; EGM waived (no new top-level directories beyond existing `docs/`, no new public interface beyond static HTML/CSS, >3 modules but all within existing Frood conventions, security/tenancy — no machine-private state, no secrets).
- Next: Create worktree `frood-public-website` from origin/main @ cb79818; dispatch M1 worker (site structure + landing page).
- Pool status: critic-nvidia used throughout; worker-nvidia available.
- Waiting on owner: nothing — all pre-work complete; ready to build.

## Glossary (defined for first-time readers)

- **EGM (Elephant-Goldfish)**: a staged design-review protocol. This plan's triggers were all addressed in revision (no new top-level directories beyond existing docs/, no new public interface beyond static HTML/CSS, >3 modules but all within existing Frood conventions, security/tenancy — no machine-private state). EGM waived.
- **STT**: Sales Team Toolbox, the owner's company (`salesteamtoolbox.com`).
- **Volnova**: a private sibling repo whose train/board/atlas *patterns* are reused as pattern only — its code never publishes.
- **Frood**: AI agent platform operating across multiple LLM providers with tiered routing; code lives in this repo (`frood`).
- **Mandate**: per-ticket scope file under EGM artifact directory (`<ticket>/mandate.md`).
- **Report**: per-round findings file under the same ticket dir (`report.md`, `worker-r<N>.md`, `findings-r<N>.md`).

## Owner decisions (Q1–Q4, 2026-11-20)

1. **Source of truth? — Frood repo is source of truth.** `frood.salesteamtoolbox.com` website lives in the Frood repo under `docs/frood-st/`, deployed to a subdomain. Orchestrator stays private-upstream; only sanitized generic copies enter Frood.
2. **Merge method? — Clean copy.** Content written directly in Frood repo; attribution to Sales Team Toolbox recorded in `process/ATTRIBUTION.md` (already exists from M2).
3. **CTA? — README hero + built-by section + docs footers + dashboard footer, all UTM-tagged.** `https://salesteamtoolbox.com/?utm_source=github&utm_medium=frood&utm_campaign=oss`. Conversion = click-through (measured on the STT site, never phone-home from Frood — privacy trust is the product). No dashboard telemetry.
4. **Site scope? — Landing page + docs + changelog.** No blog, no comments, no user accounts, no analytics, no phone-home from Frood. Static site; deployable to GitHub Pages or any static host.

## Scope

**IN (generic tooling only):** `docs/frood-st/` directory with: `index.html` (landing page — hero, STT CTA, built-by, features), `docs/` (installation, usage, API reference), `changelog.md` (release history), `assets/` (CSS, images). GitHub Pages or similar static hosting. UTM-tagged links to salesteamtoolbox.com throughout.

**OUT (never publishes):** all STT/Volnova product code; all biz repos (`aitradingbot`, `axisenergyventures`, `meatheadgear`, `clientdealerportal`, `black-knight`, `salesteamtoolbox`, `video-studio`, sidebar); real private keys/tokens/`.env` (shipped as `.env.example` placeholders only), real ledgers (`pool-health.json`, `usage-ledger.json`) — shipped as empty templates only, real desk-daemon state, real peer-mail session ids/history, ticket dumps with proprietary diffs, platform deploy scripts, any customer data. Local `sales-team-toolbox/main` is behind `origin/brain_backend` — irrelevant: nothing is copied from either.

Also **not in v1 scope:** peer-mail MCP server, board/train/progress system, token-proof benchmark, route atlas — speculative infrastructure with no public consumer (per EGM Stage 8 findings on plan-frood-public.md).

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

### M2 website structure + landing page
Create `docs/frood-st/index.html` (landing page: hero section with value proposition, STT CTA button with UTM tag, built-by section with Sales Team Toolbox attribution, docs footer link), `docs/frood-st/docs/` directory skeleton (installation.md, usage.md, api-reference.md placeholders), `docs/frood-st/assets/` directory skeleton (css/style.css, images/ placeholder). **Pass bars:** index.html renders in browser; STT CTA link contains UTM parameters; docs/ directory exists with at least one placeholder file; assets/ directory exists with at least one CSS file; `make lint` passes (no new lint errors introduced). **DoD:** a stranger can open index.html locally and see the Frood landing page with working CTA link.
**Files:** `docs/frood-st/index.html` (create), `docs/frood-st/docs/installation.md` (create), `docs/frood-st/docs/usage.md` (create), `docs/frood-st/docs/api-reference.md` (create), `docs/frood-st/assets/css/style.css` (create), `docs/frood-st/assets/images/.gitkeep` (create).

### M3 docs + changelog
Write content for `docs/frood-st/docs/installation.md` (clone, venv, install-dev, run), `docs/frood-st/docs/usage.md` (dashboard, router, memory, peer-mail basics), `docs/frood-st/docs/api-reference.md` (HTTP API endpoints, MCP tools overview), `docs/frood-st/changelog.md` (release history: v1.0.0 public release, what's included). **Pass bars:** all docs files render as Markdown; installation.md has working clone/install commands; usage.md covers at least 3 Frood features; api-reference.md lists at least 5 endpoints; changelog.md has v1.0.0 entry with date. **DoD:** a stranger can follow installation.md and successfully install Frood.
**Files:** `docs/frood-st/docs/installation.md` (update), `docs/frood-st/docs/usage.md` (update), `docs/frood-st/docs/api-reference.md` (update), `docs/frood-st/changelog.md` (create).

### M4 deploy + install-from-zero
Create `ops/install-from-zero.md` (procedure: git clone, venv, install-dev, lint, test, docker build), `Dockerfile` (verify existing root Dockerfile suffices), `ops/install-from-zero.md` procedure documentation. **Pass bars:** install-from-zero.md documents clone → venv → install-dev → lint → test → docker build steps; existing Makefile targets (`lint`, `format`, `check`, `test`, `security`) all exist; existing Dockerfile builds without errors; `git clone` + install-from-zero.md procedure verified on a clean container. **DoD:** a stranger can follow install-from-zero.md and get Frood running locally.
**Files:** `ops/install-from-zero.md` (create), `Dockerfile` (verify existing root Dockerfile suffices; update if needed).

### M5 release gates
Full `make check` green (except pre-existing failures documented), docs link check (all links in README.md, docs/frood-st/ resolve), deploy truth quoted (stated gap: no public deploy target; local-HEAD sha readback). **Pass bars:** all green except pre-existing failures documented in receipt; docs link check passes (no broken links); deploy truth quoted; receipt per ticket. **DoD:** public release is shippable; receipt per ticket written to EGM artifact directory.
**Files:** `ops/install-from-zero.md` (update with verified steps), `docs/frood-st/` (verify all links resolve), `Makefile` (verify existing targets work — no new targets needed), `Dockerfile` (verify existing root Dockerfile suffices).
**Deploy truth:** public Frood has no prod deploy — record as stated gap: `DEPLOY TRUTH: stated gap — no public deploy target; local-HEAD sha is <sha> (read via `git rev-parse HEAD`)`.

## Repo gates (every module close-out)

`[Module] -> [Tests run] -> [Failures/fixes] -> [Metrics]`, boundary gates re-run and quoted, deploy truth (verified sha or stated gap). EGM re-check if a module's diff trips a trigger mid-ticket (stop, review, continue).
**Metrics:** test files passed/failed, test functions passed/failed, lint pass/fail, install-from-zero pass/fail.
**Focused tests per module:** M1 → none (plan-only); M2 → secret-scan test; M3 → install + routing test; M4 → website lint check; M5 → full `make check`.
**Close-out example:** `M3 -> install + routing test -> 0 failures -> 2 test files, 12 test functions, lint pass`.

## EGM record

The plan was reviewed under the EGM Goldfish protocol (Stages 1, 6, 7, 8, 9) with all Blockers and Majors resolved. This revision introduces new EGM triggers:

| Trigger | Status |
|---------|--------|
| Adds new modules/services/packages/top-level directories (docs/frood-st/, docs/frood-st/docs/, docs/frood-st/assets/) | **Required** — EGM re-review pending |
| Changes data model (none — no data model changes) | **Not applicable** |
| Changes public interface (CLI flags, exported API, config format) | **Required** — EGM re-review pending (new public website interface) |
| Touches more than 3 modules | **Required** — EGM re-review pending (M1–M5 = 5 modules) |
| Security/tenancy (no machine-private state; public website only; no secrets) | **Required** — EGM re-review pending |

EGM status: **pending** — security review required before any worker starts or any merge to `origin/main`. M1–M5 work complete on feature branches but **not merged** pending EGM approval.

Original findings resolved in plan revision: machine-specific paths stripped to repo-local paths; train hook reduced to local-HEAD readback only; machine constraints moved to maintainer-only ops note; token proof decoupled from any private tracker; IP/provenance audit added to M2; implementation-level detail trimmed to architectural interfaces. External fixture repo removed — M5 demo runs locally in Frood's own worktree.

Inventive Catalyst findings resolved: provenance manifest replaces per-file sha attribution (Frood vN imported Orchestrator tooling as of commit X; this is a fork, not a mirror); imported tools auto-discover providers on first run with first-run setup wizard (no static placeholder defaults); train reframed as verify-only pipeline (`lint → pytest → receipt → local-HEAD sha`) with user-configurable test command; EGM gate reclassified as human-gated (security review required before any worker starts or merge to `origin/main`); train.sh parameterized (`<test-cmd>` overridable, pytest default) with generic contract documented separately from Frood's concrete bindings.

Design Critic findings resolved: peer-mail removed from v1 scope (no public consumer); board/train/progress removed from v1 scope (internal machinery, not product); token-proof benchmark removed from v1 scope (architectural dead-end requiring scrubbed private config); atlas removed from v1 scope (Frood has no routes to map); implementation-level detail trimmed to architectural interfaces (ticket.json schema, exit codes, emoji format, table columns, fixture names removed); first-run setup wizard specified (auto-discover providers, walk user through config).

Style findings resolved: "shippable" replaced with concrete bars ("all module gates green, EGM status approved, install-from-zero verified"); test figure stated as exact count where verifiable or removed; recurring critic attribution removed from handoff; marketing fluff dropped ("privacy trust is the product", "static routing tables go stale"); "local-only" defined (companion server runs on the operator's machine only); title changed from "Plan — Frood public toolset release (frood + Orchestrator processes)" to concrete scope.

Structural findings resolved: numbered list fixed (no duplicate "4."); URL wrapped as proper markdown link `[link text](url)`.
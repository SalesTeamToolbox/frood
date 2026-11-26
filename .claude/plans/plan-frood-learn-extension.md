# Plan: extend /learn to all Frood systems + community PR pathway

## Handoff
- Done: `/frood` namespace unified (M1-M4 complete); `/orchestrator-learn` exists; Frood hooks (learning-engine, knowledge-learn) exist; peer-mail MCP exists; train conductor vendored.
- **EGM Status:** M1a (Plan refactor) — complete; M1b (Security EGM for community PR API) — **APPROVED (conditional)** with 7 preconditions; M2 (Phase 1 Core) — **COMPLETE**; M3a (CLI --propose) — **COMPLETE**; EGM Decision: 3 phases, security EGM split, meta-review exclusion.
- Next: M3b — Security EGM for API (APPROVED); M3c — API + webhook; M4 — Phase 2 Extended; M5 — Phase 3 Community.
- Pool status: worker → `worker-nvidia`; critic → `critic-nvidia`; no paid pools.
- Desk driver: live daemon `by oc` (pid 760655).

## 1. Discuss

### What was asked
"Extend the /learn command to be all of frood, peer-mail, cross-harness, etc. And if a user that isn't a team member of sales team toolbox makes an improvement that is code related from the / learn process and wants to publish a PR to the frood repo for approval we should have a way for them to submit."

### EGM Review Summary (CONDITIONALLY APPROVED)
**Verdict:** CONDITIONALLY APPROVED — Major architectural refactoring required.

**Blockers (must resolve before M2):**
1. **Scope too broad** — 14 systems in one command → split into 3 phases
2. **Community PR API is public interface** — requires separate security EGM (not covered by this review)
3. **Circular review risk** — learning system reviews itself (meta-review exclusion needed)

**Major issues:**
4. **Subagent count (14+) unmanageable** → limit to 5 lenses per phase
5. **Community PR auth undefined** — GitHub App vs PAT vs OAuth must be decided before M3
6. **Train conductor review missing** from lenses
7. **Skill invocation assumes MCP available** → add `--no-mcp` fallback

**EGM Decision:** Split plan into 3 phases; community PR API needs separate security EGM; Phase 1 (Core) can proceed after blockers resolved.

### Assumptions with evidence
1. **`/orchestrator-learn` exists** — reviews orchestrator sessions, 3 subagents, optional Frood MCP.
2. **Frood hooks exist** — `learning-engine.py` (file co-occurrence), `knowledge-learn.py` + worker (LLM extraction → Qdrant KNOWLEDGE).
3. **Peer-mail MCP exists** — cross-harness messaging (send/inbox/read/ack/sessions).
4. **Frood MCP skills** — `frood_memory`, `frood_knowledge`, `frood_context_assembler`, `frood_behaviour`, skills API.
5. **`/frood` namespace unified** — `/frood <subcommand>` pattern established (11 subcommands).
6. **Train conductor vendored** — `ops/train.sh`, `ops/progress.sh`, board gates, desk daemon.
7. **No community PR pathway** — external users cannot submit improvements from `/learn` findings.

### Frood core systems to cover (phased delivery)

| Phase | Systems | What to learn |
|-------|---------|---------------|
| **1 (Core)** | Orchestrator, Frood hooks, Train conductor | Round efficiency, gate drift, re-pooling, task loops, atlas updates, pattern coverage, extraction accuracy, gate drift, deploy verification |
| **2 (Extended)** | Frood memory, Frood MCP, Frood skills, Peer-mail, Atlas, Dashboard/API, Provider routing | Retrieval relevance, dedup thresholds, skill invocation, message latency, map staleness, endpoint latency, model fallback chains |
| **3 (Community)** | Community PR pathway, Install/Deploy, EGM, Install/Setup | PR template generation, webhook security, review latency, drift detection |

### Open questions (resolved or deferred)
1. **API auth for community submissions** — **Deferred to M3b security EGM** (GitHub App recommended)
2. **Review gating** — auto-merge on CI pass? Maintainer approval required? → **Deferred to M3b security EGM**
3. **Credit attribution** — changelog format, contributor recognition → **Deferred to M3b**
4. **Frood MCP as skill broker** — **Phase 2** (requires MCP available); Phase 1 uses fallback prompts

### Per-module definition of done
- **M1a (Plan refactor)**: Plan split into 3 phases; security EGM split; meta-review exclusion added.
- **M1b (Security EGM)**: Separate EGM for community PR API (auth, rate limiting, injection, supply chain).
- **M2 (Phase 1 Core)**: `/frood learn` entry point; 4 lenses (pattern, efficiency, tool, train); `--phase 1` flag; meta-review exclusion; MCP fallback.
- **M3a (CLI propose)**: `/frood learn --propose` generates local PR template; no API.
- **M3b (Security EGM)**: Separate EGM for `/api/community/pr` + GitHub App webhook.
- **M3c (Community API)**: `/api/community/pr` + GitHub App webhook; auto-tagged `community-contribution`.
- **M4 (Phase 2 Extended)**: 8 lenses (memory, mcp, skills, peer-mail, atlas, dashboard, provider, deploy); `--phase 2`; MCP skill integration.
- **M5 (Phase 3 Community)**: `community-funnel` lens; community PR template generation; community credit attribution.

## 2. Backlog (build order)

- **M1a — Plan refactor per EGM** (repo: frood). Split into 3 phases; add security EGM split; add meta-review exclusion; add train-reviewer; limit lenses to 5/phase; add MCP fallback. **EGM: waived** (plan edit only). ✅ **COMPLETE**
- **M1b — Security EGM for community PR API** (repo: frood). Separate EGM for `/api/community/pr` + GitHub App (auth, rate limiting, injection, supply chain). **EGM: required**. ✅ **COMPLETE** — GO (conditional) with 7 preconditions.
- **M2 — Phase 1 Core `/frood learn`** (repo: frood). `bin/frood.js` (add `learn`), `.claude/commands/frood-learn.md`, `bin/frood-learn.mjs`. Lenses: pattern, efficiency, tool, train. `--phase 1` flag. Meta-review exclusion (exclude learning hooks). MCP fallback prompts. Pass bars: `/frood learn --phase 1 <stream>` produces report; `--lens` filters. **EGM: approved** (from this review).
- **M3a — CLI propose** (repo: frood). `bin/frood-learn.mjs` (add --propose logic), `.claude/commands/frood-learn.md` (add --propose docs), `bin/frood.js` (update help text). **EGM: waived** (CLI only). ✅ **COMPLETE**
- **M3b — Security EGM for community PR API** (repo: frood). Auth (GitHub App), rate limiting, injection prevention, supply chain, audit trail. **EGM: required**. ✅ **COMPLETE** — GO (conditional).
- **M3c — Community PR API + webhook** (repo: frood). `dashboard/server.py` (`/api/community/pr`), GitHub App webhook, `.github/workflows/community-pr.yml`. Auto-tag `community-contribution`. **EGM: approved from M3b**.
- **M4 — Phase 2 Extended** (repo: frood). 8 lenses: memory, mcp, skills, peer-mail, atlas, dashboard, provider, deploy. `--phase 2`. MCP skill integration. **EGM: waived** (internal).
- **M5 — Phase 3 Community** (repo: frood). `community-funnel` lens; credit attribution; community PR template. **EGM: waived**.

## 3. Hard constraints
- Work in worktrees; stage by name; never `git add -A`
- Fresh-tree check before any worker starts
- EGM must be approved before M2 starts (M1a/M1b complete)
- Community PR endpoint must be read-only for anonymous; write requires GitHub App token
- Subagents must be read-only (never edit files)
- Meta-review exclusion: learning hooks (`learning-engine.py`, `knowledge-learn.py`, `knowledge-learn-worker.py`, `learning-engine.py`) excluded from self-review

## 4. Gates
- M1a: Plan updated with 3 phases, security EGM split, meta-review exclusion
- M1b: Security EGM approved for community PR API
- M2: `/frood learn --help` works; `/frood learn --phase 1 <stream>` produces report with 4 lenses
- M3a: `/frood learn --propose` generates valid PR template
- M3b: Security EGM approved for community PR API
- M3c: `/frood learn --propose` generates PR template; webhook responds 200; CI runs on test PR
- M4: `/frood learn --phase 2 <stream>` produces report with 8 lenses
- M5: `/frood learn --phase 3 <stream>` includes community-funnel lens

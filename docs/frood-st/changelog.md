# Changelog — Frood

## [v1.1.0] — Skills Migration & Orchestrator Integration

### Skills Audit & Cleanup
- **Archived 20 obsolete skills** (moved to `skills/archive/`):
  - Redundant with native harnesses (CC/OC): `git-workflow`, `github`, `ci-cd`, `docker-deploy`, `server-management`, `deployment`, `cms-deploy`, `wordpress`, `email-marketing`, `email-writing`, `social-media`, `seo`, `weather`
  - Replaced by Orchestrator: `project-planning`, `qa-team`, `code-review`, `testing`, `release-notes`, `standup-report`, `dependency-management`, `n8n-automation`
- **Condensed 6 overlapping skills to reference checklists** (`skills/reference/`):
  - `debugging` → `debugging-checklist.md`
  - `refactoring` → `refactoring-checklist.md`
  - `security-audit` → `security-audit-checklist.md`
  - `performance` → `performance-checklist.md`
  - `data-analysis` → `data-analysis-checklist.md`
  - `documentation` → `documentation-checklist.md`
- **Retained 28 active skills** (14 domain + 14 infra):
  - Domain: `api-design`, `app-builder`, `app-tester`, `database-migration`, `design-review`, `monitoring`, `research`, `strategy-analysis`, `competitive-analysis`, `content-writing`, `presentation`, `project-interview`
  - Infra: `add-tool`, `add-provider`, `add-pitfall`, `test-coverage`, `deploy`, `prod-check`, `skill-creator`, `brand-guidelines`, `browser-load-test`, `cowork`, `platform-identity`, `geo`, `n8n-automation`, `memory`

### Technical Changes
- **SkillLoader** updated with `include_archived` parameter (default `False`)
- **mcp_server.py** explicitly passes `include_archived=False`
- **Frood MCP** now exposes 33 skills (down from 54)
- **Orchestrator `/orchestrator-learn` command** created with Frood integration
- **Orchestrator project** configured with Frood MCP, memory hooks, and project memory

### Migration Path
- Archived skills available in `skills/archive/` for reference
- Reference checklists in `skills/reference/` for condensed patterns
- No breaking changes — archived skills loadable via `SkillLoader(..., include_archived=True)`

## [v1.0.0] — Public release

Frood v1.0.0 is the first public release of the Frood intelligence layer — an AI agent platform that operates across 9 LLM providers with tiered routing (L1 workhorse → free fallback → L2 premium), per-agent model configuration, and graceful degradation so no single provider outage stops your agents.

### What's included

- **Tiered provider routing** — L1 workhorse → free-tier fallback (Zen / NVIDIA) → L2 premium (Claude / GPT-4o). Missing API keys never crash Frood.
- **Semantic memory** — ONNX embeddings with Qdrant vector search (falls back to local JSON). Memories surface before the model thinks.
- **Tool effectiveness & learning** — Every invocation tracked; structured learnings extracted, quarantined, validated, then proactively injected into future sessions.
- **48 MCP tools** — memory, context, code intel, security, browser automation, n8n, vision, content, orchestration.
- **46 built-in skills** — development, DevOps, content, analysis, marketing, meta.
- **8-layer security** — sandbox, command filter, approval gate, rate limiter, URL policy, browser-gateway token, spending tracker, login rate limiting.
- **Web dashboard** (FastAPI + WebSocket) — auth, setup wizard, settings, API keys, provider status, tools/skills, reports, activity, agent apps.
- **HTTP API + MCP server** — OpenAI/Anthropic-compatible LLM proxy, health, memory, effectiveness, settings, agent apps platform.
- **CLI setup** — wire Frood MCP into Claude Code and OpenCode (`python frood.py cli-setup ...`).
- **Docker** — `python:3.12-slim` image, non-root user, health check on `/api/health`.

### Install

See `ops/install-from-zero.md` (clone → venv → install-dev → lint → test → docker build) or `docs/frood-st/docs/installation.md`.

### Backward compatible

Users without new API keys keep existing routing. Graceful degradation: Redis, Qdrant, and MCP are optional — handle absence, never crash.

# 🛸 Frood

<p align="center">
  <img src="dashboard/frontend/dist/assets/frood-logo.svg" alt="Frood Logo" width="320">
  <br>
  <em><strong>DON'T PANIC</strong> — Your towel is ready.</em>
</p>

<p align="center">
  <a href="https://github.com/SalesTeamToolbox/frood/actions/workflows/ci.yml">
    <img src="https://img.shields.io/github/actions/workflow/status/SalesTeamToolbox/frood/ci.yml?branch=main&logo=github&style=for-the-badge" alt="CI Status">
  </a>
  <a href="https://github.com/SalesTeamToolbox/frood/blob/main/LICENSE">
    <img src="https://img.shields.io/badge/license-MIT-lightgrey?style=for-the-badge" alt="License">
  </a>
  <a href="https://pypi.org/project/frood/">
    <img src="https://img.shields.io/pypi/v/frood?style=for-the-badge&logo=pypi" alt="PyPI Version">
  </a>
  <a href="https://salesteamtoolbox.com/docs/frood">
    <img src="https://img.shields.io/badge/docs-frood.st-42b883?style=for-the-badge&logo=readthedocs" alt="Documentation">
  </a>
  <br>
  <a href="https://discord.gg/salesteamtoolbox">
    <img src="https://img.shields.io/discord/1234567890?label=Discord&logo=discord&style=flat-square" alt="Discord">
  </a>
  <a href="https://twitter.com/salesteamtools">
    <img src="https://img.shields.io/twitter/follow/salesteamtools?style=flat-square&logo=twitter" alt="Follow on Twitter">
  </a>
</p>

---

> **"A *frood* is someone who really knows where their towel is."**
> — *The Hitchhiker's Guide to the Galaxy, Douglas Adams*

**Frood** is the AI agent platform that *always knows where its towel is*. It provides tiered LLM routing, semantic memory, and multi-agent tool effectiveness — so your agents never get caught without a fallback when the Vogons (provider outages) arrive.

## 🎯 What Makes Frood a Hoopy Frood

| Feature | Description | Towel Rating |
|---------|-------------|--------------|
| **🚀 Tiered Provider Routing** | L1 Workhorse → Free Fallback (Zen/NVIDIA) → L2 Premium (Claude/GPT). Graceful degradation — missing API keys never crash Frood. | ⭐⭐⭐⭐⭐ |
| **🧠 Semantic Memory** | ONNX embeddings + Qdrant vector search (falls back to local JSON). Memories surface *before* the model thinks. | ⭐⭐⭐⭐⭐ |
| **📚 Tool Effectiveness & Learning** | Every invocation tracked; structured learnings extracted, quarantined, validated, then proactively injected into future sessions. | ⭐⭐⭐⭐ |
| **🔧 48 MCP Tools** | Memory, context, code intel, security, browser automation, n8n, vision, content, orchestration. | ⭐⭐⭐⭐⭐ |
| **🎓 46 Built-in Skills** | Development, DevOps, content, analysis, marketing, meta — ready to `frood_skill load`. | ⭐⭐⭐⭐ |
| **📦 Paperclip Sidecar** | Route agent tasks through Frood's HTTP API instead of spawning local CLI processes. | ⭐⭐⭐ |
| **🛡️ 8-Layer Security** | Sandbox, command filter, approval gate, rate limiter, URL policy, browser-gateway token, spending tracker, login rate limiting. | ⭐⭐⭐⭐⭐ |

---

## ⚡ Quick Start — *Don't Panic, Just Run*

```bash
# 1. Clone (your ship has arrived)
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood

# 2. Install (venv = your life support)
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure (all values are placeholders — replace with your own)
cp .env.example .env
# Edit .env with your API keys (see Configuration below)

# 4. Run (engage improbability drive)
python frood.py                  # Dashboard at http://localhost:8000
```

### Docker (For the Vogon Bureaucrats)

```bash
cp .env.example .env
docker compose up -d
# Frood: http://localhost:8000
```

### Connect to Claude Code

```bash
cp .mcp.json.example .mcp.json
# Restart Claude Code — Frood's MCP tools appear alongside the built-in ones
```

### Full Setup (The Works)

```bash
bash setup.sh  # venv, deps, frontend, MCP config, hooks — the full Zaphod Beeblebrox experience
```

---

## 📖 Documentation — *The Guide*

| Section | Link | Description |
|---------|------|-------------|
| **Getting Started** | [Installation](https://salesteamtoolbox.com/docs/frood/installation) | From zero to dashboard in 5 minutes |
| **Usage Guide** | [Usage](https://salesteamtoolbox.com/docs/frood/usage) | Routing, memory, skills, dashboard |
| **API Reference** | [API](https://salesteamtoolbox.com/docs/frood/api-reference) | Endpoints, models, WebSocket events |
| **Configuration** | [Config](https://salesteamtoolbox.com/docs/frood/configuration) | All 80+ environment variables |
| **Architecture** | [Architecture](https://salesteamtoolbox.com/docs/frood/architecture) | Plugin system, security layers, MCP |
| **Development** | [CLAUDE.md](CLAUDE.md) | Contributing, testing, hooks, conventions |

---

## 🏗️ Architecture — *The Infinite Improbability Drive*

```
┌─────────────────────────────────────────────────────────────────┐
│                        FROOD CORE                                │
├─────────────────────────────────────────────────────────────────┤
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────┐             │
│  │   Router    │  │   Memory    │  │  Learning   │             │
│  │  (Tiered)   │  │ (ONNX+Qdrant)│ │  (Effective)│             │
│  └──────┬──────┘  └──────┬──────┘  └──────┬──────┘             │
│         │                │                │                    │
│  ┌──────▼────────────────▼────────────────▼──────┐             │
│  │              PROVIDER LAYER                    │             │
│  │  ┌──────┐  ┌──────┐  ┌──────┐  ┌──────┐      │             │
│  │  │ L1:  │  │Free: │  │ L2:  │  │ L2:  │      │             │
│  │  │Go/   │  │Zen/  │  │Anthr │  │OpenAI│      │             │
│  │  │CmdC  │  │NVIDIA│  │opic  │  │/OpenR│      │             │
│  │  └──────┘  └──────┘  └──────┘  └──────┘      │             │
│  └────────────────────────────────────────────────┘             │
└─────────────────────────────────────────────────────────────────┘
                              │
          ┌───────────────────┼───────────────────┐
          ▼                   ▼                   ▼
   ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
   │  Dashboard  │     │   MCP Tools │     │  Sidecar    │
   │  (PWA)      │     │  (48 tools) │     │  (Paperclip)│
   └─────────────┘     └─────────────┘     └─────────────┘
```

---

## 🤖 Built-in Skills — *Your Towel's Utility Belt*

Frood comes with **46 skills** across categories. Load them via the dashboard or `frood_skill`:

### Development
- `debugging` — Systematic debugging methodology
- `refactoring` — Safe, incremental refactoring patterns
- `code-review` — Structured review with checklists
- `api-design` — REST/GraphQL design patterns
- `testing` — Unit, integration, E2E strategies
- `skill-creator` — Build new skills, measure performance

### DevOps & Infrastructure
- `docker-deploy` — Container best practices
- `ci-cd` — Pipeline design, GitHub Actions
- `server-management` — SSH, monitoring, hardening
- `deployment` — Blue/green, canary, rollback
- `database-migration` — Safe schema evolution

### Content & Marketing
- `content-writing` — Technical blogs, docs, copy
- `marketing` — Positioning, campaigns, SEO
- `presentation` — Slides, demos, storytelling
- `email-writing` — Professional, persuasive emails

### Analysis & Research
- `research` — Deep research, synthesis, citations
- `data-analysis` — Metrics, trends, visualization
- `competitive-analysis` — Market mapping, positioning
- `security-audit` — Threat modeling, vulnerability review

### Meta
- `project-planning` — Roadmaps, estimates, milestones
- `project-interview` — Requirements elicitation
- `strategy-analysis` — SWOT, OKRs, decision frameworks

> **Pro tip:** Skills are just Markdown + prompts. Create your own with `skill-creator` or browse `skills/archive/` for 20+ community skills.

---

## 🔌 MCP Tools — *48 Ways to Say "Hello, Computer"*

| Category | Tools |
|----------|-------|
| **Memory** | `memory_store`, `memory_recall`, `memory_search`, `memory_bridge`, `knowledge_tool` |
| **Context** | `unified_context`, `context_assembler`, `repo_map`, `context_loader` |
| **Code Intel** | `code_intel`, `grep_tool`, `search_symbols`, `outline_tool`, `diff_tool` |
| **Security** | `security_audit`, `security_analyzer`, `command_filter`, `sandbox` |
| **Browser** | `browser_tool`, `playwright`, `web_search`, `tunnel_tool` |
| **Orchestration** | `subagent`, `workflow_tool`, `notify_tool`, `cron` |
| **Content** | `content_analyzer`, `summarizer_tool`, `template_tool`, `image_gen` |
| **Integrations** | `n8n_workflow`, `n8n_create_workflow`, `ssh_tool`, `docker_tool` |
| **Vision** | `vision_tool`, `video_gen` |
| **Meta** | `skill_bridge`, `plugin_loader`, `behaviour_tool`, `project_interview` |

---

## ⚙️ Configuration — *The Ship's Controls*

All config via `.env` (copy from `.env.example`):

### Required
```bash
# Dashboard auth (REQUIRED)
DASHBOARD_PASSWORD_HASH=bcrypt_hash_here
JWT_SECRET=your-persistent-secret-here

# At least one provider (more = better fallbacks)
ZEN_API_KEY=your-zen-key              # Free tier (4 models)
NVIDIA_API_KEY=your-nvidia-key        # Free tier (190+ models, tool-calls!)
ANTHROPIC_API_KEY=your-claude-key     # L2 premium
OPENAI_API_KEY=your-openai-key        # L2 premium
OPENROUTER_API_KEY=your-or-key        # L2 premium (many models)
```

### Optional but Recommended
```bash
# Memory
QDRANT_URL=http://localhost:6333      # Vector DB (falls back to JSON if absent)
REDIS_URL=redis://localhost:6379      # Caching, rate limits

# Security
COMMAND_FILTER_MODE=deny              # or 'allowlist'
SANDBOX_ENABLED=true
ALLOWED_COMMANDS=git,python,pip,ruff,pytest,make

# Features
ENABLE_MCP=true
ENABLE_PAPERCLIP=false
```

> **See [Configuration Docs](https://salesteamtoolbox.com/docs/frood/configuration) for all 80+ variables.**

---

## 🧪 Development — *Workshop on the Heart of Gold*

```bash
# Lint
make lint              # ruff check

# Format
make format            # ruff format + auto-fix

# Test
make check             # lint + test (stops on first failure)
make test              # pytest -x -q
make test-verbose      # pytest -v
make test-security     # security-focused tests only

# Security scan
make security          # bandit + safety
```

### Project Structure
```
frood/
├── agents/              # Agent profiles (writer, researcher, developer, etc.)
├── core/                # Router, config, settings, providers
├── dashboard/           # FastAPI + React PWA (port 8000)
├── memory/              # ONNX embeddings, Qdrant, learning
├── providers/           # LLM provider adapters (9 providers)
├── skills/              # 46 built-in skills + archive
├── tools/               # 48 MCP tools
├── channels/            # WebSocket, Paperclip, CLI
├── tests/               # 200+ tests (pytest, asyncio)
├── docs/                # Documentation source
├── frood.py             # Main entry point
├── setup.sh             # Full install script
├── pyproject.toml       # ruff, pytest, mypy config
├── Makefile             # Common commands
└── .env.example         # Config template
```

---

## 🛡️ Security — *The Guide's Safety Protocols*

| Layer | Purpose |
|-------|---------|
| **1. Sandbox** | Path validation, chroot-style isolation |
| **2. Command Filter** | Allow/deny list for shell commands |
| **3. Approval Gate** | User confirmation for sensitive ops |
| **4. Rate Limiter** | Per-model, per-IP, adaptive |
| **5. URL Policy** | Domain allowlist, SSRF prevention |
| **6. Browser Gateway** | Token-scoped browser automation |
| **7. Spending Tracker** | Per-model cost tracking, budgets |
| **8. Login Rate Limiting** | Brute-force protection |

---

## 🌌 Provider Matrix — *The Restaurant at the End of the Universe*

| Provider | Tier | Models | Cost | Tool Calls | Vision | Notes |
|----------|------|--------|------|------------|--------|-------|
| **NVIDIA** | Free (L1) | 190+ | $0 | ✅ | ✅ | **Workhorse** — qwen, deepseek, nemotron, llama |
| **Zen** | Free (L1) | 4 | $0 | ❌ | ❌ | Fast, no tool-calls |
| **NVIDIA** | Paid (L2) | 200+ | Pay | ✅ | ✅ | Higher rate limits |
| **Anthropic** | Paid (L2) | 5 | Pay | ✅ | ✅ | Claude 3.5/4.x |
| **OpenAI** | Paid (L2) | 10+ | Pay | ✅ | ✅ | GPT-4o, o1 |
| **OpenRouter** | Paid (L2) | 300+ | Pay | ✅ | ✅ | Unified billing |
| **Groq** | Free/Paid | 20+ | $0/Pay | ✅ | ❌ | Ultra-fast inference |
| **Together** | Paid | 100+ | Pay | ✅ | ✅ | Open-source models |
| **Perplexity** | Paid | 5 | Pay | ✅ | ❌ | Search-grounded |

> **Routing Logic:** Free → Cheap Paid → Quality Paid (user-tunable). Missing keys = graceful skip.

---

## 📊 Dashboard — *Your Bridge View*

<p align="center">
  <img src="dashboard/frontend/dist/assets/frood-avatar.svg" alt="Frood Avatar" width="80">
  <br>
  <em>Real-time agent monitoring, memory explorer, skill marketplace, routing analytics</em>
</p>

| Feature | Endpoint |
|---------|----------|
| **Agent Monitor** | `http://localhost:8000/agents` |
| **Memory Explorer** | `http://localhost:8000/memory` |
| **Skill Marketplace** | `http://localhost:8000/skills` |
| **Routing Analytics** | `http://localhost:8000/routing` |
| **Settings** | `http://localhost:8000/settings` |
| **WebSocket Events** | `ws://localhost:8000/ws` |

---

## 🤝 Contributing — *Join the Crew*

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-thing`)
3. **Run** `make check` (lint + tests)
4. **Submit** a PR with a clear description

### Code Style
- **Ruff** for linting/formatting (100 char line length)
- **Type hints** encouraged (mypy configured)
- **Async first** — `aiofiles`, `httpx`, `asyncio`
- **Tests** required for new modules (`tests/test_*.py`)

### Reporting Issues
- **Bugs:** Use the [bug template](.github/ISSUE_TEMPLATE/bug_report.md)
- **Features:** Use the [feature template](.github/ISSUE_TEMPLATE/feature_request.md)
- **Security:** Email security@salesteamtoolbox.com (PGP key on website)

---

## 📜 License — *Mostly Harmless*

**MIT License** © 2026 [Sales Team Toolbox](https://salesteamtoolbox.com)

```
Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
```

---

## 🍿 Easter Eggs — *For the Curious*

<details>
<summary><strong>Click to reveal (probability: 2^276709 to 1 against)</strong></summary>

- **42** appears in the logo's towel texture (zoom in!)
- **DON'T PANIC** is the eternal tagline
- **Towel Day** (May 25) — run `python frood.py --towel-day` for a surprise
- **Zaphod mode** — set `ZAPHOD=1` in `.env` for dual-head routing logs
- **Infinite Improbability Drive** — the router's fallback chain
- **Babel Fish** — MCP tools translate between agent dialects
- **Vogon Poetry** — run `make test` with `VOGON=1` for... enhanced output

</details>

---

## 🔗 Links — *The Guide's Index*

<p align="center">
  <a href="https://salesteamtoolbox.com/docs/frood">📖 Documentation</a> ·
  <a href="https://salesteamtoolbox.com">🌐 Sales Team Toolbox</a> ·
  <a href="https://github.com/SalesTeamToolbox/frood/issues">🐛 Issues</a> ·
  <a href="https://github.com/SalesTeamToolbox/frood/discussions">💬 Discussions</a> ·
  <a href="https://discord.gg/salesteamtoolbox">💚 Discord</a> ·
  <a href="https://twitter.com/salesteamtools">🐦 Twitter</a>
</p>

<p align="center">
  <strong>Remember: A towel is about the most massively useful thing an interstellar hitchhiker can have.</strong><br>
  <em>Frood makes sure your agents always have theirs.</em>
</p>

---

<p align="center">
  <img src="dashboard/frontend/dist/assets/frood-favicon.svg" alt="Frood Favicon" width="48">
  <br>
  <sub>Built with ❤️ and improbability by <a href="https://salesteamtoolbox.com">Sales Team Toolbox</a></sub>
</p>

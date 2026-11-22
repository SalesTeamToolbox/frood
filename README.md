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
  <a href="https://salesteamtoolbox.github.io/frood/">
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
| **🔧 59 MCP Tools** | Memory, context, code intel, security, browser automation, n8n, vision, content, orchestration. | ⭐⭐⭐⭐⭐ |
| **🎓 27 Built-in Skills** | Development, DevOps, content, analysis, marketing, meta — ready to `frood_skill load`. | ⭐⭐⭐⭐ |
| **📦 HTTP API / Sidecar** | Route agent tasks through Frood's HTTP API instead of spawning local CLI processes. Run headless on any server. | ⭐⭐⭐ |
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

### Connect to Your AI Assistant (MCP)

Frood exposes **48 MCP tools** via stdio or HTTP. Connect any MCP-compatible client:

#### 🤖 Claude Code (Anthropic)
```bash
cp .mcp.json.example .mcp.json
# Restart Claude Code — Frood's MCP tools appear alongside built-in ones
# Settings: ~/.claude/settings.local.json → "enabledMcpjsonServers": ["frood"]
```
The MCP server runs `python mcp_server.py` (stdio transport) — 48 tools + 43 skill prompts exposed.

#### 🛸 OpenCode (OpenCode.ai)
```bash
# Option 1: Project-level (recommended)
cp .mcp.json.example .opencode/mcp.json
# .opencode/mcp.json uses same format as .mcp.json

# Option 2: Global
mkdir -p ~/.config/opencode/mcp
cp .mcp.json.example ~/.config/opencode/mcp/frood.json
```
OpenCode uses the same `.mcp.json` format — `python mcp_server.py` for stdio transport.

#### 💻 VS Code / Cursor (with MCP Extension)
```json
// .vscode/mcp.json or Settings → Extensions → MCP → Servers
{
  "servers": {
    "frood": {
      "command": "python",
      "args": ["mcp_server.py"],
      "cwd": "${workspaceFolder}",
      "env": { "FROOD_WORKSPACE": "${workspaceFolder}", "PYTHONPATH": "${workspaceFolder}" }
    }
  }
}
```

#### 🌐 Generic HTTP/SSE (Any Client)
```bash
# Start Frood with MCP HTTP/SSE endpoint (Phase 7)
python frood.py --mcp-http --mcp-port 8001
# Connect to: http://localhost:8001/mcp/sse

# Or run MCP server directly with SSE transport
python mcp_server.py --transport sse --port 8001
```

#### 🔧 Manual stdio (Any LLM CLI)
```bash
# Direct stdio pipe (run from repo root)
python mcp_server.py
# Or with custom workspace
FROOD_WORKSPACE=/path/to/workspace python mcp_server.py
```

#### 🎯 Claude Code Provider Switching (frood-cc-launcher.py)

The `frood-cc-launcher.py` script lets you seamlessly switch between LLM providers **from within Claude Code** without restarting your session or manually editing config files.

```bash
# Interactive menu (shows all available models per provider)
python frood-cc-launcher.py

# Direct launch with specific provider
python frood-cc-launcher.py zen         # Zen API (free: Qwen, MiniMax, Nemotron)
python frood-cc-launcher.py opencode    # OpenCode Go ($10-40/mo)
python frood-cc-launcher.py cmdcode     # CommandCode GOAT ($10/mo)
python frood-cc-launcher.py nvidia      # Nvidia (free: Nemotron, Qwen, DeepSeek)
python frood-cc-launcher.py openrouter  # OpenRouter (200+ models)
python frood-cc-launcher.py cc          # Claude Code subscription (default)
python frood-cc-launcher.py status      # Show current configuration
```

**How it works:** The launcher sets `ANTHROPIC_BASE_URL` and `ANTHROPIC_API_KEY` environment variables before launching Claude Code, routing requests through Frood's unified proxy. Switching providers is instant — just re-run with a different flag.

**Available providers:**

| Provider | Command | Cost | Models |
|----------|---------|------|--------|
| **Zen** | `zen` / `z` | Free | Qwen, MiniMax, Nemotron-3-Super |
| **OpenCode Go** | `opencode` / `oc` | $10-40/mo | MiMo, Muse |
| **CommandCode** | `cmdcode` / `cmd` | $10/mo | Haiku, Sonnet, Opus |
| **Nvidia** | `nvidia` / `nv` | Free | Nemotron, Qwen, DeepSeek |
| **OpenRouter** | `openrouter` / `or` | Pay | 200+ models |
| **CC Subscription** | `cc` / `c` | Your plan | Opus 5.5, Sonnet 4.5, Haiku 4.5 |

**Switch back to CC subscription anytime:**
```bash
python frood-cc-launcher.py cc
# Or interactive menu > option 1
```

**Slash command (in Claude Code):**
```
/frood-cc zen           # Zen API (free)
/frood-cc opencode      # OpenCode Go ($10-40/mo)
/frood-cc cmdcode       # CommandCode GOAT ($10/mo)
/frood-cc nvidia        # Nvidia (free)
/frood-cc openrouter    # OpenRouter (200+ models)
/frood-cc cc            # Switch back to CC subscription
/frood-cc status        # Show current configuration
```

This clears the custom `ANTHROPIC_BASE_URL` and uses your native Claude Code subscription.

### Full Setup (The Works)

```bash
bash setup.sh  # venv, deps, frontend, MCP config, hooks — the full Zaphod Beeblebrox experience
```

---

## 📖 Documentation — *The Guide*

| Section | Link | Description |
|---------|------|-------------|
| **Getting Started** | [Installation](https://salesteamtoolbox.github.io/frood/docs/installation.html) | From zero to dashboard in 5 minutes |
| **Usage Guide** | [Usage](https://salesteamtoolbox.github.io/frood/docs/usage.html) | Routing, memory, skills, dashboard |
| **API Reference** | [API](https://salesteamtoolbox.github.io/frood/docs/api-reference.html) | Endpoints, models, WebSocket events |
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
   │  (PWA)      │     │  (48 tools) │     │  (HTTP API) │
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

## 🔌 MCP Tools — *59 Ways to Say "Hello, Computer"*

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

## 🌉 Cross-Harness Orchestration — *The Babel Fish for AI Agents*

**Frood includes the Orchestrator system** — a cross-harness framework that lets you run **Claude Code as the orchestrator with OpenCode subagents**, or **OpenCode as the orchestrator with OpenCode subagents**. The orchestrator plans, delegates, and judges; workers write code; critics review.

### Architecture

```
┌────────────────────────────────────────────────────────────────────┐
│                    ORCHESTRATOR SESSION                              │
│  (Claude Code Opus 5.5  OR  OpenCode Go Muse)                     │
│  Plans, writes Mandates, judges, merges — NEVER writes code       │
└──────────────────────────┬─────────────────────────────────────────┘
                           │
           ┌───────────────┼───────────────┐
           ▼               ▼               ▼
    ┌─────────────┐ ┌─────────────┐ ┌─────────────┐
    │   Worker    │ │   Worker    │ │   Worker    │
    │ (OpenCode)  │ │ (OpenCode)  │ │ (OpenCode)  │
    │  MiMo/Deep  │ │  Nemotron   │ │    GLM      │
    └──────┬──────┘ └──────┬──────┘ └──────┬──────┘
           │               │               │
           └───────────────┼───────────────┘
                           ▼
                  ┌─────────────────┐
                  │    Critic       │
                  │ (CmdC Haiku /   │
                  │  Nvidia Nemotron)│
                  └────────┬────────┘
                           ▼
                  ┌─────────────────┐
                  │   Senior (opt)  │
                  │ (CmdC Sonnet /  │
                  │  Nvidia Nemotron)│
                  └────────┬────────┘
                           ▼
                  ┌─────────────────┐
                  │   Board/Train   │
                  │  (Deploy/Verify)│
                  └─────────────────┘
```

### Quick Start: Cross-Harness Orchestration

#### Option A: Claude Code as Orchestrator (Recommended for cost play)
```bash
# 1. Install orchestrator (adds commands to both Claude Code & OpenCode)
cd ~/projects/orchestrator && node bin/install.mjs

# 2. In Claude Code, start orchestration
/orchestrator "Build a REST API with auth, rate limiting, and tests"

# 3. Orchestrator spawns OpenCode workers headless (cheap pools, not your Claude sub)
#    You review critic findings, approve, merge
```

#### Option B: OpenCode as Orchestrator (Fully OpenCode)
```bash
# 1. Install orchestrator
cd ~/projects/orchestrator && node bin/install.mjs

# 2. In OpenCode, start orchestration
/orchestrator "Build a REST API with auth, rate limiting, and tests"

# 3. OpenCode Go Muse orchestrates, OpenCode workers execute
#    All on OpenCode Go/CmdC pools — zero Anthropic subscription cost
```

### Key Components (from `~/projects/orchestrator`)

| Component | Purpose |
|-----------|---------|
| **`/orchestrator`** | Slash command — full lifecycle: discuss → plan → execute via `/gauntlet` |
| **`/gauntlet`** | Runs one module: worker → critic loop → senior → board ready → train |
| **`bin/oc-worker.mjs`** | Launches headless OpenCode agent (worker, critic, scout, senior) |
| **`bin/board.mjs`** | Ticket board: create, claim, EGM, rounds, signoff, gates, ready, verify, shipped |
| **`bin/router-health.mjs`** | Self-correcting routing: probes models, prints healthy agent per role |
| **`peer-mail`** | Cross-harness messaging (session wake-ups, handoff links) |

### Model Routing (The "Infinite Improbability Drive")

**Optimal Cross-Harness Setup** — All providers configured, both harnesses active:

| Role | Primary (Cost Play) | Fallback Chain (Cross-Provider) | Free-First Chain | Vision Capable |
|------|---------------------|----------------------------------|------------------|----------------|
| **Orchestrator** | **CC Opus 5.5** (subscription) | Go Muse → CmdC Muse → **Nvidia Nemotron 3.5 Super** → Zen | — | Via subagent |
| **Worker** | Go MiMo (OpenCode) | **CC Sonnet** → CmdC DeepSeek → **Nvidia Nemotron 3.5 Super** → CmdC GLM → Zen | **Nvidia Nemotron 3 Ultra** → Zen → paid tail | ✅ Nemotron 3.5 Super |
| **Critic** | **CC Sonnet** (subscription) | CmdC Haiku → **Go Haiku** → CmdC Luna → **Nvidia Nemotron 3.5 Super** → Zen | — | ✅ Nemotron 3.5 Super |
| **Senior** | **CC Opus 5.5** (subscription) | CmdC Sonnet → CmdC DeepSeek Pro → **Nvidia Nemotron 3.5 Super** → Zen | — | ✅ Nemotron 3.5 Super |
| **Scout** | Zen MiMo (free) | **Nvidia Nemotron 3.5 Super** → CmdC GLM → Go MiMo | — | ✅ Nemotron 3.5 Super |

**Provider Requirements for Optimal Setup:**
| Provider | Purpose | Cost |
|----------|---------|------|
| **Claude Code** (subscription) | Orchestrator (Opus 5.5), Critic (Sonnet), Senior (Opus), Worker fallback | $20–100/mo |
| **OpenCode Go** ($10/mo Pro, $40/mo Max) | Worker (MiMo), Orchestrator fallback (Muse) | $10–40/mo |
| **CommandCode GOAT** ($10/mo) | Critic (Haiku), Senior (Sonnet), Worker burst (DeepSeek) | $10/mo |
| **NVIDIA** (free) | Free-first Worker/Critic/Senior/Scout (Nemotron 3 Ultra/3.5 Super) | $0 |
| **Zen** (free) | Scout (MiMo), Free fallbacks | $0 |

> **Nvidia rate-limit handling**: 429 = `rate-limit` (1-30 min), not `quota`. Auto-resume same session after cooldown.

### 🔧 Optimal .env for Cross-Harness

```bash
# ── Core (Required) ──────────────────────────────────────────────
DASHBOARD_PASSWORD_HASH=$2b$12$...        # bcrypt hash
JWT_SECRET=$(openssl rand -hex 32)        # persistent secret

# ── Providers (Optimal: All Configured) ──────────────────────────
# Claude Code (subscription) — Orchestrator, Critic, Senior, Worker fallback
ANTHROPIC_API_KEY=sk-ant-...              # Used by CC subagents

# OpenCode Go ($10/mo Pro, $40/mo Max) — Worker (MiMo), Orchestrator fallback (Muse)
OPENCODE_GO_API_KEY=...                   # Go models

# CommandCode GOAT ($10/mo) — Critic (Haiku), Senior (Sonnet), Burst (DeepSeek)
COMMANDCODE_API_KEY=...                   # CmdC models

# NVIDIA (free) — Free-first Worker/Critic/Senior/Scout (Nemotron)
NVIDIA_API_KEY=...                        # Nemotron 3 Ultra / 3.5 Super

# Zen (free) — Scout (MiMo), Free fallbacks
ZEN_API_KEY=...                           # qwen3.6-plus, minimax, nemotron-3-super

# ── Memory (Recommended) ─────────────────────────────────────────
QDRANT_URL=http://localhost:6333          # Vector DB (Docker: qdrant/qdrant)
REDIS_URL=redis://localhost:6379          # Caching, rate limits

# ── Security ────────────────────────────────────────────────────
COMMAND_FILTER_MODE=deny
SANDBOX_ENABLED=true
ALLOWED_COMMANDS=git,python,pip,ruff,pytest,make
```

> **Pro tip**: The orchestrator's `router-health --probe` auto-detects which providers are healthy and selects the optimal model per role. Missing keys = graceful skip (no crash).

### 🎨 Vision Delegation — *The Babel Fish for Images*

**Non-vision orchestrators get vision by spawning vision-capable subagents.** The orchestrator (Opus 5.5, Go Muse, etc.) may not have native vision, but when images are detected:

1. **Auto-detection** — Orchestrator scans Mandate/task for images (file paths, base64, URLs)
2. **Auto-spawn** — Adds `--vision` flag to `oc-worker` dispatches for worker/critic/senior
3. **Vision-capable models** — `worker-nvidia`, `critic-nvidia`, `senior-nvidia`, `orchestrator-nvidia` all pin **Nemotron 3.5 Super VL** (vision-enabled)
4. **Fallback chain** — If primary vision model is rate-limited, router-health selects next vision-capable model

```bash
# Example: Orchestrator (no vision) dispatches Worker with vision
node {{ORCH_REPO}}/bin/oc-worker.mjs --agent worker-nvidia --vision \
  --dir <worktree> --prompt <mandate.md> --report <run dir>/report.md

# Example: Critic with vision reviews UI changes
node {{ORCH_REPO}}/bin/oc-worker.mjs --agent critic-nvidia --vision \
  --dir <worktree> --prompt <critic-prompt.md> --out <findings.md>
```

> **Key insight**: The orchestrator stays on its optimal model (Opus, Go Muse) for planning/reasoning, while vision work delegates to Nemotron 3.5 Super VL — the best free vision model available.

### Cross-Harness Handoff

```bash
# In Claude Code: take over an OpenCode stream
/next <stream-number>    # Asks owner, takes over on yes

# In OpenCode: take over a Claude Code stream
/next <stream-number>

# Hand back to other harness
/handback <stream-number>
```

**Cross-harness subagent spawning**: OpenCode sessions **CAN** launch Claude Code subagents (and vice versa) through the orchestrator's unified interface. When running the orchestrator in OpenCode, you can spawn `subagent({ agent: "worker" })` which launches a Claude Code `worker` agent (Sonnet) — the harness doesn't limit subagent type, only the orchestrator's model routing rules.

```bash
# In OpenCode orchestrator session, spawn a Claude Code worker
> subagent({ agent: "worker", prompt: "Fix the login bug in auth.ts" })
# Launches Claude Code `worker` agent (Sonnet) — works because orchestrator knows how to bridge harnesses
```

Streams are harness-agnostic — a stream started in one harness finishes in the other. One desk daemon at a time across both.

### EGM (Elephant-Goldfish) Gate

Before any worker starts, the orchestrator checks triggers:

| Trigger | EGM Required? |
|---------|---------------|
| New module/service/package | ✅ Yes |
| Data model change (schema, migration, persisted key) | ✅ Yes |
| Public interface change (API, CLI, config format) | ✅ Yes |
| >3 modules touched | ✅ Yes |
| Security/tenancy/money (auth, billing, wallet) | ✅ Yes |

No trigger → **waived with reason** (never silently skipped). Runs via `/egm:egm-review` (Claude Code) or `/egm-review` (OpenCode).

### Frood + Orchestrator Integration

Frood provides the **runtime** (LLM routing, memory, tools, skills, dashboard).
The Orchestrator provides the **process** (planning, delegation, review, deploy).

```bash
# Recommended setup
~/projects/
├── frood/              # LLM backbone (this repo)
├── orchestrator/       # Cross-harness process (separate repo)
└── your-project/       # Where work happens (worktrees created here)
```

1. **Frood runs** on port 8000 — provides LLM endpoint, MCP tools, memory, skills
2. **Orchestrator runs** in Claude Code or OpenCode — plans work, spawns workers
4. **Workers** (headless OpenCode) call Frood's LLM endpoint via MCP
5. **Critic** reviews, **Senior** signs off, **Board** deploys via train

### Install Both (Frood now includes Orchestrator)

```bash
# Frood (LLM backbone + cross-harness orchestrator)
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood && bash setup.sh

# The orchestrator is now integrated at ~/frood/orchestrator/
# Install slash commands for both Claude Code & OpenCode:
cd ~/frood/orchestrator && node bin/install.mjs

# In Claude Code or OpenCode, start orchestration:
/orchestrator "Build a REST API with auth, rate limiting, and tests"
```

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
# HTTP API sidecar mode (run headless on any server)
# General users: leave false, use MCP instead
ENABLE_PAPERCLIP=false
```

> **See [Configuration](https://salesteamtoolbox.github.io/frood/docs/usage.html#configuration) for all 80+ variables.**

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
├── channels/            # WebSocket, HTTP API, CLI
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
  <a href="https://salesteamtoolbox.github.io/frood/">📖 Documentation</a> ·
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

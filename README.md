# Frood

AI agent orchestration with tiered LLM routing, semantic memory, and multi-agent tool effectiveness. Frood keeps your agents running reliably — L1 workhorse, free-tier fallback, L2 premium — so no single provider outage stops your agents.

<p align="center">
  <a href="https://salesteamtoolbox.com/?utm_source=github&utm_medium=frood&utm_campaign=oss">
    <img src="https://img.shields.io/badge/Try%20Frood-Sales%20Team%20Toolbox-0b5ed6?logo=github&style=for-the-badge" alt="Try Frood on Sales Team Toolbox">
  </a>
  <a href="https://github.com/SalesTeamToolbox/frood">
    <img src="https://img.shields.io/badge/license-MIT-lightgrey" alt="License">
  </a>
</p>

## What Frood does

- **Tiered provider routing** — L1 workhorse → free fallback (Zen / NVIDIA) → L2 premium (Claude / GPT-4o). Graceful degradation; missing API keys never crash Frood.
- **Semantic memory** — ONNX embeddings with Qdrant vector search (falls back to local JSON). Memories surface before the model thinks.
- **Tool effectiveness & learning** — Every invocation tracked; structured learnings extracted, quarantined, validated, then proactively injected into future sessions.
- **48 MCP tools** — memory, context, code intel, security, browser automation, n8n, vision, content, orchestration.
- **46 built-in skills** — development, DevOps, content, analysis, marketing, meta.
- **Paperclip sidecar** — route agent tasks through Frood's HTTP API instead of spawning local CLI processes.
- **8-layer security** — sandbox, command filter, approval gate, rate limiter, URL policy, browser-gateway token, spending tracker, login rate limiting.

## Quick start

```bash
# Clone
git clone https://github.com/SalesTeamToolbox/frood.git
cd frood

# Install
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

# Configure (all values are placeholders — replace with your own)
cp .env.example .env

# Run
python frood.py                  # Dashboard at http://localhost:8000
```

Docker:

```bash
cp .env.example .env
docker compose up -d
# Frood: http://localhost:8000
```

Connect to Claude Code: copy `.mcp.json.example` to `.mcp.json` and restart Claude Code. Frood's MCP tools appear alongside the built-in ones.

Full setup (venv, deps, frontend, MCP config, hooks): `bash setup.sh`.

See `CLAUDE.md` for development guidelines, and `Makefile` targets (`lint`, `format`, `check`, `test`).

## Built by

Frood is built and maintained by **Sales Team Toolbox** — an AI agent platform for sales teams.

<p align="center">
  <a href="https://salesteamtoolbox.com/?utm_source=github&utm_medium=frood&utm_campaign=oss">
    <img src="https://img.shields.io/badge/Built%20by-Sales%20Team%20Toolbox-0b5ed6?logo=github&style=flat-square" alt="Built by Sales Team Toolbox">
  </a>
</p>

## Docs & dashboard

<p align="center">
  <a href="https://salesteamtoolbox.com/?utm_source=github&utm_medium=frood&utm_campaign=oss">Documentation</a> ·
  <a href="https://salesteamtoolbox.com/?utm_source=github&utm_medium=frood&utm_campaign=oss">Dashboard</a> ·
  <a href="https://github.com/SalesTeamToolbox/frood/issues">Issues</a> ·
  <a href="https://github.com/SalesTeamToolbox/frood">GitHub</a>
</p>

All links above carry `utm_source=github&utm_medium=frood&utm_campaign=oss`.

## License

[MIT](LICENSE) © 2026 Sales Team Toolbox

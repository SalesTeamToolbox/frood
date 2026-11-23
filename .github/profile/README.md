# 🛸 SalesTeamToolbox / Frood

<p align="center">
  <img src="https://raw.githubusercontent.com/SalesTeamToolbox/frood/main/dashboard/frontend/dist/assets/frood-logo.svg" alt="Frood Logo" width="280">
  <br>
  <em><strong>DON'T PANIC</strong> — Your agents' towel is ready.</em>
</p>

<p align="center">
  <a href="https://github.com/SalesTeamToolbox/frood">
    <img src="https://img.shields.io/github/stars/SalesTeamToolbox/frood?style=for-the-badge&logo=github&color=E8A838" alt="Stars">
  </a>
  <a href="https://github.com/SalesTeamToolbox/frood/issues">
    <img src="https://img.shields.io/github/issues/SalesTeamToolbox/frood?style=for-the-badge&logo=github&color=d63031" alt="Issues">
  </a>
  <a href="https://github.com/SalesTeamToolbox/frood/pulls">
    <img src="https://img.shields.io/github/issues-pr/SalesTeamToolbox/frood?style=for-the-badge&logo=github&color=0984e3" alt="Pull Requests">
  </a>
  <br>
  <a href="https://salesteamtoolbox.com/docs/frood">
    <img src="https://img.shields.io/badge/📖%20Documentation-frood.st-42b883?style=for-the-badge&logo=readthedocs" alt="Documentation">
  </a>
  <a href="https://discord.gg/salesteamtoolbox">
    <img src="https://img.shields.io/discord/1234567890?label=Discord&logo=discord&style=for-the-badge" alt="Discord">
  </a>
</p>

---

> **"A *frood* is someone who really knows where their towel is."**
> — *The Hitchhiker's Guide to the Galaxy, Douglas Adams*

## 🚀 What is Frood?

**Frood** is the AI agent platform that *always knows where its towel is*. It provides:

- **🚀 Tiered Provider Routing** — L1 Workhorse → Free Fallback (Zen/NVIDIA) → L2 Premium (Claude/GPT). Graceful degradation — missing API keys never crash Frood.
- **🧠 Semantic Memory** — ONNX embeddings + Qdrant vector search (falls back to local JSON). Memories surface *before* the model thinks.
- **📚 Tool Effectiveness & Learning** — Every invocation tracked; structured learnings extracted, quarantined, validated, then proactively injected into future sessions.
- **🔧 48 MCP Tools** — Memory, context, code intel, security, browser automation, n8n, vision, content, orchestration.
- **🎓 46 Built-in Skills** — Development, DevOps, content, analysis, marketing, meta — ready to `frood_skill load`.
- **🛡️ 8-Layer Security** — Sandbox, command filter, approval gate, rate limiter, URL policy, browser-gateway token, spending tracker, login rate limiting.

## 🎯 Quick Links

| What you need | Where to go |
|---------------|-------------|
| **Get Started** | [Installation Guide](https://salesteamtoolbox.com/docs/frood/installation) |
| **Full Docs** | [frood.st](https://salesteamtoolbox.com/docs/frood) |
| **API Reference** | [API Docs](https://salesteamtoolbox.com/docs/frood/api-reference) |
| **Report a Bug** | [Issues](https://github.com/SalesTeamToolbox/frood/issues/new/choose) |
| **Request Feature** | [Feature Request](https://github.com/SalesTeamToolbox/frood/issues/new/choose) |
| **Ask Questions** | [Discussions](https://github.com/SalesTeamToolbox/frood/discussions) |
| **Chat Live** | [Discord](https://discord.gg/salesteamtoolbox) |

## 🏗️ Repository Structure

```
frood/
├── agents/              # Agent profiles (writer, researcher, developer, etc.)
├── core/                # Router, config, settings, providers
├── dashboard/           # FastAPI + React PWA (port 8000)
├── memory/              # ONNX embeddings, Qdrant, learning
├── providers/           # LLM provider adapters (9 providers)
├── skills/              # 46 built-in skills + archive
├── tools/               # 48 MCP tools
├── channels/            # WebSocket, CLI
├── tests/               # 200+ tests (pytest, asyncio)
├── docs/                # Documentation source
├── frood.py             # Main entry point
├── setup.sh             # Full install script
└── pyproject.toml       # ruff, pytest, mypy config
```

## 🤝 Contributing

We welcome contributions! Frood is built by the community, for the community.

1. **Fork** the repository
2. **Create** a feature branch (`git checkout -b feature/amazing-thing`)
3. **Run** `make check` (lint + tests)
4. **Submit** a PR with a clear description

See [CONTRIBUTING.md](CONTRIBUTING.md) for detailed guidelines (coming soon).

## 🛸 The Theme

Yes, we're **that** kind of frood. The name comes from *The Hitchhiker's Guide to the Galaxy*:

- **🛸 42** — The answer to life, the universe, and everything (hidden in our logo)
- **🧺 Towel** — The most massively useful thing an interstellar hitchhiker can have
- **🚫 DON'T PANIC** — The eternal tagline, on every logo variant
- **⭐ Infinite Improbability Drive** — Our tiered fallback routing chain
- **🐟 Babel Fish** — MCP tools that translate between agent dialects

## 📜 License

**MIT License** © 2026 [Sales Team Toolbox](https://salesteamtoolbox.com)

---

<p align="center">
  <strong>Remember: A towel is about the most massively useful thing an interstellar hitchhiker can have.</strong><br>
  <em>Frood makes sure your agents always have theirs.</em>
</p>

<p align="center">
  <img src="https://raw.githubusercontent.com/SalesTeamToolbox/frood/main/dashboard/frontend/dist/assets/frood-avatar.svg" alt="Frood Avatar" width="64">
  <br>
  <sub>Built with ❤️ and improbability by <a href="https://salesteamtoolbox.com">Sales Team Toolbox</a></sub>
</p>

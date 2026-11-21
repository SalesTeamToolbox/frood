# Usage

Core concepts and how to operate Frood once it is running.

## Dashboard

Start Frood with `make run`; the dashboard is served at http://localhost:8000. It shows agent status, provider routing, and recent task activity. Use `make run-headless` to run without the dashboard.

## Router

Frood routes each agent turn through a tiered provider chain: L1 workhorse (StrongWall when configured), free tier fallback, then L2 premium opt-in. Missing API keys never crash Frood — the router falls back to the next available provider. Per-agent model configuration lives in `.env` / provider config; see `core/config.py` (frozen `Settings` dataclass).

## Memory

Frood provides persistent memory (ONNX embeddings + Qdrant with auto-sync from Claude Code) plus task-aware learning with effectiveness tracking and proactive injection. Memory, Redis, Qdrant, and MCP are optional — Frood degrades gracefully when they are absent. Use `frood_memory` to store, search, and recall facts across sessions.

## Peer-mail

Peer-mail is session messaging between agent sessions on this box. Use `peer_inbox` to list unread messages (subjects first), `peer_read` to read a body, `peer_ack` to acknowledge, and `peer_send` to send a receipt. Messages are addressed by exact session id; read and ack refuse messages addressed to anyone else. Peer-mail history and session ids never enter the public tree.

## Sandbox

All I/O is async (`aiofiles`, `httpx`, `asyncio`) — never blocking I/O in tools. Validate paths via `sandbox.resolve_path()`; the sandbox is always on in production.

## License

MIT, © Sales Team Toolbox. See `LICENSE`.

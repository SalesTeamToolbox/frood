# CLAUDE.md — Agent42 Development Guide

## Testing

**Always install dependencies before running tests:**

```bash
pip install -r requirements.txt
# Or at minimum for tests:
pip install pytest pytest-asyncio aiofiles openai
```

Run tests:
```bash
python -m pytest tests/ -x -q
```

Some tests require `fastapi` and `redis` — install the full requirements to avoid import errors.

## Project Structure

- `agent42.py` — Main orchestrator entry point
- `agents/` — Agent pipeline: model router, iteration engine, learner
- `core/` — Task queue, config, capacity, security, worktree management
- `providers/` — LLM provider registry (OpenRouter, OpenAI, Anthropic, etc.)
- `dashboard/` — FastAPI web dashboard + WebSocket manager
- `channels/` — Discord, Slack, Telegram, Email integrations
- `skills/` — Pluggable skill system
- `memory/` — Session management, semantic search, consolidation
- `tools/` — Shell, browser, web search, file operations
- `tests/` — Test suite

## Key Patterns

- All I/O is async (`asyncio`, `aiofiles`)
- Task queue uses `asyncio.PriorityQueue` with pluggable backends (JSON file or Redis)
- Model routing is free-first: uses OpenRouter free models by default
- Spending tracker enforces `MAX_DAILY_API_SPEND_USD` across all API calls
- Redis is optional — graceful fallback to JSON/JSONL when unavailable

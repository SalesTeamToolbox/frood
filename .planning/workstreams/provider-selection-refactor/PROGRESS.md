# v5.0 Provider Selection Refactor - Complete

## Overview

Simplified Agent42's provider selection system by removing dead L1/L2 config and wiring the Paperclip plugin to the consolidated TieredRoutingBridge.

## What Was Done

### Phase 34: System Simplification (2026-04-06)
- Removed 8 dead L1/L2 Settings dataclass fields from `core/config.py`
- Removed 9 matching `from_env()` calls
- Removed 29-line L1/L2 section from `.env.example`
- Fixed stale FALLBACK_ROUTING comment
- Verified SIMPLIFY-03/04/05 already satisfied

### Phase 35: Paperclip Integration (2026-04-06)
- Added `ProviderModelItem`, `ModelsResponse`, `ProviderStatusDetail` Pydantic models
- Created `GET /sidecar/models` endpoint serializing PROVIDER_MODELS registry
- Enhanced `GET /sidecar/health` with per-provider connectivity status
- Added `SYNTHETIC_API_KEY` to config, key store, and .env.example
- Wired TypeScript interfaces, `getModels()` client method, `available-models` data handler
- Enhanced `ProviderHealthWidget` with per-provider detail rendering

## What Was Not Done (and why)

### Phase 32: Provider Selection Core — Superseded
Planned CC Subscription as primary provider and Synthetic.new as fallback. Neither was adopted. The existing provider hierarchy (Zen free → OpenRouter → Anthropic → OpenAI via TieredRoutingBridge) already works. StrongWall was already removed before this milestone.

### Phase 33: Synthetic.new Integration — Superseded
Planned dynamic model discovery from Synthetic.new API. Synthetic.new was never adopted. Dynamic model discovery already works via Zen API refresh in `agent_manager.py`.

## Final Status
- 2 of 4 phases executed (34, 35)
- 2 of 4 phases superseded (32, 33)
- 9 of 16 v1 requirements complete, 7 superseded
- All tests green (2203 passed)
- Milestone closed: 2026-04-07

# Dashboard API Settings Update Summary

## Changes Made

### 1. Removed StrongWall API Key from Admin Configurable Keys
- **File**: `core/key_store.py`
- **Change**: Removed `STRONGWALL_API_KEY` from the `ADMIN_CONFIGURABLE_KEYS` frozenset
- **Reason**: StrongWall.ai has been completely removed from the codebase as verified in the phase 32 verification document

### 2. Verified Backend API Endpoints
The following backend API endpoints correctly expose the current providers:

1. **`/api/agents/models`** - Returns `PROVIDER_MODELS` from `core.agent_manager`:
   - claudecode (Claude Code Subscription)
   - anthropic (Anthropic)
   - synthetic (Synthetic.new)
   - openrouter (OpenRouter)

2. **`/api/ide/chat/config`** - Returns current chat provider configuration:
   - Anthropic (https://api.anthropic.com)
   - Synthetic (https://api.synthetic.new/v1)
   - OpenRouter (https://openrouter.ai/api/v1)

3. **`/api/providers`** and **`/api/available-models`** - Correctly indicate that provider registry was removed in v2.0 MCP pivot

### 3. Documented Frontend Update Requirements
- **File**: `.claude/reference/dashboard-frontend-update.md`
- **Content**: Detailed documentation of what needs to be updated in the frontend to reflect current providers and remove StrongWall references

## Current Provider Configuration

### Active Providers (in order of precedence):
1. **Claude Code Subscription** - Primary provider when CLAUDECODE_SUBSCRIPTION_TOKEN is configured
2. **Synthetic.new** - Fallback provider when SYNTHETIC_API_KEY is configured
3. **Anthropic** - Final fallback provider
4. **OpenRouter** - Additional provider option

### Provider Selection Hierarchy:
1. Claude Code Subscription (when CLAUDECODE_SUBSCRIPTION_TOKEN is set)
2. Synthetic.new (when SYNTHETIC_API_KEY is set)
3. Anthropic (final fallback when other keys are missing)

## Verification

All changes have been made to ensure the backend correctly exposes the current provider configuration. The frontend update documentation provides guidance for updating the UI when source files become available.
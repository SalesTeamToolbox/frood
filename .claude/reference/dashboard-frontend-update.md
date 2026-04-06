# Dashboard Frontend Update Requirements

## Current Provider Configuration

Based on the backend API endpoints, the current providers that should be displayed in the dashboard are:

1. **Claude Code Subscription** - Primary provider when CLAUDECODE_SUBSCRIPTION_TOKEN is configured
2. **Synthetic.new** - Fallback provider when SYNTHETIC_API_KEY is configured
3. **Anthropic** - Final fallback provider
4. **OpenRouter** - Additional provider option

## Providers to Remove

- **StrongWall.ai** - Completely removed from the codebase

## Backend API Endpoints

The dashboard should use these backend API endpoints to get provider information:

1. `/api/agents/models` - Returns PROVIDER_MODELS dictionary with model mappings for each provider
2. `/api/ide/chat/config` - Returns current chat provider configuration
3. `/api/settings/keys` - Returns configurable API keys (used for provider key management)

## Required Frontend Updates

### 1. Provider Settings Page
- Remove any references to StrongWall.ai
- Add Synthetic.new as a configurable provider
- Ensure Claude Code Subscription is properly displayed as the primary provider
- Update the provider configuration UI to reflect the current provider hierarchy

### 2. Chat Interface
- Update the chat configuration display to show the correct providers:
  - Anthropic (https://api.anthropic.com)
  - Synthetic (https://api.synthetic.new/v1)
  - OpenRouter (https://openrouter.ai/api/v1)

### 3. Agent Creation/Configuration
- Update the provider selection dropdown to include only the current providers
- Ensure the model selection is properly populated from the `/api/agents/models` endpoint

### 4. API Key Management
- Remove STRONGWALL_API_KEY from the API key management interface
- Ensure SYNTHETIC_API_KEY is included as a configurable key

## Provider Selection Hierarchy
The frontend should display the provider selection logic in this order:
1. Claude Code Subscription (when CLAUDECODE_SUBSCRIPTION_TOKEN is set)
2. Synthetic.new (when SYNTHETIC_API_KEY is set)
3. Anthropic (final fallback when other keys are missing)

## Technical Notes
- The PROVIDER_MODELS in core/agent_manager.py contains the current provider mappings
- The ADMIN_CONFIGURABLE_KEYS in core/key_store.py has been updated to remove STRONGWALL_API_KEY
- All backend API endpoints are already updated to reflect the current providers
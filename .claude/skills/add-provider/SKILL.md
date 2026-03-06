---
name: add-provider
description: Scaffold a complete LLM provider integration (registry, config, env, tests)
always: false
task_types: [coding]
---

# /add-provider

Scaffold a new LLM provider integration across all required touchpoints in one workflow.

## Input Gathering

Before generating any code, ask the developer for:

1. **Provider name** (lowercase, e.g., `fireworks`, `replicate`, `cohere`)
2. **Base URL** (e.g., `https://api.fireworks.ai/inference/v1`)
3. **API key environment variable name** (e.g., `FIREWORKS_API_KEY`)
4. **Display name** (e.g., `Fireworks AI`)
5. **Model IDs to register** -- at least one, with:
   - Model ID string (e.g., `accounts/fireworks/models/llama-v3p1-70b-instruct`)
   - Display name (e.g., `Llama 3.1 70B`)
   - Max output tokens (default: 4096)
   - Max context tokens (default: 128000)
   - Tier: `FREE`, `CHEAP`, or `PREMIUM`
6. **Default model ID** (must be one of the registered model IDs)
7. **Supports function calling?** (default: `True`)
8. **Sign-up URL** for the `.env.example` comment (e.g., `https://fireworks.ai/`)

## Pre-generation: Read Current State

Before making any edits, read these files to understand current structure:

1. **`providers/registry.py`** -- note the existing `ProviderType` enum values (alphabetical placement), `PROVIDERS` dict entries, and `MODELS` dict entries
2. **`core/config.py`** -- note the existing `Settings` API key fields and `from_env()` method
3. **`.env.example`** -- note the existing provider API key section layout

## Step-by-step Modifications

Execute these edits in order. Each step modifies a specific file at a specific location.

### Step A: Add ProviderType enum value

**File:** `providers/registry.py`
**Location:** `ProviderType` enum class

Add a new enum value using UPPER_SNAKE_CASE for the name and lowercase for the string value. Place it **alphabetically** among existing entries.

```python
class ProviderType(str, Enum):
    """Provider type enumeration."""

    ANTHROPIC = "anthropic"
    CEREBRAS = "cerebras"
    # ... existing entries ...
    <NAME> = "<name>"       # <-- insert alphabetically
    # ... remaining entries ...
```

### Step B: Add ProviderSpec to PROVIDERS dict

**File:** `providers/registry.py`
**Location:** `PROVIDERS` dict

Add a new entry using this exact pattern:

```python
ProviderType.<NAME>: ProviderSpec(
    provider_type=ProviderType.<NAME>,
    base_url="<base_url>",
    api_key_env="<API_KEY_ENV>",
    display_name="<Display Name>",
    default_model="<default_model_id>",
    supports_function_calling=<True|False>,
),
```

### Step C: Add ModelSpec entries to MODELS dict

**File:** `providers/registry.py`
**Location:** `MODELS` dict

Add one entry per model using this exact pattern:

```python
"<model_id>": ModelSpec(
    model_id="<model_id>",
    provider=ProviderType.<NAME>,
    display_name="<Display Name>",
    tier=ModelTier.<TIER>,
    max_tokens=<max_output_tokens>,
    max_context_tokens=<max_context_tokens>,
),
```

### Step D: Add Settings field and from_env() entry

**File:** `core/config.py`
**Location:** `Settings` frozen dataclass and `from_env()` classmethod

1. Add the API key field among other provider API key fields (alphabetical):

```python
@dataclass(frozen=True)
class Settings:
    # API keys -- providers
    cerebras_api_key: str = ""
    # ... existing fields ...
    <name>_api_key: str = ""    # <-- insert alphabetically
    # ... remaining fields ...
```

2. Add the `os.getenv()` call in `from_env()`:

```python
@classmethod
def from_env(cls):
    return cls(
        # ... existing entries ...
        <name>_api_key=os.getenv("<API_KEY_ENV>", ""),
        # ... remaining entries ...
    )
```

### Step E: Update .env.example

**File:** `.env.example`
**Location:** Provider API Keys section

Add the new provider's API key with a comment showing the tier and sign-up URL:

```
# <Display Name> -- <TIER> tier (<pricing note>)
# Get key: <sign_up_url>
# <API_KEY_ENV>=<placeholder>
```

Place it in the appropriate position among other providers, grouped by tier (FREE, CHEAP, PREMIUM).

### Step F: Create test file

**File:** `tests/test_<name>_provider.py`

Create a test file with this structure:

```python
"""Tests for <Display Name> provider registration."""

from providers.registry import (
    MODELS,
    PROVIDERS,
    ModelSpec,
    ModelTier,
    ProviderSpec,
    ProviderType,
)


class TestProviderRegistration:
    """Verify <name> provider is correctly registered."""

    def test_provider_type_enum_exists(self):
        """ProviderType.<NAME> enum value exists."""
        assert hasattr(ProviderType, "<NAME>")
        assert ProviderType.<NAME>.value == "<name>"

    def test_provider_spec_registered(self):
        """ProviderSpec is in PROVIDERS dict."""
        spec = PROVIDERS[ProviderType.<NAME>]
        assert isinstance(spec, ProviderSpec)
        assert spec.base_url == "<base_url>"
        assert spec.api_key_env == "<API_KEY_ENV>"
        assert spec.display_name == "<Display Name>"
        assert spec.default_model == "<default_model_id>"
        assert spec.supports_function_calling is <True|False>

    def test_model_specs_registered(self):
        """ModelSpec entries exist in MODELS dict."""
        # Verify each registered model
        model = MODELS["<model_id>"]
        assert isinstance(model, ModelSpec)
        assert model.provider == ProviderType.<NAME>
        assert model.tier == ModelTier.<TIER>


class TestProviderConfig:
    """Verify Settings has the API key field."""

    def test_settings_has_api_key_field(self):
        """Settings dataclass has <name>_api_key field."""
        from core.config import Settings
        import dataclasses

        field_names = [f.name for f in dataclasses.fields(Settings)]
        assert "<name>_api_key" in field_names

    def test_settings_api_key_default_empty(self):
        """API key defaults to empty string."""
        from core.config import Settings
        import dataclasses

        fields_dict = {f.name: f for f in dataclasses.fields(Settings)}
        field = fields_dict["<name>_api_key"]
        assert field.default == ""


class TestProviderClient:
    """Verify get_client() works with the provider."""

    def test_get_client_returns_async_openai(self, monkeypatch):
        """get_client() returns AsyncOpenAI when key is set."""
        monkeypatch.setenv("<API_KEY_ENV>", "test-key-12345")

        from providers.registry import get_client
        from openai import AsyncOpenAI

        client = get_client(ProviderType.<NAME>)
        assert isinstance(client, AsyncOpenAI)
```

## Post-generation Verification

Run the test file to confirm everything is wired up correctly:

```bash
python -m pytest tests/test_<name>_provider.py -x -q
```

All tests should pass. If any fail, fix the issue before proceeding.

## What NOT To Do

- **Do NOT hardcode premium models as defaults** -- the dynamic routing system handles model selection (per CLAUDE.md)
- **Do NOT add the provider to `FREE_ROUTING` or `model_router.py`** -- that is managed by the dynamic routing system (`ModelEvaluator`, `ModelCatalog`)
- **Do NOT forget `supports_function_calling`** if the provider does not support it -- set it to `False` explicitly
- **Do NOT use blocking I/O** in any generated code -- all operations must be async (per CLAUDE.md)

## Completion Checklist

Before finishing, verify all touchpoints are covered:

- [ ] `ProviderType` enum value added to `providers/registry.py`
- [ ] `ProviderSpec` entry added to `PROVIDERS` dict in `providers/registry.py`
- [ ] `ModelSpec` entry/entries added to `MODELS` dict in `providers/registry.py`
- [ ] `<name>_api_key` field added to `Settings` class in `core/config.py`
- [ ] `os.getenv("<API_KEY_ENV>", "")` added to `from_env()` in `core/config.py`
- [ ] `.env.example` updated with new API key variable and sign-up URL
- [ ] `tests/test_<name>_provider.py` created and all tests passing

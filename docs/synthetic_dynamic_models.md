# Synthetic.new Dynamic Model Discovery

Agent42 now supports dynamic model discovery for Synthetic.new, automatically fetching and updating available models from the Synthetic.new API.

## How It Works

1. **API Client**: The `providers/synthetic_api.py` module contains a client that fetches available models from the Synthetic.new API.

2. **Caching**: Models are cached locally in `data/synthetic_models_cache.json` to reduce API calls and provide fallback when the API is unavailable.

3. **Automatic Refresh**: Models are automatically refreshed every 24 hours (configurable via `MODEL_CATALOG_REFRESH_HOURS` setting).

4. **Dynamic Mapping**: The system automatically updates the `PROVIDER_MODELS["synthetic"]` mapping based on the capabilities of the available models.

## Configuration

To enable dynamic model discovery:

1. Set your Synthetic.new API key in `.env`:
   ```
   SYNTHETIC_API_KEY=your_synthetic_api_key_here
   ```

2. Optionally configure the refresh interval:
   ```
   MODEL_CATALOG_REFRESH_HOURS=24
   ```

## Model Selection Logic

The system categorizes models based on their capabilities and selects the best model for each category:

- **fast**: Fast response models
- **general**: General purpose models
- **reasoning**: Complex reasoning models
- **coding**: Code generation and analysis models
- **content**: Content creation models
- **research**: Research and analysis models
- **monitoring**: Monitoring and alerting models
- **marketing**: Marketing and copywriting models
- **analysis**: Data analysis models
- **lightweight**: Lightweight models for simple tasks

For each category, the system prefers free models when available.

## Manual Refresh

You can manually refresh the models by calling:
```python
from core.agent_manager import refresh_synthetic_models
refresh_synthetic_models(force=True)
```

## Testing

Run the test script to verify the integration:
```bash
python scripts/test_synthetic_api.py
```
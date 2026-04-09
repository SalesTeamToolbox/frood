"""
Test script for Synthetic.new API client.

Run this script to verify that the Synthetic.new API client can fetch models
and update the provider mappings.
"""

import asyncio
import logging
import sys
from pathlib import Path

# Add the project root to the path so we can import our modules
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# Configure logging
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

logger = logging.getLogger("test_synthetic_api")


async def main():
    """Test the Synthetic.new API client."""
    try:
        # Import the client
        from providers.synthetic_api import SyntheticApiClient

        # Create client instance
        client = SyntheticApiClient()

        # Refresh models
        logger.info("Fetching models from Synthetic.new API...")
        models = await client.refresh_models(force=True)

        if models:
            logger.info(f"Successfully fetched {len(models)} models:")
            for model in models[:5]:  # Show first 5 models
                logger.info(f"  - {model.id}: {model.name} (free: {model.is_free})")

            # Test updating provider mappings
            mapping = client.update_provider_models_mapping()
            logger.info(f"Generated provider mapping: {mapping}")
        else:
            logger.warning("No models fetched from Synthetic.new API")

    except Exception as e:
        logger.error(f"Error testing Synthetic.new API client: {e}")
        return False

    return True


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)

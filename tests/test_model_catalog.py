"""Tests for agents/model_catalog.py — OpenRouter catalog sync."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from agents.model_catalog import CatalogEntry, ModelCatalog, _slug_from_model_id


class TestSlugFromModelId:
    def test_simple(self):
        assert _slug_from_model_id("meta-llama/llama-4-maverick:free") == "llama-4-maverick"

    def test_no_prefix(self):
        assert _slug_from_model_id("llama-4-maverick:free") == "llama-4-maverick"

    def test_no_suffix(self):
        assert _slug_from_model_id("qwen/qwen3-coder") == "qwen3-coder"


class TestCatalogEntry:
    def test_free_model(self):
        entry = CatalogEntry(
            {
                "id": "test/model:free",
                "name": "Test Model",
                "pricing": {"prompt": "0", "completion": "0"},
                "context_length": 128000,
            }
        )
        assert entry.is_free is True
        assert entry.model_id == "test/model:free"
        assert entry.context_length == 128000

    def test_paid_model(self):
        entry = CatalogEntry(
            {
                "id": "test/model",
                "name": "Test Model",
                "pricing": {"prompt": "0.001", "completion": "0.002"},
            }
        )
        assert entry.is_free is False

    def test_coding_category(self):
        entry = CatalogEntry(
            {
                "id": "qwen/qwen3-coder:free",
                "name": "Qwen3 Coder",
                "pricing": {"prompt": "0", "completion": "0"},
            }
        )
        assert entry.inferred_category() == "coding"

    def test_reasoning_category(self):
        entry = CatalogEntry(
            {
                "id": "deepseek/deepseek-r1:free",
                "name": "DeepSeek R1",
                "pricing": {"prompt": "0", "completion": "0"},
            }
        )
        assert entry.inferred_category() == "reasoning"

    def test_general_category(self):
        entry = CatalogEntry(
            {
                "id": "meta-llama/llama-4:free",
                "name": "Llama 4 Maverick",
                "pricing": {"prompt": "0", "completion": "0"},
            }
        )
        assert entry.inferred_category() == "general"

    def test_missing_pricing(self):
        entry = CatalogEntry(
            {
                "id": "test/model",
                "name": "Test",
                "pricing": None,
            }
        )
        assert entry.is_free is True  # None pricing defaults to "0"

    def test_to_dict(self):
        entry = CatalogEntry(
            {
                "id": "test/model:free",
                "name": "Test",
                "pricing": {"prompt": "0", "completion": "0"},
                "context_length": 64000,
            }
        )
        d = entry.to_dict()
        assert d["id"] == "test/model:free"
        assert d["pricing"]["prompt"] == "0"


class TestModelCatalog:
    def test_init_empty(self, tmp_path):
        """New catalog with no cache should have no entries."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        assert catalog.free_models() == []
        assert catalog.needs_refresh() is True

    def test_cache_roundtrip(self, tmp_path):
        """Save and load catalog from cache."""
        cache_path = tmp_path / "catalog.json"

        # Create catalog with entries
        catalog1 = ModelCatalog(cache_path=cache_path)
        catalog1._entries = [
            CatalogEntry(
                {
                    "id": "test/free-model:free",
                    "name": "Free Model",
                    "pricing": {"prompt": "0", "completion": "0"},
                    "context_length": 128000,
                }
            ),
            CatalogEntry(
                {
                    "id": "test/paid-model",
                    "name": "Paid Model",
                    "pricing": {"prompt": "0.001", "completion": "0.002"},
                }
            ),
        ]
        catalog1._last_refresh = 1000.0
        catalog1._save_cache()

        # Load from cache
        catalog2 = ModelCatalog(cache_path=cache_path)
        assert len(catalog2._entries) == 2
        assert len(catalog2.free_models()) == 1
        assert catalog2._last_refresh == 1000.0

    def test_free_models_by_category(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        catalog._entries = [
            CatalogEntry(
                {
                    "id": "q/coder:free",
                    "name": "Coder Model",
                    "pricing": {"prompt": "0", "completion": "0"},
                }
            ),
            CatalogEntry(
                {
                    "id": "d/r1:free",
                    "name": "R1 Reasoner",
                    "pricing": {"prompt": "0", "completion": "0"},
                }
            ),
        ]
        by_cat = catalog.free_models_by_category()
        assert "coding" in by_cat
        assert "reasoning" in by_cat

    def test_needs_refresh_after_interval(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "c.json", refresh_hours=0.001)
        catalog._entries = [
            CatalogEntry({"id": "t/m", "name": "M", "pricing": {"prompt": "0", "completion": "0"}})
        ]
        catalog._last_refresh = 0.0  # Very old
        assert catalog.needs_refresh() is True

    def test_register_new_models(self, tmp_path):
        """Auto-register should add new free models to the registry."""
        from providers.registry import MODELS, ProviderRegistry

        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        catalog._entries = [
            CatalogEntry(
                {
                    "id": "new-provider/brand-new-model:free",
                    "name": "Brand New Model",
                    "pricing": {"prompt": "0", "completion": "0"},
                    "context_length": 200000,
                }
            ),
        ]

        registry = ProviderRegistry()
        key = "or-free-brand-new-model"

        # Clean up in case key exists from previous test runs
        MODELS.pop(key, None)

        new_keys = catalog.register_new_models(registry)
        assert key in new_keys

        # Verify it's in the registry
        spec = registry.get_model(key)
        assert spec.model_id == "new-provider/brand-new-model:free"
        assert spec.max_context_tokens == 200000

        # Clean up
        MODELS.pop(key, None)


class TestCheckAccount:
    @pytest.mark.asyncio
    async def test_no_key_returns_free_tier(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        result = await catalog.check_account(api_key="")
        assert result["is_free_tier"] is True
        assert result["error"] == "No API key provided"

    @pytest.mark.asyncio
    async def test_success_parses_response(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "c.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.raise_for_status = MagicMock()
        mock_resp.json.return_value = {
            "data": {
                "is_free_tier": False,
                "limit_remaining": 42.5,
                "rate_limit": {"requests": 200},
            }
        }

        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client):
            result = await catalog.check_account(api_key="sk-test-key")

        assert result["is_free_tier"] is False
        assert result["limit_remaining"] == 42.5
        assert result["error"] is None

    @pytest.mark.asyncio
    async def test_network_error_returns_safe_fallback(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "c.json")

        mock_client = AsyncMock()
        mock_client.get.side_effect = Exception("Connection refused")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client):
            result = await catalog.check_account(api_key="sk-test-key")

        assert result["is_free_tier"] is True
        assert "Connection refused" in result["error"]

    @pytest.mark.asyncio
    async def test_caches_within_interval(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "c.json", balance_check_hours=1.0)

        # Manually set cached status
        catalog._account_status = {
            "is_free_tier": False,
            "limit_remaining": 10.0,
            "rate_limit": {},
            "cached": False,
            "error": None,
        }
        catalog._account_last_checked = time.time()

        result = await catalog.check_account(api_key="sk-test")
        assert result["cached"] is True
        assert result["is_free_tier"] is False


class TestValidatePrimaryModels:
    def test_valid_model_returns_empty(self, tmp_path):
        """Models present in catalog should not be flagged."""
        from providers.registry import MODELS, ProviderRegistry

        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        # Add catalog entries for ALL registered OR free models so none are "missing"
        catalog._entries = [
            CatalogEntry(
                {"id": spec.model_id, "name": "M", "pricing": {"prompt": "0", "completion": "0"}}
            )
            for spec in MODELS.values()
            if spec.provider.value == "openrouter"
        ]

        result = catalog.validate_primary_models(ProviderRegistry())
        # All validated models should have no replacement (they exist in catalog)
        assert len(result) == 0

    def test_missing_model_gets_replacement(self, tmp_path):
        from providers.registry import MODELS, ModelSpec, ModelTier, ProviderRegistry, ProviderType

        catalog = ModelCatalog(cache_path=tmp_path / "c.json")

        # Register a fake model that won't be in catalog
        fake_key = "or-free-nonexistent-coder"
        MODELS[fake_key] = ModelSpec(
            model_id="fake/nonexistent-coder:free",
            provider=ProviderType.OPENROUTER,
            max_tokens=4096,
            display_name="Nonexistent Coder",
            tier=ModelTier.FREE,
        )

        # Catalog has a replacement coding model
        catalog._entries = [
            CatalogEntry(
                {
                    "id": "real/coder-model:free",
                    "name": "Real Coder Model",
                    "pricing": {"prompt": "0", "completion": "0"},
                    "context_length": 128000,
                }
            ),
        ]

        # Monkey-patch FREE_ROUTING to include our fake model
        from agents.model_router import FREE_ROUTING
        from core.task_queue import TaskType

        original = FREE_ROUTING.get(TaskType.CODING)
        FREE_ROUTING[TaskType.CODING] = {
            "primary": fake_key,
            "critic": None,
            "max_iterations": 8,
        }

        try:
            result = catalog.validate_primary_models(ProviderRegistry())
            assert fake_key in result
            assert result[fake_key] is not None  # Should have found replacement
        finally:
            FREE_ROUTING[TaskType.CODING] = original
            MODELS.pop(fake_key, None)


class TestRegisterPaidModels:
    def test_registers_affordable_model(self, tmp_path):
        from providers.registry import MODELS, ProviderRegistry

        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        catalog._entries = [
            CatalogEntry(
                {
                    "id": "test/affordable-paid-model",
                    "name": "Affordable Paid Model",
                    "pricing": {"prompt": "0.000001", "completion": "0.000002"},
                    "context_length": 128000,
                }
            ),
        ]

        registry = ProviderRegistry()
        new_keys = catalog.register_paid_models(registry, max_prompt_price_per_m=5.0)
        key = "or-paid-affordable-paid-model"
        assert key in new_keys
        spec = registry.get_model(key)
        assert spec.model_id == "test/affordable-paid-model"
        MODELS.pop(key, None)

    def test_skips_expensive_model(self, tmp_path):
        from providers.registry import ProviderRegistry

        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        catalog._entries = [
            CatalogEntry(
                {
                    "id": "test/expensive-model",
                    "name": "Expensive Model",
                    "pricing": {"prompt": "0.01", "completion": "0.02"},
                    "context_length": 128000,
                }
            ),
        ]

        registry = ProviderRegistry()
        new_keys = catalog.register_paid_models(registry, max_prompt_price_per_m=5.0)
        assert len(new_keys) == 0

    def test_skips_free_models(self, tmp_path):
        from providers.registry import ProviderRegistry

        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        catalog._entries = [
            CatalogEntry(
                {
                    "id": "test/free-model:free",
                    "name": "Free Model",
                    "pricing": {"prompt": "0", "completion": "0"},
                }
            ),
        ]

        registry = ProviderRegistry()
        new_keys = catalog.register_paid_models(registry)
        assert len(new_keys) == 0

    def test_tier_assignment(self, tmp_path):
        from providers.registry import MODELS, ModelTier, ProviderRegistry

        catalog = ModelCatalog(cache_path=tmp_path / "c.json")
        catalog._entries = [
            CatalogEntry(
                {
                    "id": "test/cheap-model",
                    "name": "Cheap",
                    "pricing": {"prompt": "0.0000005", "completion": "0.0000005"},
                    "context_length": 128000,
                }
            ),
            CatalogEntry(
                {
                    "id": "test/premium-model",
                    "name": "Premium",
                    "pricing": {"prompt": "0.000002", "completion": "0.000004"},
                    "context_length": 128000,
                }
            ),
        ]

        registry = ProviderRegistry()
        new_keys = catalog.register_paid_models(registry, max_prompt_price_per_m=5.0)
        assert "or-paid-cheap-model" in new_keys
        assert "or-paid-premium-model" in new_keys

        cheap_spec = registry.get_model("or-paid-cheap-model")
        premium_spec = registry.get_model("or-paid-premium-model")
        assert cheap_spec.tier == ModelTier.CHEAP
        assert premium_spec.tier == ModelTier.PREMIUM

        MODELS.pop("or-paid-cheap-model", None)
        MODELS.pop("or-paid-premium-model", None)


class TestSpendingTrackerPricing:
    def test_uses_actual_pricing(self):
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.update_model_prices({"test/model": (0.000003, 0.000006)})
        tracker.record_usage("key", 1000, 500, model_id="test/model")
        # Cost = 1000 * 0.000003 + 500 * 0.000006 = 0.003 + 0.003 = 0.006
        assert tracker.daily_spend_usd == pytest.approx(0.006, abs=0.0001)

    def test_free_model_zero_cost(self):
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.update_model_prices({"free/model:free": (0.0, 0.0)})
        tracker.record_usage("key", 10000, 5000, model_id="free/model:free")
        assert tracker.daily_spend_usd == 0.0

    def test_fallback_conservative_estimate(self):
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        # No model_id provided — should use conservative estimate
        tracker.record_usage("key", 1000, 500)
        expected = (1000 * 5.0 + 500 * 15.0) / 1_000_000
        assert tracker.daily_spend_usd == pytest.approx(expected, abs=0.0001)

"""Tests for agents/model_catalog.py — OpenRouter catalog sync and health checks."""

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


class TestCerebrasSpendingTracker:
    """Phase 1: Cerebras models should have $0 pricing in SpendingTracker."""

    def test_cerebras_builtin_prices_exist(self):
        """All 4 Cerebras model_ids have explicit $0 entries in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker

        expected_ids = [
            "gpt-oss-120b",
            "qwen-3-235b-a22b-instruct-2507",
            "llama3.1-8b",
            "zai-glm-4.7",
        ]
        for model_id in expected_ids:
            assert model_id in SpendingTracker._BUILTIN_PRICES, (
                f"{model_id} missing from _BUILTIN_PRICES"
            )
            prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES[model_id]
            assert prompt_price == 0.0
            assert completion_price == 0.0

    def test_cerebras_zero_cost_recording(self):
        """Recording Cerebras usage results in $0 spend."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("cerebras-gpt-oss-120b", 50000, 25000, model_id="gpt-oss-120b")
        assert tracker.daily_spend_usd == 0.0

    def test_cerebras_all_models_zero_cost(self):
        """All 4 Cerebras models record $0 cost."""
        from providers.registry import SpendingTracker

        models = [
            ("cerebras-gpt-oss-120b", "gpt-oss-120b"),
            ("cerebras-qwen3-235b", "qwen-3-235b-a22b-instruct-2507"),
            ("cerebras-llama-8b", "llama3.1-8b"),
            ("cerebras-zai-glm", "zai-glm-4.7"),
        ]
        tracker = SpendingTracker()
        for model_key, model_id in models:
            tracker.record_usage(model_key, 10000, 5000, model_id=model_id)
        assert tracker.daily_spend_usd == 0.0

    def test_cerebras_does_not_trip_spend_limit(self):
        """50 tasks of Cerebras usage should not trip a $1 spend limit."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        for _ in range(50):
            tracker.record_usage("cerebras-gpt-oss-120b", 10000, 5000, model_id="gpt-oss-120b")
        assert tracker.check_limit(1.0) is True
        assert tracker.daily_spend_usd == 0.0

    def test_cerebras_tokens_tracked(self):
        """Token counts are tracked even though cost is $0."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("cerebras-llama-8b", 1000, 500, model_id="llama3.1-8b")
        assert tracker.daily_tokens == 1500


class TestGroqSpendingTracker:
    """Phase 2: Groq models should have $0 pricing in SpendingTracker."""

    def test_groq_builtin_prices_exist(self):
        """All 3 Groq model_ids have explicit $0 entries in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker

        expected_ids = [
            "llama-3.3-70b-versatile",
            "openai/gpt-oss-120b",
            "llama-3.1-8b-instant",
        ]
        for model_id in expected_ids:
            assert model_id in SpendingTracker._BUILTIN_PRICES, (
                f"{model_id} missing from _BUILTIN_PRICES"
            )
            prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES[model_id]
            assert prompt_price == 0.0
            assert completion_price == 0.0

    def test_groq_zero_cost_recording(self):
        """Recording Groq usage results in $0 spend."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("groq-llama-70b", 50000, 25000,
                             model_id="llama-3.3-70b-versatile")
        assert tracker.daily_spend_usd == 0.0

    def test_groq_all_models_zero_cost(self):
        """All 3 Groq models record $0 cost (including openai/gpt-oss-120b with namespace prefix)."""
        from providers.registry import SpendingTracker

        models = [
            ("groq-llama-70b", "llama-3.3-70b-versatile"),
            ("groq-gpt-oss-120b", "openai/gpt-oss-120b"),
            ("groq-llama-8b", "llama-3.1-8b-instant"),
        ]
        tracker = SpendingTracker()
        for model_key, model_id in models:
            tracker.record_usage(model_key, 10000, 5000, model_id=model_id)
        assert tracker.daily_spend_usd == 0.0

    def test_groq_does_not_trip_spend_limit(self):
        """50 tasks of Groq usage should not trip a $1 spend limit."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        for _ in range(50):
            tracker.record_usage("groq-llama-70b", 8000, 2000,
                                 model_id="llama-3.3-70b-versatile")
        assert tracker.check_limit(1.0) is True
        assert tracker.daily_spend_usd == 0.0

    def test_groq_tokens_tracked(self):
        """Token counts are tracked even though cost is $0."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("groq-llama-8b", 1000, 500,
                             model_id="llama-3.1-8b-instant")
        assert tracker.daily_tokens == 1500


class TestMistralSpendingTracker:
    """Phase 3: Mistral models — $0 for Codestral, actual pricing for La Plateforme."""

    def test_codestral_builtin_prices_exist(self):
        """codestral-latest has explicit $0 entry in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker

        assert "codestral-latest" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["codestral-latest"]
        assert prompt_price == 0.0
        assert completion_price == 0.0

    def test_la_plateforme_builtin_prices_exist(self):
        """mistral-large-latest and mistral-small-latest have non-zero pricing entries."""
        from providers.registry import SpendingTracker

        for model_id in ["mistral-large-latest", "mistral-small-latest"]:
            assert model_id in SpendingTracker._BUILTIN_PRICES, (
                f"{model_id} missing from _BUILTIN_PRICES"
            )
            prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES[model_id]
            assert prompt_price > 0.0, f"{model_id} prompt price should be > 0"
            assert completion_price > 0.0, f"{model_id} completion price should be > 0"

    def test_codestral_zero_cost(self):
        """Codestral usage records $0 spend."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("mistral-codestral", 50000, 25000,
                             model_id="codestral-latest")
        assert tracker.daily_spend_usd == 0.0

    def test_mistral_large_incurs_cost(self):
        """mistral-large-latest usage records non-zero spend (not a free model)."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("mistral-large", 10000, 5000,
                             model_id="mistral-large-latest")
        assert tracker.daily_spend_usd > 0.0

    def test_mistral_tokens_tracked(self):
        """Token counts are tracked for both free and paid Mistral models."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("mistral-codestral", 1000, 500,
                             model_id="codestral-latest")
        tracker.record_usage("mistral-small", 1000, 500,
                             model_id="mistral-small-latest")
        assert tracker.daily_tokens == 3000


class TestSambanovaSpendingTracker:
    """Phase 4: SambaNova models — CHEAP tier, non-zero pricing."""

    def test_sambanova_llama_builtin_prices_exist(self):
        """Meta-Llama-3.3-70B-Instruct has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker

        assert "Meta-Llama-3.3-70B-Instruct" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["Meta-Llama-3.3-70B-Instruct"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_sambanova_deepseek_builtin_prices_exist(self):
        """DeepSeek-V3-0324 has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker

        assert "DeepSeek-V3-0324" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["DeepSeek-V3-0324"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_sambanova_llama_incurs_cost(self):
        """SambaNova Llama usage records non-zero spend."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("sambanova-llama-70b", 10000, 5000,
                             model_id="Meta-Llama-3.3-70B-Instruct")
        assert tracker.daily_spend_usd > 0.0

    def test_sambanova_deepseek_incurs_cost(self):
        """SambaNova DeepSeek usage records non-zero spend."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("sambanova-deepseek-v3", 10000, 5000,
                             model_id="DeepSeek-V3-0324")
        assert tracker.daily_spend_usd > 0.0

    def test_sambanova_tokens_tracked(self):
        """Token counts are tracked for SambaNova models."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("sambanova-llama-70b", 1000, 500,
                             model_id="Meta-Llama-3.3-70B-Instruct")
        assert tracker.daily_tokens == 1500


class TestTogetherSpendingTracker:
    """Phase 5: Together AI models -- CHEAP tier, non-zero pricing."""

    def test_together_llama_builtin_prices_exist(self):
        """meta-llama/Llama-3.3-70B-Instruct-Turbo has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker

        assert "meta-llama/Llama-3.3-70B-Instruct-Turbo" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["meta-llama/Llama-3.3-70B-Instruct-Turbo"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_together_deepseek_builtin_prices_exist(self):
        """deepseek-ai/DeepSeek-V3 has explicit pricing in _BUILTIN_PRICES."""
        from providers.registry import SpendingTracker

        assert "deepseek-ai/DeepSeek-V3" in SpendingTracker._BUILTIN_PRICES
        prompt_price, completion_price = SpendingTracker._BUILTIN_PRICES["deepseek-ai/DeepSeek-V3"]
        assert prompt_price > 0.0
        assert completion_price > 0.0

    def test_together_llama_incurs_cost(self):
        """Together AI Llama usage records non-zero spend."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("together-llama-70b", 10000, 5000,
                             model_id="meta-llama/Llama-3.3-70B-Instruct-Turbo")
        assert tracker.daily_spend_usd > 0.0

    def test_together_deepseek_incurs_cost(self):
        """Together AI DeepSeek usage records non-zero spend."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        tracker.record_usage("together-deepseek-v3", 10000, 5000,
                             model_id="deepseek-ai/DeepSeek-V3")
        assert tracker.daily_spend_usd > 0.0

    def test_together_not_free_model_detection(self):
        """Together AI model IDs don't match or-free- prefix or :free suffix -- must have explicit pricing."""
        from providers.registry import SpendingTracker

        tracker = SpendingTracker()
        # Confirm _get_price resolves to explicit entry, not $0 free detection
        price = tracker._get_price("together-llama-70b", "meta-llama/Llama-3.3-70B-Instruct-Turbo")
        assert price is not None
        assert price[0] > 0.0  # Not free


class TestHealthCheck:
    """Tests for model health check functionality."""

    def test_needs_health_check_when_empty(self, tmp_path):
        """Should need health check when no checks have been done."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        assert catalog.needs_health_check() is True

    def test_needs_health_check_after_interval(self, tmp_path):
        """Should need health check after the interval expires."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._health_status = {"some-model": {"status": "ok"}}
        catalog._last_health_check = time.time() - (7 * 3600)  # 7 hours ago
        assert catalog.needs_health_check() is True

    def test_no_health_check_within_interval(self, tmp_path):
        """Should NOT need health check within the interval."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._health_status = {"some-model": {"status": "ok"}}
        catalog._last_health_check = time.time() - (1 * 3600)  # 1 hour ago
        assert catalog.needs_health_check() is False

    def test_is_model_healthy_unchecked(self, tmp_path):
        """Unchecked models are assumed healthy (optimistic default)."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        assert catalog.is_model_healthy("never-checked-model") is True

    def test_is_model_healthy_ok(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._health_status = {
            "good-model": {"status": ModelCatalog.STATUS_OK, "latency_ms": 500}
        }
        assert catalog.is_model_healthy("good-model") is True

    def test_is_model_healthy_rate_limited(self, tmp_path):
        """Rate-limited models are still considered healthy (they exist, just throttled)."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._health_status = {"throttled-model": {"status": ModelCatalog.STATUS_RATE_LIMITED}}
        assert catalog.is_model_healthy("throttled-model") is True

    def test_is_model_unhealthy_unavailable(self, tmp_path):
        """404/unavailable models are unhealthy."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._health_status = {"dead-model": {"status": ModelCatalog.STATUS_UNAVAILABLE}}
        assert catalog.is_model_healthy("dead-model") is False

    def test_is_model_unhealthy_auth_error(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._health_status = {"auth-model": {"status": ModelCatalog.STATUS_AUTH_ERROR}}
        assert catalog.is_model_healthy("auth-model") is False

    def test_unhealthy_model_keys(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._health_status = {
            "ok-model": {"status": ModelCatalog.STATUS_OK},
            "dead-model": {"status": ModelCatalog.STATUS_UNAVAILABLE},
            "rate-model": {"status": ModelCatalog.STATUS_RATE_LIMITED},
            "err-model": {"status": ModelCatalog.STATUS_ERROR},
        }
        unhealthy = catalog.unhealthy_model_keys()
        assert "dead-model" in unhealthy
        assert "err-model" in unhealthy
        assert "ok-model" not in unhealthy
        assert "rate-model" not in unhealthy

    def test_health_summary(self, tmp_path):
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog._last_health_check = time.time()
        catalog._health_status = {
            "m1": {"status": "ok"},
            "m2": {"status": "ok"},
            "m3": {"status": "unavailable", "error": "404"},
        }
        summary = catalog.get_health_summary()
        assert summary["total_checked"] == 3
        assert summary["by_status"]["ok"] == 2
        assert summary["by_status"]["unavailable"] == 1
        assert len(summary["unhealthy_models"]) == 1
        assert summary["unhealthy_models"][0]["key"] == "m3"

    def test_health_cache_roundtrip(self, tmp_path):
        """Health status should persist and load from disk."""
        catalog1 = ModelCatalog(cache_path=tmp_path / "catalog.json")
        catalog1._health_status = {
            "model-a": {"status": "ok", "latency_ms": 200, "error": "", "last_checked": 1000.0},
            "model-b": {
                "status": "unavailable",
                "latency_ms": 50,
                "error": "404",
                "last_checked": 1000.0,
            },
        }
        catalog1._last_health_check = 1000.0
        catalog1._save_health_cache()

        catalog2 = ModelCatalog(cache_path=tmp_path / "catalog.json")
        assert len(catalog2._health_status) == 2
        assert catalog2._health_status["model-a"]["status"] == "ok"
        assert catalog2._health_status["model-b"]["status"] == "unavailable"
        assert catalog2._last_health_check == 1000.0

    @pytest.mark.asyncio
    async def test_ping_single_model_ok(self, tmp_path):
        """Successful ping returns STATUS_OK."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = '{"choices": [{"message": {"content": ""}}]}'

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client):
            result = await catalog._ping_single_model(
                "test/model:free", "https://api.example.com/v1", "sk-test"
            )

        assert result["status"] == ModelCatalog.STATUS_OK
        assert result["latency_ms"] >= 0

    @pytest.mark.asyncio
    async def test_ping_single_model_404(self, tmp_path):
        """404 response returns STATUS_UNAVAILABLE."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 404
        mock_resp.text = "No endpoints found"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client):
            result = await catalog._ping_single_model(
                "test/missing:free", "https://api.example.com/v1", "sk-test"
            )

        assert result["status"] == ModelCatalog.STATUS_UNAVAILABLE

    @pytest.mark.asyncio
    async def test_ping_single_model_429(self, tmp_path):
        """429 response returns STATUS_RATE_LIMITED."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 429
        mock_resp.text = "Rate limit exceeded"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client):
            result = await catalog._ping_single_model(
                "test/throttled:free", "https://api.example.com/v1", "sk-test"
            )

        assert result["status"] == ModelCatalog.STATUS_RATE_LIMITED

    @pytest.mark.asyncio
    async def test_ping_single_model_timeout(self, tmp_path):
        """Timeout returns STATUS_TIMEOUT."""
        import httpx as _httpx

        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")

        mock_client = AsyncMock()
        mock_client.post.side_effect = _httpx.TimeoutException("Request timed out")
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client):
            result = await catalog._ping_single_model(
                "test/slow:free", "https://api.example.com/v1", "sk-test"
            )

        assert result["status"] == ModelCatalog.STATUS_TIMEOUT

    @pytest.mark.asyncio
    async def test_health_check_no_keys(self, tmp_path):
        """Health check with no API keys configured does nothing."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")
        with patch.dict("os.environ", {}, clear=True):
            result = await catalog.health_check(api_key="")
        assert result == {}

    @pytest.mark.asyncio
    async def test_health_check_pings_or_models(self, tmp_path):
        """Health check pings registered free OR models."""
        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "{}"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client),
            patch.dict("os.environ", {"OPENROUTER_API_KEY": "sk-test-key"}),
        ):
            result = await catalog.health_check(api_key="sk-test-key")

        # Should have checked at least some OR free models
        assert len(result) > 0
        # All mocked as 200, so all should be OK
        for status in result.values():
            assert status["status"] == ModelCatalog.STATUS_OK


class TestHealthCheckCheapTier:
    """INFR-04: Verify CHEAP-tier models are included in health_check when API keys are set."""

    @pytest.mark.asyncio
    async def test_cheap_tier_included_in_health_check(self, tmp_path):
        """SambaNova and Together AI models are health-checked when their API keys are set."""
        import os

        from providers.registry import MODELS, ProviderType

        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "{}"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with (
            patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client),
            patch.dict(
                "os.environ",
                {
                    "SAMBANOVA_API_KEY": "test-sambanova-key",
                    "TOGETHER_API_KEY": "test-together-key",
                },
            ),
        ):
            result = await catalog.health_check()

        # Verify SambaNova and Together AI model keys appear in health check results
        checked_keys = set(result.keys())
        sambanova_keys = {
            k for k, spec in MODELS.items() if spec.provider == ProviderType.SAMBANOVA
        }
        together_keys = {
            k for k, spec in MODELS.items() if spec.provider == ProviderType.TOGETHER
        }

        # At least one SambaNova and one Together AI model should have been checked
        assert len(sambanova_keys & checked_keys) > 0, (
            f"No SambaNova models in health check results. Checked: {checked_keys}"
        )
        assert len(together_keys & checked_keys) > 0, (
            f"No Together AI models in health check results. Checked: {checked_keys}"
        )

    @pytest.mark.asyncio
    async def test_cheap_tier_skipped_without_key(self, tmp_path):
        """SambaNova models are not health-checked when SAMBANOVA_API_KEY is absent."""
        from providers.registry import MODELS, ProviderType

        catalog = ModelCatalog(cache_path=tmp_path / "catalog.json")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "{}"

        mock_client = AsyncMock()
        mock_client.post.return_value = mock_resp
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        # Do NOT set SAMBANOVA_API_KEY or TOGETHER_API_KEY
        env_clear = {
            "SAMBANOVA_API_KEY": "",
            "TOGETHER_API_KEY": "",
            "GEMINI_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "CEREBRAS_API_KEY": "",
            "GROQ_API_KEY": "",
            "CODESTRAL_API_KEY": "",
            "MISTRAL_API_KEY": "",
        }

        with (
            patch("agents.model_catalog.httpx.AsyncClient", return_value=mock_client),
            patch.dict("os.environ", env_clear),
        ):
            result = await catalog.health_check()

        # No models should be checked when all keys are absent (empty string = not set)
        checked_keys = set(result.keys())
        sambanova_keys = {
            k for k, spec in MODELS.items() if spec.provider == ProviderType.SAMBANOVA
        }
        together_keys = {
            k for k, spec in MODELS.items() if spec.provider == ProviderType.TOGETHER
        }

        assert len(sambanova_keys & checked_keys) == 0, (
            f"SambaNova models checked without API key: {sambanova_keys & checked_keys}"
        )
        assert len(together_keys & checked_keys) == 0, (
            f"Together AI models checked without API key: {together_keys & checked_keys}"
        )

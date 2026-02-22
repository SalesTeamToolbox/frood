"""Tests for agents/model_catalog.py — OpenRouter catalog sync."""



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

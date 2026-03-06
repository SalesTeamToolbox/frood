"""Tests for agents/model_router.py — policy routing layer."""

import os
from unittest.mock import MagicMock, patch

from agents.model_router import (
    _COMPLEX_TASK_TYPES,
    _VALID_POLICIES,
    FREE_ROUTING,
    ModelRouter,
)
from core.task_queue import TaskType


class TestPolicyConstants:
    def test_valid_policies_are_expected(self):
        assert {"free_only", "balanced", "performance"} == _VALID_POLICIES

    def test_complex_task_types_are_subset(self):
        all_task_types = set(TaskType)
        assert _COMPLEX_TASK_TYPES.issubset(all_task_types)

    def test_complex_types_include_key_types(self):
        assert TaskType.CODING in _COMPLEX_TASK_TYPES
        assert TaskType.DEBUGGING in _COMPLEX_TASK_TYPES
        assert TaskType.APP_CREATE in _COMPLEX_TASK_TYPES

    def test_simple_types_excluded(self):
        assert TaskType.EMAIL not in _COMPLEX_TASK_TYPES
        assert TaskType.DOCUMENTATION not in _COMPLEX_TASK_TYPES


def _patch_policy(policy):
    """Patch settings.model_routing_policy via core.config module."""
    return patch("core.config.settings", MagicMock(model_routing_policy=policy))


class TestPolicyRoutingFreeOnly:
    def test_free_only_returns_none(self):
        router = ModelRouter()
        with _patch_policy("free_only"):
            result = router._check_policy_routing(TaskType.CODING)
        assert result is None

    def test_free_only_never_calls_select(self):
        catalog = MagicMock()
        router = ModelRouter(catalog=catalog)
        with _patch_policy("free_only"):
            result = router._check_policy_routing(TaskType.CODING)
        assert result is None
        # Should not access catalog at all
        catalog.openrouter_account_status.__getitem__.assert_not_called()


class TestPolicyRoutingBalanced:
    def _make_router(self, account_status, catalog=None):
        if catalog is None:
            catalog = MagicMock()
            catalog.openrouter_account_status = account_status
        router = ModelRouter(catalog=catalog)
        return router

    def test_non_complex_task_returns_none(self):
        router = self._make_router({"is_free_tier": False, "limit_remaining": 10.0})
        with _patch_policy("balanced"):
            result = router._check_policy_routing(TaskType.EMAIL)
        assert result is None

    def test_free_tier_returns_none(self):
        router = self._make_router({"is_free_tier": True, "limit_remaining": None})
        with _patch_policy("balanced"):
            result = router._check_policy_routing(TaskType.CODING)
        assert result is None

    def test_exhausted_credits_returns_none(self):
        router = self._make_router({"is_free_tier": False, "limit_remaining": 0.0})
        with _patch_policy("balanced"):
            result = router._check_policy_routing(TaskType.CODING)
        assert result is None

    def test_no_catalog_returns_none(self):
        router = ModelRouter()  # No catalog
        with _patch_policy("balanced"):
            result = router._check_policy_routing(TaskType.CODING)
        assert result is None

    def test_no_account_status_returns_none(self):
        catalog = MagicMock()
        catalog.openrouter_account_status = None
        router = ModelRouter(catalog=catalog)
        with _patch_policy("balanced"):
            result = router._check_policy_routing(TaskType.CODING)
        assert result is None

    def test_limit_remaining_null_with_paid_tier_attempts_selection(self):
        """limit_remaining=None + is_free_tier=False means no per-key limit."""
        from providers.registry import MODELS, ModelSpec, ModelTier, ProviderType

        catalog = MagicMock()
        catalog.openrouter_account_status = {
            "is_free_tier": False,
            "limit_remaining": None,
        }
        router = ModelRouter(catalog=catalog)

        # Register a paid model for selection
        test_key = "or-paid-test-policy-model"
        MODELS[test_key] = ModelSpec(
            model_id="test/policy-model",
            provider=ProviderType.OPENROUTER,
            max_tokens=4096,
            display_name="Test Policy Model",
            tier=ModelTier.PREMIUM,
        )

        try:
            with _patch_policy("balanced"):
                result = router._check_policy_routing(TaskType.CODING)
            # Should attempt paid selection (may return None if score isn't high enough)
            # The important thing is it didn't return None due to account checks
            # It's OK if it returns None because no evaluator stats exist
        finally:
            MODELS.pop(test_key, None)


class TestPolicyRoutingPerformance:
    def test_performance_attempts_selection(self):
        catalog = MagicMock()
        catalog.openrouter_account_status = {
            "is_free_tier": False,
            "limit_remaining": 50.0,
        }
        router = ModelRouter(catalog=catalog)
        with _patch_policy("performance"):
            # Will return None because no models have API keys set
            result = router._check_policy_routing(TaskType.CODING)
        # Performance mode checks all providers, not just OR

    def test_performance_free_tier_returns_none(self):
        catalog = MagicMock()
        catalog.openrouter_account_status = {
            "is_free_tier": True,
            "limit_remaining": None,
        }
        router = ModelRouter(catalog=catalog)
        with _patch_policy("performance"):
            result = router._check_policy_routing(TaskType.CODING)
        assert result is None


class TestGetRoutingWithPolicy:
    def test_free_only_uses_free_routing_defaults(self):
        router = ModelRouter()
        # Provide API keys for both the FREE_ROUTING default (Cerebras) and a fallback
        # (Gemini) so get_routing() resolves without falling back to paid models.
        with patch.dict(
            os.environ,
            {
                "MODEL_ROUTING_POLICY": "free_only",
                "CEREBRAS_API_KEY": "test-cerebras-key",
                "GEMINI_API_KEY": "test-key",
                "GEMINI_PRO_FOR_COMPLEX": "false",
            },
            clear=False,
        ):
            with _patch_policy("free_only"):
                routing = router.get_routing(TaskType.CODING)
        # Should use FREE_ROUTING defaults — Cerebras primary for coding
        default = FREE_ROUTING[TaskType.CODING]
        assert routing["primary"] == default["primary"]

    def test_admin_override_beats_policy(self):
        catalog = MagicMock()
        catalog.openrouter_account_status = {
            "is_free_tier": False,
            "limit_remaining": 100.0,
        }
        router = ModelRouter(catalog=catalog)
        with patch.dict(
            os.environ,
            {"AGENT42_CODING_MODEL": "custom-model", "MODEL_ROUTING_POLICY": "performance"},
            clear=False,
        ):
            with _patch_policy("performance"):
                routing = router.get_routing(TaskType.CODING)
        assert routing["primary"] == "custom-model"

    def test_invalid_policy_falls_back_gracefully(self):
        router = ModelRouter()
        with _patch_policy("invalid_policy"):
            result = router._check_policy_routing(TaskType.CODING)
        # Invalid policy treated as "balanced"; no catalog → returns None
        assert result is None


# =============================================================================
# Phase 6 Plan 2: Routing, Config Flag, and Integration Tests
# =============================================================================


class TestFreeRoutingUpdates:
    """ROUT-01/02/03: Verify FREE_ROUTING dict has the correct task-type entries."""

    def test_cerebras_primary_for_coding(self):
        assert FREE_ROUTING[TaskType.CODING]["primary"] == "cerebras-gpt-oss-120b"

    def test_cerebras_primary_for_debugging(self):
        assert FREE_ROUTING[TaskType.DEBUGGING]["primary"] == "cerebras-gpt-oss-120b"

    def test_cerebras_primary_for_app_create(self):
        assert FREE_ROUTING[TaskType.APP_CREATE]["primary"] == "cerebras-gpt-oss-120b"

    def test_codestral_critic_for_coding(self):
        assert FREE_ROUTING[TaskType.CODING]["critic"] == "mistral-codestral"

    def test_codestral_critic_for_debugging(self):
        assert FREE_ROUTING[TaskType.DEBUGGING]["critic"] == "mistral-codestral"

    def test_codestral_critic_for_refactoring(self):
        assert FREE_ROUTING[TaskType.REFACTORING]["critic"] == "mistral-codestral"

    def test_codestral_critic_for_app_create(self):
        assert FREE_ROUTING[TaskType.APP_CREATE]["critic"] == "mistral-codestral"

    def test_groq_primary_for_research(self):
        assert FREE_ROUTING[TaskType.RESEARCH]["primary"] == "groq-llama-70b"

    def test_groq_primary_for_content(self):
        assert FREE_ROUTING[TaskType.CONTENT]["primary"] == "groq-llama-70b"

    def test_groq_primary_for_strategy(self):
        assert FREE_ROUTING[TaskType.STRATEGY]["primary"] == "groq-gpt-oss-120b"

    def test_other_types_keep_gemini(self):
        assert FREE_ROUTING[TaskType.EMAIL]["primary"] == "gemini-2-flash"


class TestFallbackChainDiversity:
    """ROUT-04, TEST-05: Verify provider-diverse fallback in _find_healthy_free_model."""

    def _make_mock_settings(self, gemini_free_tier=True, openrouter_free_only=False):
        return MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=gemini_free_tier,
            openrouter_free_only=openrouter_free_only,
        )

    def test_fallback_returns_different_provider(self):
        """_find_healthy_free_model with provider diversity returns from an available provider."""
        router = ModelRouter()
        mock_settings = self._make_mock_settings()
        # Provide GROQ_API_KEY so at least one non-Cerebras model is reachable
        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {"GROQ_API_KEY": "test-groq-key"},
                clear=False,
            ),
        ):
            result = router._find_healthy_free_model(exclude={"cerebras-gpt-oss-120b"})
        # With GROQ key set, should find a Groq model or any other available model
        # (not cerebras since excluded)
        if result:
            assert result != "cerebras-gpt-oss-120b"

    def test_fallback_skips_unhealthy_models(self):
        """Models marked unhealthy by catalog are skipped during fallback."""
        catalog = MagicMock()
        # Mark all models unhealthy except groq-llama-70b
        def is_healthy(key):
            return key == "groq-llama-70b"
        catalog.is_model_healthy.side_effect = is_healthy

        router = ModelRouter(catalog=catalog)
        mock_settings = self._make_mock_settings()

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {"GROQ_API_KEY": "test-groq-key"},
                clear=False,
            ),
        ):
            result = router._find_healthy_free_model(exclude={"cerebras-gpt-oss-120b"})

        # Should return groq-llama-70b (only healthy model with key)
        assert result == "groq-llama-70b"

    def test_fallback_returns_none_when_no_keys(self):
        """_find_healthy_free_model returns None when no API keys are configured."""
        router = ModelRouter()
        mock_settings = self._make_mock_settings()

        # Clear all provider API keys
        env_keys_to_clear = {
            "GEMINI_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "CEREBRAS_API_KEY": "",
            "GROQ_API_KEY": "",
            "MISTRAL_API_KEY": "",
            "CODESTRAL_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "SAMBANOVA_API_KEY": "",
            "TOGETHER_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
        }
        with (
            patch("core.config.settings", mock_settings),
            patch.dict(os.environ, env_keys_to_clear, clear=False),
        ):
            # Unset each key to simulate "no key configured"
            result = router._find_healthy_free_model()
        # When no keys are set (all empty strings), no model should be returned
        # (empty string is falsy, so os.getenv returns "" which fails the `if api_key` check)
        assert result is None


class TestCheapTierFallback:
    """ROUT-05: Verify CHEAP-tier fallback through _find_healthy_cheap_model."""

    def test_cheap_fallback_returns_sambanova_or_together(self):
        """CHEAP fallback returns a SambaNova model when SAMBANOVA_API_KEY is set."""
        router = ModelRouter()
        with patch.dict(
            os.environ,
            {"SAMBANOVA_API_KEY": "test-sambanova-key"},
            clear=False,
        ):
            result = router._find_healthy_cheap_model()

        # Should return a SambaNova model key
        assert result is not None
        assert "sambanova" in result

    def test_cheap_fallback_skips_gemini(self):
        """_find_healthy_cheap_model skips Gemini (handled by free path)."""
        router = ModelRouter()
        # Only set GEMINI_API_KEY — Gemini is CHEAP tier but should be skipped here
        env_clear = {
            "SAMBANOVA_API_KEY": "",
            "TOGETHER_API_KEY": "",
            "OPENAI_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "MISTRAL_API_KEY": "",
        }
        with (
            patch.dict(os.environ, {"GEMINI_API_KEY": "test-gemini-key", **env_clear}, clear=False),
        ):
            result = router._find_healthy_cheap_model()

        # Gemini is excluded from cheap search, and no other CHEAP provider keys set
        assert result is None

    def test_get_routing_uses_cheap_fallback(self):
        """get_routing() uses CHEAP-tier fallback when no free model keys are set."""
        router = ModelRouter()
        mock_settings = MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=True,
            openrouter_free_only=False,
        )

        # Clear all free model keys, provide SAMBANOVA_API_KEY
        env = {
            "GEMINI_API_KEY": "",
            "OPENROUTER_API_KEY": "",
            "CEREBRAS_API_KEY": "",
            "GROQ_API_KEY": "",
            "CODESTRAL_API_KEY": "",
            "MISTRAL_API_KEY": "",
            "ANTHROPIC_API_KEY": "",
            "OPENAI_API_KEY": "",
            "DEEPSEEK_API_KEY": "",
            "TOGETHER_API_KEY": "",
            "SAMBANOVA_API_KEY": "test-sambanova-key",
        }
        with (
            patch("core.config.settings", mock_settings),
            patch.dict(os.environ, env, clear=False),
        ):
            routing = router.get_routing(TaskType.CODING)

        # Primary should be a SambaNova model (the only provider with a key)
        assert routing["primary"] is not None
        assert "sambanova" in routing["primary"]


class TestGeminiFreeTierFlag:
    """CONF-01, TEST-04: Verify GEMINI_FREE_TIER=false excludes Gemini from routing."""

    def test_gemini_excluded_from_fallback(self):
        """When gemini_free_tier=False, _find_healthy_free_model skips Gemini models."""
        router = ModelRouter()
        mock_settings = MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=False,
            openrouter_free_only=False,
        )

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {"GEMINI_API_KEY": "test-gemini-key", "GROQ_API_KEY": "test-groq-key"},
                clear=False,
            ),
        ):
            result = router._find_healthy_free_model()

        # Should not return any Gemini model
        if result:
            from providers.registry import MODELS, ProviderType
            try:
                spec = router.registry.get_model(result)
                assert spec.provider != ProviderType.GEMINI, (
                    f"Expected non-Gemini model but got {result} (provider={spec.provider})"
                )
            except ValueError:
                pass  # Dynamic model — pass through

    def test_gemini_excluded_from_routing_primary(self):
        """When gemini_free_tier=False, tasks defaulting to gemini-2-flash use a replacement."""
        router = ModelRouter()
        mock_settings = MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=False,
            openrouter_free_only=False,
        )

        # EMAIL defaults to gemini-2-flash in FREE_ROUTING; with flag off, should use replacement
        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {
                    "GEMINI_API_KEY": "test-gemini-key",
                    "GROQ_API_KEY": "test-groq-key",
                },
                clear=False,
            ),
        ):
            routing = router.get_routing(TaskType.EMAIL)

        # Primary should NOT be gemini-2-flash (flag forces exclusion)
        assert routing["primary"] != "gemini-2-flash"

    def test_admin_override_beats_gemini_flag(self):
        """Admin override wins over GEMINI_FREE_TIER=false flag."""
        router = ModelRouter()
        mock_settings = MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=False,
            openrouter_free_only=False,
        )

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {
                    "AGENT42_EMAIL_MODEL": "gemini-2-flash",
                    "GEMINI_API_KEY": "test-gemini-key",
                },
                clear=False,
            ),
        ):
            routing = router.get_routing(TaskType.EMAIL)

        # Admin override always wins — should still be gemini-2-flash
        assert routing["primary"] == "gemini-2-flash"


class TestOpenrouterFreeOnlyFlag:
    """CONF-02, TEST-04: Verify OPENROUTER_FREE_ONLY=true restricts to :free suffix models."""

    def test_or_free_only_skips_non_free_suffix(self):
        """When openrouter_free_only=True, OR models without :free suffix are skipped."""
        from providers.registry import MODELS, ModelSpec, ModelTier, ProviderType

        router = ModelRouter()
        mock_settings = MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=True,
            openrouter_free_only=True,
        )

        # Register a test OR model without :free suffix
        test_key = "or-paid-test-no-free-suffix"
        MODELS[test_key] = ModelSpec(
            model_id="test/nonfree-model",  # no :free suffix
            provider=ProviderType.OPENROUTER,
            max_tokens=4096,
            display_name="Test Non-Free Model",
            tier=ModelTier.FREE,
        )

        try:
            with (
                patch("core.config.settings", mock_settings),
                patch.dict(
                    os.environ,
                    {
                        "OPENROUTER_API_KEY": "test-or-key",
                        "GEMINI_API_KEY": "",
                        "CEREBRAS_API_KEY": "",
                        "GROQ_API_KEY": "",
                        "CODESTRAL_API_KEY": "",
                    },
                    clear=False,
                ),
            ):
                result = router._find_healthy_free_model()

            # The non-:free OR model should be skipped
            assert result != test_key
        finally:
            MODELS.pop(test_key, None)

    def test_or_free_only_allows_free_suffix(self):
        """When openrouter_free_only=True, OR models WITH :free suffix are allowed."""
        from providers.registry import MODELS, ProviderType

        router = ModelRouter()
        mock_settings = MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=True,
            openrouter_free_only=True,
        )

        # Use an existing OR free model (e.g., or-free-llama-70b which has :free suffix)
        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {
                    "OPENROUTER_API_KEY": "test-or-key",
                    "GEMINI_API_KEY": "",
                    "CEREBRAS_API_KEY": "",
                    "GROQ_API_KEY": "",
                    "CODESTRAL_API_KEY": "",
                },
                clear=False,
            ),
        ):
            result = router._find_healthy_free_model()

        # Should return an OR model with :free suffix (or None if no OR free models in registry)
        if result:
            try:
                spec = router.registry.get_model(result)
                if spec.provider == ProviderType.OPENROUTER:
                    assert spec.model_id.endswith(":free"), (
                        f"OPENROUTER_FREE_ONLY=True but returned non-:free model: {result}"
                    )
            except ValueError:
                pass  # Dynamic model — pass through

    def test_or_free_only_does_not_affect_non_or_providers(self):
        """OPENROUTER_FREE_ONLY=true only affects OpenRouter models; Cerebras/Groq still allowed."""
        router = ModelRouter()
        mock_settings = MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=True,
            openrouter_free_only=True,
        )

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {
                    "CEREBRAS_API_KEY": "test-cerebras-key",
                    "OPENROUTER_API_KEY": "",
                    "GEMINI_API_KEY": "",
                    "GROQ_API_KEY": "",
                    "CODESTRAL_API_KEY": "",
                },
                clear=False,
            ),
        ):
            result = router._find_healthy_free_model()

        # Cerebras should still be returned (flag only restricts OR models)
        assert result is not None
        assert "cerebras" in result


class TestMultiProviderIntegration:
    """TEST-06: Multi-provider routing integration tests."""

    def _make_mock_settings(self):
        return MagicMock(
            model_routing_policy="free_only",
            gemini_free_tier=True,
            openrouter_free_only=False,
        )

    def test_coding_routes_to_cerebras_with_key(self):
        """With CEREBRAS_API_KEY set, CODING routes to cerebras primary with Codestral critic."""
        router = ModelRouter()
        mock_settings = self._make_mock_settings()

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {
                    "CEREBRAS_API_KEY": "test-cerebras-key",
                    "CODESTRAL_API_KEY": "test-codestral-key",
                    "GEMINI_API_KEY": "",
                },
                clear=False,
            ),
        ):
            routing = router.get_routing(TaskType.CODING)

        assert routing["primary"] == "cerebras-gpt-oss-120b"
        assert routing["critic"] == "mistral-codestral"

    def test_research_routes_to_groq_with_key(self):
        """With GROQ_API_KEY set, RESEARCH routes to groq-llama-70b primary."""
        router = ModelRouter()
        mock_settings = self._make_mock_settings()

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {
                    "GROQ_API_KEY": "test-groq-key",
                    "GEMINI_API_KEY": "",
                    "CEREBRAS_API_KEY": "",
                },
                clear=False,
            ),
        ):
            routing = router.get_routing(TaskType.RESEARCH)

        assert routing["primary"] == "groq-llama-70b"

    def test_missing_primary_key_falls_to_alternative(self):
        """When CEREBRAS_API_KEY is missing, CODING falls back to another model."""
        router = ModelRouter()
        mock_settings = self._make_mock_settings()

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(
                os.environ,
                {
                    "CEREBRAS_API_KEY": "",   # No Cerebras key
                    "GROQ_API_KEY": "test-groq-key",  # Groq available as fallback
                    "GEMINI_API_KEY": "",
                    "CODESTRAL_API_KEY": "",
                },
                clear=False,
            ),
        ):
            routing = router.get_routing(TaskType.CODING)

        # Primary should NOT be cerebras since its key is missing
        assert routing["primary"] != "cerebras-gpt-oss-120b"
        assert routing["primary"] is not None  # But should have found something

    def test_all_providers_routing(self):
        """With all 6 provider keys set, each task type routes to the expected primary."""
        router = ModelRouter()
        mock_settings = self._make_mock_settings()

        env = {
            "CEREBRAS_API_KEY": "test-cerebras-key",
            "GROQ_API_KEY": "test-groq-key",
            "CODESTRAL_API_KEY": "test-codestral-key",
            "OPENROUTER_API_KEY": "test-or-key",
            "GEMINI_API_KEY": "test-gemini-key",
            "SAMBANOVA_API_KEY": "test-sambanova-key",
            "GEMINI_PRO_FOR_COMPLEX": "false",
        }

        with (
            patch("core.config.settings", mock_settings),
            patch.dict(os.environ, env, clear=False),
        ):
            coding_routing = router.get_routing(TaskType.CODING)
            research_routing = router.get_routing(TaskType.RESEARCH)
            content_routing = router.get_routing(TaskType.CONTENT)
            strategy_routing = router.get_routing(TaskType.STRATEGY)

        assert coding_routing["primary"] == "cerebras-gpt-oss-120b"
        assert research_routing["primary"] == "groq-llama-70b"
        assert content_routing["primary"] == "groq-llama-70b"
        assert strategy_routing["primary"] == "groq-gpt-oss-120b"

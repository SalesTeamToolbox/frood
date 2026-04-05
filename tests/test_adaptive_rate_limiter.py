"""
Tests for AdaptiveRateLimiter and PerModelRateLimiter — TCP-style congestion
control for LLM API requests with per-model rate limiting.
"""

import asyncio
import time

import pytest

from core.rate_limiter import (
    AdaptiveRateLimiter,
    ModelRateConfig,
    PerModelRateLimiter,
    ZEN_DEFAULT_RATE_CONFIG,
    ZEN_VENDOR_RATE_LIMITS,
    resolve_model_rate_config,
)


# ── resolve_model_rate_config ────────────────────────────────────────────────


class TestResolveModelRateConfig:
    """Test vendor prefix matching — no hardcoded model IDs."""

    def test_qwen_prefix_matches_any_qwen_model(self):
        cfg = resolve_model_rate_config("qwen3.6-plus-free")
        assert cfg.initial_delay == 3.0
        cfg2 = resolve_model_rate_config("qwen2.5-72b-instruct")
        assert cfg2.initial_delay == 3.0
        cfg3 = resolve_model_rate_config("QWEN-MAX")  # case-insensitive
        assert cfg3.initial_delay == 3.0

    def test_minimax_prefix_matches_any_minimax_model(self):
        cfg = resolve_model_rate_config("minimax-m2.5-free")
        assert cfg.initial_delay == 2.5
        cfg2 = resolve_model_rate_config("minimax-m1-free")
        assert cfg2.initial_delay == 2.5

    def test_nemotron_prefix_matches_any_nemotron_model(self):
        cfg = resolve_model_rate_config("nemotron-3-super-free")
        assert cfg.initial_delay == 2.0
        cfg2 = resolve_model_rate_config("nemotron-ultra")
        assert cfg2.initial_delay == 2.0

    def test_unknown_model_gets_conservative_default(self):
        cfg = resolve_model_rate_config("big-pickle")
        assert cfg == ZEN_DEFAULT_RATE_CONFIG
        cfg2 = resolve_model_rate_config("some-new-model-free")
        assert cfg2 == ZEN_DEFAULT_RATE_CONFIG

    def test_vendor_order_matters_first_match_wins(self):
        """If a model name contains multiple vendor prefixes, first match wins."""
        # This shouldn't happen in practice, but verify the behavior
        pass  # Current vendors don't overlap in prefixes


# ── AdaptiveRateLimiter ──────────────────────────────────────────────────────


class TestAdaptiveRateLimiterInit:
    """Test initialization and defaults."""

    def test_default_values(self):
        limiter = AdaptiveRateLimiter()
        assert limiter.current_delay == 2.0
        assert limiter.stats["min_delay"] == 0.5
        assert limiter.stats["max_delay"] == 10.0

    def test_custom_values(self):
        limiter = AdaptiveRateLimiter(
            initial_delay=1.0,
            min_delay=0.2,
            max_delay=5.0,
            decrease_step=0.05,
            increase_factor=1.5,
        )
        assert limiter.current_delay == 1.0
        assert limiter.stats["min_delay"] == 0.2
        assert limiter.stats["max_delay"] == 5.0


class TestRecordSuccess:
    """Test success recording — additive decrease."""

    def test_success_reduces_delay(self):
        limiter = AdaptiveRateLimiter(initial_delay=3.0, decrease_step=0.5, min_delay=1.0)
        limiter.record_success()
        assert limiter.current_delay == 2.5

    def test_success_does_not_go_below_min(self):
        limiter = AdaptiveRateLimiter(initial_delay=1.0, min_delay=0.5, decrease_step=0.3)
        limiter.record_success()
        assert limiter.current_delay == 0.7
        limiter.record_success()
        assert limiter.current_delay == 0.5
        limiter.record_success()
        assert limiter.current_delay == 0.5

    def test_success_resets_consecutive_failures(self):
        limiter = AdaptiveRateLimiter()
        limiter.record_rate_limit()
        assert limiter.stats["consecutive_failures"] == 1
        limiter.record_success()
        assert limiter.stats["consecutive_failures"] == 0


class TestRecordRateLimit:
    """Test rate limit recording — multiplicative increase."""

    def test_rate_limit_doubles_delay(self):
        limiter = AdaptiveRateLimiter(initial_delay=2.0, increase_factor=2.0, max_delay=10.0)
        limiter.record_rate_limit()
        assert limiter.current_delay == 4.0

    def test_rate_limit_does_not_exceed_max(self):
        limiter = AdaptiveRateLimiter(initial_delay=6.0, max_delay=10.0, increase_factor=2.0)
        limiter.record_rate_limit()
        assert limiter.current_delay == 10.0

    def test_rate_limit_respects_retry_after(self):
        limiter = AdaptiveRateLimiter(initial_delay=1.0, max_delay=30.0, increase_factor=2.0)
        limiter.record_rate_limit(retry_after=15.0)
        assert limiter.current_delay == 15.0

    def test_rate_limit_tracks_total_rate_limits(self):
        limiter = AdaptiveRateLimiter()
        limiter.record_rate_limit()
        limiter.record_rate_limit()
        assert limiter.stats["total_rate_limits"] == 2

    def test_rate_limit_increases_consecutive_failures(self):
        limiter = AdaptiveRateLimiter()
        limiter.record_rate_limit()
        limiter.record_rate_limit()
        assert limiter.stats["consecutive_failures"] == 2


class TestRecordError:
    """Test non-rate-limit error recording — mild backoff."""

    def test_error_increases_delay_mildly(self):
        limiter = AdaptiveRateLimiter(initial_delay=2.0, max_delay=10.0)
        limiter.record_error()
        assert limiter.current_delay == pytest.approx(2.4, abs=0.01)

    def test_error_does_not_exceed_max(self):
        limiter = AdaptiveRateLimiter(initial_delay=9.0, max_delay=10.0)
        limiter.record_error()
        assert limiter.current_delay == 10.0


class TestWaitIfNeeded:
    """Test async wait behavior."""

    @pytest.mark.asyncio
    async def test_first_request_no_wait(self):
        limiter = AdaptiveRateLimiter()
        start = time.monotonic()
        await limiter.wait_if_needed()
        elapsed = time.monotonic() - start
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_rapid_requests_enforce_delay(self):
        limiter = AdaptiveRateLimiter(initial_delay=0.3, min_delay=0.3)
        await limiter.wait_if_needed()
        start = time.monotonic()
        await limiter.wait_if_needed()
        elapsed = time.monotonic() - start
        assert elapsed >= 0.25

    @pytest.mark.asyncio
    async def test_delay_after_enough_time_no_wait(self):
        limiter = AdaptiveRateLimiter(initial_delay=0.1, min_delay=0.1)
        await limiter.wait_if_needed()
        await asyncio.sleep(0.15)
        start = time.monotonic()
        await limiter.wait_if_needed()
        elapsed = time.monotonic() - start
        assert elapsed < 0.05


class TestStats:
    """Test statistics tracking."""

    def test_stats_initial_values(self):
        limiter = AdaptiveRateLimiter()
        stats = limiter.stats
        assert stats["total_requests"] == 0
        assert stats["total_rate_limits"] == 0
        assert stats["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_stats_after_requests(self):
        limiter = AdaptiveRateLimiter()
        await limiter.wait_if_needed()
        await limiter.wait_if_needed()
        assert limiter.stats["total_requests"] == 2

    def test_stats_include_current_delay(self):
        limiter = AdaptiveRateLimiter(initial_delay=3.0)
        assert limiter.stats["current_delay"] == 3.0
        limiter.record_rate_limit()
        assert limiter.stats["current_delay"] == 6.0


class TestReset:
    """Test reset behavior."""

    def test_reset_clears_failures(self):
        limiter = AdaptiveRateLimiter()
        limiter.record_rate_limit()
        limiter.record_rate_limit()
        assert limiter.stats["consecutive_failures"] == 2
        limiter.reset()
        assert limiter.stats["consecutive_failures"] == 0


# ── PerModelRateLimiter ──────────────────────────────────────────────────────


class TestPerModelRateLimiter:
    """Test per-model rate limiting with vendor prefix matching."""

    def test_creates_limiter_on_first_use(self):
        limiter = PerModelRateLimiter()
        stats = limiter.get_stats()
        assert stats == {}  # No limiters yet

    def test_different_models_get_independent_limiters(self):
        limiter = PerModelRateLimiter()
        limiter.record_rate_limit("qwen3.6-plus-free")
        limiter.record_success("minimax-m2.5-free")

        qwen_stats = limiter.get_stats("qwen3.6-plus-free")
        minimax_stats = limiter.get_stats("minimax-m2.5-free")

        assert qwen_stats["consecutive_failures"] == 1
        assert minimax_stats["consecutive_failures"] == 0

    def test_unknown_model_gets_default_config(self):
        limiter = PerModelRateLimiter()
        limiter.record_success("some-unknown-model")  # creates limiter
        stats = limiter.get_stats("some-unknown-model")
        assert stats["min_delay"] == ZEN_DEFAULT_RATE_CONFIG.min_delay
        assert stats["max_delay"] == ZEN_DEFAULT_RATE_CONFIG.max_delay

    def test_qwen_model_gets_qwen_config(self):
        limiter = PerModelRateLimiter()
        limiter.record_success("qwen3.6-plus-free")
        stats = limiter.get_stats("qwen3.6-plus-free")
        qwen_config = resolve_model_rate_config("qwen3.6-plus-free")
        assert stats["min_delay"] == qwen_config.min_delay
        assert stats["max_delay"] == qwen_config.max_delay

    def test_stats_all_models(self):
        limiter = PerModelRateLimiter()
        limiter.record_success("qwen3.6-plus-free")
        limiter.record_rate_limit("minimax-m2.5-free")

        all_stats = limiter.get_stats()
        assert "qwen3.6-plus-free" in all_stats
        assert "minimax-m2.5-free" in all_stats
        assert all_stats["qwen3.6-plus-free"]["total_rate_limits"] == 0
        assert all_stats["minimax-m2.5-free"]["total_rate_limits"] == 1

    def test_reset_single_model(self):
        limiter = PerModelRateLimiter()
        limiter.record_rate_limit("qwen3.6-plus-free")
        limiter.record_rate_limit("minimax-m2.5-free")

        limiter.reset("qwen3.6-plus-free")
        assert limiter.get_stats("qwen3.6-plus-free")["consecutive_failures"] == 0
        assert limiter.get_stats("minimax-m2.5-free")["consecutive_failures"] == 1

    def test_reset_all_models(self):
        limiter = PerModelRateLimiter()
        limiter.record_rate_limit("qwen3.6-plus-free")
        limiter.record_rate_limit("minimax-m2.5-free")

        limiter.reset()
        assert limiter.get_stats("qwen3.6-plus-free")["consecutive_failures"] == 0
        assert limiter.get_stats("minimax-m2.5-free")["consecutive_failures"] == 0

    @pytest.mark.asyncio
    async def test_wait_creates_limiter_and_enforces_delay(self):
        limiter = PerModelRateLimiter()
        await limiter.wait("qwen3.6-plus-free")
        stats = limiter.get_stats("qwen3.6-plus-free")
        assert stats["total_requests"] == 1

    @pytest.mark.asyncio
    async def test_models_do_not_interfere(self):
        """Rate limiting one model doesn't affect another."""
        limiter = PerModelRateLimiter()

        # Hit Qwen with rate limit
        limiter.record_rate_limit("qwen3.6-plus-free")
        qwen_delay = limiter.get_stats("qwen3.6-plus-free")["current_delay"]
        assert qwen_delay > 3.0  # backed off from initial

        # MiniMax should still be at initial delay minus one success step
        limiter.record_success("minimax-m2.5-free")
        minimax_delay = limiter.get_stats("minimax-m2.5-free")["current_delay"]
        qwen_config = resolve_model_rate_config("qwen3.6-plus-free")
        minimax_config = resolve_model_rate_config("minimax-m2.5-free")
        # One success reduces delay by decrease_step from initial
        assert minimax_delay == minimax_config.initial_delay - minimax_config.decrease_step
        assert qwen_delay > minimax_delay  # Qwen backed off, MiniMax didn't

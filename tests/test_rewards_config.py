"""Tests for core/rewards_config.py -- RewardsConfig mutable file-backed config."""

import pytest


class TestRewardsConfig:
    """CONF-05: RewardsConfig mtime-cached load and atomic save."""

    def test_load_returns_defaults_when_no_file(self, tmp_path):
        from core.rewards_config import RewardsConfig

        RewardsConfig.set_path(str(tmp_path / "nonexistent.json"))
        cfg = RewardsConfig.load()
        assert cfg.enabled is True
        assert cfg.silver_threshold == pytest.approx(0.65)
        assert cfg.gold_threshold == pytest.approx(0.85)

    def test_save_and_reload_roundtrip(self, tmp_path):
        from core.rewards_config import RewardsConfig

        RewardsConfig.set_path(str(tmp_path / "rewards.json"))
        cfg = RewardsConfig(enabled=False, silver_threshold=0.70, gold_threshold=0.90)
        cfg.save()
        loaded = RewardsConfig.load()
        assert loaded.enabled is False
        assert loaded.silver_threshold == pytest.approx(0.70)
        assert loaded.gold_threshold == pytest.approx(0.90)

    def test_load_returns_defaults_on_corrupt_json(self, tmp_path):
        from core.rewards_config import RewardsConfig

        path = tmp_path / "rewards.json"
        path.write_text("NOT_VALID_JSON")
        RewardsConfig.set_path(str(path))
        cfg = RewardsConfig.load()
        assert cfg.enabled is True  # Falls back to defaults

    def test_mtime_cache_invalidated_after_save(self, tmp_path):
        """After save(), the next load() reads the new values."""
        from core.rewards_config import RewardsConfig

        RewardsConfig.set_path(str(tmp_path / "rewards.json"))
        cfg1 = RewardsConfig(enabled=True, silver_threshold=0.65, gold_threshold=0.85)
        cfg1.save()
        cfg_loaded = RewardsConfig.load()
        assert cfg_loaded.silver_threshold == pytest.approx(0.65)

        cfg2 = RewardsConfig(enabled=False, silver_threshold=0.80, gold_threshold=0.95)
        cfg2.save()
        cfg_reloaded = RewardsConfig.load()
        assert cfg_reloaded.silver_threshold == pytest.approx(0.80)
        assert cfg_reloaded.enabled is False

    def test_save_creates_parent_directories(self, tmp_path):
        from core.rewards_config import RewardsConfig

        deep_path = tmp_path / "a" / "b" / "c" / "rewards.json"
        RewardsConfig.set_path(str(deep_path))
        cfg = RewardsConfig()
        cfg.save()
        assert deep_path.exists()

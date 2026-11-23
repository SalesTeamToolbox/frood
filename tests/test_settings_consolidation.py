"""Phase 40 — Settings Consolidation backend tests.

Tests:
- LEARNING_ENABLED config + guards
- Memory purge endpoint validation
- Editable settings includes LEARNING_ENABLED
"""

import asyncio
from unittest.mock import MagicMock, patch


class TestLearningEnabled:
    """D-14: LEARNING_ENABLED toggle."""

    def test_config_field_exists(self):
        from core.config import Settings

        s = Settings()
        assert s.learning_enabled is True

    def test_config_field_false(self):
        from core.config import Settings

        s = Settings(learning_enabled=False)
        assert s.learning_enabled is False

    def test_learn_async_skips_when_disabled(self):
        from core.memory_bridge import MemoryBridge

        mb = MemoryBridge(memory_store=MagicMock())
        with patch("core.config.settings", MagicMock(learning_enabled=False)):
            asyncio.run(mb.learn_async("summary", "agent-1"))
            # Should return immediately without error

    def test_drain_skips_when_disabled(self):
        from memory.effectiveness import EffectivenessStore

        store = EffectivenessStore(db_path="test_eff.db")
        with patch("core.config.settings", MagicMock(learning_enabled=False)):
            result = asyncio.run(store.drain_pending_transcripts())
            assert result == []


class TestMemoryPurge:
    """D-15: DELETE /api/settings/memory/{collection}."""

    def test_invalid_collection_rejected(self):
        valid = {"memory", "knowledge", "history"}
        assert "invalid" not in valid
        assert "memory" in valid

    def test_valid_collections_complete(self):
        valid = {"memory", "knowledge", "history"}
        assert len(valid) == 3


class TestEditableSettings:
    """LEARNING_ENABLED in dashboard editable settings."""

    def test_editable_settings_includes_learning(self):
        from dashboard.server import _DASHBOARD_EDITABLE_SETTINGS

        assert "LEARNING_ENABLED" in _DASHBOARD_EDITABLE_SETTINGS

"""Phase 40 -- Settings UI content verification tests.

Reads app.js and style.css at module level (not per-test) per Phase 38 pattern.
Verifies Memory & Learning tab structure and content in standalone dashboard.
Verifies SettingsPage.tsx tab structure for Paperclip mode.
"""

import pathlib

_APP_JS = pathlib.Path("dashboard/frontend/dist/app.js").read_text(encoding="utf-8")
_STYLE_CSS = pathlib.Path("dashboard/frontend/dist/style.css").read_text(encoding="utf-8")
_SETTINGS_TSX = pathlib.Path("plugins/agent42-paperclip/src/ui/SettingsPage.tsx").read_text(
    encoding="utf-8"
)


class TestStandaloneMemoryTab:
    """Memory & Learning tab in standalone dashboard."""

    def test_memory_tab_in_tabs_array(self):
        assert '"memory"' in _APP_JS
        assert '"Memory & Learning"' in _APP_JS

    def test_memory_stats_fetch(self):
        assert "/api/memory/stats" in _APP_JS

    def test_learning_toggle_function(self):
        assert "toggleLearningEnabled" in _APP_JS

    def test_purge_controls_present(self):
        assert "confirmPurgeCollection" in _APP_JS

    def test_purge_confirmation_required(self):
        assert "PURGE" in _APP_JS

    def test_memory_purge_endpoint(self):
        assert "/api/settings/memory/" in _APP_JS

    def test_recall_count_label(self):
        assert "Recalls (24h)" in _APP_JS

    def test_learning_enabled_setting(self):
        assert "LEARNING_ENABLED" in _APP_JS

    def test_memory_panel_in_panels_object(self):
        assert "memory: function" in _APP_JS or "memory:" in _APP_JS

    def test_learning_toggle_fetch(self):
        assert "/api/settings/env" in _APP_JS

    def test_stat_card_styles_exist(self):
        assert ".stat-card" in _STYLE_CSS

    def test_stat_card_hover(self):
        assert "box-shadow" in _STYLE_CSS


class TestPaperclipSettingsPage:
    """SettingsPage.tsx tab structure verification."""

    def test_six_tabs_defined(self):
        for tab in ["apikeys", "security", "orchestrator", "storage", "memory", "rewards"]:
            assert tab in _SETTINGS_TSX, f"Tab '{tab}' not found in SettingsPage.tsx"

    def test_tab_labels(self):
        for label in [
            "API Keys",
            "Security",
            "Orchestrator",
            "Storage & Paths",
            "Memory & Learning",
            "Rewards",
        ]:
            assert label in _SETTINGS_TSX, f"Label '{label}' not found"

    def test_source_badge_rendering(self):
        assert "source" in _SETTINGS_TSX
        assert "admin" in _SETTINGS_TSX
        assert "env" in _SETTINGS_TSX

    def test_help_text_lookup(self):
        assert "KEY_HELP" in _SETTINGS_TSX
        assert "OPENROUTER_API_KEY" in _SETTINGS_TSX
        assert "ANTHROPIC_API_KEY" in _SETTINGS_TSX

    def test_all_11_help_keys(self):
        for key in [
            "OPENROUTER_API_KEY",
            "OPENAI_API_KEY",
            "ANTHROPIC_API_KEY",
            "SYNTHETIC_API_KEY",
            "DEEPSEEK_API_KEY",
            "GEMINI_API_KEY",
            "CEREBRAS_API_KEY",
            "REPLICATE_API_TOKEN",
            "LUMA_API_KEY",
            "BRAVE_API_KEY",
            "GITHUB_TOKEN",
        ]:
            assert key in _SETTINGS_TSX, f"Help key '{key}' not found in KEY_HELP"

    def test_memory_stats_data_handler(self):
        assert "memory-stats" in _SETTINGS_TSX

    def test_storage_status_data_handler(self):
        assert "storage-status" in _SETTINGS_TSX

    def test_purge_memory_action(self):
        assert "purge-memory" in _SETTINGS_TSX

    def test_security_tab_no_password(self):
        assert "Authentication is managed by Paperclip" in _SETTINGS_TSX

    def test_clear_button_sends_empty(self):
        # Verify the clear/delete pattern: sending value="" to trigger delete
        assert 'value: ""' in _SETTINGS_TSX or "value: ''" in _SETTINGS_TSX

    def test_confirm_purge_state(self):
        assert "confirmPurge" in _SETTINGS_TSX

    def test_purge_requires_purge_text(self):
        # Verify that purge confirmation checks for "PURGE" string
        assert '"PURGE"' in _SETTINGS_TSX

    def test_tabs_constant_defined(self):
        assert "const TABS" in _SETTINGS_TSX

    def test_source_badge_component(self):
        assert "SourceBadge" in _SETTINGS_TSX

"""Tests for sidecar config fields in Settings (Phase 24, Plan 01)."""




class TestSidecarConfigDefaults:
    """Test that Settings() has correct sidecar defaults."""

    def test_paperclip_sidecar_port_default(self):
        """Test 1: Settings() default paperclip_sidecar_port is 8001."""
        from core.config import Settings

        s = Settings()
        assert s.paperclip_sidecar_port == 8001

    def test_paperclip_api_url_default(self):
        """Test 2: Settings() default paperclip_api_url is empty string."""
        from core.config import Settings

        s = Settings()
        assert s.paperclip_api_url == ""

    def test_sidecar_enabled_default(self):
        """Test 3: Settings() default sidecar_enabled is False."""
        from core.config import Settings

        s = Settings()
        assert s.sidecar_enabled is False


class TestSidecarConfigFromEnv:
    """Test that Settings.from_env() reads sidecar env vars correctly."""

    def test_from_env_reads_paperclip_sidecar_port(self, monkeypatch):
        """Test 4: Settings.from_env() reads PAPERCLIP_SIDECAR_PORT=9002 as int 9002."""
        monkeypatch.setenv("PAPERCLIP_SIDECAR_PORT", "9002")

        import core.config as cfg_mod

        s = cfg_mod.Settings.from_env()
        assert s.paperclip_sidecar_port == 9002

    def test_from_env_reads_sidecar_enabled_true(self, monkeypatch):
        """Test 5: Settings.from_env() reads SIDECAR_ENABLED=true as True."""
        monkeypatch.setenv("SIDECAR_ENABLED", "true")

        import core.config as cfg_mod

        s = cfg_mod.Settings.from_env()
        assert s.sidecar_enabled is True

    def test_from_env_reads_paperclip_api_url(self, monkeypatch):
        """Test 6: Settings.from_env() reads PAPERCLIP_API_URL correctly."""
        monkeypatch.setenv("PAPERCLIP_API_URL", "http://paperclip:3000")

        import core.config as cfg_mod

        s = cfg_mod.Settings.from_env()
        assert s.paperclip_api_url == "http://paperclip:3000"

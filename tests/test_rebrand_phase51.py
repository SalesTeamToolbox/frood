"""Phase 51 -- Rebrand & Repurpose verification tests.

Reads app.js, server.py, index.html, and README.md at module level (not per-test)
per Phase 38/40 pattern. Verifies all Phase 51 requirements across:
- Branding (Frood identity, Agent Apps, SVG renames)
- Settings cleanup (Channels tab removed, Orchestrator -> Routing, MAX_CONCURRENT_AGENTS removed)
- Reports repurposing (Tasks & Projects tab removed, intelligence metrics)
- Activity Feed (new page, intelligence events)
- Setup Wizard (no Mission Control)
- README updates
"""

import pathlib

_APP_JS = pathlib.Path("dashboard/frontend/dist/app.js").read_text(encoding="utf-8")
_SERVER_PY = pathlib.Path("dashboard/server.py").read_text(encoding="utf-8")
_INDEX_HTML = pathlib.Path("dashboard/frontend/dist/index.html").read_text(encoding="utf-8")
_README = pathlib.Path("README.md").read_text(encoding="utf-8")


class TestBranding:
    """Frood branding is consistent across all user-visible surfaces."""

    def test_agent_apps_renamed(self):
        """'Sandboxed Apps' renamed to 'Agent Apps' everywhere."""
        assert "Agent Apps" in _APP_JS
        assert "Sandboxed Apps" not in _APP_JS

    def test_no_agent42_visible(self):
        """No user-visible 'Agent42' text in app.js (deferred internal keys excluded)."""
        # Filter out lines containing deferred internal keys
        lines = _APP_JS.splitlines()
        filtered_lines = [
            line
            for line in lines
            if "agent42_token" not in line
            and "agent42_auth" not in line
            and ".frood/" not in line
        ]
        filtered_text = "\n".join(filtered_lines)
        assert "Agent42" not in filtered_text, (
            "Found user-visible 'Agent42' text (excluding deferred internal keys)"
        )

    def test_server_title(self):
        """FastAPI server title is 'Frood Dashboard'."""
        assert 'title="Frood Dashboard"' in _SERVER_PY

    def test_frood_logo_references(self):
        """Logo SVG references updated to frood-logo-light.svg."""
        assert "frood-logo-light.svg" in _APP_JS
        assert "agent42-logo-light.svg" not in _APP_JS

    def test_frood_favicon(self):
        """Favicon reference updated to frood-favicon.svg in index.html."""
        assert "frood-favicon.svg" in _INDEX_HTML
        assert "agent42-favicon.svg" not in _INDEX_HTML

    def test_frood_avatar(self):
        """Avatar SVG reference updated to frood-avatar.svg."""
        assert "frood-avatar.svg" in _APP_JS
        assert "agent42-avatar.svg" not in _APP_JS


class TestSidebarNav:
    """Sidebar navigation shows correct pages."""

    def test_sidebar_has_activity(self):
        """Activity sidebar link exists."""
        assert 'data-page="activity"' in _APP_JS

    def test_sidebar_no_channels(self):
        """Channels page is not in sidebar (removed in Phase 50)."""
        assert 'data-page="channels"' not in _APP_JS


class TestSettingsCleanup:
    """Settings tabs are cleaned up per D-16 through D-20."""

    def test_channels_tab_removed(self):
        """Settings Channels tab is completely removed."""
        assert 'id: "channels"' not in _APP_JS

    def test_routing_tab(self):
        """Settings has a Routing tab (renamed from Orchestrator)."""
        assert '"routing"' in _APP_JS
        assert 'label: "Routing"' in _APP_JS

    def test_orchestrator_label_gone(self):
        """Orchestrator label no longer exists in Settings tabs."""
        assert 'label: "Orchestrator"' not in _APP_JS

    def test_max_concurrent_removed(self):
        """MAX_CONCURRENT_AGENTS setting is removed from Routing panel."""
        assert "MAX_CONCURRENT_AGENTS" not in _APP_JS

    def test_load_channels_removed(self):
        """loadChannels() function and calls are fully removed."""
        assert "loadChannels" not in _APP_JS


class TestReportsTabs:
    """Reports page repurposed to show intelligence metrics."""

    def test_tasks_tab_removed(self):
        """Tasks & Projects tab is removed from Reports."""
        assert '"Tasks & Projects"' not in _APP_JS

    def test_tasks_renderer_removed(self):
        """_renderReportsTasks function is removed."""
        assert "_renderReportsTasks" not in _APP_JS

    def test_health_tab_present(self):
        """System Health tab is still present in Reports."""
        assert '"System Health"' in _APP_JS or '"health"' in _APP_JS

    def test_intelligence_overview(self):
        """Intelligence overview shows memory recall stats."""
        assert "memory_recall" in _APP_JS or "memoryStats" in _APP_JS

    def test_routing_distribution(self):
        """Reports Overview includes routing tier distribution from _routing_stats."""
        assert "Routing Tier Distribution" in _APP_JS
        assert "routing_stats" in _APP_JS


class TestActivityFeed:
    """Activity Feed page for intelligence event log."""

    def test_activity_renderer(self):
        """renderActivity() function exists."""
        assert "renderActivity" in _APP_JS

    def test_intelligence_event_types(self):
        """Frontend handles intelligence_event WebSocket messages."""
        assert "intelligence_event" in _APP_JS

    def test_activity_endpoint(self):
        """Server exposes /api/activity endpoint."""
        assert "/api/activity" in _SERVER_PY

    def test_routing_event_hook(self):
        """Server records routing decisions as intelligence events per D-06."""
        assert (
            '_record_intelligence_event("routing"' in _SERVER_PY
            or '_record_intelligence_event(\n            "routing"' in _SERVER_PY
        )


class TestSetupWizard:
    """Setup Wizard reflects Frood-as-service identity."""

    def test_setup_wizard_no_mission_control(self):
        """Setup wizard does not reference Mission Control."""
        assert "Mission Control" not in _APP_JS


class TestReadme:
    """README reflects Frood Dashboard as intelligence layer admin panel."""

    def test_readme_no_harness_terms(self):
        """README does not contain harness/orchestrator terms."""
        for term in ["Mission Control", "Agent Teams", "Agents page"]:
            assert term not in _README, f"Harness term '{term}' still in README"

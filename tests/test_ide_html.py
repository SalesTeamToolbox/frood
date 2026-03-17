"""Tests for IDE page HTML structure (renderCode output in app.js).

These tests verify the target state for Plan 02 (frontend rewrite).
They are marked xfail until the app.js is rebuilt with the new IDE layout.
After Plan 02 completes, remove the xfail markers.
"""

from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "app.js"


class TestIdeHtmlStructure:
    """Verify renderCode() produces correct HTML structure by inspecting app.js source."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        reason="Plan 02 not yet complete — ide-drag-handle added in frontend rewrite"
    )
    def test_drag_handle_present(self):
        """IDE layout must include a draggable divider between editor and terminal."""
        assert "ide-drag-handle" in self.src, "renderCode() must produce ide-drag-handle element"

    @pytest.mark.xfail(
        reason="Plan 02 not yet complete — ide-term-dropdown added in frontend rewrite"
    )
    def test_term_dropdown_present(self):
        """IDE layout must include terminal type dropdown menu."""
        assert "ide-term-dropdown" in self.src, (
            "renderCode() must produce ide-term-dropdown element"
        )

    @pytest.mark.xfail(
        reason="Plan 02 not yet complete — ide-chat-panel removed in frontend rewrite"
    )
    def test_chat_panel_absent(self):
        """AI Chat side panel must be completely removed."""
        assert "ide-chat-panel" not in self.src, (
            "renderCode() must NOT contain ide-chat-panel (chat removed)"
        )

    @pytest.mark.xfail(
        reason="Plan 02 not yet complete — ideChatToggle removed in frontend rewrite"
    )
    def test_chat_toggle_absent(self):
        """Chat toggle function must be removed."""
        assert "ideChatToggle" not in self.src, (
            "app.js must NOT contain ideChatToggle (chat removed)"
        )

    @pytest.mark.xfail(reason="Plan 02 not yet complete — termConnectWs added in frontend rewrite")
    def test_term_connect_ws_present(self):
        """WebSocket connector with auto-reconnect must exist."""
        assert "termConnectWs" in self.src, "app.js must contain termConnectWs function"

    @pytest.mark.xfail(reason="Plan 02 not yet complete — termFitAll added in frontend rewrite")
    def test_term_fit_all_present(self):
        """Shared terminal fit function must exist."""
        assert "termFitAll" in self.src, "app.js must contain termFitAll function"

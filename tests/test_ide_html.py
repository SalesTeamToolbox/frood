"""Tests for IDE page HTML structure (renderCode output in app.js).

These tests verify the VS Code-style IDE layout implemented in Plan 02 (frontend rewrite).
"""

from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "app.js"


class TestIdeHtmlStructure:
    """Verify renderCode() produces correct HTML structure by inspecting app.js source."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    def test_drag_handle_present(self):
        """IDE layout must include a draggable divider between editor and terminal."""
        assert "ide-drag-handle" in self.src, "renderCode() must produce ide-drag-handle element"

    def test_term_dropdown_present(self):
        """IDE layout must include terminal type dropdown menu."""
        assert "ide-term-dropdown" in self.src, (
            "renderCode() must produce ide-term-dropdown element"
        )

    def test_chat_panel_absent(self):
        """AI Chat side panel must be completely removed."""
        assert "ide-chat-panel" not in self.src, (
            "renderCode() must NOT contain ide-chat-panel (chat removed)"
        )

    def test_chat_toggle_absent(self):
        """Chat toggle function must be removed."""
        assert "ideChatToggle" not in self.src, (
            "app.js must NOT contain ideChatToggle (chat removed)"
        )

    def test_term_connect_ws_present(self):
        """WebSocket connector with auto-reconnect must exist."""
        assert "termConnectWs" in self.src, "app.js must contain termConnectWs function"

    def test_term_fit_all_present(self):
        """Shared terminal fit function must exist."""
        assert "termFitAll" in self.src, "app.js must contain termFitAll function"

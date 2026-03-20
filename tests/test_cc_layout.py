"""Tests for Phase 4 Layout + Diff Viewer -- source inspection of app.js and style.css.

Strategy: identical to tests/test_cc_tool_use.py -- read source files as text and assert
required patterns are present. Tests run RED until implementation plans 04-02 through 04-04
complete.

Requirements covered: LAYOUT-01 through LAYOUT-04.
"""

from pathlib import Path

import pytest

APP_JS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "app.js"
STYLE_CSS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "style.css"


# ---------------------------------------------------------------------------
# Class 1: TestCCPanelLayout (LAYOUT-01, LAYOUT-02, LAYOUT-03)
# ---------------------------------------------------------------------------


class TestCCPanelLayout:
    """Panel layout patterns in app.js (LAYOUT-01, LAYOUT-02, LAYOUT-03)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="LAYOUT-01: ideOpenCCChat already exists -- expected XPASS",
    )
    def test_cc_tab_default_path(self):
        """LAYOUT-01: ideOpenCCChat defines the default CC tab entry point."""
        assert "ideOpenCCChat" in self.src, (
            "app.js must define ideOpenCCChat function for the CC tab entry point"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-02 GREEN flips",
    )
    def test_panel_container_present(self):
        """LAYOUT-02: Panel container div and drag handle present in HTML template."""
        assert "ide-cc-panel" in self.src, (
            "app.js must contain ide-cc-panel element for panel container"
        )
        assert "ide-panel-drag-handle" in self.src, (
            "app.js must contain ide-panel-drag-handle element for panel resize handle"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-02 GREEN flips",
    )
    def test_panel_width_persistence(self):
        """LAYOUT-02: Panel width is persisted to localStorage via cc_panel_width key."""
        assert "cc_panel_width" in self.src, (
            "app.js must use cc_panel_width localStorage key for panel width persistence"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-02 GREEN flips",
    )
    def test_panel_drag_handle_function(self):
        """LAYOUT-02: initPanelDragHandle function defined for panel resize drag handle."""
        assert "initPanelDragHandle" in self.src, (
            "app.js must define initPanelDragHandle function for panel resize drag handle"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-03 GREEN flips",
    )
    def test_toggle_function_defined(self):
        """LAYOUT-03: ideToggleCCPanel function defined for tab/panel mode switching."""
        assert "ideToggleCCPanel" in self.src, (
            "app.js must define ideToggleCCPanel function for tab/panel mode toggle"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-03 GREEN flips",
    )
    def test_panel_mode_flag(self):
        """LAYOUT-03: _ccPanelMode state flag tracks whether CC is in panel mode."""
        assert "_ccPanelMode" in self.src, (
            "app.js must define _ccPanelMode flag to track current CC display mode"
        )


# ---------------------------------------------------------------------------
# Class 2: TestCCPanelCSS (LAYOUT-02)
# ---------------------------------------------------------------------------


class TestCCPanelCSS:
    """Panel CSS classes in style.css (LAYOUT-02)."""

    def setup_method(self):
        self.src = STYLE_CSS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-02 GREEN flips",
    )
    def test_panel_css_classes(self):
        """LAYOUT-02: style.css must define .ide-cc-panel and .ide-panel-drag-handle classes."""
        assert ".ide-cc-panel" in self.src, (
            "style.css must define .ide-cc-panel class for panel container styling"
        )
        assert ".ide-panel-drag-handle" in self.src, (
            "style.css must define .ide-panel-drag-handle class for drag handle styling"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-02 GREEN flips",
    )
    def test_panel_editor_area_wrapper(self):
        """LAYOUT-02: style.css must define .ide-main-editor-area wrapper class."""
        assert ".ide-main-editor-area" in self.src, (
            "style.css must define .ide-main-editor-area class for the editor area wrapper div"
        )


# ---------------------------------------------------------------------------
# Class 3: TestDiffViewer (LAYOUT-04)
# ---------------------------------------------------------------------------


class TestDiffViewer:
    """Diff viewer patterns in app.js (LAYOUT-04)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-04 GREEN flips",
    )
    def test_open_diff_tab_defined(self):
        """LAYOUT-04: ideOpenDiffTab function defined to create Monaco diff editor tabs."""
        assert "ideOpenDiffTab" in self.src, (
            "app.js must define ideOpenDiffTab function to open diff editor as a tab"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-04 GREEN flips",
    )
    def test_create_diff_editor_used(self):
        """LAYOUT-04: createDiffEditor used in app.js for Monaco diff editor instantiation."""
        assert "createDiffEditor" in self.src, (
            "app.js must call monaco.editor.createDiffEditor to create the diff editor"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-04 GREEN flips",
    )
    def test_view_diff_button_on_file_tools(self):
        """LAYOUT-04: View Diff button appears on Write/Edit tool cards."""
        assert "View Diff" in self.src, (
            "app.js must include 'View Diff' button text on file tool cards"
        )

    @pytest.mark.xfail(
        raises=AssertionError,
        strict=False,
        reason="Unimplemented -- Plan 04-04 GREEN flips",
    )
    def test_diff_uses_agent42_dark_theme(self):
        """LAYOUT-04: Diff editor uses agent42-dark theme (already registered globally)."""
        assert "agent42-dark" in self.src, (
            "app.js must reference agent42-dark theme for Monaco diff editor"
        )
        assert "createDiffEditor" in self.src, (
            "app.js must define createDiffEditor usage alongside agent42-dark theme"
        )

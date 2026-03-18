"""Tests for Phase 2 Core Chat UI — source inspection of app.js, index.html, style.css.

Strategy: identical to tests/test_ide_html.py — read source files as text and assert
required patterns are present. No browser automation required. Tests run RED until
implementation plans 02-03 through 02-05 complete.

Requirements covered: CHAT-01 through CHAT-09, INPUT-01 through INPUT-04.
"""

from pathlib import Path

APP_JS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "app.js"
INDEX_HTML = (
    Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "index.html"
)
STYLE_CSS = Path(__file__).resolve().parent.parent / "dashboard" / "frontend" / "dist" / "style.css"


class TestCCChatDeps:
    """CDN dependencies loaded in index.html (CHAT-03, CHAT-04, CHAT-05)."""

    def setup_method(self):
        self.html = INDEX_HTML.read_text(encoding="utf-8")

    def test_cdn_scripts_in_index(self):
        """index.html must load marked.js and highlight.js CDN scripts (CHAT-03, CHAT-04)."""
        assert "marked@17.0.4" in self.html, (
            "index.html must include marked.js CDN script: "
            "https://cdn.jsdelivr.net/npm/marked@17.0.4/lib/marked.umd.js"
        )
        assert "highlight.js@11.11.1" in self.html, (
            "index.html must include highlight.js CDN script: "
            "https://cdn.jsdelivr.net/gh/highlightjs/cdn-release@11.11.1/build/highlight.min.js"
        )
        assert "marked-highlight@2.2.3" in self.html, (
            "index.html must include marked-highlight CDN script: "
            "https://cdn.jsdelivr.net/npm/marked-highlight@2.2.3/lib/index.umd.js"
        )

    def test_dompurify_in_index(self):
        """index.html must load DOMPurify CDN script (CHAT-05 — non-negotiable locked decision)."""
        assert "dompurify@3.3.3" in self.html, (
            "index.html must include DOMPurify CDN script: "
            "https://cdn.jsdelivr.net/npm/dompurify@3.3.3/dist/purify.min.js"
        )

    def test_hljs_css_in_index(self):
        """index.html must load highlight.js github-dark CSS theme (CHAT-04)."""
        assert "github-dark.min.css" in self.html, (
            "index.html must include highlight.js github-dark CSS: "
            "https://cdn.jsdelivr.net/npm/highlight.js@11.11.1/styles/github-dark.min.css"
        )


class TestCCChatRendering:
    """Chat panel rendering patterns in app.js (CHAT-01 through CHAT-09)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    def test_user_bubble_structure(self):
        """ccAppendUserBubble creates .chat-msg-user bubble with avatar and timestamp (CHAT-01)."""
        assert "ccAppendUserBubble" in self.src, "app.js must define ccAppendUserBubble function"
        assert "chat-msg-user" in self.src, (
            "app.js must use .chat-msg-user class in CC chat user bubble"
        )

    def test_streaming_bubble_class(self):
        """Streaming assistant bubble uses cc-streaming-body class (CHAT-02)."""
        assert "cc-streaming-body" in self.src, (
            "app.js must create streaming bubble with class cc-streaming-body"
        )

    def test_chat_panel_function_defined(self):
        """ideOpenCCChat replaces ideOpenClaude for new chat tabs (CHAT-01, CHAT-02)."""
        assert "ideOpenCCChat" in self.src, "app.js must define ideOpenCCChat() function"

    def test_uses_marked_parse(self):
        """ccRenderMarkdown calls marked.parse() not deprecated marked() (CHAT-03)."""
        assert "marked.parse(" in self.src, (
            "app.js must call marked.parse() in ccRenderMarkdown (not deprecated marked())"
        )

    def test_uses_marked_highlight(self):
        """ccRenderMarkdown uses markedHighlight integration (CHAT-04)."""
        assert "markedHighlight" in self.src, (
            "app.js must use markedHighlight for highlight.js integration"
        )
        assert "hljs" in self.src, "app.js must reference hljs (highlight.js) global"

    def test_dompurify_called(self):
        """ccRenderMarkdown calls DOMPurify.sanitize on all marked output (CHAT-05)."""
        assert "DOMPurify.sanitize(" in self.src, (
            "app.js must call DOMPurify.sanitize() in ccRenderMarkdown — non-negotiable (STATE.md)"
        )

    def test_50ms_batch_interval(self):
        """Streaming uses setInterval with 50ms for batched DOM updates (CHAT-06)."""
        assert "setInterval" in self.src, (
            "app.js must use setInterval for 50ms batched streaming updates"
        )
        assert "50" in self.src, "app.js must use 50ms interval for streaming buffer flush"

    def test_stream_buffer_present(self):
        """Tab state includes streamBuffer for append-only accumulation (CHAT-06)."""
        assert "streamBuffer" in self.src, "app.js tab state object must include streamBuffer field"

    def test_thinking_uses_details(self):
        """Thinking blocks use HTML5 details/summary for collapsible display (CHAT-09)."""
        assert "cc-thinking-block" in self.src, (
            "app.js must create cc-thinking-block element for thinking content"
        )
        assert "cc-thinking-summary" in self.src, (
            "app.js must use cc-thinking-summary for collapsible thinking header"
        )


class TestCCChatScrolling:
    """Scroll behavior in app.js (CHAT-07)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")

    def test_autoscroll_flag(self):
        """Tab state includes autoScroll flag; scroll listener sets it (CHAT-07)."""
        assert "autoScroll" in self.src, "app.js must track autoScroll flag on tab state object"

    def test_scroll_anchor_button(self):
        """Scroll-to-bottom button exists in chat panel HTML (CHAT-07)."""
        assert "cc-chat-scroll-anchor" in self.src, (
            "app.js must include cc-chat-scroll-anchor button in chat panel"
        )


class TestCCChatStop:
    """Stop button — frontend sends stop, backend terminates (CHAT-08)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")
        import inspect

        import dashboard.server as _srv_mod

        self.server_src = inspect.getsource(_srv_mod)

    def test_stop_sends_type_stop(self):
        """ccStop() sends {type: stop} JSON over WebSocket (CHAT-08 frontend)."""
        assert "ccStop" in self.src, "app.js must define ccStop() function"
        assert '"stop"' in self.src or "'stop'" in self.src, (
            "app.js ccStop must send {type: 'stop'} message over WebSocket"
        )

    def test_backend_handles_stop(self):
        """cc_chat_ws handles {type: stop} message and terminates subprocess (CHAT-08 backend)."""
        assert '"stop"' in self.server_src or "'stop'" in self.server_src, (
            "server.py cc_chat_ws must handle incoming {type: stop} message"
        )
        assert "asyncio.wait(" in self.server_src or "_asyncio.wait(" in self.server_src, (
            "server.py cc_chat_ws must use asyncio.wait() for concurrent receive during subprocess read"
        )


class TestCCChatInput:
    """Input box behavior in app.js (INPUT-01 through INPUT-04)."""

    def setup_method(self):
        self.src = APP_JS.read_text(encoding="utf-8")
        self.css = STYLE_CSS.read_text(encoding="utf-8")

    def test_textarea_shift_enter(self):
        """Input uses textarea; Shift+Enter inserts newline; Enter sends (INPUT-01)."""
        assert "cc-chat-input" in self.src, (
            "app.js must include cc-chat-input textarea in composer HTML"
        )
        assert "shiftKey" in self.src, (
            "app.js must check shiftKey in keydown handler to allow Shift+Enter newlines"
        )

    def test_multiline_preserved(self):
        """CC chat CSS uses pre-wrap so paragraph breaks display correctly (INPUT-02)."""
        assert "pre-wrap" in self.css or "pre-line" in self.css, (
            "style.css must include white-space: pre-wrap (or pre-line) for CC chat message body"
        )

    def test_autoresize_scrollheight(self):
        """ccInputResize() uses scrollHeight pattern for auto-resize (INPUT-03)."""
        assert "ccInputResize" in self.src, "app.js must define ccInputResize() function"
        assert "scrollHeight" in self.src, "app.js ccInputResize must read textarea.scrollHeight"

    def test_slash_dropdown_defined(self):
        """ccUpdateSlashDropdown defined; '/' detection present (INPUT-04)."""
        assert "ccUpdateSlashDropdown" in self.src, (
            "app.js must define ccUpdateSlashDropdown() function"
        )
        assert 'startsWith("/")' in self.src or "startsWith('/')" in self.src, (
            "app.js ccUpdateSlashDropdown must detect leading '/' in input value"
        )
        assert "CC_SLASH_COMMANDS" in self.src, (
            "app.js must define CC_SLASH_COMMANDS array with /help, /clear, /compact"
        )

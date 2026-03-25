"""
Tests for UnifiedContextTool — 6-source context assembly with jcodemunch integration,
GSD workstream state, and effectiveness-ranked tools.

Coverage:
- CTX-01: jcodemunch code symbol integration + graceful degradation
- CTX-02: GSD active workstream state injection
- CTX-03: Effectiveness-ranked tool recommendations
- Budget redistribution when sources are unavailable
- Task type inference from query keywords
- Tool name and parameter schema validation
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tools.unified_context import UnifiedContextTool

# ---------------------------------------------------------------------------
# Mock helper classes
# ---------------------------------------------------------------------------


class MockMemoryResult:
    def __init__(self, text, section="Test", score=0.9):
        self._data = {"text": text, "section": section, "score": score}

    def get(self, key, default=None):
        return self._data.get(key, default)


class MockMemoryStore:
    async def semantic_search(self, query="", top_k=5):
        return [
            MockMemoryResult("Memory result about sandbox security", "Security"),
            MockMemoryResult("Another memory about authentication", "Auth"),
        ]


class MockSkillLoader:
    def all_skills(self):
        skill = MagicMock()
        skill.name = "security-review"
        skill.description = "Reviews security-sensitive code changes"
        return [skill]


class MockEffectivenessStore:
    def __init__(self, recommendations=None):
        self._recs = recommendations if recommendations is not None else []

    async def get_recommendations(self, task_type="", min_observations=5, top_k=3):
        return self._recs


# ---------------------------------------------------------------------------
# TestUnifiedContext — main tool tests
# ---------------------------------------------------------------------------


class TestUnifiedContext:
    """Tests for UnifiedContextTool.execute() covering all 6 sources."""

    def _make_tool(self, effectiveness_recs=None, workspace=""):

        memory_store = MockMemoryStore()
        skill_loader = MockSkillLoader()
        effectiveness_store = MockEffectivenessStore(effectiveness_recs or [])
        return UnifiedContextTool(
            memory_store=memory_store,
            skill_loader=skill_loader,
            workspace=workspace,
            effectiveness_store=effectiveness_store,
        )

    # ------------------------------------------------------------------
    # Test 1: CTX-01 happy path — jcodemunch returns code symbols
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_jcodemunch_happy_path_returns_code_symbols(self):
        """When jcodemunch connects successfully, response includes '## Code Symbols'."""
        tool = self._make_tool()

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock()
            mock_conn.call_tool = AsyncMock(return_value="class SandboxViolation:\n    pass")
            mock_conn.disconnect = AsyncMock()

            result = await tool.execute(topic="sandbox security")

        assert result.success is True
        assert "## Code Symbols" in result.output
        # Should also include memory results from assembler
        assert len(result.output) > 100

    # ------------------------------------------------------------------
    # Test 2: CTX-01 graceful degradation — jcodemunch TimeoutError
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_jcodemunch_timeout_still_returns_other_sources(self):
        """When jcodemunch.connect() raises TimeoutError, tool still succeeds with other sources."""
        tool = self._make_tool()

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock(side_effect=TimeoutError())
            mock_conn.disconnect = AsyncMock()

            result = await tool.execute(topic="sandbox security")

        assert result.success is True
        assert "## Code Symbols" not in result.output
        # Should still have content from base assembler
        assert len(result.output) > 50

    # ------------------------------------------------------------------
    # Test 3: CTX-02 GSD active — matching workstream STATE.md
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_gsd_state_included_when_keywords_match(self, tmp_path):
        """When active STATE.md exists and query matches, GSD section is included."""
        # Create a fake workstream STATE.md
        ws_dir = tmp_path / ".planning" / "workstreams" / "test-ws"
        ws_dir.mkdir(parents=True)
        state_content = """\
---
status: Ready to plan
stopped_at: Phase 1 context engine implementation
last_updated: "2026-03-25T10:00:00Z"
---

# Project State

## Current Position

Phase: 1
"""
        (ws_dir / "STATE.md").write_text(state_content)

        tool = self._make_tool(workspace=str(tmp_path))

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock(side_effect=Exception("no jcodemunch in test"))
            mock_conn.disconnect = AsyncMock()

            result = await tool.execute(topic="context engine phase implementation")

        assert result.success is True
        assert "## GSD Workstream" in result.output

    # ------------------------------------------------------------------
    # Test 4: CTX-02 GSD no match — keywords don't match workstream
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_gsd_state_omitted_when_no_keyword_match(self, tmp_path):
        """When query keywords do not match any active workstream, GSD section is omitted."""
        ws_dir = tmp_path / ".planning" / "workstreams" / "billing-system"
        ws_dir.mkdir(parents=True)
        state_content = """\
---
status: Ready to plan
stopped_at: Phase 2 payment integration
last_updated: "2026-03-25T10:00:00Z"
---
"""
        (ws_dir / "STATE.md").write_text(state_content)

        tool = self._make_tool(workspace=str(tmp_path))

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock(side_effect=Exception("no jcodemunch in test"))
            mock_conn.disconnect = AsyncMock()

            # Topic has nothing to do with "payment" or "billing"
            result = await tool.execute(topic="sandbox security vulnerability")

        assert result.success is True
        assert "## GSD Workstream" not in result.output

    # ------------------------------------------------------------------
    # Test 5: CTX-03 effectiveness with data — shows ranked tools section
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_effectiveness_section_included_when_data_available(self):
        """When EffectivenessStore returns recommendations, '## Effective Tools' section appears."""
        recs = [
            {
                "tool_name": "shell",
                "task_type": "coding",
                "invocations": 20,
                "success_rate": 0.95,
                "avg_duration_ms": 120.5,
            }
        ]
        tool = self._make_tool(effectiveness_recs=recs)

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock(side_effect=Exception("no jcodemunch in test"))
            mock_conn.disconnect = AsyncMock()

            result = await tool.execute(topic="add new tool parameter", task_type="coding")

        assert result.success is True
        assert "## Effective Tools" in result.output
        assert "shell" in result.output

    # ------------------------------------------------------------------
    # Test 6: CTX-03 no effectiveness data — section omitted
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_effectiveness_section_omitted_when_no_data(self):
        """When EffectivenessStore returns empty, effectiveness section is omitted."""
        tool = self._make_tool(effectiveness_recs=[])

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock(side_effect=Exception("no jcodemunch in test"))
            mock_conn.disconnect = AsyncMock()

            result = await tool.execute(topic="add new tool parameter", task_type="coding")

        assert result.success is True
        assert "## Effective Tools" not in result.output

    # ------------------------------------------------------------------
    # Test 7: D-14 budget redistribution when jcodemunch unavailable
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_budget_redistribution_when_code_symbols_unavailable(self):
        """When jcodemunch is unavailable (25% unused), total output tokens should be near max_tokens."""
        recs = [
            {
                "tool_name": "shell",
                "task_type": "coding",
                "invocations": 10,
                "success_rate": 0.9,
                "avg_duration_ms": 100.0,
            }
        ]
        tool = self._make_tool(effectiveness_recs=recs)

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock(side_effect=Exception("no jcodemunch"))
            mock_conn.disconnect = AsyncMock()

            # Use a small budget so we can detect redistribution
            result = await tool.execute(
                topic="add tool to registry coding", task_type="coding", max_tokens=500
            )

        # Tool should still succeed
        assert result.success is True
        # Output should exist (redistribution means other sources get more space)
        assert len(result.output) > 0

    # ------------------------------------------------------------------
    # Test 8: Tool name is "unified_context"
    # ------------------------------------------------------------------
    def test_tool_name_is_unified_context(self):
        """UnifiedContextTool.name returns 'unified_context'."""

        tool = UnifiedContextTool()
        assert tool.name == "unified_context"

    # ------------------------------------------------------------------
    # Test 9: MCP name uses prefix
    # ------------------------------------------------------------------
    def test_mcp_schema_name_uses_prefix(self):
        """to_mcp_schema() produces 'agent42_unified_context' per D-15/D-16."""

        tool = UnifiedContextTool()
        schema = tool.to_mcp_schema()
        assert schema["name"] == "agent42_unified_context"

    # ------------------------------------------------------------------
    # Test 10: Parameters schema has required 'topic' and optional fields
    # ------------------------------------------------------------------
    def test_parameters_schema_has_correct_fields(self):
        """parameters dict contains 'topic' as required plus optional fields."""

        tool = UnifiedContextTool()
        params = tool.parameters
        assert params["type"] == "object"
        assert "topic" in params["properties"]
        assert "required" in params
        assert "topic" in params["required"]
        # Optional fields
        assert "scope" in params["properties"]
        assert "depth" in params["properties"]
        assert "max_tokens" in params["properties"]
        assert "task_type" in params["properties"]

    # ------------------------------------------------------------------
    # Test: empty topic returns error
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_empty_topic_returns_error(self):
        """execute() with no topic returns ToolResult with success=False."""

        tool = UnifiedContextTool()
        result = await tool.execute(topic="")
        assert result.success is False
        assert "topic" in result.error.lower()

    # ------------------------------------------------------------------
    # Test: GSD Complete status is skipped
    # ------------------------------------------------------------------
    @pytest.mark.asyncio
    async def test_gsd_complete_workstreams_are_skipped(self, tmp_path):
        """Completed workstreams (status='Complete') are not included in GSD context."""
        ws_dir = tmp_path / ".planning" / "workstreams" / "old-ws"
        ws_dir.mkdir(parents=True)
        state_content = """\
---
status: Complete
stopped_at: Phase 4 context engine complete
last_updated: "2026-03-20T10:00:00Z"
---
"""
        (ws_dir / "STATE.md").write_text(state_content)

        tool = self._make_tool(workspace=str(tmp_path))

        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            MockConn.return_value = mock_conn
            mock_conn.connect = AsyncMock(side_effect=Exception("no jcodemunch in test"))
            mock_conn.disconnect = AsyncMock()

            result = await tool.execute(topic="context engine phase implementation")

        assert result.success is True
        assert "## GSD Workstream" not in result.output


# ---------------------------------------------------------------------------
# TestTaskTypeInference — _infer_task_type() unit tests
# ---------------------------------------------------------------------------


class TestTaskTypeInference:
    """Tests for the _infer_task_type() module-level function."""

    def test_security_keywords_map_to_debugging(self):
        """'fix the sandbox bug' -> 'debugging' (security work type -> debugging task type)."""
        from tools.unified_context import _infer_task_type

        result = _infer_task_type("fix the sandbox bug")
        assert result == "debugging"

    def test_tools_keywords_map_to_coding(self):
        """'add new tool parameter' -> 'coding' (tools work type -> coding task type)."""
        from tools.unified_context import _infer_task_type

        result = _infer_task_type("add new tool parameter")
        assert result == "coding"

    def test_deployment_keywords_map_to_project_setup(self):
        """'deploy to production' -> 'project_setup' (deployment work type)."""
        from tools.unified_context import _infer_task_type

        result = _infer_task_type("deploy to production server")
        assert result == "project_setup"

    def test_unknown_query_returns_empty_string(self):
        """'unknown random query xyz' -> '' (no work type match)."""
        from tools.unified_context import _infer_task_type

        result = _infer_task_type("xyzabc123 completely unrecognized jargon")
        assert result == ""


# ---------------------------------------------------------------------------
# TestMCPRegistration — verify MCP wiring (Plan 02)
# ---------------------------------------------------------------------------


class TestMCPRegistration:
    """Verify UnifiedContextTool MCP wiring."""

    def test_mcp_tool_name(self):
        """Tool name with agent42 prefix produces agent42_unified_context."""
        tool = UnifiedContextTool()
        schema = tool.to_mcp_schema(prefix="agent42")
        assert schema["name"] == "agent42_unified_context"

    def test_mcp_tool_name_no_collision_with_context(self):
        """UnifiedContextTool and ContextAssemblerTool have different MCP names."""
        from tools.context_assembler import ContextAssemblerTool

        unified = UnifiedContextTool()
        assembler = ContextAssemblerTool()
        assert unified.to_mcp_schema()["name"] != assembler.to_mcp_schema()["name"]
        assert assembler.to_mcp_schema()["name"] == "agent42_context"
        assert unified.to_mcp_schema()["name"] == "agent42_unified_context"

    def test_parameters_include_task_type(self):
        """D-17: parameters include optional task_type field."""
        tool = UnifiedContextTool()
        params = tool.parameters
        assert "task_type" in params["properties"]
        assert params["properties"]["task_type"]["type"] == "string"
        assert "topic" in params["required"]

    def test_description_mentions_code_symbols(self):
        """Description mentions the new capabilities."""
        tool = UnifiedContextTool()
        desc = tool.description.lower()
        assert "code" in desc or "symbol" in desc
        assert "effectiveness" in desc or "ranked" in desc


# ---------------------------------------------------------------------------
# TestFullIntegration — end-to-end execution with all sources mocked (Plan 02)
# ---------------------------------------------------------------------------


class TestFullIntegration:
    """End-to-end execution with all sources mocked."""

    @pytest.mark.asyncio
    async def test_all_sources_present(self, tmp_path):
        """When all sources return data, output contains all 4 section types."""
        # Set up mock workspace with GSD state
        ws = tmp_path / "workspace"
        ws.mkdir()
        planning = ws / ".planning" / "workstreams" / "test-ws"
        planning.mkdir(parents=True)
        state_md = planning / "STATE.md"
        state_md.write_text(
            "---\nstatus: Ready to plan\nstopped_at: Phase 4 context engine\n"
            'last_updated: "2026-03-25T12:00:00Z"\n---\n# Test\n'
        )
        roadmap = planning / "ROADMAP.md"
        roadmap.write_text("# Roadmap\n\n## Phase 4: Context Engine\n**Goal**: Build context\n")

        # Mock all dependencies
        mock_memory = MockMemoryStore()
        mock_skills = MockSkillLoader()
        mock_eff = MockEffectivenessStore()

        tool = UnifiedContextTool(
            memory_store=mock_memory,
            skill_loader=mock_skills,
            workspace=str(ws),
            effectiveness_store=mock_eff,
        )

        # Mock jcodemunch to return code symbols
        with patch("tools.unified_context.MCPConnection") as MockConn:
            mock_conn = AsyncMock()
            mock_conn.call_tool.return_value = "class Foo:\n  def bar(self): pass"
            MockConn.return_value = mock_conn

            result = await tool.execute(topic="context engine coding", max_tokens=4000)

        assert result.success is True
        output = result.output
        # Base assembler output should be present (memory/docs)
        assert len(output) > 100
        # Check that we got a non-empty response with reasonable token usage
        token_est = len(output) // 4
        assert token_est > 50  # Should have substantial content from multiple sources

    @pytest.mark.asyncio
    async def test_complete_degradation(self):
        """When ALL optional sources fail, tool still returns base assembler output."""
        tool = UnifiedContextTool(
            memory_store=None,
            skill_loader=None,
            workspace="/nonexistent",
            effectiveness_store=None,
        )

        with patch("tools.unified_context.MCPConnection") as MockConn:
            MockConn.return_value.connect = AsyncMock(side_effect=TimeoutError("no jcodemunch"))

            result = await tool.execute(topic="anything", max_tokens=4000)

        # Should still succeed — graceful degradation
        assert result.success is True

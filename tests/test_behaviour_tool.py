"""Tests for BehaviourTool — persistent agent behaviour rules."""

from tools.behaviour_tool import BehaviourTool, load_behaviour_rules


class TestBehaviourTool:
    def setup_method(self, tmp_path=None):
        pass  # Tool is created per test with tmp_path fixture

    async def test_show_empty_returns_no_rules(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        result = await tool.execute(operation="show")
        assert result.success
        assert "No behaviour rules" in result.output

    async def test_adjust_adds_rule(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        result = await tool.execute(operation="adjust", rule="Always use British English")
        assert result.success
        assert "Always use British English" in result.output

    async def test_show_after_adjust_returns_rule(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        await tool.execute(operation="adjust", rule="Prefer functional style")
        result = await tool.execute(operation="show")
        assert result.success
        assert "Prefer functional style" in result.output

    async def test_adjust_multiple_rules(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        await tool.execute(operation="adjust", rule="Rule one")
        await tool.execute(operation="adjust", rule="Rule two")
        await tool.execute(operation="adjust", rule="Rule three")
        result = await tool.execute(operation="show")
        assert "Rule one" in result.output
        assert "Rule two" in result.output
        assert "Rule three" in result.output

    async def test_adjust_no_duplicate_rules(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        await tool.execute(operation="adjust", rule="Unique rule")
        await tool.execute(operation="adjust", rule="Unique rule")  # duplicate
        result = await tool.execute(operation="show")
        # Count occurrences — should appear only once
        assert result.output.count("Unique rule") == 1

    async def test_reset_clears_rules(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        await tool.execute(operation="adjust", rule="Rule to remove")
        result = await tool.execute(operation="reset")
        assert result.success
        show = await tool.execute(operation="show")
        assert "No behaviour rules" in show.output

    async def test_adjust_strips_list_marker(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        await tool.execute(operation="adjust", rule="- Already formatted rule")
        result = await tool.execute(operation="show")
        # Should strip the "- " prefix
        assert "Already formatted rule" in result.output

    async def test_adjust_empty_rule_fails(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        result = await tool.execute(operation="adjust", rule="")
        assert not result.success

    async def test_unknown_operation_fails(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        result = await tool.execute(operation="unknown")
        assert not result.success

    async def test_behaviour_file_persists(self, tmp_path):
        """Rules should persist across tool instances."""
        tool1 = BehaviourTool(memory_dir=tmp_path)
        await tool1.execute(operation="adjust", rule="Persisted rule")

        # Create new tool instance pointing to same dir
        tool2 = BehaviourTool(memory_dir=tmp_path)
        result = await tool2.execute(operation="show")
        assert "Persisted rule" in result.output

    async def test_load_behaviour_rules_returns_empty_when_no_file(self, tmp_path):
        result = await load_behaviour_rules(tmp_path)
        assert result == ""

    async def test_load_behaviour_rules_returns_formatted_section(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        await tool.execute(operation="adjust", rule="Use type hints")
        result = await load_behaviour_rules(tmp_path)
        assert "Use type hints" in result
        assert "Behaviour Rules" in result

    async def test_load_behaviour_rules_empty_after_reset(self, tmp_path):
        tool = BehaviourTool(memory_dir=tmp_path)
        await tool.execute(operation="adjust", rule="Temporary rule")
        await tool.execute(operation="reset")
        result = await load_behaviour_rules(tmp_path)
        assert result == ""

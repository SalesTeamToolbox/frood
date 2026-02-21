"""Tests for non-coding tools: content analyzer, data, template, outline, scoring."""

import pytest

from tools.content_analyzer import ContentAnalyzerTool
from tools.data_tool import DataTool
from tools.template_tool import TemplateTool, BUILTIN_TEMPLATES
from tools.outline_tool import OutlineTool
from tools.scoring_tool import ScoringTool, BUILTIN_RUBRICS
from core.task_queue import TaskType, infer_task_type


# =============================================================================
# Task Type Inference Tests
# =============================================================================

class TestTaskTypeInference:
    """Test that new task types are correctly inferred from keywords."""

    def test_design_keywords(self):
        assert infer_task_type("Create a mockup for the login page") == TaskType.DESIGN
        assert infer_task_type("Review the wireframe") == TaskType.DESIGN
        assert infer_task_type("Design a new logo") == TaskType.DESIGN

    def test_content_keywords(self):
        assert infer_task_type("Write a narrative about our journey") == TaskType.CONTENT
        assert infer_task_type("Create an article on productivity") == TaskType.CONTENT

    def test_strategy_keywords(self):
        assert infer_task_type("Do a SWOT analysis of our product") == TaskType.STRATEGY
        assert infer_task_type("Develop a go-to-market strategy") == TaskType.STRATEGY

    def test_data_analysis_keywords(self):
        assert infer_task_type("Load the CSV and compute statistics") == TaskType.DATA_ANALYSIS
        assert infer_task_type("Build a chart from the sales metrics") == TaskType.DATA_ANALYSIS

    def test_project_management_keywords(self):
        assert infer_task_type("Create a project plan for Q3") == TaskType.PROJECT_MANAGEMENT
        assert infer_task_type("Set up the sprint roadmap") == TaskType.PROJECT_MANAGEMENT

    def test_fallback_to_coding(self):
        assert infer_task_type("implement the new feature") == TaskType.CODING


# =============================================================================
# Content Analyzer Tests
# =============================================================================

class TestContentAnalyzer:

    def setup_method(self):
        self.tool = ContentAnalyzerTool()

    @pytest.mark.asyncio
    async def test_readability(self):
        text = (
            "The quick brown fox jumps over the lazy dog. "
            "This is a simple sentence. Short words are easy to read. "
            "We use them every day in normal conversation."
        )
        result = await self.tool.execute(action="readability", text=text)
        assert result.success
        assert "Flesch Reading Ease" in result.output
        assert "Words" in result.output

    @pytest.mark.asyncio
    async def test_tone(self):
        text = (
            "Furthermore, the aforementioned proposal notwithstanding, "
            "we hereby acknowledge the terms pursuant to this agreement."
        )
        result = await self.tool.execute(action="tone", text=text)
        assert result.success
        assert "Formal" in result.output

    @pytest.mark.asyncio
    async def test_tone_informal(self):
        text = "Hey, this is gonna be super cool! Yeah, totally awesome stuff ok?"
        result = await self.tool.execute(action="tone", text=text)
        assert result.success
        assert "Informal" in result.output

    @pytest.mark.asyncio
    async def test_structure(self):
        text = "# Main Title\n\nFirst paragraph here.\n\n## Section One\n\n- Item one\n- Item two\n\n## Section Two\n\nMore content."
        result = await self.tool.execute(action="structure", text=text)
        assert result.success
        assert "Headings" in result.output
        assert "Paragraphs" in result.output

    @pytest.mark.asyncio
    async def test_keywords(self):
        text = "Python is great. Python is fast. Python is readable. Java is verbose."
        result = await self.tool.execute(action="keywords", text=text)
        assert result.success
        assert "python" in result.output.lower()

    @pytest.mark.asyncio
    async def test_compare(self):
        text_a = "This is the original version of the text."
        text_b = "This is the revised and improved version of the text with more detail."
        result = await self.tool.execute(
            action="compare", text=text_a, text_b=text_b
        )
        assert result.success
        assert "Version A" in result.output
        assert "Version B" in result.output

    @pytest.mark.asyncio
    async def test_action_required(self):
        result = await self.tool.execute(text="hello")
        assert not result.success

    @pytest.mark.asyncio
    async def test_text_required(self):
        result = await self.tool.execute(action="readability")
        assert not result.success


# =============================================================================
# Data Tool Tests
# =============================================================================

class TestDataTool:

    def setup_method(self):
        self.tool = DataTool()

    @pytest.mark.asyncio
    async def test_load_csv(self):
        csv_data = "name,age,city\nAlice,30,NYC\nBob,25,LA\nCarol,35,Chicago"
        result = await self.tool.execute(
            action="load", dataset="people", data=csv_data, format="csv"
        )
        assert result.success
        assert "3 rows" in result.output

    @pytest.mark.asyncio
    async def test_load_json(self):
        json_data = '[{"name":"Alice","age":30},{"name":"Bob","age":25}]'
        result = await self.tool.execute(
            action="load", dataset="people", data=json_data, format="json"
        )
        assert result.success
        assert "2 rows" in result.output

    @pytest.mark.asyncio
    async def test_stats(self):
        csv_data = "value\n10\n20\n30\n40\n50"
        await self.tool.execute(action="load", dataset="nums", data=csv_data)
        result = await self.tool.execute(action="stats", dataset="nums", column="value")
        assert result.success
        assert "Mean" in result.output
        assert "Median" in result.output

    @pytest.mark.asyncio
    async def test_query_filter(self):
        csv_data = "name,score\nAlice,90\nBob,60\nCarol,85"
        await self.tool.execute(action="load", dataset="scores", data=csv_data)
        result = await self.tool.execute(
            action="query", dataset="scores", filter="score>70"
        )
        assert result.success
        assert "Alice" in result.output
        assert "Carol" in result.output

    @pytest.mark.asyncio
    async def test_chart(self):
        csv_data = "category\nA\nB\nA\nC\nA\nB"
        await self.tool.execute(action="load", dataset="cats", data=csv_data)
        result = await self.tool.execute(
            action="chart", dataset="cats", column="category"
        )
        assert result.success
        assert "Bar Chart" in result.output

    @pytest.mark.asyncio
    async def test_transform_group_by(self):
        csv_data = "dept,salary\nEng,100\nEng,120\nSales,80\nSales,90"
        await self.tool.execute(action="load", dataset="emp", data=csv_data)
        result = await self.tool.execute(
            action="transform", dataset="emp",
            group_by="dept", agg="avg", value_column="salary"
        )
        assert result.success
        assert "Eng" in result.output
        assert "Sales" in result.output

    @pytest.mark.asyncio
    async def test_export_csv(self):
        csv_data = "a,b\n1,2\n3,4"
        await self.tool.execute(action="load", dataset="test", data=csv_data)
        result = await self.tool.execute(
            action="export", dataset="test", format="csv"
        )
        assert result.success
        assert "a,b" in result.output

    @pytest.mark.asyncio
    async def test_list_datasets(self):
        csv_data = "x\n1"
        await self.tool.execute(action="load", dataset="ds1", data=csv_data)
        result = await self.tool.execute(action="list")
        assert result.success
        assert "ds1" in result.output

    @pytest.mark.asyncio
    async def test_query_nonexistent_dataset(self):
        result = await self.tool.execute(
            action="query", dataset="nope"
        )
        assert not result.success


# =============================================================================
# Template Tool Tests
# =============================================================================

class TestTemplateTool:

    def setup_method(self):
        self.tool = TemplateTool()

    @pytest.mark.asyncio
    async def test_list_includes_builtins(self):
        result = await self.tool.execute(action="list")
        assert result.success
        for name in BUILTIN_TEMPLATES:
            assert name in result.output

    @pytest.mark.asyncio
    async def test_show_template(self):
        result = await self.tool.execute(action="show", name="email-campaign")
        assert result.success
        assert "subject" in result.output.lower()

    @pytest.mark.asyncio
    async def test_render_template(self):
        result = await self.tool.execute(
            action="render",
            name="executive-summary",
            variables={
                "title": "Q3 Report",
                "date": "2026-01-15",
                "author": "Agent42",
                "objective": "Review Q3 performance",
                "key_finding_1": "Revenue up 15%",
                "key_finding_2": "Churn down 3%",
                "key_finding_3": "NPS at 72",
                "recommendation": "Double down on retention",
                "next_steps": "Implement loyalty program",
                "timeline": "Q4 2026",
            },
        )
        assert result.success
        assert "Q3 Report" in result.output
        assert "Revenue up 15%" in result.output

    @pytest.mark.asyncio
    async def test_render_missing_variables(self):
        result = await self.tool.execute(
            action="render",
            name="executive-summary",
            variables={"title": "Test"},
        )
        assert not result.success
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_create_custom_template(self):
        result = await self.tool.execute(
            action="create",
            name="my-template",
            content="Hello {name}, welcome to {place}!",
            description="Greeting template",
        )
        assert result.success
        assert "2 variables" in result.output

    @pytest.mark.asyncio
    async def test_render_custom_template(self):
        await self.tool.execute(
            action="create",
            name="greeting",
            content="Hi {name}!",
        )
        result = await self.tool.execute(
            action="render",
            name="greeting",
            variables={"name": "World"},
        )
        assert result.success
        assert "Hi World!" in result.output

    @pytest.mark.asyncio
    async def test_delete_custom_template(self):
        await self.tool.execute(
            action="create", name="temp", content="{x}"
        )
        result = await self.tool.execute(action="delete", name="temp")
        assert result.success

    @pytest.mark.asyncio
    async def test_delete_builtin_fails(self):
        result = await self.tool.execute(action="delete", name="email-campaign")
        assert not result.success


# =============================================================================
# Outline Tool Tests
# =============================================================================

class TestOutlineTool:

    def setup_method(self):
        self.tool = OutlineTool()

    @pytest.mark.asyncio
    async def test_types(self):
        result = await self.tool.execute(action="types")
        assert result.success
        assert "article" in result.output
        assert "presentation" in result.output
        assert "report" in result.output

    @pytest.mark.asyncio
    async def test_create_article_outline(self):
        result = await self.tool.execute(
            action="create",
            doc_type="article",
            topic="AI in Healthcare",
            name="test-article",
        )
        assert result.success
        assert "Introduction" in result.output
        assert "Conclusion" in result.output

    @pytest.mark.asyncio
    async def test_create_presentation_outline(self):
        result = await self.tool.execute(
            action="create",
            doc_type="presentation",
            topic="Q3 Review",
            name="test-pres",
        )
        assert result.success
        assert "Title Slide" in result.output
        assert "Q&A" in result.output

    @pytest.mark.asyncio
    async def test_expand_section(self):
        await self.tool.execute(
            action="create", doc_type="article", name="test-expand"
        )
        result = await self.tool.execute(
            action="expand",
            name="test-expand",
            section=1,
            subsections=["Hook with stat", "Personal anecdote", "Thesis statement"],
        )
        assert result.success
        assert "Hook with stat" in result.output

    @pytest.mark.asyncio
    async def test_reorder_sections(self):
        await self.tool.execute(
            action="create", doc_type="article", name="test-reorder"
        )
        result = await self.tool.execute(
            action="reorder",
            name="test-reorder",
            new_order=[7, 1, 2, 3, 4, 5, 6],
        )
        assert result.success
        assert "reordered" in result.output.lower()

    @pytest.mark.asyncio
    async def test_show_nonexistent(self):
        # When no outlines exist at all, returns success with helpful message
        result = await self.tool.execute(action="show", name="nope")
        assert "No outlines" in result.output or not result.success

    @pytest.mark.asyncio
    async def test_export(self):
        await self.tool.execute(
            action="create", doc_type="report", name="test-export"
        )
        result = await self.tool.execute(action="export", name="test-export")
        assert result.success
        assert "##" in result.output  # Markdown headings in export mode


# =============================================================================
# Scoring Tool Tests
# =============================================================================

class TestScoringTool:

    def setup_method(self):
        self.tool = ScoringTool()

    @pytest.mark.asyncio
    async def test_list_includes_builtins(self):
        result = await self.tool.execute(action="list")
        assert result.success
        for name in BUILTIN_RUBRICS:
            assert name in result.output

    @pytest.mark.asyncio
    async def test_show_rubric(self):
        result = await self.tool.execute(action="show", rubric="marketing-copy")
        assert result.success
        assert "Audience Fit" in result.output
        assert "Weight" in result.output

    @pytest.mark.asyncio
    async def test_score_content(self):
        result = await self.tool.execute(
            action="score",
            rubric="marketing-copy",
            content_label="Homepage v2",
            scores={
                "Audience Fit": 8,
                "Value Proposition": 7,
                "Call to Action": 9,
                "Clarity": 8,
                "Brand Voice": 6,
            },
        )
        assert result.success
        assert "Scorecard" in result.output
        assert "Homepage v2" in result.output
        assert "/10" in result.output

    @pytest.mark.asyncio
    async def test_score_missing_criteria(self):
        result = await self.tool.execute(
            action="score",
            rubric="marketing-copy",
            scores={"Audience Fit": 8},
        )
        assert not result.success
        assert "Missing" in result.error

    @pytest.mark.asyncio
    async def test_define_custom_rubric(self):
        result = await self.tool.execute(
            action="define",
            rubric="test-rubric",
            description="Testing rubric",
            criteria=[
                {"name": "Quality", "weight": 60, "description": "Overall quality"},
                {"name": "Speed", "weight": 40, "description": "Completion time"},
            ],
        )
        assert result.success

    @pytest.mark.asyncio
    async def test_define_rubric_weights_must_sum_100(self):
        result = await self.tool.execute(
            action="define",
            rubric="bad-rubric",
            criteria=[
                {"name": "A", "weight": 50, "description": "a"},
                {"name": "B", "weight": 30, "description": "b"},
            ],
        )
        assert not result.success
        assert "100" in result.error

    @pytest.mark.asyncio
    async def test_compare_versions(self):
        result = await self.tool.execute(
            action="compare",
            rubric="email",
            versions=[
                {
                    "label": "Draft A",
                    "scores": {
                        "Subject Line": 8,
                        "Purpose Clarity": 7,
                        "Tone": 6,
                        "Brevity": 9,
                        "Call to Action": 7,
                    },
                },
                {
                    "label": "Draft B",
                    "scores": {
                        "Subject Line": 6,
                        "Purpose Clarity": 9,
                        "Tone": 8,
                        "Brevity": 7,
                        "Call to Action": 8,
                    },
                },
            ],
        )
        assert result.success
        assert "Draft A" in result.output
        assert "Draft B" in result.output
        assert "Rank" in result.output

    @pytest.mark.asyncio
    async def test_delete_builtin_fails(self):
        result = await self.tool.execute(action="delete", rubric="marketing-copy")
        assert not result.success

    @pytest.mark.asyncio
    async def test_delete_custom_rubric(self):
        await self.tool.execute(
            action="define",
            rubric="temp",
            criteria=[
                {"name": "X", "weight": 100, "description": "x"},
            ],
        )
        result = await self.tool.execute(action="delete", rubric="temp")
        assert result.success


# =============================================================================
# All Builtin Rubrics Validation
# =============================================================================

class TestBuiltinRubrics:
    """Validate all built-in rubrics have correct structure."""

    def test_weights_sum_to_100(self):
        for name, rubric in BUILTIN_RUBRICS.items():
            total = sum(c["weight"] for c in rubric["criteria"])
            assert total == 100, f"Rubric '{name}' weights sum to {total}, not 100"

    def test_all_criteria_have_fields(self):
        for rubric_name, rubric in BUILTIN_RUBRICS.items():
            for c in rubric["criteria"]:
                assert "name" in c, f"{rubric_name}: criterion missing name"
                assert "weight" in c, f"{rubric_name}.{c.get('name')}: missing weight"
                assert "description" in c, f"{rubric_name}.{c.get('name')}: missing description"

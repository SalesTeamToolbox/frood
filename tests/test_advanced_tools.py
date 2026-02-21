"""Tests for advanced tools: browser, code_intel, dependency_audit, docker, python_exec,
repo_map, pr_generator, security_analyzer, workflow, summarizer, file_watcher."""

import json
import os
import tempfile

import pytest

from tools.base import ToolResult


# ---------------------------------------------------------------------------
# CodeIntelTool
# ---------------------------------------------------------------------------
class TestCodeIntelTool:
    """Tests for AST-aware code intelligence."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self.tmpdir, "src", "app.py"), "w") as f:
            f.write(
                "import os\n"
                "from pathlib import Path\n\n"
                "MAX_SIZE = 1024\n\n"
                "class MyApp:\n"
                "    def __init__(self, name: str):\n"
                "        self.name = name\n\n"
                "    async def run(self):\n"
                "        pass\n\n"
                "class Helper(MyApp):\n"
                "    def assist(self):\n"
                "        pass\n\n"
                "def main():\n"
                "    app = MyApp('test')\n"
            )
        from tools.code_intel import CodeIntelTool
        self.tool = CodeIntelTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "code_intel"
        assert "action" in self.tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_find_class(self):
        result = await self.tool.execute(action="find_class", name="MyApp")
        assert result.success is True
        assert "MyApp" in result.output

    @pytest.mark.asyncio
    async def test_find_class_with_body(self):
        result = await self.tool.execute(action="find_class", name="MyApp", include_body=True)
        assert result.success is True
        assert "def __init__" in result.output

    @pytest.mark.asyncio
    async def test_find_function(self):
        result = await self.tool.execute(action="find_function", name="main")
        assert result.success is True
        assert "main" in result.output

    @pytest.mark.asyncio
    async def test_find_method(self):
        result = await self.tool.execute(action="find_method", name="run")
        assert result.success is True
        assert "MyApp.run" in result.output

    @pytest.mark.asyncio
    async def test_find_imports(self):
        result = await self.tool.execute(action="find_imports", name="os")
        assert result.success is True
        assert "import os" in result.output

    @pytest.mark.asyncio
    async def test_list_symbols(self):
        result = await self.tool.execute(action="list_symbols")
        assert result.success is True
        assert "MyApp" in result.output
        assert "MAX_SIZE" in result.output

    @pytest.mark.asyncio
    async def test_outline(self):
        result = await self.tool.execute(action="outline", path="src/app.py")
        assert result.success is True
        assert "class MyApp" in result.output
        assert "def main" in result.output

    @pytest.mark.asyncio
    async def test_no_match(self):
        result = await self.tool.execute(action="find_class", name="NonExistent")
        assert result.success is True
        assert "No classes" in result.output


# ---------------------------------------------------------------------------
# SecurityAnalyzerTool
# ---------------------------------------------------------------------------
class TestSecurityAnalyzerTool:
    """Tests for security risk analysis."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from tools.security_analyzer import SecurityAnalyzerTool
        self.tool = SecurityAnalyzerTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "security_analyze"

    @pytest.mark.asyncio
    async def test_scan_clean_code(self):
        result = await self.tool.execute(
            action="scan_code",
            code="def hello():\n    return 'world'\n",
        )
        assert result.success is True
        assert "CLEAN" in result.output

    @pytest.mark.asyncio
    async def test_scan_eval(self):
        result = await self.tool.execute(
            action="scan_code",
            code="result = eval(user_input)\n",
        )
        assert result.success is False
        assert "CRITICAL" in result.output

    @pytest.mark.asyncio
    async def test_scan_hardcoded_secret(self):
        result = await self.tool.execute(
            action="scan_code",
            code='SECRET = "my_api_key_12345"\n',
        )
        assert "SECRET" in result.output or "secret" in result.output.lower()

    @pytest.mark.asyncio
    async def test_scan_command_safe(self):
        result = await self.tool.execute(
            action="scan_command",
            command="git status",
        )
        assert result.success is True
        assert "CLEAN" in result.output

    @pytest.mark.asyncio
    async def test_scan_command_dangerous(self):
        result = await self.tool.execute(
            action="scan_command",
            command="rm -rf /",
        )
        assert result.success is False
        assert "CRITICAL" in result.output

    @pytest.mark.asyncio
    async def test_scan_file(self):
        filepath = os.path.join(self.tmpdir, "safe.py")
        with open(filepath, "w") as f:
            f.write("x = 1 + 2\nprint(x)\n")
        result = await self.tool.execute(action="scan_file", path="safe.py")
        assert result.success is True


# ---------------------------------------------------------------------------
# PythonExecTool
# ---------------------------------------------------------------------------
class TestPythonExecTool:
    """Tests for sandboxed Python execution."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from tools.python_exec import PythonExecTool
        self.tool = PythonExecTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "python_exec"

    @pytest.mark.asyncio
    async def test_simple_execution(self):
        result = await self.tool.execute(code="print('hello world')")
        assert result.success is True
        assert "hello world" in result.output

    @pytest.mark.asyncio
    async def test_math(self):
        result = await self.tool.execute(code="print(2 ** 10)")
        assert result.success is True
        assert "1024" in result.output

    @pytest.mark.asyncio
    async def test_syntax_error(self):
        result = await self.tool.execute(code="def broken(\n")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_empty_code(self):
        result = await self.tool.execute(code="")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_multiline(self):
        code = "for i in range(3):\n    print(f'item {i}')"
        result = await self.tool.execute(code=code)
        assert result.success is True
        assert "item 0" in result.output
        assert "item 2" in result.output


# ---------------------------------------------------------------------------
# RepoMapTool
# ---------------------------------------------------------------------------
class TestRepoMapTool:
    """Tests for repository structure mapping."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        os.makedirs(os.path.join(self.tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self.tmpdir, "src", "main.py"), "w") as f:
            f.write("class App:\n    def run(self):\n        pass\n\ndef main():\n    pass\n")
        with open(os.path.join(self.tmpdir, "README.md"), "w") as f:
            f.write("# Project\n")
        from tools.repo_map import RepoMapTool
        self.tool = RepoMapTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "repo_map"

    @pytest.mark.asyncio
    async def test_basic_map(self):
        result = await self.tool.execute()
        assert result.success is True
        assert "Repository Map" in result.output
        assert "main.py" in result.output

    @pytest.mark.asyncio
    async def test_signatures(self):
        result = await self.tool.execute(signatures=True)
        assert result.success is True
        assert "class App" in result.output
        assert "def main" in result.output

    @pytest.mark.asyncio
    async def test_no_signatures(self):
        result = await self.tool.execute(signatures=False)
        assert result.success is True
        assert "File Tree" in result.output

    @pytest.mark.asyncio
    async def test_nonexistent_dir(self):
        result = await self.tool.execute(path="nonexistent")
        assert result.success is False


# ---------------------------------------------------------------------------
# SummarizerTool
# ---------------------------------------------------------------------------
class TestSummarizerTool:
    """Tests for content summarization."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from tools.summarizer_tool import SummarizerTool
        self.tool = SummarizerTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "summarize"

    @pytest.mark.asyncio
    async def test_summarize_code(self):
        code = "import os\nimport sys\n\nclass Foo:\n    def bar(self):\n        pass\n\ndef main():\n    pass\n"
        result = await self.tool.execute(action="code", content=code)
        assert result.success is True
        assert "import" in result.output.lower()
        assert "class Foo" in result.output or "def main" in result.output

    @pytest.mark.asyncio
    async def test_summarize_diff(self):
        diff = (
            "diff --git a/file.py b/file.py\n"
            "--- a/file.py\n"
            "+++ b/file.py\n"
            "@@ -1,3 +1,4 @@\n"
            " line1\n"
            "-old line\n"
            "+new line\n"
            "+added line\n"
            " line3\n"
        )
        result = await self.tool.execute(action="diff", content=diff)
        assert result.success is True
        assert "file.py" in result.output

    @pytest.mark.asyncio
    async def test_summarize_log(self):
        log = (
            "2024-01-01 INFO Starting server\n"
            "2024-01-01 WARNING Slow query detected\n"
            "2024-01-01 ERROR Connection refused\n"
            "2024-01-01 INFO Request handled\n"
        )
        result = await self.tool.execute(action="log", content=log)
        assert result.success is True
        assert "Error" in result.output or "error" in result.output.lower()

    @pytest.mark.asyncio
    async def test_summarize_text(self):
        text = "# Heading\n\nThis is a paragraph.\n\n- Item one\n- Item two\n"
        result = await self.tool.execute(action="text", content=text)
        assert result.success is True

    @pytest.mark.asyncio
    async def test_empty_content(self):
        result = await self.tool.execute(action="text", content="")
        assert result.success is False


# ---------------------------------------------------------------------------
# FileWatcherTool
# ---------------------------------------------------------------------------
class TestFileWatcherTool:
    """Tests for file change monitoring."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(self.tmpdir, "file1.txt"), "w") as f:
            f.write("original content")
        from tools.file_watcher import FileWatcherTool
        self.tool = FileWatcherTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "file_watcher"

    @pytest.mark.asyncio
    async def test_snapshot_and_no_changes(self):
        result = await self.tool.execute(action="snapshot", watch_id="test")
        assert result.success is True
        assert "1 files" in result.output

        result = await self.tool.execute(action="check", watch_id="test")
        assert result.success is True
        assert "No changes" in result.output

    @pytest.mark.asyncio
    async def test_detect_modification(self):
        await self.tool.execute(action="snapshot", watch_id="test")

        # Modify a file
        with open(os.path.join(self.tmpdir, "file1.txt"), "w") as f:
            f.write("modified content")

        result = await self.tool.execute(action="check", watch_id="test")
        assert result.success is True
        assert "Modified" in result.output

    @pytest.mark.asyncio
    async def test_detect_addition(self):
        await self.tool.execute(action="snapshot", watch_id="test")

        # Add a file
        with open(os.path.join(self.tmpdir, "file2.txt"), "w") as f:
            f.write("new file")

        result = await self.tool.execute(action="check", watch_id="test")
        assert result.success is True
        assert "Added" in result.output

    @pytest.mark.asyncio
    async def test_detect_deletion(self):
        await self.tool.execute(action="snapshot", watch_id="test")

        os.remove(os.path.join(self.tmpdir, "file1.txt"))

        result = await self.tool.execute(action="check", watch_id="test")
        assert result.success is True
        assert "Deleted" in result.output

    @pytest.mark.asyncio
    async def test_list_watches(self):
        await self.tool.execute(action="snapshot", watch_id="w1")
        await self.tool.execute(action="snapshot", watch_id="w2")

        result = await self.tool.execute(action="list")
        assert result.success is True
        assert "w1" in result.output
        assert "w2" in result.output

    @pytest.mark.asyncio
    async def test_check_no_snapshot(self):
        result = await self.tool.execute(action="check", watch_id="nonexistent")
        assert result.success is False


# ---------------------------------------------------------------------------
# WorkflowTool
# ---------------------------------------------------------------------------
class TestWorkflowTool:
    """Tests for the workflow engine."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from tools.workflow_tool import WorkflowTool
        self.tool = WorkflowTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "workflow"

    @pytest.mark.asyncio
    async def test_define_workflow(self):
        steps = [
            {"tool": "shell", "args": {"command": "echo hello"}, "description": "Say hello"},
            {"tool": "shell", "args": {"command": "echo done"}, "description": "Finish"},
        ]
        result = await self.tool.execute(action="define", name="test-wf", steps=steps)
        assert result.success is True
        assert "test-wf" in result.output
        assert "2 steps" in result.output

    @pytest.mark.asyncio
    async def test_list_workflows(self):
        steps = [{"tool": "shell", "args": {}, "description": "step"}]
        await self.tool.execute(action="define", name="wf1", steps=steps, description="First workflow")
        result = await self.tool.execute(action="list")
        assert result.success is True
        assert "wf1" in result.output

    @pytest.mark.asyncio
    async def test_show_workflow(self):
        steps = [{"tool": "shell", "args": {"command": "echo hi"}, "description": "Greet"}]
        await self.tool.execute(action="define", name="wf-show", steps=steps)
        result = await self.tool.execute(action="show", name="wf-show")
        assert result.success is True
        assert "Greet" in result.output

    @pytest.mark.asyncio
    async def test_delete_workflow(self):
        steps = [{"tool": "shell", "args": {}, "description": "step"}]
        await self.tool.execute(action="define", name="wf-del", steps=steps)
        result = await self.tool.execute(action="delete", name="wf-del")
        assert result.success is True
        assert "deleted" in result.output.lower()

    @pytest.mark.asyncio
    async def test_run_no_registry(self):
        steps = [{"tool": "shell", "args": {}, "description": "step"}]
        await self.tool.execute(action="define", name="wf-run", steps=steps)
        result = await self.tool.execute(action="run", name="wf-run")
        assert result.success is False
        assert "registry" in result.error.lower()

    @pytest.mark.asyncio
    async def test_define_no_steps(self):
        result = await self.tool.execute(action="define", name="empty")
        assert result.success is False


# ---------------------------------------------------------------------------
# BrowserTool — minimal (Playwright may not be installed)
# ---------------------------------------------------------------------------
class TestBrowserTool:
    """Tests for browser automation tool metadata."""

    def setup_method(self):
        from tools.browser_tool import BrowserTool
        self.tool = BrowserTool(".")

    def test_tool_metadata(self):
        assert self.tool.name == "browser"
        assert "action" in self.tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_no_action(self):
        result = await self.tool.execute()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_navigate_no_url(self):
        result = await self.tool.execute(action="navigate")
        # Will fail because either Playwright not installed or no URL
        assert result.success is False


# ---------------------------------------------------------------------------
# DockerTool — minimal (Docker may not be installed)
# ---------------------------------------------------------------------------
class TestDockerTool:
    """Tests for Docker tool metadata."""

    def setup_method(self):
        from tools.docker_tool import DockerTool
        self.tool = DockerTool(".")

    def test_tool_metadata(self):
        assert self.tool.name == "docker"
        assert "action" in self.tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_no_action(self):
        result = await self.tool.execute()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_run_no_image(self):
        result = await self.tool.execute(action="run")
        assert result.success is False
        assert "image" in result.error.lower()


# ---------------------------------------------------------------------------
# DependencyAuditTool
# ---------------------------------------------------------------------------
class TestDependencyAuditTool:
    """Tests for dependency audit tool."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from tools.dependency_audit import DependencyAuditTool
        self.tool = DependencyAuditTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "dependency_audit"

    def test_detect_python(self):
        with open(os.path.join(self.tmpdir, "requirements.txt"), "w") as f:
            f.write("flask==2.0\n")
        assert self.tool._detect_ecosystem() == "python"

    def test_detect_javascript(self):
        with open(os.path.join(self.tmpdir, "package.json"), "w") as f:
            json.dump({"name": "test"}, f)
        assert self.tool._detect_ecosystem() == "javascript"

    def test_format_pip_audit_clean(self):
        result = self.tool._format_pip_audit({"dependencies": [{"name": "flask"}], "vulnerabilities": []}, fix=False)
        assert result.success is True
        assert "CLEAN" in result.output

    def test_format_pip_audit_vulns(self):
        data = {
            "dependencies": [],
            "vulnerabilities": [{
                "name": "flask", "version": "1.0", "id": "CVE-2024-1234",
                "description": "XSS vulnerability", "fix_versions": ["2.0"],
            }],
        }
        result = self.tool._format_pip_audit(data, fix=False)
        assert result.success is False
        assert "CVE-2024-1234" in result.output

    def test_format_npm_audit_clean(self):
        data = {"metadata": {"vulnerabilities": {"critical": 0, "high": 0, "moderate": 0, "low": 0}, "totalDependencies": 50}}
        result = self.tool._format_npm_audit(data, fix=False)
        assert result.success is True
        assert "CLEAN" in result.output


# ---------------------------------------------------------------------------
# PRGeneratorTool
# ---------------------------------------------------------------------------
class TestPRGeneratorTool:
    """Tests for PR generator tool."""

    def setup_method(self):
        from tools.pr_generator import PRGeneratorTool
        self.tool = PRGeneratorTool(".")

    def test_tool_metadata(self):
        assert self.tool.name == "create_pr"
        assert "action" in self.tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_create_no_title(self):
        result = await self.tool.execute(action="create")
        assert result.success is False
        assert "title" in result.error.lower()

    @pytest.mark.asyncio
    async def test_view_no_number(self):
        result = await self.tool.execute(action="view")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_no_action(self):
        result = await self.tool.execute()
        assert result.success is False

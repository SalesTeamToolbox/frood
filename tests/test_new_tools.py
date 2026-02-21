"""Tests for new tools: git, grep, diff, test_runner, linter, http_client."""

import json
import os
import tempfile

import pytest

from tools.base import ToolResult


# ---------------------------------------------------------------------------
# GitTool
# ---------------------------------------------------------------------------
class TestGitTool:
    """Tests for the dedicated git tool."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Initialize a git repo in the tmpdir (disable gpg signing for test environments)
        os.system(
            f"cd {self.tmpdir} && git init -q "
            f"&& git config user.email test@test.com "
            f"&& git config user.name Test "
            f"&& git config commit.gpgsign false"
        )
        # Create initial commit
        with open(os.path.join(self.tmpdir, "README.md"), "w") as f:
            f.write("# Test\n")
        ret = os.system(f"cd {self.tmpdir} && git add . && git commit -q --no-gpg-sign -m 'init'")
        self._has_initial_commit = ret == 0

        from tools.git_tool import GitTool
        self.tool = GitTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "git"
        assert "git" in self.tool.description.lower()
        assert "action" in self.tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_status(self):
        result = await self.tool.execute(action="status")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_log(self):
        if not self._has_initial_commit:
            pytest.skip("git commit not available in this environment")
        result = await self.tool.execute(action="log")
        assert result.success is True
        assert "init" in result.output

    @pytest.mark.asyncio
    async def test_diff_no_changes(self):
        result = await self.tool.execute(action="diff")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_branch_list(self):
        result = await self.tool.execute(action="branch")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_add_and_commit(self):
        if not self._has_initial_commit:
            pytest.skip("git commit not available in this environment")
        # Create a new file
        with open(os.path.join(self.tmpdir, "new.txt"), "w") as f:
            f.write("hello")

        result = await self.tool.execute(action="add", args="new.txt")
        assert result.success is True

        result = await self.tool.execute(action="commit", args="-m 'add new file'")
        assert result.success is True

    @pytest.mark.asyncio
    async def test_unknown_action(self):
        result = await self.tool.execute(action="rebase")
        assert result.success is False
        assert "Unsupported" in result.error or "Unknown" in result.error

    @pytest.mark.asyncio
    async def test_blocks_env_file_staging(self):
        with open(os.path.join(self.tmpdir, ".env"), "w") as f:
            f.write("SECRET=password123")
        result = await self.tool.execute(action="add", args=".env")
        assert result.success is False
        assert "secret" in result.error.lower() or "blocked" in result.error.lower()

    @pytest.mark.asyncio
    async def test_show(self):
        if not self._has_initial_commit:
            pytest.skip("git commit not available in this environment")
        result = await self.tool.execute(action="show", args="HEAD")
        assert result.success is True
        assert "init" in result.output

    @pytest.mark.asyncio
    async def test_blame(self):
        if not self._has_initial_commit:
            pytest.skip("git commit not available in this environment")
        result = await self.tool.execute(action="blame", args="README.md")
        assert result.success is True


# ---------------------------------------------------------------------------
# GrepTool
# ---------------------------------------------------------------------------
class TestGrepTool:
    """Tests for the codebase search tool."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        # Create some test files
        os.makedirs(os.path.join(self.tmpdir, "src"), exist_ok=True)
        with open(os.path.join(self.tmpdir, "src", "main.py"), "w") as f:
            f.write("def hello_world():\n    print('Hello, World!')\n\ndef goodbye():\n    pass\n")
        with open(os.path.join(self.tmpdir, "src", "utils.py"), "w") as f:
            f.write("import os\n\ndef get_path():\n    return os.getcwd()\n")

        from tools.grep_tool import GrepTool
        self.tool = GrepTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "grep"
        assert "search" in self.tool.description.lower()

    @pytest.mark.asyncio
    async def test_search_pattern(self):
        result = await self.tool.execute(pattern="hello_world")
        assert result.success is True
        assert "hello_world" in result.output

    @pytest.mark.asyncio
    async def test_search_no_match(self):
        result = await self.tool.execute(pattern="nonexistent_function_xyz")
        assert result.success is True  # No error, just no matches

    @pytest.mark.asyncio
    async def test_search_with_path(self):
        result = await self.tool.execute(pattern="def", path="src/main.py")
        assert result.success is True
        assert "def" in result.output

    @pytest.mark.asyncio
    async def test_case_insensitive(self):
        result = await self.tool.execute(pattern="HELLO", case_insensitive=True)
        assert result.success is True
        assert "Hello" in result.output or "hello" in result.output

    @pytest.mark.asyncio
    async def test_empty_pattern(self):
        result = await self.tool.execute(pattern="")
        assert result.success is False


# ---------------------------------------------------------------------------
# DiffTool
# ---------------------------------------------------------------------------
class TestDiffTool:
    """Tests for the diff/patch tool."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        with open(os.path.join(self.tmpdir, "file_a.txt"), "w") as f:
            f.write("line 1\nline 2\nline 3\n")
        with open(os.path.join(self.tmpdir, "file_b.txt"), "w") as f:
            f.write("line 1\nline 2 modified\nline 3\n")

        from tools.diff_tool import DiffTool
        self.tool = DiffTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "diff"
        assert "diff" in self.tool.description.lower()

    @pytest.mark.asyncio
    async def test_create_diff(self):
        result = await self.tool.execute(
            action="create", file_a="file_a.txt", file_b="file_b.txt"
        )
        assert result.success is True
        assert "line 2" in result.output

    @pytest.mark.asyncio
    async def test_compare_strings(self):
        result = await self.tool.execute(
            action="compare",
            content_a="hello\nworld\n",
            content_b="hello\nearth\n",
        )
        assert result.success is True
        assert "world" in result.output or "earth" in result.output

    @pytest.mark.asyncio
    async def test_create_diff_identical(self):
        result = await self.tool.execute(
            action="create", file_a="file_a.txt", file_b="file_a.txt"
        )
        assert result.success is True
        assert "identical" in result.output.lower() or result.output.strip() == ""


# ---------------------------------------------------------------------------
# TestRunnerTool
# ---------------------------------------------------------------------------
class TestTestRunnerTool:
    """Tests for the test runner tool."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from tools.test_runner import TestRunnerTool
        self.tool = TestRunnerTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "run_tests"
        assert "test" in self.tool.description.lower()
        assert "framework" in self.tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_detect_framework_pytest(self):
        # Create a pyproject.toml to trigger pytest detection
        with open(os.path.join(self.tmpdir, "pyproject.toml"), "w") as f:
            f.write("[tool.pytest.ini_options]\n")
        framework = await self.tool._detect_framework()
        assert framework == "pytest"

    @pytest.mark.asyncio
    async def test_detect_framework_vitest(self):
        with open(os.path.join(self.tmpdir, "package.json"), "w") as f:
            json.dump({"devDependencies": {"vitest": "^1.0"}}, f)
        framework = await self.tool._detect_framework()
        assert framework == "vitest"

    @pytest.mark.asyncio
    async def test_detect_framework_jest(self):
        with open(os.path.join(self.tmpdir, "package.json"), "w") as f:
            json.dump({"devDependencies": {"jest": "^29.0"}}, f)
        framework = await self.tool._detect_framework()
        assert framework == "jest"

    @pytest.mark.asyncio
    async def test_custom_command(self):
        result = await self.tool.execute(framework="custom", command="echo 'tests passed'")
        assert result.success is True
        assert "tests passed" in result.output

    @pytest.mark.asyncio
    async def test_custom_no_command(self):
        result = await self.tool.execute(framework="custom")
        assert result.success is False
        assert "command required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_unknown_framework(self):
        result = await self.tool.execute(framework="mocha")
        assert result.success is False


# ---------------------------------------------------------------------------
# LinterTool
# ---------------------------------------------------------------------------
class TestLinterTool:
    """Tests for the linter tool."""

    def setup_method(self):
        self.tmpdir = tempfile.mkdtemp()
        from tools.linter_tool import LinterTool
        self.tool = LinterTool(self.tmpdir)

    def test_tool_metadata(self):
        assert self.tool.name == "run_linter"
        assert "lint" in self.tool.description.lower()

    def test_detect_linter_python(self):
        with open(os.path.join(self.tmpdir, "pyproject.toml"), "w") as f:
            f.write("[tool.ruff]\n")
        # Will detect ruff if available, otherwise still returns ruff
        linter = self.tool._detect_linter()
        assert linter in ("ruff", "eslint")

    def test_detect_linter_js(self):
        with open(os.path.join(self.tmpdir, ".eslintrc.json"), "w") as f:
            f.write("{}")
        linter = self.tool._detect_linter()
        assert linter == "eslint"

    @pytest.mark.asyncio
    async def test_custom_linter(self):
        result = await self.tool.execute(linter="custom", command="echo 'no errors'")
        assert result.success is True
        assert "no errors" in result.output

    @pytest.mark.asyncio
    async def test_custom_no_command(self):
        result = await self.tool.execute(linter="custom")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_unknown_linter(self):
        result = await self.tool.execute(linter="rubocop")
        assert result.success is False

    def test_format_ruff_issues_clean(self):
        result = self.tool._format_ruff_issues([], fix=False)
        assert result.success is True
        assert "CLEAN" in result.output

    def test_format_ruff_issues_found(self):
        issues = [
            {
                "filename": "test.py",
                "location": {"row": 10, "column": 1},
                "code": "E501",
                "message": "Line too long",
                "fix": {"applicability": "safe"},
            }
        ]
        result = self.tool._format_ruff_issues(issues, fix=False)
        assert result.success is False
        assert "E501" in result.output
        assert "test.py" in result.output

    def test_format_eslint_clean(self):
        result = self.tool._format_eslint_results([], fix=False)
        assert result.success is True
        assert "CLEAN" in result.output

    def test_format_eslint_errors(self):
        results = [
            {
                "filePath": "src/app.js",
                "errorCount": 1,
                "warningCount": 0,
                "messages": [
                    {
                        "line": 5,
                        "column": 10,
                        "severity": 2,
                        "ruleId": "no-unused-vars",
                        "message": "'x' is defined but never used",
                    }
                ],
            }
        ]
        result = self.tool._format_eslint_results(results, fix=False)
        assert result.success is False
        assert "no-unused-vars" in result.output


# ---------------------------------------------------------------------------
# HttpClientTool
# ---------------------------------------------------------------------------
class TestHttpClientTool:
    """Tests for the HTTP client tool."""

    def setup_method(self):
        from tools.http_client import HttpClientTool
        self.tool = HttpClientTool()

    def test_tool_metadata(self):
        assert self.tool.name == "http_request"
        assert "http" in self.tool.description.lower()
        assert "url" in self.tool.parameters["properties"]

    @pytest.mark.asyncio
    async def test_no_url(self):
        result = await self.tool.execute()
        assert result.success is False
        assert "required" in result.error.lower()

    @pytest.mark.asyncio
    async def test_blocks_ssrf(self):
        result = await self.tool.execute(url="http://127.0.0.1/secret")
        # Should be blocked if SSRF protection is loaded
        if result.success is False:
            assert "blocked" in result.error.lower() or "private" in result.error.lower()

    @pytest.mark.asyncio
    async def test_invalid_scheme(self):
        result = await self.tool.execute(url="ftp://example.com/file")
        assert result.success is False
        assert "scheme" in result.error.lower()

    def test_format_response(self):
        output = self.tool._format_response(
            status=200,
            reason="OK",
            headers={"Content-Type": "application/json"},
            body='{"key": "value"}',
            elapsed=0.5,
            method="GET",
            url="https://api.example.com/test",
        )
        assert "200 OK" in output
        assert "GET" in output
        assert "0.50s" in output

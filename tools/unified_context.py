"""
Unified Context Tool — 6-source context assembly for Claude Code.

Wraps ContextAssemblerTool (memory, docs, git, skills) and adds three new
sources:

1. jcodemunch code symbols   — semantic symbol + text search via MCP-to-MCP
2. GSD workstream state      — active phase/plan from .planning/workstreams/
3. Effectiveness ranking     — top tools by success_rate for the inferred task type

Token budget is split across 6 sources (D-13). Unused budget from unavailable
sources is redistributed proportionally to active sources (D-14).

MCP name: agent42_unified_context  (avoids collision with existing "context" tool)
"""

import asyncio
import hashlib
import logging
from pathlib import Path

import aiofiles
import yaml

from tools.base import Tool, ToolResult
from tools.context_assembler import (
    ContextAssemblerTool,
    _estimate_tokens,
    _extract_keywords,
    _truncate_to_budget,
)
from tools.mcp_client import MCPConnection

logger = logging.getLogger("agent42.tools.unified_context")

# ---------------------------------------------------------------------------
# Budget fractions (D-13) — must sum to 1.0
# ---------------------------------------------------------------------------
_UCT_BUDGET_MEMORY = 0.30
_UCT_BUDGET_CODE = 0.25
_UCT_BUDGET_GSD = 0.15
_UCT_BUDGET_GIT = 0.10
_UCT_BUDGET_SKILLS = 0.10
_UCT_BUDGET_EFFECTIVENESS = 0.10

# ---------------------------------------------------------------------------
# Work type -> effectiveness task type mapping (D-11)
# ---------------------------------------------------------------------------
_WORK_TYPE_TO_TASK_TYPE = {
    "security": "debugging",
    "tools": "coding",
    "testing": "debugging",
    "providers": "coding",
    "dashboard": "coding",
    "memory": "coding",
    "skills": "coding",
    "deployment": "project_setup",
    "config": "project_setup",
    "async": "coding",
    "structure": "project_setup",
    "gsd": "coding",
}

# ---------------------------------------------------------------------------
# Work type keywords (copied from .claude/hooks/context-loader.py — not imported,
# since hooks are scripts, not library modules)
# ---------------------------------------------------------------------------
_WORK_TYPE_KEYWORDS = {
    "security": [
        "sandbox",
        "command_filter",
        "approval_gate",
        "auth",
        "rate_limit",
        "url_policy",
        "security",
        "permission",
        "token",
        "password",
        "jwt",
        "credential",
        "encrypt",
        "ssrf",
        "injection",
        "xss",
    ],
    "tools": [
        "tool",
        "execute",
        "toolresult",
        "registry",
        "register",
        "to_schema",
        "parameters",
    ],
    "testing": [
        "test",
        "pytest",
        "fixture",
        "mock",
        "assert",
        "conftest",
        "coverage",
        "test_",
    ],
    "providers": [
        "provider",
        "model",
        "openrouter",
        "openai",
        "anthropic",
        "deepseek",
        "gemini",
        "vllm",
        "providerspec",
        "modelspec",
        "spending",
        "api_key",
    ],
    "skills": [
        "skill",
        "skill.md",
        "frontmatter",
        "task_type",
        "builtin",
        "workspace",
        "loader",
    ],
    "async": [
        "async",
        "await",
        "asyncio",
        "aiofiles",
        "coroutine",
        "event_loop",
        "gather",
        "taskgroup",
    ],
    "config": [
        "config",
        "settings",
        "env",
        "environment",
        "settings",
        "from_env",
        ".env",
    ],
    "dashboard": [
        "dashboard",
        "fastapi",
        "websocket",
        "jwt",
        "login",
        "api",
        "endpoint",
        "route",
    ],
    "memory": [
        "memory",
        "session",
        "embedding",
        "qdrant",
        "redis",
        "semantic",
        "vector",
        "consolidat",
    ],
    "deployment": [
        "deploy",
        "install",
        "nginx",
        "systemd",
        "docker",
        "production",
        "server",
        "compose",
    ],
    "structure": [
        "structure",
        "architecture",
        "overview",
        "onboarding",
    ],
    "gsd": [
        "build",
        "create",
        "implement",
        "refactor",
        "add feature",
        "phase",
        "plan",
    ],
}

# Task types that warrant fetching code symbols from jcodemunch
_CODE_TASK_TYPES = {
    "coding",
    "debugging",
    "refactoring",
    "app_create",
    "app_update",
    "project_setup",
}


# ---------------------------------------------------------------------------
# Module-level helpers
# ---------------------------------------------------------------------------


def _infer_task_type(topic: str) -> str:
    """Infer the effectiveness task type from a free-text topic string.

    Scans the topic for keywords belonging to each work type, then maps the
    first matching work type through _WORK_TYPE_TO_TASK_TYPE.

    Returns an effectiveness task type string (e.g. "coding", "debugging",
    "project_setup") or "" if no match is found.
    """
    topic_lower = topic.lower()
    for work_type, keywords in _WORK_TYPE_KEYWORDS.items():
        for kw in keywords:
            if kw in topic_lower:
                return _WORK_TYPE_TO_TASK_TYPE.get(work_type, "coding")
    return ""


# ---------------------------------------------------------------------------
# UnifiedContextTool
# ---------------------------------------------------------------------------


class UnifiedContextTool(Tool):
    """Assemble unified project context from 6 sources.

    Sources:
    1. Semantic memory + project docs + git + skills  (via ContextAssemblerTool)
    2. jcodemunch code symbols (MCP-to-MCP, per-call connect/disconnect, 3s timeout)
    3. GSD workstream state   (active phases/plans from .planning/workstreams/)
    4. Effectiveness ranking  (top tools by task_type from EffectivenessStore)

    Token budget is split across sources. Budget from unavailable sources is
    redistributed proportionally to sources that produced content (D-14).
    """

    requires = ["memory_store", "skill_loader", "workspace"]

    def __init__(
        self,
        memory_store=None,
        skill_loader=None,
        workspace="",
        effectiveness_store=None,
        **kwargs,
    ):
        self._memory_store = memory_store
        self._skill_loader = skill_loader
        self._workspace = workspace
        self._effectiveness_store = effectiveness_store
        self._assembler = ContextAssemblerTool(
            memory_store=memory_store,
            skill_loader=skill_loader,
            workspace=workspace,
        )

    @property
    def name(self) -> str:
        return "unified_context"

    @property
    def description(self) -> str:
        return (
            "Assemble unified project context from memory, code symbols, GSD workstream "
            "state, and effectiveness-ranked tools. Extends the base context tool with "
            "jcodemunch code search, active workstream awareness, and tool effectiveness "
            "ranking."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "What you're working on",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "global", "files"],
                    "description": "Search scope: project (default), global, or files",
                },
                "depth": {
                    "type": "string",
                    "enum": ["quick", "deep"],
                    "description": "quick (default) or deep search",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max tokens in returned context (default: 4000)",
                },
                "task_type": {
                    "type": "string",
                    "description": (
                        "Override task type for effectiveness ranking (e.g., 'coding', 'debugging')"
                    ),
                },
            },
            "required": ["topic"],
        }

    async def execute(
        self,
        topic: str = "",
        scope: str = "project",
        depth: str = "quick",
        max_tokens: int = 4000,
        task_type: str = "",
        **kwargs,
    ) -> ToolResult:
        if not topic:
            return ToolResult(output="", error="topic is required", success=False)

        # Infer task type when not explicitly provided
        inferred_type = task_type or _infer_task_type(topic)
        keywords = _extract_keywords(topic)

        # Per-source token budgets
        budgets = {
            "memory": int(max_tokens * _UCT_BUDGET_MEMORY),
            "code": int(max_tokens * _UCT_BUDGET_CODE),
            "gsd": int(max_tokens * _UCT_BUDGET_GSD),
            "git": int(max_tokens * _UCT_BUDGET_GIT),
            "skills": int(max_tokens * _UCT_BUDGET_SKILLS),
            "effectiveness": int(max_tokens * _UCT_BUDGET_EFFECTIVENESS),
        }

        # Only fetch code symbols for code-related task types (or unknown)
        fetch_code = inferred_type in _CODE_TASK_TYPES or not inferred_type

        # Helper coroutine that resolves to None immediately (used when code skipped)
        async def _noop():
            return None

        # Gather all sources concurrently
        results = await asyncio.gather(
            self._assembler.execute(
                topic=topic, scope=scope, depth=depth, max_tokens=max_tokens, **kwargs
            ),
            self._fetch_code_symbols(topic, budgets["code"]) if fetch_code else _noop(),
            self._fetch_gsd_state(keywords, budgets["gsd"]),
            self._fetch_effectiveness(inferred_type, budgets["effectiveness"]),
            return_exceptions=True,
        )

        # Extract base assembler output
        base_result = results[0]
        if isinstance(base_result, Exception):
            logger.warning("Base assembler failed: %s", base_result)
            base_output = ""
        elif isinstance(base_result, ToolResult):
            base_output = base_result.output if base_result.success else ""
        else:
            base_output = str(base_result) if base_result else ""

        # Process additional source results (code, gsd, effectiveness)
        additional_sources = []
        additional_results = results[1:]  # code, gsd, effectiveness
        for i, res in enumerate(additional_results):
            if isinstance(res, Exception):
                logger.debug("Additional source %d failed: %s", i, res)
                additional_sources.append(None)
            else:
                additional_sources.append(res)

        # Budget redistribution (D-14): share unused budget proportionally
        unavailable_budget = 0
        available_indices = []
        for i, section in enumerate(additional_sources):
            if section is None:
                budgets_keys = ["code", "gsd", "effectiveness"]
                unavailable_budget += budgets[budgets_keys[i]]
            else:
                available_indices.append(i)

        if unavailable_budget > 0 and available_indices:
            per_source_extra = unavailable_budget // len(available_indices)
            budgets_keys = ["code", "gsd", "effectiveness"]
            for i in available_indices:
                key = budgets_keys[i]
                new_budget = budgets[key] + per_source_extra
                # Re-truncate the section to the expanded budget
                section = additional_sources[i]
                if section:
                    additional_sources[i] = _truncate_to_budget(section, new_budget)

        # Assemble final output
        sections = [s for s in additional_sources if s]
        extra = "\n\n".join(sections)

        if base_output and extra:
            full_output = base_output + "\n\n" + extra
        elif base_output:
            full_output = base_output
        elif extra:
            full_output = extra
        else:
            full_output = f"No relevant context found for: {topic}"

        full_output = _truncate_to_budget(full_output, max_tokens)
        token_est = _estimate_tokens(full_output)
        section_count = (1 if base_output else 0) + len(sections)
        footer = f"\n\n---\n*{section_count} context sections, ~{token_est} tokens (unified)*"
        full_output += footer

        return ToolResult(output=full_output, success=True)

    # ------------------------------------------------------------------
    # Source: jcodemunch code symbols
    # ------------------------------------------------------------------

    async def _fetch_code_symbols(self, query: str, max_tokens: int) -> str | None:
        """Fetch code symbols from jcodemunch via per-call MCPConnection.

        Uses 3-second connect timeout and 5-second per-call timeout.
        Returns formatted section string or None on any failure.
        """
        config = {"command": "uvx", "args": ["jcodemunch-mcp"]}
        conn = MCPConnection("jcodemunch", config)
        try:
            await asyncio.wait_for(conn.connect(), timeout=3.0)

            # Search symbols
            symbols_result = await asyncio.wait_for(
                conn.call_tool("search_symbols", {"query": query, "repo": "local/agent42"}),
                timeout=5.0,
            )

            seen_hashes: set[str] = set()
            parts = []

            if symbols_result:
                h = hashlib.sha256(symbols_result[:200].encode()).hexdigest()[:16]
                seen_hashes.add(h)
                parts.append(symbols_result)

            # Also try text search for broader coverage
            try:
                text_result = await asyncio.wait_for(
                    conn.call_tool("search_text", {"query": query, "repo": "local/agent42"}),
                    timeout=5.0,
                )
                if text_result:
                    h = hashlib.sha256(text_result[:200].encode()).hexdigest()[:16]
                    if h not in seen_hashes:
                        parts.append(text_result)
            except Exception:
                pass  # text search is best-effort

            if not parts:
                return None

            combined = "\n\n".join(parts)
            return _truncate_to_budget(f"## Code Symbols\n\n{combined}", max_tokens)

        except Exception as e:
            logger.debug("jcodemunch fetch failed (non-critical): %s", e)
            return None
        finally:
            try:
                await conn.disconnect()
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Source: GSD workstream state
    # ------------------------------------------------------------------

    async def _fetch_gsd_state(self, keywords: list[str], max_tokens: int) -> str | None:
        """Read active GSD workstream STATE.md files and return relevant context.

        Scans .planning/workstreams/*/STATE.md for non-Complete workstreams.
        Picks the most recently updated active workstream. Includes GSD context
        only if the topic keywords overlap with the workstream's current state.

        Returns formatted section or None if no match.
        """
        workspace = Path(self._workspace) if self._workspace else Path(".")
        state_files = list(workspace.glob(".planning/workstreams/*/STATE.md"))
        if not state_files:
            return None

        # Collect active (non-complete) workstreams
        active_workstreams = []
        for state_path in state_files:
            try:
                async with aiofiles.open(state_path, encoding="utf-8") as f:
                    content = await f.read()
            except Exception as e:
                logger.debug("Could not read STATE.md at %s: %s", state_path, e)
                continue

            # Parse YAML frontmatter
            frontmatter = {}
            if content.startswith("---"):
                try:
                    end = content.index("---", 3)
                    fm_text = content[3:end].strip()
                    frontmatter = yaml.safe_load(fm_text) or {}
                except (ValueError, yaml.YAMLError):
                    pass

            status = str(frontmatter.get("status", "")).strip()
            if status.lower() == "complete":
                continue

            stopped_at = str(frontmatter.get("stopped_at", ""))
            last_updated = str(frontmatter.get("last_updated", ""))
            ws_name = state_path.parent.name

            active_workstreams.append(
                {
                    "path": state_path,
                    "status": status,
                    "stopped_at": stopped_at,
                    "last_updated": last_updated,
                    "ws_name": ws_name,
                    "content": content,
                }
            )

        if not active_workstreams:
            return None

        # Pick most recently updated
        def _sort_key(ws):
            return ws["last_updated"] or ""

        active_workstreams.sort(key=_sort_key, reverse=True)
        best = active_workstreams[0]

        # Check keyword relevance — overlap with stopped_at + ws_name
        combined_text = (best["stopped_at"] + " " + best["ws_name"]).lower()
        overlap = sum(1 for kw in keywords if kw in combined_text)
        if overlap < 1:
            return None

        # Format the GSD context section
        status_line = best["status"]
        stopped_at_line = best["stopped_at"]

        # Try to read ROADMAP.md for current phase goal
        roadmap_snippet = ""
        roadmap_path = best["path"].parent / "ROADMAP.md"
        if roadmap_path.exists():
            try:
                async with aiofiles.open(roadmap_path, encoding="utf-8") as f:
                    roadmap_content = await f.read()
                # Extract first meaningful paragraph (up to 200 chars)
                for line in roadmap_content.split("\n"):
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#") and not stripped.startswith("---"):
                        roadmap_snippet = stripped[:200]
                        break
            except Exception:
                pass

        section_parts = [
            "## GSD Workstream\n",
            f"**Status:** {status_line}",
            f"**Current:** {stopped_at_line}",
        ]
        if roadmap_snippet:
            section_parts.append(f"\n{roadmap_snippet}")

        section = "\n".join(section_parts)
        return _truncate_to_budget(section, max_tokens)

    # ------------------------------------------------------------------
    # Source: effectiveness ranking
    # ------------------------------------------------------------------

    async def _fetch_effectiveness(self, task_type: str, max_tokens: int) -> str | None:
        """Fetch top tools for the given task_type from EffectivenessStore.

        Returns formatted section or None if no store, no task_type, or no data.
        """
        if not self._effectiveness_store or not task_type:
            return None
        try:
            recs = await self._effectiveness_store.get_recommendations(task_type=task_type, top_k=5)
            if not recs:
                return None

            lines = []
            for rec in recs:
                tool_name = rec.get("tool_name", "?")
                success_rate = rec.get("success_rate", 0.0)
                invocations = rec.get("invocations", 0)
                avg_ms = rec.get("avg_duration_ms", 0.0)
                rate_pct = int(success_rate * 100)
                lines.append(
                    f"- **{tool_name}**: {rate_pct}% success on {task_type} tasks "
                    f"({invocations} calls, avg {avg_ms:.0f}ms)"
                )

            content = "\n".join(lines)
            return _truncate_to_budget(
                f"## Effective Tools for {task_type}\n\n{content}", max_tokens
            )
        except Exception as e:
            logger.debug("Effectiveness fetch failed (non-critical): %s", e)
            return None

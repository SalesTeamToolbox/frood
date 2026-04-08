"""
Context Assembler — smart project context retrieval for Claude Code.

Replaces the old RLM system. When Claude is working on a topic, this tool
assembles relevant context from multiple sources:

1. Semantic memory (Qdrant) — past experiences, pitfalls, solutions
2. CLAUDE.md / MEMORY.md — project instructions, known issues
3. Git history — recent changes to relevant files
4. Skills — relevant skill content for the current task type

Returns a deduplicated, token-budgeted context bundle.
"""

import asyncio
import hashlib
import logging
import re
from pathlib import Path

from tools.base import Tool, ToolResult

logger = logging.getLogger("frood.tools.context_assembler")

# Budget allocation (fraction of max_tokens per source)
_BUDGET_MEMORY = 0.35
_BUDGET_DOCS = 0.25
_BUDGET_GIT = 0.20
_BUDGET_SKILLS = 0.20

_STOP_WORDS = frozenset(
    ["the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "have", "has", "had", "do", "does", "did", "will", "would", "could", "should", "may", "might", "can", "shall", "must", "need", "let", "lets", "please", "want", "like", "just", "make", "get", "use", "this", "that", "these", "those", "its", "me", "my", "we", "our", "you", "your", "they", "them", "their", "and", "or", "but", "if", "then", "else", "when", "where", "how", "what", "which", "who", "not", "no", "so", "too", "very", "also", "about", "to", "for", "with", "from", "at", "by", "on", "in", "of", "up", "out", "off", "all", "any", "some", "now", "here", "there", "yes", "ok", "done"]
)


def _extract_keywords(text):
    words = re.findall(r"[a-zA-Z_][a-zA-Z0-9_]*", text.lower())
    return list(set(w for w in words if len(w) >= 3 and w not in _STOP_WORDS))


def _estimate_tokens(text):
    return len(text) // 4


def _truncate_to_budget(text, max_tokens):
    max_chars = max_tokens * 4
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... (truncated to fit context budget)"


class ContextAssemblerTool(Tool):
    """Assemble smart project context from multiple sources."""

    requires = ["memory_store", "skill_loader", "workspace"]

    def __init__(self, memory_store=None, skill_loader=None, workspace="", **kwargs):
        self._memory_store = memory_store
        self._skill_loader = skill_loader
        self._workspace = workspace

    @property
    def name(self):
        return "context"

    @property
    def description(self):
        return (
            "Assemble relevant project context for a topic. Searches semantic memory, "
            "project docs, git history, and skills to build a focused context bundle. "
            "Use this when starting work on a feature, debugging an issue, or needing "
            "background on a codebase area."
        )

    @property
    def parameters(self):
        return {
            "type": "object",
            "properties": {
                "topic": {
                    "type": "string",
                    "description": "What you're working on (e.g., 'authentication flow', 'memory system')",
                },
                "scope": {
                    "type": "string",
                    "enum": ["project", "global", "files"],
                    "description": "Search scope: project (default), global, or files (git+code only)",
                },
                "depth": {
                    "type": "string",
                    "enum": ["quick", "deep"],
                    "description": "quick (default, top results) or deep (exhaustive search)",
                },
                "max_tokens": {
                    "type": "integer",
                    "description": "Max tokens in returned context (default: 4000)",
                },
            },
            "required": ["topic"],
        }

    async def execute(self, topic="", scope="project", depth="quick", max_tokens=4000, **kwargs):
        if not topic:
            return ToolResult(output="", error="topic is required", success=False)

        keywords = _extract_keywords(topic)
        top_k = 10 if depth == "deep" else 5
        sections = []
        seen = set()

        # Source 1: Semantic Memory
        await self._search_memory(topic, top_k, seen, sections, max_tokens)

        # Source 2: Project Docs
        self._search_docs(keywords, sections, seen, max_tokens)

        # Source 3: Git History
        if scope != "global":
            await self._search_git(keywords, sections, seen, max_tokens)

        # Source 4: Skills
        self._search_skills(keywords, sections, seen, max_tokens)

        if not sections:
            return ToolResult(output=f"No relevant context found for: {topic}", success=True)

        header = f"# Context: {topic}\n\n"
        body = "\n\n".join(sections)
        output = _truncate_to_budget(header + body, max_tokens)
        token_est = _estimate_tokens(output)
        footer = f"\n\n---\n*{len(sections)} context sections, ~{token_est} tokens*"

        return ToolResult(output=output + footer, success=True)

    async def _search_memory(self, topic, top_k, seen, sections, max_tokens):
        if not self._memory_store:
            return
        try:
            results = await self._memory_store.semantic_search(query=topic, top_k=top_k)
            if not results:
                return
            lines = []
            for r in results:
                if r.get("score", 0) < 0.20:
                    continue
                text = r.get("text", "").strip()
                section = r.get("section", "")
                h = hashlib.sha256(text[:200].encode()).hexdigest()[:16]
                if h in seen:
                    continue
                seen.add(h)
                label = f"[{section}]" if section else ""
                lines.append(f"- {label} {text[:300]}")
            if lines:
                content = "\n".join(lines)
                budgeted = _truncate_to_budget(content, int(max_tokens * _BUDGET_MEMORY))
                sections.append(f"## Relevant Memories\n\n{budgeted}")
        except Exception as e:
            logger.debug(f"Memory search failed: {e}")

    def _search_docs(self, keywords, sections, seen, max_tokens):
        workspace = Path(self._workspace) if self._workspace else Path(".")
        doc_files = [
            workspace / "CLAUDE.md",
            workspace / ".frood" / "memory" / "MEMORY.md",
        ]
        budget_per_doc = int(max_tokens * _BUDGET_DOCS) // max(len(doc_files), 1)

        for doc_path in doc_files:
            if not doc_path.exists():
                continue
            try:
                content = doc_path.read_text(encoding="utf-8")
            except Exception:
                continue

            current_section = ""
            current_lines = []
            matches = []

            for line in content.split("\n"):
                if line.startswith("## "):
                    if current_lines:
                        body = "\n".join(current_lines).strip()
                        score = sum(1 for kw in keywords if kw in body.lower())
                        if score >= 2:
                            matches.append((score, current_section, body))
                    current_section = line.lstrip("#").strip()
                    current_lines = [line]
                else:
                    current_lines.append(line)

            if current_lines:
                body = "\n".join(current_lines).strip()
                score = sum(1 for kw in keywords if kw in body.lower())
                if score >= 2:
                    matches.append((score, current_section, body))

            matches.sort(key=lambda x: x[0], reverse=True)
            for score, section_name, body in matches[:3]:
                h = hashlib.sha256(body[:200].encode()).hexdigest()[:16]
                if h in seen:
                    continue
                seen.add(h)
                label = f"{doc_path.name}: {section_name}" if section_name else doc_path.name
                budgeted = _truncate_to_budget(body, budget_per_doc)
                sections.append(f"## {label}\n\n{budgeted}")

    async def _search_git(self, keywords, sections, seen, max_tokens):
        workspace = self._workspace or "."
        try:
            proc = await asyncio.create_subprocess_exec(
                "git",
                "log",
                "--oneline",
                "--name-only",
                "-20",
                cwd=workspace,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            stdout, _ = await asyncio.wait_for(proc.communicate(), timeout=10)
            log_output = stdout.decode(errors="replace")
        except Exception:
            return

        if not log_output.strip():
            return

        commits = log_output.strip().split("\n\n")
        relevant = []
        for block in commits[:20]:
            if not block.strip():
                continue
            score = sum(1 for kw in keywords if kw in block.lower())
            if score >= 1:
                relevant.append((score, block.strip()))

        if not relevant:
            return

        relevant.sort(key=lambda x: x[0], reverse=True)
        content = "\n\n".join(block for _, block in relevant[:5])

        h = hashlib.sha256(content[:200].encode()).hexdigest()[:16]
        if h in seen:
            return
        seen.add(h)

        budgeted = _truncate_to_budget(content, int(max_tokens * _BUDGET_GIT))
        sections.append(f"## Recent Git Activity\n\n{budgeted}")

    def _search_skills(self, keywords, sections, seen, max_tokens):
        if not self._skill_loader:
            return
        try:
            all_skills = self._skill_loader.all_skills()
        except Exception:
            return

        scored = []
        for skill in all_skills:
            skill_text = f"{skill.name} {skill.description}".lower()
            score = sum(1 for kw in keywords if kw in skill_text)
            if score >= 1:
                scored.append((score, skill))

        if not scored:
            return

        scored.sort(key=lambda x: x[0], reverse=True)
        skill_lines = []
        for _, skill in scored[:3]:
            desc = skill.description[:150] if skill.description else ""
            skill_lines.append(f"- **{skill.name}**: {desc}")

        if skill_lines:
            content = "\n".join(skill_lines)
            h = hashlib.sha256(content[:200].encode()).hexdigest()[:16]
            if h in seen:
                return
            seen.add(h)
            budgeted = _truncate_to_budget(content, int(max_tokens * _BUDGET_SKILLS))
            sections.append(f"## Relevant Skills\n\n{budgeted}")

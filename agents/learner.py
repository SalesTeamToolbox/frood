"""
Self-learning agent — learns from task outcomes to improve over time.

Three learning mechanisms:
1. Post-task reflection: after every task, analyze what worked/didn't and
   update persistent memory with lessons learned.
2. Failure analysis: when tasks fail, extract the root cause and record
   a "lesson learned" so the same mistake isn't repeated.
3. Skill creation: when the agent recognizes a repeating pattern, it can
   create a workspace skill so future tasks of that type get better prompts.

All learning is written to persistent memory (MEMORY.md / HISTORY.md) and
optionally to workspace skills (skills/workspace/).
"""

import logging
from pathlib import Path

from agents.model_router import ModelRouter
from memory.store import MemoryStore

logger = logging.getLogger("agent42.learner")

REFLECTION_PROMPT = """\
You just completed a task. Analyze the outcome and extract lessons.

Task: {title}
Type: {task_type}
Iterations: {iterations}
Max allowed: {max_iterations}
Outcome: {outcome}

{iteration_summary}

{failure_details}

{tool_usage_section}

Respond with a structured analysis:

## What Worked
- (list specific techniques, approaches, or patterns that were effective)

## What Didn't Work
- (list approaches that failed or needed revision, if any)

## Tool Effectiveness
- (evaluate which tools were most/least useful for this task type)
- (note any tools that failed or were used incorrectly)
- (suggest tool preferences for future tasks of this type)

## Lesson Learned
One concise sentence capturing the key takeaway for future tasks of this type.

## Memory Update
If there's a reusable pattern or preference to remember, write it as a single
bullet point starting with the section name in brackets, e.g.:
[Project Conventions] - This repo uses pytest with --strict-markers flag
[Common Patterns] - API endpoints follow /api/v1/resource_name pattern
[Tool Preferences] - For content tasks, use content_analyzer before scoring_tool
[Tool Preferences] - For marketing tasks, always apply persona tool first

If nothing worth remembering, write: NONE
"""

SKILL_CREATION_PROMPT = """\
Based on repeated patterns in this agent's task history, decide whether a new
skill template would help future tasks.

Recent task history:
{history_excerpt}

Current skills:
{existing_skills}

If a new skill would be useful, respond with EXACTLY this format:

CREATE_SKILL
name: skill-name-here
description: One-line description
task_types: [type1, type2]
---
(skill instructions in markdown)

If no new skill is needed, respond with: NO_SKILL_NEEDED
"""


class Learner:
    """Post-task learning loop that improves the agent over time."""

    def __init__(
        self,
        router: ModelRouter,
        memory_store: MemoryStore,
        skills_dir: Path | None = None,
        reflection_model: str = "or-free-deepseek-chat",
        model_evaluator=None,
    ):
        self.router = router
        self.memory = memory_store
        self.skills_dir = skills_dir
        self.reflection_model = reflection_model
        self._model_evaluator = model_evaluator

    async def reflect_on_task(
        self,
        title: str,
        task_type: str,
        iterations: int,
        max_iterations: int,
        iteration_summary: str,
        succeeded: bool,
        error: str = "",
        tool_calls: list[dict] | None = None,
        model_key: str = "",
    ) -> dict:
        """Run post-task reflection and update memory with lessons learned.

        Args:
            tool_calls: List of tool call records from iteration history.
                Each dict has: name, success (bool), arguments (optional).
            model_key: The primary model key used for this task (for outcome tracking).

        Returns a dict with the reflection results for logging/display.
        """
        outcome = "SUCCESS" if succeeded else f"FAILED: {error}"
        failure_details = ""
        if not succeeded:
            failure_details = (
                f"Error details:\n{error}\n\n"
                "Focus your analysis on WHY this failed and how to prevent it."
            )

        # Build tool usage section for the reflection prompt
        tool_usage_section = self._build_tool_usage_section(tool_calls or [], task_type)

        prompt = REFLECTION_PROMPT.format(
            title=title,
            task_type=task_type,
            iterations=iterations,
            max_iterations=max_iterations,
            outcome=outcome,
            iteration_summary=iteration_summary,
            failure_details=failure_details,
            tool_usage_section=tool_usage_section,
        )

        try:
            reflection = await self.router.complete(
                self.reflection_model,
                [{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.warning(f"Reflection failed (non-critical): {e}")
            return {"skipped": True, "reason": str(e)}

        # Parse and apply memory updates
        memory_updates = self._parse_memory_updates(reflection)
        for section, content in memory_updates:
            self.memory.append_to_section(section, content)
            logger.info(f"Memory updated [{section}]: {content[:80]}")

        # Extract the lesson learned
        lesson = self._extract_lesson(reflection)

        # Log the reflection event (with semantic indexing)
        await self.memory.log_event_semantic(
            "reflection",
            f"Post-task reflection for '{title}' ({task_type})",
            f"Outcome: {outcome}\nLesson: {lesson}\nMemory updates: {len(memory_updates)}",
        )

        # Record model outcome for dynamic routing evaluation
        if self._model_evaluator and model_key:
            try:
                self._model_evaluator.record_outcome(
                    model_key=model_key,
                    task_type=task_type,
                    success=succeeded,
                    iterations=iterations,
                    max_iterations=max_iterations,
                )
            except Exception as e:
                logger.debug("Model outcome recording failed (non-critical): %s", e)

        return {
            "reflection": reflection,
            "lesson": lesson,
            "memory_updates": len(memory_updates),
            "succeeded": succeeded,
        }

    async def check_for_skill_creation(
        self,
        existing_skill_names: list[str],
    ) -> dict | None:
        """Analyze task history and create a new skill if a pattern is detected.

        Returns skill metadata dict if created, None otherwise.
        """
        if not self.skills_dir:
            return None

        # Get recent history for pattern detection
        history = self.memory.read_history()
        history_lines = history.strip().split("\n")
        # Use last 100 lines for pattern analysis
        history_excerpt = "\n".join(history_lines[-100:])

        prompt = SKILL_CREATION_PROMPT.format(
            history_excerpt=history_excerpt,
            existing_skills=", ".join(existing_skill_names) if existing_skill_names else "(none)",
        )

        try:
            response = await self.router.complete(
                self.reflection_model,
                [{"role": "user", "content": prompt}],
            )
        except Exception as e:
            logger.warning(f"Skill creation check failed (non-critical): {e}")
            return None

        if "CREATE_SKILL" not in response:
            return None

        return await self._create_skill_from_response(response)

    async def record_reviewer_feedback(
        self,
        task_id: str,
        task_title: str,
        feedback: str,
        approved: bool,
    ):
        """Record human reviewer feedback into memory for future learning.

        Called when a human approves/rejects the REVIEW.md output.
        """
        outcome = "APPROVED" if approved else "REJECTED"
        await self.memory.log_event_semantic(
            "reviewer_feedback",
            f"Human reviewer {outcome} task '{task_title}'",
            f"Task ID: {task_id}\nFeedback: {feedback}",
        )

        # If rejected, add the feedback to memory so the agent avoids
        # the same mistake in future tasks
        if not approved and feedback.strip():
            self.memory.append_to_section(
                "Reviewer Feedback",
                f"({task_title}) {feedback.strip()[:200]}",
            )
            logger.info(f"Reviewer rejection recorded for '{task_title}'")

    def get_tool_recommendations(self, task_type: str) -> str:
        """Read memory for tool preference entries matching a task type.

        Returns guidance text to inject into the agent's system prompt.
        """
        memory_content = self.memory.read_memory()
        if not memory_content:
            return ""

        recommendations = []
        for line in memory_content.split("\n"):
            stripped = line.strip().lstrip("- ")
            # Look for [Tool Preferences] entries
            if stripped.startswith("[Tool Preferences]"):
                content = stripped[len("[Tool Preferences]") :].strip().lstrip("- ").strip()
                if content:
                    # Check if the recommendation is relevant to this task type
                    lower_content = content.lower()
                    if task_type.lower() in lower_content or "all task" in lower_content:
                        recommendations.append(f"- {content}")
                    elif not any(
                        t.value in lower_content
                        for t in __import__("core.task_queue", fromlist=["TaskType"]).TaskType
                    ):
                        # Generic recommendation (not task-type-specific)
                        recommendations.append(f"- {content}")

        if not recommendations:
            return ""

        return "\n## Tool Usage Recommendations (from prior experience)\n" + "\n".join(
            recommendations
        )

    @staticmethod
    def _build_tool_usage_section(tool_calls: list[dict], task_type: str) -> str:
        """Build a tool usage summary for the reflection prompt."""
        if not tool_calls:
            return "Tool usage: No tools were called during this task."

        # Aggregate tool stats
        tool_stats: dict[str, dict] = {}
        for tc in tool_calls:
            name = tc.get("name", "unknown")
            success = tc.get("success", True)
            if name not in tool_stats:
                tool_stats[name] = {"total": 0, "success": 0, "fail": 0}
            tool_stats[name]["total"] += 1
            if success:
                tool_stats[name]["success"] += 1
            else:
                tool_stats[name]["fail"] += 1

        lines = [
            f"Tool usage summary (task_type={task_type}):",
            f"Total tool calls: {len(tool_calls)}",
            "",
        ]
        for name, stats in sorted(tool_stats.items()):
            rate = (stats["success"] / stats["total"] * 100) if stats["total"] > 0 else 0
            lines.append(
                f"- {name}: {stats['total']} calls "
                f"({stats['success']} success, {stats['fail']} fail, "
                f"{rate:.0f}% success rate)"
            )

        return "\n".join(lines)

    # -- Internal helpers -------------------------------------------------------

    def _parse_memory_updates(self, reflection: str) -> list[tuple[str, str]]:
        """Extract [Section] - content pairs from the reflection output."""
        updates = []
        for line in reflection.split("\n"):
            line = line.strip().lstrip("- ")
            if line.startswith("[") and "] " in line:
                bracket_end = line.index("]")
                section = line[1:bracket_end].strip()
                content = line[bracket_end + 1 :].strip().lstrip("- ").strip()
                if content and section and content.upper() != "NONE":
                    updates.append((section, content))
        return updates

    def _extract_lesson(self, reflection: str) -> str:
        """Extract the 'Lesson Learned' from the reflection output."""
        lines = reflection.split("\n")
        capture = False
        for line in lines:
            if "## Lesson Learned" in line:
                capture = True
                continue
            if capture:
                stripped = line.strip()
                if stripped and not stripped.startswith("#"):
                    return stripped
        return ""

    async def _create_skill_from_response(self, response: str) -> dict | None:
        """Parse CREATE_SKILL response and write the skill file."""
        lines = response.split("\n")
        idx = None
        for i, line in enumerate(lines):
            if line.strip() == "CREATE_SKILL":
                idx = i
                break
        if idx is None:
            return None

        # Parse metadata
        name = ""
        description = ""
        task_types = "[]"
        body_lines = []
        in_body = False

        for line in lines[idx + 1 :]:
            stripped = line.strip()
            if stripped == "---":
                in_body = True
                continue
            if in_body:
                body_lines.append(line)
            elif stripped.startswith("name:"):
                name = stripped[5:].strip()
            elif stripped.startswith("description:"):
                description = stripped[12:].strip()
            elif stripped.startswith("task_types:"):
                task_types = stripped[11:].strip()

        if not name or not body_lines:
            return None

        # Sanitize name for directory
        safe_name = "".join(c if c.isalnum() or c == "-" else "-" for c in name)

        # Write skill
        skill_dir = self.skills_dir / safe_name
        skill_dir.mkdir(parents=True, exist_ok=True)
        skill_path = skill_dir / "SKILL.md"

        frontmatter = (
            f"---\n"
            f"name: {safe_name}\n"
            f"description: {description}\n"
            f"always: false\n"
            f"task_types: {task_types}\n"
            f"---\n\n"
        )
        skill_path.write_text(frontmatter + "\n".join(body_lines))

        await self.memory.log_event_semantic(
            "skill_created",
            f"Agent created new skill: {safe_name}",
            f"Description: {description}\nTask types: {task_types}",
        )

        logger.info(f"New skill created: {skill_dir}")
        return {"name": safe_name, "description": description, "path": str(skill_path)}

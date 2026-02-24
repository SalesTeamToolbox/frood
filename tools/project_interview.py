"""
Project interview tool — structured discovery for project-level work.

Manages the interview lifecycle: start a session, collect batched Q&A
responses, extract structured answers via LLM, generate PROJECT_SPEC.md,
and decompose specs into subtasks.

State is persisted to PROJECT.json in the outputs directory so interviews
survive restarts and can be resumed.
"""

import json
import logging
import time
import uuid
from pathlib import Path

import aiofiles

from core.interview_questions import (
    ANSWER_EXTRACTION_PROMPT,
    ROUND_DISPLAY_NAMES,
    format_question_batch,
    get_questions,
    get_round_sequence,
)
from core.project_spec import ProjectSpecGenerator
from core.task_queue import Task, TaskType
from tools.base import Tool, ToolResult

logger = logging.getLogger("agent42.tools.project_interview")


class ProjectInterviewTool(Tool):
    """Conduct structured project discovery interviews and produce specifications.

    Actions:
        start     — Begin a new interview session
        respond   — Process user's response to a question batch
        status    — Get interview progress
        get_spec  — Retrieve the generated PROJECT_SPEC.md
        update_spec — Update a section of the spec (for scope changes)
        approve   — Mark the spec as approved and trigger subtask decomposition
        list      — List all interview sessions
    """

    def __init__(
        self, workspace_path: str = ".", router=None, outputs_dir: str = "", task_queue=None
    ):
        self._workspace = workspace_path
        self._router = router
        self._outputs_dir = outputs_dir or ".agent42/outputs"
        self._spec_generator = ProjectSpecGenerator(router=router)
        self._task_queue = task_queue

    @property
    def name(self) -> str:
        return "project_interview"

    @property
    def description(self) -> str:
        return (
            "Conduct structured project discovery interviews. Start an interview "
            "session for a new project or feature, collect requirements through "
            "batched Q&A rounds, generate a PROJECT_SPEC.md specification, and "
            "decompose it into subtasks. Actions: start, respond, status, get_spec, "
            "update_spec, approve, list."
        )

    @property
    def parameters(self) -> dict:
        return {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "start",
                        "respond",
                        "status",
                        "get_spec",
                        "update_spec",
                        "approve",
                        "list",
                    ],
                    "description": "Interview action to perform",
                },
                "project_id": {
                    "type": "string",
                    "description": "Project interview session ID (required for all actions except start and list)",
                    "default": "",
                },
                "task_id": {
                    "type": "string",
                    "description": "Parent task ID (required for start)",
                    "default": "",
                },
                "description": {
                    "type": "string",
                    "description": "Project/feature description (required for start)",
                    "default": "",
                },
                "project_type": {
                    "type": "string",
                    "enum": ["new_project", "new_feature"],
                    "description": "Type of work (required for start)",
                    "default": "new_project",
                },
                "complexity": {
                    "type": "string",
                    "enum": ["simple", "moderate", "complex"],
                    "description": "Assessed complexity (for start)",
                    "default": "moderate",
                },
                "response": {
                    "type": "string",
                    "description": "User's response to the current question batch (for respond)",
                    "default": "",
                },
                "section": {
                    "type": "string",
                    "description": "Spec section to update (for update_spec)",
                    "default": "",
                },
                "content": {
                    "type": "string",
                    "description": "New content for the section (for update_spec)",
                    "default": "",
                },
                "repo_url": {
                    "type": "string",
                    "description": "Repository URL or path (optional, for start)",
                    "default": "",
                },
                "pm_project_id": {
                    "type": "string",
                    "description": "ProjectManager project ID to link subtasks to (optional, for start)",
                    "default": "",
                },
            },
            "required": ["action"],
        }

    async def execute(
        self,
        action: str = "",
        project_id: str = "",
        task_id: str = "",
        description: str = "",
        project_type: str = "new_project",
        complexity: str = "moderate",
        response: str = "",
        section: str = "",
        content: str = "",
        repo_url: str = "",
        pm_project_id: str = "",
        **kwargs,
    ) -> ToolResult:
        if not action:
            return ToolResult(error="Action is required", success=False)

        if action == "start":
            return await self._start(
                task_id, description, project_type, complexity, repo_url, pm_project_id
            )
        elif action == "respond":
            return await self._respond(project_id, response)
        elif action == "status":
            return await self._status(project_id)
        elif action == "get_spec":
            return await self._get_spec(project_id)
        elif action == "update_spec":
            return await self._update_spec(project_id, section, content)
        elif action == "approve":
            return await self._approve(project_id)
        elif action == "list":
            return await self._list()
        else:
            return ToolResult(error=f"Unknown action: {action}", success=False)

    # ── Action: start ────────────────────────────────────────────────────

    async def _start(
        self,
        task_id: str,
        description: str,
        project_type: str,
        complexity: str,
        repo_url: str,
        pm_project_id: str = "",
    ) -> ToolResult:
        """Start a new interview session."""
        if not description:
            return ToolResult(error="Description is required to start an interview", success=False)

        if project_type not in ("new_project", "new_feature"):
            project_type = "new_project"
        if complexity not in ("simple", "moderate", "complex"):
            complexity = "moderate"

        project_id = f"proj_{uuid.uuid4().hex[:8]}"
        round_sequence = get_round_sequence(complexity)

        # Get first round questions
        first_theme = round_sequence[0]
        questions = get_questions(project_type, first_theme)

        project_data = {
            "id": project_id,
            "parent_task_id": task_id,
            "project_type": project_type,
            "status": "discovery",
            "complexity": complexity,
            "description": description,
            "created_at": time.time(),
            "updated_at": time.time(),
            "round_sequence": round_sequence,
            "current_round_index": 0,
            "rounds": [
                {
                    "theme": first_theme,
                    "display_name": ROUND_DISPLAY_NAMES.get(first_theme, first_theme),
                    "questions": questions,
                    "raw_response": "",
                    "extracted_answers": {},
                    "key_insights": [],
                    "asked_at": time.time(),
                    "answered_at": None,
                }
            ],
            "spec_version": 0,
            "repo_url": repo_url,
            "existing_codebase_summary": "",
            "pm_project_id": pm_project_id,
        }

        # Persist
        await self._save_project(project_id, project_data)

        # Format the first batch of questions
        question_text = format_question_batch(questions, first_theme)
        type_label = "new project" if project_type == "new_project" else "new feature"
        total_rounds = len(round_sequence)

        return ToolResult(
            output=(
                f"## Project Interview Started\n\n"
                f"**Project ID:** `{project_id}`\n"
                f"**Type:** {type_label} | **Complexity:** {complexity}\n"
                f"**Rounds:** {total_rounds} themed question batches\n\n"
                f"I'd like to understand your project better before we start building. "
                f"Let's walk through a few quick rounds of questions.\n\n"
                f"### Round 1 of {total_rounds}: {ROUND_DISPLAY_NAMES.get(first_theme, first_theme)}\n\n"
                f"{question_text}\n\n"
                f"*Please respond naturally — you don't need to answer each question "
                f"separately. Just share what you know.*"
            ),
            success=True,
        )

    # ── Action: respond ──────────────────────────────────────────────────

    async def _respond(self, project_id: str, response: str) -> ToolResult:
        """Process a user's response to the current question batch."""
        if not project_id:
            return ToolResult(error="project_id is required", success=False)
        if not response:
            return ToolResult(error="response is required", success=False)

        project_data = await self._load_project(project_id)
        if not project_data:
            return ToolResult(error=f"Project '{project_id}' not found", success=False)

        if project_data["status"] != "discovery":
            return ToolResult(
                error=f"Interview is in '{project_data['status']}' state, not accepting responses",
                success=False,
            )

        current_idx = project_data["current_round_index"]
        current_round = project_data["rounds"][current_idx]

        # Store raw response
        current_round["raw_response"] = response
        current_round["answered_at"] = time.time()

        # Extract structured answers via LLM
        extracted = await self._extract_answers(
            current_round["theme"],
            current_round["questions"],
            response,
        )
        current_round["extracted_answers"] = extracted.get("answers", {})
        current_round["key_insights"] = extracted.get("key_insights", [])

        # Check if there are follow-up questions needed
        follow_ups = extracted.get("follow_up_questions", [])

        # Advance to next round
        round_sequence = project_data["round_sequence"]
        next_idx = current_idx + 1

        if next_idx < len(round_sequence):
            # Prepare next round
            next_theme = round_sequence[next_idx]
            questions = get_questions(project_data["project_type"], next_theme)

            # Add follow-up questions from the current round if any
            if follow_ups:
                questions = follow_ups + questions

            project_data["rounds"].append(
                {
                    "theme": next_theme,
                    "display_name": ROUND_DISPLAY_NAMES.get(next_theme, next_theme),
                    "questions": questions,
                    "raw_response": "",
                    "extracted_answers": {},
                    "key_insights": [],
                    "asked_at": time.time(),
                    "answered_at": None,
                }
            )
            project_data["current_round_index"] = next_idx
            project_data["updated_at"] = time.time()

            await self._save_project(project_id, project_data)

            # Format the next batch
            question_text = format_question_batch(questions, next_theme)
            total_rounds = len(round_sequence)
            display_round = next_idx + 1

            return ToolResult(
                output=(
                    f"**Round {current_idx + 1} recorded.** "
                    f"Key insights captured: {len(current_round['key_insights'])}\n\n"
                    f"### Round {display_round} of {total_rounds}: "
                    f"{ROUND_DISPLAY_NAMES.get(next_theme, next_theme)}\n\n"
                    f"{question_text}\n\n"
                    f"*Please respond naturally.*"
                ),
                success=True,
            )
        else:
            # All rounds complete — transition to drafting
            project_data["status"] = "drafting"
            project_data["updated_at"] = time.time()
            await self._save_project(project_id, project_data)

            # Validate completeness
            completeness = self._spec_generator.validate_completeness(project_data)

            # Generate the spec
            spec_content = await self._spec_generator.generate(project_data)
            spec_path = self._project_dir(project_id) / "PROJECT_SPEC.md"
            async with aiofiles.open(spec_path, "w") as f:
                await f.write(spec_content)

            project_data["status"] = "review"
            project_data["spec_version"] = 1
            project_data["updated_at"] = time.time()
            await self._save_project(project_id, project_data)

            coverage_pct = int(completeness["coverage"] * 100)
            return ToolResult(
                output=(
                    f"**All {len(round_sequence)} interview rounds complete!**\n\n"
                    f"**Coverage:** {coverage_pct}% of questions answered\n"
                    f"**Spec generated:** `PROJECT_SPEC.md` (version 1)\n\n"
                    f"The specification is ready for review. Use `get_spec` to view it, "
                    f"then ask the user to approve it or request changes.\n\n"
                    f"Once approved, use the `approve` action to trigger subtask decomposition."
                ),
                success=True,
            )

    # ── Action: status ───────────────────────────────────────────────────

    async def _status(self, project_id: str) -> ToolResult:
        """Get the current interview status."""
        if not project_id:
            return ToolResult(error="project_id is required", success=False)

        project_data = await self._load_project(project_id)
        if not project_data:
            return ToolResult(error=f"Project '{project_id}' not found", success=False)

        rounds = project_data.get("rounds", [])
        total_rounds = len(project_data.get("round_sequence", []))
        completed_rounds = sum(1 for r in rounds if r.get("answered_at"))
        status = project_data.get("status", "unknown")

        lines = [
            "## Project Interview Status",
            "",
            f"**Project ID:** `{project_id}`",
            f"**Status:** {status}",
            f"**Type:** {project_data.get('project_type', 'unknown')}",
            f"**Complexity:** {project_data.get('complexity', 'unknown')}",
            f"**Rounds completed:** {completed_rounds}/{total_rounds}",
            f"**Spec version:** {project_data.get('spec_version', 0)}",
            "",
        ]

        for i, r in enumerate(rounds):
            answered = "answered" if r.get("answered_at") else "pending"
            insights = len(r.get("key_insights", []))
            lines.append(
                f"  {i + 1}. **{r.get('display_name', r.get('theme', '?'))}** — "
                f"{answered} ({insights} insights)"
            )

        return ToolResult(output="\n".join(lines), success=True)

    # ── Action: get_spec ─────────────────────────────────────────────────

    async def _get_spec(self, project_id: str) -> ToolResult:
        """Retrieve the generated spec."""
        if not project_id:
            return ToolResult(error="project_id is required", success=False)

        spec_path = self._project_dir(project_id) / "PROJECT_SPEC.md"
        if not spec_path.exists():
            return ToolResult(
                error=f"No spec generated yet for project '{project_id}'. Complete the interview first.",
                success=False,
            )

        async with aiofiles.open(spec_path) as f:
            content = await f.read()

        return ToolResult(output=content, success=True)

    # ── Action: update_spec ──────────────────────────────────────────────

    async def _update_spec(self, project_id: str, section: str, content: str) -> ToolResult:
        """Update a specific section of the spec."""
        if not project_id:
            return ToolResult(error="project_id is required", success=False)
        if not section:
            return ToolResult(error="section name is required", success=False)
        if not content:
            return ToolResult(error="content is required", success=False)

        project_data = await self._load_project(project_id)
        if not project_data:
            return ToolResult(error=f"Project '{project_id}' not found", success=False)

        spec_path = self._project_dir(project_id) / "PROJECT_SPEC.md"
        if not spec_path.exists():
            return ToolResult(error="No spec generated yet", success=False)

        async with aiofiles.open(spec_path) as f:
            spec_content = await f.read()

        # Find and replace the section
        # Sections are marked by "## N. Section Name"
        import re

        pattern = rf"(## \d+\. {re.escape(section)}.*?\n)(.*?)(?=\n## \d+\.|---|\Z)"
        match = re.search(pattern, spec_content, re.DOTALL)
        if not match:
            return ToolResult(
                error=f"Section '{section}' not found in spec. Available sections are numbered "
                f"(e.g., 'Overview', 'Scope', 'Requirements', etc.)",
                success=False,
            )

        updated = spec_content[: match.start(2)] + content + "\n" + spec_content[match.end(2) :]

        # Append to change log
        today = time.strftime("%Y-%m-%d")
        change_entry = f"| {today} | Updated {section} | User-requested change |\n"
        if "## Change Log" in updated:
            # Insert before the last row or at the end of the table
            updated = updated.rstrip() + "\n" + change_entry

        async with aiofiles.open(spec_path, "w") as f:
            await f.write(updated)

        # Bump version
        project_data["spec_version"] = project_data.get("spec_version", 1) + 1
        project_data["updated_at"] = time.time()
        await self._save_project(project_id, project_data)

        return ToolResult(
            output=f"Section '{section}' updated. Spec version: {project_data['spec_version']}",
            success=True,
        )

    # ── Action: approve ──────────────────────────────────────────────────

    async def _approve(self, project_id: str) -> ToolResult:
        """Mark spec as approved and generate subtasks."""
        if not project_id:
            return ToolResult(error="project_id is required", success=False)

        project_data = await self._load_project(project_id)
        if not project_data:
            return ToolResult(error=f"Project '{project_id}' not found", success=False)

        if project_data["status"] not in ("review", "drafting"):
            return ToolResult(
                error=f"Project is in '{project_data['status']}' state. "
                f"Must be in 'review' state to approve.",
                success=False,
            )

        # Read the spec
        spec_path = self._project_dir(project_id) / "PROJECT_SPEC.md"
        if not spec_path.exists():
            return ToolResult(error="No spec found to approve", success=False)

        async with aiofiles.open(spec_path) as f:
            spec_content = await f.read()

        # Update spec status to Approved
        spec_content = spec_content.replace("Draft — Awaiting Approval", "Approved")
        async with aiofiles.open(spec_path, "w") as f:
            await f.write(spec_content)

        # Generate subtasks
        subtasks = await self._spec_generator.generate_subtasks(
            spec_content, project_data["project_type"]
        )

        # Transition to executing
        project_data["status"] = "approved"
        project_data["updated_at"] = time.time()
        await self._save_project(project_id, project_data)

        # Save subtasks for reference
        subtasks_path = self._project_dir(project_id) / "subtasks.json"
        async with aiofiles.open(subtasks_path, "w") as f:
            await f.write(json.dumps(subtasks, indent=2))

        # Create Task objects in the queue if task_queue is wired up
        pm_project_id = project_data.get("pm_project_id", "")
        created_task_ids: list[str] = []
        if self._task_queue and pm_project_id:
            for st in subtasks:
                type_str = st.get("task_type", "coding").upper()
                tt = TaskType[type_str] if type_str in TaskType.__members__ else TaskType.CODING
                new_task = Task(
                    title=st.get("title", "Untitled subtask"),
                    description=st.get("description", ""),
                    task_type=tt,
                    project_id=pm_project_id,
                    project_spec_path=str(spec_path),
                )
                await self._task_queue.add(new_task)
                created_task_ids.append(new_task.id)
            logger.info(
                "Created %d subtasks for project %s (interview %s)",
                len(created_task_ids),
                pm_project_id,
                project_id,
            )

        # Format subtask summary
        tasks_note = (
            f"\n**Tasks created in queue:** {len(created_task_ids)}"
            if created_task_ids
            else "\n*Note: Subtasks saved to JSON — add a task_queue to auto-create them.*"
        )
        lines = [
            "## Spec Approved — Subtasks Generated\n",
            f"**Project:** `{project_id}`",
            f"**Subtasks:** {len(subtasks)}",
            tasks_note,
            "",
        ]
        for i, st in enumerate(subtasks):
            deps = st.get("depends_on", [])
            dep_str = f" (depends on: {deps})" if deps else ""
            lines.append(
                f"  {i + 1}. **{st.get('title', 'Untitled')}** "
                f"[{st.get('task_type', 'coding')}]{dep_str}"
            )
            criteria = st.get("acceptance_criteria", [])
            for c in criteria:
                lines.append(f"     - {c}")

        lines.append(
            f"\nSpec path: `{spec_path}`\n"
            f"Subtasks path: `{subtasks_path}`\n\n"
            f"The tasks are now in the queue and will be picked up by the coding agents. "
            f"You can track progress in Mission Control → Projects."
        )

        return ToolResult(output="\n".join(lines), success=True)

    # ── Action: list ─────────────────────────────────────────────────────

    async def _list(self) -> ToolResult:
        """List all interview sessions."""
        base = Path(self._outputs_dir)
        if not base.exists():
            return ToolResult(output="No interview sessions found.", success=True)

        sessions = []
        for d in base.iterdir():
            if d.is_dir():
                project_json = d / "PROJECT.json"
                if project_json.exists():
                    try:
                        async with aiofiles.open(project_json) as f:
                            data = json.loads(await f.read())
                        sessions.append(data)
                    except (json.JSONDecodeError, OSError):
                        continue

        if not sessions:
            return ToolResult(output="No interview sessions found.", success=True)

        lines = ["## Project Interview Sessions\n"]
        for s in sorted(sessions, key=lambda x: x.get("created_at", 0), reverse=True):
            lines.append(
                f"- **{s.get('id', '?')}** — {s.get('status', '?')} | "
                f"{s.get('project_type', '?')} | {s.get('complexity', '?')} | "
                f"v{s.get('spec_version', 0)}"
            )
            desc = s.get("description", "")
            if desc:
                lines.append(f"  {desc[:80]}...")

        return ToolResult(output="\n".join(lines), success=True)

    # ── Internal helpers ─────────────────────────────────────────────────

    def _project_dir(self, project_id: str) -> Path:
        """Get the directory for a project's data."""
        d = Path(self._outputs_dir) / project_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def _save_project(self, project_id: str, data: dict):
        """Persist project data to PROJECT.json."""
        path = self._project_dir(project_id) / "PROJECT.json"
        async with aiofiles.open(path, "w") as f:
            await f.write(json.dumps(data, indent=2, default=str))

    async def _load_project(self, project_id: str) -> dict | None:
        """Load project data from PROJECT.json."""
        path = self._project_dir(project_id) / "PROJECT.json"
        if not path.exists():
            return None
        try:
            async with aiofiles.open(path) as f:
                return json.loads(await f.read())
        except (json.JSONDecodeError, OSError) as e:
            logger.error(f"Failed to load project {project_id}: {e}")
            return None

    async def _extract_answers(self, theme: str, questions: list[str], response: str) -> dict:
        """Extract structured answers from a user's response via LLM.

        Falls back to basic extraction if LLM is unavailable.
        """
        if self._router:
            try:
                return await self._llm_extract(theme, questions, response)
            except Exception as e:
                logger.warning(f"LLM answer extraction failed: {e}")

        return self._basic_extract(questions, response)

    async def _llm_extract(self, theme: str, questions: list[str], response: str) -> dict:
        """Use LLM to extract structured answers."""
        numbered_questions = "\n".join(f"{i + 1}. {q}" for i, q in enumerate(questions))
        prompt = ANSWER_EXTRACTION_PROMPT.format(
            theme=theme,
            questions=numbered_questions,
            response=response,
        )

        messages = [
            {"role": "system", "content": prompt},
            {"role": "user", "content": "Extract answers from the response above."},
        ]

        result = await self._router.complete(
            "or-free-mistral-small", messages, temperature=0.1, max_tokens=1000
        )

        # Parse JSON response
        text = result.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            text = "\n".join(lines[1:])
            if text.endswith("```"):
                text = text[:-3]
            text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            logger.warning(f"Failed to parse extraction response: {text[:200]}")
            return self._basic_extract(questions, response)

    @staticmethod
    def _basic_extract(questions: list[str], response: str) -> dict:
        """Fallback: basic answer extraction without LLM."""
        answers = {}
        for i, _q in enumerate(questions):
            answers[f"q{i + 1}"] = response if i == 0 else "see full response"

        return {
            "answers": answers,
            "vague_questions": [],
            "follow_up_needed": False,
            "follow_up_questions": [],
            "key_insights": [response[:200]] if response else [],
        }
